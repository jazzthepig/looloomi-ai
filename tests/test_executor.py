"""T-122:执行器核心 —— 目标与前向账本同一个核、价格过期拒单、出场优先、上限截断、一键停、灾难止损。"""
import asyncio

import numpy as np
import pandas as pd

from src.data.execution import executor as ex
from src.data.signals.tom import trade_path


def _series(vals, start="2024-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"), dtype=float)


def _trend(n=400, seed=1, drift=0.003):
    rng = np.random.default_rng(seed)
    return _series(100 * np.exp(np.cumsum(rng.normal(drift, 0.02, n))))


def test_target_uses_the_same_kernel_as_the_forward_book_capped_at_spot():
    c = _trend()
    g = trade_path(c, "rally", 0.0, exit_mode="l20", vol=True).iloc[-1]
    assert ex.x1v_spot_target(c) == min(1.0, max(0.0, g))
    w = ex.target_weights({"BTC": c, "ETH": _trend(seed=2)})
    assert set(w) == {"BTC", "ETH"} and all(0 <= v <= 0.5 for v in w.values())


def test_stale_prices_are_refused_and_halt_stops_everything():
    now = 1_000_000.0
    p = ex.plan_orders({"BTC": 0.5}, {}, 3000.0, {"BTC": (80000.0, now - 600)}, now)
    assert not p.orders and any("过期" in r for r in p.refused)
    h = ex.plan_orders({"BTC": 0.5}, {}, 3000.0, {"BTC": (80000.0, now)}, now, ex.Limits(halted=True))
    assert not h.orders and h.refused == ["halted:一键停"]


def test_exits_go_first_small_drifts_are_ignored_and_limits_truncate():
    now = 1.0
    px = {"BTC": (80000.0, now), "ETH": (2400.0, now)}
    p = ex.plan_orders({"BTC": 0.0, "ETH": 0.5}, {"BTC": 1500.0}, 1500.0, px, now, ex.Limits(max_order_usd=1000.0))
    assert p.orders[0]["symbol"] == "BTC" and p.orders[0]["side"] == ex.SELL, "出场排在前面"
    assert all(o["notional_usd"] <= 1000.0 for o in p.orders) and p.orders[0]["truncated"]
    small = ex.plan_orders({"BTC": 0.52}, {"BTC": 1500.0}, 1500.0, px, now)
    assert not small.orders, "2% 的漂移不动"


def test_catastrophe_stop_only_on_a_gap_below_the_20_day_low():
    c = _series([100.0] * 30)
    assert not ex.catastrophe_hit(95.0, c)
    assert ex.catastrophe_hit(91.0, c)


def test_dry_run_writes_intents_and_never_places_orders(monkeypatch):
    import src.data.execution.fill_log as fl
    seen = []

    async def fake_write(i):
        seen.append(i)
        return True
    monkeypatch.setattr(fl, "write_intent", fake_write)
    c = _trend()
    now = 5.0
    out = asyncio.run(ex.dry_run_cycle({"BTC": c, "ETH": c}, {}, 3000.0, {"BTC": (float(c.iloc[-1]), now), "ETH": (float(c.iloc[-1]), now)}, now))
    assert out["written"] == out["intents"] == len(seen)
    assert all(i.signal_ref == ex.SIGNAL_REF and i.decision_mid > 0 for i in seen)
