"""
API Key Router — CometCloud AI
================================
Handles key issuance, validation, and usage tracking.

POST /api/v1/keys/create   — Request a free-tier API key (email + name)
GET  /api/v1/keys/verify   — Verify a key is valid (for integrations)
GET  /api/v1/keys/tiers    — Public tier limits reference

Key format: cc_live_<32 random hex chars>
Keys are returned once at creation — we only store the SHA-256 hash.

Rate limit middleware is in src/api/middleware/rate_limit.py.
"""

import hashlib
import hmac
import os
import secrets
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

_log = logging.getLogger(__name__)

_SB_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))

router = APIRouter(prefix="/api/v1/keys", tags=["api-keys"])

# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_key() -> str:
    return "cc_live_" + secrets.token_hex(16)   # 40 chars total


async def _sb_post(table: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{_SB_URL}/rest/v1/{table}",
            json=payload,
            headers={
                "apikey":        _SB_KEY,
                "Authorization": f"Bearer {_SB_KEY}",
                "Content-Type":  "application/json",
                "Prefer":        "return=representation",
            },
        )
        if r.status_code not in (200, 201):
            # Name the most likely cause. `_SB_KEY` falls back from SUPABASE_SERVICE_KEY
            # to SUPABASE_KEY, and the anon key CANNOT insert here — api_keys grants
            # anon only SELECT, and its RLS policy `api_keys_service_only` is
            # `ALL USING false`. So a missing SUPABASE_SERVICE_KEY surfaces as a
            # customer-facing 500 with nothing pointing at the env var. Measured
            # 2026-08-09: zero keys had ever been issued for exactly this reason.
            hint = ""
            if r.status_code in (401, 403) and not os.getenv("SUPABASE_SERVICE_KEY"):
                hint = (" — SUPABASE_SERVICE_KEY is not set, so this fell back to the "
                        "anon key, which has no INSERT grant on api_keys")
            _log.error(f"[keys] Supabase {table} write failed: "
                       f"{r.status_code} {r.text[:300]}{hint}")
            # SURFACE THE CAUSE (2026-08-11). This used to raise a bare
            # "Key storage failed" for every failure mode, with the status and body
            # visible only in a log nobody reads while debugging from the outside.
            #
            # The actual bug was one wrong column name. It was diagnosed wrong THREE
            # times — "anon lacks INSERT", "SUPABASE_SERVICE_KEY is missing", "id has
            # no sequence" — and every one of those was a plausible story invented to
            # fill the space the error message left empty. A message that names no
            # cause does not merely fail to help: it funds confident wrong answers,
            # and each one costs a round trip through a human with console access.
            #
            # PostgREST's own message ("column X does not exist", "violates row-level
            # security policy") is precise and contains no secrets — it describes OUR
            # schema, not the caller's data. Passing it through is the difference
            # between a five-minute fix and three wrong ones.
            detail = "Key storage failed"
            try:
                body_msg = (r.json() or {}).get("message") or ""
            except Exception:
                body_msg = r.text[:200]
            if body_msg:
                detail = f"Key storage failed: {body_msg}"
            raise HTTPException(status_code=500, detail=detail)
        return r.json()


async def _sb_get_by_hash(key_hash: str) -> Optional[dict]:
    """Look up a key by hash. Returns None if not found."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{_SB_URL}/rest/v1/api_keys",
            params={"key_hash": f"eq.{key_hash}", "select": "id,key_prefix,tier,rate_limit_rpm,rate_limit_day,active,name"},
            headers={
                "apikey":        _SB_KEY,
                "Authorization": f"Bearer {_SB_KEY}",
            },
        )
        if r.status_code != 200:
            return None
        rows = r.json()
        return rows[0] if rows else None


async def _sb_increment_usage(key_id: int) -> None:
    """Bump request_count (via RPC) and last_used_at. Fire-and-forget.

    Two separate calls:
      1. PATCH last_used_at (string value — safe in PostgREST PATCH)
      2. RPC increment_api_key_usage (atomic INTEGER increment — cannot use
         SQL expression strings in PATCH body; PostgREST treats them as literals)
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=5) as client:
            # Update timestamp
            await client.patch(
                f"{_SB_URL}/rest/v1/api_keys",
                params={"id": f"eq.{key_id}"},
                json={"last_used_at": now},
                headers={
                    "apikey":        _SB_KEY,
                    "Authorization": f"Bearer {_SB_KEY}",
                    "Content-Type":  "application/json",
                    "Prefer":        "return=minimal",
                },
            )
            # Atomic counter via RPC
            await client.post(
                f"{_SB_URL}/rest/v1/rpc/increment_api_key_usage",
                json={"p_key_id": key_id},
                headers={
                    "apikey":        _SB_KEY,
                    "Authorization": f"Bearer {_SB_KEY}",
                    "Content-Type":  "application/json",
                },
            )
    except Exception:
        pass


# ── Public key lookup (cached in Redis by rate_limit.py) ─────────────────────

async def lookup_key(raw_key: str) -> Optional[dict]:
    """
    Validate a raw API key. Returns key row or None.
    Called by rate_limit middleware on every authenticated request.
    """
    if not raw_key or not raw_key.startswith("cc_live_"):
        return None
    key_hash = _hash_key(raw_key)
    row = await _sb_get_by_hash(key_hash)
    if row and row.get("active"):
        return row
    return None


# ── Routes ─────────────────────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name:         str           = Field(..., min_length=1, max_length=80,  description="Label for this key, e.g. 'My trading bot'")
    email:        str           = Field(..., description="Contact email — used for abuse notifications only")
    tier:         str           = Field("free", description="Tier: 'free' (default). Pro keys issued manually.")
    intended_use: Optional[str] = Field(None, max_length=200, description="Self-described use case — optional")


class CreateKeyResponse(BaseModel):
    key:         str
    key_prefix:  str
    tier:        str
    rate_limit_rpm: int
    rate_limit_day: int
    message:     str


@router.post("/create", response_model=CreateKeyResponse, summary="Request a free API key")
async def create_key(body: CreateKeyRequest):
    """
    Issue a free-tier CometCloud API key.

    The full key is returned **once** — store it securely.
    Only the SHA-256 hash is retained server-side.

    Free tier: 60 req/min, 1,000 req/day.
    Pro tier available on request: jazz@cometcloud.ai
    """
    # Only free tier via self-serve — pro is manual
    tier = "free"
    rpm, rpd = 60, 1000

    key = _generate_key()
    key_prefix = key[:12]  # "cc_live_XXXX" — safe to display

    await _sb_post("api_keys", {
        "key_prefix":     key_prefix,
        "key_hash":       _hash_key(key),
        "name":           body.name,
        "email":          body.email,
        # The live column is `notes`, NOT `intended_use` (2026-08-11). The request
        # model and scripts/supabase_all_tables.sql both say intended_use; the table
        # has never had it. PostgREST answers an unknown column with a 400, `_sb_post`
        # collapsed every failure into "Key storage failed", and so the endpoint has
        # returned the same opaque 500 since it was written — zero keys ever issued.
        #
        # The bug is one word. What made it expensive is that the error message named
        # no cause, so it was diagnosed wrong three times (anon lacks INSERT; the
        # service key is missing; id has no sequence — id is GENERATED ALWAYS AS
        # IDENTITY, and for identity columns information_schema reports
        # column_default = null, which is exactly what a missing default looks like).
        # A generic failure message does not merely fail to help; it actively funds
        # plausible wrong answers. See the status/body now surfaced in _sb_post.
        "notes":          body.intended_use or "",
        "tier":           tier,
        "rate_limit_rpm": rpm,
        "rate_limit_day": rpd,
    })

    _log.info(f"[keys] New {tier} key issued: {key_prefix}*** ({body.email})")

    return CreateKeyResponse(
        key=key,
        key_prefix=key_prefix,
        tier=tier,
        rate_limit_rpm=rpm,
        rate_limit_day=rpd,
        message=(
            "Store this key securely — it will not be shown again. "
            "Pass it as the X-API-Key header on all requests. "
            "Free tier: 60 req/min, 1,000 req/day. "
            "Need higher limits? Email jazz@cometcloud.ai"
        ),
    )


@router.get("/verify", summary="Verify an API key is valid")
async def verify_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Check if an API key is active. Returns tier and rate limits."""
    row = await lookup_key(x_api_key)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return {
        "valid":           True,
        "key_prefix":      row["key_prefix"],
        "tier":            row["tier"],
        "rate_limit_rpm":  row["rate_limit_rpm"],
        "rate_limit_day":  row["rate_limit_day"],
    }


@router.get("/tiers", summary="Public tier limits reference")
async def get_tiers():
    """Returns available API tiers and their rate limits."""
    return {
        "tiers": [
            {"tier": "anon",     "rate_limit_rpm": 10,   "rate_limit_day": 100,   "description": "Unauthenticated — IP-based"},
            {"tier": "free",     "rate_limit_rpm": 60,   "rate_limit_day": 1000,  "description": "Free — developer access, no credit card"},
            {"tier": "pro",      "rate_limit_rpm": 300,  "rate_limit_day": 50000, "description": "Pro — production workloads, contact jazz@cometcloud.ai"},
            {"tier": "internal", "rate_limit_rpm": 5000, "rate_limit_day": 999999,"description": "Internal — reserved"},
        ],
        "header": "X-API-Key",
        "key_format": "cc_live_<32 hex chars>",
        "get_key": "POST /api/v1/keys/create",
    }
