"""T-219 step 2 (2026-11-02 ~09:2x UTC): re-check the data gate after the EODHD weekly
landing window opened, and hunt for a longer NAV history for the core (beta sleeve 1).

Read-only. No keys printed.
"""
import os, json, urllib.request

U = os.environ["SUPABASE_URL"]
K = os.environ["SUPABASE_KEY"]
HDR = {"apikey": K, "Authorization": "Bearer " + K}


def get(path, params=None, extra=None):
    h = dict(HDR)
    if extra:
        h.update(extra)
    q = ""
    if params:
        q = "?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
    req = urllib.request.Request(U + "/rest/v1/" + path + q, headers=h)
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode()
        cr = r.headers.get("Content-Range")
    return (json.loads(body) if body else []), cr


RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]

# ---- A. rail gate re-check -------------------------------------------------
print("=== A. ohlcv_daily per source for the 10 rail tickers ===")
for s in RAIL:
    rows, _ = get("ohlcv_daily", {"select": "trade_date,source,close", "symbol": "eq." + s,
                                 "order": "trade_date.asc", "limit": 2000})
    if not rows:
        print("  %-5s NO ROWS" % s)
        continue
    bysrc = {}
    for r in rows:
        bysrc.setdefault(r.get("source"), []).append(r)
    parts = []
    for src, rs in sorted(bysrc.items()):
        parts.append("%s:%d(%s..%s)" % (src, len(rs), rs[0]["trade_date"], rs[-1]["trade_date"]))
    print("  %-5s %s" % (s, " | ".join(parts)))

print("\n=== A2. asset_mcap_daily / world50_mcap_weekly ===")
probe, _ = get("asset_mcap_daily", {"select": "*", "limit": 1})
print("  asset_mcap_daily cols:", list(probe[0].keys()) if probe else None)
probe2, _ = get("world50_mcap_weekly", {"select": "*", "limit": 1})
print("  world50_mcap_weekly cols:", list(probe2[0].keys()) if probe2 else None)
for s in RAIL:
    a, _ = get("asset_mcap_daily", {"select": "symbol", "symbol": "eq." + s,
                                    "order": "symbol.asc", "limit": 2000})
    b, _ = get("world50_mcap_weekly", {"select": "key", "key": "eq." + s,
                                       "order": "key.asc", "limit": 2000})
    print("  %-5s asset_mcap_daily=%d world50_mcap_weekly=%d" % (s, len(a), len(b)))

# ---- B. hunt a longer NAV history for the core -----------------------------
print("\n=== B. readable tables matching nav/core/cap/beta ===")
req = urllib.request.Request(U + "/rest/v1/", headers=dict(HDR, Accept="application/openapi+json"))
with urllib.request.urlopen(req, timeout=60) as r:
    spec = json.loads(r.read().decode())
tables = sorted(set(p[1:] for p in spec.get("paths", {}) if p.startswith("/")))
print("  total readable tables:", len(tables))
for t in tables:
    tl = t.lower()
    if any(k in tl for k in ("nav", "core", "cap", "beta", "weight", "alloc", "portfolio")):
        try:
            rows, cr = get(t, {"select": "*", "limit": 1}, extra={"Prefer": "count=exact"})
            n = cr.split("/")[-1] if cr and "/" in cr else "?"
        except Exception as e:
            n = "ERR %s" % e
        cols = list(rows[0].keys()) if rows else []
        print("   %-42s rows=%s cols=%s" % (t, n, cols[:12]))
