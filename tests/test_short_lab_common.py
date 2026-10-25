"""做空模拟器(S-681)四道共用 —— 止损、跳空、到期、规则出场、资金费方向、不叠票、判据,必须钉死。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs" / "research"))
import short_lab_common as sl  # noqa: E402


def _bars(o, h, l, c, start="2022-01-01"):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return {"d": [(d0 + dt.timedelta(days=i)).isoformat() for i in range(len(c))],
            "o": np.array(o, float), "h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float),
            "qv": np.full(len(c), 1e7)}


def test_stop_is_hit_intraday_at_the_stop_price():
    a = _bars(o=[100, 100, 101, 102], h=[100, 105, 131, 103], l=[100, 99, 100, 100], c=[100, 101, 102, 101])
    t = sl.short_ticket(a, 0, 0.30, 10)
    assert t["why"] == "stop" and abs(t["exit_px"] - 130) < 1e-9
    assert abs(t["r"] - ((100 - 130) / 100 - 2 * sl.COST_SIDE) / 0.30) < 1e-9, "打止损 ≈ −1R(再扣成本)"


def test_gap_above_the_stop_exits_at_the_open_and_is_flagged():
    a = _bars(o=[100, 100, 150, 150], h=[100, 101, 155, 151], l=[100, 99, 149, 149], c=[100, 100, 150, 150])
    t = sl.short_ticket(a, 0, 0.30, 10)
    assert t["why"] == "stop_gap" and t["gap"] and t["exit_px"] == 150 and t["r"] < -1.6


def test_time_exit_and_funding_paid_to_the_short():
    n = 8
    a = _bars(o=[100] * n, h=[101] * n, l=[90] * n, c=[95] * n)
    fund = {d: 0.001 for d in a["d"]}                       # 每天 +0.1%,空头收
    t = sl.short_ticket(a, 0, 0.30, 3, fund=fund)
    assert t["why"] == "time" and t["xi"] == 4 and t["exit_px"] == 100
    assert abs(t["funding"] - 0.003) < 1e-12 and abs(t["ret"] - (0.003 - 2 * sl.COST_SIDE)) < 1e-12


def test_rule_exit_next_open_and_explicit_stop_price():
    a = _bars(o=[100, 100, 98, 90, 91], h=[100, 101, 99, 92, 92], l=[99, 97, 96, 89, 90], c=[100, 98, 97, 91, 91])
    t = sl.short_ticket(a, 0, 0.0, 30, exit_rule=lambda a, j: j == 2, stop_px=110.0)
    assert t["why"] == "rule" and t["xi"] == 3 and t["exit_px"] == 90 and abs(t["risk"] - 0.10) < 1e-12


def test_no_stacking_on_the_same_coin():
    a = _bars(o=[100] * 12, h=[101] * 12, l=[99] * 12, c=[100] * 12)
    t1 = sl.short_ticket(a, 0, 0.3, 5, symbol="X")
    t2 = sl.short_ticket(a, 2, 0.3, 5, symbol="X")        # 第一张还没出
    t3 = sl.short_ticket(a, 7, 0.3, 2, symbol="X")
    out = sl.chain([t1, t2, t3])
    assert [t["ei"] for t in out] == [1, 8]


def test_judge_needs_all_four():
    tk = [{"r": 0.5, "signal_d": f"2021-{m:02d}-01"} for m in range(1, 13)] * 5
    j = sl.judge(tk, np.array([0.0] * 100), [{"r": 0.2}])
    assert j["verdict"] == "过"
    assert sl.judge(tk, np.array([0.0] * 100), [{"r": -0.2}])["verdict"] == "不过", "留出段反向 ⇒ 不过"
    assert sl.judge(tk[:30], np.array([0.0] * 100), [{"r": 0.2}])["verdict"] == "不过", "票数不到 50"
