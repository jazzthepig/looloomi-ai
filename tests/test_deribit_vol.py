"""Deribit DVOL(11-03):解析按 UTC 日、分块回填、一年分位、增量模式、错误汇总。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import deribit_vol as dv  # noqa: E402

PAYLOAD = {"result": {"data": [[1761955200000, 43.31, 43.82, 42.73, 43.49], [1762041600000, 43.49, 44.9, 43.45, 44.12],
                               [1762041600001, 43.49, 44.9, 43.45, 44.20], ["x", 1, 2, 3, 4]]}}


def test_parse_dedupes_per_utc_day_and_skips_junk():
    rows = dv.parse(PAYLOAD, "BTC")
    assert [r["d"] for r in rows] == ["2025-11-01", "2025-11-02"] and rows[1]["dvol_close"] == 44.20
    assert rows[0]["currency"] == "BTC" and rows[0]["source"] == "deribit"


def test_chunks_and_percentile():
    cs = dv.chunks(dt.date(2021, 3, 1), dt.date(2022, 6, 1), 365)
    assert cs[0] == (dt.date(2021, 3, 1), dt.date(2022, 2, 28)) and cs[-1][1] == dt.date(2022, 6, 1) and len(cs) == 2
    assert dv.pct_rank([40, 50, 60, 70], 55) == 0.5 and dv.pct_rank([], 1) is None and dv.pct_rank([1], None) is None


def test_run_once_backfills_then_only_recent(monkeypatch):
    import src.api.store as store
    up, redis, calls = [], {}, []

    async def rget(key):
        return redis.get(key), "hit" if key in redis else "miss"

    async def rset(key, data, ttl=7200):
        redis[key] = data
        return True

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True

    class FakeResp:
        status_code = 200

        def json(self):
            return PAYLOAD

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            calls.append((params["currency"], params["start_timestamp"]))
            return FakeResp()
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(store, "redis_get_key_status", rget)
    monkeypatch.setattr(store, "redis_set_key", rset)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    async def nosleep(s):
        return None
    monkeypatch.setattr(asyncio, "sleep", nosleep)
    now = dt.datetime(2026, 11, 3, 16, 0, tzinfo=dt.timezone.utc)
    r = asyncio.run(dv.run_once(now))
    assert r["ok"] and r["backfill"] and len(calls) == 2 * len(dv.chunks(dv.START, now.date())) and redis[dv.RAN_KEY]["done"]
    calls.clear()
    r2 = asyncio.run(dv.run_once(now))
    assert not r2["backfill"] and len(calls) == 2, "回填过 ⇒ 每币只补最近 10 天"


def test_wiring():
    assert "_deribit_vol_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-03_deriv_vol_daily.sql").read_text(encoding="utf-8")
    for col in dv.WRITES_COLUMNS[dv.TABLE]:
        assert col in mig, col
    assert 'inputs["dvol_btc"]' in (ROOT / "src/data/execution/exposure_decision.py").read_text(encoding="utf-8")
