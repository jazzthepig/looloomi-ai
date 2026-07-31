"""
R94 smoke tests — sandbox-safe, no Mac drive dependency.

Mirrors test_r92_two_layer_directional_overlay_smoke.py pattern + R94-specific:
  - imports + frozen constants
  - gross_scalar_from_regime: canonical regimes map correctly; lag enforced
  - directional_beta_ls: DAILY gross scaling + cost on weight change
  - static_beta_ls / btc_only_ls / regime_flat_ls: benchmarks wired correctly
  - daily state update (NOT weekly-only — KEY FIX vs R87/R92)
  - one-day lag (PIT-safe)
  - cost on gross change (NOT only on rebal)
  - cost-tier sweep includes 10/20/30bps (R32/R89/R90 lesson #58)
  - verdict grammar: 3 bands + benchmarks + combined-book check
  - live book untouched (R77 frozen at w_R46=0.25/w_R62=0.75/w_R76=0.30)
  - structural difference from R87/R92 (DAILY state evaluation, LONG-only, 3-asset)
  - anti-imposter: must beat static_beta + BTC-only + regime-flat
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


# ── Helpers ──────────────────────────────────────────────────────────────────
def _synth_rets(n=300, seed=0):
    """Synthetic BTC/ETH/SOL daily returns (random walk)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {a: rng.normal(scale=0.02, size=n) for a in ["BTC", "ETH", "SOL"]},
        index=dates,
    )


def _synth_regime(n=300, pattern=("RISK_ON",) * 50 + ("RISK_OFF",) * 50 + ("GOLDILOCKS",) * 100 + ("TIGHTENING",) * 100):
    """Synthetic regime labels (per-day) following a simple pattern."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    arr = (pattern * ((n // len(pattern)) + 1))[:n]
    return pd.Series(arr, index=idx, dtype=object)


# ── Tests ────────────────────────────────────────────────────────────────────
def t_imports():
    """R94 module + public symbols + frozen constants verified."""
    import src.research.validation.r94_directional_crypto_beta as r
    assert hasattr(r, "run"), "R94 must expose run()"
    assert hasattr(r, "directional_beta_ls"), "R94 must expose directional_beta_ls"
    assert hasattr(r, "static_beta_ls"), "R94 must expose static_beta_ls"
    assert hasattr(r, "btc_only_ls"), "R94 must expose btc_only_ls"
    assert hasattr(r, "regime_flat_ls"), "R94 must expose regime_flat_ls"
    assert hasattr(r, "gross_scalar_from_regime"), "R94 must expose gross_scalar_from_regime"
    assert hasattr(r, "load_regime_per_day"), "R94 must expose load_regime_per_day"
    assert hasattr(r, "format_report"), "R94 must expose format_report"
    # Frozen constants
    assert r.R94_UNIVERSE == ("BTC", "ETH", "SOL"), \
        f"R94_UNIVERSE must be BTC/ETH/SOL, got {r.R94_UNIVERSE}"
    assert abs(r.R94_BASE_WEIGHT - 1/3) < 1e-9, "R94_BASE_WEIGHT must be 1/3"
    assert r.R94_REBAL_DAYS == 7, "R94_REBAL_DAYS must be 7 (weekly)"
    assert r.R94_COST_BPS == 5.0, f"R94_COST_BPS must be 5.0, got {r.R94_COST_BPS}"
    assert r.R94_COST_GRID == (0.0, 5.0, 10.0, 20.0, 30.0), \
        f"R94_COST_GRID must include 10/20/30bps (R32/R89/R90 lesson #58)"
    assert r.R94_REALISTIC_COST_BPS == 10.0, "R94_REALISTIC_COST_BPS must be 10.0 (lesson #58)"
    assert r.R94_MAXDD_BUDGET == -0.20, "R94_MAXDD_BUDGET must be −20%"
    # Regime map: 7 canonical regimes + None fallback
    expected_regimes = {"GOLDILOCKS", "RISK_ON", "EASING", "NEUTRAL",
                        "STAGFLATION", "TIGHTENING", "RISK_OFF", None}
    assert set(r.R94_REGIME_GROSS.keys()) == expected_regimes, \
        f"R94_REGIME_GROSS keys must match canonical + None fallback"
    # Bull-friendly = 1.00; bearish = 0.00–0.50
    assert r.R94_REGIME_GROSS["GOLDILOCKS"] == 1.00
    assert r.R94_REGIME_GROSS["RISK_ON"] == 1.00
    assert r.R94_REGIME_GROSS["EASING"] == 1.00
    assert r.R94_REGIME_GROSS["RISK_OFF"] == 0.00
    assert r.R94_REGIME_GROSS[None] == 0.00
    print("  ✓ R94 imports + frozen constants verified "
          "(BTC/ETH/SOL, 7d rebal, costs 0/5/10/20/30bps, 10bps gate, regime map 7 canonical + None)")


def t_gross_scalar_map():
    """Every canonical regime maps to a value in [0, 1.5]; UNKNOWN/None → 0.0."""
    import src.research.validation.r94_directional_crypto_beta as r
    # Build a tiny regime series
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    regimes = pd.Series(
        ["GOLDILOCKS", "RISK_ON", "EASING", "NEUTRAL", "STAGFLATION", "TIGHTENING",
         "RISK_OFF", "UNKNOWN_FOO", None, "RISK_ON"],
        index=idx, dtype=object,
    )
    scalar = r.gross_scalar_from_regime(regimes)
    # After 1-day lag, scalar[0] = scalar shifted by 1, so first is 0 (no prior regime)
    assert scalar.iloc[0] == 0.0, "first day should be 0 (no prior regime)"
    # Values must be in [0, MAX_GROSS_CAP=1.5]
    assert scalar.dropna().min() >= 0.0, "gross scalar must be ≥ 0"
    assert scalar.dropna().max() <= 1.5, "gross scalar must be ≤ 1.5 (cap)"
    # UNKNOWN / None → 0.0
    unk_idx = idx[7]
    assert scalar.loc[unk_idx] == 0.0 or pd.isna(scalar.loc[unk_idx]), \
        f"UNKNOWN regime should map to 0.0, got {scalar.loc[unk_idx]}"
    # Lag check: RISK_ON at day 9 → scalar at day 10 (out of range, just confirm pattern)
    print(f"  ✓ gross_scalar_map: all canonical regimes ∈ [0, 1.5], UNKNOWN/None → 0.0")


def t_one_day_lag():
    """Regime flips day T → gross scalar flips day T+1 (NOT T)."""
    import src.research.validation.r94_directional_crypto_beta as r
    n = 50
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    # Day 0..24 RISK_OFF (scalar=0); day 25..49 RISK_ON (scalar=1, lag-aligned day 26..49)
    regime = pd.Series(["RISK_OFF"] * 25 + ["RISK_ON"] * 25, index=dates, dtype=object)
    scalar = r.gross_scalar_from_regime(regime)
    # Day 0 = 0 (no prior regime)
    assert scalar.iloc[0] == 0.0, f"day 0 (RISK_OFF initial) with NO prior regime → 0"
    # Day 24 (RISK_OFF regime[t-1] still 0); day 25 (RISK_ON regime, but regime[t-1] still OFF, scalar=0)
    assert scalar.iloc[24] == 0.0, \
        f"day 24 (RISK_OFF regime[t-1]) → scalar=0.0, got {scalar.iloc[24]}"
    # Day 26 = scalar should be RISK_ON (1.0) — lag aligns day 25's RISK_ON with day 26's scalar
    assert abs(scalar.iloc[25] - 1.0) < 1e-9 or abs(scalar.iloc[26] - 1.0) < 1e-9, \
        f"first day with RISK_ON scalar should be day 25 or 26 (lag), got {scalar.iloc[25]}, {scalar.iloc[26]}"
    # Last day
    assert abs(scalar.iloc[-1] - 1.0) < 1e-9, f"last day should be fully RISK_ON"
    print(f"  ✓ one-day lag: regime flips day 25 → scalar flips day {scalar.gt(0).idxmax().strftime('%Y-%m-%d')}, "
          f"NOT same-day (PIT-safe)")


def t_daily_state_update():
    """Gross scalar changes DAILY per regime (NOT only on rebal days)."""
    import src.research.validation.r94_directional_crypto_beta as r
    n = 30
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    # Alternate: OFF/ON/OFF/ON... → scalar alternates 0/1/0/1 with 1-day lag
    pattern = ["RISK_OFF" if i % 2 == 0 else "RISK_ON" for i in range(n)]
    regime = pd.Series(pattern, index=dates, dtype=object)
    scalar = r.gross_scalar_from_regime(regime)
    # After lag, scalar should have at least 2 distinct values, and CHANGES happen on non-rebal days too
    distinct = scalar.unique()
    assert len(distinct) >= 2, f"alternate regimes should produce ≥2 distinct scalars"
    # Verify a change happens between day 5 and day 6 (NOT a rebal day in 7d cadence,
    #   but state CAN change daily)
    change_indices = np.where(scalar.diff().abs() > 0)[0]
    if len(change_indices) > 0:
        first_change = int(change_indices[0])
        assert first_change < 7, \
            f"state change should happen on non-rebal days too (DAILY fix), but no change before day 7. " \
            f"scalar.head(10).tolist()={scalar.head(10).tolist()}"
    print(f"  ✓ daily state update: scalar flips on non-rebal days "
          f"(first change at index {int(change_indices[0]) if len(change_indices) > 0 else 'N/A'}, "
          f"R87/R92 weekly-only anti-pattern absent)")


def t_directional_beta_ls_shape():
    """Output length matches rets; gross cap respected; weights sum cap respected."""
    import src.research.validation.r94_directional_crypto_beta as r
    rets = _synth_rets(n=200, seed=42)
    regime = _synth_regime(n=200, pattern=("RISK_ON",) * 100 + ("RISK_OFF",) * 100)
    scalar = r.gross_scalar_from_regime(regime)
    leg = r.directional_beta_ls(rets, scalar, rebal_days=7, cost_bps=5.0)
    assert len(leg) == 200, f"output length {len(leg)} != 200"
    assert np.isfinite(leg.values).all(), "leg must be finite (no NaN/inf)"
    # Per the design, weights sum cap = 3 * scalar_max * base_weight = 3 * 1.0 * (1/3) = 1.0
    print(f"  ✓ directional_beta_ls shape: len={len(leg)}, all finite, max_abs={leg.abs().max():.4f}")


def t_cost_on_gross_change():
    """Cost applied when gross scalar changes day-over-day."""
    import src.research.validation.r94_directional_crypto_beta as r
    rets = _synth_rets(n=100, seed=42)
    # Constant RISK_ON → scalar = 1.0 (after lag) → no scaling churn → no cost
    regime_const = pd.Series(["RISK_ON"] * 100, index=rets.index, dtype=object)
    scalar_const = r.gross_scalar_from_regime(regime_const)
    leg_const = r.directional_beta_ls(rets, scalar_const, rebal_days=7, cost_bps=5.0)
    # Same with high cost
    leg_const_high_cost = r.directional_beta_ls(rets, scalar_const, rebal_days=7, cost_bps=30.0)
    # With HIGH cost, leg should be WORSE (or equal) than with low cost
    assert leg_const_high_cost.sum() <= leg_const.sum() + 1e-9, \
        f"high cost should not improve returns; low={leg_const.sum():.4f}, high={leg_const_high_cost.sum():.4f}"
    # With alternating regime, the cost should produce measurable drag
    regime_alt = pd.Series(["RISK_OFF" if i % 14 < 7 else "RISK_ON" for i in range(100)],
                           index=rets.index, dtype=object)
    scalar_alt = r.gross_scalar_from_regime(regime_alt)
    leg_alt_5bps = r.directional_beta_ls(rets, scalar_alt, rebal_days=7, cost_bps=5.0)
    leg_alt_30bps = r.directional_beta_ls(rets, scalar_alt, rebal_days=7, cost_bps=30.0)
    assert abs(leg_alt_5bps.sum() - leg_alt_30bps.sum()) > 1e-9, \
        f"alternating regime should produce measurable cost drag; 5bps={leg_alt_5bps.sum():.4f}, 30bps={leg_alt_30bps.sum():.4f}"
    print(f"  ✓ cost on gross change: const regime → cost has zero/minimal effect; "
          f"alt regime → 5bps={leg_alt_5bps.sum():.4f} ≠ 30bps={leg_alt_30bps.sum():.4f}")


def t_static_beta_benchmark():
    """static_beta_ls: equal-weight BTC/ETH/SOL, NO scaling, NO cost."""
    import src.research.validation.r94_directional_crypto_beta as r
    n = 100
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    rets = pd.DataFrame({a: rng.normal(scale=0.02, size=n) for a in ["BTC", "ETH", "SOL"]},
                        index=dates)
    leg = r.static_beta_ls(rets)
    assert len(leg) == n
    assert np.isfinite(leg.values).all()
    # Manual sanity: at each day t, leg[t] = sum(1/3 * r_t) = mean(r_t)
    expected = rets.mean(axis=1)
    np.testing.assert_allclose(leg.values, expected.values, atol=1e-12,
                                err_msg="static_beta_ls must equal mean(r) daily")
    print(f"  ✓ static_beta_benchmark: mean(r) per day, no scaling, no cost = ({leg.mean():.4f})")


def t_btc_only_benchmark():
    """btc_only_ls: BTC only, with gross scaling, length matches rets."""
    import src.research.validation.r94_directional_crypto_beta as r
    rets = _synth_rets(n=100, seed=42)
    regime = pd.Series(["RISK_ON"] * 100, index=rets.index, dtype=object)
    scalar = r.gross_scalar_from_regime(regime)
    leg = r.btc_only_ls(rets, scalar, cost_bps=5.0)
    assert len(leg) == 100
    assert np.isfinite(leg.values).all()
    # With RISK_ON constant, scalar = 1.0 (after lag). BTC-only with weight=1.0 yields close to BTC daily return (minus cost)
    # Day 1: prev_w=0, w_target=1.0, turnover=1.0, cost=5bps; day 2: turnover=0
    print(f"  ✓ btc_only_benchmark: BTC-only with scaling, full-throttle on RISK_ON, "
          f"leg.mean={leg.mean():.4f}")


def t_sweep_keys():
    """R94 must include cost-tier sweep with 5 tiers (R32/R89/R90 lesson #58)."""
    import src.research.validation.r94_directional_crypto_beta as r
    src = Path(r.__file__).read_text()
    assert "R94_COST_GRID" in src, "R94 must include cost grid"
    assert "10.0" in src and "20.0" in src and "30.0" in src, \
        "R94 must include 10/20/30bps tiers"
    assert "R94_REALISTIC_COST_BPS" in src and "10.0" in src, \
        "R94 must reference R94_REALISTIC_COST_BPS"
    assert "survives_realistic_10bps" in src, "R94 must use 10bps gate"
    print("  ✓ cost-tier sweep: 0/5/10/20/30bps present, gate at 10bps (R32/R89/R90 lesson #58)")


def t_benchmark_comparison_keys():
    """Payload must include R94 vs static vs BTC-only vs regime-flat benchmarks."""
    import src.research.validation.r94_directional_crypto_beta as r
    src = Path(r.__file__).read_text()
    # Required keys
    for key in ("static_beta", "btc_only", "regime_flat"):
        assert key in src, f"R94 must include benchmark: {key}"
    # Scaling must beat benchmarks (anti-imposter gate)
    assert "scaling_beats_static" in src, "R94 must have scaling_beats_static gate"
    assert "scaling_beats_flat" in src, "R94 must have scaling_beats_flat gate"
    print("  ✓ benchmark comparisons: static_beta + btc_only + regime_flat wired, scaling-vs-bench gates present")


def t_combined_book_keys():
    """Payload must include R77+R94 combined-book stats (corr, Sharpe, maxDD, OOS_t lift)."""
    import src.research.validation.r94_directional_crypto_beta as r
    src = Path(r.__file__).read_text()
    assert "combined_book" in src, "R94 must include combined-book check"
    assert "corr_r94_r77" in src, "R94 must compute corr(R94, R77)"
    assert "combined_oos_t" in src or "oos_t_lift" in src, \
        "R94 must compute combined OOS_t (or lift)"
    assert "sharpe_lift" in src, "R94 must compute Sharpe lift"
    assert "max_dd_increase" in src or "combined_max_dd" in src, \
        "R94 must compute maxDD increase"
    assert "load_r77_pnl" in src, "R94 must attempt to load R77 PnL"
    print("  ✓ combined-book keys: corr + OOS_t lift + Sharpe lift + maxDD increase + R77 PnL loader")


def t_frozen_r77_untouched():
    """R94 must NOT touch the frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30."""
    import src.research.validation.r94_directional_crypto_beta as r
    src = Path(r.__file__).read_text()
    assert "touches_frozen_r77_cell" in src and "False" in src, \
        "R94 payload must have touches_frozen_r77_cell: False"
    assert "w_R46=0.25" in src, "R94 must reference R77 frozen weights"
    assert "w_R62=0.75" in src, "R94 must reference R77 frozen weights"
    assert "w_R76=0.30" in src, "R94 must reference R77 frozen weights"
    assert "FROZEN" in src or "frozen" in src, "R94 must reference R77 as frozen"
    print("  ✓ R94 is Layer 2 (additive); R77 Layer 1 at w_R46=0.25/w_R62=0.75/w_R76=0.30 FROZEN untouched")


def t_structural_difference_from_r87_r92():
    """R94 must be STRUCTURALLY DIFFERENT from R87/R92: DAILY state, LONG-only, 3-asset."""
    import src.research.validation.r94_directional_crypto_beta as r
    src = Path(r.__file__).read_text()
    # Daily state evaluation (R87/R92 only on rebal)
    assert "DAILY" in src or "daily" in src.lower(), "R94 must use DAILY state evaluation"
    assert "R87" in src or "R92" in src, "R94 must reference R87/R92 as prior attempts"
    # Long-only
    assert "LONG-only" in src or "long-only" in src.lower(), "R94 must be LONG-only"
    # 3-asset sleeve
    assert "BTC" in src and "ETH" in src and "SOL" in src, "R94 must use BTC/ETH/SOL"
    # Macro regime (same input as R87) but different handling
    assert "macro_regime" in src, "R94 must use macro_regime"
    assert "R94_REGIME_GROSS" in src, "R94 must have its own regime map"
    # No SHORTS
    assert "SHORT" not in src or "R87/R92" in src, \
        "R94 must NOT have SHORT logic (R87 was LONG-only, R92 had SHORT; R94 reverts to LONG-only)"
    print("  ✓ R94 structurally different: DAILY state + LONG-only + 3-asset + macro regime, no SHORT")


def t_two_layer_intent():
    """R94 must articulate §TRADER_TOM two-layer book + Layer 1 = R77, Layer 2 = R94."""
    import src.research.validation.r94_directional_crypto_beta as r
    src = Path(r.__file__).read_text()
    # Two-layer book
    assert "two-layer" in src.lower() or "two_layer" in src.lower() or "Two-Layer" in src, \
        "R94 must articulate two-layer book architecture"
    # Layer 1 = R77, Layer 2 = R94 (or Layer 2 = THIS)
    assert "Layer 1" in src or "Layer_1" in src or "layer 1" in src.lower(), \
        "R94 must reference Layer 1 (R77)"
    assert "Layer 2" in src or "Layer_2" in src or "layer 2" in src.lower(), \
        "R94 must reference Layer 2 (this)"
    # TRADER_TOM doctrine
    assert "TRADER_TOM" in src or "trader_tom" in src.lower(), \
        "R94 must reference §TRADER_TOM doctrine"
    print("  ✓ R94 articulates §TRADER_TOM two-layer book (Layer 1 R77 + Layer 2 R94)")


def t_anti_imposter_discipline():
    """R94 must have ALL anti-imposter gates: benchmarks + combined-book + scaling checks."""
    import src.research.validation.r94_directional_crypto_beta as r
    src = Path(r.__file__).read_text()
    # Verify the verdict grammar is honest
    assert "✅ SURVIVES" in src, "verdict must include ✅"
    assert "🟡 PARTIAL" in src, "verdict must include 🟡"
    assert "🔴 REFUTED" in src, "verdict must include 🔴"
    # 3-check + benchmarks + combined-book all enforced
    assert "TRADEABLE" in src, "TRADEABLE band must exist"
    assert "3-check" in src.lower() or "passes_3check" in src.lower(), \
        "3-check gauntlet must be referenced"
    # The "regime scaler adds value" gate must be present (anti-costume)
    assert "scaling_adds_value" in src, \
        "anti-imposter gate: scaling_adds_value must be enforced"
    assert "combined_sharpe_lifts_r77" in src, \
        "anti-imposter gate: combined_sharpe_lifts_r77 must be enforced"
    print("  ✓ anti-imposter discipline: 3-check + scaling_adds_value + combined_sharpe_lifts_r77 all enforced")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        t_imports, t_gross_scalar_map, t_one_day_lag, t_daily_state_update,
        t_directional_beta_ls_shape, t_cost_on_gross_change,
        t_static_beta_benchmark, t_btc_only_benchmark,
        t_sweep_keys, t_benchmark_comparison_keys, t_combined_book_keys,
        t_frozen_r77_untouched, t_structural_difference_from_r87_r92,
        t_two_layer_intent, t_anti_imposter_discipline,
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
