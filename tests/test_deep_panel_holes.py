"""binance_hist 内部缺口自愈(10-20,S-628 撞上的 08-09 → 09-06 洞):前沿自愈看不见历史中间的洞。

钉住:窗口够长能盖住最早的洞、名字有上限、读不到不抛、日更没成功就不补、补的走同一个写入端。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import deep_panel_collector as dp  # noqa: E402


def test_heal_plan_covers_the_oldest_hole():
    holes = [{"symbol": "crv", "first_missing": "2026-08-09", "n_missing": 29},
             {"symbol": "ALGO", "first_missing": "2026-07-28", "n_missing": 41}]
    days, syms = dp.heal_plan(holes, date(2026, 10, 20))
    assert syms == ["ALGO", "CRV"]
    assert days == (date(2026, 10, 20) - date(2026, 7, 28)).days + 3
    assert dp.heal_plan([], date(2026, 10, 20)) is None
    far = [{"symbol": "X", "first_missing": "2025-01-01", "n_missing": 1}]
    assert dp.heal_plan(far, date(2026, 10, 20))[0] == dp._HEAL_MAX_DAYS
    many = [{"symbol": f"S{i}", "first_missing": "2026-10-01", "n_missing": 1} for i in range(400)]
    assert len(dp.heal_plan(many, date(2026, 10, 20))[1]) == dp._HOLE_MAX_SYMBOLS


def test_heal_uses_the_same_writer_and_never_raises(monkeypatch):
    from src.api import store
    calls = []

    async def rpc(fn, payload=None):
        assert fn == "binance_hist_interior_holes"
        return [{"symbol": "CRV", "first_missing": "2026-08-09", "n_missing": 29}]

    async def collect(days=None, symbols=None):
        calls.append((days, symbols))
        return {"ok": True, "symbols_ok": 1, "rows_upserted": 29}

    monkeypatch.setattr(store, "supabase_rpc", rpc)
    monkeypatch.setattr(dp, "collect_deep_panel", collect)
    r = asyncio.run(dp.heal_interior_holes(date(2026, 10, 20)))
    assert r["ok"] and r["holes"] == 1 and r["missing_days"] == 29
    assert calls == [((date(2026, 10, 20) - date(2026, 8, 9)).days + 3, ["CRV"])]

    async def rpc_none(fn, payload=None):
        return None

    monkeypatch.setattr(store, "supabase_rpc", rpc_none)
    assert asyncio.run(dp.heal_interior_holes(date(2026, 10, 20)))["ok"] is False

    async def boom(fn, payload=None):
        raise RuntimeError("down")

    monkeypatch.setattr(store, "supabase_rpc", boom)
    assert "down" in asyncio.run(dp.heal_interior_holes(date(2026, 10, 20)))["error"]


def test_loop_heals_only_after_a_good_daily_run_and_records_it():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    body = src.split("async def _deep_panel_loop", 1)[1].split("@app.on_event", 1)[0]
    assert "if r.get(\"ok\"):" in body and "heal_interior_holes()" in body
    assert '"heal":           _heal' in body
    sql = (ROOT / "migrations" / "2026-10-20_binance_hist_interior_holes.sql").read_text(encoding="utf-8")
    assert "revoke all on function public.binance_hist_interior_holes(int) from public, anon, authenticated" in sql
