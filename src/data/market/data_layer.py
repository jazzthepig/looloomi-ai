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
        _llama_client = httpx.AsyncClient(timeout=15, limits=_POOL_LIMITS)
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
    """Write to Upstash with TTL. Fire-and-forget style (non-blocking on failure)."""
    if not _UPSTASH_URL:
        return False
    try:
        client = _get_redis_client()
        r = await client.post(
            f"{_UPSTASH_URL}/set/{key}",
            content=json.dumps(val),
            headers={
                "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                "Content-Type": "application/json",
            },
            params={"EX": ttl},
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
            "arbitrum", "optimism", "base", "zksync era", "scroll",
            "starknet", "linea", "mantle", "blast", "mode", "manta", "taiko",
        }
        l2_tvl = 0.0
        if not isinstance(chains_r, Exception) and chains_r.status_code == 200:
            chains_data = chains_r.json()
            for ch in chains_data:
                if (ch.get("name") or "").lower() in L2_CHAINS:
                    l2_tvl += ch.get("tvl") or 0

        # ── Top protocols ─────────────────────────────────────────────────────
        protocols = []
        if not isinstance(proto_r, Exception) and proto_r.status_code == 200:
            all_protos = proto_r.json()
            protocols  = all_protos[:20]

        # ── RWA TVL — filter protocols by category ────────────────────────────
        rwa_tvl = 0.0
        rwa_change_24h = 0.0
        if not isinstance(proto_r, Exception) and proto_r.status_code == 200:
            rwa_protos = [p for p in all_protos if (p.get("category") or "").lower() == "rwa"]
            rwa_tvl = sum(p.get("tvl") or 0 for p in rwa_protos)
            if rwa_protos:
                rwa_changes = [p.get("change_1d") or 0 for p in rwa_protos if p.get("change_1d") is not None]
                if rwa_changes:
                    rwa_change_24h = round(sum(rwa_changes) / len(rwa_changes), 2)

        result = {
            "total_tvl_usd": current_tvl,
            "total_tvl":     current_tvl,   # alias used by IntelligencePage
            "total_tvl_formatted": f"${current_tvl/1e9:.1f}B",
            "defi_change_24h": defi_change_24h,
            "l2_tvl":          l2_tvl,
            "l2_change_24h":   0.0,          # chain-level 24h delta not in /v2/chains
            "rwa_tvl":         rwa_tvl,
            "rwa_change_24h":  rwa_change_24h,
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
    VC funding rounds via DeFiLlama /raises endpoint.
    Returns up to `limit` rounds sorted by date desc, last 180 days.
    Amount is returned in USD (DeFiLlama stores in $M; we multiply ×1M).
    TTL: 1h in-memory + 1h Redis.
    """
    key = f"vc_raises_v3:{limit}"
    cached = _cache_get(key, ttl=3600)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    try:
        client = _get_llama_client()
        resp = await client.get("https://api.llama.fi/raises", timeout=25)
        resp.raise_for_status()
        data = resp.json()

        raw = data.get("raises", [])
        cutoff = datetime.now(timezone.utc).timestamp() - 180 * 86400

        raises = []
        for r in raw:
            raw_amount = r.get("amount") or 0   # DeFiLlama: $M
            date_ts    = r.get("date") or 0
            if raw_amount <= 0 or date_ts < cutoff:
                continue

            lead  = r.get("leadInvestors") or []
            other = r.get("otherInvestors") or []

            raises.append({
                # Frontend reads: name, amount (USD), round, date, category, leadInvestors, investors, chains
                "name":          r.get("name") or r.get("project") or "Unknown",
                "amount":        int(raw_amount * 1_000_000),   # → USD for frontend /1M display
                "round":         r.get("round") or r.get("roundType") or "—",
                "date":          date_ts,                        # Unix timestamp seconds
                "category":      r.get("category") or "DeFi",
                "categoryGroup": r.get("category") or "DeFi",
                "sector":        r.get("sector") or r.get("category") or "DeFi",
                "chains":        (r.get("chains") or [])[:3],
                "leadInvestors": lead,
                "investors":     lead + other,
                "description":   (r.get("description") or "")[:200],
                "source":        "defillama",
            })

        raises.sort(key=lambda x: x.get("date", 0) or 0, reverse=True)
        result = raises[:limit]
        await _redis_set(key, result, ttl=3600)
        return _cache_set(key, result)
    except Exception as e:
        _logger.warning(f"[VC_RAISES] Error: {e}")
        return []


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
                "price_change_percentage": "7d",
                "per_page": 250,
                "page": 1,
            },
        )
        r.raise_for_status()
        result = r.json()
        return _cache_set(key, result)
    except Exception as e:
        _logger.warning(f"[CG_MARKETS] Error: {e}")
        return []


async def get_cg_derivatives() -> list:
    """
    CoinGecko derivatives tickers — funding rates and open interest.
    Focuses on BTC and ETH perpetuals.
    Returns list of {symbol, funding_rate, open_interest_usd, price_change_24h}.
    TTL: 5 min.
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
        r = await client.get(f"{CG_PRO_BASE}/derivatives",
                             headers=_cg_headers(),
                             params={"include_tickers": "unexpired"})
        r.raise_for_status()
        tickers = r.json()
        # Focus on BTC and ETH perpetuals with meaningful OI
        targets = {"BTC", "ETH", "SOL"}
        result  = []
        seen    = set()
        for t in tickers:
            sym = (t.get("base") or "").upper()
            if sym not in targets:
                continue
            key_str = f"{sym}:{t.get('market','')}"
            if key_str in seen:
                continue
            seen.add(key_str)
            fr = t.get("funding_rate")
            oi = t.get("open_interest_usd") or t.get("open_interest")
            result.append({
                "symbol":            sym,
                "market":            t.get("market", ""),
                "price":             float(t.get("last") or 0),
                "funding_rate":      float(fr) if fr is not None else None,
                "open_interest_usd": float(oi) if oi is not None else None,
                "price_change_pct":  float(t.get("price_percentage_change_24h") or 0),
                "contract_type":     t.get("contract_type", ""),
            })
            if len(result) >= 9:  # 3 per asset × 3 assets
                break
        await _redis_set(key, result, ttl=300)
        return _cache_set(key, result)
    except Exception as e:
        return []


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
            if cid not in _VC_CAT_IDS:
                continue
            mcap   = cat.get("market_cap") or 0
            chg24  = cat.get("market_cap_change_24h") or 0
            vol24  = cat.get("volume_24h") or 0
            top3   = cat.get("top_3_coins_id") or cat.get("top_3_coins") or []
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
            "fear_greed_label":      _fg_lbl,
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
        except Exception:
            pass  # regime stays UNKNOWN — non-blocking

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
    - Price momentum (25%) — Binance, free
    - DeFi TVL trend (20%) — DeFiLlama, free
    - DEX volume trend (15%) — DeFiLlama, free
    - Market dominance (15%) — DeFiLlama stablecoins, free
    """
    key = f"mmi:{token}"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    try:
        fg_data, price_data, tvl_data, dex_data = await asyncio.gather(
            get_fear_greed(limit=7),
            get_price(token),
            get_defi_overview(),
            get_dex_volumes(),
        )

        # Component 1: Fear & Greed (0-100)
        fg_score = fg_data.get("current", {}).get("value", 50)

        # Component 2: Price momentum (7-day trend → 0-100)
        price_change = price_data.get("change_24h", 0) if price_data else 0
        momentum_score = min(100, max(0, 50 + price_change * 2.5))

        # Component 3: DeFi TVL health (simplified → use 50 as baseline if data unavailable)
        tvl_score = 55.0  # placeholder — expand with TVL trend calculation

        # Component 4: DEX volume relative to baseline
        dex_volume = dex_data.get("total_24h", 0)
        dex_score = min(100, max(20, 40 + (dex_volume / 1e9) * 2)) if dex_volume else 50

        # Component 5: Stablecoin dominance (high dominance → fear)
        stable_score = 50.0  # placeholder

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
                "stablecoin":    round(stable_score, 1),
            },
            "fear_greed_label": fg_data.get("current", {}).get("label", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": ["alternative.me", "binance", "defillama"],
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
        return {"error": str(e), "ticker": ticker}


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
    TTL: 24 hours (GitHub stats update once/day on CoinGecko)
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


async def get_economic_dashboard() -> dict:
    """
    Institutional-grade macro economic dashboard.
    Combines EODHD macro indicators across US/HK/CN in a single call.
    Used by: /api/v1/market/economic-indicators endpoint + MacroBrief pipeline.
    TTL: 4 hours Redis.
    """
    key = "economic_dashboard"
    cached = _cache_get(key, ttl=14400)
    if cached:
        return cached
    r_cached = await _redis_get(key)
    if r_cached:
        return _cache_set(key, r_cached)

    if not EODHD_KEY:
        return {"available": False, "reason": "EODHD_API_KEY not set in Railway env vars"}

    # Fetch US, HK, CN indicators in parallel
    usa, hkg, chn = await asyncio.gather(
        get_eodhd_macro_indicators("usa"),
        get_eodhd_macro_indicators("hkg"),
        get_eodhd_macro_indicators("chn"),
        return_exceptions=True,
    )

    def _safe(r):
        return r if isinstance(r, dict) else {"error": str(r)}

    us_data  = _safe(usa)
    hk_data  = _safe(hkg)
    cn_data  = _safe(chn)

    # US regime from economic data (used as fallback when Mac Mini isn't pushing)
    us_regime = us_data.get("derived_regime", "UNKNOWN")
    us_inputs = us_data.get("regime_inputs", {})

    result = {
        "available":    True,
        "us":           us_data,
        "hk":           hk_data,
        "cn":           cn_data,
        "us_regime":    us_regime,
        "regime_inputs": us_inputs,
        "source":       "eodhd",
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }
    await _redis_set(key, result, ttl=14400)
    return _cache_set(key, result)
