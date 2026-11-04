#!/usr/bin/env python3
"""T-236 走前参数选择(agent 调参的机械版):R-v2 的 {止损 k} × {出场 SMA} × {量能门 m} 27 组网格,
每月初只用「该日前已出场 + 开票日在过去 18 个月内」的票选一组,与固定 (2.5, 20, 2) 和
「每月均匀随机抽一组」的 1,000 条路径对比。

预注册(先写后算)见 docs/research/T-236_walk_forward_params.md 开头。纪律:不改代码、不做 DDL、不入库。
只读本地缓存:bars = research/t156/_bars{,_early}.jsonl + research/t159/_bars.jsonl;gate = research/t156/_style.json;
⓪ 相位 = research/t236/_cycle_vector.json(cycle_vector_daily 快照)。

用法: python3 docs/research/t236_walk_forward_params.py [--stage fixed|all] [--out PATH]
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("COMETCLOUD_LOCAL", "/Volumes/CometCloudAI/cometcloud-local")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)
if not hasattr(t159, "np"):
    t159.np = np

# ── 预注册常量 ────────────────────────────────────────────────────────────────
SIG_FROM, SIG_TO = "2020-03-01", "2026-10-19"     # 信号日窗(票生成)
SEL_FROM = "2022-01-01"                            # 选参起始月(按开票日分月)
CURVE_TO = "2026-10-19"                            # 钱曲线终点
FIXED = (2.5, 20, 2.0)                             # 固定对照组(S-610/S-620 定下的)
LOOKBACK_M = 18                                    # 候选池回看月数
MIN_TICKETS = 30                                   # 候选票数门槛(不足 ⇒ 退回固定)
KS = (2.0, 2.5, 3.0)
SMAS = (10, 20, 30)
MS = (1.5, 2.0, 3.0)
N_RANDOM = 1000
RANDOM_SEED = 236
COST = 0.004                                       # 来回成本(与 t159 逐字)
HALVES = [("2022-01-01", "2024-01-01"), ("2024-01-01", "2027-01-01")]


def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    return dt.date(y, m + 1, 1)


def month_iter(a: dt.date, b: dt.date):
    cur = a
    while cur < b:
        yield cur
        cur = add_months(cur, 1)


# ── 数据 ──────────────────────────────────────────────────────────────────────
def load_gate_and_maj():
    """t159.load_gate 的逐字复刻,外加「majors 在/不在 200 日线上」。"""
    rows = [x for x in json.load(open(f"{t159.T156}_style.json")) if x["ret"] is not None and x["ret"] > -0.95]
    rows.sort(key=lambda x: x["d"])
    lvl, cur = [], 1.0
    for x in rows:
        cur *= (1.0 + x["ret"])
        lvl.append(cur)
    g, maj = {}, {}
    for i, x in enumerate(rows):
        n = min(i + 1, 200)
        w = t159.win(lvl, i, 0, 199)
        g[x["d"]] = dict(n=n, lvl=lvl[i],
                         gate_open=bool(n < 200 or lvl[i] > w),
                         gate_closed=bool(n >= 200 and lvl[i] <= w))
        maj[x["d"]] = bool(w is not None and lvl[i] > w)
    return g, maj


def load_phase() -> dict[str, str]:
    """⓪ 相位:turning / normal;NA(缺值)按卡的口径归 normal。"""
    rows = json.load(open(os.path.join(ROOT, "research", "t236", "_cycle_vector.json")))["rows"]
    return {x["d"]: (x["phase"] or "normal") for x in rows}


def prep(bars: dict) -> dict:
    """indicators 算一次,27 组共用;补 sma10 / sma30。"""
    out = {}
    for s, rows in bars.items():
        a = t159.indicators(rows)
        c, n = a["c"], len(a["c"])
        a["sma10"] = [t159.win(c, i, 0, 9) or c[i] for i in range(n)]
        a["sma30"] = [t159.win(c, i, 0, 29) or c[i] for i in range(n)]
        out[s] = a
    return out


# ── 票生成(参数化;进场其余规则不动) ─────────────────────────────────────────
def _base_sig(a, i, gate, m) -> bool:
    """t159._universe + sig_long,只把量能门从 2 换成 m。"""
    if i < 220 or a["atr14"][i] is None or a["atr14"][i] <= 0:
        return False
    if a["adv30"][i] is None or a["adv30"][i] < 5e6:
        return False
    hh, ll = a["hh40"][i], a["ll40"][i]
    if hh is None or ll is None or hh == 0 or (hh - ll) / hh > 0.40:
        return False
    if a["adv40p"][i] is None or a["dv"][i] < m * a["adv40p"][i]:
        return False
    if a["mindd120"][i] is None or a["mindd120"][i] > 0.5:
        return False
    if not a["c"][i] > a["hh40"][i]:
        return False
    if a["sma200"][i] is None or not a["c"][i] > a["sma200"][i]:
        return False
    if not gate.get(a["d"][i], {}).get("gate_open", True):
        return False
    return True


def run_param(abar, gate, d_from, d_to, k: float, sma_x: int, m: float):
    """t159.run_long 的逐字移植,三处可调:止损 k、出场 SMA_x、量能门 m。"""
    tr = defaultdict(list)
    for sym, a in abar.items():
        n = len(a["d"])
        sma = a[f"sma{sma_x}"]
        for i in range(220, n):
            d = a["d"][i]
            if not (d_from <= d <= d_to):
                continue
            if not _base_sig(a, i, gate, m):
                continue
            ei = i + 1
            if ei >= n:
                continue
            entry, stop = a["o"][ei], a["o"][ei] - k * a["atr14"][i]
            if not (entry > stop):
                continue
            kk = None
            for j in range(ei, min(i + 120, n - 1) + 1):
                if a["l"][j] <= stop or a["c"][j] < sma[j]:
                    kk = j
                    break
            if kk is None:
                xi, xp, still = min(i + 120, n - 1), a["c"][min(i + 120, n - 1)], (i + 120 > n - 1)
            elif a["l"][kk] <= stop:
                xi, xp, still = kk, (a["o"][kk] if (kk > ei and a["o"][kk] <= stop) else stop), False
            elif kk + 1 <= n - 1:
                xi, xp, still = kk + 1, a["o"][kk + 1], False
            else:
                xi, xp, still = kk, a["c"][kk], True
            t = dict(symbol=sym, signal_d=d, entry_d=a["d"][ei], exit_d=None if still else a["d"][xi],
                     entry_px=entry, stop_px=stop, exit_px=None if still else xp, ei=ei, xi=xi,
                     bars_held=xi - ei + 1, still=still)
            t["r"] = None if still else ((xp - entry) / (entry - stop) - COST * entry / (entry - stop))
            tr[sym].append(t)
    return t159._chain(tr)


def mtm(tickets, bars):
    """s657.mtm 的逐字复刻:仍持有的票按最后收盘盯市。"""
    for t in tickets:
        if t.get("r") is None:
            last_c = bars[t["symbol"]][-1][4]
            t["r"] = (last_c - t["entry_px"]) / (t["entry_px"] - t["stop_px"]) - COST * t["entry_px"] / (
                t["entry_px"] - t["stop_px"])
            t["still"] = True
    return tickets


# ── 选择器 ────────────────────────────────────────────────────────────────────
def _cand(tk, s_iso: str, lo_iso: str):
    """该日前已出场 + 开票日在过去 18 个月内。"""
    return [t for t in tk if t["exit_d"] and t["exit_d"] < s_iso and t["entry_d"] >= lo_iso]


def select_group(tickets_by_group, s: dt.date, extra=None):
    """按候选票的 R 均值选一组;候选票数 < 30 的组不参选(小样本均值不参选);
    没有任何一组达标 ⇒ 返回 None,由调用方决定回退。

    extra: 额外的票过滤(选择器 B 的桶)。"""
    s_iso, lo_iso = s.isoformat(), add_months(s, -LOOKBACK_M).isoformat()
    best, best_mu, best_n = None, None, 0
    for g, tk in tickets_by_group.items():
        cand = [t for t in tk
                if t["exit_d"] and t["exit_d"] < s_iso and t["entry_d"] >= lo_iso
                and (extra is None or extra(t))]
        if len(cand) < MIN_TICKETS:
            continue
        mu = sum(t["r"] for t in cand) / len(cand)
        if best_mu is None or mu > best_mu:
            best, best_mu, best_n = g, mu, len(cand)
    if best is None:
        return None, None, 0
    return best, best_mu, best_n


def month_tickets(tickets_by_group, g, m_start: dt.date, m_end: dt.date):
    lo, hi = m_start.isoformat(), m_end.isoformat()
    return [t for t in tickets_by_group[g] if lo <= t["entry_d"] < hi]


def build_walkforward(tickets_by_group, bucket_key=None, a_choice=None):
    """走前选参 → 每月的票集合。

    bucket_key 为 None ⇒ 选择器 A(每月一组)。
    否则 ⇒ 选择器 B:四个桶(majors 在/不在 200 日线上 × ⓪ turning/normal)各自独立走前选,
    桶内候选 < 30 ⇒ 该桶退回 A 在当月的选择(a_choice)。"""
    months = list(month_iter(dt.date.fromisoformat(SEL_FROM), dt.date.fromisoformat(CURVE_TO)))
    picks = {}
    if bucket_key is None:
        for m in months:
            g, mu, n = select_group(tickets_by_group, m)
            picks[m] = dict(group=g if g is not None else FIXED, mu=mu, n=n, fallback=(g is None))
    else:
        buckets = sorted({bucket_key(t) for tk in tickets_by_group.values() for t in tk})
        for m in months:
            pb = {}
            for b in buckets:
                g, mu, n = select_group(tickets_by_group, m, extra=lambda t, b=b: bucket_key(t) == b)
                fb = g is None
                if fb:
                    g = a_choice.get(m, FIXED) if a_choice is not None else FIXED
                pb[b] = dict(group=g, mu=mu, n=n, fallback=fb)
            picks[m] = pb
    chosen = []
    for m in months:
        m_end = add_months(m, 1)
        if bucket_key is None:
            chosen += month_tickets(tickets_by_group, picks[m]["group"], m, m_end)
        else:
            for b, info in picks[m].items():
                chosen += [t for t in month_tickets(tickets_by_group, info["group"], m, m_end)
                           if bucket_key(t) == b]
    return chosen, picks


# ── 指标 ──────────────────────────────────────────────────────────────────────
def summarise(tickets, bars, d_from=SEL_FROM, d_to=CURVE_TO):
    tk = [t for t in tickets if d_from <= t["entry_d"] <= d_to]
    rs = [t["r"] for t in tk]
    curve = list(t159.nav(tk, bars, 0.01, cap=10, d_to=d_to))
    st = t159.stats(curve) if curve else None
    out = dict(n=len(rs), total_r=round(sum(rs), 4) if rs else 0.0,
               mean_r=round(sum(rs) / len(rs), 6) if rs else None,
               win=round(sum(r > 0 for r in rs) / len(rs), 4) if rs else None,
               still_open=sum(1 for t in tk if t.get("still")))
    if st:
        mdd = st["mdd"]
        out["nav"] = dict(end=round(st["end"], 6), annualised=st["annualised"], mdd=mdd,
                          calmar=(st["annualised"] / abs(mdd)) if (st["annualised"] and mdd) else None,
                          d0=st["d0"], d1=st["d1"], taken=st["taken"], skipped=st["skipped"],
                          closed=st["closed"])
    for label, (lo, hi) in zip(("h1_2022_23", "h2_2024_26"), HALVES):
        sub = [t for t in tk if lo <= t["entry_d"] < hi]
        sr = [t["r"] for t in sub]
        c2 = list(t159.nav(sub, bars, 0.01, cap=10, d_to=d_to)) if sub else []
        s2 = t159.stats(c2) if c2 else None
        h = dict(n=len(sr), total_r=round(sum(sr), 4) if sr else 0.0,
                 mean_r=round(sum(sr) / len(sr), 6) if sr else None)
        if s2:
            h["annualised"] = s2["annualised"]
            h["mdd"] = s2["mdd"]
            h["calmar"] = (s2["annualised"] / abs(s2["mdd"])) if (s2["annualised"] and s2["mdd"]) else None
        out[label] = h
    return out


def switches(picks):
    """A: 每月选了一组 → 相邻月换组次数 / 比例(比例 ≥ 0.5 说明选的是噪声)。"""
    ks = [picks[m]["group"] for m in sorted(picks)]
    sw = sum(1 for a, b in zip(ks, ks[1:]) if a != b)
    months = len(ks)
    return dict(n_months=months, switches=sw, switch_rate=round(sw / max(months - 1, 1), 4),
                noise_flag=bool(months > 1 and sw / max(months - 1, 1) >= 0.5),
                series=[f"{m.isoformat()}:{picks[m]['group']}" for m in sorted(picks)])


def switches_b(picks, buckets):
    """B: 每个桶各自按月的选择序列 → 切换次数;合计。"""
    out = {}
    tot_sw = tot_m = 0
    for b in buckets:
        ks = [picks[m][b]["group"] for m in sorted(picks)]
        sw = sum(1 for a, c in zip(ks, ks[1:]) if a != c)
        out[str(b)] = dict(n_months=len(ks), switches=sw, switch_rate=round(sw / max(len(ks) - 1, 1), 4),
                           fallback_months=sum(1 for m in picks if picks[m][b]["fallback"]))
        tot_sw += sw
        tot_m += max(len(ks) - 1, 0)
    out["total"] = dict(switches=tot_sw, month_pairs=tot_m,
                         switch_rate=round(tot_sw / max(tot_m, 1), 4),
                         noise_flag=bool(tot_m > 0 and tot_sw / tot_m >= 0.5))
    return out


def select_group2(groups, s, stat="mean", lb=LOOKBACK_M, min_t=MIN_TICKETS, extra=None):
    """探索性:可换统计量 / 回看窗口 / 票数门槛的选择器(主判定不用)。"""
    s_iso, lo_iso = s.isoformat(), add_months(s, -lb).isoformat()
    best, best_v, best_n = None, None, 0
    for g, tk in groups.items():
        cand = [t for t in tk
                if t["exit_d"] and t["exit_d"] < s_iso and t["entry_d"] >= lo_iso
                and (extra is None or extra(t))]
        if len(cand) < min_t:
            continue
        rs = sorted(t["r"] for t in cand)
        if stat == "mean":
            v = sum(rs) / len(rs)
        elif stat == "median":
            v = rs[len(rs) // 2]
        else:                                    # "sum":候选池总 R(目标函数 = 评价指标)
            v = sum(rs)
        if best_v is None or v > best_v:
            best, best_v, best_n = g, v, len(cand)
    return (None, None, 0) if best is None else (best, best_v, best_n)


def explore(groups, bars):
    """探索性:换统计量 / 回看窗口 / 门槛,以及『整段 in-sample 最优一组』对照。

    这些数字不参与预注册的判定,只用于诊断『为什么走前选参不如固定』。"""
    out = {}
    variants = {
        "base_mean_lb18_t30": ("mean", 18, 30),
        "median_lb18_t30": ("median", 18, 30),
        "mean_lb6_t30": ("mean", 6, 30),
        "mean_lb12_t30": ("mean", 12, 30),
        "mean_lb36_t30": ("mean", 36, 30),
        "median_lb36_t30": ("median", 36, 30),
        "mean_lb18_t15": ("mean", 18, 15),
        "mean_lb18_t60": ("mean", 18, 60),
        "sum_lb18_t30": ("sum", 18, 30),
        "sum_lb12_t30": ("sum", 12, 30),
        "sum_lb36_t30": ("sum", 36, 30),
    }
    months = list(month_iter(dt.date.fromisoformat(SEL_FROM), dt.date.fromisoformat(CURVE_TO)))
    for name, (stat, lb, mt) in variants.items():
        chosen, picks = [], {}
        for m in months:
            g, v, n = select_group2(groups, m, stat=stat, lb=lb, min_t=mt)
            g = g if g is not None else FIXED
            picks[m] = g
            chosen += month_tickets(groups, g, m, add_months(m, 1))
        s = summarise(chosen, bars)
        ks = [picks[m] for m in months]
        sw = sum(1 for a, b in zip(ks, ks[1:]) if a != b)
        out[name] = dict(stat=stat, lb=lb, min_tickets=mt, total_r=s["total_r"], n=s["n"],
                         mean_r=s["mean_r"], annualised=(s.get("nav") or {}).get("annualised"),
                         mdd=(s.get("nav") or {}).get("mdd"), calmar=(s.get("nav") or {}).get("calmar"),
                         switches=sw, switch_rate=round(sw / max(len(ks) - 1, 1), 4))
    # 整段 in-sample 最优一组(只看 2022-01 之后的票)—— 上界的另一个版本
    best, best_mu = None, None
    for g, tk in groups.items():
        sub = [t for t in tk if SEL_FROM <= t["entry_d"] <= CURVE_TO]
        if not sub:
            continue
        mu = sum(t["r"] for t in sub) / len(sub)
        if best_mu is None or mu > best_mu:
            best, best_mu = g, mu
    sub = [t for t in groups[best] if SEL_FROM <= t["entry_d"] <= CURVE_TO]
    s = summarise(sub, bars)
    out["insample_single_group"] = dict(group=str(best), mean_r_in_sample=round(best_mu, 6),
                                        total_r=s["total_r"], n=s["n"], mean_r=s["mean_r"],
                                        annualised=(s.get("nav") or {}).get("annualised"),
                                        mdd=(s.get("nav") or {}).get("mdd"),
                                        calmar=(s.get("nav") or {}).get("calmar"))
    # 固定组在 27 组网格里的名次(按总 R)
    rank = sorted(groups.items(), key=lambda kv: -sum(t["r"] for t in kv[1]))
    tot = {str(g): sum(t["r"] for t in tk) for g, tk in rank}
    out["grid_rank"] = dict(
        fixed_group=str(FIXED), fixed_total_r=round(tot[str(FIXED)], 4),
        fixed_rank=1 + sum(1 for v in tot.values() if v > tot[str(FIXED)]),
        best_group=str(rank[0][0]), best_total_r=round(tot[str(rank[0][0])], 4),
        worst_group=str(rank[-1][0]), worst_total_r=round(tot[str(rank[-1][0])], 4),
        rank_by_mean_r=sorted(groups.items(),
                               key=lambda kv: -(sum(t["r"] for t in kv[1]) / len(kv[1])))[0][0],
        rank_by_total_r=rank[0][0],
        total_r_sorted={str(g): round(v, 2) for g, v in tot.items()})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["fixed", "all", "explore"])
    ap.add_argument("--out", default=os.path.join(HERE, "t236_results.json"))
    args = ap.parse_args()

    bars = t159.load_bars()
    gate, maj = load_gate_and_maj()
    phase = load_phase()
    print(f"bars: {len(bars)} syms / {sum(len(v) for v in bars.values())} rows; "
          f"gate {len(gate)} days; phase {len(phase)} days", file=sys.stderr)

    abar = prep(bars)
    groups = {}
    for m in MS:
        for k in KS:
            for sx in SMAS:
                g = (k, sx, m)
                tk = mtm(run_param(abar, gate, SIG_FROM, SIG_TO, k, sx, m), bars)
                groups[g] = tk
    res = {"meta": {"sig_from": SIG_FROM, "sig_to": SIG_TO, "sel_from": SEL_FROM, "curve_to": CURVE_TO,
                    "fixed": FIXED, "lookback_m": LOOKBACK_M, "min_tickets": MIN_TICKETS,
                    "n_groups": len(groups), "random_paths": N_RANDOM, "random_seed": RANDOM_SEED,
                    "cost_roundtrip": COST},
           "groups": {str(g): dict(n=len(tk), total_r=round(sum(t["r"] for t in tk), 4),
                                   mean_r=round(sum(t["r"] for t in tk) / len(tk), 6) if tk else None,
                                   n_closed=sum(1 for t in tk if not t.get("still")))
                      for g, tk in groups.items()}}

    if args.stage == "fixed":
        json.dump(res, open(args.out, "w"), indent=1, default=str)
        print(json.dumps(res["groups"][str(FIXED)], indent=1))
        return

    if args.stage == "explore":
        ex = explore(groups, bars)
        if os.path.exists(args.out):
            old = json.load(open(args.out))
            old["explore"] = ex
            json.dump(old, open(args.out, "w"), indent=1, default=str)
        else:
            res["explore"] = ex
            json.dump(res, open(args.out, "w"), indent=1, default=str)
        print(json.dumps(ex, indent=1, default=str))
        return

    # ── 选择器 A(无条件走前) ──
    tkA, picksA = build_walkforward(groups)
    # ── 选择器 B(regime 条件:majors 200 日线上/下 × ⓪ turning/normal) ──
    def bucket(t):
        return (maj.get(t["entry_d"], False), phase.get(t["entry_d"], "normal"))
    tkB, picksB = build_walkforward(groups, bucket_key=bucket,
                                    a_choice={m: picksA[m]["group"] for m in picksA})
    buckets = sorted({bucket(t) for tk in groups.values() for t in tk})
    # ── 固定组 ──
    tkFix = [t for t in groups[FIXED] if SEL_FROM <= t["entry_d"] <= CURVE_TO]
    # ── 事后最优(上界) ──
    tkOracle, picksO = [], {}
    for m in month_iter(dt.date.fromisoformat(SEL_FROM), dt.date.fromisoformat(CURVE_TO)):
        m_end = add_months(m, 1)
        best, best_mu = None, None
        for g, tk in groups.items():
            sub = [t for t in tk if m.isoformat() <= t["entry_d"] < m_end.isoformat()]
            if not sub:
                continue
            mu = sum(t["r"] for t in sub) / len(sub)
            if best_mu is None or mu > best_mu:
                best, best_mu = g, mu
        if best is None:
            best = FIXED
        picksO[m] = dict(group=best, mu=best_mu)
        tkOracle += month_tickets(groups, best, m, m_end)

    res["A"] = summarise(tkA, bars)
    res["A"].update(switches(picksA))
    res["A"]["fallback_months"] = sum(1 for m in picksA if picksA[m]["fallback"])
    res["B"] = summarise(tkB, bars)
    res["B"].update(switches_b(picksB, buckets))
    res["B"]["picks"] = {m.isoformat(): {str(b): picksB[m][b]["group"] for b in picksB[m]}
                         for m in sorted(picksB)}
    res["fixed"] = summarise(tkFix, bars)
    res["oracle"] = summarise(tkOracle, bars)
    res["oracle"].update(switches(picksO))
    res["A"]["tickets"] = [(t["symbol"], t["entry_d"], t["exit_d"], round(t["r"], 4)) for t in tkA]
    res["B"]["tickets"] = [(t["symbol"], t["entry_d"], t["exit_d"], round(t["r"], 4)) for t in tkB]

    # ── 随机选参 1,000 条路径(只用 apparatus.py) ──
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "src")))
    from data.evaluation.apparatus import null_distribution, percentile_of  # noqa: E402
    months = list(month_iter(dt.date.fromisoformat(SEL_FROM), dt.date.fromisoformat(CURVE_TO)))
    gkeys = list(groups.keys())
    by_month = defaultdict(list)
    for g, tk in groups.items():
        for t in tk:
            by_month[(t["entry_d"][:7], g)].append(t)

    def one_path(rng):
        tot = 0.0
        for m in months:
            g = gkeys[int(rng.integers(0, len(gkeys)))]
            tot += sum(t["r"] for t in by_month.get((m.isoformat()[:7], g), []))
        return tot

    a_total = res["A"]["total_r"]
    null = null_distribution(one_path, N_RANDOM, RANDOM_SEED, actual=a_total)
    res["random"] = dict(n=int(null.size), q05=float(np.quantile(null, 0.05)), q50=float(np.quantile(null, 0.5)),
                         q95=float(np.quantile(null, 0.95)), q99=float(np.quantile(null, 0.99)),
                         mean=float(null.mean()), max=float(null.max()), min=float(null.min()),
                         pct_of_A=percentile_of(a_total, null), pct_of_B=percentile_of(res["B"]["total_r"], null))
    # A/B 各自的 95 分位判定
    res["random"]["A_ge_q95"] = bool(a_total >= float(np.quantile(null, 0.95)))
    res["random"]["B_ge_q95"] = bool(res["B"]["total_r"] >= float(np.quantile(null, 0.95)))

    # ── 判定(预注册 ⑥) ──
    def judge(tag, s):
        c1 = s["total_r"] > res["fixed"]["total_r"]
        c2 = s["total_r"] >= float(np.quantile(null, 0.95))
        c3 = s["h1_2022_23"]["total_r"] > res["fixed"]["h1_2022_23"]["total_r"] and \
            s["h2_2024_26"]["total_r"] > res["fixed"]["h2_2024_26"]["total_r"]
        c4 = None
        if s.get("nav", {}).get("calmar") is not None and res["fixed"].get("nav", {}).get("calmar") is not None:
            c4 = s["nav"]["calmar"] >= 0.9 * res["fixed"]["nav"]["calmar"]
        chk = dict(total_r_beats_fixed=c1, total_r_ge_random_q95=c2, both_halves_beat_fixed=c3,
                   calmar_not_worse_10pct=c4)
        passed = all(v is True for v in chk.values())
        res[f"judge_{tag}"] = dict(checks=chk, passed=passed,
                                   failed=[k for k, v in chk.items() if v is False])
        return passed

    pa = judge("A", res["A"])
    pb = judge("B", res["B"])
    res["verdict"] = "✅" if (pa or pb) else "❌"
    res["verdict_detail"] = dict(A=pa, B=pb)

    json.dump(res, open(args.out, "w"), indent=1, default=str)
    slim = {k: v for k, v in res.items() if k not in ("A", "B", "groups")}
    slim["A"] = {k: v for k, v in res["A"].items() if k != "tickets"}
    slim["B"] = {k: v for k, v in res["B"].items() if k != "tickets"}
    slim["groups"] = res["groups"]
    print(json.dumps(slim, indent=1, default=str))


if __name__ == "__main__":
    main()
