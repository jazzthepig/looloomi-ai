"""T-093 — Jazz 10-14「多重情景分析」逆向 T-092 三条规则 + 边际流动性 × BTC 趋势 四状态标签 + 8 周块打乱对照

Pre-registered: M-223 (2026-10-14, sealed)

§Seth-1014k 退回原 c258f81:补回撤列、删无数据支撑的因果句、台账号 M-224。
本版本(2026-10-15 lane-b 改)两处 R3c bug 已修:
- short_ret 改用 `src.data.evaluation.apparatus.short_return`(1 − exit/ent,有界)
  旧 p_ent/p_ext − 1 凸、价格 → 0 记 +∞(红测见 docs/research/T-093_red_tests.py)
- 入场/出场价改用 `apparatus.price_on_or_after`,ent_d_b 早于 sym 上市日 ⇒ 整条事件 None
  旧 `bisect_right − 1` 在 i_ent_s = −1 时 i_ext_s = 29 > −1,继续算,用 sym[−1] 当入价(假 P&L)
"""
from __future__ import annotations
import os, json, math, random, datetime as dt, time, pickle, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import numpy as np

# apparatus(主仓库 src/,本 worktree 不带)
MAIN_REPO = "/Users/sbb/Projects/looloomi-ai"
if MAIN_REPO not in sys.path:
    sys.path.insert(0, MAIN_REPO)
from src.data.evaluation.apparatus import short_return as _short_return, price_on_or_after as _price_on_or_after  # noqa: E402

ENV = "/Users/sbb/Projects/looloomi-ai-lane-b/.env"
for line in open(ENV):
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,_,v=line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ["SUPABASE_KEY"]
BASE = os.environ["SUPABASE_URL"].rstrip("/")
ROOT = "/Users/sbb/Projects/looloomi-ai-lane-b"
OUT_RESULTS = f"{ROOT}/docs/research/T-093_results.json"
CACHE_092 = f"{ROOT}/docs/research/T-092_cache.pkl"

UNIVERSE_24 = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK",
               "DOT","LTC","TRX","ATOM","NEAR","APT","ARB","OP","SUI",
               "UNI","AAVE","INJ","FIL","ETC","BCH"]

WINDOWS = {
    "W1_2020_2022": ("2020-06-01", "2022-12-31"),
    "W2_2023_2024": ("2023-01-01", "2024-12-31"),
    "W3_2025_now":   ("2025-01-01", "2026-10-14"),
}

N_SHUFFLES = int(os.environ.get("T093_SHUFFLES", "1000"))
SEED = 20261014
COST_R3 = 0.0020
DEFAULT_FUND_ANN = 0.10
PAGE_SIZE = 1000
N_WORKERS = 8
BLOCK_WEEKS = 8


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


def compute_stable_mcap_growth(stable_mcap_by_d, sort_dates):
    """Compute 30-day growth rate per date, and at each date d: delta = growth[d] - growth[d-30].
    Then improvement = sign(delta).
    Returns dict d -> (sum_usdt_usdc_mcap, growth_30d, growth_delta)
    """
    out = {}
    n = len(sort_dates)
    # mcap[date] = total
    series = [stable_mcap_by_d.get(d, float("nan")) for d in sort_dates]
    for i in range(30, n):
        if math.isnan(series[i]) or math.isnan(series[i-30]) or series[i-30] == 0:
            continue
        g_now = series[i] / series[i-30] - 1
        if i >= 60 and not math.isnan(series[i-60]) and series[i-60] != 0:
            g_prev = series[i-30] / series[i-60] - 1
        else:
            g_prev = float("nan")
        if not math.isnan(g_prev):
            delta = g_now - g_prev
        else:
            delta = float("nan")
        out[sort_dates[i]] = {
            "mcap": series[i],
            "growth_30d": g_now,
            "growth_delta": delta,
            "improving": (delta > 0) if not math.isnan(delta) else None,
            "weak_recovery": (g_now <= 0.02 and delta > 0) if not math.isnan(delta) else False,
        }
    return out


def compute_btc_trend(btc_closes, sort_dates, ma_window=200):
    """Returns dict d -> bool (True = above 200-day MA)"""
    out = {}
    for i, d in enumerate(sort_dates):
        if i < ma_window:
            continue
        window = [btc_closes.get(sort_dates[j]) for j in range(i - ma_window, i)]
        window = [x for x in window if x is not None and x > 0]
        if len(window) < ma_window * 0.8:
            continue
        ma = sum(window) / len(window)
        cur = btc_closes.get(d)
        if cur is None or cur <= 0:
            continue
        # log ratio
        log_ratio = math.log(cur / ma)
        out[d] = (log_ratio > 0)
    return out


def build_states(ms, stable_info_by_d, btc_trend_by_d):
    """For each Monday, determine (improving, above_ma).
    Returns: dict monday_iso -> {"improving": bool, "above_ma": bool, "weak_recovery": bool}
    """
    out = {}
    for m in ms:
        d1 = (dt.date.fromisoformat(m) - dt.timedelta(days=1)).isoformat()
        s = stable_info_by_d.get(d1)
        b = btc_trend_by_d.get(d1)
        if s is None or b is None:
            continue
        out[m] = {
            "improving": bool(s["improving"]),
            "above_ma": bool(b),
            "weak_recovery": bool(s["weak_recovery"]),
        }
    return out


def main():
    log("=== T-093 RUN ===")
    t_start = time.time()

    # Load T-092 cache (close, z30, mcap_rank, funding)
    with open(CACHE_092, "rb") as f:
        c = pickle.load(f)
    close_by_sym = c["close_by_sym"]
    z30 = c["z30"]
    mcap_by_d = c["mcap_by_d"]
    rank_by_dsym = c["rank_by_dsym"]
    fund_by_d = c["fund_by_d"]
    sorted_dates = {sym: sorted(ddict.keys()) for sym, ddict in close_by_sym.items()}
    log(f"  T-092 cache loaded t={time.time()-t_start:.0f}s")

    # Fetch stable coin mcap
    log("[1] fetch USDT+USDC mcap")
    stable_rows = fetch_all("cg_coin_mcap_daily?select=coin_id,d,mcap&coin_id=in.(tether,usd-coin)")
    stable_mcap_by_d = defaultdict(float)
    for r in stable_rows:
        if r.get("mcap") is not None:
            stable_mcap_by_d[r["d"]] += float(r["mcap"])
    log(f"  stable mcap days: {len(stable_mcap_by_d)}")

    # All sorted dates from stable_mcap (which starts 2019-12)
    sort_stable = sorted(stable_mcap_by_d.keys())
    stable_info_by_d = compute_stable_mcap_growth(stable_mcap_by_d, sort_stable)

    # BTC trend
    btc_closes = close_by_sym.get("BTC", {})
    btc_sort = sorted(btc_closes.keys())
    btc_trend_by_d = compute_btc_trend(btc_closes, btc_sort)
    log(f"  btc_trend days: {len(btc_trend_by_d)}")

    non_btc = [s for s in UNIVERSE_24 if s != "BTC"]
    non_universe = [s for s in close_by_sym.keys() if s not in UNIVERSE_24]

    results = {}
    for wname, (lo, hi) in WINDOWS.items():
        log(f"--- {wname} ({lo} → {hi}) ---")
        ms = mondays(lo, hi)
        nM = len(ms)

        # States per monday (d-1 basis)
        states = build_states(ms, stable_info_by_d, btc_trend_by_d)
        log(f"  states built: {len(states)}/{nM}")
        # log weekly state counts
        cnt_improving = sum(1 for s in states.values() if s["improving"])
        cnt_above_ma = sum(1 for s in states.values() if s["above_ma"])
        cnt_weak = sum(1 for s in states.values() if s["weak_recovery"])
        log(f"    improving={cnt_improving}, above_ma={cnt_above_ma}, weak_recovery={cnt_weak}")

        # === Compute unconditional T-092 baselines (per rule) ===
        # R1 events
        r1_events = []
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            for j, sym in enumerate(UNIVERSE_24):
                if sym == "BTC": continue
                z = z30.get((sym, d1))
                if z is not None and z >= 3:
                    r1_events.append((i, j))
        log(f"  R1 events: {len(r1_events)}")

        # R2 events (BTC z30 <= -2)
        r2_events_idx = []
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            z = z30.get(("BTC", d1))
            if z is not None and z <= -2:
                r2_events_idx.append(i)
        log(f"  R2 events: {len(r2_events_idx)}")

        # R3 events
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

        # pre-compute weekly rebal weights
        rebal_w_arr = np.zeros((nM, 24))
        for i, d in enumerate(ms):
            d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
            mcaps = np.array([mcap_by_d.get(d1, {}).get(sym, 0.0) for sym in UNIVERSE_24])
            tot = mcaps.sum()
            if tot > 0:
                rebal_w_arr[i] = mcaps / tot
            else:
                rebal_w_arr[i] = 1.0 / 24

        # weekly returns [nM-1, 24]
        rets_arr = np.zeros((max(nM-1, 0), 24))
        rets_arr[:] = np.nan
        for i, d in enumerate(ms[:-1]):
            for j, sym in enumerate(UNIVERSE_24):
                cs = sorted_dates.get(sym, [])
                if not cs: continue
                idx = None
                for k, dd in enumerate(cs):
                    if dd >= d:
                        idx = k; break
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

        # === Helper: run R1c with a "block" function ===
        # block returns a [nM, 24] boolean weight-zero mask.
        # For each event week i, sym idx j: if states[ti] indicates "active", apply the block.
        # Then renormalize remaining to BTC-heavy weights per the rule.
        def run_r1c(active_fn):
            """active_fn(i, j) -> 'zero'|'half'|'none'"""
            masked_w = rebal_w_arr.copy()
            for i, j in r1_events:
                act = active_fn(i, j)
                if act == "zero":
                    masked_w[i:i+13, j] = 0
                elif act == "half":
                    masked_w[i:i+13, j] *= 0.5
            # renormalize per row
            sums = masked_w.sum(axis=1, keepdims=True)
            sums[sums == 0] = 1
            masked_w = masked_w / sums
            rets_filled = np.nan_to_num(rets_arr, nan=0.0)
            if nM > 1:
                port_ret = (masked_w[:-1] * rets_filled).sum(axis=1)
            else:
                port_ret = np.array([0.0])
            nav = np.cumprod(1 + port_ret)
            return nav[-1], nav.tolist()

        def run_r2c(active_fn):
            """active_fn(i) -> bool: lever 1.3"""
            nav_arr = []
            nav_v = 1.0
            if nM > 1:
                for i in range(nM-1):
                    w = rebal_w_arr[i]
                    r_vec = np.nan_to_num(rets_arr[i], nan=0.0)
                    base_ret = (w * r_vec).sum()
                    mult = 1.3 if active_fn(i) else 1.0
                    week_fund = (mult - 1.0) * fund_arr[i] / 52.0
                    nav_v *= (1 + mult * base_ret - week_fund)
                    nav_arr.append(nav_v)
            return nav_v, nav_arr

        # R3 unconditional pnl — 改法(§Seth-1014k):short_ret 用 apparatus.short_return,
        # 入场 / 出场价用 price_on_or_after 拿「该日或之后 3 日内」第一个有效收盘,取不到 ⇒ 整事件 None。
        cs_btc = sorted_dates["BTC"]
        MAX_GAP_DAYS = 3  # 价格「该日或之后 3 日内」未找到 ⇒ 不可算

        def r3_pnl(week_idx, sym):
            d = ms[week_idx]
            # BTC 入场 / 出场:沿用旧的 (i0 + 7, +30) 索引
            if d not in cs_btc:
                # cs_btc 已经有序;二分找 ≥ d 的第一个
                import bisect
                i0 = bisect.bisect_left(cs_btc, d)
            else:
                i0 = cs_btc.index(d)
            if i0 >= len(cs_btc): return None
            i_entry = min(i0 + 7, len(cs_btc) - 1)
            i_exit = min(i_entry + 30, len(cs_btc) - 1)
            if i_exit <= i_entry: return None
            ent_d_b = cs_btc[i_entry]
            ext_d_b = cs_btc[i_exit]
            # 改法:sym 端用 price_on_or_after,ent_d_b / ext_d_b 早于 sym 上市日 ⇒ None(不假入场)
            cs_s = sorted_dates.get(sym, [])
            if not cs_s: return None
            sym_closes_seq = [close_by_sym[sym][dd] for dd in cs_s]
            p_ent_s = _price_on_or_after(cs_s, sym_closes_seq, ent_d_b, max_gap_days=MAX_GAP_DAYS)
            p_ext_s = _price_on_or_after(cs_s, sym_closes_seq, ext_d_b, max_gap_days=MAX_GAP_DAYS)
            p_ent_b = close_by_sym["BTC"].get(ent_d_b)
            p_ext_b = close_by_sym["BTC"].get(ext_d_b)
            if None in (p_ent_s, p_ext_s, p_ent_b, p_ext_b): return None
            if p_ent_s <= 0 or p_ent_b <= 0: return None
            # 改法:短仓公式用 apparatus.short_return(1 − exit / entry,有界)
            short_ret = _short_return(p_ent_s, p_ext_s)
            long_ret = p_ext_b / p_ent_b - 1
            net = short_ret + long_ret - COST_R3
            return {"net": net, "short": short_ret, "long": long_ret,
                    "entry": ent_d_b, "exit": ext_d_b, "sym": sym}

        def run_r3c(sizing_fn):
            """sizing_fn(week_idx, sym) -> size in {0, 0.5, 1.0, 1.5}. Returns sum of size * net."""
            total = 0.0
            n = 0
            _nets = []
            for i, sym in r3_events:
                r = r3_pnl(i, sym)
                if r is None: continue
                size = sizing_fn(i, sym)
                total += size * r["net"]
                n += 1
                if size != 0.0:
                    _nets.append(size * r["net"])
            return total / n if n > 0 else 0, n, _nets

        # === unconditional baselines ===
        # R1 unconditional: zero weight for 13 weeks on event
        def uncond_r1(i, j):
            return "zero"
        nav_base_r1, _ = run_r1c(uncond_r1)
        # R2 unconditional: lever on BTC events
        def uncond_r2(i):
            return i in r2_events_idx or any(i in range(k, min(k+13, nM)) for k in r2_events_idx)
        # simpler: lever on event idx set including 13-week tail
        r2_active_uncond = np.zeros(nM, dtype=bool)
        for k in r2_events_idx:
            for w in range(13):
                if k + w < nM:
                    r2_active_uncond[k + w] = True
        def uncond_r2_fn(i):
            return bool(r2_active_uncond[i])
        nav_base_r2, _ = run_r2c(uncond_r2_fn)
        # R3 unconditional: full size
        def uncond_r3(i, sym):
            return 1.0
        r3_mean_uncond, n_r3_uncond, _r3_nets_uncond = run_r3c(uncond_r3)

        # === conditional versions ===
        def cond_r1(i, j):
            s = states.get(ms[i])
            if s is None:
                return "none"
            if not s["improving"]:
                return "zero"
            # improving
            return "half"
        nav_cond_r1, _ = run_r1c(cond_r1)

        def cond_r2(i):
            s = states.get(ms[i])
            if s is None:
                return False
            return s["improving"]
        nav_cond_r2, _ = run_r2c(cond_r2)

        def cond_r3(i, sym):
            s = states.get(ms[i])
            if s is None:
                return 0.0
            if s["weak_recovery"]:
                return 0.0  # full unwind
            if not s["improving"]:
                return 1.5  # max short (full + extra)
            return 0.5  # improving: half short
        r3_mean_cond, n_r3_cond, _r3_nets_cond = run_r3c(cond_r3)

        # Excess
        excess_cond_r1 = nav_cond_r1 / nav_base_r1 - 1
        excess_cond_r2 = nav_cond_r2 / nav_base_r2 - 1
        excess_cond_r3 = r3_mean_cond - r3_mean_uncond

        log(f"  R1c uncond={nav_base_r1:.4f} cond={nav_cond_r1:.4f} excess={excess_cond_r1*100:+.2f}%")
        log(f"  R2c uncond={nav_base_r2:.4f} cond={nav_cond_r2:.4f} excess={excess_cond_r2*100:+.2f}%")
        log(f"  R3c uncond={r3_mean_uncond*100:+.2f}% cond={r3_mean_cond*100:+.2f}% excess={excess_cond_r3*100:+.2f}%")

        # === 8-week block shuffle: 1000 reps ===
        # Each rep: take the state labels (improving/above_ma) per Monday and shuffle in 8-week blocks
        # while preserving event timing. Must break key->value binding by shuffling VALUES not DICTs.
        def shuffle_states(rep_seed):
            rng = random.Random(SEED + rep_seed + 11000)
            keys = list(states.keys())
            # Build list of 8-week block VALUES, padding the last with copies of the last item
            block_values = []
            for k in range(0, len(keys), BLOCK_WEEKS):
                block = [states[m] for m in keys[k:k+BLOCK_WEEKS]]
                while len(block) < BLOCK_WEEKS:
                    block.append(block[-1] if block else {"improving": False, "above_ma": True, "weak_recovery": False})
                block_values.append(block)
            rng.shuffle(block_values)
            shuffled = {}
            for bi, b in enumerate(block_values):
                start = bi * BLOCK_WEEKS
                end = min(start + BLOCK_WEEKS, len(keys))
                for j, m in enumerate(keys[start:end]):
                    shuffled[m] = b[j]
            return shuffled

        # R1c shuffled
        shuf_r1c = []
        shuf_r2c = []
        shuf_r3c = []
        for s_i in range(N_SHUFFLES):
            shuf_states = shuffle_states(s_i)
            # R1c
            def shuf_r1_fn(i, j, sh=shuf_states):
                s = sh.get(ms[i])
                if s is None: return "none"
                if not s["improving"]: return "zero"
                return "half"
            nv, _ = run_r1c(shuf_r1_fn)
            shuf_r1c.append(nv / nav_base_r1 - 1)
            # R2c
            def shuf_r2_fn(i, sh=shuf_states):
                s = sh.get(ms[i])
                if s is None: return False
                return s["improving"]
            nv, _ = run_r2c(shuf_r2_fn)
            shuf_r2c.append(nv / nav_base_r2 - 1)
            # R3c
            def shuf_r3_fn(i, sym, sh=shuf_states):
                s = sh.get(ms[i])
                if s is None: return 0.0
                if s["weak_recovery"]: return 0.0
                if not s["improving"]: return 1.5
                return 0.5
            mean_s, _, _ = run_r3c(shuf_r3_fn)
            shuf_r3c.append(mean_s - r3_mean_uncond)

        pct_r1c = sum(1 for v in shuf_r1c if v <= excess_cond_r1) / len(shuf_r1c) if shuf_r1c else 0
        pct_r2c = sum(1 for v in shuf_r2c if v <= excess_cond_r2) / len(shuf_r2c) if shuf_r2c else 0
        pct_r3c = sum(1 for v in shuf_r3c if v <= excess_cond_r3) / len(shuf_r3c) if shuf_r3c else 0

        log(f"  R1c excess={excess_cond_r1*100:+.2f}% shuffle_pct={pct_r1c*100:.1f}")
        log(f"  R2c excess={excess_cond_r2*100:+.2f}% shuffle_pct={pct_r2c*100:.1f}")
        log(f"  R3c excess={excess_cond_r3*100:+.2f}% shuffle_pct={pct_r3c*100:.1f}")

        # 4-state week counts
        cnt_state = {(True, True): 0, (True, False): 0, (False, True): 0, (False, False): 0}
        for s in states.values():
            k = (s["improving"], s["above_ma"])
            cnt_state[k] = cnt_state.get(k, 0) + 1

        results[wname] = {
            "n_mondays": nM,
            "n_with_state": len(states),
            "lo": lo, "hi": hi,
            "state_counts": {
                "improving": cnt_improving,
                "above_ma": cnt_above_ma,
                "weak_recovery": cnt_weak,
                "4state": {f"imp={t[0]}_above_ma={t[1]}": cnt_state.get(t, 0) for t in cnt_state},
            },
            "R1c": {
                "nav_uncond": round(float(nav_base_r1), 4),
                "nav_cond": round(float(nav_cond_r1), 4),
                "excess_cond_vs_uncond_pct": round(float(excess_cond_r1) * 100, 2),
                "shuffle_pct": round(float(pct_r1c) * 100, 1),
                "shuf_p10": round(percentile(shuf_r1c, 0.10) * 100, 2),
                "shuf_p50": round(percentile(shuf_r1c, 0.50) * 100, 2),
                "shuf_p90": round(percentile(shuf_r1c, 0.90) * 100, 2),
            },
            "R2c": {
                "nav_uncond": round(float(nav_base_r2), 4),
                "nav_cond": round(float(nav_cond_r2), 4),
                "excess_cond_vs_uncond_pct": round(float(excess_cond_r2) * 100, 2),
                "shuffle_pct": round(float(pct_r2c) * 100, 1),
                "shuf_p10": round(percentile(shuf_r2c, 0.10) * 100, 2),
                "shuf_p50": round(percentile(shuf_r2c, 0.50) * 100, 2),
                "shuf_p90": round(percentile(shuf_r2c, 0.90) * 100, 2),
            },
            "R3c": {
                "n_events": n_r3_cond,
                "mean_uncond_pct": round(float(r3_mean_uncond) * 100, 2),
                "mean_cond_pct": round(float(r3_mean_cond) * 100, 2),
                "excess_cond_vs_uncond_pct": round(float(excess_cond_r3) * 100, 2),
                "shuffle_pct": round(float(pct_r3c) * 100, 1),
                "shuf_p10": round(percentile(shuf_r3c, 0.10) * 100, 2),
                "shuf_p50": round(percentile(shuf_r3c, 0.50) * 100, 2),
                "shuf_p90": round(percentile(shuf_r3c, 0.90) * 100, 2),
            },
            "maxdd_uncond_r1_pct": round(float(maxdd(run_r1c(uncond_r1)[1])) * 100, 2),
            "maxdd_cond_r1_pct": round(float(maxdd(run_r1c(cond_r1)[1])) * 100, 2),
            "maxdd_uncond_r2_pct": round(float(maxdd(run_r2c(uncond_r2_fn)[1])) * 100, 2),
            "maxdd_cond_r2_pct": round(float(maxdd(run_r2c(cond_r2)[1])) * 100, 2),
            # R3c 是 per-event 损益,不是 NAV,改报:最差单笔盈亏
            "r3_min_event_uncond_pct": round(float(min(_r3_nets_uncond, default=0.0)) * 100, 2),
            "r3_min_event_cond_pct": round(float(min(_r3_nets_cond, default=0.0)) * 100, 2),
            "r3_n_events_uncond": n_r3_uncond,
        }

    out = {
        "task": "T-093",
        "windows": WINDOWS,
        "n_shuffles": N_SHUFFLES,
        "seed": SEED,
        "block_weeks": BLOCK_WEEKS,
        "pre_registered": True,
        "results_by_window": results,
        "verdicts": {
            w: {
                "R1c_PASS": results[w]["R1c"]["excess_cond_vs_uncond_pct"] > 0 and results[w]["R1c"]["shuffle_pct"] >= 90,
                "R2c_PASS": results[w]["R2c"]["excess_cond_vs_uncond_pct"] > 0 and results[w]["R2c"]["shuffle_pct"] >= 90,
                "R3c_PASS": results[w]["R3c"]["excess_cond_vs_uncond_pct"] > 0 and results[w]["R3c"]["shuffle_pct"] >= 90,
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