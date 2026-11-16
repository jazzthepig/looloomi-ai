"""T-366 探针:asset_flow_daily 分页边界到底长什么样(offset 是否生效 / order 是否生效)。"""
from __future__ import annotations

import json
import os
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def rows(qs):
    url = URL + "/rest/v1/asset_flow_daily?" + qs
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        return json.loads(r.read().decode())


for off in (0, 1000, 2000, 5000, 100000):
    rs = rows("select=symbol,d&order=symbol.asc&limit=1000&offset=" + str(off))
    if rs:
        print(off, "n=", len(rs), "first=", rs[0]["symbol"], rs[0]["d"], "last=", rs[-1]["symbol"], rs[-1]["d"])
    else:
        print(off, "empty")
rs = rows("select=symbol,d&order=symbol.asc&limit=5")
print("head:", rs)
