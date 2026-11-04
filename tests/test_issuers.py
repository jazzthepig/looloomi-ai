"""发行方 / 决策层(11-04):登记表完整覆盖 CIS 25 + 轨道 10、稳定币归实际发行方、三个派生写入端、一轮 run_once。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.entity import issuers as iss  # noqa: E402


def test_registry_covers_the_universe_and_maps_symbols_to_one_issuer():
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.universe.world50 import RAIL_EQUITIES
    bs = iss.entity_by_symbol()
    for s in CRYPTO_ASSETS:
        assert s in bs, f"CIS 名字 {s} 没有发行方"
    for c in RAIL_EQUITIES:
        assert c.key in bs, f"轨道公司 {c.key} 没有发行方"
    assert bs["PYUSD"] == "paxos" and bs["USDC"] == "circle" and bs["MKR"] == "sky" and bs["BTC"] == "bitcoin"
    assert len({e["id"] for e in iss.ENTITIES}) == len(iss.ENTITIES), "id 唯一"
    assert all(e["confidence"] in ("verified", "assumed") for e in iss.ENTITIES)
    bg = iss.entity_by_gecko()
    assert bg["hyperliquid"] == "hyperliquid" and bg["maker"] == "sky"


def test_fundamentals_become_dated_decisions_on_filing_date():
    bs = iss.entity_by_symbol()
    f = [{"symbol": "COIN", "period": "CY2025Q1", "filed": "2025-05-08", "buybacks": 0, "dividends": None, "diluted_shares": 250},
         {"symbol": "COIN", "period": "CY2025Q2", "filed": "2025-07-31", "buybacks": 1.2e8, "dividends": None, "diluted_shares": 256},
         {"symbol": "ZZZ", "period": "CY2025Q2", "filed": "2025-07-31", "buybacks": 5, "dividends": 5, "diluted_shares": 1}]
    out = iss.decisions_from_fundamentals(f, bs)
    kinds = sorted((d["kind"], d["ts"][:10]) for d in out)
    assert kinds == [("buyback", "2025-07-31"), ("share_dilution", "2025-07-31")], "零回购不写;不在登记表的不写;Q1 无前值不判稀释"
    assert next(d for d in out if d["kind"] == "share_dilution")["value"] == 0.024
    assert len({d["id"] for d in out}) == 2 and iss.decisions_from_fundamentals(f, bs)[0]["id"] == out[0]["id"], "id 稳定"


def test_events_and_treatment_writers():
    bs = iss.entity_by_symbol()
    ev = [{"id": "e1", "ts": "2026-11-01T00:00:00+00:00", "kind": "listing", "source": "binance", "symbols": ["HYPE", "FOO"], "payload": {"scope": "spot"}},
          {"id": "e2", "ts": "2026-11-01T00:00:00+00:00", "kind": "perp_delisting", "source": "binance", "symbols": ["ARB"], "payload": {}},
          {"id": "e3", "ts": "2026-11-01T00:00:00+00:00", "kind": "news", "source": "coindesk", "symbols": ["BTC"], "payload": {}}]
    out = iss.decisions_from_events(ev, bs)
    assert [(d["entity_id"], d["kind"], d["payload"]["perp"]) for d in out] == [("hyperliquid", "venue_listing", False), ("arbitrum", "venue_delisting", True)]
    tr = [{"symbol": "HYPE", "revenue_30d": 1e6, "holders_30d": 1e6, "holders_share": 1.0, "supply_growth_30d": 0.03, "supply": 1},
          {"symbol": "AAVE", "revenue_30d": 5e6, "holders_30d": 0, "holders_share": 0.0, "supply_growth_30d": 0.0, "supply": 1},
          {"symbol": "BTC", "revenue_30d": None, "holders_share": None, "supply_growth_30d": 0.001}]
    out = iss.decisions_from_treatment(tr, bs, "2026-11-02")
    kinds = sorted((d["entity_id"], d["kind"]) for d in out)
    assert kinds == [("aave", "payout_class"), ("hyperliquid", "payout_class"), ("hyperliquid", "token_dilution")]
    assert next(d for d in out if d["entity_id"] == "aave")["payload"]["class"] == "keeps"


def test_run_once_syncs_registry_and_writes_decisions(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    up = {}

    async def read_all(t, params):
        if t == "issuer_fundamentals_quarterly":
            return [{"symbol": "COIN", "period": "CY2025Q2", "filed": "2025-07-31", "buybacks": 1e8, "dividends": None, "diluted_shares": 256}]
        if t == "events":
            return [{"id": "e1", "ts": "2026-11-01T00:00:00+00:00", "kind": "listing", "source": "binance", "symbols": ["HYPE"], "payload": {"scope": "spot"}}]
        if t == "treatment_daily":
            assert params["d"] == "eq.2026-11-02", "取本周一"
            return [{"symbol": "UNI", "revenue_30d": 8e6, "holders_30d": 8e6, "holders_share": 1.0, "supply_growth_30d": 0.0, "supply": 1}]
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up.setdefault(t, []).extend(rows)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(iss.run_once(dt.datetime(2026, 11, 5, 3, 0, tzinfo=dt.timezone.utc)))
    assert r["ok"] and r["entities"] == len(iss.ENTITIES) and r["kinds"] == {"buyback": 1, "venue_listing": 1, "payout_class": 1}
    assert len(up[iss.ENTITIES_TABLE]) == len(iss.ENTITIES) and len(up[iss.DECISIONS_TABLE]) == 3


def test_wiring():
    assert "_issuer_decisions_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/entities"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-04_issuer_entities_decisions.sql").read_text(encoding="utf-8")
    for t, cols in iss.WRITES_COLUMNS.items():
        for col in cols:
            assert col in mig, f"{t}.{col}"
