"""T-335 探针 v6:探 ohlcv_daily 的列名与 BTC 最新收盘。只读。"""
import json
import os
import urllib.parse
import urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact"}


def q(table, params, limit=1000):
    p = dict(params)
    p["limit"] = str(limit)
    url = f"{U}/rest/v1/{table}?" + urllib.parse.urlencode(p)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"ERR": f"{e.code} {e.read()[:200].decode(errors='replace')}"}


print("A select=* limit=1:", json.dumps(q("ohlcv_daily", {"select": "*"}, 1), ensure_ascii=False)[:700])
for col in ("d", "date", "trade_date"):
    r = q("ohlcv_daily", {"select": f"{col},symbol,close", "symbol": "eq.BTC", "order": f"{col}.desc"}, 2)
    print(f"B {col}:", json.dumps(r, ensure_ascii=False)[:400])
