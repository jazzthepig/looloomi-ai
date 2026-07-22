"""Smoke tests for w5_forensics.py (R57 module).

Verifies:
  1. Module imports cleanly + all symbols present
  2. compute_features returns DataFrame with expected columns + sane coverage
  3. partition_into_windows returns 6 equal-length windows
  4. fingerprint_window returns per-feature stats dict
  5. ks_distance returns per-feature KS + p-value dict
  6. _ks_2samp (no-scipy) returns sane values for synthetic samples
  7. _spearman_corr (no-scipy) returns values in [-1, 1]
  8. build_w5_detector with synthetic W5-distinctive feature fires inside W5
  9. gauntlet_3check returns expected fields + has passes_all boolean

Pure Python + numpy + pandas; no scipy / nautilus / freqtrade. Reads the
shared cis_quality_absorption loaders but does NOT require the Mac drive to
be present (synthetic-data tests for the core helpers).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.w5_forensics import (
    compute_features, partition_into_windows, fingerprint_window,
    ks_distance, build_w5_detector, gauntlet_3check,
    _ks_2samp, _spearman_corr,
    N_WINDOWS, W5_START, W5_END, R46_BASELINE_T_GROSS,
)


def _synthetic_data(n_assets=40, n_days=400, seed=42):
    """Synthetic CIS long form (with 'O' pillar) + daily returns wide form.

    `cis` has columns: date, asset, O (pillar_O score). This matches what
    compute_features expects (it pivots 'O' to wide).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]
    # Score matrix (date × asset) — slowly mean-reverting
    score_w = pd.DataFrame(
        rng.uniform(20, 80, (n_days, n_assets)).cumsum(axis=0).clip(0, 100)
                  + rng.normal(0, 0.5, (n_days, n_assets)).cumsum(axis=0),
        index=dates, columns=assets,
    )
    rets = pd.DataFrame(
        rng.normal(0, 0.02, (n_days, n_assets))
            + 0.0002 * (score_w.values - score_w.values.mean(axis=0)),
        index=dates, columns=assets,
    )
    # Long form with 'O' column (matches cis_quality_absorption shape)
    cis_long = score_w.stack().reset_index()
    cis_long.columns = ["date", "asset", "O"]
    return cis_long, rets


def test_imports():
    from src.research.validation import w5_forensics as m
    for sym in ("compute_features", "partition_into_windows", "fingerprint_window",
                "ks_distance", "build_w5_detector", "gauntlet_3check",
                "_ks_2samp", "_spearman_corr",
                "N_WINDOWS", "W5_START", "W5_END"):
        assert hasattr(m, sym), f"missing symbol: {sym}"
    assert N_WINDOWS == 6
    print(f"✓ imports OK (N_WINDOWS={N_WINDOWS}, W5={W5_START.date()}→{W5_END.date()})")


def test_partition_into_windows():
    dates = pd.date_range("2024-01-01", periods=300, freq="D")
    windows = partition_into_windows(dates, n_windows=6)
    assert len(windows) == 6
    total = sum(int((e - s).days + 1) for _, s, e in windows)
    assert total == 300, f"window sum mismatch: {total} vs 300"
    # all labels W1..W6
    labels = [w[0] for w in windows]
    assert labels == ["W1", "W2", "W3", "W4", "W5", "W6"]
    print(f"✓ partition_into_windows OK (6 windows, {total} days total)")


def test_compute_features_shapes_and_coverage():
    cis, rets = _synthetic_data()
    assets = list(rets.columns)
    feats = compute_features(cis, rets, assets)
    assert isinstance(feats, pd.DataFrame)
    assert feats.shape[0] == rets.shape[0], f"row mismatch: {feats.shape[0]} vs {rets.shape[0]}"
    expected_cols = {"mkt_ret", "mkt_vol_30", "mkt_trail30",
                     "xsec_disp", "xsec_absret", "xsec_rank_ic_30",
                     "score_disp", "rankflip_5", "top_bot_5d", "streak_5"}
    assert expected_cols.issubset(set(feats.columns)), f"missing cols: {expected_cols - set(feats.columns)}"
    # mkt_ret has no warmup, should be ~100% coverage
    assert feats["mkt_ret"].notna().mean() > 0.95, f"mkt_ret coverage low: {feats['mkt_ret'].notna().mean()}"
    print(f"✓ compute_features shapes OK ({feats.shape[1]} features, "
          f"coverage mkt_ret={feats['mkt_ret'].notna().mean():.0%}, "
          f"mkt_vol_30={feats['mkt_vol_30'].notna().mean():.0%})")


def test_fingerprint_window_keys():
    cis, rets = _synthetic_data()
    assets = list(rets.columns)
    feats = compute_features(cis, rets, assets)
    fp = fingerprint_window(feats, rets.index[10], rets.index[100])
    assert "mkt_ret" in fp
    for col in feats.columns:
        assert col in fp, f"missing in fingerprint: {col}"
        assert {"n", "mean", "std", "q25", "q50", "q75"}.issubset(set(fp[col].keys())), \
            f"missing stats keys for {col}"
    print(f"✓ fingerprint_window keys OK ({len(fp)} features × 6 stats each)")


def test_ks_distance_shape_and_range():
    cis, rets = _synthetic_data()
    assets = list(rets.columns)
    feats = compute_features(cis, rets, assets)
    # Build a synthetic W5 window: shift mean by -2σ on one feature
    feats_synth = feats.copy()
    mid = len(feats) // 2
    feats_synth.iloc[mid:, feats_synth.columns.get_loc("score_disp")] -= 2 * feats["score_disp"].std()
    ks = ks_distance(feats_synth, feats_synth.index[mid], feats_synth.index[-1],
                     feats_synth.index[0], feats_synth.index[mid - 1])
    assert "score_disp" in ks
    assert 0.0 <= ks["score_disp"]["ks"] <= 1.0, f"KS out of range: {ks['score_disp']['ks']}"
    assert 0.0 <= ks["score_disp"]["p"] <= 1.0, f"p out of range: {ks['score_disp']['p']}"
    # score_disp mean diff should be ~ -2σ
    assert ks["score_disp"]["mean_diff"] < 0, "shifted mean_diff should be negative"
    print(f"✓ ks_distance shape/range OK (score_disp KS={ks['score_disp']['ks']:.2f}, "
          f"p={ks['score_disp']['p']:.3f}, mean_diff={ks['score_disp']['mean_diff']:.3f})")


def test_ks_2samp_synthetic():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 200)
    b = rng.normal(0, 1, 200)  # same dist → KS small
    ks, p = _ks_2samp(a, b)
    assert ks < 0.20, f"KS should be small for same dist: {ks}"
    assert p > 0.05, f"p should be >0.05 for same dist: {p}"
    c = rng.normal(3, 1, 200)  # shifted mean → KS larger
    ks2, p2 = _ks_2samp(a, c)
    assert ks2 > ks, f"KS for shifted should be larger: {ks2} vs {ks}"
    assert p2 < 0.001, f"p for shifted should be tiny: {p2}"
    print(f"✓ _ks_2samp OK (same-dist KS={ks:.3f} p={p:.3f}, shifted KS={ks2:.3f} p={p2:.4f})")


def test_spearman_corr_range():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 100)
    y = x + rng.normal(0, 0.1, 100)  # high positive corr
    r = _spearman_corr(x, y)
    assert 0.9 < r < 1.0, f"expected high positive corr, got {r}"
    y_neg = -x + rng.normal(0, 0.1, 100)
    r_neg = _spearman_corr(x, y_neg)
    assert -1.0 < r_neg < -0.9, f"expected high negative corr, got {r_neg}"
    print(f"✓ _spearman_corr OK (pos={r:.3f}, neg={r_neg:.3f})")


def test_build_w5_detector_fires_inside_synthetic_w5():
    cis, rets = _synthetic_data(n_days=400)
    assets = list(rets.columns)
    feats = compute_features(cis, rets, assets)
    # Synthesize a W5-like window: shift 5 features down for days 200-300
    w5_lo, w5_hi = feats.index[200], feats.index[300]
    feats_synth = feats.copy()
    shift_cols = ["score_disp", "mkt_trail30", "streak_5", "mkt_vol_30", "top_bot_5d"]
    for c in shift_cols:
        feats_synth.loc[w5_lo:w5_hi, c] -= 2 * feats[c].std()
    # Build ks_table manually for these 5 features
    ks_table = {}
    for c in shift_cols:
        a = feats_synth.loc[w5_lo:w5_hi, c].dropna().values
        b = feats_synth.loc[~((feats_synth.index >= w5_lo) & (feats_synth.index <= w5_hi)), c].dropna().values
        ks, p = _ks_2samp(a, b)
        ks_table[c] = {"ks": float(ks), "p": float(p),
                       "mean_diff": float(a.mean() - b.mean()),
                       "mean_w5": float(a.mean()), "mean_ref": float(b.mean())}
    det, _ = build_w5_detector(feats_synth, w5_lo, w5_hi, w5_lo, w5_hi,
                                ks_table, feature_subset=shift_cols,
                                z_threshold=0.0, min_features=2)
    # Synthetic W5 should have high hit-rate
    w5_hr = float(det.loc[(det.index >= w5_lo) & (det.index <= w5_hi)].mean())
    assert w5_hr > 0.50, f"detector should fire >50% inside synthetic W5: {w5_hr}"
    print(f"✓ detector fires inside synthetic W5 (W5_hr={w5_hr:.0%})")


def test_gauntlet_3check_fields():
    rng = np.random.default_rng(0)
    n = 500
    # Synthetic factor with positive IC
    fac = pd.Series(rng.normal(0.001, 0.01, n))
    mkt = pd.Series(rng.normal(0.0005, 0.01, n))
    mom = pd.Series(rng.normal(0, 0.01, n))
    known = {"market": mkt.values, "momentum": mom.values}
    r = gauntlet_3check(fac.values, known, oos_idx=int(0.7 * n))
    expected = {"n_full", "n_oos", "gross_alpha_ann_pct", "gross_t",
                "oos_alpha_ann_pct", "oos_t", "passes_gross", "passes_oos", "passes_all"}
    assert expected.issubset(set(r.keys())), f"missing: {expected - set(r.keys())}"
    assert isinstance(r["passes_all"], bool)
    # With synthetic positive IC, gross_t should be positive
    assert r["gross_t"] > 0, f"expected positive gross_t: {r['gross_t']}"
    print(f"✓ gauntlet_3check fields OK (n_full={r['n_full']}, gross_t={r['gross_t']:+.2f}, "
          f"OOS_t={r['oos_t']:+.2f}, passes_all={r['passes_all']})")


def main():
    tests = [
        test_imports,
        test_partition_into_windows,
        test_compute_features_shapes_and_coverage,
        test_fingerprint_window_keys,
        test_ks_distance_shape_and_range,
        test_ks_2samp_synthetic,
        test_spearman_corr_synthetic if False else test_spearman_corr_range,
        test_build_w5_detector_fires_inside_synthetic_w5,
        test_gauntlet_3check_fields,
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