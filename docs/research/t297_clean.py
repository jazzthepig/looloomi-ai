#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-297 — S-777 纠错复算:S-726 / S-768 的 squeeze 事件集有伪事件,加两条守卫后重算 S-768 ①。

底稿 = t289_squeeze.py(lane-b/T-289),**只加两条守卫,其余一字不改**:
  ① d 日的 f7 为空 ⇒ 不是事件(资金费缺失被算成扩张分位 0.0000 = 「最低分位」,不是「空头最拥挤」);
  ② ATR14 ≤ 0 或 20 日均 qv ≤ 0 ⇒ 不是事件(门槛恒为 0 ⇒ 恒真命中)。
预注册(S-777 原文,照抄在 docs/research/T-297_squeeze_clean.md 开头)。
口径:事件定义 = S-726;wo = 0(原口径)与 wo = 1(信号日整体挪到 d+1 ⇒ 进场 d+2 开盘 → d+H+1 收盘)并报;
随机分位 = apparatus.null_distribution / percentile_of(种子 726,1,000 次)。
只读:不改代码、不做 DDL、不入库。零分布 / 盈亏只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t242/cache"
PBV_JSONL = "/Volumes/CometCloudAI/cometcloud-local/research/t238/_bars_pbv.jsonl"
OUT_JSON = os.path.join(HERE, "t297_results.json")
EVENTS_JSON = os.path.join(HERE, "t297_events.json")
TICKETS_JSON = os.path.join(HERE, "t197_results.json")
OI_CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t289/cache/deriv_oi_by_event.json"
SU = os.environ["SUPABASE_URL"]
SK = os.environ["SUPABASE_KEY"]
S_HDR = {"apikey": SK, "Authorization": "Bearer " + SK, "Prefer": "count=exact"}

# ── apparatus(唯一允许的盈亏 / 零分布来源) ─────────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "apparatus", os.path.join(REPO, "src", "data", "evaluation", "apparatus.py"))
apparatus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apparatus)
long_return = apparatus.long_return
null_distribution = apparatus.null_distribution
percentile_of = apparatus.percentile_of

# ── 预注册常数(照抄卡上 acceptance,不扫参数) ────────────────────────────────
FUND_WIN = 7           # 前 7 日均资金费
FUND_ANN_MULT = 3 * 365  # 日均费率 × 3 × 365
PCTL_HI = 0.90         # 拥挤多头
PCTL_LO = 0.10         # 拥挤空头
ATR_N = 14             # ATR14
ATR_K = 2.0            # ±2 × ATR14 / 收盘
QV_WIN = 20            # 前 20 日均 qv
QV_MULT = 3.0          # qv ≥ 3 × 均量
MIN_AGE_DAYS = 180     # 前 180 天不打分
MIN_PRIOR_F7 = 30      # 扩张历史至少 30 个 7 日资金费样本
DEDUPE_DAYS = 10       # 同一合约 10 天内只计第一次
HORIZONS = (1, 7, 30)
LISTED_MIN_DAYS = 30   # 篮子成分:已上市 ≥ 30 天
N_NULL = 1000
NULL_SEED = 726
HALVES = {"H1": ("2020-01-01", "2022-12-31"), "H2": ("2023-01-01", "2026-10-31")}


def log(*a):
    print(*a, flush=True)


# ── 载入 ────────────────────────────────────────────────────────────────────
def load_pbv():
    """perp_bv_daily:流式读 T-238 的同查询缓存(668,222 行)。"""
    cols = ["symbol", "d", "o", "h", "l", "c", "qv", "tbqv"]
    data = {c: [] for c in cols}
    meta = None
    with open(PBV_JSONL) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if i == 0:
                meta = obj.get("_meta", obj)
                continue
            for r in obj:
                for c in cols:
                    data[c].append(r.get(c))
    df = pd.DataFrame(data)
    df["d"] = pd.to_datetime(df["d"])
    for c in ["o", "h", "l", "c", "qv", "tbqv"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values(["symbol", "d"]).reset_index(drop=True)
    return df, meta


def load_cached(table):
    """fetch 缓存:JSON → DataFrame(带 csv.gz 旁路缓存)。"""
    gz = os.path.join(CACHE, table + ".csv.gz")
    if os.path.exists(gz):
        return pd.read_csv(gz)
    with open(os.path.join(CACHE, table + ".json")) as f:
        rows = json.load(f)["rows"]
    df = pd.DataFrame(rows)
    df.to_csv(gz, index=False)
    return df


# ── 面板 ────────────────────────────────────────────────────────────────────
def build_panels(pbv, pairs, funding, deriv):
    """把每合约的日序列摊成 (n_sym × max_len) 矩阵,并做按日的开/收矩阵。"""
    syms = sorted(pbv["symbol"].unique())
    sidx = {s: i for i, s in enumerate(syms)}
    n_sym = len(syms)
    max_len = int(pbv.groupby("symbol").size().max())

    dates = pd.DataFrame(index=range(n_sym), columns=range(max_len), dtype="datetime64[ns]")
    O = np.full((n_sym, max_len), np.nan)
    H = np.full((n_sym, max_len), np.nan)
    L = np.full((n_sym, max_len), np.nan)
    C = np.full((n_sym, max_len), np.nan)
    QV = np.full((n_sym, max_len), np.nan)

    g = pbv.groupby("symbol", sort=True)
    for s, sub in g:
        i = sidx[s]
        k = len(sub)
        dates.iloc[i, :k] = sub["d"].values
        O[i, :k] = sub["o"].values
        H[i, :k] = sub["h"].values
        L[i, :k] = sub["l"].values
        C[i, :k] = sub["c"].values
        QV[i, :k] = sub["qv"].values

    # 资金费 → 逐合约按日对齐
    F = np.full((n_sym, max_len), np.nan)
    if funding is not None and len(funding):
        fs = set(sidx)
        fd = funding[funding["symbol"].isin(fs)].copy()
        fd["si"] = fd["symbol"].map(sidx)
        m = pd.MultiIndex.from_arrays([fd["si"], fd["d"]])
        lut = pd.Series(fd["funding_rate"].values, index=m)
        for i in range(n_sym):
            row = dates.iloc[i]
            vals = lut.reindex(pd.MultiIndex.from_arrays([np.full(len(row), i), row.values]))
            F[i] = vals.values

    # 派生量
    with np.errstate(all="ignore"):
        prev_c = np.roll(C, 1, axis=1)
        prev_c[:, 0] = np.nan
        tr = np.nanmax(np.stack([H - L, np.abs(H - prev_c), np.abs(L - prev_c)]), axis=0)
        ret = C / prev_c - 1.0
        atr_prev = np.full_like(C, np.nan)      # ATR14 用 ≤ d−1
        for i in range(n_sym):
            k = int(np.isfinite(C[i]).sum())
            if k > ATR_N + 1:
                s = pd.Series(tr[i, :k]).rolling(ATR_N).mean().shift(1)
                atr_prev[i, :k] = s.values
        qv20 = np.full_like(QV, np.nan)          # 前 20 日均 qv
        for i in range(n_sym):
            k = int(np.isfinite(QV[i]).sum())
            if k > QV_WIN + 1:
                qv20[i, :k] = pd.Series(QV[i, :k]).rolling(QV_WIN).mean().shift(1).values
        # 7 日均资金费(年化)→ 扩张分位
        f7 = np.full_like(F, np.nan)
        pct = np.full_like(F, np.nan)
        for i in range(n_sym):
            k = int(np.isfinite(F[i]).sum())
            if k < FUND_WIN + 2:
                continue
            s = pd.Series(F[i, :k])
            m7 = s.rolling(FUND_WIN).mean().shift(1)     # d−7..d−1
            ann = m7 * FUND_ANN_MULT
            f7[i, :k] = ann.values
            # 扩张分位:参考集 = 严格早于当天的样本(自比自排除)
            av = ann.values
            nprior = np.maximum(np.arange(1, k + 1) - 1, 1)
            with np.errstate(all="ignore"):
                M = (av[None, :] < av[:, None]).astype(np.float32) + \
                    0.5 * (av[None, :] == av[:, None]).astype(np.float32)
                less_eq = np.tril(M, -1).sum(axis=1)   # 只算 j < i
            pct[i, :k] = less_eq / nprior
            del M
    # 年龄(天)
    first_ord = np.full(n_sym, np.nan)
    for i in range(n_sym):
        k = int(np.isfinite(C[i]).sum())
        if k:
            first_ord[i] = dates.iloc[i, 0].value / 86400e9
    ordmat = np.full((n_sym, max_len), np.nan)
    for i in range(n_sym):
        k = int(np.isfinite(C[i]).sum())
        ordmat[i, :k] = dates.iloc[i, :k].values.astype("datetime64[D]").astype(np.int64)

    # 按日期的开/收矩阵(篮子用)
    alld = sorted(set(pbv["d"].values))
    dpos = {int(pd.Timestamp(d).value): j for j, d in enumerate(alld)}
    Omat = np.full((len(alld), n_sym), np.nan)
    Cmat = np.full((len(alld), n_sym), np.nan)
    for s, sub in pbv.groupby("symbol", sort=True):
        i = sidx[s]
        js = [dpos[int(pd.Timestamp(d).value)] for d in sub["d"].values]
        Omat[js, i] = sub["o"].values
        Cmat[js, i] = sub["c"].values
    date_ord = np.array([pd.Timestamp(d).value / 86400e9 for d in alld])
    day0 = int(np.floor(date_ord.min()))
    dlookup = np.full(int(np.ceil(date_ord.max())) - day0 + 1, -1, dtype=np.int64)
    dlookup[(date_ord - day0).astype(np.int64)] = np.arange(len(alld))
    date_ns = ordmat * 86400e9
    return dict(syms=syms, sidx=sidx, n_sym=n_sym, max_len=max_len, dates=dates, O=O, H=H, L=L, C=C,
                QV=QV, F=F, f7=f7, pct=pct, ret=ret, atr=atr_prev, qv20=qv20, ordmat=ordmat,
                first_ord=first_ord, Omat=Omat, Cmat=Cmat, date_ord=date_ord, dpos=dpos,
                date_ns=date_ns, dlookup=dlookup, day0=day0)


# ── 事件检测 ────────────────────────────────────────────────────────────────
def detect(pan, universe_mask, off=0, guards=True):
    """off=0 原样;off=+1 信号日挪一天(在 d+1 判, d+2 开盘进)。返回事件列表。

    guards=True 时追加 S-777 的两条守卫(其余逻辑一字不改):
      ① d 日 f7 为空 ⇒ 不是事件;
      ② ATR14 ≤ 0 或 20 日均 qv ≤ 0 ⇒ 不是事件。
    guards=False = S-768 ① 原口径(用来对账「被剔掉那批」)。
    """
    ev = {"flush": [], "squeeze": []}
    n_sym = pan["n_sym"]
    age_ok = pan["ordmat"] - pan["first_ord"][:, None] >= MIN_AGE_DAYS
    for i in range(n_sym):
        if not universe_mask[i]:
            continue
        k = int(np.isfinite(pan["C"][i]).sum())
        if k < 40:
            continue
        d = pan["dates"].iloc[i]
        o = pan["O"][i]
        h = pan["H"][i]
        l = pan["L"][i]
        c = pan["C"][i]
        qv = pan["QV"][i]
        ret = pan["ret"][i]
        atr = pan["atr"][i]
        q20 = pan["qv20"][i]
        pct = pan["pct"][i]
        f7 = pan["f7"][i]
        ords = pan["ordmat"][i]
        thr = ATR_K * atr / np.roll(c, 1)
        cand_f, cand_s = [], []
        for j in range(1, k):
            jj = j + off
            if jj < 0 or jj >= k - 1:
                continue
            if not np.isfinite(pct[jj]) or not np.isfinite(q20[jj]) or not np.isfinite(thr[jj]):
                continue
            if guards:
                # S-777 守卫 ①:d 日 f7 为空 ⇒ 不是事件(缺失 ≠ 最低分位)
                if not np.isfinite(f7[jj]):
                    continue
                # S-777 守卫 ②:ATR14 ≤ 0 或 20 日均 qv ≤ 0 ⇒ 不是事件(门槛恒为 0 ⇒ 恒真命中)
                if not (atr[jj] > 0) or not (q20[jj] > 0):
                    continue
            if not np.isfinite(ords[jj]) or not (age_ok[i, jj]):
                continue
            if ret[jj] is None or not np.isfinite(ret[jj]):
                continue
            if qv[jj] < QV_MULT * q20[jj]:
                continue
            if pct[jj] >= PCTL_HI and ret[jj] <= -thr[jj]:
                cand_f.append(jj)
            elif pct[jj] <= PCTL_LO and ret[jj] >= thr[jj]:
                cand_s.append(jj)
        for name, cand in (("flush", cand_f), ("squeeze", cand_s)):
            last = None
            for jj in cand:
                if last is not None and (ords[jj] - ords[last]) < DEDUPE_DAYS:
                    continue
                ev[name].append({"sym_i": i, "bar": jj, "d": str(d.iloc[jj])[:10],
                                 "ord": float(ords[jj])})
                last = jj
    return ev


# ── 前向收益 + 篮子 ─────────────────────────────────────────────────────────
def basket_masks(pan, coin_mask, first_ord):
    return coin_mask, first_ord


def forward(pan, events, coin_mask, first_ord, horizon, offs=None, win_off=0):
    """返回 per-event 超额收益、篮子大小、事件收益。

    win_off=0 原口径:进场 d+1 开盘(bar j+1)→ d+H 收盘(bar j+H)。
    win_off=1 挪一天:信号日挪到 d+1 ⇒ 进场 d+2 开盘(bar j+2)→ d+H+1 收盘(bar j+H+1)。
    """
    O, C = pan["O"], pan["C"]
    dpos = pan["dpos"]
    date_ord = pan["date_ord"]
    n = len(events)
    if n == 0:
        return np.array([]), np.array([]), np.array([]), []
    ev_ret = np.full(n, np.nan)
    bk_ret = np.full(n, np.nan)
    bk_n = np.zeros(n, dtype=int)
    ent_ord = np.full(n, np.nan)
    ex_ord = np.full(n, np.nan)
    entry_dates = []
    for t, e in enumerate(events):
        i = e["sym_i"]
        j = e["bar"]
        eb = j + 1 + win_off
        xb = j + horizon + win_off
        k = int(np.isfinite(C[i]).sum())
        if eb >= k or xb >= k:
            continue
        p_in = O[i, eb]
        p_out = C[i, xb]
        if not (np.isfinite(p_in) and np.isfinite(p_out)) or p_in <= 0 or p_out <= 0:
            continue
        ev_ret[t] = p_out / p_in - 1.0
        de = pan["dates"].iloc[i, eb]
        dx = pan["dates"].iloc[i, xb]
        # 日历容差:horizon 天(+3)
        if (dx - de).days > horizon + 3:
            continue
        je, jx = dpos[int(pd.Timestamp(de).value)], dpos[int(pd.Timestamp(dx).value)]
        Orow, Crow = pan["Omat"][je], pan["Cmat"][jx]
        elig = np.isfinite(Orow) & np.isfinite(Crow) & coin_mask & (first_ord <= date_ord[je] - LISTED_MIN_DAYS)
        if elig.sum() == 0:
            continue
        bk_ret[t] = np.nanmean(Crow[elig] / Orow[elig] - 1.0)
        bk_n[t] = int(elig.sum())
        ent_ord[t] = date_ord[je]
        ex_ord[t] = date_ord[jx]
        entry_dates.append((de, dx))
    exc = ev_ret - bk_ret
    return ev_ret, bk_ret, exc, dict(bk_n=bk_n, entry_dates=entry_dates)


# ── 随机日期零分布(同一合约、保持年份分布) ────────────────────────────────
def null_stats(pan, events, coin_mask, first_ord, horizon, stat_fn, n_null=N_NULL, seed=NULL_SEED, win_off=0):
    """构造随机日期对照:同一合约、同一年份内随机取 d。返回零分布数组(apparatus.null_distribution)。
    win_off 与 forward() 同口径(随机日也用同一套进场/出场窗口)。"""
    n = len(events)
    if n == 0:
        return np.array([])
    O, C = pan["O"], pan["C"]
    date_ord = pan["date_ord"]
    # 每个事件:候选 bar 索引(同合约、同年、且前向窗口存在)
    cand_flat, cand_start, cand_len = [], [], []
    off = 0
    for e in events:
        i = e["sym_i"]
        k = int(np.isfinite(C[i]).sum())
        y = int(str(e["d"])[:4])
        ords = pan["ordmat"][i]
        y0 = np.datetime64("%d-01-01" % y).astype("datetime64[D]").astype(np.int64)
        y1 = np.datetime64("%d-12-31" % y).astype("datetime64[D]").astype(np.int64)
        idx = np.where((ords >= y0) & (ords <= y1) & np.isfinite(ords))[0]
        idx = idx[idx + horizon + win_off < k]
        if len(idx) == 0:
            cand_start.append(off)
            cand_len.append(0)
        else:
            cand_start.append(off)
            cand_flat.append(idx.astype(np.int64))
            off += len(idx)
            cand_len.append(len(idx))
    lens = np.array(cand_len)
    starts = np.array(cand_start)
    if (lens == 0).any():
        keep = lens > 0
        if keep.sum() < 5:
            return np.array([])
        events = [e for e, k in zip(events, keep) if k]
        lens = lens[keep]
        starts = starts[keep]
    flat = np.concatenate(cand_flat) if cand_flat else np.array([], dtype=np.int64)
    sym_arr = np.array([e["sym_i"] for e in events])
    klen_arr = np.array([int(np.isfinite(C[s]).sum()) for s in sym_arr])

    def one_draw(rng):
        u = rng.random(len(lens))
        pick = starts + (u * lens).astype(int)
        idx = flat[pick]
        eb = idx + 1 + win_off
        xb = idx + horizon + win_off
        ok = (eb < klen_arr) & (xb < klen_arr)
        if not ok.all():
            return np.nan
        p_in = O[sym_arr, eb]
        p_out = C[sym_arr, xb]
        good = np.isfinite(p_in) & np.isfinite(p_out) & (p_in > 0)
        if not good.all():
            return np.nan
        ev_ret = p_out / p_in - 1.0
        de = pan["date_ns"][sym_arr, eb]
        dx = pan["date_ns"][sym_arr, xb]
        je = pan["dlookup"][(de / 86400e9 - pan["day0"]).astype(np.int64)]
        jx = pan["dlookup"][(dx / 86400e9 - pan["day0"]).astype(np.int64)]
        Orow = pan["Omat"][je]
        Crow = pan["Cmat"][jx]
        elig = np.isfinite(Orow) & np.isfinite(Crow) & coin_mask[None, :] & \
            (first_ord[None, :] <= date_ord[je][:, None] - LISTED_MIN_DAYS)
        cnt = elig.sum(axis=1)
        if (cnt == 0).any():
            return np.nan
        rr = np.where(elig, Crow / Orow - 1.0, np.nan)
        bk = np.nanmean(rr, axis=1)
        return float(stat_fn(ev_ret - bk))

    def fn(rng):
        v = one_draw(rng)
        return v if np.isfinite(v) else 0.0

    return null_distribution(fn, n_null, seed)


# ── 统计 ────────────────────────────────────────────────────────────────────
def describe(x):
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    if x.size == 0:
        return {"n": 0}
    s = pd.Series(x)
    k = max(1, int(np.ceil(0.10 * x.size)))
    srt = np.sort(x)
    return {
        "n": int(x.size),
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "win_rate": float((x > 0).mean()),
        "skew": float(s.skew()) if x.size > 2 else None,
        "worst10_mean": float(srt[:k].mean()),
        "best10_mean": float(srt[-k:].mean()),
        "p05": float(np.percentile(x, 5)),
        "p95": float(np.percentile(x, 95)),
        "min": float(x.min()),
        "max": float(x.max()),
    }


def main():
    t0 = time.time()
    log("loading perp_bv_daily ...")
    pbv, pbv_meta = load_pbv()
    log("  perp_bv_daily rows:", len(pbv), "| meta:", (pbv_meta or {}).get("query"))
    pairs = load_cached("perp_bv_pairs")
    pairs["first_d"] = pd.to_datetime(pairs["first_d"])
    funding = load_cached("v_funding_daily")
    funding["d"] = pd.to_datetime(funding["d"])
    funding["funding_rate"] = pd.to_numeric(funding["funding_rate"], errors="coerce")
    try:
        deriv = load_cached("deriv_metrics_daily")
        deriv["d"] = pd.to_datetime(deriv["d"])
        deriv["oi_close"] = pd.to_numeric(deriv["oi_close"], errors="coerce")
    except Exception as e:
        log("  deriv load failed:", repr(e)[:200])
        deriv = None
    log("  funding rows:", len(funding), "| deriv rows:", 0 if deriv is None else len(deriv),
        "| pairs:", len(pairs), "| %.0fs" % (time.time() - t0))

    pan = build_panels(pbv, pairs, funding, deriv)
    syms = pan["syms"]
    log("panels built %.0fs" % (time.time() - t0))

    # 宇宙(卡):kind='coin' 或 kind 为空且 dead_from 有值
    kind = dict(zip(pairs["symbol"], pairs["kind"]))
    dead = {s: (None if pd.isna(dd) else dd) for s, dd in zip(pairs["symbol"], pairs["dead_from"])}
    coin_mask = np.array([(kind.get(s) == "coin") for s in syms])
    uni_mask = np.array([(kind.get(s) == "coin") or (kind.get(s) is None and dead.get(s) is not None)
                         for s in syms])
    log("universe:", int(uni_mask.sum()), "| coin(basket):", int(coin_mask.sum()))
    # first_d 用于篮子「已上市 ≥ 30 天」;用 pairs.first_d,缺则用 bars 首日
    first_ord_pairs = np.full(len(syms), np.nan)
    for s, fd in zip(pairs["symbol"], pairs["first_d"]):
        if s in pan["sidx"]:
            first_ord_pairs[pan["sidx"][s]] = fd.value / 86400e9 if pd.notna(fd) else np.nan
    first_ord = np.where(np.isfinite(first_ord_pairs), first_ord_pairs, pan["first_ord"])

    res = {"meta": {"task": "T-242", "pre_registered": "S-726 / card T-242 acceptance (2026-11-05)",
                    "perp_bv_rows": int(len(pbv)),
                    "perp_bv_query": (pbv_meta or {}).get("query"),
                    "perp_bv_source": PBV_JSONL,
                    "funding_rows": int(len(funding)),
                    "deriv_rows": 0 if deriv is None else int(len(deriv)),
                    "n_universe": int(uni_mask.sum()), "n_coin": int(coin_mask.sum()),
                    "constants": {"fund_win": FUND_WIN, "ann": FUND_ANN_MULT, "pct_hi": PCTL_HI,
                                  "pct_lo": PCTL_LO, "atr_n": ATR_N, "atr_k": ATR_K,
                                  "qv_win": QV_WIN, "qv_mult": QV_MULT, "min_age_days": MIN_AGE_DAYS,
                                  "min_prior_f7": MIN_PRIOR_F7, "dedupe_days": DEDUPE_DAYS,
                                  "listed_min_days": LISTED_MIN_DAYS, "n_null": N_NULL,
                                  "seed": NULL_SEED},
                    "atr_reference": "ATR14 / c_{d-1}(ATR 窗口止于 d−1)",
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
           "events": {}, "results": {}, "selfcheck": {}, "concentration": {}, "oi_sub": {}}

    # ── 事件检测 ──
    # S-777 干净集(两条守卫) = 正式口径;legacy(guards=False) = S-768 ① 原口径,只用来对账
    ev0 = detect(pan, uni_mask, off=0, guards=True)
    ev1 = detect(pan, uni_mask, off=1, guards=True)   # S-665 挪一天
    ev0_legacy = detect(pan, uni_mask, off=0, guards=False)
    ev1_legacy = detect(pan, uni_mask, off=1, guards=False)
    for nm, ev in (("flush", ev0["flush"]), ("squeeze", ev0["squeeze"])):
        yrs = {}
        for e in ev:
            yrs[e["d"][:4]] = yrs.get(e["d"][:4], 0) + 1
        res["events"][nm] = {"n": len(ev), "by_year": dict(sorted(yrs.items()))}
        log("  events", nm, len(ev), dict(sorted(yrs.items())))

    # ── 长返回自检(200 样本) ──
    sc = {"n": 0, "max_abs_diff": 0.0}
    for nm, ev in (("flush", ev0["flush"]), ("squeeze", ev0["squeeze"])):
        for e in ev[:100]:
            i, j = e["sym_i"], e["bar"]
            if j + 1 >= pan["n_sym"] and False:
                continue
            k = int(np.isfinite(pan["C"][i]).sum())
            if j + 30 >= k:
                continue
            a, b = pan["O"][i, j + 1], pan["C"][i, j + 30]
            mine = b / a - 1.0
            theirs = long_return(a, b)
            if theirs is None:
                continue
            sc["n"] += 1
            sc["max_abs_diff"] = max(sc["max_abs_diff"], abs(mine - theirs))
    res["selfcheck"] = sc
    log("  long_return selfcheck:", sc)

    # ── 主统计:两种口径并报(win_off=0 原口径;win_off=1 信号日整体挪到 d+1) ──
    for nm, ev in (("flush", ev0["flush"]), ("squeeze", ev0["squeeze"])):
        res["results"][nm] = {}
        ev_sorted = sorted(ev, key=lambda e: e["d"])
        darr = np.array([e["d"] for e in ev_sorted])
        for wo in (0, 1):
            for H in HORIZONS:
                ev_ret, bk_ret, exc, meta = forward(pan, ev_sorted, coin_mask, first_ord, H, win_off=wo)
                block = {"full": {"excess": describe(exc), "event": describe(ev_ret),
                                  "basket": describe(bk_ret)}}
                for hk, (a, b) in HALVES.items():
                    m = (darr >= a) & (darr <= b)
                    block[hk] = {"excess": describe(exc[m]), "event": describe(ev_ret[m]),
                                 "basket": describe(bk_ret[m])}
                # 零分布(超额中位 / 均值)——全样本;同一零分布口径报两半
                nulls = {}
                if len(ev_sorted) < 10:
                    nulls["full"] = {"n": len(ev_sorted), "note": "too few events for null"}
                else:
                    nm_med = null_stats(pan, ev_sorted, coin_mask, first_ord, H, np.median, win_off=wo)
                    act_md = float(np.nanmedian(exc))
                    rec = {"n": len(ev_sorted), "actual_median": act_md,
                           "null_median_pctl": percentile_of(act_md, nm_med),
                           "null_median_median": float(np.median(nm_med)),
                           "null_median_n": int(len(nm_med))}
                    if H == 30:
                        nm_mean = null_stats(pan, ev_sorted, coin_mask, first_ord, H, np.mean, win_off=wo)
                        act_m = float(np.nanmean(exc))
                        rec.update({"actual_mean": act_m,
                                    "null_mean_pctl": percentile_of(act_m, nm_mean),
                                    "null_mean_median": float(np.median(nm_mean)),
                                    "null_mean_n": int(len(nm_mean))})
                    nulls["full"] = rec
                block["null"] = nulls
                res["results"][nm].setdefault(str(H), {})[str(wo)] = block
                log("  %s wo=%d H=%d full excess median %.4f (n=%d) | null med pctl %.3f | %.0fs"
                    % (nm, wo, H, block["full"]["excess"].get("median", float("nan")),
                       block["full"]["excess"].get("n", 0),
                       nulls.get("full", {}).get("null_median_pctl", float("nan")), time.time() - t0))

        # 聚集度:前 5 个日期占事件数
        bydate = {}
        for e in ev_sorted:
            bydate[e["d"]] = bydate.get(e["d"], 0) + 1
        top = sorted(bydate.items(), key=lambda kv: -kv[1])[:5]
        res["concentration"][nm] = {"n_dates": len(bydate), "top5": top,
                                     "top5_share": (sum(c for _, c in top) / max(1, len(ev_sorted))),
                                     "top1_date": top[0] if top else None}

    # ── S-777:被两条守卫剔掉的那批(legacy 事件集 − 干净事件集)单独的中位 ──
    res["dropped"] = {}
    for nm in ("flush", "squeeze"):
        legacy = ev0_legacy[nm]
        legacy_keys = {(e["sym_i"], e["bar"]) for e in legacy}
        clean_keys = {(e["sym_i"], e["bar"]) for e in ev0[nm]}
        dropped = [e for e in legacy if (e["sym_i"], e["bar"]) not in clean_keys]
        added = [e for e in ev0[nm] if (e["sym_i"], e["bar"]) not in legacy_keys]
        why = {"f7_nan": 0, "atr_le_0": 0, "qv20_le_0": 0}
        for e in dropped:
            i, j = e["sym_i"], e["bar"]
            if not np.isfinite(pan["f7"][i, j]):
                why["f7_nan"] += 1
            if not (pan["atr"][i, j] > 0):
                why["atr_le_0"] += 1
            if not (pan["qv20"][i, j] > 0):
                why["qv20_le_0"] += 1
        ds = sorted(dropped, key=lambda e: e["d"])
        d_drop = {}
        for wo in (0, 1):
            for H in HORIZONS:
                ev_ret, bk_ret, exc, meta = forward(pan, ds, coin_mask, first_ord, H, win_off=wo)
                blk = {"n": len(ds), "excess": describe(exc)}
                for hk, (a, b) in HALVES.items():
                    m = np.array([(a <= e["d"] <= b) for e in ds], dtype=bool)
                    blk[hk] = {"n": int(m.sum()), "excess": describe(exc[m])}
                d_drop["H%d|wo%d" % (H, wo)] = blk
        ls = sorted(legacy, key=lambda e: e["d"])
        d_leg = {}
        for wo in (0, 1):
            for H in HORIZONS:
                ev_ret, bk_ret, exc, meta = forward(pan, ls, coin_mask, first_ord, H, win_off=wo)
                d_leg["H%d|wo%d" % (H, wo)] = {"n": len(ls), "excess": describe(exc)}
        res["dropped"][nm] = {"n_legacy": len(legacy), "n_clean": len(ev0[nm]),
                              "n_dropped": len(dropped), "n_added": len(added),
                              "dropped_by": why, "dropped_stats": d_drop,
                              "legacy_stats": d_leg,
                              "dropped_events": [{"d": e["d"], "sym": pan["syms"][e["sym_i"]],
                                                  "bar": e["bar"]} for e in ds]}
        log("  dropped", nm, "legacy", len(legacy), "clean", len(ev0[nm]),
            "dropped", len(dropped), "added", len(added), why)

    # ── S-665 挪一天 ──
    res["shift_day"] = {}
    for nm, ev in (("flush", ev1["flush"]), ("squeeze", ev1["squeeze"])):
        ev_sorted = sorted(ev, key=lambda e: e["d"])
        d = {}
        for H in HORIZONS:
            ev_ret, bk_ret, exc, meta = forward(pan, ev_sorted, coin_mask, first_ord, H)
            d[str(H)] = {"n": len(ev_sorted), "excess": describe(exc)}
        res["shift_day"][nm] = d
        log("  shifted(+1)", nm, {k: (v["excess"].get("median"), v["n"]) for k, v in d.items()})

    # ── 副口径:OI 变化 ≤ −10% ──
    if deriv is not None and len(deriv):
        deriv = deriv.drop_duplicates(subset=["symbol", "d"], keep="last")
        oi_map = {}
        for s, dd, oi in zip(deriv["symbol"], deriv["d"], deriv["oi_close"]):
            if s in pan["sidx"]:
                oi_map[(pan["sidx"][s], dd)] = oi
        for nm, ev in (("flush", ev0["flush"]), ("squeeze", ev0["squeeze"])):
            ev_sorted = sorted(ev, key=lambda e: e["d"])
            H = 30
            ev_ret, bk_ret, exc, meta = forward(pan, ev_sorted, coin_mask, first_ord, H)
            rows = []
            for t, e in enumerate(ev_sorted):
                i = e["sym_i"]
                j = e["bar"]
                k = int(np.isfinite(pan["C"][i]).sum())
                if j < 1 or j >= k:
                    continue
                d0 = pan["dates"].iloc[i, j]
                dm1 = pan["dates"].iloc[i, j - 1]
                a = oi_map.get((i, d0))
                b = oi_map.get((i, dm1))
                if a is None or b is None or not np.isfinite(a) or not np.isfinite(b) or b <= 0:
                    continue
                ch = a / b - 1.0
                rows.append({"chg": ch, "exc": exc[t] if np.isfinite(exc[t]) else np.nan})
            if not rows:
                continue
            chg = np.array([r["chg"] for r in rows])
            ex = np.array([r["exc"] for r in rows])
            flat = chg <= -0.10
            res["oi_sub"][nm] = {
                "n_with_oi": int(len(rows)),
                "n_oi_down_10": int(flat.sum()), "n_other": int((~flat).sum()),
                "median_oi_chg": float(np.median(chg)),
                "down10_excess": describe(ex[flat]) if flat.sum() else {"n": 0},
                "other_excess": describe(ex[~flat]) if (~flat).sum() else {"n": 0},
                "all_excess": describe(ex),
            }
            log("  OI sub", nm, res["oi_sub"][nm]["n_with_oi"],
                "down10:", res["oi_sub"][nm]["n_oi_down_10"])

    # ── 事件清单先落文件(再取价) ──
    ev_dump = {"flush": ev0["flush"], "squeeze": ev0["squeeze"]}
    with open(EVENTS_JSON, "w") as f:
        json.dump(ev_dump, f, ensure_ascii=False, indent=1, default=float)
    log("  events written", EVENTS_JSON)

    # ── ② OI 副口径:按事件符号补取 deriv_metrics_daily(翻页带 order=) ──
    oi_map, oi_fetch = fetch_oi_for_events(ev_dump, pan["syms"])
    log("  OI rows:", len(oi_map), "| queries:", oi_fetch.get("queries"),
        "| no_oi_syms:", len(oi_fetch.get("no_oi_syms", [])))
    res["oi_fetch"] = oi_fetch
    res["oi_sub"] = {}
    for nm, ev in (("flush", ev0["flush"]), ("squeeze", ev0["squeeze"])):
        ev_sorted = sorted(ev, key=lambda e: e["d"])
        res["oi_sub"][nm] = {}
        for wo in (0, 1):
            H = 30
            ev_ret, bk_ret, exc, meta = forward(pan, ev_sorted, coin_mask, first_ord, H, win_off=wo)
            rows = []
            for t, e in enumerate(ev_sorted):
                i = e["sym_i"]
                j = e["bar"]
                k = int(np.isfinite(pan["C"][i]).sum())
                if j < 1 or j >= k:
                    continue
                sym = pan["syms"][i]
                a = oi_map.get((sym, str(pan["dates"].iloc[i, j])[:10]))
                b = oi_map.get((sym, str(pan["dates"].iloc[i, j - 1])[:10]))
                if a is None or b is None or b <= 0:
                    continue
                rows.append({"chg": a / b - 1.0,
                             "exc": exc[t] if np.isfinite(exc[t]) else np.nan})
            if not rows:
                continue
            chg = np.array([r["chg"] for r in rows])
            ex = np.array([r["exc"] for r in rows])
            flat = chg <= -0.10
            res["oi_sub"][nm][str(wo)] = {
                "n_with_oi": int(len(rows)),
                "n_oi_down_10": int(flat.sum()), "n_other": int((~flat).sum()),
                "median_oi_chg": float(np.median(chg)),
                "down10_excess": describe(ex[flat]) if flat.sum() else {"n": 0},
                "other_excess": describe(ex[~flat]) if (~flat).sum() else {"n": 0},
                "all_excess": describe(ex),
            }
            log("  OI sub", nm, "wo=%d" % wo, "n=", res["oi_sub"][nm][str(wo)]["n_with_oi"],
                "down10 n=", res["oi_sub"][nm][str(wo)]["n_oi_down_10"],
                "med=", res["oi_sub"][nm][str(wo)]["down10_excess"].get("median"),
                "other med=", res["oi_sub"][nm][str(wo)]["other_excess"].get("median"))

    # ── ③ R-v2 回放 ──
    res["rv2"] = replay_rv2(ev_dump, pan["syms"])
    log("  rv2 blocked:", res["rv2"].get("n_blocked"), "/", res["rv2"].get("n_tickets"),
        "| blocked mean r:", res["rv2"].get("blocked_mean_r"),
        "| rest mean r:", res["rv2"].get("rest_mean_r"))

    # ── 判定(S-768 三条) ──
    verd = {}
    for nm in ("flush", "squeeze"):
        r0 = res["results"][nm]["30"]["0"]
        r1 = res["results"][nm]["30"]["1"]
        oi0 = res["oi_sub"].get(nm, {}).get("0", {})
        dn = oi0.get("down10_excess", {}).get("median")
        ot = oi0.get("other_excess", {}).get("median")
        rv2 = res.get("rv2", {})
        bk = rv2.get("book", {}) if isinstance(rv2.get("book"), dict) else {}
        nb = int(rv2.get("n_blocked", 0))
        s1m = r1["full"]["excess"].get("median")
        s1p = r1["null"]["full"].get("null_median_pctl")
        s1h1 = r1["H1"]["excess"].get("median")
        s1h2 = r1["H2"]["excess"].get("median")
        c1 = bool(s1m is not None and s1m < 0 and s1p is not None and s1p <= 0.05
                  and s1h1 is not None and s1h2 is not None and s1h1 < 0 and s1h2 < 0)
        c2 = bool(dn is not None and ot is not None and np.sign(dn) == np.sign(ot))
        c3 = "不适用" if nb < 10 else bool(bk.get("rule_S_R_not_lower") and bk.get("rule_S_mdd_not_worse"))
        verd[nm] = {
            "orig_30d_median": r0["full"]["excess"].get("median"),
            "orig_h1": r0["H1"]["excess"].get("median"), "orig_h2": r0["H2"]["excess"].get("median"),
            "orig_null_pctl": r0["null"]["full"].get("null_median_pctl"),
            "shift_30d_median": s1m, "shift_h1": s1h1, "shift_h2": s1h2,
            "shift_null_pctl": s1p,
            "c1_shift_ok": c1, "c2_oi_same_sign": c2, "c3_rule_S": c3, "n_blocked": nb,
            "pass_123": bool(c1 and c2 and (c3 is True)),
        }
    res["verdict_s768"] = verd
    log("verdict:", json.dumps(verd, ensure_ascii=False, default=float))

    # 兼容旧登记块(它的键是 wo=0 的形状):把 wo=0 放回 H 层,并把 shift_day 换成真挪一天
    for nm in ("flush", "squeeze"):
        for H in [str(h) for h in HORIZONS]:
            b0 = res["results"][nm][H].get("0", {})
            if b0:
                res["results"][nm][H]["full"] = b0.get("full", {})
                for hk in HALVES:
                    if hk in b0:
                        res["results"][nm][H][hk] = b0[hk]
                res["results"][nm][H]["null"] = b0.get("null", {})
            b1 = res["results"][nm][H].get("1", {})
            res.setdefault("shift_day", {})
            res["shift_day"].setdefault(nm, {})[H] = {
                "n": b1.get("full", {}).get("excess", {}).get("n", 0),
                "excess": b1.get("full", {}).get("excess", {})}

    # ── 登记标记 ──
    reg = {}
    for nm in ("flush", "squeeze"):
        r30 = res["results"][nm]["30"]
        m30 = r30["full"]["excess"].get("median")
        h1 = r30["H1"]["excess"].get("median")
        h2 = r30["H2"]["excess"].get("median")
        pctl = r30["null"]["full"].get("null_median_pctl") if "full" in r30["null"] else None
        shift_med = res["shift_day"][nm]["30"]["excess"].get("median")
        same_sign = (h1 is not None and h2 is not None and np.sign(h1) == np.sign(h2))
        no_flip = (m30 is not None and shift_med is not None and np.sign(m30) == np.sign(shift_med))
        cand = (m30 is not None and m30 > 0 and same_sign and (pctl is not None and pctl >= 0.95) and no_flip)
        reg[nm] = {"median_30d": m30, "h1_median": h1, "h2_median": h2,
                   "null_median_pctile": pctl, "shifted_median_30d": shift_med,
                   "halves_same_sign": bool(same_sign), "shift_no_flip": bool(no_flip),
                   "is_setup_candidate": bool(cand),
                   "worst10_30d": r30["full"]["excess"].get("worst10_mean"),
                   "best10_30d": r30["full"]["excess"].get("best10_mean")}
    res["registration"] = reg
    log("registration:", json.dumps(reg, ensure_ascii=False, default=float))

    with open(OUT_JSON, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    log("wrote", OUT_JSON, "%.0fs" % (time.time() - t0))


# ── ② OI 补取(按事件符号;翻页带 order=;每页 ≤ 1000 行) ─────────────────────
def _sget(table, params, start=0, step=1000):
    url = SU + "/rest/v1/" + table + "?" + urllib.parse.urlencode(params)
    h = dict(S_HDR)
    h["Range"] = "bytes=%d-%d" % (start, start + step - 1)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode()), r.headers.get("Content-Range")


def fetch_oi_for_events(ev_dump, syms):
    """按事件符号补取 deriv_metrics_daily 的 oi_close:每个事件取 d 与 d−1 两天。翻页带 order=。"""
    import datetime as _dt
    need = {}
    for nm, ev in ev_dump.items():
        for e in ev:
            need.setdefault(syms[e["sym_i"]], set()).add(e["d"])
    need2 = {}
    for s, ds in need.items():
        s2 = set(ds)
        for d in ds:
            s2.add((_dt.date.fromisoformat(d) - _dt.timedelta(days=1)).isoformat())
        need2[s] = sorted(s2)
    oi = {}
    stats = {"symbols": len(need2), "queries": 0, "rows": 0, "no_oi_syms": [], "errors": []}
    for s, ds in need2.items():
        got = 0
        for i in range(0, len(ds), 25):
            chunk = ds[i:i + 25]
            params = {"select": "symbol,d,oi_close", "symbol": "eq." + s,
                      "d": "in.(" + ",".join(chunk) + ")",
                      "order": "symbol.asc,d.asc", "limit": "1000"}
            try:
                rows, cr = _sget("deriv_metrics_daily", params)
            except Exception as e:
                stats["errors"].append("%s: %s" % (s, repr(e)[:120]))
                continue
            stats["queries"] += 1
            for r in rows:
                v = r.get("oi_close")
                if v is None:
                    continue
                oi[(r["symbol"], r["d"])] = float(v)
                got += 1
            stats["rows"] += len(rows)
        if got == 0:
            stats["no_oi_syms"].append(s)
    try:
        os.makedirs(os.path.dirname(OI_CACHE), exist_ok=True)
        with open(OI_CACHE, "w") as f:
            json.dump({"oi": {"%s|%s" % k: v for k, v in oi.items()}, "stats": stats},
                      f, ensure_ascii=False)
    except Exception as e:
        stats["cache_err"] = repr(e)[:120]
    return oi, stats


# ── ③ R-v2 回放 ────────────────────────────────────────────────────────────
def _load_mod(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def replay_rv2(ev_dump, syms):
    """t197_results.json 的 A 组票;进场日落在同币 squeeze 事件 d+1…d+30 ⇒ 被规则 S 挡。"""
    import datetime as _dt
    res = {"source": "docs/research/t197_results.json tickets A",
           "rule_S": "squeeze 后 30 天内不开新票",
           "match": "进场日 − 事件日 ∈ [1, 30] 天(同币)"}
    blob = json.load(open(TICKETS_JSON))
    tk = blob["tickets"]["A"]
    ev_by_sym = {}
    for e in ev_dump["squeeze"]:
        ev_by_sym.setdefault(syms[e["sym_i"]], []).append(e["d"])
    for s in ev_by_sym:
        ev_by_sym[s] = sorted(ev_by_sym[s])

    def hit_of(t):
        for d in ev_by_sym.get(t["symbol"], []):
            k = (_dt.date.fromisoformat(t["entry_d"]) - _dt.date.fromisoformat(d)).days
            if 1 <= k <= 30:
                return d
        return None

    blocked = [(t, hit_of(t)) for t in tk]
    blocked = [(t, h) for t, h in blocked if h]
    res["n_tickets"] = len(tk)
    res["n_blocked"] = len(blocked)
    res["n_rest"] = len(tk) - len(blocked)
    rb = np.array([t["r"] for t, h in blocked if t.get("r") is not None], dtype=float)
    rr = np.array([t["r"] for t in tk if t.get("r") is not None and hit_of(t) is None], dtype=float)
    res["blocked_mean_r"] = float(rb.mean()) if rb.size else None
    res["rest_mean_r"] = float(rr.mean()) if rr.size else None
    res["blocked_median_r"] = float(np.median(rb)) if rb.size else None
    res["rest_median_r"] = float(np.median(rr)) if rr.size else None
    res["blocked_win"] = float((rb > 0).mean()) if rb.size else None
    res["rest_win"] = float((rr > 0).mean()) if rr.size else None
    res["blocked_list"] = [{"symbol": t["symbol"], "entry_d": t["entry_d"], "exit_d": t.get("exit_d"),
                            "r": t.get("r"), "squeeze_d": h} for t, h in blocked][:200]
    # 月块自助(apparatus.block_permute + null_distribution):被挡组 vs 其余
    items = sorted([t for t in tk if t.get("r") is not None], key=lambda t: t["entry_d"])
    Rs = np.array([t["r"] for t in items], dtype=float)
    isb = np.array([hit_of(t) is not None for t in items])
    if isb.sum() >= 2 and (~isb).sum() >= 2:
        blk = max(1, int(round(len(items) / 74.0)))

        def stat(rv):
            return float(rv[isb].mean() - rv[~isb].mean())

        obs = stat(Rs)

        def fn(rng):
            return stat(np.asarray(apparatus.block_permute(Rs.tolist(), blk, rng), dtype=float))

        try:
            null = null_distribution(fn, 2000, 768, actual=obs)
            res["block_boot"] = {"n_closed": len(items), "n_blocked": int(isb.sum()),
                                 "block_tickets": blk, "draws": 2000, "seed": 768,
                                 "observed_blocked_minus_rest": obs,
                                 "null_median": float(np.median(null)),
                                 "p_le_0": float((null <= 0).mean())}
        except Exception as e:
            res["block_boot"] = {"error": repr(e)[:200]}
    # 规则 S 的全书(t159.nav:f=1%、cap=10、复利、到 2026-09-30)
    try:
        t159 = _load_mod("t159_bear_short")
        t197 = _load_mod("t197_rv2_survivorship")
        bars = t197.load_um()
        NAV_TO = "2026-09-30"

        def book(tickets_):
            cur = list(t159.nav(tickets_, bars, 0.01, cap=10, d_to=NAV_TO))
            return t159.stats(cur)

        full = book(tk)
        keep = [t for t in tk if hit_of(t) is None]
        rule = book(keep)
        res["book"] = {"nav_to": NAV_TO, "f": 0.01, "cap": 10, "n_full": len(tk), "n_rule": len(keep),
                       "full": full, "rule_S": rule,
                       "rule_S_R_not_lower": bool(rule.get("end", 0) >= full.get("end", 0)),
                       "rule_S_mdd_not_worse": bool(rule.get("mdd", 0) >= full.get("mdd", 0))}
        halves = {}
        for hk, (a, b) in HALVES.items():
            sel = [t for t in tk if a <= t["entry_d"] <= b]
            selk = [t for t in sel if hit_of(t) is None]
            halves[hk] = {"n_full": len(sel), "n_rule": len(selk),
                          "full": book(sel), "rule_S": book(selk)}
        res["book_halves"] = halves
    except Exception as e:
        res["book"] = {"error": repr(e)[:300]}
    return res


if __name__ == "__main__":
    main()
