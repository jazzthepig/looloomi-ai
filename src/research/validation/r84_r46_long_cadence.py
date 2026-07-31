"""
R84 — R46 (pillar_O) at LONGER CADENCE (21d rebal) — OOS rescue attempt (Seth, 2026-07-26).

Triggered by R82 PARTIAL + R83 REFUTED + R76 standalone failing 5bps — no
standalone L/S strategy cleared the 3-check gauntlet on the 731-day panel.
R77 fusion cell is Strategy 1 (validated). Strategy 2 needs a different L/S that
clears 3-check.

Hypothesis:
  R46 (pillar_O 5d/5bps) cleared gross (t=+3.33) + 5bps but FAILED OOS (t=−0.31).
  The OOS failure is the 2025-10 → 2026-06 bear window where pillar_O quality
  collapsed. Longer rebal (21d) smooths exposure and should:
    (a) Reduce OOS sensitivity to specific bear windows (lower turnover)
    (b) Capture the same quality alpha at lower cost
    (c) Match the institutional L/S rebal cadence (monthly)

This is the LAST honest attempt at a single-leg L/S Strategy 2. If R84 also fails,
we accept: Strategy 1 = R77 fusion cell; Strategy 2 = sliced R77 (regime-gated
or vol-targeted overlay), not a separate leg.

Mechanics:
  - Score: pillar_O LEVEL (R46's score, NOT demeaned).
  - Cadence: 21d (vs R46 5d).
  - Cost: 5bps.
  - Same 28-asset funding-bearing panel.
  - 3-check gauntlet + per-window W1-W6 attribution.

Anti-imposter:
  - Sweep cadences {5, 7, 14, 21, 30} × costs {0, 5, 10} to see the whole
    longer-cadence landscape. R46 5d/5bps baseline is the reference.
  - Sign: pillar_O is "high_quality_long" (long top, short bottom).
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
    cadence_ls as _cadence_ls,
    estimate_turnover_ann,
    quarter_cuts,
    sub_period_absorption,
)
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)

OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365
R84_K = 3
R84_CADENCES = (5, 7, 14, 21, 30)
R84_COST_GRID = (0.0, 5.0, 10.0)


def score_pillar_o(cis_long: pd.DataFrame) -> pd.DataFrame:
    """Pivot pillar_O from long → wide. PIT-safe ffill."""
    wide = cis_long.pivot(index="date", columns="asset", values="O").sort_index()
    return wide.ffill()


def build_known_factors(rets: pd.DataFrame, lookback: int = 30) -> dict:
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    return {"market": f_market.values, "momentum": f_momentum.values}


def gauntlet_for(fac: pd.Series, known_arrs: dict) -> dict:
    cut = int(len(fac) * (1 - OOS_FRAC))
    r_full = absorption_test(fac.values, known_arrs, nw_lags=NW_LAGS,
                              periods_per_year=PERIODS_PER_YEAR)
    r_oos = absorption_test(fac.values[cut:], {k: v[cut:] for k, v in known_arrs.items()},
                             nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
    return {
        "full_t": r_full["alpha_t"],
        "full_ann_pct": r_full["alpha_ann_pct"],
        "oos_t": r_oos["alpha_t"],
        "oos_ann_pct": r_oos["alpha_ann_pct"],
    }


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R84 — R46 pillar_O at LONGER CADENCE (21d) ===\n")

    cis = load_cis_history_wide()
    rets = load_daily_returns()
    common = sorted(set(cis["asset"].unique()) & set(rets.columns))
    rets = rets[common]

    score_o = score_pillar_o(cis[cis["asset"].isin(common)])
    score_o = score_o[common].reindex(rets.index).ffill()
    print(f"Score shape: {score_o.shape}, rets shape: {rets.shape}")

    known_arrs = build_known_factors(rets)

    # Sweep cadence × cost
    print(f"\n--- Cadence × cost sweep (pillar_O level, k={R84_K}) ---")
    sweep = {}
    for cad in R84_CADENCES:
        for bps in R84_COST_GRID:
            fac = _cadence_ls(score_o, rets, rebal_days=cad, cost_bps=bps, k_terciles=R84_K)
            fac = fac.reindex(rets.index).fillna(0.0)
            g = gauntlet_for(fac, known_arrs)
            sweep[(cad, bps)] = g
            clears = (g["full_t"] > 1.96) + (g["oos_t"] > 1.96)
            marker = "✓✓" if clears == 2 else ("✓" if clears == 1 else "✗")
            print(f"  cad={cad:2d}  bps={bps:4.1f}  full_t={g['full_t']:+.2f}  "
                  f"OOS_t={g['oos_t']:+.2f}  full_ann={g['full_ann_pct']:+.1f}%  "
                  f"OOS_ann={g['oos_ann_pct']:+.1f}%  {marker}")

    # 3-check requires gross + 5bps + OOS all > 1.96
    print(f"\n--- 3-check gauntlet (gross + 5bps + OOS) ---")
    cleared = []
    for cad in R84_CADENCES:
        # gross
        fac_0 = _cadence_ls(score_o, rets, rebal_days=cad, cost_bps=0.0, k_terciles=R84_K)
        fac_0 = fac_0.reindex(rets.index).fillna(0.0)
        g_0 = gauntlet_for(fac_0, known_arrs)
        # 5bps
        fac_5 = _cadence_ls(score_o, rets, rebal_days=cad, cost_bps=5.0, k_terciles=R84_K)
        fac_5 = fac_5.reindex(rets.index).fillna(0.0)
        g_5 = gauntlet_for(fac_5, known_arrs)
        clears = (g_0["full_t"] > 1.96) + (g_5["full_t"] > 1.96) + (g_5["oos_t"] > 1.96)
        marker = "✅" if clears == 3 else ("🟡" if clears >= 2 else "🔴")
        print(f"  cad={cad:2d}  gross_t={g_0['full_t']:+.2f}  5bps_t={g_5['full_t']:+.2f}  "
              f"OOS_t={g_5['oos_t']:+.2f}  {clears}/3  {marker}")
        if clears == 3:
            cleared.append(cad)

    if cleared:
        winner = cleared[0]
        print(f"\n✅ SURVIVES at cad={winner}d — eligible for Strategy 2")
        # W1-W6 attribution for winner
        fac_5 = _cadence_ls(score_o, rets, rebal_days=winner, cost_bps=5.0, k_terciles=R84_K)
        fac_5 = fac_5.reindex(rets.index).fillna(0.0)
        windows = quarter_cuts(fac_5.index[0], fac_5.index[-1], n_windows=6)
        sub = sub_period_absorption(fac_5, known_arrs, windows, nw_lags=NW_LAGS,
                                      periods_per_year=PERIODS_PER_YEAR)
        for w in sub:
            print(f"  {w['label']}: α_t={w['alpha_t']:+.2f}  α_ann_pct={w['alpha_ann_pct']:+.2f}%")
        verdict = "✅ SURVIVES"
    else:
        print(f"\n🔴 REFUTED at all cadences × costs — no second-strategy candidate on this panel")
        sub = []
        verdict = "🔴 REFUTED"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_dates": int(len(rets)),
        "n_assets": int(len(rets.columns)),
        "pipeline": "score=pillar_O level, sweep cadences × costs",
        "sweep": {f"cad{c}_bps{b}": v for (c, b), v in sweep.items()},
        "cleared_cadences": cleared,
        "verdict": verdict,
        "w5_attribution": [
            {"label": w["label"], "alpha_t": float(w["alpha_t"]) if w["alpha_t"] is not None else None,
             "alpha_ann_pct": float(w["alpha_ann_pct"]) if w["alpha_ann_pct"] is not None else None}
            for w in sub
        ],
    }
    json_path = out_dir / "verdict.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {json_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="R84 — R46 at longer cadence")
    ap.add_argument("--out-dir", type=Path,
                     default=ROOT / "reports" / "r84_r46_long_cadence" /
                              datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    run(args.out_dir)


if __name__ == "__main__":
    main()
