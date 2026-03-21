"""
Vault router — GP funds, portfolio optimization
Endpoints: /api/v1/vault/*, /api/v1/portfolio/*
"""
import asyncio
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from datetime import datetime
import logging
import re

_logger = logging.getLogger(__name__)

# Asset validation: alphanumeric, 2-12 chars, comma-separated
_ASSET_RE = re.compile(r"^[A-Z0-9]{2,12}(,[A-Z0-9]{2,12})*$")

def _validate_assets(assets: str) -> list[str]:
    if not _ASSET_RE.match(assets.upper()):
        raise HTTPException(status_code=400, detail="Invalid asset format")
    return [s.strip().upper() for s in assets.split(",")]

router = APIRouter()


# ── Vault GP Funds ────────────────────────────────────────────────────────────

# Real verified GP partners only — no fictional data
_VAULT_FUNDS = [
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
        "performance": {"ytd": 0, "annualReturn": 0, "sharpeRatio": 0, "maxDrawdown": 0},
        "scores": {"performance": 0, "strategy": 0, "team": 0, "risk": 0, "transparency": 0, "aumTrackRecord": 0, "total": 0},
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
        "performance": {"ytd": 0, "annualReturn": 0, "sharpeRatio": 0, "maxDrawdown": 0},
        "scores": {"performance": 0, "strategy": 0, "team": 0, "risk": 0, "transparency": 0, "aumTrackRecord": 0, "total": 0},
        "grade": None,
        "description": "GP onboarding in progress.",
        "team": None,
        "strategyDetail": None,
        "advantage": None,
        "isPlaceholder": True,
    },
]


@router.get("/api/v1/vault/funds")
async def get_vault_funds():
    return {"timestamp": datetime.now().isoformat(), "data": _VAULT_FUNDS}


# ── Portfolio Optimization ────────────────────────────────────────────────────

class PortfolioRequest(BaseModel):
    assets: List[str] = ["BTC", "ETH", "SOL", "BNB", "AVAX"]
    strategy: str = "hrp"


@router.post("/api/v1/portfolio/optimize")
async def optimize_portfolio(request: PortfolioRequest):
    def _run():
        from analytics.portfolio.optimizer import CryptoPortfolioOptimizer
        optimizer = CryptoPortfolioOptimizer(assets=request.assets)
        optimizer.fetch_historical_data(days=90)
        if request.strategy == "hrp":
            return optimizer.optimize_hrp()
        elif request.strategy == "min_variance":
            return optimizer.optimize_min_variance()
        else:
            return optimizer.optimize_equal_weight()
    try:
        result = await asyncio.to_thread(_run)
        return {"timestamp": datetime.now().isoformat(), "result": result}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/api/v1/portfolio/stats")
async def get_portfolio_stats(assets: str = "BTC,ETH,SOL"):
    asset_list = _validate_assets(assets)

    def _run():
        from analytics.portfolio.optimizer import CryptoPortfolioOptimizer
        optimizer = CryptoPortfolioOptimizer(assets=asset_list)
        return optimizer, optimizer.fetch_historical_data(days=90)

    try:
        optimizer, prices = await asyncio.to_thread(_run)

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
                    "asset":      asset,
                    "return_90d": round(float(r.sum() * 100), 2),
                    "volatility": round(float(r.std() * np.sqrt(365) * 100), 2),
                    "sharpe":     round(float((r.mean() * 365) / (r.std() * np.sqrt(365) + 1e-9)), 2),
                    "price":      round(last_price, 2),
                })
            except Exception as e:
                stats.append({"asset": asset, "error": str(e)})

        return {"data": stats}
    except Exception as e:
        _logger.error(f"Error in {__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
