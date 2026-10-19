"""S-602 —— 交易层的模拟一 / 二 / 三(协议见 REFUTATION_LEDGER §S-602):路径蒙特卡洛、执行现实、参数扰动。

用法:python3 docs/research/s602_simulate.py <research 目录> <输出目录> [mc|exec|params|all]
规则不在这里重写:H / F / FB 来自 s600_tom_trader.trade_path,X1V 来自 s601_drawdown.path + vol_scale,PD13 来自 s596_tom_pyramid.gross_path。
参数扰动用本文件的 x1v_param(默认参数下与 s601 逐日一致,启动时自检)。
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _apparatus import stationary_bootstrap_index  # noqa: E402
import s596_tom_pyramid as s596  # noqa: E402
import s600_tom_trader as s600  # noqa: E402
import s601_drawdown as s601  # noqa: E402

WARM_EVAL = 261                 # 规则 200 天热身 + 波动率缩放 260 天 ⇒ 从第 261 天起算
PATH_DAYS = 260 + 2190          # 热身 + 6 年
N_PATHS, SEED = 1000, 602
LONG_FUND = 0.10 / 365          # 合成路径没有资金费数据:多头 > 1 的部分一律 10% 年化,空头 0(这些规则不开空)
RULES = ("H", "F", "FB", "X1V", "PD13")


def exposures(c: np.ndarray) -> dict[str, np.ndarray]:
    n = len(c)
    x1 = s601.path(c, "l20")
    vs = s601.vol_scale(c)
    return {"H": np.ones(n),
            "F": s600.trade_path(c, "flat", 0.0)[0],
            "FB": s600.trade_path(c, "rally", 0.0)[0],
            "X1V": np.where(np.arange(n) >= s601.WARM, x1 * vs, x1),
            "PD13": s596.gross_path(c, 1.3, True)[0]}


def rets(c: np.ndarray, g: np.ndarray, friction: bool = False) -> np.ndarray:
    """friction=False:同 S-600(t 收盘定、t+1 生效,|Δg| × 10bp)。
    friction=True:晚一天成交(t 收盘的信号 t+2 才生效)+ 滑点 5bp + 0.1 × 20 日实现波动(每单位敞口变化),手续费 10bp 照收。"""
    n = len(c)
    fl, fs = np.full(n, LONG_FUND), np.zeros(n)
    if not friction:
        return s600.returns(c, g, fl, fs)
    gd = np.concatenate([[g[0]], g[:-1]])            # 晚一天
    r = s600.returns(c, gd, fl, fs)
    lr = np.zeros(n)
    lr[1:] = np.log(c[1:] / c[:-1])
    v20 = np.zeros(n)
    for t in range(20, n):
        v20[t] = lr[t - 19:t + 1].std(ddof=1)
    prev = np.concatenate([[1.0], gd[:-2]])
    slip = np.abs(gd[:-1] - prev) * (5 / 1e4 + 0.1 * v20[:-1])
    r[1:] -= slip
    return r


def metrics(r: np.ndarray) -> dict[str, float]:
    x = r[WARM_EVAL:]
    nav = np.cumprod(1 + x)
    yrs = len(x) / 365
    cagr = nav[-1] ** (1 / yrs) - 1 if nav[-1] > 0 else -1.0
    dd = float((nav / np.maximum.accumulate(nav) - 1).min())
    return {"cagr": float(cagr), "max_dd": dd, "calmar": float(cagr / abs(dd)) if dd < 0 else float("nan")}


def one_path(args) -> dict[str, dict[str, dict[str, float]]]:
    lr, idx = args
    c = 100 * np.exp(np.concatenate([[0.0], np.cumsum(lr[idx])]))
    ex = exposures(c)
    return {"clean": {k: metrics(rets(c, g)) for k, g in ex.items()},
            "friction": {k: metrics(rets(c, g, True)) for k, g in ex.items()}}


def summarize(results: list[dict], mode: str) -> dict[str, Any]:
    out = {}
    for k in RULES:
        cagr = np.array([p[mode][k]["cagr"] for p in results])
        dd = np.array([p[mode][k]["max_dd"] for p in results])
        cal = np.array([p[mode][k]["calmar"] for p in results])
        hc = np.array([p[mode]["H"]["cagr"] for p in results])
        out[k] = {"cagr_median": float(np.median(cagr)), "cagr_p05": float(np.percentile(cagr, 5)), "cagr_p95": float(np.percentile(cagr, 95)),
                  "dd_median": float(np.median(dd)), "dd_p05_worst": float(np.percentile(dd, 5)),
                  "p_dd_worse_50": float((dd < -0.5).mean()), "p_dd_worse_70": float((dd < -0.7).mean()),
                  "calmar_median": float(np.nanmedian(cal)), "p_beats_hold_cagr": float((cagr > hc).mean()) if k != "H" else None}
    h = out["H"]
    x = out["X1V"]
    out["X1V_passes"] = bool(x["dd_median"] - h["dd_median"] >= 0.20 and x["dd_p05_worst"] > h["dd_p05_worst"] and x["p_dd_worse_50"] <= 0.25)
    return out


def load(research: str, sym: str) -> np.ndarray:
    w = json.loads((Path(research) / "w50_daily/close.json").read_text())
    pts = [(d, x) for d, x in zip(w["dates"], w["close"][sym]) if x]
    return np.array([x for d, x in pts if d >= "2015-01-01"], dtype=float)


def sim_mc(research: str, sym: str, block: int) -> dict[str, Any]:
    c = load(research, sym)
    lr = np.log(c[1:] / c[:-1])
    idx = stationary_bootstrap_index(len(lr), block, N_PATHS, np.random.default_rng(SEED + block))[:, :PATH_DAYS - 1]
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(one_path, [(lr, idx[i]) for i in range(N_PATHS)], chunksize=20))
    return {"block": block, "paths": N_PATHS, "clean": summarize(res, "clean"), "friction": summarize(res, "friction")}


def sim_history(research: str, sym: str) -> dict[str, Any]:
    c = load(research, sym)
    ex = exposures(c)
    return {"clean": {k: metrics(rets(c, g)) for k, g in ex.items()}, "friction": {k: metrics(rets(c, g, True)) for k, g in ex.items()}}


# ── 模拟三:参数扰动 ────────────────────────────────────────────────────────────

def x1v_param(c: np.ndarray, ma_n: int, ch: int, vwin: int, vlook: int) -> np.ndarray:
    """X1V 的参数化版本(多头规则、加仓、FB 熊市反弹同 s601;只换 200 日线 / 20 日通道 / 波动窗 / 常态回看)。"""
    n = len(c)
    warm = max(ma_n, 200)
    g = np.ones(n)
    mode, k, last_add, entry, hi = "long", 0, None, None, 0.0
    for t in range(warm, n):
        x = c[t]
        ma = c[t - ma_n + 1:t + 1].mean()
        hch, lch, h55, l10 = c[t - ch:t].max(), c[t - ch:t].min(), c[t - 55:t].max(), c[t - 10:t].min()
        long_entry = x > ma and x > hch
        if mode == "long":
            if x < lch:
                mode, k, last_add = "flat", 0, None
            else:
                if k == 0 and x > h55 and 1.1 <= 1.3 + 1e-9:
                    k, last_add = 1, x
                elif k > 0 and x >= last_add * 1.10 and 1 + 0.1 * (k + 1) <= 1.3 + 1e-9:
                    k, last_add = k + 1, x
        elif mode == "flat":
            if long_entry:
                mode, k = "long", 0
            elif x > hch:
                mode, entry = "rally", x
        elif mode == "rally":
            if long_entry:
                mode, k = "long", 0
            elif x >= entry * 1.15 or x < l10:
                mode = "flat"
        g[t] = {"long": 1 + 0.1 * k, "flat": 0.0, "rally": 0.5}[mode]
    lr = np.zeros(n)
    lr[1:] = np.log(c[1:] / c[:-1])
    v = np.full(n, np.nan)
    for t in range(vwin, n):
        v[t] = lr[t - vwin + 1:t + 1].std(ddof=1)
    s = np.ones(n)
    for t in range(260, n):
        hist = v[max(vwin, t - vlook):t + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= 200 and v[t] > 0:
            s[t] = min(1.0, float(np.median(hist)) / v[t])
    return np.where(np.arange(n) >= warm, g * s, g)


def sim_params(research: str) -> dict[str, Any]:
    syms = ("BTC", "ETH")
    data = {s: load(research, s) for s in syms}
    p = json.loads((Path(research) / "crypto_daily/panel.json").read_text())
    w = json.loads((Path(research) / "w50_daily/close.json").read_text())
    for s in s601.OOS_W50:
        data[s] = np.array([x for x in w["close"][s] if x], dtype=float)
    for s in s601.OOS_PANEL:
        data[s] = np.array([x for x in p["price"][s] if x], dtype=float)
    # 自检:默认参数下与 s601 的 X1V 逐日一致(s601 的熊市反弹 / 加仓都在 path 里)
    c = data["BTC"]
    ref = s601.path(c, "l20") * np.where(np.arange(len(c)) >= s601.WARM, s601.vol_scale(c), 1.0)
    chk = float(np.abs(x1v_param(c, 200, 20, 20, 730) - ref).max())
    grid = [(m, ch, vw, vl) for m in (150, 200, 250) for ch in (15, 20, 30) for vw in (10, 20, 30) for vl in (365, 730)]
    out: dict[str, Any] = {"self_check_max_abs_diff": chk, "combos": len(grid), "assets": {}}
    for sym, c in data.items():
        h = metrics(rets(c, np.ones(len(c))))
        rows = []
        for m, ch, vw, vl in grid:
            met = metrics(rets(c, x1v_param(c, m, ch, vw, vl)))
            rows.append({"ma": m, "ch": ch, "vwin": vw, "vlook": vl, **met})
        dd_gain = np.array([r["max_dd"] - h["max_dd"] for r in rows])
        out["assets"][sym] = {"H": h, "share_dd_20pp_better": float((dd_gain >= 0.20).mean()),
                              "dd_median": float(np.median([r["max_dd"] for r in rows])),
                              "cagr_median": float(np.median([r["cagr"] for r in rows])),
                              "calmar_median": float(np.median([r["calmar"] for r in rows])),
                              "calmar_min": float(np.min([r["calmar"] for r in rows])), "rows": rows}
    b = out["assets"]["BTC"]
    out["passes_btc"] = bool(b["share_dd_20pp_better"] >= 0.80 and b["calmar_median"] > b["H"]["calmar"])
    return out


def main(research: str, outdir: str, which: str = "all") -> None:
    o = Path(outdir)
    o.mkdir(parents=True, exist_ok=True)
    if which in ("mc", "exec", "all"):
        res = {"history": {s: sim_history(research, s) for s in ("BTC", "ETH")}}
        for sym in ("BTC", "ETH"):
            for block in ((60, 20, 120) if sym == "BTC" else (60,)):
                res[f"{sym}_mc_b{block}"] = sim_mc(research, sym, block)
                print(sym, block, "done", flush=True)
        (o / "s602_mc_exec.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    if which in ("params", "all"):
        (o / "s602_params.json").write_text(json.dumps(sim_params(research), ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "all")
