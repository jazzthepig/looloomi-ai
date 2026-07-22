"""
Beta-adjusted alpha — the production yardstick (Seth, 2026-07-21).
===================================================================

**Why this module exists (R61 → R62).** For a year the live track record measured
`alpha = a_ret − b_ret`. That is only alpha if the asset's beta to its benchmark is 1.0. Ours is
**1.4 – 2.4**. So the published number was **leveraged beta**, and in a bear-dominated window it
made a genuinely strong signal look *inverted*:

    signal              raw edge     β-adjusted edge      t
    OUTPERFORM           −0.36           +2.86          +5.75
    STRONG OUTPERFORM    +3.42           +8.06          +5.41
    UNDERPERFORM         +1.67           +1.00          +4.48
    UNDERWEIGHT          −1.00           −4.10          −3.79   ← the one real defect

We spent weeks concluding our edges were weak because of a broken instrument. Meta-lesson #21:
**audit the METRIC before the MODEL.**

**Point-in-time discipline.** Beta at time *t* uses ONLY observations strictly before *t*. Estimating
beta on the full sample is the same look-ahead bug found in `interpretation_c.py` the same day —
it would leak future covariance into historical scores. `estimate_beta_pit` is expanding-window and
never sees the row it is adjusting.

**Interpretation — publish both, and label them.** β-adjusted alpha is the *hedged* excess return:
capturing it requires shorting the benchmark. An unhedged holder experiences the RAW number. Report
`alpha_raw` and `alpha_beta_adj` side by side; presenting only the adjusted figure would overstate
what an investor actually receives.

Compliance: measurement utility. Positioning language only in any surfaced output.
"""
from __future__ import annotations

import math

MIN_PRIORS = 20          # below this, beta is noise — return None rather than a bad number
DEFAULT_BETA = 1.0       # only for explicit fallback; callers should prefer None-handling


def estimate_beta_pit(prior_a: list[float], prior_b: list[float],
                      min_priors: int = MIN_PRIORS) -> float | None:
    """OLS beta of asset returns on benchmark returns using ONLY prior observations.

    Returns None when there is insufficient history or the benchmark has no variance — callers must
    handle None explicitly rather than silently substituting 1.0, otherwise unadjusted rows leak
    into an 'adjusted' series and the whole point is lost.
    """
    n = min(len(prior_a), len(prior_b))
    if n < min_priors:
        return None
    a, b = prior_a[-n:], prior_b[-n:]
    sa, sb = sum(a), sum(b)
    sab = sum(x * y for x, y in zip(a, b))
    sbb = sum(y * y for y in b)
    var = sbb - sb * sb / n
    if abs(var) < 1e-12:
        return None
    beta = (sab - sa * sb / n) / var
    if not math.isfinite(beta):
        return None
    return float(beta)


def beta_adjusted_alpha(a_ret: float, b_ret: float, beta: float | None) -> float | None:
    """`a_ret − β·b_ret`. None beta ⇒ None (do NOT fall back to raw and call it adjusted)."""
    if beta is None or a_ret is None or b_ret is None:
        return None
    return float(a_ret) - float(beta) * float(b_ret)


def directional_edge(signal: str, alpha: float | None) -> float | None:
    """Score alpha against the signal's own directional claim: positive = the call was right.

    Compliance-safe positioning vocabulary only. NEUTRAL makes no directional claim ⇒ None.
    Without this, UNDERPERFORM's correct negative alpha is scored as a loss (the R61 mistake).
    """
    if alpha is None:
        return None
    s = (signal or "").strip().upper()
    if s in ("STRONG OUTPERFORM", "OUTPERFORM"):
        return float(alpha)
    if s in ("UNDERPERFORM", "UNDERWEIGHT"):
        return -float(alpha)
    return None


def enrich_rows(rows: list[dict], *, symbol_key: str = "symbol", a_key: str = "a_ret",
                b_key: str = "b_ret", signal_key: str = "signal",
                min_priors: int = MIN_PRIORS) -> list[dict]:
    """Add `beta_pit`, `alpha_beta_adj`, `edge_beta_adj` to chronologically-ordered rows.

    Rows MUST already be sorted oldest→newest; beta for each row is estimated only from that
    symbol's earlier rows. Rows without enough history get None (not a guess) — expect roughly the
    first `min_priors` observations per symbol to be unadjustable, which is correct and honest.
    """
    hist: dict[str, tuple[list, list]] = {}
    out = []
    for r in rows:
        sym = r.get(symbol_key)
        a, b = r.get(a_key), r.get(b_key)
        pa, pb = hist.setdefault(sym, ([], []))
        beta = estimate_beta_pit(pa, pb, min_priors)
        adj = beta_adjusted_alpha(a, b, beta)
        out.append({**r,
                    "beta_pit": None if beta is None else round(beta, 4),
                    "alpha_raw": None if (a is None or b is None) else round(float(a) - float(b), 6),
                    "alpha_beta_adj": None if adj is None else round(adj, 6),
                    "edge_beta_adj": directional_edge(r.get(signal_key), adj)})
        if a is not None and b is not None:
            pa.append(float(a)); pb.append(float(b))
    return out


def summarize(enriched: list[dict]) -> dict:
    """Per-signal {n, mean_edge, t_stat} on the β-adjusted directional edge — the honest scorecard."""
    buckets: dict[str, list[float]] = {}
    for r in enriched:
        e = r.get("edge_beta_adj")
        if e is not None:
            buckets.setdefault(r.get("signal", "?"), []).append(float(e))
    out = {}
    for sig, vals in buckets.items():
        n = len(vals)
        if n < 2:
            out[sig] = {"n": n, "mean_edge": None, "t_stat": None}
            continue
        mu = sum(vals) / n
        var = sum((v - mu) ** 2 for v in vals) / (n - 1)
        sd = math.sqrt(var)
        out[sig] = {"n": n, "mean_edge": round(mu, 4),
                    "t_stat": None if sd < 1e-12 else round(mu / sd * math.sqrt(n), 2)}
    return out
