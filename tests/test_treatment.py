"""小股东待遇日表(11-03):多 slug 求和、没有协议收入是 NULL 不是 0、稀释与收益率口径、排名、一轮 run_once。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.entity import treatment as tr  # noqa: E402

ASSETS = {"HYPE": {"coingecko": "hyperliquid"}, "AAVE": {"coingecko": "aave"}, "BTC": {"coingecko": "bitcoin"}, "ARB": {"coingecko": "arbitrum"}}
REV = [{"gecko_id": "hyperliquid", "revenue_30d": 66e6, "holders_30d": 66e6}, {"gecko_id": "hyperliquid", "revenue_30d": 0.8e6, "holders_30d": 0.8e6},
       {"gecko_id": "aave", "revenue_30d": 5e6, "holders_30d": 0}, {"gecko_id": "arbitrum", "revenue_30d": 0.57e6, "holders_30d": 0},
       {"gecko_id": "arbitrum", "revenue_30d": 0.1e6, "holders_30d": 0}]
TODAY = {"HYPE": {"mcap": 12e9, "price": 40.0}, "AAVE": {"mcap": 3e9, "price": 200.0}, "BTC": {"mcap": 2e12, "price": 100000.0}, "ARB": {"mcap": 2e9, "price": 0.4}}
AGO = {"HYPE": {"mcap": 11e9, "price": 40.0}, "AAVE": {"mcap": 3e9, "price": 200.0}, "BTC": {"mcap": 1.9e12, "price": 95000.0}}


def test_rows_sum_slugs_and_keep_null_for_names_without_protocol_revenue():
    rows = {r["symbol"]: r for r in tr.rows_for("2026-11-02", ASSETS, REV, TODAY, AGO)}
    h = rows["HYPE"]
    assert h["revenue_30d"] == 66.8e6 and h["holders_share"] == 1.0 and h["n_slugs"] == 2
    assert abs(h["supply_growth_30d"] - (12e9 / 40 / (11e9 / 40) - 1)) < 1e-6 and abs(h["holder_yield_ann"] - 66.8e6 * 12 / 12e9) < 1e-6
    assert rows["AAVE"]["holders_share"] == 0.0 and rows["AAVE"]["holder_yield_ann"] == 0.0, "有收入、零分给持有人 ⇒ 0,不是 NULL"
    assert rows["BTC"]["revenue_30d"] is None and rows["BTC"]["holders_share"] is None and rows["BTC"]["rank_holder_yield"] is None
    assert abs(rows["BTC"]["supply_growth_30d"] - (2e12 / 100000 / (1.9e12 / 95000) - 1)) < 1e-9
    assert rows["ARB"]["supply_growth_30d"] is None, "30 天前没数据 ⇒ NULL"
    assert rows["HYPE"]["rank_holder_yield"] == 1 and rows["ARB"]["rank_holder_yield"] in (2, 3) and rows["AAVE"]["rank_holder_yield"] in (2, 3)


def test_run_once_skips_when_written_or_inputs_missing(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    import src.data.cis.cis_provider as cp
    up = []
    state = {"have": [], "rev": REV}

    async def read_all(t, params):
        if t == tr.TABLE:
            return state["have"]
        if t == "protocol_revenue_daily":
            return state["rev"]
        if t == "asset_mcap_daily":
            src = TODAY if params["d"] == "eq.2026-11-02" else AGO
            return [{"symbol": s, **v} for s, v in src.items()]
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    monkeypatch.setattr(cp, "CRYPTO_ASSETS", ASSETS)
    now = dt.datetime(2026, 11, 3, 3, 0, tzinfo=dt.timezone.utc)
    r = asyncio.run(tr.run_once(now))
    assert r["ok"] and r["d"] == "2026-11-02" and r["written"] == 4 and r["with_share"] == 3
    state["have"] = [{"symbol": "HYPE"}]
    assert asyncio.run(tr.run_once(now))["status"] == "already_done"      # S-862:写过了 ≠ 拒绝
    state["have"], state["rev"] = [], []
    assert "还没到" in asyncio.run(tr.run_once(now))["why"]


def test_wiring():
    assert "_treatment_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-03_treatment_daily.sql").read_text(encoding="utf-8")
    for col in tr.WRITES_COLUMNS[tr.TABLE]:
        assert col in mig, col
