"""T-052:② CIS 倾斜 —— 预注册参数钉死、z 的缺分规则、倾斜仍守 40% 上限、无分时退化为 ①、只在起点与周一再平衡。
T-088:cis_a1_u 在新 ①(cap_a1_u,无单币上限)上的臂 —— 单币可超 40%;cis_a1_u_replay 从 2023-01-02 起按时点回放,
z 只用 cis_rebuild_daily d−1 的 score。
"""
import math

import numpy as np
import pandas as pd
import pytest

from src.data.signals import cis_tilt as ct
from src.data.signals import core_cap as cc


def test_preregistered_parameters_are_pinned():
    """改任何一项 = 新起点(旧记录留档),不是在原账本上调参。"""
    assert ct.K == 0.5 and ct.CIS_COLUMN == "raw_cis_score" and ct.ARM == "cis_a1"
    assert ct.INCEPTION == pd.Timestamp("2026-10-06") and ct.CIS_MAX_AGE_DAYS == 3
    assert ct.COST_BPS == cc.COST_BPS and ct.SINGLE_ASSET_CAP == cc.SINGLE_ASSET_CAP == 0.40
    assert ct.capped_weights is cc.capped_weights          # 同一个迭代算法,不是第二条路径


def test_preregistered_parameters_u_arm_are_pinned():
    """T-088:cis_a1_u 用新 ① 的参数 —— 起点 = core_cap.CORE_SINCE,cap 解除,code_ref 单独标记。"""
    assert ct.ARM_U == "cis_a1_u"
    assert ct.REPLAY_ARM_U == "cis_a1_u_replay"
    assert ct.INCEPTION_U == cc.CORE_SINCE == pd.Timestamp("2026-10-12")
    assert ct.ARM_CAP_U == 1.0                            # 不设单币上限
    assert ct.REPLAY_START == pd.Timestamp("2023-01-02")  # 周一
    assert ct.CODE_REF_U.startswith("T-088")
    assert "cap_a1_u" in ct.CODE_REF_U


def test_z_missing_is_zero_and_degenerate_cases_are_all_zero():
    names = ["A", "B", "C", "D"]
    z = ct.cis_z({"A": 70.0, "B": 60.0, "C": None}, names)
    assert z["C"] == 0.0 and z["D"] == 0.0 and z["A"] == pytest.approx(-z["B"]) and z["A"] > 0
    assert ct.cis_z({"A": 70.0}, names) == {s: 0.0 for s in names}
    assert ct.cis_z({"A": 70.0, "B": 70.0}, names) == {s: 0.0 for s in names}
    assert ct.cis_z({"A": float("nan"), "B": 60.0, "C": 50.0}, names)["A"] == 0.0


def test_no_scores_means_exactly_the_core():
    w_core = cc.capped_weights({"BTC": 60.0, "ETH": 20.0, "SOL": 10.0, "XRP": 5.0, "ADA": 5.0}, 1.0)
    w = ct.tilted_weights(w_core, {})
    assert w == pytest.approx(w_core)


def test_tilt_overweights_high_cis_and_keeps_the_cap():
    w_core = cc.capped_weights({"BTC": 60.0, "ETH": 20.0, "SOL": 10.0, "XRP": 5.0, "ADA": 5.0}, 1.0)
    z = {"BTC": 3.0, "ETH": 3.0, "SOL": -1.0, "XRP": 0.0, "ADA": 1.0}
    w = ct.tilted_weights(w_core, z)
    assert sum(w.values()) == pytest.approx(1.0) and max(w.values()) <= 0.40 + 1e-9
    assert w["ADA"] / w["XRP"] == pytest.approx(math.exp(0.5 * 1.0) * w_core["ADA"] / w_core["XRP"])
    assert w["SOL"] < w_core["SOL"]


def test_u_arm_tilt_lets_a_coin_exceed_40pct():
    """T-088 acceptance:cis_a1_u 倾斜后单币可以 > 40%(新 ① 不设单币上限 ⇒ ② 也不设)。"""
    w_core = cc.capped_weights({"BTC": 60.0, "ETH": 20.0, "SOL": 10.0, "XRP": 5.0, "ADA": 5.0}, 1.0, cap=1.0)
    z = {"BTC": 4.0, "ETH": 4.0, "SOL": -1.0, "XRP": 0.0, "ADA": 1.0}
    w = ct.tilted_weights(w_core, z, cap=1.0)
    assert sum(w.values()) == pytest.approx(1.0)
    assert max(w.values()) > 0.40 + 1e-9, f"cis_a1_u 应可超 40%; got {max(w.values()):.4f}"
    assert w["BTC"] > 0.40


def _panel(days, syms, seed=0):
    rng = np.random.default_rng(seed)
    px = pd.DataFrame(100 * np.exp(np.cumsum(0.02 * rng.standard_normal((len(days), len(syms))), axis=0)),
                      index=days, columns=syms)
    mc = pd.DataFrame({s: 1e9 * (i + 1) ** 2 for i, s in enumerate(syms)}, index=days)
    return px, mc


def test_rebalances_only_at_inception_and_mondays_and_records_z():
    days = pd.date_range(ct.INCEPTION, periods=10, freq="D")
    syms = [f"S{i}" for i in range(6)]
    px, mc = _panel(days, syms)
    rebal = [d for d in days if ct.is_rebalance_day(d)]
    cis = {d: {"S0": 80.0, "S1": 60.0, "S2": 70.0} for d in rebal}
    rows = ct.compute_path(px, mc, cis, [], "binance_hist")
    assert {r["d"] for r in rows if r["z"] is not None} == {d.date().isoformat() for d in rebal}
    assert {pd.Timestamp(d).weekday() for d in [r["d"] for r in rows if r["z"]][1:]} <= {0}
    first = rows[0]
    assert first["n_scored"] == 3 and first["z"]["S3"] == 0.0 and first["arm"] == "cis_a1"
    assert all(abs(sum(r["weights"].values()) - 1) < 1e-4 for r in rows)


def test_refuses_to_start_anywhere_but_inception():
    days = pd.date_range(ct.INCEPTION + pd.Timedelta(days=1), periods=5, freq="D")
    px, mc = _panel(days, ["A", "B", "C"])
    with pytest.raises(ValueError):
        ct.compute_path(px, mc, {}, [], "binance_hist")


def test_u_arm_path_does_not_write_before_inception_u():
    """T-088 acceptance:cis_a1_u 的前向第一行 > 10-12(把 INCEPTION_U 当起点)。"""
    days = pd.date_range(ct.INCEPTION, periods=8, freq="D")  # 10-06 → 10-13
    syms = [f"S{i}" for i in range(6)]
    px, mc = _panel(days, syms)
    rebal = [d for d in days if ct.is_rebalance_day(d, ct.INCEPTION_U)]
    cis = {d: {"S0": 80.0, "S1": 60.0, "S2": 70.0} for d in rebal}
    rows = ct.compute_path(px, mc, cis, [], "binance_hist",
                            arm=ct.ARM_U, inception=ct.INCEPTION_U,
                            cap=ct.ARM_CAP_U, code_ref=ct.CODE_REF_U)
    assert rows, "10-12 之后再平衡日应该至少一行"
    assert all(r["d"] >= ct.INCEPTION_U.date().isoformat() for r in rows)
    assert rows[0]["arm"] == "cis_a1_u" and rows[0]["inception"] == "2026-10-12"
    # 旧臂 cis_a1 在再平衡日 max_weight ≤ 0.40(cap=0.40) —— 只查再平衡日,中间日的漂移不约束
    rows_old = ct.compute_path(px, mc, cis, [], "binance_hist")
    rebal_old_days = {d.date().isoformat() for d in days if ct.is_rebalance_day(d, ct.INCEPTION)}
    assert all(r["max_weight"] is None or r["max_weight"] <= 0.40 + 1e-6
               for r in rows_old if r["d"] in rebal_old_days)


def test_replay_path_pins_z_to_d_minus_one():
    """T-088 acceptance:cis_a1_u_replay 的 z 用 cis_rebuild_daily d−1 的 score。

    这里只测纯函数层 —— compute_replay_path 接受调用方按时点填好的 cis_at;约束是
    _cis_at_rebuild 取 d-1 而不是 d。 用 fake session 内的 _read_all 检查:把 d 的 score 设成不一样的
    值,验证读到的是 d-1 的。"""
    import asyncio
    from unittest.mock import AsyncMock, patch
    panel = ["BTC", "ETH", "SOL"]
    rebal = [pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-12")]
    # 构造重建表:d 当天有行(诱饵),d-1 也有行(应选);d 当天的 score 与 d-1 不同 —— 若读错日期就破
    rows = [
        {"symbol": "BTC", "d": "2026-01-04", "score": 80.0},
        {"symbol": "ETH", "d": "2026-01-04", "score": 60.0},
        {"symbol": "SOL", "d": "2026-01-04", "score": 50.0},
        {"symbol": "BTC", "d": "2026-01-05", "score": 999.0},   # 当天的诱饵 —— 不该被读
        {"symbol": "BTC", "d": "2026-01-11", "score": 70.0},
        {"symbol": "ETH", "d": "2026-01-11", "score": 50.0},
        {"symbol": "SOL", "d": "2026-01-11", "score": 60.0},
        {"symbol": "BTC", "d": "2026-01-12", "score": 888.0},   # 当天的诱饵 —— 不该被读
    ]
    async def _go():
        with patch("src.data.style.header._read_all", new=AsyncMock(return_value=rows)):
            return await ct._cis_at_rebuild(rebal, panel, "cis-standard-v1.3")
    cis = asyncio.new_event_loop().run_until_complete(_go())
    assert cis[pd.Timestamp("2026-01-05")] == {"BTC": 80.0, "ETH": 60.0, "SOL": 50.0}
    assert cis[pd.Timestamp("2026-01-12")] == {"BTC": 70.0, "ETH": 50.0, "SOL": 60.0}


def test_replay_path_runs_from_2023_with_uncapped():
    """T-088:cis_a1_u_replay 从 REPLAY_START 起按时点回放,cap=1.0。"""
    days = pd.date_range(ct.REPLAY_START, periods=10, freq="D")
    syms = ["S0", "S1", "S2", "S3", "S4", "S5"]
    px, mc = _panel(days, syms)
    rebal = [d for d in days if ct.is_rebalance_day(d, ct.REPLAY_START)]
    cis = {d: {"S0": 80.0, "S1": 60.0, "S2": 70.0} for d in rebal}
    rows = ct.compute_replay_path(px, mc, cis, [], "binance_hist")
    assert rows
    assert rows[0]["d"] == ct.REPLAY_START.date().isoformat()
    assert all(r["arm"] == "cis_a1_u_replay" for r in rows)
    assert all(r["inception"] == "2023-01-02" for r in rows)
    assert all(r["code_ref"] == ct.CODE_REF_U for r in rows)
