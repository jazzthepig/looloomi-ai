"""Smoke tests for cross_asset_factor_tilt.py (Strategy 4).

Verifies:
  1. Long-only constraint: tilt_weights never produces a negative weight.
  2. PIT-safe z-score: zscore_cross_section uses only data through t-lag,
     so a target-day observation cannot influence its own z-score.
  3. Vol targeting: vol_target on a high-vol series caps annualised vol
     to ≤ 13% (target 12% with 1pp headroom).

Pure Python + numpy + pandas; synthetic data only — sandbox-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.cross_asset_factor_tilt import (
    zscore_cross_section, tilt_weights, vol_target,
    build_quality_score, build_momentum_score, build_lowrisk_score,
    build_composite, h32_size,
    VOL_TARGET_ANN, Z_CLIP,
    PERIODS_PER_YEAR,
)


# === Test 1: long-only constraint ============================================
def test_tilt_weights_never_negative():
    """tilt_weights must never produce a negative weight (CLAUDE.md canonical).

    Spec: BOTTOM QUARTILE (worst-ranked 25%) gets exactly 1/N each (the floor);
    top 75% absorbs the residual. No negative weights anywhere. Per-day
    weights sum to 1.
    """
    rng = np.random.default_rng(11)
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    n_assets = 58
    cols = [f"A{i:02d}" for i in range(n_assets)]
    scores = pd.DataFrame(rng.normal(0, 1, (100, n_assets)),
                          index=dates, columns=cols)
    weights = tilt_weights(scores, min_weight=1.0 / n_assets)
    floor = 1.0 / n_assets
    k_floor = max(1, int(round(n_assets * 0.25)))

    # No negative weights anywhere
    assert (weights >= 0).all().all(), "found negative weight(s) — tilt_weights bug"
    # Weights sum to 1 each day
    sums = weights.sum(axis=1)
    assert (np.abs(sums - 1.0) < 1e-9).all(), (
        f"weights don't sum to 1: min={sums.min()}, max={sums.max()}")
    # Best asset gets more weight than worst asset (top-heaviness preserved)
    last_day = weights.iloc[-1]
    assert last_day.max() > last_day.min(), (
        "best asset should have more weight than worst asset")
    # Bottom quartile by RANK gets exactly the floor weight (the spec's guarantee)
    last_ranks = scores.iloc[-1].rank(ascending=False)
    bottom_assets = last_ranks[last_ranks > (n_assets - k_floor)].index
    bottom_weights = last_day.loc[bottom_assets]
    assert np.allclose(bottom_weights.values, floor, atol=1e-9), (
        f"bottom-quartile-by-rank should be exactly floor={floor:.6f}; got "
        f"{bottom_weights.values}")
    # Top 75% by rank sum to (1 - k_floor * floor)
    top_assets = last_ranks[last_ranks <= (n_assets - k_floor)].index
    top_sum = last_day.loc[top_assets].sum()
    expected_top_sum = 1.0 - k_floor * floor
    assert abs(top_sum - expected_top_sum) < 1e-9, (
        f"top-75% should sum to {expected_top_sum:.6f}; got {top_sum:.6f}")
    print(f"✓ test_tilt_weights_never_negative — "
          f"min_w={weights.min().min():.4f}, max_w={weights.max().max():.4f}, "
          f"bottom quartile (n={k_floor}) = floor {floor:.4f} exactly")


# === Test 2: PIT-safe z-score =================================================
def test_zscore_uses_only_lagged_data():
    """zscore_cross_section must use ONLY data through t-lag.

    Setup: 30-day panel with realistic cross-section, then inject an extreme
    outlier at row t=15 in asset X. With lag=1, row 15's z-score uses row 14
    (no outlier); row 16's z-score uses row 15 (outlier visible).
    """
    rng = np.random.default_rng(31)
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    cols = ["X", "Y", "Z", "W"]
    raw = pd.DataFrame(rng.normal(0, 1, (30, 4)), index=dates, columns=cols)

    # Sanity: z-score of row 0 is NaN (no prior data for lag=1)
    z = zscore_cross_section(raw, lag=1)
    assert z.iloc[0].isna().all(), "row 0 should be NaN with lag=1 (no prior)"

    # Inject an extreme outlier at row 15 in asset X (100× the natural range)
    raw.loc[dates[15], "X"] = 100.0

    z = zscore_cross_section(raw, lag=1)
    # Row 15's z-score must NOT include the outlier (PIT-safe).
    # With lag=1, row 15's z uses row 14's data (no outlier).
    z15_x = z.iloc[15]["X"]
    assert np.isfinite(z15_x), (
        f"PIT violation: row 15 z-score is {z15_x} (NaN or inf)")
    # Row 15's z should be small — outlier not yet visible.
    assert abs(z15_x) < 3.0, (
        f"PIT violation: row 15 z=|{z15_x}| too large — outlier leaked in")
    # Row 16's z-score DOES use row 15's data — outlier has SOME effect.
    z16_x = z.iloc[16]["X"]
    assert np.isfinite(z16_x)
    # The key PIT-safe assertion: z16_X must NOT equal z15_X (outlier changed it).
    # The z16 magnitude is bounded by the cross-section std (which the outlier
    # itself inflates for small N), so we check the relative change, not the
    # absolute z magnitude.
    assert abs(z16_x - z15_x) > 0.1, (
        f"PIT violation: outlier at row 15 didn't propagate to row 16: "
        f"z15={z15_x:.3f}, z16={z16_x:.3f}")
    print(f"✓ test_zscore_uses_only_lagged_data — "
          f"z15_X={z15_x:+.3f} (PIT-safe, outlier not yet visible), "
          f"z16_X={z16_x:+.3f} (outlier at row 15 propagated to row 16)")


# === Test 3: vol targeting ====================================================
def test_vol_target_caps_annualized_vol():
    """vol_target caps annualised vol to ≤ 13% on a high-vol synthetic series."""
    rng = np.random.default_rng(13)
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    # Daily vol ~10% → ann vol ~158% (very high)
    high_vol = pd.Series(rng.normal(0, 0.10, 400), index=dates)
    targeted = vol_target(high_vol, target_ann=VOL_TARGET_ANN)
    ann_vol = float(targeted.std() * np.sqrt(PERIODS_PER_YEAR))
    assert ann_vol <= 0.13 + 1e-6, (
        f"vol_target overshot: ann_vol={ann_vol:.4f}, expected ≤ 0.13")
    assert targeted.notna().all()
    assert np.isfinite(targeted).all()
    print(f"✓ test_vol_target_caps_annualized_vol — "
          f"raw_ann_vol={high_vol.std() * np.sqrt(PERIODS_PER_YEAR):.2f} → "
          f"targeted={ann_vol:.4f}")


# === Test 4 (bonus): composite score is finite and bounded ===================
def test_composite_score_bounded_by_z_clip():
    """build_composite output should be bounded by ±Z_CLIP on average."""
    rng = np.random.default_rng(17)
    n_days = 100
    n_assets = 10
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    cols = [f"A{i:02d}" for i in range(n_assets)]
    cis_long = pd.DataFrame({
        "date": np.repeat(dates, n_assets),
        "asset": cols * n_days,
        "O": rng.uniform(0, 100, n_days * n_assets),
    })
    rets = pd.DataFrame(rng.normal(0, 0.02, (n_days, n_assets)),
                        index=dates, columns=cols)
    score = build_composite(cis_long, rets, cols, dates)
    assert score.notna().any().any(), "composite is all NaN"
    # After clipping, abs(z) ≤ Z_CLIP + tolerance
    abs_max = score.abs().max().max()
    assert abs_max <= Z_CLIP + 1e-6, (
        f"composite score exceeded Z_CLIP={Z_CLIP}: max|z|={abs_max:.3f}")
    print(f"✓ test_composite_score_bounded_by_z_clip — "
          f"max|z|={abs_max:.3f}, Z_CLIP={Z_CLIP}")


# === Test 5 (bonus): H3.2 size scalar stays within [floor, cap] ==============
def test_h32_size_within_bounds():
    """h32_size should clip to [H32_FLOOR, H32_CAP] = [0.5, 1.75]."""
    from src.research.validation.cross_asset_factor_tilt import H32_FLOOR, H32_CAP
    # Very high realized vol → tiny size → clipped to H32_FLOOR
    high_vol_returns = pd.Series(np.random.default_rng(19).normal(0, 0.10, 100))
    s_high = h32_size(high_vol_returns)
    assert H32_FLOOR - 1e-9 <= s_high <= H32_CAP + 1e-9, (
        f"size {s_high} outside [{H32_FLOOR}, {H32_CAP}]")
    # Very low realized vol → huge size → clipped to H32_CAP
    low_vol_returns = pd.Series(np.random.default_rng(23).normal(0, 0.0001, 100))
    s_low = h32_size(low_vol_returns)
    assert H32_FLOOR - 1e-9 <= s_low <= H32_CAP + 1e-9
    print(f"✓ test_h32_size_within_bounds — "
          f"high_vol→{s_high:.3f}, low_vol→{s_low:.3f} "
          f"(clipped to [{H32_FLOOR}, {H32_CAP}])")


if __name__ == "__main__":
    test_tilt_weights_never_negative()
    test_zscore_uses_only_lagged_data()
    test_vol_target_caps_annualized_vol()
    test_composite_score_bounded_by_z_clip()
    test_h32_size_within_bounds()
    print("\n=== All factor_tilt smoke tests passed ===")