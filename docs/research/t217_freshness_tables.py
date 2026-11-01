#!/usr/bin/env python3
"""T-217: read /internal/data-freshness producers.tables + books + liveness.

This is the only public surface that names the RLS-blocked tables. Extract
per-table verdicts (n_rows, last write, age) and the per-book forward records.
"""
from __future__ import annotations

import json
from pathlib import Path
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
TARGET = ["core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
          "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
          "depth_divergence_log", "rr_matrix_daily", "loop_attempt", "core_variants_daily",
          "multiplier_daily", "portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily",
          "beta_core_nav", "r_money_daily", "short_paper_money", "risk_meter_history",
          "cis_official_daily", "signal_journal"]


def main() -> None:
    d = json.loads(urllib.request.urlopen(f"{BASE}/internal/data-freshness", timeout=90).read().decode())
    prod = d.get("producers") or {}
    tabs = prod.get("tables") or {}
    print("producers keys:", list(prod.keys()))
    print("n tables in producers:", len(tabs))
    print()
    for t in TARGET:
        v = tabs.get(t)
        if v is None:
            print(f"{t:26s} ABSENT from producers.tables")
            continue
        w = v.get("write") or {}
        print(f"{t:26s} verdict={v.get('verdict'):10s} n_rows={v.get('n_rows')} "
              f"last_write={w.get('last')} age_days={w.get('age_days')} write_col={w.get('col')}")
        if v.get("reason"):
            print(f"{'':26s}   reason: {str(v.get('reason'))[:150]}")
    print()
    print("=== books ===")
    books = d.get("books") or {}
    print(json.dumps(books, ensure_ascii=False)[:2500])
    print()
    print("=== coverage ===")
    print(json.dumps(d.get("coverage"), ensure_ascii=False)[:1500])
    with open(str(Path(__file__).resolve().parent / "t217_freshness_tables.json"), "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
