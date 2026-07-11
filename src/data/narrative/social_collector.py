"""
Narrative Data Collectors — Social, Orderflow, Trend
Collects narrative signals from multiple free sources:
  - CoinGecko community_data (Twitter/Reddit/Facebook/GitHub)
  - CryptoPanic RSS news aggregator
  - Binance orderbook depth (already in data_layer.py)

Author: CometCloud Intelligence
"""

import json
import time
import asyncio
import logging
import os
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional

_logger = logging.getLogger(__name__)

# ── Clients ────────────────────────────────────────────────────────────────────

_cg_client: httpx.AsyncClient | None = None
_misc_client: httpx.AsyncClient | None = None

_POOL_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)

def _get_cg_client() -> httpx.AsyncClient:
    global _cg_client
    if _cg_client is None or _cg_client.is_closed:
        _cg_client = httpx.AsyncClient(timeout=12, limits=_POOL_LIMITS)
    return _cg_client

def _get_misc_client() -> httpx.AsyncClient:
    global _misc_client
    if _misc_client is None or _misc_client.is_closed:
        _misc_client = httpx.AsyncClient(timeout=10, limits=_POOL_LIMITS)
    return _misc_client

# ── Simple in-memory TTL cache ───────────────────────────────────────────────

_cache: dict = {}

def _cache_get(key: str, ttl: int = 300):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < ttl:
            return val
    return None

def _cache_set(key: str, val):
    _cache[key] = (val, time.time())
    return val


# ── CoinGecko community data ───────────────────────────────────────────────────

async def fetch_cg_community_data(coin_id: str) -> dict:
    """
    Fetch community metrics from CoinGecko.
    Fields: twitter_followers, telegram_channel_users, reddit_subscribers,
            facebook_likes, github_stars, etc.
    Cache TTL: 600s (10 minutes)
    """
    key = f"cg_community:{coin_id}"
    cached = _cache_get(key, ttl=600)
    if cached:
        return cached

    # Use the PRO base + key when available (matches data_layer.py). community_data is a
    # FIELD inside /coins/{id}, NOT a /community_data sub-route (that 404s on every tier).
    # CG deprecated the social-media fields (twitter/telegram/facebook = null); the LIVE,
    # real signals on this endpoint are developer_data + sentiment_votes_up_percentage.
    _KEY = os.getenv("COINGECKO_API_KEY", "")
    CG_BASE = "https://pro-api.coingecko.com/api/v3" if _KEY else "https://api.coingecko.com/api/v3"
    headers = {"x-cg-pro-api-key": _KEY} if _KEY else {}

    try:
        client = _get_cg_client()
        r = await client.get(
            f"{CG_BASE}/coins/{coin_id}",
            params={"localization": "false", "tickers": "false", "market_data": "false",
                    "community_data": "true", "developer_data": "true", "sparkline": "false"},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        cd = data.get("community_data", {}) or {}
        dd = data.get("developer_data", {}) or {}

        result = {
            "coin_id":            coin_id,
            # live developer momentum (the alive signal)
            "github_stars":       dd.get("stars", 0) or 0,
            "github_forks":       dd.get("forks", 0) or 0,
            "github_subscribers": dd.get("subscribers", 0) or 0,
            "commits_4w":         dd.get("commit_count_4_weeks", 0) or 0,
            "total_issues":       dd.get("total_issues", 0) or 0,
            # CG's own community sentiment vote (alive)
            "sentiment_up_pct":   data.get("sentiment_votes_up_percentage") or 50.0,
            # reddit may still carry a signal for some coins; social-media fields mostly null now
            "reddit_subscribers": cd.get("reddit_subscribers", 0) or 0,
            "reddit_active_48h":  cd.get("reddit_accounts_active_48h", 0) or 0,
            "timestamp":          datetime.now(timezone.utc).isoformat(),
        }
        return _cache_set(key, result)

    except Exception as e:
        _logger.warning(f"[social_collector] CG community fetch failed for {coin_id}: {e}")
        return {"coin_id": coin_id, "error": str(e)}


# ── CryptoPanic RSS news sentiment ────────────────────────────────────────────

CRYPTO_PANIC_RSS = "https://cryptopanic.com/news/rss/"

# Known crypto news keywords for basic sentiment scoring
_POSITIVE_KW = [
    "bullish", "breakout", "surge", "rally", "all-time", "new high",
    "adoption", "upgrade", "partnership", "approve", "approval", "launch",
    "record", "soar", "gain",
]
_NEGATIVE_KW = [
    "crash", "plunge", "selloff", "bearish", "drop", "warn", "probe",
    "hack", "exploit", "scam", "fraud", "ban", "regulation", "investigation",
    "hack", "warning", "risk", "correction",
]

async def fetch_news_sentiment(coin_id: str = None, min_posts: int = 5) -> dict:
    """
    Fetch recent news from CryptoPanic RSS and compute basic sentiment score.
    Returns: {sentiment_score (0-100), positive_count, negative_count, total_count}
    Cache TTL: 300s (5 minutes)
    """
    key = f"news_sentiment:{coin_id or 'all'}"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    try:
        client = _get_misc_client()
        r = await client.get(CRYPTO_PANIC_RSS, timeout=15)
        r.raise_for_status()
        xml_text = r.text

        # Parse basic RSS — just look for <title>...</title>
        import re
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", xml_text)
        if not titles:
            titles = re.findall(r"<title>(.*?)</title>", xml_text)

        if not titles:
            return _cache_set(key, {
                "coin_id": coin_id,
                "sentiment_score": 50,
                "positive_count": 0,
                "negative_count": 0,
                "total_count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        positive = sum(1 for t in titles if any(kw in t.lower() for kw in _POSITIVE_KW))
        negative = sum(1 for t in titles if any(kw in t.lower() for kw in _NEGATIVE_KW))
        total    = len(titles)

        # Sentiment score: 50 neutral, 100 all positive, 0 all negative
        sentiment_score = 50 + 50 * (positive - negative) / max(total, 1)

        result = {
            "coin_id":         coin_id,
            "sentiment_score": round(sentiment_score, 1),
            "positive_count": positive,
            "negative_count": negative,
            "total_count":    total,
            "recent_titles":  titles[:5],
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        }
        return _cache_set(key, result)

    except Exception as e:
        _logger.warning(f"[social_collector] CryptoPanic fetch failed: {e}")
        return {
            "coin_id": coin_id,
            "sentiment_score": 50,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Social score aggregation ───────────────────────────────────────────────────

async def get_social_signals(coin_id: str) -> dict:
    """
    Aggregate CoinGecko community_data + CryptoPanic news sentiment.
    Returns composite social_score (0-100) and sub-scores.

    Sub-scores:
      twitter_score: 30% weight
      reddit_score: 30% weight
      news_sentiment: 40% weight
    """
    key = f"social_signal:{coin_id}"
    cached = _cache_get(key, ttl=300)
    if cached:
        return cached

    cg_data = await fetch_cg_community_data(coin_id)
    news    = await fetch_news_sentiment(coin_id)

    if "error" in cg_data and "error" in news:
        return {
            "coin_id": coin_id,
            "social_score": 50.0,
            "twitter_score": 50.0,
            "reddit_score": 50.0,
            "news_sentiment": 50.0,
            "error": "both sources failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # LIVE signals (CG social-media fields are deprecated/null — see fetch above):
    # 1) developer momentum — commits over 4 weeks (real dev activity)
    commits = cg_data.get("commits_4w", 0) or 0
    dev_score = min(100, round(100 * (1 - 1 / (1 + commits / 50.0)), 1)) if commits else 25.0
    # 2) CoinGecko community sentiment vote (alive, 0-100)
    sentiment_vote = float(cg_data.get("sentiment_up_pct", 50.0) or 50.0)
    # 3) reddit activity if present (many coins now 0)
    reddit_raw  = cg_data.get("reddit_subscribers", 0) or 0
    reddit_score = min(100, round(100 * (1 - 1 / (1 + reddit_raw / 500_000)), 1)) if reddit_raw else 25.0
    # 4) news sentiment (CryptoPanic, already 0-100)
    news_sentiment = news.get("sentiment_score", 50.0) or 50.0

    # Weighted composite — news + community vote + developer momentum are the live drivers
    social_score = round(
        news_sentiment * 0.40 +
        sentiment_vote * 0.35 +
        dev_score      * 0.20 +
        reddit_score   * 0.05,
        1,
    )

    result = {
        "coin_id":        coin_id,
        "social_score":   social_score,
        # kept keys (twitter/reddit) for schema stability; twitter is retired → dev momentum
        "twitter_score":  dev_score,          # repurposed: developer-momentum score
        "reddit_score":   reddit_score,
        "news_sentiment": news_sentiment,
        "sentiment_vote": sentiment_vote,
        "dev_commits_4w": commits,
        "news_total":     news.get("total_count", 0),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
    return _cache_set(key, result)


# ── Attention / trend heat (Binance volume+price momentum — replaces dead pytrends) ──

_BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
_TREND_SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT",
    "XRP": "XRPUSDT", "DOGE": "DOGEUSDT", "ADA": "ADAUSDT", "AVAX": "AVAXUSDT",
    "LINK": "LINKUSDT", "HYPE": "HYPEUSDT", "SUI": "SUIUSDT", "APT": "APTUSDT",
    "ARB": "ARBUSDT", "OP": "OPUSDT", "UNI": "UNIUSDT", "AAVE": "AAVEUSDT",
}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


async def get_google_trend_score(keyword: str, days: int = 7) -> dict:
    """Attention/trend heat from REAL market data (Binance volume + price momentum) —
    the actual footprint of narrative heat. Replaces Google Trends/pytrends, which
    rate-limits (429) and returned a flat 50 for everything. Name kept for call-site
    compatibility; `keyword` is the asset symbol (e.g. "BTC").

    trend_score 0-100: 50 = neutral; rising = volume surge + positive price momentum
    (attention building), falling = quiet + negative momentum. Cache TTL 1800s.
    """
    sym = (keyword or "").upper()
    ticker = _TREND_SYMBOL_MAP.get(sym, f"{sym}USDT")
    key = f"attention:{ticker}"
    cached = _cache_get(key, ttl=1800)
    if cached:
        return cached

    try:
        client = _get_misc_client()
        r = await client.get(f"{_BINANCE_FAPI}/klines",
                             params={"symbol": ticker, "interval": "1d", "limit": 40})
        r.raise_for_status()
        kl = r.json()
        if not kl or len(kl) < 15:
            raise ValueError("insufficient klines")

        close = [float(k[4]) for k in kl]
        qvol  = [float(k[7]) for k in kl]          # quote (USD) volume

        base = qvol[:-3]
        import statistics
        vmean = statistics.mean(base); vstd = statistics.pstdev(base) or 1e-9
        vol_z = (statistics.mean(qvol[-3:]) - vmean) / vstd     # recent 3d vs baseline
        price_mom_7d = (close[-1] - close[-8]) / close[-8] if len(close) >= 8 else 0.0

        # attention rises with volume surge AND positive momentum; both directions matter
        trend_score = round(_clamp(50 + 12.0 * _clamp(vol_z, -3, 3) + 60.0 * _clamp(price_mom_7d, -0.5, 0.5), 0, 100), 1)

        result = {
            "keyword":      sym,
            "trend_score":  trend_score,
            "volume_z":     round(vol_z, 2),
            "price_mom_7d": round(price_mom_7d * 100, 1),
            "source":       "binance_vol_price_momentum",
            "days":         days,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }
        return _cache_set(key, result)

    except Exception as e:
        _logger.warning(f"[social_collector] attention/trend fetch failed for '{keyword}': {e}")
        return {
            "keyword": keyword,
            "trend_score": 50.0,
            "error": str(e),
            "days": days,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Batch social signals for multiple assets ───────────────────────────────────

COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
    "AVAX": "avalanche-2", "DOT": "polkadot", "NEAR": "near",
    "SUI": "sui", "APT": "aptos", "HYPE": "hyperliquid",
    "ARB": "arbitrum", "OP": "optimism", "LINK": "chainlink",
    "UNI": "uniswap", "AAVE": "aave", "MKR": "maker",
}


async def batch_social_signals(symbols: list[str] = None) -> dict[str, dict]:
    """
    Fetch social signals for multiple assets in parallel.
    Returns: {symbol: social_signal_dict}
    """
    targets = symbols or list(COINGECKO_IDS.keys())
    coin_ids = {s: COINGECKO_IDS.get(s, s.lower()) for s in targets}

    async def _one(sym):
        return sym, await get_social_signals(coin_ids[sym])

    results = {}
    for sym, sig in await asyncio.gather(*[_one(s) for s in targets]):
        results[sym] = sig
    return results


if __name__ == "__main__":
    async def _test():
        logging.basicConfig(level=logging.INFO)
        print("=== Social Signals (BTC) ===")
        print(await get_social_signals("bitcoin"))
        print("\n=== News Sentiment ===")
        print(await fetch_news_sentiment())
        print("\n=== Google Trends (bitcoin, 7d) ===")
        print(await get_google_trend_score("bitcoin", days=7))
        print("\n=== Batch (BTC, ETH, SOL) ===")
        print(await batch_social_signals(["BTC", "ETH", "SOL"]))

    asyncio.run(_test())