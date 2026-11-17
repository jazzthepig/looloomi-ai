"""
CoinGecko 调用闸门 —— 日预算 + 熔断 + 计数(S-894,2026-11-17)。

## 为什么需要它

2026-11-17 起 CoinGecko 的**超额计费打开**:超出 Analyst 档的每一次调用都要真金白银。
在这之前,「多调几次」的代价只是 429;现在 429 和「扣钱」是同一件事的两面 —— **限额
用尽之后,每一次重试都是一次付费调用**。而我们原来的行为恰恰是「429 当成没数据」,
下一轮照打不误:熔断不存在,预算不存在,也没有人知道今天到底花了多少。

所以闸门是**唯一收口点**,做三件事:

① **日预算**(`CG_DAILY_BUDGET`,默认 16,000 次/UTC 日 ≈ Analyst 档 500,000/月 的
   95% 不到,留出余量)。超了就不再发外部请求 —— 宁可返回「没有数据」,也不发一记
   付费请求。预算可以用 Redis 键 `cg:quota:budget` 在线改(不用重新部署)。

② **熔断**(`CG_BREAKER_COOLDOWN_S`,默认 300s)。收到 429 或 5xx 之后开闸,期间
   **一次 CoinGecko 请求都不发**,直接返回带原因的 503。原来的行为是「429 → 空
   数据 → 下一轮再打」,于是限额用尽之后每一轮都在烧钱。

③ **计数**。每次请求记一次,写进 Redis 的当日计数(跨进程共享)。想知道今天花了
   多少:`GET /internal/cg-quota`。**计数不是日志,是闸门本身** —— 它决定还要不要
   发下一次请求。

## 口径

`GuardedCGClient` 是 `httpx.AsyncClient` 的**子类**,不是包装器 —— 因为仓库里
到处都在用 `isinstance` / `async with` / 直接构造 `httpx.AsyncClient`。子类覆写
`request()`(httpx 的 `.get()` / `.post()` 全部经过它),于是**一处收口,全覆盖**,
且不改变任何调用点的形状。

拒绝时返回的是一个**合成的 503 响应**,而不是异常:
`raise_for_status()` 会照常抛(于是既有代码的 `except` 分支照常兜底),
`r.json()` 返回 `{"error": "coingecko_guard", "reason": ...}`(于是既有代码不会
把拒绝当成「数据是空的」而静默写库)。

## Redis

自己带一份极小的 Upstash 访问(GET / INCR+EXPIRE / SET),**不 import
data_layer** —— data_layer 要 import 本模块,反向 import 就是循环依赖。

没有 Redis 时退回**进程内计数**:每个进程各有一份预算,比共享预算松,但仍然有界。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

# ── 配置 ─────────────────────────────────────────────────────────────────────

#: Analyst 档 ≈ 500,000 次/月 ≈ 16,600 次/日。取 16,000 留 4% 余量。
DEFAULT_DAILY_BUDGET = 16_000

#: 收到 429 / 5xx 之后开闸多久。300s = 5 分钟,足够限额窗口(1 分钟)滚过去。
DEFAULT_BREAKER_COOLDOWN_S = 300

_USED_KEY_PREFIX = "cg:quota:used:"
_BREAKER_KEY = "cg:quota:breaker"
_BUDGET_KEY = "cg:quota:budget"
_TRIED_KEY = "cg:quota:tripped"

_UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

_redis_http: Optional[httpx.AsyncClient] = None


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _used_key(day: Optional[str] = None) -> str:
    return f"{_USED_KEY_PREFIX}{day or _today_utc()}"


# ── 进程内状态(Redis 不可用时的兜底,也是 Redis 之前的快速路径)───────────────

_local_used: dict[str, int] = {}      # day → count
_local_breaker_until: float = 0.0     # unix ts
_local_tripped: int = 0


# ── 极小 Redis 访问(不 import data_layer,避免循环依赖)────────────────────────

def _get_redis_http() -> httpx.AsyncClient:
    global _redis_http
    if _redis_http is None or _redis_http.is_closed:
        _redis_http = httpx.AsyncClient(timeout=5,
                                        limits=httpx.Limits(max_connections=10))
    return _redis_http


async def _r_get(key: str) -> Any:
    """读一个键。读不到(未配置 / 出错)返回 None。"""
    if not _UPSTASH_URL:
        return None
    try:
        r = await _get_redis_http().get(
            f"{_UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
        )
        if r.status_code == 200:
            raw = (r.json() or {}).get("result")
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return raw
    except Exception:
        pass
    return None


async def _r_pipeline(cmds: list[list]) -> Any:
    """Upstash pipeline。返回 result 数组;失败返回 None。"""
    if not _UPSTASH_URL:
        return None
    try:
        r = await _get_redis_http().post(
            f"{_UPSTASH_URL}/pipeline",
            content=json.dumps(cmds),
            headers={
                "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        if r.status_code == 200:
            return (r.json() or {}).get("result")
    except Exception:
        pass
    return None


async def _r_set(key: str, val: str, ttl: int) -> bool:
    cmds = [["SET", key, val]]
    if ttl and ttl > 0:
        cmds.append(["EXPIRE", key, str(ttl)])
    res = await _r_pipeline(cmds)
    return bool(res)


# ── 闸门本体 ─────────────────────────────────────────────────────────────────

async def effective_budget() -> int:
    """日预算。优先级:Redis 在线覆盖 > 环境变量 > 默认值。

    Redis 覆盖(`cg:quota:budget`)是为了让 Jazz 不重新部署就能改预算。
    """
    over = await _r_get(_BUDGET_KEY)
    if over is not None:
        try:
            n = int(over)
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
    raw = (os.getenv("CG_DAILY_BUDGET", "") or "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    return DEFAULT_DAILY_BUDGET


async def used_today() -> int:
    """今天已用的调用次数。Redis 优先,退回进程内计数。"""
    day = _today_utc()
    r = await _r_get(_used_key(day))
    if r is not None:
        try:
            return int(r)
        except (TypeError, ValueError):
            pass
    return int(_local_used.get(day, 0))


async def _bump_used() -> int:
    """计数 +1。返回新的计数(Redis 成功时是权威值)。"""
    day = _today_utc()
    _local_used[day] = _local_used.get(day, 0) + 1
    res = await _r_pipeline([["INCR", _used_key(day)],
                              ["EXPIRE", _used_key(day), "259200"]])   # 3 天
    if isinstance(res, list) and res:
        first = res[0]
        if isinstance(first, (int, float)):
            return int(first)
    return int(_local_used[day])


async def breaker_state() -> tuple[bool, str]:
    """熔断是否开着,以及为什么。"""
    now = time.time()
    if _local_breaker_until > now:
        return True, "cooldown"
    r = await _r_get(_BREAKER_KEY)
    if r:
        return True, str(r)
    return False, ""


async def trip_breaker(reason: str) -> None:
    """开闸。冷却期内所有 CoinGecko 请求短路。"""
    global _local_tripped, _local_breaker_until
    _local_tripped += 1
    _local_breaker_until = time.time() + breaker_cooldown_s()
    try:
        await _r_set(_BREAKER_KEY, reason[:120], breaker_cooldown_s())
        await _r_pipeline([["INCR", _TRIED_KEY]])
    except Exception:
        pass


def breaker_cooldown_s() -> int:
    raw = (os.getenv("CG_BREAKER_COOLDOWN_S", "") or "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    return DEFAULT_BREAKER_COOLDOWN_S


async def admit() -> tuple[bool, str]:
    """能不能再发一次 CoinGecko 请求?返回 (允许, 原因)。

    顺序很重要:**先看熔断,再看预算**。熔断是「上游正在拒绝我们」,那是更紧急的
    事实;预算用完了也只是「今天到此为止」。
    """
    open_, why = await breaker_state()
    if open_:
        return False, f"breaker_open:{why or 'unknown'}"
    budget = await effective_budget()
    used = await used_today()
    if used >= budget:
        return False, f"budget_exhausted:{used}/{budget}"
    return True, ""


async def spend() -> int:
    """记一次调用。返回今日累计。"""
    return await _bump_used()


async def report() -> dict:
    """当前额度状态 —— `/internal/cg-quota` 返回的就是它。"""
    budget = await effective_budget()
    used = await used_today()
    open_, why = await breaker_state()
    tripped = await _r_get(_TRIED_KEY)
    return {
        "used_today": used,
        "daily_budget": budget,
        "remaining": max(0, budget - used),
        "pct_used": round(100.0 * used / budget, 2) if budget else None,
        "day_utc": _today_utc(),
        "breaker_open": bool(open_),
        "breaker_reason": why or None,
        "breaker_cooldown_s": breaker_cooldown_s(),
        "trips_total": int(tripped) if isinstance(tripped, (int, float)) else _local_tripped,
        "redis_shared": bool(_UPSTASH_URL),
        "note": ("计数走 Redis ⇒ 跨进程共享;没有 Redis 时每个进程各有一份预算"
                 "(仍然有界,但更松)。"),
    }


# ── 受闸门约束的 HTTP 客户端 ────────────────────────────────────────────────

def denied_response(method: str, url: str, reason: str) -> httpx.Response:
    """闸门拒绝时返回的**合成 503**。

    做成响应而不是异常,是因为调用点遍布全仓库,抛异常会打断它们各自的
    降级分支(`except` / `stale` / `[]`)。合成体带 `request=`,于是
    `raise_for_status()` 照常抛 —— 既有代码一句都不用改。
    """
    try:
        req = httpx.Request(method, url)
    except Exception:                                   # noqa: BLE001
        req = httpx.Request("GET", "https://coingecko.invalid/")
    return httpx.Response(
        503,
        json={"error": "coingecko_guard", "reason": reason},
        request=req,
    )


class GuardedCGClient(httpx.AsyncClient):
    """`httpx.AsyncClient` + 预算/熔断。

    覆写 `request()` —— httpx 的 `.get()` / `.post()` / `.put()` 全部经过它,
    所以**一处收口,全覆盖**,而调用点的形状一点没变(仍然是
    `httpx.AsyncClient`,仍然可以 `async with`)。
    """

    async def request(self, method, url, *args, **kwargs):   # type: ignore[override]
        allowed, why = await admit()
        if not allowed:
            return denied_response(method, str(url), why)
        # 记账放在**发请求之前**:请求失败不代表 CoinGecko 没收到,而我们无法
        # 区分。宁可多记一次(预算早用完一点),不可漏记(超额扣费)。
        await spend()
        try:
            resp = await super().request(method, url, *args, **kwargs)
        except Exception:
            raise
        if resp.status_code == 429 or resp.status_code >= 500:
            await trip_breaker(f"HTTP {resp.status_code}")
        return resp
