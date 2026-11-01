#!/usr/bin/env python3
"""T-217 ③: is there ANY explainable row for the +17.4 live-balance move during
the 64.7h executor_host heartbeat gap (2026-10-26 21:42 UTC -> 2026-10-29 14:24 UTC)?

Readable candidates (publishable key): execution_intents, execution_outcomes,
decisions, vault_nav_tick, trade_results, wallet_profiles, nav_exceptions.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import os
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}

GAP_A = "2026-10-26T21:42:00Z"
GAP_B = "2026-10-29T14:24:00Z"

TABLES = ["execution_intents", "execution_outcomes", "decisions", "vault_nav_tick",
          "trade_results", "wallet_profiles", "nav_exceptions"]


def q(table: str, params: dict) -> tuple:
    qq = urllib.parse.urlencode(params, safe="(),:*$")
    req = urllib.request.Request(f"{SB}/rest/v1/{table}?{qq}", headers=H)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def main() -> None:
    out = {}
    for t in TABLES:
        st, sample = q(t, {"select": "*", "limit": "1"})
        if st != 200:
            print("ERR", t, st, str(sample)[:120])
            continue
        cols = list(sample[0].keys()) if sample else []
        if not cols:
            # empty sample: either the table is empty, or every row is RLS-filtered.
            st_c, cnt = q(t, {"select": "*", "limit": "1"})
            print(f"{t:20s} NO COLUMNS from sample; probe status={st_c}")
            out[t] = {"cols": [], "note": "sample empty — table empty or fully RLS-filtered"}
            continue
        # pick a date-ish column
        datecol = next((c for c in cols if c in ("at", "ts", "created_at", "d",
                                                 "trade_date", "recorded_at", "logged_at",
                                                 "executed_at", "as_of", "marked_at")), None)
        # count all rows via the data-landing-like trick: select the date col and count len
        st2, rows = q(t, {"select": datecol or cols[0], "order": (datecol or cols[0]) + ".asc", "limit": "5000"})
        n_all = len(rows) if st2 == 200 else None
        print(f"{t:20s} n_rows<=5000: {n_all} datecol={datecol}")
        print(f"{'':20s} cols: {cols}")
        out[t] = {"cols": cols, "datecol": datecol, "n": n_all}
        if datecol and st2 == 200 and rows:
            vals = [r.get(datecol) for r in rows if r.get(datecol)]
            print(f"{'':20s} first={vals[0]} last={vals[-1]}")
            # rows inside the gap window
            inwin = [v for v in vals if GAP_A <= str(v)[:19] <= GAP_B]
            print(f"{'':20s} IN-GAP rows: {len(inwin)}")
            out[t]["in_gap"] = inwin
            out[t]["first"] = vals[0]
            out[t]["last"] = vals[-1]
    with open(str(Path(__file__).resolve().parent / "t217_exec_tables.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
