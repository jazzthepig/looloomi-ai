"""
Macro events scraper — macro-relevant events from multiple reliable sources.

Sources (priority order):
  1. DeFiLlama Raises — always available on Railway, feeds INSTITUTIONAL events
  2. RSS feeds (CoinDesk, CoinTelegraph, Decrypt) — best-effort; US cloud IPs
     frequently get rate-limited/blocked, so RSS is treated as additive only.

Cached in-process for 30 min.
"""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)

_CACHE: dict = {"data": [], "at": 0.0}
_TTL = 1800  # 30 min

# RSS feeds — best-effort (may be blocked on Railway US IPs)
_RSS_FEEDS = [
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "source": "CoinDesk"},
    {"url": "https://cointelegraph.com/rss",                    "source": "CoinTelegraph"},
    {"url": "https://decrypt.co/feed",                          "source": "Decrypt"},
]

# Broad keyword filter — don't over-filter; any finance/crypto headline counts
_MACRO_KEYWORDS = [
    "fed", "federal reserve", "fomc", "rate", "inflation", "cpi", "gdp",
    "treasury", "yield", "bitcoin", "crypto", "sec", "regulation", "etf",
    "powell", "monetary policy", "recession", "macro", "halving",
    "institutional", "blackrock", "vanguard", "fund", "billion", "million",
    "stablecoin", "defi", "solana", "ethereum", "bank", "finance",
]


def _is_macro_relevant(title: str, summary: str = "") -> bool:
    text = (title + " " + summary).lower()
    return any(kw in text for kw in _MACRO_KEYWORDS)


def _fmt_amount(usd: float) -> str:
    """Format raise amount for event title."""
    if usd >= 1_000_000_000:
        return f"${usd / 1_000_000_000:.1f}B"
    if usd >= 1_000_000:
        return f"${usd / 1_000_000:.0f}M"
    return f"${usd:,.0f}"


async def _fetch_defillama_raises(client: httpx.AsyncClient) -> list:
    """
    Pull recent VC raises from DeFiLlama and convert to macro-event format.
    This is the guaranteed baseline — DeFiLlama is always accessible on Railway.
    """
    events = []
    try:
        r = await client.get("https://api.llama.fi/raises", timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        raw = data.get("raises", [])
        cutoff = time.time() - 90 * 86400  # last 90 days

        for raise_ in raw:
            amount_m = raise_.get("amount") or 0
            date_ts  = raise_.get("date") or 0
            if amount_m < 1 or date_ts < cutoff:
                continue  # skip tiny/old raises

            amount_usd = amount_m * 1_000_000
            name       = raise_.get("name") or raise_.get("project") or "Unknown"
            round_type = raise_.get("round") or raise_.get("roundType") or "Funding"
            category   = raise_.get("category") or "DeFi"
            lead_investors = raise_.get("leadInvestors") or []
            lead_str   = f" · {', '.join(lead_investors[:2])}" if lead_investors else ""

            title = f"{name} raises {_fmt_amount(amount_usd)} {round_type}{lead_str}"
            desc  = (raise_.get("description") or "")[:200] or f"{category} · {_fmt_amount(amount_usd)} funding round"

            events.append({
                "title":        title,
                "source":       "DeFiLlama",
                "category":     "INSTITUTIONAL",
                "impact":       "HIGH" if amount_usd >= 50_000_000 else "MEDIUM",
                "published_at": datetime.fromtimestamp(date_ts, tz=timezone.utc).isoformat(),
                "date":         datetime.fromtimestamp(date_ts, tz=timezone.utc).strftime("%b %d"),
                "description":  desc,
                "type":         "raise",
            })
    except Exception as e:
        logger.warning(f"[macro_events] DeFiLlama raises failed: {e}")
    return events


async def _fetch_rss(feed: dict, client: httpx.AsyncClient) -> list:
    """Fetch and parse a single RSS feed. Returns list of event dicts."""
    events = []
    try:
        r = await client.get(feed["url"], timeout=5, follow_redirects=True)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
        channel = root.find("channel")
        if channel is None:
            return []
        for item in channel.findall("item")[:12]:
            title       = (item.findtext("title") or "").strip()
            link        = (item.findtext("link") or "").strip()
            pub_date    = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()[:250]

            if not title or not _is_macro_relevant(title, description):
                continue

            ts = None
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    ts = parsedate_to_datetime(pub_date).isoformat()
                except Exception:
                    pass

            # Classify category by keyword
            text_lower = (title + " " + description).lower()
            if any(k in text_lower for k in ["sec", "regulation", "law", "policy", "ban", "approve"]):
                cat, impact = "REGULATORY", "HIGH"
            elif any(k in text_lower for k in ["fed", "fomc", "rate", "inflation", "cpi", "powell", "monetary"]):
                cat, impact = "MACRO", "HIGH"
            elif any(k in text_lower for k in ["institutional", "blackrock", "vanguard", "fund", "etf"]):
                cat, impact = "INSTITUTIONAL", "MEDIUM"
            else:
                cat, impact = "MARKET", "MEDIUM"

            events.append({
                "title":        title,
                "url":          link,
                "source":       feed["source"],
                "category":     cat,
                "impact":       impact,
                "published_at": ts,
                "date":         datetime.fromisoformat(ts).strftime("%b %d") if ts else None,
                "description":  description,
                "type":         "news",
            })
    except Exception as e:
        logger.warning(f"[macro_events] RSS failed for {feed['source']}: {e}")
    return events


async def fetch_all_macro_events() -> list:
    """
    Returns macro-relevant events from all sources, newest first.
    DeFiLlama raises provide the guaranteed floor; RSS is additive.
    Caches for 30 min.
    """
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["at"]) < _TTL:
        return _CACHE["data"]

    all_events: list = []
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "CometCloud/1.0 intelligence-bot"},
            timeout=15,
        ) as client:
            # DeFiLlama first (reliable), RSS concurrently (best-effort)
            results = await asyncio.gather(
                _fetch_defillama_raises(client),
                *[_fetch_rss(feed, client) for feed in _RSS_FEEDS],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, list):
                    all_events.extend(result)

        # Deduplicate by normalised title prefix
        seen: set = set()
        deduped = []
        for ev in all_events:
            key = ev["title"][:55].lower().strip()
            if key not in seen:
                seen.add(key)
                deduped.append(ev)

        # Sort newest-first; events without timestamp go to end
        def _sort_key(e):
            ts = e.get("published_at")
            if ts:
                try:
                    return datetime.fromisoformat(ts).timestamp()
                except Exception:
                    pass
            return 0.0

        deduped.sort(key=_sort_key, reverse=True)
        result = deduped[:60]

        # Only update cache if we got something useful
        if result:
            _CACHE["data"] = result
            _CACHE["at"] = now

        logger.info(f"[macro_events] fetched {len(result)} events "
                    f"(raises + {len(_RSS_FEEDS)} RSS feeds)")
    except Exception as e:
        logger.error(f"[macro_events] fetch_all_macro_events failed: {e}")
        # Serve stale rather than empty
        return _CACHE["data"]

    return _CACHE["data"]
