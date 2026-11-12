"""S-823(11-12,Seth 的一份;A 道 T-347 另算):三态敞口 —— 趋势明显向下 −0.3 / 不明确 +0.3 / 明显向上 +1.0。

预注册见 REFUTATION_LEDGER `## S-823`。两步:discovery(2012-01-01 → 2020-12-31)选一条并落盘,之后 holdout(2021-01-01 起)只判那一条。
用法(仓库根目录):
  python3 docs/research/s823_three_state.py discovery <coinmetrics_price_usd.json> <um_funding.jsonl>
  python3 docs/research/s823_three_state.py holdout   <coinmetrics_price_usd.json> <um_funding.jsonl>
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from src.data.evaluation import apparatus as ap  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DISC = os.path.join(HERE, "s823_discovery.json")
E_DOWN, E_MID, E_UP, COST = -0.3, 0.3, 1.0, 0.0010
D0, D1, H0, H1 = "2012-01-01", "2020-12-31", "2021-01-01", "2026-10-30"
RULES = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8")


def load(price_path, funding_path, end):
    raw = json.load(open(price_path))
    p = pd.Series({pd.Timestamp(r["time"][:10]): float(r["PriceUSD"]) for r in raw if r.get("PriceUSD")}).sort_index()
    p = p[p.index <= end]                                   # discovery 这一步不读留出段的任何一天
    f = pd.Series(dtype=float)
    for line in open(funding_path):
        x = json.loads(line)
        if x["symbol"] == "BTC":
            s = pd.Series({pd.Timestamp(t).tz_localize(None) if pd.Timestamp(t).tzinfo is None else pd.Timestamp(t).tz_convert(None): float(v) for t, v in x["rates"]})
            f = s.groupby(s.index.normalize()).sum()
            break
    return p, f[f.index <= end]


def states(p):
    m200, m50 = p.rolling(200).mean(), p.rolling(50).mean()
    slope, ret20, low90 = m200 - m200.shift(30), p / p.shift(20) - 1, p.rolling(90).min()
    ok = m200.notna() & slope.notna()
    up2, dn2 = (p > m200) & (slope > 0), (p < m200) & (slope < 0)
    up3, dn3 = (m50 > m200) & (p > m200), (m50 < m200) & (p < m200)
    vguard = p > 1.25 * low90
    spec = {"R1": (p > m200, p < m200, E_DOWN), "R2": (up2, dn2, E_DOWN), "R3": (up3, dn3, E_DOWN),
            "R4": (up2, dn2 & (ret20 < 0), E_DOWN), "R5": (up3, dn3 & (ret20 < 0), E_DOWN),
            "R6": (up2, dn2 & ~vguard, E_DOWN), "R7": (up2, dn2 & (ret20 < 0) & ~vguard, E_DOWN), "R8": (up2, dn2, 0.0)}
    out = {}
    for k, (up, dn, e_dn) in spec.items():
        e = pd.Series(E_MID, index=p.index)
        e[up & ok] = E_UP
        e[dn & ok] = e_dn
        out[k] = e
    out["HOLD"] = pd.Series(1.0, index=p.index)
    return out


def account(e, p, f, a, b):
    """信号 d 日收盘定、d + 1 日生效。返回 (日收益, 生效敞口, 空头腿日收益)。"""
    r = p.pct_change()
    pos = e.shift(1)
    fd = f.reindex(p.index).fillna(0.0)
    ret = pos * r + (-pos.clip(upper=0)) * fd - COST * (pos - pos.shift(1)).abs().fillna(0)
    short_leg = (pos < 0) * (pos * r + (-pos) * fd)
    m = (p.index >= a) & (p.index <= b)
    return ret[m].fillna(0), pos[m], short_leg[m].fillna(0)


def metrics(ret, pos):
    nav = (1 + ret).cumprod()
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    peak = nav.cummax()
    under, longest, start = nav < peak, 0, None
    last_peak_d = nav.index[0]
    for d, u in under.items():
        if not u:
            last_peak_d = d
        else:
            longest = max(longest, (d - last_peak_d).days)
    return {"cagr": float(nav.iloc[-1] ** (1 / yrs) - 1), "total": float(nav.iloc[-1] - 1), "longest_uw_d": int(longest),
            "mdd": float((nav / peak - 1).min()), "days": {"short": int((pos < 0).sum()), "flat": int((pos == 0).sum()), "low": int((pos == E_MID).sum()), "full": int((pos == E_UP).sum())},
            "turns": int((pos != pos.shift(1)).sum() - 1)}


def comp(x):
    return float((1 + x).prod() - 1)


def main():
    step, price_path, funding_path = sys.argv[1], sys.argv[2], sys.argv[3]
    if step == "discovery":
        p, f = load(price_path, funding_path, D1)
        st = states(p)
        res = {}
        for k, e in st.items():
            ret, pos, sl = account(e, p, f, D0, D1)
            res[k] = {**metrics(ret, pos), "short_leg_total": comp(sl)}
        base = res["R8"]
        elig = [k for k in RULES[:-1] if res[k]["longest_uw_d"] <= base["longest_uw_d"]]
        pick = max(elig, key=lambda k: res[k]["cagr"] - base["cagr"]) if elig else None
        json.dump({"window": [D0, D1], "last_price_day_read": str(p.index[-1].date()), "rules": res, "eligible": elig, "picked": pick}, open(DISC, "w"), indent=1)
        for k in list(RULES) + ["HOLD"]:
            m = res[k]
            print(f"{k:5s} cagr {m['cagr']*100:+8.2f}%  longest_uw {m['longest_uw_d']:5d}d  mdd {m['mdd']*100:6.1f}%  days {m['days']}  turns {m['turns']:4d}  short_leg {m['short_leg_total']*100:+7.2f}%")
        print("eligible (uw ≤ R8):", elig, "→ picked:", pick)
        return
    d = json.load(open(DISC))
    pick = d["picked"]
    if not pick:
        print("discovery picked nothing — S-823 ends there"); return
    p, f = load(price_path, funding_path, H1)
    st = states(p)
    out = {"picked": pick, "window": [H0, H1], "last_price_day_read": str(p.index[-1].date())}
    for k in (pick, "R8", "HOLD"):
        ret, pos, sl = account(st[k], p, f, H0, H1)
        out[k] = {**metrics(ret, pos), "short_leg_total": comp(sl), "yearly": {int(y): round(comp(x), 4) for y, x in ret.groupby(ret.index.year)}}
        if k == pick:
            seg = lambda a, b: comp(sl[(sl.index >= a) & (sl.index <= b)])
            out["short_leg"] = {"2022": seg("2022-01-01", "2022-12-31"), "2025-11→2026-08": seg("2025-11-01", "2026-08-31"), "2021-05→2021-09": seg("2021-05-01", "2021-09-30"),
                                "yearly": {int(y): round(comp(x), 4) for y, x in sl.groupby(sl.index.year)}}
            r = p.pct_change()[pos.index].fillna(0); fd = f.reindex(pos.index).fillna(0.0)
            flag = (pos < 0).values
            rng = np.random.default_rng(823)
            null = [comp(pd.Series(np.asarray(ap.circular_shift(flag, rng, block=1), dtype=bool), index=pos.index) * (E_DOWN * r - E_DOWN * fd)) for _ in range(500)]
            out["null"] = {"p_upper": ap.p_upper(out[k]["short_leg_total"], null), "median": float(np.median(null))}
    P, C = out[pick], out["R8"]
    out["verdict"] = {"i_cagr_gt_R8": P["cagr"] > C["cagr"], "ii_uw_le_R8": P["longest_uw_d"] <= C["longest_uw_d"],
                      "iii_short_leg_2022_and_2025_26_positive": out["short_leg"]["2022"] > 0 and out["short_leg"]["2025-11→2026-08"] > 0,
                      "iv_p_lt_0.10": out["null"]["p_upper"] is not None and out["null"]["p_upper"] < 0.10}
    json.dump(out, open(os.path.join(HERE, "s823_results.json"), "w"), indent=1, default=str)
    for k in (pick, "R8", "HOLD"):
        m = out[k]
        print(f"{k:5s} cagr {m['cagr']*100:+7.2f}%  longest_uw {m['longest_uw_d']:4d}d  mdd {m['mdd']*100:6.1f}%  days {m['days']}  short_leg {m['short_leg_total']*100:+6.2f}%  yearly {m['yearly']}")
    print("short leg:", out["short_leg"], "\nnull:", out["null"], "\nverdict:", out["verdict"])


if __name__ == "__main__":
    main()
