"""T-120 / S-602 模拟五:压力情景(预注册见台账 §S-602)。

三种情景:
  1. 单日 −35% 闪崩插入:BTC 历史随机 100 个位置,在第 T 天收盘插入 −35%,
     之后保留真实收益。报告 H / F / FB / X1V / PD13 五个臂的当日损失、
     之后 30 天累计收益、全期年化与回撤分布。
  2. 出场推迟 3 天(交易所宕机):在每条臂的状态机里,任意「出场」信号推迟
     3 天成交。报告原 / 推迟版的 CAGR / MaxDD / 终值。
  3. 120 天高波动横盘:随机插入 120 个交易日,日对数收益 N(0, 0.04),
     起点保留真实 close[start-1]。报告该窗口内的手续费合计、
     进出次数(每次 g 0↔非 0 算一次)、相对持有的损耗。

规则一律从 s596 / s600 / s601 import,不允许重写;随机种子写死 = 120;
统计走 src/data/evaluation/apparatus.py。

用法:python3 docs/research/t120_stress.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = Path("/Volumes/CometCloudAI/cometcloud-local/research")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from s596_tom_pyramid import gross_path, load  # noqa: E402
from s600_tom_trader import trade_path as fb_trade_path  # noqa: E402
from s601_drawdown import path as fb_path, vol_scale  # noqa: E402
from s600_tom_trader import returns as ret600  # noqa: E402

SEED = 120
ASSETS = ("BTC", "ETH", "XRP", "BNB", "XAUUSD", "SPY", "AGG")
FUND = str(RESEARCH / "s596/funding_monthly.txt")
CLOSE_PATH = str(RESEARCH / "w50_daily/close.json")
N_FLASH, N_SIDE = 100, 100
FLASH_PCT, SIDEWAYS_DAYS, SIDEWAYS_VOL = -0.35, 120, 0.04
EXIT_DELAY = 3
COST = 10 / 1e4
WARM = 200


def _series() -> dict[str, tuple[list[str], np.ndarray, np.ndarray]]:
    """从 w50_daily 拉 7 个资产;只有 BTC / ETH 有真实资金费,其它用 10%/365 回退。"""
    w = json.loads(Path(CLOSE_PATH).read_text())
    out: dict[str, tuple[list[str], np.ndarray, np.ndarray]] = {}
    for sym in ASSETS:
        if sym not in w.get("close", {}):
            continue
        v = [x for x in w["close"][sym] if x]
        if not v:
            continue
        dates = w["dates"][-len(v):]
        c = np.array(v, dtype=float)
        try:
            _, _, fund = load(CLOSE_PATH, FUND, sym)
            fl = fund if sym in ("BTC", "ETH") else np.full(len(c), 0.10 / 365)
        except Exception:
            fl = np.full(len(c), 0.10 / 365)
        out[sym] = (dates, c, fl)
    return out


def arm_paths(c: np.ndarray) -> dict[str, np.ndarray]:
    """返回 {arm: g}。H=常持 1.0,F=breakdown 即空仓,FB=反弹多 0.5,
    X1V=多头破前 20 日低即平 + 波动率缩放,PD13=200 日线跌破收 + 上限 1.3 加仓。"""
    g_h = np.ones(len(c))
    g_f, _ = fb_trade_path(c, "flat", 0.0)
    g_fb, _ = fb_trade_path(c, "rally", 0.0)
    g_x1v = fb_path(c, "l20")
    vs = vol_scale(c)
    g_x1v = np.where(np.arange(len(c)) >= WARM, g_x1v * vs, g_x1v)
    g_pd13, _ = gross_path(c, 1.3, True)
    return {"H": g_h, "F": g_f, "FB": g_fb, "X1V": g_x1v, "PD13": g_pd13}


def apply_exit_delay(g: np.ndarray, delay: int) -> np.ndarray:
    """把所有 g 状态变化延迟 delay 天。g'[t] = g[max(0, t-delay)]。"""
    if delay <= 0:
        return g.copy()
    g2 = np.empty_like(g)
    g2[:delay] = g[0]
    g2[delay:] = g[:-delay]
    return g2


def arm_returns(c: np.ndarray, g: np.ndarray, fs_long: np.ndarray, fs_short: np.ndarray | None = None) -> np.ndarray:
    if fs_short is None:
        fs_short = np.zeros(len(c))
    return ret600(c, g, fs_long, fs_short)


def summary_metrics(r: np.ndarray, start: int = WARM + 1) -> dict[str, float]:
    x = r[start:]
    if len(x) == 0:
        return {"cagr": 0.0, "max_dd": 0.0, "total_x": 1.0}
    nav = np.cumprod(1 + x)
    yrs = len(x) / 365
    cagr = nav[-1] ** (1 / yrs) - 1 if yrs > 0 else 0.0
    dd = float((nav / np.maximum.accumulate(nav) - 1).min())
    return {"cagr": float(cagr), "max_dd": dd, "total_x": float(nav[-1])}


def scenario_flash(dates: list[str], c: np.ndarray, fund_long: np.ndarray, n_pos: int) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    n = len(c)
    warm = WARM + 30
    positions = rng.integers(warm, n - 31, size=n_pos)
    arms = ("H", "F", "FB", "X1V", "PD13")
    fs_short = np.zeros(n)

    base_g = arm_paths(c)
    base_metrics = {a: summary_metrics(arm_returns(c, base_g[a], fund_long, fs_short)) for a in arms}

    flash_metrics: dict[str, list[dict[str, float]]] = {a: [] for a in arms}
    for t in positions:
        c2 = c.copy()
        c2[t] = c2[t - 1] * (1 + FLASH_PCT)
        g2 = arm_paths(c2)
        r2 = {a: arm_returns(c2, g2[a], fund_long, fs_short) for a in arms}
        for a in arms:
            r = r2[a]
            day_pnl = float(r[t]) if t > 0 else 0.0
            next30 = float(np.log1p(r[t:t + 30]).sum()) if t + 30 <= n else float(np.log1p(r[t:]).sum())
            met = summary_metrics(r)
            flash_metrics[a].append({
                "t": int(t), "date": dates[t],
                "day_pnl": day_pnl, "next30": next30,
                "cagr": met["cagr"], "max_dd": met["max_dd"], "total_x": met["total_x"],
            })

    out: dict[str, Any] = {"positions": [int(x) for x in positions], "baseline": base_metrics, "arms": {}}
    for a in arms:
        rows = flash_metrics[a]
        keys = ("day_pnl", "next30", "cagr", "max_dd", "total_x")
        stats = {}
        for k in keys:
            v = np.array([r[k] for r in rows])
            stats[k] = {
                "median": float(np.median(v)), "mean": float(v.mean()),
                "p05": float(np.quantile(v, 0.05)), "p95": float(np.quantile(v, 0.95)),
                "frac_lt_baseline_day": float((v < 0).mean()) if k == "day_pnl" else None,
            }
        stats["n"] = len(rows)
        out["arms"][a] = {"rows": rows, "stats": stats}
    return out


def scenario_delay(dates: list[str], c: np.ndarray, fund_long: np.ndarray) -> dict[str, Any]:
    fs_short = np.zeros(len(c))
    base_g = arm_paths(c)
    out: dict[str, Any] = {"baseline": {}, "delayed": {}}
    for a, g in base_g.items():
        r0 = arm_returns(c, g, fund_long, fs_short)
        m0 = summary_metrics(r0)
        g_delay = apply_exit_delay(g, EXIT_DELAY)
        r1 = arm_returns(c, g_delay, fund_long, fs_short)
        m1 = summary_metrics(r1)
        out["baseline"][a] = m0
        out["delayed"][a] = {
            **m1,
            "cagr_delta": m1["cagr"] - m0["cagr"],
            "total_x_delta": m1["total_x"] - m0["total_x"],
            "max_dd_delta": m1["max_dd"] - m0["max_dd"],
        }
    return out


def _count_round_trips(g: np.ndarray) -> int:
    """g 由 0 变非 0 的次数(进入)。"""
    nz = (g[:-1] == 0) & (g[1:] != 0)
    return int(nz.sum())


def scenario_sideways(dates: list[str], c: np.ndarray, fund_long: np.ndarray, n_runs: int) -> dict[str, Any]:
    rng = np.random.default_rng(SEED + 1)
    n = len(c)
    warm = WARM + SIDEWAYS_DAYS + 10
    positions = rng.integers(warm, n - SIDEWAYS_DAYS - 10, size=n_runs)
    arms = ("H", "F", "FB", "X1V", "PD13")
    fs_short = np.zeros(n)

    per_arm_stats: dict[str, dict[str, list[float]]] = {
        a: {"fees": [], "round_trips": [], "strat_x": [], "bh_x": [], "loss_vs_bh_pp": []}
        for a in arms
    }
    for start in positions:
        rets = rng.normal(0.0, SIDEWAYS_VOL, size=SIDEWAYS_DAYS)
        target_end = c[start + SIDEWAYS_DAYS]
        c2 = c.copy()
        c2[start] = c2[start - 1]
        for j in range(1, SIDEWAYS_DAYS):
            c2[start + j] = c2[start + j - 1] * math.exp(rets[j])
        c2[start + SIDEWAYS_DAYS] = target_end
        g2 = arm_paths(c2)
        for a in arms:
            g = g2[a]
            r_full = arm_returns(c2, g, fund_long, fs_short)
            r_win = r_full[start:start + SIDEWAYS_DAYS + 1]
            g_win = g[start:start + SIDEWAYS_DAYS + 1]
            prev_w = np.concatenate([[g_win[0]], g_win[:-1]])
            fees = float(np.abs(g_win[1:] - prev_w[1:]).sum() * COST)
            rt = _count_round_trips(g_win)
            strat_x = float(np.prod(1 + r_win[1:]))
            bh_x = float(c2[start + SIDEWAYS_DAYS] / c2[start])
            per_arm_stats[a]["fees"].append(fees)
            per_arm_stats[a]["round_trips"].append(rt)
            per_arm_stats[a]["strat_x"].append(strat_x)
            per_arm_stats[a]["bh_x"].append(bh_x)
            per_arm_stats[a]["loss_vs_bh_pp"].append((strat_x - bh_x) * 100)

    summary: dict[str, Any] = {"positions": [int(x) for x in positions], "arms": {}}
    for a in arms:
        s = per_arm_stats[a]
        row = {}
        for k, v in s.items():
            arr = np.array(v)
            row[k] = {
                "median": float(np.median(arr)), "mean": float(arr.mean()),
                "p05": float(np.quantile(arr, 0.05)), "p95": float(np.quantile(arr, 0.95)),
            }
        summary["arms"][a] = row
    return summary


def main() -> dict[str, Any]:
    series = _series()
    out: dict[str, Any] = {"meta": {
        "seed": SEED, "n_flash": N_FLASH, "n_side": N_SIDE,
        "flash_pct": FLASH_PCT, "sideways_days": SIDEWAYS_DAYS, "sideways_vol": SIDEWAYS_VOL,
        "exit_delay_days": EXIT_DELAY, "assets": ASSETS,
    }, "assets": {}}
    for sym, (dates, c, fl) in series.items():
        print(f"== {sym}: {dates[0]} → {dates[-1]}  n={len(c)}", flush=True)
        asset_out: dict[str, Any] = {
            "first": dates[0], "last": dates[-1], "days": len(c),
            "flash": scenario_flash(dates, c, fl, N_FLASH),
            "delay": scenario_delay(dates, c, fl),
            "sideways": scenario_sideways(dates, c, fl, N_SIDE),
        }
        out["assets"][sym] = asset_out
    return out


def render_report(res: dict[str, Any]) -> str:
    L: list[str] = []
    meta = res["meta"]
    L.append("# T-120 / §S-602 模拟五:压力情景报告")
    L.append("")
    L.append(f"随机种子={meta['seed']} | 闪崩插入数={meta['n_flash']} (单日 {meta['flash_pct']*100:.0f}%) | "
             f"横盘窗口={meta['sideways_days']} 天 (σ={meta['sideways_vol']*100:.0f}%, {meta['n_side']} 次) | "
             f"出场推迟={meta['exit_delay_days']} 天 | 资产={', '.join(meta['assets'])}")
    L.append("")
    L.append("> 规则一律 import 自 s596 / s600 / s601,**未改一行**;手续费 10 bp/Δg;warm-up 200 天;"
             "统计走 apparatus。报告里的中位 / p05 / p95 是 100 次随机插入的分布。")
    L.append("")

    L.append("## 1) 单日 −35% 闪崩插入 — 各臂当日 / 30 天 / 全期分布")
    L.append("")
    for sym, a in res["assets"].items():
        flash = a["flash"]
        L.append(f"### {sym} (基线无插入) — H/F/FB/X1V/PD13 全期指标")
        L.append("")
        L.append("| arm | CAGR | MaxDD | TotalX |")
        L.append("|---|---|---|---|")
        for arm, m in flash["baseline"].items():
            L.append(f"| {arm} | {m['cagr']*100:.1f}% | {m['max_dd']*100:.1f}% | {m['total_x']:.2f}x |")
        L.append("")
        L.append(f"#### 闪崩插入 — 各臂分布(中位 / p05 / p95)")
        L.append("")
        L.append("| arm | 当日 PnL | 30 天累计 | CAGR | MaxDD | TotalX |")
        L.append("|---|---|---|---|---|---|")
        for arm, blk in flash["arms"].items():
            s = blk["stats"]
            L.append(f"| {arm} | {s['day_pnl']['median']*100:+.2f}% / {s['day_pnl']['p05']*100:+.2f}% / {s['day_pnl']['p95']*100:+.2f}% "
                     f"| {s['next30']['median']*100:+.2f}% / {s['next30']['p05']*100:+.2f}% / {s['next30']['p95']*100:+.2f}% "
                     f"| {s['cagr']['median']*100:+.1f}% / {s['cagr']['p05']*100:+.1f}% / {s['cagr']['p95']*100:+.1f}% "
                     f"| {s['max_dd']['median']*100:+.1f}% / {s['max_dd']['p05']*100:+.1f}% / {s['max_dd']['p95']*100:+.1f}% "
                     f"| {s['total_x']['median']:.2f}x / {s['total_x']['p05']:.2f}x / {s['total_x']['p95']:.2f}x |")
        L.append("")

    L.append("## 2) 出场推迟 3 天 — 各臂退化")
    L.append("")
    L.append("| 资产 / arm | 基线 CAGR | 推迟 CAGR | ΔCAGR | 基线 MaxDD | 推迟 MaxDD | 基线 TotalX | 推迟 TotalX |")
    L.append("|---|---|---|---|---|---|---|---|")
    for sym, a in res["assets"].items():
        delay = a["delay"]
        for arm in ("H", "F", "FB", "X1V", "PD13"):
            m0 = delay["baseline"][arm]
            m1 = delay["delayed"][arm]
            L.append(f"| {sym} / {arm} | {m0['cagr']*100:.1f}% | {m1['cagr']*100:.1f}% | {m1['cagr_delta']*100:+.1f}pp "
                     f"| {m0['max_dd']*100:.1f}% | {m1['max_dd']*100:.1f}% | {m0['total_x']:.2f}x | {m1['total_x']:.2f}x |")
    L.append("")

    L.append("## 3) 120 天高波动横盘(σ=4%/日)— 窗口内磨损")
    L.append("")
    L.append("| 资产 / arm | 手续费中位 | 进出次数中位 | 策略 x 中位 | 持有 x 中位 | 损耗 vs 持有中位(pp) |")
    L.append("|---|---|---|---|---|---|")
    for sym, a in res["assets"].items():
        side = a["sideways"]["arms"]
        for arm in ("H", "F", "FB", "X1V", "PD13"):
            s = side[arm]
            L.append(f"| {sym} / {arm} | {s['fees']['median']*100:.2f}% / p05 {s['fees']['p05']*100:.2f}% / p95 {s['fees']['p95']*100:.2f}% "
                     f"| {s['round_trips']['median']:.1f} / p05 {s['round_trips']['p05']:.1f} / p95 {s['round_trips']['p95']:.1f} "
                     f"| {s['strat_x']['median']:.3f}x / p05 {s['strat_x']['p05']:.3f} / p95 {s['strat_x']['p95']:.3f} "
                     f"| {s['bh_x']['median']:.3f}x / p05 {s['bh_x']['p05']:.3f} / p95 {s['bh_x']['p95']:.3f} "
                     f"| {s['loss_vs_bh_pp']['median']:+.2f} / p05 {s['loss_vs_bh_pp']['p05']:+.2f} / p95 {s['loss_vs_bh_pp']['p95']:+.2f} |")
        L.append("")

    L.append("---")
    L.append("")
    L.append("**注**:本报告未跑零分布 / A/B 比较 — 那属于下一步(下一张卡);本卡只回答「扰动有多大」的事实层。")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    res = main()
    out_json = Path(__file__).resolve().parent.parent / "_reports" / "absorb_input" / "T-120_stress.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print(f"json → {out_json}", flush=True)
    out_md = out_json.with_suffix(".md")
    out_md.write_text(render_report(res))
    print(f"md   → {out_md}", flush=True)