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


def test_explicit_symbol_backfill_is_not_refused_by_the_full_panel_floor(monkeypatch):
    """S-439:首次真跑 24 个币被「活标的 ≥100」地板拒绝,0 行写入。显式传入的标的按比例定地板。"""
    import src.data.market.deep_panel_collector as dpc
    import src.api.store as store

    async def fake_fetch(sym, days):
        return sym, [{"symbol": sym, "trade_date": "2026-09-05", "close": 1.0, "source": "binance_hist"}], None
    written = []

    async def fake_upsert(table, rows, on_conflict=None):
        written.extend(rows); return True
    monkeypatch.setattr(dpc, "_fetch_one", fake_fetch)
    monkeypatch.setattr(store, "supabase_upsert_table", fake_upsert)
    monkeypatch.setattr(dpc, "_BATCH_PAUSE_S", 0, raising=False)
    monkeypatch.setattr(dpc, "assert_purpose_source", lambda *a, **k: None, raising=False)
    syms = [f"S{i}" for i in range(24)]
    r = asyncio.run(dpc.collect_deep_panel(days=400, symbols=syms))
    assert not r.get("refused") and r["ok"] and len(written) == 24


def test_explicit_backfill_still_refuses_when_most_symbols_fail(monkeypatch):
    import src.data.market.deep_panel_collector as dpc
    import src.api.store as store

    async def fake_fetch(sym, days):
        if sym in ("S0", "S1", "S2"):
            return sym, [{"symbol": sym, "trade_date": "2026-09-05", "close": 1.0}], None
        return sym, [], "http 451"
    async def fake_upsert(*a, **k):
        raise AssertionError("must not write")
    monkeypatch.setattr(dpc, "_fetch_one", fake_fetch)
    monkeypatch.setattr(store, "supabase_upsert_table", fake_upsert)
    monkeypatch.setattr(dpc, "_BATCH_PAUSE_S", 0, raising=False)
    r = asyncio.run(dpc.collect_deep_panel(days=400, symbols=[f"S{i}" for i in range(24)]))
    assert r.get("refused") is True
