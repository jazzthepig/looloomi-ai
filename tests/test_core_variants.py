"""T-072 / S-517:① 的候选定义 —— 上限、动量与退回、时点、漂移与成本、随机权重对照。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals.core_variants import (COST_BPS, build, capped, momentum, simulate,  # noqa: E402
                                            target_weights)


def _panel(n=500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-09-01", periods=n)
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (n, 5)), axis=0)), index=idx,
                      columns=["BTC", "ETH", "SOL", "ADA", "XRP"])
    mc = pd.DataFrame({"BTC": 6e11, "ETH": 2e11, "SOL": 5e10, "ADA": 1e10, "XRP": 3e10}, index=idx)
    return px, mc


def test_cap_holds_and_uncapped_is_proportional() -> None:
    w = capped({"BTC": 6, "ETH": 2, "SOL": 1, "ADA": 1}, 0.4)
    assert abs(sum(w.values()) - 1) < 1e-9 and max(w.values()) <= 0.4 + 1e-9
    px, mc = _panel()
    d = px.index[200]
    u = target_weights("cap_uncapped", d, px, mc, list(px.columns))
    assert abs(u["BTC"] - 6e11 / 8.9e11) < 1e-9


def test_momentum_uses_only_yesterday_and_falls_back_when_nothing_is_up() -> None:
    px, mc = _panel()
    d = px.index[300]
    m1 = momentum(px, d, list(px.columns))
    px2 = px.copy()
    px2.loc[d:] = px2.loc[d:] * 5
    assert momentum(px2, d, list(px.columns)) == m1, "d 当天及之后的价格不能进 d 的权重"
    down = px.copy()
    down.loc[:d - pd.Timedelta(days=2)] = 1e6
    w = target_weights("mom90", d, down, mc, list(px.columns))
    assert w == target_weights("cap_uncapped", d, down, mc, list(px.columns)), "没有一个上涨 ⇒ 退回市值加权"


def test_simulate_drift_and_cost() -> None:
    idx = pd.date_range("2024-01-01", periods=3)
    rets = pd.DataFrame({"A": [0.10, 0.0, 0.0], "B": [0.0, 0.0, 0.0]}, index=idx)
    out = simulate(rets, {idx[0]: {"A": 0.5, "B": 0.5}, idx[2]: {"A": 0.5, "B": 0.5}})
    assert abs(out.iloc[0] - (0.05 - 1.0 * COST_BPS / 1e4)) < 1e-12, "第一天:建仓换手 1.0"
    drift_a = 0.55 / 1.05
    assert abs(out.iloc[2] - (-abs(0.5 - drift_a) * 2 * COST_BPS / 1e4)) < 1e-12, "再平衡只付漂移部分的换手"


def test_build_reports_all_arms_and_random_baseline_on_noise() -> None:
    px, mc = _panel(n=900, seed=3)
    rows, ev = build(px, mc, px.index[-1], n_random=60)
    arms = {r["arm"] for r in rows}
    assert arms == {"cap_c40", "cap_uncapped", "mom90", "mom90_x_cap", "btc", "dual_mom"}
    w = ev["in_sample_2023_2024"]
    assert "random_weights" in w and 0.0 <= w["mom90"]["pct_vs_random"] <= 1.0
    assert ev["latest_weights"]["btc"] == {"BTC": 1.0}


def test_dual_momentum_switches_on_yesterdays_btc_trend_and_pays_for_it() -> None:
    from src.data.signals.core_variants import CASH_ANN, dual_momentum
    idx = pd.date_range("2024-01-01", periods=400)
    btc = pd.Series(np.r_[np.linspace(100, 50, 380), np.full(20, 50.0)], index=idx)
    mom = pd.Series(0.01, index=idx)
    out = dual_momentum(mom, btc, None)
    assert abs(out.iloc[10] - 0.01) < 1e-12, "信号读不到 ⇒ 不切"
    late = out.iloc[-1]
    assert abs(late - CASH_ANN / 365) < 1e-9, "BTC 一年跌 ⇒ 防守腿(没有 ④ 时全是现金)"
    btc2 = btc.copy(); btc2.iloc[-1] = 1e9
    assert abs(dual_momentum(mom, btc2, None).iloc[-1] - late) < 1e-12, "当天的价格不影响当天的仓位"
