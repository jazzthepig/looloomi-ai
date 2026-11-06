"""S-741 前向记分(11-06):特征冻结 59 个、隔离带 30、训练不足不出预测、已存的预测不重算、z 只看更早的 90 个、只有 live 算前向证据。"""
from __future__ import annotations

import asyncio
import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import joint_forecast as jf  # noqa: E402


def _data(n=520, seed=1):
    rng = np.random.default_rng(seed)
    d0 = dt.date(2021, 3, 24)
    ds = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]
    sig = np.cumsum(rng.normal(0, 0.02, n))
    px = 100 * np.exp(sig)
    frows = [{"d": d, "f": {k: float(rng.normal()) for k in jf.FEATURES[:5]} | {"mom_20": float(sig[i] - sig[max(0, i - 20)])}}
             for i, d in enumerate(ds)]
    prows = [{"d": d, "c": float(px[i])} for i, d in enumerate(ds)]
    return ds, frows, prows


def test_features_frozen():
    assert len(jf.FEATURES) == 59 and len(set(jf.FEATURES)) == 59
    assert not any(k.startswith("venue:") for k in jf.FEATURES), "之后才有的维度不进 —— 换特征集 = 新预注册"


def test_build_targets_and_embargo():
    ds, frows, prows = _data()
    d2, X, y = jf.build(frows, prows)
    assert X.shape == (len(d2), 59) and math.isnan(y[-1]) and not math.isnan(y[0])
    assert jf.predict_at(X, y, jf.MIN_TRAIN + jf.EMBARGO - 1)[0] is None          # 训练行不足
    p, n = jf.predict_at(X, y, jf.MIN_TRAIN + jf.EMBARGO + 5)
    assert p is not None and n == jf.MIN_TRAIN + 5                                # 只用 i − 30 之前的行


def test_z_scores_use_only_earlier_predictions():
    preds = [float(i % 7) for i in range(100)]
    z = jf.z_scores(preds)
    assert all(v is None for v in z[:jf.Z_MIN]) and z[jf.Z_MIN] is not None
    w = np.asarray(preds[jf.Z_MIN - jf.Z_MIN:jf.Z_MIN], float)
    assert abs(z[jf.Z_MIN] - (preds[jf.Z_MIN] - w.mean()) / w.std(ddof=1)) < 1e-3


def test_plan_never_recomputes_stored_predictions():
    ds, frows, prows = _data()
    d2, X, y = jf.build(frows, prows)
    today = dt.date.fromisoformat(d2[-1])
    rows = jf.plan(d2, X, y, {}, today, "t0")
    assert rows and rows[-1]["kind"] == "live" and rows[0]["kind"] == "backfill"
    have = {r["d"]: {**r, "pred": 9.99} for r in rows[:10]}
    again = jf.plan(d2, X, y, have, today, "t1")
    assert [r["pred"] for r in again[:10]] == [9.99] * 10 and again[0]["computed_at"] == "t0"


def test_forward_ic_counts_only_live():
    rows = [{"kind": "backfill", "z": float(i), "fwd_ret_30d": float(i)} for i in range(30)]
    assert jf.forward_ic(rows)["ic"] is None and jf.forward_ic(rows, "backfill")["ic"] == 1.0


def test_run_once():
    ds, frows, prows = _data()
    out = []

    async def read(t, p):
        return {"feature_matrix_daily": frows, "perp_bv_daily": prows}.get(t, [])

    async def up(t, rows, on_conflict=None):
        out.extend(rows)
        return True

    r = asyncio.run(jf.run_once(now=dt.datetime.fromisoformat(ds[-1] + "T12:00:00+00:00"), read=read, upsert=up))
    assert r["ok"] and r["latest_d"] == ds[-1] and set(out[0]) == set(jf.WRITES_COLUMNS[jf.TABLE])


def test_wiring():
    assert "async def _joint_forecast_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_joint_forecast_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in jf.WRITES_COLUMNS[jf.TABLE])
