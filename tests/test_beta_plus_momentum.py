"""S-429 — ② β+ 动量 + 52 周高点前向账本:预注册被钉住,账本与回测同一内核,价格进 NAV,读不到就拒绝。"""
import math

import numpy as np
import pandas as pd
import pytest

from src.data.signals import beta_plus_momentum as bp

PANEL = tuple(f"C{i}" for i in range(8))


def _prices(end="2026-10-10", seed=0, trend=None):
    """起点前 400 天的合成价格;trend: {币: 日漂移}。"""
    days = pd.date_range(pd.Timestamp("2026-09-25") - pd.Timedelta(days=400), end, freq="D")
    rng = np.random.default_rng(seed)
    cols = {}
    for i, s in enumerate(PANEL):
        mu = (trend or {}).get(s, 0.0)
        cols[s] = 100 * np.exp(np.cumsum(mu + 0.02 * rng.standard_normal(len(days))))
    return pd.DataFrame(cols, index=days)


def _rows(rows, arm):
    return [r for r in rows if r["arm"] == arm]


def test_tilt_targets_long_only_full_and_bounded():
    x = pd.Series(np.arange(10, dtype=float), index=[f"A{i}" for i in range(10)])
    w = bp.tilt_targets(x, 1.0)
    assert math.isclose(w.sum(), 1.0) and (w >= 0).all()
    assert w.max() <= 2 / 10 + 1e-9                         # k=1 ⇒ 至多 2/N
    assert w.idxmax() == "A9" and w.idxmin() == "A0"        # 高分超配
    e = bp.tilt_targets(x, 0.0)
    assert np.allclose(e.values, 0.1)                       # k=0 ⇒ 等权 = 基准


def test_signal_prefers_winners_near_their_high():
    px = _prices(trend={"C0": 0.008, "C7": -0.008})
    sig = bp.combo_signal(px)
    d = pd.Timestamp("2026-09-25")
    assert sig.loc[d].idxmax() == "C0" and sig.loc[d].idxmin() == "C7"


def test_preregistration_is_pinned():
    assert set(bp.ARMS) == {"panel_hold_w", "momentum_52w_w", "panel_hold_m", "momentum_52w_m"}
    assert bp.K == 1.0 and bp.COST_BPS == 10.0 and bp.MIN_HIST == 180
    assert bp.INCEPTION == pd.Timestamp("2026-09-25") and bp.PRICE_SOURCE == "binance_hist"


def test_signal_monday_trades_tuesday_not_same_day():
    px = _prices()
    rows = bp.compute_path(px, PANEL, "t")
    w = {r["d"]: r for r in _rows(rows, "momentum_52w_w")}
    assert w["2026-09-28"]["signal"] is not None and not w["2026-09-28"]["traded"]   # 周一出信号
    assert w["2026-09-29"]["traded"]                                                   # 周二成交
    assert not any(w[d]["traded"] for d in ("2026-09-30", "2026-10-01", "2026-10-02"))


def test_prices_move_nav_and_arms_differ():
    """fusion 那种「只扣成本不记价格」在这里不可能:NAV 随价格变,倾斜臂 ≠ 基准臂。"""
    px = _prices(trend={"C0": 0.01, "C1": 0.006, "C7": -0.01})
    rows = bp.compute_path(px, PANEL, "t")
    last = {r["arm"]: r["nav"] for r in rows if r["d"] == "2026-10-10"}
    assert len({round(v, 6) for v in last.values()}) >= 3
    assert last["momentum_52w_w"] > last["panel_hold_w"]    # 这条合成路径上赢家一直赢
    rets = {r["ret"] for r in _rows(rows, "panel_hold_w")}
    assert len(rets) > 5


def test_benchmark_arms_are_equal_weight():
    rows = bp.compute_path(_prices(), PANEL, "t")
    r0 = next(r for r in rows if r["arm"] == "panel_hold_w" and r["d"] == "2026-09-25")
    assert all(math.isclose(v, 1 / 8, abs_tol=1e-5) for v in r0["weights"].values())


def test_missing_quotes_refuse():
    px = _prices()
    px.loc["2026-09-26", ["C0", "C1", "C2"]] = np.nan
    with pytest.raises(ValueError, match="读不到"):
        bp.compute_path(px, PANEL, "t")


def test_no_silent_start_elsewhere():
    px = _prices().loc[:"2026-09-24"]
    with pytest.raises(ValueError, match="起点"):
        bp.compute_path(px, PANEL, "t")


def test_research_uses_the_same_kernel():
    """回测里的权重就是账本那天会算出的权重。"""
    import inspect
    from src.research.validation import s428_beta_plus_factor_tilt as research
    assert "tilt_targets" in inspect.getsource(research.backtest)


def test_a_missing_calendar_day_does_not_stretch_the_windows():
    """binance_hist 整天缺 41 天(S-429 实测)。缺一天的行被整行拿掉,信号不应改变多少(窗口按自然日)。"""
    px = _prices(trend={"C0": 0.003, "C3": -0.002})
    full = bp.compute_path(px, PANEL, "t")
    holed = bp.compute_path(px.drop(index=pd.date_range("2026-07-01", "2026-07-20")), PANEL, "t")
    a = next(r for r in full if r["arm"] == "momentum_52w_w" and r["d"] == "2026-09-25")["signal"]
    b = next(r for r in holed if r["arm"] == "momentum_52w_w" and r["d"] == "2026-09-25")["signal"]
    assert list(a) == list(b)                 # 同样的排序
