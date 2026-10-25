"""S-679(台账 2026-10-23 16:16 UTC):X1V 的两种快回场 —— Seth 的那一份(G1 NASDAQ、G2 Binance;G3 World50 个股交 A 道 T-190)。

A 道 T-190 另做一份完整实现(三组),两份对照。规则照台账一字不改:
  B  = X1V = tom.trade_path(close, "rally", 0.0, exit_mode="l20", vol=True)
  V1 = 反弹仓去掉 +15% 止盈(只在收盘 < 前 10 日最低时出,或转多头)
  V2 = 多头进场改成「收盘 > 前 55 日最高收盘」(不要求在 200 日线上)
参数化重写 trade_path(本文件 `path`),先在每条序列上证明 B 与 `tom.trade_path` 逐日一致,不一致就停。
收益 = tom.trade_returns(close, g)(>1 的部分按 10% 年化付资金费、|Δg| × 10bp、现金 0);净值从第 201 天起。
熊市段 = crash_atlas_common.bear_episodes(股票 / 指数 0.20、加密 0.50),前高在第 201 天之后才算;
修复 = 谷底 → +120 天、下跌 = 前高 → 谷底(phase_returns,套在各自净值上)。
用法:python3 docs/research/s679_reentry_seth.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import json
import os
import statistics
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import crash_atlas_common as ca  # noqa: E402
from src.data.signals import tom  # noqa: E402

ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
S601_SEEN = {"XRP", "BNB", "LTC", "BCH", "ADA", "LINK", "DOGE", "XLM", "TRX", "ETC", "XMR", "ATOM"}
S601_CUT = "2019-05-31"


def path(close: pd.Series, rally_tp: float | None = tom.RALLY_TP, entry: str = "ma20") -> pd.Series:
    """tom.trade_path(bear="rally", short_size=0, exit_mode="l20", vol=True) 的参数化重写。
    rally_tp=None ⇒ 反弹仓不止盈(V1);entry="h55" ⇒ 多头进场 = 收盘 > 前 55 日最高收盘(V2)。"""
    s = close.dropna().astype(float)
    c, n = s.to_numpy(), len(s)
    g = np.ones(n)
    mode, k, last_add, ent = "long", 0, None, None
    for t in range(tom.WARM, n):
        x = c[t]
        ma = c[t - tom.MA_N + 1:t + 1].mean()
        h20, l20, h55, l10 = c[t - 20:t].max(), c[t - 20:t].min(), c[t - 55:t].max(), c[t - 10:t].min()
        long_entry = (x > ma and x > h20) if entry == "ma20" else (x > h55)
        if mode == "long":
            if x < l20:
                mode, k, last_add = "flat", 0, None
                g[t] = 0.0
                continue
            if k > 0 and x < l20:
                k, last_add = 0, None
            elif k == 0 and x > h55 and 1 + tom.UNIT <= tom.CAP + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * tom.STEP and 1 + tom.UNIT * (k + 1) <= tom.CAP + 1e-9:
                k, last_add = k + 1, x
            if x < ma and x < l20:
                k, last_add = 0, None
                mode, ent = "flat", None
        elif mode == "flat":
            if long_entry:
                mode, k = "long", 0
            elif x > h20:
                mode, ent = "rally", x
        elif mode == "rally":
            if long_entry:
                mode, k = "long", 0
            elif (rally_tp is not None and x >= ent * rally_tp) or x < l10:
                mode = "flat"
        g[t] = {"long": 1 + tom.UNIT * k, "flat": 0.0, "rally": tom.RALLY_SIZE}[mode]
    out = pd.Series(g, index=s.index)
    vs = tom.vol_scale(s)
    return out.where(np.arange(n) < tom.WARM, out * vs)


def nav_of(close: pd.Series, g: pd.Series) -> pd.Series:
    r = tom.trade_returns(close, g)
    r = r.iloc[tom.WARM - 1:]                    # 第 201 天起
    return (1 + r).cumprod()


def stats(nav: pd.Series) -> dict:
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    ann = nav.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else None
    mdd = float((nav / nav.cummax() - 1).min())
    return {"ann": ann, "mdd": mdd, "calmar": (ann / abs(mdd)) if ann is not None and mdd < 0 else None}


ARMS = {"B": dict(rally_tp=tom.RALLY_TP, entry="ma20"), "V1": dict(rally_tp=None, entry="ma20"),
        "V2": dict(rally_tp=tom.RALLY_TP, entry="h55")}


def run_asset(close: pd.Series, thr: float) -> dict:
    close = close.dropna().astype(float)
    ref = tom.trade_path(close, "rally", 0.0, exit_mode="l20", vol=True)
    gs = {a: path(close, **kw) for a, kw in ARMS.items()}
    if not np.allclose(ref.to_numpy(), gs["B"].to_numpy(), atol=1e-12):
        raise SystemExit(f"B 与 tom.trade_path 不一致:{int((~np.isclose(ref, gs['B'])).sum())} 天")
    navs = {a: nav_of(close, g) for a, g in gs.items()}
    hold = close.iloc[tom.WARM - 1:] / close.iloc[tom.WARM - 1]
    start = close.index[tom.WARM]
    eps = [e for e in ca.bear_episodes(close, thr) if e["peak_d"] >= start]
    rows = []
    for e in eps:
        ph = {a: ca.phase_returns(n, e) for a, n in navs.items()}
        ph["H"] = ca.phase_returns(hold, e)
        rows.append({"peak": e["peak_d"].date().isoformat(), "trough": e["trough_d"].date().isoformat(), **{
            a: {"crash": p["crash"], "recovery": p["recovery"]} for a, p in ph.items()}})
    return {"stats": {a: stats(n) for a, n in navs.items()} | {"H": stats(hold)}, "episodes": rows,
            "avg_exposure": {a: float(g.iloc[tom.WARM:].mean()) for a, g in gs.items()},
            "switches": {a: int((g.iloc[tom.WARM:].diff().abs() > 1e-9).sum()) for a, g in gs.items()}}


def judge(assets: dict[str, dict]) -> dict:
    out = {}
    for v in ("V1", "V2"):
        rec = [ep[v]["recovery"] - ep["B"]["recovery"] for a in assets.values() for ep in a["episodes"]
               if ep[v]["recovery"] is not None and ep["B"]["recovery"] is not None]
        crash = [ep[v]["crash"] - ep["B"]["crash"] for a in assets.values() for ep in a["episodes"]
                 if ep[v]["crash"] is not None and ep["B"]["crash"] is not None]
        cal = [a["stats"][v]["calmar"] - a["stats"]["B"]["calmar"] for a in assets.values()
               if a["stats"][v]["calmar"] is not None and a["stats"]["B"]["calmar"] is not None]
        m_rec = statistics.median(rec) if rec else None
        m_crash = statistics.median(crash) if crash else None
        m_cal = statistics.median(cal) if cal else None
        ok = (m_rec is not None and m_rec >= 0.10) and (m_crash is not None and m_crash >= -0.05) and \
             (m_cal is not None and m_cal > 0)
        cap_share = [ep[v]["recovery"] / ep["H"]["recovery"] for a in assets.values() for ep in a["episodes"]
                     if ep[v]["recovery"] is not None and ep["H"]["recovery"] not in (None, 0)]
        cap_b = [ep["B"]["recovery"] / ep["H"]["recovery"] for a in assets.values() for ep in a["episodes"]
                 if ep["B"]["recovery"] is not None and ep["H"]["recovery"] not in (None, 0)]
        out[v] = {"n_assets": len(assets), "n_recovery_eps": len(rec), "n_crash_eps": len(crash),
                  "1_median_recovery_diff": m_rec, "2_median_crash_diff": m_crash, "3_median_calmar_diff": m_cal,
                  "pass": ok, "recovery_capture_vs_hold_median": statistics.median(cap_share) if cap_share else None,
                  "recovery_capture_B_median": statistics.median(cap_b) if cap_b else None}
    return out


def main() -> None:
    res = {}
    nas = ca.load_fred("NASDAQCOM", os.path.join(ROOT, "research", "crash_atlas", "fred"))
    g1 = {"NASDAQCOM": run_asset(nas[nas.index <= "2014-12-31"], 0.20)}
    res["G1"] = {"judge": judge(g1), "assets": g1}
    g2 = {}
    for line in open(os.path.join(ROOT, "research", "s677", "_bv_daily.jsonl")):
        x = json.loads(line)
        bars = [b for b in x["bars"] if b[4] > 0]
        if x["symbol"] in S601_SEEN:
            bars = [b for b in bars if b[0] <= S601_CUT]
        if len(bars) < 400 or x["symbol"] in ("BTC", "ETH"):
            continue
        s = pd.Series([b[4] for b in bars], index=pd.to_datetime([b[0] for b in bars]))
        g2[x["symbol"]] = run_asset(s, 0.50)
    res["G2"] = {"judge": judge(g2), "assets": g2}
    json.dump(res, open(os.path.join(HERE, "s679_seth_results.json"), "w"), indent=1, default=str)
    for g in ("G1", "G2"):
        print(g, json.dumps(res[g]["judge"], indent=1, default=str))
    print("G1 stats", json.dumps(g1["NASDAQCOM"]["stats"], default=str))


if __name__ == "__main__":
    main()
