"""S-737 前向记录(11-06):冻结规格重拟合后能对上参考中心、结算公式、BS 看跌、接线。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import state_map as sm  # noqa: E402


def _synthetic(n_per=60, seed=1):
    """以 T257_MEANS 为中心造训练期样本 ⇒ 重拟合应把每一类对回自己的类号。"""
    rng = np.random.default_rng(seed)
    means = np.array([sm.T257_MEANS[s] for s in range(6)])
    scale = np.abs(means).mean(0) * 0.03 + 1e-3
    ds, X, truth = [], [], []
    k = 0
    for s in range(6):
        for _ in range(n_per):
            ds.append(f"2022-{1 + k // 28 % 12:02d}-{1 + k % 28:02d}")
            X.append(means[s] + rng.normal(size=len(sm.FEATURES)) * scale)
            truth.append(s)
            k += 1
    return ds, np.array(X), truth


def test_fit_aligns_refit_clusters_to_t257_labels():
    ds, X, truth = _synthetic()
    model = sm.fit(ds, X)
    assert model["align_worst"] < sm.MAX_ALIGN_DIST
    got = [sm.assign(model, x)[0] for x in X[::25]]
    assert got == truth[::25], "每一类都对回 T-257 的编号"


def test_matrix_drops_incomplete_days():
    full = {k: 0.1 for k in sm.FEATURES}
    rows = [{"d": "2026-11-02", "f": full}, {"d": "2026-11-01", "f": {**full, "macro:vix": None}}]
    ds, X = sm.matrix(rows)
    assert ds == ["2026-11-02"] and X.shape == (1, len(sm.FEATURES))


def test_settle_and_bs_put():
    rs, rp = sm.settle(100.0, 70.0, 1.0)
    assert abs(rs + 0.30) < 1e-12 and abs(rp - (-0.30 + 0.20 - 0.01)) < 1e-12, "跌 30%:看跌赔 20%,扣权利金 1%"
    rs, rp = sm.settle(100.0, 110.0, 1.0)
    assert abs(rp - 0.09) < 1e-12
    p = sm.bs_put(1.0, 0.9, 30, 0.40)
    assert 0.005 < p < 0.02, p


def test_wiring():
    assert "async def _state_map_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_state_map.sql").read_text(encoding="utf-8")
    for cols in sm.WRITES_COLUMNS.values():
        assert all(c in mig for c in cols)
