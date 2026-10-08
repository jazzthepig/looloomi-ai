"""T-067 / S-512:风格指数按时点、宽宇宙 —— 候选、刷新、分类映射、行标注、覆盖率、逐年差。"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.style.pit import (CODE_REF_PIT, MAX_CATEGORY_FETCH, annotate_rows, category_ids,  # noqa: E402
                                coverage_rows, needs_refresh, universe_candidates, yearly_gap)
from src.data.style.header import compute_style_index  # noqa: E402


def test_candidates_skip_unmapped_and_todays_members() -> None:
    c = universe_candidates(["AGIX", "BTC", "ZZZ", "FTT"], {"AGIX": "singularitynet", "BTC": "bitcoin", "FTT": "ftx-token"},
                            current={"BTC"})
    assert c == {"AGIX": "singularitynet", "FTT": "ftx-token"}, "映射不到的不猜,今天已在名单里的不重复"


def test_refresh_rules_and_cap() -> None:
    today = date(2026, 10, 8)
    have = {"A": {"coin_id": "a", "fetched_d": "2026-10-01"}, "B": {"coin_id": "b-old", "fetched_d": "2026-10-07"},
            "C": {"coin_id": "c", "fetched_d": "2026-08-01"}}
    todo = needs_refresh(have, {"A": "a", "B": "b", "C": "c", "D": "d"}, today)
    assert todo == ["B", "C", "D"], "新的、coin_id 变了的、过期的才重取"
    many = {f"S{i}": f"s{i}" for i in range(MAX_CATEGORY_FETCH + 50)}
    assert len(needs_refresh({}, many, today)) == MAX_CATEGORY_FETCH


def test_category_names_map_to_ids_and_unknown_names_drop() -> None:
    assert category_ids(["Layer 1 (L1)", "Meme", "Unknown"], {"Layer 1 (L1)": "layer-1", "Meme": "meme-token"}) == \
        ["layer-1", "meme-token"]


def test_pit_rows_count_members_outside_todays_lists() -> None:
    days = pd.date_range("2023-01-01", periods=5)
    price = pd.DataFrame({"A": np.linspace(1, 2, 5), "B": np.linspace(1, 1.5, 5), "C": np.linspace(1, 0.5, 5)}, index=days)
    mcap = pd.DataFrame({"A": 5e9, "B": 3e9, "C": 1e9}, index=days)
    rows = compute_style_index(price, mcap, {"A": "l1", "B": "l1", "C": "l1"}, {}, start="2023-01-02", end="2023-01-05")
    rows = annotate_rows(rows, current={"A"})
    r = next(x for x in rows if x["style"] == "top_l1" and x["weighting"] == "cap")
    assert r["code_ref"] == CODE_REF_PIT and r["n_not_in_today_lists"] == 2, "B、C 不在今天的名单上 —— 旧口径看不见它们"


def test_coverage_is_universe_over_market_ex_stables_and_never_guessed() -> None:
    days = pd.date_range("2023-01-01", periods=3)
    mcap = pd.DataFrame({"A": [1e10, 1e10, 1e10], "B": [5e6, 5e6, 5e6]}, index=days)
    total = pd.Series([3e10, 3e10], index=days[:2])
    stables = pd.Series([1e10, 1e10, 1e10], index=days)
    rows = coverage_rows(mcap, total, stables, {"A"}, days[0], days[-1])
    assert rows[0]["coverage"] == 0.5 and rows[0]["n_universe"] == 1, "小于 2,000 万美元的不算进宇宙"
    assert rows[2]["coverage"] is None, "分母缺的日子不猜"


def test_yearly_gap_is_old_minus_new_and_missing_endpoints_are_none() -> None:
    old = {("top_l1", "2022-12-31"): 1.0, ("top_l1", "2023-12-31"): 2.0}
    new = {("top_l1", "2022-12-31"): 1.0, ("top_l1", "2023-12-31"): 1.5}
    g = yearly_gap(old, new, [2023, 2024], ["top_l1"])
    assert g["top_l1"]["2023"] == 0.5 and g["top_l1"]["2024"] is None
