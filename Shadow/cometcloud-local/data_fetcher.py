#!/usr/bin/env python3
"""
CometCloud CIS v4.0 - Data Fetcher
====================================
Multi-asset price data fetcher with:
- CoinGecko API (Crypto) with rate limiting (30 req/min)
- Yahoo Finance (TradFi) with retry logic
- Fallback to cache on API failure
- JSON output with timestamp and data_freshness

Author: CometCloud AI
Version: 1.0.0
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import threading
from functools import wraps

import requests
import pandas as pd
import numpy as np

# Try importing yfinance, install if not available
try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call(["pip", "install", "yfinance", "-q"])
    import yfinance as yf


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

CACHE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# CoinGecko API key (Pro tier if set, free tier otherwise)
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")

# Rate limiting: Pro = 500 calls/min, Free = 25 calls/min (conservative)
COINGECKO_RATE_LIMIT = 300 if COINGECKO_API_KEY else 25
COINGECKO_RATE_PERIOD = 60  # seconds

# Retry configuration
YF_RETRY_COUNT = 3
YF_RETRY_DELAY = 2  # seconds
YF_TIMEOUT = 15  # seconds

# Cache TTL (hours)
CACHE_TTL = {
    "crypto": 1,      # 1 hour for crypto
    "tradfi": 1,      # 1 hour for stocks/bonds
    "macro": 4,       # 4 hours for macro data
}


# ═══════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cis_data_fetcher")


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PriceData:
    """Single asset price data"""
    symbol: str
    price: float
    change_24h: float
    change_7d: float
    change_30d: float
    volume_24h: float
    market_cap: float
    timestamp: str
    source: str


@dataclass
class FetchResult:
    """Result of a fetch operation"""
    success: bool
    data: Optional[Dict[str, Any]]
    error: Optional[str]
    timestamp: str
    data_freshness: str  # "live", "cache", "partial"
    sources_used: List[str]


# ═══════════════════════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Token bucket rate limiter for CoinGecko"""

    def __init__(self, rate: int, period: int):
        self.rate = rate
        self.period = period
        self.tokens = rate
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self) -> bool:
        """Acquire a token, return True if allowed"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.period))
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False

    def wait_if_needed(self):
        """Wait until a token is available"""
        while not self.acquire():
            time.sleep(0.1)


# Global rate limiter
coingecko_limiter = RateLimiter(COINGECKO_RATE_LIMIT, COINGECKO_RATE_PERIOD)


# ═══════════════════════════════════════════════════════════════════════════
# CACHE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def get_cache_path(symbol: str, data_type: str = "crypto") -> Path:
    """Get cache file path for a symbol"""
    cache_dir = CACHE_DIR / data_type
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_symbol = symbol.replace("/", "_")
    return cache_dir / f"{safe_symbol}.json"


def load_cache(symbol: str, data_type: str = "crypto", max_age_hours: int = 1) -> Optional[Dict]:
    """Load cached data if fresh enough"""
    cache_path = get_cache_path(symbol, data_type)

    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r") as f:
            cached = json.load(f)

        cached_time = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
        age_hours = (datetime.now() - cached_time).total_seconds() / 3600

        if age_hours <= max_age_hours:
            logger.info(f"Cache hit: {symbol} (age: {age_hours:.1f}h)")
            return cached
        else:
            logger.info(f"Cache expired: {symbol} (age: {age_hours:.1f}h)")
            return None

    except Exception as e:
        logger.warning(f"Cache read error for {symbol}: {e}")
        return None


def save_cache(symbol: str, data: Dict, data_type: str = "crypto"):
    """Save data to cache"""
    cache_path = get_cache_path(symbol, data_type)

    # Add timestamp
    data["timestamp"] = datetime.now().isoformat()
    data["cached_at"] = datetime.now().isoformat()

    try:
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Cached: {symbol}")
    except Exception as e:
        logger.warning(f"Cache write error for {symbol}: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# COINGECKO API
# ═══════════════════════════════════════════════════════════════════════════

COINGECKO_BASE_URL = (
    "https://pro-api.coingecko.com/api/v3" if os.environ.get("COINGECKO_API_KEY")
    else "https://api.coingecko.com/api/v3"
)

# Mapping from our symbols to CoinGecko IDs
SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "POL": "polygon-ecosystem-token",
    "UNI": "uniswap",
    "AAVE": "aave",
    "MKR": "maker",
    "ONDO": "ondo",
    "PENDLE": "pendle",
    "TIA": "celestia",
    "SUI": "sui",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "PEPE": "pepe",
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
    "FIL": "filecoin",
    "ATOM": "cosmos",
    "NEAR": "near",
    "INJ": "injective-protocol",
    "RENDER": "render-token",
    "IMX": "immutable-x",
    "STX": "stacks",
    "RUNE": "thorchain",
    "LDO": "lido-dao",
    "RETH": "rocket-pool",
}


def coingecko_request(endpoint: str, params: Dict = None) -> Optional[Dict]:
    """Make a rate-limited request to CoinGecko"""
    coingecko_limiter.wait_if_needed()

    url = f"{COINGECKO_BASE_URL}/{endpoint}"
    headers = {"Accept": "application/json"}
    if COINGECKO_API_KEY:
        headers["x-cg-pro-api-key"] = COINGECKO_API_KEY

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RateLimitError:
        logger.warning("CoinGecko rate limit hit, waiting...")
        time.sleep(5)
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"CoinGecko request failed: {e}")
        return None


def fetch_crypto_price(symbol: str) -> FetchResult:
    """
    Fetch single crypto price from CoinGecko with cache fallback
    """
    timestamp = datetime.now().isoformat()
    cg_id = SYMBOL_TO_ID.get(symbol.lower())

    if not cg_id:
        return FetchResult(
            success=False,
            data=None,
            error=f"Unknown symbol: {symbol}",
            timestamp=timestamp,
            data_freshness="error",
            sources_used=[]
        )

    # Try cache first
    cached = load_cache(symbol, "crypto", CACHE_TTL["crypto"])
    if cached:
        return FetchResult(
            success=True,
            data=cached.get("data"),
            error=None,
            timestamp=cached.get("timestamp", timestamp),
            data_freshness="cache",
            sources_used=["cache"]
        )

    # Fetch from API
    params = {
        "ids": cg_id,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_market_cap": "true",
    }

    data = coingecko_request("simple/price", params)

    if not data or cg_id not in data:
        # Try cache as fallback
        cached = load_cache(symbol, "crypto", 24)  # Allow older cache
        if cached:
            return FetchResult(
                success=True,
                data=cached.get("data"),
                error="API failed, using stale cache",
                timestamp=cached.get("timestamp", timestamp),
                data_freshness="cache",
                sources_used=["cache"]
            )

        return FetchResult(
            success=False,
            data=None,
            error=f"API failed for {symbol}",
            timestamp=timestamp,
            data_freshness="error",
            sources_used=[]
        )

    # Parse response
    item = data[cg_id]
    result_data = {
        "symbol": symbol,
        "price": item.get("usd", 0),
        "change_24h": item.get("usd_24h_change", 0),
        "volume_24h": item.get("usd_24h_vol", 0),
        "market_cap": item.get("usd_market_cap", 0),
    }

    # Save to cache
    save_cache(symbol, {"data": result_data}, "crypto")

    return FetchResult(
        success=True,
        data=result_data,
        error=None,
        timestamp=timestamp,
        data_freshness="live",
        sources_used=["coingecko"]
    )


def fetch_crypto_prices_batch(symbols: List[str]) -> FetchResult:
    """
    Fetch multiple crypto prices in a single API call
    """
    timestamp = datetime.now().isoformat()

    # Filter to known symbols
    valid_symbols = [s for s in symbols if s.upper() in SYMBOL_TO_ID]

    if not valid_symbols:
        return FetchResult(
            success=False,
            data=None,
            error="No valid symbols provided",
            timestamp=timestamp,
            data_freshness="error",
            sources_used=[]
        )

    # Try cache first for all
    all_cached = True
    results = {}

    for symbol in valid_symbols:
        cached = load_cache(symbol, "crypto", CACHE_TTL["crypto"])
        if cached:
            results[symbol] = cached.get("data")
        else:
            all_cached = False

    if all_cached and results:
        return FetchResult(
            success=True,
            data=results,
            error=None,
            timestamp=datetime.now().isoformat(),
            data_freshness="cache",
            sources_used=["cache"]
        )

    # Fetch from API
    cg_ids = [SYMBOL_TO_ID[s.upper()] for s in valid_symbols]

    params = {
        "ids": ",".join(cg_ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_market_cap": "true",
    }

    data = coingecko_request("simple/price", params)

    if not data:
        # Fallback to cache
        cached_results = {}
        for symbol in valid_symbols:
            cached = load_cache(symbol, "crypto", 24)
            if cached:
                cached_results[symbol] = cached.get("data")

        if cached_results:
            return FetchResult(
                success=True,
                data=cached_results,
                error="API failed, using stale cache",
                timestamp=timestamp,
                data_freshness="cache",
                sources_used=["cache"]
            )

        return FetchResult(
            success=False,
            data=None,
            error="API failed",
            timestamp=timestamp,
            data_freshness="error",
            sources_used=[]
        )

    # Parse response
    results = {}
    for symbol in valid_symbols:
        cg_id = SYMBOL_TO_ID[symbol.upper()]
        if cg_id in data:
            item = data[cg_id]
            results[symbol] = {
                "symbol": symbol,
                "price": item.get("usd", 0),
                "change_24h": item.get("usd_24h_change", 0),
                "volume_24h": item.get("usd_24h_vol", 0),
                "market_cap": item.get("usd_market_cap", 0),
            }
            # Save individual cache
            save_cache(symbol, {"data": results[symbol]}, "crypto")

    return FetchResult(
        success=True,
        data=results,
        error=None,
        timestamp=timestamp,
        data_freshness="live",
        sources_used=["coingecko"]
    )


# ═══════════════════════════════════════════════════════════════════════════
# YAHOO FINANCE (TRADFI)
# ═══════════════════════════════════════════════════════════════════════════

def retry_on_failure(max_retries: int = YF_RETRY_COUNT, delay: int = YF_RETRY_DELAY):
    """Decorator for retry logic"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_retries} attempts failed: {e}")
            return {"error": str(last_error)}
        return wrapper
    return decorator


@retry_on_failure()
def fetch_yf_price(symbol: str) -> Dict:
    """Fetch single asset price from Yahoo Finance with retry"""
    ticker = yf.Ticker(symbol)

    # Get info and history
    info = ticker.info
    hist = ticker.history(period="30d", auto_adjust=True)

    if hist.empty:
        raise ValueError(f"No data for {symbol}")

    # Calculate returns
    latest = hist.iloc[-1]
    price = float(latest["Close"])

    # 7d and 30d returns
    if len(hist) >= 7:
        price_7d = float(hist.iloc[-7]["Close"])
        change_7d = ((price / price_7d) - 1) * 100
    else:
        change_7d = 0

    if len(hist) >= 30:
        price_30d = float(hist.iloc[0]["Close"])
        change_30d = ((price / price_30d) - 1) * 100
    else:
        change_30d = 0

    # 24h change
    prev_close = float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else price
    change_24h = ((price / prev_close) - 1) * 100

    # Volume
    volume_24h = float(latest["Volume"]) if "Volume" in latest else 0

    # Market cap (if available)
    market_cap = info.get("marketCap", 0)

    return {
        "symbol": symbol,
        "price": price,
        "change_24h": change_24h,
        "change_7d": change_7d,
        "change_30d": change_30d,
        "volume_24h": volume_24h,
        "market_cap": market_cap,
    }


def fetch_tradfi_price(symbol: str) -> FetchResult:
    """
    Fetch single TradFi price (stocks, bonds, commodities) with cache fallback
    """
    timestamp = datetime.now().isoformat()

    # Try cache first
    cached = load_cache(symbol, "tradfi", CACHE_TTL["tradfi"])
    if cached:
        return FetchResult(
            success=True,
            data=cached.get("data"),
            error=None,
            timestamp=cached.get("timestamp", timestamp),
            data_freshness="cache",
            sources_used=["cache"]
        )

    # Fetch from Yahoo Finance
    result = fetch_yf_price(symbol)

    if "error" in result:
        # Try cache as fallback
        cached = load_cache(symbol, "tradfi", 24)
        if cached:
            return FetchResult(
                success=True,
                data=cached.get("data"),
                error=f"API failed: {result['error']}",
                timestamp=cached.get("timestamp", timestamp),
                data_freshness="cache",
                sources_used=["cache"]
            )

        return FetchResult(
            success=False,
            data=None,
            error=result["error"],
            timestamp=timestamp,
            data_freshness="error",
            sources_used=[]
        )

    # Save to cache
    save_cache(symbol, {"data": result}, "tradfi")

    return FetchResult(
        success=True,
        data=result,
        error=None,
        timestamp=timestamp,
        data_freshness="live",
        sources_used=["yahoo_finance"]
    )


def fetch_tradfi_prices_batch(symbols: List[str]) -> FetchResult:
    """Fetch multiple TradFi prices"""
    timestamp = datetime.now().isoformat()

    results = {}
    errors = []

    for symbol in symbols:
        # Check cache first
        cached = load_cache(symbol, "tradfi", CACHE_TTL["tradfi"])
        if cached:
            results[symbol] = cached.get("data")
            continue

        # Fetch from API
        result = fetch_yf_price(symbol)
        if "error" not in result:
            results[symbol] = result
            save_cache(symbol, {"data": result}, "tradfi")
        else:
            # Try stale cache
            cached = load_cache(symbol, "tradfi", 24)
            if cached:
                results[symbol] = cached.get("data")
            else:
                errors.append(f"{symbol}: {result['error']}")

    freshness = "live" if not errors else ("partial" if results else "error")
    sources = ["yahoo_finance", "cache"] if results else []

    return FetchResult(
        success=len(results) > 0,
        data=results if results else None,
        error=f"Errors: {', '.join(errors)}" if errors else None,
        timestamp=timestamp,
        data_freshness=freshness,
        sources_used=sources
    )


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED FETCHER
# ═══════════════════════════════════════════════════════════════════════════

def fetch_price(symbol: str) -> FetchResult:
    """
    Unified price fetcher - automatically detects asset type
    """
    # Check if it's a crypto symbol
    if symbol.upper() in SYMBOL_TO_ID:
        return fetch_crypto_price(symbol)

    # Otherwise treat as TradFi
    return fetch_tradfi_price(symbol)


# ═══════════════════════════════════════════════════════════════════════════
# BINANCE KLINES FOR OHLCV DATA
# ═══════════════════════════════════════════════════════════════════════════

BINANCE_BASE_URL = "https://api.binance.com"


def fetch_klines(symbol: str, interval: str = "1d", limit: int = 31) -> Optional[List[List]]:
    """
    Fetch OHLCV klines from Binance.

    Args:
        symbol: Trading pair, e.g., "BTCUSDT", "ETHUSDT"
        interval: Kline interval, e.g., "1d", "1h", "15m"
        limit: Number of klines to fetch (max 1000)

    Returns:
        List of klines, each as [openTime, open, high, low, close, volume, closeTime, ...]
        None on failure.
    """
    cache_key = f"klines_{symbol}_{interval}_{limit}"
    cache_path = get_cache_path(cache_key, "klines")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Check cache (5 min TTL for klines)
    if cache_path.exists():
        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)
            cached_time = cached.get('timestamp', 0)
            if time.time() - cached_time < 300:
                return cached.get('data')
        except Exception:
            pass

    try:
        url = f"{BINANCE_BASE_URL}/api/v3/klines"
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        klines = response.json()

        # Cache the result
        with open(cache_path, 'w') as f:
            json.dump({
                'timestamp': time.time(),
                'data': klines
            }, f)

        return klines
    except Exception as e:
        logger.warning(f"Failed to fetch klines for {symbol}: {e}")
        return None


def fetch_klines_as_prices(symbol: str, limit: int = 90) -> Optional[np.ndarray]:
    """
    Fetch klines and convert to price array for CIS engine.

    For crypto: uses Binance API
    For TradFi (SPY, QQQ, GLD, etc.): uses yfinance

    Returns:
        numpy array of closing prices, oldest to newest
        None on failure.
    """
    # Check if symbol is crypto (in SYMBOL_TO_ID) or TradFi
    is_crypto = symbol.upper() in SYMBOL_TO_ID

    if is_crypto:
        # Crypto - use Binance
        klines = fetch_klines(symbol, interval="1d", limit=limit + 1)
        if not klines:
            return None
        prices = np.array([float(k[4]) for k in klines], dtype=np.float64)
    else:
        # TradFi - use yfinance
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=f"{limit}d")
            if hist.empty or len(hist) < 30:
                return None
            # yfinance returns oldest first
            prices = hist['Close'].values.astype(np.float64)
        except Exception as e:
            logger.warning(f"yfinance fetch failed for {symbol}: {e}")
            return None

    return prices


def fetch_prices_batch(symbols: List[str]) -> FetchResult:
    """
    Fetch multiple prices, splitting by asset type
    """
    timestamp = datetime.now().isoformat()

    crypto_symbols = [s for s in symbols if s.upper() in SYMBOL_TO_ID]
    tradfi_symbols = [s for s in symbols if s.upper() not in SYMBOL_TO_ID]

    results = {}
    all_sources = []
    errors = []
    freshness = "live"

    # Fetch crypto
    if crypto_symbols:
        crypto_result = fetch_crypto_prices_batch(crypto_symbols)
        if crypto_result.success:
            results.update(crypto_result.data)
            all_sources.extend(crypto_result.sources_used)
        elif crypto_result.data:
            results.update(crypto_result.data)
            all_sources.extend(crypto_result.sources_used)
            freshness = "partial"

    # Fetch TradFi
    if tradfi_symbols:
        tradfi_result = fetch_tradfi_prices_batch(tradfi_symbols)
        if tradfi_result.success:
            results.update(tradfi_result.data)
            all_sources.extend(tradfi_result.sources_used)
        elif tradfi_result.data:
            results.update(tradfi_result.data)
            all_sources.extend(tradfi_result.sources_used)
            freshness = "partial"

    if not results:
        return FetchResult(
            success=False,
            data=None,
            error="All fetch attempts failed",
            timestamp=timestamp,
            data_freshness="error",
            sources_used=[]
        )

    return FetchResult(
        success=True,
        data=results,
        error=None,
        timestamp=timestamp,
        data_freshness=freshness,
        sources_used=list(set(all_sources))
    )


# ═══════════════════════════════════════════════════════════════════════════
# FUNDAMENTAL DATA FETCHERS (DeFiLlama + CoinGecko)
# ═══════════════════════════════════════════════════════════════════════════

# DeFiLlama TVL endpoint
DEFI_LLAMA_TVL_API = "https://api.llama.fi"


def fetch_defillama_tvl(symbol: str, coingecko_id: str = None) -> Optional[Dict]:
    """
    Fetch TVL from DeFiLlama for a protocol.
    Returns: { "tvl": float, "tvl_history": List } or None on failure
    """
    # Map symbols to DeFiLlama protocol names (must match DeFiLlama's naming)
    protocol_map = {
        # L1/L2 - not DeFi protocols, TVL not meaningful
        "ETH": None, "BTC": None, "SOL": None, "AVAX": None,
        "DOT": None, "NEAR": None, "APT": None, "SUI": None,
        "ARB": "arbitrum", "OP": "optimism", "POL": "polygon",
        # DeFi protocols - TVL available
        "LINK": "chainlink",
        "UNI": "uniswap",
        "AAVE": "aave",
        "MKR": "makerdao",  # Note: makerdao, not maker
        "CRV": "curve",
        "LDO": "lido-dao",
        "SNX": "synthetix",
        "COMP": "compound",
        "SUSHI": "sushi",
    }

    # Get DeFiLlama protocol name
    defillama_id = protocol_map.get(symbol.upper())

    # Skip if no DeFiLlama mapping (e.g., BTC, ETH, SOL)
    if not defillama_id:
        return None

    cache_path = get_cache_path(f"{symbol}_tvl", "fundamental")
    cached = load_cache(symbol, "fundamental", max_age_hours=6)
    if cached:
        return cached

    try:
        url = f"{DEFI_LLAMA_TVL_API}/tvl/{defillama_id}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            text = response.text.strip()
            # DeFiLlama returns either a JSON object {"tvl": ...} or just a number/string "0"
            try:
                data = response.json()
                if isinstance(data, dict):
                    tvl = data.get("tvl", 0)
                else:
                    tvl = float(data) if data else 0
            except (json.JSONDecodeError, ValueError):
                tvl = float(text) if text else 0
            result = {"tvl": tvl, "symbol": symbol, "defillama_id": defillama_id}
            save_cache(symbol, result, "fundamental")
            return result
    except Exception as e:
        logging.warning(f"DeFiLlama TVL fetch failed for {symbol}: {e}")

    return None


def fetch_coingecko_market_data(coingecko_id: str, symbol: str = None) -> Optional[Dict]:
    """
    Fetch market data from CoinGecko: market_cap, fdv, circulating_supply, ath, atl
    """
    cache_key = f"{coingecko_id}_market"
    cached = load_cache(cache_key, "fundamental", max_age_hours=1)
    if cached:
        return cached

    try:
        url = f"{COINGECKO_BASE_URL}/coins/{coingecko_id}"
        headers = {"Accept": "application/json"}
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
        params = {
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false",
        }
        response = requests.get(url, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            market_data = data.get("market_data", {})

            # Get TVL from CoinGecko's total_value_locked (can be nested dict like {"usd": 123, "btc": 456})
            total_value_locked = market_data.get("total_value_locked")
            if isinstance(total_value_locked, dict):
                tvl_value = total_value_locked.get("usd", 0)
            else:
                tvl_value = total_value_locked if total_value_locked else 0

            result = {
                "symbol": symbol or coingecko_id,
                "coingecko_id": coingecko_id,
                "market_cap": market_data.get("market_cap", {}).get("usd", 0),
                "fdv": market_data.get("fully_diluted_valuation", {}).get("usd", 0),
                "tvl": float(tvl_value) if tvl_value else 0.0,
                "circulating_supply": market_data.get("circulating_supply", 0),
                "total_supply": market_data.get("total_supply", 0),
                "ath": market_data.get("ath", {}).get("usd", 0),
                "atl": market_data.get("atl", {}).get("usd", 0),
                "price": market_data.get("current_price", {}).get("usd", 0),
            }

            save_cache(coingecko_id, result, "fundamental")
            return result
    except Exception as e:
        logging.warning(f"CoinGecko market fetch failed for {coingecko_id}: {e}")

    return None


# Symbol to CoinGecko ID mapping
SYMBOL_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "TON": "the-open-network",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "SUI": "sui",
    "APT": "aptos",
    "NEAR": "near",
    "INJ": "injective-protocol",
    "ARB": "arbitrum",
    "OP": "optimism",
    "POL": "polygon-ecosystem-token",
    "MNT": "mantle",
    "UNI": "uniswap",
    "AAVE": "aave",
    "MKR": "maker",
    "SNX": "havven",
    "CRV": "curve-dao-token",
    "LDO": "lido-dao",
    "COMP": "compound-governance-token",
    "SUSHI": "sushi",
    "LINK": "chainlink",
    "STX": "stacks",
    "RUNE": "thorchain",
    "FIL": "filecoin",
    "TIA": "celestia",
    "ONDO": "ondo-finance",
    "POLYX": "polymesh",
    "PEPE": "pepe",
    "WIF": "wif",
}


def fetch_fundamental_data(symbol: str) -> Dict:
    """
    Fetch all fundamental data for F Pillar scoring.
    Returns dict with tvl_mcap_ratio, revenue_fdv_ratio, etc.
    Uses DeFiLlama for DeFi protocol TVL, CoinGecko for market cap.
    """
    coingecko_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())

    result = {
        "symbol": symbol,
        "tvl_mcap_ratio": 0.0,  # Default to 0 (neutral)
        "revenue_fdv_ratio": 0.0,
        "market_cap": 0.0,
        "fdv": 0.0,
        "tvl": 0.0,
    }

    # Fetch TVL from DeFiLlama (for DeFi protocols like UNI, AAVE, MKR, etc.)
    tvl_data = fetch_defillama_tvl(symbol, coingecko_id)
    if tvl_data and tvl_data.get("tvl"):
        result["tvl"] = float(tvl_data["tvl"])

    # Fetch market data from CoinGecko (market cap, FDV)
    if coingecko_id:
        market_data = fetch_coingecko_market_data(coingecko_id, symbol)
        if market_data:
            # CoinGecko returns nested dict: {"usd": 123, "eur": 456, ...}
            mcap = market_data.get("market_cap", {})
            fdv = market_data.get("fdv", {})
            result["market_cap"] = float(mcap.get("usd", 0) or 0) if isinstance(mcap, dict) else float(mcap or 0)
            result["fdv"] = float(fdv.get("usd", 0) or 0) if isinstance(fdv, dict) else float(fdv or 0)

    # Fallback: if market_cap is 0 but FDV exists, use FDV as market cap proxy
    if result["market_cap"] == 0 and result["fdv"] > 0:
        result["market_cap"] = result["fdv"]

    # Calculate TVL/MCap ratio (only if both values are non-zero)
    if result["tvl"] > 0 and result["market_cap"] > 0:
        result["tvl_mcap_ratio"] = result["tvl"] / result["market_cap"]

    return result


def fetch_fundamentals_batch(symbols: List[str]) -> Dict[str, Dict]:
    """
    Fetch fundamental data for multiple assets.
    Returns dict mapping symbol -> fundamental data dict
    """
    results = {}
    for symbol in symbols:
        data = fetch_fundamental_data(symbol)
        if data:
            results[symbol.upper()] = data
    return results


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test with sample assets
    TEST_ASSETS = [
        # Crypto
        "BTC", "ETH", "SOL", "AVAX", "LINK", "ONDO",
        # US Equity
        "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
        # Bonds
        "TLT", "IEF", "TIP",
        # Commodities
        "GLD", "SLV",
        # FX
        "UUP", "FXE",
    ]

    logger.info(f"Fetching {len(TEST_ASSETS)} assets...")

    result = fetch_prices_batch(TEST_ASSETS)

    print("\n" + "=" * 60)
    print("FETCH RESULT")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Freshness: {result.data_freshness}")
    print(f"Sources: {result.sources_used}")
    print(f"Timestamp: {result.timestamp}")
    if result.error:
        print(f"Error: {result.error}")
    print(f"\nData count: {len(result.data) if result.data else 0}")
    print("=" * 60)

    if result.data:
        # Save to file
        output = {
            "success": result.success,
            "timestamp": result.timestamp,
            "data_freshness": result.data_freshness,
            "sources": result.sources_used,
            "data": result.data,
        }

        output_path = CACHE_DIR / "price_fetch_result.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)

        print(f"\nSaved to: {output_path}")

        # Print sample
        print("\nSample prices:")
        for symbol in ["BTC", "ETH", "SPY", "GLD"][:4]:
            if symbol in result.data:
                d = result.data[symbol]
                print(f"  {symbol}: ${d['price']:.2f} ({d['change_24h']:+.2f}% 24h)")
