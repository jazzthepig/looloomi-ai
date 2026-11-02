"""T-219 step 1: which rail-company symbols already have daily lines in ohlcv_daily?"""
import os, json, urllib.request, urllib.parse

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
HDR = {"apikey": K, "Authorization": "Bearer " + K}


def get(path, params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(U + "/rest/v1/" + path + "?" + q, headers=HDR)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


SYMS = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]

src = get("ohlcv_daily", {"select": "source", "source": "not.is.null", "limit": 1000})
print("distinct sources:", sorted(set(r["source"] for r in src)))

for s in SYMS:
    rows = get("ohlcv_daily", {"select": "trade_date,source", "symbol": "eq." + s,
                               "order": "trade_date.asc", "limit": 1000})
    if not rows:
        print(s, "NO ROWS")
        continue
    srcs = sorted(set(r["source"] for r in rows))
    print(s, "n=", len(rows), "first=", rows[0]["trade_date"], "last=", rows[-1]["trade_date"], "src=", srcs)
