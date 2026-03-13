"""
Signal Server - CIS API for Agents
===================================
Port :8001 - Lightweight API for CIS scores
Designed for: Freqtrade bots, AI agents, x402 payments

Author: Seth
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio
import uvicorn
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.cis.cis_provider import (
    calculate_cis_universe,
    calculate_cis_score,
    calculate_total_score,
    get_grade,
    get_signal,
    ASSETS_CONFIG,
)


app = FastAPI(
    title="CometCloud CIS API",
    version="1.0.0",
    description="""# CometCloud Intelligence Score (CIS) API

## Overview
CIS is a cross-asset rating system that evaluates assets across five pillars:
- **F** - Fundamental (team, tokenomics, product, partnerships)
- **M** - Market Structure (liquidity, volume, exchange support)
- **O** - On-Chain Health (TVL, network activity)
- **S** - Sentiment (social signals, funding rate)
- **A** - Alpha Independence (correlation to BTC/ETH)

## Data Sources
- **Crypto**: CoinGecko API
- **TVL**: DeFiLlama
- **Sentiment**: Alternative.me (Fear & Greed)
- **Traditional Assets**: yfinance

## Authentication
Currently open. x402 payment integration coming soon.

## Rate Limits
- 60 requests/minute for live data
- Cached data served from 5-minute TTL

## Contact
- API Support: api@cometcloud.ai
- Documentation: docs.cometcloud.ai
""",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Response Models ───────────────────────────────────────────────────────

class CISAsset(BaseModel):
    symbol: str
    name: str
    asset_class: str
    cis_score: float
    grade: str
    signal: str
    f: float
    m: float
    o: float
    s: float
    a: float
    change_30d: float
    percentile: int


class CISMaro(BaseModel):
    regime: str
    fed_funds: float
    treasury_10y: float
    vix: float
    dxy: float
    cpi_yoy: float


class CISUniverseResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    data_source: str
    macro: CISMaro
    universe: List[CISAsset]
    asset_count: int


class CISSingleResponse(BaseModel):
    symbol: str
    name: str
    asset_class: str
    cis_score: float
    grade: str
    signal: str
    f: float
    m: float
    o: float
    s: float
    a: float
    change_30d: float
    percentile: int


class SignalResponse(BaseModel):
    signal: str
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float
    rationale: str


# ── Cache ──────────────────────────────────────────────────────────────────

_cache: Dict[str, Any] = {}
_cache_ttl = 300  # 5 minutes


def _get_cached(key: str) -> Optional[Any]:
    if key in _cache:
        val, ts = _cache[key]
        if datetime.now().timestamp() - ts < _cache_ttl:
            return val
    return None


def _set_cached(key: str, val: Any):
    _cache[key] = (val, datetime.now().timestamp())


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
async def root():
    """Health check."""
    return {
        "status": "healthy",
        "service": "CometCloud Signal API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health", tags=["health"])
async def health():
    """Health check (alternative)."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/v1/cis/universe", response_model=CISUniverseResponse, tags=["CIS"])
async def get_cis_universe(
    asset_class: Optional[str] = Query(None, description="Filter by asset class"),
    min_score: Optional[float] = Query(None, description="Minimum CIS score"),
    limit: Optional[int] = Query(None, description="Limit number of results"),
):
    """
    Get CIS universe with scores for all assets.

    Filters:
    - asset_class: Crypto, L1, L2, DeFi, RWA, US Equity, US Bond, Commodity
    - min_score: Minimum CIS score (0-100)
    - limit: Maximum number of results
    """
    # Try cache first
    cache_key = f"universe:{asset_class}:{min_score}:{limit}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        result = await calculate_cis_universe()

        # Apply filters
        universe = result.get("universe", [])

        if asset_class:
            universe = [a for a in universe if a["asset_class"] == asset_class]

        if min_score is not None:
            universe = [a for a in universe if a["cis_score"] >= min_score]

        if limit:
            universe = universe[:limit]

        response = {
            "status": result.get("status", "success"),
            "version": result.get("version", "1.0.0"),
            "timestamp": result.get("timestamp", datetime.now().isoformat()),
            "data_source": result.get("data_source", "coingecko+defillama"),
            "macro": result.get("macro", {}),
            "universe": universe,
            "asset_count": len(universe),
        }

        # Add 30d CIS change for each asset
        try:
            from src.data.cis.history_db import get_score_change
            history_map = {}
            for asset in universe:
                change = get_score_change(asset["symbol"], days=30)
                if change:
                    history_map[asset["symbol"]] = change
            response["history"] = history_map
        except Exception as e:
            print(f"Failed to get history: {e}")

        _set_cached(cache_key, response)
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/cis/asset/{symbol}", response_model=CISSingleResponse, tags=["CIS"])
async def get_cis_asset(symbol: str):
    """
    Get detailed CIS score for a specific asset.

    Example: /api/v1/cis/asset/BTC

    Returns complete breakdown with:
    - cis_score and grade
    - pillar breakdown with weights and contributions
    - component-level details
    - data sources
    """
    # Try cache first
    cache_key = f"asset:{symbol.upper()}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        result = await calculate_cis_universe()

        universe = result.get("universe", [])
        asset = next((a for a in universe if a["symbol"].upper() == symbol.upper()), None)

        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset {symbol} not found")

        # Build detailed response
        breakdown = asset.get("breakdown", {})

        response = {
            "symbol": asset["symbol"],
            "timestamp": result.get("timestamp", datetime.now().isoformat()),
            "data_freshness": result.get("timestamp"),
            "cis_score": asset["cis_score"],
            "cis_grade": asset["grade"],
            "signal": asset["signal"],
            "cross_asset_percentile": asset["percentile"],
            "macro_regime": result.get("macro", {}).get("regime", "Unknown"),
            "pillar_breakdown": {
                "fundamental": {
                    "score": asset.get("f", 0),
                    "weight": breakdown.get("fundamental", {}).get("weight", 0.25),
                    "contribution": breakdown.get("fundamental", {}).get("contribution", 0),
                    "components": breakdown.get("fundamental", {}).get("components", {}),
                },
                "momentum": {
                    "score": asset.get("m", 0),
                    "weight": breakdown.get("momentum", {}).get("weight", 0.25),
                    "contribution": breakdown.get("momentum", {}).get("contribution", 0),
                    "components": breakdown.get("momentum", {}).get("components", {}),
                },
                "risk_adjusted": {
                    "score": asset.get("r", 0),
                    "weight": breakdown.get("risk_adjusted", {}).get("weight", 0.20),
                    "contribution": breakdown.get("risk_adjusted", {}).get("contribution", 0),
                    "components": breakdown.get("risk_adjusted", {}).get("components", {}),
                },
                "sensitivity": {
                    "score": asset.get("s", 0),
                    "weight": breakdown.get("sensitivity", {}).get("weight", 0.15),
                    "contribution": breakdown.get("sensitivity", {}).get("contribution", 0),
                    "components": breakdown.get("sensitivity", {}).get("components", {}),
                },
                "alpha": {
                    "score": asset.get("a", 0),
                    "weight": breakdown.get("alpha", {}).get("weight", 0.15),
                    "contribution": breakdown.get("alpha", {}).get("contribution", 0),
                    "components": breakdown.get("alpha", {}).get("components", {}),
                },
            },
            "data_sources": {
                "price": "coingecko",
                "tvl": "defillama",
                "sentiment": "alternative.me",
                "macro": "yfinance" if asset.get("asset_class") in ["US Equity", "US Bond", "Commodity"] else "estimated",
            },
            "methodology_version": "CIS_v4.0_FMRSA",
        }

        _set_cached(cache_key, response)
        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/cis/grades", tags=["CIS"])
async def get_cis_grades():
    """
    Get CIS grade thresholds and definitions.
    """
    return {
        "grades": {
            "A+": {"min": 90, "max": 100, "label": "Top Tier", "action": "Strong Buy"},
            "A": {"min": 85, "max": 89.99, "label": "Excellent", "action": "Buy"},
            "B+": {"min": 80, "max": 84.99, "label": "Good", "action": "Buy"},
            "B": {"min": 70, "max": 79.99, "label": "Above Average", "action": "Hold"},
            "C+": {"min": 60, "max": 69.99, "label": "Average", "action": "Hold"},
            "C": {"min": 50, "max": 59.99, "label": "Below Average", "action": "Sell"},
            "D": {"min": 30, "max": 49.99, "label": "Poor", "action": "Sell"},
            "F": {"min": 0, "max": 29.99, "label": "Fail", "action": "Avoid"},
        },
        "pillars": {
            "F": "Fundamental - Team, tokenomics, product, partnerships",
            "M": "Market Structure - Liquidity, volume, exchange support",
            "O": "On-Chain Health - TVL, network activity, developer engagement",
            "S": "Sentiment - Social signals, funding rate, market sentiment",
            "A": "Alpha Independence - Correlation to BTC/ETH, uniqueness",
        },
    }


@app.get("/api/v1/signal/{symbol}", response_model=SignalResponse, tags=["Signals"])
async def get_trading_signal(symbol: str):
    """
    Get trading signal for a specific asset.

    Returns: signal type, action, confidence, and rationale
    """
    try:
        result = await calculate_cis_universe()
        universe = result.get("universe", [])

        asset = next((a for a in universe if a["symbol"].upper() == symbol.upper()), None)

        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset {symbol} not found")

        cis_score = asset["cis_score"]
        grade = asset["grade"]

        # Determine action
        if grade in ["A+", "A"]:
            action = "BUY"
            confidence = min(1.0, (cis_score - 80) / 20 + 0.7)
        elif grade in ["B+", "B"]:
            action = "HOLD"
            confidence = 0.6 + (cis_score - 70) / 100
        elif grade == "C+":
            action = "HOLD"
            confidence = 0.5
        else:
            action = "SELL"
            confidence = min(1.0, (60 - cis_score) / 60 + 0.6)

        # Generate rationale
        rationale = f"CIS Score: {cis_score:.1f} ({grade}). "
        rationale += f"Fundamental: {asset['f']}, "
        rationale += f"Market: {asset['m']}, "
        rationale += f"On-Chain: {asset['o']}, "
        rationale += f"Sentiment: {asset['s']}, "
        rationale += f"Alpha: {asset['a']}."

        return {
            "signal": asset["signal"],
            "action": action,
            "confidence": round(confidence, 2),
            "rationale": rationale,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/assets", tags=["Assets"])
async def list_assets(
    asset_class: Optional[str] = Query(None, description="Filter by asset class"),
):
    """
    List all available assets.
    """
    if asset_class:
        assets = [
            {"symbol": k, **v}
            for k, v in ASSETS_CONFIG.items()
            if v.get("class") == asset_class
        ]
    else:
        assets = [
            {"symbol": k, **v}
            for k, v in ASSETS_CONFIG.items()
        ]

    return {
        "assets": assets,
        "count": len(assets),
        "asset_classes": list(set(v.get("class") for v in ASSETS_CONFIG.values())),
    }


# ── Run Server ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("CometCloud Signal API")
    print("Port: 8001")
    print("Docs: http://localhost:8001/docs")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=8001)
