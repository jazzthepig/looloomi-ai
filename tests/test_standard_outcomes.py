"""S-540 — 档位历史表现只从正式序列算:每个 (名字, 日) 的 30 日结果,基准 BTC / SPY,风险带用基准过去 30 日。"""
from __future__ import annotations

import pandas as pd

from src.data.cis.standard_outcomes import COLUMNS, outcome_rows

TRADFI = frozenset({"US Equity"})


def _px(start: str, vals: list[float]) -> pd.Series:
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"), dtype=float)


def test_outcomes_use_d_close_to_d_plus_30_and_the_right_benchmark():
    n = 80
    closes = {"BTC": _px("2026-01-01", [100.0 + i for i in range(n)]),
              "X": _px("2026-01-01", [10.0 * (1.01 ** i) for i in range(n)]),
              "SPY": _px("2026-01-01", [500.0] * n), "QQQ": _px("2026-01-01", [400.0 + i for i in range(n)])}
    classes = {"BTC": "L1", "X": "L1", "SPY": "US Equity", "QQQ": "US Equity"}
    pts = {"X": [{"d": "2026-02-01", "signal": "OUTPERFORM", "grade": "B", "provenance": "reconstructed"},
                 {"d": "2026-03-10", "signal": "NEUTRAL", "grade": "B", "provenance": "published"}],
           "QQQ": [{"d": "2026-02-01", "signal": "NEUTRAL", "grade": "C", "provenance": "published"}]}
    rows = outcome_rows(pts, closes, classes, TRADFI, closes["BTC"].index.max())
    assert all(set(r) == set(COLUMNS) for r in rows)
    x = [r for r in rows if r["symbol"] == "X"]
    assert len(x) == 1, "03-10 + 30 天还没到 → 不出"
    d = pd.Timestamp("2026-02-01")
    a = closes["X"][d + pd.Timedelta(days=30)] / closes["X"][d] - 1
    b = closes["BTC"][d + pd.Timedelta(days=30)] / closes["BTC"][d] - 1
    assert x[0]["bench"] == "BTC" and abs(x[0]["a_ret"] - round(a, 6)) < 1e-9 and abs(x[0]["alpha"] - round(a - b, 6)) < 1e-9
    bt = closes["BTC"][d] / closes["BTC"][d - pd.Timedelta(days=30)] - 1
    assert abs(x[0]["bench_trail_30d"] - round(bt, 6)) < 1e-9
    q = [r for r in rows if r["symbol"] == "QQQ"][0]
    assert q["bench"] == "SPY" and q["grp"] == "tradfi" and q["panel_fwd_30d"] is None
    assert x[0]["provenance"] == "reconstructed"


def test_rpcs_aggregate_from_the_standard_outcomes_table():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "scripts/supabase_s540_standard_outcomes.sql").read_text()
    for fn in ("refresh_signal_track_record", "refresh_signal_edge_map"):
        body = sql[sql.index(f"function public.{fn}()"):]
        body = body[:body.index("$function$;")]
        assert "from cis_standard_outcomes" in body and "cis_scores" not in body and "signal_outcomes_unified" not in body
