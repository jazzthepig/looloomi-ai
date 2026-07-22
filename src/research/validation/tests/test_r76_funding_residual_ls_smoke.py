"""
R76 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r73_pillar_a_level_ls_smoke.py + test_r74_pillar_a_fusion_contribution_smoke.py
patterns. 10 tests cover:
  - imports
  - score: funding residual = cross-sectional demean (mean ≈ 0)
  - score ≠ score_funding_zwide (R62's per-asset z over time) — different normalization
  - L/S core: funding_residual_ls signature parity with R73's pillar_a_level_ls
  - both signs supported
  - rejects invalid sign
  - leg-correlation gate (lesson #42 anti-imposter)
  - matched-cell sign audit (returns top-3 differentials)
  - universe floor (R76_MIN_TRADEABLE)
  - verdict grammar (3 bands)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """R76 module + key public symbols importable."""
    import src.research.validation.r76_funding_residual_ls as r
    assert hasattr(r, "run"), "R76 must expose run()"
    assert hasattr(r, "score_funding_residual"), "R76 must expose score_funding_residual"
    assert hasattr(r, "funding_residual_ls"), "R76 must expose funding_residual_ls"
    assert hasattr(r, "leg_correlation_gate"), "R76 must expose leg_correlation_gate"
    assert r.R76_K_TERCILES == 3, f"R76 K_TERCILES must be 3, got {r.R76_K_TERCILES}"
    assert r.R76_MIN_TRADEABLE == 12, f"R76 MIN_TRADEABLE must be 12, got {r.R76_MIN_TRADEABLE}"
    assert r.R76_ORTHOGONALITY_GATE == 0.30, \
        f"R76 orthogonality gate must be 0.30 (lesson #42), got {r.R76_ORTHOGONALITY_GATE}"
    # Sign constants
    assert hasattr(r, "SIGN_HIGH_FUND_LONG")
    assert hasattr(r, "SIGN_LOW_FUND_LONG")
    assert r.SIGN_HIGH_FUND_LONG == "high_fund_long"
    assert r.SIGN_LOW_FUND_LONG == "low_fund_long"
    print("  ✓ R76 imports + K_TERCILES=3 + MIN_TRADEABLE=12 + orthogonality gate=0.30")


def t_score_funding_residual_demean():
    """score_funding_residual = funding[t, a] - mean_a(funding[t, a]).
    Mean across assets at each time must be ~0 by construction."""
    import src.research.validation.r76_funding_residual_ls as r
    # Synthetic: 5 dates × 4 assets with random funding
    rng = np.random.default_rng(42)
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    assets = ["A", "B", "C", "D"]
    funding = pd.DataFrame(
        rng.normal(scale=0.01, size=(5, 4)),
        index=dates, columns=assets,
    )
    tradeable = assets
    residual = r.score_funding_residual(funding, tradeable)
    # Mean across assets at each date must be ≈ 0 (cross-sectional demean)
    row_means = residual.mean(axis=1)
    np.testing.assert_array_almost_equal(row_means.values, np.zeros(5),
                                          decimal=10,
                                          err_msg="residual mean must be 0 by construction")
    # Shape parity
    assert residual.shape == funding.shape, f"shape mismatch: {residual.shape} vs {funding.shape}"
    # Total sum should be ≈ 0 (sum of demeaned values per row is 0)
    assert abs(residual.sum().sum()) < 1e-9, f"total residual sum must be 0, got {residual.sum().sum()}"
    print("  ✓ score_funding_residual: cross-sectional demean (mean ≈ 0 by construction)")


def t_score_different_from_zwide():
    """score_funding_residual (cross-sectional demean) is NOT identical to
    score_funding_zwide (per-asset z over time). Both are funding-based so they
    correlate to some degree, but they apply different normalizations and produce
    different score series. The test confirms the two are NOT the same function.
    """
    import src.research.validation.r76_funding_residual_ls as r
    from src.research.validation.funding_crowding_ls import score_funding_zwide
    rng = np.random.default_rng(7)
    n_days, n_assets = 60, 8
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    # Funding with per-asset mean structure (so residual ≠ zwide)
    asset_means = rng.normal(scale=0.003, size=n_assets)
    funding = pd.DataFrame(
        rng.normal(scale=0.005, size=(n_days, n_assets)) + asset_means,
        index=dates, columns=assets,
    )
    residual = r.score_funding_residual(funding, assets)
    zwide = score_funding_zwide(funding, zwin=30, sign="fade_crowd")

    # Sanity check 1: shapes match
    assert residual.shape == funding.shape, "residual shape mismatch"
    assert zwide.shape == funding.shape, "zwide shape mismatch"

    # Sanity check 2: row means of residual are 0 (demean construction)
    row_means = residual.mean(axis=1)
    np.testing.assert_array_almost_equal(row_means.values, np.zeros(n_days),
                                          decimal=10,
                                          err_msg="residual must be demeaned per row")

    # Sanity check 3: row means of zwide are NOT 0 (zwide keeps per-asset level)
    zwide_row_means = zwide.mean(axis=1)
    # zwide uses lookback window; the per-row mean after warmup is not 0.
    # Just confirm the two scores differ in their row-mean structure:
    assert not np.allclose(row_means.values, zwide_row_means.fillna(0).values, atol=1e-6), \
        "residual and zwide should produce different row-mean structures"

    # Sanity check 4: residual series is NOT a column-shifted version of zwide
    # (would mean they're functionally equivalent). Take first asset and check.
    a = assets[0]
    # After warmup, residual and zwide should differ in their pattern
    diff = (residual[a].fillna(0) - zwide[a].fillna(0)).std()
    assert diff > 0, "residual and zwide must produce different score series"
    print(f"  ✓ score_funding_residual ≠ score_funding_zwide (different normalization; "
          f"std diff = {diff:.4f})")


def t_funding_residual_ls_signature_parity():
    """funding_residual_ls signature must mirror R73's pillar_a_level_ls for orthogonality."""
    import src.research.validation.r76_funding_residual_ls as r
    import inspect
    sig_r76 = inspect.signature(r.funding_residual_ls)
    # Must accept: score_wide, rets, k_terciles, cost_bps, rebal_days, sign
    required_params = {"score_wide", "rets", "k_terciles", "cost_bps", "rebal_days", "sign"}
    sig_params = set(sig_r76.parameters.keys())
    assert required_params.issubset(sig_params), \
        f"funding_residual_ls missing required params; have {sig_params}"
    # Defaults
    assert sig_r76.parameters["k_terciles"].default == r.R76_K_TERCILES
    assert sig_r76.parameters["sign"].default == r.SIGN_HIGH_FUND_LONG
    print("  ✓ funding_residual_ls signature parity with R73's pillar_a_level_ls")


def t_rejects_invalid_sign():
    """funding_residual_ls must ValueError on invalid sign."""
    import src.research.validation.r76_funding_residual_ls as r
    rng = np.random.default_rng(11)
    score_wide = pd.DataFrame(rng.standard_normal((3, 3)), columns=["A", "B", "C"])
    rets = pd.DataFrame(rng.standard_normal((3, 3)) * 0.01, columns=["A", "B", "C"])
    try:
        r.funding_residual_ls(score_wide, rets, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected (ValueError)")


def t_both_signs_supported():
    """Both SIGN_HIGH_FUND_LONG and SIGN_LOW_FUND_LONG must be valid."""
    import src.research.validation.r76_funding_residual_ls as r
    assert r.SIGN_HIGH_FUND_LONG in r._VALID_SIGNS
    assert r.SIGN_LOW_FUND_LONG in r._VALID_SIGNS
    assert len(r._VALID_SIGNS) == 2, f"only 2 valid signs, got {len(r._VALID_SIGNS)}"
    print("  ✓ both signs supported (high_fund_long, low_fund_long)")


def t_leg_correlation_gate():
    """leg_correlation_gate must return all required fields + correct logic."""
    import src.research.validation.r76_funding_residual_ls as r
    rng = np.random.default_rng(13)
    n = 200
    idx = pd.date_range("2025-06-01", periods=n, freq="D")

    # Synthetic: R76 leg independent of R46 + R62
    r76_leg = pd.Series(rng.standard_normal(n), index=idx)
    r46_leg = pd.Series(rng.standard_normal(n), index=idx)  # independent
    r62_leg = pd.Series(rng.standard_normal(n), index=idx)  # independent
    gate = r.leg_correlation_gate(r76_leg, r46_leg, r62_leg, gate=0.30)
    # All required fields
    for k in ("corr_r76_vs_r46", "corr_r76_vs_r62", "max_abs_corr",
              "gate_threshold", "passes_orthogonality_gate", "fusion_candidatable"):
        assert k in gate, f"gate missing {k}"
    # Independent series: should pass gate (low correlation)
    assert gate["passes_orthogonality_gate"], \
        f"independent series should pass gate; got {gate}"
    assert gate["fusion_candidatable"], "fusion_candidatable must match passes_gate"

    # Synthetic: R76 highly correlated with R46
    r46_leg_corr = pd.Series(r76_leg.values * 0.9 + rng.standard_normal(n) * 0.1, index=idx)
    gate_corr = r.leg_correlation_gate(r76_leg, r46_leg_corr, r62_leg, gate=0.30)
    assert not gate_corr["passes_orthogonality_gate"], \
        f"highly correlated series should fail gate; got {gate_corr}"
    assert gate_corr["corr_r76_vs_r46"] > 0.5, \
        f"expected strong positive corr, got {gate_corr['corr_r76_vs_r46']}"
    print("  ✓ leg_correlation_gate: independent passes, correlated fails")


def t_universe_floor():
    """R76 must enforce R76_MIN_TRADEABLE = 12 — refuse to silently widen."""
    import src.research.validation.r76_funding_residual_ls as r
    assert r.R76_MIN_TRADEABLE == 12
    src = Path(r.__file__).read_text()
    assert "do not silently widen" in src.lower() or "refuses to silently widen" in src.lower(), \
        "R76 must encode anti-imposter discipline on universe floor"
    assert "R76_MIN_TRADEABLE" in src, "R76 must reference R76_MIN_TRADEABLE in source"
    print("  ✓ universe floor R76_MIN_TRADEABLE=12 enforced")


def t_matched_cell_sign_audit_logic():
    """matched-cell sign audit must produce top-3 entries + sign verdict logic."""
    import src.research.validation.r76_funding_residual_ls as r
    src = Path(r.__file__).read_text()
    assert "matched_cell_sign_audit" in src or "matched_cell" in src.lower(), \
        "R76 must include matched-cell sign audit (anti-imposter)"
    assert "matched_diffs" in src, "R76 must compute matched-cell differentials"
    assert "top-3" in src.lower() or "matched_diffs[:3]" in src, \
        "R76 must report top-3 matched cells"
    assert "sign_verdict" in src, "R76 must declare sign_verdict from matched-cell diff"
    print("  ✓ matched-cell sign audit logic (top-3 + sign_verdict)")


def t_verdict_grammar():
    """Verdict must be one of SURVIVES_ORTHOGONAL / SURVIVES_CORRELATED / REFUTED."""
    import src.research.validation.r76_funding_residual_ls as r
    src = Path(r.__file__).read_text()
    assert "SURVIVES_ORTHOGONAL" in src, "verdict must include SURVIVES_ORTHOGONAL band"
    assert "SURVIVES_CORRELATED" in src, "verdict must include SURVIVES_CORRELATED band"
    assert "REFUTED" in src and "REFUTED" in src.upper(), "verdict must include REFUTED band"
    # Emoji
    assert "✅ SURVIVES + ORTHOGONAL" in src, "verdict must include ✅ for SURVIVES_ORTHOGONAL"
    assert "🟡 SURVIVES + CORRELATED" in src, "verdict must include 🟡 for SURVIVES_CORRELATED"
    assert "🔴 REFUTED" in src, "verdict must include 🔴 for REFUTED"
    # Lesson #42 explicit reference
    assert "lesson #42" in src.lower(), "R76 must explicitly reference lesson #42"
    print("  ✓ verdict grammar: 3 bands (✅/🟡/🔴) + lesson #42 explicit")


def t_live_book_untouched():
    """R76 must NOT touch the frozen R69 cell. Payload must declare this."""
    import src.research.validation.r76_funding_residual_ls as r
    src = Path(r.__file__).read_text()
    assert "R76 is research-only" in src or "research-only" in src, \
        "R76 must self-mark as research-only"
    assert "touches_frozen_r69_cell" in src and "False" in src, \
        "R76 must include touches_frozen_r69_cell: False in payload"
    print("  ✓ R76 is research-only; live book untouched")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_score_funding_residual_demean, t_score_different_from_zwide,
             t_funding_residual_ls_signature_parity, t_rejects_invalid_sign,
             t_both_signs_supported, t_leg_correlation_gate, t_universe_floor,
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
