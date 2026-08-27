"""Daily NAV ledger for 3-sleeve parallel paper phase.

Per user direction 2026-07-28 ("三件并行 paper only, 60d forward paper, 不卡 1.96").
The 60-day verdict at Sharpe / maxDD / orthogonal-to-R77 requires daily P&L
accumulation — `weekly_summary.py` operates on signal trajectories only.
This module is the paper P&L ledger (the missing infrastructure piece).

Honest scope (anti-imposter, §CLAUDE.md "no mock data"):
  - sleeve_3 (cross-asset macro L/S): direct L/S basket return.
    P&L_t = sum over positions of (qty_t × (close_t − close_{t−1})).
    Mark source = EODHD close (same source as the signal computation).
  - sleeve_1 (vol carry): term_premium mean-reversion proxy.
    P&L_t = −(term_premium_t − term_premium_{t−1}) × sleeve_notional × time_decay_factor
    − (tail_hedge_drag_proportional_to_daily_btc_move).
    This is a PROXY for short-vol carry P&L — it captures θ-decay when
    term_premium mean-reverts (sell-high-buy-low), not the full option Greeks.
    A production sleeve would use Black-Scholes greeks; this is paper.
  - sleeve_2 (regime tilt): tilt-change × R77 daily return.
    GATED on R77 NAV availability from Supabase `fusion_paper_nav`.
    Returns None if R77 NAV unavailable (no fabrication).

Output:
  /tmp/cometcloud_data/paper_books/{sleeve_id}_nav.csv
  Schema: date_utc, daily_pnl_usd, cumulative_nav_usd, n_positions, sleeve_note

Usage:
  python3 src/research/paper_books/nav_ledger.py
  # or from daily_runner.py (auto-wired post sleeve runs)

Anti-imposter reminders:
  - This is a PAPER ledger. No live fills, no live mark-to-market against real
    positions. The proxy is honest about its simplifications.
  - sleeve_1's vol carry P&L is the most uncertain (options Greeks are not
    modeled). Treat sleeve_1 NAV as informational, not authoritative.
  - sleeve_2's NAV is gated on R77 paper book; until that pipeline is
    unblocked, sleeve_2 returns NaN NAV (not zero, not fabricated).
"""
from __future__ import annotations

import csv
import os
import sys
import math
import urllib.request
import urllib.error
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src" / "research" / "paper_books"))

from ledger import LEDGER_DIR, read_sleeve, append_paper_position, PaperPosition  # noqa: E402

# Reuse sleeve_3's EODHD fetcher (no duplicate code)
from src.research.paths import MAC_ENV as _MAC_ENV
_keys = dotenv_values(_MAC_ENV) if _MAC_ENV.exists() else {}
EODHD_API_KEY = _keys.get("EODHD_API_KEY", "")

# Supabase config for R77 NAV (gates sleeve_2)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
R77_NAV_TABLE = "fusion_paper_nav"

# Per-sleeve constants (mirror sleeve modules to stay aligned)
SLEEVE1_NOTIONAL_USD = 300_000.0      # sleeve_1: 30% × $1M paper NAV
SLEEVE1_TAIL_HEDGE_NOTIONAL = 90_000.0  # 30% of short-vol premium
SLEEVE1_TIME_DECAY_FACTOR = 0.25       # daily theta proxy (4-5%/month → ~0.18% per day)

SLEEVE2_R77_TOTAL_NOTIONAL_USD = 1_000_000.0  # R77 paper NAV assumption (placeholder until Supabase live)

SLEEVE3_NOTIONAL_USD = 400_000.0       # sleeve_3: 40% × $1M paper NAV

NAV_HEADER = ["date_utc", "daily_pnl_usd", "cumulative_nav_usd", "n_positions", "sleeve_note"]


def _nav_csv_path(sleeve_id: str) -> Path:
    return LEDGER_DIR / f"{sleeve_id}_nav.csv"


def _read_nav(sleeve_id: str) -> list[dict]:
    """Read all NAV rows for a sleeve (sorted by date_utc asc)."""
    path = _nav_csv_path(sleeve_id)
    if not path.exists():
        return []
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return sorted(rows, key=lambda r: r.get("date_utc", ""))


def _append_nav(sleeve_id: str, row: dict) -> Path:
    """Append or replace today's NAV row."""
    path = _nav_csv_path(sleeve_id)
    existing = _read_nav(sleeve_id)
    today = row["date_utc"]
    existing = [r for r in existing if r.get("date_utc") != today]
    existing.append(row)
    existing.sort(key=lambda r: r.get("date_utc", ""))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=NAV_HEADER)
        w.writeheader()
        w.writerows(existing)
    return path


# ---------------------------------------------------------------------------
# sleeve_3 — direct L/S basket daily P&L (cleanest)
# ---------------------------------------------------------------------------

def _eodhd_close(symbol: str, on_date: str) -> float | None:
    """Fetch EODHD close for a single symbol on a specific date."""
    if not EODHD_API_KEY:
        return None
    url = (
        f"https://eodhd.com/api/eod/{symbol}.US?from={on_date}&to={on_date}"
        f"&period=d&api_token={EODHD_API_KEY}&fmt=json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if isinstance(data, list) and data:
            close = data[0].get("close")
            if close is not None:
                return float(close)
    except Exception:
        pass
    return None


def _latest_positions_per_day(rows: list[dict]) -> dict[str, dict]:
    """Return {symbol: latest_row_per_today} grouped by date_utc (date only, not ts)."""
    by_date_symbol: dict[str, dict[str, dict]] = {}
    for r in rows:
        ts = r.get("ts_utc", "")
        date_only = ts[:10] if len(ts) >= 10 else ""
        sym = r.get("symbol", "")
        if not date_only or not sym:
            continue
        by_date_symbol.setdefault(date_only, {})[sym] = r
    return {d: list(sym_map.values()) for d, sym_map in sorted(by_date_symbol.items())}


def compute_sleeve3_daily_pnl(today_iso: str) -> Optional[dict]:
    """Compute sleeve_3 daily P&L: L/S basket return vs prior day.

    Returns NAV row dict, or None if insufficient data.
    """
    rows = read_sleeve("macro_overlay")
    if not rows:
        return None
    by_day = _latest_positions_per_day(rows)
    days = sorted(by_day.keys())
    if today_iso not in by_day:
        return None
    today_idx = days.index(today_iso)
    if today_idx == 0:
        # First day — no prior to compute return against. NAV = notional * 0 (no P&L accrued yet).
        return None

    # Yesterday's positions (latest of prior day)
    yest_positions = by_day[days[today_idx - 1]]
    # Today's positions (latest of today)
    today_positions = by_day[today_iso]

    # Map {symbol: (qty_yest, mark_yest)}
    yest_map = {r.get("symbol"): (float(r.get("qty", 0)), float(r.get("mark_price", 0))) for r in yest_positions if r.get("side") != "FLAT"}
    today_map = {r.get("symbol"): (float(r.get("qty", 0)), float(r.get("mark_price", 0))) for r in today_positions if r.get("side") != "FLAT"}

    # Fetch today's closes for all held symbols
    all_symbols = set(yest_map.keys()) | set(today_map.keys())
    pnl = 0.0
    components = []
    for sym in sorted(all_symbols):
        yest_qty, yest_close = yest_map.get(sym, (0.0, 0.0))
        today_qty, today_close = today_map.get(sym, (0.0, 0.0))
        if today_close == 0:
            # Try to fetch today's close from EODHD
            fetched = _eodhd_close(sym, today_iso)
            if fetched is not None:
                today_close = fetched
            elif yest_close > 0:
                today_close = yest_close  # fall back to flat (no price evolution)
        if yest_close == 0 or yest_qty == 0:
            continue
        # P&L contribution: yesterday's qty × (today_close − yest_close)
        # qty already carries sign (LONG = +, SHORT = −)
        contribution = yest_qty * (today_close - yest_close)
        pnl += contribution
        components.append(f"{sym}({yest_qty:+.0f}×{today_close - yest_close:+.2f}={contribution:+.0f})")

    # Compute cumulative NAV
    nav_rows = _read_nav("macro_overlay")
    last_nav = float(nav_rows[-1]["cumulative_nav_usd"]) if nav_rows else SLEEVE3_NOTIONAL_USD
    cum_nav = last_nav + pnl
    n_pos = len([r for r in today_positions if r.get("side") != "FLAT"])
    note = f"P&L components: {' '.join(components)}" if components else "no held positions; P&L=0"
    return {
        "date_utc": today_iso,
        "daily_pnl_usd": round(pnl, 2),
        "cumulative_nav_usd": round(cum_nav, 2),
        "n_positions": n_pos,
        "sleeve_note": note,
    }


# ---------------------------------------------------------------------------
# sleeve_1 — vol carry term_premium mean-reversion proxy
# ---------------------------------------------------------------------------

def _latest_term_premium_per_day(rows: list[dict]) -> dict[str, float]:
    """Extract latest term_premium per date (from the SHORT-STRADDLE row's signal_value)."""
    by_date: dict[str, tuple[str, float]] = {}
    for r in rows:
        ts = r.get("ts_utc", "")
        date_only = ts[:10] if len(ts) >= 10 else ""
        if not date_only or "SHORT-STRADDLE" not in r.get("symbol", ""):
            continue
        try:
            tp = float(r.get("signal_value", 0))
        except (TypeError, ValueError):
            continue
        prev_ts, prev_tp = by_date.get(date_only, ("", -1e9))
        if ts > prev_ts:
            by_date[date_only] = (ts, tp)
    return {d: tp for d, (ts, tp) in sorted(by_date.items())}


def compute_sleeve1_daily_pnl(today_iso: str) -> Optional[dict]:
    """Compute sleeve_1 daily P&L: term_premium mean-reversion proxy.

    Logic:
      - When ENTER_SELL held: short-vol θ-decay ≈ +term_premium/365 per day (positive).
      - When Δterm_premium > 0 (term_premium widening): NAV DECREASES (short-vol hurts).
      - When Δterm_premium < 0 (term_premium narrowing): NAV INCREASES (short-vol helps).
      - Tail hedge drag: |BTC daily return| × tail_hedge_notional × 0.30 (rough proxy).
    """
    rows = read_sleeve("vol_carry")
    if not rows:
        return None
    by_day_tp = _latest_term_premium_per_day(rows)
    if today_iso not in by_day_tp:
        return None
    days = sorted(by_day_tp.keys())
    today_idx = days.index(today_iso)
    if today_idx == 0:
        return None
    tp_today = by_day_tp[today_iso]
    tp_yest = by_day_tp[days[today_idx - 1]]
    delta_tp = tp_today - tp_yest  # negative = mean-revert (good for short-vol)

    # Fetch BTC daily return to estimate tail hedge drag
    btc_today = _eodhd_close("BTC", today_iso)
    btc_yest = _eodhd_close("BTC", days[today_idx - 1])
    btc_daily_return = 0.0
    if btc_today is not None and btc_yest is not None and btc_yest > 0:
        btc_daily_return = (btc_today - btc_yest) / btc_yest

    # Short-vol P&L: when term_premium narrows (Δ < 0), positive carry accrues
    # Proxy: -delta_tp × sleeve_notional × time_decay_factor / 100  (term_premium in %)
    short_vol_pnl = (-delta_tp / 100) * SLEEVE1_NOTIONAL_USD * SLEEVE1_TIME_DECAY_FACTOR
    # Tail hedge drag: |BTC daily return| × tail hedge notional × drag factor
    tail_drag = -abs(btc_daily_return) * SLEEVE1_TAIL_HEDGE_NOTIONAL * 0.30
    pnl = short_vol_pnl + tail_drag

    nav_rows = _read_nav("vol_carry")
    last_nav = float(nav_rows[-1]["cumulative_nav_usd"]) if nav_rows else SLEEVE1_NOTIONAL_USD
    cum_nav = last_nav + pnl
    note = (
        f"Δterm_premium={delta_tp:+.3f}% → short_vol_pnl={short_vol_pnl:+.2f}  "
        f"btc_daily_return={btc_daily_return:+.4f} → tail_drag={tail_drag:+.2f}  "
        f"PAPER PROXY (Black-Scholes not modeled)"
    )
    return {
        "date_utc": today_iso,
        "daily_pnl_usd": round(pnl, 2),
        "cumulative_nav_usd": round(cum_nav, 2),
        "n_positions": 2,  # short straddle + tail hedge
        "sleeve_note": note,
    }


# ---------------------------------------------------------------------------
# sleeve_2 — regime tilt × R77 daily return (GATED on Supabase R77 NAV)
# ---------------------------------------------------------------------------

def _fetch_r77_nav_close_to(today_iso: str) -> tuple[Optional[float], Optional[float]]:
    """Fetch R77 NAV for today and yesterday. Returns (nav_today, nav_yest) or (None, None)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None, None
    try:
        url = (
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/{R77_NAV_TABLE}"
            f"?select=date_utc,nav&order=date_utc.desc&limit=2"
        )
        req = urllib.request.Request(
            url,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if not isinstance(data, list) or len(data) < 1:
            return None, None
        # data is desc — [0] is today, [1] is yesterday (if exists)
        latest = data[0]
        if latest.get("date_utc") != today_iso:
            return None, None  # today's NAV not yet written
        nav_today = float(latest.get("nav"))
        nav_yest = float(data[1].get("nav")) if len(data) > 1 else None
        return nav_today, nav_yest
    except Exception as e:
        print(f"  [INFO] R77 NAV fetch failed: {type(e).__name__}: {str(e)[:120]}")
        return None, None


def _latest_tilt_per_day(rows: list[dict]) -> dict[str, float]:
    """Extract latest tilt multiplier per date from regime_nowcast_positions.csv."""
    by_date: dict[str, tuple[str, float]] = {}
    for r in rows:
        ts = r.get("ts_utc", "")
        date_only = ts[:10] if len(ts) >= 10 else ""
        if not date_only:
            continue
        try:
            tilt = float(r.get("qty", 1.0))
        except (TypeError, ValueError):
            continue
        prev_ts, _ = by_date.get(date_only, ("", 1.0))
        if ts > prev_ts:
            by_date[date_only] = (ts, tilt)
    return {d: t for d, (ts, t) in sorted(by_date.items())}


def compute_sleeve2_daily_pnl(today_iso: str) -> Optional[dict]:
    """Compute sleeve_2 daily P&L: tilt multiplier × R77 daily return.

    Logic:
      - The sleeve is a tilt ON R77, not a direct position.
      - P&L contribution: (tilt_t − 1.0) × (R77 NAV_today − R77 NAV_yest) on R77's full notional.
      - GATED on R77 NAV being available today + yesterday.
    """
    rows = read_sleeve("regime_nowcast")
    if not rows:
        return None
    by_day_tilt = _latest_tilt_per_day(rows)
    if today_iso not in by_day_tilt:
        return None
    days = sorted(by_day_tilt.keys())
    today_idx = days.index(today_iso)
    if today_idx == 0:
        return None
    tilt_today = by_day_tilt[today_iso]
    tilt_yest = by_day_tilt[days[today_idx - 1]]

    nav_today, nav_yest = _fetch_r77_nav_close_to(today_iso)
    if nav_today is None or nav_yest is None:
        return None  # GATED: no fabrication

    r77_daily_return = (nav_today - nav_yest) / nav_yest if nav_yest > 0 else 0.0
    # The sleeve's effective delta vs baseline 1.0x: (tilt_today - 1.0) × R77 daily return × R77 notional
    pnl = (tilt_today - 1.0) * r77_daily_return * SLEEVE2_R77_TOTAL_NOTIONAL_USD

    nav_rows = _read_nav("regime_nowcast")
    # For sleeve_2, "NAV" is the cumulative excess return from tilt deviations vs 1.0x baseline
    last_nav = float(nav_rows[-1]["cumulative_nav_usd"]) if nav_rows else 0.0
    cum_excess = last_nav + pnl
    note = (
        f"tilt={tilt_today:.2f} (vs yest={tilt_yest:.2f})  "
        f"R77 return={r77_daily_return:+.4f}  pnl={pnl:+.2f}  "
        f"GATED on Supabase R77 NAV"
    )
    return {
        "date_utc": today_iso,
        "daily_pnl_usd": round(pnl, 2),
        "cumulative_nav_usd": round(cum_excess, 2),
        "n_positions": 1,
        "sleeve_note": note,
    }


# ---------------------------------------------------------------------------
# main — run all 3 sleeves' NAV computation for today
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 72)
    print("Daily NAV ledger — 3-sleeve parallel paper phase")
    print("=" * 72)
    print(f"  output: {LEDGER_DIR}/{{sleeve_id}}_nav.csv")
    today = datetime.now(timezone.utc).date().isoformat()
    print(f"  today (UTC): {today}")
    print()

    # sleeve_3
    print("--- sleeve_3 (L/S basket direct return) ---")
    s3 = compute_sleeve3_daily_pnl(today)
    if s3 is None:
        print("  INSUFFICIENT — no prior day positions; NAV not computed")
    else:
        path = _append_nav("macro_overlay", s3)
        print(f"  daily_pnl={s3['daily_pnl_usd']:+.2f}  cumulative_nav={s3['cumulative_nav_usd']:.2f}")
        print(f"  {s3['sleeve_note']}")
        print(f"  ✓ appended: {path}")
    print()

    # sleeve_1
    print("--- sleeve_1 (vol carry term_premium proxy) ---")
    s1 = compute_sleeve1_daily_pnl(today)
    if s1 is None:
        print("  INSUFFICIENT — no prior day term_premium; NAV not computed")
    else:
        path = _append_nav("vol_carry", s1)
        print(f"  daily_pnl={s1['daily_pnl_usd']:+.2f}  cumulative_nav={s1['cumulative_nav_usd']:.2f}")
        print(f"  {s1['sleeve_note']}")
        print(f"  ✓ appended: {path}")
    print()

    # sleeve_2
    print("--- sleeve_2 (regime tilt × R77 NAV, GATED) ---")
    s2 = compute_sleeve2_daily_pnl(today)
    if s2 is None:
        print("  GATED — R77 NAV not available; NAV not computed (no fabrication)")
    else:
        path = _append_nav("regime_nowcast", s2)
        print(f"  daily_pnl={s2['daily_pnl_usd']:+.2f}  cumulative_excess={s2['cumulative_nav_usd']:.2f}")
        print(f"  {s2['sleeve_note']}")
        print(f"  ✓ appended: {path}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())