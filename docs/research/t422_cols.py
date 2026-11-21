import json
import os
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY}
for t in ("asset_mcap_daily", "ohlcv_daily", "coin_supply_daily"):
    req = urllib.request.Request(URL + "/rest/v1/" + t + "?select=*&limit=1", headers=H)
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    if d:
        print(t, list(d[0].keys()))
        print("   sample:", {k: str(v)[:22] for k, v in list(d[0].items())[:9]})
    else:
        print(t, "EMPTY")
