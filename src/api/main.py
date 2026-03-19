"""
Looloomi AI - FastAPI Backend v0.3.0
Real data from: Binance + DeFiLlama + Alternative.me + Moralis + Etherscan
"""
from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List
from datetime import datetime
import sys, os, numpy as np, json, time
import httpx
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import CIS data provider
from src.data.cis.cis_provider import calculate_cis_universe

# Import our new data layer
from data.market.data_layer import (
    get_prices_multi, get_price, get_ohlcv, get_top_gainers_losers,
    get_defi_overview, get_dex_volumes, get_protocol_revenues,
    get_stablecoin_overview, get_top_yields, get_vc_raises,
    get_fear_greed, get_wallet_portfolio, get_wallet_defi_positions,
    get_eth_balance, get_eth_transactions, get_token_transfers, get_eth_gas,
    calculate_mmi,
)

# Import macro events scraper
from backend.macro_events_scraper import fetch_all_macro_events

app = FastAPI(title="Looloomi AI API", version="0.3.0")

# ── Upstash Redis (persistent CIS cache across Railway deploys/instances) ────────
_UPSTASH_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_REDIS_KEY     = "cis:local_scores"
_REDIS_TTL     = 7200  # 2 hours

async def _redis_set(data: dict) -> bool:
    """Write CIS payload to Upstash with 2 h TTL."""
    if not _UPSTASH_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{_UPSTASH_URL}/set/{_REDIS_KEY}",
                content=json.dumps(data),
                headers={
                    "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                    "Content-Type": "application/json",
                },
                params={"EX": _REDIS_TTL},
            )
            return resp.status_code == 200
    except Exception as e:
        print(f"[REDIS] SET error: {e}")
        return False

async def _redis_get() -> dict | None:
    """Read CIS payload from Upstash. Returns None on miss/error."""
    if not _UPSTASH_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{_UPSTASH_URL}/get/{_REDIS_KEY}",
                headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
            )
            if resp.status_code == 200:
                raw = resp.json().get("result")
                if raw:
                    return json.loads(raw)
        return None
    except Exception as e:
        print(f"[REDIS] GET error: {e}")
        return None

# ── Supabase (CIS score history) ─────────────────────────────────────────────
_SB_URL   = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY   = os.environ.get("SUPABASE_KEY", "")
_SB_TABLE = "cis_scores"

async def _supabase_insert_batch(rows: list) -> bool:
    """Bulk-insert CIS score rows into Supabase REST API."""
    if not _SB_URL or not _SB_KEY or not rows:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_SB_URL}/rest/v1/{_SB_TABLE}",
                content=json.dumps(rows),
                headers={
                    "apikey":        _SB_KEY,
                    "Authorization": f"Bearer {_SB_KEY}",
                    "Content-Type":  "application/json",
                    "Prefer":        "return=minimal",
                },
            )
            if resp.status_code not in (200, 201):
                print(f"[SUPABASE] INSERT error {resp.status_code}: {resp.text[:200]}")
                return False
            return True
    except Exception as e:
        print(f"[SUPABASE] INSERT exception: {e}")
        return False

async def _supabase_get_history(symbol: str, days: int = 7) -> list:
    """Read CIS score history for one symbol from Supabase."""
    if not _SB_URL or not _SB_KEY:
        return []
    try:
        limit = days * 48  # up to 48 records/day (every 30 min)
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                f"{_SB_URL}/rest/v1/{_SB_TABLE}",
                params={
                    "symbol":  f"eq.{symbol.upper()}",
                    "order":   "recorded_at.desc",
                    "limit":   str(limit),
                    "select":  "score,grade,signal,percentile,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,source,recorded_at",
                },
                headers={
                    "apikey":        _SB_KEY,
                    "Authorization": f"Bearer {_SB_KEY}",
                },
            )
            if resp.status_code == 200:
                return resp.json()
            print(f"[SUPABASE] GET history error {resp.status_code}: {resp.text[:200]}")
            return []
    except Exception as e:
        print(f"[SUPABASE] GET history exception: {e}")
        return []

def _sanitize_floats(obj):
    """Recursively replace NaN/Inf numpy floats with None for JSON compliance."""
    import math
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if hasattr(obj, 'item'):          # numpy scalar (np.float64, np.int64, etc.)
        try:
            val = obj.item()
            return None if isinstance(val, float) and not math.isfinite(val) else val
        except Exception:
            return None
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(i) for i in obj]
    return obj

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PortfolioRequest(BaseModel):
    assets: List[str] = ["BTC", "ETH", "SOL", "BNB", "AVAX"]
    strategy: str = "hrp"

# ── Market endpoints (Binance) ─────────────────────────────────────────────

@app.get("/api/v1/market/prices")
async def get_market_prices(symbols: str = "BTC,ETH,SOL,BNB,AVAX"):
    symbol_list = [s.strip() for s in symbols.split(",")]
    data = await get_prices_multi(symbol_list)
    return {"timestamp": datetime.now().isoformat(), "data": data}

@app.get("/api/v1/market/ohlcv/{symbol}")
async def get_market_ohlcv(symbol: str, interval: str = "1h", limit: int = 100):
    data = await get_ohlcv(symbol, interval, limit)
    if data and "error" in data[0]:
        raise HTTPException(status_code=502, detail=data[0]["error"])
    return {"symbol": symbol, "interval": interval, "data": data}

@app.get("/api/v1/market/movers")
async def get_market_movers():
    return await get_top_gainers_losers()

@app.get("/api/v1/market/gas")
async def get_gas_prices():
    return await get_eth_gas()

# ── DeFi endpoints (DeFiLlama) ─────────────────────────────────────────────

@app.get("/api/v1/defi/overview")
async def defi_overview():
    return await get_defi_overview()

@app.get("/api/v1/defi/dex-volumes")
async def dex_volumes():
    return await get_dex_volumes()

@app.get("/api/v1/defi/revenues")
async def protocol_revenues():
    return await get_protocol_revenues()

@app.get("/api/v1/defi/stablecoins")
async def stablecoins():
    return await get_stablecoin_overview()

@app.get("/api/v1/defi/yields")
async def top_yields(min_tvl: float = 1_000_000, limit: int = 20):
    return {"data": await get_top_yields(min_tvl, limit)}

@app.get("/api/v1/defi/protocol/{slug}")
async def protocol_detail(slug: str):
    from data.market.data_layer import get_protocol
    return await get_protocol(slug)

# ── MMI endpoint (composite: Binance + DeFiLlama + Alternative.me) ──────────

@app.get("/api/v1/mmi/{token}")
async def get_mmi(token: str = "BTC"):
    return await calculate_mmi(token.upper())

@app.get("/api/v1/mmi/sentiment/fear-greed")
async def fear_greed(limit: int = 30):
    return await get_fear_greed(limit)

# ── Signals API ────────────────────────────────────────────────────────────────

@app.get("/api/v1/signals")
async def get_signals():
    """
    Generate trading signals from real market data.
    Combines Fear & Greed, price momentum, DeFi TVL, and market movers.
    Always returns at least the FNG signal regardless of market conditions.
    """
    signals = []
    now = datetime.now()

    try:
        # 1. Fear & Greed Index — always generate, regardless of value range
        fng = await get_fear_greed(limit=1)
        if fng.get("current"):
            fng_val = fng["current"].get("value", 50)
            fng_time = fng["current"].get("update_time", "")

            if fng_val <= 20:
                sig_type = "RISK"; sig_imp = "HIGH"
                sig_desc = f"F&G指数极度恐惧({fng_val})，历史数据显示此时入场BTC长期回报优异"
            elif fng_val <= 40:
                sig_type = "RISK"; sig_imp = "MED"
                sig_desc = f"F&G指数恐惧({fng_val})，市场情绪低迷但未至极端，可关注优质标的"
            elif fng_val <= 60:
                sig_type = "MACRO"; sig_imp = "LOW"
                sig_desc = f"F&G指数中性({fng_val})，市场无明显方向，保持仓位观望"
            elif fng_val <= 80:
                sig_type = "MACRO"; sig_imp = "MED"
                sig_desc = f"F&G指数贪婪({fng_val})，市场乐观情绪升温，注意仓位管理"
            else:
                sig_type = "RISK"; sig_imp = "HIGH"
                sig_desc = f"F&G指数极度贪婪({fng_val})，风险积聚，考虑分批减仓"

            signals.append({
                "id": "fng_1",
                "timestamp": fng_time or now.isoformat(),
                "type": sig_type,
                "description": sig_desc,
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
                "importance": sig_imp,
                "source": "alternative.me",
                "value": fng_val,
            })

        # 2. Top Gainers/Losers — lowered threshold to 5%
        movers = await get_top_gainers_losers()
        if movers.get("gainers"):
            for g in movers["gainers"][:3]:
                change = g.get("change_24h", 0) or 0
                if change >= 5:
                    signals.append({
                        "id": f"gainer_{g['symbol']}",
                        "timestamp": now.isoformat(),
                        "type": "MOMENTUM",
                        "description": f"{g['symbol']} 24h上涨{change:.1f}%，强劲上涨动能",
                        "affected_assets": [g["symbol"]],
                        "importance": "HIGH" if change >= 15 else ("MED" if change >= 10 else "LOW"),
                        "source": "coingecko",
                        "value": change,
                    })

        if movers.get("losers"):
            for l in movers["losers"][:3]:
                change = l.get("change_24h", 0) or 0
                if change <= -5:
                    signals.append({
                        "id": f"loser_{l['symbol']}",
                        "timestamp": now.isoformat(),
                        "type": "RISK",
                        "description": f"{l['symbol']} 24h下跌{abs(change):.1f}%，注意下行风险",
                        "affected_assets": [l["symbol"]],
                        "importance": "HIGH" if change <= -15 else ("MED" if change <= -10 else "LOW"),
                        "source": "coingecko",
                        "value": change,
                    })

        # 3. DeFi TVL flows — lowered threshold to 2%
        defi = await get_defi_overview()
        tvl_change = defi.get("change_24h", 0) or 0
        total_tvl  = defi.get("total_tvl", 0) or 0

        if total_tvl > 0:
            if tvl_change > 2:
                signals.append({
                    "id": "defi_tvl_up",
                    "timestamp": now.isoformat(),
                    "type": "FLOW",
                    "description": f"DeFi总TVL 24h增加{tvl_change:.1f}%，资金净流入(${total_tvl/1e9:.1f}B)",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "HIGH" if tvl_change > 8 else "MED",
                    "source": "defillama",
                    "value": tvl_change,
                })
            elif tvl_change < -2:
                signals.append({
                    "id": "defi_tvl_down",
                    "timestamp": now.isoformat(),
                    "type": "RISK",
                    "description": f"DeFi总TVL 24h下降{abs(tvl_change):.1f}%，资金净流出(${total_tvl/1e9:.1f}B)",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "HIGH" if tvl_change < -8 else "MED",
                    "source": "defillama",
                    "value": tvl_change,
                })
            else:
                # Always emit a TVL context signal
                signals.append({
                    "id": "defi_tvl_stable",
                    "timestamp": now.isoformat(),
                    "type": "FLOW",
                    "description": f"DeFi总TVL稳定在${total_tvl/1e9:.1f}B，24h变化{tvl_change:+.1f}%",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "LOW",
                    "source": "defillama",
                    "value": tvl_change,
                })

        # 4. Stablecoin dominance
        stables = await get_stablecoin_overview()
        usdc_dom = stables.get("usdc", {}).get("dominance", 0) or 0
        usdt_dom = stables.get("usdt", {}).get("dominance", 0) or 0
        usdc_mcap = stables.get("usdc", {}).get("market_cap", 0) or 0
        usdt_mcap = stables.get("usdt", {}).get("market_cap", 0) or 0

        if usdt_dom > 0 or usdc_dom > 0:
            if usdc_dom > usdt_dom + 5:
                signals.append({
                    "id": "stablecoin_usdc_lead",
                    "timestamp": now.isoformat(),
                    "type": "FLOW",
                    "description": f"USDC主导地位领先USDT({usdc_dom:.0f}% vs {usdt_dom:.0f}%)，机构端稳定币偏好增强",
                    "affected_assets": ["USDC", "USDT"],
                    "importance": "LOW",
                    "source": "defillama",
                })
            elif usdt_dom > usdc_dom + 5:
                signals.append({
                    "id": "stablecoin_usdt_dom",
                    "timestamp": now.isoformat(),
                    "type": "FLOW",
                    "description": f"USDT保持稳定币主导地位({usdt_dom:.0f}%)，散户流动性优先",
                    "affected_assets": ["USDT", "USDC"],
                    "importance": "LOW",
                    "source": "defillama",
                })

    except Exception as e:
        print(f"[SIGNALS] generation error: {e}")

    # Sort: HIGH first, then MED, then LOW; within same tier by timestamp desc
    importance_order = {"HIGH": 0, "MED": 1, "LOW": 2}
    signals.sort(key=lambda x: (importance_order.get(x["importance"], 2), -(datetime.fromisoformat(x["timestamp"].replace("Z", "")).timestamp() if "T" in x["timestamp"] else 0)))

    return {
        "status": "success",
        "version": "1.1.0",
        "timestamp": now.isoformat(),
        "data_source": "coingecko+defillama+alternative.me",
        "signals": signals[:15],
    }

# ── CIS (CometCloud Intelligence Score) ───────────────────────────────────

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


@app.post("/internal/cis-scores")
async def receive_local_cis_scores(payload: dict, x_internal_token: str = Header(None)):
    """
    Internal endpoint to receive CIS scores from local Mac Mini engine.
    Called by cis_push.py after local engine completes scoring.
    Scores are stored in Upstash Redis (persistent across deploys/instances).
    """
    print(f"[INTERNAL] Auth check — token configured: {bool(_INTERNAL_TOKEN)}, header present: {bool(x_internal_token)}")

    if _INTERNAL_TOKEN:
        if not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
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
        ok = await _redis_set(cache_data)
        print(f"[INTERNAL] Received {len(universe)} CIS scores — Redis write: {ok}")

        # 2. Write to Supabase (score history, persistent)
        if universe:
            sb_rows = []
            for asset in universe:
                pillars = asset.get("pillars", {})
                sb_rows.append({
                    "symbol":      asset.get("symbol", ""),
                    "name":        asset.get("name", ""),
                    "score":       asset.get("score"),
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
                    # Supabase auto-fills recorded_at = NOW()
                })
            sb_ok = await _supabase_insert_batch(sb_rows)
            print(f"[INTERNAL] Supabase history write: {sb_ok} ({len(sb_rows)} rows)")
        else:
            sb_ok = False

        # Broadcast to WebSocket clients
        asyncio.create_task(broadcast_cis_update(universe))

        return {"status": "success", "received": len(universe), "cached": ok, "history_written": sb_ok}
    except Exception as e:
        print(f"[INTERNAL] Error receiving CIS scores: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/cis/universe")
async def get_cis_universe(force_source: str = None):
    """
    CIS v4.0 Universe Endpoint
    Priority: local_engine (Redis) → Railway calculation → stale Redis fallback
    """
    cached   = None
    use_local = False

    if force_source != "railway":
        cached = await _redis_get()
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

    # Fallback: Railway calculates its own scores
    try:
        result = await calculate_cis_universe()
        result["source"] = "railway"
        return _sanitize_floats(result)
    except Exception as e:
        print(f"[CIS] Railway calculation error: {e}")
        # Last resort: return stale Redis data if any
        if cached and cached.get("universe"):
            return {
                "status":    "degraded",
                "message":   str(e),
                "source":    "local_engine_stale",
                "universe":  cached["universe"],
            }
        return {"status": "error", "message": str(e), "universe": []}

@app.get("/api/v1/cis/asset/{symbol}")
async def get_cis_asset(symbol: str):
    """Get CIS score for a specific asset."""
    universe = await get_cis_universe()
    for asset in universe.get("universe", []):
        if asset["symbol"].upper() == symbol.upper():
            return asset
    return {"error": "Asset not found"}


@app.get("/api/v1/cis/history/{symbol}")
async def get_cis_history(symbol: str, days: int = 7):
    """
    GET /api/v1/cis/history/{symbol}?days=7
    Returns CIS score history for sparklines and trend analysis.
    Sourced from Supabase; returns up to `days * 48` data points (30-min intervals).
    """
    rows = await _supabase_get_history(symbol.upper(), days)
    if not rows:
        return {
            "status":  "empty",
            "symbol":  symbol.upper(),
            "days":    days,
            "history": [],
        }
    # Reverse to chronological order (oldest first) for sparkline rendering
    rows = list(reversed(rows))
    return {
        "status":  "success",
        "symbol":  symbol.upper(),
        "days":    days,
        "count":   len(rows),
        "history": rows,
    }


@app.get("/api/v1/cis/history/batch")
async def get_cis_history_batch(symbols: str, days: int = 7):
    """
    GET /api/v1/cis/history/batch?symbols=BTC,ETH,SOL&days=7
    Batch version of history endpoint — fetches all symbols concurrently.
    Eliminates N+1 sparkline fetches from the frontend.
    Returns a map of symbol → history array.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"status": "error", "message": "No symbols provided", "data": {}}

    # Cap at 60 symbols to avoid Supabase rate limits
    symbol_list = symbol_list[:60]

    results = await asyncio.gather(
        *[_supabase_get_history(sym, days) for sym in symbol_list],
        return_exceptions=True,
    )

    data = {}
    for sym, rows in zip(symbol_list, results):
        if isinstance(rows, Exception) or not rows:
            data[sym] = []
        else:
            data[sym] = list(reversed(rows))  # chronological for sparklines

    return {
        "status":  "success",
        "days":    days,
        "count":   len(data),
        "data":    data,
    }


# ── Agent API (JSON-only, minimal) ─────────────────────────────────────────

@app.get("/api/v1/agent/cis")
async def agent_cis_endpoint():
    """
    Agent-optimized CIS endpoint: returns minimal JSON, no HTML/comments.
    Perfect for LLM agents to consume directly.
    """
    cached = await _redis_get()
    if cached and cached.get("universe"):
        universe = cached["universe"]
    else:
        try:
            result = await calculate_cis_universe()
            universe = result.get("universe", [])
        except Exception:
            universe = []

    # Minimal format for agents — pillar keys match cis_provider.py (F/M/O/S/A)
    return {
        "v": "4.0",
        "ts": cached.get("timestamp") if cached else datetime.now().isoformat(),
        "assets": [
            {
                "s": a["symbol"],
                "g": a.get("grade", "?"),
                "sc": a.get("score", a.get("cis_score", 0)),
                "sg": a.get("signal", "?"),
                "f": a.get("pillars", {}).get("F"),
                "m": a.get("pillars", {}).get("M"),
                "r": a.get("pillars", {}).get("O"),
                "ss": a.get("pillars", {}).get("S"),
                "a": a.get("pillars", {}).get("A"),
            }
            for a in universe
        ]
    }


# ── WebSocket for Real-time CIS Updates ───────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

manager = ConnectionManager()

# Store last CIS data for new subscribers
_last_cis_broadcast = None

@app.websocket("/ws/cis")
async def websocket_cis(websocket: WebSocket):
    """
    WebSocket endpoint for real-time CIS score updates.
    Clients receive instant notifications when scores change (local engine push).

    Message format:
    {
        "type": "update|full",
        "timestamp": "ISO8601",
        "assets": [...]  // only for "full" type
    }
    """
    global _last_cis_broadcast
    await manager.connect(websocket)

    # Send current state immediately
    if _last_cis_broadcast:
        await websocket.send_json(_last_cis_broadcast)

    try:
        while True:
            # Keep connection alive, wait for messages (ping/pong)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_cis_update(universe: list):
    """Call this when CIS scores are updated (from /internal/cis-scores)"""
    global _last_cis_broadcast
    _last_cis_broadcast = {
        "type": "full",
        "timestamp": datetime.now().isoformat(),
        "count": len(universe),
        "assets": [
            {
                "s": a["symbol"],
                "g": a.get("grade", "?"),
                "sc": a.get("score", a.get("cis_score", 0)),
            }
            for a in universe
        ]
    }
    await manager.broadcast(_last_cis_broadcast)


# ── Intelligence / Macro Events ──────────────────────────────────────────────

@app.get("/api/v1/intelligence/macro-events")
async def get_macro_events():
    """Fetch latest macro events from RSS feeds (CoinDesk, The Block, Decrypt, CoinTelegraph) + DefiLlama Raises
    Returns up to 20 events with auto-classification: REGULATORY/INSTITUTIONAL/MARKET/TECH
    Impact levels: HIGH/MEDIUM/LOW
    Cached for 60 minutes to avoid overloading RSS servers.
    """
    return {"events": await fetch_all_macro_events()}

# ── VC deal flow endpoints ─────────────────────────────────────────────────

@app.get("/api/v1/vc/funding-rounds")
async def get_funding_rounds(limit: int = 20):
    try:
        # Try existing VC tracker first, fallback to DeFiLlama
        try:
            from data.vc.deal_flow import VCDealFlowTracker
            tracker = VCDealFlowTracker()
            rounds = tracker.get_recent_funding_rounds(limit)
            if rounds:
                return {"timestamp": datetime.now().isoformat(), "data": rounds, "source": "internal"}
        except Exception:
            pass
        # DeFiLlama fallback
        raises = await get_vc_raises(limit)
        return {"timestamp": datetime.now().isoformat(), "data": raises, "source": "defillama"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/vc/unlocks")
async def get_token_unlocks(days: int = 30):
    try:
        from data.vc.deal_flow import VCDealFlowTracker
        tracker = VCDealFlowTracker()
        return {"timestamp": datetime.now().isoformat(), "data": tracker.get_token_unlocks(days)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/vc/overlap")
async def get_vc_overlap():
    try:
        from data.vc.deal_flow import VCDealFlowTracker
        tracker = VCDealFlowTracker()
        return {"timestamp": datetime.now().isoformat(), "data": tracker.get_vc_portfolio_overlap([])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/vault/funds")
async def get_vault_funds():
    """Get Vault GP funds - only real verified partners"""
    # Real verified GP partners only - no fictional data
    VAULT_FUNDS = [
        {
            "id": "est-alpha",
            "name": "EST Alpha",
            "strategy": "Multi-Strategy",
            "location": "Singapore",
            "aum": "Confidential",
            "yearFounded": 2024,
            "status": "active",
            "verified": True,
            "note": "CometCloud Founding GP Partner",
            "performance": {
                "ytd": 8.5,
                "annualReturn": 0,
                "sharpeRatio": 0,
                "maxDrawdown": -2.1,
            },
            "scores": {
                "performance": 15,
                "strategy": 18,
                "team": 20,
                "risk": 15,
                "transparency": 10,
                "aumTrackRecord": 5,
                "total": 83,
            },
            "grade": "B",
            "description": "CometCloud's flagship GP partner specializing in institutional DeFi strategies.",
            "team": "Ex-Jane Street, Wintermute, Delphi Digital",
            "strategyDetail": "Multi-strategy DeFi: yield optimization, delta-neutral, protocol governance",
            "advantage": "Direct integration with CometCloud vault infrastructure",
        },
        {
            "id": "placeholder-2",
            "name": "GP Partner #2",
            "strategy": "Under Evaluation",
            "location": "—",
            "aum": "—",
            "yearFounded": None,
            "status": "evaluating",
            "verified": False,
            "note": "GP onboarding in progress · Q2 2026",
            "performance": {
                "ytd": 0,
                "annualReturn": 0,
                "sharpeRatio": 0,
                "maxDrawdown": 0,
            },
            "scores": {
                "performance": 0,
                "strategy": 0,
                "team": 0,
                "risk": 0,
                "transparency": 0,
                "aumTrackRecord": 0,
                "total": 0,
            },
            "grade": None,
            "description": "GP onboarding in progress.",
            "team": None,
            "strategyDetail": None,
            "advantage": None,
            "isPlaceholder": True,
        },
        {
            "id": "placeholder-3",
            "name": "GP Partner #3",
            "strategy": "Under Evaluation",
            "location": "—",
            "aum": "—",
            "yearFounded": None,
            "status": "evaluating",
            "verified": False,
            "note": "GP onboarding in progress · Q2 2026",
            "performance": {
                "ytd": 0,
                "annualReturn": 0,
                "sharpeRatio": 0,
                "maxDrawdown": 0,
            },
            "scores": {
                "performance": 0,
                "strategy": 0,
                "team": 0,
                "risk": 0,
                "transparency": 0,
                "aumTrackRecord": 0,
                "total": 0,
            },
            "grade": None,
            "description": "GP onboarding in progress.",
            "team": None,
            "strategyDetail": None,
            "advantage": None,
            "isPlaceholder": True,
        },
    ]
    return {"timestamp": datetime.now().isoformat(), "data": VAULT_FUNDS}

# ── Portfolio optimization (unchanged, uses skfolio) ──────────────────────

@app.post("/api/v1/portfolio/optimize")
async def optimize_portfolio(request: PortfolioRequest):
    try:
        from analytics.portfolio.optimizer import CryptoPortfolioOptimizer
        optimizer = CryptoPortfolioOptimizer(assets=request.assets)
        optimizer.fetch_historical_data(days=90)
        if request.strategy == "hrp":
            result = optimizer.optimize_hrp()
        elif request.strategy == "min_variance":
            result = optimizer.optimize_min_variance()
        else:
            result = optimizer.optimize_equal_weight()
        return {"timestamp": datetime.now().isoformat(), "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/portfolio/stats")
async def get_portfolio_stats(assets: str = "BTC,ETH,SOL"):
    try:
        from analytics.portfolio.optimizer import CryptoPortfolioOptimizer
        asset_list = [s.strip() for s in assets.split(",")]
        optimizer = CryptoPortfolioOptimizer(assets=asset_list)
        prices = optimizer.fetch_historical_data(days=90)

        if optimizer.returns_data is not None:
            cols = list(optimizer.returns_data.columns)
            if len(cols) == len(asset_list) and all(isinstance(c, (int, float)) for c in cols):
                optimizer.returns_data.columns = asset_list
            elif any("/" in str(c) for c in cols):
                col_map = {}
                for c in cols:
                    for a in asset_list:
                        if a in str(c).upper():
                            col_map[c] = a
                            break
                optimizer.returns_data = optimizer.returns_data.rename(columns=col_map)

        stats = []
        for asset in asset_list:
            try:
                r = optimizer.returns_data[asset]
                last_price = float(prices[asset].iloc[-1]) if asset in prices.columns else 0.0
                stats.append({
                    "asset":       asset,
                    "return_90d":  round(float(r.sum() * 100), 2),
                    "volatility":  round(float(r.std() * np.sqrt(365) * 100), 2),
                    "sharpe":      round(float((r.mean() * 365) / (r.std() * np.sqrt(365) + 1e-9)), 2),
                    "price":       round(last_price, 2),
                })
            except Exception as e:
                stats.append({"asset": asset, "error": str(e)})

        return {"data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── On-chain address analysis (Moralis + Etherscan) ────────────────────────

@app.get("/api/v1/onchain/wallet/{address}")
async def analyze_wallet(address: str, chain: str = "eth"):
    return await get_wallet_portfolio(address, chain)

@app.get("/api/v1/onchain/wallet/{address}/defi")
async def wallet_defi(address: str, chain: str = "eth"):
    return await get_wallet_defi_positions(address, chain)

@app.get("/api/v1/onchain/address/{address}")
async def address_info(address: str):
    """ETH address info: balance + recent transactions."""
    balance, txs = await get_eth_balance(address), await get_eth_transactions(address)
    return {
        "address":  address,
        "balance":  balance,
        "transactions": txs.get("result", [])[:10] if "result" in txs else [],
        "timestamp": datetime.now().isoformat(),
    }

@app.get("/api/v1/onchain/address/{address}/tokens")
async def address_tokens(address: str):
    return await get_token_transfers(address)

# ── Health ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":  "healthy",
        "version": "0.3.0",
        "sources": ["binance", "defillama", "alternative.me", "moralis", "etherscan"],
    }

# ── Serve React SPA ────────────────────────────────────────────────────────

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
        file_path = os.path.join(dashboard_path, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(dashboard_path, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
