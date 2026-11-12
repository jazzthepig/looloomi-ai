"""T-360(S-835 候选二):吃反转的一类 —— S-569 / S-570 量到的两个效应做成可交易的序列,干净重跑后按 S-835 准入标准判。

  卡:tasks/T-360.json(allowed_paths: docs/research/, tasks/T-360.json)
  账:REFUTATION_LEDGER `## S-835`(准入 i–iv)、`## S-569`、`## S-570`、`## S-594`(z30 更正)、`## S-834`(账户口径)

只读:不写库、不写外部文件(除本目录产物)。用法(仓库根):
  python3 docs/research/T-360_reversal_engines.py

**规则(算之前写死)**
  z30(S-594 更正版,直接用 T-092_cache.pkl 里 `z30_meta.method = "M-559 / S-594 FIXED"`):
      r30 = log(P_t / P_{t-30});z30 = (r30 − μ)/σ,μ/σ 取该名自己过去两年(730 → 31 行前)的 30 日对数收益分布。
      每周一取样,只用 d−1 已知的信息。
  规则 A(山寨暴涨 → 相对做空):非 BTC 名 z30 ≥ 3 ⇒ t+7 收盘进场,短该名 + 等额多 BTC,对冲,持有 H 天。
      (S-569 原文测的就是这一格:30 日相对 BTC(t+7) = −16.4,90 日(t+7) = −38.7,跑输比例 0.81。)
  规则 B(主流暴跌 → 做多):BTC / ETH z30 ≤ −2 ⇒ t+7 收盘进场,做多该名,持有 H 天。
      (S-569 原文:BTC 暴跌 9 周 90 日 +10.3%(基准 +6.3);ETH 暴跌 14 周 +19.2%(+6.6)。)
  H ∈ {7, 30, 90}:7 = 卡面写的「一周」;30 / 90 = S-569 原文测过的窗口。全部报,不许只报好的那个。
  成本:单边 10 bp(每条腿的每次成交额变动 10 bp,进场与出场各一次)。资金费另记(见 FUND)。

**账户(照 S-834:RBv2 + 现金 + R-v2 叠加)**:先对上 S-834 的账户年化 +35.7%、R-v2 风险占比 0.742,再叠候选。
**尺寸**:候选调到它自己的风险贡献 = 10%(二分 w,月度 cov/var 口径同 S-834)。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import pickle
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = "docs/research"
sys.path.insert(0, HERE)
sys.path.insert(0, ".")
import t310_slots as T310                                        # noqa: E402
from src.data.universe import flex_alloc as fa                    # noqa: E402
from src.data.evaluation import apparatus as AP                  # noqa: E402

R = "/Volumes/CometCloudAI/cometcloud-local/research/"
T310.UM = R + "s681/_um_daily.jsonl"
T310.STYLE = R + "t156/_style.json"
_sp = importlib.util.spec_from_file_location("t352_engine", HERE + "/t352_engine.py")
E1 = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(E1)

OUT = os.path.join(HERE, "T-360_results.json")
CACHE = HERE + "/T-092_cache.pkl"
SEED = 20261113
N_NULL = 500
COST_BPS = 10          # 单边 10 bp
TARGET_RC = 0.10       # 候选自己的风险贡献占账户 10%
START = pd.Timestamp("2021-10-11")

# ── 1. 账户(照 S-834 的脚本逐字) ─────────────────────────────────────────────
d = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
cal = pd.date_range(d.index[0], d.index[-1], freq="D")
cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
raw, _ = T310.load_tickets()
bars = T310.load_bars({t["symbol"] for t in raw})
exits, _ = T310.classify_exits(raw, bars)
TK = T310.to_engine_tickets(raw, exits)
gate_d, _, _ = T310.load_gate()
F_, CAP_, N_ = 0.0075, 0.80, 10
res = E1.simulate(TK, bars, gate_d, CAP_, equity0=630.0, risk_frac=F_, cap_n=N_, fix=True)
rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()

df = pd.concat(legs_px, axis=1).dropna().sort_index()
rets = df.pct_change()
idx = [x for x in df.index if x >= START]
tgt = pd.Series(fa.rb_weights(rets.loc[:idx[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
hold = tgt.copy()
rows, nav = [], 1.0
between = fa._between
for i, day in enumerate(idx[1:], start=1):
    row = rets.loc[day, list(fa.LEGS)]
    prev = idx[i - 1]
    c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
    c["cash"] = (1.0 - float(hold.sum())) * between(cash_rate, prev, day)
    c["rv2"] = between(rv2, prev, day)
    g = sum(c.values())
    nav *= 1 + g
    hold = hold * (1 + row) / (1 + g)
    if i % 21 == 0:
        new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
        cost = float((hold - new).abs().sum()) * 20 / 1e4
        nav *= 1 - cost
        c["cost"] = -cost
        hold = new.copy()
    rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav, "cash_frac": 1.0 - float(pd.Series(c).abs().sum())})
C = pd.DataFrame(rows).set_index("d").fillna(0.0)
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
core = d.core_nav_1_cap_pit24.reindex(C.index).pct_change().fillna(0.0)

M = lambda x: (1 + x).resample("M").prod() - 1
Cm = pd.DataFrame({k: C[k].resample("M").sum() for k in SRC})
Am = M(C["acct"])
Km = M(core)
stress = Km <= Km.quantile(0.2)
rc_full = {k: float(np.cov(Cm[k], Am)[0, 1] / Am.var()) for k in SRC}
ent = lambda w: float(np.exp(-sum(x * math.log(x) for x in (np.clip(np.abs(np.array(list(w.values()))), 1e-9, None) / np.clip(np.abs(np.array(list(w.values()))), 1e-9, None).sum()))))
recon = {
    "window": [str(idx[0].date()), str(idx[-1].date())],
    "months": int(len(Am)),
    "acct_cagr_pct": round(float(C["nav"].iloc[-1] ** (365.25 / (idx[-1] - idx[0]).days) - 1) * 100, 1),
    "acct_vol_ann_pct": round(float(Am.std() * math.sqrt(12)) * 100, 1),
    "worst_month_pct": round(float(Am.min()) * 100, 1),
    "rv2_risk_share": round(rc_full["rv2"], 3),
    "eff_sources_entropy": round(ent(rc_full), 2),
    "risk_contrib_full": {k: round(v, 3) for k, v in rc_full.items()},
    "s834_expected": {"cagr_pct": 35.7, "rv2_risk_share": 0.742, "eff_sources": 2.0, "vol_ann_pct": 36.7, "worst_month_pct": -10.5},
}
print("RECON", json.dumps(recon, ensure_ascii=False))

# ── 2. 面板与 z30(S-594 更正版,来自 T-092_cache.pkl) ───────────────────────
with open(CACHE, "rb") as f:
    cache = pickle.load(f)
assert cache.get("z30_meta", {}).get("method", "").endswith("FIXED"), cache.get("z30_meta")
close_by_sym = cache["close_by_sym"]
z30 = cache["z30"]
rank_by_dsym = cache["rank_by_dsym"]
fund_by_d = cache["fund_by_d"]
alldates = sorted({d0 for dd in close_by_sym.values() for d0 in dd})
didx = {d0: i for i, d0 in enumerate(alldates)}
NDAYS = len(alldates)
PX = {}
for s, dd in close_by_sym.items():
    a = np.full(NDAYS, np.nan)
    for d0, v in dd.items():
        a[didx[d0]] = float(v)
    PX[s] = a
# 日收益(用主日历的前一日;缺前一日 ⇒ NaN)
RET = {s: np.full(NDAYS, np.nan) for s in PX}
for s, a in PX.items():
    prev = np.concatenate([[np.nan], a[:-1]])
    with np.errstate(invalid="ignore", divide="ignore"):
        RET[s] = np.where((prev > 0) & (a > 0), a / prev - 1.0, np.nan)
z30_min_date = min(d0 for (_, d0) in z30)
# 资金费(年化);覆盖不全的地方当 0,另报覆盖率
fund_arr = np.zeros(NDAYS)
fund_cov = np.zeros(NDAYS)
for d0, v in (fund_by_d or {}).items():
    if d0 in didx:
        if v is None:
            continue
        fund_arr[didx[d0]] = float(v)
        fund_cov[didx[d0]] = 1.0

MOND = [x for x in alldates if pd.Timestamp(x).weekday() == 0]
_fv = fund_arr[fund_cov > 0]
print("PANEL", json.dumps({"symbols": len(close_by_sym), "dates": [alldates[0], alldates[-1]], "z30_entries": len(z30),
                           "z30_first": z30_min_date, "fund_days": int(fund_cov.sum()),
                           "fund_ann_median": (round(float(np.median(_fv)), 5) if len(_fv) else None),
                           "fund_ann_p10_p90": ([round(float(np.quantile(_fv, 0.1)), 5), round(float(np.quantile(_fv, 0.9)), 5)] if len(_fv) else None)},
                          ensure_ascii=False))

# ── 3. 两条规则的票 ─────────────────────────────────────────────────────────
def dplus(d0, n):
    i = didx[d0] + n
    return alldates[i] if 0 <= i < NDAYS else None


def rule_a_events(H, min_rank=None):
    """非 BTC 名 z30 ≥ 3 ⇒ t+7 进场,短该名 + 多 BTC(等额),持 H 天。"""
    ev = []
    for t in MOND:
        if z30_min_date > t:
            continue
        for s in close_by_sym:
            if s == "BTC":
                continue
            z = z30.get((s, t))
            if z is None or z < 3:
                continue
            if min_rank is not None:
                r = rank_by_dsym.get((t, s))
                if r is None or r <= min_rank:
                    continue
            ev.append({"t": t, "sym": s, "z": float(z), "rank": rank_by_dsym.get((t, s))})
    return ev


def rule_b_events(H, syms=("BTC", "ETH")):
    """BTC / ETH z30 ≤ −2 ⇒ t+7 进场,做多该名,持 H 天。"""
    ev = []
    for t in MOND:
        if z30_min_date > t:
            continue
        for s in syms:
            z = z30.get((s, t))
            if z is None or z > -2:
                continue
            ev.append({"t": t, "sym": s, "z": float(z)})
    return ev


def build_series(ev, kind, H, use_funding=False):
    """日收益序列(单位:每张票名义 1,规则 A 毛敞口 2 / 规则 B 毛敞口 1)。"""
    ser = defaultdict(float)
    detail = []
    for e in ev:
        s = e["sym"]
        E = dplus(e["t"], 7)          # t+7 收盘进场
        if E is None:
            continue
        ie, xe = didx[E], didx.get(dplus(E, H), didx[alldates[-1]])
        # 名在窗口内消失 ⇒ 截到最后一个有价的日子
        last = xe
        for i in range(ie, xe + 1):
            if not (np.isnan(PX[s][i])):
                last = i
        died = last < xe
        xe = last
        if xe < ie:
            continue
        for i in range(ie, xe + 1):
            if i == ie:
                continue                # 进场当日的收益不归我们(收盘价成交)
            rs = RET[s][i]
            if np.isnan(rs):
                continue
            if kind == "A":
                rb = RET["BTC"][i]
                if np.isnan(rb):
                    continue
                v = float(rb - rs)
                if use_funding:
                    v -= fund_arr[i] / 365.0        # 多 BTC 一条腿付资金费
            else:
                v = float(rs)
                if use_funding:
                    v -= fund_arr[i] / 365.0 if s == "BTC" else 0.0
            ser[alldates[i]] += v
        # 成本:进场与出场各一次,每条腿 10 bp
        n_legs = 2 if kind == "A" else 1
        ser[alldates[ie]] -= COST_BPS / 1e4 * n_legs
        ser[alldates[xe]] -= COST_BPS / 1e4 * n_legs
        detail.append({"t": e["t"], "sym": s, "z": e.get("z"), "entry": alldates[ie], "exit": alldates[xe],
                       "died": bool(died), "ret": None})
    srs = pd.Series(ser).sort_index()
    return srs, detail


def cum(srs, a, b):
    x = srs[(srs.index >= a) & (srs.index <= b)]
    return float((1 + x).prod() - 1) if len(x) else 0.0


def ann(srs, a, b):
    x = srs[(srs.index >= a) & (srs.index <= b)]
    if len(x) < 30:
        return None
    yrs = (pd.Timestamp(x.index[-1]) - pd.Timestamp(x.index[0])).days / 365.25
    return float((1 + x).prod() ** (1 / yrs) - 1)


# ── 4. 准入标准 (i)–(iv) ───────────────────────────────────────────────────
ACCT_CAL = list(C.index)                 # 账户日历(2021-10-12 起)
A0 = str(idx[0].date())
A1 = str(idx[-1].date())


# 账户里现金腿的日收益率:直接用 cash_rate 在 (prev, day] 上的复利(与 C["cash"] 同源)
_cash_btw = {}
for i, day in enumerate(idx[1:], start=1):
    _cash_btw[day] = between(cash_rate, idx[i - 1], day)
CASH_RET = pd.Series(_cash_btw).reindex(C.index).fillna(0.0)


def acct_new(w, cand_on_acct):
    """账户 + 候选(候选由现金供资,付掉那份现金的利息)。"""
    return C["acct"] + w * cand_on_acct - w * CASH_RET


def rc_of(w, cand_on_acct):
    an = acct_new(w, cand_on_acct)
    Amn = M(an)
    cm = (w * cand_on_acct).resample("M").sum()
    if Amn.var() == 0 or len(Amn) < 12:
        return None
    return float(np.cov(cm, Amn)[0, 1] / Amn.var())


def bisect_w(cand_on_acct, target=TARGET_RC, lo=0.0, hi=50.0, it=60):
    f_lo = rc_of(lo, cand_on_acct)
    f_hi = rc_of(hi, cand_on_acct)
    if f_lo is None or f_hi is None or f_hi < target:
        return None
    for _ in range(it):
        mid = (lo + hi) / 2
        fm = rc_of(mid, cand_on_acct)
        if fm is None:
            return None
        if fm < target:
            lo = mid
        else:
            hi = mid
    return hi


def monthly_corr(a, b):
    if len(a) < 12 or len(b) < 12:
        return None
    v = float(a.corr(b))
    return None if (v is None or math.isnan(v)) else round(v, 3)


def null_p_upper(srs, stat, n=N_NULL, seed=SEED):
    """apparatus.circular_shift(整条序列,block=1)×n ⇒ 单侧 p_upper。"""
    vals = srs.values
    actual = stat(vals)
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(n):
        null.append(stat(AP.circular_shift(vals, rng, block=1)))
    return actual, AP.p_upper(actual, null), float(np.nanmedian(null))


def evaluate(variant, srs, ev, kind, H, a_lo, a_hi, use_funding=False):
    """对一个候选序列做完整的 (i)–(iv)。"""
    out = {"variant": variant, "kind": kind, "H": H, "events": len(ev), "use_funding": use_funding}
    # 票数逐年
    yr = defaultdict(int)
    for e in ev:
        yr[e["t"][:4]] += 1
    out["events_per_year"] = dict(sorted(yr.items()))
    # 事件窗口内的收益(单位名义)
    out["total_ret_pct"] = round(cum(srs, a_lo, a_hi) * 100, 2)
    out["total_ret_full_pct"] = round(cum(srs, z30_min_date, a_hi) * 100, 2)
    out["ann_pct"] = None if ann(srs, a_lo, a_hi) is None else round(ann(srs, a_lo, a_hi) * 100, 2)
    out["active_days"] = int(((srs.index >= a_lo) & (srs.index <= a_hi)).sum())
    # (ii) 自己的贡献为正 + circular_shift p_upper
    actual, p, med = null_p_upper(srs.loc[(srs.index >= a_lo) & (srs.index <= a_hi)],
                                   lambda v: float(np.prod(1 + v) - 1))
    out["self_total_ret_pct"] = round(actual * 100, 2)
    out["p_upper"] = None if p is None else round(float(p), 4)
    out["null_median_pct"] = round(med * 100, 2)
    out["ii_positive"] = bool(actual > 0)
    out["ii_p"] = bool(p is not None and p < 0.10)
    out["ii_pass"] = bool(out["ii_positive"] and out["ii_p"])
    # 叠到账户上
    on_acct = srs.reindex(C.index).fillna(0.0)
    w = bisect_w(on_acct)
    out["w"] = None if w is None else round(w, 6)
    if w is None:
        out["error"] = "无法把风险贡献调到 10%"
        return out
    out["rc_achieved"] = round(rc_of(w, on_acct), 3)
    an = acct_new(w, on_acct)
    Amn = M(an)
    # (i) 月度相关:与账户、与 R-v2;全样本与压力月
    cand_m = (w * on_acct).resample("M").sum()
    rv2_m = Cm["rv2"]
    cm_acct = Cm.sum(axis=1)   # 账户(旧口径的贡献和)
    out["corr_acct_full"] = monthly_corr(cand_m, Amn)
    out["corr_rv2_full"] = monthly_corr(cand_m, rv2_m)
    out["corr_acct_stress"] = monthly_corr(cand_m[stress], Amn[stress])
    out["corr_rv2_stress"] = monthly_corr(cand_m[stress], rv2_m[stress])
    ok = [out["corr_acct_full"], out["corr_rv2_full"], out["corr_acct_stress"], out["corr_rv2_stress"]]
    out["i_pass"] = bool(all(v is not None and v < 0.30 for v in ok))
    out["corrs"] = {"acct_full": out["corr_acct_full"], "rv2_full": out["corr_rv2_full"],
                    "acct_stress": out["corr_acct_stress"], "rv2_stress": out["corr_rv2_stress"]}
    # (iii) 账户最差 20 日不变差 + 有效来源数上升
    r20_old = (1 + C["acct"]).rolling(20).apply(np.prod) - 1
    r20_new = (1 + an).rolling(20).apply(np.prod) - 1
    out["worst20_old_pct"] = round(float(r20_old.min()) * 100, 2)
    out["worst20_new_pct"] = round(float(r20_new.min()) * 100, 2)
    out["iii_worst20_ok"] = bool(out["worst20_new_pct"] >= out["worst20_old_pct"] - 1e-9)
    rc_new = dict(rc_full)
    rc_new["cand"] = out["rc_achieved"]
    out["eff_sources_old"] = round(ent(rc_full), 2)
    out["eff_sources_new"] = round(ent(rc_new), 2)
    ev_old = np.linalg.eigvalsh(Cm.corr().values)
    ev_new = np.linalg.eigvalsh(pd.DataFrame({**{k: Cm[k] for k in SRC}, "cand": cand_m}).corr().fillna(0).values)
    out["eig_pr_old"] = round(float(ev_old.sum() ** 2 / (ev_old ** 2).sum()), 2)
    out["eig_pr_new"] = round(float(ev_new.sum() ** 2 / (ev_new ** 2).sum()), 2)
    out["iii_eff_ok"] = bool(out["eff_sources_new"] > out["eff_sources_old"])
    out["iii_pass"] = bool(out["iii_worst20_ok"] and out["iii_eff_ok"])
    # 核心:R-v2 输的那些月,候选赚不赚
    rv2_m_sorted = rv2_m.sort_values()
    worst12 = rv2_m_sorted.index[:12]
    out["cand_in_rv2_worst12_months_pct"] = round(float(cand_m[worst12].mean()) * 100, 3)
    out["rv2_in_its_worst12_months_pct"] = round(float(rv2_m[worst12].mean()) * 100, 3)
    out["cand_2023_02_to_03_08_pct"] = round(cum(w * on_acct, "2023-02-08", "2023-03-08") * 100, 2)
    e20 = r20_old.idxmin()
    s20 = C.index[max(0, C.index.get_loc(e20) - 19)]
    out["worst20d_window"] = [str(s20.date()), str(e20.date())]
    out["cand_in_worst20d_window_pct"] = round(cum(w * on_acct, str(s20.date()), str(e20.date())) * 100, 2)
    out["rv2_in_worst20d_window_pct"] = round(float(C["rv2"].loc[str(s20.date()):str(e20.date())].sum()) * 100, 2)
    # (iv) 两个窗口同向:候选自身的结论
    w1 = evaluate_window(srs, z30_min_date, a_hi)
    w2 = evaluate_window(srs, A0, a_hi)
    out["window1"] = w1
    out["window2"] = w2
    out["iv_same_sign"] = bool(w1["verdict"] == w2["verdict"])
    out["iv_pass"] = bool(out["iv_same_sign"])
    out["all_pass"] = bool(out["i_pass"] and out["ii_pass"] and out["iii_pass"] and out["iv_pass"])
    return out


def evaluate_window(srs, a, b):
    x = srs[(srs.index >= a) & (srs.index <= b)]
    if len(x) < 60:
        return {"window": [a, b], "n": int(len(x)), "verdict": None, "note": "样本不足"}
    actual, p, _ = null_p_upper(x, lambda v: float(np.prod(1 + v) - 1))
    verdict = "pass" if (actual > 0 and p is not None and p < 0.10) else "fail"
    return {"window": [a, b], "n": int(len(x)), "total_ret_pct": round(actual * 100, 2),
            "p_upper": None if p is None else round(float(p), 4), "verdict": verdict}


# ── 5. 跑 ───────────────────────────────────────────────────────────────────
variants = []
for H in (7, 30, 90):
    ev = rule_a_events(H)
    srs, det = build_series(ev, "A", H)
    variants.append(evaluate(f"A_all_H{H}", srs, ev, "A", H, A0, A1))
    if H == 30:
        ev_r = rule_a_events(H, min_rank=30)
        srs_r, det_r = build_series(ev_r, "A", H)
        variants.append(evaluate("A_rank_gt30_H30", srs_r, ev_r, "A", H, A0, A1))
        srs_f, _ = build_series(ev, "A", H, use_funding=True)
        variants.append(evaluate(f"A_all_H{H}_fund", srs_f, ev, "A", H, A0, A1))
for H in (7, 30, 90):
    ev = rule_b_events(H)
    srs, det = build_series(ev, "B", H)
    variants.append(evaluate(f"B_btceth_H{H}", srs, ev, "B", H, A0, A1))
    if H == 30:
        for one in ("BTC", "ETH"):
            ev1 = rule_b_events(H, syms=(one,))
            srs1, _ = build_series(ev1, "B", H)
            variants.append(evaluate(f"B_{one}_H{H}", srs1, ev1, "B", H, A0, A1))
        srs_f, _ = build_series(ev, "B", H, use_funding=True)
        variants.append(evaluate(f"B_btceth_H{H}_fund", srs_f, ev, "B", H, A0, A1))

summary = []
for v in variants:
    summary.append({k: v.get(k) for k in ("variant", "kind", "H", "events", "events_per_year", "total_ret_pct",
                                           "total_ret_full_pct", "ann_pct",
                                           "self_total_ret_pct", "p_upper", "null_median_pct", "w", "rc_achieved",
                                           "corrs", "i_pass", "ii_pass", "iii_pass", "iv_pass", "all_pass",
                                           "worst20_old_pct", "worst20_new_pct", "eff_sources_old", "eff_sources_new",
                                           "eig_pr_old", "eig_pr_new", "cand_in_rv2_worst12_months_pct",
                                           "rv2_in_its_worst12_months_pct", "worst20d_window",
                                           "cand_in_worst20d_window_pct", "rv2_in_worst20d_window_pct",
                                           "window1", "window2", "error")})
    print("VAR", json.dumps(summary[-1], ensure_ascii=False))

out = {"recon": recon, "panel": {"symbols": len(close_by_sym), "z30_first": z30_min_date, "z30_meta": cache.get("z30_meta"),
                                  "fund_days": int(fund_cov.sum())},
       "variants": summary,
       "account": {"start": A0, "end": A1, "months": int(len(Am)), "acct_cagr_pct": recon["acct_cagr_pct"]}}
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
print("WROTE", OUT)
