"""偏离(11-02,规则是零假设):在预算内动真钱、带编号 / 理由 / 退出、开始与到期当天当作再平衡事件、读不到按基线、lane 写不了。"""
import asyncio
import datetime as dt
from pathlib import Path

import pytest

from src.data.execution import overlays as ov
from src.data.execution import portfolio_targets as pt

TODAY = dt.date(2026, 11, 2)


def _o(**kw):
    o = {"id": "OV-0001", "source": "scenario", "thesis": "强平地图显示 −10% 冲击下踩踏风险高", "scenario_id": "R1-A-01",
         "crypto_mult": 0.5, "starts_d": "2026-11-03", "ends_d": "2026-11-17", "exit_rule": "到期或强平名义额回到深度以下"}
    return {**o, **kw}


def test_validate_budget_and_discipline():
    assert ov.validate(_o(), TODAY) == []
    assert any("[0, 3" in w for w in ov.validate(_o(crypto_mult=3.5), TODAY))
    assert any("±10" in w for w in ov.validate(_o(crypto_mult=None, gold_pp=12), TODAY))
    assert any("不能早于今天" in w for w in ov.validate(_o(starts_d="2026-11-01"), TODAY)), "不补写过去"
    assert any("最长 90 天" in w for w in ov.validate(_o(ends_d="2027-03-01"), TODAY))
    assert any("exit_rule" in w for w in ov.validate(_o(exit_rule="到期"), TODAY)), "退出条件要写清楚"
    assert any("至少给一个" in w for w in ov.validate(_o(crypto_mult=None), TODAY))


def test_apply_within_budget_and_baseline_kept():
    base = pt.plan_fields("2026-11-03", 1000.0)          # X1V 30% = 300;黄金 20% = 200;股票 30% = 300
    act = [_o(), _o(id="OV-0002", crypto_mult=None, gold_pp=6, equity_pp=-4)]
    out = ov.apply(base, act, ["OV-0001"])
    assert out["x1v_nav_budget_usd"] == 150.0 and out["overlays"]["baseline"]["x1v_nav_budget_usd"] == 300.0
    legs = out["t25"]["legs"]
    assert legs["XAUT0"]["target_usd"] == 260.0 and legs["SPYX"]["target_usd"] == 260.0
    assert out["t25"]["rebalance_today"] is True and out["t25"]["event"] == "overlay:OV-0001", "开始当天立刻生效、周末也动"
    big = ov.apply(base, [_o(crypto_mult=3.0), _o(id="OV-0003", crypto_mult=2.0, gold_pp=8),
                          _o(id="OV-0004", crypto_mult=None, gold_pp=8)], [])
    assert big["x1v_nav_budget_usd"] == 900.0, "加密不超过净值 × 0.9"
    assert big["t25"]["legs"]["XAUT0"]["target_usd"] == 300.0, "黄金合计 +16pp 截到 +10pp"
    assert big["overlays"]["clipped"] == ["crypto_mult 6 → 3", "gold_pp +16 → ±10"] and not big["t25"].get("event")
    assert ov.apply(base, [], [])["x1v_nav_budget_usd"] == 300.0, "没有偏离 = 基线"


def test_active_and_boundaries():
    rows = [_o(), _o(id="OV-0002", starts_d="2026-11-01", ends_d="2026-11-02"), _o(id="OV-0003", starts_d="2026-11-01")]
    act = ov.active(rows, {"OV-0003"}, "2026-11-03")
    assert [o["id"] for o in act] == ["OV-0001"], "OV-0002 昨天到期、OV-0003 撤了"
    assert ov.boundary_today(rows, {"OV-0003": "2026-11-02"}, "2026-11-03") == ["OV-0001", "OV-0002", "OV-0003"]
    assert ov.boundary_today(rows, {}, "2026-11-05") == []


def test_plan_fields_live_applies_overlays_and_falls_back_to_baseline(monkeypatch):
    async def cap(d):
        return 1000.0, False, "快照"

    async def load_ok(d):
        return [_o()], ["OV-0001"]

    async def load_boom(d):
        raise RuntimeError("HTTP 503")
    monkeypatch.setattr(pt, "resolve_capital", cap)
    monkeypatch.setattr(ov, "load", load_ok)
    f = asyncio.run(pt.plan_fields_live("2026-11-03"))
    assert f["x1v_nav_budget_usd"] == 150.0 and f["overlays"]["ids"] == ["OV-0001"]
    monkeypatch.setattr(ov, "load", load_boom)
    f = asyncio.run(pt.plan_fields_live("2026-11-03"))
    assert f["x1v_nav_budget_usd"] == 300.0 and "读不到" in f["overlays"]["why"], "读不到 ⇒ 按基线,写明"


def test_only_main_tokens_can_write_and_daily_row(monkeypatch):
    r = asyncio.run(ov.submit(_o(), "lane-a"))
    assert not r["ok"] and "lane-a" in r["why"]
    row = ov.daily_row("2026-11-03", ov.apply(pt.plan_fields("2026-11-03", 1000.0), [_o()], []))
    assert row["x1v_base_usd"] == 300.0 and row["x1v_usd"] == 150.0 and row["gold_base_usd"] == row["gold_usd"] == 200.0
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "2026-11-02_overlays.sql").read_text(encoding="utf-8")
    assert "append-only" in sql and "starts_d % is before the day it is written" in sql
