"""T-219 step 4: β of the legacy rails (and QQQ/SPY) vs ① — the long ① NAV that the
card asks for — using the system's ONE sanctioned ① read path
(src/data/accounting/registry.core_nav: cap_pit24 history arm + cap_a1 + cap_a1_u).

Also: ① vs BTC (sanity anchor: crypto-vs-crypto correlation must be high, otherwise the
alignment convention is wrong) and ①'s own vol / drawdown per window.

Read-only. Writes docs/research/t219_core_beta.json.
"""
import asyncio, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from t219_db import DB

WINDOWS = {"from_2023-01": ("2023-01-01", "2026-11-02"),
           "from_2025-01": ("2025-01-01", "2026-11-02")}


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
        return {"n": n, "beta": None, "corr": None, "beta_t": None, "first": None, "last": None}
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
    return {"n": n, "beta": beta, "corr": r, "beta_t": t,
            "first": common[0], "last": common[-1]}


def maxdd(series):
    vals = [(d, v) for d, v in sorted(series.items()) if v is not None]
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


def ann_vol(x):
    n = len(x)
    if n < 2:
        return None
    m = sum(x) / n
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1)) * math.sqrt(252)


async def main():
    from src.data.accounting.registry import core_nav
    nav = await core_nav(start="2019-01-01")
    if nav is None:
        raise SystemExit("core_nav returned None")
    nav = nav.dropna().sort_index()
    nav_series = {ts.date().isoformat(): float(v) for ts, v in nav.items()}
    nav_rets = rets(nav_series)
    print("① nav points:", len(nav_series), nav_series and min(nav_series), "->", max(nav_series))

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

    out = {"nav_source": "registry.core_nav(cap_pit24<=2026-10-02 + cap_a1 + cap_a1_u)",
           "nav_points": len(nav_series),
           "nav_first": min(nav_series), "nav_last": max(nav_series),
           "windows": WINDOWS, "symbols": {}, "core_stats": {}}

    for wname, (ws, we) in WINDOWS.items():
        sub = {d: v for d, v in nav_series.items() if ws <= d <= we}
        rr = [v for d, v in rets(sub).items()]
        mdd, pk, tr = maxdd(sub)
        out["core_stats"][wname] = {
            "n_days": len(sub), "ann_vol_252": ann_vol(rr), "max_drawdown": mdd,
            "dd_peak": pk, "dd_trough": tr,
            "total_return": (sub[max(sub)] / sub[min(sub)] - 1.0) if sub else None,
        }

    for s in SYMS:
        row = {}
        for wname, (ws, we) in WINDOWS.items():
            src = pick(s, ws, we)
            if src is None:
                row[wname] = {"source": None}
                continue
            ser = {d: v for d, v in by_src[s][src].items() if ws <= d <= we}
            r = rets(ser)
            bc = beta_corr(r, nav_rets)
            row[wname] = {"source": src, "n_beta_vs_core": bc["n"],
                          "beta_vs_core": bc["beta"], "corr_vs_core": bc["corr"],
                          "beta_t": bc["beta_t"], "beta_window": [bc["first"], bc["last"]],
                          "ann_vol_252": ann_vol(list(r.values()))}
        row["vs_btc"] = {}
        for wname, (ws, we) in WINDOWS.items():
            src = pick(s, ws, we)
            bsrc = pick("BTC", ws, we)
            if src is None or bsrc is None:
                continue
            r = rets({d: v for d, v in by_src[s][src].items() if ws <= d <= we})
            rb = rets({d: v for d, v in by_src["BTC"][bsrc].items() if ws <= d <= we})
            bc = beta_corr(r, rb)
            row["vs_btc"][wname] = {"beta": bc["beta"], "corr": bc["corr"], "n": bc["n"]}
        out["symbols"][s] = row

    # sanity anchor: ① itself vs BTC (crypto vs crypto) — if this is not high, alignment is wrong
    for wname, (ws, we) in WINDOWS.items():
        sub = {d: v for d, v in nav_series.items() if ws <= d <= we}
        bsrc = pick("BTC", ws, we)
        rb = rets({d: v for d, v in by_src["BTC"][bsrc].items() if ws <= d <= we})
        bc = beta_corr(rets(sub), rb)
        out.setdefault("core_vs_btc", {})[wname] = {"beta": bc["beta"], "corr": bc["corr"], "n": bc["n"]}

    with open(os.path.join(HERE, "t219_core_beta.json"), "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print("\n① stats:")
    for wname in WINDOWS:
        c = out["core_stats"][wname]
        cb = out["core_vs_btc"][wname]
        print("  %-12s days=%4d vol=%5.1f%% dd=%6.1f%% ret=%7.1f%% | vs BTC beta=%5.2f corr=%5.3f n=%d"
              % (wname, c["n_days"], c["ann_vol_252"] * 100, c["max_drawdown"] * 100,
                 c["total_return"] * 100, cb["beta"], cb["corr"], cb["n"]))
    print("\nsym    | vs ① 2023 (beta / corr / t / n) | vs ① 2025 (beta / corr / t / n) | vs BTC 2023 (b / r)")
    for s in SYMS:
        r = out["symbols"][s]
        a, b = r["from_2023-01"], r["from_2025-01"]
        print("%-6s | %7s %6s %6s %5d | %7s %6s %6s %5d | %6s %6s" % (
            s,
            "%.3f" % a["beta_vs_core"] if a.get("beta_vs_core") is not None else "-",
            "%.3f" % a["corr_vs_core"] if a.get("corr_vs_core") is not None else "-",
            "%.2f" % a["beta_t"] if a.get("beta_t") is not None else "-",
            a.get("n_beta_vs_core") or 0,
            "%.3f" % b["beta_vs_core"] if b.get("beta_vs_core") is not None else "-",
            "%.3f" % b["corr_vs_core"] if b.get("corr_vs_core") is not None else "-",
            "%.2f" % b["beta_t"] if b.get("beta_t") is not None else "-",
            b.get("n_beta_vs_core") or 0,
            "%.3f" % r["vs_btc"]["from_2023-01"]["beta"] if r.get("vs_btc", {}).get("from_2023-01", {}).get("beta") is not None else "-",
            "%.3f" % r["vs_btc"]["from_2023-01"]["corr"] if r.get("vs_btc", {}).get("from_2023-01", {}).get("corr") is not None else "-"))


asyncio.run(main())
