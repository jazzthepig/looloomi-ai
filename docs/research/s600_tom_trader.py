"""S-600 —— Trader Tom 交易模拟 v2:跌破就空仓、熊市里赚了就跑、或者开空(预注册见 REFUTATION_LEDGER §S-600)。

用法:python3 docs/research/s600_tom_trader.py <w50_daily/close.json> <funding_monthly.txt> [输出 json]
多头:收盘 > 200 日线且 > 前 20 日高 ⇒ 多 1.0;多头时照 S-596 加仓(> 55 日高 +0.1、每 +10% 再 +0.1,上限 1.3,破 20 日低撤加仓)。
跌破:多头时收盘 < 200 日线且 < 前 20 日低 ⇒ 全部平掉。熊市里:F 空仓;FB 反弹多 0.5、+15% 止盈 / 破 10 日低止损;
S50 / S100 开空 −0.5 / −1.0、价格 −20% 止盈平空 / 破 20 日高止损。第 t 天收盘判断、t+1 生效;前 200 天持有 1.0。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import ab_test, null_distribution, percentile_of  # noqa: E402
from s596_tom_pyramid import SEGS, gross_path, load, stats, zigzag  # noqa: E402

COST, UNIT, STEP, CAP, MA_N, WARM = 10 / 1e4, 0.1, 1.10, 1.3, 200, 200
RALLY_SIZE, RALLY_TP, SHORT_TP = 0.5, 1.15, 0.80
ARMS = {"F": ("flat", 0.0), "FB": ("rally", 0.0), "S50": ("short", -0.5), "S100": ("short", -1.0)}


def trade_path(c: np.ndarray, bear: str, short_size: float) -> tuple[np.ndarray, dict]:
    """g[t] = 第 t 天收盘定下、t+1 生效的净敞口。纯函数。"""
    n = len(c)
    g = np.ones(n)
    mode, k, last_add, entry = "long", 0, None, None
    ev = {"breakdowns": 0, "long_entries": 0, "rally_tp": 0, "rally_stop": 0, "short_entries": 0, "short_tp": 0, "short_stop": 0}
    for t in range(WARM, n):
        x = c[t]
        ma = c[t - MA_N + 1:t + 1].mean()
        h20, l20, h55, l10 = c[t - 20:t].max(), c[t - 20:t].min(), c[t - 55:t].max(), c[t - 10:t].min()
        long_entry = x > ma and x > h20
        if mode == "long":
            if k > 0 and x < l20:
                k, last_add = 0, None
            elif k == 0 and x > h55 and 1 + UNIT <= CAP + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * STEP and 1 + UNIT * (k + 1) <= CAP + 1e-9:
                k, last_add = k + 1, x
            if x < ma and x < l20:
                ev["breakdowns"] += 1
                k, last_add = 0, None
                if bear == "short":
                    mode, entry = "short", x
                    ev["short_entries"] += 1
                else:
                    mode = "flat"
        elif mode == "flat":
            if long_entry:
                mode, k = "long", 0
                ev["long_entries"] += 1
            elif bear == "rally" and x > h20:
                mode, entry = "rally", x
            elif bear == "short" and x < ma and x < l20:
                mode, entry = "short", x
                ev["short_entries"] += 1
        elif mode == "rally":
            if long_entry:
                mode, k = "long", 0
                ev["long_entries"] += 1
            elif x >= entry * RALLY_TP:
                mode = "flat"; ev["rally_tp"] += 1
            elif x < l10:
                mode = "flat"; ev["rally_stop"] += 1
        elif mode == "short":
            if long_entry:
                mode, k = "long", 0
                ev["long_entries"] += 1
            elif x <= entry * SHORT_TP:
                mode = "flat"; ev["short_tp"] += 1
            elif x > h20:
                mode = "flat"; ev["short_stop"] += 1
        g[t] = {"long": 1 + UNIT * k, "flat": 0.0, "rally": RALLY_SIZE, "short": short_size}[mode]
    return g, ev


def returns(c: np.ndarray, g: np.ndarray, fund_long: np.ndarray, fund_short: np.ndarray) -> np.ndarray:
    px = c[1:] / c[:-1] - 1
    gp = g[:-1]
    prev = np.concatenate([[1.0], g[:-2]])
    r = (gp * px - np.maximum(gp - 1, 0) * fund_long[1:] + np.maximum(-gp, 0) * fund_short[1:]
         - np.abs(gp - prev) * COST)
    return np.concatenate([[0.0], r])


def run_asset(close_path: str, fund_path: str, sym: str) -> dict[str, Any]:
    dates, c, fund_long = load(close_path, fund_path, sym)
    # 空头:2020 前资金费按 0(保守);之后用当月实际(fund_long 在 2020 前是 10% 回退值)
    fund_short = np.array([f if d >= "2020-01" else 0.0 for d, f in zip(dates, fund_long)])
    h = returns(c, np.ones(len(c)), fund_long, fund_short)
    out: dict[str, Any] = {"first": dates[0], "last": dates[-1], "H": {**stats(h), "segments": {}}, "arms": {}}
    seg_mask = {nm: np.array([lo <= d <= hi for d in dates]) for nm, lo, hi in SEGS}
    for nm, m in seg_mask.items():
        out["H"]["segments"][nm] = float(np.log1p(h[m]).sum())
    g96, _ = gross_path(c, 1.3, True)
    out["PD13_ref"] = stats(returns(c, g96, fund_long, fund_short))
    zz = zigzag(c)
    for arm, (bear, size) in ARMS.items():
        g, ev = trade_path(c, bear, size)
        r = returns(c, g, fund_long, fund_short)
        avg = float(g.mean())
        const = returns(c, np.full(len(c), avg), fund_long, fund_short)
        row = {**stats(r), "avg_net_exposure": avg, "short_day_share": float((g < 0).mean()), "flat_day_share": float((g == 0).mean()),
               "events": ev, "segments": {nm: float(np.log1p(r[m]).sum()) for nm, m in seg_mask.items()},
               "const_same_avg": stats(const)}
        row["ab_vs_H"] = {k: v for k, v in ab_test(list(h[1:]), list(r[1:]), mean_block=20, days_per_year=365).items()
                          if k in ("verdict", "ratio_b_over_a", "p_b_le_a", "underpowered")}
        row["ab_vs_const"] = {k: v for k, v in ab_test(list(const[1:]), list(r[1:]), mean_block=20, days_per_year=365).items()
                              if k in ("verdict", "ratio_b_over_a", "p_b_le_a", "underpowered")}
        actual = float(np.log1p(r).sum())

        def shuffled(rng, g=g):
            return float(np.log1p(returns(c, np.roll(g, int(rng.integers(30, len(g) - 30))), fund_long, fund_short)).sum())
        row["random_timing_pct"] = percentile_of(actual, null_distribution(shuffled, 1000, seed=600, actual=actual))
        row["segments_won"] = sum(1 for nm in row["segments"] if row["segments"][nm] > out["H"]["segments"][nm])
        up = dn = upH = dnH = 0.0
        for s, e, kind in zz:
            if e <= s:
                continue
            a = float(np.log1p(r[s + 1:e + 1]).sum()); b = float(np.log1p(h[s + 1:e + 1]).sum())
            if kind == "UP":
                up += a; upH += b
            else:
                dn += a; dnH += b
        row["zigzag"] = {"up_minus_H": up - upH, "down_minus_H": dn - dnH}
        row["passes"] = (row["ab_vs_H"]["verdict"] == "B > A" and row["ab_vs_const"]["verdict"] == "B > A"
                         and (row["random_timing_pct"] or 0) >= 0.95 and row["segments_won"] >= 2)
        out["arms"][arm] = row
    return out


def main(close_path: str, fund_path: str, out_path: Optional[str] = None) -> dict:
    res = {sym: run_asset(close_path, fund_path, sym) for sym in ("BTC", "ETH")}
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    r = main(*sys.argv[1:4])
    for sym, a in r.items():
        H = a["H"]
        print(f"== {sym} {a['first']} → {a['last']}  H {H['total_x']:.1f}x CAGR {H['cagr']*100:.1f}% MDD {H['max_dd']*100:.1f}%  "
              f"segs {', '.join(f'{k} {v:+.2f}' for k, v in H['segments'].items())} | PD13 {a['PD13_ref']['total_x']:.1f}x MDD {a['PD13_ref']['max_dd']*100:.1f}%")
        for arm, v in a["arms"].items():
            cs = v["const_same_avg"]
            print(f"  {arm:5s} {v['total_x']:8.1f}x CAGR {v['cagr']*100:6.1f}% MDD {v['max_dd']*100:6.1f}% avg {v['avg_net_exposure']:.2f} "
                  f"short {v['short_day_share']:.2f} flat {v['flat_day_share']:.2f} | const {cs['total_x']:.1f}x MDD {cs['max_dd']*100:.1f}%\n"
                  f"        vsH {v['ab_vs_H']['verdict']} {v['ab_vs_H']['ratio_b_over_a']:.2f} p {v['ab_vs_H']['p_b_le_a']:.3f} | "
                  f"vsC {v['ab_vs_const']['verdict']} {v['ab_vs_const']['ratio_b_over_a']:.2f} p {v['ab_vs_const']['p_b_le_a']:.3f} | "
                  f"rand {v['random_timing_pct']:.3f} | segs {', '.join(f'{x:+.2f}' for x in v['segments'].values())} won {v['segments_won']} | "
                  f"zz up {v['zigzag']['up_minus_H']:+.2f} down {v['zigzag']['down_minus_H']:+.2f} | {v['events']} | PASS {v['passes']}")
