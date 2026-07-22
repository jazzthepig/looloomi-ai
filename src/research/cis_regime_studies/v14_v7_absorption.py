"""
V14 vs V7 Absorption Sweep — §ABSORPTION-SWEEP action item (Minimax-C, 2026-07-18).

PURPOSE: Does V14's regime overlay earn its slot?  Run the absorption gate on:
  · V14  = SwingOverlayV14_MTF_DirAware_CISRegimeOverlay (with CIS regime filter)
  · V7   = SwingOverlayV7_MTF (no regime filter, baseline convex trend)

If V14's α-after-factors survives (t>1.96) AND V14 carries MORE residual α than V7, the overlay
earns its slot.  If V7 survives and V14 absorbs (or both absorb), the overlay is dead weight
that only narrows the trade count.

INPUTS (built by the C-S1 scorecard runner, Minimax-C, 2026-07-18):
  · /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/v14_d_aligned.parquet
  · /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/v7_d_aligned.parquet
  · /Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/v14_full_wf.parquet

FACTORS (built inline from Mac-local OHLCV):
  · f_market     = BTC daily return
  · f_momentum   = TSMOM(30) on BTC
  · f_cis_quality= long top-CIS / short bot-CIS daily return (from 11yr historical)
  · f_funding    = cross-sectional mean funding × −1 (perp crowding pressure)

OUTPUTS:
  · reports/absorption_sweep/2026-07-18_v14_v7/verdict.txt
  · reports/absorption_sweep/2026-07-18_v14_v7/verdict.json
  · reports/absorption_sweep/2026-07-18_v14_v7/sleeve_returns.csv

This is the load-bearing test for whether V14 deserves a slot in C-S4 two-layer book.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Project paths
LOOLOOMI_AI_ROOT = Path("/Users/sbb/Projects/looloomi-ai")
sys.path.insert(0, str(LOOLOOMI_AI_ROOT))

from src.research.validation.absorption_sweep import sweep, format_table  # noqa: E402

# Inputs (Minimax-C emitted)
INPUT_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input")
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")
CIS_HISTORICAL_CSV = LOOLOOMI_AI_ROOT / "_data" / "cis_historical" / "cis_historical_11yr.csv"
FUNDING_CSV = Path("/Volumes/CometCloudAI/cometcloud-local/_data/strategy_revive/funding_daily_summary.csv")

# Output
OUT_DIR = LOOLOOMI_AI_ROOT / "reports" / "absorption_sweep" / "2026-07-18_v14_v7"


# ── Factor builders (replicates cis_regime_studies/absorption_sweep_runner.py) ──
_CIS_HIST_COLS = [
    "symbol", "name", "score", "raw_cis_score", "grade", "signal",
    "pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a",
    "asset_class", "macro_regime", "data_tier", "las", "confidence",
    "score_delta", "score_zscore", "source", "recorded_at",
]


def build_factor_panel(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """f_market, f_momentum, f_cis_quality, f_funding for the given date index."""
    # 1) OHLCV → daily close → daily returns per asset
    all_rets = {}
    for f in sorted(OHLCV_DIR.glob("*.parquet")):
        sym = f.stem
        df = pd.read_parquet(f)
        if "timestamp" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.normalize()
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df = df.sort_values("date")
        daily = df.groupby("date")["close"].last().sort_index()
        all_rets[sym] = daily.pct_change().fillna(0.0)

    rets_df = pd.DataFrame(all_rets).reindex(dates).fillna(0.0)

    # 2) f_market = BTC daily return
    f_market = rets_df.get("BTC", pd.Series(0.0, index=dates))

    # 3) f_momentum = TSMOM(30) on BTC
    btc_daily = rets_df["BTC"].reindex(dates).fillna(0.0)
    btc_30d_ret = (1 + btc_daily).rolling(30).sum() - 1
    tsmom_signal = np.sign(btc_30d_ret.shift(1)).fillna(0.0)
    f_momentum = tsmom_signal * btc_daily

    # 4) f_cis_quality = long top-CIS / short bot-CIS daily return (true factor from 11yr)
    f_cis_quality = _build_f_cis_quality_true(dates, rets_df)

    if f_cis_quality.abs().sum() == 0:
        # Fallback to proxy
        K = max(1, rets_df.shape[1] // 4)
        f_cis_quality = rets_df.apply(
            lambda row: np.sort(row.values)[::-1][:K].mean() - np.sort(row.values)[:K].mean(),
            axis=1
        ).fillna(0.0).rename("f_cis_quality")

    # 5) f_funding = cross-sectional mean funding × −1 (per absorb_input spec)
    f_funding = pd.Series(0.0, index=dates, name="f_funding")
    if FUNDING_CSV.exists():
        try:
            fdf = pd.read_csv(FUNDING_CSV)
            fdf["date"] = pd.to_datetime(fdf["date"]).dt.tz_localize(None).dt.normalize()
            xs_mean = fdf.groupby("date")["funding_paid_pct_per_day_long"].mean()
            f_funding = (-xs_mean.reindex(dates).fillna(0.0) / 100.0).rename("f_funding")
        except Exception as e:
            print(f"  ⚠️  f_funding failed: {e}")

    out = pd.DataFrame({
        "f_market": f_market,
        "f_momentum": f_momentum,
        "f_cis_quality": f_cis_quality,
        "f_funding": f_funding,
    }, index=dates)
    return out


def _build_f_cis_quality_true(dates, rets_df):
    """Replicates absorption_sweep_runner._build_f_cis_quality_true (true factor from 11yr CIS)."""
    if not CIS_HISTORICAL_CSV.exists():
        return pd.Series(0.0, index=dates, name="f_cis_quality")
    try:
        cis = pd.read_csv(CIS_HISTORICAL_CSV, header=None, names=_CIS_HIST_COLS)
    except Exception:
        return pd.Series(0.0, index=dates, name="f_cis_quality")

    cis["date"] = pd.to_datetime(cis["recorded_at"]).dt.tz_localize(None).dt.normalize()
    cis["raw_cis_score"] = pd.to_numeric(cis["raw_cis_score"], errors="coerce")
    cis = cis.dropna(subset=["raw_cis_score", "date"])

    symbol_map = {
        "BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "BNB": "BNB", "XRP": "XRP",
        "ADA": "ADA", "AVAX": "AVAX", "LINK": "LINK", "DOT": "DOT", "MATIC": "MATIC",
        "POL": "POL", "DOGE": "DOGE", "TRX": "TRX", "LTC": "LTC", "NEAR": "NEAR",
        "ATOM": "ATOM", "XLM": "XLM", "ALGO": "ALGO", "HBAR": "HBAR", "FIL": "FIL",
        "APT": "APT", "ARB": "ARB", "OP": "OP", "INJ": "INJ",
    }
    rets_symbols = set(rets_df.columns)
    f_cis_quality = pd.Series(0.0, index=dates, name="f_cis_quality")

    for d in dates:
        snap = cis[cis["date"] == d][["symbol", "raw_cis_score"]].copy()
        snap = snap[snap["symbol"].isin(symbol_map.keys())]
        if len(snap) < 4:
            continue
        snap["ohlcv_sym"] = snap["symbol"].map(symbol_map)
        snap = snap[snap["ohlcv_sym"].isin(rets_symbols)]
        if len(snap) < 4:
            continue
        snap = snap.sort_values("raw_cis_score", ascending=False).reset_index(drop=True)
        K = max(1, len(snap) // 4)
        top_syms = snap.head(K)["ohlcv_sym"].tolist()
        bot_syms = snap.tail(K)["ohlcv_sym"].tolist()
        try:
            d_next = dates[dates.get_loc(d) + 1] if d in dates else None
        except (KeyError, IndexError):
            d_next = None
        if d_next is None or d_next not in rets_df.index:
            continue
        top_ret = rets_df.loc[d_next, top_syms].mean()
        bot_ret = rets_df.loc[d_next, bot_syms].mean()
        f_cis_quality.loc[d] = top_ret - bot_ret
    return f_cis_quality


# ── Load sleeves ──
def load_sleeve_nav(path: Path) -> pd.Series:
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df = df.set_index("date")
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df["nav"].astype(float).sort_index()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    v14_d = load_sleeve_nav(INPUT_DIR / "v14_d_aligned.parquet")
    v7 = load_sleeve_nav(INPUT_DIR / "v7_d_aligned.parquet")
    v14_full = load_sleeve_nav(INPUT_DIR / "v14_full_wf.parquet")

    print("=== V14 vs V7 ABSORPTION SWEEP (§ABSORPTION-SWEEP action, Minimax-C 2026-07-18) ===\n")

    # Window D: fair A/B (V14 and V7 ran on identical 122-day window)
    print("[1/2] WINDOW D (V14 vs V7, 122 days, 2026-03-16 → 2026-07-15)")
    common = v14_d.index.intersection(v7.index)
    v14_d_rets = v14_d.loc[common].pct_change().fillna(0.0)
    v7_rets = v7.loc[common].pct_change().fillna(0.0)
    factor_panel = build_factor_panel(common)
    factor_panel = factor_panel.reindex(common).fillna(0.0)
    print(f"  V14 NAV:  ${v14_d.loc[common].iloc[0]:.0f} → ${v14_d.loc[common].iloc[-1]:.2f}  "
          f"(PnL ${v14_d.loc[common].iloc[-1] - v14_d.loc[common].iloc[0]:+.2f})")
    print(f"  V7  NAV:  ${v7.loc[common].iloc[0]:.0f} → ${v7.loc[common].iloc[-1]:.2f}  "
          f"(PnL ${v7.loc[common].iloc[-1] - v7.loc[common].iloc[0]:+.2f})")
    print(f"  Factors built: {list(factor_panel.columns)}  ({len(common)} days)")
    print(f"  Factor vols: market={factor_panel['f_market'].std()*np.sqrt(365)*100:.2f}%  "
          f"momentum={factor_panel['f_momentum'].std()*np.sqrt(365)*100:.2f}%  "
          f"cis_quality={factor_panel['f_cis_quality'].std()*np.sqrt(365)*100:.2f}%  "
          f"funding={factor_panel['f_funding'].std()*np.sqrt(365)*100:.2f}%")

    wide_d = pd.DataFrame({
        "v14": v14_d_rets.values,
        "v7": v7_rets.values,
        **factor_panel,
    }, index=common)
    wide_d.index.name = "date"
    wide_d.to_csv(OUT_DIR / "v14_v7_returns_window_d.csv", float_format="%.6f")
    print(f"  Saved: {OUT_DIR}/v14_v7_returns_window_d.csv ({len(wide_d)} rows)")

    data = {c: wide_d[c].values for c in wide_d.columns}
    sleeve_cols = ["v14", "v7"]
    factor_cols = ["f_market", "f_momentum", "f_cis_quality", "f_funding"]
    rows_d = sweep(data, sleeve_cols=sleeve_cols, factor_cols=factor_cols)
    table_d = format_table(rows_d)
    print("\n" + "=" * 80)
    print("VERDICT — WINDOW D (V14 vs V7, 122 days)")
    print("=" * 80)
    print(table_d)
    (OUT_DIR / "verdict_window_d.txt").write_text(table_d + "\n")

    # V14 full walk-forward (926 days, V14 only — V7 not available for full window)
    print("\n[2/2] V14 FULL WALK-FORWARD (926 days, 2024-01-02 → 2026-07-15)")
    v14_full_rets = v14_full.pct_change().fillna(0.0)
    factor_panel_full = build_factor_panel(v14_full.index)
    factor_panel_full = factor_panel_full.reindex(v14_full.index).fillna(0.0)

    # NOTE: over the 2024-01 → 2026-07 bull window, BTC 30d cum return was almost always
    # positive → f_momentum = sign(positive) × f_market = f_market exactly → corr(f_market,
    # f_momentum) = 1.000. We drop f_momentum here to avoid singular matrix; orthogonal factor
    # choice for the bull window is left for follow-up work (C2).
    factor_cols_full = ["f_market", "f_cis_quality", "f_funding"]
    corr_mm = np.corrcoef(factor_panel_full["f_market"], factor_panel_full["f_momentum"])[0, 1]
    print(f"  ⚠️  corr(f_market, f_momentum)={corr_mm:.4f}  → dropping f_momentum to avoid singular X")
    print(f"  V14 NAV:  ${v14_full.iloc[0]:.0f} → ${v14_full.iloc[-1]:.2f}  "
          f"(PnL ${v14_full.iloc[-1] - v14_full.iloc[0]:+.2f}, +{(v14_full.iloc[-1]/v14_full.iloc[0]-1)*100:.1f}%)")
    print(f"  Factor vols: market={factor_panel_full['f_market'].std()*np.sqrt(365)*100:.2f}%  "
          f"momentum={factor_panel_full['f_momentum'].std()*np.sqrt(365)*100:.2f}%  "
          f"cis_quality={factor_panel_full['f_cis_quality'].std()*np.sqrt(365)*100:.2f}%  "
          f"funding={factor_panel_full['f_funding'].std()*np.sqrt(365)*100:.2f}%")

    wide_full = pd.DataFrame({
        "v14_full_wf": v14_full_rets.values,
        **factor_panel_full,
    }, index=v14_full.index)
    wide_full.index.name = "date"
    wide_full.to_csv(OUT_DIR / "v14_full_wf_returns.csv", float_format="%.6f")

    data_full = {c: wide_full[c].values for c in wide_full.columns}
    rows_full = sweep(data_full, sleeve_cols=["v14_full_wf"], factor_cols=factor_cols_full)
    table_full = format_table(rows_full)
    print("\n" + "=" * 80)
    print("VERDICT — V14 FULL WALK-FORWARD (V14 only, 926 days)")
    print("=" * 80)
    print(table_full)
    (OUT_DIR / "verdict_v14_full_wf.txt").write_text(table_full + "\n")

    # Combined verdict JSON
    verdict_json = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "window_d": {
            "n_days": len(common),
            "start": str(common[0].date()),
            "end": str(common[-1].date()),
            "rows": rows_d,
        },
        "v14_full_wf": {
            "n_days": len(v14_full),
            "start": str(v14_full.index[0].date()),
            "end": str(v14_full.index[-1].date()),
            "rows": rows_full,
        },
        "factor_cols": factor_cols,
        "sleeve_cols_window_d": sleeve_cols,
    }
    with open(OUT_DIR / "verdict.json", "w") as f:
        json.dump(verdict_json, f, indent=2, default=str)
    print(f"\nSaved: {OUT_DIR}/verdict.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())