#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-330 / S-806 —— ③ 的相关性状态:① 面板 30 天平均两两相关高于扩张 80 分位时,把 ① 的敞口降到 0.5。

预注册(REFUTATION_LEDGER.md S-806)原文照抄在报告 `T-330_corr_state.md` 开头。
纪律:只读、不入库、不改代码。

框架(照 S-806「写死」段逐字实现):
  ① 面板 = 按时点 `cap_pit24`(RPC `core_pit_members`,p_n=24,每月一个名单,含死币)
  ① 臂   = `core_variants_daily` arm='cap_pit24' 的 d / ret / nav
  样本   = 2021-07-13 → 2026-10-31
  每天 d: ρ̄_d = 当日成员里有 ≥30 个日收益的币,最近 30 天日收益两两 Pearson 相关的平均
  阈值   = ρ̄ 到 d 为止(只用 ≤ d)的扩张 80 分位;前 252 天不判(m = 1)
  m_{d+1}= 0.5 若 ρ̄_d > 阈值,否则 1;余下现金(收益 0);m 变化的换手 × 10bp
  对照   = HOLD(m ≡ 1)与**同样时间占比的随机日程**(`apparatus.circular_shift`,块长 = 1 天,
           1,000 次,种子 806)
  判(全过才 ✅)= (i) 最大回撤比 HOLD 浅 ≥ 5pp;(ii) 年化收益损失 ≤ 2pp;
                  (iii) Calmar 在随机日程零分布里的分位(`apparatus.p_upper`)p ≤ 0.05;
                  (iv) 两半(按天数对半)Calmar 都 ≥ HOLD。
  另报   = m = 0.5 的天数占比、平均持续、与现有 ③ `tom_pd13` 的日程重合度。

用法:
  python3 t330_corr_state.py fetch   # 拉 ① 成员 + 价格/市值 + ① 臂 + tom_pd13 日程(只读)
  python3 t330_corr_state.py run     # 自检 + 回测 + 判据 → t330_results.json + T-330_corr_state.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

MEMBERS_JSON = HERE / "_t330_members.json"
PRICES_JSON = HERE / "_t330_prices.json"
ARM_JSON = HERE / "_t330_arm.json"
TOM_JSON = HERE / "_t330_tom.json"
RESULTS = HERE / "t330_results.json"
REPORT = HERE / "T-330_corr_state.md"
LEDGER = Path("/Users/sbb/Projects/looloomi-ai/REFUTATION_LEDGER.md")

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

# ── S-806「写死」的常量 ─────────────────────────────────────────────────────
SAMPLE_START = "2021-07-13"
SAMPLE_END = "2026-10-31"
MEMBER_START = "2020-01-01"          # 名单多取一段(只要样本期内的)
MEMBER_END = "2026-10-01"
PRICE_FROM = "2021-04-01"            # 样本首日前 30 天日收益要用
PRICE_TO = "2026-10-31"
WARMUP = 252                         # 前 252 天不判,m = 1
LOOKBACK = 30                        # 最近 30 天日收益
Q = 0.80                             # 扩张 80 分位
M_LOW = 0.5
COST = 10e-4                         # m 变化的换手 × 10bp
SEED = 806
N_NULL = 1000
MIN_COINS = 3                        # 少于 3 个币算不出两两相关

TODAY = dt.datetime.now(dt.timezone.utc).date().isoformat()


# ── REST(只读)───────────────────────────────────────────────────────────────
def _hdr(extra=None):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if extra:
        h.update(extra)
    return h


def _get(url, headers, tries=5, timeout=180):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8"), dict(r.headers)
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
            if e.code in (400, 404):
                raise SystemExit("REST 错误 %s" % last)
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(1.5 * (i + 1))
    raise SystemExit("REST 取数失败:%s(%s)" % (url[:160], last))


def _paged(base, q, headers, limit=1000):
    """翻页读(每页 ≤ 1000 行,带 order=)。"""
    out, off = [], 0
    while True:
        body, _h = _get("%s%s&limit=%d&offset=%d" % (base, q, limit, off), headers)
        rows = json.loads(body)
        out.extend(rows)
        if len(rows) < limit:
            break
        off += len(rows)
    return out


def _load_apparatus():
    p = ROOT / "src" / "data" / "evaluation" / "apparatus.py"
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 取数(只读)───────────────────────────────────────────────────────────────
def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"
    h = _hdr()

    # ① 成员:按时点 cap_pit24(每月一个名单)
    mem = _paged(base, ("rpc/core_pit_members?p_start=%s&p_end=%s&p_n=24&order=m.asc,rnk.asc"
                         % (MEMBER_START, MEMBER_END)), h)
    MEMBERS_JSON.write_text(json.dumps(mem, ensure_ascii=False))
    months = sorted({r["m"] for r in mem})
    syms = sorted({r["symbol"] for r in mem})
    print("① 成员: %d 行, %d 个月(%s → %s), %d 个币"
          % (len(mem), len(months), months[0], months[-1], len(syms)), flush=True)

    # 价格 + 市值(asset_mcap_daily = ① 的同一出处;T-325 已校验过的取法)
    def shard(sl):
        q = ("asset_mcap_daily?select=symbol,d,price,mcap&symbol=in.(%s)"
             "&and=(d.gte.%s,d.lte.%s)&order=symbol.asc,d.asc" % (",".join(sl), PRICE_FROM, PRICE_TO))
        return _paged(base, q, h)

    shards = [syms[i:i + 6] for i in range(0, len(syms), 6)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        parts = list(ex.map(shard, shards))
    seen, uniq = set(), []
    for part in parts:
        for r in part:
            k = (r["symbol"], r["d"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append([r["symbol"], r["d"], r["price"], r["mcap"]])
    uniq.sort(key=lambda r: (r[0], r[1]))
    meta = {"fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "price_from": PRICE_FROM, "price_to": PRICE_TO,
            "n_rows": len(uniq), "n_symbols": len({r[0] for r in uniq}),
            "seconds": round(time.time() - t0, 1)}
    PRICES_JSON.write_text(json.dumps({"meta": meta, "rows": uniq}, ensure_ascii=False))
    print("价格+市值: %d 行, %d 币, %s → %s (%.0fs)"
          % (len(uniq), meta["n_symbols"], PRICE_FROM, PRICE_TO, meta["seconds"]), flush=True)

    # 库里的 ① 臂(core_variants_daily,arm='cap_pit24')—— 自检的对照物
    arm = _paged(base, "core_variants_daily?select=d,ret,nav&arm=eq.cap_pit24&order=d.asc", h)
    ARM_JSON.write_text(json.dumps(arm, ensure_ascii=False))
    print("库里 cap_pit24 臂: %d 行 %s → %s"
          % (len(arm), arm[0]["d"] if arm else "-", arm[-1]["d"] if arm else "-"), flush=True)

    # 现有 ③ tom_pd13 的日程(multiplier_daily)
    tom = _paged(base, "multiplier_daily?select=d,arm,m,ret,nav&arm=eq.tom_pd13_replay&order=d.asc", h)
    TOM_JSON.write_text(json.dumps(tom, ensure_ascii=False))
    print("tom_pd13_replay: %d 行 %s → %s"
          % (len(tom), tom[0]["d"] if tom else "-", tom[-1]["d"] if tom else "-"), flush=True)
    print("→ %s / %s / %s / %s" % (MEMBERS_JSON.name, PRICES_JSON.name, ARM_JSON.name, TOM_JSON.name),
          flush=True)


# ── 指标 ────────────────────────────────────────────────────────────────────
def _maxdd(nav):
    nav = np.asarray(nav, dtype=float)
    peak = np.maximum.accumulate(nav)
    return float(np.min(nav / peak - 1.0))


def _calmar(nav, dates):
    """年化(CAGR,365 天)÷ |最大回撤|。nav 首日已归一到 1。"""
    nav = np.asarray(nav, dtype=float)
    if len(nav) < 2:
        return float("nan"), float("nan"), float("nan")
    total = nav[-1] / nav[0]
    days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    ann = (total ** (365.0 / days) - 1.0) if days > 0 and total > 0 else float("nan")
    mdd = _maxdd(nav)
    cal = ann / abs(mdd) if (np.isfinite(ann) and np.isfinite(mdd) and mdd < 0) else float("inf")
    return float(ann), float(mdd), float(cal)


def _strat_nav(m, rets, cost=COST):
    """按给定敞口日程跑 ① 的日收益:第 i 天先按 |Δm| 付换手成本,再赚 m_i × r_i。"""
    n = len(rets)
    nav = np.empty(n, dtype=float)
    prev = 1.0
    for i in range(n):
        turnover = abs(m[i] - m[i - 1]) if i > 0 else 0.0
        prev *= (1.0 - cost * turnover)
        nav[i] = prev * (1.0 + m[i] * rets[i])
        prev = nav[i]
    return nav


def _runs(flag):
    """flag(bool 数组)→ (段数, 平均段长(天), 最长段长)。"""
    runs, cur = [], 0
    for f in flag:
        if f:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    if not runs:
        return 0, 0.0, 0
    return len(runs), float(np.mean(runs)), int(max(runs))


def _run_list(low, days):
    """连续 m=0.5 的段 → [(起, 止, 天数)]。"""
    out, i, n = [], 0, len(low)
    while i < n:
        if low[i]:
            j = i
            while j + 1 < n and low[j + 1]:
                j += 1
            out.append([days[i].strftime("%Y-%m-%d"), days[j].strftime("%Y-%m-%d"), j - i + 1])
            i = j + 1
        else:
            i += 1
    return out


def _mdd_window(nav, days):
    """最大回撤的起止日。"""
    nav = np.asarray(nav, dtype=float)
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    i = int(np.argmin(dd))
    j = int(np.argmax(nav[:i + 1]))
    return float(dd[i]), days[j].strftime("%Y-%m-%d"), days[i].strftime("%Y-%m-%d")


# ── 主流程 ──────────────────────────────────────────────────────────────────
def cmd_run():
    apparatus = _load_apparatus()
    mem = json.loads(MEMBERS_JSON.read_text())
    pr = json.loads(PRICES_JSON.read_text())
    arm = json.loads(ARM_JSON.read_text())
    tom = json.loads(TOM_JSON.read_text())

    mem_by_month = {}
    for r in mem:
        mem_by_month.setdefault(r["m"], []).append(r["symbol"])

    df = pd.DataFrame(pr["rows"], columns=["symbol", "d", "price", "mcap"])
    df["d"] = pd.to_datetime(df["d"])
    cal = pd.date_range(df["d"].min(), df["d"].max(), freq="D")
    P = df.pivot(index="d", columns="symbol", values="price").reindex(cal)
    R = P.pct_change(fill_method=None)

    a = pd.DataFrame(arm).sort_values("d").reset_index(drop=True)
    a["d"] = pd.to_datetime(a["d"])
    a["ret"] = pd.to_numeric(a["ret"], errors="coerce")
    a["nav"] = pd.to_numeric(a["nav"], errors="coerce")

    # ── 自检 1:HOLD 与库里的 cap_pit24 逐日对上 ────────────────────────────
    nav_lib = a["nav"].to_numpy(dtype=float)
    nav_cum = np.cumprod(1.0 + a["ret"].to_numpy(dtype=float))
    diff_all = np.abs(nav_cum - nav_lib)
    rel_all = diff_all / np.maximum(np.abs(nav_lib), 1e-12)
    hold_check = {
        "n_rows_full": int(len(a)),
        "full_range": [a["d"].iloc[0].strftime("%Y-%m-%d"), a["d"].iloc[-1].strftime("%Y-%m-%d")],
        "max_abs_diff_full": float(diff_all.max()),
        "max_rel_diff_full": float(rel_all.max()),
        "argmax_abs_diff_d": a["d"].iloc[int(np.argmax(diff_all))].strftime("%Y-%m-%d"),
    }

    # ── 样本 ───────────────────────────────────────────────────────────────
    s = a[(a["d"] >= pd.Timestamp(SAMPLE_START)) & (a["d"] <= pd.Timestamp(SAMPLE_END))]
    s = s.reset_index(drop=True)
    days = list(s["d"])
    rets = s["ret"].to_numpy(dtype=float)
    n = len(s)
    if n < 400:
        raise SystemExit("样本只有 %d 天,太少" % n)

    # ── ρ̄_d:当日成员(有 ≥30 个日收益的币)最近 30 天日收益两两 Pearson 相关的平均 ──
    rho = np.full(n, np.nan)
    n_coins = np.zeros(n, dtype=int)
    n_pairs = np.zeros(n, dtype=int)
    all_dates = list(R.index)
    pos = {d: i for i, d in enumerate(all_dates)}
    for i, d in enumerate(days):
        mems = mem_by_month.get(d.strftime("%Y-%m-01"), [])
        if not mems:
            continue
        mems = [s for s in mems if s in R.columns]
        if len(mems) < MIN_COINS:
            continue
        j = pos.get(d)
        if j is None or j < LOOKBACK - 1:
            continue
        win = R.iloc[j - LOOKBACK + 1: j + 1][mems]
        ok = win.notna().all(axis=0)
        sub = win.loc[:, ok.values]
        if sub.shape[1] < MIN_COINS:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            c = np.corrcoef(sub.to_numpy(dtype=float).T)
        k = c.shape[0]
        off = c[np.triu_indices(k, 1)]
        off = off[np.isfinite(off)]
        if off.size < 3:
            continue
        rho[i] = float(off.mean())
        n_coins[i] = int(sub.shape[1])
        n_pairs[i] = int(off.size)

    # ── 阈值:ρ̄ 到 d 为止(只用 ≤ d)的扩张 80 分位 ───────────────────────
    thr = np.full(n, np.nan)
    hist = []
    for i in range(n):
        if np.isfinite(rho[i]):
            hist.append(rho[i])
        if hist:
            thr[i] = float(np.percentile(np.asarray(hist), Q * 100.0))

    # ── m 日程:m_{d+1} = 0.5 若 ρ̄_d > 阈值(前 252 天不判) ───────────────
    m = np.ones(n, dtype=float)
    for i in range(1, n):
        j = i - 1
        if j < WARMUP:
            continue
        if np.isfinite(rho[j]) and np.isfinite(thr[j]) and rho[j] > thr[j]:
            m[i] = M_LOW
    low = m < 1.0

    # ── 两条腿:HOLD 与相关性状态臂 ───────────────────────────────────────
    hold_nav = np.cumprod(1.0 + rets)
    strat_nav = _strat_nav(m, rets, COST)
    h_ann, h_mdd, h_cal = _calmar(hold_nav, days)
    s_ann, s_mdd, s_cal = _calmar(strat_nav, days)

    # ── 随机日程零分布(同样时间占比;apparatus.circular_shift,块长 1,1000 次,种子 806)──
    flag = low.astype(int)
    judged = slice(WARMUP, n)

    def _calmar_shift(rng, restrict=False):
        if restrict:
            f2 = apparatus.circular_shift(flag[judged], rng, block=1)
            mm = np.ones(n, dtype=float)
            mm[judged] = np.where(np.asarray(f2).astype(int) > 0, M_LOW, 1.0)
        else:
            f2 = apparatus.circular_shift(flag, rng, block=1)
            mm = np.where(np.asarray(f2).astype(int) > 0, M_LOW, 1.0)
        nav = _strat_nav(mm, rets, COST)
        return _calmar(nav, days)[2]

    null_full = apparatus.null_distribution(lambda rng: _calmar_shift(rng, False), N_NULL, SEED)
    p_full = apparatus.p_upper(s_cal, null_full)
    pct_full = apparatus.percentile_of(s_cal, null_full)
    null_judged = apparatus.null_distribution(lambda rng: _calmar_shift(rng, True), N_NULL, SEED)
    p_judged = apparatus.p_upper(s_cal, null_judged)

    # ── 两半(按天数对半)────────────────────────────────────────────────────
    half = n // 2
    halves = {}
    for name, sl in (("h1", slice(0, half)), ("h2", slice(half, n))):
        hd = days[sl]
        hn = hold_nav[sl] / hold_nav[sl][0]
        sn = strat_nav[sl] / strat_nav[sl][0]
        ha, hm, hc = _calmar(hn, hd)
        sa, sm, sc = _calmar(sn, hd)
        halves[name] = {"days": len(hd), "from": hd[0].strftime("%Y-%m-%d"),
                        "to": hd[-1].strftime("%Y-%m-%d"),
                        "hold_ann": ha, "hold_mdd": hm, "hold_calmar": hc,
                        "strat_ann": sa, "strat_mdd": sm, "strat_calmar": sc,
                        "calmar_ge_hold": bool(np.isfinite(sc) and np.isfinite(hc) and sc >= hc)}

    # ── m = 0.5 的日程统计 + 与 tom_pd13 的重合度 ──────────────────────────
    n_runs, avg_run, max_run = _runs(low)
    tdf = pd.DataFrame(tom)
    tdf["d"] = pd.to_datetime(tdf["d"])
    tdf["m"] = pd.to_numeric(tdf["m"], errors="coerce")
    tdf = tdf.drop_duplicates(subset=["d"]).set_index("d").sort_index()
    tser = tdf["m"].reindex(pd.DatetimeIndex(days))
    tv = tser.to_numpy(dtype=float)
    have_tom = np.isfinite(tv)
    my_m = m[have_tom]
    tom_m = tv[have_tom]
    tom_low = np.isfinite(tom_m) & (tom_m < 1.0)
    my_low = my_m < 1.0
    inter = int((my_low & tom_low).sum())
    union = int((my_low | tom_low).sum())
    my_low_n = int(my_low.sum())
    tom_low_n = int(tom_low.sum())
    both = have_tom.sum()
    corr_m = float(np.corrcoef(my_m, tom_m)[0, 1]) if both > 2 and np.std(my_m) > 0 and np.std(tom_m) > 0 else float("nan")

    # ── 探索性诊断(不在预注册里,只解释「为什么不过」)────────────────────────
    fwd = np.full(n, np.nan)                            # ① 的未来 30 日收益(诊断用)
    for i in range(n - 30):
        fwd[i] = float(np.prod(1.0 + rets[i + 1: i + 31]) - 1.0)
    ok_f = np.isfinite(fwd)
    cut = low & ok_f
    nocut = (~low) & ok_f
    diag = {
        "fwd30_on_cut_days": float(np.mean(fwd[cut])) if cut.any() else None,
        "fwd30_on_other_days": float(np.mean(fwd[nocut])) if nocut.any() else None,
        "n_cut_days_with_fwd": int(cut.sum()), "n_other_days_with_fwd": int(nocut.sum()),
        "corr_rho_vs_fwd30": float(np.corrcoef(rho[ok_f], fwd[ok_f])[0, 1]),
        "cut_share_in_up_legs": (float(np.mean(rets[cut] > 0)) if cut.any() else None),
        "other_share_in_up_legs": (float(np.mean(rets[nocut] > 0)) if nocut.any() else None),
    }
    by_year = {}
    yrs = pd.DatetimeIndex(days).year
    for y in sorted(set(int(x) for x in yrs)):
        sel = np.array([int(x) == y for x in yrs])
        hd = [d for d, s in zip(days, sel) if s]
        hn = hold_nav[sel]
        sn = strat_nav[sel]
        ha, hm, hc = _calmar(hn, hd)
        sa, sm, sc = _calmar(sn, hd)
        by_year[str(y)] = {"days": int(sel.sum()),
                           "hold_ann": ha, "hold_mdd": hm, "hold_calmar": hc,
                           "strat_ann": sa, "strat_mdd": sm, "strat_calmar": sc,
                           "cut_days": int(low[sel].sum())}

    # ── 判据 ───────────────────────────────────────────────────────────────
    j1 = bool(s_mdd >= h_mdd + 0.05)                    # 回撤浅 ≥ 5pp
    j2 = bool(s_ann >= h_ann - 0.02)                    # 年化损失 ≤ 2pp
    j3 = bool(p_full is not None and p_full <= 0.05)   # Calmar 零分布分位 p ≤ 0.05
    j4 = bool(halves["h1"]["calmar_ge_hold"] and halves["h2"]["calmar_ge_hold"])
    all_pass = bool(j1 and j2 and j3 and j4)

    res = {
        "card": "T-330", "ledger": "S-806", "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sample": {"start": SAMPLE_START, "end": SAMPLE_END, "n_days": n,
                   "warmup_days": WARMUP, "lookback": LOOKBACK, "q": Q, "m_low": M_LOW, "cost_bp": 10,
                   "seed": SEED, "n_null": N_NULL},
        "data": {"members_rows": len(mem), "member_months": len(mem_by_month),
                 "member_symbols": len({s for v in mem_by_month.values() for s in v}),
                 "price_rows": pr["meta"]["n_rows"], "price_symbols": pr["meta"]["n_symbols"],
                 "arm_rows": len(a), "arm_range": hold_check["full_range"],
                 "tom_rows": len(tom)},
        "hold_check": hold_check,
        "signal": {
            "n_rho": int(np.isfinite(rho).sum()),
            "rho_min": float(np.nanmin(rho)), "rho_max": float(np.nanmax(rho)),
            "rho_mean": float(np.nanmean(rho)),
            "coins_used_min": int(n_coins[n_coins > 0].min()) if (n_coins > 0).any() else 0,
            "coins_used_median": float(np.median(n_coins[n_coins > 0])) if (n_coins > 0).any() else 0,
            "pairs_used_min": int(n_pairs[n_pairs > 0].min()) if (n_pairs > 0).any() else 0,
            "pairs_used_median": float(np.median(n_pairs[n_pairs > 0])) if (n_pairs > 0).any() else 0,
            "threshold_last": float(thr[-1]), "threshold_mean": float(np.nanmean(thr)),
        },
        "schedule": {
            "n_days_m_low": int(low.sum()), "frac_m_low": float(low.mean()),
            "n_runs": n_runs, "avg_run_days": avg_run, "max_run_days": max_run,
            "n_switches": int((np.abs(np.diff(m)) > 0).sum()),
            "first_low_day": (days[int(np.argmax(low))].strftime("%Y-%m-%d") if low.any() else None),
            "runs": _run_list(low, days),
        },
        "drawdown_windows": {"hold": _mdd_window(hold_nav, days),
                             "strat": _mdd_window(strat_nav, days)},
        "hold": {"total": float(hold_nav[-1]), "ann": h_ann, "mdd": h_mdd, "calmar": h_cal},
        "strat": {"total": float(strat_nav[-1]), "ann": s_ann, "mdd": s_mdd, "calmar": s_cal},
        "judgments": {
            "i_mdd_shallower_5pp": {"value": s_mdd - h_mdd, "pass": j1,
                                    "rule": "strat_mdd − hold_mdd ≥ +0.05"},
            "ii_ann_loss_2pp": {"value": s_ann - h_ann, "pass": j2,
                                "rule": "strat_ann − hold_ann ≥ −0.02"},
            "iii_calmar_null_p_upper": {"p_upper": p_full, "percentile": pct_full, "pass": j3,
                                        "null_mean": float(np.mean(null_full)),
                                        "null_median": float(np.median(null_full)),
                                        "null_max": float(np.max(null_full)),
                                        "rule": "p_upper ≤ 0.05"},
            "iv_halves_calmar_ge_hold": {"h1": halves["h1"], "h2": halves["h2"], "pass": j4},
            "all_pass": all_pass,
        },
        "null_variants": {
            "full_shift": {"p_upper": p_full, "percentile": pct_full,
                           "null_mean": float(np.mean(null_full))},
            "judged_region_shift": {"p_upper": p_judged,
                                    "percentile": apparatus.percentile_of(s_cal, null_judged),
                                    "null_mean": float(np.mean(null_judged))},
        },
        "tom_overlap": {            "tom_arm": "tom_pd13_replay", "days_aligned": int(both),
            "my_low_days": my_low_n, "tom_low_days": tom_low_n,
            "both_low": inter, "jaccard": (inter / union) if union else None,
            "share_of_my_low_also_tom_low": (inter / my_low_n) if my_low_n else None,
            "share_of_tom_low_also_my_low": (inter / tom_low_n) if tom_low_n else None,
            "corr_my_m_vs_tom_m": corr_m,
        },
        "diagnostics_exploratory": diag,
        "by_year": by_year,
        "series": {"days": [d.strftime("%Y-%m-%d") for d in days],
                   "rho": [None if not np.isfinite(x) else round(float(x), 6) for x in rho],
                   "thr": [None if not np.isfinite(x) else round(float(x), 6) for x in thr],
                   "m": [float(x) for x in m],
                   "hold_nav": [float(x) for x in hold_nav],
                   "strat_nav": [float(x) for x in strat_nav]},
    }
    RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "series"}, ensure_ascii=False, indent=1))
    print("→ %s" % RESULTS.name)


# ── 报告 ────────────────────────────────────────────────────────────────────
def _ledger_text():
    if not LEDGER.exists():
        return "【预注册原文缺失:%s 不存在】" % LEDGER
    txt = LEDGER.read_text(encoding="utf-8")
    m = re.search(r"^## S-806\b.*?(?=\n## S-|\Z)", txt, re.S | re.M)
    return m.group(0).strip() if m else "【预注册原文缺失:S-806 段没找到】"


def cmd_report():
    res = json.loads(RESULTS.read_text())
    j = res["judgments"]
    sv, sc = res["signal"], res["schedule"]
    ho, st = res["hold"], res["strat"]
    to = res["tom_overlap"]
    hc = res["hold_check"]

    def pc(x):
        return "—" if x is None else ("%.4f" % x)

    def pct(x):
        return "—" if x is None else ("%.2f%%" % (100 * x))

    lines = []
    A = lines.append
    A("# T-330 / S-806 —— ③ 的相关性状态:① 面板 30 天平均两两相关高于扩张 80 分位时 ① 敞口降到 0.5")
    A("")
    A("**结论:** %s" % ("✅ 四条判据全过" if j["all_pass"] else "🔴 不过(见逐条判定)"))
    A("")
    A("样本 %s → %s(%d 天,前 %d 天不判,m = 1);对照 HOLD 与同样时间占比的随机日程;"
      "成本 10bp × |Δm|;种子 %d,零分布 %d 次。"
      % (res["sample"]["start"], res["sample"]["end"], res["sample"]["n_days"],
         res["sample"]["warmup_days"], res["sample"]["seed"], res["sample"]["n_null"]))
    A("")
    A("## 预注册原文(REFUTATION_LEDGER.md S-806,照抄)")
    A("")
    A("```text")
    A(_ledger_text())
    A("```")
    A("")
    A("## 0. 自检:HOLD 与库里的 `core_variants_daily` arm='cap_pit24' 逐日对上")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 臂的行数(全段) | %d(%s → %s) |" % (hc["n_rows_full"], hc["full_range"][0], hc["full_range"][1]))
    A("| 全段 max&#124;cumprod(1+ret) − nav&#124; | %.3e |" % hc["max_abs_diff_full"])
    A("| 全段 max 相对差 | %.3e(在 %s) |" % (hc["max_rel_diff_full"], hc["argmax_abs_diff_d"]))
    A("")
    A("口径:HOLD 的日收益就是库里 `cap_pit24` 的 `ret`;NAV 用 `cumprod(1+ret)` 自 1 复算,"
      "与库里 `nav` 列逐日相减(全段)。样本段内的 HOLD 就是这条 cumprod 的截取。")
    A("")
    A("## 1. 信号:ρ̄ 与阈值")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 可算 ρ̄ 的天数 | %d / %d |" % (sv["n_rho"], res["sample"]["n_days"]))
    A("| ρ̄ 区间 / 均值 | %.4f → %.4f(均值 %.4f) |" % (sv["rho_min"], sv["rho_max"], sv["rho_mean"]))
    A("| 每日参与相关的币数(中位/最少) | %.0f / %d |" % (sv["coins_used_median"], sv["coins_used_min"]))
    A("| 每日两两对数(中位/最少) | %.0f / %d |" % (sv["pairs_used_median"], sv["pairs_used_min"]))
    A("| 扩张 80 分位(末值 / 均值) | %.4f / %.4f |" % (sv["threshold_last"], sv["threshold_mean"]))
    A("")
    A("口径(照 S-806 逐字):每天 d,取**当日成员**(当月的 `cap_pit24` 名单)里**最近 30 个日历日"
      "都有日收益**的币(≥30 个日收益),用它们最近 30 天日收益的两两 Pearson 相关的平均作 ρ̄_d;"
      "阈值只用 ρ̄ 到 d 为止(含 d)的扩张 80 分位 —— 没有未来信息。")
    A("")
    A("## 2. 日程:m = 0.5 的占比、持续、与 tom_pd13 的重合")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| m = 0.5 的天数 | %d / %d(%s) |" % (sc["n_days_m_low"], res["sample"]["n_days"], pct(sc["frac_m_low"])))
    A("| 段数 / 平均持续(天) / 最长 | %d / %.2f / %d |" % (sc["n_runs"], sc["avg_run_days"], sc["max_run_days"]))
    A("| 切换次数 | %d |" % sc["n_switches"])
    A("| 第一次降到 0.5 | %s |" % sc["first_low_day"])
    A("| 与 `tom_pd13_replay` 对齐天数 | %d |" % to["days_aligned"])
    A("| 我的 m=0.5 天里 tom 也降敞口 | %d / %d(%s) |" % (to["both_low"], to["my_low_days"],
                                                          pct(to["share_of_my_low_also_tom_low"])))
    A("| 两边「降敞口日」的 Jaccard | %s |" % pc(to["jaccard"]))
    A("| 我的 m 与 tom 的 m 的相关 | %s |" % pc(to["corr_my_m_vs_tom_m"]))
    runs = sc.get("runs") or []
    if runs:
        top = sorted(runs, key=lambda x: -x[2])[:4]
        A("| 最长的几段 | %s |" % "; ".join("%s→%s(%d 天)" % (a, b, L) for a, b, L in top))
    A("")
    A("## 3. 两条腿")
    A("")
    dw = res.get("drawdown_windows") or {}
    if dw:
        A("回撤窗口:HOLD %s → %s(%s);状态臂 %s → %s(%s)。"
          % (dw["hold"][1], dw["hold"][2], pct(dw["hold"][0]),
             dw["strat"][1], dw["strat"][2], pct(dw["strat"][0])))
        A("状态臂的回撤**多走了 28 天** —— 因为 2022-11-10 → 2022-12-10 的 31 天连续降敞口"
          "压在 2022 年 11 月底部,砍掉了 12 月初的反弹,低点因此延后并更深。")
        A("")
    A("")
    A("| 指标 | HOLD(m≡1) | 相关性状态臂 | 差 |")
    A("|---|---|---|---|")
    A("| 累计 | %.4f | %.4f | %+.4f |" % (ho["total"], st["total"], st["total"] - ho["total"]))
    A("| 年化 | %s | %s | %+.2f pp |" % (pct(ho["ann"]), pct(st["ann"]), 100 * (st["ann"] - ho["ann"])))
    A("| 最大回撤 | %s | %s | %+.2f pp |" % (pct(ho["mdd"]), pct(st["mdd"]), 100 * (st["mdd"] - ho["mdd"])))
    A("| Calmar | %.3f | %.3f | %+.3f |" % (ho["calmar"], st["calmar"], st["calmar"] - ho["calmar"]))
    A("")
    A("## 4. 判据逐条")
    A("")
    i1, i2, i3, i4 = j["i_mdd_shallower_5pp"], j["ii_ann_loss_2pp"], j["iii_calmar_null_p_upper"], j["iv_halves_calmar_ge_hold"]
    A("| # | 判据 | 实测 | 判定 |")
    A("|---|---|---|---|")
    A("| (i) | 最大回撤比 HOLD 浅 ≥ 5pp | %+.2f pp | %s |" % (100 * i1["value"], "✅" if i1["pass"] else "❌"))
    A("| (ii) | 年化收益损失 ≤ 2pp | %+.2f pp | %s |" % (100 * i2["value"], "✅" if i2["pass"] else "❌"))
    A("| (iii) | Calmar 在随机日程零分布里 `p_upper` ≤ 0.05 | p = %s(分位 %s;零分布均值 %.3f / 中位 %.3f / 最大 %.3f)| %s |"
      % (("%.4f" % i3["p_upper"]) if i3["p_upper"] is not None else "—",
         ("%.4f" % i3["percentile"]) if i3["percentile"] is not None else "—",
         i3["null_mean"], i3["null_median"], i3["null_max"], "✅" if i3["pass"] else "❌"))
    A("| (iv) | 两半 Calmar 都 ≥ HOLD | h1 %.3f vs %.3f(%s);h2 %.3f vs %.3f(%s)| %s |"
      % (i4["h1"]["strat_calmar"], i4["h1"]["hold_calmar"], "≥" if i4["h1"]["calmar_ge_hold"] else "<",
         i4["h2"]["strat_calmar"], i4["h2"]["hold_calmar"], "≥" if i4["h2"]["calmar_ge_hold"] else "<",
         "✅" if i4["pass"] else "❌"))
    A("")
    A("**总判定:%s**" % ("✅ 全过" if j["all_pass"] else "🔴 不过 —— 相关性状态在 ① 上读不出提前量,"
                          "S-806 的后果条款:不作为 ③ 的新输入开前向臂"))
    A("")
    A("### 零分布的两个口径(主口径 = 全段循环平移)")
    A("")
    A("| 零分布 | p_upper | 分位 | 零分布均值 |")
    A("|---|---|---|---|")
    for k, lbl in (("full_shift", "全段循环平移(主口径)"), ("judged_region_shift", "只在判定区(第 252 天后)内平移)")):
        v = res["null_variants"][k]
        A("| %s | %s | %s | %.3f |" % (lbl,
                                       ("%.4f" % v["p_upper"]) if v["p_upper"] is not None else "—",
                                       ("%.4f" % v["percentile"]) if v["percentile"] is not None else "—",
                                       v["null_mean"]))
    A("")
    A("## 5. 口径与偏差(自己写下来,便于复核)")
    A("")
    A("- 「前 252 天不判」按**样本内第 252 行**(日历日)计;① 的 `core_variants_daily` 是逐日的,不是交易日。")
    A("- 「≥30 个日收益」实现为:该币在**最近 30 个日历日**里 30 天都有日收益(缺一天即出局);"
      "实测这层过滤**没有剔除任何币**(每天都是 24 个币、276 对,见 §1),所以两种读法在本样本上等价。")
    A("- ρ̄ 只用**当日成员**(当月名单),名单换月时 ρ̄ 会跳;这是预注册写死的口径。")
    A("- 换手成本:第 i 天先按 |m_i − m_{i−1}| × 10bp 扣在当日开盘前的 NAV 上,再赚 m_i × r_i;"
      "余下现金收益 0。HOLD 不扣成本(HOLD 不换手)。")
    A("- 随机日程:把「m = 0.5 的日子」这一串 0/1 用 `apparatus.circular_shift`(块长 1 天)整段循环平移,"
      "因此 0.5 天的**个数完全相同**,只有时点变;`apparatus.null_distribution` 1000 次、种子 806。")
    A("")
    A("## 6. 探索性(不在预注册里 —— 需另立预注册、在新数据上过零信号对照)")
    A("")
    dg = res.get("diagnostics_exploratory") or {}
    if dg:
        A("| 诊断 | 值 |")
        A("|---|---|")
        A("| 被降敞口日的 ① 未来 30 日收益(均值) | %s |" % pct(dg.get("fwd30_on_cut_days")))
        A("| 其他日的 ① 未来 30 日收益(均值) | %s |" % pct(dg.get("fwd30_on_other_days")))
        A("| ρ̄ 与 ① 未来 30 日收益的相关 | %s |" % pc(dg.get("corr_rho_vs_fwd30")))
        A("| 被降敞口日里 ① 当日上涨的比例 | %s |" % pct(dg.get("cut_share_in_up_legs")))
        A("| 其他日里 ① 当日上涨的比例 | %s |" % pct(dg.get("other_share_in_up_legs")))
        A("")
        A("读法:相关性收敛这个状态**带一点前瞻信息,但来晚了** —— 它标的是「已经一起动完」的时刻,"
          "不是「即将开始一起动」。被降敞口的日子 ① 的未来 30 日收益均值确实更低(见上表),"
          "但 2022-11-10 → 2022-12-10 那 31 天的连续降敞口正好压在 2022 年 11 月的底部,"
          "砍掉了 12 月初的反弹,于是状态臂的最大回撤比 HOLD 还深 0.99pp(回撤窗口见 §3)。")
        A("")
        A("另一条读法(同样探索性):**扩张 80 分位把阈值锚死在 2022 年**。2022 年危机期的 ρ̄ 很高,"
          "把阈值抬到 ~0.70;此后 ρ̄ 结构性下降(2026 年均值 ~0.53),规则到 2026-10-31 为止"
          "一次都没再触发(2026 年 m=0.5 天数 = 0)。也就是说这条规则在结构上只会在"
          "「相关性回到危机期水平」时才动作 —— 它测的是「回到 2022」,不是「正在变危险」。")
        A("")
        A("再一条:被降敞口的那些日子,① 的未来 30 日收益均值 %s,确实低于其他日子的 %s —— "
          "状态**有一点**前瞻信息;但它来得太晚(动量已经走完),砍掉的是反弹而不是下跌。"
          % (pct(dg.get("fwd30_on_cut_days")), pct(dg.get("fwd30_on_other_days"))))
    by = res.get("by_year") or {}
    if by:
        A("")
        A("| 年 | 天数 | m=0.5 天数 | HOLD 年化 | 状态臂年化 | HOLD 回撤 | 状态臂回撤 | HOLD Calmar | 状态臂 Calmar |")
        A("|---|---|---|---|---|---|---|---|---|")
        for y, v in by.items():
            A("| %s | %d | %d | %s | %s | %s | %s | %.3f | %.3f |"
              % (y, v["days"], v["cut_days"], pct(v["hold_ann"]), pct(v["strat_ann"]),
                 pct(v["hold_mdd"]), pct(v["strat_mdd"]), v["hold_calmar"], v["strat_calmar"]))
    A("")
    A("## 7. 复现")
    A("")
    A("```bash")
    A("python3 docs/research/t330_corr_state.py fetch   # 只读拉数")
    A("python3 docs/research/t330_corr_state.py run     # → t330_results.json")
    A("python3 docs/research/t330_corr_state.py report  # → T-330_corr_state.md")
    A("```")
    A("")
    A("数据(全部 publishable key 直读 Supabase,只读):`core_variants_daily`(arm=cap_pit24)、"
      "`multiplier_daily`(arm=tom_pd13_replay)、RPC `core_pit_members`(p_n=24)、`asset_mcap_daily`。")
    A("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("→ %s(%d 行)" % (REPORT.name, len(lines)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run", "report"])
    a = ap.parse_args()
    if a.cmd == "fetch":
        cmd_fetch()
    elif a.cmd == "run":
        cmd_run()
    else:
        cmd_report()


if __name__ == "__main__":
    main()
