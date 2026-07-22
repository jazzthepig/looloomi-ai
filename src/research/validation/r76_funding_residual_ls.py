"""
R76 — Funding residual cross-sectional L/S (Seth, 2026-07-22).

Per R74 lesson #42 (proposed 2026-07-22): REFUTED at the gauntlet → don't rescue
via fusion. The fusion book only works when (a) the leg independently clears enough
cells AND (b) is sufficiently orthogonal (|corr| ≲ 0.30) to existing fusion legs.
R73/R74 closed the CIS-quality lane (pillar_A is correlated +0.69 with R46 pillar_O).

R76 opens a genuinely orthogonal signal source: **funding residual** = funding[t, asset]
− cross-sectional mean(funding[t, :]). This is NOT the same as R62's
`score_funding_zwide` (per-asset z over time). Funding residual captures RELATIVE
funding pressure within the universe on each date — an asset with above-mean funding
has more long pressure than the universe average, and vice versa.

R76 design:
  · Universe: same 28-asset strict funding ∩ CIS ∩ OHLCV (R46/R62/R73/R74 parity).
  · Score: funding[t, a] − mean_a(funding[t, a]) — cross-sectional demean (NOT z-score).
  · k_terciles = 3 (R46/R73 standard).
  · Cadences {1,3,5,7,14,21}d × costs {0,5,10}bps.
  · 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  · Per-window W1-W6 attribution.
  · **Pre-test leg-correlation gate (lesson #42 anti-imposter)**: measure
    corr(R76_leg, R46_leg) and corr(R76_leg, R62_leg) BEFORE fusion sweep.
    If max |corr| > 0.30 vs existing legs, flag the candidate as fusion-uncandidatable
    (it would be R74's mistake to add it to the fusion book).
  · Both signs run; matched-cell sign verdict.

Verdict grammar:
  · ✅ SURVIVES + ORTHOGONAL — clears 3-check AND max |corr| ≤ 0.30 vs existing legs.
    Eligible for fusion contribution (R77 candidate material).
  · 🟡 SURVIVES + CORRELATED — clears 3-check BUT correlated (|corr| > 0.30) with
    existing legs → standalone-eligible but NOT fusion-uncandidatable (R73 pattern).
  · 🔴 REFUTED — fails 3-check. Lesson #42 sharpens: orthogonal candidate direction
    matters more than signal source; R46+R62 fusion may be near-optimal for this data.

Aggregate lesson #43 (depends on verdict):
  - ✅ if true: "Orthogonal signal sources carry real cross-sectional edges that
    survive the 3-check gauntlet AND are uncorrelated with existing fusion legs.
    Lesson #42 holds: leg-correlation gate is necessary; orthogonal candidates are
    the right next R-number."
  - 🟡 if true: "Standalone edge exists but leg-correlation is structural; orthogonal
    candidates must be screened for |corr| ≲ 0.30 BEFORE testing standalone."
  - 🔴 if true: "Lesson #42 sharpens: residual funding signal may not have any
    standalone edge after residualization. R46+R62 fusion may be near-optimal for
    this data; future R-numbers need to look at structurally different sources
    (cross-asset carry, microstructure volatility, regime-conditional overlays)."

Anti-imposter:
  - Funding residual is NOT the same as funding-z (R62's score). Funding-z normalizes
    per-asset over time; funding residual demeans cross-sectionally at each t. The
    correlation between funding-z and funding-residual is intentionally near zero
    (different normalizations).
  - Pre-test leg-correlation gate is MANDATORY (lesson #42). Don't run the fusion
    sweep until the gate clears.
  - The R74 fusion-cell (R46+R62 at w_R46=0.25) is FROZEN; R76 does NOT touch it.
  - R76 result informs a future R77 candidate (R76 as fusion contribution) only
    if verdict is ✅ SURVIVES + ORTHOGONAL.
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
    DEFAULT_CADENCES, DEFAULT_COST_GRID,
    score_funding_zwide, R46_K,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.r73_pillar_a_level_ls import (
    pillar_a_level_ls, SIGN_HIGH_A_LONG, SIGN_LOW_A_LONG,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28,
    _build_r62_detector, R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    R62_FEATURE_SET, R62_Z, R62_MF,
)
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# R76-specific
R76_K_TERCILES = 3                    # R46 standard
R76_MIN_TRADEABLE = 12                # same floor as R73
R76_ORTHOGONALITY_GATE = 0.30         # lesson #42 — max |corr| vs existing legs

# Sign constants (mirror R73 convention)
SIGN_HIGH_FUND_LONG = "high_fund_long"   # long assets with above-mean funding (relatively long pressure)
SIGN_LOW_FUND_LONG = "low_fund_long"     # long assets with below-mean funding (relatively short pressure)
_VALID_SIGNS = {SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG}


# === Score: funding residual ==================================================
def score_funding_residual(funding_daily: pd.DataFrame, tradeable: list) -> pd.DataFrame:
    """Cross-sectionally demeaned funding: funding[t, a] − mean_a(funding[t, a]).

    Returns wide DataFrame (date × asset) on the tradeable subset.

    This is fundamentally different from `score_funding_zwide` (R62):
      - score_funding_zwide: per-asset z over time (relative to that asset's history)
      - score_funding_residual: per-time demean (relative to the universe at that t)

    These two normalizations are intentionally near-orthogonal: an asset's z-score
    captures its deviation from its OWN typical funding level; the residual captures
    its deviation from the universe's CURRENT typical funding level.
    """
    sub = funding_daily.reindex(columns=tradeable)
    residual = sub.subtract(sub.mean(axis=1), axis=0)
    return residual


# === L/S core (reuses R73's pillar_a_level_ls signature for parity) ==========
def funding_residual_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                        k_terciles: int = R76_K_TERCILES,
                        cost_bps: float = 0.0,
                        rebal_days: int = 1,
                        sign: str = SIGN_HIGH_FUND_LONG) -> pd.Series:
    """Long high-funding-residual / short low-funding-residual (or reversed under SIGN_LOW_FUND_LONG).

    Reuses R73's pillar_a_level_ls as the L/S engine — the score function differs
    (funding residual vs pillar_A level) but the L/S logic is the same: long top
    tercile, short bottom tercile, optional sign flip.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_FUND_LONG else score_wide
    return pillar_a_level_ls(flipped, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign=SIGN_HIGH_A_LONG)  # already flipped above


# === Leg-correlation pre-test gate (lesson #42 anti-imposter) ================
def leg_correlation_gate(leg_r76: pd.Series, leg_r46: pd.Series,
                         leg_r62: pd.Series, gate: float = R76_ORTHOGONALITY_GATE,
                         ) -> dict:
    """Measure |corr| of R76's leg vs R46/R62. Returns gate verdict.

    Lesson #42: if max |corr| > gate, flag as fusion-uncandidatable.
    """
    s_r76 = pd.Series(leg_r76.values).fillna(0.0)
    s_r46 = pd.Series(leg_r46.values).fillna(0.0)
    s_r62 = pd.Series(leg_r62.values).fillna(0.0)
    # Align
    s_r46_a = s_r46.reindex(s_r76.index).fillna(0.0)
    s_r62_a = s_r62.reindex(s_r76.index).fillna(0.0)
    corr_r46 = float(s_r76.corr(s_r46_a)) if s_r76.std() > 0 and s_r46_a.std() > 0 else float("nan")
    corr_r62 = float(s_r76.corr(s_r62_a)) if s_r76.std() > 0 and s_r62_a.std() > 0 else float("nan")
    finite_corrs = [abs(c) for c in (corr_r46, corr_r62) if not np.isnan(c)]
    max_abs_corr = max(finite_corrs) if finite_corrs else float("nan")
    passes_gate = max_abs_corr <= gate
    return {
        "corr_r76_vs_r46": corr_r46,
        "corr_r76_vs_r62": corr_r62,
        "max_abs_corr": max_abs_corr,
        "gate_threshold": gate,
        "passes_orthogonality_gate": passes_gate,
        "fusion_candidatable": passes_gate,
    }


# === Run =====================================================================
def run(out_dir: Path,
        cadences: tuple = DEFAULT_CADENCES,
        cost_grid: tuple = DEFAULT_COST_GRID,
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS,
        zwin: int = 30,
        sign: str = SIGN_HIGH_FUND_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R76 — Funding residual cross-sectional L/S (sign={sign}, k={R76_K_TERCILES}) ===\n")

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

    tradeable = funding_assets  # 28-asset strict intersection
    print(f"Strict intersection universe: {len(tradeable)} assets\n")
    if len(tradeable) < R76_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(tradeable)} < {R76_MIN_TRADEABLE} "
            f"(R76_MIN_TRADEABLE floor). R76 refuses to silently widen.")

    # ── Score: funding residual ───────────────────────────────────────────────
    print("Computing funding residual (cross-sectional demean) …")
    score_residual_wide = score_funding_residual(funding_daily, tradeable)
    score_residual_wide = score_residual_wide.reindex(rets.index).ffill()
    print(f"  Score shape: {score_residual_wide.shape}, "
          f"mean={score_residual_wide.mean().mean():.6f} (should be ~0 by construction), "
          f"std={score_residual_wide.std().mean():.6f}")

    # ── 6-window partition (R63 parity) ───────────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── Build R76 leg at best-cadence default (3d/0bps — mirrors R73 best cell) ─
    best_cad = 3
    leg_r76 = funding_residual_ls(score_residual_wide, rets[tradeable],
                                   k_terciles=R76_K_TERCILES, cost_bps=0.0,
                                   rebal_days=best_cad, sign=sign)
    leg_r76 = leg_r76.reindex(rets.index).fillna(0.0)

    # ── Reproduce R46 + R62 legs on the same panel (gate prerequisites) ──────
    print("Reproducing R46 leg (pillar_O 5d/5bps on 28-asset) for correlation gate …")
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets, tradeable)

    print("Reproducing R62 leg (fade-the-crowd 21d/0bps gated) for correlation gate …")
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                       sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis_long, rets, tradeable_full, tradeable,
                                       funding_daily)
    feats = feats.reindex(rets.index)
    # Use R63's _build_r62_detector (signature parity)
    ks = build_fragility_ks_table(feats, fragile_mask)
    external_cols = [c for c in feats.columns if c in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    det, _ = _build_r62_detector(feats, fragile_mask, fragile_ranges, playable_ranges) \
        if False else (None, None)
    # Build detector manually to avoid importing the private function (lesson: simpler)
    from src.research.validation.w5_forensics import build_w5_detector
    det, _ = build_w5_detector(
        feats,
        *fragile_ranges[0] if fragile_ranges else (feats.index[0], feats.index[0]),
        *playable_ranges[0] if playable_ranges else (feats.index[0], feats.index[0]),
        ks, feature_subset=external_cols,
        z_threshold=R62_Z, min_features=R62_MF,
    )
    leg_r62 = build_r62_sleeve_28(score_zwide, rets, tradeable, det)

    # ── Known factors + OOS cut (R63 parity) ─────────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── Leg-correlation gate (lesson #42 anti-imposter) ──────────────────────
    print("\n══ Leg-correlation gate (lesson #42, |corr| ≲ 0.30 vs R46/R62) ══\n")
    gate = leg_correlation_gate(leg_r76, leg_r46, leg_r62)
    print(f"corr(R76_leg, R46_leg) = {gate['corr_r76_vs_r46']:+.3f}")
    print(f"corr(R76_leg, R62_leg) = {gate['corr_r76_vs_r62']:+.3f}")
    print(f"max |corr| = {gate['max_abs_corr']:.3f}  "
          f"(gate ≤ {gate['gate_threshold']})")
    print(f"passes_orthogonality_gate: **{gate['passes_orthogonality_gate']}**")
    print(f"fusion_candidatable: **{gate['fusion_candidatable']}**\n")

    # ── Per-leg gauntlet ────────────────────────────────────────────────────
    g_r76 = gauntlet_3check(leg_r76.values, known_full, cut)
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    print(f"Leg R76 (3d/0bps): gross_t={g_r76['gross_t']:+.2f}, "
          f"OOS_t={g_r76['oos_t']:+.2f}, pass_all={g_r76['passes_all']}")
    print(f"Leg R46: gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}")
    print(f"Leg R62: gross_t={g_r62['gross_t']:+.2f}, OOS_t={g_r62['oos_t']:+.2f}\n")

    # ── Sweep cadences × costs (both signs; matched-cell sign verdict) ──────
    print(f"══ Cadence × cost sweep (signs: {SIGN_HIGH_FUND_LONG}, {SIGN_LOW_FUND_LONG}) ══\n")
    sweep_hi = {}
    sweep_lo = {}
    for cad in cadences:
        for bps in cost_grid:
            fac_hi = funding_residual_ls(score_residual_wide, rets[tradeable],
                                          k_terciles=R76_K_TERCILES, cost_bps=bps,
                                          rebal_days=cad, sign=SIGN_HIGH_FUND_LONG)
            fac_hi = fac_hi.reindex(rets.index).fillna(0.0)
            g_hi = gauntlet_3check(fac_hi.values, known_full, cut)
            sweep_hi[(cad, bps)] = {
                "alpha_t": g_hi["gross_t"], "oos_t": g_hi["oos_t"],
                "passes_gross": g_hi["passes_gross"], "passes_oos": g_hi["passes_oos"],
                "passes_all": g_hi["passes_all"],
            }
            fac_lo = funding_residual_ls(score_residual_wide, rets[tradeable],
                                          k_terciles=R76_K_TERCILES, cost_bps=bps,
                                          rebal_days=cad, sign=SIGN_LOW_FUND_LONG)
            fac_lo = fac_lo.reindex(rets.index).fillna(0.0)
            g_lo = gauntlet_3check(fac_lo.values, known_full, cut)
            sweep_lo[(cad, bps)] = {
                "alpha_t": g_lo["gross_t"], "oos_t": g_lo["oos_t"],
                "passes_gross": g_lo["passes_gross"], "passes_oos": g_lo["passes_oos"],
                "passes_all": g_lo["passes_all"],
            }

    # ── Matched-cell sign audit (anti-imposter) ──────────────────────────────
    print("Matched-cell sign audit (high_fund_long vs low_fund_long at same cad×bps):")
    matched_diffs = []
    for cad in cadences:
        for bps in cost_grid:
            hi_entry = sweep_hi[(cad, bps)]
            lo_entry = sweep_lo[(cad, bps)]
            diff = hi_entry["alpha_t"] - lo_entry["alpha_t"]
            matched_diffs.append((cad, bps, hi_entry["alpha_t"], lo_entry["alpha_t"], diff))
    matched_diffs.sort(key=lambda x: x[4], reverse=True)
    print(f"  Top-3 matched cells by directional differential (high − low):")
    for cad, bps, hi_t, lo_t, diff in matched_diffs[:3]:
        print(f"    {cad}d/{bps}bps: high_fund={hi_t:+.2f}, low_fund={lo_t:+.2f}, "
              f"diff={diff:+.2f}")
    best_diff_cad, best_diff_bps, _, _, best_diff = matched_diffs[0]
    sign_verdict = "high_fund_long" if best_diff > 0 else "low_fund_long"
    print(f"  Sign verdict: {sign_verdict} (matched-cell diff = {best_diff:+.2f})\n")

    # ── Best cell selection ─────────────────────────────────────────────────
    # Pick best cell by gross_t, restricted to the sign-verdict direction.
    chosen_sign = sign_verdict
    chosen_sweep = sweep_hi if chosen_sign == SIGN_HIGH_FUND_LONG else sweep_lo
    best_cell = max(chosen_sweep.items(),
                    key=lambda kv: (kv[1]["alpha_t"], kv[1]["oos_t"]))
    (best_cad_final, best_bps_final), best_metrics = best_cell
    print(f"Best cell: {best_cad_final}d/{best_bps_final}bps, sign={chosen_sign}")
    print(f"  gross_t = {best_metrics['alpha_t']:+.2f}, "
          f"OOS_t = {best_metrics['oos_t']:+.2f}, "
          f"passes_all = {best_metrics['passes_all']}\n")

    # ── Final verdict (3-way) ────────────────────────────────────────────────
    passes_gauntlet = best_metrics["passes_all"]
    if passes_gauntlet and gate["fusion_candidatable"]:
        verdict = "✅ SURVIVES + ORTHOGONAL — eligible for R77 fusion candidate"
        verdict_band = "SURVIVES_ORTHOGONAL"
    elif passes_gauntlet and not gate["fusion_candidatable"]:
        verdict = ("🟡 SURVIVES + CORRELATED — standalone-eligible but "
                   "NOT fusion-uncandidatable (R73 pattern)")
        verdict_band = "SURVIVES_CORRELATED"
    else:
        verdict = ("🔴 REFUTED — orthogonal funding-residual candidate does NOT "
                   "clear 3-check. Lesson #42 sharpens: orthogonal candidates may "
                   "not have any standalone edge either; R46+R62 fusion may be "
                   "near-optimal for this data.")
        verdict_band = "REFUTED"

    print(f"Verdict: {verdict}\n")

    # ── Per-window attribution at best cell ─────────────────────────────────
    fac_best = funding_residual_ls(score_residual_wide, rets[tradeable],
                                    k_terciles=R76_K_TERCILES, cost_bps=best_bps_final,
                                    rebal_days=best_cad_final, sign=chosen_sign)
    fac_best = fac_best.reindex(rets.index).fillna(0.0)
    from src.research.validation.r63_fusion_validation import per_window
    pw_best = per_window(fac_best, windows)
    print("Per-window W1-W6 ann% at best cell:")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in pw_best:
            print(f"  {label}: {pw_best[label]['ann_pct']:+.1f}%  "
                  f"(n={pw_best[label]['n_days']})")
    print()

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable)},
        "construction": {
            "score": "funding_residual = funding[t, a] - mean_a(funding[t, a])",
            "k_terciles": R76_K_TERCILES, "min_tradeable": R76_MIN_TRADEABLE,
            "orthogonality_gate": R76_ORTHOGONALITY_GATE,
            "universe": "28-asset strict funding ∩ CIS ∩ OHLCV",
            "cadences": list(cadences), "cost_grid": list(cost_grid),
        },
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                      "n_days": int((e - s).days + 1),
                      "fragile": lab in fragile_labels} for lab, s, e in windows],
        "leg_correlation_gate": gate,
        "best_cell": {
            "cadence": best_cad_final, "cost_bps": best_bps_final,
            "sign": chosen_sign,
            "gauntlet": best_metrics,
            "per_window": pw_best,
        },
        "matched_cell_sign_audit": {
            "top3": [{"cadence": c, "cost_bps": b, "high_fund_long_t": h,
                       "low_fund_long_t": l, "differential": d}
                      for c, b, h, l, d in matched_diffs[:3]],
            "sign_verdict": sign_verdict,
            "differential": best_diff,
        },
        "per_leg_gauntlet": {
            "r76_3d_0bps": g_r76,
            "r46": g_r46,
            "r62": g_r62,
        },
        "sweep_high_sign": {f"{c}d/{b}bps": v for (c, b), v in sweep_hi.items()},
        "sweep_low_sign": {f"{c}d/{b}bps": v for (c, b), v in sweep_lo.items()},
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_gauntlet": passes_gauntlet,
            "passes_orthogonality_gate": gate["passes_orthogonality_gate"],
        },
        "live_book_impact": {
            "touches_frozen_r69_cell": False,
            "note": ("R76 is research-only. R77 fusion candidate MAY be built only "
                     "if verdict is SURVIVES_ORTHOGONAL."),
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable R76 report."""
    lines = []
    lines.append("# R76 — Funding residual cross-sectional L/S")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_assets_intersection']}-asset strict universe)")
    lines.append("")
    lines.append("## Verdict")
    v = payload["verdict"]
    lines.append(f"**{v['band']}** — {v['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes gauntlet: **{v['passes_gauntlet']}**")
    lines.append(f"- Passes orthogonality gate (|corr| ≲ {payload['construction']['orthogonality_gate']}): "
                 f"**{v['passes_orthogonality_gate']}**")
    lines.append("")
    lines.append("## Leg-correlation gate (lesson #42)")
    g = payload["leg_correlation_gate"]
    lines.append(f"- corr(R76_leg, R46_leg) = {g['corr_r76_vs_r46']:+.3f}")
    lines.append(f"- corr(R76_leg, R62_leg) = {g['corr_r76_vs_r62']:+.3f}")
    lines.append(f"- max |corr| = {g['max_abs_corr']:.3f} (gate ≤ {g['gate_threshold']})")
    lines.append(f"- fusion_candidatable = **{g['fusion_candidatable']}**")
    lines.append("")
    lines.append("## Best cell (after matched-cell sign audit)")
    b = payload["best_cell"]
    bg = b["gauntlet"]
    lines.append(f"- {b['cadence']}d/{b['cost_bps']}bps, sign={b['sign']}")
    lines.append(f"- gross_t = {bg['alpha_t']:+.2f}, "
                 f"OOS_t = {bg['oos_t']:+.2f}, "
                 f"passes_all = {bg['passes_all']}")
    lines.append("")
    lines.append("## Matched-cell sign audit (top-3)")
    for entry in payload["matched_cell_sign_audit"]["top3"]:
        lines.append(f"- {entry['cadence']}d/{entry['cost_bps']}bps: "
                     f"high={entry['high_fund_long_t']:+.2f}, "
                     f"low={entry['low_fund_long_t']:+.2f}, "
                     f"diff={entry['differential']:+.2f}")
    lines.append(f"- **Sign verdict: {payload['matched_cell_sign_audit']['sign_verdict']}** "
                 f"(matched-cell diff = {payload['matched_cell_sign_audit']['differential']:+.2f})")
    lines.append("")
    lines.append("## Per-window W1-W6 ann% at best cell")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in b["per_window"]:
            pw = b["per_window"][label]
            lines.append(f"- {label}: {pw['ann_pct']:+.1f}%  "
                         f"(n={pw['n_days']}, maxDD={pw['max_dd']:+.2%})")
    lines.append("")
    lines.append("## Per-leg gauntlet")
    for leg in ("r76_3d_0bps", "r46", "r62"):
        g_leg = payload["per_leg_gauntlet"][leg]
        lines.append(f"- **{leg}**: gross_t = {g_leg['gross_t']:+.2f}, "
                     f"OOS_t = {g_leg['oos_t']:+.2f}, "
                     f"passes_all = {g_leg['passes_all']}")
    lines.append("")
    lines.append("## Live book impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R69 cell: **{li['touches_frozen_r69_cell']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    lines.append("## Aggregate lesson #43 (proposed, depends on verdict)")
    if v["band"] == "SURVIVES_ORTHOGONAL":
        lines.append("- ✅ Aggregate lesson #43: \"Orthogonal signal sources carry real "
                     "cross-sectional edges that survive the 3-check gauntlet AND are "
                     "uncorrelated with existing fusion legs. Lesson #42 holds: "
                     "leg-correlation gate is necessary; orthogonal candidates are the "
                     "right next R-number. Funding residual = cross-sectional demean "
                     "funding is a viable R77 fusion-contribution candidate.\"")
    elif v["band"] == "SURVIVES_CORRELATED":
        lines.append("- 🟡 Aggregate lesson #43 (partial): \"Standalone edge exists but "
                     "leg-correlation is structural; orthogonal candidates must be "
                     "screened for |corr| ≲ 0.30 BEFORE testing standalone. Funding "
                     "residual is correlated with R46/R62 even though it's a different "
                     "signal source — the universe's funding pressures co-move with "
                     "CIS-quality.\"")
    else:
        lines.append("- 🔴 Aggregate lesson #43 (sharpens #42): \"Residual funding signal "
                     "may not have any standalone edge after residualization. R46+R62 "
                     "fusion may be near-optimal for this data; future R-numbers need "
                     "to look at structurally different sources (cross-asset carry, "
                     "microstructure volatility, regime-conditional overlays).\"")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_HIGH_FUND_LONG,
                        choices=[SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r76_funding_residual_ls/{today}")
    payload = run(out, sign=args.sign)

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
