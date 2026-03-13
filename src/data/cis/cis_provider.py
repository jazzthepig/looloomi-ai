"""
CIS Data Provider - Real-time CIS scoring from market data
===========================================================
Fetches real market data and calculates CIS scores using the scoring engine.

Author: Terry
"""

import httpx
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# CoinGecko API base
CG_BASE = "https://api.coingecko.com/api/v3"

# Asset configuration - maps to CoinGecko IDs
ASSETS_CONFIG = {
    "BTC": {"coingecko": "bitcoin", "name": "Bitcoin", "class": "Crypto"},
    "ETH": {"coingecko": "ethereum", "name": "Ethereum", "class": "Crypto"},
    "SOL": {"coingecko": "solana", "name": "Solana", "class": "L1"},
    "BNB": {"coingecko": "binancecoin", "name": "BNB", "class": "L1"},
    "AVAX": {"coingecko": "avalanche-2", "name": "Avalanche", "class": "L1"},
    "ARB": {"coingecko": "arbitrum", "name": "Arbitrum", "class": "L2"},
    "OP": {"coingecko": "optimism", "name": "Optimism", "class": "L2"},
    "MATIC": {"coingecko": "matic-network", "name": "Polygon", "class": "L2"},
    "LINK": {"coingecko": "chainlink", "name": "Chainlink", "class": "Infrastructure"},
    "UNI": {"coingecko": "uniswap", "name": "Uniswap", "class": "DeFi"},
    "AAVE": {"coingecko": "aave", "name": "Aave", "class": "DeFi"},
    "DOT": {"coingecko": "polkadot", "name": "Polkadot", "class": "L1"},
    "ONDO": {"coingecko": "ondo-finance", "name": "Ondo Finance", "class": "RWA"},
    "BLUR": {"coingecko": "blur", "name": "Blur", "class": "NFT"},
    "IMX": {"coingecko": "immutable-x", "name": "Immutable", "class": "L2"},
    "RPL": {"coingecko": "rocket-pool", "name": "Rocket Pool", "class": "DeFi"},
    "MKR": {"coingecko": "maker", "name": "Maker", "class": "DeFi"},
    "SNX": {"coingecko": "havven", "name": "Synthetix", "class": "DeFi"},
    "CRV": {"coingecko": "curve-dao-token", "name": "Curve", "class": "DeFi"},
    "LDO": {"coingecko": "lido-dao", "name": "Lido DAO", "class": "DeFi"},
}

# Cache
_cache: Dict = {}
_cache_ttl = 300  # 5 minutes


def _cache_get(key: str) -> Optional[Any]:
    if key in _cache:
        val, ts = _cache[key]
        if datetime.now().timestamp() - ts < _cache_ttl:
            return val
    return None


def _cache_set(key: str, val: Any):
    _cache[key] = (val, datetime.now().timestamp())
    return val


async def fetch_cg_markets() -> Dict[str, dict]:
    """Fetch all market data from CoinGecko."""
    cache_key = "cg_markets"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Fetch top 100 coins
            url = f"{CG_BASE}/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 100,
                "page": 1,
                "sparkline": False,
                "price_change_percentage": "30d"
            }
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()

            result = {}
            for coin in data:
                result[coin["id"]] = {
                    "symbol": coin["symbol"].upper(),
                    "name": coin["name"],
                    "market_cap": coin.get("market_cap", 0),
                    "volume_24h": coin.get("total_volume", 0),
                    "price": coin.get("current_price", 0),
                    "change_24h": coin.get("price_change_percentage_24h", 0),
                    "change_30d": coin.get("price_change_percentage_30d", 0),
                    "circulating_supply": coin.get("circulating_supply", 0),
                    "total_supply": coin.get("total_supply", 0),
                    "ath_change_percentage": coin.get("ath_change_percentage", 0),
                }

            return _cache_set(cache_key, result)
    except Exception as e:
        print(f"CoinGecko API error: {e}")
        return {}


async def fetch_defillama_tvl() -> Dict[str, float]:
    """Fetch TVL data from DeFiLlama."""
    cache_key = "llama_tvl"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.llama.fi/protocols")
            r.raise_for_status()
            protocols = r.json()

            result = {}
            for p in protocols:
                # Match by ticker symbol
                slug = p.get("slug", "").lower()
                symbol = p.get("symbol", "").upper()
                tvl = p.get("tvl", 0)

                # Map to our config
                for asset_id, config in ASSETS_CONFIG.items():
                    if config["coingecko"].lower() == slug or symbol == asset_id:
                        result[asset_id] = tvl
                        break

            return _cache_set(cache_key, result)
    except Exception as e:
        print(f"DeFiLlama API error: {e}")
        return {}


async def fetch_fear_greed() -> Optional[dict]:
    """Fetch Fear & Greed index."""
    cache_key = "fear_greed"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.alternative.me/fng/")
            r.raise_for_status()
            data = r.json()
            return _cache_set(cache_key, data.get("data", [{}])[0])
    except Exception as e:
        print(f"Fear&Greed API error: {e}")
        return None


def get_asset_class(asset_id: str) -> str:
    """Get asset class from config."""
    if asset_id in ASSETS_CONFIG:
        return ASSETS_CONFIG[asset_id]["class"]
    return "Crypto"


def calculate_cis_score(
    market_data: dict,
    tvl: float,
    fng: Optional[dict],
    asset_class: str
) -> Dict[str, Any]:
    """
    Calculate CIS scores based on real market data.
    Uses the five-pillar model: F, M, O, S, A (alpha)
    """

    # === Fundamental Score (F) - 25% default ===
    # Based on: product age (proxy by market cap), exchange listings, partnerships
    f_score = 50  # base

    market_cap = market_data.get("market_cap", 0) if market_data else 0
    if market_cap > 10e9:  # > $10B
        f_score += 30
    elif market_cap > 1e9:  # > $1B
        f_score += 25
    elif market_cap > 100e6:  # > $100M
        f_score += 20
    elif market_cap > 10e6:  # > $10M
        f_score += 15
    elif market_cap > 0:
        f_score += 10

    # Circulating supply ratio bonus
    circ_supply = market_data.get("circulating_supply", 0) if market_data else 0
    total_supply = market_data.get("total_supply", 0) if market_data else 0
    if total_supply > 0 and circ_supply > 0:
        ratio = circ_supply / total_supply
        if ratio >= 0.7:
            f_score += 15
        elif ratio >= 0.5:
            f_score += 10
        elif ratio >= 0.3:
            f_score += 5

    f_score = min(100, f_score)

    # === Market Structure Score (M) - 25% default ===
    # Based on: volume, liquidity, market cap
    m_score = 30  # base

    volume_24h = market_data.get("volume_24h", 0) if market_data else 0
    if volume_24h > 1e9:  # > $1B daily
        m_score += 35
    elif volume_24h > 100e6:
        m_score += 30
    elif volume_24h > 10e6:
        m_score += 20
    elif volume_24h > 1e6:
        m_score += 15
    elif volume_24h > 0:
        m_score += 10

    # Volume/MCap ratio (liquidity indicator)
    if market_cap > 0:
        vol_ratio = volume_24h / market_cap
        if vol_ratio > 0.3:
            m_score += 20
        elif vol_ratio > 0.1:
            m_score += 15
        elif vol_ratio > 0.05:
            m_score += 10

    # TVL bonus for DeFi/L2
    if asset_class in ["DeFi", "L2"] and tvl > 0:
        if tvl > 1e9:
            m_score += 15
        elif tvl > 100e6:
            m_score += 10
        elif tvl > 10e6:
            m_score += 5

    m_score = min(100, m_score)

    # === On-Chain Health Score (O) - 20% default ===
    # Based on: TVL, ATH distance (indicates maturity)
    o_score = 40  # base

    if asset_class == "DeFi":
        if tvl > 1e9:
            o_score += 35
        elif tvl > 100e6:
            o_score += 25
        elif tvl > 10e6:
            o_score += 15
        elif tvl > 1e6:
            o_score += 10
    else:
        # For non-DeFi, use ATH distance as proxy
        ath_distance = abs(market_data.get("ath_change_percentage", 0)) if market_data else 50
        if ath_distance < 20:  # Near ATH
            o_score += 30
        elif ath_distance < 50:
            o_score += 20
        elif ath_distance < 70:
            o_score += 10

    # Supply health
    if total_supply > 0:
        circ_ratio = circ_supply / total_supply
        if circ_ratio > 0.5:
            o_score += 15

    o_score = min(100, o_score)

    # === Sentiment Score (S) - 15% default ===
    # Based on: Fear & Greed, price momentum
    s_score = 50  # base

    if fng:
        fng_value = int(fng.get("value", 50))
        if fng_value > 75:  # Extreme Greed
            s_score = 85
        elif fng_value > 65:  # Greed
            s_score = 75
        elif fng_value > 55:  # Neutral
            s_score = 60
        elif fng_value > 35:  # Fear
            s_score = 45
        else:  # Extreme Fear
            s_score = 30

    # 30d price change
    change_30d = market_data.get("change_30d", 0) if market_data else 0
    if change_30d > 50:
        s_score = min(100, s_score + 15)
    elif change_30d > 20:
        s_score = min(100, s_score + 10)
    elif change_30d < -30:
        s_score = max(0, s_score - 15)
    elif change_30d < -15:
        s_score = max(0, s_score - 10)

    # === Alpha Independence Score (A) - 15% default ===
    # Lower correlation = higher alpha score
    # We use ATH distance as a proxy for independence
    a_score = 50  # base

    ath_distance = abs(market_data.get("ath_change_percentage", 0)) if market_data else 0
    if asset_class in ["DeFi", "RWA", "L2"]:
        # These are more independent
        a_score += 20
    elif asset_class == "L1":
        a_score += 15

    # Large market cap = more established = less alpha
    if market_cap > 10e9:
        a_score -= 10
    elif market_cap > 1e9:
        a_score -= 5

    # Price independence (distance from ATH)
    if 30 < ath_distance < 70:  # Sweet spot
        a_score += 15
    elif ath_distance < 10:  # Too close to ATH (potential pullback)
        a_score -= 10

    a_score = max(0, min(100, a_score))

    return {
        "F": round(f_score, 1),
        "M": round(m_score, 1),
        "O": round(o_score, 1),
        "S": round(s_score, 1),
        "A": round(a_score, 1),
    }


def calculate_total_score(pillars: Dict[str, float], asset_class: str) -> float:
    """Calculate weighted total CIS score."""

    # Default weights
    weights = {
        "Crypto": {"F": 0.25, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.15},
        "L1": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "L2": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "DeFi": {"F": 0.25, "M": 0.25, "O": 0.25, "S": 0.15, "A": 0.10},
        "RWA": {"F": 0.35, "M": 0.20, "O": 0.20, "S": 0.15, "A": 0.10},
        "Infrastructure": {"F": 0.30, "M": 0.20, "O": 0.25, "S": 0.10, "A": 0.15},
        "NFT": {"F": 0.15, "M": 0.25, "O": 0.15, "S": 0.30, "A": 0.15},
    }

    w = weights.get(asset_class, weights["Crypto"])

    total = (
        w["F"] * pillars["F"] +
        w["M"] * pillars["M"] +
        w["O"] * pillars["O"] +
        w["S"] * pillars["S"] +
        w["A"] * pillars["A"]
    )

    return round(total, 1)


def get_grade(score: float) -> str:
    """Get letter grade from score."""
    if score >= 85:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 50:
        return "C+"
    elif score >= 40:
        return "C"
    elif score >= 30:
        return "D"
    return "F"


def get_signal(score: float, grade: str) -> str:
    """Get trading signal from score."""
    if grade in ["A+", "A"]:
        return "STRONG OVERWEIGHT"
    elif grade in ["B+", "B"]:
        return "OVERWEIGHT"
    elif grade == "C":
        return "NEUTRAL"
    else:
        return "UNDERWEIGHT"


async def calculate_cis_universe() -> Dict[str, Any]:
    """
    Calculate CIS scores for all tracked assets.
    Returns the complete universe with scores.
    """
    # Fetch all data concurrently
    cg_markets, llama_tvl, fng = await asyncio.gather(
        fetch_cg_markets(),
        fetch_defillama_tvl(),
        fetch_fear_greed()
    )

    # Macro regime determination
    btc_data = cg_markets.get("bitcoin", {})
    btc_30d = btc_data.get("change_30d", 0) if btc_data else 0
    fng_value = int(fng.get("value", 50)) if fng else 50

    if btc_30d > 5 and fng_value > 55:
        regime = "Risk-On"
    elif btc_30d < -10 or fng_value < 35:
        regime = "Risk-Off"
    else:
        regime = "Neutral"

    # Calculate scores for each asset
    universe = []

    for asset_id, config in ASSETS_CONFIG.items():
        cg_id = config["coingecko"]
        asset_class = config["class"]

        market_data = cg_markets.get(cg_id, {})
        tvl = llama_tvl.get(asset_id, 0)

        # Skip if no market data
        if not market_data:
            continue

        # Calculate pillar scores
        pillars = calculate_cis_score(market_data, tvl, fng, asset_class)

        # Calculate total
        total_score = calculate_total_score(pillars, asset_class)
        grade = get_grade(total_score)
        signal = get_signal(total_score, grade)

        # 30d change
        change_30d = market_data.get("change_30d", 0) or 0

        # Percentile (simplified - based on score)
        percentile = int(min(99, max(1, total_score)))

        universe.append({
            "symbol": asset_id,
            "name": config["name"],
            "asset_class": asset_class,
            "cis_score": total_score,
            "grade": grade,
            "signal": signal,
            "f": pillars["F"],
            "m": pillars["M"],
            "r": pillars["O"],
            "s": pillars["S"],
            "a": pillars["A"],
            "change_30d": round(change_30d, 1),
            "percentile": percentile,
            "market_cap": market_data.get("market_cap", 0),
            "volume_24h": market_data.get("volume_24h", 0),
            "tvl": tvl,
        })

    # Sort by CIS score
    universe.sort(key=lambda x: x["cis_score"], reverse=True)

    # Get macro data
    macro = {
        "regime": regime,
        "fed_funds": 5.25,  # Would need real Fed data
        "treasury_10y": 4.25,  # Would need real Treasury data
        "vix": 18.0,  # Would need real VIX
        "dxy": 104.0,  # Would need real DXY
        "cpi_yoy": 3.2,  # Would need real CPI
    }

    return {
        "status": "success",
        "version": "4.0.0",
        "timestamp": datetime.now().isoformat(),
        "data_source": "coingecko+defillama",
        "macro": macro,
        "universe": universe,
    }


# Test
if __name__ == "__main__":
    import json
    result = asyncio.run(calculate_cis_universe())
    print(json.dumps(result, indent=2))
