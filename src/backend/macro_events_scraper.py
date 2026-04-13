"""
Macro events scraper — pulls upcoming/recent events from public RSS/JSON feeds.
Sources: CoinDesk, CoinTelegraph, Decrypt, Fed calendar.
Cached in-process for 30 min to avoid hammering RSS feeds.
"""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

_CACHE: dict = {"data": [], "at": 0.0}
_TTL = 1800  # 30 min

# RSS feeds with macro relevance
_RSS_FEEDS = [
    {
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "source": "CoinDesk",
        "category": "crypto",
    },
    {
        "url": "https://cointelegraph.com/rss",
        "source": "CoinTelegraph",
        "category": "crypto",
    },
    {
        "url": "https://decrypt.co/feed",
        "source": "Decrypt",
        "category": "crypto",
    },
]

# Keywords to flag as macro-relevant
_MACRO_KEYWORDS = [
    "fed", "federal reserve", "fomc", "rate", "inflation", "cpi", "gdp",
    "treasury", "yield", "bitcoin", "crypto", "sec", "regulation", "etf",
    "powell", "interest rate", "monetary policy", "recession", "macro",
    "halving", "etf approval", "institutional", "blackrock", "vanguard",
]


def _is_macro_relevant(title: str, summary: str = "") -> bool:
    text = (title + " " + summary).lower()
    return any(kw in text for kw in _MACRO_KEYWORDS)


async def _fetch_rss(feed: dict, client: httpx.AsyncClient) -> list:
    """Fetch and parse a single RSS feed. Returns list of event dicts."""
    events = []
    try:
        r = await client.get(feed["url"], timeout=8, follow_redirects=True)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
        channel = root.find("channel")
        if channel is None:
            return []
        items = channel.findall("item")[:15]  # cap at 15 per feed
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date_str = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()[:300]

            if not title or not _is_macro_relevant(title, description):
                continue

            # Parse pubDate → ISO timestamp (best effort)
            ts = None
            if pub_date_str:
                try:
                    from email.utils import parsedate_to_datetime
                    ts = parsedate_to_datetime(pub_date_str).isoformat()
                except Exception:
                    ts = None

            events.append({
                "title": title,
                "url": link,
                "source": feed["source"],
                "category": feed["category"],
                "published_at": ts,
                "summary": description,
                "type": "news",
            })
    except Exception as e:
        logger.warning(f"[macro_events] RSS fetch failed for {feed['source']}: {e}")
    return events


async def fetch_all_macro_events() -> list:
    """
    Fetch macro-relevant events from RSS feeds.
    Returns deduplicated, sorted list (newest first).
    Caches for 30 min.
    """
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["at"]) < _TTL:
        return _CACHE["data"]

    all_events = []
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "CometCloud/1.0 macro-events-bot"},
            timeout=10,
        ) as client:
            results = await asyncio.gather(
                *[_fetch_rss(feed, client) for feed in _RSS_FEEDS],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, list):
                    all_events.extend(result)

        # Deduplicate by title prefix (first 60 chars)
        seen: set = set()
        deduped = []
        for ev in all_events:
            key = ev["title"][:60].lower()
            if key not in seen:
                seen.add(key)
                deduped.append(ev)

        # Sort: items with timestamp first (newest), then those without
        def _sort_key(e):
            ts = e.get("published_at")
            if ts:
                try:
                    return datetime.fromisoformat(ts).timestamp()
                except Exception:
                    pass
            return 0.0

        deduped.sort(key=_sort_key, reverse=True)
        _CACHE["data"] = deduped[:50]  # cap at 50 total
        _CACHE["at"] = now
        logger.info(f"[macro_events] fetched {len(deduped)} events from {len(_RSS_FEEDS)} feeds")
    except Exception as e:
        logger.error(f"[macro_events] fetch_all_macro_events failed: {e}")
        # Return stale cache rather than empty
        return _CACHE["data"]

    return _CACHE["data"]
