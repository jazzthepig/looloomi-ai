"""Daily paper-book runner — orchestrates 3 sleeve prototypes + ⓠ regime track.

Per user direction 2026-07-28 ("三件并行 paper only, 60d forward paper").
Runs all 3 sleeve modules in sequence, then writes a daily summary row to
/tmp/cometcloud_data/paper_books/daily_summary.csv with sleeve-level signal
values + tilt multipliers for that day.

Per Jazz direction 2026-08-06 ("接吧"): after the NAV ledger runs, also compute
today's ⓠ regime override paper track (parallel paper NAV under the enforcer).
This is the daily entry point for the 60-day forward paper test of the enforcer
(per STRATEGY_PLAYBOOK.md §P3 promotion gate).

Output: /tmp/cometcloud_data/paper_books/daily_summary.csv
Schema: date, vol_carry_iv, vol_carry_rv, vol_carry_term_premium,
        vol_carry_action, regime_nowcast_btc_30d, regime_nowcast_tvl_7d,
        regime_nowcast_usdt_7d, regime_nowcast_p, regime_nowcast_tilt,
        macro_overlay_long_count, macro_overlay_short_count

Usage:
  python3 src/research/paper_books/daily_runner.py    # run all 3 sleeves + regime track + write daily summary
  python3 src/research/paper_books/daily_runner.py --read-last   # show last daily summary
"""
from __future__ import annotations

import os
import sys
import csv
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src" / "research" / "paper_books"))

from ledger import LEDGER_DIR  # noqa: E402

SLEEVES = ["sleeve_1_vol_carry", "sleeve_2_regime_nowcast", "sleeve_3_macro_overlay"]
DAILY_SUMMARY_PATH = LEDGER_DIR / "daily_summary.csv"
NAV_LEDGER_MODULE = "nav_ledger"
DAILY_SUMMARY_HEADER = [
    "date_utc",
    "vol_carry_iv", "vol_carry_rv", "vol_carry_term_premium", "vol_carry_action",
    "regime_nowcast_btc_30d", "regime_nowcast_tvl_7d", "regime_nowcast_usdt_7d",
    "regime_nowcast_p", "regime_nowcast_tilt",
    "macro_overlay_long_count", "macro_overlay_short_count",
]


def _run_sleeve(module_name: str) -> int:
    """Run a single sleeve module and return its exit code."""
    path = _REPO_ROOT / "src" / "research" / "paper_books" / f"{module_name}.py"
    res = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=180)
    print(res.stdout)
    if res.returncode != 0:
        print(f"  [ERROR] {module_name} exit={res.returncode}")
        print(res.stderr)
    return res.returncode


def _read_last_row(sleeve_id: str) -> dict:
    """Read the last row from a sleeve's positions CSV."""
    safe = sleeve_id.replace("/", "_").replace(" ", "_")
    path = LEDGER_DIR / f"{safe}_positions.csv"
    if not path.exists():
        return {}
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return rows[-1] if rows else {}


def main() -> int:
    print("=" * 72)
    print("Daily paper-book runner — 3 sleeves parallel paper phase")
    print("=" * 72)
    print(f"  today: {datetime.now(timezone.utc).date().isoformat()}")
    print(f"  ledgers: {LEDGER_DIR}")
    print()

    # Run all 3 sleeves sequentially
    for s in SLEEVES:
        print(f"--- {s} ---")
        rc = _run_sleeve(s)
        if rc != 0:
            print(f"  [WARN] {s} failed; continuing to next sleeve")
        print()

    # Run NAV ledger for daily P&L accumulation (the 60d verdict needs this)
    print(f"--- {NAV_LEDGER_MODULE} ---")
    rc = _run_sleeve(NAV_LEDGER_MODULE)
    if rc != 0:
        print(f"  [WARN] NAV ledger failed; continuing")
    print()

    # ⓠ REGIME OVERRIDE paper track — parallel paper NAV under the enforcer.
    # Per Jazz 2026-08-06: 60d forward paper test of the enforcer (NOT a live override).
    # Reads R64 NAV (just-written above) + stablecoin signal → regime-adjusted NAV.
    # Gated: returns None if R64 NAV unavailable or signal too short (no fabrication).
    print("--- regime_override_track (ⓠ paper track) ---")
    try:
        from src.research.validation.fusion_paper_regime_track import compute_today_track
        today = datetime.now(timezone.utc).date().isoformat()
        regime_row = compute_today_track(today_iso=today)
        if regime_row is None:
            print(f"  GATED — R64 NAV missing or signal too short; track not advanced "
                  f"(no fabrication, per §CLAUDE.md no-mock-data)")
        else:
            print(f"  band={regime_row['band']} cap={regime_row['exposure_cap']} "
                  f"r77_ret={regime_row['r77_daily_return']:+.4f} "
                  f"regime_pnl={regime_row['regime_pnl_usd']:+.2f} "
                  f"regime_nav={regime_row['regime_nav_usd']:.2f}")
    except Exception as e:
        print(f"  [WARN] regime_track compute failed: {type(e).__name__}: {e}")
    print()

    # Read last row from each sleeve
    vol_carry = _read_last_row("vol_carry")
    regime = _read_last_row("regime_nowcast")
    macro = [r for r in (
        _read_last_row("macro_overlay"),
    )] if False else []  # noqa
    macro_path = LEDGER_DIR / "macro_overlay_positions.csv"
    macro_rows = []
    if macro_path.exists():
        with open(macro_path) as f:
            macro_rows = list(csv.DictReader(f))
    long_count = sum(1 for r in macro_rows if r.get("side") == "LONG")
    short_count = sum(1 for r in macro_rows if r.get("side") == "SHORT")

    # Build daily summary row
    today = datetime.now(timezone.utc).date().isoformat()
    row = {
        "date_utc": today,
        "vol_carry_iv": vol_carry.get("mark_price", ""),  # spot in vol_carry
        "vol_carry_rv": "",
        "vol_carry_term_premium": vol_carry.get("signal_value", ""),
        "vol_carry_action": vol_carry.get("sleeve_note", "").split("action=")[-1].split(" ")[0]
                             if "action=" in vol_carry.get("sleeve_note", "") else "",
        "regime_nowcast_btc_30d": "",
        "regime_nowcast_tvl_7d": "",
        "regime_nowcast_usdt_7d": "",
        "regime_nowcast_p": regime.get("signal_value", ""),
        "regime_nowcast_tilt": regime.get("qty", ""),
        "macro_overlay_long_count": long_count,
        "macro_overlay_short_count": short_count,
    }
    # Parse vol_carry sleeve_note for IV/RV
    note = vol_carry.get("sleeve_note", "")
    for part in note.split():
        if part.startswith("IV="):
            row["vol_carry_iv"] = part[3:]
        if part.startswith("RV="):
            row["vol_carry_rv"] = part[3:]

    # Parse regime sleeve_note for features
    rnote = regime.get("sleeve_note", "")
    for part in rnote.split():
        if part.startswith("btc_30d="):
            row["regime_nowcast_btc_30d"] = part[8:].rstrip("%")
        if part.startswith("tvl_7d="):
            row["regime_nowcast_tvl_7d"] = part[7:].rstrip("%")
        if part.startswith("usdt_7d="):
            row["regime_nowcast_usdt_7d"] = part[8:].rstrip("%")

    # Append (or update) today's row
    file_exists = DAILY_SUMMARY_PATH.exists()
    existing = []
    if file_exists:
        with open(DAILY_SUMMARY_PATH) as f:
            existing = list(csv.DictReader(f))
    # Replace today's row if it already exists
    existing = [r for r in existing if r.get("date_utc") != today]
    existing.append(row)
    with open(DAILY_SUMMARY_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DAILY_SUMMARY_HEADER)
        w.writeheader()
        w.writerows(existing)
    print(f"  ✓ daily summary written: {DAILY_SUMMARY_PATH}")
    print(f"  total days logged: {len(existing)}")
    print()
    print("Today's signal values:")
    print(f"  vol_carry         term_premium={row['vol_carry_term_premium']}  action={row['vol_carry_action']}")
    print(f"  regime_nowcast    p={row['regime_nowcast_p']}  tilt={row['regime_nowcast_tilt']}")
    print(f"  macro_overlay     longs={row['macro_overlay_long_count']}  shorts={row['macro_overlay_short_count']}")
    print()
    print("Daily NAV accumulation: see {sleeve_id}_nav.csv")
    print("  sleeve_3 — direct L/S basket return")
    print("  sleeve_1 — term_premium mean-reversion proxy")
    print("  sleeve_2 — tilt × R77 NAV (GATED on Supabase fusion_paper_nav)")
    print()
    print("ⓠ Regime track: /tmp/cometcloud_data/paper_books/fusion_paper_regime_track/regime_track.csv")
    print("  parallel paper NAV under the enforcer (NOT a live override)")
    print("  → 60d forward paper test feeds STRATEGY_PLAYBOOK.md §P3 promotion gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
