"""
R78 — Relative momentum (TSMOM cross-sectional demean) as orthogonal candidate #2 (Seth, 2026-07-23).

Per R76 lesson #43 (CONFIRMED 2026-07-23 via R77): orthogonal signal sources DO
carry as 3rd fusion contribution to the R46+R62 fusion book. R76 (funding residual)
was orthogonal candidate #1; R77 confirmed it lifts the fusion (best w_R76=0.30,
ΔOOS_t=+1.17).

R78 opens orthogonal candidate #2: **relative momentum** = TSMOM[t, a] −
mean_a(TSMOM[t, a]) (cross-sectional demean of TSMOM). TSMOM is the trailing-30
sign of each asset's own returns; the cross-sectional demean removes the universe's
common trend component and leaves *relative trend strength*. This is structurally
different from R46 (CIS-quality multi-pillar rank), R62 (absolute funding-z
crowding), and R76 (funding residual — relative funding pressure).

R78 design (parallels R76):
  · Universe: same 28-asset strict funding ∩ CIS ∩ OHLCV (R46/R62/R73/R74/R76/R77 parity).
  · Score: TSMOM[t, a] − mean_a(TSMOM[t, a]) — cross-sectional demean of TSMOM sign.
  · k_terciles = 3 (R46 standard).
  · Cadences {1,3,5,7,14,21}d × costs {0,5,10}bps.
  · 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  · Per-window W1-W6 attribution.
  · **Pre-test leg-correlation gate (lesson #42 anti-imposter)** — extended to
    test vs R46 + R62 + R76 (the 3 existing fusion legs). If max |corr| > 0.30,
    flag as fusion-uncandidatable (R74 mistake).
  · Both signs run; matched-cell sign verdict.

Verdict grammar:
  · ✅ SURVIVES + ORTHOGONAL — clears 3-check AND max |corr| ≤ 0.30 vs R46/R62/R76.
    Eligible for fusion contribution (R79 candidate material).
  · 🟡 SURVIVES + CORRELATED — clears 3-check BUT correlated (|corr| > 0.30) with
    existing legs → standalone-eligible but NOT fusion-candidatable.
  · 🔴 REFUTED — fails 3-check. Lesson #43 sharpens: orthogonal candidates may
    not have any standalone edge after residualization; the fusion book may be
    near-optimal for this data on this universe.

Anti-imposter:
  - Relative momentum is NOT the same as R46's CIS-quality (multi-pillar rank) nor
    R76's funding residual. TSMOM demean captures relative trend direction within
    the universe; CIS-quality captures multi-pillar aggregate; funding residual
    captures relative funding pressure.
  - Pre-test leg-correlation gate is MANDATORY (lesson #42). Don't run the fusion
    sweep until the gate clears.
  - The R77 fusion-cell (R46+R62+R76 at w_R46=0.25, w_R62=0.75, w_R76=0.30) is
    FROZEN. R78 does NOT touch it.
  - R78 result informs a future R79 candidate (R78 as 4th fusion contribution)
    only if verdict is ✅ SURVIVES + ORTHOGONAL.
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
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    R62_FEATURE_SET, R62_Z, R62_MF,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# R78-specific
R78_K_TERCILES = 3                    # R46 standard
R78_MIN_TRADEABLE = 12                # same floor as R73/R76
R78_ORTHOGONALITY_GATE = 0.30         # lesson #42 — max |corr| vs existing legs
R78_TSMOM_LOOKBACK = 30               # days; R46's market residual uses 30

# Sign constants (mirror R73/R76 convention)
SIGN_HIGH_MOM_LONG = "high_mom_long"   # long assets with above-mean TSMOM (relatively stronger trend)
SIGN_LOW_MOM_LONG = "low_mom_long"     # long assets with below-mean TSMOM (relatively weaker trend = mean-reversion)
_VALID_SIGNS = {SIGN_HIGH_MOM_LONG, SIGN_LOW_MOM_LONG}


# === Score: relative momentum =================================================
def score_relative_momentum(rets: pd.DataFrame, tradeable: list,
                             lookback: int = R78_TSMOM_LOOKBACK) -> pd.DataFrame:
    """Cross-sectionally demeaned TSMOM: TSMOM[t, a] − mean_a(TSMOM[t, a]).

    TSMOM[t, a] = sign of trailing-lookback return for asset a at time t:
        cum_a[t] / cum_a[t - lookback] - 1, then sign.

    Cross-sectional demean at each t removes the universe's common trend
    component; the residual is RELATIVE trend strength (which assets are
    trending harder than the universe on this date).

    Returns wide DataFrame (date × asset) on the tradeable subset.
    """
    sub = rets[tradeable].copy()
    # Per-asset cumulative return
    cum = (1 + sub.fillna(0.0)).cumprod()
    trail = cum / cum.shift(lookback) - 1
    # TSMOM sign per asset (uses t-1 to avoid look-ahead in score construction;
    # the L/S engine applies its own look-ahead convention via rebalance lag).
    # Keep NaN warmup rows so the cross-sectional demean is computed on
    # fully-observed rows only (otherwise NaN→0 in early rows pollutes demean).
    tsmom = np.sign(trail.shift(1))
    # Cross-sectional demean at each t — only on fully-observed rows
    fully_observed = tsmom.dropna(how="any")
    demeaned_full = fully_observed.subtract(fully_observed.mean(axis=1), axis=0)
    # Reindex back to original index; warmup rows are NaN (filled later at L/S)
    residual = demeaned_full.reindex(tsmom.index)
    return residual


# === L/S core (reuses R73's pillar_a_level_ls signature for parity) ==========
def relative_momentum_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                          k_terciles: int = R78_K_TERCILES,
                          cost_bps: float = 0.0,
                          rebal_days: int = 1,
                          sign: str = SIGN_HIGH_MOM_LONG) -> pd.Series:
    """Long high-relative-momentum / short low-relative-momentum (or reversed under SIGN_LOW_MOM_LONG).

    Reuses R73's pillar_a_level_ls as the L/S engine — the score function differs
    (relative momentum vs pillar_A level) but the L/S logic is the same: long
    top tercile, short bottom tercile, optional sign flip.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_MOM_LONG else score_wide
    return pillar_a_level_ls(flipped, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign=SIGN_HIGH_A_LONG)  # already flipped above


# === Leg-correlation pre-test gate (lesson #42 anti-imposter) ================
def leg_correlation_gate_n(leg_new: pd.Series, existing_legs: dict,
                            gate: float = R78_ORTHOGONALITY_GATE) -> dict:
    """Measure |corr| of new candidate vs each existing fusion leg. Returns gate verdict.

    Args:
        leg_new: candidate sleeve returns (e.g., R78)
        existing_legs: dict {name: pd.Series} of existing fusion legs
                       (e.g., {"r46": leg_r46, "r62": leg_r62, "r76": leg_r76})
        gate: max |corr| threshold (lesson #42)

    Returns dict with per-leg correlations + max |corr| + passes_gate + fusion_candidatable.
    """
    s_new = pd.Series(leg_new.values).fillna(0.0)
    corrs = {}
    finite_corrs = []
    for name, leg in existing_legs.items():
        s_leg = pd.Series(leg.values).fillna(0.0).reindex(s_new.index).fillna(0.0)
        if s_new.std() > 0 and s_leg.std() > 0:
            c = float(s_new.corr(s_leg))
        else:
            c = float("nan")
        corrs[f"corr_new_vs_{name}"] = c
        if not np.isnan(c):
            finite_corrs.append(abs(c))
    max_abs_corr = max(finite_corrs) if finite_corrs else float("nan")
    passes_gate = max_abs_corr <= gate
    return {
        **corrs,
        "max_abs_corr": max_abs_corr,
        "gate_threshold": gate,
        "n_existing_legs": len(existing_legs),
        "passes_orthogonality_gate": passes_gate,
        "fusion_candidatable": passes_gate,
    }


# === R62 detector reproduction (lifted from R77) =============================
def _build_r62_detector_local(features: pd.DataFrame, fragile_mask: pd.Series,
                              fragile_ranges: list, playable_ranges: list):
    """Reproduce R62 best-cell detector on the R78 panel."""
    from src.research.validation.w5_forensics import build_w5_detector
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


# === Run =====================================================================
def run(out_dir: Path,
        cadences: tuple = DEFAULT_CADENCES,
        cost_grid: tuple = DEFAULT_COST_GRID,
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS,
        zwin: int = 30,
        sign: str = SIGN_HIGH_MOM_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R78 — Relative momentum (TSMOM demean) cross-sectional L/S "
          f"(sign={sign}, k={R78_K_TERCILES}) ===\n")

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

    tradeable = funding_assets  # 28-asset STRICT intersection (do not silently widen)
    print(f"Strict intersection universe: {len(tradeable)} assets")
    if len(tradeable) < R78_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(tradeable)} < {R78_MIN_TRADEABLE} "
            f"(R78_MIN_TRADEABLE floor). R78 refuses to silently widen.")

    # ── Score: relative momentum ──────────────────────────────────────────────
    print("Computing relative momentum (TSMOM cross-sectional demean) …")
    score_relmom_wide = score_relative_momentum(rets, tradeable)
    score_relmom_wide = score_relmom_wide.reindex(rets.index).ffill()
    print(f"  Score shape: {score_relmom_wide.shape}, "
          f"mean={score_relmom_wide.mean().mean():.6f} (should be ~0 by construction), "
          f"std={score_relmom_wide.std().mean():.6f}")

    # ── 6-window partition (R63 parity) ───────────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── Build R78 leg at default cadence (3d/0bps — mirrors R73/R76 best cell) ─
    best_cad = 3
    leg_r78 = relative_momentum_ls(score_relmom_wide, rets[tradeable],
                                    k_terciles=R78_K_TERCILES, cost_bps=0.0,
                                    rebal_days=best_cad, sign=sign)
    leg_r78 = leg_r78.reindex(rets.index).fillna(0.0)

    # ── Reproduce R46 + R62 legs on the same panel (gate prerequisites) ──────
    print("\nReproducing R46 leg (pillar_O 5d/5bps on 28-asset) for correlation gate …")
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets, tradeable)

    print("Reproducing R62 leg (fade-the-crowd 21d/0bps gated) for correlation gate …")
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                       sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis_long, rets, tradeable_full, tradeable,
                                       funding_daily)
    feats = feats.reindex(rets.index)
    det = _build_r62_detector_local(feats, fragile_mask, fragile_ranges, playable_ranges)
    leg_r62 = build_r62_sleeve_28(score_zwide, rets, tradeable, det)

    # ── Reproduce R76 leg (funding residual 5d/0bps) for correlation gate ─────
    print("Reproducing R76 leg (funding residual 5d/0bps) for correlation gate …")
    from src.research.validation.r76_funding_residual_ls import (
        score_funding_residual, funding_residual_ls as r76_ls,
        SIGN_HIGH_FUND_LONG,
    )
    score_fundres_wide = score_funding_residual(funding_daily, tradeable) \
                                          .reindex(rets.index).ffill()
    leg_r76 = r76_ls(score_fundres_wide, rets[tradeable],
                      k_terciles=R78_K_TERCILES, cost_bps=0.0,
                      rebal_days=5, sign=SIGN_HIGH_FUND_LONG)
    leg_r76 = leg_r76.reindex(rets.index).fillna(0.0)

    # ── Known factors + OOS cut (R63 parity) ─────────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── Leg-correlation gate (lesson #42 anti-imposter) — extended to 3 legs ─
    print("\n══ Leg-correlation gate (lesson #42, |corr| ≲ 0.30 vs R46/R62/R76) ══\n")
    existing_legs = {"r46": leg_r46, "r62": leg_r62, "r76": leg_r76}
    gate = leg_correlation_gate_n(leg_r78, existing_legs)
    print(f"corr(R78_leg, R46_leg) = {gate['corr_new_vs_r46']:+.3f}")
    print(f"corr(R78_leg, R62_leg) = {gate['corr_new_vs_r62']:+.3f}")
    print(f"corr(R78_leg, R76_leg) = {gate['corr_new_vs_r76']:+.3f}")
    print(f"max |corr| = {gate['max_abs_corr']:.3f}  "
          f"(gate ≤ {gate['gate_threshold']})")
    print(f"passes_orthogonality_gate: **{gate['passes_orthogonality_gate']}**")
    print(f"fusion_candidatable: **{gate['fusion_candidatable']}**\n")

    # ── Per-leg gauntlet ────────────────────────────────────────────────────
    g_r78 = gauntlet_3check(leg_r78.values, known_full, cut)
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    g_r76 = gauntlet_3check(leg_r76.values, known_full, cut)
    print(f"Leg R78 ({best_cad}d/0bps): gross_t={g_r78['gross_t']:+.2f}, "
          f"OOS_t={g_r78['oos_t']:+.2f}, pass_all={g_r78['passes_all']}")
    print(f"Leg R46: gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}")
    print(f"Leg R62: gross_t={g_r62['gross_t']:+.2f}, OOS_t={g_r62['oos_t']:+.2f}")
    print(f"Leg R76: gross_t={g_r76['gross_t']:+.2f}, OOS_t={g_r76['oos_t']:+.2f}\n")

    # ── Sweep cadences × costs (both signs; matched-cell sign verdict) ──────
    print(f"══ Cadence × cost sweep (signs: {SIGN_HIGH_MOM_LONG}, {SIGN_LOW_MOM_LONG}) ══\n")
    sweep_hi = {}
    sweep_lo = {}
    for cad in cadences:
        for bps in cost_grid:
            fac_hi = relative_momentum_ls(score_relmom_wide, rets[tradeable],
                                            k_terciles=R78_K_TERCILES, cost_bps=bps,
                                            rebal_days=cad, sign=SIGN_HIGH_MOM_LONG)
            fac_hi = fac_hi.reindex(rets.index).fillna(0.0)
            g_hi = gauntlet_3check(fac_hi.values, known_full, cut)
            sweep_hi[(cad, bps)] = {
                "alpha_t": g_hi["gross_t"], "oos_t": g_hi["oos_t"],
                "passes_gross": g_hi["passes_gross"], "passes_oos": g_hi["passes_oos"],
                "passes_all": g_hi["passes_all"],
            }
            fac_lo = relative_momentum_ls(score_relmom_wide, rets[tradeable],
                                            k_terciles=R78_K_TERCILES, cost_bps=bps,
                                            rebal_days=cad, sign=SIGN_LOW_MOM_LONG)
            fac_lo = fac_lo.reindex(rets.index).fillna(0.0)
            g_lo = gauntlet_3check(fac_lo.values, known_full, cut)
            sweep_lo[(cad, bps)] = {
                "alpha_t": g_lo["gross_t"], "oos_t": g_lo["oos_t"],
                "passes_gross": g_lo["passes_gross"], "passes_oos": g_lo["passes_oos"],
                "passes_all": g_lo["passes_all"],
            }

    # ── Matched-cell sign audit (anti-imposter) ──────────────────────────────
    print("══ Matched-cell sign audit (anti-imposter) ══\n")
    matched_diffs = []
    for cad in cadences:
        for bps in cost_grid:
            hi_entry = sweep_hi[(cad, bps)]
            lo_entry = sweep_lo[(cad, bps)]
            diff = hi_entry["alpha_t"] - lo_entry["alpha_t"]
            matched_diffs.append((cad, bps, diff, hi_entry["alpha_t"], lo_entry["alpha_t"]))
    matched_diffs.sort(key=lambda x: -x[2])
    print("Top-3 matched-cell differentials (sign audit):")
    for cad, bps, diff, hi_t, lo_t in matched_diffs[:3]:
        print(f"  cad={cad:>2}d bps={bps:>4.1f}: Δ(α_t) = {diff:+.2f} "
              f"(hi={hi_t:+.2f}, lo={lo_t:+.2f})")
    # Sign verdict: if all top-3 are positive, high_mom_long wins; if all negative, low wins
    pos_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff > 0)
    neg_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff < 0)
    sign_verdict = "high_mom_long" if pos_count >= 2 else ("low_mom_long" if neg_count >= 2 else "mixed")
    print(f"Sign verdict (top-3 majority): **{sign_verdict}**\n")

    # ── Sweep summary: best cell by pass + alpha + OOS ───────────────────────
    print("══ Sweep summary (best cell per sign) ══\n")
    viable_hi = [(k, v) for k, v in sweep_hi.items() if v["passes_all"]]
    viable_lo = [(k, v) for k, v in sweep_lo.items() if v["passes_all"]]
    best_hi = max(viable_hi, key=lambda kv: kv[1]["alpha_t"]) if viable_hi else (None, None)
    best_lo = max(viable_lo, key=lambda kv: kv[1]["alpha_t"]) if viable_lo else (None, None)
    if best_hi[0]:
        cad, bps = best_hi[0]
        v = best_hi[1]
        print(f"Best SIGN_HIGH_MOM_LONG cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if best_lo[0]:
        cad, bps = best_lo[0]
        v = best_lo[1]
        print(f"Best SIGN_LOW_MOM_LONG  cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if not viable_hi and not viable_lo:
        print("⚠ NO cell passes 3-check — R78 likely REFUTED.\n")
    else:
        print()

    # ── Final verdict ────────────────────────────────────────────────────────
    passes_3check = g_r78["passes_all"]
    orthogonal = gate["passes_orthogonality_gate"]
    if passes_3check and orthogonal:
        verdict = "✅ SURVIVES + ORTHOGONAL — R78 (relative momentum) eligible as fusion contribution"
        verdict_band = "SURVIVES_ORTHOGONAL"
    elif passes_3check and not orthogonal:
        verdict = ("🟡 SURVIVES + CORRELATED — clears 3-check but leg-correlated; "
                   "standalone-eligible, NOT fusion-candidatable")
        verdict_band = "SURVIVES_CORRELATED"
    else:
        verdict = ("🔴 REFUTED — fails 3-check; lesson #43 sharpens: orthogonal candidates "
                   "may not have any standalone edge on this data")
        verdict_band = "REFUTED"
    print(f"VERDICT: {verdict}\n")

    # ── Per-window W1-W6 attribution (best cell if exists) ───────────────────
    from src.research.validation.r63_fusion_validation import per_window, max_drawdown
    dd_r78 = max_drawdown(leg_r78)
    pw_r78 = per_window(leg_r78, windows)
    print(f"R78 maxDD: {dd_r78:+.2%}")
    print(f"R78 per-window (best-cad {best_cad}d/0bps, sign={sign}):")
    for label_, ann_pct, n in [(lab, pw_r78[lab]["ann_pct"], pw_r78[lab]["n_days"]) for lab in sorted(pw_r78.keys())]:
        print(f"  {label_}: {ann_pct:+.1f}% (n={n})")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable),
                  "matched_assets": tradeable},
        "construction": {
            "score_basis": "relative_momentum (TSMOM cross-sectional demean)",
            "tsmom_lookback": R78_TSMOM_LOOKBACK,
            "k_terciles": R78_K_TERCILES,
            "universe": "28-asset funding-bearing intersection",
            "cadences": list(cadences), "cost_grid": list(cost_grid),
            "default_cad": best_cad, "default_cost_bps": 0.0,
            "sign": sign,
        },
        "leg_correlation_gate": gate,
        "per_leg_gauntlet": {
            "leg_r78": {"gauntlet": g_r78, "default_cad": best_cad, "default_cost_bps": 0.0,
                        "max_dd": dd_r78, "per_window": pw_r78},
            "leg_r46": {"gauntlet": g_r46, "cad": R46_CAD, "cost_bps": R46_BPS},
            "leg_r62": {"gauntlet": g_r62, "cad": R62_CAD, "cost_bps": R62_BPS,
                        "feature_set": R62_FEATURE_SET, "z_threshold": R62_Z,
                        "min_features": R62_MF, "zwin": zwin},
            "leg_r76": {"gauntlet": g_r76, "cad": 5, "cost_bps": 0.0,
                        "score_basis": "funding_residual"},
        },
        "sweep_high": {f"{k[0]}d_{k[1]}bps": v for k, v in sweep_hi.items()},
        "sweep_low": {f"{k[0]}d_{k[1]}bps": v for k, v in sweep_lo.items()},
        "matched_cell_sign_audit": {
            "top_3": [{"cad": c, "bps": b, "diff": d, "hi_alpha_t": h, "lo_alpha_t": l}
                       for c, b, d, h, l in matched_diffs[:3]],
            "sign_verdict": sign_verdict,
        },
        "best_cells": {
            "sign_high_mom_long": ({"cad": best_hi[0][0], "cost_bps": best_hi[0][1],
                                     "alpha_t": best_hi[1]["alpha_t"],
                                     "oos_t": best_hi[1]["oos_t"]}
                                    if best_hi[0] else None),
            "sign_low_mom_long": ({"cad": best_lo[0][0], "cost_bps": best_lo[0][1],
                                    "alpha_t": best_lo[1]["alpha_t"],
                                    "oos_t": best_lo[1]["oos_t"]}
                                   if best_lo[0] else None),
        },
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_3check": passes_3check,
            "orthogonal_to_existing_legs": orthogonal,
            "max_abs_corr_vs_existing": gate["max_abs_corr"],
        },
        "live_book_impact": {
            "touches_frozen_r77_cell": False,
            "r65_paper_book_unaffected": True,
            "r66_tracking_unaffected": True,
            "note": "R78 is research-only. R79 = R78 as 4th fusion contribution is the "
                    "next step IF verdict is SURVIVES_ORTHOGONAL.",
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable R78 report."""
    lines = []
    lines.append("# R78 — Relative momentum (TSMOM demean) cross-sectional L/S")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_assets_intersection']}-asset strict universe)")
    lines.append("")
    lines.append("## Verdict")
    v = payload["verdict"]
    lines.append(f"**{v['band']}** — {v['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes 3-check: **{v['passes_3check']}**")
    lines.append(f"- Orthogonal to existing legs (R46/R62/R76): "
                 f"**{v['orthogonal_to_existing_legs']}**")
    lines.append(f"- Max |corr| vs existing legs: {v['max_abs_corr_vs_existing']:.3f}")
    lines.append("")
    lines.append("## Leg-correlation gate (lesson #42, extended to 3 existing legs)")
    g = payload["leg_correlation_gate"]
    lines.append(f"- corr(R78, R46) = {g['corr_new_vs_r46']:+.3f}")
    lines.append(f"- corr(R78, R62) = {g['corr_new_vs_r62']:+.3f}")
    lines.append(f"- corr(R78, R76) = {g['corr_new_vs_r76']:+.3f}")
    lines.append(f"- max |corr| = {g['max_abs_corr']:.3f} (gate ≤ {g['gate_threshold']})")
    lines.append(f"- passes_orthogonality_gate = **{g['passes_orthogonality_gate']}**")
    lines.append("")
    lines.append("## Per-leg gauntlet (on 28-asset)")
    for leg in ("leg_r78", "leg_r46", "leg_r62", "leg_r76"):
        gp = payload["per_leg_gauntlet"][leg]["gauntlet"]
        lines.append(f"- **{leg}**: gross_t = {gp['gross_t']:+.2f}, "
                     f"OOS_t = {gp['oos_t']:+.2f}, pass_all = {gp['passes_all']}")
    lines.append("")
    lines.append("## Matched-cell sign audit (top-3)")
    lines.append("| cad | bps | Δ(α_t) | hi (long) | lo (short) |")
    lines.append("|---:|---:|---:|---:|---:|")
    for r in payload["matched_cell_sign_audit"]["top_3"]:
        lines.append(f"| {r['cad']} | {r['bps']} | {r['diff']:+.2f} | "
                     f"{r['hi_alpha_t']:+.2f} | {r['lo_alpha_t']:+.2f} |")
    lines.append(f"\n**Sign verdict:** `{payload['matched_cell_sign_audit']['sign_verdict']}`\n")
    lines.append("## Live book impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R77 cell: **{li['touches_frozen_r77_cell']}**")
    lines.append(f"- R65 paper book unaffected: **{li['r65_paper_book_unaffected']}**")
    lines.append(f"- R66 tracking unaffected: **{li['r66_tracking_unaffected']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    lines.append("## Aggregate lesson (proposed, depends on verdict)")
    if v["band"] == "SURVIVES_ORTHOGONAL":
        lines.append("- ✅ Lesson #43 confirmed for orthogonal candidate #2: \"Relative "
                     "momentum (TSMOM cross-sectional demean) is structurally orthogonal to "
                     "R46 (CIS-quality), R62 (crowding-z), and R76 (funding residual). The "
                     "cross-sectional demean removes the universe's common trend component, "
                     "leaving RELATIVE trend strength — a fundamentally different signal axis. "
                     "R79 = R78 as 4th fusion contribution is the natural next step.\"")
    elif v["band"] == "SURVIVES_CORRELATED":
        lines.append("- 🟡 Lesson #43 sharpens: \"Standalone edge exists but R78 correlates "
                     "with one of the existing fusion legs — likely R46 (momentum factor "
                     "overlap). Orthogonal candidate screening must catch this BEFORE "
                     "gauntlet testing, not after. R79 not warranted as fusion contribution.\"")
    else:
        lines.append("- 🔴 Lesson #43 sharpens: \"Orthogonal candidate #2 fails 3-check on "
                     "this data. R46+R62+R76 fusion may be near-optimal for this universe; "
                     "future R-numbers need to look at even more structurally different "
                     "sources (cross-asset carry, microstructure volatility, regime-conditional "
                     "overlays).\"")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_HIGH_MOM_LONG,
                        choices=[SIGN_HIGH_MOM_LONG, SIGN_LOW_MOM_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r78_relative_momentum_residual/{today}")
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