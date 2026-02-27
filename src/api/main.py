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
