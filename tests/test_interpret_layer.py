"""T-040 解读层:相似日只来自过去、标准化只用过去、前向结果与实际结果分开、说明不含仓位建议。"""
import numpy as np
import pandas as pd

from src.data.interpret import interpret as it


def _levels(n=900, seed=0):
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    rng = np.random.default_rng(seed)
    cols = {s: 100 * np.exp(np.cumsum(0.03 * rng.standard_normal(n)))
            for s in ("majors", "top_l1", "second_l1_l2", "app", "ai", "meme")}
    return pd.DataFrame(cols, index=idx)


def test_analogs_are_only_from_before_d_minus_30_and_spaced_apart():
    lv = _levels()
    st = it.style_state(lv)
    d = lv.index[700]
    an = it.analogs(st, d)
    assert an and all(pd.Timestamp(x) <= d - pd.Timedelta(days=30) for x, _ in an)
    ds = sorted(pd.Timestamp(x) for x, _ in an)
    assert all((b - a).days >= it.SPACING_DAYS for a, b in zip(ds, ds[1:]))


def test_changing_the_future_does_not_change_todays_analogs():
    """PIT:把 d 之后的数据全部改掉,d 的相似日不变(标准化只用过去)。"""
    lv = _levels()
    d = lv.index[600]
    a1 = it.analogs(it.style_state(lv), d)
    lv2 = lv.copy()
    lv2.loc[lv2.index > d] *= 7.0
    a2 = it.analogs(it.style_state(lv2), d)
    assert a1 == a2


def test_an_exact_repeat_of_history_is_found():
    lv = _levels()
    st = it.style_state(lv)
    st.loc[lv.index[800]] = st.loc[lv.index[400]]            # 让第 800 天的状态与第 400 天完全一样
    an = it.analogs(st, lv.index[800], k=3)
    assert an[0][0] == lv.index[400].date().isoformat() and an[0][1] > 0.999


def test_forward_returns_and_spreads():
    lv = _levels()
    d = lv.index[100]
    f = it.forward_returns(lv, d)
    exp = lv.loc[d + pd.Timedelta(days=30), "meme"] / lv.loc[d, "meme"] - 1
    assert abs(f["meme"] - exp) < 1e-12
    assert abs(f["meme-majors"] - (f["meme"] - f["majors"])) < 1e-12
    assert it.forward_returns(lv, lv.index[-5]) == {}            # 前瞻还没走完 ⇒ 空,不是 0


def test_day_row_keeps_prediction_and_realized_apart_and_no_position_language():
    lv = _levels()
    spaces = {"style": it.style_state(lv)}
    row = it.interpret_day(lv.index[700], lv, spaces, {"meme": "meme", "ai": "AI"})
    assert row["angles"]["style"]["analogs"] and row["pooled"] and row["realized"]
    assert all(pd.Timestamp(x) < lv.index[700] for x, _ in row["angles"]["style"]["analogs"])
    for w in ("买", "卖", "加仓", "减仓", "BUY", "SELL"):
        assert w not in row["narrative"]
    last = it.interpret_day(lv.index[-1], lv, spaces, {})
    assert last["realized"] is None                                 # 30 天后才对账


def test_thin_history_gives_no_angle_rather_than_a_guess():
    lv = _levels(n=100)
    assert it.analogs(it.style_state(lv), lv.index[-1]) == []


def test_agreement_needs_three_shared_spreads():
    a = {"meme-majors": {"median": 0.1}, "ai-majors": {"median": -0.1}, "app-majors": {"median": 0.2}}
    b = {"meme-majors": {"median": 0.3}, "ai-majors": {"median": 0.1}, "app-majors": {"median": 0.1}}
    assert abs(it.agreement(a, b) - 2 / 3) < 1e-12
    assert it.agreement({"meme-majors": {"median": 1}}, {"meme-majors": {"median": 1}}) is None
