"""T-121 —— §S-602 模拟六:五条腿风险平价组合(BTC / ETH / XAUUSD / SPY / AGG)。

加密两条腿(BTC、ETH)分别用「持有 H」与「X1V」(s601_drawdown.path + vol_scale,空出的部分留现金);
每月月初按过去 60 天实现波动倒数配权,月内不调。对照 60/40(SPY/AGG,月度再平衡)与全持 BTC。
规则一律 import,不重写。2016-01-01 起,统计用 src.data.evaluation.apparatus.ab_test。

用法:python3 docs/research/t121_portfolio.py <research 目录> [输出 json]
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

ROOT_PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_PROJ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from s596_tom_pyramid import COST, FALLBACK_FUND  # noqa: E402
from s600_tom_trader import returns  # noqa: E402
from s601_drawdown import path, vol_scale  # noqa: E402
from src.data.evaluation.apparatus import ab_test  # noqa: E402

LEGS = ("BTC", "ETH", "XAUUSD", "SPY", "AGG")
CRYPTO = ("BTC", "ETH")
COST_BPS = COST            # 10 bp / |Δg|
REBAL_DAYS = 30            # 每月近似 30 天
VOL_LOOKBACK = 60          # 配权用过去 60 天
START = "2016-01-01"       # 任务指定 2016 起
SEED = 121


# ── 数据 ─────────────────────────────────────────────────────────────────────

def load_close(research: str) -> tuple[list[str], dict[str, np.ndarray]]:
    """返回 (dates, {sym: close});从 w50_daily/close.json 读 5 条腿,缺失位置补 NaN 再前向填空,
    并把任何一条腿在尾段为 NaN 的日子丢掉(防止 cumprod 出 nan)。"""
    p = json.loads((Path(research) / "w50_daily/close.json").read_text())
    dates = list(p["dates"])
    raw = {sym: np.array([(x if x else np.nan) for x in p["close"].get(sym, [])], dtype=float) for sym in LEGS}
    n = len(dates)
    out: dict[str, np.ndarray] = {}
    for sym, v in raw.items():
        if len(v) < n:
            v = np.concatenate([v, np.full(n - len(v), np.nan)])
        elif len(v) > n:
            v = v[:n]
        mask = np.isfinite(v)
        idx = np.flatnonzero(mask)
        out[sym] = v.copy()
        if idx.size:
            first = idx[0]
            out[sym][:first] = v[first] if first < n and np.isfinite(v[first]) else np.nan
            for i in range(1, len(idx)):
                a, b = idx[i - 1], idx[i]
                if b - a > 1:
                    out[sym][a + 1:b] = v[a]
    # 尾部:任一条腿 NaN ⇒ 整段都丢
    arr = np.column_stack([out[s] for s in LEGS])
    bad = ~np.all(np.isfinite(arr), axis=1)
    if bad.any():
        cut = int(np.argmax(~bad[::-1]))          # 从尾往前第一个非坏的下标 = n - 1 - argmax
        cut = n - cut
        dates = dates[:cut]
        for sym in LEGS:
            out[sym] = out[sym][:cut]
    return dates, out


# ── 配权 ─────────────────────────────────────────────────────────────────────

def weights_monthly(dates: list[str], closes: dict[str, np.ndarray]) -> list[dict[str, float]]:
    """每月月初用过去 60 天对数收益 std 的倒数配权,5 条腿和为 1。"""
    n = len(dates)
    w_log = np.log(np.column_stack([closes[s] for s in LEGS]))
    # 每月第一天:0、30、60、…
    rebal = list(range(0, n, REBAL_DAYS))
    out: list[dict[str, float]] = []
    for t in rebal:
        lo = max(1, t - VOL_LOOKBACK + 1)
        window = w_log[lo:t + 1]
        sigma = np.nanstd(window, axis=0)
        if not np.all(np.isfinite(sigma)) or np.any(sigma <= 0):
            # 历史不足够任何一条腿:等权
            w = np.ones(len(LEGS)) / len(LEGS)
        else:
            inv = 1.0 / sigma
            w = inv / inv.sum()
        out.append({LEGS[i]: float(w[i]) for i in range(len(LEGS))})
    return out


def assert_weights_sum_to_one(weights: list[dict[str, float]]) -> None:
    """红测:每月权重和 = 1。"""
    bad = []
    for i, w in enumerate(weights):
        s = sum(w.values())
        if abs(s - 1.0) > 1e-9:
            bad.append((i, s))
    assert not bad, f"权重加总 != 1 在 {len(bad)} 个月(首例 {bad[0]})"


# ── 策略 ─────────────────────────────────────────────────────────────────────

def hold_path(n: int) -> np.ndarray:
    return np.ones(n)


def x1v_path(close: np.ndarray) -> np.ndarray:
    g = path(close, "l20")
    vs = vol_scale(close)
    n = len(close)
    g = np.where(np.arange(n) >= 200, g * vs, g)
    return g


def leg_strategy(close: np.ndarray, sym: str) -> np.ndarray:
    """加密腿返回 H;TradFi 也返回 H(任务说"加密腿持有 vs X1V")。但提供 X1V 接口给 X1V 组合用。"""
    return hold_path(len(close))


# ── 资金费 ───────────────────────────────────────────────────────────────────

def fund_daily(dates: list[str], sym: str) -> np.ndarray:
    """无 funding 数据 ⇒ 多头 10%/年(2020 前是 fallback),非加密 0;从 2020-01 起加密用 fallback 10% 也行
    —— 真实 funding 没在 Mac 数据根,统一按 fallback。"""
    if sym not in CRYPTO:
        return np.zeros(len(dates))
    return np.full(len(dates), FALLBACK_FUND / 365)


# ── 组合收益 ────────────────────────────────────────────────────────────────

def portfolio_returns(dates: list[str], closes: dict[str, np.ndarray],
                      weights: list[dict[str, float]], leg_g: dict[str, np.ndarray]) -> np.ndarray:
    """按月分段:每月 [t_start, t_start+30) 用当月权重,各腿 r_i = returns(c_i, g_i, fl, fs),
    加权组合 r = sum_i w_i * r_i。空余的现金(1 − Σw_i*g_i,t)收益 0。"""
    n = len(dates)
    r = np.zeros(n)
    fund_long = {s: fund_daily(dates, s) for s in LEGS}
    fund_short = {s: np.zeros(n) for s in LEGS}                  # 这些臂不开空
    per_leg_ret = {s: returns(closes[s], leg_g[s], fund_long[s], fund_short[s]) for s in LEGS}
    rebal = list(range(0, n, REBAL_DAYS))
    for i, t in enumerate(rebal):
        end = min(t + REBAL_DAYS, n)
        w = weights[i]
        seg = np.zeros(end - t)
        for s in LEGS:
            seg += w[s] * per_leg_ret[s][t:end]
        # 月内用月度权重,跨月不调;空出部分现金 0
        r[t:end] = seg
    return r


# ── 指标 ─────────────────────────────────────────────────────────────────────

def metrics(r: np.ndarray) -> dict[str, float]:
    """年化、最大回撤、Calmar、最差 12 个月。r 是日收益(0 起)。"""
    x = r[1:] if r[0] == 0 else r            # 第 0 天是占位
    nav = np.cumprod(1 + x)
    yrs = max(len(x) / 365.0, 1e-9)
    cagr = float(nav[-1] ** (1 / yrs) - 1)
    dd = nav / np.maximum.accumulate(nav) - 1
    max_dd = float(dd.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else float("nan")
    # 最差 12 个月(滚动 365 日对数收益最小)
    roll = pd_rolling_logsum(x, 365)
    worst_12m = float(roll.min()) if roll.size else 0.0
    return {"years": yrs, "total_x": float(nav[-1]), "cagr": cagr, "max_dd": max_dd,
            "calmar": calmar, "worst_12m": worst_12m,
            "vol_ann": float(x.std(ddof=1) * math.sqrt(365))}


def pd_rolling_logsum(r: np.ndarray, window: int) -> np.ndarray:
    """滚动 window 日的对数收益和。r 长度 ≥ window。"""
    lr = np.log1p(r)
    cs = np.cumsum(lr)
    out = np.full(len(r) - window + 1, np.nan)
    for i in range(len(out)):
        out[i] = cs[i + window - 1] - (cs[i - 1] if i > 0 else 0.0)
    return out


def attribution(dates: list[str], closes: dict[str, np.ndarray],
                weights: list[dict[str, float]], leg_g: dict[str, np.ndarray]) -> dict[str, float]:
    """各腿贡献:log(1 + leg_contribution_i) 加总 ≈ log(1 + portfolio_total)。
    整段 daily return 算一次,按月取切片乘月度权重。"""
    n = len(dates)
    contrib = {s: 0.0 for s in LEGS}
    fund_long = {s: fund_daily(dates, s) for s in LEGS}
    fund_short = {s: np.zeros(n) for s in LEGS}
    leg_r = {s: returns(closes[s], leg_g[s], fund_long[s], fund_short[s]) for s in LEGS}
    rebal = list(range(0, n, REBAL_DAYS))
    for i, t in enumerate(rebal):
        end = min(t + REBAL_DAYS, n)
        for s in LEGS:
            seg = leg_r[s][t:end]
            contrib[s] += float(np.log1p(seg[1:] if seg.size and seg[0] == 0 else seg).sum()) * weights[i][s]
    return contrib


# ── 对照 ─────────────────────────────────────────────────────────────────────

def run_60_40(dates: list[str], closes: dict[str, np.ndarray]) -> np.ndarray:
    """60% SPY + 40% AGG,月度再平衡到 60/40。TradFi 无资金费。"""
    n = len(dates)
    r = np.zeros(n)
    spy_r = returns(closes["SPY"], hold_path(n), np.zeros(n), np.zeros(n))
    agg_r = returns(closes["AGG"], hold_path(n), np.zeros(n), np.zeros(n))
    for t in range(0, n, REBAL_DAYS):
        end = min(t + REBAL_DAYS, n)
        r[t:end] = 0.6 * spy_r[t:end] + 0.4 * agg_r[t:end]
    return r


def run_all_btc(dates: list[str], closes: dict[str, np.ndarray]) -> np.ndarray:
    n = len(dates)
    fl = fund_daily(dates, "BTC")
    fs = np.zeros(n)
    return returns(closes["BTC"], hold_path(n), fl, fs)


# ── 主流程 ───────────────────────────────────────────────────────────────────

def slice_start(dates: list[str], arr: np.ndarray, start: str = START) -> np.ndarray:
    i = next((k for k, d in enumerate(dates) if d >= start), len(dates))
    return arr[i:]


def slice_start_dict(dates: list[str], closes: dict[str, np.ndarray], start: str = START
                     ) -> tuple[list[str], dict[str, np.ndarray]]:
    i = next((k for k, d in enumerate(dates) if d >= start), len(dates))
    return dates[i:], {k: v[i:] for k, v in closes.items()}


def slice_weights(dates: list[str], weights: list[dict[str, float]], start: str = START
                  ) -> list[dict[str, float]]:
    """按 2016 起重对齐:每月 [t_start, t_start+30) 对应一个权重,但有些 rebal 整段都在 2016 之前就丢掉。"""
    i = next((k for k, d in enumerate(dates) if d >= start), len(dates))
    # rebal 是按 dates 索引 0/30/60/...;每个月对应 rebal[t//30];第一个 rebal ≥ i 的纳入
    rebal = list(range(0, len(dates), REBAL_DAYS))
    keep = []
    for j, t in enumerate(rebal):
        end = min(t + REBAL_DAYS, len(dates))
        if end <= i:
            continue
        keep.append(weights[j])
    return keep


def run(research: str, out_path: str | None = None) -> dict[str, Any]:
    dates_all, closes_all = load_close(research)
    weights_full = weights_monthly(dates_all, closes_all)
    assert_weights_sum_to_one(weights_full)            # 红测

    dates, closes = slice_start_dict(dates_all, closes_all, START)
    # 把 2016 之前的 rebal 月丢掉,只留与切片后 rebal 点对齐的权重
    n = len(dates)
    n_rebal = (n + REBAL_DAYS - 1) // REBAL_DAYS
    drop = len(weights_full) - n_rebal
    weights = weights_full[drop:]

    # 组合 A:5 条腿加权,加密腿都用 H
    leg_g_h = {s: hold_path(len(dates)) for s in LEGS}
    r_h = portfolio_returns(dates, closes, weights, leg_g_h)

    # 组合 B:5 条腿加权,加密腿用 X1V(非加密仍 H,因为非加密波动率缩放意义不在策略层)
    leg_g_x = {s: (x1v_path(closes[s]) if s in CRYPTO else hold_path(len(dates))) for s in LEGS}
    r_x = portfolio_returns(dates, closes, weights, leg_g_x)

    r_60_40 = run_60_40(dates, closes)
    r_btc = run_all_btc(dates, closes)

    out = {
        "meta": {"legs": LEGS, "crypto": list(CRYPTO), "rebal_days": REBAL_DAYS,
                 "vol_lookback": VOL_LOOKBACK, "start": START, "end": dates[-1],
                 "n_days": len(dates), "first": dates[0], "n_months": len(weights)},
        "weights_first_rebal": weights[0],
        "weights_last_rebal": weights[-1],
        "weights_min_max_dispersion": {
            "min_BTC": float(min(w["BTC"] for w in weights)),
            "max_BTC": float(max(w["BTC"] for w in weights)),
            "min_AGG": float(min(w["AGG"] for w in weights)),
            "max_AGG": float(max(w["AGG"] for w in weights)),
        },
        "portfolio_hold":  {**metrics(r_h),  "attribution": attribution(dates, closes, weights, leg_g_h)},
        "portfolio_x1v":   {**metrics(r_x),  "attribution": attribution(dates, closes, weights, leg_g_x)},
        "bench_60_40":     metrics(r_60_40),
        "bench_all_btc":   metrics(r_btc),
        "ab_x1v_vs_hold":  {k: v for k, v in ab_test(list(r_h[1:]), list(r_x[1:]), mean_block=20, days_per_year=365).items()
                            if k in ("verdict", "ratio_b_over_a", "p_b_le_a", "log_diff_total", "underpowered", "n_days", "years")},
        "ab_x1v_vs_btc":   {k: v for k, v in ab_test(list(r_btc[1:]), list(r_x[1:]), mean_block=20, days_per_year=365).items()
                            if k in ("verdict", "ratio_b_over_a", "p_b_le_a", "log_diff_total", "underpowered", "n_days", "years")},
        "ab_x1v_vs_6040":  {k: v for k, v in ab_test(list(r_60_40[1:]), list(r_x[1:]), mean_block=20, days_per_year=365).items()
                            if k in ("verdict", "ratio_b_over_a", "p_b_le_a", "log_diff_total", "underpowered", "n_days", "years")},
    }
    if out_path:
        Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))
    return out


def format_table(out: dict[str, Any]) -> str:
    h = out["portfolio_hold"]; x = out["portfolio_x1v"]; b60 = out["bench_60_40"]; btc = out["bench_all_btc"]
    lines = [
        f"区间 {out['meta']['start']} → {out['meta']['end']}  {out['meta']['n_days']} 天 / {out['meta']['n_months']} 月",
        "",
        f"{'组合':18s} {'总倍':>8s} {'年化':>8s} {'最大回撤':>10s} {'Calmar':>8s} {'最差12m':>10s} {'年化波':>8s}",
        f"{'五条腿 H':18s} {h['total_x']:7.2f}x {h['cagr']*100:6.1f}%  {h['max_dd']*100:6.1f}%  {h['calmar']:6.2f}  {h['worst_12m']*100:6.1f}%  {h['vol_ann']*100:6.1f}%",
        f"{'五条腿 X1V':18s} {x['total_x']:7.2f}x {x['cagr']*100:6.1f}%  {x['max_dd']*100:6.1f}%  {x['calmar']:6.2f}  {x['worst_12m']*100:6.1f}%  {x['vol_ann']*100:6.1f}%",
        f"{'对照 60/40':18s} {b60['total_x']:7.2f}x {b60['cagr']*100:6.1f}%  {b60['max_dd']*100:6.1f}%  {b60['calmar']:6.2f}  {b60['worst_12m']*100:6.1f}%  {b60['vol_ann']*100:6.1f}%",
        f"{'对照 全持 BTC':18s} {btc['total_x']:7.2f}x {btc['cagr']*100:6.1f}%  {btc['max_dd']*100:6.1f}%  {btc['calmar']:6.2f}  {btc['worst_12m']*100:6.1f}%  {btc['vol_ann']*100:6.1f}%",
        "",
        f"A/B(X1V vs H): {out['ab_x1v_vs_hold']['verdict']}  ratio={out['ab_x1v_vs_hold']['ratio_b_over_a']:.3f}  p(B≤A)={out['ab_x1v_vs_hold']['p_b_le_a']:.3f}  underpowered={out['ab_x1v_vs_hold']['underpowered']}",
        f"A/B(X1V vs BTC): {out['ab_x1v_vs_btc']['verdict']}  ratio={out['ab_x1v_vs_btc']['ratio_b_over_a']:.3f}  p(B≤A)={out['ab_x1v_vs_btc']['p_b_le_a']:.3f}  underpowered={out['ab_x1v_vs_btc']['underpowered']}",
        f"A/B(X1V vs 60/40): {out['ab_x1v_vs_6040']['verdict']}  ratio={out['ab_x1v_vs_6040']['ratio_b_over_a']:.3f}  p(B≤A)={out['ab_x1v_vs_6040']['p_b_le_a']:.3f}  underpowered={out['ab_x1v_vs_6040']['underpowered']}",
        "",
        "各腿贡献(对数收益,权重 × 月度):",
        f"  五腿 H:    BTC={h['attribution']['BTC']:+.2f} ETH={h['attribution']['ETH']:+.2f} XAU={h['attribution']['XAUUSD']:+.2f} SPY={h['attribution']['SPY']:+.2f} AGG={h['attribution']['AGG']:+.2f}",
        f"  五腿 X1V:  BTC={x['attribution']['BTC']:+.2f} ETH={x['attribution']['ETH']:+.2f} XAU={x['attribution']['XAUUSD']:+.2f} SPY={x['attribution']['SPY']:+.2f} AGG={x['attribution']['AGG']:+.2f}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    research = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    out = run(research, out_path)
    print(format_table(out))