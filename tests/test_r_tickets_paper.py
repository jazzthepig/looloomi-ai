"""交易层 v2 纸面账本:Railway 这一侧的薄壳(内核在 Postgres 函数 r_tickets_scan 里)。

钉住三件事:只推进已收盘的 UTC 日;「数据没到」记 refused 不是 error;主程序真的把循环挂上并记 loop_attempt。
内核与研究 SQL 的一致性在 Supabase 里验过(2024 年 266 张、267.68R 逐笔相同,见台账 / docs/TRADING_LAYER_V2.md)。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals import r_tickets_paper as rt  # noqa: E402


def test_target_day_is_the_last_completed_utc_day():
    assert rt.target_day(datetime(2026, 10, 20, 0, 5, tzinfo=timezone.utc)) == date(2026, 10, 19)
    assert rt.target_day(datetime(2026, 10, 20, 23, 59, tzinfo=timezone.utc)) == date(2026, 10, 19)


def test_interpret_ok_refused_error():
    s, why, d = rt.interpret({"ok": True, "last_done": "2026-10-19", "new_pending": 2, "blocked": 0, "closed": 1,
                              "open_now": 5})
    assert s == "ok" and "2026-10-19" in why and d["open_now"] == 5
    s, why, _ = rt.interpret({"ok": False, "last_done": "2026-10-18", "stopped": "only 10 bars on 2026-10-19"})
    assert s == "refused" and "2026-10-18" in why
    assert rt.interpret({"ok": False})[0] == "error"
    assert rt.interpret(None)[0] == "error"
    assert rt.interpret({"ok": True, "reason": "up to date", "last_d": "2026-10-19"})[0] == "ok"


def test_run_once_asks_for_yesterday_and_surfaces_failures(monkeypatch):
    from src.api import store
    from src.api.store_result import StoreResult
    calls = []

    async def fake_ok(fn, payload=None):
        calls.append((fn, payload))
        return StoreResult.ok_(value={"ok": True, "last_done": payload["p_to"], "open_now": 0})

    monkeypatch.setattr(store, "supabase_rpc_write", fake_ok)
    out = asyncio.run(rt.run_once(datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)))
    assert calls == [("r_tickets_scan", {"p_to": "2026-10-19"})]
    assert out["status"] == "ok"

    async def fake_fail(fn, payload=None):
        return StoreResult.fail("HTTP 500: boom")

    monkeypatch.setattr(store, "supabase_rpc_write", fake_fail)
    out = asyncio.run(rt.run_once(datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)))
    assert out["status"] == "error" and "boom" in out["reason"]


def test_main_schedules_the_loop_and_records_attempts():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert "async def _r_tickets_paper_loop" in src
    assert "_asyncio.create_task(_r_tickets_paper_loop())" in src
    body = src.split("async def _r_tickets_paper_loop", 1)[1].split("@app.on_event", 1)[0]
    assert body.count("_record_loop_attempt(") >= 2, "成功与异常两条路都要记 loop_attempt"


def test_migration_is_the_kernel_and_revokes_anonymous_execute():
    sql = (ROOT / "migrations" / "2026-10-20_r_tickets_paper.sql").read_text(encoding="utf-8")
    assert "create or replace function public.r_tickets_scan(p_to date, p_from date default null)" in sql
    assert "2.5 * t.atr14" in sql and "b.c < b.sma20" in sql and "t.bars_held >= 120" in sql
    assert "revoke all on function public.r_tickets_scan(date, date) from public, anon, authenticated" in sql
    assert "is not a completed UTC day" in sql
