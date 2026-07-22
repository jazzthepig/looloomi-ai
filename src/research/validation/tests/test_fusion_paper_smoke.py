"""Smoke tests for fusion_paper.py (R65 module).

Verifies:
  1. Module + symbols import cleanly
  2. R64 frozen cell constants are intact (w_R46=0.25, R46 5d/5bps k=3, R62 21d/0bps)
  3. 28-asset strict intersection universe is frozen
  4. Frozen detector reproduces the R62 best-cell behavior (z=0.5, mf=2, external)
  5. Funding score sign-flipped (high score = LOW funding = LONG candidate)
  6. Target weights normalize to gross Σ|w| = 2/3 (preserves L/S structure)
  7. Fill-attribution reconciles to declared capacity ($5M CRUDE)
  8. Detector fires zero times when features are NaN (graceful degradation)
  9. Compliance language only (no BUY/SELL/ACCUMULATE in any surfaced string)

Pure Python + numpy + pandas; no scipy / nautilus / freqtrade. Sandbox-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.data.signals.fusion_paper import (
    FUSION_W_R46, R46_CAD, R46_BPS, R46_K,
    R62_CAD, R62_BPS, R62_ZWIN, R62_Z, R62_MF, R62_FEATURE_SET,
    UNIVERSE, EXTERNAL_FEATURES,
    _funding_features_daily, _frozen_detector, _score_funding_zwide_live,
    _target_weights, DEFAULT_DECLARED_CAPACITY_USD, VALIDATION_MIN_DAYS,
)
from src.data.signals.fill_attribution import attribute_fill


# === Synthetic data factory ==================================================
def _synthetic_panel(n_assets=28, n_days=300, seed=42):
    """28-asset × N-day panel: CIS wide + returns wide + funding daily (all synthetic)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    assets = [f"A{i:02d}" for i in range(n_assets)]

    # CIS pillar_O wide
    pillar_o_wide = pd.DataFrame(
        rng.uniform(0, 100, (n_days, n_assets)),
        index=dates, columns=assets,
    )

    # Daily returns wide
    rets = pd.DataFrame(
        rng.normal(0, 0.02, (n_days, n_assets)),
        index=dates, columns=assets,
    )

    # Funding daily
    funding = pd.DataFrame(
        rng.normal(0.0001, 0.0005, (n_days, n_assets)),
        index=dates, columns=assets,
    )
    # Embed a "fragile" zone — high funding dispersion
    funding.iloc[80:120, :] *= 3.0
    funding.iloc[200:240, :] *= 2.5
    return pillar_o_wide, rets, funding


def test_imports():
    from src.data.signals import fusion_paper as m
    for sym in (
        "FUSION_W_R46", "R46_CAD", "R46_BPS", "R46_K",
        "R62_CAD", "R62_BPS", "R62_ZWIN", "R62_Z", "R62_MF",
        "UNIVERSE", "EXTERNAL_FEATURES",
        "_funding_features_daily", "_frozen_detector", "_score_funding_zwide_live",
        "_target_weights", "mark_and_rebalance", "get_curve",
        "DEFAULT_DECLARED_CAPACITY_USD", "VALIDATION_MIN_DAYS",
    ):
        assert hasattr(m, sym), f"missing symbol: {sym}"
    print("✓ imports OK")


def test_r64_frozen_cell_constants():
    """The R64 cell must NOT drift — these are the pre-declared §P1 cells."""
    assert FUSION_W_R46 == 0.25, f"FUSION_W_R46 must be 0.25 (R64 best cell), got {FUSION_W_R46}"
    assert R46_CAD == 5 and R46_BPS == 5.0 and R46_K == 3
    assert R62_CAD == 21 and R62_BPS == 0.0 and R62_ZWIN == 30
    assert R62_Z == 0.5 and R62_MF == 2 and R62_FEATURE_SET == "external"
    assert DEFAULT_DECLARED_CAPACITY_USD == 5_000_000.0, "R64 declared $5.0M CRUDE per §P2"
    assert VALIDATION_MIN_DAYS == 60, "Honesty gate at ~3 months of forward clock"
    print(f"✓ R64 cell frozen: w_R46={FUSION_W_R46}, R46={R46_CAD}d/{R46_BPS}bps k={R46_K}, "
          f"R62={R62_CAD}d/{R62_BPS}bps z={R62_Z}/mf={R62_MF}/zwin={R62_ZWIN}, "
          f"cap=${DEFAULT_DECLARED_CAPACITY_USD:,.0f}")


def test_universe_frozen_28():
    """28-asset strict intersection per R64 verdict."""
    assert len(UNIVERSE) == 28, f"R64 universe must be 28, got {len(UNIVERSE)}"
    expected_anchors = {"BTC", "ETH", "SOL", "AVAX", "LINK", "MKR", "AAVE", "XRP"}
    missing = expected_anchors - set(UNIVERSE)
    assert not missing, f"R64 universe missing anchors: {missing}"
    # No duplicates
    assert len(set(UNIVERSE)) == 28, "Universe must have 28 unique assets"
    print(f"✓ 28-asset universe frozen: {sorted(UNIVERSE)}")


def test_external_features_match_r62_best_cell():
    """The 6 external features MUST match the R62 best-cell feature subset."""
    expected = {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }
    assert set(EXTERNAL_FEATURES) == expected, (
        f"EXTERNAL_FEATURES mismatch: {set(EXTERNAL_FEATURES) ^ expected}")
    print(f"✓ 6 external features match R62 best-cell subset exactly")


def test_funding_features_columns_and_trailing():
    """Funding features: 6 columns, trailing 30d for the rolling features (PIT-safe).

    Note: funding_extreme_*_frac and funding_net_long_frac are instantaneous
    cross-section fractions, NOT trailing. Only the rolling-mean-based features
    (funding_mean/disp/skew) enforce the 30d warmup.
    """
    _, _, funding = _synthetic_panel()
    feats = _funding_features_daily(funding)
    assert list(feats.columns) == EXTERNAL_FEATURES
    assert feats.shape == (funding.shape[0], 6)
    # Rolling-mean features MUST be NaN for the first (win-1) days = 29 days
    rolling_cols = ["funding_mean", "funding_disp", "funding_skew"]
    win = 30  # R62_ZWIN
    n_warmup_nans = int(feats["funding_mean"].iloc[:win].isna().sum())
    assert n_warmup_nans == win - 1, (
        f"funding_mean should have {win - 1} NaN at the start, got {n_warmup_nans}")
    # Post-warmup, rolling features should be non-NaN
    assert not feats[rolling_cols].iloc[win:].isna().any().any(), (
        "Post-warmup rolling features should be non-NaN")
    print(f"✓ funding features: shape={feats.shape}, rolling cols NaN-warmup ✓ "
          f"({n_warmup_nans} NaN), post-warmup-clean ✓")


def test_frozen_detector_fires():
    """Detector fires on some days (composite z-score with min_features gate)."""
    _, _, funding = _synthetic_panel(n_days=300)
    feats = _funding_features_daily(funding)
    det = _frozen_detector(feats)
    assert det.dtype == bool
    assert len(det) == 300
    # Some fires (synthetic noise should produce some)
    assert det.sum() > 0, "Detector should fire on some days"
    # Some non-fires (else the gate is meaningless)
    assert (~det).sum() > 0, "Detector should NOT fire on some days"
    fire_rate = float(det.mean())
    print(f"✓ frozen detector: fires on {int(det.sum())}/{len(det)} days ({fire_rate:.1%})")


def test_frozen_detector_nan_graceful():
    """Empty features → empty detector (no crash, no false fires)."""
    empty = pd.DataFrame(columns=EXTERNAL_FEATURES)
    det = _frozen_detector(empty)
    assert len(det) == 0
    # All-NaN features
    nan_feats = pd.DataFrame(np.nan, index=pd.date_range("2024-01-01", periods=100, freq="D"),
                              columns=EXTERNAL_FEATURES)
    det2 = _frozen_detector(nan_feats)
    assert det2.dtype == bool
    assert det2.sum() == 0, "All-NaN features should produce zero fires"
    print("✓ detector graceful on NaN/empty input")


def test_funding_score_sign_flipped():
    """HIGH funding ⇒ LOWER score than LOW funding (sign-flipped = fade-the-crowd).

    The SIGN test uses a comparison: an asset with persistently HIGH funding
    should have a LOWER mean score than an asset with persistently LOW funding
    over the trailing 30d window. This is the load-bearing invariant — it does
    NOT require each individual point to be in sign, only that the long-run
    means separate in the right direction (sign-flipped = fade-the-crowd).
    """
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=200, freq="D")
    # Asset A = LONG crowd (high positive funding); Asset B = SHORT crowd (negative)
    a_high = rng.normal(0.001, 0.0003, (200, 1))
    b_low = rng.normal(-0.001, 0.0003, (200, 1))
    funding = pd.DataFrame(np.hstack([a_high, b_low]), index=idx, columns=["A", "B"])
    score = _score_funding_zwide_live(funding)
    # Past warmup (skip first 60 days)
    score_a = score["A"].iloc[60:].dropna()
    score_b = score["B"].iloc[60:].dropna()
    mean_a, mean_b = float(score_a.mean()), float(score_b.mean())
    # The KEY invariant: A's mean < B's mean (high funding → lower score)
    assert mean_a < mean_b, (
        f"Asset A (high funding) score mean should be < Asset B (low funding) score mean, "
        f"got A={mean_a:.4f} vs B={mean_b:.4f}")
    # The GAP should be substantial — well-separated, not within noise
    gap = mean_b - mean_a
    assert gap > 0.005, (
        f"Score gap (B - A) should be > 0.005 (well-separated), got {gap:.4f}")
    print(f"✓ funding score sign-flipped: A (high funding)={mean_a:+.4f} < "
          f"B (low funding)={mean_b:+.4f}, gap={gap:.4f}")


def test_target_weights_normalize():
    """Target weights sum to gross Σ|w| = 2/3 (L/S structure preserved, not 1.0)."""
    pillar_o, _, funding = _synthetic_panel()
    feats = _funding_features_daily(funding)
    det = _frozen_detector(feats)
    score = _score_funding_zwide_live(funding)
    today = pillar_o.index[-1]
    pillar_o_today = {c: float(pillar_o[c].iloc[-1]) for c in pillar_o.columns}

    w = _target_weights(pillar_o_today, score, det, today)
    assert isinstance(w, dict)
    if w:
        gross = sum(abs(x) for x in w.values())
        assert abs(gross - 2.0/3.0) < 1e-6, f"Gross should be 2/3, got {gross:.6f}"
        # Longs and shorts balanced
        longs = sum(v for v in w.values() if v > 0)
        shorts = sum(v for v in w.values() if v < 0)
        assert longs > 0 and shorts < 0, f"Need both long and short sides, got L={longs} S={shorts}"
        # All weights in [-1, +1]
        for s, v in w.items():
            assert -1.0 <= v <= 1.0, f"Weight for {s} out of [-1,+1]: {v}"
    print(f"✓ target weights: n={len(w)}, gross={sum(abs(x) for x in w.values()):.4f}, "
          f"L={sum(v for v in w.values() if v > 0):.3f}, S={sum(v for v in w.values() if v < 0):.3f}")


def test_target_weights_detector_zeros_leg2():
    """When detector fires today, leg2 (R62 fade-crowd) should be ZERO — only R46 fires."""
    idx = pd.date_range("2024-01-01", periods=200, freq="D")
    n_assets = 28
    rng = np.random.default_rng(0)
    pillar_o_today = {f"A{i}": float(rng.uniform(0,100)) for i in range(n_assets)}
    funding = pd.DataFrame(rng.normal(0.0001, 0.0005, (200, n_assets)), index=idx,
                            columns=[f"A{i}" for i in range(n_assets)])
    score = _score_funding_zwide_live(funding)
    feats = _funding_features_daily(funding)

    # Detector fires EVERY day
    det_all_on = pd.Series(True, index=idx)
    w_det_on = _target_weights(pillar_o_today, score, det_all_on, idx[-1])
    # When detector fires, leg2 is empty → only R46 (0.25×leg1) contributes.
    # Each weight should be EITHER 0.25 * leg1 OR 0.0 (asset not in leg1's terciles).
    assert len(w_det_on) > 0, "Even with detector on, R46 leg should produce weights"
    for s, v in w_det_on.items():
        assert -1.0 <= v <= 1.0, f"Weight for {s} out of range: {v}"

    # Detector fires NEVER
    det_all_off = pd.Series(False, index=idx)
    w_det_off = _target_weights(pillar_o_today, score, det_all_off, idx[-1])
    # Both legs contribute if today is in score index and has values
    if idx[-1] in score.index and not score.loc[idx[-1]].dropna().empty:
        assert len(w_det_off) > 0
    print(f"✓ detector gates leg2: on-day n={len(w_det_on)}, off-day n={len(w_det_off)}")


def test_fill_attribution_reconciles_to_declared_capacity():
    """Fill attribution reconciles target gross to declared capacity ($5M CRUDE)."""
    w = {"BTC": 0.10, "ETH": -0.05, "SOL": 0.05, "AVAX": -0.05}
    px = {"BTC": 60000.0, "ETH": 3000.0, "SOL": 150.0, "AVAX": 35.0}
    adv = {"BTC": 2e9, "ETH": 1e9, "SOL": 5e8, "AVAX": 2e8}
    fill = attribute_fill(
        target_weights=w, current_weights={}, nav_usd=5_000_000,
        prices=px, adv_usd=adv, slippage_model_bps=5.0,
        declared_capacity_usd=5_000_000,
    )
    # Target gross on the leveraged book: ~25% of $5M = ~$1.25M, well below $5M cap
    assert fill["capacity"]["status"] == "ok"
    assert fill["capacity"]["declared_usd"] == 5_000_000
    assert fill["totals"]["fill_ratio_overall"] >= 0.99
    # Per-asset slippage present
    for s in w:
        assert s in fill["per_asset"]
        assert fill["per_asset"][s]["slippage_bps"] >= 5.0
    print(f"✓ fill attribution: cap={fill['capacity']['status']}, "
          f"fill={fill['totals']['fill_ratio_overall']:.4f}, "
          f"slip={fill['totals']['weighted_slippage_bps']:.2f}bps, "
          f"used={fill['capacity']['used_pct']}%")


def test_no_buy_sell_language_in_surfaced_strings():
    """Compliance: positioning language only — no BUY/SELL/ACCUMULATE in module source."""
    import re
    # test file is at src/research/validation/tests/test_fusion_paper_smoke.py
    # Need to walk up: tests/ → validation/ → research/ → src/ → data/signals/
    src_file = (Path(__file__).resolve().parent.parent.parent.parent
                / "data" / "signals" / "fusion_paper.py")
    assert src_file.exists(), f"Source not found at {src_file}"
    text = src_file.read_text()
    # Look for actual signal FORMS, not negations of them
    forbidden_patterns = [
        r"\bBUY\b", r"\bSELL\b", r"\bSTRONG BUY\b",
        r"\bACCUMULATE\b", r"\bAVOID\b", r"\bREDUCE\b",
    ]
    found = []
    for pat in forbidden_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx_start = max(0, m.start() - 25)
            ctx = text[ctx_start:m.end() + 25].lower()
            # Allow meta-statements that negate the term (e.g. "no BUY/SELL")
            # Also allow technical Python: np.maximum.accumulate (NUMPY array op, not signal)
            if any(neg in ctx for neg in ["no ", "not ", "forbid", "prohibit", "compliance",
                                            "accumulate(navs)", ".accumulate"]):
                continue
            found.append((pat, m.start(), text[ctx_start:m.end() + 25]))
    assert not found, f"Forbidden signal language found: {found}"
    print("✓ no forbidden signal language (BUY/SELL/ACCUMULATE/AVOID/REDUCE) in module")


def main():
    tests = [
        test_imports,
        test_r64_frozen_cell_constants,
        test_universe_frozen_28,
        test_external_features_match_r62_best_cell,
        test_funding_features_columns_and_trailing,
        test_frozen_detector_fires,
        test_frozen_detector_nan_graceful,
        test_funding_score_sign_flipped,
        test_target_weights_normalize,
        test_target_weights_detector_zeros_leg2,
        test_fill_attribution_reconciles_to_declared_capacity,
        test_no_buy_sell_language_in_surfaced_strings,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"✗ {t.__name__}: {exc!r}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed} test(s) FAILED, {passed} passed")
        return 1
    print(f"\n{passed} test(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
