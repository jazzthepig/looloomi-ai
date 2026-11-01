#!/usr/bin/env python3
"""T-217: extract the coverage tier of every named table from data-freshness.

`coverage.not_covered_by_tier` names the tables the platform itself does not
watch. A daily forward table that lands in "ops"/"track_record" tier is one the
platform cannot prove the continuity of — that is the answer to the card's
「能否被外部第三方当作证据」question.
"""
from __future__ import annotations

import json
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
TARGET = ["core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
          "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
          "depth_divergence_log", "rr_matrix_daily", "core_variants_daily", "multiplier_daily",
          "portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily",
          "r_money_daily", "short_paper_money", "risk_meter_history", "cis_official_daily",
          "signal_journal", "beta_core_nav"]


def main() -> None:
    d = json.loads(urllib.request.urlopen(f"{BASE}/internal/data-freshness", timeout=90).read().decode())
    cov = d.get("coverage") or {}
    by_tier = {}
    for tier, tables in (cov.get("not_covered_by_tier") or {}).items():
        for t in tables:
            by_tier.setdefault(t, []).append(tier)
    print("coverage summary:", {k: v for k, v in cov.items() if k != "not_covered_by_tier"})
    print()
    print(f"{'table':28s} {'tier(not covered by)':30s} {'covered?':10s}")
    for t in TARGET:
        tiers = by_tier.get(t, [])
        print(f"{t:28s} {','.join(tiers) if tiers else '-':30s} "
              f"{'NO' if tiers else 'yes':10s}")
    print()
    print("=== all tiers present ===")
    for tier, tables in (cov.get("not_covered_by_tier") or {}).items():
        print(f"  {tier}: n={len(tables)}")
    print()
    print("=== verdict_scope / note ===")
    for k in ("verdict_scope", "verdict_note", "verdict_source", "overall"):
        print(k, ":", json.dumps(d.get(k), ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
