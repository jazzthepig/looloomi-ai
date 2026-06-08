"""
Looloomi AI — FastAPI Backend v0.6.1
Modular router architecture. God-file main.py split complete.

Routers:
  src/api/routers/market.py       — /api/v1/market/*, /api/v1/defi/*, /api/v1/mmi/*, /api/v1/signals
  src/api/routers/cis.py          — /api/v1/cis/*, /api/v1/agent/cis, /ws/cis, /internal/cis-scores
  src/api/routers/intelligence.py — /api/v1/intelligence/*, /api/v1/vc/*
  src/api/routers/vault.py        — /api/v1/vault/*, /api/v1/portfolio/*
  src/api/routers/onchain.py      — /api/v1/onchain/*
  src/api/routers/macro.py        — /api/v1/macro/*, /internal/macro-brief
  src/api/routers/quant.py        — /api/v1/quant/*, /internal/quant-push
  src/api/routers/auth.py         — /api/v1/auth/*
  src/api/routers/leads.py        — /api/v1/leads/*
  src/api/routers/social.py       — /api/v1/social/*
  src/api/routers/share.py        — /api/v1/share/og-image
  src/api/routers/factory.py      — /api/v1/factory/*
  src/api/routers/agent.py        — /api/v1/agent/tasks (A2A Phase 2.3)
  src/api/routers/keys.py         — /api/v1/keys/* (API key issuance + verification)
  src/api/routers/webhooks.py     — /api/v1/webhooks/* (grade-change push subscriptions)
  src/api/routers/trading.py      — /api/v1/trading/* (paper trading + signal queue + data mining)
  src/api/routers/vector.py       — /api/v1/cis/similar, /api/v1/cis/cluster, /api/v1/cis/embeddings,
                                     /api/v1/market/funding-rates, /api/v1/market/trending-overlay
  src/api/routers/factors.py      — /api/v1/factors/*, factor registry + §F-SEL + performance tracking
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from src.api.routers.market import router as market_router
from src.api.routers.cis import router as cis_router
from src.api.routers.intelligence import router as intelligence_router
from src.api.routers.vault import router as vault_router
from src.api.routers.onchain import router as onchain_router
from src.api.routers.macro import router as macro_router
from src.api.routers.quant import router as quant_router
from src.api.routers.auth import router as auth_router
from src.api.routers.leads import router as leads_router
from src.api.routers.social import router as social_router
from src.api.routers.factory import router as factory_router
from src.api.routers.share import router as share_router
from src.api.routers.agent import router as agent_router
from src.api.routers.keys import router as keys_router
from src.api.routers.webhooks  import router as webhooks_router
from src.api.routers.analytics import router as analytics_router
from src.api.routers.trading import router as trading_router
from src.api.routers.vector import router as vector_router
from src.api.routers.factors import router as factors_router
from src.api.routers.discovery import router as discovery_router
from src.api.routers.strategies import router as strategies_router
from src.api.routers.signals import router as signals_router
from src.api.middleware.rate_limit import RateLimitMiddleware

_ENV = os.environ.get("ENVIRONMENT", "production")

app = FastAPI(title="Looloomi AI API", version="0.6.3")

app.add_middleware(GZipMiddleware, minimum_size=500)  # ~60% payload reduction for agents
app.add_middleware(RateLimitMiddleware)               # sliding-window rate limiter (Upstash Redis)
_frontend_origins = os.environ.get(
    "FRONTEND_ORIGINS",
    "https://looloomi.ai,https://looloomi.com,http://localhost:5173,http://localhost:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Security + LLM discoverability headers — applied to every response
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # llms.txt discoverability — tells LLM crawlers where to find structured docs
    response.headers["Link"] = '</llms.txt>; rel="llms-txt"'
    response.headers["X-Llms-Txt"] = "/llms.txt"
    return response

app.include_router(market_router)
app.include_router(cis_router)
app.include_router(intelligence_router)
app.include_router(vault_router)
app.include_router(onchain_router)
app.include_router(macro_router)
app.include_router(quant_router)
app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(social_router)
app.include_router(factory_router)
app.include_router(share_router)
app.include_router(agent_router)
app.include_router(keys_router)
app.include_router(webhooks_router)
app.include_router(analytics_router)
app.include_router(trading_router)
app.include_router(vector_router)
app.include_router(factors_router)
app.include_router(discovery_router)
app.include_router(strategies_router)
app.include_router(signals_router)


# ── Daily signal-outcome resolver ─────────────────────────────────────────────
# Resolves 30-day directional outcomes (WIN/LOSS/EXPIRED) for matured signals.
# Runs ~once/day in-process so the LP track-record metrics stay current without
# depending on the Mac Mini OHLCV pipeline. Idempotent (only touches NULL rows).
import asyncio as _asyncio

_OUTCOME_INTERVAL_S = 24 * 3600   # daily


async def _outcome_tracker_loop():
    # small startup delay so the app is fully up before the first run
    await _asyncio.sleep(120)
    while True:
        try:
            from src.data.signals.outcome_tracker import run_outcome_tracker
            summary = await run_outcome_tracker(dry_run=False)
            print(f"[OUTCOME] daily run — resolved={summary.get('resolved')} "
                  f"win={summary.get('wins')} loss={summary.get('losses')} "
                  f"written={summary.get('rows_written')}")
        except Exception as _e:
            print(f"[OUTCOME] ⚠️  daily run failed: {_e}")
        await _asyncio.sleep(_OUTCOME_INTERVAL_S)


@app.on_event("startup")
async def _start_outcome_tracker():
    if os.environ.get("DISABLE_OUTCOME_TRACKER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_outcome_tracker_loop())
        print("[OUTCOME] ✅ daily outcome-tracker loop scheduled")


# ── Heartbeat / observability loop ────────────────────────────────────────────
# Polls the health verdict and alerts Telegram on a status transition (plus a
# once-daily digest). This is the loop that turns reactive firefighting into
# proactive alerts — it would have caught today's stale-push / drift / empty-
# universe incidents the moment they happened.
_HEARTBEAT_INTERVAL_S = 20 * 60   # every 20 min


async def _heartbeat_loop():
    await _asyncio.sleep(180)   # let the app + caches warm first
    while True:
        try:
            from src.api.health import heartbeat_tick
            summary = await heartbeat_tick()
            print(f"[HEARTBEAT] status={summary.get('status')}")
        except Exception as _e:
            print(f"[HEARTBEAT] ⚠️  tick failed: {_e}")
        await _asyncio.sleep(_HEARTBEAT_INTERVAL_S)


@app.on_event("startup")
async def _start_heartbeat():
    if os.environ.get("DISABLE_HEARTBEAT", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_heartbeat_loop())
        print("[HEARTBEAT] ✅ observability loop scheduled (Telegram alerts)")


# ── MCP Server (ROADMAP_A2A Phase 2.2) ───────────────────────────────────────
# Mounts the CometCloud MCP tool server at /mcp using streamable-HTTP transport.
# Any MCP-compatible agent (Claude, GPT, Gemini, Cursor) can query CIS scores
# and fund data natively at https://looloomi.ai/mcp.
# Fail-safe: if mcp[cli] dep is missing the main app still runs.

try:
    from src.mcp.cometcloud_mcp import mcp as _cometcloud_mcp
    # SSE transport: GET /mcp/sse (stream), POST /mcp/messages (send)
    # Clients: Claude Desktop, Cursor, any MCP-compatible agent
    app.mount("/mcp", _cometcloud_mcp.sse_app())
    print("[MCP] ✅ Mounted at /mcp/sse — ROADMAP_A2A Phase 2.2")
except Exception as _mcp_err:
    print(f"[MCP] ⚠️  Not mounted: {_mcp_err}")


# ── Agent Discovery (A2A v0.3) ────────────────────────────────────────────────

_AGENT_CARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".well-known", "agent.json"
)

# Load once at startup — static file, never changes at runtime
try:
    with open(_AGENT_CARD_PATH) as f:
        _AGENT_CARD: dict | None = json.load(f)
except Exception:
    _AGENT_CARD = None

@app.get("/.well-known/agent.json", include_in_schema=False)
async def agent_card():
    """A2A Agent Card — standard discovery document for agent-to-agent protocols."""
    if _AGENT_CARD is None:
        return JSONResponse(status_code=404, content={"error": "agent card not found"})
    return JSONResponse(content=_AGENT_CARD)


# ── Health ────────────────────────────────────────────────────────────────────
# Two endpoints: /health for Railway direct, /api/v1/health to bypass Cloudflare SPA cache.

_health_payload = {
    "status":  "healthy",
    "version": "0.6.3",
    "environment": _ENV,
    "sources": ["binance", "defillama", "alternative.me", "moralis", "etherscan"],
}

@app.get("/health")
async def health():
    return _health_payload

@app.get("/api/v1/health")
async def health_api():
    """API-prefixed health check — bypasses Cloudflare SPA caching rules."""
    return _health_payload


# ── Build/deploy self-introspection ───────────────────────────────────────────
# Answers the question Jazz asks every session: "what's actually LIVE on Railway,
# and is my local HEAD ahead of it?" The running instance reports the git sha it
# was built from (Railway injects RAILWAY_GIT_COMMIT_SHA) so a local script can
# diff live-sha vs `git rev-parse HEAD` and count undeployed commits. Also surfaces
# the freshness + provenance of the last Mac Mini push, so deploy health and data
# health are visible in one place. Public read (git sha is non-sensitive).
import time as _time

_BOOT_TS = _time.time()


@app.get("/internal/health-summary")
async def health_summary():
    """One health verdict over Mac Mini push freshness, universe, contract drift,
    and MacroBrief. Read by the heartbeat loop + ops. Public read (no secrets)."""
    from src.api.health import compute_health_summary
    return await compute_health_summary()


@app.post("/internal/notify/test")
async def notify_test(payload: dict = None, x_internal_token: str = Header(None)):
    """Send a test Telegram alert. INTERNAL_TOKEN guarded. Confirms env wiring."""
    _tok = os.environ.get("INTERNAL_TOKEN", "")
    if not _tok or x_internal_token != _tok:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    from src.api.notify import notify_telegram, telegram_configured
    msg = (payload or {}).get("text") or "✅ CometCloud alerts wired — Telegram is live."
    ok = await notify_telegram(msg)
    return {"configured": telegram_configured(), "sent": ok}


@app.get("/internal/build-state")
async def build_state():
    try:
        from src.api.contracts.cis_push import SCHEMA_VERSION
    except Exception:
        SCHEMA_VERSION = "unknown"

    git_sha = (
        os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("GIT_COMMIT_SHA")
        or os.environ.get("SOURCE_COMMIT")
        or ""
    )

    # Last Mac Mini push: freshness + provenance (from the CIS hot cache)
    last_push = {"present": False}
    try:
        from src.api.store import redis_get
        cached = await redis_get()
        if cached:
            age = _time.time() - float(cached.get("last_updated") or 0)
            uni = cached.get("universe") or []
            prov = cached.get("provenance") or {}
            last_push = {
                "present":         True,
                "age_seconds":     round(age, 1),
                "stale":           age > 3600,   # pushes are ~30min; >1h = problem
                "asset_count":     len(uni),
                "schema_version":  cached.get("schema_version"),
                "engine_git_sha":  prov.get("engine_git_sha"),
                "config_hash":     prov.get("config_hash"),
                "drift_warnings":  len(cached.get("contract_warnings") or []),
            }
    except Exception as _e:
        last_push = {"present": False, "error": str(_e)}

    return {
        "service":         "looloomi-api",
        "version":         app.version,
        "environment":     _ENV,
        "git_sha":         git_sha,
        "git_sha_short":   git_sha[:8] if git_sha else None,
        "git_branch":      os.environ.get("RAILWAY_GIT_BRANCH"),
        "deployment_id":   os.environ.get("RAILWAY_DEPLOYMENT_ID"),
        "contract_schema_version": SCHEMA_VERSION,
        "route_count":     len(app.routes),
        "uptime_seconds":  round(_time.time() - _BOOT_TS, 1),
        "last_cis_push":   last_push,
        "as_of":           _time.time(),
    }


# ── Serve React SPA ───────────────────────────────────────────────────────────

dashboard_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "dashboard", "dist"
)
if os.path.exists(dashboard_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(dashboard_path, "assets")), name="assets")

    @app.get("/")
    async def serve_dashboard():
        return FileResponse(os.path.join(dashboard_path, "index.html"))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # API/internal/ws/mcp paths that don't match any router → 404 JSON (not SPA fallback)
        _api_prefixes = ("api/", "internal/", "ws/", "mcp/", ".env", "config", "secrets", "admin", ".git")
        if any(full_path.startswith(p) for p in _api_prefixes):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        file_path = os.path.join(dashboard_path, full_path)
        try:
            return FileResponse(file_path)
        except FileNotFoundError:
            pass
        return FileResponse(os.path.join(dashboard_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
