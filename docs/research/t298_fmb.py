#!/usr/bin/env python3
"""T-298 / S-778 — 控制住价格扩散(R1)之后,C1 / C3 的「因」扩散还剩不剩。

预注册:REFUTATION_LEDGER.md §S-778(Seth,2026-11-07 17:34 UTC)。报告 docs/research/T-298_diffusion_vs_price.md
开头照抄预注册原文。本脚本只算,不写库、不改生产代码。

口径(全部照预注册 + S-775):
  同一份数据(.t294_cache,S-775 拉过,不重拉)、同一个场(90 天去均值收益,k=10、min_sim=0.10、α=0.5)、
  同一批周一、x7。每周截面:x7 的截面秩 ~ e(R1) + e(C1) + e(C3) + s(R1) + s(C1) + s(C3)
  (全部换成当周截面秩、居中),OLS;取每周系数,Fama–MacBeth 均值与 NW t(滞后 1)。
  判(C1、C3 各自,BH 两条):系数均值 > 0、NW t ≥ 2、两半同号为正 ⇒ ✅。
  只报:同一回归在 x30 上;去掉 s 的版本;加 e(C2) 之后的系数。

样本:每周取「y 与所有回归元都有值」的交集(联合回归的横截面);秩在该交集内算(当周截面)。
稳健性:秩若各自在自己的覆盖面上先算再取交集,结论是否改变(rank_on_own)。

零分布 / 打乱 / 分位:src/data/evaluation/apparatus.py(shuffle_within / null_distribution / percentile_of)——
  每周内打乱 y(x7 的截面秩)的归属(组内打乱、组间不混),重跑每周 OLS,得到「Fama–MacBeth 系数均值」的零分布。
NW t:src/data/evaluation/apparatus.py 的 newey_west_t(11-07 Seth 收编;若还没落地则用
  src/research/narrative/activation_z_pit.nw_tstat,同式、同 Bartlett 权重)。

跑法:python3 docs/research/t298_fmb.py
输入:.t294_cache/{asset_flow,perp_bv}.jsonl
输出:docs/research/t298_results.json
"""
from __future__ import annotations

import datetime as dt
import json
import math
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

try:  # apparatus.newey_west_t(11-07 在排提交;没落地就用同式实现)
    from src.data.evaluation.apparatus import newey_west_t  # type: ignore

    NW_SRC = "apparatus.newey_west_t"
except Exception:  # pragma: no cover
    from src.research.narrative.activation_z_pit import nw_tstat  # type: ignore

    NW_SRC = "activation_z_pit.nw_tstat"

CACHE = os.path.join(REPO, ".t294_cache")
OUT_JSON = os.path.join(REPO, "docs", "research", "t298_results.json")

# 源:标签 → asset_flow_daily 的 q_ 列(居中百分位 2q−1);与 S-775 完全一致
SOURCES = [
    ("C1", "q_doi7"),
    ("C2", "q_taker7"),
    ("C3", "q_turn"),
    ("R1", "q_mom7"),
]
JUDGED = ["C1", "C3"]
WIN, MIN_OBS, K_MAIN, MIN_SIM, ALPHA = 90, 60, 10, 0.10, 0.5
FIRST_MONDAY = "2023-01-02"
CUT = "2024-10-01"          # 两半切点(同 S-775)
SEED = 778
N_SHUFFLE = int(os.environ.get("T298_N_SHUFFLE", "1000"))
MAX_WEEKS = int(os.environ.get("T298_MAX_WEEKS", "0"))   # 0 = 全量(调试用)
MIN_WEEK_N = 20
# 每个设定要跑零分布的回归元(apparatus.null_distribution 每次只吃一个标量统计量)
NULL_TERMS = {
    "main_x7": ["e(R1)", "e(C1)", "e(C3)"],
    "main_x30": ["e(C1)", "e(C3)"],
    "withc2_x7": ["e(C1)", "e(C2)", "e(C3)"],
}

# 回归设定:y + 回归元清单(只报预注册点名的三个版本 + 稳健性)
SPECS = {
    "main_x7": {"y": "x7", "terms": [("e", "R1"), ("e", "C1"), ("e", "C3"),
                                     ("s", "R1"), ("s", "C1"), ("s", "C3")]},
    "main_x30": {"y": "x30", "terms": [("e", "R1"), ("e", "C1"), ("e", "C3"),
                                       ("s", "R1"), ("s", "C1"), ("s", "C3")]},
    "nos_x7": {"y": "x7", "terms": [("e", "R1"), ("e", "C1"), ("e", "C3")]},
    "withc2_x7": {"y": "x7", "terms": [("e", "R1"), ("e", "C1"), ("e", "C2"), ("e", "C3"),
                                       ("s", "R1"), ("s", "C1"), ("s", "C2"), ("s", "C3")]},
}
T0 = time.time()


def log(msg):
    print("[%6.1fs] %s" % (time.time() - T0, msg), flush=True)


# ── 载入(与 S-775 同一个 cache,不重拉)──────────────────────────────────────
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
    best = {}
    for r in load_jsonl(os.path.join(CACHE, "perp_bv.jsonl")):
        key = (r["symbol"], r["d"])
        prev = best.get(key)
        if prev is None or (r.get("recorded_at") or "") > (prev.get("recorded_at") or ""):
            best[key] = r
    closes = defaultdict(dict)
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
            rr[ds[i]] = float(np.log(ser[ds[i]] / ser[ds[i - 1]]))
        out[sym] = rr
    return out


# ── 统计小工具 ──────────────────────────────────────────────────────────────
def rank_center(vals):
    """当周截面秩(平均秩)并居中。"""
    a = np.asarray(vals, dtype=float)
    r = rankdata(a)
    return r - r.mean()


def mean_fin(x):
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    return float(x.mean()) if x.size else float("nan")


def nw_t(x, lags=1):
    a = [v for v in x if v is not None and np.isfinite(v)]
    if len(a) < lags + 2:
        return float("nan")
    if NW_SRC == "apparatus.newey_west_t":
        t, _, _ = newey_west_t(a, lags=lags)
        return float(t) if t is not None else float("nan")
    t, _ = nw_tstat(np.asarray(a, dtype=float), lags=lags)
    return float(t)


def p_two_sided(t):
    if t is None or not np.isfinite(t):
        return float("nan")
    return float(math.erfc(abs(t) / math.sqrt(2.0)))


def bh(pvals, alpha=0.05):
    """Benjamini–Hochberg:返回 (是否通过, 阈值, 校正后 q)。"""
    m = len(pvals)
    order = sorted((p, i) for i, p in enumerate(pvals) if p is not None and np.isfinite(p))
    passed = [False] * m
    thr = [float("nan")] * m
    q = [float("nan")] * m
    k = 0
    for rank, (p, i) in enumerate(order, start=1):
        if p <= alpha * rank / m:
            k = rank
    for rank, (p, i) in enumerate(order, start=1):
        thr[i] = alpha * rank / m
        passed[i] = rank <= k
        q[i] = min(1.0, p * m / rank)
    return passed, thr, q


# ── 每周一週的回归 ──────────────────────────────────────────────────────────
def fit_week(rec, spec, rank_on_own=False):
    """一周的截面 OLS:y 的截面秩 ~ 各回归元的截面秩(居中)。返回 None 当样本太小。"""
    y_map = rec.get(spec["y"], {})
    term_maps = [rec[kind].get(label, {}) for kind, label in spec["terms"]]
    common = set(y_map)
    for m in term_maps:
        common &= set(m)
    common = sorted(common)
    if len(common) < MIN_WEEK_N:
        return None
    y = rank_center([y_map[s] for s in common])
    X = np.column_stack([rank_center([m[s] for s in common]) for m in term_maps])
    if rank_on_own:
        # 稳健性:秩在各自的覆盖面上先算,再取交集
        cols = []
        for m in term_maps:
            own = sorted(m)
            cols.append(dict(zip(own, rank_center([m[s] for s in own]))))
        X = np.column_stack([np.array([cols[j][s] for s in common]) for j in range(len(cols))])
        X = X - X.mean(axis=0)
    beta, _, rank_x, sv = np.linalg.lstsq(X, y, rcond=None)
    cond = float(sv[0] / sv[-1]) if len(sv) and sv[-1] > 0 else float("inf")
    return {
        "d": rec["d"], "n": len(common), "beta": beta, "X": X, "y": y,
        "P": np.linalg.pinv(X), "cond": cond,
        "grp": np.array([rec["d"]] * len(common), dtype=object),
    }


def fmb(week_fits, spec):
    """Fama–MacBeth:每周系数 → 均值 / NW t(lag 1) / 两半。"""
    out = {}
    n_terms = len(spec["terms"])
    for j, (kind, label) in enumerate(spec["terms"]):
        name = "%s(%s)" % (kind, label)
        pairs = [(w["d"], float(w["beta"][j])) for w in week_fits]
        vals = [v for _, v in pairs]
        h1 = [v for d, v in pairs if d < CUT]
        h2 = [v for d, v in pairs if d >= CUT]
        out[name] = {
            "n_weeks": len(vals),
            "mean_coef": mean_fin(vals),
            "nw_t_lag1": nw_t(vals, 1),
            "p_two_sided_nw": p_two_sided(nw_t(vals, 1)),
            "half1_mean": mean_fin(h1), "half1_n": len(h1),
            "half2_mean": mean_fin(h2), "half2_n": len(h2),
            "weekly": pairs,
        }
    return out


def permutation_null(week_fits, spec, terms_wanted):
    """零分布:每周内打乱 y 的归属 → 重跑每周 OLS → 每周系数均值。返回 {term: {perm_p, null_mean, null_std}}。"""
    if not week_fits:
        return {}
    names = ["%s(%s)" % (k, l) for k, l in spec["terms"]]
    idx = {n: j for j, n in enumerate(names)}
    res = {}
    for name in terms_wanted:
        if name not in idx:
            continue
        j = idx[name]

        def fn(rng, j=j):
            betas = []
            for w in week_fits:
                yp = np.asarray(shuffle_within(w["y"], w["grp"], rng), dtype=float)
                betas.append(w["P"] @ yp)
            B = np.vstack(betas)
            return float(np.mean(B[:, j]))

        actual = float(np.mean([w["beta"][j] for w in week_fits]))
        try:
            nulls = null_distribution(fn, N_SHUFFLE, SEED, actual)
        except Exception as e:  # NoOpNull 等
            log("null failed %s/%s: %s" % (name, spec.get("y"), e))
            continue
        col = np.asarray(nulls, dtype=float)
        col = col[np.isfinite(col)]
        pct = percentile_of(actual, col)
        res[name] = {
            "perm_p_one_sided": None if pct is None else float(max(0.0, 1.0 - pct)),
            "perm_pct": pct,
            "null_mean": float(np.mean(col)), "null_std": float(np.std(col)),
            "actual": actual,
        }
    return res


def diag_corr(week_fits, spec):
    """诊断:回归元之间的平均截面相关(均值池化),看 e(C1) 与 e(R1) 是否高度共线。"""
    names = ["%s(%s)" % (k, l) for k, l in spec["terms"]]
    pairs = ["%s~%s" % (names[a], names[b])
             for a in range(len(names)) for b in range(a + 1, len(names))]
    acc = {p: [] for p in pairs}
    for w in week_fits:
        X = w["X"]
        C = np.corrcoef(X, rowvar=False)
        for a in range(len(names)):
            for b in range(a + 1, len(names)):
                acc["%s~%s" % (names[a], names[b])].append(float(C[a, b]))
    return {k: mean_fin(v) for k, v in acc.items()}


def main():
    af, closes = load()
    rets = daily_returns(closes)
    log("loaded af=%d rows, perp symbols=%d" % (len(af), len(closes)))

    by_day = defaultdict(list)
    for (sym, d) in af:
        by_day[d].append(sym)
    mondays = sorted(d for d in by_day
                     if dt.date.fromisoformat(d).weekday() == 0 and d >= FIRST_MONDAY)
    weeks = []
    for d in mondays:
        syms = sorted(by_day[d])
        u_t = [s for s in syms if af[(s, d)].get("vec") is not None]
        x7n = sum(1 for s in syms if af[(s, d)].get("x7") is not None)
        weeks.append((d, syms, u_t, x7n))
    last_ok = None
    for d, syms, u_t, x7n in weeks:
        if syms and x7n / len(syms) >= 0.5:
            last_ok = d
    weeks = [w for w in weeks if w[0] <= (last_ok or weeks[-1][0])]
    if MAX_WEEKS:
        weeks = weeks[:MAX_WEEKS]
    log("study weeks: %d (%s .. %s)" % (len(weeks), weeks[0][0], weeks[-1][0]))

    store = []
    for wi, (d, syms, u_t, x7n) in enumerate(weeks):
        t = dt.date.fromisoformat(d)
        days = [(t - dt.timedelta(days=WIN - 1 - i)).isoformat() for i in range(WIN)]
        emb = {}
        for s in u_t:
            rr = rets.get(s, {})
            v = np.array([rr.get(dd, np.nan) for dd in days], dtype=float)
            if int(np.isfinite(v).sum()) < MIN_OBS:
                continue
            m = float(np.nanmean(v))
            emb[s] = [float(x - m) if np.isfinite(x) else float("nan") for x in v]
        if len(emb) < 20:
            continue
        g20 = build_similarity_graph(emb, k=20, min_sim=MIN_SIM)
        gk = {nd: nbrs[:K_MAIN] for nd, nbrs in g20.items()}
        rec = {"d": d, "n_field": len(emb), "e": {}, "s": {}, "x7": {}, "x30": {}, "lvl": {}}
        degs = [len(v) for v in gk.values()]
        shares = []
        for nd, nbrs in gk.items():
            tot = sum(w for _, w in nbrs)
            if tot > 0:
                shares.append(max(w for _, w in nbrs) / tot)
        rec["graph"] = {"mean_degree": float(np.mean(degs)) if degs else float("nan"),
                        "mean_top1_weight_share": float(np.mean(shares)) if shares else float("nan")}
        for label, qcol in SOURCES:
            src = {}
            for s in emb:
                q = af[(s, d)].get(qcol)
                if q is None:
                    continue
                src[s] = 2.0 * float(q) - 1.0
            if len(src) < 10:
                continue
            p = propagate(gk, src, alpha=ALPHA)
            e = entanglement_delta(p, src)
            rec["e"][label] = {s: float(v) for s, v in e.items()}
            rec["s"][label] = {s: float(v) for s, v in src.items()}
            # 水平诊断:e 与 s 是不是同一个东西的反面?(秩相关之外要看水平)
            syms_l = sorted(rec["e"][label])
            ev = np.array([rec["e"][label][s] for s in syms_l])
            sv = np.array([rec["s"][label][s] for s in syms_l])
            pv = np.array([p.get(s, np.nan) for s in syms_l])
            ok = np.isfinite(ev) & np.isfinite(sv)
            if int(ok.sum()) >= 20:
                e_, s_ = ev[ok], sv[ok]
                cs = (float(np.corrcoef(e_, s_)[0, 1])
                      if e_.std() > 0 and s_.std() > 0 else float("nan"))
                slope = (float(np.polyfit(s_, e_, 1)[0]) if s_.std() > 0 else float("nan"))
                rec["lvl"][label] = {
                    "corr_e_s_level": cs, "slope_e_on_s": slope,
                    "r2_e_on_s": (cs * cs if np.isfinite(cs) else float("nan")),
                    "std_e": float(e_.std()), "std_s": float(s_.std()),
                    "std_p": float(np.nanstd(pv)), "mean_p": float(np.nanmean(pv)),
                    "n": int(ok.sum()),
                }
        for s in emb:
            r = af.get((s, d))
            if not r:
                continue
            if r.get("x7") is not None:
                rec["x7"][s] = float(r["x7"])
            if r.get("x30") is not None:
                rec["x30"][s] = float(r["x30"])
        store.append(rec)
        if wi % 40 == 0:
            log("week %d/%d %s field=%d" % (wi, len(weeks), d, len(emb)))
    log("weeks kept: %d" % len(store))

    results = {}
    for name, spec in SPECS.items():
        fits = [f for f in (fit_week(r, spec) for r in store) if f is not None]
        log("spec %s: %d weeks fitted (of %d)" % (name, len(fits), len(store)))
        summ = fmb(fits, spec)
        results[name] = {
            "y": spec["y"],
            "terms": [("%s(%s)" % (k, l)) for k, l in spec["terms"]],
            "n_weeks": len(fits),
            "median_week_n": float(np.median([w["n"] for w in fits])) if fits else float("nan"),
            "mean_week_n": float(np.mean([w["n"] for w in fits])) if fits else float("nan"),
            "mean_cond": mean_fin([w["cond"] for w in fits]),
            "coefs": summ,
        }
        if name in NULL_TERMS:
            log("null %s ..." % name)
            results[name]["null"] = permutation_null(fits, spec, NULL_TERMS[name])
        results[name]["diag_corr"] = diag_corr(fits, spec)
        if name == "main_x7":
            log("robustness rank_on_own ...")
            fits2 = [f for f in (fit_week(r, spec, rank_on_own=True) for r in store) if f is not None]
            results[name]["robust_rank_on_own"] = fmb(fits2, spec)
            results[name]["robust_rank_on_own"]["n_weeks"] = len(fits2)

    # ── 判定(C1、C3 各自;BH 两条)────────────────────────────────────────────
    main = results["main_x7"]["coefs"]
    nullmain = results["main_x7"].get("null", {})
    p_perm = [nullmain.get("e(%s)" % l, {}).get("perm_p_one_sided") for l in JUDGED]
    p_nw = [main["e(%s)" % l]["p_two_sided_nw"] for l in JUDGED]
    pass_perm, thr_perm, q_perm = bh(p_perm, 0.05)
    pass_nw, thr_nw, q_nw = bh(p_nw, 0.05)

    verdicts = {}
    for i, label in enumerate(JUDGED):
        c = main["e(%s)" % label]
        gates = {
            "mean_gt0": bool(np.isfinite(c["mean_coef"]) and c["mean_coef"] > 0),
            "nw_t_ge2": bool(np.isfinite(c["nw_t_lag1"]) and c["nw_t_lag1"] >= 2.0),
            "halves_both_positive": bool(np.isfinite(c["half1_mean"]) and c["half1_mean"] > 0
                                         and np.isfinite(c["half2_mean"]) and c["half2_mean"] > 0),
            "bh_perm_pass": bool(pass_perm[i]),
            "bh_nw_pass": bool(pass_nw[i]),
        }
        gates["verdict_prereg"] = "✅" if (gates["mean_gt0"] and gates["nw_t_ge2"]
                                          and gates["halves_both_positive"]
                                          and gates["bh_perm_pass"]) else "❌"
        gates["verdict_prereg_no_bh"] = "✅" if (gates["mean_gt0"] and gates["nw_t_ge2"]
                                                  and gates["halves_both_positive"]) else "❌"
        gates["p_perm_one_sided"] = p_perm[i]
        gates["p_nw_two_sided"] = p_nw[i]
        gates["q_perm_bh"] = q_perm[i]
        gates["q_nw_bh"] = q_nw[i]
        gates["bh_threshold_perm"] = thr_perm[i]
        verdicts[label] = gates

    out = {
        "task": "T-298", "prereg": "S-778",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level_diag": {
            "per_source": {
                lbl: {
                    "mean_corr_e_s_level": mean_fin([r["lvl"][lbl]["corr_e_s_level"]
                                                     for r in store if lbl in r.get("lvl", {})]),
                    "mean_slope_e_on_s": mean_fin([r["lvl"][lbl]["slope_e_on_s"]
                                                  for r in store if lbl in r.get("lvl", {})]),
                    "mean_r2_e_on_s": mean_fin([r["lvl"][lbl]["r2_e_on_s"]
                                                for r in store if lbl in r.get("lvl", {})]),
                    "mean_std_e": mean_fin([r["lvl"][lbl]["std_e"]
                                            for r in store if lbl in r.get("lvl", {})]),
                    "mean_std_s": mean_fin([r["lvl"][lbl]["std_s"]
                                            for r in store if lbl in r.get("lvl", {})]),
                    "mean_std_p": mean_fin([r["lvl"][lbl]["std_p"]
                                            for r in store if lbl in r.get("lvl", {})]),
                    "mean_p_over_s": mean_fin([r["lvl"][lbl]["std_p"] / r["lvl"][lbl]["std_s"]
                                               for r in store if lbl in r.get("lvl", {})
                                               and r["lvl"][lbl]["std_s"] > 0]),
                    "mean_mean_p": mean_fin([r["lvl"][lbl]["mean_p"]
                                             for r in store if lbl in r.get("lvl", {})]),
                }
                for lbl, _ in SOURCES
            },
            "graph": {
                "mean_degree": mean_fin([r["graph"]["mean_degree"] for r in store]),
                "mean_top1_weight_share": mean_fin([r["graph"]["mean_top1_weight_share"]
                                                    for r in store]),
            },
        },
        "config": {
            "k_main": K_MAIN, "min_sim": MIN_SIM, "alpha": ALPHA, "window_days": WIN,
            "min_obs": MIN_OBS, "cut": CUT, "seed": SEED, "n_shuffle": N_SHUFFLE,
            "nw_source": NW_SRC, "sources": dict(SOURCES),
            "rank_convention": "当周截面平均秩,居中;样本 = y 与所有回归元有值的交集",
        },
        "weeks_total": len(store),
        "week_range": [store[0]["d"], store[-1]["d"]] if store else None,
        "specs": results,
        "verdict": verdicts,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=1, default=str)
    log("wrote %s" % OUT_JSON)

    # ── 只打印要报的格 ───────────────────────────────────────────────────────
    for name in ("main_x7", "main_x30", "nos_x7", "withc2_x7"):
        r = results[name]
        print("\n[%s] y=%s weeks=%d median_n=%.0f mean_cond=%.1f"
              % (name, r["y"], r["n_weeks"], r["median_week_n"], r["mean_cond"]))
        for tname, c in r["coefs"].items():
            nl = r.get("null", {}).get(tname)
            print("  %-10s mean=%+.5f nw_t=%+.2f h1=%+.5f(%d) h2=%+.5f(%d)%s"
                  % (tname, c["mean_coef"], c["nw_t_lag1"], c["half1_mean"], c["half1_n"],
                     c["half2_mean"], c["half2_n"],
                     ("  perm_p=%.4f null=%.5f±%.5f" % (nl["perm_p_one_sided"], nl["null_mean"],
                                                        nl["null_std"])) if nl else ""))
    print("\n[verdict] ")
    for label in JUDGED:
        v = verdicts[label]
        print("  %s: mean>0=%s nw>=2=%s halves=%s bh_perm=%s bh_nw=%s ⇒ %s (prereg_no_bh=%s)"
              % (label, v["mean_gt0"], v["nw_t_ge2"], v["halves_both_positive"],
                 v["bh_perm_pass"], v["bh_nw_pass"], v["verdict_prereg"], v["verdict_prereg_no_bh"]))
    print("\n[diag corr main_x7] " + "  ".join(
        "%s=%.3f" % (k, v) for k, v in results["main_x7"]["diag_corr"].items()
        if k in ("e(C1)~s(C1)", "e(C3)~s(C3)", "e(R1)~e(C1)", "e(R1)~e(C3)",
                 "e(C1)~e(C3)", "s(C1)~s(C3)")))
    print("\n[level diag] graph: mean_degree=%.1f mean_top1_weight_share=%.3f"
          % (out["level_diag"]["graph"]["mean_degree"],
             out["level_diag"]["graph"]["mean_top1_weight_share"]))
    for lbl, _ in SOURCES:
        d = out["level_diag"]["per_source"][lbl]
        print("  %s: corr(e,s)=%.3f slope(e~s)=%.3f R2=%.3f std_e=%.4f std_s=%.4f "
              "std_p=%.4f mean_p=%.4f std(p)/std(s)=%.3f"
              % (lbl, d["mean_corr_e_s_level"], d["mean_slope_e_on_s"], d["mean_r2_e_on_s"],
                 d["mean_std_e"], d["mean_std_s"], d["mean_std_p"], d["mean_mean_p"],
                 d["mean_p_over_s"]))
    rr = results["main_x7"].get("robust_rank_on_own")
    if rr:
        print("\n[robust rank_on_own] weeks=%d" % rr["n_weeks"])
        for tname in ("e(C1)", "e(C3)"):
            c = rr[tname]
            print("  %-8s mean=%+.5f nw_t=%+.2f h1=%+.5f h2=%+.5f"
                  % (tname, c["mean_coef"], c["nw_t_lag1"], c["half1_mean"], c["half2_mean"]))


if __name__ == "__main__":
    main()
