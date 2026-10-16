"""S-604 —— 灵活组合的回撤—收益地图(预注册见 REFUTATION_LEDGER §S-604)。

用法:python3 docs/research/s604_frontier.py <research 目录> <输出 json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import stationary_bootstrap_index  # noqa: E402
import s602_simulate as s602  # noqa: E402

START, END, REB, COST, N_PATHS, DAYS, BLOCK, SEED = "2016-01-04", "2026-10-15", 21, 10 / 1e4, 1000, 1512, 60, 604


def legs(research: str):
    w = json.loads((Path(research) / "w50_daily/close.json").read_text())
    dates = w["dates"]
    btc = np.array([x if x else np.nan for x in w["close"]["BTC"]], dtype=float)
    ok = np.isfinite(btc)
    bd = [d for d, o in zip(dates, ok) if o]
    bc = btc[ok]
    ex = s602.exposures(bc)
    nav = {"H": np.cumprod(1 + s602.rets(bc, ex["H"])),
           "X1V": np.cumprod(1 + s602.rets(bc, ex["X1V"])),
           "X1V_fric": np.cumprod(1 + s602.rets(bc, ex["X1V"], True))}
    btc_nav = {k: dict(zip(bd, v)) for k, v in nav.items()}
    acwi, xau = w["close"]["ACWI"], w["close"]["XAUUSD"]
    common = [d for i, d in enumerate(dates) if START <= d <= END and acwi[i] and xau[i] and d in btc_nav["H"]]
    idx = {d: i for i, d in enumerate(dates)}
    eq = np.array([acwi[idx[d]] for d in common]); gd = np.array([xau[idx[d]] for d in common])
    out = {}
    for k in nav:
        c = np.array([btc_nav[k][d] for d in common])
        R = np.column_stack([c[1:] / c[:-1] - 1, eq[1:] / eq[:-1] - 1, gd[1:] / gd[:-1] - 1])
        out[k] = R
    return common, out


def grid():
    out = []
    for c in range(1, 8):
        for e in range(1, 9):
            for g in (0, 1, 2):
                if c + e + g <= 10 and c + e + g >= 3:
                    out.append((c / 10, e / 10, g / 10))
    return out


def portfolio(R: np.ndarray, w: tuple) -> np.ndarray:
    """R: (paths, days, 3);恒定配比,每 REB 天再平衡;返回 (paths, days) 日收益。"""
    tgt = np.array(w)
    P, D, _ = R.shape
    hold = np.tile(tgt, (P, 1))
    out = np.zeros((P, D))
    for t in range(D):
        if t % REB == 0 and t > 0:
            tv = np.abs(hold - tgt).sum(axis=1)
            hold = np.tile(tgt, (P, 1))
            cost = tv * COST
        else:
            cost = 0.0
        r = (hold * R[:, t, :]).sum(axis=1)
        out[:, t] = r - cost
        grown = hold * (1 + R[:, t, :])
        tot = grown.sum(axis=1) + (1 - hold.sum(axis=1))           # 现金收益 0
        hold = grown / tot[:, None]
    return out


def stats(r: np.ndarray, per_year: float = 252.0):
    nav = np.cumprod(1 + r, axis=1)
    yrs = r.shape[1] / per_year
    cagr = nav[:, -1] ** (1 / yrs) - 1
    dd = (nav / np.maximum.accumulate(nav, axis=1) - 1).min(axis=1)
    return cagr, dd


def main(research: str, out_path: str):
    common, legs_R = legs(research)
    rng = np.random.default_rng(SEED)
    n = len(next(iter(legs_R.values())))
    idx = stationary_bootstrap_index(n, BLOCK, N_PATHS, rng)[:, :DAYS]
    res = {"days": [common[0], common[-1], len(common)], "variants": {}}
    for k, R in legs_R.items():
        Rp = R[idx]                                            # (paths, days, 3),同一天整行
        rows = []
        for w in grid():
            cg, dd = stats(portfolio(Rp, w))
            hc, hd = stats(portfolio(R[None, :, :], w))
            rows.append({"crypto": w[0], "equity": w[1], "gold": w[2], "cash": round(1 - sum(w), 2),
                         "cagr_median": float(np.median(cg)), "cagr_p05": float(np.percentile(cg, 5)),
                         "dd_median": float(np.median(dd)), "dd_p05_worst": float(np.percentile(dd, 5)),
                         "hist_cagr": float(hc[0]), "hist_dd": float(hd[0])})
        front = {}
        for cap in (-0.25, -0.35, -0.45):
            ok = [r for r in rows if r["dd_p05_worst"] >= cap]
            front[str(cap)] = max(ok, key=lambda r: r["cagr_median"]) if ok else None
        res["variants"][k] = {"rows": rows, "frontier": front}
        print(k, "done", flush=True)
    Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2])
    print("days", r["days"])
    for k, v in r["variants"].items():
        print("==", k)
        for cap, f in v["frontier"].items():
            if f:
                print(f"  worst5%DD ≥ {cap}: crypto {f['crypto']:.0%} eq {f['equity']:.0%} gold {f['gold']:.0%} cash {f['cash']:.0%} | "
                      f"cagr med {f['cagr_median']*100:.1f}% p05 {f['cagr_p05']*100:.1f}% | dd med {f['dd_median']*100:.1f}% worst5 {f['dd_p05_worst']*100:.1f}% | hist {f['hist_cagr']*100:.1f}% / {f['hist_dd']*100:.1f}%")
