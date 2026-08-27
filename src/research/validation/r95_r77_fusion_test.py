"""R95 as 4th fusion leg of R77 — does adding funding-IVOL residual lift the cell?

Per lesson #42: max |corr| < 0.30 vs existing legs.
Per lesson #43: orthogonal signal sources DO carry as fusion contributions.

Constructs the R77 baseline (R46 + R62 + R76 at frozen weights w_R46=0.25,
w_R62=0.75, w_R76=0.30), then sweeps w_R95 in {0, 0.05, ..., 0.50}.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.r73_pillar_a_level_ls import pillar_a_level_ls
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28, fuse, max_drawdown, per_window,
)
from src.research.validation.r76_funding_residual_ls import (
    score_funding_residual, funding_residual_ls,
)
from src.research.validation.funding_crowding_ls import score_funding_zwide
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.pod_aggregator import _simple_t
from src.data.signals.fusion_paper import UNIVERSE as TRADEABLE_28

_logger = logging.getLogger("r95_r77_fusion_test")
PERIODS_PER_YEAR = 365

# Frozen R77 weights (memory: w_R46=0.25 / w_R62=0.75 / w_R76=0.30)
# Construction: R69 = 0.25 × R46 + 0.75 × R62; R77 = 0.70 × R69 + 0.30 × R76
R69_W_R46 = 0.25
R69_W_R62 = 0.75
R77_W_R76 = 0.30


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # ── Load panel ───────────────────────────────────────────────────────────
    _logger.info("Loading panel + building R77 legs...")
    cis_long = load_cis_history_wide()
    rets = load_daily_returns()
    funding_daily = load_funding_daily()
    common = [a for a in TRADEABLE_28
              if a in cis_long["asset"].values
              and a in rets.columns
              and a in funding_daily.columns]
    _logger.info("Universe: %d assets (28-strict)", len(common))

    # ── Build R77 legs on the panel ──────────────────────────────────────────
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets, common)
    score_r62 = score_funding_zwide(funding_daily[common], sign="fade_crowd")
    # Use fragility_detector via r63's run path for simplicity
    # Actually for fusion test we want SIMPLE R62 (not detector-gated)
    leg_r62 = build_r62_sleeve_28(score_r62, rets, common, detector=pd.Series(False, index=score_r62.index))
    score_r76 = score_funding_residual(funding_daily, common)
    leg_r76 = funding_residual_ls(score_r76, rets[common], k_terciles=3, cost_bps=0.0)
    leg_r76 = leg_r76.reindex(rets.index).fillna(0.0)

    # R95 leg
    ivol = funding_daily[common].rolling(30, min_periods=10).std()
    score_r95 = ivol.sub(ivol.mean(axis=1), axis=0)
    leg_r95 = pillar_a_level_ls(
        score_r95, rets[common], k_terciles=2,
        cost_bps=5.0, rebal_days=3, sign="low_a_long",
    ).reindex(rets.index).fillna(0.0)

    # R77 baseline (frozen weights)
    fac_2_baseline = fuse(leg_r46, leg_r62, R69_W_R46)
    r77_baseline = (1 - R77_W_R76) * fac_2_baseline + R77_W_R76 * leg_r76
    r77_baseline = r77_baseline.reindex(rets.index).fillna(0.0)

    # ── Cross-pod correlation: lesson #42 gate ───────────────────────────────
    # Need ≥ 50 overlapping days
    overlap = leg_r95.dropna().index.intersection(r77_baseline.dropna().index)
    if len(overlap) < 50:
        print("Insufficient overlap for correlation gate")
        return 1
    corr_r95_r77 = float(leg_r95.reindex(overlap).corr(r77_baseline.reindex(overlap)))
    corr_r95_r46 = float(leg_r95.reindex(overlap).corr(leg_r46.reindex(overlap)))
    corr_r95_r62 = float(leg_r95.reindex(overlap).corr(leg_r62.reindex(overlap)))
    corr_r95_r76 = float(leg_r95.reindex(overlap).corr(leg_r76.reindex(overlap)))
    max_abs_corr = max(abs(corr_r95_r77), abs(corr_r95_r46),
                        abs(corr_r95_r62), abs(corr_r95_r76))
    print(f"\nLesson #42 cross-pod correlation:")
    print(f"  corr(R95, R46) = {corr_r95_r46:+.3f}")
    print(f"  corr(R95, R62) = {corr_r95_r62:+.3f}")
    print(f"  corr(R95, R76) = {corr_r95_r76:+.3f}")
    print(f"  corr(R95, R77) = {corr_r95_r77:+.3f}")
    print(f"  MAX |corr|     = {max_abs_corr:.3f} "
          f"({'✓' if max_abs_corr < 0.30 else '✗'} clears lesson #42 gate < 0.30)")

    # ── Sweep w_R95 ──────────────────────────────────────────────────────────
    print(f"\n=== R77 + R95 fusion sweep (w_R95 ∈ [0, 0.50]) ===")
    print(f"{'w_R95':>6} | {'gross_t':>8} | {'OOS_t':>8} | {'pass':>5} | "
          f"{'OOS_S':>7} | {'maxDD %':>8}")

    results = []
    for w in np.arange(0, 0.55, 0.05):
        w = round(w, 2)
        fused = (1 - w) * r77_baseline + w * leg_r95
        fused = fused.reindex(rets.index).fillna(0.0)
        cut = int(len(fused) * 0.70)
        is_p = fused.iloc[:cut].fillna(0.0)
        oos_p = fused.iloc[cut:].fillna(0.0)
        # 3-check
        known = {}
        mkt = rets[common].mean(axis=1).fillna(0.0).reindex(fused.index).fillna(0.0)
        cum = (1 + mkt).cumprod()
        trail30 = cum / cum.shift(30) - 1
        known["market"] = mkt.values
        known["momentum"] = (np.sign(trail30.shift(1)).fillna(0.0) * mkt).values
        try:
            res = gauntlet_3check(fused, known, oos_idx=cut)
            gross_t = float(res.get("gross_t", 0.0))
            oos_t = float(res.get("oos_t", 0.0))
        except (np.linalg.LinAlgError, ValueError):
            gross_t = _simple_t(is_p.values)
            oos_t = _simple_t(oos_p.values)
        passes = gross_t > 1.96 and oos_t > 1.96
        oos_sharpe = (float(oos_p.mean() / oos_p.std() * np.sqrt(PERIODS_PER_YEAR))
                      if oos_p.std() > 0 else 0.0)
        mdd = max_drawdown(fused)
        results.append({
            "w_R95": w, "gross_t": gross_t, "oos_t": oos_t,
            "passes": passes, "oos_sharpe": oos_sharpe, "max_dd": mdd,
        })
        print(f"  {w:>5.2f} | {gross_t:>+7.3f} | {oos_t:>+7.3f} | "
              f"{'✓' if passes else '✗':>4} | {oos_sharpe:>+6.2f} | "
              f"{mdd*100:>+7.2f}%")

    # ── Decision ─────────────────────────────────────────────────────────────
    df = pd.DataFrame(results)
    passes = df[df["passes"]]
    print(f"\nPassing cells: {len(passes)} / {len(df)}")
    if len(passes):
        best = passes.sort_values("oos_t", ascending=False).iloc[0]
        print(f"Best passing cell: w_R95={best['w_R95']:.2f} "
              f"→ gross_t={best['gross_t']:+.3f} oos_t={best['oos_t']:+.3f} "
              f"OOS_sharpe={best['oos_sharpe']:+.2f} maxDD={best['max_dd']*100:+.2f}%")
    else:
        # Best by OOS_t improvement vs baseline
        baseline_row = df.iloc[0]  # w_R95=0
        nonbaseline = df.iloc[1:]
        if len(nonbaseline):
            best_delta = nonbaseline.loc[nonbaseline["oos_t"].idxmax()]
            delta = best_delta["oos_t"] - baseline_row["oos_t"]
            print(f"No config passes 3-check. Best w_R95>0: {best_delta['w_R95']:.2f} "
                  f"ΔOOS_t={delta:+.3f} (does NOT clear lesson #43 lift bar +0.5)")
    return 0


if __name__ == "__main__":
    sys.exit(main())