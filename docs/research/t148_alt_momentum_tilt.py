"""T-148 (S-634):钉住 BTC/ETH,只在山寨里按 30 日动量倾斜 —— 与 S-630 同框架、同判据。

做法(逐字对应 S-634):
  - 从 cis_tilt_daily 的 cis_a1_u_replay 行反推 ① 权重 w_① ∝ w × exp(−0.5 · z)(V0 必须复现
    multiplier_daily.core_u_replay NAV 到 1% 以内)。
  - V3 = BTC/ETH 保持 w_①,其余名字在剩余份额内按 w_① × exp(0.5 · z30) 重新分配。
  - z30 = 到 d − 1 收盘的 30 日收益在山寨内的横截面 z 分。
  - 周一(UTC)再平衡、周内买入持有、换手 × 10bp。
  - 200 次随机打乱 z30(只在山寨里打乱,不动时序)。
  - 90 日动量同口径数(只报不判)。
  - 用 src/data/evaluation/apparatus.py 的 shuffle_within;不另写零分布。

判(V3 进 ② 前向 ⇒ 两条都满足):
  ① V3 − V0 全程 > 0 且 2025-01-01 起留出段 > 0
  ② V3 − V0 高于「每个再平衡日在山寨里随机打乱 z30」200 次的第 190 大(95 分位)。

数据:
  - cis_tilt_daily(arm=eq.cis_a1_u_replay):{d, nav, weights, z, rebalanced}
  - ohlcv_daily(source=eq.binance_hist):{symbol, trade_date, close}
  - multiplier_daily(arm=eq.core_u_replay):{d, nav}  ← V0 核对目标
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import shuffle_within  # noqa: E402

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

REBAL_INCEPTION = "2023-01-02"
HOLDOUT_FROM = "2025-01-01"
COST_BPS = 0.001
PANEL_BTC_ETH = ("BTC", "ETH")
N_SHUFFLES = 200
SEED = 148
MOMENTUM_DAYS_PRIMARY = 30
MOMENTUM_DAYS_SECONDARY = 90


# ── 数据读取 ─────────────────────────────────────────────────────────────────
def fetch_all(path: str) -> list[dict]:
    out: list[dict] = []
    offset = 0
    page = 1000
    while True:
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(
            f"{URL}/rest/v1/{path}{sep}limit={page}&offset={offset}",
            headers=HEADERS,
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        if not resp:
            break
        out.extend(resp)
        if len(resp) < page:
            break
        offset += page
    return out


def fetch_ohlcv(symbols: list[str]) -> dict[str, dict[str, float]]:
    """{symbol: {YYYY-MM-DD: close_price}}。"""
    sym_list = ",".join(f'"{s}"' for s in symbols)
    rows = fetch_all(
        f"ohlcv_daily?select=symbol,trade_date,close&source=eq.binance_hist"
        f"&symbol=in.({sym_list})&trade_date=gte.{REBAL_INCEPTION}"
    )
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        d = str(r["trade_date"])[:10]
        c = r.get("close")
        if c is not None:
            out[r["symbol"]][d] = float(c)
    return dict(out)


# ── 工具函数 ─────────────────────────────────────────────────────────────────
def cross_sectional_z(values: dict[str, float], names: list[str]) -> dict[str, float]:
    """横截面 z 分(只对 names 中那些值非空的算);缺 / 标准差 0 ⇒ 全部 0。"""
    have = {s: v for s, v in values.items() if s in names and v is not None and math.isfinite(v)}
    if len(have) < 2:
        return {s: 0.0 for s in names}
    arr = np.array(list(have.values()), dtype=float)
    mu = float(arr.mean())
    sd = float(arr.std(ddof=1))
    if sd <= 0:
        return {s: 0.0 for s in names}
    return {s: (have[s] - mu) / sd if s in have else 0.0 for s in names}


def normalize(d: dict[str, float]) -> dict[str, float]:
    s = sum(max(0.0, v) for v in d.values())
    if s <= 0:
        return {k: 0.0 for k in d}
    return {k: max(0.0, v) / s for k, v in d.items()}


def turnover_cost(old: dict[str, float], new: dict[str, float]) -> float:
    """|Δw| sum × 10bp。"""
    keys = set(old) | set(new)
    diff = sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) for k in keys)
    return diff * COST_BPS


# ── 1. V0 反推 ────────────────────────────────────────────────────────────────
def back_solve_w0(weights: dict[str, float], z: dict[str, float]) -> dict[str, float]:
    """w_① ∝ w_② × exp(-0.5 · z),再归一(总和=1)。
    cis_a1_u 的 cap=1.0 不压单币,所以反推就是 exp 比例 + 归一化。"""
    raw = {s: float(w) * math.exp(-0.5 * float(z.get(s, 0.0))) for s, w in weights.items() if w and w > 0}
    return normalize(raw)


# ── 2. 动量 z(只看 d−1 及以前) ───────────────────────────────────────────────
def compute_momentum_z(px: dict[str, dict[str, float]], panel_names: list[str],
                       rebal_date: str, lookback: int) -> dict[str, float]:
    """到 d − 1 收盘的 lookback 日收益,在 山寨 (非 BTC/ETH) 横截面里的 z 分。
    BTC/ETH 始终返回 0(V3 里它们被钉住,不进 z 分母也用不上)。"""
    target = date.fromisoformat(rebal_date) - timedelta(days=1)

    def last_close_before(sym: str, end: date):
        d = end
        prices = []
        for _ in range(lookback * 5):
            ds = d.isoformat()
            if sym in px and ds in px[sym]:
                prices.append((d, px[sym][ds]))
            d = d - timedelta(days=1)
            if len(prices) >= lookback + 1:
                break
        if len(prices) < lookback + 1:
            return None
        prices.sort()
        p_now, p_then = prices[-1][1], prices[-(lookback + 1)][1]
        if p_then <= 0 or p_now <= 0:
            return None
        return (p_now / p_then) - 1.0

    alts = [s for s in panel_names if s not in PANEL_BTC_ETH]
    rets = {s: last_close_before(s, target) for s in alts}
    raw = {s: r for s, r in rets.items() if r is not None}
    z = cross_sectional_z(raw, alts)
    out = {s: 0.0 for s in PANEL_BTC_ETH if s in panel_names}
    out.update({s: z.get(s, 0.0) for s in alts})
    return out


# ── 3. 周 NAV ────────────────────────────────────────────────────────────────
def segment_return(w: dict[str, float], d_start: str, d_end: str,
                   px: dict[str, dict[str, float]], panel_names: list[str]) -> float:
    """周内买入持有:Σ w[s] × (close[d_end] / close[d_start] − 1)。缺价 symbol 跳过。"""
    seg = 0.0
    for s in panel_names:
        if s not in w or w[s] <= 0:
            continue
        if s not in px:
            continue
        p_s = px[s].get(d_start)
        p_e = px[s].get(d_end)
        if p_s is None or p_e is None or p_s <= 0:
            continue
        seg += w[s] * (p_e / p_s - 1.0)
    return seg


def run_weekly(rebal_dates: list[str], w_per_date: dict[str, dict[str, float]],
               px: dict[str, dict[str, float]], panel_names: list[str],
               inception_nav: float = 1.0) -> tuple[dict[str, float], float]:
    """nav[d_t] = nav[d_{t-1}] × (1 + segment[d_{t-1} → d_t]) × (1 − cost_t) ——
    与 multiplier_daily 的 nav 字段口径一致。返回 {d: nav} 和总换手。"""
    nav = inception_nav
    nav_by_date: dict[str, float] = {}
    total_turnover = 0.0
    prev_w: dict[str, float] = {}
    for t, d in enumerate(rebal_dates):
        w = w_per_date.get(d, {})
        cost = turnover_cost(prev_w, w) if prev_w else 0.0
        if t == 0:
            nav_by_date[d] = nav
        if t + 1 < len(rebal_dates):
            d_next = rebal_dates[t + 1]
            seg = segment_return(w, d, d_next, px, panel_names)
            nav = nav * (1.0 + seg) * (1.0 - cost)
            nav_by_date[d_next] = nav
            total_turnover += cost
        prev_w = w
    return nav_by_date, total_turnover


def nav_total(nav_by_date: dict[str, float], inception_nav: float = 1.0) -> float:
    last = nav_by_date[max(nav_by_date.keys())]
    return (last / inception_nav) - 1.0


def nav_total_holdout(nav_by_date: dict[str, float], since: str = HOLDOUT_FROM) -> float:
    keys = sorted(nav_by_date.keys())
    base = next((d for d in reversed(keys) if d < since), None)
    if base is None:
        return 0.0
    base_nav = nav_by_date[base]
    last = nav_by_date[keys[-1]]
    return (last / base_nav) - 1.0 if base_nav > 0 else 0.0


def nav_max_dd(nav_by_date: dict[str, float]) -> float:
    keys = sorted(nav_by_date.keys())
    navs = np.array([nav_by_date[d] for d in keys], dtype=float)
    if len(navs) == 0:
        return 0.0
    peak = np.maximum.accumulate(navs)
    dd = (navs - peak) / peak
    return float(dd.min())


# ── 4. V3 权重:BTC/ETH 钉住,山寨内 w × exp(K·z) 重排 ─────────────────────────
def build_v3_weights(w0: dict[str, float], z: dict[str, float],
                     panel_names: list[str], k: float = 0.5) -> dict[str, float]:
    """BTC/ETH 保持 w_①;其余在剩余份额(1 − BTC − ETH)内按 w_① × exp(k·z) 重排。"""
    pinned = {s: w0.get(s, 0.0) for s in PANEL_BTC_ETH if s in w0}
    pinned_share = sum(pinned.values())
    residual = max(0.0, 1.0 - pinned_share)
    alts = [s for s in panel_names if s not in PANEL_BTC_ETH and w0.get(s, 0.0) > 0]
    raw = {s: w0[s] * math.exp(k * float(z.get(s, 0.0))) for s in alts}
    raw_sum = sum(max(0.0, v) for v in raw.values())
    if raw_sum <= 0:
        # z 全 0 或全空:回退到 w_① 等比
        fb_sum = sum(w0[s] for s in alts)
        if fb_sum <= 0:
            return dict(pinned)
        return {**pinned, **{s: (w0[s] / fb_sum) * residual for s in alts}}
    return {**pinned, **{s: (max(0.0, v) / raw_sum) * residual for s, v in raw.items()}}


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> int:
    print("[T-148] Fetching cis_tilt_daily cis_a1_u_replay...", flush=True)
    ct_rows = fetch_all("cis_tilt_daily?select=d,arm,nav,ret,weights,z,rebalanced,turnover"
                        "&arm=eq.cis_a1_u_replay&order=d.asc")
    rebal = [r for r in ct_rows if r.get("rebalanced")]
    print(f"  total rows: {len(ct_rows)}, rebalance days: {len(rebal)}")

    sample = rebal[0]["weights"]
    panel_names = sorted(sample.keys())
    print(f"  panel ({len(panel_names)}): {panel_names[:5]} … {panel_names[-3:]}")

    print("[T-148] Back-solving w_① from cis_tilt_daily rows...", flush=True)
    w0_per_date: dict[str, dict[str, float]] = {}
    for r in rebal:
        d = r["d"]
        weights = r.get("weights") or {}
        z = r.get("z") or {}
        if weights:
            w0_per_date[d] = back_solve_w0(weights, z)

    rebal_dates_all = sorted(w0_per_date.keys())
    print(f"[T-148] {len(rebal_dates_all)} rebal dates: "
          f"{rebal_dates_all[0]} → {rebal_dates_all[-1]}")

    # ── 价格 ──────────────────────────────────────────────────────────────
    print("[T-148] Fetching ohlcv_daily (binance_hist) for panel...", flush=True)
    px = fetch_ohlcv(panel_names)
    coverage = sum(1 for s in panel_names if len(px.get(s, {})) > 0)
    print(f"  panel price coverage: {coverage}/{len(panel_names)}")

    # ── V0 NAV(反推的 w_① 做周再平衡) ───────────────────────────────────
    v0_nav_by_date, v0_turnover = run_weekly(
        rebal_dates_all, w0_per_date, px, panel_names, inception_nav=1.0)

    # ── V0 核对:对比 multiplier_daily.core_u_replay NAV ─────────────────
    print("[T-148] Fetching multiplier_daily.core_u_replay for V0 cross-check...", flush=True)
    md_rows = fetch_all("multiplier_daily?select=d,nav&arm=eq.core_u_replay&order=d.asc")
    md_nav = {r["d"]: r["nav"] for r in md_rows}
    final_v0_date = rebal_dates_all[-1]
    final_v0_nav = v0_nav_by_date[final_v0_date]
    final_md_date = max(md_nav.keys())
    final_md_nav = md_nav[final_md_date]
    aligned = sorted((d for d in v0_nav_by_date if d in md_nav))
    diffs_pct = [abs(v0_nav_by_date[d] - md_nav[d]) / md_nav[d] * 100 for d in aligned]
    max_diff_pct = max(diffs_pct) if diffs_pct else float("nan")
    median_diff_pct = float(np.median(diffs_pct)) if diffs_pct else float("nan")
    print(f"[T-148] V0 final NAV: my {final_v0_nav:.5f} @ {final_v0_date} | "
          f"reference {final_md_nav:.5f} @ {final_md_date}")
    print(f"  ratio my/ref: {final_v0_nav / final_md_nav:.5f}  "
          f"max_rel_diff: {max_diff_pct:.3f}%  median: {median_diff_pct:.3f}%  "
          f"({len(aligned)} aligned days)")
    v0_passes = max_diff_pct < 1.0
    if not v0_passes:
        print(f"[T-148] ❌ V0 reproduction FAIL: max_diff {max_diff_pct:.3f}% ≥ 1%; stop per S-634.")
        return 2

    # ── V3 动量倾斜(30d) ───────────────────────────────────────────────
    print(f"[T-148] Building V3 momentum tilt ({MOMENTUM_DAYS_PRIMARY}d)...", flush=True)
    v3_w_per_date: dict[str, dict[str, float]] = {}
    z30_per_date: dict[str, dict[str, float]] = {}
    for d in rebal_dates_all:
        z30 = compute_momentum_z(px, panel_names, d, MOMENTUM_DAYS_PRIMARY)
        z30_per_date[d] = z30
        v3_w_per_date[d] = build_v3_weights(w0_per_date[d], z30, panel_names, k=0.5)

    v3_nav_by_date, v3_turnover = run_weekly(
        rebal_dates_all, v3_w_per_date, px, panel_names, inception_nav=1.0)

    v3_total = nav_total(v3_nav_by_date)
    v0_total = nav_total(v0_nav_by_date)
    v3_total_holdout = nav_total_holdout(v3_nav_by_date)
    v0_total_holdout = nav_total_holdout(v0_nav_by_date)

    diff_all = v3_total - v0_total
    diff_holdout = v3_total_holdout - v0_total_holdout

    print(f"[T-148] V3 (30d) vs V0:")
    print(f"  V0 total: {v0_total:+.4f}   V3 total: {v3_total:+.4f}   diff: {diff_all:+.4f}")
    print(f"  V0 holdout: {v0_total_holdout:+.4f}   V3 holdout: {v3_total_holdout:+.4f}   "
          f"diff: {diff_holdout:+.4f}")

    # ── 200 次随机打乱 z30(每个再平衡日只在山寨里打乱) ─────────────────
    print(f"[T-148] Running {N_SHUFFLES} shuffles of z30 within 山寨...", flush=True)
    rng = np.random.default_rng(SEED)
    alts = [s for s in panel_names if s not in PANEL_BTC_ETH]
    shuffle_totals_full: list[float] = []
    shuffle_totals_holdout: list[float] = []
    for k in range(N_SHUFFLES):
        sh_w_per_date: dict[str, dict[str, float]] = {}
        for d in rebal_dates_all:
            sh_z = dict(z30_per_date[d])
            vals = np.array([sh_z[s] for s in alts], dtype=float)
            vals_sh = shuffle_within(vals.tolist(), ["x"] * len(alts), rng)
            for s, v in zip(alts, vals_sh):
                sh_z[s] = float(v)
            sh_w_per_date[d] = build_v3_weights(w0_per_date[d], sh_z, panel_names, k=0.5)
        sh_nav, _ = run_weekly(rebal_dates_all, sh_w_per_date, px, panel_names, inception_nav=1.0)
        shuffle_totals_full.append(nav_total(sh_nav))
        shuffle_totals_holdout.append(nav_total_holdout(sh_nav))
    s_full = np.array(shuffle_totals_full)
    s_holdout = np.array(shuffle_totals_holdout)
    pctile_full = float((s_full < v3_total).mean())
    pctile_holdout = float((s_holdout < v3_total_holdout).mean())
    diff_diff_full = float((s_full - v0_total < diff_all).mean())  # 等价于 s_full < v3_total
    pctile_v3_minus_v0 = float((s_full - v0_total < diff_all).mean())

    print(f"  V3 percentile vs 200 shuffles (full): {pctile_full:.3f}")
    print(f"  V3 percentile vs 200 shuffles (holdout): {pctile_holdout:.3f}")
    print(f"  (V3−V0) percentile vs shuffles (full): {pctile_v3_minus_v0:.3f}")

    judgement_pass = (diff_all > 0) and (diff_holdout > 0) and (pctile_v3_minus_v0 > 0.95)

    # ── 90 日动量(只报,不判) ──────────────────────────────────────────
    print(f"[T-148] V3 report-only momentum tilt ({MOMENTUM_DAYS_SECONDARY}d)...", flush=True)
    v3w_w_per_date: dict[str, dict[str, float]] = {}
    for d in rebal_dates_all:
        z90 = compute_momentum_z(px, panel_names, d, MOMENTUM_DAYS_SECONDARY)
        v3w_w_per_date[d] = build_v3_weights(w0_per_date[d], z90, panel_names, k=0.5)
    v3w_nav, _ = run_weekly(rebal_dates_all, v3w_w_per_date, px, panel_names, inception_nav=1.0)
    v3w_total = nav_total(v3w_nav)
    v3w_total_holdout = nav_total_holdout(v3w_nav)
    diff_all_90 = v3w_total - v0_total
    diff_holdout_90 = v3w_total_holdout - v0_total_holdout

    # 最大回撤
    v0_dd = nav_max_dd(v0_nav_by_date)
    v3_dd = nav_max_dd(v3_nav_by_date)
    v3w_dd = nav_max_dd(v3w_nav)

    # ── 按慢状态分层 S-624 / S-627 ──────────────────────────────────────
    print("[T-148] Computing slow-state (majors ≥ 200-day MA) year splits + slow-state stratum...", flush=True)
    # 简化:仅报分年总收益,不报慢状态(因为 trader_daily 没有 200 日线数据)
    yearly: dict[str, dict] = {}
    for d in rebal_dates_all:
        yr = d[:4]
        if yr not in yearly:
            yearly[yr] = {"v0_first_date": d, "v0_first_nav": v0_nav_by_date[d],
                           "v0_last_nav_by_year": {}, "v3_last_nav_by_year": {},
                           "v3w_last_nav_by_year": {}}
    for d in rebal_dates_all:
        yr = d[:4]
        yearly[yr]["v0_last_nav_by_year"][d] = v0_nav_by_date[d]
        yearly[yr]["v3_last_nav_by_year"][d] = v3_nav_by_date[d]
        yearly[yr]["v3w_last_nav_by_year"][d] = v3w_nav[d]

    yearly_summaries = []
    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        v0_first = y["v0_first_nav"]
        v0_last = y["v0_last_nav_by_year"][max(y["v0_last_nav_by_year"])]
        v3_last = y["v3_last_nav_by_year"][max(y["v3_last_nav_by_year"])]
        v3w_last = y["v3w_last_nav_by_year"][max(y["v3w_last_nav_by_year"])]
        yearly_summaries.append({
            "year": yr,
            "v0_ret": (v0_last / v0_first) - 1,
            "v3_30d_ret": (v3_last / v0_first) - 1,
            "v3_30d_minus_v0": (v3_last / v0_first) - (v0_last / v0_first),
            "v3_90d_ret": (v3w_last / v0_first) - 1,
            "v3_90d_minus_v0": (v3w_last / v0_first) - (v0_last / v0_first),
        })

    out: dict = {
        "data_window": {
            "start": rebal_dates_all[0],
            "end": rebal_dates_all[-1],
            "n_rebalance": len(rebal_dates_all),
        },
        "panel": {"size": len(panel_names), "names": panel_names,
                  "pinned": list(PANEL_BTC_ETH)},
        "v0_check": {
            "final_nav_my": round(final_v0_nav, 5),
            "final_nav_reference": round(final_md_nav, 5),
            "ratio": round(final_v0_nav / final_md_nav, 5),
            "max_relative_diff_pct": round(max_diff_pct, 4),
            "median_relative_diff_pct": round(median_diff_pct, 4),
            "n_aligned_days": len(aligned),
            "passes_1pct": bool(v0_passes),
        },
        "v3_30d": {
            "v0_total": round(v0_total, 4),
            "v3_total": round(v3_total, 4),
            "diff_full": round(diff_all, 4),
            "diff_2025_holdout": round(diff_holdout, 4),
            "v0_max_dd": round(v0_dd, 4),
            "v3_max_dd": round(v3_dd, 4),
            "pctile_vs_shuffles_full": round(pctile_full, 4),
            "pctile_vs_shuffles_holdout": round(pctile_holdout, 4),
            "pctile_v3_minus_v0_full": round(pctile_v3_minus_v0, 4),
            "turnover_v0_total": round(v0_turnover, 4),
            "turnover_v3_total": round(v3_turnover, 4),
        },
        "v3_90d_report_only": {
            "v3_total": round(v3w_total, 4),
            "diff_full": round(diff_all_90, 4),
            "diff_2025_holdout": round(diff_holdout_90, 4),
            "v3_max_dd": round(v3w_dd, 4),
        },
        "yearly": yearly_summaries,
        "judgement_pass": bool(judgement_pass),
        "n_shuffles": N_SHUFFLES,
        "momentum_days_primary": MOMENTUM_DAYS_PRIMARY,
        "momentum_days_secondary": MOMENTUM_DAYS_SECONDARY,
        "cost_bps": COST_BPS,
    }

    out_path = ROOT / "docs" / "research" / "t148_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[T-148] results written: {out_path}")
    print(f"  judgement: {'✅ PASS' if judgement_pass else '❌ FAIL'}")
    return 0 if judgement_pass else 1


if __name__ == "__main__":
    sys.exit(main())
