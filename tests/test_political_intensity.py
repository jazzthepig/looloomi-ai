"""政治 / 地缘强度(11-06):GPR 与 GDELT 解析、可得日、批量请求、接线。"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

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


@pytest.fixture(autouse=True)
def _gpr_clock_is_not_shared_between_tests():
    pi._GPR.update(at=0.0, max_d=None)
    yield
    pi._GPR.update(at=0.0, max_d=None)


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
    assert pi.due_topics(last, today) == ["election_unrest", "crypto_policy", "sanctions", "trade_war"][:pi.GDELT_PER_ROUND]      # 没有行的在前,其次最旧的
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

    last = {t: "2026-11-07" for t in pi.all_series()} | {"conflict": "2026-11-04"}
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


def test_market_narratives_ride_the_same_loop_with_volume_and_tone():
    """S-855:叙事(英伟达 / 加息 / 日元 …)每条两条序列 —— 量与调;政治五条不变;调的行来源标成 timelinetone。"""
    ser = pi.all_series()
    assert set(pi.TOPICS) <= set(ser) and all(ser[t][1] == "timelinevol" for t in pi.TOPICS)
    for t in pi.NARRATIVE_TOPICS:
        assert ser[t] == (pi.NARRATIVE_TOPICS[t], "timelinevol") and ser[t + pi.TONE_SUFFIX] == (pi.NARRATIVE_TOPICS[t], "timelinetone")
    assert len(ser) == len(pi.TOPICS) + 2 * len(pi.NARRATIVE_TOPICS) and {"ai_chips", "fed_hike", "boj_yen"} <= set(pi.NARRATIVE_TOPICS)
    today = dt.date(2026, 11, 13)
    last = {t: "2026-11-14" for t in ser} | {"ai_chips:tone": "2026-11-01"}
    del last["fed_hike"]
    assert pi.due_topics(last, today, ser) == ["fed_hike", "ai_chips:tone"], "没有行的排最前,其次最旧的"
    assert pi.due_topics({t: "2026-11-14" for t in pi.TOPICS}, today) == [], "不传 topics = 只看政治五条(旧行为)"
    rows = pi.gdelt_rows({"timeline": [{"data": [{"date": "20261112T000000Z", "value": -2.3456789}]}]}, "ai_chips:tone", "timelinetone")
    assert rows == [{"d": "2026-11-13", "topic": "ai_chips:tone", "value": -2.34568, "source": "gdelt_doc_timelinetone"}]


def test_an_empty_series_is_a_visible_failure_not_zero_rows(monkeypatch):
    """S-855 / 5b:调的那种模式若返回形状不同,循环要报不通,而不是安静地写 0 行。"""
    written = []

    def get(url):
        if url == pi.GPR_URL:
            raise RuntimeError("no xls in test")
        return b'{"timeline": []}' if "timelinetone" in url else b'{"timeline": [{"data": [{"date": "20261104T000000Z", "value": 8.0}]}]}'

    last = {t: "2026-11-14" for t in pi.all_series()} | {"ai_chips:tone": "2026-11-01", "conflict": "2026-11-02"}
    _patch(monkeypatch, last, written)
    r = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc), get=get, pause_s=0))
    assert r["ok"] is False and "ai_chips:tone" in r["failed"] and "没有序列" in r["failed"]["ai_chips:tone"]
    assert r["gdelt"] == {"conflict": 1}, "别的序列照常写"


def test_a_series_that_never_arrives_cannot_starve_the_rest():
    """S-855:21 条序列、每轮 3 条。队首三条若一直不通,不轮转的话其余 18 条永远没有行。"""
    ser, today = pi.all_series(), dt.date(2026, 11, 13)
    seen = set()
    for r in range(len(ser)):
        got = pi.due_topics({}, today, ser, rot=r * pi.GDELT_PER_ROUND)        # 库一直是空的 = 每一条都一直不通
        assert len(got) == pi.GDELT_PER_ROUND
        seen |= set(got)
    assert seen == set(ser), "每一条都轮得到"
    assert pi.due_topics({}, today, ser) == list(ser)[:pi.GDELT_PER_ROUND], "rot 缺省 = 原来的顺序"


def test_a_throttling_source_is_a_refusal_not_a_broken_loop_and_the_round_stops(monkeypatch):
    """11-14:13 小时里每一轮都是「不通」,看不出原因;其实是 GDELT 在限速。限速 ⇒ 记 refused、这一轮停手、原因写明。"""
    calls, written = [], []

    def always_throttled(url):
        calls.append(url)
        if url == pi.GPR_URL:
            raise RuntimeError("no xls in test")
        return b"Please limit requests to one every 5 seconds"
    _patch(monkeypatch, {}, written)
    r = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc), get=always_throttled, pause_s=0))
    gd = [c for c in calls if c != pi.GPR_URL]
    assert len(gd) == 1 + len(pi.GDELT_THROTTLE_WAITS), "只对第一条重试;被限速后不再请求后面两条"
    assert r["throttled"] and len(r["throttled"]) == pi.GDELT_PER_ROUND and not r["gdelt"] and not written
    assert set(r["failed"]) == {"gpr"} and r["ok"] is False and r["refused"] is False, "GPR 文件读不到是硬失败,照旧报错"

    def gpr_ok_then_throttle(url):
        if url == pi.GPR_URL:
            raise RuntimeError("no xls in test")
        return b"Please limit requests to one every 5 seconds"
    monkeypatch.setattr(pi, "gpr_rows", lambda df: [])
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *_a, **_k: pd.DataFrame())
    r2 = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc), get=lambda u: b"x" if u == pi.GPR_URL else b"Please limit requests", pause_s=0))
    assert r2["failed"] is None and r2["ok"] is False and r2["refused"] is True, r2
    assert "被限速" in r2["why"] and "还落后" in r2["why"] and r2["behind"] == len(pi.all_series())

    def http_429(url):
        if url == pi.GPR_URL:
            return b"x"
        raise RuntimeError("HTTP Error 429: Too Many Requests")
    r3 = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc), get=http_429, pause_s=0))
    assert r3["refused"] is True and r3["failed"] is None and len(r3["throttled"]) == pi.GDELT_PER_ROUND


def test_a_hard_failure_names_its_reason_and_partial_progress_is_ok(monkeypatch):
    written = []
    n = {"i": 0}

    def get(url):
        if url == pi.GPR_URL:
            return b"x"
        n["i"] += 1
        if n["i"] == 1:
            return b'{"timeline": [{"data": [{"date": "20261112T000000Z", "value": 1.0}]}]}'
        if n["i"] == 2:
            return b'{"timeline": []}'
        return b"Please limit requests to one every 5 seconds"
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *_a, **_k: pd.DataFrame())
    monkeypatch.setattr(pi, "gpr_rows", lambda df: [])
    _patch(monkeypatch, {}, written)
    r = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc), get=get, pause_s=0))
    assert len(r["gdelt"]) == 1 and len(r["failed"]) == 1 and len(r["throttled"]) == pi.GDELT_PER_ROUND - 2
    assert r["ok"] is False and r["refused"] is False and "没有序列" in r["why"], "有硬失败 ⇒ 报错,原因写在 why 里"


def test_the_rhythm_is_many_small_looks_and_an_open_window_is_used(monkeypatch):
    """S-863。原来一天 8 轮、每轮最多落一条,21 条序列轮不过来。现在 20 分钟看一次:被限速就收工(一轮 ≤ 3 次请求),
    通了就接着取到 GDELT_PER_ROUND 条。"""
    from src.data.market.source_policy import BULK_THRESHOLD
    assert pi.GDELT_TICK_S <= 1800 and len(pi.GDELT_THROTTLE_WAITS) <= 2 and max(pi.GDELT_THROTTLE_WAITS) <= 30
    assert pi.GDELT_PER_ROUND <= BULK_THRESHOLD, "一轮的请求数不能越过免费源的闸"
    assert pi.GDELT_PAUSE_S >= 5, "源的规矩:每 5 秒最多一次"
    assert 86400 // pi.GDELT_TICK_S * (1 + len(pi.GDELT_THROTTLE_WAITS)) <= 300, "全天都被限速时,请求总数要有上限"
    written, calls = [], []
    payload = b'{"timeline": [{"data": [{"date": "20261113T000000Z", "value": 2.0}]}]}'

    def open_window(url):
        calls.append(url)
        if url == pi.GPR_URL:
            raise RuntimeError("no xls in test")
        return payload
    _patch(monkeypatch, {}, written)
    r = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 14, 13, 0, tzinfo=dt.timezone.utc), get=open_window, pause_s=0))
    assert len(r["gdelt"]) == pi.GDELT_PER_ROUND and r["requests"] == pi.GDELT_PER_ROUND and not r["throttled"]
    first_a = list(r["gdelt"])[0]
    r_next = asyncio.run(pi.run_once(now=dt.datetime(2026, 11, 14, 13, 20, tzinfo=dt.timezone.utc), get=open_window, pause_s=0))
    assert list(r_next["gdelt"])[0] != first_a, "下一轮从下一条开始 —— 一条坏的查询不会一直占着队首"
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    i = src.index("async def _political_intensity_loop")
    assert "GDELT_TICK_S" in src[i:src.index("@app.on_event", i)], "循环的间隔跟着模块里的常数走"


def test_gpr_is_fetched_twice_a_day_not_every_look(monkeypatch):
    """GPR 是 45,000 多行的日更文件;原来每一轮整份下载、整份写。看得勤了之后:12 小时一次,同一进程里第二次起只写最近 45 天。"""
    import pandas as pd
    written, gpr_calls = [], []
    rows_all = [{"series": "gpr", "d": (dt.date(2026, 1, 1) + dt.timedelta(days=i)).isoformat(), "value": 1.0, "source": "x"} for i in range(300)]
    monkeypatch.setattr(pd, "read_excel", lambda *_a, **_k: pd.DataFrame())
    monkeypatch.setattr(pi, "gpr_rows", lambda df: list(rows_all))

    def get(url):
        if url == pi.GPR_URL:
            gpr_calls.append(url)
            return b"x"
        return b"Please limit requests to one every 5 seconds"
    _patch(monkeypatch, {}, written)
    now = dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc)
    r1 = asyncio.run(pi.run_once(now=now, get=get, pause_s=0))
    assert r1["gpr"] == 300 and len(gpr_calls) == 1
    r2 = asyncio.run(pi.run_once(now=now, get=get, pause_s=0))
    assert r2["gpr"] is None and len(gpr_calls) == 1 and "GPR" not in r2["why"], "12 小时内不再取,也不在 why 里冒充取过"
    pi._GPR["at"] = 0.0                                   # 12 小时过去了
    written.clear()
    r3 = asyncio.run(pi.run_once(now=now, get=get, pause_s=0))
    assert len(gpr_calls) == 2 and r3["gpr"] == pi.GPR_REWRITE_DAYS + 1 == len(written), "第二次只写最近 45 天"
