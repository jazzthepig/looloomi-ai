"""单票账本的账户内核(S-828 之后):进场当天被止损的票必须出场;名额、名义上限、同币、成本各有一条;不变量抓得住幽灵仓。"""
import pytest

from src.data.evaluation import ticket_account as ta


def _bars(px):                         # {sym: {day: (o, c)}} → bars
    return {s: [[d, o, 0, 0, c] for d, (o, c) in sorted(v.items())] for s, v in px.items()}


def _t(tid, sym, entry_d, entry_px, stop_px, exit_d, exit_px, reason="sma20", signal_d=None):
    return {"tid": tid, "symbol": sym, "signal_d": signal_d or entry_d, "entry_d": entry_d, "entry_px": entry_px, "stop_px": stop_px,
            "exit_d": exit_d, "exit_px": exit_px, "exit_reason": reason}


FLAT = {s: {f"2026-01-{d:02d}": (100.0, 100.0) for d in range(1, 11)} for s in ("A", "B", "C")}


def test_a_ticket_stopped_on_its_entry_day_exits_and_frees_its_slot():
    """S-828:旧研究引擎先处理开盘出场、再进场 ⇒ 这张票永不出场,名额被永久占住,后面的票进不来。"""
    tks = [_t(1, "A", "2026-01-02", 100.0, 90.0, "2026-01-02", 90.0, "stop"),
           _t(2, "B", "2026-01-03", 100.0, 90.0, "2026-01-05", 110.0)]
    r = ta.simulate(tks, ta.marks_from_bars(_bars(FLAT)), risk_frac=0.01, gross_cap=None, cap_n=1, cost=0.0)
    assert r["taken"] == {1, 2} and r["open_at_end"] == [], "同日止损的票出场了,名额让给了第二张"
    # 每票风险 1%、止损 10% ⇒ 名义 10% 净值:第一张 −1%,第二张按 0.99 的净值算 +10% × 10%
    assert r["curve"][-1][1] == pytest.approx(0.99 + 0.099 * 0.10, rel=1e-12)
    assert [n for _, _, n, _ in r["curve"]][:2] == [0, 1], "进场当天收盘已经不在场"


def test_slots_gross_cap_and_same_coin_each_block_for_their_own_reason():
    tks = [_t(1, "A", "2026-01-02", 100.0, 90.0, "2026-01-08", 100.0), _t(2, "B", "2026-01-02", 100.0, 90.0, "2026-01-08", 100.0),
           _t(3, "C", "2026-01-02", 100.0, 90.0, "2026-01-08", 100.0), _t(4, "A", "2026-01-03", 100.0, 90.0, "2026-01-08", 100.0)]
    m = ta.marks_from_bars(_bars(FLAT))
    r = ta.simulate(tks, m, risk_frac=0.01, gross_cap=None, cap_n=2, cost=0.0)
    assert r["taken"] == {1, 2} and r["blocked"]["cap"] == [3, 4], "名额 2:第三张与次日那张都被名额挡"
    r = ta.simulate(tks, m, risk_frac=0.01, gross_cap=0.25, cap_n=9, cost=0.0)     # 每张名义 10% ⇒ 上限 25% 只装得下两张
    assert r["taken"] == {1, 2} and r["blocked"]["gross"] == [3] and r["blocked"]["coin"] == [4]
    assert max(g for _, g in r["gross_ratio"]) == pytest.approx(0.20)
    r = ta.simulate(tks, m, risk_frac=0.01, gross_cap=None, cap_n=9, cost=0.0, min_notional=0.2)
    assert r["taken"] == set() and len(r["blocked"]["min"]) == 4, "名义低于最小额的不进"


def test_cost_is_charged_once_and_the_single_ticket_cap_is_half_of_equity():
    px = {"A": {"2026-01-02": (100.0, 100.0), "2026-01-03": (100.0, 100.0), "2026-01-04": (100.0, 100.0)}}
    r = ta.simulate([_t(1, "A", "2026-01-02", 100.0, 99.9, "2026-01-04", 100.0)], ta.marks_from_bars(_bars(px)),
                    risk_frac=0.01, gross_cap=None, cap_n=1, cost=0.004)
    # 止损只有 0.1% ⇒ 名义本来是净值的 10 倍,被单票上限截到一半;来回成本 0.4% × 0.5
    assert r["gross_ratio"][0][1] == pytest.approx(0.5)
    assert r["curve"][0][1] == pytest.approx(1 - 0.5 * 0.002) and r["curve"][-1][1] == pytest.approx(1 - 0.5 * 0.004)


def test_the_invariant_catches_a_ghost_position():
    """把同日出场的票伪装成「出场日早于进场日」(旧引擎的效果):strict 必须拦下,而不是让它活到窗口末。"""
    ghost = _t(1, "A", "2026-01-03", 100.0, 90.0, "2026-01-02", 90.0, "stop")
    with pytest.raises(AssertionError, match="不变量"):
        ta.simulate([ghost, _t(2, "B", "2026-01-03", 100.0, 90.0, "2026-01-06", 100.0)], ta.marks_from_bars(_bars(FLAT)),
                    risk_frac=0.01, gross_cap=None, cap_n=5, cost=0.0)


def test_marks_carry_the_last_close_and_never_invent_a_price():
    m = ta.marks_from_bars({"A": [["2026-01-02", 10.0, 0, 0, 11.0]]})
    assert m("A", "2026-01-02", True) == 10.0 and m("A", "2026-01-05", True) == 11.0 and m("A", "2026-01-01", False) is None
    assert m("ZZZ", "2026-01-02", False) is None
