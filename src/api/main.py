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

# ── CIS (CometCloud Intelligence Score) ───────────────────────────────────

@app.get("/api/v1/cis/universe")
async def get_cis_universe():
    """
    CIS v4.0 Universe Endpoint
    Returns CIS scores for all tracked assets across 8 classes
    """
    from datetime import datetime

    # Mock data - in production, this would connect to cometcloud-local cis_scheduler
    mock_data = {
        "status": "success",
        "version": "4.0.0",
        "timestamp": datetime.now().isoformat(),
        "macro": {
            "regime": "Tightening",
            "fed_funds": 5.25,
            "treasury_10y": 4.25,
            "vix": 18.0,
            "dxy": 104.0,
            "cpi_yoy": 3.2,
        },
        "universe": [
            {"symbol": "BTC", "name": "Bitcoin", "asset_class": "Crypto", "cis_score": 82.3, "grade": "A", "signal": "OVERWEIGHT", "f": 85, "m": 78, "r": 84, "s": 72, "a": 88, "change_30d": 4.2, "percentile": 91},
            {"symbol": "ETH", "name": "Ethereum", "asset_class": "Crypto", "cis_score": 76.8, "grade": "B+", "signal": "OVERWEIGHT", "f": 80, "m": 74, "r": 78, "s": 68, "a": 76, "change_30d": -1.3, "percentile": 82},
            {"symbol": "SOL", "name": "Solana", "asset_class": "Crypto", "cis_score": 74.1, "grade": "B+", "signal": "NEUTRAL", "f": 72, "m": 82, "r": 70, "s": 74, "a": 68, "change_30d": 6.8, "percentile": 78},
            {"symbol": "NVDA", "name": "NVIDIA", "asset_class": "US Equity", "cis_score": 88.5, "grade": "A+", "signal": "STRONG OVERWEIGHT", "f": 92, "m": 90, "r": 85, "s": 82, "a": 91, "change_30d": 2.1, "percentile": 96},
            {"symbol": "SPY", "name": "S&P 500", "asset_class": "US Equity", "cis_score": 71.2, "grade": "B", "signal": "NEUTRAL", "f": 70, "m": 68, "r": 76, "s": 72, "a": 65, "change_30d": -0.8, "percentile": 68},
            {"symbol": "AAPL", "name": "Apple", "asset_class": "US Equity", "cis_score": 79.4, "grade": "B+", "signal": "OVERWEIGHT", "f": 84, "m": 76, "r": 80, "s": 74, "a": 78, "change_30d": 1.5, "percentile": 85},
            {"symbol": "GLD", "name": "Gold", "asset_class": "Commodity", "cis_score": 84.7, "grade": "A", "signal": "STRONG OVERWEIGHT", "f": 78, "m": 88, "r": 90, "s": 85, "a": 82, "change_30d": 5.4, "percentile": 93},
            {"symbol": "TLT", "name": "20Y Treasury", "asset_class": "US Bond", "cis_score": 58.3, "grade": "C+", "signal": "UNDERWEIGHT", "f": 65, "m": 45, "r": 62, "s": 58, "a": 55, "change_30d": -3.2, "percentile": 35},
            {"symbol": "ONDO", "name": "Ondo Finance", "asset_class": "Crypto", "cis_score": 71.9, "grade": "B", "signal": "OVERWEIGHT", "f": 78, "m": 65, "r": 72, "s": 62, "a": 80, "change_30d": 12.1, "percentile": 70},
            {"symbol": "LINK", "name": "Chainlink", "asset_class": "Crypto", "cis_score": 73.5, "grade": "B+", "signal": "OVERWEIGHT", "f": 76, "m": 70, "r": 74, "s": 70, "a": 75, "change_30d": 3.7, "percentile": 76},
            {"symbol": "AAVE", "name": "Aave", "asset_class": "Crypto", "cis_score": 69.8, "grade": "B", "signal": "NEUTRAL", "f": 74, "m": 66, "r": 70, "s": 64, "a": 72, "change_30d": -2.5, "percentile": 62},
            {"symbol": "QQQ", "name": "Nasdaq 100", "asset_class": "US Equity", "cis_score": 75.6, "grade": "B+", "signal": "OVERWEIGHT", "f": 78, "m": 74, "r": 76, "s": 72, "a": 74, "change_30d": 0.4, "percentile": 80},
            {"symbol": "SLV", "name": "Silver", "asset_class": "Commodity", "cis_score": 68.2, "grade": "B", "signal": "NEUTRAL", "f": 62, "m": 72, "r": 68, "s": 70, "a": 64, "change_30d": 7.2, "percentile": 58},
            {"symbol": "HYG", "name": "High Yield Bond", "asset_class": "US Bond", "cis_score": 52.1, "grade": "C", "signal": "UNDERWEIGHT", "f": 55, "m": 48, "r": 54, "s": 50, "a": 52, "change_30d": -1.8, "percentile": 22},
            {"symbol": "AVAX", "name": "Avalanche", "asset_class": "Crypto", "cis_score": 62.4, "grade": "C+", "signal": "NEUTRAL", "f": 66, "m": 58, "r": 64, "s": 60, "a": 63, "change_30d": -5.1, "percentile": 45},
            {"symbol": "EEM", "name": "EM Equity", "asset_class": "EM Equity", "cis_score": 56.7, "grade": "C+", "signal": "UNDERWEIGHT", "f": 58, "m": 52, "r": 60, "s": 55, "a": 54, "change_30d": -2.9, "percentile": 30},
        ]
    }

    # Sort by CIS score
    mock_data["universe"].sort(key=lambda x: x["cis_score"], reverse=True)

    return mock_data

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
