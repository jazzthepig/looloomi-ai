"""
CIS Signal Journal — institutional-grade performance tracking.

Records every OUTPERFORM / STRONG OUTPERFORM threshold crossing as a
tradeable signal with entry price, tracks open positions, closes them
on downgrade, and computes empyrical risk metrics for the buy-side dashboard.

Endpoints:
  GET  /api/v1/signals/journal       — paginated signal history (open + closed)
  GET  /api/v1/signals/performance   — Sharpe, Sortino, CAGR, maxDD, win rate, equity curve
  GET  /api/v1/signals/summary       — quick KPI strip (cached 10 min)

Called internally by cis.py after /internal/cis-scores processing:
  log_cis_signals(assets, regime, prices)
  close_cis_signals(assets, prices)
"""
import os
import json
import logging
import math
import time
from datetime import datetime, timezone, timedelta

import httpx
import numpy as np

from fastapi import APIRouter, Query, Header, HTTPException, Response

_logger = logging.getLogger(__name__)
router  = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

# ── Config ────────────────────────────────────────────────────────────────────
_SB_URL    = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY    = os.environ.get("SUPABASE_KEY", "")
_SB_TABLE  = "signal_journal"

# Signal thresholds (same as CLAUDE.md CIS spec)
_OUTPERFORM_THRESH        = 60.0
_STRONG_OUTPERFORM_THRESH = 75.0
_EXIT_THRESH              = 52.0    # close when score falls below this
_STOP_LOSS_PCT            = -0.15   # close if unrealized < -15%
_MAX_HOLDING_DAYS         = 90      # force-close stale open signals

# Dedup: skip if open signal for same asset within N days
_DEDUP_DAYS = 3

# Redis cache key for performance metrics
_REDIS_PERF_KEY = "signals:performance"
_REDIS_PERF_TTL = 600   # 10 min

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10)
    return _client


def _sb_headers() -> dict:
    return {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }


def _safe(v):
    """Sanitize float for JSON (replace NaN/Inf with None)."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if not math.isfinite(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


# ── Supabase helpers ─────────────────────────────────────────────────────────

async def _sb_query(table: str, params: dict) -> list:
    """GET from Supabase PostgREST."""
    if not _SB_URL or not _SB_KEY:
        return []
    try:
        resp = await _get_client().get(
            f"{_SB_URL}/rest/v1/{table}",
            params=params,
            headers={
                "apikey":        _SB_KEY,
                "Authorization": f"Bearer {_SB_KEY}",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        _logger.warning(f"[SIGNALS] Supabase GET error: {e}")
    return []


async def _sb_insert(rows: list) -> bool:
    if not _SB_URL or not _SB_KEY or not rows:
        return False
    try:
        resp = await _get_client().post(
            f"{_SB_URL}/rest/v1/{_SB_TABLE}",
            content=json.dumps(rows),
            headers=_sb_headers(),
            timeout=8,
        )
        return resp.status_code in (200, 201)
    except Exception as e:
        _logger.warning(f"[SIGNALS] Insert error: {e}")
        return False


async def _sb_update(row_id: int, data: dict) -> bool:
    if not _SB_URL or not _SB_KEY:
        return False
    try:
        resp = await _get_client().patch(
            f"{_SB_URL}/rest/v1/{_SB_TABLE}",
            content=json.dumps(data),
            params={"id": f"eq.{row_id}"},
            headers=_sb_headers(),
            timeout=8,
        )
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        _logger.warning(f"[SIGNALS] Update error: {e}")
        return False


async def _get_open_signals() -> dict:
    """Fetch all open signals keyed by symbol (uppercase)."""
    rows = await _sb_query(_SB_TABLE, {
        "exit_date": "is.null",
        "select": "id,symbol,entry_price,cis_score,signal_date,signal",
        "order": "signal_date.desc",
        "limit": "200",
    })
    result = {}
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if sym and sym not in result:   # keep most recent open per symbol
            result[sym] = row
    return result


# ── Signal logging (called from cis.py) ─────────────────────────────────────

async def log_cis_signals(assets: list, regime: str, prices: dict) -> int:
    """
    Called after /internal/cis-scores push.
    Checks each asset — if OUTPERFORM and no recent open signal, logs entry.
    Also closes open signals for assets that have fallen below exit threshold.

    assets  — list of asset dicts from CIS universe
    regime  — current macro regime string
    prices  — dict {SYMBOL: current_price_usd}
    Returns count of new signals logged.
    """
    if not _SB_URL or not _SB_KEY:
        return 0

    open_signals = await _get_open_signals()
    now = datetime.now(timezone.utc)
    new_rows   = []
    close_ops  = []

    for asset in assets:
        sym    = (asset.get("symbol") or asset.get("asset_id") or "").upper()
        score  = asset.get("cis_score") or asset.get("score") or 0
        signal = asset.get("signal") or ""
        grade  = asset.get("grade") or ""

        if not sym:
            continue

        is_outperform = (
            "OUTPERFORM" in signal.upper() or score >= _OUTPERFORM_THRESH
        )
        is_strong = (
            "STRONG" in signal.upper() or score >= _STRONG_OUTPERFORM_THRESH
        )
        is_downgrade = (score < _EXIT_THRESH) and not is_outperform

        price = prices.get(sym) or prices.get(sym.lower())

        # ── Close open signal on downgrade ──────────────────────────────────
        if sym in open_signals and is_downgrade:
            open_row  = open_signals[sym]
            entry_px  = open_row.get("entry_price")
            ret_pct   = None
            if entry_px and price and entry_px > 0:
                ret_pct = round((price - entry_px) / entry_px * 100, 4)
            entry_dt  = open_row.get("signal_date")
            hold_days = None
            if entry_dt:
                try:
                    dt_entry = datetime.fromisoformat(entry_dt.replace("Z", "+00:00"))
                    hold_days = round((now - dt_entry).total_seconds() / 86400, 2)
                except Exception:
                    pass

            close_ops.append((open_row["id"], {
                "exit_price":  _safe(price),
                "exit_date":   now.isoformat(),
                "exit_reason": "DOWNGRADE",
                "return_pct":  _safe(ret_pct),
                "holding_days": _safe(hold_days),
            }))

        # ── Open new signal if not already open ─────────────────────────────
        elif is_outperform and sym not in open_signals:
            row = {
                "symbol":       sym,
                "asset_class":  asset.get("asset_class"),
                "grade":        grade,
                "signal":       "STRONG_OUTPERFORM" if is_strong else "OUTPERFORM",
                "cis_score":    _safe(score),
                "raw_cis_score": _safe(asset.get("raw_cis_score")),
                "las":          _safe(asset.get("las")),
                "pillar_f":     _safe(asset.get("pillar_f") or (asset.get("pillars") or {}).get("F") or asset.get("f")),
                "pillar_m":     _safe(asset.get("pillar_m") or (asset.get("pillars") or {}).get("M") or asset.get("m")),
                "pillar_o":     _safe(asset.get("pillar_o") or (asset.get("pillars") or {}).get("O") or asset.get("o")),
                "pillar_s":     _safe(asset.get("pillar_s") or (asset.get("pillars") or {}).get("S") or asset.get("s")),
                "pillar_a":     _safe(asset.get("pillar_a") or (asset.get("pillars") or {}).get("A") or asset.get("a")),
                "macro_regime": regime or asset.get("macro_regime"),
                "strategy":     "CIS_THRESHOLD",
                "data_tier":    asset.get("data_tier", 2),
                "entry_price":  _safe(price),
                "exit_price":   None,
                "exit_date":    None,
                "exit_reason":  None,
                "return_pct":   None,
                "holding_days": None,
                "signal_date":  now.isoformat(),
                "recorded_at":  now.isoformat(),
            }
            new_rows.append(row)

    # Execute inserts + closes
    inserted = 0
    if new_rows:
        ok = await _sb_insert(new_rows)
        if ok:
            inserted = len(new_rows)
            _logger.info(f"[SIGNALS] Logged {inserted} new signals (regime={regime})")
        else:
            _logger.warning("[SIGNALS] Signal insert failed")

    for row_id, update_data in close_ops:
        ok = await _sb_update(row_id, update_data)
        if ok:
            sym_closed = next(
                (r["symbol"] for r in open_signals.values() if r.get("id") == row_id), "?"
            )
            _logger.info(f"[SIGNALS] Closed signal id={row_id} sym={sym_closed} reason=DOWNGRADE ret={update_data.get('return_pct')}%")

    return inserted


# ── Performance computation ───────────────────────────────────────────────────

def _compute_metrics(closed: list, open_signals: list) -> dict:
    """
    Compute institutional-grade performance metrics from signal history.
    Uses empyrical if available; falls back to numpy implementation.
    """
    if not closed:
        return {
            "status": "building",
            "message": "Accumulating signal history — metrics available after first closed positions.",
            "total_signals": len(open_signals),
            "open_signals":  len(open_signals),
            "closed_signals": 0,
            "outcome_30d_count": 0,
            "outcome_30d_pending": len(open_signals),
        }

    # Sanitize: a closed signal whose price feed returned 0 produces a -100% sentinel
    # (the known price=0 artifact). Drop those and clip extremes so one bad data point
    # can't masquerade as a -94% blow-up. Keep only economically plausible returns.
    _raw = [r["return_pct"] for r in closed
            if r.get("return_pct") is not None and r["return_pct"] > -99.0]
    returns = np.array([max(-90.0, min(500.0, float(x))) / 100.0 for x in _raw])
    if len(returns) == 0:
        return {"status": "building", "message": "Waiting for valid price data on closed signals.", "total_signals": len(closed) + len(open_signals)}

    wins        = returns[returns > 0]
    losses      = returns[returns <= 0]
    win_rate    = round(len(wins) / len(returns) * 100, 1)
    avg_return  = round(float(np.mean(returns)) * 100, 3)
    avg_win     = round(float(np.mean(wins)) * 100, 3) if len(wins) else 0
    avg_loss    = round(float(np.mean(losses)) * 100, 3) if len(losses) else 0

    # Profit factor = gross profit / gross loss
    gross_profit = float(np.sum(wins)) if len(wins) else 0
    gross_loss   = abs(float(np.sum(losses))) if len(losses) else 0
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

    # Equity curve — each signal sized as an equal slug of a diversified book, NOT a
    # full-notional sequential bet. Compounding each signal at 100% notional made one
    # bad signal wipe the curve (the -94% artifact). A signal-following book holds many
    # positions concurrently; model each as a fixed fraction so the curve reflects the
    # set's efficacy, not a single name's blow-up.
    POSITION_FRAC = 0.10
    equity_curve = []
    equity = 100_000.0
    peak   = equity
    max_dd = 0.0
    for r in returns:
        equity = equity * (1.0 + POSITION_FRAC * r)
        peak   = max(peak, equity)
        dd     = (equity - peak) / peak
        max_dd = min(max_dd, dd)
        equity_curve.append(round(equity, 2))

    # CAGR — annualized from first to last signal
    dates = [r["signal_date"] for r in closed if r.get("signal_date")]
    cagr  = None
    if len(dates) >= 2:
        try:
            dt0 = datetime.fromisoformat(dates[-1].replace("Z", "+00:00"))
            dt1 = datetime.fromisoformat(dates[0].replace("Z", "+00:00"))
            years = (dt1 - dt0).total_seconds() / (365.25 * 86400)
            if years > 0.05 and equity_curve:
                cagr = round((equity_curve[-1] / 100_000) ** (1 / years) - 1, 4)
        except Exception:
            pass

    # Per-signal Sharpe — mean / std of trade returns. NOTE: these are sparse,
    # event-driven signal returns, NOT daily periods, so we do NOT annualize.
    # (QA 2026-06-05: the old sqrt(252)/empyrical period="daily" annualization
    # exploded this to -24.5 — a nonsensical magnitude.) This reports a unitless
    # per-trade risk-adjusted return, which is the honest metric for a signal log.
    sharpe = None
    if len(returns) >= 5 and np.std(returns) > 0:
        sharpe = round(float(np.mean(returns) / np.std(returns)), 3)

    # Per-signal Sortino — mean / downside deviation (no annualization, same reason)
    sortino = None
    if len(returns) >= 5:
        neg = returns[returns < 0]
        if len(neg) > 0 and np.std(neg) > 0:
            sortino = round(float(np.mean(returns) / np.std(neg)), 3)

    # Calmar — CAGR / |maxDD|
    calmar = None
    if cagr is not None and max_dd < 0:
        calmar = round(cagr / abs(max_dd), 3)

    # Attribution by regime
    by_regime: dict = {}
    for r in closed:
        reg = r.get("macro_regime") or "Unknown"
        ret = r.get("return_pct")
        if ret is None:
            continue
        if reg not in by_regime:
            by_regime[reg] = {"returns": [], "count": 0}
        by_regime[reg]["returns"].append(ret)
        by_regime[reg]["count"] += 1

    regime_stats = {}
    for reg, v in by_regime.items():
        rets = np.array(v["returns"])
        regime_stats[reg] = {
            "avg_return_pct": round(float(np.mean(rets)), 2),
            "win_rate_pct":   round(len(rets[rets > 0]) / len(rets) * 100, 1),
            "trade_count":    v["count"],
        }

    # Attribution by asset class
    by_class: dict = {}
    for r in closed:
        cls = r.get("asset_class") or "Unknown"
        ret = r.get("return_pct")
        if ret is None:
            continue
        if cls not in by_class:
            by_class[cls] = {"returns": [], "count": 0}
        by_class[cls]["returns"].append(ret)
        by_class[cls]["count"] += 1

    class_stats = {}
    for cls, v in by_class.items():
        rets = np.array(v["returns"])
        class_stats[cls] = {
            "avg_return_pct": round(float(np.mean(rets)), 2),
            "win_rate_pct":   round(len(rets[rets > 0]) / len(rets) * 100, 1),
            "trade_count":    v["count"],
        }

    # Attribution by grade
    by_grade: dict = {}
    for r in closed:
        g   = r.get("grade") or "?"
        ret = r.get("return_pct")
        if ret is None:
            continue
        if g not in by_grade:
            by_grade[g] = {"returns": [], "count": 0}
        by_grade[g]["returns"].append(ret)
        by_grade[g]["count"] += 1

    grade_stats = {}
    for g, v in by_grade.items():
        rets = np.array(v["returns"])
        grade_stats[g] = {
            "avg_return_pct": round(float(np.mean(rets)), 2),
            "win_rate_pct":   round(len(rets[rets > 0]) / len(rets) * 100, 1),
            "trade_count":    v["count"],
        }

    # ── 30d outcome metrics ──────────────────────────────────────────────
    #outcome_30d signals: those with outcome_30d set (computed by signal_outcome_tracker)
    resolved_signals = [r for r in closed if r.get("outcome_30d") in ("WIN", "LOSS", "EXPIRED")]
    pending_signals  = [r for r in open_signals if not r.get("outcome_30d")]
    out_wins   = [r for r in resolved_signals if r.get("outcome_30d") == "WIN"]
    out_losses = [r for r in resolved_signals if r.get("outcome_30d") == "LOSS"]
    out_exp    = [r for r in resolved_signals if r.get("outcome_30d") == "EXPIRED"]

    out_count     = len(resolved_signals)
    out_win_rate  = round(len(out_wins) / out_count * 100, 1) if out_count > 0 else None
    out_avg_ret   = round(float(np.mean([r.get("return_pct_30d", 0) for r in resolved_signals])) / 100.0 * 100, 3) if resolved_signals else None
    # Benchmark-relative: WIN/LOSS now reflect alpha vs benchmark (BTC/SPY), not absolute
    # return — an OUTPERFORM signal is a relative claim (see outcome_tracker.py).
    _alphas = [r.get("alpha_30d") for r in resolved_signals if r.get("alpha_30d") is not None]
    out_avg_alpha = round(float(np.mean(_alphas)), 3) if _alphas else None

    outcome_stats = {
        "outcome_30d_count":     out_count,
        "outcome_30d_win_rate":  out_win_rate,          # now benchmark-relative
        "outcome_30d_basis":     "benchmark_relative" if _alphas else "absolute",
        "outcome_30d_avg_return": out_avg_ret,          # absolute, reference
        "outcome_30d_avg_alpha":  out_avg_alpha,        # avg outperformance vs benchmark
        "outcome_30d_wins":       len(out_wins),
        "outcome_30d_losses":     len(out_losses),
        "outcome_30d_expired":    len(out_exp),
        "outcome_30d_pending":    len(pending_signals) + sum(1 for r in closed if r.get("outcome_30d") is None and r.get("return_pct") is None),
    }

    # Equity curve with dates for chart
    equity_series = []
    eq = 100_000.0
    for r in closed:
        ret = r.get("return_pct")
        if ret is None:
            continue
        eq  = eq * (1 + ret / 100.0)
        equity_series.append({
            "date":   r.get("exit_date") or r.get("signal_date"),
            "equity": round(eq, 2),
            "symbol": r.get("symbol"),
            "return": ret,
        })

    avg_holding = None
    hold_days = [r.get("holding_days") for r in closed if r.get("holding_days") is not None]
    if hold_days:
        avg_holding = round(float(np.mean(hold_days)), 1)

    return {
        "status":          "live",
        "as_of":           datetime.now(timezone.utc).isoformat(),
        # Core KPIs
        "sharpe":          sharpe,
        "sortino":         sortino,
        "cagr_pct":        round(cagr * 100, 2) if cagr is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar":          calmar,
        "win_rate_pct":    win_rate,
        "profit_factor":   profit_factor,
        "avg_return_pct":  avg_return,
        "avg_win_pct":     avg_win,
        "avg_loss_pct":    avg_loss,
        "avg_holding_days": avg_holding,
        # Signal counts
        "total_signals":   len(closed) + len(open_signals),
        "closed_signals":  len(closed),
        "open_signals":    len(open_signals),
        "winning_signals": int(len(wins)),
        "losing_signals":  int(len(losses)),
        # Equity
        "starting_equity": 100_000,
        "current_equity":  round(equity_curve[-1], 2) if equity_curve else 100_000,
        "equity_series":   equity_series[-120:],   # last 120 data points for chart
        # Attribution
        "by_regime":       regime_stats,
        "by_class":        class_stats,
        "by_grade":        grade_stats,
        # 30d outcome metrics (populated by signal_outcome_tracker.py after 30d)
        **outcome_stats,
        # Honest methodology framing (QA 2026-06-05). Closed-signal returns here
        # come from the DOWNGRADE-CLOSE path: a signal closes when its score falls
        # below the exit threshold. Winners that never downgrade stay open, so this
        # sample is selection-biased toward losers and is NOT a clean track record.
        # The forward, unbiased metric is the 30-day fixed-horizon outcome
        # (outcome_30d_*), which only becomes meaningful once signals mature
        # (first signals logged 2026-05-25 → first 30d outcomes ~2026-06-24).
        "methodology": {
            "closed_basis": "downgrade_close",
            "closed_basis_note": "selection-biased toward losers; not a track record",
            "forward_metric": "outcome_30d (30-day fixed horizon)",
            "forward_metric_ready": out_count >= 10,
            "forward_metric_first_resolves": "2026-06-24",
        },
    }


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("/api/v1/signals/journal")
async def get_signal_journal(
    limit: int  = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default="all"),    # all | open | closed
    symbol: str = Query(default=None),
):
    """
    Paginated signal history with open/closed filter.
    Returns latest signals first.
    """
    params = {
        "order":  "signal_date.desc",
        "limit":  str(limit),
        "offset": str(offset),
        "select": "id,symbol,asset_class,grade,signal,cis_score,macro_regime,strategy,data_tier,entry_price,exit_price,exit_date,exit_reason,return_pct,holding_days,signal_date",
    }
    if status == "open":
        params["exit_date"] = "is.null"
    elif status == "closed":
        params["exit_date"] = "not.is.null"
    if symbol:
        params["symbol"] = f"eq.{symbol.upper()}"

    rows = await _sb_query(_SB_TABLE, params)
    return {
        "signals": rows,
        "count":   len(rows),
        "offset":  offset,
        "limit":   limit,
        "filter":  status,
    }


@router.get("/api/v1/signals/performance")
async def get_signal_performance():
    """
    Institutional-grade performance metrics computed from signal_journal.
    Sharpe, Sortino, CAGR, max drawdown, win rate, profit factor, equity curve.
    Cached 10 minutes in Redis.
    """
    # Try Redis cache first
    try:
        from src.api.store import redis_get_key, redis_set_key
        cached = await redis_get_key(_REDIS_PERF_KEY)
        if cached and cached.get("status") == "live":
            age = int(time.time()) - cached.get("_cached_at", 0)
            if age < _REDIS_PERF_TTL:
                return {**cached, "cache_age_s": age}
    except Exception:
        pass

    # Fetch closed signals (last 180 days, ordered oldest→newest for equity curve)
    closed = await _sb_query(_SB_TABLE, {
        "exit_date": "not.is.null",
        "order":     "signal_date.asc",
        "limit":     "500",
        "select":    "id,symbol,asset_class,grade,signal,cis_score,macro_regime,return_pct,holding_days,signal_date,exit_date,exit_reason,entry_price,exit_price,outcome_30d,return_pct_30d,alpha_30d,benchmark_symbol",
    })

    # Fetch open signals
    open_rows = await _sb_query(_SB_TABLE, {
        "exit_date": "is.null",
        "order":     "signal_date.desc",
        "limit":     "100",
        "select":    "id,symbol,asset_class,grade,signal,cis_score,macro_regime,entry_price,signal_date,outcome_30d",
    })

    result = _compute_metrics(closed, open_rows)
    result["_cached_at"] = int(time.time())

    # Cache result
    try:
        from src.api.store import redis_set_key
        await redis_set_key(_REDIS_PERF_KEY, result, ttl=_REDIS_PERF_TTL)
    except Exception:
        pass

    return result


@router.post("/internal/run-outcome-tracker")
async def run_outcome_tracker_endpoint(
    dry_run: bool = Query(default=False),
    limit: int = Query(default=500, le=2000),
    x_internal_token: str = Header(None),
):
    """
    Resolve 30-day directional outcomes for matured signals (WIN/LOSS/EXPIRED).
    Internal-only — guarded by INTERNAL_TOKEN. Idempotent; safe to call repeatedly.
    Also runs automatically once/day via the startup background task.
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.data.signals.outcome_tracker import run_outcome_tracker
    result = await run_outcome_tracker(dry_run=dry_run, limit=limit)
    # bust the cached performance metrics so the new outcomes surface immediately
    if not dry_run and result.get("rows_written"):
        try:
            from src.api.store import redis_set_key
            await redis_set_key(_REDIS_PERF_KEY, {"status": "stale"}, ttl=1)
        except Exception:
            pass
    return result


@router.get("/api/v1/signals/summary")
async def get_signal_summary():
    """
    Lightweight KPI strip — for embedding in other pages.
    Cached in Redis; fast response.
    """
    perf = await get_signal_performance()
    return {
        "status":          perf.get("status"),
        "sharpe":          perf.get("sharpe"),
        "sortino":         perf.get("sortino"),
        "cagr_pct":        perf.get("cagr_pct"),
        "max_drawdown_pct": perf.get("max_drawdown_pct"),
        "win_rate_pct":    perf.get("win_rate_pct"),
        "profit_factor":   perf.get("profit_factor"),
        "total_signals":   perf.get("total_signals"),
        "open_signals":    perf.get("open_signals"),
        "closed_signals":  perf.get("closed_signals"),
        "current_equity":  perf.get("current_equity"),
        "as_of":           perf.get("as_of"),
    }


@router.get("/api/v1/signals/track-record")
async def get_signal_track_record(response: Response = None):
    """
    The honest, defensible track record: 30-day BENCHMARK-RELATIVE outcomes of our
    OUTPERFORM signals, computed entirely from our own data (cis_scores × ohlcv_daily),
    refreshed daily. The finding: the edge is the top-conviction tier — STRONG OUTPERFORM
    on A/A+ delivered positive alpha; the broad OUTPERFORM tier did not. Consuming agents
    and investor pages should cite THIS, with the tier breakdown, not a blended headline.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=1800, stale-while-revalidate=3600"
    from src.api.store import supabase_get_latest_track_record
    rows = await supabase_get_latest_track_record()

    def _agg(rs):
        n = sum(int(r.get("n") or 0) for r in rs)
        if not n:
            return None
        wa = sum(float(r.get("avg_alpha_pct") or 0) * int(r.get("n") or 0) for r in rs) / n
        ww = sum(float(r.get("alpha_win_pct") or 0) * int(r.get("n") or 0) for r in rs) / n
        return {"n": n, "avg_alpha_pct": round(wa, 2), "alpha_win_pct": round(ww, 1)}

    strong = [r for r in rows if str(r.get("signal") or "").upper() == "STRONG OUTPERFORM"]
    plain  = [r for r in rows if str(r.get("signal") or "").upper() == "OUTPERFORM"]
    return {
        "basis": "30d benchmark-relative alpha (BTC for crypto / SPY for TradFi), from own data (cis_scores × ohlcv_daily)",
        "tiers": rows,
        "headline": {
            "STRONG_OUTPERFORM": _agg(strong),   # the proven edge
            "OUTPERFORM_broad":  _agg(plain),     # the noise tier — shown for honesty
        },
        "note": "Observational signal→30d outcome (validates the signal), not live-traded P&L. "
                "Size on the top-conviction tier; the broad tier is watchlist, not position.",
        "compliance": "Positioning language only; not investment advice.",
    }
