"""S-840(11-13,Seth):规则 A(山寨暴涨后空它、等额多 BTC)从零重写 —— 第二台引擎 + 第二份数据(U 本位永续日线)。

登记见 REFUTATION_LEDGER `## S-840`(先登记后算)。只读。用法(仓库根目录):
  SUPABASE_URL=x SUPABASE_KEY=x python3 docs/research/s840_rule_a_rewrite.py docs/research/t342_daily.csv <cometcloud-local/research/>
账户装配逐字照 docs/research/s834_diversification_audit.py(那是共同的底);候选、z30、袖子记账、进账户日的换算都是这里自己写的,
不 import B 道的 T-360 脚本,也不读 T-092 的缓存。
"""
import datetime as dt
import importlib.util
import json
import math
import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "docs/research"); sys.path.insert(0, ".")
R = sys.argv[2] if len(sys.argv) > 2 else "/Volumes/CometCloudAI/cometcloud-local/research/"
OUT = "docs/research/s840_results.json"
SEED, N_NULL, TARGET_RC, COST = 20261113, 200, 0.10, 0.0010
SLOTS, Z_MIN, HS, HS_JUDGED = 10, 3.0, (7, 20, 30, 45, 90), (20, 30, 45)
HALVES = (("2021-10-12", "2024-03-31"), ("2024-04-01", "2026-09-30"))
WORST = ("2023-02-08", "2023-03-08")


# ── 1. 账户(S-834 的装配;缓存到 /tmp 只为反复跑省时间,删掉缓存结果不变) ─────────────────────────
def build_account():
    ck = "/tmp/s840_acct.pkl"
    if os.path.exists(ck):
        return pickle.load(open(ck, "rb"))
    import t310_slots as T310
    from src.data.universe import flex_alloc as fa
    T310.UM = R + "s681/_um_daily.jsonl"; T310.STYLE = R + "t156/_style.json"
    sp = importlib.util.spec_from_file_location("t352_engine", "docs/research/t352_engine.py"); E1 = importlib.util.module_from_spec(sp); sp.loader.exec_module(E1)
    d = pd.read_csv(sys.argv[1], parse_dates=["date"]).set_index("date")
    START = pd.Timestamp("2021-10-11")
    legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
    cal = pd.date_range(d.index[0], d.index[-1], freq="D")
    cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
    raw, _ = T310.load_tickets(); bars = T310.load_bars({t["symbol"] for t in raw}); exits, _ = T310.classify_exits(raw, bars)
    TK = T310.to_engine_tickets(raw, exits); gate_d, _, _ = T310.load_gate()
    res = E1.simulate(TK, bars, gate_d, 0.80, equity0=630.0, risk_frac=0.0075, cap_n=10, fix=True)
    rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()
    df = pd.concat(legs_px, axis=1).dropna().sort_index(); rets = df.pct_change()
    idx = [x for x in df.index if x >= START]
    tgt = pd.Series(fa.rb_weights(rets.loc[:idx[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0); hold = tgt.copy()
    rows, nav = [], 1.0
    for i, day in enumerate(idx[1:], start=1):
        row = rets.loc[day, list(fa.LEGS)]; prev = idx[i - 1]
        c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
        cr = fa._between(cash_rate, prev, day)
        c["cash"] = (1.0 - float(hold.sum())) * cr; c["rv2"] = fa._between(rv2, prev, day)
        g = sum(c.values()); nav *= 1 + g; hold = hold * (1 + row) / (1 + g)
        if i % 21 == 0:
            new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
            cost = float((hold - new).abs().sum()) * 20 / 1e4; nav *= 1 - cost; c["cost"] = -cost; hold = new.copy()
        rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav, "cash_ret": cr})
    C = pd.DataFrame(rows).set_index("d").fillna(0.0)
    out = (C, idx[0])
    pickle.dump(out, open(ck, "wb"))
    return out


C, DAY0 = build_account()
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
M = lambda x: (1 + x).resample("M").prod() - 1
MS = lambda x: x.resample("M").sum()


def cagr(daily, a=None, b=None):
    s = daily if a is None else daily.loc[a:b]
    days = (s.index[-1] - (DAY0 if a is None else max(pd.Timestamp(a) - pd.Timedelta(days=1), DAY0))).days
    return float((1 + s).prod() ** (365.25 / days) - 1)


def worst20(daily):
    r = (1 + daily).rolling(20).apply(np.prod, raw=True) - 1
    i = r.idxmin(); j = daily.index[daily.index.get_loc(i) - 19]
    return float(r.min()), str(j.date()), str(i.date())


def eff_sources(contrib_m, acct_m):
    rc = {k: float(np.cov(v, acct_m)[0, 1] / acct_m.var()) for k, v in contrib_m.items()}
    w = np.clip(np.abs(np.array(list(rc.values()))), 1e-9, None); w = w / w.sum()
    return float(np.exp(-(w * np.log(w)).sum())), rc


BASE_M = M(C["acct"])
base_eff, base_rc = eff_sources({k: MS(C[k]) for k in SRC}, BASE_M)
recon = {"cagr_pct": round(cagr(C["acct"]) * 100, 2), "rv2_risk_share": round(base_rc["rv2"], 3), "eff_sources": round(base_eff, 2),
         "worst20": worst20(C["acct"]), "window": [str(DAY0.date()), str(C.index[-1].date())], "expected": {"cagr_pct": 35.7, "rv2_risk_share": 0.742}}
print("RECON", json.dumps(recon, ensure_ascii=False), flush=True)
assert abs(recon["cagr_pct"] - 35.7) < 0.15 and abs(recon["rv2_risk_share"] - 0.742) < 0.002, "账户对不上 S-834,停"

# ── 2. 永续日线 → 日历矩阵;z30 从日线重算 ─────────────────────────────────────────────────────────
D0 = dt.date(2020, 1, 1)
px = {}
for line in open(R + "s681/_um_daily.jsonl"):
    x = json.loads(line)
    if not x["pair"].endswith("USDT"):
        continue
    px[x["pair"]] = {dt.date.fromisoformat(str(b[0])[:10]): float(b[4]) for b in x["bars"] if len(b) >= 5 and b[4] and b[4] > 0}
DN = max(max(v) for v in px.values() if v)
NDAY = (DN - D0).days + 1
DAYS = [D0 + dt.timedelta(days=i) for i in range(NDAY)]
PAIRS = sorted(px)
P = np.full((len(PAIRS), NDAY), np.nan)
for i, p in enumerate(PAIRS):
    for d_, v in px[p].items():
        if d_ >= D0:
            P[i, (d_ - D0).days] = v
IB = PAIRS.index("BTCUSDT")
LAST = np.array([np.max(np.where(~np.isnan(P[i]))[0]) if (~np.isnan(P[i])).any() else -1 for i in range(len(PAIRS))])
with np.errstate(invalid="ignore", divide="ignore"):
    LR30 = np.full_like(P, np.nan); LR30[:, 30:] = np.log(P[:, 30:] / P[:, :-30])
NBARS = np.cumsum(~np.isnan(P), axis=1)


def z30_at(i, t):
    """t 日的 z30:30 日对数收益,按该合约 t−730 … t−31 这段里的 30 日对数收益标准化;不够数 ⇒ None。"""
    if t < 31 or np.isnan(LR30[i, t]) or NBARS[i, t - 1] < 600:
        return None
    w = LR30[i, max(0, t - 730):t - 30]
    w = w[~np.isnan(w)]
    if len(w) < 365:
        return None
    sd = float(w.std(ddof=1))
    return None if sd <= 0 else float((LR30[i, t] - w.mean()) / sd)


EVENTS = []
for t in range(NDAY):
    if DAYS[t].weekday() != 0:
        continue
    for i in range(len(PAIRS)):
        if i == IB:
            continue
        z = z30_at(i, t)
        if z is not None and z >= Z_MIN:
            EVENTS.append((t, -z, PAIRS[i], i))
EVENTS.sort()
print("EVENTS", json.dumps({"n": len(EVENTS), "pairs": len({e[2] for e in EVENTS}), "first": str(DAYS[EVENTS[0][0]]), "last": str(DAYS[EVENTS[-1][0]]),
                            "by_year": {str(y): sum(1 for e in EVENTS if DAYS[e[0]].year == y) for y in range(2021, 2027)}}), flush=True)

# 资金费(每日合计;空头收到正费率、多头付出)
FUND = np.zeros_like(P)
if os.path.exists(R + "s681/_um_funding.jsonl"):
    for line in open(R + "s681/_um_funding.jsonl"):
        x = json.loads(line)
        if x["pair"] not in px:
            continue
        i = PAIRS.index(x["pair"])
        for ts, r in x["rates"]:
            k = (dt.date.fromisoformat(ts[:10]) - D0).days
            if 0 <= k < NDAY and r is not None:
                FUND[i, k] += float(r)


# ── 3. 袖子:逐日历日记账(数量定死、两腿等额、最多 10 张、同币不重复) ─────────────────────────────
def sleeve(H, funding=False, drop=None):
    """返回 (日历日净值数组, 票列表)。净值从第一张票进场前一天起为 1。"""
    by_entry = {}
    for (t, negz, pair, i) in EVENTS:
        by_entry.setdefault(t + 7, []).append((negz, pair, i, t))
    S = np.ones(NDAY); eq = 1.0
    book, tickets = {}, []
    for d_ in range(NDAY):
        pnl = 0.0
        for pair, p in list(book.items()):
            a, b = P[p["i"], d_], P[IB, d_]
            a = p["last_a"] if np.isnan(a) else a
            b = p["last_b"] if np.isnan(b) else b
            day = p["qb"] * (b - p["last_b"]) - p["qa"] * (a - p["last_a"])
            if funding:
                day += p["qa"] * a * FUND[p["i"], d_] - p["qb"] * b * FUND[IB, d_]
            p["last_a"], p["last_b"] = a, b
            p["pnl"] += day; pnl += day
            if d_ >= p["x"]:
                c = COST * (p["qa"] * a + p["qb"] * b)
                p["pnl"] -= c; pnl -= c
                tickets.append({"pair": pair, "t": str(DAYS[p["t"]]), "entry": str(DAYS[p["e"]]), "exit": str(DAYS[d_]), "u": p["u"], "pnl": p["pnl"],
                                "ret_on_u": p["pnl"] / p["u"], "z": p["z"], "cut_short": bool(p["x"] < p["e"] + H)})
                del book[pair]
        eq += pnl
        for (negz, pair, i, t) in sorted(by_entry.get(d_, [])):
            if drop is not None and (pair, str(DAYS[t])) == drop:
                continue
            a, b = P[i, d_], P[IB, d_]
            if np.isnan(a) or np.isnan(b) or LAST[i] <= d_:
                tickets.append({"pair": pair, "t": str(DAYS[t]), "blocked": "no_price"}); continue
            if pair in book:
                tickets.append({"pair": pair, "t": str(DAYS[t]), "blocked": "coin"}); continue
            if len(book) >= SLOTS:
                tickets.append({"pair": pair, "t": str(DAYS[t]), "blocked": "cap"}); continue
            u = eq / SLOTS
            c = COST * 2 * u
            eq -= c
            book[pair] = {"i": i, "t": t, "e": d_, "x": min(d_ + H, int(LAST[i])), "u": u, "qa": u / a, "qb": u / b, "last_a": a, "last_b": b, "pnl": -c, "z": -negz}
        S[d_] = eq
    return S, tickets


def on_account_days(S):
    """日历日净值 → 账户日收益:账户日 d 的收益 = S[d] / S[上一个账户日] − 1(周末与假日的盈亏落在下一个账户日)。"""
    s = pd.Series(S, index=pd.to_datetime(DAYS))
    days = [DAY0] + list(C.index)
    v = s.reindex(pd.DatetimeIndex(days)).ffill()
    on = (v / v.shift(1) - 1).iloc[1:]
    on.index = C.index
    span = float(s.loc[:C.index[-1]].iloc[-1] / s.loc[:DAY0].iloc[-1])
    assert abs(float((1 + on).prod()) - span) < 1e-9, "自检:账户日收益的连乘 ≠ 袖子净值首尾比"
    return on.fillna(0.0), span - 1


def augment(w, on):
    return C["acct"] + w * on - w * C["cash_ret"]


def rc_of(w, on):
    am = M(augment(w, on))
    return float(np.cov(MS(w * on), am)[0, 1] / am.var())


def size(on):
    if rc_of(1.0, on) < TARGET_RC:
        return 1.0, False
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if rc_of(mid, on) < TARGET_RC else (lo, mid)
    return (lo + hi) / 2, True


def corr(a, b, mask=None):
    if mask is not None:
        a, b = a[mask], b[mask]
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 0 and b.std() > 0 else None


def judge(H, funding=False, drop=None, null=True):
    S, tk = sleeve(H, funding=funding, drop=drop)
    on, own_total = on_account_days(S)
    assert float((augment(0.0, on) - C["acct"]).abs().max()) == 0.0, "自检:w = 0 时必须逐日等于 A_base"
    w, reached = size(on)
    aug = augment(w, on)
    cm, stress = MS(w * on), BASE_M <= BASE_M.quantile(0.2)
    rvm = MS(C["rv2"])
    stat = cagr(aug) - cagr(C["acct"])
    out = {"H": H, "funding": funding, "w": round(w, 4), "size_reached": reached, "rc": round(rc_of(w, on), 4),
           "tickets_taken": sum(1 for t in tk if "pnl" in t), "blocked": {k: sum(1 for t in tk if t.get("blocked") == k) for k in ("cap", "coin", "no_price")},
           "own_total_ret_pct": round(own_total * 100, 2),
           "own_by_year_pct": {str(y): round(float((1 + on[on.index.year == y]).prod() - 1) * 100, 2) for y in sorted(set(on.index.year))},
           "i_corr_acct_full": corr(cm, BASE_M), "i_corr_acct_stress": corr(cm, BASE_M, stress), "i_corr_rv2_full": corr(cm, rvm), "i_corr_rv2_stress": corr(cm, rvm, stress),
           "ii_cagr_diff_pp": round(stat * 100, 2)}
    if null:
        rng = np.random.default_rng(SEED); n = len(on); nd = []
        for _ in range(N_NULL):
            k = int(rng.integers(20, n - 20))
            sh = pd.Series(np.roll(on.values, k), index=on.index)
            nd.append(cagr(augment(w, sh)) - cagr(C["acct"]))
        nd = np.array(nd)
        out["ii_p_upper"] = round(float((1 + (nd >= stat).sum()) / (N_NULL + 1)), 4)
        out["ii_null_median_pp"] = round(float(np.median(nd)) * 100, 2)
        out["ii_null_p5_p95_pp"] = [round(float(np.quantile(nd, 0.05)) * 100, 2), round(float(np.quantile(nd, 0.95)) * 100, 2)]
    w20b, w20a = worst20(C["acct"]), worst20(aug)
    eff, rc = eff_sources({**{k: MS(C[k]) for k in SRC}, "cand": cm}, M(aug))
    out.update({"iii_worst20_base_pct": round(w20b[0] * 100, 2), "iii_worst20_aug_pct": round(w20a[0] * 100, 2), "iii_worst20_aug_span": w20a[1:],
                "iii_eff_sources": [round(base_eff, 2), round(eff, 2)],
                "iv_halves_cagr_diff_pp": [round((cagr(aug, a, b) - cagr(C["acct"], a, b)) * 100, 2) for a, b in HALVES],
                "worst_window_cand_contrib_pct": round(float((1 + (w * on).loc[WORST[0]:WORST[1]]).prod() - 1) * 100, 2)})
    c = [x for x in (out["i_corr_acct_full"], out["i_corr_acct_stress"], out["i_corr_rv2_full"], out["i_corr_rv2_stress"])]
    out["pass_i"] = all(x is not None and x < 0.30 for x in c)
    out["pass_ii"] = bool(stat > 0 and out.get("ii_p_upper", 1.0) < 0.10)
    out["pass_iii"] = bool(w20a[0] >= w20b[0] and eff > base_eff)
    out["pass_iv"] = all(x > 0 for x in out["iv_halves_cagr_diff_pp"])
    return out, tk


if __name__ == "__main__":
    res = {"recon": recon, "events": len(EVENTS), "rows": [], "funding_rows": [], "report_only": {}}
    best = None
    for H in HS:
        o, tk = judge(H)
        res["rows"].append(o)
        print("ROW", json.dumps(o, ensure_ascii=False), flush=True)
        if H == 30:
            done = [t for t in tk if "pnl" in t]
            best = max(done, key=lambda t: t["pnl"])
            res["report_only"]["H30_ticket_stats"] = {"n": len(done), "win_rate": round(sum(1 for t in done if t["pnl"] > 0) / len(done), 3),
                                                     "mean_ret_on_u_pct": round(float(np.mean([t["ret_on_u"] for t in done])) * 100, 2),
                                                     "median_ret_on_u_pct": round(float(np.median([t["ret_on_u"] for t in done])) * 100, 2),
                                                     "worst_5": sorted([(round(t["ret_on_u"] * 100, 1), t["pair"], t["entry"]) for t in done])[:5],
                                                     "best_5": sorted([(round(t["ret_on_u"] * 100, 1), t["pair"], t["entry"]) for t in done])[-5:]}
    for H in HS_JUDGED:
        o, _ = judge(H, funding=True, null=False)
        res["funding_rows"].append(o)
        print("FUND", json.dumps({k: o[k] for k in ("H", "w", "own_total_ret_pct", "ii_cagr_diff_pp", "iii_worst20_aug_pct", "iv_halves_cagr_diff_pp")}, ensure_ascii=False), flush=True)
    o, _ = judge(30, drop=(best["pair"], best["t"]), null=False)
    res["report_only"]["H30_drop_best_ticket"] = {"dropped": [best["pair"], best["entry"], round(best["ret_on_u"] * 100, 1)], "own_total_ret_pct": o["own_total_ret_pct"], "ii_cagr_diff_pp": o["ii_cagr_diff_pp"]}
    by = {r["H"]: r for r in res["rows"]}; fb = {r["H"]: r for r in res["funding_rows"]}
    h30 = all(by[30][k] for k in ("pass_i", "pass_ii", "pass_iii", "pass_iv")) and fb[30]["ii_cagr_diff_pp"] > 0
    nb = all(by[h]["ii_cagr_diff_pp"] > 0 and by[h]["iii_worst20_aug_pct"] >= by[h]["iii_worst20_base_pct"] for h in (20, 45))
    res["verdict"] = {"H30_all_four_and_funding_sign": bool(h30), "neighbours_20_45_ok": bool(nb), "forward_shadow_arm": bool(h30 and nb)}
    print("VERDICT", json.dumps(res["verdict"]), flush=True)
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
