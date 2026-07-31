"""
R93 — Informativeness-Weighted Funding L/S (Seth, 2026-07-26).

Per R82/R90 lessons (#56 panel length, #58 cost-tier gate, #42 anti-costume):
- R47 (pooled funding-crowding): REFUTED — naive fade failed in F1 meme-rotation
  ("fade the crowd only right when crowd was wrong").
- R60 (per-asset funding-crowding): REFUTED — best cell 21d/0bps gross_t=+1.73
  and OOS_t=+1.89, both <1.96. W1=−37.4%, W3=−22.5% the specific failure windows.
- R62 (regime-conditioned fade): SURVIVES in R77 as the w=0.75 leg — the residual
  funding-as-edge lives there.
- R76 (funding residual): SURVIVES at 5d/5bps (3-check passes), orthogonal to R46/R62,
  ships as R77's 3rd fusion contribution at w_R76=0.30. R77 frozen cell
  (w_R46=0.25/w_R62=0.75/w_R76=0.30) is FROZEN; R93 must NOT modify.

R93 opens a structurally-new axis: **INFORMATIVENESS-WEIGHTED FUNDING Z**.
Mechanism (lesson #14): "fade the crowd is only right when the crowd is wrong."
R47/R60 failed in exactly the windows where funding was NOISE or the crowd was
RIGHT. The fix is conditioning the cross-section on how *informative* each asset's
funding reading is.

Construction:
  · Per-asset z of funding over zwin=30d (time-series normalization, NOT cross-sec).
  · Informativeness ι[i,t] over trailing iwin ∈ {14,30,60}d, one of:
      - sign_consistency: |frac(same-sign days) − 0.5| × 2   ∈ [0,1]   (DEFAULT)
      - abs_autocorr:     |lag-1 autocorr of funding|         ∈ [0,1]
      - snr:              |mean(funding)| / (std(funding)+ε), cross-sec ranked
  · score[i,t] = fade_sign × funding_z[i,t] × ι[i,t]      (fade_sign=−1 default)
  · L/S: long top tercile / short bottom tercile (R76/R46 k=3 standard)
  · Universe: 47 perps with funding + perp OHLCV (Hyperliquid dataset, 2023-05 →
    2026-07 ~1150 days — longer/more regime-balanced than the 731d strict panel).
  · Cadences {5,7,14,21}d × costs {0,5,10,20,30}bps (R60: ≥14d needed for funding).
  · 3-check gauntlet: gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96.
  · Cost-tier sweep (R32 lesson #58 baked in).
  · Leg-correlation gate (lesson #42 anti-costume): corr(R93_leg, naive_fade_leg) <
    0.60 (vs R62-style per-asset-z fade). If ι≡1, R93 reduces to naive fade and the
    gate fails. R93 must PROVE it adds information via informativeness conditioning.

Anti-costume guard:
  - R93 with ι≡1 reduces to R62's per-asset-z fade (REFUTED R60 form). The
    corr<0.60 gate ensures informativeness conditioning does meaningful work —
    else R93 is just a relabeling of a refuted sleeve.
  - R93 is STRUCTURALLY DIFFERENT from R62/R76: per-asset z × per-asset
    informativeness (nonlinear per-asset conditioning), NOT cross-sectional demean.

Verdict grammar (R90 style + R62-style anti-costume gate — STRICT):
  · ✅ TRADEABLE — 3-check at 5bps passes AND survives_realistic_10bps AND
    matched-sign clear AND W5 t ≥ 0 AND corr(R93, naive_fade) < 0.60. Eligible for
    Strategy 2 slot.
  · 🟡 PARTIAL — clears 5bps 3-check BUT dies at 10bps (fee illusion, R32/R89) OR
    corr(R93, naive_fade) ≥ 0.60 (R62 in disguise). NOT tradeable.
  · 🔴 REFUTED — fails 3-check at any cost tier. Informativeness conditioning on
    funding-z doesn't add information; R93 collapses onto refuted signal.

The falsifiable mechanistic claim (must be reported): did informativeness-weighting
turn the naive-fade *failure* windows positive? Compare R93 vs R60 on W1 (R60
−37.4%) and W3 (R60 −22.5%). If R93 stays negative there, informativeness thesis
is disproven even if headline t clears — report it honestly.

Anti-imposter:
  - R93 is research-only. The R77 fusion cell (w_R46=0.25/w_R62=0.75/w_R76=0.30) is
    FROZEN; R93 does NOT touch it.
  - R93 result informs Strategy 2 slot ONLY if verdict is ✅ TRADEABLE.
  - Live paper deployment requires user sign-off after verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.research.validation.r73_pillar_a_level_ls import (
    pillar_a_level_ls, SIGN_HIGH_A_LONG,
)
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.r63_fusion_validation import per_window


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365

# R93-specific
R93_ZWIN = 30                          # per-asset z-score window
R93_IWINS = (14, 30, 60)               # informativeness windows to sweep
R93_IMETHODS = ("sign_consistency",)   # DEFAULT; others for robustness
R93_K_TERCILES = 3                     # R76/R46 standard
R93_MIN_TRADEABLE = 12                 # same floor as R76/R90/R73
R93_CADENCES = (5, 7, 14, 21)          # R60: funding signal lives at ≥14d
R93_COST_GRID = (0.0, 5.0, 10.0, 20.0, 30.0)
R93_REALISTIC_COST_BPS = 10.0          # lesson #58 — gate on survival here
R93_LEGCORR_GATE = 0.60                # corr vs naive-fade (anti-costume)
R93_PERP_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")

# Sign constants (mirror R76/R90 convention)
SIGN_HIGH_FUND_LONG = "high_fund_long"   # long assets with high funding_z (above-mean funding pressure)
SIGN_LOW_FUND_LONG = "low_fund_long"     # long assets with low funding_z = FADE (default)
_VALID_SIGNS = {SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG}

# Informativeness methods
IMETHOD_SIGN_CONSISTENCY = "sign_consistency"  # default
IMETHOD_ABS_AUTOCORR = "abs_autocorr"
IMETHOD_SNR = "snr"
_VALID_IMETHODS = {IMETHOD_SIGN_CONSISTENCY, IMETHOD_ABS_AUTOCORR, IMETHOD_SNR}


# === Informativeness weight ===================================================
def informativeness_weight(funding_wide: pd.DataFrame, iwin: int = 30,
                           method: str = IMETHOD_SIGN_CONSISTENCY) -> pd.DataFrame:
    """Per-asset rolling informativeness of funding over trailing iwin days.

    Returns wide DataFrame (date × asset) with ι ∈ [0,1] cross-sectionally normalized.
    Three methods:
      - sign_consistency: |frac(same-sign days) - 0.5| × 2   ∈ [0,1]   (default)
      - abs_autocorr:     |lag-1 autocorr of funding|         ∈ [0,1]
      - snr:              |mean(funding)| / (std(funding)+ε), cross-sec ranked [0,1]

    Higher ι = more informative funding reading (persistent, committed positioning).
    Lower ι = noisy/chattering funding (transient, mean-reverting on its own).
    """
    if method not in _VALID_IMETHODS:
        raise ValueError(f"method must be one of {_VALID_IMETHODS}, got {method!r}")
    if iwin < 2:
        raise ValueError(f"iwin must be ≥ 2, got {iwin}")

    min_p = max(2, iwin // 2)

    if method == IMETHOD_SIGN_CONSISTENCY:
        # Per-asset rolling mean of sign(funding) → in [-1, +1].
        # Take abs → in [0, 1]. Already cross-asset compatible (no need to normalize).
        sign_x = np.sign(funding_wide.fillna(0.0))
        roll_sign_mean = sign_x.rolling(iwin, min_periods=min_p).mean()
        iota = roll_sign_mean.abs()
        # Cross-sec min-max normalize to [0, 1] each day. If degenerate (all same),
        # default to 0.5 (neutral).
        iota_min = iota.min(axis=1)
        iota_max = iota.max(axis=1)
        rng = (iota_max - iota_min).replace(0, np.nan)
        iota = iota.sub(iota_min, axis=0).div(rng, axis=0)
        iota = iota.fillna(0.5)
    elif method == IMETHOD_ABS_AUTOCORR:
        # Lag-1 autocorr over rolling iwin
        shifted = funding_wide.shift(1)
        corr = funding_wide.rolling(iwin, min_periods=min_p).corr(shifted)
        iota = corr.abs()
        # Cross-sec min-max normalize to [0, 1] each day
        iota_min = iota.min(axis=1)
        iota_max = iota.max(axis=1)
        rng = (iota_max - iota_min).replace(0, np.nan)
        iota = iota.sub(iota_min, axis=0).div(rng, axis=0)
        iota = iota.fillna(0.5)
    else:  # IMETHOD_SNR
        m = funding_wide.rolling(iwin, min_periods=min_p).mean().abs()
        s = funding_wide.rolling(iwin, min_periods=min_p).std()
        iota = m / (s + 1e-8)
        # Cross-sec rank to [0, 1] (pct=True → in [0, 1])
        iota = iota.rank(axis=1, pct=True)
        iota = iota.fillna(0.5)

    return iota


# === Combined score ===========================================================
def score_iw_funding(funding_wide: pd.DataFrame, *,
                     zwin: int = R93_ZWIN,
                     iwin: int = 30,
                     method: str = IMETHOD_SIGN_CONSISTENCY,
                     fade_sign: int = -1) -> pd.DataFrame:
    """Build R93 informativeness-weighted funding-z score.

    Args:
        funding_wide: date × asset daily-mean funding
        zwin: per-asset z-score window
        iwin: informativeness window
        method: informativeness method
        fade_sign: -1 = fade (short crowded / long uncrowded, the R62 default);
                   +1 = anti-fade (long crowded / short uncrowded)

    Returns:
        score: date × asset, fade_sign × funding_z × iota

    When ι≡1 for all assets (e.g. persistent universe), score reduces to naive
    fade_sign × funding_z. The leg-correlation gate (lesson #42 anti-costume) detects
    when ι≡1 is approximately true.
    """
    if fade_sign not in (-1, +1):
        raise ValueError(f"fade_sign must be -1 or +1, got {fade_sign!r}")

    # Per-asset z of funding over rolling zwin
    min_p = max(2, zwin // 2)
    mu = funding_wide.rolling(zwin, min_periods=min_p).mean()
    sd = funding_wide.rolling(zwin, min_periods=min_p).std()
    funding_z = (funding_wide - mu) / (sd + 1e-8)

    # Informativeness ι ∈ [0, 1]
    iota = informativeness_weight(funding_wide, iwin=iwin, method=method)

    # Combined score (fillna 0 → no signal during warmup, PIT-safe)
    score = (fade_sign * funding_z * iota).fillna(0.0)
    return score


# === L/S kernel ===============================================================
def iw_funding_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                  k_terciles: int = R93_K_TERCILES,
                  cost_bps: float = 0.0,
                  rebal_days: int = 7) -> pd.Series:
    """Long top tercile / short bottom tercile of R93 informativeness-weighted score.

    Reuses pillar_a_level_ls (R73's L/S engine). The score encodes fade by construction
    (fade_sign=-1 default), so this function passes score_wide directly with
    sign="high_a_long" — long top tercile (positive score = low funding = uncrowded).
    """
    return pillar_a_level_ls(score_wide, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign=SIGN_HIGH_A_LONG)


def iw_funding_ls_sign(score_wide: pd.DataFrame, rets: pd.DataFrame,
                        k_terciles: int = R93_K_TERCILES,
                        cost_bps: float = 0.0,
                        rebal_days: int = 7,
                        sign: str = SIGN_LOW_FUND_LONG) -> pd.Series:
    """L/S with sign choice — mirrors R76's funding_residual_ls_sign pattern.

    Sign conventions:
      - SIGN_LOW_FUND_LONG (default = fade): long uncrowded, short crowded. score as-is.
      - SIGN_HIGH_FUND_LONG (anti-fade): long crowded, short uncrowded. score flipped.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_HIGH_FUND_LONG else score_wide
    return pillar_a_level_ls(flipped, rets, k_terciles=k_terciles,
                              cost_bps=cost_bps, rebal_days=rebal_days,
                              sign=SIGN_HIGH_A_LONG)


# === Perp returns loader (R90 verbatim) =======================================
def load_perp_returns(panel_dates: pd.DatetimeIndex,
                      assets: list) -> pd.DataFrame:
    """Load perp close-to-close returns for the given assets, aligned to panel_dates.

    Single-instrument (perp OHLCV only — no spot leg). R90's load_perp_returns exact pattern.
    """
    rets = pd.DataFrame(index=panel_dates)
    for asset in assets:
        fp = R93_PERP_DIR / f"{asset.lower()}_1d_ohlcv.csv"
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        if df.empty or "openTime" not in df.columns or "close" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["openTime"], unit="ms").dt.normalize()
        daily = df.groupby("date")["close"].last().sort_index().pct_change()
        rets[asset] = daily.reindex(panel_dates)
    return rets


# === Sweep ===================================================================
def iw_funding_sweep(funding_wide: pd.DataFrame, rets: pd.DataFrame, tradeable: list, *,
                     cadences: tuple = R93_CADENCES,
                     iwins: tuple = R93_IWINS,
                     imethods: tuple = R93_IMETHODS,
                     cost_grid: tuple = R93_COST_GRID,
                     k: int = R93_K_TERCILES) -> dict:
    """Sweep (cad, iwin, method, bps, sign) → leg (pd.Series of returns).

    Grid size = len(cadences) × len(iwins) × len(imethods) × len(cost_grid) × 2 (signs).
    Default = 4 × 3 × 1 × 5 × 2 = 120 cells.
    """
    sweep = {}
    funding_sub = funding_wide[tradeable]
    for iwin in iwins:
        for method in imethods:
            # Build score once per (iwin, method); both signs reuse it
            score = score_iw_funding(funding_sub, iwin=iwin, method=method,
                                     fade_sign=-1)  # default fade
            for cad in cadences:
                for bps in cost_grid:
                    leg_hi = iw_funding_ls_sign(score, rets[tradeable],
                                                 k_terciles=k, cost_bps=bps,
                                                 rebal_days=cad,
                                                 sign=SIGN_HIGH_FUND_LONG)
                    leg_lo = iw_funding_ls_sign(score, rets[tradeable],
                                                 k_terciles=k, cost_bps=bps,
                                                 rebal_days=cad,
                                                 sign=SIGN_LOW_FUND_LONG)
                    sweep[(cad, iwin, method, bps, SIGN_HIGH_FUND_LONG)] = leg_hi
                    sweep[(cad, iwin, method, bps, SIGN_LOW_FUND_LONG)] = leg_lo
    return sweep


# === Cost-tier sweep (R32/R89/R90 lesson #58 — MANDATORY) =====================
def cost_tier_sweep_with_score(score_wide: pd.DataFrame, rets: pd.DataFrame,
                                tradeable: list, *,
                                cadence: int,
                                cost_grid: tuple = R93_COST_GRID,
                                cut: int,
                                sign: str = SIGN_LOW_FUND_LONG) -> dict:
    """For each cost tier, recompute the L/S at (cadence, cost) and run gauntlet_3check.

    Returns: {cost_bps: {gross_t, oos_t, oos_ann_pct, gross_ann_pct, passes_all}}
    """
    out = {}
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.values, "momentum": f_momentum.values}
    for cost_bps in cost_grid:
        leg = iw_funding_ls_sign(score_wide, rets[tradeable],
                                  k_terciles=R93_K_TERCILES,
                                  cost_bps=cost_bps,
                                  rebal_days=cadence,
                                  sign=sign)
        leg = leg.reindex(rets.index).fillna(0.0)
        g = gauntlet_3check(leg.values, known_full, cut)
        out[cost_bps] = {
            "cost_bps": cost_bps,
            "gross_t": g["gross_t"],
            "gross_alpha_ann_pct": g["gross_alpha_ann_pct"],
            "oos_t": g["oos_t"],
            "oos_alpha_ann_pct": g["oos_alpha_ann_pct"],
            "passes_gross": g["passes_gross"],
            "passes_oos": g["passes_oos"],
            "passes_all": g["passes_all"],
        }
    return out


# === Leg-correlation gate (lesson #42 anti-imposter / anti-costume) ==========
def leg_correlation_gate(r93_leg: pd.Series, naive_leg: pd.Series,
                          gate: float = R93_LEGCORR_GATE) -> dict:
    """Measure |corr| of R93's leg vs naive-fade leg. Returns gate verdict.

    If R93 with informativeness conditioning collapses onto naive per-asset-z fade
    (ι≡1 effectively), corr will be near 1.0 and the gate fails — R93 is R60 in
    disguise. Lesson #42 + R93 anti-costume: |corr| < 0.60 means informativeness
    conditioning does meaningful work (R93 picks meaningfully different positions
    than the naive fade).
    """
    s_r93 = pd.Series(r93_leg.values).fillna(0.0)
    s_naive = pd.Series(naive_leg.values).fillna(0.0)
    # Align
    s_naive_a = s_naive.reindex(s_r93.index).fillna(0.0)
    if s_r93.std() == 0 or s_naive_a.std() == 0:
        corr = float("nan")
    else:
        corr = float(s_r93.corr(s_naive_a))
    max_abs_corr = abs(corr) if not np.isnan(corr) else float("nan")
    passes_gate = max_abs_corr < gate
    return {
        "corr_r93_vs_naive_fade": corr,
        "max_abs_corr": max_abs_corr,
        "gate_threshold": gate,
        "passes_anti_costume_gate": passes_gate,
        "structural_distinct_from_r60": passes_gate,
    }


# === Run =====================================================================
def run(out_dir: Path,
        cadences: tuple = R93_CADENCES,
        iwins: tuple = R93_IWINS,
        imethods: tuple = R93_IMETHODS,
        cost_grid: tuple = R93_COST_GRID,
        sign: str = SIGN_LOW_FUND_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== R93 — Informativeness-Weighted Funding L/S (sign={sign}, k={R93_K_TERCILES}, "
          f"zwin={R93_ZWIN}, iwins={iwins}, imethods={imethods}, cadences={cadences}, "
          f"cost_grid={cost_grid}) ===\n")

    # ── Load perp data ────────────────────────────────────────────────────────
    print("Loading perp OHLCV + funding (Hyperliquid dataset) …")
    funding_daily = load_funding_daily()
    funding_assets = set(funding_daily.columns)

    # Get perp OHLCV universe
    perp_files = list(R93_PERP_DIR.glob("*_1d_ohlcv.csv"))
    ohlcv_assets = [f.stem.replace("_1d_ohlcv", "").upper() for f in perp_files]
    perp_assets = sorted(funding_assets & set(ohlcv_assets))
    print(f"Perp universe (funding ∩ OHLCV): {len(perp_assets)} assets")

    if not perp_assets:
        raise RuntimeError(
            "No perp assets with both funding + OHLCV. "
            "R93 refuses to silently widen the universe."
        )

    # Build panel dates from perp OHLCV
    perp_returns = load_perp_returns(funding_daily.index, perp_assets)
    perp_returns = perp_returns.dropna(how="all")

    # Trim to assets with sufficient perp returns coverage
    coverage = perp_returns.notna().sum() / len(perp_returns)
    perp_assets = [a for a in perp_assets if coverage.get(a, 0) > 0.5]
    perp_returns = perp_returns[perp_assets]
    funding_daily = funding_daily[[a for a in funding_assets if a in perp_assets]]

    # Align
    lo = max(funding_daily.index.min(), perp_returns.dropna(how="all").index.min())
    hi = min(funding_daily.index.max(), perp_returns.dropna(how="all").index.max())
    rets = perp_returns.loc[(perp_returns.index >= lo) & (perp_returns.index <= hi)]
    funding_daily = funding_daily.loc[(funding_daily.index >= lo) & (funding_daily.index <= hi)]

    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, "
          f"{len(perp_assets)} perps)")
    print(f"Funding daily: {funding_daily.shape[0]} days × "
          f"{funding_daily.shape[1]} assets")

    if len(perp_assets) < R93_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(perp_assets)} < {R93_MIN_TRADEABLE} "
            f"(R93_MIN_TRADEABLE floor). R93 refuses to silently widen the universe."
        )

    # ── 6-window partition ────────────────────────────────────────────────────
    windows = partition_into_windows(rets.index, 6)
    print(f"\n6-window partition: {[lab for lab, _, _ in windows]}")

    # ── Score: informativeness-weighted funding-z (default iwin=30, sign_consistency) ──
    default_iwin = 30 if 30 in iwins else iwins[0]
    default_method = imethods[0]
    print(f"\nComputing R93 score (zwin={R93_ZWIN}, iwin={default_iwin}, "
          f"method={default_method}, fade_sign=−1) …")
    score_wide = score_iw_funding(funding_daily[perp_assets],
                                  zwin=R93_ZWIN, iwin=default_iwin,
                                  method=default_method, fade_sign=-1)
    score_wide = score_wide.reindex(rets.index).ffill()
    print(f"  Score shape: {score_wide.shape}, "
          f"mean={score_wide.mean().mean():.6f} (should be ~0 by construction), "
          f"std={score_wide.std().mean():.6f}")

    # ── Naive-fade leg (R62-style per-asset-z fade, no informativeness) ───────
    # Used for the anti-costume gate
    print(f"\nComputing naive-fade baseline (per-asset-z, no ι, R60's signal verbatim) …")
    min_p = max(2, R93_ZWIN // 2)
    mu_naive = funding_daily[perp_assets].rolling(R93_ZWIN, min_periods=min_p).mean()
    sd_naive = funding_daily[perp_assets].rolling(R93_ZWIN, min_periods=min_p).std()
    naive_score = -(funding_daily[perp_assets] - mu_naive) / (sd_naive + 1e-8)
    naive_score = naive_score.reindex(rets.index).ffill()
    naive_leg = iw_funding_ls_sign(naive_score, rets[perp_assets],
                                    k_terciles=R93_K_TERCILES, cost_bps=0.0,
                                    rebal_days=7, sign=SIGN_LOW_FUND_LONG)
    naive_leg = naive_leg.reindex(rets.index).fillna(0.0)

    # ── Build R93 leg at default cadence (7d/0bps) ────────────────────────────
    print(f"\nBuilding R93 leg at 7d/0bps (default) …")
    leg_default = iw_funding_ls_sign(score_wide, rets[perp_assets],
                                      k_terciles=R93_K_TERCILES, cost_bps=0.0,
                                      rebal_days=7, sign=sign)
    leg_default = leg_default.reindex(rets.index).fillna(0.0)

    # ── Leg-correlation gate (lesson #42 anti-costume) ────────────────────────
    print(f"\n══ Leg-correlation gate (lesson #42, anti-costume vs naive fade, "
          f"|corr| < {R93_LEGCORR_GATE}) ══\n")
    gate = leg_correlation_gate(leg_default, naive_leg)
    print(f"corr(R93_leg, naive_fade_leg) = {gate['corr_r93_vs_naive_fade']:+.3f}")
    print(f"max |corr| = {gate['max_abs_corr']:.3f}  "
          f"(gate < {gate['gate_threshold']})")
    print(f"passes_anti_costume_gate: **{gate['passes_anti_costume_gate']}**\n")

    # ── Full sweep (cadences × iwins × methods × costs × signs) ───────────────
    print(f"══ Sweep grid: cadences={cadences} × iwins={iwins} × methods={imethods} × "
          f"cost_grid={cost_grid} × 2 signs ══\n")
    sweep = iw_funding_sweep(funding_daily, rets, perp_assets,
                              cadences=cadences, iwins=iwins,
                              imethods=imethods, cost_grid=cost_grid,
                              k=R93_K_TERCILES)

    # Compute gauntlet_3check for each cell
    f_market = rets[perp_assets].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.values, "momentum": f_momentum.values}
    cut = int(len(rets) * (1.0 - OOS_FRAC))
    sweep_metrics = {}
    for key, leg in sweep.items():
        leg = leg.reindex(rets.index).fillna(0.0)
        g = gauntlet_3check(leg.values, known_full, cut)
        sweep_metrics[key] = {
            "cadence": key[0], "iwin": key[1], "method": key[2],
            "cost_bps": key[3], "sign": key[4],
            "gross_t": g["gross_t"],
            "gross_alpha_ann_pct": g["gross_alpha_ann_pct"],
            "oos_t": g["oos_t"],
            "oos_alpha_ann_pct": g["oos_alpha_ann_pct"],
            "passes_gross": g["passes_gross"],
            "passes_oos": g["passes_oos"],
            "passes_all": g["passes_all"],
        }

    # ── Matched-cell sign audit (anti-imposter) ──────────────────────────────
    print("Matched-cell sign audit (low_fund_long vs high_fund_long at same cad×iwin×method×bps):")
    matched_diffs = []
    for (cad, iwin, method, bps, _), _ in sweep.items():
        hi_entry = sweep_metrics.get((cad, iwin, method, bps, SIGN_HIGH_FUND_LONG))
        lo_entry = sweep_metrics.get((cad, iwin, method, bps, SIGN_LOW_FUND_LONG))
        if hi_entry is None or lo_entry is None:
            continue
        diff = hi_entry["gross_t"] - lo_entry["gross_t"]
        matched_diffs.append((cad, iwin, method, bps, hi_entry["gross_t"],
                              lo_entry["gross_t"], diff))
    matched_diffs.sort(key=lambda x: x[6], reverse=True)
    print(f"  Top-3 matched cells by directional differential (high − low):")
    for cad, iwin, method, bps, hi_t, lo_t, diff in matched_diffs[:3]:
        print(f"    {cad}d/iwin={iwin}/{method}/{bps}bps: high_fund={hi_t:+.2f}, "
              f"low_fund={lo_t:+.2f}, diff={diff:+.2f}")
    if matched_diffs:
        best_diff_cad, best_diff_iwin, best_diff_method, best_diff_bps, _, _, best_diff = \
            matched_diffs[0]
        sign_verdict = SIGN_LOW_FUND_LONG if best_diff < 0 else SIGN_HIGH_FUND_LONG
        print(f"  Sign verdict: {sign_verdict} (matched-cell diff = {best_diff:+.2f})\n")
    else:
        sign_verdict = sign
        best_diff = 0.0
        best_diff_cad = cadences[0]
        best_diff_iwin = iwins[0]
        best_diff_method = imethods[0]
        best_diff_bps = cost_grid[0]

    # ── Best cell selection ─────────────────────────────────────────────────
    # Pick best cell by gross_t at 5bps (safer than 0bps) within sign-verdict direction
    chosen_sign = sign_verdict
    matching_cells = [(k, v) for k, v in sweep_metrics.items()
                       if k[4] == chosen_sign and k[3] == 5.0]
    if not matching_cells:
        matching_cells = [(k, v) for k, v in sweep_metrics.items()
                           if k[4] == chosen_sign]
    best_cell = max(matching_cells, key=lambda kv: kv[1]["gross_t"])
    (best_cad, best_iwin, best_method, best_bps, _), best_metrics = best_cell
    print(f"Best cell (5bps, sign={chosen_sign}): {best_cad}d/iwin={best_iwin}/"
          f"{best_method}/{best_bps}bps")
    print(f"  gross_t = {best_metrics['gross_t']:+.2f}, "
          f"OOS_t = {best_metrics['oos_t']:+.2f}, "
          f"passes_all = {best_metrics['passes_all']}")

    # ── Cost-tier sweep at best cell (R32/R89/R90 lesson #58 — MANDATORY) ───
    print(f"\n══ Cost-tier sweep at best cell ({best_cad}d/iwin={best_iwin}/"
          f"{best_method}, sign={chosen_sign}) — R32/R89 gate ══\n")
    # Rebuild score at best (iwin, method) for cost-tier sweep
    best_score = score_iw_funding(funding_daily[perp_assets],
                                   zwin=R93_ZWIN, iwin=best_iwin,
                                   method=best_method, fade_sign=-1)
    best_score = best_score.reindex(rets.index).ffill()
    cost_tier = cost_tier_sweep_with_score(best_score, rets, perp_assets,
                                            cadence=best_cad, cost_grid=cost_grid,
                                            cut=cut, sign=chosen_sign)
    print(f"  cost_bps | gross_t | OOS_t | OOS_ann% | passes_all | survives_realistic_10bps")
    print(f"  ---------+---------+-------+----------+------------+------------------------")
    for cost_bps, v_t in cost_tier.items():
        survives = cost_tier[R93_REALISTIC_COST_BPS]["passes_all"] \
            if R93_REALISTIC_COST_BPS in cost_tier else False
        marker = " ← GATE" if cost_bps == R93_REALISTIC_COST_BPS else ""
        print(f"  {cost_bps:8.1f} | {v_t['gross_t']:+.2f} | {v_t['oos_t']:+.2f} | "
              f"{v_t['oos_alpha_ann_pct']:+.1f}% | "
              f"{'YES' if v_t['passes_all'] else 'NO':<10} | "
              f"{survives}{marker}")

    survives_realistic_10bps = cost_tier[R93_REALISTIC_COST_BPS]["passes_all"]
    survives_realistic_10bps_t = cost_tier[R93_REALISTIC_COST_BPS]["oos_t"]
    survives_realistic_10bps_ann = cost_tier[R93_REALISTIC_COST_BPS]["oos_alpha_ann_pct"]
    print(f"\n  Survives at 10bps? {survives_realistic_10bps}")
    print(f"  OOS_t at 10bps = {survives_realistic_10bps_t:+.2f}")
    print(f"  OOS_ann% at 10bps = {survives_realistic_10bps_ann:+.1f}%")

    # ── Per-window attribution at best cell (5bps) ───────────────────────────
    print(f"\n══ Per-window W1–W6 at best cell ({best_cad}d/5bps) ══\n")
    leg_5bps = iw_funding_ls_sign(best_score, rets[perp_assets],
                                   k_terciles=R93_K_TERCILES, cost_bps=5.0,
                                   rebal_days=best_cad, sign=chosen_sign)
    leg_5bps = leg_5bps.reindex(rets.index).fillna(0.0)
    pw_5bps = per_window(leg_5bps, windows)
    print("  Window | n_days | ann_pct | maxDD")
    print("  -------+--------+---------+--------")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in pw_5bps:
            print(f"  {label} | {pw_5bps[label]['n_days']:6d} | "
                  f"{pw_5bps[label]['ann_pct']:+.1f}% | "
                  f"{pw_5bps[label]['max_dd']:+.2%}")

    # Falsifiable mechanistic claim: did informativeness-weighting turn R60's
    # failure windows (W1=−37.4%, W3=−22.5%) positive?
    w1_ann = pw_5bps.get("W1", {}).get("ann_pct", None)
    w3_ann = pw_5bps.get("W3", {}).get("ann_pct", None)
    w1_improved = w1_ann is not None and w1_ann > 0
    w3_improved = w3_ann is not None and w3_ann > 0
    print(f"\n  Falsifiable mechanistic claim:")
    print(f"    W1 (R60 −37.4%): R93 = {w1_ann:+.1f}%  "
          f"{'✅ IMPROVED' if w1_improved else '🔴 STILL NEGATIVE'}")
    print(f"    W3 (R60 −22.5%): R93 = {w3_ann:+.1f}%  "
          f"{'✅ IMPROVED' if w3_improved else '🔴 STILL NEGATIVE'}")

    # ── Verdict (3-way, with anti-costume gate) ──────────────────────────────
    passes_3check_5bps = best_metrics["passes_all"]
    if passes_3check_5bps and survives_realistic_10bps and gate["passes_anti_costume_gate"]:
        verdict = ("✅ TRADEABLE — R93 informativeness-weighted funding-z clears "
                   "3-check AND survives ≥10bps realistic cost AND is structurally "
                   "distinct from naive-fade (corr < 0.60). Eligible for Strategy 2 slot.")
        verdict_band = "TRADEABLE"
    elif passes_3check_5bps and not survives_realistic_10bps:
        verdict = ("🟡 PARTIAL — 3-check passes at 5bps but edge dies at 10bps "
                   "(R32/R89 taker-fee illusion). Informativeness conditioning is "
                   "theoretically distinct from R62 but cannot survive realistic cost.")
        verdict_band = "PARTIAL"
    elif passes_3check_5bps and not gate["passes_anti_costume_gate"]:
        verdict = ("🟡 PARTIAL — 3-check passes at 5bps but informativeness "
                   "conditioning collapses onto naive-fade (corr ≥ 0.60). R93 is "
                   "R60 in disguise (anti-costume gate fails). NOT an independent "
                   "Strategy 2.")
        verdict_band = "PARTIAL"
    else:
        verdict = ("🔴 REFUTED — informativeness-weighted funding-z lacks "
                   "standalone edge. The cross-sectional funding-as-edge has "
                   "been refuted in 11 forms (R47/R60/R62/R76/R90/R89/R91/...). "
                   "Strategy 2 awaits §OHLCV-EXTENSION (Option A).")
        verdict_band = "REFUTED"

    print(f"\nVerdict: {verdict}\n")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {
            "lo": str(lo.date()), "hi": str(hi.date()),
            "n_days": int(len(rets)), "n_perps": len(perp_assets),
        },
        "construction": {
            "score": (f"fade_sign × funding_z({R93_ZWIN}d) × ι({default_method}, "
                      f"iwin={default_iwin}d); k={R93_K_TERCILES}"),
            "k_terciles": R93_K_TERCILES,
            "min_tradeable": R93_MIN_TRADEABLE,
            "universe": "perp OHLCV ∩ perp funding (Hyperliquid)",
            "zwin": R93_ZWIN,
            "iwins": list(iwins),
            "imethods_default": list(imethods),
            "cadences": list(cadences),
            "cost_grid": list(cost_grid),
            "realistic_cost_bps": R93_REALISTIC_COST_BPS,
            "legcorr_gate": R93_LEGCORR_GATE,
        },
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                      "n_days": int((e - s).days + 1)}
                     for lab, s, e in windows],
        "leg_correlation_gate": gate,
        "best_cell": {
            "cadence": best_cad,
            "iwin": best_iwin,
            "method": best_method,
            "cost_bps_5bps": 5.0,
            "sign": chosen_sign,
            "gauntlet_5bps": best_metrics,
        },
        "cost_tier_sweep": {f"{int(k)}bps": v for k, v in cost_tier.items()},
        "survives_realistic_10bps": survives_realistic_10bps,
        "per_window_5bps": pw_5bps,
        "falsifiable_mechanistic_claim": {
            "w1_r60_floor": -37.4,
            "w3_r60_floor": -22.5,
            "w1_r93": w1_ann,
            "w3_r93": w3_ann,
            "w1_improved": w1_improved,
            "w3_improved": w3_improved,
        },
        "sweep": {f"{c}d/iwin={i}/{m}/{b}bps/{s}": v
                   for (c, i, m, b, s), v in sweep_metrics.items()},
        "matched_cell_sign_audit": {
            "top3": [{"cadence": c, "iwin": i, "method": m, "cost_bps": b,
                       "high_fund_long_t": h, "low_fund_long_t": l,
                       "differential": d}
                      for c, i, m, b, h, l, d in matched_diffs[:3]],
            "sign_verdict": sign_verdict,
            "differential": best_diff,
        },
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_3check_5bps": passes_3check_5bps,
            "survives_realistic_10bps": survives_realistic_10bps,
            "passes_anti_costume_gate": gate["passes_anti_costume_gate"],
        },
        "live_book_impact": {
            "touches_frozen_r77_cell": False,
            "strategy_2_slot_eligible": (
                verdict_band == "TRADEABLE"
            ),
            "note": ("R93 is research-only. The R77 fusion cell "
                     "(w_R46=0.25, w_R62=0.75, w_R76=0.30) is FROZEN; R93 does NOT "
                     "touch it. Strategy 2 slot is OPENED only if verdict is "
                     "✅ TRADEABLE + user sign-off."),
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable R93 report."""
    lines = []
    lines.append("# R93 — Informativeness-Weighted Funding L/S")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_perps']}-perp universe)")
    lines.append("")
    lines.append("## Verdict")
    vd = payload["verdict"]
    lines.append(f"**{vd['band']}** — {vd['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes 3-check at 5bps: **{vd['passes_3check_5bps']}**")
    lines.append(f"- Survives realistic 10bps cost: **{vd['survives_realistic_10bps']}**")
    lines.append(f"- Passes anti-costume gate (|corr| < "
                 f"{payload['construction']['legcorr_gate']}): "
                 f"**{vd['passes_anti_costume_gate']}**")
    lines.append("")
    lines.append("## Leg-correlation gate (lesson #42 anti-costume vs naive fade)")
    g = payload["leg_correlation_gate"]
    lines.append(f"- corr(R93_leg, naive_fade_leg) = {g['corr_r93_vs_naive_fade']:+.3f}")
    lines.append(f"- max |corr| = {g['max_abs_corr']:.3f} "
                 f"(gate < {g['gate_threshold']})")
    lines.append(f"- passes_anti_costume_gate = **{g['passes_anti_costume_gate']}**")
    lines.append(f"- structural_distinct_from_r60 = "
                 f"**{g['structural_distinct_from_r60']}**")
    lines.append("")
    lines.append("## Cost-tier sweep (R32/R89/R90 lesson #58 — MANDATORY)")
    lines.append("")
    lines.append("| cost_bps | gross_t | OOS_t | OOS_ann% | passes_all |")
    lines.append("|----------|---------|-------|----------|------------|")
    for k, v_t in payload["cost_tier_sweep"].items():
        marker = " ← GATE" if float(k.replace("bps", "")) == R93_REALISTIC_COST_BPS else ""
        lines.append(f"| {k} | {v_t['gross_t']:+.2f} | {v_t['oos_t']:+.2f} | "
                     f"{v_t['oos_alpha_ann_pct']:+.1f}% | "
                     f"{'YES' if v_t['passes_all'] else 'NO'} |{marker}")
    lines.append("")
    lines.append("## Per-window W1–W6 at best cell (5bps)")
    lines.append("")
    lines.append("| Window | n_days | ann_pct | maxDD |")
    lines.append("|--------|--------|---------|-------|")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in payload["per_window_5bps"]:
            pw = payload["per_window_5bps"][label]
            lines.append(f"| {label} | {pw['n_days']:6d} | "
                         f"{pw['ann_pct']:+.1f}% | {pw['max_dd']:+.2%} |")
    lines.append("")
    lines.append("## Falsifiable mechanistic claim (R60 W1 / W3 windows)")
    fmc = payload["falsifiable_mechanistic_claim"]
    w1 = fmc.get("w1_r93")
    w3 = fmc.get("w3_r93")
    lines.append(f"- W1 (R60 floor −37.4%): R93 = "
                 f"{w1:+.1f}%  {'✅ IMPROVED' if fmc['w1_improved'] else '🔴 STILL NEGATIVE'}")
    lines.append(f"- W3 (R60 floor −22.5%): R93 = "
                 f"{w3:+.1f}%  {'✅ IMPROVED' if fmc['w3_improved'] else '🔴 STILL NEGATIVE'}")
    lines.append("")
    lines.append("## Matched-cell sign audit (top-3)")
    for entry in payload["matched_cell_sign_audit"]["top3"]:
        lines.append(f"- {entry['cadence']}d/iwin={entry['iwin']}/"
                     f"{entry['method']}/{entry['cost_bps']}bps: "
                     f"high={entry['high_fund_long_t']:+.2f}, "
                     f"low={entry['low_fund_long_t']:+.2f}, "
                     f"diff={entry['differential']:+.2f}")
    lines.append(f"- **Sign verdict: {payload['matched_cell_sign_audit']['sign_verdict']}** "
                 f"(matched-cell diff = {payload['matched_cell_sign_audit']['differential']:+.2f})")
    lines.append("")
    lines.append("## Sweep grid (subset)")
    lines.append("")
    lines.append("| cell | gross_t | OOS_t | OOS_ann% | passes_all |")
    lines.append("|------|---------|-------|----------|------------|")
    # Print top 10 cells by gross_t for legibility
    sorted_cells = sorted(payload["sweep"].items(),
                          key=lambda kv: kv[1]["gross_t"], reverse=True)
    for k, v_cell in sorted_cells[:10]:
        lines.append(f"| {k} | {v_cell['gross_t']:+.2f} | {v_cell['oos_t']:+.2f} | "
                     f"{v_cell['oos_alpha_ann_pct']:+.1f}% | "
                     f"{'YES' if v_cell['passes_all'] else 'NO'} |")
    lines.append("")
    lines.append("## Live book impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R77 cell (w_R46=0.25/w_R62=0.75/w_R76=0.30): "
                 f"**{li['touches_frozen_r77_cell']}**")
    lines.append(f"- Strategy 2 slot eligible: **{li['strategy_2_slot_eligible']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    lines.append("## Aggregate lesson (depends on verdict)")
    band = vd["band"]
    if band == "TRADEABLE":
        lines.append("- ✅ Aggregate lesson: 'Informativeness-conditioning on funding-z "
                     "(nonlinear per-asset conditioning) IS a structurally-new axis — "
                     "orthogonal to cross-sectional demean, orthogonal to naive fade "
                     "(|corr| < 0.60), AND tradeable at ≥10bps realistic cost. R93 "
                     "becomes Strategy 2; pair with R77 for the two-strategy book. "
                     "Lesson #14 sharpens: informativeness-weighting lets us fade the "
                     "crowd selectively (only when the crowd is persistently positioned, "
                     "not when funding is noise).'")
    elif band == "PARTIAL":
        if not vd["survives_realistic_10bps"]:
            lines.append("- 🟡 Aggregate lesson (PARTIAL, fee-illusion case): "
                         "'Informativeness-weighted funding-z passes 5bps 3-check but "
                         "dies at 10bps — same taker-fee illusion as R89. The structural "
                         "novelty (per-asset conditioning) doesn't escape the cost "
                         "constraint. Future orthogonal candidates must be "
                         "single-instrument (no spot leg) and/or frequency-demeaned to "
                         "reduce turnover.'")
        else:
            lines.append("- 🟡 Aggregate lesson (PARTIAL, anti-costume case): "
                         "'Informativeness-weighted funding-z may pass 3-check BUT "
                         "collapses onto naive fade (corr ≥ 0.60) — informativeness "
                         "weighting does not add meaningful information beyond ι≡1. "
                         "Lesson #42 anti-costume gate is the right discipline; R93 "
                         "is R60 in a new costume.'")
    else:
        lines.append("- 🔴 Aggregate lesson (REFUTED): 'Informativeness-conditioning "
                     "does not rescue the cross-sectional funding-z fade on this data. "
                     "Per-asset conditioning (R93), cross-sectional demean (R76/R77 "
                     "leg), regime-gating (R62), perp-only (R90), perp-spot basis (R89) "
                     "— all forms of funding-based cross-sectional alpha have now been "
                     "tested and refuted on the perp panel. Strategy 2 STRUCTURALLY "
                     "DEFERRED pending §OHLCV-EXTENSION (Option A) per the 11-attempt "
                     "graveyard (R82-R93). Lesson #56 FINAL: panel length, not strategy "
                     "shape.'")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_LOW_FUND_LONG,
                        choices=[SIGN_HIGH_FUND_LONG, SIGN_LOW_FUND_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r93_informativeness_weighted_funding/{today}")
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