"""
Vault router — GP funds, portfolio optimization
Endpoints: /api/v1/vault/*, /api/v1/portfolio/*
"""
import asyncio
import numpy as np
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging
import re
import os

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
        "grade": "A",  # 83 ≥ 75 → A per CIS thresholds (A+=85, A=75, B+=65, B=55)
        "description": "CometCloud's flagship GP partner specializing in institutional DeFi strategies.",
        "team": "Ex-Jane Street, Wintermute, Delphi Digital",
        "strategyDetail": "Multi-strategy DeFi: yield optimization, delta-neutral, protocol governance",
        "advantage": "Direct integration with CometCloud vault infrastructure",
    },
    {
        "id": "humblebee-capital",
        "name": "HumbleBee Capital",
        "strategy": "Structured Yield",
        "location": "Hong Kong",
        "aum": "Confidential",
        "yearFounded": 2023,
        "status": "active",
        "verified": True,
        "note": "CometCloud GP Partner · Drift Vault Integration",
        "performance": {"ytd": None, "annualReturn": None, "sharpeRatio": None, "maxDrawdown": None, "_note": "Live on-chain — see Drift vault for real-time NAV"},
        "scores": {"performance": None, "strategy": None, "team": None, "risk": None, "transparency": None, "aumTrackRecord": None, "total": None, "_note": "Assessment in progress"},
        "grade": "—",
        "description": "Hong Kong-based structured yield specialist operating on-chain vaults via Drift Protocol on Solana. On-chain transparency with real-time NAV and permissionless entry.",
        "team": "Institutional DeFi specialists, Hong Kong",
        "strategyDetail": "Drift Protocol vault: systematic structured yield on Solana. On-chain transparency, permissionless entry.",
        "advantage": "Live on-chain vault — real-time NAV, on-chain audit trail, direct Drift integration",
        "driftVault": "FS9fJYRrQ2hQPcXJTFrC1zBskTE3z4WayzbYL8jFrQK7",
        "vaultUrl": "https://app.drift.trade/vaults/strategy-vaults/FS9fJYRrQ2hQPcXJTFrC1zBskTE3z4WayzbYL8jFrQK7",
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


# ── Partner Vaults (on-chain, Drift Protocol) ─────────────────────────────────

# KnightTrade / HumbleBee Capital vault on Drift
_PARTNER_VAULTS = [
    {
        "id": "humblebee-drift-1",
        "partner": "HumbleBee Capital",
        "protocol": "Drift",
        "chain": "Solana",
        "vaultAddress": "FS9fJYRrQ2hQPcXJTFrC1zBskTE3z4WayzbYL8jFrQK7",
        "vaultUrl": "https://app.drift.trade/vaults/strategy-vaults/FS9fJYRrQ2hQPcXJTFrC1zBskTE3z4WayzbYL8jFrQK7",
        "platform": "Drift",
    }
]

# Drift vault API — public endpoint for vault stats
_DRIFT_VAULT_API = "https://dlob.drift.trade/vault/{address}"
_DRIFT_VAULTS_API = "https://drift-v2.api.drift.trade/vaults/{address}"


async def _fetch_drift_vault(vault_address: str) -> dict:
    """Fetch live stats for a Drift vault. Falls back to placeholder on error."""
    import httpx
    urls = [
        f"https://drift-v2.api.drift.trade/vaults/{vault_address}",
        f"https://mainnet-beta.api.drift.trade/vaults/{vault_address}",
    ]
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(url, headers={"Accept": "application/json"})
                if r.status_code == 200:
                    data = r.json()
                    # Normalise Drift API response into our schema
                    vault = data.get("vault") or data.get("data") or data
                    return {
                        "tvl": vault.get("totalShares") or vault.get("tvl") or vault.get("userShares"),
                        "tvlUsd": vault.get("tvlUsd") or vault.get("netDeposits"),
                        "apy": vault.get("apyEstimate") or vault.get("apy") or vault.get("annualizedReturn"),
                        "capacity": vault.get("maxTokens") or vault.get("capacity"),
                        "utilizationPct": vault.get("utilizationPct"),
                        "depositors": vault.get("numberOfSubaccounts") or vault.get("depositors"),
                        "managementFee": vault.get("managementFee"),
                        "profitShare": vault.get("profitShare") or vault.get("performanceFee"),
                        "redeemPeriod": vault.get("redeemPeriodSecs"),
                        "live": True,
                    }
        except Exception:
            continue
    # All endpoints failed — return stub so frontend still renders
    return {"live": False}


# ── Vault Deposit Intent (Memo attribution) ───────────────────────────────────

class DepositIntentRequest(BaseModel):
    wallet_address: str
    vault_id: str                   # e.g. "humblebee-drift-1"
    vault_address: str              # Drift vault pubkey
    partner: str                    # e.g. "HumbleBee Capital"
    amount_usdc: float
    tx_signature: str               # Solana memo tx sig
    memo_data: Optional[dict] = None


@router.post("/api/v1/vault/deposit-intent")
async def record_deposit_intent(req: DepositIntentRequest):
    """
    Record a vault deposit intent from CometCloud platform.
    Stores wallet + tx signature for AUM attribution.
    Persists to Redis (Supabase when available).
    """
    import json

    record = {
        "wallet_address": req.wallet_address,
        "vault_id":       req.vault_id,
        "vault_address":  req.vault_address,
        "partner":        req.partner,
        "amount_usdc":    req.amount_usdc,
        "tx_signature":   req.tx_signature,
        "memo_data":      req.memo_data or {},
        "created_at":     datetime.utcnow().isoformat(),
        "source":         "cometcloud",
    }

    stored = False

    # Try Supabase first
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if supabase_url and supabase_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(
                    f"{supabase_url}/rest/v1/vault_deposit_intents",
                    headers={
                        "apikey":        supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type":  "application/json",
                        "Prefer":        "return=minimal",
                    },
                    json=record,
                )
                if r.status_code in (200, 201):
                    stored = True
        except Exception as e:
            _logger.warning(f"Supabase deposit intent write failed: {e}")

    # Fallback: Redis list (last 500 intents)
    if not stored:
        try:
            try:
                from src.data.market.data_layer import _redis_set, _redis_get
            except ImportError:
                from data.market.data_layer import _redis_set, _redis_get
            existing_raw = await _redis_get("vault:deposit_intents")
            existing = json.loads(existing_raw) if existing_raw else []
            existing.append(record)
            await _redis_set("vault:deposit_intents", json.dumps(existing[-500:]), ttl=86400 * 30)
            stored = True
        except Exception as e:
            _logger.warning(f"Redis deposit intent write failed: {e}")

    _logger.info(
        f"Deposit intent: {req.wallet_address[:8]}… → {req.partner} "
        f"${req.amount_usdc} USDC | tx={req.tx_signature[:12]}… | stored={stored}"
    )

    return {
        "ok":           True,
        "stored":       stored,
        "tx_signature": req.tx_signature,
        "explorer_url": f"https://solscan.io/tx/{req.tx_signature}",
        "message":      f"Deposit intent recorded for {req.partner}. Complete your deposit on Drift.",
    }


@router.get("/api/v1/vault/partner-vaults")
async def get_partner_vaults():
    """Return partner vault list enriched with live on-chain data from Drift."""
    tasks = [_fetch_drift_vault(v["vaultAddress"]) for v in _PARTNER_VAULTS]
    live_data = await asyncio.gather(*tasks, return_exceptions=True)

    result = []
    for vault_meta, on_chain in zip(_PARTNER_VAULTS, live_data):
        entry = {**vault_meta}
        if isinstance(on_chain, dict):
            entry["onChain"] = on_chain
        else:
            entry["onChain"] = {"live": False}
        result.append(entry)

    return {"timestamp": datetime.now().isoformat(), "data": result}


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
