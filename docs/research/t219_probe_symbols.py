"""T-219 step 1b: exhaustive symbol search for the 10 rail names + the 5 legacy rails."""
import os, json, urllib.request, urllib.parse

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
HDR = {"apikey": K, "Authorization": "Bearer " + K}


def get(path, params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(U + "/rest/v1/" + path + "?" + q, headers=HDR)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
LEG = ["V", "MA", "BLK", "IBKR", "SCHW", "QQQ", "SPY"]
WANT = set(RAIL + LEG)

# --- ohlcv_daily: all eodhd symbols ---
eod = get("ohlcv_daily", {"select": "symbol", "source": "eq.eodhd", "limit": 5000})
syms_eod = sorted(set(r["symbol"] for r in eod))
print("eodhd symbols count:", len(syms_eod))
print("eodhd symbols:", syms_eod)
print("rail/legacy present in ohlcv_daily(eodhd):", sorted(WANT & set(syms_eod)))

# --- ohlcv_daily: ALL distinct symbols (any source), to catch naming variants ---
allo = get("ohlcv_daily", {"select": "symbol", "limit": 20000})
syms_all = sorted(set(r["symbol"] for r in allo))
print("ohlcv_daily distinct symbols count:", len(syms_all))
hits = [s for s in syms_all if any(w.lower() in s.lower() for w in WANT)]
print("substring hits in ohlcv_daily:", hits)

# --- asset_mcap_daily: columns + symbols ---
cols = get("asset_mcap_daily", {"select": "*", "limit": 1})
print("asset_mcap_daily cols:", list(cols[0].keys()) if cols else "EMPTY")
am = get("asset_mcap_daily", {"select": "symbol", "limit": 5000})
syms_am = sorted(set(r["symbol"] for r in am))
print("asset_mcap_daily symbols:", syms_am)
