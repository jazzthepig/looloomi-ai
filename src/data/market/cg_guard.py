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

## 闸门之外(S-895 阶段 0)

闸门只数**它自己放行**的请求。闸门之外的裸 client 打出去的调用,`used_today`
一概看不见 —— 于是「今天花了多少」这个数**从第一天起就是残缺的**(只数闸门内的
11 个文件)。这不是「数得不准」,是**数的东西不是那件事**。

`note_unbudgeted_call` 是**记账,不是闸门**:它不拦任何请求,只把闸门外的消耗
记进同一张表,好让 `/internal/cg-quota` 报出**真实总量**
(`used_today + unbudgeted_today`)。阶段 2 把裸 client 收口进闸门之后,这些
记账行**必须同时删掉** —— 闸门已经在数了,再记一次就是双计。
`tests/test_cg_call_sites.py` 守这条不变量。

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

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

# ── 模块别名 ─────────────────────────────────────────────────────────────────
#
# 仓库里两种 import 写法都在用(`src/api/main.py:30-38` 的双路径说明):
# `src.data.market.cg_guard` 与 `data.market.cg_guard`。Python 会把它们当成
# **两个不同的模块对象** —— 各自一份进程内计数(`_local_unbudgeted`)、
# 各自一个 Redis client。Redis 计数仍然对(同一个键),但 **Redis 写失败时,
# 读数会漏掉另一半** ⇒ 少报 = 因错误理由变绿。
#
# 所以在这里把两个名字**钉到同一个模块对象**上:谁先被 import 都不重要。
# 这个别名是本模块的**不变量**:全进程只有一份账。
_this = sys.modules[__name__]
sys.modules.setdefault("src.data.market.cg_guard", _this)
sys.modules.setdefault("data.market.cg_guard", _this)

# ── 配置 ─────────────────────────────────────────────────────────────────────

#: Analyst 档 ≈ 500,000 次/月 ≈ 16,600 次/日。取 16,000 留 4% 余量。
DEFAULT_DAILY_BUDGET = 16_000

#: 收到 429 / 5xx 之后开闸多久。300s = 5 分钟,足够限额窗口(1 分钟)滚过去。
DEFAULT_BREAKER_COOLDOWN_S = 300

#: 收到 **401 / 403**(账号 / 授权态被拒)之后开闸多久。默认 6 小时。
#:
#: 为什么授权拒绝要开得比限流久得多(2026-11-21 加):**授权拒绝不是暂时故障**。
#: 429 会自己滚过去(限额窗口 1 分钟),401/403 不会 —— 订阅没恢复之前,重试一千次
#: 也是被拒一千次,**而每一次都是一次可能计费的请求**。
#: ⇒ 6 小时 = 一天探 4 次:既能自己醒过来,又不会在被拒期间烧钱。
#: ⚠ 这条存在的**直接起因**:2026-11-21 发现 CoinGecko 整片暗,而根因是
#: **账号方自己停了订阅**(Jazz,计划 12-01 恢复)。旧语义下 401 **不开闸**
#: ⇒ 闸门照样放行每一次请求 ⇒ 每一次都在为一个必然失败的请求付费。
DEFAULT_AUTH_COOLDOWN_S = 21_600

_USED_KEY_PREFIX = "cg:quota:used:"
_BREAKER_KEY = "cg:quota:breaker"
_BUDGET_KEY = "cg:quota:budget"
_TRIED_KEY = "cg:quota:tripped"

#: 闸门外消耗(S-895 阶段 0)。计数器与分端点明细各一个键。
_UNBUDGETED_KEY_PREFIX = "cg:quota:unbudgeted:"
_UNBUDGETED_EP_KEY_PREFIX = "cg:quota:unbudgeted_ep:"

_UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

_redis_http: Optional[httpx.AsyncClient] = None
_redis_sync_http: Optional[httpx.Client] = None


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _used_key(day: Optional[str] = None) -> str:
    return f"{_USED_KEY_PREFIX}{day or _today_utc()}"


def _unbudgeted_key(day: Optional[str] = None) -> str:
    return f"{_UNBUDGETED_KEY_PREFIX}{day or _today_utc()}"


def _unbudgeted_ep_key(day: Optional[str] = None) -> str:
    return f"{_UNBUDGETED_EP_KEY_PREFIX}{day or _today_utc()}"


# ── 进程内状态(Redis 不可用时的兜底,也是 Redis 之前的快速路径)───────────────

_local_used: dict[str, int] = {}      # day → count
_local_breaker_until: float = 0.0     # unix ts
_local_breaker_reason: str = ""       # 为什么开的闸(见下)
_local_tripped: int = 0

#: 闸门外消耗的本进程账。Redis 写失败时,它是唯一还看得见的真相。
_local_unbudgeted: dict[str, int] = {}          # day → count
_local_unbudgeted_ep: dict[str, dict[str, int]] = {}   # day → {source:endpoint → count}

#: 异步记账的后台任务(强引用,否则会被 GC 掉,任务永不落地)。
_pending_unbudgeted: set = set()


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


def _get_redis_sync_http() -> httpx.Client:
    """同步版 Redis 客户端 —— 只给**没有事件循环**的调用点用(两个 `requests`
    调用点)。Upstash 的 pipeline 是一发 HTTP,几十毫秒,可以接受。"""
    global _redis_sync_http
    if _redis_sync_http is None:
        _redis_sync_http = httpx.Client(timeout=5)
    return _redis_sync_http


def _r_pipeline_sync(cmds: list[list]) -> Any:
    """同步版 pipeline(与 `_r_pipeline` 同一形状)。"""
    if not _UPSTASH_URL:
        return None
    try:
        r = _get_redis_sync_http().post(
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


async def _r_hgetall(key: str) -> dict:
    """读一个 hash。读不到(未配置 / 出错)返回 `{}`。"""
    if not _UPSTASH_URL:
        return {}
    try:
        r = await _get_redis_http().get(
            f"{_UPSTASH_URL}/hgetall/{key}",
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
        )
        if r.status_code == 200:
            return _coerce_hash((r.json() or {}).get("result"))
    except Exception:
        pass
    return {}


def _coerce_hash(res: Any) -> dict:
    """Upstash 的 HGETALL 返回形状在不同版本里不一样 —— 有的是 dict,
    有的是扁平的 `[k1, v1, k2, v2…]`。两种都收,免得读数因为一个版本差异
    变成 0(**因错误理由变绿的检查比红的更坏**)。"""
    if isinstance(res, dict):
        return {str(k): res[k] for k in res}
    if isinstance(res, list):
        out: dict = {}
        for i in range(0, len(res) - 1, 2):
            out[str(res[i])] = res[i + 1]
        return out
    return {}


#: `/coins/` 下面是**集合**端点,不是单币端点 —— 不能把 `markets` / `list`
#: 当成 coin id 归一,否则「拉全市场」和「拉单个币」会被混成同一个标签。
_COIN_SUBPATHS = {"markets", "list", "categories", "new", "trending"}


def endpoint_label(url: str) -> str:
    """把一个 CoinGecko URL 归一成**端点标签** —— `/coins/{id}/market_chart`。

    为什么要有这个:记账要按端点分组,而同一个端点的 URL 里带着**不同的
    coin id**(`/coins/bitcoin/…` vs `/coins/ethereum/…`)。不归一的话,分端点
    明细会变成「每个币一行」,读数没法用。

    归一规则:
      ① 砍掉 host 与 `/api/v3` 前缀;
      ② `/coins/<某个 id>` 里的 id 换成 `{id}`(**集合**端点除外 ——
         `/coins/markets` 是全市场,不是「叫 markets 的那个币」);
      ③ 其余原样(查询参数不进标签 —— 同一端点的参数变体是**同一个额度池**)。
    """
    s = str(url or "").strip()
    if not s:
        return "(unknown)"
    # 砍掉 scheme://host
    if "://" in s:
        s = s.split("://", 1)[1]
        s = s.split("/", 1)[1] if "/" in s else ""
    # 砍掉 `/api/v3`
    for pre in ("api/v3/", "api/v3"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    s = "/" + s.lstrip("/")
    # `/coins/<id>` → `/coins/{id}`
    parts = s.split("/")
    if len(parts) >= 3 and parts[1] == "coins" and parts[2] and parts[2] not in _COIN_SUBPATHS:
        parts[2] = "{id}"
        s = "/".join(parts)
    # 去掉查询串
    s = s.split("?", 1)[0]
    return s or "(unknown)"


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
    """熔断是否开着,以及为什么。

    ⚠ **本地原因必须一起返回**(2026-11-21 修):原来本地快路径一律返回
    `"cooldown"` —— 于是 `/internal/cg-quota` 的 `breaker_reason` 在生产上
    **永远看不到真正的理由**(是 429?是 5xx?还是 401 授权态?)。2026-11-21
    那次整片暗,最难的一步就是**分不清是哪一种**;一个只说「冷却中」的读数
    在那种时候等于没有读数。
    """
    now = time.time()
    if _local_breaker_until > now:
        return True, _local_breaker_reason or "cooldown"
    r = await _r_get(_BREAKER_KEY)
    if r:
        return True, str(r)
    return False, ""


async def trip_breaker(reason: str, cooldown_s: Optional[int] = None) -> None:
    """开闸。冷却期内所有 CoinGecko 请求短路。

    `cooldown_s` 省略时用普通冷却(429 / 5xx ⇒ 300s);**授权拒绝(401/403)用
    `auth_cooldown_s()`**(默认 6h)—— 授权态不会在 5 分钟内自己好。
    """
    global _local_tripped, _local_breaker_until, _local_breaker_reason
    _local_tripped += 1
    cd = int(cooldown_s) if cooldown_s else breaker_cooldown_s()
    _local_breaker_until = time.time() + cd
    _local_breaker_reason = str(reason)[:120]
    try:
        await _r_set(_BREAKER_KEY, reason[:120], cd)
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


def auth_cooldown_s() -> int:
    """授权拒绝(401/403)之后的冷却秒数。默认 6 小时。

    ⚠ **不要用 0 / 负数表达「关掉」** —— 冷却为 0 等于没开闸。改用
    `CG_AUTH_COOLDOWN_S` 调小(比如 300 = 5 分钟),而不是设 0。
    """
    raw = (os.getenv("CG_AUTH_COOLDOWN_S", "") or "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    return DEFAULT_AUTH_COOLDOWN_S


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


# ── 闸门外的记账(S-895 阶段 0)──────────────────────────────────────────────

def note_unbudgeted_call(source: str, endpoint: str) -> None:
    """记一次**闸门外**的 CoinGecko 调用。

    ⚠️ 这是**记账,不是闸门** —— 它不拦任何请求、不改任何返回值。存在的唯一
    理由:`used_today` 只数闸门内的消耗,闸门外的部分不进账 ⇒ 「今天花了多少」
    一直是不完整的(S-895 阶段 0)。

    **同步函数** —— 同步(`requests`)和异步(`httpx`)调用点都能用同一个形状。

    ⚠️ **阶段 2 把调用点收口进 `GuardedCGClient` 之后,这一行必须同时删掉** ——
    闸门已经在数了,再记一次就是双计。`tests/test_cg_call_sites.py` 守这条。
    """
    day = _today_utc()
    field = f"{source}:{endpoint}"
    _local_unbudgeted[day] = _local_unbudgeted.get(day, 0) + 1
    eps = _local_unbudgeted_ep.setdefault(day, {})
    eps[field] = eps.get(field, 0) + 1
    _flush_unbudgeted(day, field)


def _unbudgeted_cmds(day: str, field: str) -> list[list]:
    k = _unbudgeted_key(day)
    ek = _unbudgeted_ep_key(day)
    return [
        ["INCR", k],
        ["EXPIRE", k, "259200"],       # 3 天
        ["HINCRBY", ek, field, "1"],
        ["EXPIRE", ek, "259200"],
    ]


def _flush_unbudgeted(day: str, field: str) -> None:
    """把一条记账写进 Redis。

    异步上下文里用**后台任务**(不拖慢调用点);同步上下文(两个 `requests`
    调用点)里没有事件循环,只能同步写一发 —— Upstash pipeline 几十毫秒,
    这些调用点一天才几百次,可以接受。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(_r_pipeline(_unbudgeted_cmds(day, field)))
        _pending_unbudgeted.add(task)
        task.add_done_callback(_pending_unbudgeted.discard)
        return
    try:
        _r_pipeline_sync(_unbudgeted_cmds(day, field))
    except Exception:
        pass


async def unbudgeted_today() -> int:
    """今天**闸门外**的调用次数。"""
    day = _today_utc()
    remote: Optional[int] = None
    r = await _r_get(_unbudgeted_key(day))
    if r is not None:
        try:
            remote = int(r)
        except (TypeError, ValueError):
            remote = None
    local = int(_local_unbudgeted.get(day, 0))
    # 取**较大**者:Redis 写失败时,本进程那份仍然是真的。宁可报多(让人去查)
    # 也不报少 —— 少报 = 因错误理由变绿。
    return max(remote or 0, local)


async def unbudgeted_endpoints() -> dict:
    """闸门外消耗的**分端点**明细:`{"coingecko:/coins/markets": 128, …}`。"""
    day = _today_utc()
    merged: dict[str, int] = {}
    for k, v in (await _r_hgetall(_unbudgeted_ep_key(day))).items():
        try:
            merged[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    for k, v in _local_unbudgeted_ep.get(day, {}).items():
        merged[k] = max(merged.get(k, 0), int(v))
    return merged


async def report() -> dict:
    """当前额度状态 —— `/internal/cg-quota` 返回的就是它。"""
    budget = await effective_budget()
    used = await used_today()
    open_, why = await breaker_state()
    tripped = await _r_get(_TRIED_KEY)
    unbudgeted = await unbudgeted_today()
    endpoints = await unbudgeted_endpoints()
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
        # ── 闸门外(S-895 阶段 0)。之前这个数**不存在** ⇒ 「今天花了多少」
        # 一直是残缺的:它只数闸门内的 11 个文件,闸门外的 12 处裸 client
        # 一发都不进账。`total_calls_today` 才是**今天的真实总量**。
        "unbudgeted_today": unbudgeted,
        "unbudgeted_endpoints": endpoints,
        "unbudgeted_total": sum(endpoints.values()),
        "total_calls_today": used + unbudgeted,
        "note": ("计数走 Redis ⇒ 跨进程共享;没有 Redis 时每个进程各有一份预算"
                 "(仍然有界,但更松)。"
                 "`used_today` 只数闸门内的消耗;闸门外的在 `unbudgeted_today`"
                 "里,`total_calls_today` 是两者之和。"),
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
        if resp.status_code in (401, 403):
            # 授权 / 计划态被拒 —— **不是暂时故障**,重试只会再被拒一次,
            # 而每一次都是一次可能计费的请求 ⇒ 开**长**闸(默认 6h)。
            await trip_breaker(f"HTTP {resp.status_code} auth/plan rejected",
                               cooldown_s=auth_cooldown_s())
        elif resp.status_code == 429 or resp.status_code >= 500:
            await trip_breaker(f"HTTP {resp.status_code}")
        return resp
