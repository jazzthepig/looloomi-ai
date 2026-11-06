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


class _RD:
    def __init__(self, rows):
        self.ok, self.rows, self.reason = True, rows, None


def _patch(monkeypatch, last: dict, written: list):
    import src.api.store as store
    import src.data.vector.market_state_writer as msw

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    async def sb_get(table, params):
        t = params["topic"].removeprefix("eq.")
        return _RD([{"d": last[t]}] if t in last else [])

    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(msw, "_sb_get", sb_get)


def test_due_topics_rotates_missing_first_then_oldest():
    today = dt.date(2026, 11, 6)
    last = {"conflict": "2026-11-07", "sanctions": "2026-10-01", "trade_war": "2026-11-01"}
    assert pi.due_topics(last, today) == ["election_unrest", "crypto_policy"][:pi.GDELT_PER_ROUND]
    full = {t: "2026-11-07" for t in pi.TOPICS}
    assert pi.due_topics(full, today) == [], "到最新可得日的不再请求"
    assert pi.due_topics({**full, "sanctions": "2026-10-01", "trade_war": "2026-11-01"}, today) == ["sanctions", "trade_war"]


def test_run_once_one_file_plus_at_most_two_topics(monkeypatch):
    calls, written = [], []

    def get(u):
        calls.append(u)
        if u == pi.GPR_URL:
            raise RuntimeError("no xls in test")              # GPR 失败不挡 GDELT
        return json.dumps({"timeline": [{"data": [{"date": "20261104T000000Z", "value": 1.0}]}]}).encode()

    last = {t: "2026-11-07" for t in pi.TOPICS} | {"conflict": "2026-11-04"}
    _patch(monkeypatch, last, written)
    r = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 6, tzinfo=dt.timezone.utc), get=get, pause_s=0))
    assert len(calls) == 2 and "gpr" in r["failed"] and list(r["gdelt"]) == ["conflict"]
    assert "startdatetime=20261020" in calls[1], "库里有就只取最近 15 天(取最新那条)"


def test_wiring():
    assert "async def _political_intensity_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "xlrd" in (ROOT / "requirements.txt").read_text(encoding="utf-8")
    from src.data.market import cis_inputs as ci
    from src.data.market import prediction_markets as pm
    assert "USEPUINDXD" in ci.CREDIT_SERIES and "politics" in pm.TAGS and len(pm.TAGS) <= 6


def test_gdelt_throttle_is_retried_not_parsed(monkeypatch):
    assert pi.throttled(b"Please limit requests to one every 5 seconds or contact ...") and not pi.throttled(b'{"timeline": []}')
    calls, written = [], []
    payload = b'{"timeline": [{"data": [{"date": "20261104T000000Z", "value": 8.0}]}]}'

    def get(url):
        calls.append(url)
        if url == pi.GPR_URL:
            raise RuntimeError("no xls in test")
        return b"Please limit requests to one every 5 seconds" if len(calls) % 2 == 0 else payload

    _patch(monkeypatch, {}, written)
    r = asyncio.run(pi.run_once(get=get, pause_s=0))
    assert len(r["gdelt"]) == pi.GDELT_PER_ROUND and not [k for k in r["failed"] if k != "gpr"], r
