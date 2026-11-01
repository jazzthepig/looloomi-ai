#!/usr/bin/env python3
"""T-217 step 1: probe Supabase table existence + column shape (read-only).

Publishable key cannot read the OpenAPI root (needs secret), so we probe
candidate table names one by one; 404 == table absent, 401/403 == RLS block.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}

CAND = [
    "core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
    "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
    "depth_divergence_log", "rr_matrix_daily",
    "loop_attempt", "loop_attempts", "executor_heartbeat", "executor_host", "executor_hosts",
    "heartbeat", "core_variants_daily", "multiplier_daily", "feature_arms_daily",
    "meta_allocator_daily", "portfolio_layer_daily", "r_money_daily", "short_paper_money",
    "beta_core_nav", "risk_meter_history", "cis_official_daily", "signal_journal",
    "scheduler_heartbeat", "job_runs", "executor_run", "executor_status",
]


def probe(t: str) -> dict:
    q = urllib.parse.urlencode({"select": "*", "limit": "1"}, safe="(),:*$")
    req = urllib.request.Request(f"{SB}/rest/v1/{t}?{q}", headers=H)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            b = json.loads(r.read().decode())
            return {"exists": True, "cols": list(b[0].keys()) if b else [], "sample": b[0] if b else None}
    except urllib.error.HTTPError as e:
        return {"exists": False, "err": e.code, "msg": e.read().decode()[:140]}
    except Exception as e:  # noqa: BLE001
        return {"exists": False, "err": type(e).__name__, "msg": str(e)[:140]}


def main() -> None:
    out = {}
    for t in CAND:
        r = probe(t)
        out[t] = r
        flag = "OK " if r["exists"] else "NO "
        detail = r.get("cols") if r["exists"] else r.get("msg", "")
        print(flag, t, str(detail)[:220])
    with open("/tmp/t217_probe_tables.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
