"""T-112:World50 / 龙头腿 / 灵活组合在证据面单列 —— 各自的基准、不进配置层、开账前写开账日、对外文字不下结论。"""
import json

import numpy as np
import pandas as pd

from src.data.accounting import other_lines as ol
from src.data.accounting.registry import BOOKS
from src.data.allocation import allocator as al


def _nav(days, drift, seed):
    r = np.random.default_rng(seed).normal(drift, 0.01, len(days))
    return pd.Series(np.cumprod(1 + r), index=days)


def _navs(days):
    keys = ["world50:EW", "world50:EWxMom", "alt_leaders:TOP6", "alt_leaders:FO6", "alt_leaders:GATE_EW",
            "alt_leaders:ETH", "flex:CONST_35_50_15", "core", "tom_trader:CORE_FB", "tom_trader:CORE_H", "tom_trader:CORE_F",
            "tom_trader:BTC_FB", "tom_trader:BTC_H", "tom_trader:BTC_F", "tom_trader:BTC_S50",
            "tom_trader:ETH_FB", "tom_trader:ETH_H", "tom_trader:ETH_F", "tom_trader:ETH_S50",
            "tom_trader:CORE_X1V", "tom_trader:BTC_X1V", "tom_trader:ETH_X1V",
            "flex_x1v:T25", "flex_x1v:H_T25", "flex_x1v:T35"]
    return {k: _nav(days, 0.0005 * (i + 1), i) for i, k in enumerate(keys)}


def test_before_the_start_every_line_says_when_it_opens():
    days = pd.date_range("2026-10-01", periods=40, freq="D")
    rows = ol.other_line_rows(_navs(days), pd.Timestamp("2026-10-15"))
    assert len(rows) == len(ol.LINES)
    assert all(r["evidence_class"] == "not_started" for r in rows)
    assert {r["opens"] for r in rows if r["id"] in ("alt_top6", "flex_35_50_15")} == {ol.FORWARD_START}
    assert {r["opens"] for r in rows if r["line"] == "world50"} == {ol.WORLD50_OPEN}, "10-29:World50 不等 12-31"
    assert {r["opens"] for r in rows if r["line"] == "tom_trader" or r["id"] == "flex_x1v_t25"} == {"2026-10-16"}


def test_after_the_start_each_line_is_measured_against_its_own_benchmark():
    days = pd.date_range("2026-12-31", periods=60, freq="D")
    navs = _navs(days)
    rows = {r["id"]: r for r in ol.other_line_rows(navs, days[-1])}
    w = rows["world50_ewxmom"]
    assert w["evidence_class"] == "forward" and w["forward_days"] == 59
    tot = navs["world50:EWxMom"].iloc[-1] / navs["world50:EWxMom"].iloc[0] - 1
    ben = navs["world50:EW"].iloc[-1] / navs["world50:EW"].iloc[0] - 1
    assert abs(w["excess_vs_benchmark"] - (tot - ben)) < 1e-12
    ev = al.evidence(navs["world50:EWxMom"], navs["world50:EW"])
    assert w["anytime_lower_bound_ann"] == ev["mu_lo_cs"]
    assert rows["alt_top6"]["benchmark"] == "alt_leaders:GATE_EW"
    assert set(rows["alt_top6"]["also_same_window"]) == {"alt_leaders:ETH", "core"}
    assert rows["alt_gate_ew"]["benchmark"] == "core", "门本身对 ①(S-593:门在全市场上落后 ①)"
    assert rows["flex_35_50_15"]["benchmark"] is None and "excess_vs_benchmark" not in rows["flex_35_50_15"]
    json.dumps(list(rows.values()), allow_nan=False)


def test_unreadable_is_not_zero_and_young_is_descriptive():
    days = pd.date_range("2026-12-31", periods=5, freq="D")
    navs = _navs(days)
    navs.pop("alt_leaders:FO6")
    rows = {r["id"]: r for r in ol.other_line_rows(navs, days[-1])}
    assert rows["alt_fo6"]["evidence_class"] == "no_record"
    assert rows["alt_top6"]["evidence_class"] == "forward_young"


def test_other_lines_never_enter_the_allocation_layer():
    ids = {b.id for b in BOOKS}
    assert not ids & {ln.id for ln in ol.LINES}
    assert len({ln.id for ln in ol.LINES}) == len(ol.LINES)


def test_public_text_has_no_verdicts():
    text = json.dumps([ol.HOW_TO_READ_OTHER] + [[ln.name, ln.thesis] for ln in ol.LINES], ensure_ascii=False).lower()
    for w in ("outperforms", "beats", "positive edge", "buy", "sell", "accumulate", "avoid", "reduce"):
        assert w not in text


def test_the_real_money_line_is_measured_against_the_paper_t25():
    """10-29(P1):真钱账户对纸面 T25 —— 差距 = 实施缺口;开账前写开账日;只给收益。"""
    days = pd.date_range("2026-10-29", periods=30, freq="D")
    navs = {**_navs(days), "live:T25": _nav(days, 0.0002, 99)}
    early = {r["id"]: r for r in ol.other_line_rows(navs, pd.Timestamp("2026-10-28"))}
    assert early["t25_live"]["evidence_class"] == "not_started" and early["t25_live"]["opens"] == ol.LIVE_OPEN
    r = {x["id"]: x for x in ol.other_line_rows(navs, days[-1])}["t25_live"]
    assert r["benchmark"] == "flex_x1v:T25" and r["excess_vs_benchmark"] is not None
    assert "usd" not in json.dumps(r).lower(), "证据面不出美元额"
    missing = {r["id"]: r for r in ol.other_line_rows(_navs(days), days[-1])}["t25_live"]
    assert missing["evidence_class"] == "no_record", "读不到 ≠ 0"
