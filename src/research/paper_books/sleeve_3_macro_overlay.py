"""Sleeve 3 — cross-asset macro overlay (paper book prototype).

Per user direction 2026-07-28 ("三件并行 paper only, 60d forward paper, 不卡 1.96").
This is a PRODUCTION CANDIDATE in the parallel-paper phase, NOT a backtest sweep.
No 3-check gauntlet, no R-numbered ledger — just a working paper position log.

Universe (7 macro assets via EODHD):
  SPY (US equity), TLT (long Treasuries), GLD (gold), USO (oil),
  SLV (silver), UUP (USD index), DXY (USD index alt)

Signal: cross-sectional momentum z-score (30d return, 90d return) — top half LONG,
bottom half SHORT. Market-neutral cross-asset book, fully USD-denominated, ortho­
gonal to R77 (which is intra-crypto L/S). Sized 30-50% of total paper NAV (R77 owns
the other half).

Failsafe: if EODHD returns empty or stale (>5d), log FLAT and skip the day; never
fabricate a position. Per CLAUDE.md "no mock data in production paths".

Output: /tmp/cometcloud_data/paper_books/macro_overlay_positions.csv (one row per
rebalance decision; daily cadence for the prototype, weekly once forward-papered).

Usage:
  python3 src/research/paper_books/sleeve_3_macro_overlay.py
  ONLY=SPY,GLD python3 src/research/paper_books/sleeve_3_macro_overlay.py
"""
from __future__ import annotations

import os
import sys
import csv
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

# Load EODHD key from Mac-side env (same pattern as fetch_ohlcv_to_local.py)
from dotenv import dotenv_values
_MAC_ENV = Path("/Volumes/CometCloudAI/cometcloud-local/.env")
_keys = dotenv_values(_MAC_ENV) if _MAC_ENV.exists() else {}
EODHD_API_KEY = _keys.get("EODHD_API_KEY", "")

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))
from src.research.paper_books.ledger import (  # noqa: E402
    PaperPosition, append_paper_position, read_sleeve, LEDGER_DIR,
)

# 7-asset macro universe. Use EODHD ticker format (.US suffix for US-listed).
MACRO_UNIVERSE = [
    ("SPY", "US equity (broad)"),
    ("TLT", "long Treasuries (20y+)"),
    ("GLD", "gold"),
    ("USO", "oil"),
    ("SLV", "silver"),
    ("UUP", "USD index (Invesco)"),
    ("DBA", "agriculture"),
]
# 7 assets is intentional; keeps the cross-section diversified without liquidity issues.

REBAL_DAYS = 7           # weekly rebalance; not daily (saves turnover, structural alpha)
LOOKBACK_30 = 30         # 30d return
LOOKBACK_90 = 90         # 90d return
SLEEVES_NOTIONAL_PCT = 0.40   # this sleeve = 40% of total paper NAV
PAPER_NAV_USD = 1_000_000     # paper book reference nav (sleeve notional = $400k)


def _eodhd_fetch_one(symbol: str, lookback_days: int) -> list[dict]:
    """Fetch daily OHLC for one symbol from EODHD /eod endpoint."""
    if not EODHD_API_KEY:
        return []
    end = datetime.now(timezone.utc).date()
    # EODHD free tier caps daily EOD at ~100 rows; over-fetch by 1.5x to be safe.
    start = end - timedelta(days=int(lookback_days * 1.8))
    url = (
        f"https://eodhd.com/api/eod/{symbol}.US?from={start.isoformat()}"
        f"&to={end.isoformat()}&period=d&api_token={EODHD_API_KEY}&fmt=json"
    )
    last_err = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
                if isinstance(data, list):
                    return data
                return []
        except urllib.error.HTTPError as e:
            last_err = f"http_{e.code}"
            if e.code in (429, 503):
                time.sleep(2 ** attempt)
            elif 400 <= e.code < 500:
                return []
            else:
                time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)[:120]
            time.sleep(2 ** attempt)
    print(f"  [WARN] {symbol} EODHD exhausted: {last_err}")
    return []


def _mom_pct(rows: list[dict], lookback: int) -> float | None:
    """Return lookback-day return from EODHD rows. None if insufficient data."""
    if not rows or len(rows) < lookback:
        return None
    rows_sorted = sorted(rows, key=lambda r: r.get("date", ""))
    closes = [float(r["close"]) for r in rows_sorted if r.get("close") is not None]
    if len(closes) < lookback:
        return None
    last = closes[-1]
    past = closes[-lookback]
    if past == 0:
        return None
    return (last - past) / past


def main() -> int:
    print("=" * 72)
    print("Sleeve 3 — cross-asset macro overlay (paper book prototype)")
    print("=" * 72)
    print(f"  universe:  {len(MACRO_UNIVERSE)} assets")
    print(f"  rebal:     {REBAL_DAYS}d")
    print(f"  paper NAV: ${PAPER_NAV_USD:,.0f}  sleeve notional ${PAPER_NAV_USD * SLEEVES_NOTIONAL_PCT:,.0f}")
    print(f"  EODHD key: {'present' if EODHD_API_KEY else 'MISSING — aborting'}")
    if not EODHD_API_KEY:
        return 1
    print()

    raw = {}
    for sym, _desc in MACRO_UNIVERSE:
        rows = _eodhd_fetch_one(sym, max(LOOKBACK_30, LOOKBACK_90))
        if not rows:
            print(f"  [WARN] {sym}: no EODHD data — skipping")
            continue
        m30 = _mom_pct(rows, LOOKBACK_30)
        m90 = _mom_pct(rows, LOOKBACK_90)
        rows_sorted = sorted(rows, key=lambda r: r.get("date", ""))
        last_row = rows_sorted[-1]
        last_close_raw = last_row.get("close")
        last_close = float(last_close_raw) if last_close_raw is not None else None
        raw[sym] = {"m30": m30, "m90": m90, "close": last_close,
                     "n_rows": len(rows), "last_date": last_row.get("date")}
        last_str = f"{last_close:.4f}" if last_close is not None else "n/a"
        m30_str = f"{m30:+.2%}" if m30 is not None else "n/a"
        m90_str = f"{m90:+.2%}" if m90 is not None else "n/a"
        print(f"  {sym:5s}  m30={m30_str}  m90={m90_str}  last={last_str}  n={len(rows)}  date={raw[sym]['last_date']}")
    print()

    # Cross-sectional momentum z (combined 30d + 90d average) → rank → long top-half, short bottom-half.
    valid = {k: v for k, v in raw.items() if v["m30"] is not None and v["m90"] is not None}
    if len(valid) < 4:
        print(f"  INSUFFICIENT universe ({len(valid)}/{len(MACRO_UNIVERSE)} with data) → log FLAT")
        for sym, _desc in MACRO_UNIVERSE:
            append_paper_position(PaperPosition(
                sleeve_id="macro_overlay",
                symbol=sym, side="FLAT", qty=0.0, mark_price=0.0,
                signal_value=0.0, signal_name="insufficient_universe",
                notional_usd=0.0,
                sleeve_note=f"only {len(valid)}/{len(MACRO_UNIVERSE)} symbols had data; sleeve is FLAT",
            ))
        return 0

    # Combined momentum z = (m30 + m90) / 2
    combined = {k: (v["m30"] + v["m90"]) / 2 for k, v in valid.items()}
    mu = sum(combined.values()) / len(combined)
    var = sum((x - mu) ** 2 for x in combined.values()) / max(len(combined) - 1, 1)
    sd = var ** 0.5
    print(f"  cross-section momentum:  mean={mu:+.2%}  std={sd:+.2%}  n={len(combined)}")
    if sd == 0:
        print("  ZERO std — flat universe; log FLAT")
        for sym, _desc in MACRO_UNIVERSE:
            append_paper_position(PaperPosition(
                sleeve_id="macro_overlay", symbol=sym, side="FLAT", qty=0.0,
                mark_price=valid.get(sym, {}).get("close", 0.0),
                signal_value=0.0, signal_name="zero_std_universe",
                notional_usd=0.0,
                sleeve_note="zero std — all assets have identical momentum",
            ))
        return 0

    ranked = sorted(combined.keys(), key=lambda k: combined[k])
    n = len(ranked)
    half = n // 2
    longs = ranked[half:]      # top half
    shorts = ranked[:half]    # bottom half
    # Equal weight inside each sleeve
    sleeve_notional = PAPER_NAV_USD * SLEEVES_NOTIONAL_PCT
    long_w = 0.5 / max(len(longs), 1)
    short_w = 0.5 / max(len(shorts), 1)

    print()
    print(f"  LONGS  (top half, total = 0.50 sleeve notional):")
    for sym in longs:
        px = valid[sym]["close"]
        mom = combined[sym]
        qty = sleeve_notional * long_w / px
        print(f"    {sym:5s}  mom={mom:+.2%}  px={px:.4f}  qty={qty:,.2f}  notional=${sleeve_notional*long_w:,.0f}")
        append_paper_position(PaperPosition(
            sleeve_id="macro_overlay", symbol=sym, side="LONG",
            qty=round(qty, 4), mark_price=px,
            signal_value=round(mom, 6), signal_name="cross_section_momentum_z",
            notional_usd=round(sleeve_notional * long_w, 2),
            sleeve_note=f"z={round((mom - mu) / sd, 3)}  half=LONG",
        ))
    print(f"  SHORTS (bottom half, total = 0.50 sleeve notional):")
    for sym in shorts:
        px = valid[sym]["close"]
        mom = combined[sym]
        qty = sleeve_notional * short_w / px
        print(f"    {sym:5s}  mom={mom:+.2%}  px={px:.4f}  qty=-{qty:,.2f}  notional=${sleeve_notional*short_w:,.0f}")
        append_paper_position(PaperPosition(
            sleeve_id="macro_overlay", symbol=sym, side="SHORT",
            qty=round(-qty, 4), mark_price=px,
            signal_value=round(mom, 6), signal_name="cross_section_momentum_z",
            notional_usd=round(sleeve_notional * short_w, 2),
            sleeve_note=f"z={round((mom - mu) / sd, 3)}  half=SHORT",
        ))

    print()
    print(f"  logged positions: see {LEDGER_DIR}/macro_overlay_positions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
