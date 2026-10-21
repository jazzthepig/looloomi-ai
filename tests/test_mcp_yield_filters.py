"""10-21:`cometcloud_get_defi_yields` 把每个池子的 TVL 都印成 $0(读 `tvlUsd`,API 写的是 `tvl_usd`),
又没有池子规模下限,于是 $1M 的激励池以 900% APY 排第一 —— 对「闲置现金放哪」这个最常见的问题毫无用处。"""
from src.mcp.yield_filters import _pool_tvl, filter_yield_pools

POOLS = [{"project": "concrete", "symbol": "SRROYUSDC", "tvl_usd": 4_906_355, "apy": 988.9},
         {"project": "aave-v3", "symbol": "USDC", "tvl_usd": 3_200_000_000, "apy": 3.8},
         {"project": "aave-v3", "symbol": "USDT", "tvlUsd": 4_500_000_000, "apy": 3.1},
         {"project": "uniswap-v3", "symbol": "USDC-WETH", "tvl_usd": 300_000_000, "apy": 12.0},
         {"error": "upstream"}]


def test_tvl_is_read_from_either_spelling():
    assert _pool_tvl(POOLS[0]) == 4_906_355 and _pool_tvl(POOLS[2]) == 4_500_000_000 and _pool_tvl({}) == 0.0


def test_small_incentive_pools_drop_and_stablecoin_only_keeps_parking_spots():
    top = filter_yield_pools(POOLS, 0.0, 10_000_000, False, 10)
    assert [p["symbol"] for p in top] == ["USDC-WETH", "USDC", "USDT"]
    park = filter_yield_pools(POOLS, 0.0, 10_000_000, True, 10)
    assert [p["symbol"] for p in park] == ["USDC", "USDT"]
