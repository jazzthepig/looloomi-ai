"""T-223 part B: second factor family (G1–G6) under the S-691 protocol.

Run with `--coverage` first: that mode only measures DATA AVAILABILITY (how many
universe names carry protocol revenue, how many signal days would clear the
≥30-names rule). It computes no IC — that is what the pre-registration needs to
fix the threshold honestly, before any result exists.

Then run without the flag to compute (discovery 2023-01→2024-12, sealed holdout
2025-01→2026-09).

Writes docs/research/t223_part_b.json.
"""
import os, sys, json, math, re
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from t223_lib import (load_panel, btc_series, partial_ic, monthly_stats,
                      join_offset, join_offset_series)

DISCOVERY = ("2023-01-01", "2024-12-31")
HOLDOUT = ("2025-01-01", "2026-09-26")
COVERAGE = "--coverage" in sys.argv
MIN_NAMES_PRIMARY = 30
MIN_NAMES_SENS = 10
MIN_MCAP = 20_000_000


def build(panel, kept):
    """One row per (symbol, signal day) with y, size, G1, G2 (and the G5 time series)."""
    px = panel[["symbol", "d", "price", "mcap"]].copy()
    px = px[px["symbol"].isin(kept)]
    px = px[px["mcap"].notna() & (px["mcap"] >= MIN_MCAP)]
    px["d"] = pd.to_datetime(px["d"])

    # y: forward 30d relative to BTC.
    # SQL: join rs_s691h_px x30f on x30f.d = x.d + 30  → the price AT d+30.
    # (The naive "shift the right frame's date by +30 then merge" trick asks for the
    #  price at d-30 instead — it makes y a BACKWARD return. join_offset keeps the
    #  right frame keyed by its own date and shifts the LEFT key, so the sign is
    #  explicit. Same helper as part A.)
    df = join_offset(px[["symbol", "d", "price", "mcap"]], px[["symbol", "d", "price"]],
                     offset=30, val="price").rename(columns={"price_at": "px_fwd30"})

    btc = btc_series()
    btc = btc[(btc.index >= "2023-01-01") & (btc.index <= "2026-11-01")]
    b = pd.DataFrame({"d": pd.to_datetime(btc.index), "btc": btc.values})
    b = join_offset_series(b, b[["d", "btc"]], offset=30, val="btc").rename(
        columns={"btc_at": "btc_fwd30"})
    df = df.merge(b, on="d", how="inner")
    df = df[(df["px_fwd30"] > 0) & (df["btc"] > 0) & (df["btc_fwd30"] > 0)]
    df["y"] = (df["px_fwd30"] / df["price"] - 1) - (df["btc_fwd30"] / df["btc"] - 1)
    df["size"] = np.log(df["mcap"])

    # ---- G1 / G2: protocol revenue, joined through gecko_id = coin_id
    rev = pd.read_csv(os.path.join(HERE, "t223_cache", "protocol_revenue_daily.csv.gz"), dtype=str,
                      low_memory=False)
    rev["d"] = pd.to_datetime(rev["d"].astype(str).str[:10])
    rev["revenue_30d"] = pd.to_numeric(rev["revenue_30d"], errors="coerce")
    rev["gecko_id"] = rev["gecko_id"].astype(str)
    rev = rev[rev["gecko_id"].notna() & (rev["gecko_id"] != "nan") & rev["revenue_30d"].notna()]
    rev_by_coin = rev.groupby(["gecko_id", "d"], as_index=False)["revenue_30d"].sum()

    sym_coin = json.load(open(os.path.join(HERE, "t223_cache", "sym_coin_id.json")))
    coin_sym = {}
    for s, c in sym_coin.items():
        coin_sym.setdefault(str(c), s)
    rev_by_coin["symbol"] = rev_by_coin["gecko_id"].map(coin_sym)
    rev_by_coin = rev_by_coin[rev_by_coin["symbol"].notna()]
    rev_by_coin = rev_by_coin[rev_by_coin["symbol"].isin(set(df["symbol"]))]

    g = df[["symbol", "d", "price", "mcap", "y", "size"]].merge(
        rev_by_coin[["symbol", "d", "revenue_30d"]], on=["symbol", "d"], how="left")
    g["g01_rev_mcap"] = g["revenue_30d"] / g["mcap"]
    prev = rev_by_coin[["symbol", "d", "revenue_30d"]].copy()
    prev["d"] = prev["d"] + pd.Timedelta(days=30)
    prev = prev.rename(columns={"revenue_30d": "rev_prev"})
    g = g.merge(prev, on=["symbol", "d"], how="left")
    with np.errstate(divide="ignore", invalid="ignore"):
        g["g02_rev_chg"] = np.log(g["revenue_30d"] / g["rev_prev"])
    g.loc[(g["revenue_30d"] <= 0) | (g["rev_prev"] <= 0), "g02_rev_chg"] = np.nan
    return df, g


def daily_ic(g, factor, min_names):
    """Per-signal-day partial IC for one factor (S-691 maths)."""
    out = []
    for d, sub in g.groupby("d"):
        sub = sub[sub[factor].notna()]
        if len(sub) < min_names:
            continue
        ic = partial_ic(sub[factor].values, sub["y"].values, sub["size"].values)
        if ic is None:
            continue
        out.append({"d": d.strftime("%Y-%m-%d"), "ic": ic, "n": int(len(sub))})
    return out


def g5_timeseries(df, state):
    """u_d = equal-weight mean y across names on day d; x_d = stable_supply_30d.
    OLS slope of u on x over the segment → t-stat (n-2 df).

    Two versions:
      daily   — the pre-registered test (n = every signal day).
      monthly — SAME test after aggregating both sides to calendar months. The daily
                version regresses on 30-day-overlapping forward returns, so its t
                is inflated by autocorrelation; the monthly version is what the
                S-691 protocol does for the cross-sectional factors. Computed
                AFTER seeing the daily result → robustness check, not the verdict.
    """
    u = df.groupby("d")["y"].mean().rename("u")
    x = state.set_index("d")["value"].rename("x")
    j = pd.concat([u, x], axis=1).dropna()
    j = j.reset_index()
    if len(j) < 5:
        return None

    def ols(frame):
        xv = frame["x"].values.astype(float)
        yv = frame["u"].values.astype(float)
        n = len(frame)
        if n < 4 or np.var(xv) == 0:
            return None
        slope = float(np.cov(xv, yv, ddof=1)[0, 1] / np.var(xv, ddof=1))
        resid = yv - (yv.mean() + slope * (xv - xv.mean()))
        se = float(np.sqrt((resid ** 2).sum() / (n - 2) / ((n - 1) * np.var(xv, ddof=1))))
        return {"n": n, "slope": round(slope, 6),
                "t": None if not se else round(slope / se, 3)}

    res = ols(j)
    if res:
        res["first"] = j["d"].min().strftime("%Y-%m-%d")
        res["last"] = j["d"].max().strftime("%Y-%m-%d")
    jm = j.set_index("d").resample("ME").mean().dropna().reset_index()
    res["monthly"] = ols(jm)
    if res["monthly"]:
        res["monthly"]["first"] = jm["d"].min().strftime("%Y-%m")
        res["monthly"]["last"] = jm["d"].max().strftime("%Y-%m")
    return res


def main():
    panel, deriv, perp_map, kept, kept_stats = load_panel()
    df, g = build(panel, kept)

    state = pd.read_csv(os.path.join(HERE, "t223_cache", "state_daily.csv.gz"), dtype=str,
                        low_memory=False)
    state["d"] = pd.to_datetime(state["d"].astype(str).str[:10])
    state["value"] = pd.to_numeric(state["value"], errors="coerce")
    feats = sorted(set(state["feature"].dropna()))
    panel_state = state[state["entity"] == "panel"]

    if COVERAGE:
        rev_names = sorted(set(g[g["g01_rev_mcap"].notna()]["symbol"]))
        cov = {}
        for label, (a, b) in (("discovery", DISCOVERY), ("holdout", HOLDOUT)):
            sub = g[(g["d"] >= a) & (g["d"] <= b)]
            cnt = sub.groupby("d")["g01_rev_mcap"].count()
            cov[label] = {"days": int(len(cnt)), "days_ge30": int((cnt >= 30).sum()),
                          "days_ge10": int((cnt >= 10).sum()),
                          "median_names": float(cnt.median()) if len(cnt) else 0,
                          "max_names": int(cnt.max()) if len(cnt) else 0}
        out = {"kept_stats": kept_stats, "universe_kept": len(kept),
               "names_with_revenue": rev_names, "n_names_with_revenue": len(rev_names),
               "coverage_g1_g2": cov, "state_features": feats,
               "panel_features": sorted(set(panel_state["feature"].dropna())),
               "g6_candidates": [f for f in feats if re.search("inflow|flow|net", f, re.I)]}
        json.dump(out, open(os.path.join(HERE, "t223_part_b_coverage.json"), "w"),
                  indent=2, ensure_ascii=False)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    res = {"kept_stats": kept_stats, "segments": {}, "g5": {}}
    for label, (a, b) in (("discovery", DISCOVERY), ("holdout", HOLDOUT)):
        sub = g[(g["d"] >= a) & (g["d"] <= b)]
        seg = {"signal_days": int(sub["d"].nunique()), "names": int(sub["symbol"].nunique()),
               "factors": {}}
        for f, mn, tag in (("g01_rev_mcap", MIN_NAMES_PRIMARY, "primary"),
                           ("g01_rev_mcap", MIN_NAMES_SENS, "sens10"),
                           ("g02_rev_chg", MIN_NAMES_PRIMARY, "primary"),
                           ("g02_rev_chg", MIN_NAMES_SENS, "sens10")):
            dl = daily_ic(sub, f, mn)
            st = monthly_stats(pd.DataFrame(dl)) if dl else {}
            seg["factors"].setdefault(f, {})[tag] = {"min_names": mn, "n_days": len(dl),
                                                     "stats": st}
        res["segments"][label] = seg
        gsub = df[(df["d"] >= a) & (df["d"] <= b)]
        ss = panel_state[(panel_state["feature"] == "stable_supply_30d")]
        res["g5"][label] = g5_timeseries(gsub, ss[["d", "value"]])
    res["g5_note"] = ("G5 = 稳定币市值 30 日变化(state_daily stable_supply_30d,entity=panel):"
                      "全体名字共用的时间因子 ⇒ 只做时间序列 t 检,不做截面")
    res["g6"] = {"status": "见 t223_part_b_coverage.json 的 state_features / g6_candidates"}
    res["g3"] = "读不到(protocol_revenue_daily 没有按持有人拆分的收入列)"
    res["g4"] = "读不到(全库没有供给量列,隐含供给不是完全稀释)"
    json.dump(res, open(os.path.join(HERE, "t223_part_b.json"), "w"), indent=2, ensure_ascii=False)
    print(json.dumps({k: v for k, v in res.items() if k != "segments"}, indent=2, ensure_ascii=False))
    for lab, seg in res["segments"].items():
        print("==", lab, "days", seg["signal_days"], "names", seg["names"])
        for f, tags in seg["factors"].items():
            for tag, v in tags.items():
                for fac, st in v["stats"].items():
                    print("   %-14s %-8s n_days=%-4d n_months=%-3s mean_ic=%-9s t=%-8s pos=%s" % (
                        f, tag, v["n_days"], st.get("n_months"), st.get("mean_ic"),
                        st.get("t_month"), st.get("pos_months")))


main()
