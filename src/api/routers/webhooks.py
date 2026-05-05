"""
Webhook Subscriptions Router — CometCloud AI
=============================================
Push grade-change events (GRADE_UPGRADE / GRADE_DOWNGRADE) to registered HTTPS endpoints.

POST /api/v1/webhooks/subscribe     — Register a URL for grade events
DELETE /api/v1/webhooks/unsubscribe — Remove a subscription
GET  /api/v1/webhooks/list          — List subscriptions for this key
POST /api/v1/webhooks/test          — Fire a test ping to a registered URL

Delivery:
  - Triggered async via BackgroundTask when grade signals are generated in /api/v1/signals
  - HMAC-SHA256 signature in X-CometCloud-Signature header (hex digest of raw body)
  - Timeout: 8s per delivery attempt
  - On failure: increments fail_count, records last_error — no retry for now

Auth: X-API-Key required on all endpoints.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field, HttpUrl

_log = logging.getLogger(__name__)

_SB_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

SUPPORTED_EVENTS = {"GRADE_UPGRADE", "GRADE_DOWNGRADE"}


# ── Supabase helpers ──────────────────────────────────────────────────────────

async def _sb_get(params: dict) -> list:
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(
            f"{_SB_URL}/rest/v1/webhook_subscriptions",
            params=params,
            headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"},
        )
        return r.json() if r.status_code == 200 else []


async def _sb_post(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.post(
            f"{_SB_URL}/rest/v1/webhook_subscriptions",
            json=payload,
            headers={
                "apikey":        _SB_KEY,
                "Authorization": f"Bearer {_SB_KEY}",
                "Content-Type":  "application/json",
                "Prefer":        "return=representation",
            },
        )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=500, detail=f"Storage error: {r.text[:200]}")
        rows = r.json()
        return rows[0] if rows else {}


async def _sb_patch(key_prefix: str, url: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=8) as client:
        await client.patch(
            f"{_SB_URL}/rest/v1/webhook_subscriptions",
            params={"key_prefix": f"eq.{key_prefix}", "url": f"eq.{url}"},
            json=payload,
            headers={
                "apikey":        _SB_KEY,
                "Authorization": f"Bearer {_SB_KEY}",
                "Content-Type":  "application/json",
                "Prefer":        "return=minimal",
            },
        )


async def _sb_delete(key_prefix: str, url: str) -> None:
    async with httpx.AsyncClient(timeout=8) as client:
        await client.delete(
            f"{_SB_URL}/rest/v1/webhook_subscriptions",
            params={"key_prefix": f"eq.{key_prefix}", "url": f"eq.{url}"},
            headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"},
        )


# ── Key validation ────────────────────────────────────────────────────────────

async def _require_key(raw_key: str) -> str:
    """Validate X-API-Key and return key_prefix. Raises 401 if invalid."""
    if not raw_key:
        raise HTTPException(status_code=401, detail="X-API-Key required")
    try:
        from src.api.routers.keys import lookup_key
        row = await lookup_key(raw_key)
    except Exception:
        row = None
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return row["key_prefix"]


# ── Delivery ──────────────────────────────────────────────────────────────────

def _sign(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex signature."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _deliver(url: str, secret: str, payload: dict, key_prefix: str) -> None:
    """Fire one webhook delivery. Updates Supabase on success/failure."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    sig  = _sign(secret, body)
    now  = datetime.now(timezone.utc).isoformat()

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type":            "application/json",
                    "X-CometCloud-Signature":  sig,
                    "X-CometCloud-Event":      payload.get("event", "WEBHOOK"),
                    "User-Agent":              "CometCloud-Webhooks/1.0",
                },
            )
            if r.status_code < 300:
                await _sb_patch(key_prefix, url, {
                    "last_fired_at": now,
                    "fire_count":    "fire_count + 1",
                    "last_error":    None,
                })
                _log.info(f"[webhook] ✅ {url} → {r.status_code}")
            else:
                err = f"HTTP {r.status_code}: {r.text[:120]}"
                await _sb_patch(key_prefix, url, {
                    "fail_count": "fail_count + 1",
                    "last_error": err,
                })
                _log.warning(f"[webhook] ⚠️  {url} → {err}")
    except Exception as e:
        err = str(e)[:200]
        try:
            await _sb_patch(key_prefix, url, {
                "fail_count": "fail_count + 1",
                "last_error": err,
            })
        except Exception:
            pass
        _log.warning(f"[webhook] ❌ {url} → {err}")


async def fire_grade_webhooks(
    event: str,
    assets: list[dict],
    regime: str,
    background_tasks: BackgroundTasks,
) -> None:
    """
    Called from signal feed when grade changes are detected.
    Fans out to all active subscribers for this event type.
    Non-blocking — all deliveries run as background tasks.
    """
    try:
        rows = await _sb_get({
            "active":   "eq.true",
            "select":   "key_prefix,url,secret,events",
        })
        if not rows:
            return

        payload = {
            "event":     event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "assets":    assets,
            "regime":    regime,
            "source":    "cometcloud_cis_v4",
        }

        for row in rows:
            if event not in (row.get("events") or []):
                continue
            background_tasks.add_task(
                _deliver,
                url=row["url"],
                secret=row["secret"],
                payload=payload,
                key_prefix=row["key_prefix"],
            )
    except Exception as e:
        _log.debug(f"[webhook] fan-out error: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────

class SubscribeRequest(BaseModel):
    url:    str       = Field(..., description="HTTPS endpoint to deliver events to")
    events: list[str] = Field(
        default=["GRADE_UPGRADE", "GRADE_DOWNGRADE"],
        description="Event types to subscribe to",
    )


class SubscribeResponse(BaseModel):
    key_prefix: str
    url:        str
    events:     list[str]
    secret:     str
    message:    str


@router.post("/subscribe", response_model=SubscribeResponse, summary="Subscribe to grade-change events")
async def subscribe(
    body: SubscribeRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """
    Register an HTTPS endpoint to receive CIS grade-change events.

    Events fired:
    - **GRADE_UPGRADE**: one or more assets moved to a higher grade
    - **GRADE_DOWNGRADE**: one or more assets moved to a lower grade

    Payload includes the assets, their from/to grades, CIS scores, and current regime.

    Verify deliveries using the **X-CometCloud-Signature** header (HMAC-SHA256 of raw body).
    Store the `secret` securely — it is shown once.
    """
    key_prefix = await _require_key(x_api_key)

    # Validate URL
    if not body.url.startswith("https://"):
        raise HTTPException(status_code=400, detail="URL must use HTTPS")

    # Validate events
    bad = [e for e in body.events if e not in SUPPORTED_EVENTS]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unsupported events: {bad}. Supported: {list(SUPPORTED_EVENTS)}")

    # Generate signing secret
    secret = secrets.token_hex(32)

    # Upsert — same key_prefix + url updates events/secret
    row = await _sb_post({
        "key_prefix": key_prefix,
        "url":        body.url,
        "events":     body.events,
        "secret":     secret,
        "active":     True,
    })

    _log.info(f"[webhook] Subscribed {key_prefix} → {body.url} for {body.events}")

    return SubscribeResponse(
        key_prefix=key_prefix,
        url=body.url,
        events=body.events,
        secret=secret,
        message=(
            "Webhook registered. Store the secret securely — it will not be shown again. "
            "Verify deliveries using the X-CometCloud-Signature header (HMAC-SHA256 hex of raw body). "
            "Events fire within ~30s of grade detection."
        ),
    )


@router.delete("/unsubscribe", summary="Remove a webhook subscription")
async def unsubscribe(
    url: str,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """Remove a webhook subscription for this API key."""
    key_prefix = await _require_key(x_api_key)
    await _sb_delete(key_prefix, url)
    return {"status": "deleted", "key_prefix": key_prefix, "url": url}


@router.get("/list", summary="List webhook subscriptions for this key")
async def list_subscriptions(
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """Returns all active webhook subscriptions for the authenticated API key."""
    key_prefix = await _require_key(x_api_key)
    rows = await _sb_get({
        "key_prefix": f"eq.{key_prefix}",
        "select":     "id,url,events,active,created_at,last_fired_at,fire_count,fail_count,last_error",
    })
    return {"key_prefix": key_prefix, "subscriptions": rows, "count": len(rows)}


@router.post("/test", summary="Fire a test event to a registered webhook")
async def test_webhook(
    url: str,
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """
    Sends a test GRADE_UPGRADE payload to a registered webhook URL.
    Useful for verifying your endpoint and signature verification logic.
    """
    key_prefix = await _require_key(x_api_key)

    rows = await _sb_get({
        "key_prefix": f"eq.{key_prefix}",
        "url":        f"eq.{url}",
        "select":     "url,secret,active",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="Subscription not found for this key + URL")

    row = rows[0]
    test_payload = {
        "event":     "TEST",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "assets":    [{"symbol": "BTC", "from": "B+", "to": "A", "delta": 1, "cis_score": 76.4}],
        "regime":    "TEST_MODE",
        "source":    "cometcloud_webhook_test",
        "message":   "This is a test delivery. Your endpoint and signature verification are working correctly.",
    }

    background_tasks.add_task(
        _deliver,
        url=row["url"],
        secret=row["secret"],
        payload=test_payload,
        key_prefix=key_prefix,
    )

    return {
        "status":  "queued",
        "url":     url,
        "message": "Test event queued. Check your endpoint within 10s.",
    }


@router.get("/events", summary="List supported event types")
async def list_events():
    """Returns the supported webhook event types."""
    return {
        "events": [
            {
                "event":       "GRADE_UPGRADE",
                "description": "One or more CIS-scored assets moved to a higher grade (e.g. B→B+)",
                "importance":  "HIGH if delta ≥2 grades, MED if 1 grade",
            },
            {
                "event":       "GRADE_DOWNGRADE",
                "description": "One or more CIS-scored assets moved to a lower grade",
                "importance":  "HIGH if delta ≥2 grades, MED if 1 grade",
            },
        ],
        "payload_shape": {
            "event":     "GRADE_UPGRADE | GRADE_DOWNGRADE | TEST",
            "timestamp": "ISO8601",
            "assets":    [{"symbol": "str", "from": "str", "to": "str", "delta": "int", "cis_score": "float"}],
            "regime":    "str",
            "source":    "cometcloud_cis_v4",
        },
        "signature": "HMAC-SHA256(secret, raw_body) — hex — delivered in X-CometCloud-Signature header",
    }
