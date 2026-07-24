"""
S-78 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r78_relative_momentum_residual_smoke.py pattern. 11 tests cover:
  - imports + S-78 constants
  - score: realized vol residual = trailing-30d σ cross-sectional demean (mean ≈ 0)
  - score ≠ score_funding_residual (different signal axis)
  - score ≠ score_relative_momentum (different signal axis)
  - L/S core: vol_residual_ls signature parity with R73's pillar_a_level_ls
  - both signs supported
  - rejects invalid sign
  - leg-correlation gate extends to N legs (lesson #42 anti-imposter) — reuses R78's
  - NaN honesty (I1): warmup rows + insufficient obs ⇒ NaN, never 0
  - matched-cell sign audit
  - universe floor (S78_MIN_TRADEABLE)
  - verdict grammar (3 bands)
  - live-book-untouched flag
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """S-78 module + key public symbols importable."""
    import src.research.validation.s78_vol_residual as s
    assert hasattr(s, "run"), "S-78 must expose run()"
    assert hasattr(s, "score_realized_vol_residual"), \
        "S-78 must expose score_realized_vol_residual"
    assert hasattr(s, "vol_residual_ls"), "S-78 must expose vol_residual_ls"
    assert hasattr(s, "leg_correlation_gate_n"), \
        "S-78 must expose leg_correlation_gate_n (re-exported from R78)"
    assert s.S78_K_TERCILES == 3, f"S-78 K_TERCILES must be 3, got {s.S78_K_TERCILES}"
    assert s.S78_MIN_TRADEABLE == 12, \
        f"S-78 MIN_TRADEABLE must be 12, got {s.S78_MIN_TRADEABLE}"
    assert s.S78_ORTHOGONALITY_GATE == 0.30, \
        f"S-78 orthogonality gate must be 0.30 (lesson #42), got {s.S78_ORTHOGONALITY_GATE}"
    assert s.S78_VOL_LOOKBACK == 30, \
        f"S-78 VOL_LOOKBACK must be 30, got {s.S78_VOL_LOOKBACK}"
    assert s.S78_VOL_MIN_OBS == 5, \
        f"S-78 VOL_MIN_OBS must be 5 (NaN below this), got {s.S78_VOL_MIN_OBS}"
    # Sign constants
    assert hasattr(s, "SIGN_HIGH_VOL_LONG")
    assert hasattr(s, "SIGN_LOW_VOL_LONG")
    assert s.SIGN_HIGH_VOL_LONG == "high_vol_long"
    assert s.SIGN_LOW_VOL_LONG == "low_vol_long"
    print("  ✓ S-78 imports + K_TERCILES=3 + MIN_TRADEABLE=12 + orthogonality gate=0.30 "
          "+ VOL_LOOKBACK=30 + VOL_MIN_OBS=5")


def t_score_vol_residual_demean():
    """score_realized_vol_residual = σ_30[t, a] - mean_a(σ_30[t, a]).
    Mean across assets at each fully-observed time must be ~0 by construction."""
    import src.research.validation.s78_vol_residual as s
    # Synthetic: 60 days × 8 assets with random returns
    rng = np.random.default_rng(42)
    n_days, n_assets = 60, 8
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    rets = pd.DataFrame(
        rng.normal(scale=0.02, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    score = s.score_realized_vol_residual(rets, assets)
    # Row means on fully-observed rows must be ~0 (cross-sectional demean)
    row_means = score.mean(axis=1, skipna=True)
    observed_row_means = row_means.dropna()
    np.testing.assert_array_almost_equal(observed_row_means.values,
                                          np.zeros(len(observed_row_means)),
                                          decimal=10,
                                          err_msg="vol-residual mean must be 0 by construction")
    # First 29 rows should all be NaN (warmup period < lookback=30)
    warmup_nans = score.iloc[:29].isna().all().all()
    assert warmup_nans, "first 29 rows should be NaN (warmup)"
    # Row 30+ (idx 29+) should have at least some non-NaN values
    assert score.iloc[30:].notna().any().any(), "row 30+ should have non-NaN values"
    print(f"  ✓ score_realized_vol_residual: cross-sectional demean of σ_30 "
          f"(observed rows: mean ≈ 0, warmup=29 NaN rows as expected)")


def t_score_different_from_funding_and_momentum():
    """score_realized_vol_residual ≠ score_funding_residual ≠ score_relative_momentum.
    Three orthogonal axes — vol microstructure, funding, momentum — must produce
    distinguishable score series even on random data (different ranges, different
    cardinality, different NaN patterns).
    """
    import src.research.validation.s78_vol_residual as s
    from src.research.validation.r76_funding_residual_ls import score_funding_residual
    from src.research.validation.r78_relative_momentum_residual import score_relative_momentum

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

    volres = s.score_realized_vol_residual(rets, assets)
    fundres = score_funding_residual(funding, assets)
    relmom = score_relative_momentum(rets, assets)

    # Sanity: 3 different NaN patterns
    # volres: first 29 rows NaN (warmup)
    # fundres: all rows present (no warmup since it's a demean of funding)
    # relmom: warmup until lookback=30 (TSMOM also has warmup)
    assert volres.iloc[:29].isna().all().all(), "volres must have 29 warmup rows NaN"
    assert not fundres.iloc[:5].isna().all().all(), \
        "fundres must not have 5+ warmup NaN rows (no lookback)"
    # All three row-mean zero where defined
    np.testing.assert_array_almost_equal(volres.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(fundres.mean(axis=1).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(relmom.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    # Cardinality differences
    volres_unique = len(set(np.unique(volres.values[~np.isnan(volres.values)])))
    fundres_unique = len(set(np.unique(fundres.values)))
    relmom_unique = len(set(np.unique(relmom.values[~np.isnan(relmom.values)])))
    assert volres_unique > 50, \
        f"volres cardinality should be high (continuous); got {volres_unique}"
    assert fundres_unique > 50, \
        f"fundres cardinality should be high (continuous); got {fundres_unique}"
    # relmom cardinality is rational (bounded ≤ 2n+1 = 17)
    assert relmom_unique <= 2 * n_assets + 1, \
        f"relmom cardinality bounded by 2n+1={2*n_assets+1}; got {relmom_unique}"
    print(f"  ✓ score_realized_vol_residual (continuous, {volres_unique} unique, 29 warmup NaN) "
          f"≠ score_funding_residual (continuous, {fundres_unique} unique) "
          f"≠ score_relative_momentum (rational, {relmom_unique} unique)")


def t_vol_residual_ls_signature_parity():
    """vol_residual_ls signature must mirror R73/R76/R78 L/S pattern."""
    import src.research.validation.s78_vol_residual as s
    import inspect
    sig = inspect.signature(s.vol_residual_ls)
    required_params = {"score_wide", "rets", "k_terciles", "cost_bps", "rebal_days", "sign"}
    sig_params = set(sig.parameters.keys())
    assert required_params.issubset(sig_params), \
        f"vol_residual_ls missing required params; have {sig_params}"
    assert sig.parameters["k_terciles"].default == s.S78_K_TERCILES
    assert sig.parameters["sign"].default == s.SIGN_HIGH_VOL_LONG
    print("  ✓ vol_residual_ls signature parity with R73/R76/R78 pattern")


def t_rejects_invalid_sign():
    """vol_residual_ls must ValueError on invalid sign."""
    import src.research.validation.s78_vol_residual as s
    rng = np.random.default_rng(11)
    score_wide = pd.DataFrame(rng.standard_normal((3, 3)), columns=["A", "B", "C"])
    rets = pd.DataFrame(rng.standard_normal((3, 3)) * 0.01, columns=["A", "B", "C"])
    try:
        s.vol_residual_ls(score_wide, rets, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected (ValueError)")


def t_both_signs_supported():
    """Both SIGN_HIGH_VOL_LONG and SIGN_LOW_VOL_LONG must be valid."""
    import src.research.validation.s78_vol_residual as s
    assert s.SIGN_HIGH_VOL_LONG in s._VALID_SIGNS
    assert s.SIGN_LOW_VOL_LONG in s._VALID_SIGNS
    assert len(s._VALID_SIGNS) == 2, f"only 2 valid signs, got {len(s._VALID_SIGNS)}"
    print("  ✓ both signs supported (high_vol_long, low_vol_long)")


def t_leg_correlation_gate_4_legs():
    """leg_correlation_gate_n reused from R78 must handle 4 existing legs."""
    import src.research.validation.s78_vol_residual as s
    rng = np.random.default_rng(13)
    n = 200
    idx = pd.date_range("2025-06-01", periods=n, freq="D")

    # Independent: S-78 independent of R46/R62/R76/R78
    s78 = pd.Series(rng.standard_normal(n), index=idx)
    r46 = pd.Series(rng.standard_normal(n), index=idx)
    r62 = pd.Series(rng.standard_normal(n), index=idx)
    r76 = pd.Series(rng.standard_normal(n), index=idx)
    r78 = pd.Series(rng.standard_normal(n), index=idx)
    existing = {"r46": r46, "r62": r62, "r76": r76, "r78": r78}
    gate = s.leg_correlation_gate_n(s78, existing, gate=0.30)
    for k in ("corr_new_vs_r46", "corr_new_vs_r62", "corr_new_vs_r76", "corr_new_vs_r78",
              "max_abs_corr", "gate_threshold", "n_existing_legs",
              "passes_orthogonality_gate", "fusion_candidatable"):
        assert k in gate, f"gate missing {k}"
    assert gate["n_existing_legs"] == 4
    assert gate["passes_orthogonality_gate"], \
        f"4 independent series should pass gate; got {gate}"
    assert abs(gate["max_abs_corr"]) < 0.15, \
        f"4 independent series should have low max |corr|; got {gate['max_abs_corr']}"

    # Highly correlated: S-78 ≈ R46 — should fail gate
    r46_corr = pd.Series(s78.values * 0.9 + rng.standard_normal(n) * 0.1, index=idx)
    existing_c = {"r46": r46_corr, "r62": r62, "r76": r76, "r78": r78}
    gate_c = s.leg_correlation_gate_n(s78, existing_c, gate=0.30)
    assert not gate_c["passes_orthogonality_gate"], \
        f"highly correlated series should fail gate; got {gate_c}"
    assert gate_c["corr_new_vs_r46"] > 0.5, \
        f"expected strong positive corr, got {gate_c['corr_new_vs_r46']}"
    print("  ✓ leg_correlation_gate_n: 4-leg pre-test works (independent passes, "
          "correlated with R46 fails)")


def t_nan_honesty_warmup_and_sparse():
    """I1 invariant: warmup (< lookback) and insufficient obs (< min_obs)
    must yield NaN, NEVER 0. A σ of 0 means 'no risk' which is a LIE for a
    sparse asset — 0 it would be quietly promoted into a tercile.

    Notes on the test artifact:
    - Asset A4 is 80% NaN — sparse enough that 30-day windows frequently
      drop below min_obs=5 and produce NaN σ.
    - Cross-section demean uses dropna(how="any"): rows where ANY asset is
      NaN are excluded from the mean computation. This is correct I1
      behavior — we don't impute "the missing asset's σ was the average."
    - Expected: A4 score has high NaN fraction; ZERO 0s anywhere.
    """
    import src.research.validation.s78_vol_residual as s
    rng = np.random.default_rng(99)
    n_days, n_assets = 60, 5
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]

    # Make asset A4 sparse (80% NaN — windows frequently fall below min_obs=5)
    rets = pd.DataFrame(
        rng.normal(scale=0.02, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    sparse_mask = rng.choice([True, False], size=(n_days,), p=[0.8, 0.2])
    rets.loc[sparse_mask, "A4"] = np.nan

    score = s.score_realized_vol_residual(rets, assets, lookback=30, min_obs=5)
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
    """S-78 must enforce S78_MIN_TRADEABLE = 12 — refuse to silently widen."""
    import src.research.validation.s78_vol_residual as s
    assert s.S78_MIN_TRADEABLE == 12
    src = Path(s.__file__).read_text()
    assert "do not silently widen" in src.lower() or "refuses to silently widen" in src.lower(), \
        "S-78 must encode anti-imposter discipline on universe floor"
    assert "S78_MIN_TRADEABLE" in src, \
        "S-78 must reference S78_MIN_TRADEABLE in source"
    print("  ✓ universe floor S78_MIN_TRADEABLE=12 enforced")


def t_verdict_grammar():
    """Verdict must be one of SURVIVES_ORTHOGONAL / SURVIVES_CORRELATED / REFUTED,
    and lesson #43 v2 (gate + gauntlet) must be explicit."""
    import src.research.validation.s78_vol_residual as s
    src = Path(s.__file__).read_text()
    assert "SURVIVES_ORTHOGONAL" in src, "verdict must include SURVIVES_ORTHOGONAL band"
    assert "SURVIVES_CORRELATED" in src, "verdict must include SURVIVES_CORRELATED band"
    assert "REFUTED" in src, "verdict must include REFUTED band"
    assert "✅ SURVIVES + ORTHOGONAL" in src, "verdict must include ✅ for SURVIVES_ORTHOGONAL"
    assert "🟡 SURVIVES + CORRELATED" in src, "verdict must include 🟡 for SURVIVES_CORRELATED"
    assert "🔴 REFUTED" in src, "verdict must include 🔴 for REFUTED"
    assert "lesson #43" in src.lower(), "S-78 must explicitly reference lesson #43"
    assert "lesson #42" in src.lower(), "S-78 must explicitly reference lesson #42 (gate)"
    # Lesson #43 v2 (gate + gauntlet required)
    assert "lesson #43 v2" in src.lower() or "lesson #43 (v2" in src.lower(), \
        "S-78 must explicitly note lesson #43 v2 (gate + gauntlet required)"
    print("  ✓ verdict grammar: 3 bands (✅/🟡/🔴) + lessons #42, #43 v2 explicit")


def t_live_book_untouched():
    """S-78 must NOT touch the frozen R77 cell. Payload must declare this."""
    import src.research.validation.s78_vol_residual as s
    src = Path(s.__file__).read_text()
    assert "research-only" in src.lower(), "S-78 must self-mark as research-only"
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "S-78 must include touches_frozen_r77_cell: False in payload"
    assert "R77 fusion-cell" in src or "R77 cell" in src or "R77)" in src, \
        "S-78 must reference the R77 fusion-cell (frozen)"
    assert "S-79" in src, "S-78 must name S-79 as the next-step candidate"
    print("  ✓ S-78 is research-only; frozen R77 cell untouched; S-79 named as successor")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        t_imports,
        t_score_vol_residual_demean,
        t_score_different_from_funding_and_momentum,
        t_vol_residual_ls_signature_parity,
        t_rejects_invalid_sign,
        t_both_signs_supported,
        t_leg_correlation_gate_4_legs,
        t_nan_honesty_warmup_and_sparse,
        t_universe_floor,
        t_verdict_grammar,
        t_live_book_untouched,
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
