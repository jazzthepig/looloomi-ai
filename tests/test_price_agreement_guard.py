"""T-044b(S-484):近 45 天、每天每源一行、能抓住整体后移一天。"""
import asyncio
from datetime import date, timedelta

import numpy as np
import pytest

from src.data.market import price_agreement_guard as g


def _series(n, seed=0):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(0.03 * rng.standard_normal(n)))


def test_shifted_source_is_flagged_and_summarized_one_row_per_source(monkeypatch):
    today = date.today()
    days = [(today - timedelta(days=44 - i)).isoformat() for i in range(45)]
    px = _series(45)
    base = {"BTC": dict(zip(days, px))}
    shifted = {"BTC": dict(zip(days[1:], px[:-1]))}          # 每天写的是前一天的收盘(S-436 的形状)
    same = {"BTC": dict(zip(days, px * 1.001))}
    data = {"binance_hist": base, "coingecko_pro_ohlc": shifted, "asset_mcap_daily": same, "hyperliquid": {}}

    async def fake_panel(source, syms, start):
        assert start == (today - timedelta(days=g.WINDOW_DAYS)).isoformat()
        return data[source]
    written = []

    async def fake_upsert(table, rows, on_conflict):
        written.append((table, rows, on_conflict))

        class R:
            ok = True
        return R()
    import src.api.store as store
    monkeypatch.setattr(g, "_panel", fake_panel)
    monkeypatch.setattr(store, "supabase_upsert_table", fake_upsert)
    monkeypatch.setattr(g, "symbols", lambda: ["BTC"])
    r = asyncio.run(g.run_once())
    assert r["ok"] and written[0][0] == g.TABLE and written[0][2] == "d,source"
    rows = {x["source"]: x for x in written[0][1]}
    assert set(rows) == set(g.CANDIDATES)
    assert rows["coingecko_pro_ohlc"]["by_kind"].get("shift_by_1_day", 0) >= 1 and rows["coingecko_pro_ohlc"]["n_error"] >= 1
    assert rows["asset_mcap_daily"]["n_findings"] == 0 and rows["hyperliquid"]["n_symbols"] == 0
    assert r["n_error"] >= 1


def test_no_baseline_refuses(monkeypatch):
    async def empty(source, syms, start):
        return {}
    monkeypatch.setattr(g, "_panel", empty)
    r = asyncio.run(g.run_once())
    assert not r["ok"] and "binance_hist" in r["reason"]
