"""T-048:状态层的时点(PIT)纪律 —— d 之后的数据全部改掉,d 及以前每个特征逐位不变;缺数据是 None 不是 0。"""
import math

import numpy as np
import pandas as pd

from src.data.state import state_daily as sd


def _inputs(seed=0, n=1300):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    core = pd.Series(np.cumprod(1 + rng.normal(0.001, 0.03, n)), index=idx)
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (n, 8)), axis=0)), index=idx,
                      columns=[f"C{i}" for i in range(8)])
    px.iloc[::17, 3] = np.nan
    labels = np.array(["EASING", "RISK_OFF", "TIGHTENING", "NEUTRAL"])
    regimes = pd.Series(labels[rng.integers(0, 4, n)], index=idx).iloc[200:]
    funding = pd.Series(rng.normal(0.1, 0.05, 60), index=idx[-60:])
    oi = pd.DataFrame(rng.uniform(1e3, 2e3, (45, 6)), index=idx[-45:], columns=[f"C{i}" for i in range(6)])
    style = pd.DataFrame({"majors": np.cumprod(1 + rng.normal(0, 0.02, n)),
                          "second_l1_l2": np.cumprod(1 + rng.normal(0, 0.03, n))}, index=idx)
    return {"core": core, "px": px, "regimes": regimes, "funding": funding, "oi": oi, "style": style}


def _mutate_after(inp, d):
    out = {}
    for k, v in inp.items():
        v = v.copy()
        mask = v.index > d
        if isinstance(v, pd.DataFrame):
            v.loc[mask] = v.loc[mask].apply(lambda c: c * 100 + 7) if v.dtypes.iloc[0] != object else "RISK_ON"
        elif v.dtype == object:
            v.loc[mask] = "RISK_ON"
        else:
            v.loc[mask] = v.loc[mask] * 100 + 7
        out[k] = v
    return out


def test_pit_bitwise_including_none_positions():
    inp = _inputs()
    for d in (pd.Timestamp("2025-06-15"), inp["core"].index[-40], inp["core"].index[-1] - pd.Timedelta(days=3)):
        base = sd.features_at(d, inp)
        again = sd.features_at(d, _mutate_after(inp, d))
        assert base == again, d


def test_missing_is_none_not_zero():
    inp = _inputs()
    early = sd.features_at(pd.Timestamp("2023-02-01"), inp)
    v = {r["feature"]: r["value"] for r in early}
    assert v["mom_200"] is None and v["vol_pct_3y"] is None and v["funding_7d_ann"] is None
    assert v["oi_chg_30d"] is None and all(v[f"regime_share_30d:{k}"] is None for k in sd.REGIMES)
    assert v["regime_coverage_30d"] == 0.0


def test_regime_shares_sum_to_one_when_covered_and_names_normalise():
    inp = _inputs()
    rows = {r["feature"]: r["value"] for r in sd.features_at(inp["core"].index[-1], inp)}
    s = sum(rows[f"regime_share_30d:{k}"] for k in sd.REGIMES)
    assert math.isclose(s, 1.0) and rows["regime_coverage_30d"] == 30.0
    assert sd.normalise_regime("Risk-Off") == "RISK_OFF" and sd.normalise_regime("Neutral") == "NEUTRAL"
    assert sd.normalise_regime("Tightening") == "TIGHTENING" and sd.normalise_regime("GOLDILOCKS") is None


def test_one_row_per_feature_all_finite_or_none():
    inp = _inputs()
    rows = sd.features_at(inp["core"].index[-1], inp)
    feats = [r["feature"] for r in rows]
    assert len(feats) == len(set(feats)) == 17
    assert all(r["value"] is None or math.isfinite(r["value"]) for r in rows)
    assert {r["entity"] for r in rows} == {"panel"}
