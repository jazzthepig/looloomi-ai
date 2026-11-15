"""S-891:形态的前向记分自动化 —— 触发定义与基率那条 SQL 同一个、一个窗口一组、命题能过台账的校验、要的数没到就等、不进执行层。"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.evaluation import setup_watch as sw  # noqa: E402
from src.data.evaluation.scenario_ledger import validate  # noqa: E402

D = dt.date(2026, 11, 14)


def _bars(last_close: float, n: int = 30, low: float = 100.0) -> list[dict]:
    out = [{"d": (D - dt.timedelta(days=n - 1 - i)).isoformat(), "high": low + 10, "low": low + (i % 3), "close": low + 5}
           for i in range(n - 1)]
    out.append({"d": D.isoformat(), "high": low + 2, "low": last_close - 1, "close": last_close})
    return out


def test_trigger_is_the_registered_definition() -> None:
    bars = _bars(95.0)
    hit = sw.trigger_1(bars, D, -0.13, -0.05, 0.0001)
    assert hit and hit["lo20"] == 100.0 and hit["entry"] == 95.0
    assert abs(hit["stop"] - 101.0) < 1e-12, "认错线 = 20 日低 × 1.01"
    assert sw.trigger_1(bars, D, 0.02, -0.05, 0.0001) is None, "线上不触发"
    assert sw.trigger_1(bars, D, -0.13, 0.01, 0.0001) is None, "稳定币在注不触发"
    assert sw.trigger_1(bars, D, -0.13, -0.05, -0.0001) is None, "资金费为负不触发(S-886)"
    assert sw.trigger_1(_bars(100.5), D, -0.13, -0.05, 0.0001) is None, "没跌破 20 日低不触发"
    deep = sw.trigger_1(_bars(80.0), D, -0.13, -0.05, 0.0001)
    assert abs(deep["stop"] - 80.0 * 1.08) < 1e-12, "离进场价超过 8% ⇒ 封在 8%"
    assert sw.trigger_1(_bars(95.0, n=15), D, -0.13, -0.05, 0.0001) is None, "不足 20 根历史"
    assert sw.trigger_1(_bars(95.0), D, -0.13, -0.05, 0.0001)["lo20"] == 100.0, "20 日低不含当天那根"


def test_funding_window_is_seven_days_of_daily_means_and_needs_today() -> None:
    rows = [{"funding_time": f"{(D - dt.timedelta(days=k)).isoformat()}T{h:02d}:00:00+00:00", "funding_rate": r}
            for k, r in ((0, 0.0002), (1, -0.0001), (3, 0.0004), (9, -1.0)) for h in (0, 8, 16)]
    assert abs(sw.funding_7d(rows, D) - (0.0002 - 0.0001 + 0.0004) / 3) < 1e-15, "窗口外的不算;按有数的日子平均"
    assert sw.funding_7d([r for r in rows if not r["funding_time"].startswith(D.isoformat())], D) is None, "D 当天没有 ⇒ 等"


def test_one_set_per_window_and_the_propositions_pass_the_ledger_checks() -> None:
    hit = sw.trigger_1(_bars(95.0), D, -0.13, -0.05, 0.0001)
    ents = sw.propositions_1("BTC", D, hit)
    assert [e["id"] for e in ents] == ["SW1-BTC-20261114-STOP", "SW1-BTC-20261114-CLOSE", "SW1-BTC-20261114-MOVE"]
    assert {e["horizon_d"] for e in ents} == {"2026-12-12"}
    for e in ents:
        assert validate({**e, "author": sw.AUTHOR}, D + dt.timedelta(days=1)) == [], e["id"]
    assert ents[0]["variable"] == "high:BTC" and ents[0]["lo"] == 101.0 and ents[0]["prob"] == sw.PROBS[1]["STOP"]
    assert ents[1]["variable"] == "close:BTC" and ents[1]["hi"] == 95.0
    assert ents[2]["variable"] == "low:BTC" and abs(ents[2]["hi"] - 85.5) < 1e-9
    assert all("不是下单" in e["statement"] for e in ents)
    existing = [{"id": "SW1-BTC-20261114-STOP", "horizon_d": "2026-12-12"}]
    assert sw.blocked(existing, 1, "BTC", dt.date(2026, 12, 12)) and not sw.blocked(existing, 1, "BTC", dt.date(2026, 12, 13))
    assert not sw.blocked(existing, 1, "ETH", D + dt.timedelta(days=1)), "按币分开"
    assert sw.PROBS == {1: {"STOP": 0.597, "CLOSE": 0.801, "MOVE": 0.682}}, "概率 = S-891 结果里的两段中点,改要先记台账"


def _inputs(trigger: bool = True):
    bars = {s: _bars(95.0 if trigger else 103.0) for s in sw.SYMBOLS}
    funding = {s: [{"funding_time": f"{D.isoformat()}T00:00:00+00:00", "funding_rate": 0.0001}] for s in sw.SYMBOLS}
    return bars, {"dist_200": -0.13, "stable_supply_30d": -0.05}, funding


def test_plan_waits_for_missing_inputs_and_fires_once() -> None:
    bars, state, funding = _inputs()
    p = sw.plan(D, bars, {"dist_200": -0.13, "stable_supply_30d": None}, funding, [])
    assert p["waiting"] == ["stable_supply_30d"] and not p["entries"]
    p = sw.plan(D, {**bars, "ETH": bars["ETH"][:-1]}, state, funding, [])
    assert p["waiting"] == ["ETH 日线"]
    p = sw.plan(D, bars, state, funding, [])
    assert len(p["entries"]) == 6 and p["fired"]["BTC"].startswith("触发")
    p = sw.plan(D, bars, state, funding, [{"id": "SW1-ETH-20261101-STOP", "horizon_d": "2026-11-29"}])
    assert len(p["entries"]) == 3 and "上一组" in p["fired"]["ETH"]
    p = sw.plan(D, *_inputs(trigger=False), [])
    assert not p["entries"] and p["fired"] == {"BTC": "未触发", "ETH": "未触发"}


def test_run_once_reads_yesterday_submits_once_and_caches_the_day(monkeypatch) -> None:
    import src.data.evaluation.scenario_ledger as sl
    import src.data.style.header as hd
    bars, state, funding = _inputs()
    calls = {"submit": 0, "reads": 0}

    async def read_all(table, params):
        calls["reads"] += 1
        if table == "ohlcv_daily":
            sym = params["symbol"].split(".")[1]
            return [{"trade_date": b["d"], "high": b["high"], "low": b["low"], "close": b["close"]} for b in bars[sym]]
        if table == "state_daily":
            return [{"feature": k, "value": v} for k, v in state.items()]
        if table == "funding_history":
            return funding[params["symbol"].split(".")[1]]
        if table == "scenario_ledger":
            return []
        raise AssertionError(table)

    async def submit(entries, author, now=None):
        calls["submit"] += 1
        assert author == sw.AUTHOR and len(entries) == 6
        return {"ok": True, "ids": [e["id"] for e in entries]}
    monkeypatch.setattr(hd, "_read_all", read_all)
    monkeypatch.setattr(sl, "submit", submit)
    sw._DONE.clear()
    now = dt.datetime(2026, 11, 15, 9, tzinfo=dt.timezone.utc)
    r = asyncio.run(sw.run_once(now))
    assert r["ok"] and r["d"] == "2026-11-14" and len(r["written"]) == 6 and calls["submit"] == 1
    n = calls["reads"]
    r2 = asyncio.run(sw.run_once(now + dt.timedelta(hours=1)))
    assert r2["already"] and calls["reads"] == n and calls["submit"] == 1, "同一天判过就不再读、不再写"


def test_wired_after_settlement_and_never_into_a_real_money_path() -> None:
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    seg = main[main.index("async def _scenario_ledger_loop"):main.index("async def _start_scenario_ledger_loop")]
    assert seg.index("_sl_run()") < seg.index("_sw_run()"), "先结算,后判形态"
    assert '_iteration_result("_setup_watch", _sw)' in seg and '_iteration_error("_setup_watch", _e2)' in seg
    paths = list((ROOT / "src/data/execution").rglob("*.py")) + [ROOT / "src/api/routers/executor.py"]
    for p in paths:
        if p.exists():
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    assert "setup_watch" not in (getattr(node, "module", "") or "") + " ".join(a.name for a in node.names), p
