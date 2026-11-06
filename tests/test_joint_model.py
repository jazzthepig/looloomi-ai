"""联合模型框架(11-06):隔离带真的切开了、样本外预测不碰测试段的标签、零分布有方差、重要性能认出真因子。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.evaluation import joint_model as jm  # noqa: E402


def test_purged_folds_leave_an_embargo_and_only_look_back():
    folds = jm.purged_folds(400, 4, embargo=30, min_train=100)
    assert len(folds) == 4
    for tr, te in folds:
        assert tr.max() < te.min() - 30 + 1 and len(tr) >= 100, "训练段在测试段开始前 30 个样本之前就结束"
    assert folds[-1][1].max() == 399 and jm.purged_folds(50, 4, 30, 100) == []


def test_walk_forward_finds_a_real_signal_and_the_null_does_not():
    from sklearn.linear_model import Ridge
    rng = np.random.default_rng(1)
    n = 600
    x_true, x_noise = rng.normal(size=n), rng.normal(size=n)
    y = 0.6 * x_true + rng.normal(size=n)
    X = np.column_stack([x_true, x_noise])
    X[5, 1] = np.nan                                                   # 缺值用训练段中位数填,不报错
    folds = jm.purged_folds(n, 4, embargo=10, min_train=150)
    oof = jm.walk_forward(X, y, folds, lambda: Ridge(alpha=1.0))
    assert np.isnan(oof[:150]).all(), "最早的训练段没有样本外预测"
    months = [f"m{i // 20}" for i in range(n)]
    ev = jm.evaluate(oof, y, months, block=20, n_null=200, seed=7)
    assert ev["ic"] > 0.3 and ev["pctile"] >= 0.99 and ev["t"] > 3
    imp = jm.permutation_importance(X, y, folds, lambda: Ridge(alpha=1.0), ["true", "noise"], seed=3)
    assert imp[0]["feature"] == "true" and imp[0]["ic_drop"] > imp[1]["ic_drop"]


def test_spearman_edges():
    assert jm.spearman([1, 2, 3], [1, 2, 3]) is None and jm.spearman([1] * 6, list(range(6))) is None
    assert abs(jm.spearman(range(10), range(10)) - 1.0) < 1e-12
