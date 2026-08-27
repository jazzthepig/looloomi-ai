"""Smoke tests for simulate_paper_trade.py (60d SIM harness).

Verifies:
  1. `score_r76_funding_residual` is mean-zero per time (cross-sectional demean invariant).
  2. `_cadence_ls_sim` with rebal_days=1 produces a factor Series aligned to rets.index.
  3. Frozen cell constants match R76 best cell (5d/0bps/k=3/high_fund_long).
  4. Frozen R77 weights match the R77 module (w_R46=0.25, w_R62=0.75, w_R76=0.30).

Pure Python + numpy + pandas; synthetic data only — sandbox-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.simulate_paper_trade import (
    score_r76_funding_residual, _cadence_ls_sim,
    score_r46_pillar_o_synthetic, score_r62_funding_z,
    R76_CAD, R76_BPS, R76_K, R76_SIGN,
    W_R46, W_R62, W_R76, R46_CAD, R46_BPS, R62_CAD, R62_BPS,
    UNIVERSE, SIM_DIR,
)


# === Synthetic data factories ==============================================
def _synth_panel(n_days: int = 100, n_assets: int = 28, seed: int = 0):
    """Build a synthetic funding + returns panel with realistic shape."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-05-01", periods=n_days, freq="D", tz=None)
    cols = [f"A{i:02d}" for i in range(n_assets)]
    funding = pd.DataFrame(
        rng.normal(loc=1e-4, scale=2e-4, size=(n_days, n_assets)),
        index=dates, columns=cols,
    )
    rets = pd.DataFrame(
        rng.normal(loc=0.0, scale=0.02, size=(n_days, n_assets)),
        index=dates, columns=cols,
    )
    return funding, rets


# === Tests ==================================================================
def test_score_r76_is_mean_zero_per_time():
    """Funding residual = panel − per-time cross-sectional mean. Mean per time must be ~0."""
    funding, _ = _synth_panel()
    score = score_r76_funding_residual(funding)
    per_time_mean = score.mean(axis=1)
    assert np.all(np.abs(per_time_mean) < 1e-12), (
        f"score_r76 cross-sectional mean not zero: max |mean| = "
        f"{per_time_mean.abs().max():.2e}"
    )
    # Mathematical invariant
    expected = funding.subtract(funding.mean(axis=1), axis=0)
    np.testing.assert_allclose(score.values, expected.values, rtol=0, atol=1e-15)
    print(f"  ✓ score_r76 mean-zero per time (max |mean| = "
          f"{per_time_mean.abs().max():.2e})")


def test_cadence_ls_sim_aligns_to_rets_index():
    """_cadence_ls_sim returns a Series aligned to rets.index, daily rebal case."""
    _, rets = _synth_panel()
    score, _ = _synth_panel()  # use funding-shape matrix as score
    fac = _cadence_ls_sim(score, rets, rebal_days=1, cost_bps=0.0, k_terciles=3)
    assert isinstance(fac, pd.Series), f"Expected pd.Series, got {type(fac)}"
    assert len(fac) == len(rets), f"fac length {len(fac)} != rets length {len(rets)}"
    assert (fac.index == rets.index).all(), "fac.index not aligned to rets.index"
    # Sanity: fac should have non-zero values when rets are non-zero
    assert fac.std() > 0, f"fac has zero std (no L/S activity): mean={fac.mean()}"
    print(f"  ✓ _cadence_ls_sim produces {len(fac)}-day aligned Series "
          f"(mean={fac.mean():.4f}, std={fac.std():.4f})")


def test_frozen_cell_constants_match_r76_best_cell():
    """R76 frozen cell must match r76_funding_residual_ls.py best cell."""
    assert R76_CAD == 5, f"R76_CAD should be 5, got {R76_CAD}"
    assert R76_BPS == 0.0, f"R76_BPS should be 0.0, got {R76_BPS}"
    assert R76_K == 3, f"R76_K should be 3, got {R76_K}"
    assert R76_SIGN == "high_fund_long", f"R76_SIGN should be 'high_fund_long', got {R76_SIGN!r}"
    # Universe must be 28-asset strict
    assert len(UNIVERSE) == 28, f"Universe should be 28 assets, got {len(UNIVERSE)}"
    print(f"  ✓ R76 cell = 5d/0bps/k=3/high_fund_long on 28 assets (matches backtest)")


def test_frozen_r77_weights_match_r77_module():
    """R77 frozen weights must match r77_r76_as_fusion_contribution.py frozen cell."""
    assert W_R46 == 0.25, f"W_R46 should be 0.25 (frozen R77 cell), got {W_R46}"
    assert W_R62 == 0.75, f"W_R62 should be 0.75 (frozen R77 cell), got {W_R62}"
    assert W_R76 == 0.30, f"W_R76 should be 0.30 (frozen R77 cell), got {W_R76}"
    # R46 leg: pillar_O 5d/5bps
    assert R46_CAD == 5, f"R46_CAD should be 5, got {R46_CAD}"
    assert R46_BPS == 5.0, f"R46_BPS should be 5.0, got {R46_BPS}"
    # R62 leg: 21d/0bps (ungated in sim)
    assert R62_CAD == 21, f"R62_CAD should be 21, got {R62_CAD}"
    assert R62_BPS == 0.0, f"R62_BPS should be 0.0, got {R62_BPS}"
    print(f"  ✓ R77 weights = R46=0.25/R62=0.75/R76=0.30; cadences = 5/21/5; "
          f"costs = 5/0/0bps (matches frozen cell)")


def test_sim_dir_exists():
    """Output directory /tmp/cometcloud_data/sim_paper must exist."""
    assert SIM_DIR.exists(), f"SIM_DIR does not exist: {SIM_DIR}"
    assert SIM_DIR.is_dir(), f"SIM_DIR is not a directory: {SIM_DIR}"
    print(f"  ✓ SIM_DIR exists at {SIM_DIR}")


# === CLI ====================================================================
if __name__ == "__main__":
    print("Running simulate_paper_trade smoke tests …")
    test_score_r76_is_mean_zero_per_time()
    test_cadence_ls_sim_aligns_to_rets_index()
    test_frozen_cell_constants_match_r76_best_cell()
    test_frozen_r77_weights_match_r77_module()
    test_sim_dir_exists()
    print("All 5 tests passed.")
