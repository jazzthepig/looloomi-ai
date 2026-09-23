"""S-409 — HL 四个高流动性币上的策略适用性(预注册见 REFUTATION_LEDGER §S-409)。

    python3 -m src.research.validation.s409_hl_majors_strategies --cache /tmp/s409

缓存目录里放 `<COIN>.json`:{"candles": HL candleSnapshot 1d, "funding": HL fundingHistory}。
缺文件时本脚本不去抓 —— 抓取是一次性的,见 `fetch()`,手动调用。

参数全部写死,不调。改参数 = 新的 S 编号。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

COINS = ["BTC", "ETH", "SOL", "HYPE"]
COST_SPOT = 12e-4        # 7bps 手续费 + 5bps 滑点,每单位换手
COST_PERP = 7.5e-4       # 4.5bps + 3bps
ASSUMED_LONG_FUNDING_ANN = 0.10   # 2023-05 之前没有 HL 资金费时的假设
REAL_FUNDING_START = pd.Timestamp("2023-05-13")


def fetch(cache: Path, coins=COINS) -> None:
    import urllib.request, urllib.error

    def post(body):
        for k in range(10):
            try:
                r = urllib.request.Request("https://api.hyperliquid.xyz/info",
                                           data=json.dumps(body).encode(),
                                           headers={"Content-Type": "application/json"})
                return json.load(urllib.request.urlopen(r, timeout=30))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(4 * (k + 1)); continue
                raise
        raise RuntimeError("429")

    cache.mkdir(parents=True, exist_ok=True)
    for c in coins:
        cs = post({"type": "candleSnapshot", "req": {"coin": c, "interval": "1d", "startTime": 0,
                                                      "endTime": int(time.time() * 1000)}})
        fr, t = [], 0
        while True:
            b = post({"type": "fundingHistory", "coin": c, "startTime": t}); time.sleep(0.35)
            if not b:
                break
            fr += b
            nt = b[-1]["time"] + 1
            if len(b) < 500 or nt <= t:
                break
            t = nt
        (cache / f"{c}.json").write_text(json.dumps({"candles": cs, "funding": fr}))


# ───────────────────────── data ─────────────────────────

def load(cache: Path):
    close, fund = {}, {}
    for c in COINS:
        d = json.loads((cache / f"{c}.json").read_text())
        s = pd.Series({pd.Timestamp(x["t"], unit="ms").normalize(): float(x["c"]) for x in d["candles"]})
        close[c] = s.sort_index()
        f = pd.DataFrame(d["funding"])
        f["d"] = pd.to_datetime(f["time"], unit="ms").dt.normalize()
        fund[c] = f.groupby("d")["fundingRate"].apply(lambda v: v.astype(float).sum())
    px = pd.DataFrame(close)
    # 最后一根是今天未收盘的 K 线 —— 丢掉
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    px = px[px.index < today]
    fd = pd.DataFrame(fund).reindex(px.index)
    for c in COINS:
        pre = fd.index < REAL_FUNDING_START
        fd.loc[pre & px[c].notna() & fd[c].isna(), c] = ASSUMED_LONG_FUNDING_ANN / 365
    return px, fd


# ───────────────────────── signals (position in [-?, ?], decided at close t) ─────────────────────────

def signals(px: pd.DataFrame, fd: pd.DataFrame) -> dict[str, pd.DataFrame]:
    r = px.pct_change()
    ma200 = px.rolling(200).mean()
    ret = {L: px / px.shift(L) - 1 for L in (3, 5, 20, 60, 120)}
    vol30 = r.rolling(30).std() * math.sqrt(365)
    defined200 = ma200.notna() & ret[60].notna()
    defined120 = ret[120].notna()

    S = {}
    S["H0_hold_spot"] = px.notna().astype(float).where(px.notna())
    S["H1_hold_perp"] = S["H0_hold_spot"].copy()
    up = (px > ma200) & (ret[60] > 0)
    dn = (px < ma200) & (ret[60] < 0)
    S["T1_trend_LF"] = up.astype(float).where(defined200)
    S["T2_trend_LS"] = (up.astype(float) - dn.astype(float)).where(defined200)
    S["T3_tsmom_LF"] = sum((ret[L] > 0).astype(float) for L in (20, 60, 120)).div(3).where(defined120)
    S["T4_tsmom_LS"] = sum(np.sign(ret[L]) for L in (20, 60, 120)).div(3).where(defined120)
    S["T5_voltgt"] = (0.5 / vol30).clip(upper=1.3).where(vol30.notna())
    S["T6_core+tsmom"] = (1 + 0.5 * S["T4_tsmom_LS"]).where(defined120)
    S["T7_core+trend"] = (1 + 0.5 * S["T2_trend_LS"]).where(defined200)

    # 横截面 K1:每周一定批次,每批持有 14 天 ⇒ 任意时刻两批重叠,每批 ±0.5
    def xs(lb: int) -> pd.DataFrame:
        pos = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        tranches = []
        for d in px.index[px.index.weekday == 0]:
            row = ret[lb].loc[d].dropna()
            if len(row) < 3:
                continue
            t = pd.Series(0.0, index=px.columns)
            t[row.idxmax()] += 0.5
            t[row.idxmin()] -= 0.5
            tranches.append((d, t))
        for d, t in tranches:
            end = d + pd.Timedelta(days=14)
            m = (pos.index >= d) & (pos.index < end)
            pos.loc[m] += t.values / 2       # 两批重叠 ⇒ 每批占一半资本
        return pos.where(px.notna())
    S["X1_xs_K1_3d"] = xs(3)
    S["X2_xs_K1_60d"] = xs(60)

    f7 = fd.loc[fd.index >= REAL_FUNDING_START].rolling(7).mean().reindex(fd.index)
    pct = f7.rolling(180, min_periods=180).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    S["F1_funding_contra"] = ((pct <= 0.2).astype(float) - (pct >= 0.8).astype(float)).where(pct.notna())
    S["R1_reversal5"] = (-np.sign(ret[5])).where(ret[5].notna())
    return S


LONG_VIA_SPOT = {"H0_hold_spot", "T1_trend_LF", "T3_tsmom_LF", "T5_voltgt", "T6_core+tsmom", "T7_core+trend"}


def pnl(name: str, pos: pd.DataFrame, px: pd.DataFrame, fd: pd.DataFrame) -> pd.DataFrame:
    """每个资产一条日收益序列。lag-1:t 日信号,t+1 收盘成交,吃 t+1→t+2 的收益。"""
    # HL 日线 t = 当天 00:00 UTC 开盘,close_d 在 d 日结束。r_d = 第 d 天内的收益。
    # t 日收盘出信号 → t+1 日收盘成交 → 吃 t+2 那天的收益 ⇒ 第 d 天持仓 = pos_{d-2}。
    r = px.pct_change()
    held = pos.shift(2)
    if name in LONG_VIA_SPOT:
        spot = held.clip(lower=0, upper=1)
        perp = held - spot
    else:
        spot = held * 0
        perp = held
    cost = spot.diff().abs() * COST_SPOT + perp.diff().abs() * COST_PERP
    funding = perp * fd                       # 第 d 天内结算的资金费;多头付正费率,空头收
    out = held * r - cost.fillna(0) - funding.fillna(0)
    return out.where(held.notna() & r.notna()), cost, funding, held


def stats(x: pd.Series) -> dict:
    x = x.dropna()
    if len(x) < 30:
        return {}
    nav = (1 + x).cumprod()
    yrs = len(x) / 365
    return {"n": len(x), "total": nav.iloc[-1] - 1, "cagr": nav.iloc[-1] ** (1 / yrs) - 1,
            "vol": x.std() * math.sqrt(365),
            "sharpe": x.mean() / x.std() * math.sqrt(365) if x.std() > 0 else float("nan"),
            "maxdd": (nav / nav.cummax() - 1).min()}


def main(cache: Path) -> None:
    px, fd = load(cache)
    S = signals(px, fd)
    books = {"BTC/ETH/SOL": ["BTC", "ETH", "SOL"], "4币(含HYPE)": COINS}
    windows = {"HL真实资金费 2023-05→": ("2023-05-14", None),
               "稳健性 2020-09→2023-05(资金费假设)": ("2020-10-01", "2023-05-13"),
               "4币窗口 2025-07→": ("2025-07-01", None)}
    btc = px["BTC"]; bull = (btc > btc.rolling(200).mean()).shift(1)
    res = {}
    for name, pos in S.items():
        net, cost, fund, held = pnl(name, pos, px, fd)
        res[name] = (net, cost, fund, held)

    for bname, cols in books.items():
        for wname, (a, b) in windows.items():
            if bname.startswith("BTC") and wname.startswith("4币"):
                continue
            if bname.startswith("4币") and not wname.startswith("4币"):
                continue
            print(f"\n══ {bname} · {wname} ══")
            print(f"{'策略':18s} {'总收益':>8s} {'CAGR':>7s} {'Sharpe':>7s} {'MaxDD':>7s} {'vs H0':>8s} "
                  f"{'平均暴露':>7s} {'成本/年':>7s} {'资金费/年':>8s} {'牛市年化':>8s} {'熊市年化':>8s}")
            h0 = None
            for name, (net, cost, fund, held) in res.items():
                sub = net[cols].loc[a:b]
                ok = sub.notna().all(axis=1)          # 所有成员都有定义的日子才计
                bk = sub[ok].mean(axis=1)
                if name == "H0_hold_spot":
                    h0 = bk
                s = stats(bk)
                if not s:
                    print(f"{name:18s}  (样本不足)"); continue
                hb = h0.reindex(bk.index).dropna() if h0 is not None else None
                vs = ((1 + bk.reindex(hb.index)).prod() - (1 + hb).prod()) if hb is not None and len(hb) else float("nan")
                yrs = len(bk) / 365
                c_y = cost[cols].loc[a:b][ok].mean(axis=1).sum() / yrs
                f_y = fund[cols].loc[a:b][ok].mean(axis=1).sum() / yrs
                expo = held[cols].loc[a:b][ok].mean(axis=1).mean()
                bl = bull.reindex(bk.index)
                bu = bk[bl == True].mean() * 365; be = bk[bl == False].mean() * 365
                print(f"{name:18s} {s['total']:8.1%} {s['cagr']:7.1%} {s['sharpe']:7.2f} {s['maxdd']:7.1%} "
                      f"{vs:8.1%} {expo:7.2f} {c_y:7.2%} {f_y:8.2%} {bu:8.1%} {be:8.1%}")

    # 分年(主窗口,3 币)
    print("\n══ 分年 Sharpe · BTC/ETH/SOL ══")
    cols = ["BTC", "ETH", "SOL"]
    yrs = range(2021, 2027)
    print(f"{'策略':18s} " + " ".join(f"{y:>7d}" for y in yrs))
    for name, (net, *_ ) in res.items():
        sub = net[cols]; ok = sub.notna().all(axis=1); bk = sub[ok].mean(axis=1)
        row = []
        for y in yrs:
            x = bk[bk.index.year == y]
            row.append(f"{(x.mean()/x.std()*math.sqrt(365)) if len(x) > 60 and x.std() > 0 else float('nan'):7.2f}")
        print(f"{name:18s} " + " ".join(row))

    # 单币(主窗口)
    print("\n══ 单币 Sharpe · HL 真实资金费窗口(HYPE 自有数据起) ══")
    print(f"{'策略':18s} " + " ".join(f"{c:>7s}" for c in COINS))
    for name, (net, *_ ) in res.items():
        row = []
        for c in COINS:
            s = stats(net[c].loc["2023-05-14":])
            row.append(f"{s.get('sharpe', float('nan')):7.2f}")
        print(f"{name:18s} " + " ".join(row))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/tmp/s409")
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        fetch(Path(a.cache))
    main(Path(a.cache))
