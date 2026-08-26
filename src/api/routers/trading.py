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

from src.api.store import redis_set_key, redis_get_key, supabase_insert_table
from src.api.notify import notify_telegram

_logger = logging.getLogger(__name__)
router  = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────

_INTERNAL_TOKEN    = os.environ.get("INTERNAL_TOKEN", "")
_UPSTASH_URL       = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_UPSTASH_TOKEN     = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_COINGECKO_KEY     = os.environ.get("COINGECKO_API_KEY", "")
_EODHD_KEY         = os.environ.get("EODHD_API_KEY", "")

_CG_BASE           = "https://api.coingecko.com/api/v3"
_CG_PRO            = "https://pro-api.coingecko.com/api/v3"
_CG_HEADERS        = {"x-cg-pro-api-key": _COINGECKO_KEY} if _COINGECKO_KEY else {}

# EODHD real-time base — used as fallback for TradFi assets CoinGecko can't price.
# Endpoint: GET /real-time/{TICKER}.{EX}?api_token=KEY&fmt=json
# Exchanges: US (US Equity / Bond / ETF), CC (Crypto, in case CG is down).
_EODHD_BASE        = "https://eodhd.com/api"

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

# TradFi symbols priced via EODHD (US equity, bond ETF, commodity).
# Mapped to EODHD exchange code (US = US Equity / Bond ETF / Commodity).
_EODHD_SYM_TO_EX: dict[str, str] = {
    # US Equity (high-volume ETFs + mega-caps)
    "SPY": "US", "QQQ": "US", "DIA": "US", "IWM": "US", "VTI": "US",
    "AAPL": "US", "MSFT": "US", "NVDA": "US", "GOOGL": "US", "AMZN": "US",
    "META": "US", "TSLA": "US", "AMD": "US", "NFLX": "US", "JPM": "US",
    "BAC":  "US", "V":    "US", "MA":   "US", "XOM":  "US",
    # US Bond ETFs
    "TLT": "US", "IEF": "US", "SHY": "US", "LQD": "US", "HYG": "US",
    # Commodities
    "GLD": "US", "SLV": "US", "USO": "US", "UNG": "US", "DBC": "US",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Redis helpers (scoped to trading namespace) ────────────────────────────────

async def _rget(key: str):
    return await redis_get_key(key)

async def _rset(key: str, val, ttl: int = 86400 * 7):
    return await redis_set_key(key, val, ttl=ttl)


# ── Live price fetch (CoinGecko → EODHD fallback) ─────────────────────────────

async def _fetch_price_eodhd(symbol: str) -> float | None:
    """Fetch current USD price from EODHD real-time endpoint. Returns None on failure.

    Used for TradFi assets (US Equity, US Bond, Commodity) that CoinGecko can't price.
    Endpoint: GET /real-time/{TICKER}.{EX}?api_token=KEY&fmt=json
    Response: {"code": "SPY.US", "close": 522.31, ...}
    """
    if not _EODHD_KEY:
        return None
    exchange = _EODHD_SYM_TO_EX.get(symbol.upper())
    if not exchange:
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            r = await cl.get(
                f"{_EODHD_BASE}/real-time/{symbol.upper()}.{exchange}",
                params={"fmt": "json", "api_token": _EODHD_KEY},
            )
            r.raise_for_status()
            data = r.json()
            # EODHD real-time returns: {code, timestamp, open, high, low, close, volume, previousClose, change, change_p}
            close = data.get("close")
            if close is None:
                # Some responses wrap in {"data": {...}}
                close = (data.get("data") or {}).get("close")
            if close is None:
                return None
            return float(close)
    except Exception:
        return None


async def _fetch_price(symbol: str) -> float | None:
    """Fetch current USD price. CoinGecko for crypto, EODHD for TradFi.

    Tries CoinGecko first when the symbol has a known crypto mapping, otherwise
    falls through to EODHD. Returns None on total failure.
    """
    cg_id = _SYM_TO_CG.get(symbol.upper())
    if cg_id:
        base = _CG_PRO if _COINGECKO_KEY else _CG_BASE
        try:
            async with httpx.AsyncClient(timeout=8) as cl:
                r = await cl.get(
                    f"{base}/simple/price",
                    params={"ids": cg_id, "vs_currencies": "usd"},
                    headers=_CG_HEADERS,
                )
                data = r.json()
                price = float(data[cg_id]["usd"])
                if price > 0:
                    return price
        except Exception:
            pass
    # TradFi fallback (or CG failed) — try EODHD
    return await _fetch_price_eodhd(symbol)


async def _fetch_prices_eodhd_batch(symbols: list[str]) -> dict[str, float]:
    """EODHD real-time batch fetch — runs concurrent /real-time calls (no batch endpoint).

    EODHD doesn't have a batch endpoint like CoinGecko's /simple/price, so we fan
    out individual requests concurrently with a small concurrency limit.
    """
    if not _EODHD_KEY:
        return {}
    tradfi_syms = [s for s in symbols if s.upper() in _EODHD_SYM_TO_EX]
    if not tradfi_syms:
        return {}
    sem = asyncio.Semaphore(5)

    async def _one(sym: str) -> tuple[str, float | None]:
        async with sem:
            return sym, await _fetch_price_eodhd(sym)

    results = await asyncio.gather(*[_one(s) for s in tradfi_syms])
    return {sym: p for sym, p in results if p is not None and p > 0}


async def _fetch_prices_batch(symbols: list[str]) -> dict[str, float]:
    """Batch price fetch. CoinGecko for crypto, EODHD for TradFi — both run in parallel."""
    cg_ids = {sym: _SYM_TO_CG.get(sym.upper()) for sym in symbols}
    cg_syms = [sym for sym, cid in cg_ids.items() if cid]
    tradfi_syms = [s for s in symbols if s.upper() in _EODHD_SYM_TO_EX]

    # Both helpers short-circuit on empty list, so safe to await unconditionally.
    cg_res, eodhd_res = await asyncio.gather(
        _fetch_prices_cg_batch(cg_syms),
        _fetch_prices_eodhd_batch(tradfi_syms),
    )
    return {**cg_res, **eodhd_res}


async def _fetch_prices_cg_batch(symbols: list[str]) -> dict[str, float]:
    """CoinGecko batch price fetch for crypto symbols."""
    if not symbols:
        return {}
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
            # Mac Mini canonical: regime lives in `macro.regime` (nested). Some
            # legacy shapes / Supabase mirrors also carry flat `macro_regime`.
            # Same nested-then-flat pattern as src/data/market/data_layer.py:1787
            # and the IC loop at trading.py:855 — keep them in sync.
            regime = (
                (cached.get("macro") or {}).get("regime")
                or cached.get("macro_regime")
                or "Unknown"
            )
            for a in assets:
                sym = (a.get("symbol") or a.get("asset_id") or "").upper()
                if sym == symbol.upper():
                    score = a.get("cis_score") or a.get("total_score") or a.get("score", 0) or 0
                    return float(score), a.get("grade", "?"), regime, a
        # Fallback: compute via Railway CIS engine
        universe_data = await calculate_cis_universe()
        assets = universe_data.get("assets") or universe_data.get("universe", [])
        # Same nested-then-flat pattern — /api/v1/cis/universe returns
        # `macro.regime` nested (see cis.py:391 normalizer), not top-level
        regime = (
            (universe_data.get("macro") or {}).get("regime")
            or universe_data.get("macro_regime")
            or "Unknown"
        )
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
    stop_loss_pct: float = Field(0.02, ge=0.005, le=0.30, description="Stop loss % (e.g. 0.02 = 2%)")
    take_profit_pct: float = Field(0.04, ge=0.01, le=2.0, description="Take profit % (e.g. 0.04 = 4%)")
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
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot fetch live price for {symbol}. "
                f"Symbol must be in CoinGecko crypto mapping (line 79) or EODHD TradFi mapping (line 100). "
                f"Set EODHD_API_KEY env var to enable TradFi (US Equity/Bond/Commodity) pricing."
            ),
        )

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
    # caller-supplied pct (default 2% SL / 4% TP from the request schema, tightened
    # 2026-06-19 to bootstrap a paper track record — old defaults were 4%/10%
    # which never triggered in low-vol regimes).
    # Normalize units: crypto vol = % (e.g. 3.5), TradFi = decimal (e.g. 0.03).
    vol_raw = float(_asset.get("volatility_30d") or 0)
    vol_30d = vol_raw / 100 if vol_raw > 0.5 else vol_raw   # % → decimal if >0.5
    if vol_30d > 0.005:
        # Risk 1× daily vol for SL (was 1.5×), target 1.6× for TP (was 2.5×)
        # reward:risk ≈ 1.6 — tighter than before to force exits
        sl_pct_auto = round(max(0.02, min(0.10, 1.0 * vol_30d)), 4)
        tp_pct_auto = round(max(0.04, min(0.30, 1.6 * vol_30d)), 4)
        # Only override if caller left defaults unchanged (avoid overriding intentional sizing)
        final_sl = sl_pct_auto if req.stop_loss_pct == 0.02 else req.stop_loss_pct
        final_tp = tp_pct_auto if req.take_profit_pct == 0.04 else req.take_profit_pct
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
        # No default: this field IS the measurement _mine_signal_accuracy groups on,
        # so defaulting it to NEUTRAL files an untagged trade under a signal that was
        # never issued. NULL means "not recorded" and the miner drops it (S-122).
        "cis_signal":       _asset.get("signal"),
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

    # Persist position — re-read first so a concurrent close/open isn't clobbered
    # (new order_id is unique, so this only adds our row onto the fresh snapshot).
    positions = await _get_positions()
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

    # Fire-and-forget Telegram alert so Seth sees paper fills in ops channel
    filled_pos = positions[order_id]
    asyncio.create_task(_notify_paper_fill(filled_pos))

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

        # Check SL/TP triggers — guard against 0/None thresholds (METER_REBAL positions
        # carry stop_loss=take_profit=0; without the truthiness guard `price >= 0` fires
        # tp_triggered on every long and `price >= 0` fires sl_triggered on every short,
        # producing bogus flags — the 2026-07-04 Loop Watch false signal).
        sl = pos.get("stop_loss"); tp = pos.get("take_profit")
        if side == "LONG":
            if sl and price <= sl:
                pos["sl_triggered"] = True
            elif tp and price >= tp:
                pos["tp_triggered"] = True
        else:
            if sl and price >= sl:
                pos["sl_triggered"] = True
            elif tp and price <= tp:
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

    # Race-safe: re-read and apply only THIS position's close onto the fresh snapshot,
    # so a concurrent close/open (5-min exit loops, order endpoint) isn't clobbered.
    positions = await _get_positions()
    positions[order_id] = pos
    await _save_positions(positions)

    # Return cash to paper balance
    balance = await _get_balance()
    await _save_balance(balance + exit_value)

    _logger.info(f"[TRADING] CLOSE {sym} @ {price:.4f} | P&L: {pnl_pct:+.2f}% (${pnl_abs:+.2f})")

    # Fire-and-forget Telegram alert — Seth sees realized P&L accumulate
    closed_pos = positions[order_id]
    asyncio.create_task(_notify_paper_close(closed_pos, pnl_pct, pnl_abs))

    # Fire-and-forget Supabase trade_results write — populates Simons IC table
    # + unblocks L1 metric in MINIMAX_SYNC.md. Failure logged, doesn't block close.
    asyncio.create_task(_write_closed_trade_to_supabase(closed_pos))

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


# ── Paper trade → trade_results row (Simons Upgrade P0.1.1) ────────────────────
# Mirrors quant.py:_trade_to_row() so Freqtrade fills + paper closes land in the
# same schema. Without this, the paper trigger never populates trade_results
# (L1 in MINIMAX_SYNC.md stays at 0).
def _paper_position_to_row(pos: dict) -> dict:
    """Normalize a closed paper position into a trade_results row."""
    return {
        "symbol":               pos.get("symbol"),
        # S-122. Defaulting to LONG is the worst case of the whole class, because LONG
        # is the MAJORITY value (175/212) — a mislabelled row looks exactly like a
        # correct one, so unlike S-121 it can never be caught by inspection. And the
        # cost is not symmetric: shorts average -2.28% against longs' +0.26%, so the
        # failure quietly moves the worst trades into the long side of the record.
        "side":                 (pos.get("side") or "").upper() or None,
        "entry_time":           pos.get("opened_at"),
        "exit_time":            pos.get("closed_at"),
        "entry_price":          pos.get("entry_price"),
        "exit_price":           pos.get("exit_price"),
        "profit_pct":           pos.get("realized_pct"),
        "profit_abs":           pos.get("realized_pnl"),
        # "manual" attributes the close to a human decision. An unrecorded exit is not
        # a manual exit, and the two must not merge in the exit-reason breakdown.
        "exit_reason":          pos.get("exit_reason"),
        "enter_tag":            None,  # paper trigger has no enter_tag
        # CIS_AUTO is one of three live sleeves. Attributing an untagged position to
        # it corrupts the per-strategy attribution rather than leaving a gap in it.
        "strategy":             pos.get("strategy"),
        # NOTE: column names must match the trade_results table exactly. The previous
        # *_at_entry / macro_regime_at_entry / recorded_at keys did NOT exist on the
        # table → every PostgREST insert 400'd silently (fire-and-forget swallowed it),
        # leaving trade_results empty despite closes happening. Fixed 2026-06-27.
        "cis_score":            pos.get("cis_score"),
        "cis_grade":            pos.get("cis_grade"),
        "pillar_f":             pos.get("pillar_f_at_entry") or pos.get("pillar_f"),
        "pillar_m":             pos.get("pillar_m_at_entry") or pos.get("pillar_m"),
        "pillar_o":             pos.get("pillar_o_at_entry") or pos.get("pillar_o"),
        "pillar_s":             pos.get("pillar_s_at_entry") or pos.get("pillar_s"),
        "pillar_a":             pos.get("pillar_a_at_entry") or pos.get("pillar_a"),
        "macro_regime":         pos.get("macro_regime"),
        "data_tier":            pos.get("data_tier"),
        "realized_return_7d":   None,  # filled later if 7d price data available
    }


async def _write_closed_trade_to_supabase(pos: dict) -> bool:
    """Best-effort write of a closed paper position to trade_results.
    Fire-and-forget — failure logged but does not block close.
    """
    try:
        row = _paper_position_to_row(pos)
        if not row.get("symbol") or not row.get("exit_time"):
            return False
        ok = await supabase_insert_table("trade_results", [row])
        if ok:
            _logger.info(f"[TRADE_RESULTS] wrote {row['symbol']} {row['exit_reason']} "
                         f"profit_pct={row['profit_pct']:+.2f}%" if row['profit_pct'] is not None
                         else f"[TRADE_RESULTS] wrote {row['symbol']} {row['exit_reason']}")
        else:
            _logger.warning(f"[TRADE_RESULTS] write failed for {row.get('symbol')}")
        return ok
    except Exception as e:
        _logger.warning(f"[TRADE_RESULTS] exception: {e}")
        return False


# ── Aged-position sweep (paper track-record bootstrapper) ─────────────────────
# Closes paper positions open >7 days with unrealized PnL in ±10% band.
# Reason: tightened SL/TP (2%/4% as of 2026-06-19) still don't trigger on
# low-vol regime grind. Without an exit path, win_rate stays null forever.
# Band widened 5% → 10% on 2026-06-26 so losers like AAPL (-6.12%) get swept
# (was the gating item for MINIMAX_TRADING_TRIGGER.md track record).
# This is a paper-only intervention — distinct exit_reason so it can be
# excluded from LP-facing metrics if needed, but the default is to count it.
_AGE_SWEEP_DAYS = 7
_AGE_SWEEP_PNL_BAND_PCT = 10.0  # ±10% (was 5%)


async def sweep_aged_positions() -> dict:
    """
    Close paper positions >7 days old with unrealized PnL in ±5% band.
    Returns summary: {swept, skipped, total_open, swept_symbols, errors, ran_at}.
    """
    from datetime import datetime, timezone, timedelta

    positions = await _get_positions()
    # METER_REBAL sleeve is governed by the rebalance loop, not the age sweep.
    open_positions = {oid: p for oid, p in positions.items()
                      if p.get("status") == "open" and p.get("strategy") != "METER_REBAL"}

    if not open_positions:
        return {"swept": 0, "skipped": 0, "total_open": 0,
                "swept_symbols": [], "errors": [], "ran_at": _now()}

    # Refresh prices so we evaluate PnL at current market
    symbols = list({p["symbol"] for p in open_positions.values()})
    prices = await _fetch_prices_batch(symbols)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_AGE_SWEEP_DAYS)

    swept = 0
    skipped = 0
    swept_symbols = []
    errors = []

    for oid, pos in list(open_positions.items()):
        try:
            # Age check — require opened_at > 7 days ago
            opened_at_str = pos.get("opened_at", "")
            if not opened_at_str:
                skipped += 1
                continue
            try:
                opened_at = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
            except Exception:
                skipped += 1
                continue

            age_days = (now - opened_at).total_seconds() / 86400
            if age_days < _AGE_SWEEP_DAYS:
                skipped += 1
                continue

            # PnL check at current price
            sym = pos["symbol"]
            price = prices.get(sym) or pos.get("current_price") or pos.get("entry_price")
            if not price:
                skipped += 1
                continue

            qty = pos.get("qty", 0)
            side = pos.get("side", "LONG")
            entry = pos.get("entry_price", 0)

            if side == "LONG":
                pnl_pct = (price / entry - 1) * 100 if entry > 0 else 0
            else:
                pnl_pct = (entry / price - 1) * 100 if price > 0 else 0

            if abs(pnl_pct) > _AGE_SWEEP_PNL_BAND_PCT:
                skipped += 1
                continue

            # Sweep close — recurse into close_position for realized PnL + cash return
            req = CloseRequest(reason="sweep_aged_position")
            await close_position(oid, req)
            swept += 1
            swept_symbols.append({"symbol": sym, "age_days": round(age_days, 1),
                                  "pnl_pct": round(pnl_pct, 2)})
            _logger.info(f"[SWEEP] {sym} age={age_days:.1f}d PnL={pnl_pct:+.2f}% — forced close")
        except Exception as e:
            errors.append({"order_id": oid, "error": str(e)})
            _logger.warning(f"[SWEEP] error closing {oid}: {e}")

    return {
        "swept":         swept,
        "skipped":       skipped,
        "total_open":    len(open_positions),
        "swept_symbols": swept_symbols,
        "errors":        errors,
        "ran_at":        _now(),
    }


@router.post("/internal/sweep-aged-positions")
async def trigger_sweep_aged(x_internal_token: str = Header(default="")):
    """
    Manual trigger for aged-position sweep. Auth: X-Internal-Token must match
    INTERNAL_TOKEN env var. Returns sweep summary.
    """
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await sweep_aged_positions()



# ── SL/TP auto-execution (Simons Upgrade P0.2) ────────────────────────────────
# Until 2026-06-26 SL/TP was only a flag — sl_triggered/tp_triggered were set in
# get_positions but never closed the position. AAPL bled -6.12% past its -2% SL
# for 24h with no exit. This loop scans open positions every 5min, calls
# close_position() when price breaches SL/TP, and writes to trade_results.
async def _sl_tp_exit() -> dict:
    """
    Close any open position whose current price has breached its SL or TP.
    Returns summary: {closed: int, sl: int, tp: int, errors: list}.
    """
    positions = await _get_positions()
    # METER_REBAL positions carry no SL/TP and are governed by the rebalance loop.
    open_positions = {oid: p for oid, p in positions.items()
                      if p.get("status") == "open" and p.get("strategy") != "METER_REBAL"}
    if not open_positions:
        return {"closed": 0, "sl": 0, "tp": 0, "errors": [], "scanned": 0}

    # Fetch live prices for all open symbols
    symbols = list({p["symbol"] for p in open_positions.values()})
    prices  = await _fetch_prices_batch(symbols)

    closed = 0
    sl = 0
    tp = 0
    errors = []

    for oid, pos in list(open_positions.items()):
        try:
            sym    = pos["symbol"]
            side   = pos.get("side", "LONG")
            entry  = pos.get("entry_price", 0)
            sl_px  = pos.get("stop_loss", 0)
            tp_px  = pos.get("take_profit", 0)
            price  = prices.get(sym) or pos.get("current_price") or entry
            if not price:
                continue

            triggered = None
            if side == "LONG":
                if sl_px and price <= sl_px:
                    triggered = "sl_triggered"
                    sl += 1
                elif tp_px and price >= tp_px:
                    triggered = "tp_triggered"
                    tp += 1
            else:  # SHORT (defensive — trigger is long-only but path is here)
                if sl_px and price >= sl_px:
                    triggered = "sl_triggered"
                    sl += 1
                elif tp_px and price <= tp_px:
                    triggered = "tp_triggered"
                    tp += 1

            if triggered:
                await close_position(oid, CloseRequest(reason=triggered))
                closed += 1
                _logger.info(f"[SL/TP] {sym} {triggered} @ {price:.4f}")
        except Exception as e:
            errors.append({"order_id": oid, "error": str(e)})
            _logger.warning(f"[SL/TP] error closing {oid}: {e}")

    return {"closed": closed, "sl": sl, "tp": tp, "errors": errors,
            "scanned": len(open_positions)}


@router.post("/internal/sl-tp-exit")
async def trigger_sl_tp(x_internal_token: str = Header(default="")):
    """Manual trigger for SL/TP auto-execution. Auth via INTERNAL_TOKEN."""
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await _sl_tp_exit()


# ── CIS-flip exit (Simons Upgrade P0.3) ───────────────────────────────────────
# Closes positions whose CIS signal has flipped to UNDERPERFORM/UNDERWEIGHT
# since entry. Fetches latest CIS scores from Supabase `cis_scores`, compares
# to position's signal-at-entry. Defensive fallback: also close if score < 45
# even if signal field is missing/legacy.
_CIS_FLIP_SIGNALS = {"UNDERPERFORM", "UNDERWEIGHT"}
_CIS_FLIP_SCORE_FLOOR = 45.0


async def _cis_flip_exit() -> dict:
    """
    Close positions whose latest CIS signal is bearish.
    Returns summary: {closed: int, by_signal: int, by_score: int, errors: list}.
    """
    positions = await _get_positions()
    # METER_REBAL sleeve is governed by the rebalance loop (weight→0 drops a decayed name).
    open_positions = {oid: p for oid, p in positions.items()
                      if p.get("status") == "open" and p.get("strategy") != "METER_REBAL"}
    if not open_positions:
        return {"closed": 0, "by_signal": 0, "by_score": 0, "errors": [], "scanned": 0}

    symbols = sorted({p["symbol"] for p in open_positions.values()})

    # Fetch latest CIS score per symbol from Supabase
    latest_by_sym: dict = {}
    try:
        from src.api.store import supabase_get_recent_scores
        latest_by_sym = await supabase_get_recent_scores(symbols, n=1)
    except Exception as e:
        _logger.warning(f"[CIS-FLIP] Supabase fetch failed: {e}")
        return {"closed": 0, "by_signal": 0, "by_score": 0,
                "errors": [{"phase": "supabase", "error": str(e)}], "scanned": 0}

    closed = 0
    by_signal = 0
    by_score = 0
    errors = []

    for oid, pos in list(open_positions.items()):
        try:
            sym = pos["symbol"]
            latest_list = latest_by_sym.get(sym.upper(), [])
            if not latest_list:
                continue
            latest = latest_list[0]
            sig = (latest.get("signal") or "").upper().strip()
            score = latest.get("score") or latest.get("cis_score")

            should_close = False
            reason = None
            if sig in _CIS_FLIP_SIGNALS:
                should_close = True
                reason = "cis_flip_exit"
                by_signal += 1
            elif score is not None and score < _CIS_FLIP_SCORE_FLOOR:
                # Defensive: score below D grade floor even with NEUTRAL signal
                should_close = True
                reason = "cis_flip_exit_score"
                by_score += 1

            if should_close:
                await close_position(oid, CloseRequest(reason=reason))
                closed += 1
                _logger.info(f"[CIS-FLIP] {sym} {reason} signal={sig} score={score}")
        except Exception as e:
            errors.append({"order_id": oid, "error": str(e)})
            _logger.warning(f"[CIS-FLIP] error closing {oid}: {e}")

    return {"closed": closed, "by_signal": by_signal, "by_score": by_score,
            "errors": errors, "scanned": len(open_positions)}


@router.post("/internal/cis-flip-exit")
async def trigger_cis_flip(x_internal_token: str = Header(default="")):
    """Manual trigger for CIS-flip exit. Auth via INTERNAL_TOKEN."""
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await _cis_flip_exit()


# ── Meter-driven paper rebalance (full-universe, cause-proximity sized) ────────
# A separate paper sleeve from the sparse CIS_AUTO tilt: it holds the WHOLE qualifying
# universe at grade-driven, out-of-circle-haircut weights (src/data/market/risk_meter.py),
# rebalanced low-frequency. Pure notional book (own SLEEVE_NAV — never touches the shared
# paper balance). Every close writes trade_results + feeds the Simons IC loop → this is the
# throughput that gives the Learn layer real sample size. Governed ONLY by the rebalance
# loop (the SL/TP / CIS-flip / age-sweep loops skip strategy==METER_REBAL).
_REDIS_REBAL_STATE = "trading:rebal_state"      # {last_rebal, last_regime}
REBAL_SLEEVE_TAG   = "METER_REBAL"
REBAL_SLEEVE_NAV   = 100_000.0                  # paper notional; weights × NAV = position size
# Risk circuit-breaker: close any sleeve position past this adverse excursion, EVERY
# cycle, independent of the churn-gated rotation. Rationale: the meter opens shorts on
# benchmark-underperformers, but the sleeve trades absolute price while the signal only
# predicts benchmark-relative alpha — so a "correct" short (still UNDERPERFORM) can bleed
# unbounded absolute beta in a non-risk-off tape (ADA short −24.6%, 2026-07-04 Loop Watch).
# This is a catastrophic-loss breaker, not drawdown management: risk reduction is never
# churn-gated, and each close feeds trade_results → the Learn loop.
REBAL_MAX_ADVERSE_PCT = -20.0                   # unrealized % that force-closes a position


async def _get_rebal_state() -> dict:
    raw = await _rget(_REDIS_REBAL_STATE)
    return raw if isinstance(raw, dict) else {"last_rebal": None, "last_regime": None}


def _open_rebal_position(sym: str, notional: float, side: str, asset: dict,
                         regime: str, price: float) -> tuple[str, dict] | None:
    if not price or price <= 0:
        return None
    pillars = asset.get("pillars") or {}
    _p = lambda k: round(float(pillars.get(k) or 0), 1)
    oid = "rb_" + uuid.uuid4().hex[:10]
    pos = {
        "order_id": oid, "symbol": sym, "side": side,
        "size_usd": round(notional, 2), "qty": round(notional / price, 8),
        "entry_price": round(price, 6), "stop_loss": 0, "take_profit": 0,
        "current_price": round(price, 6), "current_value_usd": round(notional, 2),
        "unrealized_pnl": 0.0, "unrealized_pct": 0.0,
        "cis_score": round(float(asset.get("cis_score") or asset.get("score") or 0), 1),
        "cis_grade": asset.get("grade") or asset.get("cis_grade") or "?",
        "cis_signal": asset.get("signal"),  # S-122: no default — see submit_order
        "pillar_f_at_entry": _p("F"), "pillar_m_at_entry": _p("M"),
        "pillar_o_at_entry": _p("O") or _p("R"), "pillar_s_at_entry": _p("S"),
        "pillar_a_at_entry": _p("A"),
        "macro_regime": regime, "strategy": REBAL_SLEEVE_TAG, "mode": "PAPER",
        "status": "open", "opened_at": _now(), "updated_at": _now(),
        "cause_proximity": asset.get("cause_proximity"),
    }
    return oid, pos


async def _close_rebal_position(positions: dict, oid: str, reason: str, price: float) -> bool:
    """Close a sleeve position: realized P&L + trade_results write. Does NOT touch the
    shared paper balance (sleeve is a pure notional book)."""
    pos = positions.get(oid)
    if not pos or pos.get("status") != "open":
        return False
    qty, side, entry = pos.get("qty", 0), pos.get("side", "LONG"), pos.get("entry_price", 0)
    if not price or price <= 0:
        price = pos.get("current_price") or entry
    if side == "LONG":
        pnl_abs = (price - entry) * qty
        pnl_pct = (price / entry - 1) * 100 if entry else 0
    else:
        pnl_abs = (entry - price) * qty
        pnl_pct = (entry / price - 1) * 100 if price else 0
    pos.update({
        "status": "closed", "exit_price": round(price, 6),
        "exit_value_usd": round(qty * price, 2), "realized_pnl": round(pnl_abs, 2),
        "realized_pct": round(pnl_pct, 3), "exit_reason": reason,
        "closed_at": _now(), "updated_at": _now(),
    })
    positions[oid] = pos
    asyncio.create_task(_write_closed_trade_to_supabase(pos))
    return True


async def _run_paper_rebalance(dry_run: bool = True) -> dict:
    from src.data.market.risk_meter import (
        build_risk_meter, plan_rebalance, _SHORT_OK, _norm_regime, REGIME_FACTOR)
    from src.api.routers.cis import get_cis_universe
    data = await get_cis_universe()
    universe = (data or {}).get("universe", []) or []
    regime = (data or {}).get("macro_regime") or "Neutral"
    shorts_ok = _norm_regime(regime) in _SHORT_OK

    # ── PRUNED 2026-07-06: conviction_book is OFF by default. ──────────────────
    # The A2 OOS harness (Minimax-A, audit commit 0e868a7) FALSIFIED the empirical
    # edge-map-direction hypothesis: the edge gate took 4 straight longs into a falling
    # BTC (−$479) while the frozen CIS baseline made money (+0.59 Sharpe). conviction_book
    # anchors direction on that SAME edge-map tier×band signal, so it is presumed overfit
    # until it passes the same harness. Do NOT trade it until validated. Default target =
    # the risk-meter (grade × 出圈 haircut) — unvalidated but not falsified. Opt-in for
    # A/B research only via CONVICTION_BOOK_ENABLED=1.
    if os.environ.get("CONVICTION_BOOK_ENABLED", "").lower() in ("1", "true", "yes"):
        from src.data.cis.conviction import conviction_book
        cur = {}
        try:
            from src.api.routers.signals import compute_current_band
            cur = await compute_current_band()
        except Exception as _e:
            _logger.warning(f"[REBAL] current-band fetch failed: {_e}")
        gross = REGIME_FACTOR.get(_norm_regime(regime), 0.80)
        target = conviction_book(universe, cur.get("tiers_now") or {},
                                 cur.get("current_band") or "3_neutral",
                                 shorts_ok=shorts_ok, gross=gross)
    else:
        rm = build_risk_meter(universe, regime)
        target = {s: w["meter_weight"] for s, w in rm["weights"].items() if w.get("meter_weight")}
    asset_by_sym = {(a.get("symbol") or a.get("asset_id") or "").upper(): a
                    for a in universe if isinstance(a, dict)}

    positions = await _get_positions()
    sleeve = {oid: p for oid, p in positions.items()
              if p.get("status") == "open" and p.get("strategy") == REBAL_SLEEVE_TAG}
    # S-122. `side` used to default to LONG here. This is a LIVE SIZING input, not a
    # record: assuming LONG on a short makes plan_rebalance compute the delta with the
    # wrong sign, so the "safe" default is the one that doubles the wrong exposure.
    # Every position we write carries a side, so a missing one means the record is
    # corrupt — and with a corrupt record BOTH available guesses are wrong (assume a
    # side and mis-size it; drop it and re-buy something we already hold). So refuse,
    # the way neutralize() refuses below min_obs rather than returning a number.
    current, corrupt = {}, []
    for oid, p in sleeve.items():
        side = (p.get("side") or "").upper()
        if side not in ("LONG", "SHORT"):
            corrupt.append({"order_id": oid, "symbol": p.get("symbol"), "side": p.get("side")})
            continue
        current[(p.get("symbol") or "").upper()] = {
            "order_id": oid,
            "notional": float(p.get("current_value_usd") or p.get("size_usd") or 0),
            "side": side,
        }
    if corrupt:
        _logger.error("[REBAL] refusing to rebalance — %d position(s) without a usable "
                      "side: %s", len(corrupt), corrupt)
        return {"status": "refused", "reason": "positions_missing_side",
                "corrupt_positions": corrupt, "n_corrupt": len(corrupt)}

    nav = REBAL_SLEEVE_NAV
    state = await _get_rebal_state()
    now = datetime.now(timezone.utc)
    plan = plan_rebalance(target, current, nav, state, regime, now)
    summary = {"dry_run": dry_run, "regime": regime, "n_target": len(target),
               "n_held": len(current), "nav": nav, **plan}

    # ── Risk circuit-breaker (NOT churn-gated) ───────────────────────────────
    # Close positions regardless of whether the rotation triggers, for two risk reasons:
    #   1. adverse excursion past the cap (unbounded short bleed), and
    #   2. a held SHORT when the regime no longer permits shorts (Jazz 2026-07-05:
    #      regime-gate shorts — only true falling-market regimes). Both are risk
    #      reduction, which is never churn-gated. Each close feeds the Learn loop.
    # (shorts_ok already computed above from the regime; the conviction book only opens shorts
    #  when it's true, so a held short with shorts_ok False means the regime just flipped → close.)
    brk_prices = await _fetch_prices_batch([p["symbol"] for p in sleeve.values()]) if sleeve else {}
    breaker = []
    for oid, p in sleeve.items():
        px = brk_prices.get(p.get("symbol")) or p.get("current_price") or p.get("entry_price")
        entry = p.get("entry_price") or 0
        if not px or not entry:
            continue
        is_short = p.get("side") != "LONG"
        upct = (entry / px - 1) * 100 if is_short else (px / entry - 1) * 100
        if upct <= REBAL_MAX_ADVERSE_PCT:
            breaker.append((oid, px, round(upct, 2), "risk_breaker"))
        elif is_short and not shorts_ok:
            breaker.append((oid, px, round(upct, 2), "regime_no_short"))
    summary["breaker"] = [{"symbol": sleeve[o]["symbol"], "side": sleeve[o].get("side"),
                           "unrealized_pct": u, "reason": rsn} for o, _, u, rsn in breaker]

    if not dry_run and breaker:
        for oid, px, _u, rsn in breaker:
            try:
                if await _close_rebal_position(positions, oid, rsn, px):
                    current.pop((sleeve[oid].get("symbol") or "").upper(), None)
            except Exception as e:
                _logger.warning(f"[REBAL] breaker close {oid} failed: {e}")
        # Race-safe persist of breaker closes even if rotation doesn't run below.
        fresh = await _get_positions()
        for o2, p2 in positions.items():
            if p2.get("strategy") == REBAL_SLEEVE_TAG:
                fresh[o2] = p2
        await _save_positions(fresh)
        positions = fresh
        all_closed = [p for p in positions.values() if p.get("status") == "closed"]
        if len(all_closed) >= 5:
            asyncio.create_task(_auto_mine_ic(all_closed, len(all_closed)))
        _logger.info(f"[REBAL] breaker closed {len(breaker)} positions "
                     f"({[(sleeve[o].get('symbol'), rsn) for o,_,_,rsn in breaker]})")

    if dry_run or not plan.get("triggered"):
        return summary

    # ── execute ── one batched price fetch for everything we'll touch (no N+1)
    close_syms = [sleeve[oid]["symbol"] for oid in plan["closes"] if oid in sleeve]
    open_syms = [o["sym"] for o in plan["opens"]] + [r["sym"] for r in plan["resizes"]]
    prices = await _fetch_prices_batch(list({*close_syms, *open_syms}))

    closed = opened = 0
    for oid in plan["closes"]:
        try:
            p = sleeve.get(oid)
            if p and await _close_rebal_position(positions, oid, "rebalance",
                                                 prices.get(p["symbol"]) or p.get("current_price")):
                closed += 1
        except Exception as e:
            _logger.warning(f"[REBAL] close {oid} failed: {e}")
    for r in plan["resizes"]:
        try:
            p = sleeve.get(r["order_id"])
            if not p:
                continue
            await _close_rebal_position(positions, r["order_id"], "rebalance_resize",
                                        prices.get(r["sym"]) or p.get("current_price"))
            closed += 1
            res = _open_rebal_position(r["sym"], r["notional"], r["side"],
                                       asset_by_sym.get(r["sym"], {}), regime, prices.get(r["sym"]))
            if res:
                positions[res[0]] = res[1]; opened += 1
        except Exception as e:
            _logger.warning(f"[REBAL] resize {r.get('sym')} failed: {e}")
    for o in plan["opens"]:
        try:
            res = _open_rebal_position(o["sym"], o["notional"], o["side"],
                                       asset_by_sym.get(o["sym"], {}), regime, prices.get(o["sym"]))
            if res:
                positions[res[0]] = res[1]; opened += 1
        except Exception as e:
            _logger.warning(f"[REBAL] open {o.get('sym')} failed: {e}")

    # Race-safe save: re-read the live positions and re-apply ONLY our METER_REBAL
    # mutations onto the fresh snapshot. Rebalance is the sole writer of METER_REBAL
    # entries, so this preserves any concurrent CIS_AUTO closes the 5-min exit loops
    # may have written during our awaits (universe + price fetch).
    fresh = await _get_positions()
    for oid, p in positions.items():
        if p.get("strategy") == REBAL_SLEEVE_TAG:
            fresh[oid] = p
    await _save_positions(fresh)
    positions = fresh
    await _rset(_REDIS_REBAL_STATE, {"last_rebal": _now(), "last_regime": regime})

    # Feed the Simons IC loop on the now-larger closed set
    all_closed = [p for p in positions.values() if p.get("status") == "closed"]
    if len(all_closed) >= 5:
        asyncio.create_task(_auto_mine_ic(all_closed, len(all_closed)))

    _logger.info(f"[REBAL] {plan['reason']} — opened={opened} closed={closed} regime={regime}")
    return {"executed": True, "regime": regime, "reason": plan["reason"],
            "opened": opened, "closed": closed, "resized": len(plan["resizes"]),
            "n_target": len(target)}


@router.get("/api/v1/trading/rebalance/preview")
async def rebalance_preview():
    """Dry-run the meter rebalance — shows the target book + the trades it WOULD make.
    Safe: no mutation. Use this to verify before enabling the live loop."""
    return await _run_paper_rebalance(dry_run=True)


@router.post("/internal/rebalance")
async def trigger_rebalance(x_internal_token: str = Header(default="")):
    """Execute one meter rebalance. Auth via INTERNAL_TOKEN."""
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await _run_paper_rebalance(dry_run=False)


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
        from src.data.factors.performance import update_from_pillar_fitness, load as _fp_load
        update_from_pillar_fitness(enriched, n_closed)

        _logger.info(f"[IC-LOOP] IC update complete — correlations: {corrs}")

        # 4. Check for weak IC pillars → queue Gemma4-26b discovery if needed
        try:
            cis_raw = await _rget("cis:local_scores")
            # Canonical UPPER_SNAKE or None — see the note at `_REGIME_GATE`.
            # Discovery buckets its results by regime; `Tightening` and
            # `TIGHTENING` filed as two regimes is the S-120 duplicate all over.
            from src.data.cis.cis_provider import canonical_regime_strict
            regime = None
            if cis_raw and isinstance(cis_raw, dict):
                regime = canonical_regime_strict(
                    cis_raw.get("macro_regime")
                    or (cis_raw.get("macro") or {}).get("regime")
                )
            fp = _fp_load()
            if fp:
                from src.data.factors.discovery import check_and_queue_discovery
                queued = check_and_queue_discovery(fp, regime)
                if queued:
                    _logger.info(f"[IC-LOOP] Discovery queued for weak pillars: {queued}")
        except Exception as disc_exc:
            _logger.debug(f"[IC-LOOP] Discovery check skipped: {disc_exc}")

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
    # _rget/redis_get_key AUTO-json.loads → factor_raw is already a dict (or None).
    # The old `json.loads(factor_raw)` did json.loads(dict) → TypeError → 500 (same class
    # of bug already fixed for cis_raw below). Use the dict directly.
    fp   = factor_raw if isinstance(factor_raw, dict) else {}
    meta = fp.get("_meta", {})

    # Compute IC multiplier per pillar (mirrors _refresh_ic_multipliers in cis_provider.py)
    #
    # ⚠️ 1.0 HAS TWO MEANINGS AND THEY MUST BE TOLD APART (S-215, Minimax-A 2026-08-23).
    # A pillar with no usable factors gets 1.0, and a pillar whose IC genuinely
    # came out flat also gets 1.0. For four months every pillar read 1.0 because
    # `realized_return_7d` was NULL on all 234 rows — the weighting mechanism had
    # never once been energised — and the payload was indistinguishable from a
    # healthy engine that had measured neutrality. Same defect as `ok=True rows=0`,
    # same defect as a NAV that is flat because nothing could be priced.
    # So the count of MEASURED pillars ships alongside the multipliers.
    ic_mult: dict[str, float] = {}
    ic_source: dict[str, str] = {}
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
            ic_source[pillar] = f"measured (n={len(active)})"
        else:
            ic_mult[pillar] = 1.0
            ic_source[pillar] = ("no factor cleared |r|>0.10 with n>=10"
                                 if factors else "no factors for this pillar")

    n_measured = sum(1 for v in ic_source.values() if v.startswith("measured"))

    # ── Parse current regime ──────────────────────────────────────────────────
    # NOTE: _rget returns a parsed dict (redis_get_key auto-json.loads), not a
    # raw string. Earlier code did `json.loads(cis_raw)` which always failed
    # silently and pinned regime=UNKNOWN. Use the dict directly.
    # CANONICALISE BEFORE THE LOOKUP (S-242, 2026-08-26). Reading the right key
    # was only half the fix: `_REGIME_GATE` below is keyed UPPER_SNAKE and the
    # engine sends `Tightening`, so the raw label missed and silently took the
    # 50 default where TIGHTENING calls for 52. Same defect the signal feed had,
    # one endpoint over — a threshold quietly moved by a string's letter case.
    from src.data.cis.cis_provider import canonical_regime_strict
    regime = None
    if cis_raw and isinstance(cis_raw, dict):
        regime = canonical_regime_strict(
            cis_raw.get("macro_regime")
            or (cis_raw.get("macro") or {}).get("regime")
        )

    # None = unmeasured, and 50 is a regime-neutral default rather than a gate
    # anyone chose for the current regime. Surfaced as `regime_measured` below
    # so a consumer can tell the two apart.
    gate_threshold = _REGIME_GATE.get(regime or "", 50)
    loop_active    = n_closed >= 5 and bool(meta.get("last_run"))
    next_mine_at   = max(0, 5 - n_closed) if n_closed < 5 else (5 - (n_closed % 5)) % 5 or 5

    return {
        "loop_active":      loop_active,
        "closed_trades":    n_closed,
        "open_positions":   len(open_),
        "ic_multipliers":   ic_mult,
        # Read these two BEFORE reading the multipliers above. 0 measured means
        # every 1.0 is a default, and the CIS weighting layer is inert.
        "ic_pillars_measured": n_measured,
        "ic_multiplier_source": ic_source,
        "ic_layer_active":  n_measured > 0,
        "mine_last_run":    meta.get("last_run"),
        "mine_periods":     meta.get("periods_computed", 0),
        "mine_total_trades":meta.get("total_trades_analysed", 0),
        "regime":           regime,
        "regime_measured":  regime is not None,
        "gate_threshold":   gate_threshold,
        "next_mine_at":     next_mine_at,
        "auto_mine_every":  5,
        "active_factors":   len([v for k, v in fp.items() if k != "_meta" and isinstance(v, dict) and v.get("status") == "active"]),
    }


# ── GET /api/v1/trading/metrics ────────────────────────────────────────────────

async def _backfill_regime_from_history(positions: list) -> int:
    """
    For closed positions with macro_regime='Unknown' (legacy entries written
    before the nested-regime fix), look up the regime from the Supabase
    cis_scores history at the position's opened_at time.

    Mutates the position dicts in-place (sets macro_regime). Returns count of
    backfilled entries. Safe no-op if Supabase is unreachable.
    """
    unknown = [p for p in positions if p.get("macro_regime") in (None, "Unknown", "UNKNOWN")]
    if not unknown:
        return 0

    try:
        # Two-tier backfill:
        #  Tier 1: Supabase cis_scores history — precise match to opened_at.
        #    Limitation: cis_scores' symbol column is filterable but NOT
        #    returned in SELECT response, so we query per-symbol with eq.
        #    Tier 1 covers any position opened after ~2026-06-19 (history
        #    start).
        #  Tier 2: current /api/v1/cis/universe per-asset macro_regime.
        #    Coarse (uses today's regime, not the regime at open) but
        #    always-available fallback for legacy closes that pre-date
        #    Supabase history. Better than the Unknown bucket for
        #    by_regime metrics.
        from src.api.store import supabase_get_history
        from src.data.cis.cis_provider import calculate_cis_universe

        symbols = list({p["symbol"].upper() for p in unknown})

        rows_by_sym: dict[str, list] = {}
        for sym in symbols:
            rows_by_sym[sym] = await supabase_get_history(sym, days=14)

        # Tier 2: universe per-asset macro_regime (top-level on each asset,
        # not the nested global macro.regime). Coarse but always available.
        universe_regime: dict[str, str] = {}
        try:
            universe = await calculate_cis_universe()
            for a in (universe.get("assets") or universe.get("universe", [])):
                a_sym = (a.get("symbol") or a.get("asset_id") or "").upper()
                a_regime = a.get("macro_regime")
                if a_sym and a_regime and a_regime != "Unknown":
                    universe_regime[a_sym] = a_regime
        except Exception as e:
            _logger.debug(f"[METRICS] universe regime fallback unavailable: {e}")
    except Exception as e:
        _logger.warning(f"[METRICS] regime backfill skipped: {e}")
        return 0

    from datetime import datetime
    backfilled = 0
    for pos in unknown:
        sym = pos["symbol"].upper()
        rows = rows_by_sym.get(sym, [])

        opened_at_str = pos.get("opened_at", "")
        if not opened_at_str:
            continue
        try:
            opened_at = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
        except Exception:
            continue

        # Tier 1: Supabase row whose recorded_at is closest to (not after) opened_at
        best_row = None
        best_delta = None
        for row in rows:
            ts_str = row.get("recorded_at", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts > opened_at:
                continue
            delta = abs((opened_at - ts).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_row = row

        if best_row and best_row.get("macro_regime"):
            pos["macro_regime"] = best_row["macro_regime"]
            pos["macro_regime_source"] = "backfilled_from_history"
            backfilled += 1
            continue

        # Tier 2: coarse — current per-asset regime from /cis/universe
        coarse = universe_regime.get(sym)
        if coarse:
            pos["macro_regime"] = coarse
            pos["macro_regime_source"] = "backfilled_from_universe"
            backfilled += 1

    return backfilled


@router.get("/api/v1/trading/metrics")
async def get_metrics():
    """
    Realized trade performance: win rate, avg return, total P&L, Sharpe approximation.
    """
    positions = await _get_positions()
    balance   = await _get_balance()

    closed = [p for p in positions.values() if p.get("status") == "closed"]
    open_  = [p for p in positions.values() if p.get("status") == "open"]

    # ── TWO SEPARATE BOOKS (do not conflate) ──────────────────────────────────
    # 1) CASH account — the $10k paper wallet. Manual + CIS_AUTO fills DEBIT cash on
    #    open (balance -= size) and CREDIT proceeds on close (balance += exit_value),
    #    so `balance` already embeds realized P&L → equity = balance + value of OPEN
    #    cash positions. Adding total_pnl on top double-counts (old bug).
    # 2) SLEEVE (METER_REBAL) — a PURE NOTIONAL book on its own REBAL_SLEEVE_NAV; it
    #    NEVER touches the cash balance. Summing its notional open_value into the cash
    #    portfolio inflated it ($36.9k on a $10k start — 2026-07-15 Loop Watch). Report
    #    it as its own book with a % return on NAV.
    def _is_sleeve(p) -> bool:
        return (p.get("strategy") or "") == REBAL_SLEEVE_TAG
    _cv = lambda p: p.get("current_value_usd", p.get("size_usd", 0)) or 0

    cash_open     = [p for p in open_ if not _is_sleeve(p)]
    sleeve_open   = [p for p in open_ if _is_sleeve(p)]
    sleeve_closed = [p for p in closed if _is_sleeve(p)]
    cash_open_value   = sum(_cv(p) for p in cash_open)
    sleeve_open_value = sum(_cv(p) for p in sleeve_open)
    sleeve_unreal     = sum((p.get("unrealized_pnl") or 0) for p in sleeve_open)
    sleeve_realized   = sum((p.get("realized_pnl") or 0) for p in sleeve_closed)
    sleeve_book = {
        "nav":                round(REBAL_SLEEVE_NAV, 2),
        "open_positions":     len(sleeve_open),
        "open_value_usd":     round(sleeve_open_value, 2),
        "unrealized_pnl_usd": round(sleeve_unreal, 2),
        "realized_pnl_usd":   round(sleeve_realized, 2),
        "return_pct":         round((sleeve_realized + sleeve_unreal) / REBAL_SLEEVE_NAV * 100, 3),
        "closed_trades":      len(sleeve_closed),
    }

    # Backfill macro_regime for legacy closed positions written before the
    # nested-regime fix (2026-06-19). Cheap when no work needed; bounded by
    # closed-position count. Result is in-place on `closed` list.
    backfilled = await _backfill_regime_from_history(closed)

    total_trades = len(closed)
    if total_trades == 0:
        return {
            "total_trades":     0,
            "win_rate":         None,
            "avg_return_pct":   None,
            "total_pnl_usd":    0,
            "total_pnl_pct":    0,
            "best_trade":       None,
            "worst_trade":      None,
            "cash_usd":         round(balance, 2),
            "open_positions":   len(cash_open),
            "open_value_usd":   round(cash_open_value, 2),
            "portfolio_usd":    round(balance + cash_open_value, 2),
            "sleeve":           sleeve_book,
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

    total_pnl  = sum(pnls)   # realized P&L across BOTH books (per-trade % is book-agnostic)

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
        "regime_backfilled": backfilled,   # how many legacy positions we recovered (0 on steady-state)
        # CASH account only — balance already embeds realized P&L (no double count),
        # sleeve notional excluded (reported under `sleeve`).
        "cash_usd":       round(balance, 2),
        "open_positions": len(cash_open),
        "open_value_usd": round(cash_open_value, 2),
        "portfolio_usd":  round(balance + cash_open_value, 2),
        "sleeve":         sleeve_book,
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
    unattributed = 0
    for t in trades:
        # S-122. This was `or "NEUTRAL"` — the third application of the same default
        # on one path (write, write, read). Folding untagged trades into NEUTRAL does
        # not merely add noise: NEUTRAL is the bucket whose accuracy is reported as
        # None, so the contamination is invisible in the output it corrupts. Count
        # them instead; a coverage number is information, a silent merge is not.
        sig = t.get("cis_signal")
        if not sig:
            unattributed += 1
            continue
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
    n_attributed = sum(len(v) for v in groups.values())
    return {"by_signal": accuracy,
            "n_attributed": n_attributed,
            "n_unattributed": unattributed,
            "coverage_pct": round(n_attributed / (n_attributed + unattributed) * 100, 1)
                            if (n_attributed + unattributed) else None}


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


# ── Telegram alert helpers (paper trading) ────────────────────────────────────
# Fires on every fill + every close, so Seth sees track record accumulate in
# the ops channel. notify_telegram is a no-op when TELEGRAM_BOT_TOKEN unset.

async def _notify_paper_fill(pos: dict) -> None:
    """Fire-and-forget Telegram alert on a paper fill. Safe to call via create_task."""
    try:
        regime = pos.get("macro_regime", "?")
        cis = pos.get("cis_score", 0)
        grade = pos.get("cis_grade", "?")
        signal = pos.get("cis_signal", "?")
        size = pos.get("size_usd", 0)
        entry = pos.get("entry_price", 0)
        sl = pos.get("stop_loss", 0)
        tp = pos.get("take_profit", 0)
        sl_pct = pos.get("stop_loss_pct", 0) * 100
        tp_pct = pos.get("take_profit_pct", 0) * 100
        source = pos.get("note", "").split("|")[0].strip() or "manual"

        text = (
            f"📈 PAPER FILL {pos.get('side','LONG')} {pos['symbol']}\n"
            f"  ${size:.0f} @ {entry:.4f}  |  SL ${sl:.4f} (-{sl_pct:.0f}%)  TP ${tp:.4f} (+{tp_pct:.0f}%)\n"
            f"  CIS {cis:.1f} ({grade}) {signal}  |  regime={regime}\n"
            f"  source: {source}\n"
            f"  order_id: {pos.get('order_id','?')[:12]}"
        )
        await notify_telegram(text)
    except Exception as e:
        _logger.warning(f"[TRADING] notify_paper_fill failed: {e}")


async def _notify_paper_close(pos: dict, pnl_pct: float, pnl_abs: float) -> None:
    """Fire-and-forget Telegram alert on a paper position close."""
    try:
        pnl_emoji = "🟢" if pnl_abs >= 0 else "🔴"
        text = (
            f"{pnl_emoji} PAPER CLOSE {pos['symbol']}\n"
            f"  exit ${pos.get('exit_price', 0):.4f}  |  P&L {pnl_pct:+.2f}% (${pnl_abs:+.2f})\n"
            f"  reason: {pos.get('exit_reason','?')}\n"
            f"  held: {pos.get('held_seconds', 0) / 3600:.1f}h"
        )
        await notify_telegram(text)
    except Exception as e:
        _logger.warning(f"[TRADING] notify_paper_close failed: {e}")
