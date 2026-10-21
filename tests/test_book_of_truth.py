"""R-v2 真相之书(docs/TRADER_TOM_DOCTRINE.md §11):纸面票 vs 交易所,逐票对账、违规、挣来的杠杆上限。"""
import datetime as dt

import pytest

from src.data.execution import book_of_truth as bt

ASOF = "2026-11-10"


def _p(sym, sig, status="closed", entry_d=None, entry=10.0, stop=9.0, exit_d=None, exit_px=None, r=None):
    s = dt.date.fromisoformat(sig)
    return {"ticket_id": f"{sym}:{sig}", "symbol": sym, "signal_d": sig, "status": status,
            "entry_d": entry_d or (s + dt.timedelta(days=1)).isoformat(), "entry_px": entry, "stop_px": stop,
            "exit_d": exit_d, "exit_px": exit_px, "exit_reason": "sma20" if exit_d else None, "r_mult": r}


_n = iter(range(10_000))


def _i(tid, act, mid, sleeve="r_v2_live", coin=None, why="", ts="2026-11-01T00:50:00+00:00", notional=100.0):
    ref = f"r_v2:{tid}:{act}" + (f":{why}" if why else "")
    return {"intent_id": f"i{next(_n)}", "ts_decision": ts, "symbol": coin or tid.split(":")[0], "side": "buy",
            "target_notional_usd": notional, "decision_mid": mid, "sleeve": sleeve, "signal_ref": ref,
            "order_type": "taker", "limit_price": mid}


def _o(intent, px, status="filled", fee=0.0, notional=100.0):
    return {"intent_id": intent["intent_id"], "status": status, "avg_fill_price": px if status in ("filled", "partial")
            else None, "filled_notional_usd": notional if px else 0.0, "fee_usd": fee}


def test_parse_ref():
    assert bt.parse_ref("r_v2:UNI:2026-10-19:exit:sma20") == ("UNI:2026-10-19", "exit", "sma20")
    assert bt.parse_ref("r_v2:kPEPE:2026-10-19:enter") == ("kPEPE:2026-10-19", "enter", "")
    assert bt.parse_ref("x1v:BTC") is None and bt.parse_ref(None) is None


def test_a_clean_live_ticket_reconciles_fills_slippage_and_r_against_the_paper():
    p = _p("UNI", "2026-11-01", exit_d="2026-11-05", exit_px=12.0, r=1.96)
    en, tr = _i(p["ticket_id"], "enter", 10.0), _i(p["ticket_id"], "stop_trigger", 9.0, ts="2026-11-01T00:51:00+00:00")
    ex = _i(p["ticket_id"], "exit", 12.0, why="sma20", ts="2026-11-05T00:50:00+00:00")
    outs = [_o(en, 10.05, fee=0.05), _o(tr, None, "cancelled"), _o(ex, 11.94, fee=0.05)]
    r = bt.reconcile([p], [en, tr, ex], outs, mode="live", asof=ASOF)
    (t,) = r["tickets"]
    v = t["venue"]
    assert t["class"] == "venue" and not t["breaches"] and v["stop_on_venue"] is True
    assert v["entry_vs_open_bps"] == pytest.approx(50.0) and v["exit_vs_plan_bps"] == pytest.approx(-50.0)
    # 风险比例 10%:(11.94 / 10.05 − 1) / 0.1 − 0.10 / 100 / 0.1
    assert v["r"] == pytest.approx((11.94 / 10.05 - 1) / 0.1 - 0.01, abs=1e-4)
    assert t["r_gap"] == pytest.approx(v["r"] - 1.96, abs=1e-4)
    assert r["summary"]["clean_share"] == 1.0 and r["summary"]["closed_on_venue"] == 1


def test_stop_fills_are_measured_against_the_stop_line():
    p = _p("SOL", "2026-11-01", exit_d="2026-11-03", exit_px=9.0, r=-1.04)
    en = _i(p["ticket_id"], "enter", 10.0)
    tr = _i(p["ticket_id"], "stop_trigger", 9.0, ts="2026-11-01T00:51:00+00:00")
    r = bt.reconcile([p], [en, tr], [_o(en, 10.0), _o(tr, 8.91)], mode="live", asof=ASOF)
    v = r["tickets"][0]["venue"]
    assert v["exit_kind"] == "stop_trigger" and v["stop_fill_vs_line_bps"] == pytest.approx(-100.0)
    assert r["summary"]["stop_fill_vs_line_bps_mean"] == pytest.approx(-100.0)


def test_breaches_no_record_unfilled_no_stop_late_exit_orphan_off_plan():
    a = _p("AAA", "2026-11-01", status="open")                                     # 纸面进了,主机没记录
    b = _p("BBB", "2026-11-01", status="open")                                     # 进场单没成交
    c = _p("CCC", "2026-11-01", status="open")                                     # 真钱进了,没挂止损
    d = _p("DDD", "2026-11-01", exit_d="2026-11-04", exit_px=11.0, r=0.96)         # 纸面出了 6 天,交易所还开着
    e = _p("EEE", "2026-11-01", status="open")                                     # 主机说不可执行
    ib, ic, idd = _i(b["ticket_id"], "enter", 10.0), _i(c["ticket_id"], "enter", 10.0), _i(d["ticket_id"], "enter", 10.0)
    itd = _i(d["ticket_id"], "stop_trigger", 9.0)
    orphan = _i("ZZZ:2026-11-02", "enter", 1.0)
    r = bt.reconcile([a, b, c, d, e], [ib, ic, idd, itd, orphan],
                     [_o(ib, None, "expired"), _o(ic, 10.0), _o(idd, 10.0), _o(orphan, 1.0)],
                     mode="live", asof=ASOF, host_skips={e["ticket_id"]: "不可执行:HL 没有这个永续"})
    got = {t["ticket_id"].split(":")[0]: (t["class"], t["breaches"]) for t in r["tickets"]}
    assert got["AAA"] == ("no_record", ["no_record"])
    assert got["BBB"] == ("unfilled", ["unfilled"])
    assert got["CCC"] == ("venue", ["no_stop"])
    assert got["DDD"] == ("venue", ["late_exit"])
    assert got["EEE"][0] == "not_executable" and not got["EEE"][1], "主机说了为什么 ⇒ 不是违规"
    assert [o["ticket_id"] for o in r["orphans"]] == ["ZZZ:2026-11-02"]
    assert r["summary"]["clean_share"] == 0.0


def test_the_host_entering_a_ticket_the_paper_cap_skipped_is_off_plan():
    rows = [_p(f"C{k:02d}", "2026-11-01", status="open") for k in range(11)]       # 11 张同一天,上限 10
    ins = [_i(x["ticket_id"], "enter", 10.0) for x in rows]
    trg = [_i(x["ticket_id"], "stop_trigger", 9.0) for x in rows]
    r = bt.reconcile(rows, ins + trg, [_o(i, 10.0) for i in ins], mode="live", asof=ASOF)
    off = [t["ticket_id"] for t in r["tickets"] if "off_plan" in t["breaches"]]
    assert off == ["C10:2026-11-01"], "同一天按名字先到先得,第 11 张纸面没取"


def test_dry_run_uses_virtual_fills_and_never_earns_leverage():
    p = _p("UNI", "2026-11-01", exit_d="2026-11-05", exit_px=12.0, r=1.96)
    en = _i(p["ticket_id"], "enter", 10.0, sleeve="r_v2_host_dry")
    sv = _i(p["ticket_id"], "stop_virtual", 9.0, sleeve="r_v2_host_dry", ts="2026-11-03T05:00:00+00:00")
    live_noise = _i(p["ticket_id"], "enter", 99.0)                                   # 另一个 sleeve,不算
    r = bt.reconcile([p], [en, sv, live_noise], [], mode="dry_run", asof=ASOF)
    v = r["tickets"][0]["venue"]
    assert v["virtual"] and v["entry_px"] == 10.0 and v["exit_kind"] == "stop_virtual" and v["stop_on_venue"] is None
    assert r["ladder"]["earned_max_leverage"] == 1.0 and "空跑" in r["ladder"]["why"]


def test_pending_tickets_are_not_breaches():
    p = _p("UNI", "2026-11-10", status="pending", entry_d=None)
    p["entry_d"] = None
    r = bt.reconcile([p], [], [], mode="live", asof=ASOF)
    assert r["tickets"][0]["class"] == "pending" and not r["tickets"][0]["breaches"]


@pytest.mark.parametrize("n,clean,serious,want", [
    (0, None, 0, 1.0), (19, 1.0, 0, 1.0), (20, 1.0, 0, 2.0), (49, 0.95, 0, 2.0), (50, 1.0, 0, 3.0),
    (100, 1.0, 0, 5.0), (100, 0.85, 0, 3.0), (60, 1.0, 1, 2.0), (25, 0.8, 2, 1.0), (10, 0.5, 3, 1.0)])
def test_earned_leverage_ladder(n, clean, serious, want):
    assert bt.earned_leverage(n, clean, serious)[0] == want


def test_host_skips_from_cycle_details():
    d = [{"book": "r_v2", "not_executable": [{"ticket_id": "A:2026-11-01", "why": "HL 没有"}],
          "skipped_cap_paper": ["B:2026-11-01"]}, {"book": "x1v", "not_executable": [{"ticket_id": "C:2026-11-01"}]}]
    assert bt.host_skips_from(d) == {"A:2026-11-01": "不可执行:HL 没有", "B:2026-11-01": "纸面满额跳过"}
