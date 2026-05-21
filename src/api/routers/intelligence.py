"""
Intelligence router — macro events, VC funding, token unlocks, protocol intelligence
Endpoints: /api/v1/intelligence/*, /api/v1/vc/*, /api/v1/protocols/*
"""
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
import logging
import time

from data.market.data_layer import get_vc_raises, get_cg_vc_portfolios, get_token_unlocks
from data.market.protocol_engine import get_protocol_universe

router = APIRouter()
_logger = logging.getLogger(__name__)


# ── Macro Events ──────────────────────────────────────────────────────────────

# In-memory cache — 60 min TTL (RSS feeds rate-limit aggressively)
_macro_cache: dict = {"data": [], "at": 0.0}
_MACRO_TTL = 3600


@router.get("/api/v1/intelligence/macro-events")
async def get_macro_events():
    """
    Fetch latest macro events from RSS feeds (CoinDesk, The Block, Decrypt, CoinTelegraph)
    + DeFiLlama Raises. Auto-classified: REGULATORY/INSTITUTIONAL/MARKET/TECH.
    Impact levels: HIGH/MEDIUM/LOW. Cached 60 min.
    """
    now = time.time()
    # Serve from cache if fresh
    if _macro_cache["data"] and (now - _macro_cache["at"]) < _MACRO_TTL:
        return {"events": _macro_cache["data"], "cached": True, "count": len(_macro_cache["data"])}

    try:
        from backend.macro_events_scraper import fetch_all_macro_events
        events = await fetch_all_macro_events()
        # Only cache if we got actual events — don't freeze an empty result for 60 min
        if events:
            _macro_cache["data"] = events
            _macro_cache["at"] = now
        return {"events": events, "cached": False, "count": len(events)}
    except Exception as e:
        _logger.error(f"Macro events fetch failed: {e}", exc_info=True)
        # Return stale cache or empty — never 500
        return {"events": _macro_cache["data"] or [], "cached": True, "error": "fetch_failed", "count": len(_macro_cache["data"])}


# ── VC Deal Flow ──────────────────────────────────────────────────────────────

@router.get("/api/v1/vc/funding-rounds")
async def get_funding_rounds(limit: int = 20):
    """
    Recent crypto VC funding rounds via DeFiLlama /raises.
    Sorted by date desc, last 180 days, ≥$100K raises only.
    TTL: 1h. Returns empty list when DeFiLlama is unavailable — never mock data.
    """
    try:
        raises = await get_vc_raises(limit)
        data_status = "ok" if raises else "no_data"
        return {"timestamp": datetime.now().isoformat(), "data": raises, "source": "defillama", "data_status": data_status}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        return {"timestamp": datetime.now().isoformat(), "data": [], "source": "defillama", "data_status": "error"}


@router.get("/api/v1/vc/portfolios")
async def get_vc_portfolios():
    """
    VC portfolio performance via CoinGecko categories.
    Returns ~16 major firms with market_cap, 24h change, volume, top_3_coins.
    Sorted by portfolio market cap desc. TTL: 10 min.
    """
    try:
        data = await get_cg_vc_portfolios()
        return {"timestamp": datetime.now().isoformat(), "data": data, "count": len(data)}
    except Exception as e:
        _logger.error(f"VC portfolios error: {e}", exc_info=True)
        return {"timestamp": datetime.now().isoformat(), "data": [], "count": 0}


@router.get("/api/v1/vc/unlocks")
async def get_upcoming_unlocks(days: int = 30):
    """
    Upcoming token unlocks from DeFiLlama /emissions.
    Returns events within `days` days, sorted by unlock date.
    TTL: 2h. Returns empty list when DeFiLlama is unavailable — never mock data.
    """
    try:
        data = await get_token_unlocks(days_ahead=days)
        data_status = "ok" if data else "no_data"
        return {"timestamp": datetime.now().isoformat(), "data": data, "source": "defillama", "data_status": data_status}
    except Exception as e:
        _logger.error(f"Token unlocks error: {e}", exc_info=True)
        return {"timestamp": datetime.now().isoformat(), "data": [], "source": "defillama", "data_status": "error"}


@router.get("/api/v1/vc/overlap")
async def get_vc_overlap():
    """VC co-investment overlap derived from live funding rounds — no mock data."""
    try:
        raises = await get_vc_raises(200)
        project_investors: dict = {}
        for r in raises:
            proj = r.get("name") or r.get("project") or ""
            investors = r.get("investors") or []
            if not proj or not investors:
                continue
            if proj not in project_investors:
                project_investors[proj] = set()
            project_investors[proj].update(investors)

        overlaps = []
        for proj, investors in project_investors.items():
            count = len(investors)
            if count >= 2:
                overlaps.append({"project": proj, "vcs": sorted(investors), "count": count})
        overlaps.sort(key=lambda x: x["count"], reverse=True)

        return {
            "timestamp": datetime.now().isoformat(),
            "data": {
                "high_overlap": [o for o in overlaps if o["count"] >= 3][:10],
                "recent_overlap": [o for o in overlaps if o["count"] == 2][:10],
                "available": len(overlaps) > 0,
            }
        }
    except Exception as e:
        _logger.error(f"VC overlap error: {e}", exc_info=True)
        return {"timestamp": datetime.now().isoformat(), "data": {"high_overlap": [], "recent_overlap": [], "available": False}}


# ── Protocol Intelligence ────────────────────────────────────────────────────

@router.get("/api/v1/protocols/universe")
async def get_protocols(
    category: str | None = Query(None, description="Filter by category (e.g. 'RWA', 'DeFi - Lending')"),
    min_grade: str | None = Query(None, description="Minimum CIS grade (A+, A, B+, B, C+, C, D, F)"),
):
    """
    Protocol Intelligence — CIS-scored protocol universe.
    Live DeFiLlama TVL data + 5-pillar scoring (F/M/O/S/A).
    Returns ranked protocols with grade, signal, risk tier, and allocation weight.
    Agent-consumable: query ?category=RWA&min_grade=B for filtered results.
    """
    try:
        return await get_protocol_universe(category=category, min_grade=min_grade)
    except Exception as e:
        _logger.error(f"Protocol universe error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Protocol scoring failed")
