"""T-092 — Jazz 10-14「慢就做逆向,甘于人后」(S-569 → 预注册 M-559).

三条规则的按时点回放 + 打乱对照 1000 次;数据用现有 T-092_cache.pkl(close_by_sym / z30 /
mcap_by_d / rank_by_dsym / fund_by_d)。所有盈亏、零分布、A/B 都走
`src/data/evaluation/apparatus.py`(T-097),不手写。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import pickle
import sys
import time
from collections import defaultdict

import numpy as np

# Apparatus is the only sanctioned home for returns / nulls / percentiles
sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai")
from src.data.evaluation.apparatus import (  # noqa: E402
    block_permute,
    long_return,
    null_distribution,
    percentile_of,
    price_on_or_after,
    short_return,
)


UNIVERSE_24 = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
               "DOT", "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI",
               "UNI", "AAVE", "INJ", "FIL", "ETC", "BCH")

WINDOWS = (
    ("W1_2020_2022", "2020-01-01", "2022-12-31"),
    ("W2_2023_2024", "2023-01-01", "2024-12-31"),
    ("W3_2025_now",  "2025-01-01", "2026-10-14"),
)

N_SHUFFLES = 1000
SEED_BASE = 20261014
COST_R3 = 0.0020      # 10 bps 单边 × 2(空 + 多)
DAYS_PER_YEAR = 365.0
DEFAULT_FUND_ANN = 0.10  # funding 缺值时的兜底年化(预注册里写死)
HOLD_WEEKS = 13       # 移出 / 加推力持有窗口

ROOT = "/Users/sbb/Projects/looloomi-ai-lane-b"
CACHE = f"{ROOT}/docs/research/T-092_cache.pkl"
MAC_RESEARCH = "/Volumes/CometCloudAI/cometcloud-local/research/t092"
MAC_REPORTS = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input"


def log(msg: str) -> None:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def mondays(start: str, end: str) -> list:
    out = []
    cur = dt.date.fromisoformat(start)
    end_d = dt.date.fromisoformat(end)
    while cur <= end_d:
        if cur.weekday() == 0:
            out.append(cur.isoformat())
        cur += dt.timedelta(days=1)
    return out


def maxdd(path):
    if not path:
        return 0.0
    peak = path[0]
    mdd = 0.0
    for v in path:
        if v > peak:
            peak = v
        d = v / peak - 1.0
        if d < mdd:
            mdd = d
    return float(mdd)


def find_idx(cs: list[str], d_iso: str) -> int:
    """Return index of d_iso (or largest strictly < d_iso if d_iso absent).

    Negative ⇒ d_iso earlier than cs[0] (we have no data on/before d_iso).
    """
    if not cs:
        return -1
    # bisect_right then -1
    lo, hi = 0, len(cs)
    while lo < hi:
        mid = (lo + hi) // 2
        if cs[mid] < d_iso:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def nav_path_returns(weights: np.ndarray, rets: np.ndarray) -> np.ndarray:
    """weights: (T+1, N) target weights at rebal times; rets: (T, N) one-period returns.

    Apply weights to subsequent period return; product path of (1 + w_{t-1} · r_t).
    """
    if rets.shape[0] == 0:
        return np.array([1.0])
    w_used = weights[:-1]                              # (T, N)
    r_filled = np.nan_to_num(rets, nan=0.0)
    port_ret = (w_used * r_filled).sum(axis=1)
    return np.cumprod(1.0 + port_ret)


# ── 加载 cache ────────────────────────────────────────────────────────────

def load_cache() -> dict:
    with open(CACHE, "rb") as f:
        return pickle.load(f)


# ── 单窗口 ─────────────────────────────────────────────────────────────────

def run_window(cache: dict, wname: str, lo: str, hi: str) -> dict:
    close_by_sym = cache["close_by_sym"]
    z30 = cache["z30"]
    mcap_by_d = cache["mcap_by_d"]
    rank_by_dsym = cache["rank_by_dsym"]
    fund_by_d = cache["fund_by_d"]

    # 每个币的日期排序表(快查)+ 等长价格数组(快算周收益)
    sorted_dates = {sym: sorted(ddict.keys()) for sym, ddict in close_by_sym.items()}
    n_universe = len(UNIVERSE_24)
    non_btc = [s for s in UNIVERSE_24 if s != "BTC"]
    non_universe = sorted([s for s in close_by_sym.keys() if s not in UNIVERSE_24])

    ms = mondays(lo, hi)
    nM = len(ms)

    # Rebal 目标权重矩阵:nM × 24(每周一用 d-1 市值计算市值加权)
    rebal_w = np.zeros((nM, n_universe))
    for i, d in enumerate(ms):
        d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        mcs = np.array([mcap_by_d.get(d1, {}).get(sym, 0.0) for sym in UNIVERSE_24])
        tot = mcs.sum()
        rebal_w[i] = mcs / tot if tot > 0 else np.full(n_universe, 1.0 / n_universe)

    # 周收益矩阵:(nM-1) × 24,i 行 = 周 i → 周 i+1 的收益
    rets = np.full((max(nM - 1, 0), n_universe), np.nan)
    for i in range(nM - 1):
        d_in = ms[i]
        d_out = ms[i + 1]
        for j, sym in enumerate(UNIVERSE_24):
            cs = close_by_sym.get(sym)
            if not cs:
                continue
            p_in = price_on_or_after(list(cs.keys()), list(cs.values()), d_in)
            p_out = price_on_or_after(list(cs.keys()), list(cs.values()), d_out)
            r = long_return(p_in, p_out)
            if r is not None:
                rets[i, j] = r

    # 每周 funding 年化(读不到就用默认)
    fund_ann = np.zeros(nM)
    fund_present = np.zeros(nM, dtype=bool)
    for i, d in enumerate(ms):
        d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        v = fund_by_d.get(d1)
        fund_present[i] = v is not None
        fund_ann[i] = v if v is not None else DEFAULT_FUND_ANN

    # ── R1 ② 暴涨名移回 BTC ────────────────────────────────────────────────
    r1_events: list[tuple[int, str]] = []
    for i, d in enumerate(ms):
        d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        for sym in non_btc:
            z = z30.get((sym, d1))
            if z is not None and z >= 3.0:
                r1_events.append((i, sym))

    r1_active = np.zeros((nM, n_universe), dtype=bool)
    sym_to_col = {s: j for j, s in enumerate(UNIVERSE_24)}
    for i, sym in r1_events:
        for k in range(HOLD_WEEKS):
            if i + k < nM:
                r1_active[i + k, sym_to_col[sym]] = True

    def run_r1(active_mask):
        masked_w = rebal_w.copy()
        masked_w[active_mask] = 0.0
        sums = masked_w.sum(axis=1, keepdims=True)
        safe = np.where(sums == 0, 1.0, sums)
        masked_w = masked_w / safe
        path = nav_path_returns(masked_w, rets)
        nav = float(path[-1]) if path.size else 1.0
        return nav, path

    nav_b_r1, path_b_r1 = run_r1(np.zeros((nM, n_universe), dtype=bool))
    nav_r1, path_r1 = run_r1(r1_active)
    excess_r1 = nav_r1 / nav_b_r1 - 1.0

    # 对照 —— 同样大小的事件(NT 个「随机周 × 23 个非 BTC 名」),1000 次
    n_e1 = len(r1_events)
    rng = np.random.default_rng(SEED_BASE + 1)
    shuf_nav_r1 = np.empty(N_SHUFFLES)
    for s_i in range(N_SHUFFLES):
        sched = np.zeros((nM, n_universe), dtype=bool)
        if n_e1 > 0 and nM > 0:
            i_pick = rng.integers(0, nM, size=n_e1)
            j_pick = rng.integers(0, len(non_btc), size=n_e1)
            for ip, jp in zip(i_pick, j_pick):
                col = sym_to_col[non_btc[jp]]
                for k in range(HOLD_WEEKS):
                    if ip + k < nM:
                        sched[ip + k, col] = True
        v, _ = run_r1(sched)
        shuf_nav_r1[s_i] = v
    pct_r1 = percentile_of(nav_r1, shuf_nav_r1)

    per_year_r1: dict[str, int] = defaultdict(int)
    for i, _ in r1_events:
        per_year_r1[ms[i][:4]] += 1

    # ── R2 ③ 主流暴跌后加推力 ─────────────────────────────────────────────
    r2_events: list[int] = []
    for i, d in enumerate(ms):
        d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        z = z30.get(("BTC", d1))
        if z is not None and z <= -2.0:
            r2_events.append(i)

    r2_active = np.zeros(nM, dtype=bool)
    for i in r2_events:
        for k in range(HOLD_WEEKS):
            if i + k < nM:
                r2_active[i + k] = True

    def run_r2(active_mask):
        path = np.empty(max(nM - 1, 0))
        nav = 1.0
        cum_fund = 0.0
        for i in range(nM - 1):
            base_ret = float((rebal_w[i] * np.nan_to_num(rets[i], nan=0.0)).sum())
            mult = 1.3 if active_mask[i] else 1.0
            week_fund = (mult - 1.0) * fund_ann[i] / 52.0
            cum_fund += week_fund
            nav *= (1.0 + mult * base_ret - week_fund)
            path[i] = nav
        return nav, path, cum_fund

    nav_b_r2, path_b_r2, fund_b_r2 = run_r2(np.zeros(nM, dtype=bool))
    nav_r2, path_r2, fund_paid_r2 = run_r2(r2_active)
    excess_r2 = nav_r2 / nav_b_r2 - 1.0

    # 对照 —— 同样个数的 1.3 触发周(随机抽,无替换)
    n_e2 = len(r2_events)
    rng2 = np.random.default_rng(SEED_BASE + 2)
    shuf_nav_r2 = np.empty(N_SHUFFLES)
    for s_i in range(N_SHUFFLES):
        act = np.zeros(nM, dtype=bool)
        if n_e2 > 0 and nM >= n_e2:
            picks = rng2.choice(nM, size=n_e2, replace=False)
            for ip in picks:
                for k in range(HOLD_WEEKS):
                    if ip + k < nM:
                        act[ip + k] = True
        v, _, _ = run_r2(act)
        shuf_nav_r2[s_i] = v
    pct_r2 = percentile_of(nav_r2, shuf_nav_r2)

    # ── R3 30 名外暴涨名做空对冲 ──────────────────────────────────────────
    r3_candidates: list[tuple[int, str]] = []
    for i, d in enumerate(ms):
        d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        for sym in non_universe:
            z = z30.get((sym, d1))
            if z is None or z < 3.0:
                continue
            rk = rank_by_dsym.get((d, sym))
            if rk is None or rk <= 30:
                continue
            r3_candidates.append((i, sym))

    def r3_pnl(week_idx: int, sym: str) -> dict | None:
        d = ms[week_idx]
        cs_btc = sorted_dates["BTC"]
        cs_s = sorted_dates.get(sym)
        if not cs_s:
            return None
        # 入场 t+7 收盘 = 取 close_by_sym[sym] 上 ≥ d 的最早 ≤ d+7 的价格
        target_ent = (dt.date.fromisoformat(d) + dt.timedelta(days=7)).isoformat()
        ent_idx_s = find_idx(cs_s, target_ent)
        if ent_idx_s < 0:
            return None
        # 实际入场收盘 = cs_s[ent_idx_s](可能比 target 早;我们能拿到的最早)
        ent_d_s = cs_s[ent_idx_s]
        ext_idx_s = min(ent_idx_s + 30, len(cs_s) - 1)
        ext_d_s = cs_s[ext_idx_s]
        if ext_idx_s <= ent_idx_s:
            return None

        # 多 BTC 同时持仓 30 个币日(用 BTC 同步日历);与空头匹配
        ent_idx_b = find_idx(cs_btc, ent_d_s)
        if ent_idx_b < 0:
            return None
        ent_d_b = cs_btc[ent_idx_b]
        ext_idx_b = min(ent_idx_b + 30, len(cs_btc) - 1)
        ext_d_b = cs_btc[ext_idx_b]
        if ext_idx_b <= ent_idx_b:
            return None

        p_ent_s = close_by_sym[sym][ent_d_s]
        p_ext_s = close_by_sym[sym][ext_d_s]
        p_ent_b = close_by_sym["BTC"][ent_d_b]
        p_ext_b = close_by_sym["BTC"][ext_d_b]
        if None in (p_ent_s, p_ext_s, p_ent_b, p_ext_b):
            return None

        sh = short_return(p_ent_s, p_ext_s)
        lg = long_return(p_ent_b, p_ext_b)
        if sh is None or lg is None:
            return None
        net = sh + lg - COST_R3
        return {"net": net, "short": sh, "long": lg,
                "entry": ent_d_s, "exit": ext_d_s,
                "entry_btc": ent_d_b, "exit_btc": ext_d_b,
                "sym": sym, "week_idx": week_idx}

    r3_pnls = [r3_pnl(i, s) for i, s in r3_candidates]
    r3_pnls = [p for p in r3_pnls if p is not None]
    n_r3 = len(r3_pnls)
    r3_mean_net = float(np.mean([p["net"] for p in r3_pnls])) if n_r3 else 0.0
    r3_mean_short = float(np.mean([p["short"] for p in r3_pnls])) if n_r3 else 0.0
    r3_mean_long = float(np.mean([p["long"] for p in r3_pnls])) if n_r3 else 0.0
    r3_excess = r3_mean_net - r3_mean_long
    r3_win = float(np.mean([p["net"] > 0 for p in r3_pnls])) if n_r3 else 0.0

    fund_total = 0
    fund_present_n = 0
    for p in r3_pnls:
        # 持仓覆盖期 funding 现值笔数
        cs_btc = sorted_dates["BTC"]
        a = find_idx(cs_btc, p["entry_btc"])
        b = find_idx(cs_btc, p["exit_btc"])
        if a < 0:
            continue
        b = min(b, len(cs_btc) - 1)
        for j in range(a, b + 1):
            fund_total += 1
            if fund_by_d.get(cs_btc[j]) is not None:
                fund_present_n += 1
    fund_frac = (fund_present_n / fund_total) if fund_total else 0.0

    per_year_r3: dict[str, int] = defaultdict(int)
    for i, _ in r3_candidates:
        per_year_r3[ms[i][:4]] += 1

    # 对照 —— 同样笔数的「随机周 × 30 名外随机名」
    n_e3 = len(r3_candidates)
    rng3 = np.random.default_rng(SEED_BASE + 3)
    shuf_mean_r3 = np.empty(N_SHUFFLES)
    for s_i in range(N_SHUFFLES):
        nets = []
        if n_e3 > 0 and non_universe and nM > 0:
            i_pick = rng3.integers(0, nM, size=n_e3)
            s_pick = rng3.integers(0, len(non_universe), size=n_e3)
            for ip, sp in zip(i_pick, s_pick):
                r = r3_pnl(int(ip), non_universe[int(sp)])
                if r is not None:
                    nets.append(r["net"])
        shuf_mean_r3[s_i] = float(np.mean(nets)) if nets else 0.0
    pct_r3 = percentile_of(r3_mean_net, shuf_mean_r3)

    # ── 汇总 ──────────────────────────────────────────────────────────────
    return {
        "window": wname,
        "lo": lo, "hi": hi,
        "n_mondays": nM,
        "funding_data_coverage_pct": round(float(fund_present.mean()) * 100, 1),
        "R1": {
            "n_events": n_e1,
            "nav_baseline": round(nav_b_r1, 4),
            "nav_R1": round(nav_r1, 4),
            "excess_pct": round(excess_r1 * 100, 2),
            "maxdd_baseline_pct": round(maxdd(path_b_r1.tolist()) * 100, 2),
            "maxdd_R1_pct": round(maxdd(path_r1.tolist()) * 100, 2),
            "shuffle_pct": round(float(pct_r1 or 0) * 100, 1),
            "shuf_p10": round(float(np.quantile(shuf_nav_r1, 0.10)), 4),
            "shuf_p50": round(float(np.quantile(shuf_nav_r1, 0.50)), 4),
            "shuf_p90": round(float(np.quantile(shuf_nav_r1, 0.90)), 4),
            "per_year_events": dict(sorted(per_year_r1.items())),
        },
        "R2": {
            "n_events": n_e2,
            "nav_baseline": round(float(nav_b_r2), 4),
            "nav_R2": round(float(nav_r2), 4),
            "excess_pct": round(float(excess_r2) * 100, 2),
            "fund_paid_R2_pct": round(float(fund_paid_r2) * 100, 4),
            "maxdd_baseline_pct": round(float(maxdd(path_b_r2.tolist())) * 100, 2),
            "maxdd_R2_pct": round(float(maxdd(path_r2.tolist())) * 100, 2),
            "shuffle_pct": round(float(pct_r2 or 0) * 100, 1),
            "shuf_p10": round(float(np.quantile(shuf_nav_r2, 0.10)), 4),
            "shuf_p50": round(float(np.quantile(shuf_nav_r2, 0.50)), 4),
            "shuf_p90": round(float(np.quantile(shuf_nav_r2, 0.90)), 4),
        },
        "R3": {
            "n_candidates": n_e3,
            "n_pnl_computed": n_r3,
            "mean_net_pct": round(float(r3_mean_net) * 100, 2),
            "mean_short_pct": round(float(r3_mean_short) * 100, 2),
            "mean_long_btc_pct": round(float(r3_mean_long) * 100, 2),
            "excess_vs_btc_pct": round(float(r3_excess) * 100, 2),
            "win_rate": round(float(r3_win), 3),
            "fund_data_present_frac_pct": round(float(fund_frac) * 100, 1),
            "shuffle_pct": round(float(pct_r3 or 0) * 100, 1),
            "shuf_p10": round(float(np.quantile(shuf_mean_r3, 0.10)) * 100, 2),
            "shuf_p50": round(float(np.quantile(shuf_mean_r3, 0.50)) * 100, 2),
            "shuf_p90": round(float(np.quantile(shuf_mean_r3, 0.90)) * 100, 2),
            "per_year_candidates": dict(sorted(per_year_r3.items())),
        },
    }


def main() -> dict:
    log("=== T-092 RUN v2 (apparatus-only) ===")
    t0 = time.time()
    cache = load_cache()
    log(f"cache loaded (symbols={len(cache['close_by_sym'])}, "
        f"z30={len(cache['z30'])}) t={time.time()-t0:.0f}s")

    results = {}
    for wname, lo, hi in WINDOWS:
        log(f"--- {wname} ({lo} → {hi}) ---")
        r = run_window(cache, wname, lo, hi)
        log(f"  R1 exc={r['R1']['excess_pct']:.2f}% p={r['R1']['shuffle_pct']:.1f}; "
            f"R2 exc={r['R2']['excess_pct']:.2f}% p={r['R2']['shuffle_pct']:.1f}; "
            f"R3 net={r['R3']['mean_net_pct']:.2f}% p={r['R3']['shuffle_pct']:.1f} "
            f"t={time.time()-t0:.0f}s")
        results[wname] = r

    out = {
        "task": "T-092",
        "pre_reg": "M-559 (lane-b, 2026-10-14) — sealed before any data touch",
        "method": "apparatus-only: long_return / short_return / price_on_or_after / percentile_of",
        "windows": [{"name": w[0], "lo": w[1], "hi": w[2]} for w in WINDOWS],
        "n_shuffles": N_SHUFFLES,
        "seed_base": SEED_BASE,
        "cache_path": CACHE,
        "results_by_window": results,
        "verdicts": {
            w: {
                "R1_PASS": r["R1"]["excess_pct"] > 0 and r["R1"]["shuffle_pct"] >= 90,
                "R2_PASS": r["R2"]["excess_pct"] > 0 and r["R2"]["shuffle_pct"] >= 90,
                "R3_PASS": r["R3"]["excess_vs_btc_pct"] > 0 and r["R3"]["shuffle_pct"] >= 90,
            }
            for w, r in results.items()
        },
        "global_verdict": "",
    }

    # 通过判据:至少两窗口超额>0 且分位≥90%,第三窗口超额不差于 −2pp
    r1_passes = sum(1 for v in out["verdicts"].values() if v["R1_PASS"])
    r2_passes = sum(1 for v in out["verdicts"].values() if v["R2_PASS"])
    r3_passes = sum(1 for v in out["verdicts"].values() if v["R3_PASS"])
    out["global_verdict"] = (
        f"R1: {r1_passes}/3 windows pass; "
        f"R2: {r2_passes}/3 windows pass; "
        f"R3: {r3_passes}/3 windows pass. "
        f"Criterion (≥2 windows pass excess>0 + p≥90%, third not worse than −2pp): "
        f"{'PASS' if (r1_passes >= 2 or r2_passes >= 2 or r3_passes >= 2) else 'FAIL'}"
    )

    # 输出路径
    out_lane = f"{ROOT}/docs/research/t092/results_v2.json"
    out_mac = f"{MAC_RESEARCH}/results_v2.json"
    os.makedirs(os.path.dirname(out_lane), exist_ok=True)
    os.makedirs(MAC_RESEARCH, exist_ok=True)
    os.makedirs(MAC_REPORTS, exist_ok=True)
    for path in (out_lane, out_mac):
        with open(path, "w") as f:
            json.dump(out, f, indent=2, default=str)
        log(f"wrote {path}")
    return out


if __name__ == "__main__":
    out = main()
    print(json.dumps(out["global_verdict"], indent=2))