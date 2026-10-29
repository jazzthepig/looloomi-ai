"""World50 前向账本:核与回放是同一个、开账前不写、开账后写一次不再改。"""
from __future__ import annotations

import asyncio
import importlib.util
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.data.universe.world50_book as wb  # noqa: E402
from src.data.universe import world50 as w50  # noqa: E402


def _replay():
    spec = importlib.util.spec_from_file_location("t099_replay", ROOT / "docs/research/t099_world50_replay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _panel(seed: int = 7, n_keys: int = 70, n_months: int = 60):
    rnd = random.Random(seed)
    keys = [f"K{i:02d}" for i in range(n_keys)]
    rets = {}
    for k in keys:
        r = [rnd.gauss(0.01, 0.08) for _ in range(n_months)]
        if rnd.random() < 0.2:                       # 有的序列开头缺、中间断
            cut = rnd.randint(0, 30)
            r[:cut] = [None] * cut
        if rnd.random() < 0.1:
            r[rnd.randint(31, n_months - 5)] = None
        rets[k] = r
    snaps = {i: {k: rnd.lognormvariate(5, 1) for k in keys if rnd.random() > 0.05} for i in range(n_months)}
    return keys, rets, snaps


def test_the_book_and_the_replay_share_one_kernel() -> None:
    """S-581 的回放与前向账本必须是同一套规则:同样的输入,逐个权重相等。"""
    rp = _replay()
    keys, rets, snaps = _panel()
    closes = {k: rp.closes_from_returns(rets[k]) for k in keys}
    assert all(w50.closes_from_returns(rets[k]) == closes[k] for k in keys)
    members_rp: list[str] = []
    members_bk: list[str] = []
    for i in range(14, 60, 3):
        reconst = (i % 12 == 11)
        snap = snaps[i]
        if reconst or not members_rp:
            members_rp = rp.select_members(rp.rank_at(snap), previous=members_rp, n=50)
        members_rp = [k for k in members_rp if k in snap]
        w_rp, nn = rp.mom_weights(members_rp, closes, i)
        res = w50.rebalance(snap, members_bk, {k: closes[k][: i + 1] for k in keys}, reconstitute=reconst)
        members_bk = res["members"]
        assert members_bk == members_rp
        assert len(res["neutral"]) == nn
        assert set(res["EWxMom"]) == set(w_rp)
        assert all(math.isclose(res["EWxMom"][k], w_rp[k], rel_tol=1e-12) for k in w_rp)
        assert all(math.isclose(v, 1 / len(members_rp)) for v in res["EW"].values())


def test_momentum_closes_match_the_panel_definition() -> None:
    """日线 → 月末收盘之比 → 价格指数,与导面板(t099_export_panel.monthly_returns)+ closes_from_returns 同一口径。"""
    spec = importlib.util.spec_from_file_location("t099_export", ROOT / "docs/research/t099_export_panel.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    rnd = random.Random(3)
    daily, p, d = [], 100.0, wb.date(2022, 1, 3)
    while d <= wb.date(2026, 9, 30):
        if d.weekday() < 5 and not (wb.date(2023, 5, 1) <= d <= wb.date(2023, 6, 30)):   # 两个月停牌
            p *= math.exp(rnd.gauss(0, 0.01))
            daily.append((d.isoformat(), p))
        d += wb.timedelta(days=1)
    got = wb.momentum_closes(daily, "2026-09-30", months=40)
    months = [m for m in ex.months_until("2026-09")][-40:]
    want = w50.closes_from_returns(ex.monthly_returns(daily, months))
    assert len(got) == 40
    assert all((a is None and b is None) or math.isclose(a, b) for a, b in zip(got, want))
    assert None in got, "停牌那两个月要断开,缺口之前不可比"


def test_calendar_helpers() -> None:
    assert wb.quarter_ends("2026-12-31", "2027-07-01") == ["2026-12-31", "2027-03-31", "2027-06-30"]
    assert wb.quarter_ends("2026-12-31", "2026-12-30") == []
    assert wb.last_quarter_end_before("2026-10-14") == "2026-09-30"
    assert wb.last_quarter_end_before("2027-02-01") == "2026-12-31"
    assert wb.weekdays("2026-12-31", "2027-01-05") == ["2027-01-01", "2027-01-04", "2027-01-05"]


def test_drift_and_cost() -> None:
    px = {"A": [("2026-12-31", 10.0), ("2027-01-04", 11.0)], "B": [("2026-12-31", 20.0), ("2027-01-04", 20.0)]}
    g, w, n = wb.drift({"A": 0.5, "B": 0.5}, px, "2026-12-31", "2027-01-04")
    assert math.isclose(g, 1.05) and n == 2 and math.isclose(w["A"], 0.55 / 1.05)
    g, w, n = wb.drift({"A": 0.5, "C": 0.5}, px, "2026-12-31", "2027-01-04")
    assert math.isclose(g, 1.10) and n == 1, "没有价的成分按回放做法在其余成分间重归一"
    assert math.isclose(wb.turnover_cost({"A": 0.5, "BTC": 0.5}, {"A": 0.4, "BTC": 0.6}, {"BTC": "crypto"}),
                        0.1 * 10 / 1e4 + 0.1 * 20 / 1e4)


class _DB:
    """假库:记下每一次写,读的时候按写过的返回。"""
    def __init__(self):
        self.tables = {"world50_book_holdings": [], "world50_book_nav": []}

    async def get_all(self, tail: str, page: int = 1000):
        name = tail.split("?")[0]
        return [dict(r) for r in self.tables.get(name, [])]

    async def upsert(self, table, rows, on_conflict):
        keys = on_conflict.split(",")
        cur = {tuple(r[k] for k in keys): r for r in self.tables[table]}
        for r in rows:
            cur[tuple(r[k] for k in keys)] = dict(r)
        self.tables[table] = sorted(cur.values(), key=lambda r: (r.get("d") or r.get("as_of"), r["arm"]))
        return SimpleNamespace(ok=True, why=None)


def _patch(monkeypatch, db: _DB, prices: dict, snap: dict):
    import src.api.store as store
    monkeypatch.setattr(wb, "_get_all", db.get_all)
    monkeypatch.setattr(store, "supabase_upsert_table", db.upsert)

    async def fake_snapshot(as_of):
        return dict(snap)

    async def fake_prices(keys, start, end):
        return {k: [(d, p) for d, p in prices[k] if start <= d <= end] for k in keys}
    monkeypatch.setattr(wb, "snapshot", fake_snapshot)
    monkeypatch.setattr(wb, "usd_prices", fake_prices)


def _prices(keys, start="2023-01-02", end="2027-04-30", seed=11):
    rnd = random.Random(seed)
    out = {}
    for k in keys:
        s, p, d = [], 100.0, wb.date.fromisoformat(start)
        drift_k = rnd.gauss(0, 0.0008)
        while d <= wb.date.fromisoformat(end):
            if d.weekday() < 5:
                p *= math.exp(drift_k + rnd.gauss(0, 0.01))
                s.append((d.isoformat(), p))
            d += wb.timedelta(days=1)
        out[k] = s
    return out


def test_nothing_is_written_before_the_forward_start(monkeypatch) -> None:
    db = _DB()
    keys = [f"K{i:02d}" for i in range(60)]
    _patch(monkeypatch, db, _prices(keys), {k: 100.0 + i for i, k in enumerate(keys)})
    r = asyncio.run(wb.run_book(today="2026-10-16"))
    assert r["ok"] and wb.OPEN_DATE in r["waiting"]
    assert r["preview"]["as_of"] == "2026-09-30" and r["preview"]["members"] == 50
    assert db.tables == {"world50_book_holdings": [], "world50_book_nav": []}


def test_the_book_opens_marks_and_never_rewrites(monkeypatch) -> None:
    db = _DB()
    keys = [f"K{i:02d}" for i in range(60)]
    prices = _prices(keys)
    _patch(monkeypatch, db, prices, {k: 100.0 + i for i, k in enumerate(keys)})
    r = asyncio.run(wb.run_book(today="2027-01-08"))
    assert r["ok"], r
    h = db.tables["world50_book_holdings"]
    assert {x["as_of"] for x in h} == {wb.OPEN_DATE, "2026-12-31"} and len(h) == 200
    for arm in wb.ARMS:
        for q in (wb.OPEN_DATE, "2026-12-31"):
            assert math.isclose(sum(x["weight"] for x in h if x["arm"] == arm and x["as_of"] == q), 1.0)
    nav = [x for x in db.tables["world50_book_nav"] if x["arm"] == "EW"]
    assert nav[0]["d"] == wb.OPEN_DATE and nav[0]["nav"] == 1.0, "开账 = 1,不收成本"
    assert all(x["d"] >= wb.OPEN_DATE for x in db.tables["world50_book_nav"]), "开账日之前一行不写"
    q12 = [x for x in nav if x["d"] == "2026-12-31"][0]
    assert q12["as_of"] == "2026-12-31" and q12["nav"] != 1.0, "12-31 照常调仓,净值从开账日连续下来"
    assert [x["d"] for x in nav][-4:] == ["2027-01-01", "2027-01-04", "2027-01-05", "2027-01-06"], "只写到今天 − 2"
    frozen = {(x["d"], x["arm"]): x["nav"] for x in db.tables["world50_book_nav"]}
    for k in keys:                                      # 之后价格序列被改写(复权调整):写过的净值不跟着变
        prices[k] = [(d, p * (0.9 if d < "2027-01-05" else 1.0)) for d, p in prices[k]]
    r = asyncio.run(wb.run_book(today="2027-04-09"))
    assert r["ok"], r
    assert {x["as_of"] for x in db.tables["world50_book_holdings"]} == {wb.OPEN_DATE, "2026-12-31", "2027-03-31"}
    after = {(x["d"], x["arm"]): x["nav"] for x in db.tables["world50_book_nav"]}
    assert all(after[k] == v for k, v in frozen.items())
    q = [x for x in db.tables["world50_book_nav"] if x["d"] == "2027-03-31" and x["arm"] == "EWxMom"][0]
    assert q["as_of"] == "2027-03-31"
    assert max(x["d"] for x in db.tables["world50_book_nav"]) == "2027-04-07"


def test_mid_quarter_open_equals_the_replay_from_the_open_date(monkeypatch) -> None:
    """10-29:季内开账 = 09-30 季末权重漂到 10-28 收盘;此后每天的净值 = 从 09-30 一路漂移的净值 ÷ 它在 10-28 的值。"""
    db = _DB()
    keys = [f"K{i:02d}" for i in range(60)]
    prices = _prices(keys)
    _patch(monkeypatch, db, prices, {k: 100.0 + i for i, k in enumerate(keys)})
    r = asyncio.run(wb.run_book(today="2026-11-20"))
    assert r["ok"], r
    h = [x for x in db.tables["world50_book_holdings"] if x["arm"] == "EWxMom"]
    assert {x["as_of"] for x in h} == {wb.OPEN_DATE} and "季内开账" in h[0]["rule"]
    c = asyncio.run(wb.compute("2026-09-30", []))
    w0 = c["EWxMom"]
    px = {k: prices[k] for k in w0}
    g_open, _, _ = wb.drift(w0, px, "2026-09-30", wb.OPEN_DATE)
    for row in [x for x in db.tables["world50_book_nav"] if x["arm"] == "EWxMom" and x["d"] > wb.OPEN_DATE]:
        g, _, _ = wb.drift(w0, px, "2026-09-30", row["d"])
        assert math.isclose(row["nav"], g / g_open, rel_tol=1e-9), row["d"]
