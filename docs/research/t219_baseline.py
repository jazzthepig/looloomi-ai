"""T-219 step 3: legacy-rail baseline risk profile (V/MA/BLK/IBKR/SCHW) vs BTC and vs ① (cap_a1_u).

Source selection: per symbol per window, the source with the most rows inside the window
(tie-break: later last date). Deterministic, no hand-picking.
Writes docs/research/t219_baseline_results.json.
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t219_db import DB
from collections import Counter

db = DB()
SYMS = ["V", "MA", "BLK", "IBKR", "SCHW", "QQQ", "SPY", "BTC"]

by_src = {}
for s in SYMS:
    rows = db.all("ohlcv_daily", select="symbol,trade_date,source,close",
                  order="trade_date.asc", filters={"symbol": "eq." + s},
                  limit=1000, max_rows=200000)
    d = {}
    for r in rows:
        if r["close"] is None:
            continue
        d.setdefault(r["source"], {})[r["trade_date"]] = float(r["close"])
    by_src[s] = d
    print("%-6s rows=%5d sources=%s" % (s, len(rows), {k: len(v) for k, v in d.items()}))

nav_rows = db.all("core_cap_daily", select="d,arm,nav", order="d.asc",
                  filters={"arm": "eq.cap_a1_u"}, limit=1000, max_rows=100000)
nav = {r["d"]: float(r["nav"]) for r in nav_rows if r["nav"] is not None}


def pick_source(sym, start, end):
    best, best_key = None, None
    for src, ser in by_src[sym].items():
        ds = [d for d in ser if start <= d <= end]
        if not ds:
            continue
        key = (len(ds), max(ds))
        if best_key is None or key > best_key:
            best, best_key = src, key
    return best


def rets(series):
    out = {}
    prev = None
    for d in sorted(series):
        v = series[d]
        if prev is not None:
            out[d] = v / prev - 1.0
        prev = v
    return out


def stats(x):
    n = len(x)
    if n < 2:
        return None
    m = sum(x) / n
    return {"n": n, "mean": m, "std": math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))}


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
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
    vb = sum((b[i] - mb) ** 2 for i in range(n)) / (n - 1)
    r = pearson(a, b)
    beta = (cov / vb if vb else None)
    # slope t-stat: t = r * sqrt(n-2) / sqrt(1-r^2)   (== beta / se_beta)
    t = None
    if r is not None and n > 2 and r * r < 1.0:
        t = r * math.sqrt(n - 2) / math.sqrt(1.0 - r * r)
    return {"n": n, "beta": beta, "corr": r, "beta_t": t}


def maxdd(series, start, end):
    vals = [(d, series[d]) for d in sorted(series) if start <= d <= end]
    if not vals:
        return None, None, None
    cur_peak, peak_d, mdd, trough_d = vals[0][1], vals[0][0], 0.0, vals[0][0]
    for d, v in vals:
        if v > cur_peak:
            cur_peak, peak_d = v, d
        dd = v / cur_peak - 1.0
        if dd < mdd:
            mdd, trough_d = dd, d
    return mdd, peak_d, trough_d


WINDOWS = {"from_2023-01": ("2023-01-01", "2026-11-01"),
           "from_2025-01": ("2025-01-01", "2026-11-01")}

out = {"generated_at_utc": "2026-11-02", "symbols": {}, "windows": WINDOWS,
       "nav_arm": "cap_a1_u", "nav_points": len(nav),
       "notes": ["source per symbol/window = most rows inside window (tie: later last date)",
                 "ann_vol uses sqrt(252); maxdd on raw close series",
                 "beta vs BTC: equity trading days, BTC return on the same calendar date"]}

nav_rets = rets(nav)

for s in ["V", "MA", "BLK", "IBKR", "SCHW", "QQQ", "SPY"]:
    sym_out = {}
    for wname, (ws, we) in WINDOWS.items():
        src = pick_source(s, ws, we)
        ser = {d: v for d, v in by_src[s][src].items() if ws <= d <= we}
        r = rets(ser)
        btc_src = pick_source("BTC", ws, we)
        btc_ser = {d: v for d, v in by_src["BTC"][btc_src].items() if ws <= d <= we}
        bc = beta_corr(r, rets(btc_ser))
        st = stats(list(r.values()))
        mdd, pk, tr = maxdd(by_src[s][src], ws, we)
        dates = sorted(r)
        sym_out[wname] = {
            "source": src, "btc_source": btc_src,
            "n_days": len(r),
            "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
            "ann_vol_252": (st["std"] * math.sqrt(252)) if st else None,
            "max_drawdown": mdd, "dd_peak": pk, "dd_trough": tr,
            "beta_vs_btc": bc["beta"], "corr_vs_btc": bc["corr"], "n_beta": bc["n"],
            "beta_t": bc["beta_t"],
            "total_return": (ser[dates[-1]] / ser[dates[0]] - 1.0) if dates else None,
        }
    bc_nav = beta_corr(rets(by_src[s][pick_source(s, "2026-10-12", "2026-11-01")]), nav_rets)
    common = sorted(set(rets(by_src[s][pick_source(s, "2026-10-12", "2026-11-01")])) & set(nav_rets))
    sym_out["vs_cap_a1_u"] = {"n": bc_nav["n"], "beta": bc_nav["beta"], "corr": bc_nav["corr"],
                              "window": [min(common), max(common)] if common else None}
    out["symbols"][s] = sym_out

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "t219_baseline_results.json"), "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

hdr = "%-6s | %-30s | %-30s | vs ① (21d)" % ("sym", "from 2023-01", "from 2025-01")
print("\n" + hdr)
for s in out["symbols"]:
    a = out["symbols"][s]["from_2023-01"]
    b = out["symbols"][s]["from_2025-01"]
    c = out["symbols"][s]["vs_cap_a1_u"]
    print("%-6s | vol %5s%% dd %6s%% b %6s r %6s n%4d | vol %5s%% dd %6s%% b %6s r %6s n%4d | b %6s r %6s n%3d"
          % (s,
             "%.1f" % (a["ann_vol_252"] * 100) if a["ann_vol_252"] else "-",
             "%.1f" % (a["max_drawdown"] * 100) if a["max_drawdown"] is not None else "-",
             "%.3f" % a["beta_vs_btc"] if a["beta_vs_btc"] is not None else "-",
             "%.3f" % a["corr_vs_btc"] if a["corr_vs_btc"] is not None else "-", a["n_beta"],
             "%.1f" % (b["ann_vol_252"] * 100) if b["ann_vol_252"] else "-",
             "%.1f" % (b["max_drawdown"] * 100) if b["max_drawdown"] is not None else "-",
             "%.3f" % b["beta_vs_btc"] if b["beta_vs_btc"] is not None else "-",
             "%.3f" % b["corr_vs_btc"] if b["corr_vs_btc"] is not None else "-", b["n_beta"],
             "%.3f" % c["beta"] if c["beta"] is not None else "-",
             "%.3f" % c["corr"] if c["corr"] is not None else "-", c["n"]))
    print("        src=%s btc_src=%s  %s->%s  ret23 %s  ret25 %s"
          % (a["source"], a["btc_source"], a["first"], a["last"],
             "%.1f%%" % (a["total_return"] * 100) if a["total_return"] else "-",
             "%.1f%%" % (b["total_return"] * 100) if b["total_return"] else "-"))
