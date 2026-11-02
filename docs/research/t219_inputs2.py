"""T-219 step 2b: core_cap arm spans, stable_supply_30d coverage, extra nav table names."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t219_db import DB

db = DB()

print("core_cap_daily total rows:", db.count("core_cap_daily"))
for arm in ["cap_a1", "cap_a1_u", "cap_a05", "ew_a0"]:
    rows = db.all("core_cap_daily", select="d,arm,nav", order="d.asc",
                  filters={"arm": "eq." + arm}, limit=1000, max_rows=100000)
    if rows:
        print("  %-9s n=%3d  %s -> %s" % (arm, len(rows), rows[0]["d"], rows[-1]["d"]))

print("\nstate_daily stable_supply_30d:")
rows = db.all("state_daily", select="d,entity,feature,value,source", order="d.asc",
              filters={"feature": "eq.stable_supply_30d"}, limit=1000, max_rows=100000)
print("  n=", len(rows))
if rows:
    print("  ", rows[0]["d"], "->", rows[-1]["d"], "entities:", sorted(set(r["entity"] for r in rows)))
    print("  sample:", json.dumps(rows[0])[:250], json.dumps(rows[-1])[:250])

print("\nother candidate nav/price tables:")
for t in ["core_nav_daily", "nav_daily", "core_daily", "core_weights_daily", "cap_nav_daily",
          "paper_nav_daily", "core_cap_weekly", "core_cap_monthly", "bench_daily",
          "macro_daily", "stable_supply_daily", "usd_supply_daily", "stablecoin_daily",
          "price_weekly", "world50_price_weekly", "cis_official_daily", "deriv_metrics_daily"]:
    ok, cr = db.exists(t)
    if ok:
        n = db.count(t)
        print("  OK  ", t, n)
