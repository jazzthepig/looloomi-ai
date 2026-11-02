"""T-223 raw pull (PostgREST → local CSV). Read-only on the DB; writes only into
docs/research/t223_cache/ (untracked on purpose — the committed artifacts are the
small computed JSONs, not 50MB of raw rows).

Tables the S-691 protocol needs:
  deriv_metrics_daily   OI / taker ratio / top-pos (factor inputs + kept-list check)
  asset_mcap_daily      price + mcap (coingecko_pro_market_chart source)
  cg_coin_mcap_daily    price + mcap for the 43 perp-mapped coin_ids
  perp_cg_map           symbol ↔ coin_id mapping + mult
  protocol_revenue_daily  G1/G2/G3 inputs
  state_daily           G5/G6 inputs (feature panel)

Order is always explicit (PostgREST paging boundary drifts without it).
Resumable: a file that already exists is not re-pulled.
"""
import os, sys, csv, time, gzip

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from t223_db import DB          # self-contained copy on this branch
except ImportError:                 # pragma: no cover
    from t219_db import DB

CACHE = os.path.join(HERE, "t223_cache")
os.makedirs(CACHE, exist_ok=True)
db = DB()
FROM, TO = "2023-01-01", "2026-11-01"


def pull(name, table, select, order, filters=None, limit=1000):
    path = os.path.join(CACHE, name + ".csv.gz")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print("[skip]", name, os.path.getsize(path))
        return
    t0 = time.time()
    n = 0
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        w = None
        off = 0
        while True:
            params = {"select": select, "limit": limit, "offset": off, "order": order}
            for k, v in (filters or {}).items():
                params[k] = v
            rows, _ = db.get(table, params)
            if not rows:
                break
            if w is None:
                w = csv.DictWriter(fh, fieldnames=sorted(rows[0].keys()))
                w.writeheader()
            for r in rows:
                w.writerow(r)
            n += len(rows)
            off += len(rows)
            if len(rows) < limit:
                break
            if n % 50000 == 0:
                print("   %s %d rows %.0fs" % (name, n, time.time() - t0), flush=True)
    print("[done]", name, n, "rows %.0fs" % (time.time() - t0), flush=True)


# 1. perp mapping first (small) — needed to know which coin_ids to pull
pull("perp_cg_map", "perp_cg_map", "*", "symbol.asc", None, limit=100)

# 2. deriv_metrics_daily (OI etc.) for 2023-01-01..2026-11-01
pull("deriv_metrics_daily", "deriv_metrics_daily",
     "symbol,d,oi_close,oi_value_close,taker_ratio_mean,top_pos_ratio_close,global_acct_ratio_close",
     "symbol.asc,d.asc", {"d": "gte." + FROM})

# 3. names = distinct symbol in deriv_metrics_daily
names = set()
with gzip.open(os.path.join(CACHE, "deriv_metrics_daily.csv.gz"), "rt", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        names.add(r["symbol"])
print("[names]", len(names), flush=True)

# 4. prices: asset_mcap_daily (coingecko_pro_market_chart) for those names
pull("amcg", "asset_mcap_daily", "symbol,d,price,mcap", "symbol.asc,d.asc",
     {"source": "eq.coingecko_pro_market_chart", "d": "gte." + FROM,
      "symbol": "in.(" + ",".join(sorted(names)) + ")"})

# 5. cg_coin_mcap_daily for the 43 resolved perp coin_ids
coin_ids = []
with gzip.open(os.path.join(CACHE, "perp_cg_map.csv.gz"), "rt", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if r.get("verdict") == "resolved" and r.get("coin_id"):
            coin_ids.append(r["coin_id"])
print("[coin_ids]", len(coin_ids), flush=True)
if coin_ids:
    pull("cg_mcap", "cg_coin_mcap_daily", "coin_id,d,price,mcap", "coin_id.asc,d.asc",
         {"d": "gte." + FROM, "coin_id": "in.(" + ",".join(coin_ids) + ")"})

# 6. protocol revenue + state panel (small enough)
pull("protocol_revenue_daily", "protocol_revenue_daily", "*", "slug.asc,d.asc", None)
pull("state_daily", "state_daily", "d,entity,feature,value", "d.asc,entity.asc,feature.asc", None)
print("[all done]", flush=True)
