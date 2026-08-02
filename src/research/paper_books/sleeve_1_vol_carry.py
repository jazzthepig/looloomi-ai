"""Sleeve 1 — vol carry (sell IV > RV, collect term premium).

Per user direction 2026-07-28 ("三件并行 paper only, 60d forward paper, 不卡 1.96").
Production candidate in the parallel-paper phase, NOT a backtest sweep.

Signal: term_premium = IV_30d - RV_30d (both annualized %).
  - IV: Deribit DVOL 30d (BTC) — public DVOL index.
  - RV: BTC 30d close-to-close realized vol (annualized, sqrt(365)).

Action when term_premium > 5% (positive carry):
  - SELL ATM straddle (delta-hedged daily in real life; prototype logs notional only)
  - BUY tail hedge: long OTM 1.5x ATM put (paid by premium)
  - Sized as % of paper NAV based on |term_premium| scaled by realized vol.

Output: /tmp/cometcloud_data/paper_books/vol_carry_positions.csv (one row per day).

Failsafe: if DVOL fetch fails OR realized vol cannot be computed, log FLAT and skip.
Never fabricate a position. Per CLAUDE.md "no mock data in production paths".

Usage:
  python3 src/research/paper_books/sleeve_1_vol_carry.py
  DRY_RUN=1 python3 src/research/paper_books/sleeve_1_vol_carry.py
"""
from __future__ import annotations

import os
import sys
import json
import csv
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from src.research.paper_books.ledger import (  # noqa: E402
    PaperPosition, append_paper_position, read_sleeve, LEDGER_DIR,
)

# Data sources (both public, no API key needed)
DVOL_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
DVOL_CURRENCY = "BTC"
DVOL_RESOLUTION = "1D"
DVOL_LOOKBACK = 60      # 60d history sufficient to extract latest 30d

# Binance public klines for RV computation
BINANCE_BASE = "https://api.binance.com/api/v3/klines"
RV_LOOKBACK = 45         # 45 daily bars for 30d realized vol + buffer

# Signal thresholds
TERM_PREMIUM_ENTRY = 5.0   # annualized %; >= 5% → sell vol
TERM_PREMIUM_EXIT  = 0.0   # < 0% → close (term premium gone)
SLEEVE_NOTIONAL_PCT = 0.30 # 30% of total paper NAV
PAPER_NAV_USD = 1_000_000
TAIL_HEDGE_RATIO = 0.30    # 30% of short-vol premium goes to tail hedge


def _http_get_json(url: str, timeout: int = 20) -> list | dict | None:
    last_err = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last_err = f"http_{e.code}"
            if e.code in (429, 503):
                time.sleep(2 ** attempt)
            elif 400 <= e.code < 500:
                return None
            else:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(2 ** attempt)
    print(f"  [WARN] HTTP exhausted: {last_err}")
    return None


def fetch_dvol_30d() -> float | None:
    """Latest DVOL 30d value (annualized %)."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - DVOL_LOOKBACK * 86_400_000
    url = (
        f"{DVOL_URL}?currency={DVOL_CURRENCY}&resolution={DVOL_RESOLUTION}"
        f"&start_timestamp={start_ms}&end_timestamp={end_ms}"
    )
    data = _http_get_json(url)
    if not data or "result" not in data or "data" not in data["result"]:
        return None
    rows = data["result"]["data"]
    if not rows:
        return None
    # DVOL value is the 5th column (index 4) — it's the annualized % in DVOL
    last = rows[-1]
    try:
        return float(last[4])
    except (IndexError, TypeError, ValueError):
        return None


def fetch_btc_closes(lookback: int = RV_LOOKBACK) -> list[float]:
    """Fetch daily close from Binance BTCUSDT (public, no key)."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - (lookback + 5) * 86_400_000
    url = (
        f"{BINANCE_BASE}?symbol=BTCUSDT&interval=1d"
        f"&startTime={start_ms}&endTime={end_ms}&limit={lookback + 5}"
    )
    data = _http_get_json(url)
    if not isinstance(data, list):
        return []
    closes = [float(r[4]) for r in data if len(r) >= 5 and r[4] is not None]
    return closes


def realized_vol_30d(closes: list[float]) -> float | None:
    """30d close-to-close realized vol, annualized %."""
    if len(closes) < 31:
        return None
    # Use last 31 daily closes to get 30 log returns
    daily_log_ret = []
    for i in range(len(closes) - 30, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev > 0 and cur > 0:
            daily_log_ret.append((cur / prev) - 1.0)
    if len(daily_log_ret) < 30:
        return None
    import statistics
    sd = statistics.stdev(daily_log_ret)
    return sd * (365 ** 0.5) * 100  # annualized %


def main() -> int:
    print("=" * 72)
    print("Sleeve 1 — vol carry (sell IV > RV, collect term premium)")
    print("=" * 72)
    print(f"  paper NAV:        ${PAPER_NAV_USD:,.0f}  sleeve notional ${PAPER_NAV_USD * SLEEVE_NOTIONAL_PCT:,.0f}")
    print(f"  entry threshold:  term_premium >= {TERM_PREMIUM_ENTRY:.1f}%")
    print(f"  exit threshold:   term_premium < {TERM_PREMIUM_EXIT:.1f}%")
    print(f"  tail hedge:       {TAIL_HEDGE_RATIO:.0%} of short-vol notional → long OTM 1.5x put")
    print()

    iv = fetch_dvol_30d()
    print(f"  IV (Deribit DVOL 30d): {f'{iv:.2f}%' if iv is not None else 'n/a'}")
    closes = fetch_btc_closes()
    rv = realized_vol_30d(closes)
    print(f"  RV (BTC 30d close-close): {f'{rv:.2f}%' if rv is not None else 'n/a'}  n_closes={len(closes)}")

    if iv is None or rv is None:
        print(f"  INSUFFICIENT data — log FLAT (per CLAUDE.md 'no mock data')")
        for leg, side, qty in [
            ("BTC-SHORT-STRADDLE", "FLAT", 0.0),
            ("BTC-LONG-OTM-PUT-1.5x", "FLAT", 0.0),
        ]:
            append_paper_position(PaperPosition(
                sleeve_id="vol_carry", symbol=leg, side=side, qty=qty, mark_price=0.0,
                signal_value=0.0, signal_name="term_premium_pct",
                notional_usd=0.0,
                sleeve_note=f"IV={iv} RV={rv} — insufficient data → FLAT",
            ))
        return 0

    term_premium = iv - rv
    print(f"  term_premium (IV - RV): {term_premium:+.2f}%")

    if term_premium >= TERM_PREMIUM_ENTRY:
        side_action = "ENTER_SELL"
    elif term_premium < TERM_PREMIUM_EXIT:
        side_action = "EXIT_FLAT"
    else:
        side_action = "HOLD"

    sleeve_notional = PAPER_NAV_USD * SLEEVE_NOTIONAL_PCT
    short_straddle_notional = sleeve_notional if side_action == "ENTER_SELL" else 0.0
    tail_hedge_notional = short_straddle_notional * TAIL_HEDGE_RATIO

    # Mark price: spot reference for log
    spot = closes[-1] if closes else 0.0

    print()
    print(f"  ACTION: {side_action}")
    if side_action == "ENTER_SELL":
        print(f"    short ATM straddle: ${short_straddle_notional:,.0f} notional (delta-hedged daily)")
        print(f"    long OTM 1.5x put:  ${tail_hedge_notional:,.0f} notional (tail hedge)")
        print(f"    net short-vol risk: ${short_straddle_notional - tail_hedge_notional:,.0f}")
    elif side_action == "EXIT_FLAT":
        print(f"    closing all vol positions; sleeve returns to cash")
    else:
        print(f"    holding current position; term_premium in [{TERM_PREMIUM_EXIT:.0f}%, {TERM_PREMIUM_ENTRY:.0f}%]")

    # Log 2 legs (or 1 FLAT row if HOLD)
    if side_action == "ENTER_SELL":
        legs = [
            ("BTC-SHORT-STRADDLE", "SHORT", -short_straddle_notional),
            ("BTC-LONG-OTM-PUT-1.5x", "LONG", tail_hedge_notional),
        ]
    elif side_action == "EXIT_FLAT":
        legs = [
            ("BTC-SHORT-STRADDLE", "FLAT", 0.0),
            ("BTC-LONG-OTM-PUT-1.5x", "FLAT", 0.0),
        ]
    else:
        # HOLD: log the prior signal value but no new entry
        legs = [
            ("BTC-SHORT-STRADDLE", "HOLD", 0.0),
            ("BTC-LONG-OTM-PUT-1.5x", "HOLD", 0.0),
        ]

    for sym, side, qty in legs:
        append_paper_position(PaperPosition(
            sleeve_id="vol_carry", symbol=sym, side=side, qty=qty, mark_price=spot,
            signal_value=round(term_premium, 3), signal_name="term_premium_pct",
            notional_usd=round(abs(qty), 2),
            sleeve_note=f"IV={iv:.2f} RV={rv:.2f} action={side_action} spot={spot:.2f}",
        ))

    print()
    print(f"  logged positions: see {LEDGER_DIR}/vol_carry_positions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
