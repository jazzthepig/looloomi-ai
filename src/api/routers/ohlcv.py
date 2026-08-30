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
from fastapi import APIRouter, Header, HTTPException, Query

_logger = logging.getLogger(__name__)
router = APIRouter()


#: 内部端点的令牌 —— 与其他 /internal/ 路由同源。
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

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
                f"{_SB_URL}/rest/v1/ohlcv_daily?on_conflict=symbol,trade_date,source",
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
        now = int(datetime.now(timezone.utc).timestamp())
        frm = now - days * 86400

        # ── S-195 (2026-08-23): real candles, not price samples ─────────────
        # `market_chart/range` returns PRICE SAMPLE POINTS, and for short windows
        # it returns them HOURLY however `interval=daily` is set. Collapsing
        # those to a date keeps whichever hour landed last, so the "daily close"
        # was never a close — which is why our 08-19 row said BTC +0.30% against
        # the venue's +7.15%.
        #
        # `/ohlc/range` with `interval=daily` is a Pro-only parameter that
        # returns actual OHLC candles. We have paid for it monthly and never
        # called it. Jazz, 2026-08-23: "way underused".
        from src.data.market.data_layer import get_cg_ohlc_range
        candles = await get_cg_ohlc_range(coin_id, frm, now, interval="daily")
        if candles:
            vol_by_date = {}
            try:
                _h = await get_cg_market_chart_range(coin_id, frm, now, interval="daily")
                for v in (_h.get("volumes") or []):
                    if len(v) >= 2:
                        _d = datetime.fromtimestamp(float(v[0]) / 1000, tz=timezone.utc).date()
                        vol_by_date[_d.isoformat()] = float(v[1])
            except Exception:
                pass          # volume is decoration; the candle is the point
            for c in candles:
                c["volume"] = vol_by_date.get(c["trade_date"])
            return candles

        # Only if the Pro candle endpoint gave nothing. Kept because no data is
        # worse than sample-point data — but the caller must know which it got,
        # so this path is logged rather than silently equivalent.
        _logger.warning("[OHLCV] %s: ohlc/range empty, falling back to price "
                        "samples (NOT true closes)", coin_id)
        hist = await get_cg_market_chart_range(coin_id, frm, now, interval="daily")
        if not hist.get("available"):
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


async def _fetch_hyperliquid_daily(client, coin: str, days: int) -> list:
    """Fetch daily candles from Hyperliquid — the crypto FALLBACK when CoinGecko returns empty
    (CG rate-limit/quota stalled the crypto feed 06-19). HL is a public DEX API: no key, not
    geo-blocked (unlike Binance-US), and fresh — verified live 2026-07-23 returning today's candle.
    coin = the ticker (BTC/ETH/SOL/…); non-HL-listed symbols return [] and fall through. Volume is
    base volume (fine — we key off close)."""
    import time as _t
    end_ms = int(_t.time() * 1000)
    start_ms = end_ms - (days + 2) * 86_400_000
    try:
        r = await client.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "candleSnapshot", "req": {
                "coin": coin.upper(), "interval": "1d", "startTime": start_ms, "endTime": end_ms}},
            timeout=20,
        )
        r.raise_for_status()
        candles = r.json()
        if not isinstance(candles, list):
            return []
        out = []
        for k in candles:
            t, close = k.get("t"), k.get("c")
            if t is None or close is None:
                continue
            d = datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()
            out.append({
                "trade_date": d,
                "open":   float(k.get("o") or close or 0),
                "high":   float(k.get("h") or close or 0),
                "low":    float(k.get("l") or close or 0),
                "close":  float(close or 0),
                "volume": float(k.get("v") or 0),
            })
        return out
    except Exception as e:
        _logger.warning(f"[OHLCV] hyperliquid {coin} failed: {e}")
        return []


async def _fetch_eodhd_daily(client, symbol: str, days: int) -> list:
    """Fetch daily candles from EODHD /eod — the TradFi PRIMARY. yfinance is rate-limited/blocked
    (confirmed 2026-07: YFRateLimitError), which silently stalled ohlcv_daily since 06-18; the rest
    of the system already moved TradFi to EODHD (data_layer.get_eodhd_eod_data), the collector had not.
    Same endpoint/auth as that proven helper. Returns the collector row shape; [] on any failure so the
    caller falls back to yfinance (no regression)."""
    try:
        from src.data.market.data_layer import EODHD_KEY, EODHD_BASE
    except Exception:
        return []
    if not EODHD_KEY:
        return []
    frm = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    try:
        r = await client.get(
            f"{EODHD_BASE}/eod/{symbol}.US",
            params={"fmt": "json", "api_token": EODHD_KEY, "period": "d", "from": frm},
            timeout=15,
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            return []
        out = []
        for x in rows:
            d, close = x.get("date"), x.get("close")
            if not d or close is None:
                continue
            out.append({
                "trade_date": d,
                "open":   float(x.get("open")  or close or 0),
                "high":   float(x.get("high")  or close or 0),
                "low":    float(x.get("low")   or close or 0),
                "close":  float(close or 0),
                "volume": float(x.get("volume") or 0),
            })
        return out
    except Exception as e:
        _logger.warning(f"[OHLCV] EODHD {symbol} failed: {e}")
        return []


async def _fetch_yf_daily(client_unused, symbol: str, days: int) -> list:
    """Fetch daily candles via yfinance (sync, run in thread). FALLBACK only — rate-limited (2026-07)."""
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
                    if not rows_in:
                        rows_in = await _fetch_hyperliquid_daily(client, sym, days)  # crypto fallback (CG rate-limited)
                        if rows_in:
                            source_used = "hyperliquid"
                if not rows_in and yf_sym:
                    rows_in = await _fetch_eodhd_daily(client, yf_sym, days)   # PRIMARY (yfinance dead)
                    source_used = "eodhd"
                    if not rows_in:
                        rows_in = await _fetch_yf_daily(client, yf_sym, days)  # fallback
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




# ── S-258: CoinGecko Pro 深盘回填 ─────────────────────────────────────────────

@router.post("/internal/backfill-cg-pro")
async def backfill_cg_pro(
    dry_run: bool = Query(default=True, description="默认 dry_run —— 写入要显式要求"),
    dest: str = Query(default="local", pattern="^(local|supabase)$",
                      description="local=本地研究面(默认)· supabase=系统记录(显式)"),
    days: int = Query(default=1825, ge=90, le=3650, description="回看天数,默认 5 年"),
    x_internal_token: str = Header(None),
):
    """把 CoinGecko Pro 的真 K 线落进 `ohlcv_daily`,标为 `coingecko_pro_ohlc`。

    **为什么需要这个端点而不是 Mac 侧直写**:§NO-DIRECT-SUPABASE —— 写入走
    持 service_role 的 Railway。Mac 的 `.env` 是 anon key,RLS 会拒,
    而脚本会打印 "push complete" 覆盖一次从未发生的写入(S-166/S-168)。

    **为什么现在做**(S-251 实测):binance_hist 最近 3 天 0/212 标的、
    hyperliquid 0/177 —— **加密侧没有任何可用于收益的价源在更新**。
    而 M-91 量过 binance_hist 天花板是 343 天,M-92 用 CG Pro 拿到 1811 天,
    并因此把 ① 从「结构上不可行」翻成「regime-conditional」。

    `dry_run` **默认 True**:一个默认写库的回填端点,按错一次就是几万行。
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    from datetime import date as _date
    from datetime import timedelta as _td

    from src.data.market.cg_pro_backfill import backfill

    # symbol → coingecko coin_id。**显式表,不猜** —— 猜错一个映射会把另一个币
    # 的价格写进这个标的的历史,而那条曲线看起来完全正常。
    # 先覆盖 M-87 的 10 个宇宙成员(② beta+ 的标的),其余后续按需扩。
    pairs = [
        ("BTC", "bitcoin"), ("ETH", "ethereum"), ("SOL", "solana"),
        ("BNB", "binancecoin"), ("XRP", "ripple"), ("ADA", "cardano"),
        ("DOGE", "dogecoin"), ("AVAX", "avalanche-2"), ("LINK", "chainlink"),
        ("DOT", "polkadot"),
    ]
    end = _date.today()
    # `dest` 默认 local:Supabase 是免费版(实测 253MB/500MB = 50.7%),
    # 而研究面不该占系统记录的额度 (S-261)。写生产库要显式要求两次:
    # dry_run=false 且 dest=supabase。
    res = await backfill(pairs, start=end - _td(days=days), end=end,
                         asset_class="L1", dest=dest, dry_run=dry_run)
    return res.as_payload()
