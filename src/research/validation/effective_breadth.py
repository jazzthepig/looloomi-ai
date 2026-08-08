"""
Effective breadth from the correlation matrix — the fix for a formula used across
three ledger entries with an unexamined premise.

WHAT WAS WRONG, PRECISELY. S-96, S-113 and S-114 all reported
`N_eff = N / (1 + (N-1)·rho_bar)`. In S-114 I flagged it as "assumes
equicorrelation" — **that flag was itself half wrong**, and the correction matters:

  · For the EQUAL-WEIGHT PORTFOLIO VARIANCE question the formula is EXACT, not an
    approximation, and it does not need equicorrelation:
        Var = sigma^2 · [1 + (N-1)·rho_bar] / N
    holds for any correlation structure, with rho_bar the mean pairwise correlation.
    What it *does* require is EQUAL VOLATILITIES — and that is the premise actually
    violated here: crypto annualised vol 0.957 against TradFi 0.392, a 2.4x gap.

  · For the BREADTH question — "how many independent bets do I have", the quantity
    in IR ≈ IC·sqrt(breadth) — the formula is simply the wrong estimator. Breadth is
    a property of the correlation matrix's SPECTRUM, not of its average entry.

THE ACTUAL LESSON, found by sanity-checking against a matrix where equicorrelation
DOES hold. At rho = 0.3, N = 20, the two measures still disagree — naive 2.99
against participation 7.38 — and both are exactly right. Eigenvalues there are one
at 1+19(0.3) = 6.7 and nineteen at 0.7; naive = 20/6.7, participation =
400/54.2. **They are not competing estimators of one quantity; they answer
different questions, and the question is set by the BOOK, not by the matrix:**

  · a LONG-ONLY book (layer ①) rides the common factor, so what limits it is
    equal-weight variance reduction ⇒ the naive figure is the correct one;
  · a MARKET-NEUTRAL book (layer ④) trades the residual directions, so what limits
    it is how many independent directions exist ⇒ participation ratio.

So "crypto is capped near N_eff 2" was right FOR THE LONG-ONLY BOOK, and 3.31 is
right for the neutral one. The real error was never the formula — it was quoting a
breadth number without saying which book it constrains.

Measured on 2026-08-08 (20 crypto + 20 TradFi, 2024-01 on):
    crypto   naive 1.95  participation 3.31  top eigenvalue 53.0% of variance
    TradFi   naive 3.43  participation 5.96  top eigenvalue 35.2%
    combined naive 3.81  participation 7.67  top eigenvalue 31.1%
Crypto's single dominant factor carrying 53% of variance against TradFi's 35% is
the precise version of "crypto is basically one bet".

TWO SPECTRAL MEASURES ARE RETURNED, because they disagree by design and the gap is
information rather than noise:
  · participation ratio  (sum(l))^2 / sum(l^2)  — dominated by the largest
    eigenvalues, so it answers "how many BIG independent directions". Conservative.
  · entropy rank  exp(-sum(p·ln p)),  p = l/sum(l)  — counts small directions too,
    so it runs higher. Optimistic.
Report both. A single number here would be a claim the data does not support.
"""
from __future__ import annotations

import numpy as np


def effective_breadth(corr: np.ndarray) -> dict:
    """Spectral effective breadth of a correlation matrix.

    `corr` must be a symmetric correlation matrix (unit diagonal). Eigenvalues are
    clipped at zero: sample correlation matrices estimated on fewer observations
    than assets are singular, and tiny negative eigenvalues are numerical, not
    economic — but if MANY are negative the matrix is rank-deficient and the
    breadth number is meaningless, which is why `rank_deficient` is returned rather
    than silently swallowed.
    """
    n = corr.shape[0]
    if corr.shape[0] != corr.shape[1]:
        raise ValueError("correlation matrix must be square")
    w = np.linalg.eigvalsh((corr + corr.T) / 2.0)          # symmetrise defensively
    # Rank deficiency shows up as eigenvalues at NUMERICAL ZERO, not as negative
    # ones. The first version of this check counted `w < -1e-8` and missed a
    # deliberately singular 30-asset / 5-observation matrix entirely, because LAPACK
    # returned those directions as +1e-17 rather than negative. Measure the rank.
    tol = max(n, 1) * float(np.finfo(float).eps) * (abs(w).max() if n else 1.0)
    numerical_rank = int((w > tol).sum())
    neg = int((w < -tol).sum())
    w = np.clip(w, 0.0, None)
    tot = w.sum()
    if tot <= 0:
        return {"n_assets": n, "participation_ratio": float("nan"),
                "entropy_rank": float("nan"), "rank_deficient": True,
                "numerical_rank": 0, "n_negative_eigenvalues": neg}
    p = w / tot
    p = p[p > 1e-12]
    iu = np.triu_indices(n, 1)
    rho_bar = float(corr[iu].mean()) if n > 1 else float("nan")
    return {
        "n_assets": n,
        "rho_bar": rho_bar,
        # kept for continuity with S-96/S-113/S-114, explicitly labelled
        "naive_variance_neff": float(n / (1 + (n - 1) * rho_bar)) if n > 1 else 1.0,
        "participation_ratio": float(tot ** 2 / (w ** 2).sum()),
        "entropy_rank": float(np.exp(-(p * np.log(p)).sum())),
        "top_eigenvalue_share": float(w.max() / tot),
        # deficient when the matrix does not span its own dimension: a breadth
        # figure from a rank-4 matrix over 30 assets is arithmetic on noise
        "rank_deficient": numerical_rank < n,
        "numerical_rank": numerical_rank,
        "n_negative_eigenvalues": neg,
    }


def breadth_report(corr: np.ndarray, label: str = "") -> str:
    """One line, with BOTH spectral measures and the naive figure side by side.

    The naive number is printed rather than hidden precisely because three ledger
    entries quote it: seeing 1.95 next to 3.31 is what makes the correction legible
    to whoever reads those entries next."""
    r = effective_breadth(corr)
    warn = "  ⚠️ RANK-DEFICIENT" if r["rank_deficient"] else ""
    return (f"{label:24s} N={r['n_assets']:3d} rho_bar={r['rho_bar']:+.3f} "
            f"naive={r['naive_variance_neff']:5.2f} "
            f"participation={r['participation_ratio']:5.2f} "
            f"entropy={r['entropy_rank']:5.2f} "
            f"top_eig={r['top_eigenvalue_share']:.1%}{warn}")
