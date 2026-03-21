"""
Quant router — Freqtrade dry-run monitoring + Mac Mini push
Endpoints:
  GET  /api/v1/quant/status    — current open trades, balance (from Redis cache)
  GET  /api/v1/quant/trades   — trade history
  GET  /api/v1/quant/equity   — equity curve
  POST /internal/quant-push    — Mac Mini pushes Freqtrade status (auth required)
"""
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header

from src.api.store import redis_set_key, redis_get_key

router = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
_REDIS_KEY_STATUS = "quant:status"
_REDIS_KEY_TRADES = "quant:trades"
_REDIS_KEY_EQUITY = "quant:equity"
_REDIS_TTL = 300  # 5 minutes — stale data should be evident


# ── Internal push (Mac Mini → Railway) ───────────────────────────────────────

@router.post("/internal/quant-push")
async def receive_quant_status(payload: dict, x_internal_token: str = Header(None)):
    """
    Receives Freqtrade dry-run status from Mac Mini.
    Mac Mini polls Freqtrade REST API (port 18432) every 30s and pushes here.
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not payload:
        raise HTTPException(status_code=400, detail="Empty payload")

    # Extract the three data types
    status_data = payload.get("status", {})
    trades_data = payload.get("trades", [])
    equity_data = payload.get("equity", {})

    ts = datetime.now().isoformat()

    if status_data:
        await redis_set_key(_REDIS_KEY_STATUS, {**status_data, "_ts": ts}, ttl=_REDIS_TTL)
    if trades_data:
        # Append to trade history (keep last 100)
        existing = await redis_get_key(_REDIS_KEY_TRADES) or []
        updated = trades_data + existing
        await redis_set_key(_REDIS_KEY_TRADES, updated[:100], ttl=_REDIS_TTL * 10)
    if equity_data:
        await redis_set_key(_REDIS_KEY_EQUITY, {**equity_data, "_ts": ts}, ttl=_REDIS_TTL)

    count_status = 1 if status_data else 0
    count_trades = len(trades_data)
    print(f"[QUANT] Push received — status={count_status} trades={count_trades}")
    return {"ok": True, "timestamp": ts}


# ── Public endpoints (served to QuantMonitor page) ──────────────────────────

@router.get("/api/v1/quant/status")
async def get_quant_status():
    """
    Current dry-run trading status: open trades, balance, daily P&L.
    Data pushed by Mac Mini every 30s. Returns stale data with _stale flag if push missed.
    """
    data = await redis_get_key(_REDIS_KEY_STATUS)
    if not data:
        return {"open_trades": [], "balance": None, "daily_pnl": None, "_stale": True}

    ts = data.pop("_ts", None)
    return {
        "open_trades": data.get("open_trades", []),
        "balance": data.get("balance"),
        "daily_pnl": data.get("daily_pnl"),
        "updated": ts,
        "_stale": False,
    }


@router.get("/api/v1/quant/trades")
async def get_quant_trades(limit: int = 50):
    """Recent trade history from dry run."""
    trades = await redis_get_key(_REDIS_KEY_TRADES) or []
    return {
        "trades": trades[:limit],
        "count": len(trades),
    }


@router.get("/api/v1/quant/equity")
async def get_quant_equity():
    """Current equity and performance metrics."""
    data = await redis_get_key(_REDIS_KEY_EQUITY)
    if not data:
        return {"equity": None, "starting_balance": 10000, "_stale": True}
    ts = data.pop("_ts", None)
    return {
        "equity": data.get("equity"),
        "starting_balance": data.get("starting_balance", 10000),
        "updated": ts,
        "_stale": False,
    }
