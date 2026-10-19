"""验证装置(T-097)—— 研究卡的零分布、盈亏与 A/B 比较,只许用这里的函数。

## 为什么

「验证装置就是产品」(ARCHITECTURE)。到 10-14 为止它是每张卡各写一遍的脚本,那一天坏了 5 次:
打乱是空操作两次(dict 打乱不改变 key → value 的绑定,零分布 = 实际值,所有分位都是同一个数)、
空头盈亏写成 p_entry / p_exit − 1 两张卡(对跌幅是凸的:100 → 50 记 +100%,价格趋零记成无穷大)、
上市前入场取到最新收盘一张卡、领先统计量退化一张卡。这里每个函数都有把那次 bug 复现出来的测试。

## A/B(Jazz 10-14「ab test 测试模拟」)

两条臂在同一组日期上的日收益 → 逐日对数差 d_t = ln(1 + r_B) − ln(1 + r_A)。
- 总差 = Σ d_t(对数单位;expm1 之后就是「B 相对 A 多 / 少的倍数」)。
- 不确定性用平稳块自助法(Politis–Romano,平均块长默认 20 天):加密日收益的波动聚集与自相关会让
  逐日独立的自助法把置信区间算窄,A/A 测试里假阳性率会超标;块自助法在 A/A 测试里守住名义水平。
- p(B ≤ A)= 自助分布里总差 ≤ 0 的比例(单侧)。
- **最小可检出效应 MDE** = (z₁₋α + z_power) × 自助标准误,换算成每年。观测到的差小于 MDE 时标「功效不足」:
  这时「和随机分不开」不等于「没有效果」,只说明这段历史不够长,看不出来。

A/B 只回答「B 的总收益是否高于 A」。择时规则还要过「同平均仓位恒定持有」与随机择时的对照(DECISIONS 10-08),
那是 `null_distribution` + `block_permute` 的事,A/B 不替代它。
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Callable, Optional, Sequence

import numpy as np


class NoOpNull(RuntimeError):
    """零分布与实际值重合 —— 打乱没有打乱任何东西(10-14 的 T-090 / T-093 初版)。"""


# ── 盈亏 ────────────────────────────────────────────────────────────────────

def _price(p: Any) -> Optional[float]:
    try:
        x = float(p)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def long_return(p_entry: Any, p_exit: Any) -> Optional[float]:
    """多头:p_exit / p_entry − 1。任一价缺 / 非正 ⇒ None(不可算,不是 0)。"""
    a, b = _price(p_entry), _price(p_exit)
    return None if a is None or b is None else b / a - 1.0


def short_return(p_entry: Any, p_exit: Any) -> Optional[float]:
    """空头(不加杠杆、按入场名义):1 − p_exit / p_entry。100 → 50 = +0.5,100 → 200 = −1.0,上限 +1。"""
    a, b = _price(p_entry), _price(p_exit)
    return None if a is None or b is None else 1.0 - b / a


def price_on_or_after(dates: Sequence[str], closes: Sequence[Any], d: str, max_gap_days: int = 3) -> Optional[float]:
    """d 当天或之后 max_gap_days 天内的第一个有效收盘;该名那时还没有价格 ⇒ None。

    10-14:`find_idx` 在名字还没上市时返回 −1,下游用 closes[-1](最新收盘)当入场价。"""
    from datetime import date
    target = date.fromisoformat(str(d)[:10])
    for di, c in zip(dates, closes):
        dd = date.fromisoformat(str(di)[:10])
        if dd < target:
            continue
        if (dd - target).days > max_gap_days:
            return None
        p = _price(c)
        if p is not None:
            return p
    return None


# ── 零分布 ──────────────────────────────────────────────────────────────────

def block_permute(seq: Sequence[Any], block: int, rng: np.random.Generator) -> np.ndarray:
    """把序列切成长 `block` 的连续块(最后一块可以短),打乱块的顺序。保留块内结构与元素的多重集合。"""
    arr = np.asarray(seq, dtype=object if not np.issubdtype(np.asarray(seq).dtype, np.number) else None)
    if block < 1:
        raise ValueError("block must be ≥ 1")
    blocks = [arr[i:i + block] for i in range(0, len(arr), block)]
    order = rng.permutation(len(blocks))
    return np.concatenate([blocks[i] for i in order]) if blocks else arr.copy()


def shuffle_within(values: Sequence[Any], groups: Sequence[Any], rng: np.random.Generator) -> np.ndarray:
    """在同一组(例如同一周)内部打乱值的归属,组与组之间不混。"""
    vals = np.asarray(values, dtype=object)
    grp = np.asarray(groups, dtype=object)
    out = vals.copy()
    for g in dict.fromkeys(grp.tolist()):
        idx = np.flatnonzero(grp == g)
        out[idx] = vals[rng.permutation(idx)]
    return out


def null_distribution(fn: Callable[[np.random.Generator], float], n: int, seed: int,
                      actual: Optional[float] = None) -> np.ndarray:
    """调用 fn(rng) n 次得到零分布。零分布没有方差,或 ≥ 99% 的抽样等于实际值 ⇒ NoOpNull。"""
    rng = np.random.default_rng(seed)
    null = np.array([float(fn(rng)) for _ in range(n)], dtype=float)
    finite = null[np.isfinite(null)]
    if finite.size == 0:
        raise NoOpNull("零分布全是 NaN / inf")
    if np.ptp(finite) == 0.0:
        raise NoOpNull(f"零分布没有方差(全部 = {finite[0]!r})—— 打乱没有改变任何东西")
    if actual is not None and math.isfinite(actual):
        same = np.isclose(finite, actual, rtol=0.0, atol=1e-12).mean()
        if same >= 0.99:
            raise NoOpNull(f"{same:.0%} 的零分布抽样等于实际值 —— 打乱没有改变任何东西")
    return null


def percentile_of(actual: Optional[float], null: Sequence[float]) -> Optional[float]:
    """实际值在零分布里的中秩分位:(严格小于的个数 + 相等个数 / 2)/ n。空零分布或实际值不可算 ⇒ None。"""
    if actual is None or not math.isfinite(actual):
        return None
    arr = np.asarray(null, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(((arr < actual).sum() + 0.5 * (arr == actual).sum()) / arr.size)


# ── 打分与切分 ────────────────────────────────────────────────────────────────

def brier(p: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """概率预测的 Brier 分数(越小越好);长度不同或空 ⇒ None。"""
    pp, yy = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    if pp.size == 0 or pp.size != yy.size:
        return None
    if np.any((pp < 0) | (pp > 1)) or not np.all(np.isin(yy, (0.0, 1.0))):
        raise ValueError("p ∈ [0, 1],y ∈ {0, 1}")
    return float(np.mean((pp - yy) ** 2))


def windows(dates: Sequence[str], cuts: Sequence[str]) -> list[tuple[str, np.ndarray]]:
    """按切点把日期分段:cuts = ['2023-01-01', '2025-01-01'] ⇒ [起, 2025-01-01) 与 [2025-01-01, 止]。"""
    d = np.asarray([str(x)[:10] for x in dates])
    edges = [str(c)[:10] for c in cuts]
    out = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else None
        mask = (d >= lo) & ((d < hi) if hi else True)
        label = f"{lo} → {hi}" if hi else f"{lo} →"
        out.append((label, mask))
    return out


# ── A/B ─────────────────────────────────────────────────────────────────────

def stationary_bootstrap_index(n: int, mean_block: float, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """Politis–Romano 平稳块自助法的下标矩阵(n_boot × n)。mean_block = 1 退化为逐日独立重抽。"""
    if n < 1:
        raise ValueError("n must be ≥ 1")
    p = 1.0 / max(float(mean_block), 1.0)
    idx = np.empty((n_boot, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, n_boot)
    for t in range(1, n):
        new = rng.random(n_boot) < p
        idx[:, t] = np.where(new, rng.integers(0, n, n_boot), (idx[:, t - 1] + 1) % n)
    return idx


def ab_test(ret_a: Sequence[float], ret_b: Sequence[float], *, mean_block: float = 20.0, n_boot: int = 2000,
            seed: int = 0, alpha: float = 0.05, power: float = 0.80, days_per_year: float = 365.0) -> dict[str, Any]:
    """同一组日期上两条臂的日收益 → B 相对 A 的总差、块自助置信区间、单侧 p、MDE 与结论。

    任一侧当天不可算(NaN)⇒ 那一天两边都不计。"""
    a = np.asarray(ret_a, dtype=float)
    b = np.asarray(ret_b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("ret_a 与 ret_b 必须是同一组日期")
    ok = np.isfinite(a) & np.isfinite(b) & (a > -1) & (b > -1)
    a, b = a[ok], b[ok]
    n = int(a.size)
    if n < 2 * mean_block:
        return {"n_days": n, "verdict": "不可算", "why": f"只有 {n} 天,少于两个平均块长"}
    d = np.log1p(b) - np.log1p(a)
    total = float(d.sum())
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_index(n, mean_block, n_boot, rng)
    boot = d[idx].sum(axis=1)
    se = float(boot.std(ddof=1))
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    p_b_le_a = float((boot <= 0).mean())
    p_b_ge_a = float((boot >= 0).mean())
    z = NormalDist().inv_cdf
    mde_total = (z(1 - alpha) + z(power)) * se
    years = n / days_per_year
    if p_b_le_a < alpha:
        verdict = "B > A"
    elif p_b_ge_a < alpha:
        verdict = "B < A"
    else:
        verdict = "分不开"
    return {
        "n_days": n,
        "years": round(years, 2),
        "cum_a": float(np.expm1(np.log1p(a).sum())),
        "cum_b": float(np.expm1(np.log1p(b).sum())),
        "log_diff_total": total,
        "ratio_b_over_a": float(np.exp(total)),
        "ci95_log_diff": (float(lo), float(hi)),
        "p_b_le_a": p_b_le_a,
        "p_b_ge_a": p_b_ge_a,
        "se_log_diff": se,
        "mde_log_diff_total": float(mde_total),
        "mde_log_diff_per_year": float(mde_total / years) if years > 0 else None,
        "underpowered": abs(total) < mde_total,
        "verdict": verdict,
        "mean_block": mean_block,
        "n_boot": n_boot,
    }
