"""T-219 step 1e: world50_mcap_weekly coverage for rail + legacy rail keys."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t219_db import DB

db = DB()
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
LEG = ["V", "MA", "BLK", "IBKR", "SCHW", "QQQ", "SPY"]

print("key      rows   first_d     last_d      shares_non_null  src")
for k in RAIL + LEG:
    n = db.count("world50_mcap_weekly", {"key": "eq." + k})
    if n == 0:
        print("%-8s %5d  --" % (k, n))
        continue
    rows = db.all("world50_mcap_weekly", select="key,d,mcap_usd,source,shares",
                  order="d.asc", filters={"key": "eq." + k}, limit=1000, max_rows=100000)
    sh = sum(1 for r in rows if r.get("shares") is not None)
    srcs = sorted(set(r.get("source") for r in rows))
    print("%-8s %5d  %s  %s  %d  %s" % (k, len(rows), rows[0]["d"], rows[-1]["d"], sh, srcs))
