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
