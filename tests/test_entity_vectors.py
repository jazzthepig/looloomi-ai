"""Entity 空间向量(11-05):按季折、没测到的维不写、计数与金额分开、只用 30 天结果。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.entity import entity_vectors as ev  # noqa: E402


def test_quarter_of():
    assert ev.quarter_of("2026-01-15") == "2026Q1" and ev.quarter_of("2026-11-05") == "2026Q4" and ev.quarter_of("2025-12-31") == "2025Q4"


def test_vectors_fold_three_sources_and_omit_unmeasured_dims():
    by = {"UNI": "uniswap", "COIN": "coinbase"}
    tr = [{"symbol": "UNI", "d": "2026-10-21", "holders_share": 1.0, "revenue_yield_ann": 0.05, "holder_yield_ann": 0.05, "supply_growth_30d": None},
          {"symbol": "UNI", "d": "2026-10-22", "holders_share": 0.5, "revenue_yield_ann": 0.07, "holder_yield_ann": 0.03, "supply_growth_30d": 0.01},
          {"symbol": "ZZZ", "d": "2026-10-22", "holders_share": 0.9}]
    dec = [{"entity_id": "coinbase", "ts": "2026-10-27T00:00:00+00:00", "kind": "buyback", "value": 1e8},
           {"entity_id": "coinbase", "ts": "2026-08-01T00:00:00+00:00", "kind": "share_dilution", "value": 0.03},
           {"entity_id": "uniswap", "ts": "2026-11-02T00:00:00+00:00", "kind": "payout_class", "value": 1.0},
           {"entity_id": "uniswap", "ts": "2026-11-02T00:00:00+00:00", "kind": "weird", "value": 1.0}]
    out = [{"entity_id": "coinbase", "d": "2026-10-27", "horizon_d": 30, "excess": -0.02},
           {"entity_id": "coinbase", "d": "2026-10-27", "horizon_d": 90, "excess": 0.5}]
    rows = {(r["entity_id"], r["quarter"]): r for r in ev.vectors(tr, dec, out, by)}
    u = rows[("uniswap", "2026Q4")]
    assert u["n_days"] == 2 and u["vector"]["payout_share"] == 0.75 and u["vector"]["supply_growth"] == 0.01 and u["vector"]["n_payout_class"] == 1
    assert "n_weird" not in u["vector"] and "outcome_excess_30d" not in u["vector"]
    c = rows[("coinbase", "2026Q4")]
    assert c["vector"] == {"n_buyback": 1.0, "buyback_usd": 1e8, "outcome_excess_30d": -0.02} and c["n_decisions"] == 1 and c["n_days"] == 0
    assert rows[("coinbase", "2026Q3")]["vector"] == {"n_share_dilution": 1.0}
    assert ("zzz", "2026Q4") not in rows
    only = ev.vectors(tr, dec, out, by, quarters={"2026Q3"})
    assert [(r["entity_id"], r["quarter"]) for r in only] == [("coinbase", "2026Q3")]


def test_run_once_full_then_recent(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    up, reads = {}, []

    async def read_all(t, params):
        reads.append((t, params))
        if t == ev.TABLE:
            return []
        if t == "treatment_daily":
            return [{"symbol": "UNI", "d": "2026-10-21", "holders_share": 1.0}]
        if t in ("issuer_decisions", "decision_outcomes"):
            return []
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up[t] = rows
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(ev.run_once(dt.datetime(2026, 11, 5, 3, 0, tzinfo=dt.timezone.utc)))
    assert r["ok"] and r["full"] and r["written"] == 1 and up[ev.TABLE][0]["quarter"] == "2026Q4"
    assert any(p.get("d") == "gte.2015-01-01" for t, p in reads if t == "treatment_daily")


def test_wiring():
    assert "_entity_vectors_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/entity-vectors"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-05_entity_vectors.sql").read_text(encoding="utf-8")
    for col in ev.WRITES_COLUMNS[ev.TABLE]:
        assert col in mig, col
