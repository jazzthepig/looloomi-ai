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
    dest: str = Query(default="supabase", pattern="^(local|supabase)$",
                      description="supabase=系统记录(S-361 起默认)· local=本地研究面"),
    days: int = Query(default=2451, ge=90, le=3650,
                      description="回看天数,默认 2451 ≈ 回到 2020-01-01"),
    panel: str = Query(default="cis", pattern="^(cis|all)$",
                       description="cis=CIS 面板交集(默认)· all=cg_coin_map 全量"),
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

    by_class = []
    for _ac, _pairs in sorted(groups.items()):
        _res = await backfill(_pairs, start=end - _td(days=days), end=end,
                              asset_class=_ac, dest=dest, dry_run=dry_run)
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
