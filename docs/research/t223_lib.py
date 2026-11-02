"""T-223 shared machinery: read the PostgREST cache, rebuild the S-691 panel and the
mapping-check ('kept') list, and the partial-Spearman IC engine.

Everything here mirrors docs/research/s691_holdout.sql / s691_factor_zoo_discovery.sql
line by line (the SQL scratch tables were deleted, and this run had no SQL access).
"""
import os, sys, csv, gzip, math, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "t223_cache")
sys.path.insert(0, HERE)


def read_csv(name):
    p = os.path.join(CACHE, name + ".csv.gz")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, dtype=str, low_memory=False)


def to_num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_panel():
    """Return (panel_df, deriv_df, perp_df, cg_df, kept_syms, kept_stats).

    panel_df: sym, d, price, mcap, mult   (one source per symbol, as the SQL does:
             asset_mcap_daily branch (mult=1) if the symbol is in am_syms, else the
             perp_cg_map → cg_coin_mcap_daily branch with the map's mult)
    """
    perp = read_csv("perp_cg_map")
    deriv = read_csv("deriv_metrics_daily")
    amcg = read_csv("amcg")
    cg = read_csv("cg_mcap")
    for df, cols in ((perp, []), (deriv, ["oi_close", "oi_value_close", "taker_ratio_mean",
                                          "top_pos_ratio_close", "global_acct_ratio_close"]),
                     (amcg, ["price", "mcap"]), (cg, ["price", "mcap"])):
        if df is not None:
            to_num(df, cols)
    if perp is None or deriv is None:
        raise SystemExit("cache missing: run t223_pull.py first")

    names = set(deriv["symbol"].dropna().unique())
    perp_map = {}
    if perp is not None:
        p = perp[(perp.get("verdict") == "resolved")] if "verdict" in perp.columns else perp
        for _, r in p.iterrows():
            if r.get("symbol") and r.get("coin_id"):
                perp_map[str(r["symbol"])] = {"coin_id": str(r["coin_id"]),
                                              "mult": float(r.get("mult") or 1.0)}
    amcg_syms = set(amcg["symbol"].dropna().unique()) if amcg is not None else set()

    frames = []
    if amcg is not None and len(amcg):
        a = amcg[amcg["symbol"].isin(names)].copy()
        a["mult"] = 1.0
        a["src"] = "amcg"
        frames.append(a[["symbol", "d", "price", "mcap", "mult", "src"]])
    if cg is not None and len(cg):
        c = cg.copy()
        c = c.merge(pd.DataFrame([{"coin_id": v["coin_id"], "sym": k, "mult": v["mult"]}
                                  for k, v in perp_map.items()]), on="coin_id", how="inner")
        c["symbol"] = c["sym"]
        c["src"] = "cg"
        frames.append(c[["symbol", "d", "price", "mcap", "mult", "src"]])
    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    panel = panel.dropna(subset=["d", "price"])
    panel = panel[panel["price"] > 0]
    panel["d"] = panel["d"].astype(str).str[:10]
    panel = panel.sort_values(["symbol", "d"]).drop_duplicates(["symbol", "d"], keep="first")

    kept, stats = kept_list(panel, deriv)
    return panel, deriv, perp_map, kept, stats


def kept_list(panel, deriv):
    """S-691 discovery 'kept': overlap ≥ 30 days and median mapping error ≤ 0.05."""
    d = deriv.copy()
    d["d"] = d["d"].astype(str).str[:10]
    oi = d[(d["oi_close"] > 0) & (d["oi_value_close"] > 0)][
        ["symbol", "d", "oi_close", "oi_value_close"]]
    j = oi.merge(panel[["symbol", "d", "price", "mult"]], on=["symbol", "d"], how="inner")
    j = j[j["d"] >= "2023-01-01"]
    j["err"] = (j["price"] * j["mult"] / (j["oi_value_close"] / j["oi_close"]) - 1).abs()
    g = j.groupby("symbol")["err"]
    med = g.median()
    n = j.groupby("symbol")["err"].size()
    kept = set(med[(n >= 30) & (med <= 0.05)].index)
    stats = {"n_overlap_min": int(n.min()) if len(n) else 0,
             "n_kept": len(kept),
             "n_seen": int(len(n)),
             "med_err_max_kept": float(med[list(kept)].max()) if kept else None,
             "n_median_gt_005": int((med > 0.05).sum()),
             "n_overlap_lt_30": int((n < 30).sum())}
    return kept, stats


def btc_series():
    """BTC daily price from asset_mcap_daily (coin_id='bitcoin', coingecko_pro_market_chart).

    Paginates explicitly (order=d.asc): a bare read returns only PostgREST's first
    page (1000 rows → 2014-2017), which silently truncates the forward window.
    """
    try:
        from t223_db import DB       # self-contained copy on this branch
    except ImportError:              # pragma: no cover
        from t219_db import DB
    p = os.path.join(CACHE, "btc.csv.gz")
    if not os.path.exists(p):
        db = DB()
        rows, off = [], 0
        while True:
            page, _ = db.get("asset_mcap_daily",
                             {"select": "d,price", "source": "eq.coingecko_pro_market_chart",
                              "coin_id": "eq.bitcoin", "order": "d.asc",
                              "limit": "1000", "offset": str(off)})
            if not page:
                break
            rows.extend(page)
            if len(page) < 1000:
                break
            off += len(page)
        with gzip.open(p, "wt", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["d", "price"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
    df = pd.read_csv(p, dtype=str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["d"] = df["d"].astype(str).str[:10]
    return df.dropna(subset=["price"]).drop_duplicates("d").set_index("d")["price"].sort_index()


# ---------------------------------------------------------------- IC machinery
def midrank(a):
    """SQL: rank() + (count(*) over (same value) - 1)/2  → mid-rank (1-based)."""
    a = np.asarray(a, dtype=float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    vals = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and vals[j + 1] == vals[i]:
            j += 1
        c = j - i + 1
        r = (i + 1) + (c - 1) / 2.0
        ranks[order[i:j + 1]] = r
        i = j + 1
    return ranks


def corr(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


# ------------------------------------------------------------ forward joins
# SQL pattern:  join rs_s691h_px x30f on x30f.sym = x.sym and x30f.d = x.d + 30
#
# ONE signed helper for both directions. The right frame keeps ITS OWN date as
# the join key; the LEFT key is shifted by `offset` days. Matching then picks
# the right row whose date is d+offset — i.e. the value observed AT d+offset.
#
# Do NOT move the right frame's key instead: that inverts the offset (asking for
# d-30 returns the value at d+30). That exact mistake made `mom30` the mirror
# image of `y` — a partial IC of exactly -1.0 — in part A and part B alike.
def join_offset(left, right, offset=30, val="price", key="d"):
    """left[(symbol,key)] ← right[(symbol, key+offset)][val]  (per symbol)."""
    r = right[["symbol", key, val]].copy()
    r["_rk"] = pd.to_datetime(r[key])
    r = r.drop(columns=[key]).rename(columns={val: "_v"})
    l = left.copy()
    l["_fk"] = pd.to_datetime(l[key]) + pd.Timedelta(days=offset)
    out = l.merge(r, left_on=["symbol", "_fk"], right_on=["symbol", "_rk"], how="left")
    out[val + "_at"] = out["_v"]
    return out.drop(columns=["_fk", "_rk", "_v"])


def join_offset_series(left, right, offset=30, val="price", key="d"):
    """Same as join_offset for a single-series frame (no symbol column)."""
    r = right[[key, val]].copy()
    r["_rk"] = pd.to_datetime(r[key])
    r = r.drop(columns=[key]).rename(columns={val: "_v"})
    l = left.copy()
    l["_fk"] = pd.to_datetime(l[key]) + pd.Timedelta(days=offset)
    out = l.merge(r, left_on="_fk", right_on="_rk", how="left")
    out[val + "_at"] = out["_v"]
    return out.drop(columns=["_fk", "_rk", "_v"])


def partial_ic(v, y, size):
    """Spearman partial correlation of factor rank vs y rank, controlling size rank."""
    rv, ry, rs = midrank(v), midrank(y), midrank(size)
    r_vy, r_vs, r_ys = corr(rv, ry), corr(rv, rs), corr(ry, rs)
    if r_vy is None or r_vs is None or r_ys is None:
        return None
    if abs(r_vs) >= 1 or abs(r_ys) >= 1:
        return None
    return float((r_vy - r_vs * r_ys) / math.sqrt((1 - r_vs * r_vs) * (1 - r_ys * r_ys)))


def monthly_stats(daily):
    """daily: DataFrame[factor, d, ic] → per factor: n_months, mean_ic, t_month, pos_months."""
    out = {}
    if daily is None or len(daily) == 0:
        return out
    daily = daily.copy()
    daily["m"] = daily["d"].str[:7]
    for f, g in daily.groupby("factor"):
        mm = g.groupby("m")["ic"].mean()
        mm = mm.dropna()
        if len(mm) == 0:
            continue
        sd = mm.std(ddof=1)
        t = float(mm.mean() / sd * math.sqrt(len(mm))) if (sd and not np.isnan(sd)) else None
        out[f] = {"n_months": int(len(mm)), "mean_ic": round(float(mm.mean()), 6),
                  "t_month": None if t is None else round(t, 3),
                  "pos_months": int((mm > 0).sum()),
                  "months": {str(k): round(float(v), 4) for k, v in mm.items()}}
    return out
