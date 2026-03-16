"""
Looloomi AI - FastAPI Backend v0.3.0
Real data from: Binance + DeFiLlama + Alternative.me + Moralis + Etherscan
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
from datetime import datetime
import sys, os, numpy as np

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

# ── Local Engine Cache (for JSON push from Mac Mini) ─────────────────────────────
# Stores CIS scores pushed from local cis_v4_engine
_local_cis_cache: dict = {
    "universe": [],
    "last_updated": None,
    "source": None,  # "local_engine" or "railway"
}

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
    """
    signals = []
    now = datetime.now()

    try:
        # 1. Fear & Greed Index
        fng = await get_fear_greed(limit=1)
        if fng.get("current"):
            fng_val = fng["current"].get("value", 50)
            fng_label = fng["current"].get("value_classification", "Neutral")
            fng_time = fng["current"].get("update_time", "")

            if fng_val <= 25:
                sig_type = "RISK"
                sig_importance = "HIGH"
                sig_desc = f"F&G指数极度恐惧({fng_val})，历史数据显示此时买入BTC长期回报优异"
            elif fng_val <= 45:
                sig_type = "MACRO"
                sig_importance = "MED"
                sig_desc = f"F&G指数恐惧({fng_val})，市场情绪低迷但未至极端"
            elif fng_val >= 75:
                sig_type = "RISK"
                sig_importance = "HIGH"
                sig_desc = f"F&G指数极度贪婪({fng_val})，风险积聚注意回调"
            elif fng_val >= 55:
                sig_type = "MACRO"
                sig_importance = "MED"
                sig_desc = f"F&G指数贪婪({fng_val})，市场乐观情绪上升"
            else:
                sig_type = "MACRO"
                sig_importance = "LOW"
                sig_desc = f"F&G指数中性({fng_val})，市场观望情绪浓厚"

            signals.append({
                "id": "fng_1",
                "timestamp": fng_time or now.isoformat(),
                "type": sig_type,
                "description": sig_desc,
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
                "importance": sig_importance,
                "source": "alternative.me",
                "value": fng_val,
            })

        # 2. Top Gainers/Losers
        movers = await get_top_gainers_losers()
        if movers.get("gainers"):
            for g in movers["gainers"][:2]:
                change = g.get("change_24h", 0) or 0
                if change >= 10:
                    signals.append({
                        "id": f"gainer_{g['symbol']}",
                        "timestamp": now.isoformat(),
                        "type": "MOMENTUM",
                        "description": f"{g['symbol']} 24h暴涨{change:.1f}%，强劲上涨动能",
                        "affected_assets": [g['symbol']],
                        "importance": "HIGH" if change >= 15 else "MED",
                        "source": "coingecko",
                        "value": change,
                    })

        if movers.get("losers"):
            for l in movers["losers"][:2]:
                change = l.get("change_24h", 0) or 0
                if change <= -10:
                    signals.append({
                        "id": f"loser_{l['symbol']}",
                        "timestamp": now.isoformat(),
                        "type": "RISK",
                        "description": f"{l['symbol']} 24h暴跌{abs(change):.1f}%，注意止损风险",
                        "affected_assets": [l['symbol']],
                        "importance": "HIGH" if change <= -15 else "MED",
                        "source": "coingecko",
                        "value": change,
                    })

        # 3. DeFi Overview - TVL changes
        defi = await get_defi_overview()
        tvl_change = defi.get("change_24h", 0)
        total_tvl = defi.get("total_tvl", 0)

        if total_tvl > 0:
            if tvl_change > 5:
                signals.append({
                    "id": "defi_tvl_up",
                    "timestamp": now.isoformat(),
                    "type": "FLOW",
                    "description": f"DeFi总TVL 24h增加{tvl_change:.1f}%，资金大幅流入(${total_tvl/1e9:.1f}B)",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "MED",
                    "source": "defillama",
                    "value": tvl_change,
                })
            elif tvl_change < -5:
                signals.append({
                    "id": "defi_tvl_down",
                    "timestamp": now.isoformat(),
                    "type": "RISK",
                    "description": f"DeFi总TVL 24h下降{abs(tvl_change):.1f}%，资金净流出",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "MED",
                    "source": "defillama",
                    "value": tvl_change,
                })

        # 4. Stablecoin flows
        stables = await get_stablecoin_overview()
        usdc_dom = stables.get("usdc", {}).get("dominance", 0)
        usdt_dom = stables.get("usdt", {}).get("dominance", 0)

        if usdc_dom > usdt_dom + 10:
            signals.append({
                "id": "stablecoin_shift",
                "timestamp": now.isoformat(),
                "type": "FLOW",
                "description": "USDC主导地位增强(+{:.1f}%)，机构资金偏好".format(usdc_dom - usdt_dom),
                "affected_assets": ["USDC", "USDT"],
                "importance": "LOW",
                "source": "defillama",
                "value": usdc_dom - usdt_dom,
            })

    except Exception as e:
        print(f"Signal generation error: {e}")

    # Sort by importance and timestamp
    importance_order = {"HIGH": 0, "MED": 1, "LOW": 2}
    signals.sort(key=lambda x: (importance_order.get(x["importance"], 2), x["timestamp"]), reverse=True)

    return {
        "status": "success",
        "version": "1.0.0",
        "timestamp": now.isoformat(),
        "data_source": "coingecko+defillama+alternative.me",
        "signals": signals[:10],
    }

# ── CIS (CometCloud Intelligence Score) ───────────────────────────────────

# Internal token from environment (set in Railway dashboard)
import os
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


@app.post("/internal/cis-scores")
async def receive_local_cis_scores(payload: dict, x_internal_token: str = None):
    """
    Internal endpoint to receive CIS scores from local Mac Mini engine.
    Called by cis_push.py after local engine completes scoring.
    Requires X-Internal-Token header for authentication.
    """
    global _local_cis_cache

    # Debug: log what's received
    print(f"[DEBUG] INTERNAL_TOKEN env: '{_INTERNAL_TOKEN}', header: '{x_internal_token}'")

    # Verify internal token (optional - only validate if token is set AND header provided)
    if _INTERNAL_TOKEN and x_internal_token and x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        universe = payload.get("universe", [])
        timestamp = payload.get("timestamp")

        _local_cis_cache["universe"] = universe
        _local_cis_cache["last_updated"] = timestamp
        _local_cis_cache["source"] = "local_engine"

        print(f"[INTERNAL] Received {len(universe)} CIS scores from local engine")

        return {"status": "success", "received": len(universe)}
    except Exception as e:
        print(f"Error receiving CIS scores: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/cis/universe")
async def get_cis_universe(force_source: str = None):
    """
    CIS v4.0 Universe Endpoint
    Returns CIS scores. Priority: local_engine cache > Railway calculation
    """
    # Check if local engine cache has fresh data (less than 2 hours old)
    global _local_cis_cache

    use_local = False
    if force_source == "local" or (force_source != "railway" and _local_cis_cache["universe"]):
        if _local_cis_cache["last_updated"]:
            import time
            age = time.time() - _local_cis_cache["last_updated"]
            if age < 7200:  # Less than 2 hours
                use_local = True

    if use_local:
        return {
            "status": "success",
            "version": "4.0.0",
            "timestamp": _local_cis_cache["last_updated"],
            "source": "local_engine",
            "universe": _local_cis_cache["universe"],
        }

    # Fallback to Railway calculation
    try:
        result = await calculate_cis_universe()
        result["source"] = "railway"
        return result
    except Exception as e:
        print(f"CIS calculation error: {e}")
        # If Railway fails and we have stale local cache, return it
        if _local_cis_cache["universe"]:
            return {
                "status": "degraded",
                "message": str(e),
                "source": "local_engine_stale",
                "universe": _local_cis_cache["universe"],
            }
        return {
            "status": "error",
            "message": str(e),
            "universe": []
        }

@app.get("/api/v1/cis/asset/{symbol}")
async def get_cis_asset(symbol: str):
    """
    Get CIS score for a specific asset
    """
    universe = await get_cis_universe()
    for asset in universe.get("universe", []):
        if asset["symbol"].upper() == symbol.upper():
            return asset
    return {"error": "Asset not found"}


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
