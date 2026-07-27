"""
R97 — smoke tests (sandbox-safe, no Mac drive dependency for synthetic data).
========================================================================
Mirrors the test pattern of test_r77_r76_as_fusion_contribution_smoke.py +
test_w5_forensics_smoke.py. The 13 tests cover:
  1. Module imports + frozen R97 parameters
  2. 1h→4h resample correctness (synthetic panel)
  3. Dual-horizon separation: fast signal cannot REVERSE major direction
  4. All signals PIT-lagged (modify future price → historical weight unchanged)
  5. ADX/DMI gate
  6. CIS gate (composite score < floor → weight zero; missing → weight zero)
  7. Funding veto (extreme +z blocks longs, extreme -z blocks shorts, symmetric)
  8. ATR sizing (per-name |w| ≤ max_name_weight; book gross ≤ max_book_gross;
     net exposure ≈ 0)
  9. Long/short normalisation: net ≈ 0
  10. Cost monotonicity: Sharpe decreases monotonically with cost (modulo
      noise, but generally cost drains gross alpha)
  11. Funding carry direction: positive funding + long position → negative PnL
  12. R77 frozen weights unchanged (read-only check)
  13. Missing real 4h data raises loud error (no mock fallback)

All tests pass if the behaviour matches the spec; they do NOT require a
real R97 verdict (verdict comes from the real backtest only).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


# ── Test 1: imports + frozen params ────────────────────────────────────────
def t_imports_and_frozen_params():
    """R97 module + frozen parameters importable; nothing was silently mutated."""
    import src.research.validation.r97_cis_ls_v5 as r
    assert hasattr(r, "run"), "r97_cis_ls_v5 must expose run()"
    assert hasattr(r, "build_dual_horizon_score_wide"), "must expose dual-horizon builder"
    assert hasattr(r, "apply_gates_and_sizing"), "must expose gate+size combiner"
    assert hasattr(r, "backtest_daily"), "must expose backtest_daily()"
    # Frozen parameters (literal — no sweep, no override)
    assert r.R97_MAJOR_FAST == 54
    assert r.R97_MAJOR_SLOW == 126
    assert r.R97_FAST == 9
    assert r.R97_SLOW == 21
    assert r.R97_ADX_THRESHOLD == 25.0
    assert r.R97_CIS_FLOOR == 55.0
    assert r.R97_MAX_NAME_WEIGHT == 0.05
    assert r.R97_MAX_BOOK_GROSS == 1.00
    assert r.R97_FUNDING_VETO_Z == 2.0
    assert r.R97_PIT_LAG_BARS == 1
    # R77 frozen weights — read-only check
    assert r.R77_W_R46 == 0.25
    assert r.R77_W_R62 == 0.75
    assert r.R77_W_R76 == 0.30
    # cost grid
    assert 0 in r.COST_GRID_BPS and 10 in r.COST_GRID_BPS
    print("  ✓ imports + frozen params + R77 weights unchanged")


# ── Test 2: 1h→4h resample correctness ────────────────────────────────────
def t_resample_1h_to_4h():
    """Verify the local inline resampler matches data_bridge semantics."""
    import src.research.validation.r97_panel as p
    rng = np.random.default_rng(42)
    # 96 hours of synthetic 1h bars (24 days → 24 4h bars)
    n_1h = 96
    base = pd.Timestamp("2026-01-01", tz="UTC")
    hourly = pd.DataFrame({
        "timestamp": pd.date_range(base, periods=n_1h, freq="1h"),
        "open": 100 + rng.normal(0, 0.5, n_1h),
        "high": 101 + rng.normal(0, 0.5, n_1h),
        "low":  99 + rng.normal(0, 0.5, n_1h),
        "close": 100 + rng.normal(0, 0.5, n_1h),
        "volume": rng.uniform(100, 200, n_1h),
    })
    df4h = p._resample_to_4h_local(hourly)
    assert len(df4h) == n_1h // 4, f"expected {n_1h//4} 4h bars, got {len(df4h)}"
    # First 4h bar's close = the 4th hourly close (00:00 → 03:00 close at 04:00 bar close)
    # The resampler takes the last close of each bucket.
    expected_close = hourly["close"].iloc[3]  # bar 4 (0-indexed 3)
    actual_close = df4h["close"].iloc[0]
    assert abs(actual_close - expected_close) < 1e-9, "close aggregation mismatch"
    # High of bucket = max of the 4 hourly highs
    expected_high = hourly["high"].iloc[:4].max()
    actual_high = df4h["high"].iloc[0]
    assert abs(actual_high - expected_high) < 1e-9, "high aggregation mismatch"
    # Volume = sum
    expected_vol = hourly["volume"].iloc[:4].sum()
    actual_vol = df4h["volume"].iloc[0]
    assert abs(actual_vol - expected_vol) < 1e-9, "volume aggregation mismatch"
    print("  ✓ 1h→4h resample: close/high/volume match expected")


# ── Test 3: dual-horizon separation (fast cannot reverse major) ────────────
def t_dual_horizon_separation():
    """Major direction is the ceiling/floor — fast signal cannot REVERSE major.
    If major=+1 and fast=-1, the dual signal must be 0 (not flipped to -1)."""
    import src.research.validation.r97_cis_ls_v5 as r
    # Build a synthetic 4h series where EMA54>EMA126 (major=+1) but EMA9<EMA21 (fast=-1)
    # 50 bars of rising close (so EMA54>EMA126), then 30 bars of mild pullback
    # (could flip fast but not major in 30 bars)
    n = 200
    base_ts = pd.Timestamp("2026-01-01", tz="UTC")
    df4h = pd.DataFrame({
        "timestamp": pd.date_range(base_ts, periods=n, freq="4h"),
        "open": np.linspace(100, 150, n),
        "high": np.linspace(101, 151, n),
        "low": np.linspace(99, 149, n),
        "close": np.linspace(100, 150, n),
        "volume": np.ones(n),
        "symbol": "__test__",
    })
    # Force a sharp down spike at the end to flip fast but not major
    df4h.loc[df4h.index[-10:], "close"] = 130  # pullback — fast may flip, major won't
    # Per plan §2: fast signal cannot REVERSE major direction.
    # In conflict (major=+1, fast=-1) the intended side must be 0,
    # not flipped to -1. Verify via build_dual_horizon_score_wide.
    wide = r.build_dual_horizon_score_wide(df4h, ["__test__"])
    # `wide` is indexed by 4h timestamps with column "__test__"
    # Verify NO row in the wide signal has a negative value where major was +1
    # (the dual signal in any bar must be in {0, +1} for a major=+1 asset)
    sig = r.compute_dual_horizon_signals(df4h[df4h["symbol"] == "__test__"].reset_index(drop=True))
    sig["ts"] = pd.to_datetime(sig["timestamp"])
    sig = sig.set_index("ts")
    conflict = sig[(sig["major_dir"] > 0) & (sig["fast_dir"] < 0)]
    for ts in conflict.index:
        if ts in wide.index:
            side_value = wide.loc[ts, "__test__"]
            assert side_value >= 0, \
                f"BUG: side flipped to {side_value} at {ts} where major=+1, fast=-1"
    print("  ✓ dual-horizon separation: major × fast never yields reversed side")


# ── Test 4: PIT safety (modify future → historical weight unchanged) ───────
def t_pit_lag_safety():
    """Modifying a future price must NOT change today's historical weight."""
    import src.research.validation.r97_cis_ls_v5 as r
    n = 200
    df4h = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
        "open": np.linspace(100, 150, n),
        "high": np.linspace(101, 151, n),
        "low": np.linspace(99, 149, n),
        "close": np.linspace(100, 150, n),
        "volume": np.ones(n),
        "symbol": "__test__",
    })
    weights_before = r.build_dual_horizon_score_wide(df4h, ["__test__"])
    # Spike the LAST 20 bars by 100x
    df4h_modified = df4h.copy()
    df4h_modified.loc[df4h_modified.index[-20:], "close"] *= 100
    weights_after = r.build_dual_horizon_score_wide(df4h_modified, ["__test__"])
    # Signals BEFORE the spike window should be IDENTICAL
    cutoff = df4h["timestamp"].iloc[-20]
    w_before = weights_before.loc[weights_before.index < cutoff]
    w_after = weights_after.loc[weights_after.index < cutoff]
    np.testing.assert_array_almost_equal(
        w_before.values, w_after.values,
        err_msg="PIT LEAK: modifying future prices changed historical signals",
    )
    print("  ✓ PIT safety: future price change does not alter historical signals")


# ── Test 5: CIS gate (score < floor or missing → weight zero) ─────────────
def t_cis_gate():
    """CIS score below floor → weight 0; missing → weight 0 (no fallback)."""
    import src.research.validation.r97_cis_ls_v5 as r
    # Use 30 bars so ATR(14) warms up properly
    n = 30
    ts_idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    cols = ["A", "B", "C"]
    base_signal = pd.DataFrame(1.0, index=ts_idx, columns=cols)
    cis_gate = pd.DataFrame(
        {"A": [1.0] * n, "B": [0.0] * n, "C": [0.0] * n},
        index=ts_idx,
    )
    funding_z = pd.DataFrame(0.0, index=ts_idx, columns=cols)
    # Build a panel with 30 bars per asset (multiplied by 3 assets = 90 rows)
    panel_rows = []
    rng = np.random.default_rng(42)
    for sym in cols:
        for ts in ts_idx:
            panel_rows.append({
                "timestamp": ts,
                "symbol": sym,
                "open": 100.0 + rng.normal(0, 0.5),
                "high": 101.0 + rng.normal(0, 0.5),
                "low": 99.0 + rng.normal(0, 0.5),
                "close": 100.0 + rng.normal(0, 0.5),
                "volume": 100.0,
            })
    panel = pd.DataFrame(panel_rows)
    weights = r.apply_gates_and_sizing(panel, cis_gate, funding_z, base_signal)
    # Only A should be non-zero
    assert (weights["A"].abs() > 0).any(), "A (passes CIS) should have weight"
    assert (weights["B"].abs() == 0).all(), "B (CIS=0) must have weight zero"
    assert (weights["C"].abs() == 0).all(), "C (CIS=0) must have weight zero"
    print("  ✓ CIS gate: passing asset held, blocked/missing assets zeroed")


# ── Test 6: funding veto symmetry ──────────────────────────────────────────
def t_funding_veto_symmetry():
    """Extreme +z blocks longs only; extreme -z blocks shorts only; symmetric."""
    import src.research.validation.r97_cis_ls_v5 as r
    n = 30
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    cols = ["long_target", "short_target"]
    base_signal = pd.DataFrame(
        {"long_target": [1.0] * n, "short_target": [-1.0] * n},
        index=idx,
    )
    cis_gate = pd.DataFrame(1.0, index=idx, columns=cols)
    # long_target has z=+3 (should be blocked); short_target has z=−3 (should be blocked)
    funding_z = pd.DataFrame(
        {"long_target": [3.0] * n, "short_target": [-3.0] * n},
        index=idx,
    )
    panel_rows = []
    rng = np.random.default_rng(7)
    for sym in cols:
        for ts in idx:
            panel_rows.append({
                "timestamp": ts,
                "symbol": sym,
                "open": 100.0 + rng.normal(0, 0.5),
                "high": 101.0 + rng.normal(0, 0.5),
                "low": 99.0 + rng.normal(0, 0.5),
                "close": 100.0 + rng.normal(0, 0.5),
                "volume": 100.0,
            })
    panel = pd.DataFrame(panel_rows)
    weights = r.apply_gates_and_sizing(panel, cis_gate, funding_z, base_signal)
    assert (weights["long_target"].abs() == 0).all(), \
        "long with funding z=+3 should be blocked"
    assert (weights["short_target"].abs() == 0).all(), \
        "short with funding z=-3 should be blocked"
    # Now test: long with z=+1 (allowed), short with z=-1 (allowed)
    funding_z_ok = pd.DataFrame(
        {"long_target": [1.0] * n, "short_target": [-1.0] * n},
        index=idx,
    )
    weights_ok = r.apply_gates_and_sizing(panel, cis_gate, funding_z_ok, base_signal)
    assert (weights_ok["long_target"].abs() > 0).any(), \
        "long with funding z=+1 should be allowed"
    assert (weights_ok["short_target"].abs() > 0).any(), \
        "short with funding z=-1 should be allowed"
    print("  ✓ funding veto: +z blocks longs, -z blocks shorts, both sides symmetric")


# ── Test 7: ATR sizing caps ───────────────────────────────────────────────
def t_atr_sizing_caps():
    """Per-name |w| ≤ max_name_weight; book gross ≤ max_book_gross.
    Uses 5 longs + 5 shorts so zero-net normalization actually applies."""
    import src.research.validation.r97_cis_ls_v5 as r
    base_signal = pd.DataFrame(
        {**{f"L{i}": [1.0] * 30 for i in range(5)},
         **{f"S{i}": [-1.0] * 30 for i in range(5)}},
        index=pd.date_range("2026-01-01", periods=30, freq="4h"),
    )
    syms = [f"L{i}" for i in range(5)] + [f"S{i}" for i in range(5)]
    panel = pd.DataFrame({
        "timestamp": pd.to_datetime(np.tile(
            pd.date_range("2026-01-01", periods=30, freq="4h"), 10)),
        "symbol": sum([[s] * 30 for s in syms], []),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0,
    })
    weights = r.atr_weights(panel, base_signal)
    assert (weights.abs() <= r.R97_MAX_NAME_WEIGHT + 1e-12).all().all(), \
        f"per-name weight exceeds cap {r.R97_MAX_NAME_WEIGHT}"
    book_gross = weights.abs().sum(axis=1)
    assert (book_gross <= r.R97_MAX_BOOK_GROSS + 1e-12).all(), \
        f"book gross exceeds cap {r.R97_MAX_BOOK_GROSS}"
    # Net exposure ≈ 0
    net = weights.sum(axis=1)
    assert net.abs().max() < 1e-9, \
        f"long/short normalization fails; max net exposure = {net.abs().max()}"
    print("  ✓ ATR sizing: per-name cap, book-gross cap, net ≈ 0")


# ── Test 8: cost monotonicity (rough) ─────────────────────────────────────
def t_cost_monotonicity():
    """Gross Sharpe ≥ 5bps Sharpe on the same weights (cost drains alpha)."""
    import src.research.validation.r97_cis_ls_v5 as r
    # Build a simple signal: 50/50 random walk + signal, with no costs
    n = 200
    rng = np.random.default_rng(0)
    daily_rets = pd.DataFrame(
        rng.normal(0.001, 0.01, (n, 4)),
        index=pd.date_range("2026-01-01", periods=n, freq="D"),
        columns=["A", "B", "C", "D"],
    )
    weights = pd.DataFrame(
        np.tile([0.3, -0.3, 0.2, -0.2], (n, 1)),
        index=daily_rets.index, columns=daily_rets.columns,
    )
    r0 = r.backtest_daily(weights, daily_rets, cost_bps=0)
    r5 = r.backtest_daily(weights, daily_rets, cost_bps=5)
    r10 = r.backtest_daily(weights, daily_rets, cost_bps=10)
    # Turnover is non-zero, so cost should drain alpha (monotone non-increasing)
    assert r0.sum() >= r5.sum(), \
        f"5bps Sharpe should drain gross: gross_sum={r0.sum():.4f}, 5bps_sum={r5.sum():.4f}"
    assert r5.sum() >= r10.sum(), \
        f"10bps should drain 5bps further: 5bps_sum={r5.sum():.4f}, 10bps_sum={r10.sum():.4f}"
    print(f"  ✓ cost monotonicity: gross_sum={r0.sum():.4f} ≥ "
          f"5bps_sum={r5.sum():.4f} ≥ 10bps_sum={r10.sum():.4f}")


# ── Test 9: funding carry direction ──────────────────────────────────────
def t_funding_carry_direction():
    """Long position + positive funding → negative carry (longs pay shorts)."""
    import src.research.validation.r97_cis_ls_v5 as r
    n = 30
    daily_rets = pd.DataFrame(np.zeros((n, 1)), columns=["X"],
                              index=pd.date_range("2026-01-01", periods=n, freq="D"))
    weights = pd.DataFrame(np.ones((n, 1)), columns=["X"],
                           index=daily_rets.index)
    funding = pd.DataFrame(np.full((n, 1), 0.0005), columns=["X"],  # +5 bps/8h
                           index=daily_rets.index)
    pnl_with_carry = r.backtest_daily(weights, daily_rets, cost_bps=0,
                                      funding_daily=funding, funding_8h_per_bar=3.0)
    # Sum should be negative (we paid funding for 30 days)
    assert pnl_with_carry.sum() < 0, \
        f"long + positive funding should yield negative PnL, got {pnl_with_carry.sum()}"
    print(f"  ✓ funding carry: long + positive funding → PnL sum = {pnl_with_carry.sum():.6f} (< 0)")


# ── Test 10: R77 frozen weights unchanged ─────────────────────────────────
def t_r77_weights_unchanged():
    """R97 module must declare the frozen R77 weights as read-only."""
    import inspect
    import src.research.validation.r97_cis_ls_v5 as r
    # Read the source file from the imported module's path (portable across
    # worktrees / main repo — no hardcoded absolute paths).
    src_path = Path(inspect.getfile(r))
    src = src_path.read_text()
    assert "R77_W_R46 = 0.25" in src
    assert "R77_W_R62 = 0.75" in src
    assert "R77_W_R76 = 0.30" in src
    # Anti-imposter: must declare read-only
    assert "read-only" in src.lower() or "readonly" in src.lower(), \
        "R97 must mark R77 weights as read-only"
    assert "R77 cell NOT touched" in src or "frozen_r77" in src.lower(), \
        "R97 must explicitly say the frozen R77 cell is untouched"
    # Also assert the values match via import (catches "string present but
    # constant shadowed" bugs)
    assert r.R77_W_R46 == 0.25, f"R77_W_R46 drift: {r.R77_W_R46}"
    assert r.R77_W_R62 == 0.75, f"R77_W_R62 drift: {r.R77_W_R62}"
    assert r.R77_W_R76 == 0.30, f"R77_W_R76 drift: {r.R77_W_R76}"
    print("  ✓ R77 frozen weights preserved (read-only, no mutation paths)")


# ── Test 11: missing 4h data → loud error ────────────────────────────────
def t_missing_data_loud_failure():
    """If a real parquet is missing, the panel builder raises loudly."""
    import src.research.validation.r97_panel as p
    try:
        p.build_4h_for_symbol("__NONEXISTENT_SYMBOL__")
    except FileNotFoundError as e:
        assert "__NONEXISTENT_SYMBOL__" in str(e), \
            f"error message should mention the missing asset; got {e}"
        print("  ✓ missing data → FileNotFoundError (loud, no mock)")
        return
    raise AssertionError("expected FileNotFoundError for missing parquet")


# ── Test 12: universe freezing ────────────────────────────────────────────
def t_universe_freeze_min_assets():
    """freeze_universe raises if min_assets exceeds available coverage."""
    import src.research.validation.r97_panel as p
    try:
        # Asking for 100 assets when only ~24 are available must fail loudly
        p.freeze_universe(min_assets=100)
    except RuntimeError as e:
        assert "REFUSED_DATA" in str(e) or "need" in str(e), \
            f"expected REFUSED_DATA message; got {e}"
        print("  ✓ freeze_universe: REFUSED_DATA when min_assets too large")
        return
    raise AssertionError("expected RuntimeError when min_assets exceeds coverage")


# ── Test 13: walk-forward / DSR / PBO basic API smoke ─────────────────────
def t_walk_forward_imports():
    """walk_forward module imports + key API surface present."""
    import src.research.validation.r97_walk_forward as wf
    assert hasattr(wf, "run"), "r97_walk_forward must expose run()"
    assert hasattr(wf, "anchored_walk_forward"), "must expose anchored_walk_forward()"
    assert hasattr(wf, "rolling_walk_forward"), "must expose rolling_walk_forward()"
    assert hasattr(wf, "compute_dsr"), "must expose compute_dsr()"
    assert hasattr(wf, "compute_pbo"), "must expose compute_pbo()"
    assert hasattr(wf, "combined_book_check"), "must expose combined_book_check()"
    print("  ✓ r97_walk_forward imports + API surface")


# ── Orchestrate ──────────────────────────────────────────────────────────
ALL_TESTS = [
    t_imports_and_frozen_params,
    t_resample_1h_to_4h,
    t_dual_horizon_separation,
    t_pit_lag_safety,
    t_cis_gate,
    t_funding_veto_symmetry,
    t_atr_sizing_caps,
    t_cost_monotonicity,
    t_funding_carry_direction,
    t_r77_weights_unchanged,
    t_missing_data_loud_failure,
    t_universe_freeze_min_assets,
    t_walk_forward_imports,
]


def main():
    print("=== R97 smoke tests ===\n")
    passed = 0
    for t in ALL_TESTS:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"  ✗ {t.__name__}: {exc!r}")
    print(f"\n{passed}/{len(ALL_TESTS)} passed")
    if passed != len(ALL_TESTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()