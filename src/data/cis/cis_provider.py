"""
CIS Data Provider - Real-time CIS scoring from market data
===========================================================
Fetches real market data and calculates CIS scores using the scoring engine.

Author: Seth
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

# Crypto assets config - maps to CoinGecko IDs
CRYPTO_ASSETS = {
    # L1
    "BTC": {"coingecko": "bitcoin", "name": "Bitcoin", "class": "Crypto"},
    "ETH": {"coingecko": "ethereum", "name": "Ethereum", "class": "Crypto"},
    "SOL": {"coingecko": "solana", "name": "Solana", "class": "L1"},
    "BNB": {"coingecko": "binancecoin", "name": "BNB", "class": "L1"},
    "AVAX": {"coingecko": "avalanche-2", "name": "Avalanche", "class": "L1"},
    "DOT": {"coingecko": "polkadot", "name": "Polkadot", "class": "L1"},
    "ADA": {"coingecko": "cardano", "name": "Cardano", "class": "L1"},
    "XRP": {"coingecko": "ripple", "name": "XRP", "class": "L1"},
    "DOGE": {"coingecko": "dogecoin", "name": "Dogecoin", "class": "L1"},
    "TON": {"coingecko": "the-open-network", "name": "Toncoin", "class": "L1"},
    # L2
    "ARB": {"coingecko": "arbitrum", "name": "Arbitrum", "class": "L2"},
    "OP": {"coingecko": "optimism", "name": "Optimism", "class": "L2"},
    "MATIC": {"coingecko": "matic-network", "name": "Polygon", "class": "L2"},
    "IMX": {"coingecko": "immutable-x", "name": "Immutable", "class": "L2"},
    "BASE": {"coingecko": "base", "name": "Base", "class": "L2"},
    "MANTLE": {"coingecko": "mantle", "name": "Mantle", "class": "L2"},
    # DeFi
    "UNI": {"coingecko": "uniswap", "name": "Uniswap", "class": "DeFi"},
    "AAVE": {"coingecko": "aave", "name": "Aave", "class": "DeFi"},
    "MKR": {"coingecko": "maker", "name": "Maker", "class": "DeFi"},
    "SNX": {"coingecko": "havven", "name": "Synthetix", "class": "DeFi"},
    "CRV": {"coingecko": "curve-dao-token", "name": "Curve", "class": "DeFi"},
    "LDO": {"coingecko": "lido-dao", "name": "Lido DAO", "class": "DeFi"},
    "RPL": {"coingecko": "rocket-pool", "name": "Rocket Pool", "class": "DeFi"},
    "COMP": {"coingecko": "compound-governance-token", "name": "Compound", "class": "DeFi"},
    "SUSHI": {"coingecko": "sushi", "name": "SushiSwap", "class": "DeFi"},
    # Infrastructure
    "LINK": {"coingecko": "chainlink", "name": "Chainlink", "class": "Infrastructure"},
    "STX": {"coingecko": "stacks", "name": "Stacks", "class": "Infrastructure"},
    "RUNE": {"coingecko": "thorchain", "name": "THORChain", "class": "Infrastructure"},
    "INJ": {"coingecko": "injective-protocol", "name": "Injective", "class": "Infrastructure"},
    # RWA
    "ONDO": {"coingecko": "ondo-finance", "name": "Ondo Finance", "class": "RWA"},
    "GENIUS": {"coingecko": "genius", "name": "Genius", "class": "RWA"},
    "POLYX": {"coingecko": "polymesh", "name": "Polymesh", "class": "RWA"},
    # Memecoin (满足门槛的)
    "PEPE": {"coingecko": "pepe", "name": "Pepe", "class": "Memecoin"},
}

# US Equities - yfinance symbols
US_EQUITIES = {
    "SPY": {"yfinance": "SPY", "name": "S&P 500 ETF", "class": "US Equity"},
    "QQQ": {"yfinance": "QQQ", "name": "Nasdaq 100 ETF", "class": "US Equity"},
    "AAPL": {"yfinance": "AAPL", "name": "Apple", "class": "US Equity"},
    "MSFT": {"yfinance": "MSFT", "name": "Microsoft", "class": "US Equity"},
    "NVDA": {"yfinance": "NVDA", "name": "NVIDIA", "class": "US Equity"},
    "GOOGL": {"yfinance": "GOOGL", "name": "Alphabet", "class": "US Equity"},
    "AMZN": {"yfinance": "AMZN", "name": "Amazon", "class": "US Equity"},
    "META": {"yfinance": "META", "name": "Meta", "class": "US Equity"},
    "TSLA": {"yfinance": "TSLA", "name": "Tesla", "class": "US Equity"},
    "BRK.B": {"yfinance": "BRK-B", "name": "Berkshire", "class": "US Equity"},
}

# Bonds - yfinance symbols
BONDS = {
    "TLT": {"yfinance": "TLT", "name": "20+ Year Treasury Bond ETF", "class": "US Bond"},
    "IEF": {"yfinance": "IEF", "name": "7-10 Year Treasury Bond ETF", "class": "US Bond"},
    "SHY": {"yfinance": "SHY", "name": "1-3 Year Treasury Bond ETF", "class": "US Bond"},
    "HYG": {"yfinance": "HYG", "name": "High Yield Bond ETF", "class": "US Bond"},
    "LQD": {"yfinance": "LQD", "name": "Investment Grade Bond ETF", "class": "US Bond"},
}

# Commodities - yfinance symbols
COMMODITIES = {
    "GLD": {"yfinance": "GLD", "name": "Gold ETF", "class": "Commodity"},
    "SLV": {"yfinance": "SLV", "name": "Silver ETF", "class": "Commodity"},
    "USO": {"yfinance": "USO", "name": "Oil ETF", "class": "Commodity"},
    "UNG": {"yfinance": "UNG", "name": "Natural Gas ETF", "class": "Commodity"},
    "DBC": {"yfinance": "DBC", "name": "Commodities Index ETF", "class": "Commodity"},
}

# Combined assets config
ASSETS_CONFIG = {**CRYPTO_ASSETS, **US_EQUITIES, **BONDS, **COMMODITIES}

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
    """Fetch market data from CoinGecko - top 100 for broader coverage."""
    cache_key = "cg_markets"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    result = {}
    rate_limited = False

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Fetch top 100 coins (2 pages of 50) - balance between coverage and rate limit
            for page in range(1, 3):
                try:
                    url = f"{CG_BASE}/coins/markets"
                    params = {
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": 50,
                        "page": page,
                        "sparkline": False,
                        "price_change_percentage": "30d,7d"
                    }
                    r = await client.get(url, params=params)

                    # Check for rate limit
                    if r.status_code == 429:
                        rate_limited = True
                        print(f"CoinGecko rate limited on page {page}")
                        break

                    r.raise_for_status()
                    data = r.json()

                    if not data:
                        break

                    for coin in data:
                        coin_id = coin["id"]
                        result[coin_id] = {
                            "symbol": coin["symbol"].upper(),
                            "name": coin["name"],
                            "market_cap": coin.get("market_cap", 0),
                            "volume_24h": coin.get("total_volume", 0),
                            "price": coin.get("current_price", 0),
                            "change_24h": coin.get("price_change_percentage_24h", 0),
                            "change_7d": coin.get("price_change_percentage_7d", 0),
                            "change_30d": coin.get("price_change_percentage_30d", 0),
                            "circulating_supply": coin.get("circulating_supply", 0),
                            "total_supply": coin.get("total_supply", 0),
                            "ath_change_percentage": coin.get("ath_change_percentage", 0),
                            "high_24h": coin.get("high_24h", 0),
                            "low_24h": coin.get("low_24h", 0),
                        }

                    # Small delay between pages
                    await asyncio.sleep(1)

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        rate_limited = True
                        print(f"CoinGecko rate limited on page {page}")
                        break
                    raise

            # Only cache if we got data, don't cache empty results
            if result:
                return _cache_set(cache_key, result)
            elif rate_limited:
                # Return empty but don't cache - will retry on next request
                return {}
            else:
                return {}

    except Exception as e:
        print(f"CoinGecko API error: {e}")
        return result if result else {}


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


def get_yfinance_data(symbol: str) -> Optional[dict]:
    """Fetch US equity/bond/commodity data using yfinance."""
    cache_key = f"yf:{symbol}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        import yfinance as yf
        import time

        # Rate limiting
        time.sleep(0.2)

        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Get historical data for 30d change
        hist = ticker.history(period="35d")
        if len(hist) > 30:
            price_30d_ago = hist['Close'].iloc[-31] if len(hist) > 31 else hist['Close'].iloc[0]
            price_now = hist['Close'].iloc[-1]
            change_30d = ((price_now - price_30d_ago) / price_30d_ago) * 100
        else:
            change_30d = 0

        result = {
            "symbol": symbol,
            "price": info.get("currentPrice", info.get("regularMarketPrice", 0)),
            "market_cap": info.get("marketCap", 0),
            "volume_24h": info.get("regularMarketVolume", 0),
            "change_24h": info.get("regularMarketChange", 0),
            "change_30d": change_30d,
            "circulating_supply": info.get("sharesOutstanding", 0),
            "total_supply": info.get("sharesOutstanding", 0),
            "ath_change_percentage": 0,  # yfinance doesn't provide this directly
        }
        return _cache_set(cache_key, result)
    except Exception as e:
        # Don't print on rate limit - it's expected
        if "Rate limited" not in str(e):
            print(f"yfinance error for {symbol}: {e}")
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
    Returns detailed breakdown with components for each pillar.

    Returns:
        {
            "F": score,
            "M": score,
            "O": score,
            "S": score,
            "A": score,
            "breakdown": {
                "fundamental": {"score": x, "weight": y, "contribution": z, "components": {...}},
                "momentum": {...},
                ...
            }
        }
    """
    # Get raw data
    market_cap = market_data.get("market_cap", 0) if market_data else 0
    volume_24h = market_data.get("volume_24h", 0) if market_data else 0
    circ_supply = market_data.get("circulating_supply", 0) if market_data else 0
    total_supply = market_data.get("total_supply", 0) if market_data else 0
    change_30d = market_data.get("change_30d", 0) or 0
    change_24h = market_data.get("change_24h", 0) or 0
    ath_distance = abs(market_data.get("ath_change_percentage", 0)) if market_data else 50
    price = market_data.get("price", 0) if market_data else 0

    # === Fundamental Score (F) ===
    # Components: market_cap tier, circulating_supply ratio
    f_components = {
        "market_cap_tier": ">$10B" if market_cap > 10e9 else ">$1B" if market_cap > 1e9 else ">$100M" if market_cap > 100e6 else ">$10M" if market_cap > 10e6 else "<$10M",
        "market_cap_usd": market_cap,
        "circulating_supply_ratio": round(circ_supply / total_supply, 3) if total_supply > 0 and circ_supply > 0 else 0,
    }

    f_score = 50  # base
    if market_cap > 10e9:
        f_score += 30
        f_components["market_cap_tier_score"] = 30
    elif market_cap > 1e9:
        f_score += 25
        f_components["market_cap_tier_score"] = 25
    elif market_cap > 100e6:
        f_score += 20
        f_components["market_cap_tier_score"] = 20
    elif market_cap > 10e6:
        f_score += 15
        f_components["market_cap_tier_score"] = 15
    elif market_cap > 0:
        f_score += 10
        f_components["market_cap_tier_score"] = 10
    else:
        f_components["market_cap_tier_score"] = 0

    if total_supply > 0 and circ_supply > 0:
        ratio = circ_supply / total_supply
        if ratio >= 0.7:
            f_score += 15
            f_components["supply_ratio_score"] = 15
        elif ratio >= 0.5:
            f_score += 10
            f_components["supply_ratio_score"] = 10
        elif ratio >= 0.3:
            f_score += 5
            f_components["supply_ratio_score"] = 5
        else:
            f_components["supply_ratio_score"] = 0
    else:
        f_components["supply_ratio_score"] = 0

    f_score = min(100, f_score)

    # === Momentum Score (M) ===
    # Components: volume_24h, vol_mcap_ratio, tvl (for DeFi/L2)
    m_components = {
        "volume_24h": volume_24h,
        "volume_mcap_ratio": round(volume_24h / market_cap, 4) if market_cap > 0 else 0,
        "tvl_usd": tvl if asset_class in ["DeFi", "L2"] else None,
    }

    m_score = 30  # base
    if volume_24h > 1e9:
        m_score += 35
        m_components["volume_score"] = 35
    elif volume_24h > 100e6:
        m_score += 30
        m_components["volume_score"] = 30
    elif volume_24h > 10e6:
        m_score += 20
        m_components["volume_score"] = 20
    elif volume_24h > 1e6:
        m_score += 15
        m_components["volume_score"] = 15
    elif volume_24h > 0:
        m_score += 10
        m_components["volume_score"] = 10
    else:
        m_components["volume_score"] = 0

    # Volume/MCap ratio
    if market_cap > 0:
        vol_ratio = volume_24h / market_cap
        if vol_ratio > 0.3:
            m_score += 20
            m_components["liquidity_score"] = 20
        elif vol_ratio > 0.1:
            m_score += 15
            m_components["liquidity_score"] = 15
        elif vol_ratio > 0.05:
            m_score += 10
            m_components["liquidity_score"] = 10
        else:
            m_components["liquidity_score"] = 0

    # TVL bonus for DeFi/L2
    if asset_class in ["DeFi", "L2"] and tvl > 0:
        if tvl > 1e9:
            m_score += 15
            m_components["tvl_score"] = 15
        elif tvl > 100e6:
            m_score += 10
            m_components["tvl_score"] = 10
        elif tvl > 10e6:
            m_score += 5
            m_components["tvl_score"] = 5
        else:
            m_components["tvl_score"] = 0

    m_score = min(100, m_score)

    # === On-Chain Health / Risk-Adjusted Score (O) ===
    # Components: tvl (DeFi), ath_distance, supply health
    o_components = {
        "tvl_usd": tvl,
        "ath_distance_pct": ath_distance,
        "supply_circulating_ratio": round(circ_supply / total_supply, 3) if total_supply > 0 else 0,
    }

    o_score = 40  # base

    if asset_class == "DeFi":
        if tvl > 1e9:
            o_score += 35
            o_components["tvl_score"] = 35
        elif tvl > 100e6:
            o_score += 25
            o_components["tvl_score"] = 25
        elif tvl > 10e6:
            o_score += 15
            o_components["tvl_score"] = 15
        elif tvl > 1e6:
            o_score += 10
            o_components["tvl_score"] = 10
        else:
            o_components["tvl_score"] = 0
    else:
        # Use ATH distance as maturity proxy
        if ath_distance < 20:
            o_score += 30
            o_components["maturity_score"] = 30
        elif ath_distance < 50:
            o_score += 20
            o_components["maturity_score"] = 20
        elif ath_distance < 70:
            o_score += 10
            o_components["maturity_score"] = 10
        else:
            o_components["maturity_score"] = 0

    # Supply health
    if total_supply > 0 and circ_supply > 0:
        ratio = circ_supply / total_supply
        if ratio > 0.5:
            o_score += 15
            o_components["supply_health_score"] = 15
        else:
            o_components["supply_health_score"] = 0
    else:
        o_components["supply_health_score"] = 0

    o_score = min(100, o_score)

    # === Sentiment Score (S) ===
    # Components: fear_greed_index, price momentum (30d)
    s_components = {
        "fear_greed_value": fng.get("value") if fng else None,
        "fear_greed_classification": fng.get("value_classification") if fng else None,
        "return_30d": round(change_30d / 100, 4),
        "return_24h": round(change_24h / 100, 4),
    }

    s_score = 50  # base

    if fng:
        fng_value = int(fng.get("value", 50))
        if fng_value > 75:
            s_score = 85
            s_components["fng_score"] = 35
        elif fng_value > 65:
            s_score = 75
            s_components["fng_score"] = 25
        elif fng_value > 55:
            s_score = 60
            s_components["fng_score"] = 10
        elif fng_value > 35:
            s_score = 45
            s_components["fng_score"] = -5
        else:
            s_score = 30
            s_components["fng_score"] = -20

    # 30d momentum
    if change_30d > 50:
        s_score = min(100, s_score + 15)
        s_components["momentum_score"] = 15
    elif change_30d > 20:
        s_score = min(100, s_score + 10)
        s_components["momentum_score"] = 10
    elif change_30d < -30:
        s_score = max(0, s_score - 15)
        s_components["momentum_score"] = -15
    elif change_30d < -15:
        s_score = max(0, s_score - 10)
        s_components["momentum_score"] = -10
    else:
        s_components["momentum_score"] = 0

    # === Alpha Independence Score (A) ===
    # Components: asset_class type, market_cap tier, ATH distance
    a_components = {
        "asset_class": asset_class,
        "market_cap_usd": market_cap,
        "ath_distance_pct": ath_distance,
    }

    a_score = 50  # base

    # Asset class independence bonus
    if asset_class in ["DeFi", "RWA", "L2"]:
        a_score += 20
        a_components["class_independence_score"] = 20
    elif asset_class == "L1":
        a_score += 15
        a_components["class_independence_score"] = 15
    else:
        a_components["class_independence_score"] = 0

    # Market cap tier (larger = less alpha)
    if market_cap > 10e9:
        a_score -= 10
        a_components["size_drag_score"] = -10
    elif market_cap > 1e9:
        a_score -= 5
        a_components["size_drag_score"] = -5
    else:
        a_components["size_drag_score"] = 0

    # Price independence (distance from ATH)
    if 30 < ath_distance < 70:
        a_score += 15
        a_components["price_independence_score"] = 15
    elif ath_distance < 10:
        a_score -= 10
        a_components["price_independence_score"] = -10
    else:
        a_components["price_independence_score"] = 0

    a_score = max(0, min(100, a_score))

    # Build breakdown with scores
    breakdown = {
        "fundamental": {
            "score": round(f_score, 1),
            "components": f_components,
        },
        "momentum": {
            "score": round(m_score, 1),
            "components": m_components,
        },
        "risk_adjusted": {
            "score": round(o_score, 1),
            "components": o_components,
        },
        "sensitivity": {
            "score": round(s_score, 1),
            "components": s_components,
        },
        "alpha": {
            "score": round(a_score, 1),
            "components": a_components,
        },
    }

    return {
        "F": round(f_score, 1),
        "M": round(m_score, 1),
        "O": round(o_score, 1),
        "S": round(s_score, 1),
        "A": round(a_score, 1),
        "breakdown": breakdown,
    }

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


def calculate_total_score(pillars: Dict[str, float], asset_class: str) -> Dict[str, Any]:
    """Calculate weighted total CIS score with detailed breakdown."""

    # Default weights
    weights = {
        "Crypto": {"F": 0.25, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.15},
        "L1": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "L2": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "DeFi": {"F": 0.25, "M": 0.25, "O": 0.25, "S": 0.15, "A": 0.10},
        "RWA": {"F": 0.35, "M": 0.20, "O": 0.20, "S": 0.15, "A": 0.10},
        "Infrastructure": {"F": 0.30, "M": 0.20, "O": 0.25, "S": 0.10, "A": 0.15},
        "NFT": {"F": 0.15, "M": 0.25, "O": 0.15, "S": 0.30, "A": 0.15},
        "US Equity": {"F": 0.30, "M": 0.25, "O": 0.10, "S": 0.20, "A": 0.15},
        "US Bond": {"F": 0.30, "M": 0.20, "O": 0.10, "S": 0.20, "A": 0.20},
        "Commodity": {"F": 0.25, "M": 0.25, "O": 0.10, "S": 0.20, "A": 0.20},
    }

    w = weights.get(asset_class, weights["Crypto"])

    # Calculate contributions
    contributions = {
        "fundamental": {
            "score": pillars["F"],
            "weight": w["F"],
            "contribution": round(w["F"] * pillars["F"], 2),
        },
        "momentum": {
            "score": pillars["M"],
            "weight": w["M"],
            "contribution": round(w["M"] * pillars["M"], 2),
        },
        "risk_adjusted": {
            "score": pillars["O"],
            "weight": w["O"],
            "contribution": round(w["O"] * pillars["O"], 2),
        },
        "sensitivity": {
            "score": pillars["S"],
            "weight": w["S"],
            "contribution": round(w["S"] * pillars["S"], 2),
        },
        "alpha": {
            "score": pillars["A"],
            "weight": w["A"],
            "contribution": round(w["A"] * pillars["A"], 2),
        },
    }

    total = (
        w["F"] * pillars["F"] +
        w["M"] * pillars["M"] +
        w["O"] * pillars["O"] +
        w["S"] * pillars["S"] +
        w["A"] * pillars["A"]
    )

    return {
        "total_score": round(total, 1),
        "weights": w,
        "contributions": contributions,
    }


def get_grade(score: float) -> str:
    """Get letter grade from score (absolute thresholds)."""
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


def apply_forced_distribution(universe: list) -> list:
    """
    Apply forced distribution to CIS scores.
    This ensures differentiation regardless of score concentration.
    Distribution:
    - A+: Top 10% (top 2 assets for 17 assets)
    - A: 10-25%
    - B+: 25-50%
    - B: 50-75%
    - C+: 75-90%
    - C/D/F: Bottom 10%
    """
    if not universe:
        return universe

    n = len(universe)
    # Sort by score descending
    sorted_universe = sorted(universe, key=lambda x: x.get("cis_score", 0), reverse=True)

    for i, asset in enumerate(sorted_universe):
        # Calculate percentile rank (0-100, higher is better)
        percentile = ((n - i) / n) * 100

        # Assign grade based on forced distribution
        if percentile >= 90:
            grade = "A+"
        elif percentile >= 75:
            grade = "A"
        elif percentile >= 50:
            grade = "B+"
        elif percentile >= 25:
            grade = "B"
        elif percentile >= 10:
            grade = "C+"
        else:
            grade = "C"

        # Update the asset with forced grade
        asset["grade"] = grade
        asset["percentile_rank"] = round(percentile, 1)

        # Update signal based on new grade
        if grade in ["A+", "A"]:
            asset["signal"] = "STRONG OVERWEIGHT"
        elif grade in ["B+", "B"]:
            asset["signal"] = "OVERWEIGHT"
        elif grade == "C+":
            asset["signal"] = "NEUTRAL"
        else:
            asset["signal"] = "UNDERWEIGHT"

    return sorted_universe


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

    Data sources:
    - Crypto: CoinGecko API
    - US Equities/Bonds/Commodities: yfinance
    """
    # Fetch all data concurrently
    cg_markets, llama_tvl, fng = await asyncio.gather(
        fetch_cg_markets(),
        fetch_defillama_tvl(),
        fetch_fear_greed()
    )

    # Fetch yfinance data for US assets
    yf_data = {}
    for symbol, config in {**US_EQUITIES, **BONDS, **COMMODITIES}.items():
        data = get_yfinance_data(config["yfinance"])
        if data:
            yf_data[symbol] = data

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
        asset_class = config["class"]

        # Get market data based on asset type
        if asset_class in ["US Equity", "US Bond", "Commodity"]:
            # Use yfinance data
            market_data = yf_data.get(asset_id, {})
            tvl = 0  # No TVL for traditional assets
        else:
            # Use CoinGecko data
            cg_id = config.get("coingecko", "")
            market_data = cg_markets.get(cg_id, {})
            tvl = llama_tvl.get(asset_id, 0)

        # Skip if no market data
        if not market_data:
            continue

        # Calculate pillar scores with breakdown
        pillars_result = calculate_cis_score(market_data, tvl, fng, asset_class)
        pillars = {k: v for k, v in pillars_result.items() if k != "breakdown"}
        breakdown = pillars_result.get("breakdown", {})

        # Calculate total with weights
        total_result = calculate_total_score(pillars, asset_class)
        total_score = total_result["total_score"]
        weights = total_result["weights"]
        contributions = total_result["contributions"]

        grade = get_grade(total_score)
        signal = get_signal(total_score, grade)

        # 30d price change
        change_30d = market_data.get("change_30d", 0) or 0
        change_7d = market_data.get("change_7d", 0) or 0

        # Volatility (from 24h high/low)
        high_24h = market_data.get("high_24h", 0) or 0
        low_24h = market_data.get("low_24h", 0) or 0
        volatility_30d = 0
        if low_24h > 0 and high_24h > low_24h:
            volatility_30d = round((high_24h - low_24h) / low_24h * 100, 1)

        # Percentile (simplified - based on score)
        percentile = int(min(99, max(1, total_score)))

        # Merge contributions into breakdown
        for key in contributions:
            if key in breakdown:
                breakdown[key]["weight"] = contributions[key]["weight"]
                breakdown[key]["contribution"] = contributions[key]["contribution"]

        # Data completeness (confidence) - check what data sources we have
        data_completeness = {
            "price": bool(market_data.get("price", 0)),
            "volume": bool(market_data.get("volume_24h", 0)),
            "market_cap": bool(market_data.get("market_cap", 0)),
            "tvl": bool(tvl and tvl > 0),
            "sentiment": bool(fng and fng.get("value")),
            "circulating_supply": bool(market_data.get("circulating_supply", 0)),
        }
        # Confidence score: 0-1 based on data completeness
        confidence = round(sum(data_completeness.values()) / len(data_completeness), 2)

        # Get CIS score change from history
        score_change_7d = 0
        score_change_30d = 0
        try:
            from .history_db import get_score_change
            sc_30d = get_score_change(asset_id, days=30)
            if sc_30d:
                score_change_30d = round(sc_30d.get("change", 0), 1)
            sc_7d = get_score_change(asset_id, days=7)
            if sc_7d:
                score_change_7d = round(sc_7d.get("change", 0), 1)
        except Exception:
            pass

        # Max drawdown estimation (simplified from ath_distance)
        ath_distance = abs(market_data.get("ath_change_percentage", 0) or 0)
        max_drawdown_90d = min(ath_distance, 90)  # Cap at 90%

        universe.append({
            "symbol": asset_id,
            "name": config["name"],
            "asset_class": asset_class,
            "cis_score": total_score,
            "grade": grade,
            "signal": signal,
            "confidence": confidence,
            "f": pillars["F"],
            "m": pillars["M"],
            "r": pillars["O"],
            "s": pillars["S"],
            "a": pillars["A"],
            "breakdown": breakdown,
            "weights": weights,
            "change_7d": round(change_7d, 1),
            "change_30d": round(change_30d, 1),
            "score_change_7d": score_change_7d,
            "score_change_30d": score_change_30d,
            "volatility_30d": volatility_30d,
            "max_drawdown_90d": round(max_drawdown_90d, 1),
            "percentile": percentile,
            "data_completeness": data_completeness,
            "market_cap": market_data.get("market_cap", 0),
            "volume_24h": market_data.get("volume_24h", 0),
            "tvl": tvl,
        })

    # Sort by CIS score
    universe.sort(key=lambda x: x["cis_score"], reverse=True)

    # Apply forced distribution for better differentiation
    universe = apply_forced_distribution(universe)

    # Get macro data
    macro = {
        "regime": regime,
        "fed_funds": 5.25,  # Would need real Fed data
        "treasury_10y": 4.25,  # Would need real Treasury data
        "vix": 18.0,  # Would need real VIX
        "dxy": 104.0,  # Would need real DXY
        "cpi_yoy": 3.2,  # Would need real CPI
    }

    # Save to history database
    try:
        from .history_db import save_cis_snapshot
        save_cis_snapshot(universe, macro)
    except Exception as e:
        print(f"Failed to save CIS history: {e}")

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
