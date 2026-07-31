"""Smoke tests for r100_directional_trend_overlay.py.

Per project discipline (§REFUTATION_LEDGER + CLAUDE.md "every sleeve has a smoke"):
verify that the module imports, the helper functions compute correct values on
synthetic data, and the result dataclass is JSON-serializable.

Run:
  python3 src/research/validation/tests/test_r100_smoke.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

_VALIDATION_DIR = Path(__file__).resolve().parents[1]   # .../validation
_REPO_ROOT = _VALIDATION_DIR.parents[2]                  # .../looloomi-ai
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_VALIDATION_DIR))

import r100_directional_trend_overlay as r100  # noqa: E402


def _test_module_imports():
    assert hasattr(r100, "main"), "main() missing"
    assert hasattr(r100, "load_11yr_panel"), "load_11yr_panel() missing"
    assert hasattr(r100, "compute_momentum_z"), "compute_momentum_z() missing"
    assert hasattr(r100, "directional_weights"), "directional_weights() missing"
    assert hasattr(r100, "smooth_regime_tilt"), "smooth_regime_tilt() missing"
    assert hasattr(r100, "vol_target_scale"), "vol_target_scale() missing"
    assert hasattr(r100, "apply_rebalance"), "apply_rebalance() missing"
    assert hasattr(r100, "apply_caps"), "apply_caps() missing"
    assert hasattr(r100, "gauntlet_3check"), "gauntlet_3check() missing"
    assert hasattr(r100, "_result_to_jsonable"), "_result_to_jsonable() missing"
    print("  ✓ module imports + key functions present")


def _test_smooth_regime_tilt():
    """smooth_regime_tilt: P≥0.65 → 1.5x; P≤0.35 → 0.5x; else 1.0x."""
    # Build 90-day series with BTC 30d return first +6% then -6%
    # (band threshold is +5.17%/-5.17% for sigmoid(12x) at P=0.65/0.35)
    closes_list = []
    for i in range(90):
        if i < 30:
            closes_list.append(100.0 * (1.06 ** (i / 30.0)))  # up 6% over first 30d
        elif i < 60:
            closes_list.append(closes_list[-1] * 1.001)  # flat
        else:
            # last 30d: drop ~6% from peak
            peak = closes_list[59]
            closes_list.append(peak * (0.94 ** ((i - 59) / 30.0)))  # down 6% over 30d
    dates = pd.date_range("2024-01-01", periods=90, freq="D")
    close2 = pd.DataFrame({"BTC": closes_list}, index=dates)
    tilt = r100.smooth_regime_tilt(close2)
    # First valid 30-day pct_change is at i=30 (i<30 is NaN).
    # i=30: close[30]/close[0] ≈ 105.94/100 = +5.94% → sigmoid(12*0.0594) ≈ 0.671 → TILT_HIGH 1.5
    # i=89: close[89]/close[59] = (close[59]*0.94)/close[59] ≈ -6.00% → sigmoid(-0.72) ≈ 0.327 → TILT_LOW 0.5
    # Middle 30d: ~flat → P≈0.5 → TILT_MID 1.0
    assert tilt.iloc[30] == 1.5, f"i=30 (BTC up ~5.94%) should be TILT_HIGH 1.5: {tilt.iloc[30]}"
    assert tilt.iloc[89] == 0.5, f"i=89 (BTC down ~6%) should be TILT_LOW 0.5: {tilt.iloc[89]}"
    # Middle period should be 1.0 most of the time
    assert 1.0 in tilt.iloc[35:55].unique(), "middle period should have TILT_MID 1.0"
    print("  ✓ smooth_regime_tilt bands correct: P≥0.65→1.5x, P≤0.35→0.5x, else 1.0x")


def _test_directional_weights_quartile_split():
    """directional_weights: top 25% LONG, bottom 25% SHORT, gross=1.0 normalized."""
    # 8 symbols, simple z scores
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    # Day 0: sym A=+2 (top), sym B=+1, sym C=+0.5, sym D=+0.1 (rest), sym E=-0.1, sym F=-0.5, sym G=-1, sym H=-2 (bottom)
    z = pd.DataFrame({
        "A": [2.0] * 10, "B": [1.0] * 10, "C": [0.5] * 10, "D": [0.1] * 10,
        "E": [-0.1] * 10, "F": [-0.5] * 10, "G": [-1.0] * 10, "H": [-2.0] * 10,
    }, index=dates)
    w = r100.directional_weights(z)
    # Top 25% of 8 = 2 symbols: A, B (LONG)
    # Bottom 25% = 2 symbols: G, H (SHORT)
    assert w["A"].iloc[0] > 0, "A should be LONG (top 25%)"
    assert w["B"].iloc[0] > 0, "B should be LONG (top 25%)"
    assert w["G"].iloc[0] < 0, "G should be SHORT (bottom 25%)"
    assert w["H"].iloc[0] < 0, "H should be SHORT (bottom 25%)"
    assert w["C"].iloc[0] == 0, "C should be 0 (middle 50%)"
    assert w["D"].iloc[0] == 0, "D should be 0 (middle 50%)"
    # gross should be 1.0
    gross = w.iloc[0].abs().sum()
    assert abs(gross - 1.0) < 1e-9, f"gross should be 1.0: {gross}"
    # A and B should have equal positive weight: each = 0.5 / 2 = 0.25
    assert abs(w["A"].iloc[0] - 0.25) < 1e-9, f"A weight: {w['A'].iloc[0]}"
    # G and H should have equal negative weight: each = -0.25
    assert abs(w["H"].iloc[0] - (-0.25)) < 1e-9, f"H weight: {w['H'].iloc[0]}"
    print("  ✓ directional_weights: top/bottom 25% correct, gross=1.0 normalized")


def _test_apply_caps():
    """apply_caps: per-name 5% cap, book gross 100%."""
    # All-1 weights should be capped to 5% per name; then scaled to 100% gross
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    w = pd.DataFrame({f"S{i}": [1.0] * 5 for i in range(20)}, index=dates)
    capped = r100.apply_caps(w)
    # Per-name max should be 5%
    assert capped.abs().max().max() <= r100.MAX_NAME_WEIGHT + 1e-9, \
        f"per-name cap violated: max={capped.abs().max().max()}"
    # Book gross should be ≤ 100%
    for i in range(len(capped)):
        gross = capped.iloc[i].abs().sum()
        assert gross <= r100.MAX_BOOK_GROSS + 1e-9, f"day {i} gross {gross} > 100%"
    print("  ✓ apply_caps: per-name ≤5%, book gross ≤100% enforced")


def _test_apply_rebalance():
    """apply_rebalance: weight held for rebal_days then refreshed."""
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    w = pd.DataFrame({
        "A": [1.0, 0, 0, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 0, 0],
        "B": [0, 0, 0, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 0, 0],
    }, index=dates)
    reb = r100.apply_rebalance(w, rebal_days=7)
    # Days 0-6: weight should be A=1.0 (rebal day 0)
    # Days 7-13: weight should be A=0.5, B=0.5 (rebal day 7)
    assert reb["A"].iloc[0] == 1.0
    assert reb["A"].iloc[6] == 1.0
    assert reb["A"].iloc[7] == 0.5
    assert reb["B"].iloc[7] == 0.5
    print("  ✓ apply_rebalance: weights held for 7d then refreshed")


def _test_gauntlet_3check_positive():
    """gauntlet_3check: positive P&L with low vol passes gross_t but may fail M-WO-1."""
    # Synthetic 200-day positive P&L with consistent positive drift
    dates = pd.date_range("2024-01-01", periods=200, freq="D")
    np.random.seed(42)
    pnl = pd.Series(np.random.normal(0.01, 0.05, 200), index=dates)
    weights = pd.DataFrame({"A": [1.0] * 200, "B": [-1.0] * 200}, index=dates)
    g3 = r100.gauntlet_3check(pnl, weights)
    # gross_t should be positive (>0 with low std)
    assert g3["gross_t"] > 0, f"gross_t should be positive: {g3['gross_t']}"
    assert g3["max_dd"] <= 0, f"maxDD should be ≤ 0: {g3['max_dd']}"
    assert "cycle_t_stats" in g3
    assert "m_wo1" in g3
    print(f"  ✓ gauntlet_3check on positive P&L: gross_t={g3['gross_t']:.3f}, maxDD={g3['max_dd']*100:+.2f}%")


def _test_json_serializable():
    """_result_to_jsonable converts numpy types to JSON-serializable."""
    from dataclasses import dataclass
    @dataclass
    class FakeResult:
        cost_bps: int
        gross_t: float
        passes_3check: bool
        cycle_t_stats: dict
        m_wo1: dict
    r = FakeResult(
        cost_bps=5,
        gross_t=np.float64(1.234),
        passes_3check=np.bool_(True),
        cycle_t_stats={"C1": {"t_stat": np.float64(0.5), "ann_pct": np.float64(2.0)}},
        m_wo1={"n_episodes": np.int64(3), "pooled_t": np.float64(1.5)},
    )
    out = r100._result_to_jsonable(r)
    # All values should be JSON-serializable
    s = json.dumps(out)
    parsed = json.loads(s)
    assert parsed["cost_bps"] == 5
    assert parsed["passes_3check"] is True
    assert parsed["gross_t"] == 1.234
    assert parsed["m_wo1"]["n_episodes"] == 3
    print("  ✓ _result_to_jsonable: numpy types → JSON-serializable Python natives")


def main() -> int:
    print("=" * 72)
    print("r100_directional_trend_overlay.py smoke tests")
    print("=" * 72)
    _test_module_imports()
    _test_smooth_regime_tilt()
    _test_directional_weights_quartile_split()
    _test_apply_caps()
    _test_apply_rebalance()
    _test_gauntlet_3check_positive()
    _test_json_serializable()
    print()
    print(f"{'='*72}")
    print(f"  ALL R100 SMOKE TESTS PASSED")
    print(f"{'='*72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())