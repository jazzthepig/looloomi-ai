"""
CoinMarketCap 兜底层 —— 免费档、自带日预算(S-894,2026-11-17)。

## 它为什么存在

2026-11-17 起 CoinGecko 的**超额计费打开**:超出 Analyst 档的调用要真金白银。
CoinGecko 闸门(`src/data/market/cg_guard.py`)负责**把总量按在天内**;CMC 负责
**在闸门关上的时候,让最重要的两个面还有数据**。

Jazz 在 Railway 上补了把 CMC 的免费 key。免费档有**自己的**日调用上限,而且我们
**不知道**那个上限是多少 —— 所以本模块**自己计数**:Redis 里一个当日计数,
默认 40 次/天(`CMC_DAILY_BUDGET`)。用完就停,不试、不撞、不因为「还剩一点」
就多打一发把免费档也撞穿。

## 覆盖哪些面

只有两个,因为只有这两个值得用另一家 vendor 兜:

① `/v1/global-metrics/quotes/latest` → 总市值、BTC 占比、总成交量。
   对应 CoinGecko 的 `/global`。
② `/v1/cryptocurrency/quotes/latest?symbol=...` → 单个/多个标的的现价、市值、
   24h 涨跌。对应 CoinGecko 的 `/coins/markets` 与 `/simple/price`。
   **按 symbol 请求**(CMC 的 id / slug 映射要另一次调用,而 symbol 是我们
   手里本来就有的)。

## 口径

**CMC 不是 CoinGecko 的等价物** —— 两家的市值口径、纳入的币种集合都有差异。
所以 CMC 的返回值**一律带 `source: "coinmarketcap"`**,调用方在降级时把来源
带出去(前端 / 日志 / 台账都能看见)。**不静默换源**:换了源却不标,数字看着
一样、其实不是一回事 —— 这比没有数据更难发现。

CMC 的错误码里,「额度/积分耗尽」这一族是 1001 / 1002 / 1008 / 1009 / 1010 /
1011 —— 撞到其中任何一个,本模块**今天就不再试**(写一个到当日结束的
Redis 标记),而不是下一轮再撞一次。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

#: 免费档的日预算。宁可少用 —— 撞穿免费档是要账号的。
DEFAULT_DAILY_BUDGET = 40

#: CMC 的「额度/积分耗尽」错误码族。
LIMIT_ERROR_CODES = {1001, 1002, 1008, 1009, 1010, 1011}

CMC_BASE = "https://pro-api.coinmarketcap.com/v1"

_USED_KEY_PREFIX = "cmc:quota:used:"
_BLOCKED_KEY = "cmc:quota:blocked"

_UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

_http: Optional[httpx.AsyncClient] = None
_local_used: dict[str, int] = {}
#: 「今天停用」的本地兜底(没有 Redis 时)。0 = 没停用。
_local_blocked_until: float = 0.0


def _api_key() -> str:
    """CMC 的 key —— 三个名字都认。

    Jazz 在 Railway 上补 key 时用的是哪个名字没人记录过(而且不同文档用不同
    名字),所以三个都收:谁在,谁生效,不用为了一个环境变量名再发一次版。
    """
    for name in ("CMC_API_KEY", "COINMARKETCAP_API_KEY", "CMC_PRO_API_KEY"):
        v = (os.getenv(name, "") or "").strip()
        if v:
            return v
    return ""


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def daily_budget() -> int:
    raw = (os.getenv("CMC_DAILY_BUDGET", "") or "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    return DEFAULT_DAILY_BUDGET


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=12,
                                  limits=httpx.Limits(max_connections=10))
    return _http


# ── 极小 Redis 访问(与 cg_guard 同形,刻意不共享模块:两个闸门互不相干)──────

async def _r_get(key: str) -> Any:
    if not _UPSTASH_URL:
        return None
    try:
        r = await _get_http().get(
            f"{_UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"})
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
    if not _UPSTASH_URL:
        return None
    try:
        r = await _get_http().post(
            f"{_UPSTASH_URL}/pipeline",
            content=json.dumps(cmds),
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}",
                     "Content-Type": "application/json"})
        if r.status_code == 200:
            return (r.json() or {}).get("result")
    except Exception:
        pass
    return None


async def _r_set(key: str, val: str, ttl: int) -> bool:
    cmds = [["SET", key, val]]
    if ttl and ttl > 0:
        cmds.append(["EXPIRE", key, str(ttl)])
    return bool(await _r_pipeline(cmds))


# ── 预算 ─────────────────────────────────────────────────────────────────────

async def used_today() -> int:
    day = _today_utc()
    r = await _r_get(f"{_USED_KEY_PREFIX}{day}")
    if r is not None:
        try:
            return int(r)
        except (TypeError, ValueError):
            pass
    return int(_local_used.get(day, 0))


async def blocked_today() -> bool:
    """今天是否已经因为撞到额度错误码而停用。"""
    if _local_blocked_until > time.time():
        return True
    return bool(await _r_get(_BLOCKED_KEY))


async def admit() -> tuple[bool, str]:
    key = _api_key()
    if not key:
        return False, "no_cmc_key"
    if await blocked_today():
        return False, "cmc_quota_blocked_today"
    budget = daily_budget()
    used = await used_today()
    if used >= budget:
        return False, f"cmc_budget_exhausted:{used}/{budget}"
    return True, ""


async def _spend() -> None:
    day = _today_utc()
    _local_used[day] = _local_used.get(day, 0) + 1
    await _r_pipeline([["INCR", f"{_USED_KEY_PREFIX}{day}"],
                       ["EXPIRE", f"{_USED_KEY_PREFIX}{day}", "259200"]])


async def _block_rest_of_day(reason: str) -> None:
    """撞到额度错误码 → 今天不再试(到当日结束为止)。"""
    global _local_blocked_until
    now = datetime.now(timezone.utc)
    # 到次日 UTC 00:00 再多留 5 分钟,覆盖跨零点的请求
    secs = int((24 * 3600 - now.hour * 3600 - now.minute * 60 - now.second)) + 300
    # 本地兜底必须有 —— Redis 写失败时,「今天停用」不能跟着一起失效,
    # 否则每一轮都再撞一次额度(那正是这个模块要防的事)。
    _local_blocked_until = time.time() + secs
    await _r_set(_BLOCKED_KEY, reason[:120], secs)


# ── 请求 ─────────────────────────────────────────────────────────────────────

async def _get(path: str, params: dict) -> Optional[dict]:
    """打一次 CMC。返回解析后的 JSON;不可用返回 None(带原因写进日志)。"""
    allowed, why = await admit()
    if not allowed:
        return None
    key = _api_key()
    await _spend()
    try:
        r = await _get_http().get(
            f"{CMC_BASE}{path}",
            params=params,
            headers={"X-CMC_PRO_API_KEY": key, "Accept": "application/json"})
    except Exception:
        return None
    if r.status_code != 200:
        try:
            body = r.json() or {}
        except Exception:
            body = {}
        code = None
        if isinstance(body, dict):
            st = body.get("status") or {}
            if isinstance(st, dict):
                # CMC 的错误体:`{"status": {"error_code": 1001, "error_message": "..."}}`。
                # 历史上也用过 `code`,两个都认。
                code = st.get("error_code")
                if code is None:
                    code = st.get("code")
        if code in LIMIT_ERROR_CODES:
            await _block_rest_of_day(f"cmc_error_{code}")
        return None
    try:
        return r.json() or {}
    except Exception:
        return None


# ── 对外面 ───────────────────────────────────────────────────────────────────

async def cmc_quotes(symbols: list[str]) -> dict:
    """`/v1/cryptocurrency/quotes/latest` —— 按 symbol。

    返回 `{SYMBOL: {"price": float, "market_cap": float, "volume_24h": float,
    "percent_change_24h": float, "source": "coinmarketcap"}}`。
    拿不到就返回 `{}` —— **空字典 = 没有数据**,不返回编出来的 0。
    """
    syms = [s.strip().upper() for s in (symbols or []) if s and s.strip()]
    if not syms:
        return {}
    # CMC 单次最多 100 个 symbol。
    out: dict[str, dict] = {}
    for i in range(0, len(syms), 100):
        chunk = syms[i:i + 100]
        body = await _get("/cryptocurrency/quotes/latest",
                          {"symbol": ",".join(chunk), "convert": "USD"})
        data = (body or {}).get("data") or {}
        if not isinstance(data, dict):
            continue
        for sym, row in data.items():
            if not isinstance(row, dict):
                continue
            q = ((row.get("quote") or {}).get("USD") or {})
            out[str(sym).upper()] = {
                "id": row.get("id"),
                "name": row.get("name"),
                "symbol": str(sym).upper(),
                "price": q.get("price"),
                "market_cap": q.get("market_cap"),
                "volume_24h": q.get("volume_24h"),
                "percent_change_24h": q.get("percent_change_24h"),
                "percent_change_7d": q.get("percent_change_7d"),
                "last_updated": row.get("last_updated"),
                "source": "coinmarketcap",
            }
    return out


async def cmc_global_metrics() -> dict:
    """`/v1/global-metrics/quotes/latest` —— 总市值 / BTC 占比 / 总成交量。

    字段名与 CoinGecko 的 `/global` **不对齐**(口径也不同),所以这里给的是
    CMC 自己的形状,由调用方显式改名 —— 不做一个「看起来一样」的适配器,
    那样会把两家的口径差异藏起来。
    """
    body = await _get("/global-metrics/quotes/latest", {"convert": "USD"})
    data = (body or {}).get("data") or {}
    if not isinstance(data, dict) or not data:
        return {}
    quote = data.get("quote") or {}
    usd = quote.get("USD") or {}
    return {
        "total_market_cap_usd": usd.get("total_market_cap"),
        "total_volume_24h_usd": usd.get("total_volume"),
        "total_market_cap_change_24h_pct": usd.get("total_market_cap_change_percentage_24h_usd"),
        "btc_dominance_pct": data.get("btc_dominance"),
        "btc_dominance_change_24h_pp": data.get("btc_dominance_change_percentage_24h"),
        "active_cryptocurrencies": data.get("active_cryptocurrencies"),
        "markets": data.get("markets"),
        "source": "coinmarketcap",
    }


async def report() -> dict:
    """CMC 侧的额度状态(`/internal/cg-quota` 一并返回)。"""
    key = _api_key()
    used = await used_today()
    budget = daily_budget()
    return {
        "key_present": bool(key),
        "used_today": used,
        "daily_budget": budget,
        "remaining": max(0, budget - used),
        "blocked_today": await blocked_today(),
        "redis_shared": bool(_UPSTASH_URL),
    }
