"""Smoke tests for r76_strategy2_paper.py (Strategy 2).

Verifies:
  1. _score_r76 cross-sectional demean is mean-zero per time (per construction).
  2. _target_weights_r76 produces a long/short tercile split with gross = 2/3.
  3. Cell config matches the R76 frozen best cell from r76_funding_residual_ls.py
     (5d/0bps, k=3, sign=high_fund_long, 28-asset strict universe).

Pure Python + numpy + pandas; synthetic data only — sandbox-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.data.signals.r76_strategy2_paper import (
    _score_r76,
    _target_weights_r76,
    R76_CAD, R76_BPS, R76_K, R76_SIGN,
    UNIVERSE, DEFAULT_DECLARED_CAPACITY_USD, VALIDATION_MIN_DAYS,
)


# === Synthetic data factory ==================================================
def _synth_funding_panel(n_days: int = 60, n_assets: int = 28,
                          seed: int = 0) -> pd.DataFrame:
    """Build a synthetic funding panel (n_days × n_assets) with realistic shape."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-06-01", periods=n_days, freq="D")
    cols = [f"A{i:02d}" for i in range(n_assets)]
    # Each asset has its own mean + noise; cross-sectional demean produces a
    # different mix each day (which is what we want for the L/S).
    arr = rng.normal(loc=0.0, scale=1e-4, size=(n_days, n_assets))
    arr += np.linspace(-2e-4, 2e-4, n_assets)  # per-asset level tilt
    return pd.DataFrame(arr, index=dates, columns=cols)


# === Tests ====================================================================
def test_score_r76_is_mean_zero_per_time():
    """Cross-sectional demean of funding must produce mean-zero per time by construction."""
    panel = _synth_funding_panel(n_days=30, n_assets=28)
    score = _score_r76(panel)
    # Per-time cross-sectional mean must be ~0 (numerical noise only)
    per_time_mean = score.mean(axis=1)
    assert np.all(np.abs(per_time_mean) < 1e-12), (
        f"score_r76 cross-sectional mean is not zero: "
        f"max |mean| = {per_time_mean.abs().max():.2e}"
    )
    # The demeaned score must equal panel - panel.mean(axis=1) (mathematical invariant)
    expected = panel.subtract(panel.mean(axis=1), axis=0)
    np.testing.assert_allclose(score.values, expected.values, rtol=0, atol=1e-15)
    print(f"  ✓ score_r76 mean-zero per time (max |mean| = "
          f"{per_time_mean.abs().max():.2e})")


def test_target_weights_r76_tercile_split():
    """_target_weights_r76 produces a long/short split with gross = 2/3 (R76 standard)."""
    panel = _synth_funding_panel(n_days=30, n_assets=28)
    score = _score_r76(panel)
    today = score.index[-1]
    w = _target_weights_r76(score, today)
    # k=3 terciles → top tercile long, bottom tercile short
    # 28 assets / 3 terciles = 9-10 per tercile (n // k = 9)
    longs = [s for s, v in w.items() if v > 0]
    shorts = [s for s, v in w.items() if v < 0]
    assert len(longs) == 28 // R76_K, (
        f"Expected {28 // R76_K} longs, got {len(longs)}"
    )
    assert len(shorts) == 28 // R76_K, (
        f"Expected {28 // R76_K} shorts, got {len(shorts)}"
    )
    # Gross = 2/3 (R76 / R77 fusion standard for k=3)
    gross = sum(abs(v) for v in w.values())
    target_gross = 2.0 / 3.0
    assert abs(gross - target_gross) < 1e-9, (
        f"Gross should be {target_gross:.4f}, got {gross:.4f}"
    )
    # Sign: high_fund_long → top tercile (highest score) is LONG
    # The "top tercile" of score = highest demeaned funding at time t
    sorted_top = score.loc[today].sort_values(ascending=False)
    expected_longs = set(sorted_top.head(28 // R76_K).index)
    expected_shorts = set(sorted_top.tail(28 // R76_K).index)
    assert set(longs) == expected_longs, (
        f"Long set mismatch.\n  got: {set(longs)}\n  expected: {expected_longs}"
    )
    assert set(shorts) == expected_shorts, (
        f"Short set mismatch.\n  got: {set(shorts)}\n  expected: {expected_shorts}"
    )
    print(f"  ✓ target_weights_r76 → {len(longs)} longs / {len(shorts)} shorts, "
          f"gross = {gross:.4f}, sign = high_fund_long verified")


def test_frozen_cell_config_matches_r76_best_cell():
    """The frozen cell constants must match R76 sweep's best cell: 5d/0bps, k=3, high_fund_long."""
    # From r76_funding_residual_ls.py best cell: 5d/0.0bps, sign=high_fund_long
    # (gross_t=+2.06, OOS_t=+2.47, passes_all=True, 5/6 windows positive)
    assert R76_CAD == 5, f"R76_CAD should be 5 (frozen best cell), got {R76_CAD}"
    assert R76_BPS == 0.0, f"R76_BPS should be 0.0 (frozen best cell), got {R76_BPS}"
    assert R76_K == 3, f"R76_K should be 3 (frozen best cell), got {R76_K}"
    assert R76_SIGN == "high_fund_long", (
        f"R76_SIGN should be 'high_fund_long' (frozen best cell), "
        f"got {R76_SIGN!r}"
    )
    # Universe must be 28-asset strict (R64/R76 panel contract)
    assert len(UNIVERSE) == 28, (
        f"Universe should be 28 assets, got {len(UNIVERSE)}: {UNIVERSE}"
    )
    # Paper-book honesty gates
    assert VALIDATION_MIN_DAYS == 60, (
        f"Validation threshold should be 60d (paper-book), got {VALIDATION_MIN_DAYS}"
    )
    assert DEFAULT_DECLARED_CAPACITY_USD == 1_000_000.0, (
        f"Capacity ceiling should be $1M (paper book), got {DEFAULT_DECLARED_CAPACITY_USD}"
    )
    print(f"  ✓ R76 cell = 5d/0bps/k=3/high_fund_long on 28 assets "
          f"(cap $1M, validates at 60d)")


# === CLI ====================================================================
if __name__ == "__main__":
    print("Running r76_strategy2_paper smoke tests …")
    test_score_r76_is_mean_zero_per_time()
    test_target_weights_r76_tercile_split()
    test_frozen_cell_config_matches_r76_best_cell()
    print("All 3 tests passed.")
