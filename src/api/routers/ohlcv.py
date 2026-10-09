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
from typing import Optional

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
    """Upsert rows to ohlcv_daily. Returns count accepted.

    A-408-3 / S-408-3: refactored from a raw httpx POST (which bypassed
    `write_log`) to `supabase_upsert_table` (which is `@log_write_attempt`
    decorated, S-352). One row in `write_log` per chunk instead of zero
    rows for the entire batch — and each row carries
    `writer='src.api.routers.ohlcv._upsert_ohlcv'`.

    Chunking stays at 500 (caller-side); `supabase_upsert_table` does NOT
    chunk internally (it ships the entire `rows` list as one body). A
    250k-row body is a timeout — the chunk loop stays here.

    `StoreResult.__bool__ → r.ok` — the `if r:` check uses that. Documented
    so a future reader doesn't "fix" it to `if r.ok:`.
    """
    if not rows or not _SB_URL or not _SB_KEY:
        return 0
    from src.api.store import supabase_upsert_table
    CHUNK = 500
    total = 0
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i+CHUNK]
        r = await supabase_upsert_table(
            "ohlcv_daily", chunk,
            on_conflict="symbol,trade_date,source")
        if r:                                           # StoreResult.__bool__ → r.ok
            total += len(chunk)
        else:
            _logger.warning(f"[OHLCV] upsert chunk failed: {r.why[:200]}")
    return total


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
                        # S-436: the 00:00 point carries the 24h ending there = the day before.
                        from src.data.market.bar_semantics import covered_day
                        _d = covered_day("coingecko_market_chart", v[0])   # 一处定义(T-049)
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


def eodhd_adjusted_rows(rows: list) -> list:
    """纯函数。EODHD 原始日线 → 复权后的 OHLC(T-079 / S-531)。

    原来写的是**原始收盘**,而 CIS 实盘读的是 `adjusted_close`(data_layer.get_eodhd_eod_data)—— 同一个标的
    两种口径。原始收盘跨拆股会造出假跌(NVDA 2024-06 一拆十 = 一天 −90%),跨分红会少算债券 ETF 的收益。
    统一为复权:收盘 = adjusted_close,开高低按同一个系数(adjusted_close / close)缩放;成交量不动。
    复权值会随后来的分红回改 —— 所以全历史每周重取一次(cis_inputs 的回填),不是只取一次。"""
    out = []
    for x in rows or []:
        d, close = x.get("date"), x.get("close")
        try:
            close = float(close)
        except (TypeError, ValueError):
            continue
        if not d or close <= 0:
            continue
        try:
            adj = float(x.get("adjusted_close"))
        except (TypeError, ValueError):
            adj = close
        if adj <= 0:
            adj = close
        k = adj / close
        out.append({
            "trade_date": d,
            "open":   float(x.get("open") or close) * k,
            "high":   float(x.get("high") or close) * k,
            "low":    float(x.get("low") or close) * k,
            "close":  adj,
            "volume": float(x.get("volume") or 0),
        })
    return out


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
        return eodhd_adjusted_rows(rows)
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
                    # S-459:加密日线**只有一个写入端** —— `_cg_panel_loop` → `cg_pro_backfill`(按 ≤ 窗口分块取真 K 线)。
                    # 这里原来一次要 365 天的 /ohlc/range,拿不到就退回 market_chart 的**采样点**,
                    # 把 O=H=L=C 的点、按「点的日期」(晚一天)写进 `coingecko_pro_ohlc` —— 过去一年 9,098 行,
                    # 恰好是 BTC/ETH/SOL/HYPE/LINK/ONDO 等 28 个核心币;每轮还把正确的 K 线覆盖回去。
                    return {"symbol": sym, "rows": 0, "source": "coingecko_pro_ohlc", "ok": True,
                            "reason": "crypto 由 _cg_panel_loop(cg_pro_backfill)单一写入端负责"}
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




# ── 研究读取(lane 不持 key):单一来源、带起点、分页 ─────────────────────────────
#
# `/api/v1/ohlcv/{symbol}` 按行数截断且混着多个来源(同一天可能有 binance_hist 和 coingecko_pro_ohlc 两行),
# 拿来做研究会把两个源拼成一条序列 —— S-459 的接缝问题。研究用这两个端点:**必须指定来源**,按日期分页取全。

async def _paged(table: str, params: dict) -> list:
    out: list = []
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            r = await client.get(f"{_SB_URL}/rest/v1/{table}",
                                 params={**params, "limit": "1000", "offset": str(len(out))},
                                 headers=_sb_headers())
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"读不到 {table}:HTTP {r.status_code}")
            batch = r.json()
            out.extend(batch)
            if len(batch) < 1000:
                return out


@router.get("/api/v1/research/ohlcv/{symbol}")
async def research_ohlcv(symbol: str,
                         source: str = Query(..., pattern="^(binance_hist|coingecko_pro_ohlc|eodhd)$"),
                         start: str = Query("2020-01-01")):
    """单一来源的日线(旧→新)。`trade_date` = 覆盖的那一天(UTC)。"""
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="supabase not configured")
    rows = await _paged("ohlcv_daily", {"symbol": f"eq.{symbol.upper()}", "source": f"eq.{source}",
                                        "trade_date": f"gte.{start}", "order": "trade_date.asc",
                                        "select": "trade_date,open,high,low,close,volume"})
    return {"status": "ok", "symbol": symbol.upper(), "source": source, "count": len(rows), "data": rows}


@router.get("/api/v1/research/channels")
async def research_channels(level: str = Query("aggregate", pattern="^(aggregate|category)$"),
                            start: str = Query("2020-01-01")):
    """上游通道日度序列(S-458,T-046 用):稳定币 / 代币化 / RWA 分类市值之和与成员数,外加全市场市值与成交额。
    `aggregate` = 每个通道的合计(category_id='*')与 global;`category` = 逐个分类。`basis` 标幸存者回填。
    这些都是**水平**;研究里取变化量与加速度。"""
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="supabase not configured")
    params = {"d": f"gte.{start}", "order": "d.asc",
              "select": "d,channel,category_id,mcap,n_members,basis"}
    if level == "aggregate":
        params["or"] = "(category_id.eq.*,channel.eq.global)"
    rows = await _paged("channel_series_daily", params)
    return {"status": "ok", "level": level, "count": len(rows), "data": rows}


@router.get("/api/v1/research/core-alpha")
async def research_core_alpha(start: str = Query("2023-01-01"),
                              alpha: Optional[float] = Query(None, description="0 / 0.5 / 1;不给 = 三臂都给")):
    """① 加权参数 α 的三条日收益序列(α = 0 等权 / 0.5 / 1 市值,单币 ≤ 40%,24 名,每日再平衡)——
    S-472 那条 SQL 收成的库函数 `core_alpha_daily`。2026-10-02 以前是回放(先验),之后的前向记录看 `core_cap_daily`。
    ① 是 α=1。分页读全(S-487:以前只拿到前 1,000 行 = 只有 α=0)。"""
    from src.api.store import supabase_rpc_all
    params = {"order": "alpha.asc,d.asc"}
    if alpha is not None:
        params["alpha"] = f"eq.{alpha}"
    rows = await supabase_rpc_all("core_alpha_daily", {"p_start": start}, params)
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="core_alpha_daily 读不到 —— 读不到 ≠ 没有数据")
    return {"status": "ok", "count": len(rows), "data": rows,
            "note": "回放序列:成员是今天的 24 名往回取(幸存者),不计成本;① = α=1"}


@router.get("/internal/research/book-navs")
async def research_book_navs(x_internal_token: str = Header(None)):
    """登记表里每本账的逐日 NAV 与它自己的基准(给 T-047 / T-045 用)。只读。"""
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.data.accounting.registry import BOOKS, load_navs
    navs, bench = await load_navs()

    def _ser(s):
        if s is None:
            return []
        s = s.dropna().sort_index()
        return [{"d": d.date().isoformat(), "nav": float(v)} for d, v in s.items()]
    return {"status": "ok",
            "books": [{"id": b.id, "layer": b.layer, "status": b.status, "caveat": b.caveat,
                       "benchmark": b.benchmark, "nav": _ser(navs.get(b.id)), "bench": _ser(bench.get(b.id))}
                      for b in BOOKS]}


@router.get("/api/v1/research/market-state")
async def research_market_state(start: str = Query("2022-01-01")):
    """宏观状态向量(解读层 5a 的空间)。`vec_full` 里的 null = 那一维当天没测到,不是 0。"""
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="supabase not configured")
    rows = await _paged("market_state_vectors", {"d": f"gte.{start}", "order": "d.asc", "select": "d,vec_full"})
    return {"status": "ok", "count": len(rows), "data": rows}


# ── T-039:风格指数的公开读取(研究 lane 与外部 agent 用;只读、无 key)────────────
#
# lane 不持有 Supabase key(OPEN RISK #0b),研究要数据走 Railway 的公开读端点 —— 与 /api/v1/ohlcv 同一模式。
# 只返回当前 code_ref 的行:分类法改版后旧行在清理前不会混进来。

@router.get("/api/v1/style/index")
async def get_style_index(style: str = Query(..., description="majors / top_l1 / second_l1_l2 / app / ai / meme / defi / infra_tokenization"),
                          weighting: str = Query("cap", pattern="^(cap|equal)$"),
                          start: str = Query("2020-01-01"),
                          basis: str = Query("pit", pattern="^(pit|backfilled)$",
                                             description="pit = 时点 + 宽宇宙(T-067,研究默认);backfilled = 今天成分回填(有幸存者偏差)")):
    """一个风格指数的逐日收益与累计水平(旧→新)。每行带 n_members 与 basis。

    默认 `basis=pit`(T-067 / S-512):每天的成员按当日市值、宇宙含在 Binance 现货上市过的全部币;
    `backfilled` 是旧口径(今天的分类前 40 名往回取),有幸存者偏差,留作对照。"""
    from src.data.style.header import CODE_REF
    from src.data.style.pit import CODE_REF_PIT, PIT_TABLE
    from src.data.style.taxonomy import DIMENSION
    table, code_ref = (PIT_TABLE, CODE_REF_PIT) if basis == "pit" else ("style_index_daily", CODE_REF)
    if style not in DIMENSION:
        raise HTTPException(status_code=400, detail=f"未知风格 '{style}';可用:{sorted(DIMENSION)}")
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="supabase not configured")
    out: list = []
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            r = await client.get(
                f"{_SB_URL}/rest/v1/{table}",
                params={"style": f"eq.{style}", "weighting": f"eq.{weighting}", "code_ref": f"eq.{code_ref}",
                        "d": f"gte.{start}", "order": "d.asc", "limit": "1000", "offset": str(len(out)),
                        "select": "d,ret,level,n_members,n_dropped,top_member,top_weight,basis"},
                headers=_sb_headers())
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"读不到 {table}:HTTP {r.status_code}")
            batch = r.json()
            out.extend(batch)
            if len(batch) < 1000:
                break
    return {"status": "ok", "style": style, "dimension": DIMENSION[style], "weighting": weighting,
            "basis": basis, "code_ref": code_ref, "count": len(out), "data": out}


# ── v0.2 阶段 1:所有纸面账本的统一成绩单 ─────────────────────────────────────

@router.get("/internal/books/scorecard")
async def books_scorecard(x_internal_token: str = Header(None)):
    """每本纸面账本一行:层级、记账是否走公用内核、起止、缺几天、总收益、同期持有同一面板、差值、最大回撤。
    记账还没迁到公用内核的账本标 `accounting=own` —— 那一行的数字仍是它自己的记账算的。"""
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.data.accounting.registry import scorecard
    rows = await scorecard()
    return {"status": "ok", "n": len(rows), "books": rows}


# ── T-053 证据面:对外,与配置层同一口径 ─────────────────────────────────────────

_PROOF_CACHE: dict = {"at": None, "body": None}
_PROOF_TTL_S = 1800


@router.get("/api/v1/proof/books")
async def proof_books():
    """① 与每本纸面账本的前向证据,按证据等级(forward / forward_young / caveat / retired / no_record)。
    口径 = 配置层:前向窗口、相对 ① 的超额、任意时刻有效下界、配置层最新权重。不下结论句(S-491)。30 分钟缓存。"""
    now = datetime.now(timezone.utc)
    if _PROOF_CACHE["body"] is not None and _PROOF_CACHE["at"] and (now - _PROOF_CACHE["at"]).total_seconds() < _PROOF_TTL_S:
        return _PROOF_CACHE["body"]
    import pandas as pd
    from src.data.accounting.proof import HOW_TO_READ, proof_rows
    from src.data.accounting.registry import BOOKS, load_navs
    from src.data.allocation.allocator import CORE
    from src.data.style.header import _read_all
    navs, _bench = await load_navs()
    core = navs.get(CORE)
    if core is None or core.dropna().empty:
        raise HTTPException(status_code=502, detail="① 的 NAV 读不到 —— 不出证据面(读不到 ≠ 没有证据)")
    since = (now.date() - timedelta(days=7)).isoformat()
    arows = await _read_all("allocation_daily", {"select": "d,book,weight", "d": f"gte.{since}", "order": "d.asc"})
    last_d = max((r["d"] for r in arows), default=None)
    alloc = {r["book"]: {"weight": r["weight"], "d": r["d"]} for r in arows if r["d"] == last_d}
    asof = pd.Timestamp(core.dropna().index.max())
    rows = proof_rows(list(BOOKS), navs, core, alloc, asof)
    body = {"status": "ok", "as_of": asof.date().isoformat(), "allocation_as_of": last_d,
            "core": CORE, "books": rows, "how_to_read": HOW_TO_READ,
            "note": "Paper records, not live-traded P&L. Every number is labelled with its evidence class; "
                    "no book is pre-judged here.",
            "compliance": "Positioning language only; not investment advice."}
    _PROOF_CACHE.update({"at": now, "body": body})
    return body


# ── T-074 / S-522:探索仓的入口 —— 机会提交(内部,X-Internal-Token);当天的前向锚把它一起锚定 ─────────

@router.post("/internal/exploration/ideas")
async def exploration_submit(body: dict, x_internal_token: str = Header(None)):
    """提交一个机会:asset(必填)、thesis(必填,一句话:为什么、会怎样、什么情况下算错)、chain / contract / source /
    horizon(hours|days|weeks|months)/ submitted_by。只追加;当天锚定。"""
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.data.exploration.ideas import submit
    out = await submit(body or {})
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("problems"))
    return out


@router.get("/internal/exploration/ideas")
async def exploration_list(start: str = Query("2026-10-01"), x_internal_token: str = Header(None)):
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.data.style.header import _read_all
    rows = await _read_all("exploration_ideas", {"select": "*", "d": f"gte.{start}", "order": "submitted_at.asc"})
    return {"status": "ok", "count": len(rows), "ideas": rows}


# ── T-073 / S-519:前向记录锚定 —— 每天一行,只追加;外人可重算摘要、对比特币核对时间 ──────────────

@router.get("/api/v1/proof/anchors")
async def proof_anchors(start: str = Query("2026-10-01")):
    """每天一行:日期、摘要(SHA-256)、行数、提交时间、收下它的日历。payload 与 .ots 证明见 /api/v1/proof/anchors/{d}。"""
    from src.data.style.header import _read_all
    rows = await _read_all("forward_anchor_daily", {"select": "d,digest,n_rows,submitted_at,ots",
                                                    "d": f"gte.{start}", "order": "d.asc"})
    return {"status": "ok", "count": len(rows),
            "anchors": [{"d": x["d"], "digest": x["digest"], "n_rows": x["n_rows"], "submitted_at": x["submitted_at"],
                         "calendars": sorted((x.get("ots") or {}).keys())} for x in rows],
            "how_to_verify": ("GET /api/v1/proof/anchors/{d} → sha256(payload as compact JSON, keys sorted, UTF-8) must equal "
                              "digest; decode any ots value (base64) to a .ots file and run `ots verify` / `ots upgrade` "
                              "(OpenTimestamps) to check the time against Bitcoin. Anchors are append-only."),
            "note": "Paper records, not live-traded P&L."}


@router.get("/api/v1/proof/anchors/{d}")
async def proof_anchor_day(d: str):
    """一天的锚:payload(规范 JSON 的原文)、摘要、.ots 证明(base64,按日历),以及现场重算 —— 今天的表与锚定时是否一致。"""
    from src.data.accounting.anchor import verify_now
    from src.data.style.header import _read_all
    try:
        day = date.fromisoformat(d)
    except ValueError:
        raise HTTPException(status_code=400, detail="d 必须是 YYYY-MM-DD")
    rows = await _read_all("forward_anchor_daily", {"select": "*", "d": f"eq.{day.isoformat()}"})
    if not rows:
        raise HTTPException(status_code=404, detail=f"{day} 没有锚")
    x = rows[0]
    check = await verify_now(day)
    return {"status": "ok", "d": x["d"], "digest": x["digest"], "n_rows": x["n_rows"], "submitted_at": x["submitted_at"],
            "payload": x["payload"], "ots_base64": x["ots"],
            "matches_current_tables": check.get("matches_current_tables"),
            "note": ("matches_current_tables = false means the stored rows for that day were changed after anchoring; "
                     "the anchored payload is what existed at anchoring time.")}


# ── v0.2 L3 配置层(纸面)──────────────────────────────────────────────────────

from pydantic import BaseModel, Field  # noqa: E402


class AllocationOverrideIn(BaseModel):
    delta: float = Field(..., ge=-1.3, le=1.3, description="敞口偏置;最终敞口截到 [-0.3, 1.3]")
    horizon: str = Field(..., pattern="^(7d|14d|1m|delegate)$")
    reason: str = Field(..., min_length=1, max_length=500)
    start_d: date | None = None


@router.post("/internal/allocation/override")
async def allocation_override(body: AllocationOverrideIn, x_internal_token: str = Header(None)):
    """⓪ 人工通道:下一条带理由、带期限的敞口偏置(7d / 14d / 1m / delegate=全委托 即不设偏置)。
    写入后在后台整条重算配置。"""
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.api.store import supabase_insert_table
    from src.data.allocation.allocator import HORIZONS, run_once
    start = body.start_d or datetime.now(timezone.utc).date()
    days = HORIZONS[body.horizon]
    row = {"start_d": start.isoformat(), "delta": 0.0 if body.horizon == "delegate" else body.delta,
           "horizon": body.horizon, "reason": body.reason,
           "expires_d": (start + timedelta(days=days)).isoformat() if days else None}
    w = await supabase_insert_table("allocation_override", [row])
    if not w.ok:
        raise HTTPException(status_code=502, detail=f"allocation_override 写入失败:{w.why}")
    asyncio.create_task(run_once())
    return {"status": "ok", "override": row, "recompute": "started"}


@router.get("/internal/allocation/latest")
async def allocation_latest(x_internal_token: str = Header(None), days: int = Query(30, ge=1, le=400)):
    """最新一天的配置(权重、敞口、为什么)+ 最近 N 天纸面 NAV + 生效中的人工偏置。"""
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.data.vector.market_state_writer import _sb_get
    nav = await _sb_get("allocation_nav_daily", {"select": "*", "order": "d.desc", "limit": str(days)})
    if not nav.ok:
        raise HTTPException(status_code=502, detail=f"allocation_nav_daily 读不到:{nav.reason}")
    if not nav.rows:
        return {"status": "empty", "note": "配置还没有第一行 —— 看 loop_attempt 里 _allocation_loop 的原因"}
    last = nav.rows[0]["d"]
    alloc = await _sb_get("allocation_daily", {"select": "book,weight,exposure,evidence,why",
                                               "d": f"eq.{last}", "order": "weight.desc"})
    ovr = await _sb_get("allocation_override", {"select": "*", "order": "id.desc", "limit": "20"})
    if not alloc.ok or not ovr.ok:
        raise HTTPException(status_code=502, detail="allocation_daily / allocation_override 读不到")
    today = datetime.now(timezone.utc).date().isoformat()
    active = [o for o in ovr.rows or [] if o.get("expires_d") and o["start_d"] <= today < o["expires_d"]]
    why = next((r.get("why") for r in alloc.rows or [] if r.get("why")), None)
    return {"status": "ok", "d": last, "exposure": nav.rows[0]["exposure"], "nav": nav.rows[0]["nav"],
            "weights": [{k: r[k] for k in ("book", "weight", "evidence")} for r in alloc.rows or []],
            "why": why, "active_overrides": active, "nav_series": list(reversed(nav.rows))}


# ── T-041 / M-196:解读层的预注册检验(后台跑,结果落 interpretation_validation_runs)────

@router.post("/internal/interpret/validate")
async def interpret_validate(x_internal_token: str = Header(None)):
    """按台账 M-196 回放 2023-01 起每一天:相似日分布 vs 只用过去的无条件分布 vs 随机相似日。
    后台执行(几分钟);结果看 `select verdict, result from interpretation_validation_runs order by id desc limit 1`。"""
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    from src.api.rpc_diagnostics import _record_loop_attempt
    from src.data.interpret.validate import run as _validate

    async def _bg():
        try:
            r = await _validate()
            # 摘要也写进 loop_attempt:结果表写入失败时,数字不至于整轮丢失(S-462)。
            _oos = r.get("out_of_sample_2024+") or {}
            await _record_loop_attempt("_interpret_validate", "ok" if r.get("written") else "error",
                                       reason=(f"M-196 verdict={r.get('verdict')}"
                                               + ("" if r.get("written") else f" · 结果表未写入:{r.get('write_error')}")),
                                       detail={k: _oos.get(k) for k in ("n_days", "t1", "t2", "t3", "t4", "random", "overall")},
                                       writer="src.api.routers.ohlcv.interpret_validate")
        except Exception as e:                                    # noqa: BLE001
            await _record_loop_attempt("_interpret_validate", "error", reason=f"{type(e).__name__}: {e}"[:400],
                                       writer="src.api.routers.ohlcv.interpret_validate")
    asyncio.create_task(_bg())
    return {"started": True, "prereg": "M-196",
            "verify": "select verdict, result from interpretation_validation_runs order by id desc limit 1"}


# ── S-258: CoinGecko Pro 深盘回填 ─────────────────────────────────────────────

@router.post("/internal/backfill-deep-panel")
async def backfill_deep_panel(
    days: int = Query(default=400, ge=14, le=1500, description="回看天数"),
    symbols: str = Query(default="", description="逗号分隔;空 = ① 面板 24 币(T-030 的范围)"),
    dry_run: bool = Query(default=True, description="默认 dry_run —— 写入要显式要求"),
    x_internal_token: str = Header(None),
):
    """T-030(2026-09-27):用**同一个**写入端(`deep_panel_collector.collect_deep_panel`,source='binance_hist')
    按更长的窗口补历史缺口。不是第二条摄入路径 —— 同一函数、同一 upsert、同一 write_log。

    **为什么要这个端点:** binance_hist 过去一年整天缺 41 天(最后一次 09-06)。采集器每天只重写 14 天,
    自愈只在**前沿**出现缺口时放大窗口(最多 180 天)—— 历史内部的洞它看不见,也就永远不补。
    β+ 账本(S-429)与 C 的 T-005 研究都读这个源。

    **后台执行:** 请求经 Cloudflare 有 100s 上限,这里立即返回,结果看 `write_log`(writer=_upsert_ohlcv 同族)
    与 `select symbol, count(*) from ohlcv_daily where source='binance_hist' …`。
    值不变的重写不会刷新 `recorded_at`(S-430 触发器),所以补洞不会污染 PIT。
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    if symbols.strip():
        syms = [x.strip().upper() for x in symbols.split(",") if x.strip()]
    else:
        from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
        syms = list(DEFAULT_UNIVERSE)
    plan = {"source": "binance_hist", "days": days, "n_symbols": len(syms), "symbols": syms}
    if dry_run:
        return {"dry_run": True, **plan, "note": "加 ?dry_run=false 才会真正抓取并写入"}

    from src.data.market.deep_panel_collector import collect_deep_panel

    async def _run():
        # S-439:后台任务的结果必须落到能查的地方。首次真跑被「活标的 ≥100」地板拒绝,
        # 只留了一行日志,从外面看就是「跑了,没写」。
        from src.api.rpc_diagnostics import _record_loop_attempt
        try:
            r = await collect_deep_panel(days=days, symbols=syms)
            _logger.warning("[DEEP-BACKFILL] days=%s symbols=%s → %s", days, len(syms),
                            {k: r.get(k) for k in ("symbols_ok", "symbols_failed", "rows_upserted", "refused")})
            outcome = "refused" if r.get("refused") else ("ok" if r.get("ok") else "error")
            detail = {k: r.get(k) for k in ("symbols_total", "symbols_ok", "symbols_failed",
                                            "rows_built", "rows_upserted", "written")}
            detail["days"] = days
            await _record_loop_attempt(
                "_deep_panel_backfill", outcome,
                reason=str(r.get("diagnosis") or r.get("error") or "")[:400] or None,
                detail=detail, writer="src.api.routers.ohlcv.backfill_deep_panel")
        except Exception as e:                                    # noqa: BLE001
            _logger.error("[DEEP-BACKFILL] failed: %s: %s", type(e).__name__, e)
            await _record_loop_attempt("_deep_panel_backfill", "error",
                                       reason=f"{type(e).__name__}: {e}"[:400],
                                       writer="src.api.routers.ohlcv.backfill_deep_panel")

    asyncio.create_task(_run())
    return {"dry_run": False, "started": True, **plan,
            "verify": "select symbol, count(*) from ohlcv_daily where source='binance_hist' "
                      "and trade_date >= current_date - %d group by 1" % days}


@router.post("/internal/backfill-cg-pro")
async def backfill_cg_pro(
    dry_run: bool = Query(default=True, description="默认 dry_run —— 写入要显式要求"),
    dest: str = Query(default="supabase", pattern="^(local|supabase)$",
                      description="supabase=系统记录(S-361 起默认)· local=本地研究面"),
    days: int = Query(default=2451, ge=90, le=3650,
                      description="回看天数,默认 2451 ≈ 回到 2020-01-01"),
    panel: str = Query(default="cis", pattern="^(cis|all)$",
                       description="cis=CIS 面板交集(默认)· all=cg_coin_map 全量"),
    symbols: str = Query(default="", max_length=400,
                         description="逗号分隔;非空时只回填这些(仍须在 cg_coin_map 里有 coin_id)—— 改了映射后只重写那几个"),
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

    from src.api.store import supabase_rpc
    from src.data.market.cg_pro_backfill import backfill

    # S-361:标的集从 `cg_coin_map` 读,**不再硬编码**。
    #
    # 原来这里钉死 M-87 的 10 个,注释写着「其余后续按需扩」—— 那个「后续」
    # 没有发生,而 `cg_coin_map` 现在有 209 个已解析映射。**一份写着「待扩」
    # 的硬编码清单,和一份过期的注释是同一种东西**:它不会自己扩,也不会报错。
    #
    # 「显式表,不猜」这条**保留且更强了**:`cg_coin_map` 就是那张显式表
    # (symbol → coin_id,带 `resolved_from` / `verified_at` 溯源)。
    # 猜错一个映射会把另一个币的价格写进这个标的的历史,而那条曲线看起来完全正常 ——
    # 所以只取 `coin_id is not null` 的行,解析不出来的**跳过并报出来**,不猜。
    #
    # ⚠️ 这个 RPC 实测 ~20s/209 rows(LEFT JOIN + ORDER BY 没索引)——
    # `supabase_rpc` 共享 client 的 default timeout=10s 不到一半就 fallback None
    # (实测 10s 后 endpoint 503 而 service_role 直调 19.9s 通了 209 行),
    # 静默返回空。**这是一个被超时掩盖的可见 bug** —— 不知道 RPC 慢,
    # 就会以为 RPC 没数据。与下面 cis_scores 读取同模式(直 httpx + 显式 timeout)。
    async with httpx.AsyncClient(timeout=60) as _rpc_c:
        _rpc_r = await _rpc_c.post(
            f"{_SB_URL}/rest/v1/rpc/cg_known_coin_map",
            json={},
            headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}",
                     "Content-Type": "application/json"})
    if _rpc_r.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail=f"读 cg_known_coin_map RPC 失败: HTTP {_rpc_r.status_code} "
                   f"{_rpc_r.text[:200]}. **RPC 慢是已知**(给 60s);HTTP 失败是别的原因。")
    try:
        rows = _rpc_r.json() if _rpc_r.content else []
    except Exception:
        rows = []
    if not isinstance(rows, list):
        rows = []
    resolved = {r["symbol"]: r["coin_id"] for r in rows
                if r.get("symbol") and r.get("coin_id")}
    # 每个标的的 asset_class **不同**(实测 200 Crypto / 3 L1 / 2 DeFi / 2 RWA /
    # 1 Infrastructure / 1 L2)。原来这里对整批硬编码 `asset_class="L1"` ——
    # 209 个里 206 个是错的。分组调用,每组带自己的类。
    #
    # ⚠️ 不能图省事传 None:`asset_class` 空的行进 `ohlcv_daily_canonical` 后,
    # 只能靠 `coalesce(a.class, o.asset_class)` 去 `assets` 里找;标的不在
    # `assets` 里就变 NULL,而 S-361 的守卫正是判它红。**别给自己的守卫喂它要抓的东西。**
    klass = {r["symbol"]: (r.get("asset_class") or "Crypto") for r in rows
             if r.get("symbol")}

    if panel == "cis":
        # CIS 面板最近一轮。**直读表,不新建 RPC** —— 我第一版写了
        # `cis_latest_symbols`,那个函数不存在(库里只有 cg_known_coin_map /
        # deep_panel_symbol_list / panel_closes …)。凭印象写 RPC 名是
        # 这条链上反复吃亏的事:PostgREST 按参数名解析,猜错得到 PGRST202,
        # 读起来像「没有这个函数」,其实是「没有匹配这些参数名的重载」。
        #
        # 43 个 CIS 标的里 19 个是 TradFi(SPY/TLT/AAPL…),它们走 EODHD,
        # **不是 CoinGecko 的事** —— 与 cg_coin_map 求交集天然把它们排除。
        async with httpx.AsyncClient(timeout=20) as _c:
            _r = await _c.get(
                f"{_SB_URL}/rest/v1/cis_scores",
                params={"select": "symbol", "order": "recorded_at.desc",
                        "limit": "3000"},
                headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
        if _r.status_code != 200:
            raise HTTPException(
                status_code=503,
                detail=f"读 cis_scores 失败: HTTP {_r.status_code} {_r.text[:200]}. "
                       f"**读不到 ≠ 面板是空的** —— 这里不退化成回填 0 个标的。")
        wanted = {row["symbol"] for row in _r.json() if row.get("symbol")}
        pairs = [(s, cid) for s, cid in sorted(resolved.items()) if s in wanted]
        skipped = sorted(wanted - set(resolved))
    else:
        pairs = sorted(resolved.items())
        skipped = []

    # S-468:改了映射之后只重写那几个,不必整面板 30 分钟。不在映射表里的报出来,不猜。
    only = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    if only:
        pairs = [(s, cid) for s, cid in sorted(resolved.items()) if s in only]
        skipped = sorted(only - set(resolved))

    if not pairs:
        raise HTTPException(
            status_code=503,
            detail=f"没有可回填的标的 —— cg_coin_map 解析出 {len(resolved)} 个,"
                   f"panel={panel} 交集为空。**空 ≠ 完成**,这里不静默返回 ok。")

    end = _date.today()
    # `dest` 默认 supabase(S-361 改)。原来默认 local,理由是「Supabase 是免费版
    # (实测 253MB/500MB)」—— **那个前提 2026-09-16 已不成立**,Jazz 升了 Pro。
    # 实测库总 304MB,`ohlcv_daily` 121MB / 552k 行 ≈ 229 B/行;
    # 24 个 CIS 加密标的回填到 2020-01-01 ≈ 58.8k 行 ≈ 13MB。
    # `dry_run` 仍默认 True —— 那条理由(按错一次就是几万行)没有过期。
    groups: dict[str, list[tuple[str, str]]] = {}
    for _s, _cid in pairs:
        groups.setdefault(klass.get(_s, "Crypto"), []).append((_s, _cid))

    if not dry_run:
        # S-460:真写入改为后台执行。同步跑 200 个标的 × 400 天要几分钟,Cloudflare 100s 先断开,
        # 客户端只看到「upstream error」,而回填其实在服务器上跑完了 —— 结果看不到。改为立即返回,结果写 loop_attempt。
        async def _bg():
            from src.api.rpc_diagnostics import _record_loop_attempt
            out = []
            try:
                for _ac2, _p2 in sorted(groups.items()):
                    _r2 = await backfill(_p2, start=end - _td(days=days), end=end, asset_class=_ac2,
                                         dest=dest, dry_run=False, vendor_paired=set(resolved.keys()))
                    out.append({"asset_class": _ac2, "n_pairs": len(_p2), **_r2.as_payload()})
                ok = bool(out) and all(g.get("status") == "ok" for g in out)
                await _record_loop_attempt("_backfill_cg_pro", "ok" if ok else "error",
                                           reason=str([{k: g.get(k) for k in ("asset_class", "n_pairs", "status")}
                                                       for g in out])[:400],
                                           detail={"days": days, "panel": panel, "symbols": sorted(only) or None, "by_asset_class": out},
                                           writer="src.api.routers.ohlcv.backfill_cg_pro")
            except Exception as e:                                # noqa: BLE001
                await _record_loop_attempt("_backfill_cg_pro", "error", reason=f"{type(e).__name__}: {e}"[:400],
                                           writer="src.api.routers.ohlcv.backfill_cg_pro")
        asyncio.create_task(_bg())
        return {"started": True, "panel": panel, "days": days, "n_pairs": len(pairs),
                "symbols": [p[0] for p in pairs] if only else None,
                "skipped_no_coin_id": skipped,
                "verify": "select outcome, reason, detail from loop_attempt where loop_name='_backfill_cg_pro' order by at desc limit 1"}

    by_class = []
    for _ac, _pairs in sorted(groups.items()):
        # `resolved` 来自 `cg_known_coin_map` RPC(vendor-supplied mapping),
        # 不是 endpoint 自己猜的 —— 应走 `vendor_paired` 通路,允许 not-checkable
        # 时放行(S-307)。改前不传此参,所有映射都被「未校验」挡死(本 session 实测
        # 24/24 拒收);改后 vendor_paired=True 的标的可直接写入。
        _res = await backfill(_pairs, start=end - _td(days=days), end=end,
                              asset_class=_ac, dest=dest, dry_run=dry_run,
                              vendor_paired=set(resolved.keys()))
        by_class.append({"asset_class": _ac, "n_pairs": len(_pairs),
                         **_res.as_payload()})

    # 跳过的标的必须出现在返回里。**一个不报「我少做了什么」的回填,
    # 会让下一个人以为面板是全的**(S-166 的形状)。
    # ⚠️ `as_payload()` 返回的键是 `status`("ok"/"degraded"),**没有 `ok`**。
    # 我第一版写 `all(g.get("ok") ...)` —— 那会对一堆 None 求值,
    # **全部失败也返回 True**。一个把失败报成成功的汇总,比不汇总更坏。
    return {
        "ok": bool(by_class) and all(g.get("status") == "ok" for g in by_class),
        "panel": panel,
        "dry_run": dry_run,
        "dest": dest,
        "days": days,
        "start": (end - _td(days=days)).isoformat(),
        "end": end.isoformat(),
        "n_pairs": len(pairs),
        "skipped_no_coin_id": skipped,
        "by_asset_class": by_class,
    }
