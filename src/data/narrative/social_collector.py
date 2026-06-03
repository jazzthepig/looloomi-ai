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

    CG_BASE = "https://api.coingecko.com/api/v3"
    headers = {}

    try:
        client = _get_cg_client()
        r = await client.get(f"{CG_BASE}/coins/{coin_id}/community_data")
        r.raise_for_status()
        data = r.json()

        result = {
            "coin_id":          coin_id,
            "twitter_followers": data.get("twitter_followers", 0) or 0,
            "reddit_subscribers": data.get("reddit_subscribers", 0) or 0,
            "reddit_active_48h":  data.get("reddit_active_users", 0) or 0,
            "telegram_users":    data.get("telegram_channel_user_count", 0) or 0,
            "github_stars":      data.get("stars", 0) or 0,
            "github_forks":      data.get("forks", 0) or 0,
            "github_contributors": data.get("subscribers", 0) or 0,
            "facebook_likes":    data.get("facebook_likes", 0) or 0,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
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

    # Normalize twitter followers to 0-100 (log scale, cap at 10M = 100)
    twitter_raw = cg_data.get("twitter_followers", 0) or 0
    twitter_score = min(100, round(100 * (1 - 1 / (1 + twitter_raw / 1_000_000)), 1)) if twitter_raw else 25.0

    # Normalize reddit subscribers (cap at 5M = 100)
    reddit_raw  = cg_data.get("reddit_subscribers", 0) or 0
    reddit_score = min(100, round(100 * (1 - 1 / (1 + reddit_raw / 500_000)), 1)) if reddit_raw else 25.0

    # News sentiment is already 0-100
    news_sentiment = news.get("sentiment_score", 50.0) or 50.0

    # Weighted composite
    social_score = round(
        twitter_score  * 0.30 +
        reddit_score   * 0.30 +
        news_sentiment * 0.40,
        1,
    )

    result = {
        "coin_id":        coin_id,
        "social_score":   social_score,
        "twitter_score":  twitter_score,
        "reddit_score":   reddit_score,
        "news_sentiment": news_sentiment,
        "twitter_raw":    twitter_raw,
        "reddit_raw":     reddit_raw,
        "news_total":     news.get("total_count", 0),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
    return _cache_set(key, result)


# ── Google Trends (pytrends) — narrative heat ──────────────────────────────────

async def get_google_trend_score(keyword: str, days: int = 7) -> dict:
    """
    Fetch Google Trends interest over past N days.
    Returns trend_score 0-100.

    NOTE: Requires `pytrends` package. Falls back gracefully if not available.
    Cache TTL: 3600s (1 hour)

    Usage:
        await get_google_trend_score("bitcoin", days=7)
    """
    key = f"gtrends:{keyword}:{days}"
    cached = _cache_get(key, ttl=3600)
    if cached:
        return cached

    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=360)
        pt.build_payload([keyword], cat=0, timeframe=f"now {days}-d", geo="")
        data = pt.interest_over_time()

        if data.empty:
            raise ValueError("Empty response")

        values = data[keyword].dropna().tolist()
        if not values:
            raise ValueError("No data after dropna")

        # Average interest over period — normalize 0-100
        avg_interest = sum(values) / len(values)
        trend_score  = round(min(100, avg_interest), 1)

        result = {
            "keyword":     keyword,
            "trend_score": trend_score,
            "raw_values":  [round(v, 1) for v in values[-14:]],
            "period_avg":  round(avg_interest, 2),
            "days":        days,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        return _cache_set(key, result)

    except ImportError:
        return {
            "keyword": keyword,
            "trend_score": 50.0,
            "error": "pytrends not installed",
            "days": days,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        _logger.warning(f"[social_collector] Google Trends failed for '{keyword}': {e}")
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