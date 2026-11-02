"""组合层目标表 portfolio_targets_daily(Jazz 10-29):T25 起始 600、权重只从 forward_books 来、R-v2 名义 ≤ 净值 30%、21 交易日再平衡。"""
import asyncio

import pytest

from src.data.execution import portfolio_targets as pl


def test_weights_come_from_the_paper_t25_and_sum_to_one():
    from src.data.universe.forward_books import FLEX_X1V_ARMS
    w = pl.t25_weights()
    paper = FLEX_X1V_ARMS["T25"][0]
    assert (w["crypto_x1v"], w["equity"], w["gold"]) == (paper["crypto"], paper["equity"], paper["gold"])
    assert sum(w.values()) == pytest.approx(1.0) and w["cash"] == pytest.approx(0.20)


def test_rows_and_plan_fields_are_one_function():
    rows = {r["sleeve"]: r for r in pl.t25_rows("2026-10-30")}
    assert set(rows) == {"crypto_x1v", "equity", "gold", "cash", "rv2"}
    assert rows["crypto_x1v"]["target_usd"] == 180.0 and rows["gold"]["target_usd"] == 120.0
    assert "XAUT" in rows["gold"]["instrument"]
    assert rows["gold"]["executable"] is pl.LEGS_LIVE and rows["equity"]["executable"] is pl.LEGS_LIVE, "腿是否在跑照实写"
    assert rows["rv2"]["kind"] == "gross_cap" and rows["rv2"]["target_w"] == 0.30
    f = pl.plan_fields("2026-10-30")
    assert f["x1v_nav_budget_usd"] == 180.0 and f["rv2_gross_cap_frac"] == 0.30
    cols = set(pl.WRITES_COLUMNS["portfolio_targets_daily"])
    assert all(set(r) <= cols for r in rows.values()), "写的列 = 声明的列"


def test_rebalance_every_21_weekdays_from_the_open():
    assert pl.next_rebalance(pl.OPEN_DATE, pl.OPEN_DATE) == pl.OPEN_DATE
    assert pl.next_rebalance(pl.OPEN_DATE, "2026-10-31") == "2026-11-30"      # 10-30 周五之后第 21 个工作日
    assert pl.next_rebalance(pl.OPEN_DATE, "2026-11-30") == "2026-11-30"
    assert pl.next_rebalance(pl.OPEN_DATE, "2026-12-01") == "2026-12-29"


def test_the_ticket_plan_carries_the_gross_cap():
    from src.data.execution import ticket_plan as tpm
    p = tpm.make_ticket_plan([], "2026-10-28", "2026-10-28", {})
    assert p["gross_cap_frac"] == pl.RV2_GROSS_CAP_FRAC


def test_write_once_per_day(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    wrote, have = [], []

    async def read_all(table, params):
        if table == "live_account_daily":                      # 11-01:资本来自真钱快照
            return [{"d": "2026-10-29", "equity_usd": 630.64, "flows_usd": 0}]
        if table == "overlay_daily":                           # 11-02:基线 vs 偏离后的逐日记录(这里当作已写过)
            return [{"d": "2026-10-30"}]
        assert table == "portfolio_targets_daily" and params["d"] == "eq.2026-10-30"
        return list(have)

    class Ok:
        ok = True

        def __bool__(self):
            return True

    async def upsert(table, rows, on_conflict):
        wrote.append(rows)
        return Ok()
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    import datetime as dt
    now = dt.datetime(2026, 10, 30, 0, 20, tzinfo=dt.timezone.utc)
    r = asyncio.run(pl.write_today(now))
    assert r["ok"] and r["written"] == 5 and r["capital_usd"] == 630.64 and wrote[0][0]["capital_usd"] == 630.64
    have.extend({"sleeve": s} for s in ("crypto_x1v", "equity", "gold", "cash", "rv2"))
    r = asyncio.run(pl.write_today(now))
    assert r["written"] == 0 and len(wrote) == 1, "写一次不改"
    early = asyncio.run(pl.write_today(dt.datetime(2026, 10, 29, 23, 0, tzinfo=dt.timezone.utc)))
    assert early.get("waiting")


def test_the_host_plan_carries_the_portfolio_caps(monkeypatch):
    import datetime as dt
    from src.data.execution import host_plan as hp

    async def core(asof):
        return {"ok": True, "asof": asof, "targets": {"BTC": 0.0, "ETH": 0.0}}

    async def halt():
        return False, "miss"

    async def tickets(asof):
        return {"asof": asof, "ready": False, "enter": [], "hold": [], "exit": []}
    monkeypatch.setattr(hp, "plan_core", core)
    monkeypatch.setattr(hp, "read_halt", halt)
    monkeypatch.setattr(hp, "ticket_section", tickets)
    p = asyncio.run(hp.build_host_plan(dt.datetime(2026, 10, 30, 0, 50, tzinfo=dt.timezone.utc)))
    assert p["portfolio"]["x1v_nav_budget_usd"] == 180.0 and p["portfolio"]["rv2_gross_cap_frac"] == 0.30


def test_capital_follows_the_live_snapshot_and_a_deposit_makes_today_a_rebalance_day():
    """Jazz 11-01:再平衡资本 = 真钱快照;下周加钱 —— 新钱不能躺到 11-30。"""
    rows = [{"d": "2026-11-05", "equity_usd": 2629.52, "flows_usd": 2000.0}, {"d": "2026-11-04", "equity_usd": 629.5, "flows_usd": 0}]
    cap, flow, src = pl.capital_from_snapshots(rows, "2026-11-06")
    assert cap == 2629.52 and flow is True and "出入金 +2000.00" in src
    f = pl.plan_fields("2026-11-06", cap, flow, src)
    assert f["t25"]["rebalance_today"] is True and f["t25"]["flow_event"] is True and f["t25_capital_usd"] == 2629.52
    assert f["x1v_nav_budget_usd"] == pytest.approx(0.3 * 2629.52, abs=0.01)
    assert f["t25"]["legs"]["XAUT0"]["target_usd"] == pytest.approx(0.2 * 2629.52, abs=0.01)
    # 00:08 的计划常常只看得到前两天的快照:3 天内带出入金的最近一份也触发;再下一份 flows = 0 就不再触发
    cap2, flow2, _ = pl.capital_from_snapshots([{"d": "2026-11-04", "equity_usd": 2600.0, "flows_usd": 2000.0}], "2026-11-06")
    assert flow2 is True
    cap3, flow3, _ = pl.capital_from_snapshots([{"d": "2026-11-05", "equity_usd": 2610.0, "flows_usd": 0}], "2026-11-06")
    assert flow3 is False and cap3 == 2610.0
    # 11-02 修:D = 11-04 加钱;D+1 的计划在快照落库前取(看不到 11-04);D+2 时最近一份是 11-05(flows 0)—— 原来这笔永远不触发
    cap6, flow6, src6 = pl.capital_from_snapshots([{"d": "2026-11-05", "equity_usd": 2610.0, "flows_usd": 0},
                                                    {"d": "2026-11-04", "equity_usd": 2600.0, "flows_usd": 2000.0}], "2026-11-06")
    assert flow6 is True and cap6 == 2610.0 and "11-04 出入金 +2000.00" in src6
    _, flow7, _ = pl.capital_from_snapshots([{"d": "2026-11-06", "equity_usd": 2610.0, "flows_usd": 0},
                                             {"d": "2026-11-05", "equity_usd": 2610.0, "flows_usd": 0}], "2026-11-07")
    assert flow7 is False, "两份都没有出入金 ⇒ 不触发"
    cap4, flow4, src4 = pl.capital_from_snapshots([], "2026-11-06")
    assert cap4 == 600 and flow4 is False and "还没有真钱快照" in src4
    # 快照里今天的行不算(还没收盘)
    cap5, _, _ = pl.capital_from_snapshots([{"d": "2026-11-06", "equity_usd": 1.0, "flows_usd": 0}, {"d": "2026-11-05", "equity_usd": 700.0, "flows_usd": 0}], "2026-11-06")
    assert cap5 == 700.0
