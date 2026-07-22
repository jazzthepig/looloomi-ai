"""
Noise-injection robustness — does the edge survive when half the inputs are garbage?
====================================================================================

Borrowed from the CMDMamba benchmark methodology (2026-07-21). Their result is the argument
for the gate: replacing a growing fraction of input features with pure noise degraded a
selective-SSM by **6.6%** and a Transformer by **22.1%**. The model that leaned on genuine
signal survived; the one that had memorised spurious feature correlations collapsed.

WHY WE NEED THIS — it catches a failure mode none of our existing gates see:

  · `deflated_sharpe` / `pbo`  → catch selection across MANY TRIALS
  · `factor_absorption`        → catches "old wine" (known factor in a new bottle)
  · `regime_robustness`        → catches one-window mirages
  · `pit_guard`                → catches temporal leakage
  · **noise_injection**        → catches **dependence on fragile feature correlations**

A sleeve can be significant, unabsorbed, regime-broad and leak-free while still resting on a
handful of incidental feature relationships that will not persist. That is invisible to every
gate above, because they all operate on the *output* return series. This gate perturbs the
*inputs* and is therefore the only one that probes the mechanism itself.

⚠️ THE INTERFACE IS THE POINT — this gate needs a **re-runnable** candidate: `signal_fn(features)
→ returns`, not a saved return series. Many of our sleeves exist only as stored equity curves and
therefore **cannot** be noise-tested. That is itself a finding: an edge you cannot re-run on
perturbed inputs is an edge you cannot interrogate. Treat inability to run this gate as a
research-debt flag, not a pass.

Noise is **moment-matched** per column (same mean/std as the feature it replaces), so degradation
measures loss of *information*, not a distribution shift the model was never built for.
"""
from __future__ import annotations

import math

import numpy as np


def _sharpe(r: np.ndarray, ppy: int) -> float:
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 20 or r.std() == 0:
        return float("nan")
    return float(r.mean() / r.std() * math.sqrt(ppy))


def _corrupt(X: np.ndarray, frac: float, rng: np.random.Generator) -> np.ndarray:
    """Replace `frac` of COLUMNS with moment-matched Gaussian noise.

    Column-wise (not element-wise) is deliberate: it simulates a feature going dead or becoming
    uninformative, which is how features actually fail in production — a data source degrades, a
    venue changes semantics, a regime makes a metric meaningless.
    """
    Xc = np.array(X, dtype=float, copy=True)
    k = X.shape[1]
    n_bad = int(round(frac * k))
    if n_bad <= 0:
        return Xc
    cols = rng.choice(k, size=min(n_bad, k), replace=False)
    for c in cols:
        col = X[:, c]
        good = col[~np.isnan(col)]
        mu = float(good.mean()) if len(good) else 0.0
        sd = float(good.std()) if len(good) and good.std() > 0 else 1.0
        Xc[:, c] = rng.normal(mu, sd, size=X.shape[0])
    return Xc


def noise_robustness(signal_fn, features: np.ndarray, *, levels=(0.0, 0.25, 0.5, 1.0),
                     n_trials: int = 8, periods_per_year: int = 365,
                     max_degradation: float = 0.35, seed: int = 0) -> dict:
    """Re-run the candidate with a rising fraction of features replaced by noise.

    `signal_fn(features) -> returns` must be deterministic given its input and must NOT close over
    the clean features (that would silently defeat the test).

    Pass criteria — both must hold:
      1. degradation at **50% noise** ≤ `max_degradation` (default 35%)
      2. Sharpe at 50% noise still positive
    A candidate whose edge survives half its inputs being garbage is resting on mechanism.
    One that collapses was resting on feature correlations.
    """
    X = np.asarray(features, dtype=float)
    if X.ndim != 2:
        raise ValueError("features must be 2-D (observations × features)")
    rng = np.random.default_rng(seed)

    base = _sharpe(np.asarray(signal_fn(X), dtype=float), periods_per_year)
    if math.isnan(base) or base <= 0:
        return {"passed": None, "skipped": True, "baseline_sharpe": None,
                "note": "baseline Sharpe is NaN or ≤0 — nothing to degrade"}

    curve = {}
    for lvl in levels:
        if lvl == 0.0:
            curve[lvl] = base
            continue
        vals = []
        for _ in range(n_trials):
            try:
                s = _sharpe(np.asarray(signal_fn(_corrupt(X, lvl, rng)), dtype=float),
                            periods_per_year)
            except Exception:
                s = float("nan")
            if not math.isnan(s):
                vals.append(s)
        curve[lvl] = float(np.mean(vals)) if vals else float("nan")

    half = curve.get(0.5, float("nan"))
    degr = float("nan") if math.isnan(half) else (base - half) / abs(base)
    passed = (not math.isnan(degr)) and degr <= max_degradation and half > 0

    if math.isnan(degr):
        verdict = "INCONCLUSIVE — candidate failed to evaluate under noise"
    elif passed:
        verdict = (f"ROBUST — retains {(1-degr)*100:.0f}% of edge with half the features replaced "
                   f"by noise; rests on mechanism")
    elif half <= 0:
        verdict = "FRAGILE — edge INVERTS or vanishes at 50% noise; rests on feature correlations"
    else:
        verdict = (f"FRAGILE — loses {degr*100:.0f}% of edge at 50% noise "
                   f"(threshold {max_degradation*100:.0f}%)")

    return {"passed": passed, "skipped": False,
            "baseline_sharpe": round(base, 3),
            "sharpe_by_noise": {str(k): (None if math.isnan(v) else round(v, 3))
                                for k, v in curve.items()},
            "degradation_at_50pct": None if math.isnan(degr) else round(degr, 3),
            "max_degradation": max_degradation,
            "n_trials": n_trials, "verdict": verdict}


def format_report(res: dict) -> str:
    if res.get("skipped"):
        return f"NOISE INJECTION — skipped: {res.get('note','')}"
    L = ["NOISE-INJECTION ROBUSTNESS", "=" * 46,
         f"baseline Sharpe {res['baseline_sharpe']:+.2f}", ""]
    base = res["baseline_sharpe"] or 1.0
    for lvl, s in res["sharpe_by_noise"].items():
        pct = float(lvl) * 100
        # bar is RELATIVE to baseline (40 chars = full edge retained)
        bar = "" if s is None else "█" * max(0, min(40, int(round(40 * s / abs(base)))))
        L.append(f"  {pct:5.0f}% noise → {('  n/a' if s is None else f'{s:+.2f}')}  {bar}")
    L.append("")
    L.append(("✓ " if res["passed"] else "✗ ") + res["verdict"])
    return "\n".join(L)


if __name__ == "__main__":
    rng = np.random.default_rng(3)
    N, K = 900, 12
    driver = rng.normal(0, 1, N)                     # the true underlying cause
    X = rng.normal(0, 1, (N, K))
    # the cause is REDUNDANTLY visible in the first 6 features (noisy proxies of one mechanism)
    for c in range(6):
        X[:, c] = driver + rng.normal(0, 0.6, N)
    fwd = driver * 0.02 + rng.normal(0, 0.01, N)     # forward return driven by the cause

    # A: ROBUST — reads the mechanism through whichever proxies survive (redundant signal path)
    def robust_fn(f):
        return np.sign(f[:, :6].mean(axis=1)) * fwd

    # B: FRAGILE — same edge, but demands UNANIMITY across all 6 proxies. Real in-sample, and
    # any single corrupted feature breaks the agreement it depends on.
    def fragile_fn(f):
        s = np.sign(f[:, :6])
        unanimous = np.abs(s.sum(axis=1)) == 6
        return np.where(unanimous, s[:, 0], 0.0) * fwd

    print(format_report(noise_robustness(robust_fn, X)))
    print()
    print(format_report(noise_robustness(fragile_fn, X)))
