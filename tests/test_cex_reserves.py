"""交易所储备快照(11-06):解析、一次请求、接线。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import cex_reserves as cx  # noqa: E402

PAYLOAD = {"cexs": [{"name": "Binance", "cleanAssetsTvl": 1.27e11, "currentTvl": 1.4e11, "inflows_1w": -5.0e9, "oi": 3.2e10, "leverage": 0.25},
                    {"name": "Empty", "cleanAssetsTvl": None}, {"name": None, "cleanAssetsTvl": 5}]}


def test_parse():
    rows = cx.parse(PAYLOAD, "2026-11-06", "t")
    assert len(rows) == 1 and rows[0]["exchange"] == "Binance" and rows[0]["inflow_1w_usd"] == -5.0e9 and rows[0]["inflow_24h_usd"] is None
    assert set(rows[0]) == set(cx.WRITES_COLUMNS[cx.TABLE])


def test_run_once_one_request(monkeypatch):
    calls, written = [], []

    def get(u):
        calls.append(u)
        return PAYLOAD

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    import src.api.store as store
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    r = asyncio.run(cx.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), get=get))
    assert r["ok"] and len(calls) == 1 and len(written) == 1


def test_wiring():
    assert "async def _cex_reserves_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_cex_reserves_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in cx.WRITES_COLUMNS[cx.TABLE])
