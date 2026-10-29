"""P1 真钱账户每日快照:当天最后一次心跳、扣外部出入金、认不出的出入金不猜、地址不进表。"""
import asyncio
import datetime as dt

import pytest

from src.data.accounting import live_account as la

ME = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20


def _beat(at, usdc, **acct):
    return {"at": at, "detail": {"kind": "heartbeat", "balances": {"USDC": usdc, **acct.pop("coins", {})},
                                 "trade_account": ME, "account": acct}}


def test_flows_count_external_money_only():
    ups = [{"delta": {"type": "deposit", "usdc": "100"}},
           {"delta": {"type": "withdraw", "usdc": "30", "fee": "1"}},
           {"delta": {"type": "send", "user": OTHER, "destination": ME, "token": "USDC", "amount": "868.85",
                      "usdcValue": "868.85"}},                                           # 10-19 那一笔
           {"delta": {"type": "send", "user": ME, "destination": OTHER, "token": "USDC", "usdcValue": "50", "fee": "0"}},
           {"delta": {"type": "send", "user": ME, "destination": ME, "usdcValue": "400"}},  # 自己现货 → 永续
           {"delta": {"type": "accountClassTransfer", "usdc": "10", "toPerp": True}}]
    total, unknown = la.flows_of(ups, ME.upper())
    assert total == pytest.approx(100 - 31 + 868.85 - 50) and unknown == []
    _t, unknown = la.flows_of([{"delta": {"type": "vaultDeposit", "usdc": "5"}}], ME)
    assert unknown == ["vaultDeposit"], "认不出的类型不猜"


def test_open_day_then_return_net_of_flows():
    closes = {"BTC": 100_000.0}
    d0 = la.snapshot_row(la.OPEN_DATE, [_beat("2026-10-29T14:52:00Z", 600.0), _beat("2026-10-29T23:52:00Z", 630.64)],
                         closes, 0.0, [], None)
    assert d0["nav"] == 1.0 and d0["equity_usd"] == pytest.approx(630.64) and d0["heartbeat_at"].startswith("2026-10-29T23")
    assert "trade_account" not in d0 and ME not in str(d0), "地址不进表"
    d1 = la.snapshot_row("2026-10-30", [_beat("2026-10-30T23:50:00Z", 530.64, coins={"UBTC": 0.002})],
                         {"BTC": 110_000.0}, 100.0, [], d0)
    # 权益 530.64 + 220 = 750.64;扣掉 100 的入金 ⇒ 650.64 / 630.64
    assert d1["equity_usd"] == pytest.approx(750.64) and d1["spot_usd"] == {"BTC": pytest.approx(220.0)}
    assert d1["ret"] == pytest.approx(650.64 / 630.64 - 1) and d1["nav"] == pytest.approx(650.64 / 630.64)


def test_unpriced_tokens_and_unknown_flows_leave_nav_empty():
    d0 = {"d": la.OPEN_DATE, "equity_usd": 630.0, "nav": 1.0}
    r = la.snapshot_row("2026-10-30", [_beat("2026-10-30T23:50:00Z", 600.0, coins={"PURR": 50.0})], {}, 0.0, [], d0)
    assert r["nav"] is None and "PURR" in r["note"]
    r = la.snapshot_row("2026-10-30", [_beat("2026-10-30T23:50:00Z", 600.0)], {}, 0.0, ["vaultDeposit"], d0)
    assert r["nav"] is None and "vaultDeposit" in r["note"]
    r = la.snapshot_row("2026-10-30", [_beat("2026-10-30T23:50:00Z", 600.0)], {}, None, [], d0)
    assert r["nav"] is None, "出入金读不到 ≠ 0"
    assert la.snapshot_row("2026-10-30", [], {}, 0.0, [], d0) is None


def test_a_silent_day_does_not_break_the_chain():
    d0 = {"d": la.OPEN_DATE, "equity_usd": 600.0, "nav": 1.0}
    r = la.snapshot_row("2026-10-31", [_beat("2026-10-31T23:50:00Z", 612.0)], {}, 0.0, [], d0)
    assert r["nav"] == pytest.approx(1.02) and "中间主机没有心跳" in r["note"]


def test_run_once_writes_each_finished_day_once(monkeypatch):
    import src.api.store as store
    import src.data.style.header as hdr
    table: dict[str, dict] = {}
    asked_ledger = []

    async def read_all(t, params):
        if t == la.TABLE:
            return [dict(v) for v in sorted(table.values(), key=lambda r: r["d"])]
        if t == "loop_attempt":
            lo = params["and"][7:17]
            return [_beat(f"{lo}T23:50:00Z", 630.0), {"at": f"{lo}T23:55:00Z", "detail": {"kind": "cycle"}}]
        if t == "ohlcv_daily":
            return []
        raise AssertionError(t)

    async def ledger(addr, first, last):
        asked_ledger.append((addr, first, last))
        return []

    async def upsert(t, rows, on_conflict):
        for r in rows:
            table[r["d"]] = r
        return True
    monkeypatch.setattr(hdr, "_read_all", read_all)
    monkeypatch.setattr(store, "supabase_upsert_table", upsert)
    monkeypatch.setattr(la, "_ledger", ledger)
    now = dt.datetime(2026, 10, 31, 1, 0, tzinfo=dt.timezone.utc)
    r = asyncio.run(la.run_once(now))
    assert r["written"] == ["2026-10-29", "2026-10-30"] and table["2026-10-30"]["nav"] == pytest.approx(1.0)
    assert asked_ledger[-1] == (ME, "2026-10-30", "2026-10-30")
    assert asyncio.run(la.run_once(now))["written"] == [], "写一次不改"
    early = asyncio.run(la.run_once(dt.datetime(2026, 10, 29, 20, 0, tzinfo=dt.timezone.utc)))
    assert early.get("waiting")


def test_the_anchor_now_covers_the_live_book_and_its_paper_references():
    from src.data.accounting.anchor import SOURCES, key_of
    tables = {t: k for t, _f, k in SOURCES}
    for t in ("live_account_daily", "portfolio_targets_daily", "forward_book_nav", "world50_book_nav"):
        assert t in tables
    assert key_of({"book": "flex_x1v", "arm": "T25"}, tables["forward_book_nav"]) == "flex_x1v|T25"
