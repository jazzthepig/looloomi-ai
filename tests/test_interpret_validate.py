"""M-196 检验的实现:分位数损失、只用过去的无条件对照、块 bootstrap 单侧 p、校准误差、裁决逻辑。"""
import numpy as np
import pandas as pd

from src.data.interpret import validate as v


def test_pinball_loss():
    assert v.pinball(1.0, 0.0, 0.5) == 0.5 and v.pinball(-1.0, 0.0, 0.25) == 0.75


def test_unconditional_uses_only_the_past():
    idx = pd.date_range("2020-01-01", periods=400, freq="D")
    fwd = pd.DataFrame({"ai-majors": np.arange(400, dtype=float)}, index=idx)
    t = idx[200]
    u = v.unconditional(fwd, t)
    assert u["ai-majors"]["median"] == np.median(np.arange(171))     # 只到 t − 30 天
    fwd2 = fwd.copy(); fwd2.iloc[171:] = 1e9
    assert v.unconditional(fwd2, t) == u


def test_block_bootstrap_p_detects_a_clear_negative_median():
    rng = np.random.default_rng(0)
    assert v.block_bootstrap_p(-1 + 0.1 * rng.standard_normal(300)) < 0.01
    assert v.block_bootstrap_p(1 + 0.1 * rng.standard_normal(300)) > 0.99
    assert np.isnan(v.block_bootstrap_p(np.ones(10)))


def test_ece_is_zero_for_perfect_calibration():
    p = np.array([0.0] * 50 + [1.0] * 50)
    assert v.ece(p, p) == 0.0


def _day(d, a_med, actual):
    dist = lambda m: {k: {"p25": m - 0.05, "median": m, "p75": m + 0.05, "p_up": 1.0 if m > 0 else 0.0}
                      for k in v.SPREADS}
    return {"d": d, "A": dist(a_med), "B": dist(0.0), "R": dist(0.0),
            "actual": {k: actual for k in v.SPREADS}}


def test_a_forecaster_that_knows_the_answer_passes_and_one_that_does_not_fails():
    days = pd.date_range("2024-01-01", periods=240, freq="D")
    rng = np.random.default_rng(3)
    truth = 0.1 * np.sign(rng.standard_normal(240))
    good = [_day(d, t, t) for d, t in zip(days, truth)]
    r = v.evaluate(good, label="oracle")
    assert r["t1"]["pass"] and r["t4"]["pass"] and r["random"]["pass"]
    bad = [_day(d, -t, t) for d, t in zip(days, truth)]
    assert v.evaluate(bad, label="anti")["overall"] == "FAIL"
    assert v.evaluate(good[:10], label="short")["overall"] == "INCONCLUSIVE"


def test_full_run_end_to_end_on_synthetic_data(monkeypatch):
    import asyncio
    from src.data.interpret import interpret as it
    import src.api.store as store
    idx = pd.date_range("2020-01-01", "2024-06-30", freq="D")
    rng = np.random.default_rng(5)
    lv = pd.DataFrame({s: 100 * np.exp(np.cumsum(0.03 * rng.standard_normal(len(idx))))
                       for s in ("majors", "top_l1", "second_l1_l2", "app", "ai", "meme", "defi", "infra_tokenization")},
                      index=idx)
    spaces = {"style": it.style_state(lv), "macro": pd.DataFrame(rng.standard_normal((len(idx), 12)), index=idx)}

    async def fake_load():
        return lv, spaces
    written = []

    async def fake_insert(table, rows):
        written.append((table, rows))
        class R: ok = True
        return R()
    monkeypatch.setattr(it, "_load", fake_load)
    monkeypatch.setattr(store, "supabase_insert_table", fake_insert)
    monkeypatch.setattr(v, "N_BOOT", 200)
    res = asyncio.run(v.run())
    assert res["verdict"] in ("PASS", "FAIL", "INCONCLUSIVE") and written[0][0] == "interpretation_validation_runs"
    assert res["in_sample_2023"]["n_days"] > 300


def test_result_with_nan_is_sanitized_before_insert(monkeypatch):
    """S-462:前两次运行算出 FAIL,但结果里带 NaN,JSON 写入被拒,一行都没留下。"""
    import json
    from src.api.store import sanitize_floats
    r = sanitize_floats({"p": float("nan"), "x": [np.float64("nan"), 1.0]})
    json.dumps(r, allow_nan=False)
    assert r == {"p": None, "x": [None, 1.0]}
