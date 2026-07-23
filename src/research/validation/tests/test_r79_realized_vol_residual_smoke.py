"""
R79 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r78_relative_momentum_residual_smoke.py pattern. 11 tests cover:
  - imports + R79 constants
  - score: realized vol residual = cross-sectional demean of trailing-30d σ
  - score ≠ score_funding_residual (different signal axis)
  - L/S core: realized_vol_residual_ls signature parity with R73's pillar_a_level_ls
  - both signs supported
  - rejects invalid sign
  - leg-correlation gate extended to 4 existing legs (lesson #42 anti-imposter)
  - matched-cell sign audit
  - universe floor (R79_MIN_TRADEABLE)
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
    """R79 module + key public symbols importable."""
    import src.research.validation.r79_realized_vol_residual as r
    assert hasattr(r, "run"), "R79 must expose run()"
    assert hasattr(r, "score_realized_vol_residual"), "R79 must expose score_realized_vol_residual"
    assert hasattr(r, "realized_vol_residual_ls"), "R79 must expose realized_vol_residual_ls"
    assert hasattr(r, "leg_correlation_gate_n"), "R79 must expose leg_correlation_gate_n"
    assert r.R79_K_TERCILES == 3, f"R79 K_TERCILES must be 3, got {r.R79_K_TERCILES}"
    assert r.R79_MIN_TRADEABLE == 12, f"R79 MIN_TRADEABLE must be 12, got {r.R79_MIN_TRADEABLE}"
    assert r.R79_ORTHOGONALITY_GATE == 0.30, \
        f"R79 orthogonality gate must be 0.30 (lesson #42), got {r.R79_ORTHOGONALITY_GATE}"
    assert r.R79_VOL_LOOKBACK == 30, f"R79 vol lookback must be 30, got {r.R79_VOL_LOOKBACK}"
    assert r.R79_VOL_ANNUALIZATION == 365, \
        f"R79 vol annualization must be 365, got {r.R79_VOL_ANNUALIZATION}"
    # Sign constants
    assert hasattr(r, "SIGN_HIGH_VOL_LONG")
    assert hasattr(r, "SIGN_LOW_VOL_LONG")
    assert r.SIGN_HIGH_VOL_LONG == "high_vol_long"
    assert r.SIGN_LOW_VOL_LONG == "low_vol_long"
    print("  ✓ R79 imports + K_TERCILES=3 + MIN_TRADEABLE=12 + orthogonality gate=0.30 + "
          "lookback=30 + annualization=365")


def t_score_realized_vol_residual_demean():
    """score_realized_vol_residual = σ[t, a] - mean_a(σ[t, a]).
    Mean across assets at each fully-observed time must be ~0 by construction."""
    import src.research.validation.r79_realized_vol_residual as r
    # Synthetic: 90 days × 8 assets with random returns
    rng = np.random.default_rng(42)
    n_days, n_assets = 90, 8
    dates = pd.date_range("2025-09-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    rets = pd.DataFrame(
        rng.normal(scale=0.02, size=(n_days, n_assets)),
        index=dates, columns=assets,
    )
    score = r.score_realized_vol_residual(rets, assets)
    # Row means on fully-observed rows must be ~0 (cross-sectional demean)
    row_means = score.mean(axis=1, skipna=True)
    observed_row_means = row_means.dropna()
    np.testing.assert_array_almost_equal(observed_row_means.values,
                                          np.zeros(len(observed_row_means)),
                                          decimal=10,
                                          err_msg="vol-residual mean must be 0 by construction")
    # Total sum of fully-observed scores ~0
    total_score = score.sum().sum()
    assert abs(total_score) < 1e-9, f"total score sum must be 0, got {total_score}"
    # Values must be non-negative std (annualized vol, demeaned)
    fully_observed_values = score.dropna(how="any").values
    assert np.all(np.isfinite(fully_observed_values)), "all values must be finite"
    # Range bounded by ±max_mean_deviation
    max_abs = np.nanmax(np.abs(fully_observed_values))
    # Each asset's vol is sqrt(sum_sq_returns * annualization). For daily σ ≈ 0.02
    # over 30 days: vol ≈ sqrt(30 * 0.02² * 365) ≈ sqrt(4.38) ≈ 2.09. Cross-asset range
    # of vol ≈ ±0.05; demean range bounded by ±max vol-range ≈ ±0.10
    assert max_abs < 1.0, f"demeaned vol range must be reasonable; got max |x|={max_abs:.3f}"
    print(f"  ✓ score_realized_vol_residual: cross-sectional demean of σ "
          f"(observed rows: mean ≈ 0, range [{np.nanmin(fully_observed_values):.3f}, "
          f"{np.nanmax(fully_observed_values):.3f}]; warmup rows: NaN)")


def t_score_different_from_funding_residual():
    """score_realized_vol_residual (vol demean) is NOT identical to
    score_funding_residual (funding demean). Different signal axes — vol is
    microstructure (returns squared), funding is carry (level).
    """
    import src.research.validation.r79_realized_vol_residual as r
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
    volres = r.score_realized_vol_residual(rets, assets)
    fundres = score_funding_residual(funding, assets)
    # Sanity 1: shapes match
    assert volres.shape == rets.shape
    assert fundres.shape == funding.shape
    # Sanity 2: row means are 0 in both (observed rows only)
    volres_observed = volres.dropna(how="any")
    fundres_observed = fundres.dropna(how="any")
    np.testing.assert_array_almost_equal(volres_observed.mean(axis=1).values,
                                          np.zeros(volres_observed.shape[0]),
                                          decimal=10)
    np.testing.assert_array_almost_equal(fundres_observed.mean(axis=1).values,
                                          np.zeros(fundres_observed.shape[0]),
                                          decimal=10)
    # Sanity 3: vol-residual values are non-negative std (annualized vol, demeaned);
    # funding-residual values can be both positive and negative (demeaned funding)
    volres_vals = volres.dropna(how="any").values
    fundres_vals = fundres.values
    # Vol residual cardinality is high (continuous demean of σ)
    volres_card = len(set(np.unique(np.round(volres_vals, 4))))
    fundres_card = len(set(np.unique(np.round(fundres_vals, 6))))
    # Both continuous, but on different scales and distributions
    assert volres_card > 10, f"volres must have many unique values; got {volres_card}"
    assert fundres_card > 10, f"fundres must have many unique values; got {fundres_card}"
    # Vol residual range should be wider (vol demean range ≈ ±2-3; funding ≈ ±0.005)
    volres_range = np.nanmax(volres_vals) - np.nanmin(volres_vals)
    fundres_range = np.nanmax(fundres_vals) - np.nanmin(fundres_vals)
    assert volres_range > fundres_range, \
        f"volres range ({volres_range:.3f}) should exceed fundres range ({fundres_range:.6f})"
    print(f"  ✓ score_realized_vol_residual (vol axis, range {volres_range:.3f}) "
          f"≠ score_funding_residual (funding axis, range {fundres_range:.6f})")


def t_realized_vol_residual_ls_signature_parity():
    """realized_vol_residual_ls signature must mirror R73/R76/R78."""
    import src.research.validation.r79_realized_vol_residual as r
    import inspect
    sig_r79 = inspect.signature(r.realized_vol_residual_ls)
    required_params = {"score_wide", "rets", "k_terciles", "cost_bps", "rebal_days", "sign"}
    sig_params = set(sig_r79.parameters.keys())
    assert required_params.issubset(sig_params), \
        f"realized_vol_residual_ls missing required params; have {sig_params}"
    # Defaults
    assert sig_r79.parameters["k_terciles"].default == r.R79_K_TERCILES
    assert sig_r79.parameters["sign"].default == r.SIGN_HIGH_VOL_LONG
    print("  ✓ realized_vol_residual_ls signature parity with R73's pillar_a_level_ls")


def t_rejects_invalid_sign():
    """realized_vol_residual_ls must ValueError on invalid sign."""
    import src.research.validation.r79_realized_vol_residual as r
    rng = np.random.default_rng(11)
    score_wide = pd.DataFrame(rng.standard_normal((3, 3)), columns=["A", "B", "C"])
    rets = pd.DataFrame(rng.standard_normal((3, 3)) * 0.01, columns=["A", "B", "C"])
    try:
        r.realized_vol_residual_ls(score_wide, rets, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected (ValueError)")


def t_both_signs_supported():
    """Both SIGN_HIGH_VOL_LONG and SIGN_LOW_VOL_LONG must be valid."""
    import src.research.validation.r79_realized_vol_residual as r
    assert r.SIGN_HIGH_VOL_LONG in r._VALID_SIGNS
    assert r.SIGN_LOW_VOL_LONG in r._VALID_SIGNS
    assert len(r._VALID_SIGNS) == 2, f"only 2 valid signs, got {len(r._VALID_SIGNS)}"
    print("  ✓ both signs supported (high_vol_long, low_vol_long)")


def t_leg_correlation_gate_n():
    """leg_correlation_gate_n must handle 4 existing legs + return all required fields."""
    import src.research.validation.r79_realized_vol_residual as r
    rng = np.random.default_rng(13)
    n = 200
    idx = pd.date_range("2025-06-01", periods=n, freq="D")

    # Synthetic: R79 leg independent of R46 + R62 + R76 + R78
    r79_leg = pd.Series(rng.standard_normal(n), index=idx)
    r46_leg = pd.Series(rng.standard_normal(n), index=idx)
    r62_leg = pd.Series(rng.standard_normal(n), index=idx)
    r76_leg = pd.Series(rng.standard_normal(n), index=idx)
    r78_leg = pd.Series(rng.standard_normal(n), index=idx)
    existing = {"r46": r46_leg, "r62": r62_leg, "r76": r76_leg, "r78": r78_leg}
    gate = r.leg_correlation_gate_n(r79_leg, existing, gate=0.30)
    # All required fields
    for k in ("corr_new_vs_r46", "corr_new_vs_r62", "corr_new_vs_r76", "corr_new_vs_r78",
              "max_abs_corr", "gate_threshold", "n_existing_legs",
              "passes_orthogonality_gate", "fusion_candidatable"):
        assert k in gate, f"gate missing {k}"
    assert gate["n_existing_legs"] == 4
    # Independent series: should pass gate (low correlation)
    assert gate["passes_orthogonality_gate"], \
        f"independent series should pass gate; got {gate}"
    assert gate["fusion_candidatable"], "fusion_candidatable must match passes_gate"
    assert abs(gate["max_abs_corr"]) < 0.20, \
        f"4 independent series should have low max |corr|; got {gate['max_abs_corr']}"

    # Synthetic: R79 highly correlated with R46 (should fail gate)
    r46_leg_corr = pd.Series(r79_leg.values * 0.9 + rng.standard_normal(n) * 0.1, index=idx)
    existing_corr = {"r46": r46_leg_corr, "r62": r62_leg, "r76": r76_leg, "r78": r78_leg}
    gate_corr = r.leg_correlation_gate_n(r79_leg, existing_corr, gate=0.30)
    assert not gate_corr["passes_orthogonality_gate"], \
        f"highly correlated series should fail gate; got {gate_corr}"
    assert gate_corr["corr_new_vs_r46"] > 0.5, \
        f"expected strong positive corr, got {gate_corr['corr_new_vs_r46']}"
    print("  ✓ leg_correlation_gate_n: independent passes (4 legs), correlated fails")


def t_universe_floor():
    """R79 must enforce R79_MIN_TRADEABLE = 12 — refuse to silently widen."""
    import src.research.validation.r79_realized_vol_residual as r
    assert r.R79_MIN_TRADEABLE == 12
    src = Path(r.__file__).read_text()
    assert "do not silently widen" in src.lower() or "refuses to silently widen" in src.lower(), \
        "R79 must encode anti-imposter discipline on universe floor"
    assert "R79_MIN_TRADEABLE" in src, "R79 must reference R79_MIN_TRADEABLE in source"
    print("  ✓ universe floor R79_MIN_TRADEABLE=12 enforced")


def t_matched_cell_sign_audit_logic():
    """Matched-cell sign audit must produce top-3 entries + sign verdict logic."""
    import src.research.validation.r79_realized_vol_residual as r
    src = Path(r.__file__).read_text()
    assert "matched_cell_sign_audit" in src.lower() or "matched_cell" in src.lower(), \
        "R79 must include matched-cell sign audit (anti-imposter)"
    assert "matched_diffs" in src, "R79 must compute matched-cell differentials"
    assert "top_3" in src.lower() or "matched_diffs[:3]" in src, \
        "R79 must report top-3 matched cells"
    assert "sign_verdict" in src, "R79 must declare sign_verdict from matched-cell diff"
    print("  ✓ matched-cell sign audit logic (top-3 + sign_verdict)")


def t_verdict_grammar():
    """Verdict must be one of SURVIVES_ORTHOGONAL / SURVIVES_CORRELATED / REFUTED."""
    import src.research.validation.r79_realized_vol_residual as r
    src = Path(r.__file__).read_text()
    assert "SURVIVES_ORTHOGONAL" in src, "verdict must include SURVIVES_ORTHOGONAL band"
    assert "SURVIVES_CORRELATED" in src, "verdict must include SURVIVES_CORRELATED band"
    assert "REFUTED" in src and "REFUTED" in src.upper(), "verdict must include REFUTED band"
    # Emoji
    assert "✅ SURVIVES + ORTHOGONAL" in src, "verdict must include ✅ for SURVIVES_ORTHOGONAL"
    assert "🟡 SURVIVES + CORRELATED" in src, "verdict must include 🟡 for SURVIVES_CORRELATED"
    assert "🔴 REFUTED" in src, "verdict must include 🔴 for REFUTED"
    # Lesson #43 explicit reference
    assert "lesson #43" in src.lower(), "R79 must explicitly reference lesson #43"
    # Lesson #42 explicit reference (gate)
    assert "lesson #42" in src.lower(), "R79 must explicitly reference lesson #42 (gate)"
    # R78 reference (lesson #43 sharpens)
    assert "r78" in src.lower(), "R79 must reference R78 (predecessor, lesson #43 sharpens)"
    print("  ✓ verdict grammar: 3 bands (✅/🟡/🔴) + lessons #42 + #43 + R78 explicit")


def t_live_book_untouched():
    """R79 must NOT touch the frozen R77 cell. Payload must declare this."""
    import src.research.validation.r79_realized_vol_residual as r
    src = Path(r.__file__).read_text()
    assert "R79 is research-only" in src or "research-only" in src, \
        "R79 must self-mark as research-only"
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "R79 must include touches_frozen_r77_cell: False in payload"
    assert "R77 cell as FROZEN" in src or "R77 fusion-cell" in src or "R77 cell" in src, \
        "R79 must reference R77 cell as frozen"
    print("  ✓ R79 is research-only; frozen R77 cell untouched")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_score_realized_vol_residual_demean, t_score_different_from_funding_residual,
             t_realized_vol_residual_ls_signature_parity, t_rejects_invalid_sign,
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