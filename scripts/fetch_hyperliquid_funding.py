#!/usr/bin/env python3
"""
A-S1 [P1] deliverable for §CROWDING-BREADTH — Hyperliquid funding+OHLCV fetch (Minimax-A).

Per MINIMAX_SYNC §CROWDING-BREADTH 2026-07-18:
  · DATA SOURCE = HYPERLIQUID (Jazz's decision 2026-07-18 — execution venue, funding hourly).
  · The sandbox 44s window can't hold the 50+ sequential funding-pagination calls.
  · This script is Mac-side: cache funding to disk so the analysis can be replayed without re-fetch.

Outputs (per symbol):
  {SYMBOL}_funding_1h.csv         — hourly funding rate history (long, ~5y)
  {SYMBOL}_1d_ohlcv.csv           — daily OHLCV from /info candleSnapshot

Plus consolidated:
  panel_summary.json              — per-symbol coverage (start, end, n_funding, n_ohlcv)

UNIVERSE: 50+ liquid perps (BTC/ETH/SOL + idiosyncratic alts: DYDX/INJ/SUI/OP/ARB/LDO/
GMX/STX/RNDR/...) per Seth's expected breadth set. Universe=meta pulls all 232 perps;
we then filter to liquid ones (n_funding ≥ 1000).

Endpoints (verified by Seth 2026-07-18):
  · POST https://api.hyperliquid.xyz/info {"type":"meta"}            → universe[].name
  · POST …/info {"type":"fundingHistory","coin":"BTC","startTime":<ms>} → hourly, 500/page
  · POST …/info {"type":"candleSnapshot","req":{"coin":"BTC","interval":"1d",
                                                  "startTime":<ms>,"endTime":<ms>}}

Idempotent: re-running extends coverage if .csv exists (no clobber).

USAGE (Mac-side):
  python3 scripts/fetch_hyperliquid_funding.py --universe top50 --start 2022-01-01
  python3 scripts/fetch_hyperliquid_funding.py --universe all --start 2022-01-01 --min-funding 1000
  python3 scripts/fetch_hyperliquid_funding.py --coins BTC,ETH,SOL,DYDX,INJ,SUI --start 2023-01-01
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.hyperliquid.xyz/info"
DEFAULT_OUT = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")

# Liquid-perp universe Seth curated (cross-class breadth set, ~50 names).
# This is the expected direction — replace with `--universe all --min-funding 1000` to discover.
TOP_50 = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DYDX", "INJ", "SUI", "OP", "ARB",
    "LDO", "GMX", "STX", "RNDR", "AVAX",
    "LINK", "UNI", "AAVE", "MKR", "CRV",
    "SNX", "COMP", "SUSHI", "CAKE", "FXS",
    "ENA", "ETHFI", "PENDLE", "TIA", "ALT",
    "STRK", "ZRO", "WIF", "JUP", "JTO",
    "SEI", "APT", "SUI", "ATOM", "DOT",
    "NEAR", "FIL", "ICP", "ETC", "BCH",
    "TON", "DOGE", "PEPE", "SHIB", "TRX",
]


def _post(payload: dict, retries: int = 4, sleep_s: float = 3.0,
          cooldown_on_429: float = 30.0, max_cooldown_429: float = 120.0) -> list | dict:
    """POST to HL info endpoint with exponential retry/backoff. Honours 429 with extended cooldown.

    R-LIMIT NOTE (2026-07-20): HL's anon /info endpoint rate-limits aggressively (~10 calls/minute
    per IP). Default sleep of 0.1s/page is too aggressive — got 429 on BTC funding history first
    paginated call. Bumped: base sleep 3.0s, 429 cooldown 30→60→120s with full backoff.
    """
    last = None
    for k in range(retries):
        try:
            req = urllib.request.Request(
                API,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "cc-a-s1-crowd"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                # HL anon rate limit: cool down hard before retry
                wait = min(cooldown_on_429 * (2 ** k), max_cooldown_429)
                print(f"[429] cooling down {wait:.0f}s on {payload.get('type', '?')} (attempt {k+1}/{retries})",
                      file=sys.stderr)
                time.sleep(wait)
            else:
                time.sleep(sleep_s * (k + 1))
        except Exception as e:
            last = e
            time.sleep(sleep_s * (k + 1))
    raise RuntimeError(f"POST {payload.get('type')} failed after {retries}: {last}")


def _ts_ms(date_str: str) -> int:
    return int(datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _fetch_meta() -> list[dict]:
    return _post({"type": "meta"}).get("universe", [])


def _fetch_funding_history(coin: str, start_ms: int, end_ms: int) -> list[dict]:
    """Paginate 500/page FORWARD from start_ms to end_ms.

    HL endpoint behavior (verified 2026-07-20, Minimax-A): `fundingHistory` returns the OLDEST
    500 records in [startTime, endTime] (ASC by time). To paginate forward, advance `startTime`
    past the last returned record — incrementing `endTime` instead just re-returns the same
    batch (the trap I hit at 03:00 UTC: BTC appeared to hang on first coin).

    R-LIMIT (2026-07-20): per-page sleep 0.5s, anon rate-limit handling in _post() (30/60/120s
    cooldown on HTTP 429).
    """
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        page = _post({"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_ms})
        if not page:
            break
        rows.extend(page)
        # short page = we've reached the end
        if len(page) < 500:
            break
        # advance past the last returned timestamp
        cursor = int(page[-1]["time"]) + 1
        time.sleep(0.5)
    return rows


def _fetch_candles(coin: str, start_ms: int, end_ms: int) -> list[dict]:
    """Fetch daily candles in one shot (HL candleSnapshot accepts wide ranges)."""
    return _post({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "1d", "startTime": start_ms, "endTime": end_ms,
    }})


def _write_funding(path: Path, rows: list[dict], mode: str = "w"):
    new = sorted({(int(r["time"]), float(r.get("fundingRate", 0.0))) for r in rows})
    if mode == "a" and path.exists():
        with open(path) as f:
            r = csv.reader(f); next(r); existing = {int(row[0]) for row in r}
        new = [(t, v) for t, v in new if t not in existing]
    with open(path, mode, newline="") as f:
        w = csv.writer(f)
        if mode == "w":
            w.writerow(["fundingTime", "fundingRate"])
        for t, v in new:
            w.writerow([t, v])


def _write_candles(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["openTime", "close", "quoteVolume"])
        for r in rows:
            t = r["t"]
            w.writerow([t, r["c"], r.get("v", 0.0)])


def main():
    ap = argparse.ArgumentParser(description="Fetch Hyperliquid funding + OHLCV for breadth pool.")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Output dir")
    ap.add_argument("--start", default="2022-01-01", help="Start date (ISO)")
    ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="End date (ISO)")
    ap.add_argument("--universe", default="top50", choices=["top50", "all", "coins"],
                    help="Which perp set to fetch")
    ap.add_argument("--coins", default="", help="Comma list when --universe=coins")
    ap.add_argument("--min-funding", type=int, default=1000,
                    help="For --universe=all: minimum n_funding rows to keep a perp")
    ap.add_argument("--limit", type=int, default=50,
                    help="For --universe=all: cap on perps fetched (sorted by n_funding desc)")
    ap.add_argument("--funding-only", action="store_true", help="Skip OHLCV fetch (faster)")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    start_ms = _ts_ms(args.start); end_ms = _ts_ms(args.end)

    # resolve universe
    if args.universe == "top50":
        coins = TOP_50
        print(f"[universe] using curated top-{len(coins)} liquid perps", file=sys.stderr)
    elif args.universe == "coins":
        coins = [c.strip() for c in args.coins.split(",") if c.strip()]
        print(f"[universe] explicit coins: {coins}", file=sys.stderr)
    else:
        meta = _fetch_meta()
        coins = [m["name"] for m in meta]
        print(f"[universe] meta returned {len(coins)} perps; pre-filter on min-funding={args.min_funding}", file=sys.stderr)

    summary = {"start": args.start, "end": args.end, "perps": []}
    for coin in coins:
        fund_path = out / f"{coin.lower()}_funding_1h.csv"
        ohlcv_path = out / f"{coin.lower()}_1d_ohlcv.csv"
        try:
            print(f"[{coin}] funding...", file=sys.stderr)
            fund_rows = _fetch_funding_history(coin, start_ms, end_ms)
            _write_funding(fund_path, fund_rows, mode="w")

            if args.universe == "all" and len(fund_rows) < args.min_funding:
                print(f"[{coin}] SKIP — only {len(fund_rows)} funding rows (<{args.min_funding})", file=sys.stderr)
                fund_path.unlink(missing_ok=True)
                continue

            if not args.funding_only:
                print(f"[{coin}] OHLCV...", file=sys.stderr)
                candle_rows = _fetch_candles(coin, start_ms, end_ms)
                _write_candles(ohlcv_path, candle_rows)
                n_ohlcv = len(candle_rows)
            else:
                n_ohlcv = 0

            summary["perps"].append({
                "coin": coin, "n_funding": len(fund_rows), "n_ohlcv": n_ohlcv,
                "funding_path": str(fund_path), "ohlcv_path": str(ohlcv_path) if not args.funding_only else None,
            })
            print(f"[{coin}] OK — {len(fund_rows)} funding, {n_ohlcv} OHLCV", file=sys.stderr)
            time.sleep(1.0)

        except Exception as e:
            print(f"[{coin}] FAIL — {e}", file=sys.stderr)
            summary["perps"].append({"coin": coin, "error": str(e)})

    # cap if --universe=all --limit
    if args.universe == "all" and args.limit and len(summary["perps"]) > args.limit:
        ok = sorted([p for p in summary["perps"] if "n_funding" in p],
                    key=lambda p: p["n_funding"], reverse=True)
        kept = set(p["coin"] for p in ok[:args.limit])
        for p in summary["perps"]:
            if p["coin"] not in kept and "n_funding" in p:
                Path(p["funding_path"]).unlink(missing_ok=True)
                if p.get("ohlcv_path"):
                    Path(p["ohlcv_path"]).unlink(missing_ok=True)
        summary["perps"] = [p for p in summary["perps"] if p["coin"] in kept or "error" in p]

    summary_path = out / "panel_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {summary_path} ({len([p for p in summary['perps'] if 'n_funding' in p])} perps cached)",
          file=sys.stderr)


if __name__ == "__main__":
    main()