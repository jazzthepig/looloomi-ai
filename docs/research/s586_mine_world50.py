"""S-586 挖掘(第一步:只看发现段)—— World50 池子的横截面因子:哪些信号对之后 1 / 2 / 4 / 13 周的收益有排序能力。

**纪律**:这一步只算发现段(默认 2016-01 → 2021-12),留出段(2022-01 → 2026-09)一行都不读;
挑出来的候选先写进台账 S-586 预注册(方向 + 判据),再用 --holdout 跑一次留出段。DECISIONS 10-07:挖掘与检验同等重要,但挖出来的都是探索。

用法:python3 docs/research/s586_mine_world50.py <w50_daily 目录> [输出 json] [--holdout] [--top=100]
信号(第 t 周收盘可知):r1 r2 r4 r13 r26 r52(收益)、r52s4(跳过最近 4 周的 12 个月)、r26s2(跳过最近 2 周的 6 个月)、
vol26(26 周周收益波动)、beta52(对 ACWI)、hi52(收盘 / 52 周最高)、size(对数市值)。
统计:每周名字层 Spearman IC(信号, 之后 h 周收益),全段平均;IC 序列用 apparatus 的平稳块自助(块长 = h 周)给 t;
另报两种状态(ACWI 过去 26 周 > 0 / ≤ 0)与发现段前后两半的符号稳定性。
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

from src.data.evaluation.apparatus import stationary_bootstrap_index  # noqa: E402
from s584_world50_weekly_mom import fridays, last_value, weekly_closes  # noqa: E402

DISCOVERY = ("2016-01-01", "2021-12-31")
HOLDOUT = ("2022-01-01", "2026-09-25")
HORIZONS = (1, 2, 4, 13)
SIGNALS = ("r1", "r2", "r4", "r13", "r26", "r52", "r52s4", "r26s2", "vol26", "beta52", "hi52", "size")


def rank(a: np.ndarray) -> np.ndarray:
    o = a.argsort()
    r = np.empty_like(o, dtype=float)
    r[o] = np.arange(len(a), dtype=float)
    return r


def spearman(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 10:
        return None
    rx, ry = rank(x[ok]), rank(y[ok])
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def signal_matrix(P: np.ndarray, M: np.ndarray, acwi: np.ndarray) -> dict[str, np.ndarray]:
    """P、M = [名字 × 周] 收盘与市值(缺 = nan);acwi = [周]。返回 {信号: [名字 × 周]}。纯函数。"""
    n, T = P.shape
    lr = np.full_like(P, np.nan)
    lr[:, 1:] = np.log(P[:, 1:] / P[:, :-1])
    la = np.full(T, np.nan)
    la[1:] = np.log(acwi[1:] / acwi[:-1])

    def ret(k: int, skip: int = 0) -> np.ndarray:
        out = np.full_like(P, np.nan)
        out[:, k:] = P[:, k - skip: T - skip] / P[:, : T - k] - 1 if skip else P[:, k:] / P[:, :-k] - 1
        return out

    sig = {f"r{k}": ret(k) for k in (1, 2, 4, 13, 26, 52)}
    s = np.full_like(P, np.nan)
    s[:, 52:] = P[:, 48:T - 4] / P[:, :T - 52] - 1
    sig["r52s4"] = s
    s = np.full_like(P, np.nan)
    s[:, 26:] = P[:, 24:T - 2] / P[:, :T - 26] - 1
    sig["r26s2"] = s
    vol = np.full_like(P, np.nan)
    beta = np.full_like(P, np.nan)
    hi = np.full_like(P, np.nan)
    for t in range(T):
        if t >= 26:
            w = lr[:, t - 25: t + 1]
            cnt = np.isfinite(w).sum(axis=1)
            v = np.nanstd(w, axis=1, ddof=1)
            vol[:, t] = np.where(cnt >= 20, v, np.nan)
        if t >= 52:
            w = lr[:, t - 51: t + 1]
            a = la[t - 51: t + 1]
            for i in range(n):
                ok = np.isfinite(w[i]) & np.isfinite(a)
                if ok.sum() >= 40 and a[ok].var() > 0:
                    beta[i, t] = np.cov(w[i][ok], a[ok])[0, 1] / a[ok].var(ddof=1)
            hi[:, t] = P[:, t] / np.nanmax(P[:, t - 51: t + 1], axis=1)
    sig["vol26"], sig["beta52"], sig["hi52"] = vol, beta, hi
    sig["size"] = np.log(M)
    return sig


def boot_t(ics: list[float], block: int, seed: int = 586) -> tuple[float, float]:
    a = np.asarray(ics, dtype=float)
    if a.size < 3 * block:
        return float("nan"), float("nan")
    idx = stationary_bootstrap_index(a.size, float(block), 2000, np.random.default_rng(seed))
    se = float(a[idx].mean(axis=1).std(ddof=1))
    return float(a.mean()), float(a.mean() / se) if se > 0 else float("nan")


def main(dir_: str, out_path: Optional[str] = None, holdout: bool = False, top: int = 100) -> dict[str, Any]:
    window = HOLDOUT if holdout else DISCOVERY
    d = Path(dir_)
    cj = json.loads((d / "close.json").read_text())
    mj = json.loads((d / "mcap.json").read_text())
    grid = fridays("2014-12-31", "2026-10-16")
    from src.data.universe.world50 import CANDIDATES
    pool = {c.key for c in CANDIDATES}          # 共用面板里 lane 可能加了别的加密(10-16 有 380 个),只取 World50 候选池
    keys = [k for k, c in cj["cls"].items() if c != "benchmark" and k in mj and k in pool]
    P = np.array([[x if x else np.nan for x in weekly_closes(cj["dates"], cj["close"][k], grid)] for k in keys], dtype=float)
    M = np.array([[last_value(mj[k], g, 14) or np.nan for g in grid] for k in keys], dtype=float)
    acwi = np.array([x if x else np.nan for x in weekly_closes(cj["dates"], cj["close"]["ACWI"], grid)], dtype=float)
    sig = signal_matrix(P, M, acwi)
    T = len(grid)
    res: dict[str, Any] = {"window": window, "top": top, "names": len(keys), "signals": {}}
    for h in HORIZONS:
        fwd = np.full_like(P, np.nan)
        fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
        for sname in SIGNALS:
            ics, states, dates = [], [], []
            for t in range(T - h):
                g = grid[t]
                if not (window[0] <= g <= window[1]) or (not holdout and grid[t + h] > window[1]):
                    continue
                m = M[:, t]
                ok = np.isfinite(m) & np.isfinite(P[:, t])
                if ok.sum() < 20:
                    continue
                cut = np.sort(m[ok])[::-1][min(top, ok.sum()) - 1]
                uni = ok & (m >= cut)
                ic = spearman(sig[sname][uni, t], fwd[uni, t])
                if ic is None:
                    continue
                ics.append(ic)
                dates.append(g)
                up = t >= 26 and np.isfinite(acwi[t]) and np.isfinite(acwi[t - 26]) and acwi[t] > acwi[t - 26]
                states.append("up" if up else "down")
            mean, tstat = boot_t(ics, h)
            half = len(ics) // 2
            res["signals"][f"{sname}|h{h}"] = {
                "n": len(ics), "ic": mean, "t": tstat,
                "ic_first_half": float(np.mean(ics[:half])) if half else None,
                "ic_second_half": float(np.mean(ics[half:])) if half else None,
                "ic_up": float(np.mean([x for x, s in zip(ics, states) if s == "up"])) if "up" in states else None,
                "ic_down": float(np.mean([x for x, s in zip(ics, states) if s == "down"])) if "down" in states else None,
                "n_down": states.count("down"),
            }
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    top = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--top=")), 100))
    r = main(args[0], args[1] if len(args) > 1 else None, "--holdout" in sys.argv, top)
    print("window", r["window"], "top", r["top"], "names", r["names"])
    rows = sorted(r["signals"].items(), key=lambda kv: -abs(kv[1]["t"]) if math.isfinite(kv[1]["t"]) else 0)
    for k, v in rows:
        print(f"{k:12s} n {v['n']:4d}  IC {v['ic']:+.4f}  t {v['t']:+5.2f}  halves {v['ic_first_half']:+.3f}/{v['ic_second_half']:+.3f}  "
              f"up {v['ic_up'] if v['ic_up'] is not None else float('nan'):+.3f}  down {v['ic_down'] if v['ic_down'] is not None else float('nan'):+.3f} (n {v['n_down']})")
