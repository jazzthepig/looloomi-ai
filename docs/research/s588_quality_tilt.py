"""S-588 —— ② 质量倾斜的组合层检验(预注册见 REFUTATION_LEDGER §S-588)。

用法:python3 docs/research/s588_quality_tilt.py <crypto_daily 目录> [输出 json]
A = 前 24 市值加权(① 近似);B = A × m(combo);C = 只持 BTC。每 4 周调仓,成本 20 bp,周收益记账。
主判据在留出段 2023-01 → 2026-09:ab_test(A, B) = B > A 且 随机倾斜(combo 在 24 名内打乱)1,000 次里 ≥ 95 分位。
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

from src.data.evaluation.apparatus import ab_test, null_distribution, percentile_of, shuffle_within  # noqa: E402
from s584_world50_weekly_mom import fridays, weekly_closes  # noqa: E402
from s587_mine_crypto import WRAPPED  # noqa: E402

N, EVERY, COST = 24, 4, 20 / 1e4
WINDOWS = {"holdout": ("2023-01-01", "2026-09-25"), "full": ("2020-01-01", "2026-09-25"), "discovery": ("2020-01-01", "2022-12-31")}


def tilt(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -3, 3)
    return np.where(z > 0, 1 + z, 1 / (1 - z))


def build(dir_: str):
    p = json.loads((Path(dir_) / "panel.json").read_text())
    grid = fridays("2019-06-07", "2026-10-16")
    syms = [s for s in p["price"] if s.upper() not in WRAPPED]
    P = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["price"][s], grid)] for s in syms], dtype=float)
    C = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["mcap"][s], grid)] for s in syms], dtype=float)
    T = P.shape[1]
    lr = np.full_like(P, np.nan)
    with np.errstate(all="ignore"):
        lr[:, 1:] = np.log(P[:, 1:] / P[:, :-1])
        units = C / P
    v13 = np.full_like(P, np.nan)
    v26 = np.full_like(P, np.nan)
    sup = np.full_like(P, np.nan)
    with np.errstate(all="ignore"):
        sup[:, 13:] = units[:, 13:] / units[:, :-13] - 1
        for t in range(13, T):
            w = lr[:, t - 12: t + 1]
            v13[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 10, np.nanstd(w, axis=1, ddof=1), np.nan)
            if t >= 26:
                w = lr[:, t - 25: t + 1]
                v26[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 20, np.nanstd(w, axis=1, ddof=1) * math.sqrt(52), np.nan)
    wret = np.full_like(P, np.nan)
    wret[:, 1:] = P[:, 1:] / P[:, :-1] - 1
    return grid, syms, P, C, v13, v26, sup, wret


def combo_z(idx: np.ndarray, t: int, C, v13, sup) -> np.ndarray:
    parts = [v13[idx, t], sup[idx, t], np.log(C[idx, t])]
    ok = np.all([np.isfinite(x) for x in parts], axis=0)
    z = np.full(len(idx), np.nan)
    if ok.sum() >= 5:
        rk = [np.argsort(np.argsort(v[ok])) / (ok.sum() - 1) for v in parts]
        sc = -rk[0] - rk[1] + rk[2]
        z[ok] = (sc - sc.mean()) / sc.std(ddof=1) if sc.std(ddof=1) > 0 else 0.0
    return z


def run(grid, syms, P, C, v13, v26, sup, wret, start: str, end: str, arm: str, rng: Optional[np.random.Generator] = None):
    bi = syms.index("BTC")
    t0 = next(i for i, g in enumerate(grid) if g >= start)
    w: dict[int, float] = {}
    out, weeks, turn, btc_w = [], [], 0.0, []
    since = EVERY
    for t in range(t0, len(grid)):
        if grid[t] > end:
            break
        if t > t0:
            avail = {i: wret[i, t] for i in w if np.isfinite(wret[i, t])}
            tot = sum(w[i] for i in avail)
            r = sum(w[i] * avail[i] for i in avail) / tot if tot > 0 else 0.0
            out.append(r)
            weeks.append(grid[t])
            grown = {i: w[i] * (1 + avail.get(i, 0.0)) for i in w}
            s = sum(grown.values())
            w = {i: v / s for i, v in grown.items()} if s > 0 else w
            since += 1
        if since < EVERY:
            continue
        if arm == "C":
            new = {bi: 1.0}
        else:
            m = C[:, t]
            ok = np.isfinite(m) & np.isfinite(P[:, t]) & (v26[:, t] >= 0.15)
            idx = np.where(ok)[0]
            idx = idx[np.argsort(-m[idx])][:N]
            cw = m[idx] / m[idx].sum()
            if arm == "A":
                wt = cw
            else:
                z = combo_z(idx, t, C, v13, sup)
                if rng is not None:                          # 随机倾斜:同一组 z 在 24 名内打乱
                    zz = z.copy()
                    okz = np.isfinite(zz)
                    zz[okz] = shuffle_within(zz[okz], np.zeros(okz.sum()), rng)
                    z = zz
                mm = np.where(np.isfinite(z), tilt(np.nan_to_num(z)), 1.0)
                wt = cw * mm
                wt = wt / wt.sum()
            new = {int(i): float(x) for i, x in zip(idx, wt)}
        keys = set(new) | set(w)
        tv = sum(abs(new.get(i, 0.0) - w.get(i, 0.0)) for i in keys)
        if out:
            out[-1] = (1 + out[-1]) * (1 - tv * COST) - 1
        turn += tv / 2
        w = new
        since = 0
        btc_w.append(new.get(bi, 0.0))
    return weeks, out, turn / (len(out) / 52) if out else None, float(np.mean(btc_w)) if btc_w else None


def stats(r: list[float]) -> dict[str, float]:
    a = np.asarray(r)
    nav = np.cumprod(1 + a)
    yrs = len(a) / 52
    cagr = nav[-1] ** (1 / yrs) - 1
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    return {"cagr": float(cagr), "vol": float(a.std(ddof=1) * math.sqrt(52)), "max_dd": float(dd), "total_x": float(nav[-1])}


def main(dir_: str, out_path: Optional[str] = None) -> dict[str, Any]:
    data = build(dir_)
    res: dict[str, Any] = {}
    for name, (a, b) in WINDOWS.items():
        wa, ra, ta, ba = run(*data, a, b, "A")
        wb, rb, tb, bb = run(*data, a, b, "B")
        wc, rc, _, _ = run(*data, a, b, "C")
        assert wa == wb == wc
        row = {"weeks": [wa[0], wa[-1], len(wa)],
               "A": {**stats(ra), "turnover": ta, "btc_w": ba}, "B": {**stats(rb), "turnover": tb, "btc_w": bb},
               "C_btc": stats(rc),
               "ab_B_vs_A": ab_test(ra, rb, mean_block=4, days_per_year=52),
               "ab_B_vs_C": ab_test(rc, rb, mean_block=4, days_per_year=52)}
        if name == "holdout":
            actual = float(np.log1p(np.asarray(rb)).sum())
            null = null_distribution(lambda rng: float(np.log1p(np.asarray(run(*data, a, b, "B", rng)[1])).sum()),
                                     1000, seed=588, actual=actual)
            row["random_tilt_pct"] = percentile_of(actual, null)
            row["passes"] = row["ab_B_vs_A"]["verdict"] == "B > A" and (row["random_tilt_pct"] or 0) >= 0.95
        res[name] = row
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    r = main(args[0], args[1] if len(args) > 1 else None)
    for name, row in r.items():
        print("==", name, row["weeks"])
        for k in ("A", "B", "C_btc"):
            v = row[k]
            print(f"  {k:6s} CAGR {v['cagr']*100:7.1f}%  vol {v['vol']*100:5.1f}%  MDD {v['max_dd']*100:6.1f}%  "
                  + (f"turn {v['turnover']:.2f}  btc_w {v['btc_w']:.2f}" if 'turnover' in v else ""))
        for k in ("ab_B_vs_A", "ab_B_vs_C"):
            v = row[k]
            print(f"  {k}: {v['verdict']} ratio {v['ratio_b_over_a']:.3f} p {v['p_b_le_a']:.3f} MDE/yr {v['mde_log_diff_per_year']:.3f}")
        if "random_tilt_pct" in row:
            print("  random tilt pct", row["random_tilt_pct"], "PASSES", row["passes"])
