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
    assert r["ok"] and r["written"] == 4 and r["kinds"] == {"news": 1, "listing": 3} and r["errors"] == ["binance 161: HTTP 503", "binance 49: HTTP 503"]
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


def test_title_variants_11_06():
    """lane-b T-262:perp_listing 818 条里 453 条 symbols 空 —— 这些写法以前认不出。"""
    f = ev.symbols_from_title
    assert f("Binance Futures Will Launch USDⓈ-M OXT Perpetual Contract With Up to 20x Leverage") == ["OXT"]
    assert f("Binance Futures Will Launch UNI USDT-Margined Perpetual Contract With Up to 50x Leverage") == ["UNI"]
    assert f("Binance Futures Will Launch XMR/USDT Perpetual Contract With Up to 75x Leverage") == ["XMR"]
    assert f("Binance Futures Will Launch DOGSUSD COIN-M Perpetual Contract with up to 20x Leverage") == ["DOGS"]
    assert f("Binance Futures Will Launch USDⓈ-M ZK and ZRO Perpetual Contracts") == ["ZK", "ZRO"]
    assert f("Binance Futures Will Launch USDC-Margined 1000SHIB Perpetual Contract With Up to 50x Leverage") == ["1000SHIB"]
    assert f("COCOS, IQ, PHA, PROM, TVK & TWT Enabled on Binance Isolated Margin") == ["COCOS", "IQ", "PHA", "PROM", "TVK", "TWT"]
    assert f("Binance Margin to Delist ANC and MIR on Cross Margin and Isolated Margin") == ["ANC", "MIR"]
    assert f("Binance Will Add WTC(Walton) on August 27") == ["WTC"]
    assert f("Binance Futures Will List Coin-Margined Quarterly 0624 Futures Contracts") == []


def test_repair_symbols_only_fills_what_it_can_parse():
    rows = [{"id": "a", "ts": "2024-01-01T00:00:00Z", "kind": "perp_listing", "source": "binance", "symbols": [], "url": "u", "payload": {},
             "title": "Binance Futures Will Launch USDⓈ-M OXT Perpetual Contract With Up to 20x Leverage"},
            {"id": "b", "ts": "2024-01-02T00:00:00Z", "kind": "delisting", "source": "binance", "symbols": [], "url": "u", "payload": {},
             "title": "Notice of Removal of Spot Trading Pairs - 2024-07-06"}]
    out = []

    async def read(t, p):
        assert p["symbols"] == "eq.[]" and p["source"] == "eq.binance"
        return rows

    async def up(t, r, on_conflict=None):
        out.extend(r)
        return True

    n = asyncio.run(ev.repair_symbols(read, up))
    assert n == 1 and out[0]["id"] == "a" and out[0]["symbols"] == ["OXT"] and set(out[0]) == set(ev.WRITES_COLUMNS[ev.TABLE])


def test_monitoring_tag_notices_only_from_catalog_49():
    """11-07(S-753):Latest Binance News 里只留「监控标签」公告 —— 下架的前一步;通用解析器会漏代号,专用解析。"""
    assert ev.monitoring_tag("Binance Will Extend the Monitoring Tag to Include BICO & CVC on 2026-10-09") == ("monitoring_tag", ["BICO", "CVC"])
    assert ev.monitoring_tag("Binance Will Add Monitoring Tag on ALPACA, PDA, WAVES and WRX (2024-12-06)")[1] == ["ALPACA", "PDA", "WAVES", "WRX"]
    assert ev.monitoring_tag("Binance Will Remove the Monitoring Tag on ZEC (2025-01-10)") == ("monitoring_tag_removed", ["ZEC"])
    assert ev.monitoring_tag("Binance Will List FOO") == (None, [])
    payload = {"data": {"catalogs": [{"articles": [
        {"code": "a1", "title": "Binance Will Add Monitoring Tag on Tokens: AMP, BIFI, BOND (2024-08-13)", "releaseDate": 1723500000000},
        {"code": "a2", "title": "Binance Launches a New Earn Product", "releaseDate": 1723500000000}]}]}}
    rows = ev.parse_binance(payload, 49)
    assert len(rows) == 1 and rows[0]["kind"] == "monitoring_tag" and rows[0]["symbols"] == ["AMP", "BIFI", "BOND"]
    assert 49 in ev.BINANCE_CATALOGS


def test_notice_backfill_does_not_stop_on_a_page_without_tags(monkeypatch):
    """11-07 第一轮:catalog 49 第 2 页没有监控标签 ⇒ 解析出 0 行 ⇒ 被当成翻到底、标 done,回填永远停了。判断翻到底要看文章数。"""
    import src.api.store as store
    import src.data.style.header as hdr
    import src.data.venues.hl_spot as hl
    redis = {}

    async def read_all(t, params):
        return []

    async def ups(t, rows, on_conflict):
        return True

    async def rget(key):
        return redis.get(key), "hit" if key in redis else "miss"

    async def rset(key, data, ttl=7200):
        redis[key] = data
        return True

    class R:
        def __init__(self, body):
            self.status_code, self._b = 200, body

        def json(self):
            return self._b

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            if params["catalogId"] != 49:
                return R({"data": {"catalogs": [{"total": 0, "articles": []}]}})
            p = params["pageNo"]
            title = "Binance Will Add Monitoring Tag on FOO (2024-01-01)" if p == 4 else f"Binance News {p}"
            return R({"data": {"catalogs": [{"total": 2000, "articles": [{"id": p, "code": f"n{p}", "title": title, "releaseDate": 1704067200000}]}]}})
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", C)
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    monkeypatch.setattr(store, "redis_get_key_status", rget)
    monkeypatch.setattr(store, "redis_set_key", rset)
    monkeypatch.setattr(hl.HlSpotClient, "spot_meta", lambda self: {"tokens": []})
    r = asyncio.run(ev.run_once(NOW))
    assert r["kinds"].get("monitoring_tag") == 1, "第 4 页的标签被翻到"
    assert r["backfill"]["49"]["done"] is False and r["backfill"]["49"]["next_page"] == 2 + ev.BACKFILL_PAGES
    assert any(k.endswith(":v2") for k in redis), "catalog 49 换了新键(旧键在第一轮被误标 done)"


def test_monitoring_tag_titles_are_split_into_sentences():
    """11-08(T-308):一条标题几句话 —— 打上监控标签 / 移除监控标签 / 移除种子标签分开;v1 整行判「移除」漏了 43 次打上。
    FOR(ForTube)、HIGH(Highstreet)、D(原 DAR)是真代号,不当停用词。"""
    from src.data.market import events as ev
    t = ("Binance Will Extend the Monitoring Tag to Include STMX & TROY, Remove the Monitoring Tag for CVX & SUN, "
         "and Remove the Seed Tag for ARKM, BLUR, JTO & TIA on 2025-01-02")
    assert ev.monitoring_tag_changes(t) == {"add": ["STMX", "TROY"], "rem_mon": ["CVX", "SUN"], "rem_seed": ["ARKM", "BLUR", "JTO", "TIA"]}
    assert ev.monitoring_tag(t)[0] == "monitoring_tag", "有打上就是 monitoring_tag(v1 判成 removed)"
    assert ev.monitoring_tag_changes("Binance Will Remove the Monitoring Tag for ZEC and the Seed Tag for ENA, PYTH, TAO & W on 2025-07-09") == \
        {"add": [], "rem_mon": ["ZEC"], "rem_seed": ["ENA", "PYTH", "TAO", "W"]}, "Seed 沿用前面的 Remove"
    assert ev.monitoring_tag_changes("Binance Will Extend the Monitoring Tag to Include ACA, D, DATA & FLOW on 2026-01-02")["add"] == ["ACA", "D", "DATA", "FLOW"]
    assert "FOR" in ev.monitoring_tag_changes("Binance Will Extend the Monitoring Tag to Include EPX, FOR, UNFI, WAVES & WNXM on 2024-04-03")["add"]
    assert ev.monitoring_tag_changes("Binance Will Change the Monitoring Tag Inclusion Frequency to Monthly and Extend the Monitoring Tag to "
                                     "Include AERGO, ALPACA on 2025-03-04") == {"add": ["AERGO", "ALPACA"], "rem_mon": [], "rem_seed": []}


def test_retag_rewrites_only_changed_monitoring_rows():
    from src.data.market import events as ev
    t = "Binance Will Extend the Monitoring Tag to Include STMX & TROY, Remove the Monitoring Tag for CVX & SUN on 2025-01-02"
    rows = [{"id": "x", "ts": "2025-01-02T00:00:00Z", "kind": "monitoring_tag_removed", "source": "binance", "symbols": ["STMX", "TROY", "CVX", "SUN"],
             "title": t, "url": "u", "payload": {"catalog": 49}}]
    out = ev.retag_rows(rows)
    assert len(out) == 1 and out[0]["kind"] == "monitoring_tag" and out[0]["payload"]["tag_changes"]["rem_mon"] == ["CVX", "SUN"]
    assert out[0]["payload"]["catalog"] == 49, "payload 的其他键保留"
    assert ev.retag_rows(out) == [], "幂等"
