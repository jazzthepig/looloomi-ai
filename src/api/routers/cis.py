"""
CIS router — scoring, history, backtest, agent API, WebSocket, internal push
Endpoints: /api/v1/cis/*, /api/v1/agent/cis, /ws/cis, /internal/cis-scores
"""
import os, json as _json, time, asyncio, re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header, WebSocket, WebSocketDisconnect

from src.api.store import (
    redis_set, redis_get,
    supabase_insert_batch, supabase_get_history,
    sanitize_floats, ws_manager,
)
import src.api.store as store

router = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


def _p(asset: dict, key: str):
    """Read pillar score — handles flat keys (local engine) and nested pillars dict (Railway)."""
    v = asset.get(key)
    if v is not None:
        return v
    return asset.get("pillars", {}).get(key.upper())


# ── Internal push (Mac Mini → Railway) ───────────────────────────────────────

@router.post("/internal/cis-scores")
async def receive_local_cis_scores(payload: dict, x_internal_token: str = Header(None)):
    """
    Receives CIS scores from the local Mac Mini engine (cis_push.py).
    Writes to Upstash Redis (hot cache) and Supabase (score history).
    Triggers WebSocket broadcast to connected clients.
    """
    # Reject-by-default: require token always (fail secure if env var missing)
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        universe  = payload.get("universe", [])
        timestamp = payload.get("timestamp", datetime.now().isoformat())

        cache_data = {
            "universe":     universe,
            "last_updated": time.time(),
            "timestamp":    timestamp,
            "source":       "local_engine",
        }

        # 1. Write to Redis (hot cache, 2h TTL)
        ok = await redis_set(cache_data)
        print(f"[INTERNAL] Received {len(universe)} CIS scores — Redis write: {ok}")

        # 2. Write to Supabase (score history, persistent)
        sb_ok = False
        if universe:
            sb_rows = []
            for asset in universe:
                pillars = asset.get("pillars", {})
                sb_rows.append({
                    "symbol":      asset.get("symbol", ""),
                    "name":        asset.get("name", ""),
                    "score":       asset.get("cis_score") or asset.get("score"),
                    "grade":       asset.get("grade"),
                    "signal":      asset.get("signal"),
                    "percentile":  asset.get("percentile_rank"),
                    "pillar_f":    pillars.get("F") if isinstance(pillars, dict) else None,
                    "pillar_m":    pillars.get("M") if isinstance(pillars, dict) else None,
                    "pillar_o":    pillars.get("O") if isinstance(pillars, dict) else None,
                    "pillar_s":    pillars.get("S") if isinstance(pillars, dict) else None,
                    "pillar_a":    pillars.get("A") if isinstance(pillars, dict) else None,
                    "asset_class": asset.get("asset_class", asset.get("class", "")),
                    "source":      "local_engine",
                })
            sb_ok = await supabase_insert_batch(sb_rows)
            print(f"[INTERNAL] Supabase history write: {sb_ok} ({len(sb_rows)} rows)")

        # 3. Broadcast to WebSocket clients
        asyncio.create_task(_broadcast_cis_update(universe))

        return {"status": "success", "received": len(universe), "cached": ok, "history_written": sb_ok}
    except Exception as e:
        print(f"[INTERNAL] Error receiving CIS scores: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── CIS Universe ──────────────────────────────────────────────────────────────

@router.get("/api/v1/cis/universe")
async def get_cis_universe(force_source: str = None):
    """
    CIS v4.0 Universe — priority: local_engine (Redis) → Railway calc → stale Redis fallback
    """
    from src.data.cis.cis_provider import calculate_cis_universe

    cached   = None
    use_local = False

    if force_source != "railway":
        cached = await redis_get()
        if cached and cached.get("universe"):
            age = time.time() - cached.get("last_updated", 0)
            if age < 7200 or force_source == "local":
                use_local = True

    if use_local:
        return {
            "status":    "success",
            "version":   "4.0.0",
            "timestamp": cached["timestamp"],
            "source":    "local_engine",
            "universe":  cached["universe"],
        }

    try:
        result = await calculate_cis_universe()
        result["source"] = "railway"
        return sanitize_floats(result)
    except Exception as e:
        print(f"[CIS] Railway calculation error: {e}")
        if cached and cached.get("universe"):
            return {
                "status":   "degraded",
                "message":  str(e),
                "source":   "local_engine_stale",
                "universe": cached["universe"],
            }
        return {"status": "error", "message": str(e), "universe": []}


@router.get("/api/v1/cis/asset/{symbol}")
async def get_cis_asset(symbol: str):
    """Get CIS score for a specific asset."""
    universe = await get_cis_universe()
    for asset in universe.get("universe", []):
        if asset["symbol"].upper() == symbol.upper():
            return asset
    return {"error": "Asset not found"}


# ── CIS History ───────────────────────────────────────────────────────────────
# IMPORTANT: batch route MUST be registered before {symbol} route to avoid shadowing

@router.get("/api/v1/cis/history/batch")
async def get_cis_history_batch(symbols: str, days: int = 7):
    """
    Batch CIS history — single request for all symbols.
    Eliminates N+1 sparkline fetches. Returns map of symbol → history array.
    """
    _SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}(,[A-Z0-9]{2,12})*$")
    if not _SYMBOL_RE.match(symbols.upper()):
        return {"status": "error", "message": "Invalid symbol format", "data": {}}
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:60]
    if not symbol_list:
        return {"status": "error", "message": "No symbols provided", "data": {}}

    results = await asyncio.gather(
        *[supabase_get_history(sym, days) for sym in symbol_list],
        return_exceptions=True,
    )

    data = {}
    for sym, rows in zip(symbol_list, results):
        data[sym] = [] if isinstance(rows, Exception) or not rows else list(reversed(rows))

    return {"status": "success", "days": days, "count": len(data), "data": data}


@router.get("/api/v1/cis/history/{symbol}")
async def get_cis_history(symbol: str, days: int = 7):
    """CIS score history for sparklines. Up to days*48 data points (30-min intervals)."""
    rows = await supabase_get_history(symbol.upper(), days)
    if not rows:
        return {"status": "empty", "symbol": symbol.upper(), "days": days, "history": []}
    return {
        "status":  "success",
        "symbol":  symbol.upper(),
        "days":    days,
        "count":   len(rows),
        "history": list(reversed(rows)),  # chronological for sparklines
    }


# ── Backtest ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/cis/backtest")
async def get_cis_backtest():
    """
    30d realized return results by CIS grade (Binance/OKX klines).
    Used to validate scoring — shows A/B/C return spread.
    """
    results_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "cis", "backtest_results.json"
    )
    try:
        if os.path.exists(results_path):
            with open(results_path) as f:
                data = _json.load(f)
            return {"status": "success", "source": "file", **data}
    except Exception as e:
        print(f"[BACKTEST] Read error: {e}")

    try:
        from src.data.cis.history_db import get_backtest_summary
        summary = get_backtest_summary()
        return {"status": "success", "source": "db", **summary}
    except Exception as e:
        return {"status": "empty", "message": str(e)}


# ── Agent API ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/agent/cis")
async def agent_cis_endpoint():
    """
    Agent-optimized CIS endpoint: minimal JSON, no HTML/comments.
    Pillar keys: f/m/r/ss/a → F/M/O/S/A pillars.
    """
    from src.data.cis.cis_provider import calculate_cis_universe

    cached = await redis_get()
    if cached and cached.get("universe"):
        universe = cached["universe"]
    else:
        try:
            result = await calculate_cis_universe()
            universe = result.get("universe", [])
        except Exception:
            universe = []

    return {
        "v":  "4.0",
        "ts": cached.get("timestamp") if cached else datetime.now().isoformat(),
        "assets": [
            {
                "s":  a["symbol"],
                "g":  a.get("grade", "?"),
                "sc": a.get("cis_score", a.get("score", 0)),
                "sg": a.get("signal", "?"),
                "f":  _p(a, "f"),
                "m":  _p(a, "m"),
                "r":  _p(a, "r"),
                "ss": _p(a, "s"),
                "a":  _p(a, "a"),
                "ch30d":  a.get("change_30d"),
                "ch7d":   a.get("change_7d"),
                "vol":    a.get("volatility_30d"),
                "mc":     a.get("market_cap"),
                "vol24h": a.get("volume_24h"),
                "tvl":    a.get("tvl"),
                "conf":   a.get("confidence"),
            }
            for a in universe
        ],
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/cis")
async def websocket_cis(websocket: WebSocket):
    """
    Real-time CIS score updates. Sends current state immediately on connect.
    Supports ping/pong keepalive. Requires auth via first message: "auth:<INTERNAL_TOKEN>"
    """
    await websocket.accept()
    # Auth via first message — must contain valid token
    try:
        msg = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if msg != f"auth:{_INTERNAL_TOKEN}":
            await websocket.close(code=4001, reason="Unauthorized")
            return
    except asyncio.TimeoutError:
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except Exception:
        await websocket.close(code=4001, reason="Auth error")
        return

    await ws_manager.connect(websocket)

    if store.last_cis_broadcast:
        await websocket.send_json(store.last_cis_broadcast)

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
            except Exception:
                break
    except Exception:
        pass
    finally:
        ws_manager.disconnect(websocket)


async def _broadcast_cis_update(universe: list):
    """Called by internal push endpoint when new scores arrive."""
    store.last_cis_broadcast = {
        "type":      "full",
        "timestamp": datetime.now().isoformat(),
        "count":     len(universe),
        "assets": [
            {
                "s":     a["symbol"],
                "g":     a.get("grade", "?"),
                "sc":    a.get("cis_score", a.get("score", 0)),
                "sg":    a.get("signal", "?"),
                "f":     _p(a, "f"),
                "m":     _p(a, "m"),
                "r":     _p(a, "r"),
                "ss":    _p(a, "s"),
                "a":     _p(a, "a"),
                "ch30d": a.get("change_30d"),
                "ch7d":  a.get("change_7d"),
            }
            for a in universe
        ],
    }
    await ws_manager.broadcast(store.last_cis_broadcast)
