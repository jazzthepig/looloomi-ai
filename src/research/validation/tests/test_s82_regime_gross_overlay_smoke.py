"""Smoke tests for S-82 regime-conditioned gross overlay.

Covers the anti-imposter invariants:
  1. btc_trend is CAUSAL (shift(1); today's value uses only <= yesterday).
  2. btc_trend warmup rows are NaN, never 0.
  3. regime_to_gross maps bands correctly (fixed edges).
  4. regime_to_gross maps NaN trend → 1.0 (neutral, no fabricated bet).
  5. normalize_gross_equal_avg forces IS-period mean to 1.0 using IS ONLY (no OOS leak).
  6. equal-avg-gross invariant: a CONSTANT-alpha book has ~equal IS mean return
     flat vs scaled (scaling can only help via TIMING, not leverage).
  7. sharpe / ann_return basic correctness + NaN guards.
  8. verdict logic: regime-INFORMATIVE book → scaled OOS beats flat.
"""
import numpy as np
import pandas as pd

from src.research.validation.s82_regime_gross_overlay import (
    btc_trend, regime_to_gross, normalize_gross_equal_avg,
    sharpe, ann_return, S82_BANDS, S82_BAND_EDGES,
)


def _dates(n):
    return pd.date_range("2024-01-01", periods=n, freq="D")


def t_btc_trend_causal():
    # constant +1%/day → trailing-30d ≈ (1.01^30 - 1); value at t uses <= t-1.
    n = 60
    rets = pd.Series(0.01, index=_dates(n))
    trend = btc_trend(rets, lookback=30)
    # warmup: first `lookback` rows (pre-shift) NaN; after shift, index 0..30 NaN-ish
    assert trend.iloc[:30].isna().all(), "warmup must be NaN"
    # causal: trend[t] must equal the trailing window ending at t-1, i.e. it should
    # NOT reflect the return realized on day t. Build a spike and check lag.
    rets2 = pd.Series(0.0, index=_dates(n))
    rets2.iloc[40] = 0.5  # huge one-day jump on day 40
    tr2 = btc_trend(rets2, lookback=5)
    # day 40's own jump must NOT be in trend[40] (causal) but SHOULD appear by trend[41+]
    assert abs(tr2.iloc[40]) < 1e-9, "trend[40] must not see day-40 return (causal)"
    assert tr2.iloc[41] > 0.4, "trend[41] should reflect the day-40 jump"
    print("✓ btc_trend causal + warmup NaN")


def t_btc_trend_warmup_nan_not_zero():
    rets = pd.Series(np.random.RandomState(0).normal(0, 0.02, 40), index=_dates(40))
    trend = btc_trend(rets, lookback=30)
    warmup = trend.iloc[:30]
    assert warmup.isna().all(), "warmup NaN"
    assert not (warmup == 0).any(), "no impostor zeros in warmup (I1)"
    print("✓ btc_trend warmup is NaN, not 0")


def t_regime_to_gross_bands():
    idx = _dates(5)
    trend = pd.Series([-0.30, -0.10, 0.0, 0.10, 0.30], index=idx)
    gross = regime_to_gross(trend, S82_BANDS)
    expected = [0.50, 0.75, 1.00, 1.25, 1.50]
    assert list(gross.values) == expected, f"band map wrong: {list(gross.values)}"
    # boundary: exactly on an edge goes to the UPPER band (searchsorted right)
    edge = pd.Series([S82_BAND_EDGES[0], S82_BAND_EDGES[3]], index=_dates(2))
    ge = regime_to_gross(edge, S82_BANDS)
    assert ge.iloc[0] == 0.75, "lower edge -0.15 → off band (0.75)"
    assert ge.iloc[1] == 1.50, "upper edge +0.20 → deep_on (1.50)"
    print("✓ regime_to_gross band mapping + edges")


def t_regime_to_gross_nan_neutral():
    trend = pd.Series([np.nan, 0.10, np.nan], index=_dates(3))
    gross = regime_to_gross(trend, S82_BANDS)
    assert gross.iloc[0] == 1.0 and gross.iloc[2] == 1.0, "NaN trend → gross 1.0"
    assert gross.iloc[1] == 1.25, "valid trend still mapped"
    print("✓ regime_to_gross NaN → neutral 1.0 (no fabricated bet)")


def t_normalize_equal_avg_is_only():
    # gross alternates 0.5/1.5; IS mean should be forced to 1.0 using IS slice only.
    n = 100
    g = pd.Series(np.where(np.arange(n) % 2 == 0, 0.5, 1.5), index=_dates(n))
    cut = 70
    norm, scale = normalize_gross_equal_avg(g, cut)
    assert abs(norm.iloc[:cut].mean() - 1.0) < 1e-9, "IS mean forced to 1.0"
    # scale derived from IS only — OOS mean may drift (that's the honest part)
    assert abs(scale - 1.0 / g.iloc[:cut].mean()) < 1e-12, "scale from IS mean"
    print("✓ normalize_gross_equal_avg calibrates on IS only")


def t_equal_gross_removes_leverage_confound():
    # CONSTANT-alpha book: same expected return every day, independent of regime.
    # After equal-avg-gross normalization, scaled IS mean ≈ flat IS mean (no free
    # lunch from leverage). Any difference is only from gross-return covariance = 0 here.
    rng = np.random.RandomState(42)
    n = 200
    book = pd.Series(rng.normal(0.001, 0.01, n), index=_dates(n))  # regime-invariant
    trend = pd.Series(rng.normal(0.0, 0.2, n), index=_dates(n))
    gross_raw = regime_to_gross(trend, S82_BANDS)
    cut = 140
    gross_norm, _ = normalize_gross_equal_avg(gross_raw, cut)
    flat_is = book.iloc[:cut]
    scaled_is = (book * gross_norm).iloc[:cut]
    # means should be close (regime-invariant book × mean-1 gross, uncorrelated)
    assert abs(scaled_is.mean() - flat_is.mean()) < 0.0005, \
        f"leverage confound not removed: {scaled_is.mean()} vs {flat_is.mean()}"
    print("✓ equal-avg-gross removes leverage confound on regime-invariant book")


def t_sharpe_ann_guards():
    r = pd.Series([0.01, 0.02, -0.01, 0.03], index=_dates(4))
    assert np.isfinite(sharpe(r)), "sharpe finite on real data"
    assert np.isfinite(ann_return(r)), "ann finite"
    assert np.isnan(sharpe(pd.Series([0.01], index=_dates(1)))), "sharpe NaN on <2 obs"
    assert np.isnan(sharpe(pd.Series([0.01, 0.01], index=_dates(2)))), "sharpe NaN zero-var"
    print("✓ sharpe / ann_return NaN guards")


def t_informative_regime_helps():
    # Construct a book whose alpha IS regime-dependent: positive when trend>0,
    # ~0 when trend<0. A gross schedule that presses in risk-on MUST beat flat OOS
    # even at equal average gross (timing is informative).
    rng = np.random.RandomState(7)
    n = 300
    idx = _dates(n)
    trend = pd.Series(np.sin(np.linspace(0, 8 * np.pi, n)) * 0.25, index=idx)
    gross_raw = regime_to_gross(trend, S82_BANDS)
    # book: mean return scales with gross_raw signal (informative)
    base = np.where(gross_raw.values > 1.0, 0.003, -0.0005)
    book = pd.Series(base + rng.normal(0, 0.005, n), index=idx)
    cut = 210
    gross_norm, _ = normalize_gross_equal_avg(gross_raw, cut)
    flat_oos = book.iloc[cut:]
    scaled_oos = (book * gross_norm).iloc[cut:]
    assert scaled_oos.mean() > flat_oos.mean(), \
        "informative regime scaling must lift OOS mean return at equal avg gross"
    print("✓ informative regime scaling lifts OOS (timing edge, not leverage)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_") and callable(v)]
    for fn in tests:
        fn()
    print(f"\n✅ {len(tests)}/{len(tests)} S-82 smoke tests pass")
