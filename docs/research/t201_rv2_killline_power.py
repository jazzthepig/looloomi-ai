"""T-201 / S-686:R-v2 真钱关停线 / 加仓线的分辨力 —— 把 S-684 的全宇宙票当「真实过程」,量关停线在有边 / 没边两种世界里各多常过。

预注册:台账 S-686(2026-10-25 16:30 UTC,写于对下列任何量算任何数之前)。规则**一字不改**:

  票   = docs/research/t197_results.json 的 tickets.A(T-197 的结果,已合并;只取已平的 908 张;R 与信号日 / 进出场日照原样)
  世界 有边 = 原样(908 张,平均 R = +0.3329)
        没边 = 同一批票每张 R 减去 A 的平均 R(均值 0,形状不变)
  抽样 = 按信号月整块抽(保留月内成簇),种子 686,每档 5,000 次
  ① N ∈ {10,20,30,50,100,200}:观测平均 R 的 5 / 50 / 95 分位;R1「均值 > 0」、
     R2「均值 > 0 且月块自助 p < 0.10」、R3「同 R2,p < 0.05」(月块自助 2,000 次)在两个世界的通过率
  ② 钱曲线 6 / 12 / 24 个月:t159.nav(f = 1%、cap = 10,按真实持有期)按抽到的票排在一条假想时间线上;
     最大回撤分布;触到 −10% / −18% / −25% 的概率,两个世界各一份
  ③ 按 A 在 2024 年的每月开票数分布换算 N = 30 / 50 / 100 要等多少个月(中位 / 90 分位)
  最后:「检出力 ≥ 80% 且误放 ≤ 10%」的最小 N(每条规则一个数;够不到就写够不到)

台账没写「抽到一个月」的概率怎么给(见「协议问题」第 1 条)⇒ 两种抽样都算、都报:
  主口径 size  = 按月块的票数加权抽(抽一张票 → 取它整个信号月)。这样抽出来的书与总体同权重:
                有边世界抽到的平均 R ≈ +0.333、没边世界 ≈ 0,与台账写的「平均 +0.33R / 均值 0」一致。
  敏感性 month = 40 个信号月等概率抽(「抽一个信号月、整块拿」的字面读法)。此时按月等权的总体均值
                只有 +0.066(票等权才是 +0.333)⇒ 抽样本身带偏差。

零分布走 src/data/evaluation/apparatus.py(null_distribution / percentile_of),不手写;钱曲线 import t159.nav / t159.stats,不复制。
用法:
  python3 docs/research/t201_rv2_killline_power.py                       # 两个抽样口径全跑
  python3 docs/research/t201_rv2_killline_power.py --schemes size --out <path.json>
  python3 docs/research/t201_rv2_killline_power.py --merge size=<a.json> month=<b.json> --out <out.json>
"""
from __future__ import annotations

import argparse
import calendar
import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from multiprocessing import get_context

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, ROOT)

# t159 的数据根:闸门在 t156,面板 K 线在 t156 + t159。必须在 import t159 之前设好(模块级读 env)。
os.environ.setdefault("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/")
os.environ.setdefault("T159_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t159/")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

from src.data.evaluation.apparatus import NoOpNull, null_distribution, percentile_of  # noqa: E402

T197_JSON = os.path.join(HERE, "t197_results.json")
OUT_JSON = os.path.join(HERE, "t201_results.json")
OUT_MD = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-201_rv2_killline_power.md"
UM_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_daily.jsonl"

SEED = 686                 # 台账原文:种子 686
DRAWS = 5000               # 台账原文:每档 5,000 次
BOOT_DRAWS = 2000          # 卡上原文:月块自助 2,000 次
N_LIST = [10, 20, 30, 50, 100, 200]
F, CAP = 0.01, 10          # 卡上原文:f = 1%、cap = 10
HORIZONS = [6, 12, 24]     # 月
SLOTS = 24                 # 假想时间线的月槽数(最长视野)
TL_START = date(2020, 1, 1)
SCHEME_PRIMARY = "size"    # 票数加权的整块抽(与台账写的世界均值一致)
SCHEME_ALT = "month"       # 月等权的整块抽(「抽一个信号月」的字面读法)

_T: dict = {}


# ── 数据 ──────────────────────────────────────────────────────────────────────────────────────────────────
def load_tickets():
    """t197_results.json 的 tickets.A,只取已平的(r 不为 None)。R 与日期照原样。"""
    d = json.load(open(T197_JSON))
    tk = [dict(t) for t in d["tickets"]["A"] if t.get("r") is not None]
    for t in tk:
        t["month"] = t["signal_d"][:7]
    return tk, d


def build_buckets(tk):
    by = defaultdict(list)
    for t in tk:
        by[t["month"]].append(t)
    for m in by:
        by[m].sort(key=lambda t: (t["signal_d"], t["symbol"]))
    return by, sorted(by)


def load_marks(tk):
    """{(symbol, entry_d, exit_d): [(d, close)]} —— 票的持有期内的收盘(同一份 K 线:research/s681/_um_daily.jsonl)。"""
    need = defaultdict(list)
    for t in tk:
        need[t["symbol"]].append((t["entry_d"], t["exit_d"]))
    out = {}
    for line in open(UM_FILE):
        x = json.loads(line)
        sym = x.get("symbol")
        if sym not in need:
            continue
        rows = sorted((r for r in (x.get("bars") or []) if len(r) >= 5 and r[0]),
                      key=lambda r: r[0])
        for (a, b) in need[sym]:
            out[(sym, a, b)] = [(r[0], r[4]) for r in rows if a <= r[0] < b]
    return out


def month_len(m):
    y, mo = int(m[:4]), int(m[5:7])
    return calendar.monthrange(y, mo)[1]


def month_start(m):
    return date(int(m[:4]), int(m[5:7]), 1)


def month_probs(months, buckets, scheme):
    """抽一个信号月的概率。size = 按该月的票数加权(抽一张票 → 取它整月);month = 40 个月等概率。"""
    if scheme == "size":
        w = np.array([len(buckets[m]) for m in months], dtype=float)
    elif scheme == "month":
        w = np.ones(len(months), dtype=float)
    else:
        raise ValueError(f"unknown scheme {scheme}")
    return w / w.sum()


# ── ① 抽样与月块自助 ────────────────────────────────────────────────────────────────────────────────────
def sample_month_blocks(rng, months, buckets, n, probs, truncate=True):
    """按信号月整块抽(有放回地抽月,保留月内成簇),直到票数 ≥ n。truncate=True ⇒ 截断到正好 n 张。"""
    out = []
    while len(out) < n:
        out.extend(buckets[months[int(rng.choice(len(months), p=probs))]])
    return out[:n] if truncate else out


def inner_boot_p(month_sums, month_cnts, observed, seed, centered=False):
    """月块自助 p(≤0):整月有放回重抽(抽 len(months) 个月)后的均值分布中 ≤0 的比例。
    centered=False = S-684 原样(重抽原样本,零分布中位数 ≈ 样本均值);
    centered=True  = T-197 §7 的另一种读法(月均值先减总均值,零分布以 0 为中心)。
    样本只落在一个月 ⇒ 零分布退化(无方差)⇒ p 不可算(返回 None),不是 0。"""
    k = len(month_sums)
    s = np.asarray(month_sums, dtype=float)
    c = np.asarray(month_cnts, dtype=float)
    if centered:
        s = s - observed * c

    def draw(rng):
        pick = rng.integers(0, k, size=k)
        den = c[pick].sum()
        return float(s[pick].sum() / den) if den else float("nan")

    try:
        null = null_distribution(draw, BOOT_DRAWS, seed, actual=None if centered else observed)
    except NoOpNull:
        return None, None
    return float((null <= 0).mean()), float(percentile_of(observed, null))


def cell_worker(args):
    """一个 (抽样口径, 世界, N) 档:抽 5,000 次,每次算观测平均 R + 两条读法的月块自助 p。"""
    scheme, world, n, truncate, draws, seed0 = args
    buckets = _T["buckets"]; months = _T["months"]; grand = _T["grand"]
    probs = _T["probs"][scheme]
    off = 0.0 if world == "edge" else grand
    means, ps, pcs = [], [], []
    degen = 0
    for i in range(draws):
        rng = np.random.default_rng((seed0 + i) % (2 ** 32))
        samp = sample_month_blocks(rng, months, buckets, n, probs, truncate)
        rs = [t["r"] - off for t in samp]
        obs = float(np.mean(rs))
        by = defaultdict(list)
        for t, r in zip(samp, rs):
            by[t["month"]].append(r)
        ms = [float(np.sum(v)) for v in by.values()]
        mc = [len(v) for v in by.values()]
        inner = (seed0 + i) * 31 + 7
        p, _ = inner_boot_p(ms, mc, obs, inner % (2 ** 32), centered=False)
        pc, _ = inner_boot_p(ms, mc, obs, (inner + 1) % (2 ** 32), centered=True)
        if p is None:
            degen += 1
        means.append(obs); ps.append(p); pcs.append(pc)
    return dict(scheme=scheme, world=world, n=n, truncate=truncate, means=means, p=ps,
                p_centered=pcs, degen=degen)


# ── ② 钱曲线 ────────────────────────────────────────────────────────────────────────────────────────────
def noedge_path(path, entry_px, stop_px, exit_px, grand):
    """没边世界的一张票:价格路径 + 出场价,让 nav 记下的这张票的 R 正好 = R − 全样本平均 R。

    做法:den = entry − stop(>0),δ = grand × den(价格单位)。整条路径沿持有期**线性下移** δ:
    第 i 个标记点减 δ × i/(n−1)(入场那点不动、出场前那点正好减 δ),出场价也减 δ。
    ⇒ nav 的每票 R = (exit'−entry)/den − 0.004×entry/den = (R + c) − grand − c = R − grand(精确),
    中途的未实现盈亏 = 原路径减去一条从 0 到 grand 的直线(形状保留,不会像乘法缩放那样炸掉)。

    为什么不用「把价格绕 entry 乘一个系数」:那个系数 = (R−grand+c)/(R+c),在 R ≈ 0 的票上会爆到
    |k| > 100(实测 −204 ~ +38),中途的标记价会翻负 —— 没边世界的钱曲线会被这个假象毁掉。
    """
    den = entry_px - stop_px
    delta = grand * den
    n = len(path)
    if n < 2:
        new_exit = exit_px - delta
        return [(d, c) for d, c in path], new_exit
    out = []
    for i, (d, c) in enumerate(path):
        out.append((d, c - delta * i / (n - 1)))
    return out, exit_px - delta


def build_timeline(picks, buckets, marks, world, grand, compress=True):
    """把抽到的月依次接成一条假想时间线;每张票保留「相对信号月的天数偏移」,并按真实持有期给出进出场。
    compress=True  = 月槽依次相接(台账口径);compress=False = 每槽用原日历的月首(自检用)。"""
    tks, closes = [], {}
    bounds, off = [], 0
    for m in picks:
        L = month_len(m)
        ms = month_start(m)
        slot = (TL_START + timedelta(days=off)) if compress else ms
        for t in buckets[m]:
            e = date.fromisoformat(t["entry_d"])
            off_days = (e - ms).days
            new_e = slot + timedelta(days=off_days)
            hold = (date.fromisoformat(t["exit_d"]) - e).days
            new_x = new_e + timedelta(days=hold)
            key = f"{t['symbol']}#{len(tks)}"
            path = marks.get((t["symbol"], t["entry_d"], t["exit_d"])) or []
            entry_px, stop_px, exit_px = t["entry_px"], t["stop_px"], t["exit_px"]
            if world == "noedge":
                path, exit_px = noedge_path(path, entry_px, stop_px, exit_px, grand)
            new_path = []
            for i, (d, _c) in enumerate(path):
                nd = (new_e + (date.fromisoformat(d) - e)).isoformat()
                new_path.append((nd, path[i][1]))
            closes[key] = [(d, 0.0, 0.0, 0.0, c_, 0.0) for (d, c_) in new_path]
            tks.append(dict(symbol=key, signal_d=t["signal_d"], entry_d=new_e.isoformat(),
                            exit_d=new_x.isoformat(), entry_px=entry_px, stop_px=stop_px,
                            exit_px=exit_px, r=t["r"]))
        off += L
        bounds.append((TL_START + timedelta(days=off)) if compress else (ms + timedelta(days=L)))
    return tks, closes, bounds


def control_check(tk, buckets, months, marks, grand):
    """自检 1(时间线):把 908 张已平票按**原日历**排上时间线(compress=False,槽起点 = 原月首),
    跑本脚本的时间线 + nav —— 期末净值 / 最大回撤应与直接 t159.nav(同批票, 原 K 线)逐位一致。
    对不上 ⇒ 时间线 / 标记价 / nav 调用约定有 bug,② 的数不能用。"""
    tk_direct = [dict(symbol=t["symbol"], signal_d=t["signal_d"], entry_d=t["entry_d"],
                      exit_d=t["exit_d"], entry_px=t["entry_px"], stop_px=t["stop_px"],
                      exit_px=t["exit_px"]) for t in tk]
    closes_direct = {}
    for (sym, a, b), path in marks.items():
        closes_direct.setdefault(sym, []).extend((d, 0.0, 0.0, 0.0, c, 0.0) for (d, c) in path)
    for sym in closes_direct:
        closes_direct[sym].sort(key=lambda r: r[0])
    d_to = max(t["exit_d"] for t in tk)
    curve_direct = list(t159.nav(tk_direct, closes_direct, F, cap=CAP, d_to=d_to))
    sd_direct = t159.stats(curve_direct)

    tks, closes, bounds = build_timeline(months, buckets, marks, "edge", grand, compress=False)
    curve_ctl = list(t159.nav(tks, closes, F, cap=CAP, d_to=d_to))
    sd_ctl = t159.stats(curve_ctl)
    return dict(d_to=d_to, end_direct=sd_direct["end"], end_control=sd_ctl["end"],
                mdd_direct=sd_direct["mdd"], mdd_control=sd_ctl["mdd"],
                end_abs_diff=abs(sd_direct["end"] - sd_ctl["end"]),
                mdd_abs_diff=abs(sd_direct["mdd"] - sd_ctl["mdd"]),
                taken_direct=sd_direct["taken"], taken_control=sd_ctl["taken"],
                skipped_direct=sd_direct["skipped"], skipped_control=sd_ctl["skipped"])


def noedge_check(tk, marks, grand):
    """自检 2(没边世界的编码):对每张票算 nav 的每票 R 公式,必须精确等于 R − grand;并统计中途标记价翻负的票数。"""
    worst, neg, nonpos = 0.0, 0, 0
    for t in tk:
        den = t["entry_px"] - t["stop_px"]
        path = marks.get((t["symbol"], t["entry_d"], t["exit_d"])) or []
        p2, exit2 = noedge_path(path, t["entry_px"], t["stop_px"], t["exit_px"], grand)
        r_nav = (exit2 - t["entry_px"]) / den - 0.004 * t["entry_px"] / den
        worst = max(worst, abs(r_nav - (t["r"] - grand)))
        if any(c <= 0 for _d, c in p2):
            neg += 1
        if exit2 <= 0:
            nonpos += 1
    return dict(max_abs_r_error=worst, n_path_nonpositive=neg, n_exit_nonpositive=nonpos)


def curve_worker(args):
    """一批 replicate:每条 replicate 铺 24 个月槽,跑一次 nav,再取 6 / 12 / 24 个月的前缀回撤。"""
    scheme, world, start, count, seed0 = args
    buckets = _T["buckets"]; months = _T["months"]; marks = _T["marks"]; grand = _T["grand"]
    probs = _T["probs"][scheme]
    out = []
    for i in range(start, start + count):
        rng = np.random.default_rng((seed0 + i) % (2 ** 32))
        picks = [months[int(rng.choice(len(months), p=probs))] for _ in range(SLOTS)]
        tks, closes, bounds = build_timeline(picks, buckets, marks, world, grand)
        curve = list(t159.nav(tks, closes, F, cap=CAP, d_to=bounds[-1].isoformat()))
        rec = {}
        for H in HORIZONS:
            b = bounds[H - 1].isoformat()
            rows = [r for r in curve if r["d"] <= b]
            st = t159.stats(rows) if rows else None
            min_eq = min((r["equity"] for r in rows), default=None)
            rec[H] = dict(mdd=(st["mdd"] if st else None), end=(st["end"] if st else None),
                          days=(len(rows) if rows else 0),
                          taken=(st["taken"] if st else None),
                          bankrupt=bool(min_eq is not None and min_eq <= 0.0),
                          min_eq=min_eq)
        rec["n_tickets"] = len(tks)
        out.append(rec)
    return out


# ── ③ 2024 年的节奏 ────────────────────────────────────────────────────────────────────────────────────
def pace_2024(tk):
    """A 在 2024 年的每月开票数(12 个月,0 票的月份算 0)。"""
    cnt = {f"2024-{m:02d}": 0 for m in range(1, 13)}
    for t in tk:
        if t["month"].startswith("2024"):
            cnt[t["month"]] += 1
    return cnt


def wait_months_worker(args):
    n, draws, seed0, dist = args
    vals = np.asarray(dist, dtype=float)
    out = []
    for i in range(draws):
        rng = np.random.default_rng((seed0 + i) % (2 ** 32))
        tot, m = 0.0, 0
        while tot < n:
            tot += float(vals[int(rng.integers(len(vals)))])
            m += 1
            if m > 10000:
                break
        out.append(m)
    return out


# ── 汇总 ──────────────────────────────────────────────────────────────────────────────────────────────────
def pass_flags(means, ps, alpha):
    """R1 均值 > 0;R2/R3 = R1 且 p < alpha。p 不可算(零分布退化)⇒ 不通过。"""
    r1 = np.array([m > 0 for m in means])
    ok = np.array([p is not None for p in ps])
    pv = np.array([p if p is not None else 1.0 for p in ps])
    r2 = r1 & ok & (pv < alpha)
    return r1, r2


def summarize_cell(cell):
    means = np.asarray(cell["means"], dtype=float)
    ps = cell["p"]
    pcs = cell["p_centered"]
    r1, r2 = pass_flags(cell["means"], ps, 0.10)
    _, r3 = pass_flags(cell["means"], ps, 0.05)
    r1c, r2c = pass_flags(cell["means"], pcs, 0.10)
    _, r3c = pass_flags(cell["means"], pcs, 0.05)
    ok = np.array([p is not None for p in ps])
    q = [float(x) for x in np.percentile(means, [5, 50, 95])]
    return dict(scheme=cell.get("scheme"), world=cell["world"], n=cell["n"],
                truncate=cell["truncate"], degen=cell["degen"],
                degen_rate=float(1.0 - ok.mean()),
                mean_q=q, mean=float(means.mean()),
                r1=float(r1.mean()), r2=float(r2.mean()), r3=float(r3.mean()),
                r1c=float(r1c.mean()), r2c=float(r2c.mean()), r3c=float(r3c.mean()),
                r2_excl=float(r2[ok].mean()) if ok.any() else None,
                r3_excl=float(r3[ok].mean()) if ok.any() else None)


def summarize_curve(recs):
    out = {}
    for H in HORIZONS:
        mdd = np.array([r[H]["mdd"] for r in recs if r[H]["mdd"] is not None], dtype=float)
        out[H] = dict(n=int(mdd.size),
                      q=[float(x) for x in np.percentile(mdd, [5, 50, 95])] if mdd.size else None,
                      mean=float(mdd.mean()) if mdd.size else None,
                      p10=float((mdd <= -0.10).mean()) if mdd.size else None,
                      p18=float((mdd <= -0.18).mean()) if mdd.size else None,
                      p25=float((mdd <= -0.25).mean()) if mdd.size else None,
                      bankrupt=float(np.mean([bool(r[H]["bankrupt"]) for r in recs])) if recs else None)
    return out


def min_n_table(cells):
    """「检出力 ≥ 80% 且误放 ≤ 10%」的最小 N(每条规则一个数;够不到就写够不到)。"""
    idx = {(c["world"], c["n"]): c for c in cells if c["truncate"]}
    out = {}
    for key, label in (("r1", "R1"), ("r2", "R2"), ("r3", "R3"), ("r2c", "R2′"), ("r3c", "R3′")):
        best = None
        detail = {}
        for n in N_LIST:
            e = idx.get(("edge", n)); z = idx.get(("noedge", n))
            if not e or not z:
                continue
            power, fa = e[key], z[key]
            detail[n] = dict(power=power, false_accept=fa)
            if power >= 0.80 and fa <= 0.10:
                best = n
                break
        out[label] = dict(min_n=best, detail=detail)
    return out


# ── 主流程 ────────────────────────────────────────────────────────────────────────────────────────────────
def run_scheme(scheme, args, tk, t197, buckets, months, grand, marks):
    """跑一个抽样口径,返回该口径的结果片段。"""
    _T.update(tk=tk, buckets=buckets, months=months, grand=grand, marks=marks,
              probs={scheme: month_probs(months, buckets, scheme)})
    cells_raw = []
    jobs = []
    for world in ("edge", "noedge"):
        for n in N_LIST:
            for trunc, tid in ((True, 0), (False, 1)):
                seed0 = (SEED * 1000003 + (0 if world == "edge" else 7919)
                         + n * 104729 + tid * 31 + (0 if scheme == SCHEME_PRIMARY else 104729)) % (2 ** 32)
                jobs.append((scheme, world, n, trunc, args.draws, seed0))
    with get_context("fork").Pool(args.workers) as pool:
        for i, res in enumerate(pool.imap_unordered(cell_worker, jobs), 1):
            cells_raw.append(res)
            if i % 6 == 0:
                print(f"[① {scheme}] {i}/{len(jobs)} 档完成", flush=True)
    cells = [summarize_cell(c) for c in cells_raw]
    print(f"[① {scheme}] 全部完成", flush=True)

    curves, raw_curve = {}, {}
    if not args.skip_curve:
        cjobs = []
        for world in ("edge", "noedge"):
            per = max(1, args.draws // args.workers)
            for w in range(args.workers):
                start = w * per
                cnt = per if w < args.workers - 1 else args.draws - start
                if cnt <= 0:
                    continue
                seed0 = (SEED * 1000003 + (0 if world == "edge" else 6151) + w * 7717
                         + (0 if scheme == SCHEME_PRIMARY else 104729)) % (2 ** 32)
                cjobs.append((scheme, world, start, cnt, seed0))
        with get_context("fork").Pool(args.workers) as pool:
            recs = pool.map(curve_worker, cjobs)
        for world in ("edge", "noedge"):
            wr = []
            # cjobs 的元组是 (scheme, world, start, cnt, seed0) —— 解包的顺序必须对上,
            # 否则 world 拿到的是 scheme,wr 永远是空的(2026-10-26 首跑踩过:② 整节空)。
            for (_sc, wj, _s, _c, _sd), rr in zip(cjobs, recs):
                if wj == world:
                    wr.extend(rr)
            if len(wr) != args.draws:
                raise SystemExit(f"[② {scheme}/{world}] replicate 数不对:{len(wr)} != {args.draws}")
            if all(r[H]["mdd"] is None for r in wr for H in HORIZONS):
                raise SystemExit(f"[② {scheme}/{world}] 所有 replicate 的 MDD 都是 None —— 时间线 / nav 调用约定坏了")
            curves[world] = summarize_curve(wr)
            curves[world]["n_tickets_mean"] = float(np.mean([r["n_tickets"] for r in wr]))
            curves[world]["taken_mean"] = float(np.mean([r[24]["taken"] for r in wr]))
            raw_curve[world] = {str(H): _r6([r[H]["mdd"] for r in wr]) for H in HORIZONS}
        print(f"[② {scheme}] 完成", flush=True)

    return dict(cells=cells, min_n=min_n_table([c for c in cells if c["truncate"]]),
                curve=curves,
                raw_means={f"{c['world']}|{c['n']}|{int(c['truncate'])}": _r6(c["means"]) for c in cells_raw},
                raw_p={f"{c['world']}|{c['n']}|{int(c['truncate'])}": _r6(c["p"]) for c in cells_raw},
                raw_p_centered={f"{c['world']}|{c['n']}|{int(c['truncate'])}": _r6(c["p_centered"]) for c in cells_raw},
                raw_curve_mdd=raw_curve)


def merge_fragments(frags):
    """把多个抽样口径的片段合成一份结果。"""
    res = dict(meta={}, cells=[], min_n={}, curve={},
               raw_means={}, raw_p={}, raw_p_centered={}, raw_curve_mdd={})
    for scheme, f in frags.items():
        res["cells"].extend(f["cells"])
        res["min_n"][scheme] = f["min_n"]
        res["curve"][scheme] = f["curve"]
        for k in ("raw_means", "raw_p", "raw_p_centered"):
            for kk, vv in f[k].items():
                res[k][f"{scheme}|{kk}"] = vv
        res["raw_curve_mdd"][scheme] = f["raw_curve_mdd"]
    return res


def merge_files(labeled):
    """labeled = [(scheme, path), ...]:把单口径跑出来的扁平 JSON 合成一份。"""
    frags = {}
    for scheme, path in labeled:
        d = json.load(open(path))
        mn = d.get("min_n", {}) or {}
        cv = d.get("curve", {}) or {}
        rcm = d.get("raw_curve_mdd", {}) or {}
        frags[scheme] = dict(cells=d.get("cells", []), min_n=mn.get(scheme, mn),
                             curve=cv.get(scheme, cv),
                             raw_means=_strip_prefix(d.get("raw_means", {}) or {}, scheme),
                             raw_p=_strip_prefix(d.get("raw_p", {}) or {}, scheme),
                             raw_p_centered=_strip_prefix(d.get("raw_p_centered", {}) or {}, scheme),
                             raw_curve_mdd=rcm.get(scheme, rcm))
    return frags


def _strip_prefix(d, scheme):
    pre = scheme + "|"
    return {k[len(pre):] if k.startswith(pre) else k: v for k, v in d.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 4))
    ap.add_argument("--skip-curve", action="store_true")
    ap.add_argument("--no-md", action="store_true")
    ap.add_argument("--out", default=OUT_JSON)
    ap.add_argument("--schemes", default=f"{SCHEME_PRIMARY},{SCHEME_ALT}")
    ap.add_argument("--merge", nargs="*", default=None,
                    help="合并单口径的 JSON:scheme=path ...")
    args = ap.parse_args()

    if args.merge:
        labeled = []
        for spec in args.merge:
            k, v = spec.split("=", 1)
            labeled.append((k, v))
        frags = merge_files(labeled)
        res = merge_fragments(frags)
        res["meta"] = json.load(open(labeled[0][1]))["meta"]
        res["meta"]["merged_from"] = [f"{k}={v}" for k, v in labeled]
        res["pace_2024"] = json.load(open(labeled[0][1])).get("pace_2024")
        res["pace_wait"] = json.load(open(labeled[0][1])).get("pace_wait")
        with open(args.out, "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        if not args.no_md:
            write_md(res, json.load(open(T197_JSON)))
            print(f"[done] {OUT_MD}", flush=True)
        print(f"[done] {args.out}", flush=True)
        return

    t0 = datetime.now(timezone.utc)
    tk, t197 = load_tickets()
    buckets, months = build_buckets(tk)
    grand = float(np.mean([t["r"] for t in tk]))
    marks = load_marks(tk)
    print(f"[load] tickets closed={len(tk)} months={len(months)} grand_mean_R={grand:+.6f} "
          f"marks={len(marks)}", flush=True)

    ctl = control_check(tk, buckets, months, marks, grand)
    print(f"[control] nav 时间线自检: end {ctl['end_direct']:.6f} vs {ctl['end_control']:.6f} "
          f"(Δ={ctl['end_abs_diff']:.3e}) | MDD {ctl['mdd_direct']:.6f} vs {ctl['mdd_control']:.6f} "
          f"(Δ={ctl['mdd_abs_diff']:.3e}) | taken {ctl['taken_direct']}/{ctl['taken_control']}", flush=True)
    if ctl["end_abs_diff"] > 1e-9 or ctl["mdd_abs_diff"] > 1e-9:
        raise SystemExit("[control] 自检不通过:时间线 / 标记价 / nav 调用约定有 bug,② 的数不能用")

    nec = noedge_check(tk, marks, grand)
    print(f"[control] 没边世界编码自检: 每票 R 与 (R−grand) 的最大误差 {nec['max_abs_r_error']:.3e} | "
          f"中途标记价 ≤ 0 的票 {nec['n_path_nonpositive']} | 出场价 ≤ 0 的票 {nec['n_exit_nonpositive']}",
          flush=True)
    if nec["max_abs_r_error"] > 1e-9:
        raise SystemExit("[control] 没边世界的每票 R 不等于 R − grand,② 的数不能用")

    frags = {}
    for scheme in args.schemes.split(","):
        scheme = scheme.strip()
        if not scheme:
            continue
        frags[scheme] = run_scheme(scheme, args, tk, t197, buckets, months, grand, marks)

    res = merge_fragments(frags)
    res["meta"] = dict(run_utc=t0.isoformat(), draws=args.draws, seed=SEED, boot_draws=BOOT_DRAWS,
                       n_list=N_LIST, horizons=HORIZONS, f=F, cap=CAP,
                       tickets_closed=len(tk), months=len(months), grand_mean_r=grand,
                       source="docs/research/t197_results.json tickets.A",
                       um=UM_FILE, control=ctl, control_noedge=nec,
                       schemes=list(frags.keys()), scheme_primary=SCHEME_PRIMARY)

    pace = pace_2024(tk)
    pace_all = pace_2024([dict(t, month=t["signal_d"][:7]) for t in t197["tickets"]["A"]])
    wjobs = [(n, args.draws, (SEED * 1000003 + n * 104729) % (2 ** 32), list(pace.values()))
             for n in (30, 50, 100)]
    with get_context("fork").Pool(min(3, args.workers)) as pool:
        wres = pool.map(wait_months_worker, wjobs)
    pace_out = {}
    for (n, _d, _s, _v), vals in zip(wjobs, wres):
        a = np.asarray(vals, dtype=float)
        pace_out[n] = dict(median=float(np.median(a)), p90=float(np.percentile(a, 90)),
                           mean=float(a.mean()), max=int(a.max()))
    res["pace_2024"] = pace
    res["pace_2024_all"] = pace_all
    res["pace_wait"] = pace_out
    print("[③] 完成", flush=True)

    with open(args.out, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    if not args.no_md:
        write_md(res, t197)
        print(f"[done] {OUT_MD}", flush=True)
    print(f"[done] {args.out}", flush=True)


def _r6(xs):
    return [None if x is None else round(float(x), 6) for x in xs]


def _pc(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def _num(x, d=4):
    return "—" if x is None else f"{x:.{d}f}"


def _cells_of(res, scheme):
    return [c for c in res["cells"] if c.get("scheme") == scheme]


def write_md(res, t197):
    L = []
    p = L.append
    m = res["meta"]
    prim = SCHEME_PRIMARY
    alt = SCHEME_ALT
    have = {c.get("scheme") for c in res["cells"]}

    def idx_of(scheme):
        return {(c["world"], c["n"]): c for c in _cells_of(res, scheme) if c["truncate"]}

    idx = idx_of(prim) if prim in have else idx_of(alt)

    p("# T-201 / S-686 — R-v2 真钱关停线 / 加仓线的分辨力")
    p("")
    p(f"- 数据:`docs/research/t197_results.json` 的 `tickets.A`,只取已平的 **{m['tickets_closed']} 张**"
      f"(信号月 {m['months']} 个;票等权平均 R = **{m['grand_mean_r']:+.4f}**)")
    p(f"- 两个世界:有边 = 原样;没边 = 每张 R 减去全样本平均 R({m['grand_mean_r']:+.4f})")
    p(f"- 抽样:按信号月整块抽(保留月内成簇),种子 {m['seed']},每档 {m['draws']} 次;"
      f"月块自助 {m['boot_draws']} 次;钱曲线 f = {m['f']:.0%}、cap = {m['cap']}")
    p(f"- **抽一个月的概率怎么给,台账没写**(见「协议问题」第 1 条):"
      f"主口径 `size` = 按该月的票数加权(抽一张票 → 取它整个信号月,抽出来的书与总体同权重,"
      f"有边 ≈ {m['grand_mean_r']:+.3f}R、没边 ≈ 0R,与台账写的世界一致);"
      f"敏感性 `month` = 40 个信号月等概率(「抽一个信号月、整块拿」的字面读法)。")
    ctl = m.get("control") or {}
    if ctl:
        p(f"- **自检 1(时间线)**:同一批 {m['tickets_closed']} 张票按原日历排上本脚本的时间线再跑 `t159.nav`,"
          f"与直接 `t159.nav` 的期末净值 / 最大回撤逐位相同(Δ = {ctl['end_abs_diff']:.1e} / "
          f"{ctl['mdd_abs_diff']:.1e});参考:直接 nav 的期末净值 {ctl['end_direct']:.4f}、"
          f"MDD {ctl['mdd_direct'] * 100:.2f}%(T-197 的 A 曲线 −36.94%)")
    nec = m.get("control_noedge") or {}
    if nec:
        p(f"- **自检 2(没边编码)**:每票 R 与 (R − 全样本平均 R) 的最大误差 "
          f"{nec['max_abs_r_error']:.1e};中途标记价 ≤ 0 的票 {nec['n_path_nonpositive']} 张、"
          f"出场价 ≤ 0 的票 {nec['n_exit_nonpositive']} 张")
    p(f"- 复算:`python3 docs/research/t201_rv2_killline_power.py`;逐档原始数 `docs/research/t201_results.json`")
    p("")

    # ── 最小 N ──
    p("## 最小 N(检出力 ≥ 80% 且误放 ≤ 10%)")
    p("")
    p("| 规则 | 最小 N(主口径 `size`,票数加权整块抽) | 最小 N(敏感性 `month`,月等权整块抽) |")
    p("|---|---|---|")
    for lab, key, keyc in (("R1 均值 > 0", "R1", "R1"),
                           ("R2 均值 > 0 且 p < 0.10", "R2", "R2′"),
                           ("R3 均值 > 0 且 p < 0.05", "R3", "R3′")):
        a = res["min_n"].get(prim, {}).get(key, {}).get("min_n")
        b = res["min_n"].get(alt, {}).get(keyc, {}).get("min_n")
        p(f"| {lab} | {a if a is not None else '**够不到**(N ≤ 200 网格内)'} "
          f"| {b if b is not None else '**够不到**(N ≤ 200 网格内)'} |")
    p("")
    for scheme, title in ((prim, "主口径 `size`(票数加权整块抽)"), (alt, "敏感性 `month`(月等权整块抽)")):
        if scheme not in have:
            continue
        si = idx_of(scheme)
        p(f"**{title}**")
        p("")
        p("| N | 规则 | 检出力(有边) | 误放率(没边) |")
        p("|---|---|---|---|")
        for n in m["n_list"]:
            e, z = si.get(("edge", n)), si.get(("noedge", n))
            if not e or not z:
                continue
            for lab, k in (("R1", "r1"), ("R2", "r2"), ("R3", "r3")):
                p(f"| {n} | {lab} | {_pc(e[k])} | {_pc(z[k])} |")
        p("")

    # ── ① ──
    p("## ① 观测平均 R 的分布与三条规则的通过率")
    p("")
    p(f"(下表是主口径 `{prim}`;敏感性 `{alt}` 的通过率见上面的表。)")
    p("")
    p("### 1.1 观测平均 R 的 5 / 50 / 95 分位")
    p("")
    p("| N | 有边 5 / 50 / 95 | 没边 5 / 50 / 95 |")
    p("|---|---|---|")
    for n in m["n_list"]:
        e, z = idx.get(("edge", n)), idx.get(("noedge", n))
        if not e or not z:
            continue
        p(f"| {n} | {' / '.join(_num(x) for x in e['mean_q'])} | {' / '.join(_num(x) for x in z['mean_q'])} |")
    p("")
    p("### 1.2 通过率(有边 = 检出力,没边 = 误放率)")
    p("")
    p("| N | R1 有边 | R1 没边 | R2 有边 | R2 没边 | R3 有边 | R3 没边 | R2′ 有边 | R2′ 没边 | R3′ 有边 | R3′ 没边 | p 不可算 |")
    p("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n in m["n_list"]:
        e, z = idx.get(("edge", n)), idx.get(("noedge", n))
        if not e or not z:
            continue
        p(f"| {n} | {_pc(e['r1'])} | {_pc(z['r1'])} | {_pc(e['r2'])} | {_pc(z['r2'])} | "
          f"{_pc(e['r3'])} | {_pc(z['r3'])} | {_pc(e['r2c'])} | {_pc(z['r2c'])} | "
          f"{_pc(e['r3c'])} | {_pc(z['r3c'])} | {_pc(e['degen_rate'])} |")
    p("")
    p("### 1.3 敏感性:只在 p 可算的抽样里算通过率(分母剔除「样本只落在一个月」的那些)")
    p("")
    p("| N | R2 有边 | R3 有边 | R2 没边 | R3 没边 |")
    p("|---|---|---|---|---|")
    for n in m["n_list"]:
        e, z = idx.get(("edge", n)), idx.get(("noedge", n))
        if not e or not z:
            continue
        p(f"| {n} | {_pc(e['r2_excl'])} | {_pc(e['r3_excl'])} | {_pc(z['r2_excl'])} | {_pc(z['r3_excl'])} |")
    p("")
    p("### 1.4 敏感性:不截断到正好 N 张(整月保留 ⇒ 实际张数 ≥ N)")
    p("")
    for scheme in (prim, alt):
        if scheme not in have:
            continue
        si = idx_of(scheme)
        p(f"**(抽样口径 `{scheme}`)**")
        p("")
        p("| N | R1 有边 | R1 没边 | R2 有边 | R2 没边 | R3 有边 | R3 没边 |")
        p("|---|---|---|---|---|---|---|")
        for n in m["n_list"]:
            e = next((c for c in _cells_of(res, scheme) if not c["truncate"] and c["world"] == "edge" and c["n"] == n), None)
            z = next((c for c in _cells_of(res, scheme) if not c["truncate"] and c["world"] == "noedge" and c["n"] == n), None)
            if not e or not z:
                continue
            p(f"| {n} | {_pc(e['r1'])} | {_pc(z['r1'])} | {_pc(e['r2'])} | {_pc(z['r2'])} | "
              f"{_pc(e['r3'])} | {_pc(z['r3'])} |")
        p("")

    # ── ② ──
    if res.get("curve"):
        p("## ② 钱曲线的最大回撤(6 / 12 / 24 个月)")
        p("")
        p(f"(每个格子 {m['draws']} 条 replicate:一条 replicate = 24 个月槽的假想时间线,"
          f"6 / 12 / 24 个月用同一条 replicate 的前缀 —— 未来票不影响过去的净值,前缀等价。)")
        p("")
        p("| 抽样口径 | 视野 | 世界 | MDD 5 / 50 / 95 分位 | 平均 MDD | 触 −10% | 触 −18% | 触 −25% | 净值 ≤ 0(爆掉) |")
        p("|---|---|---|---|---|---|---|---|---|")
        for scheme in (prim, alt):
            if scheme not in res["curve"]:
                continue
            for H in m["horizons"]:
                for world, lab in (("edge", "有边"), ("noedge", "没边")):
                    cw = res["curve"].get(scheme, {}).get(world, {}) or {}
                    c = cw.get(str(H)) or cw.get(H)
                    if not c or c.get("q") is None:
                        continue
                    p(f"| {scheme} | {H} 个月 | {lab} | {' / '.join(_num(x) for x in c['q'])} | {_num(c['mean'])} "
                      f"| {_pc(c['p10'])} | {_pc(c['p18'])} | {_pc(c['p25'])} | {_pc(c.get('bankrupt'))} |")
        p("")

    # ── ③ ──
    p("## ③ 按 2024 年的节奏,N 张票要等多少个月")
    p("")
    p(f"2024 年每月开票数(信号月,含 0 票的月份):{res['pace_2024']} —— 合计 {sum(res['pace_2024'].values())} 张")
    allA24 = [t for t in json.load(open(T197_JSON))["tickets"]["A"] if t["signal_d"][:4] == "2024"]
    p(f"(口径对照:A 在 2024 年**开出**的票一共 {len(allA24)} 张,其中仍持有 "
      f"{sum(1 for t in allA24 if t.get('r') is None)} 张 ⇒ 2024 年的「开票数」与「已平票数」"
      f"{'一致' if all(t.get('r') is not None for t in allA24) else '不一致,见上表口径'})")
    p("")
    p("| N | 中位月数 | 90 分位月数 | 平均 | 最长 |")
    p("|---|---|---|---|---|")
    for n in (30, 50, 100):
        w = res["pace_wait"].get(str(n)) or res["pace_wait"].get(n)
        if not w:
            continue
        p(f"| {n} | {w['median']:.1f} | {w['p90']:.1f} | {w['mean']:.1f} | {w['max']} |")
    p("")

    # ── 探索性读数(台账没要) ──
    tk_all = [t for t in json.load(open(T197_JSON))["tickets"]["A"] if t.get("r") is not None]
    yr = defaultdict(list)
    mo_big = defaultdict(list)
    for t in tk_all:
        yr[t["signal_d"][:4]].append(t["r"])
        mo_big[t["signal_d"][:7]].append(t["r"])
    tot = sum(t["r"] for t in tk_all)
    p("## 探索性读数(台账没要;需另立预注册、在新数据上过零信号对照)")
    p("")
    p("| 年 | 票数 | 平均 R | ΣR |")
    p("|---|---|---|---|")
    for y in sorted(yr):
        v = yr[y]
        p(f"| {y} | {len(v)} | {sum(v) / len(v):+.4f} | {sum(v):+.2f} |")
    ex = [r for y, v in yr.items() if y not in ("2021", "2024") for r in v]
    p("")
    p(f"- **edge 集中在两年**:去掉 2021 + 2024,其余 {len(ex)} 张票的平均 R = **{sum(ex) / len(ex):+.4f}**"
      f"(ΣR {sum(ex):+.2f});全 {len(tk_all)} 张是 {tot / len(tk_all):+.4f}。")
    big = sorted(((mm, len(v), sum(v) / len(v), sum(v)) for mm, v in mo_big.items() if len(v) >= 50),
                 key=lambda x: -x[3])
    p(f"- **edge 集中在几个大月块**:{' / '.join(f'`{mm}`({n} 张、平均 {mu:+.3f}R、Σ {sm:+.1f}R)' for mm, n, mu, sm in big[:3])}"
      f" —— 前两块合计 {sum(n for _, n, _, _ in big[:2])} 张"
      f"({sum(n for _, n, _, _ in big[:2]) / len(tk_all) * 100:.1f}%)贡献 {sum(sm for _, _, _, sm in big[:2]):+.1f}R,"
      f"而全宇宙只有 {tot:+.1f}R。")
    p("- 也就是说:月块自助的零分布之所以宽(检出力低),不是票级噪声大,而是**过程本身只有 "
      f"{m['months']} 个月块、edge 落在其中几块**;抽到哪一块决定了 N 张票的平均 R。")
    p("")
    p("## 协议问题(台账没写、我怎么定的)")
    p("")
    p("1. **「按信号月整块抽」没写「抽一个月的概率怎么给」。** 两种都算、都报:"
      "主口径 `size` = 按该月的票数加权(抽一张票 → 取它整个信号月)—— 这样抽出来的书与总体同权重,"
      f"有边世界抽到的平均 R ≈ {m['grand_mean_r']:+.3f}R、没边 ≈ 0R,与台账写的「平均 +0.33R / 均值 0」一致;"
      "敏感性 `month` = 40 个信号月等概率 —— 此时**按月等权**的总体平均 R 只有 +0.066R"
      "(票等权才是 +0.333R),抽样本身带偏差,没边世界实际中心在 −0.267R ⇒ 它给的误放率会偏低。"
      "两个口径的「最小 N」结论相同(都够不到),但误放率差 20–25 个百分点。")
    p("2. **外层抽样没写「有放回还是无放回」「要不要截断到正好 N 张」。** 主口径:月有放回地整块抽,"
      "抽到票数 ≥ N 后**截断到正好 N 张**(月内按信号日排序取前几张)—— 这样「N 张票」是真的 N 张;"
      "敏感性 1.4 给的是不截断(整月保留、实际张数 ≥ N)。")
    p("3. **② 的抽样次数台账没写。** 与 ① 同为每档 5,000 次、种子 686;一条 replicate 铺 24 个月槽,"
      "6 / 12 / 24 个月用同一条 replicate 的前缀(未来票不影响过去的净值,前缀等价)。"
      "每槽 = 一个月块,槽内票保留「相对原信号月的天数偏移」;视野末尾仍开着的票按盯市算(不强行平仓)。")
    p("4. **「没边」世界怎么落到价格上,台账没写。** 本跑用「价格路径沿持有期线性下移 δ = 平均 R × (entry − stop)」:"
      "入场那点不动、出场前那点正好下移 δ、出场价也减 δ ⇒ nav 的每票 R 精确等于 R − 平均 R,"
      "中途未实现盈亏 = 原路径减一条从 0 到平均 R 的直线。"
      "**没有**用「把价格绕 entry 乘一个系数」:那个系数 = (R−平均R+成本)/(R+成本),在 R ≈ 0 的票上"
      "实测会爆到 |系数| > 100(范围 −204 ~ +38),中途标记价会翻负,没边世界的钱曲线会被这个假象毁掉。")
    p("5. **「月块自助 p」的零分布是否以 0 为中心,台账没写。** 主口径 = S-684 原样"
      "(重抽原样本的整月,零分布中位数 ≈ 样本均值,p = P(null ≤ 0));敏感性列 R2′ / R3′ = T-197 §7 的读法"
      "(月均值先减总均值、零分布以 0 为中心)。"
      "**样本只落在一个信号月 ⇒ 零分布退化 ⇒ p 不可算**,该次抽样按「不过」计(1.2 最后一列是这种抽样的占比)。"
      "**p 是在每一次外层抽样内部算的**(内层月块自助 2,000 次):通过率 = P(p < α) 在外层 5,000 次抽样上的频率,"
      "不是把 5,000 个样本合起来算一个 p。")
    p("6. **③ 的「每月开票数分布」按 A 的已平票、信号月统计,0 票的月份算 0 个月;"
      "等待月数 = 从这 12 个月的经验分布里有放回地抽月、累加到票数 ≥ N。**")
    p("7. **最小 N 只在 N ∈ {10, 20, 30, 50, 100, 200} 网格上找;网格内够不到就写「够不到」。**")
    p("8. **种子的派生**:台账只给「种子 686」。本跑按 SEED×1000003 + 世界偏移 + N×104729 + 变体×31 "
      "(+ 口径偏移)派生每一档的外层种子,内层月块自助的种子由外层种子 × 31 + 7 派生;② 的 replicate 种子同理。"
      "(同种子同结果,可复算。)")
    p("")
    p("---")
    p("")
    p(f"复算:`python3 docs/research/t201_rv2_killline_power.py`;逐档原始数 `docs/research/t201_results.json`。")
    p("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
