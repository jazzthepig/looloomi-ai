"""THE price route. One answer to "what is X worth on day D" (S-193).

Jazz, 2026-08-20: **交易和读取的 route 都要写死啊,不可以乱来啊** — and before
that: "不然就是回测好看,实盘根本没办法用,就算给你接 TradingView 和 Hyperliquid
就是浪费钱."

He is describing a specific defect, not a preference. Until now the read path was
a FALLBACK CHAIN — `ohlcv_daily_canonical` resolves
`binance_hist > hyperliquid > eodhd > coingecko > yfinance`, picking per row
whichever source happened to have data. The trade path will be Hyperliquid and
only Hyperliquid. **A backtest priced on a chain and a fill priced on a venue
cannot agree, and the gap does not show up as an error — it shows up as
slippage nobody can attribute.** Connecting a real venue on top of that spends
money to make the discrepancy expensive instead of merely wrong.

Three measured facts behind this, all from 2026-08-20:

  · CoinGecko and Hyperliquid disagreed about 08-19 by SEVENTEEN POINTS on ETH
    (+0.22% vs +17.57%). Our stored row for `trade_date=2026-08-19` held HL's
    08-18 close.
  · The cause is not a write-date bug, which is what I first said. CoinGecko's
    `market_chart/range` returns HOURLY points for short windows regardless of
    `interval=daily`; collapsing them to a date keeps whichever hour landed
    last. The "daily close" was never a close.
  · Binance is geo-blocked from Railway US: 1 of 262 panel symbols had a bar
    since 08-14, so the top-priority source in the chain is mostly absent and
    every query silently falls through to the worst one.

So: PINNED. Not "prefer HL". Not "HL with fallback". For anything we can trade,
the price is the venue's, and when the venue does not have it the answer is
**REFUSAL, not a substitute**. A refusal stops a backtest; a substitute ships it.

  tradeable symbol  → Hyperliquid, or an error. Never another source.
  non-tradeable     → research sources, and the symbol is BARRED from any book.

The second line is the other half of Jazz's point. Of the 262-symbol research
panel, 88 are listed on Hyperliquid. Backtesting the other 174 produces results
that cannot be executed at any price — which is how a backtest gets to look good
while live is impossible.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("price_route")

#: The execution venue. Changing this is a trading decision, not a config tweak,
#: and it must change in ONE place — that is the whole point of this module.
EXECUTION_VENUE = "hyperliquid"

#: Sources acceptable for RESEARCH ONLY on symbols the venue does not list.
#: Deliberately not a fallback for tradeable symbols. Ordered for determinism,
#: not for preference-at-runtime: a study states which one it used.
RESEARCH_SOURCES = ("binance_hist", "eodhd")

#: NOT in either list, deliberately. CoinGecko's daily series is hourly points
#: collapsed to a date — the value is "some hour of that day", which is fine for
#: a dashboard tile and disqualifying for a return series. Measured 2026-08-20:
#: it reported ETH 08-19 at +0.22% against the venue's +17.57%.
BARRED_FOR_RETURNS = ("coingecko", "yfinance")


class PriceRouteError(RuntimeError):
    """The route could not answer. Deliberately an exception, not a None.

    A None gets `or 0`-ed, `if px:`-ed, and defaulted into a plausible number
    three frames up. This is the failure mode this whole codebase keeps
    rediscovering (S-180 miss-vs-error, S-185 fail-closed silence, S-190 partial
    day written as a day). An unhandled exception stops the run and names the
    symbol; a None becomes a backtest.
    """


_VENUE_CACHE: dict[str, Any] = {"symbols": None, "ts": 0.0}
_VENUE_TTL = 3600.0


async def venue_symbols(force: bool = False) -> set[str]:
    """Everything listed on the execution venue. Cached 1 h."""
    import time
    now = time.time()
    if not force and _VENUE_CACHE["symbols"] is not None \
            and now - _VENUE_CACHE["ts"] < _VENUE_TTL:
        return _VENUE_CACHE["symbols"]
    from src.data.market.hyperliquid_collector import hyperliquid_universe
    syms = {s.upper() for s in await hyperliquid_universe()}
    if syms:
        _VENUE_CACHE["symbols"] = syms
        _VENUE_CACHE["ts"] = now
        return syms
    if _VENUE_CACHE["symbols"] is not None:
        _log.warning("[ROUTE] venue listing unreachable — holding last-good (%s syms)",
                     len(_VENUE_CACHE["symbols"]))
        return _VENUE_CACHE["symbols"]
    raise PriceRouteError(
        "cannot reach the execution venue's listing, and no cached copy exists. "
        "Refusing to guess which symbols are tradeable.")


async def is_tradeable(symbol: str) -> bool:
    return symbol.upper() in await venue_symbols()


def price_source_for(symbol: str, tradeable: bool, *, purpose: str) -> str:
    """The ONE source this symbol's prices may come from, for this purpose.

    `purpose` is 'execution' | 'book' | 'research'. Book marking uses the venue,
    same as execution — a paper book marked anywhere else is measuring a
    portfolio nobody could have held.
    """
    if purpose in ("execution", "book"):
        if not tradeable:
            raise PriceRouteError(
                f"{symbol} is not listed on {EXECUTION_VENUE}; it cannot be "
                f"marked or traded. Research-only symbols must be excluded from "
                f"books at construction, not priced from a substitute source.")
        return EXECUTION_VENUE
    if purpose == "research":
        return EXECUTION_VENUE if tradeable else RESEARCH_SOURCES[0]
    raise PriceRouteError(f"unknown purpose {purpose!r}")


async def split_universe(symbols: list[str]) -> dict[str, Any]:
    """Partition a candidate universe into what can and cannot be traded.

    Every book construction should start here. The 174 research-only symbols in
    our panel are not a rounding error — they are 66% of it, and a sleeve built
    across all 262 is a sleeve that cannot be run.
    """
    venue = await venue_symbols()
    up = [s.upper() for s in symbols]
    tradeable = [s for s in up if s in venue]
    research_only = [s for s in up if s not in venue]
    return {
        "tradeable": tradeable,
        "research_only": research_only,
        "tradeable_pct": round(100 * len(tradeable) / len(up), 1) if up else 0.0,
        "venue": EXECUTION_VENUE,
        "venue_listed": len(venue),
    }


async def assert_book_universe(symbols: list[str]) -> list[str]:
    """Gate for anything that marks a book. Raises unless ALL are tradeable.

    Returns the list unchanged on success so it can wrap a call site:

        panel = await assert_book_universe(panel)

    Refuses rather than silently dropping, because a book that quietly shrinks
    from 24 names to 9 still reports a NAV, and the NAV is of a different
    portfolio than the one on the page.
    """
    split = await split_universe(symbols)
    if split["research_only"]:
        raise PriceRouteError(
            f"{len(split['research_only'])} of {len(symbols)} symbols are not "
            f"listed on {EXECUTION_VENUE} and cannot be marked: "
            f"{split['research_only'][:12]}"
            f"{' …' if len(split['research_only']) > 12 else ''}. "
            f"Exclude them when the universe is built, or the book reports a NAV "
            f"for a portfolio that could not be held.")
    return symbols
