"""
Intelligence router — macro events, VC funding, token unlocks, protocol intelligence
Endpoints: /api/v1/intelligence/*, /api/v1/vc/*, /api/v1/protocols/*
"""
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
import logging
import time

from data.market.data_layer import get_vc_raises, get_cg_vc_portfolios
from data.market.protocol_engine import get_protocol_universe

router = APIRouter()
_logger = logging.getLogger(__name__)

# Lazy singleton — VCDealFlowTracker is expensive to instantiate per-request
_vc_tracker = None

def _get_vc_tracker():
    global _vc_tracker
    if _vc_tracker is None:
        from data.vc.deal_flow import VCDealFlowTracker
        _vc_tracker = VCDealFlowTracker()
    return _vc_tracker


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
    try:
        try:
            tracker = _get_vc_tracker()
            rounds = tracker.get_recent_funding_rounds(limit)
            if rounds:
                return {"timestamp": datetime.now().isoformat(), "data": rounds, "source": "internal", "data_status": "ok"}
        except Exception:
            pass
        raises = await get_vc_raises(limit)
        data_status = "ok" if raises else "no_data"
        return {"timestamp": datetime.now().isoformat(), "data": raises, "source": "defillama", "data_status": data_status}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


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
async def get_token_unlocks(days: int = 30):
    try:
        tracker = _get_vc_tracker()
        return {"timestamp": datetime.now().isoformat(), "data": tracker.get_token_unlocks(days)}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/api/v1/vc/overlap")
async def get_vc_overlap():
    try:
        tracker = _get_vc_tracker()
        return {"timestamp": datetime.now().isoformat(), "data": tracker.get_vc_portfolio_overlap([])}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


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
