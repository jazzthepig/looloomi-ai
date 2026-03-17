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
    # Top by market cap
    "BTC": {"coingecko": "bitcoin", "name": "Bitcoin", "class": "Crypto"},
    "ETH": {"coingecko": "ethereum", "name": "Ethereum", "class": "Crypto"},
    "BNB": {"coingecko": "binancecoin", "name": "BNB", "class": "L1"},
    "XRP": {"coingecko": "ripple", "name": "XRP", "class": "L1"},
    "SOL": {"coingecko": "solana", "name": "Solana", "class": "L1"},
    "ADA": {"coingecko": "cardano", "name": "Cardano", "class": "L1"},
    "DOGE": {"coingecko": "dogecoin", "name": "Dogecoin", "class": "L1"},
    # L1/L2
    "AVAX": {"coingecko": "avalanche-2", "name": "Avalanche", "class": "L1"},
    "DOT": {"coingecko": "polkadot", "name": "Polkadot", "class": "L1"},
    "POL": {"coingecko": "polygon-ecosystem-token", "name": "Polygon (POL)", "class": "L2"},
    "ARB": {"coingecko": "arbitrum", "name": "Arbitrum", "class": "L2"},
    "OP": {"coingecko": "optimism", "name": "Optimism", "class": "L2"},
    "MANTLE": {"coingecko": "mantle", "name": "Mantle", "class": "L2"},
    "TON": {"coingecko": "the-open-network", "name": "Toncoin", "class": "L1"},
    "INJ": {"coingecko": "injective-protocol", "name": "Injective", "class": "Infrastructure"},
    # DeFi
    "UNI": {"coingecko": "uniswap", "name": "Uniswap", "class": "DeFi"},
    "AAVE": {"coingecko": "aave", "name": "Aave", "class": "DeFi"},
    "MKR": {"coingecko": "maker", "name": "Maker", "class": "DeFi"},
    "SNX": {"coingecko": "havven", "name": "Synthetix", "class": "DeFi"},
    "CRV": {"coingecko": "curve-dao-token", "name": "Curve", "class": "DeFi"},
    "LDO": {"coingecko": "lido-dao", "name": "Lido DAO", "class": "DeFi"},
    "COMP": {"coingecko": "compound-governance-token", "name": "Compound", "class": "DeFi"},
    "SUSHI": {"coingecko": "sushi", "name": "SushiSwap", "class": "DeFi"},
    # Infrastructure
    "LINK": {"coingecko": "chainlink", "name": "Chainlink", "class": "Infrastructure"},
    "STX": {"coingecko": "stacks", "name": "Stacks", "class": "Infrastructure"},
    "RUNE": {"coingecko": "thorchain", "name": "THORChain", "class": "Infrastructure"},
    # RWA / Memes / High volume
    "ONDO": {"coingecko": "ondo-finance", "name": "Ondo Finance", "class": "RWA"},
    "PEPE": {"coingecko": "pepe", "name": "Pepe", "class": "Memecoin"},
    "WIF": {"coingecko": "wif", "name": "WIF", "class": "Memecoin"},
    "BONK": {"coingecko": "bonk", "name": "Bonk", "class": "Memecoin"},
    "SUI": {"coingecko": "sui", "name": "Sui", "class": "L1"},
    "APT": {"coingecko": "aptos", "name": "Aptos", "class": "L1"},
    "NEAR": {"coingecko": "near", "name": "NEAR Protocol", "class": "L1"},
    "FIL": {"coingecko": "filecoin", "name": "Filecoin", "class": "Infrastructure"},
    "ATOM": {"coingecko": "cosmos", "name": "Cosmos", "class": "L1"},
    "LTC": {"coingecko": "litecoin", "name": "Litecoin", "class": "Crypto"},
    "BCH": {"coingecko": "bitcoin-cash", "name": "Bitcoin Cash", "class": "Crypto"},
    "SEI": {"coingecko": "sei", "name": "Sei", "class": "L1"},
    "TIA": {"coingecko": "celestia", "name": "Celestia", "class": "Infrastructure"},
    "SAND": {"coingecko": "the-sandbox", "name": "The Sandbox", "class": "Gaming"},
    "MANA": {"coingecko": "decentraland", "name": "Decentraland", "class": "Gaming"},
    "AXS": {"coingecko": "axie-infinity", "name": "Axie Infinity", "class": "Gaming"},
    "FTM": {"coingecko": "fantom", "name": "Fantom", "class": "L1"},
    "ALGO": {"coingecko": "algorand", "name": "Algorand", "class": "L1"},
    "VET": {"coingecko": "vechain", "name": "VeChain", "class": "Infrastructure"},
    "HBAR": {"coingecko": "hedera-hashgraph", "name": "Hedera", "class": "L1"},
    "ICP": {"coingecko": "internet-computer", "name": "Internet Computer", "class": "Infrastructure"},
    "NEON": {"coingecko": "neon-evm", "name": "Neon EVM", "class": "L2"},
    "IO": {"coingecko": "io-net", "name": "io.net", "class": "Infrastructure"},
    "POLYX": {"coingecko": "polymesh", "name": "Polymesh", "class": "RWA"},
    # Hot tokens
    "HYPER": {"coingecko": "hyperliquid", "name": "Hyperliquid", "class": "L1"},
    "VIRTUAL": {"coingecko": "virtual-protocol", "name": "Virtuals Protocol", "class": "AI"},
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

# GitHub repo paths for developer-activity tracking (Phase 2B)
# Format: asset_id -> "owner/repo"
# Covers top 25 assets with active public repos; others get None (no dev signal)
GITHUB_REPOS: Dict[str, str] = {
    "BTC":     "bitcoin/bitcoin",
    "ETH":     "ethereum/go-ethereum",
    "SOL":     "solana-labs/solana",
    "ADA":     "IntersectMBO/cardano-node",
    "AVAX":    "ava-labs/avalanchego",
    "DOT":     "paritytech/polkadot",
    "ARB":     "OffchainLabs/nitro",
    "OP":      "ethereum-optimism/optimism",
    "NEAR":    "near/nearcore",
    "ATOM":    "cosmos/cosmos-sdk",
    "FIL":     "filecoin-project/lotus",
    "ALGO":    "algorand/go-algorand",
    "ICP":     "dfinity/ic",
    "STX":     "stacks-network/stacks-core",
    "INJ":     "InjectiveLabs/injective-core",
    "TIA":     "celestiaorg/celestia-node",
    "SEI":     "sei-protocol/sei-chain",
    "APT":     "aptos-labs/aptos-core",
    "SUI":     "MystenLabs/sui",
    "LINK":    "smartcontractkit/chainlink",
    "AAVE":    "aave/aave-v3-core",
    "UNI":     "Uniswap/v4-core",
    "RUNE":    "thorchain/thornode",
    "LDO":     "lidofinance/lido-dao",
    "COMP":    "compound-finance/compound-protocol",
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


# Symbol mapping: CIS symbol -> Binance symbol
# Priority: High liquidity pairs for reliable data
BINANCE_SYMBOLS = {
    # Top by market cap
    "BTC": "btcusdt",
    "ETH": "ethusdt",
    "BNB": "bnbusdt",
    "XRP": "xrpusdt",
    "SOL": "solusdt",
    "ADA": "adausdt",
    "DOGE": "dogeusdt",
    # L1/L2
    "AVAX": "avaxusdt",
    "DOT": "dotusdt",
    "POL": "polusdt",
    "ARB": "arbusdt",
    "OP": "opusdt",
    "MANTLE": "mntusdt",
    "TON": "tonusdt",
    "INJ": "injusdt",
    # DeFi
    "UNI": "uniusdt",
    "AAVE": "aaveusdt",
    "MKR": "mkrusdt",
    "SNX": "snxusdt",
    "CRV": "crvusdt",
    "LDO": "ldousdt",
    "COMP": "compusdt",
    "SUSHI": "sushiusdt",
    # Infrastructure
    "LINK": "linkusdt",
    "STX": "stxusdt",
    "RUNE": "runeusdt",
    # RWA / Memes
    "ONDO": "ondousdt",
    "PEPE": "pepeusdt",
    "WIF": "wifusdt",
    "BONK": "bonkusdt",
    "SUI": "suiusdt",
    "APT": "aptusdt",
    "NEAR": "nearusdt",
    "FIL": "filusdt",
    "ATOM": "atomusdt",
    "LTC": "ltcusdt",
    "BCH": "bchusdt",
    "NEON": "neonusdt",
    "SEI": "seiusdt",
    "TIA": "tiausdt",
    "SAND": "sandusdt",
    "MANA": "manausdt",
    "AXS": "axsusdt",
    "FTM": "ftmusdt",
    "ALGO": "algousdt",
    "VET": "vetusdt",
    "HBAR": "hbarusdt",
    "ICP": "icusdt",
    "FTND": "ftndusdt",
    "IO": "iousdt",
    # Hot tokens
    "HYPER": "hyperusdt",
    "VIRTUAL": "virtualusdt",
}

# Reverse mapping
BINANCE_TO_CIS = {v: k for k, v in BINANCE_SYMBOLS.items()}


async def fetch_binance_prices() -> Dict[str, dict]:
    """Fetch crypto prices from Binance API - fast, no rate limit."""
    cache_key = "binance_prices"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    result = {}
    binsym = list(BINANCE_SYMBOLS.values())

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Fetch all tickers in one call
            url = "https://api.binance.com/api/v3/ticker/24hr"

            # Get all 24hr tickers
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

            # Filter for our symbols
            for ticker in data:
                sym = ticker.get("symbol", "").lower()
                if sym in binsym:
                    cis_sym = BINANCE_TO_CIS.get(sym, sym.upper().replace("USDT", ""))

                    # Get 7d history for 7d change (approximate from 24hr)
                    # Binance doesn't have 7d, so we'll estimate from current data
                    price = float(ticker.get("lastPrice", 0))
                    change_24h = float(ticker.get("priceChangePercent", 0))
                    high_24h = float(ticker.get("highPrice", 0))
                    low_24h = float(ticker.get("lowPrice", 0))
                    volume = float(ticker.get("quoteVolume", 0))

                    result[cis_sym] = {
                        "symbol": cis_sym,
                        "name": cis_sym,
                        "price": price,
                        "change_24h": change_24h,
                        "change_7d": None,   # Will be filled from CoinGecko merge
                        "change_30d": None,  # Will be filled from CoinGecko merge
                        "volume_24h": volume,
                        "high_24h": high_24h,
                        "low_24h": low_24h,
                        "market_cap": 0,  # Will be filled from CoinGecko merge
                        "circulating_supply": 0,
                        "total_supply": 0,
                        "ath_change_percentage": 0,
                        "source": "binance",
                    }

            print(f"Binance: fetched {len(result)} assets")
            return _cache_set(cache_key, result)

    except Exception as e:
        print(f"Binance API error: {e}")
        return result


async def fetch_cg_markets() -> Dict[str, dict]:
    """Fallback: Fetch market data from CoinGecko if Binance fails."""
    cache_key = "cg_markets"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    result = {}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Fetch first page only as fallback
            url = f"{CG_BASE}/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": 1,
                "sparkline": False,
                "price_change_percentage": "30d,7d"
            }
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()

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
                    "source": "coingecko",
                }

            return _cache_set(cache_key, result)

    except Exception as e:
        print(f"CoinGecko fallback error: {e}")
        return result


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


async def fetch_cg_global() -> Optional[dict]:
    """Fetch CoinGecko global data (includes BTC dominance)."""
    cache_key = "cg_global"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{CG_BASE}/global")
            r.raise_for_status()
            data = r.json()
            return _cache_set(cache_key, data.get("data", {}))
    except Exception as e:
        print(f"CoinGecko global API error: {e}")
        return None


async def fetch_github_activity() -> Dict[str, int]:
    """
    Fetch commit counts for the last 4 weeks from GitHub public API.
    Uses /repos/{owner}/{repo}/stats/participation (no auth, 60 req/hr).
    Returns {asset_id: commits_last_4w} — best effort, empty on failure.
    Cached for 2 hours to stay within the 60 req/hr rate limit.
    """
    cache_key = "github_activity"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    results: Dict[str, int] = {}

    async def _fetch_one(asset_id: str, repo: str):
        try:
            url = f"https://api.github.com/repos/{repo}/stats/participation"
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    # 'all' = array of 52 weekly totals (owner + contributors)
                    all_weeks = data.get("all", [])
                    if all_weeks and len(all_weeks) >= 4:
                        return asset_id, sum(all_weeks[-4:])
                # 202 = GitHub still computing; 404/403 = unavailable — skip silently
        except Exception:
            pass
        return asset_id, None

    tasks = [_fetch_one(aid, repo) for aid, repo in GITHUB_REPOS.items()]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    for item in raw:
        if isinstance(item, tuple) and item[1] is not None:
            results[item[0]] = int(item[1])

    # Use a 2-hour TTL via a manual timestamp check on next hit
    # (simple _cache_set uses global _cache_ttl=300; we override by storing a wrapper)
    _cache[cache_key] = (results, datetime.now().timestamp() + 7200 - _cache_ttl)
    return results


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


# Macro data cache path on external drive
MACRO_CACHE_PATH = "/Volumes/CometCloudAI/data/macro_cache.json"
MACRO_CACHE_TTL = 3600  # 1 hour


def _load_macro_cache() -> Optional[dict]:
    """Load macro data from external drive cache."""
    try:
        if os.path.exists(MACRO_CACHE_PATH):
            import json
            with open(MACRO_CACHE_PATH, 'r') as f:
                data = json.load(f)
            # Check if cache is still valid
            ts = data.get("timestamp", 0)
            if datetime.now().timestamp() - ts < MACRO_CACHE_TTL:
                return data
    except Exception:
        pass
    return None


def _save_macro_cache(data: dict):
    """Save macro data to external drive cache."""
    try:
        os.makedirs(os.path.dirname(MACRO_CACHE_PATH), exist_ok=True)
        import json
        with open(MACRO_CACHE_PATH, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Failed to save macro cache: {e}")


async def fetch_macro_data() -> dict:
    """
    Fetch macro indicators via FRED API and Yahoo Finance.
    Falls back to hardcoded values if API fails.

    Cached to external drive for 1 hour.
    """
    FRED_API_KEY = "5afc269032ce06a65c7eba5ec1bb49ad"

    # Try memory cache first
    cache_key = "macro_data"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # Try external drive cache
    disk_cache = _load_macro_cache()
    if disk_cache:
        _cache_set(cache_key, disk_cache)
        return disk_cache

    # Default fallback values (2025-03 realistic values)
    fallback = {
        "fed_funds": 4.25,      # ~4.25% as of March 2025
        "treasury_10y": 4.15,   # ~4.15% 10Y yield
        "vix": 19.5,            # ~19.5 VIX (normal market)
        "dxy": 104.2,           # ~104 DXY
        "cpi_yoy": 2.8,         # ~2.8% CPI YoY
        "btc_dominance": 52.0,  # BTC dominance %
    }

    # Fetch fresh data
    result = {
        "timestamp": datetime.now().timestamp(),
        "regime": "unknown",
        "fed_funds": fallback["fed_funds"],
        "treasury_10y": fallback["treasury_10y"],
        "vix": fallback["vix"],
        "dxy": fallback["dxy"],
        "cpi_yoy": fallback["cpi_yoy"],
        "btc_dominance": fallback["btc_dominance"],
        "_source": "fallback",
    }

    fetched_any = False

    # Fetch from FRED API
    try:
        fred_series = {
            "fed_funds": "FEDFUNDS",      # Effective Federal Funds Rate
            "treasury_10y": "GS10",       # 10-Year Treasury Constant Maturity Rate
            "cpi_yoy": "CPIAUCSL",        # CPI for All Urban Consumers
        }

        async with httpx.AsyncClient(timeout=15) as client:
            for key, series_id in fred_series.items():
                try:
                    url = f"https://api.stlouisfed.org/fred/series/observations"
                    params = {
                        "series_id": series_id,
                        "api_key": FRED_API_KEY,
                        "observation_limit": 12,  # Need 12 for YoY CPI
                        "sort_order": "desc",
                        "file_type": "json",
                    }
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        observations = data.get("observations", [])
                        if observations and observations[0].get("value") != ".":
                            value = float(observations[0].get("value", 0))
                            if key == "cpi_yoy":
                                # CPI is monthly, calculate YoY change
                                if len(observations) >= 12 and observations[11].get("value") != ".":
                                    prev_value = float(observations[11].get("value", 0))
                                    if prev_value > 0:
                                        result[key] = round(((value - prev_value) / prev_value) * 100, 1)
                                        fetched_any = True
                            else:
                                result[key] = round(value, 2)
                                fetched_any = True
                except Exception as e:
                    print(f"FRED error for {key}: {e}")
    except Exception as e:
        print(f"FRED API error: {e}")

    # Yahoo Finance v8 quote endpoints
    ticker_map = {
        "vix": "^VIX",
        "dxy": "DX-Y.NYB",
        "treasury_10y": "^TNX",
        "fed_funds": "^IRX",  # 13-week T-Bill as Fed proxy
    }

    async def fetch_yf_async(symbol: str) -> Optional[float]:
        """Fetch using Yahoo Finance v8 quote API via httpx."""
        import time

        for attempt in range(2):
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                async with httpx.AsyncClient(timeout=8) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        result_data = data.get("chart", {}).get("result")
                        if result_data and len(result_data) > 0:
                            meta = result_data[0].get("meta", {})
                            price = (
                                meta.get("regularMarketPrice") or
                                meta.get("previousClose")
                            )
                            if price:
                                return float(price)
            except Exception:
                pass
            if attempt < 1:
                time.sleep(0.5)
        return None

    try:
        # Fetch VIX/DXY from Yahoo Finance
        for key, symbol in ticker_map.items():
            value = await fetch_yf_async(symbol)
            if value is not None:
                fetched_any = True
                if key == "fed_funds":
                    result[key] = round(value / 100, 4)  # Convert % to decimal
                else:
                    result[key] = round(value, 2)

        # Fetch BTC dominance from CoinGecko global
        cg_global = await fetch_cg_global()
        if cg_global:
            btc_dom = cg_global.get("market_cap_percentage", {}).get("btc")
            if btc_dom is not None:
                result["btc_dominance"] = round(btc_dom, 1)
                fetched_any = True

        if fetched_any:
            result["_source"] = "api"

    except Exception as e:
        print(f"Error fetching macro data: {e}")

    # Determine regime based on VIX
    if result["vix"]:
        if result["vix"] < 15:
            result["regime"] = "low_volatility"
        elif result["vix"] < 25:
            result["regime"] = "normal"
        else:
            result["regime"] = "high_volatility"

    # Save to external drive cache
    _save_macro_cache(result)
    _cache_set(cache_key, result)

    return result


def get_asset_class(asset_id: str) -> str:
    """Get asset class from config."""
    if asset_id in ASSETS_CONFIG:
        return ASSETS_CONFIG[asset_id]["class"]
    return "Crypto"


def calculate_cis_score(
    market_data: dict,
    tvl: float,
    fng: Optional[dict],
    asset_class: str,
    btc_change_30d: Optional[float] = None,
    github_commits_4w: Optional[int] = None,
    vix: Optional[float] = None,           # For non-crypto S pillar
    spy_change_30d: Optional[float] = None, # For non-crypto A pillar
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

    f_score = 10  # base — low floor so bad assets can score < 30
    # 10-tier market cap scoring (wider spread)
    if market_cap > 500e9:        # >$500B (BTC-tier)
        f_score += 55; f_components["market_cap_tier_score"] = 55
    elif market_cap > 100e9:      # >$100B
        f_score += 48; f_components["market_cap_tier_score"] = 48
    elif market_cap > 50e9:       # >$50B
        f_score += 42; f_components["market_cap_tier_score"] = 42
    elif market_cap > 10e9:       # >$10B
        f_score += 35; f_components["market_cap_tier_score"] = 35
    elif market_cap > 5e9:        # >$5B
        f_score += 28; f_components["market_cap_tier_score"] = 28
    elif market_cap > 1e9:        # >$1B
        f_score += 22; f_components["market_cap_tier_score"] = 22
    elif market_cap > 500e6:      # >$500M
        f_score += 16; f_components["market_cap_tier_score"] = 16
    elif market_cap > 100e6:      # >$100M
        f_score += 11; f_components["market_cap_tier_score"] = 11
    elif market_cap > 10e6:       # >$10M
        f_score += 6;  f_components["market_cap_tier_score"] = 6
    elif market_cap > 0:          # any cap
        f_score += 2;  f_components["market_cap_tier_score"] = 2
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

    m_score = 10  # base — low floor
    # 10-tier volume scoring
    if volume_24h > 10e9:         # >$10B (BTC/ETH-tier)
        m_score += 55; m_components["volume_score"] = 55
    elif volume_24h > 5e9:        # >$5B
        m_score += 48; m_components["volume_score"] = 48
    elif volume_24h > 1e9:        # >$1B
        m_score += 40; m_components["volume_score"] = 40
    elif volume_24h > 500e6:      # >$500M
        m_score += 33; m_components["volume_score"] = 33
    elif volume_24h > 100e6:      # >$100M
        m_score += 26; m_components["volume_score"] = 26
    elif volume_24h > 50e6:       # >$50M
        m_score += 20; m_components["volume_score"] = 20
    elif volume_24h > 10e6:       # >$10M
        m_score += 14; m_components["volume_score"] = 14
    elif volume_24h > 1e6:        # >$1M
        m_score += 8;  m_components["volume_score"] = 8
    elif volume_24h > 0:
        m_score += 3;  m_components["volume_score"] = 3
    else:
        m_components["volume_score"] = 0

    # Volume/MCap ratio - Liquidity Profile (Phase 3)
    if market_cap > 0:
        vol_ratio = volume_24h / market_cap
        if vol_ratio > 0.15:          # >15% = very liquid
            m_score += 15
            m_components["liquidity_score"] = 15
        elif vol_ratio > 0.05:         # 5-15% = liquid
            m_score += 8
            m_components["liquidity_score"] = 8
        elif vol_ratio > 0.01:         # 1-5% = moderate
            m_score += 3
            m_components["liquidity_score"] = 3
        else:                          # <1% = illiquid
            m_score -= 10
            m_components["liquidity_score"] = -10

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

    m_score = max(0, min(100, m_score))

    # === On-Chain Health / Risk-Adjusted Score (O) ===
    # Components: tvl (DeFi), ath_distance, supply health
    o_components = {
        "tvl_usd": tvl,
        "ath_distance_pct": ath_distance,
        "supply_circulating_ratio": round(circ_supply / total_supply, 3) if total_supply > 0 else 0,
    }

    o_score = 10  # base — low floor

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
    # Crypto: FNG-based baseline + per-asset momentum
    # Non-crypto (equity/bond/commodity): VIX-based baseline + per-asset momentum
    _is_tradfi = asset_class in ["US Equity", "US Bond", "Commodity"]

    s_components = {
        "return_30d": round(change_30d / 100, 4),
        "return_24h": round(change_24h / 100, 4),
    }
    if _is_tradfi:
        s_components["vix"] = vix
    else:
        s_components["fear_greed_value"] = fng.get("value") if fng else None
        s_components["fear_greed_classification"] = fng.get("value_classification") if fng else None

    s_score = 10  # low floor

    if _is_tradfi:
        # VIX-based baseline: low VIX = calm market = positive sentiment
        # Maps VIX range to 0-40 points (same scale as FNG contribution)
        if vix is not None:
            if vix < 15:    vix_pts = 40   # Very calm, greed-like
            elif vix < 20:  vix_pts = 30   # Normal
            elif vix < 25:  vix_pts = 20   # Mild concern
            elif vix < 30:  vix_pts = 10   # Elevated fear
            else:           vix_pts = 0    # Crisis / extreme fear
            s_score += vix_pts
            s_components["vix_score"] = vix_pts
        else:
            s_components["vix_score"] = None
    else:
        # FNG market baseline: maps 0-100 FNG → 0-50 points
        if fng:
            fng_value = int(fng.get("value", 50))
            fng_contribution = round(fng_value * 0.5, 1)
            s_score += fng_contribution
            s_components["fng_score"] = fng_contribution
        else:
            s_components["fng_score"] = None

    # Per-asset 30d price momentum — differentiates assets within same market
    if change_30d > 100:
        s_score = min(100, s_score + 30); s_components["momentum_score"] = 30
    elif change_30d > 50:
        s_score = min(100, s_score + 20); s_components["momentum_score"] = 20
    elif change_30d > 20:
        s_score = min(100, s_score + 12); s_components["momentum_score"] = 12
    elif change_30d > 5:
        s_score = min(100, s_score + 5);  s_components["momentum_score"] = 5
    elif change_30d > -10:
        s_components["momentum_score"] = 0
    elif change_30d > -30:
        s_score = max(0, s_score - 10);   s_components["momentum_score"] = -10
    elif change_30d > -50:
        s_score = max(0, s_score - 20);   s_components["momentum_score"] = -20
    else:
        s_score = max(0, s_score - 30);   s_components["momentum_score"] = -30

    # 24h momentum: short-term signal boost/drag
    if change_24h > 10:
        s_score = min(100, s_score + 8);  s_components["short_momentum"] = 8
    elif change_24h > 5:
        s_score = min(100, s_score + 4);  s_components["short_momentum"] = 4
    elif change_24h < -10:
        s_score = max(0, s_score - 8);    s_components["short_momentum"] = -8
    elif change_24h < -5:
        s_score = max(0, s_score - 4);    s_components["short_momentum"] = -4
    else:
        s_components["short_momentum"] = 0

    # Developer activity (GitHub commits in last 4 weeks)
    # Active development = positive signal; near-zero = red flag
    if github_commits_4w is not None:
        s_components["github_commits_4w"] = github_commits_4w
        if github_commits_4w > 300:       # Very high activity (e.g. BTC, ETH)
            s_score = min(100, s_score + 10); s_components["dev_activity_score"] = 10
        elif github_commits_4w > 100:     # Healthy activity
            s_score = min(100, s_score + 6);  s_components["dev_activity_score"] = 6
        elif github_commits_4w > 30:      # Moderate activity
            s_score = min(100, s_score + 3);  s_components["dev_activity_score"] = 3
        elif github_commits_4w > 5:       # Low but alive
            s_components["dev_activity_score"] = 0
        else:                             # Near-zero: possible red flag
            s_score = max(0, s_score - 8);    s_components["dev_activity_score"] = -8
    else:
        s_components["github_commits_4w"] = None
        s_components["dev_activity_score"] = None

    # === Alpha Independence Score (A) ===
    # Crypto: divergence vs BTC
    # Non-crypto: divergence vs SPY (bonds inverted — rising when equities fall = alpha)
    a_components = {
        "asset_class": asset_class,
        "market_cap_usd": market_cap,
        "ath_distance_pct": ath_distance,
    }

    a_score = 10  # base — low floor

    # Asset class independence bonus (crypto only)
    if not _is_tradfi:
        if asset_class in ["DeFi", "RWA", "L2"]:
            a_score += 20
            a_components["class_independence_score"] = 20
        elif asset_class == "L1":
            a_score += 15
            a_components["class_independence_score"] = 15
        else:
            a_components["class_independence_score"] = 0

    # Market cap size drag — universal
    if market_cap > 100e9:    # Mega-cap (SPY, AAPL tier or BTC tier)
        a_score -= 5
        a_components["size_drag_score"] = -5
    elif market_cap > 10e9:
        a_score -= 3
        a_components["size_drag_score"] = -3
    else:
        a_components["size_drag_score"] = 0

    # Price recovery potential (ATH distance)
    if 30 < ath_distance < 70:
        a_score += 15
        a_components["price_independence_score"] = 15
    elif ath_distance < 10:
        a_score -= 5
        a_components["price_independence_score"] = -5
    else:
        a_components["price_independence_score"] = 0

    # Benchmark divergence — crypto uses BTC, non-crypto uses SPY
    if _is_tradfi:
        if spy_change_30d is not None and asset_class != "US Equity":  # Don't benchmark SPY vs itself
            # Bonds: inverse relationship is the alpha signal
            # Bond rising while equities falling = genuine alpha
            if asset_class == "US Bond":
                divergence = spy_change_30d - change_30d  # Inverted: bond alpha = equity decline
            else:
                divergence = change_30d - spy_change_30d  # Commodity: normal divergence
            a_components["spy_divergence_30d"] = round(divergence, 1)
            if divergence > 20:
                a_score = min(100, a_score + 20); a_components["alpha_score"] = 20
            elif divergence > 10:
                a_score = min(100, a_score + 12); a_components["alpha_score"] = 12
            elif divergence > 5:
                a_score = min(100, a_score + 6);  a_components["alpha_score"] = 6
            elif divergence > -5:
                a_components["alpha_score"] = 0
            elif divergence > -15:
                a_score = max(0, a_score - 8);    a_components["alpha_score"] = -8
            elif divergence > -30:
                a_score = max(0, a_score - 15);   a_components["alpha_score"] = -15
            else:
                a_score = max(0, a_score - 20);   a_components["alpha_score"] = -20
        else:
            a_components["spy_divergence_30d"] = None
            a_components["alpha_score"] = None
    else:
        # Crypto: BTC divergence
        # BTC itself has no BTC benchmark — falls back to SPY cross-asset alpha
        if btc_change_30d is not None:
            divergence = change_30d - btc_change_30d
            a_components["btc_divergence_30d"] = round(divergence, 1)
            if divergence > 50:
                a_score = min(100, a_score + 20); a_components["btc_alpha_score"] = 20
            elif divergence > 20:
                a_score = min(100, a_score + 12); a_components["btc_alpha_score"] = 12
            elif divergence > 10:
                a_score = min(100, a_score + 6);  a_components["btc_alpha_score"] = 6
            elif divergence > -10:
                a_components["btc_alpha_score"] = 0
            elif divergence > -20:
                a_score = max(0, a_score - 8);    a_components["btc_alpha_score"] = -8
            elif divergence > -50:
                a_score = max(0, a_score - 15);   a_components["btc_alpha_score"] = -15
            else:
                a_score = max(0, a_score - 20);   a_components["btc_alpha_score"] = -20
        elif spy_change_30d is not None:
            # BTC uses SPY as cross-asset alpha: BTC outperforming equities = genuine alpha
            divergence = change_30d - spy_change_30d
            a_components["spy_divergence_30d"] = round(divergence, 1)
            a_components["benchmark"] = "SPY (cross-asset)"
            if divergence > 30:
                a_score = min(100, a_score + 20); a_components["btc_alpha_score"] = 20
            elif divergence > 15:
                a_score = min(100, a_score + 12); a_components["btc_alpha_score"] = 12
            elif divergence > 5:
                a_score = min(100, a_score + 6);  a_components["btc_alpha_score"] = 6
            elif divergence > -5:
                a_components["btc_alpha_score"] = 0
            elif divergence > -15:
                a_score = max(0, a_score - 8);    a_components["btc_alpha_score"] = -8
            elif divergence > -30:
                a_score = max(0, a_score - 15);   a_components["btc_alpha_score"] = -15
            else:
                a_score = max(0, a_score - 20);   a_components["btc_alpha_score"] = -20
        else:
            a_components["btc_divergence_30d"] = None
            a_components["btc_alpha_score"] = None

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
        "Memecoin": {"F": 0.15, "M": 0.35, "O": 0.15, "S": 0.25, "A": 0.10},
        "Gaming": {"F": 0.20, "M": 0.30, "O": 0.15, "S": 0.25, "A": 0.10},
        "AI": {"F": 0.20, "M": 0.30, "O": 0.20, "S": 0.15, "A": 0.15},
        "US Equity": {"F": 0.30, "M": 0.25, "O": 0.10, "S": 0.20, "A": 0.15},
        "US Bond": {"F": 0.30, "M": 0.20, "O": 0.10, "S": 0.20, "A": 0.20},
        "Commodity": {"F": 0.25, "M": 0.25, "O": 0.10, "S": 0.20, "A": 0.20},
    }

    w = weights.get(asset_class, weights["Crypto"])

    # Handle None pillar values - replace with 0
    f_val = pillars.get("F") or 0
    m_val = pillars.get("M") or 0
    o_val = pillars.get("O") or 0
    s_val = pillars.get("S") or 0
    a_val = pillars.get("A") or 0

    # Calculate contributions
    contributions = {
        "fundamental": {
            "score": f_val,
            "weight": w["F"],
            "contribution": round(w["F"] * f_val, 2),
        },
        "momentum": {
            "score": m_val,
            "weight": w["M"],
            "contribution": round(w["M"] * m_val, 2),
        },
        "risk_adjusted": {
            "score": o_val,
            "weight": w["O"],
            "contribution": round(w["O"] * o_val, 2),
        },
        "sensitivity": {
            "score": s_val,
            "weight": w["S"],
            "contribution": round(w["S"] * s_val, 2),
        },
        "alpha": {
            "score": a_val,
            "weight": w["A"],
            "contribution": round(w["A"] * a_val, 2),
        },
    }

    total = (
        w["F"] * f_val +
        w["M"] * m_val +
        w["O"] * o_val +
        w["S"] * s_val +
        w["A"] * a_val
    )

    return {
        "total_score": round(total, 1),
        "weights": w,
        "contributions": contributions,
    }


def get_grade(score: float) -> str:
    """Get letter grade from score (absolute thresholds). Used internally."""
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


def get_grade_by_percentile(percentile_rank: float) -> str:
    """
    Option A: Grade based on relative rank within current universe.
    Top 5% = A+, next 10% = A, next 15% = B+, next 20% = B,
    next 20% = C+, next 15% = C, next 10% = D, bottom 5% = F.
    """
    if percentile_rank >= 95:  return "A+"
    if percentile_rank >= 85:  return "A"
    if percentile_rank >= 70:  return "B+"
    if percentile_rank >= 50:  return "B"
    if percentile_rank >= 30:  return "C+"
    if percentile_rank >= 15:  return "C"
    if percentile_rank >= 5:   return "D"
    return "F"


def compute_percentile_ranks(universe: list) -> list:
    """
    Compute percentile rank for each asset within the live universe.
    After this, grades are reassigned based on relative rank (Option A).
    """
    if not universe:
        return universe
    n = len(universe)
    sorted_u = sorted(universe, key=lambda x: x.get("cis_score", 0), reverse=True)
    for i, asset in enumerate(sorted_u):
        rank = round(((n - i) / n) * 100, 1)
        asset["percentile_rank"] = rank
        # Option A: override grade and signal with percentile-based values
        asset["grade"] = get_grade_by_percentile(rank)
        asset["signal"] = get_signal(asset["cis_score"], asset["grade"])
    return sorted_u


def get_signal(score: float, grade: str) -> str:
    """Get trading signal from grade."""
    if grade in ["A+", "A"]:
        return "STRONG BUY"
    elif grade in ["B+", "B"]:
        return "BUY"
    elif grade in ["C+", "C"]:
        return "HOLD"
    elif grade == "D":
        return "REDUCE"
    else:
        return "AVOID"


async def calculate_cis_universe() -> Dict[str, Any]:
    """
    Calculate CIS scores for all tracked assets.
    Returns the complete universe with scores.

    Data sources:
    - Crypto: CoinGecko API
    - US Equities/Bonds/Commodities: yfinance
    """
    # Fetch all data concurrently
    # Priority: Binance (fast, no rate limit) > CoinGecko (fallback)
    binance_prices, cg_markets, llama_tvl, fng, github_activity = await asyncio.gather(
        fetch_binance_prices(),
        fetch_cg_markets(),
        fetch_defillama_tvl(),
        fetch_fear_greed(),
        fetch_github_activity(),   # Phase 2B: dev activity (best-effort, 2h cache)
    )

    # Merge: Binance as primary (speed), CoinGecko enriches missing fields
    # Binance has: price, change_24h, volume, high/low
    # CoinGecko has: market_cap, change_7d, change_30d, circ_supply, ATH distance
    merged_markets = {}
    for asset_id in ASSETS_CONFIG.keys():
        cg_id = ASSETS_CONFIG[asset_id].get("coingecko", "")
        cg_data = cg_markets.get(cg_id, {})

        if asset_id in binance_prices:
            rec = dict(binance_prices[asset_id])  # copy
            # Enrich from CoinGecko for fields Binance doesn't provide
            if cg_data:
                # Handle None values properly
                cg_7d = cg_data.get("change_7d")
                cg_30d = cg_data.get("change_30d")
                rec["change_7d"] = cg_7d if cg_7d is not None else rec.get("change_7d")
                rec["change_30d"] = cg_30d if cg_30d is not None else rec.get("change_30d")
                rec["market_cap"] = cg_data.get("market_cap", 0) or 0
                rec["circulating_supply"] = cg_data.get("circulating_supply", 0) or 0
                rec["total_supply"] = cg_data.get("total_supply", 0) or 0
                rec["ath_change_percentage"] = cg_data.get("ath_change_percentage", 0) or 0
            else:
                # Fallback: estimate market_cap from volume when CoinGecko fails
                # Volume is typically 2-10% of market cap for liquid assets
                volume = rec.get("volume_24h", 0) or 0
                if volume > 0 and rec.get("market_cap", 0) == 0:
                    rec["market_cap"] = volume * 20  # Conservative estimate
            merged_markets[asset_id] = rec
        elif cg_data:
            merged_markets[asset_id] = cg_data

    # Fetch yfinance data for US assets
    yf_data = {}
    for symbol, config in {**US_EQUITIES, **BONDS, **COMMODITIES}.items():
        data = get_yfinance_data(config["yfinance"])
        if data:
            yf_data[symbol] = data

    # Macro regime determination
    btc_data = merged_markets.get("BTC", {})
    btc_30d = btc_data.get("change_30d", 0) or 0 if btc_data else 0
    fng_value = int(fng.get("value", 50) or 50) if fng else 50

    if btc_30d > 5 and fng_value > 55:
        regime = "Risk-On"
    elif btc_30d < -10 or fng_value < 35:
        regime = "Risk-Off"
    else:
        regime = "Neutral"

    # Benchmarks for non-crypto scoring
    spy_30d = (yf_data.get("SPY", {}) or {}).get("change_30d", None)
    macro_data_early = await fetch_macro_data()
    live_vix = macro_data_early.get("vix")

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
            # Use merged markets (Binance primary, CoinGecko fallback)
            market_data = merged_markets.get(asset_id, {})
            tvl = llama_tvl.get(asset_id, 0)

        # Skip if no market data
        if not market_data:
            continue

        # Calculate pillar scores with breakdown
        is_tradfi = asset_class in ["US Equity", "US Bond", "Commodity"]
        # BTC: no BTC benchmark (can't compare to itself); spy_change_30d passed so A pillar uses SPY cross-asset
        # Other crypto: use BTC 30d as benchmark
        # TradFi: no BTC benchmark; use SPY (with SPY itself excluded)
        asset_btc_30d = btc_30d if (asset_id != "BTC" and not is_tradfi) else None
        asset_spy_30d = spy_30d if (is_tradfi and asset_id != "SPY") or asset_id == "BTC" else None
        gh_commits = github_activity.get(asset_id)
        pillars_result = calculate_cis_score(
            market_data, tvl, fng, asset_class,
            btc_change_30d=asset_btc_30d,
            github_commits_4w=gh_commits,
            vix=live_vix if is_tradfi else None,
            spy_change_30d=asset_spy_30d,
        )
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
            "price": market_data.get("price", 0),
            "change_24h": round(market_data.get("change_24h", 0) or 0, 2),
            "market_cap": market_data.get("market_cap", 0),
            "volume_24h": market_data.get("volume_24h", 0),
            "tvl": tvl,
        })

    # Sort by CIS score
    universe.sort(key=lambda x: x["cis_score"], reverse=True)

    # Compute percentile ranks (metadata only — absolute grades from get_grade())
    universe = compute_percentile_ranks(universe)

    # Use macro_data already fetched above (cached, no double call)
    macro_data = macro_data_early
    macro = {
        "regime": regime,  # Keep our Risk-On/Off determination
        "fed_funds": macro_data.get("fed_funds"),
        "treasury_10y": macro_data.get("treasury_10y"),
        "vix": macro_data.get("vix"),
        "dxy": macro_data.get("dxy"),
        "cpi_yoy": macro_data.get("cpi_yoy"),
        "btc_dominance": macro_data.get("btc_dominance"),
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
        "data_source": "binance+defillama+alternative.me",
        "macro": macro,
        "universe": universe,
    }


# Test
if __name__ == "__main__":
    import json
    result = asyncio.run(calculate_cis_universe())
    print(json.dumps(result, indent=2))
