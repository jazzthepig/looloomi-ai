#!/usr/bin/env python3
"""T-217: the decisive test for 「未回填」.

For a handful of key arms, print the actual (d, computed_at) sequence and count
DISTINCT computed_at values vs distinct d values. A bulk backfill writes many d
rows sharing ONE computed_at; a daily writer writes one row per d with
computed_at advancing day by day.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path
import os
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}

TARGETS = [
    ("core_cap_daily", "cap_a05", "d,computed_at,inception", "d.asc"),
    ("cis_tilt_daily", "cis_a1_u", "d,computed_at,inception", "d.asc"),
    ("core_variants_daily", "mom90", "d,computed_at,inception", "d.asc"),
    ("multiplier_daily", "mult_v2", "d,computed_at,inception", "d.asc"),
    ("hl_book_daily", None, "d,book,computed_at,correction", "d.asc,book.asc"),
    ("beta_core_nav", None, "mark_date,marked_at,rebalanced", "mark_date.asc"),
    ("risk_meter_history", None, "d,computed_at,band", "d.asc"),
    ("r_money_daily", None, "d,computed_at,inception", "d.asc"),
]


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
    for t, arm, cols, order in TARGETS:
        params = {"select": cols, "order": order, "limit": "3000"}
        if arm:
            params["arm"] = f"eq.{arm}"
        st, rows = q(t, params)
        if st != 200:
            print("ERR", t, arm, st, str(rows)[:120])
            continue
        dcol = "d" if any("d" in c for c in cols.split(",")) else "mark_date"
        tscol = "computed_at" if "computed_at" in cols else "marked_at"
        seq = [(r.get(dcol), str(r.get(tscol))) for r in rows]
        ts_vals = [s for _, s in seq]
        c = collections.Counter(ts_vals)
        nd = len({d for d, _ in seq})
        nts = len(c)
        maxc = max(c.values()) if c else 0
        print(f"\n=== {t} arm={arm}  rows={len(rows)} distinct_d={nd} distinct_ts={nts} "
              f"max_rows_per_ts={maxc}")
        top = c.most_common(6)
        print("   top computed_at clusters:", [(k[:19], v) for k, v in top])
        print("   first 6 (d, computed_at):", [(a, b[:19]) for a, b in seq[:6]])
        print("   last 6  (d, computed_at):", [(a, b[:19]) for a, b in seq[-6:]])
        out[f"{t}.{arm}"] = {"rows": len(rows), "distinct_d": nd, "distinct_ts": nts,
                             "max_rows_per_ts": maxc, "seq": seq,
                             "top_clusters": top}
    with open(str(Path(__file__).resolve().parent / "t217_ts_sequence.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
