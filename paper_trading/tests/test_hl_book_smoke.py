"""S-412 hl_book 守卫 —— 离线,合成数据,不联网。

三条对应三个真实会出错的形状:
1. Tom 的硬规则「永不给亏损仓位加仓」必须在代码里,不能交给模型
2. 换手限制:变化小于不动带就不交易,否则每周都在为噪音付成本
3. Jev 臂走完「匿名 → 打乱编号 → 解析回映射」整条路径后,喂机械答案必须 ≡ 机械 Tom;
   编号映射错一位,就是把 A 币的判断用在 B 币上,而结果看起来完全正常
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from paper_trading import hl_book as hb
from paper_trading.jev_replay_s412 import FakeJev, simulate


def _synthetic():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2022-01-01", "2024-12-31", freq="D")
    px = pd.DataFrame({c: 100 * np.exp(np.cumsum(rng.normal(0.0005 * (i - 1), 0.03, len(idx))))
                       for i, c in enumerate(["BTC", "ETH", "SOL"])}, index=idx)
    fd = pd.DataFrame(rng.normal(0.0003, 0.0002, px.shape), index=idx, columns=px.columns)
    return px, fd


def test_never_add_to_losers() -> None:
    f = {"ret_20d": .1, "ret_60d": .2, "ret_120d": .3, "vol_30d_ann": .5,
         "dist_from_ma200": .2, "drawdown_from_200d_high": -.05, "funding_7d_ann": .1}
    ans = hb.Answers({"X": True}, {"X": False}, {"X": False}, "press")
    losing = hb.tom_targets({"X": f}, ans, {"X": {"w": 1.0, "ret_since": -0.03}})
    winning = hb.tom_targets({"X": f}, ans, {"X": {"w": 1.0, "ret_since": 0.03}})
    assert losing["X"] == 1.0, f"亏损仓位被加仓:{losing}"
    assert winning["X"] == 1.5, f"盈利且确认的仓位没有加仓:{winning}"
    print("  ✓ 永不给亏损仓位加仓;盈利且趋势确认时才加")


def test_turnover_band() -> None:
    out = hb.apply_turnover_limits({"A": 0.8, "B": 0.3}, {"A": 0.7, "B": 1.0})
    assert out == {"A": 0.7, "B": 0.3}, out
    print("  ✓ 变化 < 0.2 不交易,≥ 0.2 才调")


def test_jev_path_equals_mechanical() -> None:
    import paper_trading.jev_replay_s412 as rp
    px, fd = _synthetic()
    old = rp.START
    rp.START = pd.Timestamp("2022-09-05")
    try:
        W, *_ = simulate(px, fd, "mech", FakeJev(), 10_000)
    finally:
        rp.START = old
    assert np.allclose(W["JEV_tom"].fillna(0).values, W["MECH_tom"].fillna(0).values), \
        "Jev 臂走完匿名/打乱/解析路径后与机械 Tom 不一致 —— 编号映射有错"
    print("  ✓ Jev 臂(匿名 → 打乱 → 解析)喂机械答案 ≡ 机械 Tom")


def test_daily_cycle_equals_replay() -> None:
    """S-413:每日流程 `hl_book_daily.compute_row` 逐日推进,必须和回放算出同一条收益序列。
    唯一允许的差别是起点那天的建仓成本 —— 每日流程收它,回放不收(更接近实盘)。"""
    import json
    import paper_trading.jev_replay_s412 as rp
    from src.data.signals import hl_book_daily as hd
    px, fd = _synthetic()
    start = pd.Timestamp("2022-09-05")
    old = rp.START
    rp.START = start
    try:
        W, N, *_ = simulate(px, fd, "none", None, 0)
    finally:
        rp.START = old
    replay, _ = rp.pnl(W["MECH_tom"], N, px, fd)
    rows = {}
    for d in pd.date_range(start, px.index[-1]):
        row = hd.compute_row(hb, px, fd, d, rows.get(d - pd.Timedelta(days=1)),
                             rows.get(d - pd.Timedelta(days=2)), lambda *a: (_ for _ in ()).throw(RuntimeError("no jev")))
        rows[d] = json.loads(json.dumps(row))
    live = pd.Series({d: r["ret"]["MECH_tom"] for d, r in rows.items()})
    both = pd.concat([replay, live], axis=1).dropna().iloc[3:]
    assert np.allclose(both.iloc[:, 0], both.iloc[:, 1], atol=1e-7), \
        f"每日流程与回放的收益不一致,最大差 {(both.iloc[:, 0] - both.iloc[:, 1]).abs().max():.2e}"
    assert all(r["jev_error"] for r in rows.values() if r["is_decision"]), "Jev 失败必须写进 jev_error"
    print("  ✓ 每日流程逐日推进 ≡ 回放(起点建仓成本除外);Jev 失败 fail-closed 且有记录")


if __name__ == "__main__":
    print("── S-412/S-413 hl_book 守卫 ──")
    test_never_add_to_losers()
    test_turnover_band()
    test_jev_path_equals_mechanical()
    test_daily_cycle_equals_replay()
    print("\n✅ 4/4 passed")
