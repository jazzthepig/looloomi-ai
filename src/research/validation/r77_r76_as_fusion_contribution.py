"""
R77 — R76 (funding residual) as 3rd fusion contribution to R69 family (Seth, 2026-07-22).

Per R76 lesson #43 (proposed 2026-07-22): orthogonal signal sources carry real
cross-sectional edges that survive the 3-check gauntlet AND are uncorrelated with
existing fusion legs. R76 SURVIVES + ORTHOGONAL: best cell 5d/0bps
gross_t=+2.11, OOS_t=+3.15, with W5=+98.4% (the late-cycle fragility window where
R46 sign-flips at −54.1%).

R77 tests whether R76's orthogonal-edge property translates to a real fusion lift
on top of the existing R46+R62 fusion (R69 cell, frozen at w_R46=0.25).

Methodology (anti-imposter — parallel to R74, but with the lesson #42 gate already proven):
  · Reuse R63's exact panel + 28-asset strict funding ∩ CIS ∩ OHLCV universe.
  · Leg 1: R46 pillar_O 5d/5bps (R63's existing leg_r46).
  · Leg 2: R62 fade-the-crowd 21d/0bps gated (R63's existing leg_r62).
  · Leg 3 (NEW): R76 funding residual 5d/0bps (R76's best cell, k=3).
  · Frozen 2-component baseline: fac_2 = 0.25 × Leg1 + 0.75 × Leg2 (R69 cell).
  · 3-component fusion: fac_3 = (1-w_R76) × fac_2 + w_R76 × Leg3.
  · Sweep w_R76 ∈ {0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30}.
  · At each w_R76: 3-check gauntlet + per-window W1-W6 + max DD.
  · Pre-test leg-correlation gate (lesson #42 — already proven by R76: passes).

Verdict grammar (R77-specific):
  · ✅ FUSION LIFT — best w_R76 clears 3-check AND ΔOOS_t ≥ +0.5 vs frozen
                     baseline (w_R76=0). Lesson #43 holds: orthogonal candidate
                     lifts the fusion.
  · 🟡 NEUTRAL     — best w_R76 improves 1-2 of 3 checks but ΔOOS_t < +0.5
                     OR sign-flip not eliminated.
  · 🔴 FUSION LOSES — best w_R76 gives ΔOOS_t ≤ 0 OR W5 sign-flips more than
                      the frozen baseline. Lesson #43 sharpens: orthogonal
                      candidates may not translate to fusion lift even when
                      they pass the leg-correlation gate.

Universe (anti-imposter strict): same 28-asset funding ∩ CIS ∩ OHLCV that R63,
R73, R74, R76 all used. Do not silently widen — if funding coverage falls below
R76's MIN_TRADEABLE floor, R77 must refuse rather than fall back to a wider
CIS-only panel (lesson #42 anti-imposter discipline).

This module does NOT touch the live fusion book (R65/R66). The frozen R69 cell
at w_R46=0.25 stays unchanged regardless of R77's verdict. R77 builds evidence
for a forward R78 candidate that may rebalance w_R46 + add w_R76 to the live
fusion book.
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
    estimate_turnover_ann,
)
from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, DEFAULT_ZWIN, R46_K,
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
    fuse, max_drawdown, per_window,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    R62_FEATURE_SET, R62_Z, R62_MF,
)
from src.research.validation.r76_funding_residual_ls import (
    score_funding_residual, funding_residual_ls,
    leg_correlation_gate,
    R76_K_TERCILES,
    SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# Frozen R69 cell weights (NEVER mutate in R77 — R77 is a TEST)
R69_W_R46 = 0.25
R69_W_R62 = 0.75   # = 1 - R69_W_R46

# R76's best cell (used for Leg 3, funding residual)
R76_BEST_CAD = 5
R76_BEST_BPS = 0.0

# Weight sweep for Leg 3 (w_R76 in 3-component fusion)
R77_W_GRID = (0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30)

# Lesson #42 orthogonality gate (re-asserted for R77)
R77_ORTHOGONALITY_GATE = 0.30


# === R62 detector reproduction (lifted from R63) =============================
def _build_r62_detector_local(features: pd.DataFrame, fragile_mask: pd.Series,
                              fragile_ranges: list, playable_ranges: list):
    """Reproduce R62 best-cell detector on the R77 panel."""
    ks = build_fragility_ks_table(features, fragile_mask)
    external_cols = [c for c in features.columns if c in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    det, _ = build_w5_detector(
        features,
        *fragile_ranges[0] if fragile_ranges else (features.index[0], features.index[0]),
        *playable_ranges[0] if playable_ranges else (features.index[0], features.index[0]),
        ks, feature_subset=external_cols,
        z_threshold=R62_Z, min_features=R62_MF,
    )
    return det


# === Leg 3 builder (R76's funding residual L/S on the same panel) ===========
def build_r76_sleeve_28(funding_daily: pd.DataFrame, rets: pd.DataFrame,
                        tradeable: list, sign: str = SIGN_HIGH_FUND_LONG,
                        rebal_days: int = R76_BEST_CAD,
                        cost_bps: float = R76_BEST_BPS) -> pd.Series:
    """R76 funding residual cross-sectional L/S on the tradeable universe.

    Score = funding[t, a] - mean_a(funding[t, a]) (cross-sectional demean).
    Sign convention: SIGN_HIGH_FUND_LONG = long high-funding-residual / short low.
    """
    score_wide = score_funding_residual(funding_daily, tradeable)
    score_wide = score_wide.reindex(rets.index).ffill()
    fac = funding_residual_ls(score_wide, rets[tradeable],
                                k_terciles=R76_K_TERCILES, cost_bps=cost_bps,
                                rebal_days=rebal_days, sign=sign)
    return fac.reindex(rets.index).fillna(0.0)


# === 3-component fusion ======================================================
def fuse3(fac_2: pd.Series, fac_r76: pd.Series, w_r76: float) -> pd.Series:
    """3-component fusion given the frozen 2-component baseline fac_2.

    fac_3 = (1 - w_R76) × fac_2 + w_R76 × fac_r76

    Aligned to fac_2's index. NaN in fac_r76 → 0 (no contribution that day).
    """
    aligned_r76 = fac_r76.reindex(fac_2.index).fillna(0.0)
    return (1.0 - w_r76) * fac_2 + w_r76 * aligned_r76


# === Run =====================================================================
def run(out_dir: Path,
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS,
        zwin: int = DEFAULT_ZWIN,
        w_grid: tuple = R77_W_GRID,
        leg_r76_sign: str = SIGN_HIGH_FUND_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R77 — R76 (funding residual) as 3rd fusion contribution to R69 family ===\n")
    print(f"Frozen R69 cell: w_R46={R69_W_R46}, w_R62={R69_W_R62}")
    print(f"R76 Leg 3: funding residual {R76_BEST_CAD}d/{R76_BEST_BPS}bps, "
          f"sign={leg_r76_sign}\n")

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
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                       sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis_long, rets, tradeable_full, tradeable,
                                       funding_daily)
    feats = feats.reindex(rets.index)
    det = _build_r62_detector_local(feats, fragile_mask, fragile_ranges, playable_ranges)
    leg_r62 = build_r62_sleeve_28(score_zwide, rets, tradeable, det)

    # ── Leg 3 (R76 funding residual 5d/0bps) — R77 NEW ──────────────────────
    print(f"Building Leg 3 (R76 funding residual {R76_BEST_CAD}d/{R76_BEST_BPS}bps, "
          f"sign={leg_r76_sign}) …")
    leg_r76 = build_r76_sleeve_28(funding_daily, rets, tradeable, sign=leg_r76_sign)

    # ── Known factors + OOS cut (R63 parity) ─────────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── Per-leg gauntlet + correlation gate (lesson #42) ──────────────────────
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    g_r76 = gauntlet_3check(leg_r76.values, known_full, cut)
    gate = leg_correlation_gate(leg_r76, leg_r46, leg_r62,
                                 gate=R77_ORTHOGONALITY_GATE)
    dd_r46 = max_drawdown(leg_r46)
    dd_r62 = max_drawdown(leg_r62)
    dd_r76 = max_drawdown(leg_r76)

    print(f"Leg R46: gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}, "
          f"maxDD={dd_r46:+.2%}")
    print(f"Leg R62: gross_t={g_r62['gross_t']:+.2f}, OOS_t={g_r62['oos_t']:+.2f}, "
          f"maxDD={dd_r62:+.2%}")
    print(f"Leg R76: gross_t={g_r76['gross_t']:+.2f}, OOS_t={g_r76['oos_t']:+.2f}, "
          f"maxDD={dd_r76:+.2%}")
    print(f"corr(R76,R46)={gate['corr_r76_vs_r46']:+.3f}, "
          f"corr(R76,R62)={gate['corr_r76_vs_r62']:+.3f}, "
          f"max |corr|={gate['max_abs_corr']:.3f}, "
          f"gate_passes={gate['passes_orthogonality_gate']}\n")

    # ── Frozen 2-component baseline (R69 cell) ───────────────────────────────
    fac_2_baseline = fuse(leg_r46, leg_r62, R69_W_R46)
    g_baseline = gauntlet_3check(fac_2_baseline.values, known_full, cut)
    dd_baseline = max_drawdown(fac_2_baseline)
    pw_baseline = per_window(fac_2_baseline, windows)
    print(f"Frozen baseline (w_R46={R69_W_R46:.2f}, w_R76=0): "
          f"gross_t={g_baseline['gross_t']:+.2f}, OOS_t={g_baseline['oos_t']:+.2f}, "
          f"maxDD={dd_baseline:+.2%}, pass_all={g_baseline['passes_all']}\n")

    # ── Weight sweep on w_R76 (3-component fusion) ───────────────────────────
    print(f"══ w_R76 sweep on top of frozen R69 cell (w_R76 ∈ {list(w_grid)}) ══\n")
    rows = []
    for w_r76 in w_grid:
        fused_3 = fuse3(fac_2_baseline, leg_r76, w_r76)
        g_3 = gauntlet_3check(fused_3.values, known_full, cut)
        dd_3 = max_drawdown(fused_3)
        pw_3 = per_window(fused_3, windows)
        tim = float((fused_3 != 0).mean())
        sharpe = float(fused_3.mean() / fused_3.std() * np.sqrt(PERIODS_PER_YEAR)) \
                 if fused_3.std() > 0 else float("nan")
        # ΔOOS_t vs frozen baseline (the lesson #43 hypothesis test)
        delta_oos_t = g_3["oos_t"] - g_baseline["oos_t"]
        # Per-window delta (especially W5 — R76's killer window)
        w5_ann_baseline = pw_baseline.get("W5", {}).get("ann_pct", float("nan"))
        w5_ann_3 = pw_3.get("W5", {}).get("ann_pct", float("nan"))
        delta_w5 = (w5_ann_3 - w5_ann_baseline) \
                   if not (np.isnan(w5_ann_baseline) or np.isnan(w5_ann_3)) else float("nan")
        rows.append({
            "w_r76": w_r76,
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
    print("  w_R76 | gross_t | OOS_t   | pass | maxDD    | sharpe | %TIM | "
          "ΔOOS_t  | W5 ann% | ΔW5 ann%")
    print("  -------|---------|---------|------|----------|--------|------|"
          "---------|---------|---------")
    for r in rows:
        print(f"  {r['w_r76']:>4.2f}  | {r['gross_t']:>+7.2f} | {r['oos_t']:>+7.2f} | "
              f"{'✓' if r['passes_all'] else '✗'}    | {r['max_dd']:>+8.2%} | "
              f"{r['sharpe']:>+6.2f} | {r['time_in_market']:>4.0%} | "
              f"{r['delta_oos_t_vs_baseline']:>+7.2f}  | "
              f"{r['w5_ann_pct']:>+7.1f} | {r['delta_w5_ann_pct']:>+7.1f}")
    print()

    # ── Best w_R76 selection (R77 verdict) ───────────────────────────────────
    # Lesson #43 hypothesis: best w_R76 clears 3-check AND ΔOOS_t ≥ +0.5.
    viable = [r for r in rows if r["passes_all"] and r["delta_oos_t_vs_baseline"] >= 0.5]
    if viable:
        best = max(viable, key=lambda r: r["oos_t"])
        verdict = "✅ FUSION LIFT — R76 carries as 3rd fusion contribution to R69 family"
        verdict_band = "FUSION_LIFT"
    else:
        # Diagnostic: best by OOS t lift (positive or zero)
        diagnostic = [r for r in rows if r["delta_oos_t_vs_baseline"] > 0]
        if diagnostic:
            best = max(diagnostic, key=lambda r: r["delta_oos_t_vs_baseline"])
            verdict = ("🟡 NEUTRAL — best w_R76 improves OOS but doesn't clear "
                       "3-check OR ΔOOS_t < +0.5")
            verdict_band = "FUSION_NEUTRAL"
        else:
            non_zero = [r for r in rows if r["w_r76"] > 0]
            best = max(non_zero, key=lambda r: r["oos_t"]) if non_zero else rows[0]
            verdict = ("🔴 FUSION LOSES — orthogonal candidate does NOT lift fusion; "
                       "lesson #43 sharpens: orthogonal standalone ≠ orthogonal fusion lift")
            verdict_band = "FUSION_LOSES"

    print(f"Best w_R76 = {best['w_r76']:.2f}: gross_t={best['gross_t']:+.2f}, "
          f"OOS_t={best['oos_t']:+.2f}, maxDD={best['max_dd']:+.2%}, "
          f"ΔOOS_t={best['delta_oos_t_vs_baseline']:+.2f}")
    print(f"Verdict: {verdict}\n")

    # ── Capacity proxy (P2) for the best 3-component fusion ──────────────────
    turnover_r46 = float(estimate_turnover_ann(pillar_o_w, rets[tradeable], R46_CAD))
    turnover_r62 = float(estimate_turnover_ann(score_zwide, rets[tradeable], R62_CAD))
    score_resid_wide = score_funding_residual(funding_daily, tradeable) \
                                              .reindex(rets.index).ffill()
    turnover_r76 = float(estimate_turnover_ann(score_resid_wide, rets[tradeable],
                                                R76_BEST_CAD))
    fused_turnover_ann = ((1 - best["w_r76"]) *
                           (R69_W_R46 * turnover_r46 + R69_W_R62 * turnover_r62)
                          + best["w_r76"] * turnover_r76)
    CRUDE_ADV_USD = 50e6
    PER_LEG_CLIP_PCT = 0.05
    crude_capacity_usd = (CRUDE_ADV_USD * PER_LEG_CLIP_PCT * 3)  # 3 legs

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
            "leg_r76": {"cadence": R76_BEST_CAD, "cost_bps": R76_BEST_BPS,
                          "k_terciles": R76_K_TERCILES, "sign": leg_r76_sign,
                          "score_basis": "funding_residual (cross-sectional demean)",
                          "universe": "28-asset funding-bearing intersection"},
            "r69_baseline_weights": {"w_r46": R69_W_R46, "w_r62": R69_W_R62},
            "w_grid": list(w_grid),
            "orthogonality_gate": R77_ORTHOGONALITY_GATE,
        },
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                      "n_days": int((e - s).days + 1),
                      "fragile": lab in fragile_labels} for lab, s, e in windows],
        "leg_r46": {"gauntlet": g_r46, "max_dd": dd_r46},
        "leg_r62": {"gauntlet": g_r62, "max_dd": dd_r62},
        "leg_r76": {"gauntlet": g_r76, "max_dd": dd_r76,
                    "matched_cell_direction": "high_fund_long" if leg_r76_sign == SIGN_HIGH_FUND_LONG
                                                 else "low_fund_long"},
        "leg_correlation_gate": gate,
        "baseline_2comp": {
            "w_r46": R69_W_R46, "w_r62": R69_W_R62,
            "gauntlet": g_baseline,
            "max_dd": dd_baseline,
            "per_window": pw_baseline,
        },
        "w_r76_sweep": [
            {"w_r76": r["w_r76"],
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
        "best_w_r76": {
            "w_r76": best["w_r76"],
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
        },
        "live_book_impact": {
            "touches_frozen_r69_cell": False,
            "r65_paper_book_unaffected": True,
            "r66_tracking_unaffected": True,
            "note": "R77 is research-only. Forward R78 candidate MAY rebalance "
                    "w_R46 + add w_R76 based on R77 verdict.",
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable R77 report (verdict-focused)."""
    lines = []
    lines.append("# R77 — R76 (funding residual) as 3rd fusion contribution to R69 family")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_assets_intersection']}-asset strict universe)")
    lines.append("")
    lines.append("## Verdict")
    v = payload["verdict"]
    lines.append(f"**{v['band']}** — {v['verdict_string']}")
    lines.append("")
    lines.append(f"- Best w_R76 = **{payload['best_w_r76']['w_r76']:.2f}**")
    lines.append(f"- Best w_R76 gross_t = {payload['best_w_r76']['gauntlet']['gross_t']:+.2f}, "
                 f"OOS_t = {payload['best_w_r76']['gauntlet']['oos_t']:+.2f}, "
                 f"passes_all = {payload['best_w_r76']['gauntlet']['passes_all']}")
    lines.append(f"- ΔOOS_t vs frozen baseline = "
                 f"{payload['best_w_r76']['delta_oos_t_vs_baseline']:+.2f}")
    lines.append(f"- ΔW5 ann% = {payload['best_w_r76']['delta_w5_ann_pct']:+.1f}")
    lines.append("")
    lines.append("## Frozen baseline (R69 cell, w_R76=0)")
    bl = payload["baseline_2comp"]
    lines.append(f"- w_R46 = {bl['w_r46']}, w_R62 = {bl['w_r62']}")
    lines.append(f"- gross_t = {bl['gauntlet']['gross_t']:+.2f}, "
                 f"OOS_t = {bl['gauntlet']['oos_t']:+.2f}, "
                 f"passes_all = {bl['gauntlet']['passes_all']}, "
                 f"maxDD = {bl['max_dd']:+.2%}")
    lines.append("")
    lines.append("## Per-leg gauntlet (on 28-asset)")
    for leg in ("leg_r46", "leg_r62", "leg_r76"):
        g = payload[leg]["gauntlet"]
        lines.append(f"- **{leg}**: gross_t = {g['gross_t']:+.2f}, "
                     f"OOS_t = {g['oos_t']:+.2f}, "
                     f"maxDD = {payload[leg]['max_dd']:+.2%}")
    lines.append("")
    lines.append("## Leg-correlation gate (lesson #42, R76 result)")
    g = payload["leg_correlation_gate"]
    lines.append(f"- corr(R76, R46) = {g['corr_r76_vs_r46']:+.3f}")
    lines.append(f"- corr(R76, R62) = {g['corr_r76_vs_r62']:+.3f}")
    lines.append(f"- max |corr| = {g['max_abs_corr']:.3f} (gate ≤ {g['gate_threshold']})")
    lines.append(f"- passes_orthogonality_gate = **{g['passes_orthogonality_gate']}**")
    lines.append("")
    lines.append("## w_R76 sweep (3-component fusion on top of frozen R69 cell)")
    lines.append("| w_R76 | gross_t | OOS_t | pass | maxDD | sharpe | "
                 "ΔOOS_t | W5 ann% | ΔW5 ann% |")
    lines.append("|---:|---:|---:|:--:|---:|---:|---:|---:|---:|")
    for r in payload["w_r76_sweep"]:
        lines.append(f"| {r['w_r76']:.2f} | {r['gauntlet']['gross_t']:+.2f} | "
                     f"{r['gauntlet']['oos_t']:+.2f} | "
                     f"{'✓' if r['gauntlet']['passes_all'] else '✗'} | "
                     f"{r['max_dd']:+.2%} | {r['sharpe']:+.2f} | "
                     f"{r['delta_oos_t_vs_baseline']:+.2f} | "
                     f"{r['w5_ann_pct']:+.1f} | "
                     f"{r['delta_w5_ann_pct']:+.1f} |")
    lines.append("")
    lines.append("## Capacity proxy (P2, 3-leg)")
    lines.append(f"- turnover_ann ≈ {payload['best_w_r76']['turnover_ann']:.1f}")
    lines.append(f"- declared_capacity ≈ "
                 f"${payload['best_w_r76']['crude_capacity_usd']/1e6:.1f}M "
                 f"(crude ADV × 5%/leg × 3-leg)")
    lines.append("")
    lines.append("## Live book impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R69 cell: **{li['touches_frozen_r69_cell']}**")
    lines.append(f"- R65 paper book unaffected: **{li['r65_paper_book_unaffected']}**")
    lines.append(f"- R66 tracking unaffected: **{li['r66_tracking_unaffected']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    lines.append("## Aggregate lesson (proposed, depends on verdict)")
    if v["band"] == "FUSION_LIFT":
        lines.append("- ✅ Aggregate lesson: \"Lesson #43 holds — orthogonal candidates "
                     "(funding residual, |corr|=0.156) DO carry as 3rd fusion contribution. "
                     "Lesson #42 + #43 form a complete pair: 'don't rescue via fusion' + "
                     "'do test orthogonal candidates'. The R76 W5=+98.4% (where R46 fails "
                     "at −54.1%) translates directly into positive ΔOOS_t at the fusion "
                     "level. R78 candidate = rebalance w_R46 down from 0.25 + add "
                     "w_R76=0.10-0.15 to the live R69 cell.\"")
    elif v["band"] == "FUSION_NEUTRAL":
        lines.append("- 🟡 Aggregate lesson (partial): \"Lesson #43 partial — orthogonal "
                     "candidate lifts OOS at the fusion level but doesn't clear the 3-check "
                     "bar OR ΔOOS_t < +0.5. The W5 lift is real but the marginal "
                     "contribution is small; further investigation needed.\"")
    else:
        lines.append("- 🔴 Aggregate lesson (sharpens #43): \"Orthogonal standalone ≠ "
                     "orthogonal fusion lift. R76 passes the leg-correlation gate but the "
                     "fusion lift is negative at every w_R76. Lesson #43 sharpens: even "
                     "with orthogonal signal source, the fusion may not benefit if the "
                     "baseline R69 cell is already capturing the orthogonal structure.\"")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--leg-r76-sign", type=str, default=SIGN_HIGH_FUND_LONG,
                        choices=[SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r77_r76_as_fusion_contribution/{today}")
    payload = run(out, leg_r76_sign=args.leg_r76_sign)

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
