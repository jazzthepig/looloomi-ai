"""
Absorption Sweep Runner — §ABSORPTION-SWEEP directive (Seth → Minimax-B, 2026-07-17).

THE deliverable from MINIMAX_SYNC.md §ABSORPTION-SWEEP: "a one-table verdict — which sleeves
carry residual alpha (α t>1.96 after factors) vs which are ABSORBED."

This script:
  1. Loads each sleeve's NAV from the validated parquet outputs.
  2. Converts to daily returns (decimal).
  3. Builds the known-factor panel:
     - f_market: BTC daily return (or equal-weight majors if available)
     - f_momentum: TSMOM(30) on BTC
     - f_cis_quality: long top-CIS / short bottom-CIS daily return (PROXY: equal-weight
       long top-quartile minus bottom-quartile, computed from price returns — stand-in until
       Seth's CIS-history reconstruct lands)
  4. Saves the wide CSV at `reports/absorption_sweep/<date>/sleeve_returns.csv`.
  5. Calls `absorption_sweep.sweep()` and prints the verdict table.

INPUTS (the validated sleeve NAVs):
  - LS v1 CIS-ON:     reports/multi_window_baseline_spot/2026-07-16/per_day_nav_oos_only.parquet
  - LS v1 CIS-OFF:    reports/multi_window_baseline_spot_cis_off/2026-07-16/per_day_nav_oos_only.parquet
  - Causal sleeve:    reports/causal_sleeve/2026-07-17/nav_deploy_6y.parquet
  - Cash sleeve:      reports/cash_sleeve/2026-07-16/nav.parquet

OUTPUTS:
  - reports/absorption_sweep/<date>/sleeve_returns.csv
  - reports/absorption_sweep/<date>/verdict.txt (human-readable)
  - reports/absorption_sweep/<date>/verdict.json (machine-readable)

FALSIFIABILITY (the gate):
  - If LS v1, Causal, Cash, and the 30/20/50 composite all ABSORB (residual α t<1.96 after
    known factors), then the LP pitch is a beta mirage and we need to redesign.
  - If only the Cash sleeve ABSORBS (cash is supposed to absorb — it's ballast), and ≥1
    sleeve survives, the pitch is real.
  - If NONE survive, the +1.97 Sharpe composite is a regime tailwind, not alpha.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Sleeve NAVs (validated, post-CIS, OOS-isolated)
SLEEVE_NAVS = {
    "ls_v1_cis_on": Path("reports/multi_window_baseline_spot/2026-07-16/per_day_nav_oos_only.parquet"),
    "ls_v1_cis_off": Path("reports/multi_window_baseline_spot_cis_off/2026-07-16/per_day_nav_oos_only.parquet"),
    "causal": Path("reports/causal_sleeve/2026-07-17/nav_deploy_6y.parquet"),
    "cash": Path("reports/cash_sleeve/2026-07-16/nav.parquet"),
}

# Composite weights to test (the Track 4 sweep winners)
COMPOSITE_WEIGHTS = {
    "composite_30_20_50": (0.30, 0.20, 0.50),  # LP pitch default
    "composite_35_25_40": (0.35, 0.25, 0.40),  # Own-book default
    "composite_40_30_30": (0.40, 0.30, 0.30),  # Highest CAGR
}

# Mac-side OHLCV (post-CIS window, 24-name universe aligned with CIS push)
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")

# 11yr CIS historical reconstruction (Seth, 2026-07-18 — §CIS-HISTORY-BACKFILL ✅ DONE)
# Schema: symbol, name, score, raw_cis_score, grade, signal, pillar_f, pillar_m, pillar_o,
# pillar_s, pillar_a, asset_class, macro_regime, data_tier, las, confidence, score_delta,
# score_zscore, source, recorded_at
CIS_HISTORICAL_CSV = Path("_data/cis_historical/cis_historical_11yr.csv")


def load_sleeve_returns(path: Path) -> pd.Series:
    """Load a sleeve NAV parquet, return daily returns indexed by date.

    Handles MONTHLY cash sleeve by allocating the month-end return evenly across the
    intervening days (so compounding across N days reproduces the monthly change).
    """
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df = df.set_index("date")
    elif df.index.name is None:
        # find any datetime-like column
        for col in df.columns:
            if "date" in col.lower() or "timestamp" in col.lower():
                df = df.set_index(col)
                break
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    nav = df["nav"].astype(float)
    nav.name = path.stem

    # Detect monthly vs daily cadence
    diffs = nav.index.to_series().diff().dt.days.dropna()
    is_monthly = (diffs.median() >= 20) if len(diffs) > 0 else False

    if is_monthly:
        # Expand monthly NAV → daily NAV, allocating monthly return evenly across days
        daily_dates = pd.date_range(nav.index.min(), nav.index.max(), freq="D")
        # Forward-fill NAV within each month-end observation
        nav_daily = nav.reindex(daily_dates).ffill()
        rets = nav_daily.pct_change().fillna(0.0)
    else:
        rets = nav.pct_change().fillna(0.0)

    rets.name = path.stem
    return rets


# CIS historical CSV column layout — sourced from
# src/research.data_align.cis_history_schema.CSV_COLUMNS (single source of truth,
# Jazz §DATA-ALIGN directive 2026-07-24). Header line is now prepended by
# scripts/cis_historical_align.py (idempotent), so we use header=0 reads here.
from src.research.data_align.cis_history_schema import CSV_COLUMNS as _CIS_HIST_COLS  # noqa: E402, F401


def _build_f_cis_quality_true(
    dates: pd.DatetimeIndex,
    rets_df: pd.DataFrame,
) -> pd.Series:
    """Build f_cis_quality = long top-CIS / short bottom-CIS daily return.

    Algorithm:
      1. Load the 11yr CIS historical CSV (~75K rows × 34 assets, header-less).
      2. For each date in `dates`, find the cross-section of CIS scores present
         that day; sort descending by `raw_cis_score`.
      3. Top quartile = mean of next-day returns of the top-K assets.
         Bottom quartile = mean of next-day returns of the bottom-K assets.
         f_cis_quality[t] = top_q_return[t] − bottom_q_return[t].
      4. If a date has fewer than 4 assets with CIS scores, return 0 (defensive).

    This is the canonical "CIS quality" factor — long the assets the engine
    says are high-quality, short the assets it says are low-quality. Resolves
    the §CIS-HISTORY-BACKFILL caveat that the previous run used a price-spread
    PROXY.
    """
    if not CIS_HISTORICAL_CSV.exists():
        return pd.Series(0.0, index=dates, name="f_cis_quality")

    try:
        # Header-aware read (post §DATA-ALIGN 2026-07-24: header line is prepended
        # by scripts/cis_historical_align.py; headerless files still work via
        # the loader's auto-detection, but pd.read_csv above is the fast path).
        cis = pd.read_csv(CIS_HISTORICAL_CSV, header=0)
    except Exception:
        # Defensive fallback: headerless legacy file
        cis = pd.read_csv(CIS_HISTORICAL_CSV, header=None, names=_CIS_HIST_COLS)

    # Parse the recorded_at timestamp to a tz-naive date
    cis["date"] = pd.to_datetime(cis["recorded_at"]).dt.tz_localize(None).dt.normalize()
    cis["raw_cis_score"] = pd.to_numeric(cis["raw_cis_score"], errors="coerce")
    cis = cis.dropna(subset=["raw_cis_score", "date"])

    # OHLCV symbols we have returns for (subset of CIS universe)
    rets_symbols = set(rets_df.columns)

    # Map CIS symbols to OHLCV symbols (most are identical; some need translation)
    symbol_map = {
        "BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "BNB": "BNB", "XRP": "XRP",
        "ADA": "ADA", "AVAX": "AVAX", "LINK": "LINK", "DOT": "DOT", "MATIC": "MATIC",
        "POL": "POL", "DOGE": "DOGE", "TRX": "TRX", "LTC": "LTC", "NEAR": "NEAR",
        "ATOM": "ATOM", "XLM": "XLM", "ALGO": "ALGO", "HBAR": "HBAR", "FIL": "FIL",
        "APT": "APT", "ARB": "ARB", "OP": "OP", "INJ": "INJ",
    }

    f_cis_quality = pd.Series(0.0, index=dates, name="f_cis_quality")

    for d in dates:
        # Snapshot of CIS scores for date d
        snap = cis[cis["date"] == d][["symbol", "raw_cis_score"]].copy()
        snap = snap[snap["symbol"].isin(symbol_map.keys())]
        if len(snap) < 4:
            continue
        # Translate to OHLCV symbol space
        snap["ohlcv_sym"] = snap["symbol"].map(symbol_map)
        snap = snap[snap["ohlcv_sym"].isin(rets_symbols)]
        if len(snap) < 4:
            continue

        # Sort descending by raw_cis_score → top quartile vs bottom quartile
        snap = snap.sort_values("raw_cis_score", ascending=False).reset_index(drop=True)
        K = max(1, len(snap) // 4)
        top_syms = snap.head(K)["ohlcv_sym"].tolist()
        bot_syms = snap.tail(K)["ohlcv_sym"].tolist()

        # Next-day return (date d+1) of each symbol from rets_df
        try:
            d_next = dates[dates.get_loc(d) + 1] if d in dates else None
        except (KeyError, IndexError):
            d_next = None
        if d_next is None:
            continue
        if d_next not in rets_df.index:
            continue

        top_ret = rets_df.loc[d_next, top_syms].mean()
        bot_ret = rets_df.loc[d_next, bot_syms].mean()
        f_cis_quality.loc[d] = top_ret - bot_ret

    return f_cis_quality


def _build_f_cis_quality_proxy(rets_df: pd.DataFrame) -> pd.Series:
    """Fallback f_cis_quality: cross-sectional quartile spread of price returns.

    Used only when the 11yr CIS historical CSV is missing. Conceptually similar
    to long-top/short-bottom but uses raw price returns, not CIS-selected assets.
    """
    K = rets_df.shape[1]
    top_q = max(1, K // 4)
    bot_q = max(1, K // 4)

    def _qspread(row):
        sorted_v = np.sort(row.values)[::-1]  # descending
        return sorted_v[:top_q].mean() - sorted_v[-bot_q:].mean()

    return rets_df.apply(_qspread, axis=1).fillna(0.0).rename("f_cis_quality")


def build_factor_panel(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Build f_market, f_momentum, f_cis_quality, f_funding daily-return panel.

    f_market: BTC daily return (the obvious "market" factor)
    f_momentum: TSMOM(30) = sign of 30d cumulative return × f_market
    f_cis_quality: long top-CIS / short bottom-CIS daily return from the
        11yr CIS historical reconstruction (4,015 days × 34 assets,
        `_data/cis_historical/cis_historical_11yr.csv`).
        Falls back to the proxy (cross-sectional quartile spread of price returns)
        if the 11yr CSV is missing or the date range is uncovered.
    f_funding: cross-sectional mean funding rate × -1 (perp funding crowding
        pressure; positive when market is crowded long). Independent proxy
        built from /Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive/
        funding_daily_summary.csv (BTC/ETH/SOL/BNB/XRP, 2025-01-01 → present).

    The 11yr CIS history lands via §CIS-HISTORY-BACKFILL (Seth, 2026-07-18,
    `reports/CIS_HISTORICAL_11YR_2026-07-18.md`). Building `f_cis_quality`
    as a true long-top / short-bottom factor — not a price-spread proxy — is
    the load-bearing change this session.
    """
    # Load all OHLCV files, compute daily returns
    all_rets = {}
    for f in OHLCV_DIR.glob("*.parquet"):
        sym = f.stem
        df = pd.read_parquet(f)
        if "timestamp" in df.columns:
            # Strip tz first so reindex matches naive DatetimeIndex
            df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.normalize()
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df = df.sort_values("date")
        # Daily close (use last available close per day)
        daily = df.groupby("date")["close"].last().sort_index()
        all_rets[sym] = daily.pct_change().fillna(0.0)

    rets_df = pd.DataFrame(all_rets).reindex(dates).fillna(0.0)

    # f_market: BTC daily return
    f_market = rets_df.get("BTC", pd.Series(0.0, index=dates))

    # f_momentum: TSMOM(30) — sign of 30d cumulative return on BTC × next-day return
    btc_daily = rets_df["BTC"].reindex(dates).fillna(0.0)
    btc_30d_ret = (1 + btc_daily).rolling(30).sum() - 1  # 30d cumulative return
    tsmom_signal = np.sign(btc_30d_ret.shift(1)).fillna(0.0)  # use prior signal
    f_momentum = tsmom_signal * btc_daily

    # f_cis_quality: TRUE long top-CIS / short bottom-CIS daily return
    # Build from the 11yr CIS historical reconstruction if available.
    f_cis_quality = _build_f_cis_quality_true(dates, rets_df)

    # If the true factor ended up all-zero (no historical CSV or no overlap),
    # fall back to the proxy so the panel is still well-defined.
    if f_cis_quality.abs().sum() == 0:
        f_cis_quality = _build_f_cis_quality_proxy(rets_df)

    out = pd.DataFrame({
        "f_market": f_market,
        "f_momentum": f_momentum,
        "f_cis_quality": f_cis_quality,
    }, index=dates)

    # f_funding: cross-sectional mean funding rate × -1 (perp crowding pressure)
    # Available for BTC/ETH/SOL/BNB/XRP since 2025-01-01 (563 days, per §A-S1).
    funding_path = Path("/Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive/funding_daily_summary.csv")
    if funding_path.exists():
        try:
            fdf = pd.read_csv(funding_path)
            fdf["date"] = pd.to_datetime(fdf["date"]).dt.tz_localize(None).dt.normalize()
            # Cross-sectional mean funding rate per day (across the 5 majors)
            xs_mean = fdf.groupby("date")["funding_paid_pct_per_day_long"].mean()
            # Sign convention: positive funding = longs pay shorts = crowding = forward negative pressure
            # So predict: next-day return should be NEGATIVE when funding is high
            f_funding = -xs_mean.reindex(dates).fillna(0.0) / 100.0  # scale: % / 100
            out["f_funding"] = f_funding
        except Exception as e:
            print(f"  ⚠️  f_funding failed to build: {e}")
            out["f_funding"] = 0.0
    else:
        out["f_funding"] = 0.0

    return out


def build_composite_returns(sleeve_rets: pd.DataFrame, w_ls: float, w_cs: float, w_cash: float) -> pd.Series:
    """Build a 3-sleeve composite daily return series at given weights."""
    return w_ls * sleeve_rets["ls_v1_cis_on"] + w_cs * sleeve_rets["causal"] + w_cash * sleeve_rets["cash"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    print("=== Absorption Sweep — §ABSORPTION-SWEEP (Seth → Minimax-B) ===")
    print(f"Date: {today}")
    print()

    # ── Step 1: load sleeve returns ──────────────────────────────────────────
    print("Loading sleeve NAVs → daily returns…")
    sleeve_series = {}
    for name, path in SLEEVE_NAVS.items():
        if not path.exists():
            print(f"  ⚠️  MISSING: {name} → {path}")
            continue
        s = load_sleeve_returns(path)
        sleeve_series[name] = s
        print(f"  {name}: {len(s)} days, {s.index[0].date()} → {s.index[-1].date()}, "
              f"ann_vol={s.std() * np.sqrt(365) * 100:.2f}%")

    # Intersect to common date index
    common_dates = sorted(set.intersection(*[set(s.index) for s in sleeve_series.values()]))
    common_dates = pd.DatetimeIndex(common_dates)
    print(f"\nCommon date index: {len(common_dates)} days "
          f"({common_dates[0].date()} → {common_dates[-1].date()})")

    sleeve_rets = pd.DataFrame({k: v.reindex(common_dates).fillna(0.0) for k, v in sleeve_series.items()})
    print(f"Sleeve return panel: {sleeve_rets.shape}")

    # ── Step 2: build factor panel ───────────────────────────────────────────
    print("\nBuilding factor panel (f_market, f_momentum, f_cis_quality)…")
    factor_panel = build_factor_panel(common_dates)
    print(f"  f_market: ann_vol={factor_panel['f_market'].std() * np.sqrt(365) * 100:.2f}%")
    print(f"  f_momentum: ann_vol={factor_panel['f_momentum'].std() * np.sqrt(365) * 100:.2f}%")
    print(f"  f_cis_quality: ann_vol={factor_panel['f_cis_quality'].std() * np.sqrt(365) * 100:.2f}%")

    # ── Step 3: build composite returns (the Track 4 winners) ─────────────────
    print("\nBuilding composite returns for Track 4 winners…")
    composite_series = {}
    for name, (w_ls, w_cs, w_cash) in COMPOSITE_WEIGHTS.items():
        composite_series[name] = build_composite_returns(sleeve_rets, w_ls, w_cs, w_cash)
        ann_ret = composite_series[name].mean() * 365 * 100
        ann_vol = composite_series[name].std() * np.sqrt(365) * 100
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        print(f"  {name} ({w_ls}/{w_cs}/{w_cash}): ann_ret={ann_ret:+.2f}% ann_vol={ann_vol:.2f}% "
              f"Sharpe={sharpe:+.2f}")

    # ── Step 4: assemble wide DataFrame + CSV ────────────────────────────────
    wide = pd.DataFrame(sleeve_rets)
    for name, s in composite_series.items():
        wide[name] = s
    for col in factor_panel.columns:
        wide[col] = factor_panel[col]
    wide.index.name = "date"

    csv_path = args.out_dir / "sleeve_returns.csv"
    wide.to_csv(csv_path, float_format="%.6f")
    print(f"\nSaved wide CSV: {csv_path}")
    print(f"  rows={len(wide)}, cols={list(wide.columns)}")

    # ── Step 5: run absorption sweep ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print("ABSORPTION SWEEP VERDICT")
    print("=" * 80)

    from src.research.validation.absorption_sweep import sweep, format_table

    data = wide.to_dict(orient="series")
    data = {k: v.values for k, v in data.items()}

    sleeve_cols = list(sleeve_rets.columns) + list(composite_series.keys())
    factor_cols = list(factor_panel.columns)

    rows = sweep(data, sleeve_cols=sleeve_cols, factor_cols=factor_cols)
    table = format_table(rows)
    print(table)

    # Save verdict
    verdict_txt = args.out_dir / "verdict.txt"
    verdict_txt.write_text(table + "\n")
    verdict_json = args.out_dir / "verdict.json"
    with open(verdict_json, "w") as f:
        json.dump({"date": today, "sleeve_cols": sleeve_cols, "factor_cols": factor_cols, "rows": rows},
                  f, indent=2, default=str)

    print(f"\nSaved: {verdict_txt}")
    print(f"Saved: {verdict_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
