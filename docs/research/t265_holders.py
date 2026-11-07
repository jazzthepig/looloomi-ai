#!/usr/bin/env python3
"""T-265 / S-743 — 持有人数增长(采用面)对之后 4 周相对 BTC 的超额,横截面周频。

口径逐字照 REFUTATION_LEDGER S-743 预注册段(2026-11-06 08:36 UTC):
  样本  每周一 t;宇宙 = 当周市值前 200 且持有人序列在 t-28 与 t 都有点(相差 <= 7 天)、
        上市满 26 周;去掉稳定币/包装/质押衍生(价格相对 BTC 或 ETH 或 1 美元的 90 天波动 < 1%)。
  特征  g = ln(H_t / H_{t-28});|g| > 1 丢弃;g_res = g 对「过去 4 周对数收益」与「ln 市值」
        的横截面秩回归残差(每周单独回归)。
  结果  t -> t+28 相对 BTC 的对数超额;BTC 基准 = ohlcv_daily(binance_hist,§Seth-1106m 第 2 条)。
  判据  (a) 每周横截面 Spearman IC(g_res, 超额)均值 > 0 且按周 t >= 2.0(Newey-West 4 阶);
        (b) 前五分之一减后五分之一平均 4 周超额 >= +1.5%;
        (c) 零分布:每周内打乱 g_res(1,000 次,种子 743),实际均值 IC 分位 >= 0.95;
        (d) 两段(按样本周数对半)同号。

用法:
  python3 t265_holders.py fetch                 # 抓数据到 Mac 数据根
  python3 t265_holders.py run                   # 算 (a)-(d) + 副项
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("FATAL: SUPABASE_URL / SUPABASE_KEY not in env")

OUT_DIR = "/Volumes/CometCloudAI/cometcloud-local/research/t265"
D_START = "2024-06-01"          # 取样所需的最小日期(90 天波动窗 + 26 周上市 + 4 周回看)
HDRS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Accept": "application/json",
}


# ---------------------------------------------------------------- http helpers
def get(path, params=None, count=False, retries=4):
    q = dict(params or {})
    qs = urllib.parse.urlencode(q, doseq=True)
    url = f"{URL}/rest/v1/{path}" + (f"?{qs}" if qs else "")
    headers = dict(HDRS)
    if count:
        headers["Prefer"] = "count=exact"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read()
                total = r.headers.get("Content-Range")
            rows = json.loads(body) if body else []
            n = None
            if total and "/" in total:
                try:
                    n = int(total.split("/")[-1])
                except ValueError:
                    n = None
            return rows, n
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:200]!r}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed: {last}")


def get_all(path, params=None, order=None, page=1000, label=""):
    """Fetch every row, one page at a time, always with order= (PostgREST boundary rule)."""
    base = dict(params or {})
    if order:
        base["order"] = order
    rows, total = get(path, {**base, "limit": page, "offset": 0}, count=True)
    out = list(rows)
    if total is not None:
        print(f"  {label}: total={total}", flush=True)
    while len(out) < (total or 0):
        more, _ = get(path, {**base, "limit": page, "offset": len(out)})
        if not more:
            break
        out.extend(more)
        if label and len(out) % 50000 < page:
            print(f"  {label}: {len(out)}/{total}", flush=True)
    return out


# ------------------------------------------------------------------- fetch
def cmd_fetch():
    os.makedirs(OUT_DIR, exist_ok=True)
    log = open(os.path.join(OUT_DIR, "fetch2.log"), "w")

    def say(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    def dump(name, rows):
        p = os.path.join(OUT_DIR, name)
        with open(p, "w") as f:
            json.dump(rows, f)
        say(f"  wrote {name}: rows={len(rows)}")

    say("=== fetch token_holders_daily ===")
    h = get_all(
        "token_holders_daily",
        {"select": "coin_id,d,holders,granularity,network,address", "order": "coin_id.asc,d.asc"},
        order="coin_id.asc,d.asc", label="holders",
    )
    dump("holders.json", h)
    if h:
        say(f"  holders coins={len({r.get('coin_id') for r in h})} "
            f"d=[{min(r['d'] for r in h)}..{max(r['d'] for r in h)}]")

    say("=== fetch token_holders_coverage ===")
    cov = get_all(
        "token_holders_coverage",
        {"select": "coin_id,min_d,max_d,n,n_weekly", "order": "coin_id.asc"},
        order="coin_id.asc", label="coverage",
    )
    dump("coverage.json", cov)
    if cov:
        nw = [int(r.get("n_weekly") or 0) for r in cov]
        say(f"  coverage coins={len(cov)} n_weekly>=52: {sum(1 for v in nw if v >= 52)} "
            f"n_weekly>=26: {sum(1 for v in nw if v >= 26)}")

    say("=== fetch cg_coin_mcap_daily ===")
    p = get_all(
        "cg_coin_mcap_daily",
        {"select": "coin_id,d,mcap,price", "order": "coin_id.asc,d.asc", "d": f"gte.{D_START}"},
        order="coin_id.asc,d.asc", label="cg_mcap",
    )
    dump("cg_mcap.json", p)

    say("=== fetch asset_mcap_daily ===")
    a = get_all(
        "asset_mcap_daily",
        {"select": "coin_id,d,mcap,price,symbol", "order": "coin_id.asc,d.asc", "d": f"gte.{D_START}"},
        order="coin_id.asc,d.asc", label="asset_mcap",
    )
    dump("asset_mcap.json", a)

    say("=== fetch ohlcv_daily (BTC/ETH, binance_hist) ===")
    b = get_all(
        "ohlcv_daily",
        {"select": "symbol,trade_date,close,source",
         "order": "symbol.asc,trade_date.asc",
         "source": "eq.binance_hist", "symbol": "in.(BTC,ETH)"},
        order="symbol.asc,trade_date.asc", label="bench",
    )
    dump("bench_ohlcv.json", b)
    say("fetch DONE")
    log.close()


def cmd_fetch_early():
    """补抓 D_START 之前的历史(为了「上市满 26 周」与 90 天波动窗不被抓取窗口截断)。"""
    p = get_all(
        "cg_coin_mcap_daily",
        {"select": "coin_id,d,mcap,price", "order": "coin_id.asc,d.asc", "d": f"lt.{D_START}"},
        order="coin_id.asc,d.asc", label="cg_early",
    )
    a = get_all(
        "asset_mcap_daily",
        {"select": "coin_id,d,mcap,price,symbol", "order": "coin_id.asc,d.asc", "d": f"lt.{D_START}"},
        order="coin_id.asc,d.asc", label="asset_early",
    )
    for name, rows in (("cg_mcap.json", p), ("asset_mcap.json", a)):
        path = os.path.join(OUT_DIR, name)
        cur = json.load(open(path))
        have = {(r["coin_id"], r["d"]) for r in cur}
        add = [r for r in rows if (r["coin_id"], r["d"]) not in have]
        cur.extend(add)
        cur.sort(key=lambda r: (r["coin_id"], r["d"]))
        with open(path, "w") as f:
            json.dump(cur, f)
        print(f"{name}: +{len(add)} -> {len(cur)} rows")


# ------------------------------------------------------------------- analysis
def _load_apparatus():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.abspath(os.path.join(here, "..", "..", "src", "data", "evaluation", "apparatus.py"))
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_run():
    import bisect
    import math
    from datetime import date, timedelta
    import numpy as np
    from scipy.stats import spearmanr

    ap = _load_apparatus()
    D = OUT_DIR
    for f in ["holders.json", "coverage.json", "cg_mcap.json", "bench_ohlcv.json"]:
        if not os.path.exists(os.path.join(D, f)):
            sys.exit(f"FATAL: missing {f} — run fetch first")

    def _load(name, default=None):
        p = os.path.join(D, name)
        if not os.path.exists(p):
            if default is None:
                sys.exit(f"FATAL: missing {name} — run fetch first")
            print(f"WARN: {name} missing — using empty", flush=True)
            return []
        return json.load(open(p))

    holders = _load("holders.json")
    cg = _load("cg_mcap.json")
    asset = _load("asset_mcap.json", default=[])
    for extra, target in [("cg_mcap_early.json", cg), ("asset_mcap_early.json", asset),
                          ("asset_mcap_onlyholders.json", asset), ("asset_mcap_mondays.json", asset)]:
        p = os.path.join(D, extra)
        if os.path.exists(p):
            rows = json.load(open(p))
            have = {(r["coin_id"], r["d"]) for r in target}
            target.extend([r for r in rows if (r["coin_id"], r["d"]) not in have])
            print(f"merged {extra}: +{len(rows)} rows -> {len(target)}", flush=True)
    bench = json.load(open(os.path.join(D, "bench_ohlcv.json")))
    coverage = json.load(open(os.path.join(D, "coverage.json")))

    # ---------- merge price / mcap (union universe, §Seth-1106n) ----------
    merged = {}
    for r in cg:
        merged.setdefault(r["coin_id"], {})[r["d"]] = [r.get("mcap"), r.get("price")]
    n_disagree = 0
    n_asset_only = 0
    for r in asset:
        c, dd = r["coin_id"], r["d"]
        cur = merged.setdefault(c, {})
        am, ap_ = r.get("mcap"), r.get("price")
        if dd in cur:
            cm, cp = cur[dd]
            if cm is None and am is not None:
                cur[dd][0] = am
            elif cp is None and ap_ is not None:
                cur[dd][1] = ap_
            elif cm is not None and am is not None and abs(cm - am) > 1e-6 * max(1.0, abs(cm)):
                n_disagree += 1
        else:
            cur[dd] = [am, ap_]
            n_asset_only += 1

    PXS, MCS = {}, {}
    for c, dd in merged.items():
        ds = sorted(dd.keys())
        px = [(d, dd[d][1]) for d in ds if dd[d][1] is not None and dd[d][1] > 0]
        if px:
            PXS[c] = ([p[0] for p in px], [p[1] for p in px])
        mc = [(d, dd[d][0]) for d in ds if dd[d][0] is not None]
        if mc:
            MCS[c] = ([m[0] for m in mc], [m[1] for m in mc])

    # ---------- benchmark: ohlcv_daily / binance_hist ----------
    BENCH = {}
    for r in bench:
        if r.get("close") is None:
            continue
        BENCH.setdefault(r["symbol"], []).append((r["trade_date"], float(r["close"])))
    for s in BENCH:
        BENCH[s].sort()
        seen = {}
        for d, v in BENCH[s]:
            seen[d] = v
        ds = sorted(seen)
        BENCH[s] = (ds, [seen[d] for d in ds])

    # ---------- holders ----------
    by_coin = {}
    for r in holders:
        key = (r.get("network"), r.get("address"))
        by_coin.setdefault(r["coin_id"], {}).setdefault(key, []).append((r["d"], r["holders"]))
    H = {}
    for c, sers in by_coin.items():
        lst = []
        for (net, addr), pts in sers.items():
            pts = sorted((d, float(v)) for d, v in pts if v is not None)
            if pts:
                lst.append({"net": net, "addr": addr, "d": [p[0] for p in pts], "v": [p[1] for p in pts]})
        if lst:
            lst.sort(key=lambda s: (-len(s["d"]), s["d"][0], str(s["net"])))
            H[c] = lst
    n_multi = sum(1 for c, s in H.items() if len(s) > 1)

    def holder_at(c, dstr, mode="primary"):
        sers = H.get(c)
        if not sers:
            return None
        if mode == "primary":
            s = sers[0]
            i = bisect.bisect_right(s["d"], dstr) - 1
            if i < 0:
                return None
            gap = (date.fromisoformat(dstr) - date.fromisoformat(s["d"][i])).days
            if gap > 7:
                return None
            return s["v"][i]
        tot, ok = 0.0, True
        for s in sers:
            i = bisect.bisect_right(s["d"], dstr) - 1
            if i < 0:
                ok = False
                break
            if (date.fromisoformat(dstr) - date.fromisoformat(s["d"][i])).days > 7:
                ok = False
                break
            tot += s["v"][i]
        return tot if ok else None

    def last_on_or_before(c, dstr, max_gap=7):
        px = PXS.get(c)
        if not px:
            return None
        ds, vs = px
        i = bisect.bisect_right(ds, dstr) - 1
        if i < 0:
            return None
        if (date.fromisoformat(dstr) - date.fromisoformat(ds[i])).days > max_gap:
            return None
        return vs[i]

    def mcap_at(c, dstr, max_gap=7):
        mc = MCS.get(c)
        if not mc:
            return None
        ds, vs = mc
        i = bisect.bisect_right(ds, dstr) - 1
        if i < 0:
            return None
        if (date.fromisoformat(dstr) - date.fromisoformat(ds[i])).days > max_gap:
            return None
        return vs[i]

    # bench close helper
    def bench_close(sym, dstr):
        b = BENCH.get(sym)
        if not b:
            return None
        ds, vs = b
        i = bisect.bisect_right(ds, dstr) - 1
        if i < 0:
            return None
        if (date.fromisoformat(dstr) - date.fromisoformat(ds[i])).days > 2:
            return None
        return vs[i]

    # ---------- 90 天「相对 BTC / ETH / 1 美元」的波动 ----------
    def track_vol(c, tstr):
        """返回 min(std(日收益差)) over {BTC, ETH, USD};点数不足 ⇒ None。"""
        px = PXS.get(c)
        if not px:
            return None
        ds, vs = px
        i = bisect.bisect_right(ds, tstr) - 1
        if i < 60:
            return None
        window = list(range(max(1, i - 90), i + 1))
        rc, rb, re_ = [], [], []
        prev_b = prev_e = None
        for j in window:
            d, p = ds[j], vs[j]
            p_prev = vs[j - 1]
            if p_prev <= 0 or p <= 0:
                continue
            r = math.log(p / p_prev)
            cb = bench_close("BTC", d)
            ce = bench_close("ETH", d)
            if prev_b is not None and cb is not None and prev_b > 0:
                rb.append(r - math.log(cb / prev_b))
            if prev_e is not None and ce is not None and prev_e > 0:
                re_.append(r - math.log(ce / prev_e))
            rc.append(r)
            prev_b = cb if cb is not None else prev_b
            prev_e = ce if ce is not None else prev_e
        if len(rc) < 60:
            return None
        out = []
        for arr in (rc, rb, re_):
            if len(arr) >= 60:
                out.append(float(np.std(np.array(arr), ddof=1)))
        return min(out) if out else None

    # ---------- 样本周(每周一) ----------
    hmin = min(r["d"] for r in holders)
    hmax = max(r["d"] for r in holders)
    d0 = date.fromisoformat(hmin)
    weeks = []
    cur = d0 + timedelta(days=(7 - d0.weekday()) % 7)
    while cur <= date.fromisoformat(hmax):
        weeks.append(cur.isoformat())
        cur += timedelta(days=7)

    # ---------- 主循环 ----------
    drops = {"no_holder": 0, "jump": 0, "no_price": 0, "young": 0, "stable": 0, "no_future": 0, "outside_top200": 0}
    weekly = []          # 每周的记录
    for t in weeks:
        t28 = (date.fromisoformat(t) - timedelta(days=28)).isoformat()
        t56 = (date.fromisoformat(t) - timedelta(days=56)).isoformat()
        tf28 = (date.fromisoformat(t) + timedelta(days=28)).isoformat()
        tf56 = (date.fromisoformat(t) + timedelta(days=56)).isoformat()
        # 当周市值前 200 —— 两个口径:合并宇宙(§Seth-1106n)与只算 cg_coin_mcap_daily(预注册字面)
        mc_all = []
        for c in MCS:
            v = mcap_at(c, t)
            if v is not None:
                mc_all.append((v, c))
        mc_all.sort(reverse=True)
        top200 = {c for _, c in mc_all[:200]}
        recs = []
        for c in H:
            ht = holder_at(c, t)
            h28 = holder_at(c, t28)
            if ht is None or h28 is None or ht <= 0 or h28 <= 0:
                drops["no_holder"] += 1
                continue
            g = math.log(ht / h28)
            if abs(g) > 1:
                drops["jump"] += 1
                continue
            pt = last_on_or_before(c, t)
            p28 = last_on_or_before(c, t28)
            if pt is None or p28 is None or p28 <= 0:
                drops["no_price"] += 1
                continue
            first = PXS[c][0][0]
            if (date.fromisoformat(t) - date.fromisoformat(first)).days < 182:
                drops["young"] += 1
                continue
            tv = track_vol(c, t)
            if tv is not None and tv < 0.01:
                drops["stable"] += 1
                continue
            pf = last_on_or_before(c, tf28)
            if pf is None:
                drops["no_future"] += 1
                continue
            if c not in top200:
                drops["outside_top200"] += 1
                continue
            mc = mcap_at(c, t)
            if mc is None or mc <= 0:
                continue
            recs.append({
                "week": t, "coin": c, "g": g,
                "r4w": math.log(pt / p28),
                "lnmcap": math.log(mc),
                "px_t": pt, "px_t28": p28, "px_t28f": pf,
                "net": H[c][0]["net"],
            })
        if len(recs) >= 5:
            weekly.append(recs)

    out = {"meta": {}, "weekly": {}, "a_b_c_d": {}, "secondary": {}, "diag": {}}
    out["meta"] = {
        "holders_coverage_coins": len(coverage),
        "coverage_n_weekly_ge_52": sum(1 for r in coverage if int(r.get("n_weekly") or 0) >= 52),
        "coverage_n_weekly_ge_26": sum(1 for r in coverage if int(r.get("n_weekly") or 0) >= 26),
        "holders_rows": len(holders), "holders_coins": len(H),
        "holders_d_min": hmin, "holders_d_max": hmax,
        "price_coins": len(PXS), "mcap_coins": len(MCS),
        "merged_mcap_disagreements": n_disagree, "asset_only_rows": n_asset_only,
        "coins_with_multiple_chain_series": n_multi,
        "weeks_total": len(weeks), "weeks_used": len(weekly),
        "drops": drops,
        "universe_top_n": 200,
    }

    # ---------- 特征:g_res(每周单独横截面秩回归) ----------
    def build_features(recs, use_residual=True):
        y = np.array([r["g"] for r in recs], dtype=float)
        X = np.array([[r["r4w"], r["lnmcap"]] for r in recs], dtype=float)
        def rank01(v):
            from scipy.stats import rankdata
            rk = rankdata(v).astype(float)
            sd = rk.std()
            return (rk - rk.mean()) / (sd if sd > 0 else 1.0)
        R = np.column_stack([rank01(X[:, 0]), rank01(X[:, 1])])
        if not use_residual:
            return y
        A = np.column_stack([np.ones(len(y)), R])
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        return y - A @ beta

    def weekly_ic(recs, key="gres"):
        out = []
        for wk in weeks:
            rr = [r for r in recs if r["week"] == wk]
            if len(rr) < 5:
                continue
            x = np.array([r[key] for r in rr], dtype=float)
            e = np.array([r["excess"] for r in rr], dtype=float)
            if np.std(x) == 0 or np.std(e) == 0:
                continue
            rho = spearmanr(x, e).statistic
            if not np.isnan(rho):
                out.append((wk, len(rr), float(rho)))
        return out

    def nw_t(x, lags=4):
        x = np.asarray(x, dtype=float)
        n = len(x)
        d = x - x.mean()
        var = (d @ d) / n
        for l in range(1, lags + 1):
            gl = (d[l:] @ d[:-l]) / n
            var += 2.0 * (1.0 - l / (lags + 1.0)) * gl
        se = math.sqrt(max(var, 1e-24) / n)
        return float(x.mean() / se), float(x.mean()), float(se)

    def evaluate(records, label):
        """records: list of dicts with week/gres/excess —— 跑 (a)-(d)。"""
        ics = weekly_ic(records)
        if not ics:
            return None
        wk = [i[0] for i in ics]
        rho = np.array([i[2] for i in ics])
        n_per = np.array([i[1] for i in ics])
        t_stat, mean_ic, se = nw_t(rho, lags=4)
        # (b) 五分位
        pooled_top, pooled_bot, per_week_spread = [], [], []
        raw_top, raw_bot = [], []
        for w in weeks:
            rr = [r for r in records if r["week"] == w]
            if len(rr) < 5:
                continue
            rr = sorted(rr, key=lambda r: r["gres"])
            n = len(rr)
            k = max(1, n // 5)
            top = rr[-k:]
            bot = rr[:k]
            pooled_top.extend(r["excess"] for r in top)
            pooled_bot.extend(r["excess"] for r in bot)
            per_week_spread.append(float(np.mean([r["excess"] for r in top]) -
                                       np.mean([r["excess"] for r in bot])))
            for r in top:
                lr = ap.long_return(r["px_t"], r["px_t28f"])
                if lr is not None:
                    raw_top.append(lr)
            for r in bot:
                sr = ap.short_return(r["px_t"], r["px_t28f"])
                if sr is not None:
                    raw_bot.append(sr)
        spread_pooled = float(np.mean(pooled_top) - np.mean(pooled_bot))
        spread_wmean = float(np.mean(per_week_spread)) if per_week_spread else float("nan")
        # (c) 零分布:每周内打乱
        g_arr = np.array([r["gres"] for r in records], dtype=object)
        w_arr = np.array([r["week"] for r in records], dtype=object)
        e_arr = np.array([r["excess"] for r in records], dtype=float)
        used_weeks = sorted({r["week"] for r in records})
        masks = {w: (w_arr == w) for w in used_weeks}

        def null_stat(rng):
            sh = ap.shuffle_within(g_arr, w_arr, rng)
            rs = []
            for w in used_weeks:
                m = masks[w]
                xx = np.asarray(sh[m], dtype=float)
                yy = e_arr[m]
                if np.std(xx) == 0 or np.std(yy) == 0:
                    continue
                rho_ = spearmanr(xx, yy).statistic
                if not np.isnan(rho_):
                    rs.append(float(rho_))
            return float(np.mean(rs)) if rs else float("nan")

        null_pct, null_mean, null_sd = None, None, None
        try:
            null = ap.null_distribution(null_stat, 1000, 743, actual=float(mean_ic))
            null_pct = ap.percentile_of(float(mean_ic), null)
            null_mean = float(np.mean(null))
            null_sd = float(np.std(null))
        except Exception as e:  # noqa: BLE001
            null_pct = f"ERR:{e}"
        # (d) 两段
        half = len(wk) // 2
        h1 = float(np.mean(rho[:half]))
        h2 = float(np.mean(rho[half:]))
        return {
            "label": label, "n_weeks": len(wk), "weeks": [wk[0], wk[-1]],
            "n_obs_per_week_min": int(n_per.min()), "n_obs_per_week_max": int(n_per.max()),
            "mean_weekly_ic": float(mean_ic), "nw_t_4lag": float(t_stat), "nw_se": float(se),
            "b_spread_pooled_log_excess": spread_pooled,
            "b_spread_weekmean_log_excess": spread_wmean,
            "b_raw_long_leg_mean": float(np.mean(raw_top)) if raw_top else None,
            "b_raw_short_leg_mean": float(np.mean(raw_bot)) if raw_bot else None,
            "c_null_percentile": null_pct, "c_null_mean": null_mean, "c_null_sd": null_sd,
            "d_half1_mean_ic": h1, "d_half2_mean_ic": h2, "d_same_sign": bool(h1 * h2 > 0),
            "ic_series": [{"week": w, "n": int(n), "ic": float(v)} for w, n, v in zip(wk, n_per, rho)],
        }

    # ---------- 主结果(g_res) ----------
    # 每周单独回归 → 逐周赋 g_res
    all_recs = []
    for recs in weekly:
        feats = build_features(recs, True)
        for r, f in zip(recs, feats):
            rr = dict(r)
            rr["gres"] = float(f)
            all_recs.append(rr)
    # 结果变量:4 周相对 BTC 的对数超额(用 apparatus 的 long_return)
    bt_ret_cache = {}

    def bench_ret(t, tf):
        key = (t, tf)
        if key not in bt_ret_cache:
            px0 = bench_close("BTC", t)
            px1 = bench_close("BTC", tf)
            lr = ap.long_return(px0, px1)
            bt_ret_cache[key] = math.log1p(lr) if lr is not None else None
        return bt_ret_cache[key]

    for r in all_recs:
        lr = ap.long_return(r["px_t"], r["px_t28f"])
        br = bench_ret(r["week"], (date.fromisoformat(r["week"]) + timedelta(days=28)).isoformat())
        r["excess"] = (math.log1p(lr) - br) if (lr is not None and br is not None) else float("nan")
    all_recs = [r for r in all_recs if not math.isnan(r["excess"])]
    byw = {}
    for r in all_recs:
        byw.setdefault(r["week"], []).append(r)
    weekly = [byw[w] for w in weeks if w in byw]

    main = evaluate(all_recs, "g_res (主检验)")
    out["a_b_c_d"] = {"g_res": main}
    out["weekly"] = {
        "n_per_week": {w: len(r) for w, r in zip(weeks, weekly)},
        "dates": [w[0] for w in weekly], "dates_end": [w[-1] for w in weekly],
    }

    # ---------- 副项:原始 g ----------
    raw_recs = []
    for recs in weekly:
        for r in recs:
            rr = dict(r)
            rr["gres"] = r["g"]
            raw_recs.append(rr)
    out["secondary"]["raw_g"] = evaluate(raw_recs, "原始 g(不取残差)")

    # ---------- 副项:按网络 ----------
    nets = {}
    for r in all_recs:
        nets.setdefault(r["net"] or "na", []).append(r)
    by_net_out = {}
    for k, v in nets.items():
        if len(v) < 20:
            continue
        ics = weekly_ic(v)
        by_net_out[k] = {
            "n_obs": len(v), "n_weeks": len(ics),
            "mean_weekly_ic": float(np.mean([i[2] for i in ics])) if ics else None,
        }
    out["secondary"]["by_network"] = by_net_out

    # ---------- 副项:8 周目标 ----------
    eight = []
    for recs in weekly:
        for r in recs:
            t8 = (date.fromisoformat(r["week"]) + timedelta(days=56)).isoformat()
            p8 = last_on_or_before(r["coin"], t8)
            b8 = bench_close("BTC", t8)
            lr = ap.long_return(r["px_t"], p8)
            br = ap.long_return(bench_close("BTC", r["week"]), b8)
            if lr is None or br is None:
                continue
            e = math.log1p(lr) - math.log1p(br)
            eight.append({**r, "excess": e})
    out["secondary"]["target_8w"] = evaluate(eight, "8 周目标")

    # ---------- 副项:多链求和 vs 单链 ----------
    sum_recs = []
    for recs in weekly:
        keep = []
        for r in recs:
            t = r["week"]
            t28 = (date.fromisoformat(t) - timedelta(days=28)).isoformat()
            ht = holder_at(r["coin"], t, mode="sum")
            h28 = holder_at(r["coin"], t28, mode="sum")
            if ht is None or h28 is None or ht <= 0 or h28 <= 0:
                continue
            g = math.log(ht / h28)
            if abs(g) > 1:
                continue
            rr = dict(r)
            rr["g"] = g
            keep.append(rr)
        if len(keep) >= 5:
            feats = build_features(keep, True)
            for r, f in zip(keep, feats):
                rr = dict(r)
                rr["gres"] = float(f)
                sum_recs.append(rr)
    out["secondary"]["holders_summed_over_chains"] = evaluate(sum_recs, "多链持有人求和")

    out["diag"] = {"n_disagree_mcap": n_disagree, "n_multi_chain_coins": n_multi}
    with open("/Users/sbb/Projects/looloomi-ai-lane-a/docs/research/t265_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(json.dumps({k: out[k] for k in ["meta"]}, indent=2, default=str))
    for k, v in out["a_b_c_d"].items():
        print("\n===", k)
        print(json.dumps({kk: vv for kk, vv in v.items() if kk != "ic_series"}, indent=2, default=str))
    for k, v in out["secondary"].items():
        print("\n=== 副:", k)
        print(json.dumps(v if not isinstance(v, dict) else
                         {kk: vv for kk, vv in v.items() if kk != "ic_series"}, indent=2, default=str)[:2000])


def cmd_fetch_early():
    """补抓 D_START 之前的历史 —— 只补**持有人覆盖的币**(为了「上市满 26 周」的判定不被抓取窗口截断),
    结果写独立文件(不与主抓取竞争),run() 时合并。"""
    D_EARLY = "2023-06-01"
    cov = json.load(open(os.path.join(OUT_DIR, "coverage.json")))
    coins = [r["coin_id"] for r in cov]
    print(f"holder coins: {len(coins)}", flush=True)
    for tbl, name in [("cg_coin_mcap_daily", "cg_mcap_early.json"),
                      ("asset_mcap_daily", "asset_mcap_early.json")]:
        sel = "coin_id,d,mcap,price" + (",symbol" if tbl == "asset_mcap_daily" else "")
        out = []
        for i in range(0, len(coins), 60):
            batch = coins[i:i + 60]
            rows = get_all(
                tbl,
                {"select": sel, "order": "coin_id.asc,d.asc",
                 "coin_id": f"in.({','.join(batch)})",
                 "d": [f"gte.{D_EARLY}", f"lt.{D_START}"]},
                order="coin_id.asc,d.asc", label=f"{name}[{i}]",
            )
            out.extend(rows)
        with open(os.path.join(OUT_DIR, name), "w") as f:
            json.dump(out, f)
        print(f"{name}: rows={len(out)}", flush=True)


def cmd_refresh():
    """只刷新**持有人相关**的三份缓存(holders / coverage / 早期 mcap),不动已抓好的市值缓存。

    用途:主抓取里的市值缓存要十几分钟,而持有人表在 Mac 引擎回填后行长了几倍 —— 补跑时
    只需要刷新持有人这一侧。
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    h = get_all(
        "token_holders_daily",
        {"select": "coin_id,d,holders,granularity,network,address", "order": "coin_id.asc,d.asc"},
        order="coin_id.asc,d.asc", label="holders",
    )
    with open(os.path.join(OUT_DIR, "holders.json"), "w") as f:
        json.dump(h, f)
    print(f"holders.json: rows={len(h)} coins={len({r['coin_id'] for r in h})}", flush=True)
    cov = get_all(
        "token_holders_coverage",
        {"select": "coin_id,min_d,max_d,n,n_weekly", "order": "coin_id.asc"},
        order="coin_id.asc", label="coverage",
    )
    with open(os.path.join(OUT_DIR, "coverage.json"), "w") as f:
        json.dump(cov, f)
    nw = [int(r.get("n_weekly") or 0) for r in cov]
    print(f"coverage.json: coins={len(cov)} n_weekly>=52: {sum(1 for v in nw if v >= 52)} "
          f"n_weekly>=26: {sum(1 for v in nw if v >= 26)}", flush=True)
    cmd_fetch_early()
    print("refresh DONE", flush=True)


def cmd_fetch_asset():
    """补齐 asset_mcap_daily 的两块:
    ① 合并宇宙的「当周市值前 200」阈值 —— 只要样本周一的全宇宙 mcap;
    ② 只在 asset 里出现(不在 cg 里)的持有人币的日频价格。
    """
    from datetime import date, timedelta
    d0 = date(2024, 10, 7)
    mondays = []
    cur = d0
    while cur <= date(2026, 11, 2):
        mondays.append(cur.isoformat())
        cur += timedelta(days=7)
    print(f"sample mondays: {len(mondays)} ({mondays[0]}..{mondays[-1]})", flush=True)
    q = ",".join(mondays)
    rows = get_all(
        "asset_mcap_daily",
        {"select": "coin_id,d,mcap,price,symbol", "order": "coin_id.asc,d.asc", "d": f"in.({q})"},
        order="coin_id.asc,d.asc", label="asset_mondays",
    )
    with open(os.path.join(OUT_DIR, "asset_mcap_mondays.json"), "w") as f:
        json.dump(rows, f)
    print(f"asset_mcap_mondays.json: rows={len(rows)}", flush=True)

    # 只在 asset 里的持有人币 —— 日频
    cov = json.load(open(os.path.join(OUT_DIR, "coverage.json")))
    holders = [r["coin_id"] for r in cov]
    cgpath = os.path.join(OUT_DIR, "cg_mcap.json")
    cg_coins = set()
    if os.path.exists(cgpath):
        cg_coins = {r["coin_id"] for r in json.load(open(cgpath))}
    only_asset = [c for c in holders if c not in cg_coins]
    print(f"holder coins only in asset: {len(only_asset)} of {len(holders)}", flush=True)
    out = []
    for i in range(0, len(only_asset), 60):
        batch = only_asset[i:i + 60]
        rows = get_all(
            "asset_mcap_daily",
            {"select": "coin_id,d,mcap,price,symbol",
             "order": "coin_id.asc,d.asc",
             "coin_id": f"in.({','.join(batch)})", "d": f"gte.{D_START}"},
            order="coin_id.asc,d.asc", label=f"asset_only[{i}]",
        )
        out.extend(rows)
    with open(os.path.join(OUT_DIR, "asset_mcap_onlyholders.json"), "w") as f:
        json.dump(out, f)
    print(f"asset_mcap_onlyholders.json: rows={len(out)}", flush=True)


def cmd_report():
    """把 t265_results.json 渲染成 docs/research/T-265_holder_growth.md。"""
    R = "/Users/sbb/Projects/looloomi-ai-lane-a/docs/research"
    res = json.load(open(os.path.join(R, "t265_results.json")))
    m = res["meta"]
    main = res["a_b_c_d"]["g_res"]
    L = []
    A = L.append
    A("# T-265 / S-743 — 持有人数增长(采用面)对之后 4 周相对 BTC 的超额,横截面周频")
    A("")
    A("口径逐字照 `REFUTATION_LEDGER` S-743 预注册段(2026-11-06 08:36 UTC,Seth 写;写于回填完成之前、"
      "没有人看过任何一个持有人数)。本卡只算、不改代码、不入库;台账结果段由 Seth 抄。")
    A("")
    A("## 0. 前提检查(预注册的 ①)")
    A("")
    A(f"- `token_holders_coverage` 覆盖 **{m['holders_coverage_coins']}** 个币;`n_weekly ≥ 52` 的 "
      f"**{m['coverage_n_weekly_ge_52']}** 个(门槛 80 ⇒ **前提已过**);`n_weekly ≥ 26` 的 {m['coverage_n_weekly_ge_26']} 个。")
    A(f"- 原始 `token_holders_daily` {m['holders_rows']} 行 / {m['holders_coins']} 币,周频历史 "
      f"{m['holders_d_min']} → {m['holders_d_max']}。")
    A("")
    A("## 1. 数据与口径")
    A("")
    A("| 口径 | 预注册写的 | 实际用的 | 说明 |")
    A("|---|---|---|---|")
    A("| 价格 / 市值 | `cg_coin_mcap_daily` | `cg_coin_mcap_daily` ∪ `asset_mcap_daily`(同 coin_id 同 d 合并;"
      "cg 的非空值优先,mcap 空则用 asset) | §Seth-1106n 把币宇宙改成并集(826 → 1,216);两源同日 mcap 不一致 "
      f"{m['merged_mcap_disagreements']} 处 |")
    A("| BTC 基准 | — | `ohlcv_daily`,`source = binance_hist`(锁源) | §Seth-1106m 第 2 条 |")
    A("| 样本周 | 每周一 t | 周一 | 每周单独做横截面 |")
    A(f"| 宇宙 | 当周市值前 200 | 当周市值前 200(合并宇宙) | 阈值在 {m['universe_top_n']} 名上取 |")
    A("| 持有人点 | t−28 与 t 都有点(≤ t 最近的点,相差 ≤ 7 天) | 同 | |")
    A("| 上市满 26 周 | 是 | 是(价格序列首个日期 ≤ t − 182 天) | |")
    A("| 去稳定币 / 包装 / 质押衍生 | 价格相对 BTC 或 ETH 或 1 美元的 90 天波动 < 1% | 同(90 个日收益差的标准差,"
      "对 BTC / ETH / USD 取最小) | |")
    A("| 跳变 | `|g| > 1` 丢掉 | 同 | |")
    A("| g_res | g 对「过去 4 周对数收益」与「ln 市值」的横截面秩回归残差(每周单独回归) | 同(两个回归元取"
      "横截面秩;被解释变量取 g 原值,残差留在 g 的量纲上) | |")
    A("| 结果 | t → t+28 相对 BTC 的对数超额 | 同(币端用 `apparatus.long_return`,BTC 端同样) | |")
    A("")
    A(f"价格覆盖 {m['price_coins']} 币、市值覆盖 {m['mcap_coins']} 币;有多个链上持有人序列的币 "
      f"{m['coins_with_multiple_chain_series']} 个(主口径取点数最多的那条链,副项另给「多链求和」)。")
    A("")
    A("## 2. 样本")
    A("")
    A(f"- 候选周 {m['weeks_total']} 个(周一),可用周 **{m['weeks_used']}** 个;每周横截面 "
      f"{main['n_obs_per_week_min']}–{main['n_obs_per_week_max']} 个币。")
    A(f"- 过滤漏斗(计数单位=币 × 周):无持有人点 {m['drops']['no_holder']}、跳变 |g|>1 {m['drops']['jump']}、"
      f"无价格 {m['drops']['no_price']}、上市不满 26 周 {m['drops']['young']}、稳定币/包装类 {m['drops']['stable']}、"
      f"无未来价 {m['drops']['no_future']}、不在当周市值前 200 {m['drops']['outside_top200']}。")
    A("")
    A("## 3. 判据 (a)–(d) — 主检验(g_res)")
    A("")
    A("| 判据 | 预注册要求 | 实测 | 过? |")
    A("|---|---|---|---|")
    a_ok = main["mean_weekly_ic"] > 0 and main["nw_t_4lag"] >= 2.0
    b_ok = main["b_spread_pooled_log_excess"] >= 0.015
    c_pct = main["c_null_percentile"]
    c_ok = isinstance(c_pct, float) and c_pct >= 0.95
    d_ok = main["d_same_sign"]
    A(f"| (a) 每周横截面 Spearman IC 均值 / 按周 t(Newey-West 4 阶) | 均值 > 0 且 t ≥ 2.0 | "
      f"IC = **{main['mean_weekly_ic']:.4f}**, t = **{main['nw_t_4lag']:.3f}**(se {main['nw_se']:.4f}), "
      f"{main['n_weeks']} 周 | {'✅' if a_ok else '❌'} |")
    A(f"| (b) 前五分之一减后五分之一的平均 4 周超额 | ≥ +1.5% | 合并样本 **{main['b_spread_pooled_log_excess']*100:.3f}%**"
      f"(逐周差再平均 {main['b_spread_weekmean_log_excess']*100:.3f}%) | {'✅' if b_ok else '❌'} |")
    A(f"| (c) 零分布:每周内打乱 g_res(1,000 次,种子 743)的实际均值 IC 分位 | ≥ 0.95 | "
      f"**{c_pct if not isinstance(c_pct, float) else round(c_pct, 4)}**"
      f"(零分布均值 {main['c_null_mean']:.4f},sd {main['c_null_sd']:.4f}) | {'✅' if c_ok else '❌'} |")
    A(f"| (d) 两段(按样本周数对半)同号 | 同号 | 前半 **{main['d_half1_mean_ic']:.4f}** / "
      f"后半 **{main['d_half2_mean_ic']:.4f}** | {'✅' if d_ok else '❌'} |")
    A("")
    verdict = "✅ 四条全过" if (a_ok and b_ok and c_ok and d_ok) else \
        ("❌ 有条目不过" if not (a_ok and b_ok and c_ok and d_ok) else "")
    A(f"**按 S-743 预注册的判据,本卡这次计算的结果是:{verdict}**。")
    A("")
    A(f"补充:多头腿(前五分之一,原始价格)平均 {main['b_raw_long_leg_mean']:.4f};"
      f"空头腿(后五分之一,原始价格)平均 {main['b_raw_short_leg_mean']:.4f}。")
    A("")
    A("## 4. 副项(只报不判)")
    A("")
    sec = res.get("secondary", {})
    raw = sec.get("raw_g")
    if raw:
        A(f"- **原始 g(不取残差)**:IC {raw['mean_weekly_ic']:.4f},t {raw['nw_t_4lag']:.3f},"
          f"(b) {raw['b_spread_pooled_log_excess']*100:.3f}%,(c) 分位 "
          f"{raw['c_null_percentile'] if not isinstance(raw['c_null_percentile'], float) else round(raw['c_null_percentile'],4)},"
          f"{raw['n_weeks']} 周。")
    bn = sec.get("by_network") or {}
    if bn:
        A("- **按网络分**:" + "; ".join(
            f"{k} {v['n_obs']} 点 / {v['n_weeks']} 周,IC {v['mean_weekly_ic']:.4f}"
            if v["mean_weekly_ic"] is not None else f"{k} {v['n_obs']} 点(点太少不算)"
            for k, v in sorted(bn.items(), key=lambda kv: -(kv[1]["n_obs"] or 0))))
    e8 = sec.get("target_8w")
    if e8:
        A(f"- **8 周目标**:IC {e8['mean_weekly_ic']:.4f},t {e8['nw_t_4lag']:.3f},"
          f"(b) {e8['b_spread_pooled_log_excess']*100:.3f}%,{e8['n_weeks']} 周。")
    sm = sec.get("holders_summed_over_chains")
    if sm:
        A(f"- **多链持有人求和**(替代口径):IC {sm['mean_weekly_ic']:.4f},t {sm['nw_t_4lag']:.3f},"
          f"(b) {sm['b_spread_pooled_log_excess']*100:.3f}%,{sm['n_weeks']} 周。")
    A("")
    A("## 5. 逐周 IC")
    A("")
    A("| 周 | n | IC |")
    A("|---|---|---|")
    for row in main["ic_series"]:
        A(f"| {row['week']} | {row['n']} | {row['ic']:.4f} |")
    A("")
    A("---")
    A("")
    A("*产出:`docs/research/t265_holders.py`(fetch / fetch_early / run)、`docs/research/t265_results.json`(全部原始数字)。"
      "数据快照在 Mac 数据根 `/Volumes/CometCloudAI/cometcloud-local/research/t265/`。*")
    with open(os.path.join(R, "T-265_holder_growth.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"wrote {os.path.join(R, 'T-265_holder_growth.md')} ({len(L)} lines)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    {"fetch": cmd_fetch, "fetch_early": cmd_fetch_early, "fetch_asset": cmd_fetch_asset,
     "refresh": cmd_refresh, "run": cmd_run, "report": cmd_report}.get(cmd, cmd_fetch)()
