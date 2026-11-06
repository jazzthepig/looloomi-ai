"""政治 / 地缘强度(11-06):GPR 与 GDELT 解析、可得日、批量请求、接线。"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import political_intensity as pi  # noqa: E402


def test_gpr_rows_use_availability_date():
    df = pd.DataFrame([{"DAY": 20261102, "GPRD": 97.6, "GPRD_ACT": 113.5, "GPRD_THREAT": float("nan")}, {"DAY": "bad"}])
    rows = pi.gpr_rows(df)
    assert {r["series"] for r in rows} == {"gpr", "gpr_act"} and all(r["d"] == "2026-11-07" for r in rows)


def test_gdelt_rows():
    payload = {"timeline": [{"data": [{"date": "20261104T000000Z", "value": 8.0}, {"date": "x"}]}]}
    assert pi.gdelt_rows(payload, "conflict") == [{"d": "2026-11-05", "topic": "conflict", "value": 8.0, "source": "gdelt_doc_timelinevol"}]
    assert pi.gdelt_rows({}, "conflict") == []


def test_run_once_one_request_per_topic_plus_one_file(monkeypatch):
    calls, written = [], []

    def get(u):
        calls.append(u)
        if u == pi.GPR_URL:
            raise RuntimeError("no xls in test")              # GPR 失败不挡 GDELT
        return json.dumps({"timeline": [{"data": [{"date": "20261104T000000Z", "value": 1.0}]}]}).encode()

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    async def read_all(table, params):
        return [{"topic": "conflict", "d": "2026-11-04"}, {"topic": "conflict", "d": "2026-10-01"}]

    import src.api.store as store
    import src.data.style.header as header
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(header, "_read_all", read_all)
    r = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), get=get, pause_s=0))
    assert len(calls) == 1 + len(pi.TOPICS) and "gpr" in r["failed"] and len(r["gdelt"]) == len(pi.TOPICS)
    conflict_url = [u for u in calls if "war" in u][0]
    assert "startdatetime=20261020" in conflict_url, "库里有就只取最近 15 天(取最新那条,不是最旧)"


def test_wiring():
    assert "async def _political_intensity_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "xlrd" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    from src.data.market import cis_inputs as ci
    from src.data.market import prediction_markets as pm
    assert "USEPUINDXD" in ci.CREDIT_SERIES and "politics" in pm.TAGS and len(pm.TAGS) <= 6
