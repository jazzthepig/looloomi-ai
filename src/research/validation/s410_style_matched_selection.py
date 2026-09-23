"""S-410 — 风格匹配选策略,对比静态 T3(预注册见 REFUTATION_LEDGER §S-410)。

    python3 -m src.research.validation.s410_style_matched_selection --cache /tmp/s409

复用 S-409 的数据加载、信号和成本口径;不新增策略、不调参。
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation import s409_hl_majors_strategies as s409

COLS = ["BTC", "ETH", "SOL"]
CANDIDATES = ["CASH", "H0_hold_spot", "T1_trend_LF", "T3_tsmom_LF", "P1_tsmomLS_spotlong"]
DEFAULT = "T3_tsmom_LF"
HORIZON = 14
K = 40
MIN_MATCH = 20
EVAL_START = pd.Timestamp("2022-01-01")


def composite_pnl(pos: pd.DataFrame, px: pd.DataFrame, fd: pd.DataFrame) -> pd.Series:
    """统一工具口径:多头走现货(≤1),其余走永续。三币等权。"""
    r = px[COLS].pct_change()
    held = pos[COLS].shift(2)
    spot = held.clip(lower=0, upper=1)
    perp = held - spot
    cost = spot.diff().abs() * s409.COST_SPOT + perp.diff().abs() * s409.COST_PERP
    fund = perp * fd[COLS]
    net = held * r - cost.fillna(0) - fund.fillna(0)
    return net.where(held.notna() & r.notna()).mean(axis=1, skipna=False)


def main(cache: Path) -> None:
    px, fd = s409.load(cache)
    S = s409.signals(px, fd)
    sig = {
        "CASH": S["H0_hold_spot"] * 0,
        "H0_hold_spot": S["H0_hold_spot"],
        "T1_trend_LF": S["T1_trend_LF"],
        "T3_tsmom_LF": S["T3_tsmom_LF"],
        "P1_tsmomLS_spotlong": S["T4_tsmom_LS"],
    }
    book = {k: composite_pnl(v, px, fd) for k, v in sig.items()}
    B = pd.DataFrame(book).dropna()
    idx = B.index

    # 前向 14 天净收益:t 日决策 → 第 t+2 … t+15 天的 sleeve 日收益(pnl 里已含 lag)
    fwd = pd.DataFrame({k: B[k].rolling(HORIZON).sum().shift(-(HORIZON + 1)) for k in CANDIDATES})

    # 风格状态
    btc = px["BTC"]
    feat = pd.DataFrame({
        "btc_ma200": btc / btc.rolling(200).mean() - 1,
        "ret60": (px[COLS] / px[COLS].shift(60) - 1).mean(axis=1),
        "vol30": B["H0_hold_spot"].rolling(30).std() * math.sqrt(365),
        "btc_dd200": btc / btc.rolling(200).max() - 1,
    }).reindex(idx)
    z = (feat - feat.expanding(60).mean()) / feat.expanding(60).std()

    trend = np.where((feat.btc_ma200 > 0) & (feat.ret60 > 0), "up",
                     np.where((feat.btc_ma200 < 0) & (feat.ret60 < 0), "down", "mixed"))
    volhi = feat.vol30 > feat.vol30.expanding(60).median()
    cell = pd.Series([f"{t}|{'volhi' if v else 'vollo'}" for t, v in zip(trend, volhi)], index=idx)

    choice = {"M1_cells": pd.Series(index=idx, dtype=object),
              "M2_knn": pd.Series(index=idx, dtype=object)}
    last = {m: DEFAULT for m in choice}
    for i, t in enumerate(idx):
        if t < EVAL_START:
            continue
        if (t - EVAL_START).days % 7 == 0:
            known = idx[(idx <= t - pd.Timedelta(days=HORIZON + 1))]
            known = known[fwd.loc[known].notna().all(axis=1).values]
            # M1
            same = known[(cell.loc[known] == cell.loc[t]).values]
            last["M1_cells"] = (fwd.loc[same].mean().idxmax() if len(same) >= MIN_MATCH else DEFAULT)
            # M2
            zk = z.loc[known].dropna()
            if z.loc[t].notna().all() and len(zk) >= MIN_MATCH:
                d = np.sqrt(((zk - z.loc[t]) ** 2).sum(axis=1))
                nn = d.nsmallest(K).index
                last["M2_knn"] = fwd.loc[nn].mean().idxmax()
            else:
                last["M2_knn"] = DEFAULT
        for m in choice:
            choice[m].loc[t] = last[m]

    res = {}
    for m, ch in choice.items():
        ch = ch.dropna()
        pos = pd.DataFrame(np.nan, index=px.index, columns=COLS)
        for name in CANDIDATES:
            days = ch.index[ch == name]
            pos.loc[days, COLS] = sig[name].loc[days, COLS].values
        res[m] = composite_pnl(pos, px, fd).loc[EVAL_START:]
        print(f"\n{m} 选择频率:", ch.value_counts(normalize=True).round(2).to_dict())
    for k in ["T3_tsmom_LF", "H0_hold_spot", "T1_trend_LF", "P1_tsmomLS_spotlong"]:
        res[k] = B[k].loc[EVAL_START:]

    print(f"\n══ BTC/ETH/SOL · {EVAL_START.date()} → 今 ══")
    print(f"{'':22s} {'总收益':>8s} {'Sharpe':>7s} {'MaxDD':>7s}   " + " ".join(f"{y:>6d}" for y in range(2022, 2027)))
    for k, x in res.items():
        x = x.dropna()
        s = s409.stats(x)
        yrs = []
        for y in range(2022, 2027):
            xy = x[x.index.year == y]
            yrs.append(f"{xy.mean() / xy.std() * math.sqrt(365):6.2f}" if len(xy) > 60 else "   nan")
        print(f"{k:22s} {s['total']:8.1%} {s['sharpe']:7.2f} {s['maxdd']:7.1%}   " + " ".join(yrs))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/s409")
    main(Path(ap.parse_args().cache))
