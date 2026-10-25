#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-681 H2 —— 暴涨回落 + 硬止损(台账 REFUTATION_LEDGER.md S-681 H2,2026-10-25 预注册)。

照台账一字不改(信号、止损 s、持有 N、对照、发现段 / 留出段、四条判据):
  信号 = 3 日收益(close_t / close_{t−3} − 1) ≥ +40%
       且 上市 ≥ 60 天(该合约第 61 根日线起)
       且 30 日成交额均值(含当天,quote volume)≥ $5M
       且 **不在**当天 30 日成交额前 20 名
       且 同币 14 天内只取第一次
  交易 = 信号日 t 收盘定、t+1 开盘进空;硬止损 = 进场 × (1 + 30%);持有 14 天到期
  对照 = null_same_day:同一信号日、合格(上市 ≥ 60 天 / 成交额 ≥ $5M / 不在前 20)但 3 日收益 < +40% 的合约随机抽,同 s / N
  判据 = judge() 四条(① 发现段平均 R > 0 且月块 p < 0.05;② ≥ 对照 95 分位;③ 留出段平均 R > 0;④ 发现段 ≥ 50 张)

模拟器全部 import docs/research/short_lab_common.py(S-681 唯一一份),不复制、不另写零分布。
先跑发现段 → 落盘 → 再打开留出段(main() 里两个函数,顺序即纪律)。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import short_lab_common as sl  # noqa: E402

OUT_JSON = os.path.join(HERE, "s681_h2_pump_fade_results.json")
SPOT_DAILY = os.path.join(sl.DATA_ROOT, "research", "s677", "_bv_daily.jsonl")

# ── 参数(台账写死,不改)──────────────────────────────────────────────────────────────
S_STOP = 0.30          # 硬止损:进场 × (1 + s)
N_HOLD = 14            # 持有天数
PUMP = 0.40            # 3 日涨 ≥ +40%
MIN_LIST_BARS = 60     # 第 61 根日线起(0-based index 60)
MIN_ADV = 5_000_000.0  # 30 日成交额均值 ≥ $5M
TOP_N = 20             # 当天 30 日成交额前 20 名 → 排除
DEDUP_DAYS = 14        # 同币 14 天内只取第一次
BUCKET_EDGES = (0.60, 1.00)  # 强度分档 40–60% / 60–100% / > 100%


# ── 小工具 ──────────────────────────────────────────────────────────────────────────
def _j(o):
    """json 序列化:numpy → python。"""
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if math.isnan(f) else f
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def dump(obj, path=OUT_JSON):
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=_j)


# ── 宇宙与派生量 ────────────────────────────────────────────────────────────────────
def prep(universe):
    """给每个合约补派生量:ret3(3 日收益)、adv30(30 日成交额均值,含当天)。只用当天及以前。"""
    for a in universe.values():
        c = a["c"]
        r3 = np.full(len(c), np.nan)
        if len(c) > 3:
            r3[3:] = c[3:] / c[:-3] - 1.0
        a["ret3"] = r3
        a["adv"] = sl.adv30(a)
    return universe


def top_exclusions(universe):
    """每天 30 日成交额前 20 名 → 该日被排除的合约集合(全宇宙横截面,不看 $5M 门槛)。"""
    by_day = {}
    for s, a in universe.items():
        for i, d in enumerate(a["d"]):
            v = a["adv"][i]
            if v is None or np.isnan(v):
                continue
            by_day.setdefault(d, []).append((float(v), s))
    excl = {}
    for d, lst in by_day.items():
        lst.sort(key=lambda x: (-x[0], x[1]))
        excl[d] = {s for _, s in lst[:TOP_N]}
    return excl


def eligible_pool(universe, excl, max_ret):
    """合格(上市 ≥ 60 天 / 成交额 ≥ $5M / 不在前 20)且 3 日收益 < max_ret → 日期 → [(sym, idx)]。"""
    pool = {}
    for s, a in universe.items():
        for i in range(MIN_LIST_BARS, len(a["d"])):
            r3 = a["ret3"][i]
            if np.isnan(r3) or r3 >= max_ret:
                continue
            v = a["adv"][i]
            if np.isnan(v) or v < MIN_ADV:
                continue
            if s in excl.get(a["d"][i], ()):
                continue
            pool.setdefault(a["d"][i], []).append((s, i))
    return pool


def signals(universe, excl):
    """暴涨信号(3 日 ≥ +40%)。同币 14 天内只取第一次。返回 [(sym, idx)]。"""
    out = []
    for s, a in universe.items():
        last = None
        for i in range(MIN_LIST_BARS, len(a["d"])):
            r3 = a["ret3"][i]
            if np.isnan(r3) or r3 < PUMP:
                continue
            v = a["adv"][i]
            if np.isnan(v) or v < MIN_ADV:
                continue
            d = a["d"][i]
            if s in excl.get(d, ()):
                continue
            dd = dt.date.fromisoformat(d)
            if last is not None and (dd - last).days < DEDUP_DAYS:
                continue
            last = dd
            out.append((s, i))
    out.sort(key=lambda x: (universe[x[0]]["d"][x[1]], x[0]))
    return out


def build_tickets(universe, funds, sigs):
    """信号 → 空单票(同 s / N / 资金费),再 chain(同币持仓期间不叠票)。"""
    tk = []
    for s, i in sigs:
        t = sl.short_ticket(universe[s], i, S_STOP, N_HOLD, fund=funds.get(s), symbol=s)
        if t:
            t["ret3"] = float(universe[s]["ret3"][i])
            t["list_bars"] = i
            tk.append(t)
    return sl.chain(tk)


def make_fn(universe, funds):
    def make(sym, idx):
        return sl.short_ticket(universe[sym], idx, S_STOP, N_HOLD, fund=funds.get(sym), symbol=sym)
    return make


# ── 报告项 ──────────────────────────────────────────────────────────────────────────
def payoff(tickets):
    """胜率与赔率:平均赢 R / 平均亏 R。"""
    r = np.array([t["r"] for t in tickets], float) if tickets else np.array([])
    if not len(r):
        return {}
    w, l = r[r > 0], r[r <= 0]
    return {"win_r": float(w.mean()) if len(w) else None,
            "loss_r": float(l.mean()) if len(l) else None,
            "payoff": float(w.mean() / abs(l.mean())) if len(w) and len(l) and l.mean() != 0 else None}


def bucket_of(r3):
    if r3 < BUCKET_EDGES[0]:
        return "40-60%"
    if r3 < BUCKET_EDGES[1]:
        return "60-100%"
    return ">100%"


def buckets(tickets):
    out = {}
    for name in ("40-60%", "60-100%", ">100%"):
        sub = [t for t in tickets if bucket_of(t["ret3"]) == name]
        if sub:
            r = np.array([t["r"] for t in sub])
            out[name] = {"n": len(sub), "mean_r": float(r.mean()), "win": float((r > 0).mean()),
                         "total_r": float(r.sum())}
        else:
            out[name] = {"n": 0}
    return out


def hedged(tickets, um):
    """对冲版:空 + 等名义多 BTC(同一进出场日,多头用开盘价进 / 开盘价出)。

    每一腿各自以「进场名义 = 1」计:对冲票收益 = 空单收益(含资金费与成本)+ BTC 多头收益(含成本)。
    空单止损是日内价(非开盘),BTC 腿用开盘价近似 —— 报告里写明。"""
    btc = um.get("BTC")
    if btc is None:
        return {"n": 0, "note": "no BTC in universe"}
    bidx = {d: i for i, d in enumerate(btc["d"])}

    def px(d, kind):
        i = bidx.get(d)
        if i is None:
            return None
        return float(btc["o"][i] if kind == "o" else btc["c"][i])

    out = []
    for t in tickets:
        e = px(t["entry_d"], "o")
        x = px(t["exit_d"], "c" if t["still"] else "o")
        if not e or not x:
            continue
        ret_btc = x / e - 1.0 - 2 * sl.COST_SIDE
        hret = t["ret"] + ret_btc
        out.append({"symbol": t["symbol"], "signal_d": t["signal_d"], "entry_d": t["entry_d"], "exit_d": t["exit_d"],
                    "short_ret": t["ret"], "btc_ret": ret_btc, "hedged_ret": hret, "hedged_r": hret / t["risk"]})
    if not out:
        return {"n": 0}
    hr = np.array([o["hedged_r"] for o in out])
    by_y = {}
    for o in out:
        by_y.setdefault(o["signal_d"][:4], []).append(o["hedged_r"])
    return {"n": len(out), "mean_hedged_r": float(hr.mean()), "median_hedged_r": float(np.median(hr)),
            "win": float((hr > 0).mean()), "total_hedged_r": float(hr.sum()),
            "mean_short_ret": float(np.mean([o["short_ret"] for o in out])),
            "mean_btc_ret": float(np.mean([o["btc_ret"] for o in out])),
            "by_year": {y: (len(v), round(float(np.mean(v)), 4)) for y, v in sorted(by_y.items())}}


def worst_tickets(tickets, k=10):
    ts = sorted(tickets, key=lambda t: t["r"])[:k]
    return [{kk: t[kk] for kk in ("symbol", "signal_d", "entry_d", "exit_d", "r", "ret", "why", "gap", "hold_days")}
            for t in ts]


def money_of(tickets, nb, d_to):
    """资金曲线(t159.nav:每票风险 0.5%、最多同时 10 张)。"""
    if not tickets:
        return None
    return sl.money(tickets, nb, d_to)


# ── 两段:先发现段,再打开留出段 ──────────────────────────────────────────────────────
def run_discovery(tickets, pool, universe, funds, nb):
    """发现段(信号日 2020-01-01 → 2023-12-31):判据 ①②④ + 只报项。留出段此刻还没打开。"""
    disc = sl.in_window(tickets, *sl.DISCOVERY)
    null = sl.null_same_day(disc, pool, make_fn(universe, funds))
    j = sl.judge(disc, null, [])            # ③ 需要留出段,这里留空 → 留到 run_holdout 后再判
    d_to = max(t["exit_d"] for t in disc) if disc else sl.DISCOVERY[1]
    return {
        "window": list(sl.DISCOVERY),
        "summary": sl.summary(disc),
        "payoff": payoff(disc),
        "buckets": buckets(disc),
        "null": {"draws": int(len(null)), "median": float(np.median(null)) if len(null) else None,
                 "q05": float(np.quantile(null, 0.05)) if len(null) else None,
                 "q95": float(np.quantile(null, 0.95)) if len(null) else None,
                 "mean": float(null.mean()) if len(null) else None},
        "judge_partial": j,               # ① ② ④ 此刻有效;③ 待留出段
        "money": money_of(disc, nb, d_to),
        "money_d_to": d_to,
        "hedged": hedged(disc, universe),
        "worst": worst_tickets(disc),
        "n_signals": len(disc),
        "_null": null,
    }


def run_holdout(tickets, universe, nb):
    """留出段(信号日 2024-01-01 → 最后一个完整月):只报项 + 判据 ③。"""
    hold = [t for t in tickets if t["signal_d"] >= sl.HOLDOUT_FROM]
    d_to = max((d for a in universe.values() for d in a["d"]), default=sl.HOLDOUT_FROM)
    return {
        "window": [sl.HOLDOUT_FROM, d_to],
        "summary": sl.summary(hold),
        "payoff": payoff(hold),
        "buckets": buckets(hold),
        "money": money_of(hold, nb, d_to),
        "money_d_to": d_to,
        "hedged": hedged(hold, universe),
        "worst": worst_tickets(hold),
        "n_signals": len(hold),
    }


def run_spot():
    """只报:另一个场所 / 时代 —— Binance 现货 2018–2020(同一信号与管理,无资金费)。"""
    if not os.path.exists(SPOT_DAILY):
        return {"n": 0, "note": "spot file missing"}
    universe = {}
    for line in open(SPOT_DAILY):
        x = json.loads(line)
        rows = sorted({tuple(b) for b in x["bars"] if b[4] > 0})
        if not rows:
            continue
        a = np.array([r[1:] for r in rows], float)
        universe[x["symbol"]] = {"d": [r[0] for r in rows], "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3],
                                 "qv": a[:, 4]}
    prep(universe)
    excl = top_exclusions(universe)
    sigs = signals(universe, excl)
    tk = build_tickets(universe, {}, sigs)   # 现货无资金费
    if not tk:
        return {"n": 0}
    r = np.array([t["r"] for t in tk])
    by_y = {}
    for t in tk:
        by_y.setdefault(t["signal_d"][:4], []).append(t["r"])
    by_m = {}
    for t in tk:
        by_m.setdefault(t["signal_d"][:7], []).append(t["r"])
    return {"n": len(tk), "mean_r": float(r.mean()), "median_r": float(np.median(r)), "win": float((r > 0).mean()),
            "total_r": float(r.sum()), "worst_r": float(r.min()), "best_r": float(r.max()),
            "mean_ret": float(np.mean([t["ret"] for t in tk])),
            "payoff": payoff(tk), "buckets": buckets(tk),
            "by_year": {y: (len(v), round(float(np.mean(v)), 3)) for y, v in sorted(by_y.items())},
            "by_month": {m: (len(v), round(float(np.mean(v)), 3)) for m, v in sorted(by_m.items())},
            "range": [min(t["signal_d"] for t in tk), max(t["signal_d"] for t in tk)]}


# ── 主流程 ──────────────────────────────────────────────────────────────────────────
def main():
    um = sl.load_um()
    funds = sl.daily_funding(sl.load_funding())
    prep(um)
    excl = top_exclusions(um)
    sigs = signals(um, excl)
    tickets = build_tickets(um, funds, sigs)
    pool = eligible_pool(um, excl, PUMP)

    last_d = max((d for a in um.values() for d in a["d"]), default="")
    meta = {"hypothesis": "S-681 H2 暴涨回落 + 硬止损", "params": {"s": S_STOP, "n_hold": N_HOLD, "pump": PUMP,
               "min_list_bars": MIN_LIST_BARS, "min_adv_usd": MIN_ADV, "top_n_excluded": TOP_N,
               "dedup_days": DEDUP_DAYS},
            "discovery": list(sl.DISCOVERY), "holdout_from": sl.HOLDOUT_FROM, "data_last": last_d,
            "um_symbols": len(um), "funding_symbols": len(funds),
            "n_signals_raw": len(sigs), "n_tickets_after_chain": len(tickets),
            "n_pool_days": len(pool), "seed": sl.SEED, "simulator": "docs/research/short_lab_common.py"}

    # ① 发现段先算完并落盘
    nb = sl.nav_bars(um)
    disc = run_discovery(tickets, pool, um, funds, nb)
    res = {"meta": meta, "discovery": disc}
    dump(res)
    print("[discovery]", json.dumps({"n": disc["summary"].get("n"), "mean_r": disc["summary"].get("mean_r"),
                                     "p_le0": disc["judge_partial"].get("1_p_le0"),
                                     "null_q95": disc["judge_partial"].get("2_null_q95"),
                                     "pct": disc["judge_partial"].get("2_pct")}, default=_j))

    # ② 再打开留出段
    hold = run_holdout(tickets, um, nb)
    res["holdout"] = hold
    res["judged"] = sl.judge(sl.in_window(tickets, *sl.DISCOVERY), disc["_null"],
                             [t for t in tickets if t["signal_d"] >= sl.HOLDOUT_FROM])
    res["meta"]["n_pool_days"] = len(pool)
    res["tickets"] = tickets
    res["signals"] = [{"symbol": s, "idx": i, "d": um[s]["d"][i], "ret3": float(um[s]["ret3"][i]),
                       "adv30": float(um[s]["adv"][i])} for s, i in sigs]
    # ③ 只报项:另一个场所 / 时代(Binance 现货 2018–2020)
    res["spot_2018_2020"] = run_spot()
    res["discovery"].pop("_null", None)
    dump(res)
    print("[holdout]", json.dumps({"n": hold["summary"].get("n"), "mean_r": hold["summary"].get("mean_r")}, default=_j))
    print("[spot]", json.dumps({"n": res["spot_2018_2020"].get("n"), "mean_r": res["spot_2018_2020"].get("mean_r")},
                               default=_j))
    print("[verdict]", json.dumps(res["judged"], default=_j))
    return res


if __name__ == "__main__":
    main()
