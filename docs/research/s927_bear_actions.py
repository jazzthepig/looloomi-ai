"""S-927:深熊里为什么只「减半」—— 同一窗口把 z 的动作换成空仓 / 做空,再和前向账里的趋势三态 R6 并排。只描述,不判。

问题拆成两件:动作太弱(减半)?还是信号没响(z)?
- z 换动作(信号不变,沿用 S-926 的执行:z_d 作用在 d+2 的收益):Z-half(S-926 的 A)、Z-flat(z < −1 ⇒ 0)、Z-short(⇒ −0.3)、Z-short1(⇒ −1.0)。
- 趋势(信号换成价格,动作 = R6):R6 原样走生产的纯函数 `state_arms.r6_exposure` / `r6_returns`(d 收盘定、d+1 生效);
  R8 = R6 但「明显向下」时 0 而不是 −0.3。
- 窗口 / 标的 / 成本照 S-926:2022-06-24 → 2026-11-24,BTC 永续日收盘,换手 10 bp;空头期间按天计 BTC 资金费(收盘价表 `perp_bv_daily`、
  资金费 `funding_daily` 的 funding_rate × n)。

用法(仓库根目录):
    python3 docs/research/s927_bear_actions.py --selftest
    python3 docs/research/s927_bear_actions.py --from-json <s926 的 z 导出> <btc_funding.json>   # {"c": [[YYMMDD, close]], "f": [[YYMMDD, 日资金费]]}
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from src.data.signals.state_arms import r6_exposure, r6_returns  # noqa: E402

_sp = importlib.util.spec_from_file_location("s926", os.path.join(HERE, "s926_joint_z_sizing.py"))
Z = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(Z)

OUT = "docs/research/s927_results.json"
BEAR = (dt.date(2025, 10, 7), dt.date(2026, 6, 30))       # 2025-10-06 收盘见顶 → 2026-06-30 收盘见底(S-926 结果里量的)
Z_ACTIONS = {"Z_half": 0.5, "Z_flat": 0.0, "Z_short": -0.3, "Z_short1": -1.0}


def z_rule(cut: float):
    return lambda z: cut if z < -1 else 1.0


def account(days: list, r: np.ndarray, w: np.ndarray, fund: dict) -> np.ndarray:
    """日收益 = w × r − 10bp × |Δw| + 空头时 |w| × 当天资金费。"""
    f = np.array([fund.get(t, 0.0) for t in days])
    tw = np.abs(np.diff(np.r_[w[0], w]))
    return w * r - Z.COST * tw + np.clip(-w, 0, None) * f


def seg(days: list, ret: np.ndarray, w: np.ndarray, a: dt.date, b: dt.date) -> dict:
    m = np.array([a <= t <= b for t in days])
    return {"ret": round(float(np.prod(1 + ret[m]) - 1), 4), "avg_w": round(float(w[m].mean()), 3),
            "share_cut": round(float((w[m] < 1).mean()), 3)}


def run(zr: list, closes: list, fund_rows: list) -> dict:
    cr = [(d, c) for d, c in closes]
    days, r, zdays, zvals = Z.prepare(zr, cr)
    zmap = dict(zip(zdays, zvals))
    fund = dict(fund_rows)
    out = {"window": [str(days[0]), str(days[-1])], "arms": {}}

    def put(name: str, ret: np.ndarray, w: np.ndarray):
        nv = np.cumprod(1 + ret)
        out["arms"][name] = {**Z.stats(days, nv), "avg_w": round(float(w.mean()), 3), "bear": seg(days, ret, w, *BEAR)}

    put("HOLD", r.copy(), np.ones(len(r)))
    for name, cut in Z_ACTIONS.items():
        w = Z.exposures(days, zmap, z_rule(cut))
        put(name, account(days, r, w, fund), w)
    # R6 / R8:生产的纯函数,收盘序列从 2021 年起(均线要 230 天成形)
    s = pd.Series({pd.Timestamp(d): c for d, c in closes}).sort_index()
    fs = pd.Series({pd.Timestamp(d): v for d, v in fund_rows}).sort_index()
    e6 = r6_exposure(s)
    e8 = e6.where(e6 >= 0, 0.0)
    for name, e in (("R6", e6), ("R8", e8)):
        ret, pos, _ = r6_returns(s, e, fs, start=str(days[0]), end=str(days[-1]))
        ret = ret.reindex([pd.Timestamp(t) for t in days]).fillna(0.0).to_numpy()
        pos = pos.reindex([pd.Timestamp(t) for t in days]).fillna(0.3).to_numpy()
        put(name, ret, pos)
    zb = [v for d, v in zip(zdays, zvals) if BEAR[0] - dt.timedelta(days=Z.LAG) <= d <= BEAR[1] - dt.timedelta(days=Z.LAG)]
    out["bear_z_below_m1_share"] = round(float(np.mean(np.array(zb) < -1)), 3) if zb else None
    out["r6_today"] = {"d": str(e6.index[-1].date()), "e": float(e6.iloc[-1])}
    return out


def synthetic() -> tuple:
    zr, cr = Z.synthetic()
    d0 = cr[0][0] - dt.timedelta(days=400)
    pre = [(d0 + dt.timedelta(days=i), 100.0 * (1 + 0.001 * i)) for i in range(400)]
    closes = pre + cr
    fund = [(d, 0.0003) for d, _ in closes]
    return zr, closes, fund


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        Z.N_SHIFT = 10
        zr, closes, fund = synthetic()
    else:
        i = sys.argv.index("--from-json")
        zr, _ = Z.load(sys.argv[i + 1])
        j = json.load(open(sys.argv[i + 2]))
        closes = [(dt.datetime.strptime(a, "%y%m%d").date(), float(b)) for a, b in j["c"]]
        fund = [(dt.datetime.strptime(a, "%y%m%d").date(), float(b)) for a, b in j["f"]]
    out = run(zr, closes, fund)
    print("WINDOW", json.dumps(out["window"]), "| bear z<-1 share", out["bear_z_below_m1_share"], "| R6 today", json.dumps(out["r6_today"]), flush=True)
    for k, v in out["arms"].items():
        print("ARM", k, json.dumps(v), flush=True)
    if selftest:
        assert set(out["arms"]) == {"HOLD", "Z_half", "Z_flat", "Z_short", "Z_short1", "R6", "R8"}
        # 资金费只在做空时计:满仓那条与不计资金费的同一条一致
        days, r, zdays, zvals = Z.prepare(zr, closes)
        w1 = np.ones(len(r))
        assert np.allclose(account(days, r, w1, dict(fund)), r - Z.COST * 0)
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
