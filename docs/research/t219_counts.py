"""T-219 step 1d: cheap targeted counts (no full-table reads)."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t219_db import DB

db = DB()
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
LEG = ["V", "MA", "BLK", "IBKR", "SCHW", "QQQ", "SPY", "000660.KO"]

print("ohlcv_daily total:", db.count("ohlcv_daily"))
for s in ["eodhd", "yfinance", "binance_hist"]:
    print("  ohlcv_daily source=%s ->" % s, db.count("ohlcv_daily", {"source": "eq." + s}))
for s in RAIL + LEG:
    n = db.count("ohlcv_daily", {"symbol": "eq." + s})
    print("  ohlcv_daily symbol=%s -> %s" % (s, n))

print("\nworld50_mcap_weekly total:", db.count("world50_mcap_weekly"))
r, cr = db.get("world50_mcap_weekly", {"select": "*", "limit": 3})
print("cols:", list(r[0].keys()) if r else None)
for x in r:
    print("  ", json.dumps(x, ensure_ascii=False)[:300])

print("\nasset_mcap_daily total:", db.count("asset_mcap_daily"))
for s in RAIL + ["EGLD", "BTC"]:
    print("  asset_mcap_daily symbol=%s -> %s" % (s, db.count("asset_mcap_daily", {"symbol": "eq." + s})))
