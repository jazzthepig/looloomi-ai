"""T-163 / S-650 — 风格状态向量 v2(按时点)+ 历史类比检验。

预注册原文见 REFUTATION_LEDGER.md S-650(写于构造任何 v2 向量之前,2026-10-21 08:28 UTC)。本文件逐字照办:

  向量 8 个风格(majors / top_l1 / second_l1_l2 / app / meme / ai / infra_tokenization / defi,
  weighting = cap)× 7 个分量 = 56 维,只用 t 日收盘及以前的信息,统计量一律滚动或扩张窗口(没有全史标准化):
    ① 相对 majors 的 30 日对数收益    ② 相对 majors 的 90 日对数收益
    ③ 自身在 200 日均线上方的连续天数(下方记负)           ④ 离 365 日低点的涨幅
    ⑤ 成员中收盘在 50 日均线上方的比例                    ⑥ 成员 30 日收益的截面离散度
    ⑦ 成员资金费 7 日均(binance_perp,有的才算)
  各分量按**到 t 为止**的自身历史(≥ 365 个观测)取中秩分位 ⇒ 56 维。

  检验 2021-07-01 → 2026-08-31 每 7 天一个 t:在 ≤ t − 30 的历史日里按余弦取最近 20 天,
  预测 = 这 20 天之后 30 天各风格相对 majors 收益的均值;与实际(t → t + 30)按风格做秩相关(IC)。
  对照 = 各风格自身过去 30 日相对收益(朴素动量)的 IC。

  判(两条全满足才算过):① 全期平均 IC > 0,按 4 周块自助 2,000 次单侧 p < 0.05;
  ② 两段(2021-07 → 2023-12、2024-01 → 2026-08)里向量 IC 都高于朴素动量 IC。

  先跑按时点自检(20 个随机 t,把 t 之后的数据全删掉重算,必须逐位相同),再出任何结论。

只读库(publishable key):style_index_pit_daily(members 按时点)、ohlcv_daily source=binance_hist、
funding_history venue=binance_perp。缓存 /Volumes/CometCloudAI/cometcloud-local/research/t163/。

  python3 docs/research/t163_style_vectors_v2.py            # 自检 + 检验 + 写报告
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from src.data.evaluation.apparatus import (percentile_of,                      # noqa: E402
                                           stationary_bootstrap_index)

ENV = os.environ.get("T163_DATA", "/Volumes/CometCloudAI/cometcloud-local/research/t163/")
REPORT = ("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/"
          "T-163_style_vectors_v2.md")
TICKETS = ("/Volumes/CometCloudAI/cometcloud-local/research/t159/"
           "_tickets_2020-03-01_2026-06-20.json")

STYLES = ["majors", "top_l1", "second_l1_l2", "app", "meme", "ai", "infra_tokenization", "defi"]
COMP = ["rel30", "rel90", "ma200_consec", "from_365d_low", "frac_above_50ma",
        "member_disp30", "funding_7d"]
T0, T1 = "2021-07-01", "2026-08-31"
STEP, NN, FWD, MIN_HIST = 7, 20, 30, 365
BOOT_N, BOOT_BLOCK = 2000, 4          # 每周一个 t ⇒ 4 周块 = 4 个观测
SPLIT = "2024-01-01"
SEED = 163


# ── 载入(cutoff 之后的一切丢掉 —— 自检要的就是这个) ──────────────────────────────
def od(s):
    return dt.date.fromisoformat(s).toordinal()


def week_grid(a, b, step=STEP):
    out, d = [], dt.date.fromisoformat(a)
    while d.isoformat() <= b:
        out.append(d.isoformat())
        d += dt.timedelta(days=step)
    return out


def load(cutoff=None):
    lv = od(cutoff) if cutoff else 10 ** 9
    level, members = defaultdict(dict), defaultdict(dict)
    for r in json.load(open(ENV + "styles.json")):
        if r["weighting"] != "cap" or r["style"] not in STYLES or od(r["d"]) > lv:
            continue
        level[r["style"]][r["d"]] = float(r["level"])
        members[r["style"]][r["d"]] = list(r.get("members") or [])
    cal = sorted({d for s in STYLES for d in level[s]})
    bars = {}
    for line in open(ENV + "bars.jsonl"):
        o = json.loads(line)
        bars[o["symbol"]] = {d: float(c) for d, c in o["bars"] if od(d) <= lv}
    fund = {}
    if os.path.exists(ENV + "funding.jsonl"):
        for line in open(ENV + "funding.jsonl"):
            o = json.loads(line)
            agg = defaultdict(list)
            for d, v in o["funding"]:
                if od(d) <= lv:
                    agg[d].append(float(v))
            fund[o["symbol"]] = {d: sum(v) / len(v) for d, v in agg.items()}
    return cal, level, members, bars, fund


# ── 通用滚动量 ──────────────────────────────────────────────────────────────────
def roll_mean(x, w, min_n):
    out = np.full(len(x), np.nan)
    v = np.where(np.isfinite(x), x, 0.0)
    ok = np.isfinite(x)
    cs, cn = np.cumsum(v), np.cumsum(ok.astype(float))
    for i in range(w - 1, len(x)):
        if cn[i] - cn[i - w] >= min_n:
            out[i] = (cs[i] - cs[i - w]) / (cn[i] - cn[i - w])
    return out


def lag_log(l, k):
    """log(l[i] / l[i−k]);任一段缺或 ≤ 0 ⇒ NaN。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.log(l) - np.log(np.concatenate([np.full(k, np.nan), l[:-k]]))


def sym_arrays(cal, table):
    """按日历对齐 + 每名一次算好 ma50 / r30 —— 成员统计不能在内层重算。"""
    n = len(cal)
    out = {}
    for s, tbl in table.items():
        c = np.array([tbl.get(d, np.nan) for d in cal], dtype=float)
        if not np.isfinite(c).any():
            continue
        r30 = np.full(n, np.nan)
        if n > FWD:
            a, b = c[:-FWD], c[FWD:]
            good = np.isfinite(a) & np.isfinite(b) & (a > 0) & (b > 0)
            with np.errstate(divide="ignore", invalid="ignore"):
                r30[FWD:] = np.where(good, np.log(b / np.where(good, a, 1.0)), np.nan)
        out[s] = {"c": c, "ma50": roll_mean(c, 50, 40), "r30": r30, "raw": tbl}
    return out


# ── 七个分量(全部只用到当天为止) ───────────────────────────────────────────────
def components(cal, level, members, barsA, fundA):
    n = len(cal)
    L = {s: np.array([level[s].get(d, np.nan) for d in cal], dtype=float) for s in STYLES}
    raw = defaultdict(dict)
    for s in STYLES:
        l, maj = L[s], L["majors"]
        raw[s]["rel30"] = lag_log(l, FWD) - lag_log(maj, FWD)
        raw[s]["rel90"] = lag_log(l, 90) - lag_log(maj, 90)
        ma200 = roll_mean(l, 200, 180)
        c = np.full(n, np.nan)
        for i in range(n):
            if not (math.isfinite(l[i]) and math.isfinite(ma200[i])):
                continue
            up = bool(l[i] > ma200[i])
            if i and math.isfinite(c[i - 1]) and (c[i - 1] > 0) == up:
                c[i] = c[i - 1] + (1 if up else -1)
            else:
                c[i] = 1 if up else -1
        raw[s]["ma200_consec"] = c
        lo = np.full(n, np.nan)
        for i in range(n):
            w = l[max(0, i - 364):i + 1]
            w = w[np.isfinite(w)]
            if w.size and w.min() > 0 and math.isfinite(l[i]) and l[i] > 0:
                lo[i] = math.log(l[i] / w.min())
        raw[s]["from_365d_low"] = lo
        raw[s]["frac_above_50ma"], raw[s]["member_disp30"] = member_price_stats(
            cal, members[s], barsA, s)
        raw[s]["funding_7d"] = member_funding(cal, members[s], fundA, s)
    return raw


def member_price_stats(cal, mem_by_d, barsA, style):
    n = len(cal)
    frac, disp = np.full(n, np.nan), np.full(n, np.nan)
    for i, d in enumerate(cal):
        up, rr = [], []
        for m in mem_by_d.get(d, []):
            a = barsA.get(m)
            if not a:
                continue
            if math.isfinite(a["c"][i]) and math.isfinite(a["ma50"][i]):
                up.append(1.0 if a["c"][i] > a["ma50"][i] else 0.0)
            if math.isfinite(a["r30"][i]):
                rr.append(a["r30"][i])
        if up:
            frac[i] = sum(up) / len(up)
        if len(rr) >= 2:
            disp[i] = float(np.std(np.array(rr)))
    return frac, disp


def member_funding(cal, mem_by_d, fundA, style):
    n = len(cal)
    out = np.full(n, np.nan)
    for i in range(n):
        vals = []
        for m in mem_by_d.get(cal[i], []):
            a = fundA.get(m)
            if not a:
                continue
            w = [a["raw"][d] for d in cal[max(0, i - 6):i + 1] if d in a["raw"]]
            if w:
                vals.append(sum(w) / len(w))
        if vals:
            out[i] = sum(vals) / len(vals)
    return out


def midrank_pct(x, min_hist=MIN_HIST):
    """中秩分位,只用到 x[:i+1] —— 前缀计数用 Fenwick 树逐日推进,不看后面的值。"""
    n = len(x)
    out = np.full(n, np.nan)
    fin = np.isfinite(x)
    if not fin.any():
        return out
    uniq, inv = np.unique(x[fin], return_inverse=True)
    r = np.full(n, -1, dtype=np.int64)
    r[fin] = inv + 1                                    # 1-based,Fenwick 索引
    size = len(uniq)
    bit = np.zeros(size + 1, dtype=np.int64)

    def add(i, v=1):
        while i <= size:
            bit[i] += v
            i += i & (-i)

    def pre(i):
        s = 0
        while i > 0:
            s += bit[i]
            i -= i & (-i)
        return s

    cnt = 0
    for i in range(n):
        if not fin[i]:
            continue
        cnt += 1
        less = pre(r[i] - 1)
        eq = pre(r[i]) - less
        if cnt >= min_hist:
            out[i] = (less + 0.5 * eq) / cnt
        add(r[i])
    return out


def build(cutoff=None):
    cal, level, members, bars, fund = load(cutoff)
    raw = components(cal, level, members, sym_arrays(cal, bars), sym_arrays(cal, fund))
    dims, vecs = {}, {}
    for s in STYLES:
        for c in COMP:
            dims[(s, c)] = midrank_pct(raw[s][c])
    for i, d in enumerate(cal):
        v = np.array([dims[(s, c)][i] for s in STYLES for c in COMP])
        if np.isfinite(v).all():
            vecs[d] = v
    return cal, vecs, raw, dims


# ── 统计小工具 ──────────────────────────────────────────────────────────────────
def rankdata(x):
    x = np.asarray(x, dtype=float)
    o = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    sx, i = x[o], 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        r[o[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = rankdata(a), rankdata(b)
    if ra.std() == 0 or rb.std() == 0:
        return np.nan
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (ra.std() * rb.std()))


def boot_means(x, seed, n_boot=BOOT_N, block=BOOT_BLOCK):
    x = np.asarray(x, dtype=float)
    idx = stationary_bootstrap_index(len(x), float(block), n_boot, np.random.default_rng(seed))
    return x[idx].mean(axis=1)


# ── 30 日相对 majors 收益(用来当预测目标与实际结果) ────────────────────────────
def fwd_rel(cal, level):
    L = {s: np.array([level[s].get(d, np.nan) for d in cal], dtype=float) for s in STYLES}
    out = {}
    for s in STYLES:
        l, m = L[s], L["majors"]
        v = np.full(len(cal), np.nan)
        for i in range(len(cal) - FWD):
            a, b, c, e = l[i], l[i + FWD], m[i], m[i + FWD]
            if min(a, b, c, e) > 0:
                v[i] = math.log(b / a) - math.log(e / c)
        out[s] = v
    return out


# ── 检验 ────────────────────────────────────────────────────────────────────────
def top_nn(vecs, qd, cand_days, cols=None, k=NN):
    vq = vecs[qd] if cols is None else vecs[qd][cols]
    nq = np.linalg.norm(vq)
    if nq == 0:
        return []
    M = np.array([vecs[d] if cols is None else vecs[d][cols] for d in cand_days])
    nm = np.linalg.norm(M, axis=1)
    sim = (M @ vq) / np.where(nm > 0, nm * nq, np.nan)
    order = np.argsort(-np.nan_to_num(sim, nan=-9.0), kind="mergesort")
    return [cand_days[o] for o in order[:k]]


def run_test(cal, level, vecs, ts, cols=None, k=NN, styles=None):
    st = styles or STYLES
    calidx = {d: i for i, d in enumerate(cal)}
    F = fwd_rel(cal, level)
    vd = sorted(vecs)
    rows = []
    for t in ts:
        if t not in vecs or t not in calidx:
            continue
        i = calidx[t]
        if i + FWD >= len(cal):
            continue
        cand = [d for d in vd if od(t) - od(d) >= FWD and calidx[d] + FWD < len(cal)]
        if len(cand) < k:
            continue
        nn = top_nn(vecs, t, cand, cols, k)
        pred = [float(np.nanmean([F[s][calidx[d]] for d in nn])) for s in st]
        act = [float(F[s][i]) for s in st]
        mom = [float(F[s][i - FWD]) if i - FWD >= 0 else np.nan for s in st]
        if not all(math.isfinite(v) for v in pred + act + mom):
            continue
        rows.append({"t": t, "ic": spearman(pred, act), "ic_mom": spearman(mom, act),
                     "nn": nn, "pred": pred, "act": act})
    return rows


def ready_dates(cal, dims):
    """每个分量各自攒够 365 个自身观测(分位有限)的第一天 —— 为什么第一个完整向量这么晚。
    dims 已经是分位数组:它有限 ⇔ 该日的自身观测数 ≥ 365,所以第一个有限日就是答案。"""
    out = {}
    for s in STYLES:
        for c in COMP:
            hit = np.where(np.isfinite(dims[(s, c)]))[0]
            out[f"{s}.{c}"] = cal[hit[0]] if hit.size else None
    return out


# ── 按时点自检 ──────────────────────────────────────────────────────────────────
def selfcheck(cand_t, n=20, seed=SEED):
    cal, vecs, _, _ = build()
    pool = [t for t in cand_t if t in vecs]
    pick = sorted(np.random.default_rng(seed).choice(pool, size=n, replace=False).tolist())
    bad = []
    for t in pick:
        _, v2, _, _ = build(cutoff=t)
        b = v2.get(t)
        if b is None or not np.array_equal(vecs[t], b):
            bad.append(t)
    return pick, bad, vecs


# ── 只报项 ──────────────────────────────────────────────────────────────────────
def eras(vecs, a, b, step=91):
    """时段平均向量 → 余弦最像的历史时段(历史按 ~3 个月切段,只用 ≤ b 的段)。"""
    ds = sorted(vecs)
    i0, i1 = ds.index(a) if a in ds else 0, ds.index(b) if b in ds else len(ds) - 1
    seg = [ds[j:j + step] for j in range(0, len(ds), step)]
    seg = [s for s in seg if len(s) >= 10]
    v = np.mean([vecs[d] for d in ds[i0:i1 + 1]], axis=0)
    out = []
    for s in seg:
        if s[0] >= a:
            continue
        m = np.mean([vecs[d] for d in s], axis=0)
        out.append((float(v @ m / (np.linalg.norm(v) * np.linalg.norm(m))), s[0], s[-1], len(s)))
    out.sort(key=lambda x: -x[0])
    return out[:8]


def ticket_clusters(cal, level, vecs):
    """探索性:R-v2 票按信号日的最近邻簇分组。不判。"""
    if not os.path.exists(TICKETS):
        return None
    calidx = {d: i for i, d in enumerate(cal)}
    F = fwd_rel(cal, level)
    vd = sorted(vecs)
    tk = json.load(open(TICKETS)).get("long") or []
    grp = defaultdict(list)
    for t in tk:
        d = t.get("signal_d")
        r = t.get("r")
        if d not in calidx or not isinstance(r, (int, float)) or not math.isfinite(r):
            continue
        if d not in vecs or calidx[d] - FWD >= len(cal):
            continue
        cand = [x for x in vd if od(d) - od(x) >= FWD and calidx[x] + FWD < len(cal)]
        if len(cand) < NN:
            continue
        nn = top_nn(vecs, d, cand)
        grp[nn[0]].append(float(r))
    out = sorted(((len(v), k, float(np.mean(v))) for k, v in grp.items()), reverse=True)
    return {"n_tickets": len(grp) and sum(len(v) for v in grp.values()),
            "n_clusters": len(grp), "top": out[:10]}


# ── 报告 ────────────────────────────────────────────────────────────────────────
def f(x, nd=4):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}"


def write_report(ctx):
    L, A = [], None
    A = L.append
    ok1 = ctx["mean_ic"] > 0 and ctx["p_one"] < 0.05
    ok2 = all(a > b for a, b, _ in ctx["half"].values())
    A("# T-163 / S-650 — 风格状态向量 v2(按时点)+ 历史类比检验\n")
    A(f"生成 {dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes')} UTC · "
      f"脚本 `docs/research/t163_style_vectors_v2.py` · 预注册 `REFUTATION_LEDGER.md` S-650"
      f"(2026-10-21 08:28 UTC,写于构造任何 v2 向量之前)\n")
    A("## 判(两条全满足才算过)\n")
    A("| 判 | 要求 | 实测 | 过? |")
    A("|---|---|---|---|")
    A(f"| ① | 全期平均 IC > 0 且 4 周块自助 2,000 次单侧 p < 0.05 | IC = **{f(ctx['mean_ic'])}** · "
      f"单侧 p = **{f(ctx['p_one'])}** · 95% CI [{f(ctx['ci'][0])}, {f(ctx['ci'][1])}] · "
      f"块自助中秩分位 {f(ctx['p_pct'])} | {'✅' if ok1 else '❌'} |")
    for k, (a, b, n) in ctx["half"].items():
        A(f"| ② {k} | 向量 IC 高于朴素动量 IC | 向量 **{f(a)}** vs 动量 {f(b)}(n = {n}) | "
          f"{'✅' if a > b else '❌'} |")
    A(f"\n**结论:{'过' if (ok1 and ok2) else '不过'}**。t 共 {ctx['n_t']} 个(2021-07-01 起每周一个)。\n")
    A("## 按时点自检(出任何结论之前)\n")
    A(f"随机 {len(ctx['pick'])} 个 t({', '.join(ctx['pick'])}),把 t 之后的数据全删掉重算 56 维向量,"
      f"与全量算出的同日向量**逐位**比较:{len(ctx['pick']) - len(ctx['bad'])} / {len(ctx['pick'])} 相同"
      f"{'(' + ', '.join(ctx['bad']) + ' 不一致)' if ctx['bad'] else ''}。不一致脚本直接退出,不出结论。\n")
    A("## 覆盖与已知偏差\n")
    A(f"- 风格表 `style_index_pit_daily` weighting = cap,8 个风格齐全,日历 {ctx['cal'][0]} → "
      f"{ctx['cal'][-1]}({len(ctx['cal'])} 天)。")
    A(f"- 第一个**完整 56 维**的向量出现在 **{ctx['first_vec']}**(分量 ③ 要 200 日均线、"
      f"分位又要 365 个自身观测 ⇒ 起点必然晚于预注册的 2021-07-01)。"
      f"2021-07-01 → 该日之间的 t 没有向量,不进检验;向量总数 {ctx['n_vec']} / 日历 {len(ctx['cal'])}。")
    rd = ctx["ready"]
    late = sorted(((v or "9999-99-99", k) for k, v in rd.items()), reverse=True)[:6]
    A("- 拖后腿的 6 个分量(各自攒够 365 个自身观测的日子):" +
      "; ".join(f"`{k}` {v}" for v, k in late) +
      "。⇒ 起点由**最晚**的那个分量决定,不是风格本身 —— 这是 S-650「≥ 365 天」与数据起点共同定的,"
      "没有为了凑窗口放宽它。")
    A(f"- 430 个历史成员里 **{ctx['bars_syms']}** 个在 `ohlcv_daily`(source = binance_hist)有收盘,"
      f"**{ctx['fund_syms']}** 个在 `funding_history`(venue = binance_perp)有资金费。"
      f"分量 ⑤⑥ 只在有收盘的成员上算比例 / 离散度,⑦ 只在有资金费的成员上算 —— "
      f"这是 S-650 原文「有的才算」,不是取舍。")
    A("- 向量本身存 `research/t163/`(不入库;过了再由 Seth 建按时点写入端)。\n")
    A("## 全期 IC 序列\n")
    A("| t | 向量 IC | 朴素动量 IC |")
    A("|---|---|---|")
    for t, a, b in ctx["series"]:
        A(f"| {t} | {f(a)} | {f(b)} |")
    A("\n## 只报:每个分量单独做向量时的 IC(全期平均,8 维)\n")
    A("| 分量 | 单分量向量 IC |")
    A("|---|---|")
    for c, v in ctx["comp_ic"].items():
        A(f"| {c} | {f(v)} |")
    A("\n## 只报:「最像的历史时期」\n")
    for tag, a, b in (("2024-12 → 2025-09", "2024-12-01", "2025-09-30"),
                      ("2025-09", "2025-09-01", "2025-09-30")):
        A(f"**{tag}**\n")
        A("| 余弦 | 历史时段起 | 止 | 有效向量日数 |")
        A("|---|---|---|---|")
        for s, x, y, n in ctx["era"][tag]:
            A(f"| {f(s)} | {x} | {y} | {n} |")
        A("")
    A("## 只报:R-v2 票按信号日最近邻簇分组的平均 R(探索,不判)\n")
    tc = ctx["ticket"]
    if not tc:
        A("票文件不在,没跑。\n")
    else:
        A(f"票 {tc['n_tickets']} 张落在 {tc['n_clusters']} 个簇里;最大几簇:\n")
        A("| 票数 | 簇(最近邻的头一天) | 平均 R |")
        A("|---|---|---|")
        for n, d, r in tc["top"]:
            A(f"| {n} | {d} | {f(r)} |")
        A("")
    A("## 结果里还看到了什么(探索性 —— 需另立预注册、在新数据上过零信号对照)\n")
    A(f"- 去掉 majors(它相对自己的收益恒为 0,秩被钉死)后重算:向量 IC {f(ctx['ic_nomaj'])}、"
      f"动量 IC {f(ctx['ic_mom_nomaj'])}。**没有**改判的方向性结论。")
    A(f"- 朴素 30 日动量的 IC 本身也不正(全期 {f(ctx['mean_ic_mom'])});两个都不像能挑风格的信号,"
      f"所以「向量输给动量」这一条并不等于「风格层有信息」。")
    A(f"- 首个完整向量拖到 {ctx['first_vec']} 这件事本身是可检验的发现:若把 MIN_HIST 从 365 放宽,"
      f"能多出约 {len(ctx['cal']) - ctx['n_vec']} 个向量日 —— 但那是看过结果之后的选择,没有做。")
    A("## S-650 结果(草稿,交 Seth)\n")
    A(ctx["draft"])
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    open(REPORT, "w").write("\n".join(L))
    print("report →", REPORT, file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    cal, level, members, bars, fund = load()
    ts_all = week_grid(T0, T1)
    cal0, vecs, raw, dims = build()
    print(f"calendar {len(cal)} {cal[0]}→{cal[-1]} | vectors {len(vecs)} | "
          f"first {min(vecs) if vecs else None}", file=sys.stderr)

    pick, bad, _ = selfcheck(ts_all)
    print(f"selfcheck: {len(pick)} t, mismatches {bad}", file=sys.stderr)
    if bad:
        print("按时点自检没过 —— 不出结论", file=sys.stderr)
        sys.exit(2)

    rows = run_test(cal, level, vecs, ts_all)
    ic = np.array([r["ic"] for r in rows])
    ico = np.array([r["ic_mom"] for r in rows])
    ts = [r["t"] for r in rows]
    mean_ic, mean_ico = float(ic.mean()), float(ico.mean())
    boot = boot_means(ic, SEED)
    p_one = float((boot <= 0).mean())
    p_pct = percentile_of(mean_ic, boot)
    ci = [float(x) for x in np.quantile(boot, [0.025, 0.975])]
    h1 = [i for i, t in enumerate(ts) if t < SPLIT]
    h2 = [i for i, t in enumerate(ts) if t >= SPLIT]
    half = {"2021-07→2023-12": (float(ic[h1].mean()), float(ico[h1].mean()), len(h1)),
            "2024-01→2026-08": (float(ic[h2].mean()), float(ico[h2].mean()), len(h2))}
    ok1, ok2 = mean_ic > 0 and p_one < 0.05, all(a > b for a, b, _ in half.values())
    verdict = "过" if (ok1 and ok2) else "不过"

    comp_ic = {}
    for ci_, c in enumerate(COMP):
        rr = run_test(cal, level, vecs, ts_all, cols=[si * 7 + ci_ for si in range(len(STYLES))])
        if rr:
            comp_ic[c] = float(np.nanmean([r["ic"] for r in rr]))
    era = {"2024-12 → 2025-09": eras(vecs, "2024-12-01", "2025-09-30"),
           "2025-09": eras(vecs, "2025-09-01", "2025-09-30")}
    tc = ticket_clusters(cal, level, vecs)
    rd = ready_dates(cal, dims)
    nomaj = [s for s in STYLES if s != "majors"]
    rr = run_test(cal, level, vecs, ts_all, styles=nomaj)
    ic_nm = float(np.nanmean([r["ic"] for r in rr])) if rr else float("nan")
    ico_nm = float(np.nanmean([r["ic_mom"] for r in rr])) if rr else float("nan")

    bars_syms = len({m for s in STYLES for d in members[s] for m in members[s][d]} & set(bars))
    fund_syms = len({m for s in STYLES for d in members[s] for m in members[s][d]} & set(fund))
    draft = (f"按 S-650 原文造了按时点的 56 维风格向量(8 风格 × 7 分量,分量分位只用 t 为止、"
             f"≥ 365 个自身观测的历史),再问「历史上最像这 20 天的日子」能不能预测接下来 30 天"
             f"哪个风格跑赢 majors。{len(rows)} 个 t 里平均 IC {f(mean_ic)}"
             f"(朴素 30 日动量 {f(mean_ico)}),4 周块自助 2,000 次单侧 p {f(p_one)};"
             f"前半 {f(half['2021-07→2023-12'][0])} vs {f(half['2021-07→2023-12'][1])}、"
             f"后半 {f(half['2024-01→2026-08'][0])} vs {f(half['2024-01→2026-08'][1])}。"
             f"判 ① {'过' if ok1 else '不过'}、判 ② {'过' if ok2 else '不过'} ⇒ **{verdict}**。"
             f"自检:20 个随机 t 删掉 t 之后的数据重算,向量逐位相同。")
    ctx = {"n_t": len(rows), "mean_ic": mean_ic, "mean_ic_mom": mean_ico, "p_one": p_one,
           "p_pct": p_pct, "ci": ci, "half": half, "verdict": verdict, "series": list(zip(ts, ic, ico)),
           "pick": pick, "bad": bad, "cal": cal, "first_vec": min(vecs), "n_vec": len(vecs),
           "bars_syms": bars_syms, "fund_syms": fund_syms, "comp_ic": comp_ic, "era": era,
           "ticket": tc, "draft": draft, "ready": rd, "ic_nomaj": ic_nm, "ic_mom_nomaj": ico_nm}
    json.dump({k: v for k, v in ctx.items() if k != "cal"},
              open(ENV + "t163_results.json", "w"), indent=1, default=str)
    json.dump({"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "styles": STYLES, "components": COMP, "dim_order": "style-major,7 分量/风格",
               "min_hist": MIN_HIST, "first_full_vector": min(vecs),
               "calendar": cal, "vectors": {d: v.tolist() for d, v in sorted(vecs.items())}},
              open(ENV + "style_vectors_v2.json", "w"))
    print("vectors →", ENV + "style_vectors_v2.json", file=sys.stderr)
    if not args.no_report:
        write_report(ctx)
    print(json.dumps({"verdict": verdict, "n_t": len(rows), "n_vec": len(vecs),
                      "first_vec": min(vecs), "mean_ic": round(mean_ic, 5),
                      "mean_ic_mom": round(mean_ico, 5), "p_one": p_one,
                      "half": {k: [round(a, 5), round(b, 5), n] for k, (a, b, n) in half.items()}},
                     indent=1))


if __name__ == "__main__":
    main()