"""
Universe loader — multi-asset, multi-timeframe data source for the framework.

Wraps the on-disk parquet data at /Volumes/CometCloudAI/data/ohlcv/{SYMBOL}.parquet
with selection helpers and Binance contract-spec precision tables.

Provides:
- `available_symbols()`: all parquet files on disk
- `ACTIVE_UNIVERSE`: curated 20-asset list for production runs
- `load_ohlcv(symbol, timeframe)`: load 1h or 4h for one symbol
- Precision tables for 20+ Binance USDT-margined perps
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from src.research.data_bridge import (
    load_1h_parquet, resample_to_4h, filter_timerange,
    PRICE_PRECISION, SIZE_PRECISION,
)
from src.research.indicators import precompute_indicators


# ── Data location ───────────────────────────────────────────────────────────
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")


# ── Active universe ─────────────────────────────────────────────────────────
# Curated 20-asset production list. Chosen for liquidity + institutional
# custody coverage. Order matters: BTC first, then majors, then alts.

ACTIVE_UNIVERSE = [
    "BTC", "ETH", "SOL", "BNB", "XRP",                       # top 5 (LS-V4 baseline)
    "ADA", "AVAX", "LINK", "DOGE", "DOT",                     # L1 + large-cap
    "ATOM", "LTC", "NEAR", "APT", "ARB",                      # L1 + L2
    "OP", "INJ", "SUI", "TIA", "UNI",                         # L2 / DeFi
]  # PRICE_PRECISION / SIZE_PRECISION are re-exported by reference from
# data_bridge (single source of truth — modifications flow through here).


# ── Functions ────────────────────────────────────────────────────────────────

def available_symbols() -> list[str]:
    """All symbols with parquet on disk."""
    return sorted(p.stem for p in OHLCV_DIR.glob("*.parquet"))


def has_data(symbol: str) -> bool:
    """Check if a symbol has parquet data on disk."""
    return (OHLCV_DIR / f"{symbol}.parquet").exists()


def get_precision(symbol: str) -> tuple[int, int]:
    """Return (price_precision, size_precision) for a Binance perp.

    Falls back to (2, 3) for unknown symbols (BNB-style).
    """
    pp = PRICE_PRECISION.get(symbol, 2)
    sp = SIZE_PRECISION.get(symbol, 3)
    return pp, sp


@dataclass
class UniverseStats:
    """Summary of available universe data."""
    n_total: int             # total symbols on disk
    n_active: int            # symbols in ACTIVE_UNIVERSE
    n_active_with_data: int  # ACTIVE_UNIVERSE symbols that have parquet
    missing: list[str]       # ACTIVE_UNIVERSE symbols without data


def universe_stats() -> UniverseStats:
    """Summarise data coverage across the active universe."""
    have = set(available_symbols())
    missing = [s for s in ACTIVE_UNIVERSE if s not in have]
    return UniverseStats(
        n_total=len(have),
        n_active=len(ACTIVE_UNIVERSE),
        n_active_with_data=len(ACTIVE_UNIVERSE) - len(missing),
        missing=missing,
    )


def load_ohlcv(
    symbol: str,
    timeframe: str = "4h",
    timerange: Optional[tuple[str, str]] = None,
    with_indicators: bool = True,
) -> pd.DataFrame:
    """Load OHLCV for one symbol, optionally resampled and indicator-enriched.

    Args:
        symbol: base symbol e.g. "BTC" (not "BTCUSDT").
        timeframe: "1h" or "4h" (1d requires `data_extend.py` first).
        timerange: optional (start, end) inclusive-exclusive YYYY-MM-DD.
        with_indicators: if True, attach Wilder ADX/EMA/ATR/RSI (slower).

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume, ...]
        sorted by timestamp ascending.

    Raises:
        FileNotFoundError: if symbol has no parquet on disk.
        ValueError: if timeframe is unsupported.
    """
    df = load_1h_parquet(symbol)
    if timeframe == "1h":
        pass
    elif timeframe == "4h":
        df = resample_to_4h(df)
    else:
        raise ValueError(f"timeframe {timeframe!r} unsupported (use '1h' or '4h')")
    if timerange is not None:
        df = filter_timerange(df, timerange[0], timerange[1])
    df = df.reset_index(drop=True)
    if with_indicators:
        df = precompute_indicators(df)
    return df


def load_universe(
    symbols: Sequence[str],
    timeframe: str = "4h",
    timerange: Optional[tuple[str, str]] = None,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for multiple symbols in one call.

    Args:
        symbols: list of base symbols (e.g. ["BTC", "ETH"]).
        timeframe: "1h" or "4h".
        timerange: optional date filter.

    Returns:
        Dict {symbol: DataFrame}. Missing symbols are silently skipped.
    """
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            out[sym] = load_ohlcv(sym, timeframe, timerange)
        except FileNotFoundError:
            continue
    return out


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    stats = universe_stats()
    print(f"Universe coverage:")
    print(f"  total symbols on disk: {stats.n_total}")
    print(f"  active universe size:  {stats.n_active}")
    print(f"  active with data:      {stats.n_active_with_data}")
    if stats.missing:
        print(f"  missing:               {stats.missing}")
    print()
    print("First 10 active symbols and their precision:")
    for s in ACTIVE_UNIVERSE[:10]:
        pp, sp = get_precision(s)
        have = has_data(s)
        print(f"  {s:<6} price_prec={pp} size_prec={sp}  data={'✓' if have else '✗'}")

    # Smoke load
    print()
    print("Loading BTC 4h with indicators...")
    df = load_ohlcv("BTC", "4h", ("2025-05-03", "2026-03-12"))
    print(f"  rows: {len(df)}, columns: {df.columns.tolist()}")
    print(f"  range: {df.iloc[0]['timestamp']} → {df.iloc[-1]['timestamp']}")