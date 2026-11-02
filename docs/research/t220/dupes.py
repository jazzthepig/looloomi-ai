#!/usr/bin/env python3
"""T-220 ②:查 social_daily 的重复行结构(每个 (symbol,d) 有几行、值是否相同)。"""
import json
import os
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))


def page(path, params, rng):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer " + KEY,
                                              "Accept": "application/json", "Range": rng})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode() or "null")


rows = json.load(open(os.path.join(HERE, "_cache", "social25.json")))
per = defaultdict(list)
for r in rows:
    per[(r["symbol"], str(r["d"])[:10])].append(r)
mult = Counter(len(v) for v in per.values())
print("(symbol,d) 行数分布:", dict(mult), flush=True)
same = sum(1 for v in per.values() if len({x["value"] for x in v}) == 1)
print("其中所有行 value 相同的 (symbol,d):", same, "/", len(per), flush=True)

# 看一个具体的重复样本,带 fetched_at
st = page("social_daily", {"select": "symbol,d,value,metric,source,fetched_at",
                           "symbol": "eq.AAVE", "order": "d.asc", "limit": 12}, "0-11")
for r in st:
    print(r, flush=True)

# 全表 fetched_at 的分布(前若干条,按 fetched_at 排序看是否有两批)
st2 = page("social_daily", {"select": "symbol,d,value,fetched_at", "symbol": "eq.BTC",
                            "order": "fetched_at.asc,d.asc", "limit": 8}, "0-7")
for r in st2:
    print(r, flush=True)
