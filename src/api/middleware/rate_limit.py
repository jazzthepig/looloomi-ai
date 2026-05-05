"""
Rate Limit Middleware — CometCloud AI
=======================================
Sliding-window rate limiter using Upstash Redis.

Tiers:
  anon      10 rpm / 100 rpd   — unauthenticated, IP-keyed
  free      60 rpm / 1000 rpd  — X-API-Key present, free tier
  pro      300 rpm / 50000 rpd — X-API-Key present, pro tier
  internal 5000 rpm / ∞        — internal token, no limit enforced

Paths exempt from rate limiting:
  /health, /api/v1/health, /.well-known/*, /llms.txt, /static/*, /assets/*
  /mcp/* (SSE — long-lived connection, not per-request)

Redis keys:
  rl:rpm:<identity>   — sliding minute window  (TTL 60s)
  rl:rpd:<identity>   — sliding day window     (TTL 86400s)

Identity:
  - Authenticated: key_prefix (e.g. "cc_live_ab12")
  - Anon: IP address (X-Forwarded-For or client.host)

Author: Seth
"""

import logging
import os
import time
from typing import Optional

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_log = logging.getLogger(__name__)

_UPSTASH_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

# Paths that bypass rate limiting entirely
_EXEMPT_PREFIXES = (
    "/health",
    "/api/v1/health",
    "/.well-known",
    "/llms.txt",
    "/mcp",
    "/static",
    "/assets",
    "/vite.svg",
    "/favicon",
)

# Cache validated keys in memory for 30s to avoid hitting Supabase on every request
_key_cache: dict[str, tuple[dict, float]] = {}
_KEY_CACHE_TTL = 30.0


def _is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in _EXEMPT_PREFIXES) or "." in path.split("/")[-1]


async def _redis_incr(key: str, ttl: int) -> int:
    """INCR key with TTL (only sets TTL on first call). Returns new count."""
    if not _UPSTASH_URL or not _UPSTASH_TOKEN:
        return 1  # no Redis — allow everything
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            # Pipeline: INCR + EXPIRE (only if key is new)
            r = await client.post(
                f"{_UPSTASH_URL}/pipeline",
                json=[
                    ["INCR", key],
                    ["EXPIRE", key, ttl, "NX"],  # NX = only set if not exists
                ],
                headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
            )
            if r.status_code == 200:
                results = r.json()
                return results[0].get("result", 1)
    except Exception as e:
        _log.debug(f"[rate_limit] Redis error: {e}")
    return 1  # fail open — don't block on Redis errors


async def _get_key_row(raw_key: str) -> Optional[dict]:
    """Validate API key with 30s in-process cache."""
    now = time.monotonic()
    cached = _key_cache.get(raw_key)
    if cached:
        row, ts = cached
        if now - ts < _KEY_CACHE_TTL:
            return row

    try:
        from src.api.routers.keys import lookup_key
        row = await lookup_key(raw_key)
        _key_cache[raw_key] = (row, now)
        return row
    except Exception:
        return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter.
    Runs after CORS/GZip but before route handlers.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip exempt paths (static files, health, MCP SSE)
        if _is_exempt(path):
            return await call_next(request)

        # Determine identity + limits
        raw_key = request.headers.get("X-API-Key", "").strip()
        internal_token = request.headers.get("X-Internal-Token", "").strip()
        _INTERNAL = os.getenv("INTERNAL_TOKEN", "")

        # Internal token — skip rate limiting
        if internal_token and _INTERNAL and internal_token == _INTERNAL:
            return await call_next(request)

        if raw_key:
            key_row = await _get_key_row(raw_key)
            if key_row is None:
                return JSONResponse(
                    status_code=401,
                    content={"error": "invalid_api_key", "message": "Invalid or inactive API key. Get one at POST /api/v1/keys/create"},
                )
            identity  = key_row["key_prefix"]
            rpm_limit = key_row["rate_limit_rpm"]
            rpd_limit = key_row["rate_limit_day"]
        else:
            # Anon — IP-based
            forwarded = request.headers.get("X-Forwarded-For", "")
            identity  = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
            identity  = f"ip:{identity}"
            rpm_limit = 10
            rpd_limit = 100

        # Check minute window
        rpm_count = await _redis_incr(f"rl:rpm:{identity}", 60)
        if rpm_count > rpm_limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error":        "rate_limit_exceeded",
                    "window":       "minute",
                    "limit":        rpm_limit,
                    "message":      f"Rate limit: {rpm_limit} req/min. Upgrade at jazz@cometcloud.ai",
                    "retry_after":  60,
                },
                headers={"Retry-After": "60", "X-RateLimit-Limit": str(rpm_limit)},
            )

        # Check day window
        rpd_count = await _redis_incr(f"rl:rpd:{identity}", 86400)
        if rpd_count > rpd_limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error":        "rate_limit_exceeded",
                    "window":       "day",
                    "limit":        rpd_limit,
                    "message":      f"Daily limit: {rpd_limit} req/day. Need more? Email jazz@cometcloud.ai",
                    "retry_after":  86400,
                },
                headers={"Retry-After": "86400", "X-RateLimit-Limit-Day": str(rpd_limit)},
            )

        response = await call_next(request)

        # Attach rate limit headers
        response.headers["X-RateLimit-Limit"]     = str(rpm_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, rpm_limit - rpm_count))

        return response
