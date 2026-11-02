"""T-219 step 1c: actual row counts + samples for the research tables we need."""
import os, json, urllib.request, urllib.parse

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
HDR = {"apikey": K, "Authorization": "Bearer " + K}


def get(path, params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(U + "/rest/v1/" + path + "?" + q, headers=HDR)
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode()
        cr = r.headers.get("Content-Range")
        return json.loads(body), cr


SPEC = [
    ("ohlcv_daily", "symbol,trade_date,source,close", "symbol.asc,trade_date.asc"),
    ("asset_mcap_daily", "symbol,d,price,mcap,source", "symbol.asc,d.asc"),
    ("core_cap_daily", "*", None),
    ("state_daily", "*", None),
    ("macro_daily", "*", None),
]
for tbl, sel, order in SPEC:
    p = {"select": sel, "limit": 3}
    if order:
        p["order"] = order
    try:
        rows, cr = get(tbl, p)
        print("=== ", tbl, "| content-range:", cr)
        for r in rows[:3]:
            print("   ", json.dumps(r, ensure_ascii=False)[:500])
    except Exception as e:
        print("=== ", tbl, "ERROR", str(e)[:200])
