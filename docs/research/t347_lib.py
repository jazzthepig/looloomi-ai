#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-347 / S-823 —— 三态敞口(明显向下 −0.3 / 不明确 +0.3 / 明显向上 +1.0)共用件。

数据源(只读):
  · 价格  = Supabase `macro_daily` 的 series='btc_price_usd'(Coin Metrics),PostgREST 翻页带 order=d.asc
  · 资金费= /Volumes/CometCloudAI/cometcloud-local/research/s681/_um_funding.jsonl 的 BTC

零分布 / 多空盈亏只 import `src/data/evaluation/apparatus.py`,不另起炉灶。

账户口径(S-823 写死):
  账户日收益 = e × BTC 日收益 − 10bp × |Δe| + 空头期间的资金费
  信号 d 日收盘定,d + 1 日生效 ⇒ 返回期 [i−1, i] 用 e[i−1]。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.data.evaluation import apparatus  # noqa: E402

# ── 常量(S-823 写死)────────────────────────────────────────────────────────
E_DOWN = -0.3       # 趋势明显向下
E_UNCLEAR = 0.3     # 不明确
E_UP = 1.0          # 趋势明显向上
E_FLAT = 0.0        # 空仓(只 R8 有)
COST_BPS = 10.0     # 换手成本 10bp
FUNDING_FILE = "/Volumes/CometCloudAI/cometcloud-local/research/s681/_um_funding.jsonl"
CACHE_DIR = "/Volumes/CometCloudAI/cometcloud-local/research/t347"

DISCOVERY_START = "2012-01-01"
DISCOVERY_END = "2020-12-31"
HOLDOUT_START = "2021-01-01"
HOLDOUT_END = "2026-10-30"


# ── 价格取数(Supabase macro_daily,只读)───────────────────────────────────
def _env() -> Tuple[str, str]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY 环境变量,退出")
    return url.rstrip("/"), key


def fetch_btc_price(d_from: Optional[str] = None, d_to: Optional[str] = None,
                    cache_name: Optional[str] = None) -> List[Tuple[str, float]]:
    """取 series='btc_price_usd' 的 (d, value)。服务端按日期过滤(发现段/留出段分离靠这一层)。

    翻页:每页 ≤ 1000 行,带 order=d.asc + Range 头;读完核对 Content-Range 总数。
    """
    url, key = _env()
    sel = "d,value"
    flt = "series=eq.btc_price_usd"
    if d_from:
        flt += f"&d=gte.{d_from}"
    if d_to:
        flt += f"&d=lte.{d_to}"
    path = f"/rest/v1/macro_daily?select={sel}&{flt}&order=d.asc"

    cache_path = os.path.join(CACHE_DIR, cache_name) if cache_name else None
    if cache_path and os.path.exists(cache_path):
        with open(cache_path) as fh:
            raw = json.load(fh)
        return [(r["d"], float(r["value"])) for r in raw]

    hdr = {"apikey": key, "Authorization": "Bearer " + key, "Prefer": "count=exact"}
    rows: List[Tuple[str, float]] = []
    start = 0
    total = None
    while True:
        h = dict(hdr)
        h["Range"] = f"{start}-{start + 999}"
        req = urllib.request.Request(url + path, headers=h)
        with urllib.request.urlopen(req, timeout=120) as resp:
            cr = resp.headers.get("Content-Range")
            page = json.loads(resp.read().decode())
        if total is None and cr:
            total = int(cr.split("/")[-1])
        for r in page:
            rows.append((r["d"], float(r["value"])))
        if len(page) < 1000:
            break
        start += 1000
        if total is not None and len(rows) >= total:
            break
    if total is not None and len(rows) != total:
        raise SystemExit(f"取数行数不符:拿到 {len(rows)} 行,Content-Range 说 {total} 行")
    # 同一 d 重复行(多 source)⇒ 取最后一条
    dedup: Dict[str, float] = {}
    for d, v in rows:
        dedup[d] = v
    out = sorted(dedup.items())
    if cache_path:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w") as fh:
            json.dump([{"d": d, "value": v} for d, v in out], fh)
    return out


# ── 资金费(8 小时一次,UTC 日聚合)────────────────────────────────────────
def load_btc_funding(cache_name: str = "funding_btc.json") -> Dict[str, float]:
    """BTC 永续资金费:每天的费率合计(3 个 8 小时点求和)。读不到就 {} (记 0 并单列)。"""
    cache_path = os.path.join(CACHE_DIR, cache_name)
    if os.path.exists(cache_path):
        with open(cache_path) as fh:
            return {k: float(v) for k, v in json.load(fh).items()}
    out: Dict[str, float] = {}
    with open(FUNDING_FILE) as fh:
        for line in fh:
            if '"symbol": "BTC"' not in line:
                continue
            rec = json.loads(line)
            if rec.get("symbol") != "BTC":
                continue
            for ts, rate in rec.get("rates") or []:
                day = str(ts)[:10]
                out[day] = out.get(day, 0.0) + float(rate)
            break
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "w") as fh:
        json.dump(out, fh)
    return out


# ── 部件(S-823 写死)───────────────────────────────────────────────────────
def indicators(dates: Sequence[str], closes: Sequence[float]) -> Dict[str, np.ndarray]:
    c = np.asarray(closes, dtype=float)
    n = len(c)

    def roll_mean(k: int) -> np.ndarray:
        out = np.full(n, np.nan)
        if n >= k:
            cs = np.concatenate(([0.0], np.cumsum(c)))
            out[k - 1:] = (cs[k:] - cs[:-k]) / k
        return out

    def roll_min(k: int) -> np.ndarray:
        out = np.full(n, np.nan)
        for i in range(k - 1, n):
            out[i] = float(np.min(c[i - k + 1: i + 1]))
        return out

    m200 = roll_mean(200)
    m50 = roll_mean(50)
    slope = np.full(n, np.nan)          # M200 的 30 日变化
    if n > 30:
        slope[30:] = m200[30:] - m200[:-30]
    ret20 = np.full(n, np.nan)          # 20 日收益
    if n > 20:
        ret20[20:] = c[20:] / c[:-20] - 1.0
    low90 = roll_min(90)
    return {"P": c, "M200": m200, "M50": m50, "slope": slope,
            "ret20": ret20, "low90": low90}


# ── 规则族(8 条,写完不加)─────────────────────────────────────────────────
def exposures(ind: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """规则名 → 敞口序列 e[i](i 日收盘定的信号)。"""
    P, M200, M50 = ind["P"], ind["M200"], ind["M50"]
    slope, ret20, low90 = ind["slope"], ind["ret20"], ind["low90"]
    n = len(P)

    def r2_base() -> Tuple[np.ndarray, np.ndarray]:
        slope_ok = ~np.isnan(slope)
        up = slope_ok & (~np.isnan(M200)) & (P > M200) & (slope > 0)
        dn = slope_ok & (~np.isnan(M200)) & (P < M200) & (slope < 0)
        return up, dn

    def r3_base() -> Tuple[np.ndarray, np.ndarray]:
        ok = (~np.isnan(M50)) & (~np.isnan(M200))
        up = ok & (M50 > M200) & (P > M200)
        dn = ok & (M50 < M200) & (P < M200)
        return up, dn

    out: Dict[str, np.ndarray] = {}

    # R1:上 = P > M200;下 = P < M200(两态)
    v = np.full(n, E_UNCLEAR)
    v[(~np.isnan(M200)) & (P > M200)] = E_UP
    v[(~np.isnan(M200)) & (P < M200)] = E_DOWN
    out["R1"] = v

    # R2:上 = P > M200 且 slope > 0;下 = P < M200 且 slope < 0;其余不明确
    v = np.full(n, E_UNCLEAR)
    up, dn = r2_base()
    v[up] = E_UP
    v[dn] = E_DOWN
    out["R2"] = v

    # R3:上 = M50 > M200 且 P > M200;下 = M50 < M200 且 P < M200
    v = np.full(n, E_UNCLEAR)
    up, dn = r3_base()
    v[up] = E_UP
    v[dn] = E_DOWN
    out["R3"] = v

    # R4 = R2,「下」另要 ret20 < 0
    v = np.full(n, E_UNCLEAR)
    up, dn = r2_base()
    dn = dn & (np.nan_to_num(ret20, nan=1.0) < 0)
    v[up] = E_UP
    v[dn] = E_DOWN
    out["R4"] = v

    # R5 = R3,「下」另要 ret20 < 0
    v = np.full(n, E_UNCLEAR)
    up, dn = r3_base()
    dn = dn & (np.nan_to_num(ret20, nan=1.0) < 0)
    v[up] = E_UP
    v[dn] = E_DOWN
    out["R5"] = v

    # R6 = R2,但 P 比 low90 高出 25% 以上时「下」降为不明确(V 形护栏)
    v = np.full(n, E_UNCLEAR)
    up, dn = r2_base()
    v_rail = (~np.isnan(low90)) & (P > low90 * 1.25)
    dn = dn & (~v_rail)
    v[up] = E_UP
    v[dn] = E_DOWN
    out["R6"] = v

    # R7 = R4 + R6
    v = np.full(n, E_UNCLEAR)
    up, dn = r2_base()
    dn = dn & (np.nan_to_num(ret20, nan=1.0) < 0)
    dn = dn & (~v_rail)
    v[up] = E_UP
    v[dn] = E_DOWN
    out["R7"] = v

    # R8(对照)= R2,但「下」的敞口是 0(只空仓不做空)
    v = np.full(n, E_UNCLEAR)
    up, dn = r2_base()
    v[up] = E_UP
    v[dn] = E_FLAT
    out["R8"] = v

    # 一直持有
    out["HOLD"] = np.full(n, E_UP)
    return out


# ── 账户口径回测 ─────────────────────────────────────────────────────────
def simulate(dates: Sequence[str], closes: Sequence[float], e: np.ndarray,
             funding: Dict[str, float]) -> Dict:
    """e[i] = i 日收盘定的敞口,返回期 [i−1, i] 用 e[i−1]。

    账户日收益 = e × BTC 日收益 − 10bp × |Δe| + 空头期间的资金费
    资金费:返回期所属日历日 d 的费率合计 × max(0, −e) —— 空头收租(费率 > 0 时多头付、空头收)。
    """
    n = len(dates)
    p = np.asarray(closes, dtype=float)
    r = np.zeros(n)
    r[1:] = p[1:] / p[:-1] - 1.0
    eq = np.ones(n)
    ret = np.zeros(n)
    cost_tot = 0.0
    fund_tot = 0.0
    for i in range(1, n):
        ei = e[i - 1]
        r_acct = ei * r[i]
        if ei < 0:
            f = funding.get(dates[i], 0.0)
            r_acct += (-ei) * f
            fund_tot += (-ei) * f
        de = abs(e[i] - e[i - 1])
        c = de * COST_BPS / 1e4
        r_acct -= c
        cost_tot += c
        ret[i] = r_acct
        eq[i] = eq[i - 1] * (1.0 + r_acct)
    # 建仓成本:从 0 建到 e[0](与 T-252 的 np.diff(pos, prepend=0.0) 同口径)
    c0 = abs(e[0]) * COST_BPS / 1e4
    ret[0] -= c0
    cost_tot += c0
    eq[0] = 1.0 + ret[0]
    return {"dates": list(dates), "ret": ret, "equity": eq, "exposure": e,
            "cost_total": cost_tot, "funding_total": fund_tot}


def longest_underwater(dates: Sequence[str], equity: np.ndarray) -> Dict:
    """从高点到净值第一次回到它的日历日数。最长水下(含未闭合的一段)。"""
    peak = equity[0]
    peak_i = 0
    best = 0
    best_span: Tuple[str, str, bool] = ("", "", False)
    closed_best = 0
    for i in range(len(equity)):
        if equity[i] >= peak:
            dur = int((np.datetime64(dates[i]) - np.datetime64(dates[peak_i])).astype(int))
            if dur > best:
                best = dur
                best_span = (dates[peak_i], dates[i], True)
            if dur > closed_best:
                closed_best = dur
            peak = equity[i]
            peak_i = i
    dur_open = int((np.datetime64(dates[-1]) - np.datetime64(dates[peak_i])).astype(int))
    if dur_open > best:
        best = dur_open
        best_span = (dates[peak_i], dates[-1], False)
    return {"longest_underwater_days": int(best),
            "longest_closed_underwater_days": int(closed_best),
            "underwater_span": list(best_span)}


def metrics(dates: Sequence[str], closes: Sequence[float], e: np.ndarray,
            funding: Dict[str, float]) -> Dict:
    sim = simulate(dates, closes, e, funding)
    eq = sim["equity"]
    days = int((np.datetime64(dates[-1]) - np.datetime64(dates[0])).astype(int))
    total = eq[-1] / eq[0] - 1.0
    cagr = (eq[-1] / eq[0]) ** (365.25 / max(days, 1)) - 1.0
    runmax = np.maximum.accumulate(eq)
    dd = eq / runmax - 1.0
    uw = longest_underwater(dates, eq)
    n = len(dates)
    counts = {
        "down_days": int(np.sum(e < 0)),
        "flat_days": int(np.sum(e == 0)),
        "unclear_days": int(np.sum((e > 0) & (e < 1))),
        "up_days": int(np.sum(e == 1.0)),
    }
    sw = np.abs(np.diff(e, prepend=0.0))
    out = {
        "total_return": float(total),
        "cagr": float(cagr),
        "max_drawdown": float(np.min(dd)),
        "years": days / 365.25,
        "turnover_events": int(np.sum(sw > 0)),
        "cost_total": float(sim["cost_total"]),
        "funding_total": float(sim["funding_total"]),
        **counts, **uw,
    }
    out["_sim"] = sim
    return out


# ── 空头腿(只算 e < 0 的日子)────────────────────────────────────────────
def short_leg(dates: Sequence[str], closes: Sequence[float], e: np.ndarray,
              funding: Dict[str, float], d_from: Optional[str] = None,
              d_to: Optional[str] = None) -> Dict:
    """空头腿自己的账:1 倍名义(空头腿按 1 倍折算)。

    价格口径:与 T-252 定义 C 同形 —— `apparatus.short_return(px[i-1], px[i])`(c_t/c_{t−1} − 1 取负)。
    腿只吃 e < 0 的那些返回期。资金费另计(空头收租)。
    """
    p = np.asarray(closes, dtype=float)
    n = len(dates)
    sel = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if e[i - 1] < 0:
            sel[i] = True
    if d_from:
        sel &= np.array([d >= d_from for d in dates])
    if d_to:
        sel &= np.array([d <= d_to for d in dates])
    leg_ret: List[float] = []
    leg_days: List[str] = []
    leg_fund = 0.0
    for i in range(1, n):
        if not sel[i]:
            continue
        sr = apparatus.short_return(p[i - 1], p[i])
        if sr is None:
            continue
        leg_ret.append(float(sr))
        leg_days.append(dates[i])
        leg_fund += (-e[i - 1]) * funding.get(dates[i], 0.0)
    if not leg_ret:
        return {"days": 0, "total_return": None, "scaled_total_return": None,
                "funding": 0.0, "leg_series": [], "leg_dates": []}
    arr = np.asarray(leg_ret, dtype=float)
    total = float(np.prod(1.0 + arr) - 1.0)
    # 折到 0.3 名义:账户在空头日赚 e × BTC 日收益 = (−0.3) × (−short_ret) = +0.3 × short_ret
    scaled = float(np.prod(1.0 + 0.3 * arr) - 1.0)
    return {"days": int(len(arr)), "total_return": total, "scaled_total_return": scaled,
            "funding": float(leg_fund), "leg_series": leg_ret, "leg_dates": leg_days}


def leg_without_best(leg_dates: Sequence[str], leg_series: Sequence[float],
                      year_segments: Dict[str, Tuple[str, str]]) -> Dict:
    """「去掉最好一段」与「去掉最好一笔」—— 只报不判(Jazz 10-20)。

    year_segments: 段名 → (起, 止),按日归属;每段用空头腿自己的收益算。
    """
    if not len(leg_series):
        return {}
    arr = np.asarray(leg_series, dtype=float)
    total = float(np.prod(1.0 + arr) - 1.0)
    seg_tot = {}
    for sname, (a, b) in year_segments.items():
        m = np.array([(d >= a and d <= b) for d in leg_dates])
        if m.sum() == 0:
            continue
        seg_tot[sname] = (float(np.prod(1.0 + arr[m]) - 1.0), int(m.sum()))
    best_seg = max(seg_tot.items(), key=lambda kv: kv[1][0])[0] if seg_tot else None
    if best_seg is not None:
        a, b = year_segments[best_seg]
        m = np.array([(d >= a and d <= b) for d in leg_dates])
        ex_seg = float(np.prod(1.0 + arr[~m]) - 1.0)
    else:
        ex_seg = None
    k = int(np.argmax(arr))
    mask = np.ones(len(arr), dtype=bool)
    mask[k] = False
    ex_day = float(np.prod(1.0 + arr[mask]) - 1.0)
    return {"leg_total": total, "segment_totals": seg_tot, "best_segment": best_seg,
            "total_without_best_segment": ex_seg, "total_without_best_day": ex_day,
            "best_day": leg_dates[k], "best_day_ret": float(arr[k])}


def short_flag(dates: Sequence[str], e: np.ndarray) -> np.ndarray:
    """返回期 [i−1, i] 的持仓为负 ⇒ 该返回期在空头腿里。"""
    n = len(dates)
    f = np.zeros(n, dtype=int)
    for i in range(1, n):
        f[i] = 1 if e[i - 1] < 0 else 0
    return f
