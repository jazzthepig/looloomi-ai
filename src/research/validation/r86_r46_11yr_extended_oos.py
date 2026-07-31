"""
R86 — R46 (pillar_O) on 11yr aligned panel with 50% OOS cut (Seth, 2026-07-26).

User pivot (after R82 PARTIAL + R83 REFUTED + R85 REFUTED + S-82 lesson #44):
extend the panel and re-run R46 5d/5bps with a 50% OOS cut.

Reality check: OHLCV is the binding constraint — only 731 days of forward
returns are available (2024-06-07 → 2026-06-07). The 11yr aligned CSV gives
better pillar_O reconstruction values within this 731-day window, but cannot
extend the price panel.

What R86 DOES:
  1. Use 11yr aligned CSV's pillar_O (more accurate reconstruction).
  2. 50% OOS cut (OOS data 365 days vs 219 days in 30% cut).
  3. Cadence sweep {5, 7, 14, 21, 30}.
  4. Per-asset universe: 33 assets in 11yr CSV ∩ OHLCV.
  5. 3-check gauntlet: gross + 5bps + OOS all > 1.96.

Hypothesis: with more OOS data (365 vs 219 days) + better pillar_O (reconstructed
from 11yr), the R46 5d/5bps OOS t-stat lifts from −0.31 to > 1.96.

Anti-imposter:
  - The 30% OOS cut is R46 standard. R86's 50% cut is the EXPERIMENT, not the
    default — clearly marked in the report.
  - If R86 clears 3-check with 50% OOS but NOT 30%, that's "OOS is borderline";
    the verdict flags it.
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
from src.research.validation.cis_quality_absorption import load_daily_returns
from src.research.data_align.cis_history_loader import load_cis_history

ALIGNED_CSV = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"
OOS_FRACS = (0.30, 0.50)  # 30% (R46 standard) and 50% (R86 experiment)
NW_LAGS = 6
PERIODS_PER_YEAR = 365
R86_K = 3
R86_CADENCES = (5, 7, 14, 21, 30)
R86_COST_BPS = 5.0


def score_pillar_o_wide(cis_long: pd.DataFrame) -> pd.DataFrame:
    """Pivot pillar_O from long → wide. PIT-safe ffill."""
    wide = cis_long.pivot(index="_date", columns="symbol", values="pillar_o").sort_index()
    return wide.ffill()


def build_known_factors(rets: pd.DataFrame, lookback: int = 30) -> dict:
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    return {"market": f_market.values, "momentum": f_momentum.values}


def run_one(fac: pd.Series, known: dict, oos_frac: float) -> dict:
    cut = int(len(fac) * (1 - oos_frac))
    r_full = absorption_test(fac.values, known, nw_lags=NW_LAGS,
                              periods_per_year=PERIODS_PER_YEAR)
    r_oos = absorption_test(fac.values[cut:], {k: v[cut:] for k, v in known.items()},
                             nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
    return {
        "full_t": r_full["alpha_t"],
        "full_ann_pct": r_full["alpha_ann_pct"],
        "oos_t": r_oos["alpha_t"],
        "oos_ann_pct": r_oos["alpha_ann_pct"],
        "oos_n": int(len(fac.values[cut:])),
    }


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R86 — R46 on 11yr aligned panel, 50% OOS cut ===\n")

    cis = load_cis_history(ALIGNED_CSV, force_schema=True)
    rets = load_daily_returns()
    common_assets = sorted(set(cis["symbol"].dropna().unique()) & set(rets.columns))
    rets = rets[common_assets]

    score_o = score_pillar_o_wide(cis[cis["symbol"].isin(common_assets)])
    score_o = score_o[common_assets].reindex(rets.index).ffill()
    print(f"Score shape: {score_o.shape}, rets shape: {rets.shape}")
    print(f"Panel: {rets.index[0].date()} → {rets.index[-1].date()} ({len(rets)} days)\n")

    known = build_known_factors(rets)

    # Sweep cadence × OOS cut
    print(f"--- Cadence × OOS cut sweep (pillar_O level, k={R86_K}) ---")
    sweep = {}
    for cad in R86_CADENCES:
        for oos_frac in OOS_FRACS:
            fac_gross = _cadence_ls(score_o, rets, rebal_days=cad, cost_bps=0.0,
                                     k_terciles=R86_K)
            fac_gross = fac_gross.reindex(rets.index).fillna(0.0)
            fac_5bps = _cadence_ls(score_o, rets, rebal_days=cad, cost_bps=R86_COST_BPS,
                                    k_terciles=R86_K)
            fac_5bps = fac_5bps.reindex(rets.index).fillna(0.0)
            r_g = run_one(fac_gross, known, oos_frac)
            r_5 = run_one(fac_5bps, known, oos_frac)
            clears = (r_g["full_t"] > 1.96) + (r_5["full_t"] > 1.96) + (r_5["oos_t"] > 1.96)
            marker = "✅" if clears == 3 else ("🟡" if clears >= 2 else "🔴")
            print(f"  cad={cad:2d}  oos={oos_frac*100:3.0f}%  "
                  f"gross_t={r_g['full_t']:+.2f}  5bps_t={r_5['full_t']:+.2f}  "
                  f"OOS_t={r_5['oos_t']:+.2f}  OOS_ann={r_5['oos_ann_pct']:+.1f}%  "
                  f"OOS_n={r_5['oos_n']:3d}  {clears}/3  {marker}")
            sweep[(cad, oos_frac)] = {
                "gross_t": r_g["full_t"],
                "5bps_t": r_5["full_t"],
                "oos_t": r_5["oos_t"],
                "oos_n": r_5["oos_n"],
                "clears": int(clears),
            }

    # Identify cleared cadences
    cleared_30 = [(c, o) for (c, o), v in sweep.items() if v["clears"] == 3 and o == 0.30]
    cleared_50 = [(c, o) for (c, o), v in sweep.items() if v["clears"] == 3 and o == 0.50]

    print(f"\n--- Verdict summary ---")
    if cleared_30:
        print(f"  Cleared at 30% OOS (R46 standard): cadences {[c for c, _ in cleared_30]}")
    else:
        print(f"  🔴 No cadence cleared at 30% OOS (R46 standard) — bear-window dominates")
    if cleared_50:
        print(f"  ✅ Cleared at 50% OOS (R86 experiment): cadences {[c for c, _ in cleared_50]}")
        # Take the best cadence at 50%
        best = max(cleared_50, key=lambda x: sweep[(x[0], x[1])]["oos_t"])
        best_cad, _ = best
        winner_5bps = sweep[(best_cad, 0.50)]
        print(f"  Best cell: cad={best_cad}d / 50% OOS  gross_t={winner_5bps['gross_t']:+.2f}  "
              f"5bps_t={winner_5bps['5bps_t']:+.2f}  OOS_t={winner_5bps['oos_t']:+.2f}")
        # Per-window for winner
        fac_5 = _cadence_ls(score_o, rets, rebal_days=best_cad, cost_bps=R86_COST_BPS,
                             k_terciles=R86_K)
        fac_5 = fac_5.reindex(rets.index).fillna(0.0)
        windows = quarter_cuts(fac_5.index[0], fac_5.index[-1], n_windows=6)
        sub = sub_period_absorption(fac_5, known, windows, nw_lags=NW_LAGS,
                                      periods_per_year=PERIODS_PER_YEAR)
        print(f"\n  W1-W6 attribution:")
        for w in sub:
            print(f"    {w['label']}: α_t={w['alpha_t']:+.2f}  α_ann_pct={w['alpha_ann_pct']:+.2f}%")
        verdict = "✅ SURVIVES (50% OOS)" if cleared_30 else "🟡 BORDERLINE (only 50% OOS clears)"
    else:
        print(f"  🔴 No cadence cleared even at 50% OOS — bear-window effect is structural")
        verdict = "🔴 REFUTED"
        sub = []

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "panel": {
            "lo": str(rets.index[0].date()),
            "hi": str(rets.index[-1].date()),
            "n_days": int(len(rets)),
            "n_assets": int(len(rets.columns)),
            "data_source": "11yr aligned CSV pillar_O + OHLCV 731-day intersection",
        },
        "config": {
            "k_terciles": R86_K,
            "cost_bps": R86_COST_BPS,
            "oos_fracs_tested": list(OOS_FRACS),
            "cadences_tested": list(R86_CADENCES),
        },
        "sweep": {f"cad{c}_oos{o}": v for (c, o), v in sweep.items()},
        "cleared_at_30": cleared_30,
        "cleared_at_50": cleared_50,
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
    ap = argparse.ArgumentParser(description="R86 — R46 11yr extended OOS")
    ap.add_argument("--out-dir", type=Path,
                     default=ROOT / "reports" / "r86_r46_11yr_extended_oos" /
                              datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    run(args.out_dir)


if __name__ == "__main__":
    main()
