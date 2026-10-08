"""T-070 / S-511:组合层 0–1 敞口 —— 旗标、敞口映射、时点、现金腿、对照与回放行。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals.portfolio_layer import (CASH_ANN, INCEPTION, REPLAY_ARM, V1CASH_ARM,  # noqa: E402
                                              apply_exposure, build_rows, exposure, flags_for, state_frame)


def test_flags_and_unknown_inputs_raise_nothing() -> None:
    f = flags_for({"vol_pct_3y": 0.2, "vratio": 0.6, "spy21": 0.03, "core30": -0.10, "maj_rel": -0.05, "fund7": 0.2})
    assert f == {"dead_market": -1, "decoupled": -1, "alt_froth": -1, "crowded": -1, "flushed": 0}
    assert exposure(f) == (-4, 0.0)
    none = flags_for({})
    assert all(v is None for v in none.values()) and exposure(none) == (0, 1.0), "读不到 ≠ 信号"
    flushed = flags_for({"fund7": -0.01, "maj_rel": -0.05})
    assert exposure(flushed) == (0, 1.0), "出清 +1 抵掉一个 −1"
    assert exposure({"a": -1})[1] == 0.5


def test_exposure_bounds_cash_leg_and_switch_cost() -> None:
    idx = pd.date_range("2024-01-01", periods=4)
    r = pd.Series(0.0, index=idx)
    b = apply_exposure(r, pd.Series([1.0, 0.0, 2.0, -1.0], index=idx))
    assert b["x"].tolist() == [1.0, 0.0, 1.0, 0.0], "敞口夹在 [0,1]"
    assert np.isclose(b["ret"].iloc[1], CASH_ANN / 365 - 1.0 * 10 / 1e4), "空仓那天拿现金等价物、付一次切换成本"


def test_state_uses_only_past_values_and_does_not_splice_sources() -> None:
    days = pd.date_range("2024-01-01", periods=260)
    st = pd.DataFrame({"vol_pct_3y": 0.2, "dist_200": 0.1, "style_rel_majors_30d": 0.0}, index=days)
    qv = pd.Series(100.0, index=days)
    spy = pd.DataFrame({"yfinance": pd.Series(np.linspace(100, 120, 260), index=days),
                        "eodhd": pd.Series(np.linspace(500, 600, 260), index=days)})
    core = pd.Series(0.0, index=days)
    s1 = state_frame(st, qv, spy, pd.Series(dtype=float), core)
    s2 = state_frame(st, qv.where(qv.index <= days[200], 1e9), spy, pd.Series(dtype=float), core)
    assert np.allclose(s1.loc[:days[200], "vratio"].dropna(), s2.loc[:days[200], "vratio"].dropna()), "改 d 之后的数据,d 之前不变"
    d = days[100]
    assert abs(s1.loc[d, "spy21"] - (spy.loc[d, "yfinance"] / spy["yfinance"].iloc[100 - 21] - 1)) < 1e-12, \
        "SPY 收益在同一个源内算,不拿 eodhd 的价去除 yfinance 的价"


def test_rows_apply_yesterdays_flags_and_write_three_arms() -> None:
    days = pd.date_range("2024-12-20", INCEPTION + pd.Timedelta(days=3))
    core = pd.Series(0.01, index=days)
    state = pd.DataFrame({"vol_pct_3y": 0.5, "dist_200": 0.1, "maj_rel": 0.0, "vratio": 1.0,
                          "spy21": 0.0, "core30": 0.0, "fund7": 0.05}, index=days)
    bad = days[10]
    state.loc[bad, ["vol_pct_3y", "vratio"]] = [0.1, 0.5]          # 死市
    state.loc[bad, "maj_rel"] = -0.1                              # 山寨热 ⇒ 分数 −2 ⇒ 空仓
    rows, ev = build_rows(core, state, days[-1])
    rep = {r["d"]: r for r in rows if r["arm"] == REPLAY_ARM}
    nxt = (bad + pd.Timedelta(days=1)).date().isoformat()
    assert rep[nxt]["x"] == 0.0 and rep[nxt]["score"] == -2, "d 的旗决定 d+1 的敞口"
    assert rep[bad.date().isoformat()]["x"] == 1.0, "当天的旗不作用于当天"
    arms = {r["arm"] for r in rows}
    assert {REPLAY_ARM, V1CASH_ARM, "pl_v2"} <= arms
    assert all(r["d"] > INCEPTION.date().isoformat() for r in rows if r["arm"] == "pl_v2"), "前向只从起点之后"
    assert "④" in ev["strategy4"] and ev["today"]["exposure_next_day"] == 1.0


def test_null_timing_is_centred_and_constant_control_is_reported() -> None:
    rng = np.random.default_rng(0)
    days = pd.date_range("2023-01-02", "2024-12-31")
    core = pd.Series(rng.normal(0.001, 0.03, len(days)), index=days)
    state = pd.DataFrame({"vol_pct_3y": rng.uniform(0, 1, len(days)), "vratio": rng.uniform(0.5, 1.2, len(days)),
                          "maj_rel": rng.normal(0, 0.04, len(days)), "spy21": 0.0, "core30": 0.0, "fund7": 0.05,
                          "dist_200": 0.1}, index=days)
    _, ev = build_rows(core, state, days[-1])
    w = ev["in_sample_2023_2024"]
    assert 0.03 < w["pct_vs_random"] < 0.97, "旗与收益无关时,择时分位不该在尾部"
    assert "same_exposure_constant" in w and w["avg_exposure"] < 1.0
