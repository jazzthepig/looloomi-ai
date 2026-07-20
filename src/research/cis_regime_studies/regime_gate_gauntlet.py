"""R49 gauntlet run — full signal_gauntlet on the best regime-gated variant.

The regime_gate_sweep.py matrix showed S3_basket_minus_btc > 0.10 gives the best OOS
α_t = +1.19 (small improvement over baseline +1.04). But all gates failed to cleanly
destroy F1. This script runs the FULL signal gauntlet on that best variant to get the
formal verdict, then writes the R49 REPORT.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.research.cis_regime_studies.funding_crowding_breadth import (
    load_hyperliquid_panel, build_pooled_book, build_factors, _alpha_t_new_west,
)
from src.research.cis_regime_studies.regime_gate_sweep import _gate_book_v2, _walk_forward_folds
from src.research.validation.signal_gauntlet import run_gauntlet


def main():
    panel = load_hyperliquid_panel(min_history_days=365, max_perps=50)
    canonical = build_pooled_book(panel, thr=1.0, hold=10, vol_mult=1.10, cost_bps=5.0)
    factors = build_factors(canonical)
    dates = canonical["dates"]
    pool_ret = canonical["pool_returns"]
    n = len(dates)
    cutoff = int(n * 0.80)

    syms_lower = [s.lower() for s in panel.symbols]
    btc_idx = syms_lower.index("btc") if "btc" in syms_lower else None
    asset_ret = canonical["asset_returns"]

    # Build S3 signal: 30d rolling sum of (basket - BTC)
    from datetime import datetime, timezone
    def _date_to_ms(s):
        if isinstance(s, (int, np.integer)):
            return int(s)
        return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)
    dates_ms = np.array([_date_to_ms(d) for d in dates], dtype=np.int64)

    basket = np.nanmean(asset_ret, axis=0)
    basket = np.where(np.isnan(basket), 0.0, basket)
    diff = basket - asset_ret[btc_idx]
    s3_roll = np.full(len(dates), np.nan)
    for k in range(30, len(dates)):
        s3_roll[k] = float(np.nansum(diff[k-30:k]))

    # Build canonical OOS factors once
    factors_oos = {k: v[cutoff:] for k, v in factors.items()}

    # ─── Baseline gauntlet ────────────────────────────────────────────
    print("=" * 72)
    print("BASELINE GAUNTLET (no gate, R47 reproduced)")
    print("=" * 72)
    oos_ret = pool_ret[cutoff:]
    g_base = run_gauntlet("crowding_breadth_r49_baseline", oos_ret, factors=factors_oos)
    print(f"  verdict: {g_base['verdict']}")
    print(f"  funnel:  {g_base['funnel']}")
    for st in g_base["stages"]:
        print(f"    {st['stage']:<25} pass={st['passed']} metric={st.get('metric', {})}")

    # ─── Best gated variant: S3_basket_minus_btc > 0.10 ───────────────
    print()
    print("=" * 72)
    print("REGIME-GATED GAUNTLET (S3_basket_minus_btc > 0.10, fires 12% of days)")
    print("=" * 72)
    gated = _gate_book_v2(canonical, dates_ms, s3_roll, 0.10, mode="above")
    oos_ret_g = gated["pool_returns_gated"][cutoff:]
    g_gated = run_gauntlet("crowding_breadth_r49_gated_s3", oos_ret_g, factors=factors_oos)
    print(f"  verdict: {g_gated['verdict']}")
    print(f"  funnel:  {g_gated['funnel']}")
    for st in g_gated["stages"]:
        print(f"    {st['stage']:<25} pass={st['passed']} metric={st.get('metric', {})}")

    # ─── Variant sweep on gated book ──────────────────────────────────
    print()
    print("=" * 72)
    print("GATED variant sweep (canonical OOS alpha_t per config)")
    print("=" * 72)
    variant_specs = [
        ("thr_0.5_hold_10", dict(thr=0.5, hold=10)),
        ("thr_1.0_hold_10", dict(thr=1.0, hold=10)),
        ("thr_1.5_hold_10", dict(thr=1.5, hold=10)),
        ("thr_1.0_hold_5",  dict(thr=1.0, hold=5)),
        ("thr_1.0_hold_15", dict(thr=1.0, hold=15)),
    ]
    print(f"  {'variant':<25} {'OOS α_t':>10} {'F1 α_t':>10} {'F2 α_t':>10} {'F3 α_t':>10} {'F4 α_t':>10}")
    for name, cfg in variant_specs:
        v_canonical = build_pooled_book(panel, cost_bps=5.0, **cfg)
        v_factors = build_factors(v_canonical)
        g_v = _gate_book_v2(v_canonical, dates_ms, s3_roll, 0.10, mode="above")
        v_ret = g_v["pool_returns_gated"]
        v_oos = v_ret[cutoff:]
        v_factors_oos = {k: v[cutoff:] for k, v in v_factors.items()}
        a_oos = _alpha_t_new_west(v_oos, v_factors_oos)
        folds = _walk_forward_folds(dates, v_ret, v_factors, n_folds=4)
        f_strs = " ".join(f"{f['alpha_t']:>+10.2f}" for f in folds)
        print(f"  {name:<25} {a_oos['alpha_t']:>+10.2f} {f_strs}")

    # Save
    out_dir = Path("reports/crowding_breadth/2026-07-20_regime_gate")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "gauntlet_results.json", "w") as f:
        json.dump({
            "baseline": {"verdict": g_base["verdict"], "funnel": g_base["funnel"],
                         "stages": g_base["stages"]},
            "gated_S3_btc_minus_basket_gt_0.10": {"verdict": g_gated["verdict"],
                                                  "funnel": g_gated["funnel"],
                                                  "stages": g_gated["stages"]},
        }, f, indent=2)
    print(f"\nWrote {out_dir / 'gauntlet_results.json'}")


if __name__ == "__main__":
    main()