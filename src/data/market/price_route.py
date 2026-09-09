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

#: S-323o — **进程内缓存在部署时归零,而部署恰恰是最可能错过打标的时刻。**
#:
#: 2026-09-09 00:05:39 实测:① 的 `beta_core` 在估值点拒绝打标,理由是
#: 「cannot reach the execution venue's listing, and no cached copy exists」。
#: 那句话是对的 —— 但「no cached copy」不是因为我们没缓存,是因为
#: `_VENUE_CACHE` 是一个模块级 dict,**昨天推了好几次,每推一次它就回到 None**。
#: 于是那条 last-good 兜底在**唯一需要它的场合**恰好是空的。
#:
#: 场馆挂牌是**慢变量**(永续上新以周计),而 ① 的前向记录是按天计的产品本身。
#: 拿一个慢变量的一次瞬时抖动去换一天不可补的记录,是个坏交易。
#: 落到 Redis(跨部署存活),并且**用了缓存必须说出来**——
#: 见 `split_universe()["listing_meta"]`,调用方据此记一条 flagged 异常。
_VENUE_REDIS_KEY = "route:venue_symbols"
#: 挂牌可以旧,但不能无限旧。超过这个年龄就不再算「已知」,退回拒绝。
_VENUE_PERSIST_MAX_AGE_S = 7 * 24 * 3600


async def venue_symbols_detailed(force: bool = False) -> tuple[set[str], dict]:
    """场馆挂牌 + **它是从哪来的**。

    `meta["source"]` ∈ `venue` / `memory` / `persisted`,并带 `age_s`。
    打标用的是不是当场取回来的挂牌,是一件必须能事后回答的事 ——
    S-287 已经为「被前向填充的价格」立过同样的规矩:
    **一个被沿用的值满足所有 not-NaN 检查,而它不是一次观测。**
    """
    import time
    now = time.time()
    meta: dict[str, Any] = {"source": None, "age_s": 0.0, "n": 0, "error": None}

    if not force and _VENUE_CACHE["symbols"] is not None \
            and now - _VENUE_CACHE["ts"] < _VENUE_TTL:
        meta.update(source="memory", age_s=round(now - _VENUE_CACHE["ts"], 1),
                    n=len(_VENUE_CACHE["symbols"]))
        return _VENUE_CACHE["symbols"], meta

    from src.data.market.hyperliquid_collector import hyperliquid_universe_detailed
    raw, err = await hyperliquid_universe_detailed()
    syms = {s.upper() for s in (raw or [])}
    meta["error"] = err
    if syms:
        _VENUE_CACHE["symbols"] = syms
        _VENUE_CACHE["ts"] = now
        try:
            from src.api.store import redis_set_key
            await redis_set_key(_VENUE_REDIS_KEY,
                                {"symbols": sorted(syms), "ts": now},
                                ttl=_VENUE_PERSIST_MAX_AGE_S)
        except Exception as _e:                              # noqa: BLE001
            _log.warning("[ROUTE] venue listing not persisted: %s", _e)
        meta.update(source="venue", age_s=0.0, n=len(syms))
        return syms, meta

    # 取不到。**注意 `err is None` 与 `err` 是两件事**:前者表示场馆确实回了
    # 一个空挂牌(那是场馆的事实,不该被兜底掩盖),后者是我们没问到。
    if _VENUE_CACHE["symbols"] is not None:
        age = round(now - _VENUE_CACHE["ts"], 1)
        _log.warning("[ROUTE] venue listing unreachable (%s) — holding in-memory "
                     "last-good (%s syms, %ss old)", err, len(_VENUE_CACHE["symbols"]), age)
        meta.update(source="memory", age_s=age, n=len(_VENUE_CACHE["symbols"]))
        return _VENUE_CACHE["symbols"], meta

    try:
        from src.api.store import redis_get_key
        payload = await redis_get_key(_VENUE_REDIS_KEY)
    except Exception as _e:                                  # noqa: BLE001
        payload = None
        _log.warning("[ROUTE] persisted venue listing unreadable: %s", _e)
    if isinstance(payload, dict) and payload.get("symbols"):
        age = now - float(payload.get("ts") or 0.0)
        if age <= _VENUE_PERSIST_MAX_AGE_S:
            syms = {str(s).upper() for s in payload["symbols"]}
            _VENUE_CACHE["symbols"] = syms
            _VENUE_CACHE["ts"] = now - age
            _log.warning("[ROUTE] venue listing unreachable (%s) — using PERSISTED "
                         "copy (%s syms, %.0fs old)", err, len(syms), age)
            meta.update(source="persisted", age_s=round(age, 1), n=len(syms))
            return syms, meta
        _log.warning("[ROUTE] persisted venue listing too old (%.0fs) — refusing", age)

    raise PriceRouteError(
        "cannot reach the execution venue's listing, and no cached copy exists. "
        "Refusing to guess which symbols are tradeable."
        + (f" (fetch error: {err})" if err else
           " (the venue answered with an EMPTY listing — that is the venue's"
           " fact, not a fetch failure)"))


async def venue_symbols(force: bool = False) -> set[str]:
    """Everything listed on the execution venue. Cached 1 h, persisted 7 d."""
    syms, _meta = await venue_symbols_detailed(force=force)
    return syms


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
    venue, listing_meta = await venue_symbols_detailed()
    up = [s.upper() for s in symbols]
    tradeable = [s for s in up if s in venue]
    research_only = [s for s in up if s not in venue]
    return {
        "tradeable": tradeable,
        "research_only": research_only,
        "tradeable_pct": round(100 * len(tradeable) / len(up), 1) if up else 0.0,
        "venue": EXECUTION_VENUE,
        "venue_listed": len(venue),
        # S-323o:**打标用的挂牌是不是当场取回来的,必须能事后回答。**
        # `source="venue"` 才是一次观测;memory/persisted 是沿用。
        "listing_meta": listing_meta,
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
