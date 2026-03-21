"""
Intelligence router — macro events, VC funding, token unlocks
Endpoints: /api/v1/intelligence/*, /api/v1/vc/*
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
import logging

from data.market.data_layer import get_vc_raises

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

@router.get("/api/v1/intelligence/macro-events")
async def get_macro_events():
    """
    Fetch latest macro events from RSS feeds (CoinDesk, The Block, Decrypt, CoinTelegraph)
    + DeFiLlama Raises. Auto-classified: REGULATORY/INSTITUTIONAL/MARKET/TECH.
    Impact levels: HIGH/MEDIUM/LOW. Cached 60 min.
    """
    from backend.macro_events_scraper import fetch_all_macro_events
    return {"events": await fetch_all_macro_events()}


# ── VC Deal Flow ──────────────────────────────────────────────────────────────

@router.get("/api/v1/vc/funding-rounds")
async def get_funding_rounds(limit: int = 20):
    try:
        try:
            tracker = _get_vc_tracker()
            rounds = tracker.get_recent_funding_rounds(limit)
            if rounds:
                return {"timestamp": datetime.now().isoformat(), "data": rounds, "source": "internal"}
        except Exception:
            pass
        raises = await get_vc_raises(limit)
        return {"timestamp": datetime.now().isoformat(), "data": raises, "source": "defillama"}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


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
