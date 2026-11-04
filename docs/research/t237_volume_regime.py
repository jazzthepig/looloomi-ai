#!/usr/bin/env python3
"""T-237 成交量口径核对 —— DB(`ohlcv_daily` source=binance_hist)vs 本地缓存(t156/t159)。

问题(S-698 之后):DB 里 `binance_hist` 的 volume 现在是**现货量**,而 10-21 建的本地缓存
(t156/t159)是**永续量**。R-v2 的进场门(成交额 ≥ 2× 20 日均量)和宇宙门槛(30 日均成交额 ≥
500 万美元)都吃这一列。S-610 / S-638 / S-677 的 770 张票站在**哪条**序列上,今天之前没人核过。

纪律:只读。不改代码、不做 DDL、不入库。零分布/多空盈亏/A-B 一律走 `src/data/evaluation/apparatus.py`;
本卡是口径核对,不需要零分布(不判),钱曲线用台账自己的 `t159.nav` / `t159.stats`(与 S-677 / T-236 同一条路)。

阶段:
  fetch   从 DB 重拉 bar → `/Volumes/CometCloudAI/cometcloud-local/research/t237/_bars_db.jsonl`
  compare 序列对比 + 票重生成(固定 (2.5, 20, 2))+ 宇宙按月 + 闸门核 → `docs/research/t237_results.json`

用法: python3 docs/research/t237_volume_regime.py [--stage fetch|compare|all] [--out PATH]
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("COMETCLOUD_LOCAL", "/Volumes/CometCloudAI/cometcloud-local")
MAC_DIR = os.path.join(ROOT, "research", "t237")
DB_JSONL = os.path.join(MAC_DIR, "_bars_db.jsonl")

_spec = importlib.util.spec_from_file_location("t159", os.path.join(HERE, "t159_bear_short.py"))
t159 = importlib.util.module_from_spec(_spec)
sys.modules["t159"] = t159
_spec.loader.exec_module(t159)

# ── 预注册常量(先写后算) ─────────────────────────────────────────────────────
SIG_FROM, SIG_TO = "2020-03-01", "2026-10-19"   # 票生成窗(与 t159 / S-677 台账一致)
CURVE_TO = "2026-10-19"                          # 钱曲线终点
FETCH_FROM = "2019-10-01"                        # 卡写 2019-10
FETCH_TO = "2026-11-05"                         # 卡写 2026-10-19;⑤ 的闸门核要到 11-03,故多拉几天
COST = 0.004                                    # 来回成本(与 t159 逐字)
UNIV_ADV = 5e6                                  # 宇宙门槛:30 日均成交额 ≥ 500 万美元
F_RISK = 0.01                                   # 钱曲线每笔 1%
CAP = 10                                        # 同时最多 10 张
RATIO_LO, RATIO_HI = 0.5, 2.0                    # 受影响符号判定(成交量比值中位)
GATE_CHECK = ("2026-10-29", "2026-11-03")        # ⑤ 要核的几天


# ── DB 拉取 ──────────────────────────────────────────────────────────────────
def _rest(q: str, lo: int, hi: int, count: bool = False):
    k = os.environ["SUPABASE_KEY"]
    h = {"apikey": k, "Authorization": "Bearer " + k, "Range": f"{lo}-{hi}"}
    if count:
        h["Prefer"] = "count=exact"
    r = urllib.request.Request(os.environ["SUPABASE_URL"] + "/rest/v1/" + q, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read()), resp.headers.get("Content-Range", "")
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return [], ""
        raise


def fetch_db() -> dict:
    """重拉 `ohlcv_daily` source=binance_hist。翻页带 order=symbol.asc,trade_date.asc(边界不漂)。"""
    os.makedirs(MAC_DIR, exist_ok=True)
    q = ("ohlcv_daily?select=symbol,trade_date,open,high,low,close,volume"
         f"&source=eq.binance_hist&trade_date=gte.{FETCH_FROM}&trade_date=lte.{FETCH_TO}"
         "&order=symbol.asc,trade_date.asc")
    first, cr = _rest(q, 0, 0, count=True)
    total = int(cr.split("/")[-1]) if "/" in cr else -1
    if total < 0:
        raise SystemExit("no Content-Range total; cannot page deterministically")
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    step = 10000
    n = 0
    with open(DB_JSONL, "w") as f:
        f.write(json.dumps({"_meta": {"fetched_at_utc": fetched_at, "query": q,
                                      "expected_rows": total, "page_step": step,
                                      "note": "one JSON object per line: symbol,trade_date,o,h,l,c,v"}}) + "\n")
        if first:
            f.write(json.dumps(first) + "\n")
            n += len(first)
        lo = len(first)
        while lo < total:
            rows, _ = _rest(q, lo, min(lo + step - 1, total - 1))
            if not rows:
                break
            f.write(json.dumps(rows) + "\n")
            lo += len(rows)
            n += len(rows)
            print(f"  ... {lo}/{total}", file=sys.stderr)
    meta = {"fetched_at_utc": fetched_at, "rows_written": n, "expected_rows": total,
            "file": DB_JSONL, "query": q}
    print(json.dumps(meta), file=sys.stderr)
    return meta


# ── 两条序列 ────────────────────────────────────────────────────────────────
def load_db_raw() -> dict[str, list]:
    """DB jsonl → {sym: [(d,o,h,l,c,v)]}(按 d 排序)。"""
    by = defaultdict(list)
    with open(DB_JSONL) as f:
        for line in f:
            x = json.loads(line)
            if isinstance(x, dict) and "_meta" in x:
                continue
            for r in (x if isinstance(x, list) else [x]):
                by[r["symbol"]].append((r["trade_date"], float(r["open"]), float(r["high"]),
                                        float(r["low"]), float(r["close"]), float(r["volume"])))
    return {s: sorted(set(v)) for s, v in by.items() if v}


def load_cache_raw() -> dict[str, list]:
    """本地缓存(t156/_bars{,_early}.jsonl + t159/_bars.jsonl)→ {sym: [(d,o,h,l,c,v)]}。"""
    by = defaultdict(list)
    for d in (t159.T156, t159.ENV):
        for fn in (f"{d}_bars_early.jsonl", f"{d}_bars.jsonl"):
            if not os.path.exists(fn):
                continue
            for line in open(fn):
                for x in json.loads(line):
                    by[x["symbol"]].append((x["trade_date"], float(x["open"]), float(x["high"]),
                                            float(x["low"]), float(x["close"]), float(x["volume"])))
    return {s: sorted(set(v)) for s, v in by.items() if v}


def load_cache_files() -> dict[str, dict[str, list]]:
    """逐个缓存文件分开读(带出处):哪一份抓的是哪个口径。"""
    out = {}
    for d in (t159.T156, t159.ENV):
        for fn in (f"{d}_bars_early.jsonl", f"{d}_bars.jsonl"):
            if not os.path.exists(fn):
                continue
            by = defaultdict(list)
            for line in open(fn):
                for x in json.loads(line):
                    by[x["symbol"]].append((x["trade_date"], float(x["open"]), float(x["high"]),
                                            float(x["low"]), float(x["close"]), float(x["volume"])))
            out[os.path.basename(os.path.dirname(fn)) + "/" + os.path.basename(fn)] = {
                s: sorted(set(v)) for s, v in by.items() if v}
    return out


def to_bars(raw: dict[str, list]) -> dict[str, list]:
    """t159 的行结构:(trade_date, o, h, l, c, 成交额=close×volume);去重 + EXCL 过滤。"""
    out = {}
    for s, v in raw.items():
        if s in t159.EXCL:
            continue
        rows = sorted({(d, o, h, l, c, c * vol) for d, o, h, l, c, vol in v})
        if rows:
            out[s] = rows
    return out


def last_close_at(bars: dict, sym: str, d_to: str):
    rows = bars.get(sym) or []
    c = [r[4] for r in rows if r[0] <= d_to]
    return c[-1] if c else None


# ── ① 序列对比 ──────────────────────────────────────────────────────────────
def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _quant(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def changepoint(dates, ratios):
    """成交量比值(缓存/DB)的水平切换点:切分点前后均值差最大者(O(n) 前缀和)。"""
    n = len(ratios)
    if n < 60:
        return None
    s = [0.0]
    for r in ratios:
        s.append(s[-1] + r)
    best, best_i = 0.0, None
    for i in range(30, n - 30):
        ml = s[i] / i
        mr = (s[n] - s[i]) / (n - i)
        d = abs(mr - ml)
        if d > best:
            best, best_i = d, i
    if best_i is None or best <= 0:
        return None
    ml, mr = s[best_i] / best_i, (s[n] - s[best_i]) / (n - best_i)
    lo, hi = min(ml, mr), max(ml, mr)
    if lo <= 0 or hi / lo < 1.5:      # 噪声不算切换点
        return None
    return {"date": dates[best_i], "mean_left": round(ml, 4), "mean_right": round(mr, 4),
            "level_ratio": round(hi / lo, 3), "left_n": best_i, "right_n": n - best_i}


def compare_series(cache_raw, db_raw):
    out = {"symbols": {"cache": len(cache_raw), "db": len(db_raw),
                       "common": len(set(cache_raw) & set(db_raw)),
                       "only_cache": sorted(set(cache_raw) - set(db_raw)),
                       "only_db": sorted(set(db_raw) - set(cache_raw))},
           "per_symbol": {}, "affected": [], "identical": []}
    all_ratio_med, all_close_rel = [], []
    for s in sorted(set(cache_raw) & set(db_raw)):
        cm = {r[0]: r for r in cache_raw[s]}
        dm = {r[0]: r for r in db_raw[s]}
        common = sorted(set(cm) & set(dm))
        if len(common) < 30:
            continue
        ratios, closes, dates = [], [], []
        for d in common:
            cv, dv = cm[d][5], dm[d][5]
            if dv and cv:
                ratios.append(cv / dv)
                dates.append(d)
            if dm[d][4]:
                closes.append(abs(cm[d][4] - dm[d][4]) / dm[d][4])
        if not ratios:
            continue
        rmed = _median(ratios)
        cmed = _median(closes)
        all_ratio_med.append(rmed)
        all_close_rel.append(cmed)
        rec = {"n_common_days": len(common), "first_d": common[0], "last_d": common[-1],
               "vol_ratio_median": round(rmed, 4) if rmed else None,
               "vol_ratio_p10": round(_quant(ratios, 0.10), 4),
               "vol_ratio_p90": round(_quant(ratios, 0.90), 4),
               "vol_ratio_min": round(min(ratios), 4), "vol_ratio_max": round(max(ratios), 4),
               "close_rel_diff_median": round(cmed, 8) if cmed else None,
               "close_rel_diff_max": round(max(closes), 8),
               "db_last_d": db_raw[s][-1][0], "cache_last_d": cache_raw[s][-1][0]}
        cp = changepoint(dates, ratios)
        if cp:
            rec["changepoint"] = cp
        out["per_symbol"][s] = rec
        if rmed is not None and (rmed < RATIO_LO or rmed > RATIO_HI):
            out["affected"].append(s)
        if rmed is not None and abs(rmed - 1.0) < 1e-9 and rec["close_rel_diff_max"] < 1e-12:
            out["identical"].append(s)
    out["n_affected"] = len(out["affected"])
    out["n_identical"] = len(out["identical"])
    out["affected_symbols"] = sorted(out["affected"])
    out["identical_symbols"] = sorted(out["identical"])
    out["vol_ratio_median_all"] = round(_median(all_ratio_med), 4) if all_ratio_med else None
    out["vol_ratio_distribution"] = {
        "p05": round(_quant(all_ratio_med, 0.05), 4) if all_ratio_med else None,
        "p25": round(_quant(all_ratio_med, 0.25), 4) if all_ratio_med else None,
        "p50": round(_quant(all_ratio_med, 0.50), 4) if all_ratio_med else None,
        "p75": round(_quant(all_ratio_med, 0.75), 4) if all_ratio_med else None,
        "p95": round(_quant(all_ratio_med, 0.95), 4) if all_ratio_med else None}
    out["close_rel_diff_median_all"] = round(_median(all_close_rel), 10) if all_close_rel else None
    out["close_rel_diff_max_all"] = round(max(all_close_rel), 8) if all_close_rel else None
    # 每个月的「比值中位」:看量纲切换发生在什么时候(全体符号按月汇总)
    per_month = defaultdict(list)
    for s2, rec in out["per_symbol"].items():
        cm2 = {r[0]: r for r in cache_raw[s2]}
        dm2 = {r[0]: r for r in db_raw[s2]}
        for d in sorted(set(cm2) & set(dm2)):
            cv, dv = cm2[d][5], dm2[d][5]
            if cv and dv:
                per_month[d[:7]].append(cv / dv)
    out["ratio_by_month"] = {m: {"median": round(_median(v), 3), "n_sym": len(v)}
                              for m, v in sorted(per_month.items())}
    # 切换点汇总
    cp_months = defaultdict(int)
    lvl_pairs = []
    for rec in out["per_symbol"].values():
        c = rec.get("changepoint")
        if c:
            cp_months[c["date"][:7]] += 1
            lvl_pairs.append((c["mean_left"], c["mean_right"], c["date"]))
    out["changepoint_months"] = dict(sorted(cp_months.items(), key=lambda kv: -kv[1]))
    out["changepoint_levels"] = sorted(lvl_pairs, key=lambda x: -max(x[0], x[1]))[:40]
    return out


def cache_file_breakdown(cache_files, db_raw):
    """逐个缓存文件 × 每月:该文件里的行相对 DB 的成交量比值中位 + 覆盖区间。"""
    out = {}
    for fname, raw in cache_files.items():
        per_month = defaultdict(list)
        n_rows = 0
        dmin = dmax = None
        for s, rows in raw.items():
            dm = {r[0]: r for r in db_raw.get(s, [])}
            for d, o, h, l, c, v in rows:
                n_rows += 1
                dmin = d if dmin is None or d < dmin else dmin
                dmax = d if dmax is None or d > dmax else dmax
                if d in dm and dm[d][5]:
                    per_month[d[:7]].append(v / dm[d][5])
        out[fname] = {"symbols": len(raw), "rows": n_rows, "first_d": dmin, "last_d": dmax,
                      "ratio_by_month": {m: round(_median(v), 3) for m, v in sorted(per_month.items())},
                      "overall_ratio_median": round(_median([x for v in per_month.values() for x in v]), 3)
                      if per_month else None}
    return out


# ── ② 票重生成 ──────────────────────────────────────────────────────────────
def mtm(tickets, bars, d_to=CURVE_TO):
    """s657.mtm 口径:仍持有的票按 d_to 前最后收盘盯市(两边同一 d_to,公平)。"""
    for t in tickets:
        if t.get("r") is None:
            c = last_close_at(bars, t["symbol"], d_to)
            if c is None:
                continue
            t["r"] = (c - t["entry_px"]) / (t["entry_px"] - t["stop_px"]) - COST * t["entry_px"] / (
                t["entry_px"] - t["stop_px"])
            t["still"] = True
    return tickets


def gen_tickets(bars, gate):
    return t159.run_long(bars, gate, SIG_FROM, SIG_TO)


def summarise(tickets, bars):
    rs = [t["r"] for t in tickets if t.get("r") is not None]
    curve = list(t159.nav(tickets, bars, F_RISK, cap=CAP, d_to=CURVE_TO))
    st = t159.stats(curve) if curve else None
    out = {"n": len(tickets), "n_with_r": len(rs),
           "total_r": round(sum(rs), 4) if rs else 0.0,
           "mean_r": round(sum(rs) / len(rs), 6) if rs else None,
           "win": round(sum(r > 0 for r in rs) / len(rs), 4) if rs else None,
           "still_open": sum(1 for t in tickets if t.get("still"))}
    if st:
        mdd = st["mdd"]
        out["nav"] = {"d0": st["d0"], "d1": st["d1"], "end": round(st["end"], 6),
                      "annualised": st["annualised"], "mdd": mdd,
                      "calmar": (st["annualised"] / abs(mdd)) if (st["annualised"] and mdd) else None,
                      "taken": st["taken"], "skipped": st["skipped"], "closed": st["closed"]}
    return out


def compare_tickets(tk_cache, tk_db):
    def key(t):
        return (t["symbol"], t["signal_d"])
    cm = {key(t): t for t in tk_cache}
    dm = {key(t): t for t in tk_db}
    both = sorted(set(cm) & set(dm))
    only_c = sorted(set(cm) - set(dm))
    only_d = sorted(set(dm) - set(cm))
    # 同键但出场不同(量变 ⇒ 止损/出场变了)
    diff_exit = [{"symbol": k[0], "signal_d": k[1],
                  "cache_exit_d": cm[k]["exit_d"], "db_exit_d": dm[k]["exit_d"],
                  "cache_r": cm[k]["r"], "db_r": dm[k]["r"],
                  "cache_entry_px": cm[k]["entry_px"], "db_entry_px": dm[k]["entry_px"]}
                 for k in both if (cm[k]["exit_d"] != dm[k]["exit_d"] or cm[k]["entry_px"] != dm[k]["entry_px"])]
    def agg(tks):
        rs = [t["r"] for t in tks if t.get("r") is not None]
        return {"n": len(tks), "total_r": round(sum(rs), 4) if rs else 0.0,
                "mean_r": round(sum(rs) / len(rs), 6) if rs else None,
                "win": round(sum(r > 0 for r in rs) / len(rs), 4) if rs else None}
    # 同键票的 R 对照:量纲换了以后,同一张票的 R 变了多少
    rc = [cm[k]["r"] for k in both if cm[k].get("r") is not None and dm[k].get("r") is not None]
    rd = [dm[k]["r"] for k in both if cm[k].get("r") is not None and dm[k].get("r") is not None]
    if len(rc) >= 3:
        n = len(rc)
        mc, md = sum(rc) / n, sum(rd) / n
        cov = sum((a - mc) * (b - md) for a, b in zip(rc, rd))
        vc = sum((a - mc) ** 2 for a in rc) ** 0.5
        vd = sum((b - md) ** 2 for b in rd) ** 0.5
        corr = (cov / (vc * vd)) if (vc and vd) else None
        dr = [b - a for a, b in zip(rc, rd)]
        rstat = {"n_pairs": n, "corr_r": round(corr, 4) if corr is not None else None,
                 "mean_abs_diff": round(sum(abs(x) for x in dr) / n, 4),
                 "median_abs_diff": round(_median([abs(x) for x in dr]), 4),
                 "max_abs_diff": round(max(abs(x) for x in dr), 4),
                 "sign_flip": sum(1 for a, b in zip(rc, rd) if (a > 0) != (b > 0)),
                 "mean_cache_r": round(mc, 4), "mean_db_r": round(md, 4),
                 "total_cache_r": round(sum(rc), 4), "total_db_r": round(sum(rd), 4)}
    else:
        rstat = {"n_pairs": len(rc)}
    return {"both": agg([cm[k] for k in both]),
            "only_cache": agg([cm[k] for k in only_c]),
            "only_db": agg([dm[k] for k in only_d]),
            "r_pairing": rstat,
            "n_both": len(both), "n_only_cache": len(only_c), "n_only_db": len(only_d),
            "only_cache_list": [{"symbol": k[0], "signal_d": k[1], "r": cm[k]["r"]} for k in only_c[:400]],
            "only_db_list": [{"symbol": k[0], "signal_d": k[1], "r": dm[k]["r"]} for k in only_d[:400]],
            "n_same_key_diff_exit": len(diff_exit),
            "same_key_diff_exit_sample": diff_exit[:50]}


def break_analysis(cache_bars, db_bars, gate, tk_cache, tk_db, ratio_by_month):
    """量纲切换点:DB 序列在两个日期上换口径 ⇒ 量能门(当日成交额 ≥ 2× 前 40 日均)被人为制造/掐灭。
    报:两条序列逐日信号数、按月信号数、差额最大的日子、以及切换点 ±60 天的信号数。"""
    def per_day(tks):
        c = defaultdict(int)
        for t in tks:
            c[t["signal_d"]] += 1
        return c
    dc, dd = per_day(tk_cache), per_day(tk_db)
    days = sorted(set(dc) | set(dd))
    diffs = sorted(((dd[d] - dc[d], d, dc[d], dd[d]) for d in days), reverse=True)
    # 按月
    mc, md = defaultdict(int), defaultdict(int)
    for d in days:
        mc[d[:7]] += dc[d]
        md[d[:7]] += dd[d]
    months = sorted(set(mc) | set(md))
    # 切换点(比值中位变化 > 1.5× 的月份边界)
    brk = []
    rbm = ratio_by_month
    ks = [m for m in rbm if "median" in rbm[m]]
    for a, b in zip(ks, ks[1:]):
        ra, rb = rbm[a]["median"], rbm[b]["median"]
        if ra and rb and (max(ra, rb) / min(ra, rb)) >= 1.5:
            brk.append({"from_month": a, "to_month": b, "ratio_from": ra, "ratio_to": rb})
    # 切换点 ±60 天的信号数
    windows = {}
    for b in brk:
        lo, hi = b["from_month"] + "-01", b["to_month"] + "-28"
        sel_c = sum(v for k, v in dc.items() if lo <= k <= hi)
        sel_d = sum(v for k, v in dd.items() if lo <= k <= hi)
        windows[f"{b['from_month']}->{b['to_month']}"] = {"cache_signals": sel_c, "db_signals": sel_d,
                                                         "diff": sel_d - sel_c}
    return {"top10_days_db_minus_cache": [{"d": d, "cache": c, "db": x, "diff": df}
                                           for df, d, c, x in diffs[:10]],
            "bottom10_days": [{"d": d, "cache": c, "db": x, "diff": df} for df, d, c, x in diffs[-10:]],
            "signals_by_month": {m: {"cache": mc[m], "db": md[m], "diff": md[m] - mc[m]} for m in months},
            "breaks": brk, "break_windows": windows}


# ── ③ 宇宙门槛(按月) ────────────────────────────────────────────────────────
def universe_by_month(bars):
    """每月:该月交易日中「30 日均成交额 ≥ 500 万」的符号数(取月中位数)。"""
    cnt_by_day = defaultdict(int)
    days = set()
    for s, rows in bars.items():
        a = t159.indicators(rows)
        for i in range(len(a["d"])):
            if a["adv30"][i] is not None and a["adv30"][i] >= UNIV_ADV:
                cnt_by_day[a["d"][i]] += 1
                days.add(a["d"][i])
    by_month = defaultdict(list)
    for d, c in cnt_by_day.items():
        by_month[d[:7]].append(c)
    return {m: {"median": _median(v), "min": min(v), "max": max(v), "days": len(v)}
            for m, v in sorted(by_month.items())}


def compare_universe(u_cache, u_db):
    months = sorted(set(u_cache) | set(u_db))
    rows = []
    for m in months:
        a = u_cache.get(m, {}).get("median")
        b = u_db.get(m, {}).get("median")
        rows.append({"month": m, "cache": a, "db": b,
                     "diff": (round(b - a, 2) if (a is not None and b is not None) else None)})
    diffs = [r for r in rows if r["diff"] is not None]
    worst = sorted(diffs, key=lambda r: r["diff"])[:12]
    return {"months": rows, "n_months": len(rows),
            "worst_12": worst,
            "median_diff": round(_median([r["diff"] for r in diffs]), 2) if diffs else None,
            "first": rows[0] if rows else None, "last": rows[-1] if rows else None}


# ── ⑤ 闸门核(2026-10-29 → 11-03) ───────────────────────────────────────────
def gate_check(db_bars, db_raw):
    out = {"window": list(GATE_CHECK)}
    # (a) DB 序列上 BTC 收盘 vs 200 日均
    rows = db_bars.get("BTC") or []
    c = [r[4] for r in rows]
    dts = [r[0] for r in rows]
    ma = [t159.win(c, i, 0, 199) for i in range(len(c))]
    per_day = []
    for i, d in enumerate(dts):
        if GATE_CHECK[0] <= d <= GATE_CHECK[1]:
            per_day.append({"d": d, "close": c[i], "ma200": ma[i],
                            "above": (ma[i] is not None and c[i] > ma[i])})
    out["btc_vs_ma200_db_series"] = per_day
    out["btc_last_db_d"] = dts[-1] if dts else None
    # (b) majors 闸门(style_index_pit_daily,majors / cap 权重)——DB 现读
    try:
        rows_s = []
        lo = 0
        while True:
            rr, _ = _rest("style_index_pit_daily?select=d,ret&style=eq.majors&weighting=eq.cap"
                           "&order=d.asc", lo, lo + 999)
            rows_s += rr
            if len(rr) < 1000:
                break
            lo += 1000
        rows_s = [x for x in rows_s if x["ret"] is not None and x["ret"] > -0.95]
        rows_s.sort(key=lambda x: x["d"])
        lvl, cur = [], 1.0
        for x in rows_s:
            cur *= (1.0 + x["ret"])
            lvl.append(cur)
        gate_days = []
        for i, x in enumerate(rows_s):
            if GATE_CHECK[0] <= x["d"] <= GATE_CHECK[1]:
                n = min(i + 1, 200)
                w = t159.win(lvl, i, 0, 199)
                gate_days.append({"d": x["d"], "lvl": round(lvl[i], 4), "ma200": round(w, 4) if w else None,
                                  "gate_open": bool(n < 200 or lvl[i] > w)})
        out["majors_style_gate"] = gate_days
        out["style_rows"] = len(rows_s)
        out["style_last_d"] = rows_s[-1]["d"] if rows_s else None
    except Exception as e:  # noqa: BLE001
        out["majors_style_gate_error"] = f"{type(e).__name__}: {e}"
    # (c) r_tickets_paper / r_money_daily 的现状(只读)
    for tbl in ("r_tickets_paper", "r_money_daily"):
        try:
            rr, cr = _rest(f"{tbl}?select=*", 0, 999, count=True)
            total = cr.split("/")[-1] if "/" in cr else "?"
            out[tbl] = {"rows": total, "sample": rr[:2]}
            if tbl == "r_money_daily" and rr:
                rr2, _ = _rest("r_money_daily?select=d,nav,taken,skipped,closed,open_n,gross"
                               "&order=d.asc", 0, 999)
                out[tbl]["rows_detail"] = {"n": len(rr2), "d0": rr2[0]["d"], "d1": rr2[-1]["d"],
                                           "nav_values": sorted({x["nav"] for x in rr2}),
                                           "taken_sum": sum(x["taken"] or 0 for x in rr2),
                                           "closed_sum": sum(x["closed"] or 0 for x in rr2)}
        except Exception as e:  # noqa: BLE001
            out[tbl] = {"error": f"{type(e).__name__}: {e}"}
    return out


# ── 交叉核对:DB 的 binance_hist 到底是不是「现货」 ───────────────────────────
def perp_crosscheck(cache_raw, db_raw, symbols, lo="2026-08-01", hi="2026-11-03"):
    """拿 binance_um_hist(S-698 拆出来的永续序列)对齐:
    缓存的 volume 像不像 um_hist?DB 的 binance_hist 像不像 um_hist?"""
    out = {"window": [lo, hi], "symbols": {}}
    for s in symbols:
        try:
            rows, _ = _rest(f"ohlcv_daily?select=trade_date,close,volume&source=eq.binance_um_hist"
                            f"&symbol=eq.{s}&trade_date=gte.{lo}&trade_date=lte.{hi}"
                            "&order=trade_date.asc", 0, 999)
        except Exception as e:  # noqa: BLE001
            out["symbols"][s] = {"error": f"{type(e).__name__}: {e}"}
            continue
        um = {r["trade_date"]: (float(r["close"]), float(r["volume"])) for r in rows if r["volume"]}
        cm = {r[0]: r for r in cache_raw.get(s, [])}
        dm = {r[0]: r for r in db_raw.get(s, [])}
        common = sorted(set(um) & set(cm) & set(dm))
        if len(common) < 10:
            out["symbols"][s] = {"n_common": len(common)}
            continue
        r_cache_um = [cm[d][5] / um[d][1] for d in common if um[d][1]]
        r_db_um = [dm[d][5] / um[d][1] for d in common if um[d][1]]
        r_db_cache = [dm[d][5] / cm[d][5] for d in common if cm[d][5]]
        r_px = [abs(dm[d][4] - cm[d][4]) / cm[d][4] for d in common if cm[d][4]]
        r_px_um = [abs(dm[d][4] - um[d][0]) / um[d][0] for d in common if um[d][0]]
        out["symbols"][s] = {
            "n_common": len(common),
            "vol_cache_over_um_median": round(_median(r_cache_um), 4) if r_cache_um else None,
            "vol_db_over_um_median": round(_median(r_db_um), 4) if r_db_um else None,
            "vol_db_over_cache_median": round(_median(r_db_cache), 4) if r_db_cache else None,
            "px_db_vs_cache_rel": round(_median(r_px), 6) if r_px else None,
            "px_db_vs_um_rel": round(_median(r_px_um), 6) if r_px_um else None}
    return out


# ── ⑤ 纸面书空窗:两条序列各出了多少信号 ─────────────────────────────────────
def paper_window(cache_bars, db_bars, gate, lo="2026-10-19", hi="2026-11-03"):
    out = {"window": [lo, hi]}
    for name, bars in (("cache", cache_bars), ("db", db_bars)):
        days = []
        for s, rows in bars.items():
            a = t159.indicators(rows)
            for i in range(220, len(a["d"])):
                d = a["d"][i]
                if not (lo <= d <= hi):
                    continue
                u = a["adv30"][i] is not None and a["adv30"][i] >= UNIV_ADV
                v = a["adv40p"][i] is not None and a["dv"][i] >= 2 * a["adv40p"][i]
                full = t159.sig_long(a, i, gate)
                days.append((d, s, u, v, full))
        by_d = defaultdict(lambda: [0, 0, 0, 0])
        for d, s, u, v, full in days:
            by_d[d][0] += 1
            by_d[d][1] += 1 if u else 0
            by_d[d][2] += 1 if (u and v) else 0
            by_d[d][3] += 1 if full else 0
        out[name] = {"days": {d: {"symbols": c[0], "universe": c[1], "universe_and_vol_gate": c[2],
                                  "full_signal": c[3]} for d, c in sorted(by_d.items())},
                     "max_universe": max((c[1] for c in by_d.values()), default=0),
                     "max_universe_and_vol_gate": max((c[2] for c in by_d.values()), default=0),
                     "max_full_signal": max((c[3] for c in by_d.values()), default=0),
                     "n_full_signal_days": sum(1 for c in by_d.values() if c[3])}
    return out


# ── 自检:缓存侧必须复现 770 张票 ─────────────────────────────────────────────
def selfcheck_770(tk_cache, bars):
    out = {"cache_tickets_generated": len(tk_cache)}
    p = os.path.join(t159.ENV, "_tickets_2020-03-01_2026-06-20.json")
    if not os.path.exists(p):
        out["t159_file"] = "missing"
        return out
    f = json.load(open(p))
    L = f.get("long", [])
    out["t159_file_long_n"] = len(L)
    cm = {(t["symbol"], t["signal_d"]): t for t in tk_cache}
    fm = {(t["symbol"], t["signal_d"]): t for t in L}
    common = sorted(set(cm) & set(fm))
    mism = []
    for k in common:
        a, b = cm[k], fm[k]
        for fld in ("entry_d", "exit_d", "entry_px", "stop_px", "exit_px"):
            if a.get(fld) != b.get(fld):
                mism.append({"k": list(k), "field": fld, "gen": a.get(fld), "file": b.get(fld)})
                break
    out["n_common"] = len(common)
    out["n_mismatch"] = len(mism)
    out["mismatch_sample"] = mism[:20]
    out["gen_only"] = len(set(cm) - set(fm))
    out["file_only"] = len(set(fm) - set(cm))
    return out


# ── main ────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["fetch", "compare", "all"])
    ap.add_argument("--out", default=os.path.join(HERE, "t237_results.json"))
    ap.add_argument("--force-fetch", action="store_true", help="已有 _bars_db.jsonl 时也重拉")
    args = ap.parse_args()

    res = {"meta": {"sig_from": SIG_FROM, "sig_to": SIG_TO, "curve_to": CURVE_TO,
                    "fetch_from": FETCH_FROM, "fetch_to": FETCH_TO, "cost_roundtrip": COST,
                    "universe_adv30_usd": UNIV_ADV, "f_risk": F_RISK, "cap": CAP,
                    "params": "固定 (2.5, 20, 2) —— t159.run_long(= r_v2_tickets.sql 逐字)"}}

    if args.stage in ("fetch", "all"):
        if os.path.exists(DB_JSONL) and not args.force_fetch:
            print(f"[reuse] {DB_JSONL} 已存在,跳过重拉(--force-fetch 可重拉)", file=sys.stderr)
            with open(DB_JSONL) as f:
                res["meta"]["fetch"] = json.loads(f.readline()).get("_meta", {})
        else:
            res["meta"]["fetch"] = fetch_db()

    cache_raw = load_cache_raw()
    db_raw = load_db_raw()
    cache_bars = to_bars(cache_raw)
    db_bars = to_bars(db_raw)
    res["meta"]["cache_bars"] = {"symbols": len(cache_bars), "rows": sum(len(v) for v in cache_bars.values()),
                                 "first_d": min(v[0][0] for v in cache_bars.values()),
                                 "last_d": max(v[-1][0] for v in cache_bars.values())}
    res["meta"]["db_bars"] = {"symbols": len(db_bars), "rows": sum(len(v) for v in db_bars.values()),
                              "first_d": min(v[0][0] for v in db_bars.values()),
                              "last_d": max(v[-1][0] for v in db_bars.values())}
    # 自检:我的缓存 loader == t159.load_bars(t159 官方 loader)
    ref = t159.load_bars()
    same = all(ref.get(s) == cache_bars.get(s) for s in set(ref) | set(cache_bars))
    res["meta"]["cache_loader_matches_t159"] = bool(same)

    gate = t159.load_gate()
    res["meta"]["gate_days"] = len(gate)

    # ① 序列对比
    res["series"] = compare_series(cache_raw, db_raw)
    res["cache_file_breakdown"] = cache_file_breakdown(load_cache_files(), db_raw)

    # ② 票:缓存侧 vs DB 侧
    tk_cache = mtm(gen_tickets(cache_bars, gate), cache_bars)
    tk_db = mtm(gen_tickets(db_bars, gate), db_bars)
    res["tickets"] = {"cache": summarise(tk_cache, cache_bars), "db": summarise(tk_db, db_bars),
                      "compare": compare_tickets(tk_cache, tk_db)}
    res["tickets"]["selfcheck_770"] = selfcheck_770(tk_cache, cache_bars)
    res["breaks"] = break_analysis(cache_bars, db_bars, gate, tk_cache, tk_db, res["series"]["ratio_by_month"])

    # ③ 宇宙门槛按月
    res["universe"] = compare_universe(universe_by_month(cache_bars), universe_by_month(db_bars))

    # ⑤ 闸门核
    res["gate_check"] = gate_check(db_bars, db_raw)
    res["paper_window"] = paper_window(cache_bars, db_bars, gate)
    # 交叉核对:um_hist(永续)是哪一条(两个窗口:中段 2024、末段 2026-06→08-08)
    sample = (res["series"]["affected_symbols"][:8] +
              [s for s in res["series"]["identical_symbols"][:4]] + ["BTC", "ETH"])
    res["perp_crosscheck"] = {"w_2024": perp_crosscheck(cache_raw, db_raw, sample, "2024-01-01", "2024-12-31"),
                              "w_2026H1": perp_crosscheck(cache_raw, db_raw, sample, "2026-06-01", "2026-08-08")}

    json.dump(res, open(args.out, "w"), indent=1, default=str)
    print(json.dumps({"meta": res["meta"], "series_head": {k: v for k, v in res["series"].items()
                                                           if k not in ("per_symbol", "affected_symbols",
                                                                        "identical_symbols")},
                      "tickets": res["tickets"]["cache"]["n"], "db_tickets": res["tickets"]["db"]["n"],
                      "compare": {k: v for k, v in res["tickets"]["compare"].items()
                                  if not k.endswith("_list") and k != "same_key_diff_exit_sample"}},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
