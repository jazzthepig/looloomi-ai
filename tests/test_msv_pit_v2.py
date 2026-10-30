"""矢量库 v2(T-094 / S-699):时点面板 + 按时点标准化 —— 截到 d 的数据算出的 d 行 = 全史算出的 d 行(无前视)。"""
import math
import random
from datetime import date, timedelta

import pytest

from src.data.vector import market_state as ms
from src.data.vector import market_state_writer as W


def _panel(n_sym=40, n_days=700, seed=7, dead=None):
    rnd = random.Random(seed)
    d0 = date(2020, 1, 1)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range(n_days)]
    panel = {}
    for k in range(n_sym):
        sym = "BTC" if k == 0 else f"C{k:02d}"
        p, start = 100.0 + k, (0 if k < 30 else 150 * (k - 29))
        ser = {}
        for i, d in enumerate(days):
            if i < start or (dead and sym in dead and i > dead[sym]):
                continue
            p *= math.exp(rnd.gauss(0, 0.03))
            ser[d] = (p, (1e6 + 1e5 * k) * (1 + rnd.random()))
        panel[sym] = ser
    return panel, days


def _cut(panel, d):
    return {s: {x: v for x, v in ser.items() if x <= d} for s, ser in panel.items()}


def test_members_use_only_data_before_the_month_and_keep_n_constant():
    panel, days = _panel()
    full = W.monthly_members(panel, days[0], n=20)
    assert full and all(len(v) == 20 for v in full.values()), "每个出成员的月份都是 20 个"
    for m in list(full)[2:6]:
        cut = W.monthly_members(_cut(panel, f"{m}-01"), days[0], n=20)
        assert cut.get(m) == full[m], f"{m} 的成员只能由上月末之前的数据决定"


def test_a_dead_coin_is_in_the_panel_while_it_was_alive_and_big():
    panel, days = _panel(dead={"C25": 450})
    for sym, ser in panel.items():                                    # 让 C25 最大,活到第 450 天
        if sym == "C25":
            panel[sym] = {d: (c, v * 50) for d, (c, v) in ser.items()}
    mem = W.monthly_members(panel, days[0], n=20)
    months = sorted(mem)
    alive = [m for m in months if m <= days[440][:7]]
    gone = [m for m in months if m > days[480][:7]]
    assert alive and all("C25" in mem[m] for m in alive if m > days[260][:7]), "活着、够大的月份在面板里"
    assert gone and not any("C25" in mem[m] for m in gone), "死了之后不在"


def test_stablecoins_and_perp_only_names_never_enter():
    panel, days = _panel()
    panel["USDC"] = {d: (1.0, 1e12) for d in days}
    panel["1000SHIB"] = {d: (1.0, 1e12) for d in days}
    mem = W.monthly_members(panel, days[0], n=20, exclude=W.PANEL_EXCLUDE | {"XMR"})
    assert not any(s in v for v in mem.values() for s in ("USDC", "1000SHIB"))


def test_expanding_z_is_point_in_time():
    rows = [ms.StateVector(d=f"2021-01-{i:02d}" if i < 32 else f"2021-02-{i - 31:02d}",
                           values={"vol_mkt": float(i % 7) + i * 0.1}) for i in range(1, 50)]
    full = [ms.StateVector(d=r.d, values=dict(r.values)) for r in rows]
    ms.zscore_expanding(full, min_obs=10)
    for k in (15, 30, 48):
        part = [ms.StateVector(d=r.d, values=dict(r.values)) for r in rows[:k + 1]]
        ms.zscore_expanding(part, min_obs=10)
        assert part[-1].values["vol_mkt"] == pytest.approx(full[k].values["vol_mkt"]), "第 k 天的 z 不看 k 之后"
    assert full[5].values["vol_mkt"] is None, "读数不够之前记 None,不是 0"
    # 负控制:全史一次的 z 在第 15 天用了未来
    once = [ms.StateVector(d=r.d, values=dict(r.values)) for r in rows]
    ms.zscore_columns(once, min_obs=10)
    part = [ms.StateVector(d=r.d, values=dict(r.values)) for r in rows[:16]]
    ms.zscore_columns(part, min_obs=10)
    assert part[-1].values["vol_mkt"] != pytest.approx(once[15].values["vol_mkt"])


def test_a_vector_computed_on_data_cut_at_d_equals_the_full_history_row():
    """T-094 验收:截到 d 的数据算出的 d 行向量与全史算出的 d 行向量一致(价格维 + 横截面维 + 按时点 z)。"""
    panel, days = _panel()
    def run(pnl):
        mem = W.monthly_members(pnl, days[0], n=20)
        spec = W.members_spec(pnl, mem, source="binance_hist")
        vec = W.compute_vectors(pnl, spec, members=mem)
        ms.zscore_expanding(vec, min_obs=60)
        return {v.d: v.values for v in vec}
    full = run(panel)
    for d in (days[420], days[560], days[-1]):
        cut = run(_cut(panel, d))
        assert set(cut[d]) == set(full[d])
        for k, x in full[d].items():
            assert (x is None and cut[d][k] is None) or cut[d][k] == pytest.approx(x), (d, k)
