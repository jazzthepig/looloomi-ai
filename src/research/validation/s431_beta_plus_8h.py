"""S-431 — ② β+ 换到 8 小时 K 线:20/60/365 根(≈ 6.7 天 / 20 天 / 122 天)是否比日线 14/28/90 天 + 52 周高点更好。

Jazz 2026-09-26:「20/60/365 日 K 的验证对于 crypto 可能有点长。如果我们将周期缩短,看 20/60/365 的 8h 的 K 线呢?」

同一个问题(S-428):只做多、满仓、无杠杆,面板内倾斜 vs 持有同一面板等权,β≈1 才算 β+。
同一内核:`beta_plus_momentum.tilt_targets`(k=1 ⇒ 0~2/N)。信号在 bar 收盘算,**下一根 bar 收盘成交**,
权重随价漂移,成本 10 bps × 换手,两臂同扣,基准同日程同延迟。合格 = 已有 ≥540 根(180 天)。
再平衡三档:每根 8h / 每天(00:00 UTC 那根)/ 每周(周一 00:00)。
对照:现行日线信号(14/28/90 天 + 52 周高点)在 8h 网格上按等价根数重算(42/84/270/1095 根)。
数据:Binance 公共 8h K 线(研究读取,不落库),`/tmp/s428/binance_8h.json`。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.data.signals.beta_plus_momentum import tilt_targets
from src.research.validation.s428_beta_plus_factor_tilt import PANEL

BARS_PER_DAY = 3
BPY = 365 * BARS_PER_DAY
COST = 10e-4
MIN_HIST = 180 * BARS_PER_DAY
START, IS_END = "2020-01-01", "2023-12-31"


def load(path="/tmp/s428/binance_8h.json") -> pd.DataFrame:
    raw = json.load(open(path))
    P = pd.DataFrame({s: pd.Series([r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows], unit="ms"))
                      for s, rows in raw.items()}).sort_index()
    # 日历化到 8h 网格:缺的 bar = NaN(S-429 教训:按根数 shift 前必须补日历)
    P = P.reindex(pd.date_range(P.index.min(), P.index.max(), freq="8h"))
    return P[[s for s in PANEL if s in P.columns]]


def signals(P: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rk = lambda X: X.rank(axis=1, pct=True)
    F = P.ffill()
    mom = lambda n: F / F.shift(n) - 1
    high = lambda n, m: F / F.rolling(n, min_periods=m).max()
    m20, m60, m365 = mom(20), mom(60), mom(365)
    combo8 = (rk(m20) + rk(m60) + rk(m365)) / 3
    high365 = high(365, 180)
    daily_combo = (rk(mom(42)) + rk(mom(84)) + rk(mom(270))) / 3
    return {
        "8h_mom20": m20, "8h_mom60": m60, "8h_mom365": m365,
        "8h_combo20/60/365": combo8,
        "8h_high365": high365,
        "8h_combo+high365": (rk(combo8) + rk(high365)) / 2,
        "8h_combo+52w": (rk(combo8) + rk(high(1095, 540))) / 2,
        "INCUMBENT_daily14/28/90+52w": (rk(daily_combo) + rk(high(1095, 540))) / 2,
    }


def _is_rebalance(ts: pd.Timestamp, cadence: str) -> bool:
    if cadence == "8h":
        return True
    if cadence == "D":
        return ts.hour == 0
    return ts.hour == 0 and ts.dayofweek == 0


def backtest(P: pd.DataFrame, sig: pd.DataFrame, cadence: str, k: float = 1.0):
    P = P.loc[START:]
    sig = sig.reindex(P.index)
    R = (P.ffill() / P.ffill().shift(1) - 1).fillna(0.0).to_numpy()
    avail = P.notna().to_numpy()
    hist = pd.DataFrame(avail, index=P.index).cumsum().to_numpy()
    S = sig.to_numpy()
    cols = list(P.columns)
    n = len(cols)
    w_t = np.zeros(n); w_b = np.zeros(n)
    pend = None
    out_t = np.zeros(len(P)); out_b = np.zeros(len(P)); to_t = to_b = 0.0
    for i, ts in enumerate(P.index):
        r = R[i]
        rt = float(w_t @ r); rb = float(w_b @ r)
        if w_t.sum() > 0:
            w_t = w_t * (1 + r) / (1 + rt)
        if w_b.sum() > 0:
            w_b = w_b * (1 + r) / (1 + rb)
        if pend is not None:
            tt, tb = pend
            ct = np.abs(tt - w_t).sum(); cb = np.abs(tb - w_b).sum()
            rt = (1 + rt) * (1 - ct * COST) - 1; rb = (1 + rb) * (1 - cb * COST) - 1
            to_t += ct; to_b += cb
            w_t, w_b, pend = tt, tb, None
        out_t[i] = rt; out_b[i] = rb
        if _is_rebalance(ts, cadence) or w_b.sum() == 0:
            elig = [j for j in range(n) if hist[i, j] >= MIN_HIST and avail[i, j] and not np.isnan(S[i, j])]
            if len(elig) < 5:
                continue
            x = pd.Series(S[i, elig], index=elig)
            tgt = tilt_targets(x, k)
            tt = np.zeros(n); tt[list(tgt.index)] = tgt.values
            tb = np.zeros(n); tb[elig] = 1.0 / len(elig)
            pend = (tt, tb)
    yrs = len(P) / BPY
    return pd.Series(out_t, index=P.index), pd.Series(out_b, index=P.index), to_t / yrs, to_b / yrs


def stats(t: pd.Series, b: pd.Series) -> dict:
    ex = t - b
    wk = ex.groupby(ex.index.to_period("W")).sum()
    tc, bc = float((1 + t).prod() - 1), float((1 + b).prod() - 1)
    rel = (1 + t).cumprod() / (1 + b).cumprod()
    daily_rel = rel.resample("1D").last()
    r12 = (daily_rel / daily_rel.shift(365) - 1).dropna()
    return {"ann_ex": ex.mean() * BPY, "t_wk": wk.mean() / wk.std() * np.sqrt(len(wk)),
            "beta": float(np.cov(t, b)[0, 1] / np.var(b)), "rel_maxdd": float((rel / rel.cummax() - 1).min()),
            "worst_12m": float(r12.min()) if len(r12) else np.nan}


def run():
    P = load()
    S = signals(P)
    btc_d = P["BTC"].ffill().resample("1D").last()
    bull_d = (btc_d > btc_d.rolling(200).mean()).shift(1)
    rows, years = [], {}
    for name, sig in S.items():
        for cad in ("8h", "D", "W"):
            t, b, tt, tb = backtest(P, sig, cad)
            bull = bull_d.reindex(t.index, method="ffill").fillna(False).astype(bool)
            f, i_, o = stats(t, b), stats(t[:IS_END], b[:IS_END]), stats(t["2024-01-01":], b["2024-01-01":])
            key = f"{name}|{cad}"
            rows.append({"variant": key, "ann_ex": f["ann_ex"], "t": f["t_wk"], "IS": i_["ann_ex"],
                         "OOS": o["ann_ex"], "OOS_t": o["t_wk"],
                         "bull": stats(t[bull], b[bull])["ann_ex"], "bear": stats(t[~bull], b[~bull])["ann_ex"],
                         "beta": f["beta"], "rel_maxdd": f["rel_maxdd"], "worst_12m": f["worst_12m"], "turnover": tt})
            years[key] = (1 + t).groupby(t.index.year).prod() / (1 + b).groupby(b.index.year).prod() - 1
    return pd.DataFrame(rows).set_index("variant"), pd.DataFrame(years).T


if __name__ == "__main__":
    df, yr = run()
    pct = ["ann_ex", "IS", "OOS", "bull", "bear", "rel_maxdd", "worst_12m"]
    out = df.copy()
    out[pct] = (out[pct] * 100).round(1)
    out[["t", "OOS_t", "beta", "turnover"]] = out[["t", "OOS_t", "beta", "turnover"]].round(2)
    pd.set_option("display.width", 250)
    print(out.sort_values("ann_ex", ascending=False).to_string())
    print()
    print((yr * 100).round(1).to_string())
    df.to_csv("/tmp/s428/s431_summary.csv"); yr.to_csv("/tmp/s428/s431_yearly.csv")
