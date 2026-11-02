#!/usr/bin/env python3
"""T-220:取 CIS 加密宇宙(cis_v2_daily grp 分组)+ social_daily 的 slug→symbol 映射。只读、分页带 order。"""
import json
import os
import urllib.parse
import urllib.request
import urllib.error
from collections import defaultdict

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))


def page(path, params, rng="0-999"):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json", "Range": rng})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def fetch_all(path, params, key_cols):
    out = []
    off = 0
    while True:
        st, body = page(path, params, f"{off}-{off+999}")
        if st != 200 or not isinstance(body, list) or not body:
            break
        out.extend(body)
        if len(body) < 1000:
            break
        off += 1000
    return out


# 1) cis_v2_daily → grp × symbol
rows = fetch_all("cis_v2_daily", {"select": "symbol,grp,d,score,signal", "order": "symbol.asc,d.asc"}, ("symbol", "d"))
grp = defaultdict(set)
dates = defaultdict(list)
for r in rows:
    grp[r.get("grp")].add(r["symbol"])
    dates[r.get("grp")].append(r["d"])
print("cis rows:", len(rows), "groups:", {k: len(v) for k, v in grp.items()}, flush=True)
for k in sorted(grp, key=lambda x: -len(grp[x])):
    print(f"  grp={k!r} n_sym={len(grp[k])} range={min(dates[k])}..{max(dates[k])}", flush=True)
    print("   ", sorted(grp[k])[:40], flush=True)

crypto_syms = sorted(grp.get("crypto", set()))
out = {"cis_groups": {k: sorted(v) for k, v in grp.items()},
       "cis_group_sizes": {k: len(v) for k, v in grp.items()},
       "crypto_symbols": crypto_syms}
json.dump(out, open(os.path.join(HERE, "_cis_universe.json"), "w"), ensure_ascii=False, indent=1)

# 2) social_daily slug→symbol 映射(只取 symbol,slug 列,全表去重)
sl = fetch_all("social_daily", {"select": "symbol,slug", "order": "symbol.asc,slug.asc"}, ("symbol", "slug"))
m = defaultdict(set)
for r in sl:
    m[r["symbol"]].add(r["slug"])
print("social_daily rows:", len(sl), "symbols:", len(m), flush=True)
json.dump({k: sorted(v) for k, v in m.items()},
          open(os.path.join(HERE, "_social_slug_map.json"), "w"), ensure_ascii=False, indent=1)
print("saved")
