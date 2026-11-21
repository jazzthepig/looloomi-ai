"""T-422 探针:摸清兜底原料与 CG 现状(只读)。产物 → /Volumes/CometCloudAI/cometcloud-local/research/t422/"""
import json, os, sys
import urllib.parse
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
OUT = "/Volumes/CometCloudAI/cometcloud-local/research/t422"


def get(path, params=None, count=False):
    q = dict(params or {})
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in q.items())
    req = urllib.request.Request(f"{URL}/rest/v1/{path}?{qs}", headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}",
        "Prefer": "count=exact" if count else "return=minimal"})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read().decode()
        return (json.loads(body) if body.strip() else []), r.headers.get("Content-Range")


out = {}
# 列名:直接 select=* limit 1 探(根 schema 端点 401)
for t in ("coin_supply_daily", "asset_mcap_daily", "ohlcv_daily", "macro_daily"):
    try:
        rows, _ = get(t, {"select": "*", "limit": "1"})
        out[t + "_cols"] = sorted(rows[0].keys()) if rows else []
    except Exception as e:
        out[t + "_cols_err"] = f"{type(e).__name__}: {e}"

for t, dcol in (("asset_mcap_daily", "d"), ("coin_supply_daily", "d"), ("macro_daily", "d")):
    try:
        rows, _ = get(t, {"select": f"{dcol}", "order": f"{dcol}.desc", "limit": "1"})
        out[t + "_max_d"] = rows
    except Exception as e:
        out[t + "_err"] = f"{type(e).__name__}: {e}"

for d in ("2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"):
    rows, rng = get("asset_mcap_daily", {"select": "coin_id,d,price,mcap,volume,source",
                                         "d": f"eq.{d}", "order": "coin_id.asc"}, count=True)
    out[f"mcap_{d}_n"] = len(rows)
    out[f"mcap_{d}_range"] = rng
    if d == "2026-11-19":
        out["mcap_1119_sample"] = rows[:2]

rows, rng = get("coin_supply_daily", {"select": "coin_id,d,circulating_supply,total_supply",
                                      "order": "d.desc,coin_id.asc"}, count=True)
out["supply_total_rows"] = rng
out["supply_latest_d"] = rows[0]["d"] if rows else None
if rows:
    dd = rows[0]["d"]
    rows2, _ = get("coin_supply_daily", {"select": "coin_id,d,circulating_supply,total_supply",
                                          "d": f"eq.{dd}", "order": "coin_id.asc"})
    out["supply_batch_d"] = dd
    out["supply_batch_n"] = len(rows2)
    out["supply_batch_missing_tot"] = sum(1 for r in rows2 if r.get("total_supply") is None)
    out["supply_batch_missing_circ"] = sum(1 for r in rows2 if r.get("circulating_supply") is None)
    out["supply_batch_ids"] = [r["coin_id"] for r in rows2]
    out["supply_sample"] = rows2[:2]

rows, _ = get("macro_daily", {"select": "series,d,value", "series": "eq.total_mcap",
                               "order": "d.desc", "limit": "5"})
out["macro_total_mcap_tail"] = rows
rows, _ = get("macro_daily", {"select": "series", "order": "series.asc"})
out["macro_series"] = sorted({r["series"] for r in rows})

for d in ("2026-11-19", "2026-11-20", "2026-11-21"):
    rows, rng = get("ohlcv_daily", {"select": "symbol,trade_date,close,volume",
                                    "source": "eq.binance_hist", "trade_date": f"eq.{d}",
                                    "order": "symbol.asc"}, count=True)
    out[f"ohlcv_bh_{d}_n"] = len(rows)
    out[f"ohlcv_bh_{d}_syms"] = sorted(r["symbol"] for r in rows)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "probe.json"), "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, default=str)
print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
