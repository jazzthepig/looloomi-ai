"""事件库(11-02):Binance 公告标题解析、HL 新代币第一轮只登记、新闻映射、一轮 run_once 的写入与错误汇总。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import events as ev  # noqa: E402

NOW = dt.datetime(2026, 11, 2, 16, 0, tzinfo=dt.timezone.utc)


def test_binance_titles_parse_to_symbols_kind_and_scope():
    assert ev.symbols_from_title("Binance Will List Hyperliquid (HYPE) and Plasma (XPL) with Seed Tag Applied") == ["HYPE", "XPL"]
    assert ev.symbols_from_title("Binance Will Delist ICX, SCRT, STORJ on 2026-09-03") == ["ICX", "SCRT", "STORJ"]
    assert ev.symbols_from_title("Binance Futures Will Launch USDⓈ-Margined MARSCOINUSDT Perpetual Contract (2026-09-01)") == ["MARSCOIN"]
    assert ev.symbols_from_title("Notice of Removal of Spot Trading Pairs - 2026-08-21") == []
    assert ev.symbols_from_title("Binance Margin And Loan Will Delist BTTC & POWR on 2026-08-14") == ["BTTC", "POWR"]
    assert ev.binance_kind("Binance Futures Will Launch X", "listing") == "perp_listing"
    assert ev.binance_kind("Binance Will List X", "listing") == "listing"
    assert ev.binance_scope("Binance Alpha Will Remove TTD") == "alpha" and ev.binance_scope("Binance Will List X (X)") == "spot"
    payload = {"data": {"catalogs": [{"articles": [
        {"id": 1, "code": "abc", "title": "Binance Will List Foo (FOO)", "releaseDate": 1788252305663},
        {"id": 2, "code": "", "title": "no code"}]}]}}
    rows = ev.parse_binance(payload, 48)
    assert len(rows) == 1 and rows[0]["symbols"] == ["FOO"] and rows[0]["kind"] == "listing" and rows[0]["ts"].startswith("2026-09-01")
    assert rows[0]["url"].endswith("/abc") and rows[0]["id"] == ev.event_id("binance", "abc")


def test_hl_new_tokens_first_round_only_registers():
    meta = {"tokens": [{"name": "USDC"}, {"name": "UBTC"}, {"name": "NEWT"}]}
    evs, names = ev.hl_new_tokens(meta, None, NOW)
    assert evs == [] and names == {"USDC", "UBTC", "NEWT"}, "第一轮只登记,不把 300 个老代币当今天上市"
    evs2, names2 = ev.hl_new_tokens(meta, {"USDC", "UBTC"}, NOW)
    assert [e["symbols"] for e in evs2] == [["NEWT"]] and evs2[0]["kind"] == "listing" and evs2[0]["source"] == "hyperliquid"


def test_news_events_only_for_items_that_name_someone():
    items = [{"id": "n1", "source": "The Block", "title": "x", "link": "https://t/1", "published_at": "2026-11-02T10:00:00+00:00",
              "fetched_at": "2026-11-02T10:05:00+00:00", "hits": ["BTC"], "score": 3},
             {"id": "n2", "source": "Decrypt", "title": "y", "link": "https://t/2", "published_at": None, "fetched_at": "2026-11-02T10:05:00+00:00",
              "hits": [], "score": 0}]
    out = ev.news_events(items)
    assert len(out) == 1 and out[0]["kind"] == "news" and out[0]["source"] == "the_block" and out[0]["ts"] == "2026-11-02T10:00:00+00:00"


def test_run_once_writes_all_three_writers_and_reports_errors(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    import src.data.venues.hl_spot as hl
    up, redis = [], {}

    async def read_all(t, params):
        assert t == "feed_items"
        return [{"id": "n1", "source": "CoinDesk", "title": "t", "link": "https://t/1", "published_at": None,
                 "fetched_at": "2026-11-02T15:00:00+00:00", "hits": ["ETH"], "score": 4}]

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True

    async def rget(key):
        return redis.get(key), "hit" if key in redis else "miss"

    async def rset(key, data, ttl=7200):
        redis[key] = data
        return True

    class FakeResp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            if params["catalogId"] == 48:
                page = params["pageNo"]
                arts = [{"id": page, "code": f"c{page}", "title": f"Binance Will List Foo{page} (FOO{page})", "releaseDate": 1788252305663}] if page <= 3 else []
                return FakeResp(200, {"data": {"catalogs": [{"total": 60, "articles": arts}]}})
            return FakeResp(503, {})
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    monkeypatch.setattr(store, "redis_get_key_status", rget)
    monkeypatch.setattr(store, "redis_set_key", rset)
    monkeypatch.setattr(hl.HlSpotClient, "spot_meta", lambda self: {"tokens": [{"name": "USDC"}, {"name": "UBTC"}]})
    r = asyncio.run(ev.run_once(NOW))
    assert r["ok"] and r["written"] == 4 and r["kinds"] == {"news": 1, "listing": 3} and r["errors"] == ["binance 161: HTTP 503"]
    assert r["backfill"]["48"]["done"] is True, "第 4 页空 ⇒ 回填完"
    assert redis[ev.HL_SEEN_KEY]["names"] == ["UBTC", "USDC"], "第一轮登记 HL 代币"
    monkeypatch.setattr(hl.HlSpotClient, "spot_meta", lambda self: {"tokens": [{"name": "USDC"}, {"name": "UBTC"}, {"name": "NEWT"}]})
    up.clear()
    r = asyncio.run(ev.run_once(NOW))
    assert any(x["source"] == "hyperliquid" and x["symbols"] == ["NEWT"] for x in up), "第二轮新代币成事件"


def test_loop_and_migration_are_wired():
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "_events_loop" in src and "_start_events_loop" in src
    mig = (ROOT / "migrations/2026-11-02_events.sql").read_text(encoding="utf-8")
    for col in ev.WRITES_COLUMNS["events"]:
        assert col in mig, col
