"""按币资金面空间(11-07):刷新只在上游有新一天时做、近邻摘要报独立簇、近邻函数只看到期的行。"""
from pathlib import Path

from src.data.state import asset_flow as af

ROOT = Path(__file__).resolve().parents[1]


def test_refresh_only_when_upstream_moved():
    assert af.needs_refresh("2026-11-05", "2026-11-06") is True
    assert af.needs_refresh("2026-11-06", "2026-11-06") is False
    assert af.needs_refresh(None, "2026-11-06") is True
    assert af.needs_refresh("2026-11-06", None) is False, "上游读不到不等于该刷"


def test_summary_counts_clusters_not_rows():
    nb = [{"symbol": "SOL", "d": f"2024-03-{i:02d}", "dist": 0.5, "x30": -0.1} for i in range(1, 21)] + \
         [{"symbol": "AVAX", "d": "2025-01-05", "dist": 0.6, "x30": 0.2}]
    s = af.summarize(nb, 30)
    assert s["n"] == 21 and s["symbols"] == 2 and s["clusters"] == 2, "21 个近邻只是 2 个独立簇"
    assert s["share_negative"] == round(20 / 21, 3) and s["median"] == -0.1
    assert af.summarize([], 30) == {"n": 0}


def test_extremes_pick_the_farthest_from_median():
    row = {"q_fund7": 0.02, "q_crowd": 0.55, "q_turn": 0.97, "q_dd90": 0.5, "fund7": -0.3, "turn": 1.2}
    ex = af.extremes(row, 2)
    assert [e["dim"] for e in ex] == ["fund7", "turn"]


def test_knn_function_is_point_in_time_and_vector_order_matches_dims():
    sql = (ROOT / "migrations/2026-11-07_asset_flow_daily.sql").read_text(encoding="utf-8")
    assert "a.d < p_d - greatest(p_h, 7)" in sql, "近邻只能来自结果已到期的行"
    body = sql[sql.index("then array["):sql.index("]::real[]::vector(11)")]
    order = [t.strip().split("*q_")[1].split("-")[0] for t in body.replace("then array[", "").split(",")]
    assert tuple(order) == af.DIMS, "向量维的次序必须和 DIMS 一致(解释近邻时按它读)"
