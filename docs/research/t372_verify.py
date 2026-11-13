#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-372 独立复核:不 import t372_s847_basket.py,自己把规则再写一遍,逐周比对。

  1) 全样本(每周)独立复算「成分 / 权重 / 价格腿 / 资金费 / 成本 / 周收益」,与 t372_results.json 的
     成分表、逐周 price/fund/cost/ret 比对(最大绝对差);
  2) 状态周(91 周)逐周比对;最差周给出整周明细(30 天成交额 top20、被剔除的拥挤币、每币周收益与拖累)。
只读。不入库。用法(仓库根): python3 docs/research/t372_verify.py
"""
from __future__ import annotations

import datetime as dt
import json
import os

import numpy as np

R = "/Volumes/CometCloudAI/cometcloud-local/research/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t372_verify.json")
MAIN = json.load(open(os.path.join(HERE, "t372_results.json")))
D0 = dt.date(2020, 1, 1)
TOPN, CAP, CROWDSUM, COST = 20, 0.05, -0.001, 0.0010
STABLE = {"USDT", "USDC", "FDUSD", "TUSD", "USDP", "BUSD", "DAI", "EURI", "EURT",
          "USTC", "USDD", "PYUSD", "USDS", "USDTB", "RLUSD", "USD1", "GUSD", "SUSD", "USDF"}

# ── 日线 ─────────────────────────────────────────────────────────────────────
px, vol, sym = {}, {}, {}
for line in open(R + "s681/_um_daily.jsonl"):
    x = json.loads(line)
    p = x["pair"]
    if not p.endswith("USDT"):
        continue
    b = x["bars"]
    if not b:
        continue
    d = np.array([(dt.date.fromisoformat(str(t[0])[:10]) - D0).days for t in b], dtype=np.int64)
    c = np.array([float(t[4]) if len(t) > 4 and t[4] else np.nan for t in b], dtype=float)
    v = np.array([float(t[5]) if len(t) > 5 and t[5] else 0.0 for t in b], dtype=float)
    k = (d >= 0) & np.isfinite(c) & (c > 0)
    if k.any():
        px[p] = (d[k], c[k])
        vol[p] = v[k]
        sym[p] = x["symbol"]
PAIRS = sorted(px)
PI = {p: i for i, p in enumerate(PAIRS)}
N = max(int(px[p][0].max()) for p in PAIRS) + 1
DAYS = [D0 + dt.timedelta(days=i) for i in range(N)]
NP = len(PAIRS)
IB = PAIRS.index("BTCUSDT")
CL = np.full((NP, N), np.nan)
VO = np.zeros((NP, N))
for p, (d, c) in px.items():
    CL[PI[p], d] = c
    VO[PI[p], d] = vol[p]
for i in range(NP):                                   # 前向填充
    row = CL[i]
    m = ~np.isnan(row)
    if m.any():
        idx = np.where(m, np.arange(N), 0)
        np.maximum.accumulate(idx, out=idx)
        CL[i] = row[idx]
CV = np.cumsum(VO, axis=1)
print(f"[verify] pairs={NP} days={N}", flush=True)

# ── 资金费 ───────────────────────────────────────────────────────────────────
FU = np.zeros((NP, N))
for line in open(R + "s681/_um_funding.jsonl"):
    x = json.loads(line)
    i = PI.get(x["pair"])
    if i is None:
        continue
    rs = x["rates"]
    if not rs:
        continue
    dd = np.array([(dt.date.fromisoformat(str(ts)[:10]) - D0).days for ts, _ in rs], dtype=np.int64)
    vv = np.array([float(r) if r else 0.0 for _, r in rs], dtype=float)
    ok = (dd >= 0) & (dd < N)
    if ok.any():
        FU[i] += np.bincount(dd[ok], weights=vv[ok], minlength=N)
print("[verify] funding loaded", flush=True)

# ── 逐周独立复算 ─────────────────────────────────────────────────────────────
def wts(sel):
    n = len(sel)
    w = [0.0] * n
    rem, active = 1.0, list(range(n))
    while rem > 1e-12 and active:
        share = rem / len(active)
        over = [i for i in active if share > CAP + 1e-12]
        if over:
            for i in over:
                w[i] = CAP
            rem -= CAP * len(over)
            active = [i for i in active if i not in over]
            continue
        for i in active:
            w[i] = share
        rem = 0.0
        break
    return w


SUN = [i for i in range(N) if DAYS[i].weekday() == 6 and i + 7 < N and i - 30 >= 0]
mine = {}
for d in SUN:
    v30 = CV[:, d] - (CV[:, d - 30] if d - 30 >= 0 else 0.0)
    cand = [i for i in range(NP) if v30[i] > 0 and sym[PAIRS[i]].upper() not in STABLE and i != IB]
    cand.sort(key=lambda i: -v30[i])
    top = cand[:TOPN]
    f7 = FU[:, d - 6:d + 1].sum(axis=1)
    kept = [i for i in top if f7[i] >= CROWDSUM]
    w = wts(kept)
    r = CL[kept, d + 7] / CL[kept, d + 1] - 1.0
    price = float((-np.array(w) * r).sum())
    btc = float(CL[IB, d + 7] / CL[IB, d + 1] - 1.0)
    fund = float((np.array(w) * FU[kept, d + 1:d + 8].sum(axis=1)).sum()) - float(FU[IB, d + 1:d + 8].sum())
    cost = -COST * 2.0 * (float(sum(w)) + 1.0)
    if not kept:
        # 篮子为空(拥挤剔除把 20 个全剔光)⇒ 保守口径:整条腿不开仓(无 BTC 腿、无成本)
        price, btc, fund, cost = 0.0, 0.0, 0.0, 0.0
    mine[str(DAYS[d])] = {"pairs": [PAIRS[i] for i in kept], "w": w, "price": price, "btc": btc,
                          "fund": fund, "cost": cost, "ret": price + btc + fund + cost,
                          "dropped": [PAIRS[i] for i in top if i not in kept],
                          "per_coin": [{"pair": PAIRS[i], "w": float(w[j]), "r": float(r[j]),
                                        "contrib": float(-w[j] * r[j])} for j, i in enumerate(kept)]}

# ── 与主脚本逐周比对 ─────────────────────────────────────────────────────────
import urllib.parse
import urllib.request

BASE = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}


def fetch_all(table, filters, order, columns="*"):
    rows, off = [], 0
    while True:
        p = dict(filters)
        p.update({"select": columns, "order": order, "limit": "1000", "offset": str(off)})
        q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in p.items())
        req = urllib.request.Request(f"{BASE}/{table}?{q}", headers=HDR)
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode()
        page = json.loads(body) if body else []
        rows.extend(page)
        if len(page) < 1000:
            break
        off += 1000
    return rows


SUP = {}
for r in fetch_all("state_daily", {"entity": "eq.panel", "feature": "eq.stable_supply_30d"}, "d.asc", "d,value"):
    if r.get("value") is not None:
        SUP[dt.date.fromisoformat(str(r["d"])[:10])] = float(r["value"])

main_weeks = {w["date"]: w for w in MAIN["weeks"]}
bad_basket, d_state = [], 0
d_short, d_btc, d_fund, d_cost, d_ret = 0.0, 0.0, 0.0, 0.0, 0.0
per_week, my_on, on_rets, off_rets = [], 0, [], []
for d in SUN:
    ds = str(DAYS[d])
    m = mine[ds]
    w = main_weeks.get(ds)
    if w is None:
        continue
    if m["pairs"] != w["pairs"]:
        bad_basket.append(ds)
    d_short = max(d_short, abs(m["price"] - w.get("short_price", float("nan"))))
    d_btc = max(d_btc, abs(m["btc"] - w.get("btc_leg", float("nan"))))
    d_fund = max(d_fund, abs(m["fund"] - w["fund"]))
    d_cost = max(d_cost, abs(m["cost"] - w["cost"]))
    d_ret = max(d_ret, abs(m["ret"] - w["ret"]))
    val = SUP.get(DAYS[d])
    on = bool(val is not None and val < 0)
    if on != w["on"]:
        d_state += 1
    per_week.append({"date": ds, "on": on, "n": len(m["pairs"]),
                     "d_short": m["price"] - w.get("short_price", 0.0),
                     "d_btc": m["btc"] - w.get("btc_leg", 0.0),
                     "d_fund": m["fund"] - w["fund"],
                     "d_cost": m["cost"] - w["cost"],
                     "d_ret": m["ret"] - w["ret"],
                     "notional_mine": float(sum(m["w"])), "notional_main": w["notional"]})
    if on:
        my_on += 1
        on_rets.append(m["ret"])
    else:
        off_rets.append(m["ret"])

on_rets = np.array(on_rets)
off_rets = np.array(off_rets)
per_week.sort(key=lambda z: -abs(z["d_ret"]))
out = {
    "n_weeks_compared": len(SUN), "state_weeks_mine": my_on, "state_weeks_main": MAIN["stats"]["n_on"],
    "basket_mismatch_weeks": len(bad_basket), "basket_mismatch_first": bad_basket[:5],
    "max_abs_diff": {"short_price": d_short, "btc_leg": d_btc, "fund": d_fund, "cost": d_cost, "ret": d_ret},
    "state_flag_mismatch_weeks": d_state,
    "mean_on_pct_mine": round(float(on_rets.mean()) * 100, 6) if on_rets.size else None,
    "mean_on_pct_main": round(MAIN["stats"]["mean_on"] * 100, 6),
    "worst_on_pct_mine": round(float(on_rets.min()) * 100, 6) if on_rets.size else None,
    "worst_on_pct_main": round(MAIN["stats"]["worst_on"] * 100, 6),
    "mean_off_uncond_pct_mine": round(float(off_rets.mean()) * 100, 6) if off_rets.size else None,
    "mean_off_uncond_pct_main": round(MAIN["stats"]["mean_off_uncond"] * 100, 6),
    "top10_week_diffs": per_week[:10],
}
# 最差周明细
wd = min([d for d in SUN if str(DAYS[d]) in main_weeks],
         key=lambda d: mine[str(DAYS[d])]["ret"])
wm = mine[str(DAYS[wd])]
out["worst_week_detail"] = {"date": str(DAYS[wd]), "n": len(wm["pairs"]), "price": wm["price"], "btc": wm["btc"],
                            "fund": wm["fund"], "cost": wm["cost"], "ret": wm["ret"],
                            "dropped_crowded": wm["dropped"],
                            "per_coin": sorted(wm["per_coin"], key=lambda z: z["contrib"])}
json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: v for k, v in out.items() if k != "worst_week_detail"}, ensure_ascii=False, indent=1), flush=True)
print("[verify] written", OUT, flush=True)
