"""
Looloomi AI — Unified Data Layer v1.0
Phase 1: Binance (prices) + DeFiLlama (DeFi/TVL) + Alternative.me (F&G) + Moralis (wallets)

All sources are free. No paid API keys required for core functionality.
Moralis requires a free key from moralis.io
Etherscan requires a free key from etherscan.io/myapikey
"""

import os
import json
import time
import httpx
import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

_logger = logging.getLogger(__name__)

load_dotenv()

# ── API Keys (set in Railway environment variables) ───────────────────────────
MORALIS_KEY   = os.getenv("MORALIS_API_KEY", "")
ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "")
HELIUS_KEY    = os.getenv("HELIUS_API_KEY", "")
EODHD_KEY     = os.getenv("EODHD_API_KEY", "")
CRYPTORANK_KEY = os.getenv("CRYPTORANK_API_KEY", "")

# ── Persistent HTTP clients — one per API domain ──────────────────────────────
# Reused across requests: eliminates TCP connect + TLS handshake overhead per call.
# ~50–100ms saved per cold connection, multiplied across 20 concurrent signal-feed fetches.

_redis_http_client: httpx.AsyncClient | None = None
_binance_client:    httpx.AsyncClient | None = None
_llama_client:      httpx.AsyncClient | None = None
_cg_client:         httpx.AsyncClient | None = None
_misc_client:       httpx.AsyncClient | None = None

_POOL_LIMITS = httpx.Limits(max_connections=30, max_keepalive_connections=15)

def _get_redis_client() -> httpx.AsyncClient:
    global _redis_http_client
    if _redis_http_client is None or _redis_http_client.is_closed:
        _redis_http_client = httpx.AsyncClient(timeout=5, limits=httpx.Limits(max_connections=20))
    return _redis_http_client

def _get_binance_client() -> httpx.AsyncClient:
    """Persistent client for data-api.binance.vision"""
    global _binance_client
    if _binance_client is None or _binance_client.is_closed:
        _binance_client = httpx.AsyncClient(timeout=10, limits=_POOL_LIMITS)
    return _binance_client

def _get_llama_client() -> httpx.AsyncClient:
    """Persistent client for api.llama.fi / coins.llama.fi / yields.llama.fi"""
    global _llama_client
    if _llama_client is None or _llama_client.is_closed:
        _llama_client = httpx.AsyncClient(
            timeout=20, limits=_POOL_LIMITS,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; CometCloud/1.0; +https://looloomi.ai)",
                "Accept": "application/json",
            },
        )
    return _llama_client

def _get_cg_client() -> httpx.AsyncClient:
    """Persistent client for pro-api.coingecko.com / api.coingecko.com"""
    global _cg_client
    if _cg_client is None or _cg_client.is_closed:
        _cg_client = httpx.AsyncClient(timeout=12, limits=_POOL_LIMITS)
    return _cg_client

def _get_misc_client() -> httpx.AsyncClient:
    """Persistent client for alternative.me, etherscan, and other misc APIs"""
    global _misc_client
    if _misc_client is None or _misc_client.is_closed:
        _misc_client = httpx.AsyncClient(timeout=10, limits=_POOL_LIMITS)
    return _misc_client

# ── Simple TTL Cache ──────────────────────────────────────────────────────────
_cache: dict = {}

def _cache_get(key: str, ttl: int = 30):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < ttl:
            return val
    return None

def _cache_set(key: str, val):
    _cache[key] = (val, time.time())
    return val


# ── Negative-cache TTL (2026-08-07, S-104) ───────────────────────────────────
# How long a FAILED provider call is remembered. Deliberately short: long enough
# that one universe build's worth of retries collapses to a single attempt, short
# enough that recovery is picked up within minutes without a deploy. The failure
# mode this exists for: a provider that is slow-failing, a cache that only stores
# successes, and a caller that retries the full fan-out every build.
_NEG_TTL_S = int(os.getenv("PROVIDER_NEGATIVE_CACHE_TTL_S", "600"))   # 10 min


# ── Upstash Redis L2 Cache (shared across workers, survives deploys) ──────────
_UPSTASH_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

async def _redis_get(key: str):
    """Read from Upstash. Returns None on miss or if not configured."""
    if not _UPSTASH_URL:
        return None
    try:
        client = _get_redis_client()
        r = await client.get(
            f"{_UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
        )
        if r.status_code == 200:
            raw = r.json().get("result")
            return json.loads(raw) if raw else None
    except Exception:
        pass
    return None

async def _redis_set(key: str, val, ttl: int) -> bool:
    """Write to Upstash with TTL. Fire-and-forget style (non-blocking on failure).

    ttl <= 0 means PERSIST WITHOUT EXPIRY: we must OMIT the EX param, because Redis/
    Upstash rejects `EX 0` as an invalid expire → the SET silently fails. This bug froze
    the causal_paper book (state written with ttl=0 never persisted → every daily mark
    re-inceptioned at NAV 1.0). Any long-lived state key (not a cache) relies on this.
    """
    if not _UPSTASH_URL:
        return False
    try:
        client = _get_redis_client()
        params = {"EX": ttl} if ttl and ttl > 0 else None
        r = await client.post(
            f"{_UPSTASH_URL}/set/{key}",
            content=json.dumps(val),
            headers={
                "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                "Content-Type": "application/json",
            },
            params=params,
        )
        return r.status_code == 200
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# BINANCE — Real-time prices, OHLCV, 24h stats
# No API key needed. 6000 weight/min free.
# ══════════════════════════════════════════════════════════════════════════════
BINANCE_BASE = "https://data-api.binance.vision/api/v3"

SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "BNB": "BNBUSDT", "AVAX": "AVAXUSDT", "ARB": "ARBUSDT",
    "OP":  "OPUSDT",  "MATIC": "MATICUSDT", "LINK": "LINKUSDT",
    "UNI": "UNIUSDT", "AAVE": "AAVEUSDT",  "DOT": "DOTUSDT",
}

async def get_price(symbol: str) -> Optional[dict]:
    """Get current price for a single symbol."""
    key = f"price:{symbol}"
    cached = _cache_get(key, ttl=10)
    if cached:
        return cached

    ticker = SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")
    try:
        client = _get_binance_client()
        r = await client.get(f"{BINANCE_BASE}/ticker/24hr", params={"symbol": ticker})
        r.raise_for_status()
        d = r.json()
        result = {
            "symbol": symbol.upper(),
            "price": float(d["lastPrice"]),
            "change_24h": float(d["priceChangePercent"]),
            "high_24h": float(d["highPrice"]),
            "low_24h": float(d["lowPrice"]),
            "volume_24h_usdt": float(d["quoteVolume"]),
            "source": "binance",
        }
        return _cache_set(key, result)
    except Exception as e:
        return {"symbol": symbol, "error": str(e), "source": "binance"}


async def get_prices_multi(symbols: list[str]) -> list[dict]:
    """Get prices for multiple symbols concurrently."""
    key = f"prices:{','.join(sorted(symbols))}"
    cached = _cache_get(key, ttl=15)
    if cached:
        return cached

    results = await asyncio.gather(*[get_price(s) for s in symbols])
    return _cache_set(key, [r for r in results if r])


async def get_ohlcv(symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
    """
    Get OHLCV candles from Binance.
    intervals: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
    """
    key = f"ohlcv:{symbol}:{interval}:{limit}"
    cached = _cache_get(key, ttl=60)
    if cached:
        return cached

    ticker = SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")
    try:
        client = _get_binance_client()
        r = await client.get(f"{BINANCE_BASE}/klines",
                             params={"symbol": ticker, "interval": interval, "limit": limit})
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, list):
            return [{"error": f"Binance returned non-list response: {str(raw)[:100]}"}]
        candles = []
        for c in raw:
            candles.append({
                "time":   datetime.fromtimestamp(c[0]/1000, tz=timezone.utc).isoformat(),
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            })
        return _cache_set(key, candles)
    except Exception as e:
        return [{"error": str(e)}]


async def get_orderbook_imbalance(symbol: str, limit: int = 20) -> dict:
    """
    Compute orderbook depth imbalance for a symbol.
    bid_imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    Range: -1.0 (all asks) to +1.0 (all bids).

    Data source: Binance Vision /api/v3/depth
    Cache TTL: 300s (5 minutes)
    """
    key = f"ob_imbalance:{symbol.upper()}:{limit}"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    ticker = SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")
    try:
        client = _get_binance_client()
        r = await client.get(
            f"{BINANCE_BASE}/depth",
            params={"symbol": ticker, "limit": limit},
        )
        r.raise_for_status()
        data = r.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        total   = bid_vol + ask_vol

        if total == 0:
            imbalance = 0.0
        else:
            imbalance = (bid_vol - ask_vol) / total

        result = {
            "symbol":       symbol.upper(),
            "bid_imbalance": round(imbalance, 4),
            "bid_vol":      round(bid_vol, 2),
            "ask_vol":      round(ask_vol, 2),
            "total_vol":    round(total, 2),
            "best_bid":     float(bids[0][0]) if bids else None,
            "best_ask":     float(asks[0][0]) if asks else None,
            "spread":       round(float(asks[0][0]) - float(bids[0][0]), 8) if (bids and asks) else None,
            "n_levels":     limit,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }
        return _cache_set(key, result)

    except Exception as e:
        return {"symbol": symbol.upper(), "error": str(e)}


async def get_top_gainers_losers() -> dict:
    """Get top 5 gainers and losers from Binance USDT pairs."""
    key = "gainers_losers"
    cached = _cache_get(key, ttl=60)
    if cached:
        return cached

    try:
        client = _get_binance_client()
        r = await client.get(f"{BINANCE_BASE}/ticker/24hr")
        all_tickers = [t for t in r.json() if t["symbol"].endswith("USDT")]
        sorted_t = sorted(all_tickers, key=lambda x: float(x["priceChangePercent"]))
        result = {
            "gainers": [{
                "symbol":  t["symbol"].replace("USDT", ""),
                "change":  float(t["priceChangePercent"]),
                "price":   float(t["lastPrice"]),
                "volume":  float(t["quoteVolume"]),
            } for t in sorted_t[-5:][::-1]],
            "losers": [{
                "symbol":  t["symbol"].replace("USDT", ""),
                "change":  float(t["priceChangePercent"]),
                "price":   float(t["lastPrice"]),
                "volume":  float(t["quoteVolume"]),
            } for t in sorted_t[:5]],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# DEFI LLAMA — TVL, Protocol data, Token prices, Stablecoins, Yields
# Completely free, no API key, no rate limits published.
# ══════════════════════════════════════════════════════════════════════════════
LLAMA_BASE  = "https://api.llama.fi"
LLAMA_COINS = "https://coins.llama.fi"
LLAMA_YIELDS = "https://yields.llama.fi"
LLAMA_STABLES = "https://stablecoins.llama.fi"

async def get_defi_overview() -> dict:
    """
    Global DeFi TVL, 24h change, L2 TVL breakdown, and top protocols.
    TTL: 5 min in-memory, 5 min Redis.
    """
    key = "defi_overview_v2"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    try:
        client = _get_llama_client()
        hist_r, proto_r, chains_r = await asyncio.gather(
            client.get(f"{LLAMA_BASE}/v2/historicalChainTvl"),
            client.get(f"{LLAMA_BASE}/protocols"),
            client.get(f"{LLAMA_BASE}/v2/chains"),
            return_exceptions=True,
        )

        # ── Total TVL + 24h change ────────────────────────────────────────────
        current_tvl = 0
        defi_change_24h = 0.0
        if not isinstance(hist_r, Exception) and hist_r.status_code == 200:
            hist = hist_r.json()
            if hist:
                current_tvl = hist[-1].get("tvl", 0)
                if len(hist) >= 2 and hist[-2].get("tvl", 0):
                    prev = hist[-2]["tvl"]
                    defi_change_24h = round((current_tvl - prev) / prev * 100, 2)

        # ── L2 TVL (Arbitrum, Optimism, Base, zkSync, Scroll, Starknet, Linea, Mantle) ──
        L2_CHAINS = {
            "arbitrum", "optimism", "op mainnet", "base", "zksync era", "zksync",
            "scroll", "starknet", "linea", "mantle", "blast", "mode", "manta", "taiko",
            "unichain", "polygon zkevm", "metis", "loopring", "immutablex",
        }
        l2_tvl = 0.0
        chains_data = []
        if not isinstance(chains_r, Exception) and chains_r.status_code == 200:
            chains_data = chains_r.json()
            for ch in chains_data:
                if (ch.get("name") or "").lower() in L2_CHAINS:
                    l2_tvl += ch.get("tvl") or 0

        # ── L1 TVL (major non-L2 chains by TVL) ──────────────────────────────
        L1_CHAINS = {
            "ethereum", "tron", "bsc", "solana", "avalanche", "sui",
            "near", "aptos", "cardano", "ton", "polkadot",
        }
        l1_tvl = 0.0
        for ch in chains_data:
            if (ch.get("name") or "").lower() in L1_CHAINS:
                l1_tvl += ch.get("tvl") or 0

        # ── Top protocols ─────────────────────────────────────────────────────
        protocols = []
        all_protos = []
        if not isinstance(proto_r, Exception) and proto_r.status_code == 200:
            all_protos = proto_r.json()
            protocols  = all_protos[:20]

        def _sector_tvl_change(cat_names: set) -> tuple[float, float]:
            """Return (total_tvl, avg_change_1d) for protocols matching category names."""
            matched = [p for p in all_protos if (p.get("category") or "").lower() in cat_names]
            tvl = sum(p.get("tvl") or 0 for p in matched)
            changes = [p.get("change_1d") for p in matched if p.get("change_1d") is not None]
            change = round(sum(changes) / len(changes), 2) if changes else 0.0
            return tvl, change

        def _l2_change(proto_list: list) -> float:
            """L2 24h change: average change_1d of protocols primarily on L2 chains."""
            l2_protos = [
                p for p in proto_list
                if any(c.lower() in L2_CHAINS for c in (p.get("chains") or []))
                and (p.get("tvl") or 0) > 1_000_000  # ignore micro-protocols
            ]
            changes = [p.get("change_1d") for p in l2_protos if p.get("change_1d") is not None]
            return round(sum(changes) / len(changes), 2) if changes else 0.0

        # ── Sector breakdowns ─────────────────────────────────────────────────
        rwa_tvl, rwa_change_24h    = _sector_tvl_change({"rwa"})
        staking_tvl, staking_change = _sector_tvl_change({"liquid staking", "staking", "lst"})
        oracle_tvl, oracle_change   = _sector_tvl_change({"oracle"})
        gaming_tvl, gaming_change   = _sector_tvl_change({"gaming", "gamefi", "nft marketplace"})
        dex_tvl, dex_change         = _sector_tvl_change({"dexes", "dex", "amm", "dex aggregator", "aggregator"})
        lending_tvl, lending_change = _sector_tvl_change({"lending", "cdp"})

        l2_change_24h = _l2_change(all_protos) if all_protos else 0.0

        result = {
            "total_tvl_usd":          current_tvl,
            "total_tvl":              current_tvl,   # alias
            "total_tvl_formatted":    f"${current_tvl/1e9:.1f}B",
            "defi_change_24h":        defi_change_24h,
            # Sector TVL + 24h change
            "l1_tvl":                 l1_tvl,
            "l1_change_24h":          0.0,           # chain-level not available in /v2/chains
            "l2_tvl":                 l2_tvl,
            "l2_change_24h":          l2_change_24h,
            "rwa_tvl":                rwa_tvl,
            "rwa_change_24h":         rwa_change_24h,
            "staking_tvl":            staking_tvl,
            "staking_change_24h":     staking_change,
            "oracle_tvl":             oracle_tvl,
            "oracle_change_24h":      oracle_change,
            "gaming_tvl":             gaming_tvl,
            "gaming_change_24h":      gaming_change,
            "dex_tvl":                dex_tvl,
            "dex_change_24h":         dex_change,
            "lending_tvl":            lending_tvl,
            "lending_change_24h":     lending_change,
            "top_protocols": [{
                "name":      p.get("name"),
                "tvl":       p.get("tvl", 0),
                "change_1d": p.get("change_1d", 0),
                "change_7d": p.get("change_7d", 0),
                "category":  p.get("category"),
                "chains":    p.get("chains", [])[:3],
            } for p in protocols if p.get("tvl", 0) > 0],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _redis_set(key, result, ttl=300)
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_defi_protocols_curated() -> list:
    """
    Returns real TVL + 7d change for CometCloud's curated DeFi protocol library.
    Fetches DeFiLlama /protocols (full list) and filters to our approved set.
    TTL: 30 min Redis (DeFiLlama updates ~hourly, no need to hammer it).
    """
    key = "defi_protocols_curated_v2"
    cached = _cache_get(key, ttl=1800)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    # Curated protocol names (DeFiLlama name field — case-insensitive match)
    CURATED = {
        # Lending
        "aave v3", "aave", "morpho", "spark", "compound v3", "compound",
        "venus", "kamino lending", "marginfi",
        # DEX
        "uniswap", "curve dex", "curve", "balancer", "aerodrome",
        "raydium", "orca", "pancakeswap",
        # Liquid Staking
        "lido", "rocket pool", "frax ether", "mantle staking",
        "stader", "binance staking", "jito",
        # CDP / Stablecoin
        "sky", "makerdao", "liquity", "abracadabra",
        # Yield
        "convex finance", "yearn", "beefy", "pendle",
        # RWA
        "ondo finance", "maple finance", "goldfinch",
        # Restaking
        "eigenlayer", "karak network", "symbiotic",
        # Bridge
        "across protocol", "stargate", "hop protocol",
    }

    try:
        client = _get_llama_client()
        r = await client.get(f"{LLAMA_BASE}/protocols")
        r.raise_for_status()
        all_protos = r.json()

        result = []
        for p in all_protos:
            name_lower = (p.get("name") or "").lower()
            if name_lower in CURATED:
                tvl = p.get("tvl") or 0
                result.append({
                    "name":          p.get("name"),
                    "slug":          p.get("slug") or p.get("id") or "",
                    "category":      p.get("category") or "DeFi",
                    "chains":        (p.get("chains") or [])[:4],
                    "tvl":           tvl,
                    "change_1d":     round(p.get("change_1d") or 0, 2),
                    "change_7d":     round(p.get("change_7d") or 0, 2),
                    "logo":          p.get("logo") or "",
                    "url":           p.get("url") or "",
                })
        # Sort by TVL descending
        result.sort(key=lambda x: x["tvl"], reverse=True)
        await _redis_set(key, result, ttl=1800)
        return _cache_set(key, result)
    except Exception as e:
        _logger.warning(f"[DEFI_PROTOCOLS] Error: {e}")
        return []


async def get_protocol(protocol_slug: str) -> dict:
    """
    Get detailed data for a specific protocol.
    Examples: 'uniswap', 'aave', 'compound', 'lido', 'makerdao'
    """
    key = f"protocol:{protocol_slug}"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    try:
        client = _get_llama_client()
        r = await client.get(f"{LLAMA_BASE}/protocol/{protocol_slug}")
        d = r.json()
        result = {
            "name":        d.get("name"),
            "tvl":         d.get("currentChainTvls", {}),
            "total_tvl":   d.get("tvl", [{}])[-1].get("totalLiquidityUSD", 0),
            "description": d.get("description"),
            "category":    d.get("category"),
            "chains":      d.get("chains", []),
            "raises":      d.get("raises", []),  # funding rounds (free!)
            "audits":      len(d.get("audits", [])),
            "url":         d.get("url"),
            "twitter":     d.get("twitter"),
        }
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_token_price_llama(coin_id: str) -> Optional[float]:
    """
    Get token price from DeFiLlama coins API.
    coin_id format: 'coingecko:bitcoin' or 'ethereum:0x...' (contract address)
    """
    try:
        client = _get_llama_client()
        r = await client.get(f"{LLAMA_COINS}/prices/current/{coin_id}")
        coins = r.json().get("coins", {})
        if coins:
            return list(coins.values())[0].get("price")
    except Exception:
        pass
    return None


async def get_stablecoin_overview() -> dict:
    """Top stablecoins by market cap with chain breakdown."""
    key = "stablecoins"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    try:
        client = _get_llama_client()
        r = await client.get(f"{LLAMA_STABLES}/stablecoins?includePrices=true")
        stables = r.json().get("peggedAssets", [])[:10]
        result = {
            "stablecoins": [{
                "name":        s.get("name"),
                "symbol":      s.get("symbol"),
                "peg_type":    s.get("pegType"),
                "circulating": s.get("circulating", {}).get("peggedUSD", 0),
                "chains":      list(s.get("chainCirculating", {}).keys())[:5],
            } for s in stables],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _redis_set(key, result, ttl=600)
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_top_yields(min_tvl: float = 1_000_000, limit: int = 20) -> list[dict]:
    """Top yield farming opportunities filtered by TVL. TTL: 10 min Redis."""
    key = f"yields:{min_tvl}:{limit}"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    try:
        client = _get_llama_client()
        r = await client.get(f"{LLAMA_YIELDS}/pools")
        pools = r.json().get("data", [])
        filtered = [p for p in pools
                    if (p.get("tvlUsd", 0) >= min_tvl and
                        p.get("apy", 0) > 0 and
                        p.get("apy", 0) < 1000)]  # filter out obviously broken pools
        filtered.sort(key=lambda x: x.get("apy", 0), reverse=True)
        result = [{
            "project":    p.get("project"),
            "chain":      p.get("chain"),
            "symbol":     p.get("symbol"),
            "tvl_usd":    p.get("tvlUsd", 0),
            "apy":        round(p.get("apy", 0), 2),
            "apy_base":   round(p.get("apyBase", 0) or 0, 2),
            "apy_reward": round(p.get("apyReward", 0) or 0, 2),
            "pool_id":    p.get("pool"),
        } for p in filtered[:limit]]
        await _redis_set(key, result, ttl=600)
        return _cache_set(key, result)
    except Exception as e:
        return [{"error": str(e)}]


async def get_dex_volumes() -> dict:
    """Top DEX volumes from DeFiLlama. TTL: 5 min Redis."""
    key = "dex_volumes"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    try:
        client = _get_llama_client()
        r = await client.get(f"{LLAMA_BASE}/overview/dexs?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyVolume")
        d = r.json()
        protocols = d.get("protocols", [])[:10]
        result = {
            "total_24h": d.get("total24h", 0),
            "total_7d":  d.get("total7d", 0),
            "top_dexs": [{
                "name":        p.get("name"),
                "volume_24h":  p.get("total24h", 0),
                "volume_7d":   p.get("total7d", 0),
                "chains":      p.get("chains", [])[:3],
                "change_1d":   p.get("change_1d", 0),
            } for p in protocols],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _redis_set(key, result, ttl=300)
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_protocol_revenues() -> dict:
    """Top protocol fees and revenues (protocol earnings). TTL: 10 min Redis."""
    key = "revenues"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    try:
        client = _get_llama_client()
        r = await client.get(f"{LLAMA_BASE}/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyFees")
        d = r.json()
        protocols = d.get("protocols", [])[:10]
        result = {
            "total_fees_24h": d.get("total24h", 0),
            "top_protocols": [{
                "name":      p.get("name"),
                "fees_24h":  p.get("total24h", 0),
                "fees_7d":   p.get("total7d", 0),
                "category":  p.get("category"),
            } for p in protocols],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _redis_set(key, result, ttl=600)
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_vc_raises(limit: int = 100) -> list[dict]:
    """
    VC funding rounds from multiple free sources.
    Priority: 1) DeFiLlama /raises (if available) 2) RSS headline extraction 3) CoinGecko recently added
    Returns up to `limit` rounds sorted by date desc, last 180 days.
    Amount is returned in USD.
    TTL: 1h in-memory + 1h Redis.
    """
    import re as _re
    import xml.etree.ElementTree as _ET

    key = f"vc_raises_v5:{limit}"
    cached = _cache_get(key, ttl=3600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    raises: list[dict] = []
    cutoff = datetime.now(timezone.utc).timestamp() - 180 * 86400

    # ── Source 0: CryptoRank v2 (primary — DeFiLlama /raises paywalled 2026-06) ─
    # Structured funding-round API. Gated on CRYPTORANK_API_KEY; no-ops cleanly
    # (returns []) when the key is absent so RSS still carries the panel.
    async def _fetch_cryptorank() -> list:
        if not CRYPTORANK_KEY:
            return []
        try:
            client = _get_misc_client()
            resp = await client.get(
                # Correct v2 path. NOTE: gated to paid tiers — free tier returns 403
                # ("not available in your tariff plan"); handled below → RSS fallback.
                # Activates automatically once the CryptoRank plan is upgraded.
                "https://api.cryptorank.io/v2/currencies/funding-rounds",
                headers={"X-Api-Key": CRYPTORANK_KEY},
                params={"limit": min(limit, 100), "sortBy": "announcementDate", "sortDirection": "DESC"},
                timeout=15,
            )
            if resp.status_code != 200:
                _logger.info(f"[VC_RAISES] CryptoRank HTTP {resp.status_code} "
                             f"({'tariff-gated — upgrade plan' if resp.status_code == 403 else 'unavailable'})")
                return []
            payload = resp.json()
            rows = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                return []
            items = []
            for r in rows:
                # Project name — CryptoRank nests it under a few possible keys
                name = (
                    r.get("name")
                    or (r.get("project") or {}).get("name")
                    or (r.get("keysData") or {}).get("name")
                    or (r.get("coin") or {}).get("name")
                    or "Unknown"
                )
                # Date — ISO string → epoch
                date_ts = 0
                adate = r.get("announcementDate") or r.get("date")
                if adate:
                    try:
                        date_ts = int(datetime.fromisoformat(str(adate).replace("Z", "+00:00")).timestamp())
                    except Exception:
                        date_ts = 0
                if date_ts and date_ts < cutoff:
                    continue
                amount_usd = _safe_float(r.get("raise")) or 0
                funds = r.get("funds") or []
                lead = [f.get("name") for f in funds if f.get("isLead") and f.get("name")]
                allf = [f.get("name") for f in funds if f.get("name")]
                cat = r.get("category") or (r.get("project") or {}).get("category") or "Crypto"
                items.append({
                    "name":             name,
                    "amount":           int(amount_usd),
                    "amount_disclosed": amount_usd > 0,
                    "round":            r.get("stage") or r.get("type") or "—",
                    "date":             date_ts,
                    "category":         cat,
                    "categoryGroup":    cat,
                    "sector":           cat,
                    "chains":           [],
                    "leadInvestors":    lead,
                    "investors":        allf,
                    "valuation":        _safe_float(r.get("valuation")),
                    "description":      "",
                    "link":             r.get("announcementLink") or "",
                    "source":           "cryptorank",
                })
            return items
        except Exception as e:
            _logger.warning(f"[VC_RAISES] CryptoRank error: {e}")
            return []

    # ── Source 1: DeFiLlama /raises (may be paywalled — best-effort) ─────────
    async def _fetch_defillama() -> list:
        try:
            client = _get_llama_client()
            resp = await client.get("https://api.llama.fi/raises", timeout=15)
            if resp.status_code != 200:
                _logger.info(f"[VC_RAISES] DeFiLlama /raises HTTP {resp.status_code} (likely paywalled)")
                return []
            data = resp.json()
            if isinstance(data, str) and "upgrade" in data.lower():
                _logger.info("[VC_RAISES] DeFiLlama /raises is paywalled")
                return []
            raw = data.get("raises") or data.get("data") or []
            if not raw:
                return []

            items = []
            for r in raw:
                raw_amount = r.get("amount")
                date_ts    = r.get("date") or 0
                if date_ts < cutoff:
                    continue
                lead  = r.get("leadInvestors") or []
                other = r.get("otherInvestors") or []
                items.append({
                    "name":          r.get("name") or r.get("project") or "Unknown",
                    "amount":        int((raw_amount or 0) * 1_000_000),
                    "amount_disclosed": raw_amount is not None and raw_amount > 0,
                    "round":         r.get("round") or r.get("roundType") or "—",
                    "date":          date_ts,
                    "category":      r.get("category") or "DeFi",
                    "categoryGroup": r.get("category") or "DeFi",
                    "sector":        r.get("sector") or r.get("category") or "DeFi",
                    "chains":        (r.get("chains") or [])[:3],
                    "leadInvestors": lead,
                    "investors":     lead + other,
                    "description":   (r.get("description") or "")[:200],
                    "source":        "defillama",
                })
            return items
        except Exception as e:
            _logger.warning(f"[VC_RAISES] DeFiLlama error: {e}")
            return []

    # ── Source 2: RSS feeds — extract structured funding data from headlines ──
    _FUNDING_RSS = [
        {"url": "https://www.theblock.co/rss.xml",      "source": "The Block"},
        {"url": "https://blockworks.co/feed",            "source": "Blockworks"},
        {"url": "https://cryptoslate.com/feed/",         "source": "CryptoSlate"},
        {"url": "https://bitcoinmagazine.com/feed",      "source": "Bitcoin Magazine"},
        {"url": "https://cointelegraph.com/rss",         "source": "CoinTelegraph"},
        {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "source": "CoinDesk"},
        {"url": "https://thedefiant.io/feed",            "source": "The Defiant"},
        {"url": "https://www.dlnews.com/arc/outboundfeeds/rss/", "source": "DL News"},
    ]

    # Regex patterns for extracting funding data from headlines
    _AMOUNT_PAT = _re.compile(
        r"\$\s*([\d,.]+)\s*(million|mln|m(?:il)?|billion|bln|b)\b",
        _re.IGNORECASE,
    )
    _ROUND_PAT = _re.compile(
        r"(seed|pre-seed|series\s*[a-f]|strategic|private|extension|bridge|token\s*sale|ido|ieo)",
        _re.IGNORECASE,
    )
    _RAISE_PAT = _re.compile(
        r"(raise[sd]?|secures?|closes?|bags?|lands?|nabs?|snags?|completes?|announces?)\s+\$",
        _re.IGNORECASE,
    )
    _INVESTOR_PAT = _re.compile(
        r"(?:led\s+by|from|backed\s+by|with\s+participation\s+from)\s+([A-Z][\w\s&',]+?)(?:\s+and\s+|,|\.|$)",
        _re.IGNORECASE,
    )

    def _parse_amount(text: str) -> int:
        """Extract USD amount from text. Returns 0 if not found."""
        m = _AMOUNT_PAT.search(text)
        if not m:
            return 0
        num = float(m.group(1).replace(",", ""))
        unit = m.group(2).lower()
        if unit.startswith("b"):
            return int(num * 1_000_000_000)
        return int(num * 1_000_000)

    # Generic aggregate terms that are NOT real company names — block these
    _GENERIC_NAME_BLOCKLIST = {
        "crypto companies", "crypto firms", "crypto startups", "crypto projects",
        "web3 companies", "web3 firms", "web3 startups", "web3 projects",
        "blockchain companies", "blockchain firms", "blockchain startups",
        "defi projects", "defi protocols", "defi companies",
        "nft projects", "nft companies", "metaverse projects",
        "bitcoin companies", "ethereum companies", "solana projects",
        "tech companies", "tech startups", "fintech companies",
        "ai companies", "ai startups", "artificial intelligence companies",
        "gaming companies", "gaming startups",
        "investment firm", "venture capital", "crypto funds",
        "report", "analysis", "weekly", "monthly", "quarterly", "annual",
        "the report", "a report", "new report",
    }

    def _parse_project_name(title: str) -> str:
        """Extract project name from a funding headline."""
        # Common patterns: "ProjectName raises $X", "ProjectName secures $X"
        for pat in [
            r"^([A-Z][\w.]+(?:\s+\w+){0,3}?)\s+(?:raise|secure|close|bag|land|nab|snag|complete|announce)",
            r"^([A-Z][\w.]+(?:\s+\w+){0,2}?)\s+(?:gets?|nets?|receives?)",
        ]:
            m = _re.match(pat, title, _re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                # Clean up trailing conjunctions/prepositions
                name = _re.sub(r"\s+(has|have|to|in|for|the)\s*$", "", name, flags=_re.IGNORECASE)
                # Reject generic aggregate names (industry-level headlines, not company rounds)
                if name.lower() in _GENERIC_NAME_BLOCKLIST:
                    return ""
                if len(name) > 2 and len(name) < 60:
                    return name
        return ""

    # Loose pre-filter: only items that plausibly mention funding get sent to the LLM.
    _FUND_HINT = _re.compile(
        r"\b(raise[sd]?|funding|round|seed|series\s*[a-f]|million|billion|backed|"
        r"investment|secures?|closes?|strategic|venture)\b", _re.IGNORECASE)

    async def _rss_llm_extract() -> list | None:
        """LLM extraction over raw RSS items. None ⇒ unavailable → regex fallback."""
        try:
            from src.data.market.llm_extract import llm_extract_rounds, llm_configured
        except ImportError:
            from data.market.llm_extract import llm_extract_rounds, llm_configured
        if not llm_configured():
            return None
        candidates = []
        cid = 0
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "CometCloud/1.0 vc-tracker"}, timeout=8,
            ) as client:
                tasks = [client.get(f["url"], follow_redirects=True) for f in _FUNDING_RSS]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for feed_info, result in zip(_FUNDING_RSS, results):
                    if isinstance(result, Exception) or result.status_code != 200:
                        continue
                    try:
                        root = _ET.fromstring(result.text)
                    except Exception:
                        continue
                    channel = root.find("channel")
                    if channel is None:
                        continue
                    for item in channel.findall("item")[:25]:
                        title = (item.findtext("title") or "").strip()
                        desc = _re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
                        desc = _re.sub(r"\s+", " ", desc).strip()[:250]
                        if not _FUND_HINT.search(title + " " + desc):
                            continue
                        date_ts = 0
                        pub_date = (item.findtext("pubDate") or "").strip()
                        if pub_date:
                            try:
                                from email.utils import parsedate_to_datetime
                                date_ts = int(parsedate_to_datetime(pub_date).timestamp())
                            except Exception:
                                pass
                        if date_ts and date_ts < cutoff:
                            continue
                        cid += 1
                        candidates.append({"id": cid, "title": title, "summary": desc,
                                           "source": feed_info["source"], "date_ts": date_ts})
        except Exception as e:
            _logger.warning(f"[VC_RAISES] RSS raw fetch error: {e}")
            return None
        if not candidates:
            return []
        return await llm_extract_rounds(candidates[:60], cutoff)

    async def _fetch_rss_raises() -> list:
        # Prefer LLM extraction (robust to phrasing); fall back to regex below.
        llm_rows = await _rss_llm_extract()
        if llm_rows is not None:
            return llm_rows

        items = []
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "CometCloud/1.0 vc-tracker"},
                timeout=8,
            ) as client:
                tasks = [client.get(f["url"], follow_redirects=True) for f in _FUNDING_RSS]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for feed_info, result in zip(_FUNDING_RSS, results):
                    if isinstance(result, Exception) or result.status_code != 200:
                        continue
                    try:
                        root = _ET.fromstring(result.text)
                    except Exception:
                        continue

                    channel = root.find("channel")
                    if channel is None:
                        continue

                    for item in channel.findall("item")[:20]:
                        title = (item.findtext("title") or "").strip()
                        desc  = (item.findtext("description") or "").strip()
                        # Strip HTML from description
                        desc = _re.sub(r"<[^>]+>", " ", desc)
                        desc = _re.sub(r"\s+", " ", desc).strip()[:250]

                        # Must look like a funding headline
                        if not _RAISE_PAT.search(title + " " + desc):
                            continue

                        amount = _parse_amount(title + " " + desc)
                        project = _parse_project_name(title)
                        if not project:
                            continue

                        # Parse round type
                        round_m = _ROUND_PAT.search(title + " " + desc)
                        round_type = round_m.group(1).strip().title() if round_m else "Funding"

                        # Parse investors
                        investors = []
                        inv_m = _INVESTOR_PAT.search(title + " " + desc)
                        if inv_m:
                            inv_str = inv_m.group(1).strip()
                            investors = [v.strip() for v in _re.split(r",\s*|\s+and\s+", inv_str) if v.strip()][:5]

                        # Parse date
                        pub_date = (item.findtext("pubDate") or "").strip()
                        date_ts = 0
                        if pub_date:
                            try:
                                from email.utils import parsedate_to_datetime
                                date_ts = int(parsedate_to_datetime(pub_date).timestamp())
                            except Exception:
                                pass

                        if date_ts and date_ts < cutoff:
                            continue

                        # Classify category
                        text_lower = (title + " " + desc).lower()
                        if any(k in text_lower for k in ["rwa", "real world", "tokeniz"]):
                            category = "RWA"
                        elif any(k in text_lower for k in ["defi", "dex", "lending", "yield", "amm"]):
                            category = "DeFi"
                        elif any(k in text_lower for k in ["l1", "l2", "layer", "chain", "rollup"]):
                            category = "Infrastructure"
                        elif any(k in text_lower for k in ["ai", "machine learning", "llm"]):
                            category = "AI"
                        elif any(k in text_lower for k in ["game", "gaming", "metaverse", "nft"]):
                            category = "Gaming"
                        elif any(k in text_lower for k in ["bitcoin", "btc", "mining"]):
                            category = "Bitcoin"
                        else:
                            category = "DeFi"

                        items.append({
                            "name":          project,
                            "amount":        amount,
                            "amount_disclosed": amount > 0,
                            "round":         round_type,
                            "date":          date_ts or int(datetime.now(timezone.utc).timestamp()),
                            "category":      category,
                            "categoryGroup": category,
                            "sector":        category,
                            "chains":        [],
                            "leadInvestors": investors,
                            "investors":     investors,
                            "description":   desc[:200] if desc else title[:200],
                            "source":        feed_info["source"],
                        })
        except Exception as e:
            _logger.warning(f"[VC_RAISES] RSS extraction error: {e}")
        return items

    # ── Source 3: CoinGecko recently added coins (proxy for funded projects) ──
    async def _fetch_cg_recent() -> list:
        if not CG_API_KEY:
            return []
        items = []
        try:
            client = _get_cg_client()
            resp = await client.get(
                f"{CG_PRO_BASE}/coins/markets",
                headers=_cg_headers(),
                params={
                    "vs_currency": "usd",
                    "order": "id_asc",
                    "per_page": 30,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "7d",
                    "category": "recently-added",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            coins = resp.json()
            for coin in coins:
                mcap = coin.get("market_cap") or 0
                if mcap < 100_000:
                    continue  # skip dust
                items.append({
                    "name":          coin.get("name") or "Unknown",
                    "amount":        0,
                    "amount_disclosed": False,
                    "round":         "Token Launch",
                    "date":          int(datetime.now(timezone.utc).timestamp()),
                    "category":      "DeFi",
                    "categoryGroup": "DeFi",
                    "sector":        "DeFi",
                    "chains":        [],
                    "leadInvestors": [],
                    "investors":     [],
                    "description":   f"Recently listed · Market cap ${mcap / 1e6:.1f}M" if mcap > 0 else "Recently listed on CoinGecko",
                    "source":        "coingecko",
                })
        except Exception as e:
            _logger.warning(f"[VC_RAISES] CoinGecko recent error: {e}")
        return items

    # ── Fetch all sources concurrently ───────────────────────────────────────
    try:
        cr_data, llama_data, rss_data, cg_data = await asyncio.gather(
            _fetch_cryptorank(),
            _fetch_defillama(),
            _fetch_rss_raises(),
            _fetch_cg_recent(),
            return_exceptions=True,
        )
        # Merge — priority: CryptoRank > DeFiLlama > RSS > CoinGecko
        for src in [cr_data, llama_data, rss_data, cg_data]:
            if isinstance(src, list):
                raises.extend(src)

        # Deduplicate by normalised project name
        seen: set = set()
        deduped = []
        for r in raises:
            norm = (r["name"] or "").lower().strip().replace(" ", "")[:30]
            if norm and norm not in seen:
                seen.add(norm)
                deduped.append(r)

        deduped.sort(key=lambda x: x.get("date", 0) or 0, reverse=True)
        result = deduped[:limit]

        sources = set()
        for r in result:
            sources.add(r.get("source", ""))
        _logger.info(f"[VC_RAISES] {len(result)} raises from {sources}")

        if result:
            await _redis_set(key, result, ttl=3600)
            await _redis_set(f"{key}:stale", result, ttl=86400)
            return _cache_set(key, result)

        stale = await _redis_get(f"{key}:stale")
        return stale or []
    except Exception as e:
        _logger.warning(f"[VC_RAISES] Error: {e}")
        stale = await _redis_get(f"{key}:stale")
        return stale or []


async def get_token_unlocks(days_ahead: int = 30) -> list[dict]:
    """
    Upcoming token unlocks from DeFiLlama /emissions endpoint.
    Note: DeFiLlama paywalled /emissions as of ~May 2026.
    Returns [] gracefully — never returns mock/fabricated data.
    TTL: 2h in-memory + 2h Redis.
    """
    key = f"token_unlocks_v1:{days_ahead}"
    cached = _cache_get(key, ttl=7200)
    if cached is not None:
        return cached
    r_cached = await _redis_get(key)
    if r_cached is not None:
        return _cache_set(key, r_cached)

    try:
        client = _get_llama_client()
        resp = await client.get("https://api.llama.fi/emissions", timeout=15)
        if resp.status_code != 200:
            _logger.info(f"[TOKEN_UNLOCKS] DeFiLlama /emissions HTTP {resp.status_code} (likely paywalled)")
            return _cache_set(key, [])

        # Check for paywall response
        text = resp.text.strip()
        if "upgrade" in text.lower() or "paid" in text.lower():
            _logger.info("[TOKEN_UNLOCKS] DeFiLlama /emissions is paywalled")
            return _cache_set(key, [])

        data = resp.json()
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff_ts = now_ts + days_ahead * 86400

        unlocks: list[dict] = []
        protocols = data if isinstance(data, list) else data.get("protocols", [])
        for proto in protocols:
            name = proto.get("name") or proto.get("protocol") or "Unknown"
            events = proto.get("events") or proto.get("upcomingEvent") or []
            if not isinstance(events, list):
                events = [events] if events else []
            for ev in events:
                ts = ev.get("timestamp") or ev.get("ts") or 0
                if not ts or ts < now_ts or ts > cutoff_ts:
                    continue
                amount_usd = ev.get("value") or ev.get("amount_usd") or 0
                days_until = int((ts - now_ts) / 86400)
                unlocks.append({
                    "protocol":   name,
                    "date":       datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "timestamp":  int(ts),
                    "amount_usd": amount_usd,
                    "type":       ev.get("type") or ev.get("category") or "unlock",
                    "days_until": days_until,
                })

        unlocks.sort(key=lambda x: x["timestamp"])
        result = unlocks[:50]
        await _redis_set(key, result, ttl=7200)
        return _cache_set(key, result)
    except Exception as e:
        _logger.warning(f"[TOKEN_UNLOCKS] Error: {e}")
        return _cache_set(key, [])


# ══════════════════════════════════════════════════════════════════════════════
# ALTERNATIVE.ME — Fear & Greed Index (free, no key, full history)
# ══════════════════════════════════════════════════════════════════════════════

async def get_fear_greed(limit: int = 30) -> dict:
    """Crypto Fear & Greed Index. limit=1 for current, limit=30 for history. TTL: 1 hr Redis."""
    key = f"fng:{limit}"
    cached = _cache_get(key, ttl=3600)  # updates daily
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    try:
        client = _get_misc_client()
        r = await client.get(f"https://api.alternative.me/fng/?limit={limit}")
        data = r.json().get("data", [])
        result = {
            "current": {
                "value":     int(data[0]["value"]),
                "label":     data[0]["value_classification"],
                "timestamp": data[0]["timestamp"],
            } if data else {},
            "history": [{
                "value":     int(d["value"]),
                "label":     d["value_classification"],
                "timestamp": d["timestamp"],
                "date":      datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
            } for d in data],
            "source": "alternative.me",
        }
        await _redis_set(key, result, ttl=3600)
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# COINGECKO PRO — Market global, trending, GeckoTerminal on-chain, derivatives
# Requires COINGECKO_API_KEY in Railway env vars.
# Pro base: https://pro-api.coingecko.com/api/v3
# GeckoTerminal on-chain data accessible via /onchain/* (included in Pro plan).
# Rate limit: up to 500 calls/min on Pro tier.
# ══════════════════════════════════════════════════════════════════════════════

CG_PRO_BASE = "https://pro-api.coingecko.com/api/v3"
CG_API_KEY  = os.getenv("COINGECKO_API_KEY", "")

def _cg_headers() -> dict:
    """Attach Pro API key header. Falls back gracefully if key absent."""
    return {"x-cg-pro-api-key": CG_API_KEY} if CG_API_KEY else {}


async def get_cg_global() -> dict:
    """
    CoinGecko global market data.
    Returns: btc_dominance, btc_dom_change_24h (approx), total_market_cap,
             mcap_change_pct_24h, defi_market_cap, defi_to_total_ratio,
             volume_24h, active_cryptocurrencies.
    TTL: 3 min.
    """
    key = "cg_global"
    cached = _cache_get(key, ttl=180)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)
    if not CG_API_KEY:
        return {"error": "COINGECKO_API_KEY not set"}
    try:
        client = _get_cg_client()
        r = await client.get(f"{CG_PRO_BASE}/global", headers=_cg_headers())
        r.raise_for_status()
        d = r.json().get("data", {})
        btc_dom  = d.get("market_cap_percentage", {}).get("btc", 0)
        eth_dom  = d.get("market_cap_percentage", {}).get("eth", 0)
        mcaps    = d.get("total_market_cap", {})
        total_usd = mcaps.get("usd", 0)
        defi_mcap = d.get("total_market_cap_defi_usd") or d.get("defi_market_cap", 0) or 0
        result = {
            "btc_dominance":       round(btc_dom, 2),
            "eth_dominance":       round(eth_dom, 2),
            "total_market_cap_usd": total_usd,
            "mcap_change_pct_24h": round(d.get("market_cap_change_percentage_24h_usd", 0), 2),
            "volume_24h_usd":      d.get("total_volume", {}).get("usd", 0),
            "defi_market_cap":     defi_mcap,
            "defi_to_total_ratio": round(defi_mcap / total_usd * 100, 2) if total_usd else 0,
            "active_cryptocurrencies": d.get("active_cryptocurrencies", 0),
            "markets":             d.get("markets", 0),
        }
        await _redis_set(key, result, ttl=180)
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_cg_trending() -> list:
    """
    CoinGecko trending coins (top 7 in 24h by search volume).
    Each entry: symbol, name, market_cap_rank, price_change_24h, score.
    TTL: 5 min.
    """
    key = "cg_trending"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)
    if not CG_API_KEY:
        return []
    try:
        client = _get_cg_client()
        r = await client.get(f"{CG_PRO_BASE}/search/trending", headers=_cg_headers())
        r.raise_for_status()
        coins = r.json().get("coins", [])
        result = []
        for c in coins[:7]:
            item  = c.get("item", {})
            pdata = item.get("data", {})
            result.append({
                "symbol":         item.get("symbol", "").upper(),
                "name":           item.get("name", ""),
                "market_cap_rank": item.get("market_cap_rank"),
                "score":          item.get("score", 0),          # 0=highest
                "price_change_24h": pdata.get("price_change_percentage_24h", {}).get("usd", 0),
                "sparkline":      pdata.get("sparkline"),
            })
        await _redis_set(key, result, ttl=300)
        return _cache_set(key, result)
    except Exception as e:
        return []


async def get_trending_map() -> dict[str, int]:
    """
    Returns {SYMBOL: trending_rank} for top-15 CoinGecko trending coins.
    Rank 1 = highest search volume. Used by cis_provider S-pillar scoring.
    Cached 5 min.
    """
    key = "cg_trending_map"
    r_cached = await _redis_get(key)
    if r_cached and isinstance(r_cached, dict):
        return r_cached
    # Extend to top-15 for wider coverage
    if not CG_API_KEY:
        return {}
    try:
        client = _get_cg_client()
        r = await client.get(f"{CG_PRO_BASE}/search/trending", headers=_cg_headers())
        r.raise_for_status()
        coins = r.json().get("coins", [])
        trend_map = {}
        for i, c in enumerate(coins[:15]):
            sym = c.get("item", {}).get("symbol", "").upper()
            if sym:
                trend_map[sym] = i + 1   # rank 1-based
        await _redis_set(key, trend_map, ttl=300)
        return trend_map
    except Exception:
        return {}


async def get_gecko_terminal_pools(network: str = "eth", limit: int = 10) -> list:
    """
    GeckoTerminal trending DEX pools for a network (via CoinGecko Pro /onchain).
    Returns top pools with price_change_24h, volume_24h_usd, reserve_in_usd (TVL),
    base_token_symbol, pool_address.
    Supported networks: eth, solana, bsc, arbitrum, base, polygon_pos, optimism.
    TTL: 2 min.
    """
    key = f"gt_pools:{network}"
    cached = _cache_get(key, ttl=120)
    if cached:
        return cached
    if not CG_API_KEY:
        return []
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)
    try:
        client = _get_cg_client()
        url = f"{CG_PRO_BASE}/onchain/networks/{network}/trending_pools"
        r   = await client.get(url, headers=_cg_headers(),
                               params={"include": "base_token,quote_token", "page": 1})
        r.raise_for_status()
        pools = r.json().get("data", [])[:limit]
        result = []
        for p in pools:
            attrs = p.get("attributes", {})
            base  = (p.get("relationships", {})
                       .get("base_token", {}).get("data", {}).get("id", "")) or ""
            # Extract base symbol from included or attributes
            sym = attrs.get("base_token_price_usd") and attrs.get("name", "").split("/")[0].strip()
            result.append({
                "pool_address":       p.get("id", "").split("_")[-1] if "_" in p.get("id","") else p.get("id",""),
                "name":               attrs.get("name", ""),
                "base_token":         attrs.get("name", "").split("/")[0].strip().upper(),
                "network":            network,
                "price_change_5m":    float(attrs.get("price_change_percentage", {}).get("m5", 0) or 0),
                "price_change_1h":    float(attrs.get("price_change_percentage", {}).get("h1", 0) or 0),
                "price_change_24h":   float(attrs.get("price_change_percentage", {}).get("h24", 0) or 0),
                "volume_24h_usd":     float(attrs.get("volume_usd", {}).get("h24", 0) or 0),
                "reserve_usd":        float(attrs.get("reserve_in_usd", 0) or 0),
                "transactions_24h":   (attrs.get("transactions", {}).get("h24", {}).get("buys", 0) or 0) +
                                      (attrs.get("transactions", {}).get("h24", {}).get("sells", 0) or 0),
                "fdv_usd":            float(attrs.get("fdv_usd", 0) or 0),
            })
        await _redis_set(key, result, ttl=120)
        return _cache_set(key, result)
    except Exception as e:
        return []


async def get_cg_markets(ids: list[str]) -> list:
    """
    CoinGecko coins/markets — full market data for a list of coin IDs.
    Returns the raw CoinGecko response list (same schema the frontend expects):
      current_price, market_cap, total_volume, price_change_percentage_24h,
      price_change_percentage_7d_in_currency, sparkline_in_7d.price, etc.
    Uses the Pro endpoint + API key to avoid browser-side rate limits.
    TTL: 2 min (fast-moving price data).
    """
    if not ids:
        return []
    ids_str = ",".join(sorted(ids))  # sort for consistent cache key
    import hashlib
    ids_hash = hashlib.md5(ids_str.encode()).hexdigest()[:12]
    key = f"cg_markets_{ids_hash}_{len(ids)}"  # hash-based key, no truncation collision
    cached = _cache_get(key, ttl=120)
    if cached is not None:
        return cached
    r2 = await _redis_get(key)
    if r2:
        _cache_set(key, r2)
        return r2
    base = CG_PRO_BASE if CG_API_KEY else "https://api.coingecko.com/api/v3"
    try:
        client = _get_cg_client()
        r = await client.get(
            f"{base}/coins/markets",
            headers=_cg_headers(),
            params={
                "vs_currency": "usd",
                "ids": ids_str,
                "order": "market_cap_desc",
                "sparkline": "true",
                "price_change_percentage": "30d,7d,1y",
                "per_page": 250,
                "page": 1,
            },
        )
        r.raise_for_status()
        result = r.json()
        _cache_set(key, result)
        return result
    except Exception as e:
        _logger.warning(f"[CG_MARKETS] Error: {e}")
        # Return stale L2 cache on error
        r2 = await _redis_get(key)
        return r2 or []


async def get_cg_derivatives() -> list:
    """
    CoinGecko derivatives tickers — funding rates and open interest.
    Expanded to full CIS universe (all perpetual-listed assets).
    Returns list of {symbol, funding_rate, open_interest_usd, ...}.
    TTL: 5 min (300s Redis).
    """
    key = "cg_derivatives"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)
    if not CG_API_KEY:
        return []
    try:
        client = _get_cg_client()
        r = await client.get(
            f"{CG_PRO_BASE}/derivatives",
            headers=_cg_headers(),
            params={"include_tickers": "unexpired"},
        )
        r.raise_for_status()
        tickers = r.json()

        # All symbols in CIS universe that trade perpetuals
        _CIS_PERPS = {
            "BTC","ETH","SOL","BNB","XRP","ADA","AVAX","DOT","LINK",
            "UNI","AAVE","MKR","CRV","COMP","LDO","ARB","OP","MATIC",
            "POL","STX","NEAR","APT","SUI","INJ","PENDLE","ONDO","JTO",
            "WLD","FET","RENDER","TAO","LTC","DOGE","ATOM",
            # TradFi derivatives (CME futures via CG)
            "SPY","GLD","SLV",
        }

        # Aggregate per symbol: weighted avg funding rate (by OI), sum OI
        _agg: dict[str, dict] = {}
        for t in tickers:
            sym = (t.get("base") or "").upper()
            if sym not in _CIS_PERPS:
                continue
            fr = t.get("funding_rate")
            oi = float(t.get("open_interest_usd") or t.get("open_interest") or 0)
            if fr is None:
                continue
            fr = float(fr)
            if sym not in _agg:
                _agg[sym] = {
                    "symbol":       sym,
                    "markets":      [],
                    "_fr_oi_sum":   0.0,   # Σ(fr × oi) for weighted avg
                    "_oi_sum":      0.0,
                    "price":        float(t.get("last") or 0),
                    "price_change_pct": float(t.get("price_percentage_change_24h") or 0),
                }
            _agg[sym]["markets"].append(t.get("market", ""))
            _agg[sym]["_oi_sum"]    += oi
            _agg[sym]["_fr_oi_sum"] += fr * oi if oi > 0 else fr

        result = []
        for sym, d in _agg.items():
            oi_sum = d["_oi_sum"]
            # Weighted avg funding rate by OI
            if oi_sum > 0:
                avg_fr = d["_fr_oi_sum"] / oi_sum
            else:
                avg_fr = d["_fr_oi_sum"] / max(len(d["markets"]), 1)

            # Funding rate signal interpretation
            if avg_fr > 0.0005:         # > 0.05% per 8h = overleveraged longs
                fr_signal = "overleveraged_long"
            elif avg_fr > 0.0001:       # 0.01%-0.05% = healthy bullish
                fr_signal = "bullish_basis"
            elif avg_fr > -0.0001:      # near zero = balanced
                fr_signal = "neutral"
            elif avg_fr > -0.0005:      # negative = shorts dominant
                fr_signal = "bearish_basis"
            else:                        # very negative = extreme short squeeze risk
                fr_signal = "extreme_short"

            result.append({
                "symbol":              sym,
                "funding_rate":        round(avg_fr, 6),
                "funding_rate_8h_pct": round(avg_fr * 100, 4),
                "funding_signal":      fr_signal,
                "open_interest_usd":   round(oi_sum, 0),
                "markets_count":       len(d["markets"]),
                "price":               d["price"],
                "price_change_pct":    d["price_change_pct"],
            })

        # Sort by OI descending
        result.sort(key=lambda x: -x["open_interest_usd"])
        await _redis_set(key, result, ttl=300)
        return _cache_set(key, result)
    except Exception as e:
        return []


async def get_derivatives_map() -> dict[str, dict]:
    """
    Returns {symbol: {funding_rate, open_interest_usd, funding_signal}} for O-pillar integration.
    Used by cis_provider to compute O-pillar adjustments and LAS.
    Cached in Redis 5 min.
    """
    key = "cg_derivatives_map"
    r_cached = await _redis_get(key)
    if r_cached and isinstance(r_cached, dict):
        return r_cached
    tickers = await get_cg_derivatives()
    deriv_map = {t["symbol"]: t for t in tickers}
    await _redis_set(key, deriv_map, ttl=300)
    return deriv_map


# ── VC Portfolio categories tracked ───────────────────────────────────────────
_VC_CATS = [
    {"id": "andreessen-horowitz-a16z-portfolio", "short": "a16z",           "tier": 1},
    {"id": "paradigm-portfolio",                 "short": "Paradigm",        "tier": 1},
    {"id": "coinbase-ventures-portfolio",        "short": "Coinbase Ventures","tier": 1},
    {"id": "pantera-capital-portfolio",          "short": "Pantera",         "tier": 1},
    {"id": "polychain-capital-portfolio",        "short": "Polychain",       "tier": 1},
    {"id": "multicoin-capital-portfolio",        "short": "Multicoin",       "tier": 1},
    {"id": "galaxy-digital-portfolio",           "short": "Galaxy Digital",  "tier": 1},
    {"id": "dragonfly-capital-portfolio",        "short": "Dragonfly",       "tier": 2},
    {"id": "sequoia-capital-portfolio",          "short": "Sequoia",         "tier": 2},
    {"id": "delphi-ventures-portfolio",          "short": "Delphi",          "tier": 2},
    {"id": "okx-ventures-portfolio",             "short": "OKX Ventures",    "tier": 2},
    {"id": "binance-labs-portfolio",             "short": "Binance Labs",    "tier": 2},
    {"id": "animoca-brands-portfolio",           "short": "Animoca",         "tier": 2},
    {"id": "hashkey-capital-portfolio",          "short": "HashKey",         "tier": 2},
    {"id": "dwf-labs-portfolio",                 "short": "DWF Labs",        "tier": 2},
    {"id": "circle-ventures-portfolio",          "short": "Circle Ventures", "tier": 2},
]
_VC_CAT_IDS = {c["id"] for c in _VC_CATS}
_VC_SHORT    = {c["id"]: c["short"] for c in _VC_CATS}
_VC_TIER     = {c["id"]: c["tier"]  for c in _VC_CATS}


async def get_cg_vc_portfolios() -> list[dict]:
    """
    CoinGecko /coins/categories filtered to major VC portfolio buckets.
    Returns ~16 firms with: name, market_cap, change_24h, volume_24h, top_3_coins, tier.
    Sorted by market_cap desc. TTL: 10 min.
    """
    key = "cg_vc_portfolios"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    if not CG_API_KEY:
        return []

    try:
        client = _get_cg_client()
        r = await client.get(
            f"{CG_PRO_BASE}/coins/categories",
            headers=_cg_headers(),
            params={"order": "market_cap_desc"},
        )
        r.raise_for_status()
        all_cats = r.json()

        result = []
        for cat in all_cats:
            cid = cat.get("id", "")
            # Match VC portfolio buckets resiliently: the curated whitelist OR any
            # category whose id ends in "-portfolio" (CoinGecko's naming for VC
            # holdings). The whitelist alone rotted as CG renamed/removed ids
            # (animoca-brands-portfolio → animoca-brands, binance-labs gone), which
            # silently emptied this panel. Suffix-match auto-includes new firms.
            if cid not in _VC_CAT_IDS and not cid.endswith("-portfolio"):
                continue
            mcap   = cat.get("market_cap") or 0
            chg24  = cat.get("market_cap_change_24h") or 0
            vol24  = cat.get("volume_24h") or 0
            top3   = cat.get("top_3_coins_id") or cat.get("top_3_coins") or []
            # Quality floor — the "-portfolio" suffix auto-includes CoinGecko JOKE categories
            # (Pump Fund Portfolio = $0 mcap, scam holdings like CLAWPUMP). Require a real
            # portfolio (whitelisted firms bypass the floor) and block meme/pump buckets.
            if cid not in _VC_CAT_IDS:
                if mcap < 25_000_000 or any(b in cid for b in ("pump", "meme", "sample", "test", "airdrop")):
                    continue
            result.append({
                "id":          cid,
                "name":        _VC_SHORT.get(cid, cat.get("name", cid)),
                "full_name":   cat.get("name", cid),
                "tier":        _VC_TIER.get(cid, 2),
                "market_cap":  mcap,
                "change_24h":  round(chg24, 2),
                "volume_24h":  vol24,
                "top_coins":   top3[:3],
                "updated_at":  cat.get("updated_at", ""),
            })

        result.sort(key=lambda x: -(x["market_cap"] or 0))
        await _redis_set(key, result, ttl=600)
        return _cache_set(key, result)
    except Exception as e:
        _logger.warning(f"[CG_VC_PORTFOLIOS] Error: {e}")
        return []


async def get_macro_pulse() -> dict:
    """
    Combined macro snapshot for the MacroPulse widget.
    Fetches CG global market data + Fear & Greed + BTC price in parallel.
    Uses Pro key when available; falls back to free CoinGecko endpoints.
    Response mirrors the field paths MacroPulse.jsx expects:
      .data.market_cap_percentage.btc
      .data.market_cap_change_percentage_24h_usd
      .fng.value / .fng.value_classification
      .btc.usd / .btc.usd_24h_change / .btc.usd_7d_change
    TTL: 5 min Redis, 2 min in-memory.
    """
    key = "macro_pulse"
    cached = _cache_get(key, ttl=120)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    cg_base = CG_PRO_BASE if CG_API_KEY else "https://api.coingecko.com/api/v3"
    try:
        cg   = _get_cg_client()
        msc  = _get_misc_client()
        # ── Run all fetches in parallel (4 concurrent) ─────────────────────────
        global_r, fng_r, btc_r, defi_ov = await asyncio.gather(
            cg.get(f"{cg_base}/global", headers=_cg_headers()),
            msc.get("https://api.alternative.me/fng/?limit=1"),
            cg.get(
                f"{cg_base}/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_7d_change": "true",
                },
                headers=_cg_headers(),
            ),
            get_defi_overview(),   # parallel — has its own Redis TTL
            return_exceptions=True,
        )

        # ── Parse global ──────────────────────────────────────────────────────
        cg_data: dict = {}
        if not isinstance(global_r, Exception) and global_r.status_code == 200:
            cg_data = global_r.json().get("data", {})

        # ── Parse FNG ─────────────────────────────────────────────────────────
        fng_entry: dict = {}
        if not isinstance(fng_r, Exception) and fng_r.status_code == 200:
            fng_list = fng_r.json().get("data", [])
            if fng_list:
                fng_entry = fng_list[0]

        # ── Parse BTC ─────────────────────────────────────────────────────────
        btc_entry: dict = {}
        if not isinstance(btc_r, Exception) and btc_r.status_code == 200:
            btc_entry = btc_r.json().get("bitcoin", {})

        # ── Parse DeFi overview (only need total_tvl_usd) ─────────────────────
        _defi_tvl = 0
        if not isinstance(defi_ov, Exception) and isinstance(defi_ov, dict):
            _defi_tvl = defi_ov.get("total_tvl_usd", 0)

        _btc_dom = round(cg_data.get("market_cap_percentage", {}).get("btc", 0), 2)
        _fg_val  = int(fng_entry.get("value", 50))
        _fg_lbl  = fng_entry.get("value_classification", "Neutral")
        _btc_px  = btc_entry.get("usd", 0)
        _mc_usd  = cg_data.get("total_market_cap", {}).get("usd", 0)

        result = {
            # ── nested structure (MacroPulse.jsx compat) ──────────────────────
            "data": {
                "market_cap_percentage": cg_data.get("market_cap_percentage", {}),
                "market_cap_change_percentage_24h_usd": cg_data.get(
                    "market_cap_change_percentage_24h_usd", 0
                ),
            },
            "fng": {
                "value": str(_fg_val),
                "value_classification": _fg_lbl,
            },
            "btc": btc_entry,  # {usd, usd_24h_change, usd_7d_change}
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # ── flat fields (MCP agent compat) ────────────────────────────────
            "btc_price":             _btc_px,
            "btc_dominance":         _btc_dom,
            "fear_greed_index":      _fg_val,
            "fear_greed_value":     _fg_val,  # alias for backward compat
            "fear_greed_label":     _fg_lbl,
            "total_market_cap_usd":  _mc_usd,
            "defi_tvl_usd":          _defi_tvl,
            "macro_regime":          "UNKNOWN",  # set by Mac Mini push via Redis; see below
        }

        # ── EODHD regime fallback — use when Mac Mini hasn't pushed a regime ──
        # Check Redis for Mac Mini regime first; if UNKNOWN, derive from EODHD.
        try:
            mm_regime = await _redis_get("cis:local_scores")
            if mm_regime and isinstance(mm_regime, dict):
                # Mac Mini stores nested {"macro": {"regime": "RISK_ON"}}; flat "macro_regime" key is fallback
                pushed_regime = (
                    (mm_regime.get("macro") or {}).get("regime")
                    or mm_regime.get("macro_regime")
                    or "UNKNOWN"
                )
            else:
                pushed_regime = "UNKNOWN"

            if pushed_regime != "UNKNOWN":
                result["macro_regime"] = pushed_regime
                result["regime_source"] = "mac_mini"
            elif EODHD_KEY:
                # Derive from economic indicators (cached 4h separately)
                us_macro = await get_eodhd_macro_indicators("usa")
                derived  = us_macro.get("derived_regime", "UNKNOWN")
                if derived != "UNKNOWN":
                    result["macro_regime"]   = derived
                    result["regime_source"]  = "eodhd_derived"
                    result["regime_inputs"]  = us_macro.get("regime_inputs", {})
                else:
                    # EODHD failed or missing — try FRED
                    fred_data = await _get_fred_macro_indicators("usa")
                    fred_regime = fred_data.get("derived_regime")
                    if fred_regime and fred_regime != "UNKNOWN":
                        result["macro_regime"]   = fred_regime
                        result["regime_source"] = "fred_derived"
                        result["regime_inputs"] = fred_data.get("regime_inputs", {})
                # Always apply unified regime: blend crypto sentiment + macro inputs
                _apply_unified_regime(result, fred_data, _fg_val, _btc_dom, cg_data)
                # Write unified regime to shared key so CIS endpoint reads the same value
                await _redis_set("cis:regime", {
                    "regime": result["macro_regime"],
                    "source": result.get("regime_source", "unified"),
                }, ttl=300)
            else:
                # No EODHD key — try FRED directly (free, no API key needed)
                fred_data = await _get_fred_macro_indicators("usa")
                fred_regime = fred_data.get("derived_regime")
                if fred_regime and fred_regime != "UNKNOWN":
                    result["macro_regime"]   = fred_regime
                    result["regime_source"] = "fred_derived"
                    result["regime_inputs"] = fred_data.get("regime_inputs", {})
                # Always apply unified regime: blend crypto sentiment + macro inputs
                _apply_unified_regime(result, fred_data, _fg_val, _btc_dom, cg_data)
                # Write unified regime to shared key so CIS endpoint reads the same value
                await _redis_set("cis:regime", {
                    "regime": result["macro_regime"],
                    "source": result.get("regime_source", "unified"),
                }, ttl=300)
        except Exception:
            pass  # regime stays UNKNOWN — non-blocking

        # ONE SPELLING ON THE WIRE (S-243, 2026-08-26). Every branch above can
        # land a different dialect here: the Mac push sends `Tightening`, the
        # EODHD/FRED derivations send their own, and the initial value is the
        # literal "UNKNOWN". This endpoint is one of two public regime surfaces
        # (the other is /api/v1/cis/universe) and they must agree character for
        # character — every regime lookup table in this codebase and in
        # dashboard/src is keyed UPPER_SNAKE, so a title-case label does not
        # error, it just misses and takes a default nobody chose.
        # "UNKNOWN" collapses to None here for the same reason it does on the
        # write path: a placeholder that reads like a reading is worse than an
        # honest absence (S-120).
        from src.data.cis.cis_provider import canonical_regime_strict
        result["macro_regime"] = canonical_regime_strict(result.get("macro_regime"))

        await _redis_set(key, result, ttl=300)
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# MORALIS — Multi-chain wallet analysis (free tier: 10M req/month)
# Requires free API key from moralis.io
# ══════════════════════════════════════════════════════════════════════════════
MORALIS_BASE = "https://deep-index.moralis.io/api/v2.2"

async def get_wallet_portfolio(address: str, chain: str = "eth") -> dict:
    """
    Full wallet portfolio: tokens + DeFi positions + net worth.
    chain: eth, bsc, polygon, arbitrum, optimism, base, avalanche
    """
    if not MORALIS_KEY:
        return {"error": "MORALIS_API_KEY not set. Get free key at moralis.io"}

    key = f"wallet:{address}:{chain}"
    cached = _cache_get(key, ttl=120)
    if cached:
        return cached

    headers = {"X-API-Key": MORALIS_KEY}
    try:
        client = _get_misc_client()
        # Net worth across all chains
        r_worth = await client.get(
            f"{MORALIS_BASE}/wallets/{address}/net-worth",
            headers=headers,
            params={"chains": [chain], "exclude_spam": "true", "exclude_unverified_contracts": "true"}
        )
        # Token balances with prices
        r_tokens = await client.get(
            f"{MORALIS_BASE}/wallets/{address}/tokens",
            headers=headers,
            params={"chain": chain, "exclude_spam": "true"}
        )
        # Recent transactions
        r_txs = await client.get(
            f"{MORALIS_BASE}/wallets/{address}/history",
            headers=headers,
            params={"chain": chain, "limit": 10}
        )

        worth_data   = r_worth.json()
        tokens_data  = r_tokens.json()
        txs_data     = r_txs.json()

        tokens = tokens_data.get("result", [])[:15]
        txs    = txs_data.get("result", [])[:10]

        result = {
            "address": address,
            "chain":   chain,
            "net_worth_usd": float(worth_data.get("total_networth_usd", 0)),
            "holdings": [{
                "symbol":      t.get("symbol"),
                "name":        t.get("name"),
                "balance":     float(t.get("balance_formatted", 0)),
                "price_usd":   float(t.get("usd_price", 0) or 0),
                "value_usd":   float(t.get("usd_value", 0) or 0),
                "pct_change":  float(t.get("usd_price_24hr_percent_change", 0) or 0),
                "thumbnail":   t.get("thumbnail"),
            } for t in tokens if float(t.get("usd_value", 0) or 0) > 0.01],
            "recent_txs": [{
                "hash":     tx.get("hash"),
                "type":     tx.get("category", "transfer"),
                "value_usd": float(tx.get("value_usd", 0) or 0),
                "timestamp": tx.get("block_timestamp"),
                "summary":  tx.get("summary"),
            } for tx in txs],
            "source": "moralis",
        }
        return _cache_set(key, result)
    except Exception as e:
        return {"address": address, "error": str(e), "source": "moralis"}


async def get_wallet_defi_positions(address: str, chain: str = "eth") -> dict:
    """Get active DeFi positions (Uniswap LP, Aave lending, etc.)"""
    if not MORALIS_KEY:
        return {"error": "MORALIS_API_KEY not set"}

    key = f"defi:{address}:{chain}"
    cached = _cache_get(key, ttl=180)
    if cached:
        return cached

    headers = {"X-API-Key": MORALIS_KEY}
    try:
        client = _get_misc_client()
        r = await client.get(
            f"{MORALIS_BASE}/wallets/{address}/defi/positions",
            headers=headers,
            params={"chain": chain}
        )
        positions = r.json()
        result = {
            "address":  address,
            "chain":    chain,
            "positions": positions if isinstance(positions, list) else positions.get("result", []),
            "source":   "moralis",
        }
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_token_holders(token_address: str, chain: str = "eth", limit: int = 20) -> dict:
    """Top token holders — useful for whale identification."""
    if not MORALIS_KEY:
        return {"error": "MORALIS_API_KEY not set"}

    key = f"holders:{token_address}:{chain}"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached

    headers = {"X-API-Key": MORALIS_KEY}
    try:
        client = _get_misc_client()
        r = await client.get(
            f"{MORALIS_BASE}/erc20/{token_address}/owners",
            headers=headers,
            params={"chain": chain, "limit": limit, "order": "DESC"}
        )
        data = r.json()
        result = {
            "token_address": token_address,
            "holders": data.get("result", []),
            "source": "moralis",
        }
        return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# ETHERSCAN — Ethereum deep data (free: 3 req/s, 100K/day)
# Requires free key from etherscan.io/myapikey
# ══════════════════════════════════════════════════════════════════════════════
ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"

async def etherscan_request(module: str, action: str, **params) -> dict:
    """Generic Etherscan V2 request wrapper."""
    if not ETHERSCAN_KEY:
        return {"error": "ETHERSCAN_API_KEY not set. Get free key at etherscan.io/myapikey"}

    try:
        client = _get_misc_client()
        r = await client.get(ETHERSCAN_BASE, params={
            "chainid": 1,
            "module":  module,
            "action":  action,
            "apikey":  ETHERSCAN_KEY,
            **params
        })
        data = r.json()
        if data.get("status") == "1":
            return {"result": data.get("result"), "source": "etherscan"}
        else:
            return {"error": data.get("message", "Unknown error"), "source": "etherscan"}
    except Exception as e:
        return {"error": str(e), "source": "etherscan"}


async def get_eth_balance(address: str) -> dict:
    """ETH balance for an address."""
    result = await etherscan_request("account", "balance", address=address, tag="latest")
    if "result" in result:
        wei = int(result["result"])
        return {"address": address, "eth": wei / 1e18, "wei": wei}
    return result


async def get_eth_transactions(address: str, limit: int = 20) -> dict:
    """Recent normal transactions for an address."""
    return await etherscan_request(
        "account", "txlist",
        address=address, startblock=0, endblock=99999999,
        page=1, offset=limit, sort="desc"
    )


async def get_token_transfers(address: str, limit: int = 20) -> dict:
    """ERC-20 token transfers for an address."""
    return await etherscan_request(
        "account", "tokentx",
        address=address, page=1, offset=limit, sort="desc"
    )


async def get_top_token_holders(token_address: str) -> dict:
    """Top 10 holders of an ERC-20 token (good for whale tracking)."""
    return await etherscan_request("token", "tokenholderlist",
                                    contractaddress=token_address, page=1, offset=10)


async def get_eth_gas() -> dict:
    """Current ETH gas prices."""
    key = "gas"
    cached = _cache_get(key, ttl=30)
    if cached:
        return cached

    result = await etherscan_request("gastracker", "gasoracle")
    return _cache_set(key, result) if "result" in result else result


# ══════════════════════════════════════════════════════════════════════════════
# COMPOSITE MMI — Market Mood Index combining all free sources
# ══════════════════════════════════════════════════════════════════════════════

async def calculate_mmi(token: str = "BTC") -> dict:
    """
    Composite Market Mood Index using:
    - Fear & Greed (25%) — Alternative.me, free
    - Price momentum (25%) — Binance/CoinGecko, free
    - DeFi TVL trend (20%) — DeFiLlama 24h change, free
    - DEX volume trend (15%) — DeFiLlama, free
    - Stablecoin dominance (15%) — CoinGecko global, free
    """
    key = f"mmi:{token}"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    try:
        fg_data, price_data, tvl_data, dex_data, cg_global = await asyncio.gather(
            get_fear_greed(limit=7),
            get_price(token),
            get_defi_overview(),
            get_dex_volumes(),
            get_cg_global(),
        )

        # Component 1: Fear & Greed (0-100)
        fg_score = fg_data.get("current", {}).get("value", 50)

        # Component 2: Price momentum (24h change → 0-100)
        price_change = price_data.get("change_24h", 0) if price_data else 0
        momentum_score = min(100, max(0, 50 + price_change * 2.5))

        # Component 3: DeFi TVL trend — live 24h change from DeFiLlama
        # +2% TVL day = strong confidence (score 60); -2% = low (score 40)
        defi_change = tvl_data.get("defi_change_24h", 0) if not tvl_data.get("error") else 0
        tvl_score = min(100, max(0, 50 + defi_change * 5))

        # Component 4: DEX volume relative to $3B/day baseline
        dex_volume = dex_data.get("total_24h", 0)
        dex_score = min(100, max(20, 40 + (dex_volume / 1e9) * 2)) if dex_volume else 50

        # Component 5: BTC dominance — rising dominance = capital rotating to safety = risk-off
        # BTC dom 60% = neutral (50); 70% = strong risk-off (30); 50% = risk-on (70)
        # Falls back to neutral (50) if CG global unavailable (no Pro key)
        btc_dom = 60.0  # neutral baseline
        if isinstance(cg_global, dict) and not cg_global.get("error"):
            btc_dom = float(cg_global.get("btc_dominance") or 60)
        stable_score = min(100, max(0, 50 - (btc_dom - 60) * 2))

        # Weighted composite
        mmi_score = round(
            fg_score       * 0.25 +
            momentum_score * 0.25 +
            tvl_score      * 0.20 +
            dex_score      * 0.15 +
            stable_score   * 0.15,
            1
        )

        signal = (
            "STRONG OUTPERFORM"  if mmi_score >= 75 else
            "OUTPERFORM"         if mmi_score >= 60 else
            "NEUTRAL"            if mmi_score >= 40 else
            "UNDERPERFORM"       if mmi_score >= 25 else
            "UNDERWEIGHT"
        )

        result = {
            "token":     token,
            "mmi_score": mmi_score,
            "signal":    signal,
            "components": {
                "fear_greed":    round(fg_score, 1),
                "momentum":      round(momentum_score, 1),
                "defi_tvl":      round(tvl_score, 1),
                "dex_volume":    round(dex_score, 1),
                "btc_dominance": round(stable_score, 1),
            },
            "btc_dominance":    round(btc_dom, 2),
            "fear_greed_label": fg_data.get("current", {}).get("label", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": ["alternative.me", "coingecko", "defillama"],
        }
        return _cache_set(key, result)
    except Exception as e:
        return {"token": token, "mmi_score": 50, "signal": "NEUTRAL", "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# HISTORICAL KLINES FOR BACKTEST (Binance + OKX)
# ══════════════════════════════════════════════════════════════════════════════

# Binance API (public, no key needed for klines)
BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"  # geo-accessible mirror (api.binance.com blocked on Railway US)

# OKX API (public, no key needed for public candles)
OKX_KLINES_URL = "https://www.okx.com/api/v5/market/history-candles"


async def get_klines_binance(symbol: str, interval: str = "1d", months: int = 6) -> list[dict]:
    """
    Fetch historical klines from Binance.

    Args:
        symbol: e.g., "BTCUSDT", "ETHUSDT"
        interval: "1d", "1h", "4h", etc.
        months: number of months of history (default 6, max ~6 months limit)

    Returns:
        List of kline dicts: [{"time": ts, "open":, "high":, "low":, "close":, "volume":}, ...]
    """
    import httpx

    # Binance limit is 1000 candles max per request
    limit = min(months * 30, 1000)

    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit,
        "startTime": int((datetime.now(timezone.utc) - timedelta(days=months * 30)).timestamp() * 1000)
    }

    try:
        client = _get_binance_client()
        resp = await client.get(BINANCE_KLINES_URL, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [
            {
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "timestamp": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).isoformat(),
            }
            for k in data
        ]
    except Exception as e:
        _logger.warning(f"[BINANCE] klines error for {symbol}: {e}")
        return []


async def get_klines_okx(symbol: str, interval: str = "1d", months: int = 6) -> list[dict]:
    """
    Fetch historical klines from OKX.

    Args:
        symbol: e.g., "BTC-USDT", "ETH-USDT"
        interval: "1D", "1H", "4H", etc. (OKX format)
        months: number of months of history

    Returns:
        List of kline dicts: [{"time": ts, "open":, "high":, "low":, "close":, "volume":}, ...]
    """
    import httpx

    # Map interval format
    interval_map = {"1d": "1D", "1h": "1H", "4h": "4H", "15m": "15M", "5m": "5M"}
    okx_interval = interval_map.get(interval, "1D")

    # OKX uses after/before for pagination, we fetch the most recent ~6 months
    params = {
        "instId": symbol.upper().replace("USDT", "-USDT"),
        "bar": okx_interval,
        "limit": 100,
    }

    try:
        client = _get_misc_client()
        resp = await client.get(OKX_KLINES_URL, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if data.get("code") != "0":
            return []
        klines = data.get("data", [])
        # OKX returns: [time, open, high, low, close, volume, ...]
        return [
            {
                "time": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "timestamp": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).isoformat(),
            }
            for k in reversed(klines)  # Oldest first
        ]
    except Exception as e:
        _logger.warning(f"[OKX] klines error for {symbol}: {e}")
        return []


async def get_klines(symbol: str, source: str = "binance", interval: str = "1d", months: int = 6) -> list[dict]:
    """
    Unified klines fetcher - try primary source, fallback to other.

    Args:
        symbol: e.g., "BTCUSDT"
        source: "binance", "okx", or "auto" (try binance first, then okx)
    """
    if source == "binance" or source == "auto":
        result = await get_klines_binance(symbol, interval, months)
        if result:
            return result

    if source == "okx" or source == "auto":
        return await get_klines_okx(symbol, interval, months)

    return []


# ══════════════════════════════════════════════════════════════════════════════
# EODHD — Macro Economic Indicators + Equity Fundamentals
# Requires EODHD_API_KEY in Railway env vars.
# Plans: All-World ~$80/mo  ·  Fundamentals World ~$50/mo  ·  Free plan = EOD only
# Docs: https://eodhd.com/financial-apis/
# ══════════════════════════════════════════════════════════════════════════════

EODHD_BASE = "https://eodhd.com/api"

# Macro indicator codes recognised by EODHD /macro-indicator/{country}
_EODHD_MACRO_INDICATORS = {
    "cpi_yoy":          "inflation_consumer_prices_annual",
    "gdp_growth":       "real_gdp_growth",
    "unemployment":     "unemployment_rate",
    "interest_rate":    "interest_rate",       # central bank policy rate
    "real_interest":    "real_interest_rate",
}

# Which countries we care about — ISO 2-letter
_MACRO_COUNTRIES = ["usa", "hkg", "chn"]


async def get_eodhd_macro_indicators(country: str = "usa") -> dict:
    """
    Fetch latest macro economic indicators for a country from EODHD.
    Returns: {cpi_yoy, gdp_growth, unemployment, interest_rate, real_interest, country, source}
    TTL: 4 hours Redis (macro data is daily/monthly; no need to hammer)
    """
    if not EODHD_KEY:
        return {"error": "EODHD_API_KEY not set", "country": country}

    country = country.lower()
    key = f"eodhd_macro_{country}"
    cached = _cache_get(key, ttl=14400)   # 4h in-mem
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    client = _get_misc_client()
    result = {"country": country, "source": "eodhd", "indicators": {}}
    errors = []

    async def _fetch_one(short_name: str, indicator_code: str):
        try:
            r = await client.get(
                f"{EODHD_BASE}/macro-indicator/{country}",
                params={
                    "indicator": indicator_code,
                    "fmt": "json",
                    "api_token": EODHD_KEY,
                    "limit": 4,          # last 4 readings for trend
                },
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                if data and isinstance(data, list):
                    latest = data[0]
                    prev   = data[1] if len(data) > 1 else None
                    return short_name, {
                        "value":       float(latest.get("value", 0) or 0),
                        "date":        latest.get("date", ""),
                        "prev_value":  float(prev.get("value", 0)) if prev else None,
                        "trend":       "up" if prev and float(latest.get("value", 0)) > float(prev.get("value", 0)) else "down",
                    }
        except Exception as e:
            errors.append(f"{short_name}: {e}")
        return short_name, None

    tasks = [_fetch_one(k, v) for k, v in _EODHD_MACRO_INDICATORS.items()]
    fetched = await asyncio.gather(*tasks)

    for short_name, data in fetched:
        if data:
            result["indicators"][short_name] = data

    result["errors"] = errors if errors else None

    # Derive simple regime signal from EODHD data
    inds = result["indicators"]
    if not inds:
        # All indicators failed — EODHD free plan may not cover macro data, or API errored silently
        result["error"] = "EODHD_MACRO_UNAVAILABLE"
        result["derived_regime"] = "UNKNOWN"
        result["regime_inputs"] = {}
    else:
        cpi   = inds.get("cpi_yoy",       {}).get("value", 0) or 0
        gdp   = inds.get("gdp_growth",    {}).get("value", 0) or 0
        rate  = inds.get("interest_rate", {}).get("value", 0) or 0
        rate_trend = inds.get("interest_rate", {}).get("trend", "")

        regime = _derive_macro_regime(cpi=cpi, gdp=gdp, rate=rate, rate_trend=rate_trend)
        result["derived_regime"] = regime
        result["regime_inputs"]  = {"cpi_yoy": cpi, "gdp_growth": gdp, "policy_rate": rate}

    await _redis_set(key, result, ttl=14400)
    return _cache_set(key, result)


def _derive_macro_regime(cpi: float, gdp: float, rate: float, rate_trend: str) -> str:
    """
    Simple regime classification from EODHD macro indicators.
    Used as Railway-side fallback when Mac Mini hasn't pushed a regime.

    Thresholds calibrated to post-2020 environment:
      TIGHTENING   : CPI > 4% OR rate rising AND CPI > 3%
      EASING       : rate falling AND CPI < 3%
      STAGFLATION  : CPI > 4% AND GDP < 1.5%
      GOLDILOCKS   : CPI 1.5-3.5% AND GDP > 2.5% AND rate stable
      RISK_ON      : GDP > 2% AND CPI moderate (2-4%)
      RISK_OFF     : GDP < 1% OR rate > 5% AND CPI > 3%
    """
    if cpi > 4 and gdp < 1.5:
        return "STAGFLATION"
    if cpi > 4 or (rate_trend == "up" and cpi > 3):
        return "TIGHTENING"
    if rate_trend == "down" and cpi < 3:
        return "EASING"
    if 1.5 <= cpi <= 3.5 and gdp > 2.5 and rate_trend != "up":
        return "GOLDILOCKS"
    if gdp < 1 or (rate > 5 and cpi > 3):
        return "RISK_OFF"
    return "RISK_ON"


def derive_regime_unified(
    vix: Optional[float] = None,
    fng_value: Optional[int] = None,
    btc_30d: float = 0.0,
    btc_dom: float = 52.0,
    cpi: float = 0.0,
    gdp: float = 0.0,
    rate: float = 0.0,
    rate_trend: str = "",
) -> str:
    """
    Weighted regime classifier combining crypto sentiment (VIX/FNG/BTC) and
    real-economy signals (CPI/GDP/rates). Returns a unified regime string.

    Weights:
      Crypto sentiment (VIX/FNG/BTC momentum): 40%
      Real-economy (CPI/GDP/rates):          60%

    Each signal normalized 0-100:
      vix_sentiment:   100-vix  (VIX 10→90, 30→70 is bearish)
      fng_sentiment:   fng      (FNG 0-100 direct)
      btc_momentum:    BTC 30d change mapped to 0-100
      econ_sentiment:  derived from _derive_macro_regime on macro inputs

    All regimes: Goldilocks / Risk-On / Easing / Neutral / Tightening / Risk-Off / Stagflation
    """
    # ── Crypto sentiment score (0-100) ───────────────────────────────────────
    vix_s  = max(0.0, min(100.0, 100.0 - (vix or 20.0)))       # low VIX = bullish
    fng_s  = max(0.0, min(100.0, float(fng_value or 50)))
    btc_s  = max(0.0, min(100.0, (btc_30d + 20) * 2.5))        # -20%→0, +20%→100

    crypto_score = vix_s * 0.35 + fng_s * 0.40 + btc_s * 0.25   # 0-100

    # ── Real-economy score (0-100) ─────────────────────────────────────────────
    # Use the same threshold logic as _derive_macro_regime but emit a 0-100 score
    _MACRO_WEIGHTS = {
        "STAGFLATION": 10,
        "TIGHTENING":  25,
        "RISK_OFF":    20,
        "NEUTRAL":     45,
        "EASING":      60,
        "RISK_ON":     70,
        "GOLDILOCKS":  85,
    }
    macro_regime = _derive_macro_regime(cpi=cpi, gdp=gdp, rate=rate, rate_trend=rate_trend)
    macro_score = _MACRO_WEIGHTS.get(macro_regime, 45)

    # ── Weighted combined score ─────────────────────────────────────────────────
    combined = crypto_score * 0.40 + macro_score * 0.60          # 0-100

    if combined >= 80:
        return "GOLDILOCKS"
    if combined >= 70:
        return "RISK_ON"
    if combined >= 60:
        return "EASING"
    if combined >= 45:
        return "NEUTRAL"
    if combined >= 30:
        return "TIGHTENING"
    if combined < 20:
        return "RISK_OFF"
    return "STAGFLATION"


# ── World Bank Fallback — Free macro data for HK / CN / USA ───────────────────
# World Bank API: https://api.worldbank.org/v2
# No API key required. Annual data, updated ~6 months after year-end.
# Used as fallback when EODHD is unavailable (expired key or free plan limit).

async def _get_worldbank_macro(country: str) -> dict:
    """
    Free fallback for EODHD macro data using World Bank API + yfinance.
    Returns same structure as get_eodhd_macro_indicators().
    Country codes: 'hkg', 'chn', 'usa'
    """
    WB_CODES = {"hkg": "HKG", "chn": "CHN", "usa": "USA"}
    WB_BASE = "https://api.worldbank.org/v2"

    wb_code = WB_CODES.get(country.lower(), country.upper())
    indicators = {}

    async def _fetch_wb(short_name, wb_indicator):
        try:
            client = _get_misc_client()
            r = await client.get(
                f"{WB_BASE}/country/{wb_code}/indicator/{wb_indicator}",
                params={"format": "json", "mrv": 2, "per_page": 2},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                rows = data[1] if len(data) > 1 else []
                rows = [x for x in (rows or []) if x.get("value") is not None]
                if rows:
                    latest = rows[0]
                    prev = rows[1] if len(rows) > 1 else None
                    val = float(latest["value"])
                    prev_val = float(prev["value"]) if prev else None
                    return short_name, {
                        "value": round(val, 2),
                        "date": latest.get("date", ""),
                        "prev_value": round(prev_val, 2) if prev_val else None,
                        "trend": "up" if prev_val and val > prev_val else "down",
                        "source": "worldbank",
                    }
        except Exception:
            pass
        return short_name, None

    tasks = [
        _fetch_wb("cpi_yoy",      "FP.CPI.TOTL.ZG"),
        _fetch_wb("gdp_growth",   "NY.GDP.MKTP.KD.ZG"),
        _fetch_wb("unemployment", "SL.UEM.TOTL.ZS"),
    ]
    fetched = await asyncio.gather(*tasks)
    for name, val in fetched:
        if val:
            indicators[name] = val

    # Known policy rates — updated May 2026
    # Fed: 4.25% (two 25bp cuts in 2025 from 4.75% peak)
    # HKMA: tracks USD LIBOR/SOFR closely, effectively 4.25-4.50%
    # PBOC: continued easing, MLF rate 3.10%
    policy_rates = {
        "hkg": {"value": 4.25, "date": "2026-05", "trend": "down", "source": "hkma", "prev_value": 4.75},
        "chn": {"value": 3.10, "date": "2026-05", "trend": "down", "source": "pboc", "prev_value": 3.35},
        "usa": {"value": 4.25, "date": "2026-05", "trend": "down", "source": "fed",  "prev_value": 4.50},
    }
    if country.lower() in policy_rates:
        indicators["interest_rate"] = policy_rates[country.lower()]

    # PMI proxy from yfinance equity index momentum (5-day return → 50 ± 15 scale)
    yf_symbols = {"hkg": "^HSI", "chn": "000001.SS", "usa": "SPY"}
    yf_sym = yf_symbols.get(country.lower())
    if yf_sym:
        try:
            import yfinance as yf
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period="5d")
            if not hist.empty:
                close_latest = float(hist["Close"].iloc[-1])
                close_prev   = float(hist["Close"].iloc[0])
                pct = round((close_latest - close_prev) / close_prev * 100, 2)
                pmi_proxy = round(50 + max(-15, min(15, pct * 2)), 1)
                indicators["pmi"] = {
                    "value": pmi_proxy,
                    "date": hist.index[-1].strftime("%Y-%m-%d"),
                    "trend": "up" if pct > 0 else "down",
                    "source": "yfinance_proxy",
                    "note": f"{yf_sym} 5d: {pct:+.2f}%",
                }
        except Exception:
            pass

    if not indicators:
        return {"error": "WORLDBANK_UNAVAILABLE", "country": country, "indicators": {}}

    cpi        = indicators.get("cpi_yoy",       {}).get("value", 0) or 0
    gdp        = indicators.get("gdp_growth",    {}).get("value", 0) or 0
    rate       = indicators.get("interest_rate", {}).get("value", 0) or 0
    rate_trend = indicators.get("interest_rate", {}).get("trend", "")

    return {
        "country":        country,
        "source":         "worldbank+yfinance",
        "indicators":     indicators,
        "derived_regime": _derive_macro_regime(cpi=cpi, gdp=gdp, rate=rate, rate_trend=rate_trend),
        "regime_inputs":  {"cpi_yoy": cpi, "gdp_growth": gdp, "policy_rate": rate},
    }


# ── FRED Fallback — Free macro data (no API key required) ─────────────────────
# FRED: Federal Reserve Economic Data (St. Louis Fed)
# Series used:
#   CPALTT01USM661S  — CPI YoY % (monthly, already year-over-year)
#   A191RL1Q225SBEA   — Real GDP QoQ % (quarterly)
#   UNRATE           — Unemployment rate % (monthly)
#   FEDFUNDS         — Federal funds rate % (monthly)

_FRED_SERIES = {
    "cpi_yoy":       "CPALTT01USM661S",
    "gdp_growth":    "A191RL1Q225SBEA",
    "unemployment":  "UNRATE",
    "interest_rate": "FEDFUNDS",
}


async def _get_fred_macro_indicators(country: str = "usa") -> dict:
    """
    Fetch latest US macro indicators from FRED (Federal Reserve Economic Data).
    Free, no API key needed. Used as fallback when EODHD is unavailable.

    Series used:
      CPIAUCSL        — CPI index level (monthly), used to compute YoY %
      A191RL1Q225SBEA — Real GDP QoQ % (quarterly, already percent change)
      UNRATE          — Unemployment rate % (monthly)
      FEDFUNDS        — Federal funds rate % (monthly)
    TTL: 4 hours Redis.
    """
    if country.lower() != "usa":
        return {"country": country, "error": "FRED fallback only supports USA"}

    key = "fred_macro_usa"
    cached = _cache_get(key, ttl=14400)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    client = _get_misc_client()
    result = {"country": "usa", "source": "fred", "indicators": {}}
    errors = []

    async def _fetch_cpi_yoy():
        """CPI YoY: fetch CPIAUCSL, compute 12-month % change."""
        try:
            r = await client.get(
                "https://fred.stlouisfed.org/graph/fredgraph.csv",
                params={"id": "CPIAUCSL", "limit": 14},
                timeout=15,
            )
            if r.status_code == 200:
                lines = r.text.strip().split("\n")
                rows = [ln.split(",") for ln in lines[1:] if ln]
                rows_sorted = sorted(rows, key=lambda r: r[0], reverse=True)
                # rows_sorted[0] = latest month, [12] = same month last year
                if len(rows_sorted) >= 13:
                    latest = rows_sorted[0]
                    prev = rows_sorted[12]
                    val = float(latest[1])
                    prev_val = float(prev[1])
                    yoy = (val - prev_val) / prev_val * 100
                    return {
                        "value":     round(yoy, 2),
                        "date":      latest[0],
                        "prev_value": round((prev_val - float(rows_sorted[13][1])) / float(rows_sorted[13][1]) * 100, 2) if len(rows_sorted) > 13 else None,
                        "trend":     "up" if yoy > 0 else "down",
                    }
        except Exception as e:
            errors.append(f"cpi_yoy: {e}")
        return None

    async def _fetch_series(short_name: str, series_id: str):
        try:
            r = await client.get(
                "https://fred.stlouisfed.org/graph/fredgraph.csv",
                params={"id": series_id, "limit": 4},
                timeout=15,
            )
            if r.status_code == 200:
                lines = r.text.strip().split("\n")
                rows = [ln.split(",") for ln in lines[1:] if ln]
                rows_sorted = sorted(rows, key=lambda r: r[0], reverse=True)
                if len(rows_sorted) >= 2:
                    latest = rows_sorted[0]
                    prev = rows_sorted[1]
                    try:
                        val = float(latest[1])
                        prev_val = float(prev[1])
                        return short_name, {
                            "value":      val,
                            "date":       latest[0],
                            "prev_value": prev_val,
                            "trend":      "up" if val > prev_val else "down",
                        }
                    except (ValueError, IndexError):
                        pass
        except Exception as e:
            errors.append(f"{short_name}: {e}")
        return short_name, None

    # Fetch all in parallel
    cpi_task = _fetch_cpi_yoy()
    gdp_task = _fetch_series("gdp_growth", "A191RL1Q225SBEA")
    unemp_task = _fetch_series("unemployment", "UNRATE")
    rate_task = _fetch_series("interest_rate", "FEDFUNDS")

    cpi_data, gdp_result, unemp_result, rate_result = await asyncio.gather(
        cpi_task, gdp_task, unemp_task, rate_task
    )

    if cpi_data:
        result["indicators"]["cpi_yoy"] = cpi_data
    if gdp_result:
        _, gdp_val = gdp_result
        if gdp_val:
            result["indicators"]["gdp_growth"] = gdp_val
    if unemp_result:
        _, unemp_val = unemp_result
        if unemp_val:
            result["indicators"]["unemployment"] = unemp_val
    if rate_result:
        _, rate_val = rate_result
        if rate_val:
            result["indicators"]["interest_rate"] = rate_val

    result["errors"] = errors if errors else None

    inds = result["indicators"]
    if not inds:
        result["error"] = "FRED_UNAVAILABLE"
        result["derived_regime"] = "UNKNOWN"
        result["regime_inputs"] = {}
    else:
        cpi        = inds.get("cpi_yoy",       {}).get("value", 0) or 0
        gdp_raw    = inds.get("gdp_growth",    {}).get("value", 0) or 0
        rate       = inds.get("interest_rate", {}).get("value", 0) or 0
        rate_trend = inds.get("interest_rate", {}).get("trend", "")
        # A191RL1Q225SBEA is quarterly % change; annualize for regime thresholds
        gdp        = gdp_raw * 4

        regime = _derive_macro_regime(cpi=cpi, gdp=gdp, rate=rate, rate_trend=rate_trend)
        result["derived_regime"] = regime
        result["regime_inputs"]  = {"cpi_yoy": cpi, "gdp_growth": gdp, "policy_rate": rate}

    await _redis_set(key, result, ttl=14400)
    return _cache_set(key, result)




async def get_eodhd_fundamentals(ticker: str, exchange: str = "US") -> dict:
    """
    EODHD equity fundamentals — P/E, EPS, revenue, margins, beta.
    Covers SPY/QQQ/AAPL/MSFT/NVDA/GOOGL/AMZN/META/TSLA/GLD/TLT and others.
    TTL: 6 hours (fundamentals update daily post-close at most)

    ticker: e.g. "SPY", "AAPL", "NVDA"
    exchange: "US" for NYSE/NASDAQ, "TO" for TSX, "LSE" for London, etc.
    """
    if not EODHD_KEY:
        return {"error": "EODHD_API_KEY not set", "ticker": ticker}

    key = f"eodhd_fund_{ticker}_{exchange}"
    cached = _cache_get(key, ttl=21600)   # 6h
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)
    # Negative cache — same reasoning as get_cg_developer_data (S-104): the 6 h
    # TTL above stores successes only, so a failing EODHD was re-attempted for
    # every ticker on every build at 12 s a call.
    neg = _cache_get(f"{key}__neg", ttl=_NEG_TTL_S)
    if neg is None:
        neg = await _redis_get(f"{key}__neg")
    if neg:
        return {"ticker": ticker,
                "error": f"negative-cached: {str(neg.get('error'))[:80]}"}

    client = _get_misc_client()
    try:
        r = await client.get(
            f"{EODHD_BASE}/{ticker}.{exchange}/fundamentals",
            params={
                "fmt": "json",
                "api_token": EODHD_KEY,
                # Fetch only the fields we need — reduce response size
                "filter": ",".join([
                    "General::Code",
                    "General::Type",
                    "General::Sector",
                    "General::Industry",
                    "Highlights::MarketCapitalizationMln",
                    "Highlights::PERatio",
                    "Highlights::ForwardPE",
                    "Highlights::EPS",
                    "Highlights::EPSEstimateNextYear",
                    "Highlights::DividendYield",
                    "Highlights::RevenueGrowthTTM",
                    "Highlights::GrossProfitTTM",
                    "Highlights::EBITDAMrgin",
                    "Technicals::Beta",
                    "Valuation::TrailingPE",
                    "Valuation::ForwardPE",
                    "Valuation::PriceSalesTTM",
                    "Valuation::PriceBookMRQ",
                ]),
            },
            timeout=12,
        )
        r.raise_for_status()
        raw = r.json()

        # Flatten into a clean dict — raw EODHD structure is deeply nested
        hi = raw.get("Highlights", {}) or {}
        tech = raw.get("Technicals", {}) or {}
        val  = raw.get("Valuation",  {}) or {}
        gen  = raw.get("General",    {}) or {}

        result = {
            "ticker":          ticker,
            "exchange":        exchange,
            "type":            gen.get("Type", ""),
            "sector":          gen.get("Sector", ""),
            "industry":        gen.get("Industry", ""),
            "market_cap_mln":  _safe_float(hi.get("MarketCapitalizationMln")),
            "pe_ratio":        _safe_float(hi.get("PERatio") or val.get("TrailingPE")),
            "forward_pe":      _safe_float(hi.get("ForwardPE") or val.get("ForwardPE")),
            "eps":             _safe_float(hi.get("EPS")),
            "eps_next_year":   _safe_float(hi.get("EPSEstimateNextYear")),
            "dividend_yield":  _safe_float(hi.get("DividendYield")),
            "revenue_growth":  _safe_float(hi.get("RevenueGrowthTTM")),
            "gross_profit":    _safe_float(hi.get("GrossProfitTTM")),
            "ebitda_margin":   _safe_float(hi.get("EBITDAMrgin")),  # note: EODHD typo preserved
            "beta":            _safe_float(tech.get("Beta")),
            "price_to_sales":  _safe_float(val.get("PriceSalesTTM")),
            "price_to_book":   _safe_float(val.get("PriceBookMRQ")),
            "source":          "eodhd",
        }
        await _redis_set(key, result, ttl=21600)
        return _cache_set(key, result)
    except Exception as e:
        _neg = {"error": str(e)[:200], "at": int(time.time())}
        _cache_set(f"{key}__neg", _neg)
        await _redis_set(f"{key}__neg", _neg, ttl=_NEG_TTL_S)
        return {"error": str(e), "ticker": ticker}


async def get_eodhd_eod_data(ticker: str, exchange: str = "US") -> Optional[dict]:
    """
    TradFi price + 30d momentum from EODHD end-of-day history.

    Primary TradFi price source — replaces yfinance, which is rate-limited and has
    blocked the portal (2026-06). Returns the SAME shape as cis_provider's
    get_yfinance_data so it's a drop-in: price, change_24h/7d/30d, volume_24h,
    high/low, volatility_30d, market_cap.

    EODHD `/eod/{ticker}.{ex}` returns daily OHLCV: [{date, open, high, low,
    close, adjusted_close, volume}, …] ascending by date.
    TTL: 1h Redis.
    """
    if not EODHD_KEY:
        return None
    key = f"eodhd_eod_{ticker}_{exchange}"
    cached = _cache_get(key, ttl=3600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    from datetime import date, timedelta
    frm = (date.today() - timedelta(days=50)).isoformat()
    client = _get_misc_client()
    try:
        r = await client.get(
            f"{EODHD_BASE}/eod/{ticker}.{exchange}",
            params={"fmt": "json", "api_token": EODHD_KEY, "period": "d", "from": frm},
            timeout=12,
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or len(rows) < 2:
            return None
        closes = [_safe_float(x.get("adjusted_close") or x.get("close")) for x in rows]
        closes = [c for c in closes if c is not None and c > 0]
        if len(closes) < 2:
            return None

        price_now = closes[-1]

        def _chg(n: int) -> float:
            if len(closes) > n:
                ref = closes[-(n + 1)]
                return round((price_now - ref) / ref * 100, 2) if ref else 0.0
            return 0.0

        change_24h = _chg(1)
        change_7d  = _chg(7)
        change_30d = _chg(30)

        # volatility: std of daily returns over the window
        rets = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes)) if closes[i - 1]
        ]
        if rets:
            mean = sum(rets) / len(rets)
            volatility_30d = (sum((x - mean) ** 2 for x in rets) / len(rets)) ** 0.5
        else:
            volatility_30d = 0.0

        last = rows[-1]
        high_24h = _safe_float(last.get("high")) or 0.0
        low_24h  = _safe_float(last.get("low")) or 0.0
        volume_24h = _safe_float(last.get("volume")) or 0.0
        window_high = max(closes)
        ath_chg = round((price_now - window_high) / window_high * 100, 1) if window_high else 0.0

        # Market cap — REQUIRED by the Fundamental pillar (mcap=0 craters F→0 →
        # the whole asset grades F). yfinance used to supply this; EODHD /eod does
        # not, so fetch it from fundamentals (equities: MarketCapitalizationMln;
        # ETFs: ETF_Data.TotalAssets). Best-effort, cached.
        market_cap = 0.0
        try:
            fr = await client.get(
                f"{EODHD_BASE}/fundamentals/{ticker}.{exchange}",
                params={"fmt": "json", "api_token": EODHD_KEY,
                        "filter": "Highlights::MarketCapitalizationMln,ETF_Data::TotalAssets,General::Type"},
                timeout=10,
            )
            if fr.status_code == 200:
                fj = fr.json() or {}
                mc_mln = _safe_float((fj.get("Highlights") or {}).get("MarketCapitalizationMln")
                                     if isinstance(fj.get("Highlights"), dict) else fj.get("MarketCapitalizationMln"))
                etf_aum = _safe_float((fj.get("ETF_Data") or {}).get("TotalAssets")
                                      if isinstance(fj.get("ETF_Data"), dict) else fj.get("TotalAssets"))
                if mc_mln:
                    market_cap = mc_mln * 1e6
                elif etf_aum:
                    market_cap = etf_aum
        except Exception:
            pass
        # Fallback floor: if cap still unknown, estimate from price×volume so the
        # F pillar is never starved to 0 by a missing-data gap.
        if not market_cap and price_now and volume_24h:
            market_cap = price_now * volume_24h * 30   # rough ADV→cap proxy

        result = {
            "symbol":        ticker,
            "price":         price_now,
            "market_cap":    market_cap,
            "volume_24h":    volume_24h,
            "change_24h":    change_24h,
            "high_24h":      high_24h,
            "low_24h":       low_24h,
            "change_7d":     change_7d,
            "change_30d":    change_30d,
            "volatility_30d": round(volatility_30d, 5),
            "circulating_supply": 0,
            "total_supply":  0,
            "ath_change_percentage": ath_chg,
            "source":        "eodhd_eod",
        }
        await _redis_set(key, result, ttl=3600)
        return _cache_set(key, result)
    except Exception as e:
        _logger.warning(f"[EODHD] eod fetch failed for {ticker}.{exchange}: {e}")
        return None


def _safe_float(val) -> Optional[float]:
    """Safely convert EODHD value to float; returns None for null/None/empty."""
    if val is None or val == "" or val == "None":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def get_eodhd_earnings_calendar(symbols: list[str], days_ahead: int = 14) -> list[dict]:
    """
    Upcoming earnings events for a list of tickers (EODHD earnings calendar).
    Useful for S pillar — earnings dates create volatility; pre-earnings premium.
    TTL: 4 hours (calendar doesn't change intraday)

    symbols: ['AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA']
    Returns: [{symbol, report_date, eps_estimate, eps_actual, surprise_pct}, ...]
    """
    if not EODHD_KEY:
        return []

    from datetime import date, timedelta
    today    = date.today()
    end_date = today + timedelta(days=days_ahead)
    key = f"eodhd_earnings_{','.join(sorted(symbols))}_{today.isoformat()}"
    cached = _cache_get(key, ttl=14400)
    if cached:
        return cached

    client = _get_misc_client()
    try:
        r = await client.get(
            f"{EODHD_BASE}/calendar/earnings",
            params={
                "fmt":       "json",
                "api_token": EODHD_KEY,
                "from":      today.isoformat(),
                "to":        end_date.isoformat(),
                "symbols":   ",".join(f"{s}.US" for s in symbols),
            },
            timeout=10,
        )
        r.raise_for_status()
        raw = r.json()
        earnings = raw.get("earnings", []) if isinstance(raw, dict) else raw
        result = []
        for e in earnings:
            result.append({
                "symbol":      e.get("code", "").replace(".US", ""),
                "report_date": e.get("report_date", ""),
                "eps_estimate":  _safe_float(e.get("estimate")),
                "eps_actual":    _safe_float(e.get("actual")),
                "surprise_pct":  _safe_float(e.get("percent")),
                "before_after_market": e.get("before_after_market", ""),
            })
        result.sort(key=lambda x: x["report_date"])
        return _cache_set(key, result)
    except Exception as e:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# COINGECKO PRO — Developer Activity + Exchange Concentration
# Uses COINGECKO_API_KEY (Pro endpoint). Falls back gracefully if not set.
# ══════════════════════════════════════════════════════════════════════════════

async def get_cg_developer_data(coin_id: str) -> dict:
    """
    CoinGecko /coins/{id} — developer_data only.
    Returns commit cadence, issue velocity, contributor count, stars.
    These are direct signals for the F pillar (Fundamental) — active dev = healthier protocol.

    coin_id: CoinGecko ID, e.g. 'solana', 'ethereum', 'chainlink'
    TTL: 24 hours success / _NEG_TTL failure (see below)

    NEGATIVE CACHING (2026-08-07, S-104): failures used to return an error dict
    WITHOUT writing any cache entry, and the bulk caller discarded results
    containing "error". So a 24 h TTL cached successes only. When CoinGecko Pro
    was slow or rate-limiting, all 25 tech assets were re-attempted at 15 s each,
    behind Semaphore(4) = 7 serial waves, on EVERY universe build — and the build
    never finished, so nothing was ever cached, so the next build repeated it.
    A TTL that only caches success is not protection against a provider that is
    down; it is an amplifier. Failures are now cached briefly: pay once, not once
    per build.
    """
    if not CG_API_KEY:
        return {"coin_id": coin_id, "available": False}

    key = f"cg_devdata_{coin_id}"
    cached = _cache_get(key, ttl=86400)    # 24h
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)
    # Short-TTL failure marker — checked separately so it can expire fast while
    # the success entry keeps its 24 h life.
    neg = _cache_get(f"{key}__neg", ttl=_NEG_TTL_S)
    if neg is None:
        neg = await _redis_get(f"{key}__neg")
    if neg:
        return {"coin_id": coin_id, "available": False,
                "error": f"negative-cached: {str(neg.get('error'))[:80]}"}

    client = _get_cg_client()
    try:
        r = await client.get(
            f"{CG_PRO_BASE}/coins/{coin_id}",
            headers=_cg_headers(),
            params={
                "localization":   "false",
                "tickers":        "false",
                "market_data":    "false",
                "community_data": "false",
                "developer_data": "true",
                "sparkline":      "false",
            },
            timeout=15,
        )
        r.raise_for_status()
        raw  = r.json()
        devd = raw.get("developer_data", {}) or {}

        result = {
            "coin_id":                   coin_id,
            "available":                 True,
            "forks":                     devd.get("forks", 0),
            "stars":                     devd.get("stars", 0),
            "subscribers":               devd.get("subscribers", 0),
            "total_issues":              devd.get("total_issues", 0),
            "closed_issues":             devd.get("closed_issues", 0),
            "pull_requests_merged":      devd.get("pull_requests_merged", 0),
            "pull_request_contributors": devd.get("pull_request_contributors", 0),
            "commit_count_4_weeks":      devd.get("commit_count_4_weeks", 0),
            "code_additions_4_weeks":    (devd.get("code_additions_deletions_4_weeks") or {}).get("additions", 0),
            "code_deletions_4_weeks":    (devd.get("code_additions_deletions_4_weeks") or {}).get("deletions", 0),
            "source": "coingecko_pro",
        }

        # Derived dev activity score 0-100
        result["dev_activity_score"] = _score_dev_activity(result)

        await _redis_set(key, result, ttl=86400)
        return _cache_set(key, result)
    except Exception as e:
        # Record the failure so the next build skips this coin instead of paying
        # the full 15 s timeout again. See NEGATIVE CACHING note in the docstring.
        _neg = {"error": str(e)[:200], "at": int(time.time())}
        _cache_set(f"{key}__neg", _neg)
        await _redis_set(f"{key}__neg", _neg, ttl=_NEG_TTL_S)
        return {"coin_id": coin_id, "available": False, "error": str(e)}


def _score_dev_activity(d: dict) -> float:
    """
    Scores developer activity 0-100 based on CoinGecko developer_data.
    Logarithmic scaling — avoids large projects (BTC/ETH) monopolising the score.

    Components (equal weight):
      - commit_count_4_weeks  : 0-100 (log scale, 200 commits = ~90)
      - closed_issues_4_weeks : 0-100 (log scale, 100 closed = ~90)
      - stars                 : 0-100 (log scale, 10k stars = ~90)
      - pr_merged             : 0-100 (log scale, 50 merged/mo = ~90)
    """
    import math

    def log_score(val, midpoint):
        """Maps val to 0-100 with midpoint at ~50."""
        if not val or val <= 0:
            return 0.0
        return min(100.0, 100.0 * math.log1p(val) / math.log1p(midpoint * 4))

    commits     = log_score(d.get("commit_count_4_weeks", 0),      50)
    closed      = log_score(d.get("closed_issues", 0),             200)
    stars       = log_score(d.get("stars", 0),                    5000)
    pr_merged   = log_score(d.get("pull_requests_merged", 0),      100)

    return round((commits + closed + stars + pr_merged) / 4, 1)


async def get_cg_exchange_concentration(coin_id: str) -> dict:
    """
    CoinGecko /coins/{id}/tickers — exchange volume concentration.
    High concentration (>70% on one exchange) = elevated liquidity/custody risk.
    Used in O pillar (on-chain/risk-adjusted) scoring.

    Returns:
      top_exchange: str           — name of exchange with most volume
      top_exchange_pct: float     — % of total volume on that exchange
      exchange_count: int         — number of exchanges listing this asset
      herfindahl_index: float     — 0-1 market concentration index (1 = monopoly)
      risk_flag: bool             — True if top_exchange_pct > 65%
    """
    key = f"cg_exconc_{coin_id}"
    cached = _cache_get(key, ttl=3600)   # 1h
    if cached:
        return cached
    if not CG_API_KEY:
        return {"coin_id": coin_id, "available": False}

    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    client = _get_cg_client()
    try:
        r = await client.get(
            f"{CG_PRO_BASE}/coins/{coin_id}/tickers",
            headers=_cg_headers(),
            params={
                "include_exchange_logo": "false",
                "order":    "volume_desc",
                "per_page": 100,
                "page":     1,
            },
            timeout=15,
        )
        r.raise_for_status()
        tickers = r.json().get("tickers", [])

        # Aggregate volume by exchange
        exchange_vol: dict[str, float] = {}
        for t in tickers:
            ex_name = (t.get("market", {}) or {}).get("name", "Unknown")
            vol_usd = float(t.get("converted_volume", {}).get("usd", 0) or 0)
            exchange_vol[ex_name] = exchange_vol.get(ex_name, 0) + vol_usd

        if not exchange_vol:
            return {"coin_id": coin_id, "available": False}

        total_vol = sum(exchange_vol.values())
        if total_vol == 0:
            return {"coin_id": coin_id, "available": False}

        sorted_ex = sorted(exchange_vol.items(), key=lambda x: x[1], reverse=True)
        top_ex, top_vol = sorted_ex[0]
        top_pct = round(top_vol / total_vol * 100, 1)

        # Herfindahl-Hirschman Index (sum of squared market shares)
        hhi = round(sum((v / total_vol) ** 2 for v in exchange_vol.values()), 4)

        result = {
            "coin_id":          coin_id,
            "available":        True,
            "top_exchange":     top_ex,
            "top_exchange_pct": top_pct,
            "exchange_count":   len(exchange_vol),
            "herfindahl_index": hhi,
            "risk_flag":        top_pct > 65,
            "top_3_exchanges":  [{"exchange": ex, "pct": round(vol / total_vol * 100, 1)}
                                  for ex, vol in sorted_ex[:3]],
            "total_volume_usd": round(total_vol, 0),
            "source": "coingecko_pro",
        }

        await _redis_set(key, result, ttl=3600)
        return _cache_set(key, result)
    except Exception as e:
        return {"coin_id": coin_id, "available": False, "error": str(e)}


async def get_cg_price_history(coin_id: str, days: int = 365) -> dict:
    """
    CoinGecko /coins/{id}/market_chart — full price history.
    Pro key unlocks up to 365 days (free tier capped at 30 days for hourly data).
    Used for: A pillar (90d+ alpha calculation), volatility regime detection.

    Returns: {coin_id, days, prices: [[ts_ms, price], ...], source}
    TTL: 2h Redis (daily candles; intraday not needed here)
    """
    if not CG_API_KEY:
        return {"coin_id": coin_id, "available": False, "reason": "no_pro_key"}

    # Clamp to safe range; Pro supports up to 'max'
    days = min(max(days, 7), 365)
    key = f"cg_history_{coin_id}_{days}d"
    cached = _cache_get(key, ttl=7200)   # 2h
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    client = _get_cg_client()
    try:
        r = await client.get(
            f"{CG_PRO_BASE}/coins/{coin_id}/market_chart",
            headers=_cg_headers(),
            params={
                "vs_currency": "usd",
                "days":        str(days),
                "interval":    "daily",    # daily candles regardless of range
            },
            timeout=20,
        )
        r.raise_for_status()
        raw    = r.json()
        prices = raw.get("prices", [])       # [[timestamp_ms, price], ...]
        volumes = raw.get("total_volumes", [])

        result = {
            "coin_id":     coin_id,
            "available":   True,
            "days":        days,
            "data_points": len(prices),
            "prices":      prices,
            "volumes":     volumes,
            "source":      "coingecko_pro",
        }
        await _redis_set(key, result, ttl=7200)
        return _cache_set(key, result)
    except Exception as e:
        return {"coin_id": coin_id, "available": False, "error": str(e)}


async def get_cg_ohlc_range(coin_id: str, from_ts: int, to_ts: int,
                            interval: str = "daily") -> list[dict]:
    """CoinGecko Pro /coins/{id}/ohlc/range — REAL OHLC candles (S-195, 2026-08-23).

    ⚠️ THIS IS THE ENDPOINT WE SHOULD HAVE BEEN USING ALL ALONG, and not using it
    is what made four months of CoinGecko Pro largely wasted.

    Jazz, 2026-08-23: "coingecko pro 这个数据源还是要价值最大化,现在我们 way
    underused". Measured the same day, that is exactly right and worse than it
    sounds. Every daily bar we store from CoinGecko comes from
    `market_chart/range`, which returns PRICE SAMPLE POINTS, not candles — and
    for short windows it returns them HOURLY regardless of `interval=daily`.
    Collapsing those to a date keeps whichever hour landed last, so our "daily
    close" was never a close. That is why our 08-19 row said BTC +0.30% while
    the venue said +7.15%.

    `/ohlc/range` returns `[ts, open, high, low, close]` — actual candles, and
    `interval=daily` is a PRO-ONLY parameter that is honoured. We pay for it
    monthly and have never called it once.

    WHAT COINGECKO IS FOR, now that Hyperliquid prices execution (S-193). Not
    marks — HL is the venue and its bars are what fills happen against. CG's
    value is BREADTH: ~17,000 assets against HL's 232 perps, plus market cap,
    dominance, categories and trending that no venue provides. It is the
    research and universe-construction source. Those are different jobs and
    conflating them is what produced a price route that could not agree with
    itself.

    Returns [] on any failure — callers must treat empty as "no data", never as
    a flat series.
    """
    if not CG_API_KEY:
        return []

    key = f"cg_ohlc_{coin_id}_{from_ts}_{to_ts}_{interval}"
    cached = _cache_get(key, ttl=7200)
    if cached is not None:
        return cached
    r_cached = await _redis_get(key)
    if r_cached is not None:
        return _cache_set(key, r_cached)

    client = _get_cg_client()
    try:
        r = await client.get(
            f"{CG_PRO_BASE}/coins/{coin_id}/ohlc/range",
            headers=_cg_headers(),
            params={"vs_currency": "usd", "from": from_ts, "to": to_ts,
                    "interval": interval},
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()
        if not isinstance(raw, list):
            return []
        out = []
        for k in raw:
            if not isinstance(k, (list, tuple)) or len(k) < 5:
                continue
            try:
                # The DATE COMES FROM THE CANDLE. Never from the write clock —
                # that is the mistake this whole endpoint switch exists to end.
                d = datetime.fromtimestamp(float(k[0]) / 1000, tz=timezone.utc).date()
                out.append({"trade_date": d.isoformat(),
                            "open": float(k[1]), "high": float(k[2]),
                            "low": float(k[3]), "close": float(k[4])})
            except (TypeError, ValueError):
                continue
        await _redis_set(key, out, ttl=7200)
        return _cache_set(key, out)
    except Exception as e:                                    # noqa: BLE001
        _logger.warning(f"[CG] ohlc/range {coin_id} failed: {e}")
        return []


async def get_cg_market_chart_range(coin_id: str, from_ts: int, to_ts: int, interval: str = None) -> dict:
    """
    CoinGecko Pro /coins/{id}/market_chart/range — prices in a precise unix timestamp window.
    Superior to the `days` endpoint for regime fitness computation: returns ONLY the data
    for the requested window, no over-fetching.

    Args:
        coin_id:  CoinGecko coin ID (e.g. 'bitcoin')
        from_ts:  Unix timestamp (seconds) — window start
        to_ts:    Unix timestamp (seconds) — window end
        interval: Pro-only granularity override ("daily" / "hourly"). None = CoinGecko
                  auto (5m <1d, hourly 1–90d, daily >90d). Pass "daily" for deep
                  multi-year backfills to force daily points + bound payload.

    Returns: {prices: [[ts_ms, price]], volumes: [[ts_ms, vol]], granularity}
    TTL: 2h Redis (historical data doesn't change)
    """
    if not CG_API_KEY:
        return {"available": False, "reason": "no_pro_key"}

    key = f"cg_range_{coin_id}_{from_ts}_{to_ts}_{interval or 'auto'}"
    cached = _cache_get(key, ttl=7200)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    client = _get_cg_client()
    try:
        _params = {"vs_currency": "usd", "from": from_ts, "to": to_ts}
        if interval:
            _params["interval"] = interval
        r = await client.get(
            f"{CG_PRO_BASE}/coins/{coin_id}/market_chart/range",
            headers=_cg_headers(),
            params=_params,
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()
        result = {
            "coin_id":     coin_id,
            "available":   True,
            "from_ts":     from_ts,
            "to_ts":       to_ts,
            "data_points": len(raw.get("prices", [])),
            "prices":      raw.get("prices", []),     # [[ts_ms, price], ...]
            "volumes":     raw.get("total_volumes", []),
            "market_caps": raw.get("market_caps", []),
            "source":      "coingecko_pro",
        }
        await _redis_set(key, result, ttl=7200)
        return _cache_set(key, result)
    except Exception as e:
        return {"coin_id": coin_id, "available": False, "error": str(e)}


async def get_cg_coin_history(coin_id: str, date_str: str) -> dict:
    """
    CoinGecko /coins/{id}/history — snapshot price, market cap, volume at a specific date.
    date_str format: 'DD-MM-YYYY' (CoinGecko format)

    Returns: {price, market_cap, volume_24h, date_str, source}
    TTL: 24h (historical snapshots are immutable)

    Key use cases:
      - Regime fitness: exact price at CIS score timestamp
      - Backtest: reconstruct entry/exit prices for any historical date
    """
    key = f"cg_hist_{coin_id}_{date_str}"
    cached = _cache_get(key, ttl=86400)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    base = CG_PRO_BASE if CG_API_KEY else "https://api.coingecko.com/api/v3"
    client = _get_cg_client()
    try:
        r = await client.get(
            f"{base}/coins/{coin_id}/history",
            headers=_cg_headers(),
            params={"date": date_str, "localization": "false"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        md = data.get("market_data", {})
        result = {
            "coin_id":    coin_id,
            "date_str":   date_str,
            "available":  True,
            "price":      md.get("current_price", {}).get("usd"),
            "market_cap": md.get("market_cap", {}).get("usd"),
            "volume_24h": md.get("total_volume", {}).get("usd"),
            "source":     "coingecko_pro" if CG_API_KEY else "coingecko_free",
        }
        await _redis_set(key, result, ttl=86400)
        return _cache_set(key, result)
    except Exception as e:
        return {"coin_id": coin_id, "date_str": date_str, "available": False, "error": str(e)}


async def get_cg_circulating_supply_chart(coin_id: str, days: int = 30) -> dict:
    """
    CoinGecko Pro /coins/{id}/circulating_supply_chart — supply trend over time.
    Pro-only endpoint. Free tier returns 404.

    Returns supply change data useful for F pillar scoring:
      - Deflationary supply (burns, buybacks) → F pillar boost
      - Rapid supply inflation → F pillar penalty
      - Supply_change_pct: (latest - earliest) / earliest * 100

    TTL: 4h Redis (supply doesn't change rapidly)
    """
    if not CG_API_KEY:
        return {"available": False, "reason": "pro_only"}

    days = min(max(days, 7), 365)
    key = f"cg_supply_{coin_id}_{days}d"
    cached = _cache_get(key, ttl=14400)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    client = _get_cg_client()
    try:
        r = await client.get(
            f"{CG_PRO_BASE}/coins/{coin_id}/circulating_supply_chart",
            headers=_cg_headers(),
            params={"days": str(days)},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json()
        # CG returns [[ts_ms, supply], ...]
        supply_series = raw.get("circulating_supply", [])
        if not supply_series or len(supply_series) < 2:
            return {"coin_id": coin_id, "available": False, "reason": "insufficient_data"}

        supplies = [float(s[1]) for s in supply_series]
        earliest = supplies[0]
        latest   = supplies[-1]
        change_pct = (latest - earliest) / earliest * 100 if earliest > 0 else 0

        result = {
            "coin_id":          coin_id,
            "available":        True,
            "days":             days,
            "supply_earliest":  earliest,
            "supply_latest":    latest,
            "supply_change_pct": round(change_pct, 4),  # negative = deflationary (bullish F)
            "data_points":      len(supply_series),
            "series":           supply_series[-30:],    # last 30 data points for charts
            "source":           "coingecko_pro",
        }
        await _redis_set(key, result, ttl=14400)
        return _cache_set(key, result)
    except Exception as e:
        return {"coin_id": coin_id, "available": False, "error": str(e)}


async def get_cg_coin_tickers(coin_id: str, depth: int = 10) -> dict:
    """
    CoinGecko /coins/{id}/tickers — exchange volume distribution.
    Used for O pillar liquidity concentration scoring:
      - High exchange concentration (top-3 > 80%) → liquidity risk flag
      - Low bid-ask spread → tighter markets → O pillar boost
      - Trust score per exchange: green/yellow/red

    Returns: {exchanges: [{name, volume_usd, trust_score, bid_ask_spread_pct}],
              hhi: Herfindahl–Hirschman Index of volume concentration,
              top3_share_pct: float}
    TTL: 10 min
    """
    base = CG_PRO_BASE if CG_API_KEY else "https://api.coingecko.com/api/v3"
    key = f"cg_tickers_{coin_id}"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    client = _get_cg_client()
    try:
        r = await client.get(
            f"{base}/coins/{coin_id}/tickers",
            headers=_cg_headers(),
            params={"depth": "true", "order": "volume_desc", "page": 1},
            timeout=15,
        )
        r.raise_for_status()
        tickers = r.json().get("tickers", [])

        # Aggregate by exchange
        exchange_vol: dict[str, float] = {}
        exchange_trust: dict[str, str] = {}
        exchange_spread: dict[str, float] = {}
        for t in tickers[:50]:
            mkt = t.get("market", {}).get("name", "Unknown")
            vol = float(t.get("converted_volume", {}).get("usd", 0) or 0)
            exchange_vol[mkt] = exchange_vol.get(mkt, 0) + vol
            exchange_trust[mkt] = t.get("trust_score", "")
            if t.get("bid_ask_spread_percentage"):
                exchange_spread[mkt] = float(t["bid_ask_spread_percentage"])

        total_vol = sum(exchange_vol.values()) or 1
        sorted_exchanges = sorted(exchange_vol.items(), key=lambda x: x[1], reverse=True)[:depth]

        # HHI — sum of squared market shares (0–10000); lower = more distributed
        hhi = sum((vol / total_vol * 100) ** 2 for _, vol in sorted_exchanges)
        top3_share = sum(v for _, v in sorted_exchanges[:3]) / total_vol * 100

        result = {
            "coin_id":       coin_id,
            "available":     True,
            "total_volume_usd": total_vol,
            "exchanges":     [
                {
                    "name":            ex,
                    "volume_usd":      vol,
                    "share_pct":       round(vol / total_vol * 100, 2),
                    "trust_score":     exchange_trust.get(ex, ""),
                    "bid_ask_spread":  exchange_spread.get(ex),
                }
                for ex, vol in sorted_exchanges
            ],
            "hhi":           round(hhi, 1),
            "top3_share_pct": round(top3_share, 2),
            "source":        "coingecko_pro" if CG_API_KEY else "coingecko_free",
        }
        await _redis_set(key, result, ttl=600)
        return _cache_set(key, result)
    except Exception as e:
        return {"coin_id": coin_id, "available": False, "error": str(e)}


async def get_economic_dashboard() -> dict:
    """
    Institutional-grade macro economic dashboard.
    Combines EODHD macro indicators across US/HK/CN in a single call.
    Used by: /api/v1/market/economic-indicators endpoint + MacroBrief pipeline.
    TTL: 4 hours Redis.
    """
    # v3: bumped after adding static scaffold fallback (invalidates old error cache)
    key = "economic_dashboard_v3"
    cached = _cache_get(key, ttl=14400)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    # Try EODHD first, fall back to FRED (free) for USA
    # HK/CN only via EODHD — FRED is US-only
    usa_task = get_eodhd_macro_indicators("usa")
    hkg_task = get_eodhd_macro_indicators("hkg")
    chn_task = get_eodhd_macro_indicators("chn")
    usa, hkg, chn = await asyncio.gather(usa_task, hkg_task, chn_task, return_exceptions=True)

    def _safe(r):
        return r if isinstance(r, dict) else {"error": str(r)}

    us_data = _safe(usa)
    hk_data = _safe(hkg)
    cn_data = _safe(chn)

    # Fall back to FRED for US if EODHD failed
    if us_data.get("error") in ("EODHD_API_KEY not set", "EODHD_MACRO_UNAVAILABLE") or us_data.get("error", "").startswith("EODHD_"):
        fred_data = await _get_fred_macro_indicators("usa")
        if not fred_data.get("error"):
            us_data = fred_data

    # Fallback for HK when EODHD unavailable — World Bank + yfinance (^HSI proxy)
    if hk_data.get("error"):
        hk_fallback = await _get_worldbank_macro("hkg")
        if not hk_fallback.get("error"):
            hk_data = hk_fallback

    # Fallback for CN when EODHD unavailable — World Bank + yfinance (000001.SS proxy)
    if cn_data.get("error"):
        cn_fallback = await _get_worldbank_macro("chn")
        if not cn_fallback.get("error"):
            cn_data = cn_fallback

    # Also try World Bank for US if both EODHD and FRED failed
    if us_data.get("error"):
        us_wb = await _get_worldbank_macro("usa")
        if not us_wb.get("error"):
            us_data = us_wb

    # Last-resort static scaffold — known macro values (updated May 2026)
    # Reflects: Fed at 4.25% (one cut from Q1), PBOC easing cycle ongoing,
    # HK tracking Fed via HKMA peg. Ensures panel always renders.
    _STATIC_FALLBACK = {
        "usa": {"cpi_yoy": 2.4, "gdp_growth": 2.1, "interest_rate": 4.25, "unemployment": 4.2, "pmi": 50.2, "source": "static_may_2026", "derived_regime": "TIGHTENING"},
        "hkg": {"cpi_yoy": 2.0, "gdp_growth": 2.8, "interest_rate": 4.50, "unemployment": 3.0, "pmi": 51.2, "source": "static_may_2026", "derived_regime": "NEUTRAL"},
        "chn": {"cpi_yoy": 0.3, "gdp_growth": 4.9, "interest_rate": 3.10, "unemployment": 5.0, "pmi": 50.4, "source": "static_may_2026", "derived_regime": "EASING"},
    }
    if us_data.get("error"):
        us_data = {**_STATIC_FALLBACK["usa"], "stale": True}
    if hk_data.get("error"):
        hk_data = {**_STATIC_FALLBACK["hkg"], "stale": True}
    if cn_data.get("error"):
        cn_data = {**_STATIC_FALLBACK["chn"], "stale": True}

    # US regime from economic data (used as fallback when Mac Mini isn't pushing)
    us_regime = us_data.get("derived_regime", "UNKNOWN")
    us_inputs = us_data.get("regime_inputs", {})

    source = us_data.get("source", "unknown")

    result = {
        "available":    True,
        "us":           us_data,
        "hk":           hk_data,
        "cn":           cn_data,
        "us_regime":    us_regime,
        "regime_inputs": us_inputs,
        "source":       source,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }
    await _redis_set(key, result, ttl=14400)
    return _cache_set(key, result)
