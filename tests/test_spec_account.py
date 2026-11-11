"""投机仓记分账(11-12):收益 = 累计盈亏之差 ÷ 上一天净值 —— 入金不是收益;读不到 ≠ 0;没配地址不读不写。"""
import asyncio

import pytest

from src.data.accounting import spec_account as sa


def _resp(av, pnl):
    return [["day", {"accountValueHistory": [[1, "1"]], "pnlHistory": [[1, "0"]], "vlm": "0"}],
            ["allTime", {"accountValueHistory": [[1, "100"], [2, str(av)]], "pnlHistory": [[1, "0"], [2, str(pnl)]], "vlm": "0"}]]


def test_last_point_reads_the_all_time_bucket_and_refuses_bad_shapes():
    assert sa.last_point(_resp(1234.5, 34.5)) == (1234.5, 34.5)
    assert sa.last_point({"allTime": {"accountValueHistory": [[1, "7"]], "pnlHistory": [[1, "-1"]]}}) == (7.0, -1.0)
    for bad in (None, [], [["week", {}]], [["allTime", {"accountValueHistory": []}]], "x", [["allTime", None]]):
        assert sa.last_point(bad) == (None, None), bad


def test_deposit_is_not_return_and_nav_compounds_on_pnl_only():
    r0 = sa.day_row("2026-11-12", 1000.0, 0.0, None, None, "t")
    assert (r0["ret"], r0["nav"], r0["n_reads"]) == (0.0, 1.0, 1)
    # 第二天:挣了 50,又入金 500 ⇒ 净值 1550,但收益只有 50 / 1000
    r1 = sa.day_row("2026-11-13", 1550.0, 50.0, r0, None, "t")
    assert r1["ret"] == pytest.approx(0.05) and r1["nav"] == pytest.approx(1.05)
    # 同一天再读一次:覆盖,读数次数 + 1,收益仍对上一天算
    r1b = sa.day_row("2026-11-13", 1530.0, 30.0, r0, r1, "t")
    assert r1b["n_reads"] == 2 and r1b["ret"] == pytest.approx(0.03)
    r2 = sa.day_row("2026-11-14", 1499.0, -1.0, r1b, None, "t")
    assert r2["ret"] == pytest.approx(-31.0 / 1530.0) and r2["nav"] == pytest.approx(1.03 * (1 - 31.0 / 1530.0))


def test_unreadable_or_empty_account_leaves_nav_blank_not_zero():
    r = sa.day_row("2026-11-13", None, 5.0, {"d": "2026-11-12", "equity_usd": 100, "cum_pnl_usd": 0, "nav": 1}, None, "t")
    assert r["ret"] is None and r["nav"] is None and "读不到" in r["note"]
    r = sa.day_row("2026-11-13", 10.0, 5.0, {"d": "2026-11-12", "equity_usd": 0, "cum_pnl_usd": 0, "nav": 1}, None, "t")
    assert r["ret"] is None and r["nav"] is None and "≤ 0" in r["note"]


def test_scorecard_compares_on_common_days_and_counts_days_since_the_peak():
    rows = [{"d": f"2026-11-{d}", "nav": n} for d, n in ((12, 1.0), (13, 1.10), (14, 1.05), (15, 1.02), (16, None))]
    core = [{"d": f"2026-11-{d}", "nav": n} for d, n in ((11, 1.0), (12, 1.0), (13, 1.01), (14, 1.01), (15, 1.02))]
    s = sa.scorecard(rows, core)
    assert s["days"] == 4 and s["from"] == "2026-11-12" and s["to"] == "2026-11-15"
    assert s["spec_return"] == pytest.approx(0.02) and s["core_return"] == pytest.approx(0.02) and s["excess"] == pytest.approx(0.0)
    assert s["days_under_water"] == 2
    assert sa.scorecard(rows[:1], core)["why"]


def test_no_address_means_no_read_and_no_write(monkeypatch):
    monkeypatch.delenv(sa.ENV, raising=False)
    r = asyncio.run(sa.run_once())
    assert r["ok"] and r["skipped"]
    monkeypatch.setenv(sa.ENV, "not-an-address")
    assert asyncio.run(sa.run_once())["ok"] is False


def test_the_account_reader_allows_portfolio_and_nothing_that_needs_a_key():
    from src.data.accounting.live_account import HL_ACCOUNT_INFO_TYPES
    assert "portfolio" in HL_ACCOUNT_INFO_TYPES and sa.TABLE in sa.WRITES_TABLES
