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


def test_lane_scenario_files_are_ingested_once_with_the_file_author(monkeypatch, tmp_path):
    """S-705:lane 的前向预期以 docs/research/scenarios/<lane>-T-NNN.json 进 PR,合并后入账;作者认文件、不认正文;
    已入账的 id 不重写;结算日没留余量的只报不写;author 不合格的整文件不写。"""
    import json
    import src.api.store as store
    import src.data.style.header as hdr
    d = tmp_path / sl.SCENARIO_DIR
    d.mkdir(parents=True)
    (d / "lane-a-T-222.json").write_text(json.dumps({"author": "lane-a", "entries": [
        {"id": "T-222-1", "author": "jazz", "scenario": "s", "statement": "x", "variable": "close:BTC", "op": "gt", "lo": 1,
         "prob": 0.6, "horizon_d": "2026-12-01"},
        {"id": "T-222-2", "scenario": "s", "statement": "y", "variable": "manual", "op": "gt", "lo": 1, "prob": 0.4,
         "horizon_d": "2026-11-01"},
        {"id": "E53", "scenario": "s", "statement": "dup", "variable": "manual", "op": "gt", "lo": 1, "prob": 0.5,
         "horizon_d": "2026-12-01"}]}), encoding="utf-8")
    (d / "bad.json").write_text(json.dumps({"author": "lane-z", "entries": []}), encoding="utf-8")
    ins = []

    async def read_all(t, params):
        assert t == sl.TABLE
        return [{"id": "E53"}]

    async def insert(t, rows):
        ins.extend(rows)
        return type("R", (), {"ok": True, "why": ""})()
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_insert_table", insert)
    r = asyncio.run(sl.ingest_repo(dt.date(2026, 11, 3), root=str(tmp_path)))
    assert r["files"] == 2 and r["written"] == 1
    assert [x["id"] for x in ins] == ["T-222-1"] and ins[0]["author"] == "lane-a", "作者取文件,正文里的 jazz 不算"
    assert any("T-222-2" in s and "horizon_d" in s for s in r["skipped"]) and any("lane-z" in s for s in r["skipped"])
    assert (Path(sl.SCENARIO_DIR) / "README.md").exists(), "格式说明就放在目录里,lane 不用去读别的"


# ── 11-12 人工命题的结算:之前没有这条路(628 条里 285 条 manual,永远不会被打分)──────────────────────────
def _manual(author="lane-c", op="gt", lo=1.0, hi=None, prob=0.8, h="2026-11-21"):
    return {"id": "T-1-4", "author": author, "variable": "manual", "op": op, "lo": lo, "hi": hi, "prob": prob, "horizon_d": h}


def test_manual_settlement_outcome_comes_from_the_registered_rule_not_from_the_settler():
    today = dt.date(2026, 11, 25)
    row, why = sl.settle_manual(_manual(), {"id": "T-1-4", "observed": 0.97, "evidence": "docs/research/t9.py → ratio 0.97", "outcome": True},
                                "lane-b", today)
    assert why is None and row["outcome"] is False and row["brier"] == pytest.approx(0.64), "结算人写 outcome=True 不算数;0.97 不 > 1.0"
    assert "lane-b" in row["note"] and row["code_ref"] == sl.CODE_REF_MANUAL
    row, _ = sl.settle_manual(_manual(), {"id": "T-1-4", "observed": 1.2, "evidence": "docs/research/t9.py → ratio 1.2"}, "seth", today)
    assert row["outcome"] is True and row["brier"] == pytest.approx(0.04)


def test_nobody_settles_their_own_and_nothing_settles_early_or_without_evidence():
    today = dt.date(2026, 11, 25)
    ok = {"id": "T-1-4", "observed": 1.2, "evidence": "docs/research/t9.py → ratio 1.2"}
    assert "自己" in sl.settle_manual(_manual("lane-c"), ok, "lane-c", today)[1]
    assert "自己" in sl.settle_manual(_manual("seth:cycle-space"), ok, "seth", today)[1]
    assert sl.settle_manual(_manual("seth:cycle-space"), ok, "lane-a", today)[0] is not None
    assert "还没过" in sl.settle_manual(_manual(h="2026-11-25"), ok, "lane-b", today)[1]
    assert "evidence" in sl.settle_manual(_manual(), {**ok, "evidence": "看了"}, "lane-b", today)[1]
    assert "observed" in sl.settle_manual(_manual(), {**ok, "observed": "大概是"}, "lane-b", today)[1]
    assert "不是 manual" in sl.settle_manual({**_manual(), "variable": "close:BTC"}, ok, "lane-b", today)[1]
    assert "没有这条" in sl.settle_manual(None, ok, "lane-b", today)[1]
    assert "不认" in sl.settle_manual(_manual(), ok, "someone", today)[1]


def test_open_manual_counts_what_is_waiting_for_a_settler_by_party():
    today = dt.date(2026, 11, 25)
    es = [{**_manual("lane-c"), "id": "a"}, {**_manual("lane-c", h="2026-12-10"), "id": "b"}, {**_manual("seth:x", h="2027-03-01"), "id": "c"},
          {**_manual("lane-c"), "id": "d"}, {**_manual(), "id": "e", "variable": "close:BTC"}]
    got = sl.open_manual(es, {"d": {"outcome": True}}, today)
    assert got == {"lane-c": {"overdue": 1, "due_30d": 1, "later": 0}, "seth": {"overdue": 0, "due_30d": 0, "later": 1}}


def test_settlement_files_live_in_their_own_folder_and_are_not_read_as_scenarios(tmp_path):
    import json
    d = tmp_path / sl.SETTLE_DIR
    d.mkdir(parents=True)
    (d / "lane-b-2026-11-25.json").write_text(json.dumps({"settled_by": "lane-b", "settlements": [{"id": "T-1-4", "observed": 1.2, "evidence": "x" * 20}]}))
    (d / "bad.json").write_text("{not json")
    recs = sl.settlement_files(str(tmp_path))
    assert [r["file"] for r in recs] == ["bad.json", "lane-b-2026-11-25.json"] and recs[0]["problems"] and recs[1]["settled_by"] == "lane-b"
    assert sl.repo_files(str(tmp_path)) == [], "结算文件夹不被当成情景文件"


def test_path_propositions_validate_and_settle_on_hourly_bars_after_they_were_written(monkeypatch):
    """T-409:「周一 13:00 前碰到 1,834」这类走法命题。写下之前的小时不算(否则写的时候就已经知道答案)。"""
    import src.api.store as store
    import src.data.style.header as hdr
    assert sl.validate({**_e(variable="high:ETH@13", op="gt", lo=1834, hi=None), "author": "seth:x"}, TODAY) == []
    assert sl.validate({**_e(variable="low:BTC", op="lt", lo=None, hi=62006), "author": "seth:x"}, TODAY) == []
    assert any("HH" in w for w in sl.validate({**_e(variable="high:ETH@25", op="gt", lo=1), "author": "x"}, TODAY))
    sym, start, end = sl.path_window("ETH@13", "2026-11-16", "2026-11-15T07:20:05+00:00")
    assert sym == "ETH" and start == dt.datetime(2026, 11, 15, 8, tzinfo=dt.timezone.utc) and end == dt.datetime(2026, 11, 16, 13, tzinfo=dt.timezone.utc)
    assert sl.path_window("ETH", "2026-11-16", "2026-11-15T07:00:00+00:00")[1:] == (
        dt.datetime(2026, 11, 15, 7, tzinfo=dt.timezone.utc), dt.datetime(2026, 11, 17, 0, tzinfo=dt.timezone.utc))
    up, asked = [], []
    bars = [{"ts": f"2026-11-{15 + (h // 24):02d}T{h % 24:02d}:00:00+00:00", "high": 1800 + h, "low": 1790 - h} for h in range(8, 24 + 13)]

    async def read_all(t, params):
        if t == sl.TABLE:
            return [{"id": "W1", "variable": "high:ETH@13", "op": "gt", "lo": 1834, "hi": None, "prob": 0.7,
                     "horizon_d": "2026-11-16", "written_at": "2026-11-15T07:20:05+00:00"}]
        if t == sl.SCORES:
            return []
        if t == "ohlcv_hourly":
            asked.append(params)
            return bars
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(sl.run_once(dt.datetime(2026, 11, 17, 1, 0, tzinfo=dt.timezone.utc)))
    assert r["scored"] == 1 and up[0]["observed"] == 1800 + 36 and up[0]["outcome"] is True
    assert "ts.gte.2026-11-15T08:00:00+00:00" in asked[0]["and"] and "ts.lt.2026-11-16T13:00:00+00:00" in asked[0]["and"]
    bars[:] = bars[:-3]                                                  # 小时线还没到截止时刻 ⇒ 等值,不结
    up.clear()
    r = asyncio.run(sl.run_once(dt.datetime(2026, 11, 17, 1, 0, tzinfo=dt.timezone.utc)))
    assert r["scored"] == 0 and r["waiting"] == 1


# ── 11-23 作废层(T-427):「这条登记本身是错的」—— 结算之外的第三类记录 ───────────────────────────────
def _voided(sid="T-417-1", reason="defective_threshold", evidence="docs/research/t417_audit.py → 81,200 是 BO20 触发价",
            sup=""):
    v = {"id": sid, "reason": reason, "evidence": evidence}
    if sup:
        v["superseded_by"] = sup
    return v


def test_void_reason_is_a_closed_set_and_refutation_is_not_one_of_them():
    """作废 ≠ 结算:闭集里没有一个 reason 能表达「命题被证伪」—— 那只能走结算。"""
    assert sl.VOID_REASONS == ("defective_threshold", "defective_base_rate", "complement_pair",
                               "not_machine_checkable", "duplicate_id", "superseded")
    entry = {"id": "T-417-1", "author": "lane-c"}
    r = sl.void_marker(_voided(reason="falsified"), entry, False, "seth")
    assert r["status"] == "rejected" and "不在闭集" in r["why"] and "结算" in r["why"], "被证伪只能走结算"
    r = sl.void_marker(_voided(reason="defective_threshold"), entry, False, "seth")
    assert r["status"] == "ok", r["why"]
    assert r["row"]["observed"] is None and r["row"]["outcome"] is None and r["row"]["brier"] is None, "作废行三列全空"
    assert sl.is_void(r["row"]) and r["row"]["note"].startswith(sl.VOID_NOTE_PREFIX)


def test_a_note_that_merely_mentions_a_void_is_not_a_void_row():
    """负控制:不做自由文本匹配 —— 说明文字里出现「作废」两个字,不该把结算行变成作废行。"""
    row = {"id": "x", "note": "结算日 2026-12-01 过了 7 天仍读不到 state:dist_200 —— 不当成假(登记错误待作废)"}
    assert not sl.is_void(row)
    assert sl.is_void({"id": "x", "note": sl.VOID_NOTE_PREFIX + "seth · duplicate_id · 证据"})
    assert not sl.is_void(None) and not sl.is_void("作废 · seth")


def test_nobody_voids_their_own_and_no_lane_can_void_anybody():
    entry = {"id": "T-417-1", "author": "lane-c"}
    r = sl.void_marker(_voided(), {"id": "T-1", "author": "seth:weekly"}, False, "seth:cycle-space")
    assert r["status"] == "rejected" and "自己" in r["why"], "seth 不能作废 seth 自己写的"
    r = sl.void_marker(_voided(), entry, False, "lane-c")
    assert r["status"] == "rejected" and "不认" in r["why"], "lane 不能作废任何人的条目(否则能把自己的失败样本拿掉)"
    assert sl.void_marker(_voided(), entry, False, "seth")["status"] == "ok"
    assert sl.void_marker(_voided(), entry, False, "jazz")["status"] == "ok"
    for who in ("ai:MiniMax-M3", "ai:lane-b-T-999"):
        r = sl.void_marker(_voided(), entry, False, who)
        assert r["status"] == "rejected" and "不认" in r["why"], f"{who}:lane 能自称 ai:,不能靠它作废(§Seth-1123x)"


def test_a_settled_entry_cannot_be_voided_and_a_missing_one_is_only_named():
    entry = {"id": "T-417-1", "author": "lane-c"}
    r = sl.void_marker(_voided(), entry, True, "seth")
    assert r["status"] == "rejected" and "已结" in r["why"], "结算是不可改的历史事实"
    r = sl.void_marker(_voided(sid="T-420-P1"), None, False, "seth")
    assert r["status"] == "not_in_ledger" and r["row"] is None and "只点名" in r["why"]


def test_superseded_needs_the_new_id():
    entry = {"id": "T-375-1", "author": "lane-a"}
    r = sl.void_marker(_voided(reason="superseded"), entry, False, "seth")
    assert r["status"] == "rejected" and "superseded_by" in r["why"]
    r = sl.void_marker(_voided(reason="superseded", sup="T-381-1"), entry, False, "seth")
    assert r["status"] == "ok" and "T-381-1" in r["row"]["note"]
    assert sl.void_marker(_voided(sid="T-375-1", reason="superseded", sup="T-375-1"), entry, False, "seth")["status"] == "rejected"


def test_void_files_live_in_their_own_folder_and_are_not_read_as_scenarios(tmp_path):
    """目录隔离:`repo_files()` 是 `SCENARIO_DIR.glob("*.json")`(非递归)⇒ `voids/` 里的文件不会被当成情景文件读进来。"""
    import json
    for sub in (sl.SCENARIO_DIR, sl.VOID_DIR, sl.SETTLE_DIR):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / sl.SCENARIO_DIR / "lane-a-T-1.json").write_text(json.dumps({"author": "lane-a", "entries": []}), encoding="utf-8")
    (tmp_path / sl.VOID_DIR / "seth-2026-11-23.json").write_text(json.dumps(
        {"voided_by": "seth", "voids": [{"id": "T-1-1", "reason": "superseded", "evidence": "e" * 20,
                                        "superseded_by": "T-2-1"}]}), encoding="utf-8")
    (tmp_path / sl.VOID_DIR / "bad.json").write_text("{not json", encoding="utf-8")
    recs = sl.void_files(str(tmp_path))
    assert [r["file"] for r in recs] == ["bad.json", "seth-2026-11-23.json"]
    assert recs[0]["problems"] and recs[1]["voided_by"] == "seth" and recs[1]["voids"][0]["id"] == "T-1-1"
    assert [r["file"] for r in sl.repo_files(str(tmp_path))] == ["lane-a-T-1.json"], "voids/ 不被当成情景文件"
    assert sl.settlement_files(str(tmp_path)) == [], "voids/ 也不被当成结算记录"


def test_apply_voids_writes_markers_names_the_missing_and_is_idempotent(monkeypatch, tmp_path):
    import json
    import src.api.store as store
    import src.data.style.header as hdr
    d = tmp_path / sl.VOID_DIR
    d.mkdir(parents=True)
    (d / "seth-2026-11-23.json").write_text(json.dumps({"voided_by": "seth", "voids": [
        {"id": "T-417-1", "reason": "defective_threshold", "evidence": "x" * 30},
        {"id": "T-420-P1", "reason": "not_machine_checkable", "evidence": "y" * 30},
        {"id": "T-375-1", "reason": "superseded", "evidence": "z" * 30, "superseded_by": "T-381-1"}]}), encoding="utf-8")
    state: dict[str, dict] = {}
    up = []

    async def read_all(t, params):
        if t == sl.TABLE:
            return [{"id": "T-417-1", "author": "lane-c"}, {"id": "T-375-1", "author": "lane-a"}]
        if t == sl.SCORES:
            return list(state.values())
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        assert t == sl.SCORES, "台账一行都不许动"
        for x in rows:
            state[x["id"]] = x
        up.extend(rows)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(sl.apply_voids(dt.date(2026, 11, 23), root=str(tmp_path)))
    assert sorted(r["written"]) == ["T-375-1", "T-417-1"], r
    assert [m["id"] for m in r["not_in_ledger"]] == ["T-420-P1"], "不在台账的只点名,不写行"
    assert "外键" in r["not_in_ledger"][0]["why"], "点名要说清为什么不能进库"
    assert r["rejected"] == [] and r["voided"] == 2
    assert [x["id"] for x in up] == ["T-417-1", "T-375-1"]
    assert all(x["outcome"] is None and x["brier"] is None and x["observed"] is None for x in up)
    assert "T-381-1" in up[1]["note"] and sl.is_void(up[1])
    up.clear()
    r2 = asyncio.run(sl.apply_voids(dt.date(2026, 11, 23), root=str(tmp_path)))
    assert up == [], "同一条记录跑两次不重写"
    assert r2["written"] == [] and r2["already"] == ["T-375-1", "T-417-1"] and r2["voided"] == 2, "幂等:结果一样"


def test_a_voided_entry_is_never_settled_never_calibrated_and_never_open(monkeypatch, tmp_path):
    """三个消费点的负控制:造一行作废标记 ⇒ 不被结算、不进校准、不进「该结了」。"""
    import json
    import src.api.store as store
    import src.data.style.header as hdr
    void_row = {"id": "T-1-4", "observed": None, "outcome": None, "brier": None,
                "note": sl.VOID_NOTE_PREFIX + "seth · defective_threshold · 登记时把触发价当现价",
                "code_ref": sl.CODE_REF_VOID}
    entry = {"id": "T-1-4", "author": "lane-c", "variable": "manual", "op": "gt", "lo": 1.0, "hi": None,
             "prob": 0.8, "horizon_d": "2026-11-21"}
    today = dt.date(2026, 11, 25)
    assert sl.open_manual([entry], {"T-1-4": void_row}, today) == {}, "作废的条目不进「该结了」"
    assert sl.calibration([entry], {"T-1-4": void_row}) == {}, "作废的条目不进校准(n / hit_rate / buckets)"

    # (1) 人工结算不覆盖作废行
    sd = tmp_path / sl.SETTLE_DIR
    sd.mkdir(parents=True)
    (sd / "lane-b-2026-11-25.json").write_text(json.dumps(
        {"settled_by": "lane-b", "settlements": [{"id": "T-1-4", "observed": 1.2, "evidence": "x" * 20}]}), encoding="utf-8")
    score_rows = [void_row]
    up = []

    async def read_all(t, params):
        if t == sl.TABLE:
            return [dict(entry)]
        if t == sl.SCORES:
            if params.get("outcome") == "not.is.null":
                return [{"id": r["id"]} for r in score_rows if r.get("outcome") is not None]
            return list(score_rows)
        raise AssertionError(t)

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    r = asyncio.run(sl.apply_settlements(today, root=str(tmp_path)))
    assert r["settled"] == 0 and up == [], "作废的条目不被人工结算"
    assert r["skipped_void"] == ["T-1-4"]

    # (2) 自动结算不覆盖作废行(到期那天也不会)
    up.clear()
    ledger = [{"id": "T-9-1", "variable": "close:BTC", "op": "gt", "lo": 1, "hi": None, "prob": 0.7,
               "horizon_d": "2026-11-09"}]
    void_auto = {"id": "T-9-1", "observed": None, "outcome": None, "brier": None,
                 "note": sl.VOID_NOTE_PREFIX + "seth · defective_threshold · 登记时把触发价当现价",
                 "code_ref": sl.CODE_REF_VOID}

    async def read_all2(t, params):
        if t == sl.TABLE:
            return ledger
        if t == sl.SCORES:
            if params.get("outcome") == "not.is.null":
                return [{"id": r["id"]} for r in [void_auto] if r.get("outcome") is not None]
            return [void_auto]
        if t == "ohlcv_daily":
            return [{"close": 80123.0}] if params["source"] == "eq.binance_hist" else []
        raise AssertionError(t)

    async def ins(t, rows):
        return type("R", (), {"ok": False, "why": "测试里不写台账"})()
    monkeypatch.setattr(hdr, "_read_all", read_all2)
    monkeypatch.setattr(store, "supabase_insert_table", ins)
    r = asyncio.run(sl.run_once(dt.datetime(2026, 11, 10, 1, 0, tzinfo=dt.timezone.utc)))
    assert r["scored"] == 0 and up == [], "作废的条目不被自动结算覆盖"
    assert r["voids"]["voided"] == 0
