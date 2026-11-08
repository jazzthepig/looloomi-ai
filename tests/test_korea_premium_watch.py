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


def test_backfill_chunks_walk_back_and_stop_and_never_hit_the_row_cap():
    c = kp.chunks(dt.date(2026, 9, 26))
    assert len(c) == kp.MAX_CHUNKS and c[0][1] == dt.date(2026, 9, 26) and (c[0][1] - c[0][0]).days == kp.CHUNK_D - 1
    assert all(c[i][0] - dt.timedelta(days=1) == c[i + 1][1] for i in range(len(c) - 1)), "段与段首尾相接,不漏天"
    tail = kp.chunks(dt.date(2021, 2, 1))
    assert tail[-1][0] == kp.HISTORY_FROM and kp.chunks(dt.date(2021, 1, 3)) == []
    assert (kp.CHUNK_D // 7 + 1) * 90 < kp.PAGE_MAX, "一段最多 9 个周一 × 90 个币,必须在 PostgREST 上限之下"
    assert kp.truncated([{}] * 1000) and not kp.truncated([{}] * 999)


def test_wiring():
    man = json.loads((ROOT / "src/api/schema_manifest.json").read_text(encoding="utf-8"))
    assert kp.TABLE in man["write_tables"] and kp.RPC in man["rpc_functions"]
    sql = (ROOT / "migrations/2026-11-08_korea_premium_watch.sql").read_text(encoding="utf-8")
    assert f"function public.{kp.RPC}(p_from date, p_to date)" in sql
    assert all(f"  {c} " in sql for c in kp.WRITES_COLUMNS[kp.TABLE])
    assert "from src.data.signals.korea_premium_watch import run_once" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
