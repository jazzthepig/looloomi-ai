"""时序窗口向量(11-05):形状向量尺度无关、近邻排除最近 31 天、样本不够回无条件、③ 决定里只是描述臂。"""
from __future__ import annotations

import datetime as dt
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import window_vectors as wv  # noqa: E402


def _path(n=700, seed=5, start=dt.date(2019, 1, 1)):
    random.seed(seed)
    c, out = 100.0, {}
    for i in range(n):
        c *= math.exp(random.gauss(0.0005, 0.03))
        out[(start + dt.timedelta(days=i)).isoformat()] = c
    return out


def test_vector_is_scale_free_and_has_17_dims():
    closes = _path()
    days = sorted(closes)
    seg = [closes[k] for k in days[:61]]
    v1, v2 = wv.window_vector(seg), wv.window_vector([x * 1000 for x in seg])
    assert v1 and len(v1) == len(wv.DIMS) == 17 and all(abs(a - b) < 1e-6 for a, b in zip(v1, v2))
    assert -1 <= v1[12] <= 0 and 0 <= v1[13] <= 1                     # dd, pos
    assert wv.window_vector(seg[:40]) is None and wv.window_vector([0.0] + seg[1:]) is None


def test_vectors_by_day_and_nearest_exclude_recent():
    closes = _path()
    vecs = wv.vectors_by_day(closes)
    d = max(vecs)
    assert len(vecs) == len(closes) - wv.WINDOW
    near = wv.nearest(vecs, vecs[d], d, k=10)
    assert len(near) == 10 and all((dt.date.fromisoformat(d) - dt.date.fromisoformat(k)).days > wv.EXCLUDE_DAYS for _, k in near)
    assert near == sorted(near)


def test_window_rates_shrinks_and_falls_back():
    from src.data.execution.exposure_decision import forward_returns
    closes = _path(1200)
    vecs = wv.vectors_by_day(closes)
    d = max(vecs)
    fwd = forward_returns({k: v for k, v in closes.items() if k < d})
    r = wv.window_rates(vecs, fwd, vecs[d], d)
    assert r["n"] == wv.K and r["segments"] >= 1 and abs(sum(r["probs"].values()) - 1) < 0.01 and len(r["matches"]) == 5
    assert all(m["d"] in fwd for m in r["matches"])
    small = wv.window_rates({k: v for k, v in list(vecs.items())[:20]}, fwd, vecs[d], d)
    assert small["n"] == 0 and small["matches"] == []


def test_decision_carries_window_arm_as_description_only():
    src = (ROOT / "src/data/execution/exposure_decision.py").read_text(encoding="utf-8")
    assert 'inputs["probs_window"]' in src and "window_matches" in src
    # 敞口仍只由规则给:窗口臂不进 rule_exposure / flag_for
    i, j = src.find("def rule_exposure"), src.find("def flag_for")
    assert "window" not in src[i:j] and "window" not in src[j:src.find("def rationale")]


def test_wiring():
    assert "_window_vectors_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/window-knn"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-05_window_vectors.sql").read_text(encoding="utf-8")
    for col in wv.WRITES_COLUMNS[wv.TABLE]:
        assert col in mig, col
