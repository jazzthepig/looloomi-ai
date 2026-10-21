"""Pure filters for `cometcloud_get_defi_yields` (kept out of cometcloud_mcp so they test without the mcp package).

10-21: the tool printed TVL $0 for every pool (it read `tvlUsd`, the API writes `tvl_usd`) and, with no pool-size floor,
ranked $1M incentive pools at 900% APY first — useless for the question it is asked most: where can idle cash sit.
"""
from __future__ import annotations

#: single-asset stablecoin symbols as DeFiLlama writes them (a pool like "USDC-ETH" is not a parking spot)
_STABLE_SYMBOLS = frozenset({"USDC", "USDT", "DAI", "USDS", "USDE", "SUSDE", "SUSDS", "SDAI", "PYUSD", "FDUSD",
                             "USDT0", "USDC.E", "GHO", "FRAX", "LUSD", "RLUSD", "USD1", "USDG"})


def _pool_tvl(p: dict) -> float:
    """The API writes `tvl_usd`; DeFiLlama raw writes `tvlUsd`. Reading only one of them printed $0 for every pool."""
    v = p.get("tvl_usd", p.get("tvlUsd"))
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def filter_yield_pools(pools: list, min_apy: float, min_tvl_usd: float, stablecoin_only: bool, limit: int) -> list:
    """Pure. TVL floor first, then APY floor, optional single-asset stablecoin filter, sorted by APY."""
    out = [p for p in pools if isinstance(p, dict) and "error" not in p
           and _pool_tvl(p) >= min_tvl_usd and float(p.get("apy") or 0) >= min_apy
           and (not stablecoin_only or str(p.get("symbol") or "").upper() in _STABLE_SYMBOLS)]
    return sorted(out, key=lambda p: float(p.get("apy") or 0), reverse=True)[:limit]
