"""Hyperliquid daily candles — the venue we will actually trade on (S-192).

WHY THIS AND NOT BINANCE. Jazz, 2026-08-20: "不是有用 hyperliquid 吗?之后我们要
接 hyperliquid 去交易的呀,直接用起来。" That reframes a problem I had been
solving badly for two days, and it is right on three separate counts:

1. IT REACHES. `data-api.binance.vision` is what `deep_panel_collector` uses
   because api.binance.com is geo-blocked from Railway US. Measured 2026-08-20,
   exactly ONE of 262 panel symbols had a bar since 08-14 — the mirror is not
   working either. Hyperliquid is a public DEX API, no key, not geo-blocked;
   `_fetch_hyperliquid_daily` in `routers/ohlcv.py` has said so in its docstring
   since 2026-07-23. I built a Binance collector anyway.

2. ITS BARS CARRY THEIR OWN DATE. Every candle has a `t` epoch. The CoinGecko
   writer labels rows with the WRITE date instead, which is how our
   `trade_date = 2026-08-19` row ended up holding 2026-08-18's close (measured
   against HL: ours 64,686.30, HL 08-18 64,696, HL 08-19 69,323). A source that
   ships the timestamp cannot drift like that.

3. IT IS THE VENUE. A paper book marked on CoinGecko spot and executed on
   Hyperliquid perps is a splice — it just shows up as unexplained slippage
   rather than as a discontinuity in a chart. Marks should come from where the
   fills will.

WHAT THIS COSTS, STATED PLAINLY. Of the 262-symbol Binance research panel, only
**88 (34%)** are listed on Hyperliquid; HL lists 144 the panel has never seen.
So this is not a drop-in replacement for the historical panel — it is a
different, SMALLER, TRADEABLE universe. The 174 non-overlapping symbols are
assets we can research and cannot execute, which is the same class of error as
building sleeve ④ before sleeve ① : work that cannot reach a book.

SOURCE LABEL. Writes `source='hyperliquid'`, never mixed into `binance_hist`.
Bar convention is a property of the source (S-106/S-107: >1% open gaps run
31.3% on Crypto vs 83.5% on DeFi), and perp marks are not spot closes. Two
labels, two conventions, no splice.

THE FLOOR BLOCKS. See S-190: `deep_panel_collector` had its coverage floor wired
into the return value only, so a 1-of-262 run still wrote, and `max(trade_date)`
then read as current. Here the floor returns before the write.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

_log = logging.getLogger("hyperliquid")

_INFO_URL = "https://api.hyperliquid.xyz/info"
SOURCE = "hyperliquid"

_CONCURRENCY = 8
_BATCH_PAUSE_S = 0.15
_MIN_OK_FRACTION = 0.70
_DEFAULT_DAYS = 10
_TIMEOUT = 25.0


async def hyperliquid_universe(client: httpx.AsyncClient | None = None) -> list[str]:
    """Every perp currently listed. This IS our tradeable universe."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await client.post(_INFO_URL, json={"type": "meta"})
        r.raise_for_status()
        return [a["name"] for a in r.json().get("universe", []) if a.get("name")]
    except Exception as e:                                    # noqa: BLE001
        _log.warning("[HL] universe fetch failed: %s", e)
        return []
    finally:
        if own:
            await client.aclose()


async def _fetch_one(client: httpx.AsyncClient, coin: str,
                     days: int) -> tuple[str, list[dict], str | None]:
    """One symbol's daily candles. Never raises."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - (days + 2) * 86_400_000
    try:
        r = await client.post(_INFO_URL, json={
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": "1d",
                    "startTime": start_ms, "endTime": end_ms}})
        r.raise_for_status()
        candles = r.json()
    except Exception as e:                                    # noqa: BLE001
        return coin, [], f"{type(e).__name__}: {str(e)[:80]}"
    if not isinstance(candles, list) or not candles:
        return coin, [], "empty"

    rows = []
    for k in candles:
        try:
            # ⚠️ THE DATE COMES FROM THE BAR, NEVER FROM THE CLOCK.
            # This single line is the difference between this collector and the
            # CoinGecko one, whose rows are stamped with the write date and are
            # therefore all off by one day (S-191). A bar knows when it is; the
            # process writing it does not.
            ts = int(k["t"]) / 1000.0
            close = float(k["c"])
            rows.append({
                "symbol": coin.upper(),
                "asset_class": "Crypto",
                "trade_date": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                "open":  float(k.get("o") or close),
                "high":  float(k.get("h") or close),
                "low":   float(k.get("l") or close),
                "close": close,
                "volume": float(k.get("v") or 0.0),
                "source": SOURCE,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return coin, rows, None


async def collect_hyperliquid(days: int = _DEFAULT_DAYS,
                              symbols: list[str] | None = None) -> dict[str, Any]:
    """Refresh Hyperliquid daily bars. Idempotent; safe to run repeatedly."""
    from src.api.store import supabase_upsert_table

    started = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        syms = symbols or await hyperliquid_universe(client)
        if not syms:
            return {"ok": False, "error": "no Hyperliquid symbols resolved",
                    "note": "meta endpoint unreachable or empty"}

        sem = asyncio.Semaphore(_CONCURRENCY)
        all_rows: list[dict] = []
        failures: dict[str, str] = {}

        async def _go(s: str):
            async with sem:
                sym, rows, err = await _fetch_one(client, s, days)
                if err:
                    failures[sym] = err
                else:
                    all_rows.extend(rows)
                await asyncio.sleep(_BATCH_PAUSE_S)

        await asyncio.gather(*[_go(s) for s in syms])

    ok_n = len(syms) - len(failures)
    frac = ok_n / len(syms) if syms else 0.0
    elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 1)

    # S-190: the floor BLOCKS. A partial panel day is not a thin day, it is a
    # different object — a cross-sectional read of it gets a handful of symbols
    # with no way to know, and `max(trade_date)` then reports the feed as
    # current. A visible gap is recoverable; a silently partial day is not.
    if all_rows and frac < _MIN_OK_FRACTION:
        _log.error("[HL] REFUSING TO WRITE — %s/%s symbols (%.0f%%, floor %.0f%%). "
                   "Sample: %s", ok_n, len(syms), frac * 100,
                   _MIN_OK_FRACTION * 100, dict(list(failures.items())[:5]))
        return {"ok": False, "refused": True, "written": False,
                "symbols_total": len(syms), "symbols_ok": ok_n,
                "symbols_failed": len(failures), "ok_fraction": round(frac, 3),
                "rows_built": len(all_rows), "rows_upserted": 0,
                "elapsed_s": elapsed,
                "failure_sample": dict(list(failures.items())[:8]),
                "diagnosis": (f"only {ok_n}/{len(syms)} symbols ({frac:.0%}) — below "
                              f"the {_MIN_OK_FRACTION:.0%} floor. Write REFUSED so the "
                              f"gap stays visible.")}

    written = bool(all_rows)
    if all_rows:
        for i in range(0, len(all_rows), 2000):
            if not await supabase_upsert_table(
                    "ohlcv_daily", all_rows[i:i + 2000],
                    on_conflict="symbol,trade_date,source"):
                written = False
                break

    out = {
        "ok": written and frac >= _MIN_OK_FRACTION,
        "symbols_total": len(syms),
        "symbols_ok": ok_n,
        "symbols_failed": len(failures),
        "ok_fraction": round(frac, 3),
        "rows_built": len(all_rows),
        "rows_upserted": len(all_rows) if written else 0,
        "written": written,
        "elapsed_s": elapsed,
        "latest_bar": max((r["trade_date"] for r in all_rows), default=None),
        "failure_sample": dict(list(failures.items())[:8]),
    }
    if not written and all_rows:
        out["diagnosis"] = ("rows built but the upsert was declined — check "
                            "APP_ROLE=production and the Supabase log")
    (_log.warning if not out["ok"] else _log.info)(
        "[HL] %s/%s symbols · %s rows · latest %s · %.1fs",
        ok_n, len(syms), out["rows_upserted"], out["latest_bar"], elapsed)
    return out


async def tradeable_overlap(panel_symbols: list[str]) -> dict[str, Any]:
    """How much of a research panel can actually be executed on Hyperliquid.

    Exists because the answer surprised me and belongs in front of anyone
    designing a sleeve: measured 2026-08-20, 88 of the 262-symbol Binance panel
    (34%) are listed on HL. Research on the other 174 cannot reach a book.
    """
    hl = set(await hyperliquid_universe())
    panel = {s.upper() for s in panel_symbols}
    both = sorted(panel & hl)
    return {
        "panel_n": len(panel),
        "hyperliquid_n": len(hl),
        "tradeable_n": len(both),
        "tradeable_pct": round(100 * len(both) / len(panel), 1) if panel else 0.0,
        "research_only": sorted(panel - hl),
        "untouched_on_venue": sorted(hl - panel),
    }
