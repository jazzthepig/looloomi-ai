#!/usr/bin/env python3
"""
export_backtest_to_supabase.py — Simons Upgrade P0.1
====================================================
Reads backtest result JSON (Freqtrade export trades) → queries CIS score at entry
via CISHistoryProvider → writes combined row to Supabase trade_results.

Usage:
    python export_backtest_to_supabase.py backtest_results.json
    python export_backtest_to_supabase.py --latest   # find most recent zip/json
    python export_backtest_to_supabase.py --dry-run   # show what would be exported

Each trade row captures:
    - Entry CIS state (score, grade, all 5 pillars, macro regime)
    - Realized return 7d (computed from price at exit vs entry)
    - Trade metadata (side, profit, strategy, enter_tag)

This closes the feedback loop: scores → trades → realized returns → regression.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

_log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_KEY", ""))
SUPABASE_TABLE = "trade_results"

# Local path where Freqtrade backtests are stored
BACKTEST_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/backtest_results")
RAILWAY_BASE = os.getenv("COMETCLOUD_API_BASE", "https://looloomi.ai")


def _parse_trade_row(row: dict) -> dict:
    """Normalize a Freqtrade trade export row into our schema."""
    # Freqtrade exports: open_rate, close_rate, profit_abs, profit_ratio,
    # exit_reason, enter_tag, side, pair, open_time, close_time
    return {
        "symbol":         row.get("pair", "").replace("_", "/"),
        "side":           row.get("side", "").upper(),
        "entry_time":     _parse_ts(row.get("open_time")),
        "exit_time":      _parse_ts(row.get("close_time")),
        "entry_price":    row.get("open_rate"),
        "exit_price":     row.get("close_rate"),
        "profit_pct":     round(row.get("profit_ratio", 0) * 100, 4) if row.get("profit_ratio") is not None else None,
        "profit_abs":     row.get("profit_abs"),
        "exit_reason":    row.get("exit_reason"),
        "enter_tag":      row.get("enter_tag"),
        "strategy":       row.get("strategy", "unknown"),
    }


def _parse_ts(ts_str: str) -> Optional[str]:
    """Parse ISO timestamp, return ISO string or None."""
    if not ts_str:
        return None
    try:
        # Handle milliseconds or seconds
        if ts_str.isdigit():
            ts = int(ts_str)
            if ts > 1e12:  # milliseconds
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _load_cis_history_provider():
    """Lazy-import and create CISHistoryProvider."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from src.data.cis.cis_history_provider import CISHistoryProvider
    return CISHistoryProvider()


def _fetch_cis_at_entry(symbol: str, entry_time: str, provider) -> dict:
    """Query CISHistoryProvider for CIS state at entry time."""
    if not entry_time:
        return {}
    try:
        dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
    except Exception:
        return {}

    score = provider.get_cis_at(symbol, dt)
    if score is None:
        return {}

    return {
        "cis_score_at_entry":   score,
        "cis_grade_at_entry":   provider.get_grade_at(symbol, dt),
        "pillar_f_at_entry":    provider.get_pillar_at(symbol, dt).get("F"),
        "pillar_m_at_entry":    provider.get_pillar_at(symbol, dt).get("M"),
        "pillar_o_at_entry":    provider.get_pillar_at(symbol, dt).get("O"),
        "pillar_s_at_entry":    provider.get_pillar_at(symbol, dt).get("S"),
        "pillar_a_at_entry":    provider.get_pillar_at(symbol, dt).get("A"),
        "macro_regime_at_entry": provider.get_regime_at(symbol, dt),
    }


def _compute_realized_7d(trade_row: dict, all_trades_by_symbol: dict) -> Optional[float]:
    """
    For a closed trade, compute realized return over 7 days post-exit.
    If price data is available from backtest, use it; otherwise return None
    and accept that the feedback loop will need live trade data to close.
    """
    if not trade_row.get("exit_price") or not trade_row.get("entry_price"):
        return None

    # This requires having price data 7d after exit — not always available in backtest.
    # Mark as None; live Freqtrade will write realized_return_7d via quant push.
    return None


def _write_trade_results(rows: list[dict]) -> bool:
    """Bulk-insert trade result rows into Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY or not rows:
        return False

    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, content=json.dumps(rows), headers=headers)
        if resp.status_code in (200, 201):
            _log.info(f"[EXPORT] Wrote {len(rows)} trade rows to Supabase")
            return True
        _log.warning(f"[EXPORT] Write failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        _log.warning(f"[EXPORT] Exception: {e}")
    return False


def export_backtest_file(filepath: Path, dry_run: bool = False) -> dict:
    """
    Main export function: read backtest JSON → enrich with CIS data → write to Supabase.
    Returns summary dict.
    """
    if not filepath.exists():
        return {"error": f"File not found: {filepath}"}

    with open(filepath) as f:
        data = json.load(f)

    # Handle both single-trade-array and wrapped {trades: [...]} formats
    trades = data.get("trades", data) if isinstance(data, dict) else data
    if not isinstance(trades, list):
        return {"error": "Invalid format: expected list of trades"}

    provider = _load_cis_history_provider()
    enriched_rows = []
    skipped = 0

    for raw_row in trades:
        row = _parse_trade_row(raw_row)
        if not row.get("symbol") or not row.get("entry_time"):
            skipped += 1
            continue

        cis_state = _fetch_cis_at_entry(
            row["symbol"],
            row["entry_time"],
            provider,
        )
        row.update(cis_state)
        row["recorded_at"] = datetime.now(timezone.utc).isoformat()

        # Realized 7d return: only set if exit_price available (closed trade)
        if row.get("exit_price") and row.get("entry_price"):
            row["realized_return_7d"] = None  # computed live; backtest price data gap
        else:
            row["realized_return_7d"] = None

        enriched_rows.append(row)

    if dry_run:
        print(f"\n[DRY RUN] Would export {len(enriched_rows)} trades ({skipped} skipped)")
        for r in enriched_rows[:5]:
            print(f"  {r['symbol']} | entry={r['entry_time'][:19]} | "
                  f"CIS={r.get('cis_score_at_entry', 'N/A')} | "
                  f"grade={r.get('cis_grade_at_entry', 'N/A')}")
        if len(enriched_rows) > 5:
            print(f"  ... and {len(enriched_rows) - 5} more")
        return {"dry_run": True, "count": len(enriched_rows), "skipped": skipped}

    ok = _write_trade_results(enriched_rows)
    return {
        "total":    len(enriched_rows),
        "written":  ok,
        "skipped":  skipped,
        "file":     str(filepath),
    }


def find_latest_backtest() -> Optional[Path]:
    """Find most recent backtest result file in BACKTEST_DIR."""
    if not BACKTEST_DIR.exists():
        return None
    candidates = list(BACKTEST_DIR.glob("*.json")) + list(BACKTEST_DIR.glob("*.zip"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export Freqtrade backtest results to Supabase")
    parser.add_argument("filepath", nargs="?", help="Path to backtest result JSON/ZIP")
    parser.add_argument("--latest", action="store_true", help="Auto-find latest backtest result")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be exported")
    args = parser.parse_args()

    if args.latest:
        path = find_latest_backtest()
        if path:
            print(f"Found: {path}")
        else:
            print("No backtest results found")
            sys.exit(1)
    elif args.filepath:
        path = Path(args.filepath)
    else:
        print("Provide --latest or a filepath")
        sys.exit(1)

    result = export_backtest_file(path, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))