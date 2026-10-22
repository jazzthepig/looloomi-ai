"""T-181 / S-597 红测:篮子权重的两条机制 —— ① 两次调仓之间按价格漂移、L 臂调仓日不回等权;
② LC 的砍(从进篮子那天的价格跌 ≥ 25% ⇒ 下周收盘卖出、钱按当前权重分给还在篮子里的、到下次调仓前不回来)。

跑法:`python3 -m pytest docs/research/t181_test.py -q` —— 红测先写,实现后补。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import ab_test  # noqa: E402,F401
from docs.research.t181_s597_crypto15 import (  # noqa: E402
    apply_cut, cap_weights, cuts_at, drift_weights, rebalance_r, rebalance_l, simulate,
)


# ---------------------------------------------------------------- ① 权重漂移

def test_drift_is_price_weighted_normalised():
    """一周后 w_i' = w_i(1+r_i) / Σ_j w_j(1+r_j) —— 不是等权,也不是各按原价等分。"""
    w = np.array([0.5, 0.3, 0.2])
    r = np.array([0.10, 0.0, -0.50])           # 赢家 +10%,输家 −50%
    w2 = drift_weights(w, r)
    raw = w * (1.0 + r)
    assert w2 == pytest.approx(raw / raw.sum())
    # 赢家权重上升、输家权重塌缩
    assert w2[0] > w[0] and w2[2] < w[2]
    assert w2.sum() == pytest.approx(1.0)


def test_drift_zero_return_is_identity():
    w = np.array([0.6, 0.25, 0.15])
    assert drift_weights(w, np.zeros(3)) == pytest.approx(w)


def test_l_rebalance_does_not_reset_survivors_to_equal_weight():
    """L 臂:调仓日只换成分 —— 老成员按比例让出 1/N 给新进的,自己的权重仍彼此不等。"""
    # 3 周后老成员权重已被价格漂移打歪
    w = np.array([0.55, 0.30, 0.15])
    shares = {"A": 0.55, "B": 0.30, "C": 0.15}
    entry = {"A": 0, "B": 0, "C": 0}
    new_shares, entry, turnover = rebalance_l(
        shares, entry, basket={"A", "B", "D"}, n_slots=4, price=1.0, nav=1.0, t=3)
    vals = {k: v * 1.0 for k, v in new_shares.items()}
    # A、B 幸存共拿 nav × (1 − 1/4) = 0.75(离场的 C 的 0.15 也在里面),按各自比例缩
    shrink = 0.75 / 0.85
    assert vals["A"] == pytest.approx(0.55 * shrink)
    assert vals["B"] == pytest.approx(0.30 * shrink)
    assert vals["C"] == 0.0                                   # 离场的清零
    assert vals["D"] == pytest.approx(0.25)                   # 新进的各拿 1/N
    # 幸存者仍然不是等权(0.4125 vs 0.225),这正是 L 与 R 的区别
    assert vals["A"] != pytest.approx(vals["B"])
    assert turnover > 0.0
    # 老成员的 entry 不被重置(LC 的“进篮子那天的价格”要跨调仓日存活)
    assert entry["A"] == 0 and entry["B"] == 0
    assert entry["D"] == 3


def test_r_rebalance_resets_to_equal_weight():
    w = {"A": 0.55, "B": 0.30, "C": 0.15}
    shares, entry, turnover = rebalance_r(
        w, {"A": 0, "B": 0, "C": 0}, basket={"A", "B", "D"}, n_slots=4, price=1.0, nav=1.0, t=3)
    assert shares["A"] == pytest.approx(0.25)
    assert shares["B"] == pytest.approx(0.25)
    assert shares["D"] == pytest.approx(0.25)
    assert shares["C"] == 0.0
    assert turnover > 0.0


# ---------------------------------------------------------------- ② LC 的砍

def test_apply_cut_redistributes_by_current_weight():
    """砍掉一个成员 ⇒ 它的钱按当前权重分给还在篮子里的(不是补成等权)。"""
    w = {"A": 0.50, "B": 0.30, "C": 0.20}
    out = apply_cut(w, cut={"B"})
    # B 的 0.30 按 A:C 的 0.50:0.20 分回去
    assert out == pytest.approx({"A": 0.50 + 0.30 * 0.50 / 0.70,
                                 "B": 0.0, "C": 0.20 + 0.30 * 0.20 / 0.70})
    assert sum(out.values()) == pytest.approx(1.0)
    assert out["A"] != pytest.approx(out["C"])               # 按权重,没回等权


def test_cuts_at_needs_25pct_and_uses_entry_day_price():
    """跌 ≥ 25% 才砍;跌 24% 不砍;并且是从**进篮子那天**的价格算,不是从当周。"""
    P = np.array([
        [100.0, 100.0],   # 第 0 周:A 进篮(entry=0),价格 100
        [90.0, 100.0],
        [80.0, 100.0],
        [76.0, 100.0],    # −24% ⇒ 不砍
        [75.0, 100.0],    # −25% ⇒ 砍
    ])
    entry = {0: 0, 1: 0}
    assert cuts_at(P, [0, 1], entry, 3) == set()
    assert cuts_at(P, [0, 1], entry, 4) == {0}
    # entry 是第 3 周(当周)⇒ 阈值贴着当周价格,75 不砍
    assert cuts_at(P, [0, 1], {0: 3, 1: 3}, 4) == set()


def test_lc_cut_does_not_reenter_before_next_rebalance():
    """触发当周仍持有,下周收盘卖出;被砍的名字到下次调仓前不回来。"""
    P = np.array([
        [100.0, 100.0],
        [95.0, 100.0],
        [90.0, 100.0],
        [60.0, 100.0],   # 第 3 周触发(−40%)
        [55.0, 100.0],   # 第 4 周收盘卖出
        [58.0, 100.0],   # 反弹 —— 但调仓前不回来
        [60.0, 100.0],
    ])
    # 第 4 周起市值榜不再含 0(篮子规则不让它回来)
    basket = [{0, 1}] * 4 + [{1}] * 3
    out = simulate(P, basket=basket, reb=[0, 4], arm="LC", cost_bp=0.0)
    assert 0 in out["held_by_week"][3]          # 触发当周还拿着
    assert 0 not in out["held_by_week"][4]       # 下周收盘已卖
    assert 0 not in out["held_by_week"][5]
    assert 0 not in out["held_by_week"][6]
    assert out["n_cuts"] == 1
    assert out["cuts"][0][0] == 4


def test_lc_cut_respects_prior_rebalance_entry_price():
    """跨调仓日的成员:entry 是**第一次进篮子**那周,不被新调仓重置 —— 否则永远不触发。"""
    P = np.array([
        [100.0, 100.0],   # 第 0 周调仓,A 进篮(entry=0)
        [96.0, 100.0],
        [92.0, 100.0],
        [88.0, 100.0],
        [85.0, 100.0],    # 第 4 周调仓 —— A 仍是成员,entry 保持 0(85 > 75,不砍)
        [80.0, 100.0],
        [76.0, 100.0],    # −24%
        [74.0, 100.0],    # −26% ⇒ 从第 0 周算起才触发
        [72.0, 100.0],    # 下周收盘卖出
        [70.0, 100.0],
    ])
    out = simulate(P, basket=[[0, 1]] * 10, reb=[0, 4, 8], arm="LC", cost_bp=0.0)
    assert out["n_cuts"] == 1
    assert out["cuts"][0][0] == 8               # 第 7 周触发、第 8 周收盘执行


def test_r_and_l_never_cut():
    """R / L 没有砍腿;同一段价格上 LC 砍了,R / L 不砍。"""
    P = np.array([
        [100.0, 100.0], [96.0, 100.0], [92.0, 100.0], [88.0, 100.0],
        [85.0, 100.0], [70.0, 100.0], [60.0, 100.0], [50.0, 100.0],
    ])
    basket = [{0, 1}] * 8
    assert simulate(P, basket, [0, 4], arm="R", cost_bp=0.0)["n_cuts"] == 0
    assert simulate(P, basket, [0, 4], arm="L", cost_bp=0.0)["n_cuts"] == 0
    assert simulate(P, basket, [0, 4], arm="LC", cost_bp=0.0)["n_cuts"] == 1


def test_lccap_arm_caps_single_name_at_2_over_n():
    """LC-cap(10-18 看过结果才加的,只报):单名上限 2/N,超出的按比例分给未超额的。"""
    w = {"A": 0.60, "B": 0.20, "C": 0.20}
    out = cap_weights(w, 0.50)
    assert out["A"] == pytest.approx(0.50)
    assert sum(out.values()) == pytest.approx(1.0)
    assert out["B"] > 0.20 and out["C"] > 0.20
    # 上限只在调仓日按目标权重施加;两次调仓之间权重照漂(L 的本意:让赢家跑)
    P = np.array([[100.0, 100.0, 100.0],      # 第 0 周调仓:等权
                  [500.0, 100.0, 100.0],      # A 漂到 0.714 > 2/3
                  [500.0, 100.0, 100.0],      # 第 2 周调仓 ⇒ 上限在这里起作用
                  [500.0, 100.0, 100.0]])
    b3 = [{0, 1, 2}] * 4
    free = simulate(P, b3, [0, 2], arm="L", cost_bp=0.0)
    capped = simulate(P, b3, [0, 2], arm="LCcap", cost_bp=0.0)
    assert free["max_weight"].max() == pytest.approx(500 / 700)
    assert capped["max_weight"][2] == pytest.approx(2.0 / 3.0)
    assert free["max_weight"][2] == pytest.approx(500 / 700)


# ---------------------------------------------------------------- 端到端小样本

def test_simulate_returns_finite_weekly_returns_and_nav_composes():
    P = np.array([
        [100.0, 100.0, 100.0],
        [110.0, 100.0, 90.0],
        [120.0, 105.0, 81.0],
        [108.0, 110.0, 90.0],
        [130.0, 99.0, 99.0],
    ])
    basket = [[0, 1, 2]] * 5
    out = simulate(P, basket, [0], arm="R", cost_bp=0.0)
    assert len(out["weekly_ret"]) == 5
    assert all(np.isfinite(out["weekly_ret"]))
    nav = out["nav"]
    assert nav[0] == pytest.approx(1.0)
    # 第 1 周等权 ⇒ 净值 = 平均收益
    assert nav[1] == pytest.approx((1.10 + 1.00 + 0.90) / 3.0)


def test_cost_reduces_nav():
    P = np.array([[100.0, 100.0], [110.0, 100.0], [110.0, 100.0]])
    free = simulate(P, [[0, 1]] * 3, [0], arm="R", cost_bp=0.0)["nav"][-1]
    paid = simulate(P, [[0, 1]] * 3, [0], arm="R", cost_bp=20.0)["nav"][-1]
    assert paid < free


def test_ab_test_runs_on_weekly_returns():
    """统计走 apparatus 的 ab_test:周收益、mean_block 4、days_per_year 52。"""
    a = [0.001 + 0.01 * ((-1) ** i) for i in range(60)]
    b = [0.005 + 0.02 * ((-1) ** i) for i in range(60)]
    out = ab_test(a, b, mean_block=4, days_per_year=52)
    assert out["verdict"] == "B > A"
    assert out["n_days"] == 60
    assert out["p_b_le_a"] < 0.05