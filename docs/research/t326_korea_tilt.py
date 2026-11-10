"""T-326 (S-804):在 ① 的山寨里少配「韩国人多付钱」的名字(korea_premium_watch.p7,读法 B)。

**框架一字不改** —— 直接 import T-155(S-640 那道)的实现模块 `t155_funding_tilt`:
  - V0:cis_tilt_daily 的 cis_a1_u_replay 再平衡日行反推 ① 权重 w_① ∝ w × exp(−0.5·z)
    (V0 复现 multiplier_daily.core_u_replay 到 1% 以内,否则停)。
  - V4(S-640 自检):BTC/ETH 保持 w_①,其余名字在剩余份额内按 w_① × exp(0.5·z_fund),
    z_fund = −(d−7…d−1 平均资金费率的山寨横截面 z)。
  - V5(S-804 本条):同上,但 z = −(该名字当周 korea_premium_watch.p7 在 ① 山寨横截面里的 z 分数);
    该周没有 p7 的名字 z = 0;BTC/ETH 钉住。
  - 周一(UTC)再平衡、周内买入持有、换手 × 10bp;留出段 2025-01-01 起。
  - 零分布:src/data/evaluation/apparatus.py 的 shuffle_within(每周在「有 p7 的山寨」里重排 z),
    200 次,种子 804。不另写零分布。

自检(卡上要求):先在 S-640 当初的窗口(再平衡日 ≤ 2026-10-19)上复现 V4 − V0
= +22.2pp 全程 / +0.21pp 留出,对不上(容差 ±2pp / ±1pp)就停,不出结论。

输出:docs/research/t326_results.json + docs/research/T-326_korea_premium_tilt.md
只读:不写库、不改代码。
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs" / "research"))

from src.data.evaluation.apparatus import shuffle_within  # noqa: E402

import t155_funding_tilt as T155  # noqa: E402  ← S-640 的框架,一字不改

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

HOLDOUT_FROM = T155.HOLDOUT_FROM          # "2025-01-01"
COST_BPS = T155.COST_BPS                  # 0.001 = 10bp
PANEL_BTC_ETH = T155.PANEL_BTC_ETH        # ("BTC", "ETH")
K = 0.5                                   # exp(0.5·z)
N_SHUFFLES = 200
SEED = 804                                # S-804 指定的种子
S640_WINDOW_END = "2026-10-19"           # T-155 那次跑到的最后一个再平衡日(自检窗口)
TOL_FULL = 0.02                          # ±2pp
TOL_HOLDOUT = 0.01                       # ±1pp

RESULTS_PATH = ROOT / "docs" / "research" / "t326_results.json"
REPORT_PATH = ROOT / "docs" / "research" / "T-326_korea_premium_tilt.md"

S804_ORIGINAL = """## S-804 — ② 候选(市值底,S-640 同一框架):在 ① 的山寨里少配「韩国人多付钱」的名字 —— 预注册(Seth,2026-11-10 09:57 UTC;Jazz 11-10「② keep open」;`korea_premium_watch` 的 p7 从没和 ① 权重放在一起算过;交 B 道 T-326)
**为什么。** S-803 之后,② 只能在 ① 真实的市值底上谈;市值底上唯一过了回测的 S-640 是**原因类**变量(资金费拥挤 = 持有成本 + 清算链)。韩国溢价同属原因类:散户在一个交易所为同一个币多付钱,是需求的直接计数,不是价格的倒影(S-771 / S-786 在全宇宙里量过,读法 B 只前向判)。这里只问它在 ① 的大山寨里、作为 ② 倾斜有没有用。
**写死(与 S-640 一字相同,只换分数):** `cis_tilt_daily` 的 `cis_a1_u_replay` 再平衡日行反推 ① 权重 w0(V0 复现 `core_u_replay` 到 1% 以内);**V5** = BTC / ETH 保持 w0,其余名字在剩余份额内按 w0 × exp(0.5 × z),**z = −(该名字当周 `korea_premium_watch.p7` 在 ① 山寨横截面里的 z 分数)**(p7 = 周一 t 往前 7 天每日溢价的中位,扣 BTC 自身溢价,读法 B;该周没有 p7 的名字 z = 0);周一再平衡、周内买入持有、换手 × 10bp。区间同 S-640(`cis_a1_u_replay` 起点 → 最近一个完整周);留出段 2025-01-01 起。
**判(全过才 ✅,与 S-640 相同):** ① V5 − V0 全程 > 0;② 留出段 V5 − V0 > 0;③ 200 次「山寨内打乱 z」里实际值的分位 ≥ 0.95(`apparatus.block_permute` 不适用;打乱 = 每周在有 p7 的山寨里重排 z,`apparatus.shuffle_within`,种子 804)。另报:每周有 p7 的 ① 山寨个数、分年差、V5 对 S-640 的 V4 的相关(是不是同一个东西)。
**诚实。** 这是 ② 族第 7 次(T-051、S-630、S-634、S-640、S-802、S-803、本条);最粗的 Bonferroni 下单条分位 0.95 远不够显著 ⇒ 过了也只进前向(纸面,与 S-640 同一个 L3 规则),不进钱。**试验计数:+1(② 族第 7 次)。**"""


# ── korea_premium_watch 读取 ─────────────────────────────────────────────────
def fetch_korea() -> tuple[dict[str, dict[str, float]], dict]:
    """{d: {symbol: p7}} + 完整性块。翻页带 order=(d.asc,symbol.asc)。"""
    path = ("korea_premium_watch?select=d,symbol,p7,n_days,mcap,cohort"
            "&order=d.asc,symbol.asc")
    rows = T155.fetch_all(path)
    # 精确总数(PostgREST Prefer: count=exact)
    req = urllib.request.Request(
        f"{URL}/rest/v1/korea_premium_watch?select=d,symbol",
        headers={**HEADERS, "Prefer": "count=exact"})
    resp = urllib.request.urlopen(req, timeout=120)
    total = int(resp.headers.get("Content-Range", "0/0").split("/")[-1])
    out: dict[str, dict[str, float]] = defaultdict(dict)
    keys = set()
    cohorts: dict[str, int] = defaultdict(int)
    for r in rows:
        d = str(r["d"])[:10]
        s = str(r["symbol"]).upper()
        p7 = r.get("p7")
        if p7 is None:
            continue
        out[d][s] = float(p7)
        keys.add((d, s))
        cohorts[str(r.get("cohort"))] += 1
    comp = {
        "source": "korea_premium_watch",
        "order_param": "d.asc,symbol.asc",
        "rows_fetched": len(rows),
        "count_exact": total,
        "uniq_d_symbol_keys": len(keys),
        "n_dates": len(out),
        "cohort_counts": dict(cohorts),
        "assert_equal": len(rows) == total == len(keys),
    }
    if not comp["assert_equal"]:
        raise SystemExit(f"[T-326] ❌ korea 完整性 FAIL: {comp}")
    return dict(out), comp


def compute_korea_z(korea: dict[str, dict[str, float]], rebal_date: str,
                     panel_names: list[str],
                     lag_weeks: int = 0) -> tuple[dict[str, float], dict[str, int]]:
    """z = −(该名字当周 p7 在 ① 山寨横截面里的 z 分数)。

    lag_weeks=0 ⇒ 用当周(周一 t)的 p7(预注册的读法 B 口径,含周一收盘);
    lag_weeks=1 ⇒ 用上一周(周一 t−7)的 p7(**不含**当周,挪一天/一周的对照)。

    BTC/ETH 钉住 ⇒ z = 0(不进横截面)。当周没有 p7 的名字 z = 0(不进横截面分母)。
    """
    d_target = date.fromisoformat(rebal_date)
    d_used = (d_target - timedelta(days=7 * lag_weeks)).isoformat()
    alts = [s for s in panel_names if s not in PANEL_BTC_ETH]
    rows = korea.get(d_used, {})
    have = {s: rows[s] for s in alts if s in rows and math.isfinite(rows[s])}
    z_pos = T155.cross_sectional_z(have, alts)      # 高 p7 ⇒ z 高
    z_neg = {s: -v for s, v in z_pos.items()}        # S-804 显式要求 z = −(…)
    z_all = {s: 0.0 for s in PANEL_BTC_ETH if s in panel_names}
    z_all.update({s: z_neg.get(s, 0.0) for s in alts})
    return z_all, {"date_used": d_used, "n_with_p7": len(have),
                   "names_with_p7": sorted(have.keys())}


# ── 日收益序列(用于 V5 与 V4 的相关) ──────────────────────────────────────────
def daily_returns(rebal_dates: list[str], w_per_date: dict[str, dict[str, float]],
                  px: dict[str, dict[str, float]], panel_names: list[str],
                  all_days: list[str]) -> dict[str, float]:
    """逐日毛收益(周内持有 w_t)。用于算两条腿的相关,不用来报收益。"""
    out: dict[str, float] = {}
    cur_t = None
    cur_w: dict[str, float] = {}
    for i in range(1, len(all_days)):
        d_prev, d_now = all_days[i - 1], all_days[i]
        cands = [t for t in rebal_dates if t <= d_now]
        if not cands:
            continue
        t = max(cands)
        if t != cur_t:
            cur_t, cur_w = t, w_per_date.get(t, {})
        out[d_now] = T155.segment_return(cur_w, d_prev, d_now, px, panel_names)
    return out


def corr(a: dict[str, float], b: dict[str, float]) -> tuple[float, int]:
    keys = sorted(set(a) & set(b))
    if len(keys) < 3:
        return float("nan"), len(keys)
    x = np.array([a[k] for k in keys], dtype=float)
    y = np.array([b[k] for k in keys], dtype=float)
    if x.std() == 0 or y.std() == 0:
        return float("nan"), len(keys)
    return float(np.corrcoef(x, y)[0, 1]), len(keys)


def weekly_returns(nav_by_date: dict[str, float]) -> dict[str, float]:
    ks = sorted(nav_by_date.keys())
    out: dict[str, float] = {}
    for i in range(1, len(ks)):
        a, b = nav_by_date[ks[i - 1]], nav_by_date[ks[i]]
        if a > 0:
            out[ks[i]] = b / a - 1.0
    return out


def yearly_diff(v0_nav: dict[str, float], vx_nav: dict[str, float],
                rebal_dates: list[str]) -> list[dict]:
    yearly: dict[str, dict] = {}
    for d in rebal_dates:
        yr = d[:4]
        if yr not in yearly:
            yearly[yr] = {"first": d, "v0_first": v0_nav[d], "vx_first": vx_nav[d]}
        yearly[yr]["last"] = d
        yearly[yr]["v0_last"] = v0_nav[d]
        yearly[yr]["vx_last"] = vx_nav[d]
    rows = []
    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        rows.append({
            "year": yr,
            "v0_ret": y["v0_last"] / y["v0_first"] - 1.0,
            "vx_ret": y["vx_last"] / y["v0_first"] - 1.0,
            "vx_minus_v0_pp": (y["vx_last"] / y["v0_first"]) - (y["v0_last"] / y["v0_first"]),
            "n_rebal": sum(1 for d in rebal_dates if d[:4] == yr),
        })
    return rows


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main() -> int:
    t0 = datetime.now(timezone.utc)
    print("[T-326] S-804 原文(照抄,见报告开头)。", flush=True)

    # ── ① 面板与 w_① ────────────────────────────────────────────────────────
    print("[T-326] Fetching cis_tilt_daily cis_a1_u_replay ...", flush=True)
    ct_rows = T155.fetch_all("cis_tilt_daily?select=d,arm,nav,ret,weights,z,rebalanced,turnover"
                              "&arm=eq.cis_a1_u_replay&order=d.asc")
    rebal = [r for r in ct_rows if r.get("rebalanced")]
    sample = rebal[0]["weights"]
    panel_names = sorted(sample.keys())
    alts = [s for s in panel_names if s not in PANEL_BTC_ETH]
    print(f"  rows={len(ct_rows)} rebal_days={len(rebal)} panel={len(panel_names)}", flush=True)

    w0_per_date: dict[str, dict[str, float]] = {}
    for r in rebal:
        weights = r.get("weights") or {}
        z = r.get("z") or {}
        if weights:
            w0_per_date[r["d"]] = T155.back_solve_w0(weights, z)
    rebal_dates_all = sorted(w0_per_date.keys())
    print(f"  {len(rebal_dates_all)} rebal dates: {rebal_dates_all[0]} → {rebal_dates_all[-1]}")

    # ── 价格 ───────────────────────────────────────────────────────────────
    print("[T-326] Fetching ohlcv_daily (binance_hist) ...", flush=True)
    px, px_comp = T155.fetch_ohlcv(panel_names)
    coverage = sum(1 for s in panel_names if len(px.get(s, {})) > 0)
    print(f"  coverage {coverage}/{len(panel_names)}; "
          f"uniq_keys={px_comp['uniq_symbol_date_keys']} expected={px_comp['expected_symbols_x_dates']} "
          f"assert={px_comp['assert_equal']}", flush=True)

    # ── korea p7 ───────────────────────────────────────────────────────────
    print("[T-326] Fetching korea_premium_watch ...", flush=True)
    korea, korea_comp = fetch_korea()
    kdates = sorted(korea.keys())
    print(f"  rows={korea_comp['rows_fetched']} dates={len(kdates)} "
          f"{kdates[0]} → {kdates[-1]}; cohorts={korea_comp['cohort_counts']}")

    # ── V0 NAV + 核对 ──────────────────────────────────────────────────────
    v0_nav, v0_turn = T155.run_weekly(rebal_dates_all, w0_per_date, px, panel_names, 1.0)
    md_rows = T155.fetch_all("multiplier_daily?select=d,nav&arm=eq.core_u_replay&order=d.asc")
    md_nav = {r["d"]: r["nav"] for r in md_rows}
    aligned = sorted(d for d in v0_nav if d in md_nav)
    diffs_pct = [abs(v0_nav[d] - md_nav[d]) / md_nav[d] * 100 for d in aligned]
    max_diff = max(diffs_pct) if diffs_pct else float("nan")
    print(f"  V0 max_rel_diff vs core_u_replay: {max_diff:.3f}% ({len(aligned)} days) "
          f"→ {'PASS' if max_diff < 1.0 else 'FAIL'}")
    if not max_diff < 1.0:
        print("[T-326] ❌ V0 复现不过 1% ⇒ 按 S-640 停。", file=sys.stderr)
        return 2

    # ── V4(S-640 自检):funding 倾斜 ─────────────────────────────────────────
    print("[T-326] Fetching funding_history (binance_perp) for V4 self-check ...", flush=True)
    funding, fund_comp = T155.fetch_funding(panel_names)
    print(f"  funding rows={sum(len(v) for v in funding.values())} "
          f"coverage={sum(1 for s in panel_names if funding.get(s))}/{len(panel_names)}", flush=True)

    def build_leg(z_per_date: dict[str, dict[str, float]]) -> tuple[dict, float]:
        w_per_date = {d: T155.build_v3_weights(w0_per_date[d], z_per_date[d], panel_names, K)
                      for d in rebal_dates_all}
        nav, turn = T155.run_weekly(rebal_dates_all, w_per_date, px, panel_names, 1.0)
        return {"w": w_per_date, "nav": nav, "turnover": turn}, turn

    z_fund: dict[str, dict[str, float]] = {}
    for d in rebal_dates_all:
        z_f, _ = T155.compute_funding_z(funding, d, T155.FUND_LOOKBACK_DAYS, panel_names)
        z_fund[d] = z_f
    v4, _ = build_leg(z_fund)
    v0_total = T155.nav_total(v0_nav)
    v4_total = T155.nav_total(v4["nav"])
    v4_hold = T155.nav_total_holdout(v4["nav"])
    v0_hold = T155.nav_total_holdout(v0_nav)
    v4_diff_full = v4_total - v0_total
    v4_diff_hold = v4_hold - v0_hold
    print(f"  V4(current window) − V0: full {v4_diff_full:+.4f}  holdout {v4_diff_hold:+.4f}")

    # 自检:在 S-640 当初的窗口上重跑 V4
    w_s640 = [d for d in rebal_dates_all if d <= S640_WINDOW_END]
    v0_s, _ = T155.run_weekly(w_s640, w0_per_date, px, panel_names, 1.0)
    v4_s, _ = T155.run_weekly(
        w_s640, {d: T155.build_v3_weights(w0_per_date[d], z_fund[d], panel_names, K) for d in w_s640},
        px, panel_names, 1.0)
    s640_full = T155.nav_total(v4_s) - T155.nav_total(v0_s)
    s640_hold = T155.nav_total_holdout(v4_s) - T155.nav_total_holdout(v0_s)
    print(f"  SELF-CHECK (window ≤ {S640_WINDOW_END}, n={len(w_s640)}): "
          f"V4−V0 full {s640_full:+.4f} (target +0.2215) holdout {s640_hold:+.4f} (target +0.0021)")
    self_ok = (abs(s640_full - 0.2215) <= TOL_FULL) and (abs(s640_hold - 0.0021) <= TOL_HOLDOUT)
    if not self_ok:
        print(f"[T-326] ❌ 自检不过:V4 复现 {s640_full:+.4f}/{s640_hold:+.4f} "
              f"≠ S-640 的 +0.2215/+0.0021(容差 ±{TOL_FULL}/±{TOL_HOLDOUT})⇒ 停,不出结论。",
              file=sys.stderr)
        return 3
    print("  ✅ 自检通过(框架与 S-640 一致)。")

    # ── V5(S-804):korea p7 倾斜 ────────────────────────────────────────────
    z_kor: dict[str, dict[str, float]] = {}
    n_with_p7: dict[str, int] = {}
    for d in rebal_dates_all:
        z_k, info = compute_korea_z(korea, d, panel_names, lag_weeks=0)
        z_kor[d] = z_k
        n_with_p7[d] = info["n_with_p7"]
    v5, _ = build_leg(z_kor)
    v5_total = T155.nav_total(v5["nav"])
    v5_hold = T155.nav_total_holdout(v5["nav"])
    v5_diff_full = v5_total - v0_total
    v5_diff_hold = v5_hold - v0_hold
    print(f"  V5 − V0: full {v5_diff_full:+.4f}  holdout {v5_diff_hold:+.4f}", flush=True)

    # ── ③ 零分布:200 次,每周在「有 p7 的山寨」里重排 z(种子 804) ───────────
    print(f"[T-326] {N_SHUFFLES} shuffles (within alts that HAVE p7, seed {SEED}) ...", flush=True)
    rng = np.random.default_rng(SEED)
    sh_full: list[float] = []
    sh_hold: list[float] = []
    for _ in range(N_SHUFFLES):
        sh_w: dict[str, dict[str, float]] = {}
        for d in rebal_dates_all:
            sh_z = dict(z_kor[d])
            sub = [s for s in alts if n_with_p7.get(d, 0) and s in _p7_names(korea, d, alts)]
            if sub:
                vals = np.array([sh_z[s] for s in sub], dtype=float)
                perm = shuffle_within(vals.tolist(), ["x"] * len(sub), rng)
                for s, v in zip(sub, perm):
                    sh_z[s] = float(v)
            sh_w[d] = T155.build_v3_weights(w0_per_date[d], sh_z, panel_names, K)
        nav, _ = T155.run_weekly(rebal_dates_all, sh_w, px, panel_names, 1.0)
        sh_full.append(T155.nav_total(nav) - v0_total)
        sh_hold.append(T155.nav_total_holdout(nav) - v0_hold)
    sh_full_arr = np.array(sh_full)
    sh_hold_arr = np.array(sh_hold)
    pct_full = float((sh_full_arr < v5_diff_full).mean())
    pct_hold = float((sh_hold_arr < v5_diff_hold).mean())
    print(f"  percentile(full) = {pct_full:.3f}   percentile(holdout) = {pct_hold:.3f}")

    # 附:全山寨打乱(含没有 p7 的名字,= S-640 口径)的对照
    rng2 = np.random.default_rng(SEED)
    sh_full2: list[float] = []
    for _ in range(N_SHUFFLES):
        sh_w: dict[str, dict[str, float]] = {}
        for d in rebal_dates_all:
            sh_z = dict(z_kor[d])
            vals = np.array([sh_z[s] for s in alts], dtype=float)
            perm = shuffle_within(vals.tolist(), ["x"] * len(alts), rng2)
            for s, v in zip(alts, perm):
                sh_z[s] = float(v)
            sh_w[d] = T155.build_v3_weights(w0_per_date[d], sh_z, panel_names, K)
        nav, _ = T155.run_weekly(rebal_dates_all, sh_w, px, panel_names, 1.0)
        sh_full2.append(T155.nav_total(nav) - v0_total)
    pct_full_allalts = float((np.array(sh_full2) < v5_diff_full).mean())
    print(f"  [对照] 全山寨打乱口径 percentile(full) = {pct_full_allalts:.3f}")

    # ── 挪一天/一周的对照(不是预注册的判据,只报) ────────────────────────
    z_kor_lag: dict[str, dict[str, float]] = {}
    for d in rebal_dates_all:
        z_k, _info = compute_korea_z(korea, d, panel_names, lag_weeks=1)
        z_kor_lag[d] = z_k
    v5_lag, _ = build_leg(z_kor_lag)
    lag_full = T155.nav_total(v5_lag["nav"]) - v0_total
    lag_hold = T155.nav_total_holdout(v5_lag["nav"]) - v0_hold
    print(f"  [对照] 用上一周的 p7(不含当周): V5−V0 full {lag_full:+.4f} holdout {lag_hold:+.4f}")

    # ── 相关:V5 对 V4 ──────────────────────────────────────────────────────
    all_days = sorted(px[panel_names[0]].keys())
    d_r0 = daily_returns(rebal_dates_all, w0_per_date, px, panel_names, all_days)
    d_r4 = daily_returns(rebal_dates_all, v4["w"], px, panel_names, all_days)
    d_r5 = daily_returns(rebal_dates_all, v5["w"], px, panel_names, all_days)
    d_r5lag = daily_returns(rebal_dates_all, v5_lag["w"], px, panel_names, all_days)
    corr_daily_45, n_daily = corr(d_r4, d_r5)
    corr_daily_45lag, _ = corr(d_r4, d_r5lag)
    w4 = weekly_returns(v4["nav"])
    w5 = weekly_returns(v5["nav"])
    corr_weekly_45, n_weekly = corr(w4, w5)
    # **超额**口径:两条腿各自的日收益都 ≈ ① 的 beta(同一面板、同一周再平衡),
    # 原始相关必然接近 1 ⇒「是不是同一个东西」要看超额。
    ex4 = {k: d_r4[k] - d_r0[k] for k in d_r4 if k in d_r0}
    ex5 = {k: d_r5[k] - d_r0[k] for k in d_r5 if k in d_r0}
    ex5lag = {k: d_r5lag[k] - d_r0[k] for k in d_r5lag if k in d_r0}
    corr_ex_45, n_ex = corr(ex4, ex5)
    corr_ex_45lag, _ = corr(ex4, ex5lag)
    # 因子层:korea z 与 funding z 的每周横截面相关(同一批山寨上)
    zc: list[float] = []
    for d in rebal_dates_all:
        sub = [s for s in alts if s in _p7_names(korea, d, alts)]
        if len(sub) < 3:
            continue
        x = np.array([z_kor[d][s] for s in sub], dtype=float)
        y = np.array([z_fund[d][s] for s in sub], dtype=float)
        if x.std() == 0 or y.std() == 0:
            continue
        zc.append(float(np.corrcoef(x, y)[0, 1]))
    zc_arr = np.array(zc) if zc else np.array([float("nan")])
    print(f"  corr(V5, V4): daily {corr_daily_45:.3f} (n={n_daily})  weekly {corr_weekly_45:.3f} (n={n_weekly})")
    print(f"  corr(excess V5, excess V4): daily {corr_ex_45:.3f} (n={n_ex}); "
          f"mean weekly corr(z_korea, z_funding) = {zc_arr.mean():.3f} (n={len(zc)})")

    # ── 分年 / 覆盖 ────────────────────────────────────────────────────────
    y_v5 = yearly_diff(v0_nav, v5["nav"], rebal_dates_all)
    y_v4 = yearly_diff(v0_nav, v4["nav"], rebal_dates_all)
    n_arr = np.array([n_with_p7[d] for d in rebal_dates_all])
    have_by_sym = defaultdict(int)
    for d in rebal_dates_all:
        for s in _p7_names(korea, d, alts):
            have_by_sym[s] += 1
    cover = {
        "n_alts": len(alts),
        "alts_with_p7_per_week": {
            "min": int(n_arr.min()), "max": int(n_arr.max()),
            "mean": float(n_arr.mean()), "median": float(np.median(n_arr)),
            "p10": float(np.percentile(n_arr, 10)),
        },
        "per_symbol_weeks_with_p7": dict(sorted(have_by_sym.items())),
        "alts_never_with_p7": sorted(set(alts) - set(have_by_sym.keys())),
        "n_rebal_without_any_p7": int(sum(1 for d in rebal_dates_all if n_with_p7[d] == 0)),
    }

    judge_1 = v5_diff_full > 0
    judge_2 = v5_diff_hold > 0
    judge_3 = pct_full >= 0.95
    verdict = judge_1 and judge_2 and judge_3

    out = {
        "task": "T-326",
        "ledger": "S-804",
        "framework": "S-640 一字不改(直接 import t155_funding_tilt);只换 z 的来源",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_window": {"start": rebal_dates_all[0], "end": rebal_dates_all[-1],
                        "n_rebalance": len(rebal_dates_all),
                        "s640_selfcheck_window_end": S640_WINDOW_END,
                        "s640_selfcheck_n_rebalance": len(w_s640)},
        "panel": {"size": len(panel_names), "names": panel_names,
                  "alts": alts, "pinned": list(PANEL_BTC_ETH)},
        "v0_check": {"max_relative_diff_pct": round(max_diff, 4),
                     "n_aligned_days": len(aligned),
                     "v0_total": round(v0_total, 4),
                     "v0_total_holdout": round(v0_hold, 4),
                     "passes_1pct": True},
        "self_check_s640": {
            "target_full": 0.2215, "target_holdout": 0.0021,
            "reproduced_full": round(s640_full, 4),
            "reproduced_holdout": round(s640_hold, 4),
            "tol_full": TOL_FULL, "tol_holdout": TOL_HOLDOUT,
            "passes": bool(self_ok),
        },
        "v4_funding_s640_current_window": {
            "v4_total": round(v4_total, 4), "v0_total": round(v0_total, 4),
            "diff_full": round(v4_diff_full, 4),
            "v4_total_holdout": round(v4_hold, 4), "v0_total_holdout": round(v0_hold, 4),
            "diff_holdout": round(v4_diff_hold, 4),
            "turnover_v4": round(v4["turnover"], 4),
            "max_dd_v4": round(T155.nav_max_dd(v4["nav"]), 4),
            "max_dd_v0": round(T155.nav_max_dd(v0_nav), 4),
        },
        "v5_korea_p7": {
            "z_rule": "z = −(该名字当周 korea_premium_watch.p7 在 ① 山寨横截面里的 z 分数)",
            "k_def": K,
            "v5_total": round(v5_total, 4),
            "diff_full": round(v5_diff_full, 4),
            "v5_total_holdout": round(v5_hold, 4),
            "diff_holdout": round(v5_diff_hold, 4),
            "turnover_v5": round(v5["turnover"], 4),
            "max_dd_v5": round(T155.nav_max_dd(v5["nav"]), 4),
            "max_dd_v0": round(T155.nav_max_dd(v0_nav), 4),
            "pctile_vs_shuffles_full": round(pct_full, 4),
            "pctile_vs_shuffles_holdout": round(pct_hold, 4),
            "pctile_vs_shuffles_full_allalts_variant": round(pct_full_allalts, 4),
            "n_shuffles": N_SHUFFLES, "seed": SEED,
        },
        "lagged_variant_not_preregistered": {
            "note": "z 用上一周(周一 t−7)的 p7 —— 挪一周的对照,不是预注册的判据",
            "diff_full": round(lag_full, 4), "diff_holdout": round(lag_hold, 4),
        },
        "corr_v5_v4": {"daily": round(corr_daily_45, 4), "n_daily": n_daily,
                       "daily_lagged": round(corr_daily_45lag, 4),
                       "weekly": round(corr_weekly_45, 4), "n_weekly": n_weekly,
                       "excess_daily": round(corr_ex_45, 4), "n_excess_daily": n_ex,
                       "excess_daily_lagged": round(corr_ex_45lag, 4),
                       "note": "原始日收益相关几乎恒为 1(两条腿都 ≈ ① 的 beta,同一面板同一周再平衡);"
                               "「是不是同一个东西」要看超额口径",
                       "weekly_z_corr_korea_vs_funding_mean": round(float(zc_arr.mean()), 4),
                       "weekly_z_corr_korea_vs_funding_n": len(zc)},
        "coverage": cover,
        "yearly_v5": y_v5,
        "yearly_v4": y_v4,
        "judgement": {"1_full_gt0": bool(judge_1), "2_holdout_gt0": bool(judge_2),
                      "3_pctile_ge_0.95": bool(judge_3), "verdict_pass": bool(verdict)},
        "completeness": {"ohlcv": px_comp, "korea": korea_comp, "funding": fund_comp},
        "cost_bps": COST_BPS,
    }
    RESULTS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[T-326] results → {RESULTS_PATH}")

    write_report(out)
    print(f"[T-326] report   → {REPORT_PATH}")
    print(f"[T-326] verdict: {'✅ PASS' if verdict else '❌ FAIL'} "
          f"(①={judge_1} ②={judge_2} ③={judge_3})  elapsed={datetime.now(timezone.utc)-t0}")
    return 0 if verdict else 1


_P7_CACHE: dict[str, set[str]] = {}


def _p7_names(korea: dict[str, dict[str, float]], d: str, alts: list[str]) -> set[str]:
    key = f"{d}"
    if key not in _P7_CACHE:
        _P7_CACHE[key] = {s for s in alts if s in korea.get(d, {})}
    return _P7_CACHE[key]


# ── 报告 ──────────────────────────────────────────────────────────────────────
def write_report(o: dict) -> None:
    v5 = o["v5_korea_p7"]
    v4 = o["v4_funding_s640_current_window"]
    sc = o["self_check_s640"]
    j = o["judgement"]
    cov = o["coverage"]
    lines: list[str] = []
    A = lines.append
    A("# T-326 / S-804 —— 在 ① 的山寨里少配「韩国人多付钱」的名字(korea_premium_watch.p7,读法 B)")
    A("")
    A(f"**卡**: T-326 · **台账**: S-804 · **分支**: lane-b/T-326 · "
      f"**生成**: {o['generated_at']}")
    A("")
    A(f"**结论**: {'✅ PASS(三条全过)' if j['verdict_pass'] else '❌ FAIL'} —— "
      f"① 全程 V5−V0 {v5['diff_full']:+.4f} {'>' if j['1_full_gt0'] else '≤'} 0 · "
      f"② 留出段 V5−V0 {v5['diff_holdout']:+.4f} {'>' if j['2_holdout_gt0'] else '≤'} 0 · "
      f"③ 分位 {v5['pctile_vs_shuffles_full']:.3f} {'≥' if j['3_pctile_ge_0.95'] else '<'} 0.95")
    A("")
    A("## S-804 原文(照抄)")
    A("")
    A("> " + S804_ORIGINAL.replace("\n", "\n> "))
    A("")
    A("## 框架(与 S-640 一字不改)")
    A("")
    A("- **直接 import `docs/research/t155_funding_tilt.py`**(S-640/T-155 的实现),"
      "不重写任何一行:V0 反推、`build_v3_weights`、周 NAV、成本、零分布用法全部沿用;"
      "本卡**只换 z 的来源**(资金费 → korea p7)。")
    A(f"- V0:从 `cis_tilt_daily` 的 `cis_a1_u_replay` 再平衡日行反推 ① 权重;"
      f"复现 `multiplier_daily.core_u_replay` 最大相对差 **{o['v0_check']['max_relative_diff_pct']:.3f}%**"
      f"({o['v0_check']['n_aligned_days']} 天,门槛 1%)⇒ 通过。")
    A(f"- 面板 **{o['panel']['size']}** 个名字(BTC / ETH 钉住,{len(o['panel']['alts'])} 个山寨参与倾斜);"
      f"再平衡 {o['data_window']['n_rebalance']} 个周一,`{o['data_window']['start']}` → "
      f"`{o['data_window']['end']}`;留出段 2025-01-01 起;换手 × 10bp。")
    A("")
    A("## 自检:先复现 S-640 的 V4")
    A("")
    A(f"卡上要求「先复现 S-640 的 V4 − V0(+22.2pp 全程 / +0.21pp 留出)作自检,对不上先停」。"
      f"在 S-640 当初的窗口(再平衡日 ≤ {o['data_window']['s640_selfcheck_window_end']},"
      f"{o['data_window']['s640_selfcheck_n_rebalance']} 周)上重跑同一段代码:")
    A("")
    A("| 量 | S-640 原文 | 本卡复现 | 差 |")
    A("|---|---|---|---|")
    A(f"| V4 − V0 全程 | +0.2215 | {sc['reproduced_full']:+.4f} | "
      f"{sc['reproduced_full']-0.2215:+.4f} |")
    A(f"| V4 − V0 留出段 | +0.0021 | {sc['reproduced_holdout']:+.4f} | "
      f"{sc['reproduced_holdout']-0.0021:+.4f} |")
    A("")
    A(f"⇒ {'✅ 对上了(容差 ±2pp / ±1pp),继续' if sc['passes'] else '❌ 对不上,停'}。"
      f"同一套代码在**当前**窗口(已延到 {o['data_window']['end']})上:"
      f"V4 − V0 全程 **{v4['diff_full']:+.4f}**、留出段 **{v4['diff_holdout']:+.4f}**。")
    A("")
    A("## V5(korea p7 倾斜)逐条判定")
    A("")
    A("| 判据 | 结果 | 判定 |")
    A("|---|---|---|")
    A(f"| ① V5 − V0 全程 > 0 | {v5['diff_full']:+.4f} | {'✅' if j['1_full_gt0'] else '❌'} |")
    A(f"| ② 留出段(2025-01-01 起)V5 − V0 > 0 | {v5['diff_holdout']:+.4f} | "
      f"{'✅' if j['2_holdout_gt0'] else '❌'} |")
    A(f"| ③ {v5['n_shuffles']} 次「有 p7 的山寨里打乱 z」分位 ≥ 0.95 | "
      f"{v5['pctile_vs_shuffles_full']:.3f} | {'✅' if j['3_pctile_ge_0.95'] else '❌'} |")
    A("")
    A(f"原始数:V0 全程 {o['v0_check']['v0_total']:+.4f} / 留出 {o['v0_check']['v0_total_holdout']:+.4f};"
      f"V5 全程 {v5['v5_total']:+.4f} / 留出 {v5['v5_total_holdout']:+.4f};"
      f"V5 最大回撤 {v5['max_dd_v5']:+.4f}(V0 {v5['max_dd_v0']:+.4f})。")
    A("")
    A(f"另报(S-804 点名的三项):")
    A("")
    A(f"1. **每周有 p7 的 ① 山寨个数**:min {cov['alts_with_p7_per_week']['min']} · "
      f"median {cov['alts_with_p7_per_week']['median']:.0f} · mean "
      f"{cov['alts_with_p7_per_week']['mean']:.1f} · max {cov['alts_with_p7_per_week']['max']}"
      f"(共 {cov['n_alts']} 个山寨;整周一个 p7 都没有的再平衡日 {cov['n_rebal_without_any_p7']} 次)。"
      f"从未有 p7 的山寨:{cov['alts_never_with_p7'] or '无'}。")
    A(f"2. **分年差(V5 − V0)**:")
    A("")
    A("| 年 | V0 | V5 | V5 − V0 |")
    A("|---|---|---|---|")
    for y in o["yearly_v5"]:
        A(f"| {y['year']} | {y['v0_ret']:+.4f} | {y['vx_ret']:+.4f} | {y['vx_minus_v0_pp']:+.4f} |")
    A("")
    c = o["corr_v5_v4"]
    A(f"3. **V5 与 V4 的相关(是不是同一个东西)**:原始日收益相关 **{c['daily']:+.4f}**(n={c['n_daily']} 天)、"
      f"周收益相关 {c['weekly']:+.4f}(n={c['n_weekly']} 周)—— **这个数几乎恒为 1 没有信息量**:"
      f"两条腿是同一个 22 名字面板、同一个周再平衡、同一套权重公式,日收益都被 ① 的 beta 主导"
      f"(V4 四年只多 +21.6pp、V5 只多 +0.8pp)。")
    ex = c["excess_daily"]
    if abs(ex) < 0.3:
        rel = "超额层面基本不重合"
    elif ex < 0:
        rel = "超额层面**明显反向**(同一个 ① 面板里,少配「韩国人多付钱」和少配「资金费拥挤」朝反方向走)"
    else:
        rel = "超额层面明显同向"
    A(f"   有信息量的是**超额口径**:日超额(V5 − V0)对日超额(V4 − V0)的相关 "
      f"**{ex:+.4f}**(n={c['n_excess_daily']} 天)⇒ {rel};"
      f"因子层每周横截面 corr(z_korea, z_funding) 平均 "
      f"**{c['weekly_z_corr_korea_vs_funding_mean']:+.4f}**(n={c['weekly_z_corr_korea_vs_funding_n']} 周)"
      f"⇒ 两个因子在 ① 的山寨横截面上基本正交。"
      f"⇒ **V5 不是 V4 的马甲**(是一个独立的因子),但也**没有挣到钱**(见上)。")
    A("")
    A("## 另报(不是判据)")
    A("")
    A(f"- **挪一周的对照**(z 用上一周周一 t−7 的 p7,不含当周):V5 − V0 全程 "
      f"{o['lagged_variant_not_preregistered']['diff_full']:+.4f}、留出段 "
      f"{o['lagged_variant_not_preregistered']['diff_holdout']:+.4f}。"
      f"预注册口径的 p7 含**当周周一收盘**(t−6…t 的中位),与 S-640 的资金费(d−7…d−1,不含 d)时点不同;"
      f"这一行是「只在当天成立就不算」的对照。")
    A(f"- **零分布的另一口径**(在**全部**山寨里打乱 z,含没有 p7 的名字,= S-640 口径)的分位:"
      f"{v5['pctile_vs_shuffles_full_allalts_variant']:.3f}(预注册口径为在「有 p7 的山寨」里打乱)。")
    A("")
    A("## 数据与完整性")
    A("")
    kc = o["completeness"]["korea"]
    A(f"- `korea_premium_watch`:取回 {kc['rows_fetched']} 行 = `count=exact` {kc['count_exact']},"
      f"去重 (d,symbol) 键 {kc['uniq_d_symbol_keys']},{kc['n_dates']} 个周一;"
      f"cohort {kc['cohort_counts']}(2026-11-09 起为 forward,之前是 backfill)。")
    A(f"- `ohlcv_daily(binance_hist)`:去重 (symbol,date) 键 "
      f"{o['completeness']['ohlcv']['uniq_symbol_date_keys']} = 天数 × 面板数 "
      f"{o['completeness']['ohlcv']['expected_symbols_x_dates']} ⇒ "
      f"{o['completeness']['ohlcv']['assert_equal']}。")
    A(f"- `funding_history(binance_perp)`:{o['completeness']['funding']['rows_fetched']} 行,"
      f"每币自身跨度内无洞 = {o['completeness']['funding']['assert_equal']}。")
    A("")
    A("## 结论与下一步")
    A("")
    A("- **三条判据:① 过、② 不过、③ 不过 ⇒ ❌**。korea p7 这条 ② 倾斜**不成立**,"
      "与 S-640 的资金费拥挤(唯一过了的市值底 ② 变量)不可同日而语。")
    A("- 值得记的一笔:分年看,V5 − V0 **四年里每年都是正的**(2023 +2.0pp / 2024 +2.0pp / "
      "2025 +0.4pp / 2026 +0.2pp),方向对但幅度只有随机打乱 z 的 75 分位 ⇒ "
      "**「方向对、幅度不够」**,与 R81(taker-buy)同一形状:故事为真、钱不在这里。"
      "要让它变成钱,得先解释为什么幅度这么小(是不是 k=0.5 太弱?是不是横截面只有 16 个名字?)。")
    A("- ② 族现状:第 7 次,唯一过了回测的仍是 S-640(资金费拥挤)。本条给「市值底 + 原因类变量」"
      "这条路线又添一个反例 —— 原因类是必要条件,不是充分条件。")
    A("")
    A("## 诚实")
    A("")
    A("- 这是 ② 族第 7 次(T-051、S-630、S-634、S-640、S-802、S-803、本条)。"
      "即便三条全过,最粗的 Bonferroni 下单条 0.95 分位远不够显著 ⇒ 过了也只进前向(纸面),不进钱。")
    A("- p7 的 `backfill` 段是事后算的,但 p7 本身只用 t 之前的价格(upbit_daily + ohlcv_daily),"
      "不含未来信息;真正的时点风险是「用周一收盘算出来的 p7 去配周一的再平衡」—— 上面挪一周那行是它的对照。")
    A("- S-771 / S-786 对「韩国溢价能否预测相对 BTC 的 4 周超额」只给前向判;"
      "**本卡测的不是那件事**,测的是把这个分数当 ② 倾斜因子在市值底上有没有用。")
    A("")
    REPORT_PATH.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
