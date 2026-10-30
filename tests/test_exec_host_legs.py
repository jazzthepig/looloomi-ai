"""T25 的黄金 / 股票腿在 HL 现货上执行(Jazz 10-30:XAUT0 @182、SPYX @703,与 X1V 同一个账户、同一套意图 / 成交记录)。

钉住:建仓 / 偏离带 / 再平衡日三种情形、取整与卖单上限、空跑不下单、停着不提交、Railway 侧只收认得的腿、
R-v2 净值把现货代币算进去、每日真钱快照用主机估的市值。"""
import datetime as dt
import json
import pathlib

import pytest

from src.api.routers import executor as api
from src.data.accounting import live_account as la
from src.data.execution import dry_run as dr
from src.data.execution import portfolio_targets as pt
from src.exec_host import legs, tickets
from src.exec_host import runner as rn
from tests.test_exec_host import MASTER, FakeRailway, _outbox, _plan

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "hl_spot"
NOW = dt.datetime(2026, 10, 31, 0, 31, tzinfo=dt.timezone.utc)
MID = {"@182": 4000.0, "@703": 700.0}


class _LegClient:
    """真实的 spotMeta(含 XAUT0 / SPYX 与 @209 那一对 USDT0),盘口是合成的:每档 5 个,价差 ±0.05%。"""

    def spot_meta(self):
        return json.loads((FIX / "spotMeta.json").read_text())

    def spot_meta_and_asset_ctxs(self):
        return json.loads((FIX / "spotMetaAndAssetCtxs.json").read_text())

    def l2_book(self, coin):
        m = MID[coin]
        return {"coin": coin, "time": 1, "levels": [[{"px": str(m * (1 - 5e-4 * k)), "sz": "5", "n": 1} for k in (1, 2, 3)],
                                                    [{"px": str(m * (1 + 5e-4 * k)), "sz": "5", "n": 1} for k in (1, 2, 3)]]}


def _lq():
    return dr._spot_quotes_sync(_LegClient(), legs.LEG_TOKENS)


def _t25(rebalance=False, gold=120.0, eq=180.0):
    return {"capital_usd": 600.0, "band": 0.05, "rebalance_today": rebalance,
            "legs": {"XAUT0": {"target_usd": gold, "sleeve": "gold"}, "SPYX": {"target_usd": eq, "sleeve": "equity"}}}


def _bal(usdc=600.0, xaut=0.0, spyx=0.0, xaut_hold=0.0):
    return {"USDC": {"total": usdc, "hold": 0.0}, "XAUT0": {"total": xaut, "hold": xaut_hold},
            "SPYX": {"total": spyx, "hold": 0.0}}


class LegVenue:
    def __init__(self, balances):
        self.b, self.sent = balances, []

    def balances(self):
        return self.b

    def quotes(self, tokens=None):
        if tokens:
            return _lq()
        from tests.test_executor_dry_run import _quotes
        return _quotes()

    def mids(self, pairs):
        return {s: MID.get(p, 1.0) for s, p in pairs.items()}

    def fills_since(self, t_ms):
        return [{"oid": 9, "fee": "0.05", "feeToken": "USDC", "px": "1", "crossed": True}]

    def order(self, pair, side, qty, limit_px, cloid):
        self.sent.append({"pair": pair, "side": side, "qty": qty, "px": limit_px})
        return {"status": "ok", "response": {"data": {"statuses": [{"filled": {"totalSz": str(qty), "avgPx": str(limit_px),
                                                                                   "oid": 9}}]}}}


def _ex(tmp_path, t25_mode, venue, t25=None):
    cfg = rn.Config({"EXECUTOR_MODE": "dry_run", "EXECUTOR_T25_MODE": t25_mode, "EXECUTOR_TICKETS_MODE": "off",
                     "HL_ACCOUNT_ADDRESS": MASTER, "EXECUTOR_TOKEN": "t", "EXECUTOR_STATE_DIR": str(tmp_path)})
    plan = {**_plan(asof=rn.asof_for(NOW)), "portfolio": {"x1v_nav_budget_usd": 180.0, "t25": t25 or _t25()}}
    e = rn.Executor(cfg, venue, FakeRailway(plan), clock=lambda: NOW)
    e.settle_s = 0
    e.state.set(plan=plan)
    return e


# ── 报价与纯函数 ────────────────────────────────────────────────────────────
def test_leg_quotes_take_the_usdc_pair_not_the_usdt0_one():
    q = _lq()
    assert q["XAUT0"]["pair"] == "@182", "XAUT0 还有 @209 XAUT0/USDT0 —— 只认 USDC 计价那一对"
    assert q["SPYX"]["pair"] == "@703"
    assert q["XAUT0"]["sz_decimals"] == 2 and q["SPYX"]["sz_decimals"] == 2
    assert q["XAUT0"]["mid"] == pytest.approx(4000.0) and q["XAUT0"]["bid"] < q["XAUT0"]["ask"]


def test_first_connection_builds_both_legs_and_sells_come_first():
    lo = legs.leg_orders(_t25(), legs.holdings_usd(_bal(), _lq()))
    assert [(o["symbol"], o["side"], o["notional_usd"]) for o in lo["orders"]] == [("SPYX", "buy", 180.0),
                                                                                  ("XAUT0", "buy", 120.0)]
    assert lo["skipped"] == [], "持仓 0 ⇒ 偏离 = 目标本身 > 5% ⇒ 不等再平衡日,直接建仓"
    over = legs.leg_orders(_t25(), {"XAUT0": 200.0, "SPYX": 100.0})
    assert [o["side"] for o in over["orders"]] == ["sell", "buy"], "卖在前,先腾出 USDC"


def test_inside_the_band_nothing_moves_unless_it_is_a_rebalance_day():
    held = {"XAUT0": 135.0, "SPYX": 170.0}                       # 偏离 2.5% / 1.7%
    lo = legs.leg_orders(_t25(), held)
    assert lo["orders"] == [] and len(lo["skipped"]) == 2 and "不是再平衡日" in lo["skipped"][0]["why"]
    rb = legs.leg_orders(_t25(rebalance=True), held)
    assert {(o["symbol"], o["side"], o["notional_usd"]) for o in rb["orders"]} == {("XAUT0", "sell", 15.0),
                                                                                  ("SPYX", "buy", 10.0)}
    tiny = legs.leg_orders(_t25(rebalance=True), {"XAUT0": 125.0, "SPYX": 180.0})
    assert tiny["orders"] == [] and all("最小名义额" in s["why"] for s in tiny["skipped"])


def test_no_quote_means_no_order_not_a_zero_position():
    lo = legs.leg_orders(_t25(), {"SPYX": 0.0})
    assert [o["symbol"] for o in lo["orders"]] == ["SPYX"]
    assert lo["skipped"] == [{"symbol": "XAUT0", "why": "没有盘口报价 —— 持仓读不到,不下单"}]
    assert legs.leg_orders({**_t25(), "legs": {"PAXG": {"target_usd": 50}}}, {})["skipped"][0]["symbol"] == "PAXG"


def test_sizing_rounds_down_to_two_decimals_and_sells_never_exceed_the_free_balance():
    q = _lq()
    sized, refused = legs.size_leg_orders(legs.leg_orders(_t25(), {"XAUT0": 0.0, "SPYX": 0.0})["orders"], q, _bal())
    by = {o["symbol"]: o for o in sized}
    assert refused == [] and by["XAUT0"]["qty_base"] == 0.03 and by["SPYX"]["qty_base"] == 0.25
    assert by["XAUT0"]["pair"] == "@182" and by["XAUT0"]["notional_rounded"] == pytest.approx(120.0)
    sell = [{"symbol": "XAUT0", "side": "sell", "notional_usd": 200.0}]
    s2, _ = legs.size_leg_orders(sell, q, _bal(xaut=0.06, xaut_hold=0.02))
    assert s2[0]["qty_base"] == 0.04, "只卖可用的(0.06 − 挂单占用 0.02)"
    s3, _ = legs.size_leg_orders(sell, q, _bal(xaut=0.0))
    assert s3 == [], "没有可卖的 ⇒ 不出单"


# ── 执行器 ──────────────────────────────────────────────────────────────────
def test_dry_run_records_leg_intents_and_never_orders(tmp_path):
    v = LegVenue(_bal())
    e = _ex(tmp_path, "dry_run", v)
    out = e.run_t25_cycle(NOW)
    assert v.sent == [] and out["outcomes"] == []
    (rep,) = _outbox(e)
    assert rep["book"] == "t25" and rep["mode"] == "dry_run" and rep["kind"] == "cycle"
    assert {i["symbol"] for i in rep["intents"]} == {"XAUT0", "SPYX"}
    assert all(i["sleeve"] == legs.SLEEVES["dry_run"] for i in rep["intents"])
    assert rep["detail"]["pairs"] == {"XAUT0": "@182", "SPYX": "@703"} and "T25 腿" in rep["alert"]
    clean, why = api.vet_report(rep)
    assert why == [] and clean["book"] == "t25", "Railway 收这一批"
    assert e.state.get("t25_done_asof") == rn.asof_for(NOW)


def test_live_submits_ioc_on_the_usdc_pairs_and_records_one_outcome_per_intent(tmp_path):
    v = LegVenue(_bal())
    e = _ex(tmp_path, "live", v)
    out = e.run_t25_cycle(NOW)
    assert [(s["pair"], s["side"]) for s in v.sent] == [("@703", "buy"), ("@182", "buy")]
    assert v.sent[0]["px"] > 700.0, "买单限价在中间价之上(IOC 带)"
    assert [o["status"] for o in out["outcomes"]] == ["filled", "filled"]
    reps = _outbox(e)
    assert [len(r.get("intents") or []) for r in reps] == [2, 0] and len(reps[1]["outcomes"]) == 2
    assert reps[0]["alert"] is None and "T25 腿真单" in reps[1]["alert"], "真跑:意图那条不报警,结果那条报"
    for r in reps:
        assert api.vet_report(r)[1] == []
    assert out["outcomes"][0]["mid_at_resolve"] == pytest.approx(700.0), "成交后中间价按这一轮的币对取,不是 X1V 的"


def test_halted_live_records_intents_and_cancels_them_without_submitting(tmp_path):
    v = LegVenue(_bal())
    e = _ex(tmp_path, "live", v)
    e.cfg.halt_file.write_text("x")
    out = e.run_t25_cycle(NOW)
    assert v.sent == [] and {o["status"] for o in out["outcomes"]} == {"cancelled"}
    assert "已停,不提交" in _outbox(e)[0]["alert"]


def test_cycle_gate_runs_once_per_plan_and_not_when_off(tmp_path):
    v = LegVenue(_bal())
    e = _ex(tmp_path, "dry_run", v)
    e._maybe_t25_cycle(NOW)
    e._maybe_t25_cycle(NOW)
    assert len(_outbox(e)) == 1, "同一个 asof 只跑一轮"
    e.cfg.t25_mode = "live"
    e._maybe_t25_cycle(NOW)
    assert len(v.sent) == 2, "当天空跑过、切 live ⇒ live 当场跑一轮"
    e._maybe_t25_cycle(NOW)
    assert len(v.sent) == 2, "live 也只跑一轮"
    off = _ex(tmp_path / "off", "off", LegVenue(_bal()))
    off._maybe_t25_cycle(NOW)
    assert _outbox(off) == []
    no_t25 = _ex(tmp_path / "old", "dry_run", LegVenue(_bal()))
    no_t25.state.set(plan={**no_t25.state.get("plan"), "portfolio": {"x1v_nav_budget_usd": 180.0}})
    no_t25._maybe_t25_cycle(NOW)
    assert _outbox(no_t25) == [], "旧计划没有 t25 段 ⇒ 不动"


def test_live_needs_the_exchange_but_dry_run_does_not(tmp_path):
    for mode, raises in (("dry_run", True), ("live", False)):
        cfg = rn.Config({"EXECUTOR_MODE": "dry_run", "EXECUTOR_TICKETS_MODE": "off", "EXECUTOR_T25_MODE": mode,
                         "HL_ACCOUNT_ADDRESS": MASTER, "EXECUTOR_TOKEN": "t", "EXECUTOR_STATE_DIR": str(tmp_path)})
        v = rn.Venue(cfg, info=object(), exchange="sentinel")
        if raises:
            with pytest.raises(RuntimeError):
                v.exchange()
        else:
            assert v.exchange() == "sentinel"
    with pytest.raises(SystemExit):
        rn.Config({"EXECUTOR_T25_MODE": "yes", "HL_ACCOUNT_ADDRESS": MASTER, "EXECUTOR_TOKEN": "t"})


# ── Railway 侧 / 记账 ───────────────────────────────────────────────────────
def test_railway_accepts_only_the_two_legs_under_their_own_sleeves():
    base = {"mode": "dry_run", "kind": "cycle", "book": "t25", "host": "h", "asof": "2026-10-30"}
    intent = {"intent_id": "a", "ts_decision": "2026-10-31T00:31:00+00:00", "symbol": "XAUT0", "side": "buy",
              "target_notional_usd": 120.0, "decision_mid": 4000.0, "sleeve": legs.SLEEVES["dry_run"],
              "signal_ref": "t25:x", "order_type": "taker", "limit_price": 4020.0}
    assert api.vet_report({**base, "intents": [intent]})[1] == []
    assert api.vet_report({**base, "intents": [{**intent, "symbol": "BTC"}]})[1], "BTC 不是 T25 腿"
    assert api.vet_report({**base, "intents": [{**intent, "sleeve": legs.SLEEVES["live"]}]})[1], "sleeve 跟 mode 走"
    assert api.vet_report({**base, "book": "x1v", "intents": [intent]})[1], "X1V 那本账不收 XAUT0"


def test_rv2_equity_counts_the_spot_tokens_at_their_usdc_mids():
    meta_ctxs = json.loads((FIX / "spotMetaAndAssetCtxs.json").read_text())
    names = {int(t["index"]): t["name"] for t in meta_ctxs[0]["tokens"]}
    px = {names[u["tokens"][0]]: float(meta_ctxs[1][u["index"]]["midPx"]) for u in meta_ctxs[0]["universe"]
          if u["index"] in (182, 703) and meta_ctxs[1][u["index"]].get("midPx")}
    tot, vals = tickets.spot_value_usd(_bal(usdc=300.0, xaut=0.03, spyx=0.25), meta_ctxs)
    assert set(vals) == set(px) and tot == pytest.approx(sum(q * px[k] for k, q in (("XAUT0", 0.03), ("SPYX", 0.25)) if k in px))
    perp = tickets.parse_perp_state({"marginSummary": {"accountValue": "0.0"}, "assetPositions": []})
    u = tickets.account_for_tickets(perp, "unifiedAccount", _bal(usdc=300.0), spot_tokens_usd=300.0)
    assert u["equity"] == pytest.approx(600.0) and "现货代币 300.00" in u["basis"]
    assert tickets.spot_value_usd({}, None) == (0.0, {}), "读不到 ⇒ 0(偏小,偏安全)"


def test_daily_snapshot_values_legs_from_the_host_heartbeat():
    beat = {"at": "2026-10-31T23:50:00Z", "detail": {"kind": "heartbeat", "trade_account": MASTER,
                                                     "balances": {"USDC": 300.0, "XAUT0": 0.03, "SPYX": 0.25},
                                                     "account": {"spot_values": {"XAUT0": 120.0, "SPYX": 175.0}}}}
    prev = {"d": "2026-10-30", "equity_usd": 600.0, "nav": 1.0}
    r = la.snapshot_row("2026-10-31", [beat], {}, 0.0, [], prev)
    assert r["equity_usd"] == pytest.approx(595.0) and "HL 中间价" in " ".join(r.get("notes") or [r.get("note") or ""])


def test_plan_fields_carry_the_leg_targets_from_the_same_weights():
    f = pt.plan_fields("2026-10-30")["t25"]
    assert f["capital_usd"] == 600 and f["band"] == pt.DRIFT_BAND
    assert f["legs"] == {"XAUT0": {"target_usd": 120.0, "sleeve": "gold"}, "SPYX": {"target_usd": 180.0, "sleeve": "equity"}}
    assert set(f["legs"]) == set(legs.LEG_TOKENS), "目标表与执行器认的是同两条腿"
