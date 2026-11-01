#!/usr/bin/env python3
"""T-217 —— risk_meter_history 的缺口逐日核对(这是新发现,必须逐日核,不靠汇总数)。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent


def get(path, **kw):
    q = urllib.parse.urlencode(kw, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    with urllib.request.urlopen(req, timeout=120) as x:
        return json.loads(x.read().decode() or "[]")


rows = get("risk_meter_history", select="d,computed_at,regime,band,score", order="d.asc")
days = sorted(r["d"] for r in rows)
sd = {dt.date.fromisoformat(x) for x in days}
lo, hi = min(sd), max(sd)
print("rows:", len(rows), "| unique d:", len(sd), "|", lo, "->", hi)
print("computed_at 时刻分布(UTC 时):", sorted({str(r.get("computed_at"))[11:13] for r in rows}))

runs, cur = [], None
day = lo
while day <= hi:
    if day in sd:
        if cur:
            runs.append((cur[0], cur[1], (cur[1] - cur[0]).days + 1))
            cur = None
    else:
        cur = [day, day] if cur is None else [cur[0], day]
    day += dt.timedelta(days=1)
if cur:
    runs.append((cur[0], cur[1], (cur[1] - cur[0]).days + 1))

print("缺口段数:", len(runs), "| 缺失天数合计:", sum(r[2] for r in runs))
for a, b, n in runs:
    print("   缺口 %s .. %s  (%d 天)" % (a, b, n))
print()
print("缺口前后各 3 行:")
for r in rows:
    if "2026-10-10" <= r["d"] <= "2026-11-01":
        print("   ", r["d"], r.get("computed_at"), "band=", r.get("band"))
