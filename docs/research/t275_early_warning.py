#!/usr/bin/env python3
"""T-275 · S-754 预注册 —— Binance 现货成交额排名掉到底部 10% 的名字,之后 90 天被宣布下架的概率与跑输。

判据(REFUTATION_LEDGER.md § S-754,2026-11-07 Seth 写死,一字不改):
  宇宙 = ohlcv_daily source='binance_hist' 的全部代号(含已停更的);2022-01 → 2026-10 每个月末 m;
         只取 m 当天有收盘、且之前有 ≥ 180 根日线的代号。
  特征(严格 ≤ m):L = 过去 30 天日成交额(close × volume)中位数,在当月截面里的百分位;标记 = L ≤ 10%。
  结果 = (m, m + 90 天] 里该代号出现在 delisting_watch(公告时刻)。
  基率 = 全部代号月里结果为真的比例。
  判据(全满足才 ✅):
    (a) 标记组精度 ≥ 5 × 基率
    (b) 召回 ≥ 40%(公告前那个月末被标记的公告代币 ÷ 全部能算的公告代币)
    (c) 2022-01 → 2024-03 与 2024-04 → 2026-10 两段精度各 ≥ 3 × 基率
    (d) 标记组之后 90 天相对 BTC 超额中位 ≤ −10%

只读:全部走 Supabase REST SELECT;不改代码、不做 DDL、不入库。
统计只用 src/data/evaluation/apparatus.py(盈亏 / 零分布 / A-B);AUC 这类纯描述统计就地算,只报不判。

用法: python3 docs/research/t275_early_warning.py [--refresh]
"""
from __future__ import annotations

import argparse
import calendar
import csv
import importlib.util
import json
import os
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

# ── 零分布 / 盈亏:只用 apparatus.py(硬规则) ────────────────────────────────
_spec = importlib.util.spec_from_file_location("cc_apparatus", os.path.join(REPO, "src", "data", "evaluation", "apparatus.py"))
apparatus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apparatus)
long_return = apparatus.long_return
price_on_or_after = apparatus.price_on_or_after
random_dates_like = apparatus.random_dates_like
null_distribution = apparatus.null_distribution
percentile_of = apparatus.percentile_of

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

# ── 预注册常数(S-754) ─────────────────────────────────────────────────────
PREREG = "S-754"
FIRST_MONTH = "2022-01"          # 宇宙起点
LAST_MONTH = "2026-10"           # 宇宙终点
MIN_PRIOR_BARS = 180             # m 之前的日线根数下限
LOOKBACK_L = 30                  # L 的回看窗口(自然日)
LOOKBACK_TREND = 180             # 成交额趋势的长期窗口(副项)
FORWARD_DAYS = 90                # 结果窗口与持有期
MARK_PCT = 0.10                  # 标记阈值:百分位 ≤ 10%
SEG1 = ("2022-01", "2024-03")    # (c) 第一段
SEG2 = ("2024-04", "2026-10")    # (c) 第二段
CRIT_A_MULT = 5.0                # (a) 精度 ≥ 5 × 基率
CRIT_B_RECALL = 0.40             # (b) 召回 ≥ 40%
CRIT_C_MULT = 3.0                # (c) 每段精度 ≥ 3 × 该段基率
CRIT_D_EXCESS = -0.10            # (d) 标记组 90 天相对 BTC 超额中位 ≤ −10%
NULL_SEED = 754
NULL_N = 2000

# 缓存:默认放 Mac 数据根(不入库);可用 T275_CACHE 覆盖
_DEFAULT_CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t275_cache"
CACHE = os.environ.get("T275_CACHE", _DEFAULT_CACHE)
if not os.path.isdir(os.path.dirname(CACHE)):
    CACHE = os.path.join(HERE, "t275_cache")
OUT_DIR = HERE


# ── 读库 ──────────────────────────────────────────────────────────────────
def _raw(path: str, extra: dict | None = None):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if extra:
        h.update(extra)
    req = urllib.request.Request(URL + "/rest/v1/" + path, headers=h)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode(), r.headers.get("Content-Range")


def _fetch_all(table: str, cols: str, where: str, order: str, page: int = 1000, workers: int = 12):
    """按 order 流式翻页;服务端每页硬上限 1000 行。必须带 order=。"""
    base = f"{table}?select={cols}&{where}&order={order}"
    body, cr = _raw(base, {"Range": f"0-{page - 1}", "Prefer": "count=exact"})
    rows = json.loads(body)
    total = int(cr.split("/")[-1]) if cr and "/" in cr else len(rows)
    npages = (total + page - 1) // page

    def get(i: int):
        b, _ = _raw(base, {"Range": f"{i * page}-{i * page + page - 1}"})
        return json.loads(b)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for chunk in ex.map(get, range(1, npages)):
            rows.extend(chunk)
    if len(rows) != total:
        raise SystemExit(f"抓取不完整:{table} 拿到 {len(rows)} 行,表头说 {total} 行")
    return rows


def _cached(name: str, fn, refresh: bool):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not refresh and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    val = fn()
    with open(path, "w") as fh:
        json.dump(val, fh)
    return val


def load_binance_hist(refresh=False):
    return _cached("ohlcv_binance_hist.json", lambda: _fetch_all(
        "ohlcv_daily", "symbol,trade_date,close,volume", "source=eq.binance_hist",
        "symbol.asc,trade_date.asc"), refresh)


def load_delisting(refresh=False):
    return _cached("delisting_watch.json", lambda: _fetch_all(
        "delisting_watch", "symbol,announced_at,d0,kind", "", "symbol.asc"), refresh)


# ── 序列结构 ──────────────────────────────────────────────────────────────
class Series:
    __slots__ = ("sym", "dates", "closes", "to", "ord")

    def __init__(self, sym, dates, closes, to):
        self.sym = sym
        self.dates = dates
        self.closes = closes
        self.to = to
        self.ord = np.array([date.fromisoformat(d).toordinal() for d in dates], dtype=np.int64)

    def idx_on(self, d: str):
        """d 当天的下标;没有则 None。"""
        o = date.fromisoformat(d).toordinal()
        i = int(np.searchsorted(self.ord, o, side="left"))
        if i < len(self.dates) and self.ord[i] == o:
            return i
        return None

    def window(self, d: str, lo_days: int, hi_days: int = 0):
        """[d - lo_days + 1, d] 之间的 (close×volume) 与 close。"""
        o = date.fromisoformat(d).toordinal()
        a = np.searchsorted(self.ord, o - lo_days + 1, side="left")
        b = np.searchsorted(self.ord, o - hi_days, side="right")
        return a, b


def build_series(rows):
    per = defaultdict(lambda: ([], [], []))
    for r in rows:
        s, d = r["symbol"], r["trade_date"]
        c = r.get("close")
        v = r.get("volume")
        dd, cc, vv = per[s]
        dd.append(d)
        cc.append(c)
        vv.append(None if (c is None or v is None) else float(c) * float(v))
    out = {}
    for s, (dd, cc, vv) in per.items():
        order = np.argsort(np.array(dd))
        out[s] = Series(s, [dd[i] for i in order], [cc[i] for i in order], [vv[i] for i in order])
    return out


def month_ends(first="2022-01", last="2026-10"):
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while True:
        d = date(y, m, calendar.monthrange(y, m)[1]).isoformat()
        out.append(d)
        if d[:7] >= last:
            break
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# ── 第一步:每个月末的截面(先落文件,再算判据) ──────────────────────────
def build_cross_sections(series, delisting, mends):
    """每个月末 m 产出:合格代号 / L / 百分位 / 标记 / 结果。"""
    ann = {}
    for r in delisting:
        ad = str(r["announced_at"])[:10]
        ann[r["symbol"]] = ad
    out = []
    for m in mends:
        o_m = date.fromisoformat(m).toordinal()
        o_end = o_m + FORWARD_DAYS
        recs = []
        for sym, ser in series.items():
            i = ser.idx_on(m)
            if i is None:
                continue
            prior = int(np.searchsorted(ser.ord, o_m, side="left"))
            if prior < MIN_PRIOR_BARS:
                continue
            a, b = ser.window(m, LOOKBACK_L)
            to = [x for x in ser.to[a:b] if x is not None and x > 0]
            if len(to) < 15:          # 30 天窗口里有效成交额太少 → 不可算
                continue
            L = float(np.median(to))
            j30 = ser.idx_on(date.fromordinal(o_m - 30).isoformat())
            mom30 = None
            if j30 is not None and ser.closes[j30]:
                mom30 = float(ser.closes[i] / ser.closes[j30] - 1.0)
            recs.append({"sym": sym, "L": L, "n_bars": len(to),
                         "close_m": ser.closes[i], "mom30": mom30,
                         "ad": ann.get(sym)})
        # 百分位:按 L 升序、同值按代号升序定序,rank → pct = (rank-1)/(N-1)
        recs.sort(key=lambda r: (r["L"], r["sym"]))
        n = len(recs)
        for k, r in enumerate(recs):
            r["pct"] = (k / (n - 1)) if n > 1 else 0.0
            r["marked"] = r["pct"] <= MARK_PCT
            ad = r.pop("ad")
            r["result"] = 1 if (ad is not None and o_m < date.fromisoformat(ad).toordinal() <= o_end) else 0
            r["ann_date"] = ad
        out.append({"m": m, "recs": recs, "n": n})
    return out


def write_monthly_counts(sections, path):
    """① 判据之前先落文件:每个月末截面的代号数、标记数、结果为真数。"""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month_end", "n_eligible", "n_marked", "n_marked_result_true",
                    "n_result_true", "n_universe_codes", "n_lt30_bars"])
        for s in sections:
            recs = s["recs"]
            w.writerow([s["m"], s["n"], sum(1 for r in recs if r["marked"]),
                        sum(1 for r in recs if r["marked"] and r["result"]),
                        sum(1 for r in recs if r["result"]),
                        s.get("n_codes", ""), s.get("n_lt30", "")])
    return path


# ── 盈亏(相对 BTC,90 天) ─────────────────────────────────────────────────
def excess_returns(sections, series, btc_sym="BTC"):
    """给每个观察打上:入场价 m、离场价 m+90(price_on_or_after)、BTC 同期、超额。"""
    btc = series.get(btc_sym)
    if btc is None:
        raise SystemExit("binance_hist 里没有 BTC")
    obs = []
    for s in sections:
        m = s["m"]
        m90 = (date.fromisoformat(m) + timedelta(days=FORWARD_DAYS)).isoformat()
        b_in = btc.closes[btc.idx_on(m)] if btc.idx_on(m) is not None else None
        b_out = price_on_or_after(btc.dates, btc.closes, m90)
        r_btc = long_return(b_in, b_out)
        for r in s["recs"]:
            r["_m"] = m
            ser = series[r["sym"]]
            t_out = price_on_or_after(ser.dates, ser.closes, m90)
            r_tok = long_return(r["close_m"], t_out)
            r["ret_90d"] = r_tok
            r["btc_ret_90d"] = r_btc
            r["excess_90d"] = None if (r_tok is None or r_btc is None) else r_tok - r_btc
            obs.append(r)
    return obs


# ── 判据 ────────────────────────────────────────────────────────────────
def _seg(month: str) -> str:
    if SEG1[0] <= month[:7] <= SEG1[1]:
        return "seg1"
    if SEG2[0] <= month[:7] <= SEG2[1]:
        return "seg2"
    return "other"


def judge(sections, obs):
    all_obs = [r for s in sections for r in s["recs"]]
    n_all = len(all_obs)
    base = sum(r["result"] for r in all_obs) / n_all if n_all else None
    marked = [r for r in all_obs if r["marked"]]
    m_true = sum(r["result"] for r in marked)
    prec = m_true / len(marked) if marked else None

    # (b) 召回:公告前那个月末(该代号可算的最晚月末)被标记 ÷ 全部能算的公告代币
    by_sym = defaultdict(list)
    for s in sections:
        for r in s["recs"]:
            by_sym[r["sym"]].append((s["m"], r))
    delisted_syms = {r["sym"] for r in all_obs if r["ann_date"]}
    ann_map = {r["sym"]: r["ann_date"] for r in all_obs if r["ann_date"]}
    delist_syms = set(ann_map)
    rec_num = rec_den = 0
    rec_detail = []
    for sym in sorted(delist_syms):
        ad = ann_map[sym]
        elig = [(m, r) for (m, r) in by_sym.get(sym, []) if m < ad]
        if not elig:
            continue
        rec_den += 1
        m_last, r_last = max(elig, key=lambda x: x[0])
        hit = bool(r_last["marked"])
        rec_num += int(hit)
        rec_detail.append({"symbol": sym, "announced": ad, "last_month_end": m_last,
                           "marked": hit, "pct": r_last["pct"], "L": r_last["L"]})
    recall = rec_num / rec_den if rec_den else None

    # (c) 两段
    segs = {}
    for tag, (lo, hi) in (("seg1", SEG1), ("seg2", SEG2)):
        pool = [r for s in sections if lo <= s["m"][:7] <= hi for r in s["recs"]]
        mk = [r for r in pool if r["marked"]]
        sb = sum(r["result"] for r in pool) / len(pool) if pool else None
        sp = sum(r["result"] for r in mk) / len(mk) if mk else None
        segs[tag] = {"window": f"{lo}→{hi}", "n_obs": len(pool), "n_marked": len(mk),
                     "n_result_true": sum(r["result"] for r in pool),
                     "base_rate": sb, "precision": sp,
                     "mult_vs_base": (sp / sb) if (sp is not None and sb) else None,
                     "pass": (sp is not None and sb is not None and sp >= CRIT_C_MULT * sb)}

    # (d) 标记组 90 天相对 BTC 超额中位
    ex = [r["excess_90d"] for r in marked if r["excess_90d"] is not None]
    ex_med = float(np.median(ex)) if ex else None
    marked_not_delisted = [r["excess_90d"] for r in marked
                           if not r["result"] and r["excess_90d"] is not None]
    ex_mnd_med = float(np.median(marked_not_delisted)) if marked_not_delisted else None

    crit = {
        "a_precision_vs_base": {"precision": prec, "base_rate": base, "mult": (prec / base) if (prec is not None and base) else None,
                                "threshold": CRIT_A_MULT, "pass": (prec is not None and base is not None and prec >= CRIT_A_MULT * base)},
        "b_recall": {"recall": recall, "numerator": rec_num, "denominator": rec_den, "threshold": CRIT_B_RECALL,
                     "pass": recall is not None and recall >= CRIT_B_RECALL},
        "c_segments": segs,
        "d_excess_median": {"median_excess": ex_med, "n": len(ex), "threshold": CRIT_D_EXCESS,
                            "pass": ex_med is not None and ex_med <= CRIT_D_EXCESS},
    }
    all_pass = all([crit["a_precision_vs_base"]["pass"], crit["b_recall"]["pass"],
                    segs["seg1"]["pass"], segs["seg2"]["pass"], crit["d_excess_median"]["pass"]])
    return {"base_rate": base, "n_obs": n_all, "n_marked": len(marked),
            "n_marked_result_true": m_true, "precision": prec,
            "recall": recall, "recall_detail": rec_detail,
            "criteria": crit, "all_pass": bool(all_pass),
            "marked_not_delisted_excess_median": ex_mnd_med,
            "marked_not_delisted_n": len(marked_not_delisted)}


# ── 副项(只报不判) ───────────────────────────────────────────────────────
def _auc(scores, labels):
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    ok = np.isfinite(s)
    s, y = s[ok], y[ok]
    npos, nneg = int((y == 1).sum()), int((y == 0).sum())
    if npos == 0 or nneg == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        ranks[order[i:j + 1]] = avg
        i = j + 1
    return float((ranks[y == 1].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


def secondary(sections, obs, series):
    out = {}
    all_obs = [r for s in sections for r in s["recs"]]
    # AUC:L(取负)+结果;按月截面内算,再平均;同时给合并 AUC
    per_month_auc, pooled_scores, pooled_y = [], [], []
    for s in sections:
        recs = s["recs"]
        if not recs:
            continue
        sc = [-r["L"] for r in recs]
        yy = [r["result"] for r in recs]
        a = _auc(sc, yy)
        if a is not None:
            per_month_auc.append(a)
        pooled_scores += sc
        pooled_y += yy
    out["auc_L_pooled"] = _auc(pooled_scores, pooled_y)
    out["auc_L_mean_per_month"] = float(np.mean(per_month_auc)) if per_month_auc else None
    out["auc_L_months_scored"] = len(per_month_auc)

    # 20% / 5% 阈值(只报)
    for thr in (0.20, 0.05):
        mk = [r for r in all_obs if r["pct"] <= thr]
        tp = sum(r["result"] for r in mk)
        base = sum(r["result"] for r in all_obs) / len(all_obs)
        out[f"thr_{int(thr*100)}pct"] = {"n_marked": len(mk), "precision": tp / len(mk) if mk else None,
                                         "mult_vs_base": (tp / len(mk) / base) if mk and base else None}

    # 动量排名 / 成交额趋势:单独与合并(只报)
    mom_ok = [r for r in all_obs if r.get("mom30") is not None]
    out["n_with_mom30"] = len(mom_ok)
    out["auc_mom30"] = _auc([r["mom30"] for r in mom_ok], [r["result"] for r in mom_ok])
    out["auc_mom30_neg"] = _auc([-r["mom30"] for r in mom_ok], [r["result"] for r in mom_ok])
    # 成交额趋势:30 天均值 ÷ 180 天均值
    tr = {}
    for s in sections:
        for r in s["recs"]:
            ser = series[r["sym"]]
            a30, b30 = ser.window(s["m"], 30)
            a180, b180 = ser.window(s["m"], 180)
            m30 = [x for x in ser.to[a30:b30] if x is not None and x > 0]
            m180 = [x for x in ser.to[a180:b180] if x is not None and x > 0]
            r["trend_30_180"] = (np.mean(m30) / np.mean(m180)) if (m30 and m180 and np.mean(m180) > 0) else None
            tr[(s["m"], r["sym"])] = r["trend_30_180"]
    tv = [(r["trend_30_180"], r["result"]) for r in all_obs if r.get("trend_30_180") is not None]
    out["n_with_trend"] = len(tv)
    out["auc_trend"] = _auc([a for a, _ in tv], [b for _, b in tv])
    out["auc_trend_neg"] = _auc([-a for a, _ in tv], [b for _, b in tv])
    # 合并:三个特征在当月截面内的百分位平均(L 取负 = 越低越像)
    combined, cl, cy = [], [], []
    for s in sections:
        recs = s["recs"]
        def pr(key, val, invert):
            vals = [r[key] for r in recs if r.get(key) is not None]
            if not vals:
                return
            for r in recs:
                if r.get(key) is None:
                    continue
                less = sum(1 for v in vals if v < r[key])
                eq = sum(1 for v in vals if v == r[key])
                p = (less + 0.5 * eq) / len(vals)
                r["_pct_" + key] = (1.0 - p) if invert else p
        pr("L", None, True)
        pr("mom30", None, True)
        pr("trend_30_180", None, True)
        for r in recs:
            ks = [k for k in ("_pct_L", "_pct_mom30", "_pct_trend_30_180") if k in r]
            if len(ks) == 3:
                combined.append(sum(r[k] for k in ks) / 3.0)
                cl.append(r["result"])
                cy.append(r["result"])
    out["auc_combined_L_mom_trend"] = _auc(combined, cl)
    out["n_combined"] = len(combined)
    return out


def null_check(marked, series, sections, seed=NULL_SEED, n=NULL_N, pre_ann_only=False):
    """副项:随机日期对照(同一个代号、同一年里的另一个月末)下,标记组 90 天超额中位的零分布。

    超额收益与「是否被标记」无关 ⇒ 每个 (代号, 月末) 的超额已经算好,随机日期直接查表。
    pre_ann_only=True:对照日期池只留**公告之前**的月末(否则随机日期可能落在公告之后,
    那个代号的成交额已经崩了,零分布被系统性压低)。
    """
    ex_by_key = {}
    pools = defaultdict(list)
    ann_map = {}
    for s in sections:
        for r in s["recs"]:
            pools[r["sym"]].append(s["m"])
            if r["excess_90d"] is not None:
                ex_by_key[(r["sym"], s["m"])] = r["excess_90d"]
            if r.get("ann_date"):
                ann_map[r["sym"]] = r["ann_date"]
    if pre_ann_only:
        for sym, ds in list(pools.items()):
            ad = ann_map.get(sym)
            if ad:
                pools[sym] = [d for d in ds if d < ad]
            pools[sym] = [d for d in pools[sym] if (sym, d) in ex_by_key]
    events = [(r["sym"], r["_m"]) for r in marked]
    if not events:
        return None

    def one(rng):
        picked = random_dates_like(events, pools, rng)
        vals = [ex_by_key[(sym, d)] for (sym, _), (_, d) in zip(events, picked)
                if d is not None and (sym, d) in ex_by_key]
        return float(np.median(vals)) if vals else float("nan")

    try:
        null = null_distribution(one, n, seed)
    except Exception as e:
        return {"error": str(e)}
    actual = float(np.median([r["excess_90d"] for r in marked if r["excess_90d"] is not None]))
    return {"actual_median_excess": actual, "null_median": float(np.median(null)),
            "percentile_of_actual": percentile_of(actual, null), "n": n, "seed": seed,
            "pre_ann_only": pre_ann_only,
            "note": "随机日期对照:同代号、同年里的另一个月末"}


def recall_variants(sections, obs):
    """召回的另外两种口径(只报):公告前 90 天内任一月末被标记 / 公告前任一月末被标记。"""
    by_sym = defaultdict(list)
    for s in sections:
        for r in s["recs"]:
            by_sym[r["sym"]].append((s["m"], r))
    ann_map = {r["sym"]: r["ann_date"] for r in obs if r["ann_date"]}
    v90_num = v90_den = ever_num = ever_den = 0
    for sym, ad in ann_map.items():
        o_ad = date.fromisoformat(ad).toordinal()
        cands = [(m, r) for (m, r) in by_sym.get(sym, []) if m < ad]
        if not cands:
            continue
        v90_den += 1
        ever_den += 1
        w90 = [(m, r) for (m, r) in cands if 0 < o_ad - date.fromisoformat(m).toordinal() <= 90]
        v90_num += int(any(r["marked"] for _, r in w90))
        ever_num += int(any(r["marked"] for _, r in cands))
    return {"any_month_end_within_90d_before": {"num": v90_num, "den": v90_den,
                                                "recall": v90_num / v90_den if v90_den else None},
            "any_month_end_ever_before": {"num": ever_num, "den": ever_den,
                                          "recall": ever_num / ever_den if ever_den else None}}


# ── 主流程 ──────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    hist = load_binance_hist(args.refresh)
    delist = load_delisting(args.refresh)
    series = build_series(hist)
    mends = month_ends()
    ann_symbols = {r["symbol"] for r in delist}
    universe = sorted(series)

    # 覆盖情况
    cov = {
        "n_codes_binance_hist": len(universe),
        "n_delisting_watch": len(delist),
        "delisting_d0_min": min(str(r["d0"]) for r in delist),
        "delisting_d0_max": max(str(r["d0"]) for r in delist),
        "delisting_with_binance_hist": len(ann_symbols & set(universe)),
        "ohlcv_rows": len(hist),
        "first_trade_date": min(series[s].dates[0] for s in universe),
        "last_trade_date": max(series[s].dates[-1] for s in universe),
        "months": len(mends),
    }
    from collections import Counter
    cov["ann_year_all"] = sorted(Counter(str(r["d0"])[:4] for r in delist).items())
    cov["ann_year_with_binance_hist"] = sorted(Counter(str(r["d0"])[:4] for r in delist
                                                       if r["symbol"] in series).items())
    _pb = []
    for r in delist:
        s = r["symbol"]
        if s not in series:
            continue
        o = date.fromisoformat(str(r["d0"])).toordinal()
        _pb.append(int(np.searchsorted(series[s].ord, o, side="left")))
    cov["prior_bars_before_announce"] = {"min": min(_pb), "max": max(_pb),
                                          "median": int(np.median(_pb)),
                                          "n_ge_180": sum(1 for v in _pb if v >= MIN_PRIOR_BARS)}

    sections = build_cross_sections(series, delist, mends)
    for s in sections:
        s["n_codes"] = len(universe)
        s["n_lt30"] = sum(1 for r in s["recs"] if r["n_bars"] < LOOKBACK_L)
    monthly_path = os.path.join(OUT_DIR, "t275_monthly_counts.csv")
    write_monthly_counts(sections, monthly_path)          # ① 先落文件

    obs = excess_returns(sections, series)

    res = judge(sections, obs)
    res["coverage"] = cov
    res["universe_sample"] = universe[:10]
    res["monthly_counts_file"] = os.path.relpath(monthly_path, REPO)
    res["prereg"] = PREREG
    res["as_of"] = "2026-11-07"

    # 副项
    res["secondary"] = secondary(sections, obs, series)
    res["recall_variants"] = recall_variants(sections, obs)
    marked = [r for s in sections for r in s["recs"] if r["marked"]]
    res["secondary"]["null_random_dates"] = null_check(marked, series, sections)
    res["secondary"]["null_random_dates_pre_ann"] = null_check(marked, series, sections, pre_ann_only=True)

    out_path = os.path.join(OUT_DIR, "t275_results.json")
    with open(out_path, "w") as fh:
        json.dump(res, fh, indent=1, default=str)

    print(json.dumps({k: res[k] for k in ("base_rate", "n_obs", "n_marked", "precision",
                                          "recall", "all_pass", "criteria",
                                          "marked_not_delisted_excess_median")},
                     indent=1, default=str))
    print("coverage:", json.dumps(cov, default=str))
    print("secondary:", json.dumps(res["secondary"], indent=1, default=str))


if __name__ == "__main__":
    main()
