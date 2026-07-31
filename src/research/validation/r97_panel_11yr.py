"""R97 panel 11yr — daily-bar deep panel for multi-cycle re-validation.

Purpose: per user direction 2026-07-27 ("怎么又卡在731天这里了，我们不是有11年的吗？
如果是数据问题，你先去修数据"), the 4h-based R97 (R97_MAJOR_FAST=54,
R97_MAJOR_SLOW=126 4h bars = 9d/21d) was REFUTED on the 731-day panel with
gross_t=+0.69, OOS_t=−0.29, maxDD=−30.10%, 3/6 positive windows. The 731-day
window is bear-dominated (2024-06 → 2026-06) and any single-leg factor
struggles to clear 3-check on it. We need a multi-cycle panel to know whether
R97's dual-horizon shape is genuinely a no-edge signal OR a panel artifact.

This module freezes the 11yr daily panel from /tmp/cometcloud_data/ohlcv_11yr.db
(48 symbols fetched via Binance public klines, 88,794 rows, 2017-08-17 → 2026-07-27)
and partitions it per cycle:
  2018 bear       (BTC -73%, peak-to-trough)
  2019 recovery   (BTC +94%)
  2020-21 bull    (BTC +800% from Mar 2020 to Nov 2021)
  2022 bear       (BTC -77% from Nov 2021 to Nov 2022)
  2023-24 recovery (BTC +400% from Nov 2022 to Mar 2024)
  2025-26 chop    (BTC range-bound, late-cycle)

Universe freeze: 27 symbols with ≥2000 days of daily history (multi-cycle
evidence; the §M-WO-2 acceptance bar). 6 symbols have full 2017+ history
(BTC/ETH/BNB/LTC/ADA/XRP) and are the deep-panel core.

Signal architecture (DAILY adaptation of R97):
  Major trend:   EMA200/EMA500 daily  (≈ 9mo / 22mo — multi-cycle ceiling/floor)
  Fast signal:   EMA50/EMA100 daily   (≈ 2.5mo / 5mo — mid-cycle confirmation)
  Direction rule (same as 4h R97 §2): major trend is the ceiling/floor;
                  fast signal CANNOT reverse major direction — if they
                  disagree, side = 0.
  Entry:         ADX14 ≥ 25 + DMI consistency (same as 4h R97)
  Gates NOT applied on 11yr:
    - CIS gate (CIS history only spans 2024+, no 11yr coverage)
    - Funding z-veto (funding history ~2019-2020+, partial 11yr coverage)
  ATR14 inverse-vol sizing (same as 4h R97)
  5d rebal; PIT lag ≥ 1 bar (no look-ahead)

What this gets us:
  - 6 distinct cycle windows (vs the 3 windows on 731-day panel)
  - Per-cycle sign stability (the §M-WO-2 acceptance criterion)
  - Episode-count audit per M-WO-1 (gap>7d on the OOS)
  - Direct test: is R97 dual-horizon edge a real cycle-balanced phenomenon,
    or a 731-day-bear-window artifact?

What this CANNOT do:
  - Match the 4h R97 verdict one-for-one (different lookbacks, different
    signal character). The 4h verdict is REFUTED on 731d; the daily verdict
    is a fresh test, not a re-run of the 4h test.

Usage:
  python3 src/research/validation/r97_panel_11yr.py
"""
from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

DB_PATH = Path("/tmp/cometcloud_data/ohlcv_11yr.db")
MIN_SPAN_DAYS = 2000  # §M-WO-2 multi-cycle threshold

# 6 fixed cycle windows (BTC peak-to-trough narrative; consistent across symbols
# because crypto is highly correlated at the cycle level).
CYCLE_WINDOWS = [
    ("C1_2018_bear",       date(2018, 1, 1), date(2018, 12, 31)),
    ("C2_2019_recovery",   date(2019, 1, 1), date(2019, 12, 31)),
    ("C3_2020_21_bull",    date(2020, 1, 1), date(2021, 11, 30)),
    ("C4_2022_bear",       date(2021, 12, 1), date(2022, 11, 30)),
    ("C5_2023_24_recovery", date(2022, 12, 1), date(2024, 3, 31)),
    ("C6a_2024_post_halving", date(2024, 4, 1), date(2024, 12, 31)),
    ("C6b_2025_26_late_cycle", date(2025, 1, 1), date(2026, 7, 27)),
]

# Frozen daily-bar R97 signal params (NOT the 4h numbers).
# R97_MAJOR_FAST/SLOW in 4h were 54/126 (9d/21d on 4h bars).
# On daily bars, the natural multi-cycle equivalent is 200/500 (≈9mo/22mo).
DAILY_R97_PARAMS = {
    "MAJOR_FAST":      200,    # ≈ 9 months (BTC cycle half)
    "MAJOR_SLOW":      500,    # ≈ 22 months (BTC full cycle)
    "FAST":             50,    # ≈ 2.5 months
    "SLOW":            100,    # ≈ 5 months
    "ADX_PERIOD":       14,
    "ADX_THRESHOLD":   25.0,
    "ATR_PERIOD":       14,
    "REBAL_DAYS":        5,
    "MAX_NAME_WEIGHT": 0.05,
    "MAX_BOOK_GROSS": 1.00,
    "PIT_LAG_BARS":      1,
}


@dataclass
class Panel11yr:
    """Frozen 11yr daily panel (long-form: one row per (symbol, trade_date))."""
    df: pd.DataFrame             # columns: symbol, trade_date, open, high, low, close, volume
    universe: list[str]
    cycle_windows: list = field(default_factory=lambda: CYCLE_WINDOWS)
    source: str = "binance_spot@/tmp/cometcloud_data/ohlcv_11yr.db"
    min_span_days: int = MIN_SPAN_DAYS
    first_date: str = ""
    last_date: str = ""


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"11yr panel DB not found: {db_path}. "
            f"Run: python3 scripts/fetch_ohlcv_11yr_binance.py"
        )
    return sqlite3.connect(db_path)


def _coverage(conn: sqlite3.Connection) -> pd.DataFrame:
    """Per-symbol span stats; filter to ≥min_span_days multi-cycle panel."""
    rows = conn.execute(
        "SELECT symbol, COUNT(*) AS n, MIN(trade_date) AS first, MAX(trade_date) AS last "
        "FROM ohlcv_11yr_daily GROUP BY symbol"
    ).fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "n", "first", "last"])
    df["first"] = pd.to_datetime(df["first"]).dt.date
    df["last"] = pd.to_datetime(df["last"]).dt.date
    df["span_days"] = df.apply(lambda r: (r["last"] - r["first"]).days, axis=1)
    df["n"] = df["n"].astype(int)
    return df.sort_values("span_days", ascending=False).reset_index(drop=True)


def freeze_universe(
    db_path: Path = DB_PATH,
    min_span_days: int = MIN_SPAN_DAYS,
    verbose: bool = True,
) -> Panel11yr:
    """Freeze the 11yr daily panel and multi-cycle universe.

    Returns a Panel11yr with:
      - df: long-form (symbol, trade_date, OHLCV), filtered to frozen universe
      - universe: sorted list of symbols with ≥min_span_days history
      - cycle_windows: 6 fixed calendar windows
    """
    conn = _connect(db_path)
    cov = _coverage(conn)
    if verbose:
        print(f"[R97-11yr] coverage: {len(cov)} symbols in DB")
        print(f"[R97-11yr] min_span_days: {min_span_days}")

    frozen = cov[cov["span_days"] >= min_span_days].copy()
    if len(frozen) < 12:
        raise ValueError(
            f"REFUSED_DATA: only {len(frozen)} symbols with ≥{min_span_days}d "
            f"history (need ≥12 for multi-cycle test)"
        )
    universe = sorted(frozen["symbol"].tolist())
    if verbose:
        print(f"[R97-11yr] frozen universe: {len(universe)} symbols")
        for sym in universe:
            r = frozen[frozen["symbol"] == sym].iloc[0]
            print(f"  {sym:8s}  n={r['n']:>5d}  {str(r['first']):10s} → {str(r['last']):10s}  ({r['span_days']}d)")
        print()
        # Cycle window coverage
        for cn, cs, ce in CYCLE_WINDOWS:
            n_in = ((frozen["first"] <= ce) & (frozen["last"] >= cs)).sum()
            print(f"  cycle {cn:24s} ({cs} → {ce}): {n_in}/{len(universe)} symbols covered")

    # Pull the actual rows
    placeholders = ",".join("?" * len(universe))
    df = pd.read_sql_query(
        f"SELECT symbol, trade_date, open, high, low, close, volume "
        f"FROM ohlcv_11yr_daily "
        f"WHERE symbol IN ({placeholders}) "
        f"ORDER BY symbol, trade_date",
        conn,
        params=universe,
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    conn.close()

    p = Panel11yr(
        df=df,
        universe=universe,
        first_date=str(df["trade_date"].min().date()),
        last_date=str(df["trade_date"].max().date()),
        min_span_days=min_span_days,
    )
    if verbose:
        print()
        print(f"[R97-11yr] panel: {len(df):,} rows × {df['symbol'].nunique()} symbols")
        print(f"[R97-11yr] range: {p.first_date} → {p.last_date}")
    return p


def to_wide(panel: Panel11yr, field: str = "close") -> pd.DataFrame:
    """Pivot long-form panel to wide: index=trade_date, columns=symbol, values=field."""
    return panel.df.pivot_table(index="trade_date", columns="symbol", values=field).sort_index()


def main() -> int:
    """CLI: print coverage + universe freeze, no signal run here (R97 11yr module does that)."""
    print("=" * 72)
    print("R97-11yr daily panel freeze")
    print("=" * 72)
    p = freeze_universe()
    print()
    print("Daily-bar R97 signal parameters (frozen, daily):")
    for k, v in DAILY_R97_PARAMS.items():
        print(f"  {k:20s} = {v}")
    print()
    print("Cycle windows (per §M-WO-2 acceptance):")
    for cn, cs, ce in p.cycle_windows:
        print(f"  {cn:24s}  {cs}  →  {ce}")
    print()
    close_wide = to_wide(p, "close")
    print(f"Wide close panel: {close_wide.shape[0]:,} days × {close_wide.shape[1]} symbols")
    print(f"NaN ratio: {close_wide.isna().sum().sum() / close_wide.size:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
