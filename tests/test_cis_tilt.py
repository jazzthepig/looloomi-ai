"""T-052:② CIS 倾斜 —— 预注册参数钉死、z 的缺分规则、倾斜仍守 40% 上限、无分时退化为 ①、只在起点与周一再平衡。"""
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
