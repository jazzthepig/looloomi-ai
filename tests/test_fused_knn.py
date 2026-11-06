"""融合状态近邻臂(11-06):键冻结、按时点 z(只用更早的值)、重合维数不够不比、结果没出的最近 31 天不算近邻、接进 ③ 与周信。"""
from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.state import fused_knn as fk  # noqa: E402

D0 = dt.date(2021, 1, 1)


def _rows(n=900, seed=3):
    rng = random.Random(seed)
    return [{"d": (D0 + dt.timedelta(days=i)).isoformat(), "f": {k: rng.gauss(0, 1) for k in fk.KEYS}} for i in range(n)]


def test_keys_frozen_without_drifting_levels():
    assert len(fk.KEYS) == len(set(fk.KEYS)) == 56
    for bad in ("macro:total_mcap", "macro:total_volume", "macro:fed_net_liquidity", "pos:n_symbols", "regime_coverage_30d"):
        assert bad not in fk.KEYS


def test_pit_vectors_use_only_earlier_values():
    rows = _rows(400)
    v = fk.pit_vectors(rows)
    first = rows[fk.MIN_HIST]["d"]
    assert all(x is None for x in v[rows[fk.MIN_HIST - 1]["d"]]) and v[first][0] is not None
    rows2 = [dict(r) for r in rows]
    rows2[-1] = {"d": rows[-1]["d"], "f": {k: 1e6 for k in fk.KEYS}}           # 改最后一天,不能影响更早的 z
    v2 = fk.pit_vectors(rows2)
    assert v2[rows[-2]["d"]] == v[rows[-2]["d"]]


def test_distance_needs_overlap():
    a = [0.0] * len(fk.KEYS)
    b = [1.0] * len(fk.KEYS)
    assert abs(fk.distance(a, b) - len(fk.KEYS) ** 0.5) < 1e-9
    half = [None] * (len(fk.KEYS) // 2) + [1.0] * (len(fk.KEYS) - len(fk.KEYS) // 2)
    assert fk.distance(a, half) is None


def test_rates_exclude_recent_days_and_shrink():
    rows = _rows(900)
    vecs = fk.pit_vectors(rows)
    fwd = {r["d"]: 0.2 if i % 3 == 0 else (-0.2 if i % 3 == 1 else 0.0) for i, r in enumerate(rows[:-40])}
    d = rows[-1]["d"]
    r = fk.rates(vecs, fwd, d, k=100)
    assert r["probs"] and abs(sum(r["probs"].values()) - 1) < 0.01 and r["vector_d"] == d
    cutoff = (dt.date.fromisoformat(d) - dt.timedelta(days=fk.EXCLUDE_DAYS)).isoformat()
    assert all(x <= cutoff for x in r["nearest"])
    assert fk.rates(vecs, fwd, "2020-01-01")["probs"] is None


def test_wiring():
    ed = (ROOT / "src/data/execution/exposure_decision.py").read_text(encoding="utf-8")
    assert "fused_knn" in ed and 'prefix="F"' in ed
    import inspect
    from src.data.execution import exposure_decision as e
    assert "fused" not in inspect.getsource(e.rule_exposure), "融合近邻只是描述臂"
    from src.data.ops.weekly_letter import public_edition
    assert "融合近邻臂" in public_edition("作者 seth:exposure-knn-fused 与 seth:exposure-knn")
