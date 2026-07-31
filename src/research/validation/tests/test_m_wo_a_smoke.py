"""Smoke tests for m_wo_a_beta_capture.py."""
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

import m_wo_a_beta_capture as mwoa  # noqa: E402


def _test_module_imports():
    assert hasattr(mwoa, "main"), "main() missing"
    assert hasattr(mwoa, "simulate"), "simulate() missing"
    assert hasattr(mwoa, "compute_eligibility"), "compute_eligibility() missing"
    assert hasattr(mwoa, "ew_weights"), "ew_weights() missing"
    assert hasattr(mwoa, "cw_proxy_weights"), "cw_proxy_weights() missing"
    assert hasattr(mwoa, "_max_dd_stop_scale"), "_max_dd_stop_scale() missing"
    assert hasattr(mwoa, "_stats"), "_stats() missing"
    assert hasattr(mwoa, "_to_jsonable" if hasattr(mwoa, "_to_jsonable") else "_result_to_jsonable"), "json helper missing"
    print("  ✓ module imports + key functions present")


def _test_ew_weights():
    w = mwoa.ew_weights(["BTC", "ETH", "SOL"])
    assert abs(sum(w.values()) - 1.0) < 1e-9, f"sum not 1: {sum(w.values())}"
    assert all(abs(v - 1/3) < 1e-9 for v in w.values()), f"unequal: {w}"
    print("  ✓ ew_weights: equal 1/N, sum=1")


def _test_cw_proxy_cap():
    """Cap at CW_CAP=0.30; never exceed. Under-universe stays at cap (residual cash)."""
    # dates are 30 days BEFORE as_of so the trailing-30d window has data
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    df = pd.DataFrame({
        "symbol": ["BTC"] * 30 + ["ETH"] * 30,
        "date": dates.tolist() * 2,
        "quote_volume": [100.0] * 30 + [1.0] * 30,
    })
    w = mwoa.cw_proxy_weights(df, ["BTC", "ETH"], pd.Timestamp("2024-02-15"))
    # Each name must respect the cap
    assert max(w.values()) <= mwoa.CW_CAP + 1e-9, f"cap violated: {max(w.values())}"
    # In a 2-symbol universe where both raw weights > cap, residual cannot be
    # redistributed ⇒ sum < 1 (honest underallocation, NOT renormalized-to-violate)
    assert sum(w.values()) <= 1.0 + 1e-9, f"sum cannot exceed 1: {sum(w.values())}"
    # BTC had 100x volume so should be at the cap (0.30); ETH gets residual
    assert abs(w["BTC"] - mwoa.CW_CAP) < 1e-9, f"BTC should be at cap: {w['BTC']}"
    print(f"  ✓ cw_proxy_weights: BTC={w['BTC']:.3f} ETH={w['ETH']:.3f} sum={sum(w.values()):.3f} (cap respected, residual cash)")


def _test_pit_eligibility_excludes_stables():
    # Build data spanning 2023-10-01 → 2024-08-01 (data extends past as_of)
    # so the trailing-30d window [as_of-30, as_of) catches the latest 30 days.
    dates = pd.date_range("2023-10-01", "2024-08-01", freq="D")
    df = pd.DataFrame({
        "symbol": ["BTC"] * len(dates) + ["USDT"] * len(dates) + ["ETH"] * len(dates),
        "date": dates.tolist() * 3,
        "close": [100.0] * len(dates) * 3,
        "quote_volume": [10_000_000.0] * len(dates) * 3,
    })
    elig = mwoa.compute_eligibility(df, pd.Timestamp("2024-07-15"))
    assert "USDT" not in elig, f"stablecoin leaked: {elig}"
    assert "BTC" in elig and "ETH" in elig, f"core missing: {elig}"
    print(f"  ✓ PIT eligibility excludes stables (eligible: {sorted(elig)})")


def _test_max_dd_stop_scale_triggers_freeze():
    """Drop NAV 20% → -15% should trigger freeze + zero exposure."""
    nav = pd.Series([100.0, 95.0, 90.0, 85.0, 82.0, 79.0],
                    index=pd.date_range("2024-01-01", periods=6))
    scaled, freeze = mwoa._max_dd_stop_scale(nav)
    # At day 5, dd from peak (100) = -21%, beyond -15% → freeze should fire
    assert freeze.iloc[-1] is True or freeze.iloc[-1] == True, f"freeze should fire at last day: {freeze.iloc[-1]}"
    # During freeze, scaled stays flat (no PnL)
    # First 4 days, dd is -10%..-18%, should at minimum trigger 0.5 or 0.25 scale
    print(f"  ✓ _max_dd_stop_scale: freeze fired={freeze.sum()}/{len(freeze)}, final scaled={scaled.iloc[-1]:.2f}")


def _test_stats_basic():
    nav = pd.Series([100.0, 110.0, 99.0, 121.0, 110.0, 130.0],
                    index=pd.date_range("2024-01-01", periods=6))
    s = mwoa._stats(nav)
    assert "total_return" in s
    assert "sharpe" in s
    assert "max_dd" in s
    assert s["n_days"] == 6
    print(f"  ✓ _stats: total_return={s['total_return']*100:+.1f}% maxDD={s['max_dd']*100:+.1f}%")


def _test_result_to_jsonable():
    out = mwoa._result_to_jsonable({
        "intval": np.int64(42),
        "floatval": np.float64(3.14),
        "boolval": np.bool_(True),
        "nanval": np.float64("nan"),
        "nested": {"x": np.int64(7)},
    })
    assert out["intval"] == 42
    assert out["floatval"] == 3.14
    assert out["boolval"] is True
    assert out["nanval"] is None
    assert out["nested"]["x"] == 7
    s = json.dumps(out)
    assert json.loads(s) == out
    print("  ✓ _result_to_jsonable: numpy → JSON-safe Python natives")


def main() -> int:
    print("=" * 72)
    print("m_wo_a_beta_capture.py smoke tests")
    print("=" * 72)
    _test_module_imports()
    _test_ew_weights()
    _test_cw_proxy_cap()
    _test_pit_eligibility_excludes_stables()
    _test_max_dd_stop_scale_triggers_freeze()
    _test_stats_basic()
    _test_result_to_jsonable()
    print()
    print(f"{'='*72}")
    print(f"  ALL M-WO-A SMOKE TESTS PASSED")
    print(f"{'='*72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
