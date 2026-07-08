"""
Edge-map shrinkage — empirical-Bayes regularization of the signal × risk-band alpha grid.

The problem: with ~100 days of outcomes the edge-map cells are wildly uneven — some have
n>1500, some have n=1 (a single 30-day outcome). A raw thin cell is pure noise (OUTPERFORM /
deep-off read −64% on n=3). The old fix was a hard n-cutoff — which THROWS AWAY the thin cells.

The right fix (AQR/Millennium standard) is to SHRINK, not discard: pull each cell toward a
structural prior in proportion to how little data it has. A cell with n=1500 keeps its own
value; a cell with n=3 is almost entirely the prior; cells in between blend.

Two pieces:
  1. **Prior** = two-way ADDITIVE model  μ + tier_effect_i + band_effect_j  (n-weighted).
     This encodes the real structure — every tier improves as the tape goes risk-on — without
     assuming interaction the thin cells can't support. High-n cells keep their interaction;
     thin cells borrow the additive backbone.
  2. **Weight** = James-Stein / empirical-Bayes  w_ij = n_ij / (n_ij + K),  K = σ²_within / τ²_between
     estimated by method-of-moments from the grid itself (no per-observation data needed).

Output: a shrunk alpha per cell + the weight + the prior, so conviction/posture read a
statistically honest surface instead of raw thin-cell noise.
"""
from __future__ import annotations

_BAND_ORDER = ["1_deep_off", "2_off", "3_neutral", "4_on", "5_deep_on"]
_K_FLOOR = 5.0      # never trust a cell's own mean more than ~n/(n+5) even if τ² is huge
_K_CEIL = 400.0     # never shrink so hard that a n=1500 cell is ignored


def _wmean(pairs):
    """n-weighted mean of (value, n)."""
    sw = sum(n for _, n in pairs)
    return (sum(v * n for v, n in pairs) / sw) if sw > 0 else 0.0


def shrink_edge_map(cells: list) -> dict:
    """cells: [{signal, risk_band, n, avg_alpha_pct}]. Returns
       {"cells": {(signal,band): {raw, n, prior, weight, shrunk}}, "params": {...}}."""
    grid = {}
    for c in cells:
        try:
            sig = c["signal"]; band = c["risk_band"]
            n = float(c.get("n") or 0)
            a = float(c.get("avg_alpha_pct"))
        except (KeyError, TypeError, ValueError):
            continue
        if n <= 0:
            continue
        grid[(sig, band)] = {"raw": a, "n": n}
    if not grid:
        return {"cells": {}, "params": {}}

    tiers = sorted({s for s, _ in grid})
    bands = [b for b in _BAND_ORDER if any((s, b) in grid for s in tiers)]

    # ── two-way additive prior: μ + tier_i + band_j (all n-weighted) ──
    mu = _wmean([(v["raw"], v["n"]) for v in grid.values()])
    tier_eff = {t: _wmean([(grid[(t, b)]["raw"], grid[(t, b)]["n"]) for b in bands if (t, b) in grid]) - mu
                for t in tiers}
    band_eff = {b: _wmean([(grid[(t, b)]["raw"], grid[(t, b)]["n"]) for t in tiers if (t, b) in grid]) - mu
                for b in bands}
    for (s, b), v in grid.items():
        v["prior"] = mu + tier_eff.get(s, 0.0) + band_eff.get(b, 0.0)

    # ── method-of-moments EB: residual e = raw − prior. e ~ N(0, τ² + σ²/n). ──
    # τ² (interaction/lack-of-fit variance) from high-n cells (~zero sampling noise → e² ≈ τ²).
    # σ² (within-cell sampling variance) via the ROBUST median of (e²−τ²)·n across cells — the
    # median resists the extreme thin-cell outliers (e.g. −64% on n=3) that wreck a mean estimate.
    resid = [(v["raw"] - v["prior"], v["n"]) for v in grid.values()]
    hi = [e for e, n in resid if n >= 100]
    tau2 = max((sum(e * e for e in hi) / len(hi)) if hi else
               (sum(e * e for e, _ in resid) / len(resid)), 1e-6)
    sig_samples = sorted(max(0.0, (e * e - tau2)) * n for e, n in resid)
    m = len(sig_samples)
    sigma2 = (sig_samples[m // 2] if m % 2 else 0.5 * (sig_samples[m // 2 - 1] + sig_samples[m // 2]))
    K = min(_K_CEIL, max(_K_FLOOR, sigma2 / tau2))

    out = {}
    for (s, b), v in grid.items():
        w = v["n"] / (v["n"] + K)
        shrunk = w * v["raw"] + (1.0 - w) * v["prior"]
        out[(s, b)] = {"raw": round(v["raw"], 3), "n": int(v["n"]),
                       "prior": round(v["prior"], 3), "weight": round(w, 3),
                       "shrunk": round(shrunk, 3)}
    return {"cells": out,
            "params": {"mu": round(mu, 3), "tau2": round(tau2, 2), "sigma2": round(sigma2, 1),
                       "K": round(K, 1), "n_cells": len(out)}}


def shrunk_grid_by_signal(cells: list) -> dict:
    """Convenience: {signal: {band: shrunk_alpha}} for edge-map / conviction consumption."""
    res = shrink_edge_map(cells)
    grid = {}
    for (s, b), v in res["cells"].items():
        grid.setdefault(s, {})[b] = v["shrunk"]
    return grid
