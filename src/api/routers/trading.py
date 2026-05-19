"""
Trading Execution Router — CometCloud AI
=========================================
Paper trading engine + signal queue + data mining endpoints.

Modes:
  PAPER  — simulates fills against live CoinGecko prices (default, Railway-safe)
  SIGNAL — queues trade signals for Mac Mini Freqtrade pickup
  LIVE   — direct CCXT execution (requires exchange API keys, future)

Endpoints:
  POST /api/v1/trading/order          — submit paper order (CIS-gated)
  GET  /api/v1/trading/positions       — open positions with live P&L
  DELETE /api/v1/trading/positions/{id} — close position
  GET  /api/v1/trading/metrics         — portfolio performance metrics
  GET  /api/v1/trading/signal-queue    — Mac Mini polls pending signals
  DELETE /api/v1/trading/signal-queue/{id} — Mac Mini acks executed signal
  GET  /api/v1/trading/mine            — alpha mining (grade_alpha | pillar_fitness | signal_accuracy)

Risk controls:
  - CIS gate: min score by regime (Tightening=52, Risk-Off=62, else=48)
  - Max position size: 10% of portfolio per symbol
  - Max portfolio drawdown: 15% before halting new entries
  - Max open positions: 10
"""

import os
import uuid
import asyncio
import logging
import httpx
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel, Field

from src.api.store import redis_set_key, redis_get_key

_logger = logging.getLogger(__name__)
router  = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────

_INTERNAL_TOKEN    = os.environ.get("INTERNAL_TOKEN", "")
_UPSTASH_URL       = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_UPSTASH_TOKEN     = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_COINGECKO_KEY     = os.environ.get("COINGECKO_API_KEY", "")

_CG_BASE           = "https://api.coingecko.com/api/v3"
_CG_PRO            = "https://pro-api.coingecko.com/api/v3"
_CG_HEADERS        = {"x-cg-pro-api-key": _COINGECKO_KEY} if _COINGECKO_KEY else {}

_REDIS_POSITIONS   = "trading:positions"       # {order_id: position}
_REDIS_SIG_QUEUE   = "trading:signal_queue"    # [signal]
_REDIS_METRICS     = "trading:metrics"         # performance snapshot
_REDIS_ORDERS      = "trading:orders"          # full order log

# Starting paper portfolio balance (USD)
_PAPER_BALANCE_KEY = "trading:paper_balance"
_DEFAULT_BALANCE   = 10_000.0

# Risk controls
_CIS_GATE_BY_REGIME = {
    "Tightening":  52,
    "Risk-Off":    62,
    "Stagflation": 65,
    "Goldilocks":  45,
    "Risk-On":     48,
    "Easing":      48,
}
_CIS_GATE_DEFAULT  = 50
_MAX_POSITION_PCT  = 0.10   # 10% of portfolio per position
_MAX_DRAWDOWN_PCT  = 0.15   # halt new entries if portfolio down 15%
_MAX_OPEN          = 10     # max concurrent positions

# Symbol → CoinGecko ID mapping (subset of CIS universe, liquid)
_SYM_TO_CG: dict[str, str] = {
    "BTC":   "bitcoin",         "ETH":   "ethereum",
    "SOL":   "solana",          "BNB":   "binancecoin",
    "XRP":   "ripple",          "ADA":   "cardano",
    "AVAX":  "avalanche-2",     "DOT":   "polkadot",
    "LINK":  "chainlink",       "UNI":   "uniswap",
    "AAVE":  "aave",            "MKR":   "maker",
    "SNX":   "synthetix-network-token",
    "CRV":   "curve-dao-token", "COMP":  "compound-governance-token",
    "LDO":   "lido-dao",        "ARB":   "arbitrum",
    "OP":    "optimism",        "MATIC":  "polygon-ecosystem-token",
    "POL":   "polygon-ecosystem-token",
    "STX":   "blockstack",      "NEAR":  "near",
    "APT":   "aptos",           "SUI":   "sui",
    "INJ":   "injective-protocol",
    "PENDLE":"pendle",           "ONDO":  "ondo-finance",
    "JTO":   "jito-governance-token",
    "WLD":   "worldcoin-wld",   "FET":   "fetch-ai",
    "RENDER":"render-token",    "TAO":   "bittensor",
    "LTC":   "litecoin",        "DOGE":  "dogecoin",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Redis helpers (scoped to trading namespace) ────────────────────────────────

async def _rget(key: str):
    return await redis_get_key(key)

async def _rset(key: str, val, ttl: int = 86400 * 7):
    return await redis_set_key(key, val, ttl=ttl)


# ── Live price fetch (CoinGecko) ──────────────────────────────────────────────

async def _fetch_price(symbol: str) -> float | None:
    """Fetch current USD price from CoinGecko. Returns None on failure."""
    cg_id = _SYM_TO_CG.get(symbol.upper())
    if not cg_id:
        return None
    base = _CG_PRO if _COINGECKO_KEY else _CG_BASE
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            r = await cl.get(
                f"{base}/simple/price",
                params={"ids": cg_id, "vs_currencies": "usd"},
                headers=_CG_HEADERS,
            )
            data = r.json()
            return float(data[cg_id]["usd"])
    except Exception:
        return None


async def _fetch_prices_batch(symbols: list[str]) -> dict[str, float]:
    """Batch price fetch for multiple symbols."""
    cg_ids = {sym: _SYM_TO_CG.get(sym.upper()) for sym in symbols}
    valid_ids = {sym: cg_id for sym, cg_id in cg_ids.items() if cg_id}
    if not valid_ids:
        return {}
    base = _CG_PRO if _COINGECKO_KEY else _CG_BASE
    try:
        async with httpx.AsyncClient(timeout=10) as cl:
            r = await cl.get(
                f"{base}/simple/price",
                params={"ids": ",".join(set(valid_ids.values())), "vs_currencies": "usd"},
                headers=_CG_HEADERS,
            )
            data = r.json()
        result: dict[str, float] = {}
        id_to_syms: dict[str, list[str]] = {}
        for sym, cg_id in valid_ids.items():
            id_to_syms.setdefault(cg_id, []).append(sym)
        for cg_id, price_data in data.items():
            price = float(price_data.get("usd", 0) or 0)
            if price > 0:
                for sym in id_to_syms.get(cg_id, []):
                    result[sym] = price
        return result
    except Exception:
        return {}


# ── Portfolio state helpers ────────────────────────────────────────────────────

async def _get_positions() -> dict[str, dict]:
    """Returns {order_id: position_dict}."""
    raw = await _rget(_REDIS_POSITIONS)
    if not isinstance(raw, dict):
        return {}
    return raw

async def _save_positions(positions: dict):
    await _rset(_REDIS_POSITIONS, positions)

async def _get_balance() -> float:
    raw = await _rget(_PAPER_BALANCE_KEY)
    if isinstance(raw, dict):
        return float(raw.get("balance", _DEFAULT_BALANCE))
    return _DEFAULT_BALANCE

async def _save_balance(balance: float):
    await _rset(_PAPER_BALANCE_KEY, {"balance": balance, "updated": _now()})

async def _get_signal_queue() -> list:
    raw = await _rget(_REDIS_SIG_QUEUE)
    return raw if isinstance(raw, list) else []

async def _save_signal_queue(queue: list):
    await _rset(_REDIS_SIG_QUEUE, queue, ttl=3600 * 6)


# ── CIS gate check ─────────────────────────────────────────────────────────────

async def _get_cis_for_symbol(symbol: str) -> tuple[float, str, str, dict]:
    """Returns (cis_score, grade, macro_regime, full_asset_dict) for a symbol.

    Returns the full asset dict so callers can snapshot pillar scores at entry
    for alpha mining (pillar_fitness Pearson correlation via /api/v1/trading/mine).
    """
    try:
        from src.data.cis.cis_provider import calculate_cis_universe
        from src.api.store import redis_get_key as _rg
        # Try Redis cache first (Mac Mini T1 push, 2h TTL)
        cached = await _rg("cis:local_scores")
        if cached and isinstance(cached, dict):
            assets = cached.get("assets") or cached.get("universe", [])
            for a in assets:
                sym = (a.get("symbol") or a.get("asset_id") or "").upper()
                if sym == symbol.upper():
                    score = a.get("cis_score") or a.get("total_score") or a.get("score", 0) or 0
                    return float(score), a.get("grade", "?"), cached.get("macro_regime", "Unknown"), a
        # Fallback: compute via Railway CIS engine
        universe_data = await calculate_cis_universe()
        assets = universe_data.get("assets") or universe_data.get("universe", [])
        regime = universe_data.get("macro_regime", "Unknown")
        for a in assets:
            sym = (a.get("symbol") or a.get("asset_id") or "").upper()
            if sym == symbol.upper():
                score = a.get("cis_score") or a.get("total_score") or a.get("score", 0) or 0
                return float(score), a.get("grade", "?"), regime, a
    except Exception as e:
        _logger.warning(f"[TRADING] CIS lookup failed for {symbol}: {e}")
    return 0.0, "?", "Unknown", {}


# ── Risk validation ────────────────────────────────────────────────────────────

async def _validate_risk(
    symbol: str,
    size_usd: float,
    cis_score: float,
    macro_regime: str,
    positions: dict,
    balance: float,
) -> tuple[bool, str]:
    """
    Returns (ok, rejection_reason).
    Validates: CIS gate, position count, position size, drawdown.
    """
    # CIS gate
    gate = _CIS_GATE_BY_REGIME.get(macro_regime, _CIS_GATE_DEFAULT)
    if cis_score < gate:
        return False, f"CIS gate: score {cis_score:.1f} < {gate} required in {macro_regime} regime"

    # Max open positions
    open_syms = {p["symbol"] for p in positions.values() if p.get("status") == "open"}
    if len(open_syms) >= _MAX_OPEN and symbol.upper() not in open_syms:
        return False, f"Max open positions ({_MAX_OPEN}) reached"

    # Position size limit
    portfolio_value = balance + sum(
        p.get("current_value_usd", p.get("size_usd", 0))
        for p in positions.values()
        if p.get("status") == "open"
    )
    if size_usd > portfolio_value * _MAX_POSITION_PCT:
        max_allowed = round(portfolio_value * _MAX_POSITION_PCT, 2)
        return False, f"Position size ${size_usd} exceeds max {_MAX_POSITION_PCT*100:.0f}% (${max_allowed})"

    # Drawdown check
    if portfolio_value < _DEFAULT_BALANCE * (1 - _MAX_DRAWDOWN_PCT):
        return False, f"Portfolio drawdown > {_MAX_DRAWDOWN_PCT*100:.0f}% — new entries halted"

    # Duplicate check (already long this asset)
    for pos in positions.values():
        if pos.get("symbol") == symbol.upper() and pos.get("status") == "open":
            return False, f"Already have an open position in {symbol}"

    return True, ""


# ── Schemas ────────────────────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    symbol: str = Field(..., description="Asset symbol e.g. BTC, ETH, SOL")
    side: Literal["LONG", "SHORT"] = Field("LONG", description="Trade direction")
    size_usd: float = Field(..., gt=10, le=100_000, description="Position size in USD")
    stop_loss_pct: float = Field(0.04, ge=0.005, le=0.30, description="Stop loss % (e.g. 0.04 = 4%)")
    take_profit_pct: float = Field(0.10, ge=0.01, le=2.0, description="Take profit % (e.g. 0.10 = 10%)")
    mode: Literal["PAPER", "SIGNAL"] = Field("PAPER", description="PAPER=simulate locally, SIGNAL=queue for Freqtrade")
    note: str = Field("", max_length=200, description="Optional agent reasoning note")


class CloseRequest(BaseModel):
    reason: str = Field("agent_close", description="Exit reason")


# ── POST /api/v1/trading/order ─────────────────────────────────────────────────

@router.post("/api/v1/trading/order")
async def submit_order(req: OrderRequest):
    """
    Submit a paper trade order. CIS-gated, risk-controlled.

    Returns immediately with order_id and fill details.
    All signals use positioning language per HK SFC compliance.
    """
    symbol = req.symbol.upper()

    # Fetch CIS + live price in parallel
    cis_result, price = await asyncio.gather(
        _get_cis_for_symbol(symbol),
        _fetch_price(symbol),
    )
    if isinstance(cis_result, tuple) and len(cis_result) == 4:
        cis_score, grade, regime, _asset = cis_result
    else:
        cis_score, grade, regime, _asset = 0.0, "?", "Unknown", {}

    if not price:
        raise HTTPException(status_code=422, detail=f"Cannot fetch live price for {symbol}. Check symbol or CoinGecko ID mapping.")

    # Load portfolio state
    positions, balance = await asyncio.gather(
        _get_positions(),
        _get_balance(),
    )

    # Risk validation
    ok, reason = await _validate_risk(symbol, req.size_usd, cis_score, regime, positions, balance)
    if not ok:
        return {
            "status": "rejected",
            "reason": reason,
            "symbol": symbol,
            "cis_score": round(cis_score, 1),
            "grade": grade,
            "macro_regime": regime,
        }

    # Paper fill
    order_id  = uuid.uuid4().hex[:12]
    qty       = req.size_usd / price
    filled_at = price

    # ── Volatility-adjusted SL/TP ─────────────────────────────────────────────
    # Use asset's realized 30d volatility if available, otherwise fall back to
    # caller-supplied pct (default 4% SL / 10% TP from the request schema).
    # Normalize units: crypto vol = % (e.g. 3.5), TradFi = decimal (e.g. 0.03).
    vol_raw = float(_asset.get("volatility_30d") or 0)
    vol_30d = vol_raw / 100 if vol_raw > 0.5 else vol_raw   # % → decimal if >0.5
    if vol_30d > 0.005:
        # Risk 1.5× daily vol for SL, target 2.5× for TP (reward:risk ≈ 1.67)
        sl_pct_auto = round(max(0.02, min(0.15, 1.5 * vol_30d)), 4)
        tp_pct_auto = round(max(0.05, min(0.50, 2.5 * vol_30d)), 4)
        # Only override if caller left defaults unchanged (avoid overriding intentional sizing)
        final_sl = sl_pct_auto if req.stop_loss_pct == 0.04 else req.stop_loss_pct
        final_tp = tp_pct_auto if req.take_profit_pct == 0.10 else req.take_profit_pct
    else:
        final_sl = req.stop_loss_pct
        final_tp = req.take_profit_pct

    sl_price = filled_at * (1 - final_sl) if req.side == "LONG" else filled_at * (1 + final_sl)
    tp_price = filled_at * (1 + final_tp) if req.side == "LONG" else filled_at * (1 - final_tp)

    # ── Snapshot pillar scores at entry (required for mine_alpha pillar_fitness) ──
    _pillars = _asset.get("pillars") or {}
    _p = lambda k: round(float(_pillars.get(k) or 0), 1)

    position = {
        "order_id":         order_id,
        "symbol":           symbol,
        "side":             req.side,
        "size_usd":         req.size_usd,
        "qty":              round(qty, 8),
        "entry_price":      filled_at,
        "stop_loss":        round(sl_price, 6),
        "take_profit":      round(tp_price, 6),
        "stop_loss_pct":    final_sl,
        "take_profit_pct":  final_tp,
        "current_price":    filled_at,
        "current_value_usd":req.size_usd,
        "unrealized_pnl":   0.0,
        "unrealized_pct":   0.0,
        "cis_score":        round(cis_score, 1),
        "cis_grade":        grade,
        "cis_signal":       _asset.get("signal", "NEUTRAL"),  # for _mine_signal_accuracy
        "pillar_f_at_entry": _p("F"),
        "pillar_m_at_entry": _p("M"),
        "pillar_o_at_entry": _p("O") or _p("R"),  # O (risk-adjusted) may be keyed "R" in T2
        "pillar_s_at_entry": _p("S"),
        "pillar_a_at_entry": _p("A"),
        "las_at_entry":     round(float(_asset.get("las") or 0), 1),
        "confidence_at_entry": round(float(_asset.get("confidence") or 0), 3),
        "macro_regime":     regime,
        "mode":             req.mode,
        "note":             req.note,
        "status":           "open",
        "opened_at":        _now(),
        "updated_at":       _now(),
    }

    # Deduct from paper balance
    if req.mode == "PAPER":
        new_balance = balance - req.size_usd
        await _save_balance(new_balance)

    # Persist position
    positions[order_id] = position
    await _save_positions(positions)

    # Queue signal for Mac Mini Freqtrade if requested
    if req.mode == "SIGNAL":
        queue = await _get_signal_queue()
        queue.insert(0, {
            "signal_id":        order_id,
            "symbol":           symbol,
            "side":             req.side,
            "size_usd":         req.size_usd,
            "stop_loss_pct":    req.stop_loss_pct,
            "take_profit_pct":  req.take_profit_pct,
            "cis_score":        round(cis_score, 1),
            "grade":            grade,
            "macro_regime":     regime,
            "created_at":       _now(),
            "status":           "pending",
        })
        await _save_signal_queue(queue[:50])  # keep last 50

    _logger.info(f"[TRADING] {req.mode} {req.side} {symbol} ${req.size_usd:.0f} @ {filled_at:.4f} | CIS={cis_score:.1f} {grade}")

    return {
        "status":       "filled",
        "order_id":     order_id,
        "symbol":       symbol,
        "side":         req.side,
        "qty":          round(qty, 6),
        "fill_price":   filled_at,
        "size_usd":     req.size_usd,
        "stop_loss":    round(sl_price, 6),
        "take_profit":  round(tp_price, 6),
        "cis_score":    round(cis_score, 1),
        "grade":        grade,
        "macro_regime": regime,
        "mode":         req.mode,
        "opened_at":    position["opened_at"],
        "compliance":   "CometCloud positions use OUTPERFORM/NEUTRAL language. Not investment advice.",
    }


# ── GET /api/v1/trading/positions ─────────────────────────────────────────────

@router.get("/api/v1/trading/positions")
async def get_positions():
    """
    Open positions with live P&L. Prices updated from CoinGecko batch call.
    """
    positions = await _get_positions()
    open_positions = {oid: p for oid, p in positions.items() if p.get("status") == "open"}

    if not open_positions:
        balance = await _get_balance()
        return {"positions": [], "count": 0, "cash_usd": round(balance, 2), "portfolio_usd": round(balance, 2)}

    # Batch price update
    symbols = list({p["symbol"] for p in open_positions.values()})
    prices  = await _fetch_prices_batch(symbols)

    updated_positions = []
    total_value = 0.0
    total_pnl   = 0.0

    for oid, pos in open_positions.items():
        sym   = pos["symbol"]
        price = prices.get(sym, pos["entry_price"])
        qty   = pos.get("qty", 0)
        side  = pos.get("side", "LONG")

        current_value = qty * price
        if side == "LONG":
            pnl_abs = (price - pos["entry_price"]) * qty
            pnl_pct = (price / pos["entry_price"] - 1) * 100
        else:
            pnl_abs = (pos["entry_price"] - price) * qty
            pnl_pct = (pos["entry_price"] / price - 1) * 100 if price > 0 else 0

        pos["current_price"]     = round(price, 6)
        pos["current_value_usd"] = round(current_value, 2)
        pos["unrealized_pnl"]    = round(pnl_abs, 2)
        pos["unrealized_pct"]    = round(pnl_pct, 3)
        pos["updated_at"]        = _now()

        # Check SL/TP triggers
        if side == "LONG":
            if price <= pos["stop_loss"]:
                pos["sl_triggered"] = True
            elif price >= pos["take_profit"]:
                pos["tp_triggered"] = True
        else:
            if price >= pos["stop_loss"]:
                pos["sl_triggered"] = True
            elif price <= pos["take_profit"]:
                pos["tp_triggered"] = True

        total_value += current_value
        total_pnl   += pnl_abs
        updated_positions.append(pos)

    # Persist updated prices
    for pos in updated_positions:
        positions[pos["order_id"]] = pos
    await _save_positions(positions)

    balance = await _get_balance()
    portfolio_usd = balance + total_value

    return {
        "positions":     sorted(updated_positions, key=lambda x: x["opened_at"], reverse=True),
        "count":         len(updated_positions),
        "cash_usd":      round(balance, 2),
        "positions_usd": round(total_value, 2),
        "portfolio_usd": round(portfolio_usd, 2),
        "unrealized_pnl":round(total_pnl, 2),
        "unrealized_pct":round(total_pnl / _DEFAULT_BALANCE * 100, 3) if _DEFAULT_BALANCE else 0,
        "updated_at":    _now(),
    }


# ── DELETE /api/v1/trading/positions/{order_id} ────────────────────────────────

@router.delete("/api/v1/trading/positions/{order_id}")
async def close_position(order_id: str, req: CloseRequest = None):
    """
    Close a paper position at current market price. Records realized P&L.
    """
    positions = await _get_positions()
    pos = positions.get(order_id)
    if not pos:
        raise HTTPException(status_code=404, detail=f"Position {order_id} not found")
    if pos.get("status") != "open":
        raise HTTPException(status_code=409, detail=f"Position {order_id} already closed")

    sym   = pos["symbol"]
    price = await _fetch_price(sym)
    if not price:
        price = pos["current_price"] or pos["entry_price"]

    qty  = pos.get("qty", 0)
    side = pos.get("side", "LONG")

    if side == "LONG":
        pnl_abs = (price - pos["entry_price"]) * qty
        pnl_pct = (price / pos["entry_price"] - 1) * 100
    else:
        pnl_abs = (pos["entry_price"] - price) * qty
        pnl_pct = (pos["entry_price"] / price - 1) * 100 if price > 0 else 0

    exit_value = qty * price
    pos.update({
        "status":       "closed",
        "exit_price":   round(price, 6),
        "exit_value_usd": round(exit_value, 2),
        "realized_pnl": round(pnl_abs, 2),
        "realized_pct": round(pnl_pct, 3),
        "exit_reason":  (req.reason if req else "manual"),
        "closed_at":    _now(),
        "updated_at":   _now(),
    })

    positions[order_id] = pos
    await _save_positions(positions)

    # Return cash to paper balance
    balance = await _get_balance()
    await _save_balance(balance + exit_value)

    _logger.info(f"[TRADING] CLOSE {sym} @ {price:.4f} | P&L: {pnl_pct:+.2f}% (${pnl_abs:+.2f})")

    # ── Simons IC Loop — auto-mine after every 5th closed trade ──────────────
    all_closed = [p for p in positions.values() if p.get("status") == "closed"]
    n_closed   = len(all_closed)
    if n_closed >= 5 and (n_closed == 5 or n_closed % 5 == 0):
        asyncio.create_task(_auto_mine_ic(all_closed, n_closed))

    return {
        "status":       "closed",
        "order_id":     order_id,
        "symbol":       sym,
        "exit_price":   round(price, 6),
        "realized_pnl": round(pnl_abs, 2),
        "realized_pct": round(pnl_pct, 3),
        "exit_reason":  pos["exit_reason"],
        "held_seconds": (
            datetime.fromisoformat(pos["closed_at"].replace("Z", "+00:00")) -
            datetime.fromisoformat(pos["opened_at"].replace("Z", "+00:00"))
        ).total_seconds() if pos.get("opened_at") else None,
    }


# ── Simons IC Loop — auto-mine background task ───────────────────────────────

async def _auto_mine_ic(closed: list, n_closed: int) -> None:
    """
    Background task: runs pillar fitness correlation and writes IC multipliers to Redis.
    Called automatically every 5th trade close. Never blocks the close response.

    Flow: close_position() → create_task(_auto_mine_ic) →
          _mine_pillar_fitness(closed) → update_from_pillar_fitness() →
          cis:factor_performance (Redis, 7d TTL) →
          _refresh_ic_multipliers() reads on next CIS scoring run →
          calculate_total_score(ic_mult=...) Layer 3 applied.
    """
    _logger.info(f"[IC-LOOP] Auto-mine triggered — {n_closed} closed trades")
    try:
        # 1. Bust stale mine cache (all hour windows for pillar_fitness)
        for hours in [24, 72, 168, 720]:
            await _rset(f"trading:mine:pillar_fitness:{hours}", json.dumps({"_busted": True}), ttl=1)

        # 2. Run Pearson IC per pillar against ALL closed trades (max sample)
        result  = _mine_pillar_fitness(closed)
        corrs   = result.get("pillar_correlations", {})
        enriched = {
            k: {"correlation": v, "sample_size": n_closed}
            for k, v in corrs.items() if v is not None
        }
        if not enriched:
            _logger.info("[IC-LOOP] Insufficient pillar snapshot data — need ≥5 trades with pillar_X_at_entry fields")
            return

        # 3. Persist to cis:factor_performance via performance.py
        from src.data.factors.performance import update_from_pillar_fitness
        update_from_pillar_fitness(enriched, n_closed)

        _logger.info(f"[IC-LOOP] IC update complete — correlations: {corrs}")
    except Exception as exc:
        _logger.warning(f"[IC-LOOP] Auto-mine failed: {exc}")


# ── GET /api/v1/trading/loop-state ────────────────────────────────────────────

_REGIME_GATE = {
    "RISK_ON": 45, "GOLDILOCKS": 45, "EASING": 48,
    "TIGHTENING": 52, "RISK_OFF": 58, "STAGFLATION": 60,
}


@router.get("/api/v1/trading/loop-state")
async def get_loop_state():
    """
    Simons IC feedback loop — unified state for the analysis/trade cycle.

    Returns:
      loop_active       — bool: mine has run + ≥5 closed trades
      closed_trades     — total closed paper trades
      open_positions    — current open count
      ic_multipliers    — {F,M,O,S,A} → current weight multiplier (1.0 = neutral)
      mine_last_run     — unix timestamp of last mine run (or null)
      mine_periods      — how many mine runs completed
      next_mine_at      — trades until next auto-mine trigger
      regime            — current macro regime from CIS
      gate_threshold    — min CIS score for trade entry in current regime
    """
    positions_data, factor_raw, cis_raw = await asyncio.gather(
        _get_positions(),
        _rget("cis:factor_performance"),
        _rget("cis:local_scores"),
    )

    closed = [p for p in positions_data.values() if p.get("status") == "closed"]
    open_  = [p for p in positions_data.values() if p.get("status") == "open"]
    n_closed = len(closed)

    # ── Parse factor performance ──────────────────────────────────────────────
    fp   = json.loads(factor_raw) if factor_raw else {}
    meta = fp.get("_meta", {})

    # Compute IC multiplier per pillar (mirrors _refresh_ic_multipliers in cis_provider.py)
    ic_mult: dict[str, float] = {}
    for pillar in ("F", "M", "O", "S", "A"):
        factors = [
            v for k, v in fp.items()
            if k != "_meta" and isinstance(v, dict) and (v.get("pillar") or "").upper() == pillar
        ]
        active = [
            f for f in factors
            if f.get("pearson_r") is not None
            and abs(f.get("pearson_r", 0)) > 0.10
            and (f.get("sample_size") or 0) >= 10
        ]
        if active:
            mean_r = sum(f["pearson_r"] for f in active) / len(active)
            ic_mult[pillar] = round(1.0 + max(-0.30, min(0.30, mean_r * 2.5)), 4)
        else:
            ic_mult[pillar] = 1.0

    # ── Parse current regime ──────────────────────────────────────────────────
    regime = "UNKNOWN"
    if cis_raw:
        try:
            cis_data = json.loads(cis_raw)
            regime = (
                cis_data.get("macro", {}).get("regime")
                or cis_data.get("macro_regime")
                or "UNKNOWN"
            )
        except Exception:
            pass

    gate_threshold = _REGIME_GATE.get(regime, 50)
    loop_active    = n_closed >= 5 and bool(meta.get("last_run"))
    next_mine_at   = max(0, 5 - n_closed) if n_closed < 5 else (5 - (n_closed % 5)) % 5 or 5

    return {
        "loop_active":      loop_active,
        "closed_trades":    n_closed,
        "open_positions":   len(open_),
        "ic_multipliers":   ic_mult,
        "mine_last_run":    meta.get("last_run"),
        "mine_periods":     meta.get("periods_computed", 0),
        "mine_total_trades":meta.get("total_trades_analysed", 0),
        "regime":           regime,
        "gate_threshold":   gate_threshold,
        "next_mine_at":     next_mine_at,
        "auto_mine_every":  5,
        "active_factors":   len([v for k, v in fp.items() if k != "_meta" and isinstance(v, dict) and v.get("status") == "active"]),
    }


# ── GET /api/v1/trading/metrics ────────────────────────────────────────────────

@router.get("/api/v1/trading/metrics")
async def get_metrics():
    """
    Realized trade performance: win rate, avg return, total P&L, Sharpe approximation.
    """
    positions = await _get_positions()
    balance   = await _get_balance()

    closed = [p for p in positions.values() if p.get("status") == "closed"]
    open_  = [p for p in positions.values() if p.get("status") == "open"]

    total_trades = len(closed)
    if total_trades == 0:
        open_count = len(open_)
        open_value = sum(p.get("current_value_usd", p.get("size_usd", 0)) for p in open_)
        return {
            "total_trades":     0,
            "win_rate":         None,
            "avg_return_pct":   None,
            "total_pnl_usd":    0,
            "total_pnl_pct":    0,
            "best_trade":       None,
            "worst_trade":      None,
            "cash_usd":         round(balance, 2),
            "open_positions":   open_count,
            "open_value_usd":   round(open_value, 2),
            "portfolio_usd":    round(balance + open_value, 2),
            "starting_balance": _DEFAULT_BALANCE,
        }

    returns = [p["realized_pct"] for p in closed if p.get("realized_pct") is not None]
    pnls    = [p["realized_pnl"] for p in closed if p.get("realized_pnl") is not None]
    wins    = [r for r in returns if r > 0]

    # Simple Sharpe approximation (daily returns, annualized)
    import statistics
    avg_ret = statistics.mean(returns) if returns else 0
    std_ret = statistics.stdev(returns) if len(returns) > 1 else 0
    sharpe  = round(avg_ret / std_ret * (252 ** 0.5) / 100, 3) if std_ret > 0 else None  # rough annualized

    best  = max(closed, key=lambda p: p.get("realized_pct", -999))
    worst = min(closed, key=lambda p: p.get("realized_pct", 999))

    open_count = len(open_)
    open_value = sum(p.get("current_value_usd", p.get("size_usd", 0)) for p in open_)
    total_pnl  = sum(pnls)

    return {
        "total_trades":   total_trades,
        "win_rate":       round(len(wins) / len(returns) * 100, 1) if returns else None,
        "avg_return_pct": round(avg_ret, 3),
        "total_pnl_usd":  round(total_pnl, 2),
        "total_pnl_pct":  round(total_pnl / _DEFAULT_BALANCE * 100, 3),
        "sharpe_approx":  sharpe,
        "best_trade":     {"symbol": best["symbol"], "pnl_pct": round(best.get("realized_pct",0),2), "pnl_usd": round(best.get("realized_pnl",0),2)},
        "worst_trade":    {"symbol": worst["symbol"], "pnl_pct": round(worst.get("realized_pct",0),2), "pnl_usd": round(worst.get("realized_pnl",0),2)},
        "by_grade":       _group_by(closed, "cis_grade", "realized_pct"),
        "by_regime":      _group_by(closed, "macro_regime", "realized_pct"),
        "cash_usd":       round(balance, 2),
        "open_positions": open_count,
        "open_value_usd": round(open_value, 2),
        "portfolio_usd":  round(balance + open_value + total_pnl, 2),
        "starting_balance": _DEFAULT_BALANCE,
    }


def _group_by(trades: list, key: str, metric: str) -> dict:
    """Group trade results by a key, compute avg metric."""
    groups: dict[str, list] = {}
    for t in trades:
        k = t.get(key, "Unknown") or "Unknown"
        groups.setdefault(k, []).append(t.get(metric, 0) or 0)
    return {k: round(sum(vs)/len(vs), 3) for k, vs in groups.items() if vs}


# ── Signal Queue (Mac Mini pickup) ─────────────────────────────────────────────

@router.get("/api/v1/trading/signal-queue")
async def get_signal_queue(x_internal_token: str = Header(None)):
    """
    Mac Mini polls this endpoint every 30s to pick up pending trade signals.
    Returns signals in SIGNAL mode that haven't been acked yet.
    Requires X-Internal-Token.
    """
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="X-Internal-Token required")
    queue = await _get_signal_queue()
    pending = [s for s in queue if s.get("status") == "pending"]
    return {"count": len(pending), "signals": pending}


@router.delete("/api/v1/trading/signal-queue/{signal_id}")
async def ack_signal(signal_id: str, x_internal_token: str = Header(None)):
    """Mac Mini acks a signal as executed. Marks it done in queue."""
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="X-Internal-Token required")
    queue = await _get_signal_queue()
    for s in queue:
        if s.get("signal_id") == signal_id:
            s["status"] = "executed"
            s["acked_at"] = _now()
    await _save_signal_queue(queue)
    return {"ok": True, "signal_id": signal_id}


# ── GET /api/v1/trading/mine ───────────────────────────────────────────────────

@router.get("/api/v1/trading/mine")
async def mine_alpha(
    type: str = Query("grade_alpha", description="grade_alpha | pillar_fitness | signal_accuracy | regime_performance"),
    hours: int = Query(168, ge=1, le=8760, description="Lookback window in hours"),
):
    """
    Data mining endpoint. Correlates CIS signals with realized trade outcomes.

    type=grade_alpha        — avg realized return by CIS grade (A+, A, B+, B, C, D, F)
    type=pillar_fitness     — which pillars (F/M/O/S/A) predict outcomes by regime
    type=signal_accuracy    — OUTPERFORM/NEUTRAL/UNDERPERFORM vs realized
    type=regime_performance — trade performance by macro regime
    """
    cache_key = f"trading:mine:{type}:{hours}"
    cached = await _rget(cache_key)
    if cached:
        return {"source": "cache", "type": type, **cached}

    positions = await _get_positions()
    closed = [p for p in positions.values() if p.get("status") == "closed"]

    # Filter to window
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    closed = [
        p for p in closed
        if p.get("closed_at") and datetime.fromisoformat(
            p["closed_at"].replace("Z", "+00:00")
        ) >= cutoff
    ]

    if not closed:
        return {"type": type, "hours": hours, "message": "No closed trades in window yet", "data": {}}

    if type == "grade_alpha":
        result = _mine_grade_alpha(closed)
    elif type == "pillar_fitness":
        result = _mine_pillar_fitness(closed)
        # v4.3: Persist pillar fitness to factor performance DB
        try:
            from src.data.factors.performance import update_from_pillar_fitness
            pillar_corrs = result.get("pillar_correlations", {})
            # Convert {"F": 0.23, ...} → {"F": {"correlation": 0.23, "sample_size": len(closed)}}
            enriched = {k: {"correlation": v, "sample_size": len(closed)}
                        for k, v in pillar_corrs.items() if v is not None}
            update_from_pillar_fitness(enriched, len(closed))
        except Exception as _pf_err:
            _logger.debug(f"[trading] factor perf update skipped: {_pf_err}")
    elif type == "signal_accuracy":
        result = _mine_signal_accuracy(closed)
    elif type == "regime_performance":
        result = _mine_regime_performance(closed)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown mining type: {type}")

    output = {"type": type, "hours": hours, "trade_count": len(closed), **result}
    await _rset(cache_key, output, ttl=3600)
    return {"source": "computed", **output}


def _mine_grade_alpha(trades: list) -> dict:
    """Avg realized return by CIS grade at entry."""
    _GRADE_ORDER = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
    groups: dict[str, list] = {}
    for t in trades:
        g = t.get("cis_grade", "?") or "?"
        groups.setdefault(g, []).append(t.get("realized_pct", 0) or 0)
    alpha = {}
    for grade, rets in groups.items():
        alpha[grade] = {
            "avg_return_pct": round(sum(rets)/len(rets), 3),
            "win_rate_pct":   round(len([r for r in rets if r > 0]) / len(rets) * 100, 1),
            "trade_count":    len(rets),
            "total_pnl_pct":  round(sum(rets), 3),
        }
    # Sort by grade rank
    sorted_alpha = dict(sorted(alpha.items(), key=lambda x: -_GRADE_ORDER.get(x[0], 0)))
    return {"by_grade": sorted_alpha}


def _mine_signal_accuracy(trades: list) -> dict:
    """OUTPERFORM/NEUTRAL/UNDERPERFORM vs realized returns."""
    # Map CIS signals to directional expectation
    _SIG_EXPECTATION = {
        "STRONG OUTPERFORM": 1,
        "OUTPERFORM":        1,
        "NEUTRAL":           0,
        "UNDERPERFORM":     -1,
        "UNDERWEIGHT":      -1,
    }
    groups: dict[str, list] = {}
    for t in trades:
        # Derive signal from grade if not stored directly
        sig = t.get("cis_signal") or "NEUTRAL"
        groups.setdefault(sig, []).append(t.get("realized_pct", 0) or 0)
    accuracy = {}
    for sig, rets in groups.items():
        exp = _SIG_EXPECTATION.get(sig, 0)
        correct = sum(1 for r in rets if (r > 0) == (exp > 0)) if exp != 0 else 0
        accuracy[sig] = {
            "avg_return_pct": round(sum(rets)/len(rets), 3),
            "accuracy_pct":   round(correct / len(rets) * 100, 1) if exp != 0 else None,
            "trade_count":    len(rets),
        }
    return {"by_signal": accuracy}


def _mine_pillar_fitness(trades: list) -> dict:
    """
    Correlation between pillar scores and realized return.
    Requires trade records to have pillar_X_at_entry fields.
    """
    pillars = ["f", "m", "o", "s", "a"]
    correlations: dict[str, float | None] = {}
    for p in pillars:
        key = f"pillar_{p}_at_entry"
        pairs = [(t.get(key, 0) or 0, t.get("realized_pct", 0) or 0) for t in trades if t.get(key) is not None]
        if len(pairs) < 5:
            correlations[p.upper()] = None
            continue
        xs = [pair[0] for pair in pairs]
        ys = [pair[1] for pair in pairs]
        # Pearson correlation
        n = len(pairs)
        mean_x = sum(xs)/n
        mean_y = sum(ys)/n
        cov = sum((x - mean_x)*(y - mean_y) for x, y in zip(xs, ys))
        std_x = (sum((x - mean_x)**2 for x in xs)/n)**0.5
        std_y = (sum((y - mean_y)**2 for y in ys)/n)**0.5
        correlations[p.upper()] = round(cov / (n * std_x * std_y), 4) if std_x and std_y else None

    return {
        "pillar_correlations": correlations,
        "note": "Pearson correlation between pillar score at trade entry and realized return. Null = insufficient data (<5 trades with pillar data).",
    }


def _mine_regime_performance(trades: list) -> dict:
    """Trade performance broken down by macro regime."""
    groups: dict[str, list] = {}
    for t in trades:
        r = t.get("macro_regime", "Unknown") or "Unknown"
        groups.setdefault(r, []).append(t.get("realized_pct", 0) or 0)
    perf = {}
    for regime, rets in groups.items():
        wins = [r for r in rets if r > 0]
        perf[regime] = {
            "avg_return_pct": round(sum(rets)/len(rets), 3),
            "win_rate_pct":   round(len(wins)/len(rets)*100, 1),
            "trade_count":    len(rets),
            "best_trade_pct": round(max(rets), 2),
            "worst_trade_pct":round(min(rets), 2),
        }
    return {"by_regime": dict(sorted(perf.items(), key=lambda x: -x[1]["avg_return_pct"]))}


# ── GET /api/v1/trading/history ────────────────────────────────────────────────

@router.get("/api/v1/trading/history")
async def get_history(limit: int = Query(50, ge=1, le=200)):
    """All closed trades, most recent first."""
    positions = await _get_positions()
    closed = sorted(
        [p for p in positions.values() if p.get("status") == "closed"],
        key=lambda x: x.get("closed_at", ""),
        reverse=True,
    )
    return {"trades": closed[:limit], "total_closed": len(closed)}


# ── GET /api/v1/trading/portfolio ─────────────────────────────────────────────

@router.get("/api/v1/trading/portfolio")
async def get_portfolio():
    """Full portfolio snapshot: balance + open positions + realized metrics."""
    pos_data, metrics, balance = await asyncio.gather(
        get_positions(),
        get_metrics(),
        _get_balance(),
    )
    return {
        "balance":    pos_data,
        "metrics":    metrics,
        "as_of":      _now(),
    }
