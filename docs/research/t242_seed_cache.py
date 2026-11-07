#!/usr/bin/env python3
"""Seed the T-242 perp_bv_daily cache from the T-238 pull (identical query, fetched 2026-11-05T03:09Z).

T-238 file: /Volumes/CometCloudAI/cometcloud-local/research/t238/_bars_pbv.jsonl
  line 0 = _meta;  lines 1.. = JSON arrays of {symbol,d,o,h,l,c,qv,tbqv}
Query: perp_bv_daily?select=symbol,d,o,h,l,c,qv,tbqv&d=gte.2019-10-01&d=lte.2026-11-04&order=symbol.asc,d.asc
"""
import json
import os
import sys

SRC = "/Volumes/CometCloudAI/cometcloud-local/research/t238/_bars_pbv.jsonl"
DST = "/Volumes/CometCloudAI/cometcloud-local/research/t242/cache/perp_bv_daily.json"

rows = []
meta = None
with open(SRC) as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if i == 0:
            meta = obj.get("_meta", obj)
            continue
        rows.extend(obj)
os.makedirs(os.path.dirname(DST), exist_ok=True)
out = {"meta": {"fetched_at_utc": (meta or {}).get("fetched_at_utc"),
                "table": "perp_bv_daily",
                "n_rows": len(rows),
                "source": "T-238 cache (identical query)",
                "query": (meta or {}).get("query")},
       "rows": rows}
with open(DST, "w") as f:
    json.dump(out, f)
print("seeded", len(rows), "rows ->", DST)
