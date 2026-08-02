"""Shared paper-book ledger for the 3-sleeve parallel prototype (Seth, 2026-07-28).

Per user direction 2026-07-28 ("三件并行 paper only, 60d forward paper, 不卡 1.96"),
this is the unified append-only log interface used by:
  - sleeve_1: vol_carry_paper.py
  - sleeve_2: regime_nowcast_paper.py
  - sleeve_3: macro_overlay_paper.py

R77's existing `fusion_paper_nav` table on Supabase is the production-of-record for
Strategy 1; these parallel sleeves write to local CSV so they do not contaminate the
R77 paper book. After 60 days the 3 sleeves' CSVs are aggregated for a parallel
paper verdict (Sharpe / maxDD / orthogonal-to-R77).

Schema (one row per paper position, indexed by sleeve_id + ts + symbol):
  sleeve_id, ts_utc, symbol, side, qty, mark_price, signal_value, signal_name,
  notional_usd, sleeve_note

CSV path: /tmp/cometcloud_data/paper_books/{sleeve_id}_positions.csv
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LEDGER_DIR = Path("/tmp/cometcloud_data/paper_books")
LEDGER_DIR.mkdir(parents=True, exist_ok=True)

CSV_HEADER = [
    "sleeve_id", "ts_utc", "symbol", "side", "qty", "mark_price",
    "signal_value", "signal_name", "notional_usd", "sleeve_note",
]


@dataclass
class PaperPosition:
    sleeve_id: str           # e.g. "vol_carry", "regime_nowcast", "macro_overlay"
    symbol: str              # ticker, e.g. "BTC", "TLT", "DXY"
    side: str                # "LONG" | "SHORT" | "FLAT"
    qty: float               # notional units (USD for cash, contracts for futures)
    mark_price: float        # mid at decision time
    signal_value: float      # the raw signal (term_premium, P(RISK_ON), cross-asset score)
    signal_name: str         # e.g. "term_premium_pct", "p_risk_on", "macro_z"
    notional_usd: float      # |qty * mark_price| (paper book nav reference)
    sleeve_note: str = ""
    ts_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _csv_path(sleeve_id: str) -> Path:
    safe = sleeve_id.replace("/", "_").replace(" ", "_")
    return LEDGER_DIR / f"{safe}_positions.csv"


def append_paper_position(pos: PaperPosition) -> Path:
    """Append a single PaperPosition to {sleeve_id}_positions.csv.

    Creates the file with header if missing. Returns the CSV path.
    """
    path = _csv_path(pos.sleeve_id)
    file_exists = path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if not file_exists:
            w.writeheader()
        w.writerow({k: getattr(pos, k) for k in CSV_HEADER})
    return path


def read_sleeve(sleeve_id: str) -> list[dict]:
    """Read all positions for a sleeve (for daily NAV computation)."""
    path = _csv_path(sleeve_id)
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def all_sleeves_summary() -> dict:
    """Quick summary across all sleeves — for the 60d review endpoint."""
    out = {}
    for path in sorted(LEDGER_DIR.glob("*_positions.csv")):
        sleeve_id = path.name.replace("_positions.csv", "")
        rows = read_sleeve(sleeve_id)
        n = len(rows)
        notional = sum(float(r.get("notional_usd") or 0) for r in rows)
        out[sleeve_id] = {
            "n_positions": n,
            "total_notional_usd": round(notional, 2),
            "csv_path": str(path),
        }
    return out


if __name__ == "__main__":
    # Self-test
    test = PaperPosition(
        sleeve_id="smoke",
        symbol="BTC",
        side="LONG",
        qty=1.0,
        mark_price=100000.0,
        signal_value=0.0,
        signal_name="smoke",
        notional_usd=100000.0,
        sleeve_note="ledger smoke",
    )
    p = append_paper_position(test)
    rows = read_sleeve("smoke")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTC"
    print(f"✓ ledger smoke: {p}  rows={len(rows)}")
    # Clean up smoke row
    p.unlink()
