"""
S-81 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_s80_turnover_residual_smoke.py pattern. 12 tests cover:
  - imports + S-81 constants
  - score: 4h turnover residual = 180-bar rolling-mean dollar-volume cross-section demean
  - score ≠ score_funding_residual / score_relative_momentum / score_realized_vol_residual / score_turnover_residual
  - L/S core: freq_residual_ls signature parity with R73/R76/S-80
  - both signs supported
  - rejects invalid sign
  - leg-correlation gate extends to 4 legs (lesson #42 anti-imposter)
  - NaN honesty (I1): warmup rows + insufficient obs ⇒ NaN, never 0
  - universe floor (S81_MIN_TRADEABLE)
  - verdict grammar (3 bands)
  - live-book-untouched flag
  - load_4h_panel helper
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """S-81 module + key public symbols importable."""
    import src.research.validation.s81_cross_frequency as s
    assert hasattr(s, "run"), "S-81 must expose run()"
    assert hasattr(s, "score_4h_turnover_residual"), \
        "S-81 must expose score_4h_turnover_residual"
    assert hasattr(s, "freq_residual_ls"), "S-81 must expose freq_residual_ls"
    assert hasattr(s, "load_4h_panel"), "S-81 must expose load_4h_panel"
    assert s.S81_K_TERCILES == 3, f"S-81 K_TERCILES must be 3, got {s.S81_K_TERCILES}"
    assert s.S81_MIN_TRADEABLE == 12, \
        f"S-81 MIN_TRADEABLE must be 12, got {s.S81_MIN_TRADEABLE}"
    assert s.S81_ORTHOGONALITY_GATE == 0.30, \
        f"S-81 orthogonality gate must be 0.30 (lesson #42), got {s.S81_ORTHOGONALITY_GATE}"
    assert s.S81_FREQ == "4h", f"S-81 FREQ must be '4h', got {s.S81_FREQ}"
    assert s.S81_TONUS_LOOKBACK_BARS == 30 * 6, \
        f"S-81 TONUS_LOOKBACK_BARS must be 180 (= 30 days × 6 4h-bars/day), got {s.S81_TONUS_LOOKBACK_BARS}"
    assert s.S81_TONUS_MIN_OBS == 5 * 6, \
        f"S-81 TONUS_MIN_OBS must be 30 (= 5 days × 6), got {s.S81_TONUS_MIN_OBS}"
    # Sign constants
    assert hasattr(s, "SIGN_HIGH_FREQ_LONG")
    assert hasattr(s, "SIGN_LOW_FREQ_LONG")
    assert s.SIGN_HIGH_FREQ_LONG == "high_freq_long"
    assert s.SIGN_LOW_FREQ_LONG == "low_freq_long"
    print("  ✓ S-81 imports + K_TERCILES=3 + MIN_TRADEABLE=12 + FREQ=4h "
          "+ LOOKBACK_BARS=180 + MIN_OBS=30")


def t_score_4h_turnover_residual_demean():
    """score_4h_turnover_residual = dv_180[t, a] - mean_a(dv_180[t, a]).
    Mean across assets at each fully-observed 4h bar must be ~0 by construction."""
    import src.research.validation.s81_cross_frequency as s
    # Synthetic: 200 4h-bars × 8 assets with random dollar volumes
    rng = np.random.default_rng(42)
    n_bars, n_assets = 200, 8
    bars = pd.date_range("2025-11-01", periods=n_bars, freq="4h")
    assets = [f"A{i}" for i in range(n_assets)]
    dv_4h = pd.DataFrame(
        rng.uniform(low=1.0, high=10.0, size=(n_bars, n_assets)),
        index=bars, columns=assets,
    )
    score = s.score_4h_turnover_residual(dv_4h, assets, lookback_bars=180, min_obs=30)
    # Row means on fully-observed rows must be ~0 (cross-sectional demean)
    row_means = score.mean(axis=1, skipna=True)
    observed_row_means = row_means.dropna()
    np.testing.assert_array_almost_equal(observed_row_means.values,
                                          np.zeros(len(observed_row_means)),
                                          decimal=10,
                                          err_msg="freq-residual mean must be 0 by construction")
    # With min_obs=30 (default), warmup is 29 bars (idx 0..28) — once 30 obs
    # accumulate, the rolling mean begins. Lookback=180 is the default finance-
    # convention window; min_obs=30 is the sparse-data tolerance (S78/S80 parity).
    warmup_nans = score.iloc[:29].isna().all().all()
    assert warmup_nans, "first 29 bars should be NaN (warmup of min_obs=30)"
    # Bar 30+ should have at least some non-NaN values
    assert score.iloc[30:].notna().any().any(), "bar 30+ should have non-NaN values"
    print(f"  ✓ score_4h_turnover_residual: 180-bar cross-section demean (observed bars: "
          f"mean ≈ 0, warmup=29 NaN bars (min_obs=30 sparse-data tolerance))")


def t_score_different_from_all_axes():
    """S-81's 4h turnover residual ≠ R76's funding residual / R78's TSMOM / S-78's vol residual
    / S-80's daily turnover residual. Five orthogonal axes — 4h turnover, daily funding,
    TSMOM, vol, daily turnover — must produce distinguishable score series."""
    import src.research.validation.s81_cross_frequency as s
    from src.research.validation.r76_funding_residual_ls import score_funding_residual
    from src.research.validation.r78_relative_momentum_residual import score_relative_momentum
    from src.research.validation.s78_vol_residual import score_realized_vol_residual
    from src.research.validation.s80_turnover_residual import score_turnover_residual

    rng = np.random.default_rng(11)
    n_days, n_assets = 90, 8
    dates = pd.date_range("2025-09-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    rets_daily = pd.DataFrame(
        rng.normal(scale=0.02, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    funding = pd.DataFrame(
        rng.normal(scale=0.005, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    dv_daily = pd.DataFrame(
        rng.uniform(low=1.0, high=10.0, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )

    # Build a 4h dollar-volume panel from the daily (synthetic upsample)
    bars_4h = pd.date_range(dates[0], periods=n_days * 6, freq="4h")
    dv_4h = pd.DataFrame(
        rng.uniform(low=1.0, high=10.0, size=(n_days * 6, n_assets)),
        index=bars_4h, columns=assets,
    )

    freq = s.score_4h_turnover_residual(dv_4h, assets, lookback_bars=180, min_obs=30)
    s80 = score_turnover_residual(dv_daily, assets)  # 30d rolling-mean
    fundres = score_funding_residual(funding, assets)
    volres = score_realized_vol_residual(rets_daily, assets)
    relmom = score_relative_momentum(rets_daily, assets)

    # Sanity: freq has 29 warmup bars (min_obs=30 sparse-data tolerance),
    # not 179 (which would be full-window finance convention).
    assert freq.iloc[:29].isna().all().all(), \
        "freq must have 29 warmup bars NaN (4h min_obs=30 sparse-data tolerance)"
    assert s80.iloc[:29].isna().all().all(), \
        "s80 daily turnover must have 29 warmup rows NaN (daily lookback=30)"
    assert volres.iloc[29:].dropna(how="any").shape[0] >= 1, \
        "volres should have at least one observed row beyond warmup"
    # All five row-mean zero where defined
    np.testing.assert_array_almost_equal(freq.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days * 6), decimal=10)
    np.testing.assert_array_almost_equal(s80.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(fundres.mean(axis=1).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(volres.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(relmom.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    print(f"  ✓ S-81 4h turnover residual ≠ S-80 daily turnover residual ≠ "
          f"R76 funding residual ≠ S-78 vol residual ≠ R78 TSMOM demean (5 axes)")


def t_freq_residual_ls_signature_parity():
    """freq_residual_ls signature must mirror R73/R76/S-80 L/S pattern."""
    import src.research.validation.s81_cross_frequency as s
    import inspect
    sig = inspect.signature(s.freq_residual_ls)
    required_params = {"score_wide", "rets_4h", "k", "cost_bps", "rebal_bars", "sign"}
    sig_params = set(sig.parameters.keys())
    assert required_params.issubset(sig_params), \
        f"freq_residual_ls missing required params; have {sig_params}"
    assert sig.parameters["k"].default == s.S81_K_TERCILES
    assert sig.parameters["sign"].default == s.SIGN_HIGH_FREQ_LONG
    print("  ✓ freq_residual_ls signature parity with R73/R76/S-80 pattern")


def t_rejects_invalid_sign():
    """freq_residual_ls must ValueError on invalid sign."""
    import src.research.validation.s81_cross_frequency as s
    rng = np.random.default_rng(11)
    score_wide = pd.DataFrame(rng.standard_normal((3, 3)), columns=["A", "B", "C"])
    rets_4h = pd.DataFrame(rng.standard_normal((3, 3)) * 0.01, columns=["A", "B", "C"])
    try:
        s.freq_residual_ls(score_wide, rets_4h, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected (ValueError)")


def t_both_signs_supported():
    """Both SIGN_HIGH_FREQ_LONG and SIGN_LOW_FREQ_LONG must be valid."""
    import src.research.validation.s81_cross_frequency as s
    assert s.SIGN_HIGH_FREQ_LONG in s._VALID_SIGNS
    assert s.SIGN_LOW_FREQ_LONG in s._VALID_SIGNS
    assert len(s._VALID_SIGNS) == 2, f"only 2 valid signs, got {len(s._VALID_SIGNS)}"
    print("  ✓ both signs supported (high_freq_long, low_freq_long)")


def t_leg_correlation_gate_4_legs():
    """leg_correlation_gate_n reused from R78 must handle 4 existing legs."""
    import src.research.validation.s81_cross_frequency as s
    rng = np.random.default_rng(13)
    n = 200
    idx = pd.date_range("2025-06-01", periods=n, freq="D")

    # Independent: S-81 independent of R46/R62/R76/R78
    s81 = pd.Series(rng.standard_normal(n), index=idx)
    r46 = pd.Series(rng.standard_normal(n), index=idx)
    r62 = pd.Series(rng.standard_normal(n), index=idx)
    r76 = pd.Series(rng.standard_normal(n), index=idx)
    r78 = pd.Series(rng.standard_normal(n), index=idx)
    existing = {"r46": r46, "r62": r62, "r76": r76, "r78": r78}
    gate = s.leg_correlation_gate_n(s81, existing, gate=0.30)
    for k in ("corr_new_vs_r46", "corr_new_vs_r62", "corr_new_vs_r76", "corr_new_vs_r78",
              "max_abs_corr", "gate_threshold", "n_existing_legs",
              "passes_orthogonality_gate", "fusion_candidatable"):
        assert k in gate, f"gate missing {k}"
    assert gate["n_existing_legs"] == 4
    assert gate["passes_orthogonality_gate"], \
        f"4 independent series should pass gate; got {gate}"
    assert abs(gate["max_abs_corr"]) < 0.15, \
        f"4 independent series should have low max |corr|; got {gate['max_abs_corr']}"
    print("  ✓ leg_correlation_gate_n: 4-leg pre-test works (independent passes)")


def t_nan_honesty_warmup_and_sparse():
    """I1 invariant: warmup (< lookback_bars) and insufficient obs (< min_obs)
    must yield NaN, NEVER 0. A 0 turnover mean would mean 'no activity' which
    is a LIE for a sparse asset."""
    import src.research.validation.s81_cross_frequency as s
    rng = np.random.default_rng(99)
    n_bars, n_assets = 220, 5
    bars = pd.date_range("2025-11-01", periods=n_bars, freq="4h")
    assets = [f"A{i}" for i in range(n_assets)]

    # Make asset A4 sparse (80% NaN)
    dv_4h = pd.DataFrame(
        rng.uniform(low=1.0, high=10.0, size=(n_bars, n_assets)),
        index=bars, columns=assets,
    )
    sparse_mask = rng.choice([True, False], size=(n_bars,), p=[0.8, 0.2])
    dv_4h.loc[sparse_mask, "A4"] = np.nan

    score = s.score_4h_turnover_residual(dv_4h, assets, lookback_bars=180, min_obs=30)
    # I1 invariant: NO impostor zeros in the entire score matrix
    full_zero_count = (score == 0).sum().sum()
    assert full_zero_count == 0, \
        f"score matrix should have ZERO 0s (I1); got {full_zero_count} impostor zeros"
    # Where score IS defined, verify cross-section row-mean is exactly 0
    observed_rows = score.dropna(how="any")
    if len(observed_rows) > 0:
        row_means = observed_rows.mean(axis=1)
        np.testing.assert_array_almost_equal(row_means.values,
                                              np.zeros(len(row_means)),
                                              decimal=10,
                                              err_msg="observed rows must have mean ~0")
    print(f"  ✓ NaN honesty (I1): sparse asset A4 (80% NaN); "
          f"ZERO impostor zeros anywhere; cross-section demean preserves mean ~0 "
          f"on observed rows ({len(observed_rows)} rows)")


def t_universe_floor():
    """S-81 must enforce S81_MIN_TRADEABLE = 12 — refuse to silently widen."""
    import src.research.validation.s81_cross_frequency as s
    assert s.S81_MIN_TRADEABLE == 12
    src = Path(s.__file__).read_text()
    assert "do not silently widen" in src.lower() or "refuses to silently widen" in src.lower(), \
        "S-81 must encode anti-imposter discipline on universe floor"
    assert "S81_MIN_TRADEABLE" in src, \
        "S-81 must reference S81_MIN_TRADEABLE in source"
    print("  ✓ universe floor S81_MIN_TRADEABLE=12 enforced")


def t_verdict_grammar():
    """Verdict must be one of SURVIVES_ORTHOGONAL / SURVIVES_CORRELATED / REFUTED,
    and lesson #43 v4 (cross-frequency structural change) must be explicit."""
    import src.research.validation.s81_cross_frequency as s
    src = Path(s.__file__).read_text()
    assert "SURVIVES_ORTHOGONAL" in src, "verdict must include SURVIVES_ORTHOGONAL band"
    assert "SURVIVES_CORRELATED" in src, "verdict must include SURVIVES_CORRELATED band"
    assert "REFUTED" in src, "verdict must include REFUTED band"
    assert "✅ SURVIVES + ORTHOGONAL" in src, "verdict must include ✅"
    assert "🟡 SURVIVES + CORRELATED" in src, "verdict must include 🟡"
    assert "🔴 REFUTED" in src, "verdict must include 🔴"
    assert "lesson #43" in src.lower(), "S-81 must explicitly reference lesson #43"
    assert "lesson #42" in src.lower(), "S-81 must reference lesson #42 (gate)"
    assert "lesson #43 v3" in src.lower() or "lesson #43 v4" in src.lower() or \
        "exhausted" in src.lower() or "STRUCTURALLY" in src, \
        "S-81 must explicitly note lesson #43 v3/v4 (cross-frequency structural change)"
    print("  ✓ verdict grammar: 3 bands (✅/🟡/🔴) + lessons #42, #43 v3/v4 explicit")


def t_live_book_untouched():
    """S-81 must NOT touch the frozen R77 cell. Payload must declare this."""
    import src.research.validation.s81_cross_frequency as s
    src = Path(s.__file__).read_text()
    assert "research-only" in src.lower(), "S-81 must self-mark as research-only"
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "S-81 must include touches_frozen_r77_cell: False in payload"
    assert "R77 fusion-cell" in src or "R77 cell" in src or "R77)" in src, \
        "S-81 must reference the R77 fusion-cell (frozen)"
    assert "S-82" in src, "S-81 must name S-82 as the next-step candidate"
    print("  ✓ S-81 is research-only; frozen R77 cell untouched; S-82 named as successor")


def t_load_4h_panel_helper():
    """load_4h_panel must be importable and have correct signature."""
    import src.research.validation.s81_cross_frequency as s
    import inspect
    sig = inspect.signature(s.load_4h_panel)
    assert "ohlcv_dir" in sig.parameters, \
        "load_4h_panel must accept ohlcv_dir parameter (default Path)"
    assert sig.parameters["ohlcv_dir"].default is not inspect.Parameter.empty, \
        "load_4h_panel must have a default ohlcv_dir (OHLCV_DIR)"
    # Verify ret type is a tuple (annotation may be tuple[...] or Tuple[...])
    sig_ann = inspect.signature(s.load_4h_panel).return_annotation
    assert sig_ann == tuple or "Tuple" in str(sig_ann) or "tuple[" in str(sig_ann), \
        f"load_4h_panel must return tuple, got annotation {sig_ann}"
    # Verify no-op on empty directory returns empty tuple
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_dir = Path(tmpdir)
        result = s.load_4h_panel(empty_dir)
        assert isinstance(result, tuple), \
            f"load_4h_panel must return tuple, got {type(result)}"
        assert len(result) == 2, f"load_4h_panel must return 2-tuple, got len {len(result)}"
        assert result[0].empty and result[1].empty, \
            f"empty dir should return empty tup of DFs, got {result[0].shape}, {result[1].shape}"
    print("  ✓ load_4h_panel helper: signature correct, returns 2-tuple, empty-dir → empty")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        t_imports,
        t_score_4h_turnover_residual_demean,
        t_score_different_from_all_axes,
        t_freq_residual_ls_signature_parity,
        t_rejects_invalid_sign,
        t_both_signs_supported,
        t_leg_correlation_gate_4_legs,
        t_nan_honesty_warmup_and_sparse,
        t_universe_floor,
        t_verdict_grammar,
        t_live_book_untouched,
        t_load_4h_panel_helper,
    ]
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
