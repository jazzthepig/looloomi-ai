"""
Effective-breadth guard — pins the distinction that three ledger entries missed.

S-96, S-113 and S-114 all quoted `N_eff = N/(1+(N-1)·rho_bar)` as "the number of
independent bets". S-114 then flagged it as "assumes equicorrelation", which was
itself half wrong. The truth found by testing against a matrix where
equicorrelation genuinely holds: the two measures disagree even THERE, because
they answer different questions —

  · naive = equal-weight portfolio VARIANCE REDUCTION. Exact for any correlation
    structure; needs equal VOLATILITIES, which crypto-vs-TradFi violates 2.4x.
    Correct constraint for a LONG-ONLY book (layer ①).
  · participation ratio = number of independent DIRECTIONS in the spectrum.
    Correct constraint for a MARKET-NEUTRAL book (layer ④).

The error was never arithmetic. It was quoting a breadth number without saying
which book it constrains.

Run: python3 -m tests.test_effective_breadth
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np  # noqa: E402

from src.research.validation.effective_breadth import (  # noqa: E402
    breadth_report, effective_breadth,
)


def _equicorr(n: int, rho: float) -> np.ndarray:
    c = np.full((n, n), rho)
    np.fill_diagonal(c, 1.0)
    return c


def test_independent_assets_give_full_breadth_on_both_measures():
    """The only case where the two measures must agree: with zero correlation every
    asset is its own direction AND equal-weighting reduces variance by the full N."""
    r = effective_breadth(_equicorr(20, 0.0))
    assert abs(r["naive_variance_neff"] - 20) < 1e-6
    assert abs(r["participation_ratio"] - 20) < 1e-6


def test_the_two_measures_diverge_even_under_true_equicorrelation():
    """THE test. If these agreed under equicorrelation, 'the formula assumes
    equicorrelation' would be the right diagnosis. They do not: at rho=0.3, N=20
    the spectrum is one eigenvalue at 6.7 and nineteen at 0.7, giving naive
    20/6.7 = 2.99 and participation 400/54.2 = 7.38. Both exact, both correct,
    answering different questions."""
    r = effective_breadth(_equicorr(20, 0.3))
    assert abs(r["naive_variance_neff"] - 2.99) < 0.02
    assert abs(r["participation_ratio"] - 7.38) < 0.05
    assert r["participation_ratio"] > 2 * r["naive_variance_neff"], (
        "they must diverge by a wide margin even when equicorrelation HOLDS — "
        "that divergence is the whole point")


def test_naive_measure_tracks_long_only_variance_reduction_exactly():
    """The long-only book's real constraint. Var(equal weight) = [1+(N-1)rho]/N,
    so the naive figure is not an approximation for that question — it is the
    answer. Verified against a direct portfolio-variance computation."""
    n, rho = 12, 0.45
    c = _equicorr(n, rho)
    w = np.full(n, 1.0 / n)
    var_port = float(w @ c @ w)            # unit vols by construction
    assert abs(1.0 / var_port - effective_breadth(c)["naive_variance_neff"]) < 1e-9


def test_a_dominant_factor_collapses_breadth_and_is_reported():
    """Crypto's shape: one factor carrying half the variance. `top_eigenvalue_share`
    exists because it is the number that says 'this panel is basically one bet',
    which an average correlation states only obliquely."""
    r_hi = effective_breadth(_equicorr(20, 0.6))
    r_lo = effective_breadth(_equicorr(20, 0.1))
    assert r_hi["top_eigenvalue_share"] > 0.55 > r_lo["top_eigenvalue_share"]
    assert r_hi["participation_ratio"] < r_lo["participation_ratio"]


def test_rank_deficiency_is_surfaced_not_swallowed():
    """A correlation matrix estimated on fewer observations than assets is singular,
    and a breadth number computed from it is meaningless. Clipping negative
    eigenvalues silently would return a confident figure from a degenerate matrix —
    the same class as imputing NaN to zero (I1)."""
    rng = np.random.default_rng(0)
    x = rng.normal(size=(5, 30))           # 30 assets, only 5 observations
    c = np.corrcoef(x.T)
    r = effective_breadth(c)
    assert r["rank_deficient"] is True, "singular matrix must be flagged"
    # The first version of this assertion demanded n_negative_eigenvalues > 0 and
    # FAILED — correctly. Deficiency shows up as eigenvalues at NUMERICAL ZERO,
    # which LAPACK may return as +1e-17 rather than negative, so the negative count
    # can legitimately be 0 on a rank-4 matrix. The evidence is the RANK.
    assert r["numerical_rank"] == 4, (
        f"5 demeaned observations span rank 4, got {r['numerical_rank']}")
    assert r["numerical_rank"] < r["n_assets"]
    # and a healthy matrix must NOT be flagged, or the flag is noise
    assert effective_breadth(_equicorr(20, 0.3))["rank_deficient"] is False


def test_report_shows_both_measures_side_by_side():
    """Three ledger entries quote the naive number. Printing it beside the spectral
    one is what makes the correction legible to whoever reads them next; dropping
    it would leave those entries silently orphaned."""
    line = breadth_report(_equicorr(20, 0.3), "sanity")
    for token in ("naive=", "participation=", "entropy=", "top_eig="):
        assert token in line, f"report must show {token}"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} effective-breadth checks passed")
    sys.exit(1 if f else 0)
