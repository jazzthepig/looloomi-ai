"""Deribit DVOL(BTC / ETH 隐含波动率指数)日线 —— 加密自己的波动率结构,免费,2021-03 起(`docs/UPGRADE_PATHS.md` A6)。

## 为什么

③ 的减仓规则只有一条价格趋势。S-685 证明 TradFi 的压力读数(VIX > 30、信用利差)在 BTC 上**不是**减仓信号,反而更像买点;
加密有自己的隐含波动率(Deribit DVOL = 30 日远期隐含波动率指数,方法同 VIX)。先把它作为**输入**接进 ③ 每日决定的描述
(水平 + 一年分位),再由 S-710 预注册它作为减仓规则的回放(lane-c T-229);这里不判任何东西。

## 做法

`GET https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=1D&start_timestamp&end_timestamp`
→ `[ts_ms, open, high, low, close]`。第一轮从 2021-03-01 起按 365 天分块回填(每块一次请求,间隔 0.3s);之后每天补最近 10 天。
表 `deriv_vol_daily`(d, currency)主键,source = deribit。lane 可读。
判活:`select currency, max(d), count(*) from deriv_vol_daily group by 1`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "deriv_vol_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"deriv_vol_daily": ("d", "currency", "dvol_open", "dvol_high", "dvol_low", "dvol_close", "source")}
LOOP_NAME = "_deribit_vol_loop"
API = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
CURRENCIES = ("BTC", "ETH")
START = dt.date(2021, 3, 1)
CHUNK_DAYS = 365
RECENT_DAYS = 10
RAN_KEY = "deribit_vol:backfilled"


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def parse(payload: dict, currency: str) -> list[dict]:
    """纯函数。Deribit 返回 → 表行(按 UTC 日;同一天多条取最后一条)。"""
    out: dict[str, dict] = {}
    for row in (((payload or {}).get("result") or {}).get("data") or []):
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            d = dt.datetime.fromtimestamp(int(row[0]) / 1000, tz=dt.timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            continue
        o, h, lo, c = (_f(row[1]), _f(row[2]), _f(row[3]), _f(row[4]))
        if c is None:
            continue
        out[d] = {"d": d, "currency": currency, "dvol_open": o, "dvol_high": h, "dvol_low": lo, "dvol_close": c, "source": "deribit"}
    return list(out.values())


def chunks(start: dt.date, end: dt.date, days: int = CHUNK_DAYS) -> list[tuple[dt.date, dt.date]]:
    out, a = [], start
    while a <= end:
        b = min(a + dt.timedelta(days=days - 1), end)
        out.append((a, b))
        a = b + dt.timedelta(days=1)
    return out


def pct_rank(history: list[float], value: Optional[float]) -> Optional[float]:
    """纯函数。value 在 history 里的分位(0–1,≤ 的比例);history 空或 value 缺 ⇒ None。"""
    if value is None or not history:
        return None
    return round(sum(1 for h in history if h <= value) / len(history), 3)


async def fetch(client, currency: str, start: dt.date, end: dt.date) -> list[dict]:
    r = await client.get(API, params={"currency": currency, "resolution": "1D",
                                      "start_timestamp": int(dt.datetime.combine(start, dt.time(), dt.timezone.utc).timestamp() * 1000),
                                      "end_timestamp": int(dt.datetime.combine(end, dt.time(23, 59), dt.timezone.utc).timestamp() * 1000)})
    if r.status_code != 200:
        raise RuntimeError(f"deribit {currency} HTTP {r.status_code}")
    return parse(r.json(), currency)


async def latest(currency: str = "BTC", days: int = 365) -> dict[str, Any]:
    """③ 决定用:最新 DVOL 收盘与一年分位。读不到 ⇒ {}。"""
    from src.data.style.header import _read_all
    since = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=days + 7)).isoformat()
    rows = await _read_all(TABLE, {"select": "d,dvol_close", "currency": f"eq.{currency}", "d": f"gte.{since}", "order": "d.asc"})
    vals = [float(r["dvol_close"]) for r in rows if _f(r.get("dvol_close")) is not None]
    if not vals:
        return {}
    return {"d": str(rows[-1]["d"])[:10], "dvol": vals[-1], "pct_1y": pct_rank(vals[:-1] or vals, vals[-1])}


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    import asyncio
    import httpx
    from src.api.store import redis_get_key_status, redis_set_key, supabase_upsert_table
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    today = now.date()
    done, _st = await redis_get_key_status(RAN_KEY)
    backfilled = bool(done and done.get("done"))
    written, errors = 0, []
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "CometCloud-vol/1.0"}) as client:
        for cur in CURRENCIES:
            spans = [(today - dt.timedelta(days=RECENT_DAYS), today)] if backfilled else chunks(START, today)
            for a, b in spans:
                try:
                    rows = await fetch(client, cur, a, b)
                except Exception as e:                                    # noqa: BLE001
                    errors.append(f"{cur} {a}: {type(e).__name__}: {str(e)[:80]}")
                    continue
                if rows:
                    w = await supabase_upsert_table(TABLE, rows, on_conflict="d,currency")
                    if not w:
                        errors.append(f"{cur} {a}: 写失败")
                        continue
                    written += len(rows)
                await asyncio.sleep(0.3)
    if not backfilled and not errors:
        await redis_set_key(RAN_KEY, {"done": True, "at": now.isoformat()}, ttl=365 * 86400)
    return {"ok": written > 0 or not errors, "written": written, "backfill": not backfilled, "errors": errors,
            "why": f"{'回填' if not backfilled else '增量'} 写 {written} 行" + (f";错 {errors}" if errors else "")}
