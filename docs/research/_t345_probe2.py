"""T-345 探针 2:查 state_daily(panel)有哪些 feature 可用,并测基率。

只读库。state_daily 是长表:entity / feature / d / value。
"""
from __future__ import annotations

import json
import os
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def fetch(table: str, query: str, order: str) -> list[dict]:
    rows, start, total = [], 0, None
    while True:
        req = urllib.request.Request(
            f"{URL}/rest/v1/{table}?{query}&order={order}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Prefer": "count=exact", "Range": f"{start}-{start + 999}"},
        )
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
    if total is not None and len(rows) != total:
        raise SystemExit(f"{table}: 抓到 {len(rows)} 行 ≠ total {total}")
    return rows


last_d = fetch("state_daily", "select=d&entity=eq.panel&order=d.desc", "d.desc")[0]["d"]
print("latest d:", last_d)
rows = fetch("state_daily", f"select=feature,value&entity=eq.panel&d=eq.{last_d}", "feature.asc")
print("features:", len(rows))
for r in rows:
    print(f"  {r['feature']}: {r['value']}")
