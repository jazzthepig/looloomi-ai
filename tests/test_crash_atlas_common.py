"""崩盘图谱共用内核(S-675):三道都 import 它,所以它的定义要钉死 —— 熊市段落、急跌、按时点分位不看未来、
迹象对基准率的零分布能分开「真先兆」与「随便亮的灯」、分阶段收益。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs" / "research"))
import crash_atlas_common as ca  # noqa: E402


def _price(path):
    idx = pd.date_range("2020-01-01", periods=len(path), freq="D")
    return pd.Series(path, index=idx, dtype=float)


def test_bear_episode_is_one_per_peak_and_closes_on_a_new_high():
    up = list(np.linspace(100, 200, 50))
    down = list(np.linspace(200, 140, 30))           # −30%
    back = list(np.linspace(140, 210, 60))           # 新高 ⇒ 段落结束
    eps = ca.bear_episodes(_price(up + down + back), 0.20)
    assert len(eps) == 1
    e = eps[0]
    assert e["peak_d"] == pd.Timestamp("2020-01-01") + pd.Timedelta(days=50), "平了前高也算新高 ⇒ 前高日取最后一次 200"
    assert abs(e["depth"] - (-0.30)) < 1e-9 and e["recover_d"] is not None
    assert e["break_d"] > e["peak_d"] and e["trough_d"] >= e["break_d"]
    assert ca.bear_episodes(_price(up + list(np.linspace(200, 170, 30)) + list(np.linspace(170, 210, 60))), 0.20) == [], \
        "−15% 不到门槛"


def test_a_second_bear_before_the_old_high_is_regained_is_its_own_episode():
    """NASDAQ:2000 年的高点 2015 年才回来;2007–09 必须是单独的一段,不能吞进 2000 年那段(10-23 实测踩过)。"""
    path = (list(np.linspace(100, 200, 50)) + list(np.linspace(200, 50, 50))      # −75%
            + list(np.linspace(50, 150, 50)) + list(np.linspace(150, 75, 50))    # 反弹 +200% 后再 −50%,没回到 200
            + list(np.linspace(75, 120, 50)))
    eps = ca.bear_episodes(_price(path), 0.20)
    assert len(eps) == 2
    assert abs(eps[0]["depth"] + 0.75) < 1e-9 and abs(eps[1]["depth"] + 0.5) < 1e-9
    assert eps[1]["peak_d"] > eps[0]["trough_d"] and eps[0]["recover_d"] is None
    assert eps[0]["first_leg"] and not eps[1]["first_leg"], "第二段的前高 150 < 第一段的 200 ⇒ 不是新一轮的顶"


def test_open_episode_has_no_recovery_date():
    eps = ca.bear_episodes(_price(list(np.linspace(100, 200, 50)) + list(np.linspace(200, 100, 50))), 0.20)
    assert len(eps) == 1 and eps[0]["recover_d"] is None and abs(eps[0]["depth"] + 0.5) < 1e-9


def test_fast_crash_hits_once_per_cluster():
    path = [100.0] * 40 + [100 - 3 * i for i in range(1, 11)] + [70.0] * 20 + [70 - 3 * i for i in range(1, 11)]
    hits = ca.fast_crashes(_price(path), window_days=10, threshold=0.20, decluster_days=60)
    assert len(hits) == 1, "两段急跌相隔 < 60 天 ⇒ 只算第一段"
    assert hits[0]["ret"] <= -0.20
    assert len(ca.fast_crashes(_price(path), window_days=10, threshold=0.20, decluster_days=15)) == 2


def test_expanding_percentile_does_not_look_ahead():
    x = pd.Series(np.arange(400, dtype=float), index=pd.date_range("2020-01-01", periods=400, freq="D"))
    a = ca.expanding_pct(x, min_periods=10)
    y = x.copy()
    y.iloc[300:] = -1e9                                   # 改掉未来
    b = ca.expanding_pct(y, min_periods=10)
    assert a.iloc[:300].equals(b.iloc[:300]), "过去的分位不能因为未来变了而变"


def test_sign_lift_separates_a_real_precursor_from_a_random_light():
    idx = pd.date_range("2000-01-01", periods=6000, freq="D")
    anchors = [idx[i] for i in range(400, 5900, 110)]
    real = pd.Series(False, index=idx)
    for a in anchors:
        real.loc[a - pd.Timedelta(days=20):a - pd.Timedelta(days=10)] = True
    rng = np.random.default_rng(1)
    noise = pd.Series(rng.random(len(idx)) < 0.02, index=idx)
    r = ca.sign_lift(real, anchors, lookback_days=30, n_shift=300)
    z = ca.sign_lift(noise, anchors, lookback_days=30, n_shift=300)
    assert r["hit_rate"] == 1.0 and r["lift"] > 2 and r["pctile"] > 0.99
    assert 0.02 < z["pctile"] < 0.98 and 0.7 < z["lift"] < 1.3, "随便亮的灯:命中率≈基准率,分位落在中间"


def test_sign_lift_skips_anchors_before_the_sign_has_history():
    idx = pd.date_range("2010-01-01", periods=1000, freq="D")
    on = pd.Series(np.nan, index=idx, dtype=object)
    on.iloc[500:] = False
    r = ca.sign_lift(on, [idx[100], idx[800]], lookback_days=30, n_shift=50)
    assert r["n_anchors"] == 1 and r["n_skipped"] == 1


def test_release_lag_moves_economic_data_to_the_day_it_could_be_seen():
    um = pd.Series([100.0, 90.0], index=pd.to_datetime(["2020-03-01", "2020-04-01"]), name="UMCSENT")
    a = ca.available(um)
    assert a.index[0] == pd.Timestamp("2020-04-01"), "3 月的消费者信心 4 月 1 日才算看得到"
    vix = pd.Series([20.0], index=pd.to_datetime(["2020-03-16"]), name="VIXCLS")
    assert ca.available(vix).index[0] == pd.Timestamp("2020-03-16"), "市场价格当天就看得到"
    assert ca.available(vix, "NFCI").index[0] == pd.Timestamp("2020-03-21")


def test_phase_returns_and_trend_reference():
    path = list(np.linspace(100, 200, 300)) + list(np.linspace(200, 100, 100)) + list(np.linspace(100, 150, 200))
    p = _price(path)
    ep = ca.bear_episodes(p, 0.2)[0]
    ph = ca.phase_returns(p, ep, pre_days=60, post_days=120)
    assert ph["crash"] is not None and abs(ph["crash"] + 0.5) < 1e-9 and ph["pre"] > 0 and ph["recovery"] > 0
    nav = ca.trend_200_nav(p)
    assert abs(nav.iloc[199] - 1.0) < 1e-12, "前 200 天没有均线 ⇒ 不持有"
    assert nav.loc[ep["trough_d"]] > p.loc[ep["trough_d"]] / p.loc[ep["peak_d"]], "趋势规则在这段下跌里少亏"
