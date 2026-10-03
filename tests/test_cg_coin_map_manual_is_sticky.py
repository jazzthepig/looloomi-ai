"""S-469:映射表读不到时,本轮不解析、不覆盖;人工确认的映射不被自动解析覆盖。"""
import asyncio

from src.data.market import cg_panel_sync as ps
from src.data.market import cg_pro_backfill as bf


def _run(rows_or_none, panel, monkeypatch, resolved=None):
    upserts, gets = [], []

    async def q(table, cols):
        if isinstance(rows_or_none, Exception):
            raise rows_or_none
        return rows_or_none

    async def up(table, rows, on_conflict):
        upserts.append(rows)
        return True

    class Client:
        async def get(self, *a, **k):
            gets.append(a)
            raise AssertionError("映射读不到时不该去 CoinGecko 重新解析")

    class Res:
        rows_written, ok, per_symbol, reason = 1, True, (), ""

    async def fake_backfill(*a, **k):
        return Res()
    monkeypatch.setattr(bf, "backfill", fake_backfill)
    out = asyncio.run(ps.run_once(client=Client(), supabase_query=q, supabase_upsert=up,
                                  panel_symbols=panel, today="2026-10-03"))
    return out, upserts, gets


def test_unreadable_map_refuses_the_round(monkeypatch):
    for bad in (None, [], RuntimeError("timeout")):
        out, upserts, gets = _run(bad, ["ONE", "AI", "BTC"], monkeypatch)
        assert out["status"] == "error" and "读不到" in out["error"]
        assert upserts == [] and gets == []


def test_readable_map_leaves_manual_rows_alone(monkeypatch):
    rows = [{"symbol": "ONE", "coin_id": "harmony", "resolved_from": "manual_verified"},
            {"symbol": "BTC", "coin_id": "bitcoin", "resolved_from": "list_unique"}]
    out, upserts, gets = _run(rows, ["ONE", "BTC"], monkeypatch)
    assert upserts == [] and gets == []
    assert out["n_missing"] == 0
