"""S-596 —— Trader Tom 的仓位管理(预注册见 REFUTATION_LEDGER §S-596)。

用法:python3 docs/research/s596_tom_pyramid.py <w50_daily/close.json> <funding_monthly.txt> [输出 json]
底仓 1.0;收盘创 55 日新高 ⇒ 加 0.1(记加仓价),之后每 ≥ 上次加仓价 × 1.10 再加 0.1;跌破前 20 日最低 ⇒ 撤掉所有加仓。
D 臂:收盘 < 200 日均线且跌破前 20 日最低 ⇒ 底仓 0.7;收盘 > 200 日均线 ⇒ 底仓回 1.0。第 t 天收盘判断,t+1 生效。
成本 |Δg| × 10 bp;g > 1 的部分付当月永续平均资金费(2020 前 10% 年化);g < 1 的现金收益 0。
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

from src.data.evaluation.apparatus import ab_test, null_distribution, percentile_of  # noqa: E402

COST, UNIT, STEP, HI_N, LO_N, MA_N, DEF_BASE, FALLBACK_FUND = 10 / 1e4, 0.1, 1.10, 55, 20, 200, 0.7, 0.10
ARMS = {"H": (1.0, False), "P13": (1.3, False), "P16": (1.6, False), "PD13": (1.3, True), "PD16": (1.6, True)}
SEGS = (("2015–2018", "2015-01-01", "2018-12-31"), ("2019–2022", "2019-01-01", "2022-12-31"), ("2023 → 2026-10", "2023-01-01", "2026-12-31"))


def gross_path(close: np.ndarray, cap: float, defend: bool) -> tuple[np.ndarray, dict]:
    """g[t] = 第 t 天收盘后定、t+1 天生效的敞口。纯函数。"""
    n = len(close)
    g = np.ones(n)
    b, k, last_add = 1.0, 0, None
    adds, episodes, ep_start = 0, [], None
    if cap <= 1.0:
        return g, {"adds": 0, "episodes": []}
    for t in range(n):
        c = close[t]
        if t >= HI_N:
            hi = close[t - HI_N:t].max()
            lo = close[t - LO_N:t].min()
            ma = close[t - MA_N + 1:t + 1].mean() if t >= MA_N - 1 else None
            if k > 0 and c < lo:                                  # 加的部分破位就撤
                episodes.append((ep_start, t, k))
                k, last_add = 0, None
            elif k == 0 and c > hi and b + UNIT <= cap + 1e-9:
                k, last_add, ep_start = 1, c, t
                adds += 1
            elif k > 0 and c >= last_add * STEP and b + UNIT * (k + 1) <= cap + 1e-9:
                k, last_add = k + 1, c
                adds += 1
            if defend and ma is not None:
                if c < ma and c < lo:
                    b = DEF_BASE
                elif c > ma:
                    b = 1.0
        g[t] = min(cap, b + UNIT * k)
    if k > 0:
        episodes.append((ep_start, n - 1, k))
    return g, {"adds": adds, "episodes": episodes}


def daily_returns(close: np.ndarray, g: np.ndarray, fund_daily: np.ndarray) -> np.ndarray:
    """r[t](t ≥ 1)= g[t−1] × 价格收益 − (g[t−1] − 1)+ × 资金费 − |g[t−1] − g[t−2]| × 成本。"""
    px = close[1:] / close[:-1] - 1
    gp = g[:-1]
    prev = np.concatenate([[1.0], g[:-2]])
    r = gp * px - np.maximum(gp - 1, 0) * fund_daily[1:] - np.abs(gp - prev) * COST
    return np.concatenate([[0.0], r])


def stats(r: np.ndarray) -> dict[str, float]:
    nav = np.cumprod(1 + r)
    yrs = len(r) / 365
    return {"total_x": float(nav[-1]), "cagr": float(nav[-1] ** (1 / yrs) - 1),
            "max_dd": float((nav / np.maximum.accumulate(nav) - 1).min()), "vol": float(r.std(ddof=1) * math.sqrt(365))}


def load(close_path: str, fund_path: str, sym: str):
    c = json.loads(Path(close_path).read_text())
    dates, v = c["dates"], c["close"][sym]
    pts = [(d, x) for d, x in zip(dates, v) if x]
    dates = [d for d, _ in pts]
    close = np.array([x for _, x in pts], dtype=float)
    fm = {}
    for line in Path(fund_path).read_text().splitlines():
        parts = line.split()
        if parts and parts[0] == sym:
            fm = {p.split(":")[0]: float(p.split(":")[1]) for p in parts[1:]}
    fund_daily = np.array([fm.get(d[:7], FALLBACK_FUND) / 365 for d in dates])
    return dates, close, fund_daily


def zigzag(close: np.ndarray, th: float = 0.20) -> list[tuple[int, int, str]]:
    """事后切段(只用于归因):价格从极值回撤 / 反弹 20% 换段。"""
    segs, start, ext, mode = [], 0, 0, None
    for t in range(1, len(close)):
        if mode in (None, "UP"):
            if close[t] > close[ext] or mode is None and close[t] >= close[start]:
                ext = t
            if close[t] <= close[ext] * (1 - th):
                segs.append((start, ext, "UP")); start, ext, mode = ext, t, "DOWN"
                continue
            mode = mode or "UP"
        else:
            if close[t] < close[ext]:
                ext = t
            if close[t] >= close[ext] * (1 + th):
                segs.append((start, ext, "DOWN")); start, ext, mode = ext, t, "UP"
    segs.append((start, len(close) - 1, mode or "UP"))
    return segs


def run_asset(close_path: str, fund_path: str, sym: str) -> dict[str, Any]:
    dates, close, fund = load(close_path, fund_path, sym)
    out: dict[str, Any] = {"first": dates[0], "last": dates[-1], "days": len(dates), "arms": {}}
    rets = {}
    for arm, (cap, defend) in ARMS.items():
        g, info = gross_path(close, cap, defend)
        r = daily_returns(close, g, fund)
        rets[arm] = (g, r)
        eps = info["episodes"]
        hit = [close[e] / close[s] - 1 for s, e, _ in eps if s is not None]
        row = {**stats(r), "avg_gross": float(g.mean()), "adds": info["adds"], "add_episodes": len(eps),
               "episode_hit_rate": float(np.mean([h > 0 for h in hit])) if hit else None,
               "funding_paid": float((np.maximum(g[:-1] - 1, 0) * fund[1:]).sum()),
               "segments": {}}
        for nm, lo, hi in SEGS:
            m = np.array([lo <= d <= hi for d in dates])
            if m.sum() > 30:
                row["segments"][nm] = float(np.log1p(r[m]).sum())
        out["arms"][arm] = row
    hr = rets["H"][1]
    zz = zigzag(close)
    for arm in ARMS:
        if arm == "H":
            continue
        g, r = rets[arm]
        row = out["arms"][arm]
        row["ab_vs_H"] = {k: v for k, v in ab_test(list(hr[1:]), list(r[1:]), mean_block=20, days_per_year=365).items()
                          if k in ("verdict", "ratio_b_over_a", "p_b_le_a", "log_diff_total", "underpowered")}
        seg_wins = sum(1 for nm in row["segments"] if row["segments"][nm] > out["arms"]["H"]["segments"].get(nm, 0))
        row["segments_won"] = seg_wins
        actual = float(np.log1p(r).sum())

        def shuffled(rng, g=g):
            k = int(rng.integers(30, len(g) - 30))
            gs = np.roll(g, k)
            return float(np.log1p(daily_returns(close, gs, fund)).sum())
        null = null_distribution(shuffled, 1000, seed=596, actual=actual)
        row["random_timing_pct"] = percentile_of(actual, null)
        row["passes"] = (row["ab_vs_H"]["verdict"] == "B > A" and seg_wins >= 2
                         and row["max_dd"] >= out["arms"]["H"]["max_dd"] - 0.05 and (row["random_timing_pct"] or 0) >= 0.95)
        up = dn = upH = dnH = 0.0
        for s, e, kind in zz:
            if e <= s:
                continue
            a = float(np.log1p(r[s + 1:e + 1]).sum()); h = float(np.log1p(hr[s + 1:e + 1]).sum())
            if kind == "UP":
                up += a; upH += h
            else:
                dn += a; dnH += h
        row["zigzag"] = {"up_minus_H": up - upH, "down_minus_H": dn - dnH, "segments": len(zz)}
    return out


def main(close_path: str, fund_path: str, out_path: Optional[str] = None) -> dict:
    res = {sym: run_asset(close_path, fund_path, sym) for sym in ("BTC", "ETH")}
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    r = main(*sys.argv[1:4])
    for sym, a in r.items():
        print("==", sym, a["first"], "→", a["last"], a["days"], "days")
        for arm, v in a["arms"].items():
            line = (f"  {arm:5s} {v['total_x']:8.2f}x CAGR {v['cagr']*100:6.1f}% MDD {v['max_dd']*100:6.1f}% "
                    f"avg g {v['avg_gross']:.3f} adds {v['adds']:3d} fund {v['funding_paid']*100:5.1f}% "
                    f"segs {', '.join(f'{k} {x:+.2f}' for k, x in v['segments'].items())}")
            if arm != "H":
                ab = v["ab_vs_H"]
                line += (f"\n        ab {ab['verdict']} ratio {ab['ratio_b_over_a']:.3f} p {ab['p_b_le_a']:.3f} | won {v['segments_won']}/3 | "
                         f"rand pct {v['random_timing_pct']:.3f} | zigzag up {v['zigzag']['up_minus_H']:+.2f} down {v['zigzag']['down_minus_H']:+.2f} "
                         f"| hit {v['episode_hit_rate']} | PASSES {v['passes']}")
            print(line)
