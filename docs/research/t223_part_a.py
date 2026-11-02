"""T-223 part A: S-696's first forward check — the 2026-10 signal month.

Protocol = docs/research/s691_holdout.sql, recomputed in Python (no SQL access this
run). Signal days 2026-10-01 / 2026-10-02 (y needs d+30, data ends 2026-11-01).

Writes docs/research/t223_part_a.json.
"""
import os, sys, json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from t223_lib import (load_panel, btc_series, partial_ic, monthly_stats,
                      join_offset, join_offset_series)

SIG = ["2026-10-01", "2026-10-02"]
WIN_FROM, WIN_TO = "2026-06-20", "2026-11-01"
RECONCILE = "--reconcile" in sys.argv
if RECONCILE:
    # same protocol, but the whole sealed holdout segment: does this Python port
    # reproduce the SQL-produced numbers in s691_holdout_seth.json?
    WIN_FROM, WIN_TO = "2024-11-01", "2026-10-26"
HOLD = json.load(open(os.path.join(HERE, "s691_holdout_seth.json")))


def parse_months(s):
    """'2501=-0.242 2502=-0.086' → {'2025-01': -0.242, ...}"""
    out = {}
    for tok in str(s).split():
        k, _, v = tok.partition("=")
        out["20%s-%s" % (k[:2], k[2:])] = float(v)
    return out


def reconcile(res):
    """Compare this Python port against the SQL-produced holdout ledger."""
    rows = []
    for reading in ("main", "literal"):
        for f, sqlrow in HOLD.get("main", {}).items():
            mine = res["by_reading"][reading].get(f)
            if not mine:
                rows.append({"reading": reading, "factor": f, "mine": None})
                continue
            sql_m = parse_months(sqlrow.get("months", ""))
            my_m = {k[:7]: v for k, v in mine["months"].items()}
            common = sorted(set(sql_m) & set(my_m))
            max_d = max((abs(my_m[k] - sql_m[k]) for k in common), default=None)
            row = {"reading": reading, "factor": f,
                   "mine_mean_ic": mine["mean_ic"], "sql_mean_ic": sqlrow["mean_ic"],
                   "d_mean_ic": None if mine["mean_ic"] is None or sqlrow["mean_ic"] is None
                                else round(mine["mean_ic"] - sqlrow["mean_ic"], 4),
                   "mine_t": mine["t_month"], "sql_t": sqlrow["t_month"],
                   "d_t": None if mine["t_month"] is None or sqlrow["t_month"] is None
                           else round(mine["t_month"] - sqlrow["t_month"], 3),
                   "mine_pos_months": mine["pos_months"], "sql_pos_months": sqlrow["pos_months"],
                   "n_months_common": len(common),
                   "max_abs_monthly_ic_diff": None if max_d is None else round(max_d, 4)}
            lit = HOLD.get("literal_t", {}).get(f) if reading == "literal" else None
            if lit is not None:
                row["sql_literal_t"] = lit.get("t_month") if isinstance(lit, dict) else lit
                row["d_t_literal"] = (None if row["sql_literal_t"] is None or mine["t_month"] is None
                                      else round(mine["t_month"] - row["sql_literal_t"], 3))
            rows.append(row)
    return rows


def tkr_roll(o, col, days=6):
    """SQL: avg(col) over (partition by symbol order by d range between interval
    '6 days' preceding and current row) → mean over [d-6, d], and the matching count.
    Keyed by (symbol, date)."""
    o = o.sort_values(["symbol", "d"]).copy()
    o["_d"] = pd.to_datetime(o["d"])
    out = {}
    win = f"{days + 1}D"
    for sym, g in o.groupby("symbol"):
        g = g.set_index("_d").sort_index()
        s = pd.to_numeric(g[col], errors="coerce")
        sm = s.rolling(win, min_periods=1).mean()
        cn = s.rolling(win, min_periods=1).count()
        for d, v, c in zip(sm.index, sm.values, cn.values):
            out[(sym, d.strftime("%Y-%m-%d"))] = (v, c)
    return out


def main():
    global SIG
    panel, deriv, perp_map, kept, kept_stats = load_panel()
    btc = btc_series()

    p = panel[(panel["d"] >= WIN_FROM) & (panel["d"] <= WIN_TO)].copy()
    o = deriv[(deriv["d"] >= WIN_FROM) & (deriv["d"] <= WIN_TO)].copy()
    o = o[o["symbol"].isin(kept)]

    # per-symbol panel: lag prices and rolling vol
    rows = []
    for sym, g in p.groupby("symbol"):
        g = g.sort_values("d").copy()
        g["_d"] = pd.to_datetime(g["d"])
        g = g.set_index("_d").drop(columns=["d"])
        g["px_lag1"] = g["price"].shift(1)
        lr = np.log(g["price"] / g["px_lag1"])
        g["nlr30"] = lr.notna().astype(float).rolling("30D", min_periods=1).count()
        g["vol30"] = lr.rolling("30D", min_periods=1).std(ddof=1)
        g = g.reset_index().rename(columns={"_d": "d"})
        g["d"] = g["d"].dt.strftime("%Y-%m-%d")
        rows.append(g)
    P = pd.concat(rows, ignore_index=True)
    P = P[P["symbol"].isin(kept)]
    if RECONCILE:
        # every signal day of the sealed holdout segment that the panel can price
        SIG = sorted(P.loc[(P["d"] >= "2025-01-01") & (P["d"] <= "2026-09-26"),
                           "d"].unique().tolist())

    # forward 30d price: SQL joins on x30f.d = x.d + 30 (CALENDAR)
    P = join_offset(P, P[["symbol", "d", "price"]], offset=30, val="price").rename(
        columns={"price_at": "px_fwd"})
    # backward 7d / 30d prices: SQL joins on x7.d = x.d - 7 / x30.d = x.d - 30
    P = join_offset(P, P[["symbol", "d", "price"]], offset=-7, val="price").rename(
        columns={"price_at": "px7"})
    P = join_offset(P, P[["symbol", "d", "price"]], offset=-30, val="price").rename(
        columns={"price_at": "px30"})

    tkr = tkr_roll(o, "taker_ratio_mean", 6)

    # BTC: one map keyed by the ACTUAL date; every lookup is explicit target-date
# arithmetic (SQL: b.d = x.d, b30f.d = x.d + 30, b7.d = x.d - 7, b30.d = x.d - 30).
    b = pd.DataFrame({"d": pd.to_datetime(btc.index), "btc": btc.values})
    b = b[(b["d"] >= WIN_FROM) & (b["d"] <= WIN_TO)]
    bmap = dict(zip(b["d"].dt.strftime("%Y-%m-%d"), b["btc"]))

    def btc_at(ds):
        return bmap.get(pd.Timestamp(ds).strftime("%Y-%m-%d"))

    def shift(ds, days):
        return (pd.Timestamp(ds) + pd.Timedelta(days=days)).strftime("%Y-%m-%d")

    o["d"] = o["d"].astype(str).str[:10]
    oi = o.set_index(["symbol", "d"])

    recs = []
    for d in SIG:
        day = P[P["d"] == d]
        for _, r in day.iterrows():
            sym = r["symbol"]
            mcap = r["mcap"]
            if mcap is None or not np.isfinite(mcap) or mcap < 20_000_000:
                continue
            px_d = r["price"]
            px_f = r["px_fwd"]
            if not np.isfinite(px_d) or not np.isfinite(px_f) or px_f <= 0:
                continue
            b_d, b_f = btc_at(d), btc_at(shift(d, 30))
            if not (np.isfinite(b_d) and np.isfinite(b_f)) or b_f <= 0:
                continue
            y = (px_f / px_d - 1) - (b_f / b_d - 1)
            oi_v = oi.loc[(sym, d)] if (sym, d) in oi.index else None
            oi_close = oi_v["oi_close"] if oi_v is not None else np.nan
            oi_value = oi_v["oi_value_close"] if oi_v is not None else np.nan
            k30 = (sym, shift(d, -30))
            oi30_v = oi.loc[k30] if k30 in oi.index else None
            oi_close30 = oi30_v["oi_close"] if oi30_v is not None else np.nan
            t = tkr.get((sym, d))
            px7, px30 = r["px7"], r["px30"]
            b7, b30 = btc_at(shift(d, -7)), btc_at(shift(d, -30))
            recs.append({
                "symbol": sym, "d": d, "y": y, "size": float(np.log(mcap)),
                "has_oi": bool(np.isfinite(oi_value) and oi_value > 0),
                "f01_oi_mcap": float(oi_value / mcap) if (np.isfinite(oi_value) and oi_value > 0) else None,
                "f03_doi30": float(np.log(oi_close / oi_close30)) if (np.isfinite(oi_close) and np.isfinite(oi_close30) and oi_close > 0 and oi_close30 > 0) else None,
                "f07_taker7": t[0] if (t and t[1] >= 5) else None,
                "f08_mom30": float((px_d / px30 - 1) - (b_d / b30 - 1)) if (np.isfinite(px30) and px30 > 0 and np.isfinite(b30) and b30 > 0) else None,
                "f09_mom7": float((px_d / px7 - 1) - (b_d / b7 - 1)) if (np.isfinite(px7) and px7 > 0 and np.isfinite(b7) and b7 > 0) else None,
                "f11_vol30": float(r["vol30"]) if (np.isfinite(r["vol30"]) and r["nlr30"] >= 25) else None,
            })

    D = pd.DataFrame(recs)
    FAC = ["f01_oi_mcap", "f03_doi30", "f07_taker7", "f08_mom30", "f09_mom7", "f11_vol30"]
    daily_rows = []
    per_day = []
    for reading in ("main", "literal"):
        for f in FAC:
            for d in SIG:
                sub = D[(D["d"] == d) & D[f].notna()]
                if reading == "main":
                    sub = sub[sub["has_oi"]]
                if len(sub) < 30:
                    continue
                ic = partial_ic(sub[f].values, sub["y"].values, sub["size"].values)
                if ic is None:
                    continue
                daily_rows.append({"reading": reading, "factor": f, "d": d, "ic": ic,
                                   "n": int(len(sub))})
                per_day.append({"reading": reading, "factor": f, "d": d,
                                 "n_names": int(len(sub)), "ic": round(ic, 4)})
    daily = pd.DataFrame(daily_rows)
    res = {"signal_days": SIG, "n_rows_panel": int(len(D)),
           "kept_stats": kept_stats, "per_day": per_day, "by_reading": {}}
    for reading in ("main", "literal"):
        sub = daily[daily["reading"] == reading] if len(daily) else daily
        res["by_reading"][reading] = monthly_stats(sub)
    cmp_rows = []
    for reading in ("main", "literal"):
        for f in FAC:
            fwd = res["by_reading"][reading].get(f)
            h = HOLD.get(reading, {}).get(f) or HOLD["main"].get(f)
            if not fwd:
                cmp_rows.append({"reading": reading, "factor": f, "forward_ic": None,
                                 "forward_sign": None, "holdout_mean_ic": h["mean_ic"],
                                 "holdout_sign": "+" if h["mean_ic"] > 0 else "-",
                                 "same_sign": None, "note": "no value"})
                continue
            fv = fwd["mean_ic"]
            cmp_rows.append({"reading": reading, "factor": f,
                             "forward_ic": fv, "forward_n_days": fwd["n_months"],
                             "forward_sign": "+" if fv > 0 else ("-" if fv < 0 else "0"),
                             "holdout_mean_ic": h["mean_ic"], "holdout_t": h["t_month"],
                             "holdout_sign": "+" if h["mean_ic"] > 0 else "-",
                             "same_sign": (fv > 0) == (h["mean_ic"] > 0) if fv != 0 else None})
    res["sign_vs_holdout"] = cmp_rows
    path = os.path.join(HERE, "t223_part_a.json")
    if RECONCILE:
        rec = reconcile(res)
        res["reconcile"] = rec
        with open(os.path.join(HERE, "t223_part_a_reconcile.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    if RECONCILE:
        print("signal_days=%d kept=%d" % (len(SIG), len(kept)))
        for r in res["reconcile"]:
            print("%-8s %-14s mean_ic mine=%-9s sql=%-9s d=%-8s | t mine=%-8s sql=%-8s d=%-7s | pos mine=%-3s sql=%-3s | months=%-3s maxdiff=%s" % (
                r.get("reading"), r.get("factor"), r.get("mine_mean_ic"), r.get("sql_mean_ic"),
                r.get("d_mean_ic"), r.get("mine_t"), r.get("sql_t"), r.get("d_t"),
                r.get("mine_pos_months"), r.get("sql_pos_months"),
                r.get("n_months_common"), r.get("max_abs_monthly_ic_diff")))
    else:
        print(json.dumps({"kept_stats": kept_stats, "per_day": per_day,
                          "sign_vs_holdout": cmp_rows}, indent=2, ensure_ascii=False))


main()
