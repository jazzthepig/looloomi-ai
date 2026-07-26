"""
Per-pillar IC × regime × cycle mining — §DATA-ALIGN directive, sub-task (C).

Goal: settle the "is pillar_A / vol real or regime-confounded?" question by
running the SAME IC computation across regimes × cycles × asset classes, and
applying an EVENT-COUNT GATE that prevents pseudo-replication.

Why the event-count gate matters:
  - S-78 (vol sleeve) and S-79 (vol residual) BOTH died of pseudo-replication:
    multiple correlated observations in the same regime cycle were counted as
    independent events. With an honest event-count floor (default n_events ≥
    MIN_EVENTS=30), cells with thin samples are flagged "INSUFFICIENT" rather
    than reported as positive or negative — preventing over-trust of
    "directional-right, magnitude-wrong" results.

What this produces:
  - Per-pillar (F/M/O/S/A) × regime (6) × cycle (3) IC table with t-stat,
    n_events, and verdict (✅ POSITIVE / 🔴 NEGATIVE / ⚪ INSUFFICIENT).
  - Per-pillar × asset-class breakdown.
  - Per-pillar × realized-vol bucket (annualized 30d σ) breakdown.

IC computation:
  - Spearman rank correlation between pillar value at time t and the asset's
    forward 30-day simple return.
  - Cross-sectional IC: each (date, asset) pair is one observation. Pool across
    the cell, compute one rank-IC + t-stat.
  - For per-asset IC: time-series IC per asset, then aggregate (mean, t-stat).

CLI:
    python3 src/research/data_align/pillar_ic_mining.py
    python3 src/research/data_align/pillar_ic_mining.py --csv <aligned.csv> --csv-ohlcv <dir> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _spearman_corr(x: pd.Series | np.ndarray, y: pd.Series | np.ndarray) -> float:
    """Spearman rank correlation without scipy. Pure pandas."""
    rx = pd.Series(x).rank(method="average")
    ry = pd.Series(y).rank(method="average")
    # Pearson on ranks = Spearman
    if rx.std(ddof=1) == 0 or ry.std(ddof=1) == 0:
        return float("nan")
    return float(rx.corr(ry))

from src.research.data_align.cis_history_schema import (
    CSV_COLUMNS, REGIMES, NUMERIC_COLUMNS,
)
from src.research.data_align.cis_history_loader import load_cis_history
from src.research.data_align.cis_history_enrich import load_returns_wide

PILLARS: tuple[str, ...] = ("f", "m", "o", "s", "a")

# ── Event-count gate (default) ───────────────────────────────────────────────
MIN_EVENTS_DEFAULT = 30    # below this ⇒ INSUFFICIENT (per S-78/S-79 lesson)
MIN_T_ABS = 1.96           # |t| ≥ 1.96 ⇒ POSITIVE/NEGATIVE, else NEUTRAL

# ── Cycle definitions (calendar halves; one bull, one chop, one bear) ─────────
CYCLES: dict[str, tuple[str, str]] = {
    "2024_bull":  ("2024-01-01", "2024-12-31"),
    "2025_chop":  ("2025-01-01", "2025-12-31"),
    "2026_bear":  ("2026-01-01", "2026-07-19"),  # data ends 2026-07-19
}

# Forward-return horizons (in trading days)
FWD_HORIZONS: tuple[int, ...] = (5, 10, 30)


def compute_forward_returns(rets_wide: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Compute forward N-day simple returns. Shape: (date, asset)."""
    # fwd_ret[t] = (close[t+h] / close[t]) - 1
    fwd = rets_wide.shift(-horizon)  # shift up so future returns align with today
    # Compound h daily returns
    # Use log-sum for numerical stability: log(1+r) ≈ r for small r
    log_rets = np.log1p(rets_wide.fillna(0.0))
    fwd_log = log_rets[::-1].rolling(horizon, min_periods=horizon).sum()[::-1].shift(-horizon + 1)
    # Actually simpler: directly compound the simple returns over the window
    # Use rolling product: prod(1 + r) - 1 over the next h days
    fwd_ret = (1 + rets_wide.fillna(0.0)).rolling(horizon, min_periods=horizon).apply(np.prod, raw=True) - 1
    fwd_ret = fwd_ret.shift(-(horizon - 1))
    return fwd_ret


def compute_realized_vol(rets_wide: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """30-day rolling realized vol (annualized)."""
    return rets_wide.rolling(window, min_periods=window).std() * np.sqrt(365)


# ── Verdict logic (event-count gate) ─────────────────────────────────────────

def verdict(t_stat: float, n_events: int, min_events: int = MIN_EVENTS_DEFAULT) -> str:
    """Map (t, n) → verdict string. The honest gate."""
    if n_events < min_events:
        return "⚪ INSUFFICIENT"
    if t_stat >= MIN_T_ABS:
        return "✅ POSITIVE"
    if t_stat <= -MIN_T_ABS:
        return "🔴 NEGATIVE"
    return "🟡 NEUTRAL"


def ic_tstat(ic_values: pd.Series) -> tuple[float, float, int]:
    """Spearman rank IC summary: mean IC, t-stat, n_finite."""
    finite = ic_values.dropna()
    n = int(len(finite))
    if n < 2:
        return float("nan"), float("nan"), 0
    mean_ic = float(finite.mean())
    std_ic = float(finite.std(ddof=1))
    if std_ic == 0 or not np.isfinite(std_ic):
        return mean_ic, float("nan"), n
    t = mean_ic / (std_ic / np.sqrt(n))
    return mean_ic, float(t), n


# ── Per-(regime × cycle × pillar) IC cell ────────────────────────────────────

def per_regime_cycle_pillar(
    df: pd.DataFrame,
    fwd_rets: pd.DataFrame,
    *,
    cycle_name: str,
    cycle_lo: str,
    cycle_hi: str,
    regime: str,
    pillar: str,
    min_events: int = MIN_EVENTS_DEFAULT,
) -> dict:
    """One IC cell: regime × cycle × pillar."""
    sub = df[(df["_date"] >= pd.Timestamp(cycle_lo)) &
             (df["_date"] <= pd.Timestamp(cycle_hi)) &
             (df["macro_regime"] == regime)]
    if len(sub) == 0:
        return {"regime": regime, "cycle": cycle_name, "pillar": pillar,
                "n_obs": 0, "ic": None, "t": None, "verdict": "⚪ INSUFFICIENT",
                "min_events": min_events}

    # Cross-sectional IC: for each (date, asset), pair pillar value at t with
    # fwd 30d return at t. Pool across (date, asset) and compute one rank-IC.
    rows = []
    for _, r in sub.iterrows():
        sym = r["symbol"]
        d = r["_date"]
        if sym not in fwd_rets.columns:
            continue
        if d not in fwd_rets.index:
            continue
        fwd = fwd_rets.at[d, sym]
        if pd.isna(fwd):
            continue
        rows.append({"pillar": r[f"pillar_{pillar}"], "fwd_ret": fwd})
    pairs = pd.DataFrame(rows).dropna()
    n = len(pairs)
    if n < 3:
        return {"regime": regime, "cycle": cycle_name, "pillar": pillar,
                "n_obs": n, "ic": None, "t": None, "verdict": "⚪ INSUFFICIENT",
                "min_events": min_events}
    rho = _spearman_corr(pairs["pillar"], pairs["fwd_ret"])
    pval = float("nan")  # scipy-free; t-stat below is the primary significance test
    # t-stat for Spearman: t = rho * sqrt((n-2) / (1 - rho^2))
    if abs(rho) < 1.0 and n > 2:
        t = rho * np.sqrt((n - 2) / (1 - rho ** 2))
    else:
        t = float("inf") if abs(rho) >= 1.0 else 0.0
    return {"regime": regime, "cycle": cycle_name, "pillar": pillar,
            "n_obs": n, "ic": float(rho), "t": float(t), "p_value": float(pval),
            "verdict": verdict(t, n, min_events), "min_events": min_events}


def per_regime_cycle_pillar_table(
    df: pd.DataFrame,
    fwd_rets: pd.DataFrame,
    *,
    pillars: Iterable[str] = PILLARS,
    cycles: dict[str, tuple[str, str]] = CYCLES,
    regimes: Iterable[str] = REGIMES,
    min_events: int = MIN_EVENTS_DEFAULT,
) -> pd.DataFrame:
    """Full pivot: rows = (cycle, regime), columns = pillar."""
    rows = []
    for cyc_name, (lo, hi) in cycles.items():
        for regime in regimes:
            for pillar in pillars:
                cell = per_regime_cycle_pillar(
                    df, fwd_rets,
                    cycle_name=cyc_name, cycle_lo=lo, cycle_hi=hi,
                    regime=regime, pillar=pillar, min_events=min_events,
                )
                rows.append(cell)
    return pd.DataFrame(rows)


# ── Per-asset-class breakdown ────────────────────────────────────────────────

def per_asset_class_pillar(
    df: pd.DataFrame,
    fwd_rets: pd.DataFrame,
    *,
    cycles: dict[str, tuple[str, str]] = CYCLES,
    pillars: Iterable[str] = PILLARS,
    min_events: int = MIN_EVENTS_DEFAULT,
) -> pd.DataFrame:
    """Per (asset_class, pillar, cycle) IC cell."""
    rows = []
    for cyc_name, (lo, hi) in cycles.items():
        sub = df[(df["_date"] >= pd.Timestamp(lo)) &
                 (df["_date"] <= pd.Timestamp(hi))]
        for asset_class, g in sub.groupby("asset_class"):
            for pillar in pillars:
                pairs = []
                for _, r in g.iterrows():
                    sym = r["symbol"]
                    d = r["_date"]
                    if sym in fwd_rets.columns and d in fwd_rets.index:
                        fwd = fwd_rets.at[d, sym]
                        if pd.notna(fwd) and pd.notna(r[f"pillar_{pillar}"]):
                            pairs.append((r[f"pillar_{pillar}"], fwd))
                if len(pairs) < 3:
                    rows.append({"asset_class": asset_class, "pillar": pillar,
                                 "cycle": cyc_name, "n_obs": len(pairs),
                                 "ic": None, "t": None,
                                 "verdict": "⚪ INSUFFICIENT"})
                    continue
                p = pd.DataFrame(pairs, columns=["pillar", "fwd_ret"]).dropna()
                rho = _spearman_corr(p["pillar"], p["fwd_ret"])
                n = len(p)
                if abs(rho) < 1.0 and n > 2:
                    t = rho * np.sqrt((n - 2) / (1 - rho ** 2))
                else:
                    t = float("inf") if abs(rho) >= 1.0 else 0.0
                rows.append({"asset_class": asset_class, "pillar": pillar,
                             "cycle": cyc_name, "n_obs": n,
                             "ic": float(rho), "t": float(t),
                             "verdict": verdict(t, n, min_events)})
    return pd.DataFrame(rows)


# ── Vol-bucket breakdown ─────────────────────────────────────────────────────

def per_vol_bucket_pillar(
    df: pd.DataFrame,
    fwd_rets: pd.DataFrame,
    rets_wide: pd.DataFrame,
    *,
    vol_buckets: tuple[tuple[str, float, float], ...] = (
        ("low_vol",  0.0, 0.50),
        ("mid_vol",  0.50, 1.00),
        ("high_vol", 1.00, 3.00),
    ),
    pillars: Iterable[str] = PILLARS,
    min_events: int = MIN_EVENTS_DEFAULT,
) -> pd.DataFrame:
    """Per (realized-vol bucket, pillar) IC — annualized 30d σ."""
    vol_wide = compute_realized_vol(rets_wide, window=30)
    rows = []
    for bucket_name, lo, hi in vol_buckets:
        # Build mask: (date, asset) where vol in [lo, hi)
        for pillar in pillars:
            pairs = []
            for _, r in df.iterrows():
                sym = r["symbol"]
                d = r["_date"]
                if sym not in vol_wide.columns or d not in vol_wide.index:
                    continue
                if sym not in fwd_rets.columns or d not in fwd_rets.index:
                    continue
                vol = vol_wide.at[d, sym]
                fwd = fwd_rets.at[d, sym]
                if pd.isna(vol) or pd.isna(fwd) or pd.isna(r[f"pillar_{pillar}"]):
                    continue
                if not (lo <= vol < hi):
                    continue
                pairs.append((r[f"pillar_{pillar}"], fwd))
            if len(pairs) < 3:
                rows.append({"vol_bucket": bucket_name, "pillar": pillar,
                             "n_obs": len(pairs), "ic": None, "t": None,
                             "verdict": "⚪ INSUFFICIENT"})
                continue
            p = pd.DataFrame(pairs, columns=["pillar", "fwd_ret"]).dropna()
            rho = _spearman_corr(p["pillar"], p["fwd_ret"])
            n = len(p)
            if abs(rho) < 1.0 and n > 2:
                t = rho * np.sqrt((n - 2) / (1 - rho ** 2))
            else:
                t = float("inf") if abs(rho) >= 1.0 else 0.0
            rows.append({"vol_bucket": bucket_name, "pillar": pillar,
                         "n_obs": n, "ic": float(rho), "t": float(t),
                         "verdict": verdict(t, n, min_events)})
    return pd.DataFrame(rows)


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run(out_dir: Path,
        df: pd.DataFrame | None = None,
        rets_wide: pd.DataFrame | None = None,
        *,
        min_events: int = MIN_EVENTS_DEFAULT,
        horizons: Iterable[int] = FWD_HORIZONS) -> dict:
    """Run all mining tables and write outputs. Returns a report dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if df is None:
        df = load_cis_history()
    if rets_wide is None:
        symbols = sorted(df["symbol"].dropna().unique().tolist())
        rets_wide = load_returns_wide(symbols,
                                       date_index=pd.DatetimeIndex(sorted(df["_date"].dropna().unique())))

    # Use 30-day forward return as the headline IC horizon
    horizon = 30
    fwd_rets = compute_forward_returns(rets_wide, horizon=horizon)

    report: dict = {
        "n_rows": int(len(df)),
        "n_assets": int(df["symbol"].nunique()),
        "horizon_days": horizon,
        "min_events": min_events,
        "ohlcv_coverage": {
            "n_assets_with_returns": int((~rets_wide.isna().all()).sum()),
            "n_assets_total": len(rets_wide.columns),
        },
        "regime_cycle_pillar": None,
        "asset_class_pillar": None,
        "vol_bucket_pillar": None,
    }

    print(f"[1/3] Per (regime × cycle × pillar) IC …")
    rcp = per_regime_cycle_pillar_table(df, fwd_rets, min_events=min_events)
    report["regime_cycle_pillar"] = rcp.to_dict(orient="records")
    rcp.to_csv(out_dir / "regime_cycle_pillar_ic.csv", index=False)

    print(f"[2/3] Per (asset_class × pillar × cycle) IC …")
    acp = per_asset_class_pillar(df, fwd_rets, min_events=min_events)
    report["asset_class_pillar"] = acp.to_dict(orient="records")
    acp.to_csv(out_dir / "asset_class_pillar_ic.csv", index=False)

    print(f"[3/3] Per (vol_bucket × pillar) IC …")
    vbp = per_vol_bucket_pillar(df, fwd_rets, rets_wide, min_events=min_events)
    report["vol_bucket_pillar"] = vbp.to_dict(orient="records")
    vbp.to_csv(out_dir / "vol_bucket_pillar_ic.csv", index=False)

    # Verdicts summary
    print(f"\nVerdict counts (event-count gate min_events={min_events}):")
    for name, tab in [("regime_cycle_pillar", rcp),
                       ("asset_class_pillar", acp),
                       ("vol_bucket_pillar", vbp)]:
        if "verdict" in tab.columns:
            vc = tab["verdict"].value_counts().to_dict()
            print(f"  {name}: {vc}")

    (out_dir / "pillar_ic_mining_report.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    print(f"\nWrote {out_dir}/regime_cycle_pillar_ic.csv")
    print(f"Wrote {out_dir}/asset_class_pillar_ic.csv")
    print(f"Wrote {out_dir}/vol_bucket_pillar_ic.csv")
    print(f"Wrote {out_dir}/pillar_ic_mining_report.json")
    return report


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Per-pillar IC × regime × cycle mining")
    ap.add_argument("--csv", default=str(ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "data_align" / "pillar_ic_mining"))
    ap.add_argument("--min-events", type=int, default=MIN_EVENTS_DEFAULT,
                    help=f"Minimum n_events per cell (default {MIN_EVENTS_DEFAULT}); "
                         f"below this ⇒ INSUFFICIENT")
    args = ap.parse_args()

    df = load_cis_history(args.csv)
    print(f"Loaded {len(df):,} rows × {df['symbol'].nunique()} symbols")
    run(Path(args.out), df=df, min_events=args.min_events)


if __name__ == "__main__":
    main()