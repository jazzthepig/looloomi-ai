"""
S-80 — Turnover residual (trailing-30d rolling-mean of daily dollar-volume cross-sectional demean)
as orthogonal candidate #4 on the CARRY/MICROSTRUCTURE axis (Seth, 2026-07-23).

Per R79 lesson #43 axis-aware pivot (REFUTED 2026-07-23): orthogonal candidates on
TREND (R78) and VOL (R79) axes lack standalone edge; ONLY the CARRY/MICROSTRUCTURE-
pressure axis (R76 funding residual) carries edge. R79's structural finding: "the
signal axis matters — gating axis matters, not just orthogonality."

S-80 opens orthogonal candidate #4 on the carry/microstructure axis (NOT another
demean'd single-class trend/vol factor):

**Turnover residual** = Σ_30d_dollar_volume/30 − mean_a(Σ_30d_dollar_volume/30)

where daily dollar_volume = volume × close. Cross-sectional demean removes the
universe's common activity regime component (e.g., all assets running hot during
a market-wide event-driven day). The residual is RELATIVE volume — which assets
are running HOTTER than the universe on this date.

Why "turnover residual" is on the carry/microstructure axis:
  · Captures informed-flow pressure (heavy trading = informed flow).
  · Persistent over days/weeks (position unwind takes time).
  · Structurally different from R46 (CIS-quality rank), R62 (absolute funding-z),
    R76 (funding residual), R78 (TSMOM), S-78 (vol residual).
  · Closest sibling to funding residual R76: both capture microstructure pressure
    that perp market-makers/funds unwind over days.

Why it MIGHT carry edge (per lesson #43 axis-aware pivot):
  - Funding residual (R76) survived because perp market-maker positioning is
    persistent microstructure pressure. Turnover residual is the OTHER side of
    the same phenomenon: heavy informed flow → perp adjustment → funding tail.
    They should be correlated but not identical.

Why it MIGHT NOT carry edge:
  - Volume is noisier than funding (volume can spike on noise days).
  - Cross-sectional demean of volume is structurally similar to other demean'd
    axes (R78, R79) — just a different axis.
  - The W5 fragility window (where R46/R62 sign-flip) might torture turn too.

S-80 design (parallels R76/R78/S-78):
  · Universe: 28-asset strict funding ∩ CIS ∩ OHLCV.
  · Score: σ_30-tonus[t, a] = mean_30d(dollar_volume[t, a]) − mean_a(mean_30d(dollar_volume[t, a])).
  · k_terciles = 3.
  · Cadences {1,3,5,7,14,21}d × costs {0,5,10}bps.
  · 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  · Per-window W1-W6 attribution.
  · **Pre-test leg-correlation gate (lesson #42 anti-imposter)** extended to
    4 existing legs (R46/R62/R76/R78). If max |corr| > 0.30, flag as
    fusion-uncandidatable.
  · Both signs run; matched-cell sign verdict.

Verdict grammar:
  · ✅ SURVIVES + ORTHOGONAL — clears 3-check AND max |corr| ≤ 0.30 vs existing legs.
    Eligible for fusion contribution (S-81 candidate material).
  · 🟡 SURVIVES + CORRELATED — clears 3-check BUT correlated (|corr| > 0.30) with
    existing legs → standalone-eligible but NOT fusion-candidatable.
  · 🔴 REFUTED — fails 3-check. Lesson #43 sharpens: 1 of 4 orthogonal candidates
    (R76) carry; R78/R79/S-80 pattern = cross-sectional demean of single-class
    microstructure axes mostly lacks edge. Fusion book may be near-optimal.

Aggregate lesson (depends on verdict):
  - ✅: "Lesson #43 v3 (axis-aware pivot CONFIRMED): 2 of 4 orthogonal candidates
    carry (R76 ✅, S-80 ✅). Carry/microstructure axis (funding AND turnover)
    survives; trend/vol axes don't. Future orthogonal candidates #5+ should
    reach for cross-asset or cross-frequency sources, not just cross-sectional
    demeans of more microstructure axes."
  - 🟡: "Standalone turnover-residual exists but correlates with one existing
    leg (likely R76). Funding residual and turnover residual are the same
    phenomenon (informed-flow pressure) — adding turnover dilutes R76 without
    diversification."
  - 🔴: "Lesson #43 v3: 1 of 4 orthogonal candidates carry (R76 only). Single-class
    cross-sectional demeans (funding, momentum, vol, turnover) mostly lack edge.
    Future orthogonal candidates should reach for cross-asset carry, cross-frequency
    (4h/24h cross-section), or cross-section-of-cross-section (10y curve) sources."

Anti-imposter:
  - Turnover residual is structurally different from R46 (CIS rank), R62 (crowding-z),
    R76 (funding residual), R78 (TSMOM), S-78 (vol residual). Turnover is a
    flow/activity axis, not a price/funding/trend/dispersion axis.
  - Pre-test leg-correlation gate is MANDATORY (lesson #42). Don't run the fusion
    sweep until the gate clears.
  - The R77 fusion-cell (R46+R62+R76 at w_R46=0.25, w_R62=0.75, w_R76=0.30) is
    FROZEN. S-80 does NOT touch it.
  - S-80 result informs a future S-81 candidate (S-80 as 4th fusion contribution)
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
    load_cis_history_wide, load_daily_returns, OHLCV_DIR,
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
    funding_residual_ls as r76_ls, score_funding_residual,
    SIGN_HIGH_FUND_LONG,
)
from src.research.validation.r78_relative_momentum_residual import (
    leg_correlation_gate_n, score_relative_momentum,
    relative_momentum_ls as r78_ls, SIGN_HIGH_MOM_LONG,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# S-80-specific
S80_K_TERCILES = 3                    # R46/R76/S-78 standard
S80_MIN_TRADEABLE = 12                # same floor
S80_ORTHOGONALITY_GATE = 0.30         # lesson #42 — max |corr| vs existing legs
S80_TONUS_LOOKBACK = 30               # days; trailing volume mean window
S80_TONUS_MIN_OBS = 5                 # min observations for stable mean

# Sign constants
SIGN_HIGH_TONUS_LONG = "high_tonus_long"   # long assets with above-mean tone (informed-flow pickup)
SIGN_LOW_TONUS_LONG = "low_tonus_long"     # long assets with below-mean tone (quiet accumulation)
_VALID_SIGNS = {SIGN_HIGH_TONUS_LONG, SIGN_LOW_TONUS_LONG}


# === Load: daily dollar volume ===============================================
def load_daily_dollar_volume(ohlcv_dir: Path = OHLCV_DIR) -> pd.DataFrame:
    """Resample hourly OHLCV → daily dollar volume = Σ(hourly volume × close) per day.

    Returns wide DataFrame (date × asset). Volume is column sum across hours
    of the day; dollar volume weights by concurrent close (best approximation
    without intraday volume-weighted pricing).

    NaN behavior: assets with no parquet are absent from the output. Hours with
    NaN volume are dropped from the daily sum (I1 invariant — never impute 0,
    which would understate dollar volume on sparse days).
    """
    all_dollar = {}
    for f in sorted(ohlcv_dir.glob("*.parquet")):
        sym = f.stem
        df = pd.read_parquet(f)
        if "timestamp" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.normalize()
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        else:
            continue
        if "volume" not in df.columns or "close" not in df.columns:
            continue
        # Drop hourly rows with NaN volume or close (I1)
        df = df.dropna(subset=["volume", "close"])
        if df.empty:
            continue
        # Daily dollar volume = sum of (volume × close) over the day
        df["dollar_volume"] = df["volume"] * df["close"]
        daily = df.groupby("date")["dollar_volume"].sum().sort_index()
        all_dollar[sym] = daily
    return pd.DataFrame(all_dollar)


# === Score: turnover residual ================================================
def score_turnover_residual(dollar_volume: pd.DataFrame, tradeable: list,
                            lookback: int = S80_TONUS_LOOKBACK,
                            min_obs: int | None = None) -> pd.DataFrame:
    """Cross-sectionally demeaned trailing-30d dollar-volume mean.

    dusd_30[t, a] = mean of dollar_volume over the trailing `lookback` days (inclusive).
    tonus_residual[t, a] = dusd_30[t, a] − mean_a(dusd_30[t, a]).

    Cross-sectional demean removes the universe's common activity regime
    component (e.g., all assets running hot on a market-wide event day). The
    residual is RELATIVE volume — which assets are running HOTTER than the
    universe on this date.

    Args:
      lookback: trailing window in days (default 30, finance convention).
      min_obs: minimum non-NaN observations for the rolling mean. Defaults to
        `lookback` (full-window — conservative I1). Pass an explicit smaller
        value for sparse-asset handling.

    NaN behavior (I1, from §ARCHITECTURE):
      - Warmup rows (< min_periods): NaN, NOT zero.
      - Insufficient obs in window for an asset at a given t: NaN, NOT 0.
      - Cross-section demean uses dropna(how="any"): rows where ANY asset is
        NaN are excluded from the mean computation.

    Returns wide DataFrame (date × asset) on the tradeable subset.
    """
    if min_obs is None:
        min_obs = lookback
    sub = dollar_volume[tradeable].copy()
    # Trailing rolling mean; min_periods gates the warmup-period estimate.
    dusd = sub.rolling(lookback, min_periods=min_obs).mean()
    # Cross-sectional demean at each t — only on fully-observed rows.
    fully_observed = dusd.dropna(how="any")
    demeaned_full = fully_observed.subtract(fully_observed.mean(axis=1), axis=0)
    residual = demeaned_full.reindex(dusd.index)
    return residual


# === L/S core (reuses R73's pillar_a_level_ls signature for parity) ==========
def turnover_residual_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                         k_terciles: int = S80_K_TERCILES,
                         cost_bps: float = 0.0,
                         rebal_days: int = 1,
                         sign: str = SIGN_HIGH_TONUS_LONG) -> pd.Series:
    """Long high-tonus-residual / short low-tonus-residual (or reversed under SIGN_LOW_TONUS_LONG).

    Reuses R73's pillar_a_level_ls as the L/S engine — the score function differs
    (turnover residual vs pillar_A level vs funding residual vs TSMOM vs vol residual)
    but the L/S logic is the same: long top tercile, short bottom tercile, optional sign flip.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_TONUS_LONG else score_wide
    return pillar_a_level_ls(flipped, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign=SIGN_HIGH_A_LONG)


# === R62 detector reproduction (lifted from R77/S-78) ========================
def _build_r62_detector_local(features: pd.DataFrame, fragile_mask: pd.Series,
                              fragile_ranges: list, playable_ranges: list):
    """Reproduce R62 best-cell detector on the S-80 panel (S-78 parity)."""
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
        sign: str = SIGN_HIGH_TONUS_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== S-80 — Turnover residual (30d rolling-mean dollar-volume cross-sectional "
          f"demean) L/S (sign={sign}, k={S80_K_TERCILES}) ===\n")

    # ── Load panels (R76/S-78 parity) ─────────────────────────────────────────
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
    if len(tradeable) < S80_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(tradeable)} < {S80_MIN_TRADEABLE} "
            f"(S80_MIN_TRADEABLE floor). S-80 refuses to silently widen.")

    # ── Load daily dollar volume & compute turnover residual ──────────────────
    print("Loading daily dollar volume (Σ hourly volume × close) …")
    dollar_volume = load_daily_dollar_volume()
    dv_assets = sorted(set(tradeable) & set(dollar_volume.columns))
    print(f"  Dollar volume: {dollar_volume.shape[0]} days × "
          f"{dollar_volume.shape[1]} assets ({len(dv_assets)} matched)")
    if len(dv_assets) < S80_MIN_TRADEABLE:
        raise RuntimeError(
            f"Dollar volume universe too small: {len(dv_assets)} < {S80_MIN_TRADEABLE}. "
            f"S-80 refuses to silently widen.")

    # Restrict to assets with BOTH funding AND dollar volume (28-asset strict)
    tradeable_dv = sorted(set(tradeable) & set(dv_assets))
    print(f"  Strict intersection (funding ∩ CIS ∩ OHLCV ∩ dollar-volume): "
          f"{len(tradeable_dv)} assets")

    # ── Score: turnover residual ──────────────────────────────────────────────
    print("Computing turnover residual (30d rolling-mean dollar-volume cross-sectional "
          "demean) …")
    score_tonus_wide = score_turnover_residual(dollar_volume, tradeable_dv)
    score_tonus_wide = score_tonus_wide.reindex(rets.index).ffill()
    print(f"  Score shape: {score_tonus_wide.shape}, "
          f"mean={score_tonus_wide.mean().mean():.6f} (should be ~0 by construction), "
          f"std={score_tonus_wide.std().mean():.6f}")

    # ── 6-window partition (R76/S-78 parity) ─────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── Build S-80 leg at default cadence (5d/0bps — turnover moves slowly) ───
    best_cad = 5
    leg_s80 = turnover_residual_ls(score_tonus_wide, rets[tradeable_dv],
                                    k_terciles=S80_K_TERCILES, cost_bps=0.0,
                                    rebal_days=best_cad, sign=sign)
    leg_s80 = leg_s80.reindex(rets.index).fillna(0.0)

    # ── Reproduce R46 + R62 + R76 + R78 legs (gate prerequisites) ─────────────
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
                      k_terciles=S80_K_TERCILES, cost_bps=0.0,
                      rebal_days=5, sign=SIGN_HIGH_FUND_LONG)
    leg_r76 = leg_r76.reindex(rets.index).fillna(0.0)

    print("Reproducing R78 leg (TSMOM-demean 3d/0bps) for correlation gate …")
    score_relmom_wide = score_relative_momentum(rets, tradeable).reindex(rets.index).ffill()
    leg_r78 = r78_ls(score_relmom_wide, rets[tradeable],
                      k_terciles=S80_K_TERCILES, cost_bps=0.0,
                      rebal_days=3, sign=SIGN_HIGH_MOM_LONG)
    leg_r78 = leg_r78.reindex(rets.index).fillna(0.0)

    # ── Known factors + OOS cut (R76/S-78 parity) ─────────────────────────────
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
    gate = leg_correlation_gate_n(leg_s80, existing_legs)
    print(f"corr(S-80_leg, R46_leg) = {gate['corr_new_vs_r46']:+.3f}")
    print(f"corr(S-80_leg, R62_leg) = {gate['corr_new_vs_r62']:+.3f}")
    print(f"corr(S-80_leg, R76_leg) = {gate['corr_new_vs_r76']:+.3f}")
    print(f"corr(S-80_leg, R78_leg) = {gate['corr_new_vs_r78']:+.3f}")
    print(f"max |corr| = {gate['max_abs_corr']:.3f}  "
          f"(gate ≤ {gate['gate_threshold']})")
    print(f"passes_orthogonality_gate: **{gate['passes_orthogonality_gate']}**")
    print(f"fusion_candidatable: **{gate['fusion_candidatable']}**\n")

    # ── Per-leg gauntlet ────────────────────────────────────────────────────
    g_s80 = gauntlet_3check(leg_s80.values, known_full, cut)
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    g_r76 = gauntlet_3check(leg_r76.values, known_full, cut)
    g_r78 = gauntlet_3check(leg_r78.values, known_full, cut)
    print(f"Leg S-80 ({best_cad}d/0bps): gross_t={g_s80['gross_t']:+.2f}, "
          f"OOS_t={g_s80['oos_t']:+.2f}, pass_all={g_s80['passes_all']}")
    print(f"Leg R46: gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}")
    print(f"Leg R62: gross_t={g_r62['gross_t']:+.2f}, OOS_t={g_r62['oos_t']:+.2f}")
    print(f"Leg R76: gross_t={g_r76['gross_t']:+.2f}, OOS_t={g_r76['oos_t']:+.2f}")
    print(f"Leg R78: gross_t={g_r78['gross_t']:+.2f}, OOS_t={g_r78['oos_t']:+.2f}\n")

    # ── Sweep cadences × costs (both signs; matched-cell sign verdict) ──────
    print(f"══ Cadence × cost sweep (signs: {SIGN_HIGH_TONUS_LONG}, {SIGN_LOW_TONUS_LONG}) ══\n")
    sweep_hi = {}
    sweep_lo = {}
    for cad in cadences:
        for bps in cost_grid:
            fac_hi = turnover_residual_ls(score_tonus_wide, rets[tradeable_dv],
                                           k_terciles=S80_K_TERCILES, cost_bps=bps,
                                           rebal_days=cad, sign=SIGN_HIGH_TONUS_LONG)
            fac_hi = fac_hi.reindex(rets.index).fillna(0.0)
            g_hi = gauntlet_3check(fac_hi.values, known_full, cut)
            sweep_hi[(cad, bps)] = {
                "alpha_t": g_hi["gross_t"], "oos_t": g_hi["oos_t"],
                "passes_gross": g_hi["passes_gross"], "passes_oos": g_hi["passes_oos"],
                "passes_all": g_hi["passes_all"],
            }
            fac_lo = turnover_residual_ls(score_tonus_wide, rets[tradeable_dv],
                                           k_terciles=S80_K_TERCILES, cost_bps=bps,
                                           rebal_days=cad, sign=SIGN_LOW_TONUS_LONG)
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
    sign_verdict = "high_tonus_long" if pos_count >= 2 else ("low_tonus_long" if neg_count >= 2 else "mixed")
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
        print(f"Best SIGN_HIGH_TONUS_LONG cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if best_lo[0]:
        cad, bps = best_lo[0]
        v = best_lo[1]
        print(f"Best SIGN_LOW_TONUS_LONG  cell: {cad}d/{bps}bps, α_t={v['alpha_t']:+.2f}, "
              f"OOS_t={v['oos_t']:+.2f}")
    if not viable_hi and not viable_lo:
        print("⚠ NO cell passes 3-check — S-80 likely REFUTED.\n")
    else:
        print()

    # ── Final verdict ────────────────────────────────────────────────────────
    passes_3check = g_s80["passes_all"]
    orthogonal = gate["passes_orthogonality_gate"]
    if passes_3check and orthogonal:
        verdict = "✅ SURVIVES + ORTHOGONAL — S-80 (turnover residual) eligible as fusion contribution"
        verdict_band = "SURVIVES_ORTHOGONAL"
    elif passes_3check and not orthogonal:
        verdict = ("🟡 SURVIVES + CORRELATED — clears 3-check but leg-correlated; "
                   "standalone-eligible, NOT fusion-candidatable")
        verdict_band = "SURVIVES_CORRELATED"
    else:
        verdict = ("🔴 REFUTED — fails 3-check; lesson #43 v3: 1 of 4 orthogonal "
                   "candidates carry (R76 only); cross-sectional demean of single-class "
                   "microstructure axes mostly lacks edge")
        verdict_band = "REFUTED"
    print(f"VERDICT: {verdict}\n")

    # ── Per-window W1-W6 attribution (best cell if exists) ───────────────────
    from src.research.validation.r63_fusion_validation import per_window, max_drawdown
    dd_s80 = max_drawdown(leg_s80)
    pw_s80 = per_window(leg_s80, windows)
    print(f"S-80 maxDD: {dd_s80:+.2%}")
    print(f"S-80 per-window (best-cad {best_cad}d/0bps, sign={sign}):")
    for label_ in sorted(pw_s80.keys()):
        ann_pct = pw_s80[label_]["ann_pct"]
        n = pw_s80[label_]["n_days"]
        print(f"  {label_}: {ann_pct:+.1f}% (n={n})")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable),
                  "n_assets_strict_dollar_volume": len(tradeable_dv),
                  "matched_assets": tradeable_dv},
        "construction": {
            "score_basis": "turnover_residual (30d rolling-mean dollar-volume cross-sectional demean)",
            "tonus_lookback": S80_TONUS_LOOKBACK,
            "tonus_min_obs": S80_TONUS_MIN_OBS,
            "k_terciles": S80_K_TERCILES,
            "universe": "28-asset funding ∩ CIS ∩ OHLCV ∩ dollar-volume",
            "cadences": list(cadences), "cost_grid": list(cost_grid),
            "default_cad": best_cad, "default_cost_bps": 0.0,
            "sign": sign,
        },
        "leg_correlation_gate": gate,
        "per_leg_gauntlet": {
            "leg_s80": {"gauntlet": g_s80, "default_cad": best_cad, "default_cost_bps": 0.0,
                        "max_dd": dd_s80, "per_window": pw_s80},
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
            "sign_high_tonus_long": ({"cad": best_hi[0][0], "cost_bps": best_hi[0][1],
                                       "alpha_t": best_hi[1]["alpha_t"],
                                       "oos_t": best_hi[1]["oos_t"]}
                                      if best_hi[0] else None),
            "sign_low_tonus_long": ({"cad": best_lo[0][0], "cost_bps": best_lo[0][1],
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
            "note": ("S-80 is research-only. S-81 = S-80 as 4th fusion contribution "
                     "is the next step IF verdict is SURVIVES_ORTHOGONAL."),
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable S-80 report."""
    lines = []
    lines.append("# S-80 — Turnover residual (30d rolling-mean dollar-volume cross-sectional demean) L/S")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_assets_strict_dollar_volume']}-asset strict "
                 f"funding ∩ CIS ∩ OHLCV ∩ dollar-volume universe)")
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
    lines.append(f"- corr(S-80, R46) = {g['corr_new_vs_r46']:+.3f}")
    lines.append(f"- corr(S-80, R62) = {g['corr_new_vs_r62']:+.3f}")
    lines.append(f"- corr(S-80, R76) = {g['corr_new_vs_r76']:+.3f}")
    lines.append(f"- corr(S-80, R78) = {g['corr_new_vs_r78']:+.3f}")
    lines.append(f"- max |corr| = {g['max_abs_corr']:.3f} (gate ≤ {g['gate_threshold']})")
    lines.append(f"- passes_orthogonality_gate = **{g['passes_orthogonality_gate']}**")
    lines.append("")
    lines.append("## Per-leg gauntlet (on 28-asset)")
    for leg in ("leg_s80", "leg_r46", "leg_r62", "leg_r76", "leg_r78"):
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
        lines.append("- ✅ Lesson #43 v3 (axis-aware pivot CONFIRMED): 2 of 4 orthogonal "
                     "candidates carry (R76 ✅, S-80 ✅). Carry/microstructure axis "
                     "(funding AND turnover) survives; trend/vol axes don't. Future "
                     "orthogonal candidates should reach for cross-asset or "
                     "cross-frequency sources, not just cross-sectional demean of "
                     "more microstructure axes.")
    elif v["band"] == "SURVIVES_CORRELATED":
        lines.append("- 🟡 Lesson #43 v3: \"Standalone turnover-residual exists but "
                     "correlates with R76 (funding residual). Funding and turnover "
                     "are the same phenomenon (informed-flow pressure) — adding "
                     "turnover dilutes R76 without diversification. S-81 not warranted.\"")
    else:
        lines.append("- 🔴 Lesson #43 v3: \"1 of 4 orthogonal candidates carry (R76 only). "
                     "Cross-sectional demean of single-class microstructure axes "
                     "(funding, momentum, vol, turnover) mostly lack edge. Fusion book "
                     "may be near-optimal; future orthogonal candidates should reach "
                     "for cross-asset carry, cross-frequency (4h/24h cross-section), "
                     "or cross-section-of-cross-section (10y curve) sources.\"")
    lines.append("")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_HIGH_TONUS_LONG,
                        choices=[SIGN_HIGH_TONUS_LONG, SIGN_LOW_TONUS_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/s80_turnover_residual/{today}")
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
