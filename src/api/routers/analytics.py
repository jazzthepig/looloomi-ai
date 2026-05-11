"""
Analytics Router — CometCloud AI
==================================
Lightweight event tracking to Supabase. No third-party services.

POST /api/v1/analytics/track   — Browser fires event (fire-and-forget)
GET  /api/v1/analytics/summary — Internal summary (internal token required)

Table: analytics_events
  id, event, props (JSONB), path, referrer, ip_hash, recorded_at

IP is hashed (SHA-256) before storage — no raw IPs retained.
"""

import hashlib
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

_log = logging.getLogger(__name__)

_SB_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))
_INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

# In-memory rate limit — max 30 track calls per IP per minute (prevents abuse)
_ip_counts: dict[str, tuple[int, float]] = {}
_TRACK_LIMIT = 30


class TrackEvent(BaseModel):
    event: str
    props: dict = {}
    path: Optional[str] = None
    referrer: Optional[str] = None
    ts: Optional[str] = None


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def _rate_ok(ip_hash: str) -> bool:
    now = time.time()
    count, window_start = _ip_counts.get(ip_hash, (0, now))
    if now - window_start > 60:
        _ip_counts[ip_hash] = (1, now)
        return True
    if count >= _TRACK_LIMIT:
        return False
    _ip_counts[ip_hash] = (count + 1, window_start)
    return True


@router.post("/track")
async def track_event(body: TrackEvent, request: Request):
    """
    Fire-and-forget analytics event from the browser.
    Returns 204 immediately — never blocks the client.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    ip_hash = _hash_ip(ip)

    if not _rate_ok(ip_hash):
        return JSONResponse(status_code=204, content=None)  # silently drop

    # Validate event name — alphanumeric + underscore only
    event = body.event[:64].strip()
    if not event or not all(c.isalnum() or c == "_" for c in event):
        return JSONResponse(status_code=204, content=None)

    if _SB_URL and _SB_KEY:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(
                    f"{_SB_URL}/rest/v1/analytics_events",
                    json={
                        "event":       event,
                        "props":       body.props or {},
                        "path":        (body.path or "")[:255],
                        "referrer":    (body.referrer or "")[:255],
                        "ip_hash":     ip_hash,
                        "recorded_at": body.ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    headers={
                        "apikey":        _SB_KEY,
                        "Authorization": f"Bearer {_SB_KEY}",
                        "Content-Type":  "application/json",
                        "Prefer":        "return=minimal",
                    },
                )
        except Exception as e:
            _log.debug(f"[analytics] write failed: {e}")

    return JSONResponse(status_code=204, content=None)


@router.get("/summary")
async def analytics_summary(
    days: int = 7,
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
):
    """Internal summary — top events + section views + key creations. Requires internal token."""
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    if not _SB_URL or not _SB_KEY:
        return {"error": "Supabase not configured"}

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"{_SB_URL}/rest/v1/analytics_events",
                params={
                    "select":      "event,props,path,recorded_at",
                    "recorded_at": f"gte.{time.strftime('%Y-%m-%dT00:00:00Z', time.gmtime(time.time() - days * 86400))}",
                    "order":       "recorded_at.desc",
                    "limit":       "2000",
                },
                headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"},
            )
            rows = r.json() if r.status_code == 200 else []

        # Aggregate
        event_counts: dict[str, int] = {}
        section_counts: dict[str, int] = {}
        keys_created = 0

        for row in rows:
            ev = row.get("event", "")
            event_counts[ev] = event_counts.get(ev, 0) + 1
            if ev == "section_view":
                section = (row.get("props") or {}).get("section", "unknown")
                section_counts[section] = section_counts.get(section, 0) + 1
            if ev == "api_key_created":
                keys_created += 1

        return {
            "days":           days,
            "total_events":   len(rows),
            "unique_events":  sorted(event_counts.items(), key=lambda x: -x[1]),
            "section_views":  sorted(section_counts.items(), key=lambda x: -x[1]),
            "keys_created":   keys_created,
        }
    except Exception as e:
        return {"error": str(e)}
