"""全市场永续持仓 / 基差(11-06):按标的汇总、只收永续、持仓门槛、基差按持仓加权、最大场所的资金费原样。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import derivatives_market as dm  # noqa: E402

T = [{"index_id": "BTC", "contract_type": "perpetual", "open_interest": 3e9, "volume_24h": 1e9, "basis": 0.02, "market": "Binance", "funding_rate": 0.01},
     {"index_id": "BTC", "contract_type": "perpetual", "open_interest": 1e9, "volume_24h": 5e8, "basis": 0.10, "market": "OKX", "funding_rate": 0.03},
     {"index_id": "BTC", "contract_type": "futures", "open_interest": 9e9},
     {"index_id": "TINY", "contract_type": "perpetual", "open_interest": 1e5},
     {"index_id": None, "open_interest": 1e9}]


def test_aggregate():
    rows = dm.aggregate(T, "2026-11-06", "t")
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "BTC" and r["oi_usd"] == 4e9 and r["n_markets"] == 2 and r["top_market"] == "Binance" and r["top_funding_raw"] == 0.01
    assert abs(r["basis_oiw_pct"] - (0.02 * 3 + 0.10 * 1) / 4) < 1e-9


def test_run_once(monkeypatch):
    written = []

    async def fetch():
        return T

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    import src.api.store as store
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    r = asyncio.run(dm.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), fetch=fetch))
    assert r["ok"] and len(written) == 1 and set(written[0]) == set(dm.WRITES_COLUMNS[dm.TABLE])


def test_wiring():
    assert "async def _derivatives_market_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_derivatives_market_daily.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in dm.WRITES_COLUMNS[dm.TABLE])
