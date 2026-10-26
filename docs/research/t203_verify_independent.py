#!/usr/bin/env python3
"""T-203 独立核对(不复用主脚本的缓存与统计函数):直接从 Supabase 原始行重新算一遍,
回答三个问题:
  Q1  主脚本用的那批重建行是不是 S-687 附记二修复**之后**写的(= funding 项在分数里)?
  Q2  面板本身(σ≠BTC 的 crypto 行、alpha)跟表 `cis_standard_outcomes` 对不对得上?
  Q3  主脚本给的逐月 ρ / 月 t / 判定,能不能用**另写一遍**的代码复现出来。
只读;不写库。用法: python3 docs/research/t203_verify_independent.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
OUT = {}


def get(table, params, page=1000):
    rows, off = [], 0
    while True:
        p = dict(params)
        p["limit"] = page
        p["offset"] = off
        ps = "&".join("%s=%s" % (k, urllib.parse.quote(str(v), safe="(),.*:|+-=<>")) for k, v in p.items())
        req = urllib.request.Request(URL + "/rest/v1/" + table + "?" + ps, headers=HDR)
        last = None
        for i in range(5):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    last = json.loads(r.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and i < 4:
                    continue
                raise
        rows.extend(last)
        if len(last) < page:
            break
        off += page
    return rows


def spearman(x, y):
    def rk(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rk(x), rk(y)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def fr_adj(fr):
    def interp(x, x0, x1, y0, y1):
        lo, hi = min(y0, y1), max(y0, y1)
        if x1 == x0:
            return (y0 + y1) / 2
        t = (x - x0) / (x1 - x0)
        return max(lo, min(hi, y0 + t * (y1 - y0)))
    if fr > 0.0005:
        return interp(fr, 0.0005, 0.002, -8.0, -15.0)
    if fr > 0.0001:
        return interp(fr, 0.0001, 0.0005, 3.0, 0.0)
    if fr > -0.0001:
        return 0.0
    if fr > -0.0005:
        return 2.0
    return -3.0


print("[Q1] cis_rebuild_daily 的批次时间戳 + funding 覆盖率 ...", flush=True)
rb = get("cis_rebuild_daily",
         {"select": "symbol,d,score,raw_score,pillar_o,computed_at,inputs",
          "code_ref": "eq.cis-standard-v1.3", "order": "symbol.asc,d.asc"})
batches = defaultdict(int)
fr_present = defaultdict(int)
fr_null = defaultdict(int)
for r in rb:
    b = (r.get("computed_at") or "")[:19]
    batches[b] += 1
    if (r.get("inputs") or {}).get("funding") is None:
        fr_null[b] += 1
    else:
        fr_present[b] += 1
OUT["Q1_batches"] = {b: {"rows": n, "fr_present": fr_present[b], "fr_null": fr_null[b]}
                      for b, n in sorted(batches.items())}
print("   批次:", json.dumps(OUT["Q1_batches"], indent=2)[:1500])

# 取最新批次
newest = sorted(batches)[-1]
rb_new = [r for r in rb if (r.get("computed_at") or "")[:19] == newest]
print("   最新批次 %s: %d 行" % (newest, len(rb_new)))

print("[Q2] cis_standard_outcomes 可读性 + 与重建面板对账 ...", flush=True)
try:
    so = get("cis_standard_outcomes", {"select": "symbol,d,grp,alpha", "order": "symbol.asc,d.asc", "limit": 5})
    OUT["Q2_outcomes_readable"] = True
    print("   表可读,样本:", json.dumps(so[:2], ensure_ascii=False)[:300])
except urllib.error.HTTPError as e:
    OUT["Q2_outcomes_readable"] = False
    OUT["Q2_outcomes_error"] = "HTTP %s" % e.code
    print("   表不可读: HTTP %s(与主脚本记录一致则改用重建面板对账)" % e.code)

# 面板重建:alpha = 收盘(d+30)/收盘(d) − 1 减 BTC 同式
mc = get("asset_mcap_daily",
         {"select": "coin_id,d,price", "source": "eq.coingecko_pro_market_chart",
          "coin_id": "in.(bitcoin,ethereum,solana,binancecoin,ripple,cardano,avalanche-2,polkadot,"
                     "near,sui,aptos,hyperliquid,arbitrum,optimism,polygon-ecosystem-token,"
                     "starknet,uniswap,aave,lido-dao,pendle,chainlink,injective-protocol,celestia,"
                     "ondo-finance,sky,maker,matic-network)",
          "order": "coin_id.asc,d.asc"})
px = defaultdict(dict)
for r in mc:
    if r.get("price") is not None:
        px[r["coin_id"]][r["d"][:10]] = float(r["price"])
MIG = {"SKY": ("maker", 24000.0), "POL": ("matic-network", 1.0)}
SYM2COIN = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
    "NEAR": "near", "SUI": "sui", "APT": "aptos", "HYPE": "hyperliquid",
    "ARB": "arbitrum", "OP": "optimism", "POL": "polygon-ecosystem-token",
    "STRK": "starknet", "UNI": "uniswap", "AAVE": "aave", "LDO": "lido-dao",
    "PENDLE": "pendle", "LINK": "chainlink", "INJ": "injective-protocol",
    "TIA": "celestia", "ONDO": "ondo-finance", "SKY": "sky",
}
rb_price = defaultdict(dict)
for r in rb_new:
    inp = r.get("inputs") or {}
    if inp.get("price") is not None:
        rb_price[r["symbol"]][r["d"][:10]] = float(inp["price"])
closes = {}
for sym, coin in SYM2COIN.items():
    if sym in MIG:
        oc, ratio = MIG[sym]
        old_px, new_px = px.get(oc, {}), px.get(coin, {})
        boundary = None
        for d in sorted(rb_price.get(sym, {})):
            stored = rb_price[sym][d]
            cn, co = new_px.get(d), old_px.get(d)
            co = co / ratio if co is not None else None
            if cn is None and co is None:
                continue
            use_old = (cn is None) if co is not None else False
            if cn is not None and co is not None:
                use_old = abs(stored - co) < abs(stored - cn)
            if use_old:
                boundary = d
            else:
                break
        ser = {d: v / ratio for d, v in old_px.items() if boundary is not None and d <= boundary}
        ser.update({d: v for d, v in new_px.items() if boundary is None or d > boundary})
        closes[sym] = ser
    else:
        closes[sym] = dict(px.get(coin, {}))
btc = closes["BTC"]
last_close = max(max(v) for v in closes.values() if v)

# 点位:重建的 signal_pct(与主脚本同法:同批次的重建)
rb_pts = get("cis_rebuild_daily",
             {"select": "symbol,d,asset_class,signal_pct,code_ref",
              "code_ref": "eq.cis-standard-v1.3", "order": "symbol.asc,d.asc"})
points = {}
for r in rb_pts:
    d = r["d"][:10]
    if r.get("signal_pct"):
        points[(r["symbol"], d)] = r.get("signal_pct")

rbkey = {(r["symbol"], r["d"][:10]): r for r in rb_new}
panel = defaultdict(list)
for (sym, d), sig in points.items():
    dp = (date.fromisoformat(d) + timedelta(days=30)).isoformat()
    if dp > last_close:
        continue
    p0, p1 = closes.get(sym, {}).get(d), closes.get(sym, {}).get(dp)
    b0, b1 = btc.get(d), btc.get(dp)
    if None in (p0, p1, b0, b1):
        continue
    r2 = rbkey.get((sym, d))
    if not r2:
        continue
    fr = (r2.get("inputs") or {}).get("funding")
    panel[d].append({"symbol": sym, "alpha": round((p1 / p0 - 1) - (b1 / b0 - 1), 6),
                     "fr_adj": fr_adj(float(fr)) if fr is not None else None,
                     "fr": float(fr) if fr is not None else None,
                     "score": r2.get("score")})
OUT["Q2_panel_days"] = len(panel)
OUT["Q2_panel_rows"] = sum(len(v) for v in panel.values())
print("   重建面板: %d 天 %d 行" % (len(panel), OUT["Q2_panel_rows"]))

print("[Q3] 用另写的代码复算逐月 ρ 与月 t,与主脚本对数 ...", flush=True)
d_funding = {}
for d, rows in panel.items():
    rr = [r for r in rows if r["fr_adj"] is not None and r["symbol"] != "BTC"]
    if len(rr) < 8:
        continue
    vals = [r["fr_adj"] for r in rr]
    if len(set(vals)) < 2:
        continue
    rho = spearman(vals, [r["alpha"] for r in rr])
    if math.isfinite(rho):
        d_funding[d] = rho
bym = defaultdict(list)
for d, v in d_funding.items():
    bym[d[:7]].append(v)
monthly = {m: round(sum(v) / len(v), 6) for m, v in sorted(bym.items())}
vals = list(monthly.values())
n_m = len(vals)
mean = sum(vals) / n_m
sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n_m - 1))
t = mean / sd * math.sqrt(n_m)
h1 = [v for m, v in monthly.items() if m < "2024-07"]
h2 = [v for m, v in monthly.items() if m >= "2024-07"]
OUT["Q3_funding_monthly"] = monthly
OUT["Q3_funding_summary"] = {"n_months": n_m, "mean_rho": round(mean, 6), "monthly_sd": round(sd, 6),
                              "t": round(t, 6), "half1": round(sum(h1) / len(h1), 6) if h1 else None,
                              "half2": round(sum(h2) / len(h2), 6) if h2 else None}
print("   核对版 funding: n_months=%d mean_rho=%.6f t=%.6f half1=%.6f half2=%.6f"
      % (n_m, mean, t, sum(h1) / len(h1), sum(h2) / len(h2)))

# 与主脚本结果逐月对数
main_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t203_results.json")
if os.path.exists(main_path):
    main_res = json.load(open(main_path))
    mm = main_res.get("funding_term", {}).get("monthly", {})
    diffs = []
    for m in sorted(set(mm) | set(monthly)):
        a, b = mm.get(m), monthly.get(m)
        if a is None or b is None:
            diffs.append({"month": m, "main": a, "mine": b, "diff": None})
        else:
            diffs.append({"month": m, "main": a, "mine": b, "diff": round(a - b, 9)})
    worst = max((abs(d["diff"]) for d in diffs if d["diff"] is not None), default=None)
    OUT["Q3_monthly_diff_max_abs"] = worst
    OUT["Q3_monthly_diff_count"] = len(diffs)
    OUT["Q3_monthly_mismatch"] = [d for d in diffs if d["diff"] is None or abs(d["diff"]) > 1e-6]
    ms = main_res.get("funding_term", {})
    OUT["Q3_main_summary"] = {"n_months": ms.get("n_months"), "mean_rho": ms.get("mean_rho"),
                              "t": ms.get("t"), "half1": ms.get("half1", {}).get("mean_rho"),
                              "half2": ms.get("half2", {}).get("mean_rho")}
    print("   主脚本: n_months=%s mean_rho=%s t=%s half1=%s half2=%s"
          % (ms.get("n_months"), ms.get("mean_rho"), ms.get("t"),
             ms.get("half1", {}).get("mean_rho"), ms.get("half2", {}).get("mean_rho")))
    print("   逐月最大绝对差: %s" % worst)

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t203_verify.json")
with open(out_path, "w") as f:
    json.dump(OUT, f, indent=2, ensure_ascii=False)
print("写 %s" % out_path)
