"""World50 候选池的复权日线:2015 起整段重取、整段覆盖写入 ohlcv_daily(source = eodhd)(T-098)。

## 为什么要整段重取

复权收盘会随**之后**的分红 / 拆股回改。日更采集(`_ohlcv_collector_loop`)每天只重写最近 365 天,
更早的行停在它最后一次落在窗口里的那天的复权口径 —— 一年以前的分红再也不会写回去。长窗口的总收益
因此会少算股息与票息(10-14 对照:SHY 在 yfinance 里九年价格持平,票息全丢)。
这里每周把每个候选从 2015-01-01 起整段取一次、按同一个口径整段覆盖 —— 一次写入里的所有行同一个复权口径。

## 规则

- 只经 `data_layer.get_eodhd_eod_range`(既有取数入口,不新增)与 `eodhd_adjusted_rows`(既有复权换算)。
- 某个代码取不到 / 返回空 ⇒ 那个代码一行不写,原因记进结果;**不拿旧值或别的源补**。
- 写入经 `ohlcv._upsert_ohlcv`(merge-duplicates,按 symbol + trade_date + source)。
- 判活:`select count(distinct symbol) from ohlcv_daily where source = 'eodhd' and trade_date < '2015-02-01'` ≥ 60;
  `loop_attempt` 里 `_world50_history_loop` 每周一条 ok。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

START = "2015-01-01"
CONCURRENCY = 4
MIN_SYMBOLS_OK = 60          # 低于这个数整轮记 refused(大面积取不到 ≠ 正常的一周)


def split_code(code: str) -> tuple[str, str]:
    """`AAPL.US` → (`AAPL`, `US`);`XAUUSD.FOREX` → (`XAUUSD`, `FOREX`);`2222.SR` → (`2222`, `SR`)。"""
    if "." not in code:
        raise ValueError(f"EODHD 代码缺交易所后缀:{code!r}")
    t, ex = code.rsplit(".", 1)
    return t, ex


def rows_for(symbol: str, asset_class: str, adjusted: list[dict]) -> list[dict]:
    """`eodhd_adjusted_rows` 的输出 → ohlcv_daily 行。纯函数。"""
    return [{
        "symbol": symbol, "asset_class": asset_class, "source": "eodhd",
        "trade_date": r["trade_date"], "open": r["open"], "high": r["high"], "low": r["low"],
        "close": r["close"], "volume": r["volume"],
    } for r in adjusted if r.get("close") and r["close"] > 0]


_CLASS = {"equity": "Equity", "metal": "Commodity", "benchmark": "ETF"}


async def refresh_one(c: Any, start: str = START) -> dict[str, Any]:
    from src.api.routers.ohlcv import _upsert_ohlcv, eodhd_adjusted_rows
    from src.data.market.data_layer import get_eodhd_eod_range
    try:
        ticker, ex = split_code(c.code)
        raw = await get_eodhd_eod_range(ticker, ex, start)
    except Exception as e:  # noqa: BLE001 — 一个代码取不到不连坐整轮,原因带回去
        return {"symbol": c.key, "ok": False, "why": f"{type(e).__name__}: {str(e)[:160]}"}
    rows = rows_for(c.key, _CLASS.get(c.cls, c.cls), eodhd_adjusted_rows(raw))
    if not rows:
        return {"symbol": c.key, "ok": False, "why": "EODHD 返回 0 行可用日线"}
    written = await _upsert_ohlcv(None, rows)
    return {"symbol": c.key, "ok": written == len(rows), "rows": len(rows), "written": written,
            "first": rows[0]["trade_date"], "last": rows[-1]["trade_date"],
            **({} if written == len(rows) else {"why": f"只写进 {written}/{len(rows)} 行"})}


async def run_once(start: str = START, candidates: Optional[list] = None) -> dict[str, Any]:
    from src.data.universe.world50 import BENCHMARKS, eodhd_candidates
    todo = candidates if candidates is not None else eodhd_candidates() + list(BENCHMARKS)   # 对照组一起整段重取(T-099)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def _guard(c):
        async with sem:
            return await refresh_one(c, start)

    t0 = datetime.now(timezone.utc)
    res = await asyncio.gather(*[_guard(c) for c in todo])
    ok = [r for r in res if r.get("ok")]
    failed = [{"symbol": r["symbol"], "why": r.get("why")} for r in res if not r.get("ok")]
    written = sum(int(r.get("written") or 0) for r in res)
    enough = len(ok) >= min(MIN_SYMBOLS_OK, len(todo))
    return {
        "ok": enough, "refused": not enough,
        "symbols": len(todo), "symbols_ok": len(ok), "written": written, "failed": failed[:40],
        "elapsed_s": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
        "reason": (f"{len(ok)}/{len(todo)} 个代码整段重取,写入 {written} 行" if enough
                   else f"只有 {len(ok)}/{len(todo)} 个代码取到 —— 低于 {MIN_SYMBOLS_OK},按大面积故障报"),
    }
