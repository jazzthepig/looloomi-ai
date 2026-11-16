"""全市场永续持仓 / 基差(11-06):按标的汇总、只收永续、持仓门槛、基差按持仓加权、最大场所的资金费原样。
11-16 加:OI 加权资金费的分子分母两列(positioning 读库优先要用)。"""
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


def test_资金费分子分母():
    """positioning 读的就是这两列。分母只算带 funding_rate 的永续 —— 和 API 路径逐位相同。"""
    r = dm.aggregate(T, "2026-11-06", "t")[0]
    assert r["oi_funding_usd"] == 4e9, "非永续那一行(9e9)不该进分母"
    assert abs(r["funding_oiw_sum"] - (0.01 * 3e9 + 0.03 * 1e9)) < 1e-3
    assert abs(r["funding_oiw_sum"] / r["oi_funding_usd"] - 0.015) < 1e-12


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


def test_迁移没跑时_退回旧列集_不丢这一轮():
    """列不存在(PostgREST PGRST204)时整轮写失败 = 6 小时的数据没了。
    退回旧列集重写,资金费两列等迁移补上。"""
    calls = []

    class Fail:
        ok = False
        why = "HTTP 400: PGRST204"

        def __bool__(self):
            return False

    class W:
        ok = True

        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        calls.append([dict(r) for r in rows])
        if len(calls) == 1:
            return Fail()
        return W()

    import src.api.store as store
    original = store.supabase_upsert_table

    async def fetch():
        return T

    store.supabase_upsert_table = upsert
    try:
        r = asyncio.run(dm.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), fetch=fetch))
    finally:
        store.supabase_upsert_table = original
    assert r["ok"] and r["degraded"] is True
    assert len(calls) == 2
    assert "funding_oiw_sum" in calls[0][0]
    assert "funding_oiw_sum" not in calls[1][0], "退回的旧列集不该带新列"
    assert "oi_usd" in calls[1][0]


def test_wiring():
    assert "async def _derivatives_market_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-06_derivatives_market_daily.sql").read_text(encoding="utf-8")
    mig2 = (ROOT / "migrations/2026-11-16_derivatives_market_funding_oiw.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in dm.WRITES_COLUMNS[dm.TABLE] if c not in dm.FUNDING_COLS)
    assert all(c in mig2 for c in dm.FUNDING_COLS)
