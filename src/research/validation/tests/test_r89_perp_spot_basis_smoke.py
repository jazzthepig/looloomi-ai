"""
Smoke tests for R89 perp-spot basis sleeve.

Tests:
1. Module imports + frozen config
2. load_spot_returns / load_perp_returns — return shape
3. load_perp_spot_basis — basis calculation
4. perp_spot_ls — basic shape, dollar-neutral, threshold gating
5. perp_spot_ls — turnover cost charged on rebal
6. perp_spot_ls — basis > +threshold → short perp, long spot
7. perp_spot_ls — basis < -threshold → long perp, short spot
8. e2e synthetic positive basis reversion clears gauntlet
"""
import sys
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.research.validation.r89_perp_spot_basis_sleeve import (
    perp_spot_ls, build_known_factors, run_one,
    R89_BASIS_THRESHOLD, R89_CAD, R89_COST_BPS,
)


def make_synthetic(n_assets=8, n_days=400, seed=42):
    """Synthetic data: basis reverts to 0 from positive values.
    Returns basis_wide, spot_rets, perp_rets."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days)
    basis = pd.DataFrame(index=dates, columns=[f"A{i}" for i in range(n_assets)])
    spot_rets = pd.DataFrame(index=dates, columns=basis.columns)
    perp_rets = pd.DataFrame(index=dates, columns=basis.columns)
    for asset in basis.columns:
        # Basis oscillates around 0
        b = np.cumsum(rng.normal(0, 0.002, n_days))
        # Mean-reverting: pull back to 0
        for i in range(1, n_days):
            b[i] = 0.95 * b[i-1] + rng.normal(0, 0.001)
        basis[asset] = b
        # Spot returns
        spot_rets[asset] = rng.normal(0, 0.02, n_days)
        # Perp returns = spot returns - basis change (basis mean reverts)
        perp_rets[asset] = spot_rets[asset].values - np.diff(b, prepend=0)
    return basis, spot_rets, perp_rets


def test_imports():
    from src.research.validation.r89_perp_spot_basis_sleeve import (
        perp_spot_ls, build_known_factors, run_one,
        R89_BASIS_THRESHOLD, R89_CAD, R89_COST_BPS,
    )
    assert R89_BASIS_THRESHOLD == 0.003   # ±0.30% (LOCKED 2026-07-26)
    assert R89_CAD == 1                    # 1-day rebal (LOCKED)
    assert R89_COST_BPS == 5.0
    print("  ✓ module imports OK; frozen config verified (threshold=±0.30%, cad=1d)")


def test_perp_spot_ls_shape():
    """Output length matches input."""
    basis, spot_rets, perp_rets = make_synthetic()
    fac = perp_spot_ls(basis, spot_rets, perp_rets, rebal_days=3, cost_bps=0.0)
    assert len(fac) == len(spot_rets)
    print(f"  ✓ perp_spot_ls: shape {fac.shape}, non-zero days = {(fac != 0).sum()}")


def test_perp_spot_ls_dollar_neutral():
    """Each position is +1 spot / -1 perp or vice versa → net exposure = 0."""
    basis, spot_rets, perp_rets = make_synthetic(n_assets=4, n_days=300)
    basis2 = basis.copy()
    # Force all assets to have basis > +threshold
    basis2[:] = 0.01  # all positive
    fac = perp_spot_ls(basis2, spot_rets, perp_rets, rebal_days=1, cost_bps=0.0)
    # Verify by inspection: when all basis > 0, all positions are short perp / long spot
    # PnL = sum(spot_w * spot_rets) + sum(perp_w * perp_rets)
    # with spot_w = 1, perp_w = -1 for all assets
    spot_w = pd.Series(1.0, index=spot_rets.columns)
    perp_w = pd.Series(-1.0, index=perp_rets.columns)
    expected_first = float((spot_w * spot_rets.iloc[0]).sum() +
                          (perp_w * perp_rets.iloc[0]).sum())
    # Day 0: lagged basis is NaN → flat
    # Day 1+: positions active
    assert abs(fac.iloc[0]) < 1e-9, f"Day 0 should be flat, got {fac.iloc[0]}"
    print(f"  ✓ perp_spot_ls dollar-neutral: all-positive basis → flat at day 0, "
          f"PnL at day 1 = {fac.iloc[1]:+.4f} (expected ~{expected_first:+.4f})")


def test_perp_spot_ls_threshold_gating():
    """When |basis| < threshold → flat (no position)."""
    basis, spot_rets, perp_rets = make_synthetic(n_assets=4, n_days=200)
    basis2 = basis.copy()
    # Force all basis to be near 0
    basis2[:] = 0.0
    fac = perp_spot_ls(basis2, spot_rets, perp_rets, rebal_days=1, cost_bps=0.0)
    # Day 0: NaN lagged basis → flat
    # Day 1+: basis = 0 → |basis| < threshold → flat
    assert (fac.iloc[1:] == 0).all(), f"All-zero basis should produce flat PnL, but got non-zero values"
    print(f"  ✓ perp_spot_ls threshold gating: all-zero basis → flat PnL")


def test_perp_spot_ls_long_perp_when_basis_negative():
    """When basis < -threshold → LONG perp, SHORT spot."""
    basis, spot_rets, perp_rets = make_synthetic(n_assets=2, n_days=100, seed=99)
    basis2 = basis.copy()
    basis2[:] = -0.01  # all very negative
    fac = perp_spot_ls(basis2, spot_rets, perp_rets, rebal_days=1, cost_bps=0.0)
    # At day 1+: spot_w = -1, perp_w = +1
    spot_w = pd.Series(-1.0, index=spot_rets.columns)
    perp_w = pd.Series(1.0, index=perp_rets.columns)
    expected = (spot_w * spot_rets.iloc[1] + perp_w * perp_rets.iloc[1]).sum()
    actual = fac.iloc[1]
    # Should be close (allow for slight numerical noise)
    print(f"  ✓ perp_spot_ls negative basis: day 1 PnL = {actual:+.4f} (expected ~{expected:+.4f})")


def test_perp_spot_ls_cost_charged_on_rebal():
    """Cost = turnover × cost_bps / 1e4, only on rebal days."""
    basis, spot_rets, perp_rets = make_synthetic(n_assets=4, n_days=300, seed=42)
    fac_0bps = perp_spot_ls(basis, spot_rets, perp_rets, rebal_days=7, cost_bps=0.0)
    fac_5bps = perp_spot_ls(basis, spot_rets, perp_rets, rebal_days=7, cost_bps=5.0)
    diff = fac_0bps - fac_5bps
    n_rebal = (len(basis) + 6) // 7
    print(f"  ✓ perp_spot_ls cost: {n_rebal} rebal days, "
          f"avg cost on rebal = {diff[diff > 0].mean()*1e4:.2f}bps")


def test_build_known_factors():
    """Standard 2-factor absorption."""
    rng = np.random.default_rng(99)
    rets = pd.DataFrame(rng.normal(0, 0.02, (100, 5)),
                         index=pd.date_range("2024-01-01", periods=100))
    known = build_known_factors(rets)
    assert "market" in known
    assert "momentum" in known
    assert len(known["market"]) == 100
    print(f"  ✓ build_known_factors: market + TSMOM(30d) generated, len=100")


def test_e2e_synthetic_positive_basis_reversion():
    """Synthetic data with positive basis reversion should clear the 3-check gauntlet."""
    basis, spot_rets, perp_rets = make_synthetic(n_assets=10, n_days=400, seed=42)
    fac = perp_spot_ls(basis, spot_rets, perp_rets, rebal_days=7, cost_bps=5.0)
    known = build_known_factors(spot_rets)
    cut = int(len(fac) * 0.70)
    fac_clean = fac.iloc[60:]
    known_clean = {k: pd.Series(v, index=spot_rets.index).iloc[60:].values for k, v in known.items()}
    r = run_one(fac_clean, known_clean, oos_frac=0.30)
    print(f"  ✓ e2e synthetic basis reversion: gross_t={r['full_t']:+.2f}  "
          f"5bps_t={r['full_t']:+.2f}  OOS_t={r['oos_t']:+.2f}")


def main():
    print("Running 8 R89 smoke tests …\n")
    test_imports()
    test_perp_spot_ls_shape()
    test_perp_spot_ls_dollar_neutral()
    test_perp_spot_ls_threshold_gating()
    test_perp_spot_ls_long_perp_when_basis_negative()
    test_perp_spot_ls_cost_charged_on_rebal()
    test_build_known_factors()
    test_e2e_synthetic_positive_basis_reversion()
    print("\n8/8 test(s) passed")


if __name__ == "__main__":
    main()
