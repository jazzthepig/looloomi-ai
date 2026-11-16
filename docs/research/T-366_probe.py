"""T-366 探针(v3,2026-11-17):state_daily 的 feature 清单(给情景文件挑可自动结算的变量)+ 四个第一轮 §7 feature 的归属 + 现价。

只读。输出用来定:① 情景文件能引用哪些 state: 变量;② §7 降级是否有硬证据(entity='panel')。
"""
from __future__ import annotations

import json
import os
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def rows(table, qs):
    url = URL + "/rest/v1/" + table + "?" + qs
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
        return json.loads(r.read().decode())


print("=== ① state_daily 最近一天的全部 feature(去重) ===")
rs = rows("state_daily", "select=entity,feature,d,value&order=d.desc&limit=1000")
ds = sorted({r["d"] for r in rs}, reverse=True)
print("latest d:", ds[:3], "entities:", sorted({r["entity"] for r in rs}))
feats = sorted({r["feature"] for r in rs if r["d"] == ds[0]})
print("n_features_on_latest_d:", len(feats))
print(feats)

print("\n=== ② 第一轮 §7 引用的四个 feature:entity + 最近值 ===")
for f in ("breadth_above_ma50", "mom_20", "oi_chg_30d", "funding_7d_ann"):
    r2 = rows("state_daily", "select=entity,feature,d,value&feature=eq." + f + "&order=d.desc&limit=3")
    print(f, "->", r2)

print("\n=== ③ 现价(ohlcv_daily 收盘) ===")
for s in ("BTC", "ETH", "SOL"):
    r3 = rows("ohlcv_daily", "select=symbol,trade_date,close,source&symbol=eq." + s + "&order=trade_date.desc&limit=1")
    print(s, r3)

print("\n=== ④ asset_edge_moments 视图行数 ===")
cr, body = rows("asset_edge_moments", "select=symbol,edge_vol,edge_p10&limit=5"), None
print(cr)
