#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-205 / S-690 独立复算 —— R-v2 的票按**开票日**规模中性 OI/市值分位分组:
H(前 1/3)是不是更差、是不是偏砍大鱼。

严格照 REFUTATION_LEDGER.md 的 **S-690**(2026-10-27 04:33 UTC 预注册)一字不改实现。
A 道独立复算(T-205):交付前不读 docs/research/s690_*。

用法:
    python3 t205_rv2_oi_filter.py --mode selftest   # 统计机器自检(合成数据,已知答案)
    python3 t205_rv2_oi_filter.py --mode full       # 全量,写 t205_results.json

零分布只用 src/data/evaluation/apparatus.py 的 null_distribution / percentile_of
(月块自助的具体抽样步骤照 S-690 写死:按信号月整块重抽、2,000 次、种子 690)。

数据源(只读,publishable key;代码里只用 os.environ,不落盘任何 key):
    deriv_metrics_daily   Binance Vision —— oi_close(张) / oi_value_close(USD)
    asset_mcap_daily      source = coingecko_pro_market_chart —— price / mcap(按 symbol)
    cg_coin_mcap_daily    source = coingecko_pro_market_chart —— price / mcap(按 coin_id)
    perp_cg_map           symbol → coin_id 映射 + 价格校验结果(verdict / mult)
票源:docs/research/t197_results.json 的 tickets.A(exit_d 非空 = 908 张,S-684 全宇宙 A 臂)

缓存(可重跑,避免重复打库):<MAC_ROOT>/research/t205/_cache/*.jsonl
产物:docs/research/t205_results.json + <MAC_ROOT>/_reports/absorb_input/T-205_rv2_oi_filter.md
"""

import argparse
import collections
import datetime as dt
import json
import math
import os
import random
import statistics
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MAC_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
CACHE = os.path.join(MAC_ROOT, "research", "t205", "_cache")
REPORT_DIR = os.path.join(MAC_ROOT, "_reports", "absorb_input")

if REPO not in sys.path:
    sys.path.insert(0, REPO)
from src.data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    print("缺少 SUPABASE_URL / SUPABASE_KEY,退出", file=sys.stderr)
    sys.exit(2)

HDRS = {"apikey": KEY, "Authorization": "Bearer " + KEY}
PAGE = 1000          # PostgREST 服务端硬上限(实测 1000 行/请求)
WORKERS = 8

# ── 协议常量(全部来自 S-690,不许改) ──────────────────────────────────────
TICKETS_FILE = os.path.join(REPO, "docs", "research", "t197_results.json")
MCAP_FLOOR = 20_000_000.0     # 当天市值 ≥ 2000 万美元
MIN_OVERLAP = 30              # 映射校验:重叠日 ≥ 30
MAX_MED_ERR = 0.05            # 映射校验:median 相对误差 ≤ 0.05
H_CUT = 2.0 / 3.0             # H = p ≥ 2/3(高杠杆三分之一)
BOOT_DRAWS = 2000             # 月块自助 2,000 次
BOOT_SEED = 690
HALF_CUT = "2024-06-30"       # 两半切分:信号日 ≤ 2024-06-30 / 之后
BIG_R = 5.0                   # 「大鱼」= R ≥ 5
ALPHA = 0.05                  # p < 0.05
S689_START = "2023-01-01"     # S-689 的分析窗口起点(只用于「敏感性」那一档)

# 预注册没写死的三个选择:主口径 + 两个备选(同一条代码路径,结果写进 sensitivity)
PRIMARY_PCONV = "midrank"     # p = (平均名次 − 0.5) / n
PRIMARY_WINDOW = "full"       # 映射校验的重叠日窗口 = 该名字全部 OI 历史
PCONVS = ("midrank", "minmax", "rankn")
WINDOWS = ("full", "s689")


def log(*a):
    print(*a, file=sys.stderr)


# ── 取数(PostgREST;翻页一律带 order=,并行 + 落盘缓存) ───────────────────
def _get(path, params):
    u = URL + "/rest/v1/" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(u, headers=HDRS)
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else []


def _count(path, where, order, col="symbol"):
    p = {"select": col, "order": order, "limit": 1, "offset": 0}
    p.update(where)
    u = URL + "/rest/v1/" + path + "?" + urllib.parse.urlencode(p)
    h = dict(HDRS)
    h["Prefer"] = "count=exact"
    h["Range"] = "0-0"
    req = urllib.request.Request(u, headers=h)
    with urllib.request.urlopen(req, timeout=300) as resp:
        resp.read()
        cr = resp.headers.get("Content-Range") or ""
    tail = cr.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def fetch_rows(path, where, order, cols, cache_name, count_col="symbol"):
    """分页读全表(并行)。order 必带 —— 不带时 PostgREST 翻页边界会漂。"""
    os.makedirs(CACHE, exist_ok=True)
    cpath = os.path.join(CACHE, cache_name + ".jsonl")
    if os.path.exists(cpath) and os.path.getsize(cpath) > 0:
        rows = []
        with open(cpath) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        log("[fetch] %s: 缓存命中 %d 行(%s)" % (path, len(rows), cpath))
        return rows
    total = _count(path, where, order, count_col) or 0
    offsets = list(range(0, total, PAGE))
    log("[fetch] %s: %d 行 ⇒ %d 页" % (path, total, len(offsets)))

    def grab(off):
        p = {"select": cols, "order": order, "limit": PAGE, "offset": off}
        p.update(where)
        return _get(path, p)

    out = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, rows in enumerate(ex.map(grab, offsets)):
            out.extend(rows)
            if (i + 1) % 100 == 0:
                log("[fetch] %s: %d/%d 页" % (path, i + 1, len(offsets)))
    with open(cpath, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log("[fetch] %s: %d 行 ⇒ 缓存 %s" % (path, len(out), cpath))
    return out


# ── 统计工具 ────────────────────────────────────────────────────────────
def avg_rank(xs):
    """平均名次(1 起,并列取平均)—— 与 S-689 SQL 的
    rank() over (partition by d order by v) + (count(*) over (partition by d, v) − 1)/2 同义。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def spearman(a, b):
    if len(a) < 3:
        return None
    return pearson(avg_rank(a), avg_rank(b))


def ols_resid(y, x):
    """y = a + b·x 的残差。返回 (resid, b);x 无变化时返回 (None, None)。"""
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx == 0:
        return None, None
    sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    b = sxy / sxx
    a0 = my - b * mx
    return [y[i] - (a0 + b * x[i]) for i in range(n)], b


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def month_t(mvals):
    """按月聚类 t:月均 / 月标准差 × √月数(S-689 同式)。"""
    xs = list(mvals.values())
    n = len(xs)
    if n < 2:
        return None
    sd = statistics.stdev(xs)
    if sd == 0:
        return None
    return (sum(xs) / n) / sd * math.sqrt(n)


def pct_from_rank(rk, n, conv):
    """名次 → 分位 p ∈ [0,1]。三个口径:
    midrank = (名次 − 0.5)/n(主口径,H 的占比 ≈ 1/3)
    minmax  = (名次 − 1)/(n − 1)
    rankn   = 名次/n
    """
    if conv == "minmax":
        return (rk - 1.0) / (n - 1.0) if n > 1 else 0.5
    if conv == "rankn":
        return rk / n
    return (rk - 0.5) / n


# ── 名字层:CG 价源 + 映射校验(S-689 同一套) ────────────────────────────
def build_cg_by_symbol(rows):
    """asset_mcap_daily → {symbol: {coin_id: {d: (price, mcap)}}}。
    S-689 SQL 用 upper(a.symbol) 对齐 deriv 侧,这里同样大写归一。"""
    per = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in rows:
        per[r["symbol"].upper()][r["coin_id"]][r["d"]] = (r["price"], r["mcap"])
    return per


def pick_coin(by_coin):
    """一个 symbol 多个 coin_id ⇒ 取行数最多的那个(并列取字典序最小的 coin_id)。
    S-689 / S-690 未写这条 ⇒ 记进报告「协议问题」。"""
    return sorted(by_coin.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]


def price_check(deriv, cg_price, mult, window="full"):
    """映射校验(S-689 原文):隐含价 = oi_value_close / oi_close;
    median |CG价×倍数 / 隐含价 − 1|;重叠日 ≥ 30 且 ≤ 0.05 才留。
    校验对每个名字做一次。window='full' 用该名字全部 OI 历史;
    window='s689' 只用 d ≥ 2023-01-01 的日子(S-689 SQL 的口径,只作敏感性)。"""
    errs = []
    for d, (oi_c, oi_v) in deriv.items():
        if window == "s689" and d < S689_START:
            continue
        p = cg_price.get(d)
        if p is None or p <= 0 or not oi_c or not oi_v or oi_c <= 0:
            continue
        implied = oi_v / oi_c
        if implied <= 0:
            continue
        errs.append(abs(p * mult / implied - 1.0))
    n = len(errs)
    if n < MIN_OVERLAP:
        return False, n, None, "重叠日 %d < %d" % (n, MIN_OVERLAP)
    med = statistics.median(errs)
    if med > MAX_MED_ERR:
        return False, n, med, "median 相对误差 %.4f > %.2f" % (med, MAX_MED_ERR)
    return True, n, med, None


# ── 截面 ────────────────────────────────────────────────────────────────
def build_cross(kept, deriv, cg_series, signal_days):
    """逐日截面:当天 r 有定义(oi_value_close > 0)、当天市值 ≥ 2000 万的全部名字。
    存下 names + resid(残差),分位 p 留到分组时按口径算。"""
    cross = {}
    for d in signal_days:
        vals = []
        for s in kept:
            oi_c, oi_v = deriv[s].get(d, (None, None))
            if not oi_v or oi_v <= 0:
                continue
            mc = cg_series[s]["mcap"].get(d)
            if mc is None or mc < MCAP_FLOOR:
                continue
            vals.append((s, oi_v / mc, math.log(mc)))
        if len(vals) < 3:
            cross[d] = {"n": len(vals), "usable": False, "names": [], "resid": []}
            continue
        rr = avg_rank([v[1] for v in vals])
        rs = avg_rank([v[2] for v in vals])
        resid, beta = ols_resid(rr, rs)
        if resid is None:
            cross[d] = {"n": len(vals), "usable": False, "names": [], "resid": []}
            continue
        cross[d] = {"n": len(vals), "usable": True, "names": [v[0] for v in vals],
                    "resid": resid, "beta": beta, "ranks": avg_rank(resid)}
    return cross


def group_tickets(tickets, cross, kept, deriv, cg_series, pconv):
    """逐票分组:p = 当天残差分位;H = p ≥ 2/3。返回 (rows, excl)。"""
    rows, excl = [], []
    for t in tickets:
        s, d = t["symbol"], t["signal_d"]
        cd = cross.get(d)
        if cd is None or not cd["usable"]:
            excl.append({"symbol": s, "signal_d": d, "r": t["r"], "exit_d": t.get("exit_d"),
                         "reason": "当天截面不可用(该日可入截面的名字 %d 个 < 3)" % (cd["n"] if cd else 0),
                         "reason_code": "no_cross_section"})
            continue
        if s not in kept:
            why = kept.get(s, {}).get("reason", "名字映射校验不过或无 CG 价源")
            excl.append({"symbol": s, "signal_d": d, "r": t["r"], "exit_d": t.get("exit_d"),
                         "reason": why, "reason_code": "name_dropped"})
            continue
        if s not in cd["names"]:
            oi_c, oi_v = deriv[s].get(d, (None, None))
            mc = cg_series[s]["mcap"].get(d)
            if not oi_v or oi_v <= 0:
                why, code = "票名当天没有 Binance OI(oi_value_close 无值)", "no_oi_on_day"
            elif mc is None:
                why, code = "票名当天没有 CG 市值", "no_mcap_on_day"
            else:
                why, code = "票名当天市值 < 2000 万", "mcap_below_floor"
            excl.append({"symbol": s, "signal_d": d, "r": t["r"], "exit_d": t.get("exit_d"),
                         "reason": why, "reason_code": code})
            continue
        i = cd["names"].index(s)
        p = pct_from_rank(cd["ranks"][i], cd["n"], pconv)
        rows.append({"symbol": s, "signal_d": d, "exit_d": t.get("exit_d"), "r": t["r"], "p": p,
                     "group": "H" if p >= H_CUT else "L", "n_names": cd["n"]})
    return rows, excl


# ── 统计量(照 S-690) ───────────────────────────────────────────────────
def main_stats(rows):
    """主统计量 + 三条判定 + 副统计量。"""
    H = [r for r in rows if r["group"] == "H"]
    L = [r for r in rows if r["group"] == "L"]
    mean_h = mean([r["r"] for r in H])
    mean_l = mean([r["r"] for r in L])
    diff = (mean_h - mean_l) if (mean_h is not None and mean_l is not None) else None

    # 月块自助:按信号月整块重抽 2,000 次(种子 690),p = 抽样差 ≥ 0 的比例
    by_m = {}
    for r in rows:
        by_m.setdefault(r["signal_d"][:7], []).append(r)
    months = sorted(by_m)
    null = None
    p_boot = None
    if months and H and L:
        def draw(rng):
            pool = []
            for _ in range(len(months)):
                pool.extend(by_m[months[int(rng.integers(len(months)))]])
            hs = [t["r"] for t in pool if t["group"] == "H"]
            ls = [t["r"] for t in pool if t["group"] == "L"]
            if not hs or not ls:
                return float("nan")
            return sum(hs) / len(hs) - sum(ls) / len(ls)

        null = null_distribution(draw, BOOT_DRAWS, BOOT_SEED)
        finite = [float(x) for x in null if x == x]
        p_boot = (sum(1 for x in finite if x >= 0) / len(finite)) if finite else None

    # 两半:信号日 ≤ 2024-06-30 / 之后
    def half_diff(sel):
        hh = [r["r"] for r in rows if r["group"] == "H" and sel(r)]
        ll = [r["r"] for r in rows if r["group"] == "L" and sel(r)]
        if not hh or not ll:
            return None, len(hh), len(ll)
        return mean(hh) - mean(ll), len(hh), len(ll)

    h1 = half_diff(lambda r: r["signal_d"] <= HALF_CUT)
    h2 = half_diff(lambda r: r["signal_d"] > HALF_CUT)

    # ③ 不偏砍大鱼:H 里 R ≥ 5 的票占全部 R ≥ 5 票的比例 ≤ H 占全部票的比例
    n_big_all = sum(1 for r in rows if r["r"] >= BIG_R)
    n_big_h = sum(1 for r in H if r["r"] >= BIG_R)
    share_big_h = (n_big_h / n_big_all) if n_big_all else None
    share_h = (len(H) / len(rows)) if rows else None
    cond3 = (share_big_h <= share_h) if (share_big_h is not None and share_h is not None) else None

    cond1 = (diff is not None and diff < 0 and p_boot is not None and p_boot < ALPHA)
    cond2 = (h1[0] is not None and h2[0] is not None and h1[0] < 0 and h2[0] < 0)
    verdict = bool(cond1 and cond2 and cond3)

    # 副统计量(不判):p 与 R 的 Spearman(按月聚类 t);H / L 各自的统计
    m_spear = {}
    for m, tk in by_m.items():
        v = spearman([t["p"] for t in tk], [t["r"] for t in tk])
        if v is not None:
            m_spear[m] = v
    pooled_spear = spearman([r["p"] for r in rows], [r["r"] for r in rows])

    def grp_stats(g):
        rs = [r["r"] for r in g]
        tot_all = sum(r["r"] for r in rows)
        return {
            "n": len(g),
            "mean_r": mean(rs),
            "median_r": statistics.median(rs) if rs else None,
            "win_rate": (sum(1 for x in rs if x > 0) / len(rs)) if rs else None,
            "sum_r": sum(rs),
            "sum_r_share": (sum(rs) / tot_all) if tot_all else None,
            "n_big_r_ge5": sum(1 for x in rs if x >= BIG_R),
            "median_p": statistics.median([r["p"] for r in g]) if g else None,
        }

    out = {
        "n_used": len(rows),
        "n_H": len(H),
        "n_L": len(L),
        "mean_r_H": mean_h,
        "mean_r_L": mean_l,
        "diff_H_minus_L": diff,
        "bootstrap": {"draws": BOOT_DRAWS, "seed": BOOT_SEED,
                      "p_diff_ge_0": p_boot,
                      "n_finite_draws": len(finite) if null is not None else 0,
                      "percentile_of_0_apparatus": percentile_of(0.0, null) if null is not None else None,
                      "draws_summary": ({"mean": mean(finite), "median": statistics.median(finite),
                                         "p05": sorted(finite)[int(0.05 * len(finite))],
                                         "p95": sorted(finite)[int(0.95 * len(finite))]}
                                        if finite else None)},
        "halves": {"h1_le_" + HALF_CUT: {"diff": h1[0], "n_H": h1[1], "n_L": h1[2]},
                   "h2_gt_" + HALF_CUT: {"diff": h2[0], "n_H": h2[1], "n_L": h2[2]}},
        "big_fish": {"n_big_all": n_big_all, "n_big_in_H": n_big_h,
                     "share_big_in_H": share_big_h, "share_H": share_h,
                     "cond3_no_big_fish_biased_cut": cond3},
        "judgement": {
            "cond1_diff_neg_and_p_lt_05": bool(cond1),
            "cond2_both_halves_neg": bool(cond2),
            "cond3_not_bias_cut_big_fish": bool(cond3),
            "verdict_all_three": verdict,
            "verdict_text": ("✅ 过滤值得上前向(开一条纸面前向臂「R-v2 去掉 H」与 R-v2 并排,不直接改真钱规则)"
                             if verdict else "❌ 只记(不作成交过滤)"),
        },
        "secondary": {
            "spearman_p_r_by_month": {m: round(v, 6) for m, v in sorted(m_spear.items())},
            "spearman_p_r_month_t": month_t(m_spear),
            "n_months_with_spearman": len(m_spear),
            "pooled_spearman_p_r": pooled_spear,
            "H": grp_stats(H),
            "L": grp_stats(L),
        },
    }
    return out


# ── 主流程 ──────────────────────────────────────────────────────────────
def load_tickets():
    with open(TICKETS_FILE) as f:
        d = json.load(f)
    tk = [t for t in d["tickets"]["A"] if t.get("exit_d")]
    return tk, d.get("meta", {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["selftest", "full"], default="full")
    ap.add_argument("--out", default=os.path.join(HERE, "t205_results.json"))
    a = ap.parse_args()

    if a.mode == "selftest":
        return selftest()

    now = dt.datetime.now(dt.timezone.utc)
    log("[run] now(UTC) =", now.isoformat())

    tickets, tmeta = load_tickets()
    log("[tickets] %d 张(exit_d 非空);票名 %d 个" % (len(tickets), len({t['symbol'] for t in tickets})))
    signal_days = sorted({t["signal_d"] for t in tickets})
    log("[tickets] 信号日 %d 个(%s → %s)" % (len(signal_days), signal_days[0], signal_days[-1]))

    # ── 取数 ────────────────────────────────────────────────────────────
    pm_rows = fetch_rows("perp_cg_map", {}, "symbol.asc",
                         "symbol,coin_id,verdict,mult,med_err,n_overlap,query_symbol,note", "perp_cg_map")
    pm = {r["symbol"]: r for r in pm_rows}
    resolved = {s: r for s, r in pm.items() if (r.get("verdict") or "") == "resolved"}
    pending = sorted(s for s, r in pm.items() if (r.get("verdict") or "") != "resolved")
    log("[map] perp_cg_map %d 行(resolved %d, 未 resolved %d)" % (len(pm), len(resolved), len(pending)))

    deriv_rows = fetch_rows("deriv_metrics_daily", {}, "symbol.asc,d.asc",
                            "symbol,d,oi_close,oi_value_close", "deriv_metrics_daily")
    deriv = {}
    for r in deriv_rows:
        deriv.setdefault(r["symbol"], {})[r["d"]] = (r["oi_close"], r["oi_value_close"])
    universe = sorted(deriv.keys())
    log("[deriv] %d 个名字,合计 %d 行" % (len(universe), len(deriv_rows)))

    am_rows = fetch_rows("asset_mcap_daily", {"source": "eq.coingecko_pro_market_chart"},
                          "symbol.asc,d.asc", "symbol,coin_id,d,price,mcap", "asset_mcap_daily")
    am_per = build_cg_by_symbol(am_rows)
    log("[cg] asset_mcap_daily %d 行,%d 个 symbol" % (len(am_rows), len(am_per)))

    need_coin = sorted({resolved[s]["coin_id"] for s in universe
                         if s in resolved and s.upper() not in am_per})
    cg_rows = []
    if need_coin:
        cg_rows = fetch_rows("cg_coin_mcap_daily", {"coin_id": "in.(" + ",".join(need_coin) + ")"},
                             "coin_id.asc,d.asc", "coin_id,d,price,mcap", "cg_coin_mcap_daily",
                             count_col="coin_id")
    cg_coin = {}
    for r in cg_rows:
        cg_coin.setdefault(r["coin_id"], {})[r["d"]] = (r["price"], r["mcap"])
    log("[cg] cg_coin_mcap_daily %d 行,%d 个 coin_id" % (len(cg_rows), len(cg_coin)))

    # ── CG 价源(来源优先级照 S-689:先 asset_mcap_daily 按 symbol,没有的用 perp_cg_map 的 coin_id)
    price_of = {}   # symbol → {d: price}
    mcap_of = {}    # symbol → {d: mcap}
    cg_src, cg_mult = {}, {}
    multi_coin = {}
    no_src = {}
    for s in universe:
        if s.upper() in am_per:
            by_coin = am_per[s.upper()]
            if len(by_coin) > 1:
                multi_coin[s] = sorted(by_coin.keys())
            cid = pick_coin(by_coin)
            series = by_coin[cid]
            price_of[s] = {k: v[0] for k, v in series.items()}
            mcap_of[s] = {k: v[1] for k, v in series.items()}
            cg_src[s] = "asset_mcap_daily"
            cg_mult[s] = 1.0
        elif s in resolved:
            cid = resolved[s]["coin_id"]
            series = cg_coin.get(cid)
            if not series:
                no_src[s] = "无 CG 价源(asset_mcap_daily 无此 symbol;perp_cg_map 的 coin_id 无日线)"
                continue
            price_of[s] = {k: v[0] for k, v in series.items()}
            mcap_of[s] = {k: v[1] for k, v in series.items()}
            cg_src[s] = "cg_coin_mcap_daily"
            rm = resolved[s].get("mult")
            cg_mult[s] = float(rm) if rm else (1000.0 if s.startswith("1000") else 1.0)
        else:
            no_src[s] = "无 CG 价源(asset_mcap_daily 无此 symbol;perp_cg_map 未 resolved)"
            continue
    cg_series = {s: {"price": price_of[s], "mcap": mcap_of[s]} for s in price_of}

    # ── 两个映射校验窗口:主口径 full(全历史) + 敏感性 s689(2023 起) ─────
    kept_by_window, dropped_by_window = {}, {}
    for window in WINDOWS:
        kept, dropped = {}, []
        for s in universe:
            if s in no_src:
                dropped.append({"symbol": s, "n_overlap": 0, "med_err": None, "src": None,
                                "reason": no_src[s]})
                continue
            ok, n_ov, med, why = price_check(deriv[s], price_of[s], cg_mult[s], window)
            if not ok:
                dropped.append({"symbol": s, "n_overlap": n_ov, "med_err": med, "src": cg_src[s],
                                "reason": why})
                continue
            kept[s] = {"n_overlap": n_ov, "med_err": med, "src": cg_src[s], "mult": cg_mult[s],
                       "reason": None}
        kept_by_window[window] = kept
        dropped_by_window[window] = dropped
        log("[map/%s] kept %d / dropped %d;其中靠 perp_cg_map 补的 %d 个"
            % (window, len(kept), len(dropped),
               sum(1 for v in kept.values() if v["src"] == "cg_coin_mcap_daily")))

    # ── 主口径:full 窗口 + midrank 分位 ───────────────────────────────
    kept = kept_by_window[PRIMARY_WINDOW]
    dropped = dropped_by_window[PRIMARY_WINDOW]
    cross = build_cross(kept, deriv, cg_series, signal_days)
    usable_days = sum(1 for v in cross.values() if v["usable"])
    log("[xs] 截面日 %d 个(可算 %d 个);当日名字数 min=%d max=%d"
        % (len(cross), usable_days, min(v["n"] for v in cross.values()), max(v["n"] for v in cross.values())))

    rows, excl = group_tickets(tickets, cross, kept, deriv, cg_series, PRIMARY_PCONV)
    log("[tickets] 进组 %d 张;剔除 %d 张" % (len(rows), len(excl)))
    log("[tickets] 剔除原因:", collections.Counter(e["reason_code"] for e in excl).most_common())

    res = {
        "task": "T-205",
        "prereg": "S-690 (REFUTATION_LEDGER.md, 2026-10-27 04:33 UTC)",
        "run_utc": now.isoformat(),
        "protocol_constants": {
            "mcap_floor_usd": MCAP_FLOOR, "h_cut": H_CUT, "boot_draws": BOOT_DRAWS,
            "boot_seed": BOOT_SEED, "half_cut_signal_d": HALF_CUT, "big_r": BIG_R,
            "alpha": ALPHA, "min_overlap": MIN_OVERLAP, "max_med_err": MAX_MED_ERR,
            "primary_pconv": PRIMARY_PCONV, "primary_check_window": PRIMARY_WINDOW,
            "percentile_convention": "p = (avg_rank(resid) − 0.5) / n(当天截面)",
            "null_distribution": "src/data/evaluation/apparatus.py:null_distribution(月份块重抽)",
        },
        "tickets_meta": tmeta,
        "coverage": {
            "n_tickets_total": len(tickets),
            "n_tickets_used": len(rows),
            "n_tickets_excluded": len(excl),
            "n_names_deriv": len(universe),
            "n_names_kept": len(kept),
            "n_names_dropped": len(dropped),
            "names_dropped": sorted(dropped, key=lambda x: x["symbol"]),
            "symbol_multi_coinid": multi_coin,
            "perp_cg_map_not_resolved": pending,
            "n_signal_days": len(signal_days),
            "n_cross_section_usable_days": usable_days,
            "cross_section_n_by_day": {d: cross[d]["n"] for d in signal_days},
            "excluded_reason_counts": dict(collections.Counter(e["reason_code"] for e in excl)),
        },
    }

    res["result"] = main_stats(rows)

    # ── 敏感性:预注册没写死的三个选择(同一份数据、同一条代码路径) ───────
    sens = {}
    for conv in PCONVS:
        rr, ee = group_tickets(tickets, cross, kept, deriv, cg_series, conv)
        st = main_stats(rr)
        sens["pconv=" + conv] = {
            "n_used": st["n_used"], "n_H": st["n_H"], "n_L": st["n_L"],
            "mean_r_H": st["mean_r_H"], "mean_r_L": st["mean_r_L"],
            "diff_H_minus_L": st["diff_H_minus_L"],
            "p_diff_ge_0": st["bootstrap"]["p_diff_ge_0"],
            "halves": st["halves"], "big_fish": st["big_fish"],
            "verdict_all_three": st["judgement"]["verdict_all_three"],
        }
    for window in WINDOWS:
        if window == PRIMARY_WINDOW:
            continue
        k2 = kept_by_window[window]
        c2 = build_cross(k2, deriv, cg_series, signal_days)
        rr, ee = group_tickets(tickets, c2, k2, deriv, cg_series, PRIMARY_PCONV)
        st = main_stats(rr)
        sens["check_window=" + window] = {
            "n_names_kept": len(k2),
            "names_dropped_vs_primary": sorted(set(d["symbol"] for d in dropped_by_window[window]) -
                                              set(d["symbol"] for d in dropped)),
            "n_used": st["n_used"], "n_H": st["n_H"], "n_L": st["n_L"],
            "mean_r_H": st["mean_r_H"], "mean_r_L": st["mean_r_L"],
            "diff_H_minus_L": st["diff_H_minus_L"],
            "p_diff_ge_0": st["bootstrap"]["p_diff_ge_0"],
            "halves": st["halves"], "big_fish": st["big_fish"],
            "verdict_all_three": st["judgement"]["verdict_all_three"],
        }
    res["sensitivity"] = sens

    # ── 探索性诊断(不改协议,只报) ─────────────────────────────────────
    by_year = collections.defaultdict(lambda: {"H": [], "L": []})
    for r in rows:
        by_year[r["signal_d"][:4]][r["group"]].append(r["r"])
    yearly = {y: {"H_n": len(v["H"]), "H_mean": mean(v["H"]), "L_n": len(v["L"]), "L_mean": mean(v["L"]),
                  "diff": (mean(v["H"]) - mean(v["L"])) if v["H"] and v["L"] else None}
              for y, v in sorted(by_year.items())}
    terc_stats = {}
    if rows:
        ps = sorted(r["p"] for r in rows)
        q1 = ps[len(ps) // 3]
        q2 = ps[2 * len(ps) // 3]
        buck = collections.defaultdict(list)
        for r in rows:
            b = "低" if r["p"] < q1 else ("中" if r["p"] < q2 else "高")
            buck[b].append(r["r"])
        terc_stats = dict((b, {"n": len(v), "mean_r": mean(v), "median_r": statistics.median(v),
                               "sum_r": sum(v), "n_big_r_ge5": sum(1 for x in v if x >= BIG_R),
                               "win_rate": sum(1 for x in v if x > 0) / len(v)})
                          for b, v in buck.items())
        terc_stats["_cuts"] = {"q1_p": q1, "q2_p": q2}
    pre2023 = [t for t in tickets if t["signal_d"] < "2023-01-01"]
    pre2023_with_oi = sum(1 for t in pre2023
                          if (deriv.get(t["symbol"], {}).get(t["signal_d"], (None, None))[1] or 0) > 0)
    names_post2023 = set(s for s, dd in deriv.items() if any(k >= S689_START for k in dd))

    res["exploratory"] = {
        "by_signal_year": yearly,
        "p_terciles_by_ticket": terc_stats,
        "top5_tickets_by_r": sorted(rows, key=lambda r: -r["r"])[:5],
        "n_tickets_signal_before_2023": len(pre2023),
        "n_pre2023_tickets_with_oi_value_on_day": pre2023_with_oi,
        "n_names_multi_coinid": len(multi_coin),
        "n_deriv_names_with_data_since_2023": len(names_post2023),
        "n_deriv_names_total": len(universe),
        "signal_days_with_lt30_names": sorted({r["signal_d"] for r in rows if r["n_names"] < 30}),
        "n_tickets_on_lt30_name_days": sum(1 for r in rows if r["n_names"] < 30),
    }
    res["tickets"] = rows
    res["excluded_tickets"] = excl
    with open(a.out, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    log("[out] wrote", a.out)
    return 0


# ── 自检(合成数据,已知答案) ─────────────────────────────────────────────
def selftest():
    ok = True
    rng = random.Random(690)

    # ① r 与规模无关时,残差必须保留 r 的信息(残差化没有把信号洗掉)
    n = 50
    size = [rng.gauss(10, 1) for _ in range(n)]
    r = [rng.gauss(0, 1) for _ in range(n)]
    rr, rs = avg_rank(r), avg_rank(size)
    resid, beta = ols_resid(rr, rs)
    pr = avg_rank(resid)
    ps = [pct_from_rank(pr[i], n, "midrank") for i in range(n)]
    rho = pearson(ps, r)
    print("① r 与规模无关时 ρ(残差分位, r) = %.4f(应 >0.8)" % rho)
    ok &= rho > 0.8

    # ② 规模驱动 r ⇒ 残差与规模无关
    r2 = [0.8 * size[i] + rng.gauss(0, 0.3) for i in range(n)]
    resid2, _ = ols_resid(avg_rank(r2), rs)
    rho2 = pearson(resid2, size)
    print("② ρ(残差, 规模) = %.4f(应 ≈0)" % rho2)
    ok &= abs(rho2) < 0.2

    # ③ OLS 残差 = y − (a0 + b·x)
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [2.1, 4.0, 6.2, 7.9]
    rd, bb = ols_resid(ys, xs)
    a0 = sum(ys) / 4 - bb * 2.5
    fit_err = max(abs(rd[i] - (ys[i] - (a0 + bb * xs[i]))) for i in range(4))
    print("③ OLS 残差自洽(最大偏差 %.2e)" % fit_err)
    ok &= fit_err < 1e-9

    # ④ 分组与主统计量:构造 H 更差 ⇒ diff ≈ −3
    rows = []
    for i in range(60):
        p = rng.random()
        rows.append({"p": p, "r": (-2.0 if p >= 2 / 3 else 1.0) + rng.gauss(0, 0.3),
                     "signal_d": "2024-%02d-01" % (1 + i % 12), "group": "H" if p >= 2 / 3 else "L"})
    hh = mean([t["r"] for t in rows if t["group"] == "H"])
    ll = mean([t["r"] for t in rows if t["group"] == "L"])
    print("④ 构造数据 H−L 差 = %.4f(应 ≈ −3)" % (hh - ll))
    ok &= (hh - ll) < -2.0

    # ⑤ 月块自助:走 apparatus 的 null_distribution(同种子可复现)+ p 的方向
    def draw(rng):
        by_m = {}
        for t in rows:
            by_m.setdefault(t["signal_d"][:7], []).append(t)
        months = sorted(by_m)
        pool = []
        for _ in range(len(months)):
            pool.extend(by_m[months[int(rng.integers(len(months)))]])
        return (mean([t["r"] for t in pool if t["group"] == "H"]) -
                mean([t["r"] for t in pool if t["group"] == "L"]))

    import numpy as np
    n1 = null_distribution(draw, 200, 690)
    n2_ = null_distribution(draw, 200, 690)
    p_hat = float((np.asarray(n1) >= 0).mean())
    print("⑤ apparatus 自助可复现 = %s; p(diff≥0) = %.4f(应 ≈0)"
          % (list(n1) == list(n2_), p_hat))
    ok &= (list(n1) == list(n2_)) and p_hat < 0.05

    # ⑥ 分位约定:p ∈ (0,1),且 p ≥ 2/3 的比例 ≈ 1/3
    n2 = 100
    pr2 = avg_rank(list(range(n2)))
    p2 = [pct_from_rank(v, n2, "midrank") for v in pr2]
    share = sum(1 for v in p2 if v >= 2 / 3) / n2
    print("⑥ H 占比 = %.3f(应 ≈1/3);p 范围 [%.3f, %.3f]" % (share, min(p2), max(p2)))
    ok &= abs(share - 1 / 3) < 0.02

    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
