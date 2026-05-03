"""
CIS router — scoring, history, backtest, agent API, WebSocket, internal push
Endpoints: /api/v1/cis/*, /api/v1/agent/cis, /ws/cis, /internal/cis-scores
"""
import os, json as _json, time, asyncio, re
from datetime import datetime

import logging
from fastapi import APIRouter, HTTPException, Header, Query, WebSocket, WebSocketDisconnect, Response, Request

from src.api.store import (
    redis_set, redis_get,
    redis_set_key, redis_get_key,
    supabase_insert_batch, supabase_get_history,
    sanitize_floats, ws_manager,
)
import src.api.store as store
from src.data.cis.cis_provider import calculate_cis_universe

_logger = logging.getLogger(__name__)

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

        # Forward macro regime from Mac Mini payload so agent API + signal feed
        # can read cached.get("macro", {}).get("regime", ...) correctly
        macro = payload.get("macro") or {}
        if not macro and payload.get("macro_regime"):
            macro = {"regime": payload["macro_regime"]}

        cache_data = {
            "universe":     universe,
            "last_updated": time.time(),
            "timestamp":    timestamp,
            "source":       "local_engine",
            "macro":        macro,
        }

        # 1. Write to Redis (hot cache, 2h TTL)
        ok = await redis_set(cache_data)
        _logger.info(f"[INTERNAL] Received {len(universe)} CIS scores — Redis write: {ok}")

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
            _logger.warning(f"[INTERNAL] Supabase history write: {sb_ok} ({len(sb_rows)} rows)")

        # 3. Broadcast to WebSocket clients
        asyncio.create_task(_broadcast_cis_update(universe))

        return {"status": "success", "received": len(universe), "cached": ok, "history_written": sb_ok}
    except Exception as e:
        _logger.warning(f"[INTERNAL] Error receiving CIS scores: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── CIS Universe ──────────────────────────────────────────────────────────────

@router.get("/api/v1/cis/universe")
async def get_cis_universe(force_source: str = None, response: Response = None):
    """
    CIS v4.0 Universe — priority: local_engine (Redis) → Railway calc → stale Redis fallback
    """
    # Browser-level deduplication: 3 components hit this endpoint on load.
    # max-age=60 means concurrent fetches within 60s return from browser cache (~0ms).
    # stale-while-revalidate=120 keeps the UI fresh on background refresh.
    if response:
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"

    cached   = None
    use_local = False

    if force_source != "railway":
        cached = await redis_get()
        if cached and cached.get("universe"):
            age = time.time() - cached.get("last_updated", 0)
            if age < 7200 or force_source == "local":
                use_local = True

    # Always calculate Railway universe as T2 base (covers 65+ assets)
    railway_universe = []
    try:
        result = await calculate_cis_universe()
        railway_universe = result.get("universe", [])
    except Exception as e:
        _logger.warning(f"[CIS] Railway calculation error: {e}")

    # Merge: Mac Mini T1 scores override Railway T2 where available
    if use_local:
        local_map = {}
        for asset in cached.get("universe", []):
            sym = (asset.get("asset_id") or asset.get("symbol", "")).upper()
            asset["data_tier"] = 1
            local_map[sym] = asset

        merged = []
        seen = set()
        # First pass: Railway base (preserves ordering + enriched fields)
        for asset in railway_universe:
            sym = (asset.get("asset_id") or asset.get("symbol", "")).upper()
            if sym in local_map:
                # T1 override: use local score but keep Railway's market data + name
                la = local_map[sym]
                asset["cis_score"] = la.get("cis_score") or la.get("score", asset.get("cis_score"))
                # v4.2: Mac Mini T1 score is base-weighted (no regime adjustment applied),
                # so its score IS the raw score. Use it as raw_cis_score unless Railway
                # already computed one from the T2 fallback path.
                asset["raw_cis_score"] = la.get("raw_cis_score") or la.get("cis_score") or asset.get("cis_score")
                asset["grade"] = la.get("grade", asset.get("grade"))
                asset["signal"] = la.get("signal", asset.get("signal"))
                asset["data_tier"] = 1
                # Merge pillars if local engine provides them
                if la.get("pillars"):
                    asset["pillars"] = la["pillars"]
                elif any(la.get(k) is not None for k in ("f", "m", "o", "r", "s", "a")):
                    for k in ("f", "m", "o", "r", "s", "a"):
                        if la.get(k) is not None:
                            asset[k] = la[k]
            else:
                asset["data_tier"] = 2
            merged.append(asset)
            seen.add(sym)

        # Second pass: any Mac Mini assets not in Railway (shouldn't happen, but safe)
        for sym, la in local_map.items():
            if sym not in seen:
                la["data_tier"] = 1
                # v4.2: compute raw_cis_score from T1 pillars if not present
                if la.get("raw_cis_score") is None:
                    pf = la.get("f") or la.get("F") or 50
                    pm = la.get("m") or la.get("M") or 50
                    po = la.get("o") or la.get("O") or 50
                    ps = la.get("s") or la.get("S") or 50
                    pa = la.get("a") or la.get("A") or 50
                    la["raw_cis_score"] = round((0.25*pf + 0.25*pm + 0.20*po + 0.15*ps + 0.15*pa), 1)
                merged.append(la)

        # Sort by CIS score descending
        merged.sort(key=lambda a: a.get("cis_score") or a.get("score") or 0, reverse=True)

        # Get unified regime directly from get_macro_pulse() rather than via Redis.
        # This ensures both endpoints return identical macro_regime without Redis round-trip.
        try:
            from src.data.market.data_layer import get_macro_pulse
            pulse = await get_macro_pulse()
            _cached_regime = pulse.get("macro_regime") or "UNKNOWN"
        except Exception:
            # Fallback: try Redis key, then Mac Mini cached, then VIX
            try:
                unified = await store.redis_get_key("cis:regime")
                if unified and unified.get("regime"):
                    _cached_regime = unified["regime"]
                else:
                    _cached_regime = (
                        (cached.get("macro") or {}).get("regime")
                        or cached.get("regime")
                        or (result.get("macro") or {}).get("regime")
                        or (result.get("regime"))
                        or "UNKNOWN"
                    )
            except Exception:
                _cached_regime = (
                    (cached.get("macro") or {}).get("regime")
                    or cached.get("regime")
                    or (result.get("macro") or {}).get("regime")
                    or (result.get("regime"))
                    or "UNKNOWN"
                )

        # Normalize T1 pillars: Mac Mini sends flat keys (f/m/o/s/a).
        # Build nested pillars dict so frontend components can read asset.pillars.F etc.
        for a in merged:
            if a.get("data_tier") == 1 and a.get("pillars") is None:
                pf = a.get("f") or a.get("F")
                pm = a.get("m") or a.get("M")
                po = a.get("o") or a.get("O")
                ps = a.get("s") or a.get("S")
                pa = a.get("a") or a.get("A")
                if any(v is not None for v in (pf, pm, po, ps, pa)):
                    a["pillars"] = {"F": pf, "M": pm, "O": po, "S": ps, "A": pa}

        return sanitize_floats({
            "status":       "success",
            "version":      "4.1.0",
            "timestamp":    cached.get("timestamp", time.time()),
            "source":       "merged",
            "t1_count":     len(local_map),
            "t2_count":     len(merged) - len(local_map),
            "macro_regime": _cached_regime,
            "universe":     merged,
        })

    # Pure Railway (no Mac Mini data available)
    if railway_universe:
        result["source"] = "railway"
        # Get unified regime directly from get_macro_pulse() — same source as macro-pulse endpoint
        try:
            from src.data.market.data_layer import get_macro_pulse
            pulse = await get_macro_pulse()
            result["macro_regime"] = pulse.get("macro_regime") or "UNKNOWN"
        except Exception:
            result["macro_regime"] = (result.get("macro") or {}).get("regime", "UNKNOWN")
        result["t1_count"] = 0
        result["t2_count"] = len(railway_universe)
        return sanitize_floats(result)

    # Last resort: stale Redis
    if cached and cached.get("universe"):
        stale_universe = cached["universe"]
        return {
            "status":       "degraded",
            "version":      "4.1.0",
            "timestamp":    cached.get("timestamp", time.time()),
            "source":       "local_engine_stale",
            "t1_count":     0,
            "t2_count":     len(stale_universe),
            "macro_regime": (
                (cached.get("macro") or {}).get("regime")
                or cached.get("regime")
                or "UNKNOWN"
            ),
            "universe":     stale_universe,
        }
    return {"status": "error", "message": "No scoring data available", "universe": []}


@router.get("/api/v1/cis/debug/datasources")
async def debug_datasources():
    """
    Diagnostic: run each CIS data source independently and report what was returned.
    Shows exactly which feed is empty so we can pinpoint the T2 failure.
    NOT for production use — internal debugging only.
    """
    import asyncio, time as _time
    from src.data.cis.cis_provider import (
        fetch_binance_prices, fetch_cg_markets, fetch_defillama_tvl,
        fetch_fear_greed, CG_API_KEY, _cg_base, _UPSTASH_URL
    )
    import yfinance as yf

    results = {}
    t0 = _time.time()

    # Binance
    try:
        t = _time.time()
        bp = await asyncio.wait_for(fetch_binance_prices(), timeout=15)
        results["binance"] = {"count": len(bp), "sample": list(bp.keys())[:5], "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["binance"] = {"error": str(e)}

    # CoinGecko
    try:
        t = _time.time()
        cgm = await asyncio.wait_for(fetch_cg_markets(), timeout=30)
        results["coingecko"] = {"count": len(cgm), "sample": list(cgm.keys())[:5], "ms": int((_time.time()-t)*1000),
                                "api_key_set": bool(CG_API_KEY), "base_url": _cg_base()}
    except Exception as e:
        results["coingecko"] = {"error": str(e), "api_key_set": bool(CG_API_KEY), "base_url": _cg_base()}

    # DeFiLlama
    try:
        t = _time.time()
        tvl = await asyncio.wait_for(fetch_defillama_tvl(), timeout=15)
        results["defillama"] = {"count": len(tvl), "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["defillama"] = {"error": str(e)}

    # Fear & Greed
    try:
        t = _time.time()
        fng = await asyncio.wait_for(fetch_fear_greed(), timeout=10)
        results["fear_greed"] = {"value": fng.get("value") if fng else None, "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["fear_greed"] = {"error": str(e)}

    # yfinance spot check (SPY only)
    try:
        t = _time.time()
        def _yf_spy():
            tk = yf.Ticker("SPY")
            h = tk.history(period="5d")
            return float(h['Close'].iloc[-1]) if len(h) > 0 else None
        spy_price = await asyncio.wait_for(asyncio.to_thread(_yf_spy), timeout=20)
        results["yfinance_spy"] = {"price": spy_price, "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["yfinance_spy"] = {"error": str(e)}

    results["upstash_configured"] = bool(_UPSTASH_URL)
    results["total_ms"] = int((_time.time()-t0)*1000)
    return results


@router.get("/api/v1/cis/top")
async def get_cis_top(limit: int = 10, response: Response = None):
    """
    Top-N CIS assets by score.
    Returns the same merged T1+T2 universe as /api/v1/cis/universe but sliced
    to top N and sorted by score descending. Used by ShareCard, StrategyPage.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"

    # Re-use the full universe logic then slice
    full = await get_cis_universe(force_source=None)
    universe = full.get("universe", [])
    if not universe:
        return {"status": full.get("status", "ok"), "source": full.get("source"), "top": [], "limit": limit}

    sorted_assets = sorted(universe, key=lambda a: a.get("cis_score") or a.get("score") or 0, reverse=True)
    top = sorted_assets[:limit]
    return {
        "status":       full.get("status", "ok"),
        "version":      "4.1.0",
        "source":       full.get("source"),
        "macro_regime": full.get("macro_regime"),
        "t1_count":     full.get("t1_count", 0),
        "t2_count":     full.get("t2_count", 0),
        "total":        len(universe),
        "limit":        limit,
        "top":          sanitize_floats(top),
    }


@router.get("/api/v1/cis/asset/{symbol}")
async def get_cis_asset(symbol: str):
    """Get CIS score for a specific asset."""
    universe = await get_cis_universe()
    for asset in universe.get("universe", []):
        if asset["symbol"].upper() == symbol.upper():
            return asset
    return {"error": "Asset not found"}


# ── Compare ───────────────────────────────────────────────────────────────────

@router.get("/api/v1/cis/compare")
async def get_cis_compare(symbols: str, response: Response = None):
    """
    Side-by-side CIS pillar comparison for 2–6 assets.

    GET /api/v1/cis/compare?symbols=BTC,ETH,SOL

    Returns per-asset: score, grade, signal, all 5 pillar scores, price, change_24h,
    market_cap, data_tier — plus universe-wide pillar averages for relative context.

    Pillar keys (both T1 and T2 shapes normalised):
      F (Fundamental)  M (Momentum)  O (On-chain/Risk)  S (Sentiment)  A (Alpha)
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=45, stale-while-revalidate=90"

    _SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}(,[A-Z0-9]{2,12})*$", re.IGNORECASE)
    clean = symbols.strip().upper()
    if not _SYMBOL_RE.match(clean):
        raise HTTPException(status_code=400, detail="Invalid symbols — use comma-separated tickers, e.g. BTC,ETH,SOL")

    requested = [s.strip().upper() for s in clean.split(",") if s.strip()][:6]

    uni_data = await get_cis_universe()
    universe = uni_data.get("universe", [])

    # Build a fast lookup by symbol
    sym_map: dict[str, dict] = {}
    for a in universe:
        sym = (a.get("asset_id") or a.get("symbol", "")).upper()
        if sym:
            sym_map[sym] = a

    def _norm_pillars(a: dict) -> dict:
        """Normalise both T1 (flat keys f/m/r/s/a) and T2 (nested pillars{F,M,O,S,alpha}) shapes."""
        p = a.get("pillars") or {}
        def _get(key_nested, *flat_keys):
            v = p.get(key_nested)
            if v is not None:
                return round(float(v), 1)
            for fk in flat_keys:
                v2 = a.get(fk)
                if v2 is not None:
                    return round(float(v2), 1)
            return None

        return {
            "F": _get("F", "f"),
            "M": _get("M", "m"),
            "O": _get("O", "o", "r"),   # "o" canonical (v4.1+), "r" legacy fallback
            "S": _get("S", "s"),
            "A": _get("alpha", "a"),
        }

    def _norm_asset(a: dict, sym: str) -> dict:
        pil = _norm_pillars(a)
        cis_sc = round(float(a.get("cis_score") or a.get("score") or 0), 1)
        raw_sc = a.get("raw_cis_score")
        return {
            "symbol":         sym,
            "name":           a.get("name", sym),
            "asset_class":    a.get("asset_class") or a.get("class") or "—",
            "cis_score":      cis_sc,
            "raw_cis_score":  round(float(raw_sc), 1) if raw_sc is not None else cis_sc,
            "grade":          a.get("grade", "—"),
            "signal":         a.get("signal", "NEUTRAL"),
            "data_tier":      a.get("data_tier", 2),
            "price":          a.get("price"),
            "change_24h":     a.get("change_24h"),
            "change_7d":      a.get("change_7d"),
            "market_cap":     a.get("market_cap"),
            "volume_24h":     a.get("volume_24h"),
            "las":            a.get("las"),
            "confidence":     a.get("confidence"),
            "pillars":        pil,
        }

    # Universe pillar averages (for relative context — shown as dotted line on bars)
    pil_sums = {"F": 0.0, "M": 0.0, "O": 0.0, "S": 0.0, "A": 0.0}
    pil_n    = {"F": 0,   "M": 0,   "O": 0,   "S": 0,   "A": 0}
    for a in universe:
        for k, raw_k, flat_k in [("F","F","f"),("M","M","m"),("O","O","o"),("S","S","s"),("A","alpha","a")]:
            p = a.get("pillars") or {}
            v = p.get(raw_k) if p.get(raw_k) is not None else a.get(flat_k)
            if v is not None:
                try:
                    pil_sums[k] += float(v); pil_n[k] += 1
                except (TypeError, ValueError):
                    pass

    pillar_universe_avg = {
        k: round(pil_sums[k] / pil_n[k], 1) if pil_n[k] > 0 else None
        for k in ["F", "M", "O", "S", "A"]
    }

    assets_out = []
    not_found  = []
    for sym in requested:
        if sym in sym_map:
            assets_out.append(_norm_asset(sym_map[sym], sym))
        else:
            not_found.append(sym)

    # Class-level averages across the universe for context
    class_avgs: dict[str, float] = {}
    class_n: dict[str, int] = {}
    for a in universe:
        cls = (a.get("asset_class") or a.get("class") or "").upper()
        sc  = a.get("cis_score") or a.get("score") or 0
        if cls:
            class_avgs[cls] = class_avgs.get(cls, 0.0) + float(sc)
            class_n[cls]    = class_n.get(cls, 0) + 1
    class_avgs = {k: round(v / class_n[k], 1) for k, v in class_avgs.items()}

    return sanitize_floats({
        "status":              "success",
        "requested":           requested,
        "not_found":           not_found,
        "universe_size":       len(universe),
        "macro_regime":        uni_data.get("macro_regime", "UNKNOWN"),
        "source":              uni_data.get("source", "railway"),
        "pillar_universe_avg": pillar_universe_avg,
        "class_avg_scores":    class_avgs,
        "assets":              assets_out,
    })


# ── Regime Analysis ──────────────────────────────────────────────────────────

_REGIME_PILLAR_WEIGHTS = {
    "RISK_ON":     {"F": 1, "M": 3, "O": 1, "S": 2, "A": 3},
    "RISK_OFF":    {"F": 3, "M": 1, "O": 3, "S": 1, "A": 2},
    "TIGHTENING":  {"F": 3, "M": 2, "O": 2, "S": 1, "A": 2},
    "EASING":      {"F": 2, "M": 3, "O": 1, "S": 2, "A": 2},
    "STAGFLATION": {"F": 2, "M": 1, "O": 3, "S": 2, "A": 2},
    "GOLDILOCKS":  {"F": 2, "M": 2, "O": 1, "S": 2, "A": 3},
}
_REGIME_INSIGHTS = {
    "RISK_ON":     "Momentum and Alpha independence dominate. Assets breaking out vs BTC benchmark outperform. Reduce defensive allocations.",
    "RISK_OFF":    "Fundamental quality and On-Chain Risk scores matter most. Prefer deep-liquidity assets with low volatility regimes.",
    "TIGHTENING":  "Fundamental scoring screens for fee-generating, real-yield assets. Avoid over-leveraged protocols. Alpha divergence useful for identifying safe havens.",
    "EASING":      "Momentum leads the recovery cycle. Assets with strong 30d trend and improving sentiment are early movers.",
    "STAGFLATION": "On-Chain Risk + Fundamental stability. Real-yield and RWA historically outperform. High-beta alts underperform.",
    "GOLDILOCKS":  "Broadest opportunity set. Alpha independence is key edge — look for uncorrelated return vs benchmark. Growth and quality both rewarded.",
}
_PILLAR_FLAT = [("F","F","f"), ("M","M","m"), ("O","O","o"), ("S","S","s"), ("A","alpha","a")]


@router.get("/api/v1/cis/regime-analysis")
async def get_regime_analysis(response: Response = None):
    """
    Regime-aware CIS analysis.

    Returns:
      - current macro regime + interpretation
      - pillar weight overrides for this regime
      - per asset-class regime-weighted average CIS score + rank
      - top 5 assets per regime-weighted score (leading indicators for this regime)
      - bottom 5 (laggards — potential UNDERWEIGHT candidates)

    Useful for: sector rotation decisions, regime-aware allocation tilts, MCP agent context.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"

    uni_data  = await get_cis_universe()
    universe  = uni_data.get("universe", [])
    regime    = uni_data.get("macro_regime", "UNKNOWN")
    weights   = _REGIME_PILLAR_WEIGHTS.get(regime, {k: 2 for k in ["F","M","O","S","A"]})

    def _regime_score(a: dict) -> float:
        """Compute weighted pillar score for current regime."""
        p = a.get("pillars") or {}
        total = w_total = 0.0
        for kres, knew, kflat in _PILLAR_FLAT:
            v = p.get(knew)
            if v is None:
                v = a.get(kflat)
            if v is not None:
                try:
                    w = weights.get(kres, 2)
                    total += float(v) * w
                    w_total += w
                except (TypeError, ValueError):
                    pass
        return round(total / w_total, 1) if w_total > 0 else (a.get("cis_score") or a.get("score") or 0.0)

    # Score all assets
    scored = []
    for a in universe:
        sym = (a.get("asset_id") or a.get("symbol", "")).upper()
        rs  = _regime_score(a)
        scored.append({
            "symbol":       sym,
            "name":         a.get("name", sym),
            "asset_class":  a.get("asset_class") or a.get("class") or "—",
            "cis_score":    round(float(a.get("cis_score") or a.get("score") or 0), 1),
            "grade":        a.get("grade", "—"),
            "signal":       a.get("signal", "NEUTRAL"),
            "regime_score": rs,
            "data_tier":    a.get("data_tier", 2),
        })

    scored.sort(key=lambda x: x["regime_score"], reverse=True)
    for i, s in enumerate(scored):
        s["regime_rank"] = i + 1

    # Per-class averages (regime-weighted)
    class_sums: dict = {}
    class_ns:   dict = {}
    for s in scored:
        cls = s["asset_class"]
        class_sums[cls] = class_sums.get(cls, 0.0) + s["regime_score"]
        class_ns[cls]   = class_ns.get(cls, 0) + 1
    class_avgs = {k: round(v / class_ns[k], 1) for k, v in class_sums.items()}
    class_ranked = sorted(class_avgs.items(), key=lambda x: x[1], reverse=True)

    return sanitize_floats({
        "status":          "success",
        "macro_regime":    regime,
        "regime_insight":  _REGIME_INSIGHTS.get(regime, "Unknown regime — using equal pillar weights."),
        "pillar_weights":  weights,
        "universe_size":   len(scored),
        "class_scores":    [{"class": c, "regime_score": s, "n": class_ns[c]} for c, s in class_ranked],
        "leaders":         scored[:5],
        "laggards":        scored[-5:][::-1],
        "source":          uni_data.get("source", "railway"),
    })


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
        _logger.warning(f"[BACKTEST] Read error: {e}")

    try:
        from src.data.cis.history_db import get_backtest_summary
        summary = get_backtest_summary()
        return {"status": "success", "source": "db", **summary}
    except Exception as e:
        return {"status": "empty", "message": str(e)}


# ── Agent API ─────────────────────────────────────────────────────────────────

_AGENT_RATE_LIMIT: dict = {}  # ip → [timestamp, ...]
_AGENT_RL_WINDOW  = 60   # seconds
_AGENT_RL_MAX     = 30   # max requests per window per IP

@router.get("/api/v1/agent/cis")
async def agent_cis_endpoint(
    limit:       int = 40,    # max assets returned (1-100)
    offset:      int = 0,     # pagination offset
    asset_class: str = "",    # filter: L1/L2/DeFi/RWA/Infrastructure/Memecoin/TradFi
    min_grade:   str = "",    # filter: A+/A/B+/B/C+/C/D/F
    min_score:   float = 0.0, # filter: minimum cis_score
    request: Request = None,
):
    """
    Agent-optimized CIS endpoint — compact JSON for LLM/agent consumption.
    Supports pagination, filtering, and per-IP rate limiting (30 req/min).

    Query params:
      limit       (int, 1-100, default 40)   — assets per page
      offset      (int, default 0)           — pagination offset
      asset_class (str)                      — filter by class
      min_grade   (str)                      — minimum grade gate (e.g. B+)
      min_score   (float)                    — minimum cis_score gate
    """
    # Rate limiting — per client IP
    if request:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        hits = _AGENT_RATE_LIMIT.get(client_ip, [])
        hits = [t for t in hits if now - t < _AGENT_RL_WINDOW]
        if len(hits) >= _AGENT_RL_MAX:
            raise HTTPException(status_code=429, detail="Rate limit: 30 req/min")
        hits.append(now)
        _AGENT_RATE_LIMIT[client_ip] = hits

    # Clamp pagination params
    limit  = max(1, min(limit, 100))
    offset = max(0, offset)

    cached = await redis_get()
    if cached and cached.get("universe"):
        universe = cached["universe"]
        ts = cached.get("timestamp", datetime.now().isoformat())
        regime = cached.get("macro", {}).get("regime", "Unknown")
    else:
        try:
            result = await calculate_cis_universe()
            universe = result.get("universe", [])
            ts = result.get("timestamp", datetime.now().isoformat())
            regime = result.get("macro", {}).get("regime", "Unknown")
        except Exception:
            universe = []
            ts = datetime.now().isoformat()
            regime = "Unknown"

    # Filtering
    _GRADE_ORDER = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
    min_grade_rank = _GRADE_ORDER.get(min_grade, 0)

    filtered = []
    for a in universe:
        if asset_class and a.get("asset_class", "") != asset_class:
            continue
        sc = a.get("cis_score", a.get("score", 0)) or 0
        if sc < min_score:
            continue
        if min_grade_rank and _GRADE_ORDER.get(a.get("grade", "F"), 1) < min_grade_rank:
            continue
        filtered.append(a)

    total = len(filtered)
    page  = filtered[offset: offset + limit]

    return {
        "v":      "4.1",
        "ts":     ts,
        "regime": regime,
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "assets": [
            {
                "s":    a["symbol"],
                "g":    a.get("grade", "?"),
                "sc":   a.get("cis_score", a.get("score", 0)),
                "sg":   a.get("signal", "?"),
                "cls":  a.get("asset_class", ""),
                "tier": a.get("data_tier", 2),
                "f":    _p(a, "f"),
                "m":    _p(a, "m"),
                "o":    _p(a, "o") or _p(a, "r"),
                "ss":   _p(a, "s"),
                "a":    _p(a, "a"),
                "las":    a.get("las"),
                "conf":   a.get("confidence"),
                "ch30d":  a.get("change_30d"),
                "ch7d":   a.get("change_7d"),
                "mc":     a.get("market_cap"),
                "vol24h": a.get("volume_24h"),
                "tvl":    a.get("tvl"),
            }
            for a in page
        ],
    }


# ── Agent: Exclusion List ─────────────────────────────────────────────────────

# Static exclusion data — sourced from EXCLUSION_LIST.md v1.1 (2026-04-09)
# Updated when Jazz + MiniMax run the universe filter. Each entry is machine-readable.
_CIS_EXCLUSIONS: list[dict] = [
    # ── Memecoins ──────────────────────────────────────────────────────────────
    {"symbol": "BONK", "name": "Bonk", "asset_class": "Memecoin",
     "criterion_violated": ["3", "7"], "criterion_labels": ["Custody", "Team Integrity"],
     "reason": "No institutional custodian support. Anonymous team with no registered legal entity. No protocol utility beyond speculative trading.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    {"symbol": "PEPE", "name": "Pepe", "asset_class": "Memecoin",
     "criterion_violated": ["3", "7"], "criterion_labels": ["Custody", "Team Integrity"],
     "reason": "Anonymous team, no institutional custodian, no registered legal entity. Explicitly anonymous project with no protocol utility.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    {"symbol": "WIF", "name": "dogwifhat", "asset_class": "Memecoin",
     "criterion_violated": ["3", "6", "7"], "criterion_labels": ["Custody", "Trading History", "Team Integrity"],
     "reason": "Anonymous team, no institutional custody, insufficient trading history at institutional exchanges. No protocol utility.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    # ── Gaming / Metaverse ──────────────────────────────────────────────────────
    {"symbol": "AXS", "name": "Axie Infinity", "asset_class": "Gaming",
     "criterion_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "reason": "Ronin bridge exploit March 2022 — $625M drained. Largest single DeFi hack in history. Root cause: validator key mismanagement. Partial user restitution only.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Eligible for review 2027 if 3+ years of clean operation from rebuild date are maintained."},
    {"symbol": "MANA", "name": "Decentraland", "asset_class": "Gaming",
     "criterion_violated": ["1", "2"], "criterion_labels": ["Liquidity", "Data Completeness"],
     "reason": "30-day average daily volume below $5M threshold. DAU consistently <1,000 making on-chain engagement scoring unreliable.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies if sustained 30d volume exceeds $5M for 60+ consecutive days."},
    {"symbol": "SAND", "name": "The Sandbox", "asset_class": "Gaming",
     "criterion_violated": ["1"], "criterion_labels": ["Liquidity"],
     "reason": "30-day average daily volume in persistent decline since 2022. Borderline threshold breach with no trend reversal signal.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies if sustained 30d volume exceeds $5M for 60+ consecutive days."},
    # ── DeFi ───────────────────────────────────────────────────────────────────
    {"symbol": "CRV", "name": "Curve Finance", "asset_class": "DeFi",
     "criterion_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "reason": "Founder Michael Egorov personal DeFi positions (~$168M collateralized against CRV in 2023) created systemic liquidation risk to the protocol's own liquidity pools. Conflict of interest between founder's personal finances and protocol health.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Eligible for review if founder positions are fully unwound and a governance separation policy is established."},
    {"symbol": "SUSHI", "name": "SushiSwap", "asset_class": "DeFi",
     "criterion_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "reason": "Multiple documented integrity incidents 2020-2024: founder withdrawal of $14M dev fund without governance approval, repeated leadership disputes, treasury mismanagement allegations. Pattern of repeated incidents disqualifies.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    {"symbol": "SNX", "name": "Synthetix", "asset_class": "DeFi",
     "criterion_violated": ["2"], "criterion_labels": ["Data Completeness"],
     "reason": "Three major product pivots created data discontinuity. V2 and V3 TVL/revenue data incomparable on continuous basis. Insufficient data completeness for reliable F pillar scoring.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies after 12 months of stable V3 operating data without further major pivots."},
    # ── Infrastructure ─────────────────────────────────────────────────────────
    {"symbol": "ICP", "name": "Internet Computer", "asset_class": "Infrastructure",
     "criterion_violated": ["5"], "criterion_labels": ["Token Mechanics"],
     "reason": "Historical undisclosed inflation event: ~90% supply inflation in first 8 months post-launch (May-Dec 2021) via neuron reward emissions not clearly disclosed in pre-launch tokenomics. Variable NNS governance reward emissions create ongoing supply schedule uncertainty.",
     "excluded_since": "2026-04-01", "remediation_available": False,
     "remediation_note": "Historical non-disclosure of inflation schedule is not retroactively remediable."},
    # ── AI ─────────────────────────────────────────────────────────────────────
    {"symbol": "VIRTUAL", "name": "Virtuals Protocol", "asset_class": "AI",
     "criterion_violated": ["3"], "criterion_labels": ["Institutional Custody"],
     "reason": "No institutional custodian from the Criterion 3 approved list (Coinbase, BitGo, Fireblocks, Anchorage, Fidelity, Komainu, Zodia) offers VIRTUAL custody as of April 2026.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies immediately when Coinbase, BitGo, or Fireblocks adds custody support."},
    # ── Legacy Crypto ───────────────────────────────────────────────────────────
    {"symbol": "BCH", "name": "Bitcoin Cash", "asset_class": "Crypto",
     "criterion_violated": ["4"], "criterion_labels": ["Regulatory Status"],
     "reason": "Primary public advocate Roger Ver indicted by US DOJ April 2024 on tax evasion and wire fraud charges. Regulatory proximity concern for institutional allocators despite protocol itself not being charged.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Eligible for review if Ver case is resolved without conviction or exchange delisting risk is confirmed absent."},
    {"symbol": "FTM", "name": "Fantom / Sonic", "asset_class": "L1",
     "criterion_violated": ["5"], "criterion_labels": ["Token Mechanics"],
     "reason": "Complete rebrand to Sonic (January 2025) with token migration FTM→S at 1:1 plus new 190.5M S airdrop supply. Mid-flight tokenomics change breaks continuous time-series scoring. New asset (S/SONIC) has <18 months operating history.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "S/SONIC eligible for fresh inclusion evaluation after 12+ months stable post-migration tokenomics and institutional custody support."},
    # ── RWA ────────────────────────────────────────────────────────────────────
    {"symbol": "POLYX", "name": "Polymesh", "asset_class": "RWA",
     "criterion_violated": ["1"], "criterion_labels": ["Liquidity"],
     "reason": "30-day average daily volume ~$250K-$500K against the $5M minimum. Staking-heavy token mechanics structurally suppress secondary market liquidity.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies if sustained 30d average volume exceeds $5M."},
]

# Borderline cases — included with reduced confidence or pending Jazz decision
_CIS_BORDERLINE: list[dict] = [
    {"symbol": "RUNE", "name": "Thorchain", "asset_class": "Infrastructure",
     "status": "remediation_review",
     "criterion_previously_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "remediation_evidence": "Dual exploit 2021 ($5M + $8M). Both disclosed. Post-mortems published. Halborn audit completed post-2021. 3+ years clean operation (July 2021 – April 2026). No repeat vulnerability.",
     "pending": "Confirmation that user compensation reached ≥80% threshold. Jazz decision required."},
    {"symbol": "DOGE", "name": "Dogecoin", "asset_class": "Memecoin",
     "status": "borderline_pass",
     "note": "Passes all 7 criteria. 10+ year history, Coinbase Custody supported, >$500M daily volume, known inflation schedule. Included in universe — narrative credibility decision only."},
]


@router.get("/api/v1/agent/cis-exclusions")
async def get_cis_exclusions(
    criterion: str = "",        # filter by criterion number e.g. "7" or "1"
    asset_class: str = "",      # filter by class e.g. "DeFi", "Memecoin"
    remediable: str = "",       # filter: "true" = only remediable, "false" = permanent
    include_borderline: bool = False,
):
    """
    Returns the CometCloud institutional exclusion list with structured rejection reasons.

    Each excluded asset includes the specific criterion violated, the plain-language reason,
    and whether remediation is available. This is the only MCP tool in crypto that returns
    a structured institutional exclusion list — not a score, a rejection.

    CometCloud's 7 exclusion criteria:
      1 = Liquidity threshold   2 = Data completeness     3 = Institutional custody
      4 = Regulatory status     5 = Token mechanics       6 = Trading history
      7 = Team/protocol integrity

    Use this tool to screen portfolio candidates against an institutional-grade standard
    before any allocation decision.
    """
    results = list(_CIS_EXCLUSIONS)

    if criterion:
        results = [e for e in results if criterion in e["criterion_violated"]]
    if asset_class:
        cls = asset_class.strip().title()
        results = [e for e in results if e["asset_class"].lower() == cls.lower()]
    if remediable.lower() == "true":
        results = [e for e in results if e.get("remediation_available", False)]
    elif remediable.lower() == "false":
        results = [e for e in results if not e.get("remediation_available", False)]

    out: dict = {
        "total_excluded": len(_CIS_EXCLUSIONS),
        "filtered_count": len(results),
        "universe_evaluated": 70,
        "universe_admitted": 70 - len(_CIS_EXCLUSIONS),
        "standard_version": "1.1",
        "standard_url": "cometcloud.ai/methodology",
        "last_reviewed": "2026-04-09",
        "exclusions": results,
    }
    if include_borderline:
        out["borderline"] = _CIS_BORDERLINE

    return JSONResponse(content=out)


# ── Agent: Inclusion Standard ─────────────────────────────────────────────────

_INCLUSION_STANDARD = {
    "version": "1.1",
    "effective_date": "2026-04-09",
    "design_principle": "Alpha-preserving filter, not risk-elimination filter. Screens structurally broken or fraudulent assets — not high-conviction emerging assets that are new or have fully recovered from past incidents.",
    "criteria": [
        {
            "id": "1", "name": "Liquidity Threshold", "applies_to": "all",
            "gate_type": "hard",
            "thresholds": {
                "crypto_30d_avg_volume_usd": 5_000_000,
                "crypto_min_tier1_exchange_count": 3,
                "crypto_max_bid_ask_spread_pct": 1.5,
                "tradfi_30d_avg_volume_usd": 50_000_000,
                "tradfi_listing": "NYSE or NASDAQ primary",
            },
            "rationale": "Institutional portfolio construction requires ability to enter and exit at size without material market impact.",
            "data_sources": ["CoinGecko Pro", "Bloomberg"],
            "example_rejection": "POLYX — 30d average volume ~$300K against $5M minimum.",
        },
        {
            "id": "2", "name": "Data Completeness", "applies_to": "all",
            "gate_type": "hard",
            "thresholds": {
                "crypto_min_ohlcv_history_days": 90,
                "defi_tvl_source": "DeFiLlama API with <24h latency",
                "defi_min_tvl_history_days": 90,
                "tradfi_etf_min_audited_nav_years": 2,
                "us_equity_min_audited_financials_years": 3,
            },
            "rationale": "Incomplete data produces noise, not signal. Assets that cannot be scored reliably across all 5 pillars are excluded rather than partially scored.",
            "data_sources": ["DeFiLlama", "CoinGecko Pro", "Glassnode", "SEC EDGAR"],
            "example_rejection": "SNX — three product pivots created TVL data discontinuity; V2 and V3 data incomparable.",
        },
        {
            "id": "3", "name": "Institutional Custody Eligibility", "applies_to": "all",
            "gate_type": "hard",
            "approved_custodians": [
                "Coinbase Prime / Coinbase Custody",
                "BitGo Trust",
                "Fireblocks (institutional network)",
                "Anchorage Digital Bank",
                "Fidelity Digital Assets",
                "Komainu",
                "Standard Chartered Zodia Custody",
            ],
            "tradfi_alternative": "DTCC eligibility sufficient for TradFi assets",
            "rationale": "An asset that cannot be held by an institutional custodian cannot be allocated to by pension funds, family offices, or regulated funds.",
            "data_sources": ["Published custodian asset coverage lists, reviewed monthly"],
            "example_rejection": "VIRTUAL — not supported by any listed custodian as of April 2026.",
        },
        {
            "id": "4", "name": "Regulatory Status", "applies_to": "all",
            "gate_type": "hard",
            "requirements": [
                "Not classified as unregistered security by SFC Hong Kong, US SEC, or EU MiCA",
                "No active enforcement action or charges naming issuing entity or primary development team",
                "No OFAC sanctions designation on issuing entity or protocol treasury",
                "Primary distribution mechanism not found unlawful by relevant regulator",
            ],
            "rationale": "Active regulatory action exposes fund and LPs to legal and reputational risk. Most dynamic criterion — reviewed monthly.",
            "data_sources": ["SFC HK", "SEC enforcement database", "OFAC SDN list", "EU MiCA registry"],
            "example_rejection": "BCH — primary public advocate Roger Ver under DOJ indictment for tax evasion (April 2024).",
        },
        {
            "id": "5", "name": "Token Mechanics", "applies_to": "crypto_only",
            "gate_type": "hard",
            "thresholds": {
                "min_circulating_to_total_supply_ratio": 0.30,
                "max_annual_emission_rate_pct_of_circulating": 25.0,
                "active_emission_exploits": 0,
                "vesting_schedule_publicly_verifiable": True,
                "historical_undisclosed_inflation_events": 0,
            },
            "rationale": "Token mechanics determine whether scoring has operational meaning. Undisclosed inflation or exploitable emission schedules render all pillar scores unreliable.",
            "data_sources": ["TokenUnlocks.app", "Messari", "Etherscan", "Solscan"],
            "example_rejection": "ICP — >90% undisclosed supply inflation in first 8 months post-launch (2021).",
        },
        {
            "id": "6", "name": "Trading History", "applies_to": "all",
            "gate_type": "soft_with_fasttrack",
            "thresholds": {
                "standard_min_days": 90,
                "fasttrack_min_days": 45,
                "fasttrack_conditions": [
                    "Institutional custody supported from launch (Criterion 3)",
                    "Full tokenomics published with on-chain verifiable vesting pre-launch",
                    "Minimum $10M audited VC or institutional funding verifiable on-chain",
                    "No supply anomalies in first 45 days of trading",
                ],
                "confidence_multiplier_45_to_90_days": 0.6,
                "confidence_multiplier_90_to_180_days": 0.85,
                "confidence_multiplier_above_180_days": 1.0,
            },
            "rationale": "90-day minimum covers one full calendar quarter — sufficient for M pillar momentum and initial O pillar risk profiling. 180-day requirement was too strict and would have excluded high-conviction emerging assets like Hyperliquid.",
            "data_sources": ["CoinGecko listing date", "Bloomberg IPO date", "Messari VC funding"],
        },
        {
            "id": "7", "name": "Team and Protocol Integrity", "applies_to": "all",
            "gate_type": "judgment_required",
            "disqualifying_conditions": [
                "Documented rug-pull history with no resolution",
                "Anonymous team with no institutional accountability (no audit + no legal entity + no 2yr clean record)",
                "Unresolved material exploit >$1M (root cause unpublished or users not made whole or vulnerability unpatched)",
                "Documented treasury misuse without governance approval",
                "Active leadership in financial crime legal proceedings",
            ],
            "remediation_pathway": {
                "available": True,
                "requirements": [
                    "Full public post-mortem published within 30 days of incident",
                    "Users made whole (≥80% of lost funds recovered or compensated)",
                    "Independent security audit completed and published post-incident",
                    "12+ consecutive months clean operation since incident",
                    "No repeat of same vulnerability class",
                ],
                "note": "Protocols that have genuinely fixed problems and demonstrated sustained recovery can re-qualify. This prevents permanent blacklisting that ignores rehabilitation evidence.",
            },
            "rationale": "The failure mode that cannot be defended when capital is lost. Most subjective criterion but most important for institutional credibility.",
            "data_sources": ["Rekt.news", "DeFiLlama hacks database", "SEC enforcement", "Messari governance research"],
            "example_rejections": ["AXS ($625M Ronin exploit)", "SUSHI (repeated treasury incidents)", "CRV (founder personal position systemic risk)", "RUNE (dual exploit 2021, now in remediation review)"],
        },
    ],
    "application_rules": {
        "logic": "AND — failure on any single criterion results in exclusion",
        "compensating_mechanisms": False,
        "order_of_evaluation": ["1 (liquidity) first for efficiency", "5 and 7 require most judgment, evaluated last"],
        "emergency_exclusion_triggers": [
            "Enforcement action naming issuing team",
            "Material exploit >$1M user funds at risk",
            "Liquidity breach below threshold for 7 consecutive days",
        ],
        "emergency_exclusion_sla_hours": 24,
    },
    "review_cadence": {
        "full_universe_review": "Monthly",
        "emergency_exclusion": "Within 24 hours of trigger",
        "borderline_reevaluation": "At next monthly review when blocking condition resolves",
    },
}


@router.get("/api/v1/agent/inclusion-standard")
async def get_inclusion_standard(criterion_id: str = ""):
    """
    Returns CometCloud's 7-criterion institutional inclusion standard as structured JSON.

    Machine-readable thresholds, rationale, data sources, and remediation pathways for
    each criterion. Designed for agent reasoning context — embed this in your system prompt
    to enable your agent to apply the same standard CometCloud uses.

    Filter to a specific criterion with ?criterion_id=7 (e.g. for team integrity checks only).
    """
    if criterion_id:
        criteria = [c for c in _INCLUSION_STANDARD["criteria"] if c["id"] == criterion_id]
        if not criteria:
            return JSONResponse(status_code=404, content={"error": f"Criterion {criterion_id} not found. Valid IDs: 1-7"})
        return JSONResponse(content={
            **{k: v for k, v in _INCLUSION_STANDARD.items() if k != "criteria"},
            "criteria": criteria,
        })
    return JSONResponse(content=_INCLUSION_STANDARD)


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

    # Send current state immediately on connect
    if store.last_cis_broadcast:
        await websocket.send_json(store.last_cis_broadcast)

    # Server-side heartbeat: send ping every 30s, expect pong within 10s.
    # Cleans up stale connections from crashed Mac Mini scheduler.
    _HEARTBEAT_INTERVAL = 30
    _PONG_TIMEOUT       = 10
    _pending_pong = False

    async def _heartbeat():
        nonlocal _pending_pong
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            try:
                if _pending_pong:
                    # Previous ping went unanswered — force close
                    await websocket.close(code=1001, reason="Heartbeat timeout")
                    return
                await websocket.send_json({"type": "ping", "ts": time.time()})
                _pending_pong = True
                # Give client 10s to pong before next heartbeat check
                await asyncio.sleep(_PONG_TIMEOUT)
                # If still pending after pong window, close on next iteration
            except Exception:
                return

    heartbeat_task = asyncio.create_task(_heartbeat())

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "pong" or data == '{"type":"pong"}':
                    _pending_pong = False  # Heartbeat acknowledged
            except Exception:
                break
    except Exception:
        pass
    finally:
        heartbeat_task.cancel()
        ws_manager.disconnect(websocket)


async def _broadcast_cis_update(universe: list):
    """Called by internal push endpoint when new scores arrive."""
    try:
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
                    "o":     _p(a, "o") or _p(a, "r"),
                    "ss":    _p(a, "s"),
                    "a":     _p(a, "a"),
                    "ch30d": a.get("change_30d"),
                    "ch7d":  a.get("change_7d"),
                }
                for a in universe
            ],
        }
        await ws_manager.broadcast(store.last_cis_broadcast)
    except Exception as e:
        _logger.warning(f"[WS] broadcast error (non-fatal): {e}")


# ---------------------------------------------------------------------------
# GET /api/v1/cis/history/{symbol}
# ---------------------------------------------------------------------------

@router.get("/cis/history/{symbol}")
async def get_cis_history(
    symbol: str,
    days: int = Query(default=30, ge=1, le=90),
):
    """Return CIS score history for a symbol from Supabase (Redis-cached, TTL=300s)."""
    sym = symbol.upper()
    cache_key = f"cis:history:{sym}:{days}"

    cached = await redis_get_key(cache_key)
    if cached:
        return cached

    rows = await supabase_get_history(sym, days)

    if not rows:
        result = {"symbol": sym, "history": [], "count": 0, "message": "No history found"}
    else:
        result = {
            "symbol": sym,
            "history": rows,
            "count": len(rows),
            "days_requested": days,
        }

    await redis_set_key(cache_key, result, ttl=300)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/cis/trend/{symbol}
# ---------------------------------------------------------------------------

@router.get("/cis/trend/{symbol}")
async def get_cis_trend(
    symbol: str,
    days: int = Query(default=7, ge=1, le=30),
):
    """Return trend direction (improving / stable / declining) for a symbol over N days."""
    sym = symbol.upper()

    rows = await supabase_get_history(sym, days)

    if len(rows) < 2:
        _logger.warning(f"[CIS trend] insufficient data for {sym}: {len(rows)} rows")
        return {"symbol": sym, "trend": "insufficient_data", "direction": None}

    half = len(rows) // 2
    recent_scores = [r.get("score", 0) for r in rows[:half]]
    older_scores  = [r.get("score", 0) for r in rows[half:]]

    avg_recent = sum(recent_scores) / len(recent_scores)
    avg_older  = sum(older_scores)  / len(older_scores)
    delta = avg_recent - avg_older

    if delta > 1:
        direction = "improving"
    elif delta < -1:
        direction = "declining"
    else:
        direction = "stable"

    return {
        "symbol":        sym,
        "trend":         direction,
        "delta_cis":     round(delta, 2),
        "avg_recent":    round(avg_recent, 2),
        "avg_older":     round(avg_older, 2),
        "data_points":   len(rows),
        "days":          days,
        "latest_grade":  rows[0].get("grade"),
        "latest_signal": rows[0].get("signal"),
    }


# ── CIS Score History + Trend (agent-queryable) ───────────────────────────────

@router.get("/api/v1/cis/history/{symbol}")
async def cis_history(symbol: str, days: int = 30):
    """
    Returns CIS score history for a single asset from Supabase.
    Agents use this for backtesting, trend detection, and score drift analysis.
    Cached in Redis 5 minutes to avoid hammering Supabase on repeated calls.

    Example: GET /api/v1/cis/history/BTC?days=7
    """
    symbol = symbol.upper()
    cache_key = f"cis:history:{symbol}:{days}"

    cached = await store.redis_get_key(cache_key)
    if cached:
        return cached

    rows = await store.supabase_get_history(symbol, days=days)

    if not rows:
        return {
            "symbol": symbol,
            "days": days,
            "count": 0,
            "history": [],
            "note": "No history found. Asset may not be in T1 universe or Supabase not yet populated."
        }

    result = {
        "symbol": symbol,
        "days": days,
        "count": len(rows),
        "history": sanitize_floats(rows),
    }

    await store.redis_set_key(cache_key, result, ttl=300)
    return result


@router.get("/api/v1/cis/trend/{symbol}")
async def cis_trend(symbol: str, days: int = 7):
    """
    Returns directional trend for a single asset: improving / stable / declining.
    Compares earliest vs latest CIS score over the window.
    Agents use this for momentum-based filtering and drift alerts.

    Example: GET /api/v1/cis/trend/ETH?days=7
    """
    symbol = symbol.upper()
    cache_key = f"cis:trend:{symbol}:{days}"

    cached = await store.redis_get_key(cache_key)
    if cached:
        return cached

    rows = await store.supabase_get_history(symbol, days=days)

    if len(rows) < 2:
        return {
            "symbol": symbol,
            "days": days,
            "trend": "insufficient_data",
            "data_points": len(rows),
        }

    # rows are desc (latest first)
    latest = rows[0]
    earliest = rows[-1]
    latest_score  = latest.get("score") or 0
    earliest_score = earliest.get("score") or 0
    delta = round(latest_score - earliest_score, 2)

    if delta >= 3:
        direction = "improving"
    elif delta <= -3:
        direction = "declining"
    else:
        direction = "stable"

    result = {
        "symbol":         symbol,
        "days":           days,
        "trend":          direction,
        "delta":          delta,
        "latest_score":   round(latest_score, 2),
        "earliest_score": round(earliest_score, 2),
        "latest_grade":   latest.get("grade"),
        "latest_signal":  latest.get("signal"),
        "recorded_at":    latest.get("recorded_at"),
        "data_points":    len(rows),
    }

    await store.redis_set_key(cache_key, result, ttl=300)
    return result
