"""Strategy 空间向量(11-04):没测到的维不写(不是 0)、天气桶 ≥ 20 天才写、共享维余弦不做 0 补齐、覆盖空洞按桶报。"""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.strategy import book_vectors as bv  # noqa: E402


def _nav(n=120, drift=0.001, seed=1, start="2026-06-01"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.Series(np.cumprod(1 + drift + rng.normal(0, 0.01, n)), index=idx)


def _regime(idx):
    df = pd.DataFrame({"trend_up": [i % 2 == 0 for i in range(len(idx))], "vol_hot": [True] * len(idx)}, index=idx)
    df["cycle_turning"] = np.nan                                         # ⓪ 这段没有相位 ⇒ 桶不写
    return df


def test_vector_has_only_measured_dims_and_buckets_need_20_days():
    nav, bench, core = _nav(), _nav(drift=0.0, seed=2), _nav(drift=0.0005, seed=3)
    v = bv.vector_for(nav, bench, core, _regime(nav.index))
    assert v and v["n_days"] == 119 and "beta_core" in v and "trend_up" in v and "trend_down" in v
    assert "cycle_turning" not in v and "cycle_normal" not in v        # NaN 相位 ⇒ 不出现,不是 0
    assert "vol_cold" not in v and "vol_hot" in v                       # vol_cold 0 天
    assert all(math.isfinite(x) for x in v.values())
    assert bv.vector_for(_nav(n=30), bench, core, _regime(nav.index)) is None


def test_cosine_only_on_shared_dims_and_none_when_too_few():
    a = {"excess_ann": 0.2, "vol_ann": 0.3, "max_dd": -0.1, "hit_daily": 0.55, "skew": 0.1, "ac1": 0.0, "beta_core": 1.0, "n_days": 100}
    b = {**a, "excess_ann": 0.19, "n_days": 200}
    c = {"excess_ann": -0.2, "vol_ann": 0.3}
    sc = bv.scales({"a": a, "b": b, "c": c, "d": {k: v * 2 for k, v in a.items()}})
    assert bv.cosine_shared(a, b, sc) is not None and bv.cosine_shared(a, c, sc) is None
    nb = bv.neighbours({"a": a, "b": b, "c": c, "d": {k: v * 2 for k, v in a.items()}}, "a")
    assert nb and nb[0]["book"] in ("b", "d") and all("cosine" in r for r in nb)


def test_uncovered_reports_empty_and_all_negative_buckets():
    vecs = {"x": {"trend_up": 0.1, "trend_down": -0.2, "vol_hot": -0.05}, "y": {"trend_up": 0.05, "trend_down": -0.1}}
    u = {r["bucket"]: r["why"] for r in bv.uncovered(vecs)}
    assert "trend_up" not in u and "都是负超额" in u["trend_down"] and "没有一本账" in u["cycle_turning"]


def test_regime_frame_from_rows():
    st = [{"d": "2026-07-01", "feature": "dist_200", "value": 0.05}, {"d": "2026-07-01", "feature": "vratio_30_180", "value": 0.8},
          {"d": "2026-07-02", "feature": "dist_200", "value": -0.01}]
    cy = [{"d": "2026-07-02", "phase": "turning"}]
    df = bv.regime_frame(st, cy)
    assert bool(df.loc["2026-07-01", "trend_up"]) is True and bool(df.loc["2026-07-01", "vol_hot"]) is False
    assert bool(df.loc["2026-07-02", "cycle_turning"]) is True and pd.isna(df.loc["2026-07-02", "vol_hot"])


def test_wiring():
    assert "_book_vectors_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/book-vectors"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-04_book_vectors.sql").read_text(encoding="utf-8")
    for col in bv.WRITES_COLUMNS[bv.TABLE]:
        assert col in mig, col
