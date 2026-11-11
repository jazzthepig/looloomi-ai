#!/usr/bin/env python3
"""T-343 探针 #4:不带别名的 jsonb 取值 + 现金利率覆盖期。"""
from __future__ import annotations
import json, os, urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}


def q(path):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.headers.get("Content-Range"), json.loads(r.read().decode())


print("== 不带别名的 jsonb 取值 ==")
try:
    cr, rows = q("feature_matrix_daily?select=d,f->>'stable_lend_apy_7d'&order=d.asc&limit=3")
    print("  cr:", cr, "rows:", rows)
except Exception as e:
    print("  FAIL:", repr(e))

print("== 全表取(d + f),核覆盖期与缺口 ==")
rows, start, total = [], 0, None
while True:
    path = f"feature_matrix_daily?select=d,f&order=d.asc&limit=1000&offset={start}"
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    with urllib.request.urlopen(req, timeout=180) as r:
        cr = r.headers.get("Content-Range", "")
        page = json.loads(r.read().decode())
    if total is None and "/" in cr:
        total = int(cr.split("/")[-1])
    rows.extend(page)
    if len(page) < 1000:
        break
    start += 1000
    if total is not None and start >= total:
        break
print("  rows:", len(rows), "total:", total)
vals = [(r["d"], (r.get("f") or {}).get("stable_lend_apy_7d")) for r in rows]
nn = [(d, v) for d, v in vals if v is not None]
print("  with apy:", len(nn), "first:", nn[0] if nn else None, "last:", nn[-1] if nn else None)
import datetime as dt
ds = sorted(dt.date.fromisoformat(d) for d, _ in nn)
gaps = [(ds[i - 1].isoformat(), ds[i].isoformat(), (ds[i] - ds[i - 1]).days)
        for i in range(1, len(ds)) if (ds[i] - ds[i - 1]).days != 1]
print("  gaps(非逐日):", len(gaps), gaps[:8])
print("  weekday of first:", ds[0].strftime("%A"), "last:", ds[-1].strftime("%A"))
print("  apy min/max/median:", min(v for _, v in nn), max(v for _, v in nn),
      sorted(v for _, v in nn)[len(nn) // 2])
print("  sample:", nn[:3], nn[-3:])
