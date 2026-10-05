"""v0.2 L3 配置层(纸面)的规则:① 默认、证据门槛、上限、人工偏置期限、敞口截断、NAV 记账。"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.data.allocation import allocator as al
from src.data.allocation.allocator import CORE, Override, decide, evidence, nav_path

D = date(2026, 11, 1)


def _book(layer="②", n=90, mu=0.5, sigma=0.2, lo=0.1, post=None, status="paper", caveat=""):
    return {"layer": layer, "status": status, "caveat": caveat,
            "evidence": {"n_days": n, "mu": mu, "sigma": sigma, "mu_lo95": lo, "mu_lo_cs": lo,
                         "mu_post": mu if post is None else post}}


def test_core_is_100pct_when_no_evidence():
    out = decide(D, {CORE: _book("①"), "x": {"layer": "②", "status": "paper", "caveat": "",
                                              "evidence": {"n_days": 3}}}, [])
    assert out["weights"] == {CORE: 1.0}
    assert out["exposure"] == 1.0
    assert out["why"][0].startswith(f"① {CORE}: 100.0%")


def test_lower_bound_gate_and_min_days():
    books = {CORE: _book("①"), "neg": _book(lo=-0.01), "young": _book(n=al.MIN_DAYS - 1)}
    assert decide(D, books, [])["weights"] == {CORE: 1.0}


def test_weight_is_continuous_quarter_kelly():
    w = decide(D, {CORE: _book("①"), "x": _book(mu=0.02, sigma=0.5, lo=0.001)}, [])["weights"]
    assert w["x"] == pytest.approx(0.25 * 0.02 / 0.25)
    assert w[CORE] == pytest.approx(1 - w["x"])


def test_non_core_capped_at_single_asset_cap_until_holdings_exist():
    w = decide(D, {CORE: _book("①"), "x": _book(mu=5.0, sigma=0.1)}, [])["weights"]
    assert w["x"] == pytest.approx(al.SINGLE_ASSET_CAP)
    assert al.SINGLE_ASSET_CAP <= al.SINGLE_BOOK_CAP


def test_nothing_before_60_days_forward():
    """l3-v2:任何非 ① 账本前向不足 60 天一律 0(覆盖了原「④ / 事件 60 天内合计 ≤ 10%」)。"""
    books = {CORE: _book("①"), "a": _book("④", n=59, mu=5, sigma=0.1), "b": _book("②", n=59, mu=5, sigma=0.1)}
    assert decide(D, books, [])["weights"] == {CORE: 1.0}
    assert al.MIN_DAYS == 60


def test_weight_uses_shrunk_mean_and_gate_uses_anytime_bound():
    """权重吃收缩后的均值,不是原始均值;门槛看任意时刻下界,不看固定 2 标准误。"""
    w = decide(D, {CORE: _book("①"), "x": _book(mu=1.0, post=0.02, sigma=0.5, lo=0.001)}, [])["weights"]
    assert w["x"] == pytest.approx(0.25 * 0.02 / 0.25)
    ev = {"n_days": 90, "mu": 1.0, "sigma": 0.5, "mu_lo95": 0.3, "mu_lo_cs": -0.01, "mu_post": 0.05}
    assert decide(D, {CORE: _book("①"), "x": {"layer": "②", "status": "paper", "caveat": "", "evidence": ev}},
                  [])["weights"] == {CORE: 1.0}


def test_anytime_gate_does_not_inflate_under_daily_peeking():
    """S-485 / T-050 验收:零超额日超额、每天重看,一年内曾被放进去的比例 ≤ 5%(l3-v1 为 17%)。
    厚尾(t3)路径;门槛函数与 evidence() 用的是同一个 cs_halfwidth。"""
    rng = np.random.default_rng(485)
    R, T, s_d = 1500, 365, 0.30 / np.sqrt(365)
    x = s_d * rng.standard_t(3, (R, T)) / np.sqrt(3)
    n = np.arange(1, T + 1)
    c, c2 = np.cumsum(x, 1), np.cumsum(x * x, 1)
    m = c / n
    sd = np.sqrt(np.maximum((c2 - n * m * m) / np.maximum(n - 1, 1), 1e-18))
    v, rho = n * sd ** 2, al.CS_RHO_DAYS * sd ** 2
    half = np.sqrt((v + rho) * np.log((v + rho) / (rho * al.CS_ALPHA ** 2))) / n
    adm = ((m - half) > 0)[:, al.MIN_DAYS - 1:]
    assert adm.any(1).mean() <= 0.05
    assert al.cs_halfwidth(100, 0.01) == pytest.approx(half_ref(100, 0.01))


def half_ref(n, s):
    v, rho = n * s * s, al.CS_RHO_DAYS * s * s
    return np.sqrt((v + rho) * np.log((v + rho) / (rho * al.CS_ALPHA ** 2))) / n


def test_weight_ramps_with_evidence_instead_of_jumping_to_cap():
    """同样的观测超额,天数越多收缩越少;刚过门槛时不会顶到 40%。"""
    s = 0.30 / np.sqrt(365)
    m = s * 4 / np.sqrt(60)
    w60 = 0.25 * al.shrink(m, s, 60) * 365 / (s * s * 365)
    w365 = 0.25 * al.shrink(m, s, 365) * 365 / (s * s * 365)
    assert 0 < w60 < w365 and w60 < al.SINGLE_ASSET_CAP


def test_sum_never_exceeds_one():
    books = {CORE: _book("①"), **{f"x{i}": _book(mu=5, sigma=0.1) for i in range(4)}}
    w = decide(D, books, [])["weights"]
    assert sum(w.values()) == pytest.approx(1.0)
    assert w[CORE] == pytest.approx(0.0)


def test_caveat_or_dormant_gets_zero():
    books = {CORE: _book("①"), "c": _book(caveat="数字不可信"), "r": _book(status="retired_by_design")}
    assert decide(D, books, [])["weights"] == {CORE: 1.0}


@pytest.mark.parametrize("h,days", [("7d", 7), ("14d", 14), ("1m", 30)])
def test_override_expires(h, days):
    o = Override(date(2026, 11, 1), -0.5, h, "test")
    assert o.active_on(date(2026, 11, 1))
    assert o.active_on(date(2026, 11, 1) + pd.Timedelta(days=days - 1))
    assert not o.active_on(date(2026, 11, 1) + pd.Timedelta(days=days))
    assert not o.active_on(date(2026, 10, 31))


def test_delegate_means_no_override():
    o = Override(D, -0.5, "delegate", "全委托")
    assert not o.active_on(D)
    assert decide(D, {CORE: _book("①")}, [o])["exposure"] == 1.0


def test_exposure_clipped_both_ends():
    lo = decide(D, {CORE: _book("①")}, [Override(D, -1.3, "7d", "x")])
    hi = decide(D, {CORE: _book("①")}, [Override(D, 0.5, "7d", "x"), Override(D, 0.5, "14d", "y")])
    assert lo["exposure"] == pytest.approx(-0.3) and hi["exposure"] == pytest.approx(1.3)
    assert any("截到边界" in s for s in lo["why"])


def test_evidence_forward_lower_bound():
    idx = pd.date_range("2026-10-01", periods=100, freq="D")
    rng = np.random.default_rng(0)
    b = pd.Series(np.cumprod(1 + rng.normal(0, 0.02, 100)), index=idx)
    a = b * np.cumprod(np.full(100, 1.003))
    ev = evidence(a, b)
    assert ev["n_days"] == 99 and ev["mu"] > 0 and ev["mu_lo95"] <= ev["mu"]
    assert ev["mu_lo_cs"] < ev["mu_lo95"] and 0 < ev["mu_post"] < ev["mu"]
    assert evidence(a, None) == {"n_days": 0}


def test_nav_uses_previous_day_weights_and_exposure():
    days = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]
    dec = {days[0]: {"weights": {CORE: 1.0}, "exposure": 0.5},
           days[1]: {"weights": {CORE: 1.0}, "exposure": 1.0},
           days[2]: {"weights": {CORE: 1.0}, "exposure": 1.0}}
    r = pd.Series([0.10, np.nan], index=pd.to_datetime(["2026-10-02", "2026-10-03"]))
    rows = nav_path(days, dec, {CORE: r})
    assert rows[0]["nav"] == 1.0
    assert rows[1]["ret"] == pytest.approx(0.05)
    assert rows[2]["ret"] == 0.0 and rows[2]["missing_returns"] == [CORE]


def test_forward_window_starts_at_inception():
    idx = pd.date_range("2026-09-01", "2026-10-10", freq="D")
    s = pd.Series(1.0, index=idx)
    w = al.forward_window(s, pd.Timestamp("2026-10-05"))
    assert w.index.min() == pd.Timestamp(al.INCEPTION) - pd.Timedelta(days=1)
    assert w.index.max() == pd.Timestamp("2026-10-05")


def test_routes_registered():
    from src.api.routers.ohlcv import router
    paths = {r.path for r in router.routes}
    assert "/internal/allocation/override" in paths and "/internal/allocation/latest" in paths
