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
    assert "XAUT" in rows["gold"]["instrument"] and not rows["gold"]["executable"], "没建的腿照实写"
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
    assert r["ok"] and r["written"] == 5
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
