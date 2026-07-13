"""
Intelligence router — macro events, VC funding, token unlocks, protocol intelligence
Endpoints: /api/v1/intelligence/*, /api/v1/vc/*, /api/v1/protocols/*
"""
from fastapi import APIRouter, HTTPException, Query, Response
from datetime import datetime
import logging
import time

import os
from data.market.data_layer import get_vc_raises, get_cg_vc_portfolios, get_token_unlocks
from data.market.protocol_engine import get_protocol_universe

_CG_API_KEY = os.getenv("COINGECKO_API_KEY", "")

router = APIRouter()
_logger = logging.getLogger(__name__)


# ── VC raise sanitizer — reject the malformed RSS-extracted garbage ───────────
# The RSS headline extractor produces investor strings that are sentence fragments
# ("SBI Holdings SBI Holdings was the sole investor in the round") and repeated
# tokens. Better to show FEWER clean rounds than mangled ones. (Output-layer quality.)
_SENTENCE_JUNK = (" was ", " were ", " the ", "sole investor", "invested", "participat",
                  " round", " led ", "according", " raised", " in a ", " has ")


def _clean_investor(s):
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    low = " " + s.lower() + " "
    # sentence fragment / too long → garbage
    if any(j in low for j in _SENTENCE_JUNK) or len(s) > 40 or len(s.split()) > 5:
        # salvage: take the leading proper-noun chunk before the junk (e.g. "SBI Holdings ...")
        words = s.split()
        head = []
        for w in words:
            if (" " + w.lower() + " ") in ("  " + " ".join(_SENTENCE_JUNK)):
                break
            head.append(w)
            if len(head) >= 4:
                break
        s = " ".join(head).strip()
        if not s or len(s.split()) > 5:
            return None
    # collapse immediate duplicate tokens ("SBI Holdings SBI Holdings" → "SBI Holdings")
    toks = s.split()
    half = len(toks) // 2
    if half and toks[:half] == toks[half:half * 2]:
        s = " ".join(toks[:half])
    return s or None


def _sanitize_raises(raises: list) -> list:
    out = []
    for r in raises or []:
        if not isinstance(r, dict):
            continue
        name = (r.get("name") or r.get("project") or "").strip()
        if not name or len(name) > 60:
            continue
        raw_inv = r.get("investors") or ([r["lead_investor"]] if r.get("lead_investor") else [])
        inv = []
        for x in raw_inv:
            c = _clean_investor(x)
            if not c:
                continue
            # strip project-name contamination ("SBI Holdings EDX Markets" → "SBI Holdings")
            if c.lower().endswith(name.lower()) and len(c) > len(name):
                c = c[: -len(name)].strip()
            if c and c.lower() != name.lower() and c not in inv:
                inv.append(c)
        r = {**r, "name": name, "project": name, "investors": inv,
             "lead_investor": inv[0] if inv else None}
        out.append(r)
    return out


# ── Macro Events ──────────────────────────────────────────────────────────────

# In-memory cache — 60 min TTL (RSS feeds rate-limit aggressively)
_macro_cache: dict = {"data": [], "at": 0.0}
_MACRO_TTL = 3600


@router.get("/api/v1/intelligence/macro-events")
async def get_macro_events(response: Response):
    """
    Fetch latest macro events from RSS feeds (CoinDesk, The Block, Decrypt, CoinTelegraph)
    + DeFiLlama Raises. Auto-classified: REGULATORY/INSTITUTIONAL/MARKET/TECH.
    Impact levels: HIGH/MEDIUM/LOW. Cached 60 min.
    """
    now = time.time()
    # Serve from cache if fresh
    if _macro_cache["data"] and (now - _macro_cache["at"]) < _MACRO_TTL:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return {"events": _macro_cache["data"], "cached": True, "count": len(_macro_cache["data"])}

    try:
        from backend.macro_events_scraper import fetch_all_macro_events
        events = await fetch_all_macro_events()
        # Only cache if we got actual events — don't freeze an empty result for 60 min
        if events:
            _macro_cache["data"] = events
            _macro_cache["at"] = now
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return {"events": events, "cached": False, "count": len(events)}
    except Exception as e:
        _logger.error(f"Macro events fetch failed: {e}", exc_info=True)
        # Return stale cache or empty — never 500
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=600"
        return {"events": _macro_cache["data"] or [], "cached": True, "error": "fetch_failed", "count": len(_macro_cache["data"])}


# ── VC Deal Flow ──────────────────────────────────────────────────────────────

@router.get("/api/v1/vc/funding-rounds")
async def get_funding_rounds(response: Response, limit: int = 20):
    """
    Recent crypto VC funding rounds via DeFiLlama /raises.
    Sorted by date desc, last 180 days, ≥$100K raises only.
    TTL: 1h. Returns empty list when DeFiLlama is unavailable — never mock data.
    """
    try:
        raises = _sanitize_raises(await get_vc_raises(limit))
        data_status = "ok" if raises else "no_data"
        response.headers["Cache-Control"] = "public, max-age=1800, stale-while-revalidate=3600"
        return {"timestamp": datetime.now().isoformat(), "data": raises, "source": "defillama", "data_status": data_status}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        return {"timestamp": datetime.now().isoformat(), "data": [], "source": "defillama", "data_status": "error"}


@router.get("/api/v1/vc/portfolios")
async def get_vc_portfolios(response: Response):
    """
    VC portfolio performance via CoinGecko categories.
    Returns ~16 major firms with market_cap, 24h change, volume, top_3_coins.
    Sorted by portfolio market cap desc. TTL: 10 min.
    """
    if not _CG_API_KEY:
        return {"timestamp": datetime.now().isoformat(), "data": [], "count": 0,
                "data_status": "no_api_key"}
    try:
        data = await get_cg_vc_portfolios()
        data_status = "ok" if data else "no_data"
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
        return {"timestamp": datetime.now().isoformat(), "data": data, "count": len(data),
                "data_status": data_status}
    except Exception as e:
        _logger.error(f"VC portfolios error: {e}", exc_info=True)
        return {"timestamp": datetime.now().isoformat(), "data": [], "count": 0,
                "data_status": "error"}


@router.get("/api/v1/vc/unlocks")
async def get_upcoming_unlocks(response: Response, days: int = 30):
    """
    Upcoming token unlocks from DeFiLlama /emissions.
    Returns events within `days` days, sorted by unlock date.
    TTL: 2h. Returns empty list when DeFiLlama is unavailable — never mock data.
    """
    try:
        data = await get_token_unlocks(days_ahead=days)
        data_status = "ok" if data else "no_data"
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=7200"
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
    response: Response,
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
        result = await get_protocol_universe(category=category, min_grade=min_grade)
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
        return result
    except Exception as e:
        _logger.error(f"Protocol universe error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Protocol scoring failed")
