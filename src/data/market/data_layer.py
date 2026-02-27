"""
Looloomi AI — Unified Data Layer v1.0
Phase 1: Binance (prices) + DeFiLlama (DeFi/TVL) + Alternative.me (F&G) + Moralis (wallets)

All sources are free. No paid API keys required for core functionality.
Moralis requires a free key from moralis.io
Etherscan requires a free key from etherscan.io/myapikey
"""

import os
import time
import httpx
import asyncio
from typing import Optional
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── API Keys (set in Railway environment variables) ───────────────────────────
MORALIS_KEY   = os.getenv("MORALIS_API_KEY", "")
ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "")
HELIUS_KEY    = os.getenv("HELIUS_API_KEY", "")

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
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{BINANCE_BASE}/ticker/24hr", params={"symbol": ticker})
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
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BINANCE_BASE}/klines",
                                 params={"symbol": ticker, "interval": interval, "limit": limit})
            candles = []
            for c in r.json():
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
        async with httpx.AsyncClient(timeout=10) as client:
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
    """Global DeFi TVL and top protocols."""
    key = "defi_overview"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            # Global TVL chart
            r_global = await client.get(f"{LLAMA_BASE}/v2/historicalChainTvl")
            global_tvl = r_global.json()
            current_tvl = global_tvl[-1]["tvl"] if global_tvl else 0

            # Top protocols
            r_protocols = await client.get(f"{LLAMA_BASE}/protocols")
            protocols = r_protocols.json()[:20]  # top 20

            result = {
                "total_tvl_usd": current_tvl,
                "total_tvl_formatted": f"${current_tvl/1e9:.1f}B",
                "top_protocols": [{
                    "name":     p.get("name"),
                    "tvl":      p.get("tvl", 0),
                    "change_1d": p.get("change_1d", 0),
                    "change_7d": p.get("change_7d", 0),
                    "category": p.get("category"),
                    "chains":   p.get("chains", [])[:3],
                } for p in protocols if p.get("tvl", 0) > 0],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


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
        async with httpx.AsyncClient(timeout=12) as client:
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
        async with httpx.AsyncClient(timeout=8) as client:
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

    try:
        async with httpx.AsyncClient(timeout=12) as client:
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
            return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_top_yields(min_tvl: float = 1_000_000, limit: int = 20) -> list[dict]:
    """Top yield farming opportunities filtered by TVL."""
    key = f"yields:{min_tvl}:{limit}"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{LLAMA_YIELDS}/pools")
            pools = r.json().get("data", [])
            filtered = [p for p in pools
                        if (p.get("tvlUsd", 0) >= min_tvl and
                            p.get("apy", 0) > 0 and
                            p.get("apy", 0) < 1000)]  # filter out obviously broken pools
            filtered.sort(key=lambda x: x.get("apy", 0), reverse=True)
            result = [{
                "project":  p.get("project"),
                "chain":    p.get("chain"),
                "symbol":   p.get("symbol"),
                "tvl_usd":  p.get("tvlUsd", 0),
                "apy":      round(p.get("apy", 0), 2),
                "apy_base": round(p.get("apyBase", 0) or 0, 2),
                "apy_reward": round(p.get("apyReward", 0) or 0, 2),
                "pool_id":  p.get("pool"),
            } for p in filtered[:limit]]
            return _cache_set(key, result)
    except Exception as e:
        return [{"error": str(e)}]


async def get_dex_volumes() -> dict:
    """Top DEX volumes from DeFiLlama."""
    key = "dex_volumes"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=12) as client:
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
            return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_protocol_revenues() -> dict:
    """Top protocol fees and revenues (protocol earnings)."""
    key = "revenues"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=12) as client:
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
            return _cache_set(key, result)
    except Exception as e:
        return {"error": str(e)}


async def get_vc_raises(limit: int = 20) -> list[dict]:
    """
    VC funding rounds from DeFiLlama.
    Note: /raises endpoint requires Pro for full data.
    This uses the free protocols endpoint with embedded raise data.
    """
    key = f"vc_raises:{limit}"
    cached = _cache_get(key, ttl=3600)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{LLAMA_BASE}/protocols")
            protocols = r.json()

        raises = []
        for p in protocols:
            for raise_event in p.get("raises", []):
                raises.append({
                    "project":    p.get("name"),
                    "category":   p.get("category"),
                    "chains":     p.get("chains", [])[:3],
                    "amount_usd": raise_event.get("amount", 0),
                    "round":      raise_event.get("round"),
                    "date":       raise_event.get("date"),
                    "investors":  raise_event.get("leadInvestors", []) + raise_event.get("otherInvestors", []),
                    "source":     "defillama",
                })

        raises.sort(key=lambda x: x.get("date", 0) or 0, reverse=True)
        result = raises[:limit]
        return _cache_set(key, result)
    except Exception as e:
        return [{"error": str(e)}]


# ══════════════════════════════════════════════════════════════════════════════
# ALTERNATIVE.ME — Fear & Greed Index (free, no key, full history)
# ══════════════════════════════════════════════════════════════════════════════

async def get_fear_greed(limit: int = 30) -> dict:
    """Crypto Fear & Greed Index. limit=1 for current, limit=30 for history."""
    key = f"fng:{limit}"
    cached = _cache_get(key, ttl=3600)  # updates daily
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://api.alternative.me/fng/?limit={limit}")
            data = r.json().get("data", [])
            result = {
                "current": {
                    "value":       int(data[0]["value"]),
                    "label":       data[0]["value_classification"],
                    "timestamp":   data[0]["timestamp"],
                } if data else {},
                "history": [{
                    "value":     int(d["value"]),
                    "label":     d["value_classification"],
                    "timestamp": d["timestamp"],
                    "date":      datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
                } for d in data],
                "source": "alternative.me",
            }
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
        async with httpx.AsyncClient(timeout=15) as client:
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
        async with httpx.AsyncClient(timeout=15) as client:
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
        async with httpx.AsyncClient(timeout=15) as client:
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
        async with httpx.AsyncClient(timeout=10) as client:
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
            "STRONG BUY"  if mmi_score >= 75 else
            "BUY"         if mmi_score >= 60 else
            "NEUTRAL"     if mmi_score >= 40 else
            "SELL"        if mmi_score >= 25 else
            "STRONG SELL"
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
