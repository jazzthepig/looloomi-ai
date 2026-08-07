"""
Neutralisation guard — the R62 lesson made executable.

R62 found that raw `a_ret − b_ret` was not alpha but LEVERAGED BETA (betas
1.4–2.4). An exposure and an edge look identical on a P&L chart and behave
completely differently in a drawdown, so the only defence is to strip the known
exposures and see what is left.

These tests assert the properties that make the answer trustworthy rather than
merely available:
  · a pure-beta series must neutralise to ~zero      (the R62 case)
  · genuine residual alpha must SURVIVE               (no over-stripping)
  · unmeasured rows come back NaN, never imputed      (I1)
  · too few observations ⇒ refuse, do not interpolate

Run: python3 -m tests.test_neutralize
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np  # noqa: E402

from src.research.validation.neutralize import (  # noqa: E402
    exposure_share, neutralize, neutralize_panel,
)


def test_pure_beta_neutralises_to_zero():
    """THE R62 case: returns that are only market exposure must leave no residual.
    If this fails, every 'edge' we measure could be leverage in disguise."""
    rng = np.random.default_rng(0)
    mkt = rng.normal(0, 0.03, 60)
    beta = rng.uniform(0.5, 2.4, 60)
    y = beta * 0.02                       # returns are exactly beta x a market move
    r = neutralize(y, {"beta": beta})
    assert abs(r.betas["beta"] - 0.02) < 1e-9, r.betas
    assert np.nanmax(np.abs(r.residual)) < 1e-9, "pure exposure left a residual"
    assert exposure_share(r) > 0.999, "R2 should be ~1 when y IS the exposure"


def test_real_alpha_survives_neutralisation():
    """The converse guard. A neutraliser that strips everything is useless — it
    would refute every strategy including a real one."""
    rng = np.random.default_rng(1)
    beta = rng.uniform(0.5, 2.0, 80)
    alpha = rng.normal(0, 0.01, 80)
    y = beta * 0.02 + alpha
    r = neutralize(y, {"beta": beta})
    keep = np.corrcoef(r.residual, alpha)[0, 1]
    assert keep > 0.95, f"real alpha destroyed by neutralisation (corr {keep:.3f})"


def test_unmeasured_rows_return_nan_not_imputed():
    """I1. Imputing a missing exposure to the mean invents a zero-exposure asset
    that does not exist, and the invention is invisible downstream."""
    y = np.array([0.01, 0.02, np.nan, 0.04] + [0.01] * 8)
    b = np.array([1.0, 1.5, 2.0, np.nan] + [1.2] * 8)
    r = neutralize(y, {"beta": b})
    assert np.isnan(r.residual[2]) and np.isnan(r.residual[3])
    assert r.n_used == 10 and r.dropped == 2
    assert np.isfinite(r.residual[0])


def test_too_few_observations_refuses():
    """A neutralisation fitted on a handful of names is an interpolation through
    noise. Refusing is the honest output; returning confident residuals is not."""
    r = neutralize(np.array([0.01, 0.02, 0.03]), {"beta": np.array([1.0, 1.2, 0.9])})
    assert r.n_used == 3 and np.isnan(r.residual).all()
    assert r.betas == {} and r.r2 == 0.0


def test_multi_exposure_and_panel_shape():
    """Several exposures at once, and per-day independence (I2): each day is its
    own regression so nothing crosses a period boundary."""
    rng = np.random.default_rng(2)
    n = 40
    b, sz = rng.uniform(0.5, 2.0, n), rng.normal(0, 1, n)
    y = 0.02 * b + 0.005 * sz + rng.normal(0, 0.001, n)
    r = neutralize(y, {"beta": b, "size": sz})
    assert abs(r.betas["beta"] - 0.02) < 5e-3 and abs(r.betas["size"] - 0.005) < 5e-3

    panel = neutralize_panel({"d1": y, "d2": y[:5]}, {"d1": {"beta": b}, "d2": {"beta": b[:5]}})
    assert set(panel) == {"d1", "d2"}
    assert panel["d1"].n_used == n
    # d2 is UNDER min_obs and must still be present, all-NaN: a day that could not
    # be fitted and a day that is absent are different facts.
    assert np.isnan(panel["d2"].residual).all()


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} neutralisation checks passed")
    sys.exit(1 if f else 0)
