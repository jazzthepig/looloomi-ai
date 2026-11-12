"""S-824(11-12,Seth):S-823 选出的 R6 空头腿放进整合账本(C0 = S-815 的 L3),账户口径判回本时间。

预注册见 REFUTATION_LEDGER `## S-824`。只读。用法(仓库根目录):
  python3 docs/research/s824_house_r6_short.py <t342_daily.csv> <cometcloud-local/research/>
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
sys.path.insert(0, "docs/research")
import importlib.util
spec = importlib.util.spec_from_file_location("s823", "docs/research/s823_three_state.py"); s823 = importlib.util.module_from_spec(spec); spec.loader.exec_module(s823)
p, f = s823.load(R + "t339/coinmetrics_price_usd.json", R + "s681/_um_funding.jsonl", "2026-10-30")
e6 = s823.states(p)["R6"]
cal = pd.date_range(START - pd.Timedelta(days=5), d.index[-1], freq="D")
short_on = (e6 < 0).shift(1).reindex(cal).fillna(False).astype(bool)
rw = None
for ln in open(T310.UM):
    x = json.loads(ln)
    if x["symbol"] == "BTC": rw = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0}); break
rb = pd.Series({pd.Timestamp(r[0]): float(r[4]) for r in rw}).sort_index().pct_change().reindex(cal).fillna(0)
fd = f.reindex(cal).fillna(0)
def sret(flag, s):
    flag = pd.Series(np.asarray(flag, dtype=bool), index=cal)
    return flag * (-s * rb + s * fd) - (flag != flag.shift(1).fillna(False)) * 0.0010 * s
ov05, _ = overlay(0.005, 0.40); C0 = run(RB, ov05, CASH); print(line("C0", C0)); out = {"C0": C0}
print("short days in window:", int(short_on[cal >= START].sum()), "perp data ends", str(pd.Series({pd.Timestamp(r[0]): 1 for r in rw}).index[-1].date()))
for s in (0.15, 0.30):
    sr = sret(short_on.values, s); w = sr[sr.index >= START]
    r = run(RB, ov05.reindex(cal).fillna(0) + sr, CASH); print(line(f"C0 + R6 short s={s}", r))
    tot = float((1 + w).prod() - 1); rng = np.random.default_rng(824)
    null = [float((1 + sret(ap.circular_shift(short_on.values, rng, block=1), s)[cal >= START]).prod() - 1) for _ in range(500)]
    pu = ap.p_upper(tot, null)
    yr = {int(y): round(float((1 + x).prod() - 1) * 100, 2) for y, x in w.groupby(w.index.year)}
    ex22 = float((1 + w[w.index.year != 2022]).prod() - 1)
    v = [r["longest_uw_d"] <= C0["longest_uw_d"] - 60, r["cagr"] >= C0["cagr"] - 0.01, pu < 0.10]
    print(f"  short alone {tot*100:+.2f}%  yearly {yr}  ex-2022 {ex22*100:+.2f}%  null median {np.median(null)*100:+.2f}%  p {pu:.3f}  verdict (i,ii,iii) {v}  yearly acct { {y: round(x*100,1) for y,x in r['yearly'].items()} }")
    out[str(s)] = {**r, "short_total": tot, "short_yearly": yr, "ex2022": ex22, "p": pu, "verdict": v}
json.dump(out, open("docs/research/s824_results.json", "w"), default=str)
