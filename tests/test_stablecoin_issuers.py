"""稳定币按发行方(11-06):解析、首轮回填 / 之后只写最近、批量请求数、接线。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import stablecoin_issuers as si  # noqa: E402

DAY = 86400
T0 = int(dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp())
PAYLOAD = [{"date": T0 + k * DAY, "totalCirculatingUSD": {"peggedUSD": 1e9 + k}} for k in range(36)] + [{"date": "x"}, {"date": T0, "totalCirculatingUSD": {}}]


def test_parse():
    rows = si.parse(PAYLOAD, "USDT")
    assert len(rows) == 36 and rows[0] == {"d": "2026-10-01", "coin": "USDT", "circulating_usd": 1e9, "source": "defillama_stablecoins"}
    assert si.parse({"bad": 1}, "USDT") == []


def _run(monkeypatch, have):
    calls, written = [], []

    def get(u):
        calls.append(u)
        return PAYLOAD

    async def read_all(table, params):
        return [{"coin": "USDT"}] if have else []

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    import src.api.store as store
    import src.data.style.header as header
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(header, "_read_all", read_all)
    r = asyncio.run(si.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), get=get))
    return r, calls, written


def test_backfill_then_recent_only(monkeypatch):
    r, calls, written = _run(monkeypatch, have=False)
    assert r["full"] and len(calls) == len(si.ISSUERS) and len(written) == 36 * len(si.ISSUERS)
    r, calls, written = _run(monkeypatch, have=True)
    assert not r["full"] and all(w["d"] >= "2026-10-27" for w in written)


def test_wiring():
    assert "async def _stablecoin_issuers_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_stablecoin_issuer_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in si.WRITES_COLUMNS[si.TABLE])
