"""
S-78 — Realized vol residual (cross-sectional demean of trailing-30d σ) as orthogonal candidate #3
(Seth, 2026-07-23). Replaces "R79 candidate" under the new lane-prefix convention.

Per R76/R77 lesson #43 (CONFIRMED 2026-07-23 via R77): orthogonal signal sources DO
carry as 3rd fusion contribution to the R46+R62 fusion book. R76 (funding residual,
orthogonal #1) was confirmed via R77; R78 (relative momentum, orthogonal #2) was
REFUTED — gate passes, gauntlet fails. The pattern: gate is necessary but not
sufficient (lesson #43 v2 sharpens). S-78 must clear BOTH.

S-78 opens orthogonal candidate #3: **realized vol residual** = σ_30[t, a] −
mean_a(σ_30[t, a]), where σ_30 is the trailing-30d std of returns. Cross-sectional
demean removes the universe's common vol regime component and leaves RELATIVE
volatility (which assets are running hotter than the universe on this date).
This is structurally different from R46 (CIS-quality multi-pillar rank), R62
(absolute funding-z crowding), R76 (funding residual), R78 (TSMOM relative
trend). Vol is a microstructure axis, not a price/funding axis.

S-78 design (parallels R76/R78):
  · Universe: same 28-asset strict funding ∩ CIS ∩ OHLCV.
  · Score: σ_30[t, a] − mean_a(σ_30[t, a]) — cross-sectional demean of trailing-30d σ.
  · k_terciles = 3 (R46/R76/R78 standard).
  · Cadences {1,3,5,7,14,21}d × costs {0,5,10}bps.
  · 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  · Per-window W1-W6 attribution.
  · **Pre-test leg-correlation gate (lesson #42 anti-imposter)** — extended to
    test vs R46 + R62 + R76 + R78 (the 4 existing legs from the frozen R77 cell +
    the R78 weak signal). If max |corr| > 0.30, flag as fusion-uncandidatable.
  · Both signs run; matched-cell sign verdict.

Two competing hypotheses:
  - H_low_long: low-vol assets outperform (volatility mean-reversion). High-vol
    = recent reprice = info-driven noise; price is mean-reverting after.
  - H_high_long: high-vol assets outperform (variance risk premium). High-vol
    = investors demanding compensation; cross-section the higher-vol names pay.

Verdict grammar:
  · ✅ SURVIVES + ORTHOGONAL — clears 3-check AND max |corr| ≤ 0.30 vs R46/R62/R76/R78.
    Eligible for fusion contribution (S-79 candidate material).
  · 🟡 SURVIVES + CORRELATED — clears 3-check BUT correlated (|corr| > 0.30) with
    existing legs → standalone-eligible but NOT fusion-candidatable.
  · 🔴 REFUTED — fails 3-check. Lesson #43 sharpens: orthogonal candidates may
    not have any standalone edge after residualization; the fusion book may be
    near-optimal for this data on this universe.

Aggregate lesson (depends on verdict):
  - ✅: "Lesson #43 v2 (gate NECESSARY + sufficient): vol-residual as orthogonal
    candidate #3 confirms the pattern. 2 of 3 orthogonal candidates carry"
    (R76 ✅, R78 🔴, S-78 ✅)."
  - 🟡: "Standalone vol-residual exists but correlates with one existing leg.
    Vol microstructure may overlap with momentum (R78) when risk-on runs
    carry both higher vol AND higher TSMOM."
  - 🔴: "Lesson #43 v2: 1 of 3 orthogonal candidates carry (R76 ✅ only).
    R78/S-78 pattern = orthogonal candidates may not have standalone edge
    after residualization; future orthogonal experiments should reach for
    cross-asset or cross-frequency sources, not just cross-sectional."

Anti-imposter:
  - Vol residual is structurally different from R46 (CIS rank), R62 (crowding-z),
    R76 (funding residual), R78 (TSMOM demean). Vol is a microstructure axis,
    not a price/funding/trend axis.
  - Pre-test leg-correlation gate is MANDATORY (lesson #42). Don't run the
    fusion sweep until the gate clears.
  - The R77 fusion-cell (R46+R62+R76 at w_R46=0.25, w_R62=0.75, w_R76=0.30) is
    FROZEN. S-78 does NOT touch it.
  - S-78 result informs a future S-79 candidate (S-78 as 4th fusion contribution)
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
from src.research.validation.funding_crowding_ls import (
    DEFAULT_CADENCES, DEFAULT_COST_GRID,
    score_funding_zwide,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.r73_pillar_a_level_ls import (
    pillar_a_level_ls, SIGN_HIGH_A_LONG,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    R62_FEATURE_SET, R62_Z, R62_MF,
)
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.r76_funding_residual_ls import (
    score_funding_residual, funding_residual_ls as r76_ls,
    SIGN_HIGH_FUND_LONG,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# S-78-specific
S78_K_TERCILES = 3                    # R46/R76/R78 standard
S78_MIN_TRADEABLE = 12                # same floor
S78_ORTHOGONALITY_GATE = 0.30         # lesson #42 — max |corr| vs existing legs
S78_VOL_LOOKBACK = 30                 # days; trailing σ window
S78_VOL_MIN_OBS = 5                   # min observations for stable σ (NaN otherwise)

# Sign constants
SIGN_HIGH_VOL_LONG = "high_vol_long"   # long assets with above-mean vol (variance risk premium)
SIGN_LOW_VOL_LONG = "low_vol_long"     # long assets with below-mean vol (vol mean-reversion)
_VALID_SIGNS = {SIGN_HIGH_VOL_LONG, SIGN_LOW_VOL_LONG}


# === Score: realized vol residual ============================================
def score_realized_vol_residual(rets: pd.DataFrame, tradeable: list,
                                lookback: int = S78_VOL_LOOKBACK,
                                min_obs: int | None = None) -> pd.DataFrame:
    """Cross-sectionally demeaned trailing-lookback σ.

    σ_30[t, a] = std of returns over the trailing `lookback` days (inclusive of t).
    vol_residual[t, a] = σ_30[t, a] − mean_a(σ_30[t, a]).

    Cross-sectional demean removes the universe's common vol regime component
    (e.g., all assets running hot during a market-wide risk-off event). The
    residual is RELATIVE vol — which assets are running HOTTER than the
    universe on this date.

    Args:
      lookback: trailing window in days (default 30, finance convention).
      min_obs: minimum non-NaN observations for the rolling std. Defaults to
        `lookback` (full window — conservative I1). Pass an explicit smaller
        value (e.g. S78_VOL_MIN_OBS=5) for sparse-asset handling; the resulting
        early σ estimates will be noisier and trade only on >=_RISK_MIN_OBS.

    NaN behavior (I1, from §ARCHITECTURE):
      - Warmup rows (< min_periods obs): NaN, NOT zero.
      - Insufficient obs in trailing window for an asset at a given t: NaN,
        NOT 0 (an inferred 0 σ would mean "no risk", which is a lie for a
        sparse asset).

    Returns wide DataFrame (date × asset) on the tradeable subset.
    """
    if min_obs is None:
        min_obs = lookback                  # default: full-window (finance convention)
    sub = rets[tradeable].copy()
    # Trailing rolling std; min_periods gates the warmup-period estimate.
    sigma = sub.rolling(lookback, min_periods=min_obs).std()
    # Cross-sectional demean at each t — only on fully-observed rows; warmup NaNs.
    fully_observed = sigma.dropna(how="any")
    demeaned_full = fully_observed.subtract(fully_observed.mean(axis=1), axis=0)
    residual = demeaned_full.reindex(sigma.index)
    return residual


# === L/S core (reuses R73's pillar_a_level_ls signature for parity) ==========
def vol_residual_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                    k_terciles: int = S78_K_TERCILES,
                    cost_bps: float = 0.0,
                    rebal_days: int = 1,
                    sign: str = SIGN_HIGH_VOL_LONG) -> pd.Series:
    """Long high-vol-residual / short low-vol-residual (or reversed under SIGN_LOW_VOL_LONG).

    Reuses R73's pillar_a_level_ls as the L/S engine — the score function differs
    (vol residual vs pillar_A level vs TSMOM demean vs funding residual) but the
    L/S logic is the same: long top tercile, short bottom tercile, optional sign flip.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_VOL_LONG else score_wide
    return pillar_a_level_ls(flipped, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign=SIGN_HIGH_A_LONG)  # already flipped above


# === Leg-correlation pre-test gate (lesson #42 anti-imposter) ================
# Reuses R78's general-n-legs gate verbatim (lesson #42 anti-imposter pattern).
from src.research.validation.r78_relative_momentum_residual import (
    leg_correlation_gate_n,
)


# === R62 detector reproduction (lifted from R77/R78) =========================
def _build_r62_detector_local(features: pd.DataFrame, fragile_mask: pd.Series,
                              fragile_ranges: list, playable_ranges: list):
    """Reproduce R62 best-cell detector on the S-78 panel (R78 parity)."""
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
        sign: str = SIGN_HIGH_VOL_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== S-78 — Realized vol residual (σ_30 cross-sectional demean) "
          f"L/S (sign={sign}, k={S78_K_TERCILES}) ===\n")

    # ── Load panels (R76/R78 parity) ─────────────────────────────────────────
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
    if len(tradeable) < S78_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(tradeable)} < {S78_MIN_TRADEABLE} "
            f"(S78_MIN_TRADEABLE floor). S-78 refuses to silently widen.")

    # ── Score: realized vol residual ─────────────────────────────────────────
    print("Computing realized vol residual (trailing-30d σ cross-sectional demean) …")
    score_volres_wide = score_realized_vol_residual(rets, tradeable)
    score_volres_wide = score_volres_wide.reindex(rets.index).ffill()
    print(f"  Score shape: {score_volres_wide.shape}, "
          f"mean={score_volres_wide.mean().mean():.6f} (should be ~0 by construction), "
          f"std={score_volres_wide.std().mean():.6f}")

    # ── 6-window partition (R76/R78 parity) ─────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── Build S-78 leg at default cadence (5d/0bps — vol moves slower than TSMOM) ─
    best_cad = 5
    leg_s78 = vol_residual_ls(score_volres_wide, rets[tradeable],
                              k_terciles=S78_K_TERCILES, cost_bps=0.0,
                              rebal_days=best_cad, sign=sign)
    leg_s78 = leg_s78.reindex(rets.index).fillna(0.0)

    # ── Reproduce R46 + R62 + R76 legs (gate prerequisites) ─────────────────
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

    print("Reproducing R76 leg (funding residual 5d/0bps) for correlation gate …")
    score_fundres_wide = score_funding_residual(funding_daily, tradeable) \
                                          .reindex(rets.index).ffill()
    leg_r76 = r76_ls(score_fundres_wide, rets[tradeable],
                      k_terciles=S78_K_TERCILES, cost_bps=0.0,
                      rebal_days=5, sign=SIGN_HIGH_FUND_LONG)
    leg_r76 = leg_r76.reindex(rets.index).fillna(0.0)

    # ── Reproduce R78 leg (relative momentum 3d/0bps) for correlation gate ──
    print("Reproducing R78 leg (TSMOM-demean 3d/0bps) for correlation gate …")
    from src.research.validation.r78_relative_momentum_residual import (
        score_relative_momentum, relative_momentum_ls as r78_ls,
        SIGN_HIGH_MOM_LONG,
    )
    score_relmom_wide = score_relative_momentum(rets, tradeable).reindex(rets.index).ffill()
    leg_r78 = r78_ls(score_relmom_wide, rets[tradeable],
                      k_terciles=S78_K_TERCILES, cost_bps=0.0,
                      rebal_days=3, sign=SIGN_HIGH_MOM_LONG)
    leg_r78 = leg_r78.reindex(rets.index).fillna(0.0)

    # ── Known factors + OOS cut (R76/R78 parity) ────────────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))

    # ── Leg-correlation gate (lesson #42 anti-imposter) — extended to 4 legs ─
    print("\n══ Leg-correlation gate (lesson #42, |corr| ≲ 0.30 vs R46/R62/R76/R78) ══\n")
    existing_legs = {"r46": leg_r46, "r62": leg_r62, "r76": leg_r76, "r78": leg_r78}
    gate = leg_correlation_gate_n(leg_s78, existing_legs)
    print(f"corr(S-78_leg, R46_leg) = {gate['corr_new_vs_r46']:+.3f}")
    print(f"corr(S-78_leg, R62_leg) = {gate['corr_new_vs_r62']:+.3f}")
    print(f"corr(S-78_leg, R76_leg) = {gate['corr_new_vs_r76']:+.3f}")
    print(f"corr(S-78_leg, R78_leg) = {gate['corr_new_vs_r78']:+.3f}")
    print(f"max |corr| = {gate['max_abs_corr']:.3f}  "
          f"(gate ≤ {gate['gate_threshold']})")
    print(f"passes_orthogonality_gate: **{gate['passes_orthogonality_gate']}**")
    print(f"fusion_candidatable: **{gate['fusion_candidatable']}**\n")

    # ── Per-leg gauntlet ────────────────────────────────────────────────────
    g_s78 = gauntlet_3check(leg_s78.values, known_full, cut)
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    g_r76 = gauntlet_3check(leg_r76.values, known_full, cut)
    g_r78 = gauntlet_3check(leg_r78.values, known_full, cut)
    print(f"Leg S-78 ({best_cad}d/0bps): gross_t={g_s78['gross_t']:+.2f}, "
          f"OOS_t={g_s78['oos_t']:+.2f}, pass_all={g_s78['passes_all']}")
    print(f"Leg R46: gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}")
    print(f"Leg R62: gross_t={g_r62['gross_t']:+.2f}, OOS_t={g_r62['oos_t']:+.2f}")
    print(f"Leg R76: gross_t={g_r76['gross_t']:+.2f}, OOS_t={g_r76['oos_t']:+.2f}")
    print(f"Leg R78: gross_t={g_r78['gross_t']:+.2f}, OOS_t={g_r78['oos_t']:+.2f}\n")

    # ── Sweep cadences × costs (both signs; matched-cell sign verdict) ──────
    print(f"══ Cadence × cost sweep (signs: {SIGN_HIGH_VOL_LONG}, {SIGN_LOW_VOL_LONG}) ══\n")
    sweep_hi = {}
    sweep_lo = {}
    for cad in cadences:
        for bps in cost_grid:
            fac_hi = vol_residual_ls(score_volres_wide, rets[tradeable],
                                      k_terciles=S78_K_TERCILES, cost_bps=bps,
                                      rebal_days=cad, sign=SIGN_HIGH_VOL_LONG)
            fac_hi = fac_hi.reindex(rets.index).fillna(0.0)
            g_hi = gauntlet_3check(fac_hi.values, known_full, cut)
            sweep_hi[(cad, bps)] = {
                "alpha_t": g_hi["gross_t"], "oos_t": g_hi["oos_t"],
                "passes_gross": g_hi["passes_gross"], "passes_oos": g_hi["passes_oos"],
                "passes_all": g_hi["passes_all"],
            }
            fac_lo = vol_residual_ls(score_volres_wide, rets[tradeable],
                                      k_terciles=S78_K_TERCILES, cost_bps=bps,
                                      rebal_days=cad, sign=SIGN_LOW_VOL_LONG)
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
    pos_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff > 0)
    neg_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff < 0)
    sign_verdict = "high_vol_long" if pos_count >= 2 else ("low_vol_long" if neg_count >= 2 else "mixed")
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
        print(f"Best SIGN_HIGH_VOL_LONG cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if best_lo[0]:
        cad, bps = best_lo[0]
        v = best_lo[1]
        print(f"Best SIGN_LOW_VOL_LONG  cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if not viable_hi and not viable_lo:
        print("⚠ NO cell passes 3-check — S-78 likely REFUTED.\n")
    else:
        print()

    # ── Final verdict ────────────────────────────────────────────────────────
    passes_3check = g_s78["passes_all"]
    orthogonal = gate["passes_orthogonality_gate"]
    if passes_3check and orthogonal:
        verdict = "✅ SURVIVES + ORTHOGONAL — S-78 (vol residual) eligible as fusion contribution"
        verdict_band = "SURVIVES_ORTHOGONAL"
    elif passes_3check and not orthogonal:
        verdict = ("🟡 SURVIVES + CORRELATED — clears 3-check but leg-correlated; "
                   "standalone-eligible, NOT fusion-candidatable")
        verdict_band = "SURVIVES_CORRELATED"
    else:
        verdict = ("🔴 REFUTED — fails 3-check; lesson #43 v2: 1 of 3 orthogonal "
                   "candidates carry after residualization (R76 only)")
        verdict_band = "REFUTED"
    print(f"VERDICT: {verdict}\n")

    # ── Per-window W1-W6 attribution (best cell if exists) ───────────────────
    from src.research.validation.r63_fusion_validation import per_window, max_drawdown
    dd_s78 = max_drawdown(leg_s78)
    pw_s78 = per_window(leg_s78, windows)
    print(f"S-78 maxDD: {dd_s78:+.2%}")
    print(f"S-78 per-window (best-cad {best_cad}d/0bps, sign={sign}):")
    for label_ in sorted(pw_s78.keys()):
        ann_pct = pw_s78[label_]["ann_pct"]
        n = pw_s78[label_]["n_days"]
        print(f"  {label_}: {ann_pct:+.1f}% (n={n})")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable),
                  "matched_assets": tradeable},
        "construction": {
            "score_basis": "realized_vol_residual (trailing-30d σ cross-sectional demean)",
            "vol_lookback": S78_VOL_LOOKBACK,
            "vol_min_obs": S78_VOL_MIN_OBS,
            "k_terciles": S78_K_TERCILES,
            "universe": "28-asset funding-bearing intersection",
            "cadences": list(cadences), "cost_grid": list(cost_grid),
            "default_cad": best_cad, "default_cost_bps": 0.0,
            "sign": sign,
        },
        "leg_correlation_gate": gate,
        "per_leg_gauntlet": {
            "leg_s78": {"gauntlet": g_s78, "default_cad": best_cad, "default_cost_bps": 0.0,
                        "max_dd": dd_s78, "per_window": pw_s78},
            "leg_r46": {"gauntlet": g_r46, "cad": R46_CAD, "cost_bps": R46_BPS},
            "leg_r62": {"gauntlet": g_r62, "cad": R62_CAD, "cost_bps": R62_BPS,
                        "feature_set": R62_FEATURE_SET, "z_threshold": R62_Z,
                        "min_features": R62_MF, "zwin": zwin},
            "leg_r76": {"gauntlet": g_r76, "cad": 5, "cost_bps": 0.0,
                        "score_basis": "funding_residual"},
            "leg_r78": {"gauntlet": g_r78, "cad": 3, "cost_bps": 0.0,
                        "score_basis": "relative_momentum (TSMOM demean)"},
        },
        "sweep_high": {f"{k[0]}d_{k[1]}bps": v for k, v in sweep_hi.items()},
        "sweep_low": {f"{k[0]}d_{k[1]}bps": v for k, v in sweep_lo.items()},
        "matched_cell_sign_audit": {
            "top_3": [{"cad": c, "bps": b, "diff": d, "hi_alpha_t": h, "lo_alpha_t": l}
                       for c, b, d, h, l in matched_diffs[:3]],
            "sign_verdict": sign_verdict,
        },
        "best_cells": {
            "sign_high_vol_long": ({"cad": best_hi[0][0], "cost_bps": best_hi[0][1],
                                     "alpha_t": best_hi[1]["alpha_t"],
                                     "oos_t": best_hi[1]["oos_t"]}
                                    if best_hi[0] else None),
            "sign_low_vol_long": ({"cad": best_lo[0][0], "cost_bps": best_lo[0][1],
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
            "note": ("S-78 is research-only. S-79 = S-78 as 4th fusion contribution "
                     "is the next step IF verdict is SURVIVES_ORTHOGONAL."),
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable S-78 report."""
    lines = []
    lines.append("# S-78 — Realized vol residual (σ_30 cross-sectional demean) L/S")
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
    lines.append(f"- Orthogonal to existing legs (R46/R62/R76/R78): "
                 f"**{v['orthogonal_to_existing_legs']}**")
    lines.append(f"- Max |corr| vs existing legs: {v['max_abs_corr_vs_existing']:.3f}")
    lines.append("")
    lines.append("## Leg-correlation gate (lesson #42, extended to 4 existing legs)")
    g = payload["leg_correlation_gate"]
    lines.append(f"- corr(S-78, R46) = {g['corr_new_vs_r46']:+.3f}")
    lines.append(f"- corr(S-78, R62) = {g['corr_new_vs_r62']:+.3f}")
    lines.append(f"- corr(S-78, R76) = {g['corr_new_vs_r76']:+.3f}")
    lines.append(f"- corr(S-78, R78) = {g['corr_new_vs_r78']:+.3f}")
    lines.append(f"- max |corr| = {g['max_abs_corr']:.3f} (gate ≤ {g['gate_threshold']})")
    lines.append(f"- passes_orthogonality_gate = **{g['passes_orthogonality_gate']}**")
    lines.append("")
    lines.append("## Per-leg gauntlet (on 28-asset)")
    for leg in ("leg_s78", "leg_r46", "leg_r62", "leg_r76", "leg_r78"):
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
        lines.append("- ✅ Lesson #43 v2: \"2 of 3 orthogonal candidates carry "
                     "(R76 ✅, R78 🔴, S-78 ✅). Vol residual confirms the pattern "
                     "that cross-sectionally-demeaned microstructure signals "
                     "(funding, momentum, vol) DO carry when they survive both "
                     "the gate and the gauntlet — but only ~half of them. "
                     "Future orthogonal candidates (#4, #5, …) should reach for "
                     "structurally different sources, not just cross-sectional "
                     "demeans of more price/funding/microstructure axes.\"")
    elif v["band"] == "SURVIVES_CORRELATED":
        lines.append("- 🟡 Lesson #43 v2: \"Vol-residual clears 3-check but correlates "
                     "with one existing leg. Vol microstructure overlaps with either "
                     "momentum (R78) or funding (R62) — when risk-on runs, vol-and-momentum "
                     "tend to co-move. Orthogonal candidate screening must catch this "
                     "BEFORE gauntlet testing. S-79 not warranted as fusion contribution.\"")
    else:
        lines.append("- 🔴 Lesson #43 v2: \"1 of 3 orthogonal candidates carry "
                     "(R76 ✅ only; R78 🔴; S-78 🔴). Cross-sectional demean of "
                     "trailing-30d σ doesn't have a standalone edge on this data. "
                     "Fusion book may be near-optimal; future orthogonal candidates "
                     "should reach for cross-asset carry / cross-frequency / "
                     "cross-section-of-cross-section sources.\"")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_HIGH_VOL_LONG,
                        choices=[SIGN_HIGH_VOL_LONG, SIGN_LOW_VOL_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/s78_vol_residual/{today}")
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
