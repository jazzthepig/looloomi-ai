"""T-092 — Jazz 10-14「慢就做逆向,甘于人后」(S-569 → 预注册).

Efficient: parallel pagination + vectorized numpy.
"""
from __future__ import annotations
import os, json, math, random, datetime as dt, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import numpy as np

ENV = "/Users/sbb/Projects/looloomi-ai-lane-b/.env"
for line in open(ENV):
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,_,v=line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ["SUPABASE_KEY"]
BASE = os.environ["SUPABASE_URL"].rstrip("/")
ROOT = "/Users/sbb/Projects/looloomi-ai-lane-b"
OUT_RESULTS = f"{ROOT}/docs/research/T-092_results.json"
CACHE = f"{ROOT}/docs/research/T-092_cache.pkl"

UNIVERSE_24 = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK",
               "DOT","LTC","TRX","ATOM","NEAR","APT","ARB","OP","SUI",
               "UNI","AAVE","INJ","FIL","ETC","BCH"]

WINDOWS = {
    "W1_2020_2022": ("2020-01-01", "2022-12-31"),
    "W2_2023_2024": ("2023-01-01", "2024-12-31"),
    "W3_2025_now":   ("2025-01-01", "2026-10-14"),
}

N_SHUFFLES = int(os.environ.get("T092_SHUFFLES", "1000"))
SEED = 20261014
COST_R3 = 0.0020
DEFAULT_FUND_ANN = 0.10
PAGE_SIZE = 1000
N_WORKERS = 8


def fetch_count(path):
    url = f"{BASE}/rest/v1/{path}&limit=1"
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                                                "Prefer": "count=exact"})
    with urllib.request.urlopen(req, timeout=30) as r:
        cr = r.headers.get("content-range")
        return int(cr.split("/")[1]) if cr else 0


def fetch_page(base_path, offset):
    url = f"{base_path}&limit={PAGE_SIZE}&offset={offset}"
    req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_all(path, max_workers=N_WORKERS):
    base = f"{BASE}/rest/v1/{path}"
    total = fetch_count(path)
    log(f"  total={total}")
    n_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    results = [None] * n_pages
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_page, base, i * PAGE_SIZE): i for i in range(n_pages)}
        done = 0
        for f in as_completed(futures):
            i = futures[f]
            results[i] = f.result()
            done += 1
            if done % 100 == 0:
                log(f"    fetched {done}/{n_pages} t={time.time()-t0:.0f}s")
    out = []
    for c in results:
        if c:
            out.extend(c)
    log(f"  fetched {len(out)} rows in {time.time()-t0:.0f}s")
    return out


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def mondays(start: str, end: str) -> list:
    out = []
    cur = dt.date.fromisoformat(start)
    end_d = dt.date.fromisoformat(end)
    while cur <= end_d:
        if cur.weekday() == 0:
            out.append(cur.isoformat())
        cur += dt.timedelta(days=1)
    return out


def maxdd(path_vals):
    peak = path_vals[0] if path_vals else 1
    mdd = 0
    for v in path_vals:
        if v > peak: peak = v
        dd = v/peak - 1
        if dd < mdd: mdd = dd
    return mdd


def percentile(xs, p):
    if not xs: return float("nan")
    s = sorted(xs)
    k = max(0, min(len(s)-1, int(round(p * (len(s)-1)))))
    return s[k]


def build_z30(close_by_sym):
    z30 = {}
    for sym, ddict in close_by_sym.items():
        ds = sorted(ddict.keys())
        n = len(ds)
        if n < 760:
            continue
        closes = np.array([ddict[d] for d in ds], dtype=np.float64)
        valid = (closes[:-1] > 0) & (closes[1:] > 0)
        log_r = np.zeros(n, dtype=np.float64)
        log_r[1:] = np.where(valid, np.log(closes[1:] / closes[:-1]), 0.0)
        for i in range(760, n):
            if closes[i] <= 0 or closes[i-30] <= 0:
                continue
            win = log_r[i-730:i-30]
            win_clean = win[win != 0]
            if len(win_clean) < 365:
                continue
            mu = win_clean.mean()
            sd = win_clean.std(ddof=1)
            if sd == 0:
                continue
            r30 = math.log(closes[i] / closes[i-30])
            z = (r30 - mu) / sd
            z30[(sym, ds[i])] = z
    return z30


def main():
    log("=== T-092 RUN ===")
    t_start = time.time()

    log("[1] pull binance_hist closes")
    rows = fetch_all("ohlcv_daily?select=symbol,trade_date,close&source=eq.binance_hist")
    close_by_sym = defaultdict(dict)
    for r in rows:
        if r.get("close") is None: continue
        close_by_sym[r["symbol"]][r["trade_date"]] = float(r["close"])
    log(f"  symbols: {len(close_by_sym)} t={time.time()-t_start:.0f}s")

    log("[2] compute z30 per symbol")
    z30 = build_z30(close_by_sym)
    log(f"  z30 entries: {len(z30)} t={time.time()-t_start:.0f}s")

    log("[3] pull asset_mcap_daily 2020-now")
    mcap_rows = fetch_all("asset_mcap_daily?select=symbol,d,mcap&d=gte.2020-01-01")
    mcap_by_d = defaultdict(dict)
    for r in mcap_rows:
        if r.get("mcap") is not None:
            mcap_by_d[r["d"]][r["symbol"]] = float(r["mcap"])
    rank_by_dsym = {}
    for d, syms in mcap_by_d.items():
        sorted_syms = sorted(syms.keys(), key=lambda s: -syms[s])
        for i, s in enumerate(sorted_syms):
            rank_by_dsym[(d, s)] = i + 1
    log(f"  mcap days: {len(mcap_by_d)} t={time.time()-t_start:.0f}s")

    log("[4] pull funding_7d_ann_binance")
    fund_rows = fetch_all("state_daily?select=d,value&feature=eq.funding_7d_ann_binance")
    fund_by_d = {r["d"]: r.get("value") for r in fund_rows}
    log(f"  funding rows: {len(fund_rows)} t={time.time()-t_start:.0f}s")

    # Save cache
    import pickle
    with open(CACHE, "wb") as f:
        pickle.dump({
            "close_by_sym": {k: dict(v) for k, v in close_by_sym.items()},
            "z30": z30,
            "mcap_by_d": {d: dict(v) for d, v in mcap_by_d.items()},
            "rank_by_dsym": rank_by_dsym,
            "fund_by_d": fund_by_d,
        }, f, protocol=4)
    log(f"  cache saved t={time.time()-t_start:.0f}s")

    sorted_dates = {sym: sorted(ddict.keys()) for sym, ddict in close_by_sym.items()}

    non_btc = [s for s in UNIVERSE_24 if s != "BTC"]
    non_universe = [s for s in close_by_sym.keys() if s not in UNIVERSE_24]

    results = {}
    for wname, (lo, hi) in WINDOWS.items():
        log(f"--- {wname} ({lo} → {hi}) ---")
        ms = mondays(lo, hi)
        nM = len(ms)

        rebal_w_arr = np.zeros((nM, 24))
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            mcaps = np.array([mcap_by_d.get(d1, {}).get(sym, 0.0) for sym in UNIVERSE_24])
            tot = mcaps.sum()
            if tot > 0:
                rebal_w_arr[i] = mcaps / tot
            else:
                rebal_w_arr[i] = 1.0 / 24

        rets_arr = np.zeros((max(nM-1, 0), 24))
        rets_arr[:] = np.nan
        for i, d in enumerate(ms[:-1]):
            for j, sym in enumerate(UNIVERSE_24):
                cs = sorted_dates.get(sym, [])
                if not cs: continue
                idx = None
                for k, dd in enumerate(cs):
                    if dd >= d:
                        idx = k
                        break
                if idx is None or idx + 1 >= len(cs): continue
                p0 = close_by_sym[sym][cs[idx]]
                p1 = close_by_sym[sym][cs[idx+1]]
                if p0 > 0:
                    rets_arr[i, j] = p1 / p0 - 1

        fund_arr = np.zeros(nM)
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            v = fund_by_d.get(d1)
            fund_arr[i] = v if v is not None else DEFAULT_FUND_ANN

        # === R1 ===
        r1_events = []
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            for j, sym in enumerate(UNIVERSE_24):
                if sym == "BTC": continue
                z = z30.get((sym, d1))
                if z is not None and z >= 3:
                    r1_events.append((i, j))
        log(f"  R1 events: {len(r1_events)}")

        def run_r1(schedule_matrix):
            masked_w = rebal_w_arr.copy()
            masked_w[schedule_matrix] = 0
            sums = masked_w.sum(axis=1, keepdims=True)
            sums[sums == 0] = 1
            masked_w = masked_w / sums
            rets_filled = np.nan_to_num(rets_arr, nan=0.0)
            if nM > 1:
                w_used = masked_w[:-1]
                port_ret = (w_used * rets_filled).sum(axis=1)
            else:
                port_ret = np.array([0.0])
            nav = np.cumprod(1 + port_ret)
            return nav[-1], nav.tolist()

        sched_act = np.zeros((nM, 24), dtype=bool)
        for i, j in r1_events:
            for k in range(13):
                if i + k < nM:
                    sched_act[i+k, j] = True
        nav_base_r1, _ = run_r1(np.zeros((nM, 24), dtype=bool))
        nav_r1, path_r1 = run_r1(sched_act)
        excess_r1 = nav_r1 / nav_base_r1 - 1
        maxdd_r1 = maxdd(path_r1)
        maxdd_base_r1 = maxdd(run_r1(np.zeros((nM, 24), dtype=bool))[1])

        shuf_r1 = []
        for s_i in range(N_SHUFFLES):
            random.seed(SEED + s_i + 7000)
            sched = np.zeros((nM, 24), dtype=bool)
            for _ in r1_events:
                i_pick = random.randrange(nM)
                j_pick = random.randrange(23)
                actual_j = j_pick + 1
                for k in range(13):
                    if i_pick + k < nM:
                        sched[i_pick + k, actual_j] = True
            v, _ = run_r1(sched)
            shuf_r1.append(v)
        pct_r1 = sum(1 for v in shuf_r1 if v <= nav_r1) / len(shuf_r1) if shuf_r1 else 0

        per_year_r1 = defaultdict(int)
        for i, j in r1_events:
            per_year_r1[ms[i][:4]] += 1

        # === R2 ===
        r2_events_idx = []
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            z = z30.get(("BTC", d1))
            if z is not None and z <= -2:
                r2_events_idx.append(i)
        log(f"  R2 events: {len(r2_events_idx)}")

        def run_r2(active_mask):
            nav_arr = []
            nav_v = 1.0
            if nM > 1:
                for i in range(nM-1):
                    w = rebal_w_arr[i]
                    r_vec = np.nan_to_num(rets_arr[i], nan=0.0)
                    base_ret = (w * r_vec).sum()
                    is_active = bool(active_mask[i])
                    mult = 1.3 if is_active else 1.0
                    week_fund = (mult - 1.0) * fund_arr[i] / 52.0
                    nav_v *= (1 + mult * base_ret - week_fund)
                    nav_arr.append(nav_v)
            return nav_v, np.array(nav_arr)

        active_act = np.zeros(nM, dtype=bool)
        for i in r2_events_idx:
            for k in range(13):
                if i + k < nM:
                    active_act[i+k] = True

        nav_base_r2, path_base_r2 = run_r2(np.zeros(nM, dtype=bool))
        nav_r2, path_r2_arr = run_r2(active_act)
        excess_r2 = nav_r2 / nav_base_r2 - 1

        funding_paid_r2 = 0.0
        for i in range(nM-1):
            mult = 1.3 if active_act[i] else 1.0
            funding_paid_r2 += (mult - 1.0) * fund_arr[i] / 52.0

        maxdd_r2 = maxdd([1.0] + path_r2_arr.tolist())
        maxdd_base_r2 = maxdd([1.0] + path_base_r2.tolist())

        shuf_r2 = []
        for s_i in range(N_SHUFFLES):
            random.seed(SEED + s_i + 8000)
            shuf_idx = random.sample(range(nM), k=len(r2_events_idx))
            act = np.zeros(nM, dtype=bool)
            for i in shuf_idx:
                for k in range(13):
                    if i + k < nM:
                        act[i+k] = True
            v, _ = run_r2(act)
            shuf_r2.append(v)
        pct_r2 = sum(1 for v in shuf_r2 if v <= nav_r2) / len(shuf_r2) if shuf_r2 else 0

        # === R3 ===
        r3_events = []
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            for sym in non_universe:
                z = z30.get((sym, d1))
                if z is None or z < 3: continue
                rank = rank_by_dsym.get((d, sym))
                if rank is None or rank <= 30: continue
                r3_events.append((i, sym))
        log(f"  R3 candidate events: {len(r3_events)}")

        cs_btc = sorted_dates["BTC"]

        def find_idx(cs, d_iso):
            if d_iso in cs:
                return cs.index(d_iso)
            import bisect
            return bisect.bisect_right(cs, d_iso) - 1

        def r3_pnl(week_idx, sym):
            d = ms[week_idx]
            i0 = find_idx(cs_btc, d)
            if i0 < 0: return None
            i_entry = min(i0 + 7, len(cs_btc) - 1)
            i_exit = min(i_entry + 30, len(cs_btc) - 1)
            if i_exit <= i_entry: return None
            ent_d_b = cs_btc[i_entry]
            ext_d_b = cs_btc[i_exit]
            cs_s = sorted_dates.get(sym, [])
            if not cs_s: return None
            i_ent_s = find_idx(cs_s, ent_d_b)
            i_ext_s = min(i_ent_s + 30, len(cs_s) - 1)
            if i_ext_s <= i_ent_s: return None
            ent_d_s = cs_s[i_ent_s]
            ext_d_s = cs_s[i_ext_s]
            p_ent_s = close_by_sym[sym][ent_d_s]
            p_ext_s = close_by_sym[sym][ext_d_s]
            p_ent_b = close_by_sym["BTC"][ent_d_b]
            p_ext_b = close_by_sym["BTC"][ext_d_b]
            if None in (p_ent_s, p_ext_s, p_ent_b, p_ext_b): return None
            if p_ent_s <= 0 or p_ent_b <= 0: return None
            short_ret = p_ent_s / p_ext_s - 1
            long_ret = p_ext_b / p_ent_b - 1
            net = short_ret + long_ret - COST_R3
            return {"net": net, "short": short_ret, "long": long_ret,
                    "entry": ent_d_b, "exit": ext_d_s, "sym": sym}

        r3_pnls = []
        for i, sym in r3_events:
            r = r3_pnl(i, sym)
            if r is not None:
                r3_pnls.append(r)

        n_r3 = len(r3_pnls)
        r3_mean_net = sum(p["net"] for p in r3_pnls) / n_r3 if n_r3 else 0
        r3_mean_short = sum(p["short"] for p in r3_pnls) / n_r3 if n_r3 else 0
        r3_mean_long_btc = sum(p["long"] for p in r3_pnls) / n_r3 if n_r3 else 0
        r3_excess = r3_mean_net - r3_mean_long_btc
        r3_win = sum(1 for p in r3_pnls if p["net"] > 0) / n_r3 if n_r3 else 0

        fund_total_days = 0
        fund_present = 0
        for p in r3_pnls:
            cs_btc_idx = find_idx(cs_btc, p["entry"])
            cs_btc_idx_end = find_idx(cs_btc, p["exit"])
            for j in range(cs_btc_idx, cs_btc_idx_end + 1):
                d_in = cs_btc[j]
                fund_total_days += 1
                if fund_by_d.get(d_in) is not None: fund_present += 1
        fund_frac = fund_present / fund_total_days if fund_total_days else 0

        per_year_r3 = defaultdict(int)
        for i, _ in r3_events:
            per_year_r3[ms[i][:4]] += 1

        shuf_r3 = []
        for s_i in range(N_SHUFFLES):
            random.seed(SEED + s_i + 9000)
            shuf_pnls = []
            for _ in r3_events:
                i_pick = random.randrange(nM)
                sym_pick = random.choice(non_universe) if non_universe else None
                if sym_pick is None: continue
                r = r3_pnl(i_pick, sym_pick)
                if r is not None:
                    shuf_pnls.append(r["net"])
            mean_s = sum(shuf_pnls) / len(shuf_pnls) if shuf_pnls else 0
            shuf_r3.append(mean_s)
        pct_r3 = sum(1 for v in shuf_r3 if v <= r3_mean_net) / len(shuf_r3) if shuf_r3 else 0

        results[wname] = {
            "n_mondays": nM,
            "lo": lo, "hi": hi,
            "R1": {
                "n_events": len(r1_events),
                "nav_baseline": round(float(nav_base_r1), 4),
                "nav_R1": round(float(nav_r1), 4),
                "excess_pct": round(float(excess_r1) * 100, 2),
                "maxdd_baseline_pct": round(float(maxdd_base_r1) * 100, 2),
                "maxdd_R1_pct": round(float(maxdd_r1) * 100, 2),
                "shuffle_pct": round(float(pct_r1) * 100, 1),
                "per_year_events": dict(sorted(per_year_r1.items())),
                "shuf_p10": round(percentile(shuf_r1, 0.10), 4),
                "shuf_p50": round(percentile(shuf_r1, 0.50), 4),
                "shuf_p90": round(percentile(shuf_r1, 0.90), 4),
            },
            "R2": {
                "n_events": len(r2_events_idx),
                "nav_baseline": round(float(nav_base_r2), 4),
                "nav_R2": round(float(nav_r2), 4),
                "excess_pct": round(float(excess_r2) * 100, 2),
                "fund_paid_R2_pct": round(funding_paid_r2 * 100, 4),
                "maxdd_baseline_pct": round(float(maxdd_base_r2) * 100, 2),
                "maxdd_R2_pct": round(float(maxdd_r2) * 100, 2),
                "shuffle_pct": round(float(pct_r2) * 100, 1),
                "shuf_p10": round(percentile(shuf_r2, 0.10), 4),
                "shuf_p50": round(percentile(shuf_r2, 0.50), 4),
                "shuf_p90": round(percentile(shuf_r2, 0.90), 4),
            },
            "R3": {
                "n_events": n_r3,
                "n_candidate": len(r3_events),
                "mean_net_pct": round(float(r3_mean_net) * 100, 2),
                "mean_short_pct": round(float(r3_mean_short) * 100, 2),
                "mean_long_btc_pct": round(float(r3_mean_long_btc) * 100, 2),
                "excess_vs_btc_pct": round(float(r3_excess) * 100, 2),
                "win_rate": round(float(r3_win), 3),
                "fund_data_present_frac_pct": round(fund_frac * 100, 1),
                "shuffle_pct": round(float(pct_r3) * 100, 1),
                "per_year_events": dict(sorted(per_year_r3.items())),
                "shuf_p10": round(percentile(shuf_r3, 0.10) * 100, 2),
                "shuf_p50": round(percentile(shuf_r3, 0.50) * 100, 2),
                "shuf_p90": round(percentile(shuf_r3, 0.90) * 100, 2),
            }
        }
        log(f"  R1 excess={excess_r1*100:.2f}% pct={pct_r1*100:.1f}; "
            f"R2 excess={excess_r2*100:.2f}% pct={pct_r2*100:.1f}; "
            f"R3 mean={r3_mean_net*100:.2f}% pct={pct_r3*100:.1f} "
            f"(t={time.time()-t_start:.0f}s)")

    out = {
        "task": "T-092",
        "windows": WINDOWS,
        "n_shuffles": N_SHUFFLES,
        "seed": SEED,
        "pre_registered": True,
        "results_by_window": results,
        "verdicts": {
            w: {
                "R1_PASS": results[w]["R1"]["excess_pct"] > 0 and results[w]["R1"]["shuffle_pct"] >= 90,
                "R2_PASS": results[w]["R2"]["excess_pct"] > 0 and results[w]["R2"]["shuffle_pct"] >= 90,
                "R3_PASS": results[w]["R3"]["excess_vs_btc_pct"] > 0 and results[w]["R3"]["shuffle_pct"] >= 90,
            } for w in results
        }
    }
    with open(OUT_RESULTS, "w") as f:
        json.dump(out, f, indent=2, default=str)
    log(f"wrote {OUT_RESULTS}")
    return out


if __name__ == "__main__":
    out = main()
    print(json.dumps(out, indent=2, default=str))