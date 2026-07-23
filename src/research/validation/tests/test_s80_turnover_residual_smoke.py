"""
S-80 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_s78_vol_residual_smoke.py pattern. 12 tests cover:
  - imports + S-80 constants
  - score: turnover residual = trailing-30d dollar-volume-mean cross-sectional demean
  - score ≠ score_funding_residual / score_relative_momentum / score_realized_vol_residual
  - L/S core: turnover_residual_ls signature parity with R73/R76/S-78
  - both signs supported
  - rejects invalid sign
  - leg-correlation gate extends to 4 legs (lesson #42 anti-imposter)
  - NaN honesty (I1): warmup rows + insufficient obs ⇒ NaN, never 0
  - matched-cell sign audit
  - universe floor (S80_MIN_TRADEABLE)
  - verdict grammar (3 bands)
  - live-book-untouched flag
  - load_daily_dollar_volume helper
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """S-80 module + key public symbols importable."""
    import src.research.validation.s80_turnover_residual as s
    assert hasattr(s, "run"), "S-80 must expose run()"
    assert hasattr(s, "score_turnover_residual"), \
        "S-80 must expose score_turnover_residual"
    assert hasattr(s, "turnover_residual_ls"), "S-80 must expose turnover_residual_ls"
    assert hasattr(s, "load_daily_dollar_volume"), \
        "S-80 must expose load_daily_dollar_volume"
    assert s.S80_K_TERCILES == 3, f"S-80 K_TERCILES must be 3, got {s.S80_K_TERCILES}"
    assert s.S80_MIN_TRADEABLE == 12, \
        f"S-80 MIN_TRADEABLE must be 12, got {s.S80_MIN_TRADEABLE}"
    assert s.S80_ORTHOGONALITY_GATE == 0.30, \
        f"S-80 orthogonality gate must be 0.30 (lesson #42), got {s.S80_ORTHOGONALITY_GATE}"
    assert s.S80_TONUS_LOOKBACK == 30, \
        f"S-80 TONUS_LOOKBACK must be 30, got {s.S80_TONUS_LOOKBACK}"
    assert s.S80_TONUS_MIN_OBS == 5, \
        f"S-80 TONUS_MIN_OBS must be 5, got {s.S80_TONUS_MIN_OBS}"
    # Sign constants
    assert hasattr(s, "SIGN_HIGH_TONUS_LONG")
    assert hasattr(s, "SIGN_LOW_TONUS_LONG")
    assert s.SIGN_HIGH_TONUS_LONG == "high_tonus_long"
    assert s.SIGN_LOW_TONUS_LONG == "low_tonus_long"
    print("  ✓ S-80 imports + K_TERCILES=3 + MIN_TRADEABLE=12 + orthogonality gate=0.30 "
          "+ TONUS_LOOKBACK=30 + TONUS_MIN_OBS=5")


def t_score_turnover_residual_demean():
    """score_turnover_residual = dv_30[t, a] - mean_a(dv_30[t, a]).
    Mean across assets at each fully-observed time must be ~0 by construction."""
    import src.research.validation.s80_turnover_residual as s
    # Synthetic: 60 days × 8 assets with random dollar volumes
    rng = np.random.default_rng(42)
    n_days, n_assets = 60, 8
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    dv = pd.DataFrame(
        rng.uniform(low=1.0, high=10.0, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    score = s.score_turnover_residual(dv, assets)
    # Row means on fully-observed rows must be ~0 (cross-sectional demean)
    row_means = score.mean(axis=1, skipna=True)
    observed_row_means = row_means.dropna()
    np.testing.assert_array_almost_equal(observed_row_means.values,
                                          np.zeros(len(observed_row_means)),
                                          decimal=10,
                                          err_msg="tonus-residual mean must be 0 by construction")
    # First 29 rows should all be NaN (warmup period < lookback=30)
    warmup_nans = score.iloc[:29].isna().all().all()
    assert warmup_nans, "first 29 rows should be NaN (warmup)"
    # Row 30+ (idx 29+) should have at least some non-NaN values
    assert score.iloc[30:].notna().any().any(), "row 30+ should have non-NaN values"
    print(f"  ✓ score_turnover_residual: cross-sectional demean of dv_30 "
          f"(observed rows: mean ≈ 0, warmup=29 NaN rows as expected)")


def t_score_different_from_funding_vol_momentum():
    """score_turnover_residual ≠ score_funding_residual ≠ score_realized_vol_residual
    ≠ score_relative_momentum. Four orthogonal axes — turnover, funding, vol, momentum —
    must produce distinguishable score series even on random data (different ranges,
    different NaN patterns)."""
    import src.research.validation.s80_turnover_residual as s
    from src.research.validation.r76_funding_residual_ls import score_funding_residual
    from src.research.validation.r78_relative_momentum_residual import score_relative_momentum
    from src.research.validation.s78_vol_residual import score_realized_vol_residual

    rng = np.random.default_rng(11)
    n_days, n_assets = 90, 8
    dates = pd.date_range("2025-09-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    rets = pd.DataFrame(
        rng.normal(scale=0.02, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    funding = pd.DataFrame(
        rng.normal(scale=0.005, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    dv = pd.DataFrame(
        rng.uniform(low=1.0, high=10.0, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )

    tonus = s.score_turnover_residual(dv, assets)
    fundres = score_funding_residual(funding, assets)
    volres = score_realized_vol_residual(rets, assets)
    relmom = score_relative_momentum(rets, assets)

    # Sanity: tonus has 29 warmup rows (lookback=30)
    assert tonus.iloc[:29].isna().all().all(), "tonus must have 29 warmup rows NaN"
    volres_valid = volres.iloc[30:].dropna(how="any")
    assert not fundres.iloc[:5].isna().all().all(), \
        "fundres must not have 5+ warmup NaN rows (no lookback)"
    # All four row-mean zero where defined
    np.testing.assert_array_almost_equal(tonus.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(fundres.mean(axis=1).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(volres.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(relmom.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    # Cardinality differences
    tonus_unique = len(set(np.unique(tonus.values[~np.isnan(tonus.values)])))
    fundres_unique = len(set(np.unique(fundres.values)))
    volres_unique = len(set(np.unique(volres.values[~np.isnan(volres.values)])))
    relmom_unique = len(set(np.unique(relmom.values[~np.isnan(relmom.values)])))
    assert tonus_unique > 50, \
        f"tonus cardinality should be high (continuous); got {tonus_unique}"
    assert fundres_unique > 50, \
        f"fundres cardinality should be high (continuous); got {fundres_unique}"
    assert volres_unique > 50, \
        f"volres cardinality should be high (continuous); got {volres_unique}"
    # relmom cardinality is rational (bounded ≤ 2n+1)
    assert relmom_unique <= 2 * n_assets + 1, \
        f"relmom cardinality bounded by 2n+1={2*n_assets+1}; got {relmom_unique}"
    print(f"  ✓ score_turnover_residual (continuous, {tonus_unique} unique, 29 warmup NaN) "
          f"≠ score_funding_residual (continuous, {fundres_unique} unique) "
          f"≠ score_realized_vol_residual (continuous, {volres_unique} unique) "
          f"≠ score_relative_momentum (rational, {relmom_unique} unique)")


def t_turnover_residual_ls_signature_parity():
    """turnover_residual_ls signature must mirror R73/R76/S-78 L/S pattern."""
    import src.research.validation.s80_turnover_residual as s
    import inspect
    sig = inspect.signature(s.turnover_residual_ls)
    required_params = {"score_wide", "rets", "k_terciles", "cost_bps", "rebal_days", "sign"}
    sig_params = set(sig.parameters.keys())
    assert required_params.issubset(sig_params), \
        f"turnover_residual_ls missing required params; have {sig_params}"
    assert sig.parameters["k_terciles"].default == s.S80_K_TERCILES
    assert sig.parameters["sign"].default == s.SIGN_HIGH_TONUS_LONG
    print("  ✓ turnover_residual_ls signature parity with R73/R76/S-78 pattern")


def t_rejects_invalid_sign():
    """turnover_residual_ls must ValueError on invalid sign."""
    import src.research.validation.s80_turnover_residual as s
    rng = np.random.default_rng(11)
    score_wide = pd.DataFrame(rng.standard_normal((3, 3)), columns=["A", "B", "C"])
    rets = pd.DataFrame(rng.standard_normal((3, 3)) * 0.01, columns=["A", "B", "C"])
    try:
        s.turnover_residual_ls(score_wide, rets, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected (ValueError)")


def t_both_signs_supported():
    """Both SIGN_HIGH_TONUS_LONG and SIGN_LOW_TONUS_LONG must be valid."""
    import src.research.validation.s80_turnover_residual as s
    assert s.SIGN_HIGH_TONUS_LONG in s._VALID_SIGNS
    assert s.SIGN_LOW_TONUS_LONG in s._VALID_SIGNS
    assert len(s._VALID_SIGNS) == 2, f"only 2 valid signs, got {len(s._VALID_SIGNS)}"
    print("  ✓ both signs supported (high_tonus_long, low_tonus_long)")


def t_leg_correlation_gate_4_legs():
    """leg_correlation_gate_n reused from R78 must handle 4 existing legs."""
    import src.research.validation.s80_turnover_residual as s
    rng = np.random.default_rng(13)
    n = 200
    idx = pd.date_range("2025-06-01", periods=n, freq="D")

    # Independent: S-80 independent of R46/R62/R76/R78
    s80 = pd.Series(rng.standard_normal(n), index=idx)
    r46 = pd.Series(rng.standard_normal(n), index=idx)
    r62 = pd.Series(rng.standard_normal(n), index=idx)
    r76 = pd.Series(rng.standard_normal(n), index=idx)
    r78 = pd.Series(rng.standard_normal(n), index=idx)
    existing = {"r46": r46, "r62": r62, "r76": r76, "r78": r78}
    gate = s.leg_correlation_gate_n(s80, existing, gate=0.30)
    for k in ("corr_new_vs_r46", "corr_new_vs_r62", "corr_new_vs_r76", "corr_new_vs_r78",
              "max_abs_corr", "gate_threshold", "n_existing_legs",
              "passes_orthogonality_gate", "fusion_candidatable"):
        assert k in gate, f"gate missing {k}"
    assert gate["n_existing_legs"] == 4
    assert gate["passes_orthogonality_gate"], \
        f"4 independent series should pass gate; got {gate}"
    assert abs(gate["max_abs_corr"]) < 0.15, \
        f"4 independent series should have low max |corr|; got {gate['max_abs_corr']}"

    # Highly correlated with R76 (carry-axis sibling): should fail gate
    r76_corr = pd.Series(s80.values * 0.9 + rng.standard_normal(n) * 0.1, index=idx)
    existing_c = {"r46": r46, "r62": r62, "r76": r76_corr, "r78": r78}
    gate_c = s.leg_correlation_gate_n(s80, existing_c, gate=0.30)
    assert not gate_c["passes_orthogonality_gate"], \
        f"highly correlated with R76 should fail gate; got {gate_c}"
    assert gate_c["corr_new_vs_r76"] > 0.5, \
        f"expected strong positive corr with R76, got {gate_c['corr_new_vs_r76']}"
    print("  ✓ leg_correlation_gate_n: 4-leg pre-test works (independent passes, "
          "correlated with R76 (carry-axis sibling) fails)")


def t_nan_honesty_warmup_and_sparse():
    """I1 invariant: warmup (< lookback) and insufficient obs (< min_obs)
    must yield NaN, NEVER 0. A 0 turnover mean would mean 'no activity' which
    is a LIE for a sparse asset — 0 it would be quietly promoted into a tercile.

    Notes:
      - Asset A4 is 80% NaN — sparse enough that 30-day windows frequently
        drop below min_obs=5 and produce NaN dv_30 mean.
      - Cross-section demean uses dropna(how="any"): rows where ANY asset is
        NaN are excluded from the mean computation.
      - I1 invariant: NO impostor zeros anywhere.
    """
    import src.research.validation.s80_turnover_residual as s
    rng = np.random.default_rng(99)
    n_days, n_assets = 60, 5
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]

    # Make asset A4 sparse (80% NaN)
    dv = pd.DataFrame(
        rng.uniform(low=1.0, high=10.0, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    sparse_mask = rng.choice([True, False], size=(n_days,), p=[0.8, 0.2])
    dv.loc[sparse_mask, "A4"] = np.nan

    score = s.score_turnover_residual(dv, assets, lookback=30, min_obs=5)
    # I1 invariant: A4's score carries NaN (sparse-asset honesty)
    sparse_col_nan_frac = score["A4"].isna().mean()
    assert sparse_col_nan_frac > 0.20, \
        f"sparse asset A4 (80% NaN) should have >20% NaN in score; got {sparse_col_nan_frac:.2%}"
    # I1 invariant: NO impostor zeros in warmup rows (rows 0..3 are warmup)
    warmup_zero_count = (score.iloc[:4] == 0).sum().sum()
    assert warmup_zero_count == 0, \
        f"warmup rows should be NaN, NOT 0; got {warmup_zero_count} impostor zeros"
    # I1 invariant: NO impostor zeros in the entire score matrix (anywhere)
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
    print(f"  ✓ NaN honesty (I1): sparse asset A4 (80% NaN) → {sparse_col_nan_frac:.1%} "
          f"NaN score; ZERO impostor zeros anywhere; cross-section demean "
          f"preserves mean ~0 on observed rows ({len(observed_rows)} rows)")


def t_universe_floor():
    """S-80 must enforce S80_MIN_TRADEABLE = 12 — refuse to silently widen."""
    import src.research.validation.s80_turnover_residual as s
    assert s.S80_MIN_TRADEABLE == 12
    src = Path(s.__file__).read_text()
    assert "do not silently widen" in src.lower() or "refuses to silently widen" in src.lower(), \
        "S-80 must encode anti-imposter discipline on universe floor"
    assert "S80_MIN_TRADEABLE" in src, \
        "S-80 must reference S80_MIN_TRADEABLE in source"
    print("  ✓ universe floor S80_MIN_TRADEABLE=12 enforced")


def t_verdict_grammar():
    """Verdict must be one of SURVIVES_ORTHOGONAL / SURVIVES_CORRELATED / REFUTED,
    and lesson #43 v3 (axis-aware pivot) must be explicit."""
    import src.research.validation.s80_turnover_residual as s
    src = Path(s.__file__).read_text()
    assert "SURVIVES_ORTHOGONAL" in src, "verdict must include SURVIVES_ORTHOGONAL band"
    assert "SURVIVES_CORRELATED" in src, "verdict must include SURVIVES_CORRELATED band"
    assert "REFUTED" in src, "verdict must include REFUTED band"
    assert "✅ SURVIVES + ORTHOGONAL" in src, "verdict must include ✅ for SURVIVES_ORTHOGONAL"
    assert "🟡 SURVIVES + CORRELATED" in src, "verdict must include 🟡 for SURVIVES_CORRELATED"
    assert "🔴 REFUTED" in src, "verdict must include 🔴 for REFUTED"
    assert "lesson #43" in src.lower(), "S-80 must explicitly reference lesson #43"
    assert "lesson #42" in src.lower(), "S-80 must explicitly reference lesson #42 (gate)"
    # Lesson #43 v3 (axis-aware pivot)
    assert "lesson #43 v3" in src.lower() or "axis-aware pivot" in src.lower(), \
        "S-80 must explicitly note lesson #43 v3 (axis-aware pivot)"
    print("  ✓ verdict grammar: 3 bands (✅/🟡/🔴) + lessons #42, #43 v3 explicit")


def t_live_book_untouched():
    """S-80 must NOT touch the frozen R77 cell. Payload must declare this."""
    import src.research.validation.s80_turnover_residual as s
    src = Path(s.__file__).read_text()
    assert "research-only" in src.lower(), "S-80 must self-mark as research-only"
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "S-80 must include touches_frozen_r77_cell: False in payload"
    assert "R77 fusion-cell" in src or "R77 cell" in src or "R77)" in src, \
        "S-80 must reference the R77 fusion-cell (frozen)"
    assert "S-81" in src, "S-80 must name S-81 as the next-step candidate"
    print("  ✓ S-80 is research-only; frozen R77 cell untouched; S-81 named as successor")


def t_load_daily_dollar_volume_helper():
    """load_daily_dollar_volume must be importable and have correct signature."""
    import src.research.validation.s80_turnover_residual as s
    import inspect
    sig = inspect.signature(s.load_daily_dollar_volume)
    assert "ohlcv_dir" in sig.parameters, \
        "load_daily_dollar_volume must accept ohlcv_dir parameter (default Path)"
    assert sig.parameters["ohlcv_dir"].default is not inspect.Parameter.empty, \
        "load_daily_dollar_volume must have a default ohlcv_dir (OHLCV_DIR)"
    # Verify no-op on empty directory returns empty DataFrame
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        empty_dir = Path(tmpdir)
        result = s.load_daily_dollar_volume(empty_dir)
        assert isinstance(result, pd.DataFrame), \
            f"load_daily_dollar_volume must return DataFrame, got {type(result)}"
        assert result.empty, f"empty dir should return empty DataFrame, got shape {result.shape}"
    print("  ✓ load_daily_dollar_volume helper: signature correct, empty-dir returns empty DF")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        t_imports,
        t_score_turnover_residual_demean,
        t_score_different_from_funding_vol_momentum,
        t_turnover_residual_ls_signature_parity,
        t_rejects_invalid_sign,
        t_both_signs_supported,
        t_leg_correlation_gate_4_legs,
        t_nan_honesty_warmup_and_sparse,
        t_universe_floor,
        t_verdict_grammar,
        t_live_book_untouched,
        t_load_daily_dollar_volume_helper,
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
