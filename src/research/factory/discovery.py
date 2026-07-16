"""
Discovery → Feature-Extraction → Real-Scenario pipeline (Seth 2026-07-15, Jazz's philosophy).
==============================================================================================

Jazz's correction: good strategies are BORN from overfitting — you must ALLOW it in discovery,
then extract the invariant FEATURE (not the overfit parameter), then validate under real
conditions. And the process is 输多赢少 (lose-more-win-less) — that's the baseline, not a failure.

So this is a 3-stage pipeline, not a one-shot gate:
  STAGE 1 — DISCOVERY (allow overfit): for each signal FAMILY, sweep its parameter and take the
            in-sample-best config. This is deliberately overfit — its job is to surface "this
            family carries signal", not to be traded.
  STAGE 2 — FEATURE EXTRACTION: don't keep the single overfit param. Build the param-ROBUST
            feature = blend of the family across its whole positive-in-sample band. This keeps
            the economic driver (momentum exists) and discards the fragile point (exactly 97d).
  STAGE 3 — REAL-SCENARIO: evaluate the EXTRACTED feature out-of-sample (net of funding+cost).
            Hypothesis we test honestly: the extracted (robust) feature survives OOS BETTER than
            the overfit best-param point. If so, the pipeline is doing its job.

Reuses factory internals. Pure numpy.
"""
from __future__ import annotations

import numpy as np

from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE, load_binance_panel
from src.research.factory.signal_factory import (
    _bt, _xs_weights, _roll_ret, _roll_std, _roll_skew, _roll_downside)


def _sr(x):
    x = np.asarray(x)
    return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0


def run(start=(2024, 1, 1)) -> dict:
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])

    # families: name → (param grid, param→weight-matrix)
    families = {
        "momentum":     ([30, 60, 90, 120, 180], +1.0, lambda k: _roll_ret(close, k)),
        "reversal":     ([3, 7, 14],              -1.0, lambda k: _roll_ret(close, k)),
        "lowvol":       ([10, 30, 60],            -1.0, lambda k: _roll_std(ret, k)),
        "downside_vol": ([20, 40, 60],            -1.0, lambda k: _roll_downside(ret, k)),
    }
    warm = 180
    T_full = close.shape[0] - warm
    split = int(T_full * 0.6)                      # train = first 60% (discovery + extraction)

    out = {}
    overfit_pnls, extracted_pnls = {}, {}
    for fam, (grid, sign, scorer) in families.items():
        per_param = {}
        for k in grid:
            W = _xs_weights(scorer(k), sign=sign)
            pnl = _bt(W, ret, fsum)[warm:]
            per_param[k] = (W, pnl)
        # STAGE 1 — discovery: best IS (overfit) param
        is_sr = {k: _sr(per_param[k][1][:split]) for k in grid}
        best_k = max(grid, key=lambda k: is_sr[k])
        # STAGE 2 — extraction: param-robust feature = blend of W over positive-IS band
        band = [k for k in grid if is_sr[k] > 0] or [best_k]
        Wext = np.mean([per_param[k][0] for k in band], axis=0)
        # renormalise gross to 1 per day
        g = np.abs(Wext).sum(1, keepdims=True); g[g == 0] = 1.0
        Wext = Wext / g
        ext_pnl = _bt(Wext, ret, fsum)[warm:]
        # STAGE 3 — real-scenario: OOS Sharpe of overfit-best vs extracted-robust
        overfit_oos = _sr(per_param[best_k][1][split:])
        extracted_oos = _sr(ext_pnl[split:])
        out[fam] = {"best_param": best_k, "band": band,
                    "overfit_IS_sharpe": round(is_sr[best_k], 2),
                    "overfit_OOS_sharpe": round(overfit_oos, 2),
                    "extracted_OOS_sharpe": round(extracted_oos, 2),
                    "extraction_helps": extracted_oos >= overfit_oos - 0.05}
        overfit_pnls[fam] = per_param[best_k][1]
        extracted_pnls[fam] = ext_pnl

    # aggregate: how often did extraction hold up vs the overfit point?
    held = sum(1 for f in out.values() if f["extraction_helps"])
    mean_overfit_oos = round(float(np.mean([f["overfit_OOS_sharpe"] for f in out.values()])), 2)
    mean_extracted_oos = round(float(np.mean([f["extracted_OOS_sharpe"] for f in out.values()])), 2)
    mean_is = round(float(np.mean([f["overfit_IS_sharpe"] for f in out.values()])), 2)
    return {"families": out, "n_families": len(out),
            "extraction_held_in": f"{held}/{len(out)}",
            "mean_IS_overfit": mean_is,
            "mean_OOS_overfit_point": mean_overfit_oos,
            "mean_OOS_extracted_robust": mean_extracted_oos}


def _extract_feature(close, ret, fsum, scorer, sign, grid, split) -> np.ndarray:
    """Stage 1+2 for one family: pick positive-in-sample band, return the param-ROBUST weight
    matrix (blend across the band). The economic driver, not the overfit knob."""
    per = {}
    for k in grid:
        per[k] = _xs_weights(scorer(k), sign=sign)
    warm = 180
    issr = {}
    for k in grid:
        pnl = _bt(per[k], ret, fsum)[warm:]
        issr[k] = _sr(pnl[:split])
    band = [k for k in grid if issr[k] > 0] or [max(grid, key=lambda k: issr[k])]
    We = np.mean([per[k] for k in band], axis=0)
    g = np.abs(We).sum(1, keepdims=True); g[g == 0] = 1.0
    return We / g


def extracted_library(close, ret, fmean, fsum, split) -> dict:
    """The factory's FRONT STAGE done right: parametric families enter as param-robust EXTRACTED
    features (band selected on train only), plus the cause signals. This is the input the gate
    (DSR/PBO/walk-forward) should see — not overfit param-points."""
    from src.research.factory.signal_factory import positioning_weights, _roll_beta_idio
    fams = {
        "momentum":     ([30, 60, 90, 120, 180], +1.0, lambda k: _roll_ret(close, k)),
        "reversal":     ([3, 7, 14],              -1.0, lambda k: _roll_ret(close, k)),
        "lowvol":       ([10, 30, 60],            -1.0, lambda k: _roll_std(ret, k)),
        "downside_vol": ([20, 40, 60],            -1.0, lambda k: _roll_downside(ret, k)),
        "neg_skew":     ([30, 60, 90],            -1.0, lambda k: _roll_skew(ret, k)),
    }
    lib = {f"{name}_extracted": _extract_feature(close, ret, fsum, sc, sg, grid, split)
           for name, (grid, sg, sc) in fams.items()}
    lib["positioning_funding"] = positioning_weights(fmean, kwin=7)   # the validated cause
    beta60, idio60 = _roll_beta_idio(ret, 60)
    lib["betting_against_beta"] = _xs_weights(beta60, sign=-1.0)
    return lib


def pipeline(start=(2024, 1, 1), _cache=None) -> dict:
    """End-to-end: discover→extract (front) → DSR gate → orthogonal nucleus → combine → OOS.
    Every candidate the gate sees is already a param-robust extracted feature."""
    if _cache is not None:
        close, fmean, fsum = _cache["close"], _cache["fmean"], _cache["fsum"]
    else:
        _, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    warm = 180
    split = int((close.shape[0] - warm) * 0.6)
    from src.research.validation.deflated_sharpe import evaluate_universe
    from src.research.validation.portfolio_combiner import combine
    lib = extracted_library(close, ret, fmean, fsum, split)
    series = {n: _bt(W, ret, fsum)[warm:] for n, W in lib.items()}
    evals = evaluate_universe({n: list(s) for n, s in series.items()}, dsr_threshold=0.95)
    ann = {n: round(_sr(s), 2) for n, s in series.items()}
    # orthogonal nucleus (positive + |corr|<0.6), then OOS via train-fit blend
    names = list(series)
    cand = [n for n in names if _sr(series[n][:split]) > 0.1]
    nucleus = []
    for n in sorted(cand, key=lambda x: -ann[x]):
        if not nucleus or max(abs(np.corrcoef(series[n], series[m])[0, 1]) for m in nucleus) < 0.6:
            nucleus.append(n)
    comb = None; oos = None
    if len(nucleus) >= 2:
        rbs = {n: {i: float(v) for i, v in enumerate(series[n])} for n in nucleus}
        comb = combine(rbs)
        M = np.array([series[n] for n in nucleus]).T
        wtr = combine({n: {i: float(v) for i, v in enumerate(series[n][:split])} for n in nucleus}).weights
        wv = np.array([wtr.get(n, 0) for n in nucleus])
        oos = round(_sr((M[split + 5:]) @ wv), 2)
    return {"n_candidates": len(lib), "ann_sharpe": ann, "nucleus": nucleus,
            "combined_in_sample": comb.port_sharpe_ann if comb else None,
            "enb": comb.enb if comb else None, "combined_oos": oos}


if __name__ == "__main__":
    r = run()
    print(f"\n=== DISCOVERY → EXTRACTION → REAL-SCENARIO ({r['n_families']} families) ===\n")
    print(f"{'family':14} {'best_k':>7} {'IS(overfit)':>12} {'OOS(overfit)':>13} {'OOS(extracted)':>15}")
    for fam, d in r["families"].items():
        print(f"{fam:14} {d['best_param']:>7} {d['overfit_IS_sharpe']:>12} "
              f"{d['overfit_OOS_sharpe']:>13} {d['extracted_OOS_sharpe']:>15}")
    print(f"\nmean IS (overfit):           {r['mean_IS_overfit']}")
    print(f"mean OOS (overfit point):    {r['mean_OOS_overfit_point']}   ← in-sample inflation collapses")
    print(f"mean OOS (extracted robust): {r['mean_OOS_extracted_robust']}   ← the feature, not the param")
    print(f"extraction held up in:       {r['extraction_held_in']} families")
    print("\n输多赢少 by design: we overfit to DISCOVER, extract to SURVIVE, and most still won't clear real-scenario.")
