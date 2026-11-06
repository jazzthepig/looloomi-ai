"""各场所日成交量(11-06):点按 ts 的 UTC 日期落(不看见未来)、同日取最后一个、分段 ≤ 31 天、往回走遇空即停、次数上限。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import exchange_volume as ev  # noqa: E402

MS = lambda y, m, d, h=0: int(dt.datetime(y, m, d, h, tzinfo=dt.timezone.utc).timestamp() * 1000)  # noqa: E731


def test_parse_dates_points_by_their_own_timestamp():
    rows = ev.parse([[MS(2026, 1, 1, 15), "100.5"], [MS(2026, 1, 1, 23), "120"], [MS(2026, 1, 2), "0"], ["x", "y"]], "gdax", "t")
    assert rows == [{"d": "2026-01-01", "exchange": "gdax", "kind": "spot", "volume_btc": 120.0, "fetched_at": "t"}]
    assert ev.parse([[MS(2026, 1, 1), 5]], "hyperliquid", "t")[0]["kind"] == "deriv"


def test_plan_segments():
    today = dt.date(2026, 11, 6)
    segs = ev.plan(None, None, today)
    assert segs[0] == (today - dt.timedelta(days=29), today, "back") and segs[-1][0] == ev.START
    assert all((b - a).days <= 30 for a, b, _ in segs)
    segs = ev.plan("2026-01-01", "2026-11-01", today)
    assert segs[0] == (dt.date(2026, 10, 30), today, "forward") and segs[1][1] == dt.date(2025, 12, 31)
    assert ev.plan("2021-01-01", "2026-11-05", today) == [(dt.date(2026, 11, 3), today, "forward")]


def test_run_once_stops_backwards_at_first_empty_and_respects_budget(monkeypatch):
    calls = []

    async def fetch(ex, a, b):
        calls.append((ex, a))
        return [[MS(b.year, b.month, b.day), 10]] if a >= dt.date(2026, 9, 1) else []

    async def bounds(ex):
        return None, None

    written = []

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return True

    monkeypatch.setattr(ev, "MAX_CALLS", 7)
    r = asyncio.run(ev.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), fetch=fetch, bounds=bounds, upsert=upsert))
    assert r["calls"] == 7 and r["backlog"] and r["ok"]
    assert [c[0] for c in calls[:3]] == ["binance"] * 3 and calls[3][0] == "gdax", "空段之后不再往更早走"
    assert set(written[0]) == set(ev.WRITES_COLUMNS[ev.TABLE])


def test_wiring():
    assert "async def _exchange_volume_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_exchange_volume_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in ev.WRITES_COLUMNS[ev.TABLE])
