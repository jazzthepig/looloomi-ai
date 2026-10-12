"""策略自选拼组合 + 规模容量(Jazz 10-12,S-543 / S-544)。

- GET /api/v1/portfolio/books?mode=forward|replay   可选账本(层、来源、是否可用、记录区间)
- GET /api/v1/portfolio/combine?books=a:0.6,b:0.4&mode=forward|replay   组合的风险与收益来源
- GET /api/v1/fund/capacity   当下规模与设计规模下的容量(每个名字、每本账)
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter()
_logger = logging.getLogger(__name__)
_CACHE: dict[str, tuple[float, Any]] = {}
_TTL_S = 900

READING = ("Paper records and point-in-time replays, not live-traded P&L. The combined figures describe what the "
           "selected books did over the shown window; they are not forecasts and not investment advice. Returns are "
           "annualised only over a full year of shared record; shorter windows show the period return.")


async def _basis(mode: str):
    key = f"basis:{mode}"
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _TTL_S:
        return hit[1]
    from src.data.accounting.combine import load_basis
    val = await load_basis(mode)
    _CACHE[key] = (time.time(), val)
    return val


def _mode(mode: str) -> str:
    if mode not in ("forward", "replay"):
        raise HTTPException(status_code=400, detail="mode must be 'forward' or 'replay'")
    return mode


@router.get("/api/v1/portfolio/books")
async def portfolio_books(mode: str = Query("forward"), response: Response = None):
    """Books that can be combined, with their layer (① beta / ② beta+ / ③ multiplier / ④ alpha / event) and record."""
    mode = _mode(mode)
    if response:
        response.headers["Cache-Control"] = "public, max-age=600"
    try:
        _navs, _layers, info = await _basis(mode)
    except Exception:
        _logger.exception("[PORTFOLIO] basis read failed")
        raise HTTPException(status_code=502, detail="book records unreadable — not the same as no records")
    return {"mode": mode, "books": list(info.values()), "reading": READING}


@router.get("/api/v1/portfolio/combine")
async def portfolio_combine(books: str = Query(..., description="book:weight,… e.g. core_cap:0.6,causal_paper:0.4"),
                            mode: str = Query("forward"), response: Response = None):
    """Combine books at fixed weights (rebalanced daily; weights below 100% leave cash). Returns the portfolio's
    return, volatility, drawdown, each book's return and risk contribution, return by layer, correlation, and the
    split against holding the core (beta × core + residual)."""
    from src.data.accounting.combine import combine, parse_weights
    mode = _mode(mode)
    w = parse_weights(books)
    if not w:
        raise HTTPException(status_code=400, detail="no valid book:weight pairs")
    try:
        navs, layers, info = await _basis(mode)
    except Exception:
        _logger.exception("[PORTFOLIO] basis read failed")
        raise HTTPException(status_code=502, detail="book records unreadable — not the same as no records")
    unknown = [b for b in w if b not in info]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown books: {unknown}")
    unavailable = [b for b in w if not info[b].get("available")]
    if unavailable:
        raise HTTPException(status_code=400, detail={"unavailable_in_this_basis": unavailable,
                                                     "notes": {b: info[b].get("note") for b in unavailable}})
    out = combine(navs, w, layers, core=navs.get("core_cap"))
    if response:
        response.headers["Cache-Control"] = "public, max-age=600"
    out.update({"mode": mode, "selected": {b: info[b] for b in w}, "reading": READING})
    return out


@router.get("/api/v1/fund/capacity")
async def fund_capacity(response: Response = None):
    """Capacity at the current target AUM and at the design AUM (sized now so nothing has to be re-engineered on the
    way): for each asset and each weighted book, days to build a full position and the largest AUM that builds within
    the allowed days. Also the fee structure."""
    hit = _CACHE.get("capacity")
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    from src.api.contracts.fund import FEES
    from src.data.accounting.capacity import report
    try:
        out = await report()
    except Exception:
        _logger.exception("[CAPACITY] report failed")
        raise HTTPException(status_code=502, detail="capacity inputs unreadable — not the same as unlimited capacity")
    out["fees"] = FEES
    _CACHE["capacity"] = (time.time(), out)
    if response:
        response.headers["Cache-Control"] = "public, max-age=1800"
    return out
