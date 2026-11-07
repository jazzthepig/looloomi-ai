"""T-294 pull — pull v2 — asset_flow_daily (Mondays only) + perp_bv_daily (USDT, universe symbols).

Discipline: every query carries an explicit `order=`; pages use the Range header (≤1000 rows);
perp is sharded by symbol so page boundaries cannot drift across shards.
"""
import json
import os
import time
import urllib.request
from collections import Counter
from datetime import date, timedelta

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
           ".t294_cache")
PAGE = 1000
t0 = time.time()


def req(path, rng=None, tries=5):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if rng:
        h["Range"] = rng
    last = None
    for a in range(tries):
        try:
            r = urllib.request.Request(URL + "/rest/v1/" + path, headers=h)
            with urllib.request.urlopen(r, timeout=300) as resp:
                return resp.read().decode(), dict(resp.headers)
        except Exception as e:
            last = e
            time.sleep(1.5 * (a + 1))
    raise RuntimeError("GET failed: %s: %s" % (path[:80], last))


def page_all(path, tag=""):
    rows, start = [], 0
    while True:
        body, hdrs = req(path, rng="%d-%d" % (start, start + PAGE - 1))
        got = json.loads(body) if body else []
        if not got:
            break
        rows.extend(got)
        start += len(got)
        if len(got) < PAGE:
            break
        if start % 20000 == 0:
            print("    %s %d rows  %.0fs" % (tag, len(rows), time.time() - t0), flush=True)
    return rows


# ── Mondays ────────────────────────────────────────────────────────────────
d0, d1 = date(2022, 6, 1), date(2026, 11, 6)
mondays, c = [], d0
while c <= d1:
    if c.weekday() == 0:
        mondays.append(c.isoformat())
    c += timedelta(days=1)
print("[1] mondays: %d  (%s .. %s)" % (len(mondays), mondays[0], mondays[-1]), flush=True)

# ── 2. asset_flow_daily on Mondays ─────────────────────────────────────────
COLS = "symbol,d,n_cs,doi7,taker7,turn,mom7,q_doi7,q_taker7,q_turn,q_mom7,x7,x30,vec"
inq = ",".join(mondays)
af = page_all("asset_flow_daily?select=%s&d=in.(%s)&order=d.asc,symbol.asc" % (COLS, inq), tag="af")
with open(OUT + "/asset_flow.jsonl", "w") as f:
    for r in af:
        f.write(json.dumps(r) + "\n")
syms = sorted({r["symbol"] for r in af})
print("[2] asset_flow rows=%d symbols=%d  %.0fs" % (len(af), len(syms), time.time() - t0), flush=True)

# ── 3. perp_bv_daily for those symbols (USDT) ──────────────────────────────
perp = []
SH = 40
for i in range(0, len(syms), SH):
    chunk = syms[i:i + SH]
    filt = "symbol=in.(" + ",".join(chunk) + ")&pair=like.*USDT&d=gte.2022-10-01"
    rows = page_all("perp_bv_daily?select=symbol,pair,d,o,c,qv,recorded_at&%s&order=symbol.asc,d.asc" % filt,
                    tag="perp")
    perp.extend(rows)
    print("    shard %d/%d rows=%d total=%d %.0fs" % (i // SH + 1, (len(syms) + SH - 1) // SH,
                                                     len(rows), len(perp), time.time() - t0), flush=True)
with open(OUT + "/perp_bv.jsonl", "w") as f:
    for r in perp:
        f.write(json.dumps(r) + "\n")

# ── 4. summary ─────────────────────────────────────────────────────────────
afk = Counter((r["symbol"], r["d"]) for r in af)
pk = Counter((r["symbol"], r["d"]) for r in perp)
dates = sorted({r["d"] for r in af})
per_dates = sorted({r["d"] for r in perp})
nulls = {c2: sum(1 for r in af if r.get(c2) is None) for c2 in
         ("q_doi7", "q_taker7", "q_turn", "q_mom7", "x7", "x30", "vec")}
summary = {
    "asset_flow_rows": len(af), "asset_flow_symbols": len(syms),
    "asset_flow_dates": len(dates), "asset_flow_date_min": dates[0], "asset_flow_date_max": dates[-1],
    "asset_flow_dup_keys": sum(1 for v in afk.values() if v > 1),
    "asset_flow_nulls": nulls,
    "asset_flow_rows_with_vec": sum(1 for r in af if r.get("vec")),
    "perp_rows": len(perp), "perp_symbols": len({r["symbol"] for r in perp}),
    "perp_dates": len(per_dates), "perp_date_min": per_dates[0], "perp_date_max": per_dates[-1],
    "perp_dup_keys": sum(1 for v in pk.values() if v > 1),
    "elapsed_s": round(time.time() - t0, 1),
}
with open(OUT + "/pull_summary.json", "w") as f:
    json.dump(summary, f, indent=1)
print(json.dumps(summary, indent=1), flush=True)
print("DONE", flush=True)
