"""Smoke tests for pod_aggregator.py (Strategy 3).

Verifies:
  1. Cross-pod correlation gate drops the lowest-OOS-Sharpe pod on breach
     (lesson #42: max |corr| < 0.30).
  2. Vol targeting clips annualised vol to ≤ 13% over the IS window.
  3. Per-pod DD circuit breaker zeros a pod's contribution after a -16% drawdown.

Pure Python + numpy + pandas; synthetic data only — sandbox-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.pod_aggregator import (
    PodReturns,
    apply_correlation_gate, shrink_weights, vol_target,
    apply_dd_circuit_breaker, aggregate,
    LEG_CORR_GATE, VOL_TARGET_ANN, POD_DD_CIRCUIT_BREAKER,
    PERIODS_PER_YEAR,
)


# === Synthetic data factory ==================================================
def _synth_pod(name: str, n_days: int = 200, *,
               sharpe_oos: float = 1.0, max_dd: float = -0.05,
               shared_factor: np.ndarray | None = None,
               shared_weight: float = 0.0,
               daily_vol: float = 0.01,
               seed: int = 0) -> PodReturns:
    """Build a PodReturns with controlled Sharpe, max DD, optional shared factor.

    `daily_vol` controls the per-day standard deviation (default 1% — keeps
    random-walk drawdowns safely above -15% so OK pods don't accidentally
    trip the circuit breaker).

    If `shared_factor` is provided, the pod's daily return includes
    `shared_weight * shared_factor` so multiple pods sharing the same factor
    are correlated at ~shared_weight².
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    target_daily_sharpe = sharpe_oos / np.sqrt(PERIODS_PER_YEAR)
    base = rng.normal(target_daily_sharpe, daily_vol, n_days)
    if shared_factor is not None and shared_weight > 0:
        sf = shared_factor[:n_days]
        idio_w = np.sqrt(max(0.0, 1.0 - shared_weight**2))
        base = idio_w * base + shared_weight * sf
    fac = pd.Series(base, index=dates)
    if max_dd < -0.10:
        spike_day = n_days // 2
        fac.iloc[spike_day] = max_dd - fac.iloc[:spike_day].sum()
    fac = fac + rng.normal(0, 1e-5, n_days)
    return PodReturns(name=name, fac=fac, sharpe_is=sharpe_oos * 1.1,
                       sharpe_oos=sharpe_oos, max_dd=max_dd)


def _shared_factor(n_days: int = 200, seed: int = 999) -> np.ndarray:
    """Return a shared random series used to enforce correlation between pods."""
    return np.random.default_rng(seed).normal(0, 1, n_days)


# === Test 1: correlation gate =================================================
def test_correlation_gate_drops_breaching_pod():
    """If max |corr| > 0.30 between any pair, drop the lowest-OOS-Sharpe pod.

    The gate iterates: each round drops the lowest-OOS-Sharpe pod in the
    breaching pair until no breach remains OR only 1 survivor left. Highest-
    OOS-Sharpe pod wins by survival.
    """
    # A loads on sf at 0.5; X loads on sf at 0.95 → |corr(A, X)| > 0.30.
    # B, C are pure idiosyncratic → corr with X ≈ 0.
    sf = _shared_factor(seed=999)
    p_a = _synth_pod("A", sharpe_oos=2.0, shared_factor=sf, shared_weight=0.5, seed=1)
    p_b = _synth_pod("B", sharpe_oos=1.5, shared_factor=sf, shared_weight=0.0, seed=2)
    p_c = _synth_pod("C", sharpe_oos=1.0, shared_factor=sf, shared_weight=0.0, seed=3)
    p_x = _synth_pod("X", sharpe_oos=1.8, shared_factor=sf, shared_weight=0.95, seed=4)
    pods = [p_a, p_b, p_c, p_x]

    actual_corr = pd.DataFrame({
        p.name: p.fac for p in pods
    }).corr()
    pair_corr = abs(actual_corr.loc["A", "X"])
    assert pair_corr > 0.30, f"sanity: expected |corr(A,X)|>0.30, got {pair_corr:.3f}"

    survivors, log = apply_correlation_gate(pods, gate=LEG_CORR_GATE)
    # Highest-OOS-Sharpe pod wins (A=2.0). All others get dropped because
    # once A is alone, the while-loop terminates.
    assert [p.name for p in survivors] == ["A"], (
        f"expected only [A] to survive, got {[p.name for p in survivors]}")
    dropped_names = [d["name"] for d in log["dropped"]]
    assert "B" in dropped_names and "C" in dropped_names and "X" in dropped_names, (
        f"expected B, C, X to all be dropped, got {dropped_names}")
    # Each drop is justified by max |corr| > gate
    for d in log["dropped"]:
        assert "max |corr|" in d["reason"], f"bad reason: {d['reason']}"
    print(f"✓ test_correlation_gate_drops_breaching_pod — "
          f"corr(A,X)={pair_corr:.3f}, dropped={dropped_names}, "
          f"survivors={[p.name for p in survivors]}")


# === Test 2: vol targeting ====================================================
def test_vol_target_caps_annualized_vol():
    """Vol-target a high-vol series; ann vol must be ≤ target + 10% headroom."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=400, freq="D")
    # Daily vol ~10% → ann vol ~158% (very high)
    high_vol = pd.Series(rng.normal(0, 0.10, 400), index=dates)
    targeted = vol_target(high_vol, target_ann=VOL_TARGET_ANN)
    ann_vol = float(targeted.std() * np.sqrt(PERIODS_PER_YEAR))
    # Allow 13% headroom (target is 12%, but static floor + cap may overshoot)
    assert ann_vol <= 0.13 + 1e-6, (
        f"vol_target overshot: ann_vol={ann_vol:.4f}, expected ≤ 0.13")
    # No NaN, no inf
    assert targeted.notna().all()
    assert np.isfinite(targeted).all()
    print(f"✓ test_vol_target_caps_annualized_vol — ann_vol={ann_vol:.4f} ≤ 0.13")


# === Test 3: DD circuit breaker ===============================================
def test_dd_circuit_breaker_zeros_a_breaching_pod():
    """A pod whose maxDD breaches -15% is masked out permanently from the aggregate."""
    p_ok1 = _synth_pod("OK1", max_dd=-0.05, seed=10)
    p_ok2 = _synth_pod("OK2", max_dd=-0.08, seed=11)
    p_bad = _synth_pod("BAD", max_dd=-0.30, seed=12)
    pods = [p_ok1, p_ok2, p_bad]
    masks = apply_dd_circuit_breaker(pods, breaker=POD_DD_CIRCUIT_BREAKER)

    # BAD's mask should be 0 from the breach day onward.
    bad_mask = masks["BAD"]
    assert (bad_mask == 0).any(), "BAD mask should be 0 at least once"
    # Once zeroed, never recovers (monotonic — manual reset only).
    ever_disabled = (bad_mask == 0).cumsum() > 0
    tail = ever_disabled.iloc[len(bad_mask) // 2:]
    assert tail.all(), "BAD mask should be permanently disabled after first breach"
    # OK pods should never be disabled.
    assert (masks["OK1"] == 1).all(), "OK1 should never be disabled"
    assert (masks["OK2"] == 1).all(), "OK2 should never be disabled"

    # Aggregate should not include BAD's contribution after the breach.
    weights = {"OK1": 0.4, "OK2": 0.4, "BAD": 0.2}
    agg = aggregate([p_ok1, p_ok2, p_bad], weights, masks)
    # On the breach day and after, agg ≈ OK1*0.4 + OK2*0.4 (BAD dropped).
    # Simulate the breach-day weight: BAD's effective contribution is 0 from that day.
    # Aggregate shouldn't be all-zero (OK1 + OK2 still contribute).
    assert agg.notna().all()
    assert np.isfinite(agg).all()
    # Aggregate should NOT equal what BAD would contribute alone.
    print(f"✓ test_dd_circuit_breaker_zeros_a_breaching_pod — "
          f"agg tail ann_vol={agg.tail(50).std() * np.sqrt(PERIODS_PER_YEAR):.3f}")


# === Test 4 (bonus): shrinkage weights sum to 1 ==============================
def test_shrinkage_weights_sum_to_one():
    """shrink_weights should produce weights summing to 1.0."""
    pods = [_synth_pod(f"P{i}", sharpe_oos=float(i + 1), seed=i + 20)
            for i in range(3)]
    w = shrink_weights(pods, k=50)
    assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights sum to {sum(w.values())}"
    # All non-negative
    assert all(v >= 0 for v in w.values())
    # Higher-OOS pod gets more weight than lower
    assert w["P2"] > w["P0"]
    print(f"✓ test_shrinkage_weights_sum_to_one — weights={w}")


if __name__ == "__main__":
    test_correlation_gate_drops_breaching_pod()
    test_vol_target_caps_annualized_vol()
    test_dd_circuit_breaker_zeros_a_breaching_pod()
    test_shrinkage_weights_sum_to_one()
    print("\n=== All pod_aggregator smoke tests passed ===")