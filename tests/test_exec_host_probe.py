"""现货止损触发单探针(11-02):远离市价、刚过最小名义额、不超过可卖量一半;挂上就一定撤(出错也撤);报出三个答案。"""
import datetime as dt
from pathlib import Path

import pytest

from src.exec_host import probe_spot_trigger as pr

NOON = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)


def test_plan_is_far_from_market_and_just_over_min_notional():
    # 11-02 真跑:XAUT0 szDecimals = 2 ⇒ 一张最少 0.01;两张同时挂(0.02)超过可卖量 0.029979 的一半,被正确拒了 ⇒ 改成逐张
    p = pr.plan_probe(free_qty=0.029979, mid=3877.2, sz_decimals=2, n_orders=1)
    assert p["ok"] and p["qty"] == 0.01 and p["trigger_px"] == pytest.approx(1938.6, rel=1e-3)
    assert p["limit_px"] == pytest.approx(1744.7, rel=1e-3) and p["notional_at_limit"] >= 10.0
    assert not pr.plan_probe(free_qty=0.029979, mid=3877.2, sz_decimals=2, n_orders=2)["ok"], "那一次的拒绝照样成立"
    assert not pr.plan_probe(free_qty=0.015, mid=3877.2, sz_decimals=2, n_orders=1)["ok"], "一张也超过一半 ⇒ 不做"
    assert not pr.plan_probe(free_qty=1.0, mid=0, sz_decimals=2)["ok"]


class _Cfg:
    def __init__(self, tmp):
        self.halt_file = Path(tmp) / "HALT"
        self.trade_account = "0x" + "ab" * 20


class _Ex:
    def __init__(self, v, fail_after=None):
        self.v, self.n, self.fail_after = v, 0, fail_after

    def order(self, pair, is_buy, sz, px, order_type, reduce_only=False, cloid=None):
        assert pair == "@182" and is_buy is False and reduce_only is False and "trigger" in order_type
        assert order_type["trigger"]["triggerPx"] < px * 1.2 and order_type["trigger"]["tpsl"] == "sl"
        self.n += 1
        oid = 100 + self.n
        self.v.open.append({"oid": oid, "coin": "@182", "isTrigger": True, "triggerPx": str(order_type["trigger"]["triggerPx"]),
                            "sz": str(sz), "reduceOnly": False})
        self.v.hold += sz
        return {"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": oid}}]}}}

    def cancel(self, pair, oid):
        self.v.open = [o for o in self.v.open if o["oid"] != oid]
        self.v.hold = max(0.0, round(self.v.hold - 0.01, 10))
        return {"status": "ok"}


class _Venue:
    def __init__(self, tmp, poster_boom=False):
        self.cfg, self.open, self.hold, self.boom = _Cfg(tmp), [], 0.0, poster_boom
        self._ex = _Ex(self)

    def balances(self):
        return {"XAUT0": {"total": 0.029979, "hold": round(self.hold, 10)}, "USDC": {"total": 338.0, "hold": 0.0}}

    def quotes(self, tokens):
        return {"XAUT0": {"pair": "@182", "mid": 3877.2, "sz_decimals": 2}}

    def exchange(self):
        return self._ex

    def _poster(self, body):
        if self.boom:
            self.boom = False
            raise RuntimeError("network")
        assert body["type"] == "frontendOpenOrders"
        return list(self.open)


def test_run_places_reads_and_cancels_one_at_a_time(tmp_path):
    v = _Venue(tmp_path)
    real_order = v._ex.order

    def order(*a, **k):
        assert v.open == [], "上一张撤掉之前不挂下一张"
        return real_order(*a, **k)
    v._ex.order = order
    r = pr.run(v, "XAUT0", now=NOON, wait_s=0)
    assert r["ok"] and r["left_open"] == [] and len(r["orders"]) == 2
    assert all(o["cancel"]["ok"] and o["left_open"] == [] and o["hold_back"] for o in r["orders"])
    a = r["answers"]
    assert a["spot_trigger_accepted"] == {"isMarket=False": True, "isMarket=True": True}
    assert a["rests_as_trigger"] is True and a["locks_tokens_while_untriggered"] is True and a["cancel_works"] is True


def test_an_error_after_placing_still_cancels(tmp_path):
    v = _Venue(tmp_path, poster_boom=True)
    with pytest.raises(RuntimeError):
        pr.run(v, "XAUT0", now=NOON, wait_s=0)
    assert v.open == [], "读挂单时出错,finally 照样撤"


def test_refuses_during_the_daily_cycle_hour_and_when_halted(tmp_path):
    v = _Venue(tmp_path)
    assert not pr.run(v, "XAUT0", now=NOON.replace(hour=0, minute=20), wait_s=0)["ok"]
    v.cfg.halt_file.write_text("x")
    r = pr.run(v, "XAUT0", now=NOON, wait_s=0)
    assert not r["ok"] and "一键停" in r["why"] and v.open == []
