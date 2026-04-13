"""
CIS Data Provider - Real-time CIS scoring from market data
===========================================================
Fetches real market data and calculates CIS scores using the scoring engine.
v4.1: Continuous scoring functions, unified grading, LAS.

Author: Seth
"""

import math
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
CG_PRO_BASE = "https://pro-api.coingecko.com/api/v3"
CG_API_KEY = os.getenv("COINGECKO_API_KEY", "")

# Upstash Redis — persistent L2 cache across Railway deploys
# Mirrors the pattern in data_layer.py. Gracefully no-ops if not configured.
_UPSTASH_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

import json as _json

async def _upstash_get(key: str):
    """Read from Upstash REST. Returns None on miss or if not configured."""
    if not _UPSTASH_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as cl:
            r = await cl.get(
                f"{_UPSTASH_URL}/get/{key}",
                headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
            )
            if r.status_code == 200:
                raw = r.json().get("result")
                return _json.loads(raw) if raw else None
    except Exception:
        pass
    return None

async def _upstash_set(key: str, val, ttl: int) -> bool:
    """Write to Upstash with TTL. Fire-and-forget — never blocks on failure."""
    if not _UPSTASH_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as cl:
            r = await cl.post(
                f"{_UPSTASH_URL}/set/{key}",
                content=_json.dumps(val),
                headers={
                    "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                    "Content-Type": "application/json",
                },
                params={"EX": ttl},
            )
            return r.status_code == 200
    except Exception:
        return False

def _cg_base() -> str:
    """Use Pro API if key is set, otherwise free tier."""
    return CG_PRO_BASE if CG_API_KEY else "https://api.coingecko.com/api/v3"

def _cg_headers() -> dict:
    """Attach Pro API key header if configured."""
    return {"x-cg-pro-api-key": CG_API_KEY} if CG_API_KEY else {}

# Crypto assets config - maps to CoinGecko IDs
CRYPTO_ASSETS = {
    # Top by market cap
    "BTC": {"coingecko": "bitcoin", "name": "Bitcoin", "class": "L1"},
    "ETH": {"coingecko": "ethereum", "name": "Ethereum", "class": "L1"},
    "BNB": {"coingecko": "binancecoin", "name": "BNB", "class": "L1"},
    "XRP": {"coingecko": "ripple", "name": "XRP", "class": "L1"},
    "SOL": {"coingecko": "solana", "name": "Solana", "class": "L1"},
    "ADA": {"coingecko": "cardano", "name": "Cardano", "class": "L1"},
    "DOGE": {"coingecko": "dogecoin", "name": "Dogecoin", "class": "Memecoin"},
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
    "MKR": {"coingecko": "maker", "name": "Maker", "class": "RWA"},
    "SNX": {"coingecko": "havven", "name": "Synthetix", "class": "DeFi"},
    "CRV": {"coingecko": "curve-dao-token", "name": "Curve", "class": "DeFi"},
    "LDO": {"coingecko": "lido-dao", "name": "Lido DAO", "class": "DeFi"},
    "COMP": {"coingecko": "compound-governance-token", "name": "Compound", "class": "DeFi"},
    "SUSHI": {"coingecko": "sushi", "name": "SushiSwap", "class": "DeFi"},
    # Infrastructure
    "LINK": {"coingecko": "chainlink", "name": "Chainlink", "class": "Infrastructure"},
    "STX": {"coingecko": "blockstack", "name": "Stacks", "class": "Infrastructure"},
    "RUNE": {"coingecko": "thorchain", "name": "THORChain", "class": "Infrastructure"},
    # RWA / Memes / High volume
    "ONDO": {"coingecko": "ondo-finance", "name": "Ondo Finance", "class": "RWA"},
    "PEPE": {"coingecko": "pepe", "name": "Pepe", "class": "Memecoin"},
    "WIF": {"coingecko": "dogwifcoin", "name": "WIF", "class": "Memecoin"},
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
    "ENA": {"coingecko": "ethena", "name": "Ethena", "class": "Infrastructure"},
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


# === Beta Calculation for S Pillar ===
async def calculate_asset_betas(asset_id: str, asset_price_30d: list) -> dict:
    """
    Calculate 30d rolling betas between asset and macro factors (DXY, VIX, 10Y).
    Returns beta values for each factor.
    """
    cache_key = f"betas:{asset_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        import yfinance as yf
        import numpy as np

        # Need at least 20 data points
        if len(asset_price_30d) < 20:
            return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "insufficient_data"}

        # Calculate asset returns
        asset_returns = []
        for i in range(1, len(asset_price_30d)):
            if asset_price_30d[i-1] > 0:
                ret = (asset_price_30d[i] - asset_price_30d[i-1]) / asset_price_30d[i-1]
                asset_returns.append(ret)

        if len(asset_returns) < 15:
            return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "insufficient_data"}

        # Fetch macro factor data
        factors = {}
        for symbol, name in [("DX-Y.NYB", "dxy"), ("^VIX", "vix"), ("^TNX", "tnx")]:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="35d")
                if len(hist) > 20:
                    prices = hist['Close'].values
                    rets = []
                    for i in range(1, len(prices)):
                        if prices[i-1] > 0:
                            r = (prices[i] - prices[i-1]) / prices[i-1]
                            rets.append(r)
                    if len(rets) >= 15:
                        factors[name] = rets
            except Exception as e:
                print(f"[Beta] yfinance factor {symbol} failed: {e}")

        if not factors:
            return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "yfinance_error"}

        # Align lengths (use minimum)
        min_len = min(len(asset_returns), min(len(f.get("dxy", [0])) if "dxy" in factors else 0,
                                               len(factors.get("vix", [0])),
                                               len(factors.get("tnx", [0]))))

        if min_len < 15:
            return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "insufficient_data"}

        # Calculate betas (simplified correlation * (asset_std / factor_std))
        def calc_beta(asset_rets, factor_rets):
            if len(asset_rets) != len(factor_rets):
                min_len = min(len(asset_rets), len(factor_rets))
                asset_rets = asset_rets[:min_len]
                factor_rets = factor_rets[:min_len]
            if np.std(asset_rets) == 0 or np.std(factor_rets) == 0:
                return 0
            correlation = np.corrcoef(asset_rets, factor_rets)[0, 1]
            if np.isnan(correlation):
                return 0
            return round(correlation, 3)

        result = {
            "dxy_beta": calc_beta(asset_returns, factors.get("dxy", [0])),
            "vix_beta": calc_beta(asset_returns, factors.get("vix", [0])),
            "tnx_beta": calc_beta(asset_returns, factors.get("tnx", [0])),
            "source": "30d_rolling"
        }

        return _cache_set(cache_key, result)

    except Exception as e:
        return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "error"}


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
    """Fetch crypto prices from Binance public data mirror.

    Uses data-api.binance.vision (not api.binance.com) — the vision endpoint
    is geo-accessible from Railway US, whereas api.binance.com is geo-blocked.

    Cache hierarchy: L1 in-process → L2 Upstash (300s TTL, survives deploys).
    """
    cache_key = "binance_prices"
    redis_key = "cis:binance_prices"

    cached = _cache_get(cache_key)
    if cached:
        return cached

    r2 = await _upstash_get(redis_key)
    if r2:
        _cache_set(cache_key, r2)
        return r2

    result = {}
    binsym = list(BINANCE_SYMBOLS.values())

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # data-api.binance.vision is the public mirror — no geo-block, no API key
            url = "https://data-api.binance.vision/api/v3/ticker/24hr"

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
            _cache_set(cache_key, result)
            await _upstash_set(redis_key, result, ttl=300)   # 5min TTL — prices are time-sensitive
            return result

    except Exception as e:
        print(f"Binance API error: {e}")
        return r2 or result


async def fetch_cg_markets() -> Dict[str, dict]:
    """Fetch market data from CoinGecko for all tracked crypto assets.

    Cache hierarchy:
      L1 — in-process memory (_cache): 300s TTL, resets on restart/deploy
      L2 — Upstash Redis: 1800s TTL, survives Railway deploys and cold starts

    Uses explicit coin IDs (not top-N) so POLYX, NEON etc. are always included.
    Batches into chunks of 50 to stay within CG URL length limits.
    """
    cache_key = "cg_markets_v3"
    redis_key = "cis:cg_markets_v3"

    # L1: in-process memory (fastest)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # L2: Upstash Redis (survives deploys)
    r2 = await _upstash_get(redis_key)
    if r2:
        _cache_set(cache_key, r2)   # warm L1
        return r2

    result = {}

    # Collect all CoinGecko IDs we need
    all_cg_ids = [cfg["coingecko"] for cfg in CRYPTO_ASSETS.values() if cfg.get("coingecko")]
    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for cid in all_cg_ids:
        if cid not in seen:
            seen.add(cid)
            unique_ids.append(cid)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Batch into chunks of 50 IDs to avoid URL length issues
            batch_size = 50
            for i in range(0, len(unique_ids), batch_size):
                batch = unique_ids[i:i + batch_size]
                ids_str = ",".join(batch)

                url = f"{_cg_base()}/coins/markets"
                params = {
                    "vs_currency": "usd",
                    "ids": ids_str,
                    "order": "market_cap_desc",
                    "per_page": 250,
                    "page": 1,
                    "sparkline": False,
                    "price_change_percentage": "30d,7d"
                }
                r = await client.get(url, params=params, headers=_cg_headers())
                r.raise_for_status()
                data = r.json()

                for coin in data:
                    coin_id = coin["id"]
                    result[coin_id] = {
                        "symbol": coin["symbol"].upper(),
                        "name": coin["name"],
                        "market_cap": coin.get("market_cap", 0),
                        "fdv": coin.get("fully_diluted_valuation", 0),
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

                # Rate limit: small delay between batches (free tier: 10-30 req/min)
                if i + batch_size < len(unique_ids):
                    await asyncio.sleep(1.5)

            print(f"CoinGecko: fetched {len(result)}/{len(unique_ids)} assets")
            _cache_set(cache_key, result)                       # L1
            await _upstash_set(redis_key, result, ttl=1800)    # L2: 30min TTL
            return result

    except Exception as e:
        print(f"CoinGecko API error: {e}")
        # Return stale L2 if available rather than empty
        if not r2:
            r2 = await _upstash_get(redis_key)
        return r2 or result


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
            r = await client.get(f"{_cg_base()}/global", headers=_cg_headers())
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
        except Exception as e:
            print(f"[GitHub] activity fetch for {repo}: {e}")
        return asset_id, None

    tasks = [_fetch_one(aid, repo) for aid, repo in GITHUB_REPOS.items()]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    for item in raw:
        if isinstance(item, tuple) and item[1] is not None:
            results[item[0]] = int(item[1])

    # Use a 2-hour TTL via a manual timestamp check on next hit
    # (simple _cache_set uses global _cache_ttl=300; we override by storing a wrapper)
    _cache[cache_key] = (results, datetime.now().timestamp() + 7200)
    return results


async def get_yfinance_data(symbol: str) -> Optional[dict]:
    """Fetch US equity/bond/commodity data using yfinance."""
    cache_key = f"yf:{symbol}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        import yfinance as yf

        # Rate limiting - async sleep to avoid blocking event loop
        await asyncio.sleep(0.2)

        def _fetch():
            ticker = yf.Ticker(symbol)
            info = ticker.info
            hist = ticker.history(period="35d")
            price_now = float(hist['Close'].iloc[-1]) if len(hist) > 0 else 0
            # 7D change from history
            if len(hist) > 7:
                price_7d_ago = float(hist['Close'].iloc[-8])
                change_7d = ((price_now - price_7d_ago) / price_7d_ago) * 100 if price_7d_ago else 0
            else:
                change_7d = 0
            # 30D change from history
            if len(hist) > 30:
                price_30d_ago = float(hist['Close'].iloc[-31] if len(hist) > 31 else hist['Close'].iloc[0])
                change_30d = ((price_now - price_30d_ago) / price_30d_ago) * 100 if price_30d_ago else 0
            else:
                change_30d = 0
            return {
                "symbol": symbol,
                "price": info.get("currentPrice", info.get("regularMarketPrice", 0)),
                "market_cap": info.get("marketCap", 0),
                "volume_24h": info.get("regularMarketVolume", 0),
                "change_24h": info.get("regularMarketChange", 0),
                "change_7d": change_7d,
                "change_30d": change_30d,
                "circulating_supply": info.get("sharesOutstanding", 0),
                "total_supply": info.get("sharesOutstanding", 0),
                "ath_change_percentage": 0,  # yfinance doesn't provide this directly
            }

        result = await asyncio.to_thread(_fetch)
        return _cache_set(cache_key, result)
    except Exception as e:
        # Don't print on rate limit - it's expected
        if "Rate limited" not in str(e):
            print(f"yfinance error for {symbol}: {e}")
        return None


# Macro data cache path - configurable via env var for different deployments
# On Mac Mini: /Volumes/CometCloudAI/data/macro_cache.json
# On Railway: set MACRO_CACHE_PATH env var to a Railway-appropriate path
MACRO_CACHE_PATH = os.getenv("MACRO_CACHE_PATH", "/Volumes/CometCloudAI/data/macro_cache.json")
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
    except Exception as e:
        print(f"[MacroCache] read failed: {e}")
    return None


def _save_macro_cache(data: dict):
    """Save macro data to external drive cache."""
    try:
        cache_dir = os.path.dirname(MACRO_CACHE_PATH)
        if not os.path.exists(cache_dir):
            # Path not available (e.g., Railway) — skip disk cache silently
            return
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
    FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
    # FRED is optional enrichment — VIX, DXY, btc_dominance come from yfinance/CG
    # If key missing, skip FRED fetch entirely and rely on yfinance fallbacks below

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

    # Fetch from FRED API (optional — skip entirely if key not configured)
    if FRED_API_KEY:
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
            except Exception as e:
                print(f"[YFinance] price fetch failed for {symbol}: {e}")
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


def _log_score(value: float, base: float, scale: float, cap: float) -> float:
    """Continuous log-scale scoring. value=base → 0, each 10x → +scale, capped at cap."""
    if value <= 0:
        return 0.0
    if value <= base:
        return 0.0
    return min(cap, scale * math.log10(value / base))


def _linear_interp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Linear interpolation clamped to [y0, y1] (or [y1, y0] if inverted)."""
    lo, hi = min(y0, y1), max(y0, y1)
    if x1 == x0:
        return (y0 + y1) / 2
    t = (x - x0) / (x1 - x0)
    return max(lo, min(hi, y0 + t * (y1 - y0)))


def calculate_cis_score(
    market_data: dict,
    tvl: float,
    fng: Optional[dict],
    asset_class: str,
    btc_change_30d: Optional[float] = None,
    github_commits_4w: Optional[int] = None,
    vix: Optional[float] = None,
    spy_change_30d: Optional[float] = None,
    asset_betas: Optional[dict] = None,
    category_median_30d: Optional[float] = None,  # v4.1: median 30d change for category
    dev_activity_score: Optional[float] = None,   # v4.2: CG Pro dev score 0-100 (tech assets)
    eodhd_fundamentals: Optional[dict] = None,    # v4.2: EODHD PE/revenue data (US Equity)
) -> Dict[str, Any]:
    """
    CIS v4.2 — Continuous scoring functions.
    All pillars use log-scale or linear interpolation for genuine differentiation.
    v4.2 additions: CG Pro dev_activity_score in F pillar for tech assets;
    EODHD PE/revenue scoring in F pillar for US Equity.
    """
    market_cap = market_data.get("market_cap", 0) if market_data else 0
    volume_24h = market_data.get("volume_24h", 0) if market_data else 0
    circ_supply = market_data.get("circulating_supply", 0) if market_data else 0
    total_supply = market_data.get("total_supply", 0) if market_data else 0
    change_30d = market_data.get("change_30d", 0) or 0
    change_7d = market_data.get("change_7d", 0) or 0
    change_24h = market_data.get("change_24h", 0) or 0
    ath_distance = abs(market_data.get("ath_change_percentage", 0)) if market_data else 50
    price = market_data.get("price", 0) if market_data else 0
    high_24h = market_data.get("high_24h", 0) or 0
    low_24h = market_data.get("low_24h", 0) or 0
    fdv = market_data.get("fdv", 0) if market_data else 0
    _is_tradfi = asset_class in ["US Equity", "US Bond", "Commodity"]

    # ── F — Fundamental (Structural Quality) ──────────────────────────
    # Continuous: mcap log-scale (0-50) + tvl log-scale (0-20) + fdv fairness (0-15) + supply (0-15)
    # v4.2: US Equity → PE/revenue replace fdv/supply; tech assets → CG dev_activity bonus (0-10)
    has_tvl_class = asset_class in ["DeFi", "L2"]
    mcap_cap = 50 if has_tvl_class else 70  # Redistribute TVL points if N/A

    mcap_score = _log_score(market_cap, 1e6, 10, mcap_cap)  # $1M base, +10 per decade
    tvl_score = _log_score(tvl, 1e6, 5, 20) if (has_tvl_class and tvl and tvl > 0) else 0.0

    # FDV fairness: ratio=1 → 15, ratio≥5 → 0, linear between
    fdv_score = 0.0
    supply_ratio = (circ_supply / total_supply) if (total_supply > 0 and circ_supply > 0) else 0
    supply_score = min(15, supply_ratio * 15)

    if asset_class != "US Equity":
        if fdv > 0 and market_cap > 0:
            ratio = fdv / market_cap
            fdv_score = max(0, _linear_interp(ratio, 1.0, 5.0, 15.0, 0.0))

    # v4.2: EODHD fundamentals for US Equity — PE + revenue replace fdv + supply
    eodhd_pe_score = 0.0
    eodhd_rev_score = 0.0
    if asset_class == "US Equity" and eodhd_fundamentals:
        pe = eodhd_fundamentals.get("pe_ratio")
        # EODHD field is "revenue_growth" (TTM) — accept both keys for safety
        rev_growth = eodhd_fundamentals.get("revenue_growth_yoy") or eodhd_fundamentals.get("revenue_growth")
        # PE scoring: sweet spot 10-25 → up to 15pts; high PE or negative → penalty
        if pe is not None and pe > 0:
            if pe <= 10:
                eodhd_pe_score = _linear_interp(pe, 5, 10, 8, 13)
            elif pe <= 25:
                eodhd_pe_score = _linear_interp(pe, 10, 25, 13, 15)
            elif pe <= 40:
                eodhd_pe_score = _linear_interp(pe, 25, 40, 15, 5)
            else:
                eodhd_pe_score = max(0, _linear_interp(pe, 40, 100, 5, 0))
        # Revenue growth YoY: -10% → 0, flat → 7, +25% → 15 (cap)
        if rev_growth is not None:
            if rev_growth >= 25:
                eodhd_rev_score = 15.0
            elif rev_growth >= 0:
                eodhd_rev_score = _linear_interp(rev_growth, 0, 25, 7, 15)
            else:
                eodhd_rev_score = max(0, _linear_interp(rev_growth, -10, 0, 0, 7))
        fdv_score = eodhd_pe_score
        supply_score = eodhd_rev_score

    # v4.2: Dev activity bonus for tech assets (CG Pro developer_data, pre-fetched)
    # Classes that benefit: L1, L2, DeFi, Infrastructure, AI, RWA
    _is_tech_asset = asset_class in {"L1", "L2", "DeFi", "Infrastructure", "AI", "RWA"}
    dev_bonus = 0.0
    if _is_tech_asset and dev_activity_score is not None:
        # dev_activity_score 0-100 → bonus 0-10 (linear; 50 → 5, 90 → 9)
        dev_bonus = min(10.0, dev_activity_score * 0.10)

    f_score = round(max(0, min(100, mcap_score + tvl_score + fdv_score + supply_score + dev_bonus)), 1)

    f_components: dict = {
        "market_cap_usd": market_cap,
        "market_cap_score": round(mcap_score, 1),
        "tvl_usd": tvl if has_tvl_class else None,
        "tvl_score": round(tvl_score, 1),
    }
    if asset_class == "US Equity" and eodhd_fundamentals:
        f_components.update({
            "pe_ratio": eodhd_fundamentals.get("pe_ratio"),
            "pe_score": round(eodhd_pe_score, 1),
            "revenue_growth_yoy": eodhd_fundamentals.get("revenue_growth_yoy") or eodhd_fundamentals.get("revenue_growth"),
            "revenue_score": round(eodhd_rev_score, 1),
            "gross_margin": eodhd_fundamentals.get("gross_margin"),
            "profit_margin": eodhd_fundamentals.get("profit_margin"),
        })
    else:
        f_components.update({
            "fdv_usd": fdv,
            "fdv_ratio": round(fdv / market_cap, 2) if market_cap > 0 and fdv > 0 else None,
            "fdv_score": round(fdv_score, 1),
            "supply_ratio": round(supply_ratio, 3),
            "supply_score": round(supply_score, 1),
        })
    if dev_bonus > 0:
        f_components["dev_activity_score_cg"] = round(dev_activity_score, 1)
        f_components["dev_bonus"] = round(dev_bonus, 1)

    # ── M — Momentum (Market Activity) ───────────────────────────────
    # volume log-scale (0-40) + liquidity ratio (0-25) + price momentum (0-35)
    vol_score = _log_score(volume_24h, 1e5, 8, 40)  # $100K base, +8 per decade

    # Liquidity ratio: vol/mcap continuous, cap at 25
    liq_score = 0.0
    if market_cap > 0:
        vol_ratio = volume_24h / market_cap
        if vol_ratio >= 0.01:
            liq_score = min(25, vol_ratio * 200)  # 5%→10, 12.5%→25
        else:
            liq_score = max(-5, vol_ratio * 1000 - 5)  # Below 1% → penalty

    # Price momentum 30d: continuous linear map
    # -50% → 0, 0% → 15, +50% → 30, +100% → 35
    if change_30d <= -50:
        mom_score = 0.0
    elif change_30d <= 0:
        mom_score = _linear_interp(change_30d, -50, 0, 0, 15)
    elif change_30d <= 50:
        mom_score = _linear_interp(change_30d, 0, 50, 15, 30)
    else:
        mom_score = min(35, _linear_interp(change_30d, 50, 100, 30, 35))

    m_score = round(max(0, min(100, vol_score + liq_score + mom_score)), 1)

    m_components = {
        "volume_24h": volume_24h,
        "volume_score": round(vol_score, 1),
        "volume_mcap_ratio": round(volume_24h / market_cap, 4) if market_cap > 0 else 0,
        "liquidity_score": round(liq_score, 1),
        "momentum_30d_pct": round(change_30d, 1),
        "momentum_score": round(mom_score, 1),
    }

    # ── O — On-Chain Health / Risk-Adjusted ──────────────────────────
    # ATH recovery (0-35) + drawdown estimate (0-35) + supply+tvl health (0-30)

    # ATH recovery: continuous, at ATH → 35, -80% → 0
    ath_score = max(0, _linear_interp(ath_distance, 0, 80, 35, 0))

    # Drawdown estimate from 24h range (annualized vol proxy)
    dd_score = 35.0  # default if no range data
    if low_24h > 0 and high_24h > low_24h:
        daily_range = (high_24h - low_24h) / low_24h
        ann_vol = daily_range * math.sqrt(365) * 100  # rough annualized
        dd_score = max(0, _linear_interp(ann_vol, 0, 200, 35, 0))

    # Supply + TVL health (reuse)
    health_score = supply_score  # 0-15 from F pillar
    if has_tvl_class and tvl and tvl > 0:
        health_score += min(15, _log_score(tvl, 1e6, 3.75, 15))
    else:
        health_score += max(0, _linear_interp(ath_distance, 0, 50, 15, 0))

    o_score = round(max(0, min(100, ath_score + dd_score + health_score)), 1)

    o_components = {
        "ath_distance_pct": round(ath_distance, 1),
        "ath_recovery_score": round(ath_score, 1),
        "drawdown_estimate_score": round(dd_score, 1),
        "health_score": round(health_score, 1),
        "supply_ratio": round(supply_ratio, 3),
        "tvl_usd": tvl,
    }

    # ── S — Sentiment (Baseline + Divergence + Vol Regime) ───────────
    # baseline (0-40) + divergence (-20 to +40) + vol regime (-10 to +20)

    s_components = {
        "return_30d": round(change_30d / 100, 4),
        "return_24h": round(change_24h / 100, 4),
    }

    # Baseline
    # v4.1.1 enhancement: crypto baseline now uses 3-signal composite (0-40)
    # instead of FNG×0.4 alone. Signals are volume-observable and momentum-derived.
    baseline = 0.0
    if _is_tradfi:
        s_components["vix"] = vix
        if vix is not None:
            # VIX continuous: 10 → 40, 20 → 24, 35 → 0
            baseline = max(0, _linear_interp(vix, 10, 35, 40, 0))
            s_components["baseline_score"] = round(baseline, 1)
        else:
            baseline = 20  # neutral fallback
            s_components["baseline_score"] = 20
    else:
        # === Signal 1: Volume Surge (0–15) ===
        # Relative turnover (vol/mcap) as a proxy for active market participation.
        # High vol/mcap = real interest; low = dead market.
        vol_surge_signal = 0.0
        if market_cap > 0 and volume_24h > 0:
            vol_mcap_ratio = volume_24h / market_cap
            if vol_mcap_ratio >= 0.10:
                vol_surge_signal = 15.0
            elif vol_mcap_ratio >= 0.03:
                vol_surge_signal = _linear_interp(vol_mcap_ratio, 0.03, 0.10, 8.0, 15.0)
            elif vol_mcap_ratio >= 0.01:
                vol_surge_signal = _linear_interp(vol_mcap_ratio, 0.01, 0.03, 3.0, 8.0)
            elif vol_mcap_ratio >= 0.003:
                vol_surge_signal = _linear_interp(vol_mcap_ratio, 0.003, 0.01, 0.0, 3.0)
            # below 0.3% vol/mcap → 0 (illiquid / dead)
        else:
            vol_mcap_ratio = 0.0

        # === Signal 2: Momentum Structure (0–15) ===
        # Cross-timeframe alignment (24h / 7d / 30d). Aligned trend = conviction.
        # Mixed = neutral. All negative = risk-off.
        mom_struct = 0.0
        if change_24h > 0 and change_7d > 0 and change_30d > 0:
            # Full bullish alignment: score by composite strength
            strength = min(1.0, (change_24h / 3.0 + change_7d / 10.0 + change_30d / 20.0) / 3.0)
            mom_struct = _linear_interp(strength, 0.0, 1.0, 8.0, 15.0)
        elif change_24h < 0 and change_7d < 0 and change_30d < 0:
            # Full bearish alignment: no contribution (handled by divergence penalty)
            mom_struct = 0.0
        else:
            # Mixed signals: moderate score based on medium-term direction
            if change_7d > 5:
                mom_struct = _linear_interp(change_7d, 5.0, 20.0, 7.0, 11.0)
            elif change_7d >= -3:
                mom_struct = 6.0  # consolidating / neutral
            else:
                mom_struct = max(0.0, _linear_interp(change_7d, -15.0, -3.0, 0.0, 6.0))

        # === Signal 3: FNG Secondary (0–10) ===
        # Fear & Greed as a reduced-weight sentiment backdrop only.
        fng_value = int(fng.get("value", 50)) if fng else None
        s_components["fear_greed_value"] = fng_value
        s_components["fear_greed_classification"] = fng.get("value_classification") if fng else None
        fng_secondary = 0.0
        if fng_value is not None:
            fng_secondary = _linear_interp(float(fng_value), 0.0, 100.0, 0.0, 10.0)
        else:
            fng_secondary = 5.0  # neutral fallback

        baseline = vol_surge_signal + mom_struct + fng_secondary
        s_components["vol_surge_signal"] = round(vol_surge_signal, 1)
        s_components["vol_mcap_ratio"] = round(vol_mcap_ratio, 4)
        s_components["momentum_structure_signal"] = round(mom_struct, 1)
        s_components["fng_secondary_signal"] = round(fng_secondary, 1)
        s_components["baseline_score"] = round(baseline, 1)

    # Divergence: asset 30d vs category median (continuous)
    cat_median = category_median_30d if category_median_30d is not None else 0
    asset_div = change_30d - cat_median
    div_score = max(-15, min(25, asset_div * 0.5))
    # 24h burst
    burst_score = max(-5, min(10, change_24h * 0.5))
    divergence_total = div_score + burst_score
    s_components["category_divergence"] = round(asset_div, 1)
    s_components["divergence_score"] = round(div_score, 1)
    s_components["burst_score"] = round(burst_score, 1)

    # Dev activity
    dev_score = 0.0
    if github_commits_4w is not None:
        s_components["github_commits_4w"] = github_commits_4w
        if github_commits_4w > 300:
            dev_score = 5
        elif github_commits_4w > 100:
            dev_score = 3
        elif github_commits_4w > 30:
            dev_score = 1
        elif github_commits_4w <= 5:
            dev_score = -8
        s_components["dev_activity_score"] = dev_score
    else:
        s_components["github_commits_4w"] = None
        s_components["dev_activity_score"] = None

    # Volatility regime modifier
    vol_regime_score = 0.0
    if low_24h > 0 and high_24h > low_24h:
        daily_range_pct = ((high_24h - low_24h) / low_24h) * 100
        elevated_vol = daily_range_pct > 5  # >5% daily range = elevated
        if elevated_vol and change_7d > 5:
            vol_regime_score = 15  # breakout
        elif elevated_vol and change_7d < -5:
            vol_regime_score = -10  # capitulation
        elif not elevated_vol and change_7d > 3:
            vol_regime_score = 10  # accumulation
        elif not elevated_vol and change_7d < -3:
            vol_regime_score = -5  # stagnation
        s_components["vol_regime"] = "breakout" if vol_regime_score > 10 else "capitulation" if vol_regime_score < -5 else "accumulation" if vol_regime_score > 0 else "stagnation" if vol_regime_score < 0 else "neutral"
    s_components["vol_regime_score"] = round(vol_regime_score, 1)

    # Beta scoring (unchanged logic, continuous)
    beta_score = 0.0
    if asset_betas and asset_betas.get("source") == "30d_rolling":
        dxy_beta = asset_betas.get("dxy_beta", 0)
        vix_beta = asset_betas.get("vix_beta", 0)
        s_components["dxy_beta"] = dxy_beta
        s_components["vix_beta"] = vix_beta
        if dxy_beta < 0:
            beta_score += min(10, abs(dxy_beta) * 10)
        elif dxy_beta > 0.7:
            beta_score -= 5
        if vix_beta < 0:
            beta_score += min(5, abs(vix_beta) * 5)
        s_components["beta_score"] = round(beta_score, 1)
    else:
        s_components["beta_score"] = 0

    s_score = round(max(0, min(100, baseline + divergence_total + dev_score + vol_regime_score + beta_score)), 1)

    # ── A — Alpha Independence ───────────────────────────────────────
    # benchmark divergence (-20 to +40) + class independence (0-20) + size efficiency (-5 to +20) + correlation (-15 to 0)
    a_components = {
        "asset_class": asset_class,
        "market_cap_usd": market_cap,
        "ath_distance_pct": ath_distance,
    }

    # Class independence
    class_ind = 0.0
    if not _is_tradfi:
        class_map = {"DeFi": 20, "RWA": 20, "L2": 18, "Infrastructure": 15, "L1": 12, "Memecoin": 5}
        class_ind = class_map.get(asset_class, 8)
    a_components["class_independence_score"] = class_ind

    # Size efficiency: smaller cap with relatively strong fundamentals → more alpha potential
    size_eff = 0.0
    if market_cap > 100e9:
        size_eff = -5
    elif market_cap > 10e9:
        size_eff = 0
    elif market_cap > 1e9:
        size_eff = 10
    elif market_cap > 100e6:
        size_eff = 15
    else:
        size_eff = 20
    a_components["size_efficiency_score"] = size_eff

    # Benchmark divergence — continuous linear
    div_a_score = 0.0
    if _is_tradfi:
        if spy_change_30d is not None and asset_class != "US Equity":
            if asset_class == "US Bond":
                divergence = spy_change_30d - change_30d
            else:
                divergence = change_30d - spy_change_30d
            a_components["spy_divergence_30d"] = round(divergence, 1)
            div_a_score = max(-20, min(40, divergence * 0.8))
            a_components["alpha_score"] = round(div_a_score, 1)
        else:
            a_components["spy_divergence_30d"] = None
            a_components["alpha_score"] = 0
    else:
        if btc_change_30d is not None:
            divergence = change_30d - btc_change_30d
            a_components["btc_divergence_30d"] = round(divergence, 1)
            div_a_score = max(-20, min(40, divergence * 0.8))
            a_components["alpha_score"] = round(div_a_score, 1)
        elif spy_change_30d is not None:
            divergence = change_30d - spy_change_30d
            a_components["spy_divergence_30d"] = round(divergence, 1)
            a_components["benchmark"] = "SPY (cross-asset)"
            div_a_score = max(-20, min(40, divergence * 0.8))
            a_components["alpha_score"] = round(div_a_score, 1)
        else:
            a_components["btc_divergence_30d"] = None
            a_components["alpha_score"] = 0

    # Correlation discount (from betas)
    corr_discount = 0.0
    if asset_betas and asset_betas.get("source") == "30d_rolling":
        btc_corr = abs(asset_betas.get("dxy_beta", 0))
        if btc_corr > 0.8:
            corr_discount = -15
        elif btc_corr > 0.5:
            corr_discount = -8
    a_components["correlation_discount"] = corr_discount

    a_score = round(max(0, min(100, class_ind + size_eff + div_a_score + corr_discount + 10)), 1)  # +10 base

    # ── Build breakdown ──────────────────────────────────────────────
    breakdown = {
        "fundamental": {"score": f_score, "components": f_components},
        "momentum": {"score": m_score, "components": m_components},
        "risk_adjusted": {"score": o_score, "components": o_components},
        "sensitivity": {"score": s_score, "components": s_components},
        "alpha": {"score": a_score, "components": a_components},
    }

    return {
        "F": f_score,
        "M": m_score,
        "O": o_score,
        "S": s_score,
        "A": a_score,
        "breakdown": breakdown,
    }


def detect_regime(
    btc_30d: float,
    fng_value: int,
    vix: Optional[float],
    btc_dominance: Optional[float] = None,
) -> str:
    """
    Classify macro regime from 4 signals.
    Returns one of: Goldilocks / Risk-On / Easing / Neutral / Tightening / Risk-Off / Stagflation
    Used to shift pillar weights in calculate_total_score().
    """
    vix  = vix  or 20.0
    bdom = btc_dominance or 52.0

    # Goldilocks: strong momentum + greed + calm vol
    if btc_30d > 10 and fng_value > 60 and vix < 17:
        return "Goldilocks"
    # Pure Risk-On: positive momentum + greed (VIX moderate)
    if btc_30d > 5 and fng_value > 55:
        return "Risk-On"
    # Stagflation: high vol + falling crypto + BTC dom surge (flight-to-quality)
    if vix > 27 and btc_30d < -5 and bdom > 58:
        return "Stagflation"
    # Risk-Off: severe fear or crash
    if btc_30d < -12 or fng_value < 28 or vix > 30:
        return "Risk-Off"
    # Tightening: elevated vol + compressed sentiment (rates up / liquidity withdrawal)
    if vix > 21 and fng_value < 48:
        return "Tightening"
    # Easing: calm vol + recovering sentiment (liquidity returning)
    if vix < 17 and fng_value > 45:
        return "Easing"
    return "Neutral"


def calculate_total_score(
    pillars: Dict[str, float],
    asset_class: str,
    regime: str = "Neutral",
) -> Dict[str, Any]:
    """Calculate weighted total CIS score with regime-aware pillar weights."""

    # Base weights per asset class
    _BASE_WEIGHTS: Dict[str, Dict[str, float]] = {
        "Crypto":         {"F": 0.25, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.15},
        "L1":             {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "L2":             {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "DeFi":           {"F": 0.25, "M": 0.25, "O": 0.25, "S": 0.15, "A": 0.10},
        "RWA":            {"F": 0.35, "M": 0.20, "O": 0.20, "S": 0.15, "A": 0.10},
        "Infrastructure": {"F": 0.30, "M": 0.20, "O": 0.25, "S": 0.10, "A": 0.15},
        "NFT":            {"F": 0.15, "M": 0.25, "O": 0.15, "S": 0.30, "A": 0.15},
        "Memecoin":       {"F": 0.15, "M": 0.35, "O": 0.15, "S": 0.25, "A": 0.10},
        "Gaming":         {"F": 0.20, "M": 0.30, "O": 0.15, "S": 0.25, "A": 0.10},
        "AI":             {"F": 0.20, "M": 0.30, "O": 0.20, "S": 0.15, "A": 0.15},
        "US Equity":      {"F": 0.30, "M": 0.25, "O": 0.10, "S": 0.20, "A": 0.15},
        "US Bond":        {"F": 0.30, "M": 0.20, "O": 0.10, "S": 0.20, "A": 0.20},
        "Commodity":      {"F": 0.25, "M": 0.25, "O": 0.10, "S": 0.20, "A": 0.20},
    }

    # Regime multipliers — applied to base weights, then renormalized to sum=1.
    # Philosophy:
    #   Risk-On   → momentum + sentiment + alpha outperform; fundamentals matter less
    #   Risk-Off  → fundamentals + risk-adjusted protection; sentiment suppressed
    #   Tightening→ fundamentals dominate; momentum punished; risk-adj rises
    #   Easing    → alpha + momentum rewarded; fundamentals secondary
    #   Stagflation→ fundamentals + risk-adj paramount; sentiment & momentum penalized
    #   Goldilocks→ balanced but alpha + sentiment elevated
    _REGIME_MULT: Dict[str, Dict[str, float]] = {
        "Goldilocks":  {"F": 0.90, "M": 1.10, "O": 0.90, "S": 1.15, "A": 1.25},
        "Risk-On":     {"F": 0.85, "M": 1.20, "O": 0.85, "S": 1.20, "A": 1.25},
        "Easing":      {"F": 0.90, "M": 1.15, "O": 0.95, "S": 1.10, "A": 1.20},
        "Neutral":     {"F": 1.00, "M": 1.00, "O": 1.00, "S": 1.00, "A": 1.00},
        "Tightening":  {"F": 1.25, "M": 0.85, "O": 1.20, "S": 0.80, "A": 1.05},
        "Risk-Off":    {"F": 1.20, "M": 0.80, "O": 1.25, "S": 0.75, "A": 1.10},
        "Stagflation": {"F": 1.30, "M": 0.75, "O": 1.25, "S": 0.70, "A": 1.00},
    }

    base = dict(_BASE_WEIGHTS.get(asset_class, _BASE_WEIGHTS["Crypto"]))
    mult = _REGIME_MULT.get(regime, _REGIME_MULT["Neutral"])

    # Apply multipliers and renormalize so weights always sum to 1.0
    w = {k: base[k] * mult[k] for k in base}
    total_w = sum(w.values())
    w = {k: round(v / total_w, 4) for k, v in w.items()}

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
    """
    Unified absolute grading — v4.1.
    Both Railway and Mac Mini engines use these identical thresholds.
    See CIS_METHODOLOGY.md §5.
    """
    if score >= 85:  return "A+"
    if score >= 75:  return "A"
    if score >= 65:  return "B+"
    if score >= 55:  return "B"
    if score >= 45:  return "C+"
    if score >= 35:  return "C"
    if score >= 25:  return "D"
    return "F"


def compute_percentile_ranks(universe: list) -> list:
    """
    Compute percentile rank as METADATA only — does NOT override grades.
    v4.1: Grades come from absolute thresholds via get_grade().
    Percentile is still exposed in API for agents that want relative positioning.
    """
    if not universe:
        return universe
    n = len(universe)
    sorted_u = sorted(universe, key=lambda x: x.get("cis_score", 0), reverse=True)
    for i, asset in enumerate(sorted_u):
        rank = round(((n - i) / n) * 100, 1)
        asset["percentile_rank"] = rank
        # v4.1: NO grade override — absolute grades stand
    return sorted_u


def calculate_las(
    cis_score: float,
    volume_24h: float,
    high_24h: float,
    low_24h: float,
    confidence: float,
    aum: float = 30_000_000,
    max_position_pct: float = 0.05,
    participation_rate: float = 0.10,
) -> Dict[str, Any]:
    """
    Liquidity-Adjusted Score — v4.1.
    See CIS_METHODOLOGY.md §6.
    """
    target_position = aum * max_position_pct
    daily_tradeable = volume_24h * participation_rate

    if target_position > 0 and daily_tradeable > 0:
        liq_mult = min(1.0, daily_tradeable / target_position)
    elif daily_tradeable > 0:
        liq_mult = 1.0
    else:
        liq_mult = 0.0

    # Floor: any asset in the universe has at least 5% liquidity credit.
    # Prevents near-zero LAS from CoinGecko volume data quality issues
    # (e.g. MKR/POLYX only counting limited trading pairs).
    liq_mult = max(liq_mult, 0.05)

    # Spread penalty
    spread_penalty = 1.0
    if low_24h > 0 and high_24h > low_24h:
        hl_range = (high_24h - low_24h) / low_24h
        if hl_range > 0.05:
            spread_penalty = max(0.8, 1.0 - (hl_range - 0.05) * 2)

    las = round(cis_score * liq_mult * spread_penalty * confidence, 1)

    return {
        "las": max(0, las),
        "las_params": {
            "assumed_aum": aum,
            "participation_rate": participation_rate,
            "liquidity_multiplier": round(liq_mult, 3),
            "spread_penalty": round(spread_penalty, 3),
            "daily_tradeable_usd": round(daily_tradeable, 0),
        },
    }


def get_signal(score: float, grade: str) -> str:
    """
    CIS positioning signal — v4.1 compliance-safe.
    NO buy/sell language — we are not licensed investment advisors.
    These are quantitative positioning indicators, not investment recommendations.
    """
    if grade == "A+":
        return "STRONG OUTPERFORM"
    if grade in ("A", "B+"):
        return "OUTPERFORM"
    if grade in ("B", "C+"):
        return "NEUTRAL"
    if grade == "C":
        return "UNDERPERFORM"
    return "UNDERWEIGHT"  # D, F


async def calculate_cis_universe() -> Dict[str, Any]:
    """
    Calculate CIS scores for all tracked assets.
    Returns the complete universe with scores.

    Data sources:
    - Crypto: CoinGecko API
    - US Equities/Bonds/Commodities: yfinance
    """
    # ── v4.2 pre-fetch helpers ────────────────────────────────────────
    async def _fetch_cg_dev_bulk() -> dict:
        """Pre-fetch CG Pro developer_data for all tech assets. 24h Redis TTL."""
        _tech_classes = {"L1", "L2", "DeFi", "Infrastructure", "AI", "RWA"}
        _sem = asyncio.Semaphore(4)
        _results: dict = {}
        async def _one(aid: str, cg_id: str):
            async with _sem:
                try:
                    try:
                        from src.data.market.data_layer import get_cg_developer_data
                    except ImportError:
                        from data.market.data_layer import get_cg_developer_data
                    data = await get_cg_developer_data(cg_id)
                    if data and "error" not in data:
                        _results[aid] = data
                except Exception:
                    pass
        tasks = [
            _one(aid, cfg["coingecko"])
            for aid, cfg in CRYPTO_ASSETS.items()
            if cfg.get("class") in _tech_classes and cfg.get("coingecko")
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return _results

    async def _fetch_eodhd_bulk() -> dict:
        """Pre-fetch EODHD fundamentals for US Equity assets. 6h Redis TTL."""
        _sem = asyncio.Semaphore(3)
        _results: dict = {}
        async def _one(aid: str, ticker: str):
            async with _sem:
                try:
                    try:
                        from src.data.market.data_layer import get_eodhd_fundamentals
                    except ImportError:
                        from data.market.data_layer import get_eodhd_fundamentals
                    data = await get_eodhd_fundamentals(ticker, "US")
                    if data and "error" not in data:
                        _results[aid] = data
                except Exception:
                    pass
        tasks = [
            _one(aid, cfg["yfinance"])
            for aid, cfg in US_EQUITIES.items()
            if cfg.get("yfinance")
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return _results

    # Fetch all data concurrently
    # Priority: Binance (fast, no rate limit) > CoinGecko (fallback)
    binance_prices, cg_markets, llama_tvl, fng, github_activity, cg_dev_data, eodhd_data = await asyncio.gather(
        fetch_binance_prices(),
        fetch_cg_markets(),
        fetch_defillama_tvl(),
        fetch_fear_greed(),
        fetch_github_activity(),   # Phase 2B: dev activity (best-effort, 2h cache)
        _fetch_cg_dev_bulk(),      # v4.2: CG Pro developer data for tech assets
        _fetch_eodhd_bulk(),       # v4.2: EODHD fundamentals for US Equity
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
                cg_mc = cg_data.get("market_cap", 0) or 0
                cg_fdv = cg_data.get("fdv", 0) or 0
                cg_supply = cg_data.get("circulating_supply", 0) or 0
                # CG sometimes returns market_cap=0 for rebranded tokens (e.g. MKR→SKY).
                # Fallback chain: price×supply → FDV → volume×20
                if cg_mc == 0:
                    price = rec.get("price", 0) or cg_data.get("price", 0) or 0
                    if cg_supply > 0 and price > 0:
                        cg_mc = price * cg_supply
                    elif cg_fdv > 0:
                        cg_mc = cg_fdv
                    else:
                        volume = rec.get("volume_24h", 0) or cg_data.get("volume_24h", 0) or 0
                        if volume > 0:
                            cg_mc = volume * 20  # vol ~5% of mcap → ×20 conservative
                rec["market_cap"] = cg_mc
                rec["fdv"] = cg_fdv
                rec["circulating_supply"] = cg_supply
                rec["total_supply"] = cg_data.get("total_supply", 0) or 0
                rec["ath_change_percentage"] = cg_data.get("ath_change_percentage", 0) or 0
            else:
                # Fallback: estimate market_cap from volume when CoinGecko fails entirely
                volume = rec.get("volume_24h", 0) or 0
                if volume > 0 and rec.get("market_cap", 0) == 0:
                    rec["market_cap"] = volume * 20  # Conservative estimate
            merged_markets[asset_id] = rec
        elif cg_data:
            merged_markets[asset_id] = cg_data

    # Fetch yfinance data for US assets — parallel with semaphore to limit concurrency
    yf_data = {}
    yf_assets = {**US_EQUITIES, **BONDS, **COMMODITIES}
    yf_sem = asyncio.Semaphore(5)  # max 5 concurrent yfinance calls

    async def _fetch_yf(sym, cfg):
        async with yf_sem:
            return sym, await get_yfinance_data(cfg["yfinance"])

    yf_results = await asyncio.gather(
        *[_fetch_yf(sym, cfg) for sym, cfg in yf_assets.items()],
        return_exceptions=True
    )
    for item in yf_results:
        if isinstance(item, Exception):
            continue
        sym, data = item
        if data:
            yf_data[sym] = data

    # Macro data fetch — VIX needed for regime detection + S pillar
    macro_data_early = await fetch_macro_data()
    live_vix = macro_data_early.get("vix")

    # Macro regime determination — 7-state classifier using 4 signals
    btc_data = merged_markets.get("BTC", {})
    btc_30d = btc_data.get("change_30d", 0) or 0 if btc_data else 0
    fng_value = int(fng.get("value", 50) or 50) if fng else 50
    btc_dom = macro_data_early.get("btc_dominance")  # from fetch_macro_data CG global
    regime = detect_regime(btc_30d, fng_value, live_vix, btc_dom)

    # Benchmarks for non-crypto scoring
    spy_30d = (yf_data.get("SPY", {}) or {}).get("change_30d", None)

    # v4.1: Pre-compute category median 30d change for S pillar divergence
    category_changes = {}  # {class: [change_30d, ...]}
    for aid, cfg in ASSETS_CONFIG.items():
        ac = cfg["class"]
        if ac in ["US Equity", "US Bond", "Commodity"]:
            md = yf_data.get(aid, {})
        else:
            md = merged_markets.get(aid, {})
        if md:
            c30 = md.get("change_30d", 0) or 0
            category_changes.setdefault(ac, []).append(c30)
    category_medians = {}
    for ac, changes in category_changes.items():
        sorted_c = sorted(changes)
        n = len(sorted_c)
        category_medians[ac] = sorted_c[n // 2] if n else 0

    # Calculate scores for each asset
    universe = []

    # Pre-fetch klines for all crypto assets that need beta calculation (avoid N serial HTTP calls)
    try:
        from src.data.market.data_layer import get_klines as _gk
    except ImportError:
        try:
            from data.market.data_layer import get_klines as _gk
        except ImportError:
            _gk = None
    _kline_tasks = {}
    if _gk is not None:
        for aid, cfg in ASSETS_CONFIG.items():
            ac = cfg["class"]
            if ac not in ["US Equity", "US Bond", "Commodity"] and aid in BINANCE_SYMBOLS:
                sym = BINANCE_SYMBOLS[aid].upper().replace("USDT", "") + "USDT"
                _kline_tasks[aid] = _gk(sym, months=1)
    _kline_results = await asyncio.gather(*_kline_tasks.values(), return_exceptions=True) if _kline_tasks else []
    _kline_map = {}
    for aid, result in zip(_kline_tasks.keys(), _kline_results):
        if not isinstance(result, Exception) and result and len(result) >= 20:
            _kline_map[aid] = [k["close"] for k in result]

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

        # Calculate betas for crypto assets (pre-fetched above to avoid serial HTTP calls)
        asset_betas = None
        if not is_tradfi and asset_id in _kline_map:
            try:
                prices = _kline_map[asset_id]
                asset_betas = await calculate_asset_betas(asset_id, prices)
            except Exception as e:
                print(f"[CIS] beta calculation failed for {asset_id}: {e}")

        # v4.2: resolve per-asset enrichment data
        asset_dev_score = (cg_dev_data.get(asset_id) or {}).get("dev_activity_score") if not is_tradfi else None
        asset_eodhd = eodhd_data.get(asset_id) if asset_class == "US Equity" else None

        pillars_result = calculate_cis_score(
            market_data, tvl, fng, asset_class,
            btc_change_30d=asset_btc_30d,
            github_commits_4w=gh_commits,
            vix=live_vix if is_tradfi else None,
            spy_change_30d=asset_spy_30d,
            asset_betas=asset_betas,
            category_median_30d=category_medians.get(asset_class, 0),
            dev_activity_score=asset_dev_score,
            eodhd_fundamentals=asset_eodhd,
        )
        pillars = {k: v for k, v in pillars_result.items() if k != "breakdown"}
        breakdown = pillars_result.get("breakdown", {})

        # Calculate total with regime-aware weights
        total_result = calculate_total_score(pillars, asset_class, regime=regime)
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
        except Exception as e:
            print(f"[CIS] score change fetch failed for {asset_id}: {e}")

        # Max drawdown estimation (simplified from ath_distance)
        ath_distance = abs(market_data.get("ath_change_percentage", 0) or 0)
        max_drawdown_90d = min(ath_distance, 90)  # Cap at 90%

        # v4.1: Liquidity-Adjusted Score
        _vol_24h = market_data.get("volume_24h", 0) or 0
        _h24 = market_data.get("high_24h", 0) or 0
        _l24 = market_data.get("low_24h", 0) or 0
        las_result = calculate_las(total_score, _vol_24h, _h24, _l24, confidence)

        universe.append({
            "symbol": asset_id,
            "name": config["name"],
            "asset_class": asset_class,
            "cis_score": total_score,
            "grade": grade,
            "signal": signal,
            "confidence": confidence,
            "data_tier": 2,  # Railway = Tier 2
            "macro_regime": regime,
            "las": las_result["las"],
            "las_params": las_result["las_params"],
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
            "volume_24h": _vol_24h,
            "tvl": tvl,
        })

    # Sort by CIS score
    universe.sort(key=lambda x: x["cis_score"], reverse=True)

    # v4.1: Compute percentile ranks as metadata only — grades NOT overridden
    universe = compute_percentile_ranks(universe)

    # Use macro_data already fetched above (cached, no double call)
    macro_data = macro_data_early
    macro = {
        "regime": regime,
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
        "status": "error" if not universe else "success",
        "version": "4.1.0",
        "timestamp": datetime.now().isoformat(),
        "data_source": "coingecko+defillama+alternative.me",
        "data_tier": 2,
        "macro": macro,
        "universe": universe,
    }


# Test
if __name__ == "__main__":
    import json
    result = asyncio.run(calculate_cis_universe())
    print(json.dumps(result, indent=2))
