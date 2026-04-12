"""
Fund Factory Router — FastAPI Backend Integration
================================================

Provides REST API for on-chain Fund Factory operations.
Bridges the React frontend with the Solana Anchor program.

POST /api/v1/factory/deploy    — GP creates new fund
POST /api/v1/factory/deposit   — Investor deposits USDC
POST /api/v1/factory/redeem    — Investor redeems shares
POST /api/v1/factory/nav       — GP updates NAV
GET  /api/v1/factory/funds     — List all funds
GET  /api/v1/factory/fund/{id} — Get fund details
"""

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import asyncio
import os

_INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")

router = APIRouter(prefix="/api/v1/factory", tags=["factory"])

# ============================================================================
# Pydantic Models
# ============================================================================

class CreateFundRequest(BaseModel):
    fund_id: int = Field(..., description="Unique fund ID")
    name: str = Field(..., max_length=32, description="Fund name")
    symbol: str = Field(..., max_length=8, description="Fund symbol")
    management_fee_bps: int = Field(..., ge=0, le=10000, description="Management fee in bps")
    performance_fee_bps: int = Field(..., ge=0, le=10000, description="Performance fee in bps")
    min_investment: int = Field(..., gt=0, description="Minimum investment amount")
    max_investment: int = Field(..., gt=0, description="Maximum investment amount")
    gp_authority: str = Field(..., description="GP authority public key (base58)")
    treasury: str = Field(..., description="Treasury public key (base58)")


class DepositRequest(BaseModel):
    fund_id: int = Field(..., description="Fund ID")
    base_currency_amount: int = Field(..., gt=0, description="USDC amount to deposit")
    investor_wallet: str = Field(..., description="Investor wallet public key")


class RedeemRequest(BaseModel):
    fund_id: int = Field(..., description="Fund ID")
    share_amount: int = Field(..., gt=0, description="Share amount to redeem")
    investor_wallet: str = Field(..., description="Investor wallet public key")


class UpdateNavRequest(BaseModel):
    fund_id: int = Field(..., description="Fund ID")
    new_nav: int = Field(..., gt=0, description="New NAV value")
    gp_authority: str = Field(..., description="GP authority public key")


class WhitelistRequest(BaseModel):
    fund_id: int = Field(..., description="Fund ID")
    investor: str = Field(..., description="Investor wallet public key")
    kyc_level: int = Field(..., ge=0, le=2, description="KYC level (0=none, 1=accredited, 2=institutional)")
    add: bool = Field(..., description="Add or remove from whitelist")


class FundResponse(BaseModel):
    fund_id: int
    name: str
    symbol: str
    fund_mint: str
    nav: float
    total_shares: float
    management_fee_bps: int
    performance_fee_bps: int
    min_investment: int
    max_investment: int
    is_paused: bool
    gp_authority: str
    created_at: str
    data_source: str = "solana_mainnet"  # "solana_mainnet" or "mock"


class InvestorPositionResponse(BaseModel):
    fund_id: int
    investor: str
    shares: float
    last_nav: float
    cumulative_fees: float
    data_source: str = "solana_mainnet"


# ============================================================================
# Mock Data Store (replace with actual Solana RPC calls)
# ============================================================================

# In production, this would be populated by reading from Solana
MOCK_FUNDS = {
    1: {
        "fund_id": 1,
        "name": "EST Alpha Growth Fund",
        "symbol": "ESTAGF",
        "fund_mint": "Ej7eH8tzL5wD8vN1rQhvLnXWQXtLmZ3q9L8hBk4V2mX",
        "nav": 1.05,
        "total_shares": 1_000_000,
        "management_fee_bps": 200,
        "performance_fee_bps": 2000,
        "min_investment": 10_000,
        "max_investment": 1_000_000,
        "is_paused": False,
        "gp_authority": "GpAuthority1111111111111111111111111111111111111",
        "treasury": "Treasury1111111111111111111111111111111111111",
        "created_at": "2026-03-01T00:00:00Z",
        "data_source": "mock",  # Solana RPC not yet integrated
    }
}


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/funds", response_model=List[FundResponse])
async def list_funds():
    """List all deployed funds on-chain."""
    return [
        FundResponse(**fund) for fund in MOCK_FUNDS.values()
    ]


@router.get("/fund/{fund_id}", response_model=FundResponse)
async def get_fund(fund_id: int):
    """Get details of a specific fund."""
    if fund_id not in MOCK_FUNDS:
        raise HTTPException(status_code=404, detail="Fund not found")
    return FundResponse(**MOCK_FUNDS[fund_id])


@router.post("/deploy")
async def deploy_fund(
    request: CreateFundRequest,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    """
    Deploy a new fund to Solana.

    This endpoint constructs the Anchor transaction for creating a new fund.
    The transaction must be signed by the GP authority wallet.

    In production:
    1. Construct create_fund Anchor instruction
    2. Simulate to verify
    3. Return unsigned transaction for wallet signing
    4. Wait for signed tx submission
    """
    # TODO: Integrate with Solana RPC
    # - Construct transaction using FundFactoryClient
    # - Get recent blockhash
    # - Simulate to check for errors
    # - Return { transaction: base64, message: "Sign with wallet" }

    # Auth: reject-by-default
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {
        "status": "pending",
        "fund_id": request.fund_id,
        "message": "Transaction constructed. Awaiting wallet signature.",
        "transaction": None,  # Will be populated after wallet integration
        "estimated_fee": 0.000005,  # SOL
        "instructions": [
            "initializeFactory (if not done)",
            "createFund",
            "createToken2022Mint",
            "createFundVault",
        ],
        "data_source": "mock",  # Solana RPC not yet integrated
    }


@router.post("/deposit")
async def deposit(
    request: DepositRequest,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    """
    Deposit USDC into a fund and receive fund shares.

    Flow:
    1. Verify investor is whitelisted
    2. Verify amount within investment limits
    3. Calculate shares to mint (amount / nav)
    4. Construct deposit instruction
    5. Return transaction for signing
    """
    # TODO: Integrate with Solana RPC
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    fund = MOCK_FUNDS.get(request.fund_id)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    if fund["is_paused"]:
        raise HTTPException(status_code=400, detail="Fund is paused")

    if request.base_currency_amount < fund["min_investment"]:
        raise HTTPException(status_code=400, detail="Below minimum investment")

    if request.base_currency_amount > fund["max_investment"]:
        raise HTTPException(status_code=400, detail="Above maximum investment")

    # Calculate shares
    shares = request.base_currency_amount / fund["nav"]

    return {
        "status": "pending",
        "fund_id": request.fund_id,
        "investor": request.investor_wallet,
        "base_currency_amount": request.base_currency_amount,
        "shares_to_mint": shares,
        "nav": fund["nav"],
        "message": "Deposit transaction constructed. Awaiting wallet signature.",
        "data_source": "mock",
    }


@router.post("/redeem")
async def redeem(
    request: RedeemRequest,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    """
    Redeem fund shares for USDC.

    Flow:
    1. Verify investor has sufficient shares
    2. Calculate USDC to receive (shares * nav)
    3. Deduct fees
    4. Construct redeem instruction
    5. Return transaction for signing
    """
    # TODO: Integrate with Solana RPC
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    fund = MOCK_FUNDS.get(request.fund_id)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    if fund["is_paused"]:
        raise HTTPException(status_code=400, detail="Fund is paused")

    # Calculate USDC to receive
    base_currency_amount = request.share_amount * fund["nav"]
    management_fee = base_currency_amount * (fund["management_fee_bps"] / 10000)
    net_amount = base_currency_amount - management_fee

    return {
        "status": "pending",
        "fund_id": request.fund_id,
        "investor": request.investor_wallet,
        "share_amount": request.share_amount,
        "base_currency_amount": base_currency_amount,
        "fees_paid": management_fee,
        "net_amount": net_amount,
        "nav": fund["nav"],
        "message": "Redeem transaction constructed. Awaiting wallet signature.",
        "data_source": "mock",
    }


@router.post("/nav")
async def update_nav(
    request: UpdateNavRequest,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    """
    Update fund NAV (GP only).

    This endpoint should be called by the backend after:
    1. Fetching prices from oracles (DeFiLlama, CoinGecko, Binance)
    2. Calculating new NAV
    3. Signing with GP authority
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    # TODO: Integrate with Solana RPC

    fund = MOCK_FUNDS.get(request.fund_id)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    old_nav = fund["nav"]

    # In production: update on-chain NAV
    # For now: mock update
    fund["nav"] = request.new_nav / 1_000_000  # Convert from integer with 6 decimals

    return {
        "status": "success",
        "fund_id": request.fund_id,
        "old_nav": old_nav,
        "new_nav": fund["nav"],
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_source": "mock",
    }


@router.post("/whitelist")
async def manage_whitelist(
    request: WhitelistRequest,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
):
    """
    Add or remove investor from fund whitelist.

    KYC levels:
    - 0: None (not allowed to invest)
    - 1: Accredited investor
    - 2: Institutional investor
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    # TODO: Integrate with Solana RPC

    fund = MOCK_FUNDS.get(request.fund_id)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    return {
        "status": "success",
        "fund_id": request.fund_id,
        "investor": request.investor,
        "kyc_level": request.kyc_level,
        "action": "added" if request.add else "removed",
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_source": "mock",
    }


@router.get("/position/{fund_id}/{investor}")
async def get_investor_position(fund_id: int, investor: str):
    """Get investor's position in a fund."""
    # TODO: Integrate with Solana RPC - fetch from InvestorPosition PDA

    fund = MOCK_FUNDS.get(fund_id)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")

    # Mock position data
    return InvestorPositionResponse(
        fund_id=fund_id,
        investor=investor,
        shares=0.0,  # TODO: Fetch from chain
        last_nav=fund["nav"],
        cumulative_fees=0.0,
        data_source="mock",  # Solana RPC not yet integrated
    )


# ============================================================================
# Health Check
# ============================================================================

@router.get("/health")
async def health_check():
    """Check if factory router is healthy."""
    return {
        "status": "healthy",
        "program_id": "FundFactory1111111111111111111111111111111",
        "cluster": "devnet",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_source": "mock",  # Solana RPC not yet integrated
    }
