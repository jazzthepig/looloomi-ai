"""
M-WO-1 — Event-count audit of R77 fusion before ANY deployment language.

Per §DIRECTIVE 2026-07-27 (Jazz + Seth → Minimax):
    R77's OOS_t +3.61 is day-level on the same risk-off-dominated window that
    inflated S-78 (t+14 → 4 episodes, 2/2, dead). The evidence floor now requires
    independent-episode counting. Run gaps-and-islands (gap>7d) on the R77 fusion
    OOS P&L: report n_episodes, per-episode mean, episode-level sign count + t.

Accept (per §DIRECTIVE): ≥8 independent episodes AND majority positive AND
                         episode-t > 2 → R77 keeps "survivor".
Fail  → R77 is relabeled "regime-specific candidate", NOT unique survivor.
Either result is a win.

Methodology
-----------
1. Reuse R77's exact panel + 28-asset strict funding ∩ CIS ∩ OHLCV universe.
2. Build R77's frozen 3-component fusion (fac_3 = 0.70 × fac_2 + 0.30 × leg_R76).
3. Take the OOS cut (last 30%, per R77's OOS_FRAC).
4. Define an episode as a contiguous run of non-zero daily P&L days.
   A new episode starts after a gap of ≥7 calendar days with zero P&L
   (book was idle). This is the "gaps-and-islands" discipline.
5. Per-episode stats:
   - n_days (length)
   - mean_daily_pnl
   - ann_pct (mean × 252)
   - t_stat (mean / std × √n)
   - cum_pnl
6. Aggregate verdict:
   - n_episodes
   - n_positive, n_negative (sign count)
   - pooled episode-t = Σ(positive_t) / √n_positive (meta-t)

This module is research-only. It does NOT mutate the live fusion book
(R65/R66/R69 frozen cell). It builds evidence for M-WO-4 (second paper book
forward commit) — gated on its own verdict.
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
    R76_K_TERCILES,
    SIGN_HIGH_FUND_LONG,
)
from src.research.validation.r77_r76_as_fusion_contribution import (
    fuse3, build_r76_sleeve_28,
    R69_W_R46, R69_W_R62, R76_BEST_CAD, R76_BEST_BPS,
)


# === Constants ================================================================
OOS_FRAC = 0.30
PERIODS_PER_YEAR = 252  # for daily-rebalanced book
EPISODE_GAP_DAYS = 7    # gap ≥ 7 calendar days with zero P&L → new episode
EPISODE_MIN_DAYS = 3    # drop shorter runs (noise floor)
ZERO_TOL = 1e-12        # absolute P&L threshold for "active book"

# Frozen R77 cell (per memory: w_R46=0.25, w_R62=0.75, w_R76=0.30)
FROZEN_W_R76 = 0.30

# §DIRECTIVE acceptance thresholds
EPISODE_COUNT_FLOOR = 8
EPISODE_T_FLOOR = 2.0


# === Episode segmentation =====================================================
def segment_episodes(pnl: pd.Series, gap_days: int = EPISODE_GAP_DAYS,
                     min_days: int = EPISODE_MIN_DAYS,
                     zero_tol: float = ZERO_TOL) -> list[dict]:
    """Segment a daily P&L series into independent episodes by gap>gap_days.

    Episode = contiguous run of days with |pnl| > zero_tol.
    Gap = consecutive days with |pnl| ≤ zero_tol.
    New episode starts after gap_days+ zero-PnL days.

    Per-episode:
      - n_days (active days only, zero-PnL days excluded)
      - mean_daily_pnl (mean of active days)
      - std_daily_pnl
      - ann_pct (mean × PERIODS_PER_YEAR)
      - t_stat (mean / std × √n_days, active only)
      - cum_pnl (sum of active days)
      - first_date, last_date
    """
    if pnl.empty:
        return []

    active = pnl.abs() > zero_tol
    pnl_a = pnl.where(active, other=np.nan)

    # Identify gaps: blocks of inactive days ≥ gap_days
    episodes = []
    cur_start = None
    cur_dates = []
    cur_pnls = []

    def _flush(buf_start, buf_dates, buf_pnls):
        if buf_start is None or len(buf_pnls) < min_days:
            return
        arr = np.asarray(buf_pnls, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        ann_pct = mean * PERIODS_PER_YEAR * 100.0  # in percent
        t_stat = (mean / std * np.sqrt(len(arr))) if std > 0 else 0.0
        cum = float(arr.sum())
        episodes.append({
            "first_date": str(buf_dates[0].date()),
            "last_date": str(buf_dates[-1].date()),
            "n_days": int(len(arr)),
            "mean_daily_pnl": mean,
            "std_daily_pnl": std,
            "ann_pct": ann_pct,
            "t_stat": float(t_stat),
            "cum_pnl": cum,
        })

    last_active_idx = None
    inactive_run = 0
    for ts, val in pnl_a.items():
        if np.isnan(val):
            inactive_run += 1
            # STRICT: gap > 7d (per §DIRECTIVE). inactive_run > gap_days means
            # we have seen MORE THAN gap_days consecutive zero-PnL days.
            if inactive_run > gap_days and cur_pnls:
                _flush(cur_start, cur_dates, cur_pnls)
                cur_start = None
                cur_dates = []
                cur_pnls = []
            continue
        if cur_start is None:
            cur_start = ts
            cur_dates = [ts]
            cur_pnls = [float(val)]
        else:
            cur_dates.append(ts)
            cur_pnls.append(float(val))
        inactive_run = 0
        last_active_idx = ts

    # Final flush
    _flush(cur_start, cur_dates, cur_pnls)
    return episodes


def aggregate_episodes(episodes: list[dict]) -> dict:
    """Aggregate stats across episodes for the §DIRECTIVE verdict."""
    if not episodes:
        return {
            "n_episodes": 0,
            "n_positive": 0,
            "n_negative": 0,
            "sign_majority_positive": False,
            "pooled_positive_t": float("nan"),
            "pooled_all_t": float("nan"),
            "per_episode": [],
        }
    n_pos = sum(1 for e in episodes if e["ann_pct"] > 0)
    n_neg = sum(1 for e in episodes if e["ann_pct"] <= 0)
    pos_t = [e["t_stat"] for e in episodes if e["t_stat"] > 0]
    all_t = [e["t_stat"] for e in episodes]
    pooled_pos = float(np.sum(pos_t) / np.sqrt(len(pos_t))) if pos_t else float("nan")
    pooled_all = float(np.sum(all_t) / np.sqrt(len(all_t))) if all_t else float("nan")
    return {
        "n_episodes": len(episodes),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "sign_majority_positive": n_pos > n_neg,
        "pooled_positive_t": pooled_pos,
        "pooled_all_t": pooled_all,
        "per_episode": episodes,
    }


# === Supplementary views =====================================================
def segment_by_sign(pnl: pd.Series, min_days: int = EPISODE_MIN_DAYS) -> list[dict]:
    """Episode = contiguous run of same-sign non-zero daily P&L.

    Supplementary view (NOT the §DIRECTIVE primary method). Reveals whether the
    book has internal sign-flips even when it's continuously active.
    """
    if pnl.empty:
        return []
    active = pnl.abs() > ZERO_TOL
    pnl_a = pnl.where(active, other=np.nan).dropna()
    if pnl_a.empty:
        return []

    episodes = []
    cur_sign = None
    cur_pnls = []
    cur_dates = []

    for ts, val in pnl_a.items():
        s = 1 if val > 0 else -1
        if cur_sign is None or s == cur_sign:
            cur_sign = s
            cur_dates.append(ts)
            cur_pnls.append(float(val))
        else:
            if len(cur_pnls) >= min_days:
                arr = np.asarray(cur_pnls, dtype=float)
                mean = float(arr.mean())
                std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
                ann_pct = mean * PERIODS_PER_YEAR * 100.0
                t_stat = (mean / std * np.sqrt(len(arr))) if std > 0 else 0.0
                cum = float(arr.sum())
                episodes.append({
                    "first_date": str(cur_dates[0].date()),
                    "last_date": str(cur_dates[-1].date()),
                    "n_days": int(len(arr)),
                    "sign": "positive" if cur_sign > 0 else "negative",
                    "mean_daily_pnl": mean,
                    "std_daily_pnl": std,
                    "ann_pct": ann_pct,
                    "t_stat": float(t_stat),
                    "cum_pnl": cum,
                })
            cur_sign = s
            cur_dates = [ts]
            cur_pnls = [float(val)]

    # final flush
    if cur_sign is not None and len(cur_pnls) >= min_days:
        arr = np.asarray(cur_pnls, dtype=float)
        mean = float(arr.mean())
        std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        ann_pct = mean * PERIODS_PER_YEAR * 100.0
        t_stat = (mean / std * np.sqrt(len(arr))) if std > 0 else 0.0
        cum = float(arr.sum())
        episodes.append({
            "first_date": str(cur_dates[0].date()),
            "last_date": str(cur_dates[-1].date()),
            "n_days": int(len(cur_pnls)),
            "sign": "positive" if cur_sign > 0 else "negative",
            "mean_daily_pnl": mean,
            "std_daily_pnl": std,
            "ann_pct": ann_pct,
            "t_stat": float(t_stat),
            "cum_pnl": cum,
        })
    return episodes


def segment_by_quarter(pnl: pd.Series) -> list[dict]:
    """Episode = calendar quarter. Supplementary view for OOS sub-period analysis."""
    if pnl.empty:
        return []
    quarters = pnl.index.to_period("Q")
    out = []
    for q in sorted(set(quarters)):
        sub = pnl.loc[quarters == q]
        if len(sub) < 3:
            continue
        arr = sub.values
        mean = float(arr.mean())
        std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        ann_pct = mean * PERIODS_PER_YEAR * 100.0
        t_stat = (mean / std * np.sqrt(len(arr))) if std > 0 else 0.0
        out.append({
            "quarter": str(q),
            "first_date": str(sub.index[0].date()),
            "last_date": str(sub.index[-1].date()),
            "n_days": int(len(arr)),
            "mean_daily_pnl": mean,
            "ann_pct": ann_pct,
            "t_stat": float(t_stat),
            "cum_pnl": float(arr.sum()),
        })
    return out


def segment_by_month(pnl: pd.Series) -> list[dict]:
    """Episode = calendar month."""
    if pnl.empty:
        return []
    months = pnl.index.to_period("M")
    out = []
    for m in sorted(set(months)):
        sub = pnl.loc[months == m]
        if len(sub) < 3:
            continue
        arr = sub.values
        mean = float(arr.mean())
        std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        ann_pct = mean * PERIODS_PER_YEAR * 100.0
        t_stat = (mean / std * np.sqrt(len(arr))) if std > 0 else 0.0
        out.append({
            "month": str(m),
            "first_date": str(sub.index[0].date()),
            "last_date": str(sub.index[-1].date()),
            "n_days": int(len(arr)),
            "mean_daily_pnl": mean,
            "ann_pct": ann_pct,
            "t_stat": float(t_stat),
            "cum_pnl": float(arr.sum()),
        })
    return out


# === R77 frozen-cell reproduction (reuses r77 helpers) =======================
def _build_r62_detector_local(features: pd.DataFrame, fragile_mask: pd.Series,
                              fragile_ranges: list, playable_ranges: list):
    """Reproduce R62 best-cell detector on the M-WO-1 panel."""
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


# === Main audit ===============================================================
def run_audit(out_dir: Path,
              frozen_w_r76: float = FROZEN_W_R76,
              leg_r76_sign: str = SIGN_HIGH_FUND_LONG,
              zwin: int = DEFAULT_ZWIN) -> dict:
    """Run M-WO-1 episode-count audit on the R77 frozen-cell fusion OOS P&L."""
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== M-WO-1 — R77 fusion episode-count audit (per §DIRECTIVE 2026-07-27) ===\n")

    # ── Load panels (R63/R77 parity) ─────────────────────────────────────────
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
          f"({len(rets)} days)")
    tradeable = funding_assets  # 28-asset STRICT intersection
    print(f"Strict universe: {len(tradeable)} assets\n")

    # ── 6-window partition (for fragility detector only — episode audit is independent) ─
    windows = partition_into_windows(rets.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows
                      if label_ in DEFAULT_FRAGILE_WINDOWS]
    playable_ranges = [(s, e) for label_, s, e in windows
                       if label_ in DEFAULT_PLAYABLE_WINDOWS]
    fragile_mask = pd.Series(False, index=rets.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets.index >= s) & (rets.index <= e)] = True

    # ── Build 3 legs (R77 parity) ────────────────────────────────────────────
    print("Building Leg 1 (R46 pillar_O 5d/5bps) …")
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets, tradeable)

    print("Building Leg 2 (R62 fade-the-crowd 21d/0bps gated) …")
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                       sign="fade_crowd").reindex(rets.index).ffill()
    feats = compute_combined_features(cis_long, rets, tradeable_full, tradeable,
                                       funding_daily)
    feats = feats.reindex(rets.index)
    det = _build_r62_detector_local(feats, fragile_mask, fragile_ranges, playable_ranges)
    leg_r62 = build_r62_sleeve_28(score_zwide, rets, tradeable, det)

    print(f"Building Leg 3 (R76 funding residual {R76_BEST_CAD}d/{R76_BEST_BPS}bps, "
          f"sign={leg_r76_sign}) …")
    leg_r76 = build_r76_sleeve_28(funding_daily, rets, tradeable, sign=leg_r76_sign)

    # ── Build frozen 2-comp baseline + frozen 3-comp cell ────────────────────
    fac_2 = fuse(leg_r46, leg_r62, R69_W_R46)
    fac_3 = fuse3(fac_2, leg_r76, frozen_w_r76)
    print(f"\nFrozen R77 cell: w_R46={R69_W_R46}, w_R62={R69_W_R62}, "
          f"w_R76={frozen_w_r76:.2f}")

    # ── Take OOS cut (last 30%) ──────────────────────────────────────────────
    cut = int(len(rets) * (1.0 - OOS_FRAC))
    oos_start = rets.index[cut]
    oos_end = rets.index[-1]
    print(f"OOS window: {oos_start.date()} → {oos_end.date()} "
          f"({len(rets) - cut} days, last {int(OOS_FRAC*100)}% of panel)")

    pnl_oos = fac_3.iloc[cut:].copy()
    pnl_oos.name = "fac_3_r77_frozen_oos"

    # ── 3-check gauntlet on OOS portion (sanity check) ──────────────────────
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_full = {"market": f_market.reindex(rets.index).fillna(0.0).values,
                  "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}
    g_oos_only = gauntlet_3check(fac_3.values, known_full, cut)
    print(f"\nR77 frozen-cell 3-check on OOS cut (sanity): "
          f"gross_t={g_oos_only['gross_t']:+.2f}, "
          f"OOS_t={g_oos_only['oos_t']:+.2f}, "
          f"passes_all={g_oos_only['passes_all']}")

    # ── Episode segmentation (gap>7d) on OOS P&L ────────────────────────────
    print(f"\nSegmenting OOS P&L into episodes (gap>{EPISODE_GAP_DAYS}d, "
          f"min_days={EPISODE_MIN_DAYS}) …")
    episodes = segment_episodes(pnl_oos)
    agg = aggregate_episodes(episodes)

    print(f"\nEpisodes found: {agg['n_episodes']}")
    print(f"  positive: {agg['n_positive']}, negative: {agg['n_negative']}, "
          f"majority_positive: {agg['sign_majority_positive']}")
    print(f"  pooled positive episode-t: {agg['pooled_positive_t']:+.2f}")
    print(f"  pooled all episode-t:      {agg['pooled_all_t']:+.2f}")

    if episodes:
        print(f"\n{'#':>2} | {'first_date':<12} | {'last_date':<12} | "
              f"{'n':>4} | {'ann%':>8} | {'t':>6} | {'cum_pnl':>10}")
        print("-" * 75)
        for i, e in enumerate(episodes, 1):
            print(f"{i:>2} | {e['first_date']:<12} | {e['last_date']:<12} | "
                  f"{e['n_days']:>4} | {e['ann_pct']:>+7.1f}% | "
                  f"{e['t_stat']:>+6.2f} | {e['cum_pnl']:>+10.4f}")

    # ── Supplementary views (diagnostic, NOT changing the §DIRECTIVE verdict) ─
    print("\n--- Supplementary: same-sign clustering (informational) ---")
    sign_eps = segment_by_sign(pnl_oos)
    n_pos_sign = sum(1 for e in sign_eps if e["sign"] == "positive")
    n_neg_sign = sum(1 for e in sign_eps if e["sign"] == "negative")
    print(f"  same-sign episodes: {len(sign_eps)} "
          f"(+{n_pos_sign} / -{n_neg_sign})")
    if sign_eps:
        for i, e in enumerate(sign_eps, 1):
            print(f"  Ep{i:>2} {e['sign']:<8} {e['first_date']} → {e['last_date']} "
                  f"n={e['n_days']:>3} ann%={e['ann_pct']:>+7.1f} t={e['t_stat']:>+6.2f}")

    print("\n--- Supplementary: quarterly partition (informational) ---")
    q_eps = segment_by_quarter(pnl_oos)
    n_pos_q = sum(1 for e in q_eps if e["ann_pct"] > 0)
    print(f"  quarters: {len(q_eps)} ({n_pos_q} positive / "
          f"{len(q_eps) - n_pos_q} negative)")
    for e in q_eps:
        print(f"  {e['quarter']}: {e['first_date']} → {e['last_date']} "
              f"n={e['n_days']:>3} ann%={e['ann_pct']:>+7.1f}% t={e['t_stat']:>+6.2f}")

    print("\n--- Supplementary: monthly partition (informational) ---")
    m_eps = segment_by_month(pnl_oos)
    n_pos_m = sum(1 for e in m_eps if e["ann_pct"] > 0)
    print(f"  months: {len(m_eps)} ({n_pos_m} positive / "
          f"{len(m_eps) - n_pos_m} negative)")

    # ── Verdict per §DIRECTIVE ───────────────────────────────────────────────
    n_ep = agg["n_episodes"]
    majority_pos = agg["sign_majority_positive"]
    pooled_t = agg["pooled_positive_t"]
    passes_episode_count = n_ep >= EPISODE_COUNT_FLOOR
    passes_sign = majority_pos
    passes_t = (not np.isnan(pooled_t)) and pooled_t > EPISODE_T_FLOOR

    passes_all = passes_episode_count and passes_sign and passes_t
    if passes_all:
        verdict = ("✅ SURVIVES — R77 fusion clears the episode-count evidence floor. "
                   "Proceeds to M-WO-4 (second paper book forward commit).")
        verdict_band = "EPISODE_SURVIVES"
    elif not passes_episode_count:
        verdict = (f"🔴 REFUTED — only {n_ep} episodes, below the "
                   f"≥{EPISODE_COUNT_FLOOR} floor. R77 is relabeled "
                   "'regime-specific candidate', NOT unique survivor.")
        verdict_band = "EPISODE_REFUTED_FEW_EPISODES"
    elif not passes_sign:
        verdict = (f"🔴 REFUTED — {n_ep} episodes but majority "
                   f"({agg['n_negative']} neg vs {agg['n_positive']} pos) negative. "
                   "R77 is relabeled 'regime-specific candidate'.")
        verdict_band = "EPISODE_REFUTED_SIGN"
    else:
        verdict = (f"🔴 REFUTED — {n_ep} episodes with majority positive but pooled "
                   f"episode-t={pooled_t:+.2f} ≤ {EPISODE_T_FLOOR}. "
                   "R77 is relabeled 'regime-specific candidate'.")
        verdict_band = "EPISODE_REFUTED_T_FLOOR"

    print(f"\n{'=' * 75}")
    print(f"§DIRECTIVE acceptance thresholds: "
          f"n_episodes≥{EPISODE_COUNT_FLOOR}, majority_positive, episode_t>{EPISODE_T_FLOOR}")
    print(f"  passes_episode_count: {passes_episode_count} (n={n_ep})")
    print(f"  passes_sign:          {passes_sign} ({agg['n_positive']} pos / "
          f"{agg['n_negative']} neg)")
    print(f"  passes_t:             {passes_t} (pooled_positive_t={pooled_t:+.2f})")
    print(f"  PASSES ALL:           {passes_all}")
    print(f"\nVerdict: {verdict}\n")

    # ── Persist out ──────────────────────────────────────────────────────────
    payload = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets_intersection": len(tradeable),
                  "oos_window": [str(oos_start.date()), str(oos_end.date())],
                  "oos_n_days": int(len(rets) - cut)},
        "frozen_cell": {
            "w_r46": R69_W_R46, "w_r62": R69_W_R62, "w_r76": frozen_w_r76,
            "construction": "fac_3 = (1 - w_R76) × fuse(R46, R62, 0.25) + w_R76 × leg_R76",
        },
        "gauntlet_sanity": g_oos_only,
        "episode_segmentation": {
            "gap_days": EPISODE_GAP_DAYS,
            "min_days": EPISODE_MIN_DAYS,
            "zero_tol": ZERO_TOL,
        },
        "episode_aggregate": {k: v for k, v in agg.items() if k != "per_episode"},
        "episodes": episodes,
        "supplementary_sign_episodes": {
            "n": len(sign_eps),
            "n_positive": n_pos_sign,
            "n_negative": n_neg_sign,
            "per_episode": sign_eps,
        },
        "supplementary_quarterly": {
            "n": len(q_eps),
            "n_positive": n_pos_q,
            "n_negative": len(q_eps) - n_pos_q,
            "per_quarter": q_eps,
        },
        "supplementary_monthly": {
            "n": len(m_eps),
            "n_positive": n_pos_m,
            "n_negative": len(m_eps) - n_pos_m,
            "per_month": m_eps,
        },
        "directive_thresholds": {
            "n_episodes_floor": EPISODE_COUNT_FLOOR,
            "majority_positive_required": True,
            "episode_t_floor": EPISODE_T_FLOOR,
        },
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_episode_count": passes_episode_count,
            "passes_sign": passes_sign,
            "passes_t": passes_t,
            "passes_all": passes_all,
        },
        "live_book_impact": {
            "touches_frozen_r69_cell": False,
            "r65_paper_book_unaffected": True,
            "r66_tracking_unaffected": True,
            "note": "M-WO-1 is research-only. Forward M-WO-4 gated on its verdict.",
        },
    }
    return payload


def format_report(payload: dict) -> str:
    lines = []
    lines.append("# M-WO-1 — R77 Fusion Episode-Count Audit")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"**Panel:** {payload['panel']['lo']} → {payload['panel']['hi']} "
                 f"({payload['panel']['n_days']} days, "
                 f"{payload['panel']['n_assets_intersection']}-asset strict universe)")
    lines.append(f"**OOS window:** {payload['panel']['oos_window'][0]} → "
                 f"{payload['panel']['oos_window'][1]} "
                 f"({payload['panel']['oos_n_days']} days, last 30% of panel)")
    lines.append("")
    lines.append("## Frozen R77 Cell")
    fc = payload["frozen_cell"]
    lines.append(f"- w_R46 = {fc['w_r46']}, w_R62 = {fc['w_r62']}, w_R76 = {fc['w_r76']:.2f}")
    lines.append(f"- Construction: `{fc['construction']}`")
    lines.append("")
    lines.append("## Gauntlet Sanity (R77 3-check on OOS cut)")
    g = payload["gauntlet_sanity"]
    lines.append(f"- gross_t = {g['gross_t']:+.2f}, OOS_t = {g['oos_t']:+.2f}, "
                 f"passes_all = {g['passes_all']}")
    lines.append("")
    lines.append("## Episode Segmentation (gap>7d)")
    es = payload["episode_segmentation"]
    lines.append(f"- gap_days = {es['gap_days']}, min_days = {es['min_days']}, "
                 f"zero_tol = {es['zero_tol']}")
    lines.append("")
    lines.append("## Episode Aggregate")
    ea = payload["episode_aggregate"]
    lines.append(f"- n_episodes: **{ea['n_episodes']}**")
    lines.append(f"- positive: {ea['n_positive']}, negative: {ea['n_negative']}")
    lines.append(f"- sign_majority_positive: **{ea['sign_majority_positive']}**")
    lines.append(f"- pooled positive episode-t: **{ea['pooled_positive_t']:+.2f}**")
    lines.append(f"- pooled all episode-t:      {ea['pooled_all_t']:+.2f}")
    lines.append("")
    lines.append("## Per-Episode Detail")
    if payload["episodes"]:
        lines.append("| # | first_date | last_date | n_days | ann% | t_stat | cum_pnl |")
        lines.append("|---:|:---|:---|---:|---:|---:|---:|")
        for i, e in enumerate(payload["episodes"], 1):
            lines.append(f"| {i} | {e['first_date']} | {e['last_date']} | "
                         f"{e['n_days']} | {e['ann_pct']:+.1f}% | "
                         f"{e['t_stat']:+.2f} | {e['cum_pnl']:+.4f} |")
    else:
        lines.append("- (no episodes found)")
    lines.append("")
    lines.append("## Supplementary View 1 — Same-Sign Clustering (informational)")
    sse = payload["supplementary_sign_episodes"]
    lines.append(f"- same-sign episodes: **{sse['n']}** ({sse['n_positive']} positive / "
                 f"{sse['n_negative']} negative)")
    if sse["per_episode"]:
        lines.append("")
        lines.append("| # | sign | first_date | last_date | n_days | ann% | t_stat |")
        lines.append("|---:|:---|:---|:---|---:|---:|---:|")
        for i, e in enumerate(sse["per_episode"], 1):
            lines.append(f"| {i} | {e['sign']} | {e['first_date']} | "
                         f"{e['last_date']} | {e['n_days']} | "
                         f"{e['ann_pct']:+.1f}% | {e['t_stat']:+.2f} |")
    lines.append("")
    lines.append("## Supplementary View 2 — Quarterly Partition (informational)")
    sq = payload["supplementary_quarterly"]
    lines.append(f"- quarters: **{sq['n']}** ({sq['n_positive']} positive / "
                 f"{sq['n_negative']} negative)")
    if sq["per_quarter"]:
        lines.append("")
        lines.append("| quarter | first_date | last_date | n_days | ann% | t_stat |")
        lines.append("|:---|:---|:---|---:|---:|---:|")
        for e in sq["per_quarter"]:
            lines.append(f"| {e['quarter']} | {e['first_date']} | "
                         f"{e['last_date']} | {e['n_days']} | "
                         f"{e['ann_pct']:+.1f}% | {e['t_stat']:+.2f} |")
    lines.append("")
    lines.append("## Supplementary View 3 — Monthly Partition (informational)")
    sm = payload["supplementary_monthly"]
    lines.append(f"- months: **{sm['n']}** ({sm['n_positive']} positive / "
                 f"{sm['n_negative']} negative)")
    lines.append("")
    lines.append("## §DIRECTIVE Verdict")
    v = payload["verdict"]
    th = payload["directive_thresholds"]
    lines.append(f"**Acceptance:** n_episodes≥{th['n_episodes_floor']} AND "
                 f"majority_positive AND episode_t>{th['episode_t_floor']}")
    lines.append("")
    lines.append(f"- passes_episode_count: {v['passes_episode_count']}")
    lines.append(f"- passes_sign:          {v['passes_sign']}")
    lines.append(f"- passes_t:             {v['passes_t']}")
    lines.append(f"- **PASSES ALL: {v['passes_all']}**")
    lines.append("")
    lines.append(f"**{v['band']}** — {v['verdict_string']}")
    lines.append("")
    lines.append("## Live Book Impact")
    li = payload["live_book_impact"]
    lines.append(f"- Touches frozen R69 cell: **{li['touches_frozen_r69_cell']}**")
    lines.append(f"- R65 paper book unaffected: **{li['r65_paper_book_unaffected']}**")
    lines.append(f"- R66 tracking unaffected: **{li['r66_tracking_unaffected']}**")
    lines.append(f"- Note: {li['note']}")
    return "\n".join(lines)


# === CLI ======================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--frozen-w-r76", type=float, default=FROZEN_W_R76)
    parser.add_argument("--leg-r76-sign", type=str, default=SIGN_HIGH_FUND_LONG)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/m_wo1_r77_episode_count_audit/{today}")
    payload = run_audit(out, frozen_w_r76=args.frozen_w_r76,
                        leg_r76_sign=args.leg_r76_sign)

    out.mkdir(parents=True, exist_ok=True)
    verdict_path = out / "verdict.json"
    report_path = out / "REPORT.md"
    with verdict_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with report_path.open("w") as f:
        f.write(format_report(payload))

    print(f"Wrote {verdict_path}")
    print(f"Wrote {report_path}")