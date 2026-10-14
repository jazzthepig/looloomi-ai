"""World50 数据第二部分(T-098):历史市值行、链上形式的匹配规则、一周一轮的成败口径。"""
from __future__ import annotations

import asyncio
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


def _fund(points, ccy="USD", mcap_now=None):
    return {"General": {"CurrencyCode": ccy}, "Highlights": {"MarketCapitalization": mcap_now},
            "outstandingShares": {"quarterly": {str(i): {"dateFormatted": d, "shares": v}
                                                for i, (d, v) in enumerate(points)}}}


def test_shares_points_and_flat_or_nested_shape():
    flat = {"outstandingShares::quarterly": {"0": {"dateFormatted": "2020-03-31", "sharesMln": "100.5"},
                                             "1": {"dateFormatted": "bad", "shares": 5}, "2": {"dateFormatted": "2019-12-31", "shares": 0}}}
    assert wd.shares_points(flat) == [("2020-03-31", 100.5e6)], "平铺形状也收;坏日期、0 股不收"
    assert wd.shares_points(_fund([("2020-06-30", 2.0), ("2020-03-31", 1.0)])) == [("2020-03-31", 1.0), ("2020-06-30", 2.0)]


def test_mcap_is_point_in_time_and_split_consistent():
    # 400 个交易日,今天口径价格恒 10;第 200 天一拆四。股本「当时报告」:拆前 100,拆后 400。
    bars = _bars([10.0] * 400, split_at="2020-10-15", k=4.0)
    assert [k for _, k in wd.split_events(bars)] == [pytest.approx(4.0)]
    pts = [("2019-12-31", 100.0), ("2020-03-31", 100.0), ("2020-06-30", 100.0), ("2020-12-31", 400.0), ("2021-03-31", 400.0)]
    assert wd.shares_basis(wd.split_events(bars), pts) == "as_reported"
    out = wd.build_mcap("X", bars, _fund(pts, mcap_now=4000.0), None, "USD")
    assert out["why"] is None and out["basis"] == "as_reported" and out["calib"] == pytest.approx(1.0)
    assert {round(r["mcap_usd"], 6) for r in out["rows"]} == {4000.0}, "跨拆股市值连续(今天口径:400 股 × 10)"
    assert out["rows"][0]["d"] >= "2020-02-29", "季末 60 天后股本才算已知 —— 第一周不能早于 2019-12-31 + 60 天"
    # 同一组数,股本按今天口径回改过(拆前也是 400)
    adj_pts = [(d, 400.0) for d, _ in pts]
    assert wd.shares_basis(wd.split_events(bars), adj_pts) == "adjusted"
    assert {round(r["mcap_usd"], 6) for r in wd.build_mcap("X", bars, _fund(adj_pts, mcap_now=4000.0), None, "USD")["rows"]} == {4000.0}


def test_mcap_refuses_when_calibration_or_basis_is_off():
    bars = _bars([10.0] * 300)
    pts = [("2019-12-31", 100.0), ("2020-06-30", 100.0)]
    adr = wd.build_mcap("TSM", bars, _fund(pts, mcap_now=5000.0), None, "USD")
    assert adr["rows"] == [] and "×0.20" in adr["why"], "差 5 倍(ADR 换股比例)⇒ 不写,比值报出来"
    split = _bars([10.0] * 300, split_at="2020-06-01", k=3.0)
    odd = [("2019-12-31", 100.0), ("2020-06-30", 170.0)]
    amb = wd.build_mcap("Y", split, _fund(odd, mcap_now=1700.0), None, "USD")
    assert amb["rows"] == [] and amb["basis"] == "ambiguous", "拆股前后股本之比既不是 1 也不是 k ⇒ 不猜"
    assert wd.build_mcap("Z", bars, _fund(pts, ccy="KRW", mcap_now=1000.0), None, "KRW")["why"] == "KRW 汇率读不到"


def test_mcap_converts_local_currency_with_last_known_fx():
    bars = _bars([1000.0] * 300)
    fx = [(r["date"], 1250.0) for r in bars[::3]]            # USDKRW,隔几天才有一个点
    out = wd.build_mcap("005930.KO", bars, _fund([("2019-12-31", 1e6)], ccy="KRW", mcap_now=1e9), fx, "KRW")
    assert out["why"] is None and out["calib"] == pytest.approx(1.0), "当前市值按本币给也能校准"
    assert {round(r["mcap_usd"]) for r in out["rows"]} == {800000}, "1e6 股 × 1000 韩元 ÷ 1250"


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

    async def fund(ticker, ex):
        if ticker == "NOPE":
            raise RuntimeError("EODHD fundamentals NOPE.US HTTP 404")
        return _fund([("2019-12-31", 100.0)], mcap_now=1000.0)

    async def eod(ticker, ex, frm):
        return bars
    monkeypatch.setattr(dl, "get_eodhd_share_history", fund)
    monkeypatch.setattr(dl, "get_eodhd_eod_range", eod)
    good = Candidate("GOOD", "Good", "equity", "eodhd", "GOOD.US", "US")
    bad = Candidate("NOPE", "Nope", "equity", "eodhd", "NOPE.US", "US")
    out = asyncio.run(wd.refresh_mcap(candidates=[good, bad]))
    assert {r["key"] for r in sink["world50_mcap_weekly"]} == {"GOOD"}
    assert all(r["source"] == wd.MCAP_SOURCE for r in sink["world50_mcap_weekly"])
    assert out["companies_ok"] == 1 and out["failed"][0]["key"] == "NOPE" and "404" in out["failed"][0]["why"]
    assert out["ok"] is False, "两家只取到一家(< 60%)⇒ 整段不算 ok"


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
    assert out["parts"]["prices"] == {"ok": True, "symbols": 100, "symbols_ok": 98, "written": 1, "elapsed_s": 1.0}


def test_deploys_do_not_rerun_parts_that_already_succeeded(monkeypatch):
    """每次部署都重启循环:6 天内真跑成的段跳过;**跳过不续期**,否则永远不再真跑。"""
    from datetime import datetime, timezone
    import src.data.signals.hl_book_daily as hb
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    rows = [
        {"at": "2026-10-19T00:00:00+00:00", "detail": {"prices": {"ok": True, "skipped": "6 天内已成"},
                                                      "mcap": {"ok": False, "why": "x"}}},
        {"at": "2026-10-16T00:00:00+00:00", "detail": {"prices": {"ok": True, "symbols": 100},
                                                      "onchain_forms": {"ok": True, "skipped": "6 天内已成"}}},
        {"at": "2026-10-10T00:00:00+00:00", "detail": {"onchain_forms": {"ok": True, "tokens": 900}}},
    ]

    async def get(tail):
        assert "loop_name=eq._world50_history_loop" in tail
        return rows
    monkeypatch.setattr(hb, "_supabase_get", get)
    assert asyncio.run(wd._recent_ok_parts(now)) == {"prices"}, "链上形式上次真跑是 10 天前 ⇒ 要重跑;市值上次失败 ⇒ 要重跑"

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
