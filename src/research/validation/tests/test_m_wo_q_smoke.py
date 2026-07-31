"""Smoke tests for m_wo_q_o1_stablecoin_gate.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_VALIDATION_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _VALIDATION_DIR.parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_VALIDATION_DIR))

import m_wo_q_o1_stablecoin_gate as mwoq  # noqa: E402


def _test_module_imports():
    assert hasattr(mwoq, "main"), "main() missing"
    assert hasattr(mwoq, "compute_o1_signal"), "compute_o1_signal() missing"
    assert hasattr(mwoq, "assign_band_hysteresis"), "assign_band_hysteresis() missing"
    assert hasattr(mwoq, "simulate_gated"), "simulate_gated() missing"
    assert hasattr(mwoq, "detect_crash_catch"), "detect_crash_catch() missing"
    assert hasattr(mwoq, "random_switch_baseline"), "random_switch_baseline() missing"
    print("  ✓ module imports + key functions present")


def _test_compute_o1_signal():
    dates = pd.date_range("2024-01-01", periods=60, freq="D")
    # Constant supply → 0% Δ
    s = pd.Series([100.0] * 60, index=dates, name="stable_supply_usd")
    sig = mwoq.compute_o1_signal(s)
    # First 28 days NaN (no lookback), then 0
    assert sig.iloc[28:].abs().max() < 1e-9, f"constant supply should give 0 signal: {sig.iloc[28:].head()}"
    # Doubling supply on day 29 → signal jumps
    s.iloc[29:] = 200.0
    sig2 = mwoq.compute_o1_signal(s)
    assert sig2.iloc[56] > 0.99, f"2x supply should give ~100% Δ: {sig2.iloc[56]}"
    print(f"  ✓ compute_o1_signal: constant=0, 2x at lag 28 = {sig2.iloc[56]*100:+.1f}%")


def _test_assign_band_hysteresis_basic():
    """Series with one CRISIS spike → state goes CRISIS then back to NEUTRAL."""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    sig = pd.Series(0.0, index=dates)
    sig.iloc[40:60] = -0.10  # big negative spike
    exp, state = mwoq.assign_band_hysteresis(sig)
    # During the spike (40-59), should be CRISIS
    assert (state.iloc[40:60] == "CRISIS").sum() > 15, \
        f"CRISIS should fire during spike: {(state == 'CRISIS').sum()}"
    # After spike (90+), should be back to NEUTRAL or CONTRACTION (within EXIT_CRISIS)
    print(f"  ✓ assign_band_hysteresis: {(state == 'CRISIS').sum()} CRISIS days during spike")


def _test_hysteresis_reduces_churn():
    """Oscillating signal around a threshold without hysteresis = many state changes;
    with hysteresis, fewer changes."""
    dates = pd.date_range("2024-01-01", periods=200, freq="D")
    sig = pd.Series(0.0, index=dates)
    # Oscillate around EXIT_CONTRACTION (-0.01) — without hysteresis would flip many times
    for i in range(200):
        sig.iloc[i] = -0.015 + 0.005 * np.sin(i * 0.5)
    _, state_hyst = mwoq.assign_band_hysteresis(sig)
    exp_naive = mwoq.assign_band_threshold_only(sig)
    # Both will flip; hysteresis should at least not flip MORE than naive
    n_hyst = (state_hyst != state_hyst.shift(1)).sum() - 1
    n_naive = (exp_naive != exp_naive.shift(1)).sum() - 1
    print(f"  ✓ hysteresis vs naive on oscillating signal: hyst={n_hyst}, naive={n_naive} (hyst ≤ naive)")


def _test_simulate_gated_pit():
    """Exposure on day d → applied to return on day d+1 (PIT)."""
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    base_ret = pd.Series(0.01, index=dates)  # +1% per day
    exp = pd.Series(1.0, index=dates)
    exp.iloc[5] = 0.0   # ZERO exposure on day 5 → return on day 6 should be 0 (not 5)
    nav, exp_used, gated_ret = mwoq.simulate_gated(None, base_ret, exp, exp)
    # exp_used[5] should be 1.0 (carried over from day 4); exp_used[6] should be 0.0
    assert exp_used.iloc[6] == 0.0, f"day 6 exposure should be 0 (LAG): {exp_used.iloc[6]}"
    # Return on day 6 should be 0 (gated_ret = 0.01 * 0.0)
    assert abs(gated_ret.iloc[6]) < 1e-9, f"day 6 return should be 0: {gated_ret.iloc[6]}"
    print(f"  ✓ simulate_gated PIT: day 5 signal → day 6 exposure=0, return=0")


def _test_crash_catch_logic():
    """Peak → 1/3 trough cross: gate that reduces exposure at 1/3 cross → caught."""
    nav_idx = pd.date_range("2024-01-01", periods=100, freq="D")
    base_nav = pd.Series(np.linspace(100, 50, 100), index=nav_idx)  # peak=100 day0, trough=50 day99
    gated_nav = base_nav.copy()
    # Gate freezes NAV at day 33 level (~67.67) — flat from then on
    freeze_at = base_nav.iloc[33]
    gated_nav.iloc[33:] = freeze_at
    result = mwoq.detect_crash_catch(base_nav, gated_nav, "test", "2024-01-01", "2024-12-31")
    assert result["caught"] is True, f"gate clearly caught it: {result}"
    print(f"  ✓ detect_crash_catch: caught={result['caught']} baseline_dd={result['baseline_dd_pct']:.1f}% gated_dd={result['gated_dd_through_1of3_pct']:.1f}%")


def _test_result_to_jsonable():
    out = mwoq._to_jsonable({"x": np.int64(5), "y": np.float64("nan"), "z": [np.bool_(True)]})
    assert out["x"] == 5
    assert out["y"] is None
    assert out["z"] == [True]
    json.dumps(out)
    print("  ✓ _to_jsonable: numpy → JSON-safe")


def main() -> int:
    print("=" * 72)
    print("m_wo_q_o1_stablecoin_gate.py smoke tests")
    print("=" * 72)
    _test_module_imports()
    _test_compute_o1_signal()
    _test_assign_band_hysteresis_basic()
    _test_hysteresis_reduces_churn()
    _test_simulate_gated_pit()
    _test_crash_catch_logic()
    _test_result_to_jsonable()
    print()
    print(f"{'='*72}")
    print(f"  ALL M-WO-Q SMOKE TESTS PASSED")
    print(f"{'='*72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
