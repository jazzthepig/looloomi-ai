"""
Rate Limit Middleware — CometCloud AI
=======================================
Sliding-window rate limiter using Upstash Redis.

Tiers:
  dashboard 600 rpm / ∞       — same-origin (Referer matches FRONTEND_ORIGINS) — never throttled
  anon      120 rpm / 2000 rpd — unauthenticated external, IP-keyed
  free       60 rpm / 1000 rpd — X-API-Key present, free tier
  pro       300 rpm / 50000 rpd — X-API-Key present, pro tier
  internal  5000 rpm / ∞       — internal token, no limit enforced

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
from fastapi.responses import JSONResponse, HTMLResponse
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

# T-013 (2026-09-26): page routes still count against the limit (DoS protection
# stays in force) but a 429 on a page request returns HTML 200, NOT JSON 429 —
# the prior behaviour put `{"error":"rate_limit_exceeded"}` in front of the
# landing page, which is a JSON response on a /  URL. An API path that hits
# 429 keeps its JSON envelope. Detection: anything that does NOT start with
# one of these prefixes is a "page request" (HTML-served).
_API_PREFIXES = ("/api/", "/internal/", "/ws/", "/mcp/", "/mcp-sse")


def _is_page_request(path: str) -> bool:
    return not any(path.startswith(p) for p in _API_PREFIXES)


_HTML_429 = (
    "<!doctype html><html lang=en><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>CometCloud — rate limited</title>"
    "<meta http-equiv=refresh content='{retry_after}'>"
    "<style>body{{font-family:system-ui;background:#020208;color:#cbd5e1;"
    "display:flex;min-height:100vh;align-items:center;justify-content:center;"
    "margin:0}}main{{max-width:480px;padding:32px;text-align:center}}"
    "h1{{font-weight:600;font-size:18px;color:#e2e8f0;margin:0 0 8px}}"
    "p{{font-size:13px;line-height:1.6;opacity:0.72;margin:8px 0 0}}"
    "code{{font-family:ui-monospace,monospace;font-size:12px;color:#06b6b4}}"
    "</style></head><body><main>"
    "<h1>Rate limited</h1>"
    "<p>You've sent more than <code>{limit}</code> requests per {window_label} "
    "from this IP. The page will refresh automatically in <code>{retry_after}s</code>.</p>"
    "<p>Authenticated users and the dashboard itself are not affected.</p>"
    "</main></body></html>"
)

# Same-origin dashboard origins — treated as trusted, very high limit
#
# 2026-09-18: added Railway auto-URL to the default. Without it, anyone who
# opened the dashboard at `web-production-0cdf76.up.railway.app` (instead of
# looloomi.ai) was falling through to the anon bucket — 120 rpm / 2000 rpd —
# and the first burst on the CIS page (six components each fetching
# /api/v1/cis/universe) tripped 429, then Asset Radar showed "Data unavailable"
# because the same endpoint was already rate-limited. The dashboard IS the
# dashboard, on every host we ship it on.
_FRONTEND_ORIGINS = set(
    os.getenv(
        "FRONTEND_ORIGINS",
        "https://looloomi.ai,https://looloomi.com,https://web-production-0cdf76.up.railway.app,"
        "http://localhost:5173,http://localhost:8000"
    ).split(",")
)


def _is_same_origin(request: Request) -> bool:
    """True if request comes from our own dashboard (Referer or Origin header matches)."""
    for header in ("referer", "origin"):
        val = request.headers.get(header, "").strip().rstrip("/")
        if val and any(val.startswith(o.rstrip("/")) for o in _FRONTEND_ORIGINS):
            return True
    return False

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

        # Same-origin dashboard requests — high limit, never blocks the UI
        if not raw_key and _is_same_origin(request):
            forwarded = request.headers.get("X-Forwarded-For", "")
            ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
            identity  = f"dash:{ip}"
            rpm_limit = 600
            rpd_limit = 0  # no daily cap for dashboard
        elif raw_key:
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
            # Anon external — IP-based
            forwarded = request.headers.get("X-Forwarded-For", "")
            identity  = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
            identity  = f"ip:{identity}"
            rpm_limit = 120
            rpd_limit = 2000

        # Check minute window
        rpm_count = await _redis_incr(f"rl:rpm:{identity}", 60)
        if rpm_count > rpm_limit:
            return self._rate_limited_response(
                request=request, window="minute", limit=rpm_limit,
                window_label="minute", retry_after=60)

        # Check day window (skip if rpd_limit == 0 = unlimited)
        rpd_count = await _redis_incr(f"rl:rpd:{identity}", 86400) if rpd_limit > 0 else 0
        if rpd_limit > 0 and rpd_count > rpd_limit:
            return self._rate_limited_response(
                request=request, window="day", limit=rpd_limit,
                window_label="day", retry_after=86400)

        response = await call_next(request)

        # Attach rate limit headers
        response.headers["X-RateLimit-Limit"]     = str(rpm_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, rpm_limit - rpm_count))

        return response

    def _rate_limited_response(
            self, *, request: Request, window: str, limit: int,
            window_label: str, retry_after: int):
        """T-013: page requests get HTML 200; API requests keep JSON 429.

        The page HTML embeds a `<meta http-equiv=refresh>` so the browser
        auto-retries after `retry_after` seconds — this avoids the JSON-in-a-
        browser-URL failure mode where the user gets a wall of `{"error":...}`
        on what is supposed to be a marketing page. API requests keep the
        structured JSON envelope (`status_code=429`) so SDK consumers can
        parse `Retry-After` / `error`.
        """
        path = request.url.path
        if _is_page_request(path):
            body = _HTML_429.format(
                retry_after=retry_after, limit=limit, window_label=window_label)
            return HTMLResponse(
                content=body,
                status_code=200,
                headers={
                    "Retry-After":     str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Window": window,
                },
            )
        return JSONResponse(
            status_code=429,
            content={
                "error":        "rate_limit_exceeded",
                "window":       window,
                "limit":        limit,
                "message":      (
                    f"Rate limit: {limit} req/{window_label}. "
                    f"Upgrade at jazz@cometcloud.ai"
                    if window == "minute"
                    else f"Daily limit: {limit} req/day. "
                         f"Need more? Email jazz@cometcloud.ai"),
                "retry_after":  retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
            },
        )
