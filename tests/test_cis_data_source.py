"""T-023:CIS universe 的数据层级统一成整数,并给每行 data_source(T1 / T1_stale / T2)。

10-06 实测 `data_tier` 混着 "T1"(18 行)与 1(19 行);前端徽章按 `data_tier === 1` 染色,
字符串那 18 个 T1 显示成琥珀色的「TT1」。
"""
import inspect

from src.api.routers import cis
from src.api.routers.cis import normalize_tiers


def test_mixed_tier_types_become_ints_with_a_source():
    u = [{"symbol": "A", "data_tier": "T1"}, {"symbol": "B", "data_tier": 1}, {"symbol": "C", "data_tier": 2},
         {"symbol": "D"}, {"symbol": "E", "data_tier": "T2"}, {"symbol": "F", "data_tier_label": "T1"}]
    n1 = normalize_tiers(u, t1_fresh=True)
    assert n1 == 3
    assert [a["data_tier"] for a in u] == [1, 1, 2, 2, 2, 1]
    assert [a["data_source"] for a in u] == ["T1", "T1", "T2", "T2", "T2", "T1"]


def test_stale_t1_is_labelled_stale():
    u = [{"data_tier": 1}, {"data_tier": 2}]
    normalize_tiers(u, t1_fresh=False)
    assert [a["data_source"] for a in u] == ["T1_stale", "T2"]


def test_every_universe_return_path_normalizes():
    src = inspect.getsource(cis._build_cis_universe)
    for name in ("merged", "railway_universe", "stale_universe", "lkg_universe"):
        assert f"normalize_tiers({name}" in src, name
