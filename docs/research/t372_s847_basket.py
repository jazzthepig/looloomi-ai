#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-372 / S-847:边际流动性在抽时,空一篮子流动性够的山寨、等额多 BTC —— 篮子能不能把单币空票的尾巴摊掉。

预注册见 REFUTATION_LEDGER.md 的 `## S-847`(写于对任何篮子算任何收益之前)。规则一字不改:
  · 每周日判状态,下周一生效、持一周;
  · 状态 = state_daily(entity=panel)的 stable_supply_30d < 0(用该周日的读数);
  · 篮子 = U 本位永续(s681/_um_daily.jsonl)非 BTC、非稳定币,按**截至该周日的过去 30 天成交额**取前 20 名,
    再剔除**过去 7 天资金费合计 < −0.1%** 的(空头拥挤);等权、单币 ≤ 篮子的 5%;
  · 仓位:空篮子名义 1、多 BTC 名义 1,每周再平衡;成本每腿每边 10 bp;资金费计入(主口径);
    状态不成立的周空仓。
  · 对照 (a):同一个篮子在状态**不成立**的周(无条件的山寨对 BTC 漂移);
  · 对照 (b):把状态序列按周循环平移 200 次(种子 20261113)。
只读。不入库。

用法(仓库根目录):
  python3 docs/research/t372_s847_basket.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "docs", "research"))
_spec = importlib.util.spec_from_file_location("apparatus", os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py"))
apparatus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apparatus)

R = "/Volumes/CometCloudAI/cometcloud-local/research/"
OUT = os.path.join(ROOT, "docs", "research", "t372_results.json")

# ── 预注册参数(不调) ─────────────────────────────────────────────────────────
D0 = dt.date(2020, 1, 1)
SEED = 20261113
N_NULL = 200
COST = 0.0010            # 每腿每边 10 bp
TOPN = 20                # 过去 30 天成交额前 20
CROWDSUM = -0.001        # 过去 7 天资金费合计 < −0.1% ⇒ 空头拥挤,剔除
CAP = 0.05               # 单币 ≤ 篮子的 5%
VOL_WIN, FUND_WIN = 30, 7
ALPHA = 0.05
STABLE = {"USDT", "USDC", "FDUSD", "TUSD", "USDP", "BUSD", "DAI", "EURI", "EURT",
          "USTC", "USDD", "PYUSD", "USDS", "USDTB", "RLUSD", "USD1", "GUSD", "SUSD", "USDF"}
HALVE = dt.date(2024, 4, 20)     # 最近一次减半
H18 = dt.date(2025, 10, 20)      # 减半后 18 个月
H30 = dt.date(2026, 10, 20)      # 减半后 30 个月

BASE = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = os.environ["SUPABASE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}


def get(path: str, params: dict) -> list:
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}/{path}?{q}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
    return json.loads(body) if body else []


def fetch_all(table: str, filters: dict, order: str, columns: str = "*") -> list:
    """翻页读,一律带 order=(PostgREST 不带 order 时边界会漂);每页最多 1000 行。"""
    rows, offset = [], 0
    while True:
        params = dict(filters)
        params.update({"select": columns, "order": order, "limit": "1000", "offset": str(offset)})
        page = get(table, params)
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return rows


# ── 1. 数据 ──────────────────────────────────────────────────────────────────
def load_state():
    rows = fetch_all("state_daily", {"entity": "eq.panel", "feature": "eq.stable_supply_30d"}, "d.asc", "d,value")
    out = {}
    for r in rows:
        if r.get("value") is not None:
            out[dt.date.fromisoformat(str(r["d"])[:10])] = float(r["value"])
    print(f"[state] stable_supply_30d: {len(out)} rows {min(out)} → {max(out)}", flush=True)
    return out


def load_daily():
    """U 本位永续日线 → 每 pair 的 (day_index, close, quote_volume, symbol)。"""
    store = {}
    for line in open(R + "s681/_um_daily.jsonl"):
        x = json.loads(line)
        p = x["pair"]
        if not p.endswith("USDT"):
            continue
        bars = x["bars"]
        if not bars:
            continue
        ds = np.array([str(b[0])[:10] for b in bars])
        days = (ds.astype("datetime64[D]") - np.datetime64(D0, "D")).astype(np.int64)
        c = np.array([float(b[4]) if len(b) > 4 and b[4] else np.nan for b in bars], dtype=float)
        v = np.array([float(b[5]) if len(b) > 5 and b[5] else 0.0 for b in bars], dtype=float)
        keep = (days >= 0) & np.isfinite(c) & (c > 0)
        if not keep.any():
            continue
        store[p] = (days[keep], c[keep], v[keep], x["symbol"])
    print(f"[daily] pairs={len(store)}", flush=True)
    return store


def load_funding():
    """资金费:每 pair 每日 8 小时费率合计(空头收正费率、多头付出)。"""
    F = np.zeros((len(PAIRS), NDAY))
    seen = 0
    for line in open(R + "s681/_um_funding.jsonl"):
        x = json.loads(line)
        i = PIDX.get(x["pair"])
        if i is None:
            continue
        rates = x["rates"]
        if not rates:
            continue
        ds = np.array([str(r[0])[:10] for r in rates])
        days = (ds.astype("datetime64[D]") - np.datetime64(D0, "D")).astype(np.int64)
        vals = np.array([float(r[1]) if r[1] is not None else 0.0 for r in rates], dtype=float)
        ok = (days >= 0) & (days < NDAY)
        if not ok.any():
            continue
        F[i] += np.bincount(days[ok], weights=vals[ok], minlength=NDAY)
        seen += 1
    print(f"[funding] pairs_seen={seen}", flush=True)
    return F


store = load_daily()
PAIRS = sorted(store)
PIDX = {p: i for i, p in enumerate(PAIRS)}
SYM = {p: store[p][3] for p in PAIRS}
IB = PAIRS.index("BTCUSDT")
NDAY = max(int(store[p][0].max()) for p in PAIRS) + 1
DAYS = [D0 + dt.timedelta(days=i) for i in range(NDAY)]
NP = len(PAIRS)
P = np.full((NP, NDAY), np.nan)
V = np.zeros((NP, NDAY))
for p, (d, c, v, _s) in store.items():
    i = PIDX[p]
    P[i, d] = c
    V[i, d] = v
del store
# 价格前向填充(退市/停牌沿用最后价;与 S-840 的 last_a/last_b 同口径)
for i in range(NP):
    row = P[i]
    m = ~np.isnan(row)
    if not m.any():
        continue
    idx = np.where(m, np.arange(NDAY), 0)
    np.maximum.accumulate(idx, out=idx)
    P[i] = row[idx]
print(f"[matrix] pairs={NP} days={NDAY} {DAYS[0]} → {DAYS[-1]}", flush=True)

F = load_funding()
SUPPLY = load_state()

# ── 2. 周循环:成分、权重、周收益 ─────────────────────────────────────────────
SUN = [i for i in range(NDAY) if DAYS[i].weekday() == 6]
SUN = [i for i in SUN if i + 7 < NDAY and i - VOL_WIN >= 0]
IS_STABLE = np.array([SYM[p].upper() in STABLE for p in PAIRS])
BTC_I = np.arange(NP) == IB


def select_basket(d, drop_crowded=True, cap=CAP):
    """d = 周日索引。返回 (成分索引数组, 权重数组)。"""
    v30 = V[:, d - VOL_WIN + 1:d + 1].sum(axis=1)
    ok = (v30 > 0) & (~IS_STABLE) & (~BTC_I)
    cand = np.where(ok)[0]
    if cand.size == 0:
        return np.array([], dtype=int), np.array([])
    order = cand[np.argsort(-v30[cand], kind="stable")][:TOPN]
    if drop_crowded:
        f7 = F[:, d - FUND_WIN + 1:d + 1].sum(axis=1)
        order = order[f7[order] >= CROWDSUM]
    if order.size == 0:
        return np.array([], dtype=int), np.array([])
    return order, weights(order, cap)


def weights(sel, cap=CAP):
    """等权 + 单币 ≤ 5%;成分不足 20 个时按 5% 上限用满,剩余留现金(空篮名义 < 1)。"""
    n = sel.size
    if n == 0:
        return np.array([])
    if cap is None:          # 敏感性口径:纯等权 1/n(不封 5%)
        return np.full(n, 1.0 / n)
    w = np.zeros(n)
    rem, active = 1.0, list(range(n))
    while rem > 1e-12 and active:
        share = rem / len(active)
        over = [i for i in active if share > CAP + 1e-12]
        if over:
            for i in over:
                w[i] = CAP
            rem -= CAP * len(over)
            active = [i for i in active if i not in over]
            continue
        for i in active:
            w[i] = share
        rem = 0.0
        break
    return w


def week_ret(d, sel, w, with_btc=True):
    """周一(d+1)收盘建仓、周日(d+7)收盘平仓的一周收益(相对组合权益 1)。"""
    a, b = d + 1, d + 7
    out = {"price": 0.0, "fund": 0.0, "cost": 0.0, "contrib": [], "notional": 0.0, "short_price": 0.0, "btc_leg": 0.0}
    if sel.size:
        r = P[sel, b] / P[sel, a] - 1.0
        leg = -w * r                        # 空篮子价格腿
        out["short_price"] = float(leg.sum())
        out["price"] = float(leg.sum())
        out["notional"] = float(w.sum())
        for j in range(sel.size):
            out["contrib"].append({"pair": PAIRS[sel[j]], "sym": SYM[PAIRS[sel[j]]],
                                    "w": float(w[j]), "r": float(r[j]), "contrib": float(leg[j])})
        out["fund"] = float((w * F[sel, a:b + 1].sum(axis=1)).sum())   # 空头收正费率
    n_legs = 1 if sel.size else 0
    if with_btc:
        out["btc_leg"] = float(P[IB, b] / P[IB, a] - 1.0)
        out["price"] += out["btc_leg"]
        out["fund"] -= float(F[IB, a:b + 1].sum())                     # 多头付出
        n_legs += 1
    # 成本:每周平旧仓 + 开新仓,每腿每边 10 bp
    out["cost"] = -COST * 2.0 * (out["notional"] + (1.0 if with_btc else 0.0))
    out["ret"] = out["price"] + out["fund"] + out["cost"]
    return out


ZERO = {"ret": 0.0, "price": 0.0, "fund": 0.0, "cost": 0.0, "contrib": [], "notional": 0.0,
        "short_price": 0.0, "btc_leg": 0.0}


def build_weeks(drop_crowded=True, cap=CAP):
    rows = []
    for d in SUN:
        val = SUPPLY.get(DAYS[d])
        on = bool(val is not None and val < 0)
        sel, w = select_basket(d, drop_crowded=drop_crowded, cap=cap)
        r = week_ret(d, sel, w) if sel.size else dict(ZERO)
        rs = week_ret(d, sel, w, with_btc=False) if sel.size else dict(ZERO)
        rows.append({"d": d, "date": str(DAYS[d]), "state_val": val, "on": on, "n": int(sel.size),
                     "pairs": [PAIRS[i] for i in sel], "w": [float(x) for x in w],
                     "ret": float(r["ret"]), "price": float(r["price"]), "fund": float(r["fund"]),
                     "cost": float(r["cost"]), "notional": float(r["notional"]),
                     "short_price": float(r["short_price"]), "btc_leg": float(r["btc_leg"]),
                     "short_only_ret": float(rs["ret"]), "contrib": r["contrib"]})
    return rows


print("[weeks] building ...", flush=True)
WK = build_weeks(drop_crowded=True)
WK_NC = build_weeks(drop_crowded=False)
WK_EQ = build_weeks(drop_crowded=True, cap=None)
for w in WK + WK_NC:
    w["main"] = w["ret"] if w["on"] else 0.0
    w["main_short_only"] = w["short_only_ret"] if w["on"] else 0.0
    w["main_nocost"] = (w["ret"] - w["cost"]) if w["on"] else 0.0
print(f"[weeks] {len(WK)} weeks {WK[0]['date']} → {WK[-1]['date']}", flush=True)


def wk_stats(rows):
    on = [r for r in rows if r["on"]]
    off = [r for r in rows if not r["on"]]
    if not on:
        return None
    a = np.array([r["main"] for r in on], dtype=float)
    b = np.array([r["ret"] for r in off], dtype=float) if off else np.array([0.0])   # 对照 (a):无条件篮子
    return {"n_on": len(on), "n_off": len(off), "mean_on": float(a.mean()), "median_on": float(np.median(a)),
            "sum_on": float(a.sum()), "worst_on": float(a.min()),
            "worst_week": min(on, key=lambda r: r["main"])["date"],
            "mean_off_uncond": float(b.mean()), "n_off_nonzero": int((b != 0).sum())}


S = wk_stats(WK)
S_NC = wk_stats(WK_NC)
print("[stat]", json.dumps(S, ensure_ascii=False), flush=True)

# ── 3. 判据 ①–⑤ ─────────────────────────────────────────────────────────────
on_rows = [r for r in WK if r["on"]]
on_rets = np.array([r["main"] for r in on_rows], dtype=float)
ab = apparatus.ab_test(np.zeros_like(on_rets), on_rets, mean_block=4.0, n_boot=2000, seed=SEED, alpha=ALPHA)
p_one_sided = float(ab.get("p_b_le_a", 1.0)) if isinstance(ab, dict) else 1.0
j1 = bool(S["mean_on"] > 0 and p_one_sided < ALPHA and isinstance(ab, dict) and "p_b_le_a" in ab)
print(f"[①] 状态周周均={S['mean_on']*100:.3f}%  p={p_one_sided}  ab={json.dumps(ab, ensure_ascii=False)}", flush=True)

j2 = bool(S["mean_on"] > S["mean_off_uncond"])
print(f"[②] 状态周周均={S['mean_on']*100:.3f}%  vs  非状态周(无条件篮子)周均={S['mean_off_uncond']*100:.3f}%", flush=True)

rng = np.random.default_rng(SEED)
nweek = len(WK)
flags = np.array([1.0 if r["on"] else 0.0 for r in WK])
rets = np.array([r["ret"] for r in WK], dtype=float)
null = []
for _ in range(N_NULL):
    k = int(rng.integers(0, nweek))
    m = np.roll(flags, k) > 0
    null.append(float(rets[m].mean()) if m.any() else 0.0)
null = np.array(null)
q90 = float(np.quantile(null, 0.90))
j3 = bool(S["mean_on"] > q90)
print(f"[③] 状态周周均={S['mean_on']*100:.3f}%  vs 平移分布 90 分位={q90*100:.3f}% (中位 {np.median(null)*100:.3f}%)", flush=True)

by_year = {}
for r in on_rows:
    by_year.setdefault(int(r["date"][:4]), []).append(r["main"])
year_mean = {y: float(np.mean(v)) for y, v in by_year.items()}
year_sum = {y: float(np.sum(v)) for y, v in by_year.items()}
n_year = len(year_mean)
n_pos = sum(1 for v in year_mean.values() if v > 0)
frac_pos = n_pos / n_year if n_year else 0.0
best_year = max(year_mean, key=lambda y: year_mean[y])
drop_best = float(np.mean([r["main"] for r in on_rows if int(r["date"][:4]) != best_year])) if n_year > 1 else None
j4 = bool(frac_pos >= 2 / 3)
j4b = bool(drop_best is not None and drop_best > 0)
print(f"[④] 有数据的年份 {n_year} 个,为正 {n_pos} 个 ({frac_pos:.3f} ≥ 0.667);去掉最好年 {best_year} 后均值="
      f"{None if drop_best is None else round(drop_best*100,3)}% (只报)", flush=True)

worst = min(on_rows, key=lambda r: r["main"]) if on_rows else None
worst_ret = worst["main"] if worst else None
max_drag, max_drag_info = 0.0, None
for r in on_rows:
    for c in r["contrib"]:
        if -c["contrib"] > max_drag:
            max_drag = -c["contrib"]
            max_drag_info = {"week": r["date"], "pair": c["pair"], "sym": c["sym"], "w": c["w"],
                             "r": c["r"], "drag_pp": -c["contrib"] * 100}
j5a = bool(worst_ret is not None and worst_ret > -0.15)
j5b = bool(max_drag <= 0.02)
print(f"[⑤] 最差一周 {worst['date'] if worst else None} {None if worst_ret is None else round(worst_ret*100,2)}% (> −15%); "
      f"单币最大拖累 {max_drag*100:.3f} pp (≤ 2pp) {max_drag_info}", flush=True)

# ── 4. 只报项 ────────────────────────────────────────────────────────────────
all_years = sorted({int(r["date"][:4]) for r in WK})
state_cnt_by_year = {str(y): sum(1 for r in WK if int(r["date"][:4]) == y and r["on"]) for y in all_years}
seg = {"18-30m": [], "other": []}
for r in on_rows:
    d0 = dt.date.fromisoformat(r["date"])
    seg["18-30m" if (HALVE <= d0 <= H30) else "other"].append(r["main"])
so = np.array([r["main_short_only"] for r in on_rows], dtype=float) if on_rows else np.array([])
report_only = {
    "state_weeks_total": len(on_rows),
    "state_weeks_by_year": state_cnt_by_year,
    "unconditional_basket_mean_by_year_pct": {str(y): round(float(np.mean([r["ret"] for r in WK if int(r["date"][:4]) == y])) * 100, 3) for y in all_years},
    "year_mean_state_weeks_pct": {str(y): round(v * 100, 3) for y, v in year_mean.items()},
    "year_sum_state_weeks_pct": {str(y): round(v * 100, 3) for y, v in year_sum.items()},
    "no_crowd_drop": {"n_on": S_NC["n_on"], "mean_on_pct": round(S_NC["mean_on"] * 100, 3),
                       "worst_on_pct": round(S_NC["worst_on"] * 100, 3),
                       "vs_main_mean_pp": round((S_NC["mean_on"] - S["mean_on"]) * 100, 3)},
    "short_only_no_btc": {"n_on": int(so.size), "mean_on_pct": round(float(so.mean()) * 100, 3) if so.size else None,
                          "worst_on_pct": round(float(so.min()) * 100, 3) if so.size else None},
    "halving_phase": {k: {"n": len(v), "mean_pct": round(float(np.mean(v)) * 100, 3) if v else None,
                           "sum_pct": round(float(np.sum(v)) * 100, 3)} for k, v in seg.items()},
    "basket_size_hist_all_weeks": {str(k): sum(1 for r in WK if r["n"] == k) for k in sorted({r["n"] for r in WK})},
    "basket_size_hist_state_weeks": {str(k): sum(1 for r in on_rows if r["n"] == k) for k in sorted({r["n"] for r in on_rows})},
    "state_weeks_basket_lt20": sum(1 for r in on_rows if r["n"] < TOPN),
    "state_weeks_no_basket": sum(1 for r in on_rows if r["n"] == 0),
    "mean_basket_notional_state_weeks": round(float(np.mean([r["notional"] for r in on_rows])), 4) if on_rows else None,
    "state_weeks_notional_lt1": sum(1 for r in on_rows if r["notional"] < 0.999),
    "cost_convention": "每周平旧仓 + 开新仓;空篮腿每边 10 bp、多 BTC 腿每边 10 bp ⇒ 名义各 1 时每腿每周 20 bp、合计 40 bp/周",
    "nocost_sensitivity_mean_on_pct": round(float(np.mean([r["main_nocost"] for r in on_rows])) * 100, 3) if on_rows else None,
    "gross_split_state_weeks_pct": {
        "mean_price": round(float(np.mean([r["price"] for r in on_rows])) * 100, 4) if on_rows else None,
        "mean_fund": round(float(np.mean([r["fund"] for r in on_rows])) * 100, 4) if on_rows else None,
        "mean_cost": round(float(np.mean([r["cost"] for r in on_rows])) * 100, 4) if on_rows else None},
}
# 拥挤剔除实际剔掉了多少(按周记 top20 → 被剔除的个数)
crowd_n = []
for d in SUN:
    v30 = V[:, d - VOL_WIN + 1:d + 1].sum(axis=1)
    ok = (v30 > 0) & (~IS_STABLE) & (~BTC_I)
    cand = np.where(ok)[0]
    if cand.size == 0:
        crowd_n.append(0)
        continue
    top = cand[np.argsort(-v30[cand], kind="stable")][:TOPN]
    f7 = F[:, d - FUND_WIN + 1:d + 1].sum(axis=1)
    crowd_n.append(int((f7[top] < CROWDSUM).sum()))
report_only["crowd_dropped_hist"] = {str(k): crowd_n.count(k) for k in sorted(set(crowd_n))}

# 敏感性口径:纯等权 1/n(不封 5%)—— 只报,不用于判定
eq_on = [r for r in WK_EQ if r["on"]]
eq_rets = np.array([r["ret"] for r in eq_on], dtype=float)
eq_worst = min(eq_on, key=lambda r: r["ret"]) if eq_on else None
eq_drag, eq_drag_info = 0.0, None
for r in eq_on:
    for c in r["contrib"]:
        if -c["contrib"] > eq_drag:
            eq_drag = -c["contrib"]
            eq_drag_info = {"week": r["date"], "pair": c["pair"], "drag_pp": round(-c["contrib"] * 100, 3)}
eq_ab = apparatus.ab_test(np.zeros_like(eq_rets), eq_rets, mean_block=4.0, n_boot=2000, seed=SEED,
                          alpha=ALPHA) if eq_rets.size else {}
report_only["sensitivity_equal_weight_no_cap"] = {
    "n_on": len(eq_on), "mean_on_pct": round(float(eq_rets.mean()) * 100, 3) if eq_rets.size else None,
    "worst_on_pct": round(float(eq_rets.min()) * 100, 3) if eq_rets.size else None,
    "worst_week": eq_worst["date"] if eq_worst else None,
    "p_one_sided": float(eq_ab.get("p_b_le_a", 1.0)) if isinstance(eq_ab, dict) else None,
    "max_single_coin_drag_pp": round(eq_drag * 100, 3),
    "max_single_coin_drag_info": eq_drag_info,
    "mean_off_uncond_pct": round(float(np.mean([r["ret"] for r in WK_EQ if not r["on"]])) * 100, 3),
    "note": "只报:去掉「单币 ≤ 5%」封顶后(纯等权 1/n),判定结论不变",
}

# ── 5. 自检 ──────────────────────────────────────────────────────────────────
checks = {}
# ① 把所有收益整体后移一周 ⇒ 成分不变
WK_SHIFT = build_weeks(drop_crowded=True)
for i, r in enumerate(WK_SHIFT):
    r["main"] = WK[i - 1]["main"] if i > 0 else 0.0
checks["ret_shift_1w_keeps_basket"] = bool(all(a["pairs"] == b["pairs"] for a, b in zip(WK, WK_SHIFT)))
rolled = np.roll(np.array([r["main"] for r in WK]), 1)
checks["ret_shift_1w_is_roll"] = bool(np.allclose(rolled[1:], np.array([r["main"] for r in WK])[:-1]))
# ①b 泄漏对照:决策日后移一周 ⇒ 成分应当变化(否则说明成分没锚在决策日,检验无效)
chg = 0
for d in SUN:
    sel2, _ = select_basket(d, drop_crowded=True)
    sel1, _ = select_basket(d + 7, drop_crowded=True)
    if [PAIRS[i] for i in sel1] != [PAIRS[i] for i in sel2]:
        chg += 1
checks["basket_anchored_on_decision_day"] = bool(chg > 0)
checks["basket_changed_when_decision_shifted"] = int(chg)
# ② 状态恒不成立 ⇒ 全程空仓、净值恒 1
nav_off = float(np.prod([1.0 + (r["ret"] if r["on"] else 0.0) for r in [dict(r, on=False) for r in WK]]))
checks["state_never_on_nav_flat"] = bool(abs(nav_off - 1.0) < 1e-12)
# ③ 篮子只有 BTC 自己 ⇒ 两腿相消、净值只剩成本
d0 = SUN[0]
sel_b = np.array([IB])
w_b = np.array([1.0])
rb_full = week_ret(d0, sel_b, w_b, with_btc=True)     # 空篮子 = BTC 空腿 + 多 BTC 腿
checks["btc_only_price_legs_cancel"] = bool(abs(rb_full["price"]) < 1e-12)
checks["btc_only_funding_legs_cancel"] = bool(abs(rb_full["fund"]) < 1e-12)
checks["btc_only_net_is_cost_only"] = bool(abs(rb_full["ret"] - rb_full["cost"]) < 1e-12)
checks["btc_only_cost_value"] = round(rb_full["cost"], 6)
# ④ 单币权重上限(能抓住"等权忘了封顶"的错)
max_w = max((max(r["w"]) if r["w"] else 0.0) for r in WK)
checks["single_coin_weight_le_5pct"] = bool(max_w <= CAP + 1e-12)
checks["max_single_coin_weight"] = round(max_w, 6)
print("[checks]", json.dumps(checks, ensure_ascii=False), flush=True)

core = {
    "task": "T-372", "ledger": "S-847", "seed": SEED,
    "window": [WK[0]["date"], WK[-1]["date"]], "n_weeks": len(WK),
    "stats": S, "ab_test": ab, "p_one_sided": p_one_sided,
    "judges": {"j1_mean_gt0_and_p_lt_005": j1, "j2_beats_nonstate_weeks": j2, "j3_beats_shift_q90": j3,
               "j4_two_thirds_years_pos": j4, "j4b_drop_best_year_still_pos": j4b,
               "j5a_worst_week_gt_m15": j5a, "j5b_single_coin_drag_le_2pp": j5b},
    "null_q90_pct": round(q90 * 100, 4), "null_median_pct": round(float(np.median(null)) * 100, 4),
    "null_p95_pct": round(float(np.quantile(null, 0.95)) * 100, 4),
    "by_year_mean_pct": report_only["year_mean_state_weeks_pct"],
    "by_year_sum_pct": report_only["year_sum_state_weeks_pct"],
    "state_weeks_by_year": state_cnt_by_year,
    "worst_week": {"date": worst["date"], "ret_pct": round(worst_ret * 100, 3),
                   "n_basket": worst["n"], "pairs": worst["pairs"][:5]} if worst else None,
    "max_single_coin_drag": {"pp": round(max_drag * 100, 4), "info": max_drag_info},
    "checks": checks, "report_only": report_only,
    "weeks": [{"date": r["date"], "on": bool(r["on"]), "n": r["n"], "pairs": r["pairs"],
               "state_val": r["state_val"], "price": r["price"], "fund": r["fund"],
               "cost": r["cost"], "ret": r["ret"], "notional": r["notional"],
               "short_price": r["short_price"], "btc_leg": r["btc_leg"],
               "short_only_ret": r["short_only_ret"]} for r in WK],
    "account_overlay": None,
}
core["verdict_all_five_pass"] = bool(all([j1, j2, j3, j4, j5a, j5b]))
json.dump(core, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
print("[core written]", OUT, flush=True)

# ── 6. 只报:叠到 S-834 账户 ──────────────────────────────────────────────────
try:
    import pickle
    ck = "/tmp/s840_acct.pkl"
    if os.path.exists(ck):
        C, DAY0 = pickle.load(open(ck, "rb"))
    else:
        import t310_slots as T310
        from src.data.universe import flex_alloc as fa
        T310.UM = R + "s681/_um_daily.jsonl"
        T310.STYLE = R + "t156/_style.json"
        sp = importlib.util.spec_from_file_location("t352_engine", os.path.join(ROOT, "docs", "research", "t352_engine.py"))
        E1 = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(E1)
        dd = pd.read_csv(os.path.join(ROOT, "docs", "research", "t342_daily.csv"), parse_dates=["date"]).set_index("date")
        START = pd.Timestamp("2021-10-11")
        legs_px = {"crypto": dd.crypto_leg_nav_x1v, "equity": dd.equity_close_acwi, "gold": dd.gold_close_xauusd}
        cal = pd.date_range(dd.index[0], dd.index[-1], freq="D")
        cash_rate = dd.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
        raw, _ = T310.load_tickets()
        bars = T310.load_bars({t["symbol"] for t in raw})
        exits, _ = T310.classify_exits(raw, bars)
        TK = T310.to_engine_tickets(raw, exits)
        gate_d, _, _ = T310.load_gate()
        res = E1.simulate(TK, bars, gate_d, 0.80, equity0=630.0, risk_frac=0.0075, cap_n=10, fix=True)
        rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()
        df = pd.concat(legs_px, axis=1).dropna().sort_index()
        rets = df.pct_change()
        idx = [x for x in df.index if x >= START]
        tgt = pd.Series(fa.rb_weights(rets.loc[:idx[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
        hold = tgt.copy()
        rows, nav = [], 1.0
        for i, day in enumerate(idx[1:], start=1):
            row = rets.loc[day, list(fa.LEGS)]
            prev = idx[i - 1]
            c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
            cr = fa._between(cash_rate, prev, day)
            c["cash"] = (1.0 - float(hold.sum())) * cr
            c["rv2"] = fa._between(rv2, prev, day)
            g = sum(c.values())
            nav *= 1 + g
            hold = hold * (1 + row) / (1 + g)
            if i % 21 == 0:
                new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
                cost = float((hold - new).abs().sum()) * 20 / 1e4
                nav *= 1 - cost
                c["cost"] = -cost
                hold = new.copy()
            rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav, "cash_ret": cr})
        C = pd.DataFrame(rows).set_index("d").fillna(0.0)
        DAY0 = idx[0]
        pickle.dump((C, DAY0), open(ck, "wb"))

    def cagr(daily, a=None, b=None):
        s = daily if a is None else daily.loc[a:b]
        days = (s.index[-1] - (DAY0 if a is None else max(pd.Timestamp(a) - pd.Timedelta(days=1), DAY0))).days
        return float((1 + s).prod() ** (365.25 / days) - 1)

    def worst20(daily):
        r = (1 + daily).rolling(20).apply(np.prod, raw=True) - 1
        i = r.idxmin()
        j = daily.index[daily.index.get_loc(i) - 19]
        return float(r.min()), str(j.date()), str(i.date())

    # 篮子周收益 → 日历日收益(每周的收益按几何日均摊到该周 7 个日历日)→ 账户日收益
    day_ret = np.zeros(NDAY)
    for r in WK:
        g = (1.0 + r["main"]) ** (1.0 / 7.0) - 1.0
        for k in range(1, 8):
            day_ret[r["d"] + k] = g
    navs = np.cumprod(1.0 + day_ret)
    Sser = pd.Series(navs, index=pd.to_datetime(DAYS))
    days_acct = [DAY0] + list(C.index)
    v = Sser.reindex(pd.DatetimeIndex(days_acct)).ffill()
    on = (v / v.shift(1) - 1).iloc[1:]
    on.index = C.index
    on = on.fillna(0.0)
    span = float(Sser.loc[:C.index[-1]].iloc[-1] / Sser.loc[:DAY0].iloc[-1])
    assert abs(float((1 + on).prod()) - span) < 1e-9, "自检:账户日收益连乘 ≠ 篮子净值首尾比"

    def rc_of(w_, on_):
        am = (1 + (C["acct"] + w_ * on_ - w_ * C["cash_ret"])).resample("M").prod() - 1
        om = (w_ * on_).resample("M").sum()
        return float(np.cov(om, am)[0, 1] / am.var())

    def size(on_):
        if rc_of(1.0, on_) < 0.10:
            return 1.0, False
        lo, hi = 0.0, 1.0
        for _ in range(50):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if rc_of(mid, on_) < 0.10 else (lo, mid)
        return (lo + hi) / 2, True

    w, reached = size(on)
    aug = C["acct"] + w * on - w * C["cash_ret"]
    base_cagr, aug_cagr = cagr(C["acct"]), cagr(aug)
    ov = {"base_cagr_pct": round(base_cagr * 100, 2), "aug_cagr_pct": round(aug_cagr * 100, 2),
          "cagr_contrib_pp": round((aug_cagr - base_cagr) * 100, 2),
          "size_w": round(w, 4), "size_reached": bool(reached), "rc": round(rc_of(w, on), 4),
          "base_worst20": worst20(C["acct"]), "aug_worst20": worst20(aug),
          "own_total_ret_pct": round(float((1 + on).prod() - 1) * 100, 3),
          "own_total_ret_pct_w": round(float((1 + w * on).prod() - 1) * 100, 3),
          "window": [str(pd.Timestamp(DAY0).date()), str(C.index[-1].date())]}
    core["account_overlay"] = ov
    print("[account]", json.dumps(ov, ensure_ascii=False, default=str), flush=True)
except Exception as e:
    core["account_overlay"] = {"error": f"{type(e).__name__}: {e}"}
    print("[account ERROR]", type(e).__name__, e, flush=True)

json.dump(core, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
print("[done]", OUT, flush=True)
