#!/usr/bin/env python3
"""T-220 ②:sharpe_mindshare_snap / sharpe_narrative_mindshare 对 CIS 25 名的覆盖与事件数。"""
import json
import os
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))
CIS_CRYPTO = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE", "INJ",
              "LDO", "LINK", "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL", "STRK", "SUI",
              "TIA", "UNI", "XRP"]


def page(path, params, rng):
    url = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": "Bearer " + KEY,
                                              "Accept": "application/json", "Range": rng})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode() or "null")


def fetch_all(path, params, tag):
    fp = os.path.join(HERE, "_cache", tag + ".json")
    if os.path.exists(fp):
        return json.load(open(fp))
    out, off = [], 0
    while True:
        body = page(path, params, f"{off}-{off+999}")
        if not body:
            break
        out.extend(body)
        if len(body) < 1000:
            break
        off += 1000
    json.dump(out, open(fp, "w"))
    return out


def zseries(series, win=180, min_obs=60):
    out = {}
    vals = [v for _, v in series]
    for i in range(len(vals)):
        hist = vals[max(0, i - win):i]
        if len(hist) < min_obs:
            continue
        sd = statistics.pstdev(hist) if len(hist) > 1 else 0.0
        if sd <= 0:
            continue
        out[series[i][0]] = (vals[i] - sum(hist) / len(hist)) / sd
    return out


def episodes(z, thr=2.0):
    ev, prev = [], False
    for d in sorted(z):
        hot = z[d] > thr
        if hot and not prev:
            ev.append(d)
        prev = hot
    return ev


sym_in = "(" + ",".join(CIS_CRYPTO) + ")"
mind = fetch_all("sharpe_mindshare_snap",
                 {"select": "symbol,snap_d,mindshare_pct,social_score,watchlist_users,price",
                  "symbol": f"in.{sym_in}", "order": "symbol.asc,snap_d.asc"}, "mind25")
narr = fetch_all("sharpe_narrative_mindshare",
                 {"select": "narrative_id,snapshot_at,mindshare_pct,token_count,total_social_score,watchlist_users",
                  "order": "narrative_id.asc,snapshot_at.asc"}, "narr_all")

per = defaultdict(dict)
for r in mind:
    try:
        per[r["symbol"]][str(r["snap_d"])[:10]] = float(r["mindshare_pct"])
    except (TypeError, ValueError, KeyError):
        pass
print("=== sharpe_mindshare_snap(CIS 25)===")
tot_ev = 0
for s in CIS_CRYPTO:
    ser = sorted(per.get(s, {}).items())
    if not ser:
        print(f"{s:6s} 无数据", flush=True)
        continue
    z = zseries(ser, win=60, min_obs=20)
    ev = episodes(z)
    tot_ev += len(ev)
    print(f"{s:6s} n={len(ser):3d} {ser[0][0]}..{ser[-1][0]} ev_z>2={len(ev)} "
          f"max_z={round(max(z.values()),2) if z else None}", flush=True)
print("mindshare 事件合计:", tot_ev, flush=True)

nper = defaultdict(dict)
for r in narr:
    try:
        nper[r["narrative_id"]][str(r["snapshot_at"])[:10]] = float(r["mindshare_pct"])
    except (TypeError, ValueError, KeyError):
        pass
print("\n=== sharpe_narrative_mindshare ===")
print("narratives:", len(nper), flush=True)
nev = 0
narr_rows = []
for nid, d in sorted(nper.items()):
    ser = sorted(d.items())
    z = zseries(ser, win=90, min_obs=30)
    ev = episodes(z)
    nev += len(ev)
    narr_rows.append({"narrative_id": nid, "n": len(ser), "start": ser[0][0], "end": ser[-1][0],
                      "n_events": len(ev), "max_z": round(max(z.values()), 3) if z else None})
print(json.dumps(narr_rows, ensure_ascii=False)[:2500], flush=True)
print("narrative 事件合计:", nev, flush=True)
json.dump({"mind_per_symbol": {k: {"n": len(v), "start": min(v), "end": max(v)} for k, v in per.items()},
           "mind_events_total": tot_ev,
           "narratives": narr_rows, "narrative_events_total": nev,
           "n_narratives": len(nper)},
          open(os.path.join(HERE, "_c_mindshare.json"), "w"), ensure_ascii=False, indent=1)
print("saved _c_mindshare.json")
