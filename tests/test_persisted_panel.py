"""S-607:三本 paper book 读落过库的面板 + 今天的 Hyperliquid oracle,不再现场调 fapi.binance.com。

10-14 起 `beta_core` / `scalable` / `combined` 每天 00:33 死在同一句 `string index out of range`:
Railway 某些部署的出口被 Binance 以 HTTP 451 拒绝,响应体是 `{"code": 0, "msg": ...}`,
K 线循环迭代它的键,`float(k[4])` 落在字符串 "code" 上。
"""
import ast
import asyncio
import datetime as dt
import pathlib

import numpy as np

from src.data.market import persisted_panel as pp

ROOT = pathlib.Path(__file__).resolve().parents[1]
D0 = dt.date(2026, 10, 10)
DAYS = [D0 + dt.timedelta(days=i) for i in range(5)]          # 10-10 … 10-14(最后一天 = 今天)


def test_today_row_is_the_live_price_and_a_missing_live_price_is_carried_and_masked():
    closes = {"BTC": {d.isoformat(): 100.0 + i for i, d in enumerate(DAYS[:-1])},
              "ETH": {d.isoformat(): 10.0 for d in DAYS[:-1]}}
    close, fmean, fsum, filled, obs = pp.build_panel(["BTC", "ETH"], DAYS, closes, live={"BTC": 110.0})
    assert close[-1, 0] == 110.0 and not filled[-1, 0], "今天 = 现场价"
    assert close[-1, 1] == 10.0 and filled[-1, 1] and np.isnan(obs[-1, 1]), "没有现场价 ⇒ 前推且标记"
    assert not fmean.any() and not fsum.any()


def test_the_partial_bar_for_today_in_the_store_is_never_read_as_a_close():
    closes = {"BTC": {d.isoformat(): 100.0 for d in DAYS}}       # 采集器也写了今天未收完的 K 线
    closes["BTC"][DAYS[-1].isoformat()] = 999.0
    close, *_ = pp.build_panel(["BTC"], DAYS, closes, live=None)
    assert close[-1, 0] == 100.0, "今天那格只能来自现场价,不能来自未收完的 K 线"


def test_a_gap_is_nan_in_the_returns_not_a_flat_day():
    closes = {"BTC": {DAYS[0].isoformat(): 100.0, DAYS[2].isoformat(): 120.0, DAYS[3].isoformat(): 126.0}}
    close, _, _, filled, obs = pp.build_panel(["BTC"], DAYS, closes, live={"BTC": 126.0})
    ret = pp.observed_returns(obs)
    assert filled[1, 0] and close[1, 0] == 100.0
    assert np.isnan(ret[1, 0]) and np.isnan(ret[2, 0]), "缺口两侧的收益率是 NaN(I1),不是 0"
    assert abs(ret[3, 0] - 0.05) < 1e-12 and ret[4, 0] == 0.0


def test_funding_is_averaged_and_summed_per_utc_day():
    fund = {"BTC": {DAYS[1].isoformat(): [0.0001, 0.0002, 0.0003]}}
    _, fmean, fsum, *_ = pp.build_panel(["BTC"], DAYS, {"BTC": {DAYS[0].isoformat(): 1.0}}, funding=fund)
    assert abs(fmean[1, 0] - 0.0002) < 1e-15 and abs(fsum[1, 0] - 0.0006) < 1e-15


def test_loader_reads_completed_days_only_and_refuses_an_empty_store(monkeypatch):
    import src.data.style.header as hd
    seen = []

    async def fake_read_all(table, params):
        seen.append((table, params))
        if table == "ohlcv_daily":
            return [{"symbol": "BTC", "trade_date": d.isoformat(), "close": 100.0} for d in DAYS[:-1]]
        return [{"symbol": "BTC", "funding_time": f"{DAYS[1].isoformat()}T08:00:00+00:00", "funding_rate": 0.0001}]
    monkeypatch.setattr(hd, "_read_all", fake_read_all)
    days, close, fmean, fsum, filled, obs = asyncio.run(
        pp.load_persisted_panel(["BTC"], D0, live={"BTC": 101.0}, today=DAYS[-1]))
    assert days[-1] - days[0] == 4 and close[-1, 0] == 101.0 and fmean[1, 0] == 0.0001
    o = dict(seen)["ohlcv_daily"]
    assert o["source"] == "eq.binance_hist" and f"trade_date.lt.{DAYS[-1].isoformat()}" in o["and"]
    seen.clear()
    asyncio.run(pp.load_persisted_panel(["BTC"], D0, with_funding=False, today=DAYS[-1]))
    assert [t for t, _ in seen] == ["ohlcv_daily"], "① 不读资金费"

    async def empty(table, params):
        return []
    monkeypatch.setattr(hd, "_read_all", empty)
    try:
        asyncio.run(pp.load_persisted_panel(["BTC"], D0, today=DAYS[-1]))
        raise AssertionError("空库必须抛异常 —— 读不到 ≠ 0 行")
    except RuntimeError:
        pass


def test_live_prices_come_from_one_oracle_snapshot(monkeypatch):
    import src.data.market.hyperliquid_collector as hc

    async def snap():
        return {"ok": True, "assets": {"BTC": {"oracle": 81000.0}, "ETH": {"oracle": None}}}
    monkeypatch.setattr(hc, "venue_snapshot", snap)
    assert asyncio.run(pp.live_oracle_prices(["BTC", "ETH", "SOL"])) == {"BTC": 81000.0}

    async def down():
        return {"ok": False, "reason": "timeout"}
    monkeypatch.setattr(hc, "venue_snapshot", down)
    assert asyncio.run(pp.live_oracle_prices(["BTC"])) == {}, "读不到 ⇒ 空,由覆盖率底线拒绝记账"


def test_no_paper_book_fetches_binance_live_any_more():
    """回归:三本账的读价函数里不再调用 load_binance_panel(451 会再次让它们死掉)。"""
    for rel, fn_name in (("src/data/signals/beta_core_paper.py", "_load_panel"),
                         ("src/data/signals/scalable_paper.py", "_load_panel"),
                         ("src/data/signals/combined_book.py", "_load_live_panel")):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == fn_name)
        calls = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert "load_binance_panel" not in calls and "load_persisted_panel" in calls, rel


def _fake_store(monkeypatch, live, closes_days=300):
    import src.data.market.persisted_panel as pp2
    today = dt.datetime.now(dt.timezone.utc).date()

    async def lp(assets):
        return {a: v for a, v in live.items() if a in assets}

    async def dc(assets, start, before, with_volume=False):
        out = {}
        for a in assets:
            out[a] = {(before - dt.timedelta(days=i)).isoformat(): 100.0 + i for i in range(1, closes_days + 1)}
        return out

    async def df(assets, start):
        return {a: {(today - dt.timedelta(days=i)).isoformat(): [0.0001, 0.0002] for i in range(25)} for a in assets}
    monkeypatch.setattr(pp2, "live_oracle_prices", lp)
    monkeypatch.setattr(pp2, "daily_closes", dc)
    monkeypatch.setattr(pp2, "daily_funding", df)


def test_causal_reads_funding_from_the_store_and_price_from_the_oracle(monkeypatch):
    from src.data.signals import causal_paper as cp
    _fake_store(monkeypatch, {"BTC": 81000.0, "ETH": 2400.0})
    live = asyncio.run(cp._fetch_live(["BTC", "ETH", "SOL"]))
    assert set(live) == {"BTC", "ETH"}, "今天没有 oracle 的名字整只略过"
    assert live["BTC"]["close"] == 81000.0 and len(live["BTC"]["fmean"]) == 16
    assert abs(live["BTC"]["fmean"][-1] - 0.00015) < 1e-12


def test_two_layer_needs_200_observed_closes_and_ends_on_todays_oracle(monkeypatch):
    from src.data.signals import two_layer_paper as tl
    _fake_store(monkeypatch, {"BTC": 81000.0, "ETH": 2400.0}, closes_days=300)
    out = asyncio.run(tl._fetch_daily(["BTC", "ETH", "SOL"]))
    assert set(out) == {"BTC", "ETH"} and out["BTC"]["close"][-1] == 81000.0
    assert len(out["BTC"]["close"]) == 301 and len(out["BTC"]["funding"]) == 25
    _fake_store(monkeypatch, {"BTC": 81000.0}, closes_days=150)
    assert asyncio.run(tl._fetch_daily(["BTC"])) == {}, "不足 200 天真实收盘 ⇒ 不给"


def test_the_backlog_books_moved_off_the_free_venue_too():
    for rel, fn_name in (("src/data/signals/causal_paper.py", "_fetch_live"),
                         ("src/data/signals/two_layer_paper.py", "_fetch_daily"),
                         ("src/data/signals/fusion_paper.py", "_fetch_close_funding"),
                         ("src/data/signals/r76_strategy2_paper.py", "_fetch_close_funding")):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "_FAPI" not in src, f"{rel} 还留着直连 fapi 的常量"
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == fn_name)
        calls = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert "live_oracle_prices" in calls and not any("httpx" in c for c in calls), rel
