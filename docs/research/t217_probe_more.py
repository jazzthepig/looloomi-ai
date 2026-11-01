#!/usr/bin/env python3
"""T-217: probe additional tables for readability + content (③ balance evidence).

live_account_daily is RLS-blocked for the publishable key. The card asks whether
the +17.4 balance move has ANY explainable row in the DB during the 64.7h
executor_host gap. Candidates: execution_intents / execution_outcomes / trades /
vault_nav_tick / wallet_profiles.
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

CAND = ["execution_intents", "execution_outcomes", "trades", "trade_results",
        "vault_nav_tick", "wallet_profiles", "orders", "fills", "ledger_entries",
        "paper_positions", "nav_exceptions", "forward_book_nav", "causal_paper_nav",
        "strategy_records", "experiment_runs", "strategy_params", "decision_log",
        "decisions", "audit_log", "account_daily", "account_snapshots",
        "live_account", "live_account_snapshots", "executor_heartbeats",
        "executor_host_heartbeat", "host_heartbeat"]


def probe(t: str) -> dict:
    q = urllib.parse.urlencode({"select": "*", "limit": "1"}, safe="(),:*$")
    req = urllib.request.Request(f"{SB}/rest/v1/{t}?{q}", headers=H)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            b = json.loads(r.read().decode())
            return {"readable": True, "cols": list(b[0].keys()) if b else [], "sample": b[0] if b else None}
    except urllib.error.HTTPError as e:
        return {"readable": False, "status": e.code, "note": e.read().decode()[:110]}
    except Exception as e:  # noqa: BLE001
        return {"readable": False, "status": type(e).__name__, "note": str(e)[:110]}


def main() -> None:
    out = {}
    for t in CAND:
        r = probe(t)
        out[t] = r
        flag = "OK " if r["readable"] else "NO "
        print(flag, t, (r.get("cols") if r["readable"] else r.get("note", ""))[:200])
    with open("/tmp/t217_probe_more.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
