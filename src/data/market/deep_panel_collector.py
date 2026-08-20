"""
Daily collector for the deep research panel (S-179, 2026-08-19).

WHAT WAS WRONG. `ohlcv_daily` holds 262 crypto symbols back to 2017 under
`source='binance_hist'` — the panel every historical study runs on. It was
loaded once by a backfill and **no daily collector ever covered it**. Measured
2026-08-19 it was 11 days stale, which silently blocked the depth-divergence
forward record, any embedding rebuild, and anything else that needs today.

`collect_ohlcv` covers 58 symbols (ASSETS_CONFIG, the CIS universe) and always
did. This is not a broken feed; it is a feed that was never built.

WHY BINANCE AND NOT COINGECKO. Volumetrically CoinGecko Pro would do it — Jazz
is right about that. But this repo measured the thing that decides it (S-106 /
S-107):

    "bar convention is a property of the SOURCE, not of the class"
    >1% open gaps: Crypto 31.3% · L1 73.7% · L2 79.5% · DeFi 83.5%

Nine years of this panel are Binance bars. Appending CoinGecko bars from
2026-08-08 onward would splice two conventions into one series, and any study
crossing that date would read the discontinuity as market structure. S-106 made
exactly that mistake once already. Same source in, same source forward.

`data-api.binance.vision` is used deliberately: api.binance.com is geo-blocked
from Railway US, and `get_klines_binance` already routes to the mirror.

CONCURRENCY IS CAPPED. 262 symbols fired at once is a burst that gets an IP
banned, and the ban would look exactly like the stale feed this replaces.
`_CONCURRENCY` matches the 8 that `collect_ohlcv` already settled on, with a
small inter-batch pause. A collector that takes 30 seconds and finishes beats
one that takes 3 and gets throttled.

PARTIAL RUNS ARE VISIBLE, NOT AVERAGED AWAY. The return value reports
`symbols_ok`, `symbols_failed` and the failure reasons. A run that reaches 40 of
262 must not read like a quiet day — that collapse is what let the panel sit
stale for eleven days while `/internal/loop-health` reported "flowing" off a
single fresh BTC row.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("deep_panel")

# Matches collect_ohlcv's settled value. Binance weight for a 1d klines call is
# small; the risk is connection burst, not weight budget.
_CONCURRENCY = 8
_BATCH_PAUSE_S = 0.25

# Below this the run is a failure, not a thin day. Chosen to sit under normal
# attrition (a handful of delisted pairs 404) and well above a throttle event.
_MIN_OK_FRACTION = 0.70

_DEFAULT_DAYS = 14   # a fortnight of overlap; upsert makes re-writes free


async def deep_panel_symbols() -> list[str]:
    """Symbols that already have binance_hist history — i.e. the panel itself.

    Driven off the DATA rather than the `assets` registry on purpose. Measured
    2026-08-19: 487 registry rows carry monitor_daily=true with `class` NULL and
    zero of them are fresh, because nothing can route a symbol whose class is
    unknown. Fixing that registry is worth doing and is not a prerequisite for
    keeping the panel current — the panel knows what it is.
    """
    from src.api.store import _SB_URL, _SB_KEY, _supabase_request_with_retry
    if not _SB_URL or not _SB_KEY:
        return []
    url = (f"{_SB_URL}/rest/v1/ohlcv_daily"
           f"?select=symbol&source=eq.binance_hist&limit=100000")
    try:
        r = await _supabase_request_with_retry(
            "GET", url, headers={"apikey": _SB_KEY,
                                 "Authorization": f"Bearer {_SB_KEY}"})
        if not r or r.status_code != 200:
            return []
        return sorted({row["symbol"].upper() for row in r.json() if row.get("symbol")})
    except Exception as e:                                   # noqa: BLE001
        _log.warning("[DEEP] symbol list failed: %s", e)
        return []


async def _fetch_one(symbol: str, days: int) -> tuple[str, list[dict], str | None]:
    """One symbol. Returns (symbol, rows, error). Never raises."""
    from src.data.market.data_layer import get_klines_binance
    pair = symbol if symbol.upper().endswith("USDT") else f"{symbol.upper()}USDT"
    try:
        kl = await get_klines_binance(pair, "1d", months=max(1, days // 30 + 1))
    except Exception as e:                                   # noqa: BLE001
        return symbol, [], f"{type(e).__name__}: {str(e)[:80]}"
    if not kl:
        # A delisted pair answers empty. Distinguished from an error so the
        # summary can tell attrition from an outage.
        return symbol, [], "empty (delisted or unlisted pair?)"

    rows = []
    for k in kl[-days:]:
        try:
            ts = int(k["time"]) / 1000.0
            rows.append({
                "symbol": symbol.upper(),
                "asset_class": "Crypto",
                "trade_date": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                "open": float(k["open"]), "high": float(k["high"]),
                "low": float(k["low"]), "close": float(k["close"]),
                "volume": float(k["volume"]),
                # SAME LABEL AS THE HISTORY, deliberately. 'hist' is a misnomer
                # now, but the label's job is to mark the bar convention, and a
                # second label for the same convention would fragment the series
                # for every query that filters on source.
                "source": "binance_hist",
            })
        except (KeyError, TypeError, ValueError):
            continue
    return symbol, rows, None


async def collect_deep_panel(days: int = _DEFAULT_DAYS,
                             symbols: list[str] | None = None) -> dict[str, Any]:
    """Refresh the deep panel. Idempotent; safe to run repeatedly."""
    from src.api.store import supabase_upsert_table

    syms = symbols or await deep_panel_symbols()
    if not syms:
        return {"ok": False, "error": "no deep-panel symbols resolved",
                "note": "either Supabase is unreachable or binance_hist is empty"}

    started = datetime.now(timezone.utc)
    sem = asyncio.Semaphore(_CONCURRENCY)
    all_rows: list[dict] = []
    failures: dict[str, str] = {}

    async def _go(s: str):
        async with sem:
            sym, rows, err = await _fetch_one(s, days)
            if err:
                failures[sym] = err
            else:
                all_rows.extend(rows)
            await asyncio.sleep(_BATCH_PAUSE_S)

    await asyncio.gather(*[_go(s) for s in syms])

    ok_n = len(syms) - len(failures)
    frac = ok_n / len(syms) if syms else 0.0

    # ── S-190 (2026-08-20): the floor must BLOCK, not annotate ───────────────
    # This function's own docstring says "a run that reaches 40 of 262 must not
    # read like a quiet day", citing the eleven days the panel sat stale while
    # loop-health reported "flowing" off one fresh BTC row. `_MIN_OK_FRACTION`
    # was then wired only into `out["ok"]` — the write went ahead regardless.
    #
    # Measured 2026-08-20, one day after shipping: exactly ONE symbol (BCH) has
    # a bar since 08-14. The collector had been writing that single symbol every
    # run, reporting ok=False to a print statement nobody reads, and leaving
    # `max(trade_date)` at today — so every freshness check in the system saw a
    # current panel. I diagnosed the failure in the docstring and reproduced it
    # one function later.
    #
    # A partial panel day is not a thin panel day, it is a DIFFERENT OBJECT: any
    # cross-sectional study reading 2026-08-20 gets a one-symbol universe and no
    # way to know. A visible gap is recoverable; a day that silently contains
    # one asset corrupts every study that crosses it.
    if all_rows and frac < _MIN_OK_FRACTION:
        _log.error(
            "[DEEP] REFUSING TO WRITE — only %s/%s symbols returned data (%.0f%%, "
            "floor %.0f%%). Writing them would leave max(trade_date) at today and "
            "make the panel read as current. Sample failures: %s",
            ok_n, len(syms), frac * 100, _MIN_OK_FRACTION * 100,
            dict(list(failures.items())[:5]))
        return {
            "ok": False,
            "symbols_total": len(syms), "symbols_ok": ok_n,
            "symbols_failed": len(failures), "ok_fraction": round(frac, 3),
            "rows_built": len(all_rows), "rows_upserted": 0, "written": False,
            "refused": True,
            "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
            "failure_sample": dict(list(failures.items())[:8]),
            "diagnosis": (
                f"only {ok_n}/{len(syms)} symbols ({frac:.0%}) — below the "
                f"{_MIN_OK_FRACTION:.0%} floor. Write REFUSED so the gap stays "
                f"visible rather than being papered over by a partial day."),
        }

    written = False
    if all_rows:
        # Chunked: a single 250k-row body is a timeout, not a write.
        written = True
        for i in range(0, len(all_rows), 2000):
            if not await supabase_upsert_table(
                    "ohlcv_daily", all_rows[i:i + 2000],
                    on_conflict="symbol,trade_date,source"):
                written = False
                break

    out = {
        "ok": bool(written) and frac >= _MIN_OK_FRACTION,
        "symbols_total": len(syms),
        "symbols_ok": ok_n,
        "symbols_failed": len(failures),
        "ok_fraction": round(frac, 3),
        "rows_upserted": len(all_rows) if written else 0,
        "rows_built": len(all_rows),
        "written": written,
        "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        # First few reasons, not a count. "12 failed" is not actionable;
        # "12 failed with HTTP 418" is.
        "failure_sample": dict(list(failures.items())[:8]),
    }
    if frac < _MIN_OK_FRACTION:
        out["diagnosis"] = (
            f"only {ok_n}/{len(syms)} symbols returned data ({frac:.0%}, floor "
            f"{_MIN_OK_FRACTION:.0%}). Below this it is a throttle or an outage, "
            f"not normal delisting attrition — do NOT read the result as a quiet day.")
    if not written and all_rows:
        out["diagnosis"] = ("rows built but the upsert was declined — check "
                            "APP_ROLE=production and the Supabase log")

    (_log.warning if not out["ok"] else _log.info)(
        "[DEEP] %s/%s symbols · %s rows · %.1fs%s",
        ok_n, len(syms), out["rows_upserted"], out["elapsed_s"],
        "  ⚠️ " + out.get("diagnosis", "") if not out["ok"] else "")
    return out
