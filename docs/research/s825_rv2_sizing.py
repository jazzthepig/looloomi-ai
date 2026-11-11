"""S-825(11-12,Seth):R-v2 在名义上限不咬合的区间里每票风险多大 —— f 0.75 / 1.0 / 1.25 / 1.5% × 上限 1.2 / 2.0,按回本时间与年化判;名义占用峰值单列。

预注册见 REFUTATION_LEDGER `## S-825`。只读。用法(仓库根目录):
  python3 docs/research/s825_rv2_sizing.py <t342_daily.csv> <cometcloud-local/research/>
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
ov0, _ = overlay(0.005, 0.40); C0 = run(RB, ov0, CASH); out = {"C0": C0}
print(f"C0 cagr {C0['cagr']*100:+.2f}% uw {C0['longest_uw_d']} mdd {C0['mdd']*100:.1f}%")
for f in (0.0075, 0.01, 0.0125, 0.015):
    for cap in (1.20, 2.00):
        ov, res = overlay(f, cap); r = run(RB, ov, CASH)
        nav, _ = fa.dynamic_mix_nav(LEGS, RB, start=START, overlay_ret=ov, cash_ret=CASH)
        wm = float(nav.resample("M").last().pct_change().min())
        cand = [t for t in TK if t["tid"] in res["taken"] and t.get("r") is not None]; top = max(cand, key=lambda t: float(t["r"]))
        ov2, _ = overlay(f, cap, tickets=[t for t in TK if t["tid"] != top["tid"]]); r2 = run(RB, ov2, CASH)
        g = None
        for k in ("gross", "gross_curve", "gross_frac", "exposure"):
            if k in res: g = res[k]; break
        r.update(n=len(res["taken"]), worst_month=wm, loo={"tid": top["tid"], "cagr": r2["cagr"]}, res_keys=sorted(k for k in res if k not in ("curve", "taken")))
        out[f"{f}|{cap}"] = r
        print(f"f {f*100:.2f}% cap {cap:.2f} n {len(res['taken'])} | cagr {r['cagr']*100:+6.2f}% uw {r['longest_uw_d']}d mdd {r['mdd']*100:6.1f}% worst-month {wm*100:+.1f}% | LOO {top['tid'].split(':')[0]} → {r2['cagr']*100:+.2f}% | " + " ".join(f"{y}:{v*100:+.0f}" for y, v in r["yearly"].items()), flush=True)
print("res keys:", out[list(out)[-1]]["res_keys"])
json.dump(out, open("docs/research/s825_results.json", "w"), default=str)

# ── 名义占用(保证金现实)──
o = {}
for f, cap in ((0.005, 0.40), (0.0075, 1.2), (0.01, 1.2), (0.0125, 1.2)):
    _, res = overlay(f, cap); g = res["gross_ratio_hist"]
    vals = [float(x[1]) if isinstance(x, (list, tuple)) else float(x) for x in (g.values() if isinstance(g, dict) else g)]
    days = [x[0] for x in g] if g and isinstance(g[0], (list, tuple)) else None
    w = [v for v, dd in zip(vals, days) if str(dd)[:10] >= "2021-10-11"] if days else vals
    o[f"{f}|{cap}"] = {"peak": max(w), "days_gt_0.4": sum(v > 0.4 for v in w), "days_gt_1.0": sum(v > 1.0 for v in w), "n": len(w), "mean": sum(w) / len(w)}
    print(f, cap, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in o[f"{f}|{cap}"].items()})
r = json.load(open("docs/research/s825_results.json")); r["gross"] = o; json.dump(r, open("docs/research/s825_results.json", "w"), default=str)
