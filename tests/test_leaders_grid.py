"""T-434(台账 S-912 / S-913):龙头网格研究宇宙 —— 名单、价格线、周度整段重取、SEC 原始财报事实。

守的是这几件事:
- 研究宇宙**不是** World50 成分:不和候选池 / 对照组 / 轨道公司撞代码,已在候选池里的龙头不另起一条价格线。
- 价格线**不猜代码**:EODHD 实测 404 的交易所(东京 / 印度 / 沙特 / 新加坡 / 米兰)不许出现在名单里;每个名字有层级。
- 名单与研究产物(`docs/research/t434_leaders_grid/grid_v2.json`)说同一件事 —— 改名单就要重跑编表脚本。
- 财报事实:时点值、年初至今的期间、最早一次报送、负值都按 S-913 规则 4 存;只对 SEC 代码表里有的公司发请求。
- 按时点(⑤,S-915):历年流通市值原样存(量级守卫不在写入端);某一年取不到 = 整段不成;只给各年前 N 的公司取属性。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.store_result import StoreResult  # noqa: E402
from src.data.universe import leaders_grid as lg  # noqa: E402
from src.data.universe import world50_data as wd  # noqa: E402
from src.data.universe.world50 import BENCHMARKS, CANDIDATES, RAIL_EQUITIES  # noqa: E402

GRID = ROOT / "docs" / "research" / "t434_leaders_grid" / "grid_v2.json"


def test_research_universe_is_not_world50_and_has_no_guessed_codes():
    names = lg.names()
    keys = [n["key"] for n in names]
    assert len(names) >= 100 and len(keys) == len(set(keys))
    taken = {c.key for c in CANDIDATES} | {c.key for c in BENCHMARKS} | {c.key for c in RAIL_EQUITIES}
    assert not set(keys) & taken, "已在候选池 / 对照组 / 轨道公司里的名字沿用那边的代码,不另起一条"
    for n in names:
        tick, ex = n["code"].rsplit(".", 1)
        assert tick and ex and n["tier"] in lg.TIERS, n
        assert ex not in {"TSE", "NSE", "SR", "SG", "MI"}, f"{n['code']}:EODHD 对这个交易所 404(11-21 实测)"
        assert (ex == "US") == (n["tier"] in ("us_listed", "us_otc")), n
        assert n["key"] == (tick if ex == "US" else n["code"]), "美国线 key = 裸代码(与 World50 同法),其余 key = EODHD 代码"
    assert all(c.cls == "equity" and c.price_source == "eodhd" for c in lg.candidates())


def test_universe_file_matches_the_research_grid():
    g = json.loads(GRID.read_text(encoding="utf-8"))
    assert g["version"] == 2 and len(g["industries"]) == 30 and len(g["regions"]) == 10
    by_code = {p["price_code"]: p for p in g["pool"] if not p["pool_key"] and p["price_code"]}
    assert {n["code"] for n in lg.names()} == set(by_code), "名单与 grid_v2.json 不一致 —— 重跑 build_grid_v2.py"
    for n in lg.names():
        p = by_code[n["code"]]
        assert (p["name"], p["region"], p["industry"], p["price_tier"]) == (n["name"], n["region"], n["industry"], n["tier"])
    leaders = [c["leader"]["slug"] for c in g["cells"]]
    assert len(leaders) == len(set(leaders)), "一家公司只归一个主行业,只能当一格的龙头"
    assert all(c["leader"]["mcap_bn"] >= g["floor_bn"] for c in g["cells"])
    over = g["rules"]["overrides"]
    assert len(over) <= 40 and all(v["why"] for v in over.values()), "改判表逐行写理由;超过 40 行 = 站点口径不能用(S-913)"


def test_weekly_refresh_takes_the_leaders_once_and_world50_codes_first(monkeypatch):
    import src.data.market.tradfi_history as th
    todo = th.default_todo()
    keys = [c.key for c in todo]
    assert len(keys) == len(set(keys))
    assert {n["key"] for n in lg.names()} <= set(keys)
    first = [c.key for c in CANDIDATES if c.price_source == "eodhd"]
    assert keys[: len(first)] == first, "候选池的代码排在最前:撞 key 时留候选池那边"
    seen = []

    async def one(c, start=th.START):
        seen.append(c.key)
        return {"symbol": c.key, "ok": c.code != "SRGHY.US", "why": None if c.code != "SRGHY.US" else "RuntimeError: EODHD eod SRGHY.US HTTP 404"}
    monkeypatch.setattr(th, "refresh_one", one)
    out = asyncio.run(th.run_once())
    assert out["ok"] and len(seen) == len(todo)
    assert {"symbol": "SRGHY", "why": "RuntimeError: EODHD eod SRGHY.US HTTP 404"} in out["failed"]
    assert wd.PART_VERSIONS["prices"] >= 6, "加了代码 = 日线段要重跑一次,不能被 6 天门挡住"


def test_fact_rows_follow_the_registered_rules():
    c = {"units": {"USD": [
        {"start": "2023-01-01", "end": "2023-03-31", "filed": "2023-05-01", "val": -5.0, "accn": "a", "form": "10-Q"},   # 亏损照存
        {"start": "2023-01-01", "end": "2023-03-31", "filed": "2024-05-01", "val": -4.0, "accn": "b", "form": "10-K"},   # 重述 → 不要
        {"start": "2023-01-01", "end": "2023-06-30", "filed": "2023-08-01", "val": 7.0, "accn": "c", "form": "10-Q"},    # 半年累计 → 要
        {"start": "2023-01-01", "end": "2023-09-30", "filed": "2023-11-01", "val": 9.0, "accn": "d", "form": "10-Q"},    # 九个月 → 要
        {"start": "2023-01-01", "end": "2023-02-15", "filed": "2023-05-01", "val": 1.0, "accn": "e"},                    # 45 天 → 不要
        {"start": "2023-01-01", "end": "2023-12-31", "filed": "2024-02-01", "val": float("nan"), "accn": "f"},           # 非有限 → 不要
        {"end": "2023-12-31", "filed": "2024-02-01", "val": 120.0, "accn": "g", "form": "10-K"}]}}                       # 时点值
    rows = wd.fact_rows("X", "us-gaap:NetIncomeLoss", [c])
    got = [(r["period_start"], r["period_end"], r["val"], r["accn"]) for r in rows]
    assert got == [("2023-01-01", "2023-03-31", -5.0, "a"), ("2023-01-01", "2023-06-30", 7.0, "c"),
                   ("2023-01-01", "2023-09-30", 9.0, "d"), ("2023-12-31", "2023-12-31", 120.0, "g")]
    assert set(rows[0]) == set(wd.WRITES_COLUMNS["sec_facts"]) and rows[0]["form"] == "10-Q"
    sh = {"units": {"shares": [{"end": "2024-01-20", "filed": "2024-02-01", "val": 0.0}, {"end": "2024-04-20", "filed": "2024-05-01", "val": 5e9}]}}
    assert [r["val"] for r in wd.fact_rows("X", "dei:EntityCommonStockSharesOutstanding", sh)] == [5e9]


def test_refresh_facts_asks_sec_only_for_filers_and_reports_coverage(monkeypatch):
    import src.api.store as store
    import src.data.market.data_layer as dl
    asked, written = [], []

    async def ciks():
        return {"AAA": 1, "BBB": 2}

    async def concept(cik, tax, tag):
        asked.append((cik, tag))
        if cik == 1 and tag == "NetIncomeLoss":
            return {"units": {"USD": [{"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "val": 3.0}]}}
        if cik == 1 and tag == "PaymentsForRepurchaseOfCommonStock":
            return {"units": {"USD": [{"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "val": 1.0}]}}
        return None

    async def upsert(table, rows, on_conflict=None):
        written.append((table, len(rows), on_conflict))
        return StoreResult.ok_(len(rows))

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(dl, "get_sec_ticker_ciks", ciks)
    monkeypatch.setattr(dl, "get_sec_concept", concept)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(wd.asyncio, "sleep", no_sleep)
    from src.data.universe.world50 import Candidate
    pool = [Candidate("AAA", "A", "equity", "eodhd", "AAA.US", "US"), Candidate("BBB", "B", "equity", "eodhd", "BBB.US", "US"),
            Candidate("CCC", "C", "equity", "eodhd", "CCC.US", "US")]
    out = asyncio.run(wd.refresh_facts(pool))
    assert {c for c, _ in asked} == {1, 2}, "不在 SEC 代码表里的公司一个请求都不发"
    assert out["companies"] == 2 and out["companies_ok"] == 1 and out["not_sec_listed"] == ["CCC"]
    assert out["coverage"]["net_income"] == 1 and out["coverage"]["buyback"] == 1 and out["coverage"]["dividends"] == 0
    assert written == [("sec_facts", 2, "key,tag,unit,period_start,period_end")]
    assert {"key": "BBB", "why": "这几种标签一个都没有"} in out["failed"]
    assert out["ok"] is False, "两家在申报、只成了一家(50% < 60%)⇒ 整段不算成"


def test_facts_is_a_versioned_part_of_the_weekly_loop():
    import inspect
    assert wd.PART_VERSIONS["facts"] >= 1 and "sec_facts" in wd.WRITES_TABLES
    assert '("facts", refresh_facts)' in inspect.getsource(wd.run_week)
    assert wd._say("facts", {"ok": True, "companies": 3, "companies_ok": 2}) == "财报事实 2/3"
    assert wd._brief("facts", {"ok": True, "companies": 3, "companies_ok": 2, "rows": 9, "coverage": {"net_income": 2}})["coverage"] == {"net_income": 2}


def test_float_rows_keep_the_raw_points_and_company_row_reads_submissions():
    frame = {"ccp": "CY2015Q2I", "data": [
        {"accn": "a", "cik": 34088, "entityName": "Exxon Mobil", "loc": "US-TX", "end": "2015-06-30", "val": 346e9},
        {"accn": "b", "cik": 1, "entityName": "Typo Inc", "loc": "US-NY", "end": "2015-06-30", "val": 7.1e17},   # 量级错:照存,研究侧守
        {"accn": "c", "cik": 2, "entityName": "Zero", "end": "2015-06-30", "val": 0},
        {"accn": "d", "cik": "x", "end": "2015-06-30", "val": 5}]}
    rows = wd.float_rows(frame)
    assert [(r["cik"], r["val"]) for r in rows] == [(1, 7.1e17), (34088, 346e9)]
    assert set(rows[0]) == set(wd.WRITES_COLUMNS["sec_public_float"]) and rows[1]["ccp"] == "CY2015Q2I"
    sub = {"cik": "0000040545", "name": "GE Aerospace", "sic": "3720", "sicDescription": "Aircraft & Parts", "tickers": ["GE"],
           "exchanges": ["NYSE"], "stateOfIncorporation": "NY", "fiscalYearEnd": "1231",
           "formerNames": [{"name": "GENERAL ELECTRIC CO", "from": "1994-03-01T00:00:00.000Z", "to": "2024-04-02T00:00:00.000Z"}]}
    row = wd.company_row(sub)
    assert row["cik"] == 40545 and row["sic"] == "3720" and row["tickers"] == "GE"
    assert row["former_names"] == [{"name": "GENERAL ELECTRIC CO", "from": "1994-03-01", "to": "2024-04-02"}]
    assert set(row) == set(wd.WRITES_COLUMNS["sec_company"])
    assert wd.company_row({"name": "no cik"}) is None
    assert wd.company_row({"cik": "5", "tickers": []})["tickers"] is None, "退市公司没有现用代码:空,不是空串"


def test_refresh_public_float_needs_every_year_and_asks_only_the_top(monkeypatch):
    import src.api.store as store
    import src.data.market.data_layer as dl
    asked, written = [], {}

    async def frame(tax, tag, unit, ccp):
        y = int(ccp[2:6])
        if y < 2011:
            return None                                       # XBRL 推行前:没有
        return {"ccp": ccp, "data": [{"cik": c, "end": f"{y}-06-30", "val": float(c), "accn": "x"} for c in range(1, 1201)]}

    async def subs(cik):
        asked.append(cik)
        return {"cik": str(cik), "name": f"C{cik}", "sic": "1000"}

    async def upsert(table, rows, on_conflict=None):
        written[table] = written.get(table, 0) + len(rows)
        return StoreResult.ok_(len(rows))

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(dl, "get_sec_frame", frame)
    monkeypatch.setattr(dl, "get_sec_submissions", subs)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(wd.asyncio, "sleep", no_sleep)
    out = asyncio.run(wd.refresh_public_float(top_n=50))
    years = len(out["points"])
    assert out["ok"] and years >= wd.FLOAT_MIN_YEARS_OK and "CY2010Q2I" not in out["points"]
    assert sorted(asked) == list(range(1151, 1201)), "只给各年前 top_n 的公司取属性"
    assert written == {"sec_public_float": 1200 * years, "sec_company": 50}

    async def broken(tax, tag, unit, ccp):
        if ccp == "CY2018Q2I":
            raise RuntimeError("SEC frames EntityPublicFloat CY2018Q2I HTTP 503")
        return await frame(tax, tag, unit, ccp)
    monkeypatch.setattr(dl, "get_sec_frame", broken)
    out = asyncio.run(wd.refresh_public_float(top_n=50))
    assert out["ok"] is False and "CY2018Q2I" in out["why"], "缺一年的按时点名单不能用 ⇒ 整段不成"
    assert '("float", refresh_public_float)' in __import__("inspect").getsource(wd.run_week) and wd.PART_VERSIONS["float"] >= 1
