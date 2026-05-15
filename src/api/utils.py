"""
Shared API utilities — validators, constants, and safe helpers.
Imported by all routers to avoid duplication.
"""
import re
from fastapi import HTTPException

# ── Symbol / Asset Validation ────────────────────────────────────────────────────
# Used by market.py, vault.py, and any router validating comma-separated symbols.
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}(,[A-Z0-9]{2,12})*$")

def validate_symbols(symbols: str) -> list[str]:
    """
    Validate a comma-separated symbol string (e.g. "BTC,ETH,SOL").
    Returns list of uppercase stripped symbols, or raises HTTPException 400.
    """
    if not _SYMBOL_RE.match(symbols.upper()):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    return [s.strip().upper() for s in symbols.upper().split(",")]


# ── Safe async wrapper ──────────────────────────────────────────────────────────
async def safe_await(coro):
    """Fire-and-forget async call; returns None on any exception."""
    try:
        return await coro
    except Exception:
        return None