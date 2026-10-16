"""S-603 —— 少换手版 X1V(预注册见 REFUTATION_LEDGER §S-603):调仓带宽 / 周度波动缩放,在 S-602 的摩擦模拟里判。

用法:python3 docs/research/s603_low_turnover.py <research 目录> <输出 json>
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import stationary_bootstrap_index  # noqa: E402
import s601_drawdown as s601  # noqa: E402
import s602_simulate as s602  # noqa: E402

BAND = 0.25


def x1v_parts(c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return s601.path(c, "l20"), s601.vol_scale(c)


def weekly(vs: np.ndarray) -> np.ndarray:
    """周一更新、周内沿用。合成路径没有星期 ⇒ 每 7 天更新一次(第 0 天起)。"""
    out = vs.copy()
    for t in range(len(vs)):
        if t % 7:
            out[t] = out[t - 1]
    return out


def banded(target: np.ndarray, start: int) -> np.ndarray:
    g = target.copy()
    cur = target[start - 1] if start > 0 else 1.0
    for t in range(start, len(target)):
        x = target[t]
        if x == 0 or (cur == 0 and x > 0) or abs(x - cur) >= BAND:
            cur = x
        g[t] = cur
    return g


def variants(c: np.ndarray) -> dict[str, np.ndarray]:
    n = len(c)
    base, vs = x1v_parts(c)
    on = np.arange(n) >= s601.WARM
    x1v = np.where(on, base * vs, base)
    xw = np.where(on, base * weekly(vs), base)
    return {"H": np.ones(n), "X1V": x1v, "XB": banded(x1v, s601.WARM), "XW": xw, "XBW": banded(xw, s601.WARM)}


def turnover(g: np.ndarray) -> float:
    return float(np.abs(np.diff(g[s602.WARM_EVAL:])).sum() / ((len(g) - s602.WARM_EVAL) / 365))


def one(args):
    lr, idx = args
    c = 100 * np.exp(np.concatenate([[0.0], np.cumsum(lr[idx])]))
    ex = variants(c)
    return {"clean": {k: s602.metrics(s602.rets(c, g)) for k, g in ex.items()},
            "friction": {k: s602.metrics(s602.rets(c, g, True)) for k, g in ex.items()},
            "turnover": {k: turnover(g) for k, g in ex.items()}}


def summarize(res, mode):
    out = {}
    for k in ("H", "X1V", "XB", "XW", "XBW"):
        cagr = np.array([p[mode][k]["cagr"] for p in res]); dd = np.array([p[mode][k]["max_dd"] for p in res])
        out[k] = {"cagr_median": float(np.median(cagr)), "cagr_p05": float(np.percentile(cagr, 5)), "dd_median": float(np.median(dd)),
                  "dd_p05_worst": float(np.percentile(dd, 5)), "p_dd_worse_50": float((dd < -0.5).mean()),
                  "turnover_median": float(np.median([p["turnover"][k] for p in res]))}
    h = out["H"]
    for k in ("X1V", "XB", "XW", "XBW"):
        v = out[k]
        v["passes"] = bool(v["dd_median"] - h["dd_median"] >= 0.20 and v["p_dd_worse_50"] <= 0.35 and v["cagr_median"] >= h["cagr_median"] - 0.10)
    return out


def main(research: str, out_path: str):
    res = {}
    for sym in ("BTC", "ETH"):
        c = s602.load(research, sym)
        ex = variants(c)
        res[f"{sym}_history"] = {"clean": {k: s602.metrics(s602.rets(c, g)) for k, g in ex.items()},
                                 "friction": {k: s602.metrics(s602.rets(c, g, True)) for k, g in ex.items()},
                                 "turnover": {k: turnover(g) for k, g in ex.items()}}
        lr = np.log(c[1:] / c[:-1])
        idx = stationary_bootstrap_index(len(lr), 60, s602.N_PATHS, np.random.default_rng(s602.SEED + 60))[:, :s602.PATH_DAYS - 1]
        with ProcessPoolExecutor() as px:
            paths = list(px.map(one, [(lr, idx[i]) for i in range(s602.N_PATHS)], chunksize=20))
        res[f"{sym}_mc_b60"] = {"clean": summarize(paths, "clean"), "friction": summarize(paths, "friction")}
        print(sym, "done", flush=True)
    Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2])
    for key in ("BTC_mc_b60", "ETH_mc_b60"):
        for mode in ("clean", "friction"):
            print("==", key, mode)
            for k, v in r[key][mode].items():
                print(f"  {k:4s} cagr {v['cagr_median']*100:6.1f}% p05 {v['cagr_p05']*100:6.1f}% | dd {v['dd_median']*100:6.1f}% worst5 {v['dd_p05_worst']*100:6.1f}% "
                      f"P<-50 {v['p_dd_worse_50']:.2f} | turnover {v['turnover_median']:.1f}/yr | pass {v.get('passes')}")
    for key in ("BTC_history", "ETH_history"):
        h = r[key]
        print("==", key, {k: (round(h['friction'][k]['cagr']*100, 1), round(h['friction'][k]['max_dd']*100, 1), round(h['turnover'][k], 1)) for k in h['friction']})
