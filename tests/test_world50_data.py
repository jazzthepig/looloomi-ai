"""World50 数据第二部分(T-098):历史市值行、链上形式的匹配规则、一周一轮的成败口径。"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.store_result import StoreResult  # noqa: E402
from src.data.universe import world50_data as wd  # noqa: E402
from src.data.universe.world50 import CANDIDATES, Candidate  # noqa: E402


def _bars(prices, start="2020-01-01", adj_ratio=1.0, split_at=None, k=1.0):
    """合成日线:每个工作日一条。split_at 之前原始价是今天口径的 k 倍(一拆 k)。"""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    out, i, n = [], 0, 0
    while n < len(prices):
        d = d0 + timedelta(days=i)
        i += 1
        if d.weekday() >= 5:
            continue
        p = prices[n]
        raw = p * (k if split_at and d.isoformat() < split_at else 1.0)
        out.append({"date": d.isoformat(), "close": raw, "adjusted_close": p * adj_ratio})
        n += 1
    return out


def _concept(facts):
    return {"units": {"shares": facts}}


def _dei(*pts):
    """封面股数:(封面日, 报送日, 股数)。"""
    return _concept([{"end": e, "filed": f, "val": v} for e, f, v in pts])


def test_sec_points_keep_the_original_filing_and_quarter_over_year():
    dei = _dei(("2020-01-17", "2020-01-29", 100.0), ("2020-01-17", "2021-01-28", 999.0), ("bad", "2020-01-01", 5))
    assert wd.sec_points(dei, duration=False) == [("2020-01-17", "2020-01-29", 100.0)], "同一期取最早报送的(原始报告)"
    wavg = _concept([
        {"start": "2023-01-01", "end": "2023-12-31", "filed": "2024-02-01", "val": 12.0},   # 年度
        {"start": "2023-10-01", "end": "2023-12-31", "filed": "2024-02-01", "val": 11.0},   # 同一期末的季度
        {"start": "2023-01-01", "end": "2023-06-30", "filed": "2023-07-25", "val": 9.0},    # 半年累计:不收
        {"start": "2023-04-01", "end": "2023-06-30", "filed": "2023-07-25", "val": 10.0},
    ])
    assert wd.sec_points(wavg, duration=True) == [("2023-06-30", "2023-07-25", 10.0), ("2023-12-31", "2024-02-01", 11.0)]
    assert wd.sec_points(None, duration=False) == []


def test_mcap_is_known_from_filing_date_and_split_consistent():
    # 今天口径价格恒 10;2020-10-15 一拆四。封面股数:拆前报 100,拆后报 400。
    bars = _bars([10.0] * 400, split_at="2020-10-15", k=4.0)
    assert [round(k, 6) for _, k in wd.split_events(bars)] == [4.0]
    dei = _dei(("2020-01-10", "2020-02-03", 100.0), ("2020-07-10", "2020-08-03", 100.0),
               ("2021-01-10", "2021-02-03", 400.0))
    out = wd.build_mcap("X", bars, {"dei": dei})
    assert out["why"] is None and out["src"] == "dei"
    assert {round(r["mcap_usd"], 6) for r in out["rows"]} == {4000.0}, "跨拆股市值连续(今天口径 400 股 × 10)"
    assert out["rows"][0]["d"] >= "2020-02-03", "报送日之前不知道股数 —— 第一周不能早于第一次报送"


def test_a_filing_after_a_split_is_already_restated():
    """拆股后报送的季报会把拆股前的那一季按新口径重述 —— 用报送日(不是期末)决定要不要再乘拆股系数。"""
    bars = _bars([10.0] * 400, split_at="2020-10-15", k=4.0)
    dei = _dei(("2020-01-10", "2020-02-03", 100.0), ("2020-09-30", "2020-10-30", 400.0))   # 期末在拆股前,报送在拆股后
    rows = wd.build_mcap("X", bars, {"dei": dei})["rows"]
    assert {round(r["mcap_usd"], 6) for r in rows} == {4000.0}


def test_wavg_fallback_adr_ratio_outliers_and_jumps():
    bars = _bars([50.0] * 300)
    wavg = _concept([{"start": "2019-10-01", "end": "2019-12-31", "filed": "2020-02-01", "val": 1.0e9},
                     {"start": "2020-01-01", "end": "2020-03-31", "filed": "2020-04-30", "val": 1.0e15},   # 录入错误
                     {"start": "2020-04-01", "end": "2020-06-30", "filed": "2020-07-30", "val": 1.0e9}])
    out = wd.build_mcap("META", bars, {"wavg": wavg})
    assert out["src"] == "wavg" and {round(r["mcap_usd"]) for r in out["rows"]} == {50_000_000_000}
    assert any("录入错误" in n for n in out["notes"])
    two = _dei(("2019-12-31", "2020-01-20", 25.9e9), ("2020-06-30", "2020-07-20", 25.9e9))
    tsm = wd.build_mcap("TSM", bars, {"dei": two})
    assert {round(r["mcap_usd"] / 1e9, 1) for r in tsm["rows"]} == {259.0}, "TSM 一份 ADR = 5 股普通股"
    merged = wd.build_mcap("Y", bars, {"dei": _dei(("2019-12-31", "2020-01-20", 1e9), ("2020-03-31", "2020-04-20", 2e9),
                                                    ("2020-06-30", "2020-07-20", 2e9))})
    assert merged["rows"][0]["d"] >= "2020-04-20" and any("跳" in n for n in merged["notes"]), "股数翻倍:只用之后的段"
    wd.UNVERIFIED_ADR.add("ZZZ")
    try:
        assert wd.build_mcap("ZZZ", bars, {"dei": two})["why"].startswith("ADR 换股比例未核实")
    finally:
        wd.UNVERIFIED_ADR.discard("ZZZ")
    assert wd.build_mcap("TCEHY", bars, {})["src"] == "manual", "腾讯:港交所月报表手工补"
    assert wd.build_mcap("Z", bars, {})["why"].startswith("SEC 里没有")


def test_freshest_source_wins_and_stale_shares_are_refused():
    """MA:封面股数只报到 2010(之后按类别报)—— 按优先级选就会用 16 年前的数。只有一种口径且停在很久以前(当初的 BRK)⇒ 不写。"""
    bars = _bars([100.0] * 300)                                    # 2020-01 → 2021-02
    stale_dei = _dei(("2009-10-28", "2009-11-03", 1.1e8), ("2010-10-27", "2010-11-02", 1.2e8))
    fresh_cso = _dei(("2019-12-31", "2020-02-01", 9.0e8), ("2020-06-30", "2020-07-30", 9.0e8))
    out = wd.build_mcap("MA", bars, {"dei": stale_dei, "cso": fresh_cso})
    assert out["src"] == "cso" and {round(r["mcap_usd"] / 1e9) for r in out["rows"]} == {90}
    both_fresh = wd.build_mcap("MA", bars, {"dei": fresh_cso, "cso": fresh_cso})
    assert both_fresh["src"] == "dei", "一样新时封面股数优先"
    old = wd.build_mcap("OLD", bars, {"wavg": _concept([
        {"start": "2014-07-01", "end": "2014-09-30", "filed": "2014-11-07", "val": 1.64e6},
        {"start": "2015-07-01", "end": "2015-09-30", "filed": "2015-11-06", "val": 1.64e6}])})
    assert old["rows"] == [] and old["why"].startswith("股数停在 2015-11-06")


def test_single_bad_point_is_dropped_and_a_jump_in_the_newest_point_is_refused():
    bars = _bars([10.0] * 400)
    spike = _dei(("2019-12-31", "2020-01-20", 4.0e9), ("2020-03-31", "2020-04-20", 2.0e9), ("2020-06-30", "2020-07-20", 3.9e9))
    out = wd.build_mcap("WFC", bars, {"dei": spike})
    assert out["why"] is None and out["rows"][0]["d"] < "2020-04-20", "单点错只丢那个点,历史不截断"
    assert any("单点错" in n for n in out["notes"])
    assert {round(r["mcap_usd"] / 1e9) for r in out["rows"]} <= {40, 39}
    newest = _dei(("2019-12-31", "2020-01-20", 1.8e10), ("2020-03-31", "2020-04-20", 1.8e10), ("2020-06-30", "2020-07-20", 1.8e9))
    out = wd.build_mcap("Q", bars, {"dei": newest})
    assert out["rows"] == [] and out["why"].startswith("最新一期股数跳"), "只剩最新一个点:分不清是公司变了还是换了口径 ⇒ 不写"


def test_metal_mcap_is_investable_and_none_when_unknown():
    g = wd.metal_mcap_usd("XAUUSD", 2000.0)
    assert g == pytest.approx(50_978 * 32_150.7466 * 2000)
    assert wd.metal_mcap_usd("XAUUSD", 2000.0, "bars_coins_etfs_cb") > g
    assert wd.metal_mcap_usd("XAGUSD", 30.0) is None, "白银没有可靠存量来源 ⇒ 不可算,不是 0"
    with pytest.raises(ValueError):
        wd.metal_mcap_usd("XAUUSD", 2000.0, "above_ground")


@pytest.mark.parametrize("symbol,name,at,key,rule", [
    ("NVDA", "NVIDIA xStock", "stock", "NVDA", "ticker"),
    ("NVDAx", "NVIDIA xStock", "stock", "NVDA", "ticker-strip:NVDA"),
    ("AAPLon", "Apple (Ondo Tokenized)", "stock", "AAPL", "ticker-strip:AAPL"),
    ("BRK.Bx", "Berkshire Hathaway xStock", "stock", "BRK-B", "ticker-strip:BRKB"),
    ("Vx", "Visa xStock", "stock", "V", "ticker-strip:V"),
    ("MAX", "MaxLinear tokenized", "stock", None, "unmatched"),   # 短代码去后缀撞上 MA,名字对不上 ⇒ 不收
    ("GDX", "VanEck Gold Miners xStock", "etf", None, "etf-not-a-member"),
    ("NEM", "Newmont Gold Corp", "stock", None, "unmatched"),     # 金矿公司不是黄金
    ("GLDx", "SPDR Gold Shares xStock", "etf", "XAUUSD", "metal-etf:GLD"),
    ("PAXG", "PAX Gold", "commodity", "XAUUSD", "commodity:gold"),
    ("XAGT", "Tokenized Silver", "commodity", "XAGUSD", "commodity:silver"),
    ("OILX", "Tokenized Crude", "commodity", None, "commodity-not-a-candidate"),
    ("NESN", "Nestle SA tokenized", "stock", "NESN.SW", "name:Nestlé"),
    ("BOC", "Agricultural Bank of China tokenized", "stock", "601288.SHG", "name:Agricultural Bank of China"),
])
def test_match_rwa_rules(symbol, name, at, key, rule):
    assert wd.match_rwa(symbol, name, at, CANDIDATES) == (key, rule)


def test_form_rows_read_nested_market_data_and_keep_unmatched():
    raw = [
        {"id": "nvidia-xstock", "symbol": "NVDAx", "name": "NVIDIA xStock", "asset_type": "stock",
         "tokenized_market_data": {"market_cap": 5e7, "total_volume": 1e6, "current_price": 180.0}},
        {"id": "mystery", "symbol": "ZZZ", "name": "Mystery", "asset_type": "stock", "market_cap": 9e9},
        {"id": "nvidia-xstock", "symbol": "NVDAx", "name": "dup", "asset_type": "stock"},
        {"symbol": "NOID"},
    ]
    rows = wd.form_rows(raw, {"nvidia-xstock": {"xstocks", "backed"}}, CANDIDATES, "2026-10-14")
    assert [r["token_id"] for r in rows] == ["nvidia-xstock", "mystery"], "同一 id 只收一次;没 id 的不收"
    n, m = rows
    assert n["key"] == "NVDA" and n["mcap_usd"] == 5e7 and n["price_usd"] == 180.0 and n["issuer"] == "backed|xstocks"
    assert n["category"] == "rwa:stock"
    assert m["key"] is None and m["match_rule"] == "unmatched", "对不上的也写,方便查漏配"
    assert m["mcap_usd"] is None, "顶层 market_cap 不是代币化市值(S-266)—— 没测是 None,不是借来的数"
    assert set(n) == set(wd.WRITES_COLUMNS["world50_onchain_forms"]), "行的列 = 声明的列(schema_manifest 靠它)"


def _patch_store(monkeypatch, sink):
    import src.api.store as store

    async def fake_upsert(table, rows, on_conflict):
        sink.setdefault(table, []).extend(rows)
        return StoreResult.ok_(True)
    monkeypatch.setattr(store, "supabase_upsert_table", fake_upsert)


def test_refresh_mcap_reports_failures_and_writes_only_good(monkeypatch):
    import src.data.market.data_layer as dl
    sink: dict = {}
    _patch_store(monkeypatch, sink)
    bars = _bars([10.0] * 300)

    async def ciks():
        return {"GOOD": 1, "NOPE": 2}

    calls = []

    async def concept(cik, taxonomy, tag):
        calls.append((cik, tag))
        if cik == 2:
            raise RuntimeError("SEC companyconcept 2 HTTP 500")
        return _dei(("2019-12-31", "2020-01-20", 100.0), ("2020-06-30", "2020-07-20", 100.0)) if taxonomy == "dei" else None

    async def eod(ticker, ex, frm):
        return bars
    monkeypatch.setattr(dl, "get_sec_ticker_ciks", ciks)
    monkeypatch.setattr(dl, "get_sec_concept", concept)
    monkeypatch.setattr(dl, "get_eodhd_eod_range", eod)
    good = Candidate("GOOD", "Good", "equity", "eodhd", "GOOD.US", "US")
    bad = Candidate("NOPE", "Nope", "equity", "eodhd", "NOPE.US", "US")
    absent = Candidate("ABSENT", "Absent", "equity", "eodhd", "ABSENT.US", "US")
    local = Candidate("2222.SR", "Aramco", "equity", "eodhd", "2222.SR", "SA")
    out = asyncio.run(wd.refresh_mcap(candidates=[good, bad, absent, local]))
    assert {r["key"] for r in sink["world50_mcap_weekly"]} == {"GOOD"}
    assert all(r["source"] == wd.MCAP_SOURCE for r in sink["world50_mcap_weekly"])
    assert out["companies"] == 3 and out["not_sec_listed"] == ["2222.SR"], "本地上市不在 SEC:单列,不算失败"
    why = {f["key"]: f["why"] for f in out["failed"]}
    assert "HTTP 500" in why["NOPE"] and why["ABSENT"] == "不在 SEC 申报公司表里"
    assert out["ok"] is False and out["latest_bn"] == {"GOOD": 0.0}
    assert {tag for cik, tag in calls if cik == 1} == {"EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding",
                                                         "WeightedAverageNumberOfSharesOutstandingBasic",
                                                         "WeightedAverageShares"}, "四种口径都取"


def test_predecessor_cik_history_is_joined(monkeypatch):
    import src.data.market.data_layer as dl
    sink: dict = {}
    _patch_store(monkeypatch, sink)
    bars = _bars([100.0] * 300)

    async def ciks():
        return {"XOM": 2115436}

    async def concept(cik, taxonomy, tag):
        if taxonomy != "dei":
            return None
        if cik == 34088:
            return _dei(("2019-12-31", "2020-01-20", 4.2e9), ("2020-03-31", "2020-04-20", 4.2e9))
        return _dei(("2020-06-30", "2020-07-20", 4.1e9), ("2020-09-30", "2020-10-20", 4.1e9))

    async def eod(ticker, ex, frm):
        return bars
    monkeypatch.setattr(dl, "get_sec_ticker_ciks", ciks)
    monkeypatch.setattr(dl, "get_sec_concept", concept)
    monkeypatch.setattr(dl, "get_eodhd_eod_range", eod)
    out = asyncio.run(wd.refresh_mcap(candidates=[Candidate("XOM", "Exxon Mobil", "equity", "eodhd", "XOM.US", "US")]))
    assert out["companies_ok"] == 1 and min(r["d"] for r in sink["world50_mcap_weekly"]) < "2020-02-01", "旧 CIK 的历史接上"


def test_discover_onchain_forms_and_issuer_failure_is_reported(monkeypatch):
    import src.data.market.data_layer as dl
    sink: dict = {}
    _patch_store(monkeypatch, sink)

    async def markets(issuer=None, per_page=250, max_pages=20):
        if issuer == "broken":
            raise RuntimeError("HTTP 500")
        if issuer == "ondo":
            return [{"id": "apple-ondo"}]
        return [{"id": "apple-ondo", "symbol": "AAPLon", "name": "Apple (Ondo Tokenized)", "asset_type": "stock",
                 "tokenized_market_data": {"market_cap": 1e8, "total_volume": 2e6}},
                {"id": "pax-gold", "symbol": "PAXG", "name": "PAX Gold", "asset_type": "commodity",
                 "tokenized_market_data": {"market_cap": 1e9}}]

    async def issuers():
        return [{"id": "ondo", "name": "Ondo"}, {"id": "broken", "name": "Broken"}]
    monkeypatch.setattr(dl, "get_cg_rwa_markets", markets)
    monkeypatch.setattr(dl, "get_cg_rwa_issuers", issuers)
    out = asyncio.run(wd.discover_onchain_forms(as_of="2026-10-14"))
    assert out["ok"] is True and out["tokens"] == 2 and out["candidates_with_form"] == 2
    assert out["by_type"] == {"rwa:stock": 1, "rwa:commodity": 1}
    assert out["issuer_failed"] == ["broken: RuntimeError"], "一家发行方读不到:照写,但报出来"
    got = {r["token_id"]: r for r in sink["world50_onchain_forms"]}
    assert got["apple-ondo"]["issuer"] == "ondo" and got["pax-gold"]["issuer"] is None


def test_run_week_is_not_ok_when_any_part_fails(monkeypatch):
    import src.data.market.tradfi_history as th

    async def prices():
        return {"ok": True, "refused": False, "symbols": 100, "symbols_ok": 98, "written": 1, "elapsed_s": 1.0}

    async def mcap():
        raise RuntimeError("EODHD fundamentals HTTP 500")

    async def forms():
        return {"ok": True, "tokens": 600, "candidates_with_form": 40}

    async def nothing_recent():
        return set()
    monkeypatch.setattr(th, "run_once", prices)
    monkeypatch.setattr(wd, "refresh_mcap", mcap)
    monkeypatch.setattr(wd, "discover_onchain_forms", forms)
    monkeypatch.setattr(wd, "_recent_ok_parts", nothing_recent)
    out = asyncio.run(wd.run_week())
    assert out["ok"] is False and out["refused"] is False
    assert out["reason"].startswith("没成的段:mcap"), out["reason"]
    assert "HTTP 500" in out["parts"]["mcap"]["why"]
    assert out["parts"]["prices"] == {"ok": True, "v": wd.PART_VERSIONS["prices"], "symbols": 100, "symbols_ok": 98,
                                      "written": 1, "elapsed_s": 1.0}


def test_deploys_do_not_rerun_parts_that_already_succeeded(monkeypatch):
    """每次部署都重启循环:6 天内真跑成的段跳过;**跳过不续期**,否则永远不再真跑。"""
    from datetime import datetime, timezone
    import src.data.signals.hl_book_daily as hb
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    rows = [
        {"at": "2026-10-19T00:00:00+00:00", "detail": {"prices": {"ok": True, "skipped": "6 天内已成"},
                                                      "mcap": {"ok": False, "why": "x"}}},
        {"at": "2026-10-16T00:00:00+00:00", "detail": {"prices": {"ok": True, "symbols": 100, "v": wd.PART_VERSIONS["prices"]},
                                                      "onchain_forms": {"ok": True, "skipped": "6 天内已成"}}},
        {"at": "2026-10-10T00:00:00+00:00", "detail": {"onchain_forms": {"ok": True, "tokens": 900}}},
    ]

    async def get(tail):
        assert "loop_name=eq._world50_history_loop" in tail
        return rows
    monkeypatch.setattr(hb, "_supabase_get", get)
    assert asyncio.run(wd._recent_ok_parts(now)) == {"prices"}, "链上形式上次真跑是 10 天前 ⇒ 要重跑;市值上次失败 ⇒ 要重跑"
    rows.insert(0, {"at": "2026-10-19T12:00:00+00:00", "detail": {"mcap": {"ok": True, "companies_ok": 75}}})
    assert "mcap" not in asyncio.run(wd._recent_ok_parts(now)), "算法升了版本:旧版本跑成的不算已成"
    rows.insert(0, {"at": "2026-10-19T13:00:00+00:00", "detail": {"mcap": {"ok": True, "v": wd.PART_VERSIONS["mcap"]}}})
    assert "mcap" in asyncio.run(wd._recent_ok_parts(now))

    async def boom(tail):
        raise RuntimeError("HTTP 503")
    monkeypatch.setattr(hb, "_supabase_get", boom)
    assert asyncio.run(wd._recent_ok_parts(now)) == set(), "读不到 ⇒ 全跑"

    import src.data.market.tradfi_history as th
    ran = []

    async def prices():
        ran.append("prices")
        return {"ok": True}

    async def recent():
        return {"prices", "mcap", "onchain_forms"}
    monkeypatch.setattr(th, "run_once", prices)
    monkeypatch.setattr(wd, "_recent_ok_parts", recent)
    out = asyncio.run(wd.run_week())
    assert ran == [] and out["ok"] is True and out["parts"]["prices"]["skipped"]
    assert "跳过" in out["reason"]


def test_sec_user_agent_comes_only_from_the_environment(monkeypatch):
    """仓库是公开的:SEC 要的联系邮箱只放 Railway 环境变量,不进代码(Jazz 10-15)。"""
    import re
    import src.data.market.data_layer as dl
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        dl._sec_headers()
    monkeypatch.setenv("SEC_USER_AGENT", "Example Org ops@example.com")
    assert dl._sec_headers()["User-Agent"] == "Example Org ops@example.com"
    src = (ROOT / "src/data/market/data_layer.py").read_text(encoding="utf-8")
    block = src[src.index("def _sec_headers"):src.index("async def get_sec_concept")]
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", block), "SEC 那段代码里不许出现邮箱"


def test_manual_shares_are_current_basis_and_do_not_need_sec(monkeypatch):
    """Visa / Berkshire 的股数手工从 10-K 补(Jazz 10-15):表里的数已是今天口径 —— 2015 年一拆四之前报送的那一行不能再乘 4。"""
    for key, m in wd.MANUAL_SHARES.items():
        assert len(m["rows"]) >= 5 and all(re.fullmatch(r"\d{10}-\d{2}-\d{6}", acc) or acc.startswith("hkex:/listedco/")
                                           for *_, acc in m["rows"]), key
        assert [r[1] for r in m["rows"]] == sorted(r[1] for r in m["rows"]), "按报送日排好"
    bars = _bars([100.0] * 120, start="2015-01-01", split_at="2015-03-19", k=4.0)
    out = wd.build_mcap("V", bars, {})
    assert out["src"] == "manual" and out["why"] is None
    first = out["rows"][0]
    assert first["d"] < "2015-03-19" and round(first["mcap_usd"] / 1e9) == 247, "2,470M × 100(今天口径),不是 × 400"

    import src.data.market.data_layer as dl
    sink: dict = {}
    _patch_store(monkeypatch, sink)

    async def no_sec():
        raise RuntimeError("SEC_USER_AGENT 不在进程环境里")

    async def eod(ticker, ex, frm):
        return bars
    monkeypatch.setattr(dl, "get_sec_ticker_ciks", no_sec)
    monkeypatch.setattr(dl, "get_eodhd_eod_range", eod)
    res = asyncio.run(wd.refresh_mcap(candidates=[Candidate("V", "Visa", "equity", "eodhd", "V.US", "US"),
                                                  Candidate("AAPL", "Apple", "equity", "eodhd", "AAPL.US", "US")]))
    assert {r["key"] for r in sink["world50_mcap_weekly"]} == {"V"} and res["manual"] == ["V"]
    assert "SEC_USER_AGENT" in res["why"] and res["failed"][0]["key"] == "AAPL", "SEC 读不到:手工的照写,其余报原因"


def test_ifrs_source_sec_fix_and_adr_ratio_changes():
    bars = _bars([10.0] * 300)
    ifrs = _concept([{"start": "2018-01-01", "end": "2018-12-31", "filed": "2019-02-01", "val": 2.4e9},
                     {"start": "2019-01-01", "end": "2019-12-31", "filed": "2020-02-01", "val": 2.4e9}])
    out = wd.build_mcap("NVO", bars, {"ifrs_wavg": ifrs})
    assert out["src"] == "ifrs_wavg" and {round(r["mcap_usd"] / 1e9) for r in out["rows"]} == {24}, "IFRS 公司(Novo A + B)"
    # BABA:XBRL 少一位 → 按 20-F 封面更正;不更正就是「最新一期跳 ×0.10」被拒
    baba = _dei(("2024-03-31", "2019-12-01", 1.9e10), ("2025-03-31", "2020-01-10", 1.9e10), ("2026-03-31", "2020-02-10", 1.9e9))
    assert wd.SEC_FIX["BABA"]["2026-03-31"][0] == 18_580_374_278
    fixed = wd.build_mcap("BABA", bars, {"dei": baba})
    assert fixed["why"] is None and {round(r["mcap_usd"] / 1e9, 1) for r in fixed["rows"]} <= {23.8, 23.2}, "1.9e10 / 8 × 10"
    # TM:一拆五后普通股 ×5,ADR 从 2 股改为 10 股,ADR 价不动 —— 市值连续
    tm = _dei(("2021-03-31", "2021-06-24", 3.26e9), ("2022-03-31", "2022-06-23", 16.3e9))
    tm_rows = wd.build_mcap("TM", _bars([10.0] * 500, start="2021-01-01"), {"dei": tm})["rows"]
    assert len(tm_rows) > 50 and {round(r["mcap_usd"] / 1e9, 1) for r in tm_rows} == {16.3}


def test_crypto_mcap_backfill_uses_the_existing_path_and_skips_what_exists(monkeypatch):
    """2015–2019 的加密市值:同一张表、同一来源标签、同一个解析函数;已有就不重取。"""
    import src.data.market.data_layer as dl
    import src.data.signals.hl_book_daily as hb
    from src.data.style.header import SOURCE
    sink: dict = {}
    _patch_store(monkeypatch, sink)

    async def have(tail):
        return [] if "symbol=eq.BTC" in tail else [{"d": "2017-01-01"}]

    calls = []

    async def chart(cid, frm, to, interval=None):
        calls.append(cid)
        day = 1_514_764_800_000          # 2018-01-01 00:00 UTC
        return {"available": True, "prices": [[day, 13_000.0]], "market_caps": [[day, 2.2e11]], "volumes": [[day, 1e10]]}
    monkeypatch.setattr(hb, "_supabase_get", have)
    monkeypatch.setattr(dl, "get_cg_market_chart_range", chart)
    out = asyncio.run(wd.backfill_crypto_mcap())
    assert calls == ["bitcoin"] and out["BTC"] == 1 and out["ETH"] == "已有"
    row = sink["asset_mcap_daily"][0]
    assert row["symbol"] == "BTC" and row["coin_id"] == "bitcoin" and row["source"] == SOURCE and row["mcap"] == 2.2e11
