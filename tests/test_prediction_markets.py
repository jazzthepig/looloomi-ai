"""预测市场先验(11-06):解析 Gamma /events、去重、只用批量端点、接线。"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import prediction_markets as pm  # noqa: E402

EV = [{"slug": "btc-nov", "title": "Bitcoin above ___ on November 30?", "markets": [
    {"id": "1", "question": "BTC above 80k?", "groupItemTitle": "80,000", "outcomePrices": json.dumps(["0.42", "0.58"]), "volume24hr": "1000", "liquidityNum": 50, "endDate": "2026-11-30T17:00:00Z", "active": True, "closed": False},
    {"id": "2", "question": "closed one", "outcomePrices": json.dumps(["1", "0"]), "closed": True},
    {"id": "3", "question": "bad price", "outcomePrices": json.dumps(["1.7", "0"])},
    {"id": "4", "question": "no price", "outcomePrices": "not json"}]}]


def test_parse_keeps_open_priced_markets_only():
    rows = pm.parse_events(EV, "crypto", "2026-11-06", "2026-11-06T01:00:00+00:00")
    assert [r["market_id"] for r in rows] == ["1"]
    r = rows[0]
    assert r["p_yes"] == 0.42 and r["item"] == "80,000" and r["tag"] == "crypto" and r["venue"] == "polymarket" and r["volume_24h"] == 1000.0
    assert pm.parse_events({"error": "x"}, "crypto", "d", "t") == []


def test_run_once_one_request_per_tag_and_dedups(monkeypatch):
    urls, written = [], []

    def get(u):
        urls.append(u)
        return EV

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    import src.api.store as store
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    r = asyncio.run(pm.run_once(now=dt.datetime(2026, 11, 6, 1, tzinfo=dt.timezone.utc), get=get))
    assert len(urls) == len(pm.TAGS) and all("/events?" in u for u in urls), "批量端点,每个标签一次"
    assert r["ok"] and r["written"] == 1 and len(written) == 1, "同一个市场挂多个标签只留一行"


def test_wiring():
    assert "async def _prediction_markets_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/prediction-markets"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_prediction_markets.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in pm.WRITES_COLUMNS[pm.TABLE])
