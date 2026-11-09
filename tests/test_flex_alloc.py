"""S-797 组合层 v2 的核:天气 → 风格矢量 → 权重;回放与前向同一个核,不许看到调仓日之后的数据。"""
import numpy as np
import pandas as pd
import pytest

from src.data.universe import flex_alloc as fa


def _legs(n=300, seed=797, crypto_sig=0.03):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    r = {"crypto": rng.normal(0.001, crypto_sig, n), "equity": rng.normal(0.0004, 0.01, n), "gold": rng.normal(0.0002, 0.008, n)}
    return {k: pd.Series(np.cumprod(1 + v), index=idx) for k, v in r.items()}


def test_weather_is_four_buckets_and_unknown_stays_unknown():
    assert fa.weather_of(0.05, 1.2) == "up_hot" and fa.weather_of(-0.01, 0.8) == "down_cold"
    assert fa.weather_of(None, 1.0) is None and fa.weather_of(0.1, float("nan")) is None


def test_budget_bounds_and_cash_remainder():
    w = fa.clip_to_budget({"crypto": 1.5, "equity": 0.9, "gold": 0.0})
    assert w["crypto"] <= 0.40 + 1e-12 and sum(w.values()) <= 1.0 + 1e-12
    w2 = fa.clip_to_budget({"crypto": 0.25, "equity": 0.3, "gold": 0.2})
    assert w2 == {"crypto": 0.25, "equity": 0.3, "gold": 0.2}, "预算内不动"
    assert fa.clip_to_budget({"crypto": 0.63, "equity": 0.3, "gold": 0.2})["crypto"] == 0.40, \
        "S-801:空仓腿的权重陷阱 —— 加密也只许 ±10pp(46–63% 那几次会被截到 40%)"
    assert fa.clip_to_budget({"crypto": 0.0, "equity": 0.3, "gold": 0.2})["crypto"] == 0.20


def test_rb_falls_back_to_base_without_history_and_cuts_crypto_when_it_gets_wild():
    legs = _legs(30)
    rets = pd.concat(legs, axis=1).pct_change().iloc[1:]
    assert fa.rb_weights(rets) == fa.BASE_T25, "不足 MIN_OBS ⇒ 原样"
    calm = pd.concat(_legs(200, crypto_sig=0.009), axis=1).pct_change().iloc[1:]
    wild = pd.concat(_legs(200, crypto_sig=0.08), axis=1).pct_change().iloc[1:]
    wc, ww = fa.rb_weights(calm), fa.rb_weights(wild)
    assert ww["crypto"] < wc["crypto"], "加密腿波动变大 ⇒ 权重变小(同一事前风险)"
    for w in (wc, ww):
        assert all(fa.BOUNDS[k][0] - 1e-12 <= w[k] <= fa.BOUNDS[k][1] + 1e-12 for k in fa.LEGS) and sum(w.values()) <= 1 + 1e-12


def test_style_tilts_toward_the_leg_that_earns_in_this_weather_and_ignores_thin_buckets():
    idx = pd.bdate_range("2023-01-02", periods=400)
    weather = pd.Series(["up_cold"] * 200 + ["down_hot"] * 150 + ["up_hot"] * 50, index=idx)
    r = pd.DataFrame({"crypto": np.r_[np.full(200, 0.004), np.full(150, -0.004), np.full(50, 0.0)],
                      "equity": np.full(400, 0.0005), "gold": np.r_[np.full(200, 0.0), np.full(150, 0.002), np.full(50, 0.0)]}, index=idx)
    tab = fa.style_table(r, weather)
    assert "up_hot" not in tab["crypto"], "50 天 < MIN_BUCKET_DAYS 的格不写"
    up = fa.style_weights(tab, "up_cold")
    down = fa.style_weights(tab, "down_hot")
    assert up["crypto"] == pytest.approx(0.40) and down["crypto"] == pytest.approx(0.20)
    assert down["gold"] == pytest.approx(0.30), "下跌发热时黄金有优势"
    assert fa.style_weights(tab, "up_hot") == fa.clip_to_budget(fa.BASE_T25), "样本不够的格 ⇒ 不动"
    assert fa.style_weights(None, "up_cold") == fa.clip_to_budget(fa.BASE_T25)


def test_dynamic_mix_never_sees_the_future_and_matches_constant_compounding():
    legs = _legs(120)
    seen = []

    def wf(hist, d):
        seen.append((hist.index.max() if len(hist) else None, d))
        return fa.BASE_T25
    nav, log = fa.dynamic_mix_nav(legs, wf, reb=21, cost=0.0)
    assert all(m is None or m <= d for m, d in seen), "调仓函数只拿到当天及以前"
    assert len(log) == 1 + (len(nav) - 1) // 21
    df = pd.concat(legs, axis=1).pct_change().iloc[1:]
    hold = pd.Series(fa.BASE_T25)
    v = 1.0
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        g = float((hold * row).sum())
        v *= 1 + g
        hold = hold * (1 + row) / (1 + g)
        if i % 21 == 0:
            hold = pd.Series(fa.BASE_T25)
    assert nav.iloc[-1] == pytest.approx(v, rel=1e-12)
    nav2, _ = fa.dynamic_mix_nav(legs, wf, start=nav.index[50])
    assert nav2.index[0] == nav.index[50] and nav2.iloc[0] == 1.0, "start 之前只作历史"
