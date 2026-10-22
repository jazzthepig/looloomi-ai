"""T-170 / S-668 H2 —— 加密组:v2 合成 vs v1(一致性检查,不是证据)。

## 照抄 S-668 原文

> **H2(加密,一致性检查,不是证据 —— 维度是在 2023–26 这批数据上看出来的):** 25 个名字,
> 2023-01 → 2026-09,v2 合成 vs v1 综合分的周 IC(只报);S-630 的回放(BTC / ETH 钉住、
> 只在山寨里按 v2 z 倾斜)对 200 次随机打乱:报分位。

判据(卡 prior_value):**回放分位 ≥ 80 ⇒ 加密组满足切换条件 ③**;否则加密继续 v1、v2 影子累计前向。
IC 只报 —— 不参与判定。

## 不重写的部分

- 回放骨架 —— `docs/research/t148_alt_momentum_tilt.py` 的 `back_solve_w0` / `build_v3_weights` /
  `run_weekly` / `nav_total` / `nav_max_dd` / `segment_return`,只把 z30 换成 v2 z。
- v2 合成 —— `src/data.cis/v2.py` 的 `crypto_inputs` + `score_group`(影子写入端用同一个函数)。
- 零分布 / 分位 / 档位滞回 —— `src/data.evaluation.apparatus` 与 `src.data.cis.rebuild.pct_hysteresis`。

## 取数时点

v2 的每个输入只用 **d − 1 及以前**(周一再平衡 ⇒ 读到周日;周频 IC ⇒ 读到周四)。
F / O 取 `cis_rebuild_daily` 里 ≤ asof 的最后一行,没有就用 None(那一维不算,不是 0)。

## 打分组

v2 的组 = CIS 加密 25 个 ∪ ① 回放宇宙(24 个)的并集(32 个名字)。
① 宇宙里不在 CIS 25 个里的名字(ATOM / BCH / DOGE / ETC / FIL / LTC / TRX)没有 F / O,
`score_group` 只对有值的名字排分位,于是它们自动落到「其余三维」(≥ 2 维即可)。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs" / "research"))

import t148_alt_momentum_tilt as T148  # noqa: E402  —— 回放框架,import 不重写
# ⚠️ T-148 的 `fetch_all` 分页没有 order 约束:PostgREST 按无序结果集切 limit/offset,
# 翻页边界每次请求都会漂 ⇒ 同一段查询两次拉,23427 行里只拿到 18622 个不同 (symbol, date),
# 重复 4805 个。**本页所有查询一律显式带 `order=`**(10-22 实测)。
from t148_alt_momentum_tilt import (  # noqa: E402
    build_v3_weights, cross_sectional_z, fetch_ohlcv, nav_max_dd, nav_total,
    nav_total_holdout, run_weekly,
)

from src.data.cis import v2 as V2  # noqa: E402  —— v2 合成,import 不重写
from src.data.cis.rebuild import pct_hysteresis  # noqa: E402  —— CIS_STANDARD §6 的正式滞回
from src.data.evaluation.apparatus import percentile_of, price_on_or_after, shuffle_within  # noqa: E402

# ── 常量 ──────────────────────────────────────────────────────────────────────
# CIS 加密 25 个(src/data/cis/cis_provider.py 的 CRYPTO_ASSETS)。
CRYPTO_25 = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "NEAR", "SUI",
             "APT", "HYPE", "ARB", "OP", "POL", "STRK", "UNI", "AAVE", "LDO",
             "PENDLE", "LINK", "INJ", "TIA", "ONDO", "SKY")

IC_START = "2023-01-01"
IC_END = "2026-09-30"          # 卡:2023-01 → 2026-09
IC_FWD_DAYS = 28               # 之后 28 天
IC_EVERY_N_WEEKS = 4           # 每 4 周取一个不重叠样本
N_SHUFFLES = 200
SEED = 170
TILT_K = 0.5                   # 与 T-148 同一倾斜强度
BAND_DAYS = 30                 # 换档频率的归一窗口
V0_TOLERANCE_PCT = 1.0         # V0 复现容差(multiplier_daily.core_u_replay 1% 以内)


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


# ── v2 输入 ───────────────────────────────────────────────────────────────────
def load_mcap(symbols: list[str]) -> dict[str, list[tuple]]:
    """{symbol: [(d, price, mcap), ...]} 升序 —— `v2.crypto_inputs` 吃的就是这个形状。"""
    sel = ",".join(f'"{s}"' for s in symbols)
    rows = T148.fetch_all(
        f"asset_mcap_daily?select=symbol,d,price,mcap&symbol=in.({sel})"
        f"&d=gte.2022-06-01&d=lte.{IC_END}&order=symbol.asc,d.asc")
    out: dict[str, list[tuple]] = defaultdict(list)
    for r in rows:
        if r.get("price") is None or r.get("mcap") is None:
            continue
        out[r["symbol"]].append((str(r["d"])[:10], float(r["price"]), float(r["mcap"])))
    return dict(out)


def load_pillars(symbols: list[str]) -> tuple[dict[str, list[tuple]], dict[str, dict]]:
    """(cis_rebuild_daily 的 (d, f, o) 升序 per symbol, {symbol: {d: {...}}})。"""
    sel = ",".join(f'"{s}"' for s in symbols)
    rows = T148.fetch_all(
        f"cis_rebuild_daily?select=symbol,d,pillar_f,pillar_o,score,pct&symbol=in.({sel})"
        f"&d=gte.{IC_START}&d=lte.{IC_END}&order=symbol.asc,d.asc")
    series: dict[str, list[tuple]] = defaultdict(list)
    by_day: dict[str, dict] = defaultdict(dict)
    for r in rows:
        d = str(r["d"])[:10]
        f, o = r.get("pillar_f"), r.get("pillar_o")
        series[r["symbol"]].append((d, float(f) if f is not None else None,
                                    float(o) if o is not None else None))
        by_day[d][r["symbol"]] = {"score": r.get("score"), "pct": r.get("pct")}
    return dict(series), dict(by_day)


def _at_or_before(series: list[tuple], asof: dt.date):
    best = None
    for row in series:
        if row[0] <= asof:
            best = row
        else:
            break
    return best


def v2_scores(mcap: dict[str, list[tuple]], pillars: dict[str, list[tuple]],
              names: list[str], asof: str) -> dict[str, dict]:
    """asof(d − 1)那天的 v2 合成:每个名字一遍 `crypto_inputs`,再 `score_group('crypto', …)`。"""
    a = _d(asof)
    raw: dict[str, dict[str, float | None]] = {}
    for s in names:
        got = V2.crypto_inputs(mcap.get(s, []), a)
        row = _at_or_before(pillars.get(s, []), a.isoformat())
        raw[s] = {"size": got["size"], "stability": got["stability"], "supply": got["supply"],
                  "f": row[1] if row else None, "o": row[2] if row else None}
    return V2.score_group("crypto", raw)


def v2_percentile(scores: dict[str, dict]) -> dict[str, float]:
    """v2 综合分的组内分位(和 v1 官方档位同一口径:组内百分位)。"""
    return V2.pct_rank({k: v["score"] for k, v in scores.items() if v["score"] is not None})


# ── 1. V0 复现(先做;过不了就报差,不过不了也不静默) ─────────────────────────
def reproduce_v0(ct_rows: list[dict], md_rows: list[dict], px_all: dict, panel_names: list[str]) -> dict:
    """`cis_tilt_daily` / `multiplier_daily` 是调度者每天重写的活动表(10-22 实测 computed_at 当天),
    所以整轮只取一次快照(snap_tilt_last_computed_at 记在结果里),不在各段之间重新拉。"""
    rebal = [r for r in ct_rows if r.get("rebalanced")]
    w0_per_date: dict[str, dict[str, float]] = {}
    for r in rebal:
        if r.get("weights"):
            w0_per_date[r["d"]] = T148.back_solve_w0(r["weights"], r.get("z") or {})
    rebal_dates = sorted(w0_per_date)
    px = {s: px_all.get(s, {}) for s in panel_names}
    v0_nav, v0_turnover = run_weekly(rebal_dates, w0_per_date, px, panel_names, inception_nav=1.0)

    md_nav = {r["d"]: r["nav"] for r in md_rows}
    aligned = sorted(d for d in v0_nav if d in md_nav and md_nav[d])
    diffs = [abs(v0_nav[d] - md_nav[d]) / md_nav[d] * 100 for d in aligned]
    max_diff = max(diffs) if diffs else float("nan")
    worst = aligned[int(np.argmax(diffs))] if diffs else None
    return {
        "rebal_dates": rebal_dates, "w0_per_date": w0_per_date, "px": px,
        "v0_nav": v0_nav, "v0_turnover": v0_turnover,
        "final_v0_nav": v0_nav[rebal_dates[-1]],
        "final_v0_date": rebal_dates[-1],
        "final_md_nav_same_date": md_nav.get(rebal_dates[-1]),
        "final_md_nav": md_nav[max(md_nav)],
        "final_diff_pct_same_date": (abs(v0_nav[rebal_dates[-1]] - md_nav[rebal_dates[-1]])
                                     / md_nav[rebal_dates[-1]] * 100) if rebal_dates[-1] in md_nav else None,
        "max_relative_diff_pct": max_diff, "max_diff_day": worst,
        "median_relative_diff_pct": float(np.median(diffs)) if diffs else float("nan"),
        "n_aligned_days": len(aligned),
        "passes_1pct": bool(max_diff < V0_TOLERANCE_PCT),
    }


# ── 2. 回放:v2 z 倾斜 vs V0,200 次打乱 ───────────────────────────────────────
def replay(v0: dict, panel_names: list[str], mcap, pillars) -> dict:
    rebal_dates, w0_per_date, px = v0["rebal_dates"], v0["w0_per_date"], v0["px"]
    alts = [s for s in panel_names if s not in T148.PANEL_BTC_ETH]
    group = sorted(set(CRYPTO_25) | set(panel_names))

    z_per_date: dict[str, dict[str, float]] = {}
    v2w_per_date: dict[str, dict[str, float]] = {}
    n_scored: list[int] = []
    for d in rebal_dates:
        asof = (_d(d) - dt.timedelta(days=1)).isoformat()
        sc = v2_scores(mcap, pillars, group, asof)
        n_scored.append(sum(1 for s in panel_names if sc.get(s, {}).get("score") is not None))
        z = cross_sectional_z({s: sc[s]["score"] for s in panel_names
                               if sc.get(s, {}).get("score") is not None}, alts)
        z = {s: 0.0 for s in T148.PANEL_BTC_ETH} | {s: float(z.get(s, 0.0)) for s in alts}
        z_per_date[d] = z
        v2w_per_date[d] = build_v3_weights(w0_per_date[d], z, panel_names, k=TILT_K)

    nav, turnover = run_weekly(rebal_dates, v2w_per_date, px, panel_names, inception_nav=1.0)
    v0_total = nav_total(v0["v0_nav"])
    v2_total = nav_total(nav)
    diff_all = v2_total - v0_total
    diff_holdout = nav_total_holdout(nav) - nav_total_holdout(v0["v0_nav"])

    rng = np.random.default_rng(SEED)
    null_diff: list[float] = []
    for _ in range(N_SHUFFLES):
        sh_w: dict[str, dict[str, float]] = {}
        for d in rebal_dates:
            z = dict(z_per_date[d])
            vals = np.array([z[s] for s in alts], dtype=float)
            vals_sh = shuffle_within(vals.tolist(), ["alts"] * len(alts), rng)
            for s, v in zip(alts, vals_sh):
                z[s] = float(v)
            sh_w[d] = build_v3_weights(w0_per_date[d], z, panel_names, k=TILT_K)
        sh_nav, _ = run_weekly(rebal_dates, sh_w, px, panel_names, inception_nav=1.0)
        null_diff.append(nav_total(sh_nav) - v0_total)

    null = np.array(null_diff, dtype=float)
    pctile_diff = percentile_of(diff_all, null.tolist())
    return {
        "window": [rebal_dates[0], rebal_dates[-1]],
        "n_rebalance": len(rebal_dates),
        "n_scored_min": int(min(n_scored)), "n_scored_max": int(max(n_scored)),
        "n_alts": len(alts),
        "v0_total": v0_total, "v2_total": v2_total, "diff_full": diff_all,
        "diff_2025_holdout": diff_holdout,
        "v0_max_dd": nav_max_dd(v0["v0_nav"]), "v2_max_dd": nav_max_dd(nav),
        "turnover_v2_total": turnover,
        "null_diff_mean": float(null.mean()), "null_diff_std": float(null.std(ddof=1)),
        "pctile_v2_minus_v0_vs_200_shuffles": pctile_diff,
        "pctile_ge_80": bool(pctile_diff is not None and pctile_diff >= 0.80),
        "n_shuffles": N_SHUFFLES, "seed": SEED, "tilt_k": TILT_K,
    }


# ── 3. 周 IC(只报) ────────────────────────────────────────────────────────────
def weekly_ic(mcap, pillars, rb_by_day: dict, px_ic: dict[str, dict[str, float]],
              group: list[str]) -> dict:
    """每周五截面:v2 合成 vs v1 cis_score 对之后 28 天收益的 Spearman IC,每 4 周取一个不重叠样本。"""
    from scipy.stats import spearmanr

    days = sorted(d for d in rb_by_day if IC_START <= d <= IC_END)
    first_friday = next((d for d in days if _d(d).weekday() == 4), None)
    if first_friday is None:
        return {"samples": 0, "why": "数据里没有周五"}
    idx0 = days.index(first_friday)
    sample_days = [d for i, d in enumerate(days) if i >= idx0 and (i - idx0) % 7 == 0
                   and (i - idx0) % (7 * IC_EVERY_N_WEEKS) == 0]

    rows: list[dict] = []
    for d in sample_days:
        asof = (_d(d) - dt.timedelta(days=1)).isoformat()
        sc = v2_scores(mcap, pillars, group, asof)
        # 之后 28 天的收益:入场 d、退出 d+28 当天或之后 3 天内的第一个有效收盘
        p_out = {s: price_on_or_after(sorted(px_ic.get(s, {})), [px_ic.get(s, {})[k] for k in sorted(px_ic.get(s, {}))],
                                      (_d(d) + dt.timedelta(days=IC_FWD_DAYS)).isoformat())
                 for s in group}
        pts = []
        for s in group:
            v2 = sc.get(s, {}).get("score")
            v1 = (rb_by_day.get(d, {}).get(s) or {}).get("score")
            p_in = price_on_or_after(sorted(px_ic.get(s, {})), [px_ic.get(s, {})[k] for k in sorted(px_ic.get(s, {}))], d)
            if v2 is None or v1 is None or p_in is None or p_out.get(s) is None:
                continue
            pts.append((float(v2), float(v1), p_out[s] / p_in - 1.0, s))
        if len(pts) < 8:
            rows.append({"date": d, "n": len(pts), "ic_v2": None, "ic_v1": None, "skipped": True})
            continue
        v2s = [p[0] for p in pts]
        v1s = [p[1] for p in pts]
        fwd = [p[2] for p in pts]
        rows.append({"date": d, "n": len(pts),
                     "ic_v2": float(spearmanr(v2s, fwd).statistic),
                     "ic_v1": float(spearmanr(v1s, fwd).statistic)})

    ok = [r for r in rows if not r.get("skipped")]
    def summ(key: str) -> dict:
        xs = np.array([r[key] for r in ok], dtype=float)
        if xs.size < 3:
            return {"n_samples": int(xs.size), "mean_ic": None, "t": None}
        t = float(xs.mean() / (xs.std(ddof=1) / math.sqrt(xs.size))) if xs.std(ddof=1) > 0 else None
        return {"n_samples": int(xs.size), "mean_ic": float(xs.mean()), "t": t,
                "hit_positive_pct": float((xs > 0).mean())}
    return {"every_n_weeks": IC_EVERY_N_WEEKS, "fwd_days": IC_FWD_DAYS,
            "n_skipped": sum(1 for r in rows if r.get("skipped")),
            "n_min_cross_section": min((r["n"] for r in rows), default=0),
            "v2_vs_fwd_28d": summ("ic_v2"), "v1_vs_fwd_28d": summ("ic_v1"),
            "samples": rows}


# ── 4. 换档频率(CIS_STANDARD §6 的分位档 + 滞回) ───────────────────────────────
def switch_frequency(mcap, pillars, rb_by_day: dict, group: list[str]) -> dict:
    days = sorted(d for d in rb_by_day if IC_START <= d <= IC_END)
    # v1:cis_rebuild_daily.pct 已经是同组当日分位(§6 的正式口径)。
    v1_pct_by_day = {s: [(d, (rb_by_day.get(d, {}).get(s) or {}).get("pct")) for d in days] for s in group}
    v2_pct_by_day: dict[str, list] = {s: [] for s in group}
    for d in days:
        asof = (_d(d) - dt.timedelta(days=1)).isoformat()
        pcts = v2_percentile(v2_scores(mcap, pillars, group, asof))
        for s in group:
            v2_pct_by_day[s].append((d, pcts.get(s)))

    def rates(pct_by_day: dict[str, list]) -> tuple[dict[str, float], float]:
        per_name: dict[str, float] = {}
        for s, series in pct_by_day.items():
            seq = [p for _, p in series if p is not None]
            if len(seq) < BAND_DAYS:
                continue
            levels = [lv for lv, _ in pct_hysteresis(seq) if lv is not None]
            switches = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
            per_name[s] = switches / (len(seq) / BAND_DAYS)
        return per_name, (float(np.mean(list(per_name.values()))) if per_name else float("nan"))

    r1, m1 = rates(v1_pct_by_day)
    r2, m2 = rates(v2_pct_by_day)
    common = sorted(set(r1) & set(r2))
    return {
        "band_days": BAND_DAYS,
        "n_days": len(days),
        "v1_switches_per_name_per_30d": round(m1, 4), "v2_switches_per_name_per_30d": round(m2, 4),
        "v1": {s: round(v, 3) for s, v in sorted(r1.items())},
        "v2": {s: round(v, 3) for s, v in sorted(r2.items())},
        "common_names": common,
        "v1_common_mean": round(float(np.mean([r1[s] for s in common])), 4) if common else None,
        "v2_common_mean": round(float(np.mean([r2[s] for s in common])), 4) if common else None,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main() -> int:
    # ── 快照:cis_tilt_daily / multiplier_daily 每天被调度者重写,整轮只拉一次 ──
    ct = T148.fetch_all("cis_tilt_daily?select=d,arm,nav,weights,z,rebalanced,computed_at"
                        "&arm=eq.cis_a1_u_replay&order=d.asc")
    md = T148.fetch_all("multiplier_daily?select=d,nav,computed_at&arm=eq.core_u_replay&order=d.asc")
    rebal = [r for r in ct if r.get("rebalanced")]
    # 面板与 T-148 一致:取第一个再平衡日的 weights(后续新增的名字不并进来,否则不是同一个宇宙)
    panel_names = sorted(rebal[0]["weights"].keys())
    group = sorted(set(CRYPTO_25) | set(panel_names))
    snap = {
        "tilt_rows": len(ct), "tilt_rebal_dates": len(rebal),
        "tilt_last_computed_at": max((str(r.get("computed_at") or "") for r in ct), default=None),
        "multiplier_rows": len(md),
        "multiplier_last_computed_at": max((str(r.get("computed_at") or "") for r in md), default=None),
        "multiplier_last_d": max((str(r["d"]) for r in md), default=None),
    }
    print(f"[T-170] ① 回放宇宙 {len(panel_names)} 个 · v2 打分组 {len(group)} 个", flush=True)

    print("[T-170] 拉 ohlcv_daily / asset_mcap_daily / cis_rebuild_daily……", flush=True)
    px_raw = T148.fetch_all(
        "ohlcv_daily?select=symbol,trade_date,close&source=eq.binance_hist&symbol=in.("
        + ",".join(f'"{s}"' for s in group) + f")&trade_date=gte.{IC_START}"
        "&order=symbol.asc,trade_date.asc")   # order 不能省:见下面 fetch_all 的页漂移
    px_all: dict[str, dict[str, float]] = defaultdict(dict)
    for r in px_raw:
        if r.get("close") is not None:
            px_all[r["symbol"]][str(r["trade_date"])[:10]] = float(r["close"])
    px_all = dict(px_all)
    mcap = load_mcap(group)
    pillars, rb_by_day = load_pillars(group)
    print(f"  价 {len(px_all)} 个 · mcap {len(mcap)} 个 · pillars {len(pillars)} 个", flush=True)

    print("[T-170] V0 复现(卡:1% 以内,对不上要报差)……", flush=True)
    v0 = reproduce_v0(ct, md, px_all, panel_names)
    print(f"  终值 {v0['final_v0_nav']:.5f} @ {v0['final_v0_date']} vs multiplier_daily "
          f"{v0['final_md_nav_same_date']:.5f} → 末日差 {v0['final_diff_pct_same_date']:.3f}%,"
          f"全程最大差 {v0['max_relative_diff_pct']:.3f}% @{v0['max_diff_day']} "
          f"({v0['n_aligned_days']} 天)", flush=True)
    gate = v0["passes_1pct"]
    if not gate:
        print(f"  ❌ V0 复现超 {V0_TOLERANCE_PCT}% —— 下面的回放分位是**暂定值**,不构成判据通过。", flush=True)

    print("[T-170] 回放 v2 z 倾斜 + 200 次打乱……", flush=True)
    rep = replay(v0, panel_names, mcap, pillars)
    print(f"  V0 {rep['v0_total']:+.4f} → v2 {rep['v2_total']:+.4f}(差 {rep['diff_full']:+.4f})· "
          f"分位 {rep['pctile_v2_minus_v0_vs_200_shuffles']}", flush=True)

    print("[T-170] 周 IC(只报)……", flush=True)
    ic = weekly_ic(mcap, pillars, rb_by_day, px_all, group)
    print(f"  v2 IC {ic['v2_vs_fwd_28d'].get('mean_ic')} (t={ic['v2_vs_fwd_28d'].get('t')}) · "
          f"v1 IC {ic['v1_vs_fwd_28d'].get('mean_ic')} (t={ic['v1_vs_fwd_28d'].get('t')})", flush=True)

    print("[T-170] 换档频率(§6 分位档 + 滞回)……", flush=True)
    sw = switch_frequency(mcap, pillars, rb_by_day, group)
    print(f"  v1 {sw['v1_switches_per_name_per_30d']} vs v2 {sw['v2_switches_per_name_per_30d']} 次/名字/30 天",
          flush=True)

    if gate:
        verdict = "PASS_GE_80" if rep["pctile_ge_80"] else "BELOW_80_加密继续 v1"
    else:
        verdict = "STOP_V0_MISMATCH_回放分位暂定"
    out = {
        "ticket": "T-170", "ledger": "S-668 H2",
        "caveat": "一致性检查,不是证据 —— v2 的维度是在 2023–26 这批数据上看出来的(S-668 原文)。",
        "snapshot": snap,
        "v0_check": {k: v for k, v in v0.items()
                     if k not in ("rebal_dates", "w0_per_date", "px", "v0_nav")},
        "panel": {"n": len(panel_names), "names": panel_names, "pinned": list(T148.PANEL_BTC_ETH),
                  "note": "与 T-148 同口径:取第一个再平衡日的 weights"},
        "v2_group": {"n": len(group), "names": group,
                     "outside_cis25_in_panel": sorted(set(panel_names) - set(CRYPTO_25)),
                     "no_price": sorted(set(group) - set(px_all))},
        "replay_v2": rep,
        "weekly_ic": ic,
        "switch_frequency": sw,
        "verdict": verdict,
    }
    (ROOT / "docs" / "research" / "t170_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print("\n[T-170] 结果写入 docs/research/t170_results.json")
    print(f"  判据(卡 prior_value):{verdict}")
    return 0 if gate else 2


if __name__ == "__main__":
    sys.exit(main())