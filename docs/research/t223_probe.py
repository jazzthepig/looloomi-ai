"""T-223 probe #3: candidate tables (FDV/supply), state_daily entities, revenue holders, cache meta.

Edit this same file across rounds; do not create probe2/probe3/...
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HEAD = {"apikey": KEY, "Authorization": "Bearer " + KEY}
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t209_cache"


def _http(path, params=None, rng=None, timeout=300, csv=False):
    q = urllib.parse.urlencode(params or {}, doseq=True, safe="(),.*:<>=")
    url = f"{URL}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers=HEAD)
    if rng:
        req.add_header("Range", rng)
    req.add_header("Accept", "text/csv" if csv else "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read().decode()
    return b if csv else (json.loads(b) if b else None)


def try_table(t):
    try:
        req = urllib.request.Request(f"{URL}/rest/v1/{t}?select=*&limit=1",
                                     headers={**HEAD, "Prefer": "count=exact"})
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode()
            cr = r.headers.get("Content-Range", "")
        rows = json.loads(body) if body else []
        cols = sorted(rows[0].keys()) if rows else []
        return {"rows": cr.split("/")[-1], "cols": cols}
    except urllib.error.HTTPError as e:
        return {"err": f"{e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"err": type(e).__name__}


def main():
    print("== candidate tables ==")
    for t in ["cg_coins", "coin_supply", "cg_supply", "token_supply", "supply_daily",
              "fdv_daily", "circulating_supply", "coin_unlocks", "unlock_calendar",
              "stablecoin_daily", "stablecoin_mcap", "exchange_flows_daily", "exchange_netflow",
              "flows_daily", "netflow_daily", "onchain_daily", "registry_coins", "coin_registry"]:
        print(f"  {t}: {try_table(t)}")

    print("== state_daily entities ==")
    rows = _http("/rest/v1/state_daily", [("select", "entity,feature,d,value"),
                                          ("entity", "eq.panel"), ("feature", "eq.stable_supply_30d"),
                                          ("order", "d.asc"), ("limit", "1000")])
    if rows:
        print("  stable_supply_30d rows(sample):", len(rows), "first", rows[0], "last", rows[-1])
    else:
        print("  no stable_supply_30d rows for entity=panel")

    print("== protocol_revenue_daily holders non-zero ==")
    try:
        req = urllib.request.Request(
            f"{URL}/rest/v1/protocol_revenue_daily?select=holders_24h,holders_30d&limit=5000",
            headers={**HEAD, "Prefer": "count=exact"})
        with urllib.request.urlopen(req, timeout=300) as r:
            body = json.loads(r.read().decode())
        nz = sum(1 for b in body if (b.get("holders_24h") or 0) > 0 or (b.get("holders_30d") or 0) > 0)
        print(f"  sampled {len(body)} rows, holders>0 rows = {nz}")
    except Exception as e:  # noqa: BLE001
        print("  failed:", e)

    print("== t209 cache meta ==")
    for f in sorted(os.listdir(CACHE)):
        if f.endswith(".meta.json"):
            m = json.load(open(os.path.join(CACHE, f)))
            print(" ", f, json.dumps(m.get("want", {}), ensure_ascii=False)[:400], "rows=", m.get("rows"))


if __name__ == "__main__":
    main()
