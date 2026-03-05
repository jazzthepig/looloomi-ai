"""
CometCloud Macro Events Scraper
抓取机构级加密/RWA宏观事件，供 Intelligence 页面使用
Sources: DefiLlama Raises, CoinDesk RSS, The Block RSS, Decrypt RSS
不需要付费API，全部免费公开数据源
"""

import asyncio
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
import json
import re

# ── 事件类型分类关键词 ──────────────────────────────────────────
CATEGORY_RULES = {
    "REGULATORY": [
        "sec", "cftc", "hkma", "sfc", "mas", "fca", "regulation", "regulatory",
        "compliance", "approve", "approval", "ban", "license", "ruling", "legislation",
        "bill", "act", "policy", "framework", "guideline", "etf approved", "etf rejection"
    ],
    "INSTITUTIONAL": [
        "blackrock", "fidelity", "jpmorgan", "goldman", "hsbc", "ubs", "franklin",
        "wisdomtree", "invesco", "ark invest", "vanguard", "state street",
        "tokenize", "tokenization", "rwa", "real world asset", "fund launch",
        "billion", "$1b", "$2b", "institutional", "custody", "prime brokerage"
    ],
    "MARKET": [
        "bitcoin reserve", "strategic reserve", "etf", "halving", "fed", "interest rate",
        "inflation", "macro", "market cap", "ath", "all-time high", "crash", "rally",
        "liquidation", "short squeeze", "whale", "inflow", "outflow"
    ],
    "TECH": [
        "upgrade", "mainnet", "testnet", "hard fork", "soft fork", "eip", "protocol",
        "layer 2", "l2", "rollup", "zk", "eigen", "restaking", "defi", "dex",
        "exploit", "hack", "vulnerability", "audit", "bridge"
    ],
}

IMPACT_KEYWORDS = {
    "HIGH": ["billion", "$1b", "$2b", "$5b", "historic", "first", "largest",
             "approved", "banned", "reserve", "etf", "breakthrough"],
    "MEDIUM": ["million", "launch", "partnership", "integration", "upgrade", "announce"],
}

def classify_event(title: str, description: str) -> tuple[str, str]:
    """返回 (category, impact_level)"""
    text = (title + " " + description).lower()
    
    # Category
    cat_scores = {cat: 0 for cat in CATEGORY_RULES}
    for cat, keywords in CATEGORY_RULES.items():
        for kw in keywords:
            if kw in text:
                cat_scores[cat] += 1
    category = max(cat_scores, key=cat_scores.get)
    if cat_scores[category] == 0:
        category = "MARKET"
    
    # Impact
    for kw in IMPACT_KEYWORDS["HIGH"]:
        if kw in text:
            return category, "HIGH"
    for kw in IMPACT_KEYWORDS["MEDIUM"]:
        if kw in text:
            return category, "MEDIUM"
    return category, "LOW"

def parse_rss_date(date_str: str) -> str:
    """Parse various RSS date formats → ISO string"""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%b %Y")
        except ValueError:
            continue
    return datetime.now().strftime("%b %Y")

@dataclass
class MacroEvent:
    title: str
    description: str
    category: str      # REGULATORY / INSTITUTIONAL / MARKET / TECH
    impact: str        # HIGH / MEDIUM / LOW
    source: str        # CoinDesk / The Block / etc.
    date: str          # "Mar 2026"
    url: str = ""

    def to_dict(self):
        return asdict(self)

# ── RSS FEEDS ──────────────────────────────────────────────────
RSS_FEEDS = [
    {
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "timeout": 10,
    },
    {
        "name": "The Block",
        "url": "https://www.theblock.co/rss.xml",
        "timeout": 10,
    },
    {
        "name": "Decrypt",
        "url": "https://decrypt.co/feed",
        "timeout": 10,
    },
    {
        "name": "CoinTelegraph",
        "url": "https://cointelegraph.com/rss",
        "timeout": 10,
    },
]

# ── DEFILLAMA RAISES (for RWA/institutional funding events) ───
DEFILLAMA_RAISES_URL = "https://api.llama.fi/raises"

async def fetch_rss_events(feed: dict, client: httpx.AsyncClient) -> list[MacroEvent]:
    """Fetch and parse a single RSS feed"""
    events = []
    try:
        resp = await client.get(feed["url"], timeout=feed["timeout"],
                                headers={"User-Agent": "CometCloud/1.0 (intelligence aggregator)"})
        resp.raise_for_status()
        
        root = ET.fromstring(resp.text)
        # Handle both RSS 2.0 and Atom
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        
        for item in items[:50]:  # max 50 per feed
            # Extract fields (RSS 2.0)
            title_el = item.find("title")
            desc_el  = item.find("description") or item.find("summary")
            date_el  = item.find("pubDate") or item.find("published")
            link_el  = item.find("link")
            
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            desc  = desc_el.text.strip()  if desc_el  is not None and desc_el.text  else ""
            date_str = date_el.text.strip() if date_el is not None and date_el.text else ""
            url   = link_el.text.strip()  if link_el  is not None and link_el.text  else ""
            
            # Strip HTML from description
            desc = re.sub(r'<[^>]+>', '', desc)[:300]
            
            if not title:
                continue
            
            # Filter: only macro-relevant articles
            combined = (title + " " + desc).lower()
            macro_keywords = [
                "billion", "etf", "regulation", "regulatory", "institutional",
                "tokeniz", "rwa", "reserve", "approve", "ban", "sec", "cftc",
                "hkma", "federal reserve", "interest rate", "blackrock", "fidelity",
                "jpmorgan", "upgrade", "mainnet", "hack", "exploit", "ath"
            ]
            if not any(kw in combined for kw in macro_keywords):
                continue
            
            category, impact = classify_event(title, desc)
            date_display = parse_rss_date(date_str) if date_str else datetime.now().strftime("%b %Y")
            
            events.append(MacroEvent(
                title=title[:120],
                description=desc[:280],
                category=category,
                impact=impact,
                source=feed["name"],
                date=date_display,
                url=url,
            ))
    
    except Exception as e:
        print(f"  [WARN] {feed['name']} failed: {e}")
    
    return events

async def fetch_defillama_events(client: httpx.AsyncClient) -> list[MacroEvent]:
    """Fetch large funding rounds from DefiLlama as macro events"""
    events = []
    try:
        resp = await client.get(DEFILLAMA_RAISES_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        raises = data.get("raises", [])
        
        # Filter: last 90 days, amount > $20M
        cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp()
        
        for r in raises:
            amount = r.get("amount") or 0
            date_ts = r.get("date") or 0
            
            if amount < 20 or date_ts < cutoff_ts:
                continue
            
            name = r.get("name") or r.get("project") or "Unknown"
            round_type = r.get("round") or r.get("round_type") or "Round"
            lead = r.get("leadInvestors", [])
            lead_str = ", ".join(lead[:2]) if lead else "Undisclosed"
            
            title = f"{name} raises ${amount}M {round_type}"
            desc  = f"Led by {lead_str}. " + (r.get("description") or "")
            
            category, impact = classify_event(title, desc)
            date_display = datetime.fromtimestamp(date_ts, tz=timezone.utc).strftime("%b %Y") if date_ts else "Recent"
            
            events.append(MacroEvent(
                title=title[:120],
                description=desc[:280],
                category="INSTITUTIONAL",
                impact="HIGH" if amount >= 50 else "MEDIUM",
                source="DefiLlama",
                date=date_display,
                url=f"https://defillama.com/raises",
            ))
    
    except Exception as e:
        print(f"  [WARN] DefiLlama raises failed: {e}")
    
    return events

def deduplicate(events: list[MacroEvent]) -> list[MacroEvent]:
    """Remove near-duplicate titles"""
    seen = []
    result = []
    for ev in events:
        # Normalize title for comparison
        norm = re.sub(r'[^a-z0-9 ]', '', ev.title.lower())
        words = set(norm.split())
        
        is_dup = False
        for s_words in seen:
            overlap = len(words & s_words) / max(len(words), 1)
            if overlap > 0.7:
                is_dup = True
                break
        
        if not is_dup:
            seen.append(words)
            result.append(ev)
    
    return result

def prioritize(events: list[MacroEvent], max_events: int = 20) -> list[MacroEvent]:
    """Sort by impact, category priority, recency"""
    impact_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    cat_order = {"REGULATORY": 0, "INSTITUTIONAL": 1, "MARKET": 2, "TECH": 3}
    
    events.sort(key=lambda e: (
        impact_order.get(e.impact, 2),
        cat_order.get(e.category, 3),
    ))
    
    # Ensure category diversity: max 6 per category
    counts = {}
    result = []
    for ev in events:
        if counts.get(ev.category, 0) < 6:
            result.append(ev)
            counts[ev.category] = counts.get(ev.category, 0) + 1
        if len(result) >= max_events:
            break
    
    return result

async def fetch_all_macro_events() -> list[dict]:
    """
    Main function — call this from FastAPI endpoint
    Returns list of dicts ready for JSON response
    """
    print("🔍 Fetching macro events...")
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Fetch all sources concurrently
        tasks = [fetch_rss_events(feed, client) for feed in RSS_FEEDS]
        tasks.append(fetch_defillama_events(client))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_events = []
    for r in results:
        if isinstance(r, list):
            all_events.extend(r)
        # Exceptions already logged in individual fetchers
    
    print(f"  Raw events: {len(all_events)}")
    
    # Deduplicate + prioritize
    deduped = deduplicate(all_events)
    final = prioritize(deduped, max_events=20)
    
    print(f"  Final events: {len(final)}")
    
    return [e.to_dict() for e in final]

# ── FASTAPI INTEGRATION ─────────────────────────────────────────
FASTAPI_ROUTE = '''
# In your FastAPI main.py, add:

from macro_events_scraper import fetch_all_macro_events
from fastapi import APIRouter
import asyncio
from datetime import datetime

router = APIRouter()
_cache = {"data": [], "updated_at": None}
CACHE_TTL_MINUTES = 60  # refresh every hour

@router.get("/api/intelligence/macro-events")
async def get_macro_events():
    """
    Returns structured macro events for Intelligence page.
    Cached for 60 minutes to avoid hammering RSS feeds.
    """
    now = datetime.utcnow()
    if (
        not _cache["data"] or
        _cache["updated_at"] is None or
        (now - _cache["updated_at"]).seconds > CACHE_TTL_MINUTES * 60
    ):
        _cache["data"] = await fetch_all_macro_events()
        _cache["updated_at"] = now
    
    return {
        "events": _cache["data"],
        "updated_at": _cache["updated_at"].isoformat() if _cache["updated_at"] else None,
        "count": len(_cache["data"])
    }
'''

# ── TEST RUN ────────────────────────────────────────────────────
if __name__ == "__main__":
    async def main():
        events = await fetch_all_macro_events()
        print(f"\n✅ {len(events)} macro events fetched\n")
        for i, ev in enumerate(events[:8], 1):
            print(f"{i}. [{ev['impact']:6}] [{ev['category']:13}] {ev['title'][:70]}")
            print(f"   Source: {ev['source']} · {ev['date']}")
            print()
        
        # Save sample output
        with open("/mnt/user-data/outputs/macro_events_sample.json", "w") as f:
            json.dump(events, f, indent=2, ensure_ascii=False)
        print("💾 Saved to macro_events_sample.json")
        
        print("\n" + "="*60)
        print("FASTAPI ROUTE CODE:")
        print(FASTAPI_ROUTE)
    
    asyncio.run(main())
