"""T-085 7-day × UTC 00/08/16 sweep wrapper.

Acceptance per T-085 card:
  每天 UTC 00 / 08 / 16 三次取订单簿,7 天 = 21 个 snapshot

This script = a SINGLE-shot invocation. It decides which of the 3 UTC slots
this run should belong to, snapshots the order book + ticker, writes
`t085_sweep_<UTC_date>_H00|H08|H16.json` to OUT_DIR.

Usage:
  # cron / launchd fire once per slot:
  python3 sweep_7d.py

The script reads the current UTC hour and routes to the latest slot
within the last 4 hours (so a script firing slightly late still lands
on the intended slot). It will not double-write for the same (date, slot);
downstream aggregator skips duplicates.

Designed so that "fire 21 times across 7 days" = the full sweep.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

# Reuse probe_coverage.py functions
sys.path.insert(0, str(Path(__file__).parent))
from probe_coverage import (
    OUT_DIR, VENUES, SYMBOLS, venue_symbol,
    fetch_order_book_safe, fetch_ticker_safe, depth_within_pct,
)

UTC_SLOTS = (0, 8, 16)


def infer_slot(now_utc: dt.datetime) -> tuple[int, dt.date]:
    """Pick the slot the snapshot belongs to (≤ current hour).

    Returns (slot_hour_utc, slot_date_utc) — date is yesterday if hour < 8.
    """
    h = now_utc.hour
    if h < 8:
        return 0, (now_utc - dt.timedelta(days=1)).date()
    if h < 16:
        return 8, now_utc.date()
    return 16, now_utc.date()


def slot_path(now_utc: dt.datetime, slot_date: dt.date, slot_h: int) -> Path:
    date_str = slot_date.strftime("%Y%m%d")
    return OUT_DIR / f"t085_sweep_{date_str}_H{slot_h:02d}.json"


def slot_already_written(slot_path: Path) -> bool:
    """If the slot path already exists & was written within the last 6h,
    skip to avoid duplicate-write (double-fire of cron).
    """
    if not slot_path.exists():
        return False
    age_h = (dt.datetime.now(dt.timezone.utc).timestamp()
             - slot_path.stat().st_mtime) / 3600.0
    return age_h < 6.0


def main():
    t0 = dt.datetime.now(dt.timezone.utc)
    slot_h, slot_date = infer_slot(t0)
    out_path = slot_path(t0, slot_date, slot_h)
    if slot_already_written(out_path):
        print(f"SKIP: {out_path.name} already written in the last 6h")
        return 0

    print(f"=== T-085 sweep slot UTC {slot_date.strftime('%Y-%m-%d')} H{slot_h:02d} "
          f"(ran at {t0.strftime('%Y-%m-%dT%H:%M:%SZ')}) ===\n")

    # Initialize exchanges (re-uses ccxt)
    import ccxt
    exchanges = {}
    for v in VENUES:
        try:
            klass = getattr(ccxt, v)
            exchanges[v] = klass({"enableRateLimit": True, "timeout": 15000})
            exchanges[v].load_markets()
        except Exception as e:
            print(f"  {v}: SKIP init — {e}")
            exchanges[v] = None

    # Coverage (cheap, no API calls; in-memory only per slot)
    coverage = {}
    for sym in SYMBOLS:
        coverage[sym] = {}
        for v, ex in exchanges.items():
            if ex is None:
                coverage[sym][v] = None
                continue
            ex_sym = venue_symbol(v, sym)
            if ex_sym is None or ex_sym not in ex.markets:
                coverage[sym][v] = None
            else:
                coverage[sym][v] = ex_sym

    # Order book + ticker per covered pair
    rows = []
    ticker_rows = []
    n_probed = 0
    n_ob_hit = 0
    n_ob_miss = 0
    for sym in SYMBOLS:
        for v, ex in exchanges.items():
            ex_sym = coverage[sym][v]
            if ex is None or ex_sym is None:
                continue
            n_probed += 1
            tkr = fetch_ticker_safe(ex, ex_sym)
            if tkr:
                ticker_rows.append({
                    "symbol": sym, "venue": v, "ex_symbol": ex_sym,
                    "last": tkr.get("last"), "bid": tkr.get("bid"), "ask": tkr.get("ask"),
                    "quote_volume_24h_usd": tkr.get("quoteVolume"),
                    "base_volume_24h": tkr.get("baseVolume"),
                    "pct_change_24h": tkr.get("percentage"),
                })
            ob = fetch_order_book_safe(ex, ex_sym, limit=50)
            if ob is None or not ob.get("bids") or not ob.get("asks"):
                n_ob_miss += 1
                continue
            n_ob_hit += 1
            best_bid = ob["bids"][0][0]
            best_ask = ob["asks"][0][0]
            mid = (best_bid + best_ask) / 2.0
            d1 = depth_within_pct(ob, mid, 0.01)
            d2 = depth_within_pct(ob, mid, 0.02)
            spread_bps = (best_ask - best_bid) / mid * 10000.0
            rows.append({
                "slot_utc": f"{slot_date.strftime('%Y-%m-%d')}T{slot_h:02d}:00:00Z",
                "fetched_utc": t0.isoformat(),
                "slot_hour_utc": slot_h,
                "symbol": sym, "venue": v, "ex_symbol": ex_sym,
                "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
                "spread_bps": spread_bps,
                "depth_1pct_bid_usd": d1["bid_usd"],
                "depth_1pct_ask_usd": d1["ask_usd"],
                "depth_1pct_bid_levels": d1["bid_levels"],
                "depth_1pct_ask_levels": d1["ask_levels"],
                "depth_2pct_bid_usd": d2["bid_usd"],
                "depth_2pct_ask_usd": d2["ask_usd"],
                "depth_2pct_bid_levels": d2["bid_levels"],
                "depth_2pct_ask_levels": d2["ask_levels"],
                "quote_volume_24h_usd": tkr.get("quoteVolume") if tkr else None,
            })

    out_path.write_text(json.dumps({
        "fetched_utc": t0.isoformat(),
        "slot_utc": f"{slot_date.strftime('%Y-%m-%d')}T{slot_h:02d}:00:00Z",
        "slot_hour_utc": slot_h,
        "venues": VENUES,
        "n_probed": n_probed,
        "n_ob_hit": n_ob_hit,
        "n_ob_miss": n_ob_miss,
        "depths": rows,
        "tickers": ticker_rows,
    }, indent=2, default=str))
    print(f"WROTE {out_path} ({out_path.stat().st_size} bytes) — "
          f"{n_ob_hit}/{n_probed} OBs hit, slot H{slot_h:02d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
