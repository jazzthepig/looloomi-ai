"""S-689 补数(Jazz 10-26「分开来」):符号换算、候选先后、价格校验 —— 撞名不猜,用 Binance 隐含价对。"""
from src.data.market.perp_mcap_backfill import (MAX_CALLS_PER_RUN, accept, implied_prices, order_candidates,
                                                price_check, query_symbol)


def test_query_symbol_prefix_and_specials():
    assert query_symbol("1000SHIB") == ("SHIB", 1000)
    assert query_symbol("1000LUNC") == ("LUNC", 1000)
    assert query_symbol("LUNA2") == ("LUNA", 1)
    assert query_symbol("NEIROETH") == ("NEIRO", 1)
    assert query_symbol("42") == ("42", 1)
    assert query_symbol("OMG") == ("OMG", 1)


def test_candidates_same_name_first_and_deduped():
    assert order_candidates("OMG", ["omg-network-fake", "omisego", "omg", "omisego"])[0] == "omg"
    assert order_candidates("TRU", ["truefi", "trubit", "tru"]) == ["tru", "trubit", "truefi"]


def test_price_check_picks_the_coin_that_trades_at_the_binance_price():
    implied = implied_prices([{"d": f"2024-01-{i:02d}", "oi_value_close": 1000.0 * (1 + i / 100), "oi_close": 100.0}
                              for i in range(1, 32)] + [{"d": "2024-02-01", "oi_value_close": 5, "oi_close": 0}])
    assert len(implied) == 31
    right = [{"d": d, "price": p / 1000 * 1.01} for d, p in implied.items()]    # 1000 前缀:CG 价 × 1000 = 合约价
    wrong = [{"d": d, "price": p * 3} for d, p in implied.items()]
    err, n = price_check(right, implied, 1000)
    assert n == 31 and abs(err - 0.01) < 1e-9 and accept(err, n)
    err2, n2 = price_check(wrong, implied, 1000)
    assert not accept(err2, n2)
    assert not accept(*price_check(right[:10], implied, 1000)), "under 30 overlapping days is not enough"


def test_paced():
    assert MAX_CALLS_PER_RUN <= 3


def test_wrappers_dropped_and_largest_cap_first():
    ids = ["shibaqua", "shiba-inu", "shiba-inu-wormhole", "binance-peg-shib", "shib-on-solana"]
    out = order_candidates("SHIB", ids, {"shiba-inu": 6e9, "shibaqua": 1e5, "shib-on-solana": 2e6})
    assert out[0] == "shiba-inu" and "shiba-inu-wormhole" not in out and "binance-peg-shib" not in out
    assert order_candidates("FXS", ["frax-share-wormhole", "linea-bridged-fxs-linea", "flexstay"]) == ["flexstay"]
    assert "neiro-on-eth" in order_candidates("NEIRO", ["neiro", "neiro-on-eth"]), "-on-eth is the real coin here"


def test_top_up_picks_live_stale_coins_oldest_first():
    from datetime import date
    from src.data.market.perp_mcap_backfill import stale_coins
    resolved = [{"symbol": "1000SHIB", "coin_id": "shiba-inu"}, {"symbol": "OMG", "coin_id": "omisego"},
                {"symbol": "IP", "coin_id": "story-2"}, {"symbol": "VANRY", "coin_id": "vanar-chain"}]
    last_cg = {"shiba-inu": "2026-10-20", "omisego": "2025-01-31", "story-2": "2026-10-26", "vanar-chain": "2026-10-10"}
    last_oi = {"1000SHIB": "2026-10-26", "OMG": "2025-01-31", "IP": "2026-10-26", "VANRY": "2026-10-25"}
    out = stale_coins(resolved, last_cg, last_oi, date(2026, 10, 27))
    assert [m["symbol"] for m in out] == ["VANRY", "1000SHIB"], "delisted OMG skipped; IP already current"
