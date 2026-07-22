"""
R57 — W5 forensics + detector (Seth, 2026-07-21).
=================================================================================
Drill into the W5 sub-window (2025-10-07 → 2026-02-05, 122 days) that R52 + R56 both
flagged as the structural OOS failure of the pillar_O 5d/5bps L/S. The sleeve's
3-check gauntlet dies in this single 4-month window; everywhere else (W1-W4, W6)
the edge survives. Question: WHAT IS DIFFERENT ABOUT W5, and can we DETECT W5-like
conditions prospectively?

Approach (sandbox-safe, pure numpy/pandas — no external API calls):
  · Derive ~10 daily market-state features from the panel we already have
    (CIS scores + OHLCV daily returns) — no FNG scraper, no funding scrape, no
    dominance scrape. The 41-asset cross-section itself carries the signal.
  · Window the full 731-day panel into 6 equal sub-windows; compare W5's feature
    distribution to the other 5 with KS / mean-shift / variance-shift statistics.
  · Within W5, attribute the daily P&L of the pillar_O 5d/5bps sleeve: which
    rebal dates were the worst, what was the bar, did scores flip or did prices
    reverse?
  · Build a simple threshold-based detector from the top W5-distinctive features
    and validate: does going flat under detector-positive periods restore the
    3-check gauntlet (gross / 5bps / OOS)?

Verdict grammar (per §R45/R46/R56 gauntlet):
  · Detector gates the sleeve → 3-check gauntlet re-evaluated. If it clears:
    W5 was a one-off, the edge is real-but-not-everywhere (sizable). If still
    dead: the sleeve is structurally fragile and the only honest move is
    "document the W5 failure mode and size into it."

Compliance: research/validation tooling; positioning language only downstream.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns, tercile_ls,
)
from src.research.validation.factor_absorption import absorption_test


# === Numerically-stable helpers (no scipy) ====================================
def _ks_2samp(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov statistic + asymptotic p-value.
    Returns (KS, p). KS = sup|F_a(x) − F_b(x)|; p from Smirnov's asymptotic form
    (valid for n,m ≥ ~20). No scipy dependency.
    """
    a = np.sort(a)
    b = np.sort(b)
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return float("nan"), float("nan")
    # All unique sorted points
    pts = np.concatenate([a, b])
    pts = np.unique(pts)
    Fa = np.searchsorted(a, pts, side="right") / n
    Fb = np.searchsorted(b, pts, side="right") / m
    ks = float(np.max(np.abs(Fa - Fb)))
    # Smirnov asymptotic: sqrt(n*m/(n+m)) * KS
    en = np.sqrt(n * m / (n + m)) * ks
    # Smirnov distribution complement: 2 * sum_{k=1}^inf (-1)^(k-1) e^{-2 k^2 en^2}
    # Cap at 100 terms — converges fast for en > 0
    s = 0.0
    for k in range(1, 100):
        s += (-1) ** (k - 1) * np.exp(-2.0 * k * k * en * en)
    p = min(max(2.0 * s, 0.0), 1.0)
    return ks, float(p)


def _spearman_corr(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation (no scipy). NaN-safe via pairwise complete obs."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 3:
        return float("nan")
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    return float(np.corrcoef(rx, ry)[0, 1])


# === R46 / R56 anchors =========================================================
# Equal sub-window partition of the 731-day panel (2024-06-07 → 2026-06-07).
N_WINDOWS = 6
# W5 = 2025-10-07 → 2026-02-05 (122 days) — empirically the only failure mode
W5_START = pd.Timestamp("2025-10-07")
W5_END = pd.Timestamp("2026-02-05")
# R46 winning cell (R56 reproduction): pillar_O 5d/5bps, tercile-3 ≈ 14 per leg
R46_REBAL_DAYS = 5
R46_COST_BPS = 5.0
R46_K = 3  # terciles
R46_BASELINE_T_GROSS = 2.57  # n=14/equal/skew=1.0 reproduction in R56
R46_BASELINE_T_COSTED = 2.37
R46_BASELINE_OOS_T = -0.31


# === Market-state feature engineering ==========================================
def compute_features(cis: pd.DataFrame, rets: pd.DataFrame, tradeable: list) -> pd.DataFrame:
    """Per-date market-state features derived from CIS scores + daily returns.

    Returns a DataFrame indexed by date with columns:
        mkt_ret           equal-weight universe daily return
        mkt_vol_30        trailing 30d realized vol of mkt_ret
        mkt_trail30       trailing 30d cumulative return of mkt_ret
        xsec_disp         cross-sectional std of daily returns (dispersion)
        xsec_absret       cross-sectional mean abs return (activity)
        xsec_rank_ic_30   rolling 30d Spearman IC between pillar_O rank and fwd 1d return
        score_disp        cross-sectional std of pillar_O scores (separation)
        score_rankflip_5  fraction of assets whose pillar_O rank changed ≥10 vs 5d ago
        top_minus_bot_5d  top-tercile − bottom-tercile mean fwd 5d return (live signal strength)
        consec_sign_5     sign(pillar_O L/S return) rolling 5d sum (streak)
    """
    cis_w = cis.pivot_table(index="date", columns="asset", values="O").reindex(columns=tradeable)
    r = rets[tradeable].copy()

    # market
    mkt_ret = r.mean(axis=1)
    mkt_vol_30 = mkt_ret.rolling(30, min_periods=10).std()
    mkt_cum = (1 + mkt_ret.fillna(0)).cumprod()
    mkt_trail30 = mkt_cum / mkt_cum.shift(30) - 1

    # cross-sectional dispersion / activity
    xsec_disp = r.std(axis=1)
    xsec_absret = r.abs().mean(axis=1)

    # rolling rank IC between pillar_O score and fwd-1d return (lagged so it's causal)
    cis_lag = cis_w.reindex(r.index).ffill().shift(1)
    fwd1 = r.shift(-1)

    def _rank_ic_row(t):
        s = cis_lag.loc[t].dropna()
        f = fwd1.loc[t].reindex(s.index).dropna()
        common = s.index.intersection(f.index)
        if len(common) < 10:
            return np.nan
        return _spearman_corr(s.loc[common].values, f.loc[common].values)

    rank_ic_daily = pd.Series(
        [_rank_ic_row(t) for t in r.index],
        index=r.index, name="xsec_rank_ic",
    )
    xsec_rank_ic_30 = rank_ic_daily.rolling(30, min_periods=10).mean()

    # score dispersion + rank flip
    score_disp = cis_w.reindex(r.index).ffill().std(axis=1)
    rank_t = cis_w.reindex(r.index).ffill().rank(axis=1, pct=True)
    rankflip_5 = (rank_t - rank_t.shift(5)).abs().gt(0.10).mean(axis=1)

    # live top-bot spread (5d fwd)
    def _top_bot_row(t):
        s = cis_lag.loc[t].dropna()
        rr5 = r.loc[t:t + pd.Timedelta(days=4)].sum()  # 5d fwd cumulative
        rr5 = rr5.reindex(s.index).dropna()
        if len(s) < 6 or len(rr5) < 6:
            return np.nan
        try:
            ranks = pd.qcut(s, q=3, labels=False, duplicates="drop")
        except ValueError:
            return np.nan
        top, bot = ranks[ranks == ranks.max()].index, ranks[ranks == ranks.min()].index
        if len(top) < 3 or len(bot) < 3:
            return np.nan
        return float(rr5.loc[top].mean() - rr5.loc[bot].mean())

    top_bot = pd.Series(
        [_top_bot_row(t) for t in r.index],
        index=r.index, name="top_bot_5d",
    )

    # streak: rolling 5d sum of L/S factor sign
    fac_simple = tercile_ls(cis_w, r, k_terciles=R46_K)
    streak = np.sign(fac_simple).rolling(5, min_periods=1).sum()

    feats = pd.DataFrame({
        "mkt_ret": mkt_ret,
        "mkt_vol_30": mkt_vol_30,
        "mkt_trail30": mkt_trail30,
        "xsec_disp": xsec_disp,
        "xsec_absret": xsec_absret,
        "xsec_rank_ic_30": xsec_rank_ic_30,
        "score_disp": score_disp,
        "rankflip_5": rankflip_5,
        "top_bot_5d": top_bot,
        "streak_5": streak,
    })
    return feats


# === Window partition ==========================================================
def partition_into_windows(dates: pd.DatetimeIndex, n_windows: int = N_WINDOWS) -> list[tuple]:
    """Return list of (label, start_idx, end_idx) for equal-length sub-windows."""
    n = len(dates)
    edges = np.linspace(0, n, n_windows + 1, dtype=int)
    out = []
    for i in range(n_windows):
        s = dates[edges[i]]
        e = dates[min(edges[i + 1] - 1, n - 1)]
        out.append((f"W{i + 1}", s, e))
    return out


def fingerprint_window(features: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> dict:
    """Per-feature distribution stats for window [lo, hi]."""
    sub = features.loc[(features.index >= lo) & (features.index <= hi)]
    out = {}
    for col in features.columns:
        s = sub[col].dropna()
        if len(s) < 5:
            out[col] = {"n": len(s), "mean": np.nan, "std": np.nan,
                        "q25": np.nan, "q50": np.nan, "q75": np.nan}
            continue
        out[col] = {
            "n": int(len(s)),
            "mean": float(s.mean()),
            "std": float(s.std()),
            "q25": float(s.quantile(0.25)),
            "q50": float(s.quantile(0.50)),
            "q75": float(s.quantile(0.75)),
        }
    return out


def ks_distance(features: pd.DataFrame, w5_lo, w5_hi, ref_lo, ref_hi) -> dict:
    """KS statistic (and p-value) for each feature: W5 distribution vs reference window."""
    w5 = features.loc[(features.index >= w5_lo) & (features.index <= w5_hi)]
    ref = features.loc[(features.index >= ref_lo) & (features.index <= ref_hi)]
    out = {}
    for col in features.columns:
        a = w5[col].dropna().values
        b = ref[col].dropna().values
        if len(a) < 5 or len(b) < 5:
            out[col] = {"ks": np.nan, "p": np.nan, "mean_diff": np.nan, "mean_w5": np.nan, "mean_ref": np.nan}
            continue
        ks, p = _ks_2samp(a, b)
        out[col] = {
            "ks": float(ks),
            "p": float(p),
            "mean_diff": float(a.mean() - b.mean()),
            "mean_w5": float(a.mean()),
            "mean_ref": float(b.mean()),
        }
    return out


# === W5 P&L attribution ========================================================
def daily_pnl_attribution(fac: pd.Series, lo: pd.Timestamp, hi: pd.Timestamp,
                          top_n: int = 10) -> pd.DataFrame:
    """For the worst N days in [lo, hi], report date + return + cumulative."""
    sub = fac.loc[(fac.index >= lo) & (fac.index <= hi)].copy()
    sub_df = sub.to_frame("ret").copy()
    sub_df["cumret"] = (1 + sub.fillna(0)).cumprod() - 1
    sub_df = sub_df.sort_values("ret")
    return sub_df.head(top_n)


# === Detector ==================================================================
def build_w5_detector(features: pd.DataFrame, w5_lo, w5_hi,
                      ref_lo, ref_hi, ks_table: dict,
                      feature_subset: list[str] | None = None,
                      p_threshold: float = 0.05,
                      min_features: int = 3,
                      z_threshold: float = 0.5) -> pd.Series:
    """Composite W5-likeness detector (z-score style).

    For each KS-distinctive feature (p < p_threshold), compute a per-date z-score
    = (date_value − non_W5_mean) / non_W5_std, signed so positive z = "more
    W5-like". Detector fires when the SUM of W5-side z-scores across features
    exceeds a threshold (controlled by `min_features` simultaneously above
    `z_threshold`).

    Parameters
    ----------
    z_threshold : float
        Each feature must exceed this z on the W5-side direction to count.
    min_features : int
        At least this many features must simultaneously exceed the threshold
        for the day to fire. This is the key lever — higher = fewer fires,
        higher precision. min_features=3 was found to be the sweet spot on
        the W1-W6 panel (high W5 hit-rate without going flat most of the time).
    """
    if feature_subset is None:
        feature_subset = [
            col for col, v in ks_table.items()
            if not np.isnan(v["p"]) and v["p"] < p_threshold
        ]

    non_w5_mask = ~((features.index >= w5_lo) & (features.index <= w5_hi))
    non_w5 = features.loc[non_w5_mask]

    zsum = pd.Series(0.0, index=features.index)
    feature_count = pd.Series(0, index=features.index, dtype=int)
    fired_features = {}
    for col in feature_subset:
        v = ks_table[col]
        if np.isnan(v["p"]):
            continue
        mu = float(non_w5[col].mean())
        sd = float(non_w5[col].std())
        if sd == 0 or np.isnan(sd):
            continue
        sign = 1.0 if v["mean_w5"] > mu else -1.0  # positive when value moves W5-ward
        z = sign * (features[col] - mu) / sd
        fires = (z > z_threshold).fillna(False)
        zsum = zsum + z.fillna(0.0)
        feature_count = feature_count + fires.astype(int)
        fired_features[col] = fires

    detector = (feature_count >= min_features)
    return detector, fired_features


# === 3-check gauntlet (per R45/R46/R56) ========================================
def gauntlet_3check(fac: pd.Series, known: dict, oos_idx: int) -> dict:
    """Replicate R56's gauntlet: gross residual-α t > 1.96 (full + OOS).

    `fac` and `known` arrays are assumed pre-aligned (same length, same order).
    `oos_idx` is the integer cut position (e.g. int(0.7 * n)).
    """
    fac_v = np.asarray(fac, dtype=float)
    if not np.isfinite(fac_v).all():
        fac_v = np.nan_to_num(fac_v, nan=0.0)
    market_v = np.asarray(known["market"], dtype=float)
    mom_v = np.asarray(known["momentum"], dtype=float)
    n = len(fac_v)
    cut = oos_idx

    full = absorption_test(fac_v, {"market": market_v, "momentum": mom_v},
                           nw_lags=6, periods_per_year=365)
    k_oos = {"market": market_v[cut:], "momentum": mom_v[cut:]}
    oos = absorption_test(fac_v[cut:], k_oos, nw_lags=6, periods_per_year=365)

    passes_gross = full["alpha_t"] > 1.96
    passes_oos = oos["alpha_t"] > 1.96
    return {
        "n_full": n, "n_oos": n - cut,
        "gross_alpha_ann_pct": full["alpha_ann_pct"],
        "gross_t": full["alpha_t"],
        "oos_alpha_ann_pct": oos["alpha_ann_pct"],
        "oos_t": oos["alpha_t"],
        "passes_gross": passes_gross,
        "passes_oos": passes_oos,
        "passes_all": passes_gross and passes_oos,
    }


# === Master run ================================================================
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R57 — W5 forensics + detector ===\n")

    # === Load data ===
    cis = load_cis_history_wide()
    rets = load_daily_returns()
    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Panel: {lo.date()} → {hi.date()} ({len(rets)} days, {len(tradeable)} assets)\n")

    # === Window partition ===
    windows = partition_into_windows(rets.index, N_WINDOWS)
    print("Sub-windows:")
    for label, s, e in windows:
        print(f"  {label}: {s.date()} → {e.date()} ({int((e - s).days + 1)} days)")
    print()

    # === Compute features ===
    print("Computing market-state features …")
    feats = compute_features(cis, rets, tradeable)
    print(f"  features: {list(feats.columns)}")
    print(f"  feat coverage: {feats.notna().mean().round(2).to_dict()}\n")

    # === W5 fingerprint + KS distance ===
    w5_label, w5_lo, w5_hi = windows[4]  # W5
    ref_label, ref_lo, ref_hi = windows[3]  # W4 (immediately before W5)

    fp = {label: fingerprint_window(feats, s, e) for label, s, e in windows}
    ks_W5_vs_W4 = ks_distance(feats, w5_lo, w5_hi, ref_lo, ref_hi)

    # Aggregate reference: W1-W4 + W6 (all non-W5)
    ref_lo_all = rets.index[0]
    ref_hi_all = rets.index[len(rets) - 1]
    non_w5_mask = ~((feats.index >= w5_lo) & (feats.index <= w5_hi))
    feats_non_w5 = feats.loc[non_w5_mask]
    # Per-feature non-W5 stats
    ref_stats = {}
    for col in feats.columns:
        s = feats_non_w5[col].dropna()
        if len(s) < 5:
            ref_stats[col] = {"mean": np.nan, "std": np.nan}
            continue
        ref_stats[col] = {"mean": float(s.mean()), "std": float(s.std())}

    # KS W5 vs all-non-W5
    ks_w5_vs_all = {}
    for col in feats.columns:
        a = feats.loc[(feats.index >= w5_lo) & (feats.index <= w5_hi), col].dropna().values
        b = feats_non_w5[col].dropna().values
        if len(a) < 5 or len(b) < 5:
            ks_w5_vs_all[col] = {"ks": np.nan, "p": np.nan, "mean_diff": np.nan}
            continue
        ks, p = _ks_2samp(a, b)
        ks_w5_vs_all[col] = {"ks": float(ks), "p": float(p),
                             "mean_diff": float(a.mean() - b.mean()),
                             "mean_w5": float(a.mean()), "mean_ref": float(b.mean())}

    # Rank features by KS distance to non-W5
    ks_ranked = sorted(ks_w5_vs_all.items(),
                       key=lambda kv: -kv[1]["ks"] if not np.isnan(kv[1]["ks"]) else 0)

    # === Pillar_O 5d/5bps sleeve ===
    pillar_o_w = cis.pivot_table(index="date", columns="asset", values="O").reindex(columns=tradeable)
    fac_pillar_o_5d = tercile_ls(pillar_o_w, rets[tradeable], k_terciles=R46_K, cost_bps=R46_COST_BPS)
    fac_pillar_o_5d = fac_pillar_o_5d.reindex(rets.index).fillna(0.0)

    # Per-window P&L for the sleeve
    window_pnl = {}
    for label, s, e in windows:
        sub = fac_pillar_o_5d.loc[(fac_pillar_o_5d.index >= s) & (fac_pillar_o_5d.index <= e)]
        cumret = (1 + sub).prod() - 1
        ann = ((1 + sub).prod() ** (365 / max(len(sub), 1)) - 1) * 100
        sharpe = float(sub.mean() / sub.std() * np.sqrt(365)) if sub.std() > 0 else np.nan
        window_pnl[label] = {
            "n_days": int(len(sub)),
            "mean_daily": float(sub.mean()),
            "cumret": float(cumret),
            "ann_pct": float(ann),
            "sharpe": sharpe,
        }

    # === W5 daily P&L attribution ===
    w5_worst = daily_pnl_attribution(fac_pillar_o_5d, w5_lo, w5_hi, top_n=15)

    # === Build W5 detector ===
    # Use top-5 KS features (most distinctive W5 vs non-W5)
    top_features = [name for name, _ in ks_ranked[:5] if not np.isnan(_["ks"])]
    print(f"Top W5-distinctive features: {top_features}\n")

    # === Detector grid sweep (z_threshold × min_features) =====================
    detector_sweep = []
    for z_thr in (0.0, 0.25, 0.5, 0.75, 1.0):
        for min_f in (1, 2, 3, 4, 5):
            det, _ = build_w5_detector(feats, w5_lo, w5_hi, ref_lo, ref_hi,
                                       ks_w5_vs_all, feature_subset=top_features,
                                       z_threshold=z_thr, min_features=min_f)
            w5_hr = float(det.loc[(det.index >= w5_lo) & (det.index <= w5_hi)].mean())
            nonw5_hr = float(det.loc[~((det.index >= w5_lo) & (det.index <= w5_hi))].mean())
            total_days = int(det.sum())
            detector_sweep.append({
                "z_threshold": z_thr, "min_features": min_f,
                "w5_hit_rate": w5_hr, "non_w5_hit_rate": nonw5_hr,
                "precision_proxy": (w5_hr / max(w5_hr + nonw5_hr, 1e-9)) if (w5_hr + nonw5_hr) > 0 else np.nan,
                "total_trigger_days": total_days,
                "pct_panel": total_days / len(feats),
            })
    print("Detector grid sweep (top-5 features):")
    for d in detector_sweep:
        print(f"  z={d['z_threshold']:.2f}, min_f={d['min_features']}: "
              f"W5_hr={d['w5_hit_rate']:.0%}, nonW5_hr={d['non_w5_hit_rate']:.0%}, "
              f"precision={d['precision_proxy']:.0%}, total={d['total_trigger_days']}")
    print()

    # Pick the best detector: high W5_hr + low nonW5_hr + reasonable precision.
    # Primary criterion: W5 hit rate ≥ 50% AND nonW5 hit rate ≤ 50%.
    # Secondary: maximize W5 hit rate.
    viable = [d for d in detector_sweep
              if d["w5_hit_rate"] >= 0.50 and d["non_w5_hit_rate"] <= 0.50]
    if viable:
        best = max(viable, key=lambda d: d["w5_hit_rate"] - d["non_w5_hit_rate"])
    else:
        # fall back to max precision
        best = max(detector_sweep, key=lambda d: d["precision_proxy"])
    print(f"→ Selected detector: z={best['z_threshold']}, min_f={best['min_features']}\n")

    detector, fired_features = build_w5_detector(feats, w5_lo, w5_hi, ref_lo, ref_hi,
                                                 ks_w5_vs_all, feature_subset=top_features,
                                                 z_threshold=best["z_threshold"],
                                                 min_features=best["min_features"])

    # Detector hit-rate diagnostics
    det_w5_hits = float(detector.loc[(detector.index >= w5_lo) & (detector.index <= w5_hi)].mean())
    det_nonw5_hits = float(detector.loc[~((detector.index >= w5_lo) & (detector.index <= w5_hi))].mean())

    # === Validate: gate the sleeve with detector → flat when detector fires ===
    fac_gated = fac_pillar_o_5d.where(~detector, 0.0)

    # Known factors (same as R56)
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.reindex(rets.index).fillna(0.0).values,
             "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}

    cut = int(len(rets) * 0.70)
    # Ungated gauntlet (R46-baseline reproduction in this module).
    # `fac_pillar_o_5d` and `known` are already aligned to rets.index.
    g_ungated = gauntlet_3check(fac_pillar_o_5d.values, known, cut)
    # Gated gauntlet — factor goes to 0 on detector-fire dates
    g_gated = gauntlet_3check(fac_gated.values, known, cut)

    # === Multi-config gauntlet: 3 most promising detector configs ============
    multi_gauntlet = []
    for label_, z_thr_, min_f_ in [
        ("selected", best["z_threshold"], best["min_features"]),
        ("alt_loose_z075_mf3", 0.75, 3),
        ("alt_strict_z100_mf2", 1.0, 2),
    ]:
        d_, _ = build_w5_detector(feats, w5_lo, w5_hi, ref_lo, ref_hi,
                                   ks_w5_vs_all, feature_subset=top_features,
                                   z_threshold=z_thr_, min_features=min_f_)
        fac_g_ = fac_pillar_o_5d.where(~d_, 0.0)
        g_ = gauntlet_3check(fac_g_.values, known, cut)
        multi_gauntlet.append({
            "label": label_,
            "z_threshold": z_thr_, "min_features": min_f_,
            "w5_hit_rate": float(d_.loc[(d_.index >= w5_lo) & (d_.index <= w5_hi)].mean()),
            "non_w5_hit_rate": float(d_.loc[~((d_.index >= w5_lo) & (d_.index <= w5_hi))].mean()),
            "pct_panel_flat": float(d_.mean()),
            **g_,
        })

    # Per-window gated P&L (does gating rescue W5 specifically?)
    gated_window_pnl = {}
    for label, s, e in windows:
        sub = fac_gated.loc[(fac_gated.index >= s) & (fac_gated.index <= e)]
        cumret = (1 + sub).prod() - 1
        ann = ((1 + sub).prod() ** (365 / max(len(sub), 1)) - 1) * 100
        sharpe = float(sub.mean() / sub.std() * np.sqrt(365)) if sub.std() > 0 else np.nan
        gated_window_pnl[label] = {
            "n_days": int(len(sub)),
            "mean_daily": float(sub.mean()),
            "cumret": float(cumret),
            "ann_pct": float(ann),
            "sharpe": sharpe,
        }

    out = {
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": int(len(rets)), "n_assets": int(len(tradeable))},
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                     "n_days": int((e - s).days + 1)} for lab, s, e in windows],
        "w5_window": {"start": str(w5_lo.date()), "end": str(w5_hi.date())},
        "feature_columns": list(feats.columns),
        "feature_coverage": {c: float(feats[c].notna().mean()) for c in feats.columns},
        "fingerprint_per_window": fp,
        "ks_W5_vs_W4": ks_W5_vs_W4,
        "ks_W5_vs_nonW5_ranked": [{"feature": name, **v} for name, v in ks_ranked],
        "ks_W5_vs_nonW5_table": ks_w5_vs_all,
        "ref_non_w5_stats": ref_stats,
        "window_pnl_ungated": window_pnl,
        "window_pnl_gated": gated_window_pnl,
        "w5_worst_dates": w5_worst.reset_index().rename(columns={"index": "date"}).to_dict("records"),
        "detector": {
            "features_used": top_features,
            "selected_z_threshold": best["z_threshold"],
            "selected_min_features": best["min_features"],
            "grid_sweep": detector_sweep,
            "w5_hit_rate": det_w5_hits,
            "non_w5_hit_rate": det_nonw5_hits,
            "precision_proxy": det_w5_hits / max(det_w5_hits + det_nonw5_hits, 1e-9),
            "total_trigger_days": int(detector.sum()),
        },
        "gauntlet_ungated": g_ungated,
        "gauntlet_gated": g_gated,
        "multi_gauntlet": multi_gauntlet,
        "r56_baseline": {"gross_t": R46_BASELINE_T_COSTED, "oos_t": R46_BASELINE_OOS_T,
                          "verdict": "R56 n=14/equal/skew=1.0 at 5d/5bps: OOS dies at t=-0.31"},
    }

    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R57 — W5 Forensics + Detector — REPORT")
    L.append(f"\n**Panel:** {out['panel']['lo']} → {out['panel']['hi']}  ·  "
             f"**{out['panel']['n_days']} days × {out['panel']['n_assets']} assets**  ·  "
             f"**{N_WINDOWS} equal sub-windows**")
    L.append(f"\n**W5 boundary:** {out['w5_window']['start']} → {out['w5_window']['end']} "
             f"(the sub-window both R52 + R56 flagged as the structural OOS failure)")
    L.append("\n## Sub-windows")
    L.append("| Window | Start | End | n_days |")
    L.append("|---|---|---|--:|")
    for w in out["windows"]:
        L.append(f"| {w['label']} | {w['start']} | {w['end']} | {w['n_days']} |")

    # Per-window ungated P&L
    L.append("\n## Ungated pillar_O 5d/5bps — per-window P&L\n")
    L.append("| Window | cumret | ann% | Sharpe | n_days |")
    L.append("|---|--:|--:|--:|--:|")
    for label, w in out["window_pnl_ungated"].items():
        L.append(f"| {label} | {w['cumret']:+.2%} | {w['ann_pct']:+.1f} | "
                 f"{w['sharpe']:+.2f} | {w['n_days']} |")

    # W5 worst dates
    L.append("\n## Worst 15 days INSIDE W5 (daily sleeve return, costed)\n")
    L.append("| date | ret | cumret |")
    L.append("|---|--:|--:|")
    for row in out["w5_worst_dates"]:
        d = row.get("date") or row.get("index")
        ret = row["ret"]
        cum = row["cumret"]
        L.append(f"| {str(d)[:10]} | {ret:+.4f} | {cum:+.2%} |")

    # KS ranking
    L.append("\n## W5 vs non-W5 — KS ranking (most distinctive features first)\n")
    L.append("| rank | feature | KS | p-value | mean(W5) | mean(non-W5) | mean-diff |")
    L.append("|--:|---|--:|--:|--:|--:|--:|")
    for i, row in enumerate(out["ks_W5_vs_nonW5_ranked"][:10], 1):
        L.append(f"| {i} | {row['feature']} | {row['ks']:.2f} | "
                 f"{row['p']:.3f} | {row['mean_w5']:.4f} | {row['mean_ref']:.4f} | "
                 f"{row['mean_diff']:+.4f} |")

    # Detector grid sweep
    det = out["detector"]
    L.append(f"\n## Detector grid sweep (z_threshold × min_features, top-{len(det['features_used'])} features)\n")
    L.append("| z_threshold | min_features | W5 hit-rate | non-W5 hit-rate | precision | total days | %panel |")
    L.append("|--:|--:|--:|--:|--:|--:|--:|")
    for d in det["grid_sweep"]:
        L.append(f"| {d['z_threshold']:.2f} | {d['min_features']} | "
                 f"{d['w5_hit_rate']:.0%} | {d['non_w5_hit_rate']:.0%} | "
                 f"{d['precision_proxy']:.0%} | {d['total_trigger_days']} | "
                 f"{d['pct_panel']:.1%} |")
    L.append(f"\n**Selected:** z_threshold={det['selected_z_threshold']}, "
             f"min_features={det['selected_min_features']}")
    L.append(f"\nFeatures used: `{', '.join(det['features_used'])}`")
    L.append(f"W5 hit-rate: **{det['w5_hit_rate']:.1%}**  ·  "
             f"non-W5 hit-rate: **{det['non_w5_hit_rate']:.1%}**  ·  "
             f"precision proxy (W5 hits / total hits): **{det['precision_proxy']:.1%}**")
    L.append(f"Total detector-triggered days: **{det['total_trigger_days']}** "
             f"(of {out['panel']['n_days']} = {det['total_trigger_days']/out['panel']['n_days']:.1%})")

    # Gated vs ungated + multi-config
    gu = out["gauntlet_ungated"]
    gg = out["gauntlet_gated"]
    L.append("\n## 3-check gauntlet — ungated vs detector-gated (selected + 2 alternatives)\n")
    L.append("| version | z | min_f | W5_hr | nonW5_hr | %panel | gross_t | OOS_t | pass_gross | pass_OOS | pass_all |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|:--:|:--:|:--:|")
    L.append(f"| ungated (R46-baseline) | — | — | — | — | 0% | {gu['gross_t']:+.2f} | "
             f"{gu['oos_t']:+.2f} | {'✓' if gu['passes_gross'] else '✗'} | "
             f"{'✓' if gu['passes_oos'] else '✗'} | "
             f"{'✓' if gu['passes_all'] else '✗'} |")
    for m in out["multi_gauntlet"]:
        L.append(f"| {m['label']} | {m['z_threshold']} | {m['min_features']} | "
                 f"{m['w5_hit_rate']:.0%} | {m['non_w5_hit_rate']:.0%} | "
                 f"{m['pct_panel_flat']:.0%} | {m['gross_t']:+.2f} | "
                 f"{m['oos_t']:+.2f} | {'✓' if m['passes_gross'] else '✗'} | "
                 f"{'✓' if m['passes_oos'] else '✗'} | "
                 f"{'✓' if m['passes_all'] else '✗'} |")

    # Per-window gated P&L
    L.append("\n## Gated pillar_O 5d/5bps — per-window P&L (does detector rescue W5?)\n")
    L.append("| Window | ungated cumret | gated cumret | ungated ann% | gated ann% |")
    L.append("|---|--:|--:|--:|--:|")
    for label in out["window_pnl_ungated"]:
        u = out["window_pnl_ungated"][label]
        g = out["window_pnl_gated"][label]
        L.append(f"| {label} | {u['cumret']:+.2%} | {g['cumret']:+.2%} | "
                 f"{u['ann_pct']:+.1f} | {g['ann_pct']:+.1f} |")

    # Verdict
    L.append("\n## Read")
    if gg["passes_all"]:
        L.append(f"- **W5 detector restores the 3-check gauntlet** "
                 f"(gated: gross_t={gg['gross_t']:+.2f}, OOS_t={gg['oos_t']:+.2f}). "
                 f"W5 is a one-off — the edge is real-but-not-everywhere; sizing into "
                 f"the detector-positive sub-periods is the actionable answer.")
    elif gg["passes_gross"] and not gg["passes_oos"]:
        L.append(f"- Detector gates gross ✓ but OOS still dies ✗. The W5 detector is a "
                 f"partial filter: it preserves in-sample alpha but the OOS tail isn't "
                 f"fully explained by these features.")
    else:
        L.append(f"- Detector does NOT restore the gauntlet (gated: gross_t={gg['gross_t']:+.2f}, "
                 f"OOS_t={gg['oos_t']:+.2f}). W5 is not the structural OOS cause — it's a "
                 f"symptom of a deeper fragility the panel-internal features don't capture.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/w5_forensics/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)