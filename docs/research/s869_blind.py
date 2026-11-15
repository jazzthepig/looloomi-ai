#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-391 — S-869 的盲复算:13 条策略 × 12 个状态,只按台账预注册的文字从零写。

台账(REFUTATION_LEDGER.md,S-869 + 「S-869 / S-870 更正(算前)」①)是**全部规格**:
  · 状态:只用 `docs/research/s866_cells.json` 的逐日标签(R/L/W/T)。第一层 = 单轴 8 个半状态;
          第二层 = 趋势 × 边际流动性 4 个。D 日收盘的状态配 D+1 的收益。
  · 策略(13):核心(PIT24)· X1V 加密腿 · R-v2 票 · 股(ACWI)· 金 · 坟场 8 族。
  · 更正 ①:只有占用本金的四条(核心、X1V、股、金)扣现金利率;叠加类(R-v2、坟场 8 族)不扣。
  · 稀疏的净值在首末日之间按不变补齐。
  · 判据五条:⑴ ≥5 段且 ≥120 天 ⑵ 状态内年化超额 >0 且 均值/波动 ≥0.5 ⑶ ≥60% 的段为正
    ⑷ 去掉最好一段后状态内均值仍 >0 ⑸ 状态内均值 > 状态外均值。

**盲**:本脚本不读 `docs/research/s869_strategy_state.py` 与 `s869_results.json`(对账那一步才读,
由另一个脚本 `s869_blind_compare.py` 做)。取价 / 盈亏走 `src/data/evaluation/apparatus.py`。

本脚本只做表:不做组合、不做平移对照(卡 T-391 的范围)。
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _load_apparatus():
    path = os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py")
    spec = importlib.util.spec_from_file_location("cc_apparatus", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cc_apparatus"] = mod
    spec.loader.exec_module(mod)
    return mod


AP = _load_apparatus()

# ── 口径常量(全部写死在这里,便于对账时指出分歧)────────────────────────────
DAYS_PER_YEAR = 365.0        # 与 t348_graveyard.metrics 的 vol_ann 一致(√365)
SEG_GAP_DAYS = 5             # 段:同格内相邻两天间隔 ≤ 5 天并成一段(S-866 已盲复算过)
MIN_SEGS, MIN_DAYS = 5, 120  # 判据 ⑴
MIN_SHARPE = 0.5             # 判据 ⑵
MIN_POS_SEG_FRAC = 0.6       # 判据 ⑶

# ── 状态定义 ────────────────────────────────────────────────────────────────
# 第一层:单轴 8 个半状态;(轴, 值)。第二层:趋势 × 边际流动性 4 个。
LAYER1 = [
    ("R升", ("R", "升")), ("R降", ("R", "降")),
    ("L注", ("L", "注")), ("L抽", ("L", "抽")),
    ("W好", ("W", "好")), ("W坏", ("W", "坏")),
    ("T线上", ("T", "线上")), ("T线下", ("T", "线下")),
]
LAYER2 = [
    ("线上·注", (("T", "线上"), ("L", "注"))),
    ("线下·注", (("T", "线下"), ("L", "注"))),
    ("线下·抽", (("T", "线下"), ("L", "抽"))),
    ("线上·抽", (("T", "线上"), ("L", "抽"))),
]
STATES = LAYER1 + LAYER2


def in_state(daily: dict, d: str, spec) -> bool:
    """spec = (轴, 值) 或 ((轴, 值), ...) —— 第二层是两组。"""
    lab = daily.get(d)
    if lab is None:
        return False
    pairs = spec if (isinstance(spec[0], tuple)) else (spec,)
    return all(lab.get(ax) == val for ax, val in pairs)


# ── 取数 ────────────────────────────────────────────────────────────────────
def load_inputs():
    cells = json.load(open(os.path.join(HERE, "s866_cells.json")))
    daily = cells["daily"]
    legs = pd.read_csv(os.path.join(HERE, "t348_r4_legs.csv"))
    legs["d"] = legs["d"].astype(str).str[:10]
    t342 = pd.read_csv(os.path.join(HERE, "t342_daily.csv"))
    t342["d"] = t342["date"].astype(str).str[:10]
    rv2 = pd.read_csv(os.path.join(HERE, "t348_r3_rv2_curve.csv"))
    rv2["d"] = rv2["d"].astype(str).str[:10]
    fam = pd.read_csv(os.path.join(HERE, "t348_r3_families.csv"))
    fam["d"] = fam["d"].astype(str).str[:10]
    return daily, legs, t342, rv2, fam


def flat_series(dates: list[str], values: list[float]) -> dict[str, float]:
    """稀疏序列补到日历:区间内缺的日子按不变补齐(向后取最近一根)。

    取价走 apparatus.price_on_or_after(max_gap_days=0):只认当天那根,拿不到就是拿不到
    (10-14 那个坑:早于第一根日线时不能拿最新收盘顶替)。补齐只向后看,不取未来。
    """
    if not dates:
        return {}
    d0, d1 = dates[0], dates[-1]
    out: dict[str, float] = {}
    last: float | None = None
    day = dt.date.fromisoformat(d0)
    end = dt.date.fromisoformat(d1)
    while day <= end:
        ds = day.isoformat()
        p = AP.price_on_or_after(dates, values, ds, max_gap_days=0)
        if p is not None:
            last = float(p)
        if last is not None:
            out[ds] = last
        day += dt.timedelta(days=1)
    return out


def check_no_lookahead(flat: dict[str, float], raw_dates: list[str], raw_vals: list[float]) -> float:
    """自检:补齐后的每一天的值,必须等于「当天或之前最近一根」的值(不许含未来信息)。"""
    raw = dict(zip(raw_dates, raw_vals))
    worst = 0.0
    last = None
    for d in sorted(flat):
        if d in raw:
            last = raw[d]
        if last is None:
            continue
        v = flat[d]
        if v is None:
            continue
        worst = max(worst, abs(v - last))
    return worst


def build_strategy_returns(daily, labeled, flat, cash_map, deduct_cash):
    """D 日收盘的状态 ⇒ D→D+1 的收益(D+1 = 下一个日历日)。返回 {D: 超额收益}。"""
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
        if deduct_cash:
            r = r - float(cash_map.get(d, 0.0))
        out[d] = float(r)
    return out


def segments_of(days: list[str]) -> list[list[str]]:
    """同一状态内相邻两天间隔 ≤ 5 天算同一段(S-866 的划分,已与生产的格子逐项相同)。"""
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


def stats_of(days: list[str], rets: dict[str, float]) -> dict:
    """一组日子上的统计:段数、几何年化、均值/波动、为正的段占比等。"""
    n = len(days)
    if n == 0:
        return {"days": 0, "segments": 0, "ann_excess": None, "mean": None, "vol": None,
                "mean_vol": None, "pos_seg_frac": None, "worst_seg": None, "best_seg": None}
    segs = segments_of(days)
    r = np.array([rets[d] for d in days], dtype=float)
    seg_rets = []
    for s in segs:
        seg_rets.append(float(np.prod(1.0 + np.array([rets[x] for x in s], dtype=float)) - 1.0))
    ann = float(np.prod(1.0 + r) ** (DAYS_PER_YEAR / n) - 1.0)
    mean = float(r.mean())
    vol = float(r.std(ddof=1)) if n > 1 else 0.0
    mv = (mean * DAYS_PER_YEAR) / (vol * math.sqrt(DAYS_PER_YEAR)) if vol > 0 else None
    pos = sum(1 for x in seg_rets if x > 0)
    return {
        "days": n, "segments": len(segs),
        "ann_excess": ann, "mean": mean, "vol": vol, "mean_vol": mv,
        "pos_seg_frac": pos / len(seg_rets) if seg_rets else None,
        "worst_seg": min(seg_rets) if seg_rets else None,
        "best_seg": max(seg_rets) if seg_rets else None,
        "seg_rets": seg_rets,
    }


def main() -> None:
    daily, legs, t342, rv2, fam = load_inputs()
    labeled = sorted(daily.keys())
    cash_map = {r["d"]: (0.0 if r["cash_daily_rate"] is None or pd.isna(r["cash_daily_rate"])
                         else float(r["cash_daily_rate"]))
                for _, r in legs.iterrows()}

    # ── 自检 1:台账写的第二层天数(线上·注 1229 / 线下·注 569 / 线下·抽 461 / 线上·抽 221)──
    led_expect = {"线上·注": 1229, "线下·注": 569, "线下·抽": 461, "线上·抽": 221}
    for name, spec in LAYER2:
        got = sum(1 for d in labeled if in_state(daily, d, spec))
        assert got == led_expect[name], f"第二层 {name} 天数 {got} ≠ 台账 {led_expect[name]}"
    print("自检 1 ✓ 第二层 4 个状态的天数与台账一致(1229/569/461/221)")

    # ── 13 条策略 ────────────────────────────────────────────────────────────
    core_map = {r["d"]: (None if pd.isna(r["core_nav_1_cap_pit24"]) else float(r["core_nav_1_cap_pit24"]))
                for _, r in t342.iterrows()}
    rv2_map = {r["d"]: float(r["nav"]) for _, r in rv2.iterrows()}

    strategies: list[tuple[str, dict, bool]] = []  # (名字, {日期: 值}, 扣现金?)

    def add_from_map(name, mp, deduct):
        ds = sorted(x for x in mp if mp[x] is not None)
        vs = [mp[x] for x in ds]
        strategies.append((name, {"dates": ds, "values": vs, "raw": mp}, deduct))

    add_from_map("核心", core_map, True)
    add_from_map("X1V", {r["d"]: (None if pd.isna(r["crypto_nav"]) else float(r["crypto_nav"]))
                          for _, r in legs.iterrows()}, True)
    add_from_map("R-v2", rv2_map, False)
    add_from_map("ACWI", {r["d"]: (None if pd.isna(r["equity_close"]) else float(r["equity_close"]))
                          for _, r in legs.iterrows()}, True)
    add_from_map("XAUUSD", {r["d"]: (None if pd.isna(r["gold_close"]) else float(r["gold_close"]))
                             for _, r in legs.iterrows()}, True)
    for fam_name in ["S642", "S736_fixed", "S736_published", "S808", "S810",
                     "S681_H2", "S681_H3", "S681_H4"]:
        sub = fam[fam["family"] == fam_name]
        add_from_map(fam_name, {r["d"]: float(r["nav"]) for _, r in sub.iterrows()}, False)

    assert len(strategies) == 13, f"策略数 {len(strategies)} ≠ 13"
    print(f"自检 2 ✓ 13 条策略加载完毕")

    # ── 逐策略:补齐 → 日收益 → 与状态配对 ────────────────────────────────────
    strat_rets: dict[str, dict[str, float]] = {}
    coverage: dict[str, dict] = {}
    for name, spec, deduct in strategies:
        flat = flat_series(spec["dates"], spec["values"])
        leak = check_no_lookahead(flat, spec["dates"], spec["values"])
        assert leak <= 1e-12, f"{name} 补齐后含未来信息(最大差 {leak})"
        rets = build_strategy_returns(daily, labeled, flat, cash_map, deduct)
        assert rets, f"{name} 没有任何有效日收益"
        strat_rets[name] = rets
        coverage[name] = {
            "raw_days": len(spec["dates"]),
            "raw_first": spec["dates"][0], "raw_last": spec["dates"][-1],
            "labeled_days_with_return": len(rets),
            "first": min(rets), "last": max(rets),
            "deduct_cash": deduct,
            "flat_fill_lookahead_max_diff": leak,
        }
    print("自检 3 ✓ 13 条策略的补齐都不含未来信息(最大差 0)")

    # ── 表:13 × 12 = 156 格 ─────────────────────────────────────────────────
    table: dict[str, dict] = {}
    long_shou: list[list[str]] = []
    for name, _spec, _deduct in strategies:
        rets = strat_rets[name]
        days_all = sorted(rets)
        for sname, sspec in STATES:
            in_days = [d for d in days_all if in_state(daily, d, sspec)]
            out_days = [d for d in days_all if not in_state(daily, d, sspec)]
            s = stats_of(in_days, rets)
            o = stats_of(out_days, rets)
            segs = segments_of(in_days)
            best_seg_days: list[str] = []
            if segs:
                seg_rets = [float(np.prod(1.0 + np.array([rets[x] for x in sg], dtype=float)) - 1.0)
                            for sg in segs]
                best_seg_days = segs[int(np.argmax(seg_rets))]
            rest = [d for d in in_days if d not in set(best_seg_days)]
            after = stats_of(rest, rets)
            c1 = bool(s["segments"] >= MIN_SEGS and s["days"] >= MIN_DAYS)
            c2 = bool(s["ann_excess"] is not None and s["ann_excess"] > 0
                      and s["mean_vol"] is not None and s["mean_vol"] >= MIN_SHARPE)
            c3 = bool(s["pos_seg_frac"] is not None and s["pos_seg_frac"] >= MIN_POS_SEG_FRAC)
            c4 = bool(after["mean"] is not None and after["mean"] > 0)
            c5 = bool(s["mean"] is not None and o["mean"] is not None and s["mean"] > o["mean"])
            allp = bool(c1 and c2 and c3 and c4 and c5)
            key = f"{name}|{sname}"
            table[key] = {
                "strategy": name, "state": sname,
                "days": s["days"], "segments": s["segments"],
                "ann_excess": s["ann_excess"], "mean": s["mean"], "vol": s["vol"],
                "mean_vol": s["mean_vol"],
                "pos_seg_frac": s["pos_seg_frac"],
                "worst_seg": s["worst_seg"], "best_seg": s["best_seg"],
                "mean_after_best": after["mean"], "ann_after_best": after["ann_excess"],
                "out_days": o["days"], "out_segments": o["segments"],
                "out_ann_excess": o["ann_excess"], "out_mean": o["mean"],
                "out_vol": o["vol"], "out_mean_vol": o["mean_vol"],
                "crit": {"c1_seg5_days120": c1, "c2_ann_gt0_sharpe_ge05": c2,
                         "c3_pos_seg_ge60pct": c3, "c4_after_best_gt0": c4,
                         "c5_in_gt_out": c5},
                "all_pass": allp,
            }
            assert table[key]["days"] + table[key]["out_days"] == len(days_all), f"{key} 天数不闭合"
            if allp:
                long_shou.append([name, sname])
    assert len(table) == 156, f"格子数 {len(table)} ≠ 156"
    print(f"自检 4 ✓ 表 156 格(13 策略 × 12 状态),每格天数闭合")

    res = {
        "meta": {
            "task": "T-391",
            "kind": "blind_recompute",
            "ledger": "S-869 + 「S-869 / S-870 更正(算前)」①",
            "generated_by": "docs/research/s869_blind.py",
            "blind": "未读 docs/research/s869_strategy_state.py 与 s869_results.json",
            "conventions": {
                "universe": "s866_cells.json 的逐日标签日(2480 天)∩ 该策略有有效 D→D+1 收益的日子",
                "return": "apparatus.long_return:补齐后的 D 日值 → D+1 日值(下一个日历日)",
                "flat_fill": "稀疏序列在首末日之间按不变补齐(向后取最近一根);取价走 apparatus.price_on_or_after(max_gap_days=0)",
                "cash": "只有核心/X1V/ACWI/XAUUSD 扣 cash_daily_rate(D);2023-02-10 之前的利率记 0;缺失记 0",
                "annualization": "ann_excess = ∏(1+r)^(365/天数) − 1;mean_vol = (均值×365)/(样本标准差×√365)",
                "segment": "同状态内相邻两天间隔 ≤ 5 天并一段;段收益 = ∏(1+r) − 1",
                "out_of_state": "同一策略同一宇宙里、不属于该状态的日子;没有状态标签的日子不在宇宙里(不算状态外)",
                "days_per_year": DAYS_PER_YEAR, "seg_gap_days": SEG_GAP_DAYS,
            },
            "states": {"layer1": [n for n, _ in LAYER1], "layer2": [n for n, _ in LAYER2]},
            "strategies": [n for n, _s, _d in strategies],
            "coverage": coverage,
            "labeled_days": len(labeled),
        },
        "table": table,
        "long_shou": long_shou,
        "long_shou_strategies": sorted({x[0] for x in long_shou}),
    }
    out_path = os.path.join(HERE, "s869_blind_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"✓ 落盘 {out_path}")
    print(f"  长处(五条全过){len(long_shou)} 格:")
    for s, st in long_shou:
        c = table[f"{s}|{st}"]
        print(f"    {s:14s} {st:8s} 天 {c['days']:4d} 段 {c['segments']:3d} "
              f"年化 {c['ann_excess']:+.4f} 均值/波动 {c['mean_vol']:.3f} "
              f"正段占比 {c['pos_seg_frac']:.2f}")


if __name__ == "__main__":
    main()
