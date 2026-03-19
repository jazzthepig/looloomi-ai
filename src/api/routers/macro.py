"""
Macro Brief router — receives AI-generated macro analysis from Mac Mini,
stores in Redis, and serves to the dashboard.

Endpoints:
  POST /internal/macro-brief  — Mac Mini pushes analysis (same auth as CIS)
  GET  /api/v1/macro/brief    — Dashboard reads latest brief
"""
import os, json, time

from fastapi import APIRouter, HTTPException, Header

from src.api.store import redis_set_key, redis_get_key

router = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
_REDIS_KEY = "macro:brief"
_REDIS_TTL = 43200  # 12 hours — briefs are twice daily


# ── Internal push (Mac Mini → Railway) ───────────────────────────────────────

@router.post("/internal/macro-brief")
async def receive_macro_brief(payload: dict, x_internal_token: str = Header(None)):
    """
    Receives AI-generated macro analysis from the Mac Mini.
    Expected payload:
    {
        "brief": "...",          # The analysis text (markdown)
        "market_data": {...},    # Raw data snapshot used for the analysis
        "model": "qwen3.5-35b", # Model that generated it
        "generated_at": "..."   # ISO timestamp
    }
    """
    # Reject-by-default auth (same pattern as CIS)
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not payload.get("brief"):
        raise HTTPException(status_code=400, detail="Missing 'brief' field")

    # Add server-side received timestamp
    payload["received_at"] = int(time.time())

    ok = await redis_set_key(_REDIS_KEY, payload, ttl=_REDIS_TTL)
    if not ok:
        raise HTTPException(status_code=502, detail="Redis write failed")

    print(f"[MACRO] Brief received — {len(payload['brief'])} chars, model={payload.get('model', '?')}")
    return {
        "status": "ok",
        "chars": len(payload["brief"]),
        "key": _REDIS_KEY,
    }


# ── Public read ──────────────────────────────────────────────────────────────

@router.get("/api/v1/macro/brief")
async def get_macro_brief():
    """Returns the latest macro analysis brief from Redis."""
    data = await redis_get_key(_REDIS_KEY)
    if not data:
        return {
            "brief": None,
            "stale": True,
            "message": "No macro brief available — waiting for next scheduled run.",
        }

    age = int(time.time()) - data.get("received_at", 0)
    return {
        "brief": data.get("brief"),
        "market_data": data.get("market_data"),
        "model": data.get("model"),
        "generated_at": data.get("generated_at"),
        "received_at": data.get("received_at"),
        "age_seconds": age,
        "stale": age > _REDIS_TTL,
    }
