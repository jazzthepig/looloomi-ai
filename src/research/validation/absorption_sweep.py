"""
Absorption Sweep — the one-table verdict runner for §ABSORPTION-SWEEP (Seth, 2026-07-18).
==========================================================================================
The interface that turns Minimax-C's per-sleeve daily-return CSVs into THE deliverable: a single
table saying which sleeves carry RESIDUAL alpha (orthogonal, earns a slot) vs which are ABSORBED
(repackaged known-factor beta). Wraps `factor_absorption.absorption_test` and adds the paper's
stepwise step — cross-absorb each sleeve against the OTHER sleeves to find INDEPENDENT survivors.

LANE (per CLAUDE.md): Seth owns this runner + the gate math (src/). Minimax-B/C owns the per-sleeve
return RECONSTRUCTORS on Mac-local data (/Volumes/CometCloudAI/…) and emits the CSV below.

────────────────────────────────────────────────────────────────────────────────────────────────
CSV CONTRACT (what Minimax-C emits → `run_from_csv` consumes):
  columns: date, <sleeve_1>, <sleeve_2>, …, f_market, f_momentum, f_cis_quality[, f_size]
  · one row per day; values are DAILY RETURNS as decimals (0.012 = +1.2%), net of costs.
  · factor columns are prefixed `f_` (known factors); everything else is a candidate sleeve.
  · f_market = BTC (or eq-wt majors) daily return; f_momentum = tsmom_factor(f_market, 30);
    f_cis_quality = long top-CIS / short bottom-CIS; f_size = large-minus-small (optional).
────────────────────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import numpy as np

from src.research.validation.factor_absorption import absorption_test

FACTOR_PREFIX = "f_"
_T = 1.96


def sweep(data: dict, sleeve_cols: list[str] | None = None, factor_cols: list[str] | None = None,
          nw_lags: int = 6, periods_per_year: int = 365) -> list[dict]:
    """`data`: {column_name: 1d array of aligned daily returns} (factors prefixed 'f_'). Returns one
    verdict row per sleeve: raw vs residual alpha (after known factors) AND alpha vs peers
    (independent-survivor test). Pure numpy — no pandas dependency."""
    cols = {k: np.asarray(v, dtype=float) for k, v in data.items() if k != "date"}
    if factor_cols is None:
        factor_cols = [c for c in cols if c.startswith(FACTOR_PREFIX)]
    if sleeve_cols is None:
        sleeve_cols = [c for c in cols if c not in factor_cols]

    def _aligned(keys):
        n = min(len(cols[k]) for k in keys)
        # align by tail + drop any row with a NaN across the used columns
        M = np.column_stack([cols[k][-n:] for k in keys])
        M = M[~np.isnan(M).any(axis=1)]
        return {k: M[:, i] for i, k in enumerate(keys)}

    rows = []
    for s in sleeve_cols:
        a = _aligned([s] + factor_cols)
        if len(a[s]) < 60:
            rows.append({"sleeve": s, "n": len(a[s]), "verdict": "INSUFFICIENT DATA (<60 obs)"})
            continue
        r = absorption_test(a[s], {f: a[f] for f in factor_cols}, nw_lags, periods_per_year)
        # stepwise: alpha AFTER known factors + all OTHER sleeves (independent-survivor test)
        others = [o for o in sleeve_cols if o != s]
        indep_t = None
        if others:
            a2 = _aligned([s] + factor_cols + others)
            if len(a2[s]) >= 60:
                r2 = absorption_test(a2[s], {**{f: a2[f] for f in factor_cols},
                                             **{o: a2[o] for o in others}}, nw_lags, periods_per_year)
                indep_t = r2["alpha_t"]
        rows.append({
            "sleeve": s, "n": r["n"],
            "raw_ann_pct": r["raw_ann_pct"], "raw_t": r["raw_t"],
            "alpha_ann_pct": r["alpha_ann_pct"], "alpha_t": r["alpha_t"],
            "alpha_t_vs_peers": indep_t,
            "r2": r["r2"], "factor_betas": r["factor_betas"],
            "residual_alpha": r["alpha_significant"],
            "independent_survivor": (indep_t is not None and abs(indep_t) > _T and r["alpha_significant"]),
            "verdict": r["verdict"],
        })
    return rows


def format_table(rows: list[dict]) -> str:
    """Human-readable one-table verdict (the deliverable)."""
    h = f"{'sleeve':20s}{'rawAnn':>9s}{'rawT':>6s}{'αAnn':>9s}{'αT':>6s}{'αT|peers':>10s}  verdict"
    out = [h, "-" * len(h)]
    for r in rows:
        if "alpha_t" not in r:
            out.append(f"{r['sleeve']:20s}{'':>40s}  {r.get('verdict','')}")
            continue
        vp = f"{r['alpha_t_vs_peers']:+.2f}" if r.get("alpha_t_vs_peers") is not None else "  —"
        tag = "★ SURVIVOR" if r["independent_survivor"] else ("residual" if r["residual_alpha"] else "ABSORBED")
        out.append(f"{r['sleeve']:20s}{r['raw_ann_pct']:>+8.1f}%{r['raw_t']:>6.2f}"
                   f"{r['alpha_ann_pct']:>+8.1f}%{r['alpha_t']:>6.2f}{vp:>10s}  {tag}")
    out.append("")
    surv = [r["sleeve"] for r in rows if r.get("independent_survivor")]
    out.append(f"INDEPENDENT SURVIVORS (α t>1.96 after factors AND after peers): {surv or 'NONE — nothing orthogonal yet'}")
    return "\n".join(out)


def run_from_csv(path: str, **kw) -> list[dict]:
    """Load Minimax-C's wide CSV (date + sleeve cols + f_* factor cols) and run the sweep."""
    import csv
    data: dict[str, list] = {}
    with open(path, newline="") as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            for k, v in row.items():
                if k == "date":
                    continue
                data.setdefault(k, []).append(float(v) if v not in ("", "nan", None) else float("nan"))
    return sweep(data, **kw)


if __name__ == "__main__":
    # SELF-TEST on synthetic data: prove the runner flags an absorbed sleeve AND an orthogonal one.
    rng = np.random.default_rng(7)
    N = 800
    mkt = rng.normal(0.001, 0.03, N)
    mom = np.sign(np.convolve(mkt, np.ones(30), "same")) * mkt   # momentum factor
    quality = rng.normal(0.0003, 0.01, N)
    absorbed = 0.6 * mkt + 0.4 * mom + rng.normal(0, 0.005, N)    # pure beta → should ABSORB
    orthogonal = 0.0009 + 0.1 * mkt + rng.normal(0, 0.01, N)      # real +0.09%/day α, low beta → SURVIVE
    data = {"absorbed_sleeve": absorbed, "orthogonal_sleeve": orthogonal,
            "f_market": mkt, "f_momentum": mom, "f_cis_quality": quality}
    print(format_table(sweep(data)))
