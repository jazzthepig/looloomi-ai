"""S-777 / S-781 的前向记录(11-08):cohort 按事件日、到期才结算、没价不写 0、表空才全量。"""
import datetime as dt
import json
from pathlib import Path

from src.data.signals import crowding_watch as cw

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 8, 1, 0, tzinfo=dt.timezone.utc)


def test_cohort_and_settlement():
    raw = [
        {"kind": "squeeze", "symbol": "abc", "d": "2026-11-04", "fund_pct": 0.05, "ret": 0.3, "atr_thr": 0.2,
         "qv_mult": 4.0, "x1": 0.01, "x7": -0.1, "x30": -0.2, "basket_n": 640},
        {"kind": "squeeze", "symbol": "DEF", "d": "2026-11-05", "x1": -0.02, "x7": None, "x30": None, "basket_n": 641},
        {"kind": "flush", "symbol": "GHI", "d": "2026-11-06", "x1": None, "x7": None, "x30": float("nan"), "basket_n": None},
    ]
    rows = cw.to_rows(raw, NOW)
    assert [r["cohort"] for r in rows] == ["backfill", "forward", "forward"], "11-04 是 S-781 的最后一天,11-05 起才是前向"
    assert rows[0]["symbol"] == "ABC" and rows[0]["settled_at"] is not None
    assert rows[1]["x30"] is None and rows[1]["settled_at"] is None, "没到期就不结算"
    assert rows[2]["x30"] is None and rows[2]["basket_n"] is None, "NaN / 没价写空,不写 0"
    assert all(set(r) >= set(cw.WRITES_COLUMNS[cw.TABLE]) for r in rows)


def test_bad_rows_are_dropped():
    assert cw.to_rows([{"kind": "other", "symbol": "X", "d": "2026-11-05"}, {"kind": "squeeze", "symbol": "", "d": "2026-11-05"},
                       {"kind": "squeeze", "symbol": "X", "d": None}], NOW) == []


def test_window_full_history_only_when_empty():
    assert cw.window_start(dt.date(2026, 11, 8), True) == cw.HISTORY_FROM
    assert cw.window_start(dt.date(2026, 11, 8), False) == dt.date(2026, 9, 24)
    assert cw.LOOKBACK_D > 31, "回看必须盖住 30 天的结算窗口,否则到期的事件永远不会被重算"


def test_manifest_and_migration_agree():
    man = json.loads((ROOT / "src/api/schema_manifest.json").read_text(encoding="utf-8"))
    assert cw.TABLE in man["write_tables"] and cw.RPC in man["rpc_functions"]
    sql = (ROOT / "migrations/2026-11-08_crowding_watch.sql").read_text(encoding="utf-8")
    assert f"create table if not exists public.{cw.TABLE}" in sql and f"function public.{cw.RPC}(p_from date)" in sql
    for col in cw.WRITES_COLUMNS[cw.TABLE]:
        assert f"  {col} " in sql, col
    kern = (ROOT / "migrations/2026-11-08_crowding_events.sql").read_text(encoding="utf-8")
    assert "with recursive" in kern, "walk 自引用:没有 recursive Postgres 直接报错(提案里漏了)"
    assert "nullif(a.qv20, 0)" in kern, "旧口径下 qv20 = 0 也过门槛,不防除零整个函数报错"
