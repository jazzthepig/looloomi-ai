"""
Quant router — Freqtrade dry-run monitoring + Mac Mini push
Endpoints:
  GET  /api/v1/quant/status    — current open trades, balance (from Redis cache)
  GET  /api/v1/quant/trades   — trade history
  GET  /api/v1/quant/equity   — equity curve
  GET  /api/v1/quant/backtest — backtest results (static JSON)
  POST /internal/quant-push    — Mac Mini pushes Freqtrade status (auth required)
"""
import os
import json
from datetime import datetime, timezone
from pathlib import Path
import logging
from fastapi import APIRouter, HTTPException, Header

from src.api.store import redis_set_key, redis_get_key, supabase_insert_batch

_logger = logging.getLogger(__name__)

router = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
_REDIS_KEY_STATUS = "quant:status"
_REDIS_KEY_TRADES = "quant:trades"
_REDIS_KEY_EQUITY = "quant:equity"
_REDIS_TTL = 300  # 5 minutes — stale data should be evident
_SB_TABLE = "trade_results"


# ── Trade result capture helpers (Simons Upgrade P0.1) ───────────────────────

def _trade_to_row(t: dict) -> dict | None:
    """
    Normalize a Freqtrade trade payload into a trade_results row.
    Returns None if required fields missing.
    """
    if not t.get("pair") or not t.get("open_time"):
        return None
    entry_ts = _parse_ts(t.get("open_time"))
    exit_ts = _parse_ts(t.get("close_time")) if t.get("close_time") else None
    return {
        "symbol":             t.get("pair", "").replace("_", "/"),
        "side":               t.get("side", "").upper() if t.get("side") else None,
        "entry_time":         entry_ts,
        "exit_time":          exit_ts,
        "entry_price":        t.get("open_rate"),
        "exit_price":         t.get("close_rate"),
        "profit_pct":         round(float(t["profit_ratio"]) * 100, 4) if t.get("profit_ratio") is not None else None,
        "profit_abs":         t.get("profit_abs"),
        "exit_reason":        t.get("exit_reason"),
        "enter_tag":          t.get("enter_tag"),
        "strategy":           t.get("strategy", "unknown"),
        "cis_score_at_entry": None,   # filled by Mac Mini before push if available
        "cis_grade_at_entry": None,
        "pillar_f_at_entry":  None,
        "pillar_m_at_entry":  None,
        "pillar_o_at_entry":  None,
        "pillar_s_at_entry":  None,
        "pillar_a_at_entry":  None,
        "macro_regime_at_entry": None,
        "realized_return_7d": None,   # filled after exit if 7d price data available
        "recorded_at":        datetime.now(timezone.utc).isoformat(),
    }


def _parse_ts(ts_str) -> str | None:
    """Parse Freqtrade timestamp to ISO string."""
    if not ts_str:
        return None
    try:
        if isinstance(ts_str, (int, float)):
            secs = ts_str
            if secs > 1e12:
                secs = secs / 1000
            dt = datetime.fromtimestamp(secs, tz=timezone.utc)
        else:
            s = str(ts_str)
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


# ── Internal push (Mac Mini → Railway) ───────────────────────────────────────

@router.post("/internal/quant-push")
async def receive_quant_status(payload: dict, x_internal_token: str = Header(None)):
    """
    Receives Freqtrade dry-run status from Mac Mini.
    Mac Mini polls Freqtrade REST API (port 18432) every 30s and pushes here.
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not payload:
        raise HTTPException(status_code=400, detail="Empty payload")

    # Extract the three data types
    status_data = payload.get("status", {})
    trades_data = payload.get("trades", [])
    equity_data = payload.get("equity", {})

    ts = datetime.now().isoformat()

    if status_data:
        await redis_set_key(_REDIS_KEY_STATUS, {**status_data, "_ts": ts}, ttl=_REDIS_TTL)
    if trades_data:
        # Append to trade history (keep last 100)
        existing = await redis_get_key(_REDIS_KEY_TRADES)
        if not isinstance(existing, list):
            existing = []
        updated = trades_data + existing
        await redis_set_key(_REDIS_KEY_TRADES, updated[:100], ttl=_REDIS_TTL * 10)

        # Simons Upgrade P0.1: write closed trades to Supabase trade_results
        # Only write closed trades (have close_time); open trades have no realized return yet
        closed_rows = []
        for t in trades_data:
            row = _trade_to_row(t)
            if row and row.get("exit_time"):  # closed trade
                # Enrich with CIS state if Mac Mini provided it
                if "cis_score_at_entry" not in t or t.get("cis_score_at_entry") is None:
                    # Mac Mini may not have provided CIS data — use payload enrichment if present
                    row["cis_score_at_entry"]   = t.get("cis_score_at_entry")
                    row["cis_grade_at_entry"]   = t.get("cis_grade_at_entry")
                    row["pillar_f_at_entry"]    = t.get("pillar_f_at_entry")
                    row["pillar_m_at_entry"]    = t.get("pillar_m_at_entry")
                    row["pillar_o_at_entry"]    = t.get("pillar_o_at_entry")
                    row["pillar_s_at_entry"]    = t.get("pillar_s_at_entry")
                    row["pillar_a_at_entry"]    = t.get("pillar_a_at_entry")
                    row["macro_regime_at_entry"] = t.get("macro_regime_at_entry")
                    row["realized_return_7d"]   = t.get("realized_return_7d")
                closed_rows.append(row)

        if closed_rows:
            ok = await supabase_insert_batch(closed_rows)
            _logger.info(f"[QUANT] Trade results write to Supabase: {ok} ({len(closed_rows)} closed trades)")
    if equity_data:
        await redis_set_key(_REDIS_KEY_EQUITY, {**equity_data, "_ts": ts}, ttl=_REDIS_TTL)

    count_status = 1 if status_data else 0
    count_trades = len(trades_data)
    _logger.info(f"[QUANT] Push received — status={count_status} trades={count_trades}")
    return {"ok": True, "timestamp": ts}


# ── Public endpoints (served to QuantMonitor page) ──────────────────────────

@router.get("/api/v1/quant/status")
async def get_quant_status():
    """
    Current dry-run trading status: open trades, balance, daily P&L.
    Data pushed by Mac Mini every 30s. Returns stale data with _stale flag if push missed.
    """
    data = await redis_get_key(_REDIS_KEY_STATUS)
    if not data:
        return {"open_trades": [], "balance": None, "daily_pnl": None, "_stale": True}

    ts = data.pop("_ts", None)
    return {
        "open_trades": data.get("open_trades", []),
        "balance": data.get("balance"),
        "daily_pnl": data.get("daily_pnl"),
        "updated": ts,
        "_stale": False,
    }


@router.get("/api/v1/quant/trades")
async def get_quant_trades(limit: int = 50):
    """Recent trade history from dry run."""
    trades = await redis_get_key(_REDIS_KEY_TRADES) or []
    return {
        "trades": trades[:limit],
        "count": len(trades),
    }


@router.get("/api/v1/quant/equity")
async def get_quant_equity():
    """Current equity and performance metrics."""
    data = await redis_get_key(_REDIS_KEY_EQUITY)
    if not data:
        return {"equity": None, "starting_balance": 10000, "_stale": True}
    ts = data.pop("_ts", None)
    return {
        "equity": data.get("equity"),
        "starting_balance": data.get("starting_balance", 10000),
        "updated": ts,
        "_stale": False,
    }


_BACKTEST_PATH = Path(__file__).parent.parent.parent / "data" / "quant" / "quant_backtest_results.json"


@router.get("/api/v1/quant/backtest")
async def get_quant_backtest():
    """Historical backtest results for CometCloudMultiFactorV2 strategy."""
    if not _BACKTEST_PATH.exists():
        raise HTTPException(status_code=404, detail="Backtest results not found")
    with open(_BACKTEST_PATH) as f:
        return json.load(f)
