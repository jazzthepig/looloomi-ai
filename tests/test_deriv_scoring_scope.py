"""S-687 附记二(2026-10-26):衍生品项「只展示不计分」只针对 CoinGecko 聚合源。

第一版写成「只有 venue_consolidated 计分」,把**正式标准重建**传进来的 Binance 日均 funding(不带 source)
一起关了 —— 周一全量重建把 cis_rebuild_daily 7.9 万行按「无 funding」重写。这里钉住三种来源各自的待遇。
"""
from src.data.cis.cis_provider import CG_AGG_SOURCE, calculate_cis_score

MD = {"price": 1.0, "market_cap": 2e9, "volume_24h": 1e8, "change_24h": 1.0, "change_7d": 2.0, "change_30d": 5.0,
      "ath_change_percentage": -60.0, "fdv": 2.2e9, "circulating_supply": 9e8, "total_supply": 1e9}


def _o(deriv: dict) -> float:
    return calculate_cis_score(MD, 1e8, {"value": 50}, "L1", asset_id="OP", btc_change_30d=3.0,
                               _deriv_map=deriv, _trend_map={})["O"]


def test_official_rebuild_funding_still_moves_the_o_pillar():
    base = _o({})
    reb = _o({"OP": {"funding_rate": -0.000105, "funding_signal": "binance_perp_daily_mean"}})
    assert round(reb - base, 1) == 2.0, "rebuild passes Binance daily-mean funding without a source; it must score"


def test_venue_consolidated_still_scores():
    base = _o({})
    ven = _o({"OP": {"funding_rate": -0.000105, "funding_signal": "cross_venue", "source": "venue_consolidated"}})
    assert ven != base


def test_coingecko_aggregate_is_display_only():
    base = _o({})
    cg = _o({"OP": {"funding_rate": -0.000105, "funding_signal": "bearish_basis", "source": CG_AGG_SOURCE,
                    "open_interest_usd": 5e9}})
    assert cg == base
