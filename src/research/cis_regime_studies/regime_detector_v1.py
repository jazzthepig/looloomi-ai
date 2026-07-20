"""Regime detector for HL pooled F1 gate — R49 candidate (2026-07-20).

Why a regime gate is needed: R47 found that the pooled cross-sectional funding-crowding
market-neutral book sign-flipped catastrophically in F1 (2024-04 → 2024-10, α_t = −3.02,
the meme-crowded-long squeeze regime where "fade the crowd" was wrong). The same
lesson was independently rediscovered in R48 (cross-class regime-conditioning) but at
the L/S-quality level; here we apply it at the HL funding-crowding pooled level.

Per R46 prototype (W5 in CIS quality): gate signal-firing in the regime where the
crowd is directionally right. Three candidate signals:

1. BTC_funding_level: BTC's 30d rolling mean hourly funding rate. When BTC perp longs
   are paying >X bps/8h sustained, we're in crowd-long territory.
2. cross_class_crowded_count: count of perps whose 7d mean funding is in their own
   90th-percentile band. Many perps simultaneously elevated = cross-class crowded-long
   regime.
3. BTC_funding_acceleration: z-score of BTC's 7d funding change vs 90d std.

Pick whichever fires during F1 and stays quiet during F2/F3/F4. Test on the canonical
F1/F2/F3/F4 walk-forward windows from R47.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")


def _load_funding_1h(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Returns (ts_ms, funding_rate) arrays."""
    ts, fr = [], []
    with open(path) as f:
        r = csv.reader(f); next(r)
        for row in r:
            ts.append(int(row[0]))
            fr.append(float(row[1]))
    return np.array(ts), np.array(fr)


def _daily_mean(ts_ms: np.ndarray, fr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bin hourly funding into daily mean (a clean signal per day)."""
    days = ts_ms // 86_400_000
    out_t, out_v = [], []
    for d in np.unique(days):
        mask = days == d
        out_t.append(int(d) * 86_400_000)
        out_v.append(float(fr[mask].mean()))
    return np.array(out_t), np.array(out_v)


def btc_funding_level(cache: Path = CACHE, window: int = 30) -> tuple[np.ndarray, np.ndarray]:
    """BTC 30d rolling-mean of daily-mean funding rate (raw level)."""
    ts_ms, fr = _load_funding_1h(cache / "btc_funding_1h.csv")
    daily_t, daily_v = _daily_mean(ts_ms, fr)
    roll = np.full_like(daily_v, np.nan)
    for i in range(window - 1, len(daily_v)):
        roll[i] = float(daily_v[i - window + 1: i + 1].mean())
    return daily_t, roll


def cross_class_crowded_count(cache: Path = CACHE, *, perp_files: Iterable[str] | None = None,
                               percentile: float = 0.90, smooth_days: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """For each perp, mark days where 7d-mean funding exceeds the perp's own 90th-percentile.
    Sum across perps (cross-class breadth-of-crowded-longs).
    Returns (date_ms, crowded_count_daily)."""
    if perp_files is None:
        perp_files = sorted([p.name for p in cache.glob("*_funding_1h.csv")])
    perp_files = [p for p in perp_files if not p.startswith("btc")]  # exclude BTC for breadth

    per_perp_daily = {}  # sym -> (daily_t, daily_v)
    for fname in perp_files:
        sym = fname.replace("_funding_1h.csv", "").upper()
        ts_ms, fr = _load_funding_1h(cache / fname)
        d_t, d_v = _daily_mean(ts_ms, fr)
        per_perp_daily[fname] = (d_t, d_v)

    # find common daily index
    all_t = sorted(set().union(*[set(t) for t, _ in per_perp_daily.values()]))
    if not all_t:
        return np.array([]), np.array([])
    t_index = np.array(all_t)

    # for each perp: 7d rolling mean, then percentile threshold, then mark "crowded"
    crowded = np.zeros((len(perp_files), len(t_index)), dtype=float)
    for i, fname in enumerate(perp_files):
        d_t, d_v = per_perp_daily[fname]
        # align to t_index
        idx_map = {int(t): k for k, t in enumerate(d_t)}
        aligned = np.array([d_v[idx_map[int(t)]] if int(t) in idx_map else np.nan for t in t_index])
        # 7d rolling mean
        roll = np.full_like(aligned, np.nan)
        for k in range(smooth_days - 1, len(aligned)):
            window_vals = aligned[k - smooth_days + 1: k + 1]
            roll[k] = float(np.nanmean(window_vals)) if not np.isnan(window_vals).all() else np.nan
        # perp-specific percentile threshold (use own history)
        valid = roll[~np.isnan(roll)]
        if len(valid) < 30:
            continue
        thr = float(np.quantile(valid, percentile))
        crowded[i] = (roll > thr).astype(float)

    # cross-class count
    count_daily = np.nansum(crowded, axis=0)
    return t_index, count_daily


def btc_funding_acceleration(cache: Path = CACHE, *, short: int = 7, long: int = 30,
                              z_window: int = 90) -> tuple[np.ndarray, np.ndarray]:
    """Z-score of (BTC short-window funding minus long-window funding), normalized by
    rolling 90d std of that diff. Positive = funding accelerating."""
    ts_ms, fr = _load_funding_1h(cache / "btc_funding_1h.csv")
    daily_t, daily_v = _daily_mean(ts_ms, fr)

    short_ma = np.full_like(daily_v, np.nan)
    long_ma = np.full_like(daily_v, np.nan)
    for i in range(len(daily_v)):
        if i + 1 >= short:
            short_ma[i] = float(daily_v[i - short + 1: i + 1].mean())
        if i + 1 >= long:
            long_ma[i] = float(daily_v[i - long + 1: i + 1].mean())

    diff = short_ma - long_ma
    z = np.full_like(diff, np.nan)
    for i in range(z_window, len(diff)):
        win = diff[i - z_window: i]
        valid = win[~np.isnan(win)]
        if len(valid) < 30:
            continue
        sd = float(np.std(valid))
        if sd < 1e-12:
            continue
        z[i] = float((diff[i] - float(np.nanmean(valid))) / sd)
    return daily_t, z


def main():
    print("=" * 72)
    print("REGIME DETECTOR F1-FIT CHECK — R49 candidate (2026-07-20)")
    print("=" * 72)

    # F1 = 2024-04-02 → 2024-10-19
    # F2 = 2024-10-20 → 2025-05-08
    # F3 = 2025-05-09 → 2025-11-25
    # F4 = 2025-11-26 → 2026-06-15
    folds = [
        ("F1", 1712016000000, 1729296000000),    # 2024-04-02 → 2024-10-19
        ("F2", 1729296000000, 1746681600000),    # 2024-10-20 → 2025-05-08
        ("F3", 1746681600000, 1764105600000),    # 2025-05-09 → 2025-11-25
        ("F4", 1764105600000, 1781481600000),    # 2025-11-26 → 2026-06-15
    ]

    # 1) BTC funding level
    print("\n[1] BTC_funding_level (BTC 30d rolling-mean hourly funding):")
    t_btc, v_btc = btc_funding_level()
    for fname, t0, t1 in folds:
        mask = (t_btc >= t0) & (t_btc < t1) & ~np.isnan(v_btc)
        if not mask.any():
            print(f"  {fname}: NO DATA")
            continue
        seg = v_btc[mask]
        print(f"  {fname}: median={float(np.median(seg))*100:+.4f}%/day, "
              f"max={float(seg.max())*100:+.4f}%/day, n_days={int(mask.sum())}")

    # 2) cross-class crowded count
    print("\n[2] cross_class_crowded_count (perps in own 90th-pct funding band, 7d-smoothed):")
    t_xc, v_xc = cross_class_crowded_count()
    for fname, t0, t1 in folds:
        mask = (t_xc >= t0) & (t_xc < t1)
        if not mask.any():
            print(f"  {fname}: NO DATA")
            continue
        seg = v_xc[mask]
        print(f"  {fname}: mean_count={float(np.mean(seg)):.1f} of "
              f"{len([p for p in CACHE.glob('*_funding_1h.csv') if not p.name.startswith('btc_')])} perps, "
              f"max_count={int(seg.max())}, n_days={int(mask.sum())}")

    # 3) BTC funding acceleration (z-score)
    print("\n[3] BTC_funding_acceleration (z-score of 7d-30d diff, 90d norm):")
    t_ba, v_ba = btc_funding_acceleration()
    for fname, t0, t1 in folds:
        mask = (t_ba >= t0) & (t_ba < t1) & ~np.isnan(v_ba)
        if not mask.any():
            print(f"  {fname}: NO DATA")
            continue
        seg = v_ba[mask]
        print(f"  {fname}: mean_z={float(np.mean(seg)):+.2f}, "
              f"median_z={float(np.median(seg)):+.2f}, "
              f"frac_above_1.0={float(np.mean(seg > 1.0)):.0%}, "
              f"n_days={int(mask.sum())}")

    print("\n" + "=" * 72)
    print("VERDICT-FIT GUIDE")
    print("=" * 72)
    print("The regime signal that fires during F1 and stays quiet in F2/F3/F4 is the gate.")
    print("If BTC_funding_level median >0 and cross_class_crowded_count mean >50% of perps")
    print("during F1, and drops to <30% in F2-F4, then cross_class_crowded_count is the gate.")


if __name__ == "__main__":
    main()