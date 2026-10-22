"""CIS v2 状态层(S-669):标签定义一字不差;短历史口径标出来;动量 / 资金费只给数值;情绪是组级;永远不是预测。"""
import datetime as dt

from src.data.cis import v2_state as st


def test_trend_labels_follow_s669():
    up = [100 + i for i in range(220)]
    assert st.trend(up)["label"] == "up" and st.trend(up)["basis"] == "sma50_sma200"
    down = [400 - i for i in range(220)]
    assert st.trend(down)["label"] == "down"
    chop = [100 + (i % 2) * 3 for i in range(220)]
    assert st.trend(chop)["label"] == "range"
    short = [100 + i for i in range(80)]
    assert st.trend(short) == {"label": "up", "basis": "short_history", "close_vs_sma50": st.trend(short)["close_vs_sma50"]}
    assert st.trend([1.0] * 10)["label"] is None


def test_momentum_and_funding_are_numbers_not_labels():
    base = dt.date(2026, 9, 1)
    series = [((base + dt.timedelta(days=i)).isoformat(), 100.0 + i) for i in range(51)]
    assert st.momentum_30d(series, "2026-10-21") == round(150 / 120 - 1, 4)
    rows = [{"venue": "hyperliquid", "funding_time": "2026-10-20T01:00:00Z", "funding_rate": 0.00001},
            {"venue": "binance_perp", "funding_time": "2026-10-20T08:00:00Z", "funding_rate": 0.0001}]
    f = st.funding_apr_7d(rows, "2026-10-21")
    assert f["venue"] == "binance_perp" and f["apr"] == round(0.0001 * 3 * 365, 4), "先币安,年化按 8 小时一期"
    assert st.funding_apr_7d(rows[:1], "2026-10-21")["apr"] == round(0.00001 * 24 * 365, 4), "Hyperliquid 每小时一期"
    assert st.funding_apr_7d([], "2026-10-21") is None


def test_market_mood_is_group_level_and_state_never_claims_to_forecast():
    assert st.sentiment("crypto", 80)["label"] == "greed" and st.sentiment("crypto", 20)["label"] == "fear"
    assert st.sentiment("equity", 30)["label"] == "stress" and st.sentiment("equity", 12)["label"] == "calm"
    s = st.state_for("equity", [], "2026-10-21", (), None)
    assert s["is_forecast"] is False and "funding_7d" not in s and s["market"]["label"] is None
