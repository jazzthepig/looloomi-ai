"""
Looloomi AI - FastAPI Backend
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
from datetime import datetime
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

app = FastAPI(title="Looloomi AI API", version="0.2.0")

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

@app.get("/api/v1/market/prices")
async def get_prices(symbols: str = "BTC,ETH,SOL"):
    from data.market.exchange_data import ExchangeDataFetcher
    fetcher = ExchangeDataFetcher("binance")
    symbol_list = [s.strip() + "/USDT" for s in symbols.split(",")]
    tickers = fetcher.get_multiple_tickers(symbol_list)
    return {"timestamp": datetime.now().isoformat(), "data": tickers.to_dict(orient="records")}

@app.get("/api/v1/market/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, timeframe: str = "1d", limit: int = 30):
    from data.market.exchange_data import ExchangeDataFetcher
    fetcher = ExchangeDataFetcher("binance")
    pair = symbol.upper() + "/USDT"
    df = fetcher.get_ohlcv(pair, timeframe, limit)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data")
    df["timestamp"] = df["timestamp"].astype(str)
    return {"symbol": pair, "data": df.to_dict(orient="records")}

@app.post("/api/v1/portfolio/optimize")
async def optimize_portfolio(request: PortfolioRequest):
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

@app.get("/api/v1/portfolio/stats")
async def get_portfolio_stats(assets: str = "BTC,ETH,SOL"):
    from analytics.portfolio.optimizer import CryptoPortfolioOptimizer
    asset_list = [s.strip() for s in assets.split(",")]
    optimizer = CryptoPortfolioOptimizer(assets=asset_list)
    prices = optimizer.fetch_historical_data(days=90)
    stats = []
    for asset in asset_list:
        r = optimizer.returns_data[asset]
        stats.append({
            "asset": asset,
            "return_90d": round(float(r.sum() * 100), 2),
            "volatility": round(float(r.std() * np.sqrt(365) * 100), 2),
            "sharpe": round(float((r.mean() * 365) / (r.std() * np.sqrt(365))), 2),
            "price": round(float(prices[asset].iloc[-1]), 2)
        })
    return {"data": stats}

@app.get("/api/v1/mmi/{token}")
async def get_mmi(token: str = "bitcoin"):
    from analytics.mmi.mmi_index_v3 import LooloomiMMI
    mmi = LooloomiMMI(token)
    score = mmi.calculate()
    signal = mmi.get_signal(score)
    return {"token": token, "mmi_score": score, "signal": signal, "components": mmi.components}

@app.get("/api/v1/vc/funding-rounds")
async def get_funding_rounds(limit: int = 10):
    from data.vc.deal_flow import VCDealFlowTracker
    tracker = VCDealFlowTracker()
    rounds = tracker.get_recent_funding_rounds(limit)
    return {"timestamp": datetime.now().isoformat(), "data": rounds}

@app.get("/api/v1/vc/unlocks")
async def get_token_unlocks(days: int = 30):
    from data.vc.deal_flow import VCDealFlowTracker
    tracker = VCDealFlowTracker()
    unlocks = tracker.get_token_unlocks(days)
    return {"timestamp": datetime.now().isoformat(), "data": unlocks}

@app.get("/api/v1/vc/overlap")
async def get_vc_overlap():
    from data.vc.deal_flow import VCDealFlowTracker
    tracker = VCDealFlowTracker()
    overlap = tracker.get_vc_portfolio_overlap([])
    return {"timestamp": datetime.now().isoformat(), "data": overlap}

@app.get("/api/v1/vc/top-vcs")
async def get_top_vcs(limit: int = 10):
    from data.vc.deal_flow import VCDealFlowTracker
    tracker = VCDealFlowTracker()
    vcs = tracker.get_top_vcs(limit)
    return {"timestamp": datetime.now().isoformat(), "data": vcs}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Serve static files from dashboard build
dashboard_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dashboard", "dist")
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
