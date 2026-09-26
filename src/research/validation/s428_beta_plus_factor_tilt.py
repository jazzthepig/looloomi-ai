"""S-428 — ② β+:在 ① 长持仓面板内按因子倾斜,基准 = 持有同一面板等权(Jazz 2026-09-26)。

问题(预先写明,S-420 教训):**不是**「因子 L/S 能不能赚绝对收益」(那是 ④,R76–R97 已问过),
而是「在只做多、满仓、不加杠杆的前提下,按因子给面板里的币加减权重,能不能稳定跑赢持有面板」。

构造:w_i = (1/N)·(1 + k·z_i),z_i = 截面排名映射到 [−1, 1]。k=1 ⇒ 权重 ∈ [0, 2/N],合计 = 1。
    —— M-129 / M-117e 失败的一个原因是倾斜太小(clip [0.5/N, 1.5/N]、α=0.04,β 0.984 R² 0.997)。
信号在 t 收盘算,t+1 收盘成交(延一天),权重随价漂移;周频(周一)或月频(1 日)再平衡;成本 10 bps × 换手。
基准:同一批合格币等权,同一再平衡日程、同一延迟、同一成本。
合格:该币已有 ≥180 天日线。面板 = causal_positioning.DEFAULT_UNIVERSE(24,当前幸存者 —— 幸存者偏差,两臂共有)。
分段:年 · BTC 在 200 日均线上/下(牛/熊代理)· 样本内 2020–2023 / 样本外 2024–2026-09。
数据:Binance 公共日线(研究读取,不落库),`/tmp/s428/binance_daily.json`。
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

PANEL = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "TRX",
         "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "UNI", "AAVE", "INJ", "FIL", "ETC", "BCH"]
START, IS_END, END = "2020-01-01", "2023-12-31", "2026-09-25"
COST = 10e-4
MIN_HIST = 180


def load(path="/tmp/s428/binance_daily.json"):
    raw = json.load(open(path))
    px, vol = {}, {}
    for s, rows in raw.items():
        idx = pd.to_datetime([r[0] for r in rows], unit="ms")
        px[s] = pd.Series([r[1] for r in rows], index=idx)
        vol[s] = pd.Series([r[2] for r in rows], index=idx)
    P = pd.DataFrame(px).sort_index()
    V = pd.DataFrame(vol).sort_index()
    return P, V


def signals(P: pd.DataFrame, V: pd.DataFrame) -> dict[str, pd.DataFrame]:
    R = P.pct_change(fill_method=None)
    lr = np.log(P).diff()
    vol28 = lr.rolling(28, min_periods=20).std()
    vol60 = lr.rolling(60, min_periods=40).std()
    mom = {n: P / P.shift(n) - 1 for n in (7, 14, 28, 56, 90, 180)}
    rk = lambda X: X.rank(axis=1, pct=True)
    out = {
        "mom7": mom[7], "mom14": mom[14], "mom28": mom[28], "mom56": mom[56],
        "mom90": mom[90], "mom180": mom[180],
        "mom28_skip7": P.shift(7) / P.shift(28) - 1,
        "mom_combo": (rk(mom[14]) + rk(mom[28]) + rk(mom[90])) / 3,
        "mom28_voladj": mom[28] / (vol28 * np.sqrt(28)),
        "low_vol60": -vol60,
        "reversal3": -(P / P.shift(3) - 1),
        "high52w": P / P.rolling(365, min_periods=180).max(),
        "volume_trend": np.log(V.rolling(7).mean() / V.rolling(60).mean()),
    }
    return out


def rebalance_days(idx: pd.DatetimeIndex, cadence: str) -> set:
    if cadence == "W":
        return set(idx[idx.dayofweek == 0])
    return set(idx[idx.day == 1])


def backtest(P, sig, cadence="W", k=1.0, mode="rank", start=START, end=END):
    """→ (tilt 日收益, 基准日收益, 年化换手 tilt, 年化换手 基准)。"""
    P = P[PANEL].loc[:end]
    R = P.pct_change(fill_method=None)
    hist = P.notna().cumsum()
    days = P.loc[start:end].index
    rebs = rebalance_days(days, cadence)
    w_t, w_b = pd.Series(0.0, index=PANEL), pd.Series(0.0, index=PANEL)
    pend = None                               # (目标 tilt, 目标 基准) —— 下一天收盘成交
    out_t, out_b, to_t, to_b = [], [], 0.0, 0.0
    for d in days:
        r = R.loc[d].fillna(0.0)
        # 当天收益用昨天收盘后的持仓
        rt = float((w_t * r).sum()); rb = float((w_b * r).sum())
        if w_t.sum() > 0:
            w_t = w_t * (1 + r) / (1 + rt)
        if w_b.sum() > 0:
            w_b = w_b * (1 + r) / (1 + rb)
        # 昨天定的目标,今天收盘成交
        if pend is not None:
            tt, tb = pend
            c_t = float((tt - w_t).abs().sum()); c_b = float((tb - w_b).abs().sum())
            rt = (1 + rt) * (1 - c_t * COST) - 1; rb = (1 + rb) * (1 - c_b * COST) - 1
            to_t += c_t; to_b += c_b
            w_t, w_b, pend = tt, tb, None
        out_t.append(rt); out_b.append(rb)
        if d in rebs or (w_b.sum() == 0):
            elig = [s for s in PANEL if hist.at[d, s] >= MIN_HIST and pd.notna(P.at[d, s])]
            x = sig.loc[d, elig].dropna() if d in sig.index else pd.Series(dtype=float)
            if len(x) < 5:
                continue
            base = pd.Series(1.0 / len(x), index=x.index)
            if mode == "rank":
                # 与前向账本同一个内核(S-429):回测里的权重就是账本那天会算出的权重
                from src.data.signals.beta_plus_momentum import tilt_targets
                tgt = tilt_targets(x, k)
            else:                                                  # top_half:前一半等权
                top = x.rank(ascending=False) <= len(x) / 2
                tgt = pd.Series(0.0, index=x.index); tgt[top] = 1.0 / top.sum()
            tgt = tgt.clip(lower=0); tgt = tgt / tgt.sum()
            pend = (tgt.reindex(PANEL).fillna(0.0), base.reindex(PANEL).fillna(0.0))
    yrs = len(days) / 365
    return (pd.Series(out_t, index=days), pd.Series(out_b, index=days), to_t / yrs, to_b / yrs)


def stats(t: pd.Series, b: pd.Series) -> dict:
    ex = t - b
    wk = ex.groupby(ex.index.to_period("W")).sum()
    cum = lambda x: float((1 + x).prod() - 1)
    return {"ann_ex": ex.mean() * 365, "te": ex.std() * np.sqrt(365),
            "ir": ex.mean() / ex.std() * np.sqrt(365) if ex.std() > 0 else np.nan,
            "t_wk": wk.mean() / wk.std() * np.sqrt(len(wk)) if wk.std() > 0 else np.nan,
            "tilt": cum(t), "bench": cum(b), "rel": (1 + cum(t)) / (1 + cum(b)) - 1,
            "hit_mo": float((ex.groupby(ex.index.to_period("M")).sum() > 0).mean())}


def run(cadences=("W", "M"), ks=(0.5, 1.0), modes=("rank",)):
    P, V = load()
    S = signals(P, V)
    btc_bull = (P["BTC"] > P["BTC"].rolling(200).mean()).shift(1)
    rows, yearly = [], {}
    for name, sig in S.items():
        for cad in cadences:
            for mode in modes:
                for k in (ks if mode == "rank" else (None,)):
                    t, b, tt, tb = backtest(P, sig, cad, k or 1.0, mode)
                    full, ins, oos = stats(t, b), stats(t[:IS_END], b[:IS_END]), stats(t[IS_END:][1:], b[IS_END:][1:])
                    bull = btc_bull.reindex(t.index).fillna(False).astype(bool)
                    sb, sr = stats(t[bull], b[bull]), stats(t[~bull], b[~bull])
                    key = f"{name}|{cad}|{mode}|k={k}"
                    rows.append({"variant": key, "ann_ex": full["ann_ex"], "ir": full["ir"], "t": full["t_wk"],
                                 "IS_ann_ex": ins["ann_ex"], "OOS_ann_ex": oos["ann_ex"], "OOS_t": oos["t_wk"],
                                 "bull_ann_ex": sb["ann_ex"], "bear_ann_ex": sr["ann_ex"],
                                 "te": full["te"], "turnover_yr": tt, "hit_mo": full["hit_mo"]})
                    ex = t - b
                    yearly[key] = (1 + t).groupby(t.index.year).prod() / (1 + b).groupby(b.index.year).prod() - 1
    df = pd.DataFrame(rows).set_index("variant")
    return df, pd.DataFrame(yearly).T


if __name__ == "__main__":
    df, yr = run(modes=("rank", "top_half"))
    pd.set_option("display.width", 250, "display.max_rows", 200)
    fmt = df.copy()
    for c in ["ann_ex", "IS_ann_ex", "OOS_ann_ex", "bull_ann_ex", "bear_ann_ex", "te"]:
        fmt[c] = (fmt[c] * 100).round(1)
    for c in ["ir", "t", "OOS_t", "turnover_yr", "hit_mo"]:
        fmt[c] = fmt[c].round(2)
    print(fmt.sort_values("ann_ex", ascending=False).to_string())
    print()
    print((yr * 100).round(1).loc[fmt.sort_values("ann_ex", ascending=False).index[:12]].to_string())
    df.to_csv("/tmp/s428/summary.csv"); yr.to_csv("/tmp/s428/yearly.csv")
