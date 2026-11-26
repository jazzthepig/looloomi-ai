"""T-444 / S-924:探 6 个市场特征键在不同时点是否存在 + joint 是否有重 d + funding_daily 的币与日期覆盖。"""
import json
import os
import urllib.parse
import urllib.request

BASE = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = os.environ["SUPABASE_KEY"]
WANT = ["dist_200", "style_rel_majors_30d", "stable_supply_30d", "funding_7d_ann_binance", "pos:btc_crowd_ln", "taker_buy_share_30d"]


def rows(path, params):
    q = urllib.parse.urlencode({**params, "limit": 1000})
    req = urllib.request.Request(BASE + path + "?" + q, headers={"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


for d in ("2021-01-04", "2022-06-01", "2023-06-01", "2024-06-03", "2025-06-02", "2026-06-01", "2026-11-20"):
    r = rows("feature_matrix_daily", {"select": "d,f", "d": "eq." + d, "order": "d.asc"})
    if not r:
        print(d, "NO ROW", flush=True)
        continue
    f = r[0]["f"] or {}
    miss = [w for w in WANT if w not in f]
    alt = [k for k in f if "major" in k or "supply" in k or "style" in k]
    print(d, "n_keys", len(f), "missing", miss, "alt", alt, flush=True)

print("== joint dup check", flush=True)
j = rows("joint_forecast_daily", {"select": "d,model,kind,z", "d": "gte.2026-11-01", "order": "d.asc", "limit": 1000})
seen = {}
for x in j:
    seen.setdefault(x["d"], []).append((x["model"], x["kind"], x["z"]))
dup = {d: v for d, v in seen.items() if len(v) > 1}
print("   n_days", len(seen), "dups", json.dumps(dup, ensure_ascii=False, default=str)[:400], flush=True)
print("   kinds", sorted({v[0][1] for v in seen.values()}), flush=True)
j0 = rows("joint_forecast_daily", {"select": "d", "order": "d.asc", "limit": 1000})
print("   first d", j0[0]["d"], "last(of first page)", j0[-1]["d"], "n", len(j0), flush=True)

print("== funding_daily coverage", flush=True)
for sym in ("BTC", "ETH", "SOL"):
    f = rows("funding_daily", {"select": "symbol,d,funding_rate", "symbol": "eq." + sym, "order": "d.asc", "limit": 1000})
    print("   ", sym, "n", len(f), "first", f[0]["d"] if f else None, "last", f[-1]["d"] if f else None, flush=True)
    if f:
        print("      first row", json.dumps(f[0], default=str), flush=True)
