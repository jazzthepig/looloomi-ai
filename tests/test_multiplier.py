"""T-063 / S-505:③ 推力 —— 规则、时点、敞口边界、现金腿与资金费、随机择时对照。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals.multiplier import (CASH_ANN, FUNDING_FALLBACK_ANN, LEVELS, apply_multiplier,  # noqa: E402
                                         build_rows, evaluate, multiplier, random_timing_pct)


def test_rule_and_unknown_state() -> None:
    assert multiplier(0.1, 0.2) == 1.3 and multiplier(-0.1, 0.8) == 0.7
    assert multiplier(0.1, 0.8) == 1.0 and multiplier(-0.1, 0.2) == 1.0
    assert multiplier(None, 0.2) == 1.0 and multiplier(float("nan"), 0.2) == 1.0, "读不到状态不能当成信号"


def test_exposure_never_leaves_0_7_to_1_3() -> None:
    idx = pd.date_range("2024-01-01", periods=5)
    r = pd.Series(0.01, index=idx)
    book = apply_multiplier(r, pd.Series([5.0, -2.0, 0.0, 1.3, 0.7], index=idx), pd.Series(dtype=float))
    assert book["m"].min() >= LEVELS[0] and book["m"].max() <= LEVELS[-1]


def test_cash_leg_and_funding_cost() -> None:
    idx = pd.date_range("2024-01-01", periods=3)
    r = pd.Series([0.0, 0.0, 0.0], index=idx)
    low = apply_multiplier(r, pd.Series(0.7, index=idx), pd.Series(dtype=float))
    assert np.allclose(low["ret"].iloc[1:], 0.3 * CASH_ANN / 365), "0.7 倍时 30% 在现金等价物上"
    high = apply_multiplier(r, pd.Series(1.3, index=idx), pd.Series(dtype=float))
    assert np.allclose(high["ret"].iloc[1:], -0.3 * FUNDING_FALLBACK_ANN / 365), "1.3 倍的多出部分付资金费"
    one = apply_multiplier(pd.Series([0.02, -0.01, 0.03], index=idx), pd.Series(1.0, index=idx), pd.Series(dtype=float))
    assert np.allclose(one["ret"], [0.02, -0.01, 0.03]), "1.0 倍 = ① 本身"


def test_switch_costs_10bps_per_unit_change() -> None:
    idx = pd.date_range("2024-01-01", periods=3)
    book = apply_multiplier(pd.Series(0.0, index=idx), pd.Series([1.0, 1.3, 1.3], index=idx),
                            pd.Series(0.0, index=idx))
    assert abs(book["cost"].iloc[1] - 0.3 * 10 / 1e4) < 1e-12 and book["cost"].iloc[2] == 0


def test_state_of_d_minus_1_sets_exposure_of_d() -> None:
    """时点:d 收盘的状态只能决定 d+1 的敞口。d 当天的收益不能用 d 的状态。"""
    idx = pd.date_range("2024-01-01", periods=4)
    state = pd.DataFrame({"dist_200": [0.1, 0.1, -0.1, -0.1], "vol_pct_3y": [0.2, 0.2, 0.8, 0.8]}, index=idx)
    core = pd.Series([0.0, 0.01, 0.01, 0.01], index=idx)
    rows, _ = build_rows(core, state, idx[-1])
    m = {r["d"]: r["m"] for r in rows if r["arm"] == "mult_v1_replay"}
    assert m["2024-01-01"] == 1.0, "第一天没有前一天的状态"
    assert m["2024-01-02"] == 1.3 and m["2024-01-03"] == 1.3, "1/1 与 1/2 的状态是上行平静"
    assert m["2024-01-04"] == 0.7, "1/3 收盘转为下行不平静,1/4 才降到 0.7"


def test_random_timing_has_no_edge_on_pure_noise() -> None:
    """零信号:m 与收益无关时,实测落在随机分布中段 —— 多个种子平均接近 0.5。"""
    idx = pd.date_range("2023-01-01", periods=400)
    pcts = []
    for seed in range(6):
        rng = np.random.default_rng(100 + seed)
        r = pd.Series(rng.normal(0, 0.03, len(idx)), index=idx)
        m = pd.Series(rng.choice(LEVELS, len(idx)), index=idx)
        pcts.append(random_timing_pct(r, m, pd.Series(dtype=float), n=200)["pct_vs_random"])
    assert 0.2 < float(np.mean(pcts)) < 0.8, pcts


def test_random_timing_finds_a_planted_edge() -> None:
    """埋信号:m 提前知道下一天的方向 —— 分位应接近 1。"""
    idx = pd.date_range("2023-01-01", periods=400)
    rng = np.random.default_rng(7)
    r = pd.Series(rng.normal(0, 0.03, len(idx)), index=idx)
    m = pd.Series(np.where(r.values > 0, 1.3, 0.7), index=idx)
    assert random_timing_pct(r, m, pd.Series(dtype=float), n=200)["pct_vs_random"] > 0.95


def test_evaluate_reports_three_windows_core_first() -> None:
    idx = pd.date_range("2023-01-02", "2026-10-07")
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.02, len(idx)), index=idx)
    m = pd.Series(1.0, index=idx)
    ev = evaluate(r, m, pd.Series(dtype=float), idx[-1])
    assert set(ev) == {"in_sample_2023_2024", "holdout_2025_to_inception", "forward"}
    assert "core" in ev["holdout_2025_to_inception"] and "mult" in ev["holdout_2025_to_inception"]


if __name__ == "__main__":
    print("── T-063 ③ 推力 ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
