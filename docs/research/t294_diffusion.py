#!/usr/bin/env python3
"""T-294 / S-775 — 扩散「因」:按币资金流的邻域扩散(S-81 的正确形态第一次可测).

预注册:REFUTATION_LEDGER.md §S-775(Seth,2026-11-07 13:23 UTC)。报告 docs/research/T-294_flow_diffusion.md
开头照抄预注册原文。本脚本只算,不写库、不改生产代码。

口径(全部照预注册):
  每周一 t(2023-01 第一个周一 → x7 已到期的最后一个周一)。
  宇宙 U_t = 当天 asset_flow_daily 有 vec 的币;场宇宙 F_t = U_t ∩ (t−90, t] 的 perp_bv_daily(USDT)日对数收益
  ≥ 60 个观测的币。
  场 W_t:build_similarity_graph(去均值收益向量, k=10, min_sim=0.10) —— 余弦即皮尔逊相关(NaN 感知)。
  源 s:当天截面的居中百分位 2q−1。e = p − s(p = propagate(α=0.5))。
  目标:x7(主, d+1 开盘 → d+7 收盘,减当天截面等权)、x30(副),取自 asset_flow_daily。

零分布 / 打乱 / 分位:src/data/evaluation/apparatus.py(shuffle_within / null_distribution / percentile_of)。
NW t:仓库既有实现 src/research/narrative/activation_z_pit.nw_tstat(Bartlett 权重)—— apparatus.py 目前没有
NW 函数,已请 @seth 收编(见最终回复),此处不另写一份。

跑法:python3 docs/research/t294_diffusion.py
输入:.t294_cache/{asset_flow,perp_bv}.jsonl(拉取脚本 docs/research/t294_pull.py)
输出:docs/research/t294_results.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np
from scipy.stats import rankdata

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from src.data.evaluation.apparatus import (  # noqa: E402
    null_distribution,
    percentile_of,
    shuffle_within,
)
from src.data.vector.propagation import (  # noqa: E402
    build_similarity_graph,
    entanglement_delta,
    propagate,
)
from src.research.narrative.activation_z_pit import nw_tstat  # noqa: E402

CACHE = os.path.join(REPO, ".t294_cache")
OUT_JSON = os.path.join(REPO, "docs", "research", "t294_results.json")

# 源:标签 → asset_flow_daily 的 q_ 列(居中百分位 2q−1)
SOURCES = [
    ("C1", "q_doi7"),
    ("C2", "q_taker7"),
    ("C3", "q_turn"),
    ("R1", "q_mom7"),
]
MAIN = ("C1", "C2", "C3")          # 判定对象(BH 三条);R1 是对照
WIN = 90                            # 场窗口 (t−90, t]
MIN_OBS = 60                        # ≥ 60 个与他币重叠的日子
K_MAIN, MIN_SIM, ALPHA = 10, 0.10, 0.5
K_SENS = (5, 20)
ALPHA_SENS = (0.3, 0.8)
SEED = 775
N_SHUFFLE = 1000
CUT = "2024-10-01"                  # 两半切点
FIRST_MONDAY = "2023-01-02"
T0 = time.time()


def log(msg):
    print("[%6.1fs] %s" % (time.time() - T0, msg), flush=True)


# ── 载入 ────────────────────────────────────────────────────────────────────
def load_jsonl(path):
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                yield json.loads(ln)


def load():
    af = {}
    for r in load_jsonl(os.path.join(CACHE, "asset_flow.jsonl")):
        af[(r["symbol"], r["d"])] = r
    closes = defaultdict(dict)
    best = {}
    for r in load_jsonl(os.path.join(CACHE, "perp_bv.jsonl")):
        key = (r["symbol"], r["d"])
        prev = best.get(key)
        if prev is None or (r.get("recorded_at") or "") > (prev.get("recorded_at") or ""):
            best[key] = r
    for (sym, d), r in best.items():
        c = r.get("c")
        if c and c > 0:
            closes[sym][d] = float(c)
    return af, closes


def daily_returns(closes):
    """每个币:日对数收益(相邻可得收盘),缺日记 NaN。"""
    out = {}
    for sym, ser in closes.items():
        ds = sorted(ser)
        rr = {}
        for i in range(1, len(ds)):
            d0, d1 = ds[i - 1], ds[i]
            rr[d1] = float(np.log(ser[d1] / ser[d0]))
        out[sym] = rr
    return out


# ── 统计小工具 ──────────────────────────────────────────────────────────────
def sp(a, b, min_n=10):
    """Spearman 秩相关 = 平均秩的 Pearson(与 scipy.spearmanr 同义,快 ~10 倍)。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if int(ok.sum()) < min_n:
        return float("nan")
    ra = rankdata(a[ok])
    rb = rankdata(b[ok])
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    r = float(np.corrcoef(ra, rb)[0, 1])
    return r if np.isfinite(r) else float("nan")


def mean_fin(x):
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    return float(x.mean()) if x.size else float("nan")


def nw(x, lags):
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    if x.size < 3:
        return float("nan")
    return float(nw_tstat(x, lags=lags)[0])


def shuffle_pct(raw_weeks, tgt_idx):
    """周内打乱 e 的归属(组内打乱,组间不混)→ 重算每周 IC → 零分布 → 实际值的分位。

    raw_weeks = [(d, e_list, x7_list, x30_list), …];tgt_idx 2=x7 / 3=x30。
    零分布与分位只用 apparatus.py(shuffle_within / null_distribution / percentile_of)。
    """
    raw = [w for w in raw_weeks if len(w[1]) >= 10]
    if len(raw) < 10:
        return None, None
    xs = [np.asarray(w[tgt_idx], dtype=float) for w in raw]
    actual = mean_fin([sp(w[1], w[tgt_idx]) for w in raw])

    def fn(rng):
        ics = []
        for w, x_arr in zip(raw, xs):
            e_arr = np.asarray(w[1], dtype=float)
            groups = np.array([w[0]] * len(e_arr), dtype=object)
            es = np.asarray(shuffle_within(e_arr, groups, rng), dtype=float)
            ics.append(sp(es, x_arr))
        return mean_fin(ics)

    try:
        null = null_distribution(fn, N_SHUFFLE, SEED, actual)
    except Exception as e:  # NoOpNull 等
        log("shuffle failed: %s" % e)
        return None, None
    return percentile_of(actual, null), (round(float(np.mean(null)), 6), round(float(np.std(null)), 6))


def bh(pvals, alpha=0.05):
    """Benjamini–Hochberg:返回每条假设的 BH 阈值与是否通过。"""
    items = [(p, i) for i, p in enumerate(pvals) if p is not None and np.isfinite(p)]
    m = len(pvals)
    order = sorted(items)
    passed = [False] * m
    thr = [float("nan")] * m
    k = 0
    for rank, (p, i) in enumerate(order, start=1):
        t = alpha * rank / m
        if p <= t:
            k = rank
    for rank, (p, i) in enumerate(order, start=1):
        thr[i] = alpha * rank / m
        passed[i] = rank <= k
    return passed, thr


# ── 主循环 ──────────────────────────────────────────────────────────────────
def main():
    af, closes = load()
    rets = daily_returns(closes)
    log("loaded af=%d rows, perp symbols=%d" % (len(af), len(closes)))

    by_day = defaultdict(list)
    for (sym, d), r in af.items():
        by_day[d].append(sym)

    mondays = sorted(d for d in by_day if dt.date.fromisoformat(d).weekday() == 0 and d >= FIRST_MONDAY)
    log("mondays with data: %d (%s .. %s)" % (len(mondays), mondays[0], mondays[-1]))

    weeks = []
    for d in mondays:
        syms = sorted(by_day[d])
        u_t = [s for s in syms if af[(s, d)].get("vec") is not None]
        x7n = sum(1 for s in syms if af[(s, d)].get("x7") is not None)
        weeks.append((d, syms, u_t, x7n))

    # x7 已到期的最后一个周一:该周一 ≥ 50% 宇宙有 x7
    last_ok = None
    for d, syms, u_t, x7n in weeks:
        if syms and x7n / len(syms) >= 0.5:
            last_ok = d
    weeks = [w for w in weeks if w[0] <= (last_ok or weeks[-1][0])]
    log("study weeks: %d (%s .. %s)" % (len(weeks), weeks[0][0], weeks[-1][0]))

    rows_out = []
    raw_store = {lbl: [] for lbl, _ in SOURCES}
    hand_checks = []

    for wi, (d, syms, u_t, x7n) in enumerate(weeks):
        t = dt.date.fromisoformat(d)
        days = [(t - dt.timedelta(days=WIN - 1 - i)).isoformat() for i in range(WIN)]
        # ── 场:F_t = U_t ∩ (≥60 个收益观测)
        emb = {}
        for s in u_t:
            rr = rets.get(s, {})
            v = np.array([rr.get(dd, np.nan) for dd in days], dtype=float)
            obs = int(np.isfinite(v).sum())
            if obs < MIN_OBS:
                continue
            m = float(np.nanmean(v))
            emb[s] = [float(x - m) if np.isfinite(x) else float("nan") for x in v]
        if len(emb) < 20:
            continue
        g20 = build_similarity_graph(emb, k=max(K_SENS), min_sim=MIN_SIM)
        gk = {k: {n: e[:k] for n, e in g20.items()} for k in (K_MAIN,) + K_SENS}
        # 资金面向量场(只报):11 维 vec 当日的余弦(节点集合与主场一致,只换边的定义)
        emb_v = {}
        for s in emb:
            raw = af[(s, d)].get("vec")
            if not raw:
                continue
            try:
                vals = json.loads(raw) if isinstance(raw, str) else list(raw)
            except Exception:
                continue
            vals = [float(x) if x is not None and np.isfinite(float(x)) else float("nan") for x in vals]
            if sum(1 for x in vals if np.isfinite(x)) >= 4:
                emb_v[s] = vals
        g_flow = build_similarity_graph(emb_v, k=K_MAIN, min_sim=MIN_SIM) if len(emb_v) >= 20 else None

        rec = {"d": d, "n_universe": len(u_t), "n_field": len(emb),
               "n_x7": x7n, "src": {}}
        for label, qcol in SOURCES:
            src = {}
            for s in emb:
                q = af[(s, d)].get(qcol)
                if q is None:
                    continue
                src[s] = 2.0 * float(q) - 1.0
            if len(src) < 10:
                rec["src"][label] = {"n_src": len(src)}
                continue
            tgt7 = [af[(s, d)].get("x7") for s in src]
            tgt30 = [af[(s, d)].get("x30") for s in src]
            syms_l = list(src.keys())

            p_main = propagate(gk[K_MAIN], src, alpha=ALPHA)
            e_main = entanglement_delta(p_main, src)
            s_l = [src[s] for s in syms_l]
            p_l = [p_main.get(s, np.nan) for s in syms_l]
            e_l = [e_main.get(s, np.nan) for s in syms_l]

            cell = {
                "n_src": len(src),
                "ic_e_x7": sp(e_l, tgt7),
                "ic_s_x7": sp(s_l, tgt7),
                "ic_p_x7": sp(p_l, tgt7),
                "ic_e_x30": sp(e_l, tgt30),
                "ic_s_x30": sp(s_l, tgt30),
                "ic_p_x30": sp(p_l, tgt30),
            }
            # 敏感度(只报)
            for k in K_SENS:
                pk = propagate(gk[k], src, alpha=ALPHA)
                ek = entanglement_delta(pk, src)
                cell["ic_e_x7_k%d" % k] = sp([ek.get(s, np.nan) for s in syms_l], tgt7)
            for al in ALPHA_SENS:
                pa = propagate(gk[K_MAIN], src, alpha=al)
                ea = entanglement_delta(pa, src)
                cell["ic_e_x7_a%.1f" % al] = sp([ea.get(s, np.nan) for s in syms_l], tgt7)
            if g_flow is not None:
                pf = propagate(g_flow, src, alpha=ALPHA)
                ef = entanglement_delta(pf, src)
                cell["ic_e_x7_flowfield"] = sp([ef.get(s, np.nan) for s in syms_l], tgt7)
            rec["src"][label] = cell
            raw_store[label].append((d, list(e_l), list(tgt7), list(tgt30)))

            # 手算对照(抽 3 个周一手算一个币的 p)
            if len(hand_checks) < 3 and wi % max(1, len(weeks) // 3) == 0 and src:
                pick = sorted(src)[len(src) // 2]
                hc = manual_p(pick, src, gk[K_MAIN], K_MAIN, ALPHA)
                hc["d"] = d
                hc["symbol"] = pick
                hc["p_propagate"] = p_main.get(pick)
                hc["abs_diff"] = abs(hc["p_manual"] - hc["p_propagate"])
                hand_checks.append(hc)
        rows_out.append(rec)
        if wi % 20 == 0:
            log("week %d/%d %s field=%d" % (wi, len(weeks), d, len(emb)))

    # ── 汇总 ────────────────────────────────────────────────────────────────
    def series(label, key, tgt="x7"):
        out = []
        for r in rows_out:
            c = r["src"].get(label)
            if not c:
                continue
            v = c.get("ic_e_%s" % tgt)
            if v is not None and np.isfinite(v):
                out.append((r["d"], float(v)))
        return out

    def series_key(label, key, tgt="x7"):
        out = []
        for r in rows_out:
            c = r["src"].get(label)
            if not c:
                continue
            v = c.get(key)
            if v is not None and np.isfinite(v):
                out.append((r["d"], float(v)))
        return out

    def halves(pairs):
        a = [v for d, v in pairs if d < CUT]
        b = [v for d, v in pairs if d >= CUT]
        return mean_fin(a), mean_fin(b), len(a), len(b)

    summary = {}
    for label, qcol in SOURCES:
        e7 = series(label, "ic_e_x7")
        e30 = series(label, "ic_e_x30")
        s7 = series_key(label, "ic_s_x7")
        p7 = series_key(label, "ic_p_x7")
        diff = []
        for r in rows_out:
            c = r["src"].get(label)
            if not c:
                continue
            a, b = c.get("ic_e_x7"), c.get("ic_s_x7")
            if a is not None and b is not None and np.isfinite(a) and np.isfinite(b):
                diff.append((r["d"], float(a - b)))
        m_e = mean_fin([v for _, v in e7])
        t_e = nw([v for _, v in e7], 1)
        m_s = mean_fin([v for _, v in s7])
        m_p = mean_fin([v for _, v in p7])
        m_d = mean_fin([v for _, v in diff])
        t_d = nw([v for _, v in diff], 1)
        h1 = halves(e7)
        h2 = halves(diff)

        # 周内打乱零分布(1000 次,种子 775):每周内打乱 e 的归属,重算每周 IC,取均值
        log("shuffle %s x7 ..." % label)
        pct7, null7 = shuffle_pct(raw_store[label], 2)
        log("shuffle %s x30 ..." % label)
        pct30, null30 = shuffle_pct(raw_store[label], 3)
        summary[label] = {
            "n_weeks": len(e7),
            "mean_ic_e_x7": m_e, "nw_t_e_x7_lag1": t_e,
            "mean_ic_s_x7": m_s, "mean_ic_p_x7": m_p,
            "mean_diff_e_minus_s_x7": m_d, "nw_t_diff_lag1": t_d,
            "half1_mean_ic_e_x7": h1[0], "half1_n": h1[2],
            "half2_mean_ic_e_x7": h2[0], "half2_n": h2[2],
            "half1_mean_diff": halves(diff)[0], "half2_mean_diff": halves(diff)[1],
            "mean_ic_e_x30": mean_fin([v for _, v in e30]),
            "nw_t_e_x30_lag4": nw([v for _, v in e30], 4),
            "mean_ic_s_x30": mean_fin([v for _, v in series_key(label, "ic_s_x30")]),
            "mean_diff_e_minus_s_x30": mean_fin(
                [r["src"][label]["ic_e_x30"] - r["src"][label]["ic_s_x30"]
                 for r in rows_out if label in r["src"]
                 and np.isfinite(r["src"][label].get("ic_e_x30", np.nan))
                 and np.isfinite(r["src"][label].get("ic_s_x30", np.nan))]),
            "sens_k5_mean_ic_e_x7": mean_fin([v for _, v in series_key(label, "ic_e_x7_k5")]),
            "sens_k20_mean_ic_e_x7": mean_fin([v for _, v in series_key(label, "ic_e_x7_k20")]),
            "sens_a03_mean_ic_e_x7": mean_fin([v for _, v in series_key(label, "ic_e_x7_a0.3")]),
            "sens_a08_mean_ic_e_x7": mean_fin([v for _, v in series_key(label, "ic_e_x7_a0.8")]),
            "sens_flowfield_mean_ic_e_x7": mean_fin([v for _, v in series_key(label, "ic_e_x7_flowfield")]),
            "shuffle_pct_x7": pct7,
            "shuffle_pct_x30": pct30,
            "shuffle_null_x7": null7,
            "shuffle_null_x30": null30,
        }

    # ── 判定(C1–C3 各自,BH 三条,主目标 x7)────────────────────────────────
    # BH 用周内打乱的单侧 p(= 1 − 分位)做 Benjamini–Hochberg 校正(3 条假设);
    # 其余三条判据是合取条件,全部满足才算 ✅。
    GATE_KEYS = ("ic_mean_gt0_and_nw_t_ge2", "halves_both_positive",
                 "shuffle_pct_ge_0.95", "diff_mean_gt0_and_nw_t_ge1.5")
    verdicts = {}
    ps = []
    for label in MAIN:
        s = summary[label]
        pct = s.get("shuffle_pct_x7")
        ps.append(None if pct is None else max(0.0, 1.0 - float(pct)))
    passed, thr = bh(ps, 0.05)
    for i, label in enumerate(MAIN):
        s = summary[label]
        gates = {
            "ic_mean_gt0_and_nw_t_ge2": bool(np.isfinite(s["mean_ic_e_x7"]) and s["mean_ic_e_x7"] > 0
                                             and np.isfinite(s["nw_t_e_x7_lag1"]) and s["nw_t_e_x7_lag1"] >= 2.0),
            "halves_both_positive": bool(np.isfinite(s["half1_mean_ic_e_x7"]) and s["half1_mean_ic_e_x7"] > 0
                                         and np.isfinite(s["half2_mean_ic_e_x7"]) and s["half2_mean_ic_e_x7"] > 0),
            "shuffle_pct_ge_0.95": bool(s.get("shuffle_pct_x7") is not None and s["shuffle_pct_x7"] >= 0.95),
            "diff_mean_gt0_and_nw_t_ge1.5": bool(np.isfinite(s["mean_diff_e_minus_s_x7"]) and s["mean_diff_e_minus_s_x7"] > 0
                                                 and np.isfinite(s["nw_t_diff_lag1"]) and s["nw_t_diff_lag1"] >= 1.5),
        }
        gates["bh_pass"] = bool(passed[i])
        gates["bh_threshold"] = float(thr[i])
        gates["p_shuffle_one_sided"] = ps[i]
        gates["verdict"] = "✅" if (all(gates[k] for k in GATE_KEYS) and passed[i]) else "❌"
        verdicts[label] = gates

    out = {
        "task": "T-294", "prereg": "S-775", "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "k_main": K_MAIN, "min_sim": MIN_SIM, "alpha": ALPHA, "window_days": WIN,
            "min_obs": MIN_OBS, "seeds": SEED, "n_shuffle": N_SHUFFLE, "cut": CUT,
            "sources": {lbl: q for lbl, q in SOURCES},
        },
        "weeks": len(rows_out),
        "week_range": [rows_out[0]["d"], rows_out[-1]["d"]] if rows_out else None,
        "summary": summary,
        "verdict_gates": verdicts,
        "manual_checks": hand_checks,
        "weekly": rows_out,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=1, default=str)
    log("wrote %s" % OUT_JSON)
    for label, _ in SOURCES:
        s = summary[label]
        print("%s n=%d ic_e=%.4f nw=%.2f ic_s=%.4f ic_p=%.4f diff=%.4f nw_d=%.2f h1=%.4f h2=%.4f"
              % (label, s["n_weeks"], s["mean_ic_e_x7"], s["nw_t_e_x7_lag1"], s["mean_ic_s_x7"], s["mean_ic_p_x7"],
                 s["mean_diff_e_minus_s_x7"], s["nw_t_diff_lag1"], s["half1_mean_ic_e_x7"], s["half2_mean_ic_e_x7"]))


def manual_p(node, src, graph, k, alpha):
    """手算 p:(1−α)s + αWp 迭代到收敛,与 propagate() 的输出对照。"""
    nodes = list(graph.keys())
    W = {}
    for nd in nodes:
        nbrs = graph.get(nd, [])[:k]
        tot = sum(w for _, w in nbrs)
        W[nd] = [(j, w / tot) for j, w in nbrs] if tot > 0 else []
    p = {nd: float(src.get(nd, 0.0)) for nd in nodes}
    for _ in range(400):
        new = {}
        for nd in nodes:
            acc = sum(w * p[j] for j, w in W[nd])
            new[nd] = (1 - alpha) * float(src.get(nd, 0.0)) + alpha * acc
        diff = max(abs(new[nd] - p[nd]) for nd in nodes)
        p = new
        if diff < 1e-12:
            break
    return {"p_manual": p.get(node), "s": src.get(node)}


if __name__ == "__main__":
    main()
