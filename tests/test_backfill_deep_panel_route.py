"""T-030 — binance_hist 补洞端点:同一个写入端、默认 dry_run、后台执行。"""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import ohlcv


def _client(monkeypatch, calls):
    monkeypatch.setattr(ohlcv, "_INTERNAL_TOKEN", "t0k")

    async def fake_collect(days=None, symbols=None):
        calls.append((days, list(symbols or [])))
        return {"status": "ok", "symbols_ok": len(symbols or []), "symbols_failed": 0, "rows_written": 1}

    import src.data.market.deep_panel_collector as dpc
    monkeypatch.setattr(dpc, "collect_deep_panel", fake_collect)
    app = FastAPI(); app.include_router(ohlcv.router)
    return TestClient(app)


def test_requires_token(monkeypatch):
    c = _client(monkeypatch, [])
    assert c.post("/internal/backfill-deep-panel").status_code == 401


def test_dry_run_is_the_default_and_fetches_nothing(monkeypatch):
    calls = []
    c = _client(monkeypatch, calls)
    r = c.post("/internal/backfill-deep-panel", headers={"X-Internal-Token": "t0k"}).json()
    assert r["dry_run"] is True and r["n_symbols"] == 24 and r["source"] == "binance_hist"
    assert calls == []


def test_real_run_uses_the_same_collector(monkeypatch):
    calls = []
    c = _client(monkeypatch, calls)
    r = c.post("/internal/backfill-deep-panel?dry_run=false&days=400&symbols=btc,eth",
               headers={"X-Internal-Token": "t0k"}).json()
    assert r["started"] is True and r["symbols"] == ["BTC", "ETH"]
    # 后台任务在 TestClient 的事件循环里跑完
    assert calls == [(400, ["BTC", "ETH"])]
