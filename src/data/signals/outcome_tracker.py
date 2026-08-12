"""
Signal Outcome Tracker — Railway-side 30-day directional outcome resolver.

The track-record number for LP conversations: of every OUTPERFORM / STRONG
OUTPERFORM signal we logged, what fraction was directionally correct 30 days
later? This module resolves that, independent of the Mac Mini OHLCV pipeline.

Why a Railway-side tracker (vs the Mac Mini one in Shadow/):
  - Mac Mini's signal_outcome_tracker.py depends on local OHLCV parquet files
    (/Volumes/CometCloudAI/data/ohlcv/) + ccxt/Binance. That pipeline is not
    yet running, so outcome_30d never gets populated.
  - This path uses sources already available on Railway:
        crypto  → CoinGecko market_chart history (get_cg_price_history)
        TradFi  → yfinance daily history
    No parquet, no Binance geo-block.
  - Both paths write the SAME signal_journal columns, idempotently (only ever
    touch rows where outcome_30d IS NULL), so they can coexist safely.

For each signal aged >= 30 days with outcome_30d IS NULL:
  1. target = signal_date + 30 days
  2. fetch the daily close nearest `target` from the right source
  3. return_pct_30d = (price_at_30d - entry_price) / entry_price
  4. classify:  WIN   if return >=  0%
                LOSS  if return <= -10%
                EXPIRED otherwise (flat / neutral — neither win nor loss)
     EXPIRED is also used when a signal is too old (> grace window) and no
     price could be recovered.
  5. write outcome_30d / return_pct_30d / price_at_30d / outcome_source back.

Exposes:
  async run_outcome_tracker(dry_run=False, limit=500) -> dict
"""
from __future__ import annotations

import os
import json
import math
import logging
import asyncio
from datetime import datetime, timezone, timedelta

import httpx

_log = logging.getLogger("outcome_tracker")

# ── Config ───────────────────────────────────────────────────────────────────
_SB_URL   = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY   = os.environ.get("SUPABASE_KEY", "")
_SB_TABLE = "signal_journal"

OUTCOME_LOOKBACK_DAYS = 30
WIN_THRESHOLD   = 0.0      # return >= 0%   at 30d  → WIN
LOSS_THRESHOLD  = -0.10    # return <= -10% at 30d  → LOSS
GRACE_DAYS      = 14       # if still unresolved this long past the 30d mark and
                           # no price recoverable → mark EXPIRED (no data)
PRICE_MATCH_TOLERANCE_DAYS = 3   # accept a daily close within ±N days of target

# Asset classes priced via yfinance (everything else → CoinGecko)
_TRADFI_CLASSES = {
    "US Equity", "US Bond", "EM Equity", "DM Equity",
    "Commodity", "TradFi", "Equity", "Bond",
}

# Symbol → CoinGecko coin id (covers the live CIS universe).
_CG_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
    "NEAR": "near", "SUI": "sui", "APT": "aptos", "HYPE": "hyperliquid",
    "ARB": "arbitrum", "OP": "optimism", "LINK": "chainlink", "UNI": "uniswap",
    "AAVE": "aave", "MKR": "maker", "LTC": "litecoin", "ATOM": "cosmos",
    "ALGO": "algorand", "HBAR": "hedera-hashgraph", "INJ": "injective-protocol",
    "TIA": "celestia", "SEI": "sei-network", "ENA": "ethena", "ONDO": "ondo-finance",
    "PENDLE": "pendle", "MANTLE": "mantle", "MNT": "mantle", "STX": "blockstack",
    "RNDR": "render-token", "RENDER": "render-token", "FET": "fetch-ai",
    "TAO": "bittensor", "GRT": "the-graph", "LDO": "lido-dao", "JUP": "jupiter-exchange-solana",
    "JTO": "jito-governance-token", "PYTH": "pyth-network", "WLD": "worldcoin-wld",
    "FIL": "filecoin", "IMX": "immutable-x", "STRK": "starknet", "ZK": "zksync",
    "POL": "polygon-ecosystem-token", "TON": "the-open-network", "KAS": "kaspa",
    "DOGE": "dogecoin", "TRX": "tron", "ETC": "ethereum-classic", "XLM": "stellar",
    "VET": "vechain", "RUNE": "thorchain", "DYDX": "dydx-chain", "GMX": "gmx",
    "SNX": "synthetix-network-token", "COMP": "compound-governance-token",
}


# ── Supabase helpers (self-contained; no router import → no circular dep) ─────
def _sb_headers(write: bool = False) -> dict:
    h = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    if write:
        h["Content-Type"] = "application/json"
        h["Prefer"] = "return=minimal"
    return h


async def _sb_get_pending(client: httpx.AsyncClient, limit: int) -> list:
    """Signals aged >= lookback with no outcome yet."""
    if not _SB_URL or not _SB_KEY:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=OUTCOME_LOOKBACK_DAYS)).isoformat()
    try:
        resp = await client.get(
            f"{_SB_URL}/rest/v1/{_SB_TABLE}",
            params={
                "outcome_30d": "is.null",
                "signal_date": f"lt.{cutoff}",
                # entry_price no longer required — we backfill it from ohlcv_daily below
                "order": "signal_date.asc",
                "limit": str(limit),
                "select": "id,symbol,asset_class,entry_price,signal_date,grade,signal",
            },
            headers=_sb_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        _log.warning("[OUTCOME] pending query HTTP %s", resp.status_code)
    except Exception as e:
        _log.warning("[OUTCOME] pending query error: %s", e)
    return []


async def _sb_patch(client: httpx.AsyncClient, row_id: int, data: dict) -> bool:
    if not _SB_URL or not _SB_KEY:
        return False
    try:
        resp = await client.patch(
            f"{_SB_URL}/rest/v1/{_SB_TABLE}",
            content=json.dumps(data),
            params={"id": f"eq.{row_id}"},
            headers=_sb_headers(write=True),
            timeout=15,
        )
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        _log.warning("[OUTCOME] patch error id=%s: %s", row_id, e)
        return False


# ── Price-at-date lookups ────────────────────────────────────────────────────
import re as _re

_TS_RE = _re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?\s*"
    r"(Z|[+-]\d{2}(?::?\d{2})?)?$"
)


def _parse_dt(s: str) -> datetime | None:
    """
    Tolerant ISO/Postgres timestamp parser. Handles space or 'T' separator,
    arbitrary fractional-second precision (Postgres emits e.g. '.26974'), and
    'Z' / '+00' / '+0000' / '+00:00' offsets — none of which bare
    datetime.fromisoformat() reliably accepts on Python 3.10.
    """
    if not s:
        return None
    s = str(s).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    m = _TS_RE.match(s)
    if not m:
        return None
    date_p, time_p, frac, tz = m.groups()
    micro = int((frac or "0")[:6].ljust(6, "0")) if frac else 0
    if not tz or tz == "Z":
        tzinfo = timezone.utc
    else:
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        hh = int(digits[:2]); mm = int(digits[2:4]) if len(digits) >= 4 else 0
        tzinfo = timezone(sign * timedelta(hours=hh, minutes=mm))
    try:
        y, mo, d = (int(x) for x in date_p.split("-"))
        hr, mi, se = (int(x) for x in time_p.split(":"))
        return datetime(y, mo, d, hr, mi, se, micro, tzinfo=tzinfo)
    except Exception:
        return None


async def _crypto_price_at(symbol: str, target: datetime, age_days: float) -> float | None:
    """Nearest daily close to `target` from CoinGecko market_chart history."""
    coin_id = _CG_IDS.get(symbol.upper())
    if not coin_id:
        _log.info("[OUTCOME] no CoinGecko id for %s — skipping", symbol)
        return None
    # Pull a window that comfortably spans the target (age + grace + buffer).
    days = int(min(365, math.ceil(age_days) + GRACE_DAYS + 2))
    try:
        from src.data.market.data_layer import get_cg_price_history
        hist = await get_cg_price_history(coin_id, days)
    except Exception as e:
        _log.warning("[OUTCOME] CG history error %s: %s", symbol, e)
        return None
    prices = (hist or {}).get("prices") or []
    return _nearest_close(prices, target)


def _nearest_close(prices: list, target: datetime) -> float | None:
    """prices = [[ts_ms, price], ...]; return price nearest target within tolerance."""
    if not prices:
        return None
    target_ms = target.timestamp() * 1000.0
    tol_ms = PRICE_MATCH_TOLERANCE_DAYS * 86400_000
    best_px, best_dist = None, None
    for row in prices:
        try:
            ts, px = float(row[0]), float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        dist = abs(ts - target_ms)
        if best_dist is None or dist < best_dist:
            best_dist, best_px = dist, px
    if best_px is not None and best_dist is not None and best_dist <= tol_ms:
        return best_px
    return None


async def _ohlcv_close_at(client: httpx.AsyncClient, symbol: str, target: datetime,
                          window_days: int = 4) -> float | None:
    """Nearest daily close to `target` from the `ohlcv_daily_canonical` view (Supabase).

    The view is the deterministic one-row-per-(symbol, trade_date) pick — native venue >
    aggregator > free, with coingecko grok_open snapshot artifacts marked `open_usable=false`.
    Reads from the raw `ohlcv_daily` table would re-introduce OPEN RISK #6: identical
    `(symbol, trade_date)` pairs across `coingecko` / `eodhd` / `yfinance` / `binance_hist`
    sources with closes up to 5% apart for the same day, and `min(|trade_date - target|)`
    is unstable when multiple rows share the same trade_date. The view resolves source
    precedence server-side; this client reads one row per day. Returns None if we didn't
    store it. The 'use our own data first' path — no external fetch, no waiting. Per
    Jazz's mandate: anything we retrieved should be in our DB."""
    if not _SB_URL or not _SB_KEY:
        return None
    lo = (target - timedelta(days=window_days)).date().isoformat()
    hi = (target + timedelta(days=window_days)).date().isoformat()
    try:
        resp = await client.get(
            f"{_SB_URL}/rest/v1/ohlcv_daily_canonical",
            params=[("symbol", f"eq.{symbol.upper()}"),
                    ("trade_date", f"gte.{lo}"), ("trade_date", f"lte.{hi}"),
                    ("select", "trade_date,close"), ("order", "trade_date.asc")],
            headers=_sb_headers(), timeout=15,
        )
        if resp.status_code != 200:
            return None
        rows = [r for r in resp.json() if r.get("close")]
        if not rows:
            return None
        tgt = target.date()
        best = min(rows, key=lambda r: abs(datetime.fromisoformat(r["trade_date"]).date() - tgt))
        return float(best["close"])
    except Exception as e:
        _log.warning("[OUTCOME] ohlcv_canonical read %s: %s", symbol, e)
        return None


def _tradfi_price_at_sync(symbol: str, target: datetime) -> float | None:
    """Nearest daily close to `target` via yfinance (sync — call in a thread)."""
    try:
        import yfinance as yf
    except Exception as e:
        _log.warning("[OUTCOME] yfinance unavailable: %s", e)
        return None
    try:
        start = (target - timedelta(days=PRICE_MATCH_TOLERANCE_DAYS + 1)).date()
        end = (target + timedelta(days=PRICE_MATCH_TOLERANCE_DAYS + 2)).date()
        hist = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat())
        if hist is None or hist.empty:
            return None
        closes = hist["Close"].dropna()
        if closes.empty:
            return None
        # nearest index date to target
        target_d = target.date()
        best_px, best_dist = None, None
        for idx, px in closes.items():
            try:
                d = idx.date()
            except Exception:
                continue
            dist = abs((d - target_d).days)
            if best_dist is None or dist < best_dist:
                best_dist, best_px = dist, float(px)
        if best_px is not None and best_dist is not None and best_dist <= PRICE_MATCH_TOLERANCE_DAYS:
            return best_px
    except Exception as e:
        _log.warning("[OUTCOME] yfinance error %s: %s", symbol, e)
    return None


def _classify(ret: float) -> str:
    if ret >= WIN_THRESHOLD:
        return "WIN"
    if ret <= LOSS_THRESHOLD:
        return "LOSS"
    return "EXPIRED"   # flat / neutral band


# ── Benchmark-relative (alpha) scoring ───────────────────────────────────────
# An OUTPERFORM signal is a RELATIVE claim: it says the asset will beat its peer
# group, not that it will rise in absolute terms. Scoring absolute return in a
# down market makes every held name a "loss" even when it outperformed — the
# 0%-win-rate artifact. So we score ALPHA = asset_return − benchmark_return over
# the same 30d window. Benchmark: BTC for crypto, SPY for TradFi.
ALPHA_WIN  = 0.005    # outperformed the benchmark by ≥0.5% → WIN
ALPHA_LOSS = -0.005   # underperformed by ≥0.5% → LOSS ; flat band = EXPIRED
_CRYPTO_BENCH = "BTC"
_TRADFI_BENCH = "SPY"


def _benchmark_for(cls: str) -> str:
    return _TRADFI_BENCH if cls in _TRADFI_CLASSES else _CRYPTO_BENCH


def _classify_alpha(alpha: float) -> str:
    if alpha >= ALPHA_WIN:
        return "WIN"
    if alpha <= ALPHA_LOSS:
        return "LOSS"
    return "EXPIRED"


async def _bench_price(client, bench_sym: str, target, age_days: float, cache: dict):
    """Benchmark close nearest `target` — OUR ohlcv_daily first, external fallback.
    Cached by (symbol, date) within a run."""
    key = (bench_sym, target.date().isoformat())
    if key in cache:
        return cache[key]
    p = await _ohlcv_close_at(client, bench_sym, target)   # our own data first
    if p is None:
        if bench_sym == _TRADFI_BENCH:
            p = await asyncio.to_thread(_tradfi_price_at_sync, bench_sym, target)
        else:
            p = await _crypto_price_at(bench_sym, target, age_days)
    cache[key] = p
    return p


# ── Main entrypoint ──────────────────────────────────────────────────────────
async def run_outcome_tracker(dry_run: bool = False, limit: int = 500) -> dict:
    """
    Resolve 30-day outcomes for all matured, unresolved signals.

    dry_run=True computes everything but writes nothing — used for verification.
    Returns a summary dict (counts + per-signal results).
    """
    started = datetime.now(timezone.utc)
    if not _SB_URL or not _SB_KEY:
        return {"status": "skipped", "reason": "supabase_not_configured"}

    async with httpx.AsyncClient(timeout=20) as client:
        pending = await _sb_get_pending(client, limit)
        results = []
        counts = {"WIN": 0, "LOSS": 0, "EXPIRED": 0, "no_data": 0, "updated": 0}
        bench_cache: dict = {}   # (benchmark_sym, date) → price, within this run

        for sig in pending:
            sid = sig.get("id")
            sym = (sig.get("symbol") or "").upper()
            entry = sig.get("entry_price")
            sig_dt = _parse_dt(sig.get("signal_date"))
            cls = sig.get("asset_class") or ""
            if not (sid and sym and sig_dt):
                continue

            target = sig_dt + timedelta(days=OUTCOME_LOOKBACK_DAYS)
            age_days = (started - sig_dt).total_seconds() / 86400.0
            is_tradfi = cls in _TRADFI_CLASSES

            # Entry — backfill from OUR ohlcv_daily if the signal was logged without one
            # (fixes the aged null-entry gap: the data is in our DB, use it).
            entry_backfilled = False
            if not (entry and entry > 0):
                entry = await _ohlcv_close_at(client, sym, sig_dt)
                entry_backfilled = bool(entry and entry > 0)
            if not (entry and entry > 0):
                if age_days > OUTCOME_LOOKBACK_DAYS + GRACE_DAYS and not dry_run:
                    await _sb_patch(client, sid, {"outcome_30d": "EXPIRED",
                        "outcome_source": "no_entry_in_db", "outcome_at": started.isoformat()})
                    counts["EXPIRED"] += 1; counts["no_data"] += 1; counts["updated"] += 1
                results.append({"id": sid, "symbol": sym, "outcome": "EXPIRED" if age_days > OUTCOME_LOOKBACK_DAYS + GRACE_DAYS else "PENDING", "reason": "no_entry_price"})
                continue

            # Exit — OUR ohlcv_daily first (no external fetch, no waiting); fall back only if absent.
            price = await _ohlcv_close_at(client, sym, target)
            source = "ohlcv_daily"
            if price is None:
                if is_tradfi:
                    price = await asyncio.to_thread(_tradfi_price_at_sync, sym, target)
                    source = "yfinance"
                else:
                    price = await _crypto_price_at(sym, target, age_days)
                    source = "coingecko"

            if price is None:
                # Too old to keep waiting → close out as EXPIRED (no data).
                if age_days > OUTCOME_LOOKBACK_DAYS + GRACE_DAYS:
                    update = {
                        "outcome_30d": "EXPIRED",
                        "return_pct_30d": None,
                        "price_at_30d": None,
                        "outcome_source": f"{source}:no_data",
                        "outcome_at": started.isoformat(),
                    }
                    counts["EXPIRED"] += 1
                    counts["no_data"] += 1
                    if not dry_run and await _sb_patch(client, sid, update):
                        counts["updated"] += 1
                    results.append({"id": sid, "symbol": sym, "outcome": "EXPIRED", "reason": "no_price_data"})
                else:
                    results.append({"id": sid, "symbol": sym, "outcome": "PENDING", "reason": "price_not_yet_available"})
                continue

            ret = (price - entry) / entry   # absolute 30d return (kept for reference)

            # Benchmark-relative (alpha) — the honest score for an OUTPERFORM signal.
            bench_sym = _benchmark_for(cls)
            alpha = None
            bench_ret = None
            if bench_sym != sym:   # don't benchmark BTC against itself
                b_entry = await _bench_price(client, bench_sym, sig_dt, age_days, bench_cache)
                b_exit  = await _bench_price(client, bench_sym, target, age_days, bench_cache)
                if b_entry and b_exit and b_entry > 0:
                    bench_ret = (b_exit - b_entry) / b_entry
                    alpha = ret - bench_ret

            if alpha is not None:
                outcome = _classify_alpha(alpha)          # relative: outperformed peer?
                outcome_basis = f"{source}:vs_{bench_sym}"
            else:
                outcome = _classify(ret)                  # fallback: absolute (BTC itself / no bench data)
                outcome_basis = f"{source}:absolute"

            counts[outcome] += 1
            update = {
                "outcome_30d": outcome,
                "return_pct_30d": round(ret * 100, 4),    # absolute, for transparency
                "price_at_30d": round(price, 8),
                "benchmark_symbol": bench_sym if alpha is not None else None,
                "benchmark_return_30d": round(bench_ret * 100, 4) if bench_ret is not None else None,
                "alpha_30d": round(alpha * 100, 4) if alpha is not None else None,
                "outcome_source": outcome_basis,
                "outcome_at": started.isoformat(),
            }
            if entry_backfilled:
                update["entry_price"] = round(entry, 8)   # persist the OHLCV-backfilled entry
            if not dry_run and await _sb_patch(client, sid, update):
                counts["updated"] += 1
            results.append({
                "id": sid, "symbol": sym, "outcome": outcome,
                "return_pct_30d": round(ret * 100, 2),
                "alpha_30d": round(alpha * 100, 2) if alpha is not None else None,
                "source": outcome_basis,
            })

    resolved = counts["WIN"] + counts["LOSS"] + counts["EXPIRED"]
    win_den = counts["WIN"] + counts["LOSS"]
    summary = {
        "status": "ok",
        "dry_run": dry_run,
        "as_of": started.isoformat(),
        "pending_examined": len(pending),
        "resolved": resolved,
        "wins": counts["WIN"],
        "losses": counts["LOSS"],
        "expired": counts["EXPIRED"],
        "no_data": counts["no_data"],
        "rows_written": counts["updated"],
        # directional win rate excludes flat/EXPIRED & no-data, per LP framing
        "directional_win_rate_pct": round(counts["WIN"] / win_den * 100, 1) if win_den else None,
        "results": results,
        "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
    }
    _log.info(
        "[OUTCOME] examined=%s resolved=%s win=%s loss=%s expired=%s written=%s dry=%s",
        len(pending), resolved, counts["WIN"], counts["LOSS"], counts["EXPIRED"],
        counts["updated"], dry_run,
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    dry = "--write" not in sys.argv
    print(json.dumps(asyncio.run(run_outcome_tracker(dry_run=dry)), indent=2))
