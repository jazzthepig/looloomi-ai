"""
R95 panel freezer — 24-asset crypto OHLCV panel for per-asset TSMOM trend strategy.

Owner: Seth, 2026-07-27. Companion to r95_per_asset_tsmom.py.

Background — Jazz 2026-07-26:
  Local SQLite OHLCV buffer (`/tmp/cometcloud_data/ohlcv.db`) holds 24 crypto assets
  × 365 days (2025-07-27 → 2026-07-26) from CoinGecko Pro. The 35 TradFi symbols
  from EODHD only have 250 days. R95 needs OHLCV RETURNS (not CIS scores), so the
  local SQLite is the only sandbox-accessible source. R77 fusion cell was built on
  the 731-day panel (Mac-side parquet at /Volumes/CometCloudAI/data/ohlcv/, NOT
  sandbox-accessible); R95 will be on the 365-day local panel — shorter but
  structurally the same bear-dominated window.

Universe: 25 crypto assets with ≥350 days of coingecko OHLCV.
    L1 (12): ADA, APT, AVAX, BNB, BTC, DOT, ETH, HYPE, NEAR, SOL, SUI, XRP
    L2 (4):  ARB, OP, POL, STRK
    DeFi (4): AAVE, LDO, PENDLE, UNI
    Infra (3): INJ, LINK, TIA
    RWA (2): MKR, ONDO
Floor: R95_MIN_TRADEABLE = 12 (R78 pattern).

Usage:
    from src.research.validation.r95_panel import build_r95_universe, load_r95_panel
    assets = build_r95_universe()
    rets, assets = load_r95_panel(start="2025-07-27", end="2026-07-26")
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

OHLCV_LOCAL_DB = Path("/tmp/cometcloud_data/ohlcv.db")
R95_MIN_TRADEABLE = 12

# Frozen R95 universe — computed once via build_r95_universe() and asserted at import.
# These 24 crypto assets are the only ones with ≥350 days of coingecko OHLCV in the
# local SQLite buffer (per `get_coverage()` audit 2026-07-27). Adding/removing
# assets requires re-running build_r95_universe() and updating this frozen tuple.
R95_UNIVERSE_FROZEN: tuple[str, ...] = (
    # L1 (12)
    "ADA", "APT", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE", "NEAR", "SOL", "SUI", "XRP",
    # L2 (4)
    "ARB", "OP", "POL", "STRK",
    # DeFi (4)
    "AAVE", "LDO", "PENDLE", "UNI",
    # Infrastructure (3)
    "INJ", "LINK", "TIA",
    # RWA (2)
    "MKR", "ONDO",
)


def _conn() -> sqlite3.Connection:
    if not OHLCV_LOCAL_DB.exists():
        raise FileNotFoundError(
            f"Local OHLCV buffer not found at {OHLCV_LOCAL_DB}. "
            f"Run: python3 scripts/fetch_ohlcv_to_local.py"
        )
    return sqlite3.connect(OHLCV_LOCAL_DB)


def build_r95_universe(min_rows: int = 350) -> list[str]:
    """Compute the live R95 universe from local SQLite (CIS-style intersection).

    Filters CoinGecko-pro OHLCV to assets with ≥`min_rows` days of history.
    Returns sorted list of asset symbols. Frozen at R95_UNIVERSE_FROZEN for
    reproducibility across runs.

    Args:
        min_rows: minimum number of daily rows per symbol to include.

    Returns:
        Sorted list of asset symbols.
    """
    sql = (
        "SELECT symbol FROM ohlcv_daily "
        "WHERE source = 'coingecko' "
        f"GROUP BY symbol HAVING COUNT(*) >= {int(min_rows)} "
        "ORDER BY symbol"
    )
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn)
    return df["symbol"].tolist()


def assert_frozen_universe() -> None:
    """Sanity-check the frozen universe matches the live buffer. Loud if drift."""
    live = set(build_r95_universe())
    frozen = set(R95_UNIVERSE_FROZEN)
    if live != frozen:
        drift_in = live - frozen
        drift_out = frozen - live
        msg = (
            f"R95_UNIVERSE_FROZEN drift detected. "
            f"In buffer but not frozen: {sorted(drift_in) or '∅'}. "
            f"In frozen but not buffer: {sorted(drift_out) or '∅'}. "
            f"Re-run build_r95_universe() and update R95_UNIVERSE_FROZEN."
        )
        raise RuntimeError(msg)


def load_r95_panel(
    start: str = "2025-07-27",
    end: str = "2026-07-26",
    universe: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Load daily close-price panel for the R95 universe.

    Args:
        start: ISO date string (inclusive).
        end: ISO date string (exclusive).
        universe: optional override for R95_UNIVERSE_FROZEN.

    Returns:
        (close_prices, asset_list) — close_prices is a wide DataFrame (date × asset)
        with NaN for assets missing on a given day; asset_list is the sorted final
        universe after dropping assets with zero observations in the window.

    Raises:
        RuntimeError if the final universe has fewer than R95_MIN_TRADEABLE assets.
    """
    assert_frozen_universe()
    symbols = sorted(set(universe) if universe is not None else R95_UNIVERSE_FROZEN)

    sql = (
        "SELECT symbol, trade_date, close FROM ohlcv_daily "
        "WHERE source = 'coingecko' "
        f"AND symbol IN ({','.join('?' * len(symbols))}) "
        "AND trade_date >= ? AND trade_date < ? "
        "ORDER BY trade_date"
    )
    params = [*symbols, start, end]
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if df.empty:
        raise RuntimeError(
            f"No OHLCV rows found for {len(symbols)} symbols in [{start}, {end}). "
            f"Check that local SQLite buffer is fresh: "
            f"python3 scripts/fetch_ohlcv_to_local.py"
        )

    df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True)
    panel = df.pivot(index="trade_date", columns="symbol", values="close").sort_index()
    panel = panel.reindex(columns=symbols)
    panel.columns.name = None
    panel.index.name = "trade_date"

    # Drop assets with zero observations (i.e. not in buffer) — strict intersection.
    observed = panel.dropna(axis=1, how="all")
    final_assets = sorted(observed.columns.tolist())
    panel = observed

    if len(final_assets) < R95_MIN_TRADEABLE:
        raise RuntimeError(
            f"R95 universe too small after strict-intersection: "
            f"{len(final_assets)} < {R95_MIN_TRADEABLE} (R95_MIN_TRADEABLE floor). "
            f"R95 refuses to silently widen."
        )

    return panel, final_assets


def returns_from_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily simple returns from a close-price panel.

    Args:
        prices: wide DataFrame (date × asset) of close prices.

    Returns:
        Wide DataFrame (date × asset) of daily simple returns (first row = NaN).
    """
    return prices.pct_change()


if __name__ == "__main__":
    # CLI: print coverage + frozen universe + panel head.
    print("=== R95 panel inspection ===\n")
    print(f"Frozen universe ({len(R95_UNIVERSE_FROZEN)} assets):")
    print(", ".join(R95_UNIVERSE_FROZEN))
    print()

    live = build_r95_universe()
    print(f"Live buffer intersection: {len(live)} assets")
    print(f"Match: {set(live) == set(R95_UNIVERSE_FROZEN)}\n")

    prices, assets = load_r95_panel()
    print(f"Panel: {prices.index.min().date()} → {prices.index.max().date()} "
          f"({len(prices)} days × {len(assets)} assets)")
    rets = returns_from_prices(prices)
    print(f"Returns: {rets.shape}, mean={rets.mean().mean():.5f}, "
          f"std={rets.std().mean():.5f}")
    print(f"NaN fraction: {rets.isna().sum().sum() / rets.size:.4f}")
    print()
    print("Per-asset coverage:")
    for a in assets:
        non_nan = rets[a].notna().sum()
        print(f"  {a:6s}: {non_nan:4d} days ({non_nan / len(rets) * 100:.1f}%)")