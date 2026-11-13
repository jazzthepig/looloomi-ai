"""S-843(11-13,Seth):股票腿与黄金腿按月度 10 月均线离场(Faber 2007),叠在 S-834 的账户装配上;看水下时间。

登记见 REFUTATION_LEDGER `## S-843`(先登记后算)。只读。用法(仓库根目录):
  SUPABASE_URL=x SUPABASE_KEY=x python3 docs/research/s843_beta_leg_trend_exit.py docs/research/t342_daily.csv <cometcloud-local/research/>
月末收盘在 docs/research/s843_monthend.json(ohlcv_daily / eodhd)。账户装配与 s834 / s840 同一段,只多一个参数:某条腿某个月「不在场」时,
它那一份权重当月拿现金利息;RBv2 的配比照旧用原始收益算。
"""
import importlib.util
import json
import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "docs/research"); sys.path.insert(0, ".")
from src.data.universe import flex_alloc as fa  # noqa: E402

R = sys.argv[2] if len(sys.argv) > 2 else "/Volumes/CometCloudAI/cometcloud-local/research/"
OUT, SEED, N_NULL, SMA_N, SWITCH_COST = "docs/research/s843_results.json", 20261113, 200, 10, 20 / 1e4
ME = json.load(open("docs/research/s843_monthend.json"))
d = pd.read_csv(sys.argv[1], parse_dates=["date"]).set_index("date")
START = pd.Timestamp("2021-10-11")
cal = pd.date_range(d.index[0], d.index[-1], freq="D")
cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)


def rv2_series():
    ck = "/tmp/s843_rv2.pkl"
    if os.path.exists(ck):
        return pickle.load(open(ck, "rb"))
    import t310_slots as T310
    T310.UM = R + "s681/_um_daily.jsonl"; T310.STYLE = R + "t156/_style.json"
    sp = importlib.util.spec_from_file_location("t352_engine", "docs/research/t352_engine.py"); E1 = importlib.util.module_from_spec(sp); sp.loader.exec_module(E1)
    raw, _ = T310.load_tickets(); bars = T310.load_bars({t["symbol"] for t in raw}); exits, _ = T310.classify_exits(raw, bars)
    TK = T310.to_engine_tickets(raw, exits); gate_d, _, _ = T310.load_gate()
    res = E1.simulate(TK, bars, gate_d, 0.80, equity0=630.0, risk_frac=0.0075, cap_n=10, fix=True)
    s = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()
    pickle.dump(s, open(ck, "wb"))
    return s


RV2 = rv2_series()
df = pd.concat({"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}, axis=1).dropna().sort_index()
rets = df.pct_change()
IDX = [x for x in df.index if x >= START]
MONTHS = sorted({x.strftime("%Y-%m") for x in IDX[1:]})


def rule_signal(leg: str) -> dict[str, bool]:
    """月 m 在不在场 = 上个月月末收盘 > 截至上个月的 10 个月末收盘均值。只用 ≤ 上月末的数据。"""
    px = pd.Series(ME[leg]).sort_index()
    sma = px.rolling(SMA_N).mean()
    on = (px > sma)
    out = {}
    for m in MONTHS:
        prev = (pd.Period(m) - 1).strftime("%Y-%m")
        assert prev in on.index and not np.isnan(sma[prev]), (leg, m)
        out[m] = bool(on[prev])
    return out


def assemble(sig: dict[str, dict[str, bool]] | None = None) -> pd.DataFrame:
    """S-834 的装配;sig[leg][月] = False 时,那条腿当月拿现金利息,月初进出各付一次换仓成本。"""
    sig = sig or {}
    tgt = pd.Series(fa.rb_weights(rets.loc[:IDX[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0); hold = tgt.copy()
    rows, nav = [], 1.0
    state = {leg: True for leg in sig}
    for i, day in enumerate(IDX[1:], start=1):
        prev = IDX[i - 1]
        row = rets.loc[day, list(fa.LEGS)].copy()
        cr = fa._between(cash_rate, prev, day)
        m, sw = day.strftime("%Y-%m"), 0.0
        for leg, s in sig.items():
            want = s[m]
            if want != state[leg]:
                sw += SWITCH_COST * float(hold[leg]); state[leg] = want
            if not want:
                row[leg] = cr
        c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
        c["cash"] = (1.0 - float(hold.sum())) * cr; c["rv2"] = fa._between(RV2, prev, day)
        g = sum(c.values()); nav *= 1 + g; hold = hold * (1 + row) / (1 + g)
        cost = sw
        if i % 21 == 0:
            new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
            cost += float((hold - new).abs().sum()) * 20 / 1e4; hold = new.copy()
        if cost:
            nav *= 1 - cost; c["cost"] = -cost
        rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav})
    return pd.DataFrame(rows).set_index("d").fillna(0.0)


def cagr(C):
    return float(C["nav"].iloc[-1] ** (365.25 / (C.index[-1] - IDX[0]).days) - 1)


def underwater(C):
    nav = pd.concat([pd.Series({IDX[0]: 1.0}), C["nav"]]); peak = nav.cummax(); out, start, prev = [], None, None
    for day, v in (nav / peak - 1).items():
        if v < 0 and start is None:
            start = prev
        if v >= 0 and start is not None:
            out.append((str(start.date()), str(day.date()), (day - start).days, round(float((nav.loc[start:day] / peak.loc[start:day] - 1).min()) * 100, 1))); start = None
        prev = day
    if start is not None:
        out.append((str(start.date()), "未收回", (nav.index[-1] - start).days, round(float((nav.loc[start:] / peak.loc[start:] - 1).min()) * 100, 1)))
    return sorted(out, key=lambda x: -x[2])


def worst20(C):
    return round(float(((1 + C["acct"]).rolling(20).apply(np.prod, raw=True) - 1).min()) * 100, 2)


def summary(C):
    uw = underwater(C)
    return {"cagr_pct": round(cagr(C) * 100, 2), "longest_uw_days": uw[0][2], "top3_uw": uw[:3], "worst20_pct": worst20(C),
            "yearly_pct": {str(y): round(float(v) * 100, 2) for y, v in C["acct"].groupby(C.index.year).sum().items()}}


def shifted(s: dict[str, bool], k: int) -> dict[str, bool]:
    v = [s[m] for m in MONTHS]
    return {m: v[(j - k) % len(v)] for j, m in enumerate(MONTHS)}


if __name__ == "__main__":
    base = assemble()
    rc = float(np.cov(base["rv2"].resample("M").sum(), ((1 + base["acct"]).resample("M").prod() - 1))[0, 1] / ((1 + base["acct"]).resample("M").prod() - 1).var())
    B = summary(base); print("BASE", json.dumps(B, ensure_ascii=False), "rv2_share", round(rc, 3), flush=True)
    assert abs(B["cagr_pct"] - 35.7) < 0.15 and abs(rc - 0.742) < 0.002, "账户对不上 S-834,停"
    assert float((assemble({}).acct - base.acct).abs().max()) == 0.0
    always = {leg: {m: True for m in MONTHS} for leg in ("equity", "gold")}
    assert float((assemble(always).acct - base.acct).abs().max()) == 0.0, "自检:全程在场必须逐日等于原账户"
    SIG = {leg: rule_signal(leg) for leg in ("equity", "gold")}
    res = {"base": B, "months": len(MONTHS), "off_months": {leg: [m for m in MONTHS if not SIG[leg][m]] for leg in SIG}, "variants": {}}
    for name, legs in (("both", ("equity", "gold")), ("equity_only", ("equity",)), ("gold_only", ("gold",))):
        C = assemble({leg: SIG[leg] for leg in legs}); S = summary(C)
        S["yearly_diff_pp"] = {y: round(S["yearly_pct"][y] - B["yearly_pct"][y], 2) for y in B["yearly_pct"]}
        S["cost_ex_2022_pp"] = round(sum(v for y, v in S["yearly_diff_pp"].items() if y != "2022"), 2)
        res["variants"][name] = S; print(name.upper(), json.dumps(S, ensure_ascii=False), flush=True)
    rng = np.random.default_rng(SEED); nc, nu = [], []
    for _ in range(N_NULL):
        C = assemble({leg: shifted(SIG[leg], int(rng.integers(1, len(MONTHS)))) for leg in SIG})
        nc.append(cagr(C) * 100); nu.append(underwater(C)[0][2])
    V = res["variants"]["both"]
    res["null"] = {"n": N_NULL, "cagr_median": round(float(np.median(nc)), 2), "cagr_p90": round(float(np.quantile(nc, 0.9)), 2), "uw_median": float(np.median(nu)), "uw_p10": float(np.quantile(nu, 0.1)),
                   "real_cagr_pctile": round(float((np.array(nc) < V["cagr_pct"]).mean()), 3), "real_uw_pctile_shorter": round(float((np.array(nu) > V["longest_uw_days"]).mean()), 3)}
    a = B["longest_uw_days"] - V["longest_uw_days"] >= 60
    b = V["cagr_pct"] >= B["cagr_pct"] - 1.0
    c = V["cost_ex_2022_pp"] > -3.0
    dd = (V["cagr_pct"] > res["null"]["cagr_median"] and V["longest_uw_days"] < res["null"]["uw_median"]
          and (res["null"]["real_cagr_pctile"] >= 0.9 or res["null"]["real_uw_pctile_shorter"] >= 0.9))
    res["verdict"] = {"a_uw_shorter_60d": bool(a), "b_cagr_within_1pp": bool(b), "c_cost_ex_2022_gt_-3pp": bool(c), "d_beats_shift_null": bool(dd), "pass": bool(a and b and c and dd)}
    print("NULL", json.dumps(res["null"]), "\nVERDICT", json.dumps(res["verdict"]), flush=True)
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
