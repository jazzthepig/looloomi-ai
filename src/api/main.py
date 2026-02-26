"""
Looloomi AI - FastAPI Backend v0.2.1
Fixes: KeyError on returns_data columns, CoinGecko 429 caching
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
from datetime import datetime
import sys, os, numpy as np, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

app = FastAPI(title="Looloomi AI API", version="0.2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Simple in-memory cache to avoid CoinGecko 429 ─────────────────────────────
_cache: dict = {}
CACHE_TTL = 120  # seconds

def cache_get(key: str):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return val
    return None

def cache_set(key: str, val):
    _cache[key] = (val, time.time())

# ── Models ─────────────────────────────────────────────────────────────────────
class PortfolioRequest(BaseModel):
    assets: List[str] = ["BTC", "ETH", "SOL", "BNB", "AVAX"]
    strategy: str = "hrp"

# ── Market endpoints ───────────────────────────────────────────────────────────
@app.get("/api/v1/market/prices")
async def get_prices(symbols: str = "BTC,ETH,SOL"):
    cache_key = f"prices:{symbols}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        from data.market.exchange_data import ExchangeDataFetcher
        fetcher = ExchangeDataFetcher("binance")
        symbol_list = [s.strip() + "/USDT" for s in symbols.split(",")]
        tickers = fetcher.get_multiple_tickers(symbol_list)
        result = {"timestamp": datetime.now().isoformat(), "data": tickers.to_dict(orient="records")}
        cache_set(cache_key, result)
        return result
    except Exception as e:
        # Fallback mock prices if API fails
        symbol_list = [s.strip() for s in symbols.split(",")]
        fallback_prices = {"BTC": 44800, "ETH": 2850, "SOL": 145, "BNB": 380, "AVAX": 28}
        data = [{"symbol": s + "/USDT", "price": fallback_prices.get(s, 100), "source": "fallback"} for s in symbol_list]
        return {"timestamp": datetime.now().isoformat(), "data": data, "warning": str(e)}

@app.get("/api/v1/market/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, timeframe: str = "1d", limit: int = 30):
    cache_key = f"ohlcv:{symbol}:{timeframe}:{limit}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        from data.market.exchange_data import ExchangeDataFetcher
        fetcher = ExchangeDataFetcher("binance")
        pair = symbol.upper() + "/USDT"
        df = fetcher.get_ohlcv(pair, timeframe, limit)
        if df.empty:
            raise HTTPException(status_code=404, detail="No data")
        df["timestamp"] = df["timestamp"].astype(str)
        result = {"symbol": pair, "data": df.to_dict(orient="records")}
        cache_set(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch error: {str(e)}")

# ── Portfolio endpoints ────────────────────────────────────────────────────────
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
    cache_key = f"stats:{assets}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        from analytics.portfolio.optimizer import CryptoPortfolioOptimizer
        asset_list = [s.strip() for s in assets.split(",")]
        optimizer = CryptoPortfolioOptimizer(assets=asset_list)
        prices = optimizer.fetch_historical_data(days=90)

        # ── FIX: returns_data columns may be integer-indexed ──────────────────
        # Rename columns to match asset names if needed
        if optimizer.returns_data is not None:
            cols = list(optimizer.returns_data.columns)
            # If columns are 0,1,2... rename them to asset names
            if len(cols) == len(asset_list) and all(isinstance(c, (int, float)) for c in cols):
                optimizer.returns_data.columns = asset_list
            # If columns are named differently (e.g. "BTC/USDT"), map them
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
                    "asset": asset,
                    "return_90d": round(float(r.sum() * 100), 2),
                    "volatility": round(float(r.std() * np.sqrt(365) * 100), 2),
                    "sharpe": round(float((r.mean() * 365) / (r.std() * np.sqrt(365) + 1e-9)), 2),
                    "price": round(last_price, 2)
                })
            except (KeyError, Exception) as e:
                # Graceful fallback for individual assets
                stats.append({
                    "asset": asset,
                    "return_90d": 0.0,
                    "volatility": 0.0,
                    "sharpe": 0.0,
                    "price": 0.0,
                    "error": str(e)
                })

        result = {"data": stats}
        cache_set(cache_key, result)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Portfolio stats error: {str(e)}")

# ── MMI endpoint ───────────────────────────────────────────────────────────────
@app.get("/api/v1/mmi/{token}")
async def get_mmi(token: str = "bitcoin"):
    cache_key = f"mmi:{token}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        from analytics.mmi.mmi_index_v3 import LooloomiMMI
        mmi = LooloomiMMI(token)
        score = mmi.calculate()
        signal = mmi.get_signal(score)
        result = {"token": token, "mmi_score": score, "signal": signal, "components": mmi.components}
        cache_set(cache_key, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── VC endpoints ───────────────────────────────────────────────────────────────
@app.get("/api/v1/vc/funding-rounds")
async def get_funding_rounds(limit: int = 10):
    try:
        from data.vc.deal_flow import VCDealFlowTracker
        tracker = VCDealFlowTracker()
        rounds = tracker.get_recent_funding_rounds(limit)
        return {"timestamp": datetime.now().isoformat(), "data": rounds}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/vc/unlocks")
async def get_token_unlocks(days: int = 30):
    try:
        from data.vc.deal_flow import VCDealFlowTracker
        tracker = VCDealFlowTracker()
        unlocks = tracker.get_token_unlocks(days)
        return {"timestamp": datetime.now().isoformat(), "data": unlocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/vc/overlap")
async def get_vc_overlap():
    try:
        from data.vc.deal_flow import VCDealFlowTracker
        tracker = VCDealFlowTracker()
        overlap = tracker.get_vc_portfolio_overlap([])
        return {"timestamp": datetime.now().isoformat(), "data": overlap}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/vc/top-vcs")
async def get_top_vcs(limit: int = 10):
    try:
        from data.vc.deal_flow import VCDealFlowTracker
        tracker = VCDealFlowTracker()
        vcs = tracker.get_top_vcs(limit)
        return {"timestamp": datetime.now().isoformat(), "data": vcs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "0.2.1", "cache_keys": len(_cache)}

# ── Serve React SPA (dashboard/dist) ──────────────────────────────────────────
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
