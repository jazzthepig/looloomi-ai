"""S-819(11-12,Seth):闸门关着时空大盘(BTC / ETH 永续 50 / 50)、不设价格止损、扛到闸门重开 —— 对 C0(S-815 的 L3)判回本时间。

预注册见 REFUTATION_LEDGER `## S-819`。只读。用法(仓库根目录):
  python3 docs/research/s819_gate_short.py <t342_daily.csv> <cometcloud-local/research/>
"""
import warnings
warnings.filterwarnings("ignore")
import sys, json, os
os.environ.setdefault("SUPABASE_URL", "http://offline.invalid"); os.environ.setdefault("SUPABASE_KEY", "offline")
sys.path.insert(0, "docs/research"); sys.path.insert(0, ".")
import pandas as pd, numpy as np
import t310_slots as T310
R = sys.argv[2] if len(sys.argv) > 2 else "/Volumes/CometCloudAI/cometcloud-local/research/"
T310.UM = R + "s681/_um_daily.jsonl"; T310.STYLE = R + "t156/_style.json"
T251 = T310.T251
from src.data.universe import flex_alloc as fa
raw, _ = T310.load_tickets(); need = {t["symbol"] for t in raw}
bars = T310.load_bars(need); exits, bad = T310.classify_exits(raw, bars)
TK = T310.to_engine_tickets(raw, exits); GATE = T310.load_gate()[0]
d = pd.read_csv(sys.argv[1], parse_dates=["date"]).set_index("date")
LEGS = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
START = pd.Timestamp("2021-10-11")
cal = pd.date_range(d.index[0], d.index[-1], freq="D")
CASH = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
CONST = lambda h, x: fa.BASE_T25
RB = lambda h, x: fa.rb_weights(h)

def overlay(f, cap, cap_n=14, tickets=None):
    res = T251.simulate(tickets if tickets is not None else TK, bars, GATE, cap, equity0=630.0, risk_frac=f, cap_n=cap_n)
    c = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index()
    return c.pct_change().dropna(), res

def recovery(nav):
    """longest underwater spell (calendar days, peak → first day NAV ≥ that peak; open spell counted to the end),
    and for the max-drawdown episode: peak, trough, days peak→trough, days trough→recovery (None = not recovered)."""
    peak = nav.cummax(); uw = nav < peak
    longest, cur_start, open_end = 0, None, False
    spells = []
    for t, u in uw.items():
        if u and cur_start is None: cur_start = nav[:t][nav[:t] >= peak[t]].index[-1]
        if not u and cur_start is not None: spells.append((cur_start, t, (t - cur_start).days, False)); cur_start = None
    if cur_start is not None: spells.append((cur_start, nav.index[-1], (nav.index[-1] - cur_start).days, True))
    lg = max(spells, key=lambda s: s[2]) if spells else None
    dd = nav / peak - 1; tr = dd.idxmin(); pk = nav[:tr][nav[:tr] >= peak[tr]].index[-1]
    after = nav[tr:][nav[tr:] >= peak[tr]]
    rec = after.index[0] if len(after) else None
    return {"mdd": float(dd.min()), "longest_uw_d": lg[2] if lg else 0, "longest_uw": (str(lg[0].date()), str(lg[1].date()), "open" if lg[3] else "closed") if lg else None,
            "mdd_peak": str(pk.date()), "mdd_trough": str(tr.date()), "down_d": (tr - pk).days, "up_d": (rec - tr).days if rec is not None else None,
            "pct_days_uw10": float((dd < -0.10).mean())}

def run(wf, ov=None, cash=None):
    nav, _ = fa.dynamic_mix_nav(LEGS, wf, start=START, overlay_ret=ov, cash_ret=cash)
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    r = recovery(nav); r.update({"tot": float(nav.iloc[-1] - 1), "cagr": float(nav.iloc[-1] ** (1 / yrs) - 1)})
    r["yearly"] = {int(y): round(float(g.iloc[-1] / (nav[nav.index.year < y].iloc[-1] if (nav.index.year < y).any() else 1.0) - 1), 4) for y, g in nav.groupby(nav.index.year)}
    return r

def line(name, r):
    return (f"{name:34s} tot {r['tot']*100:+8.2f}% cagr {r['cagr']*100:+6.2f}% mdd {r['mdd']*100:6.2f}% | longest underwater {r['longest_uw_d']:4d}d {r['longest_uw']} | "
            f"maxDD {r['mdd_peak']}→{r['mdd_trough']} down {r['down_d']}d, back in {r['up_d']}d | days<-10%: {r['pct_days_uw10']*100:.0f}%")
from src.data.evaluation import apparatus as ap
gate_d, _, _ = T310.load_gate()
def daily(sym):
    rw = None
    for line in open(T310.UM):
        x = json.loads(line)
        if x["symbol"] == sym:
            rw = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0}); break
    c = pd.Series({pd.Timestamp(r[0]): float(r[4]) for r in rw}).sort_index()
    return c.pct_change().dropna()
def fund(sym):
    for line in open(R + "s681/_um_funding.jsonl"):
        x = json.loads(line)
        if x["symbol"] == sym:
            s = pd.Series({pd.Timestamp(t).tz_convert(None) if pd.Timestamp(t).tzinfo else pd.Timestamp(t): float(v) for t, v in x["rates"]})
            return s.groupby(s.index.normalize()).sum()
rb, re_, fb, fe = daily("BTC"), daily("ETH"), fund("BTC"), fund("ETH")
cal = pd.date_range(START - pd.Timedelta(days=5), d.index[-1], freq="D")
basket = ((rb + re_) / 2).reindex(cal); fnd = ((fb.reindex(cal).fillna(0) + fe.reindex(cal).fillna(0)) / 2)
g = pd.Series({pd.Timestamp(k): bool(v) for k, v in gate_d.items()}).sort_index().reindex(cal).ffill()
print("gate coverage", g.index[0].date(), g.index[-1].date(), "closed share in window", round(float((~g[g.index >= START].astype(bool)).mean()), 3), "basket NaN", int(basket[basket.index >= START].isna().sum()), "last basket", basket.dropna().index[-1].date())
def short_ret(gs, s):
    closed = (~gs.astype(bool)).shift(1).fillna(False).astype(bool)
    flips = (closed != closed.shift(1).fillna(False)).astype(float)
    return (closed * (-s * basket.fillna(0) + s * fnd) - flips * 0.0005 * s), closed
ov05, _ = overlay(0.005, 0.40)
C0 = run(RB, ov05, CASH); print(line("C0 = L3", C0))
res = {"C0": C0}
for s in (0.15, 0.30):
    sr, closed = short_ret(g, s); w = sr[sr.index >= START]
    comb = ov05.reindex(cal).fillna(0) + sr
    r = run(RB, comb, CASH); print(line(f"C0 + short s={s}", r))
    tot = float((1 + w).prod() - 1)
    yr = {int(y): round(float((1 + x).prod() - 1) * 100, 2) for y, x in w.groupby(w.index.year)}
    fy = {int(y): round(float((closed[x.index] * s * fnd[x.index]).sum()) * 100, 2) for y, x in w.groupby(w.index.year)}
    cw = closed[closed.index >= START]; eid = (cw != cw.shift(1)).cumsum()
    eps = [(x.index[0].date().isoformat(), len(x), round(float((1 + w[x.index]).prod() - 1) * 100, 2)) for _, x in cw.groupby(eid) if x.iloc[0]]
    long_eps = [e for e in eps if e[1] >= 10]
    rng = np.random.default_rng(819); null = []
    gv = g.values
    for _ in range(500):
        gs = pd.Series(ap.circular_shift(gv, rng, block=1), index=g.index).astype(bool)
        x, _c = short_ret(gs, s); x = x[x.index >= START]; null.append(float((1 + x).prod() - 1))
    p = ap.p_upper(tot, null)
    i = r["longest_uw_d"] <= C0["longest_uw_d"] - 60; ii = r["cagr"] >= C0["cagr"] - 0.01
    iii = sum(v > 0 for v in yr.values()) >= 2 and sum(e[2] > 0 for e in long_eps) * 2 > len(long_eps)
    iv = p is not None and p < 0.10
    print(f"  short alone: total {tot*100:+.2f}%  by year {yr}  funding by year {fy}\n  episodes ≥10d ({len(long_eps)}): {long_eps}\n  flips {int((cw != cw.shift(1)).sum())}  null median {np.median(null)*100:+.2f}%  p_upper {p:.3f}\n  (i) {i} uw {r['longest_uw_d']} vs {C0['longest_uw_d']}  (ii) {ii}  (iii) {iii}  (iv) {iv}", flush=True)
    res[str(s)] = {**r, "short_total": tot, "short_yearly": yr, "funding_yearly": fy, "episodes": long_eps, "p": p, "verdict": [bool(i), bool(ii), bool(iii), bool(iv)]}
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "s819_results.json"), "w"), default=str)
