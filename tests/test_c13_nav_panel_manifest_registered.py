"""
C-13 P4 — schema_manifest knows about cap-weighted ① nav_panel tables + mcap fields.

WHY THIS TEST EXISTS. `src/api/contracts/c13_nav_panel_manifest.py` declares
`WRITES_TABLES = ("nav_panel_rebalances", "nav_panel_daily")` and
`WRITES_COLUMNS = {"market_state_vectors": {...}, ...}`. The
`src/api/schema_manifest.py` AST walker reads those declarations and merges
them into `write_tables()` / `write_columns()`. Without this test, a refactor
that drops the declaration or narrows the column set would not be caught
before the next deploy — and the drift probe (`/internal/schema-drift`)
would silently miss `nav_panel_*` tables and the three new columns.

Pins four contracts:
  1. `nav_panel_rebalances` appears in `write_tables()`.
  2. `nav_panel_daily` appears in `write_tables()`.
  3. `market_state_vectors` in `write_columns()` carries the three C-13
     fields (`mcap_usd`, `adv_usd_20d`, `adv_screen_pass`).
  4. `nav_panel_rebalances` + `nav_panel_daily` in `write_columns()` carry
     their declared columns (a partial declaration would not be caught by
     (1)+(2) alone — a table can be known to exist yet have no known columns).

Run: python3 -m tests.test_c13_nav_panel_manifest_registered
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.api.schema_manifest import write_tables, write_columns  # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def test_t1_nav_panel_rebalances_in_write_tables():
    tables = write_tables()
    check("nav_panel_rebalances in write_tables()",
          "nav_panel_rebalances" in tables,
          f"tables missing nav_panel_rebalances: {sorted(t for t in tables if 'nav_panel' in t)}")


def test_t2_nav_panel_daily_in_write_tables():
    tables = write_tables()
    check("nav_panel_daily in write_tables()",
          "nav_panel_daily" in tables,
          f"tables missing nav_panel_daily: {sorted(t for t in tables if 'nav_panel' in t)}")


def test_t3_market_state_vectors_has_three_new_columns():
    cols = write_columns()
    msv = cols.get("market_state_vectors", [])
    missing = sorted({"mcap_usd", "adv_usd_20d", "adv_screen_pass"} - set(msv))
    check("market_state_vectors carries mcap_usd + adv_usd_20d + adv_screen_pass",
          not missing,
          f"missing C-13 columns: {missing}; have: {msv}")


def test_t4_nav_panel_tables_have_their_declared_columns():
    cols = write_columns()
    rebal = cols.get("nav_panel_rebalances", [])
    daily = cols.get("nav_panel_daily", [])
    rebal_missing = sorted({"symbol", "weight", "mcap_usd", "as_of", "trade_date"} - set(rebal))
    daily_missing = sorted({"trade_date", "nav", "return_pct"} - set(daily))
    check("nav_panel_rebalances columns declared (symbol/weight/mcap_usd/as_of/trade_date)",
          not rebal_missing,
          f"missing: {rebal_missing}; have: {rebal}")
    check("nav_panel_daily columns declared (trade_date/nav/return_pct)",
          not daily_missing,
          f"missing: {daily_missing}; have: {daily}")


if __name__ == "__main__":
    print("── C-13 P4: schema_manifest registers nav_panel_* + mcap fields ──")
    test_t1_nav_panel_rebalances_in_write_tables()
    test_t2_nav_panel_daily_in_write_tables()
    test_t3_market_state_vectors_has_three_new_columns()
    test_t4_nav_panel_tables_have_their_declared_columns()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ nav_panel_rebalances + nav_panel_daily registered · "
          "market_state_vectors carries mcap/adv columns · "
          "WRITES_COLUMNS declaration surfaced in the offline manifest")
