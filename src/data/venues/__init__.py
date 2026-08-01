"""
Multi-venue market-data consolidation.

Why this package exists (2026-08-01):
    `cis_provider.BINANCE_SYMBOLS` mapped HYPE -> "hyperusdt" on Binance SPOT.
    HYPE is not listed on Binance spot; HYPERUSDT is Hyperlane, a different
    asset trading at $0.0558 against Hyperliquid's $52.32 — a 937x error.
    The engine blended CoinGecko market cap with Hyperlane's order book,
    producing volume_mcap_ratio=0.0002 -> liquidity_score=-4.8 -> LAS 3.1 ->
    grade D -> UNDERWEIGHT, through a +256% run.

    A single-venue source is wrong twice over: it can silently point at the
    wrong asset, and even when correct it distorts, because venues host
    different trader populations. Measured on HYPE 2026-08-01:

        venue         24h vol      OI          turnover   funding
        Binance       $440.8M      $248.1M     1.78x      0.000050
        Hyperliquid   $314.4M      $1,174.4M   0.27x      0.000013
        Bybit         $178.2M      $201.2M     0.89x      0.000100

    Price dispersion across the three: 7bp (arbitrage converges it).
    Volume/OI/funding do NOT converge — Hyperliquid holds 72% of open
    interest on 34% of volume (position-takers); Binance is the inverse
    (leverage churn). Picking any one venue yields that cohort's picture,
    not the asset's.

Consequently the aggregation rule differs by quantity:
    price    -> volume-weighted median across venues (CME CF / Kaiko recipe;
                converges, so the median is both accurate AND a free
                integrity check — a wrong-asset mapping falls outside it)
    volume   -> sum over accepted venues (additive; single-venue undercounts)
    OI       -> sum over accepted venues, GROSS notional (see caveat below)
    funding  -> never averaged; the per-venue spread is the signal

CAVEAT on aggregate OI: summing across venues gives gross open notional, not
net directional exposure. A market maker long on Binance and short on
Hyperliquid is counted twice. Read aggregate OI as gross; read the cross-venue
funding spread for the net positioning story.

Confidence is derived from cross-venue dispersion and venue count (Pyth's
confidence-interval principle) rather than being a hardcoded constant.

Degradation policy (CLAUDE.md hard rule #9 — no fabricated data):
    Venue failures are isolated; one dead venue never fails the consolidation.
    Below MIN_VENUES_FOR_CONSENSUS the result is returned but marked
    `degraded=True` with reduced confidence. Zero venues returns None, never
    a synthesized number.
"""

from .registry import (
    VENUES,
    VenueSpec,
    venue_symbol,
    venues_for,
)
from .consolidator import (
    VenueQuote,
    ConsolidatedQuote,
    consolidate,
    fetch_consolidated,
    volume_weighted_median,
    MIN_VENUES_FOR_CONSENSUS,
    OUTLIER_REJECT_RATIO,
)

__all__ = [
    "VENUES",
    "VenueSpec",
    "venue_symbol",
    "venues_for",
    "VenueQuote",
    "ConsolidatedQuote",
    "consolidate",
    "fetch_consolidated",
    "volume_weighted_median",
    "MIN_VENUES_FOR_CONSENSUS",
    "OUTLIER_REJECT_RATIO",
]
