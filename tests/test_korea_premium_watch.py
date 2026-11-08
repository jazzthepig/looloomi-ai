"""S-771 P 的前向记录(11-08):cohort 按周一、到期才结算、p7 缺就不写、历史按年往回补到 2021-01-04 为止。"""
import datetime as dt
import json
from pathlib import Path

from src.data.signals import korea_premium_watch as kp

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 17, 2, 0, tzinfo=dt.timezone.utc)


def test_rows_cohort_and_settlement():
    rows = kp.to_rows([{"d": "2026-11-02", "symbol": "egld", "p7": 0.12, "n_days": 7, "mcap": 3e8, "q": 5, "n_cs": 75, "x28": None},
                       {"d": "2026-11-09", "symbol": "ZIL", "p7": 0.08, "n_days": 6, "mcap": 2e8, "q": 5, "n_cs": 74, "x28": -0.05},
                       {"d": "2026-11-09", "symbol": "BAD", "p7": None}], NOW)
    assert [(r["symbol"], r["cohort"]) for r in rows] == [("EGLD", "backfill"), ("ZIL", "forward")], "p7 缺的不写"
    assert rows[0]["settled_at"] is None and rows[1]["settled_at"] is not None
    assert all(set(r) == set(kp.WRITES_COLUMNS[kp.TABLE]) for r in rows)


def test_backfill_walks_back_a_year_at_a_time_and_stops():
    today = dt.date(2026, 11, 17)
    a, b = kp.backfill_window(today, None)
    assert b == today - dt.timedelta(days=kp.RECENT_D + 1) and (b - a).days == kp.CHUNK_D
    a2, b2 = kp.backfill_window(today, "2021-06-07")
    assert a2 == kp.HISTORY_FROM and b2 == dt.date(2021, 6, 6), "最后一段截在 HISTORY_FROM"
    assert kp.backfill_window(today, "2021-01-04") is None


def test_wiring():
    man = json.loads((ROOT / "src/api/schema_manifest.json").read_text(encoding="utf-8"))
    assert kp.TABLE in man["write_tables"] and kp.RPC in man["rpc_functions"]
    sql = (ROOT / "migrations/2026-11-08_korea_premium_watch.sql").read_text(encoding="utf-8")
    assert f"function public.{kp.RPC}(p_from date, p_to date)" in sql
    assert all(f"  {c} " in sql for c in kp.WRITES_COLUMNS[kp.TABLE])
    assert "from src.data.signals.korea_premium_watch import run_once" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
