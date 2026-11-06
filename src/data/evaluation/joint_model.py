"""联合模型的挖掘框架(Jazz 11-06「特征和因子没有 put together」)—— 所有挖掘卡共用的一套:按时间走步、训练 / 测试之间切隔离带,
样本外预测的截面 / 时序 IC、按月聚类的 t、块置换零分布、置换重要性。**只有一个口径,lane 不再各写一遍。**

## 为什么这样切

- **走步(expanding)**:第 k 折只用测试段开始之前的数据训练;**隔离带 = 目标的持有期**(例如 30 天收益 ⇒ 30 天),
  否则训练样本的标签和测试样本的特征在时间上重叠,IC 会被前视放大(T-249 的成熟期修正就是同一件事)。
- **零分布**:把样本外预测按块(默认 20 天)打乱再算 IC —— 回答「这么高的 IC 随机能不能撞到」;用 `apparatus.null_distribution`。
- **置换重要性**:在测试段里把一个特征打乱,看 IC 掉多少 —— 回答「哪些维度在起作用」,而不是看模型系数。

纯函数,只依赖 numpy / pandas / scikit-learn;不读库、不写库。
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Sequence

import numpy as np

from src.data.evaluation.apparatus import block_permute, null_distribution, percentile_of


def purged_folds(n: int, n_folds: int, embargo: int, min_train: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """纯函数。按时间顺序的 n 个样本 → 走步折:测试段依次排开;训练 = 测试段开始前 `embargo` 个样本之前的全部。"""
    if n_folds < 1 or n <= min_train + embargo:
        return []
    test_len = (n - min_train - embargo) // n_folds
    if test_len < 1:
        return []
    out = []
    for k in range(n_folds):
        t0 = min_train + embargo + k * test_len
        t1 = n if k == n_folds - 1 else t0 + test_len
        train = np.arange(0, t0 - embargo)
        if len(train) >= min_train:
            out.append((train, np.arange(t0, t1)))
    return out


def spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 5:
        return None
    from scipy.stats import rankdata
    ra, rb = rankdata(a[m]), rankdata(b[m])                 # 并列取平均秩

    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def walk_forward(X: np.ndarray, y: np.ndarray, folds: list[tuple[np.ndarray, np.ndarray]],
                 model_factory: Callable[[], Any]) -> np.ndarray:
    """纯函数。每折新建模型、只在训练段 fit(行里有 NaN 的特征用训练段中位数填)→ 样本外预测(不在任何测试段的位置是 NaN)。"""
    oof = np.full(len(y), np.nan)
    for tr, te in folds:
        Xtr, ytr = X[tr], y[tr]
        ok = ~np.isnan(ytr)
        med = np.nanmedian(Xtr[ok], axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        fill = lambda M: np.where(np.isnan(M), med, M)
        m = model_factory()
        m.fit(fill(Xtr[ok]), ytr[ok])
        oof[te] = m.predict(fill(X[te]))
    return oof


def monthly_t(oof: np.ndarray, y: np.ndarray, months: Sequence[str]) -> dict[str, Any]:
    """按月算样本外 IC,再按月聚类求 t(月与月之间近似独立;持有期 ≤ 30 天时才这样读)。"""
    months = np.asarray(months)
    ics = []
    for mth in dict.fromkeys(months.tolist()):
        idx = months == mth
        v = spearman(oof[idx], y[idx])
        if v is not None:
            ics.append(v)
    if len(ics) < 3:
        return {"n_months": len(ics), "mean_ic": None, "t": None}
    mu, sd = float(np.mean(ics)), float(np.std(ics, ddof=1))
    return {"n_months": len(ics), "mean_ic": round(mu, 4), "t": round(mu / (sd / math.sqrt(len(ics))), 3) if sd > 0 else None}


def evaluate(oof: np.ndarray, y: np.ndarray, months: Sequence[str], block: int = 20, n_null: int = 1000,
             seed: int = 0) -> dict[str, Any]:
    """样本外 IC + 按月 t + 块置换零分布下的分位。"""
    m = ~(np.isnan(oof) | np.isnan(y))
    p, t = oof[m], y[m]
    ic = spearman(p, t)
    out = {"n": int(m.sum()), "ic": None if ic is None else round(ic, 4), **monthly_t(oof[m], y[m], np.asarray(months)[m])}
    if ic is not None and n_null:
        null = null_distribution(lambda rng: spearman(block_permute(p, block, rng).astype(float), t) or 0.0, n_null, seed, actual=ic)
        out["null_p95"] = round(float(np.percentile(null, 95)), 4)
        out["pctile"] = round(float(percentile_of(ic, null)), 4)
    return out


def permutation_importance(X: np.ndarray, y: np.ndarray, folds: list[tuple[np.ndarray, np.ndarray]],
                           model_factory: Callable[[], Any], names: Sequence[str], seed: int = 0) -> list[dict[str, Any]]:
    """每个特征:在每个测试段里打乱它(训练不变)→ 样本外 IC 下降多少。下降越多 = 越在起作用。"""
    base = walk_forward(X, y, folds, model_factory)
    ic0 = spearman(base, y) or 0.0
    rng = np.random.default_rng(seed)
    out = []
    for j, name in enumerate(names):
        oof = np.full(len(y), np.nan)
        for tr, te in folds:
            Xtr, ytr = X[tr], y[tr]
            ok = ~np.isnan(ytr)
            med = np.nanmedian(Xtr[ok], axis=0)
            med = np.where(np.isnan(med), 0.0, med)
            fill = lambda M: np.where(np.isnan(M), med, M)
            mdl = model_factory()
            mdl.fit(fill(Xtr[ok]), ytr[ok])
            Xte = fill(X[te]).copy()
            Xte[:, j] = rng.permutation(Xte[:, j])
            oof[te] = mdl.predict(Xte)
        ic = spearman(oof, y) or 0.0
        out.append({"feature": name, "ic_drop": round(ic0 - ic, 4)})
    return sorted(out, key=lambda r: -r["ic_drop"])
