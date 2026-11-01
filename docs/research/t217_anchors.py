#!/usr/bin/env python3
"""T-217 —— 锚点序列的连续性 + hl_book_daily correction 全文(第三方可验证性)。"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent

# 1) 锚点:第三方唯一能自验的东西
req = urllib.request.Request("https://web-production-0cdf76.up.railway.app/api/v1/proof/anchors",
                             headers={"User-Agent": "t217-readonly"})
with urllib.request.urlopen(req, timeout=90) as r:
    a = json.loads(r.read().decode())
anc = a.get("anchors") or []
print("### proof/anchors count=", a.get("count"), "as_of=", a.get("as_of"))
ds = [x["d"] for x in anc]
print("   d range:", min(ds), "->", max(ds), "| n=", len(ds), "| unique:", len(set(ds)))
have = {dt.date.fromisoformat(x) for x in ds}
lo, hi = min(have), max(have)
miss = []
day = lo
while day <= hi:
    if day not in have:
        miss.append(day.isoformat())
    day += dt.timedelta(days=1)
print("   期望日历天:", (hi - lo).days + 1, "| 缺失:", miss if miss else "无")
for x in sorted(anc, key=lambda z: z["d"]):
    lag = (dt.datetime.fromisoformat(str(x["submitted_at"]).replace("Z", "+00:00")).date()
           - dt.date.fromisoformat(x["d"])).days
    print("   %s rows=%-4s submitted=%s lag=%sd digest=%s" % (
        x["d"], x.get("n_rows"), x.get("submitted_at"), lag, str(x.get("digest"))[:16]))

# 2) hl_book_daily 的 correction 全文
url = (SB + "/rest/v1/hl_book_daily?select=d,computed_at,correction&order=d.asc")
req2 = urllib.request.Request(url, headers=H)
with urllib.request.urlopen(req2, timeout=90) as r:
    rows = json.loads(r.read().decode() or "[]")
print()
print("### hl_book_daily correction 非空的行")
seen = set()
for x in rows:
    c = x.get("correction")
    if c in (None, "", [], {}):
        continue
    txt = json.dumps(c, ensure_ascii=False)
    if txt not in seen:
        seen.add(txt)
        print("   payload:", txt[:900])
        print("   出现在 d:", [y["d"] for y in rows if y.get("correction") not in (None, "", [], {})])
        break
print("   correction 非空的 d 列表:",
      [y["d"] for y in rows if y.get("correction") not in (None, "", [], {})])
