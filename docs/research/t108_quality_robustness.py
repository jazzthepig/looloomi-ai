"""T-108 —— 加密质量因子的稳健性挖掘(S-587 留出段复现 → 拆解 + 宇宙放宽 + 波动窗口 + 幸存者 + 分年)。

按 tasks/T-108.json acceptance 做(全部标「探索」,S-587 留出段已是结论):
① 三个因子的分工:双重排序(按 size 分三档,档内看 vol13 / supply13 的 IC)+ 周频横截面回归。
② 宇宙放宽:前 100、前 150 各跑一次 combo 的 4 / 13 周 IC。
③ 换波动窗口:vol4 / vol26 对 vol13。
④ 幸存者:列 2020-2023 曾进过市值前 50、今天 mcap < $100M 的币(只列,不补数据)。
⑤ 分年份的 combo IC 表。

数据:Mac 数据根 research/crypto_daily/panel.json(由 s587_mine_crypto.py 同源);零分布 / A/B 用 apparatus.py。
用法:python3 docs/research/t108_quality_robustness.py <crypto_daily 目录> <输出 json>
"""
from __future__ import annotations

import bisect
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import percentile_of  # noqa: E402
from s584_world50_weekly_mom import fridays, weekly_closes  # noqa: E402
from s586_mine_world50 import boot_t, spearman  # noqa: E402
from s587_mine_crypto import WRAPPED  # noqa: E402

HOLDOUT = ("2023-01-01", "2026-09-25")
HORIZONS = (1, 2, 4, 13)


def build_panel(dir_: str):
    """同 S-587 口径:周五网格 + 周价 / 周市值 + vol13 / vol4 / vol26 / supply13 / size。"""
    p = json.loads((Path(dir_) / "panel.json").read_text())
    grid = fridays("2019-06-07", "2026-10-16")
    syms = [s for s in p["price"] if s.upper() not in WRAPPED]
    P = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["price"][s], grid)] for s in syms], dtype=float)
    C = np.array([[x if x else np.nan for x in weekly_closes(p["dates"], p["mcap"][s], grid)] for s in syms], dtype=float)
    n, T = P.shape
    lr = np.full_like(P, np.nan)
    lr[:, 1:] = np.log(P[:, 1:] / P[:, :-1])
    v4 = np.full_like(P, np.nan)
    v13 = np.full_like(P, np.nan)
    v26 = np.full_like(P, np.nan)
    sup = np.full_like(P, np.nan)
    with np.errstate(all="ignore"):
        units = C / P
        sup[:, 13:] = units[:, 13:] / units[:, :-13] - 1
        for t in range(T):
            if t >= 4:
                w = lr[:, t - 3: t + 1]
                v4[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 3, np.nanstd(w, axis=1, ddof=1) * math.sqrt(52), np.nan)
            if t >= 13:
                w = lr[:, t - 12: t + 1]
                v13[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 10, np.nanstd(w, axis=1, ddof=1) * math.sqrt(52), np.nan)
            if t >= 26:
                w = lr[:, t - 25: t + 1]
                v26[:, t] = np.where(np.isfinite(w).sum(axis=1) >= 20, np.nanstd(w, axis=1, ddof=1) * math.sqrt(52), np.nan)
    return grid, syms, P, C, v4, v13, v26, sup


def universe_mask(m_t: np.ndarray, p_t: np.ndarray, v26_t: np.ndarray, top: int) -> np.ndarray:
    """同 S-587:有 mcap / 有价 / 26 周波动 ≥ 15% + top-N。"""
    ok = np.isfinite(m_t) & np.isfinite(p_t) & (v26_t >= 0.15)
    if ok.sum() < 5:
        return ok
    cut = np.sort(m_t[ok])[::-1][min(top, ok.sum()) - 1]
    return ok & (m_t >= cut)


def rank_safe(values: np.ndarray) -> np.ndarray:
    """在 finite 子集上做 [0, 1] 秩;非 finite 为 NaN。"""
    out = np.full_like(values, np.nan)
    ok = np.isfinite(values)
    if ok.sum() < 3:
        return out
    out[ok] = np.argsort(np.argsort(values[ok])) / (ok.sum() - 1)
    return out


def combo_z(v13_t, sup_t, sz_t):
    """−秩(vol13) − 秩(supply13) + 秩(size),在三者都 finite 的子集上算。"""
    ok = np.isfinite(v13_t) & np.isfinite(sup_t) & np.isfinite(sz_t)
    z = np.full(len(v13_t), np.nan)
    if ok.sum() < 10:
        return z
    rv = rank_safe(v13_t)[ok]
    rs = rank_safe(sup_t)[ok]
    rz = rank_safe(sz_t)[ok]
    sc = -rv - rs + rz
    m, s = sc.mean(), sc.std(ddof=1)
    if s > 0:
        z[ok] = (sc - m) / s
    else:
        z[ok] = 0.0
    return z


def cross_section_regression(y: np.ndarray, x: np.ndarray) -> tuple[float, float, int]:
    """每周横截面:收益 y 对三个秩的回归系数(解在三者 finite 交集上)。返回 (β_vol13, β_supply13, β_size, n)。"""
    ok = np.isfinite(y) & np.isfinite(x[:, 0]) & np.isfinite(x[:, 1]) & np.isfinite(x[:, 2])
    if ok.sum() < 10 or y[ok].std() == 0:
        return (np.nan, np.nan, np.nan, int(ok.sum()))
    X = np.column_stack([x[ok, 0], x[ok, 1], x[ok, 2], np.ones(ok.sum())])
    yv = y[ok]
    try:
        beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
    except np.linalg.LinAlgError:
        return (np.nan, np.nan, np.nan, int(ok.sum()))
    return (float(beta[0]), float(beta[1]), float(beta[2]), int(ok.sum()))


def collect_combo_ics(grid, syms, P, C, v13, sup, top: int, h: int, window: tuple[str, str]):
    """每周 t 算 combo 在 N 名宇宙的 IC。返回 [(iso_t, ic), ...]。"""
    T = P.shape[1]
    fwd = np.full_like(P, np.nan)
    fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
    out = []
    for t in range(T - h):
        g = grid[t]
        if not (window[0] <= g <= window[1]):
            continue
        m = C[:, t]
        uni = _build_uni(m, P[:, t], _v26_for_uni[:, t], top)
        if uni.sum() < 10:
            continue
        sz = np.log(np.where(m > 0, m, np.nan))
        ic = spearman(combo_z(v13[uni, t], sup[uni, t], sz[uni]), fwd[uni, t])
        if ic is None:
            continue
        out.append((g, ic))
    return out


# globals filled in main(); collect_* 通过 module globals 读 v26 / v13 / sup 构造宇宙。
_v26_for_uni = None


def collect_combo_ics(grid, syms, P, C, v13, sup, top: int, h: int, window: tuple[str, str]):
    T = P.shape[1]
    fwd = np.full_like(P, np.nan)
    fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
    out = []
    for t in range(T - h):
        g = grid[t]
        if not (window[0] <= g <= window[1]):
            continue
        m = C[:, t]
        uni = _build_uni(m, P[:, t], _v26_for_uni[:, t], top)
        if uni.sum() < 10:
            continue
        sz = np.log(np.where(m > 0, m, np.nan))
        ic = spearman(combo_z(v13[uni, t], sup[uni, t], sz[uni]), fwd[uni, t])
        if ic is None:
            continue
        out.append((g, ic))
    return out


def collect_single_ics(grid, syms, P, C, sig_data: np.ndarray, top: int, h: int, window: tuple[str, str]):
    T = P.shape[1]
    fwd = np.full_like(P, np.nan)
    fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
    out = []
    for t in range(T - h):
        g = grid[t]
        if not (window[0] <= g <= window[1]):
            continue
        m = C[:, t]
        uni = _build_uni(m, P[:, t], _v26_for_uni[:, t], top)
        if uni.sum() < 10:
            continue
        ic = spearman(sig_data[uni, t], fwd[uni, t])
        if ic is None:
            continue
        out.append((g, ic))
    return out


def _build_uni(m_t: np.ndarray, p_t: np.ndarray, v26_t: np.ndarray, top: int) -> np.ndarray:
    ok = np.isfinite(m_t) & np.isfinite(p_t) & (v26_t >= 0.15)
    if ok.sum() < 5:
        return ok
    cut = np.sort(m_t[ok])[::-1][min(top, ok.sum()) - 1]
    return ok & (m_t >= cut)


# ── ① 双重排序 + 横截面回归 ─────────────────────────────────────────────────────

def double_sort_by_size(grid, syms, P, C, v13, sup, top: int, h: int, window: tuple[str, str]):
    """按 size 分三档,在每档内看 vol13 与 supply13 的 IC。"""
    T = P.shape[1]
    fwd = np.full_like(P, np.nan)
    fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
    out: dict[str, list[float]] = {"big_vol": [], "mid_vol": [], "sml_vol": [], "big_sup": [], "mid_sup": [], "sml_sup": []}
    for t in range(T - h):
        g = grid[t]
        if not (window[0] <= g <= window[1]):
            continue
        m = C[:, t]
        uni = _build_uni(m, P[:, t], _v26_for_uni[:, t], top)
        if uni.sum() < 15:
            continue
        sz = np.log(np.where(m > 0, m, np.nan))
        sz_in = sz[uni]
        ok = np.isfinite(sz_in)
        if ok.sum() < 15:
            continue
        # 三档分位
        terciles = np.quantile(sz_in[ok], [1 / 3, 2 / 3])
        big = uni & (sz >= terciles[1])
        mid = uni & (sz >= terciles[0]) & (sz < terciles[1])
        sml = uni & (sz < terciles[0])
        for layer_name, m_idx in [("big", np.where(big)[0]), ("mid", np.where(mid)[0]), ("sml", np.where(sml)[0])]:
            if len(m_idx) < 5:
                continue
            ic_vol = spearman(v13[m_idx, t], fwd[m_idx, t])
            ic_sup = spearman(sup[m_idx, t], fwd[m_idx, t])
            if ic_vol is not None:
                out[f"{layer_name}_vol"].append(ic_vol)
            if ic_sup is not None:
                out[f"{layer_name}_sup"].append(ic_sup)
    return {k: {"n": len(v), "mean": float(np.mean(v)) if v else None} for k, v in out.items()}


def weekly_regression(grid, syms, P, C, v13, sup, top: int, h: int, window: tuple[str, str]):
    """每周横截面回归:forward_h = a + b1·rank(vol13) + b2·rank(supply13) + b3·rank(size) + e。返回三个 β 的样本均值与 t。"""
    T = P.shape[1]
    fwd = np.full_like(P, np.nan)
    fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
    coefs = {"b_vol": [], "b_sup": [], "b_sz": []}
    for t in range(T - h):
        g = grid[t]
        if not (window[0] <= g <= window[1]):
            continue
        m = C[:, t]
        uni = _build_uni(m, P[:, t], _v26_for_uni[:, t], top)
        if uni.sum() < 15:
            continue
        sz = np.log(np.where(m > 0, m, np.nan))
        rv = rank_safe(v13[uni, t])
        rs = rank_safe(sup[uni, t])
        rz = rank_safe(sz[uni])
        X = np.column_stack([rv, rs, rz])
        b_vol, b_sup, b_sz, n = cross_section_regression(fwd[uni, t], X)
        if not math.isnan(b_vol):
            coefs["b_vol"].append(b_vol)
            coefs["b_sup"].append(b_sup)
            coefs["b_sz"].append(b_sz)
    res = {}
    for k, vs in coefs.items():
        if len(vs) >= 5:
            mean, t = boot_t(vs, block=4, seed=108)
            res[k] = {"n": len(vs), "mean": float(mean), "t": float(t)}
    return res


# ── ④ 幸存者 ─────────────────────────────────────────────────────────────────

def survivor_list(dir_: str, grid, syms, dates: list[str]):
    """2020-2023 曾进过 top 50,今天 mcap < $100M 的币。LUNA / UST / FTT / LUNA2 / LUNC 等。"""
    p = json.loads((Path(dir_) / "panel.json").read_text())
    last_iso = dates[-1]
    seen = set()
    for g in grid:
        y = g[:4]
        if y < "2020" or y > "2023":
            continue
        i = bisect.bisect_right(p["dates"], g) - 1
        if i < 0:
            continue
        vals = []
        for s in syms:
            v = p["mcap"][s][i]
            if v:
                vals.append((s, v))
        vals.sort(key=lambda x: -x[1])
        for s, _ in vals[:50]:
            seen.add(s)
    i_last = bisect.bisect_right(p["dates"], last_iso) - 1
    out = {"missing_from_panel": [], "missing_mcap": [], "below_100M": []}
    for s in sorted(seen):
        if s not in p["price"]:
            out["missing_from_panel"].append(s)
            continue
        mc = p["mcap"][s][i_last]
        if mc is None:
            out["missing_mcap"].append(s)
            continue
        if mc < 100e6:
            out["below_100M"].append((s, round(mc / 1e6, 1)))
    return out


# ── ⑤ 分年份 combo IC ────────────────────────────────────────────────────────

def yearly_combo(grid, syms, P, C, v13, sup, top: int, h: int, base_window: tuple[str, str]):
    T = P.shape[1]
    fwd = np.full_like(P, np.nan)
    fwd[:, : T - h] = P[:, h:] / P[:, : T - h] - 1
    buckets = {"2020": [], "2021": [], "2022": [], "2023": [], "2024": [], "2025": [], "2026": []}
    for t in range(T - h):
        g = grid[t]
        if not (base_window[0] <= g <= base_window[1]):
            continue
        y = g[:4]
        if y not in buckets:
            continue
        m = C[:, t]
        uni = _build_uni(m, P[:, t], _v26_for_uni[:, t], top)
        if uni.sum() < 10:
            continue
        sz = np.log(np.where(m > 0, m, np.nan))
        ic = spearman(combo_z(v13[uni, t], sup[uni, t], sz[uni]), fwd[uni, t])
        if ic is None:
            continue
        buckets[y].append(ic)
    return {y: {"n": len(v), "mean": float(np.mean(v)) if v else None} for y, v in buckets.items()}


# ── main ─────────────────────────────────────────────────────────────────────

def main(dir_: str, out_path: str | None = None) -> dict[str, Any]:
    global _v26_for_uni, _v13_for_uni, _sup_for_uni
    grid, syms, P, C, v4, v13, v26, sup = build_panel(dir_)
    _v26_for_uni = v26
    _v13_for_uni = v13
    _sup_for_uni = sup
    dates = json.loads((Path(dir_) / "panel.json").read_text())["dates"]
    res: dict[str, Any] = {"window": HOLDOUT, "n_symbols_eligible": len(syms), "n_weeks": len(grid)}

    # ── ① 双重排序(h=13 周,S-587 留出段 4-13 周最强)
    res["double_sort_top50_h13"] = double_sort_by_size(grid, syms, P, C, v13, sup, top=50, h=13, window=HOLDOUT)
    # ── ① 横截面回归(h=4 与 h=13 都报)
    res["weekly_regression_top50"] = {
        "h4": weekly_regression(grid, syms, P, C, v13, sup, top=50, h=4, window=HOLDOUT),
        "h13": weekly_regression(grid, syms, P, C, v13, sup, top=50, h=13, window=HOLDOUT),
    }

    # ── ② 宇宙放宽
    res["universe_relaxation"] = {}
    for top in (50, 100, 150):
        out = {}
        for h in (4, 13):
            ics = collect_combo_ics(grid, syms, P, C, v13, sup, top=top, h=h, window=HOLDOUT)
            if len(ics) >= 10:
                mean, t = boot_t([x for _, x in ics], block=4, seed=108)
                out[f"h{h}"] = {"n": len(ics), "ic": float(mean), "t": float(t)}
        res["universe_relaxation"][f"top{top}"] = out

    # ── ③ 换波动窗口
    res["vol_window_switch_top13_h4"] = {}
    res["vol_window_switch_top13_h13"] = {}
    for name, v_data in (("vol4", v4), ("vol13", v13), ("vol26", v26)):
        out_h4 = {}
        out_h13 = {}
        for h in (4, 13):
            ics = collect_single_ics(grid, syms, P, C, v_data, top=50, h=h, window=HOLDOUT)
            if len(ics) >= 10:
                mean, t = boot_t([x for _, x in ics], block=4, seed=108)
                if h == 4:
                    out_h4 = {"n": len(ics), "ic": float(mean), "t": float(t)}
                else:
                    out_h13 = {"n": len(ics), "ic": float(mean), "t": float(t)}
        res["vol_window_switch_top13_h4"][name] = out_h4
        res["vol_window_switch_top13_h13"][name] = out_h13

    # ── ④ 幸存者
    res["survivors"] = survivor_list(dir_, grid, syms, dates)

    # ── ⑤ 分年 combo IC(top 50,h=4 与 h=13)
    res["yearly_combo_top50"] = {
        "h4": yearly_combo(grid, syms, P, C, v13, sup, top=50, h=4, base_window=("2020-01-01", "2026-09-25")),
        "h13": yearly_combo(grid, syms, P, C, v13, sup, top=50, h=13, base_window=("2020-01-01", "2026-09-25")),
    }

    if out_path:
        Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    r = main(args[0], args[1] if len(args) > 1 else None)
    print("== HOLDOUT", r["window"], "n_symbols", r["n_symbols_eligible"])
    print("\n① 双重排序(top 50, h=13,vol13 与 supply13 各档 IC):")
    for k, v in r["double_sort_top50_h13"].items():
        if v["n"] >= 10:
            print(f"  {k:8s}  n {v['n']:4d}  IC {v['mean']:+.4f}")
    print("\n① 周频横截面回归(top 50):")
    for hk in ("h4", "h13"):
        print(f"  {hk}:")
        for k, v in r["weekly_regression_top50"][hk].items():
            print(f"    {k:6s}  n {v['n']:4d}  β̄ {v['mean']:+.4f}  t {v['t']:+.2f}")
    print("\n② 宇宙放宽(combo IC):")
    for top, out in r["universe_relaxation"].items():
        print(f"  {top}:")
        for hk, v in out.items():
            print(f"    {hk}  n {v['n']:4d}  IC {v['ic']:+.4f}  t {v['t']:+.2f}")
    print("\n③ 换波动窗口(top 50):")
    for hk, row in [("h4", r["vol_window_switch_top13_h4"]), ("h13", r["vol_window_switch_top13_h13"])]:
        print(f"  {hk}:")
        for sig_name, v in row.items():
            if v:
                print(f"    {sig_name:6s}  n {v['n']:4d}  IC {v['ic']:+.4f}  t {v['t']:+.2f}")
    print("\n④ 幸存者(2020-2023 top 50,今天 mcap < $100M 或缺失):")
    print(f"  panel 缺: {r['survivors']['missing_from_panel']}")
    print(f"  mcap = None: {r['survivors']['missing_mcap']}")
    print(f"  mcap < $100M: {[s for s, _ in r['survivors']['below_100M']]}")
    print(f"  总: {len(r['survivors']['missing_from_panel']) + len(r['survivors']['missing_mcap']) + len(r['survivors']['below_100M'])} 个")
    print("\n⑤ 分年 combo IC(top 50):")
    for hk in ("h4", "h13"):
        print(f"  {hk}:")
        for y, v in r["yearly_combo_top50"][hk].items():
            if v["n"] >= 3:
                print(f"    {y}  n {v['n']:4d}  IC̄ {v['mean']:+.4f}")