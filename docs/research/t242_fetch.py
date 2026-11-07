#!/usr/bin/env python3
"""T-242 fetch layer — read-only pull from Supabase with an on-disk cache.

只用 os.environ["SUPABASE_URL"] / os.environ["SUPABASE_KEY"];翻页一律带 order=。
缓存目录:/Volumes/CometCloudAI/cometcloud-local/research/t242/cache
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t242/cache"
HDR = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}

TABLES = {
    "perp_bv_daily": {
        "select": "symbol,d,o,h,l,c,qv,tbqv",
        "d": "gte.2019-10-01",
        "d2": "lte.2026-11-04",
        "order": "symbol.asc,d.asc",
    },
    "v_funding_daily": {
        "select": "symbol,d,funding_rate",
        "order": "symbol.asc,d.asc",
    },
    "deriv_metrics_daily": {
        "select": "symbol,d,oi_close,oi_value_close",
        "order": "symbol.asc,d.asc",
    },
    "perp_bv_pairs": {
        "select": "symbol,kind,dead_from,first_d",
        "order": "symbol.asc",
    },
}


def _get_page(table, extra, start, step):
    q = {"select": TABLES[table]["select"], "order": TABLES[table]["order"]}
    if "d" in TABLES[table]:
        q["d"] = TABLES[table]["d"]
    if "d2" in TABLES[table]:
        q["d2"] = TABLES[table]["d2"]
    q.update(extra)
    url = U + "/rest/v1/" + table + "?" + urllib.parse.urlencode(q)
    h = dict(HDR)
    h["Range"] = "bytes=%d-%d" % (start, start + step - 1)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=300) as r:
        body = r.read()
        cr = r.headers.get("Content-Range")
    return json.loads(body.decode()), cr


def fetch(table, step=10000):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, table + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)["rows"]
    rows = []
    start = 0
    total = None
    t0 = time.time()
    while True:
        page, cr = _get_page(table, {}, start, step)
        if not page:
            break
        rows.extend(page)
        if total is None and cr and "/" in cr:
            try:
                total = int(cr.split("/")[-1])
            except ValueError:
                total = None
        if len(page) < step and total is None:
            break
        start += len(page)
        if total is not None and start >= total:
            break
        if len(page) < step:
            step = len(page)
        if start % (step * 10) == 0:
            print("  %s %d/%s rows (%.0fs)" % (table, len(rows), total, time.time() - t0), flush=True)
    meta = {"fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "table": table, "n_rows": len(rows), "query": TABLES[table]}
    with open(path, "w") as f:
        json.dump({"meta": meta, "rows": rows}, f)
    print("  DONE %s %d rows in %.0fs" % (table, len(rows), time.time() - t0), flush=True)
    return rows


def load(table):
    path = os.path.join(CACHE, table + ".json")
    with open(path) as f:
        return json.load(f)["rows"]


if __name__ == "__main__":
    import sys
    tabs = sys.argv[1:] or list(TABLES)
    for t in tabs:
        print("==", t, flush=True)
        fetch(t)
