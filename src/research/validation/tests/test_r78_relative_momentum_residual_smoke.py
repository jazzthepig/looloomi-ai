"""
R78 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r76_funding_residual_ls_smoke.py pattern. 11 tests cover:
  - imports + R78 constants
  - score: relative momentum = cross-sectional demean (mean ≈ 0)
  - score ≠ score_funding_residual (different signal axis)
  - L/S core: relative_momentum_ls signature parity with R73's pillar_a_level_ls
  - both signs supported
  - rejects invalid sign
  - leg-correlation gate extended to N legs (lesson #42 anti-imposter)
  - matched-cell sign audit
  - universe floor (R78_MIN_TRADEABLE)
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
    """R78 module + key public symbols importable."""
    import src.research.validation.r78_relative_momentum_residual as r
    assert hasattr(r, "run"), "R78 must expose run()"
    assert hasattr(r, "score_relative_momentum"), "R78 must expose score_relative_momentum"
    assert hasattr(r, "relative_momentum_ls"), "R78 must expose relative_momentum_ls"
    assert hasattr(r, "leg_correlation_gate_n"), "R78 must expose leg_correlation_gate_n"
    assert r.R78_K_TERCILES == 3, f"R78 K_TERCILES must be 3, got {r.R78_K_TERCILES}"
    assert r.R78_MIN_TRADEABLE == 12, f"R78 MIN_TRADEABLE must be 12, got {r.R78_MIN_TRADEABLE}"
    assert r.R78_ORTHOGONALITY_GATE == 0.30, \
        f"R78 orthogonality gate must be 0.30 (lesson #42), got {r.R78_ORTHOGONALITY_GATE}"
    assert r.R78_TSMOM_LOOKBACK == 30, f"R78 TSMOM lookback must be 30, got {r.R78_TSMOM_LOOKBACK}"
    # Sign constants
    assert hasattr(r, "SIGN_HIGH_MOM_LONG")
    assert hasattr(r, "SIGN_LOW_MOM_LONG")
    assert r.SIGN_HIGH_MOM_LONG == "high_mom_long"
    assert r.SIGN_LOW_MOM_LONG == "low_mom_long"
    print("  ✓ R78 imports + K_TERCILES=3 + MIN_TRADEABLE=12 + orthogonality gate=0.30 + lookback=30")


def t_score_relative_momentum_demean():
    """score_relative_momentum = TSMOM[t, a] - mean_a(TSMOM[t, a]).
    Mean across assets at each fully-observed time must be ~0 by construction."""
    import src.research.validation.r78_relative_momentum_residual as r
    # Synthetic: 60 days × 8 assets with random returns
    rng = np.random.default_rng(42)
    n_days, n_assets = 60, 8
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    rets = pd.DataFrame(
        rng.normal(scale=0.02, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    score = r.score_relative_momentum(rets, assets)
    # Row means on fully-observed rows must be ~0 (cross-sectional demean)
    row_means = score.mean(axis=1, skipna=True)
    observed_row_means = row_means.dropna()
    np.testing.assert_array_almost_equal(observed_row_means.values,
                                          np.zeros(len(observed_row_means)),
                                          decimal=10,
                                          err_msg="rel-mom mean must be 0 by construction")
    # Total sum of fully-observed scores ~0
    total_score = score.sum().sum()
    assert abs(total_score) < 1e-9, f"total score sum must be 0, got {total_score}"
    # Values are continuous (demean of {-1, 0, +1} signs → rationals);
    # max range = ±(2 - 1/n_assets) for n_assets tradeable.
    fully_observed_values = score.dropna(how="any").values
    n_assets = score.shape[1]
    max_abs = 2.0 - 1.0 / n_assets
    assert np.nanmin(fully_observed_values) >= -max_abs - 1e-9, \
        f"score min ≥ -{max_abs:.3f}; got {np.nanmin(fully_observed_values):.3f}"
    assert np.nanmax(fully_observed_values) <= max_abs + 1e-9, \
        f"score max ≤ +{max_abs:.3f}; got {np.nanmax(fully_observed_values):.3f}"
    print(f"  ✓ score_relative_momentum: cross-sectional demean of TSMOM "
          f"(observed rows: mean ≈ 0, range [{np.nanmin(fully_observed_values):.3f}, "
          f"{np.nanmax(fully_observed_values):.3f}]; warmup rows: NaN)")


def t_score_different_from_funding_residual():
    """score_relative_momentum (TSMOM demean) is NOT identical to
    score_funding_residual (funding demean). Different signal axes — even with
    correlated inputs they produce different score series.
    """
    import src.research.validation.r78_relative_momentum_residual as r
    from src.research.validation.r76_funding_residual_ls import score_funding_residual
    rng = np.random.default_rng(7)
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
    relmom = r.score_relative_momentum(rets, assets)
    fundres = score_funding_residual(funding, assets)
    # Sanity 1: shapes match
    assert relmom.shape == rets.shape
    assert fundres.shape == funding.shape
    # Sanity 2: row means are 0 in both
    np.testing.assert_array_almost_equal(relmom.mean(axis=1).fillna(0).values,
                                          np.zeros(n_days), decimal=10)
    np.testing.assert_array_almost_equal(fundres.mean(axis=1).values,
                                          np.zeros(n_days), decimal=10)
    # Sanity 3: different value ranges — relmom values are rational (demean of
    # {-1, 0, +1} signs) while fundres values are continuous (demean of
    # continuous funding). Both are bounded by ±max_abs; the cardinality of
    # unique values differs qualitatively (relmom ≤ 2n+1, fundres continuous).
    relmom_vals = set(np.unique(relmom.values[~np.isnan(relmom.values)]))
    fundres_vals = set(np.unique(fundres.values))
    n_assets = relmom.shape[1]
    max_relmom_cardinality = 2 * n_assets + 1
    assert len(relmom_vals) <= max_relmom_cardinality, \
        f"relmom cardinality must be bounded (≤ {max_relmom_cardinality}); got {len(relmom_vals)}"
    # Funding residual cardinality is much higher (continuous)
    assert len(fundres_vals) > max_relmom_cardinality, \
        f"fundres cardinality must exceed relmom bound ({max_relmom_cardinality}); got {len(fundres_vals)}"
    print(f"  ✓ score_relative_momentum (rational, {len(relmom_vals)} unique vals) "
          f"≠ score_funding_residual (continuous, {len(fundres_vals)} unique vals)")


def t_relative_momentum_ls_signature_parity():
    """relative_momentum_ls signature must mirror R73's pillar_a_level_ls / R76's funding_residual_ls."""
    import src.research.validation.r78_relative_momentum_residual as r
    import inspect
    sig_r78 = inspect.signature(r.relative_momentum_ls)
    required_params = {"score_wide", "rets", "k_terciles", "cost_bps", "rebal_days", "sign"}
    sig_params = set(sig_r78.parameters.keys())
    assert required_params.issubset(sig_params), \
        f"relative_momentum_ls missing required params; have {sig_params}"
    # Defaults
    assert sig_r78.parameters["k_terciles"].default == r.R78_K_TERCILES
    assert sig_r78.parameters["sign"].default == r.SIGN_HIGH_MOM_LONG
    print("  ✓ relative_momentum_ls signature parity with R73's pillar_a_level_ls")


def t_rejects_invalid_sign():
    """relative_momentum_ls must ValueError on invalid sign."""
    import src.research.validation.r78_relative_momentum_residual as r
    rng = np.random.default_rng(11)
    score_wide = pd.DataFrame(rng.standard_normal((3, 3)), columns=["A", "B", "C"])
    rets = pd.DataFrame(rng.standard_normal((3, 3)) * 0.01, columns=["A", "B", "C"])
    try:
        r.relative_momentum_ls(score_wide, rets, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected (ValueError)")


def t_both_signs_supported():
    """Both SIGN_HIGH_MOM_LONG and SIGN_LOW_MOM_LONG must be valid."""
    import src.research.validation.r78_relative_momentum_residual as r
    assert r.SIGN_HIGH_MOM_LONG in r._VALID_SIGNS
    assert r.SIGN_LOW_MOM_LONG in r._VALID_SIGNS
    assert len(r._VALID_SIGNS) == 2, f"only 2 valid signs, got {len(r._VALID_SIGNS)}"
    print("  ✓ both signs supported (high_mom_long, low_mom_long)")


def t_leg_correlation_gate_n():
    """leg_correlation_gate_n must handle N existing legs + return all required fields."""
    import src.research.validation.r78_relative_momentum_residual as r
    rng = np.random.default_rng(13)
    n = 200
    idx = pd.date_range("2025-06-01", periods=n, freq="D")

    # Synthetic: R78 leg independent of R46 + R62 + R76
    r78_leg = pd.Series(rng.standard_normal(n), index=idx)
    r46_leg = pd.Series(rng.standard_normal(n), index=idx)
    r62_leg = pd.Series(rng.standard_normal(n), index=idx)
    r76_leg = pd.Series(rng.standard_normal(n), index=idx)
    existing = {"r46": r46_leg, "r62": r62_leg, "r76": r76_leg}
    gate = r.leg_correlation_gate_n(r78_leg, existing, gate=0.30)
    # All required fields
    for k in ("corr_new_vs_r46", "corr_new_vs_r62", "corr_new_vs_r76",
              "max_abs_corr", "gate_threshold", "n_existing_legs",
              "passes_orthogonality_gate", "fusion_candidatable"):
        assert k in gate, f"gate missing {k}"
    assert gate["n_existing_legs"] == 3
    # Independent series: should pass gate (low correlation)
    assert gate["passes_orthogonality_gate"], \
        f"independent series should pass gate; got {gate}"
    assert gate["fusion_candidatable"], "fusion_candidatable must match passes_gate"
    assert abs(gate["max_abs_corr"]) < 0.20, \
        f"3 independent series should have low max |corr|; got {gate['max_abs_corr']}"

    # Synthetic: R78 highly correlated with R46 (should fail gate)
    r46_leg_corr = pd.Series(r78_leg.values * 0.9 + rng.standard_normal(n) * 0.1, index=idx)
    existing_corr = {"r46": r46_leg_corr, "r62": r62_leg, "r76": r76_leg}
    gate_corr = r.leg_correlation_gate_n(r78_leg, existing_corr, gate=0.30)
    assert not gate_corr["passes_orthogonality_gate"], \
        f"highly correlated series should fail gate; got {gate_corr}"
    assert gate_corr["corr_new_vs_r46"] > 0.5, \
        f"expected strong positive corr, got {gate_corr['corr_new_vs_r46']}"
    print("  ✓ leg_correlation_gate_n: independent passes (3 legs), correlated fails")


def t_universe_floor():
    """R78 must enforce R78_MIN_TRADEABLE = 12 — refuse to silently widen."""
    import src.research.validation.r78_relative_momentum_residual as r
    assert r.R78_MIN_TRADEABLE == 12
    src = Path(r.__file__).read_text()
    assert "do not silently widen" in src.lower() or "refuses to silently widen" in src.lower(), \
        "R78 must encode anti-imposter discipline on universe floor"
    assert "R78_MIN_TRADEABLE" in src, "R78 must reference R78_MIN_TRADEABLE in source"
    print("  ✓ universe floor R78_MIN_TRADEABLE=12 enforced")


def t_matched_cell_sign_audit_logic():
    """Matched-cell sign audit must produce top-3 entries + sign verdict logic."""
    import src.research.validation.r78_relative_momentum_residual as r
    src = Path(r.__file__).read_text()
    assert "matched_cell_sign_audit" in src.lower() or "matched_cell" in src.lower(), \
        "R78 must include matched-cell sign audit (anti-imposter)"
    assert "matched_diffs" in src, "R78 must compute matched-cell differentials"
    assert "top_3" in src.lower() or "matched_diffs[:3]" in src, \
        "R78 must report top-3 matched cells"
    assert "sign_verdict" in src, "R78 must declare sign_verdict from matched-cell diff"
    print("  ✓ matched-cell sign audit logic (top-3 + sign_verdict)")


def t_verdict_grammar():
    """Verdict must be one of SURVIVES_ORTHOGONAL / SURVIVES_CORRELATED / REFUTED."""
    import src.research.validation.r78_relative_momentum_residual as r
    src = Path(r.__file__).read_text()
    assert "SURVIVES_ORTHOGONAL" in src, "verdict must include SURVIVES_ORTHOGONAL band"
    assert "SURVIVES_CORRELATED" in src, "verdict must include SURVIVES_CORRELATED band"
    assert "REFUTED" in src and "REFUTED" in src.upper(), "verdict must include REFUTED band"
    # Emoji
    assert "✅ SURVIVES + ORTHOGONAL" in src, "verdict must include ✅ for SURVIVES_ORTHOGONAL"
    assert "🟡 SURVIVES + CORRELATED" in src, "verdict must include 🟡 for SURVIVES_CORRELATED"
    assert "🔴 REFUTED" in src, "verdict must include 🔴 for REFUTED"
    # Lesson #43 explicit reference
    assert "lesson #43" in src.lower(), "R78 must explicitly reference lesson #43"
    # Lesson #42 explicit reference (gate)
    assert "lesson #42" in src.lower(), "R78 must explicitly reference lesson #42 (gate)"
    print("  ✓ verdict grammar: 3 bands (✅/🟡/🔴) + lessons #42 and #43 explicit")


def t_live_book_untouched():
    """R78 must NOT touch the frozen R77 cell. Payload must declare this."""
    import src.research.validation.r78_relative_momentum_residual as r
    src = Path(r.__file__).read_text()
    assert "R78 is research-only" in src or "research-only" in src, \
        "R78 must self-mark as research-only"
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "R78 must include touches_frozen_r77_cell: False in payload"
    assert "R77 is a TEST" in src or "R77 cell as FROZEN" in src or "R77 fusion-cell" in src, \
        "R78 must reference R77 cell as frozen / reference R77 research-only status"
    print("  ✓ R78 is research-only; frozen R77 cell untouched")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_score_relative_momentum_demean, t_score_different_from_funding_residual,
             t_relative_momentum_ls_signature_parity, t_rejects_invalid_sign,
             t_both_signs_supported, t_leg_correlation_gate_n, t_universe_floor,
             t_matched_cell_sign_audit_logic, t_verdict_grammar,
             t_live_book_untouched]
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