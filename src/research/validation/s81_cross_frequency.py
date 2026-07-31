"""
S-81 — Cross-frequency orthogonal candidate #5 (R81).
4h cross-section turnover residual as a STRUCTURALLY DIFFERENT axis from R76/R78/R79/S-80.

Per lesson #43 v3 (REFINED 2026-07-24): "Cross-sectional demean of single-class
microstructure axes (funding, momentum, vol, turnover) MOSTLY LACK EDGE. STOP running
'cross-sectional demean of X' for new X; R76 is the 1-in-4 outlier, not the rule."

S-81 reaches for a STRUCTURALLY DIFFERENT axis: **cross-frequency**. Instead of
demeaning a daily panel, S-81 demeans at a 4h frequency. The hypothesis: 4h
cross-section captures microstructure noise that daily aggregates miss, while
washing out sub-4h noise that the 1h cross-section would carry.

S-81 design:
  · Data: hourly OHLCV parquets → 4h bars (close, dollar_volume).
  · Score: 30d rolling-mean dollar-volume cross-section demean, computed at 4h frequency.
  · k_terciles = 3.
  · Rebalance cadence: 4h bar (every 4h).
  · 4h returns → factor returns → aggregate to daily for the 3-check gauntlet.
  · 4-leg gate (R46/R62/R76/R78 — daily legs, compared against S-81's daily-aggregated P&L).
  · Both signs run; matched-cell sign verdict.

Why "cross-frequency" might work where cross-sectional didn't:
  - 4h is a different statistical population: the daily panel averages out
    microstructure noise; the 4h panel exposes it.
  - S-80 (daily turnover) and S-81 (4h turnover) are mathematically different scores
    even though both are cross-sectional demeans of dollar-volume.
  - The 4h panel has 6× the data points, so the L/S has more rebalance events
    to harvest alpha from.

Why "cross-frequency" might NOT work:
  - Roll mechanics: the 30d rolling mean at 4h frequency = 180 bars. The
    volume signal at this granularity is heavily smoothed.
  - Cost: 4h rebalance (6× per day) has higher turnover than daily.
  - The dominant signal at 4h is still microstructure noise.

Anti-imposter:
  - S-81 is STRUCTURALLY DIFFERENT from R76/R78/R79/S-80 (different time scale).
  - Pre-test leg-correlation gate is MANDATORY (lesson #42). Don't run the fusion
    sweep until the gate clears.
  - The R77 fusion-cell (R46+R62+R76 at w_R46=0.25, w_R62=0.75, w_R76=0.30) is
    FROZEN. S-81 does NOT touch it.
  - S-81 result informs a future S-82 candidate (S-81 as 4th fusion contribution)
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
from src.research.validation.r75_hourly_so_quintile import (
    hourly_ls, load_hourly_returns,
)


# === Constants ================================================================
OOS_FRAC = 0.30
NW_LAGS = 6
PERIODS_PER_YEAR = 365 * 24 / 4   # 4h bars per year: 2190

# S-81-specific
S81_K_TERCILES = 3                    # R46/R76/S-80 standard
S81_MIN_TRADEABLE = 12                # same floor
S81_ORTHOGONALITY_GATE = 0.30         # lesson #42 — max |corr| vs existing legs
S81_FREQ = "4h"                       # cross-frequency
S81_TONUS_LOOKBACK_BARS = 30 * 6      # 30 days × 6 4h-bars/day = 180 bars
S81_TONUS_MIN_OBS = 5 * 6             # 5 days × 6 = 30 bars (sparse-data tolerance)

# Sign constants
SIGN_HIGH_FREQ_LONG = "high_freq_long"
SIGN_LOW_FREQ_LONG = "low_freq_long"
_VALID_SIGNS = {SIGN_HIGH_FREQ_LONG, SIGN_LOW_FREQ_LONG}


# === Load: 4h dollar volume + 4h close returns ===============================
def load_4h_panel(ohlcv_dir: Path = OHLCV_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resample hourly OHLCV → 4h bars; return (4h-returns, 4h-dollar-volume).

    4h returns: pct_change of 4h-close, by asset.
    4h dollar-volume: Σ(hourly volume × hourly close) per 4h bar, by asset.

    Returns:
      rets_4h: 4h × asset return matrix (NaN where close is missing).
      dv_4h: 4h × asset dollar-volume matrix.
    """
    rets_dict = {}
    dv_dict = {}
    for f in sorted(ohlcv_dir.glob("*.parquet")):
        sym = f.stem
        df = pd.read_parquet(f)
        if "timestamp" not in df.columns:
            continue
        if "volume" not in df.columns or "close" not in df.columns:
            continue
        ts = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        df = pd.DataFrame({
            "timestamp": ts,
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df["volume"], errors="coerce"),
        }).dropna()
        if df.empty:
            continue
        df = df.set_index("timestamp").sort_index()
        # 4h aggregation: close=last, volume=sum, then dollar_volume = vol × close
        agg = df.resample("4h").agg({"close": "last", "volume": "sum"})
        agg["dollar_volume"] = agg["close"] * agg["volume"]
        agg = agg.dropna(subset=["close", "dollar_volume"])
        if agg.empty:
            continue
        rets_dict[sym] = agg["close"].pct_change()
        dv_dict[sym] = agg["dollar_volume"]
    rets_4h = pd.DataFrame(rets_dict).sort_index()
    dv_4h = pd.DataFrame(dv_dict).sort_index()
    return rets_4h, dv_4h


# === Score: 4h turnover residual ==============================================
def score_4h_turnover_residual(dv_4h: pd.DataFrame, tradeable: list,
                               lookback_bars: int = S81_TONUS_LOOKBACK_BARS,
                               min_obs: int = S81_TONUS_MIN_OBS) -> pd.DataFrame:
    """Cross-sectionally demeaned trailing-N-bar dollar-volume mean at 4h frequency.

    dv_30d_4h[t, a] = mean of dollar_volume over the trailing `lookback_bars` 4h-bars.
    freq_residual[t, a] = dv_30d_4h[t, a] − mean_a(dv_30d_4h[t, a]).

    Cross-sectional demean removes the universe's common activity regime at 4h
    frequency. The residual is RELATIVE 4h turnover — which assets are running
    HOTTER than the universe on this 4h bar.

    NaN behavior (I1, from §ARCHITECTURE):
      - Warmup rows (< min_periods): NaN, NOT zero.
      - Insufficient obs in trailing window for an asset at a given t: NaN, NOT 0.
      - Cross-section demean uses dropna(how="any"): rows where ANY asset is
        NaN are excluded from the mean computation.

    Returns wide DataFrame (4h-bar × asset) on the tradeable subset.
    """
    sub = dv_4h[tradeable].copy()
    dusd = sub.rolling(lookback_bars, min_periods=min_obs).mean()
    fully_observed = dusd.dropna(how="any")
    demeaned_full = fully_observed.subtract(fully_observed.mean(axis=1), axis=0)
    residual = demeaned_full.reindex(dusd.index)
    return residual


# === 4h L/S core (reuses R75's hourly_ls as the engine) =====================
def freq_residual_ls(score_wide: pd.DataFrame, rets_4h: pd.DataFrame,
                      k: int = S81_K_TERCILES, cost_bps: float = 0.0,
                      rebal_bars: int = 1,
                      sign: str = SIGN_HIGH_FREQ_LONG) -> pd.Series:
    """Long high-frequency-residual / short low-frequency-residual at 4h cadence.

    Reuses R75's hourly_ls as the L/S engine — the score function differs
    (4h turnover residual vs pillar_S ranking) but the L/S logic is the same:
    long top tercile, short bottom tercile, optional sign flip, next-bar PIT lag.
    """
    if sign not in _VALID_SIGNS:
        raise ValueError(f"sign must be one of {_VALID_SIGNS}, got {sign!r}")
    flipped = -score_wide if sign == SIGN_LOW_FREQ_LONG else score_wide
    # R75's hourly_ls assumes score is hourly-indexed; our 4h score is 4h-indexed.
    # Convert cadence: rebal_bars=1 means every 4h-bar; set cadence_hours=4 to
    # match the 4h grid (R75's cadence_hours operates on bars, not hours).
    return hourly_ls(flipped, rets_4h, cadence_hours=rebal_bars,
                     cost_bps=cost_bps, k=k)


# === Run =====================================================================
def run(out_dir: Path,
        cost_bps_grid: tuple = (0.0, 5.0, 10.0),
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS,
        zwin: int = 30,
        sign: str = SIGN_HIGH_FREQ_LONG) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"=== S-81 — 4h cross-frequency turnover residual L/S "
          f"(sign={sign}, k={S81_K_TERCILES}) ===\n")

    # ── Load daily panels (R76/S-80 parity) ──────────────────────────────────
    cis_long = load_cis_history_wide()
    rets_daily = load_daily_returns()
    lo = max(cis_long["date"].min(), rets_daily.index.min())
    hi = min(cis_long["date"].max(), rets_daily.index.max())
    rets_daily = rets_daily.loc[(rets_daily.index >= lo) & (rets_daily.index <= hi)]
    tradeable_full = sorted(set(cis_long["asset"]) & set(rets_daily.columns))
    print(f"Daily panel: {lo.date()} → {hi.date()} ({len(rets_daily)} days, "
          f"{len(tradeable_full)} CIS ∩ OHLCV assets)")

    funding_daily = load_funding_daily(assets=tradeable_full)
    funding_assets = sorted(set(tradeable_full) & set(funding_daily.columns))
    print(f"Funding daily: {funding_daily.shape[0]} days × "
          f"{funding_daily.shape[1]} assets ({len(funding_assets)} matched)")

    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets_daily = rets_daily.loc[(rets_daily.index >= f_lo) & (rets_daily.index <= f_hi)]
    print(f"Aligned daily panel: {rets_daily.index.min().date()} → "
          f"{rets_daily.index.max().date()} ({len(rets_daily)} days)\n")

    tradeable = funding_assets
    print(f"Strict intersection universe: {len(tradeable)} assets")
    if len(tradeable) < S81_MIN_TRADEABLE:
        raise RuntimeError(
            f"Universe too small: {len(tradeable)} < {S81_MIN_TRADEABLE} "
            f"(S81_MIN_TRADEABLE floor). S-81 refuses to silently widen.")

    # ── Load 4h panel and compute 4h turnover residual ───────────────────────
    print("Loading 4h OHLCV panel (resample hourly → 4h) …")
    rets_4h, dv_4h = load_4h_panel()
    four_h_assets = sorted(set(tradeable) & set(rets_4h.columns) & set(dv_4h.columns))
    print(f"  4h rets: {rets_4h.shape[0]} bars × {rets_4h.shape[1]} assets "
          f"({len(four_h_assets)} matched)")
    if len(four_h_assets) < S81_MIN_TRADEABLE:
        raise RuntimeError(
            f"4h universe too small: {len(four_h_assets)} < {S81_MIN_TRADEABLE}. "
            f"S-81 refuses to silently widen.")

    print("Computing 4h turnover residual (180-bar rolling-mean dollar-volume "
          "cross-sectional demean) …")
    score_freq_wide = score_4h_turnover_residual(dv_4h, four_h_assets)
    score_freq_wide = score_freq_wide.reindex(rets_4h.index).ffill()
    print(f"  Score shape: {score_freq_wide.shape}, "
          f"mean={score_freq_wide.mean().mean():.6f} (should be ~0 by construction), "
          f"std={score_freq_wide.std().mean():.6f}")

    # ── Build S-81 leg at 4h default (every 4h bar) ─────────────────────────
    leg_4h = freq_residual_ls(score_freq_wide, rets_4h[four_h_assets],
                               k=S81_K_TERCILES, cost_bps=0.0,
                               rebal_bars=1, sign=sign)
    # Aggregate 4h factor returns to daily by sum
    leg_s81_daily = leg_4h.resample("1D").sum().reindex(rets_daily.index).fillna(0.0)

    # ── 6-window partition on daily index ────────────────────────────────────
    windows = partition_into_windows(rets_daily.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets_daily.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets_daily.index >= s) & (rets_daily.index <= e)] = True

    # ── Reproduce R46 + R62 + R76 + R78 legs (daily, gate prerequisites) ─────
    print("\nReproducing R46 leg (pillar_O 5d/5bps on 28-asset) for correlation gate …")
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets_daily, tradeable)

    print("Reproducing R62 leg (fade-the-crowd 21d/0bps gated) for correlation gate …")
    from src.research.validation.funding_crowding_ls import score_funding_zwide
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                       sign="fade_crowd").reindex(rets_daily.index).ffill()
    feats = compute_combined_features(cis_long, rets_daily, tradeable_full, tradeable,
                                       funding_daily)
    feats = feats.reindex(rets_daily.index)
    from src.research.validation.w5_forensics import build_w5_detector
    ks = build_fragility_ks_table(feats, fragile_mask)
    external_cols = [c for c in feats.columns if c in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    det, _ = build_w5_detector(
        feats,
        *fragile_ranges[0] if fragile_ranges else (feats.index[0], feats.index[0]),
        *playable_ranges[0] if playable_ranges else (feats.index[0], feats.index[0]),
        ks, feature_subset=external_cols,
        z_threshold=R62_Z, min_features=R62_MF,
    )
    leg_r62 = build_r62_sleeve_28(score_zwide, rets_daily, tradeable, det)

    print("Reproducing R76 leg (funding residual 5d/0bps) for correlation gate …")
    score_fundres_wide = score_funding_residual(funding_daily, tradeable) \
                                          .reindex(rets_daily.index).ffill()
    leg_r76 = r76_ls(score_fundres_wide, rets_daily[tradeable],
                      k_terciles=S81_K_TERCILES, cost_bps=0.0,
                      rebal_days=5, sign=SIGN_HIGH_FUND_LONG)
    leg_r76 = leg_r76.reindex(rets_daily.index).fillna(0.0)

    print("Reproducing R78 leg (TSMOM-demean 3d/0bps) for correlation gate …")
    score_relmom_wide = score_relative_momentum(rets_daily, tradeable) \
                                              .reindex(rets_daily.index).ffill()
    leg_r78 = r78_ls(score_relmom_wide, rets_daily[tradeable],
                      k_terciles=S81_K_TERCILES, cost_bps=0.0,
                      rebal_days=3, sign=SIGN_HIGH_MOM_LONG)
    leg_r78 = leg_r78.reindex(rets_daily.index).fillna(0.0)

    # ── Known factors + OOS cut (R76/S-80 parity) ─────────────────────────────
    f_market = rets_daily[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets_daily.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets_daily.index).fillna(0.0).values}
    cut = int(len(rets_daily) * (1.0 - OOS_FRAC))

    # ── Leg-correlation gate (lesson #42 anti-imposter) — extended to 4 legs ─
    print("\n══ Leg-correlation gate (lesson #42, |corr| ≲ 0.30 vs R46/R62/R76/R78) ══\n")
    existing_legs = {"r46": leg_r46, "r62": leg_r62, "r76": leg_r76, "r78": leg_r78}
    gate = leg_correlation_gate_n(leg_s81_daily, existing_legs)
    print(f"corr(S-81_leg, R46_leg) = {gate['corr_new_vs_r46']:+.3f}")
    print(f"corr(S-81_leg, R62_leg) = {gate['corr_new_vs_r62']:+.3f}")
    print(f"corr(S-81_leg, R76_leg) = {gate['corr_new_vs_r76']:+.3f}")
    print(f"corr(S-81_leg, R78_leg) = {gate['corr_new_vs_r78']:+.3f}")
    print(f"max |corr| = {gate['max_abs_corr']:.3f}  "
          f"(gate ≤ {gate['gate_threshold']})")
    print(f"passes_orthogonality_gate: **{gate['passes_orthogonality_gate']}**")
    print(f"fusion_candidatable: **{gate['fusion_candidatable']}**\n")

    # ── Per-leg gauntlet (daily-aggregated) ──────────────────────────────────
    g_s81 = gauntlet_3check(leg_s81_daily.values, known_full, cut)
    g_r46 = gauntlet_3check(leg_r46.values, known_full, cut)
    g_r62 = gauntlet_3check(leg_r62.values, known_full, cut)
    g_r76 = gauntlet_3check(leg_r76.values, known_full, cut)
    g_r78 = gauntlet_3check(leg_r78.values, known_full, cut)
    print(f"Leg S-81 (4h→daily, 0bps): gross_t={g_s81['gross_t']:+.2f}, "
          f"OOS_t={g_s81['oos_t']:+.2f}, pass_all={g_s81['passes_all']}")
    print(f"Leg R46: gross_t={g_r46['gross_t']:+.2f}, OOS_t={g_r46['oos_t']:+.2f}")
    print(f"Leg R62: gross_t={g_r62['gross_t']:+.2f}, OOS_t={g_r62['oos_t']:+.2f}")
    print(f"Leg R76: gross_t={g_r76['gross_t']:+.2f}, OOS_t={g_r76['oos_t']:+.2f}")
    print(f"Leg R78: gross_t={g_r78['gross_t']:+.2f}, OOS_t={g_r78['oos_t']:+.2f}\n")

    # ── Sweep 4h bars × costs (both signs; matched-cell sign verdict) ───────
    print(f"══ 4h-bars × cost sweep (signs: {SIGN_HIGH_FREQ_LONG}, {SIGN_LOW_FREQ_LONG}) ══\n")
    sweep_hi = {}
    sweep_lo = {}
    for rebal_bars in (1, 6, 24, 168):  # 4h, 1d, 4d, 28d
        for bps in cost_bps_grid:
            fac_hi_4h = freq_residual_ls(score_freq_wide, rets_4h[four_h_assets],
                                          k=S81_K_TERCILES, cost_bps=bps,
                                          rebal_bars=rebal_bars, sign=SIGN_HIGH_FREQ_LONG)
            fac_hi_daily = fac_hi_4h.resample("1D").sum().reindex(rets_daily.index).fillna(0.0)
            g_hi = gauntlet_3check(fac_hi_daily.values, known_full, cut)
            sweep_hi[(rebal_bars, bps)] = {
                "alpha_t": g_hi["gross_t"], "oos_t": g_hi["oos_t"],
                "passes_gross": g_hi["passes_gross"], "passes_oos": g_hi["passes_oos"],
                "passes_all": g_hi["passes_all"],
            }
            fac_lo_4h = freq_residual_ls(score_freq_wide, rets_4h[four_h_assets],
                                          k=S81_K_TERCILES, cost_bps=bps,
                                          rebal_bars=rebal_bars, sign=SIGN_LOW_FREQ_LONG)
            fac_lo_daily = fac_lo_4h.resample("1D").sum().reindex(rets_daily.index).fillna(0.0)
            g_lo = gauntlet_3check(fac_lo_daily.values, known_full, cut)
            sweep_lo[(rebal_bars, bps)] = {
                "alpha_t": g_lo["gross_t"], "oos_t": g_lo["oos_t"],
                "passes_gross": g_lo["passes_gross"], "passes_oos": g_lo["passes_oos"],
                "passes_all": g_lo["passes_all"],
            }

    # ── Matched-cell sign audit (anti-imposter) ──────────────────────────────
    print("══ Matched-cell sign audit (anti-imposter) ══\n")
    matched_diffs = []
    for rebal_bars in (1, 6, 24, 168):
        for bps in cost_bps_grid:
            hi_entry = sweep_hi[(rebal_bars, bps)]
            lo_entry = sweep_lo[(rebal_bars, bps)]
            diff = hi_entry["alpha_t"] - lo_entry["alpha_t"]
            matched_diffs.append((rebal_bars, bps, diff, hi_entry["alpha_t"], lo_entry["alpha_t"]))
    matched_diffs.sort(key=lambda x: -x[2])
    print("Top-3 matched-cell differentials (sign audit):")
    for rebal_bars, bps, diff, hi_t, lo_t in matched_diffs[:3]:
        print(f"  rebal={rebal_bars:>3}bars bps={bps:>4.1f}: Δ(α_t) = {diff:+.2f} "
              f"(hi={hi_t:+.2f}, lo={lo_t:+.2f})")
    pos_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff > 0)
    neg_count = sum(1 for _, _, diff, _, _ in matched_diffs[:3] if diff < 0)
    sign_verdict = "high_freq_long" if pos_count >= 2 else ("low_freq_long" if neg_count >= 2 else "mixed")
    print(f"Sign verdict (top-3 majority): **{sign_verdict}**\n")

    # ── Sweep summary: best cell by pass + alpha + OOS ───────────────────────
    print("══ Sweep summary (best cell per sign) ══\n")
    viable_hi = [(k, v) for k, v in sweep_hi.items() if v["passes_all"]]
    viable_lo = [(k, v) for k, v in sweep_lo.items() if v["passes_all"]]
    best_hi = max(viable_hi, key=lambda kv: kv[1]["alpha_t"]) if viable_hi else (None, None)
    best_lo = max(viable_lo, key=lambda kv: kv[1]["alpha_t"]) if viable_lo else (None, None)
    if best_hi[0]:
        rebal_bars, bps = best_hi[0]
        v = best_hi[1]
        print(f"Best SIGN_HIGH_FREQ_LONG cell: reb={rebal_bars}bars/{bps}bps, "
              f"α_t={v['alpha_t']:+.2f}, OOS_t={v['oos_t']:+.2f}")
    if best_lo[0]:
        rebal_bars, bps = best_lo[0]
        v = best_lo[1]
        print(f"Best SIGN_LOW_FREQ_LONG  cell: reb={rebal_bars}bars/{bps}bps, "
              f"α_t={v['alpha_t']:+.2f}, OOS_t={v['oos_t']:+.2f}")
    if not viable_hi and not viable_lo:
        print("⚠ NO cell passes 3-check — S-81 likely REFUTED.\n")
    else:
        print()

    # ── Final verdict ────────────────────────────────────────────────────────
    passes_3check = g_s81["passes_all"]
    orthogonal = gate["passes_orthogonality_gate"]
    if passes_3check and orthogonal:
        verdict = "✅ SURVIVES + ORTHOGONAL — S-81 (4h cross-frequency) eligible as fusion contribution"
        verdict_band = "SURVIVES_ORTHOGONAL"
    elif passes_3check and not orthogonal:
        verdict = ("🟡 SURVIVES + CORRELATED — clears 3-check but leg-correlated; "
                   "standalone-eligible, NOT fusion-candidatable")
        verdict_band = "SURVIVES_CORRELATED"
    else:
        verdict = ("🔴 REFUTED — fails 3-check; lesson #43 v4: cross-frequency also "
                   "lacks edge; the cross-sectional-demean family is genuinely exhausted "
                   "for this data/universe. Future candidates must reach for STRUCTURALLY "
                   "different math (time-series, structural breaks, cross-asset).")
        verdict_band = "REFUTED"
    print(f"VERDICT: {verdict}\n")

    # ── Per-window W1-W6 attribution (best cell if exists) ───────────────────
    from src.research.validation.r63_fusion_validation import per_window, max_drawdown
    dd_s81 = max_drawdown(leg_s81_daily)
    pw_s81 = per_window(leg_s81_daily, windows)
    print(f"S-81 maxDD: {dd_s81:+.2%}")
    print(f"S-81 per-window (4h, 0bps, sign={sign}):")
    for label_ in sorted(pw_s81.keys()):
        ann_pct = pw_s81[label_]["ann_pct"]
        n = pw_s81[label_]["n_days"]
        print(f"  {label_}: {ann_pct:+.1f}% (n={n})")

    # ── Persist out ──────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(rets_daily.index.min().date()),
                  "hi": str(rets_daily.index.max().date()),
                  "n_days": int(len(rets_daily)),
                  "n_4h_bars": int(len(rets_4h)),
                  "n_assets_intersection": len(tradeable),
                  "n_assets_4h_strict": len(four_h_assets),
                  "matched_assets": four_h_assets},
        "construction": {
            "score_basis": "4h cross-frequency turnover residual (180-bar rolling-mean dollar-volume cross-sectional demean)",
            "freq": S81_FREQ,
            "tonus_lookback_bars": S81_TONUS_LOOKBACK_BARS,
            "tonus_min_obs": S81_TONUS_MIN_OBS,
            "k_terciles": S81_K_TERCILES,
            "universe": "28-asset funding ∩ CIS ∩ OHLCV ∩ 4h-availability",
            "rebal_bars_grid": [1, 6, 24, 168],
            "cost_grid": list(cost_bps_grid),
            "default_rebal_bars": 1, "default_cost_bps": 0.0,
            "sign": sign,
        },
        "leg_correlation_gate": gate,
        "per_leg_gauntlet": {
            "leg_s81": {"gauntlet": g_s81, "default_rebal_bars": 1,
                        "default_cost_bps": 0.0, "max_dd": dd_s81,
                        "per_window": pw_s81},
            "leg_r46": {"gauntlet": g_r46, "cad": R46_CAD, "cost_bps": R46_BPS},
            "leg_r62": {"gauntlet": g_r62, "cad": R62_CAD, "cost_bps": R62_BPS,
                        "feature_set": R62_FEATURE_SET, "z_threshold": R62_Z,
                        "min_features": R62_MF, "zwin": zwin},
            "leg_r76": {"gauntlet": g_r76, "cad": 5, "cost_bps": 0.0,
                        "score_basis": "funding_residual"},
            "leg_r78": {"gauntlet": g_r78, "cad": 3, "cost_bps": 0.0,
                        "score_basis": "relative_momentum (TSMOM demean)"},
        },
        "sweep_high": {f"{k[0]}bars_{k[1]}bps": v for k, v in sweep_hi.items()},
        "sweep_low": {f"{k[0]}bars_{k[1]}bps": v for k, v in sweep_lo.items()},
        "matched_cell_sign_audit": {
            "top_3": [{"rebal_bars": r, "bps": b, "diff": d, "hi_alpha_t": h, "lo_alpha_t": l}
                       for r, b, d, h, l in matched_diffs[:3]],
            "sign_verdict": sign_verdict,
        },
        "best_cells": {
            "sign_high_freq_long": ({"rebal_bars": best_hi[0][0],
                                      "cost_bps": best_hi[0][1],
                                      "alpha_t": best_hi[1]["alpha_t"],
                                      "oos_t": best_hi[1]["oos_t"]}
                                     if best_hi[0] else None),
            "sign_low_freq_long": ({"rebal_bars": best_lo[0][0],
                                     "cost_bps": best_lo[0][1],
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
            "note": ("S-81 is research-only. S-82 = S-81 as 4th fusion contribution "
                     "is the next step IF verdict is SURVIVES_ORTHOGONAL."),
        },
    }
    return out


# === Format report ===========================================================
def format_report(payload: dict) -> str:
    """Human-readable S-81 report."""
    lines = []
    lines.append("# S-81 — 4h cross-frequency turnover residual L/S")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_4h_bars']} 4h bars, "
                 f"{payload['panel']['n_assets_4h_strict']}-asset strict 4h universe)")
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
    lines.append(f"- corr(S-81, R46) = {g['corr_new_vs_r46']:+.3f}")
    lines.append(f"- corr(S-81, R62) = {g['corr_new_vs_r62']:+.3f}")
    lines.append(f"- corr(S-81, R76) = {g['corr_new_vs_r76']:+.3f}")
    lines.append(f"- corr(S-81, R78) = {g['corr_new_vs_r78']:+.3f}")
    lines.append(f"- max |corr| = {g['max_abs_corr']:.3f} (gate ≤ {g['gate_threshold']})")
    lines.append(f"- passes_orthogonality_gate = **{g['passes_orthogonality_gate']}**")
    lines.append("")
    lines.append("## Per-leg gauntlet (on 28-asset, daily-aggregated)")
    for leg in ("leg_s81", "leg_r46", "leg_r62", "leg_r76", "leg_r78"):
        gp = payload["per_leg_gauntlet"][leg]["gauntlet"]
        lines.append(f"- **{leg}**: gross_t = {gp['gross_t']:+.2f}, "
                     f"OOS_t = {gp['oos_t']:+.2f}, pass_all = {gp['passes_all']}")
    lines.append("")
    lines.append("## Matched-cell sign audit (top-3)")
    lines.append("| rebal_bars | bps | Δ(α_t) | hi (long) | lo (short) |")
    lines.append("|---:|---:|---:|---:|---:|")
    for r in payload["matched_cell_sign_audit"]["top_3"]:
        lines.append(f"| {r['rebal_bars']} | {r['bps']} | {r['diff']:+.2f} | "
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
        lines.append("- ✅ Lesson #43 v4: cross-frequency (R81) is the 1-in-5 outlier, "
                     "not the rule. Cross-frequency CAN carry edge when the daily "
                     "panel averages out microstructure signal. R77 fusion book may "
                     "benefit from a 4h contribution as a 4th leg.")
    elif v["band"] == "SURVIVES_CORRELATED":
        lines.append("- 🟡 Lesson #43 v4: 4h cross-frequency is correlated with one "
                     "existing leg (likely R76 daily funding or S-80 daily turnover). "
                     "The 4h panel exposes the same microstructure signal as the daily "
                     "panel, just with higher granularity. S-82 not warranted.")
    else:
        lines.append("- 🔴 Lesson #43 v4: 1 of 5 orthogonal candidates carry (R76 only). "
                     "Cross-sectional demean family is GENUINELY EXHAUSTED for this "
                     "data/universe. Future candidates must reach for STRUCTURALLY "
                     "different math (time-series, structural breaks, cross-asset). "
                     "Don't run 'cross-sectional demean of X at 4h/daily/weekly' — "
                     "STOP changing the X, change the structure.")
    lines.append("")
    return "\n".join(lines)


# === CLI =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--sign", type=str, default=SIGN_HIGH_FREQ_LONG,
                        choices=[SIGN_HIGH_FREQ_LONG, SIGN_LOW_FREQ_LONG])
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/s81_cross_frequency/{today}")
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
