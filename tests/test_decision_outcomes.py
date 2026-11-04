"""决策 → 结果(11-04):入场是决策日之后第一根收盘(披露日才知道)、出场对齐周末、到期才结、缺价不写 0、聚合 n<5 标 thin。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.entity import decision_outcomes as do  # noqa: E402


def _closes():
    eq, spy = {}, {}
    d0 = dt.date(2026, 1, 1)
    for i in range(130):
        d = d0 + dt.timedelta(days=i)
        if d.weekday() < 5:                                           # 股票没有周末 bar
            eq[d.isoformat()] = 100.0 * (1 + 0.002 * i)
            spy[d.isoformat()] = 50.0 * (1 + 0.001 * i)
    return {("eodhd", "COIN"): eq, ("eodhd", "SPY"): spy}


def test_entry_is_first_close_on_or_after_filing_and_exit_aligns_to_weekend():
    dec = [{"id": "x1", "entity_id": "coinbase", "ts": "2026-01-03T00:00:00+00:00", "kind": "buyback", "symbols": ["COIN"]}]  # 周六披露
    rows, n = do.settle(dec, _closes(), dt.date(2026, 4, 15), {"COIN": "equity"})
    assert n == {"settled": 3, "pending": 0, "no_price": 0, "skipped_cls": 0}
    r7 = next(r for r in rows if r["horizon_d"] == 7)
    assert r7["entry_d"] == "2026-01-05" and r7["exit_d"] == "2026-01-09"         # 周一入、下周五出(1-10 是周六)
    assert r7["bench"] == "SPY" and abs(r7["excess"] - (r7["ret"] - r7["ret_bench"])) < 1e-5 and r7["hit"] is True


def test_unmatured_horizons_wait_and_missing_prices_are_not_zero():
    dec = [{"id": "x2", "entity_id": "coinbase", "ts": "2026-04-01T00:00:00+00:00", "kind": "buyback", "symbols": ["COIN"]},
           {"id": "x3", "entity_id": "uniswap", "ts": "2026-01-10T00:00:00+00:00", "kind": "venue_listing", "symbols": ["UNI"]},
           {"id": "x4", "entity_id": "tether", "ts": "2026-01-10T00:00:00+00:00", "kind": "payout_class", "symbols": ["USDT"]}]
    rows, n = do.settle(dec, _closes(), dt.date(2026, 4, 15), {"COIN": "equity", "UNI": "token"})
    assert [r["horizon_d"] for r in rows if r["decision_id"] == "x2"] == [7]        # 30 / 90 还没到期
    assert n["pending"] == 2 and n["no_price"] == 3 and n["skipped_cls"] == 1
    assert not any(r["decision_id"] in ("x3", "x4") for r in rows)


def test_already_settled_rows_are_not_recomputed():
    dec = [{"id": "x1", "entity_id": "coinbase", "ts": "2026-01-03T00:00:00+00:00", "kind": "buyback", "symbols": ["COIN"]}]
    rows, _ = do.settle(dec, _closes(), dt.date(2026, 4, 15), {"COIN": "equity"}, done={("x1", 7), ("x1", 30)})
    assert [r["horizon_d"] for r in rows] == [90]


def test_aggregate_marks_thin_and_reports_hit_rate():
    rows = [{"kind": "buyback", "horizon_d": 30, "excess": v} for v in (0.05, -0.01, 0.02, 0.03, -0.02, 0.01)]
    rows += [{"kind": "venue_listing", "horizon_d": 30, "excess": -0.1}]
    agg = {(a["kind"], a["horizon_d"]): a for a in do.aggregate(rows)}
    b = agg[("buyback", 30)]
    assert b["n"] == 6 and not b["thin"] and abs(b["hit_rate"] - 4 / 6) < 1e-3 and b["q1"] is not None
    assert agg[("venue_listing", 30)]["thin"]


def test_run_once_reads_only_needed_sources_and_upserts(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    up, reads = {}, []

    async def read_all(t, params):
        reads.append((t, params))
        if t == "issuer_decisions":
            return [{"id": "x1", "entity_id": "coinbase", "ts": "2026-01-03T00:00:00+00:00", "kind": "buyback", "symbols": ["COIN"]}]
        if t == do.TABLE:
            return [{"decision_id": "x1", "horizon_d": 7}]
        if t == "ohlcv_daily":
            assert params["source"] == "eq.eodhd" and "COIN" in params["symbol"] and "SPY" in params["symbol"]
            return [{"symbol": s, "trade_date": d, "close": c} for (src, s), ser in _closes().items() for d, c in ser.items()]
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up.setdefault(t, []).extend(rows)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(do.run_once(dt.datetime(2026, 4, 15, 3, 0, tzinfo=dt.timezone.utc)))
    assert r["ok"] and r["written"] == 2 and sorted(x["horizon_d"] for x in up[do.TABLE]) == [30, 90]
    assert not any(p.get("source") == "eq.coingecko_pro_ohlc" for _, p in reads)


def test_wiring():
    assert "_decision_outcomes_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert '"/internal/decision-outcomes"' in (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-04_decision_outcomes.sql").read_text(encoding="utf-8")
    for col in do.WRITES_COLUMNS[do.TABLE]:
        assert col in mig, col
