"""S-459:加密日线只有一个写入端(_cg_panel_loop → cg_pro_backfill)。collect_ohlcv 不再写 coingecko_pro_ohlc。"""
import asyncio

from src.api.routers import ohlcv


def test_collect_ohlcv_skips_crypto_and_writes_nothing_for_it(monkeypatch):
    monkeypatch.setattr(ohlcv, "_SB_URL", "http://x")
    monkeypatch.setattr(ohlcv, "_SB_KEY", "k")
    monkeypatch.setattr(ohlcv, "_universe", lambda: {"BTC": {"class": "Crypto", "coingecko": "bitcoin"}})
    written = []

    async def upsert(client, rows):
        written.extend(rows)
        return len(rows)

    async def boom(*a, **k):
        raise AssertionError("不该再走 CoinGecko 的采样点回退")
    monkeypatch.setattr(ohlcv, "_upsert_ohlcv", upsert)
    monkeypatch.setattr(ohlcv, "_fetch_cg_daily", boom)
    asyncio.run(ohlcv.collect_ohlcv(symbols=["BTC"], days=365))
    assert written == []


def test_a_sample_point_row_is_not_accepted_as_a_mapping_reference(monkeypatch):
    """S-459:用 O=H=L=C 的坏行当参照,会把正确的真 K 线判成映射错误而拒写 —— 坏数据永远修不掉。"""
    from src.data.market import cg_pro_backfill as bf
    import src.api.store as store

    class R:
        status_code = 200
        content = b"x"
        def __init__(self, row): self._row = row
        def json(self): return [self._row]

    async def flat(*a, **k):
        return R({"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0})
    monkeypatch.setattr(store, "_supabase_request_with_retry", flat)
    assert asyncio.run(bf._fetch_close("http://x", "k", "NEAR", "2026-09-20", "coingecko_pro_ohlc")) is None

    async def real(*a, **k):
        return R({"open": 5.0, "high": 5.4, "low": 4.9, "close": 5.2})
    monkeypatch.setattr(store, "_supabase_request_with_retry", real)
    assert asyncio.run(bf._fetch_close("http://x", "k", "NEAR", "2026-09-20", "coingecko_pro_ohlc")) == 5.2


def test_research_ohlcv_requires_a_single_source():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI(); app.include_router(ohlcv.router)
    c = TestClient(app)
    assert c.get("/api/v1/research/ohlcv/BTC").status_code == 422                       # 不给来源 ⇒ 拒绝
    assert c.get("/api/v1/research/ohlcv/BTC?source=hyperliquid").status_code == 422     # 死源 ⇒ 拒绝


def test_backfill_cg_pro_symbols_restricts_to_the_named_mappings(monkeypatch):
    """S-468:改了映射之后只重写那几个;不在映射表里的报出来,不猜。"""
    from src.data.market import cg_pro_backfill as bf
    monkeypatch.setattr(ohlcv, "_INTERNAL_TOKEN", "t")
    monkeypatch.setattr(ohlcv, "_SB_URL", "http://x")
    monkeypatch.setattr(ohlcv, "_SB_KEY", "k")

    class Resp:
        def __init__(self, data):
            self.status_code, self._d, self.content, self.text = 200, data, b"x", ""

        def json(self):
            return self._d

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return Resp([{"symbol": "ONE", "coin_id": "harmony"}, {"symbol": "BTC", "coin_id": "bitcoin"},
                         {"symbol": "AI", "coin_id": "sleepless-ai"}])

        async def get(self, *a, **k):
            return Resp([{"symbol": "BTC"}, {"symbol": "ONE"}, {"symbol": "AI"}])
    monkeypatch.setattr(ohlcv.httpx, "AsyncClient", Client)
    seen = []

    class Res:
        def as_payload(self):
            return {"status": "ok"}

    async def fake_backfill(pairs, **k):
        seen.extend(pairs)
        return Res()
    monkeypatch.setattr(bf, "backfill", fake_backfill)
    out = asyncio.run(ohlcv.backfill_cg_pro(dry_run=True, dest="supabase", days=400, panel="all",
                                            symbols="one, ai,NOPE", x_internal_token="t"))
    assert sorted(seen) == [("AI", "sleepless-ai"), ("ONE", "harmony")]
    assert out["skipped_no_coin_id"] == ["NOPE"]


def test_research_reads_for_lanes_are_registered():
    """T-045 / T-046 / T-047 的只读入口:lane 不持 Supabase key,研究数据走 Railway 读端点。"""
    paths = {r.path for r in ohlcv.router.routes}
    assert {"/api/v1/research/channels", "/api/v1/research/core-alpha", "/internal/research/book-navs"} <= paths
