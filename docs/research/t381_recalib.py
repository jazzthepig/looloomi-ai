"""T-381(S-852 情景返工):校准窗口与到期口径对齐 + 两处数改正 + 随机起点臂。

只读。不改 s851/s852 的任何一行 —— 这里 import 它们的 get() / weekly_down_days() / conditions(),
把 v2 的 episodes 规则重写一遍(多了 starts= 参数),并用自检证明与 s852_results.json 的 15 段逐字一致。

口径(本次要修的三处):
  1) state_daily 的 panel 序列是**自然日**序列(一行 = 一个日历日,周末也有行),不是交易日序列。
     T-375 的基率用 persist(…,22):+22 行 = +22 自然日;但到期日 2026-12-15 距写下日 2026-11-13
     是 **32 自然日** —— 窗口不等长 ⇒ 基率要按 32 重算。
  2) 8 周后收益的分母是**有 8 周读数的段数**(不是全部 confirmed 段数)。
  3) 起点间隔 = 相邻两段起点日之差(自然日),n = 段数 − 1。

用法(仓库根目录,环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    nohup python3 docs/research/t381_recalib.py > docs/research/t381_run.txt 2>&1 &
产出 docs/research/t381_results.json。
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import statistics
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
    random_dates_like,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_sp = importlib.util.spec_from_file_location("s851", os.path.join(_HERE, "s851_watch_base_rate.py"))
S = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(S)

OUT = "docs/research/t381_results.json"
WRITE_DAY, EXPIRY = dt.date(2026, 11, 13), dt.date(2026, 12, 15)
HORIZON = (EXPIRY - WRITE_DAY).days            # 32 自然日
OLD_H = 22                                     # T-375 用过的行数
N_NULL, SEED = 200, 20261114
MIN_CONDS, MAX_WATCH_D, INVALID_D, POST_D = 2, 180, 14, 56
SEGMENTS = (("2021", (2021, 2021)), ("2022-23", (2022, 2023)), ("2024-25", (2024, 2025)), ("2026", (2026, 2026)))


# ---------------------------------------------------------------- 序列与口径核验
def state_panel(feature: str) -> list[tuple[dt.date, float | None]]:
    rows = S.get("state_daily", {"select": "d,value", "entity": "eq.panel", "feature": "eq." + feature,
                                 "d": "gte.2019-01-01", "order": "d.asc"})
    return [(S.D(r["d"]), (None if r.get("value") is None else float(r["value"]))) for r in rows]


def macro_series(series: str, start: str | None = None) -> list[tuple[dt.date, float | None]]:
    """start=None ⇒ 取全表(与 T-375 定标脚本 s852_calibration_read.macro_series 同一口径:不过滤起点)。"""
    params = {"select": "d,value", "series": "eq." + series, "order": "d.asc"}
    if start:
        params["d"] = "gte." + start
    rows = S.get("macro_daily", params)
    return [(S.D(r["d"]), (None if r.get("value") is None else float(r["value"]))) for r in rows]


def audit_calendar(series) -> dict:
    """这条序列是不是自然日序列:相邻两行的日期间隔是否恒为 1 天。"""
    dates = [d for d, _ in series]
    gaps = [(dates[i - 1], dates[i], (dates[i] - dates[i - 1]).days) for i in range(1, len(dates))
            if (dates[i] - dates[i - 1]).days != 1]
    return {"rows": len(dates), "first": str(dates[0]), "last": str(dates[-1]),
            "weekend_rows": sum(1 for d in dates if d.weekday() >= 5),
            "null_rows": sum(1 for _, v in series if v is None),
            "non_contiguous_gaps": len(gaps),
            "gap_examples": [[str(a), str(b), n] for a, b, n in gaps[:5]],
            "is_calendar_day_series": len(gaps) == 0 and len(dates) > 0}


# ---------------------------------------------------------------- 基率:点对点
def p2p_date(series, src, dst, h: int) -> tuple[int, int, float | None]:
    """P(dst 在 d+h **自然日**那天成立 | src 在 d 那天成立)。按日期算,不是按行号。"""
    idx = {d: v for d, v in series}
    n = hits = 0
    for d, v in series:
        if v is None or not src(v):
            continue
        w = idx.get(d + dt.timedelta(days=h))
        if w is None:
            continue
        n += 1
        hits += bool(dst(w))
    return n, hits, (hits / n if n else None)


def p2p_rows(series, src, dst, h: int) -> tuple[int, int, float | None]:
    """同一个量,但按**行号**走 h 行(行序;null 行跳过不算样本)。"""
    n = hits = 0
    for i, (d, v) in enumerate(series):
        if v is None or not src(v):
            continue
        j = i + h
        if j >= len(series) or series[j][1] is None:
            continue
        n += 1
        hits += bool(dst(series[j][1]))
    return n, hits, (hits / n if n else None)


def legacy(series, want, horizon: int) -> tuple[int, int, float | None]:
    """T-375 原写法(s852_calibration_read.py):先滤掉 null 行,再 +horizon **行**。仅用于复现旧数字。"""
    vals = [v for _, v in series if v is not None]
    n = hits = 0
    for i, v in enumerate(vals):
        if not want(v) or i + horizon >= len(vals):
            continue
        n += 1
        if want(vals[i + horizon]):
            hits += 1
    return n, hits, (hits / n if n else None)


def legacy_complement(series, want, horizon: int) -> tuple[int, int, float | None]:
    """T-375 第三段写法:从「**当前不满足**」出发,+horizon 行后**恰好**满足的频率。"""
    vals = [v for _, v in series if v is not None]
    n = hits = 0
    for i, v in enumerate(vals):
        if want(v) or i + horizon >= len(vals):
            continue
        n += 1
        if want(vals[i + horizon]):
            hits += 1
    return n, hits, (hits / n if n else None)


def med(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return None if not xs else round(float(statistics.median(xs)), 1)


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return None if not xs else round(float(statistics.fmean(xs)), 2)


# ---------------------------------------------------------------- v2 规则(加 starts=)
def episodes_v2(days, cond: dict, wdown: dict, close: dict, starts=None) -> list[dict]:
    """与 s852_watch_v2.episodes_v2 同一套规则,多了 starts= : 给了就用给的起点(随机起点臂),
    不给就按 v2 的自然规则找起点(条件 ≥2 且周线没坏的第一天;上一段结束后接着找)。"""
    out, i, n = [], 0, len(days)
    idx = {d: k for k, d in enumerate(days)}
    if starts is not None:
        given = sorted(idx[d] for d in starts if d in idx)
        for i0 in given:
            out.append(_one_episode(days, cond, wdown, close, i0)[0])
        return out
    while i < n:
        d = days[i]
        if not ((cond.get(d) or 0) >= MIN_CONDS and wdown.get(d) is False):
            i += 1
            continue
        e, j = _one_episode(days, cond, wdown, close, i, want_j=True)
        out.append(e)
        i = max(j, i) + 1
    return out


def _one_episode(days, cond, wdown, close, i0: int, want_j: bool = False):
    n = len(days)
    d0 = days[i0]
    peak, peak_d, zero_run, end, how = close[d0], d0, 0, None, "timeout"
    j = i0
    for j in range(i0 + 1, min(i0 + MAX_WATCH_D, n - 1) + 1):
        x = days[j]
        if close.get(x, 0) > peak:
            peak, peak_d = close[x], x
        if wdown.get(x):
            end, how = x, "confirmed"
            break
        zero_run = zero_run + 1 if (cond.get(x) or 0) == 0 else 0
        if zero_run >= INVALID_D:
            end, how = x, "invalidated"
            break
    end = end or days[j]
    post = close.get(end + dt.timedelta(days=POST_D))
    return {"start": str(d0), "peak": str(peak_d), "end": str(end), "outcome": how, "days": (end - d0).days,
            "days_to_peak": (peak_d - d0).days, "max_runup_pct": round((peak / close[d0] - 1) * 100, 1),
            "ret_start_to_end_pct": round((close[end] / close[d0] - 1) * 100, 1),
            "ret_peak_to_end_pct": round((close[end] / peak - 1) * 100, 1),
            "ret_8w_after_end_pct": None if post is None else round((post / close[end] - 1) * 100, 1)}, (j if want_j else i0)


# ---------------------------------------------------------------- 随机起点臂
def arm_stats(ep: list[dict]) -> dict:
    conf = [e for e in ep if e["outcome"] == "confirmed"]
    return {"n": len(ep), "confirmed": len(conf),
            "share_confirmed": round(len(conf) / len(ep), 3) if ep else None,
            "median_days_to_peak": med([e["days_to_peak"] for e in conf]),
            "mean_days_to_peak": mean([e["days_to_peak"] for e in conf]),
            "median_max_runup_pct": med([e["max_runup_pct"] for e in conf]),
            "mean_max_runup_pct": mean([e["max_runup_pct"] for e in conf])}


def random_starts(pool: list[dt.date], anchors: list[str], rng) -> list[dt.date]:
    """用 apparatus.random_dates_like 抽随机起点:每个锚点年份内抽一个合格日(同层没有就退回全池)。"""
    if not pool or not anchors:
        return []
    events = [(i, anchors[i % len(anchors)]) for i in range(len(anchors))]
    got = random_dates_like(events, {i: pool for i in range(len(events))}, rng, stratum=lambda d: str(d)[:4])
    return [dt.date.fromisoformat(d) for _, d in got if d is not None]


def null_arm(days, cond, wdown, close, pool, anchors, rng) -> dict:
    starts = random_starts(pool, anchors, rng)
    return arm_stats(episodes_v2(days, cond, wdown, close, starts=starts))


# ---------------------------------------------------------------- 主流程
def main() -> None:
    for k in ("SUPABASE_URL", "SUPABASE_KEY"):
        if not os.environ.get(k):
            print("缺环境变量", k, "—— 退出", flush=True)
            sys.exit(1)

    print("== 1. 序列口径(行 = 自然日?)==", flush=True)
    d200 = state_panel("dist_200")
    taker = state_panel("taker_buy_share_30d")
    fng = macro_series("fng")
    mvrv = macro_series("btc_mvrv")
    audits = {"state:dist_200": audit_calendar(d200), "state:taker_buy_share_30d": audit_calendar(taker),
              "macro:fng": audit_calendar(fng), "macro:btc_mvrv": audit_calendar(mvrv)}
    for name, a in audits.items():
        print("  %-28s rows=%-5d weekend_rows=%-4d null_rows=%-2d first=%s last=%s contiguous=%s gaps=%s" % (
            name, a["rows"], a["weekend_rows"], a["null_rows"], a["first"], a["last"],
            a["is_calendar_day_series"], a["non_contiguous_gaps"]), flush=True)

    print("\n-- 最新读数(情景 statement 要引用)--", flush=True)
    for name, s in (("state:dist_200", d200), ("state:taker_buy_share_30d", taker),
                    ("macro:fng", fng), ("macro:btc_mvrv", mvrv)):
        last = [(d, v) for d, v in s if v is not None]
        print("  %-28s %s = %s" % (name, last[-1][0], round(last[-1][1], 4)), flush=True)

    print("\n== 2. 窗口口径 ==", flush=True)
    print("  写下日 %s → 到期日 %s = %d 自然日(T-375 用的 +%d 行 = +%d 自然日,窗口不等长)" % (
        WRITE_DAY, EXPIRY, HORIZON, OLD_H, OLD_H), flush=True)
    for name, s in (("state:dist_200", d200), ("state:taker_buy_share_30d", taker)):
        last = max(d for d, _ in s)
        print("  %-28s 最新读数日 %s → 到期日 %s = %d 自然日" % (name, last, EXPIRY, (EXPIRY - last).days), flush=True)

    print("\n== 3. 基率(点对点;旧口径复现 vs 新窗口)==", flush=True)
    gt0 = lambda v: v > 0                                              # noqa: E731
    le0 = lambda v: v <= 0                                             # noqa: E731
    ge5 = lambda v: v >= 0.5                                           # noqa: E731
    lt5 = lambda v: v < 0.5                                            # noqa: E731
    lt50 = lambda v: v < 50                                           # noqa: E731
    lt220 = lambda v: v < 2.20                                         # noqa: E731

    base = {}
    # T-375-1:dist_200 现在 ≤ 0 ⇒ 要的是 +H 天后回到线上方的频率(旧口径:从「不满足」出发)
    old = legacy_complement(d200, gt0, OLD_H)
    base["T-375-1"] = {"series": "state:dist_200", "src": "<=0", "dst": ">0", "legacy_direction": "complement",
                       "legacy_row_filtered_H22": {"n": old[0], "hits": old[1], "rate": round(old[2], 3) if old[2] is not None else None},
                       "new_date_H32": dict(zip(("n", "hits", "rate"), p2p_date(d200, le0, gt0, HORIZON))),
                       "new_rows_H32": dict(zip(("n", "hits", "rate"), p2p_rows(d200, le0, gt0, HORIZON))),
                       "new_date_H33": dict(zip(("n", "hits", "rate"), p2p_date(d200, le0, gt0, HORIZON + 1)))}
    # T-375-4:taker 现在 ≥ 0.5 ⇒ 要的是 +H 天后跌破 0.5 的频率(旧口径写的是「仍 ≥0.5」= 1 − 目标)
    old = legacy(taker, ge5, OLD_H)
    base["T-375-4"] = {"series": "state:taker_buy_share_30d", "src": ">=0.5", "dst": "<0.5", "legacy_direction": "persist",
                       "legacy_row_filtered_H22": {"n": old[0], "hits": old[1], "rate": round(old[2], 3) if old[2] is not None else None},
                       "new_date_H32": dict(zip(("n", "hits", "rate"), p2p_date(taker, ge5, lt5, HORIZON))),
                       "new_rows_H32": dict(zip(("n", "hits", "rate"), p2p_rows(taker, ge5, lt5, HORIZON))),
                       "new_date_H33": dict(zip(("n", "hits", "rate"), p2p_date(taker, ge5, lt5, HORIZON + 1)))}
    # 顺带重算 T-375-2 / T-375-3(同样用了 +22 行窗口)
    for tid, s, src, dst, sname, slabel in (("T-375-2", fng, lt50, lt50, "macro:fng", "<50"),
                                            ("T-375-3", mvrv, lt220, lt220, "macro:btc_mvrv", "<2.20")):
        old = legacy(s, src, OLD_H)
        base[tid] = {"series": sname, "src": slabel, "dst": slabel, "legacy_direction": "persist",
                     "legacy_row_filtered_H22": {"n": old[0], "hits": old[1], "rate": round(old[2], 3) if old[2] is not None else None},
                     "new_date_H32": dict(zip(("n", "hits", "rate"), p2p_date(s, src, dst, HORIZON))),
                     "new_rows_H32": dict(zip(("n", "hits", "rate"), p2p_rows(s, src, dst, HORIZON)))}
    for tid, b in base.items():
        ld, nd, nr = b["legacy_row_filtered_H22"], b["new_date_H32"], b["new_rows_H32"]
        b["new_date_H32"]["rate"] = round(nd["rate"], 3) if nd["rate"] is not None else None
        b["new_rows_H32"]["rate"] = round(nr["rate"], 3) if nr["rate"] is not None else None
        b["row_vs_date_agree"] = (nd["n"], nd["hits"]) == (nr["n"], nr["hits"])
        print("  %-8s %-26s 旧(+%d 行,滤 null) N=%-5d 命中=%-5d 频率=%-6s | 新(+%d 自然日,日期算术) N=%-5d 命中=%-5d 频率=%-6s | 行序口径 N=%-5d 频率=%-6s | 一致=%s" % (
            tid, b["series"], OLD_H, ld["n"], ld["hits"], ld["rate"], HORIZON,
            nd["n"], nd["hits"], nd["rate"], nr["n"], nr["rate"], b["row_vs_date_agree"]), flush=True)

    print("\n-- 旧口径的「+22 行」在日历上到底是多少天(滤掉 null 行之后,行 ≠ 日)--", flush=True)
    row_span = {}
    for name, s in (("state:dist_200", d200), ("state:taker_buy_share_30d", taker)):
        vals = [(d, v) for d, v in s if v is not None]
        spans = [(vals[i + OLD_H][0] - vals[i][0]).days for i in range(len(vals) - OLD_H)]
        row_span[name] = {"rows_after_filter": len(vals), "span_mean": round(statistics.fmean(spans), 1),
                          "span_min": min(spans), "span_max": max(spans), "span_median": round(float(statistics.median(spans)), 1)}
        print("  %-28s 滤 null 后 %d 行;+22 行跨 %d 自然日(均值 %.1f,中位 %.1f,区间 %d–%d)" % (
            name, len(vals), len(spans), row_span[name]["span_mean"], row_span[name]["span_median"],
            row_span[name]["span_min"], row_span[name]["span_max"]), flush=True)

    print("\n== 4. v2 规则 + 两处数改正 + 随机起点臂 ==", flush=True)
    px = S.get("ohlcv_daily", {"select": "trade_date,close", "symbol": "eq.BTC", "source": "eq.binance_hist",
                               "trade_date": "gte.2018-09-01", "order": "trade_date.asc"})
    close = {S.D(r["trade_date"]): float(r["close"]) for r in px if r.get("close")}
    days = sorted(d for d in close if d >= dt.date(2019, 6, 1))
    d200d = {d: v for d, v in d200}
    takd = {d: v for d, v in taker}
    stbd = state_panel("stable_supply_30d")
    stbd = {d: v for d, v in stbd}
    y2 = macro_series("ust_2y", start="2018-06-01")          # 与 s851.load_live 同一口径(否则条件数会变)
    y2d, y2v = [d for d, _ in y2], [v for _, v in y2]
    wdown = S.weekly_down_days(days, close)
    cond = {d: S.conditions(d, close, d200d, takd, stbd, y2d, y2v) for d in days}
    ep = episodes_v2(days, cond, wdown, close)
    conf = [e for e in ep if e["outcome"] == "confirmed"]
    with8w = [e for e in conf if e["ret_8w_after_end_pct"] is not None]
    neg8w = [e for e in with8w if e["ret_8w_after_end_pct"] < 0]
    starts = [dt.date.fromisoformat(e["start"]) for e in ep]
    gaps = [(starts[i + 1] - starts[i]).days for i in range(len(starts) - 1)]
    print("  段数 n=%d confirmed=%d invalidated=%d timeout=%d" % (
        len(ep), len(conf), sum(1 for e in ep if e["outcome"] == "invalidated"), sum(1 for e in ep if e["outcome"] == "timeout")), flush=True)
    print("  8 周口径:confirmed=%d,其中有 +8 周读数的=%d,其中为负=%d ⇒ %d/%d(T-375 写的 8/14 的分母应是 %d)" % (
        len(conf), len(with8w), len(neg8w), len(neg8w), len(with8w), len(with8w)), flush=True)
    print("  起点间隔(相邻段起点日之差,自然日):n=%d 中位数=%.1f 排序=%s" % (len(gaps), float(statistics.median(gaps)), sorted(gaps)), flush=True)

    # 随机起点池:趋势还好(dist_200>0)且周线没坏的任意一天(与 S-851 的对照池同定义)
    pool = [d for d in days[:-MAX_WATCH_D] if (d200d.get(d) or 0) > 0 and not wdown.get(d)]
    pool_relaxed = [d for d in days[:-60] if (d200d.get(d) or 0) > 0 and not wdown.get(d)]
    anchors = [e["start"] for e in ep]
    print("  随机起点池:dist_200>0 且周线没坏 ⇒ %d 天(锚点 = 真实段的起点,按**同一年**分层抽样)" % len(pool), flush=True)

    rng = np.random.default_rng(SEED)
    real_arm = arm_stats(ep)
    rand_arms = [null_arm(days, cond, wdown, close, pool, anchors, rng) for _ in range(N_NULL)]
    print("  真实 15 段 : n=%d confirmed=%d days_to_peak 中位=%.1f 均值=%.2f | max_runup 中位=%.1f 均值=%.2f" % (
        real_arm["n"], real_arm["confirmed"], real_arm["median_days_to_peak"], real_arm["mean_days_to_peak"],
        real_arm["median_max_runup_pct"], real_arm["mean_max_runup_pct"]), flush=True)
    r_dtp = [a["median_days_to_peak"] for a in rand_arms if a["median_days_to_peak"] is not None]
    r_mru = [a["median_max_runup_pct"] for a in rand_arms if a["median_max_runup_pct"] is not None]
    r_scf = [a["share_confirmed"] for a in rand_arms if a["share_confirmed"] is not None]
    print("  随机起点臂: n=%d 次抽样 | days_to_peak 中位 %.1f(分位 %.1f–%.1f) | max_runup 中位 %.1f(分位 %.1f–%.1f) | share_confirmed 中位 %.3f" % (
        len(rand_arms), float(np.median(r_dtp)), float(np.quantile(r_dtp, 0.1)), float(np.quantile(r_dtp, 0.9)),
        float(np.median(r_mru)), float(np.quantile(r_mru, 0.1)), float(np.quantile(r_mru, 0.9)), float(np.median(r_scf))), flush=True)

    nulls = {}
    for label, stat, actual in (("days_to_peak_mean", "mean_days_to_peak", real_arm["mean_days_to_peak"]),
                                 ("max_runup_mean", "mean_max_runup_pct", real_arm["mean_max_runup_pct"]),
                                 ("share_confirmed", "share_confirmed", real_arm["share_confirmed"])):
        def _fn(g, s=stat):
            v = null_arm(days, cond, wdown, close, pool, anchors, g).get(s)
            return float("nan") if v is None else float(v)
        try:
            null = null_distribution(_fn, N_NULL, SEED + 1)
            nulls[label] = {"n_null": int(len(null)), "null_median": round(float(np.median(null)), 3),
                            "actual": actual, "percentile_of_actual": percentile_of(actual, null)}
        except NoOpNull as ex:
            nulls[label] = {"error": str(ex)}
        print("  零分布(%s): %s" % (label, json.dumps(nulls[label], ensure_ascii=False)), flush=True)

    # T-375-5 的基率:历史上任意一天起,往后 32 自然日内有没有新开出的盯盘段
    start_set = {dt.date.fromisoformat(e["start"]) for e in ep}
    spans = [(dt.date.fromisoformat(e["start"]), dt.date.fromisoformat(e["end"])) for e in ep]
    n_all = hit_all = n_free = hit_free = 0
    for d in days:
        if d + dt.timedelta(days=HORIZON) > days[-1]:
            continue
        window = (d, d + dt.timedelta(days=HORIZON))
        got = any(d < s <= window[1] for s in start_set)
        n_all += 1
        hit_all += got
        free = not any(a <= d <= b for a, b in spans)
        if free:
            n_free += 1
            hit_free += got
    seg3 = {"horizon_natural_days": HORIZON,
            "all_days": {"n": n_all, "with_new_segment": hit_all, "rate_no_new": round(1 - hit_all / n_all, 3) if n_all else None},
            "free_days": {"n": n_free, "with_new_segment": hit_free, "rate_no_new": round(1 - hit_free / n_free, 3) if n_free else None},
            "last_segment": {"start": ep[-1]["start"], "end": ep[-1]["end"], "outcome": ep[-1]["outcome"]}}
    print("  新段基率(往后 %d 自然日):全部日 n=%d 其中 %d 天内新开段 ⇒ P(没有)=%s | 不在段内的空闲日 n=%d 其中 %d ⇒ P(没有)=%s" % (
        HORIZON, n_all, hit_all, seg3["all_days"]["rate_no_new"], n_free, hit_free, seg3["free_days"]["rate_no_new"]), flush=True)

    print("\n== 5. 四段分拆(2021 / 2022-23 / 2024-25 / 2026)==", flush=True)
    seg_out = {}
    for name, (y0, y1) in SEGMENTS:
        se = [e for e in ep if y0 <= int(e["start"][:4]) <= y1]
        sa = arm_stats(se)
        spool = [d for d in pool if y0 <= d.year <= y1]
        sanchors = [e["start"] for e in se]
        srand = [null_arm(days, cond, wdown, close, spool, sanchors, rng) for _ in range(N_NULL)]
        s_dtp = [a["median_days_to_peak"] for a in srand if a["median_days_to_peak"] is not None]
        s_mru = [a["median_max_runup_pct"] for a in srand if a["median_max_runup_pct"] is not None]
        s_scf = [a["share_confirmed"] for a in srand if a["share_confirmed"] is not None]
        spool_r = [d for d in pool_relaxed if y0 <= d.year <= y1]
        srand_r = [null_arm(days, cond, wdown, close, spool_r, sanchors, rng) for _ in range(N_NULL)]
        r_dtp = [a["median_days_to_peak"] for a in srand_r if a["median_days_to_peak"] is not None]
        r_mru = [a["median_max_runup_pct"] for a in srand_r if a["median_max_runup_pct"] is not None]
        seg_out[name] = {"years": [y0, y1], "real": sa, "pool_days": len(spool), "pool_relaxed_days": len(spool_r),
                         "random_median_days_to_peak": round(float(np.median(s_dtp)), 1) if s_dtp else None,
                         "random_median_max_runup_pct": round(float(np.median(s_mru)), 1) if s_mru else None,
                         "random_share_confirmed_median": round(float(np.median(s_scf)), 3) if s_scf else None,
                         "relaxed_median_days_to_peak": round(float(np.median(r_dtp)), 1) if r_dtp else None,
                         "relaxed_median_max_runup_pct": round(float(np.median(r_mru)), 1) if r_mru else None}
        print("  %-8s 真实 n=%-2d conf=%-2d days_to_peak 中位=%-6s max_runup 中位=%-6s | 随机 中位 days_to_peak=%-6s max_runup=%-6s share_confirmed=%-6s (池 %d 天) | 松池(60d 后瞻) days_to_peak=%-6s max_runup=%-6s (池 %d 天)" % (
            name, sa["n"], sa["confirmed"], sa["median_days_to_peak"], sa["median_max_runup_pct"],
            seg_out[name]["random_median_days_to_peak"], seg_out[name]["random_median_max_runup_pct"],
            seg_out[name]["random_share_confirmed_median"], len(spool),
            seg_out[name]["relaxed_median_days_to_peak"], seg_out[name]["relaxed_median_max_runup_pct"], len(spool_r)), flush=True)

    print("\n== 6. 自检(能失败)==", flush=True)
    cut = days[len(days) // 2]
    close2 = {d: v * (2.0 if d > cut else 1.0) for d, v in close.items()}
    ep2 = episodes_v2(days, cond, S.weekly_down_days(days, close2), close2)
    key = lambda e: (e["start"], e["peak"], e["end"], e["outcome"], e["days"], e["days_to_peak"], e["max_runup_pct"])
    lim = str(cut - dt.timedelta(days=POST_D))
    checks = {
        "episodes_before_cut_ignore_future_prices": [key(e) for e in ep if e["end"] <= lim] == [key(e) for e in ep2 if e["end"] <= lim],
        "no_start_while_weekly_already_down": all(wdown.get(S.D(e["start"])) is False for e in ep),
        "episodes_do_not_overlap": all(ep[i]["end"] < ep[i + 1]["start"] for i in range(len(ep) - 1)),
        "state_panel_series_are_calendar_days": audits["state:dist_200"]["is_calendar_day_series"] and audits["state:taker_buy_share_30d"]["is_calendar_day_series"],
        "row_index_equals_date_arithmetic_H32": all(b["row_vs_date_agree"] for b in base.values()),
    }
    ref = os.path.join(_HERE, "s852_results.json")
    if os.path.exists(ref):
        ref_ep = json.load(open(ref, encoding="utf-8"))["episodes"]
        checks["reproduces_s852_15_episodes"] = (len(ref_ep) == len(ep) and
                                                 [key(e) for e in ref_ep] == [key(e) for e in ep])
    else:
        checks["reproduces_s852_15_episodes"] = "s852_results.json 不在,跳过"
    for k, v in checks.items():
        print("  %-42s %s" % (k, v), flush=True)

    out = {"write_day": str(WRITE_DAY), "expiry": str(EXPIRY), "horizon_natural_days": HORIZON, "old_row_horizon": OLD_H,
           "audits": audits, "base_rates": base, "row_span_22": row_span, "episodes_n": len(ep), "confirmed_n": len(conf),
           "eight_week": {"confirmed": len(conf), "with_8w_reading": len(with8w), "negative": len(neg8w)},
           "start_gaps": {"n": len(gaps), "median": float(statistics.median(gaps)), "sorted": sorted(gaps)},
           "pool_days": len(pool), "pool_relaxed_days": len(pool_relaxed), "real_arm": real_arm, "nulls": nulls, "segments": seg_out,
           "new_segment_base_rate": seg3,
           "random_arm_medians": {"days_to_peak": round(float(np.median(r_dtp)), 1) if r_dtp else None,
                                  "max_runup_pct": round(float(np.median(r_mru)), 1) if r_mru else None,
                                  "share_confirmed": round(float(np.median(r_scf)), 3) if r_scf else None},
           "self_checks": checks}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nWROTE", OUT, flush=True)


if __name__ == "__main__":
    main()
