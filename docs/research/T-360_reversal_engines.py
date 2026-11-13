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
  H ∈ {7, 20, 30, 45, 90}:7 = 卡面写的「一周」;30 / 90 = S-569 原文测过的窗口;20 / 45 = 新加的邻点。全部报,不许只报好的那个。
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
from src.data.evaluation import ticket_account as TA             # noqa: E402

R = "/Volumes/CometCloudAI/cometcloud-local/research/"
T310.UM = R + "s681/_um_daily.jsonl"
T310.STYLE = R + "t156/_style.json"
_sp = importlib.util.spec_from_file_location("t352_engine", HERE + "/t352_engine.py")
E1 = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(E1)

OUT = os.environ.get("T360_OUT") or os.path.join(HERE, "T-360_results.json")
VERIFY_OUT = os.environ.get("T360_VERIFY_OUT") or os.path.join(HERE, "T-360_verify.json")
CACHE = HERE + "/T-092_cache.pkl"
SEED = 20261113
N_NULL = int(os.environ.get("T360_N_NULL", 500))
# 本轮(2026-11-13 返工)只跑子集:持有期档位与规则可由环境变量覆盖,
#   T360_H_A="20,30,45"  T360_RULE_B=0  T360_N_NULL=50
H_A = tuple(int(x) for x in os.environ.get("T360_H_A", "7,20,30,45,90").split(","))
RUN_B = os.environ.get("T360_RULE_B", "1") not in ("0", "false", "False")
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


def _fwd(s, i0, days):
    """自 i0 收盘起 forward `days` 个日历日的对数收益(主日历为界);缺价 ⇒ None。"""
    j = didx.get(dplus(alldates[i0], days))
    if j is None:
        j = NDAYS - 1
    p0, p1 = PX[s][i0], PX[s][j]
    if np.isnan(p0) or np.isnan(p1) or p0 <= 0 or p1 <= 0:
        return None
    return float(math.log(p1 / p0))


def _hold(s, ie, xe):
    """持有期实现收益(简单收益)。"""
    p0, p1 = PX[s][ie], PX[s][xe]
    if np.isnan(p0) or np.isnan(p1) or p0 <= 0:
        return None
    return float(p1 / p0 - 1.0)


def build_book_ta(ev, H, use_funding=False):
    """规则 B 的逐日账本走 `src/data/evaluation/ticket_account.py`(11-13 进 main 的那台:有不变量、有测试)。

    口径与账户腿一致:每票名义 = 开盘净值 × risk_frac ÷ stop_frac(0.0075 / 5%),名额 10,毛上限 0.80,
    来回成本 10 bp(手写版是单边 10 bp,同量)。
    **规则 A 用不到它**:规则 A 的空头腿(空山寨)这个库做不了(只做多)⇒ 规则 A 仍走下面的手写
    等权两腿账本(每票名义不叠加)。
    """
    eng, tks = [], []
    for k, e in enumerate(ev):
        s = e["sym"]
        E = dplus(e["t"], 7)
        if E is None:
            continue
        ie = didx[E]
        xe_sched = didx.get(dplus(E, H), didx[alldates[-1]])
        xe = xe_sched
        for i in range(ie, xe + 1):
            if not np.isnan(PX[s][i]):
                xe = i
        if xe < ie:
            continue
        p0, p1 = PX[s][ie], PX[s][xe]
        if np.isnan(p0) or np.isnan(p1) or p0 <= 0:
            continue
        eng.append({"tid": f"B{k}", "symbol": s, "signal_d": e["t"],
                    "entry_d": alldates[ie], "entry_px": float(p0), "stop_px": float(p0) * 0.95,
                    "exit_d": alldates[xe], "exit_px": float(p1), "exit_reason": "expiry"})
        tks.append({"sym": s, "t": e["t"], "z": e.get("z"), "ie": ie, "xe": xe,
                    "died": bool(xe < xe_sched), "entry": alldates[ie], "exit": alldates[xe],
                    "fwd30": _fwd(s, ie, 30), "fwd90": _fwd(s, ie, 90),
                    "fwd30_rel": None, "fwd90_rel": None, "hold_ret": _hold(s, ie, xe)})
    if not eng:
        return pd.Series(dtype=float), tks
    bars = {}
    for s in {t["symbol"] for t in eng}:
        rows = []
        for d0 in alldates:
            v = PX[s][didx[d0]]
            if not np.isnan(v):
                rows.append([d0, float(v), float(v), float(v), float(v)])
        bars[s] = rows
    mark = TA.marks_from_bars(bars)
    res = TA.simulate(eng, mark, risk_frac=F_, gross_cap=CAP_, cap_n=N_, equity0=1.0,
                      cost=2 * COST_BPS / 1e4, min_notional=0.0, strict=False)
    curve = res.get("curve") or []
    nav = pd.Series({r[0]: float(r[1]) for r in curve}).sort_index()
    srs = nav.pct_change().fillna(0.0).reindex(alldates).fillna(0.0)
    print("TA_B", json.dumps({"H": H, "tickets": len(eng), "taken": len(res.get("taken") or []),
                              "blocked": {k: len(vv) for k, vv in (res.get("blocked") or {}).items()},
                              "nav_end": float(nav.iloc[-1]) if len(nav) else None}, ensure_ascii=False), flush=True)
    return srs, tks


def build_book(ev, kind, H, use_funding=False):
    """固定毛敞口的日收益序列(每条规则一条)。

    规则 A:毛 2 —— 多 BTC 一篮(权重 1)+ 空山寨一篮(权重 1,活跃票等权)
    规则 B:毛 1 —— 做多该名一篮(权重 1,活跃票等权)
    同日 N 张活跃票各占 1/N ⇒ 总毛敞口恒定,**不叠名义**(上一轮 −100% 的记账假象由此消除:
    上一轮每张票按名义 1 直接相加,并发 10 张 ⇒ 毛敞口冲到 10,一只山寨翻倍就把复利打成负数)。
    成本:每日权重变动(新开仓按满额计) × 单边 10 bp;规则 A 的多 BTC 一篮只在「有票 ↔ 无票」时变动。
    """
    if kind == "B":
        try:
            return build_book_ta(ev, H, use_funding=use_funding)
        except Exception as _e:
            print("TA_FALLBACK", repr(_e), flush=True)
    tickets = []
    for e in ev:
        s = e["sym"]
        E = dplus(e["t"], 7)          # t+7 收盘进场
        if E is None:
            continue
        ie = didx[E]
        xe = didx.get(dplus(E, H), didx[alldates[-1]])
        last = xe                     # 名在窗口内消失 ⇒ 截到最后一个有价的日子
        for i in range(ie, xe + 1):
            if not np.isnan(PX[s][i]):
                last = i
        died = last < xe
        xe = last
        if xe < ie:
            continue
        rets = []
        for i in range(ie + 1, xe + 1):   # 进场当日的收益不归我们(收盘价成交)
            rs = RET[s][i]
            if np.isnan(rs):
                rets.append(None)
                continue
            if kind == "A":
                rb = RET["BTC"][i]
                if np.isnan(rb):
                    rets.append(None)
                    continue
                v = float(rb - rs)
                if use_funding:
                    v -= fund_arr[i] / 365.0        # 多 BTC 一条腿付资金费
            else:
                v = float(rs)
                if use_funding and s == "BTC":
                    v -= fund_arr[i] / 365.0
            rets.append(v)
        tk = {"sym": s, "t": e["t"], "z": e.get("z"), "ie": ie, "xe": xe, "died": bool(died),
              "entry": alldates[ie], "exit": alldates[xe], "rets": rets}
        # 事件级前瞻统计(S-569 口径:自 t+7 收盘起)
        f30, f90 = _fwd(s, ie, 30), _fwd(s, ie, 90)
        tk["fwd30"] = f30
        tk["fwd90"] = f90
        if kind == "A":
            b30, b90 = _fwd("BTC", ie, 30), _fwd("BTC", ie, 90)
            tk["fwd30_rel"] = None if (f30 is None or b30 is None) else f30 - b30
            tk["fwd90_rel"] = None if (f90 is None or b90 is None) else f90 - b90
            h_alt, h_btc = _hold(s, ie, xe), _hold("BTC", ie, xe)
            tk["hold_rel"] = None if (h_alt is None or h_btc is None) else (1 + h_btc) / (1 + h_alt) - 1.0
        else:
            tk["fwd30_rel"] = None
            tk["fwd90_rel"] = None
            tk["hold_ret"] = _hold(s, ie, xe)
        tickets.append(tk)

    # 逐日:活跃票、权重、换手
    active_by_day = defaultdict(list)
    for k, tk in enumerate(tickets):
        for j, i in enumerate(range(tk["ie"] + 1, tk["xe"] + 1)):
            active_by_day[i].append((k, j))
    ser = {}
    prev_w = {}
    for i in range(NDAYS):
        act = active_by_day.get(i, [])
        N = len(act)
        ret_day, w_now = 0.0, {}
        for (k, j) in act:
            w = 1.0 / N if N else 0.0
            w_now[k] = w
            v = tickets[k]["rets"][j]
            if v is None:
                continue
            ret_day += w * v
        turn = 0.0
        for k, w in w_now.items():
            turn += abs(w - prev_w.get(k, 0.0))
        for k in prev_w:
            if k not in w_now:
                turn += prev_w[k]
        if kind == "A":
            btc_w = 1.0 if N > 0 else 0.0
            turn += abs(btc_w - (1.0 if prev_w else 0.0))
        ser[alldates[i]] = ret_day - COST_BPS / 1e4 * turn
        prev_w = w_now
    srs = pd.Series(ser).sort_index()
    return srs, tickets


def bench_weekly(sym, days):
    """S-569 的「全部周」基准:面板内每个周一的 forward `days` 对数收益均值。"""
    v = []
    for t in MOND:
        if z30_min_date > t:
            continue
        i = didx.get(t)
        if i is None:
            continue
        f = _fwd(sym, i, days)
        if f is not None:
            v.append(f)
    return (float(np.mean(v)), len(v)) if v else (None, 0)


def event_stats(tickets, kind):
    """事件级统计(S-569 口径):每张票的前瞻收益与跑输比例。"""
    n = len(tickets)
    if not n:
        return {"tickets": 0}
    out = {"tickets": n, "names": len({t["sym"] for t in tickets}),
           "died_early": sum(1 for t in tickets if t["died"])}
    if kind == "A":
        rel30 = [t["fwd30_rel"] for t in tickets if t["fwd30_rel"] is not None]
        rel90 = [t["fwd90_rel"] for t in tickets if t["fwd90_rel"] is not None]
        hold = [t["hold_rel"] for t in tickets if t["hold_rel"] is not None]
        out["fwd30_rel_pct"] = round(float(np.mean(rel30)) * 100, 2) if rel30 else None
        out["fwd90_rel_pct"] = round(float(np.mean(rel90)) * 100, 2) if rel90 else None
        out["underperform30_ratio"] = round(float(np.mean([1.0 if x < 0 else 0.0 for x in rel30])), 3) if rel30 else None
        out["underperform90_ratio"] = round(float(np.mean([1.0 if x < 0 else 0.0 for x in rel90])), 3) if rel90 else None
        out["hold_rel_pct"] = round(float(np.mean(hold)) * 100, 2) if hold else None
        out["hold_rel_win_ratio"] = round(float(np.mean([1.0 if x > 0 else 0.0 for x in hold])), 3) if hold else None
        out["per_year"] = {y: sum(1 for t in tickets if t["t"][:4] == y)
                           for y in sorted({t["t"][:4] for t in tickets})}
    else:
        for sym in sorted({t["sym"] for t in tickets}):
            f90 = [t["fwd90"] for t in tickets if t["sym"] == sym and t["fwd90"] is not None]
            f30 = [t["fwd30"] for t in tickets if t["sym"] == sym and t["fwd30"] is not None]
            if not f90:
                continue
            bm90, n_bm = bench_weekly(sym, 90)
            out[sym] = {"tickets": len(f90), "fwd90_pct": round(float(np.mean(f90)) * 100, 2),
                        "fwd30_pct": round(float(np.mean(f30)) * 100, 2) if f30 else None,
                        "bench90_pct": round(bm90 * 100, 2) if bm90 is not None else None,
                        "lower_after90_ratio": round(float(np.mean([1.0 if x < 0 else 0.0 for x in f90])), 3)}
        out["per_year"] = {y: sum(1 for t in tickets if t["t"][:4] == y)
                           for y in sorted({t["t"][:4] for t in tickets})}
    return out


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


def srs_on_acct(srs, acct_idx):
    """把 crypto 日历(7×24)的候选日收益聚到账户日历(工作日)上。

    **口径(2026-11-13 更正,Seth §Seth-1113e)**:账户腿(equity/gold)的工作日收益是
    「上个工作日收盘 → 本工作日收盘」,**含周末漂移**;候选序列必须同口径。
    上一版写的是 `u = g.index.union(acct_idx); gg / gg.shift(1)` —— 账户日**都是加密日** ⇒ `u` 就是加密日历
    ⇒ `shift(1)` 取的是**前一个加密日**(周五→周日的单日收益),周末那一段照样被丢 ⇒ 改完数字逐位不变
    (实测:链式复利 +122.63% vs 候选全日历 −44.54%)。
    正确做法:`ga = gg.reindex(acct_idx); on_acct = ga / ga.shift(1) − 1`
    —— 相邻两个**账户日**之间的全部加密日都计入(含周末);
    首个账户日的基准取它**之前最后一个加密日**的 g(没有 ⇒ 该日记 0)。
    """
    sdt = pd.Series(np.asarray(srs.values, dtype=float),
                    index=pd.to_datetime(pd.Index(srs.index))).sort_index()
    sdt = sdt[~sdt.index.duplicated(keep="last")]
    g = (1.0 + sdt.fillna(0.0)).cumprod()
    u = g.index.union(acct_idx)
    gg = g.reindex(u).ffill()
    ga = gg.reindex(acct_idx)              # 账户日上的 g
    prev = ga.shift(1)                     # 上一个**账户日**的 g
    first = acct_idx[0]
    base = g[g.index < first]              # 首个账户日之前最后一个加密日
    prev.iloc[0] = float(base.iloc[-1]) if len(base) else 1.0
    ratio = (ga / prev - 1.0).fillna(0.0)
    # 口径自检(2026-11-13):链式复利必须 == 「末个账户日的 g ÷ 首个账户日的基准 g」。
    # 不过就抛 —— 周末漂移、基准取错、账户日错位都会在这里露出来
    #(旧口径实测:链 +122.63% vs 全日历参考 −44.54%)。
    base_g = float(prev.iloc[0]) if len(prev) else float("nan")
    end_g = float(ga.iloc[-1]) if len(ga) else float("nan")
    if bool(ga.notna().all()) and np.isfinite(base_g) and base_g != 0.0 and np.isfinite(end_g):
        got = float((1.0 + ratio).prod())
        exp = end_g / base_g
        if not abs(got - exp) < 1e-9:
            raise AssertionError(
                f"srs_on_acct 口径自检失败: chain={got!r} expected={exp!r} "
                f"(base_g={base_g!r} end_g={end_g!r})")
    return ratio


def chain_selfcheck(srs, acct_idx):
    """自检:账户日聚合后的**链式复利** == 候选在同一区间的**全日历复利**。

    链式:`(1+on_acct).prod()` = g(末个账户日)/g(基准日)(基准日 = 首个账户日之前最后一个加密日);
    参考:直接在加密日历上把 (1+r) 连乘一遍,取 (基准日, 末个账户日] 区间的加密日。
    两者独立算,差 < 1e-9 才算口径对齐 —— 旧口径实测链 +122.63% vs 参考 −44.54% ⇒ 被拦下。
    """
    sdt = pd.Series(np.asarray(srs.values, dtype=float),
                    index=pd.to_datetime(pd.Index(srs.index))).sort_index()
    sdt = sdt[~sdt.index.duplicated(keep="last")]
    g = (1.0 + sdt.fillna(0.0)).cumprod()
    first, last = acct_idx[0], acct_idx[-1]
    bi = g.index[g.index < first]
    base_date = bi[-1] if len(bi) else None
    chain = float((1.0 + srs_on_acct(srs, acct_idx)).prod())
    if base_date is not None:
        sel = sdt[(sdt.index > base_date) & (sdt.index <= last)]
        incl = sdt[(sdt.index >= first) & (sdt.index <= last)]
    else:
        sel = sdt[sdt.index <= last]
        incl = sel
    ref = float((1.0 + sel).prod()) if len(sel) else 1.0
    ref_incl = float((1.0 + incl).prod()) if len(incl) else 1.0
    return {"baseline_date": str(base_date.date()) if base_date is not None else None,
            "chain_cum": chain, "ref_cum_fullcal": ref, "diff_abs": abs(chain - ref),
            "ref_cum_incl_first_acct_day": ref_incl,
            "n_crypto_days_in_ref": int(len(sel)),
            "pass": bool(abs(chain - ref) < 1e-9)}


def rc_of(w, cand_on_acct):
    """候选占账户风险的份额:月度 cov(候选贡献, 账户) / var(账户)(同 S-834 口径)。"""
    if w <= 0:
        return 0.0
    x = 1.0 + w * cand_on_acct.values          # 复利守卫:月度连乘不得翻号
    if np.nanmin(x) <= 0:
        return None
    an = acct_new(w, cand_on_acct)
    Amn = M(an)
    cm = (w * cand_on_acct).resample("M").sum()
    if len(Amn) < 12:
        return None
    if Amn.var() == 0:
        return 0.0
    return float(np.cov(cm, Amn)[0, 1] / Amn.var())


def bisect_w(cand_on_acct, target=TARGET_RC, hi=1.0, it=40):
    """解出使风险贡献 = target 的账户权重 w。

    上界 = 1.0(资金倍数 1 倍;C 道口径:资金倍数超 1 倍写「尺寸不可行」,不算过)。
    上一轮上界 50 让 1+w·c 变号、月度连乘失真 ⇒ rc 判不出 10%,这里先收缩到复利不翻号的点再二分。
    """
    whi = hi
    while whi > 1e-6 and rc_of(whi, cand_on_acct) is None:
        whi *= 0.5
    if whi <= 1e-6:
        return None
    f_hi = rc_of(whi, cand_on_acct)
    if f_hi is None:
        return None
    if f_hi < target:
        return None
    lo = 0.0
    for _ in range(it):
        mid = (lo + whi) / 2
        fm = rc_of(mid, cand_on_acct)
        if fm is None:
            whi = mid
            continue
        if fm < target:
            lo = mid
        else:
            whi = mid
    return whi


def monthly_corr(a, b):
    if len(a) < 12 or len(b) < 12:
        return None
    v = float(a.corr(b))
    return None if (v is None or math.isnan(v)) else round(v, 3)


def acct_cagr(daily, a, b):
    x = daily[(daily.index >= a) & (daily.index <= b)]
    if len(x) < 60:
        return None
    yrs = (pd.Timestamp(x.index[-1]) - pd.Timestamp(x.index[0])).days / 365.25
    if yrs <= 0:
        return None
    return float((1 + x).prod() ** (1 / yrs) - 1)


def stat_contrib(cand_on_acct, w, a, b):
    """候选对账户的贡献:账户年化(有候选) − 账户年化(无候选),单位 pp。

    **必须是对齐型统计量**:`apparatus.circular_shift` 是整条序列的循环平移,**保留日收益的多重集**,
    所以任何只依赖多重集的量(候选自己的总收益、Sharpe、平均日收益)在零分布里完全不变
    ⇒ 上一轮实测总收益的 p_upper 恒为 1.0,判据对谁都过不了。账户层面的贡献依赖
    「候选的收益落在哪一天」⇒ 平移会改变它 ⇒ 零分布才有意义。
    """
    c0 = acct_cagr(C["acct"], a, b)
    c1 = acct_cagr(acct_new(w, cand_on_acct), a, b)
    if c0 is None or c1 is None:
        return None
    return (c1 - c0) * 100.0


def null_p_upper_acct(cand_on_acct, w, a, b, n=N_NULL, seed=SEED, resize=False):
    """apparatus.circular_shift(候选日收益序列,block=1)×n ⇒ 账户贡献的单侧 p_upper。

    **尺寸固定**(resize=False):循环平移保留日收益多重集 ⇒ 候选自身的波动幅度不变 ⇒ 风险贡献不变,
    重调尺寸没有意义,而且每次平移都要重跑一遍二分(成本 ~40×)。
    """
    vals = cand_on_acct.values
    actual = stat_contrib(cand_on_acct, w, a, b)
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(n):
        sh = pd.Series(AP.circular_shift(vals, rng, block=1), index=cand_on_acct.index)
        ww = w
        if resize:
            ww = bisect_w(sh, it=20)
            if ww is None:
                continue
        v = stat_contrib(sh, ww, a, b)
        if v is not None:
            null.append(v)
    med = float(np.nanmedian(null)) if null else None
    return actual, AP.p_upper(actual, null), med, len(null)


def null_p_upper_self(srs, stat, n=N_NULL, seed=SEED):
    """字面读法的零分布(候选自己的总收益)—— 保留用于**展示它退化**,不作为判据。"""
    vals = srs.values
    actual = stat(vals)
    rng = np.random.default_rng(seed)
    null = [stat(AP.circular_shift(vals, rng, block=1)) for _ in range(n)]
    return actual, AP.p_upper(actual, null), float(np.nanmedian(null))


def evaluate(variant, srs, ev, kind, H, a_lo, a_hi, use_funding=False, skip_null=False):
    """在一个窗口 (a_lo, a_hi) 上做 (i)(ii)(iii);(iv) 由外层把两个窗口并起来判。"""
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
    out["days_in_window"] = int(((srs.index >= a_lo) & (srs.index <= a_hi)).sum())
    # 叠到账户上,尺寸:候选自己的风险贡献 = 10%(资金倍数上限 1 倍)
    # ⚠️ 索引对齐:srs 的索引是**字符串**日期,账户 C.index 是 DatetimeIndex ⇒ 必须先转,
    #    否则 reindex 全是 NaN、fillna(0) 之后候选在账户上是**全零**(上一轮 (i)(iii)(iv) 全空的真凶)。
    on_acct = srs_on_acct(srs, C.index)
    # 候选在**账户日历**上的链式累计(= 全日历复利,自检见 chain_selfcheck)
    out["self_chain_cum_pct"] = round(float((1.0 + on_acct).prod() - 1.0) * 100, 2)
    w = bisect_w(on_acct)
    out["w"] = None if w is None else round(w, 6)
    if w is None:
        out["error"] = "尺寸不可行(资金倍数 1 倍内调不到风险贡献 10%,或复利守卫拦下)"
        return out
    out["rc_achieved"] = round(rc_of(w, on_acct), 3)
    # (ii) 自己的贡献为正 + 零分布 p_upper(账户贡献口径:对齐型统计量)
    # Seth 定稿口径:候选序列循环平移后叠到账户上的**账户年化 − 不带候选的账户年化**。
    # 循环平移保留日收益多重集 ⇒ 候选自身总量的零分布退化(p_upper≡1);账户层面的贡献依赖
    # 「候选的收益落在哪一天」⇒ 平移会改变它 ⇒ 这个口径才有分辨力。
    if skip_null:
        act_c, p_c, med_c, nnull = stat_contrib(on_acct, w, a_lo, a_hi), None, None, 0
    else:
        act_c, p_c, med_c, nnull = null_p_upper_acct(on_acct, w, a_lo, a_hi, resize=False)
    out["acct_contrib_pp"] = None if act_c is None else round(float(act_c), 4)
    out["p_upper_acct_contrib"] = None if p_c is None else round(float(p_c), 4)
    out["null_median_contrib_pp"] = None if med_c is None else round(float(med_c), 4)
    out["null_n"] = nnull
    # 字面读法(候选自己的总收益)保留:展示 circular_shift 对它退化(p_upper ≡ 1.0)
    actual, p, med = null_p_upper_self(srs.loc[(srs.index >= a_lo) & (srs.index <= a_hi)],
                                        lambda v: float(np.prod(1 + v) - 1))
    out["self_total_ret_pct"] = round(actual * 100, 2)
    out["p_upper_self_literal"] = None if p is None else round(float(p), 4)
    out["null_median_self_pct"] = round(med * 100, 2)
    out["ii_positive"] = bool(act_c is not None and act_c > 0)
    out["ii_p"] = bool(p_c is not None and p_c < 0.10)
    out["ii_pass"] = bool(out["ii_positive"] and out["ii_p"])
    an = acct_new(w, on_acct)
    Amn = M(an)
    # 尺寸调到 10% 之后,账户本身的变化
    out["acct_cagr_old_pct"] = recon["acct_cagr_pct"]
    out["acct_vol_old_pct"] = recon["acct_vol_ann_pct"]
    _cg = acct_cagr(an, a_lo, a_hi)
    out["acct_cagr_new_pct"] = None if _cg is None else round(_cg * 100, 2)
    out["acct_vol_new_pct"] = round(float(Amn.std() * math.sqrt(12)) * 100, 1)
    out["acct_worst_month_new_pct"] = round(float(Amn.min()) * 100, 2)
    # (i) 月度相关:与账户、与 R-v2;全样本与压力月
    cand_m = (w * on_acct).resample("M").sum()
    rv2_m = Cm["rv2"]
    cm_acct = Cm.sum(axis=1)   # 账户(旧口径的贡献和)
    # (i) 对**不带候选**的账户算(Seth §Seth-1113e ③):基准是 C["acct"] 的月度复利 Am,
    #     不是叠加后的账户(那会把候选自己算进相关里)。
    out["corr_acct_full"] = monthly_corr(cand_m, Am)
    out["corr_rv2_full"] = monthly_corr(cand_m, rv2_m)
    out["corr_acct_stress"] = monthly_corr(cand_m[stress], Am[stress])
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
    # (iv) 的两个窗口由外层 _mk 组装(本函数只判单窗口的 (i)(ii)(iii))
    _own = cum(srs, a_lo, a_hi)
    out["sign_self"] = 1 if _own > 0 else (-1 if _own < 0 else 0)
    out["self_total_ret_pct_win"] = round(_own * 100, 2)
    out["all_pass_123"] = bool(out["i_pass"] and out["ii_pass"] and out["iii_pass"])
    return out


def evaluate_window(srs, a, b):
    """窗口内的候选自身结论:总收益的符号 + 字面读法的 p_upper(展示它退化,不作判据)。

    窗口 1(候选数据最早日起)落在账户起点之前 ⇒ **没有账户可叠**,只能看候选自身序列
    ⇒ 按 C 道口径,窗口 1 的账户口径结论记「另一窗口不可得」。
    """
    x = srs[(srs.index >= a) & (srs.index <= b)]
    if len(x) < 60:
        return {"window": [a, b], "n": int(len(x)), "sign": None, "verdict": None, "note": "样本不足"}
    actual, p, _ = null_p_upper_self(x, lambda v: float(np.prod(1 + v) - 1))
    sign = 1 if actual > 0 else (-1 if actual < 0 else 0)
    return {"window": [a, b], "n": int(len(x)), "total_ret_pct": round(actual * 100, 2),
            "p_upper_self_literal": None if p is None else round(float(p), 4),
            "sign": sign, "verdict": "pass" if actual > 0 else "fail"}


# ── 5. 跑 ───────────────────────────────────────────────────────────────────
variants = []
_tk_cache = {}


def _mk(name, ev, kind, H, use_funding=False, skip_null=False):
    """两窗口并排:窗口 1 = 候选数据最早日(z30_min_date)起;窗口 2 = 账户起点(A0)起。

    (i)(ii)(iii) 在**每个窗口上各判一遍**;(iv) = 候选自身在两窗口的结论同号。
    """
    srs, tk = build_book(ev, kind, H, use_funding=use_funding)
    chk = chain_selfcheck(srs, C.index)
    print("SELFCHECK", name, json.dumps(chk, ensure_ascii=False), flush=True)
    if not chk["pass"]:
        raise SystemExit(f"SELFCHECK FAIL {name}: diff_abs={chk['diff_abs']}")
    w1 = evaluate(name, srs, ev, kind, H, z30_min_date, A1, use_funding=use_funding, skip_null=skip_null)
    w2 = evaluate(name, srs, ev, kind, H, A0, A1, use_funding=use_funding, skip_null=skip_null)
    iv = bool(w1.get("sign_self") is not None and w1.get("sign_self") == w2.get("sign_self"))
    v = {"variant": name, "kind": kind, "H": H, "events": len(ev), "use_funding": use_funding,
         "selfcheck": chk,
         "window1": w1, "window2": w2, "event_stats": event_stats(tk, kind),
         "iv_same_sign": iv, "iv_pass": iv,
         "all_pass": bool(iv and w1.get("all_pass_123") and w2.get("all_pass_123"))}
    variants.append(v)
    _SERIES[name] = srs
    print("VAR", json.dumps({"variant": name, "kind": kind, "H": H, "events": len(ev),
                             "w1": w1.get("w"), "w2": w2.get("w"),
                             "w1_contrib_pp": w1.get("acct_contrib_pp"), "w2_contrib_pp": w2.get("acct_contrib_pp"),
                             "w1_p": w1.get("p_upper_acct_contrib"), "w2_p": w2.get("p_upper_acct_contrib"),
                             "w1_123": w1.get("all_pass_123"), "w2_123": w2.get("all_pass_123"),
                             "w1_sign": w1.get("sign_self"), "w2_sign": w2.get("sign_self"),
                             "iv_pass": iv, "all_pass": v["all_pass"],
                             "w1_err": w1.get("error"), "w2_err": w2.get("error")}, ensure_ascii=False), flush=True)
    return v


_SERIES = {}


# 本轮出:规则 A 的判定表(五个持有期 × 两个窗口并排)+ 规则 B 的一句「窗口依赖」。
# H = 7 / 20 / 30 / 45 / 90:7 = 卡面写的「一周」;30 / 90 = S-569 原文测过的窗口;20 / 45 = 新加的邻点。
for H in H_A:
    _mk(f"A_all_H{H}", rule_a_events(H), "A", H)
if RUN_B:
    for H in (7, 30, 90):
        _mk(f"B_btceth_H{H}", rule_b_events(H), "B", H, skip_null=True)

summary = []
for v in variants:
    summary.append({k: v.get(k) for k in ("variant", "kind", "H", "events", "events_per_year", "total_ret_pct",
                                           "total_ret_full_pct", "ann_pct", "days_in_window",
                                           "self_total_ret_pct", "p_upper_self_literal", "null_median_self_pct",
                                           "acct_contrib_pp", "p_upper_acct_contrib", "null_median_contrib_pp", "null_n",
                                           "w", "rc_achieved",
                                           "acct_cagr_old_pct", "acct_cagr_new_pct",
                                           "acct_vol_old_pct", "acct_vol_new_pct", "acct_worst_month_new_pct",
                                           "corrs", "i_pass", "ii_positive", "ii_p", "ii_pass",
                                           "iii_pass", "iii_worst20_ok", "iii_eff_ok",
                                           "iv_pass", "iv_same_sign", "all_pass",
                                           "worst20_old_pct", "worst20_new_pct", "eff_sources_old", "eff_sources_new",
                                           "eig_pr_old", "eig_pr_new", "cand_in_rv2_worst12_months_pct",
                                           "rv2_in_its_worst12_months_pct", "worst20d_window",
                                           "cand_in_worst20d_window_pct", "rv2_in_worst20d_window_pct",
                                           "window1", "window2", "event_stats", "error", "selfcheck")})
    print("VAR", json.dumps(summary[-1], ensure_ascii=False))

out = {"recon": recon, "panel": {"symbols": len(close_by_sym), "z30_first": z30_min_date, "z30_meta": cache.get("z30_meta"),
                                  "fund_days": int(fund_cov.sum())},
       "variants": summary,
       "account": {"start": A0, "end": A1, "months": int(len(Am)), "acct_cagr_pct": recon["acct_cagr_pct"]}}
json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False, default=str)
print("WROTE", OUT)

# ── 6. 复核:候选序列的极值 / 复利守卫 / 账户 CAGR 的独立复算 ────────────────
# 目的:任何 (ii) 的数字都建立在「候选的日收益序列」上 ⇒ 必须能核对这条序列本身:
# 极值、哪些日子把复利打成负数、加进去之后账户 CAGR 的独立复算。
def _verify():
    vv = {}
    for name in ("A_all_H7", "A_all_H20", "A_all_H30", "A_all_H45", "A_all_H90",
                 "B_btceth_H7", "B_btceth_H30", "B_btceth_H90"):
        srs = _SERIES.get(name)
        if srs is None:
            continue
        on = srs_on_acct(srs, C.index)
        w = next((v["window2"].get("w") for v in variants if v["variant"] == name), None)
        v = next(v for v in variants if v["variant"] == name)
        worst = on.nsmallest(5)
        rec = {"diag_srs_n": int(len(srs)), "diag_srs_dtype": str(getattr(srs.index, "dtype", "?")),
               "diag_srs_first": str(srs.index[0]), "diag_srs_last": str(srs.index[-1]),
               "diag_acct_n": int(len(C.index)), "diag_acct_first": str(C.index[0].date()),
               "diag_acct_last": str(C.index[-1].date()),
               "diag_srs_in_A0_A1": int(((srs.index >= A0) & (srs.index <= A1)).sum()),
               "diag_cum_slice_n": int(((srs.index >= A0) & (srs.index <= A1)).sum()),
               "diag_on_agg_cum_pct": round(float((1 + on).prod() - 1) * 100, 2),
               "diag_on_reindex_cum_pct": round(float((1 + pd.Series(
                   np.asarray(srs.values, dtype=float),
                   index=pd.to_datetime(pd.Index(srs.index))).reindex(C.index).fillna(0.0)).prod() - 1) * 100, 2),
               "diag_cum_srs_A0_A1_pct": round(float(cum(srs, A0, A1)) * 100, 2),
               "min_day_ret_pct": round(float(on.min()) * 100, 2),
               "max_day_ret_pct": round(float(on.max()) * 100, 2),
               "worst5": [[str(i.date()), round(float(x) * 100, 2)] for i, x in worst.items()],
               "days_below_-100pct": int((on < -1.0).sum()),
               "days_below_-50pct": int((on < -0.5).sum()),
               "nonzero_days": int((on != 0).sum()),
               "w": w,
               "acct_cagr_base_pct": round(float(acct_cagr(C["acct"], A0, A1)) * 100, 2),
               "acct_cagr_with_pct": None if w is None else round(float(acct_cagr(acct_new(w, on), A0, A1)) * 100, 2),
               "base_prod_sign": int(np.sign((1 + C["acct"]).prod())),
               "with_prod_sign": None if w is None else int(np.sign((1 + acct_new(w, on)).prod())),
               "self_cum_pct": round(float((1 + on).prod() - 1) * 100, 2),
               "self_cum_fullcal_pct": round(float(cum(srs, A0, A1)) * 100, 2),
               "sum_daily_pct": round(float(on.sum()) * 100, 2),
               "cand_min_1_plus_w": None if w is None else round(float(np.min(1 + w * on.values)), 4),
               "report_cagr_new_pct": v["window2"].get("acct_cagr_new_pct"),
               "report_contrib_pp": v["window2"].get("acct_contrib_pp"),
               "selfcheck": v.get("selfcheck"),
               "selfcheck_diff_abs": (v.get("selfcheck") or {}).get("diff_abs"),
               "chain_cum_pct": round(((v.get("selfcheck") or {}).get("chain_cum", 1.0) - 1.0) * 100, 2),
               "ref_fullcal_cum_pct": round(((v.get("selfcheck") or {}).get("ref_cum_fullcal", 1.0) - 1.0) * 100, 2)}
        vv[name] = rec
        print("VERIFY", name, json.dumps(rec, ensure_ascii=False), flush=True)
    json.dump(vv, open(VERIFY_OUT, "w"), indent=1, ensure_ascii=False, default=str)
    print("WROTE", VERIFY_OUT)


try:
    _verify()
except Exception as _e:            # 复核块绝不能把主结果带崩
    print("VERIFY_SKIPPED", repr(_e), flush=True)


def _mult_leg_check():
    """口径对照:同一段候选日收益,在两种记账口径下账户年化各是多少。

    **加法口径(S-834 的账户模型,本卡一切判据都在它上面)**:账户日收益 = 各腿 P&L 之和,
    候选腿按 `w·r` 每天加进去 ⇒ 账户 NAV 复利。
    **乘法口径(候选腿自己复利,再乘到账户上)**:账户 NAV = Π(1+base)·Π(1+w·r)。
    两者不同 ⇒ 说明「候选自己的乘法战绩」与「它加进账户的贡献」是两件事。
    """
    rows = []
    for v in variants:
        if v.get("kind") != "A":
            continue
        srs = _SERIES.get(v["variant"])
        w = (v.get("window2") or {}).get("w")
        if srs is None or w is None:
            continue
        on = srs_on_acct(srs, C.index)
        T = (C.index[-1] - C.index[0]).days / 365.25
        base_nav = float((1.0 + C["acct"]).prod())
        mult_nav = base_nav * float((1.0 + w * on).prod())
        rows.append({
            "variant": v["variant"], "w": round(float(w), 6),
            "cagr_base_pct": round(float(acct_cagr(C["acct"], A0, A1)) * 100, 2),
            "cagr_additive_pct": round(float(acct_cagr(acct_new(w, on), A0, A1)) * 100, 2),
            "cagr_mult_leg_pct": round((mult_nav ** (1.0 / T) - 1.0) * 100, 2),
            "prod_1_plus_w_r": round(float((1.0 + w * on).prod()), 6),
            "min_1_plus_w_r": round(float(np.min(1.0 + w * on.values)), 4),
            "cand_own_cum_pct": round(float((1.0 + on).prod() - 1.0) * 100, 2),
            "cand_own_arith_sum_pct": round(float(on.sum()) * 100, 2),
        })
    print("MULT", json.dumps(rows, ensure_ascii=False), flush=True)
    return rows


try:
    _mult_leg_check()
except Exception as _e:            # 同上:诊断块绝不能把主结果带崩
    print("MULT_SKIPPED", repr(_e), flush=True)
