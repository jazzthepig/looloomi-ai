"""S-733 — ④ carry on HL realized hourly funding, S-707 criteria unchanged. Window 2023-06-01 → 2026-07-20."""
import csv, datetime as dt, json, os, sys
from pathlib import Path
from collections import defaultdict
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.data.evaluation.apparatus import block_permute, null_distribution, percentile_of
from scipy.stats import spearmanr

#: HL fundingHistory 小时档(Minimax-A 07-20 抓,scripts/fetch_hyperliquid_funding.py)。Mac 侧默认路径;别处用 HL_FUNDING_DIR 指过去。
D = os.environ.get("HL_FUNDING_DIR", "/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
NAMES = ['BTC','ETH','SOL','BNB','XRP','DOGE','ADA','AVAX','LINK','DOT','LTC','TRX','ATOM','NEAR','APT','ARB','OP','SUI','UNI','AAVE','INJ','FIL','ETC','BCH']
D0, D1 = dt.date(2023, 6, 1), dt.date(2026, 7, 20)
COST = 0.0004 + 0.00035
N_NULL = int(sys.argv[1]) if len(sys.argv) > 1 else 1000

daily = {}
for n in NAMES:
    try:
        rows = list(csv.DictReader(open(f"{D}/{n.lower()}_funding_1h.csv")))
    except FileNotFoundError:
        continue
    acc = defaultdict(float); cnt = defaultdict(int)
    for r in rows:
        d = dt.datetime.fromtimestamp(int(r["fundingTime"]) // 1000, dt.timezone.utc).date()
        if D0 <= d <= D1:
            acc[d] += float(r["fundingRate"]); cnt[d] += 1
    daily[n] = {d: v for d, v in acc.items() if cnt[d] >= 20}
names = sorted(daily)
days = [D0 + dt.timedelta(i) for i in range((D1 - D0).days + 1)]
mondays = [d for d in days if d.weekday() == 0]
idx = {m: i for i, m in enumerate(mondays)}
F = np.full((len(days), len(names)), np.nan)
for j, n in enumerate(names):
    for i, d in enumerate(days):
        v = daily[n].get(d)
        if v is not None: F[i, j] = v
avail = ~np.isnan(F)
Fz = np.nan_to_num(F)

def rule_b_seq():
    S = np.zeros((len(mondays), len(names)), bool)
    for k, m in enumerate(mondays):
        i = days.index(m)
        w = F[max(0, i - 7):i]
        cnt = (~np.isnan(w)).sum(0); mu = np.nanmean(np.where(np.isnan(w), np.nan, w), 0) if len(w) else np.zeros(len(names))
        S[k] = (cnt >= 5) & (np.nan_to_num(mu) > 0)
    return S

def portfolio(on_weeks):
    """on_weeks: bool [n_mondays, n_names] (None ⇒ rule A). Returns daily equal-weight net returns and switch count."""
    on = np.zeros((len(days), len(names)), bool); cost = np.zeros((len(days), len(names)))
    if on_weeks is None:
        first = avail.argmax(0)
        on[:] = True
        for j in range(len(names)): cost[first[j], j] = COST
        sw = len(names)
    else:
        prev = np.zeros(len(names), bool); sw = 0
        k = -1
        for i, d in enumerate(days):
            if d.weekday() == 0:
                k += 1
                cur = on_weeks[k]
                ch = cur != prev
                cost[i, ch] = COST; sw += int(ch.sum()); prev = cur
            on[i] = prev
    r = np.where(avail, Fz * on - cost, np.nan)
    with np.errstate(all='ignore'):
        m = np.nanmean(r, 1)
    return np.nan_to_num(m), sw

A, swA = portfolio(None)
S = rule_b_seq()
B, swB = portfolio(S)

def stats(x):
    cum = np.cumsum(x); dd = (cum - np.maximum.accumulate(cum)).min()
    bl, bloss, cl, closs = 0, 0.0, 0, 0.0
    for v in x:
        if v < 0:
            cl += 1; closs += v
            if cl > bl or (cl == bl and closs < bloss): bl, bloss = cl, closs
        else: cl, closs = 0, 0.0
    return {"ann_net": round(float(x.mean() * 365), 4), "max_dd": round(float(dd), 4), "neg_run_days": bl, "neg_run_loss": round(float(bloss), 4)}

out = {"days_no_names": int((avail.sum(1) == 0).sum()), "min_names_per_day": int(avail.sum(1)[avail.sum(1) > 0].min()), "names": names, "n_names": len(names), "days": len(days), "A": stats(A), "B": stats(B), "switches_A": swA, "switches_B": swB,
       "B_on_share": round(float(S.mean()), 3)}
per = defaultdict(list)
for d, a, b in zip(days, A, B):
    k = f"{d.year}H{1 if d.month <= 6 else 2}" if d.year in (2023, 2026) else str(d.year)
    per[k].append((a, b))
out["by_period"] = {k: {"A": round(float(np.mean([a for a, _ in v]) * 365), 4), "B": round(float(np.mean([b for _, b in v]) * 365), 4), "days": len(v)} for k, v in sorted(per.items())}
out["per_name_A_gross"] = dict(sorted(((n, round(float(np.nanmean(F[:, j]) * 365), 4)) for j, n in enumerate(names)), key=lambda kv: kv[1]))

px = {}
for r in csv.DictReader(open(f"{D}/btc_1d_ohlcv.csv")):
    px[dt.datetime.fromtimestamp(int(r["openTime"]) // 1000, dt.timezone.utc).date()] = float(r["close"])
ser = dict(zip(days, B))
mes = sorted({(d.replace(day=1) + dt.timedelta(32)).replace(day=1) - dt.timedelta(1) for d in days if d <= D1})
xs, ys, xc, yc = [], [], [], []
for m in mes:
    if m > D1: continue
    mc = sum(v for d, v in ser.items() if d.year == m.year and d.month == m.month)
    p0, p1, pb = px.get(m), px.get(m + dt.timedelta(30)), px.get(m.replace(day=1) - dt.timedelta(1))
    if p0 and p1: xs.append(mc); ys.append(p1 / p0 - 1)
    if p0 and pb: xc.append(mc); yc.append(p0 / pb - 1)
rho_f, p_par = spearmanr(xs, ys); rho_c, p_c = spearmanr(xc, yc)
dd_ = [d for d in days if d - dt.timedelta(29) >= D0 and px.get(d) and px.get(d + dt.timedelta(30))]
cx = np.array([sum(ser[d - dt.timedelta(k)] for k in range(30)) for d in dd_]); cy = np.array([px[d + dt.timedelta(30)] / px[d] - 1 for d in dd_])
rho_d = float(spearmanr(cx, cy)[0])
null = null_distribution(lambda rng: spearmanr(block_permute(cx, 30, rng).astype(float), cy)[0], 1000, 733, actual=rho_d)
out["c"] = {"monthly_future_rho": round(float(rho_f), 3), "monthly_n": len(xs), "monthly_param_p": round(float(p_par), 3),
            "monthly_same_month_rho": round(float(rho_c), 3), "same_month_p": round(float(p_c), 3),
            "daily_trailing30_vs_fwd30_rho": round(rho_d, 3), "block30_p": round(float((np.abs(null) >= abs(rho_d)).mean()), 3)}

def runs(q):
    o = []
    for v in q:
        if o and o[-1][0] == v: o[-1][1] += 1
        else: o.append([v, 1])
    return o
RR = [runs(S[:, j].tolist()) for j in range(len(names))]
def rand_gate(rng):
    G = np.zeros_like(S)
    for j, rr in enumerate(RR):
        ons = list(rng.permutation([l for v, l in rr if v])); offs = list(rng.permutation([l for v, l in rr if not v]))
        q = []
        for v, _ in rr: q += [v] * int(ons.pop() if v else offs.pop())
        G[:, j] = q
    return float(portfolio(G)[0].mean() * 365)
nullB = null_distribution(rand_gate, N_NULL, 733)
out["d"] = {"B_ann": out["B"]["ann_net"], "null_p95": round(float(np.percentile(nullB, 95)), 4), "null_median": round(float(np.median(nullB)), 4),
            "pctile": round(float(percentile_of(out["B"]["ann_net"], nullB)), 3), "n": N_NULL,
            "note": "per name: rule B's on-runs and off-runs shuffled separately (same on-weeks, same switches)"}
json.dump(out, open(ROOT / "docs/research/s733_hl_carry_result.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
