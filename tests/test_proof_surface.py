"""T-053:证据面与配置层同一口径;读不到 ≠ 0;不满 60 天只描述;有警示 / 退役单列;对外文字不下结论。"""
import json

import numpy as np
import pandas as pd

from src.data.accounting.proof import HOW_TO_READ, evidence_class, proof_rows
from src.data.accounting.registry import Book
from src.data.allocation import allocator as al


def _nav(days, drift, seed):
    r = np.random.default_rng(seed).normal(drift, 0.02, len(days))
    return pd.Series(np.cumprod(1 + r), index=days)


def test_classes():
    assert evidence_class("retired_by_design", "", 200) == "retired"
    assert evidence_class("paper", "数字不可信", 200) == "caveat"
    assert evidence_class("paper", "", al.MIN_DAYS) == "forward"
    assert evidence_class("paper", "", al.MIN_DAYS - 1) == "forward_young"


def test_rows_share_the_allocation_window_and_bound():
    days = pd.date_range(pd.Timestamp(al.INCEPTION) - pd.Timedelta(days=20), periods=120, freq="D")
    core = _nav(days, 0.001, 1)
    books = [Book("core_cap", "①", "core", "c", "t", "arms"), Book("x", "②", "x", "c", "t", "arms"),
             Book("dead", "④", "d", "c", "t", "plain", status="retired_by_design"),
             Book("gone", "②", "g", "c", "t", "arms")]
    navs = {"x": _nav(days, 0.002, 2), "dead": _nav(days, 0.0, 3)}
    rows = {r["id"]: r for r in proof_rows(books, navs, core, {"x": {"weight": 0.0, "d": "2026-12-01"}}, days[-1])}
    assert rows["x"]["window"][0] == al.INCEPTION
    ev = al.evidence(al.forward_window(navs["x"], days[-1]), al.forward_window(core, days[-1]))
    assert rows["x"]["anytime_lower_bound_ann"] == ev["mu_lo_cs"] and rows["x"]["forward_days"] == ev["n_days"]
    assert rows["dead"]["evidence_class"] == "retired"
    assert rows["gone"]["evidence_class"] == "no_record"
    assert rows["core_cap"]["l3_weight"] is None
    json.dumps(list(rows.values()), allow_nan=False)


def test_public_text_has_no_verdicts():
    text = json.dumps(HOW_TO_READ, ensure_ascii=False).lower()
    for w in ("outperforms", "beats", "positive edge", "buy", "sell"):
        assert w not in text
