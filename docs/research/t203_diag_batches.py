#!/usr/bin/env python3
"""T-203 诊断:重建批次里 funding 到底有没有、哪个批次有、时间戳与卡片 12:00 UTC 门槛的关系。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}


def get(table, params, page=1000):
    rows, off = [], 0
    while True:
        p = dict(params)
        p["limit"] = page
        p["offset"] = off
        ps = "&".join("%s=%s" % (k, urllib.parse.quote(str(v), safe="(),.*:|+-=<>")) for k, v in p.items())
        req = urllib.request.Request(URL + "/rest/v1/" + table + "?" + ps, headers=HDR)
        last = None
        for i in range(5):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    last = json.loads(r.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and i < 4:
                    continue
                raise
        rows.extend(last)
        if len(last) < page:
            break
        off += page
    return rows


print("== A. 抽样:inputs 里到底有没有 funding 键(三种取法对比) ==")
s1 = get("cis_rebuild_daily", {"select": "symbol,d,computed_at,inputs", "code_ref": "eq.cis-standard-v1.3",
                                "order": "symbol.asc,d.asc", "limit": 3})
for r in s1:
    inp = r.get("inputs") or {}
    print("  %s %s computed_at=%s inputs_keys=%s" %
          (r["symbol"], r["d"][:10], (r.get("computed_at") or "")[:19], sorted(inp.keys())[:40]))

print("\n== B. 全量:computed_at 批次 × funding 是否为 null ==")
rb = get("cis_rebuild_daily", {"select": "symbol,d,computed_at,inputs", "code_ref": "eq.cis-standard-v1.3",
                                "order": "symbol.asc,d.asc"})
batches = defaultdict(lambda: {"rows": 0, "fr_present": 0, "fr_null": 0, "dmin": None, "dmax": None,
                               "fr_min": None, "fr_max": None, "fr_nonzero": 0})
for r in rb:
    b = (r.get("computed_at") or "")[:19]
    e = batches[b]
    e["rows"] += 1
    d = r["d"][:10]
    e["dmin"] = d if e["dmin"] is None or d < e["dmin"] else e["dmin"]
    e["dmax"] = d if e["dmax"] is None or d > e["dmax"] else e["dmax"]
    fr = (r.get("inputs") or {}).get("funding")
    if fr is None:
        e["fr_null"] += 1
    else:
        e["fr_present"] += 1
        f = float(fr)
        e["fr_min"] = f if e["fr_min"] is None or f < e["fr_min"] else e["fr_min"]
        e["fr_max"] = f if e["fr_max"] is None or f > e["fr_max"] else e["fr_max"]
        if f != 0:
            e["fr_nonzero"] += 1
for b in sorted(batches):
    e = batches[b]
    print("  %s rows=%-7d d %s..%s fr_present=%-7d fr_null=%-7d fr_nonzero=%-7d fr[%.6f..%.6f]" %
          (b, e["rows"], e["dmin"], e["dmax"], e["fr_present"], e["fr_null"], e["fr_nonzero"],
           e["fr_min"] or 0.0, e["fr_max"] or 0.0))

print("\n== C. 缓存里的批次(主脚本实际用的) ==")
cache_dir = "/Volumes/CometCloudAI/cometcloud-local/research/t203"
for root, _dirs, files in os.walk(cache_dir):
    for fn in sorted(files):
        if not fn.startswith("rb_v13") or not fn.endswith(".json"):
            continue
        p = os.path.join(root, fn)
        try:
            rows = json.load(open(p))
        except Exception as ex:
            print("  %s: 读不了 %s" % (p, ex))
            continue
        ts = defaultdict(int)
        frmiss = 0
        for r in rows:
            ts[(r.get("computed_at") or "")[:19]] += 1
            if (r.get("inputs") or {}).get("funding") is None:
                frmiss += 1
        print("  %s rows=%d 批次=%s funding_missing=%d" %
              (p, len(rows), dict(sorted(ts.items())), frmiss))

print("\n== D. 现在几点(UTC) ==")
import datetime
print("  ", datetime.datetime.now(datetime.timezone.utc).isoformat())
