"""S-829(11-12,Seth):引擎修好之后,R-v2 三个真钱参数(名额 × 名义上限 × 每票风险)在账户口径上各值多少;两台引擎(t352 修后 / t353 从零写)各算一遍。

预注册见 REFUTATION_LEDGER `## S-829`。只读。用法(仓库根目录):
  SUPABASE_URL=x SUPABASE_KEY=x python3 docs/research/s829_rv2_params.py <t342_daily.csv> <cometcloud-local/research/> docs/research/t352_engine.py 14,10
(SUPABASE_* 只是让 t251 的 import 守卫放行,脚本不联网。)
"""
import warnings, json, sys, importlib.util
warnings.filterwarnings("ignore")
import sys, json, os
os.environ.setdefault("SUPABASE_URL", "http://offline.invalid"); os.environ.setdefault("SUPABASE_KEY", "offline")
sys.path.insert(0, "docs/research"); sys.path.insert(0, ".")
import pandas as pd, numpy as np
import t310_slots as T310
R = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "x" else "/Volumes/CometCloudAI/cometcloud-local/research/"
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
def mod(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
E1 = mod("t352_engine", sys.argv[3] if len(sys.argv) > 3 else "docs/research/t352_engine.py")
E2 = mod("t353_engine", "docs/research/t353_engine.py")
bars2 = E2.load_um(T310.UM); tk2, _ = E2.load_tickets("docs/research/t197_results.json")
RMAX = max((t for t in TK if t.get("r") is not None), key=lambda t: float(t["r"]))
def curve1(f, cap, n, drop=None):
    res = E1.simulate([t for t in TK if t["tid"] != drop], bars, GATE, cap, equity0=630.0, risk_frac=f, cap_n=n, fix=True)
    c = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index()
    g = [float(x[1]) if isinstance(x, (list, tuple)) else float(x) for x in res["gross_ratio_hist"]]
    return c, len(res["taken"]), max(g), res["taken"]
def key2(t):
    return f"{t.get('symbol')}:{t.get('signal_d')}"
def curve2(f, cap, n, drop=None):
    tk = [t for t in tk2 if key2(t) != drop]
    r = E2.simulate(tk, bars2, f=f, gross_cap=cap, cap_n=n, nav_to="2026-09-30", strict=True, exits_first=True, gross_basis="marked")
    c = pd.Series({pd.Timestamp(x[0]): float(x[1]) for x in r["curve"]}).sort_index()
    pg = max((x[2] / x[1] if x[1] > 0 else 0.0) for x in r["curve"])
    return c, r["taken"] if isinstance(r["taken"], int) else len(r["taken"]), pg, None
def acct(c):
    o = c.pct_change().dropna(); r = run(RB, o, CASH)
    nav, _ = fa.dynamic_mix_nav(LEGS, RB, start=START, overlay_ret=o, cash_ret=CASH)
    r["worst_month"] = float(nav.resample("M").last().pct_change().min()); return r
out = {}
base = run(RB, None, CASH); print(f"no R-v2: cagr {base['cagr']*100:+.2f}% uw {base['longest_uw_d']}d mdd {base['mdd']*100:.1f}%", flush=True)
NS = [int(x) for x in sys.argv[4].split(',')] if len(sys.argv) > 4 else [14, 10]
for n in NS:
    for cap in (0.40, 0.80):
        for f in (0.005, 0.0075, 0.01):
            row = {}
            for name, fn in (("E1", curve1), ("E2", curve2)):
                c, nt, pg, taken = fn(f, cap, n); a = acct(c)
                top = RMAX["tid"]
                if taken is not None:
                    cand = [t for t in TK if t["tid"] in taken and t.get("r") is not None]; top = max(cand, key=lambda t: float(t["r"]))["tid"]
                c2, *_ = fn(f, cap, n, drop=top); a2 = acct(c2)
                row[name] = {"cagr": a["cagr"], "uw": a["longest_uw_d"], "mdd": a["mdd"], "wm": a["worst_month"], "y2022": a["yearly"].get(2022), "n": nt, "peak_gross": pg, "loo": a2["cagr"], "top": top, "rv2_total": float(c.iloc[-1] / c.iloc[0] - 1)}
            out[f"{n}|{cap}|{f}"] = row
            print(f"n{n:2d} cap {cap:.2f} f {f*100:.2f}% | " + " || ".join(f"{k}: cagr {v['cagr']*100:+6.2f}% uw {v['uw']} mdd {v['mdd']*100:5.1f}% wm {v['wm']*100:+5.1f}% 22:{v['y2022']*100:+.0f} n {v['n']} pg {v['peak_gross']:.2f} loo {v['loo']*100:+.2f}%" for k, v in row.items()), flush=True)
P = "docs/research/s829_results.json"
import os
prev = json.load(open(P)).get("cells", {}) if os.path.exists(P) else {}
prev.update(out)
json.dump({"base_no_rv2": base, "cells": prev}, open(P, "w"), default=str)
