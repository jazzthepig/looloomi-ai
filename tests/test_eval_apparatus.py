"""T-097 验证装置:每条都把 10-14 那一天出过的 bug 复现出来(旧写法会红),再加 A/A 与埋信号的校准。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (NoOpNull, ab_test, block_permute, brier, long_return,  # noqa: E402
                                           null_distribution, percentile_of, price_on_or_after,
                                           short_return, shuffle_within, stationary_bootstrap_index, windows)


def test_short_return_is_bounded_not_convex():
    """T-092 / T-093:short_ret = p_ent / p_ext − 1 把 100 → 50 记成 +100%,价格趋零记成无穷大。"""
    assert short_return(100, 50) == pytest.approx(0.5)
    assert short_return(100, 200) == pytest.approx(-1.0)
    assert short_return(100, 100) == 0.0
    assert short_return(100, 1e-9) <= 1.0
    old = lambda e, x: e / x - 1  # noqa: E731 — the bug
    assert old(100, 50) != short_return(100, 50)
    assert long_return(100, 150) == pytest.approx(0.5)
    for bad in (None, 0, -1, float("nan"), "x"):
        assert short_return(bad, 100) is None and long_return(100, bad) is None


def test_entry_before_listing_is_not_the_latest_close():
    """T-092 / T-093:名字还没上市时 find_idx 返回 −1,入场价取成最新收盘。"""
    dates = ["2025-03-01", "2025-03-02", "2025-03-03"]
    closes = [10.0, 11.0, 12.0]
    assert price_on_or_after(dates, closes, "2024-06-01") is None, "上市前 ⇒ 不可算"
    assert price_on_or_after(dates, closes, "2025-02-28") == 10.0, "3 天内的第一个收盘"
    assert price_on_or_after(dates, closes, "2025-03-04") is None, "之后没有价格 ⇒ 不可算,不是 closes[-1]"


def test_dict_shuffle_noop_is_caught():
    """T-090 / T-093 初版:打乱 dict 的 items 不改变 key → value 的绑定,零分布 = 实际值。"""
    states = {f"w{i}": (i % 3) for i in range(60)}
    outcome = {k: float(v) for k, v in states.items()}
    actual = sum(outcome[k] * states[k] for k in states)

    def buggy(rng):
        items = list(states.items())
        rng.shuffle(items)          # 打乱的是顺序,绑定没变
        s = dict(items)
        return sum(outcome[k] * s[k] for k in s)

    with pytest.raises(NoOpNull):
        null_distribution(buggy, 200, seed=1, actual=actual)

    keys, vals = list(states), list(states.values())

    def fixed(rng):
        perm = block_permute(vals, 4, rng)
        return sum(outcome[k] * v for k, v in zip(keys, perm))

    null = null_distribution(fixed, 200, seed=1, actual=actual)
    assert percentile_of(actual, null) > 0.95, "真实绑定的乘积和应高于打乱"


def test_block_permute_keeps_blocks_and_values():
    rng = np.random.default_rng(0)
    seq = np.arange(23)
    out = block_permute(seq, 5, rng)
    assert sorted(out.tolist()) == seq.tolist()
    starts = [i for i in range(len(out)) if i == 0 or out[i] != out[i - 1] + 1]
    assert len(starts) <= 5, "块内连续"
    assert np.array_equal(block_permute(seq, 100, rng), seq), "一个块 ⇒ 不变"
    with pytest.raises(NoOpNull):
        null_distribution(lambda r: float(block_permute(seq, 100, r)[0]), 50, seed=0)


def test_shuffle_within_stays_inside_groups():
    rng = np.random.default_rng(3)
    vals = list(range(12))
    groups = ["a"] * 4 + ["b"] * 4 + ["c"] * 4
    out = shuffle_within(vals, groups, rng)
    for g, lo in (("a", 0), ("b", 4), ("c", 8)):
        assert sorted(out[lo:lo + 4].tolist()) == list(range(lo, lo + 4))


def test_percentile_edges():
    assert percentile_of(5.0, [1, 2, 3]) == 1.0
    assert percentile_of(0.0, [1, 2, 3]) == 0.0
    assert percentile_of(2.0, [1, 2, 3]) == pytest.approx(0.5)
    assert percentile_of(1.0, []) is None and percentile_of(None, [1]) is None


def test_brier_and_windows():
    assert brier([1, 0], [1, 0]) == 0.0 and brier([0.5, 0.5], [1, 0]) == 0.25
    assert brier([], []) is None
    with pytest.raises(ValueError):
        brier([1.2], [1])
    w = windows(["2022-12-31", "2023-06-01", "2025-01-01", "2026-01-01"], ["2023-01-01", "2025-01-01"])
    assert [m.tolist() for _, m in w] == [[False, True, False, False], [False, False, True, True]]


def _ar1(n, phi, sd, rng):
    e = rng.normal(0, sd, n)
    x = np.empty(n)
    x[0] = e[0]
    for t in range(1, n):
        x[t] = phi * x[t - 1] + e[t]
    return x


def test_aa_false_positive_rate_holds_with_autocorrelation():
    """A/A:两条臂没有真实差别、差是自相关的 —— 5% 单侧的假阳性率要守在名义附近;逐日自助法会超标。"""
    rng = np.random.default_rng(7)
    sims, fp_block, fp_iid = 120, 0, 0
    for s in range(sims):
        a = rng.normal(0.0005, 0.03, 900)
        b = a + _ar1(900, 0.6, 0.004, rng)
        fp_block += ab_test(a, b, mean_block=20, n_boot=300, seed=s)["p_b_le_a"] < 0.05
        fp_iid += ab_test(a, b, mean_block=1, n_boot=300, seed=s)["p_b_le_a"] < 0.05
    assert fp_block / sims <= 0.10, f"块自助法 A/A 假阳性 {fp_block / sims:.2f}"
    assert fp_iid > fp_block, "自相关下逐日自助法更容易误报 —— 这就是默认用块的原因"


def test_planted_effect_is_found_and_mde_is_honest():
    rng = np.random.default_rng(11)
    hits, under = 0, 0
    for s in range(40):
        a = rng.normal(0.0, 0.03, 1000)
        b = a + 0.0008 + rng.normal(0, 0.006, 1000)   # ≈ +29% / 年 的对数差
        r = ab_test(a, b, n_boot=400, seed=s)
        hits += r["verdict"] == "B > A"
        under += r["underpowered"]
    assert hits >= 34, f"埋了 +29%/年 只检出 {hits}/40"
    small = ab_test(a, a + 0.00002 + rng.normal(0, 0.006, 1000), n_boot=400, seed=1)
    assert small["underpowered"] and small["verdict"] == "分不开", "小于 MDE 的差要标功效不足"


def test_ab_drops_uncomputable_days_and_refuses_short_samples():
    a = [0.01, float("nan"), 0.02] * 30
    b = [0.02, 0.01, float("nan")] * 30
    r = ab_test(a, b, mean_block=5, n_boot=200)
    assert r["n_days"] == 30
    assert ab_test([0.01] * 10, [0.02] * 10)["verdict"] == "不可算"
    idx = stationary_bootstrap_index(50, 1, 10, np.random.default_rng(0))
    assert idx.shape == (10, 50) and idx.min() >= 0 and idx.max() < 50


def test_float_noise_null_is_still_a_noop():
    """T-171:块置换不改变均值 —— 零分布只剩求和顺序的浮点噪声(跨度 ~1e-19),以前过得了 `ptp == 0`。"""
    import numpy as np
    xs = np.random.default_rng(1).normal(size=500) * 0.01

    def mean_after_block_permute(rng):
        return float(np.mean(block_permute(xs, 20, rng)))

    with pytest.raises(NoOpNull):
        null_distribution(mean_after_block_permute, 200, seed=7)
