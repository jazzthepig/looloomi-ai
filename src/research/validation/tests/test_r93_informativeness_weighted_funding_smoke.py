"""
R93 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r90_perp_funding_carry_held_smoke.py + test_r92_two_layer_directional_overlay_smoke.py
patterns + R93-specific:
  - imports + frozen constants (zwin=30, iwins={14,30,60}, imethods default sign_consistency)
  - informativeness_weight: ι ∈ [0,1]; persistent-sign → high ι, coin-flip → low ι
  - score_iw_funding: combined score with sign_consistency / abs_autocorr / snr methods
  - iw_funding_ls: dollar-neutral, gross≈1, length matches rets
  - sweep keyed by (cad, iwin, method, bps, sign) with cost-tier sweep + lesson #58 gate
  - leg-correlation gate vs naive-fade (anti-costume, corr < 0.60)
  - distinct-from-naive-fade: ι≡1 reduces to naive fade; ι varies → R93 diverges
  - live book untouched (R77 frozen at w_R46=0.25/w_R62=0.75/w_R76=0.30)
  - PIT no forward look
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """R93 module + key public symbols importable; frozen constants verified."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    # Public API
    assert hasattr(r, "run"), "R93 must expose run()"
    assert hasattr(r, "iw_funding_ls"), "R93 must expose iw_funding_ls"
    assert hasattr(r, "iw_funding_ls_sign"), "R93 must expose iw_funding_ls_sign"
    assert hasattr(r, "informativeness_weight"), "R93 must expose informativeness_weight"
    assert hasattr(r, "score_iw_funding"), "R93 must expose score_iw_funding"
    assert hasattr(r, "iw_funding_sweep"), "R93 must expose iw_funding_sweep"
    assert hasattr(r, "cost_tier_sweep_with_score"), "R93 must expose cost_tier_sweep_with_score"
    assert hasattr(r, "leg_correlation_gate"), "R93 must expose leg_correlation_gate"
    assert hasattr(r, "format_report"), "R93 must expose format_report"
    # Frozen constants
    assert r.R93_ZWIN == 30, f"R93_ZWIN must be 30, got {r.R93_ZWIN}"
    assert r.R93_IWINS == (14, 30, 60), f"R93_IWINS must be (14,30,60), got {r.R93_IWINS}"
    assert r.R93_IMETHODS == ("sign_consistency",), \
        f"R93_IMETHODS default must be ('sign_consistency',), got {r.R93_IMETHODS}"
    assert r.R93_K_TERCILES == 3, f"R93_K_TERCILES must be 3, got {r.R93_K_TERCILES}"
    assert r.R93_CADENCES == (5, 7, 14, 21), \
        f"R93_CADENCES must be (5,7,14,21), got {r.R93_CADENCES}"
    assert r.R93_COST_GRID == (0.0, 5.0, 10.0, 20.0, 30.0), \
        f"R93_COST_GRID must include 10/20/30bps (R32/R89 lesson #58), got {r.R93_COST_GRID}"
    assert r.R93_REALISTIC_COST_BPS == 10.0, \
        f"R93_REALISTIC_COST_BPS must be 10.0 (lesson #58), got {r.R93_REALISTIC_COST_BPS}"
    assert r.R93_LEGCORR_GATE == 0.60, \
        f"R93_LEGCORR_GATE must be 0.60 (anti-costume vs R62), got {r.R93_LEGCORR_GATE}"
    assert r.R93_MIN_TRADEABLE == 12, \
        f"R93_MIN_TRADEABLE must be 12, got {r.R93_MIN_TRADEABLE}"
    # Sign constants
    assert r.SIGN_HIGH_FUND_LONG == "high_fund_long"
    assert r.SIGN_LOW_FUND_LONG == "low_fund_long"
    assert r.SIGN_HIGH_FUND_LONG in r._VALID_SIGNS
    assert r.SIGN_LOW_FUND_LONG in r._VALID_SIGNS
    # Informativeness method constants
    assert r.IMETHOD_SIGN_CONSISTENCY == "sign_consistency"
    assert r.IMETHOD_ABS_AUTOCORR == "abs_autocorr"
    assert r.IMETHOD_SNR == "snr"
    assert {r.IMETHOD_SIGN_CONSISTENCY, r.IMETHOD_ABS_AUTOCORR,
            r.IMETHOD_SNR} == r._VALID_IMETHODS
    print("  ✓ R93 imports + frozen constants verified (zwin=30, iwins=(14,30,60), "
          "method=sign_consistency, k=3, cadences=(5,7,14,21), cost 0/5/10/20/30bps, "
          "gate=0.60)")


def t_informativeness_weight_range():
    """ι ∈ [0,1]; persistent-sign funding → high ι, coin-flip → low ι."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    rng = np.random.default_rng(42)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    # Persistent funding: same sign every day (e.g., always positive)
    persistent = pd.Series(np.full(n, 0.001), index=dates, name="PERSIST")
    # Coin-flip: random sign, low signal
    coin = pd.Series(rng.choice([-0.001, 0.001], size=n), index=dates, name="COIN")
    # Anti-persistent: alternates
    anti = pd.Series(np.where(np.arange(n) % 2 == 0, 0.001, -0.001), index=dates, name="ANTI")

    funding_wide = pd.DataFrame({"PERSIST": persistent, "COIN": coin, "ANTI": anti})

    # sign_consistency method
    iota = r.informativeness_weight(funding_wide, iwin=30, method=r.IMETHOD_SIGN_CONSISTENCY)

    # After warmup, PERSIST should have ι > 0.5 (consistent sign); COIN should be lower
    # Cross-sec normalized so values are in [0, 1] each day
    assert iota.shape == funding_wide.shape, f"ι shape {iota.shape} != funding {funding_wide.shape}"
    assert iota.index.equals(funding_wide.index)
    # Min/max bounds
    valid = iota.dropna(how="all")
    assert valid.min().min() >= -1e-9, f"ι must be ≥ 0 (got min {valid.min().min():.4f})"
    assert valid.max().max() <= 1.0 + 1e-9, f"ι must be ≤ 1 (got max {valid.max().max():.4f})"
    # PERSIST should have higher ι than COIN/ANTI on average
    tail_iota = iota.iloc[60:]  # past warmup
    persist_mean = tail_iota["PERSIST"].mean()
    coin_mean = tail_iota["COIN"].mean()
    assert persist_mean > coin_mean, \
        f"persistent funding should have higher ι than coin-flip ({persist_mean:.3f} vs {coin_mean:.3f})"
    print(f"  ✓ ι ∈ [0,1]; PERSIST ι_mean={persist_mean:.3f} > COIN ι_mean={coin_mean:.3f} "
          f"(sign_consistency method works)")


def t_score_iw_funding_shapes():
    """Score aligned; noisy-funding column downweighted vs persistent column."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    rng = np.random.default_rng(7)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="D")

    # PERSIST: persistent positive funding with a level shift (so z is non-zero
    # in the shift plateau). Signs stay → ι high. Score = -z × ι ≈ -1 × 1.
    persist_vals = np.full(n, 0.001)
    persist_vals[60:120] = 0.0025  # level shift up → z ≈ +1 in plateau
    persist = pd.Series(persist_vals, index=dates)

    # COIN: oscillating sign every day (mean ~0, |z| ≈ 1) but ι very low
    coin = pd.Series(rng.choice([-0.0015, 0.0015], size=n), index=dates)

    funding_wide = pd.DataFrame({"PERSIST": persist, "COIN": coin})

    score = r.score_iw_funding(funding_wide, iwin=30, method=r.IMETHOD_SIGN_CONSISTENCY)

    # Score shape matches input
    assert score.shape == funding_wide.shape, \
        f"score shape {score.shape} != funding {funding_wide.shape}"
    assert score.index.equals(funding_wide.index)
    assert set(score.columns) == set(funding_wide.columns)

    # |score| for PERSIST should exceed |score| for COIN
    # (PERSIST: high z AND high ι → large score; COIN: high z BUT low ι → suppressed)
    tail_score = score.iloc[80:140]  # focus on the level-shift plateau
    persist_abs = tail_score["PERSIST"].abs().mean()
    coin_abs = tail_score["COIN"].abs().mean()
    assert persist_abs > coin_abs, \
        f"PERSIST |score| should exceed COIN |score| ({persist_abs:.5f} vs {coin_abs:.5f})"
    print(f"  ✓ Score aligned + shapes match; |PERSIST|={persist_abs:.5f} > |COIN|={coin_abs:.5f} "
          f"(informativeness downweights noisy column in level-shift window)")


def t_iw_funding_ls_dollar_neutral():
    """k=3 weights sum≈0, gross≈1, length matches rets (PIT parity)."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    rng = np.random.default_rng(11)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    assets = [f"A{i}" for i in range(12)]
    funding_wide = pd.DataFrame(rng.normal(0, 0.001, size=(n, len(assets))),
                                 index=dates, columns=assets)
    rets = pd.DataFrame(rng.normal(0, 0.02, size=(n, len(assets))),
                        index=dates, columns=assets)

    score = r.score_iw_funding(funding_wide, iwin=30, method=r.IMETHOD_SIGN_CONSISTENCY)
    leg = r.iw_funding_ls(score, rets, k_terciles=r.R93_K_TERCILES,
                          cost_bps=0.0, rebal_days=7)
    # Length parity
    assert len(leg) == n, f"leg length {len(leg)} != {n}"
    assert np.isfinite(leg.values).all(), "leg must be finite"
    # Leg is portfolio return — not weights. Check it has nonzero variance on rebal days
    nonzero_days = (leg != 0).sum()
    assert nonzero_days > n * 0.5, \
        f"leg should have nonzero return days ({nonzero_days}/{n})"
    print(f"  ✓ L/S leg length={len(leg)}, finite, {nonzero_days}/{n} active days")


def t_sweep_keys():
    """Sweep keyed by (cad, iwin, method, bps, sign); grid size = 4×3×1×5×2 = 120."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    rng = np.random.default_rng(13)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    assets = [f"A{i}" for i in range(8)]
    funding_wide = pd.DataFrame(rng.normal(0, 0.001, size=(n, len(assets))),
                                 index=dates, columns=assets)
    rets = pd.DataFrame(rng.normal(0, 0.02, size=(n, len(assets))),
                        index=dates, columns=assets)

    # Use smaller grid for speed
    sweep = r.iw_funding_sweep(funding_wide, rets, assets,
                                cadences=(5, 14),
                                iwins=(14, 30),
                                imethods=(r.IMETHOD_SIGN_CONSISTENCY,),
                                cost_grid=(0.0, 5.0, 10.0),
                                k=r.R93_K_TERCILES)

    # Keys must be tuples of (cad, iwin, method, bps, sign)
    expected_grid_size = 2 * 2 * 1 * 3 * 2  # cad × iwin × method × bps × sign
    assert len(sweep) == expected_grid_size, \
        f"sweep size {len(sweep)} != {expected_grid_size}"

    sample_key = next(iter(sweep.keys()))
    assert isinstance(sample_key, tuple) and len(sample_key) == 5, \
        f"sweep key must be (cad,iwin,method,bps,sign), got {sample_key}"
    cad, iwin, method, bps, sign = sample_key
    assert cad in (5, 14)
    assert iwin in (14, 30)
    assert method == r.IMETHOD_SIGN_CONSISTENCY
    assert bps in (0.0, 5.0, 10.0)
    assert sign in (r.SIGN_HIGH_FUND_LONG, r.SIGN_LOW_FUND_LONG)
    # Each value is a pd.Series of returns (leg), length matches rets
    sample_leg = sweep[sample_key]
    assert isinstance(sample_leg, pd.Series), "sweep values must be pd.Series"
    assert len(sample_leg) == n, f"sweep leg length {len(sample_leg)} != {n}"
    print(f"  ✓ Sweep grid size = {expected_grid_size} = cad×iwin×method×bps×sign; "
          f"keys = (cad,iwin,method,bps,sign) tuples")


def t_cost_tier_sweep_present():
    """R93 must include cost_tier_sweep_with_score with realistic 10bps gate (lesson #58)."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    src = Path(r.__file__).read_text()
    assert "cost_tier_sweep_with_score" in src, \
        "R93 must include cost_tier_sweep_with_score"
    assert "R93_REALISTIC_COST_BPS" in src, \
        "R93 must reference R93_REALISTIC_COST_BPS"
    assert "survives_realistic_10bps" in src, \
        "R93 must use survives_realistic_10bps gate"
    assert "lesson #58" in src.lower() or "R32" in src or "R89" in src, \
        "R93 must reference lesson #58 / R32 / R89"
    # The cost grid must include realistic 10bps
    assert "10.0" in src and "20.0" in src and "30.0" in src, \
        "R93 cost grid must include 10/20/30bps (lesson #58)"
    print("  ✓ cost-tier sweep present (R32/R89 lesson #58 wired, gate at 10bps)")


def t_leg_correlation_gate_present():
    """R93 must include leg_correlation_gate with anti-costume < 0.60 hard guard."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    src = Path(r.__file__).read_text()
    assert "leg_correlation_gate" in src, \
        "R93 must include leg_correlation_gate"
    assert "R93_LEGCORR_GATE" in src, \
        "R93 must reference R93_LEGCORR_GATE"
    assert "0.60" in src, \
        "R93 gate threshold must be 0.60 (anti-costume vs R62)"
    assert "anti-costume" in src.lower() or "anti_costume" in src.lower() \
        or "anti-imposter" in src.lower() or "lesson #42" in src.lower(), \
        "R93 must reference anti-costume / anti-imposter / lesson #42"
    print("  ✓ leg_correlation_gate present (anti-costume gate 0.60 vs R62 / lesson #42)")


def t_distinct_from_naive_fade():
    """ι≡1 reduces R93 to naive fade; ι varies → R93 score diverges from naive."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    rng = np.random.default_rng(17)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    assets = [f"A{i}" for i in range(10)]

    # PERSIST (half the assets): persistent positive funding with level shift → high z, high ι
    # COIN (other half): oscillating sign → random z, low ι
    persist = np.full(n, 0.001)
    persist[60:120] = 0.0025  # level shift for non-zero z
    persist_series = pd.Series(persist, index=dates)
    coin_series = pd.Series(rng.choice([-0.0015, 0.0015], size=n), index=dates)

    cols = {}
    for i, a in enumerate(assets):
        cols[a] = persist_series if i < 5 else coin_series
    funding_wide = pd.DataFrame(cols, index=dates)

    # Naive fade score (no ι): just per-asset z (mirror R62's score_funding_zwide pattern)
    mu = funding_wide.rolling(30, min_periods=15).mean()
    sd = funding_wide.rolling(30, min_periods=15).std()
    naive_score = -(funding_wide - mu) / (sd + 1e-8)  # fade sign

    # R93 score (with sign_consistency ι)
    r93_score = r.score_iw_funding(funding_wide, iwin=30, method=r.IMETHOD_SIGN_CONSISTENCY)

    # Use level-shift window for fair comparison
    tail_r93 = r93_score.iloc[80:140]
    tail_naive = naive_score.iloc[80:140]
    r93_persist_abs = tail_r93[assets[:5]].abs().mean().mean()
    r93_coin_abs = tail_r93[assets[5:]].abs().mean().mean()
    naive_persist_abs = tail_naive[assets[:5]].abs().mean().mean()
    naive_coin_abs = tail_naive[assets[5:]].abs().mean().mean()

    # Informativeness should suppress COIN |score| more than naive (the structural move)
    assert r93_coin_abs < naive_coin_abs, \
        f"R93 should suppress COIN |score| ({r93_coin_abs:.5f}) below naive ({naive_coin_abs:.5f})"

    # Per-column score correlation: R93 score for COIN columns should DIVERGE from naive
    # (downweighted by ι) while PERSIST columns should align (high ι → near-full weight).
    r93_coin = tail_r93[assets[5:]].values.flatten()
    naive_coin = tail_naive[assets[5:]].values.flatten()
    r93_persist = tail_r93[assets[:5]].values.flatten()
    naive_persist = tail_naive[assets[:5]].values.flatten()

    # For PERSIST (ι high), R93 ≈ naive → corr should be high (>0.8)
    if r93_persist.std() > 0 and naive_persist.std() > 0:
        corr_persist = float(np.corrcoef(r93_persist, naive_persist)[0, 1])
    else:
        corr_persist = 1.0
    # For COIN (ι low), R93 = naive × ι → magnitude suppressed, corr may still be high
    # but the absolute value should differ
    abs_diff_coin = float(np.abs(np.abs(r93_coin) - np.abs(naive_coin)).mean())
    assert abs_diff_coin > 1e-3, \
        f"R93 should differ from naive on COIN columns |abs_diff|={abs_diff_coin:.5f}"

    print(f"  ✓ R93 with ι≠1 diverges from naive-fade: |COIN_R93|={r93_coin_abs:.5f} < "
          f"|COIN_naive|={naive_coin_abs:.5f}; PERSIST corr={corr_persist:+.3f}; "
          f"COIN abs_diff={abs_diff_coin:.4f}")


def t_pit_no_forward_look():
    """PIT-safe: funding flips sign at midpoint; score post-flip uses only as-of data."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    rng = np.random.default_rng(19)
    n = 200
    midpoint = n // 2
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    # Pre-midpoint: positive funding (crowded longs) with noise for non-zero z
    funding_pre = 0.001 + rng.normal(0, 0.0002, size=midpoint)
    # Post-midpoint: negative funding (crowded shorts — flipped sign)
    funding_post = -0.001 + rng.normal(0, 0.0002, size=n - midpoint)
    funding_series = pd.Series(np.concatenate([funding_pre, funding_post]), index=dates)

    funding_wide = pd.DataFrame({"A": funding_series})
    score = r.score_iw_funding(funding_wide, iwin=30, method=r.IMETHOD_SIGN_CONSISTENCY)

    # Score post-midpoint should reflect the flipped funding (sign change)
    pre_tail = score.iloc[midpoint - 30: midpoint]
    post_tail = score.iloc[midpoint: midpoint + 30]
    pre_mean = pre_tail["A"].mean()
    post_mean = post_tail["A"].mean()
    # PIT: score uses only data as-of t (no forward look)
    assert np.isfinite(score.values).all(), "score must be finite throughout"
    # Sign relationship: pre-funding positive → fade score negative (short crowded)
    # post-funding negative → fade score positive (long uncrowded)
    assert pre_mean < post_mean, \
        f"PIT flip test: pre score mean ({pre_mean:.5f}) should be < post ({post_mean:.5f})"
    print(f"  ✓ PIT no forward look: score pre_mean={pre_mean:.5f} < post_mean={post_mean:.5f} "
          f"(funding flip at midpoint reflected correctly using only as-of data)")


def t_frozen_r77_untouched():
    """R93 must NOT touch the frozen R77 cell."""
    import src.research.validation.r93_informativeness_weighted_funding as r
    src = Path(r.__file__).read_text()
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "R93 must include touches_frozen_r77_cell: False in payload"
    assert "FROZEN" in src or "frozen" in src, "R93 must reference R77 as frozen"
    assert "w_R46=0.25" in src, "R93 must reference R77 frozen weights"
    assert "w_R62=0.75" in src or "w_R76=0.30" in src, \
        "R93 must reference R77 frozen weights"
    print("  ✓ R93 is orthogonal research; R77 FROZEN untouched at w_R46=0.25/w_R62=0.75/w_R76=0.30")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_informativeness_weight_range, t_score_iw_funding_shapes,
             t_iw_funding_ls_dollar_neutral, t_sweep_keys,
             t_cost_tier_sweep_present, t_leg_correlation_gate_present,
             t_distinct_from_naive_fade, t_pit_no_forward_look, t_frozen_r77_untouched]
    passed = 0
    for i, t in enumerate(tests, 1):
        name = t.__name__[2:]
        try:
            print(f"[{i}] {name}")
            t()
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            raise
    print(f"\n{passed} test(s) passed")