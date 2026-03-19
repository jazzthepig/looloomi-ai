"""
On-chain router — wallet analysis, address info, token transfers
Endpoints: /api/v1/onchain/*
"""
from fastapi import APIRouter
from datetime import datetime

from data.market.data_layer import (
    get_wallet_portfolio, get_wallet_defi_positions,
    get_eth_balance, get_eth_transactions, get_token_transfers,
)

router = APIRouter()


@router.get("/api/v1/onchain/wallet/{address}")
async def analyze_wallet(address: str, chain: str = "eth"):
    return await get_wallet_portfolio(address, chain)


@router.get("/api/v1/onchain/wallet/{address}/defi")
async def wallet_defi(address: str, chain: str = "eth"):
    return await get_wallet_defi_positions(address, chain)


@router.get("/api/v1/onchain/address/{address}")
async def address_info(address: str):
    """ETH address info: balance + recent transactions."""
    import asyncio
    balance, txs = await asyncio.gather(get_eth_balance(address), get_eth_transactions(address))
    return {
        "address":      address,
        "balance":      balance,
        "transactions": txs.get("result", [])[:10] if "result" in txs else [],
        "timestamp":    datetime.now().isoformat(),
    }


@router.get("/api/v1/onchain/address/{address}/tokens")
async def address_tokens(address: str):
    return await get_token_transfers(address)
