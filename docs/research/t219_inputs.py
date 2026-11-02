"""T-219 step 2: inputs for the legacy-rail baseline — BTC series, core_cap arms, stable supply feature."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t219_db import DB

db = DB()

print("== ohlcv_daily BTC ==")
for s in ["BTC", "BTCUSDT", "BTC-USDT"]:
    n = db.count("ohlcv_daily", {"symbol": "eq." + s})
    print("  ", s, n)
rows = db.all("ohlcv_daily", select="symbol,trade_date,source,close",
              order="trade_date.asc", filters={"symbol": "eq.BTC"}, limit=1000, max_rows=100000)
if rows:
    srcs = sorted(set(r["source"] for r in rows))
    print("  BTC rows:", len(rows), rows[0]["trade_date"], "->", rows[-1]["trade_date"], srcs)

print("\n== core_cap_daily arms ==")
arms = db.all("core_cap_daily", select="arm", order="arm.asc", limit=1000, max_rows=200000)
from collections import Counter
print("  ", Counter(r["arm"] for r in arms))
cc = db.all("core_cap_daily", select="d,arm,nav,ret", order="d.asc,arm.asc",
            filters={"arm": "eq.cap_a1"}, limit=1000, max_rows=100000)
if cc:
    print("  cap_a1 rows:", len(cc), cc[0]["d"], "->", cc[-1]["d"])
    print("  sample:", json.dumps(cc[0])[:200], json.dumps(cc[-1])[:200])

print("\n== state_daily features with 'stable' ==")
feats = db.all("state_daily", select="feature", order="feature.asc", limit=1000, max_rows=100000)
fs = sorted(set(r["feature"] for r in feats))
print("  n features:", len(fs))
for f in fs:
    if "stable" in f.lower() or "supply" in f.lower():
        print("   *", f)
