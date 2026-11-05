#!/usr/bin/env python3
"""T-242 fetch v3 — symbol=in.(...) 分批 + 每批内 1000 行分页(PostgREST max-rows=1000)。"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t242/cache"
HDR = {"apikey": K, "Authorization": "Bearer " + K}

SELECT = {
    "v_funding_daily": "symbol,d,funding_rate",
    "deriv_metrics_daily": "symbol,d,oi_close,oi_value_close",
    "perp_bv_pairs": "symbol,kind,dead_from,first_d",
}
ORDER = {
    "v_funding_daily": "symbol.asc,d.asc",
    "deriv_metrics_daily": "symbol.asc,d.asc",
    "perp_bv_pairs": "symbol.asc",
}
PAGE = 1000
BATCH = 30


def all_syms():
    path = os.path.join(CACHE, "perp_bv_symbols.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    syms = set()
    with open("/Volumes/CometCloudAI/cometcloud-local/research/t238/_bars_pbv.jsonl") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if i == 0:
                continue
            for r in obj:
                syms.add(r["symbol"])
    syms = sorted(syms)
    with open(path, "w") as f:
        json.dump(syms, f)
    return syms


def fetch_table(table, syms):
    rows = []
    t0 = time.time()
    for i in range(0, len(syms), BATCH):
        chunk = syms[i:i + BATCH]
        off = 0
        while True:
            q = {"select": SELECT[table], "order": ORDER[table], "limit": str(PAGE),
                 "offset": str(off), "symbol": "in.(%s)" % ",".join(chunk)}
            url = U + "/rest/v1/" + table + "?" + urllib.parse.urlencode(q)
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=600) as r:
                page = json.loads(r.read().decode())
            if not page:
                break
            rows.extend(page)
            off += len(page)
            if len(page) < PAGE:
                break
        print("  %s %d/%d syms, %d rows (%.0fs)" % (table, min(i + BATCH, len(syms)), len(syms),
                                                   len(rows), time.time() - t0), flush=True)
    return rows


def main():
    syms = all_syms()
    for table in sys.argv[1:]:
        rows = fetch_table(table, syms)
        os.makedirs(CACHE, exist_ok=True)
        meta = {"fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "table": table, "n_rows": len(rows), "page": PAGE, "batch": BATCH,
                "query": "%s?select=%s&order=%s" % (table, SELECT[table], ORDER[table])}
        with open(os.path.join(CACHE, table + ".json"), "w") as f:
            json.dump({"meta": meta, "rows": rows}, f)
        print("DONE", table, len(rows), flush=True)


if __name__ == "__main__":
    main()
