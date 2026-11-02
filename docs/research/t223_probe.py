"""T-223 probe: raw-data facts behind the second-family (G1–G6) verdicts.

Two sources, both read-only:
  * the local PostgREST cache (docs/research/t223_cache/*.csv.gz) — these files are
    full-table pulls (`select=*`, no filter), so they ARE the raw rows;
  * the DB itself, for the things the cache cannot show: the column list of the
    mcap tables (G4: is there a supply column?) and whether some other table
    carries supply / exchange-flow data (G4, G6).

Every "读不到" in the report is checked here against raw rows, not against a
previous round's notes.

Writes docs/research/t223_probe.json.
"""
import os, sys, json, re
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CACHE = os.path.join(HERE, "t223_cache")

out = {}

# ---------------------------------------------------------------- G1/G2/G3 source
rev = pd.read_csv(os.path.join(CACHE, "protocol_revenue_daily.csv.gz"), dtype=str,
                  low_memory=False)
rev["d"] = rev["d"].astype(str).str[:10]
out["protocol_revenue_daily"] = {
    "rows": int(len(rev)),
    "columns": sorted(rev.columns.tolist()),
    "min_d": rev["d"].min(),
    "max_d": rev["d"].max(),
    "distinct_days": int(rev["d"].nunique()),
    "rows_before_2026_10_01": int((rev["d"] < "2026-10-01").sum()),
    "rows_in_discovery_2023_01_to_2024_12":
        int(((rev["d"] >= "2023-01-01") & (rev["d"] <= "2024-12-31")).sum()),
    "rows_in_holdout_2025_01_to_2026_09_26":
        int(((rev["d"] >= "2025-01-01") & (rev["d"] <= "2026-09-26")).sum()),
    "distinct_gecko_id": int(rev["gecko_id"].nunique()) if "gecko_id" in rev.columns else None,
    "revenue_columns": [c for c in rev.columns if c.startswith("revenue")],
    "holder_columns": [c for c in rev.columns if "holder" in c.lower()],
}

# ---------------------------------------------------------------- G5/G6 source
st = pd.read_csv(os.path.join(CACHE, "state_daily.csv.gz"), dtype=str, low_memory=False)
st["d"] = st["d"].astype(str).str[:10]
st["value"] = pd.to_numeric(st["value"], errors="coerce")
panel = st[st["entity"] == "panel"]
out["state_daily"] = {
    "rows": int(len(st)),
    "columns": sorted(st.columns.tolist()),
    "min_d": st["d"].min(),
    "max_d": st["d"].max(),
    "entities": sorted(set(st["entity"].dropna().tolist())),
    "panel_features": sorted(set(panel["feature"].dropna().tolist())),
    "all_features": sorted(set(st["feature"].dropna().tolist())),
}
ss = panel[panel["feature"] == "stable_supply_30d"].sort_values("d")
out["stable_supply_30d"] = {
    "rows": int(len(ss)),
    "min_d": ss["d"].min() if len(ss) else None,
    "max_d": ss["d"].max() if len(ss) else None,
    "last_value": float(ss["value"].iloc[-1]) if len(ss) else None,
    "value_2026_10_31": (float(ss[ss["d"] == "2026-10-31"]["value"].iloc[0])
                         if len(ss[ss["d"] == "2026-10-31"]) else None),
}
out["g6_candidate_features"] = [f for f in sorted(set(st["feature"].dropna().tolist()))
                                if re.search("inflow|outflow|flow|net|exchange|reserve",
                                             str(f), re.I)]

# ---------------------------------------------------------------- DB-side checks
try:
    from t223_db import DB
    db = DB()
    CAND = ["protocol_revenue_daily", "protocol_fees_daily", "fees_daily",
            "revenue_daily", "token_revenue_daily", "supply_daily", "token_supply_daily",
            "supply_history", "market_supply_daily", "circulating_supply_daily",
            "asset_supply_daily", "exchange_flows_daily", "exchange_netflow_daily",
            "exchange_inflows_daily", "cex_flows_daily", "netflow_daily",
            "holder_counts_daily", "state_daily", "macro_daily", "asset_mcap_daily",
            "cg_coin_mcap_daily", "ohlcv_daily", "deriv_metrics_daily"]
    found = {}
    for t in CAND:
        ok, _ = db.exists(t)
        if ok:
            found[t] = db.count(t)
    out["db_tables_present"] = found
    cols = {}
    for t in ("asset_mcap_daily", "cg_coin_mcap_daily", "protocol_revenue_daily",
              "state_daily", "macro_daily"):
        if t in found:
            rows, _ = db.get(t, {"select": "*", "limit": 1})
            cols[t] = sorted(rows[0].keys()) if rows else None
    out["db_columns"] = cols
    macro = db.all("macro_daily", select="series", order="series.asc", limit=1000)
    out["macro_series"] = sorted(set(r.get("series") for r in macro if r.get("series")))
except Exception as e:  # read-only probe: report the failure, never fabricate
    out["db_probe_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])

json.dump(out, open(os.path.join(HERE, "t223_probe.json"), "w"), indent=2, ensure_ascii=False)

# compact summary for the console (the JSON file above is the full record)
rv = out["protocol_revenue_daily"]
print("REV rows=%s days=%s min=%s max=%s pre2026-10=%s disc=%s hold=%s" % (
    rv["rows"], rv["distinct_days"], rv["min_d"], rv["max_d"],
    rv["rows_before_2026_10_01"], rv["rows_in_discovery_2023_01_to_2024_12"],
    rv["rows_in_holdout_2025_01_to_2026_09_26"]))
print("REV revenue_cols=%s holder_cols=%s" % (rv["revenue_columns"], rv["holder_columns"]))
sd = out["state_daily"]
print("STATE rows=%s min=%s max=%s entities=%s" % (sd["rows"], sd["min_d"], sd["max_d"], sd["entities"]))
print("STATE panel_features=%s" % (sd["panel_features"],))
print("STATE all_features=%s" % (sd["all_features"],))
print("G6 candidates=%s" % (out["g6_candidate_features"],))
print("G5 stable_supply_30d=%s" % json.dumps(out["stable_supply_30d"], ensure_ascii=False))
print("DB tables=%s" % json.dumps(out.get("db_tables_present"), ensure_ascii=False))
print("DB columns=%s" % json.dumps(out.get("db_columns"), ensure_ascii=False))
print("MACRO series=%s" % (out.get("macro_series"),))
print("DB probe error=%s" % out.get("db_probe_error"))
