"""R-v2 单票在 HL 永续上的执行(Jazz 10-21:永续、真钱、先空跑)。

守的东西:计划只翻译账本、不重新判断信号;同时最多 10 张按纸面账本的先到先得;止损按比例给;空跑按中间价虚拟成交、
不碰私钥;live 进场后挂减仓止损触发单、出场前撤单;读不到永续账户时不把账上的票记成已平;回报按 (book, mode) 分 sleeve。
"""
import datetime as dt
import json
from dataclasses import asdict

import pytest

from src.data.execution import ticket_plan as tpm
from src.exec_host import core, tickets
from src.exec_host import runner as rn

NOW = dt.datetime(2026, 10, 22, 0, 50, tzinfo=dt.timezone.utc)
ASOF = "2026-10-21"
MASTER = "0x" + "cd" * 20


def _row(tid, sym, status, signal_d, entry_d=None, exit_d=None, exit_flag=False, atr=1.0, **kw):
    return {"ticket_id": tid, "symbol": sym, "status": status, "signal_d": signal_d, "entry_d": entry_d,
            "exit_d": exit_d, "exit_flag": exit_flag, "atr14": atr, "entry_px": kw.get("entry_px"),
            "stop_px": kw.get("stop_px"), "bars_held": kw.get("bars_held"), "exit_px": kw.get("exit_px"),
            "exit_reason": kw.get("exit_reason")}


# ── Railway:计划 ───────────────────────────────────────────────────────────
def test_cap_walk_is_the_kernel_rule_first_come_by_signal_day_then_symbol():
    d = dt.date
    rows = [_row("A", "AAA", "open", "2026-10-18", "2026-10-19"),
            _row("B", "BBB", "closed", "2026-10-18", "2026-10-19", exit_d="2026-10-22"),   # 出场日当天仍占位
            _row("C", "CCC", "pending", "2026-10-21"), _row("D", "DDD", "pending", "2026-10-21")]
    assert tpm.taken_ids(rows, 3, d(2026, 10, 22)) == {"A", "B", "C"}, "B 在 10-22 出场,当天仍占位 ⇒ 只剩一个位"
    assert tpm.taken_ids(rows, 3, d(2026, 10, 23)) == {"A", "B", "C", "D"}, "B 出场之后的进场日不再占位"
    assert tpm.taken_ids(rows, 2, d(2026, 10, 22)) == {"A", "B"}


def test_plan_translates_the_book_and_is_not_ready_until_the_scan_reached_asof():
    rows = [_row("P1", "UNI", "pending", ASOF, atr=0.4), _row("P0", "OLD", "pending", "2026-10-20"),
            _row("H", "SOL", "open", "2026-10-10", "2026-10-11"),
            _row("X", "ARB", "open", "2026-10-09", "2026-10-10", exit_flag=True),
            _row("S", "OP", "closed", "2026-10-01", "2026-10-02", exit_d=ASOF, exit_reason="stop")]
    closes = {("UNI", ASOF): 8.0}
    p = tpm.make_ticket_plan(rows, "2026-10-20", ASOF, closes)
    assert not p["ready"] and not p["enter"] and "2026-10-21" in p["why"]
    p = tpm.make_ticket_plan(rows, ASOF, ASOF, closes, risk_frac=0.005, cap=10)
    assert p["ready"] and [e["ticket_id"] for e in p["enter"]] == ["P1"], "只进信号日 = asof 的 pending"
    assert p["enter"][0]["stop_frac"] == pytest.approx(2.5 * 0.4 / 8.0)
    assert [h["ticket_id"] for h in p["hold"]] == ["H"]
    assert {x["ticket_id"]: x["why"] for x in p["exit"]} == {"X": "sma20", "S": "stop"}
    assert p["sleeves"] == {"dry_run": "r_v2_host_dry", "live": "r_v2_live"}


def test_a_ticket_without_a_signal_day_close_is_held_back_not_sized_on_a_guess():
    p = tpm.make_ticket_plan([_row("P1", "UNI", "pending", ASOF)], ASOF, ASOF, {})
    assert not p["enter"] and p["bad_stop"] == ["P1"]


# ── 主机:纯函数 ───────────────────────────────────────────────────────────
def test_perp_price_rules_coin_names_and_risk_sizing():
    assert tickets.round_px_perp(8.123456, 1) == 8.1235, "5 位有效数字"
    assert tickets.round_px_perp(0.0123456, 0) == 0.012346, "小数位 ≤ 6 − szDecimals"
    assert tickets.resolve_coin("PEPE", {"kPEPE": 0, "UNI": 1}) == "kPEPE"
    assert tickets.resolve_coin("UNI", {"kPEPE": 0, "UNI": 1}) == "UNI"
    assert tickets.resolve_coin("ZIL", {"UNI": 1}) is None
    s = tickets.size_entry(700.0, 0.005, 0.10, 8.0, 1)            # 风险 $3.5 ÷ 10% = $35
    assert s["qty"] == 4.3 and s["notional"] == pytest.approx(34.4) and s["why"] is None
    tiny = tickets.size_entry(700.0, 0.005, 0.40, 8.0, 1)         # $3.5 ÷ 40% = $8.75 < $10
    assert tiny["qty"] == 0 and "最小名义额" in tiny["why"]
    tight = tickets.size_entry(700.0, 0.005, 0.002, 8.0, 1)       # $3.5 ÷ 0.2% = $1,750 ⇒ 封顶净值一半
    assert tight["notional"] <= 350.0 and tight["capped"]
    lim, ot = tickets.trigger_order(7.2, 1)
    assert ot == {"trigger": {"triggerPx": 7.2, "isMarket": True, "tpsl": "sl"}} and lim < 7.2


def _tplan(enter=(), hold=(), exit_=(), cap=10, ready=True, asof=ASOF):
    return {"asof": asof, "ready": ready, "risk_frac": 0.005, "cap": cap, "enter": list(enter), "hold": list(hold),
            "exit": list(exit_), "skipped_cap": [], "sleeves": dict(tpm.TICKET_SLEEVE_FOR_MODE)}


def _e(tid, sym, stop_frac=0.1):
    return {"ticket_id": tid, "symbol": sym, "signal_d": ASOF, "atr14": 1.0, "ref_close": 10.0, "stop_frac": stop_frac}


def test_actions_reconcile_exit_and_refuse_without_substituting():
    szd = {"UNI": 1, "SOL": 2, "ARB": 1, "kPEPE": 0}
    mids = {"UNI": 8.0, "SOL": 150.0, "ARB": 0.5, "kPEPE": 0.01}
    book = {"H": {"coin": "SOL", "qty": 0.2}, "X": {"coin": "ARB", "qty": 50.0}, "G": {"coin": "OP", "qty": 10.0}}
    pos = {"SOL": 0.2, "ARB": 50.0}                                # OP 已经不在交易所上了
    act = tickets.ticket_actions(_tplan(enter=[_e("N1", "UNI"), _e("N2", "ZIL"), _e("N3", "SOL"), _e("N4", "PEPE", 0.6)],
                                        hold=[{"ticket_id": "H"}], exit_=[{"ticket_id": "X", "why": "sma20"}]),
                                 book, pos, mids, szd, 700.0, done=set())
    assert [c["ticket_id"] for c in act["closed_on_venue"]] == ["G"]
    assert act["exits"] == [{"ticket_id": "X", "coin": "ARB", "qty": 50.0, "why": "sma20"}]
    assert [e["ticket_id"] for e in act["entries"]] == ["N1"]
    why = {n["ticket_id"]: n["why"] for n in act["not_executable"]}
    assert "HL 上没有" in why["N2"] and "同一个币" in why["N3"] and "最小名义额" in why["N4"]
    full = tickets.ticket_actions(_tplan(enter=[_e("N1", "UNI")], hold=[{"ticket_id": "H"}], cap=1),
                                  {"H": {"coin": "SOL", "qty": 0.2}}, {"SOL": 0.2}, mids, szd, 700.0, set())
    assert not full["entries"] and "已满 1 张" in full["not_executable"][0]["why"]


# ── 主机:执行器 ───────────────────────────────────────────────────────────
class PerpVenue:
    def __init__(self, equity=704.0, positions=None, mids=None, ok=True, fill=True):
        self.equity, self.pos, self.ok, self.fill = equity, dict(positions or {}), ok, fill
        self.m = mids or {"UNI": 8.0, "SOL": 150.0}
        self.sent, self.triggers, self.cancels = [], [], []

    def perp_meta(self):
        return {"UNI": 1, "SOL": 2}

    def perp_mids(self):
        return dict(self.m)

    def perp_state(self):
        if not self.ok:
            return {"ok": False, "equity": 0.0, "positions": {}}
        return {"ok": True, "equity": self.equity, "positions": dict(self.pos)}

    mode, usdc = "default", 0.0

    def ticket_account(self):                                      # 与 runner.Venue 同一个纯函数
        st = self.perp_state()
        return tickets.account_for_tickets(st, self.mode, {"USDC": {"total": self.usdc, "hold": 0.0}}
                                           if self.mode in tickets.UNIFIED_MODES else None)

    def order_perp(self, coin, side, qty, px, cloid, reduce_only):
        self.sent.append({"coin": coin, "side": side, "qty": qty, "px": px, "reduce_only": reduce_only})
        if not self.fill:
            return {"status": "ok", "response": {"data": {"statuses": [{"error": "Order could not immediately match"}]}}}
        self.pos[coin] = self.pos.get(coin, 0.0) + (qty if side == "buy" else -qty)
        return {"status": "ok", "response": {"data": {"statuses": [{"filled": {"totalSz": str(qty), "avgPx": str(self.m[coin]), "oid": 9}}]}}}

    def stop_trigger(self, coin, qty, limit_px, order_type, cloid):
        self.triggers.append({"coin": coin, "qty": qty, "px": limit_px, "type": order_type})
        if getattr(self, "trigger_fail", False):
            return {"status": "ok", "response": {"data": {"statuses": [{"error": "Trigger rejected"}]}}}
        return {"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": 4242}}]}}}

    def cancel(self, coin, oid):
        self.cancels.append((coin, oid))
        return {"status": "ok"}

    def fills_since(self, t_ms):
        return [{"oid": 9, "fee": "0.01", "feeToken": "USDC", "px": "8", "crossed": True}]

    def exchange(self):
        raise AssertionError("测试里不建交易客户端")


class Rw:
    def plan(self):
        return 200, {}

    def report(self, payload):
        return 200, {}


def _exe(tmp_path, tmode, venue, tplan):
    cfg = rn.Config({"EXECUTOR_MODE": "dry_run", "EXECUTOR_TICKETS_MODE": tmode, "HL_ACCOUNT_ADDRESS": MASTER,
                     "EXECUTOR_TOKEN": "t", "EXECUTOR_STATE_DIR": str(tmp_path)})
    e = rn.Executor(cfg, venue, Rw(), clock=lambda: NOW)
    e.settle_s = 0
    e.state.set(ticket_plan=tplan)
    return e


def _ob(e):
    return [json.loads(p.read_text()) for p in e.outbox.pending()]


def test_dry_run_fills_virtually_at_mid_never_touches_the_exchange_and_reports_to_its_own_sleeve(tmp_path):
    v = PerpVenue(equity=0.0)                                      # 永续账户为空 ⇒ 按上限记账,写明来源
    e = _exe(tmp_path, "dry_run", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    assert not v.sent and not v.triggers
    b = e.state.get("ticket_book")["N1"]
    assert b["entry_px"] == 8.0 and b["stop_px"] == pytest.approx(7.2) and b["qty"] > 0
    (rep,) = _ob(e)
    assert rep["book"] == "r_v2" and rep["mode"] == "dry_run" and not rep.get("outcomes")
    assert rep["intents"][0]["sleeve"] == "r_v2_host_dry" and rep["intents"][0]["symbol"] == "UNI"
    assert "按上限" in rep["detail"]["equity_source"]
    e._maybe_ticket_cycle(NOW)
    assert len(_ob(e)) == 1, "同一个 asof 只跑一轮"
    # 盘中:现价跌破止损线 ⇒ 空跑按止损线虚拟平仓
    v.m["UNI"] = 7.1
    assert e.check_ticket_stops(NOW) == ["N1"]
    assert not e.state.get("ticket_book") and e.state.get("ticket_done")["N1"]["close_px"] == pytest.approx(7.2)


def test_dry_run_exits_a_ticket_that_left_the_hold_list(tmp_path):
    v = PerpVenue()
    e = _exe(tmp_path, "dry_run", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    nxt = NOW + dt.timedelta(days=1)
    e.clock = lambda: nxt
    e.state.set(ticket_plan=_tplan(asof="2026-10-22", exit_=[{"ticket_id": "N1", "why": "sma20"}]))
    r = e.run_ticket_cycle(nxt)
    assert [x["ticket_id"] for x in r["exits"]] == ["N1"] and not e.state.get("ticket_book")
    assert e.state.get("ticket_done")["N1"]["close_why"] == "出场"


def test_live_enters_ioc_then_hangs_a_reduce_only_stop_and_cancels_it_before_exiting(tmp_path):
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    (buy,) = v.sent
    assert buy["side"] == "buy" and not buy["reduce_only"] and buy["px"] > 8.0
    (trg,) = v.triggers
    assert trg["type"]["trigger"]["triggerPx"] == pytest.approx(7.2) and trg["qty"] == buy["qty"]
    b = e.state.get("ticket_book")["N1"]
    assert b["trigger_oid"] == 4242
    first, trig_rep, second = _ob(e)
    assert first["intents"] and not first.get("outcomes"), "意图先落盘"
    (ti,) = trig_rep["intents"]
    assert ti["signal_ref"] == "r_v2:N1:stop_trigger" and ti["order_type"] == "trigger" and ti["side"] == "sell"
    assert ti["decision_mid"] == pytest.approx(7.2) and b["trigger_intent_id"] == ti["intent_id"], "止损触发单也有意图"
    assert second["outcomes"][0]["status"] == "filled" and not second.get("intents")
    nxt = NOW + dt.timedelta(days=1)
    e.state.set(ticket_plan=_tplan(asof="2026-10-22", exit_=[{"ticket_id": "N1", "why": "time"}]))
    e.run_ticket_cycle(nxt)
    assert v.cancels == [("UNI", 4242)]
    sell = v.sent[-1]
    assert sell["side"] == "sell" and sell["reduce_only"] and sell["qty"] == buy["qty"]
    assert not e.state.get("ticket_book")
    cancelled = [o for r in _ob(e) for o in r.get("outcomes") or [] if o["intent_id"] == ti["intent_id"]]
    assert [o["status"] for o in cancelled] == ["cancelled"], "撤掉的触发单补一个 cancelled 结果"


def test_live_does_not_declare_positions_closed_when_the_account_cannot_be_read(tmp_path):
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    v.ok = False
    with pytest.raises(RuntimeError):
        e.check_ticket_stops(NOW)
    assert "N1" in e.state.get("ticket_book"), "读不到账户 ≠ 仓位没了"


def test_live_backup_stop_sells_reduce_only_when_the_trigger_did_not_fire(tmp_path):
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    v.m["UNI"] = 7.0
    assert e.check_ticket_stops(NOW) == ["N1"]
    sell = v.sent[-1]
    assert sell["side"] == "sell" and sell["reduce_only"]
    assert not e.state.get("ticket_book")


def test_unfilled_live_entry_leaves_no_book_row_and_no_trigger(tmp_path):
    v = PerpVenue(equity=704.0, fill=False)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    assert not v.triggers and not e.state.get("ticket_book")
    assert _ob(e)[-1]["outcomes"][0]["status"] == "expired"


# ── Railway:回报按 (book, mode) 分 sleeve ─────────────────────────────────
def test_report_vetting_keeps_the_two_books_apart():
    from src.api.routers.executor import vet_report
    i = asdict(core.make_intent({"symbol": "kPEPE", "side": "buy", "qty_base": 1.0, "price": 0.01}, "r_v2_host_dry",
                                "r_v2:x:enter", NOW, 0.0101))
    ok, why = vet_report({"mode": "dry_run", "kind": "cycle", "book": "r_v2", "intents": [i]})
    assert ok and not why
    assert vet_report({"mode": "dry_run", "kind": "cycle", "intents": [i]})[0] is None, "没有 book = X1V,kPEPE 不在现货表里"
    assert vet_report({"mode": "live", "kind": "cycle", "book": "r_v2", "intents": [i]})[0] is None, "空跑意图进不了真跑 sleeve"
    assert vet_report({"mode": "dry_run", "kind": "cycle", "book": "nope", "intents": [i]})[0] is None


def test_gross_notional_is_capped_across_tickets():
    szd = {"UNI": 1, "SOL": 2}
    mids = {"UNI": 8.0, "SOL": 150.0}
    book = {"H": {"coin": "SOL", "qty": 4.0, "entry_px": 150.0}}            # $600 名义,净值 700 ⇒ 已 0.86 倍
    act = tickets.ticket_actions(_tplan(enter=[_e("N1", "UNI", 0.02)], hold=[{"ticket_id": "H"}]),
                                 book, {"SOL": 4.0}, mids, szd, 700.0, set())
    assert not act["entries"] and "1.0 倍" in act["not_executable"][0]["why"], "Jazz 10-21:各层 0–1 倍,不加杠杆"


def test_a_failed_trigger_is_retried_at_most_every_15_minutes(tmp_path):
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    v.trigger_fail = True
    e._maybe_ticket_cycle(NOW)
    assert e.state.get("ticket_book")["N1"]["trigger_error"], "挂不上要记下来"
    assert "止损触发单没挂上" in _ob(e)[-1]["alert"]
    e.check_ticket_stops(NOW)
    e.check_ticket_stops(NOW + dt.timedelta(minutes=5))
    assert len(v.triggers) == 2, "进场时一次 + 第一次补挂;5 分钟内不再挂"
    v.trigger_fail = False
    e.check_ticket_stops(NOW + dt.timedelta(minutes=16))
    assert len(v.triggers) == 3 and e.state.get("ticket_book")["N1"]["trigger_oid"] == 4242


def test_loader_reads_the_book_state_and_signal_day_closes(monkeypatch):
    import asyncio

    import src.data.style.header as hdr
    seen = []

    async def fake(table, params):
        seen.append((table, params))
        if table == "r_tickets_paper":
            assert params["status"] == "in.(pending,open,closed)"
            return [_row("P1", "UNI", "pending", ASOF, atr=0.4)]
        if table == "r_tickets_state":
            return [{"last_d": ASOF}]
        if table == "ohlcv_daily":
            assert params["source"] == "eq.binance_hist" and params["trade_date"] == f"eq.{ASOF}"
            return [{"symbol": "UNI", "trade_date": ASOF, "close": 8.0}]
        if table in ("regime_calls", "j_tickets"):
            return []                                              # 没有 Jazz ⓪ 判断 ⇒ 系统默认
        if table == "oi_lev_snapshot_daily":
            return []                                              # S-690 快照没有;10-21 的窗口早过了 ⇒ 不过滤照常进
        raise AssertionError(table)
    monkeypatch.setattr(hdr, "_read_all", fake)
    monkeypatch.delenv("R_V2_RISK_FRAC", raising=False)
    p = asyncio.run(tpm.load_ticket_plan(ASOF))
    assert p["ready"] and p["risk_frac"] == 0.005 and p["enter"][0]["stop_frac"] == pytest.approx(0.125)
    assert p["oi_filter"]["status"] == "unavailable"
    monkeypatch.setenv("R_V2_RISK_FRAC", "0.05")
    with pytest.raises(ValueError):
        asyncio.run(tpm.load_ticket_plan(ASOF))


def test_portfolio_leverage_scales_the_allocation_and_is_capped_at_five():
    szd, mids = {"UNI": 1}, {"UNI": 8.0}
    one = tickets.ticket_actions(_tplan(enter=[_e("N1", "UNI", 0.1)]), {}, {}, mids, szd, 700.0, set())
    two = tickets.ticket_actions({**_tplan(enter=[_e("N1", "UNI", 0.1)]), "portfolio_leverage": 2.0}, {}, {}, mids, szd,
                                 700.0, set())
    assert one["entries"][0]["notional"] == pytest.approx(34.4) and two["entries"][0]["notional"] == pytest.approx(69.6)
    wild = tickets.ticket_actions({**_tplan(enter=[_e("N1", "UNI", 0.1)]), "portfolio_leverage": 50}, {}, {}, mids, szd,
                                  700.0, set())
    assert wild["portfolio_leverage"] == 5.0 and wild["alloc"] == 3500.0, "主机这一侧再守一次 5 倍上限"


def test_railway_refuses_a_leverage_outside_one_to_five(monkeypatch):
    import asyncio

    import src.data.style.header as hdr

    async def fake(table, params):
        return [{"last_d": ASOF}] if table == "r_tickets_state" else []
    monkeypatch.setattr(hdr, "_read_all", fake)
    monkeypatch.setenv("R_V2_PORTFOLIO_LEVERAGE", "2")
    assert asyncio.run(tpm.load_ticket_plan(ASOF))["portfolio_leverage"] == 2.0
    monkeypatch.setenv("R_V2_PORTFOLIO_LEVERAGE", "6")
    with pytest.raises(ValueError):
        asyncio.run(tpm.load_ticket_plan(ASOF))


# ── Book of Truth:交易所上发生的,按交易所记(doctrine §11)──────────────────
def test_close_fills_prefers_the_trigger_oid_then_close_long_fills_since_entry():
    fills = [{"coin": "UNI", "px": "7.0", "sz": "1", "time": 2000, "oid": 4242, "dir": "Close Long", "fee": "0.01"},
             {"coin": "UNI", "px": "6.0", "sz": "1", "time": 2000, "oid": 4242, "dir": "Close Long", "fee": "0.01"},
             {"coin": "UNI", "px": "9.0", "sz": "5", "time": 2000, "oid": 7, "dir": "Close Long", "fee": "0.1"},
             {"coin": "UNI", "px": "1.0", "sz": "9", "time": 10, "oid": 4242, "dir": "Close Long"},
             {"coin": "SOL", "px": "1.0", "sz": "9", "time": 2000, "oid": 4242, "dir": "Close Long"}]
    f = tickets.close_fills(fills, "UNI", 1000, 4242)
    assert f["px"] == pytest.approx(6.5) and f["sz"] == 2 and f["fee"] == pytest.approx(0.02) and f["n"] == 2
    g = tickets.close_fills(fills, "UNI", 1000, None)
    assert g["sz"] == 7 and g["px"] == pytest.approx((7 + 6 + 45) / 7), "没有 oid ⇒ 进场以来所有 Close Long"
    assert tickets.close_fills(fills, "ETH", 0, None) is None


def test_live_stop_fill_is_recorded_at_the_venue_price_not_assumed_at_the_stop_line(tmp_path):
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    b = e.state.get("ticket_book")["N1"]
    v.pos["UNI"] = 0.0                                             # 触发单在交易所上成交了,滑到 7.0(止损线 7.2)
    v.fills_since = lambda t_ms: [{"coin": "UNI", "px": "7.0", "sz": str(b["qty"]), "time": _ms_now() + 5,
                                   "oid": 4242, "dir": "Close Long", "fee": "0.02"}]
    e.check_ticket_stops(NOW)
    done = e.state.get("ticket_done")["N1"]
    assert done["close_px"] == pytest.approx(7.0) and done["close_px_source"] == "venue_fills"
    outs = [o for r in _ob(e) for o in r.get("outcomes") or [] if o["intent_id"] == b["trigger_intent_id"]]
    assert outs[0]["status"] == "filled" and outs[0]["avg_fill_price"] == pytest.approx(7.0)
    assert not e.state.get("truth_pending")


def test_fills_not_yet_visible_stay_pending_and_settle_on_a_later_minute(tmp_path):
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    b = e.state.get("ticket_book")["N1"]
    v.pos["UNI"] = 0.0
    v.fills_since = lambda t_ms: []
    e.check_ticket_stops(NOW)
    assert list(e.state.get("truth_pending")) == ["N1"], "成交还没出来 ⇒ 待查,不当没成交"
    v.fills_since = lambda t_ms: [{"coin": "UNI", "px": "7.1", "sz": str(b["qty"]), "time": _ms_now() + 5,
                                   "oid": 4242, "dir": "Close Long", "fee": "0"}]
    assert e.settle_truth(NOW + dt.timedelta(minutes=1)) == ["N1"]
    assert e.state.get("ticket_done")["N1"]["close_px"] == pytest.approx(7.1)


def test_a_close_we_did_not_send_is_written_down_as_a_venue_close(tmp_path):
    v = PerpVenue(equity=704.0)
    v.trigger_fail = True                                          # 没挂上触发单,然后仓位被手动平了
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    b = e.state.get("ticket_book")["N1"]
    assert not b.get("trigger_intent_id")
    v.pos["UNI"] = 0.0
    v.fills_since = lambda t_ms: [{"coin": "UNI", "px": "8.4", "sz": str(b["qty"]), "time": _ms_now() + 5,
                                   "oid": 55, "dir": "Close Long", "fee": "0"}]
    e.check_ticket_stops(NOW)
    rep = [r for r in _ob(e) if (r.get("detail") or {}).get("phase") == "venue_close"]
    assert rep and rep[0]["intents"][0]["signal_ref"] == "r_v2:N1:venue_close"
    assert rep[0]["outcomes"][0]["avg_fill_price"] == pytest.approx(8.4) and "手动" in rep[0]["alert"]


def test_a_failed_exit_clears_the_cancelled_trigger_so_it_is_hung_again(tmp_path):
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    v.fill = False
    nxt = NOW + dt.timedelta(days=1)
    e.state.set(ticket_plan=_tplan(asof="2026-10-22", exit_=[{"ticket_id": "N1", "why": "sma20"}]))
    e.run_ticket_cycle(nxt)
    b = e.state.get("ticket_book")["N1"]
    assert b["trigger_oid"] is None and "待重挂" in b["trigger_error"], "撤了触发单、出场又没成交 ⇒ 不能裸着"
    v.fill = True
    e.check_ticket_stops(nxt)
    assert e.state.get("ticket_book")["N1"]["trigger_oid"] == 4242


def test_dry_run_virtual_stop_is_written_as_an_intent(tmp_path):
    v = PerpVenue(equity=0.0)
    e = _exe(tmp_path, "dry_run", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    v.m["UNI"] = 7.1
    e.check_ticket_stops(NOW)
    (rep,) = [r for r in _ob(e) if r["kind"] == "stop"]
    (i,) = rep["intents"]
    assert i["signal_ref"] == "r_v2:N1:stop_virtual" and i["decision_mid"] == pytest.approx(7.2)
    from src.api.routers.executor import vet_report
    ok, why = vet_report({k: rep[k] for k in rep if k in ("mode", "kind", "book", "host", "asof", "intents", "outcomes",
                                                           "detail", "alert")})
    assert ok and not why, why


def test_every_report_the_live_host_writes_passes_railway_vetting(tmp_path):
    """触发单意图、撤销结果、venue_close(意图 + 结果同一批)都要过 Railway 的校验,否则发件箱会卡在 rejected/。"""
    from src.api.routers.executor import vet_report
    v = PerpVenue(equity=704.0)
    e = _exe(tmp_path, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1), _e("N2", "SOL", 0.1)]))
    e._maybe_ticket_cycle(NOW)
    v.pos["UNI"] = 0.0
    v.fills_since = lambda t_ms: [{"coin": "UNI", "px": "7.0", "sz": "100", "time": _ms_now() + 5, "oid": 4242,
                                   "dir": "Close Long", "fee": "0"}]
    e.check_ticket_stops(NOW)
    e.state.set(ticket_plan=_tplan(asof="2026-10-22", exit_=[{"ticket_id": "N2", "why": "time"}]))
    e.run_ticket_cycle(NOW + dt.timedelta(days=1))
    for r in _ob(e):
        ok, why = vet_report(r)
        assert ok, (r.get("detail"), why)


def _ms_now():
    return int(NOW.timestamp() * 1000)


# ── 10-29:HL 统一账户 + 组合层的名义上限 ─────────────────────────────────────
def test_unified_account_equity_is_spot_usdc_plus_losses_only():
    """10-29 实测:Jazz 的账户是 unifiedAccount,630 USDC 在现货,永续 marginSummary 全是 0。"""
    perp = tickets.parse_perp_state({"marginSummary": {"accountValue": "0.0"}, "assetPositions": [
        {"position": {"coin": "UNI", "szi": "2.0", "unrealizedPnl": "-3.5"}},
        {"position": {"coin": "SOL", "szi": "0.1", "unrealizedPnl": "5.0"}}]})
    assert perp["ok"] and perp["equity"] == 0.0 and perp["upnl"] == pytest.approx(1.5)
    bal = {"USDC": {"total": 630.64, "hold": 12.0}}
    u = tickets.account_for_tickets(perp, "unifiedAccount", bal)
    assert u["equity"] == pytest.approx(630.64), "浮盈不计(+1.5 不加)"
    loss = tickets.account_for_tickets({**perp, "upnl": -4.0}, "portfolioMargin", bal)
    assert loss["equity"] == pytest.approx(626.64), "浮亏要减"
    assert tickets.account_for_tickets(perp, "default", bal)["equity"] == 0.0, "标准账户:永续是永续,现货是现货"
    assert tickets.account_for_tickets(perp, None, None)["equity"] == 0.0, "模式读不到 ⇒ 按永续(不开新票)"


def test_live_host_on_a_unified_account_opens_the_ticket_the_perp_balance_would_have_refused(tmp_path):
    """零信号对照:同一个账户,标准模式读法 ⇒ 永续 0 ⇒ 一张不开(10-29 的 bug);统一账户读法 ⇒ 开。"""
    for mode, opens in (("default", False), ("unifiedAccount", True)):
        v = PerpVenue(equity=0.0)
        v.mode, v.usdc = mode, 630.64
        e = _exe(tmp_path / mode, "live", v, _tplan(enter=[_e("N1", "UNI", 0.1)]))
        e._maybe_ticket_cycle(NOW)
        assert bool(v.sent) is opens, mode
        if opens:
            assert v.sent[0]["qty"] * 8.0 == pytest.approx(630.64 * 0.005 / 0.1, rel=0.02), "单票风险 = 净值 × 0.5%"


def test_gross_cap_from_the_portfolio_layer_only_tightens():
    """Jazz 10-29:R-v2 名义合计 ≤ 净值 × 30%;单票风险仍按整个净值。主机只收紧,计划给 > 1 也按 1。"""
    szd, mids = {"UNI": 1, "SOL": 2}, {"UNI": 8.0, "SOL": 150.0}
    book = {"H": {"coin": "SOL", "qty": 1.2, "entry_px": 150.0}}                 # 已有 $180 名义
    plan = {**_tplan(enter=[_e("N1", "UNI", 0.1)], hold=[{"ticket_id": "H"}]), "gross_cap_frac": 0.30}
    act = tickets.ticket_actions(plan, book, {"SOL": 1.2}, mids, szd, 630.0, set())
    assert not act["entries"] and "0.3 倍" in act["not_executable"][0]["why"], "180 + 31.2 > 630 × 0.3 = 189"
    act = tickets.ticket_actions({**plan, "gross_cap_frac": 0.30}, {}, {}, mids, szd, 630.0, set())
    assert act["entries"] and act["gross_cap_frac"] == 0.30
    loose = tickets.ticket_actions({**plan, "gross_cap_frac": 3.0}, book, {"SOL": 1.2}, mids, szd, 630.0, set())
    assert loose["gross_cap_frac"] == 1.0, "放大不了"


def test_x1v_nav_cap_is_the_crypto_leg_budget_when_the_plan_carries_one():
    assert rn.x1v_nav_cap({"portfolio": {"x1v_nav_budget_usd": 180.0}}, 3000.0)[0] == 180.0
    assert rn.x1v_nav_cap({}, 3000.0) == (3000.0, "EXECUTOR_MAX_NAV_USD"), "旧计划没有组合层 ⇒ 环境变量"
    assert rn.x1v_nav_cap({"portfolio": {"x1v_nav_budget_usd": 5000.0}}, 3000.0)[0] == 3000.0, "只能收紧"
    assert rn.x1v_nav_cap({"portfolio": {"x1v_nav_budget_usd": "x"}}, 3000.0)[0] == 3000.0
    # 统一账户里 630 USDC:X1V 全仓目标时只用 $180,其余留给现金腿 / R-v2 保证金
    st = core.book_state({"USDC": {"total": 630.64, "hold": 0.0}}, {}, 180.0, 10.0)
    assert st["nav_book"] == pytest.approx(180.0) and st["nav_raw"] == pytest.approx(630.64)
