"""
OHLCV daily collector — Railway-side safety net for backtest + outcome
resolution. Mirrors the role of the Mac Mini /Volumes/.../ohlcv/ parquet
library but persists to Supabase ohlcv_daily (no volume footprint on
Railway — short rows, indexed by symbol+date).

Sources (in order of preference):
  1. CoinGecko Pro /coins/{id}/market_chart/range — crypto, 84 assets
  2. yfinance daily history — TradFi (US Equity, Bond, Commodity, FX, REIT, EM)

Endpoints:
  POST /internal/ohlcv-collect       — manual trigger (admin.py delegates here)
  GET  /api/v1/ohlcv/{symbol}        — public read of last N daily candles
  GET  /api/v1/ohlcv/coverage        — coverage report (per-symbol row counts)

Loop wiring lives in main.py (`_ohlcv_collector_loop`) — daily, gated to
~03:00 UTC so it doesn't fight the morning snapshot.
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta, date

import httpx
from fastapi import APIRouter, Query, HTTPException

_logger = logging.getLogger(__name__)
router = APIRouter()

_SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.environ.get("SUPABASE_KEY", "") or os.environ.get("SUPABASE_SERVICE_KEY", "")

# Lazy imports to avoid heavy cost on startup
def _universe():
    """Return the canonical ASSETS_CONFIG dict from cis_provider."""
    from src.data.cis.cis_provider import ASSETS_CONFIG
    return ASSETS_CONFIG


def _sb_headers(write: bool = False) -> dict:
    h = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    if write:
        h["Content-Type"] = "application/json"
        h["Prefer"] = "resolution=ignore-duplicates,return=minimal"
    return h


# ── Helpers ────────────────────────────────────────────────────────────────
async def _upsert_ohlcv(client: httpx.AsyncClient, rows: list) -> int:
    """Upsert rows to ohlcv_daily. Returns count accepted."""
    if not _SB_URL or not _SB_KEY or not rows:
        return 0
    try:
        # chunk to avoid oversized bodies
        CHUNK = 500
        total = 0
        for i in range(0, len(rows), CHUNK):
            chunk = rows[i:i+CHUNK]
            r = await client.post(
                f"{_SB_URL}/rest/v1/ohlcv_daily",
                content=json.dumps(chunk),
                headers=_sb_headers(write=True),
                timeout=30,
            )
            if r.status_code in (200, 201):
                total += len(chunk)
            else:
                _logger.warning(f"[OHLCV] upsert chunk failed: {r.status_code} {r.text[:120]}")
        return total
    except Exception as e:
        _logger.warning(f"[OHLCV] upsert error: {e}")
        return 0


async def _fetch_cg_daily(client: httpx.AsyncClient, coin_id: str, days: int) -> list:
    """Fetch daily candles from CoinGecko Pro market_chart/range."""
    try:
        from src.data.market.data_layer import get_cg_market_chart_range, get_cg_price_history
        # Use the range endpoint to bound the window precisely
        now = int(datetime.now(timezone.utc).timestamp())
        frm = now - days * 86400
        hist = await get_cg_market_chart_range(coin_id, frm, now)
        if not hist.get("available"):
            # Fall back to the days endpoint
            hist = await get_cg_price_history(coin_id, days)
        prices = hist.get("prices") or []
        volumes = hist.get("volumes") or []
        # index volumes by date for join
        vol_by_date = {}
        for v in volumes:
            if len(v) >= 2:
                try:
                    d = datetime.fromtimestamp(float(v[0]) / 1000, tz=timezone.utc).date()
                    vol_by_date[d] = float(v[1])
                except Exception:
                    continue
        out = []
        for row in prices:
            if len(row) < 2:
                continue
            try:
                ts_ms = float(row[0]); px = float(row[1])
            except (TypeError, ValueError):
                continue
            d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
            out.append({
                "trade_date": d.isoformat(),
                "open":  px,    # market_chart returns price points, not true OHLC — use point as both
                "high":  px,
                "low":   px,
                "close": px,
                "volume": vol_by_date.get(d),
            })
        return out
    except Exception as e:
        _logger.warning(f"[OHLCV] CG daily fetch {coin_id} failed: {e}")
        return []


async def _fetch_yf_daily(client_unused, symbol: str, days: int) -> list:
    """Fetch daily candles via yfinance (sync, run in thread)."""
    def _sync():
        try:
            import yfinance as yf
            end = datetime.now(timezone.utc).date()
            start = end - timedelta(days=days)
            t = yf.Ticker(symbol)
            hist = t.history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)
            if hist is None or hist.empty:
                return []
            out = []
            for idx, row in hist.iterrows():
                try:
                    d = idx.date() if hasattr(idx, "date") else idx
                    out.append({
                        "trade_date": d.isoformat(),
                        "open":  float(row.get("Open", 0) or 0),
                        "high":  float(row.get("High", 0) or 0),
                        "low":   float(row.get("Low",  0) or 0),
                        "close": float(row.get("Close",0) or 0),
                        "volume": float(row.get("Volume", 0) or 0),
                    })
                except Exception:
                    continue
            return out
        except Exception as e:
            _logger.warning(f"[OHLCV] yfinance {symbol} failed: {e}")
            return []
    return await asyncio.to_thread(_sync)


# ── Public collector function (called by /internal/ohlcv-collect + daily loop) ──
async def collect_ohlcv(symbols: list = None, days: int = 365) -> dict:
    """
    Pull `days` of daily candles for `symbols` (or full universe if None)
    and upsert into ohlcv_daily. Returns a per-symbol summary.
    """
    if not _SB_URL or not _SB_KEY:
        return {"ok": False, "error": "supabase_not_configured"}

    cfg = _universe()
    todo = symbols or list(cfg.keys())
    started = datetime.now(timezone.utc)
    rows_total = 0
    per_symbol = []
    sem = asyncio.Semaphore(8)   # CG Pro rate-limited; 8 concurrent is safe

    async with httpx.AsyncClient(timeout=30) as client:
        async def _one(sym: str):
            nonlocal rows_total
            async with sem:
                c = cfg.get(sym, {})
                asset_class = c.get("class", "Unknown")
                cg_id = c.get("coingecko")
                yf_sym = c.get("yfinance")
                rows_in: list = []
                source_used = None
                if cg_id:
                    rows_in = await _fetch_cg_daily(client, cg_id, days)
                    source_used = "coingecko"
                if not rows_in and yf_sym:
                    rows_in = await _fetch_yf_daily(client, yf_sym, days)
                    source_used = "yfinance"
                if not rows_in:
                    return {"symbol": sym, "rows": 0, "source": None, "ok": False, "reason": "no_data"}
                out_rows = [{
                    "symbol":      sym,
                    "asset_class": asset_class,
                    "source":      source_used,
                    "trade_date":  r["trade_date"],
                    "open":        r["open"],
                    "high":        r["high"],
                    "low":         r["low"],
                    "close":       r["close"],
                    "volume":      r["volume"],
                } for r in rows_in]
                n = await _upsert_ohlcv(client, out_rows)
                rows_total += n
                per_symbol.append({"symbol": sym, "rows": n, "source": source_used, "ok": True})

        await asyncio.gather(*[_one(s) for s in todo], return_exceptions=True)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return {
        "ok":           True,
        "rows_written": rows_total,
        "symbols_ok":   sum(1 for x in per_symbol if x.get("ok")),
        "symbols_total": len(todo),
        "days":         days,
        "elapsed_s":    round(elapsed, 1),
        "as_of":        started.isoformat(),
    }


# ── Public read endpoints ─────────────────────────────────────────────────
@router.get("/api/v1/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, days: int = Query(90, ge=1, le=730)):
    """Return daily OHLCV for a symbol (newest first)."""
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="supabase not configured")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{_SB_URL}/rest/v1/ohlcv_daily",
                params={
                    "symbol":     f"eq.{symbol.upper()}",
                    "order":      "trade_date.desc",
                    "limit":      str(min(days, 730)),
                    "select":     "trade_date,open,high,low,close,volume,source",
                },
                headers=_sb_headers(),
                timeout=15,
            )
        if r.status_code != 200:
            return {"status": "error", "code": r.status_code, "body": r.text[:200]}
        return {"status": "ok", "symbol": symbol.upper(), "count": len(r.json()), "data": r.json()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/api/v1/ohlcv/coverage")
async def ohlcv_coverage():
    """
    Per-symbol row counts + date range — for the audit dashboard.
    """
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="supabase not configured")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{_SB_URL}/rest/v1/ohlcv_daily",
                params={
                    "select":  "symbol,asset_class,source",
                    "order":   "trade_date.desc",
                    "limit":   "1000",
                },
                headers=_sb_headers(),
                timeout=20,
            )
        if r.status_code != 200:
            return {"status": "error", "code": r.status_code}
        # Group
        from collections import defaultdict
        agg = defaultdict(lambda: {"rows": 0, "asset_class": None, "sources": set()})
        for row in r.json():
            sym = row.get("symbol")
            if not sym: continue
            agg[sym]["rows"] += 1
            agg[sym]["asset_class"] = agg[sym]["asset_class"] or row.get("asset_class")
            if row.get("source"): agg[sym]["sources"].add(row["source"])
        out = [
            {"symbol": k, "rows": v["rows"], "asset_class": v["asset_class"], "sources": sorted(v["sources"])}
            for k, v in sorted(agg.items())
        ]
        return {"status": "ok", "symbols": len(out), "data": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])
