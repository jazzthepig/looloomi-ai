"""S-601 —— 交易层的回撤:快出场 / 移动止损 / 波动率缩放(预注册见 REFUTATION_LEDGER §S-601)。

用法:python3 docs/research/s601_drawdown.py <research 目录> <funding_monthly.txt> [输出 json]
基准 B0 = S-600 的 FB;X1 = 多头破前 20 日低即平;X2 = 多头跌破本轮最高收盘 × 0.75 即平(S-600 跌破规则照留);
V = 敞口 × min(1, 过去两年 20 日实现波动中位数 ÷ 当前 20 日实现波动);X1V、X2V 组合。回撤与收益从第 201 天算。
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

from s600_tom_trader import RALLY_SIZE, RALLY_TP, returns  # noqa: E402

UNIT, STEP, CAP, MA_N, WARM, TRAIL = 0.1, 1.10, 1.3, 200, 200, 0.75
ARMS = {"B0": ("ma", False), "X1": ("l20", False), "X2": ("trail", False), "V": ("ma", True), "X1V": ("l20", True), "X2V": ("trail", True)}
SEEN = ("BTC", "ETH")
OOS_W50 = ("XRP", "BNB")
OOS_PANEL = ("LTC", "BCH", "ADA", "LINK", "DOGE", "XLM", "TRX", "ETC", "XMR", "ATOM")
METALS = ("XAUUSD", "XAGUSD")


def path(c: np.ndarray, exit_mode: str) -> np.ndarray:
    """FB 的状态机,出场方式可换。g[t] = 第 t 天收盘定下、t+1 生效。纯函数。"""
    n = len(c)
    g = np.ones(n)
    mode, k, last_add, entry, hi = "long", 0, None, None, c[min(WARM, n - 1)] if n else 0.0
    for t in range(WARM, n):
        x = c[t]
        ma = c[t - MA_N + 1:t + 1].mean()
        h20, l20, h55, l10 = c[t - 20:t].max(), c[t - 20:t].min(), c[t - 55:t].max(), c[t - 10:t].min()
        long_entry = x > ma and x > h20
        if mode == "long":
            hi = max(hi, x)
            if k > 0 and x < l20:
                k, last_add = 0, None
            elif k == 0 and x > h55 and 1 + UNIT <= CAP + 1e-9:
                k, last_add = 1, x
            elif k > 0 and x >= last_add * STEP and 1 + UNIT * (k + 1) <= CAP + 1e-9:
                k, last_add = k + 1, x
            out = (x < ma and x < l20) or (exit_mode == "l20" and x < l20) or (exit_mode == "trail" and x < hi * TRAIL)
            if out:
                mode, k, last_add = "flat", 0, None
        elif mode == "flat":
            if long_entry:
                mode, k, hi = "long", 0, x
            elif x > h20:
                mode, entry = "rally", x
        elif mode == "rally":
            if long_entry:
                mode, k, hi = "long", 0, x
            elif x >= entry * RALLY_TP or x < l10:
                mode = "flat"
        g[t] = {"long": 1 + UNIT * k, "flat": 0.0, "rally": RALLY_SIZE}[mode]
    return g


def vol_scale(c: np.ndarray) -> np.ndarray:
    """min(1, 过去 730 天 20 日实现波动的中位数 ÷ 当前 20 日实现波动);历史不足 ⇒ 1。只用当天及以前。"""
    lr = np.zeros(len(c))
    lr[1:] = np.log(c[1:] / c[:-1])
    v20 = np.full(len(c), np.nan)
    for t in range(20, len(c)):
        v20[t] = lr[t - 19:t + 1].std(ddof=1)
    s = np.ones(len(c))
    for t in range(260, len(c)):
        hist = v20[max(20, t - 730):t + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= 200 and v20[t] > 0:
            s[t] = min(1.0, float(np.median(hist)) / v20[t])
    return s


def metrics(r: np.ndarray, start: int) -> dict[str, float]:
    x = r[start:]
    nav = np.cumprod(1 + x)
    yrs = len(x) / 365
    cagr = nav[-1] ** (1 / yrs) - 1
    dd = nav / np.maximum.accumulate(nav) - 1
    under = float((dd < -0.05).mean())
    return {"cagr": float(cagr), "max_dd": float(dd.min()), "calmar": float(cagr / abs(dd.min())) if dd.min() < 0 else float("nan"),
            "total_x": float(nav[-1]), "time_under_5pct": under}


def series(research: str) -> dict[str, np.ndarray]:
    out = {}
    w = json.loads((Path(research) / "w50_daily/close.json").read_text())
    for k in SEEN + OOS_W50 + METALS:
        v = [x for x in w["close"].get(k, []) if x]
        if v:
            out[k] = np.array(v, dtype=float)
    p = json.loads((Path(research) / "crypto_daily/panel.json").read_text())
    for k in OOS_PANEL:
        v = [x for x in p["price"].get(k, []) if x]
        if v:
            out[k] = np.array(v, dtype=float)
    return out


def run(research: str, fund_path: str) -> dict[str, Any]:
    data = series(research)
    res: dict[str, Any] = {}
    for sym, c in data.items():
        fl = np.full(len(c), 0.10 / 365)          # 无资金费数据 ⇒ 多头 10% 年化、空头 0(这些臂不开空)
        fs = np.zeros(len(c))
        h = returns(c, np.ones(len(c)), fl, fs)
        row = {"H": metrics(h, WARM + 1)}
        vs = vol_scale(c)
        for arm, (exit_mode, vol) in ARMS.items():
            g = path(c, exit_mode)
            if vol:
                g = np.where(np.arange(len(c)) >= WARM, g * vs, g)
            row[arm] = metrics(returns(c, g, fl, fs), WARM + 1)
            row[arm]["avg_exposure"] = float(g[WARM:].mean())
        res[sym] = row
    oos = list(OOS_W50) + list(OOS_PANEL)
    verdict = {}
    for arm in ARMS:
        if arm == "B0":
            continue
        imp = [res[s]["B0"]["max_dd"] - res[s][arm]["max_dd"] for s in oos if s in res]      # 负值改负值:正 = 变浅
        cal = [res[s][arm]["calmar"] - res[s]["B0"]["calmar"] for s in oos if s in res]
        shallower = sum(1 for x in imp if x < 0)
        verdict[arm] = {"shallower": shallower, "n": len(imp), "median_dd_improvement_pp": float(-np.median(imp) * 100),
                        "median_calmar_change": float(np.median(cal)),
                        "passes": shallower >= math.ceil(0.75 * len(imp)) and -np.median(imp) >= 0.10 and np.median(cal) > 0}
    return {"assets": res, "verdict": verdict}


if __name__ == "__main__":
    r = run(sys.argv[1], sys.argv[2])
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float))
    arms = ["H"] + list(ARMS)
    print("asset   " + "  ".join(f"{a:>17s}" for a in arms))
    for sym, row in r["assets"].items():
        print(f"{sym:7s} " + "  ".join(f"{row[a]['cagr']*100:6.1f}%/{row[a]['max_dd']*100:6.1f}%/{row[a]['calmar']:4.2f}" for a in arms))
    for arm, v in r["verdict"].items():
        print(arm, v)
