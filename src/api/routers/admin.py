"""
Admin / observability router — data-landing audit + internal triggers.

The 2026-06-14 data-landing task force added three missing tables
(cis_backtest_results, cis_regime_fitness, ohlcv_daily) and now wires
endpoints that:
  1. Audit all known persistence tables in one place
  2. Trigger the regime-fitness compute from Railway (independent of Mac Mini)
  3. Manually nudge the OHLCV collector when the daily loop is stuck

Public read (no secrets leaked): /api/v1/admin/data-landing
Internal trigger (INTERNAL_TOKEN guarded):
  POST /internal/regime-fitness
  POST /internal/ohlcv-collect
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Header

_logger = logging.getLogger(__name__)
router = APIRouter()

_SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.environ.get("SUPABASE_KEY", "") or os.environ.get("SUPABASE_SERVICE_KEY", "")
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


# ── Tables we track ─────────────────────────────────────────────────────────
# Each entry: key, table, freshness window (seconds) for "healthy" verdict,
# and a "kind" tag for the audit summary.
_TABLES = [
    {"key": "cis_scores",            "table": "cis_scores",            "freshness_s": 86400,    "kind": "core",  "description": "CIS daily snapshot (T1+T2)"},
    {"key": "macro_briefs",          "table": "macro_briefs",          "freshness_s": 86400,    "kind": "core",  "description": "Macro brief history (Mac + template fallback)"},
    {"key": "signal_journal",        "table": "signal_journal",        "freshness_s": 86400,    "kind": "track", "description": "OUTPERFORM threshold crossings — track record"},
    {"key": "trade_results",         "table": "trade_results",         "freshness_s": 604800,   "kind": "track", "description": "Freqtrade fills (closed loop)"},
    {"key": "agent_call_log",        "table": "agent_call_log",        "freshness_s": 86400,    "kind": "infra", "description": "MCP tool usage"},
    {"key": "cis_backtest_results",  "table": "cis_backtest_results",  "freshness_s": 604800,   "kind": "track", "description": "Backtest runs by grade"},
    {"key": "cis_regime_fitness",    "table": "cis_regime_fitness",    "freshness_s": 86400,    "kind": "track", "description": "Pearson IC per pillar × regime (Simons loop)"},
    {"key": "ohlcv_daily",           "table": "ohlcv_daily",           "freshness_s": 86400,    "kind": "core",  "description": "Daily candles (CoinGecko Pro market_chart)"},
    {"key": "wallet_profiles",       "table": "wallet_profiles",       "freshness_s": None,     "kind": "auth",  "description": "Solana wallet auth profiles"},
    {"key": "leads",                 "table": "leads",                 "freshness_s": None,     "kind": "auth",  "description": "Investor leads"},
    {"key": "vault_deposit_intents", "table": "vault_deposit_intents", "freshness_s": None,     "kind": "auth",  "description": "Vault deposit memos"},
    {"key": "api_keys",              "table": "api_keys",              "freshness_s": None,     "kind": "infra", "description": "Self-serve API keys"},
    {"key": "webhook_subscriptions", "table": "webhook_subscriptions", "freshness_s": None,     "kind": "infra", "description": "Webhook subscribers"},
    {"key": "analytics_events",      "table": "analytics_events",      "freshness_s": None,     "kind": "infra", "description": "Self-hosted analytics"},
]


def _sb_headers() -> dict:
    return {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}


async def _probe_table(client: httpx.AsyncClient, table: str) -> dict:
    """
    Returns {count, last_write, error?} for a table by hitting
    Prefer: count=exact and selecting a tiny row.
    Fast — single round-trip for count, one more for last_write.
    Accepts 200 AND 206 (Supabase returns 206 for partial content with count=exact).
    """
    if not _SB_URL or not _SB_KEY:
        return {"count": None, "last_write": None, "error": "supabase_not_configured"}
    # Heuristic timestamp column — first one that succeeds wins
    ts_candidates = ("recorded_at", "run_at", "computed_at",
                     "created_at", "signal_date", "last_seen")
    try:
        # count — use * to avoid id-only / wallet_address-only column issues
        r_count = await client.get(
            f"{_SB_URL}/rest/v1/{table}",
            params={"select": "*", "limit": "1"},
            headers={**_sb_headers(), "Prefer": "count=exact"},
            timeout=10,
        )
        count = None
        if r_count.status_code in (200, 206):
            cr = r_count.headers.get("content-range", "")
            if "/" in cr:
                try:
                    count = int(cr.rsplit("/", 1)[1])
                except Exception:
                    count = None
            else:
                try:
                    count = len(r_count.json())
                except Exception:
                    count = None
        else:
            return {"count": None, "last_write": None, "error": f"http_{r_count.status_code}"}

        # last_write — try each ts col until one returns 200
        last_write = None
        for ts_col in ts_candidates:
            r_last = await client.get(
                f"{_SB_URL}/rest/v1/{table}",
                params={"select": ts_col, "order": f"{ts_col}.desc", "limit": "1"},
                headers=_sb_headers(),
                timeout=10,
            )
            if r_last.status_code == 200 and r_last.json():
                last_write = r_last.json()[0].get(ts_col)
                break
        return {"count": count, "last_write": last_write}
    except Exception as e:
        return {"count": None, "last_write": None, "error": str(e)[:120]}


# ── Audit endpoint ──────────────────────────────────────────────────────────
@router.get("/api/v1/admin/data-landing")
async def data_landing_audit():
    """
    One-shot audit of every known persistence table.

    Returns per-table {count, last_write, healthy, age_seconds, kind, description}
    plus an overall verdict: how many tables are healthy vs stale vs empty.
    Public read — only metadata, no secrets.
    """
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="supabase not configured")

    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=15) as client:
        results = await asyncio.gather(*[_probe_table(client, t["table"]) for t in _TABLES])

    tables_out = []
    healthy = 0
    stale = 0
    empty = 0
    error = 0
    for t, r in zip(_TABLES, results):
        cnt = r.get("count")
        lw = r.get("last_write")
        age = None
        is_healthy = None
        freshness = t.get("freshness_s")
        if r.get("error"):
            verdict = "error"
            error += 1
        elif cnt == 0 or cnt is None:
            verdict = "empty"
            empty += 1
        else:
            if lw:
                try:
                    lw_dt = datetime.fromisoformat(str(lw).replace("Z", "+00:00"))
                    age = round((now - lw_dt).total_seconds(), 1)
                except Exception:
                    age = None
            if freshness is None:
                # No freshness expectation (auth/infra tables — count is what matters)
                verdict = "ok" if (cnt and cnt > 0) else "empty"
                if verdict == "ok":
                    healthy += 1
            elif age is None:
                verdict = "stale"
                stale += 1
            elif age <= freshness:
                verdict = "healthy"
                healthy += 1
            elif age <= freshness * 2:
                verdict = "stale"
                stale += 1
            else:
                verdict = "very_stale"
                stale += 1
        tables_out.append({
            "key":         t["key"],
            "table":       t["table"],
            "kind":        t["kind"],
            "description": t["description"],
            "count":       cnt,
            "last_write":  lw,
            "age_seconds": age,
            "freshness_s": freshness,
            "verdict":     verdict,
            "error":       (r.get("error") if r.get("error") else None),
        })

    # Overall
    if error:
        overall = "degraded"
    elif empty > 4:
        overall = "missing_tables"
    elif stale > 2:
        overall = "stale"
    elif healthy >= 8:
        overall = "healthy"
    else:
        overall = "ok"

    return {
        "overall":  overall,
        "as_of":    now.isoformat(),
        "totals":   {"healthy": healthy, "stale": stale, "empty": empty, "error": error},
        "tables":   tables_out,
        "note":     "verdict=healthy means data is fresh. empty=table exists but zero rows. very_stale=age > 2× expected.",
    }


# ── Internal: trigger regime fitness compute ───────────────────────────────
@router.post("/internal/regime-fitness")
async def trigger_regime_fitness(x_internal_token: str = Header(None),
                                 window_days: int = 90,
                                 dry_run: bool = False):
    """
    Wraps scripts/compute_regime_fitness.py as an internal Railway endpoint.
    Runs the same logic the Mac Mini cron would, but inserts directly to
    cis_regime_fitness via Supabase REST. INTERNAL_TOKEN guarded.
    """
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        from scripts.compute_regime_fitness import (
            fetch_historical_rows, fetch_trade_results, compute_7d_returns,
            compute_fitness, sb_post,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"import failed: {e}")

    try:
        rows = fetch_historical_rows(window_days)
        trades = fetch_trade_results(window_days)
        enriched = compute_7d_returns(rows, trades)
        fitness = compute_fitness(enriched, window_days)
        if not fitness:
            return {"ok": True, "rows": 0, "note": "no fitness rows computed (insufficient data)"}

        if dry_run:
            return {"ok": True, "dry_run": True, "would_insert": len(fitness), "sample": fitness[:3]}

        ok = sb_post("cis_regime_fitness", fitness)
        return {
            "ok":       bool(ok),
            "rows":     len(fitness),
            "window_days": window_days,
            "sample":   fitness[:3],
        }
    except Exception as e:
        _logger.error(f"[REGIME_FITNESS] compute failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)[:200])


# ── Internal: trigger OHLCV daily collection ───────────────────────────────
@router.post("/internal/ohlcv-collect")
async def trigger_ohlcv_collect(x_internal_token: str = Header(None),
                                symbols: str = "",
                                days: int = 365):
    """
    One-shot OHLCV collection for given symbols (comma-separated) or default
    84-asset universe. Writes to ohlcv_daily via Supabase REST.
    INTERNAL_TOKEN guarded.
    """
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        from src.api.routers.ohlcv import collect_ohlcv
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ohlcv module not built yet: {e}")

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None

    # Deep backfills (large windows) can exceed the gateway timeout — run them in the
    # background and return immediately. Short top-ups stay synchronous (caller wants the result).
    if days > 800:
        import asyncio
        asyncio.create_task(collect_ohlcv(symbols=sym_list, days=days))
        return {"ok": True, "started": True, "background": True, "days": days,
                "symbols": len(sym_list) if sym_list else "universe",
                "note": "deep backfill running in background; check /api/v1/ohlcv/coverage"}

    res = await collect_ohlcv(symbols=sym_list, days=days)
    return res
