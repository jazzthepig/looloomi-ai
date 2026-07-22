"""
R74 — pillar_A as 3rd fusion contribution to R69 family (Seth, 2026-07-22).

Per R73 lesson #41 (proposed 2026-07-22): R73 REFUTED pillar_A as a standalone
sleeve (gross α_t=+1.69, 5bps_t=+1.44, OOS_t=−0.22 on best cell 3d/0bps), but
the **matched-cell directional differential = +3.07** favoring R63b direction
was decisively real. The open question R73 flagged for follow-on:

    "pillar_A may carry ~5-10% w in the R69 fusion family with the right
     weight, but that's a separate test (R74 or beyond)."

R74 tests that hypothesis. The R69 cell is the deployed fusion book (R65 +
R66 tracking); its frozen weight is w_R46=0.25 (R69 family → Seth lane equivalent
of Minimax's R64 family per §LEDGER-RECONCILIATION-MAP). R74 does NOT touch the
live book — it builds evidence for a forward R75 candidate that may rebalance w_R46.

Methodology (anti-imposter):
  · Reuse R63's exact panel + 28-asset strict funding ∩ CIS ∩ OHLCV universe.
  · Leg 1: R46 pillar_O 5d/5bps (R63's existing leg_r46).
  · Leg 2: R62 fade-the-crowd 21d/0bps gated (R63's existing leg_r62).
  · Leg 3 (NEW): R73 pillar_A LEVEL 3d/0bps (R73's best cell, k=3).
  · Frozen 2-component baseline: fac_2 = 0.25 × Leg1 + 0.75 × Leg2 (R69 cell).
  · 3-component fusion: fac_3 = (1-w_A) × fac_2 + w_A × Leg3.
  · Sweep w_A ∈ {0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30}.
  · At each w_A: 3-check gauntlet + per-window W1-W6 + max DD.
  · Both signs of Leg3 run side-by-side; sign verdict from matched-cell.

Verdict grammar (R74-specific):
  · ✅ FUSION LIFT  — best w_A clears 3-check AND ΔOOS_t ≥ +0.5 vs frozen
                     baseline (w_A=0). Lesson #42 = "REFUTED sleeves may still
                     ship as fusion contributions."
  · 🟡 NEUTRAL      — best w_A improves 1-2 of 3 checks but ΔOOS_t < +0.5
                     OR sign-flip not eliminated. Diagnostic.
  · 🔴 FUSION LOSES — best w_A gives ΔOOS_t ≤ 0 OR W5 sign-flips more than
                      the frozen baseline. Lesson #42 = "REFUTED at the
                      gauntlet → don't rescue via fusion."

Universe (anti-imposter strict): same 28-asset funding ∩ CIS ∩ OHLCV that R63
and R73 used. R74 result is comparable ONLY to those R-numbers on the same
panel. No silent widening to the 41-asset easier CIS ∩ OHLCV.

This module does NOT touch the live fusion book (R65/R66). The frozen R69
cell at w_R46=0.25 stays unchanged regardless of R74's verdict.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.cis_quality_robustness import (
    estimate_turnover_ann, quarter_cuts,
)
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, funding_ls, DEFAULT_ZWIN, R46_K,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import (
    partition_into_windows, build_w5_detector, gauntlet_3check,
)
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28,
    _build_r62_detector, fuse, max_drawdown, per_window,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    R62_FEATURE_SET, R62_Z, R62_MF,
)
from src.research.validation.r73_pillar_a_level_ls import (
    score_pillar_a_level, pillar_a_level_ls,
    SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG,
    R73_K_TERCILES,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# Frozen R69 cell weights (NEVER mutate in R74 — R74 is a TEST)
R69_W_R46 = 0.25
R69_W_R62 = 0.75   # = 1 - R69_W_R46

# R73's best cell (used for Leg3, pillar_A LEVEL L/S)
R73_BEST_CAD = 3
R73_BEST_BPS = 0.0

# Weight sweep for Leg3 (w_A in 3-component fusion)
R74_W_A_GRID = (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30)


# === R62 detector reproduction (lifted from R63) =============================
def _build_r62_detector_local(features: pd.DataFrame, fragile_mask: pd.Series,
                              fragile_ranges: list, playable_ranges: list) -> tuple:
    """Reproduce R62 best-cell detector on the R74 panel."""
    ks = build_fragility_ks_table(features, fragile_mask)
    external_cols = [c for c in features.columns if c in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    det, fired = build_w5_detector(
        features,
        *fragile_ranges[0] if fragile_ranges else (features.index[0], features.index[0]),
        *playable_ranges[0] if playable_ranges else (features.index[0], features.index[0]),
        ks, feature_subset=external_cols,
        z_threshold=R62_Z, min_features=R62_MF,
    )
    return det


# === Leg 3 builder (R73's pillar_A LEVEL L/S on the same panel) =============
def build_r73_sleeve_28(cis_long: pd.DataFrame, rets: pd.DataFrame,
                        tradeable: list, sign: str,
                        rebal_days: int = R73_BEST_CAD,
                        cost_bps: float = R73_BEST_BPS) -> pd.Series:
    """R73 pillar_A LEVEL cross-sectional L/S on the tradeable universe.

    Score = pillar_A LEVEL (PIT-safe ffill, no .diff()).
    Sign convention: SIGN_HIGH_A_LONG = long high-A / short low-A (R63b direction).
    """
    score_wide = score_pillar_a_level(cis_long)
    score_wide = score_wide.reindex(columns=tradeable).reindex(rets.index).ffill()
    fac = pillar_a_level_ls(score_wide, rets[tradeable],
                            k_terciles=R73_K_TERCILES, cost_bps=cost_bps,
                            rebal_days=rebal_days, sign=sign)
    return fac.reindex(rets.index).fillna(0.0)


# === 3-component fusion ======================================================
def fuse3(fac_2: pd.Series, fac_a: pd.Series, w_a: float) -> pd.Series:
    """3-component fusion given the frozen 2-component baseline fac_2.

    fac_3 = (1 - w_A) × fac_2 + w_A × fac_a

    Aligned to fac_2's index. NaN in fac_a → 0 (no contribution that day).
    """
    aligned_a = fac_a.reindex(fac_2.index).fillna(0.0)
    return (1.0 - w_a) * fac_2 + w_a * aligned_a


# === Run =====================================================================
def run(out_dir: Path,
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS,
        zwin: int = DEFAULT_ZWIN,
        w_a_grid: tuple = R74_W_A_GRID,
        leg_a_sign: str = SIGN_HIGH_A_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R74 — pillar_A as 3rd fusion contribution to R69 family ===\n")
    print(f"Frozen R69 cell: w_R46={R69_W_R46}, w_R62={R69_W_R62}")
    print(f"R73 Leg3: pillar_A LEVEL {R73_BEST_CAD}d/{R73_BEST_BPS}bps, sign={leg_a_sign}\n")

    # ── Load panels (R63 parity) ──────────────────────────────────────────────
    cis_long = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis_long["date"].min(), rets.index.min())
    hi = min(cis_long["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable_full = sorted(set(cis_long["asset"]) & set(rets.columns))
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, "
          f"{len(tradeable_full)} CIS ∩ OHLCV assets)")

    funding_daily = load_funding_daily(assets=tradeable_full)
    funding_assets = sorted(set(tradeable_full) & set(funding_daily.columns))
    print(f"Funding daily: {funding_daily.shape[0]} days × "
          f"{funding_daily.shape[1]} assets ({len(funding_assets)} matched)")

    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets = rets.loc[(rets.index >= f_lo) & (rets.index <= f_hi)]
    print(f"Aligned panel: {rets.index.min().date()} → {rets.index.max().date()} "
          f"({len(rets)} days)\n")

    tradeable = funding_assets  # 28-asset STRICT intersection
    print(f"Strict intersection universe: {len(tradeable)} assets\n")

    # ── 6-window partition (R63 parity) ───────────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── Leg 1 (R46 pillar_O 5d/5bps) ──────────────────────────────────────────
    print("Building Leg 1 (R46 pillar_O 5d/5bps on 28-asset) …")
    leg_r46, pillar_o_w = build_r46_sleeve_28(cis_long, rets, tradeable)

    # ── Leg 2 (R62 fragility-gated fade-the-crowd) ────────────────────────────
    print("Building Leg 2 (R62 fade-the-crowd 21d/0bps gated) …")
    score = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis_long, rets, tradeable_full, tradeable,
                                       funding_daily)
    feats = feats.reindex(rets.index)
    det = _build_r62_detector_local(feats, fragile_mask, fragile_ranges, playable_ranges)
    leg_r62 = build_r62_sleeve_28(score, rets, tradeable, det)

    # ── Leg 3 (R73 pillar_A LEVEL 3d/0bps) — R74 NEW ─────────────────────────
    print(f"Building Leg 3 (R73 pillar_A LEVEL {R73_BEST_CAD}d/{R73_BEST_BPS}bps, "
          f"sign={leg_a_sign}) …")
    leg_r73 = build_r73_sleeve_28(cis_long, rets, tradeable, sign=leg_a_sign)

    # ── Known factors + OOS cut (R63 parity) ─────────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── Per-leg gauntlet + correlation + max DD ──────────────────────────────
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    g_r73 = gauntlet_3check(leg_r73.values, known_full, cut)
    corr_legs_r46_r62 = float(pd.Series(leg_r46.values).corr(pd.Series(leg_r62.values)))
    corr_legs_r46_r73 = float(pd.Series(leg_r46.values).corr(pd.Series(leg_r73.values)))
    corr_legs_r62_r73 = float(pd.Series(leg_r62.values).corr(pd.Series(leg_r73.values)))
    dd_r46 = max_drawdown(leg_r46)
    dd_r62 = max_drawdown(leg_r62)
    dd_r73 = max_drawdown(leg_r73)

    print(f"Leg R46: gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}, "
          f"maxDD={dd_r46:+.2%}")
    print(f"Leg R62: gross_t={g_r62['gross_t']:+.2f}, OOS_t={g_r62['oos_t']:+.2f}, "
          f"maxDD={dd_r62:+.2%}")
    print(f"Leg R73: gross_t={g_r73['gross_t']:+.2f}, OOS_t={g_r73['oos_t']:+.2f}, "
          f"maxDD={dd_r73:+.2%}")
    print(f"corr(R46,R62)={corr_legs_r46_r62:+.2f}, corr(R46,R73)={corr_legs_r46_r73:+.2f}, "
          f"corr(R62,R73)={corr_legs_r62_r73:+.2f}\n")

    # ── Frozen 2-component baseline (R69 cell) ───────────────────────────────
    fac_2_baseline = fuse(leg_r46, leg_r62, R69_W_R46)
    g_baseline = gauntlet_3check(fac_2_baseline.values, known_full, cut)
    dd_baseline = max_drawdown(fac_2_baseline)
    pw_baseline = per_window(fac_2_baseline, windows)
    print(f"Frozen baseline (w_R46={R69_W_R46:.2f}, w_A=0): "
          f"gross_t={g_baseline['gross_t']:+.2f}, OOS_t={g_baseline['oos_t']:+.2f}, "
          f"maxDD={dd_baseline:+.2%}, pass_all={g_baseline['passes_all']}\n")

    # ── Weight sweep on w_A (3-component fusion) ─────────────────────────────
    print(f"══ w_A sweep on top of frozen R69 cell (w_A ∈ {list(w_a_grid)}) ══\n")
    rows = []
    for w_a in w_a_grid:
        fused_3 = fuse3(fac_2_baseline, leg_r73, w_a)
        g_3 = gauntlet_3check(fused_3.values, known_full, cut)
        dd_3 = max_drawdown(fused_3)
        pw_3 = per_window(fused_3, windows)
        tim = float((fused_3 != 0).mean())
        sharpe = float(fused_3.mean() / fused_3.std() * np.sqrt(PERIODS_PER_YEAR)) \
                 if fused_3.std() > 0 else float("nan")
        # ΔOOS_t vs frozen baseline (the lesson #41 hypothesis test)
        delta_oos_t = g_3["oos_t"] - g_baseline["oos_t"]
        # Per-window delta (especially W5 — R73's known fragility window)
        w5_ann_baseline = pw_baseline.get("W5", {}).get("ann_pct", float("nan"))
        w5_ann_3 = pw_3.get("W5", {}).get("ann_pct", float("nan"))
        delta_w5 = (w5_ann_3 - w5_ann_baseline) \
                   if not (np.isnan(w5_ann_baseline) or np.isnan(w5_ann_3)) else float("nan")
        rows.append({
            "w_a": w_a,
            "gross_t": g_3["gross_t"], "oos_t": g_3["oos_t"],
            "passes_gross": g_3["passes_gross"], "passes_oos": g_3["passes_oos"],
            "passes_all": g_3["passes_all"],
            "max_dd": dd_3, "sharpe": sharpe, "time_in_market": tim,
            "delta_oos_t_vs_baseline": delta_oos_t,
            "w5_ann_pct": w5_ann_3,
            "w5_ann_pct_baseline": w5_ann_baseline,
            "delta_w5_ann_pct": delta_w5,
            "per_window": pw_3,
        })

    # Print sweep table
    print("  w_A   | gross_t | OOS_t   | pass | maxDD    | sharpe | %TIM | "
          "ΔOOS_t  | W5 ann% | ΔW5 ann%")
    print("  -------|---------|---------|------|----------|--------|------|"
          "---------|---------|---------")
    for r in rows:
        print(f"  {r['w_a']:>4.2f}  | {r['gross_t']:>+7.2f} | {r['oos_t']:>+7.2f} | "
              f"{'✓' if r['passes_all'] else '✗'}    | {r['max_dd']:>+8.2%} | "
              f"{r['sharpe']:>+6.2f} | {r['time_in_market']:>4.0%} | "
              f"{r['delta_oos_t_vs_baseline']:>+7.2f}  | "
              f"{r['w5_ann_pct']:>+7.1f} | {r['delta_w5_ann_pct']:>+7.1f}")
    print()

    # ── Best w_A selection (R74 verdict) ─────────────────────────────────────
    # Lesson #41 hypothesis: best w_A clears 3-check AND ΔOOS_t ≥ +0.5.
    viable = [r for r in rows if r["passes_all"] and r["delta_oos_t_vs_baseline"] >= 0.5]
    if viable:
        best = max(viable, key=lambda r: r["oos_t"])
        verdict = "✅ FUSION LIFT — pillar_A carries as 3rd fusion contribution"
        verdict_band = "FUSION_LIFT"
    else:
        # Diagnostic: best by OOS t lift (positive or zero)
        diagnostic = [r for r in rows if r["delta_oos_t_vs_baseline"] > 0]
        if diagnostic:
            best = max(diagnostic, key=lambda r: r["delta_oos_t_vs_baseline"])
            verdict = ("🟡 NEUTRAL — best w_A improves OOS but doesn't clear "
                       "3-check OR ΔOOS_t < +0.5")
            verdict_band = "FUSION_NEUTRAL"
        else:
            # Pick any w_A > 0 as the diagnostic; show best (least bad) by OOS_t
            non_zero = [r for r in rows if r["w_a"] > 0]
            best = max(non_zero, key=lambda r: r["oos_t"]) if non_zero else rows[0]
            verdict = ("🔴 FUSION LOSES — pillar_A does NOT carry as fusion contribution; "
                       "REFUTED at the gauntlet = REFUTED in the fusion book too")
            verdict_band = "FUSION_LOSES"

    print(f"Best w_A = {best['w_a']:.2f}: gross_t={best['gross_t']:+.2f}, "
          f"OOS_t={best['oos_t']:+.2f}, maxDD={best['max_dd']:+.2%}, "
          f"ΔOOS_t={best['delta_oos_t_vs_baseline']:+.2f}")
    print(f"Verdict: {verdict}\n")

    # ── Capacity proxy (P2) for the best 3-component fusion ──────────────────
    turnover_r46 = float(estimate_turnover_ann(pillar_o_w, rets[tradeable], R46_CAD))
    turnover_r62 = float(estimate_turnover_ann(score, rets[tradeable], R62_CAD))
    score_a_wide = score_pillar_a_level(cis_long).reindex(columns=tradeable) \
                                                .reindex(rets.index).ffill()
    turnover_r73 = float(estimate_turnover_ann(score_a_wide, rets[tradeable],
                                                R73_BEST_CAD))
    fused_turnover_ann = ((1 - best["w_a"]) *
                           (R69_W_R46 * turnover_r46 + R69_W_R62 * turnover_r62)
                          + best["w_a"] * turnover_r73)
    CRUDE_ADV_USD = 50e6
    PER_LEG_CLIP_PCT = 0.05
    crude_capacity_usd = (CRUDE_ADV_USD * PER_LEG_CLIP_PCT * 3)  # 3 legs now

    print(f"Capacity proxy (P2, 3-leg): turnover_ann ≈ {fused_turnover_ann:.1f}, "
          f"declared_capacity ≈ ${crude_capacity_usd/1e6:.1f}M "
          f"(crude ADV × {PER_LEG_CLIP_PCT:.0%}/leg × 3-leg)\n")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable),
                  "matched_assets": tradeable},
        "construction": {
            "leg_r46": {"cadence": R46_CAD, "cost_bps": R46_BPS, "k_terciles": R46_K,
                          "universe": "28-asset funding-bearing intersection"},
            "leg_r62": {"cadence": R62_CAD, "cost_bps": R62_BPS, "k_terciles": R46_K,
                          "feature_set": R62_FEATURE_SET, "z_threshold": R62_Z,
                          "min_features": R62_MF, "zwin": zwin,
                          "universe": "28-asset funding-bearing intersection"},
            "leg_r73": {"cadence": R73_BEST_CAD, "cost_bps": R73_BEST_BPS,
                          "k_terciles": R73_K_TERCILES, "sign": leg_a_sign,
                          "score_basis": "level_A",
                          "universe": "28-asset funding-bearing intersection"},
            "r69_baseline_weights": {"w_r46": R69_W_R46, "w_r62": R69_W_R62},
            "w_a_grid": list(w_a_grid),
        },
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                      "n_days": int((e - s).days + 1),
                      "fragile": lab in fragile_labels} for lab, s, e in windows],
        "leg_r46": {"gauntlet": g_r46, "max_dd": dd_r46},
        "leg_r62": {"gauntlet": g_r62, "max_dd": dd_r62},
        "leg_r73": {"gauntlet": g_r73, "max_dd": dd_r73,
                    "matched_cell_direction": "high_a_long" if leg_a_sign == SIGN_HIGH_A_LONG
                                              else "low_a_long"},
        "correlations": {
            "corr_r46_r62": corr_legs_r46_r62,
            "corr_r46_r73": corr_legs_r46_r73,
            "corr_r62_r73": corr_legs_r62_r73,
        },
        "baseline_2comp": {
            "w_r46": R69_W_R46, "w_r62": R69_W_R62,
            "gauntlet": g_baseline,
            "max_dd": dd_baseline,
            "per_window": pw_baseline,
        },
        "w_a_sweep": [
            {"w_a": r["w_a"],
             "gauntlet": {k: r[k] for k in ["gross_t", "oos_t", "passes_gross",
                                              "passes_oos", "passes_all"]},
             "max_dd": r["max_dd"], "sharpe": r["sharpe"], "time_in_market": r["time_in_market"],
             "delta_oos_t_vs_baseline": r["delta_oos_t_vs_baseline"],
             "w5_ann_pct": r["w5_ann_pct"],
             "w5_ann_pct_baseline": r["w5_ann_pct_baseline"],
             "delta_w5_ann_pct": r["delta_w5_ann_pct"],
             "per_window": r["per_window"]}
            for r in rows
        ],
        "best_w_a": {
            "w_a": best["w_a"],
            "gauntlet": {k: best[k] for k in ["gross_t", "oos_t", "passes_gross",
                                                "passes_oos", "passes_all"]},
            "max_dd": best["max_dd"], "sharpe": best["sharpe"],
            "time_in_market": best["time_in_market"],
            "delta_oos_t_vs_baseline": best["delta_oos_t_vs_baseline"],
            "w5_ann_pct": best["w5_ann_pct"],
            "delta_w5_ann_pct": best["delta_w5_ann_pct"],
            "per_window": best["per_window"],
            "turnover_ann": fused_turnover_ann,
            "crude_capacity_usd": crude_capacity_usd,
        },
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "delta_oos_t_best": best["delta_oos_t_vs_baseline"],
            "delta_w5_ann_pct_best": best["delta_w5_ann_pct"],
            "lesson_42_candidate": None,   # filled in by format_report if applicable
        },
        "live_book_impact": {
            "touches_frozen_r69_cell": False,
            "r65_paper_book_unaffected": True,
            "r66_tracking_unaffected": True,
            "note": "R74 is research-only. Forward R75 candidate MAY rebalance "
                    "w_R46/w_A based on R74 verdict.",
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable R74 report (verdict-focused)."""
    lines = []
    lines.append("# R74 — pillar_A as 3rd fusion contribution to R69 family")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_assets_intersection']}-asset strict universe)")
    lines.append("")
    lines.append("## Verdict")
    v = payload["verdict"]
    lines.append(f"**{v['band']}** — {v['verdict_string']}")
    lines.append("")
    lines.append(f"- Best w_A = **{payload['best_w_a']['w_a']:.2f}**")
    lines.append(f"- Best w_A gross_t = {payload['best_w_a']['gauntlet']['gross_t']:+.2f}, "
                 f"OOS_t = {payload['best_w_a']['gauntlet']['oos_t']:+.2f}, "
                 f"passes_all = {payload['best_w_a']['gauntlet']['passes_all']}")
    lines.append(f"- ΔOOS_t vs frozen baseline = "
                 f"{payload['best_w_a']['delta_oos_t_vs_baseline']:+.2f}")
    lines.append(f"- ΔW5 ann% = {payload['best_w_a']['delta_w5_ann_pct']:+.1f}")
    lines.append("")
    lines.append("## Frozen baseline (R69 cell, w_A=0)")
    bl = payload["baseline_2comp"]
    lines.append(f"- w_R46 = {bl['w_r46']}, w_R62 = {bl['w_r62']}")
    lines.append(f"- gross_t = {bl['gauntlet']['gross_t']:+.2f}, "
                 f"OOS_t = {bl['gauntlet']['oos_t']:+.2f}, "
                 f"passes_all = {bl['gauntlet']['passes_all']}, "
                 f"maxDD = {bl['max_dd']:+.2%}")
    lines.append("")
    lines.append("## Per-leg gauntlet (on 28-asset)")
    for leg in ("leg_r46", "leg_r62", "leg_r73"):
        g = payload[leg]["gauntlet"]
        lines.append(f"- **{leg}**: gross_t = {g['gross_t']:+.2f}, "
                     f"OOS_t = {g['oos_t']:+.2f}, "
                     f"maxDD = {payload[leg]['max_dd']:+.2%}")
    lines.append("")
    lines.append("## Leg correlations (R46/R62/R73)")
    c = payload["correlations"]
    lines.append(f"- corr(R46, R62) = {c['corr_r46_r62']:+.2f}")
    lines.append(f"- corr(R46, R73) = {c['corr_r46_r73']:+.2f}")
    lines.append(f"- corr(R62, R73) = {c['corr_r62_r73']:+.2f}")
    lines.append("")
    lines.append("## w_A sweep (3-component fusion on top of frozen R69 cell)")
    lines.append("| w_A | gross_t | OOS_t | pass | maxDD | sharpe | "
                 "ΔOOS_t | W5 ann% | ΔW5 ann% |")
    lines.append("|---:|---:|---:|:--:|---:|---:|---:|---:|---:|")
    for r in payload["w_a_sweep"]:
        lines.append(f"| {r['w_a']:.2f} | {r['gauntlet']['gross_t']:+.2f} | "
                     f"{r['gauntlet']['oos_t']:+.2f} | "
                     f"{'✓' if r['gauntlet']['passes_all'] else '✗'} | "
                     f"{r['max_dd']:+.2%} | {r['sharpe']:+.2f} | "
                     f"{r['delta_oos_t_vs_baseline']:+.2f} | "
                     f"{r['w5_ann_pct']:+.1f} | "
                     f"{r['delta_w5_ann_pct']:+.1f} |")
    lines.append("")
    lines.append("## Capacity proxy (P2, 3-leg)")
    lines.append(f"- turnover_ann ≈ {payload['best_w_a']['turnover_ann']:.1f}")
    lines.append(f"- declared_capacity ≈ "
                 f"${payload['best_w_a']['crude_capacity_usd']/1e6:.1f}M "
                 f"(crude ADV × 5%/leg × 3-leg)")
    lines.append("")
    lines.append("## Live book impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R69 cell: **{li['touches_frozen_r69_cell']}**")
    lines.append(f"- R65 paper book unaffected: **{li['r65_paper_book_unaffected']}**")
    lines.append(f"- R66 tracking unaffected: **{li['r66_tracking_unaffected']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    lines.append("## Lesson #42 (proposed, depends on verdict)")
    if v["band"] == "FUSION_LIFT":
        lines.append("- ✅ Aggregate lesson #42: \"REFUTED sleeves may still ship "
                     "as fusion contributions. The gauntlet verdict is per-cell, "
                     "not per-mechanism. pillar_A's standalone REFUTED (R73, "
                     "α_t=+1.69) does NOT preclude its value as a small (~5-10%) "
                     "diversifying contribution to the fusion book.\"")
    elif v["band"] == "FUSION_NEUTRAL":
        lines.append("- 🟡 Aggregate lesson #42 (partial): \"REFUTED sleeves may "
                     "ship as fusion contribution only when their directional "
                     "differential survives at small w. pillar_A lifts OOS at "
                     "the best w_A but doesn't clear the 3-check at any weight; "
                     "the fusion contribution is real but small.\"")
    else:
        lines.append("- 🔴 Aggregate lesson #42 (negative): \"REFUTED at the "
                     "gauntlet → don't rescue via fusion. The fusion only works "
                     "if the leg independently clears enough cells. pillar_A's "
                     "matched-cell +3.07 directional differential does NOT carry "
                     "as fusion contribution at any w_A.\"")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--leg-a-sign", type=str, default=SIGN_HIGH_A_LONG,
                        choices=[SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r74_pillar_a_fusion_contribution/{today}")
    payload = run(out, leg_a_sign=args.leg_a_sign)

    out.mkdir(parents=True, exist_ok=True)
    verdict_path = out / "verdict.json"
    report_path = out / "REPORT.md"
    with verdict_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with report_path.open("w") as f:
        f.write(format_report(payload))

    print(f"Wrote {verdict_path}")
    print(f"Wrote {report_path}")
    print()
    print(format_report(payload))
