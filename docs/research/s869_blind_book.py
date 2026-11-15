#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-405 — S-869「状态取长处」组合的盲复算(纸面前向账 T-395 的前置)。

规格全部来自卡 tasks/T-405.json 的 check(台账 S-869 五条判据 + 「S-869 / S-870 更正(算前)」
① + S-870 的做法 + S-871 的 v2 + 「S-871 补」的缩放上限 + 「S-877 复核结果」的第二轴),
**只按文字从零写**,不读 docs/research/s869_strategy_state.py / s877_axis_mining.py /
s871_results.json / s877_results*.json;台账里这几条的「结果」段也不看。

三本:
  A = T × L(抽/注)     —— s866_cells.json 的两个轴
  B = T × 谁在领        —— 第二轴 = state_daily(entity=panel, feature=style_rel_majors_30d)
  C = 只用 T 两格        —— 同样做法

盲:本脚本只做算;落盘 s869_blind_book_results.json 之后才由另一个脚本对账。
"""
from __future__ import annotations

import bisect
import datetime as dt
import importlib.util
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PAGE = 1000

# ── 口径常量(全部写死,便于对账时指出分歧)────────────────────────────
DAYS_PER_YEAR = 365.0
SEG_GAP_DAYS = 5
MIN_SEGS, MIN_DAYS = 5, 120
MIN_SHARPE = 0.5
MIN_PAYOFF = 2.0
STATE_HISTORY_DAYS = 730
SIG_LOOKBACK = 90
SIG_MIN_OBS = 60
TARGET_VOL = 0.10
MAX_SCALE = 3.0
LEAD_MIN_HISTORY = 365
LAST_MONTH = "2026-11"
SEG_FROM = "2023-02-01"


def _load_apparatus():
    path = os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py")
    spec = importlib.util.spec_from_file_location("cc_apparatus", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cc_apparatus"] = mod
    spec.loader.exec_module(mod)
    return mod


AP = _load_apparatus()


# ── Supabase(只读)───────────────────────────────────────────────────────
def fetch_supabase(table: str, params: dict) -> list[dict]:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    out: list[dict] = []
    start = 0
    while True:
        p = dict(params)
        p["limit"] = str(PAGE)
        p["offset"] = str(start)
        url = base + "/rest/v1/" + table + "?" + urllib.parse.urlencode(p)
        req = urllib.request.Request(
            url,
            headers={"apikey": key, "Authorization": "Bearer " + key, "Prefer": "count=exact"},
        )
        with urllib.request.urlopen(req, timeout=180) as fh:
            rows = json.loads(fh.read().decode())
        if not rows:
            break
        out.extend(rows)
        if len(rows) < PAGE:
            break
        start += PAGE
    return out


# ── 补齐 / 收益 ────────────────────────────────────────────────────────
def flat_series(dates: list[str], values: list[float]) -> dict:
    """稀疏序列补到日历:首末日之间缺的日子按不变补齐(向后取最近一根,不许用未来值)。"""
    if not dates:
        return {}
    out: dict[str, float] = {}
    last = None
    day = dt.date.fromisoformat(dates[0])
    end = dt.date.fromisoformat(dates[-1])
    while day <= end:
        ds = day.isoformat()
        p = AP.price_on_or_after(dates, values, ds, max_gap_days=0)
        if p is not None:
            last = float(p)
        if last is not None:
            out[ds] = last
        day += dt.timedelta(days=1)
    return out


def check_no_lookahead(flat: dict, raw_dates: list[str], raw_vals: list[float]) -> float:
    raw = dict(zip(raw_dates, raw_vals))
    worst = 0.0
    last = None
    for d in sorted(flat):
        if d in raw:
            last = raw[d]
        if last is None:
            continue
        worst = max(worst, abs(flat[d] - last))
    return worst


def build_returns(labeled: list[str], flat: dict, cash_map: dict, deduct: bool) -> dict:
    """D 日收盘的状态 ⇒ D→D+1 的收益(标签落在 D 上)。"""
    out: dict[str, float] = {}
    for d in labeled:
        a = flat.get(d)
        if a is None:
            continue
        nxt = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
        b = flat.get(nxt)
        if b is None:
            continue
        r = AP.long_return(a, b)
        if r is None:
            continue
        if deduct:
            r = r - float(cash_map.get(d, 0.0))
        out[d] = float(r)
    return out


def segments_of(days: list[str]) -> list[list[str]]:
    segs: list[list[str]] = []
    cur: list[str] = []
    for d in days:
        if cur and (dt.date.fromisoformat(d) - dt.date.fromisoformat(cur[-1])).days <= SEG_GAP_DAYS:
            cur.append(d)
        else:
            if cur:
                segs.append(cur)
            cur = [d]
    if cur:
        segs.append(cur)
    return segs


def _ann_excess(r: np.ndarray) -> float:
    """年化超额(几何):∏(1+r)^(365/n) − 1;用对数和避免溢出。"""
    n = len(r)
    if n == 0:
        return None
    lr = np.log1p(r)
    s = float(lr.sum())
    if s / n * DAYS_PER_YEAR > 700:
        return float("inf")
    return float(math.exp(s / n * DAYS_PER_YEAR) - 1.0)


# ── 长处五条 ───────────────────────────────────────────────────────────
def cell_stats(days: list[str], rets: dict, out_days: list[str], out_rets: dict) -> dict:
    """一条策略在一个格子上的五条判据。"""
    n = len(days)
    if n == 0:
        return {"days": 0, "segments": 0, "mean": None, "vol": None, "mean_vol": None,
                "ann_excess": None, "payoff": None, "payoff_no_neg_seg": False,
                "n_pos_segs": 0, "n_neg_segs": 0, "mean_after_best": None, "out_mean": None,
                "best_seg": None, "worst_seg": None, "crit": {}, "all_pass": False}
    segs = segments_of(days)
    r = np.array([rets[d] for d in days], dtype=float)
    seg_rets = []
    for sg in segs:
        seg_rets.append(float(np.prod(1.0 + np.array([rets[x] for x in sg], dtype=float)) - 1.0))
    mean = float(r.mean())
    vol = float(r.std(ddof=1)) if n > 1 else 0.0
    mv = (mean * DAYS_PER_YEAR) / (vol * math.sqrt(DAYS_PER_YEAR)) if vol > 0 else None
    pos_segs = [x for x in seg_rets if x > 0]
    neg_segs = [x for x in seg_rets if x < 0]
    if not neg_segs:
        payoff = float("inf")          # 没有为负的段 ⇒ 算过
    elif not pos_segs:
        payoff = 0.0                   # 没有为正的段 ⇒ 不过
    else:
        payoff = (sum(pos_segs) / len(pos_segs)) / abs(sum(neg_segs) / len(neg_segs))
    best_seg_days = segs[int(np.argmax(seg_rets))] if segs else []
    best_set = set(best_seg_days)
    rest = [d for d in days if d not in best_set]
    rr = np.array([rets[d] for d in rest], dtype=float) if rest else np.array([], dtype=float)
    mean_after = float(rr.mean()) if rest and rr.size else None
    out_mean = None
    if out_days:
        out_mean = float(np.mean([out_rets[d] for d in out_days]))
    c1 = bool(len(segs) >= MIN_SEGS and n >= MIN_DAYS)
    c2 = bool(mean * DAYS_PER_YEAR > 0 and mv is not None and mv >= MIN_SHARPE)
    c3 = bool(payoff >= MIN_PAYOFF)
    c4 = bool(mean_after is not None and mean_after > 0)
    c5 = bool(out_mean is not None and mean > out_mean)
    return {
        "days": n, "segments": len(segs), "mean": mean, "vol": vol, "mean_vol": mv,
        "ann_excess": _ann_excess(r),
        "payoff": None if payoff == float("inf") else payoff,
        "payoff_no_neg_seg": bool(payoff == float("inf")),
        "n_pos_segs": len(pos_segs), "n_neg_segs": len(neg_segs),
        "mean_after_best": mean_after, "out_mean": out_mean,
        "best_seg": max(seg_rets) if seg_rets else None,
        "worst_seg": min(seg_rets) if seg_rets else None,
        "crit": {"c1_seg5_days120": c1, "c2_ann_gt0_sharpe_ge05": c2, "c3_payoff_ge2": c3,
                 "c4_after_best_gt0": c4, "c5_in_gt_out": c5},
        "all_pass": bool(c1 and c2 and c3 and c4 and c5),
    }


# ── 主流程 ─────────────────────────────────────────────────────────────
def main() -> None:
    # 1) 状态标签(T / L)--------------------------------------------------
    cells_json = json.load(open(os.path.join(HERE, "s866_cells.json")))
    daily = cells_json["daily"]
    labeled = sorted(daily.keys())
    # 自检:T 标签必须等于 dist_200 < 0 ⇒ 线下,否则线上
    for d in labeled:
        lab = daily[d]
        want = "线下" if float(lab["dist_200"]) < 0 else "线上"
        assert lab["T"] == want, f"{d} T={lab['T']} 与 dist_200={lab['dist_200']} 不符"
    print(f"自检 1 ✓ T 标签与 dist_200 一致({len(labeled)} 天 "
          f"{labeled[0]}→{labeled[-1]})")

    # 2) 第二轴「谁在领」-------------------------------------------------
    srows = fetch_supabase(
        "state_daily",
        {"select": "d,value", "entity": "eq.panel", "feature": "eq.style_rel_majors_30d",
         "order": "d.asc"},
    )
    svals = [(str(r["d"])[:10], r["value"]) for r in srows if r.get("value") is not None]
    svals.sort()
    lead: dict[str, str] = {}
    run_sum = 0.0
    cnt = 0
    for d, v in svals:
        if cnt >= LEAD_MIN_HISTORY:
            lead[d] = "主流领" if float(v) > run_sum / cnt else "二线领"
        run_sum += float(v)
        cnt += 1
    print(f"自检 2 ✓ 「谁在领」{len(svals)} 个值 / {len(lead)} 天有状态 "
          f"(首个有状态日 {min(lead) if lead else None})")

    # 3) 面板 26 条 -------------------------------------------------------
    legs = pd.read_csv(os.path.join(HERE, "t348_r4_legs.csv"))
    legs["d"] = legs["d"].astype(str).str[:10]
    t342 = pd.read_csv(os.path.join(HERE, "t342_daily.csv"))
    t342["d"] = t342["date"].astype(str).str[:10]
    rv2 = pd.read_csv(os.path.join(HERE, "t348_r3_rv2_curve.csv"))
    rv2["d"] = rv2["d"].astype(str).str[:10]
    fam = pd.read_csv(os.path.join(HERE, "t348_r3_families.csv"))
    fam["d"] = fam["d"].astype(str).str[:10]
    extra = pd.read_csv(os.path.join(HERE, "s869_extra_panel_a.csv"))
    extra["d"] = extra["d"].astype(str).str[:10]
    extra_meta = json.load(open(os.path.join(HERE, "s869_extra_panel_a.meta.json")))
    funded_of = {e["family"]: int(e.get("funded") or 0) for e in extra_meta["entries"]}

    cash_map = {r["d"]: (0.0 if r["cash_daily_rate"] is None or pd.isna(r["cash_daily_rate"])
                         else float(r["cash_daily_rate"]))
                for _, r in legs.iterrows()}

    strategies: list[tuple] = []   # (name, dates, values, deduct_cash)

    def add(name, mp, deduct):
        ds = sorted(x for x in mp if mp[x] is not None)
        vs = [mp[x] for x in ds]
        strategies.append((name, ds, vs, deduct))

    add("核心", {r["d"]: (None if pd.isna(r["core_nav_1_cap_pit24"]) else float(r["core_nav_1_cap_pit24"]))
                 for _, r in t342.iterrows()}, True)
    add("X1V", {r["d"]: (None if pd.isna(r["crypto_nav"]) else float(r["crypto_nav"]))
                for _, r in legs.iterrows()}, True)
    add("R-v2", {r["d"]: float(r["nav"]) for _, r in rv2.iterrows()}, False)
    add("ACWI", {r["d"]: (None if pd.isna(r["equity_close"]) else float(r["equity_close"]))
                 for _, r in legs.iterrows()}, True)
    add("XAUUSD", {r["d"]: (None if pd.isna(r["gold_close"]) else float(r["gold_close"]))
                   for _, r in legs.iterrows()}, True)
    for fn in ["S642", "S736_fixed", "S736_published", "S808", "S810",
               "S681_H2", "S681_H3", "S681_H4"]:
        sub = fam[fam["family"] == fn]
        add(fn, {r["d"]: float(r["nav"]) for _, r in sub.iterrows()}, False)
    for fn in sorted(funded_of):
        sub = extra[extra["family"] == fn]
        add(fn, {r["d"]: float(r["nav"]) for _, r in sub.iterrows()}, bool(funded_of[fn]))

    assert len(strategies) == 26, f"策略数 {len(strategies)} ≠ 26"
    print(f"自检 3 ✓ 面板 26 条(13 + 13)")

    # 4) 逐策略收益 -------------------------------------------------------
    strat_rets: dict[str, dict] = {}
    coverage: dict[str, dict] = {}
    for name, ds, vs, deduct in strategies:
        flat = flat_series(ds, vs)
        leak = check_no_lookahead(flat, ds, vs)
        assert leak <= 1e-12, f"{name} 补齐含未来信息({leak})"
        rets = build_returns(labeled, flat, cash_map, deduct)
        assert rets, f"{name} 没有有效日收益"
        strat_rets[name] = rets
        coverage[name] = {
            "raw_days": len(ds), "raw_first": ds[0], "raw_last": ds[-1],
            "return_days": len(rets), "first": min(rets), "last": max(rets),
            "deduct_cash": deduct, "flat_lookahead_max_diff": leak,
        }
    print(f"自检 4 ✓ 26 条策略的补齐都不含未来信息(最大差 0)")
    keys_by_name = {n: list(strat_rets[n].keys()) for n in strat_rets}

    # 5) 三本书的格子定义 --------------------------------------------------
    t_axis = {d: daily[d]["T"] for d in labeled}
    l_axis = {d: daily[d]["L"] for d in labeled}
    universe_A = [d for d in labeled if d in t_axis and d in l_axis]
    universe_B = [d for d in labeled if d in t_axis and d in lead]
    universe_C = [d for d in labeled if d in t_axis]

    BOOKS = {
        "A_T_x_L": {
            "universe": universe_A,
            "cells": {"线上·注": lambda d: (t_axis[d] == "线上" and l_axis[d] == "注"),
                      "线上·抽": lambda d: (t_axis[d] == "线上" and l_axis[d] == "抽"),
                      "线下·注": lambda d: (t_axis[d] == "线下" and l_axis[d] == "注"),
                      "线下·抽": lambda d: (t_axis[d] == "线下" and l_axis[d] == "抽")},
        },
        "B_T_x_lead": {
            "universe": universe_B,
            "cells": {"线上·主流领": lambda d: (t_axis[d] == "线上" and lead[d] == "主流领"),
                      "线上·二线领": lambda d: (t_axis[d] == "线上" and lead[d] == "二线领"),
                      "线下·主流领": lambda d: (t_axis[d] == "线下" and lead[d] == "主流领"),
                      "线下·二线领": lambda d: (t_axis[d] == "线下" and lead[d] == "二线领")},
        },
        "C_T_only": {
            "universe": universe_C,
            "cells": {"线上": lambda d: t_axis[d] == "线上",
                      "线下": lambda d: t_axis[d] == "线下"},
        },
    }

    # 6) 逐月向前 ---------------------------------------------------------
    out: dict[str, dict] = {}
    for bname, bspec in BOOKS.items():
        uni = bspec["universe"]
        uni_set = set(uni)
        cellfns = bspec["cells"]
        state_first = uni[0]
        d0 = dt.date.fromisoformat(state_first)
        m = dt.date(d0.year, d0.month, 1)
        while (m - d0).days < STATE_HISTORY_DAYS:
            m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        first_m = m.isoformat()

        # 每策略 × 每格:状态内/外的日子(与月份无关,只需按月取前缀)
        strat_cells: dict[str, dict] = {}
        for name, _ds, _vs, _de in strategies:
            rets = strat_rets[name]
            days_all = [d for d in uni if d in rets]
            per_cell = {}
            for cname, cfn in cellfns.items():
                in_d = [d for d in days_all if cfn(d)]
                out_d = [d for d in days_all if not cfn(d)]
                per_cell[cname] = (in_d, out_d)
            strat_cells[name] = per_cell

        # 逐月
        book_days: list[str] = []
        book_rets: list[float] = []
        monthly: list[dict] = []
        held_counter: dict[str, dict[str, int]] = {c: defaultdict(int) for c in cellfns}
        last_roster: dict[str, list] = {}
        mcur = dt.date.fromisoformat(first_m)
        # 组合的日历终点:所有策略能实现收益的最后一天
        last_real = max((dt.date.fromisoformat(max(strat_rets[n])) + dt.timedelta(days=1))
                        for n, _ds, _vs, _de in strategies)
        while mcur.isoformat() <= last_real.isoformat():
            mstr = mcur.isoformat()
            cutoff = (mcur - dt.timedelta(days=2)).isoformat()   # D+1 < m  ⇒  D ≤ m−2
            roster: dict[str, list] = {}
            cell_stats_store: dict[str, dict] = {}
            for cname in cellfns:
                passed = []
                for name, _ds, _vs, _de in strategies:
                    rets = strat_rets[name]
                    in_d, out_d = strat_cells[name][cname]
                    i = bisect.bisect_right(in_d, cutoff)
                    pre_in = in_d[:i]
                    j = bisect.bisect_right(out_d, cutoff)
                    pre_out = out_d[:j]
                    st = cell_stats(pre_in, rets, pre_out, rets)
                    cell_stats_store.setdefault(cname, {})[name] = {
                        "days": st["days"], "segments": st["segments"], "mean": st["mean"],
                        "mean_vol": st.get("mean_vol"), "payoff": st.get("payoff"),
                        "crit": st.get("crit"), "all_pass": st["all_pass"],
                    }
                    if st["all_pass"]:
                        passed.append(name)
                roster[cname] = passed
            monthly.append({"month": mstr, "roster": {c: list(v) for c, v in roster.items()},
                            "n_candidates": {c: len(v) for c, v in cell_stats_store.items()}})

            # 月内逐日
            mnext = (mcur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            d = mcur
            while d < mnext:
                if d > last_real:
                    break
                ds = d.isoformat()
                prev = (d - dt.timedelta(days=1)).isoformat()
                cell_name = None
                for cname, cfn in cellfns.items():
                    if prev in uni_set and cfn(prev):
                        cell_name = cname
                        break
                legs_r = []
                if cell_name:
                    for name in roster.get(cell_name, []):
                        rets = strat_rets[name]
                        if prev not in rets:
                            continue
                        keys = keys_by_name[name]
                        lo = (d - dt.timedelta(days=SIG_LOOKBACK)).isoformat()
                        i = bisect.bisect_right(keys, (d - dt.timedelta(days=1)).isoformat())
                        j = bisect.bisect_left(keys, lo)
                        obs = [rets[k] for k in keys[j:i]]
                        if len(obs) < SIG_MIN_OBS:
                            continue
                        sig = float(np.std(np.array(obs, dtype=float), ddof=1))
                        if not (sig > 0):
                            continue
                        scale = min(MAX_SCALE, (TARGET_VOL / math.sqrt(DAYS_PER_YEAR)) / sig)
                        legs_r.append(rets[prev] * scale)
                        held_counter[cell_name][name] += 1
                if legs_r:
                    book_days.append(ds)
                    book_rets.append(float(np.mean(legs_r)))
                else:
                    book_days.append(ds)
                    book_rets.append(0.0)
                d += dt.timedelta(days=1)
            if mstr.startswith(LAST_MONTH):
                last_roster = {c: list(v) for c, v in roster.items()}
            mcur = mnext

        book_days, book_rets = book_days[:len(book_days)], book_rets[:len(book_rets)]
        out[bname] = summarize(bname, first_m, book_days, book_rets, cellfns, held_counter,
                               last_roster, monthly, state_first)
        print(f"  {bname}: {first_m} → {book_days[-1] if book_days else None} "
              f"n={len(book_days)} 均值/波动={out[bname]['mean_vol']}")

    res = {
        "meta": {
            "task": "T-405",
            "kind": "blind_recompute_book",
            "ledger": "S-869 五条判据 + S-870 做法 + S-871 v2 + S-871 补缩放上限 + S-877 第二轴",
            "generated_by": "docs/research/s869_blind_book.py",
            "blind": "未读 s869_strategy_state.py / s877_axis_mining.py / s871_results.json / s877_results*.json",
            "panel": "T-391 的 13 条 + s869_extra_panel_a.csv 的 13 条 = 26",
            "conventions": {
                "state_universe": "s866_cells.json 的逐日标签日;T/L 轴全有;B 书另需 style_rel_majors_30d 有状态",
                "return": "D 日收盘的状态 ⇒ D→D+1 的收益(标签落在 D);apparatus.long_return",
                "flat_fill": "稀疏序列首末日之间按不变补齐;apparatus.price_on_or_after(max_gap_days=0)",
                "cash": "funded=1 的策略扣 t348_r4_legs.csv 的 cash_daily_rate(D);funded=0 不扣",
                "selection": "每月第一天 m:只用 D+1 < m 的收益(= D ≤ m−2);状态历史满 730 天才开始",
                "criteria": "⑴≥5段且≥120天 ⑵状态内日均×365>0 且 均值/波动≥0.5 ⑶盈亏比≥2.0 "
                            "⑷去掉最高段后状态内日均>0 ⑸状态内日均>状态外日均",
                "holding": "每天 d 看 d−1 的状态;等权平均该格名单策略的缩放后收益;"
                           "缩放 = 当天收益 × min(3, (0.10/√365)/σ),σ=该策略此前 90 天日收益标准差"
                           "(≥60 观测、σ>0);一个都没有 ⇒ 当天收益 0",
                "annualization": "mean_vol = (日均×365)/(日标准差×√365);日标准差用 ddof=1",
                "lead_axis": "state_daily(entity=panel, feature=style_rel_majors_30d):当天值 > 严格更早全部值的均值"
                             "且更早的非空值 ≥365 ⇒ 主流领,否则二线领",
                "days_per_year": DAYS_PER_YEAR, "seg_gap_days": SEG_GAP_DAYS,
                "state_history_days": STATE_HISTORY_DAYS, "sig_lookback": SIG_LOOKBACK,
                "sig_min_obs": SIG_MIN_OBS, "target_vol": TARGET_VOL, "max_scale": MAX_SCALE,
            },
            "labeled_days": len(labeled),
            "coverage": coverage,
            "lead_state_days": len(lead),
        },
        "books": out,
    }
    out_path = os.path.join(HERE, "s869_blind_book_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"✓ 落盘 {out_path}")


def longest_underwater(days: list[str], rets: list[float]) -> tuple:
    cum = 1.0
    peak = 1.0
    run = 0
    best = 0
    best_end = None
    for ds, r in zip(days, rets):
        cum *= (1.0 + r)
        if cum >= peak:
            peak = cum
            run = 0
        else:
            run += 1
            if run > best:
                best = run
                best_end = ds
    return best, best_end


def summarize(bname, first_m, days, rets, cellfns, held_counter, last_roster, monthly, state_first):
    r = np.array(rets, dtype=float)
    n = len(r)
    mean = float(r.mean()) if n else None
    vol = float(r.std(ddof=1)) if n > 1 else 0.0
    mv = (mean * DAYS_PER_YEAR) / (vol * math.sqrt(DAYS_PER_YEAR)) if (mean is not None and vol > 0) else None
    uw, uw_end = longest_underwater(days, rets)
    cum = float(np.prod(1.0 + r)) if n else None
    seg_days = [(d, x) for d, x in zip(days, rets) if d >= SEG_FROM]
    if seg_days:
        sr = np.array([x for _d, x in seg_days], dtype=float)
        smean = float(sr.mean())
        svol = float(sr.std(ddof=1)) if len(sr) > 1 else 0.0
        smv = (smean * DAYS_PER_YEAR) / (svol * math.sqrt(DAYS_PER_YEAR)) if svol > 0 else None
        seg_stats = {"start": seg_days[0][0], "end": seg_days[-1][0], "n_days": len(sr),
                     "mean": smean, "vol": svol, "mean_vol": smv,
                     "total_return": float(np.prod(1.0 + sr) - 1.0)}
    else:
        seg_stats = None
    per_cell = {}
    for c in cellfns:
        cnt = held_counter.get(c, {})
        top = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        per_cell[c] = {
            "held_days_top5": [{"strategy": k, "days": v} for k, v in top],
            "roster_last_month": last_roster.get(c, []),
            "n_held_days": sum(cnt.values()),
        }
    return {
        "book": bname,
        "state_first_day": state_first,
        "first_month": first_m,
        "start": days[0] if days else None,
        "end": days[-1] if days else None,
        "n_days": n,
        "mean_daily": mean,
        "vol_daily": vol,
        "mean_vol": mv,
        "total_return": cum,
        "longest_underwater_days": uw,
        "longest_underwater_end": uw_end,
        "from_2023_02_01": seg_stats,
        "cells": per_cell,
        "monthly_rosters": monthly,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        rows = fetch_supabase(
            "state_daily",
            {"select": "*", "entity": "eq.panel", "feature": "eq.style_rel_majors_30d", "order": "d.asc"},
        )
        print("rows:", len(rows))
        if rows:
            print("cols:", sorted(rows[0].keys()))
            dates = sorted(str(r.get("d"))[:10] for r in rows if r.get("d"))
            print("date range:", dates[0], dates[-1], "unique:", len(set(dates)))
    elif len(sys.argv) > 1 and sys.argv[1] == "probe2":
        rows = fetch_supabase("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                                              "order": "feature.asc,d.asc"})
        byfeat = defaultdict(list)
        for r in rows:
            if r.get("value") is not None:
                byfeat[r["feature"]].append((str(r["d"])[:10], float(r["value"])))
        for f in sorted(byfeat):
            v = byfeat[f]
            print(f"{f:34s} n={len(v):5d} last={v[-1][0]} {v[-1][1]:+.6f}")
        px = fetch_supabase("ohlcv_daily", {"select": "*", "symbol": "eq.BTC",
                                            "order": "trade_date.desc", "limit": "3"})
        print("ohlcv cols:", sorted(px[0].keys()) if px else "none")
        print("BTC tail:", px[:2])
    else:
        main()
