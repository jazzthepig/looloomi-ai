"""T-446 探针:① NAV 两条序列的对比 + cap_pit24 的日历完整性(判断 ⓪ 周日全平检查会不会被跳过)。只读。"""
import datetime as dt
import json
import os
import urllib.error
import urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
DATES = "2019-07-01,2023-01-03,2024-01-02,2026-01-02,2026-11-19"


def get(path):
    req = urllib.request.Request(
        U + "/rest/v1/" + path,
        headers={"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r), r.headers.get("Content-Range")
    except urllib.error.HTTPError as e:
        return {"err": e.read().decode()[:200]}, None


rows, rng = get("core_variants_daily?select=d&arm=eq.cap_pit24&d=gte.2020-02-01&d=lte.2026-11-19&order=d.asc&limit=3000")
print("cap_pit24 rows", len(rows) if isinstance(rows, list) else rows, rng)
if isinstance(rows, list) and rows:
    ds = [x["d"] for x in rows]
    d0, d1 = dt.date.fromisoformat(ds[0]), dt.date.fromisoformat(ds[-1])
    have = set(ds)
    miss, sund = [], []
    d = d0
    while d <= d1:
        if d.isoformat() not in have:
            miss.append(d.isoformat())
        if d.weekday() == 6:
            sund.append(d.isoformat())
        d += dt.timedelta(days=1)
    print("calendar_days", (d1 - d0).days + 1, "present", len(ds), "missing", len(miss), miss[:6])
    print("sundays", len(sund), "sundays_missing", [s for s in sund if s not in have][:5])
