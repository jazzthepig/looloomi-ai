"""Daily closes for a book's universe — from the sources we PAY for (S-323u).

JAZZ, repeatedly, most recently 2026-09-09:

    「不可以那么多资产打向免费 api。多资产重复调取要走付费 api。
      binance 和 hyperliquid 这些是进入交易之后才调取。」

Many assets, repeatedly → a PAID source. Binance and Hyperliquid are read
*after* entering a trade, not to price a research panel.

WHAT WAS ACTUALLY HAPPENING. Measured 2026-09-09: **eight** paper books fetched
their closes by looping over their universe and hitting
`https://fapi.binance.com/fapi/v1/klines` once per symbol, and read TradFi from
a hardcoded Mac path (`/Volumes/CometCloudAI/...`) that does not exist on
Railway. So `factor_tilt` lost all 17 TradFi names on every run, leaving 28
crypto against a >=20 floor, and refused for weeks. `pod_aggregator` the same.

The data was in our own database the whole time, from sources we pay for:

    28/28 crypto in coingecko_pro_ohlc, >=40 bars in 60d
    11/17 tradfi in eodhd

This module replaces the fan-out with ONE `panel_closes` RPC call.

THREE PROPERTIES IT DELIBERATELY HAS

1. **One request, not N.** `source_policy` says a fan-out over more than
   BULK_THRESHOLD assets belongs on a paid source; the cheapest way to keep that
   true is to not fan out at all.

2. **One source per symbol.** S-106: bar convention is a property of the SOURCE,
   so splicing two sources into one close series makes the seam look like a
   move. The RPC picks a single source per symbol and *returns which one*, so
   the caller can see the convention it received rather than assume it.

3. **Missing comes back with a reason.** A shorter dict and a failed read are
   different states with different owners (S-240). `FetchCoverage` keeps them
   apart, and this loader never degrades to a free endpoint to fill a gap —
   a gap is reported, not papered over.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

_log = logging.getLogger("paid_close_loader")

__all__ = ["PaidCloses", "load_paid_closes"]

#: Sources allowed to price a research panel. Mirrors the RPC's own filter —
#: barred: coingecko + yfinance (S-195 bar convention), binance_hist (frozen
#: history per S-323i, not a live feed).
PAID_SOURCES = ("eodhd", "coingecko_pro_ohlc")


@dataclass
class PaidCloses:
    """Same shape the books already consume, plus the source provenance."""

    prices: dict[str, list[float]]
    missing: dict[str, str]
    sources: dict[str, str]

    @property
    def coverage(self) -> float:
        n = len(self.prices) + len(self.missing)
        return round(len(self.prices) / n, 4) if n else 0.0

    def as_payload(self) -> dict[str, Any]:
        grouped: dict[str, int] = {}
        for reason in self.missing.values():
            grouped[reason] = grouped.get(reason, 0) + 1
        by_source: dict[str, int] = {}
        for src in self.sources.values():
            by_source[src] = by_source.get(src, 0) + 1
        return {
            "priced": len(self.prices),
            "unpriced": len(self.missing),
            "coverage": self.coverage,
            "by_source": by_source,
            "missing_reasons": dict(sorted(grouped.items(), key=lambda kv: -kv[1])),
        }


async def load_paid_closes(symbols: Iterable[str],
                           lookback_days: int = 60,
                           *, min_bars: int = 2) -> PaidCloses:
    """One RPC. Never touches a venue API.

    `min_bars` exists because a symbol with a single bar is not a series — and
    returning it would let a book compute a "return" from one observation.
    """
    from src.api.rpc_diagnostics import rpc_with_detail, render_detail

    want = [str(s).upper() for s in symbols]
    if not want:
        return PaidCloses({}, {}, {})

    rows, detail = await rpc_with_detail(
        "panel_closes", {"p_symbols": want, "p_days": int(lookback_days)})

    if detail.get("outcome") != "ok" or not isinstance(rows, list):
        # ⚠️ **读不到 ≠ 一个都没有。** 全部标成 missing 并带上真实原因
        # (状态码 + PostgREST body),而不是回一个空的 prices 让调用方
        # 以为宇宙是空的 —— 那正是 S-323 那条链的形状。
        why = render_detail(detail, prefix="panel_closes ")
        _log.warning("[PAID-CLOSE] %s", why)
        return PaidCloses({}, {s: why for s in want}, {})

    prices: dict[str, list[float]] = {}
    sources: dict[str, str] = {}
    seen: set[str] = set()
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        seen.add(sym)
        closes = [float(c) for c in (r.get("closes") or []) if c is not None]
        if len(closes) < min_bars:
            continue
        prices[sym] = closes
        sources[sym] = str(r.get("source") or "?")

    missing: dict[str, str] = {}
    for s in want:
        if s in prices:
            continue
        if s in seen:
            missing[s] = f"fewer than {min_bars} usable bars in {lookback_days}d"
        else:
            missing[s] = (f"no bars from a paid source "
                          f"({'/'.join(PAID_SOURCES)}) in {lookback_days}d")
    if missing:
        _log.info("[PAID-CLOSE] %s/%s priced · %s",
                  len(prices), len(want),
                  PaidCloses(prices, missing, sources).as_payload()["missing_reasons"])
    return PaidCloses(prices, missing, sources)
