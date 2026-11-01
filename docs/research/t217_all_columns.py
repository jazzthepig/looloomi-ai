#!/usr/bin/env python3
"""T-217: 保存全部 public 表的列名(rpc/public_columns,只读)→ t217_all_columns.json"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent


def main() -> None:
    qq = urllib.parse.urlencode({}, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/rpc/public_columns?" + qq, headers=H)
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode() or "{}")
    (HERE / "t217_all_columns.json").write_text(json.dumps(body, ensure_ascii=False, indent=1))
    print("tables:", len(body))
    for t in ("causal_paper_nav", "r77_forward_episodes", "nav_exceptions", "trending_log",
              "vault_nav_tick", "execution_unresolved", "regime_band_log", "crowd_clock_log",
              "trade_results", "execution_outcomes", "j_tickets", "interpretation_validation_runs",
              "r_money_daily", "state_daily", "social_daily", "perp_bv_daily"):
        print(f"  {t:32s}", body.get(t))


if __name__ == "__main__":
    main()
