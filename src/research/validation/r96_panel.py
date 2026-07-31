"""
R96 panel freezer — 33-asset TradFi OHLCV panel for cross-asset bond-equity β-residual L/S.

Owner: Seth, 2026-07-27. Companion to r96_cross_asset_bond_equity.py.

Background — Option D pivot (post R95, 13-attempt graveyard):
  R95 (per-asset signed TSMOM, canonical AQR/Tran) REFUTED on the 363-day 25-asset
  crypto panel. The 13-attempt graveyard (R82/R83/R85/R86/R87/R88/R89/R90/R91/R92/
  R93/R94/R95) is structurally blocked by the bear-dominated short panel. R96 is
  the first candidate on a STRUCTURALLY DIFFERENT data class: cross-asset L/S
  using EODHD TradFi cache (33 symbols × 250 days).

  The signal: §TRADER_TOM §5b-style cross-asset value carry / risk-premium. Long
  bond β-residual, short equity β-residual (or reverse). β-residual = difference
  between each asset's rolling 30d β to the equity index (SPY) and to the
  long-bond index (TLT). Positive residual = bond-like (rate-sensitive,
  defensive), negative = equity-like (rate-insensitive, risk-on).

  Universe: 33 TradFi symbols with ≥250 days of EODHD OHLCV in local SQLite.
    Equity (8)  : SPY, QQQ, IWM, AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA
    Bond (6)    : TLT, IEF, SHY, TIP, HYG, LQD
    Commodity(6): GLD, SLV, USO, UNG, DBA, CPER
    FX (3)      : UUP, FXE, FXY
    EM (4)      : EEM, EWZ, FXI, VWO, INDA
    REIT (3)    : IYR, VNQ, VNQI
    Sector (1)  : XLF
  (33 total, all from /tmp/cometcloud_data/ohlcv.db source='eodhd')

Usage:
    from src.research.validation.r96_panel import build_r96_universe, load_r96_panel
    rets, assets, classes = load_r96_panel()
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
R96_MIN_TRADEABLE = 18  # need at least 6 per class × 3 classes for the score to be meaningful


# Frozen R96 universe — computed once via build_r96_universe() and asserted at import.
# These 33 TradFi assets are the only ones with ≥250 days of EODHD OHLCV in the
# local SQLite buffer (per `get_coverage()` audit 2026-07-27). Adding/removing
# assets requires re-running build_r96_universe() and updating this frozen tuple.
R96_UNIVERSE_FROZEN: tuple[str, ...] = (
    # Equity (9)
    "AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "QQQ", "SPY", "TSLA",
    # Bond (6)
    "HYG", "IEF", "LQD", "SHY", "TIP", "TLT",
    # Commodity (6)
    "CPER", "DBA", "GLD", "SLV", "UNG", "USO",
    # FX (3)
    "FXE", "FXY", "UUP",
    # EM (5)
    "EEM", "EWZ", "FXI", "INDA", "VWO",
    # REIT (3)
    "IYR", "VNQ", "VNQI",
    # Sector (1)
    "XLF",
)

# Class taxonomy — used to (a) ensure class balance, (b) build per-class control factors.
R96_CLASS: dict[str, str] = {
    "AAPL": "equity", "AMZN": "equity", "GOOGL": "equity", "META": "equity",
    "MSFT": "equity", "NVDA": "equity", "QQQ": "equity", "SPY": "equity",
    "TSLA": "equity",
    "HYG": "bond", "IEF": "bond", "LQD": "bond", "SHY": "bond", "TIP": "bond",
    "TLT": "bond",
    "CPER": "commodity", "DBA": "commodity", "GLD": "commodity", "SLV": "commodity",
    "UNG": "commodity", "USO": "commodity",
    "FXE": "fx", "FXY": "fx", "UUP": "fx",
    "EEM": "em", "EWZ": "em", "FXI": "em", "INDA": "em", "VWO": "em",
    "IYR": "reit", "VNQ": "reit", "VNQI": "reit",
    "XLF": "sector",
}


def _conn() -> sqlite3.Connection:
    if not OHLCV_LOCAL_DB.exists():
        raise FileNotFoundError(
            f"Local OHLCV buffer not found at {OHLCV_LOCAL_DB}. "
            f"Run: python3 scripts/fetch_ohlcv_to_local.py"
        )
    return sqlite3.connect(OHLCV_LOCAL_DB)


def build_r96_universe(min_rows: int = 240) -> list[str]:
    """Compute the live R96 universe from local SQLite (EODHD-only).

    Filters EODHD OHLCV to assets with ≥`min_rows` days of history.
    Returns sorted list of asset symbols. Frozen at R96_UNIVERSE_FROZEN for
    reproducibility across runs.
    """
    sql = (
        "SELECT symbol FROM ohlcv_daily "
        "WHERE source = 'eodhd' "
        f"GROUP BY symbol HAVING COUNT(*) >= {int(min_rows)} "
        "ORDER BY symbol"
    )
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn)
    return df["symbol"].tolist()


def assert_frozen_universe() -> None:
    """Sanity-check the frozen universe matches the live buffer. Loud if drift."""
    live = set(build_r96_universe())
    frozen = set(R96_UNIVERSE_FROZEN)
    if live != frozen:
        drift_in = live - frozen
        drift_out = frozen - live
        msg = (
            f"R96_UNIVERSE_FROZEN drift detected. "
            f"In buffer but not frozen: {sorted(drift_in) or '∅'}. "
            f"In frozen but not buffer: {sorted(drift_out) or '∅'}. "
            f"Re-run build_r96_universe() and update R96_UNIVERSE_FROZEN."
        )
        raise RuntimeError(msg)


def load_r96_panel(
    start: str = "2025-07-28",
    end: str = "2026-07-25",
    universe: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    """Load daily close-price panel for the R96 TradFi universe.

    Returns:
        (close_prices, asset_list, class_map) — class_map[asset] ∈
        {equity, bond, commodity, fx, em, reit, sector}.
    """
    assert_frozen_universe()
    symbols = sorted(set(universe) if universe is not None else R96_UNIVERSE_FROZEN)
    sql = (
        "SELECT symbol, trade_date, close FROM ohlcv_daily "
        "WHERE source = 'eodhd' "
        f"AND symbol IN ({','.join('?' * len(symbols))}) "
        "AND trade_date >= ? AND trade_date < ? "
        "ORDER BY trade_date"
    )
    params = [*symbols, start, end]
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if df.empty:
        raise RuntimeError(
            f"No EODHD rows found for {len(symbols)} symbols in [{start}, {end}). "
            f"Check that local SQLite buffer is fresh: "
            f"python3 scripts/fetch_ohlcv_to_local.py"
        )

    df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True)
    panel = df.pivot(index="trade_date", columns="symbol", values="close").sort_index()
    panel = panel.reindex(columns=symbols)
    panel.columns.name = None
    panel.index.name = "trade_date"

    observed = panel.dropna(axis=1, how="all")
    final_assets = sorted(observed.columns.tolist())
    panel = observed
    if len(final_assets) < R96_MIN_TRADEABLE:
        raise RuntimeError(
            f"R96 universe too small after strict-intersection: "
            f"{len(final_assets)} < {R96_MIN_TRADEABLE} (R96_MIN_TRADEABLE floor). "
            f"R96 refuses to silently widen."
        )

    # Build class_map for surviving assets only.
    class_map = {a: R96_CLASS.get(a, "other") for a in final_assets}
    return panel, final_assets, class_map


def returns_from_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily simple returns from a close-price panel.

    First row = NaN. NaN-fills missing days per asset (ffill close → pct_change).
    """
    return prices.pct_change()


if __name__ == "__main__":
    print("=== R96 panel inspection ===\n")
    print(f"Frozen universe ({len(R96_UNIVERSE_FROZEN)} assets):")
    print(", ".join(R96_UNIVERSE_FROZEN))
    print()
    live = build_r96_universe()
    print(f"Live buffer intersection: {len(live)} assets")
    print(f"Match: {set(live) == set(R96_UNIVERSE_FROZEN)}\n")

    prices, assets, classes = load_r96_panel()
    print(f"Panel: {prices.index.min().date()} → {prices.index.max().date()} "
          f"({len(prices)} days × {len(assets)} assets)")
    rets = returns_from_prices(prices)
    print(f"Returns: {rets.shape}, mean={rets.mean().mean():.5f}, "
          f"std={rets.std().mean():.5f}")
    print(f"NaN fraction: {rets.isna().sum().sum() / rets.size:.4f}")
    print()
    print("Per-class counts:")
    from collections import Counter
    ctr = Counter(classes.values())
    for k, v in sorted(ctr.items()):
        print(f"  {k:10s}: {v}")
    print()
    print("Per-asset coverage:")
    for a in assets:
        non_nan = rets[a].notna().sum()
        print(f"  {a:6s} ({classes[a]:10s}): {non_nan:4d} days ({non_nan / len(rets) * 100:.1f}%)")
