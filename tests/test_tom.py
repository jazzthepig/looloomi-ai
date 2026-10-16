"""S-596:Tom 仓位管理 —— 只在盈利上加仓、破位撤加仓、跌破长期趋势底仓 0.7;③ 的新臂与研究脚本同一个核。"""
import numpy as np
import pandas as pd

from src.data.signals import multiplier as mu
from src.data.signals.tom import tom_gross


def _series(vals, start="2023-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"), dtype=float)


def test_adds_only_on_profit_and_drops_adds_on_a_20_day_low():
    up = list(np.linspace(100, 100, 60)) + [101.0] + [101 * 1.11] + [101 * 1.23] + [101 * 1.40]
    g = tom_gross(_series(up), defend=False)
    assert g.iloc[59] == 1.0, "没创新高不加"
    assert abs(g.iloc[60] - 1.1) < 1e-9, "55 日新高加 0.1"
    assert abs(g.iloc[61] - 1.2) < 1e-9 and abs(g.iloc[62] - 1.3) < 1e-9, "每再涨 10% 再加 0.1"
    assert abs(g.iloc[63] - 1.3) < 1e-9, "上限 1.3"
    crash = up + [90.0]
    g2 = tom_gross(_series(crash), defend=False)
    assert g2.iloc[-1] == 1.0, "破 20 日低 ⇒ 加的部分全撤,底仓不动"


def test_never_adds_to_a_loser():
    down = list(np.linspace(100, 60, 120))
    g = tom_gross(_series(down), defend=False)
    assert (g == 1.0).all()


def test_defence_cuts_the_base_below_the_200_day_line_and_restores_above():
    vals = list(np.linspace(100, 200, 250)) + list(np.linspace(199, 120, 60)) + list(np.linspace(121, 260, 80))
    g = tom_gross(_series(vals))
    assert g.min() >= 0.7 - 1e-9 and g.max() <= 1.3 + 1e-9
    assert (g.iloc[250:310] <= 0.7 + 1e-9).any(), "跌破 200 日线且破 20 日低 ⇒ 0.7"
    assert g.iloc[-1] >= 1.0, "重新站上 200 日线 ⇒ 底仓回 1.0"


def test_tom_arms_are_written_on_the_uncapped_core_with_the_shared_cost_model():
    days = pd.date_range("2023-01-02", "2026-10-20", freq="D")
    rng = np.random.default_rng(1)
    core_ret = pd.Series(rng.normal(0.001, 0.03, len(days)), index=days)
    state = pd.DataFrame(index=days)
    rows, ev = mu.build_rows_tom(core_ret, state, days[-1])
    arms = {r["arm"] for r in rows}
    assert arms == {mu.REPLAY_ARM_TOM, mu.ARM_TOM}
    fwd = [r for r in rows if r["arm"] == mu.ARM_TOM]
    assert fwd and min(r["d"] for r in fwd) > mu.INCEPTION_TOM.date().isoformat()
    m = pd.Series({r["d"]: r["m"] for r in rows if r["arm"] == mu.REPLAY_ARM_TOM})
    assert m.min() >= 0.7 - 1e-9 and m.max() <= 1.3 + 1e-9


def test_registry_carries_the_tom_book_as_a_third_layer_paper_book():
    from src.data.accounting.registry import BOOKS
    b = {x.id: x for x in BOOKS}["tom_overlay"]
    assert b.layer == "③" and b.table == "multiplier_daily" and b.arm == mu.ARM_TOM and b.status == "paper"
