#!/usr/bin/env python3
"""T-222 —— ④ 候选的量测:HL 现货多 + 永续空(cash-and-carry)在 ① 的 24 个加密名上值多少。

只读 SELECT(不写库、不 DDL)。零分布 / A/B / 多空盈亏只用 src/data/evaluation/apparatus.py。
用法:
  python3 docs/research/t222_funding_carry.py probe   # 数据形状探针(改同一个文件再跑)
  python3 docs/research/t222_funding_carry.py run     # 最终量测,写 t222_results.json
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from src.data.evaluation.apparatus import (  # noqa: E402
    ab_test,
    brier,
    block_permute,
    long_return,
    null_distribution,
    percentile_of,
    price_on_or_after,
    short_return,
)

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}

CRYPTO_CLASSES = ("L1", "L2", "DeFi", "RWA", "Memecoin", "Gaming", "AI", "Infrastructure")
START = "2023-01-01"
END = "2026-10-31"
HL_START = "2026-09-05"
FEE_SPOT = 0.0004    # 现货 taker 4bp
FEE_PERP = 0.00035   # 永续 taker 3.5bp
SWITCH_COST = FEE_SPOT + FEE_PERP  # 一次开平(多空各一次 taker)
SRC_PRIORITY = ("binance_hist", "hyperliquid", "coingecko_pro_ohlc", "coingecko")


def sb(path, params):
    """读一页。params 必须带 order=(翻页边界会漂,规则要求)。
    params 传 list[tuple] 时同名 key 会重复出现(PostgREST 里是 AND)。"""
    if isinstance(params, dict):
        params = list(params.items())
    q = urllib.parse.urlencode(params, safe="().,:*$-", doseq=True)
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def sb_all(path, params, page_size=1000):
    """顺序翻页取全量(每页都带 order=)。"""
    rows, offset = [], 0
    if isinstance(params, dict):
        params = list(params.items())
    while True:
        p = list(params) + [("limit", page_size), ("offset", offset)]
        chunk = sb(path, p)
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return rows


# ── 数据装载 ────────────────────────────────────────────────────────────────

def load_universe():
    """cis_official_daily 最近一天的加密名(卡上的定义)。"""
    d0 = sb("cis_official_daily", {"select": "d", "order": "d.desc", "limit": 1})[0]["d"]
    rows = sb_all("cis_official_daily",
                  {"select": "symbol,asset_class,grade,signal", "d": "eq." + d0,
                   "order": "symbol.asc"})
    crypto = [r for r in rows if r["asset_class"] in CRYPTO_CLASSES]
    return d0, crypto


def load_funding(symbols, venue, start, end):
    """→ {symbol: [(date, n_rows, sum_rate), ...]}。rate 是小数(1e-4 = 1bp)。"""
    out = {}
    for s in symbols:
        rows = sb_all("funding_history",
                      [("select", "funding_time,funding_rate"), ("venue", "eq." + venue),
                       ("symbol", "eq." + s), ("funding_time", "gte." + start),
                       ("funding_time", "lte." + end + "T23:59:59Z"),
                       ("order", "funding_time.asc")])
        agg = defaultdict(lambda: [0, 0.0])
        for r in rows:
            d = str(r["funding_time"])[:10]
            agg[d][0] += 1
            agg[d][1] += float(r["funding_rate"])
        out[s] = sorted((d, v[0], v[1]) for d, v in agg.items())
    return out


def load_close(symbol, start=START, warmup_days=90):
    """→ {date: close}。同日多 source 时按 SRC_PRIORITY 取第一个存在的。

    下界是 start − warmup_days 而不是 start:§4 要算窗口头部(2023-01)的 **30 日滞后**回报,
    没有这段预热就没有头 30 天的 btc30。warmup 90 天留了 30 天以上的余量。
    两个 trade_date 边界在 PostgREST 里是 AND,所以必须用 list[tuple] 传 ——
    用 dict 传同名 key 会互相覆盖、静默丢掉下界(踩过:曾经把整张表拉下来才发现)。
    """
    w0 = (datetime.date.fromisoformat(start) - datetime.timedelta(days=warmup_days)).isoformat()
    rows = sb_all("ohlcv_daily",
                  [("select", "trade_date,close,source"), ("symbol", "eq." + symbol),
                   ("trade_date", "gte." + w0), ("trade_date", "lte." + END),
                   ("order", "trade_date.asc")])
    by = defaultdict(dict)
    for r in rows:
        by[str(r["trade_date"])[:10]][r["source"]] = float(r["close"])
    out = {}
    for d, m in by.items():
        for src in SRC_PRIORITY:
            if src in m:
                out[d] = m[src]
                break
        else:
            out[d] = list(m.values())[0]
    return out


def load_depth(venue):
    """venue_depth_snapshots 每个 symbol 最新一条的 ±2% 深度。"""
    rows = sb_all("venue_depth_snapshots",
                  {"select": "symbol,depth_2pct_bid_usd,depth_2pct_ask_usd,fetched_utc",
                   "venue": "eq." + venue, "order": "symbol.asc,fetched_utc.desc"})
    latest = {}
    for r in rows:
        latest.setdefault(r["symbol"], r)
    return latest


# ── ① 每日已实现 funding ───────────────────────────────────────────────────

def portfolio_daily(series_by_symbol, symbols, extrap_hours=None):
    """等权组合的日 funding。extrap_hours=None ⇒ 原样相加;否则按 24 小时外推(小时采样稀疏时用)。"""
    per_day = defaultdict(list)
    for s in symbols:
        for d, n, tot in series_by_symbol.get(s, []):
            v = tot
            if extrap_hours and n > 0 and n < extrap_hours:
                v = tot * (extrap_hours / n)
            per_day[d].append(v)
    return {d: (float(np.mean(v)), len(v)) for d, v in per_day.items()}


def monthly_map(daily):
    """→ {YYYY-MM: 月内累计 rate}。daily 必须是 {date: float}。"""
    mm = defaultdict(float)
    for d, v in daily.items():
        mm[d[:7]] += float(v)
    return dict(sorted(mm.items()))


def negative_segments(daily):
    """连续负费率段。→ [(start, end, days, cum_rate)]。"""
    dates = sorted(daily)
    segs, cur = [], []
    for d in dates:
        if daily[d][0] < 0:
            cur.append(d)
        else:
            if cur:
                segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return [(s[0], s[-1], len(s), float(sum(daily[d][0] for d in s))) for s in segs]


# ── 主流程 ─────────────────────────────────────────────────────────────────

def run():
    d0, crypto = load_universe()
    symbols = [r["symbol"] for r in crypto]
    print(f"[universe] cis_official_daily d={d0} 加密名 {len(symbols)}: {','.join(symbols)}")

    bin_f = load_funding(symbols, "binance_perp", START, END)
    hl_f = load_funding(symbols, "hyperliquid", HL_START, END)

    have_bin = [s for s in symbols if bin_f.get(s)]
    have_hl = [s for s in symbols if hl_f.get(s)]
    print(f"[coverage] binance_perp 有数据 {len(have_bin)}/{len(symbols)}; "
          f"hyperliquid {len(have_hl)}/{len(symbols)}")

    res = {"universe_date": d0, "universe": crypto,
           "window": [START, END], "hl_start": HL_START,
           "fees": {"spot_taker_bp": FEE_SPOT * 1e4, "perp_taker_bp": FEE_PERP * 1e4,
                    "switch_cost_bp": SWITCH_COST * 1e4}}

    # ── ① 面板:用有 binance_perp 全窗口数据的名字 ───────────────────────────
    coverage = {}
    for s in symbols:
        days = bin_f.get(s, [])
        if not days:
            coverage[s] = {"n_days": 0}
            continue
        cov = {}
        for d, n, t in days:
            cov[d] = cov.get(d, 0) + n
        ds = sorted(cov)
        span = (datetime.date.fromisoformat(ds[-1]) -
                datetime.date.fromisoformat(ds[0])).days + 1
        coverage[s] = {"n_days": len(ds), "first": ds[0], "last": ds[-1], "span_days": span,
                       "coverage_pct": round(100.0 * len(ds) / span, 1),
                       "rows_per_day": round(sum(cov.values()) / len(ds), 2)}
    res["coverage_binance"] = coverage
    missing = [s for s in symbols if not bin_f.get(s)]
    res["no_binance_funding"] = missing
    print(f"[coverage] binance_perp 无数据: {missing or '无'}")

    panel = []
    for s in symbols:
        days = bin_f.get(s, [])
        if days and days[0][0] <= "2023-02-01" and days[-1][0] >= "2026-09-01":
            panel.append(s)
    res["panel"] = panel
    res["panel_n"] = len(panel)
    print(f"[panel] 全窗口连续覆盖 {len(panel)}: {','.join(panel)}")
    print("  未入连续面板的: " + ", ".join(
        f"{s}({coverage[s].get('first','-')}→{coverage[s].get('last','-')})"
        for s in symbols if s not in panel))

    p_daily = portfolio_daily(bin_f, panel)
    p_month = monthly_map({d: v[0] for d, v in p_daily.items()})
    res["n_days"] = len(p_daily)
    res["first_day"] = min(p_daily) if p_daily else None
    res["last_day"] = max(p_daily) if p_daily else None

    # 等权(每名按自身有数据的窗口)年化 —— 卡的「等权 24 名」口径
    per_name_ann = {}
    for s in symbols:
        c = coverage.get(s) or {}
        if not c.get("n_days") or c["n_days"] < 180:
            per_name_ann[s] = None
            continue
        tot = sum(t for d, n, t in bin_f[s])
        per_name_ann[s] = tot / (c["span_days"] / 365.0) * 100
    res["per_name_ann_pct"] = per_name_ann
    ok = [v for v in per_name_ann.values() if v is not None]
    res["equal_weight_ann_pct"] = float(np.mean(ok)) if ok else None
    res["equal_weight_n_names"] = len(ok)

    # 连续面板的年化
    years = ((datetime.date.fromisoformat(res["last_day"]) -
              datetime.date.fromisoformat(res["first_day"])).days / 365.0) if res["last_day"] else 0
    tot_rate = float(sum(v[0] for v in p_daily.values()))
    res["panel_ann_gross_pct"] = tot_rate / years * 100 if years else None
    res["panel_total_rate_pct"] = tot_rate * 100
    res["panel_years"] = years

    # 逐年年化(看资金费率的制度变化)
    by_year = defaultdict(float)
    yr_days = defaultdict(int)
    for d, v in p_daily.items():
        by_year[d[:4]] += v[0]
        yr_days[d[:4]] += 1
    res["panel_by_year"] = {y: {"ann_pct": by_year[y] / (yr_days[y] / 365.0) * 100,
                                 "days": yr_days[y], "total_pct": by_year[y] * 100}
                            for y in sorted(by_year)}
    print("[①] 逐年年化: " + " | ".join(
        f"{y}={res['panel_by_year'][y]['ann_pct']:.2f}%" for y in res["panel_by_year"]))
    print(f"[①] 等权年化(每名自身窗口, {len(ok)} 名)= {res['equal_weight_ann_pct']:.3f}%/yr  "
          f"连续 {len(panel)} 名面板= {res['panel_ann_gross_pct']:.3f}%/yr")
    # 尾部 run-rate(与 CLAUDE.md 里「等权 funding +23.07% 年化」的口径对照)
    ds_sorted = sorted(p_daily)
    for win in (30, 90):
        tail = ds_sorted[-win:]
        if len(tail) == win:
            tot = sum(p_daily[d][0] for d in tail)
            res[f"panel_runrate_ann_pct_{win}d"] = tot / (win / 365.0) * 100
            print(f"[①] 尾部 {win} 日 run-rate 年化 = {res[f'panel_runrate_ann_pct_{win}d']:.3f}%/yr")

    # 正 / 负费率月
    pos_m = [m for m, v in p_month.items() if v > 0]
    neg_m = [m for m, v in p_month.items() if v < 0]
    res["months_total"] = len(p_month)
    res["months_pos"] = len(pos_m)
    res["months_neg"] = len(neg_m)
    res["months_flat"] = len(p_month) - len(pos_m) - len(neg_m)
    res["monthly_min_pct"] = min(p_month.values()) * 100 if p_month else None
    res["monthly_max_pct"] = max(p_month.values()) * 100 if p_month else None
    print(f"[①] 月数 {len(p_month)} 正 {len(pos_m)} 负 {len(neg_m)}")

    # 最长连续负费率段
    segs = negative_segments(p_daily)
    res["n_neg_segments"] = len(segs)
    res["neg_segments"] = [{"start": s, "end": e, "days": n, "cum_pct": c * 100}
                           for s, e, n, c in sorted(segs, key=lambda x: -x[2])[:12]]
    if segs:
        best = max(segs, key=lambda x: x[2])
        res["longest_neg_segment"] = {"start": best[0], "end": best[1], "days": best[2],
                                      "cum_pct": best[3] * 100}
        print(f"[①] 负费率段 {len(segs)} 段,最长 {best[2]} 天 "
              f"({best[0]}→{best[1]}) 累计 {best[3]*100:.4f}%")
    else:
        res["longest_neg_segment"] = None

    # ── ①b HL venue 面板(2026-09-05 起;表里的 HL 行是稀疏的小时费率采样)────
    # 每名每天的行数与费率和:HL 行是「那一小时」的小时费率(稀疏采样);
    # Binance 是每 8 小时一行、3 行/天(完整)。
    hl_nd, bn_nd = {}, {}          # {symbol: {date: (n_rows, sum_rate)}}
    for s in have_hl:
        agg = defaultdict(lambda: [0, 0.0])
        for d, n, t in hl_f[s]:
            agg[d][0] += n
            agg[d][1] += t
        hl_nd[s] = dict(agg)
    for s in have_bin:
        agg = defaultdict(lambda: [0, 0.0])
        for d, n, t in bin_f[s]:
            agg[d][0] += n
            agg[d][1] += t
        bn_nd[s] = dict(agg)
    common_days = sorted(set().union(*[set(hl_nd[s]) for s in have_hl])) if have_hl else []

    hl_panel_raw = portfolio_daily(hl_f, have_hl)
    hl_panel_ext = portfolio_daily(hl_f, have_hl, extrap_hours=24)
    hl_days_all = sorted(hl_panel_ext)
    hl_years = ((datetime.date.fromisoformat(hl_days_all[-1]) -
                 datetime.date.fromisoformat(hl_days_all[0])).days / 365.0) if hl_days_all else 0
    for tag, dd in (("raw", hl_panel_raw), ("ext24", hl_panel_ext)):
        tot = sum(v[0] for v in dd.values())
        res[f"hl_panel_ann_pct_{tag}"] = tot / hl_years * 100 if hl_years else None
        res[f"hl_panel_days_{tag}"] = len(dd)
        res[f"hl_panel_total_pct_{tag}"] = tot * 100
    res["hl_panel_first"] = hl_days_all[0] if hl_days_all else None
    res["hl_panel_last"] = hl_days_all[-1] if hl_days_all else None
    res["hl_panel_n_names"] = len(have_hl)
    hl_row_counts = [n for s in have_hl for d, n, t in hl_f[s]]
    res["hl_rows_per_day_mean"] = float(np.mean(hl_row_counts)) if hl_row_counts else None
    res["hl_rows_per_day_hist"] = sorted(Counter(hl_row_counts).items())
    # 基线核对:HL 基线费率 1.25e-05/小时 ⇒ 全日 3e-4 = 0.03%/日 = 10.95%/年
    res["hl_baseline_ann_pct"] = 1.25e-05 * 24 * 365 * 100
    # 同窗口同名字的 Binance 面板(用于口径对齐)
    both = [s for s in have_hl if s in have_bin]
    bn_recent = {d: v for d, v in portfolio_daily(bin_f, both).items() if d in set(common_days)} \
        if common_days else {}
    if bn_recent:
        bn_years = ((datetime.date.fromisoformat(max(bn_recent)) -
                     datetime.date.fromisoformat(min(bn_recent))).days / 365.0)
        res["bin_same_window_ann_pct"] = sum(v[0] for v in bn_recent.values()) / bn_years * 100
        res["bin_same_window_days"] = len(bn_recent)
    print(f"[①b] HL 面板({len(have_hl)} 名,{res['hl_panel_first']}→{res['hl_panel_last']},"
          f"{res['hl_panel_days_ext24']} 天): 原样年化 {res['hl_panel_ann_pct_raw']:.3f}%/yr | "
          f"24h 外推年化 {res['hl_panel_ann_pct_ext24']:.3f}%/yr "
          f"(平均 {res['hl_rows_per_day_mean']:.2f} 行/天)")
    hl_ds = sorted(hl_panel_ext)
    for win in (30,):
        tail = hl_ds[-win:]
        if len(tail) == win:
            res[f"hl_panel_runrate_ann_pct_{win}d"] = (
                sum(hl_panel_ext[d][0] for d in tail) / (win / 365.0) * 100)
            res[f"hl_panel_runrate_ann_pct_{win}d_raw"] = (
                sum(hl_panel_raw[d][0] for d in tail) / (win / 365.0) * 100)

    # ── ② 规则 A / B ───────────────────────────────────────────────────────
    dates = sorted(p_daily)
    vals = [p_daily[d][0] for d in dates]

    def rule_stats(on_flags):
        gross = sum(v for v, on in zip(vals, on_flags) if on)
        sw = 0
        prev = False
        for on in on_flags:
            if on != prev:
                sw += 1
            prev = on
        # 末尾持仓平仓也算一次开平
        if on_flags and on_flags[-1]:
            sw += 1
        net = gross - sw * SWITCH_COST
        n_on = sum(1 for f in on_flags if f)
        return {"gross_pct": gross * 100, "net_pct": net * 100, "switches": sw,
                "days_on": n_on, "days_off": len(on_flags) - n_on,
                "ann_gross_pct": gross / years * 100, "ann_net_pct": net / years * 100}

    # 规则 A:常开
    res["rule_A"] = rule_stats([True] * len(dates))

    # 规则 B:7 天均 funding > 0 才开。同日版(S-665 当天版)与滞后 1 天版(主口径)
    trail7 = []
    for i in range(len(vals)):
        lo = max(0, i - 6)
        trail7.append(float(np.mean(vals[lo:i + 1])))
    same_day = [t > 0 for t in trail7]
    lag1 = [False] + [trail7[i - 1] > 0 for i in range(1, len(vals))]
    res["rule_B_lag1"] = rule_stats(lag1)
    res["rule_B_sameday"] = rule_stats(same_day)
    print(f"[②] A: gross {res['rule_A']['gross_pct']:.3f}% net {res['rule_A']['net_pct']:.3f}% "
          f"switches {res['rule_A']['switches']}")
    print(f"[②] B(lag1): gross {res['rule_B_lag1']['gross_pct']:.3f}% "
          f"net {res['rule_B_lag1']['net_pct']:.3f}% switches {res['rule_B_lag1']['switches']} "
          f"on {res['rule_B_lag1']['days_on']}/{len(dates)}")
    print(f"[②] B(sameday): gross {res['rule_B_sameday']['gross_pct']:.3f}% "
          f"net {res['rule_B_sameday']['net_pct']:.3f}% switches {res['rule_B_sameday']['switches']}")

    # A/B(B 相对 A),用 apparatus.ab_test
    ret_A = [v for v in vals]
    ret_B = [v if on else 0.0 for v, on in zip(vals, lag1)]
    ab = ab_test(ret_A, ret_B, mean_block=20.0, n_boot=2000, seed=222)
    res["ab_B_lag1_vs_A"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in ab.items()}
    print(f"[②] A/B: verdict={ab['verdict']} p_b_le_a={ab['p_b_le_a']:.4f} "
          f"cum_a={ab['cum_a']*100:.3f}% cum_b={ab['cum_b']*100:.3f}%")
    ab2 = ab_test(ret_A, [v if on else 0.0 for v, on in zip(vals, same_day)],
                  mean_block=20.0, n_boot=2000, seed=223)
    res["ab_B_sameday_vs_A"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in ab2.items()}

    # 净值口径的 A/B(决策相关:开关仓的费用必须扣进去才可比)
    def net_series(on_flags):
        out, prev = [], False
        for i, on in enumerate(on_flags):
            v = vals[i] if on else 0.0
            if on != prev:          # 开仓
                v -= SWITCH_COST
            out.append(v)
            prev = on
        if on_flags and on_flags[-1]:   # 末尾平仓
            out[-1] -= SWITCH_COST
        return out

    net_A = net_series([True] * len(vals))
    net_B = net_series(lag1)
    ab_net = ab_test(net_A, net_B, mean_block=20.0, n_boot=2000, seed=225)
    res["ab_net_B_lag1_vs_A"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in ab_net.items()}
    print(f"[②] A/B(净值口径): verdict={ab_net['verdict']} "
          f"cum_A_net={ab_net['cum_a']*100:.3f}% cum_B_net={ab_net['cum_b']*100:.3f}% "
          f"p_b_ge_a={ab_net['p_b_ge_a']:.4f}")

    # ── ③ HL vs Binance ───────────────────────────────────────────────────
    # 两个口径:原样求和,以及按 24 小时外推(每小时费率的样本均值 × 24 = 全日费率)。
    hl_raw, hl_ext, bn_same = {}, {}, {}
    for d in common_days:
        hsum = [v[1] for s in have_hl for v in [hl_nd[s].get(d)] if v]
        hn = [v[0] for s in have_hl for v in [hl_nd[s].get(d)] if v]
        hl_raw[d] = float(np.mean(hsum)) if hsum else None
        hl_ext[d] = float(np.mean([t * (24.0 / n) for t, n in zip(hsum, hn)])) if hsum else None
        bsum = [bn_nd[s][d][1] for s in have_bin if d in bn_nd[s]]
        bn_same[d] = float(np.mean(bsum)) if bsum else None
    for key, src in (("hl_vs_bin_raw", hl_raw), ("hl_vs_bin_ext", hl_ext)):
        days = [d for d in common_days if src.get(d) is not None and bn_same.get(d) is not None]
        if len(days) < 5:
            res[key] = {"n_days": len(days)}
            continue
        a = np.array([src[d] for d in days])
        b = np.array([bn_same[d] for d in days])
        diff = a - b
        corr = float(np.corrcoef(a, b)[0, 1]) if len(days) > 2 and a.std() > 0 and b.std() > 0 else None
        res[key] = {
            "n_days": len(days),
            "hl_mean_pct": float(a.mean()) * 100,
            "bin_mean_pct": float(b.mean()) * 100,
            "diff_mean_pct": float(diff.mean()) * 100,
            "diff_median_pct": float(np.median(diff)) * 100,
            "corr": corr,
            "hl_higher_days": int((diff > 0).sum()),
            "hl_higher_pct": float((diff > 0).mean()) * 100,
        }
        print(f"[③] {key}: n={len(days)} HL均值 {res[key]['hl_mean_pct']:.5f}%/d "
              f"Binance {res[key]['bin_mean_pct']:.5f}%/d 差 {res[key]['diff_mean_pct']:.5f}pp "
              f"corr {corr if corr is None else round(corr,4)} HL更高 {res[key]['hl_higher_pct']:.1f}%")

    # HL 每名:Binance 均价 vs HL 外推价,年化差
    hl_vs_bin_by_name = {}
    for s in have_hl:
        d_hl = {d: t for d, n, t in hl_f[s]}
        n_hl = {d: n for d, n, t in hl_f[s]}
        d_bn = {d: t for d, n, t in bin_f.get(s, [])}
        ds = sorted(set(d_hl) & set(d_bn))
        if len(ds) < 5:
            continue
        hl_e = float(np.mean([d_hl[d] * (24.0 / n_hl[d]) for d in ds])) * 365 * 100
        bn_e = float(np.mean([d_bn[d] for d in ds])) * 365 * 100
        hl_vs_bin_by_name[s] = {"hl_ann_pct": hl_e, "bin_ann_pct": bn_e, "diff_ann_pct": hl_e - bn_e}
    res["hl_vs_bin_by_name"] = hl_vs_bin_by_name

    # ── ④ 负费率段 vs BTC 30 日回报 ────────────────────────────────────────
    btc = load_close("BTC")
    bdates = sorted(btc)
    btc30 = {}
    for i, d in enumerate(bdates):
        if i >= 30:
            btc30[d] = btc[bdates[i]] / btc[bdates[i - 30]] - 1.0
    btc_cum = {}
    for i, d in enumerate(bdates):
        btc_cum[d] = btc[d] / btc[bdates[0]] - 1.0

    seg_detail = []
    for s0, s1, n, cum in sorted(segs, key=lambda x: -x[2])[:10]:
        ds = [d for d in bdates if s0 <= d <= s1 and d in btc30]
        if not ds:
            continue
        seg_detail.append({
            "start": s0, "end": s1, "days": n, "cum_funding_pct": cum * 100,
            "btc30_mean_pct": float(np.mean([btc30[d] for d in ds])) * 100,
            "btc_seg_return_pct": (btc[s1] / btc[s0] - 1.0) * 100 if s0 in btc and s1 in btc else None,
            "btc30_neg_days": int(sum(1 for d in ds if btc30[d] < 0)),
            "n_btc_days": len(ds),
        })
    res["neg_segments_vs_btc"] = seg_detail
    # 最贵的负费率段(对常开 sleeve 的拖累)
    worst = min(seg_detail, key=lambda x: x["cum_funding_pct"]) if seg_detail else None
    res["worst_neg_segment"] = worst
    if worst:
        print(f"[④] 最贵负段 {worst['start']}→{worst['end']} ({worst['days']}d) "
              f"资金费 {worst['cum_funding_pct']:.4f}% / BTC 该段 {worst['btc_seg_return_pct']:.1f}% "
              f"/ BTC 30 日均值 {worst['btc30_mean_pct']:.1f}%")

    # 全样本:负费率日 vs 正费率日的 BTC 30 日回报
    common = [d for d in sorted(p_daily) if d in btc30]
    neg_days = [d for d in common if p_daily[d][0] < 0]
    pos_days = [d for d in common if p_daily[d][0] >= 0]
    res["btc30_on_neg_days_pct"] = float(np.mean([btc30[d] for d in neg_days])) * 100 if neg_days else None
    res["btc30_on_pos_days_pct"] = float(np.mean([btc30[d] for d in pos_days])) * 100 if pos_days else None
    res["btc30_all_days_pct"] = float(np.mean([btc30[d] for d in common])) * 100 if common else None
    res["n_neg_days"] = len(neg_days)
    res["n_pos_days"] = len(pos_days)
    # 2x2:负费率日 × BTC30 为负
    if neg_days and pos_days:
        tn = sum(1 for d in neg_days if btc30[d] < 0)
        fp = sum(1 for d in neg_days if btc30[d] >= 0)
        fn = sum(1 for d in pos_days if btc30[d] < 0)
        tp = sum(1 for d in pos_days if btc30[d] >= 0)
        res["contingency"] = {"neg_funding_btc_down": tn, "neg_funding_btc_up": fp,
                              "pos_funding_btc_down": fn, "pos_funding_btc_up": tp}
        res["p_down_given_neg_funding"] = tn / len(neg_days)
        res["p_down_given_pos_funding"] = fn / len(pos_days)

    # 零分布:负费率日 BTC30 均值 —— 打乱 funding 序列(块置换)后重算
    if len(neg_days) >= 20:
        btc_vec = np.array([btc30[d] for d in common])
        fund_vec = np.array([p_daily[d][0] for d in common])
        actual = float(np.mean(btc_vec[fund_vec < 0])) * 100

        def _null(rng):
            perm = block_permute(fund_vec, block=7, rng=rng)
            sel = perm < 0
            if sel.sum() < 5:
                return np.nan
            return float(np.mean(btc_vec[sel])) * 100

        try:
            null = null_distribution(_null, n=2000, seed=222, actual=actual)
            res["btc30_neg_funding_null_pct"] = percentile_of(actual, null)
            res["btc30_neg_funding_actual_pct"] = actual
            print(f"[④] 负费率日 BTC30 均值 {actual:.3f}% "
                  f"零分布分位 p={res['btc30_neg_funding_null_pct']:.4f}")
        except Exception as e:  # noqa: BLE001
            res["btc30_neg_funding_null_error"] = str(e)

    # apparatus.ab_test:B = 只在负费率日,A = 全样本。用 BTC **日**收益(可加)——
    # 30 日收益是重叠窗口,叠进 ab_test 的复利口径会退化(cum 恒为 -100%),不作数。
    btc_daily = {}
    for i in range(1, len(bdates)):
        if bdates[i - 1] in btc:
            btc_daily[bdates[i]] = btc[bdates[i]] / btc[bdates[i - 1]] - 1.0
    if neg_days:
        rA = [btc_daily.get(d, np.nan) for d in sorted(p_daily)]
        rB = [btc_daily[d] if (d in btc_daily and p_daily[d][0] < 0) else np.nan
              for d in sorted(p_daily)]
        ab_btc = ab_test(rA, rB, mean_block=20.0, n_boot=2000, seed=224)
        res["ab_btc_daily_negfund_vs_all"] = {k: (list(v) if isinstance(v, tuple) else v)
                                              for k, v in ab_btc.items()}
        print(f"[④] A/B(BTC 日收益,负费率日 vs 全样本): verdict={ab_btc['verdict']} "
              f"n={ab_btc['n_days']} cum_a={ab_btc['cum_a']*100:.2f}% "
              f"cum_b={ab_btc['cum_b']*100:.2f}% p_b_ge_a={ab_btc['p_b_ge_a']:.4f}")

    # ① 的月度时间线(报告用):资金费率 × BTC 月末 30 日回报 × BTC 当月回报
    timeline = []
    for m, v in p_month.items():
        md = [d for d in sorted(btc) if d[:7] == m]
        if not md:
            continue
        last = md[-1]
        prev_m = [d for d in sorted(btc) if d[:7] < m]
        timeline.append({
            "month": m, "funding_pct": v * 100,
            "btc30_pct": (btc30.get(last) or 0) * 100,
            "btc_month_pct": ((btc[last] / btc[prev_m[-1]] - 1.0) * 100) if prev_m else None,
        })
    res["timeline"] = timeline

    # ④ 的正面回答:资金费率与 BTC 的相关性 —— 这是不是伪装的 β
    tl = [t for t in timeline if t.get("btc_month_pct") is not None]
    if len(tl) >= 12:
        f = np.array([t["funding_pct"] for t in tl])
        m = np.array([t["btc_month_pct"] for t in tl])
        b30 = np.array([t["btc30_pct"] for t in tl])
        corr = float(np.corrcoef(f, m)[0, 1])
        res["monthly_corr_funding_vs_btc_month"] = corr
        res["monthly_corr_funding_vs_btc30"] = float(np.corrcoef(f, b30)[0, 1])
        res["monthly_corr_n"] = len(tl)

        def _null_corr(rng):
            p = block_permute(f, block=3, rng=rng)
            if np.std(p) < 1e-12:
                return np.nan
            return float(np.corrcoef(p, m)[0, 1])

        try:
            null = null_distribution(_null_corr, n=2000, seed=226, actual=corr)
            res["monthly_corr_p"] = percentile_of(corr, null)
            res["monthly_corr_null_q025"] = float(np.quantile(null, 0.025))
            res["monthly_corr_null_q975"] = float(np.quantile(null, 0.975))
            print(f"[④] 月度 funding vs BTC 月回报 corr={corr:.4f} "
                  f"(p={res['monthly_corr_p']:.4f}, null 95% "
                  f"[{res['monthly_corr_null_q025']:.3f},{res['monthly_corr_null_q975']:.3f}]) | "
                  f"vs BTC30 corr={res['monthly_corr_funding_vs_btc30']:.4f}")
        except Exception as e:  # noqa: BLE001
            res["monthly_corr_p_error"] = str(e)

    # ── ⑤ 容量(HL 现货 ±2% 深度) ──────────────────────────────────────────
    spot = load_depth("hyperliquid_spot")
    perp = load_depth("hyperliquid_perp")
    cap = []
    for s in panel:
        sp, pp = spot.get(s), perp.get(s)
        if not sp:
            continue
        cap.append({"symbol": s,
                    "spot_bid2": sp["depth_2pct_bid_usd"], "spot_ask2": sp["depth_2pct_ask_usd"],
                    "perp_bid2": pp["depth_2pct_bid_usd"] if pp else None,
                    "perp_ask2": pp["depth_2pct_ask_usd"] if pp else None,
                    "fetched_utc": sp["fetched_utc"]})
    res["hl_spot_depth"] = cap
    res["hl_spot_depth_n"] = len(cap)
    if cap:
        tot_ask = sum(c["spot_ask2"] for c in cap)
        tot_bid = sum(c["spot_bid2"] for c in cap)
        res["hl_spot_total_bid2_usd"] = tot_bid
        res["hl_spot_total_ask2_usd"] = tot_ask
        res["hl_spot_total_min_usd"] = float(np.mean([min(c["spot_bid2"], c["spot_ask2"]) for c in cap]))
        print(f"[⑤] HL 现货 ±2% 深度覆盖 {len(cap)} 名,总 bid {tot_bid/1e6:.1f}M / ask {tot_ask/1e6:.1f}M")

    # asset_mcap_daily 覆盖(卡上列的数据源)。资金费是费率不是收益,市值不进入算式;
    # 这里用它核对「名字集合在三个源上是否一致」(面板 = 加密名,不是市值筛选出来的)。
    mc = {}
    for s in panel:
        rows = sb_all("asset_mcap_daily", {"select": "d,mcap,price,source", "symbol": "eq." + s,
                                           "order": "d.asc"})
        mc[s] = {"n": len(rows), "first": rows[0]["d"] if rows else None,
                 "last": rows[-1]["d"] if rows else None}
    res["asset_mcap_daily_probe"] = mc

    out = os.path.join(HERE, "t222_results.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\n[out] {out}")
    return res


def probe():
    d0, crypto = load_universe()
    print(f"[universe] d={d0} crypto={len(crypto)}")
    print("  " + ", ".join(f"{r['symbol']}({r['asset_class']},{r['grade']})" for r in crypto))

    s = "BTC"
    for venue, start in (("binance_perp", START), ("hyperliquid", HL_START)):
        rows = sb_all("funding_history",
                      {"select": "funding_time,funding_rate", "venue": "eq." + venue,
                       "symbol": "eq." + s, "funding_time": "gte." + start,
                       "order": "funding_time.asc"})
        if not rows:
            print(f"[{venue}] {s}: 0 rows")
            continue
        per_day = Counter(str(r["funding_time"])[:10] for r in rows)
        print(f"[{venue}] {s}: n={len(rows)} {rows[0]['funding_time'][:10]}→{rows[-1]['funding_time'][:10]} "
              f"rows/day hist={sorted(Counter(per_day.values()).items())[:8]}")
        d0s = sorted(per_day)[len(per_day) // 2]
        day = [(str(r["funding_time"])[11:16], r["funding_rate"]) for r in rows
               if str(r["funding_time"])[:10] == d0s]
        print(f"   sample day {d0s}: n={len(day)} {day[:14]}")

    spot = load_depth("hyperliquid_spot")
    print(f"[depth] HL spot symbols={len(spot)} sample="
          f"{[(k, round(v['depth_2pct_ask_usd'])) for k, v in list(spot.items())[:6]]}")

    for s in ("BTC", "ETH", "SOL"):
        rows = sb_all("asset_mcap_daily", {"select": "d,mcap,price,source", "symbol": "eq." + s,
                                           "order": "d.asc"})
        print(f"[mcap] {s}: n={len(rows)} {rows[0]['d'] if rows else ''}→{rows[-1]['d'] if rows else ''}")


def schema():
    """情景文件要用的变量类型:state_daily / macro_daily 有什么列、有什么 feature/series。"""
    rows = sb_all("state_daily", {"select": "feature,entity,d,value", "d": "gte.2026-10-25",
                                  "order": "feature.asc,d.desc"})
    feats = {}
    for r in rows:
        feats.setdefault(r["feature"], []).append(r)
    print(f"[state_daily] rows={len(rows)} features={len(feats)}")
    for f, rs in sorted(feats.items()):
        ents = sorted({r["entity"] for r in rs})
        print(f"   {f:<28} entities={ents} latest={rs[0]['d']} value={rs[0]['value']}")

    mrows = sb_all("macro_daily", {"select": "series,d,value", "d": "gte.2026-10-25",
                                   "order": "series.asc,d.desc"})
    ser = {}
    for r in mrows:
        ser.setdefault(r["series"], []).append(r)
    print(f"[macro_daily] rows={len(mrows)} series={len(ser)}")
    for s, rs in sorted(ser.items()):
        print(f"   {s:<28} latest={rs[0]['d']} value={rs[0]['value']}")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "probe"
    {"probe": probe, "run": run, "schema": schema}[stage]()
