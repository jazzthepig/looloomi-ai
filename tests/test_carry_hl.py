"""S-733:HL 已实现小时费率采集 + ④ 套息纸面前向账。"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import hl_funding_hourly as hf  # noqa: E402
from src.data.signals import carry_hl as ch  # noqa: E402


def test_parse_page_keeps_good_rows_and_drops_bad_ones():
    raw = [{"coin": "BTC", "fundingRate": "0.0000125", "premium": "0.0003", "time": 1683849600000},
           {"coin": "BTC", "fundingRate": "x", "time": 1683853200000},
           {"coin": "ETH", "fundingRate": "0.00001", "time": 1683853200000},
           {"coin": "BTC", "fundingRate": "-0.00002", "time": 1683856800000}]
    rows = hf.parse_page(raw, "BTC")
    assert [r["rate"] for r in rows] == [0.0000125, -0.00002] and rows[0]["t"].startswith("2023-05-12T00:00:00")
    assert hf.parse_page({"error": 1}, "BTC") == [] and hf.next_start([], 5) is None
    assert hf.next_start(rows, 0) == 1683856800001 and hf.next_start(rows, 1683856800001) is None, "没前进就停"
    assert hf.start_for(None) == hf._ms(hf.BACKFILL_FROM) and hf.start_for("2026-11-05T10:00:00+00:00") == hf._ms("2026-11-05T10:00:00") + 1


def test_run_once_pages_until_short_page_and_names_the_failures(monkeypatch):
    calls, written = [], []

    def post(p):
        calls.append(p)
        if p["coin"] == "ETH":
            raise RuntimeError("429")
        base = p["startTime"]
        n = hf.PAGE if len([c for c in calls if c["coin"] == p["coin"]]) == 1 else 3
        return [{"coin": p["coin"], "fundingRate": "0.00001", "time": base + k * 3_600_000} for k in range(n)]

    async def read_all(table, params):
        return [{"coin": "BTC", "last_t": "2026-10-01T00:00:00+00:00"}]

    class W:
        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return W()

    import src.api.store as store
    import src.data.style.header as header
    monkeypatch.setattr(hf, "coins", lambda: ("BTC", "ETH"))
    monkeypatch.setattr(header, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    r = asyncio.run(hf.run_once(now=dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc), post=post, pause_s=0))
    btc = [c for c in calls if c["coin"] == "BTC"]
    assert len(btc) == 2 and btc[0]["startTime"] == hf.start_for("2026-10-01T00:00:00+00:00"), "从 last_t 往后,满页翻下一页,短页停"
    assert r["written"] == hf.PAGE + 3 and r["failed"] == {"ETH": "RuntimeError: 429"} and not r["ok"]
    assert all("_ms" not in w for w in written)


def _rows(names, d0, n_days, rate):
    return [{"coin": c, "d": (d0 + dt.timedelta(i)).isoformat(), "rate_sum": rate(c, i), "n_hours": 24} for c in names for i in range(n_days)]


def test_carry_a_earns_mean_funding_minus_one_entry_cost_and_starts_at_one():
    d0 = ch.INCEPTION - dt.timedelta(days=ch.WARMUP_DAYS)
    names = ("BTC", "ETH")
    rows = _rows(names, d0, ch.WARMUP_DAYS + 4, lambda c, i: 0.0003 if c == "BTC" else 0.0001)
    days, F = ch.matrix(rows, names, d0, ch.INCEPTION + dt.timedelta(days=3))
    p = ch.path(days, F, "carry_a")
    assert p[0]["d"] == ch.INCEPTION.isoformat() and p[0]["nav"] == 1.0 and p[0]["ret"] == 0.0
    assert abs(p[1]["ret"] - (0.0002 - ch.COST)) < 1e-12 and abs(p[2]["ret"] - 0.0002) < 1e-12 and p[-1]["switches"] == 2


def test_carry_b_is_off_after_a_negative_week_and_switches_only_on_monday():
    d0 = ch.INCEPTION - dt.timedelta(days=ch.WARMUP_DAYS)
    names = ("BTC",)
    # 起点前一直为正;起点后那一周为负 ⇒ 下周一(11-09)关
    rows = _rows(names, d0, ch.WARMUP_DAYS + 10, lambda c, i: 0.0002 if d0 + dt.timedelta(i) <= ch.INCEPTION else -0.0005)
    end = ch.INCEPTION + dt.timedelta(days=9)
    days, F = ch.matrix(rows, names, d0, end)
    p = {r["d"]: r for r in ch.path(days, F, "carry_b")}
    assert p["2026-11-06"]["n_on"] == 1 and abs(p["2026-11-06"]["ret"] - (-0.0005 - ch.COST)) < 1e-12, "11-02 的决定(过去一周为正)⇒ 起点开"
    assert p["2026-11-08"]["n_on"] == 1, "周日之前不换"
    assert p["2026-11-09"]["n_on"] == 0 and abs(p["2026-11-09"]["ret"] + ch.COST) < 1e-12, "周一看 11-02 … 11-08:4 天 +2bp、3 天 −5bp,均值为负 ⇒ 关,付一次关仓成本"


def test_partial_days_are_missing_not_zero():
    d0 = dt.date(2026, 11, 1)
    days, F = ch.matrix([{"coin": "BTC", "d": "2026-11-01", "rate_sum": 0.001, "n_hours": 19}], ("BTC",), d0, d0)
    assert np.isnan(F[0, 0])


def test_wiring():
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "async def _hl_funding_hourly_loop" in main and "async def _carry_hl_loop" in main
    mig = (ROOT / "migrations/2026-11-05_hl_funding_carry.sql").read_text(encoding="utf-8")
    for t, cols in list(hf.WRITES_COLUMNS.items()) + list(ch.WRITES_COLUMNS.items()):
        assert f"public.{t} (" in mig and all(c in mig for c in cols), t
    assert "hl_funding_hourly_last" in mig and "hl_funding_daily" in mig
    from src.data.accounting.registry import BOOKS
    from src.data.accounting.combine import PUBLIC
    b = [x for x in BOOKS if x.id == "carry_hl"]
    assert b and b[0].layer == "④" and b[0].table == ch.TABLE and b[0].arm == "carry_b" and "carry_hl" in PUBLIC


def test_spot_arm_uses_only_names_with_hl_spot_and_runs_rule_b():
    assert set(ch.HL_SPOT_NAMES) <= set(__import__("src.data.signals.core_cap", fromlist=["x"]).panel_universe())
    assert "carry_b_spot" in ch.ARMS and len(ch.HL_SPOT_NAMES) == 10 and "ADA" not in ch.HL_SPOT_NAMES
    d0 = ch.INCEPTION - dt.timedelta(days=ch.WARMUP_DAYS)
    days, F = ch.matrix(_rows(("BTC",), d0, ch.WARMUP_DAYS + 3, lambda c, i: 0.0002), ("BTC",), d0, ch.INCEPTION + dt.timedelta(days=2))
    p = ch.path(days, F, "carry_b_spot")
    assert p[1]["n_on"] == 1 and abs(p[1]["ret"] - (0.0002 - ch.COST)) < 1e-12, "carry_b_spot 走 B 的规则"
    rows = _rows(("BTC",), d0, ch.WARMUP_DAYS + 10, lambda c, i: 0.0002 if d0 + dt.timedelta(i) <= ch.INCEPTION else -0.0005)
    days, F = ch.matrix(rows, ("BTC",), d0, ch.INCEPTION + dt.timedelta(days=9))
    q = {r["d"]: r for r in ch.path(days, F, "carry_b_spot")}
    assert q["2026-11-09"]["n_on"] == 0, "carry_b_spot 也每周一按过去 7 天换"
