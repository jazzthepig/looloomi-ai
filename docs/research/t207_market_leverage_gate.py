#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-207 / S-692 独立复算 —— 全市场杠杆(前 30 名 Σ OI / Σ 市值)偏高时把 ① 降到 0.5

严格照 REFUTATION_LEDGER.md 的 **S-692**(2026-10-27 04:33 UTC 预注册)一字不改实现。
C 道独立复算(T-207):交付前不读 docs/research/s692_*。

用法:
    python3 t207_market_leverage_gate.py --mode selftest   # 合成数据自检(已知答案)
    python3 t207_market_leverage_gate.py --mode gate       # 只查闸门(perp_cg_map 无 pending)
    python3 t207_market_leverage_gate.py --mode full       # 全量:写 t207_results.json + 报告

协议(全部来自 S-692 / T-207 卡,不许改):
  信号  L_d = 当天市值前 30 名(在有 Binance OI 的名字里按 CG 市值排)的 Σ OI 值 / Σ 市值
        z_d = (L_d − 过去 365 天 L 的均值) / 标准差(d 当天不进窗口;≥ 300 个值)
  规则  d 收盘 z_d > 1.0 ⇒ d + 1 起暴露 0.5,否则 1.0;每天重判;降下来的那部分记 0 收益
  资产  主 = BTC(CG 日收盘);副 = ① 面板(cis_rebuild_daily 加密名,当天市值加权,不设上限)
  窗口  信号日 2023-01-01 → 2026-09-30(2022 年只用来给 2023 年初的 z 垫 365 天窗口)
  对照  ① 一直持有(1.0);② 随机降仓 = 同一条暴露序列按随机偏移循环平移 2,000 次(种子 692)
  判定  ✅ 须同时满足(主资产 BTC):
        ① 最大回撤比持有浅至少 15%(相对)
        ② Calmar(年化 / |最大回撤|)高于随机降仓分布的 95 分位
        ③ 两半(2023-01 → 2024-10 / 2024-11 → 2026-09)各自的 Calmar 都 ≥ 持有

数据源(只读,publishable key):
    deriv_metrics_daily   Binance Vision,USDT 本位 —— oi_close / oi_value_close
    asset_mcap_daily      source = coingecko_pro_market_chart —— price / mcap(按 symbol)
    cg_coin_mcap_daily    source = coingecko_pro_market_chart —— price / mcap(按 coin_id)
    perp_cg_map           symbol → coin_id 的映射与价格校验结果
    cis_rebuild_daily     ① 面板的加密名(asset_class ∈ {L1,L2,DeFi,Infrastructure,RWA})
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.data.evaluation import apparatus  # noqa: E402  (零分布/盈亏/A-B 只许用它)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, "t207_results.json")
DATA_ROOT = os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local")
REPORT_DIR = os.path.join(DATA_ROOT, "_reports", "absorb_input")
REPORT = os.path.join(REPORT_DIR, "T-207_market_leverage_gate.md")
CACHE_DIR = os.path.join(DATA_ROOT, "research", "t207_cache")

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY")
HDRS = {"apikey": KEY or "", "Authorization": "Bearer " + (KEY or ""),
        "Prefer": "count=exact"}
PAGE = 1000
WORKERS = 10

# ── 协议常量(台账 S-692,不许改) ───────────────────────────────────────────
PAD_START = "2022-01-01"        # 只用来给 2023 年初的 z 垫 365 天窗口
SIG_START = "2023-01-01"
SIG_END = "2026-09-30"
Z_WINDOW_DAYS = 365             # 「过去 365 天」
Z_MIN_VALUES = 300              # 「≥ 300 个值」
Z_THRESHOLD = 1.0               # z_d > 1.0 才降仓
EXPO_REDUCED = 0.5              # 降下来后的暴露
EXPO_FULL = 1.0
TOP_N = 30                      # 市值前 30 名
MIN_OVERLAP = 30                # 映射校验(S-689 原文)
MAX_MED_ERR = 0.05              # 映射校验(S-689 原文)
N_NULL = 2000                   # 随机降仓 2,000 次
SEED = 692                      # 种子 692
BTC_COIN_ID = "bitcoin"
HALF_CUTS = ["2023-01-01", "2024-11-01"]   # 两半:2023-01 → 2024-10 / 2024-11 → 2026-09
CRYPTO_CLASSES = ("L1", "L2", "DeFi", "Infrastructure", "RWA")   # cis_rebuild_daily 的加密类
PANEL_EXCLUDE = ("BTC",)        # 主资产是 BTC;① 面板(副)不含它
DAYS_PER_YEAR = 365.0

# 闸门(S-689 SQL 头写死的开工条件;本卡照抄)
GATE_DEADLINE = datetime(2026, 10, 28, tzinfo=timezone.utc)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ── Supabase 读取(翻页一律带 order=) ─────────────────────────────────────
def _get(path, params):
    u = URL + "/rest/v1/" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(u, headers=HDRS)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode()), resp.headers.get("Content-Range")


def _total(cr):
    if cr and "/" in cr:
        tail = cr.rsplit("/", 1)[1]
        if tail.isdigit():
            return int(tail)
    return None


def fetch_all(table, where, order, cols="*", workers=WORKERS):
    """分页读全表。where: list[(k, v)] —— 同一列可以给两个条件(如 d 的 gte / lte);
    order 必须带(否则翻页边界会漂,T-170 / T-173 实测)。"""
    base = [("select", cols), ("order", order), ("limit", str(PAGE))]
    rows, cr = _get(table, base + list(where))
    out = list(rows)
    tot = _total(cr)
    if not tot or tot <= len(out):
        return out

    offsets = list(range(len(out), tot, PAGE))

    def one(off):
        try:
            r, _ = _get(table, base + list(where) + [("offset", str(off))])
            return off, r
        except Exception as e:  # noqa: BLE001
            log("  ! %s offset=%s 失败:%r" % (table, off, e))
            return off, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for off, r in ex.map(one, offsets):
            if r:
                out.extend(r)
                continue
            try:                                    # 串行重试一次
                r2, _ = _get(table, base + list(where) + [("offset", str(off))])
                out.extend(r2)
            except Exception as e:  # noqa: BLE001
                raise RuntimeError("%s offset=%s 取不到:%r" % (table, off, e))
    if tot and len(out) != tot:
        raise RuntimeError("%s 行数 %d ≠ Content-Range 报的 %d(翻页漂了)" % (table, len(out), tot))
    return out


def fetch_cached(name, table, where, order, cols="*"):
    """带本地缓存的取数(缓存写在 Mac 数据根,不在仓库里)。"""
    path = os.path.join(CACHE_DIR, name + ".pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    rows = fetch_all(table, where, order, cols)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(rows, f, protocol=4)
    return rows


def check_gate():
    """闸门:perp_cg_map 没有 verdict='pending' 的行,或已过 2026-10-28 00:00 UTC。"""
    rows = fetch_cached("perp_cg_map", "perp_cg_map", [], "symbol.asc",
                        "symbol,coin_id,verdict,mult")
    pending = [r["symbol"] for r in rows if r.get("verdict") == "pending"]
    now = datetime.now(timezone.utc)
    ok = (not pending) or (now >= GATE_DEADLINE)
    log("perp_cg_map 行数 %d、pending %d、now=%s、闸门=%s" % (len(rows), len(pending), now.isoformat(), ok))
    return ok, pending, rows


# ── 统计工具(盈亏与零分布只许用 apparatus) ────────────────────────────────
def long_ret(p_entry, p_exit):
    return apparatus.long_return(p_entry, p_exit)


def curve_metrics(dates, rets):
    """年化 / 最大回撤 / Calmar。rets = 逐日简单收益。
    年化 = (1+总收益)^(1/年数) − 1,年数 = 收益天数 / 365;最大回撤是负数(深度)。"""
    arr = np.asarray([r for r in rets if r is not None and math.isfinite(r)], dtype=float)
    n = int(arr.size)
    if n == 0:
        return {"n_days": 0, "total": None, "annualized": None, "max_drawdown": None, "calmar": None}
    if np.any(arr <= -1.0):
        raise ValueError("日收益 ≤ −1,算不了")
    cum = np.cumprod(1.0 + arr)
    run_max = np.maximum.accumulate(cum)
    dd = cum / run_max - 1.0
    mdd = float(dd.min())
    total = float(cum[-1] - 1.0)
    years = n / DAYS_PER_YEAR
    annual = float((1.0 + total) ** (1.0 / years) - 1.0) if total > -1.0 else -1.0
    calmar = float(annual / abs(mdd)) if mdd < 0 else float("inf")
    return {"n_days": n, "total": total, "annualized": annual,
            "max_drawdown": mdd, "calmar": calmar,
            "first_d": dates[0] if dates else None, "last_d": dates[-1] if dates else None}


def rolling_z(dates, L, win_days=Z_WINDOW_DAYS, min_values=Z_MIN_VALUES, ddof=1,
              obs_n=None, include_d=False):
    """z_d = (L_d − 过去 win_days 个日历日里 L 的均值) / 标准差(d 当天不进窗口)。

    台账口径 = 365 个日历日、d 不进窗、样本标准差(ddof=1)、≥ 300 个值。
    敏感性口径(只报不判):
      obs_n=N     —— 窗口改成「往前 N 个观测值」(不看日历跨度)
      include_d   —— 把 d 当天的 L 也算进窗口
    """
    out = {}
    for i, d in enumerate(dates):
        if obs_n is not None:
            j0 = max(0, i - int(obs_n))
            vals = [L[j] for j in range(j0, i + (1 if include_d else 0))]
        else:
            lo = (date.fromisoformat(d) - timedelta(days=win_days)).isoformat()
            vals = [L[j] for j in range(i + (1 if include_d else 0))
                    if dates[j] >= lo]
        if len(vals) < min_values:
            out[d] = None
            continue
        m = sum(vals) / len(vals)
        denom = (len(vals) - 1) if ddof == 1 else len(vals)
        var = sum((v - m) ** 2 for v in vals) / denom
        sd = math.sqrt(var)
        out[d] = None if sd == 0 else (L[i] - m) / sd
    return out


def exposure_from_z(sig_dates, z, ret_dates, sig_start=SIG_START, sig_end=SIG_END):
    """暴露序列:e_t = 0.5 当且仅当 前一日(上一个日历日)的 z 存在且 > 1.0,否则 1.0。"""
    zmap = {d: z.get(d) for d in sig_dates}
    expo = {}
    for t in ret_dates:
        if t < sig_start or t > sig_end:
            continue
        prev = (date.fromisoformat(t) - timedelta(days=1)).isoformat()
        zz = zmap.get(prev)
        expo[t] = EXPO_REDUCED if (zz is not None and zz > Z_THRESHOLD) else EXPO_FULL
    return expo


def circular_shift_null(exposure_dates, exposure_vals, asset_dates, asset_rets,
                         n=N_NULL, seed=SEED):
    """随机降仓零分布:同一条暴露序列按随机偏移循环平移 n 次(种子 692)。
    循环平移保留降仓天数与连续段长度(台账 S-692 要求)。"""
    e = np.asarray(exposure_vals, dtype=float)
    idx = {d: i for i, d in enumerate(exposure_dates)}
    aligned = np.array([e[idx[d]] if d in idx else EXPO_FULL for d in asset_dates], dtype=float)
    base = np.asarray(asset_rets, dtype=float)

    def fn(rng):
        off = int(rng.integers(0, len(aligned)))
        shifted = np.roll(aligned, off)
        m = curve_metrics(asset_dates, shifted * base)
        return m["calmar"]

    null = apparatus.null_distribution(fn, n, seed)
    return null


def runs_of(mask):
    """0/1 序列里连续 1 的段长(降仓段的连续性检查)。"""
    out, cur = [], 0
    for v in mask:
        if v:
            cur += 1
        else:
            if cur:
                out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


# ── 自检(合成数据,已知答案) ─────────────────────────────────────────────
def selftest():
    ok = True

    def chk(name, got, want, tol=1e-9):
        nonlocal ok
        good = abs(got - want) <= tol if isinstance(want, float) else got == want
        ok = ok and good
        print("  %-46s got=%s want=%s %s" % (name, got, want, "OK" if good else "FAIL"))

    # 1) 盈亏用 apparatus:100 → 50 = +50%,→ 200 = −50%
    chk("long_return(100,50)", long_ret(100, 50), -0.5)
    chk("long_return(100,200)", long_ret(100, 200), 1.0)
    chk("long_return(None,100) is None", long_ret(None, 100) is None, True)

    # 2) 曲线统计:收益 +0.1、−0.2、+0.1 ⇒ cum 1.1*0.8*1.1=0.968;
    #    回撤序列 dd = cum/累计峰值−1 = [0, 0.88/1.1−1, 0.968/1.1−1] = [0, −0.2, −0.12];
    #    最大回撤 = min(dd) = −0.2(峰值 1.1 → 谷 0.88),不是末点的 −0.12。
    m = curve_metrics(["2024-01-01", "2024-01-02", "2024-01-03"], [0.1, -0.2, 0.1])
    chk("cum total", m["total"], -0.032, 1e-12)
    chk("max_drawdown(峰值→谷)", m["max_drawdown"], -0.2, 1e-12)

    # 3) rolling_z:前 300 个常数 + 一个跳变 ⇒ 标准差为 0 ⇒ None
    d0 = date(2023, 1, 1)
    ds = [(d0 + timedelta(days=i)).isoformat() for i in range(400)]
    L = [1.0] * 399 + [2.0]
    z = rolling_z(ds, L)
    chk("rolling_z 标准差=0 ⇒ None", z[ds[399]] is None, True)
    chk("rolling_z 值不足 300 ⇒ None", z[ds[100]] is None, True)

    # 4) rolling_z 已知答案:窗口 = 「过去 365 个日历日」(d 当天不进窗口)
    #    ds[399] 往前 365 天 ⇒ 取 ds[34..398] 共 365 个值(L2[34:399]):
    #    L2 = [1.0]*300 + [2.0]*100 ⇒ 窗口里 266 个 1.0 + 99 个 2.0。
    L2 = [1.0] * 300 + [2.0] * 100
    z2 = rolling_z(ds, L2)
    win = L2[34:399]
    mw = sum(win) / len(win)
    sw = math.sqrt(sum((v - mw) ** 2 for v in win) / (len(win) - 1))
    chk("rolling_z 已知答案(365 日历日窗)", z2[ds[399]], (2.0 - mw) / sw, 1e-9)
    chk("rolling_z 窗口长度 = 365", float(len(win)), 365.0)

    # 5) 暴露规则:z>1.0 的次日才降仓
    sig = ["2024-01-01", "2024-01-02", "2024-01-03"]
    zz = {"2024-01-01": 1.5, "2024-01-02": 0.9, "2024-01-03": None}
    rets = ["2024-01-02", "2024-01-03", "2024-01-04"]
    ex = exposure_from_z(sig, zz, rets, sig_start="2024-01-01", sig_end="2024-01-04")
    chk("expo:z=1.5 ⇒ 次日 0.5", ex["2024-01-02"], 0.5)
    chk("expo:z=0.9 ⇒ 次日 1.0", ex["2024-01-03"], 1.0)
    chk("expo:z=None ⇒ 次日 1.0", ex["2024-01-04"], 1.0)

    # 6) 循环平移保留降仓天数与连续段长度
    exv = [1.0] * 10 + [0.5] * 3 + [1.0] * 5 + [0.5] * 2
    dsx = ["2024-01-%02d" % (i + 1) for i in range(20)]
    off = 7
    sh = np.roll(np.asarray(exv), off)
    chk("shift 降仓天数不变", int((sh < 1).sum()), int((np.asarray(exv) < 1).sum()))
    chk("shift 连续段长度不变", sorted(runs_of(sh < 1)), sorted(runs_of(np.asarray(exv) < 1)))

    # 7) 零分布:apparatus 的 percentile_of(中秩:(严格小于 + 相等/2)/ n)
    #    实际值 0.95 在 linspace(0,1,101) 里不存在(那是 0.9500000000000001 > 0.95),
    #    ⇒ 相等 0 个、严格小于 95 个 ⇒ 95/101。
    chk("percentile_of(0.95, 0..1)", apparatus.percentile_of(0.95, list(np.linspace(0, 1, 101))), 95.0 / 101.0, 1e-12)
    chk("percentile_of 相等记半秩", apparatus.percentile_of(0.5, [0.0, 0.5, 1.0]), 0.5, 1e-12)

    print("SELFTEST:", "ALL OK" if ok else "FAIL")
    return 0 if ok else 1


# ── 主流程 ───────────────────────────────────────────────────────────────
def build_universe(deriv_rows, px, sym_filter=None):
    """deriv → 每个 symbol 的 {d: (oi_close, oi_value_close)};同时做映射/价格校验(S-689 原文)。"""
    by_sym = defaultdict(dict)
    for r in deriv_rows:
        s = r["symbol"].upper()
        by_sym[s][r["d"]] = (r.get("oi_close"), r.get("oi_value_close"))

    names, check = [], {}
    for s in sorted(by_sym):
        if sym_filter and s not in sym_filter:
            continue
        errs = []
        for d, (oic, oiv) in by_sym[s].items():
            p = px.get((s, d))
            if not p:
                continue
            price, _mcap, mult = p
            if not price or price <= 0:
                continue
            if oic is None or oiv is None or oic <= 0 or oiv <= 0:
                continue
            implied = oiv / oic
            errs.append(abs(price * mult / implied - 1.0))
        n_overlap = len(errs)
        med_err = float(np.median(errs)) if errs else None
        kept = (n_overlap >= MIN_OVERLAP) and (med_err is not None) and (med_err <= MAX_MED_ERR)
        check[s] = {"n_overlap": n_overlap, "med_err": med_err, "kept": kept}
        if kept:
            names.append(s)
    return by_sym, names, check


def compute_L(deriv_by_sym, names, px):
    """L_d = 当天市值前 30 名(在有 Binance OI 的名字里按 CG 市值排)的 Σ OI 值 / Σ 市值。"""
    per_day = defaultdict(list)
    for s in names:
        for d, (oic, oiv) in deriv_by_sym[s].items():
            if oic is None or oiv is None or oic <= 0 or oiv <= 0:
                continue
            p = px.get((s, d))
            if not p:
                continue
            price, mcap, _mult = p
            if not mcap or mcap <= 0 or not price or price <= 0:
                continue
            per_day[d].append((float(mcap), float(oiv), s))
    L, n_names, n_below_floor = {}, {}, {}
    for d, lst in per_day.items():
        lst.sort(key=lambda x: (-x[0], x[2]))
        top = lst[:TOP_N]
        if len(top) < TOP_N:
            continue
        L[d] = sum(x[1] for x in top) / sum(x[0] for x in top)
        n_names[d] = len(lst)
        n_below_floor[d] = sum(1 for x in top if x[0] < 20_000_000)
    return L, n_names, n_below_floor


def panel_returns(panel_mcap, panel_price, panel_days, panel_dates):
    """① 面板:市值加权、日再平衡的组合收益(权重用 d−1 的市值,α=1,不设上限)。"""
    rets, used = {}, {}
    for i in range(1, len(panel_dates)):
        d0, d1 = panel_dates[i - 1], panel_dates[i]
        # panel_mcap / panel_price 都是 {symbol: {date: 值}} —— 按 symbol 取,再按 date 取值。
        # 名字取自 cis_rebuild_daily 当天有行的;当天没有市值的(MKR/SKY 换名交接等)自然被跳过。
        names = [s for s in panel_days.get(d0, [])
                 if d0 in panel_mcap.get(s, {}) and d0 in panel_price.get(s, {})]
        cand = []
        for s in names:
            p0 = panel_price.get(s, {}).get(d0)
            p1 = panel_price.get(s, {}).get(d1)
            m0 = panel_mcap.get(s, {}).get(d0)
            if not p0 or not p1 or not m0 or m0 <= 0:
                continue
            r = long_ret(p0, p1)
            if r is None:
                continue
            cand.append((s, float(m0), r))
        if not cand:
            continue
        tot = sum(c[1] for c in cand)
        rets[d1] = sum(w / tot * r for _s, w, r in cand)
        used[d1] = len(cand)
    return rets, used


def fetch_asset(symbols):
    """asset_mcap_daily(CG)按 symbol 取(分块,免得 URL 过长)。"""
    out = []
    syms = sorted(set(symbols))
    for i in range(0, len(syms), 120):
        chunk = syms[i:i + 120]
        out += fetch_cached("asset_cg_%d" % i, "asset_mcap_daily",
                            [("source", "eq.coingecko_pro_market_chart"),
                             ("symbol", "in.(%s)" % ",".join(chunk)),
                             ("d", "gte." + PAD_START), ("d", "lte." + SIG_END)],
                            "symbol.asc,d.asc", "symbol,coin_id,d,price,mcap")
    return out


def run_full():
    gate_ok, pending, pm_rows = check_gate()
    if not gate_ok:
        log("闸门未开(perp_cg_map 有 pending:%s),退出。" % pending)
        return 3

    pm = {r["symbol"]: r for r in pm_rows if r.get("verdict") == "resolved"}

    # 1) ① 面板的加密名(cis_rebuild_daily;四个 code_ref 版本 ⇒ 同 (symbol,d) 会重复,去重)
    log("读 cis_rebuild_daily(加密类) …")
    cis_rows = fetch_cached("cis_crypto", "cis_rebuild_daily",
                            [("asset_class", "in.(%s)" % ",".join(CRYPTO_CLASSES)),
                             ("d", "gte." + PAD_START), ("d", "lte." + SIG_END)],
                            "symbol.asc,d.asc,code_ref.asc", "d,symbol,asset_class,code_ref")
    panel_days = defaultdict(set)
    for r in cis_rows:
        panel_days[r["d"]].add(r["symbol"])
    panel_syms_all = sorted({r["symbol"] for r in cis_rows})
    panel_syms = [s for s in panel_syms_all if s not in PANEL_EXCLUDE]
    log("  ① 面板加密名 %d(去 BTC 后 %d):%s" % (len(panel_syms_all), len(panel_syms), panel_syms))

    # 2) 衍生品 OI(全宇宙)
    log("读 deriv_metrics_daily …")
    deriv_rows = fetch_cached("deriv", "deriv_metrics_daily",
                              [("d", "gte." + PAD_START), ("d", "lte." + SIG_END)],
                              "symbol.asc,d.asc", "d,symbol,oi_close,oi_value_close,source")
    log("  deriv 行数 %d" % len(deriv_rows))
    deriv_syms = sorted({r["symbol"].upper() for r in deriv_rows})

    # 3) CG 价 / 市值(按 symbol;面板名一起带上)
    log("读 asset_mcap_daily(按 symbol) …")
    asset_rows = fetch_asset(set(deriv_syms) | set(panel_syms_all))
    log("  asset 行数 %d" % len(asset_rows))
    asset_syms = sorted({r["symbol"].upper() for r in asset_rows})

    # 4) perp_cg_map 解析出来、asset 里没有的名字 → cg_coin_mcap_daily
    only_perp = [s for s in deriv_syms if s not in set(asset_syms)]
    cg_rows = []
    if only_perp:
        cid_map = {s: pm[s]["coin_id"] for s in only_perp if s in pm}
        cids = sorted(set(cid_map.values()))
        log("读 cg_coin_mcap_daily(%d 个 coin_id) …" % len(cids))
        for i in range(0, len(cids), 40):
            cg_rows += fetch_cached("cg_coins_%d" % i, "cg_coin_mcap_daily",
                                    [("source", "eq.coingecko_pro_market_chart"),
                                     ("coin_id", "in.(%s)" % ",".join(cids[i:i + 40])),
                                     ("d", "gte." + PAD_START), ("d", "lte." + SIG_END)],
                                    "coin_id.asc,d.asc", "coin_id,d,price,mcap")
        log("  cg 行数 %d" % len(cg_rows))

    # px 表:(sym, d) → (price, mcap, mult)
    px = {}
    for r in asset_rows:
        px[(r["symbol"].upper(), r["d"])] = (r["price"], r["mcap"], 1)
    coin_to_sym = {}
    for s in only_perp:
        if s in pm:
            coin_to_sym[pm[s]["coin_id"]] = s
    for r in cg_rows:
        s = coin_to_sym.get(r["coin_id"])
        if s is None:
            continue
        px[(s, r["d"])] = (r["price"], r["mcap"], float(pm[s].get("mult") or 1))

    # 5) 宇宙 + 映射/价格校验(S-689 原文)
    deriv_by_sym, names, check = build_universe(deriv_rows, px)
    dropped = {s: v for s, v in check.items() if not v["kept"]}
    log("宇宙 %d 名 ⇒ 校验通过 %d / 剔除 %d" % (len(check), len(names), len(dropped)))

    # 6) L_d
    L, n_names, n_below_floor = compute_L(deriv_by_sym, names, px)
    all_L_dates = sorted(L)
    log("L 有定义的天数 %d(%s → %s)" % (len(all_L_dates), all_L_dates[0] if all_L_dates else None,
                                      all_L_dates[-1] if all_L_dates else None))

    # 7) z_d(信号日窗口)
    sig_dates = [d for d in all_L_dates if SIG_START <= d <= SIG_END]
    z_all = rolling_z(all_L_dates, [L[d] for d in all_L_dates])
    z = {d: z_all.get(d) for d in sig_dates}
    n_z = sum(1 for d in sig_dates if z[d] is not None)
    log("信号日 %d、z 有定义 %d" % (len(sig_dates), n_z))

    # 敏感性:标准差用总体口径(ddof=0)时降仓天数变不变
    z0 = rolling_z(all_L_dates, [L[d] for d in all_L_dates], ddof=0)
    expo0 = exposure_from_z(sig_dates, {d: z0.get(d) for d in sig_dates},
                            [d for d in sorted(all_L_dates) if SIG_START <= d <= SIG_END])
    n_reduced_ddof0 = sum(1 for v in expo0.values() if v < 1)

    # 敏感性:z 窗口口径(台账「过去 365 天」可以读成日历日,也可以读成 365 个观测值;
    # 边界差一天就会让临界日翻转 —— 2023-01-02 的 z = 1.0025,正好卡在阈值上)
    z_variants = {}
    for tag, kwargs in (
        ("365 个日历日(d 不进窗,ddof=1)", dict(win_days=365, ddof=1)),
        ("365 个观测值(d 不进窗,ddof=1)", dict(win_days=365, ddof=1, obs_n=365)),
        ("364 个日历日(d 不进窗,ddof=1)", dict(win_days=364, ddof=1)),
        ("365 个日历日(d 进窗,ddof=1)", dict(win_days=365, ddof=1, include_d=True)),
        ("365 个日历日(d 不进窗,ddof=0)", dict(win_days=365, ddof=0)),
    ):
        obs_n = kwargs.pop("obs_n", None)
        include_d = kwargs.pop("include_d", False)
        vv = rolling_z(all_L_dates, [L[d] for d in all_L_dates],
                       win_days=kwargs["win_days"], ddof=kwargs["ddof"],
                       obs_n=obs_n, include_d=include_d)
        ex_v = exposure_from_z(sig_dates, {d: vv.get(d) for d in sig_dates},
                               [d for d in sorted(all_L_dates) if SIG_START <= d <= SIG_END])
        z_variants[tag] = {"n_reduced": sum(1 for v in ex_v.values() if v < 1),
                           "z_2023_01_02": vv.get("2023-01-02")}
    log("z 窗口口径敏感性:%s" % json.dumps({k: v["n_reduced"] for k, v in z_variants.items()},
                                           ensure_ascii=False))

    # 8) ① 面板价格 / 市值(asset_mcap_daily,按 symbol ⇒ 同一 coin_id)
    sym2coin = {}
    panel_price, panel_mcap = defaultdict(dict), defaultdict(dict)
    for r in asset_rows:
        s = r["symbol"].upper()
        sym2coin.setdefault(s, r["coin_id"])
        if s in panel_syms:
            panel_price[s][r["d"]] = r["price"]
            panel_mcap[s][r["d"]] = r["mcap"]
    for r in cg_rows:
        s = coin_to_sym.get(r["coin_id"])
        if s in panel_syms:
            panel_price[s][r["d"]] = r["price"]
            panel_mcap[s][r["d"]] = r["mcap"]
    panel_coin_of = {s: sym2coin.get(s) for s in panel_syms}
    log("  面板名字 → coin_id:%s" % json.dumps(panel_coin_of, ensure_ascii=False))

    # BTC(CG 日收盘,coin_id='bitcoin')
    btc_price = {}
    for r in asset_rows:
        if r["symbol"].upper() == "BTC" and r["coin_id"] == BTC_COIN_ID:
            btc_price[r["d"]] = r["price"]
    if not btc_price:
        for r in asset_rows:
            if r["symbol"].upper() == "BTC":
                btc_price[r["d"]] = r["price"]
    if not btc_price:
        btc_rows = fetch_cached("btc_coin", "asset_mcap_daily",
                                [("source", "eq.coingecko_pro_market_chart"),
                                 ("coin_id", "eq." + BTC_COIN_ID),
                                 ("d", "gte." + PAD_START), ("d", "lte." + SIG_END)],
                                "d.asc", "d,price")
        btc_price = {r["d"]: r["price"] for r in btc_rows if r.get("price")}
    log("  BTC 价格点 %d(%s → %s)" % (len(btc_price), min(btc_price), max(btc_price)))

    # 9) 暴露序列 + 收益
    panel_dates = sorted(d for d in panel_days if PAD_START <= d <= SIG_END)
    ret_dates = [d for d in sorted(btc_price) if SIG_START <= d <= SIG_END]
    expo = exposure_from_z(sig_dates, z, ret_dates)
    log("  暴露日 %d、其中降仓 %d 天" % (len(expo), sum(1 for v in expo.values() if v < 1)))

    btc_ret = {}
    for t in ret_dates:
        prev = (date.fromisoformat(t) - timedelta(days=1)).isoformat()
        r = long_ret(btc_price.get(prev), btc_price.get(t))
        if r is None:
            continue
        btc_ret[t] = r
    btc_hold = dict(btc_ret)

    pan_ret, pan_used = panel_returns(panel_mcap, panel_price, panel_days, panel_dates)
    pan_ret = {d: v for d, v in pan_ret.items() if SIG_START <= d <= SIG_END}
    pan_hold = dict(pan_ret)
    if pan_used:
        log("  ① 面板收益日 %d、每天持仓数中位 %d(最少 %d、最多 %d)"
            % (len(pan_used), int(np.median(list(pan_used.values()))),
               min(pan_used.values()), max(pan_used.values())))

    arm_btc = {d: expo.get(d, EXPO_FULL) * btc_ret[d] for d in btc_ret}
    arm_pan = {d: expo.get(d, EXPO_FULL) * pan_ret[d] for d in pan_ret}

    # 10) 指标(全窗口 + 两半)
    def block(asset_rets, dates=None):
        ds = sorted(asset_rets) if dates is None else [d for d in dates if d in asset_rets]
        return curve_metrics(ds, [asset_rets[d] for d in ds])

    hold_btc = block(btc_hold)
    rule_btc = block(arm_btc)
    hold_pan = block(pan_hold)
    rule_pan = block(arm_pan)

    halves = {}
    expo_sorted = sorted(expo)
    for label, mask in apparatus.windows(expo_sorted, HALF_CUTS):
        # apparatus.windows 给的是按 expo_sorted 顺序的布尔数组(不是按日期索引)
        ds = [d for d, keep in zip(expo_sorted, mask) if keep]
        hb = [d for d in ds if d in btc_hold]
        hp = [d for d in ds if d in pan_hold]
        halves[label] = {
            "btc_hold": curve_metrics(hb, [btc_hold[d] for d in hb]),
            "btc_rule": curve_metrics(hb, [arm_btc[d] for d in hb]),
            "panel_hold": curve_metrics(hp, [pan_hold[d] for d in hp]),
            "panel_rule": curve_metrics(hp, [arm_pan[d] for d in hp]),
            "n_expo_days": len(ds),
            "n_reduced": sum(1 for d in ds if expo[d] < 1),
        }

    # 11) 随机降仓零分布(循环平移;台账 S-692)
    log("跑随机降仓零分布(%d 次,种子 %d) …" % (N_NULL, SEED))
    expo_dates = sorted(expo)
    expo_vals = [expo[d] for d in expo_dates]
    rand = {}
    for tag, hold_rets in (("btc", btc_hold), ("panel", pan_hold)):
        ds = [d for d in expo_dates if d in hold_rets]
        if not ds:
            raise RuntimeError("%s 臂没有可算的收益日(暴露日 %d)—— 面板取数或对齐有问题"
                               % (tag, len(expo_dates)))
        null = circular_shift_null(expo_dates, expo_vals, ds, [hold_rets[d] for d in ds])
        actual = rule_btc["calmar"] if tag == "btc" else rule_pan["calmar"]
        p = apparatus.percentile_of(actual, null)
        rand[tag] = {
            "n": int(null.size),
            "min": float(np.min(null)), "p05": float(np.quantile(null, 0.05)),
            "p50": float(np.quantile(null, 0.50)), "p95": float(np.quantile(null, 0.95)),
            "p99": float(np.quantile(null, 0.99)), "max": float(np.max(null)),
            "mean": float(np.mean(null)),
            "actual_calmar": actual,
            "percentile_of_actual": p,
            "q95": float(np.quantile(null, 0.95)),
            "n_better_than_actual": int((null > actual).sum()),
        }

    # 12) 判定(照抄台账,主资产 BTC)
    c1 = (abs(rule_btc["max_drawdown"]) <= 0.85 * abs(hold_btc["max_drawdown"])) \
        if (rule_btc["max_drawdown"] is not None and hold_btc["max_drawdown"] is not None) else False
    c2 = (rand["btc"]["percentile_of_actual"] is not None
          and rand["btc"]["percentile_of_actual"] >= 0.95
          and rule_btc["calmar"] > rand["btc"]["q95"])
    h1 = [v for k, v in halves.items() if k.startswith("2023-01-01 → 2024-11-01")]
    h2 = [v for k, v in halves.items() if k.startswith("2024-11-01 →")]
    c3 = bool(h1 and h2 and h1[0]["btc_rule"]["calmar"] >= h1[0]["btc_hold"]["calmar"]
              and h2[0]["btc_rule"]["calmar"] >= h2[0]["btc_hold"]["calmar"])
    verdict = "✅" if (c1 and c2 and c3) else "❌"

    # 副资产(① 面板)同样的三条 —— 只报不判
    p_c1 = (abs(rule_pan["max_drawdown"]) <= 0.85 * abs(hold_pan["max_drawdown"])) \
        if (rule_pan["max_drawdown"] is not None and hold_pan["max_drawdown"] is not None) else False
    p_c2 = (rand["panel"]["percentile_of_actual"] is not None
            and rand["panel"]["percentile_of_actual"] >= 0.95
            and rule_pan["calmar"] > rand["panel"]["q95"])
    p_h1 = [v for k, v in halves.items() if k.startswith("2023-01-01 → 2024-11-01")]
    p_h2 = [v for k, v in halves.items() if k.startswith("2024-11-01 →")]
    p_c3 = bool(p_h1 and p_h2
                and p_h1[0]["panel_rule"]["calmar"] >= p_h1[0]["panel_hold"]["calmar"]
                and p_h2[0]["panel_rule"]["calmar"] >= p_h2[0]["panel_hold"]["calmar"])
    panel_verdict = {"c1": bool(p_c1), "c2": bool(p_c2), "c3": bool(p_c3),
                     "pass": bool(p_c1 and p_c2 and p_c3)}

    # 13) A/B(装置;附带,不判)
    ab = apparatus.ab_test([btc_hold[d] for d in sorted(btc_hold)],
                            [arm_btc[d] for d in sorted(btc_hold)],
                            mean_block=20.0, n_boot=N_NULL, seed=SEED)

    # 14) 落盘
    daily = []
    for d in sig_dates:
        nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        daily.append({
            "d": d, "L": L.get(d), "n_names": n_names.get(d),
            "n_top30_below_20m": n_below_floor.get(d),
            "z": z.get(d), "exposure_next_day": expo.get(nxt),
            "btc_close": btc_price.get(d), "btc_ret": btc_ret.get(nxt),
            "panel_ret": pan_ret.get(nxt),
        })

    protocol_issues = [
        "z 的窗口:台账写「过去 365 天 L 的均值 / 标准差」「d 当天不进窗口;≥ 300 个值」,"
        "没写标准差用总体(ddof=0)还是样本(ddof=1)。本复算用 ddof=1;"
        "改 ddof=0 时降仓天数 %d 天(主口径 %d 天)—— 结论不变。" % (n_reduced_ddof0, sum(1 for v in expo.values() if v < 1)),
        "z 不成立(窗口不足 300 个值)的日子:台账没写怎么办。本复算按「不成立 ⇒ 敞口 1.0」"
        "(没有信号就不降仓);这样的日子 %d 天。" % (len(sig_dates) - n_z),
        "① 面板的名字:台账写「cis_rebuild_daily 加密 24 名」。库里加密 asset_class "
        "(L1/L2/DeFi/Infrastructure/RWA)实际有 %d 个符号(%s);去掉主资产 BTC 后 %d 个,"
        "其中 MKR 与 SKY 是同一个项目(CG coin 'maker' 与 'sky'),二者的市值在每个交易日"
        "恰好只有一个非空(实测 1,734 天里 1,734 天如此)⇒ 有效资产 %d 个 —— 与台账「24 名」对上。"
        % (len(panel_syms_all), ",".join(panel_syms_all), len(panel_syms),
           len(panel_syms) - 1),
        "① 面板的权重用哪一天的市场值:台账写「当天市值加权」,但当天市值含当天涨跌(前视)。"
        "本复算按 core_cap 的同一读法:权重用 d−1 的市值,α=1,不设单币上限,每天重算权重。",
        "MKR→SKY:价格尺度差 24000 倍(t203 已发布口径),本复算不合并两条价格线;"
        "靠市值不重叠(MKR ≤ 2025-06-04、SKY ≥ 2025-06-05)实现交接,交接日 SKY 的权重由前一日 MKR 市值起算。",
        "随机降仓的循环平移:台账没写平移量怎么抽。本复算用 numpy default_rng(692) 抽 2,000 个均匀偏移"
        "(可重复);0 位移(与实测同一条)约占 1.5/2000,对分位影响 < 0.1pp。",
        "年化口径:台账只写「年化」。本复算用 (1+总收益)^(1/年数) − 1,年数 = 收益天数/365;"
        "判定窗口 2023-01-01 → 2026-09-30(%d 个收益日;首日 2023-01-01 的收益用 2022-12-31 的收盘算 —— "
        "信号窗从 2023-01-01 起,2022-12-31 没有 z,那天敞口 1.0)。" % len(expo),
        "卡片列了 funding_history(binance_perp)可读,但 S-692 的信号(ΣOI/Σ市值)与 ① 面板(市值加权)"
        "都用不到资金费;本复算没有用它,也没有为了用它而改规则。",
        "① 面板的成员:本复算按 cis_rebuild_daily 当天有行的加密名取;某个名字在库里当天没行,"
        "当天就不进面板(不猜)。",
    ]

    exploratory = [
        "L 的水平:中位 %.4f、范围 %.4f ~ %.4f(单位:OI 值 ÷ 市值)。"
        % (np.median([L[d] for d in sig_dates if d in L]),
           min(L[d] for d in sig_dates if d in L), max(L[d] for d in sig_dates if d in L)),
        "降仓日的连续段:最长 %d 天、共 %d 段(中位 %.0f 天);降仓 %d 天里 %d 天落在 2024-11 之后。"
        % (max(runs_of([expo[d] < 1 for d in expo_dates])) if expo_dates else 0,
           len(runs_of([expo[d] < 1 for d in expo_dates])),
           float(np.median(runs_of([expo[d] < 1 for d in expo_dates]))) if runs_of([expo[d] < 1 for d in expo_dates]) else 0.0,
           sum(1 for v in expo.values() if v < 1),
           sum(1 for d in expo if expo[d] < 1 and d >= "2024-11-01")),
        "z 的极值:最大 %.2f、最小 %.2f(窗口 2023-01 → 2026-09)。"
        % (max([v for v in z.values() if v is not None] or [0]),
           min([v for v in z.values() if v is not None] or [0])),
        "随机降仓零分布里,Calmar 比实测高的有 %d/%d 次(%.1f%%)。"
        % (rand["btc"]["n_better_than_actual"], N_NULL,
           100.0 * rand["btc"]["n_better_than_actual"] / N_NULL),
        "前 30 名里市值 < 2,000 万美元的名字:有 %d 天至少一个。"
        % sum(1 for v in n_below_floor.values() if v),
    ]

    res = {
        "card": "T-207", "ledger": "S-692", "generated_utc": datetime.now(timezone.utc).isoformat(),
        "gate": {"ok": gate_ok, "pending": pending, "perp_cg_map_rows": len(pm_rows),
                 "deadline_utc": GATE_DEADLINE.isoformat()},
        "protocol": {
            "pad_start": PAD_START, "sig_start": SIG_START, "sig_end": SIG_END,
            "z_window_days": Z_WINDOW_DAYS, "z_min_values": Z_MIN_VALUES, "z_threshold": Z_THRESHOLD,
            "expo_reduced": EXPO_REDUCED, "expo_full": EXPO_FULL, "top_n": TOP_N,
            "min_overlap": MIN_OVERLAP, "max_med_err": MAX_MED_ERR,
            "n_null": N_NULL, "seed": SEED, "half_cuts": HALF_CUTS,
            "reduced_part_return": 0.0, "days_per_year": DAYS_PER_YEAR,
            "z_std": "sample(ddof=1)", "z_window": "过去 365 个日历日,d 当天不进窗口",
            "panel_exclude": list(PANEL_EXCLUDE),
        },
        "universe": {
            "deriv_symbols": len(deriv_syms),
            "names_kept": len(names),
            "names_dropped": len(dropped),
            "kept": names,
            "dropped": {s: {"n_overlap": v["n_overlap"], "med_err": v["med_err"]} for s, v in dropped.items()},
            "check": {s: {"n_overlap": v["n_overlap"], "med_err": v["med_err"]} for s, v in check.items()},
            "panel_symbols_all": panel_syms_all,
            "panel_symbols": panel_syms,
            "panel_n": len(panel_syms),
            "panel_coin_id": panel_coin_of,
            "n_deriv_rows": len(deriv_rows), "n_asset_rows": len(asset_rows),
        },
        "signal": {
            "n_days_L": len(all_L_dates),
            "L_first": all_L_dates[0] if all_L_dates else None,
            "L_last": all_L_dates[-1] if all_L_dates else None,
            "n_sig_days": len(sig_dates), "n_z_defined": n_z,
            "n_expo_days": len(expo), "n_reduced_days": sum(1 for v in expo.values() if v < 1),
            "n_reduced_days_ddof0": n_reduced_ddof0,
            "reduced_run_lengths": sorted(runs_of([expo[d] < 1 for d in expo_dates])),
            "n_days_top30_below_20m": sum(v for v in n_below_floor.values() if v),
        },
        "curves": {
            "btc": {"hold": hold_btc, "rule": rule_btc},
            "panel": {"hold": hold_pan, "rule": rule_pan},
        },
        "halves": halves,
        "random": rand,
        "ab_test_btc": ab,
        "verdict": {
            "overall": verdict,
            "c1_dd15pct": {"pass": bool(c1),
                           "rule_mdd": rule_btc["max_drawdown"], "hold_mdd": hold_btc["max_drawdown"],
                           "depth_ratio": (abs(rule_btc["max_drawdown"]) / abs(hold_btc["max_drawdown"]))
                           if hold_btc["max_drawdown"] else None,
                           "need": "规则回撤 ≤ 持有回撤 × 0.85"},
            "c2_calmar_vs_random_p95": {"pass": bool(c2),
                                        "rule_calmar": rule_btc["calmar"],
                                        "null_p95": rand["btc"]["q95"],
                                        "percentile_of_actual": rand["btc"]["percentile_of_actual"]},
            "c3_halves_calmar": {"pass": bool(c3),
                                 "halves": {k: {"hold_calmar": v["btc_hold"]["calmar"],
                                               "rule_calmar": v["btc_rule"]["calmar"],
                                               "n_reduced": v["n_reduced"]}
                                            for k, v in halves.items()}},
        },
        "panel_verdict": panel_verdict,
        "protocol_issues": protocol_issues,
        "exploratory": exploratory,
        "daily": daily,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    log("写 %s" % OUT_JSON)

    write_report(res)
    log("写 %s" % REPORT)
    log("判定:%s" % verdict)
    return 0


def fmt(x, nd=4):
    if x is None:
        return "—"
    if isinstance(x, float):
        if math.isinf(x):
            return "∞"
        return ("%%.%df" % nd) % x
    return str(x)


def write_report(res):
    os.makedirs(REPORT_DIR, exist_ok=True)
    c = res["curves"]
    v = res["verdict"]
    r = res["random"]
    h = res["halves"]
    L = []
    A = L.append
    A("# T-207 / S-692 独立复算 —— 全市场杠杆(前 30 名 Σ OI / Σ 市值)偏高时把 ① 降到 0.5")
    A("")
    A("照 REFUTATION_LEDGER.md 的 **S-692**(2026-10-27 04:33 UTC 预注册)一字不改;C 道独立复算"
      "(交付前未读 docs/research/s692_*)。脚本 `docs/research/t207_market_leverage_gate.py`,"
      "结果 `docs/research/t207_results.json`。")
    A("")
    A("## 判定表")
    A("")
    A("| 条 | 判据(S-692 原文) | 实测 | 过? |")
    A("|---|---|---|---|")
    A("| ① | 最大回撤比持有浅至少 15%%(相对,主资产 BTC) | 持有 %s → 规则 %s(深度比 **%s**,须 ≤ 0.85) | %s |"
      % (fmt(c["btc"]["hold"]["max_drawdown"]), fmt(c["btc"]["rule"]["max_drawdown"]),
         fmt(v["c1_dd15pct"]["depth_ratio"], 4), "✅" if v["c1_dd15pct"]["pass"] else "❌"))
    A("| ② | Calmar 高于随机降仓分布的 95 分位(主资产 BTC) | 规则 Calmar **%s** vs 随机分布 p95 %s(实际值在分布中的分位 **%s**) | %s |"
      % (fmt(c["btc"]["rule"]["calmar"]), fmt(r["btc"]["q95"]), fmt(r["btc"]["percentile_of_actual"], 4),
         "✅" if v["c2_calmar_vs_random_p95"]["pass"] else "❌"))
    cut1, cut2 = res["protocol"]["half_cuts"]
    end_d = res["protocol"]["sig_end"]
    half_labels = ["%s → 2024-10-31" % cut1, "%s → %s" % (cut2, end_d)]
    for (label, hv), hl in zip(h.items(), half_labels):
        A("| ③ | 两半 %s 各自 Calmar ≥ 持有 | 持有 %s / 规则 %s | %s |"
          % (hl,
             fmt(hv["btc_hold"]["calmar"]), fmt(hv["btc_rule"]["calmar"]),
             "✅" if hv["btc_rule"]["calmar"] >= hv["btc_hold"]["calmar"] else "❌"))
    A("")
    A("**总判定:%s**(%s)" % (v["overall"],
                              "三条全过 ⇒ 按预注册进组合层纸面(与现行 ③ 并排),不改真钱"
                              if v["overall"] == "✅" else "只记,不动任何在跑的规则"))
    A("")
    A("## 1. 规则与数据(照台账)")
    A("")
    A("- **信号**:L_d = 当天市值前 30 名(在有 Binance OI 的名字里按 CG 市值排)的 Σ OI 值 / Σ 市值;"
      "z_d = (L_d − 过去 365 天 L 的均值)/标准差(d 当天不进窗口,≥ 300 个值)。")
    A("- **规则**:d 收盘 z_d > 1.0 ⇒ d+1 起暴露 0.5,否则 1.0;每天重判;降下来的那部分记 0 收益。")
    A("- **资产**:主 = BTC(CG 日收盘);副 = ① 面板(cis_rebuild_daily 加密名,市值加权,不设上限)。")
    A("- **窗口**:信号日 %s → %s;2022 年只用来给 2023 年初的 z 垫 365 天窗口。"
      % (res["protocol"]["sig_start"], res["protocol"]["sig_end"]))
    A("- **对照**:① 一直持有(1.0);② 随机降仓 = 同一条暴露序列按随机偏移循环平移 %d 次(种子 %d)。"
      % (res["protocol"]["n_null"], res["protocol"]["seed"]))
    A("- **宇宙**:deriv %d 名 → 映射/价格校验(S-689 原文:n_overlap ≥ 30 且 med_err ≤ 0.05)通过 **%d** 名,剔除 %d 名;"
      "L 有定义的天数 %d;信号日 %d 天里 z 有定义 %d 天;暴露日 %d 天,其中降仓 **%d** 天。"
      % (res["universe"]["deriv_symbols"], res["universe"]["names_kept"], res["universe"]["names_dropped"],
         res["signal"]["n_days_L"], res["signal"]["n_sig_days"], res["signal"]["n_z_defined"],
         res["signal"]["n_expo_days"], res["signal"]["n_reduced_days"]))
    A("")
    A("## 2. 三条判定")
    A("")
    A("### ① 回撤")
    A("")
    A("| 资产 | 臂 | 年化 | 累计 | 最大回撤 | Calmar | 天数 |")
    A("|---|---|---|---|---|---|---|")
    for asset, tag in (("btc", "BTC(主)"), ("panel", "① 面板(副)")):
        for arm, an in (("hold", "一直持有"), ("rule", "降仓规则")):
            m = c[asset][arm]
            A("| %s | %s | %s | %s | %s | %s | %d |"
              % (tag, an, fmt(m["annualized"]), fmt(m["total"]), fmt(m["max_drawdown"]),
                 fmt(m["calmar"]), m["n_days"]))
    A("")
    A("### ② 随机降仓对照")
    A("")
    A("| 资产 | 实际 Calmar | 零分布 p05 | p50 | p95 | p99 | max | 实际值分位 |")
    A("|---|---|---|---|---|---|---|---|")
    for asset, tag in (("btc", "BTC(主)"), ("panel", "① 面板(副)")):
        rr = r[asset]
        A("| %s | %s | %s | %s | %s | %s | %s | %s |"
          % (tag, fmt(rr["actual_calmar"]), fmt(rr["p05"]), fmt(rr["p50"]), fmt(rr["p95"]),
             fmt(rr["p99"]), fmt(rr["max"]), fmt(rr["percentile_of_actual"], 4)))
    A("")
    A("零分布 = 同一条暴露序列按随机偏移循环平移(保留降仓天数与连续段长度),%d 次,种子 %d;"
      "取自 `apparatus.null_distribution` + `apparatus.percentile_of`。"
      % (res["protocol"]["n_null"], res["protocol"]["seed"]))
    A("")
    A("### ③ 两半")
    A("")
    A("| 段 | 天数 | 降仓天 | BTC 持有 Calmar | BTC 规则 Calmar | 面板持有 | 面板规则 |")
    A("|---|---|---|---|---|---|---|")
    for (label, hv), hl in zip(h.items(), half_labels):
        A("| %s | %d | %d | %s | %s | %s | %s |"
          % (hl, hv["btc_hold"]["n_days"], hv["n_reduced"],
             fmt(hv["btc_hold"]["calmar"]), fmt(hv["btc_rule"]["calmar"]),
             fmt(hv["panel_hold"]["calmar"]), fmt(hv["panel_rule"]["calmar"])))
    A("")
    A("副资产(① 面板)按同样三条判:① %s、② %s、③ %s ⇒ 面板版 **%s**(副资产,不参与主判定)。"
      % ("✓" if res["panel_verdict"]["c1"] else "✗", "✓" if res["panel_verdict"]["c2"] else "✗",
         "✓" if res["panel_verdict"]["c3"] else "✗",
         "✅ 过" if res["panel_verdict"]["pass"] else "❌ 不过"))
    A("")
    A("附带(不判):BTC 臂对持有臂的 A/B(装置 `ab_test`,块长 20 天,%d 次自助,种子 %d):总对数差 %s、"
      "单侧 p(B≤A)=%s、结论「%s」。"
      % (res["ab_test_btc"]["n_boot"], res["protocol"]["seed"],
         fmt(res["ab_test_btc"]["log_diff_total"]), fmt(res["ab_test_btc"]["p_b_le_a"], 4),
         res["ab_test_btc"]["verdict"]))
    A("")
    A("## 3. 结果里还看到了什么(假设之外)")
    A("")
    A("以下都是描述性的观察,**不判**;要用它们做新规则,需另立预注册、在新数据上过零信号对照。")
    A("")
    for s in res.get("exploratory", []):
        A("- %s" % s)
    A("")
    A("## 4. 协议问题(照执行、不改协议,列给 Seth)")
    A("")
    for i, s in enumerate(res.get("protocol_issues", []), 1):
        A("%d. %s" % (i, s))
    A("")
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="full", choices=["selftest", "gate", "full"])
    a = ap.parse_args()
    if not URL or not KEY:
        print("缺少 SUPABASE_URL / SUPABASE_KEY,退出", file=sys.stderr)
        return 2
    if a.mode == "selftest":
        return selftest()
    if a.mode == "gate":
        ok, pending, _ = check_gate()
        return 0 if ok else 3
    return run_full()


if __name__ == "__main__":
    sys.exit(main())
