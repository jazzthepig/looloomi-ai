#!/usr/bin/env python3
"""15m HL candle fetch — R50 substrate (Minimax-A, 2026-07-21).

§CIS-REGIME-BOOK P0 (Seth 2026-07-20) needs 15m execution/stops validation.
Seth couldn't fetch in-sandbox (timeout). Mac-side: reuse the R47 rate-limiter pattern.
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
DEFAULT_OUT = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_15m")
SYMBOLS = ["BTC", "ETH", "SOL"]


def _post(payload: dict, retries: int = 4, sleep_s: float = 3.0,
          cooldown_on_429: float = 30.0, max_cooldown_429: float = 120.0) -> list | dict:
    """R47 rate-limiter pattern."""
    last = None
    for k in range(retries):
        try:
            req = urllib.request.Request(
                API,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "cc-r50-15m"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
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


def _fetch_15m(coin: str, start_ms: int, end_ms: int) -> list[dict]:
    """Paginate 15m candles. HL candleSnapshot accepts wide ranges but chunks internally;
    paginate by 30-day windows to be safe."""
    rows = []
    chunk_ms = 30 * 86_400_000  # 30 days
    cur = start_ms
    while cur < end_ms:
        nxt = min(cur + chunk_ms, end_ms)
        page = _post({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "15m", "startTime": cur, "endTime": nxt,
        }})
        if isinstance(page, list):
            rows.extend(page)
        elif isinstance(page, dict) and page.get("candles"):
            rows.extend(page["candles"])
        cur = nxt
        time.sleep(1.0)
    return rows


def _write(path: Path, rows: list[dict]):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["openTime", "close", "quoteVolume"])
        for r in rows:
            t = r.get("t") or r.get("openTime")
            c = r.get("c") or r.get("close")
            v = r.get("v", r.get("quoteVolume", 0.0))
            w.writerow([t, c, v])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--start", default="2024-04-02", help="Aligned to V5c H1/H2 validation window start")
    ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--coins", default=",".join(SYMBOLS))
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    start_ms = _ts_ms(args.start); end_ms = _ts_ms(args.end)
    coins = [c.strip() for c in args.coins.split(",") if c.strip()]

    summary = {"start": args.start, "end": args.end, "coins": []}
    for coin in coins:
        path = out / f"{coin.lower()}_15m.csv"
        try:
            print(f"[{coin}] fetching 15m…", file=sys.stderr)
            rows = _fetch_15m(coin, start_ms, end_ms)
            _write(path, rows)
            summary["coins"].append({"coin": coin, "n_rows": len(rows),
                                      "path": str(path)})
            print(f"[{coin}] OK — {len(rows)} 15m candles", file=sys.stderr)
        except Exception as e:
            print(f"[{coin}] FAIL — {e}", file=sys.stderr)
            summary["coins"].append({"coin": coin, "error": str(e)})

    with open(out / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {out / 'summary.json'}")


if __name__ == "__main__":
    main()