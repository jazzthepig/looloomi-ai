"""轨道公司季度基本面(SEC EDGAR,11-02):frame 取最早披露、Q4 由年度减三季、股数不推 Q4、CIK 映射缺的记「读不到」、7 天内不重跑。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import issuer_fundamentals as fu  # noqa: E402

FACTS = {"facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [
        {"frame": "CY2024Q1", "val": 100, "end": "2024-03-31", "filed": "2024-05-02"},
        {"frame": "CY2024Q1", "val": 100, "end": "2024-03-31", "filed": "2025-05-08"},
        {"frame": "CY2024Q2", "val": 110, "end": "2024-06-30", "filed": "2024-08-01"},
        {"frame": "CY2024Q3", "val": 120, "end": "2024-09-30", "filed": "2024-10-30"},
        {"frame": "CY2024", "val": 500, "end": "2024-12-31", "filed": "2025-02-13"},
        {"start": "2024-01-01", "end": "2024-06-30", "val": 210, "filed": "2024-08-01"}]}},
    "NetIncomeLoss": {"units": {"USD": [{"frame": "CY2024Q3", "val": -5, "end": "2024-09-30", "filed": "2024-10-30"}]}},
    "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
        {"frame": "CY2024Q3", "val": 250, "end": "2024-09-30", "filed": "2024-10-30"},
        {"frame": "CY2024", "val": 255, "end": "2024-12-31", "filed": "2025-02-13"}]}}}}}


def test_quarterly_rows_are_point_in_time_and_q4_is_derived():
    rows = {r["period"]: r for r in fu.quarterly(FACTS, "COIN", 1679788)}
    assert rows["CY2024Q1"]["filed"] == "2024-05-02", "同一 frame 取最早披露(时点口径)"
    assert rows["CY2024Q4"]["revenue"] == 170 and rows["CY2024Q4"]["filed"] == "2025-02-13"
    assert rows["CY2024Q4"]["diluted_shares"] is None, "股数不是流量,不从年度推"
    assert rows["CY2024Q3"]["net_income"] == -5 and rows["CY2024Q3"]["diluted_shares"] == 250
    assert "CY2024" not in rows, "年度不单独成行"
    assert all(r["source"] == "sec_edgar" and r["cik"] == 1679788 for r in rows.values())


def test_cik_map_only_known_tickers():
    j = {"0": {"cik_str": 1679788, "ticker": "COIN", "title": "Coinbase"}, "1": {"cik_str": 1, "ticker": "AAPL", "title": "x"}}
    assert fu.cik_map(j, ["coin", "BLSH"]) == {"COIN": 1679788}


def test_run_once_skips_within_a_week_and_reports_missing_ciks(monkeypatch):
    import src.api.store as store
    up, redis = [], {}

    async def rget(key):
        return redis.get(key), "hit" if key in redis else "miss"

    async def rset(key, data, ttl=7200):
        redis[key] = data
        return True

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True

    class FakeResp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *a, **k):
            assert "User-Agent" in k.get("headers", {}), "SEC 要求 User-Agent"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            if url == fu.TICKERS_URL:
                return FakeResp(200, {"0": {"cik_str": 1679788, "ticker": "COIN", "title": "Coinbase"}})
            return FakeResp(200, FACTS)
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(store, "redis_get_key_status", rget)
    monkeypatch.setattr(store, "redis_set_key", rset)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    now = dt.datetime(2026, 11, 2, 16, 0, tzinfo=dt.timezone.utc)
    r = asyncio.run(fu.run_once(now))
    assert r["ok"] and r["written"] == 4 and r["companies"] == 1 and "CRCL" in r["missing_cik"] and "BLSH" in r["missing_cik"]
    assert all(x["symbol"] == "COIN" for x in up)
    r2 = asyncio.run(fu.run_once(now + dt.timedelta(days=1)))
    assert r2["status"] == "skipped"
    assert asyncio.run(fu.run_once(now + dt.timedelta(days=8)))["written"] == 4


def test_table_and_loop_are_wired():
    mig = (ROOT / "migrations/2026-11-02_issuer_fundamentals.sql").read_text(encoding="utf-8")
    for col in fu.WRITES_COLUMNS[fu.TABLE]:
        assert col in mig, col
    assert "_issuer_fundamentals_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
