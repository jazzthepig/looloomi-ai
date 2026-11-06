"""稳定币按链(11-06):图表 / 快照解析、只留登记的链、表空才回填(≤ 6 次)、当天快照覆盖图表点。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import stablecoin_chains as sc  # noqa: E402

NOW = dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc)
TS = int(dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc).timestamp())


def test_parsers():
    assert sc.chart_rows([{"date": TS, "totalCirculatingUSD": {"peggedUSD": 5.0}}, {"date": "x"}], "Tron")[0]["chain"] == "Tron"
    snap = sc.snapshot_rows([{"name": "Tron", "totalCirculatingUSD": {"peggedUSD": 9e10}}, {"name": "Monad", "totalCirculatingUSD": {"peggedUSD": 1}}], "2026-11-06")
    assert [r["chain"] for r in snap] == ["Tron"]


def test_backfill_only_when_empty_and_snapshot_wins_same_day():
    calls, out = [], []

    def get(url):
        calls.append(url)
        if url == sc.SNAPSHOT_API:
            return [{"name": c, "totalCirculatingUSD": {"peggedUSD": 2.0}} for c in sc.CHAINS]
        return [{"date": TS, "totalCirculatingUSD": {"peggedUSD": 1.0}}]

    async def up(t, rows, on_conflict=None):
        out.extend(rows)
        return True

    async def empty(t, p):
        return []

    r = asyncio.run(sc.run_once(now=NOW, get=get, read=empty, upsert=up))
    assert r["ok"] and len(calls) == len(sc.CHAINS) + 1 and len(out) == len(sc.CHAINS)
    assert all(x["circulating_usd"] == 2.0 for x in out), "当天快照覆盖图表点"
    calls.clear()

    async def full(t, p):
        return [{"chain": "Tron"}]

    asyncio.run(sc.run_once(now=NOW, get=get, read=full, upsert=up))
    assert calls == [sc.SNAPSHOT_API], "表里有数就只取快照(一次请求)"


def test_wiring():
    assert "async def _stablecoin_chains_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_stablecoin_chain_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in sc.WRITES_COLUMNS[sc.TABLE])
