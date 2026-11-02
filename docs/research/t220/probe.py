#!/usr/bin/env python3
"""T-220 只读体检:探 lane 只读 key 能读哪些表 + 表结构(不打印 key)。"""
import json
import os
import urllib.parse
import urllib.request
import urllib.error

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
TABLES = [
    "social_daily", "sharpe_mindshare_snap", "sharpe_narrative_mindshare",
    "trending_log", "cis_v2_daily", "ohlcv_daily", "asset_mcap_daily",
    "deriv_metrics_daily", "state_daily", "macro_daily",
]


def get(path, params):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)[:400]


out = {}
for t in TABLES:
    st, body = get(t, {"select": "*", "limit": 1})
    if st == 200 and isinstance(body, list):
        cols = sorted(body[0].keys()) if body else []
        out[t] = {"status": st, "n_returned": len(body), "cols": cols}
    else:
        out[t] = {"status": st, "err": str(body)[:300]}
    print(t, json.dumps(out[t], ensure_ascii=False)[:600], flush=True)

json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_tables.json"), "w"),
          ensure_ascii=False, indent=1)
