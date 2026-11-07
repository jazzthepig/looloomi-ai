#!/usr/bin/env python3
"""T-299 / S-779 — S-775 的反射对照(R1:邻居 7 日动量减自己 ⇒ 之后 7 天)在 2020–2022 留出段的复验。

预注册:REFUTATION_LEDGER.md §S-779(Seth,2026-11-07 17:36 UTC)。报告 docs/research/T-299_leadlag_holdout.md
开头照抄预注册原文。本脚本只算、不改生产代码、不入库。

口径(全部照预注册,一字不改):
  每周一 t,2020-01-06 → 2022-12-26。
  宇宙 U_t = 当天 perp_bv_daily 有 USDT 永续收盘、上市 ≥ 90 天、7 日均成交额 ≥ 200 万美元、
             且 perp_bv_pairs 里 kind = 'coin' 或(kind 为空且 dead_from 非空 —— 含死币)的合约。
  场 W_t = S-775 原样:每个币 (t−89 … t] 的 USDT 永续日对数收益(相邻可得收盘)去均值,
             ≥ 60 个观测;build_similarity_graph(k=10, min_sim=0.10) → propagate(α=0.5)。
  s = 7 日相对 BTC 对数收益(log(c_t/c_{t−7}) − 同口径 BTC)的当天截面百分位居中(2q−1)。
  e = p − s。
  x7  = d+1 开盘 → d+7 收盘,减当天宇宙等权(期间停更取最后收盘);x30 同口径到 d+30。

判(照预注册):mean IC(e, x7) > 0 ∧ NW t(滞后 1) ≥ 2 ∧ 2020–21 / 2022 两段同号为正
             ∧ 周内打乱 1,000 次(种子 779)分位 ≥ 0.95。
只报:x30;IC(s) 单独;按市值三档;成本粗估(周换手 × 每边 0.1%)。

零分布 / 打乱 / 分位 / 盈亏 / NW t 一律走 src/data/evaluation/apparatus.py。
跑法:python3 docs/research/t299_leadlag.py
输入:T299_CACHE(默认 /Volumes/CometCloudAI/cometcloud-local/research/_cache/t299)下
      perp_bv_early.jsonl / pairs.json / mcap.jsonl(拉取脚本 docs/research/t299_pull.py)。
输出:docs/research/t299_results.json
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np
from scipy.stats import rankdata, spearmanr

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from src.data.evaluation.apparatus import (  # noqa: E402
    long_return,
    newey_west_t,
    null_distribution,
    percentile_of,
    short_return,
    shuffle_within,
)
from src.data.vector.propagation import (  # noqa: E402
    build_similarity_graph,
    entanglement_delta,
    propagate,
)

CACHE = os.environ.get("T299_CACHE", "/Volumes/CometCloudAI/cometcloud-local/research/_cache/t299")
OUT_JSON = os.path.join(REPO, "docs", "research", "t299_results.json")

FIRST_MONDAY, LAST_MONDAY = "2020-01-06", "2022-12-26"
WIN, MIN_OBS = 90, 60
K, MIN_SIM, ALPHA = 10, 0.10, 0.5
MIN_FIELD = 20                       # S-775 实现里的下限(少于 20 个节点不成场)
SEED, N_SHUFFLE = 779, 1000
MIN_QV, MIN_LISTED_DAYS = 2_000_000.0, 90
QV_MIN_DAYS = 3                      # 7 日窗口里至少要有 3 天的成交额
# (键, 入场日偏移, 出场日偏移):x7/x30 是登记口径;x7_delay 是执行推迟一天(稳健性,非判据)
WINDOWS = (("x7", 1, 7), ("x30", 1, 30), ("x7_delay", 2, 9))
HALF_CUT = "2022-01-01"              # 2020–21 / 2022 两段
COST_ONE_WAY = 0.001                # 每边 0.1%
T0 = time.time()


def log(m):
    print("[%6.1fs] %s" % (time.time() - T0, m), flush=True)


def read_jsonl(path):
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                yield json.loads(ln)


def last_at(dates, series, target):
    """≤ target 的最后一个可得值(ISO 日期串可直接比大小)。"""
    i = bisect.bisect_right(dates, target)
    return series[dates[i - 1]] if i > 0 else None


def last_at2(dates, series, target):
    """(日期, 值):≤ target 的最后一个可得值。"""
    i = bisect.bisect_right(dates, target)
    return (dates[i - 1], series[dates[i - 1]]) if i > 0 else (None, None)


def mean_fin(x):
    v = np.asarray([a for a in x if a is not None and np.isfinite(a)], dtype=float)
    return float(v.mean()) if v.size else float("nan")


def sp(a, b):
    """Spearman IC;样本不足 / 常量 ⇒ NaN。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if int(ok.sum()) < 10:
        return float("nan")
    if np.nanstd(a[ok]) == 0 or np.nanstd(b[ok]) == 0:
        return float("nan")
    r = spearmanr(a[ok], b[ok]).statistic
    return float(r) if r == r else float("nan")


def nw(x, lags=1):
    t, _, _ = newey_west_t([v for v in x if v is not None and np.isfinite(v)], lags=lags)
    return float("nan") if t is None else float(t)


# ── 载入 ────────────────────────────────────────────────────────────────────
def load():
    best = {}
    n_rows = 0
    for r in read_jsonl(os.path.join(CACHE, "perp_bv_early.jsonl")):
        if not (r.get("pair") or "").endswith("USDT"):
            continue
        n_rows += 1
        k = (r["symbol"], r["d"])
        prev = best.get(k)
        if prev is None or (r.get("recorded_at") or "") > (prev.get("recorded_at") or ""):
            best[k] = r

    closes, opens, qv = defaultdict(dict), defaultdict(dict), defaultdict(dict)
    for (sym, d), r in best.items():
        c, o, q = r.get("c"), r.get("o"), r.get("qv")
        if c is not None and float(c) > 0:
            closes[sym][d] = float(c)
        if o is not None and float(o) > 0:
            opens[sym][d] = float(o)
        if q is not None:
            qv[sym][d] = float(q)

    pairs = json.load(open(os.path.join(CACHE, "pairs.json")))
    pinfo = {}
    for r in pairs:
        sym = r.get("symbol")
        if not sym:
            continue
        info = pinfo.setdefault(sym, {"coin_ish": False, "first_d": None})
        if r.get("kind") == "coin" or (r.get("kind") in (None, "") and r.get("dead_from")):
            info["coin_ish"] = True
        fd = r.get("first_d")
        if fd and (info["first_d"] is None or fd < info["first_d"]):
            info["first_d"] = fd

    mcap = {}
    for r in read_jsonl(os.path.join(CACHE, "mcap.jsonl")):
        v = r.get("mcap")
        if v is not None and float(v) > 0:
            mcap[(r["symbol"], r["d"])] = float(v)

    return closes, opens, qv, pinfo, mcap, n_rows


def daily_returns(closes):
    """每个币:相邻可得收盘之间的对数收益(键 = 后一个日期);缺日记 NaN。"""
    out = {}
    for sym, ser in closes.items():
        ds = sorted(ser)
        rr = {}
        for i in range(1, len(ds)):
            rr[ds[i]] = float(np.log(ser[ds[i]] / ser[ds[i - 1]]))
        out[sym] = rr
    return out


# ── 主循环 ──────────────────────────────────────────────────────────────────
def main():
    closes, opens, qv, pinfo, mcap, n_rows = load()
    rets = daily_returns(closes)
    cl_dates = {s: sorted(v) for s, v in closes.items()}
    log("perp rows=%d symbols=%d mcap keys=%d" % (n_rows, len(closes), len(mcap)))

    d0 = dt.date.fromisoformat(FIRST_MONDAY)
    d1 = dt.date.fromisoformat(LAST_MONDAY)
    mondays = []
    c = d0
    while c <= d1:
        if c.weekday() == 0:
            mondays.append(c.isoformat())
        c += dt.timedelta(days=1)
    log("mondays in window: %d" % len(mondays))

    weeks, skipped, raw_store = [], [], []
    for d in mondays:
        t = dt.date.fromisoformat(d)
        days = [(t - dt.timedelta(days=WIN - 1 - i)).isoformat() for i in range(WIN)]

        # ── 宇宙 U_d ────────────────────────────────────────────────────────
        U = []
        for sym, ser in closes.items():
            if d not in ser:
                continue
            info = pinfo.get(sym)
            if not info or not info["coin_ish"]:
                continue
            first = info["first_d"] or (cl_dates[sym][0] if cl_dates.get(sym) else None)
            if not first:
                continue
            if (t - dt.date.fromisoformat(first)).days < MIN_LISTED_DAYS:
                continue
            qser = qv.get(sym, {})
            wq = [qser[dd] for dd in days[-7:] if dd in qser]
            if len(wq) < QV_MIN_DAYS or float(np.mean(wq)) < MIN_QV:
                continue
            U.append(sym)

        # ── s:7 日相对 BTC 对数收益的截面百分位居中 ─────────────────────────
        btc_c = closes.get("BTC", {})
        btc_d = btc_c.get(d)
        btc_7 = last_at(cl_dates.get("BTC", []), btc_c, (t - dt.timedelta(days=7)).isoformat())
        rel = {}
        if btc_d and btc_7:
            btc_mom = float(np.log(btc_d / btc_7))
            for sym in U:
                c0 = closes[sym].get(d)
                c7 = last_at(cl_dates[sym], closes[sym], (t - dt.timedelta(days=7)).isoformat())
                if c0 and c7:
                    rel[sym] = float(np.log(c0 / c7)) - btc_mom
        if len(rel) < 10:
            skipped.append((d, "universe=%d rel=%d" % (len(U), len(rel))))
            continue
        syms_rel = sorted(rel)
        rk = rankdata([rel[s] for s in syms_rel], method="average")
        n = len(syms_rel)
        src = {s: 2.0 * ((rk[i] - 1.0) / max(1.0, n - 1.0)) - 1.0 for i, s in enumerate(syms_rel)}

        # ── 场:去均值收益余弦,kNN ───────────────────────────────────────────
        emb = {}
        for sym in U:
            rr = rets.get(sym, {})
            v = np.array([rr.get(dd, np.nan) for dd in days], dtype=float)
            if int(np.isfinite(v).sum()) < MIN_OBS:
                continue
            m = float(np.nanmean(v))
            emb[sym] = [float(x - m) if np.isfinite(x) else float("nan") for x in v]
        if len(emb) < MIN_FIELD:
            skipped.append((d, "universe=%d field=%d" % (len(U), len(emb))))
            continue
        g = build_similarity_graph(emb, k=K, min_sim=MIN_SIM)
        p_map = propagate(g, {s: src[s] for s in emb if s in src}, alpha=ALPHA)
        e_map = entanglement_delta(p_map, {s: src[s] for s in emb if s in src})

        # ── 前向收益 x7 / x30(减当天宇宙等权) ──────────────────────────────
        fwd = {}
        for sym in U:
            cs, os_ = closes[sym], opens.get(sym, {})
            row = {}
            for key, e_off, x_off in WINDOWS:
                dE = (t + dt.timedelta(days=e_off)).isoformat()
                dX = (t + dt.timedelta(days=x_off)).isoformat()
                e1 = os_.get(dE)
                if e1 is None:
                    e1 = cs.get(dE)
                if e1 is None:                   # 停更:取入场日之前最后一个收盘
                    e1 = last_at(cl_dates[sym], cs, dE)
                x = cs.get(dX)
                if x is None:                    # 期间停更:取最后一个收盘(≥ 入场日)
                    xd, xv = last_at2(cl_dates[sym], cs, dX)
                    x = xv if (xd is not None and xd >= dE) else None
                row[key] = (long_return(e1, x), x)
                row[key + "_entry"] = e1
            fwd[sym] = row

        def bench(key):
            vals = [fwd[s][key][0] for s in U if fwd[s][key][0] is not None]
            return float(np.mean(vals)) if vals else float("nan")

        b7, b30 = bench("x7"), bench("x30")
        b7d = bench("x7_delay")

        # ── 当周 IC(样本 = 场里有 s 且有 x7 的币) ──────────────────────────
        sample = [s for s in emb if s in e_map and s in src and fwd.get(s, {}).get("x7", (None,))[0] is not None]
        if len(sample) < 10:
            skipped.append((d, "universe=%d field=%d sample=%d" % (len(U), len(emb), len(sample))))
            continue
        e_l = [e_map[s] for s in sample]
        s_l = [src[s] for s in sample]
        x7_l = [fwd[s]["x7"][0] - b7 for s in sample]
        x30_l = [fwd[s]["x30"][0] - b30 for s in sample if fwd[s]["x30"][0] is not None]
        s30_l = [src[s] for s in sample if fwd[s]["x30"][0] is not None]
        x7d_l = [fwd[s]["x7_delay"][0] - b7d for s in sample if fwd[s]["x7_delay"][0] is not None]

        # 结构检查:e ≈ a·s + b?(S-778 在 2023–26 段查到 e ≈ −0.47·s)
        fit = np.polyfit(s_l, e_l, 1) if len(sample) >= 10 else (np.nan, np.nan)
        corr_es = float(np.corrcoef(s_l, e_l)[0, 1]) if len(sample) >= 10 else float("nan")

        # 市值三档(当天截面,按 asset_mcap_daily)
        tiers = {1: [], 2: [], 3: []}
        with_mc = [s for s in sample if (s, d) in mcap]
        if len(with_mc) >= 9:
            order = sorted(with_mc, key=lambda s: mcap[(s, d)])
            for i, s in enumerate(order):
                tier = min(3, i * 3 // len(order))
                tiers[tier + 1].append((s, mcap[(s, d)]))

        rec = {
            "d": d, "n_universe": len(U), "n_field": len(emb), "n_ic": len(sample),
            "n_rel": len(rel), "n_x7": int(sum(1 for s in U if fwd[s]["x7"][0] is not None)),
            "ic_e_x7": sp(e_l, x7_l), "ic_s_x7": sp(s_l, x7_l),
            "ic_e_x30": sp(e_l, x30_l) if len(x30_l) >= 10 else float("nan"),
            "ic_s_x30": sp(s_l, x30_l) if len(x30_l) >= 10 else float("nan"),
            "ic_e_x7_delay": sp(e_l, x7d_l) if len(x7d_l) >= 10 else float("nan"),
            "ic_s_x7_delay": sp(s_l, x7d_l) if len(x7d_l) >= 10 else float("nan"),
            "corr_e_s": corr_es, "slope_e_on_s": float(fit[0]), "intercept_e_on_s": float(fit[1]),
            "r2_e_on_s": float(corr_es ** 2) if corr_es == corr_es else float("nan"),
            "ic_e_x7_tier": {}, "tier_n": {},
        }
        for ti in (1, 2, 3):
            mem = tiers[ti]
            if len(mem) >= 5:
                ee = [e_map[s] for s, _ in mem]
                xx = [fwd[s]["x7"][0] - b7 for s, _ in mem]
                rec["ic_e_x7_tier"][str(ti)] = sp(ee, xx)
            rec["tier_n"][str(ti)] = len(mem)

        # 成本粗估:e 排序的顶/底五分位,多空各一半名义;周换手 × 每边 0.1%
        by_e = sorted(sample, key=lambda s: -e_map[s])
        k = max(1, len(by_e) // 5)
        long_leg, short_leg = by_e[:k], by_e[-k:]
        w = {}
        for s in long_leg:
            w[s] = 1.0 / (2.0 * len(long_leg))
        for s in short_leg:
            w[s] = -1.0 / (2.0 * len(short_leg))
        lg = [fwd[s]["x7"][0] for s in long_leg]
        sg = [short_return(fwd[s]["x7_entry"], fwd[s]["x7"][1]) for s in short_leg]
        rec["book"] = {
            "n_long": len(long_leg), "n_short": len(short_leg),
            "long_leg_mean": float(np.mean(lg)) if lg else float("nan"),
            "short_leg_mean": float(np.mean([x for x in sg if x is not None])) if sg else float("nan"),
            "long_leg_mean_s": float(np.mean([src[s] for s in long_leg])),
            "short_leg_mean_s": float(np.mean([src[s] for s in short_leg])),
            "weights": w,
        }
        # 形状诊断(机制检查,非登记判据):按 e 降序分五档的 x7 超额
        by_e5 = sorted(sample, key=lambda s: -e_map[s])
        buckets = []
        for b in range(5):
            mem = by_e5[b * len(by_e5) // 5:(b + 1) * len(by_e5) // 5]
            vals = [fwd[s]["x7"][0] - b7 for s in mem]
            buckets.append({"n": len(mem),
                            "mean": float(np.mean(vals)) if vals else float("nan"),
                            "median": float(np.median(vals)) if vals else float("nan"),
                            "min": float(np.min(vals)) if vals else float("nan"),
                            "max": float(np.max(vals)) if vals else float("nan"),
                            "mean_s": float(np.mean([src[s] for s in mem])) if mem else float("nan")})
        rec["buckets"] = buckets
        rec["n_entry_fallback"] = int(sum(1 for s in U
                                          if (t + dt.timedelta(days=1)).isoformat() not in opens.get(s, {})))
        rec["n_exit_fallback"] = int(sum(1 for s in U
                                         if (t + dt.timedelta(days=7)).isoformat() not in closes.get(s, {})))
        rec["book"]["spread_L_minus_S"] = (rec["book"]["long_leg_mean"] + rec["book"]["short_leg_mean"])   # L − S(S = 空头腿原始收益 = −short_leg_mean)
        rec["book"]["gross"] = 0.5 * rec["book"]["spread_L_minus_S"]   # 名义 gross=1:多空各半
        weeks.append(rec)
        raw_store.append((d, list(e_l), list(x7_l)))

        if len(weeks) % 20 == 1:
            log("week %d  %s  U=%d field=%d sample=%d ic_e_x7=%+.4f"
                % (len(weeks), d, len(U), len(emb), len(sample), rec["ic_e_x7"]))

    log("weeks used=%d skipped=%d" % (len(weeks), len(skipped)))

    # ── 汇总(只打印要报的格)────────────────────────────────────────────────
    def ser(key, weeks_=None):
        out = []
        for r in (weeks_ if weeks_ is not None else weeks):
            v = r.get(key)
            if v is not None and np.isfinite(v):
                out.append((r["d"], float(v)))
        return out

    def halves(pairs):
        a = [v for d, v in pairs if d < HALF_CUT]
        b = [v for d, v in pairs if d >= HALF_CUT]
        return mean_fin(a), mean_fin(b), len(a), len(b)

    e7 = ser("ic_e_x7")
    m_e = mean_fin([v for _, v in e7])
    t_e = nw([v for _, v in e7], 1)
    h1, h2, n1, n2 = halves(e7)

    # 周内打乱(种子 779,1,000 次):每周内打乱 e 的归属 → 重算每周 IC → 均值零分布
    def _shuffle_stat(rng):
        ics = []
        for _d, e_arr, x_arr in raw_store:
            e_arr = np.asarray(e_arr, dtype=float)
            groups = np.array([_d] * len(e_arr), dtype=object)
            es = np.asarray(shuffle_within(e_arr, groups, rng), dtype=float)
            ics.append(sp(es, np.asarray(x_arr, dtype=float)))
        return mean_fin(ics)

    try:
        null = null_distribution(_shuffle_stat, N_SHUFFLE, SEED, m_e)
        sh_pct = percentile_of(m_e, null)
        sh_null = {"mean": float(np.mean(null)), "std": float(np.std(null))}
    except Exception as exc:  # NoOpNull 等
        log("shuffle failed: %s" % exc)
        sh_pct, sh_null = None, None

    out = {
        "lineage": {
            "prereg": "REFUTATION_LEDGER.md §S-779 (Seth, 2026-11-07 17:36 UTC)",
            "window": [FIRST_MONDAY, LAST_MONDAY], "perp_rows": n_rows,
            "perp_symbols": len(closes), "n_weeks_used": len(weeks), "n_weeks_skipped": len(skipped),
            "first_week": weeks[0]["d"] if weeks else None, "last_week": weeks[-1]["d"] if weeks else None,
            "field": {"win_days": WIN, "min_obs": MIN_OBS, "k": K, "min_sim": MIN_SIM, "alpha": ALPHA},
            "universe": {"min_listed_days": MIN_LISTED_DAYS, "min_7d_qv_usd": MIN_QV},
            "skipped_reasons": skipped[:20],
        },
    }

    # 判定
    judgment = {
        "mean_ic_e_x7": m_e, "nw_t_e_x7_lag1": t_e, "n_weeks": len(e7),
        "half1_mean_ic_e_x7": h1, "half1_n": n1, "half2_mean_ic_e_x7": h2, "half2_n": n2,
        "halves_same_sign_positive": bool(h1 > 0 and h2 > 0),
        "shuffle_pct": sh_pct, "shuffle_null": sh_null,
        "shuffle_pass": bool(sh_pct is not None and sh_pct >= 0.95),
    }
    verdict = bool(m_e > 0 and t_e >= 2.0 and h1 > 0 and h2 > 0
                   and sh_pct is not None and sh_pct >= 0.95)
    judgment["verdict"] = "PASS" if verdict else "FAIL"
    out["judgment"] = judgment

    # 只报
    s7 = ser("ic_s_x7")
    e30 = ser("ic_e_x30")
    s30 = ser("ic_s_x30")
    out["report_only"] = {
        "ic_s_x7_mean": mean_fin([v for _, v in s7]), "ic_s_x7_nw_t_lag1": nw([v for _, v in s7], 1),
        "ic_e_x30_mean": mean_fin([v for _, v in e30]), "ic_e_x30_nw_t_lag1": nw([v for _, v in e30], 1),
        "ic_s_x30_mean": mean_fin([v for _, v in s30]), "ic_s_x30_nw_t_lag1": nw([v for _, v in s30], 1),
    }
    tiers = {}
    for ti in (1, 2, 3):
        pairs = [(r["d"], r["ic_e_x7_tier"][str(ti)]) for r in weeks
                 if str(ti) in r["ic_e_x7_tier"] and r["ic_e_x7_tier"][str(ti)] is not None
                 and np.isfinite(r["ic_e_x7_tier"][str(ti)])]
        tiers[str(ti)] = {"mean_ic_e_x7": mean_fin([v for _, v in pairs]),
                          "nw_t_lag1": nw([v for _, v in pairs], 1), "n": len(pairs),
                          "mean_n_members": float(np.mean([r["tier_n"][str(ti)] for r in weeks]))}
    out["report_only"]["mcap_terciles"] = tiers

    # 成本粗估:e 排序的顶/底五分位多空(名义各半)—— 周换手(单边)× 每边 0.1%
    turn, prev_w = [], {}
    for r in weeks:
        w = r["book"]["weights"]
        if prev_w:
            turn.append(0.5 * sum(abs(w.get(k, 0.0) - prev_w.get(k, 0.0))
                                   for k in set(w) | set(prev_w)))
        prev_w = w
    mean_turn = mean_fin(turn)
    gross_wk = mean_fin([r["book"]["gross"] for r in weeks])
    cost_wk = mean_turn * COST_ONE_WAY * 2 if mean_turn == mean_turn else float("nan")
    out["report_only"]["cost_estimate"] = {
        "book": "e 排序:多头顶五分之一 / 空头底五分之一,名义各半,美元中性",
        "mean_one_way_turnover_per_week": mean_turn,
        "annualized_turnover": mean_turn * 52 if mean_turn == mean_turn else float("nan"),
        "cost_per_week_2sides_0.1pct": cost_wk,
        "cost_annualized": cost_wk * 52 if cost_wk == cost_wk else float("nan"),
        "gross_weekly_mean": gross_wk, "gross_annualized": gross_wk * 52,
        "gross_weekly_median": float(np.median([r["book"]["gross"] for r in weeks])),
        "gross_weeks_positive_pct": float(np.mean([r["book"]["gross"] > 0 for r in weeks]) * 100.0),
        "long_leg_weekly_mean": mean_fin([r["book"]["long_leg_mean"] for r in weeks]),
        "short_leg_weekly_mean": mean_fin([r["book"]["short_leg_mean"] for r in weeks]),
        "spread_weekly_mean": mean_fin([r["book"]["spread_L_minus_S"] for r in weeks]),
        "spread_weekly_median": float(np.median([r["book"]["spread_L_minus_S"] for r in weeks])),
        "spread_weeks_positive_pct": float(np.mean([r["book"]["spread_L_minus_S"] > 0 for r in weeks]) * 100.0),
        "gross_minus_cost_annualized": (gross_wk - cost_wk) * 52 if cost_wk == cost_wk else float("nan"),
    }

    # 每周明细(可核)
    out["weekly"] = [{
        "d": r["d"], "n_universe": r["n_universe"], "n_field": r["n_field"], "n_ic": r["n_ic"],
        "ic_e_x7": r["ic_e_x7"], "ic_s_x7": r["ic_s_x7"], "ic_e_x30": r["ic_e_x30"],
        "ic_e_x7_delay": r["ic_e_x7_delay"],
        "corr_e_s": r["corr_e_s"], "slope_e_on_s": r["slope_e_on_s"],
        "book_gross": r["book"]["gross"],
    } for r in weeks]
    out["report_only"]["delay_execution"] = {
        "note": "同一信号晚一天执行(d+2 开盘 -> d+9 收盘);稳健性,非登记判据",
        "ic_e_x7_delay_mean": mean_fin([v for _, v in ser("ic_e_x7_delay")]),
        "ic_e_x7_delay_nw_t_lag1": nw([v for _, v in ser("ic_e_x7_delay")], 1),
        "ic_s_x7_delay_mean": mean_fin([v for _, v in ser("ic_s_x7_delay")]),
        "ic_s_x7_delay_nw_t_lag1": nw([v for _, v in ser("ic_s_x7_delay")], 1),
    }
    out["report_only"]["bucket_shape_e_desc"] = {
        "note": "按 e 降序五档(b1=e 最高档);mean/median 为跨周平均的 x7 超额;机制检查,非登记判据",
        "buckets": [{
            "bucket": b + 1,
            "mean_of_weekly_mean": mean_fin([r["buckets"][b]["mean"] for r in weeks]),
            "mean_of_weekly_median": mean_fin([r["buckets"][b]["median"] for r in weeks]),
            "mean_of_weekly_min": mean_fin([r["buckets"][b]["min"] for r in weeks]),
            "mean_of_weekly_max": mean_fin([r["buckets"][b]["max"] for r in weeks]),
            "mean_s": mean_fin([r["buckets"][b]["mean_s"] for r in weeks]),
            "mean_n": mean_fin([r["buckets"][b]["n"] for r in weeks]),
        } for b in range(5)],
        "n_entry_fallback_mean": mean_fin([r["n_entry_fallback"] for r in weeks]),
        "n_exit_fallback_mean": mean_fin([r["n_exit_fallback"] for r in weeks]),
    }
    out["report_only"]["ic_weekly_median"] = float(np.median([v for _, v in e7]))
    out["report_only"]["ic_weeks_positive_pct"] = float(np.mean([v > 0 for _, v in e7]) * 100.0)

    out["structure"] = {
        "mean_corr_e_s": mean_fin([v for _, v in ser("corr_e_s")]),
        "mean_slope_e_on_s": mean_fin([v for _, v in ser("slope_e_on_s")]),
        "mean_r2_e_on_s": mean_fin([v for _, v in ser("r2_e_on_s")]),
    }

    with open(OUT_JSON, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, default=float)
    log("wrote %s" % OUT_JSON)
    print(json.dumps({k: out[k] for k in ("judgment", "report_only", "structure")},
                     indent=1, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
