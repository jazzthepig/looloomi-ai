"""T-219: exact contents of ohlcv_daily / world50_mcap_weekly / asset_mcap_daily."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t219_db import DB

db = DB()

# --- ohlcv_daily: full symbol list with row counts + date span ---
rows = db.all("ohlcv_daily", select="symbol,trade_date,source", order="symbol.asc,trade_date.asc", limit=1000)
by = {}
for r in rows:
    s = r["symbol"]
    b = by.setdefault(s, {"n": 0, "first": r["trade_date"], "last": r["trade_date"], "src": set()})
    b["n"] += 1
    b["last"] = r["trade_date"]
    b["src"].add(r["source"])
print("ohlcv_daily total rows:", len(rows), " distinct symbols:", len(by))
for s in sorted(by):
    b = by[s]
    print("   ", s, "n=", b["n"], b["first"], "->", b["last"], sorted(b["src"]))

# --- world50_mcap_weekly ---
w = db.all("world50_mcap_weekly", order="symbol.asc,week.asc", limit=1000)
print("\nworld50_mcap_weekly rows:", len(w))
if w:
    print("cols:", list(w[0].keys()))
    byw = {}
    for r in w:
        k = r.get("symbol")
        b = byw.setdefault(k, {"n": 0, "w": []})
        b["n"] += 1
        b["w"].append(r.get("week") or r.get("d") or r.get("date"))
    for s in sorted(byw):
        ws = sorted([x for x in byw[s]["w"] if x])
        print("   ", s, "n=", byw[s]["n"], (ws[0] if ws else ""), "->", (ws[-1] if ws else ""))
    print("sample row:", json.dumps(w[0], ensure_ascii=False)[:400])

# --- asset_mcap_daily ---
am = db.all("asset_mcap_daily", select="symbol,d,price,mcap,source", order="symbol.asc,d.asc", limit=1000)
print("\nasset_mcap_daily rows:", len(am), "symbols:", sorted(set(r["symbol"] for r in am))[:40])
