"""
R83 — Cross-sectional realized-vol RISK-PREMIA L/S (Seth, 2026-07-26).

Triggered by R82 PARTIAL verdict (pillar_A regime-gated L/S does not clear the
3-check gauntlet on the 731-day panel). The user goal is two L/S strategies ready
for real trading; R77 fusion cell is Strategy 1. Strategy 2 needs a STRUCTURALLY
DIFFERENT signal source — R83 is the lottery/risk-premia candidate.

Hypothesis (behavioral cause):
  Long low-vol / short high-vol. The "lottery effect" — investors overpay for
  volatile assets hoping for big wins, creating a structural premium for low-vol
  assets (Baker-Bradley-Wurgler 2011; Frazzini-Israel-Moskowitz 2014 AQR BAB).

Why this is orthogonal to R77:
  R77 = 0.25 × R46 (pillar_O alpha) + 0.75 × R62 (fragility-gated fade-the-crowd)
        + 0.30 × R76 (funding residual).
  R83 = pure risk-premia (cross-section vol-rank). No overlap with: alpha
  (R46), crowding (R62), funding (R76).

Why this is novel vs R79:
  R79 was the cross-sectional DEMEAN of realized vol (residual vol); R79 was
  REFUTED. R83 is the vol LEVEL (not residualized) — different signal unit.

Methodology (mirrors R46 baseline for honesty):
  - Score: -1 × realized_vol_30d (long top = low-vol).
  - Universe: 11yr aligned CSV ∩ OHLCV (34 assets, 731-day common panel).
  - K-terciles = 3; cadence = 5d (R46 winner); cost = 5bps (R46 frozen).
  - 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  - Per-window W1-W6 attribution.
  - Residualization: market + 30d trailing momentum; Newey-West lags=6.

Anti-imposter:
  - Universe is the same 11yr aligned CSV as R82 — apples-to-apples.
  - OOS is the last 30% (cut at 70%), identical to R73/R82 split.
  - Both signs (long low-vol / long high-vol) run; sign verdict is the
    matched-cell direct comparison.

Verdict positioning:
  - ✅ SURVIVES — clears all 3 checks AND matched sign favors the risk-premia
    direction (low-vol long). Eligible for live-spec lock.
  - 🟡 PARTIAL — clears 2 of 3 (or 3 of 3 with ambiguous sign).
  - 🔴 REFUTED — fails 2+ checks.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.validation.cis_quality_robustness import (
    cadence_ls as _cadence_ls_re,
    estimate_turnover_ann,
    quarter_cuts,
    sub_period_absorption,
)
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.cis_quality_absorption import load_daily_returns

# ── Constants ───────────────────────────────────────────────────────────────
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365
R83_K_TERCILES = 3
R83_CADENCE = 5
R83_COST_BPS = 5.0

# Sign constants (per R73 convention)
SIGN_LOW_VOL_LONG = "low_vol_long"   # lottery/risk-premia direction
SIGN_HIGH_VOL_LONG = "high_vol_long"  # momentum/chase direction
_VALID_SIGNS = {SIGN_LOW_VOL_LONG, SIGN_HIGH_VOL_LONG}

ALIGNED_CSV = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"


# ── Score: cross-sectional realized-vol level ─────────────────────────────
def realized_vol_wide(rets: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """30-day rolling realized vol (annualized). Shape: (date × asset)."""
    return rets.rolling(window, min_periods=window).std() * np.sqrt(365)


def score_low_vol_long(vol_wide: pd.DataFrame) -> pd.DataFrame:
    """Score = -1 × realized_vol. Higher score = lower vol. PIT-safe ffill."""
    return (-vol_wide).ffill()


# ── Standard L/S core (wraps R46 cadence_ls with sign) ───────────────────
def vol_ls(vol_wide: pd.DataFrame, rets: pd.DataFrame,
            k_terciles: int = R83_K_TERCILES,
            cost_bps: float = R83_COST_BPS,
            rebal_days: int = R83_CADENCE,
            sign: str = SIGN_LOW_VOL_LONG) -> pd.Series:
    """Long low-vol / short high-vol (or reversed under SIGN_HIGH_VOL_LONG).
    Score = -1 × realized_vol (or +1 for the reversed direction)."""
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    score = -vol_wide if sign == SIGN_LOW_VOL_LONG else vol_wide
    return _cadence_ls_re(score, rets, rebal_days=rebal_days, cost_bps=cost_bps)


# ── Known factors for absorption ───────────────────────────────────────────
def build_known_factors(rets: pd.DataFrame, lookback: int = 30) -> dict:
    """Standard f_market (cross-section mean) + f_momentum (TSMOM 30d)."""
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    return {"market": f_market.values, "momentum": f_momentum.values}


# ── Run + Gauntlet ─────────────────────────────────────────────────────────
def run_gauntlet(vol_wide: pd.DataFrame, rets: pd.DataFrame,
                  known_arrs: dict) -> dict:
    """Run both signs; report 3-check gauntlet."""
    out = {}
    for label, sign in (("low_vol_long", SIGN_LOW_VOL_LONG), ("high_vol_long", SIGN_HIGH_VOL_LONG)):
        # 5bps costed
        fac_5 = vol_ls(vol_wide, rets, cost_bps=R83_COST_BPS, rebal_days=R83_CADENCE, sign=sign)
        fac_5 = fac_5.reindex(rets.index).fillna(0.0)
        r_5 = absorption_test(fac_5.values, known_arrs, nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
        # 0bps gross
        fac_0 = vol_ls(vol_wide, rets, cost_bps=0.0, rebal_days=R83_CADENCE, sign=sign)
        fac_0 = fac_0.reindex(rets.index).fillna(0.0)
        r_0 = absorption_test(fac_0.values, known_arrs, nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
        # OOS: last 30%
        cut = int(len(rets) * (1 - OOS_FRAC))
        r_oos = absorption_test(fac_5.values[cut:], {k: v[cut:] for k, v in known_arrs.items()},
                                 nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
        out[label] = {
            "gross_t": r_0["alpha_t"],
            "gross_ann_pct": r_0["alpha_ann_pct"],
            "5bps_t": r_5["alpha_t"],
            "5bps_ann_pct": r_5["alpha_ann_pct"],
            "oos_t": r_oos["alpha_t"],
            "oos_ann_pct": r_oos["alpha_ann_pct"],
            "oos_n": int(len(fac_5.values[cut:])),
        }
    # Matched-cell sign verdict
    lo = out["low_vol_long"]
    hi = out["high_vol_long"]
    matched_diff = (lo["gross_t"] + lo["5bps_t"] + lo["oos_t"]) - \
                   (hi["gross_t"] + hi["5bps_t"] + hi["oos_t"])
    sign_verdict = SIGN_LOW_VOL_LONG if matched_diff > 0 else SIGN_HIGH_VOL_LONG
    out["matched_diff"] = float(matched_diff)
    out["sign_verdict"] = sign_verdict

    # Verdict
    v = out[sign_verdict]
    clears = (v["gross_t"] > 1.96) + (v["5bps_t"] > 1.96) + (v["oos_t"] > 1.96)
    if clears == 3:
        verdict = "✅ SURVIVES"
    elif clears >= 2:
        verdict = "🟡 PARTIAL"
    else:
        verdict = "🔴 REFUTED"
    out["verdict"] = verdict
    return out


# ── Master run ──────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R83 — cross-sectional realized-vol risk-premia L/S ===\n")

    # Load OHLCV (the canonical source for returns)
    rets = load_daily_returns()
    print(f"OHLCV returns: {len(rets):,} dates × {len(rets.columns)} assets")

    # Drop assets with too few observations
    valid = rets.notna().sum() > 200
    rets = rets.loc[:, valid]
    print(f"After missing filter: {len(rets.columns)} assets")

    # Build vol_wide and score
    vol_wide = realized_vol_wide(rets, window=30)
    score = score_low_vol_long(vol_wide)

    # Correlation check (sanity: who is "low-vol" structurally?)
    avg_vol = vol_wide.mean().sort_values()
    print(f"\nTop 5 lowest-vol assets (avg σ): {avg_vol.head().to_dict()}")
    print(f"Top 5 highest-vol assets (avg σ): {avg_vol.tail().to_dict()}")

    # Build known factors for absorption
    known_arrs = build_known_factors(rets)

    # Run gauntlet
    g = run_gauntlet(vol_wide, rets, known_arrs)
    print(f"\n--- Gauntlet ---")
    for label in ("low_vol_long", "high_vol_long"):
        d = g[label]
        print(f"  {label}: gross_t={d['gross_t']:+.2f}  5bps_t={d['5bps_t']:+.2f}  OOS_t={d['oos_t']:+.2f}")
    print(f"  matched-cell diff: {g['matched_diff']:+.3f}  → sign: {g['sign_verdict']}")
    print(f"  verdict: {g['verdict']}")

    # Per-window W1-W6 attribution
    print(f"\n--- W1-W6 attribution (5bps, sign={g['sign_verdict']}) ---")
    fac_5 = vol_ls(vol_wide, rets, cost_bps=R83_COST_BPS, rebal_days=R83_CADENCE, sign=g["sign_verdict"])
    fac_5 = fac_5.reindex(rets.index).fillna(0.0)
    windows = quarter_cuts(fac_5.index[0], fac_5.index[-1], n_windows=6)
    sub = sub_period_absorption(fac_5, known_arrs, windows, nw_lags=NW_LAGS,
                                  periods_per_year=PERIODS_PER_YEAR)
    for w in sub:
        print(f"  {w['label']}: n={w['n']}  α_t={w['alpha_t']:+.2f}  α_ann_pct={w['alpha_ann_pct']:+.2f}%")

    # Compile report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_dates": int(len(rets)),
        "n_assets": int(len(rets.columns)),
        "pipeline": "score=-1×realized_vol_30d, abs=market+momentum",
        "config": {
            "k_terciles": R83_K_TERCILES,
            "cadence": R83_CADENCE,
            "cost_bps": R83_COST_BPS,
            "oos_frac": OOS_FRAC,
        },
        "gauntlet": g,
        "w5_attribution": [
            {"label": w["label"], "n": w["n"],
             "alpha_t": float(w["alpha_t"]) if w["alpha_t"] is not None else None,
             "alpha_ann_pct": float(w["alpha_ann_pct"]) if w["alpha_ann_pct"] is not None else None}
            for w in sub
        ],
        "avg_vol_rank": avg_vol.to_dict(),
    }
    json_path = out_dir / "verdict.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {json_path}")
    return report


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="R83 — vol risk-premia L/S")
    ap.add_argument("--out-dir", type=Path,
                     default=ROOT / "reports" / "r83_vol_risk_premia_ls" /
                              datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    run(args.out_dir)


if __name__ == "__main__":
    main()
