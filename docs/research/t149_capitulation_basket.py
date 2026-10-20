"""T-149 / S-635 — 投降篮子:全市场冲洗日(D)的第二天开盘,全宇宙宽止损 2.5×ATR + SMA20 出场,
捕鱼数与每条鱼票价是否胜过同年随机同样多的日子 × 200。

照 S-635 原文(台账 2026-10-20 15:54 UTC 预注册,写于对冲洗日篮子算任何结果之前):

  冲洗日 F = S-616 定义(按未平仓市值加权的合约 OI 日变化 ≤ −5% 且 BTC 日收益 ≤ −4%)。
           读 deriv_metrics_daily 的 oi_value_close(n_points ≥ 200)、binance_hist。
  篮子     F 的第二天开盘,宇宙(binance_hist、rn ≥ 220、30 日均成交额 ≥ 500 万美元、
           去 USDC / BTCDOM / DEFI)里每个名字各开一张:止损 = max(信号日 low, 进场 − 2.5×ATR14),
           收盘破 SMA20 次日开盘出,120 根到期,R 含 0.4% 来回成本,
           同名 30 天内只开一次(相邻冲洗日合并)。
  对照     同年随机抽同样多的日子,同样的篮子,200 次。
  判据 ①  篮子捕到的鱼数(S-618 定义)≥ 随机 200 次的第 190 大(单侧 ≥ 90 分位,index 189 sort asc)
  判据 ②  每条鱼的票价(没在鱼上票 R 合计 / 捕到鱼数) < 随机 200 次的第 11 小(单侧 ≤ 5 分位,index 10 sort asc)
  只报     总 R、按冲洗日分、按慢状态(S-627 闸门)、子篮子:大跌后 3 天内又站回 SMA20。
  复用     T-141 / T-145 的票与鱼代码(S-618 定义);先复现 S-618 鱼数作自检。

读库用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'],不读 .env、不打印 key。
零分布就 permutation-of-trade-by-year + 同年随机日,按预注册在脚本里写。
"""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

# ── env / 常数 ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("env SUPABASE_URL / SUPABASE_KEY missing")

EXCLUDED = {"USDC", "BTCDOM", "DEFI"}
MIN_RN = 220
MIN_ADV30 = 5e6
K_STOP = 2.5
COST = 0.004
FISH_BARS = 120
SEED = 20261020  # 预注册日的日期
N_TRIALS = 200  # 随机对照次数(预注册写 200)
DERIV_NPOINTS_MIN = 200  # S-616 的 n_points ≥ 200 过滤

CACHE_DIR = "/Volumes/CometCloudAI/cometcloud-local/_cache/t149"
os.makedirs(CACHE_DIR, exist_ok=True)
OHLCV_PATH = f"{CACHE_DIR}/binance_raw.json"
DERIV_PATH = f"{CACHE_DIR}/deriv_metrics_daily.json"
OUT_JSON = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-149_results.json"


# ── 拉数(全量) ────────────────────────────────────────────────────────────────
def fetch_all(table, extra_params, out_path):
    hdr = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
           "Prefer": "count=exact"}
    page = 0
    pagesize = 1000
    rows = []
    while True:
        q = urllib.parse.urlencode({**extra_params, "limit": str(pagesize),
                                     "offset": str(page * pagesize)})
        url = f"{SUPABASE_URL}/rest/v1/{table}?{q}"
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=120) as r:
            chunk = json.loads(r.read().decode())
        rows.extend(chunk)
        if len(chunk) < pagesize:
            break
        page += 1
        if page > 5000:
            print(f"WARN: {table} hit page cap, partial")
            break
    with open(out_path, "w") as f:
        json.dump(rows, f)
    print(f"# {table}: pulled {len(rows)} rows -> {out_path}")
    return rows


def ensure_ohlcv():
    if os.path.exists(OHLCV_PATH):
        with open(OHLCV_PATH) as f:
            rows = json.load(f)
        print(f"# ohlcv_daily (cached): {len(rows)}")
        return rows
    rows = fetch_all("ohlcv_daily",
                     {"select": "symbol,trade_date,open,high,low,close,volume",
                      "source": "eq.binance_hist", "order": "symbol.asc,trade_date.asc"},
                     OHLCV_PATH)
    return rows


def ensure_deriv():
    if os.path.exists(DERIV_PATH):
        with open(DERIV_PATH) as f:
            rows = json.load(f)
        print(f"# deriv_metrics_daily (cached): {len(rows)}")
        return rows
    rows = fetch_all("deriv_metrics_daily",
                     {"select": "symbol,d,oi_value_close,n_points",
                      "order": "d.asc,symbol.asc"},
                     DERIV_PATH)
    return rows


# ── 冲洗日 S-616 ─────────────────────────────────────────────────────────────
def find_flush_days(deriv, ohlcv_by_sym):
    """总 oi_value_close (n_points>=200) 日变化 ≤ -5% 且 BTC 日收益 ≤ -4% 的日子。

    修正(S-616 prereg 原口径):宇宙按 S-616 也是「30 日均成交额 ≥ 500 万美元」
    当日有效;这里的 oi_value 聚合只对进入当日宇宙的符号求和。
    """
    # build per-day universe symbols (ADV30 ≥ 5M, i + 1 >= MIN_RN) like S-616's universe gate
    day_sym_adv = defaultdict(set)
    sym_idx = {}
    btc = ohlcv_by_sym.get("BTC")
    if btc is None:
        sys.exit("ERR: no BTC in binance_hist")
    for sym, info in ohlcv_by_sym.items():
        n = info["n"]
        d = info["d"]
        for i in range(n):
            if i + 1 < MIN_RN:
                continue
            if info["adv30"][i] < MIN_ADV30:
                continue
            day_sym_adv[d[i]].add(sym)
        sym_idx[sym] = d

    sum_oi = defaultdict(float)
    sym_cnt = defaultdict(int)
    for r in deriv:
        if (r.get("n_points") or 0) < DERIV_NPOINTS_MIN:
            continue
        if r.get("oi_value_close") is None:
            continue
        d = r["d"]
        sym = r["symbol"]
        if sym not in day_sym_adv.get(d, set()):
            continue
        sum_oi[d] += float(r["oi_value_close"])
        sym_cnt[d] += 1
    days = sorted(sum_oi)
    oi_change = {}
    for i, d in enumerate(days):
        if i == 0:
            continue
        prev = sum_oi[days[i - 1]]
        cur = sum_oi[d]
        if prev > 0:
            oi_change[d] = (cur - prev) / prev

    btc_ret = {}
    for i in range(1, len(btc["c"])):
        prev = btc["c"][i - 1]
        if prev > 0:
            btc_ret[btc["d"][i]] = (btc["c"][i] - prev) / prev

    flush = []
    diagnostics_all = []
    for d in days:
        if d not in oi_change or d not in btc_ret:
            continue
        diagnostics_all.append((d, oi_change[d], btc_ret[d], sym_cnt[d]))
        if oi_change[d] <= -0.05 and btc_ret[d] <= -0.04:
            flush.append(d)
    return flush, {"oi_change": oi_change, "btc_ret": btc_ret,
                   "days": days, "sym_cnt": sym_cnt,
                   "diagnostics": diagnostics_all,
                   "btc_first": btc["d"][0], "btc_last": btc["d"][-1]}


# ── 价格整理 / 指标 ───────────────────────────────────────────────────────────
def build_per_symbol(rows):
    by_sym = defaultdict(list)
    for r in rows:
        if r["symbol"] in EXCLUDED:
            continue
        by_sym[r["symbol"]].append(r)
    out = {}
    for sym, rs in by_sym.items():
        rs.sort(key=lambda r: r["trade_date"])
        n = len(rs)
        o = [r["open"] for r in rs]
        h = [r["high"] for r in rs]
        l = [r["low"] for r in rs]
        c = [r["close"] for r in rs]
        d = [r["trade_date"] for r in rs]
        v = [r.get("volume") or 0.0 for r in rs]
        dv = [c[i] * v[i] for i in range(n)]
        pc = [c[0]] + c[:-1]
        tr = [max(h[i] - l[i], abs(h[i] - pc[i]), abs(l[i] - pc[i])) for i in range(n)]
        sma20 = [0.0] * n
        atr14 = [0.0] * n
        adv30 = [0.0] * n
        for i in range(n):
            lo20 = max(0, i - 19)
            sma20[i] = sum(c[lo20 : i + 1]) / (i - lo20 + 1)
            lo14 = max(0, i - 13)
            atr14[i] = sum(tr[lo14 : i + 1]) / (i - lo14 + 1)
            lo30 = max(0, i - 29)
            adv30[i] = sum(dv[lo30 : i + 1]) / (i - lo30 + 1)
        out[sym] = dict(n=n, o=o, h=h, l=l, c=c, d=d, dv=dv,
                        sma20=sma20, atr14=atr14, adv30=adv30)
    return out


# ── 篮子模拟器 ───────────────────────────────────────────────────────────────
def basket_for_dates(by, dates):
    """给定触发日列表,每张次日开盘,2.5×ATR14 止损,SMA20 出场,120 根到期,
    R 含 0.4% 成本,同名 30 天内只开一次(冷却)。
    """
    sig_dates = sorted(set(dates))
    if not sig_dates:
        return []
    trades = []
    last_entry_by_sym = {}
    d_index = {}
    for sym, info in by.items():
        d_index[sym] = {d: i for i, d in enumerate(info["d"])}
    for sig_d in sig_dates:
        for sym, info in by.items():
            if sig_d not in d_index[sym]:
                continue
            i = d_index[sym][sig_d]
            n = info["n"]
            if i + 1 >= n or i + 1 < MIN_RN:
                continue
            if info["adv30"][i] < MIN_ADV30 or info["atr14"][i] <= 0:
                continue
            entry_idx = i + 1
            entry = info["o"][entry_idx]
            stop = max(info["l"][i], entry - K_STOP * info["atr14"][i])
            if entry <= stop:
                continue
            if sym in last_entry_by_sym and entry_idx - last_entry_by_sym[sym] < 30:
                continue
            hi = min(entry_idx + FISH_BARS, n - 1)
            k_idx = None
            for j in range(entry_idx, hi + 1):
                if info["l"][j] <= stop or info["c"][j] < info["sma20"][j]:
                    k_idx = j
                    break
            if k_idx is None:
                xi, xp = hi, info["c"][hi]
            elif info["l"][k_idx] <= stop:
                if k_idx > entry_idx and info["o"][k_idx] <= stop:
                    xi, xp = k_idx, info["o"][k_idx]
                else:
                    xi, xp = k_idx, stop
            else:
                xi = k_idx + 1
                xp = info["o"][xi] if xi < n else info["c"][k_idx]
            r = ((xp - entry) / (entry - stop)
                 - COST * entry / (entry - stop))
            lo_i = entry_idx + 1
            hi_i = min(entry_idx + FISH_BARS, n - 1)
            if hi_i >= lo_i:
                fmh = max(info["h"][lo_i : hi_i + 1])
                fmc = max(info["c"][lo_i : hi_i + 1])
            else:
                fmh = fmc = entry
            on_fish = max(fmh, fmc) >= 3.0 * entry
            exit_d_safe = info["d"][xi] if xi < n else info["d"][-1]
            trades.append(dict(
                sym=sym, sig_d=info["d"][i],
                entry_d=info["d"][entry_idx], exit_d=exit_d_safe,
                entry=entry, stop=stop, exit_price=xp, R=r,
                fish_caught=on_fish, fish_pmax=max(fmh, fmc) / entry - 1.0,
                year=info["d"][entry_idx][:4],
                entry_idx=entry_idx, exit_idx=xi,
            ))
            last_entry_by_sym[sym] = entry_idx
    return trades


def summarize(trades, label, sig_dates):
    if not trades:
        return dict(label=label, n=0, n_fish=0, n_dates=len(sig_dates),
                    total_r=0.0, mean_r=0.0, ticket_price=None)
    n = len(trades)
    fish = sum(1 for t in trades if t["fish_caught"])
    off = [t for t in trades if not t["fish_caught"]]
    ticket_price = sum(t["R"] for t in off) / fish if fish else None
    return dict(
        label=label, n=n, n_fish=fish, n_dates=len(sig_dates),
        total_r=sum(t["R"] for t in trades),
        mean_r=sum(t["R"] for t in trades) / n,
        ticket_price=ticket_price,
    )


# ── S-618 自检:复现鱼数 ─────────────────────────────────────────────────────
def selfcheck_s618(by):
    fish_count = 0
    fish_runs = 0
    sample_sym_cnt = 0
    for sym, info in by.items():
        n = info["n"]
        d = info["d"]
        if not d or d[-1] < "2020-03-01":
            continue
        lo = 0
        while lo < n and d[lo] < "2020-03-01":
            lo += 1
        hi_run = n - 1
        while hi_run >= 0 and d[hi_run] > "2026-06-20":
            hi_run -= 1
        if hi_run - FISH_BARS < lo:
            continue
        sample_sym_cnt += 1
        hits = []
        for i in range(max(lo + MIN_RN - 1, lo + 1), hi_run + 1):
            if info["adv30"][i] < MIN_ADV30:
                continue
            lo_i = i + 1
            hi_i = min(i + FISH_BARS, n - 1)
            if hi_i <= lo_i:
                continue
            fmh = max(info["h"][lo_i : hi_i + 1])
            fmc = max(info["c"][lo_i : hi_i + 1])
            if max(fmh, fmc) >= 3.0 * info["c"][i]:
                hits.append(i)
        runs = []
        last = None
        for i in hits:
            if last is None or i - last > 30:
                runs.append(i)
                last = i
        fish_runs += len(runs)
        fish_count += len(hits)
    return dict(n_fish_unmerged=fish_count, n_fish_runs=fish_runs,
                n_symbols=sample_sym_cnt)


# ── 主函数 ──────────────────────────────────────────────────────────────────
def main():
    rows = ensure_ohlcv()
    deriv = ensure_deriv()
    by = build_per_symbol(rows)
    print(f"# symbols (excl. USDC/BTCDOM/DEFI): {len(by)}")
    if "BTC" not in by:
        sys.exit("no BTC in binance_hist")
    flush_days, aux = find_flush_days(deriv, by)
    print(f"# 冲洗日(预注册口径): {len(flush_days)}")
    print(f"# BTC date coverage: {aux['btc_first']} → {aux['btc_last']}")
    print(f"# deriv days: {len(aux['days'])}")
    # diagnostics 输出最严重的 10 + tail
    digs = aux["diagnostics"]
    digs_sorted = sorted(digs, key=lambda x: x[1])
    print("# 最严重的 10 个 oi_chg 日 (d, oi_chg, btc_ret, sym_cnt):")
    for r in digs_sorted[:10]:
        print(f"  {r}")
    print("# 全部 flush 日详情 (d, oi_chg, btc_ret, sym_cnt):")
    for d in flush_days:
        idx = [i for i, r in enumerate(digs) if r[0] == d]
        if idx:
            print(f"  flush {digs[idx[0]]}")

    # 治疗组:每个冲洗日开一张/名,信号日 ≤ BTC 末日 - 1
    last_btc_d = max(by["BTC"]["d"])
    flush_tradeable = [d for d in flush_days if d < last_btc_d]
    print(f"\n# tradeable flush days (signal ≤ {last_btc_d}): {len(flush_tradeable)}")
    treat_trades = basket_for_dates(by, flush_tradeable)
    treat_sum = summarize(treat_trades, "treatment_flush", flush_tradeable)
    print("\n## treatment_flush:")
    print(json.dumps(treat_sum, indent=2, default=str))

    # 对照 × 200:同年随机抽同样多的日子(从非冲洗日随机抽,匹配每年)
    rng = random.Random(SEED)
    flush_set = set(flush_tradeable)
    flush_by_year = defaultdict(list)
    for d in flush_tradeable:
        flush_by_year[d[:4]].append(d)
    # 非冲洗日的池子:满足 (i) signal_d < last_btc_d (ii) signal_d 不在 flush_set
    # (iii) 至少一个名字当日 ADV30 ≥ 5M 的日子(篮子才有真实候选),用来保「对照»
    # 仍是与治疗组同样的可执行篮子
    day_has_universe = set()
    for sym, info in by.items():
        for i, d in enumerate(info["d"]):
            if d >= last_btc_d:
                continue
            if i + 1 < MIN_RN:
                continue
            if info["adv30"][i] >= MIN_ADV30:
                day_has_universe.add(d)
    eligible_pool = sorted(d for d in day_has_universe if d not in flush_set)
    eligible_by_year = defaultdict(list)
    for d in eligible_pool:
        eligible_by_year[d[:4]].append(d)
    print(f"\n# control pool: {len(eligible_pool)} non-flush days with universe; by_year: "
          + ", ".join(f"{y}={len(eligible_by_year[y])}" for y in sorted(eligible_by_year)))
    n_flush = len(flush_tradeable)
    control_trials = []
    sample_log = []
    if n_flush == 0:
        print("WARN: 0 flush days; no controls")
    else:
        for trial in range(N_TRIALS):
            # 同年:把治疗组的年与每年冲洗日数映射,从该年的 eligible_pool 抽同样多日
            sample = []
            for y, ys_flush in flush_by_year.items():
                k = len(ys_flush)
                pool_y = eligible_by_year.get(y, [])
                if len(pool_y) < k:
                    # 该年非冲洗日不够,补齐:本年内全用上 + 跨年补
                    sample.extend(pool_y)
                    deficit = k - len(pool_y)
                    others = [d for yy, lst in eligible_by_year.items() if yy != y for d in lst]
                    sample.extend(rng.sample(others, min(deficit, len(others))))
                else:
                    sample.extend(rng.sample(pool_y, k))
            ct = basket_for_dates(by, sample)
            control_trials.append(summarize(ct, f"ctrl_{trial}", sample))
            if trial < 5:
                sample_log.append(sample[:5])
    fish_counts = sorted(t["n_fish"] for t in control_trials)
    ticket_prices = sorted([t["ticket_price"] for t in control_trials
                            if t["ticket_price"] is not None])
    obs_fish = treat_sum["n_fish"]
    obs_ticket = treat_sum["ticket_price"]

    fish_190 = fish_counts[189] if len(fish_counts) >= 200 else max(fish_counts)
    ticket_11 = ticket_prices[10] if len(ticket_prices) >= 200 else (min(ticket_prices) if ticket_prices else None)

    # 自检
    sc = selfcheck_s618(by)
    print(f"\n# S-618 自检: n_fish_runs = {sc['n_fish_runs']} (期望 ~287), unmerged = {sc['n_fish_unmerged']}")

    res = dict(
        meta=dict(seed=SEED,
                  n_flush_total=len(flush_days),
                  n_flush_tradeable=len(flush_tradeable),
                  n_per_treatment=n_flush, n_trials=N_TRIALS,
                  symbols=len(by), btc_first=aux["btc_first"],
                  btc_last=aux["btc_last"], deriv_rows=len(deriv),
                  n_deriv_days=len(aux["days"]),
                  worst_10_oi_chg=digs_sorted[:10],
                  control_pool_size=len(eligible_pool),
                  control_pool_by_year={y: len(eligible_by_year[y]) for y in sorted(eligible_by_year)}),
        flush_days=flush_days,
        flush_tradeable=flush_tradeable,
        treatment=treat_sum,
        control_distribution_fish=dict(
            n=len(fish_counts),
            min=fish_counts[0], max=fish_counts[-1],
            median=fish_counts[len(fish_counts) // 2],
            p10=fish_counts[len(fish_counts) // 10],
            p50=fish_counts[len(fish_counts) // 2],
            p90=fish_counts[(len(fish_counts) * 9) // 10],
            p190_index_189=fish_190,
            obs=obs_fish,
            obs_pct_rank_le=(sum(1 for x in fish_counts if x <= obs_fish) / len(fish_counts)) if fish_counts else None,
            obs_pct_rank_strict=(sum(1 for x in fish_counts if x < obs_fish) / len(fish_counts)) if fish_counts else None,
            decision_1_pass=obs_fish >= fish_190,
        ),
        control_distribution_ticket=dict(
            n=len(ticket_prices),
            min=ticket_prices[0], max=ticket_prices[-1],
            median=ticket_prices[len(ticket_prices) // 2],
            p10=ticket_prices[len(ticket_prices) // 10],
            p90=ticket_prices[(len(ticket_prices) * 9) // 10],
            p11_index_10=ticket_11,
            obs=obs_ticket,
            obs_pct_rank_ge=(sum(1 for x in ticket_prices if x >= obs_ticket) / len(ticket_prices)) if ticket_prices and obs_ticket is not None else None,
            obs_pct_rank_strict_ge=(sum(1 for x in ticket_prices if x > obs_ticket) / len(ticket_prices)) if ticket_prices and obs_ticket is not None else None,
            decision_2_pass=(obs_ticket is not None and ticket_11 is not None and obs_ticket < ticket_11),
        ),
        control_first10=control_trials[:10],
        control_last5=control_trials[-5:],
        selfcheck_s618=sc,
    )

    # 年分布:治疗
    years_t = defaultdict(int)
    for t in treat_trades:
        years_t[t["sig_d"][:4]] += 1
    res["treatment_by_year"] = dict(years_t)
    res["treatment_yearly"] = {}
    for y in sorted({t["year"] for t in treat_trades}):
        lst = [t for t in treat_trades if t["year"] == y]
        res["treatment_yearly"][y] = dict(
            n=len(lst), fish=sum(1 for t in lst if t["fish_caught"]),
            total_r=sum(t["R"] for t in lst), mean_r=sum(t["R"] for t in lst) / len(lst),
        )

    # 子篮子:信号日后 3 日内收盘 ≥ 当日 SMA20(再次站回)
    sub = []
    for t in treat_trades:
        info = by[t["sym"]]
        d = info["d"]
        try:
            sig_i = d.index(t["sig_d"])
        except ValueError:
            continue
        for k in range(1, 4):
            j = sig_i + k
            if j >= info["n"]:
                break
            if info["c"][j] >= info["sma20"][j]:
                sub.append(t)
                break
    nosub = [t for t in treat_trades if t not in sub]
    res["treatment_subbounce"] = summarize(sub, "sub_bounce", sorted(set(t["sig_d"] for t in sub)))
    res["treatment_nosubbounce"] = summarize(nosub, "no_sub_bounce", sorted(set(t["sig_d"] for t in nosub)))

    print("\n## FULL RESULTS")
    print(json.dumps(res, indent=2, default=str))
    with open(OUT_JSON, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\n# wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
