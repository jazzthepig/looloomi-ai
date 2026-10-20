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
    assert rt.interpret({"ok": False, "busy": True})[0] == "refused"
    assert rt.interpret({"ok": True, "reason": "up to date", "last_d": "2026-10-19"})[0] == "ok"


def test_run_once_asks_for_yesterday_and_surfaces_failures(monkeypatch):
    from src.api import store
    from src.api.store_result import StoreResult
    calls = []

    async def fake_ok(fn, payload=None, *, timeout=None):
        calls.append((fn, payload))
        assert timeout and timeout >= 60, "单日约 8 秒,共享客户端 10 秒不够"
        return StoreResult.ok_(value={"ok": True, "last_done": payload["p_to"], "open_now": 0})

    async def money_ok():
        return {"ok": True, "written": 2, "last_d": "2026-10-19"}

    monkeypatch.setattr(store, "supabase_rpc_write", fake_ok)
    monkeypatch.setattr(rt, "write_money", money_ok)
    out = asyncio.run(rt.run_once(datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)))
    assert calls == [("r_tickets_scan", {"p_to": "2026-10-19"})]
    assert out["status"] == "ok" and out["detail"]["money"]["ok"]

    async def money_bad():
        return {"ok": False, "why": "HTTP 500"}
    monkeypatch.setattr(rt, "write_money", money_bad)
    out = asyncio.run(rt.run_once(datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)))
    assert out["status"] == "error" and "r_money_daily" in out["reason"], "钱曲线没写进去 = 这一轮失败,不能报 ok"

    async def fake_fail(fn, payload=None, *, timeout=None):
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
    assert "pg_try_advisory_xact_lock" in sql, "并发调用(超时重试)不能把同一天跑两遍"


# ── S-638:记钱的内核 r_tickets_nav(只读;前向与回放喂同一个函数)────────────────────────────────

def _nav_sql() -> str:
    return (ROOT / "migrations" / "2026-10-21_r_tickets_nav.sql").read_text(encoding="utf-8")


def test_nav_kernel_sizes_on_yesterdays_equity_and_charges_the_r_formula_cost():
    sql = _nav_sql()
    assert "p_f * (case when p_compound then v_eq_prev else p_equity0 end) / (r.entry_px - r.stop_px)" in sql
    # 进出各 0.2% × 进场名义 = R 公式里的 0.4% × 进场 /(进场 − 止损);持仓期先扣进场那一半,出场扣齐
    assert "k.exit_px - k.entry_px - 0.004 * k.entry_px" in sql
    assert "m.c - k.entry_px - 0.002 * k.entry_px" in sql
    # 前一天收盘的净值:已实现 + 当天(v_e − 1)还持有的盯市
    assert "k.exit_d <= v_e - 1" in sql and "p.t = v_e - 1" in sql


def test_nav_kernel_cap_is_first_come_first_served_and_counts_exit_day_as_occupied():
    sql = _nav_sql()
    assert "k.entry_d < v_e and (k.exit_d is null or k.exit_d >= v_e)" in sql, "出场当天仍占位(S-638 写死的保守口径)"
    assert "order by k.signal_d, k.symbol" in sql
    assert "v_occ + v_k < p_cap" in sql


def test_nav_kernel_is_read_only_and_not_callable_anonymously():
    sql = _nav_sql().lower()
    for verb in ("insert into public.", "update public.", "delete from public.", "insert into r_tickets",
                 "update r_tickets", "delete from r_tickets"):
        assert verb not in sql, f"记钱内核只读,不该有 {verb!r}"
    assert "create temp table _nv_tk on commit drop" in sql
    assert "revoke all on function public.r_tickets_nav(jsonb, double precision, int, date, date, boolean, double precision) from public, anon, authenticated" in sql
    assert "revoke all on function public.r_tickets_nav_paper(double precision, int, date) from public, anon, authenticated" in sql


def test_replay_tickets_sql_uses_the_same_rules_as_the_forward_scan():
    """回放的票(docs/research/r_v2_tickets.sql)与前向的 r_tickets_scan 必须同一套规则 —— 改一边就得改另一边。"""
    scan = (ROOT / "migrations" / "2026-10-20_r_tickets_paper.sql").read_text(encoding="utf-8")
    rep = (ROOT / "docs" / "research" / "r_v2_tickets.sql").read_text(encoding="utf-8")
    assert "2.5 * t.atr14" in scan and "2.5*e.atr14" in rep, "止损 = 进场 − 2.5 × ATR14"
    cond = ("mindd120 <= 0.5", "<= 0.40", "> hh40", "> sma200", "adv40p", "adv30 >= 5e6", "rn >= 220")
    for c in cond:
        assert c in scan and c in rep, c
    for g in ("style = 'majors' and weighting = 'cap'", "rows between 199 preceding and current row", "n < 200 or lvl > sma"):
        assert g in scan and g in rep, f"闸门口径不同:{g}"
    assert "least(s.rn+120, s.n)" in rep and "t.bars_held >= 120" in scan
    assert "'exit_d', case when r.still_open then null" in rep, "没出场的票要按持仓逐日盯市,不能当已平仓"


def test_money_rows_chain_nav_and_carry_the_s638_parameters():
    curve = [{"d": "2026-10-20", "equity": 1.02, "realized": 0.0, "unrealized": 0.02, "open_n": 1, "gross": 0.1,
              "taken": 1, "skipped": 0, "closed": 0},
             {"d": "2026-10-19", "equity": 1.0, "realized": 0.0, "unrealized": 0.0, "open_n": 0, "gross": 0.0,
              "taken": 0, "skipped": 0, "closed": 0}]
    rows = rt.money_rows(curve)
    assert [r["d"] for r in rows] == ["2026-10-19", "2026-10-20"], "按日期排序,不信返回顺序"
    assert rows[0]["ret"] == 0.0 and abs(rows[1]["ret"] - 0.02) < 1e-12 and rows[1]["nav"] == 1.02
    assert all(r["f"] == 0.01 and r["cap"] == 10 and r["inception"] == "2026-10-19" for r in rows)
    assert rt.money_rows(None) == [] and rt.money_rows([{"d": "2026-10-19", "equity": None}]) == []


def test_write_money_goes_through_the_forward_lock(monkeypatch):
    from src.api import store
    from src.api.store_result import StoreResult
    from src.data.accounting import forward_lock
    seen = {}

    async def rpc(fn, payload=None, *, timeout=None):
        seen["rpc"] = (fn, payload)
        return StoreResult.ok_(value=[{"d": "2026-10-19", "equity": 1.0, "open_n": 0}])

    async def locked(table, rows, *, key, on_conflict, **kw):
        seen["lock"] = (table, key, on_conflict, len(rows))
        return {"ok": True, "written": len(rows)}

    monkeypatch.setattr(store, "supabase_rpc_write", rpc)
    monkeypatch.setattr(forward_lock, "write_locked", locked)
    out = asyncio.run(rt.write_money())
    assert seen["rpc"] == ("r_tickets_nav_paper", {"p_f": 0.01, "p_cap": 10})
    assert seen["lock"] == ("r_money_daily", None, "d", 1), "前天及更早的行不再改(S-560)"
    assert out["ok"] and out["last_d"] == "2026-10-19"


def test_money_table_migration_exists_and_is_lane_readable():
    sql = (ROOT / "migrations" / "2026-10-20_r_money_daily.sql").read_text(encoding="utf-8")
    assert "create table if not exists public.r_money_daily" in sql and "inception    date not null" in sql
    assert "create policy lane_read on public.r_money_daily for select to anon" in sql
