"""行情快照(S-908,2026-11-23):取回来的全宇宙行情落一份;请求路径先读表。

Jazz 11-23:「读取后是否落表」「研究时候是否直接走了 api 而不是走我们数据库」。
量出来的:`data_layer` 里打 CoinGecko 的 25 个函数没有一个自己写库;CMC 的回包一份都没落过。
"""
import asyncio
import datetime as dt
from pathlib import Path

import pytest

import src.data.market.market_snapshot as ms

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 23, 13, 0, 5, tzinfo=dt.timezone.utc)


class _Read:
    def __init__(self, rows, reason="ok"):
        self.rows, self.reason = rows, reason

    @property
    def ok(self):
        return self.rows is not None


class _Res:
    def __init__(self, ok, why=None):
        self.ok, self.why = ok, why


# ── 身份核对:CMC 按代码查币会查错 ─────────────────────────────────────────────

def test_same_name_and_sane_price_is_ours():
    assert ms.identity_of("Bitcoin", "Bitcoin", 61000, 60500, True) == "name"
    assert ms.identity_of("Sky (prev. Maker)", "Sky", 0.061, 0.058, False) == "name"
    assert ms.identity_of("StarkNet", "Starknet", 0.11, 0.12, True) == "name"


def test_a_different_coin_with_our_ticker_is_refused():
    """代码一样、名字是另一个词、价也对不上 ⇒ 不是我们的那个。"""
    assert ms.identity_of("Sky (prev. Maker)", "Skycoin", 0.9, 0.058, True) is None
    assert ms.identity_of("Sui", "Suiswap", 0.0004, 1.9, True) is None


def test_name_matches_but_price_is_far_off_is_refused():
    """名字对得上也不够:同名的另一条链 / 包装币,价差出 0.5–2 倍 ⇒ 拒。"""
    assert ms.identity_of("Ondo Finance", "Ondo", 9.0, 0.6, True) is None
    assert ms.identity_of("Ondo Finance", "Ondo", 0.2, 0.6, False) is None


def test_renamed_coin_passes_only_on_a_venue_price():
    """POL:我们叫 Polygon,对方叫「POL (prev. MATIC)」—— 名字对不上,只有币安最近收盘对得上才认。"""
    assert ms.identity_of("Polygon", "POL (prev. MATIC)", 0.201, 0.195, True) == "price"
    assert ms.identity_of("Polygon", "POL (prev. MATIC)", 0.26, 0.195, True) is None      # 差 33%
    assert ms.identity_of("Polygon", "POL (prev. MATIC)", 0.201, 0.195, False) is None    # 旧日点不够格
    assert ms.identity_of("Polygon", "POL (prev. MATIC)", 0.201, None, False) is None     # 没参考价 ⇒ 没法确认


def test_name_alone_is_enough_when_there_is_no_reference():
    assert ms.identity_of("Hyperliquid", "Hyperliquid", 31.0, None, False) == "name"


# ── CMC 回包 → 行 ─────────────────────────────────────────────────────────────

def _quotes():
    return {"BTC": {"id": 1, "name": "Bitcoin", "price": 61265.0, "market_cap": 1.22e12, "volume_24h": 3.1e10,
                    "percent_change_24h": -1.2, "percent_change_7d": -6.0, "circulating_supply": 19_950_000,
                    "total_supply": 19_950_000, "max_supply": 21_000_000, "last_updated": "2026-11-23T12:59:00.000Z"},
            "HYPE": {"id": 32196, "name": "Hyperliquid", "price": 31.0, "market_cap": 1.0e10, "volume_24h": 2.0e8,
                     "circulating_supply": 333_000_000, "total_supply": 999_000_000, "max_supply": None},
            "SKY": {"id": 99, "name": "Skycoin", "price": 0.9, "market_cap": 1.0e7}}


GLOB = {"total_market_cap_usd": 2.09e12, "total_volume_24h_usd": 9.0e10,
        "total_market_cap_change_24h_pct": -1.5, "btc_dominance_pct": 58.85}
NAMES = {"BTC": "Bitcoin", "HYPE": "Hyperliquid", "SKY": "Sky (prev. Maker)", "ARB": "Arbitrum"}
REFS = {"BTC": (60900.0, True), "SKY": (0.058, False)}


def test_rows_carry_supply_and_missing_stays_missing():
    rows, rejected = ms.cmc_rows(_quotes(), GLOB, NOW, NAMES, REFS)
    by = {r["symbol"]: r for r in rows}
    assert set(by) == {"BTC", "HYPE", ms.GLOBAL}
    assert by["BTC"]["max_supply"] == 21_000_000 and by["BTC"]["total_supply"] == 19_950_000
    assert by["BTC"]["source_ts"].startswith("2026-11-23T12:59:00")
    assert by["HYPE"]["max_supply"] is None, "没有上限 = 缺,不是 0"
    assert by["HYPE"]["pct_24h"] is None and by["HYPE"]["source_ts"] is None
    assert by["HYPE"]["identity"] == "name" and by["BTC"]["identity"] == "name"
    assert all(set(r) == set(ms.WRITES_COLUMNS[ms.TABLE]) for r in rows), "每行都是同一组列"
    assert all(r["source"] == ms.SOURCE_CMC and r["ts"] == NOW.isoformat() and r["d"] == "2026-11-23" for r in rows)


def test_rejected_names_are_named_with_the_reason():
    _, rejected = ms.cmc_rows(_quotes(), GLOB, NOW, NAMES, REFS)
    txt = ";".join(rejected)
    assert "SKY" in txt and "Skycoin" in txt and "身份对不上" in txt
    assert "ARB:没有报价" in txt


def test_global_row_holds_dominance_and_total():
    rows, _ = ms.cmc_rows({}, GLOB, NOW, {}, {})
    assert len(rows) == 1
    g = rows[0]
    assert g["symbol"] == ms.GLOBAL and g["btc_dominance"] == 58.85 and g["market_cap"] == 2.09e12 and g["price"] is None


def test_no_global_is_said_not_written_as_zero():
    rows, rejected = ms.cmc_rows(_quotes(), {}, NOW, NAMES, REFS)
    assert all(r["symbol"] != ms.GLOBAL for r in rows) and any(x.startswith(ms.GLOBAL) for x in rejected)


def test_date_is_the_utc_day_whatever_zone_the_caller_is_in():
    """规则 5c:Mac 在 JST,15:00 UTC 之后本地日期已经是明天。"""
    jst = dt.timezone(dt.timedelta(hours=9))
    rows, _ = ms.cmc_rows({}, GLOB, dt.datetime(2026, 11, 24, 2, 0, tzinfo=jst), {}, {})
    assert rows[0]["d"] == "2026-11-23" and rows[0]["ts"].startswith("2026-11-23T17:00:00")


def test_cg_rows_from_the_engine_shape():
    markets = {"bitcoin": {"name": "Bitcoin", "price": 61000, "market_cap": 1.2e12, "volume_24h": 3e10,
                           "circulating_supply": 19.95e6, "total_supply": 19.95e6, "max_supply": 21e6,
                           "change_24h": -1.0, "change_7d": -5.0, "last_updated": "2026-12-02T00:10:00Z"},
               "unknown-coin": {"price": 1.0}, "sky": {"price": 0}}
    rows = ms.cg_rows(markets, NOW, {"bitcoin": "BTC", "sky": "SKY"})
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "BTC" and r["vendor_id"] == "bitcoin" and r["source"] == ms.SOURCE_CG and r["identity"] == "id"
    assert r["max_supply"] == 21e6 and r["pct_7d"] == -5.0 and set(r) == set(ms.WRITES_COLUMNS[ms.TABLE])


# ── 一轮 ──────────────────────────────────────────────────────────────────────

def _wire(monkeypatch, last_ts=None, read_ok=True, admit=(True, ""), quotes=None, glob=GLOB, insert_ok=True):
    import src.api.store as store
    import src.data.market.cmc_provider as cmc
    import src.data.vector.market_state_writer as msw
    calls = {"cmc": 0, "rows": None}

    async def sb_get(table, params):
        if not read_ok:
            return _Read(None, "HTTP 401: nope")
        return _Read([{"ts": last_ts}] if last_ts else [])

    async def fake_admit():
        return admit

    async def fake_quotes(symbols):
        calls["cmc"] += 1
        return _quotes() if quotes is None else quotes

    async def fake_glob():
        calls["cmc"] += 1
        return glob

    async def fake_refs(symbols, sym2cg, today=None):
        return {"BTC": (60900.0, True), "SKY": (0.058, False)}

    async def fake_insert(table, rows):
        calls["rows"] = rows
        return _Res(insert_ok, None if insert_ok else "HTTP 400: bad")

    monkeypatch.setattr(msw, "_sb_get", sb_get)
    monkeypatch.setattr(cmc, "admit", fake_admit)
    monkeypatch.setattr(cmc, "cmc_quotes", fake_quotes)
    monkeypatch.setattr(cmc, "cmc_global_metrics", fake_glob)
    monkeypatch.setattr(ms, "ref_prices", fake_refs)
    monkeypatch.setattr(store, "supabase_insert_table", fake_insert)
    return calls


def test_a_round_writes_and_names_what_it_left_out(monkeypatch):
    calls = _wire(monkeypatch)
    r = asyncio.run(ms.run_once(NOW))
    assert r["ok"] and r["written"] == len(calls["rows"]) == 3 and r["btc_dominance"] == 58.85
    assert r["by_identity"] == {"name": 2, "price": 0, "global": 1}
    assert any("SKY" in x for x in r["rejected"]) and "SKY" in r["why"]
    assert len(r["rejected"]) == 23, "25 个名字里只给了 3 个报价、其中 1 个身份不对 ⇒ 23 个没落,一个不少地点名"


def test_fresh_snapshot_costs_no_cmc_call(monkeypatch):
    calls = _wire(monkeypatch, last_ts=(NOW - dt.timedelta(minutes=12)).isoformat())
    r = asyncio.run(ms.run_once(NOW))
    assert r["ok"] and r["status"] == "already_done" and r["written"] == 0 and calls["cmc"] == 0


def test_due_snapshot_is_taken(monkeypatch):
    calls = _wire(monkeypatch, last_ts=(NOW - dt.timedelta(minutes=30)).isoformat())
    assert asyncio.run(ms.run_once(NOW))["written"] == 3 and calls["cmc"] == 2


def test_unreadable_table_is_a_fault_not_a_first_run(monkeypatch):
    """读不到 ≠ 没有上一份:读不到就去取,每 10 分钟一轮会把 CMC 的额度打光。"""
    calls = _wire(monkeypatch, read_ok=False)
    r = asyncio.run(ms.run_once(NOW))
    assert not r["ok"] and "401" in r["why"] and calls["cmc"] == 0


def test_cmc_unavailable_is_a_refusal_with_its_reason(monkeypatch):
    calls = _wire(monkeypatch, admit=(False, "cmc_budget_exhausted:120/120"))
    r = asyncio.run(ms.run_once(NOW))
    assert not r["ok"] and r["refused"] and "cmc_budget_exhausted" in r["why"] and calls["cmc"] == 0 and calls["rows"] is None


def test_empty_cmc_answers_write_nothing(monkeypatch):
    calls = _wire(monkeypatch, quotes={}, glob={})
    r = asyncio.run(ms.run_once(NOW))
    assert not r["ok"] and r["refused"] and calls["rows"] is None


def test_failed_insert_is_reported(monkeypatch):
    _wire(monkeypatch, insert_ok=False)
    r = asyncio.run(ms.run_once(NOW))
    assert not r["ok"] and r["written"] == 0 and "400" in r["why"]


# ── 读 ────────────────────────────────────────────────────────────────────────

def _wire_read(monkeypatch, ts):
    import src.data.style.header as header
    import src.data.vector.market_state_writer as msw
    rows, _ = ms.cmc_rows(_quotes(), GLOB, ts, NAMES, REFS)
    n = {"reads": 0}

    async def sb_get(table, params):
        n["reads"] += 1
        return _Read([{"ts": ts.isoformat()}])

    async def read_all(table, params):
        assert params["ts"] == f"eq.{ts.isoformat()}" and params["source"] == f"eq.{ms.SOURCE_CMC}"
        return rows

    monkeypatch.setattr(msw, "_sb_get", sb_get)
    monkeypatch.setattr(header, "_read_all", read_all)
    ms._latest_cache.update({"at": 0.0, "val": None})
    return n


def test_latest_gives_a_fresh_snapshot_and_refuses_a_stale_one(monkeypatch):
    _wire_read(monkeypatch, NOW - dt.timedelta(minutes=40))
    snap = asyncio.run(ms.latest(now=NOW))
    assert snap and snap["age_s"] == 2400 and snap["global"]["btc_dominance"] == 58.85 and set(snap["rows"]) == {"BTC", "HYPE"}
    _wire_read(monkeypatch, NOW - dt.timedelta(minutes=91))
    assert asyncio.run(ms.latest(now=NOW)) is None, "太旧的不给 —— 调用方自己回落,不拿旧数冒充"


def test_latest_is_cached_in_process(monkeypatch):
    n = _wire_read(monkeypatch, NOW - dt.timedelta(minutes=5))
    asyncio.run(ms.latest(now=NOW))
    asyncio.run(ms.latest(now=NOW))
    assert n["reads"] == 1


def test_shaped_like_the_live_cmc_functions(monkeypatch):
    _wire_read(monkeypatch, NOW - dt.timedelta(minutes=5))
    sh = ms.cmc_shaped(asyncio.run(ms.latest(now=NOW)))
    assert sh["global"]["btc_dominance_pct"] == 58.85 and sh["global"]["total_market_cap_usd"] == 2.09e12
    assert sh["quotes"]["BTC"]["price"] == 61265.0 and sh["quotes"]["BTC"]["percent_change_7d"] == -6.0
    assert sh["as_of"] == (NOW - dt.timedelta(minutes=5)).isoformat()
    assert ms.cmc_shaped(None) == {"global": {}, "quotes": {}, "as_of": None}


# ── 请求路径先读表 ────────────────────────────────────────────────────────────

def test_global_fallback_reads_the_table_before_spending_a_call(monkeypatch):
    import src.data.market.cmc_provider as cmc
    import src.data.market.data_layer as dl
    _wire_read(monkeypatch, dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5))

    async def boom():
        raise AssertionError("表里有新快照,不该再打 CMC")

    monkeypatch.setattr(cmc, "cmc_global_metrics", boom)
    out = asyncio.run(dl._cmc_global_fallback())
    assert out["source"] == "coinmarketcap" and out["btc_dominance"] == 58.85 and out["data_as_of"]
    assert out["eth_dominance"] is None


def test_global_fallback_goes_live_when_the_table_has_nothing_fresh(monkeypatch):
    import src.data.market.cmc_provider as cmc
    import src.data.market.data_layer as dl
    _wire_read(monkeypatch, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3))

    async def live():
        return {"btc_dominance_pct": 60.0, "total_market_cap_usd": 2.0e12}

    monkeypatch.setattr(cmc, "cmc_global_metrics", live)
    out = asyncio.run(dl._cmc_global_fallback())
    assert out["btc_dominance"] == 60.0 and out["data_as_of"] is None


# ── CoinGecko 那一半:取到就落 ────────────────────────────────────────────────

def test_cg_markets_are_persisted_once_per_interval_and_never_raise(monkeypatch):
    import src.api.store as store
    got = []

    async def fake_insert(table, rows):
        got.append((table, len(rows)))
        return _Res(True)

    monkeypatch.setattr(store, "supabase_insert_table", fake_insert)
    monkeypatch.setattr(ms, "_cg_last_persist", 0.0)
    markets = {"bitcoin": {"name": "Bitcoin", "price": 61000, "market_cap": 1.2e12}}
    r1 = asyncio.run(ms.persist_cg_markets(markets, NOW))
    r2 = asyncio.run(ms.persist_cg_markets(markets, NOW))
    assert r1["written"] == 1 and r2["written"] == 0 and "还新" in r2["why"] and got == [(ms.TABLE, 1)]

    async def explode(table, rows):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "supabase_insert_table", explode)
    monkeypatch.setattr(ms, "_cg_last_persist", 0.0)
    r3 = asyncio.run(ms.persist_cg_markets(markets, NOW))
    assert r3["ok"] is False and "RuntimeError" in r3["why"]
    assert asyncio.run(ms.persist_cg_markets({}, NOW))["written"] == 0


# ── 接线 ──────────────────────────────────────────────────────────────────────

def test_wiring():
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "async def _market_snapshot_loop" in main and "_start_market_snapshot_loop" in main
    mig = (ROOT / "migrations/2026-11-23_market_snapshot.sql").read_text(encoding="utf-8")
    for col in ms.WRITES_COLUMNS[ms.TABLE]:
        assert col in mig, col
    assert "enable row level security" in mig and "revoke all" in mig and "market_snapshot_guard" in mig
    assert "create policy lane_read" in mig and "for select to anon" in mig, "研究要读得到(这张表就是为了不再打 API)"
    assert "insert" not in mig.split("revoke all")[1].lower(), "写只有服务端 key"
    from src.api.routers import lane_read as lr
    assert ms.TABLE in lr.ALLOW
    for src in (ms.SOURCE_CMC, ms.SOURCE_CG):
        assert f"'{src}'" in mig, src
    cis = (ROOT / "src/data/cis/cis_provider.py").read_text(encoding="utf-8")
    seg = cis[cis.index("async def fetch_cg_markets"):cis.index("async def fetch_defillama_tvl")]
    assert "persist_cg_markets(result)" in seg, "盘中引擎取到 /coins/markets 就得落一份"
    dl = (ROOT / "src/data/market/data_layer.py").read_text(encoding="utf-8")
    pulse = dl[dl.index("async def get_macro_pulse"):]
    assert pulse.index("cmc_latest_shaped") < pulse.index("cmc_global_metrics() or {}"), "宏观脉搏先读表,再活取"


def test_cmc_supply_fields_come_through():
    import src.data.market.cmc_provider as cmc
    src = (ROOT / "src/data/market/cmc_provider.py").read_text(encoding="utf-8")
    for k in ("circulating_supply", "total_supply", "max_supply"):
        assert f'"{k}": row.get("{k}")' in src, k
    per_day = 2 * 86400 // ms.INTERVAL_S
    assert per_day + 20 <= cmc.DEFAULT_DAILY_BUDGET, "快照一天的笔数 + 给请求路径留的活回落,要装得进日预算"
    assert cmc.DEFAULT_DAILY_BUDGET * 31 <= 5000, "一个月不超过免费档月额度的一半"


# ── CMC 请求本身(MockTransport,不出网)────────────────────────────────────────

def _cmc_mock(monkeypatch, handler):
    import httpx
    import src.data.market.cmc_provider as cmc
    monkeypatch.setattr(cmc, "_UPSTASH_URL", "")
    monkeypatch.setattr(cmc, "_local_used", {})
    monkeypatch.setattr(cmc, "_local_blocked_until", 0.0)
    monkeypatch.setenv("CMC_API_KEY", "test-cmc-key")
    monkeypatch.delenv("CMC_DAILY_BUDGET", raising=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(cmc, "_get_http", lambda: client)
    cmc.LAST.clear()
    return cmc


def test_one_unknown_ticker_does_not_fail_the_whole_batch(monkeypatch):
    """官方文档:一批里有一个代码不认识,缺省整批 400;`skip_invalid=true` ⇒ 认识的照回。"""
    import httpx
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"data": {"BTC": {
            "id": 1, "name": "Bitcoin", "symbol": "BTC", "circulating_supply": 19950000, "total_supply": 19950000,
            "max_supply": 21000000, "last_updated": "2026-11-23T14:00:00.000Z",
            "quote": {"USD": {"price": 61000.0, "market_cap": 1.2e12, "volume_24h": 3e10,
                              "percent_change_24h": -1.0, "percent_change_7d": -5.0}}}}})

    cmc = _cmc_mock(monkeypatch, handler)
    out = asyncio.run(cmc.cmc_quotes(["BTC", "NOPE"]))
    assert seen[0]["skip_invalid"] == "true" and seen[0]["symbol"] == "BTC,NOPE"
    assert set(out) == {"BTC"} and out["BTC"]["max_supply"] == 21000000 and out["BTC"]["total_supply"] == 19950000


def test_a_failed_cmc_call_leaves_its_reason(monkeypatch):
    import httpx

    def handler(request):
        return httpx.Response(400, json={"status": {"error_code": 400, "error_message": "Invalid value for symbol"}})

    cmc = _cmc_mock(monkeypatch, handler)
    assert asyncio.run(cmc.cmc_quotes(["BTC"])) == {}
    assert "HTTP 400" in cmc.LAST["why"] and cmc.LAST["path"] == "/cryptocurrency/quotes/latest"


def test_the_loop_never_says_skipped_and_its_refusal_has_a_rule():
    """`skipped` 在这个仓库里的意思是「等上游」(S-862)。这条循环不等谁:上一份还新 = `already_done`(算成);
    CMC 不可用 = 拒绝并带原因,指挥台上有它的规则(等什么、谁清、多久算故障)。"""
    import importlib.util
    assert '"status": "skipped"' not in (ROOT / "src/data/market/market_snapshot.py").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("ops_console", ROOT / "scripts" / "ops_console.py")
    oc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc)
    pol = oc.REFUSAL_POLICY[ms.LOOP_NAME]
    assert "S-908" in pol["reason"] and pol["stale_after_days"] == 1 and pol["escalate_after_n_refusals"] <= 18
