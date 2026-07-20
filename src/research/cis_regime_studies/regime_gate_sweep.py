"""Regime-gated pooled book + gate sweep — R49 candidate (2026-07-20).

R47 found that pooled cross-sectional funding-crowding market-neutral sign-flipped
catastrophically in F1 (2024-04 → 2024-10, α_t = −3.02). R46's lesson: gate signal
firing in the regime where "the crowd is directionally right."

This script:
1. Loads the HL pooled book from R47's canonical config (thr=1.0, hold=10, vol_mult=1.10).
2. Computes 3 candidate external regime signals that DON'T look at the book itself:
   - S1: BTC funding-acceleration (z-score of BTC 7d-30d diff)
   - S2: cross-class breadth-of-crowded-longs (perps in own 90th-pct funding band)
   - S3: basket-vs-BTC 30d spread (the perp basket outperforming BTC)
3. For each (signal × threshold) combo, gates the book: position → 0 when gate fires.
4. Re-runs walk-forward fold analysis + canonical OOS alpha_t.
5. Reports the matrix: which (if any) gate cleanly destroys F1 without gutting F2-F4.

The honest R49 finding is whichever the matrix shows. If no clean gate → R49 = "regime-
conditioning approach does not save the pooled book at any tested signal × threshold."
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# repo path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.research.cis_regime_studies.funding_crowding_breadth import (
    load_hyperliquid_panel,
    build_pooled_book,
    build_factors,
    run_pooled_breadth_experiment,
    _alpha_t_new_west,
)
from src.research.cis_regime_studies.regime_detector_v1 import (
    btc_funding_acceleration,
    cross_class_crowded_count,
    CACHE,
)

CACHE = Path(CACHE)
F1_END = 1729296000000  # 2024-10-19
F2_END = 1746681600000  # 2025-05-08
F3_END = 1764105600000  # 2025-11-25


def _gate_book(pool_returns: np.ndarray, position: np.ndarray, dates: np.ndarray,
               signal: np.ndarray, threshold: float, *, mode: str = "above") -> np.ndarray:
    """Apply regime gate: where signal crosses threshold, set position to 0 (skip the day).
    mode='above': skip when signal > threshold; mode='below': skip when signal < threshold.
    Returns adjusted pool_returns."""
    sig = np.asarray(signal)
    if len(sig) != len(dates):
        # align signal to dates (in case signal is on different daily index)
        # use nearest-prior
        sig_aligned = np.full(len(dates), np.nan)
        sig_dates = np.asarray(signal_dates)  # need signal_dates passed in
        raise NotImplementedError("use _gate_book_aligned")
    if mode == "above":
        mask = sig > threshold
    else:
        mask = sig < threshold
    pos_gated = np.where(mask, 0.0, position)
    # recompute pool_returns = position[t-1] * asset_ret[t]; since we don't have asset_ret here,
    # we approximate by scaling pool_returns by (pos_gated / position). When pos was 0 → returns = 0.
    pos_prev = np.concatenate([[0.0], position[:-1]])
    pos_gated_prev = np.where(mask, 0.0, pos_prev)
    scale = np.where(np.abs(pos_prev) > 1e-9, pos_gated_prev / np.where(np.abs(pos_prev) > 1e-9, pos_prev, 1.0), 1.0)
    return pool_returns * scale


def _gate_book_v2(canonical: dict, signal_dates: np.ndarray, signal: np.ndarray,
                  threshold: float, *, mode: str = "above") -> dict:
    """Gate the canonical book by zeroing positions on gated days. Re-costs turnover.

    canonical = output of build_pooled_book (has pool_position, pool_returns, asset_returns, per_perp_pos, dates).
    """
    dates = canonical["dates"]
    sig = np.asarray(signal)
    sig_dates = np.asarray(signal_dates)

    # Convert dates to ms ints (panel uses ISO date strings)
    from datetime import datetime, timezone
    def _date_to_ms(s):
        if isinstance(s, (int, np.integer)):
            return int(s)
        return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)
    dates_ms = np.array([_date_to_ms(d) for d in dates], dtype=np.int64)
    sig_dates = np.array([_date_to_ms(d) for d in sig_dates], dtype=np.int64)

    # align signal to dates: forward-fill NaN, take signal value at each date (nearest prior)
    aligned = np.full(len(dates), np.nan)
    j = 0
    for k, d in enumerate(dates_ms):
        # advance j to last sig_date <= d
        while j < len(sig_dates) and sig_dates[j] <= d:
            j += 1
        # sig_dates[j-1] is the most recent signal value at or before d
        if j > 0:
            aligned[k] = sig[j - 1]

    if mode == "above":
        gated_mask = aligned > threshold
    elif mode == "below":
        gated_mask = aligned < threshold
    else:
        raise ValueError(f"unknown mode: {mode}")

    # zero out positions on gated days, recompute returns and turnover
    per_perp_pos = canonical.get("per_perp_pos")  # may not exist; recompute
    if per_perp_pos is None:
        # Need to recover per-perp positions. They aren't stored in canonical dict, only
        # the demeaned pool_position. We can still gate the pool_position.
        pool_pos = canonical["pool_position"]
        asset_ret = canonical["asset_returns"]
        n_perps = canonical["n_perps"]
        n = len(dates)
        # recompute pool_pos[t-1] * asset_ret[t] with gating (broadcast 1D mask across perps)
        gated_pool_pos = pool_pos.copy()
        gated_pool_pos[:, gated_mask] = 0.0
        pool_ret_gated = np.zeros(n)
        for t in range(1, n):
            pool_ret_gated[t] = float(np.nanmean(gated_pool_pos[:, t - 1] * asset_ret[:, t]))
        # turnover cost: only count trades on NON-gated days
        pool_turn = np.zeros(n)
        pool_pos_prev = np.concatenate([np.zeros((n_perps, 1)), pool_pos[:, :-1]], axis=1)
        gated_pool_pos_prev = np.where(gated_mask[np.newaxis, :], 0.0, pool_pos_prev)
        # per-day turnover = mean abs position change across perps
        diffs = np.abs(np.diff(gated_pool_pos, axis=1))  # [n_perps, n-1]
        pool_turn[1:] = diffs.mean(axis=0)
        # cost = pool_turn * cost_bps * 1e-4 (R47's convention)
        # we don't have cost_bps here — use 5.0 default
        cost_bps = 5.0
        pool_ret_gated -= pool_turn * cost_bps * 1e-4
        return {
            "pool_returns_gated": pool_ret_gated,
            "pool_position_gated": gated_pool_pos,
            "gated_mask": gated_mask,
            "n_gated_days": int(gated_mask.sum()),
            "frac_gated": float(gated_mask.mean()),
        }
    else:
        raise NotImplementedError("per_perp_pos path")


def _walk_forward_folds(dates, pool_ret, factors, *, n_folds=4):
    """dates may be ISO strings OR ms ints; we keep both as raw."""
    n = len(dates)
    fold_size = n // n_folds
    out = []
    for k in range(n_folds):
        if k < n_folds - 1:
            sl = slice(k * fold_size, (k + 1) * fold_size)
        else:
            sl = slice(k * fold_size, n)
        seg_dates = dates[sl]
        seg_ret = pool_ret[sl]
        seg_factors = {kk: vv[sl] for kk, vv in factors.items()}
        if len(seg_ret) > 30:
            a = _alpha_t_new_west(seg_ret, seg_factors)
            sh = float(np.nanmean(seg_ret) / max(np.nanstd(seg_ret), 1e-12) * np.sqrt(365))
            # try to coerce dates to ms for label
            try:
                d0 = int(seg_dates[0])
                d1 = int(seg_dates[-1])
            except (ValueError, TypeError):
                d0 = str(seg_dates[0])
                d1 = str(seg_dates[-1])
            out.append({"fold": k + 1, "dates": (d0, d1),
                        "n_days": len(seg_ret), "ann_sharpe": round(sh, 2),
                        "alpha_t": a["alpha_t"], "alpha_ann_pct": a["alpha_ann_pct"]})
        else:
            out.append({"fold": k + 1, "n_days": len(seg_ret), "alpha_t": None})
    return out


def main():
    print("=" * 72)
    print("REGIME-GATED POOLED BOOK — R49 candidate, 2026-07-20")
    print("=" * 72)

    print("\n[1] Loading HL pooled panel (R47 canonical config)…")
    panel = load_hyperliquid_panel(min_history_days=365, max_perps=50)
    canonical = build_pooled_book(panel, thr=1.0, hold=10, vol_mult=1.10, cost_bps=5.0)
    factors = build_factors(canonical)
    dates = canonical["dates"]
    pool_ret = canonical["pool_returns"]
    print(f"  {canonical['n_perps']} perps × {len(dates)} days")

    # panel.symbols is lower-case; canonical uses lower too. Build sym lookup for BTC.
    syms_lower = [s.lower() for s in panel.symbols]
    btc_idx = syms_lower.index("btc") if "btc" in syms_lower else None

    # Compute fold boundaries on this panel's actual dates (panel uses ISO date strings)
    def _date_to_ms(s):
        from datetime import datetime
        return int(datetime.fromisoformat(s).replace(tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)

    dates_ms = np.array([_date_to_ms(d) for d in dates], dtype=np.int64)
    print(f"  range: {dates_ms[0]} → {dates_ms[-1]}")
    f1_end = F1_END
    f2_end = F2_END
    f3_end = F3_END

    # ─── BASELINE: no gate ────────────────────────────────────────────
    print("\n[2] BASELINE (no gate) — R47 reproduced:")
    folds_baseline = _walk_forward_folds(dates, pool_ret, factors, n_folds=4)
    for f in folds_baseline:
        print(f"  F{f['fold']}: annSR {f['ann_sharpe']:+.2f}, α_t {f['alpha_t']:+.2f}, "
              f"α_ann {f['alpha_ann_pct']:+.2f}%, n={f['n_days']}")

    # Canonical OOS (last 20%) alpha_t for baseline
    n = len(dates)
    cutoff = int(n * 0.80)
    base_oos = pool_ret[cutoff:]
    base_factors_oos = {k: v[cutoff:] for k, v in factors.items()}
    base_oos_alpha = _alpha_t_new_west(base_oos, base_factors_oos)
    print(f"  Canonical OOS α_t: {base_oos_alpha['alpha_t']:+.2f} (ann {base_oos_alpha['alpha_ann_pct']:+.2f}%)")

    # ─── Candidate regime signals ────────────────────────────────────
    print("\n[3] Computing candidate regime signals…")

    # S1: BTC funding acceleration
    s1_dates, s1_vals = btc_funding_acceleration()
    s1_dates = np.array(s1_dates, dtype=np.int64)
    # S2: cross-class crowded count
    s2_dates, s2_vals = cross_class_crowded_count()
    s2_dates = np.array(s2_dates, dtype=np.int64)
    s2_frac = s2_vals / 46.0  # 46 non-BTC perps

    # S3: basket-vs-BTC 30d spread (canonical asset_returns is indexed by panel.symbols order)
    asset_ret = canonical["asset_returns"]
    if btc_idx is not None:
        basket = np.nanmean(asset_ret, axis=0)
        basket = np.where(np.isnan(basket), 0.0, basket)
        diff = basket - asset_ret[btc_idx]
        s3_roll = np.full(len(dates), np.nan)
        for k in range(30, len(dates)):
            s3_roll[k] = float(np.nansum(diff[k-30:k]))
        s3_dates = np.array(dates_ms, dtype=np.int64)
        s3_vals = s3_roll
    else:
        s3_dates = np.array([], dtype=np.int64)
        s3_vals = np.array([])

    # ─── Gate sweep ──────────────────────────────────────────────────
    print("\n[4] Gate sweep (matrix):\n")
    rows = []

    # S1 thresholds (above): z > 0.0, 0.5, 1.0
    for thr in [0.0, 0.5, 1.0]:
        gated = _gate_book_v2(canonical, s1_dates, s1_vals, thr, mode="above")
        gw_ret = gated["pool_returns_gated"]
        folds = _walk_forward_folds(dates, gw_ret, factors, n_folds=4)
        oos = gw_ret[cutoff:]
        oos_a = _alpha_t_new_west(oos, base_factors_oos)
        rows.append(("S1_btc_z>thr", thr, gated["frac_gated"], oos_a["alpha_t"], folds))

    # S2 thresholds (above): fraction of perps in 90th-pct band
    for thr in [0.10, 0.20, 0.30]:
        gated = _gate_book_v2(canonical, s2_dates, s2_frac, thr, mode="above")
        gw_ret = gated["pool_returns_gated"]
        folds = _walk_forward_folds(dates, gw_ret, factors, n_folds=4)
        oos = gw_ret[cutoff:]
        oos_a = _alpha_t_new_west(oos, base_factors_oos)
        rows.append(("S2_frac_crowded>thr", thr, gated["frac_gated"], oos_a["alpha_t"], folds))

    # S3 thresholds (above): basket-outperforming-BTC 30d spread
    for thr in [0.05, 0.10, 0.15]:
        gated = _gate_book_v2(canonical, s3_dates, s3_vals, thr, mode="above")
        gw_ret = gated["pool_returns_gated"]
        folds = _walk_forward_folds(dates, gw_ret, factors, n_folds=4)
        oos = gw_ret[cutoff:]
        oos_a = _alpha_t_new_west(oos, base_factors_oos)
        rows.append(("S3_basket_minus_btc>thr", thr, gated["frac_gated"], oos_a["alpha_t"], folds))

    # Also S3 below (skip when basket UNDERperforming BTC — alt season reversal)
    for thr in [-0.05, -0.10]:
        gated = _gate_book_v2(canonical, s3_dates, s3_vals, thr, mode="below")
        gw_ret = gated["pool_returns_gated"]
        folds = _walk_forward_folds(dates, gw_ret, factors, n_folds=4)
        oos = gw_ret[cutoff:]
        oos_a = _alpha_t_new_west(oos, base_factors_oos)
        rows.append(("S3_basket_minus_btc<thr", thr, gated["frac_gated"], oos_a["alpha_t"], folds))

    # Print matrix
    print(f"  {'signal':<32} {'thr':>6} {'frac_gated':>10} {'OOS α_t':>10} {'F1 α_t':>10} {'F2 α_t':>10} {'F3 α_t':>10} {'F4 α_t':>10}")
    print(f"  {'(none)':<32} {'-':>6} {'-':>10} {base_oos_alpha['alpha_t']:>+10.2f} "
          f"{folds_baseline[0]['alpha_t']:>+10.2f} {folds_baseline[1]['alpha_t']:>+10.2f} "
          f"{folds_baseline[2]['alpha_t']:>+10.2f} {folds_baseline[3]['alpha_t']:>+10.2f}")
    for sig, thr, frac, oos_a, folds in rows:
        f_strs = " ".join(f"{f['alpha_t']:>+10.2f}" for f in folds)
        print(f"  {sig:<32} {thr:>+6.2f} {frac:>10.2f} {oos_a:>+10.2f} {f_strs}")

    # Save
    import json
    out_dir = Path("reports/crowding_breadth/2026-07-20_regime_gate")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "sweep_results.json", "w") as f:
        json.dump({
            "baseline": {"oos_alpha_t": base_oos_alpha["alpha_t"],
                         "folds": folds_baseline},
            "gated": [{"signal": s, "threshold": t, "frac_gated": fg,
                       "oos_alpha_t": oa, "folds": fl}
                      for s, t, fg, oa, fl in rows],
        }, f, indent=2)
    print(f"\nWrote {out_dir / 'sweep_results.json'}")


if __name__ == "__main__":
    main()