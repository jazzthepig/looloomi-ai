"""③ 每日决定(11-03,S-709):桶、前向收益不偷看、基率向无条件收缩、分歧标记、情景条目、合规文案、一轮 run_once。"""
from __future__ import annotations

import asyncio
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.execution import exposure_decision as x  # noqa: E402


def _state(mom, **shares):
    s = {"mom_200": mom}
    for r in x.REGIMES:
        s[f"regime_share_30d:{r}"] = shares.get(r, 0.0)
    return s


def test_bucket_is_trend_sign_times_dominant_regime():
    assert x.bucket_of(_state(0.04, RISK_ON=0.2, TIGHTENING=0.8)) == "up|TIGHTENING"
    assert x.bucket_of(_state(-0.1, RISK_OFF=0.5, RISK_ON=0.5)) in ("down|RISK_ON", "down|RISK_OFF")
    assert x.bucket_of({}) == "unknown"


def test_forward_returns_use_calendar_days_and_never_the_future():
    closes = {"2026-01-01": 100.0, "2026-01-31": 110.0, "2026-02-15": 90.0}
    fwd = x.forward_returns(closes)
    assert list(fwd) == ["2026-01-01"] and abs(fwd["2026-01-01"] - 0.10) < 1e-9, "只有 d+30 那天有收盘的 d 才算"


def test_base_rates_shrink_small_buckets_toward_unconditional():
    buckets, fwd = {}, {}
    i = 0

    def add(bk, n, pd, pf):
        nonlocal i
        for j in range(n):
            d = f"d{i}"
            i += 1
            fwd[d] = -0.2 if j < n * pd else (0.0 if j < n * (pd + pf) else 0.2)
            buckets[d] = bk
    add("up|RISK_ON", 2000, 0.2, 0.5)
    add("down|TIGHTENING", 70, 0.0, 0.56)
    p, n, used = x.base_rates(buckets, fwd, "down|TIGHTENING")
    assert used == "down|TIGHTENING" and n == 70 and 0.1 < p["down"] < 0.2, "70 个重叠日 ≈ 2 段,P(跌) 不能是 0"
    assert abs(sum(p.values()) - 1) < 0.01
    p2, n2, used2 = x.base_rates(buckets, fwd, "up|RISK_OFF")
    assert used2 == "all" and n2 == 2070 and abs(p2["down"] - 0.2) < 0.02, "没见过的桶 ⇒ 无条件"


def test_flag_only_when_rule_and_base_rates_disagree():
    assert x.flag_for(1.0, {"down": 0.45, "flat": 0.4, "up": 0.15}).startswith("规则与基率分歧")
    assert x.flag_for(0.0, {"down": 0.1, "flat": 0.4, "up": 0.5}).startswith("规则与基率分歧")
    assert x.flag_for(1.0, {"down": 0.2, "flat": 0.5, "up": 0.3}) is None
    assert x.flag_for(None, {"down": 0.2, "flat": 0.5, "up": 0.3}) is not None


def test_scenario_entries_and_rationale_are_machine_checkable_and_compliant():
    es = x.scenario_entries("2026-11-02", 100000.0, {"down": 0.2, "flat": 0.5, "up": 0.3})
    assert [e["id"] for e in es] == ["X-2026-11-02-down", "X-2026-11-02-flat", "X-2026-11-02-up"]
    assert es[0]["op"] == "lt" and es[0]["hi"] == 90000.0 and es[2]["op"] == "gt" and es[2]["lo"] == 110000.0
    assert all(e["horizon_d"] == "2026-12-02" and e["variable"] == "close:BTC" for e in es)
    from src.data.evaluation.scenario_ledger import validate
    assert all(not validate({**e, "author": x.AUTHOR}, dt.date(2026, 11, 3)) for e in es)
    txt = x.rationale("2026-11-02", 0.0, "down|TIGHTENING", {"down": 0.13, "flat": 0.52, "up": 0.35}, 70, "down|TIGHTENING",
                      {"funding_7d_ann": 0.08, "oi_chg_30d": -0.12, "breadth_above_ma50": 0.0, "liq_shock_5pct_max": 1.7,
                       "events_7d": {"delisting": 3}}, None)
    assert "敞口 0%" in txt and "13%" in txt and "1.7 倍" in txt and "delisting 3" in txt
    assert not re.search(r"\b(buy|sell|accumulate|avoid|reduce)\b", txt, re.I)
    assert "不是对任何人的建议" in x.post_text({"d": "2026-11-02", "rationale": txt})


def test_run_once_writes_row_scenarios_and_posts(monkeypatch):
    import src.api.notify as notify
    import src.api.store as store
    import src.data.style.header as hdr
    import src.data.execution.host_plan as hp
    import src.data.ops.news_feed as nf
    import src.data.evaluation.scenario_ledger as sl
    up, sent, subs = [], [], []
    now = dt.datetime(2026, 11, 3, 5, 0, tzinfo=dt.timezone.utc)

    async def hist():
        buckets = {f"2025-{m:02d}-{dd:02d}": "down|TIGHTENING" for m in range(1, 13) for dd in range(1, 29)}
        closes = {}
        base = dt.date(2025, 1, 1)
        for i in range(400):
            closes[(base + dt.timedelta(days=i)).isoformat()] = 100.0 + (i % 7)
        closes["2026-11-02"] = 100.0
        return buckets, closes

    async def today(d):
        return _state(-0.05, TIGHTENING=1.0, **{"dist_200": -0.07, "funding_7d_ann": 0.08, "oi_chg_30d": -0.12, "breadth_above_ma50": 0.0})

    async def read_all(t, params):
        if t == x.TABLE:
            return []
        if t == "multiplier_daily":
            return [{"m": 0.5}]
        if t == "events":
            return [{"kind": "delisting"}]
        raise AssertionError(t)

    async def plan(asof):
        return {"ok": True, "targets": {"BTC": 0.0, "ETH": 0.0}}

    async def submit(entries, author, now=None):
        subs.append((author, [e["id"] for e in entries]))
        return {"ok": True, "written": 3, "ids": [e["id"] for e in entries]}

    async def ups(t, rows, on_conflict):
        up.extend(rows)
        return True

    async def chat():
        return "-100", "redis"

    async def tg(text, chat_id=None, parse_mode=None, disable_preview=True):
        sent.append(text)
        return True

    async def liq():
        return 1.7
    monkeypatch.setattr(x, "_history", hist)
    monkeypatch.setattr(x, "_today_state", today)
    monkeypatch.setattr(x, "_liq_shock", liq)
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(hp, "plan_core", plan)
    monkeypatch.setattr(sl, "submit", submit)
    monkeypatch.setattr(store, "supabase_upsert_table", ups)
    monkeypatch.setattr(nf, "resolve_feed_chat", chat)
    monkeypatch.setattr(notify, "notify_telegram", tg)
    monkeypatch.setattr(notify, "telegram_configured", lambda: True)
    r = asyncio.run(x.run_once(now))
    assert r["ok"] and r["d"] == "2026-11-02" and r["exposure"] == 0.0 and r["scenarios"] == 3 and r["posted"]
    assert subs[0][0] == x.AUTHOR and up[0]["mult_m"] == 0.5 and up[0]["inputs"]["events_7d"] == {"delisting": 1}
    assert up[0]["inputs"]["liq_shock_5pct_max"] == 1.7 and "③ 每日决定" in sent[0]


def test_wiring():
    assert "_exposure_decision_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-03_exposure_decision.sql").read_text(encoding="utf-8")
    for col in x.WRITES_COLUMNS[x.TABLE]:
        assert col in mig, col
