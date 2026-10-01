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
