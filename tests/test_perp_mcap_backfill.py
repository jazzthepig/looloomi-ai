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
