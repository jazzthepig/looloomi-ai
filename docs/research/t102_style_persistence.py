"""T-102 / S-582 —— 风格周期(8 组)的延续性量测(预注册见 REFUTATION_LEDGER §S-582)。

数据:私有面板 ~/Projects/looloomi-private/research_data/t099_panel.json(同 S-581,不复制进任何 git 仓库)。
零分布 / 分位 / 盈亏 / A/B 一律用 src.data.evaluation.apparatus。

用法:
    python3 docs/research/t102_style_persistence.py <panel.json> <out.json>
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (  # noqa: E402
    null_distribution, percentile_of, shuffle_within,
)

# ── §1 八组(只看业务描述;与 S-582 §1 一字不差) ──────────────────────────────
GROUPS: dict[str, list[str]] = {
    "1_半导体与硬件": ["NVDA", "AMD", "INTC", "MU", "AVGO", "TSM", "ASML", "ARM", "TXN", "MRVL",
                       "KLAC", "LRCX", "AMAT", "ANET", "CRWD", "PANW", "DELL", "IBM", "CSCO"],
    "2_软件与互联网": ["MSFT", "GOOGL", "META", "AMZN", "NFLX", "ADBE", "CRM", "ORCL", "PLTR", "SAP"],
    "3_金融":        ["JPM", "BAC", "WFC", "C", "GS", "MS", "V", "MA", "BRK-B", "HSBC", "MUFG", "RY"],
    "4_能源与材料":  ["XOM", "CVX", "BHP", "RIO", "SHEL", "TTE", "LIN", "GEV"],
    "5_医药":        ["LLY", "JNJ", "PFE", "MRK", "ABBV", "NVS", "AZN", "NVO", "TMO", "AMGN", "ABT", "UNH"],
    "6_消费与工业":  ["WMT", "COST", "HD", "KO", "PG", "PM", "PEP", "T", "VZ", "CMCSA", "DIS", "CAT",
                       "TM", "TCEHY", "BABA", "SHOP", "AAPL", "GE", "RTX", "TSLA"],
    "7_黄金":        ["XAUUSD"],
    "8_加密":        ["BTC", "ETH", "BNB", "SOL", "XRP"],
}
GROUP_ORDER = list(GROUPS.keys())
TICKER_TO_GROUP: dict[str, str] = {tk: g for g, tks in GROUPS.items() for tk in tks}

LAGS = (1, 2, 4)
N_NULL = 1000
SEED = 20261015
N_TOP = 60
N_BOOT = 2000


# ── 数据 ─────────────────────────────────────────────────────────────────────

def quarter_end_idx(months: list[str]) -> list[int]:
    return [i for i, m in enumerate(months) if m.endswith(("03", "06", "09", "12"))]


def quarter_ret(monthly: list[Optional[float]], qe_idx: int) -> Optional[float]:
    """qe_idx 当季 3 个月的复利收益(若 3 月都缺 ⇒ None;有 1-2 月有效 ⇒ 用有效月复利)。"""
    rets = monthly[qe_idx - 2: qe_idx + 1] if qe_idx >= 2 else monthly[:qe_idx + 1]
    rets = [r for r in rets if r is not None and math.isfinite(r) and r > -1]
    if not rets:
        return None
    v = 1.0
    for r in rets:
        v *= 1 + r
    return v - 1.0


def top_n_members(snap: dict[str, float], n: int = N_TOP) -> list[str]:
    return [k for k, v in sorted(snap.items(), key=lambda kv: -kv[1]) if v and v > 0][:n]


def acwi_state(months: list[str], rets: dict[str, list[Optional[float]]], qe_idx: int) -> str:
    """ACWI 过去 4 季(共 12 月)复利收益 > 0 ⇒ up,否则 down。状态在季初(t 当季)已知。"""
    if qe_idx < 12:
        return "n/a"
    window = rets["ACWI"][qe_idx - 12: qe_idx]
    window = [r for r in window if r is not None and math.isfinite(r)]
    if len(window) < 6:
        return "n/a"
    v = 1.0
    for r in window:
        v *= 1 + r
    return "up" if v > 1.0 else "down"


# ── §3.1 组层面 ───────────────────────────────────────────────────────────────

def group_returns_for_quarter(members: list[str], rets: dict[str, list[Optional[float]]],
                              qe_idx: int) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {}
    for g in GROUP_ORDER:
        g_members = [m for m in members if TICKER_TO_GROUP.get(m) == g]
        rs = []
        for m in g_members:
            r = quarter_ret(rets.get(m, []), qe_idx)
            if r is not None:
                rs.append(r)
        out[g] = float(np.mean(rs)) if rs else None
    return out


def spearman_persistence(series_t: dict[str, Optional[float]],
                         series_t_lag: dict[str, Optional[float]]) -> Optional[float]:
    """两个等长 dict(同 group order),对齐非 None 值,做 Spearman。"""
    keys = [g for g in GROUP_ORDER if series_t.get(g) is not None and series_t_lag.get(g) is not None]
    if len(keys) < 3:
        return None
    a = [series_t[k] for k in keys]
    b = [series_t_lag[k] for k in keys]
    rho, _ = spearmanr(a, b)
    return float(rho) if rho is not None and math.isfinite(rho) else None


def lag_average(panel: list[Optional[float]], lag: int) -> Optional[float]:
    valid = [x for x in panel if x is not None and math.isfinite(x)]
    return float(np.mean(valid)) if valid else None


# ── 主程序 ────────────────────────────────────────────────────────────────────

def run(panel_path: str) -> dict:
    p = json.loads(Path(panel_path).read_text())
    months = p["months"]
    rets = {k: [None if v is None else float(v) for v in vs] for k, vs in p["ret"].items()}
    mcap_q = {m: {k: float(v) for k, v in snap.items() if v} for m, snap in p["mcap"].items()}
    qe_idx = quarter_end_idx(months)
    qe_months = [months[i] for i in qe_idx]

    # 每季:前 N_TOP + 8 组组收益
    per_q = []
    for k, i in enumerate(qe_idx):
        snap = mcap_q.get(qe_months[k], {})
        members = top_n_members(snap, N_TOP)
        g_ret = group_returns_for_quarter(members, rets, i)
        per_q.append({
            "month": qe_months[k],
            "idx": i,
            "n_members": len(members),
            "g_ret": g_ret,
            "members": members,
            "acwi_state": acwi_state(months, rets, i),
        })

    # ── §3.1 / §3.3:组层面 Spearman,lag 1/2/4
    def collect_lag(lag: int) -> tuple[list[float], list[str]]:
        rhos, states = [], []
        for k in range(len(per_q) - lag):
            rho = spearman_persistence(per_q[k]["g_ret"], per_q[k + lag]["g_ret"])
            if rho is not None:
                rhos.append(rho)
                states.append(per_q[k + lag]["acwi_state"])
        return rhos, states

    def null_lag_distribution(lag: int, n: int = N_NULL, seed: int = SEED) -> np.ndarray:
        rng = np.random.default_rng(seed + lag)
        nulls = np.empty(n, dtype=float)
        valid_count = len(per_q) - lag
        for it in range(n):
            rho_sum, rho_n = 0.0, 0
            for k in range(valid_count):
                gr = per_q[k]["g_ret"]
                gr_next = per_q[k + lag]["g_ret"]
                keys = [g for g in GROUP_ORDER if gr.get(g) is not None and gr_next.get(g) is not None]
                if len(keys) < 3:
                    continue
                vals = np.array([gr_next[g] for g in keys])
                shuffled = shuffle_within(vals, np.array(["q"] * len(keys)), rng)
                a = [gr[g] for g in keys]
                b = list(shuffled)
                rho, _ = spearmanr(a, b)
                if rho is not None and math.isfinite(rho):
                    rho_sum += rho
                    rho_n += 1
            nulls[it] = rho_sum / rho_n if rho_n else float("nan")
        return nulls[~np.isnan(nulls)]

    grp_results: dict[str, dict] = {}
    for lag in LAGS:
        rhos, states = collect_lag(lag)
        if not rhos:
            continue
        actual_mean = float(np.mean(rhos))
        null_arr = null_lag_distribution(lag)
        p95 = float(np.quantile(null_arr, 0.95))
        p_actual = percentile_of(actual_mean, null_arr)
        # 按状态
        by_state = {"up": [], "down": []}
        for r, s in zip(rhos, states):
            if s in by_state:
                by_state[s].append(r)
        grp_results[f"lag{lag}"] = {
            "n_pairs": len(rhos),
            "actual_mean_rho": actual_mean,
            "null_p95": p95,
            "actual_pct_in_null": p_actual,
            "verdict_95": "组层面领先会延续" if actual_mean > p95 else "分不开",
            "by_state": {s: {"n": len(vs), "mean_rho": float(np.mean(vs)) if vs else None}
                         for s, vs in by_state.items()},
        }

    # ── §3.2:名字层面
    name_rhos: dict[int, list[float]] = {lag: [] for lag in LAGS}
    name_states: dict[int, list[str]] = {lag: [] for lag in LAGS}
    for lag in LAGS:
        for k in range(len(per_q) - lag):
            members_t = set(per_q[k]["members"])
            members_lag = set(per_q[k + lag]["members"])
            common = sorted(members_t & members_lag)
            rs_t = [quarter_ret(rets[m], per_q[k]["idx"]) for m in common]
            rs_lag = [quarter_ret(rets[m], per_q[k + lag]["idx"]) for m in common]
            ok = [(a, b) for a, b in zip(rs_t, rs_lag) if a is not None and b is not None]
            if len(ok) < 10:
                continue
            a, b = zip(*ok)
            rho, _ = spearmanr(a, b)
            if rho is not None and math.isfinite(rho):
                name_rhos[lag].append(float(rho))
                name_states[lag].append(per_q[k + lag]["acwi_state"])

    def null_name_lag(lag: int, n: int = N_NULL, seed: int = SEED) -> np.ndarray:
        rng = np.random.default_rng(seed * 7 + lag)
        nulls = np.empty(n, dtype=float)
        for it in range(n):
            rho_sum, rho_n = 0.0, 0
            for k in range(len(per_q) - lag):
                members_t = set(per_q[k]["members"])
                members_lag = set(per_q[k + lag]["members"])
                common = sorted(members_t & members_lag)
                rs_t = [quarter_ret(rets[m], per_q[k]["idx"]) for m in common]
                rs_lag = [quarter_ret(rets[m], per_q[k + lag]["idx"]) for m in common]
                ok = [(a, b) for a, b in zip(rs_t, rs_lag) if a is not None and b is not None]
                if len(ok) < 10:
                    continue
                a, b = zip(*ok)
                b_arr = np.array(b)
                b_shuf = shuffle_within(b_arr, np.array(["q"] * len(b_arr)), rng)
                rho, _ = spearmanr(a, list(b_shuf))
                if rho is not None and math.isfinite(rho):
                    rho_sum += rho
                    rho_n += 1
            nulls[it] = rho_sum / rho_n if rho_n else float("nan")
        return nulls[~np.isnan(nulls)]

    name_results: dict[str, dict] = {}
    for lag in LAGS:
        rhos = name_rhos[lag]
        if not rhos:
            continue
        actual_mean = float(np.mean(rhos))
        null_arr = null_name_lag(lag)
        p95 = float(np.quantile(null_arr, 0.95))
        p_actual = percentile_of(actual_mean, null_arr)
        states = name_states[lag]
        by_state = {"up": [], "down": []}
        for r, s in zip(rhos, states):
            if s in by_state:
                by_state[s].append(r)
        name_results[f"lag{lag}"] = {
            "n_pairs": len(rhos),
            "actual_mean_rho": actual_mean,
            "null_p95": p95,
            "actual_pct_in_null": p_actual,
            "verdict_95": "名字层面领先会延续" if actual_mean > p95 else "分不开",
            "by_state": {s: {"n": len(vs), "mean_rho": float(np.mean(vs)) if vs else None}
                         for s, vs in by_state.items()},
        }

    # ── §3.4 探索:EW×Mom − EW 季超额 vs 当季组延续强度
    try:
        from docs.research.t099_world50_replay import run_arm, closes_from_returns  # type: ignore
    except Exception as e:
        run_arm = None
        run_arm_err = str(e)
        closes_from_returns = None  # type: ignore

    excess_per_q: list[Optional[float]] = []
    rho_per_q: list[Optional[float]] = []
    if run_arm is not None and closes_from_returns is not None:
        closes = {k: closes_from_returns(v) for k, v in rets.items()}
        ew = run_arm("EW", months, rets, mcap_q, p["cls"], closes)
        ewmom = run_arm("EWxMom", months, rets, mcap_q, p["cls"], closes)
        ew_map = dict(zip(ew["months"], ew["ret"]))
        ewmom_map = dict(zip(ewmom["months"], ewmom["ret"]))
        for q in per_q:
            m = q["month"]
            if m not in ew_map or m not in ewmom_map:
                continue
            # 季超额 = 季内 3 个月的 (EWxMom - EW) 复利:用相邻 2 季的差异
            i = q["idx"]
            ew_seq = ew["ret"]
            ewmom_seq = ewmom["ret"]
            # ew/ewmom 的 ret 是月份与 qe 对齐的序列;但 run_arm 输出只含调仓后到 i_end 的月份
            # 用月份列表定位
            ew_idx = ew["months"].index(m) if m in ew["months"] else None
            ewmom_idx = ewmom["months"].index(m) if m in ewmom["months"] else None
            if ew_idx is None or ewmom_idx is None or ew_idx < 2 or ewmom_idx < 2:
                continue
            ew_q = 1.0
            ewmom_q = 1.0
            ok = True
            for j in range(3):
                er = ew_seq[ew_idx - j]
                mr = ewmom_seq[ewmom_idx - j]
                if er is None or mr is None:
                    ok = False
                    break
                ew_q *= 1 + er
                ewmom_q *= 1 + mr
            if not ok or ew_q == 0:
                continue
            excess = ewmom_q / ew_q - 1.0
            # 当季组延续强度 = q 与 q+1 之间的 ρ
            i_q = per_q.index(q)
            if i_q + 1 >= len(per_q):
                continue
            rho = spearman_persistence(q["g_ret"], per_q[i_q + 1]["g_ret"])
            excess_per_q.append(excess)
            rho_per_q.append(rho if rho is not None else float("nan"))

    excess_clean = [(e, r) for e, r in zip(excess_per_q, rho_per_q)
                    if e is not None and r is not None and math.isfinite(r)]
    if len(excess_clean) >= 5:
        a, b = zip(*excess_clean)
        corr, _ = spearmanr(a, b)
        corr = float(corr) if corr is not None and math.isfinite(corr) else None
    else:
        corr = None
    exploratory = {"n_pairs": len(excess_clean),
                   "spearman_corr_excess_vs_group_persistence": corr,
                   "note": "探索性 — 不参与主检验判据;只能用此结论调主判据、不能写进产品陈述"}

    return {
        "panel": panel_path,
        "quarters": [q["month"] for q in per_q],
        "n_quarters": len(per_q),
        "group_layer": grp_results,
        "name_layer": name_results,
        "exploratory": exploratory,
        "groups_def": {g: tks for g, tks in GROUPS.items()},
        "lags": list(LAGS),
        "n_null": N_NULL,
        "seed": SEED,
    }


if __name__ == "__main__":
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    rep = run(sys.argv[1])
    if out_path:
        Path(out_path).write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
