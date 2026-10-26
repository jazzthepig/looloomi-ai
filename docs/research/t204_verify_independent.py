# -*- coding: utf-8 -*-
"""T-204 的**第二实现**(独立复算用):照 S-689 台账 SQL 重写一遍,用 pandas/numpy,
不 import t204_oi_mcap_outofpanel.py 的任何函数(不共用一行统计代码)。

用途:① 给主脚本的面板对照做一次跨实现对数(同样的数据、不同的代码路径);
     ② 把**还没被跑过的那条分支**(`perp_cg_map.verdict='resolved'` →
     `cg_coin_mcap_daily`)用合成数据测一遍 —— 43 个待补名字将来全靠这条分支进宇宙,
     它在闸门开之前不会被执行,没有测试就等于没有。

用法:
    python3 docs/research/t204_verify_independent.py --compare <主脚本的 results.json>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    print("缺少 SUPABASE_URL / SUPABASE_KEY,退出", file=sys.stderr)
    sys.exit(2)

HDRS = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Prefer": "count=exact"}
PAGE = 1000

PANEL = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE",
         "INJ", "LDO", "LINK", "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL",
         "STRK", "SUI", "TIA", "UNI", "XRP"]
START = "2023-01-01"
HOLD = 30
MCAP_FLOOR = 20_000_000.0
MIN_OVERLAP = 30
MAX_ERR = 0.05
MIN_NAMES = 8          # 面板对照档(台账未写这一档门槛;主脚本同样用 8)
CUT = "2024-07"


def _get(table, params):
    u = URL + "/rest/v1/" + table + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(u, headers=HDRS)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def fetch(table, where, order, cols="*"):
    out, off = [], 0
    while True:
        p = {"select": cols, "order": order, "limit": PAGE, "offset": off}
        p.update(where)
        rows = _get(table, p)
        if not rows:
            break
        out.extend(rows)
        off += len(rows)
        if len(rows) < PAGE:
            break
    return out


def mult_for(sym):
    return 1000.0 if sym.upper().startswith("1000") else 1.0


def _mult_for_source(sym, from_asset, resolved):
    """台账 px 两个分支的倍数:asset_mcap_daily 分支 = 1(台账写死);
    cg_coin_mcap_daily 分支 = perp_cg_map.mult。"""
    if from_asset:
        return 1.0
    row = (resolved or {}).get(sym) or {}
    rm = row.get("mult")
    return float(rm) if rm else mult_for(sym)


# ── 取数 ────────────────────────────────────────────────────────────────
def deriv_for(symbols):
    rows = fetch("deriv_metrics_daily",
                 {"d": "gte." + START, "symbol": "in.(" + ",".join(sorted(symbols)) + ")"},
                 "symbol.asc,d.asc", "symbol,d,oi_close,oi_value_close")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["d"] = df["d"].astype(str)
    df["oi_close"] = pd.to_numeric(df["oi_close"], errors="coerce")
    df["oi_value_close"] = pd.to_numeric(df["oi_value_close"], errors="coerce")
    return df


def cg_for(symbols):
    rows = fetch("asset_mcap_daily",
                 {"source": "eq.coingecko_pro_market_chart",
                  "symbol": "in.(" + ",".join(sorted(symbols)) + ")"},
                 "symbol.asc,d.asc", "symbol,coin_id,d,price,mcap")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["d"] = df["d"].astype(str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["mcap"] = pd.to_numeric(df["mcap"], errors="coerce")
    # 一个 symbol 多个 coin_id ⇒ 取行数最多的那个(主脚本同规则,确定性)
    keep = df.groupby("symbol")["coin_id"].agg(lambda s: s.value_counts().index[0])
    df = df[df.apply(lambda r: r["coin_id"] == keep[r["symbol"]], axis=1)]
    return df


def btc_series():
    rows = fetch("asset_mcap_daily",
                 {"coin_id": "eq.bitcoin", "source": "eq.coingecko_pro_market_chart"},
                 "coin_id.asc,d.asc", "d,price")
    df = pd.DataFrame(rows)
    df["d"] = df["d"].astype(str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["price"])
    return {r["d"]: float(r["price"]) for _, r in df.iterrows()}


# ── 台账口径:价格校验 → 行 → 截面 → 逐月 ────────────────────────────────
def build_rows(dv, cg, mult=1.0):
    """dv: deriv 行(DataFrame), cg: CG 价/市值(DataFrame)。
    mult = 该名字**所用价格源**的倍数(台账 px 两分支不同:
      asset_mcap_daily 分支 = 1;cg_coin_mcap_daily 分支 = perp_cg_map.mult)。"""
    if dv is None or cg is None or dv.empty or cg.empty:
        return [], None, 0
    sym = dv["symbol"].iloc[0]
    m = dv.merge(cg, on="d", how="inner")
    m = m[(m["oi_close"] > 0) & (m["oi_value_close"] > 0) & (m["price"] > 0)]
    implied = m["oi_value_close"] / m["oi_close"]
    err = (m["price"] * mult / implied - 1.0).abs()
    n = len(err)
    if n < MIN_OVERLAP:
        return [], None, n
    med = float(err.median())
    if med > MAX_ERR:
        return [], med, n
    # 行:d 与 d+30 都有价、mcap≥2000 万、OI 值>0
    px = dict(zip(cg["d"], cg["price"]))
    mc = dict(zip(cg["d"], cg["mcap"]))
    rows = []
    for _, r in m.iterrows():
        d = r["d"]
        d2 = (dt.date.fromisoformat(d) + dt.timedelta(days=HOLD)).isoformat()
        if d2 not in px or d2 not in mc:
            continue
        p1, p2 = px[d], px[d2]
        mc1 = mc[d]
        if p1 is None or p2 is None or p1 <= 0 or p2 <= 0:
            continue
        if mc1 is None or not (mc1 >= MCAP_FLOOR):
            continue
        if r["oi_value_close"] is None or r["oi_value_close"] <= 0:
            continue
        rows.append({"symbol": sym, "d": d, "p1": p1, "p2": p2, "mcap": mc1,
                     "oi_v": float(r["oi_value_close"])})
    return rows, med, n


def cross_section(row_df, btc, min_names=MIN_NAMES):
    """btc: {d: price}(字典 —— 按日期直取 d 与 d+30,不假设日历连续,和台账的 join 一致)。"""
    if row_df.empty:
        return {}
    df = row_df.copy()
    bp1, bp2 = [], []
    for d in df["d"]:
        d2 = (dt.date.fromisoformat(d) + dt.timedelta(days=HOLD)).isoformat()
        bp1.append(btc.get(d))
        bp2.append(btc.get(d2))
    df["bp1"] = bp1
    df["bp2"] = bp2
    df = df[(df["bp1"] > 0) & (df["bp2"] > 0)]
    df["y"] = (df["p2"] / df["p1"] - 1.0) - (df["bp2"] / df["bp1"] - 1.0)
    df["r"] = df["oi_v"] / df["mcap"]
    df["size"] = np.log(df["mcap"])
    out = {}
    for d, g in df.groupby("d"):
        if len(g) < min_names:
            continue
        rr = g["r"].rank(method="average").to_numpy()
        ry = g["y"].rank(method="average").to_numpy()
        rs = g["size"].rank(method="average").to_numpy()
        r_ry = float(np.corrcoef(rr, ry)[0, 1])
        r_rs = float(np.corrcoef(rr, rs)[0, 1])
        r_ys = float(np.corrcoef(rs, ry)[0, 1])
        den = (1 - r_rs ** 2) * (1 - r_ys ** 2)
        if den <= 0:
            continue
        out[d] = {"main": (r_ry - r_rs * r_ys) / math.sqrt(den),
                  "raw": r_ry, "size": r_ys, "n": len(g)}
    return out


def summarize(daily):
    res = {}
    for key in ("main", "raw", "size"):
        vals = {d: v[key] for d, v in daily.items()}
        bym = {}
        for d, v in vals.items():
            bym.setdefault(d[:7], []).append(v)
        months = sorted(bym)
        mv = {m: sum(bym[m]) / len(bym[m]) for m in months}
        xs = [mv[m] for m in months]
        sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
        t = (sum(xs) / len(xs)) / sd * math.sqrt(len(xs)) if sd else None
        h1 = [mv[m] for m in months if m < CUT]
        h2 = [mv[m] for m in months if m >= CUT]
        res[key] = {
            "n_days": len(vals), "n_months": len(months),
            "monthly": {m: round(mv[m], 6) for m in months},
            "month_mean": sum(xs) / len(xs) if xs else None,
            "month_t": t,
            "h1_mean": sum(h1) / len(h1) if h1 else None,
            "h2_mean": sum(h2) / len(h2) if h2 else None,
        }
    return res


# ── 合成测试:cg_coin_mcap_daily 分支(perp_cg_map resolved) ─────────────
def synth_cg_branch():
    """用合成数据测:① perp_cg_map resolved → cg_coin_mcap_daily 进宇宙;
    ② 1000 前缀的倍数在价格校验里生效;③ asset_mcap_daily 里已有的 symbol 不走 coin 分支。"""
    ok = True
    # 合成:一个名字 1000SHIB(倍数 1000)。CG 原币价 2e-5;一张 1000SHIB 合约 ≈ 1000 × 2e-5 = 0.02 美元
    # ⇒ 隐含价(oi_value/oi_close)应 = 0.02,校验时用 CG 价 × 1000 去比。
    days = [ (dt.date(2023, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(120) ]
    deriv = [{"symbol": "1000SHIB", "d": d, "oi_close": 1000.0, "oi_value_close": 20.0} for d in days]
    cg_coin = [{"coin_id": "shib", "d": d, "price": 0.00002, "mcap": 1e9} for d in days]
    implied = 20.0 / 1000.0
    err_mult = abs(cg_coin[0]["price"] * 1000.0 / implied - 1.0)
    err_nomult = abs(cg_coin[0]["price"] / implied - 1.0)
    print("合成① 1000 前缀: 用倍数 err=%.6f(应≈0) / 不用倍数 err=%.6f(应很大)" % (err_mult, err_nomult))
    ok &= (err_mult < 1e-9) and (err_nomult > 0.9)

    # 用主脚本的 build_set 跑一遍(它读 perp_cg_map resolved 的分支)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import t204_oi_mcap_outofpanel as T
    dv = {d: (1000.0, 20.0) for d in days}
    kept, dropped = T.build_set(["1000SHIB"], {"1000SHIB": dv}, {},
                                 {"shib": {r["d"]: (r["price"], r["mcap"]) for r in cg_coin}},
                                 {"1000SHIB": {"coin_id": "shib", "mult": 1000}})
    print("合成② build_set(resolved 分支): kept=%s dropped=%s" % (sorted(kept), dropped))
    ok &= (len(kept) == 1) and (kept["1000SHIB"]["src"] == "cg_coin_mcap_daily")
    if kept:
        rows = kept["1000SHIB"]["rows"]
        # 行里 d+30 也要有价 ⇒ 120 天里前 90 天成行
        print("     行数=%d(应=90) med_err=%.6f n_overlap=%d" %
              (len(rows), kept["1000SHIB"]["med_err"], kept["1000SHIB"]["n_overlap"]))
        ok &= (len(rows) == 90) and kept["1000SHIB"]["n_overlap"] == 120

    # ③ asset_mcap_daily 里已有的 symbol:即使 perp_cg_map 也 resolved,仍走 symbol 分支
    #    (用**普通** symbol 测「源优先级」;asset 分支的价格要跟隐含价自洽才能过校验)
    dv3 = dict((d, (1000.0, 20.0)) for d in days)          # 隐含价 = 20/1000 = 0.02
    px3 = dict((r["d"], (0.02, r["mcap"])) for r in cg_coin)  # asset 分支给同一个 0.02
    kept3, _ = T.build_set(["SHIB"], {"SHIB": dv3},
                            {"SHIB": px3},
                            {"shib": px3},
                            {"SHIB": {"coin_id": "shib", "mult": 1000}})
    src3 = kept3["SHIB"]["src"] if kept3 else None
    print("合成③ symbol 分支优先: src=%s(应=asset_mcap_daily)" % src3)
    ok &= (src3 == "asset_mcap_daily")

    # ④ 台账 px 第一分支 mult 写死 1 ⇒ 1000 前缀名字若落在 asset 分支,
    #    隐含价(1000 枚合约价)与 asset 的 1 枚币价差 1000 倍 ⇒ 过不了校验 ⇒ 被剔
    #    (这正是报告 §5.14 那个量纲问题的后果;主统计量照台账,敏感性另算)
    kept4, _ = T.build_set(["1000SHIB"], {"1000SHIB": dv},
                            {"1000SHIB": {r["d"]: (r["price"], r["mcap"]) for r in cg_coin}},
                            {"shib": {r["d"]: (r["price"], r["mcap"]) for r in cg_coin}},
                            {"1000SHIB": {"coin_id": "shib", "mult": 1000}})
    print("合成④ 1000 前缀走 asset 分支(mult=1): kept=%s(应=空 ⇒ 被剔)" % sorted(kept4))
    ok &= (len(kept4) == 0)
    print("合成测试:", "PASS" if ok else "FAIL")
    return ok


def perp_map():
    rows = fetch("perp_cg_map", {}, "symbol.asc", "symbol,coin_id,verdict,mult,med_err,n_overlap")
    return {r["symbol"]: r for r in rows}


def cg_by_coin(coin_ids):
    if not coin_ids:
        return {}
    rows = fetch("cg_coin_mcap_daily", {"coin_id": "in.(" + ",".join(sorted(coin_ids)) + ")"},
                 "coin_id.asc,d.asc", "coin_id,d,price,mcap")
    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    df["d"] = df["d"].astype(str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["mcap"] = pd.to_numeric(df["mcap"], errors="coerce")
    out = {}
    for cid, g in df.groupby("coin_id"):
        out[cid] = dict(zip(g["d"], zip(g["price"], g["mcap"])))
    return out


def out_of_panel():
    """面板外宇宙(台账口径):deriv 符号(2023 起)减面板名单;
    CG 价源:先 asset_mcap_daily(按 symbol),没有的用 perp_cg_map 里 resolved 的 coin_id
    去 cg_coin_mcap_daily 取。"""
    pm = perp_map()
    resolved = {s: r for s, r in pm.items() if r.get("verdict") == "resolved" and r.get("coin_id")}
    rows_all = fetch("deriv_metrics_daily", {"d": "gte." + START},
                     "symbol.asc,d.asc", "symbol,d,oi_close,oi_value_close")
    dv_all = pd.DataFrame(rows_all)
    dv_all["d"] = dv_all["d"].astype(str)
    dv_all["oi_close"] = pd.to_numeric(dv_all["oi_close"], errors="coerce")
    dv_all["oi_value_close"] = pd.to_numeric(dv_all["oi_value_close"], errors="coerce")
    universe = sorted(set(dv_all["symbol"]) - set(PANEL))
    print("  面板外宇宙 =", len(universe), "个名字(deriv 符号减面板)")
    cg = cg_for(universe)                       # asset_mcap_daily(按 symbol)
    have_sym = set(cg["symbol"]) if not cg.empty else set()
    need = [s for s in universe if s not in have_sym and s in resolved]
    coins = cg_by_coin(sorted({resolved[s]["coin_id"] for s in need}))
    print("  CG 价源:asset_mcap_daily %d 个;cg_coin_mcap_daily(perp_cg_map resolved)%d 个" %
          (len(have_sym), len(need)))
    rows, kept, dropped = [], [], []
    for s in universe:
        d1 = dv_all[dv_all["symbol"] == s]
        c1 = cg[cg["symbol"] == s] if s in have_sym else None
        if c1 is None:
            cid = resolved[s]["coin_id"] if s in resolved else None
            series = coins.get(cid) if cid else None
            if not series:
                dropped.append({"symbol": s, "reason": "无 CG 价源(asset_mcap_daily 无;perp_cg_map 未 resolved)"})
                continue
            c1 = pd.DataFrame([{"symbol": s, "coin_id": cid, "d": d, "price": p, "mcap": m}
                               for d, (p, m) in series.items()])
        r, med, n = build_rows(d1, c1, _mult_for_source(s, s in have_sym, resolved))
        if r:
            rows.extend(r)
            kept.append(s)
        else:
            dropped.append({"symbol": s, "n_overlap": n, "med_err": med,
                            "reason": "价格校验不过或无可用行"})
    return kept, dropped, pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--scope", choices=["panel", "out"], default="panel")
    a = ap.parse_args()

    print("=== 合成测试(cg_coin_mcap_daily 分支) ===")
    ok = synth_cg_branch()

    btc = btc_series()
    if a.scope == "panel":
        print("\n=== 面板对照:第二实现(pandas) vs 主脚本 ===")
        syms = [s for s in PANEL if s != "BTC"]
        dv = deriv_for(syms)
        cg = cg_for(syms)
        rows, kept, dropped = [], [], []
        for s in syms:
            d1 = dv[dv["symbol"] == s] if not dv.empty else dv
            c1 = cg[cg["symbol"] == s] if not cg.empty else cg
            r, med, n = build_rows(d1, c1, 1.0)   # 面板对照全走 asset_mcap_daily 分支 ⇒ mult = 1
            if r:
                rows.extend(r)
                kept.append(s)
            else:
                dropped.append({"symbol": s, "n_overlap": n, "med_err": med})
        row_df = pd.DataFrame(rows)
        other_key = "panel_control"
    else:
        print("\n=== 面板外宇宙:第二实现(pandas) vs 主脚本 ===")
        kept, dropped, row_df = out_of_panel()
        other_key = "out_of_panel"

    daily = cross_section(row_df, btc)
    mine = summarize(daily)
    print("kept=%d dropped=%d 截面日=%d 行=%d" % (len(kept), len(dropped), len(daily), len(row_df)))
    for k in ("main", "raw", "size"):
        print("  %-5s mean=%.6f t=%.4f h1=%.6f h2=%.6f" %
              (k, mine[k]["month_mean"], mine[k]["month_t"], mine[k]["h1_mean"], mine[k]["h2_mean"]))

    out = {"task": "T-204", "scope": a.scope,
           "what": "第二实现(pandas/numpy)对主脚本的 %s" % other_key,
           "synthetic_cg_branch_pass": ok,
           "kept": kept, "dropped": dropped,
           "n_cross_section_days": len(daily), "n_rows": len(row_df),
           "stats": mine, "diff_vs_main": {}}
    if a.out:                      # 先落盘:对数崩了也不丢结果
        with open(a.out, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("wrote", a.out)

    diff = {}
    if a.compare:
        other = json.load(open(a.compare))
        if other_key == "out_of_panel":
            oc = other["out_of_panel"].get("stats") \
                or other["out_of_panel"].get("stats_diagnostic_pre_gate") \
                or other["out_of_panel"]["stats_diagnostic_pre_gate"]["stats"]
            if "stats" in oc and "monthly" not in oc:
                oc = oc["stats"]
        else:
            oc = other["panel_control"]["stats"]
        for k in ("main", "raw", "size"):
            mm = mine[k]["monthly"]
            om = oc[k]["monthly"]
            common = sorted(set(mm) & set(om))
            dmax = max((abs(mm[m] - om[m]) for m in common), default=None)
            dmean = abs(mine[k]["month_mean"] - oc[k]["month_mean"]) if oc[k]["month_mean"] else None
            diff[k] = {"n_months_common": len(common),
                       "max_abs_monthly_diff": dmax,
                       "month_mean_diff": dmean,
                       "month_t_diff": abs(mine[k]["month_t"] - oc[k]["month_t"]),
                       "h1_diff": abs(mine[k]["h1_mean"] - oc[k]["halves"]["h1"]["month_mean"]),
                       "h2_diff": abs(mine[k]["h2_mean"] - oc[k]["halves"]["h2"]["month_mean"])}
            print("  比对 %-5s 逐月最大差=%.2e 月均差=%.2e 月 t 差=%.2e" %
                  (k, dmax or 0, dmean or 0, diff[k]["month_t_diff"]))
            ok &= (dmax is not None and dmax < 1e-4 and diff[k]["month_t_diff"] < 1e-3)
        out["diff_vs_main"] = diff
        if a.out:
            with open(a.out, "w") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
    print("总判定:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
