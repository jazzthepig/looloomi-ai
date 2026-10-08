"""T-075 / S-521:类比元配置 —— 时点(相似日的结果必须在 d 之前已知)、埋信号能学到、零信号不在尾部。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals.meta_allocator import (CASH, H, STATE_FEATURES, build, decide, expanding_z,  # noqa: E402
                                             forward_sums)


def _world(seed=0, planted=True, n=900):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n)
    regime = np.repeat(rng.integers(0, 2, n // 30 + 1), 30)[:n]          # 30 天一段的隐状态
    a = np.where(regime == 1, 0.004, -0.004) + rng.normal(0, 0.01, n)
    b = np.where(regime == 1, -0.004, 0.004) + rng.normal(0, 0.01, n)
    arms = pd.DataFrame({"btc": a, "other": b, **{f"n{i}": rng.normal(0, 0.01, n) for i in range(4)}}, index=idx)
    sig = regime if planted else rng.integers(0, 2, n)
    state = pd.DataFrame({f: rng.normal(0, 1, n) for f in STATE_FEATURES}, index=idx)
    state["dist_200"] = sig * 3.0 + rng.normal(0, 0.1, n)
    return arms, state


def test_forward_sums_look_only_after_t() -> None:
    idx = pd.date_range("2024-01-01", periods=20)
    r = pd.DataFrame({"x": np.arange(20) / 1000}, index=idx)
    f = forward_sums(r, h=3)
    assert abs(f["x"].iloc[0] - (np.prod(1 + np.array([1, 2, 3]) / 1000) - 1)) < 1e-12
    assert f["x"].iloc[-3:].isna().all()


def test_decision_at_d_does_not_change_when_the_future_changes() -> None:
    arms, state = _world()
    z = expanding_z(state)
    d = pd.Timestamp("2024-06-03")
    w1, _ = decide(d, z, forward_sums(arms), list(arms.columns))
    arms2 = arms.copy()
    arms2.loc[d:] *= -5                                   # d 及之后的收益在 d 当天都还不知道
    state2 = state.copy()
    state2.loc[d:] += 9
    w2, _ = decide(d, expanding_z(state2), forward_sums(arms2), list(arms.columns))
    assert w1 == w2, "d 的决定只能用 d−1 及以前已知的结果"
    arms3 = arms.copy()
    arms3.loc[d - pd.Timedelta(days=3):] *= -5
    w3, _ = decide(d, z, forward_sums(arms3), list(arms.columns))
    assert isinstance(w3, dict)


def test_planted_signal_is_learned_and_noise_is_not_in_the_tail() -> None:
    arms, state = _world(planted=True)
    _, ev = build(arms, state, arms.index[-1], n_random=200, n_shuffle=40)
    assert ev["holdout_2025_to_inception"]["pct_vs_shuffled_state"] > 0.95
    arms0, state0 = _world(seed=1, planted=False)
    _, ev0 = build(arms0, state0, arms0.index[-1], n_random=200, n_shuffle=40)
    assert ev0["holdout_2025_to_inception"]["pct_vs_shuffled_state"] < 0.95, "状态是噪声时不该显得会挑"


def test_early_days_without_enough_analogs_hold_cash() -> None:
    arms, state = _world()
    w, why = decide(pd.Timestamp("2023-03-06"), expanding_z(state), forward_sums(arms), list(arms.columns))
    assert w == {CASH: 1.0}
