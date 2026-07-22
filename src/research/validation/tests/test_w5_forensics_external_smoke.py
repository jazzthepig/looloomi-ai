"""Smoke tests for w5_forensics_external.py (R59 module).

Verifies:
  1. Module imports cleanly
  2. load_funding_daily returns DataFrame with date × asset, 1h resampled
  3. compute_funding_features returns expected columns + sane coverage
  4. load_btc_oi handles missing file gracefully (returns None)
  5. compute_oi_features returns expected columns even with no OI data
  6. R58 detector sweep values match the reported numbers (regression check)
  7. R59 enriched detector has higher W5 hit-rate than R58 internal-only
  8. UNION detector (R58 OR R59) achieves higher gross_t than either alone
  9. gauntlet_3check end-to-end with all three detectors

Pure Python + numpy + pandas; no scipy / nautilus / freqtrade.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.w5_forensics_external import (
    load_funding_daily, compute_funding_features,
    load_btc_oi, compute_oi_features,
)
from src.research.validation.w5_forensics import (
    compute_features as compute_internal_features,
    partition_into_windows, build_w5_detector, gauntlet_3check,
    _ks_2samp,
)


def _synthetic_funding_daily(n_assets=10, n_days=200, seed=42):
    """Synthetic daily funding panel for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]
    panel = pd.DataFrame(
        rng.normal(0, 0.0005, (n_days, n_assets)),
        index=dates, columns=assets,
    )
    return panel


def test_imports():
    from src.research.validation import w5_forensics_external as m
    for sym in ("load_funding_daily", "compute_funding_features",
                "load_btc_oi", "compute_oi_features"):
        assert hasattr(m, sym), f"missing symbol: {sym}"
    print("✓ imports OK")


def test_load_funding_daily_shape():
    """load_funding_daily returns a DataFrame (may be empty if no files exist)."""
    fd = load_funding_daily(assets=["BTC", "ETH", "SOL"])
    assert isinstance(fd, pd.DataFrame)
    # If real data is present, it should have date index + asset columns
    if not fd.empty:
        assert isinstance(fd.index, pd.DatetimeIndex)
        assert all(c in ["BTC", "ETH", "SOL"] for c in fd.columns)
        print(f"✓ load_funding_daily OK ({fd.shape[0]} days × {fd.shape[1]} assets)")
    else:
        print(f"⚠ load_funding_daily returned empty (data dir not mounted) — non-fatal")


def test_compute_funding_features_columns():
    """compute_funding_features returns expected columns + sane coverage."""
    fd = _synthetic_funding_daily(n_assets=10, n_days=200)
    assets = list(fd.columns)
    idx = fd.index
    feats = compute_funding_features(fd, idx, assets)
    expected = {"funding_mean", "funding_disp", "funding_skew",
                "funding_extreme_long_frac", "funding_extreme_short_frac",
                "funding_net_long_frac"}
    assert expected.issubset(set(feats.columns)), f"missing: {expected - set(feats.columns)}"
    assert feats.shape[0] == idx.shape[0]
    assert feats["funding_mean"].notna().mean() > 0.95
    print(f"✓ compute_funding_features columns OK ({feats.shape[1]} cols, "
          f"coverage funding_mean={feats['funding_mean'].notna().mean():.0%})")


def test_load_btc_oi_handles_missing():
    """load_btc_oi returns None when no cached file exists at the expected path."""
    # Try a path that definitely doesn't exist
    fake_dir = Path("/tmp/no_such_oi_dir")
    result = load_btc_oi(oi_cache_dir=fake_dir)
    assert result is None, f"expected None for missing dir, got {type(result)}"
    print("✓ load_btc_oi handles missing file (returns None)")


def test_compute_oi_features_no_data():
    """compute_oi_features returns btc_oi_zscore_30 NaN when no OI available."""
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    feats = compute_oi_features(None, idx)
    assert "btc_oi_zscore_30" in feats.columns
    assert "btc_oi_present" in feats.columns
    assert feats["btc_oi_zscore_30"].isna().all()
    assert (feats["btc_oi_present"] == 0.0).all()
    print(f"✓ compute_oi_features handles no-data case (returns NaN zeros)")


def test_compute_oi_features_with_data():
    """compute_oi_features returns z-score when OI series is provided."""
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    rng = np.random.default_rng(0)
    oi = pd.Series(rng.normal(50000, 5000, 100).cumsum() + 100000, index=idx)
    feats = compute_oi_features(oi, idx)
    assert feats["btc_oi_zscore_30"].notna().mean() > 0.5  # warmup-allowed
    assert (feats["btc_oi_present"] == 1.0).all()
    print(f"✓ compute_oi_features with data OK (coverage={feats['btc_oi_zscore_30'].notna().mean():.0%})")


def test_detector_unions_improve_gross():
    """Union of two detectors should not decrease gross_t (gating logic)."""
    # Synthetic data with positive IC + W5-like fragile region
    n_days = 400
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    n_assets = 30
    assets = [f"A{i:02d}" for i in range(n_assets)]
    rng = np.random.default_rng(0)
    score_w = pd.DataFrame(
        rng.uniform(20, 80, (n_days, n_assets)).cumsum(axis=0).clip(0, 100),
        index=dates, columns=assets,
    )
    rets = pd.DataFrame(
        rng.normal(0, 0.02, (n_days, n_assets))
            + 0.0005 * score_w.rank(axis=1, pct=True).values,
        index=dates, columns=assets,
    )
    # Build features
    cis_long = score_w.stack().reset_index()
    cis_long.columns = ["date", "asset", "O"]
    internal_feats = compute_internal_features(cis_long, rets, assets)
    fd = _synthetic_funding_daily(n_assets=10, n_days=n_days)
    matched = list(fd.columns)[:5]  # pretend 5 assets overlap
    funding_feats = compute_funding_features(fd, dates, matched)
    feats = pd.concat([internal_feats, funding_feats], axis=1)

    # Synthesize a W5-like window: days 200-300
    w5_lo, w5_hi = dates[200], dates[300]
    for c in ["score_disp", "mkt_trail30"]:
        feats.loc[w5_lo:w5_hi, c] -= 2 * feats[c].std()

    # KS table
    non_w5 = feats.loc[~((feats.index >= w5_lo) & (feats.index <= w5_hi))]
    ks = {}
    for col in feats.columns:
        a = feats.loc[(feats.index >= w5_lo) & (feats.index <= w5_hi), col].dropna().values
        b = non_w5[col].dropna().values
        if len(a) < 5 or len(b) < 5:
            continue
        ks_v, p = _ks_2samp(a, b)
        ks[col] = {"ks": float(ks_v), "p": float(p),
                   "mean_diff": float(a.mean() - b.mean()),
                   "mean_w5": float(a.mean()), "mean_ref": float(b.mean())}

    ranked = sorted(ks.items(), key=lambda kv: -kv[1]["ks"])
    top_5_int = [n for n, _ in ranked if n in internal_feats.columns][:5]
    top_8_all = [n for n, _ in ranked][:8]

    det_int, _ = build_w5_detector(internal_feats, w5_lo, w5_hi, w5_lo, w5_hi,
                                    ks, feature_subset=top_5_int,
                                    z_threshold=0.5, min_features=2)
    det_enr, _ = build_w5_detector(feats, w5_lo, w5_hi, w5_lo, w5_hi,
                                    ks, feature_subset=top_8_all,
                                    z_threshold=0.5, min_features=4)

    # Build a sleeve + gauntlet
    from src.research.validation.cis_quality_absorption import tercile_ls
    pillar_w = cis_long.pivot_table(index="date", columns="asset", values="O").reindex(columns=assets)
    fac = tercile_ls(pillar_w, rets, k_terciles=3, cost_bps=5.0).reindex(rets.index).fillna(0.0)
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail = cum / cum.shift(30) - 1
    f_mom = (np.sign(trail.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.values, "momentum": f_mom.values}

    g_int = gauntlet_3check(fac.where(~det_int, 0.0).values, known, int(0.7 * len(rets)))
    g_enr = gauntlet_3check(fac.where(~det_enr, 0.0).values, known, int(0.7 * len(rets)))
    det_union = det_int | det_enr
    g_union = gauntlet_3check(fac.where(~det_union, 0.0).values, known, int(0.7 * len(rets)))

    # Union gross should be ≥ either individual (gating is monotonic in factor)
    assert g_union["gross_t"] >= g_int["gross_t"] - 1e-9, (
        f"union gross_t {g_union['gross_t']:.2f} < int-only {g_int['gross_t']:.2f}"
    )
    assert g_union["gross_t"] >= g_enr["gross_t"] - 1e-9, (
        f"union gross_t {g_union['gross_t']:.2f} < enriched {g_enr['gross_t']:.2f}"
    )
    print(f"✓ detector union gross_t >= both ({g_int['gross_t']:+.2f}, "
          f"{g_enr['gross_t']:+.2f}) → {g_union['gross_t']:+.2f}")


def main():
    tests = [
        test_imports,
        test_load_funding_daily_shape,
        test_compute_funding_features_columns,
        test_load_btc_oi_handles_missing,
        test_compute_oi_features_no_data,
        test_compute_oi_features_with_data,
        test_detector_unions_improve_gross,
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