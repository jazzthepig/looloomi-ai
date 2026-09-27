"""S-432 — 强势标的的回撤入场:短期技术位置直接介入胜率低;强势标的 2 天内回撤完毕、在支撑处形成反弹 —— 等一等能否增厚?

Jazz 2026-09-26。定位:② β+ 的**执行时点层**,不改目标权重(β 不变),只决定每一笔加仓在 2 天内何时成交。
价值 = 成交价相对「立即成交」的改善 − 等待中错过的涨幅。等待中的资金留在面板里(与账本一致)。

事件(每天 00:00 UTC 那根 8h bar 收盘时):
    E1  信号前 1/3 的币(所有买入意图)
    E2  当天**新进入**前 1/3 的币(「进入观察」)
    S   信号后 1/3 的币(卖出意图,镜像)
信号 = 现行 β+ 信号在 8h 网格上的等价根数(动量 42/84/270 根 + 1095 根高点),截面排名只在合格币之间。

情景(全部对照「下一根 8h 收盘立即成交」,统一在 t+H 结算,H = 15 根(5 天)与 42 根(14 天)):
    R1  Jazz 规则:仅当延伸(收盘 > SMA20 + x·ATR14)才等;从信号后最高点回撤 ≥ d·ATR 后,出现 8h 收盘 > 前一根最高 ⇒ 成交;
        收盘跌破 SMA20(支撑)⇒ 取消(资金留在面板);T 根未成交 ⇒ 时间止损按收盘成交。网格 x∈{2,3} d∈{0.75,1.25} T∈{6,9}
    R2  纯限价:信号价 − d·ATR 挂单,触及即成交(跳空按开盘),6 根未成交 ⇒ 收盘成交。d∈{0.75,1.25}
    R3  纯延迟:1 天 / 2 天后收盘成交(对照:改善是否只是时间漂移)
    R4  Jazz 规则去掉延伸门槛(所有强势事件都等回撤)
    R5  Jazz 规则用在**所有**合格币上(不只强势)—— 检验「强势」这个条件是否必要
    R6  一半立即、一半按 R1 默认格(x=2 d=0.75 T=6)
    S1  卖出镜像:仅当超卖(收盘 < SMA20 − x·ATR)才等;从最低点反弹 ≥ d·ATR 后出现 8h 收盘 < 前一根最低 ⇒ 卖出;
        收盘站回 SMA20 ⇒ 取消卖出(继续持有到 t+H);T 根 ⇒ 时间止损。
统计:每事件改善(bps),按周聚类的 t;成交/取消/时间止损占比;牛熊(BTC 日线 200 日均线)、样本内(<2024)/外、分年。
数据:Binance 公共 8h K 线(研究读取,不落库),`/tmp/s428/8hohlc/`。
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np
import pandas as pd

from src.research.validation.s428_beta_plus_factor_tilt import PANEL

START = "2020-07-01"
MIN_HIST = 540


def load(dir_="/tmp/s428/8hohlc"):
    frames = {}
    for f in sorted(glob.glob(os.path.join(dir_, "*.json"))):
        s = os.path.basename(f)[:-5]
        rows = json.load(open(f))
        idx = pd.to_datetime([r[0] for r in rows], unit="ms")
        frames[s] = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c"], index=idx).drop(columns="t")
    cal = pd.date_range(min(f.index.min() for f in frames.values()),
                        max(f.index.max() for f in frames.values()), freq="8h")
    syms = [s for s in PANEL if s in frames]
    get = lambda k: pd.DataFrame({s: frames[s][k] for s in syms}).reindex(cal)
    return get("o"), get("h"), get("l"), get("c")


def features(O, H, L, C):
    Cf = C.ffill()
    prev = Cf.shift(1)
    tr = pd.concat([(H - L), (H - prev).abs(), (L - prev).abs()]).groupby(level=0).max()
    tr = tr.reindex(C.index)
    atr = tr.rolling(14, min_periods=10).mean()
    sma = Cf.rolling(20, min_periods=15).mean()
    rk = lambda X: X.rank(axis=1, pct=True)
    mom = lambda n: Cf / Cf.shift(n) - 1
    combo = (rk(mom(42)) + rk(mom(84)) + rk(mom(270))) / 3
    high = Cf / Cf.rolling(1095, min_periods=540).max()
    sig = (rk(combo) + rk(high)) / 2
    hist = C.notna().cumsum()
    r = (Cf / prev - 1)
    elig = (hist >= MIN_HIST) & C.notna()
    panel_r = r.where(elig).mean(axis=1).fillna(0.0)
    PL = np.log1p(panel_r).cumsum()
    return atr, sma, sig.where(elig), PL


def events(sig: pd.DataFrame):
    """→ dict[名称] = [(bar_idx, col_idx), ...],只取 00:00 UTC 的 bar,START 之后。"""
    idx = sig.index
    sel = np.where((idx.hour == 0) & (idx >= pd.Timestamp(START)))[0]
    S = sig.to_numpy()
    out = {"E1": [], "E2": [], "S": [], "ALL": []}
    prev_top = set()
    for i in sel:
        row = S[i]
        ok = ~np.isnan(row)
        if ok.sum() < 9:
            continue
        ranks = pd.Series(row[ok]).rank(pct=True).to_numpy()
        cols = np.where(ok)[0]
        top = set(cols[ranks > 2 / 3]); bot = set(cols[ranks <= 1 / 3])
        out["E1"] += [(i, j) for j in top]
        out["E2"] += [(i, j) for j in top - prev_top]
        out["S"] += [(i, j) for j in bot]
        out["ALL"] += [(i, j) for j in cols]
        prev_top = top
    return out


def _buy_rule(i, j, arr, gate_x, d, T, always=False):
    """→ (fill_bar | None, fill_price | None, 状态)。状态 ∈ immediate / filled / timestop / cancel。"""
    O, H, L, C, ATR, SMA = arr
    c0, a0, s0 = C[i, j], ATR[i, j], SMA[i, j]
    if np.isnan(c0) or np.isnan(a0) or np.isnan(s0):
        return i + 1, C[i + 1, j], "immediate"
    extended = c0 > s0 + gate_x * a0
    if not (extended or always):
        return i + 1, C[i + 1, j], "immediate"
    hmax, pulled = H[i, j], False
    for k in range(i + 1, i + T + 1):
        if np.isnan(C[k, j]):
            continue
        hmax = max(hmax, H[k, j])
        if C[k, j] < s0:
            return None, None, "cancel"
        if L[k, j] <= hmax - d * a0:
            pulled = True
        if pulled and C[k, j] > H[k - 1, j]:
            return k, C[k, j], "filled"
    return i + T, C[i + T, j], "timestop"


def _sell_rule(i, j, arr, gate_x, d, T):
    O, H, L, C, ATR, SMA = arr
    c0, a0, s0 = C[i, j], ATR[i, j], SMA[i, j]
    if np.isnan(c0) or np.isnan(a0) or np.isnan(s0) or not (c0 < s0 - gate_x * a0):
        return i + 1, C[i + 1, j], "immediate"
    lmin, bounced = L[i, j], False
    for k in range(i + 1, i + T + 1):
        if np.isnan(C[k, j]):
            continue
        lmin = min(lmin, L[k, j])
        if C[k, j] > s0:
            return None, None, "cancel"
        if H[k, j] >= lmin + d * a0:
            bounced = True
        if bounced and C[k, j] < L[k - 1, j]:
            return k, C[k, j], "filled"
    return i + T, C[i + T, j], "timestop"


def simulate(evts, arr, PL, rule, H_bars, side="buy"):
    """→ DataFrame:每事件的改善(对立即成交,log 收益差)与状态。"""
    O, Hh, L, C, ATR, SMA = arr
    n = C.shape[0]
    rows = []
    for i, j in evts:
        e = i + H_bars
        if e >= n or i + 1 >= n or np.isnan(C[i + 1, j]) or np.isnan(C[e, j]):
            continue
        # 立即成交基准
        if side == "buy":
            r_imm = (PL[i + 1] - PL[i]) + np.log(C[e, j] / C[i + 1, j])
        else:
            r_imm = np.log(C[i + 1, j] / C[i, j]) + (PL[e] - PL[i + 1])
        f, p, st = rule(i, j)
        if side == "buy":
            r = (PL[e] - PL[i]) if f is None else (PL[f] - PL[i]) + np.log(C[e, j] / p)
        else:
            r = np.log(C[e, j] / C[i, j]) if f is None else np.log(p / C[i, j]) + (PL[e] - PL[f])
        rows.append((i, r - r_imm, st))
    return pd.DataFrame(rows, columns=["bar", "impr", "state"])


def summarize(df, idx, bull):
    if df.empty:
        return {}
    ts = idx[df["bar"].to_numpy()]
    s = pd.Series(df["impr"].to_numpy(), index=ts)
    wk = s.groupby(s.index.to_period("W")).mean()
    b = bull.reindex(ts, method="ffill").fillna(False).astype(bool).to_numpy()
    oos = ts >= pd.Timestamp("2024-01-01")
    st = df["state"].value_counts(normalize=True)
    return {"n": len(df), "bps": s.mean() * 1e4, "t_wk": wk.mean() / wk.std() * np.sqrt(len(wk)),
            "win": float((s > 0).mean()), "bps_IS": s[~oos].mean() * 1e4, "bps_OOS": s[oos].mean() * 1e4,
            "bps_bull": s[b].mean() * 1e4, "bps_bear": s[~b].mean() * 1e4,
            "waited": 1 - st.get("immediate", 0.0), "filled": st.get("filled", 0.0),
            "timestop": st.get("timestop", 0.0), "cancel": st.get("cancel", 0.0)}


def run(H_list=(15, 42)):
    O, H, L, C = load()
    atr, sma, sig, PL = features(O, H, L, C)
    arr = tuple(x.to_numpy() for x in (O, H, L, C, atr, sma))
    PLa = PL.to_numpy()
    ev = events(sig)
    btc = C["BTC"].ffill().resample("1D").last()
    bull = (btc > btc.rolling(200).mean()).shift(1)
    scen = []
    for x in (2, 3):
        for d in (0.75, 1.25):
            for T in (6, 9):
                scen.append((f"R1 Jazz x={x} d={d} T={T}", "E1", "buy",
                             lambda i, j, x=x, d=d, T=T: _buy_rule(i, j, arr, x, d, T)))
                scen.append((f"R1 Jazz x={x} d={d} T={T}", "E2", "buy",
                             lambda i, j, x=x, d=d, T=T: _buy_rule(i, j, arr, x, d, T)))
    for d in (0.75, 1.25):
        def lim(i, j, d=d):
            c0, a0 = arr[3][i, j], arr[4][i, j]
            if np.isnan(a0):
                return i + 1, arr[3][i + 1, j], "immediate"
            lp = c0 - d * a0
            for k in range(i + 1, i + 7):
                if arr[2][k, j] <= lp:
                    return k, min(arr[0][k, j], lp), "filled"
            return i + 6, arr[3][i + 6, j], "timestop"
        scen.append((f"R2 limit d={d}", "E1", "buy", lim))
        scen.append((f"R2 limit d={d}", "E2", "buy", lim))
    for lag in (3, 6):
        scen.append((f"R3 delay {lag // 3}d", "E1", "buy", lambda i, j, lag=lag: (i + lag, arr[3][i + lag, j], "timestop")))
    scen.append(("R4 Jazz no-gate d=0.75 T=6", "E1", "buy", lambda i, j: _buy_rule(i, j, arr, 2, 0.75, 6, always=True)))
    scen.append(("R4 Jazz no-gate d=0.75 T=6", "E2", "buy", lambda i, j: _buy_rule(i, j, arr, 2, 0.75, 6, always=True)))
    scen.append(("R5 Jazz on ALL coins x=2 d=0.75 T=6", "ALL", "buy", lambda i, j: _buy_rule(i, j, arr, 2, 0.75, 6)))
    for x in (2, 3):
        for d in (0.75, 1.25):
            scen.append((f"S1 sell-bounce x={x} d={d} T=6", "S", "sell",
                         lambda i, j, x=x, d=d: _sell_rule(i, j, arr, x, d, 6)))
    out = []
    for Hb in H_list:
        for name, evset, side, rule in scen:
            df = simulate(ev[evset], arr, PLa, rule, Hb, side)
            out.append({"scenario": name, "events": evset, "H": f"{Hb // 3}d", **summarize(df, C.index, bull)})
            if name.startswith("R1 Jazz x=2 d=0.75 T=6") and evset == "E1":
                half = df.copy(); half["impr"] = half["impr"] / 2
                out.append({"scenario": "R6 half now / half R1", "events": "E1", "H": f"{Hb // 3}d",
                            **summarize(half, C.index, bull)})
    return pd.DataFrame(out), {k: len(v) for k, v in ev.items()}


if __name__ == "__main__":
    res, counts = run()
    print("events:", counts)
    pd.set_option("display.width", 260, "display.max_rows", 200)
    r = res.copy()
    for c in ["bps", "bps_IS", "bps_OOS", "bps_bull", "bps_bear"]:
        r[c] = r[c].round(1)
    for c in ["t_wk", "win", "waited", "filled", "timestop", "cancel"]:
        r[c] = r[c].round(2)
    print(r.to_string(index=False))
    res.to_csv("/tmp/s428/s432_results.csv", index=False)


# ── S-432b 追加情景:限价单为什么有效(不要确认)────────────────────────────────

def _limit(i, j, arr, d, T=6, gate_x=None, cancel_below_sma=False):
    O, H, L, C, ATR, SMA = arr
    c0, a0, s0 = C[i, j], ATR[i, j], SMA[i, j]
    if np.isnan(a0) or (gate_x is not None and not (c0 > s0 + gate_x * a0)):
        return i + 1, C[i + 1, j], "immediate"
    lp = c0 - d * a0
    for k in range(i + 1, i + T + 1):
        if np.isnan(C[k, j]):
            continue
        if L[k, j] <= lp:
            return k, min(O[k, j], lp), "filled"
        if cancel_below_sma and C[k, j] < s0:
            return None, None, "cancel"
    return i + T, C[i + T, j], "timestop"


def run_extra(Hb=15):
    O, H, L, C = load()
    atr, sma, sig, PL = features(O, H, L, C)
    arr = tuple(x.to_numpy() for x in (O, H, L, C, atr, sma))
    PLa = PL.to_numpy()
    ev = events(sig)
    btc = C["BTC"].ffill().resample("1D").last()
    bull = (btc > btc.rolling(200).mean()).shift(1)
    scen = [
        ("R2 limit d=0.5", "E1", lambda i, j: _limit(i, j, arr, 0.5)),
        ("R2 limit d=0.75", "E1", lambda i, j: _limit(i, j, arr, 0.75)),
        ("R2 limit d=0.75 T=3", "E1", lambda i, j: _limit(i, j, arr, 0.75, T=3)),
        ("R7 limit only-if-stretched x=2 d=0.75", "E1", lambda i, j: _limit(i, j, arr, 0.75, gate_x=2)),
        ("R9 limit + cancel below SMA20 d=0.75", "E1", lambda i, j: _limit(i, j, arr, 0.75, cancel_below_sma=True)),
        ("R2 limit d=0.75 on ALL coins", "ALL", lambda i, j: _limit(i, j, arr, 0.75)),
    ]
    out, dfs = [], {}
    for name, es, rule in scen:
        df = simulate(ev[es], arr, PLa, rule, Hb, "buy")
        dfs[name] = df
        out.append({"scenario": name, "events": es, **summarize(df, C.index, bull)})
    # R8 分拆:一半 −0.5 ATR,一半 −1.0 ATR
    a = simulate(ev["E1"], arr, PLa, lambda i, j: _limit(i, j, arr, 0.5), Hb)
    b = simulate(ev["E1"], arr, PLa, lambda i, j: _limit(i, j, arr, 1.0), Hb)
    lad = a.copy(); lad["impr"] = (a["impr"].to_numpy() + b["impr"].to_numpy()) / 2
    out.append({"scenario": "R8 ladder 1/2 @−0.5 + 1/2 @−1.0 ATR", "events": "E1", **summarize(lad, C.index, bull)})
    best = dfs["R2 limit d=0.75"]
    yr = pd.Series(best["impr"].to_numpy(), index=C.index[best["bar"].to_numpy()]).groupby(lambda t: t.year).mean() * 1e4
    return pd.DataFrame(out), yr


# S-432c(已在会话中跑过,结论写入台账):限价单要求「穿价 0.1 ATR」才算成交 ⇒ R2 d=0.75 从 +9.3 bps(t 2.02)
# 翻为 −12.9 bps(t −2.50)。触价即成交的假设把「刚好在限价处反弹」的最好那部分算成了成交 —— 现实里排队不一定成交,
# 而真正成交的往往是继续下跌的那些(逆向选择)。限价单的正值是撮合假设的产物,不是可执行的优势。
