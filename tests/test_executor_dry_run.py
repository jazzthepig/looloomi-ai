"""T-122 空跑:收盘没到不跑、目标与前向账本同一个核、按真实盘口取整与估滑点、超出可见深度拒单、意图落表不下单。"""
import asyncio
import datetime as dt
import json
import pathlib

import numpy as np
import pandas as pd

from src.data.execution import dry_run as dr
from src.data.execution import executor as ex

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "hl_spot"


class _FixtureClient:
    def spot_meta(self):
        return json.loads((FIX / "spotMeta.json").read_text())

    def spot_meta_and_asset_ctxs(self):
        return json.loads((FIX / "spotMetaAndAssetCtxs.json").read_text())

    def l2_book(self, coin):
        return json.loads((FIX / ("l2Book_UBTC.json" if coin == "@142" else "l2Book_UETH.json")).read_text())


def _quotes():
    return dr._spot_quotes_sync(_FixtureClient())


def _closes(end="2026-10-17", n=420, seed=1, breakout=True):
    idx = pd.date_range(end=end, periods=n, freq="D")
    rng = np.random.default_rng(seed)
    path = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    if breakout:
        path[-1] = path[-60:-1].max() * 1.05          # 收盘创 55 日新高
    return pd.Series(path, index=idx)


def test_minutes_after_close_and_the_quotes_from_the_real_book():
    assert dr.minutes_after_close(dt.datetime(2026, 10, 18, 0, 42, tzinfo=dt.timezone.utc)) == 42.0
    q = _quotes()
    assert q["BTC"]["pair"] == "@142" and q["BTC"]["sz_decimals"] == 5 and q["BTC"]["bid"] < q["BTC"]["ask"]
    assert q["ETH"]["pair"] == "@151" and q["ETH"]["sz_decimals"] == 4


def test_sizing_rounds_down_checks_min_notional_and_refuses_beyond_visible_depth():
    q = _quotes()
    orders = [{"symbol": "BTC", "side": "buy", "notional_usd": 1500.0, "price": q["BTC"]["mid"]},
              {"symbol": "ETH", "side": "buy", "notional_usd": 5.0, "price": q["ETH"]["mid"]},
              {"symbol": "ETH", "side": "sell", "notional_usd": 5_000_000.0, "price": q["ETH"]["mid"]},
              {"symbol": "SOL", "side": "buy", "notional_usd": 100.0, "price": 1.0}]
    sized, refused = dr.size_orders(orders, q)
    assert len(sized) == 1 and sized[0]["symbol"] == "BTC"
    b = sized[0]
    assert b["qty_base"] == round(b["qty_base"], 5) and b["qty_base"] * q["BTC"]["mid"] <= 1500.0
    assert 0 <= b["est_slippage_bps"] < 5
    assert any("最小名义额" in r for r in refused) and any("可见深度" in r for r in refused) and any("SOL" in r for r in refused)


def test_refuses_until_yesterdays_close_is_in(monkeypatch):
    import src.data.universe.forward_books as fb

    async def late(end):
        return {"BTC": _closes(end="2026-10-16"), "ETH": _closes(end="2026-10-16", seed=2)}, {}
    monkeypatch.setattr(fb, "tom_inputs", late)
    out = asyncio.run(dr.run_dry_cycle(now=dt.datetime(2026, 10, 18, 0, 20, tzinfo=dt.timezone.utc),
                                       write=False, quotes=_quotes()))
    assert out["refused"] and "2026-10-17" in out["why"]


def test_a_cycle_plans_from_the_same_kernel_and_writes_intents_without_ordering(monkeypatch):
    import src.data.execution.fill_log as fl
    import src.data.universe.forward_books as fb
    closes = {"BTC": _closes(), "ETH": _closes(seed=2)}

    async def inputs(end):
        return closes, {}
    seen = []

    async def fake_write(i):
        seen.append(i)
        return True
    monkeypatch.setattr(fb, "tom_inputs", inputs)
    monkeypatch.setattr(fl, "write_intent", fake_write)
    now = dt.datetime(2026, 10, 18, 0, 35, tzinfo=dt.timezone.utc)
    out = asyncio.run(dr.run_dry_cycle(now=now, quotes=_quotes()))
    assert out["ok"] and out["on_time"] and out["minutes_after_close"] == 35.0
    assert out["targets"] == {s: round(v, 4) for s, v in ex.target_weights(closes).items()}
    assert len(out["orders"]) == 2, "收盘突破 ⇒ 两个币都从 0 进场"
    assert out["intents_written"] == len(seen) == len(out["orders"])
    for i in seen:
        assert i.sleeve == dr.SLEEVE and i.decision_bid and i.decision_ask and i.signal_ref == ex.SIGNAL_REF
    assert set(out["catastrophe"]) == {"BTC", "ETH"}


def test_one_cycle_per_utc_day_even_across_deploys(monkeypatch):
    import src.data.style.header as hd
    state = {"execution_intents": [], "loop_attempt": []}

    async def read_all(table, params):
        return list(state[table])
    monkeypatch.setattr(hd, "_read_all", read_all)
    now = dt.datetime(2026, 10, 18, 9, 0, tzinfo=dt.timezone.utc)
    assert not asyncio.run(dr.already_ran_today(now))
    state["loop_attempt"] = [{"id": 1}]
    assert asyncio.run(dr.already_ran_today(now)), "没有订单的日子靠 loop_attempt 判定已跑"
    state = {"execution_intents": [{"intent_id": "x"}], "loop_attempt": []}
    assert asyncio.run(dr.already_ran_today(now)), "写过意图 ⇒ 不再写第二批"
