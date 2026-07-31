"""
Smoke tests for R83 vol risk-premia L/S (sandbox-safe, synthetic data only).

Tests:
  1. Imports
  2. realized_vol_wide — 30d rolling std × sqrt(365), no NaN after warmup
  3. score_low_vol_long — sign inverted correctly
  4. vol_ls — both signs produce valid time-series
  5. End-to-end synthetic: low-vol assets predict positive return, high-vol
     negative → matched-cell diff favors low_vol_long
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    from src.research.validation.r83_vol_risk_premia_ls import (
        realized_vol_wide, score_low_vol_long, vol_ls, run_gauntlet,
        R83_CADENCE, R83_COST_BPS, R83_K_TERCILES,
        SIGN_LOW_VOL_LONG, SIGN_HIGH_VOL_LONG,
    )
    print("  ✓ module imports OK")


def t_realized_vol_wide():
    from src.research.validation.r83_vol_risk_premia_ls import realized_vol_wide
    rng = np.random.default_rng(1)
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    rets = pd.DataFrame(rng.normal(0, 0.02, (100, 5)), index=dates, columns=list("ABCDE"))
    vol = realized_vol_wide(rets, window=30)
    # First 29 rows: NaN
    assert vol.iloc[:29].isna().all().all()
    # Row 29+: finite
    assert vol.iloc[29:].notna().all().all()
    # Annualized: vol.iloc[50] uses rets.iloc[21:51] (30-day window).
    # Compare to that window's std × sqrt(365).
    sample = vol.iloc[50, 0]
    window_std = rets.iloc[21:51, 0].std()  # 30-day window
    ratio = sample / window_std
    expected = np.sqrt(365)
    assert abs(ratio - expected) / expected < 0.05, \
        f"Expected ratio ≈ √365={expected:.2f}, got {ratio:.2f}"
    print(f"  ✓ realized_vol_wide: 30d rolling σ × √365, ratio={ratio:.2f}")


def t_score_low_vol_long():
    from src.research.validation.r83_vol_risk_premia_ls import score_low_vol_long
    vol = pd.DataFrame({"A": [0.1, 0.5, 0.9], "B": [0.5, 0.1, 0.5]})
    score = score_low_vol_long(vol)
    # Score = -1 × vol, so higher score = lower vol
    assert score["A"].iloc[0] == -0.1
    assert score["A"].iloc[2] == -0.9
    # B has low vol at idx=1; should have highest score there
    assert score["B"].iloc[1] == -0.1
    print("  ✓ score_low_vol_long: -1×vol, higher score = lower vol")


def t_vol_ls_both_signs():
    from src.research.validation.r83_vol_risk_premia_ls import vol_ls
    rng = np.random.default_rng(2)
    dates = pd.date_range("2024-01-01", periods=60, freq="D")
    rets = pd.DataFrame(rng.normal(0, 0.02, (60, 8)), index=dates, columns=list("ABCDEFGH"))
    vol = pd.DataFrame(rng.uniform(0.01, 0.10, (60, 8)), index=dates, columns=list("ABCDEFGH"))
    fac_low = vol_ls(vol, rets, cost_bps=0.0, rebal_days=5, sign="low_vol_long")
    fac_high = vol_ls(vol, rets, cost_bps=0.0, rebal_days=5, sign="high_vol_long")
    assert len(fac_low) == 60
    assert len(fac_high) == 60
    # The two signs should be opposite (low-vol long = -(high-vol long))
    np.testing.assert_array_almost_equal(fac_low.values, -fac_high.values, decimal=8)
    print("  ✓ vol_ls: both signs produce valid time-series; opposite signs")


def t_e2e_synthetic_positive_risk_premia():
    """Synthetic: low-vol assets predict positive return, high-vol negative.
    Matched-cell diff should favor low_vol_long."""
    from src.research.validation.r83_vol_risk_premia_ls import (
        realized_vol_wide, score_low_vol_long, run_gauntlet,
    )
    from src.research.validation.factor_absorption import absorption_test
    np.random.seed(11)
    dates = pd.date_range("2024-01-01", periods=180, freq="D")
    n_assets = 12
    # Construct returns: low-vol assets have positive drift, high-vol have negative
    drift = np.linspace(0.002, -0.002, n_assets)  # +0.2% to -0.2%
    vol_levels = np.linspace(0.01, 0.05, n_assets)  # 1% to 5% daily vol
    rets = pd.DataFrame(0.0, index=dates, columns=[f"A{i}" for i in range(n_assets)])
    for a in range(n_assets):
        rets.iloc[:, a] = np.random.normal(drift[a], vol_levels[a], 180)
    vol_wide = realized_vol_wide(rets, window=30)
    # Build known (random — uncorrelated to rets)
    f_market = np.random.default_rng(99).normal(0, 0.01, 180)
    f_momentum = np.random.default_rng(100).normal(0, 0.01, 180)
    known = {"market": f_market, "momentum": f_momentum}
    g = run_gauntlet(vol_wide, rets, known)
    print(f"  ✓ e2e: low_vol_long gross_t={g['low_vol_long']['gross_t']:+.2f}  "
          f"5bps_t={g['low_vol_long']['5bps_t']:+.2f}  OOS_t={g['low_vol_long']['oos_t']:+.2f}")
    print(f"  ✓ e2e: high_vol_long gross_t={g['high_vol_long']['gross_t']:+.2f}  "
          f"5bps_t={g['high_vol_long']['5bps_t']:+.2f}  OOS_t={g['high_vol_long']['oos_t']:+.2f}")
    print(f"  ✓ e2e: matched_diff={g['matched_diff']:+.2f}  sign={g['sign_verdict']}")
    # The synthetic risk-premia is engineered to favor low_vol_long
    assert g["sign_verdict"] == "low_vol_long", f"Expected low_vol_long, got {g['sign_verdict']}"
    # The gross_t of low_vol_long should be POSITIVE
    assert g["low_vol_long"]["gross_t"] > 0, f"Expected positive gross_t, got {g['low_vol_long']['gross_t']}"


# ── Test runner ─────────────────────────────────────────────────────────────
TESTS = [
    t_imports,
    t_realized_vol_wide,
    t_score_low_vol_long,
    t_vol_ls_both_signs,
    t_e2e_synthetic_positive_risk_premia,
]


def main() -> int:
    print(f"Running {len(TESTS)} R83 smoke tests …\n")
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ {t.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__} ERROR: {type(e).__name__}: {e}")
            failed += 1
    total = len(TESTS)
    passed = total - failed
    print(f"\n{passed}/{total} test(s) passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
