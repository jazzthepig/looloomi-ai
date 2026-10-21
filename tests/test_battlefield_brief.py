"""⓪ 战场简报:单币状态(趋势位置、第一段 / 回撤 / 第二段形态与 S-658 同一组数)、标签、广度汇总。"""
import datetime as dt

import pytest

from src.data.execution import battlefield_brief as bb


def _series(closes, vol=1.0):
    d0 = dt.date(2026, 1, 1)
    return [((d0 + dt.timedelta(days=k)).isoformat(), c, c * 1.01, c * 0.99, c, vol) for k, c in enumerate(closes)]


def test_second_leg_setup_matches_the_s658_definition():
    # 30 根 10 → 80 根涨到 25(第一段 2.5 倍)→ 40 根回撤到 18(−28%)→ 今天放量收 26(破 20 日高、站上 SMA50)
    closes = [10.0] * 30 + [10 + 15 * k / 79 for k in range(80)] + [25 - 7 * k / 39 for k in range(40)]
    bars = _series(closes) + [("2026-06-01", 25.0, 26.5, 24.9, 26.0, 3.0)]
    s = bb.coin_state(bars, {"funding": "0.00001", "openInterest": "100", "markPx": "26", "dayNtlVlm": "5e6"})
    assert s["first_leg_x"] == pytest.approx(2.5) and s["pullback"] == pytest.approx(18 / 25 - 1, abs=0.01)
    assert s["breakout_20d"] and s["above_sma50"] and s["second_leg_setup"] and bb.tag(s) == "第二段形态"
    assert s["funding_apr"] == pytest.approx(0.0876) and s["oi_usd"] == 2600.0


def test_no_volume_expansion_means_no_setup_and_short_history_is_partial():
    closes = [10.0] * 30 + [10 + 15 * k / 79 for k in range(80)] + [25 - 7 * k / 39 for k in range(40)]
    quiet = _series(closes) + [("2026-06-01", 25.0, 26.5, 24.9, 26.0, 1.0)]
    assert bb.coin_state(quiet)["second_leg_setup"] is False
    short = bb.coin_state(_series([1.0, 1.1, 1.2]))
    assert short["bars"] == 3 and "first_leg_x" not in short and short["ret_30d"] is None


def test_tags_and_breadth():
    assert bb.tag({"above_sma50": False, "above_sma200": False}) == "弱势"
    assert bb.tag({"above_sma50": True, "sma50_rising": True}) == "趋势中"
    rows = [{"above_sma50": True, "ret_30d": 0.1, "funding_apr": 0.1}, {"above_sma50": False, "ret_30d": -0.2},
            {"above_sma50": None, "ret_30d": 0.0, "second_leg_setup": True}]
    b = bb.summarize(rows)
    assert b["above_sma50"] == 0.5 and b["second_leg_setups"] == 1 and b["median_ret_30d"] == 0.0
