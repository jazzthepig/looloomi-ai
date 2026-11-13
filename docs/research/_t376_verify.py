import json, time, urllib.request
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0.0.0 Safari/537.36"}


def get(u):
    r = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(r, timeout=40) as resp:
        return json.loads(resp.read().decode())


out = {}

# --- CMC chart: point spacing structure + supply series ---
for name, cid in (("BTC", 1), ("ETH", 1027), ("SOL", 5426)):
    j = get(f"https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id={cid}&range=all")
    pts = j["data"]["points"]
    ks = sorted(int(k) for k in pts)
    gaps = [round((ks[i + 1] - ks[i]) / 86400, 2) for i in range(len(ks) - 1)]
    from collections import Counter
    cnt = Counter(gaps).most_common(8)
    out[f"cmc_{name}"] = {
        "n_points": len(ks),
        "first": time.strftime("%Y-%m-%d", time.gmtime(ks[0])),
        "last": time.strftime("%Y-%m-%d", time.gmtime(ks[-1])),
        "supply_first": pts[str(ks[0])]["v"][4],
        "supply_last": pts[str(ks[-1])]["v"][4],
        "gap_hist_top": cnt,
        "gap_min": min(gaps), "gap_max": max(gaps),
        "gaps_last30": gaps[-30:],
        "tail_dates": [time.strftime("%Y-%m-%d", time.gmtime(k)) for k in ks[-6:]],
    }

# --- blockchain.com: daily BTC supply, x in SECONDS ---
bc = get("https://api.blockchain.info/charts/total-bitcoins?timespan=all&format=json")
vals = bc["values"]
bmap = {time.strftime("%Y-%m-%d", time.gmtime(v["x"])): v["y"] for v in vals}
bdays = sorted(bmap)
out["blockchain"] = {
    "name": bc.get("name"), "unit": bc.get("unit"), "period": bc.get("period"),
    "n_points": len(vals), "first": bdays[0], "last": bdays[-1],
    "gap_median_days": round((vals[-1]["x"] - vals[0]["x"]) / 86400 / (len(vals) - 1), 3),
    "supply_first": bmap[bdays[0]], "supply_last": bmap[bdays[-1]],
}

# --- cross-check CMC v[4] vs blockchain.com on matched dates ---
cmc = get("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id=1&range=all")
cpts = {time.strftime("%Y-%m-%d", time.gmtime(int(k))): v["v"][4] for k, v in cmc["data"]["points"].items()}
pairs = []
for d in sorted(bmap):
    if d in cpts:
        pairs.append((d, round(float(cpts[d]), 1), round(float(bmap[d]), 1)))
out["cmc_vs_bc_matched"] = {"n_matched": len(pairs), "head": pairs[:3], "tail": pairs[-3:],
                            "max_abs_rel_diff_pct": round(max(abs(a - b) / b * 100 for _, a, b in pairs), 4) if pairs else None}

# --- current supply cross-check via CMC detail (does v[4] match circulatingSupply today?) ---
det = get("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail?id=1")
d = det.get("data", {})
out["cmc_detail_btc"] = {k: d.get(k) for k in ("name", "symbol", "circulatingSupply", "totalSupply", "maxSupply")}

print(json.dumps(out, indent=1)[:3000])
json.dump(out, open("docs/research/T-376_supply_verify.json", "w"), indent=1)
