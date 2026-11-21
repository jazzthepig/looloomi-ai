"""T-422 探针 5:macro_daily 全系列 + coin_supply_daily 的批次日(带 order 与翻页)。"""
import json, os
import urllib.parse, urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t422"


def get_all(table, params):
    """带 order 的整读:limit 1000 一页,翻到取完。"""
    rows, off = [], 0
    while True:
        q = dict(params)
        q.update({"limit": "1000", "offset": str(off)})
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in q.items())
        req = urllib.request.Request(f"{URL}/rest/v1/{table}?{qs}", headers={
            "apikey": KEY, "Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode()
        batch = json.loads(body) if body.strip() else []
        rows.extend(batch)
        off += len(batch)
        if len(batch) < 1000:
            return rows


out = {}
m = get_all("macro_daily", {"select": "series,d,value", "order": "series.asc,d.asc"})
out["macro_n_rows"] = len(m)
ser = {}
for r in m:
    ser.setdefault(r["series"], []).append(r)
out["macro_series"] = {k: {"n": len(v), "max_d": max(x["d"] for x in v),
                            "min_d": min(x["d"] for x in v)} for k, v in sorted(ser.items())}
for s in ("total_mcap", "btc_dominance", "fng", "vix"):
    if s in ser:
        v = sorted(ser[s], key=lambda x: x["d"])
        out[f"macro_{s}_tail"] = [{"d": x["d"], "value": x["value"], "source": x.get("source")} for x in v[-4:]]

s = get_all("coin_supply_daily", {"select": "coin_id,d,circulating_supply,total_supply,fetched_at",
                                   "order": "d.asc,coin_id.asc"})
out["supply_rows"] = len(s)
batches = {}
for r in s:
    batches.setdefault(r["d"], []).append(r)
out["supply_batches"] = {d: {"n": len(v), "max_fetched": max((x.get("fetched_at") or "") for x in v),
                              "n_missing_tot": sum(1 for x in v if x.get("total_supply") is None)}
                          for d, v in sorted(batches.items())}
out["supply_batch_ids_1120"] = sorted(x["coin_id"] for x in batches.get("2026-11-20", []))
out["supply_batch_ids_1119"] = sorted(x["coin_id"] for x in batches.get("2026-11-19", []))

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "probe5.json"), "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, default=str)
print(json.dumps({k: v for k, v in out.items() if k != "supply_batch_ids_1120"}, indent=1,
                 ensure_ascii=False, default=str)[:4000])
