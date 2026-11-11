"""S-817(11-11,Seth):自有账户把 R-v2 的名义上限 / 每票风险往上开 —— 12 格网格、回本时间、去掉 R 最大的一张票重跑。

预注册见 REFUTATION_LEDGER `## S-817`。只读;腿取自 lane-c 的 t342_daily.csv(分支 lane-c/T-342),叠加 = t251_gross_cap.simulate 的日历日曲线。
用法(仓库根目录):python3 docs/research/s817_overlay_grid.py <t342_daily.csv> <cometcloud-local/research/>
"""
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
out={}
for cap in (0.40,0.80,1.20,2.00):
    for f in (0.005,0.01,0.02):
        ov,res=overlay(f,cap); r=run(RB,ov,CASH)
        taken=res["taken"]; 
        rr=lambda t: float(t['r'])
        cand=[t for t in TK if t['tid'] in taken and t.get('r') is not None]
        top=max(cand,key=rr) if cand else None
        loo=None
        if top is not None:
            tid=top.get("tid") or f"{top.get('symbol')}:{top.get('signal_d')}"
            ov2,_=overlay(f,cap,tickets=[t for t in TK if t["tid"]!=tid]); r2=run(RB,ov2,CASH); loo={"tid":tid,"r":rr(top),"cagr":r2["cagr"],"uw":r2["longest_uw_d"]}
        r["n"]=len(taken); r["loo"]=loo; out[f"{f}|{cap}"]=r
        print(f"f {f*100:.1f}% cap {cap:.2f} n {len(taken):3d} | cagr {r['cagr']*100:+6.2f}% tot {r['tot']*100:+8.1f}% mdd {r['mdd']*100:6.1f}% uw {r['longest_uw_d']}d {r['longest_uw'][0]}→{r['longest_uw'][1]} down {r['down_d']} up {r['up_d']} | LOO {loo and (loo['tid'], round(loo['r'],1), round(loo['cagr']*100,2), loo['uw'])} | " + " ".join(f"{y}:{v*100:+.0f}" for y,v in r['yearly'].items()), flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "s817_results.json"), "w"), default=str)

