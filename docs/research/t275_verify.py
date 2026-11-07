#!/usr/bin/env python3
"""T-275 核对 —— 手算抽检 + 敏感性(不改判据,只核数字)。只读。"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import t275_early_warning as T  # noqa: E402

out = {}

hist = T.load_binance_hist(False)
delist = T.load_delisting(False)
series = T.build_series(hist)
mends = T.month_ends()

# ── 1. 公告的时间分布(全部 164 / 有 binance_hist 的 67) ────────────────────
ann_all = {r["symbol"]: str(r["d0"]) for r in delist}
ann_with_hist = {s: d for s, d in ann_all.items() if s in series}
out["ann_year_all164"] = sorted(Counter(d[:4] for d in ann_all.values()).items())
out["ann_year_with_binance_hist"] = sorted(Counter(d[:4] for d in ann_with_hist.values()).items())
out["n_with_hist"] = len(ann_with_hist)
out["n_all"] = len(ann_all)

# 第一个有 binance_hist 的公告之前,该代号有多少根日线(召回分母的核对)
prior_hist = {}
for s, d in ann_with_hist.items():
    ser = series[s]
    o = date.fromisoformat(d).toordinal()
    prior_hist[s] = int(np.searchsorted(ser.ord, o, side="left"))
out["prior_bars_before_announce"] = {"min": min(prior_hist.values()), "max": max(prior_hist.values()),
                                     "median": int(np.median(list(prior_hist.values()))),
                                     "n_ge_180": sum(1 for v in prior_hist.values() if v >= 180)}

# ── 2. 抽检:标记且结果为真的观察,逐个手算 ────────────────────────────────
sections = T.build_cross_sections(series, delist, mends)
obs = T.excess_returns(sections, series)
marked = [r for r in obs if r["marked"]]
hits = [r for r in marked if r["result"] == 1]
out["n_marked"] = len(marked)
out["n_marked_hit"] = len(hits)

checks = []
for r in hits[:3]:
    ser = series[r["sym"]]
    m = r["_m"]
    # 手算 L:过去 30 个自然日的 close×volume 中位数
    o = date.fromisoformat(m).toordinal()
    vals = []
    for i, dd in enumerate(ser.dates):
        oo = date.fromisoformat(dd).toordinal()
        if o - 29 <= oo <= o and ser.to[i] is not None:
            vals.append(ser.to[i])
    L_manual = float(np.median(vals))
    # 当月截面里 L 的百分位(手算排名)
    sec = next(s for s in sections if s["m"] == m)
    ordered = sorted(sec["recs"], key=lambda x: (x["L"], x["sym"]))
    rank = [i for i, x in enumerate(ordered) if x["sym"] == r["sym"]][0]
    pct_manual = rank / (len(ordered) - 1)
    ad = date.fromisoformat(str(r["ann_date"]))
    checks.append({
        "sym": r["sym"], "month_end": m, "ann": r["ann_date"],
        "L_script": round(r["L"], 6), "L_manual": round(L_manual, 6),
        "L_match": abs(r["L"] - L_manual) < 1e-9,
        "pct_script": round(r["pct"], 4), "pct_manual": round(pct_manual, 4),
        "n_in_section": len(ordered),
        "in_window": 0 < (ad.toordinal() - o) <= 90,
        "days_to_ann": ad.toordinal() - o,
    })
out["spot_checks"] = checks

# ── 3. 90 天超额抽检(手算一条) ──────────────────────────────────────────
ex_ok = [r for r in marked if r["excess_90d"] is not None]
r0 = ex_ok[0]
ser = series[r0["sym"]]
m90 = (date.fromisoformat(r0["_m"]) + timedelta(days=90)).isoformat()
btc = series["BTC"]
tok_in = ser.closes[ser.idx_on(r0["_m"])]
tok_out = T.price_on_or_after(ser.dates, ser.closes, m90)
btc_in = btc.closes[btc.idx_on(r0["_m"])]
btc_out = T.price_on_or_after(btc.dates, btc.closes, m90)
out["excess_spot"] = {
    "sym": r0["sym"], "m": r0["_m"], "tok_in": tok_in, "tok_out": tok_out,
    "btc_in": btc_in, "btc_out": btc_out,
    "ret": T.long_return(tok_in, tok_out), "btc_ret": T.long_return(btc_in, btc_out),
    "excess_script": r0["excess_90d"],
    "match": abs((T.long_return(tok_in, tok_out) - T.long_return(btc_in, btc_out)) - r0["excess_90d"]) < 1e-12,
}

# ── 4. 敏感性 A:把 BTC 从宇宙里剔掉再算 ────────────────────────────────
def judge_variant(exclude_btc=False, recall_variant=False):
    secs = []
    for s in sections:
        recs = [r for r in s["recs"] if not (exclude_btc and r["sym"] == "BTC")]
        n = len(recs)
        for k, r in enumerate(sorted(recs, key=lambda x: (x["L"], x["sym"]))):
            pass
        ordered = sorted(recs, key=lambda x: (x["L"], x["sym"]))
        for k, r in enumerate(ordered):
            r2 = dict(r)
            r2["pct"] = (k / (n - 1)) if n > 1 else 0.0
            r2["marked"] = r2["pct"] <= T.MARK_PCT
            r2["_m"] = s["m"]
        secs.append({"m": s["m"], "recs": ordered, "n": n})
    # 判据(a)(c)用变动后的截面;(b)(d)用原值(超额与标记无关于宇宙构成)
    all_obs = [r for s in secs for r in s["recs"]]
    base = sum(r["result"] for r in all_obs) / len(all_obs)
    mk = [r for r in all_obs if r["marked"]]
    prec = sum(r["result"] for r in mk) / len(mk)
    segs = {}
    for tag, (lo, hi) in (("seg1", T.SEG1), ("seg2", T.SEG2)):
        pool = [r for s in secs if lo <= s["m"][:7] <= hi for r in s["recs"]]
        m2 = [r for r in pool if r["marked"]]
        sb = sum(r["result"] for r in pool) / len(pool)
        sp = sum(r["result"] for r in m2) / len(m2)
        segs[tag] = {"base": sb, "prec": sp, "mult": sp / sb}
    return {"base": base, "prec": prec, "mult": prec / base, "segs": segs}

out["sens_exclude_btc"] = judge_variant(exclude_btc=True)

# ── 5. 敏感性 B:召回口径 —— 公告前 90 天内任一月末被标记(变体,只报) ──────
by_sym = defaultdict(list)
for s in sections:
    for r in s["recs"]:
        by_sym[r["sym"]].append((s["m"], r))
ann_map = {r["sym"]: r["ann_date"] for r in obs if r["ann_date"]}
var_num = var_den = 0
for sym, ad in ann_map.items():
    o_ad = date.fromisoformat(ad).toordinal()
    cands = [(m, r) for (m, r) in by_sym.get(sym, []) if 0 < o_ad - date.fromisoformat(m).toordinal() <= 90]
    if not cands:
        continue
    var_den += 1
    var_num += int(any(r["marked"] for _, r in cands))
out["recall_variant_any_of_90d"] = {"num": var_num, "den": var_den, "recall": var_num / var_den if var_den else None}
out["recall_primary"] = {"num": 17, "den": 67}

# ── 6. BTC 在宇宙里的位置 + L 的量纲 ────────────────────────────────────
sec0 = sections[0]
b0 = next(r for r in sec0["recs"] if r["sym"] == "BTC")
out["btc_in_universe"] = {"first_month": sec0["m"], "pct": b0["pct"], "L": b0["L"],
                          "marked": b0["marked"], "n": sec0["n"]}
allL = [r["L"] for r in obs]
out["L_quantiles"] = {q: float(np.quantile(allL, q)) for q in (0.01, 0.1, 0.5, 0.9, 0.99)}
out["L_zero_frac"] = float(np.mean([1.0 if v <= 0 else 0.0 for v in allL]))

# ── 7. volume 的量纲(BTC 一行):close × volume = 计价货币成交额 ─────────────
btc_raw = [r for r in hist if r["symbol"] == "BTC" and r["trade_date"] == "2022-01-31"]
out["btc_raw_row"] = btc_raw
if btc_raw:
    b = btc_raw[0]
    out["btc_turnover"] = (b["close"] * b["volume"]) if b.get("volume") else None

# ── 8. 召回随「距公告几个月」的衰减 ────────────────────────────────────
lag_rows = []
for k in (1, 2, 3, 4, 6):
    num = den = 0
    for sym, ad in ann_map.items():
        cands = sorted([(m, r) for (m, r) in by_sym.get(sym, []) if m < ad], key=lambda x: x[0])
        if len(cands) < k:
            continue
        m_k, r_k = cands[-k]
        den += 1
        num += int(r_k["marked"])
    lag_rows.append({"lag_month_ends": k, "n": den, "n_marked": num, "recall": num / den if den else None})
out["recall_by_lag"] = lag_rows
pcts = [x["pct"] for x in json.load(open(os.path.join(HERE, "t275_results.json")))["recall_detail"]]
out["pct_at_last_month_end"] = {"median": float(np.median(pcts)), "n_le_0.20": sum(1 for p in pcts if p <= 0.20),
                                 "n_le_0.30": sum(1 for p in pcts if p <= 0.30), "n": len(pcts)}

print(json.dumps(out, indent=1, default=str))
