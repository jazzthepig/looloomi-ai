"""T-220 补交:查 state_daily 可结算 feature + ohlcv_daily 里 SPELL 的价格(只读,定点查询)。"""
import json
import os
import urllib.parse
import urllib.request

BASE = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def get(path, params):
    url = BASE + "/rest/v1/" + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


out = {}

# 1) state_daily:feature 清单 + panel 最近快照
rows = get("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                           "order": "d.desc,feature.asc", "limit": 200})
out["panel_latest_d"] = rows[0]["d"] if rows else None
out["panel_latest"] = {r["feature"]: r["value"] for r in rows if r["d"] == out["panel_latest_d"]}
out["n_state_features"] = len({r["feature"] for r in rows})

# 2) ohlcv_daily 列结构
one = get("ohlcv_daily", {"select": "*", "limit": 1})
out["ohlcv_cols"] = sorted(one[0].keys()) if one else []

# 3) SPELL(与 social_daily 对齐的 symbol):定点取收盘序列
for cand in ("SPELL", "spell-token"):
    h = get("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq." + cand,
                           "order": "trade_date.asc", "limit": 2000})
    if h:
        out["spell"] = {
            "symbol": cand, "n": len(h), "first": h[0], "last": h[-1],
            "around_open": [x for x in h if "2026-05-25" <= x["trade_date"] <= "2026-06-12"],
            "tail": h[-6:],
        }
        break
else:
    out["spell"] = None

# 4) 25 个 CIS 加密名字里哪些在 ohlcv_daily 有数据(抽样本看覆盖率)
samp = get("ohlcv_daily", {"select": "symbol", "order": "symbol.asc", "limit": 400})
out["symbol_sample"] = sorted({r["symbol"] for r in samp})[:60]

print(json.dumps(out, ensure_ascii=False, indent=1))
