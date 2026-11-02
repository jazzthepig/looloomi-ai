"""T-219 step 5: rail-ticker risk profile from the PUBLIC Nasdaq historical endpoint
(Nasdaq = the same issuer registry the card asks us to verify by issuer, and the same
source the previous round used for `info`).  Our own EODHD channel has NOT landed the
10 rail tickers yet (0 rows in ohlcv_daily / asset_mcap_daily / world50_mcap_weekly as of
2026-11-02 09:2x UTC) — so these numbers are labelled PUBLIC-SOURCE, not universe data.

Also: (a) the calibration — same five legacy rails computed from Nasdaq vs from our own
EODHD series, so the public-source bias is measured, not assumed;
    (b) M-585's panel length: how many months of panel the public source can support.

Read-only public GET + read-only SELECT. Writes docs/research/t219_public_profile.json
and docs/research/t219_nasdaq_raw.json.
"""
import asyncio, json, math, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from t219_db import DB

HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
LEG = ["V", "MA", "BLK", "IBKR", "SCHW"]
ETF = ["QQQ", "SPY"]

WINDOWS = {"from_2023-01": ("2023-01-01", "2026-11-02"),
           "from_2025-01": ("2025-01-01", "2026-11-02")}


def nasdaq_hist(sym, assetclass="stocks", frm="2023-01-01", to="2026-11-02", limit=1400):
    url = ("https://api.nasdaq.com/api/quote/" + sym + "/historical?assetclass=" + assetclass +
           "&fromdate=" + frm + "&todate=" + to + "&limit=" + str(limit))
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    rows = ((d.get("data") or {}).get("tradesTable") or {}).get("rows") or []
    out = {}
    for r in rows:
        dt = r.get("date")
        cl = r.get("close")
        if not dt or not cl or cl in ("N/A", "--"):
            continue
        cl = cl.replace("$", "").replace(",", "").strip()
        try:
            v = float(cl)
        except ValueError:
            continue
        mm, dd, yy = dt.split("/")
        iso = "%s-%s-%s" % (yy, mm, dd)
        out[iso] = v
    return out


def rets(series):
    out, prev = {}, None
    for d in sorted(series):
        v = series[d]
        if prev is not None:
            out[d] = v / prev - 1.0
        prev = v
    return out


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((v - ma) ** 2 for v in a))
    db = math.sqrt(sum((v - mb) ** 2 for v in b))
    return None if (da == 0 or db == 0) else num / (da * db)


def beta_corr(asset, bench):
    common = sorted(set(asset) & set(bench))
    n = len(common)
    if n < 3:
        return {"n": n, "beta": None, "corr": None, "beta_t": None}
    a = [asset[d] for d in common]
    b = [bench[d] for d in common]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (n - 1)
    vb = sum((v - mb) ** 2 for v in b) / (n - 1)
    r = pearson(a, b)
    beta = cov / vb if vb else None
    t = None
    if r is not None and n > 2 and abs(r) < 1.0:
        t = r * math.sqrt(n - 2) / math.sqrt(1.0 - r * r)
    return {"n": n, "beta": beta, "corr": r, "beta_t": t}


def ann_vol(x):
    n = len(x)
    if n < 2:
        return None
    m = sum(x) / n
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1)) * math.sqrt(252)


def maxdd(series):
    vals = sorted((d, v) for d, v in series.items() if v is not None)
    if not vals:
        return None, None, None
    peak, peak_d, mdd, trough_d = vals[0][1], vals[0][0], 0.0, vals[0][0]
    for d, v in vals:
        if v > peak:
            peak, peak_d = v, d
        dd = v / peak - 1.0
        if dd < mdd:
            mdd, trough_d = dd, d
    return mdd, peak_d, trough_d


async def main():
    from src.data.accounting.registry import core_nav
    nav = await core_nav(start="2019-01-01")
    nav = nav.dropna().sort_index()
    nav_series = {ts.date().isoformat(): float(v) for ts, v in nav.items()}
    nav_rets = rets(nav_series)

    db = DB()
    DB_SYMS = LEG + ETF + ["BTC"]
    by_src = {}
    for s in DB_SYMS:
        rows = db.all("ohlcv_daily", select="symbol,trade_date,source,close",
                      order="trade_date.asc", filters={"symbol": "eq." + s},
                      limit=1000, max_rows=200000)
        d = {}
        for r in rows:
            if r["close"] is None:
                continue
            d.setdefault(r["source"], {})[r["trade_date"]] = float(r["close"])
        by_src[s] = d

    def pick(sym, start, end):
        best, best_key = None, None
        for src, ser in by_src[sym].items():
            ds = [d for d in ser if start <= d <= end]
            if not ds:
                continue
            key = (len(ds), max(ds))
            if best_key is None or key > best_key:
                best, best_key = src, key
        return best

    btc_src = pick("BTC", "2023-01-01", "2026-11-02")
    btc = by_src["BTC"][btc_src]
    btc_rets = rets(btc)
    print("BTC source:", btc_src, "n=", len(btc))

    # ---- fetch public data ----
    raw = {}
    for s in RAIL + LEG:
        try:
            raw[s] = nasdaq_hist(s)
            print("nasdaq %-6s n=%d %s..%s" % (s, len(raw[s]),
                                               min(raw[s]) if raw[s] else "-",
                                               max(raw[s]) if raw[s] else "-"))
        except Exception as e:
            raw[s] = {}
            print("nasdaq %-6s ERR %s" % (s, str(e)[:120]))
        time.sleep(0.8)
    for s in ETF:
        try:
            raw[s] = nasdaq_hist(s, assetclass="etf")
            print("nasdaq %-6s (etf) n=%d %s..%s" % (s, len(raw[s]),
                                                     min(raw[s]) if raw[s] else "-",
                                                     max(raw[s]) if raw[s] else "-"))
        except Exception as e:
            raw[s] = {}
            print("nasdaq %-6s (etf) ERR %s" % (s, str(e)[:120]))
        time.sleep(0.8)

    with open(os.path.join(HERE, "t219_nasdaq_raw.json"), "w") as f:
        json.dump({"fetched_at_utc": "2026-11-02", "source": "api.nasdaq.com/api/quote/<S>/historical",
                   "series": raw}, f, indent=1)

    out = {"source": "api.nasdaq.com historical (PUBLIC, unadjusted close)",
           "fetched_at_utc": "2026-11-02 ~09:4x UTC",
           "windows": WINDOWS, "symbols": {}, "calibration": {}}

    def profile(ser, label):
        row = {}
        wins = dict(WINDOWS)
        wins["full"] = (min(ser), max(ser)) if ser else None
        for wname, (ws, we) in wins.items():
            if not ser:
                row[wname] = {"n_days": 0}
                continue
            sub = {d: v for d, v in ser.items() if ws <= d <= we}
            r = rets(sub)
            ds = sorted(r)
            mdd, pk, tr = maxdd(sub)
            bc = beta_corr(r, btc_rets)
            bn = beta_corr(r, nav_rets)
            row[wname] = {
                "n_days": len(sub), "first": min(sub) if sub else None,
                "last": max(sub) if sub else None,
                "ann_vol_252": ann_vol(list(r.values())), "max_drawdown": mdd,
                "dd_peak": pk, "dd_trough": tr,
                "total_return": (sub[max(sub)] / sub[min(sub)] - 1.0) if sub else None,
                "beta_vs_btc": bc["beta"], "corr_vs_btc": bc["corr"], "n_beta_btc": bc["n"],
                "beta_t_vs_btc": bc["beta_t"],
                "beta_vs_core": bn["beta"], "corr_vs_core": bn["corr"], "n_beta_core": bn["n"],
                "beta_t_vs_core": bn["beta_t"],
            }
        return row

    for s in RAIL:
        out["symbols"][s] = profile(raw.get(s, {}), s)

    # ---- calibration: nasdaq vs our EODHD series on the legacy rails ----
    for s in LEG + ETF:
        src = pick(s, "2023-01-01", "2026-11-02")
        eod = {d: v for d, v in by_src[s][src].items()} if src else {}
        nq = raw.get(s, {})
        common = sorted(set(eod) & set(nq))
        if len(common) < 30:
            out["calibration"][s] = {"n_common": len(common), "note": "too few common days"}
            continue
        re_e = rets({d: eod[d] for d in common})
        re_n = rets({d: nq[d] for d in common})
        common_r = sorted(set(re_e) & set(re_n))
        a = [re_e[d] for d in common_r]
        b = [re_n[d] for d in common_r]
        pn = profile({d: nq[d] for d in common}, s)
        pe = profile({d: eod[d] for d in common}, s)
        out["calibration"][s] = {
            "eodhd_source": src, "n_common_days": len(common_r),
            "daily_return_corr": pearson(a, b),
            "nasdaq_ann_vol": pn["full"]["ann_vol_252"], "eodhd_ann_vol": pe["full"]["ann_vol_252"],
            "nasdaq_maxdd": pn["full"]["max_drawdown"], "eodhd_maxdd": pe["full"]["max_drawdown"],
            "nasdaq_total_return": pn["full"]["total_return"], "eodhd_total_return": pe["full"]["total_return"],
            "nasdaq_beta_btc": pn["full"]["beta_vs_btc"], "eodhd_beta_btc": pe["full"]["beta_vs_btc"],
            "nasdaq_beta_core": pn["full"]["beta_vs_core"], "eodhd_beta_core": pe["full"]["beta_vs_core"],
        }

    # ---- M-585 panel length from the public source ----
    firsts = {s: (min(raw[s]) if raw.get(s) else None) for s in RAIL}
    panel_last = max(v for v in firsts.values() if v)
    # rule: a name joins a window only if it already has >=60 trading days of history at the window start
    all_days = sorted({d for s in RAIL for d in raw.get(s, {})})
    panel_start = None
    for d in all_days:
        if all(d in raw[s] and sum(1 for x in raw[s] if x <= d) >= 60 for s in RAIL):
            panel_start = d
            break
    months = 0
    if panel_start:
        for d in all_days:
            if d >= panel_start:
                months += 1
        # count distinct months
        ms = sorted({d[:7] for d in all_days if d >= panel_start})
        months = len(ms)
    out["m585_panel"] = {"first_dates": firsts, "panel_start_if_all_10_qualify": panel_start,
                         "panel_months_available": months,
                         "last_common_date": min(max(raw[s]) for s in RAIL if raw.get(s)),
                         "note": "M-585 rule: a name joins only with >=60 trading days of history at window start"}

    with open(os.path.join(HERE, "t219_public_profile.json"), "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # ---- print ----
    print("\n=== rail tickers (PUBLIC source, unadjusted close) ===")
    print("%-6s %-14s %5s %6s %7s %8s %8s %6s %6s" % (
        "sym", "window", "days", "vol%", "maxDD%", "ret%", "b(BTC)", "r(BTC)", "b(①)"))
    for s in RAIL:
        for wname in ["from_2023-01", "from_2025-01", "full"]:
            w = out["symbols"][s][wname]
            if not w.get("n_days"):
                print("%-6s %-14s (no data)" % (s, wname))
                continue
            print("%-6s %-14s %5d %6.1f %7.1f %8.1f %8.3f %6.3f %6.3f" % (
                s, wname, w["n_days"], w["ann_vol_252"] * 100, w["max_drawdown"] * 100,
                w["total_return"] * 100, w["beta_vs_btc"] or 0, w["corr_vs_btc"] or 0,
                w["beta_vs_core"] or 0))
    print("\n=== calibration: nasdaq vs our EODHD (legacy rails) ===")
    for s, c in out["calibration"].items():
        if c.get("n_common_days", 0) < 30:
            print("%-6s %s" % (s, c))
            continue
        print("%-6s n=%4d  dret_corr=%.4f | vol nq %.1f%% vs eod %.1f%% | dd nq %.1f%% vs eod %.1f%% | "
              "ret nq %.1f%% vs eod %.1f%% | b(BTC) nq %.3f vs eod %.3f | b(①) nq %.3f vs eod %.3f" % (
            s, c["n_common_days"], c["daily_return_corr"], c["nasdaq_ann_vol"] * 100,
            c["eodhd_ann_vol"] * 100, c["nasdaq_maxdd"] * 100, c["eodhd_maxdd"] * 100,
            c["nasdaq_total_return"] * 100, c["eodhd_total_return"] * 100,
            c["nasdaq_beta_btc"], c["eodhd_beta_btc"], c["nasdaq_beta_core"], c["eodhd_beta_core"]))
    print("\n=== M-585 panel (public source) ===")
    print(json.dumps(out["m585_panel"], indent=1, ensure_ascii=False)[:1200])


asyncio.run(main())
