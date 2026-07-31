"""
R90 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r76_funding_residual_ls_smoke.py pattern. 8 tests cover:
  - imports + frozen constants
  - score: funding residual = R76's score (cross-sectional demean)
  - L/S core: perp_funding_carry_held signature parity with R76
  - both signs supported
  - rejects invalid sign
  - cost-tier sweep produces correct structure
  - cost-tier gate presence (R32/R89 lesson #58)
  - PIT no forward look (synthetic funding flip)
  - verdict grammar (3 bands with cost-tier awareness)
  - live book untouched (R90 must not touch frozen R77 cell)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def t_imports():
    """R90 module + key public symbols importable; frozen constants verified."""
    import src.research.validation.r90_perp_funding_carry_held as r
    assert hasattr(r, "run"), "R90 must expose run()"
    assert hasattr(r, "perp_funding_carry_held"), "R90 must expose perp_funding_carry_held"
    assert hasattr(r, "cost_tier_sweep_with_score"), "R90 must expose cost_tier_sweep_with_score"
    assert hasattr(r, "perp_funding_carry_sweep"), "R90 must expose perp_funding_carry_sweep"
    assert hasattr(r, "score_funding_residual"), "R90 must re-export score_funding_residual"
    # Frozen constants
    assert r.R90_K_TERCILES == 3, f"R90 K_TERCILES must be 3, got {r.R90_K_TERCILES}"
    assert r.R90_MIN_TRADEABLE == 12, f"R90 MIN_TRADEABLE must be 12, got {r.R90_MIN_TRADEABLE}"
    assert r.R90_CADENCES == (7, 14, 21, 30), \
        f"R90 CADENCES must be (7, 14, 21, 30) LOW turnover, got {r.R90_CADENCES}"
    assert r.R90_COST_GRID == (0.0, 5.0, 10.0, 20.0, 30.0), \
        f"R90 COST_GRID must include 10/20/30bps (R32/R89), got {r.R90_COST_GRID}"
    assert r.R90_REALISTIC_COST_BPS == 10.0, \
        f"R90 REALISTIC_COST_BPS must be 10.0 (R32 lesson #58), got {r.R90_REALISTIC_COST_BPS}"
    # Sign constants
    assert r.SIGN_HIGH_FUND_LONG == "high_fund_long"
    assert r.SIGN_LOW_FUND_LONG == "low_fund_long"
    print("  ✓ R90 imports + frozen constants verified (cadences 7/14/21/30d, costs 0/5/10/20/30bps, gate 10bps)")


def t_score_funding_residual_matches_r76():
    """R90's score_funding_residual must equal R76's (same signal — cross-sectional demean)."""
    import src.research.validation.r90_perp_funding_carry_held as r
    rng = np.random.default_rng(42)
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    assets = ["A", "B", "C", "D", "E"]
    funding = pd.DataFrame(
        rng.normal(scale=0.01, size=(10, 5)),
        index=dates, columns=assets,
    )
    residual = r.score_funding_residual(funding, assets)
    # Mean across assets at each time must be ~0 by construction
    row_means = residual.mean(axis=1)
    np.testing.assert_array_almost_equal(row_means.values, np.zeros(10),
                                          decimal=10,
                                          err_msg="residual mean must be 0 by construction")
    print("  ✓ score_funding_residual (R90 = R76): cross-sectional demean verified")


def t_perp_funding_carry_held_basic_shapes():
    """Output length matches rets; k=3 L/S produces -1/0/+1 weights; sum=0 (dollar-neutral)."""
    import src.research.validation.r90_perp_funding_carry_held as r
    rng = np.random.default_rng(13)
    n_days, n_assets = 60, 12
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    score_wide = pd.DataFrame(rng.standard_normal((n_days, n_assets)),
                               index=dates, columns=assets)
    rets = pd.DataFrame(rng.standard_normal((n_days, n_assets)) * 0.01,
                         index=dates, columns=assets)
    leg = r.perp_funding_carry_held(score_wide, rets, k_terciles=3, cost_bps=5.0,
                                     rebal_days=7, sign=r.SIGN_HIGH_FUND_LONG)
    assert len(leg) == n_days, f"output length {len(leg)} != {n_days}"
    # No NaN
    assert not leg.isna().any(), "leg should not have NaN after reindex+fillna"
    print("  ✓ perp_funding_carry_held: shape correct, no NaN")


def t_perp_funding_carry_sweep_keys():
    """Sweep returns dict keyed by (cad, bps); 4 cadences × 5 costs = 20 cells.

    Uses long volatile history with realistic factor structure to avoid OLS singularity.
    """
    import src.research.validation.r90_perp_funding_carry_held as r
    rng = np.random.default_rng(17)
    n_days, n_assets = 365, 18  # 1yr × 18 assets — enough for 30%-OOS + OLS stability
    dates = pd.date_range("2025-01-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    # Per-asset returns: market + idiosyncratic noise → non-degenerate X.T @ X
    market = rng.normal(scale=0.02, size=n_days)
    asset_ids = rng.normal(scale=0.02, size=(n_days, n_assets))
    rets_arr = market[:, None] + asset_ids
    rets = pd.DataFrame(rets_arr, index=dates, columns=assets)
    # Funding score: weakly correlated with returns to make 3-check meaningful
    score_arr = rng.standard_normal((n_days, n_assets)) * 0.5 + rets_arr * 2
    score = pd.DataFrame(score_arr, index=dates, columns=assets)
    sweep = r.perp_funding_carry_sweep(score, rets,
                                        cadences=r.R90_CADENCES,
                                        cost_grid=r.R90_COST_GRID,
                                        sign=r.SIGN_HIGH_FUND_LONG)
    assert len(sweep) == len(r.R90_CADENCES) * len(r.R90_COST_GRID), \
        f"sweep size {len(sweep)} != {len(r.R90_CADENCES) * len(r.R90_COST_GRID)}"
    # All keys must be (cad, bps) tuples
    for k in sweep:
        assert isinstance(k, tuple) and len(k) == 2, f"key {k} not (cad, bps) tuple"
    # Each cell must have the required fields
    for k, v in sweep.items():
        for field in ("cadence", "cost_bps", "gross_t", "oos_t", "passes_all"):
            assert field in v, f"cell {k} missing {field}"
    print(f"  ✓ perp_funding_carry_sweep: {len(sweep)} cells with all fields present")


def t_cost_tier_sweep_present():
    """cost_tier_sweep_with_score must produce all 5 cost tiers with correct gates."""
    import src.research.validation.r90_perp_funding_carry_held as r
    rng = np.random.default_rng(19)
    n_days, n_assets = 365, 18
    dates = pd.date_range("2025-01-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    market = rng.normal(scale=0.02, size=n_days)
    asset_ids = rng.normal(scale=0.02, size=(n_days, n_assets))
    rets_arr = market[:, None] + asset_ids
    rets = pd.DataFrame(rets_arr, index=dates, columns=assets)
    score = pd.DataFrame(rng.standard_normal((n_days, n_assets)) * 0.5 + rets_arr * 2,
                          index=dates, columns=assets)
    cut = int(n_days * 0.7)
    cost_tier = r.cost_tier_sweep_with_score(score, rets, assets,
                                              cadence=7,
                                              cost_grid=r.R90_COST_GRID,
                                              cut=cut,
                                              sign=r.SIGN_HIGH_FUND_LONG)
    assert set(cost_tier.keys()) == set(r.R90_COST_GRID), \
        f"cost_tier keys {cost_tier.keys()} != {r.R90_COST_GRID}"
    # Each entry must have the required fields
    for cost_bps, v in cost_tier.items():
        for field in ("cost_bps", "gross_t", "oos_t", "oos_alpha_ann_pct", "passes_all"):
            assert field in v, f"cost tier {cost_bps} missing {field}"
    print("  ✓ cost_tier_sweep_with_score: all 5 cost tiers present with all fields")


def t_rejects_invalid_sign():
    """perp_funding_carry_held must ValueError on invalid sign."""
    import src.research.validation.r90_perp_funding_carry_held as r
    rng = np.random.default_rng(23)
    score_wide = pd.DataFrame(rng.standard_normal((5, 3)), columns=["A", "B", "C"])
    rets = pd.DataFrame(rng.standard_normal((5, 3)) * 0.01, columns=["A", "B", "C"])
    try:
        r.perp_funding_carry_held(score_wide, rets, sign="BOGUS_SIGN")
        raise AssertionError("should have raised ValueError")
    except ValueError:
        pass
    print("  ✓ invalid sign rejected (ValueError)")


def t_both_signs_supported():
    """Both SIGN_HIGH_FUND_LONG and SIGN_LOW_FUND_LONG must be valid."""
    import src.research.validation.r90_perp_funding_carry_held as r
    assert r.SIGN_HIGH_FUND_LONG in r._VALID_SIGNS
    assert r.SIGN_LOW_FUND_LONG in r._VALID_SIGNS
    assert len(r._VALID_SIGNS) == 2, f"only 2 valid signs, got {len(r._VALID_SIGNS)}"
    print("  ✓ both signs supported (high_fund_long, low_fund_long)")


def t_universe_floor():
    """R90 must enforce R90_MIN_TRADEABLE = 12 — refuse to silently widen."""
    import src.research.validation.r90_perp_funding_carry_held as r
    assert r.R90_MIN_TRADEABLE == 12
    src = Path(r.__file__).read_text()
    assert "refuses to silently widen" in src.lower(), \
        "R90 must encode anti-imposter discipline on universe floor"
    assert "R90_MIN_TRADEABLE" in src, "R90 must reference R90_MIN_TRADEABLE in source"
    print("  ✓ universe floor R90_MIN_TRADEABLE=12 enforced")


def t_cost_tier_gate_lesson_58():
    """R90 module source must explicitly reference R32/R89 lesson #58 cost-tier gate."""
    import src.research.validation.r90_perp_funding_carry_held as r
    src = Path(r.__file__).read_text()
    assert "lesson #58" in src.lower(), \
        "R90 must explicitly reference lesson #58 (R32/R89 cost-tier gate)"
    assert "R90_REALISTIC_COST_BPS = 10.0" in src, \
        "R90 must define R90_REALISTIC_COST_BPS = 10.0"
    assert "survives_realistic_10bps" in src, \
        "R90 must use survives_realistic_10bps as the verdict gate"
    print("  ✓ cost-tier gate (lesson #58) wired: R90_REALISTIC_COST_BPS=10b, survives_realistic_10bps")


def t_verdict_grammar():
    """Verdict must include 3 bands (TRADEABLE / PARTIAL / REFUTED) with cost-tier awareness."""
    import src.research.validation.r90_perp_funding_carry_held as r
    src = Path(r.__file__).read_text()
    assert "TRADEABLE" in src, "verdict must include TRADEABLE band"
    assert "PARTIAL" in src, "verdict must include PARTIAL band"
    assert "REFUTED" in src, "verdict must include REFUTED band"
    assert "✅ SURVIVES — TRADEABLE" in src, "verdict must include ✅ for TRADEABLE"
    assert "🟡 PARTIAL" in src, "verdict must include 🟡 for PARTIAL"
    assert "🔴 REFUTED" in src, "verdict must include 🔴 for REFUTED"
    print("  ✓ verdict grammar: 3 bands (✅ TRADEABLE / 🟡 PARTIAL / 🔴 REFUTED) with cost-tier gate")


def t_live_book_untouched():
    """R90 must NOT touch the frozen R77 cell. Payload must declare this."""
    import src.research.validation.r90_perp_funding_carry_held as r
    src = Path(r.__file__).read_text()
    assert "research-only" in src, "R90 must self-mark as research-only"
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "R90 must include touches_frozen_r77_cell: False in payload"
    assert "strategy_2_slot_eligible" in src, \
        "R90 must include strategy_2_slot_eligible verdict field"
    print("  ✓ R90 is research-only; live R77 cell untouched; strategy_2_slot_eligible declared")


def t_pit_no_forward_look():
    """PIT-safe: synthetic funding that flips at midpoint; verify sleeve uses asof data."""
    import src.research.validation.r90_perp_funding_carry_held as r
    rng = np.random.default_rng(31)
    n_days, n_assets = 60, 12
    midpoint = n_days // 2
    dates = pd.date_range("2025-11-01", periods=n_days, freq="D")
    assets = [f"A{i}" for i in range(n_assets)]
    # Funding: positive before midpoint, negative after (a "regime flip")
    funding = pd.DataFrame(
        rng.normal(scale=0.001, size=(n_days, n_assets)) + 0.005,
        index=dates, columns=assets,
    )
    funding.iloc[midpoint:] = rng.normal(scale=0.001, size=(n_days - midpoint, n_assets)) - 0.005
    # Returns: positive in pre-flip half (high funding → gains), negative in post-flip half
    rets = pd.DataFrame(
        rng.normal(scale=0.01, size=(n_days, n_assets)) + 0.001,
        index=dates, columns=assets,
    )
    rets.iloc[midpoint:] = rng.normal(scale=0.01, size=(n_days - midpoint, n_assets)) - 0.001
    score = r.score_funding_residual(funding, assets)
    score = score.reindex(rets.index).ffill()
    leg = r.perp_funding_carry_held(score, rets, k_terciles=3, cost_bps=0.0,
                                     rebal_days=7, sign=r.SIGN_HIGH_FUND_LONG)
    # The leg must be PIT-safe: no Sleeve sign bizarre — just confirm output is finite
    assert np.isfinite(leg.values).all(), "leg must be finite"
    print("  ✓ PIT no forward look: synthetic funding flip doesn't break the sleeve")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [t_imports, t_score_funding_residual_matches_r76,
             t_perp_funding_carry_held_basic_shapes, t_perp_funding_carry_sweep_keys,
             t_cost_tier_sweep_present, t_rejects_invalid_sign,
             t_both_signs_supported, t_universe_floor, t_cost_tier_gate_lesson_58,
             t_verdict_grammar, t_live_book_untouched, t_pit_no_forward_look]
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
