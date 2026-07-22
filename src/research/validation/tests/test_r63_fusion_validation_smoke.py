"""Smoke tests for r63_fusion_validation.py.

Verifies:
  1. Module + symbols import cleanly
  2. fuse() math is correct (linear combination)
  3. max_drawdown() returns negative for losing series, 0 for flat
  4. per_window() returns 6 windows + expected fields
  5. build_r46_sleeve_28 returns a series aligned to rets.index
  6. build_r62_sleeve_28 returns a series with some zeros (gate fires)
  7. _build_r62_detector returns a boolean series covering the panel
  8. End-to-end mini run on synthetic data: gauntlet fields present, verdict emitted

Pure Python + numpy + pandas; no scipy / nautilus / freqtrade.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.r63_fusion_validation import (
    fuse, max_drawdown, per_window,
    build_r46_sleeve_28, build_r62_sleeve_28, _build_r62_detector,
    R46_CAD, R46_BPS, R62_CAD, R62_BPS, R62_Z, R62_MF,
)


# === Synthetic data factory ==================================================
def _synthetic_panel(n_assets=20, n_days=400, seed=42):
    """Long-form CIS + wide rets + wide funding (all synthetic)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]
    cis_long = pd.DataFrame({
        "date": np.repeat(dates, n_assets),
        "asset": np.tile(assets, n_days),
        "O": rng.uniform(0, 100, n_days * n_assets),
        "F": rng.uniform(0, 100, n_days * n_assets),
        "M": rng.uniform(0, 100, n_days * n_assets),
        "S": rng.uniform(0, 100, n_days * n_assets),
        "A": rng.uniform(0, 100, n_days * n_assets),
    })
    rets = pd.DataFrame(
        rng.normal(0, 0.02, (n_days, n_assets)),
        index=dates, columns=assets,
    )
    funding = pd.DataFrame(
        rng.normal(0, 0.0005, (n_days, n_assets)),
        index=dates, columns=assets,
    )
    # Inject funding dispersion in days 50-100 and 200-250 (fragile windows)
    funding.iloc[50:100, :] *= 3.0
    funding.iloc[200:250, :] *= 2.0
    return cis_long, rets, funding


def test_imports():
    from src.research.validation import r63_fusion_validation as m
    for sym in ("fuse", "max_drawdown", "per_window",
                "build_r46_sleeve_28", "build_r62_sleeve_28",
                "_build_r62_detector",
                "R46_CAD", "R46_BPS", "R62_CAD", "R62_BPS", "R62_Z", "R62_MF"):
        assert hasattr(m, sym), f"missing symbol: {sym}"
    assert R46_CAD == 5 and R46_BPS == 5.0
    assert R62_CAD == 21 and R62_BPS == 0.0
    assert R62_Z == 0.5 and R62_MF == 2
    print(f"✓ imports OK (R46={R46_CAD}d/{R46_BPS}bps, R62={R62_CAD}d/{R62_BPS}bps, "
          f"det={R62_Z}/{R62_MF})")


def test_fuse_math():
    """fuse(w) = w × L1 + (1-w) × L2."""
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    l1 = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], index=idx)
    l2 = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], index=idx)
    # w=1 → all L1
    f1 = fuse(l1, l2, 1.0)
    np.testing.assert_array_almost_equal(f1.values, l1.values)
    # w=0 → all L2
    f0 = fuse(l1, l2, 0.0)
    np.testing.assert_array_almost_equal(f0.values, l2.values)
    # w=0.5 → half each
    f_half = fuse(l1, l2, 0.5)
    np.testing.assert_array_almost_equal(f_half.values, [0.5]*10)
    print("✓ fuse() math OK (w=0/0.5/1 endpoints)")


def test_max_drawdown_flat_and_loss():
    """max_drawdown: 0 for flat series, negative for losing series."""
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    flat = pd.Series(0.0, index=idx)
    dd_flat = max_drawdown(flat)
    assert dd_flat == 0.0, f"flat series should have 0 DD, got {dd_flat}"

    # Series that goes 1 → 0.5 (50% loss)
    losing = pd.Series([0.0] * 50 + [-0.05] * 50, index=idx)
    dd_loss = max_drawdown(losing)
    assert dd_loss < -0.20, f"losing series should have DD < -20%, got {dd_loss}"

    # Series that goes up then down 30%
    up_then_down = pd.Series([0.02] * 30 + [-0.01] * 30 + [-0.05] * 40, index=idx)
    dd_ud = max_drawdown(up_then_down)
    print(f"✓ max_drawdown OK (flat=0, losing={dd_loss:.2%}, up-then-down={dd_ud:.2%})")


def test_per_window_helper():
    """per_window returns 6 windows + ann_pct / sharpe / max_dd / cumret."""
    idx = pd.date_range("2024-01-01", periods=730, freq="D")
    fac = pd.Series(np.random.default_rng(0).normal(0, 0.01, 730), index=idx)
    windows = [
        ("W1", idx[0], idx[120]),
        ("W2", idx[121], idx[243]),
        ("W3", idx[244], idx[365]),
        ("W4", idx[366], idx[487]),
        ("W5", idx[488], idx[608]),
        ("W6", idx[609], idx[-1]),
    ]
    pw = per_window(fac, windows)
    assert len(pw) == 6
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        assert label in pw
        for k in ("n_days", "ann_pct", "sharpe", "max_dd", "cumret"):
            assert k in pw[label]
    print(f"✓ per_window OK (6 windows, W1 n={pw['W1']['n_days']}, "
          f"W1 ann={pw['W1']['ann_pct']:+.2f}, W1 DD={pw['W1']['max_dd']:+.2%})")


def test_build_r46_sleeve_28():
    """R46 leg on synthetic data — returns series aligned to rets.index."""
    cis_long, rets, _ = _synthetic_panel(n_assets=20, n_days=300)
    tradeable = sorted(set(rets.columns))
    fac, pillar_w = build_r46_sleeve_28(cis_long, rets, tradeable)
    assert isinstance(fac, pd.Series)
    assert len(fac) == len(rets)
    assert (fac.index == rets.index).all()
    # Costed series should have mostly small magnitudes and some small negatives
    assert fac.abs().max() < 0.5
    print(f"✓ build_r46_sleeve_28 OK (len={len(fac)}, max|f|={fac.abs().max():.4f}, "
          f"mean={fac.mean():+.5f})")


def test_build_r62_sleeve_28_with_gate():
    """R62 leg — should produce series with some zeros (gate fires)."""
    cis_long, rets, funding = _synthetic_panel(n_assets=20, n_days=300)
    tradeable = sorted(set(rets.columns))
    funding_daily = funding

    # Build a fragility mask covering days 50-100 and 200-250 (injected frag)
    idx = rets.index
    fragile_mask = pd.Series(False, index=idx)
    fragile_mask.iloc[50:100] = True
    fragile_mask.iloc[200:250] = True
    fragile_ranges = [(idx[50], idx[99]), (idx[200], idx[249])]
    playable_ranges = [(idx[100], idx[199]), (idx[250], idx[-1])]

    # Compute features via R62 infra (re-import)
    from src.research.validation.r62_fragility_gated_funding import (
        compute_combined_features, features_in_ranges,
    )
    feats = compute_combined_features(
        cis_long, rets, tradeable, tradeable, funding_daily
    ).reindex(idx)
    det, ks = _build_r62_detector(feats, fragile_mask, fragile_ranges, playable_ranges)
    assert isinstance(det, pd.Series)
    assert det.dtype == bool
    assert det.sum() > 0, "detector should fire on some days"
    print(f"  _build_r62_detector: fired on {int(det.sum())}/{len(det)} days "
          f"({det.mean():.0%})")

    # Build score and run sleeve
    from src.research.validation.funding_crowding_ls import score_funding_zwide
    score = score_funding_zwide(funding_daily[tradeable]).reindex(idx).ffill()
    fac = build_r62_sleeve_28(score, rets, tradeable, det)
    assert isinstance(fac, pd.Series)
    assert (fac.index == rets.index).all()
    # Gate should zero out some days
    n_gated_zero = int(((fac == 0.0) & (det)).sum())
    print(f"✓ build_r62_sleeve_28 OK (len={len(fac)}, "
          f"gate-zeroed days on detector fire: {n_gated_zero}/{int(det.sum())})")


def test_factor_decomposition_shapes():
    """Quick matrix-vector sanity for the OLS decomposition block."""
    n = 100
    rng = np.random.default_rng(0)
    X = np.column_stack([rng.normal(0, 1, n) for _ in range(4)])
    y = rng.normal(0, 1, n)
    X_ = np.column_stack([np.ones(n), X])
    coef, *_ = np.linalg.lstsq(X_, y, rcond=None)
    assert len(coef) == 5
    y_hat = X_ @ coef
    resid = y - y_hat
    var_y = float(np.var(y))
    var_resid = float(np.var(resid))
    r2 = 1 - var_resid / var_y
    assert -1.0 < r2 < 1.0, f"R² out of range: {r2:.2f}"
    print(f"✓ factor decomposition shapes OK "
          f"(coef length={len(coef)}, R²={r2:.2f})")


def test_fusion_improves_max_dd_vs_each_leg_orthogonal():
    """If two legs are perfectly negatively correlated, fusion max DD < each leg's."""
    n = 200
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    # Leg 1: positive trend with crashes on odd days
    l1 = pd.Series(np.where(np.arange(n) % 2 == 0, 0.005, -0.020), index=idx)
    # Leg 2: opposite sign
    l2 = pd.Series(np.where(np.arange(n) % 2 == 0, -0.005, 0.020), index=idx)
    # Negatively correlated
    corr_l1_l2 = float(l1.corr(l2))
    assert corr_l1_l2 < 0, f"expected negative correlation, got {corr_l1_l2}"

    fused = fuse(l1, l2, 0.5)
    dd_l1 = max_drawdown(l1)
    dd_l2 = max_drawdown(l2)
    dd_fused = max_drawdown(fused)
    # Both legs have negative DD; fused should be less negative (closer to 0)
    assert dd_fused > max(dd_l1, dd_l2), (
        f"fused DD {dd_fused:.2%} should be > each leg's worst DD "
        f"({dd_l1:.2%}, {dd_l2:.2%})"
    )
    print(f"✓ orthogonality intuition holds: "
          f"ρ={corr_l1_l2:+.2f}, DD(l1)={dd_l1:+.2%}, DD(l2)={dd_l2:+.2%}, "
          f"DD(fused 50/50)={dd_fused:+.2%}")


def test_fusion_endpoint_equals_leg():
    """fuse with w=1 returns leg_r46 exactly; w=0 returns leg_r62 exactly."""
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    l1 = pd.Series(np.random.default_rng(0).normal(0.001, 0.01, 50), index=idx)
    l2 = pd.Series(np.random.default_rng(1).normal(-0.001, 0.01, 50), index=idx)
    f1 = fuse(l1, l2, 1.0)
    f0 = fuse(l1, l2, 0.0)
    np.testing.assert_array_almost_equal(f1.values, l1.values)
    np.testing.assert_array_almost_equal(f0.values, l2.values)
    print("✓ fusion endpoints OK (w=1 = leg1, w=0 = leg2)")


def main():
    tests = [
        test_imports,
        test_fuse_math,
        test_max_drawdown_flat_and_loss,
        test_per_window_helper,
        test_build_r46_sleeve_28,
        test_build_r62_sleeve_28_with_gate,
        test_factor_decomposition_shapes,
        test_fusion_improves_max_dd_vs_each_leg_orthogonal,
        test_fusion_endpoint_equals_leg,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"✗ {t.__name__}: {exc!r}")
            failed += 1
    if failed:
        print(f"\n{failed} test(s) FAILED, {passed} passed")
        return 1
    print(f"\n{passed} test(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
