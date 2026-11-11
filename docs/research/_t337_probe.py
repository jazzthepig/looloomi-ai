"""T-337 探针:先查 macro_daily 的 btc_mvrv / btc_issuance_usd / fng 覆盖区间与行数(卡上的开工前置条件)。"""
import os
import sys
import json
import urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]


def q(path):
    h = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}
    r = urllib.request.Request(U + "/rest/v1/" + path, headers=h)
    with urllib.request.urlopen(r, timeout=120) as f:
        return f.headers.get("Content-Range"), json.loads(f.read().decode())


def count_series(s):
    """分页数全量行数,并核对首尾日期。"""
    lo = 0
    n = 0
    first = None
    last = None
    while True:
        _, rows = q("macro_daily?select=d&series=eq." + s + "&order=d.asc&limit=1000&offset=" + str(lo))
        if not rows:
            break
        if first is None:
            first = rows[0]["d"]
        last = rows[-1]["d"]
        n += len(rows)
        lo += len(rows)
        if len(rows) < 1000:
            break
    return n, first, last


for s in ["btc_mvrv", "btc_issuance_usd", "btc_hashrate", "fng"]:
    n, first, last = count_series(s)
    print(s, "| rows:", n, "| first:", first, "| last:", last)
    sys.stdout.flush()

# 全 series 清单(分页,只取 distinct)
seen = set()
lo = 0
while True:
    _, rows = q("macro_daily?select=series&order=series.asc,d.asc&limit=1000&offset=" + str(lo))
    if not rows:
        break
    for r in rows:
        seen.add(r["series"])
    lo += len(rows)
    if lo % 10000 == 0:
        print("... scanned", lo, flush=True)
    if len(rows) < 1000:
        break
print("all series:", sorted(seen))
print("total rows scanned:", lo)
