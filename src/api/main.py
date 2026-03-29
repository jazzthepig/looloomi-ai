"""
Looloomi AI — FastAPI Backend v0.4.0
Modular router architecture. God-file main.py split complete.

Routers:
  src/api/routers/market.py       — /api/v1/market/*, /api/v1/defi/*, /api/v1/mmi/*, /api/v1/signals
  src/api/routers/cis.py          — /api/v1/cis/*, /api/v1/agent/cis, /ws/cis, /internal/cis-scores
  src/api/routers/intelligence.py — /api/v1/intelligence/*, /api/v1/vc/*
  src/api/routers/vault.py        — /api/v1/vault/*, /api/v1/portfolio/*
  src/api/routers/onchain.py      — /api/v1/onchain/*
  src/api/routers/macro.py        — /api/v1/macro/*, /internal/macro-brief
  src/api/routers/quant.py        — /api/v1/quant/*, /internal/quant-push
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI, Request
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

app = FastAPI(title="Looloomi AI API", version="0.4.3")

app.add_middleware(GZipMiddleware, minimum_size=500)  # ~60% payload reduction for agents
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

# Security headers — applied to every response
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
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


# ── Agent Discovery (A2A v0.3) ────────────────────────────────────────────────

_AGENT_CARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".well-known", "agent.json"
)

@app.get("/.well-known/agent.json", include_in_schema=False)
async def agent_card():
    """A2A Agent Card — standard discovery document for agent-to-agent protocols."""
    try:
        with open(_AGENT_CARD_PATH) as f:
            return JSONResponse(content=json.load(f))
    except Exception:
        return JSONResponse(status_code=404, content={"error": "agent card not found"})


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":  "healthy",
        "version": "0.4.0",
        "sources": ["binance", "defillama", "alternative.me", "moralis", "etherscan"],
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
        # API/internal/ws paths that don't match any router → 404 JSON (not SPA fallback)
        _api_prefixes = ("api/", "internal/", "ws/", ".env", "config", "secrets", "admin", ".git")
        if any(full_path.startswith(p) for p in _api_prefixes):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        file_path = os.path.join(dashboard_path, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(dashboard_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
