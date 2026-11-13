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
    assert rows["rv2"]["kind"] == "gross_cap" and rows["rv2"]["target_w"] == 0.80
    f = pl.plan_fields("2026-10-30")
    assert f["x1v_nav_budget_usd"] == 180.0 and f["rv2_gross_cap_frac"] == 0.80
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
        if table == "portfolio_targets_daily" and params["d"].startswith("lt."):
            return []                                          # 11-10:当期权重沿用上一次 —— 开账日之前没有
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
    import src.data.universe.forward_books as fb

    async def no_legs(d):
        raise RuntimeError("测试里不取价")
    monkeypatch.setattr(fb, "rb_leg_returns", no_legs)
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
    assert p["portfolio"]["x1v_nav_budget_usd"] == 180.0 and p["portfolio"]["rv2_gross_cap_frac"] == 0.80


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


def test_rv2_gross_cap_is_flexible_up_to_40pct_and_refuses_beyond():
    """Jazz 11-05:探索仓 0–40% 灵活。默认 30%;Railway 的 R_V2_GROSS_CAP_FRAC 可改到 ≤ 40%;写错不悄悄夹到边界。"""
    import pytest
    from src.data.execution import portfolio_targets as pt
    assert pt.rv2_gross_cap_frac({}) == 0.80 and pt.rv2_gross_cap_frac({"R_V2_GROSS_CAP_FRAC": "0.30"}) == 0.30
    assert pt.rv2_gross_cap_frac({"R_V2_GROSS_CAP_FRAC": " 0.35 "}) == 0.35
    for bad in ("0.81", "0", "-0.1", "x"):
        with pytest.raises(ValueError):
            pt.rv2_gross_cap_frac({"R_V2_GROSS_CAP_FRAC": bad})



def test_t25_is_flexible_within_bands_rbv2_on_rebalance_days_carried_between(monkeypatch):
    """Jazz 11-10:30/30/20 是推荐比例,像保险组合一样在带内灵活 —— 再平衡日 RBv2 定权重,其余日子沿用,算不出沿用上一次。"""
    import numpy as np
    import pandas as pd
    from src.data.universe import flex_alloc as fa
    stored = {"2026-11-27": [{"d": "2026-11-27", "sleeve": "crypto_x1v", "target_w": 0.25},
                             {"d": "2026-11-27", "sleeve": "equity", "target_w": 0.35},
                             {"d": "2026-11-27", "sleeve": "gold", "target_w": 0.28}]}

    async def read(table, params):
        d = params["d"]
        if d.startswith("eq."):
            return stored.get(d[3:], [])
        return [r for k in sorted(stored, reverse=True) if k < d[3:] for r in stored[k]]
    rng = np.random.default_rng(1110)
    idx = pd.bdate_range("2026-08-01", periods=80)
    rets = pd.DataFrame({"crypto": rng.normal(0, 0.05, 80), "equity": rng.normal(0, 0.01, 80), "gold": rng.normal(0, 0.008, 80)}, index=idx)

    async def legs(d):
        return rets

    async def broken(d):
        raise RuntimeError("eodhd down")
    w, why = asyncio.run(pl.flex_weights("2026-11-27", True, read, legs))
    assert w == {"crypto": 0.25, "equity": 0.35, "gold": 0.28} and why == "今天的目标表", "当天已写 ⇒ 表是唯一出处"
    w, why = asyncio.run(pl.flex_weights("2026-12-01", False, read, legs))
    assert w["crypto"] == 0.25 and "沿用 2026-11-27" in why
    w, why = asyncio.run(pl.flex_weights("2026-12-29", True, read, legs))
    assert why.startswith("RBv2") and all(fa.BOUNDS[k][0] - 1e-9 <= w[k] <= fa.BOUNDS[k][1] + 1e-9 for k in fa.LEGS)
    assert w["crypto"] < 0.30, "加密腿波动大 ⇒ 权重低于推荐比例(同一事前风险)"
    w, why = asyncio.run(pl.flex_weights("2026-12-29", True, read, broken))
    assert w["gold"] == 0.28 and "算不出" in why and "沿用" in why
    empty = lambda t, p: asyncio.sleep(0, result=[])
    w, why = asyncio.run(pl.flex_weights("2026-12-29", True, empty, broken))
    assert w is None and "推荐比例" in why
    rows = {r["sleeve"]: r for r in pl.t25_rows("2026-12-29", 1000.0, False, {"crypto": 0.22, "equity": 0.38, "gold": 0.27})}
    assert rows["crypto_x1v"]["target_usd"] == 220.0 and abs(rows["cash"]["target_w"] - 0.13) < 1e-9
    f = pl.plan_fields("2026-12-29", 1000.0, False, "x", {"crypto": 0.22, "equity": 0.38, "gold": 0.27}, "RBv2")
    assert f["x1v_nav_budget_usd"] == 220.0 and f["weights_source"] == "RBv2" and f["t25"]["legs"]["SPYX"]["target_usd"] == 380.0


def test_passive_legs_stay_unless_explicitly_switched_off(monkeypatch):
    """S-854:股票腿 / 黄金腿移出实盘是一个只有 Jazz 能扳的开关。缺省、写错都照旧持有;明确关了才是 0,钱回现金,加密腿不变。"""
    monkeypatch.delenv(pl.PASSIVE_LEGS_ENV, raising=False)
    base = pl.t25_weights()
    assert base["equity"] > 0 and base["gold"] > 0 and pl.passive_legs_live()
    for typo in ("", "1", "on", "yes", "o", "zero", " 1 "):
        assert pl.passive_legs_live({pl.PASSIVE_LEGS_ENV: typo}) is True
    for off in ("0", "off", "OFF", " false ", "no"):
        assert pl.passive_legs_live({pl.PASSIVE_LEGS_ENV: off}) is False
    monkeypatch.setenv(pl.PASSIVE_LEGS_ENV, "0")
    w = pl.t25_weights()
    assert w["equity"] == 0.0 and w["gold"] == 0.0 and w["crypto_x1v"] == base["crypto_x1v"]
    assert abs(w["cash"] - (1.0 - base["crypto_x1v"])) < 1e-9 and abs(sum(w.values()) - 1.0) < 1e-9
    f = pl.plan_fields("2026-11-16", 630.17)
    assert f["t25"]["legs"]["SPYX"]["target_usd"] == 0.0 and f["t25"]["legs"]["XAUT0"]["target_usd"] == 0.0
    assert f["x1v_nav_budget_usd"] == round(base["crypto_x1v"] * 630.17, 2)
    rows = {r["sleeve"]: r for r in pl.t25_rows("2026-11-16", 630.17)}
    assert "S-854" in rows["equity"]["why"] and "S-854" in rows["gold"]["why"] and "S-854" not in rows["crypto_x1v"]["why"]
    w2 = pl.t25_weights({"crypto": 0.22, "equity": 0.38, "gold": 0.27})                          # RBv2 给的权重同样被关掉
    assert w2["equity"] == 0.0 and w2["gold"] == 0.0 and w2["crypto_x1v"] == 0.22 and abs(w2["cash"] - 0.78) < 1e-9


def test_host_sells_a_leg_whose_target_is_zero_but_not_on_a_weekend():
    """主机一侧:目标 0 ⇒ 卖出整条腿;周末不动(底层不开盘)。"""
    import datetime as dt
    from src.exec_host import legs
    t25 = {"capital_usd": 630.17, "band": 0.05, "rebalance_today": False, "legs": {"SPYX": {"target_usd": 0.0}, "XAUT0": {"target_usd": 0.0}}}
    held = {"SPYX": 175.96, "XAUT0": 116.10}
    mon = legs.leg_orders(t25, held, dt.date(2026, 11, 16))
    assert [(o["symbol"], o["side"], o["notional_usd"]) for o in mon["orders"]] == [("SPYX", "sell", 175.96), ("XAUT0", "sell", 116.1)]
    sat = legs.leg_orders(t25, held, dt.date(2026, 11, 14))
    assert sat["orders"] == [] and all("周末" in x["why"] for x in sat["skipped"])
