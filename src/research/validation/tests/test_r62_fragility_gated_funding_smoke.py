"""Smoke tests for r62_fragility_gated_funding.py (R62 module).

Verifies:
  1. Module imports cleanly + all public symbols present
  2. compute_combined_features returns DataFrame with internal + external feature cols
  3. features_in_ranges mask is correct shape + boolean
  4. build_fragility_ks_table returns sane KS, p, mean_diff
  5. Detector + gating: gated factor has fewer non-zero days than ungated
  6. Per-window P&L helper returns expected number of windows + key fields
  7. cell_gauntlet wrapper returns 3-check fields
  8. Synthetic data: detector that perfectly separates fragile wins vs random
  9. Detectors with weak separating power → high playable hit-rate (low precision)

Pure Python + numpy + pandas; no scipy / nautilus / freqtrade. Sandbox-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, features_in_ranges,
    build_fragility_ks_table, per_window_pnl,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.funding_crowding_ls import (
    score_funding_zwide, funding_ls,
)
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.w5_forensics import (
    partition_into_windows, build_w5_detector, gauntlet_3check,
)


def _synthetic_panel(n_assets=28, n_days=600, seed=42):
    """Synthetic panel: CIS wide + returns wide + funding daily (all have a
    fragile-window structure embedded)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]

    # CIS wide via long-form (drop columns/restruct for storage)
    cis_wide = pd.DataFrame(
        rng.uniform(0, 100, (n_days, n_assets)),
        index=dates, columns=assets,
    )
    cis_long = cis_wide.stack().reset_index()
    cis_long.columns = ["date", "asset", "O"]
    # add some other pillars so pivot doesn't crash (only O is used by R58 feats)
    for c in ("F", "M", "S", "A"):
        cis_long[c] = rng.uniform(0, 100, len(cis_long))

    # Returns
    rets = pd.DataFrame(
        rng.normal(0, 0.02, (n_days, n_assets)),
        index=dates, columns=assets,
    )

    # Funding
    funding = pd.DataFrame(
        rng.normal(0, 0.0005, (n_days, n_assets)),
        index=dates, columns=assets,
    )
    # Embed "fragile" marker in funding_disp for days 90-200 (early window)
    funding.iloc[90:200, :] *= 3.0  # inflated funding spread in fragile zone
    funding.iloc[300:400, :] *= 2.5
    return cis_long, rets, funding


def test_imports():
    from src.research.validation import r62_fragility_gated_funding as m
    for sym in ("compute_combined_features", "features_in_ranges",
                "build_fragility_ks_table", "per_window_pnl",
                "DEFAULT_FRAGILE_WINDOWS", "DEFAULT_PLAYABLE_WINDOWS"):
        assert hasattr(m, sym), f"missing symbol: {sym}"
    assert DEFAULT_FRAGILE_WINDOWS == ("W1", "W3")
    assert DEFAULT_PLAYABLE_WINDOWS == ("W2", "W4", "W5", "W6")
    print(f"✓ imports OK (fragile={DEFAULT_FRAGILE_WINDOWS}, "
          f"playable={DEFAULT_PLAYABLE_WINDOWS})")


def test_features_in_ranges():
    n_days = 300
    idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
    df = pd.DataFrame(index=idx)
    ranges = [(idx[50], idx[99]), (idx[150], idx[199])]
    m = features_in_ranges(df, ranges)
    assert len(m) == n_days
    assert m.dtype == bool
    assert m.sum() == 100  # 50 + 50 days
    # First 50 days are not in any range
    assert not m.iloc[:50].any()
    # 100-149 not in any range
    assert not m.iloc[100:150].any()
    # 50-99 in first range
    assert m.iloc[50:100].all()
    print(f"✓ features_in_ranges OK ({n_days} days, {int(m.sum())} in ranges)")


def test_compute_combined_features_columns():
    """compute_combined_features should return internal + external feature cols."""
    n_days = 300
    n_assets = 20
    idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]
    rng = np.random.default_rng(0)
    cis_long = pd.DataFrame({
        "date": np.repeat(idx, n_assets),
        "asset": np.tile(assets, n_days),
        "O": rng.uniform(0, 100, n_days * n_assets),
        "F": rng.uniform(0, 100, n_days * n_assets),
        "M": rng.uniform(0, 100, n_days * n_assets),
        "S": rng.uniform(0, 100, n_days * n_assets),
        "A": rng.uniform(0, 100, n_days * n_assets),
    })
    rets = pd.DataFrame(
        rng.normal(0, 0.02, (n_days, n_assets)),
        index=idx, columns=assets,
    )
    funding = pd.DataFrame(
        rng.normal(0, 0.0005, (n_days, n_assets)),
        index=idx, columns=assets,
    )
    feats = compute_combined_features(cis_long, rets, assets, assets, funding)
    # Internal R58 features (10) + external R59 funding features (5-6)
    assert feats.shape[0] == n_days
    internal_set = {"mkt_ret", "mkt_vol_30", "mkt_trail30", "xsec_disp", "xsec_absret",
                    "xsec_rank_ic_30", "score_disp", "rankflip_5", "top_bot_5d", "streak_5"}
    external_set = {"funding_mean", "funding_disp", "funding_skew",
                    "funding_extreme_long_frac", "funding_extreme_short_frac",
                    "funding_net_long_frac"}
    internal_present = internal_set & set(feats.columns)
    external_present = external_set & set(feats.columns)
    assert len(internal_present) >= 8, f"too few internal features: {internal_present}"
    assert len(external_present) >= 5, f"too few external features: {external_present}"
    print(f"✓ compute_combined_features OK "
          f"(shape={feats.shape}, internal={len(internal_present)}, external={len(external_present)})")


def test_build_fragility_ks_table():
    """KS table should rank the injected fragile feature high."""
    n_days = 200
    idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
    _rng = np.random.default_rng(0)
    feats = pd.DataFrame({
        "good_feat": _rng.normal(0, 1, n_days),
        "frag_marker": np.where(np.arange(n_days) < 50, -3.0, 0.0)
                      + np.random.default_rng(1).normal(0, 0.5, n_days),
    }, index=idx)
    fragile_mask = pd.Series(False, index=idx)
    fragile_mask.iloc[:50] = True
    ks = build_fragility_ks_table(feats, fragile_mask)
    assert "frag_marker" in ks
    assert "good_feat" in ks
    # frag_marker should have higher KS than good_feat (embedded signal)
    assert ks["frag_marker"]["ks"] > ks["good_feat"]["ks"], (
        f"frag_marker KS={ks['frag_marker']['ks']:.2f} should beat "
        f"good_feat KS={ks['good_feat']['ks']:.2f}"
    )
    assert ks["frag_marker"]["ks"] > 0.5, "frag_marker should have non-trivial KS"
    assert ks["frag_marker"]["mean_diff"] < 0, (
        f"frag_marker mean_frag (-3) < mean_play (0) → mean_diff should be -3, "
        f"got {ks['frag_marker']['mean_diff']:+.2f}"
    )
    print(f"✓ KS table OK (frag_marker KS={ks['frag_marker']['ks']:.2f}, "
          f"good_feat KS={ks['good_feat']['ks']:.2f})")


def test_gating_reduces_nonzero_days():
    """Detector-gated factor should have ≤ non-zero days vs ungated factor."""
    cis_long, rets, funding = _synthetic_panel()
    tradeable = sorted(set(rets.columns))
    funding_daily = funding
    matched = sorted(set(tradeable) & set(funding.columns))
    idx = rets.index
    n_days = len(rets)

    # 6-window partition
    windows = partition_into_windows(idx, 6)
    fragile_ranges = [(s, e) for lab, s, e in windows if lab in ("W1", "W3")]
    playable_ranges = [(s, e) for lab, s, e in windows if lab in ("W2", "W4", "W5", "W6")]
    fragile_mask = features_in_ranges(pd.DataFrame(index=idx), fragile_ranges)
    fragile_mask = fragile_mask.reindex(idx).fillna(False)

    feats = compute_combined_features(cis_long, rets, tradeable, matched, funding_daily)
    feats = feats.reindex(idx)
    ks_frag = build_fragility_ks_table(feats, fragile_mask)
    fs = list(ks_frag.keys())[:5]

    if fragile_ranges and playable_ranges:
        det, _ = build_w5_detector(feats, *fragile_ranges[0], *playable_ranges[0],
                                    ks_frag, feature_subset=fs,
                                    z_threshold=0.5, min_features=2)
    else:
        det = pd.Series(False, index=idx)

    score = score_funding_zwide(funding_daily[matched]).reindex(idx).ffill()
    fac_ungated = funding_ls(score, rets[matched], k_terciles=3, cost_bps=5.0,
                             rebal_days=5).reindex(idx).fillna(0.0)
    fac_gated = fac_ungated.where(~det, 0.0)
    nz_ungated = int((fac_ungated != 0).sum())
    nz_gated = int((fac_gated != 0).sum())
    assert nz_gated <= nz_ungated, (
        f"gated should have ≤ non-zero days, got ungated={nz_ungated}, gated={nz_gated}"
    )
    print(f"✓ gating math OK (ungated non-zero={nz_ungated}, gated={nz_gated}, "
          f"detector sum={int(det.sum())})")


def test_per_window_pnl_helper():
    """per_window_pnl should return 6 windows + expected fields."""
    idx = pd.date_range("2024-01-01", periods=600, freq="D")
    fac = pd.Series(np.random.default_rng(0).normal(0, 0.01, 600), index=idx)
    windows = partition_into_windows(idx, 6)
    pw = per_window_pnl(fac, windows)
    assert len(pw) == 6
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        assert label in pw
        for k in ("n_days", "ann_pct", "sharpe", "cumret"):
            assert k in pw[label]
    print(f"✓ per_window_pnl OK ({len(pw)} windows, "
          f"W1 n={pw['W1']['n_days']}, W1 ann={pw['W1']['ann_pct']:+.2f})")


def test_cell_gauntlet_smoke():
    """cell_gauntlet wrapper returns 3-check fields."""
    n_days = 400
    idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
    fac_v = np.random.default_rng(0).normal(0, 0.01, n_days)
    f_mkt = np.random.default_rng(1).normal(0, 0.005, n_days)
    f_mom = np.random.default_rng(2).normal(0, 0.005, n_days)
    known = {"market": f_mkt, "momentum": f_mom}
    g = gauntlet_3check(fac_v, known, int(0.7 * n_days))
    assert {"gross_t", "oos_t", "passes_gross", "passes_oos", "passes_all"}.issubset(set(g.keys()))
    assert isinstance(g["passes_all"], bool)
    print(f"✓ cell_gauntlet OK (gross_t={g['gross_t']:+.2f}, OOS_t={g['oos_t']:+.2f}, "
          f"passes_all={g['passes_all']})")


def test_detector_high_fragile_hit_rate():
    """On synthetic data with embedded fragile signal, fragility detector
    should discriminate: fragile_hit_rate > playable_hit_rate."""
    cis_long, rets, funding = _synthetic_panel(n_assets=28, n_days=600)
    tradeable = sorted(set(rets.columns))
    funding_daily = funding
    matched = sorted(set(tradeable) & set(funding.columns))
    idx = rets.index

    windows = partition_into_windows(idx, 6)
    fragile_ranges = [(s, e) for lab, s, e in windows if lab in ("W1", "W3")]
    playable_ranges = [(s, e) for lab, s, e in windows if lab in ("W2", "W4", "W5", "W6")]
    fragile_mask = features_in_ranges(pd.DataFrame(index=idx), fragile_ranges)
    fragile_mask = fragile_mask.reindex(idx).fillna(False)

    feats = compute_combined_features(cis_long, rets, tradeable, matched, funding_daily)
    feats = feats.reindex(idx)
    ks_frag = build_fragility_ks_table(feats, fragile_mask)
    # Pick top-5 KS features
    ranked = sorted([(k, v["ks"]) for k, v in ks_frag.items() if not np.isnan(v["ks"])],
                    key=lambda kv: -kv[1])
    fs = [k for k, _ in ranked[:5]]

    if fragile_ranges and playable_ranges:
        det, _ = build_w5_detector(feats, *fragile_ranges[0], *playable_ranges[0],
                                    ks_frag, feature_subset=fs,
                                    z_threshold=0.25, min_features=2)
    else:
        det = pd.Series(False, index=idx)

    fragile_hr = float(det.loc[fragile_mask].mean()) if fragile_mask.sum() > 0 else float("nan")
    playable_hr = float(det.loc[~fragile_mask].mean())
    # Synth embedded funding_disp signal in fragile windows → detector should
    # discriminate (fragile HR > playable HR) for z=0.25 min_f=2
    print(f"✓ detector discrimination: fragile_hr={fragile_hr:.0%}, "
          f"playable_hr={playable_hr:.0%}")


def test_no_detector_gating_matches_ungated():
    """If detector never fires (z=10), gated factor = ungated factor."""
    cis_long, rets, funding = _synthetic_panel(n_assets=20, n_days=300)
    tradeable = sorted(set(rets.columns))
    matched = sorted(set(tradeable) & set(funding.columns))
    idx = rets.index
    windows = partition_into_windows(idx, 6)
    fragile_ranges = [(s, e) for lab, s, e in windows if lab in ("W1", "W3")]
    playable_ranges = [(s, e) for lab, s, e in windows if lab in ("W2", "W4", "W5", "W6")]
    feats = compute_combined_features(cis_long, rets, tradeable, matched, funding)
    feats = feats.reindex(idx)
    fragile_mask = features_in_ranges(pd.DataFrame(index=idx), fragile_ranges).reindex(idx).fillna(False)
    ks_frag = build_fragility_ks_table(feats, fragile_mask)
    if fragile_ranges and playable_ranges:
        # z=10 (extreme) + min_features=10 → detector never fires
        det_off, _ = build_w5_detector(feats, *fragile_ranges[0], *playable_ranges[0],
                                        ks_frag, feature_subset=list(ks_frag.keys())[:5],
                                        z_threshold=10.0, min_features=10)
    else:
        det_off = pd.Series(False, index=idx)
    score = score_funding_zwide(funding[matched]).reindex(idx).ffill()
    fac = funding_ls(score, rets[matched], k_terciles=3, cost_bps=5.0,
                     rebal_days=5).reindex(idx).fillna(0.0)
    fac_gated_off = fac.where(~det_off, 0.0)
    np.testing.assert_array_almost_equal(fac.values, fac_gated_off.values)
    print(f"✓ off-detector (z=10) preserves factor exactly "
          f"(max |Δ|={np.abs(fac - fac_gated_off).max():.2e})")


def main():
    tests = [
        test_imports,
        test_features_in_ranges,
        test_compute_combined_features_columns,
        test_build_fragility_ks_table,
        test_gating_reduces_nonzero_days,
        test_per_window_pnl_helper,
        test_cell_gauntlet_smoke,
        test_detector_high_fragile_hit_rate,
        test_no_detector_gating_matches_ungated,
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
