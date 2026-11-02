"""情景台账(11-02):事前写下(结算日晚于今天)、只追加、机器能核的命题自动结算、读不到不当成假、按作者校准。"""
import asyncio
import datetime as dt
from pathlib import Path

import pytest

from src.data.evaluation import scenario_ledger as sl

TODAY = dt.date(2026, 11, 2)


def _e(**kw):
    e = {"id": "E53", "scenario": "S1 压缩继续", "statement": "BTC 11-09 收盘在 74k–86k", "variable": "close:BTC",
         "op": "between", "lo": 74000, "hi": 86000, "prob": 0.7, "horizon_d": "2026-11-09"}
    return {**e, **kw}


def test_validate_requires_an_ex_ante_machine_checkable_proposition():
    assert sl.validate({**_e(), "author": "seth:weekly"}, TODAY) == []
    assert any("晚于今天" in w for w in sl.validate({**_e(horizon_d="2026-11-02"), "author": "x"}, TODAY)), "结算日不能是今天"
    assert any("lo ≤ hi" in w for w in sl.validate({**_e(lo=90000), "author": "x"}, TODAY))
    assert any("prob" in w for w in sl.validate({**_e(prob=1.2), "author": "x"}, TODAY))
    assert any("认不出" in w for w in sl.validate({**_e(variable="price:BTC"), "author": "x"}, TODAY))
    assert sl.validate({**_e(variable="manual", op="gt", lo=0), "author": "x"}, TODAY) == []
    assert any("id" in w for w in sl.validate({**_e(id="bad id!"), "author": "x"}, TODAY))


def test_scoring_brier_and_late_values_are_not_false():
    e = {**_e(), "author": "seth:weekly"}
    assert sl.score(e, 80000.0, dt.date(2026, 11, 9)) is None, "结算日当天还不结(收盘可能没落库)"
    s = sl.score(e, 80000.0, dt.date(2026, 11, 10))
    assert s["outcome"] is True and s["brier"] == pytest.approx(0.09)
    s = sl.score(e, 90000.0, dt.date(2026, 11, 10))
    assert s["outcome"] is False and s["brier"] == pytest.approx(0.49)
    assert sl.score(e, None, dt.date(2026, 11, 12)) is None, "宽限 7 天内等值"
    late = sl.score(e, None, dt.date(2026, 11, 20))
    assert late["outcome"] is None and "不当成假" in late["note"]
    assert sl.holds("gt", 0.05, None, 0.051) and not sl.holds("lt", None, 0.05, 0.051)


def test_calibration_by_author():
    entries = [{"id": "a", "author": "seth:weekly", "prob": 0.7}, {"id": "b", "author": "seth:weekly", "prob": 0.7},
               {"id": "c", "author": "lane-a:x", "prob": 0.2}, {"id": "d", "author": "seth:weekly", "prob": 0.5}]
    scores = {"a": {"outcome": True, "brier": 0.09}, "b": {"outcome": False, "brier": 0.49},
              "c": {"outcome": False, "brier": 0.04}, "d": {"outcome": None, "brier": None}}
    c = sl.calibration(entries, scores)
    assert c["seth:weekly"]["n"] == 2 and c["seth:weekly"]["mean_brier"] == pytest.approx(0.29)
    assert c["seth:weekly"]["buckets"]["60-80%"] == {"n": 2, "true": 1} and c["lane-a:x"]["hit_rate"] == 0.0


def test_submit_rejects_the_whole_batch_on_any_problem(monkeypatch):
    import src.api.store as store
    written = []

    class R:
        ok, why = True, None

    async def ins(t, rows):
        written.extend(rows)
        return R()
    monkeypatch.setattr(store, "supabase_insert_table", ins)
    now = dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.timezone.utc)
    bad = asyncio.run(sl.submit([_e(), _e(id="E54", prob=2)], "seth:weekly", now))
    assert not bad["ok"] and "E54" in bad["problems"] and written == []
    dup = asyncio.run(sl.submit([_e(), _e()], "seth:weekly", now))
    assert not dup["ok"] and "_batch" in dup["problems"]
    ok = asyncio.run(sl.submit([_e(), _e(id="E54", variable="state:breadth_above_ma50", op="gt", lo=0.05, hi=None)],
                               "seth:weekly", now))
    assert ok["ok"] and [r["id"] for r in written] == ["E53", "E54"] and written[0]["author"] == "seth:weekly"


def test_run_once_scores_due_rows_once(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    up = []

    async def read_all(t, params):
        if t == sl.TABLE:
            return [{"id": "E53", "variable": "close:BTC", "op": "between", "lo": 74000, "hi": 86000, "prob": 0.7,
                     "horizon_d": "2026-11-09"}]
        if t == sl.SCORES:
            return [{"id": r["id"]} for r in up if r.get("outcome") is not None]
        if t == "ohlcv_daily":
            return [{"close": 80123.0}] if params["source"] == "eq.binance_hist" else []
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(sl.run_once(dt.datetime(2026, 11, 10, 1, 0, tzinfo=dt.timezone.utc)))
    assert r["scored"] == 1 and up[0]["outcome"] is True and up[0]["observed"] == 80123.0
    assert asyncio.run(sl.run_once(dt.datetime(2026, 11, 10, 2, 0, tzinfo=dt.timezone.utc)))["scored"] == 0, "结过的不再结"


def test_the_ledger_is_append_only_in_the_database_and_anchored():
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "2026-11-02_scenario_ledger.sql").read_text(encoding="utf-8")
    assert "append-only" in sql and "before insert or update or delete" in sql and "new.written_at := now()" in sql
    from src.data.accounting import anchor
    assert anchor.KEYS["scenario_ledger"] == "id" and "scenario_scores" not in anchor.KEYS, "命题锚定,打分可重算不锚"
