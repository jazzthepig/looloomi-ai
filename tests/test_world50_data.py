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


def test_mcap_rows_keep_only_real_numbers():
    raw = [{"date": "2015-01-02", "value": "7.1e11"}, {"date": "2015-01-09", "value": None},
           {"date": "2015-01-16", "value": 0}, {"date": "bad", "value": 1}, {"date": "2015-01-23", "value": 7.2e11}]
    rows = wd.mcap_rows("AAPL", raw)
    assert [r["d"] for r in rows] == ["2015-01-02", "2015-01-23"], "None / 0 / 坏日期不收 —— 不拿 0 冒充市值"
    assert rows[0] == {"key": "AAPL", "d": "2015-01-02", "mcap_usd": 7.1e11, "source": "eodhd_hist_mcap"}


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

    async def hist(ticker, ex, frm):
        if ticker == "NOPE":
            raise RuntimeError("EODHD historical-market-cap NOPE.US HTTP 404")
        return [{"date": "2015-01-02", "value": 1e11}]
    monkeypatch.setattr(dl, "get_eodhd_historical_mcap", hist)
    good = Candidate("GOOD", "Good", "equity", "eodhd", "GOOD.US", "US")
    bad = Candidate("NOPE", "Nope", "equity", "eodhd", "NOPE.US", "US")
    out = asyncio.run(wd.refresh_mcap(candidates=[good, bad]))
    assert [r["key"] for r in sink["world50_mcap_weekly"]] == ["GOOD"]
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
        raise RuntimeError("EODHD plan does not include historical-market-cap")

    async def forms():
        return {"ok": True, "tokens": 600, "candidates_with_form": 40}
    monkeypatch.setattr(th, "run_once", prices)
    monkeypatch.setattr(wd, "refresh_mcap", mcap)
    monkeypatch.setattr(wd, "discover_onchain_forms", forms)
    out = asyncio.run(wd.run_week())
    assert out["ok"] is False and out["refused"] is False
    assert out["reason"].startswith("没成的段:mcap"), out["reason"]
    assert "historical-market-cap" in out["parts"]["mcap"]["why"]
    assert out["parts"]["prices"] == {"ok": True, "symbols": 100, "symbols_ok": 98, "written": 1, "elapsed_s": 1.0}
