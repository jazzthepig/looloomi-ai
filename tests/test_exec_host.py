"""T-015 云主机执行器:空跑不碰私钥、意图先于订单落盘、每个意图恰好一个结果、两个停、盘中止损不依赖 Railway、
对交易所只有 `order` 一种写操作;Railway 侧的计划与回报校验。"""
import ast
import asyncio
import datetime as dt
import json
import pathlib
from dataclasses import asdict

import pytest

from src.data.execution import executor as ex
from src.data.execution.host_plan import HOST_DRY_SLEEVE, LIVE_SLEEVE, SLEEVE_FOR_MODE
from src.exec_host import core
from src.exec_host import runner as rn

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 20, 0, 31, tzinfo=dt.timezone.utc)
MASTER = "0x" + "ab" * 20


def _quotes():
    from tests.test_executor_dry_run import _quotes as q
    return q()


def _plan(targets=None, stop=None, asof="2026-10-19"):
    q = _quotes()
    return {"ok": True, "asof": asof, "targets": targets if targets is not None else {"BTC": 0.5, "ETH": 0.0},
            "stop_px": stop if stop is not None else {"BTC": q["BTC"]["mid"] * 0.8, "ETH": q["ETH"]["mid"] * 0.8},
            "signal_ref": ex.SIGNAL_REF, "limits": asdict(ex.Limits()), "sleeves": dict(SLEEVE_FOR_MODE),
            "halted": False, "halt_status": "miss"}


class FakeRailway:
    def __init__(self, plan=None, code=200):
        self.plan_resp, self.code, self.reports = plan, code, []

    def plan(self):
        return 200, self.plan_resp

    def report(self, payload):
        self.reports.append(payload)
        return self.code, {"ok": True}


class FakeVenue:
    def __init__(self, balances, quotes, response=None, fills=None, mids=None):
        self.b, self.q, self.sent = balances, quotes, []
        self.response = response or (lambda pair, side, qty, px: {"status": "ok", "response": {"type": "order", "data": {
            "statuses": [{"filled": {"totalSz": str(qty), "avgPx": str(px), "oid": 77}}]}}})
        self.fills = fills if fills is not None else [{"oid": 77, "fee": "0.35", "feeToken": "USDC", "px": "1", "crossed": True}]
        self.m = mids or {s: q["mid"] for s, q in quotes.items()}

    def balances(self):
        return self.b

    def quotes(self):
        return self.q

    def mids(self, pairs):
        return dict(self.m)

    def fills_since(self, t_ms):
        return self.fills

    def order(self, pair, side, qty, limit_px, cloid):
        self.sent.append({"pair": pair, "side": side, "qty": qty, "px": limit_px, "cloid": cloid})
        return self.response(pair, side, qty, limit_px)


def _cfg(tmp_path, mode="dry_run"):
    return rn.Config({"EXECUTOR_MODE": mode, "HL_ACCOUNT_ADDRESS": MASTER, "EXECUTOR_TOKEN": "t",
                      "EXECUTOR_STATE_DIR": str(tmp_path)})


def _ex(tmp_path, mode, venue, plan):
    e = rn.Executor(_cfg(tmp_path, mode), venue, FakeRailway(plan), clock=lambda: NOW)
    e.settle_s = 0
    e.state.set(plan=plan)
    return e


def _usdc(n, btc=0.0, eth=0.0):
    return {"USDC": {"total": n, "hold": 0.0}, "UBTC": {"total": btc, "hold": 0.0}, "UETH": {"total": eth, "hold": 0.0}}


def _outbox(e):
    return [json.loads(p.read_text()) for p in e.outbox.pending()]


# ── 纯函数 ──────────────────────────────────────────────────────────────────
def test_hl_spot_price_rules_and_the_ioc_band():
    assert core.round_px_spot(82122.7, 5) == 82123.0, "5 位有效数字"
    assert core.round_px_spot(2407.137, 4) == 2407.1
    assert core.round_px_spot(0.0123456789, 2) == 0.012346, "小数位 ≤ 8 − szDecimals"
    assert core.ioc_limit_px(100_000.0, "buy", 50, 5) == 100_500.0
    assert core.ioc_limit_px(100_000.0, "sell", 50, 5) == 99_500.0


def test_book_state_caps_the_nav_and_sets_dust_aside():
    q = _quotes()
    b = _usdc(5_000.0, btc=0.00001, eth=0.5)
    st = core.book_state(b, q, nav_cap=3_000.0, min_notional=10.0)
    assert "BTC" in st["dust_usd"] and "BTC" not in st["holdings_usd"], "卖不掉的零头不算持仓"
    eth = 0.5 * q["ETH"]["mid"]
    assert abs(st["nav_book"] - 3_000.0) < 1e-6 and abs(st["cash_eff"] - (3_000.0 - eth)) < 1e-6
    assert st["nav_raw"] > 5_000.0, "上限只限制记账,不改变真实净值的报告"


def test_order_responses_map_to_exactly_one_terminal_outcome():
    i = core.make_intent({"symbol": "BTC", "side": "buy", "qty_base": 0.01, "price": 100_000.0}, LIVE_SLEEVE, "x", NOW, 100_500.0)
    ok = {"status": "ok", "response": {"data": {"statuses": [{"filled": {"totalSz": "0.006", "avgPx": "100010", "oid": 5}}]}}}
    nomatch = {"status": "ok", "response": {"data": {"statuses": [{"error": "Order could not immediately match against any resting orders. asset=10142"}]}}}
    fills = [{"oid": 5, "fee": "0.0000042", "feeToken": "UBTC", "px": "100010", "crossed": True}]
    p = core.outcome_for(i, 0.01, core.parse_order_response(ok), fills, 100_020.0, 1.0, 1.4, NOW)
    assert p.status == "partial" and abs(p.filled_notional_usd - 600.06) < 1e-6 and p.liquidity == "taker"
    assert abs(p.fee_usd - 0.0000042 * 100010) < 1e-9, "以基础币计的手续费按成交价折成 USDC"
    assert core.outcome_for(i, 0.01, core.parse_order_response(nomatch), [], 1.0, 1, 2, NOW).status == "expired"
    assert core.outcome_for(i, 0.01, core.parse_order_response({"status": "err", "response": "bad"}), [], 1.0, 1, 2, NOW).status == "cancelled"
    assert core.cloid_for(i.intent_id) == "0x" + i.intent_id.replace("-", "")


# ── 空跑 ────────────────────────────────────────────────────────────────────
def test_dry_run_records_intents_from_real_balances_and_never_builds_an_exchange(tmp_path):
    q = _quotes()
    v = FakeVenue(_usdc(868.85), q)
    e = _ex(tmp_path, "dry_run", v, _plan())
    out = e.run_cycle(NOW)
    assert not v.sent and out["outcomes"] == []
    (rep,) = _outbox(e)
    assert rep["mode"] == "dry_run" and rep["kind"] == "cycle" and rep["asof"] == "2026-10-19"
    (it,) = rep["intents"]
    assert it["sleeve"] == HOST_DRY_SLEEVE and it["symbol"] == "BTC" and it["side"] == "buy"
    assert it["target_notional_usd"] <= 0.5 * 868.85 + 1e-6, "按真实余额定尺寸,不是纸面 3,000"
    assert it["limit_price"] > q["BTC"]["mid"] and "BTC buy" in rep["alert"]
    assert e.state.get("done_asof") == "2026-10-19"
    with pytest.raises(RuntimeError):
        rn.Venue(_cfg(tmp_path), info=object()).exchange()


def test_the_cycle_runs_once_per_asof_and_waits_for_yesterdays_plan(tmp_path):
    v = FakeVenue(_usdc(1000.0), _quotes())
    e = _ex(tmp_path, "dry_run", v, _plan(asof="2026-10-18"))
    e._maybe_cycle(NOW)
    assert not e.outbox.pending(), "计划还是前天的 ⇒ 不跑"
    e.state.set(plan=_plan())
    e._maybe_cycle(NOW)
    e._maybe_cycle(NOW)
    assert len(e.outbox.pending()) == 1


# ── 真跑 ────────────────────────────────────────────────────────────────────
def test_live_submits_ioc_with_the_intent_as_client_id_and_resolves_every_intent(tmp_path):
    q = _quotes()
    v = FakeVenue(_usdc(1000.0), q)
    e = _ex(tmp_path, "live", v, _plan())
    e.run_cycle(NOW)
    (sent,) = v.sent
    first, second = _outbox(e)
    (it,) = first["intents"]
    assert first["intents"] and not first.get("outcomes"), "意图先落盘,在订单之前"
    assert sent["cloid"] == core.cloid_for(it["intent_id"]) and sent["pair"] == "@142"
    assert sent["qty"] * sent["px"] <= 1000.0, "买单不超过可用 USDC"
    (oc,) = second["outcomes"]
    assert oc["intent_id"] == it["intent_id"] and oc["status"] == "filled" and oc["fee_usd"] == 0.35
    assert it["sleeve"] == LIVE_SLEEVE and "真单" in second["alert"]


def test_halt_file_stops_submission_but_still_records_what_would_have_happened(tmp_path):
    v = FakeVenue(_usdc(1000.0), _quotes())
    e = _ex(tmp_path, "live", v, _plan())
    (tmp_path / "HALT").touch()
    e.run_cycle(NOW)
    assert not v.sent
    first, second = _outbox(e)
    assert first["intents"] and "已停" in first["alert"]
    assert [o["status"] for o in second["outcomes"]] == ["cancelled"], "真跑 sleeve 里不留没有结果的意图"


def test_railway_halt_is_kept_when_the_flag_cannot_be_read(tmp_path):
    e = _ex(tmp_path, "live", FakeVenue(_usdc(1.0), _quotes()), _plan())
    e.railway = FakeRailway({**_plan(), "halted": True, "halt_status": "hit"})
    e.refresh_plan(NOW)
    assert e.halted()[0]
    e._last.clear()
    e.railway = FakeRailway({**_plan(), "halted": False, "halt_status": "error"})
    e.refresh_plan(NOW)
    assert e.halted()[0], "读不到一键停 ≠ 解除"
    e._last.clear()
    e.railway = FakeRailway({**_plan(), "halted": False, "halt_status": "miss"})
    e.refresh_plan(NOW)
    assert not e.halted()[0]


# ── 盘中灾难止损 ────────────────────────────────────────────────────────────
def test_catastrophe_stop_exits_from_the_cached_plan_once_per_day(tmp_path):
    q = _quotes()
    mid = q["BTC"]["mid"]
    v = FakeVenue(_usdc(10.0, btc=0.01), q, mids={"BTC": mid * 0.7, "ETH": q["ETH"]["mid"]})
    e = _ex(tmp_path, "live", v, _plan(stop={"BTC": mid * 0.8, "ETH": None}))
    e.railway = None                                   # 止损不需要 Railway
    e.state.set(pairs={"BTC": {"pair": "@142", "sz_decimals": 5}, "ETH": {"pair": "@151", "sz_decimals": 4}})
    assert e.check_stops(NOW) == ["BTC"]
    (sent,) = v.sent
    assert sent["side"] == "sell" and sent["qty"] == 0.01 and sent["px"] < mid * 0.7
    assert e.check_stops(NOW) == [], "同一天不止第二次"
    kinds = [r["kind"] for r in _outbox(e)]
    assert kinds == ["stop", "stop"] and "灾难止损" in _outbox(e)[0]["alert"]


def test_ex_stop_line_is_the_same_definition_as_catastrophe_hit():
    import numpy as np
    import pandas as pd
    c = pd.Series(np.linspace(100, 130, 40))
    line = ex.stop_price(c)
    assert line == float(c.iloc[-20:].min()) * ex.CATASTROPHE
    assert ex.catastrophe_hit(line * 0.999, c) and not ex.catastrophe_hit(line * 1.001, c)
    assert ex.stop_price(c.iloc[:10]) is None


# ── 发件箱 ──────────────────────────────────────────────────────────────────
def test_outbox_delivers_in_order_parks_rejections_and_keeps_the_rest(tmp_path):
    ob = rn.Outbox(tmp_path / "ob")
    for k in ("cycle", "heartbeat", "stop"):
        ob.put({"kind": k})
    seq = iter([(200, {}), (422, {"rejected": ["x"]}), (503, "down")])

    class R:
        def report(self, payload):
            return next(seq)
    r = ob.flush(R())
    assert r == {"sent": 1, "rejected": 1, "pending": 1}
    assert [json.loads(p.read_text())["kind"] for p in ob.pending()] == ["stop"]
    assert len(list((tmp_path / "ob" / "rejected").glob("*.json"))) == 1


# ── 只有一种写操作 ───────────────────────────────────────────────────────────
_FORBIDDEN = ("withdraw", "usd_transfer", "spot_transfer", "usd_class_transfer", "vault_usd_transfer", "approve_agent",
              "approve_builder_fee", "update_leverage", "update_isolated_margin", "sub_account_transfer", "send_asset",
              "set_referrer", "convert_to_multi_sig_user", "market_close", "bulk_cancel")


def test_the_host_package_calls_only_order_on_the_exchange():
    for p in (ROOT / "src" / "exec_host").glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Call) and ast.unparse(n.func.value.func).endswith("exchange")}
        assert calls <= {"order"}, f"{p.name}: {calls}"
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
                {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not names & set(_FORBIDDEN), f"{p.name}: {names & set(_FORBIDDEN)}"


def test_the_private_key_is_read_in_exactly_one_place():
    hits = [(p.name, n.lineno) for p in (ROOT / "src" / "exec_host").glob("*.py")
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and n.value == "HL_API_WALLET_PRIVATE_KEY"]
    assert len(hits) == 1 and hits[0][0] == "runner.py", hits


# ── Railway 侧 ──────────────────────────────────────────────────────────────
def test_report_vetting_rejects_rather_than_drops():
    from src.api.routers.executor import vet_report
    i = asdict(core.make_intent({"symbol": "BTC", "side": "buy", "qty_base": 0.01, "price": 1.0}, HOST_DRY_SLEEVE, "x", NOW, 1.0))
    ok, why = vet_report({"mode": "dry_run", "kind": "cycle", "intents": [i]})
    assert ok and not why
    assert vet_report({"mode": "dry_run", "kind": "cycle", "intents": [{**i, "sleve": 1}]})[0] is None
    assert vet_report({"mode": "live", "kind": "cycle", "intents": [i]})[0] is None, "空跑的意图不能写进真跑 sleeve"
    out = {"intent_id": i["intent_id"], "ts_resolved": NOW.isoformat(), "status": "filled"}
    assert vet_report({"mode": "dry_run", "kind": "cycle", "outcomes": [out]})[0] is None, "空跑没有成交结果"
    assert vet_report({"mode": "live", "kind": "cycle", "outcomes": [{**out, "status": "open"}]})[0] is None
    assert vet_report({"mode": "live", "kind": "cycle", "outcomes": [out]})[0] is not None
    assert vet_report({"mode": "live", "kind": "cycle", "extra": 1})[0] is None


def test_token_gate_fails_closed(monkeypatch):
    from fastapi import HTTPException

    from src.api.routers.executor import _token_ok
    monkeypatch.delenv("EXECUTOR_TOKEN", raising=False)
    with pytest.raises(HTTPException) as e:
        _token_ok("anything", "EXECUTOR_TOKEN")
    assert e.value.status_code == 503
    monkeypatch.setenv("EXECUTOR_TOKEN", "s3cret")
    with pytest.raises(HTTPException) as e:
        _token_ok("s3cre", "EXECUTOR_TOKEN")
    assert e.value.status_code == 403
    _token_ok("s3cret", "EXECUTOR_TOKEN")


def test_plan_core_ships_targets_and_stop_lines_from_the_same_kernel(monkeypatch):
    import src.data.execution.host_plan as hp
    import src.data.universe.forward_books as fb
    from tests.test_executor_dry_run import _closes
    closes = {"BTC": _closes(end="2026-10-19"), "ETH": _closes(end="2026-10-19", seed=2)}

    async def inputs(end):
        return closes, {}
    monkeypatch.setattr(fb, "tom_inputs", inputs)
    hp._CORE_CACHE.clear()
    core_ = asyncio.run(hp.plan_core("2026-10-19"))
    assert core_["ok"] and core_["targets"] == {s: round(w, 6) for s, w in ex.target_weights(closes).items()}
    assert core_["stop_px"]["BTC"] == ex.stop_price(closes["BTC"])
    assert core_["sleeves"] == {"dry_run": HOST_DRY_SLEEVE, "live": LIVE_SLEEVE}
    hp._CORE_CACHE.clear()
    late = asyncio.run(hp.plan_core("2026-10-20"))
    assert not late["ok"] and "2026-10-20" in late["why"]
