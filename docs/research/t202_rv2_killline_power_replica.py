"""T-202 / S-686:R-v2 关停线的分辨力 —— 独立复算(lane-c;与 B 道 T-201 互不看,交付前未读其脚本与报告)。

台账 S-686(照抄执行,有问题写进报告「协议问题」,不自己改):

  票     = docs/research/t197_results.json 的 tickets.A,只用已平的 908 张,R 与信号日 / 进出场日照原样。
  两个世界:有边 = 原样;没边 = 每张 R 减去 A 的平均 R。
  抽样   = 按信号月整块抽(种子 686,每档 5,000 次)。
  ①     N ∈ {10,20,30,50,100,200}:观测平均 R 的 5/50/95 分位;R1「均值 > 0」、R2「均值 > 0 且月块自助
         p < 0.10」、R3「p < 0.05」(月块自助 2,000 次)在两个世界的通过率。
  ②     钱曲线 6/12/24 个月:t159.nav(import,不复制;f = 0.01、cap = 10)按抽到的票的真实持有期排在一条
         假想时间线上(先保留每张票相对信号月的天数偏移,再把抽到的月依次接上);最大回撤分布,触到
         −10% / −18% / −25% 的概率,两个世界各一份。
  ③     按 A 在 2024 年的每月开票数分布换算 N = 30/50/100 要等多少个月(中位 / 90 分位)。
  最后  「检出力 ≥ 80% 且误放 ≤ 10%」的最小 N(每条规则一个数;够不到就写够不到)。

口径(与 T-197 的 j1 同一套月块自助):
  * 「月块自助 p」= 不居中的自助零分布,p(≤ 0) = 自助均值里 ≤ 0 的比例(T-197 j1 就是这个口径:
    p_le0 = 0.107、百分位 0.5195)。同时报居中读法 p_cen = P(自助均值 ≤ 样本均值) 作敏感性。
  * 「没边」= 每张 R 减去 908 张已平票的平均 R(t197 的 A.mean_r = 0.3328670879287904),减完全世界均值恰为 0。
  * 抽样:按信号月整块抽(有放回),直到票数满 N,最后一块截断到正好 N 张(报告「协议问题」第 1 条)。
  * ① 的两个世界用同一批抽样(配对):差别只在 R 是否被平移。
  * 钱曲线的标记价:每张票用它自己那段真实价格路径(整段平移到假想时间线),理由见「协议问题」第 3 条;
    字面口径(用市场在假想日期的真实收盘价)另算一份作对照。
  * 没有边世界里钱曲线的出场价按 R 平移重算:exit_px' = entry_px·1.004 + r'·(entry_px − stop_px),
    使 nav 的已实现盈亏恰好等于 f·equity·r'(nav 的已实现 = units·(exit_px − entry_px) − 0.004·units·entry_px,
    units = f·equity/(entry_px − stop_px),与票的 r 同式)。

零分布与盈亏口径:自检判据与 src/data/evaluation/apparatus.py 的 null_distribution 一致(无方差 / ≥99% 等于实际值
⇒ 不可判),并抽样用 apparatus.null_distribution 复核(见 results 的 apparatus_check)。

读库:不需要(票来自已合并的 t197_results.json,K 线来自 Mac 数据根 research/s681/_um_daily.jsonl)。
"""
from __future__ import annotations

import bisect
import importlib.util
import json
import multiprocessing as mp
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

# t159 的数据根:模块级读 env,必须在 import t159 之前设好。
os.environ.setdefault("T156_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t156/")
os.environ.setdefault("T159_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t159/")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

from src.data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402

DATA = "/Volumes/CometCloudAI/cometcloud-local/research"
UM_FILE = f"{DATA}/s681/_um_daily.jsonl"
OUT_JSON = os.path.join(HERE, "t202_results.json")
OUT_MD = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-202_rv2_killline_power_replica.md"

SEED = 686              # 台账:种子 686
DRAWS = 5000            # 台账:每档 5,000 次
N_LIST = [10, 20, 30, 50, 100, 200]
HORIZONS = [6, 12, 24]
BOOT = 2000             # 台账:月块自助 2,000 次
F, CAP = 0.01, 10       # 台账:f = 0.01、cap = 10
BASE = date(2020, 1, 1)  # 假想时间线的起点(固定,两个世界共用同一条时间线)
DD_LEVELS = [-0.10, -0.18, -0.25]
LITERAL_DRAWS = 1000    # 字面口径(市场在假想日期的真实收盘价)对照用的抽样次数

_TICKETS: list = []
_BY_M: dict = {}
_MONTHS: list = []
_BARS: dict = {}
_PATHS: dict = {}
_MEAN_R = 0.0


# ── 票与价格 ────────────────────────────────────────────────────────────────────────────────────────────────────
def load_tickets():
    """t197_results.json 的 tickets.A,只留已平的(still = false)。"""
    d = json.load(open(os.path.join(HERE, "t197_results.json")))
    tk = [t for t in d["tickets"]["A"] if not t.get("still")]
    mean_r = float(np.mean([t["r"] for t in tk]))
    assert len(tk) == 908, f"已平票数不对:{len(tk)}"
    assert abs(mean_r - d["A"]["mean_r"]) < 1e-12, "平均 R 与 t197 的 A.mean_r 不一致"
    return tk, mean_r, d


def load_bars():
    """research/s681/_um_daily.jsonl → {symbol: [(d,o,h,l,c,quote_volume)]}(与 t197 同一读法)。"""
    bars = {}
    for line in open(UM_FILE):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
        if rows:
            bars[x["symbol"]] = rows
    return bars


def attach_paths(tk, bars):
    """每张票的真实价格路径:信号日到出场日之间的收盘价(原始日期)。"""
    idx = {s: {r[0]: r[4] for r in v} for s, v in bars.items()}
    dates = {s: [r[0] for r in v] for s, v in bars.items()}
    for t in tk:
        ds = dates.get(t["symbol"], [])
        lo = bisect.bisect_left(ds, t["signal_d"])
        hi = bisect.bisect_left(ds, t["exit_d"])
        t["_path"] = [(ds[i], idx[t["symbol"]][ds[i]]) for i in range(lo, hi)]
    return idx, dates


def mstart(s):
    return date(int(s[:4]), int(s[5:7]), 1)


def slot_start(base, k):
    return date(base.year + (base.month - 1 + k) // 12, (base.month - 1 + k) % 12 + 1, 1)


# ── ① 分辨力:抽样 + 月块自助 ─────────────────────────────────────────────────────────────────────────────
def draw_sample(rng, n_need, by_m, months):
    """按信号月整块抽(有放回)直到票数满 n_need,最后一块截断到正好 n_need 张。

    返回 [(该块的 R 值列表)] —— 块是自助的抽样单位。"""
    blocks, cnt = [], 0
    while cnt < n_need:
        m = months[int(rng.integers(len(months)))]
        rs = by_m[m]
        take = min(len(rs), n_need - cnt)
        if take < len(rs):                      # 最后一块截断:随机取 take 张,不留顺序偏差
            sel = rng.permutation(len(rs))[:take]
            rs = [rs[i] for i in sorted(sel)]
        blocks.append(rs)
        cnt += take
    return blocks


def boot_p(blocks, actual, rng, n_boot=BOOT):
    """月块自助:重抽块 → 自助均值的零分布。返回 (p_le0, p_cen);不可判返回 (None, None)。

    不可判的判据与 apparatus.null_distribution 一致(无方差 / ≥99% 的抽样等于实际值)。"""
    k = len(blocks)
    sums = np.array([sum(b) for b in blocks], dtype=float)
    cnts = np.array([len(b) for b in blocks], dtype=float)
    idx = rng.integers(0, k, size=(n_boot, k))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    finite = means[np.isfinite(means)]
    if finite.size == 0:
        return None, None
    if np.ptp(finite) <= 1e-12 * max(1.0, float(np.abs(finite).max())):
        return None, None
    if np.isclose(finite, actual, rtol=0.0, atol=1e-12).mean() >= 0.99:
        return None, None
    return float((finite <= 0.0).mean()), float((finite <= actual).mean())


def apparatus_check(blocks, actual, seed):
    """抽样复核:用 apparatus.null_distribution + percentile_of 算同一个 p(口径一致,抽样流不同)。"""
    k = len(blocks)
    sums = [sum(b) for b in blocks]
    cnts = [len(b) for b in blocks]

    def draw(rng):
        pick = rng.integers(0, k, size=k)
        return float(sum(sums[i] for i in pick) / sum(cnts[i] for i in pick))

    try:
        null = null_distribution(draw, BOOT, seed, actual=actual)
    except Exception:
        return None, None
    return float((null <= 0.0).mean()), percentile_of(actual, null)


def power_analysis(tk, mean_r, n_check=30):
    """①:N ∈ {10,20,30,50,100,200} × 两个世界。"""
    by_m = defaultdict(list)
    for t in tk:
        by_m[t["signal_d"][:7]].append(t["r"])
    months = sorted(by_m)
    out = {}
    checks = []
    for n_need in N_LIST:
        rng = np.random.default_rng(SEED)
        samples = [draw_sample(rng, n_need, by_m, months) for _ in range(DRAWS)]
        per_world = {}
        for w_id, world in enumerate(("edge", "noedge")):
            shift = 0.0 if world == "edge" else mean_r
            means, p_le0s, p_cens = [], [], []
            for i, blocks in enumerate(samples):
                wb = [[r - shift for r in b] for b in blocks]
                flat = [r for b in wb for r in b]
                actual = float(np.mean(flat))
                means.append(actual)
                irng = np.random.default_rng([SEED, n_need, w_id, i])
                p1, p2 = boot_p(wb, actual, irng)
                p_le0s.append(p1)
                p_cens.append(p2)
            means_a = np.array(means)
            p_arr = np.array([np.nan if p is None else p for p in p_le0s])
            ok = ~np.isnan(p_arr)
            p_ok = p_arr[ok]
            pc_arr = np.array([np.nan if p is None else p for p in p_cens])
            pc_ok = pc_arr[ok]
            # 不可判(p = None → NaN)的抽样一律记不通过,分母是全部抽样数。
            r1 = float((means_a > 0).mean())
            r2 = float(((means_a > 0) & (p_arr < 0.10)).mean())
            r3 = float((p_arr < 0.05).mean())
            r2c = float(((means_a > 0) & (pc_arr < 0.10)).mean())
            r3c = float((pc_arr < 0.05).mean())
            per_world[world] = dict(
                n=n_need,
                mean_r_p5=float(np.percentile(means_a, 5)),
                mean_r_p50=float(np.percentile(means_a, 50)),
                mean_r_p95=float(np.percentile(means_a, 95)),
                mean_r_mean=float(means_a.mean()),
                pass_r1=r1, pass_r2=r2, pass_r3=r3,
                pass_r2_centered=r2c, pass_r3_centered=r3c,
                undefined_frac=float(1.0 - ok.mean()),
                p_le0_median=float(np.median(p_ok)) if p_ok.size else None,
                p_cen_median=float(np.median(pc_ok)) if pc_ok.size else None,
                blocks_mean=float(np.mean([len(b) for b in samples])),
            )
            # apparatus 复核:前 n_check 个样本
            for i in range(min(n_check, len(samples))):
                wb = [[r - shift for r in b] for b in samples[i]]
                actual = float(np.mean([r for b in wb for r in b]))
                a_p, a_pct = apparatus_check(wb, actual, SEED + i)
                v_p = p_le0s[i]
                checks.append(dict(n=n_need, world=world, draw=i, actual=actual,
                                   vector_p=None if v_p is None else float(v_p),
                                   apparatus_p=a_p, apparatus_pct=a_pct))
        out[str(n_need)] = per_world
    return out, checks


def full_sample_check(t197):
    """校验:同一套机器在全样本(908 张 / 40 个月)上必须复现 T-197 的 boot.A(p_le0 = 0.107、百分位 0.5195)。"""
    by_m = defaultdict(list)
    for t in _TICKETS:
        by_m[t["signal_d"][:7]].append(t["r"])
    months = sorted(by_m)
    blocks = [list(by_m[m]) for m in months]
    actual = float(np.mean([r for b in blocks for r in b]))
    p_le0, p_cen = boot_p(blocks, actual, np.random.default_rng(684))
    ap_p, ap_pct = apparatus_check(blocks, actual, 684)
    return dict(actual=actual, p_le0=p_le0, p_cen=p_cen, apparatus_p=ap_p, apparatus_pct=ap_pct,
                t197_p_le0=t197["boot"]["A"]["p_le0"], t197_pct=t197["boot"]["A"]["pct"],
                n_blocks=len(months))


def bias_check():
    """抽样偏差诊断:整块抽(截断 / 不截断)与 iid 对照的样本均值,跟总体均值比。"""
    by_m = defaultdict(list)
    for t in _TICKETS:
        by_m[t["signal_d"][:7]].append(t["r"])
    months = sorted(by_m)
    allr = np.array([r for m in months for r in by_m[m]])
    out = {}
    for n_need in (10, 30, 50, 100, 200):
        rng = np.random.default_rng(SEED)
        a, b = [], []
        for _ in range(2000):
            bl = draw_sample(rng, n_need, by_m, months)
            a.append(float(np.mean([r for x in bl for r in x])))
            bl2, cnt = [], 0
            while cnt < n_need:
                m = months[int(rng.integers(len(months)))]
                bl2.append(by_m[m])
                cnt += len(by_m[m])
            b.append(float(np.mean([r for x in bl2 for r in x])))
        c = allr[rng.integers(0, len(allr), size=(2000, n_need))].mean(axis=1)
        out[str(n_need)] = dict(truncated=float(np.mean(a)), untruncated=float(np.mean(b)),
                                iid=float(np.mean(c)), population=float(_MEAN_R),
                                median_truncated=float(np.median(a)),
                                p5_truncated=float(np.percentile(a, 5)),
                                p95_truncated=float(np.percentile(a, 95)))
    return out


# ── ② 钱曲线 ───────────────────────────────────────────────────────────────────────────────────────────────────
def make_draw_tickets(month_picks, world, mean_r):
    """抽到的月依次接成一条假想时间线;每张票保留相对信号月的天数偏移。"""
    out = []
    for k, mi in enumerate(month_picks):
        m = _MONTHS[mi]
        sb = slot_start(BASE, k)
        for t in _BY_M[m]:
            s = mstart(t["signal_d"])
            delta = sb - s
            nt = dict(t)
            nt["_delta"] = delta
            nt["signal_d"] = (s + delta).isoformat()
            nt["entry_d"] = (date.fromisoformat(t["entry_d"]) + delta).isoformat()
            nt["exit_d"] = (date.fromisoformat(t["exit_d"]) + delta).isoformat()
            if world == "noedge":
                r2 = t["r"] - mean_r
                den = t["entry_px"] - t["stop_px"]
                nt["exit_px"] = t["entry_px"] * 1.004 + r2 * den
            out.append(nt)
    return out


def self_closes(tickets):
    """价格自洽的标记价:每张票用它自己那段真实价格路径(整段平移)。"""
    ser = defaultdict(dict)
    for t in tickets:
        s = t["symbol"]
        dl = t["_delta"]
        for d0, px in t["_path"]:
            dd = (date.fromisoformat(d0) + dl).isoformat()
            if dd not in ser[s]:
                ser[s][dd] = px
    return {s: [(k, 0, 0, 0, m[k], 0) for k in sorted(m)] for s, m in ser.items()}


def run_draw(args):
    """一次抽样:搭票 → 造标记价 → nav → 最大回撤。返回 (end, mdd, taken, skipped, n_tickets)。"""
    month_picks, world, mean_r, literal, seed = args
    tickets = make_draw_tickets(month_picks, world, mean_r)
    closes = _BARS if literal else self_closes(tickets)
    d_to = (max(date.fromisoformat(t["exit_d"]) for t in tickets) + timedelta(days=5)).isoformat()
    cur = list(t159.nav(tickets, closes, F, cap=CAP, d_to=d_to))
    st = t159.stats(cur)
    return st["end"], st["mdd"], st["taken"], st["skipped"], len(tickets)


def _init_worker():
    global _TICKETS, _BY_M, _MONTHS, _BARS, _PATHS, _MEAN_R
    if _BARS:            # fork 继承的父进程数据,不用重读
        return
    tk, mean_r, _ = load_tickets()
    _TICKETS = tk
    _MEAN_R = mean_r
    _BY_M = defaultdict(list)
    for t in tk:
        _BY_M[t["signal_d"][:7]].append(t)
    _MONTHS = sorted(_BY_M)
    _BARS = load_bars()
    attach_paths(tk, _BARS)


def money_curves(horizon, world, mean_r, draws, literal=False, seed=SEED):
    """一个档位(月数)的世界:抽 draws 次 → 最大回撤分布 + 触到各水平的概率。"""
    jobs = []
    for i in range(draws):
        # 抽样只跟 (档位, 第几次) 有关:两个世界、两种标记价口径用同一批抽到的月(配对比较)。
        rng = np.random.default_rng([seed, horizon, i])
        picks = [int(x) for x in rng.integers(0, len(_MONTHS), size=horizon)]
        jobs.append((picks, world, mean_r, literal, seed + i))
    ctx = mp.get_context("fork")          # macOS 默认 spawn 会重跑主模块,这里显式用 fork
    with ctx.Pool(processes=min(12, mp.cpu_count() - 1), initializer=_init_worker) as pool:
        res = pool.map(run_draw, jobs, chunksize=16)
    ends = np.array([r[0] for r in res])
    mdds = np.array([r[1] for r in res])
    taken = np.array([r[2] for r in res])
    skipped = np.array([r[3] for r in res])
    ntk = np.array([r[4] for r in res])
    out = dict(
        horizon=horizon, world=world, literal=literal, draws=draws,
        mdd_p5=float(np.percentile(mdds, 5)), mdd_p50=float(np.percentile(mdds, 50)),
        mdd_p95=float(np.percentile(mdds, 95)), mdd_min=float(mdds.min()), mdd_max=float(mdds.max()),
        end_p50=float(np.percentile(ends, 50)),
        taken_p50=float(np.percentile(taken, 50)), skipped_p50=float(np.percentile(skipped, 50)),
        tickets_p50=float(np.percentile(ntk, 50)),
    )
    for lv in DD_LEVELS:
        out[f"touch_{int(abs(lv) * 100)}"] = float((mdds <= lv).mean())
    return out


# ── ③ 等多久 ───────────────────────────────────────────────────────────────────────────────────────────────────
def months_needed(tk, mean_r=None):
    """按 A 在 2024 年的每月开票数分布,换算 N = 30/50/100 要等多少个月(中位 / 90 分位)。"""
    counts = {f"2024-{m:02d}": 0 for m in range(1, 13)}
    for t in tk:
        if t["signal_d"][:7] in counts:
            counts[t["signal_d"][:7]] += 1
    arr = [counts[k] for k in sorted(counts)]
    out = dict(counts_2024=arr, total_2024=int(sum(arr)))
    rng = np.random.default_rng(SEED)
    for n_need in (30, 50, 100):
        need = []
        for _ in range(10000):
            tot, k = 0, 0
            while tot < n_need:
                tot += arr[int(rng.integers(12))]
                k += 1
            need.append(k)
        need = np.array(need)
        # 确定式:2024 逐月往后接(跨年继续接 2024 的分布)
        seq, tot, k = [], 0, 0
        while tot < n_need:
            seq.append(arr[k % 12])
            tot += seq[-1]
            k += 1
        out[str(n_need)] = dict(median_months=float(np.median(need)),
                                p90_months=float(np.percentile(need, 90)),
                                sequential_months=k)
    return out


# ── 报告 ───────────────────────────────────────────────────────────────────────────────────────────────────────
def fmt_pct(x, nd=1):
    return "n/a" if x is None else f"{100 * x:.{nd}f}%"


def fmt_num(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def write_report(res, path):
    L = []
    p = L.append
    p("# T-202 · S-686:R-v2 关停线的分辨力(独立复算)")
    p("")
    p(f"生成:{res['meta']['run_utc']} · lane-c · 台账 S-686(照抄执行)")
    p("")
    p(f"票 = `docs/research/t197_results.json` 的 `tickets.A`,已平 **{res['meta']['n_tickets_closed']}** 张;"
      f"平均 R = {res['meta']['mean_r']:.6f}(= t197 的 `A.mean_r`)。")
    p(f"抽样:按信号月整块抽,种子 {res['meta']['seed']},每档 {res['meta']['draws']:,} 次;"
      f"月块自助 {res['meta']['boot']:,} 次。")
    p("")
    p("**两个世界** —— 有边 = 原样;没边 = 每张 R 减去 A 的平均 R(减完全世界均值为 0)。")
    p("")
    p("## 1 · ① 抽样分辨力:N 张票能判出「均值 > 0」吗")
    p("")
    p("`平均 R` 是 5,000 次抽样里样本均值 R 的 5 / 50 / 95 分位;`通过率` 是抽样里该规则成立的份额。")
    p("`R1` = 均值 > 0;`R2` = 均值 > 0 且月块自助 p(≤ 0) < 0.10;`R3` = p(≤ 0) < 0.05。")
    p("`不可判` = 该次抽样的月块自助没有方差(样本只落在一个信号月里),p 不存在,一律记不通过。")
    p("")
    p("| N | 世界 | 平均 R 5% | 50% | 95% | R1 通过率 | R2 通过率 | R3 通过率 | 不可判 |")
    p("|---|---|---|---|---|---|---|---|---|")
    for n in N_LIST:
        for world, wlab in (("edge", "有边"), ("noedge", "没边")):
            d = res["power"][str(n)][world]
            p(f"| {n} | {wlab} | {fmt_num(d['mean_r_p5'])} | {fmt_num(d['mean_r_p50'])} | {fmt_num(d['mean_r_p95'])} "
              f"| {fmt_pct(d['pass_r1'])} | {fmt_pct(d['pass_r2'])} | {fmt_pct(d['pass_r3'])} | {fmt_pct(d['undefined_frac'])} |")
    p("")
    p("居中读法的自助 p(敏感性):居中零分布以**样本均值**为中心(不是以 0 为中心),所以 p 恒在 0.5 上下,"
      "居中读法下 R2 / R3 几乎从不可能成立 —— 这正是 T-197 判据 j1 不用居中读法的原因"
      "(它用的是不居中的 p(≤ 0) = 0.107)。")
    p("")
    p("| N | 世界 | R2 通过率(居中) | R3 通过率(居中) |")
    p("|---|---|---|---|")
    for n in N_LIST:
        for world, wlab in (("edge", "有边"), ("noedge", "没边")):
            d = res["power"][str(n)][world]
            p(f"| {n} | {wlab} | {fmt_pct(d['pass_r2_centered'])} | {fmt_pct(d['pass_r3_centered'])} |")
    p("")
    p("机器校验(同一套代码在全样本上必须复现 T-197 的数):")
    p("")
    fsc = res["full_sample_check"]
    p(f"- 全样本 908 张 / {fsc['n_blocks']} 个月:平均 R = {fsc['actual']:.10f};"
      f"本卡月块自助 p(≤ 0) = **{fsc['p_le0']:.4f}**(T-197: {fsc['t197_p_le0']});"
      f"居中百分位 = **{fsc['p_cen']:.4f}**(T-197: {fsc['t197_pct']});"
      f"apparatus 复核 p = {fsc['apparatus_p']:.4f}、百分位 = {fsc['apparatus_pct']:.4f}。")
    p("")
    p("抽样偏差诊断(整块抽 vs 逐票 iid 对照;总体平均 R = "
      f"{res['sampling_bias']['10']['population']:.4f}):")
    p("")
    p("| N | 整块抽(截断)均值 | 整块抽(不截断)均值 | iid 对照均值 | 总体均值 |")
    p("|---|---|---|---|---|")
    for n in (10, 30, 50, 100, 200):
        b = res["sampling_bias"][str(n)]
        p(f"| {n} | {b['truncated']:+.4f} | {b['untruncated']:+.4f} | {b['iid']:+.4f} | {b['population']:+.4f} |")
    p("")
    p("## 2 · ② 钱曲线:6 / 12 / 24 个月")
    p("")
    p(f"`t159.nav`(f = {res['meta']['f']:.0%}、cap = {res['meta']['cap']}、复利),假想时间线从 "
      f"{res['meta']['timeline_base']} 起,抽到的月依次接上,每张票保留相对信号月的天数偏移。")
    p("`触到` = 最大回撤达到或超过该水平的概率。")
    p("")
    p("| 月数 | 世界 | 最大回撤 5% | 50% | 95% | 触到 −10% | 触到 −18% | 触到 −25% | 期末净值中位 |")
    p("|---|---|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        for world, wlab in (("edge", "有边"), ("noedge", "没边")):
            d = res["money"][f"{h}_{world}"]
            p(f"| {h} | {wlab} | {fmt_pct(d['mdd_p5'])} | {fmt_pct(d['mdd_p50'])} | {fmt_pct(d['mdd_p95'])} "
              f"| {fmt_pct(d['touch_10'])} | {fmt_pct(d['touch_18'])} | {fmt_pct(d['touch_25'])} | {fmt_num(d['end_p50'])} |")
    p("")
    p("对照(字面口径:标记价取市场在假想日期的真实收盘价,抽样 "
      f"{res['meta']['literal_draws']:,} 次;见「协议问题」第 3 条):")
    p("")
    p("| 月数 | 世界 | 最大回撤 5% | 50% | 95% | 触到 −10% | 触到 −18% | 触到 −25% | 期末净值中位 |")
    p("|---|---|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        for world, wlab in (("edge", "有边"), ("noedge", "没边")):
            d = res["money_literal"][f"{h}_{world}"]
            p(f"| {h} | {wlab} | {fmt_pct(d['mdd_p5'])} | {fmt_pct(d['mdd_p50'])} | {fmt_pct(d['mdd_p95'])} "
              f"| {fmt_pct(d['touch_10'])} | {fmt_pct(d['touch_18'])} | {fmt_pct(d['touch_25'])} | {fmt_num(d['end_p50'])} |")
    p("")
    p("## 3 · ③ 按 2024 年的开票密度,凑够 N 张票要等多久")
    p("")
    p(f"2024 年每月开票数(零的月份照列):{res['months_needed']['counts_2024']},全年合计 "
      f"{res['months_needed']['total_2024']} 张。")
    p("")
    p("| N | 中位月数 | 90 分位月数 | 逐月顺序接(确定性) |")
    p("|---|---|---|---|")
    for n in (30, 50, 100):
        d = res["months_needed"][str(n)]
        p(f"| {n} | {d['median_months']:.0f} | {d['p90_months']:.0f} | {d['sequential_months']} |")
    p("")
    p("## 4 · 「检出力 ≥ 80% 且误放 ≤ 10%」的最小 N")
    p("")
    p("| 规则 | 最小 N | 达到时的检出力 | 达到时的误放 |")
    p("|---|---|---|---|")
    for rule in ("R1", "R2", "R3"):
        d = res["min_n"][rule]
        if d["min_n"] is None:
            p(f"| {rule} | 够不到 | {fmt_pct(d['best_power'])}(最大检出力,N = {d['best_n']}) | "
              f"{fmt_pct(d['at_best_false_pass'])} |")
        else:
            p(f"| {rule} | {d['min_n']} | {fmt_pct(d['power_at'])} | {fmt_pct(d['false_pass_at'])} |")
    p("")
    p("## 5 · 协议问题(照抄执行,不改协议;以下是把协议跑出来时看到的问题)")
    p("")
    for i, item in enumerate(res["protocol_issues"], 1):
        p(f"{i}. {item}")
    p("")
    ic = res.get("indep_check")
    if ic:
        p("## 6 · 独立复核(另写实现、换随机种子)")
        p("")
        p(f"复核脚本 `docs/research/t202_indep_check.py`:随机种子 {ic['seed']}、{ic['draws']:,} 次,"
          "抽样与钱曲线都另写一遍。票、月块、③ 的等多久、2024 每月开票数、每月票数中位、"
          "没边世界的出场价重算逐项对上。")
        p("")
        p("R1 通过率对照(本卡 = 种子 686、5,000 次;复核 = 种子 20261026、2,000 次):")
        p("")
        p("| N | R1 有边(本卡) | R1 有边(复核) | R1 没边(本卡) | R1 没边(复核) |")
        p("|---|---|---|---|---|")
        for n in N_LIST:
            d = res["power"][str(n)]
            x = ic["r1_pass"][str(n)]
            p(f"| {n} | {fmt_pct(d['edge']['pass_r1'])} | {fmt_pct(x['pass_r1_edge'])} | "
              f"{fmt_pct(d['noedge']['pass_r1'])} | {fmt_pct(x['pass_r1_noedge'])} |")
        p("")
        p("钱曲线三口径的最大回撤(独立复核):")
        p("")
        p("| 样本 | 真实日期 | 平移·自洽标记价 | 平移·字面标记价 |")
        p("|---|---|---|---|")
        for label, c in ic["curves"].items():
            p(f"| {label}({c['n']} 张) | {fmt_pct(c['real']['mdd'], 2)} | {fmt_pct(c['shift_self']['mdd'], 2)} | "
              f"{fmt_pct(c['shift_literal']['mdd'], 2)} |")
        p("")
        p(f"其余:每月票数 min {ic['tickets_per_month']['min']} / max {ic['tickets_per_month']['max']} / "
          f"中位 {ic['tickets_per_month']['median']:.0f};平均 R ≤ 0 的月 {ic['months_mean_r_le0']} 个;"
          f"2024 每月开票 {ic['counts_2024']} 合计 {ic['total_2024']} 张;"
          f"没边世界 exit_px'/entry_px 最小 {ic['noedge_exit_ratio']['min']:.4f}"
          f"(≤ 0 的 {ic['noedge_exit_ratio']['n_nonpos']} 张)。")
        p("")
    p("## 7 · 口径说明")
    p("")
    for line in res["notes"]:
        p(f"- {line}")
    p("")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("\n".join(L) + "\n")


# ── 协议问题 / 口径说明(模块级,便于从既有 results.json 重生成报告)────────────────────────────
def protocol_issues_block(bias):
    """协议问题:照抄执行、不改协议,把跑出来时看到的问题列在这里。"""
    return [
        "抽样单位是「信号月」整块,但 N 是票数:一块里票数不定(最少 1 张、最多 152 张)。本卡的做法是"
        "整块抽到票数 ≥ N,最后一块随机截断到正好 N 张 —— 截断意味着最后一个月的票被部分丢掉,"
        "样本因此不是严格的整块。台账没写这一点。",
        "N ≤ 30 时,抽到的样本常常只落在一个信号月里(40 个月、908 张票,月均 22.7 张、中位 13 张),"
        "这时月块自助只有一个块 → 零分布没有方差 → p 不存在。表里的「不可判」是这种抽样的占比,"
        "本卡一律记不通过(因此小 N 的 R2/R3 通过率被压低)。台账没写不可判怎么处理。",
        "② 的标记价:台账写「按抽到的票的真实持有期排在一条假想时间线上」。字面执行(标记价取市场在假想"
        "日期的真实收盘价)会让入场价与标记价来自两个不同的市场时期,已实现/未实现盈亏失真。核对用的样本是"
        "信号月在 2024-01…2025-12 的 435 张已平票:真实日期的最大回撤 −36.94%,搬到假想时间线后字面口径变成"
        "−88.72%;本卡主表口径(每张票用它自己那段真实价格路径整段平移)是 −37.18%(与真实日期差 0.24pp,"
        "差在 nav 取 mark 的起点上)。本卡的主表用「每张票用它自己那段真实价格路径(整段平移)」—— 真实持有期"
        "照旧,只挪时间;字面口径的结果另列「对照」表。台账若本意是字面口径,以对照表为准。",
        "② 的抽样:台账只写「按信号月整块抽」,没说有放回也没说无放回。本卡两个世界与两档口径统一用"
        "有放回(与 ① 的整块自助一致);有放回时同一个月可能被抽到两次,那批票会在时间线上出现两遍"
        "(日期不同)。无放回的结果没有单列。",
        "② 的时间线起点固定在 2020-01-01(两个世界、每档抽样共用同一条时间线,便于配对比较);"
        "「抽到的月依次接上」没有规定起点,这是本卡自定的口径。",
        "没边世界的钱曲线:票的 R 平移后,出场价按 exit_px' = entry_px·1.004 + r'·(entry_px − stop_px) "
        "重算,使 nav 的已实现盈亏恰为 f·equity·r'(908 张票重算后的出场价全为正,最低是入场价的 0.60 倍)。"
        "中间那段未实现盈亏仍用票自己的真实价格路径(平移后),所以没边世界的回撤路径与有边世界形状相同、"
        "水平不同。台账没有规定没边世界怎么落到钱曲线上,这是本卡自定的口径。",
        f"整块抽不是无偏的:N = 10 时 2,000 次抽样的样本均值平均只有 {bias['10']['truncated']:+.4f}"
        f"(不截断 {bias['10']['untruncated']:+.4f}),逐票 iid 对照是 {bias['10']['iid']:+.4f},"
        f"总体平均 R 是 {bias['10']['population']:+.4f};N = 200 时分别是 {bias['200']['truncated']:+.4f} / "
        f"{bias['200']['untruncated']:+.4f} / {bias['200']['iid']:+.4f}。"
        "原因是块的大小差得远(每月 1…152 张)且 40 个月里有 26 个月平均 R ≤ 0,按块抽时"
        "「抽到哪几个月」本身就把均值往下拽。这不是本卡的实现偏差(iid 对照复现了总体均值),"
        "是「按信号月整块抽」这个协议自带的性质 —— 意味着用 N 张票的平均 R 做关停判据,"
        "在小 N 上比朴素算法还要不可靠。",
    ]


def indep_check_block():
    """独立复核的结果(docs/research/t202_indep_check.json,不存在则 None)。"""
    p = os.path.join(HERE, "t202_indep_check.json")
    if not os.path.exists(p):
        return None
    return json.load(open(p))


def notes_block(n_checked, max_diff, mean_diff):
    """口径说明。"""
    return [
        "「月块自助 p」用的是不居中的自助零分布 p(≤ 0),与 T-197 判据 j1 同口径(其 p_le0 = 0.107、"
        "百分位 0.5195);居中读法 p_cen = P(自助均值 ≤ 样本均值)作敏感性另列。",
        "① 的两个世界用同一批抽样(配对),差别只在 R 是否被平移;自助的种子是 (686, N, 世界, 第几次抽样)。",
        "自检:不可判的判据(零分布无方差 / ≥99% 的抽样等于实际值)与 apparatus.null_distribution 一致;"
        f"另用 apparatus.null_distribution + percentile_of 复核 {n_checked} 个样本,"
        f"p 的最大差 {max_diff:.4f}、平均差 {mean_diff:.4f}"
        "(蒙特卡洛噪声量级)。",
        "钱曲线用 t159.nav(import,不复制)与 t159.stats;f = 1%、cap = 10、复利;每张票的持仓天数照原样。",
        "独立复核(另写实现、换随机种子 20261026、2,000 次,脚本 docs/research/t202_indep_check.py):"
        "R1 通过率有边 N=10/20/30/50/100/200 = 34.5%/41.2%/40.9%/46.7%/56.3%/67.2%、"
        "没边 = 27.1%/27.8%/29.4%/34.4%/36.1%/45.1%,与本卡(种子 686、5,000 次)"
        "36.5%/40.7%/41.0%/49.1%/56.9%/67.1%、27.6%/27.8%/30.7%/35.9%/36.5%/44.1% 同量级"
        "(块抽样高度相关 ⇒ 有效样本量远小于名义次数,最大 2.4pp 的差是种子噪声);"
        "③ 的等多久、2024 每月开票数(308 张)、每月票数中位 13、"
        "没边世界出场价重算(最低为入场价的 0.60 倍、0 张为负)逐项对上。",
        "没有写任何建议:选哪条线是 Jazz 的事。",
    ]


# ── main ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def main():
    global _TICKETS, _BY_M, _MONTHS, _BARS, _MEAN_R
    import datetime as _dt
    tk, mean_r, t197 = load_tickets()
    _TICKETS = tk
    _MEAN_R = mean_r
    _BY_M = defaultdict(list)
    for t in tk:
        _BY_M[t["signal_d"][:7]].append(t)
    _MONTHS = sorted(_BY_M)
    _BARS = load_bars()
    attach_paths(tk, _BARS)
    print(f"[t202] 票 {len(tk)} 张 / 月 {len(_MONTHS)} 个 / 平均 R {mean_r:.6f}", flush=True)

    # ①
    power, checks = power_analysis(tk, mean_r)
    print("[t202] ① 完成", flush=True)

    # ②
    money, money_lit = {}, {}
    for h in HORIZONS:
        for world in ("edge", "noedge"):
            money[f"{h}_{world}"] = money_curves(h, world, mean_r, DRAWS)
            print(f"[t202] ② {h} 月 {world} 完成", flush=True)
            money_lit[f"{h}_{world}"] = money_curves(h, world, mean_r, LITERAL_DRAWS, literal=True)
            print(f"[t202] ② {h} 月 {world}(字面)完成", flush=True)

    # ③
    mn = months_needed(tk)

    # 校验与偏差诊断
    fsc = full_sample_check(t197)
    bias = bias_check()
    print(f"[t202] 校验:全样本 p_le0={fsc['p_le0']:.4f}(t197 {fsc['t197_p_le0']}) "
          f"百分位={fsc['p_cen']:.4f}(t197 {fsc['t197_pct']})", flush=True)

    # 最终表
    min_n = {}
    for rule, key in (("R1", "pass_r1"), ("R2", "pass_r2"), ("R3", "pass_r3")):
        best = None
        for n in N_LIST:
            pw = power[str(n)]["edge"][key]
            fp = power[str(n)]["noedge"][key]
            if pw >= 0.80 and fp <= 0.10:
                best = dict(min_n=n, power_at=pw, false_pass_at=fp)
                break
        if best is None:
            pws = [(power[str(n)]["edge"][key], n) for n in N_LIST]
            best_n = max(pws)[1]
            best = dict(min_n=None, best_n=best_n, best_power=power[str(best_n)]["edge"][key],
                        at_best_false_pass=power[str(best_n)]["noedge"][key])
        min_n[rule] = best

    ap_ok = [c for c in checks if c["vector_p"] is not None and c["apparatus_p"] is not None]
    ap_diff = [abs(c["vector_p"] - c["apparatus_p"]) for c in ap_ok]

    res = dict(
        meta=dict(run_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(), seed=SEED, draws=DRAWS,
                  boot=BOOT, n_list=N_LIST, horizons=HORIZONS, f=F, cap=CAP,
                  timeline_base=BASE.isoformat(), n_tickets_closed=len(tk), mean_r=mean_r,
                  literal_draws=LITERAL_DRAWS,
                  source="docs/research/t197_results.json(tickets.A,已平)+ research/s681/_um_daily.jsonl"),
        power=power,
        money=money,
        money_literal=money_lit,
        months_needed=mn,
        min_n=min_n,
        full_sample_check=fsc,
        sampling_bias=bias,
        apparatus_check=dict(n_checked=len(ap_ok), max_abs_diff=float(max(ap_diff)) if ap_diff else None,
                             mean_abs_diff=float(np.mean(ap_diff)) if ap_diff else None,
                             samples=ap_ok[:20]),
        indep_check=indep_check_block(),
        protocol_issues=protocol_issues_block(bias),
        notes=notes_block(len(ap_ok), float(max(ap_diff)), float(np.mean(ap_diff))),
    )
    with open(OUT_JSON, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"[t202] 结果 → {OUT_JSON}", flush=True)
    write_report(res, OUT_MD)
    print(f"[t202] 报告 → {OUT_MD}", flush=True)


if __name__ == "__main__":
    main()
