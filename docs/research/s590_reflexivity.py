"""S-590 —— 反身性阶段:因子在不同阶段换不换号(预注册见 REFUTATION_LEDGER §S-590)。

用法:python3 docs/research/s590_reflexivity.py <crypto_daily 目录> <states.csv> [输出 json]
states.csv = 每周五:稳定币总量(USDT + USDC + DAI + USDe,百万美元)、恐惧贪婪 4 周均值(SQL 从 cg_coin_mcap_daily / macro_daily 导出)。
阶段:R+ = BTC 在 26 周均线上 且 稳定币 13 周增速 > 0 且高于 13 周前;F = BTC 在均线上、流动性不扩张;W = BTC 在均线下 且 恐惧(≤ 35);D = 其余下行。
H1:r2 → 之后 4 周 IC,R+ 减 (F ∪ W),阶段标签按 13 周块打乱 1,000 次(apparatus.block_permute)≥ 95 分位才算。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import block_permute, null_distribution, percentile_of  # noqa: E402
from s584_world50_weekly_mom import fridays, weekly_closes  # noqa: E402
from s586_mine_world50 import spearman  # noqa: E402
from s587_mine_crypto import WRAPPED  # noqa: E402

WINDOW = ("2021-06-04", "2026-09-18")
H = 4


def load_states(path: str) -> dict[str, tuple[Optional[float], Optional[float]]]:
    out = {}
    for r in csv.DictReader(open(path)):
        out[r["d"]] = (float(r["stable_musd"]) if r["stable_musd"] else None, float(r["fng4w"]) if r["fng4w"] else None)
    return out


def phases(grid: list[str], btc: np.ndarray, st: dict) -> list[Optional[str]]:
    sup = [st.get(g, (None, None))[0] for g in grid]
    fng = [st.get(g, (None, None))[1] for g in grid]
    out: list[Optional[str]] = []
    for t, g in enumerate(grid):
        if t < 26 or not np.isfinite(btc[t]) or sup[t] is None or t < 26 or sup[t - 13] is None or sup[t - 26] is None or fng[t] is None:
            out.append(None)
            continue
        ma = np.nanmean(btc[t - 25: t + 1])
        up = btc[t] > ma
        g13 = sup[t] / sup[t - 13] - 1
        g13_prev = sup[t - 13] / sup[t - 26] - 1
        expanding = g13 > 0 and g13 > g13_prev
        if up:
            out.append("R+" if expanding else "F")
        else:
            out.append("W" if fng[t] <= 35 else "D")
    return out


def main(dir_: str, states_path: str, out_path: Optional[str] = None) -> dict[str, Any]:
    p = json.loads((Path(dir_) / "panel.json").read_text())
    grid = fridays("2019-06-07", "2026-10-16")
    syms = [s for s in p["price"] if s.upper() not in WRAPPED]
    P = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["price"][s], grid)] for s in syms], dtype=float)
    C = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["mcap"][s], grid)] for s in syms], dtype=float)
    T = P.shape[1]
    bi = syms.index("BTC")
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
                v26[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 20, np.nanstd(w, axis=1, ddof=1) * np.sqrt(52), np.nan)
    r2 = np.full_like(P, np.nan)
    r2[:, 2:] = P[:, 2:] / P[:, :-2] - 1
    fwd = np.full_like(P, np.nan)
    fwd[:, : T - H] = P[:, H:] / P[:, : T - H] - 1
    ph = phases(grid, P[bi], load_states(states_path))
    rows = []
    for t in range(T - H):
        g = grid[t]
        if not (WINDOW[0] <= g <= WINDOW[1]) or ph[t] is None:
            continue
        m = C[:, t]
        ok = np.isfinite(m) & np.isfinite(P[:, t]) & (v26[:, t] >= 0.15)
        if ok.sum() < 30:
            continue
        cut = np.sort(m[ok])[::-1][min(50, ok.sum()) - 1]
        uni = ok & (m >= cut)
        parts = [v13[uni, t], sup[uni, t], np.log(C[uni, t])]
        okc = np.all([np.isfinite(x) for x in parts], axis=0)
        combo = np.full(int(uni.sum()), np.nan)
        if okc.sum() >= 10:
            rk = [np.argsort(np.argsort(v[okc])) / (okc.sum() - 1) for v in parts]
            combo[okc] = -rk[0] - rk[1] + rk[2]
        ew = np.nanmean(fwd[uni, t])
        rows.append({"d": g, "phase": ph[t], "ic_r2": spearman(r2[uni, t], fwd[uni, t]), "ic_combo": spearman(combo, fwd[uni, t]),
                     "btc_fwd": float(fwd[bi, t]) if np.isfinite(fwd[bi, t]) else None, "ew_fwd": float(ew)})
    labels = [r["phase"] for r in rows]
    ic_r2 = np.array([r["ic_r2"] if r["ic_r2"] is not None else np.nan for r in rows])

    def h1_stat(lab) -> float:
        lab = np.asarray(lab)
        a = ic_r2[(lab == "R+") & np.isfinite(ic_r2)]
        b = ic_r2[((lab == "F") | (lab == "W")) & np.isfinite(ic_r2)]
        return float(a.mean() - b.mean()) if a.size and b.size else float("nan")
    actual = h1_stat(labels)
    null = null_distribution(lambda rng: h1_stat(block_permute(labels, 13, rng)), 1000, seed=590, actual=actual)
    res: dict[str, Any] = {"weeks": len(rows), "H1_stat": actual, "H1_pct": percentile_of(actual, null),
                           "H1_passes": (percentile_of(actual, null) or 0) >= 0.95, "by_phase": {}}
    for ph_name in ("R+", "F", "W", "D"):
        sel = [r for r in rows if r["phase"] == ph_name]
        def mean(k):
            v = [r[k] for r in sel if r[k] is not None]
            return float(np.mean(v)) if v else None
        res["by_phase"][ph_name] = {"weeks": len(sel), "ic_r2": mean("ic_r2"), "ic_combo": mean("ic_combo"),
                                    "btc_fwd4w": mean("btc_fwd"), "ew50_fwd4w": mean("ew_fwd")}
    # 阶段收益对打乱的分位(每个阶段的 BTC 之后 4 周均值)
    btc = np.array([r["btc_fwd"] if r["btc_fwd"] is not None else np.nan for r in rows])
    ewf = np.array([r["ew_fwd"] for r in rows])
    for ph_name in ("R+", "F", "W", "D"):
        for nm, arr in (("btc", btc), ("ew50", ewf)):
            def st(lab, arr=arr, ph_name=ph_name):
                lab = np.asarray(lab)
                x = arr[(lab == ph_name) & np.isfinite(arr)]
                return float(x.mean()) if x.size else float("nan")
            a = st(labels)
            nl = null_distribution(lambda rng: st(block_permute(labels, 13, rng)), 1000, seed=591, actual=a)
            res["by_phase"][ph_name][f"{nm}_pct_vs_shuffle"] = percentile_of(a, nl)
    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print("weeks", r["weeks"], "H1 stat", round(r["H1_stat"], 4), "pct", r["H1_pct"], "passes", r["H1_passes"])
    for k, v in r["by_phase"].items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})
