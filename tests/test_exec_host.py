"""T-015 云主机执行器:空跑不碰私钥、意图先于订单落盘、每个意图恰好一个结果、两个停、盘中止损不依赖 Railway、
对交易所只有 `order` / `cancel` 两种写操作;Railway 侧的计划与回报校验。"""
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
        # `cancel`:R-v2 单票出场前撤掉自己挂的减仓止损触发单(撤单动不了钱);其余写操作一律不许
        assert calls <= {"order", "cancel"}, f"{p.name}: {calls}"
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


# ── 子账户(HL_SUBACCOUNT_ADDRESS)──────────────────────────────────────────
SUB = "0x" + "cd" * 20


class FakeInfo:
    def __init__(self, subs=None, fail=False):
        self.users, self.subs, self.fail = [], subs, fail

    def spot_user_state(self, user):
        self.users.append(("spot", user))
        return {"balances": []}

    def user_state(self, user):
        self.users.append(("perp", user))
        return {"marginSummary": {"accountValue": "0"}, "assetPositions": []}

    def user_fills_by_time(self, user, t_ms):
        self.users.append(("fills", user))
        return []

    def query_sub_accounts(self, user):
        if self.fail:
            raise TimeoutError("hl down")
        self.users.append(("subs", user))
        return self.subs


def _sub_cfg(tmp_path, sub=SUB, mode="dry_run", tickets="dry_run"):
    return rn.Config({"EXECUTOR_MODE": mode, "EXECUTOR_TICKETS_MODE": tickets, "HL_ACCOUNT_ADDRESS": MASTER,
                      "HL_SUBACCOUNT_ADDRESS": sub, "EXECUTOR_TOKEN": "t", "EXECUTOR_STATE_DIR": str(tmp_path)})


def test_subaccount_is_optional_and_must_be_a_different_address(tmp_path):
    assert _cfg(tmp_path).trade_account == MASTER and _cfg(tmp_path).subaccount is None, "不设 ⇒ 照旧整个主账户"
    assert _sub_cfg(tmp_path).trade_account == SUB
    with pytest.raises(SystemExit):
        _sub_cfg(tmp_path, sub="0x123")
    with pytest.raises(SystemExit):
        _sub_cfg(tmp_path, sub=MASTER.upper().replace("0X", "0x"))


def test_with_a_subaccount_every_read_is_on_the_subaccount_not_the_master(tmp_path):
    info = FakeInfo()
    v = rn.Venue(_sub_cfg(tmp_path), info=info)
    v.balances(), v.perp_state(), v.fills_since(0)
    assert info.users == [("spot", SUB), ("perp", SUB), ("fills", SUB)], \
        "Jazz 在主账户手动交易:执行器读主账户就会把他的仓位当成自己的"


def test_orders_on_a_subaccount_are_signed_by_the_same_api_wallet_with_vault_address(tmp_path, monkeypatch):
    """不依赖本机装没装 SDK(Mac 上的 preflight 没装 hyperliquid / eth_account):把三个模块换成假的。"""
    import sys
    import types
    built = {}

    class FakeExchange:
        def __init__(self, wallet, url, **kw):
            built.update(kw, wallet=wallet.address, url=url)

    class FakeAccount:
        @staticmethod
        def from_key(k):
            return types.SimpleNamespace(address="0xagent")

    utils = types.ModuleType("hyperliquid.utils")
    utils.constants = types.SimpleNamespace(MAINNET_API_URL="https://api.hyperliquid.xyz")
    mods = {"hyperliquid": types.ModuleType("hyperliquid"), "hyperliquid.exchange": types.ModuleType("hyperliquid.exchange"),
            "hyperliquid.utils": utils, "eth_account": types.ModuleType("eth_account")}
    mods["hyperliquid.exchange"].Exchange = FakeExchange
    mods["eth_account"].Account = FakeAccount
    for k, m in mods.items():
        monkeypatch.setitem(sys.modules, k, m)
    monkeypatch.setenv("HL_API_WALLET_PRIVATE_KEY", "0x" + "11" * 32)
    rn.Venue(_sub_cfg(tmp_path, mode="dry_run", tickets="live"), info=object()).exchange()
    assert built["vault_address"] == SUB and built["account_address"] == MASTER and built["wallet"] == "0xagent"
    built.clear()
    rn.Venue(rn.Config({"EXECUTOR_MODE": "live", "HL_ACCOUNT_ADDRESS": MASTER, "EXECUTOR_TOKEN": "t",
                        "EXECUTOR_STATE_DIR": str(tmp_path)}), info=object()).exchange()
    assert built["vault_address"] is None, "不设子账户 ⇒ 不带 vaultAddress(照旧)"


def test_a_subaccount_that_is_not_under_the_master_refuses_to_start(tmp_path):
    cfg = _sub_cfg(tmp_path)
    mine = rn.Venue(cfg, info=FakeInfo(subs=[{"name": "cometcloud-rv2", "subAccountUser": SUB.upper().replace("0X", "0x")}]))
    assert mine.subaccount_check() == {"ok": True, "address": SUB, "name": "cometcloud-rv2"}
    rn.refuse_foreign_subaccount(mine)
    foreign = rn.Venue(cfg, info=FakeInfo(subs=[{"name": "x", "subAccountUser": "0x" + "ee" * 20}]))
    assert foreign.subaccount_check()["ok"] is False
    with pytest.raises(SystemExit):
        rn.refuse_foreign_subaccount(foreign)
    none = rn.Venue(cfg, info=FakeInfo(subs=None))
    assert none.subaccount_check()["ok"] is False, "主账户名下一个子账户都没有"
    down = rn.Venue(cfg, info=FakeInfo(fail=True))
    assert down.subaccount_check()["ok"] is None, "读不到 ≠ 不是"
    rn.refuse_foreign_subaccount(down)
    assert rn.Venue(_cfg(tmp_path), info=FakeInfo()).subaccount_check()["ok"] is None


# ── 切 live 前:API 钱包是不是主账户批准的 agent ─────────────────────────────
AGENT = "0x" + "77" * 20


class RoleInfo:
    def __init__(self, role=None, agents=None, fail=False):
        self.role, self.agents, self.fail = role, agents, fail

    def user_role(self, user):
        if self.fail:
            raise TimeoutError("hl down")
        return self.role

    def extra_agents(self, user):
        return self.agents or []


def _live_venue(tmp_path, info, tickets="live"):
    import types
    cfg = rn.Config({"EXECUTOR_MODE": "dry_run", "EXECUTOR_TICKETS_MODE": tickets, "HL_ACCOUNT_ADDRESS": MASTER,
                     "EXECUTOR_TOKEN": "t", "EXECUTOR_STATE_DIR": str(tmp_path)})
    return rn.Venue(cfg, info=info, exchange=types.SimpleNamespace(wallet=types.SimpleNamespace(address=AGENT)))


def test_live_refuses_to_start_when_the_api_wallet_is_not_an_approved_agent(tmp_path):
    ok = _live_venue(tmp_path, RoleInfo(role={"role": "agent", "data": {"user": MASTER.upper().replace("0X", "0x")}},
                                        agents=[{"name": "x", "address": AGENT, "validUntil": 1830000000000}]))
    c = ok.agent_check()
    assert c["ok"] is True and c["agent"] == AGENT and c["valid_until"].startswith("2027-")
    rn.refuse_unapproved_agent(ok)
    other = _live_venue(tmp_path, RoleInfo(role={"role": "agent", "data": {"user": "0x" + "ee" * 20}}))
    assert other.agent_check()["ok"] is False, "批准它的是别的主账户"
    with pytest.raises(SystemExit):
        rn.refuse_unapproved_agent(other)
    missing = _live_venue(tmp_path, RoleInfo(role={"role": "missing"}))
    assert missing.agent_check()["ok"] is False, "没批准 / 已过期"
    down = _live_venue(tmp_path, RoleInfo(fail=True))
    assert down.agent_check()["ok"] is None, "读不到 ≠ 没批准"
    rn.refuse_unapproved_agent(down)


def test_dry_run_never_checks_the_agent_and_never_reads_the_key(tmp_path):
    v = rn.Venue(_cfg(tmp_path), info=RoleInfo(fail=True))
    rn.refuse_unapproved_agent(v)                 # dry_run:直接返回,不建交易客户端
    with pytest.raises(RuntimeError):
        v.exchange()
