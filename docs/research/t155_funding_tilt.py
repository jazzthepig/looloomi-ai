"""T-155 (S-640):钉住 BTC/ETH,只在山寨里按「负的 7 日平均资金费率 z 分数」倾斜。

做法(逐字对应 S-640,只把 z30 换成 z_fund):
  - V0 从 cis_tilt_daily 的 cis_a1_u_replay 行反推 ① 权重 w_① ∝ w × exp(−0.5·z)
    (V0 必须复现 multiplier_daily.core_u_replay NAV 到 1% 以内)。
  - V3 = BTC/ETH 保持 w_①,其余名字在剩余份额内按 w_① × exp(0.5·z) 重排。
  - z = −(d − 7 … d − 1 平均资金费率的山寨横截面 z)。资金费率读 funding_history
    venue = binance_perp;当天没资金费的名字 z = 0 并计数。
  - 周一(UTC)再平衡、周内买入持有、换手 × 10bp。
  - 200 次随机打乱 z(只在山寨里打乱,不动时序)。
  - 用 src/data/evaluation/apparatus.py 的 shuffle_within;不另写零分布。

判(V3 进 ② 前向 ⇒ 两条都满足):
  ① V3 − V0 全程 > 0 且 2025-01-01 起留出段 > 0
  ② V3 − V0 高于「每个再平衡日在山寨里随机打乱 z」200 次的第 190 大(95 分位)。

数据:
  - cis_tilt_daily(arm=eq.cis_a1_u_replay):{d, nav, weights, z, rebalanced}
  - ohlcv_daily(source=eq.binance_hist):{symbol, trade_date, close}
  - funding_history(venue=eq.binance_perp):{symbol, funding_time, funding_rate, …}
  - multiplier_daily(arm=eq.core_u_replay):{d, nav}  ← V0 核对目标
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
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
SEED = 155
FUND_LOOKBACK_DAYS = 7  # d − 7 … d − 1


# ── 数据读取 ─────────────────────────────────────────────────────────────────
def fetch_all(path: str) -> list[dict]:
    """按 limit/offset 分页直到取完(path 必须允许排序稳定;否则去重见用)。"""
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
    quoted = ",".join(f'"{s}"' for s in symbols)
    rows = fetch_all(
        f"ohlcv_daily?select=symbol,trade_date,close&source=eq.binance_hist"
        f"&symbol=in.({quoted})&trade_date=gte.{REBAL_INCEPTION}"
    )
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        d = str(r["trade_date"])[:10]
        c = r.get("close")
        if c is not None:
            out[r["symbol"]][d] = float(c)
    return dict(out)


def fetch_funding(symbols: list[str]) -> dict[str, list[tuple[str, float]]]:
    """{symbol: [(YYYY-MM-DD, funding_rate), ...]},按 funding_time 升序。"""
    quoted = ",".join(f'"{s}"' for s in symbols)
    rows = fetch_all(
        f"funding_history?select=symbol,funding_time,funding_rate"
        f"&venue=eq.binance_perp&symbol=in.({quoted})"
        f"&order=funding_time.asc"
    )
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        t = r.get("funding_time") or ""
        d = t[:10]
        fr = r.get("funding_rate")
        if fr is None or not d:
            continue
        out[r["symbol"]].append((d, float(fr)))
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
    """w_① ∝ w_② × exp(-0.5 · z),再归一(总和=1)。"""
    raw = {s: float(w) * math.exp(-0.5 * float(z.get(s, 0.0))) for s, w in weights.items() if w and w > 0}
    return normalize(raw)


# ── 2. 资金费率 z(只看 d − 7 … d − 1,平均资金费率;negate ⇒ 钉住 z=0) ────────
def compute_funding_z(funding: dict[str, list[tuple[str, float]]],
                      rebal_date: str, lookback: int = FUND_LOOKBACK_DAYS,
                      panel_names: list[str] | None = None) -> tuple[dict[str, float], dict[str, int]]:
    """到 d − 1 的 [d − lookback, d − 1] 窗口内,每个 alt 平均资金费率的横截面 z,然后取负。

    当天 0 行 funding(没有该名字的资金费样本)的名字 z = 0 并在返回里计数(空缺计 0)。
    BTC/ETH 始终返回 z=0(V3 里它们被钉住,不进 z 分母也用不上)。
    """
    d_target = date.fromisoformat(rebal_date)
    d_end_exclusive = d_target              # 不含 d
    d_start = d_target - timedelta(days=lookback)  # 含 d − lookback

    mean_rates: dict[str, float] = {}
    n_obs: dict[str, int] = {}
    if panel_names is None:
        names = list(funding.keys())
    else:
        names = panel_names
    for s in names:
        if s in PANEL_BTC_ETH:
            mean_rates[s] = None  # pinned
            n_obs[s] = 0
            continue
        rates: list[float] = []
        for d_str, fr in funding.get(s, []):
            d_row = date.fromisoformat(d_str)
            if d_start <= d_row < d_end_exclusive:
                rates.append(fr)
        n_obs[s] = len(rates)
        if rates:
            mean_rates[s] = float(np.mean(rates))
        else:
            mean_rates[s] = None  # 计数 = 0

    raw = {s: r for s, r in mean_rates.items() if r is not None}
    alts = [s for s in names if s not in PANEL_BTC_ETH]
    z_pos = cross_sectional_z(raw, alts)  # 高资金费 ⇒ z 高
    z_neg = {s: -v for s, v in z_pos.items()}  # S-640 显式要求 z = -(…)
    z_all = {s: 0.0 for s in PANEL_BTC_ETH if s in names}
    z_all.update({s: z_neg.get(s, 0.0) for s in alts if s in names})
    # 缺数计 0 已经由 cross_sectional_z 处理(没有 raw 就不在 z_pos 里、默认 0)
    return z_all, n_obs


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
    """nav[d_t] = nav[d_{t-1}] × (1 + segment[d_{t-1} → d_t]) × (1 − cost_t)。"""
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


# ── 4. V3 权重 ────────────────────────────────────────────────────────────────
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
        fb_sum = sum(w0[s] for s in alts)
        if fb_sum <= 0:
            return dict(pinned)
        return {**pinned, **{s: (w0[s] / fb_sum) * residual for s in alts}}
    return {**pinned, **{s: (max(0.0, v) / raw_sum) * residual for s, v in raw.items()}}


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> int:
    print("[T-155] Fetching cis_tilt_daily cis_a1_u_replay...", flush=True)
    ct_rows = fetch_all("cis_tilt_daily?select=d,arm,nav,ret,weights,z,rebalanced,turnover"
                        "&arm=eq.cis_a1_u_replay&order=d.asc")
    rebal = [r for r in ct_rows if r.get("rebalanced")]
    print(f"  total rows: {len(ct_rows)}, rebalance days: {len(rebal)}")

    sample = rebal[0]["weights"]
    panel_names = sorted(sample.keys())
    print(f"  panel ({len(panel_names)}): {panel_names[:5]} … {panel_names[-3:]}")

    print("[T-155] Back-solving w_① from cis_tilt_daily rows...", flush=True)
    w0_per_date: dict[str, dict[str, float]] = {}
    for r in rebal:
        d = r["d"]
        weights = r.get("weights") or {}
        z = r.get("z") or {}
        if weights:
            w0_per_date[d] = back_solve_w0(weights, z)

    rebal_dates_all = sorted(w0_per_date.keys())
    print(f"[T-155] {len(rebal_dates_all)} rebal dates: "
          f"{rebal_dates_all[0]} → {rebal_dates_all[-1]}")

    # ── 价格 ──────────────────────────────────────────────────────────────────
    print("[T-155] Fetching ohlcv_daily (binance_hist) for panel...", flush=True)
    px = fetch_ohlcv(panel_names)
    coverage = sum(1 for s in panel_names if len(px.get(s, {})) > 0)
    print(f"  panel price coverage: {coverage}/{len(panel_names)}")

    # ── 资金费率 ──────────────────────────────────────────────────────────────
    print("[T-155] Fetching funding_history (binance_perp) for panel...", flush=True)
    funding = fetch_funding(panel_names)
    fund_coverage = sum(1 for s in panel_names if len(funding.get(s, [])) > 0)
    print(f"  panel funding coverage: {fund_coverage}/{len(panel_names)}  "
          f"(total rows: {sum(len(v) for v in funding.values())})")

    # ── V0 NAV ─────────────────────────────────────────────────────────────────
    v0_nav_by_date, v0_turnover = run_weekly(
        rebal_dates_all, w0_per_date, px, panel_names, inception_nav=1.0)

    # ── V0 核对 ────────────────────────────────────────────────────────────────
    print("[T-155] Fetching multiplier_daily.core_u_replay for V0 cross-check...", flush=True)
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
    print(f"[T-155] V0 final NAV: my {final_v0_nav:.5f} @ {final_v0_date} | "
          f"reference {final_md_nav:.5f} @ {final_md_date}")
    print(f"  ratio my/ref: {final_v0_nav / final_md_nav:.5f}  "
          f"max_rel_diff: {max_diff_pct:.3f}%  median: {median_diff_pct:.3f}%  "
          f"({len(aligned)} aligned days)")
    v0_passes = max_diff_pct < 1.0
    if not v0_passes:
        print(f"[T-155] ❌ V0 reproduction FAIL: max_diff {max_diff_pct:.3f}% ≥ 1%; stop per S-640.")
        return 2

    # ── V3 资金费倾斜(7 日) ───────────────────────────────────────────────
    print(f"[T-155] Building V3 funding tilt ({FUND_LOOKBACK_DAYS}d, neg-z)...", flush=True)
    v3_w_per_date: dict[str, dict[str, float]] = {}
    z_fund_per_date: dict[str, dict[str, float]] = {}
    no_fund_count_per_rebal: list[int] = []  # 每期 z=0 因没资金费的山寨数
    for d in rebal_dates_all:
        z_f, n_obs = compute_funding_z(funding, d, FUND_LOOKBACK_DAYS, panel_names)
        z_fund_per_date[d] = z_f
        # 只有「该 rebal 日属于 d-7 … d-1 窗口里没资金费样本」的名字算缺
        alts = [s for s in panel_names if s not in PANEL_BTC_ETH]
        no_fund_count_per_rebal.append(sum(1 for s in alts if n_obs.get(s, 0) == 0))
        v3_w_per_date[d] = build_v3_weights(w0_per_date[d], z_f, panel_names, k=0.5)

    v3_nav_by_date, v3_turnover = run_weekly(
        rebal_dates_all, v3_w_per_date, px, panel_names, inception_nav=1.0)

    v3_total = nav_total(v3_nav_by_date)
    v0_total = nav_total(v0_nav_by_date)
    v3_total_holdout = nav_total_holdout(v3_nav_by_date)
    v0_total_holdout = nav_total_holdout(v0_nav_by_date)
    diff_all = v3_total - v0_total
    diff_holdout = v3_total_holdout - v0_total_holdout

    print(f"[T-155] V3 (funding) vs V0:")
    print(f"  V0 total: {v0_total:+.4f}   V3 total: {v3_total:+.4f}   diff: {diff_all:+.4f}")
    print(f"  V0 holdout: {v0_total_holdout:+.4f}   V3 holdout: {v3_total_holdout:+.4f}   "
          f"diff: {diff_holdout:+.4f}")

    # ── 200 次随机打乱 z_fund(每个再平衡日只在山寨里打乱) ─────────────
    print(f"[T-155] Running {N_SHUFFLES} shuffles of z_fund within 山寨...", flush=True)
    rng = np.random.default_rng(SEED)
    alts = [s for s in panel_names if s not in PANEL_BTC_ETH]
    shuffle_totals_full: list[float] = []
    shuffle_totals_holdout: list[float] = []
    for k in range(N_SHUFFLES):
        sh_w_per_date: dict[str, dict[str, float]] = {}
        for d in rebal_dates_all:
            sh_z = dict(z_fund_per_date[d])
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
    # 与 T-148 同口径:(V3 − V0) 分位 ⇒ shuffles − v0_total < diff_all
    diffs = s_full - v0_total
    pctile_v3_minus_v0 = float((diffs < diff_all).mean())

    print(f"  V3 percentile vs 200 shuffles (full): {pctile_full:.3f}")
    print(f"  V3 percentile vs 200 shuffles (holdout): {pctile_holdout:.3f}")
    print(f"  (V3−V0) percentile vs shuffles (full): {pctile_v3_minus_v0:.3f}")

    judgement_pass = (diff_all > 0) and (diff_holdout > 0) and (pctile_v3_minus_v0 > 0.95)

    # ── 最大回撤 ────────────────────────────────────────────────────────────────
    v0_dd = nav_max_dd(v0_nav_by_date)
    v3_dd = nav_max_dd(v3_nav_by_date)

    # ── 分年 ────────────────────────────────────────────────────────────────────
    yearly: dict[str, dict] = {}
    for d in rebal_dates_all:
        yr = d[:4]
        if yr not in yearly:
            yearly[yr] = {"first": None, "last_d": None}
    for d in rebal_dates_all:
        yr = d[:4]
        if yearly[yr]["first"] is None:
            yearly[yr]["first"] = d
            yearly[yr]["v0_first_nav"] = v0_nav_by_date[d]
            yearly[yr]["v3_first_nav"] = v3_nav_by_date[d]
        yearly[yr]["last_d"] = d
        yearly[yr]["v0_last_nav"] = v3_nav_by_date[d] and v0_nav_by_date[d]
        yearly[yr]["v0_last_nav"] = v0_nav_by_date[d]
        yearly[yr]["v3_last_nav"] = v3_nav_by_date[d]
    yearly_summaries = []
    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        v0_first = y["v0_first_nav"]
        v0_last = y["v0_last_nav"]
        v3_last = y["v3_last_nav"]
        yearly_summaries.append({
            "year": yr,
            "v0_ret": (v0_last / v0_first) - 1,
            "v3_ret": (v3_last / v0_first) - 1,
            "v3_minus_v0_pp": (v3_last / v0_first) - (v0_last / v0_first),
        })

    no_fund_arr = np.array(no_fund_count_per_rebal)
    no_fund_summary = {
        "min": int(no_fund_arr.min()),
        "max": int(no_fund_arr.max()),
        "mean": float(no_fund_arr.mean()),
        "median": float(np.median(no_fund_arr)),
    }

    out: dict = {
        "data_window": {
            "start": rebal_dates_all[0],
            "end": rebal_dates_all[-1],
            "n_rebalance": len(rebal_dates_all),
        },
        "panel": {"size": len(panel_names), "names": panel_names,
                  "pinned": list(PANEL_BTC_ETH)},
        "funding_coverage": {
            "panel_with_funding": fund_coverage,
            "panel_total": len(panel_names),
            "no_funding_per_rebal": no_fund_summary,
        },
        "v0_check": {
            "final_nav_my": round(final_v0_nav, 5),
            "final_nav_reference": round(final_md_nav, 5),
            "ratio": round(final_v0_nav / final_md_nav, 5),
            "max_relative_diff_pct": round(max_diff_pct, 4),
            "median_relative_diff_pct": round(median_diff_pct, 4),
            "n_aligned_days": len(aligned),
            "passes_1pct": bool(v0_passes),
        },
        "v3_funding": {
            "lookback_days": FUND_LOOKBACK_DAYS,
            "negate_z": True,
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
        "yearly": yearly_summaries,
        "judgement_pass": bool(judgement_pass),
        "n_shuffles": N_SHUFFLES,
        "cost_bps": COST_BPS,
    }

    out_path = ROOT / "docs" / "research" / "t155_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[T-155] results written: {out_path}")
    print(f"  judgement: {'✅ PASS' if judgement_pass else '❌ FAIL'}")
    return 0 if judgement_pass else 1


if __name__ == "__main__":
    sys.exit(main())
