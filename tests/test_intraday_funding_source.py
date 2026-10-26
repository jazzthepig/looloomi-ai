"""S-688(2026-10-26):盘中 O 支柱的 funding 项与正式标准同源 —— Binance 永续按 UTC 日取平均,读本库,不打交易所。"""
from src.data.cis.cis_provider import BINANCE_DAILY_SOURCE, calculate_cis_score, latest_binance_funding

EV = [
    {"symbol": "NEAR", "funding_time": "2026-10-25T00:00:00+00:00", "funding_rate": 0.0001},
    {"symbol": "NEAR", "funding_time": "2026-10-25T08:00:00+00:00", "funding_rate": 0.0002},
    {"symbol": "NEAR", "funding_time": "2026-10-25T16:00:00+00:00", "funding_rate": 0.0003},
    {"symbol": "NEAR", "funding_time": "2026-10-26T00:00:00+00:00", "funding_rate": -0.0002},
    {"symbol": "OP", "funding_time": "2026-10-25T16:00:00+00:00", "funding_rate": -0.0004},
    {"symbol": "OP", "funding_time": "2026-10-26T07:00:00+09:00", "funding_rate": 0.0009},   # = 10-25 22:00 UTC
    {"symbol": "XRP", "funding_time": "2026-10-27T00:00:00Z", "funding_rate": 0.01},          # 明天:不该出现
]


def test_latest_utc_day_mean_today_partial_else_yesterday():
    m = latest_binance_funding(EV, "2026-10-26")
    assert m["NEAR"]["funding_day"] == "2026-10-26" and m["NEAR"]["partial_day"] is True
    assert abs(m["NEAR"]["funding_rate"] + 0.0002) < 1e-12 and m["NEAR"]["n_settlements"] == 1
    assert m["OP"]["funding_day"] == "2026-10-25" and m["OP"]["partial_day"] is False
    assert abs(m["OP"]["funding_rate"] - 0.00025) < 1e-12, "+09:00 timestamp belongs to the 10-25 UTC day"
    assert "XRP" not in m
    assert m["NEAR"]["source"] == BINANCE_DAILY_SOURCE


def test_binance_daily_mean_scores_like_the_official_rebuild():
    md = {"price": 1.0, "market_cap": 2e9, "volume_24h": 1e8, "change_24h": 1.0, "change_7d": 2.0, "change_30d": 5.0,
          "ath_change_percentage": -60.0, "fdv": 2.2e9, "circulating_supply": 9e8, "total_supply": 1e9}

    def o(dm):
        return calculate_cis_score(md, 1e8, {"value": 50}, "L1", asset_id="OP", btc_change_30d=3.0,
                                   _deriv_map=dm, _trend_map={})["O"]
    fr = -0.000105
    official = o({"OP": {"funding_rate": fr, "funding_signal": "binance_perp_daily_mean"}})
    intraday = o(latest_binance_funding([{"symbol": "OP", "funding_time": "2026-10-26T00:00:00+00:00",
                                          "funding_rate": fr}], "2026-10-26"))
    assert official == intraday
