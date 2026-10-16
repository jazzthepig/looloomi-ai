"""山寨龙头腿(S-589)与灵活配置组合的前向账本:规则照预注册、开账前不写、开账后写一次不再改。"""
from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.data.universe.forward_books as fb  # noqa: E402


def _row(sym, f, o, mcap, vol, sup):
    return {"sym": sym, "f": f, "o": o, "mcap": mcap, "vol13": vol, "sup13": sup}


def test_alt_select_follows_the_preregistered_gates() -> None:
    rows = [_row("BTC", 90, 90, 2e12, 0.5, 0.0)]                                   # BTC 不进(在核心里)
    rows += [_row(f"A{i:02d}", 50 + i, 30 + i, 1e11 / (i + 1), 0.6, 0.0) for i in range(20)]
    rows += [_row("WILD", 99, 99, 9e10, 3.0, 0.0),                                  # 波动 > 中位数 × 1.5 ⇒ 出局
             _row("DILUTE", 99, 99, 8e10, 0.6, 0.25),                               # 13 周增发 25% ⇒ 出局
             _row("NOF", None, 50, 7e10, 0.6, 0.0)]                                 # 缺 F ⇒ 不算
    sel = fb.alt_select(rows)
    assert "BTC" not in sel["gate"] and "WILD" not in sel["gate"] and "DILUTE" not in sel["gate"] and "NOF" not in sel["gate"]
    assert len(sel["gate"]) <= fb.ALT_TOP_MCAP and len(sel["top"]) == fb.ALT_PICK
    assert set(sel["top"]) <= set(sel["gate"])
    best = max(sel["scores"], key=sel["scores"].get)
    assert best in sel["top"]
    assert set(sel["fo6"]) <= set(sel["gate"]) and len(sel["fo6"]) == fb.ALT_PICK


def test_fo6_ignores_size_and_vol_inside_the_gate() -> None:
    # S-591:门内最大最稳但 F / O 最差的名字,TOP6 会因为市值与波动把它选回来,FO6 不会
    rows = [_row("BIG", 10, 10, 1e12, 0.30, 0.0)]
    rows += [_row(f"S{i}", 60 + i, 60 + i, 1e10 / (i + 1), 0.60, 0.0) for i in range(7)]
    sel = fb.alt_select(rows)
    assert "BIG" in sel["gate"] and "BIG" not in sel["fo6"]
    assert sel["fo6"][0] == "S6"                                                    # F + O 最高
    assert sel["fo_scores"]["S6"] > sel["fo_scores"]["BIG"]


def test_vol_and_supply_from_price_and_mcap() -> None:
    from datetime import date, timedelta
    ser, p, units = [], 100.0, 1e6
    d0 = date(2026, 6, 1)
    for i in range(130):
        p *= math.exp(0.02 if i % 2 else -0.02)
        units *= 1.001                                                              # 每天 0.1% 增发
        ser.append(((d0 + timedelta(days=i)).isoformat(), p, p * units))
    vol, sup = fb.vol_and_supply(ser, ser[-1][0])
    assert vol and 0.3 < vol < 0.5                                                  # 每天 ±2% ⇒ 年化约 0.38
    assert sup and abs(sup - (1.001 ** 91 - 1)) < 0.01


def test_flex_step_is_the_weighted_sum_with_cash_at_zero() -> None:
    assert math.isclose(fb.flex_step(1.0, 0.10, -0.02), 1 + 0.35 * 0.10 - 0.50 * 0.02)
    assert math.isclose(sum(fb.FLEX_WEIGHTS.values()), 1.0)


class _DB:
    def __init__(self, extra=None):
        self.tables = {"forward_book_holdings": [], "forward_book_nav": [], **(extra or {})}

    async def get_all(self, tail):
        name = tail.split("?")[0]
        return [dict(r) for r in self.tables.get(name, [])]

    async def upsert(self, table, rows, on_conflict):
        keys = on_conflict.split(",")
        cur = {tuple(r[k] for k in keys): r for r in self.tables[table]}
        for r in rows:
            cur[tuple(r[k] for k in keys)] = dict(r)
        self.tables[table] = sorted(cur.values(), key=lambda r: (r.get("d") or r.get("as_of"), r["arm"]))
        return SimpleNamespace(ok=True, why=None)


def test_nothing_written_before_start_and_flex_combines_the_two_books(monkeypatch) -> None:
    import src.api.store as store
    from datetime import date, timedelta
    days = [(date(2026, 12, 24) + timedelta(days=i)).isoformat() for i in range(40)]
    core = [{"d": d, "nav": 1.0 + 0.01 * i} for i, d in enumerate(days)]
    w50 = [{"d": d, "nav": 1.0 + 0.002 * i} for i, d in enumerate(days) if d >= "2026-12-31"]
    db = _DB({"core_cap_daily": core, "world50_book_nav": w50})
    monkeypatch.setattr(fb, "_get_all", db.get_all)
    monkeypatch.setattr(store, "supabase_upsert_table", db.upsert)

    async def inputs(as_of):
        return [_row(s, 50 + i, 40 + i, 1e10 * (10 - i), 0.6, 0.0) for i, s in enumerate(["ETH", "SOL", "XRP", "BNB", "LINK", "AVAX", "UNI", "AAVE"])]

    async def px(keys, start, end):
        return {k: [(d, 100.0) for d in days if start <= d <= end] for k in keys}
    monkeypatch.setattr(fb, "alt_inputs", inputs)
    monkeypatch.setattr(fb, "prices", px)

    async def tom_stub(cutoff):
        return {"ok": True, "nav_written": 0}
    monkeypatch.setattr(fb, "run_tom_trader", tom_stub)
    r = asyncio.run(fb.run_forward_books(today="2026-10-16"))
    assert r["ok"] and r["preview"]["alt_top6"] and db.tables["forward_book_nav"] == []
    r = asyncio.run(fb.run_forward_books(today="2027-01-10"))
    assert r["ok"], r
    alt = [x for x in db.tables["forward_book_holdings"] if x["arm"] == "TOP6"]
    assert {x["as_of"] for x in alt} == {"2026-12-31"} and len(alt) == 6
    fo6 = [x for x in db.tables["forward_book_holdings"] if x["arm"] == "FO6"]
    assert len(fo6) == 6 and all(x["rule"] == fb.RULE_FO6 for x in fo6)
    assert {x["arm"] for x in db.tables["forward_book_nav"] if x["book"] == "alt_leaders"} == set(fb.ALT_ARMS)
    flex = [x for x in db.tables["forward_book_nav"] if x["book"] == "flex"]
    assert flex[0]["d"] == "2026-12-31" and flex[0]["nav"] == 1.0
    i0 = days.index("2026-12-31")
    d1 = flex[1]["d"]
    i1 = days.index(d1)
    want = 1 + 0.35 * (core[i1]["nav"] / core[i0]["nav"] - 1) + 0.50 * (w50[i1 - i0]["nav"] / w50[0]["nav"] - 1)
    assert math.isclose(flex[1]["nav"], want)
    before = {(x["book"], x["arm"], x["d"]): x["nav"] for x in db.tables["forward_book_nav"]}
    asyncio.run(fb.run_forward_books(today="2027-01-12"))
    after = {(x["book"], x["arm"], x["d"]): x["nav"] for x in db.tables["forward_book_nav"]}
    assert all(after[k] == v for k, v in before.items()), "写过的不再改"


def test_tom_trader_writes_once_from_its_start_and_never_rewrites(monkeypatch):
    """S-600:交易层前向 10-16 起;每轮整段重算敞口,只追加没写过的天;敞口在 −0.5 … 1.3。"""
    import pandas as pd
    import numpy as np
    import src.api.store as store
    days = pd.date_range("2024-01-01", "2026-11-10", freq="D")
    rng = np.random.default_rng(3)
    path = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, len(days))))
    closes = {k: pd.Series(path * (1 + 0.1 * i), index=days) for i, k in enumerate(("BTC", "ETH", "CORE"))}
    fund = {"BTC": pd.Series(0.08, index=days), "ETH": pd.Series(0.08, index=days), "CORE": pd.Series(0.08, index=days)}
    db = _DB()

    async def inputs(end):
        e = pd.Timestamp(end)
        return {k: v[v.index <= e] for k, v in closes.items()}, fund
    monkeypatch.setattr(fb, "tom_inputs", inputs)
    monkeypatch.setattr(fb, "_get_all", db.get_all)
    monkeypatch.setattr(store, "supabase_upsert_table", db.upsert)
    assert asyncio.run(fb.run_tom_trader("2026-10-16"))["waiting"]
    r = asyncio.run(fb.run_tom_trader("2026-10-31"))
    assert r["ok"], r
    navs = [x for x in db.tables["forward_book_nav"] if x["book"] == "tom_trader"]
    assert {x["arm"] for x in navs} == set(fb.TOM_ARMS)
    assert min(x["d"] for x in navs) == fb.TOM_START and max(x["d"] for x in navs) == "2026-10-31"
    assert all(x["nav"] == 1.0 for x in navs if x["d"] == fb.TOM_START)
    w = [x["weight"] for x in db.tables["forward_book_holdings"] if x["book"] == "tom_trader"]
    assert w and min(w) >= -0.5 - 1e-9 and max(w) <= 1.3 + 1e-9
    before = {(x["arm"], x["d"]): x["nav"] for x in navs}
    closes = {k: v * 1.5 for k, v in closes.items()}                      # 源数据被改:写过的天不跟着改
    asyncio.run(fb.run_tom_trader("2026-11-05"))
    after = {(x["arm"], x["d"]): x["nav"] for x in db.tables["forward_book_nav"] if x["book"] == "tom_trader"}
    assert all(after[k] == v for k, v in before.items())
    assert max(d for (_, d) in after) == "2026-11-05"

    async def boom(end):
        raise AssertionError("已写到 cutoff 不该再读价格")
    monkeypatch.setattr(fb, "tom_inputs", boom)
    assert asyncio.run(fb.run_tom_trader("2026-11-05")) == {"ok": True, "up_to_date": "2026-11-05"}
