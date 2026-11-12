"""S-834(11-13,Seth):分散度体检 —— 真钱现配置拆成五个收益来源,量相关、风险贡献、有效来源数与压力窗。

登记见 REFUTATION_LEDGER `## S-834`。只读、描述性。用法(仓库根目录):
  SUPABASE_URL=x SUPABASE_KEY=x python3 docs/research/s834_diversification_audit.py docs/research/t342_daily.csv <cometcloud-local/research/>
"""
import importlib.util
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "docs/research"); sys.path.insert(0, ".")
import t310_slots as T310                                   # noqa: E402
from src.data.universe import flex_alloc as fa              # noqa: E402

R = sys.argv[2] if len(sys.argv) > 2 else "/Volumes/CometCloudAI/cometcloud-local/research/"
T310.UM = R + "s681/_um_daily.jsonl"; T310.STYLE = R + "t156/_style.json"
sp = importlib.util.spec_from_file_location("t352_engine", "docs/research/t352_engine.py"); E1 = importlib.util.module_from_spec(sp); sp.loader.exec_module(E1)
sp = importlib.util.spec_from_file_location("s823", "docs/research/s823_three_state.py"); S823 = importlib.util.module_from_spec(sp); sp.loader.exec_module(S823)

d = pd.read_csv(sys.argv[1], parse_dates=["date"]).set_index("date")
START = pd.Timestamp("2021-10-11")
legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
cal = pd.date_range(d.index[0], d.index[-1], freq="D")
cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
raw, _ = T310.load_tickets(); bars = T310.load_bars({t["symbol"] for t in raw}); exits, _ = T310.classify_exits(raw, bars)
TK = T310.to_engine_tickets(raw, exits); gate_d, _, _ = T310.load_gate()
F_, CAP_, N_ = float(os.environ.get("S834_F", 0.0075)), float(os.environ.get("S834_CAP", 0.80)), int(os.environ.get("S834_N", 10))   # 默认 = 真钱现配置(S-831)
res = E1.simulate(TK, bars, gate_d, CAP_, equity0=630.0, risk_frac=F_, cap_n=N_, fix=True)
rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()

# 账户:逐日记下每个来源的贡献(与 flex_alloc.dynamic_mix_nav 同一套记账,这里展开是为了拿到分项)
df = pd.concat(legs_px, axis=1).dropna().sort_index(); rets = df.pct_change()
idx = [x for x in df.index if x >= START]
tgt = pd.Series(fa.rb_weights(rets.loc[:idx[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0); hold = tgt.copy()
rows, nav = [], 1.0
between = fa._between
for i, day in enumerate(idx[1:], start=1):
    row = rets.loc[day, list(fa.LEGS)]; prev = idx[i - 1]
    c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
    c["cash"] = (1.0 - float(hold.sum())) * between(cash_rate, prev, day); c["rv2"] = between(rv2, prev, day)
    g = sum(c.values()); nav *= 1 + g; hold = hold * (1 + row) / (1 + g)
    if i % 21 == 0:
        new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
        cost = float((hold - new).abs().sum()) * 20 / 1e4; nav *= 1 - cost; c["cost"] = -cost; hold = new.copy()
    rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav})
C = pd.DataFrame(rows).set_index("d").fillna(0.0)
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
core = d.core_nav_1_cap_pit24.reindex(C.index).pct_change().fillna(0.0)

# 候选对冲(叠加在账户净值上的日收益)
def um(sym):
    for line in open(T310.UM):
        x = json.loads(line)
        if x["symbol"] == sym:
            rw = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
            return pd.Series({pd.Timestamp(r[0]): float(r[4]) for r in rw}).sort_index().pct_change()
rb, re_ = um("BTC").reindex(cal).fillna(0), um("ETH").reindex(cal).fillna(0)
g = pd.Series({pd.Timestamp(k): bool(v) for k, v in gate_d.items()}).sort_index().reindex(cal).ffill()
gate_short = (~g.astype(bool)).shift(1).fillna(False).astype(bool) * (-0.30 * (rb + re_) / 2)
p, f = S823.load(R + "t339/coinmetrics_price_usd.json", R + "s681/_um_funding.jsonl", "2026-10-30")
r6_short = (S823.states(p)["R6"] < 0).shift(1).reindex(cal).fillna(False).astype(bool) * (-0.30 * rb)
def on_common(s):
    return pd.Series([between(s, idx[i - 1], idx[i]) for i in range(1, len(idx))], index=idx[1:])
H = pd.DataFrame({"gate_short": on_common(gate_short), "r6_short": on_common(r6_short)})

M = lambda x: (1 + x).resample("M").prod() - 1            # 月度
Cm = pd.DataFrame({k: C[k].resample("M").sum() for k in SRC}); Am = M(C["acct"]); Km = M(core); Hm = pd.DataFrame({k: M(H[k]) for k in H})
stress = Km <= Km.quantile(0.2)
out = {"window": [str(idx[0].date()), str(idx[-1].date())], "months": int(len(Am)), "stress_months": int(stress.sum())}
out["acct"] = {"cagr": float(C["nav"].iloc[-1] ** (365.25 / (idx[-1] - idx[0]).days) - 1), "vol_ann_monthly": float(Am.std() * np.sqrt(12)), "worst_month": [str(Am.idxmin().date()), float(Am.min())]}
out["corr_full"] = Cm.corr().round(2).to_dict(); out["corr_stress"] = Cm[stress].corr().round(2).to_dict()
out["corr_to_core"] = {"full": {k: round(float(Cm[k].corr(Km)), 2) for k in SRC}, "stress": {k: round(float(Cm[k][stress].corr(Km[stress])), 2) for k in SRC}}
rc = {k: float(np.cov(Cm[k], Am)[0, 1] / Am.var()) for k in SRC}; rcs = {k: float(np.cov(Cm[k][stress], Am[stress])[0, 1] / Am[stress].var()) for k in SRC}
ent = lambda w: float(np.exp(-sum(x * np.log(x) for x in (np.clip(list(w.values()), 1e-9, None) / np.clip(list(w.values()), 1e-9, None).sum()))))
ev = np.linalg.eigvalsh(Cm.corr().values); evs = np.linalg.eigvalsh(Cm[stress].corr().fillna(0).values)
out["risk_contribution"] = {"full": {k: round(v, 3) for k, v in rc.items()}, "stress": {k: round(v, 3) for k, v in rcs.items()}}
out["effective_sources"] = {"entropy_full": round(ent(rc), 2), "entropy_stress": round(ent(rcs), 2), "eig_participation_full": round(float(ev.sum() ** 2 / (ev ** 2).sum()), 2), "eig_participation_stress": round(float(evs.sum() ** 2 / (evs ** 2).sum()), 2)}
out["mean_monthly_contribution_pct"] = {"full": {k: round(float(Cm[k].mean() * 100), 3) for k in SRC}, "stress": {k: round(float(Cm[k][stress].mean() * 100), 3) for k in SRC}, "acct_full": round(float(Am.mean() * 100), 3), "acct_stress": round(float(Am[stress].mean() * 100), 3), "core_stress": round(float(Km[stress].mean() * 100), 2)}
def win(a, b):
    m = (C.index >= a) & (C.index <= b)
    return {"acct": round(float((1 + C["acct"][m]).prod() - 1) * 100, 1), "core": round(float((1 + core[m]).prod() - 1) * 100, 1), **{k: round(float(C[k][m].sum()) * 100, 1) for k in SRC}, **{k: round(float((1 + H[k][m]).prod() - 1) * 100, 1) for k in H}}
out["stress_windows"] = {"2021-11→2022-06": win("2021-11-08", "2022-06-30"), "2022-11 (FTX)": win("2022-11-01", "2022-11-30"), "2024-08-01→08-05": win("2024-08-01", "2024-08-05"), "2025-02": win("2025-02-01", "2025-02-28")}
r20 = (1 + C["acct"]).rolling(20).apply(np.prod) - 1; e = r20.idxmin(); s0 = C.index[max(0, C.index.get_loc(e) - 19)]
out["stress_windows"][f"worst 20d {s0.date()}→{e.date()}"] = win(s0, e)
legm = pd.DataFrame({k: M(rets[k].reindex(C.index).fillna(0)) for k in fa.LEGS}); alld = (legm < 0).all(axis=1)
out["all_three_legs_down_months"] = {"n": int(alld.sum()), "of": int(len(legm)), "acct_mean_pct": round(float(Am[alld].mean() * 100), 2), "acct_worst_pct": round(float(Am[alld].min() * 100), 2), "rv2_mean_pct": round(float(Cm["rv2"][alld].mean() * 100), 2)}
out["hedges"] = {k: {"total_pct": round(float((1 + H[k]).prod() - 1) * 100, 1), "corr_acct_full": round(float(Hm[k].corr(Am)), 2), "corr_acct_stress": round(float(Hm[k][stress].corr(Am[stress])), 2), "mean_in_stress_pct": round(float(Hm[k][stress].mean() * 100), 2), "mean_outside_pct": round(float(Hm[k][~stress].mean() * 100), 2),
                     "corr_sources_full": {s: round(float(Hm[k].corr(Cm[s])), 2) for s in SRC}} for k in H}
out["config"] = {"f": F_, "cap": CAP_, "n": N_}
print("ONE", json.dumps({"f": F_, "cap": CAP_, "n": N_, "cagr": round(out["acct"]["cagr"] * 100, 1), "vol": round(out["acct"]["vol_ann_monthly"] * 100, 1), "rv2_risk_share": out["risk_contribution"]["full"]["rv2"], "eff_sources": out["effective_sources"]["entropy_full"], "worst_month": round(out["acct"]["worst_month"][1] * 100, 1), "worst_20d": [k for k in out["stress_windows"] if k.startswith("worst")][0] + " " + str([v for k, v in out["stress_windows"].items() if k.startswith("worst")][0]["acct"]), "stress_month_mean": out["mean_monthly_contribution_pct"]["acct_stress"]}))
if os.environ.get("S834_F") is None:
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "s834_results.json"), "w"), indent=1, default=str)
for k in ("acct", "effective_sources", "risk_contribution", "corr_to_core", "mean_monthly_contribution_pct", "all_three_legs_down_months"):
    print(k, json.dumps(out[k], ensure_ascii=False))
print("corr_full"); print(Cm.corr().round(2).to_string()); print("corr_stress"); print(Cm[stress].corr().round(2).to_string())
for k, v in out["stress_windows"].items(): print(k, v)
for k, v in out["hedges"].items(): print(k, v)
