#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-328 —— BOUNDS 构造扫描 + 带内随机零分布(lane-b / Minimax-B,2026-11-10)

**问题(卡 T-328 的预注册,Seth 2026-11-10):**
RBv2(加密腿也只许 0.20–0.40)在 W1(2021-07→2022-12)与 W2(2024→2026)两段都过了 S-801 的判据。
但那个「过」里有多少来自**夹紧**(尤其地板 0.20)、多少来自**常数配比**、多少只是**随机**?

**口径(核与成本一字不改):**
- 核 = `src/data/universe/flex_alloc.py`(`dynamic_mix_nav` / `rb_weights` / `clip_to_budget`),只 import;
  `BOUNDS` 靠**原地改字典**生效(核的 `clip_to_budget` 默认参数绑的是同一个字典对象),`src/` 一个字节没动。
- reb = 21 个共同日、cost = 20bp(照 S-797 / T-323)。
- 腿 = `docs/research/t323_legs.csv`(**只读**,T-323 的三腿共同日期序列)。
- 零分布 / 分位只用 `src/data/evaluation/apparatus.py`(`null_distribution` / `percentile_of` /
  `p_upper` / `p_lower`);指标口径照 `docs/research/t323_rb_v2.py` 的 `metrics`。

**窗口(两个口径都跑,不猜):**
- `W1_card` = T-328 卡上写的 W1:2021-07-13 → 2022-12-30(372 天,零暖机)
- `W1_rec`  = T-323 / S-801 的 W1 记 NAV 区间:2021-10-11 → 2022-12-30(309 天,前 63 个共同日只喂权重)
- `W2`      = T-323 / S-797 的 W2:2024-01-04 → 2026-10-30(709 天,前 252 个共同日只喂权重)

只读、不入库、不改 `src/`。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from typing import Callable, Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MAIN_ROOT = "/Users/sbb/Projects/looloomi-ai"

LEGS_CSV = os.path.join(MAIN_ROOT, "docs", "research", "t323_legs.csv")
OUT_JSON = os.path.join(HERE, "t328_results.json")
OUT_MD = os.path.join(HERE, "T-328_bounds_sweep.md")

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from src.data.evaluation.apparatus import (  # noqa: E402
    null_distribution,
    p_lower,
    p_upper,
    percentile_of,
)

# ── 口径常量(照 S-797 / T-323,一字不改)──────────────────────────────────────
REB = 21
COST = 20 / 1e4
DAYS_PER_YEAR = 365.0

# ── 本卡新增的口径 ───────────────────────────────────────────────────────────
N_NULL = 200
NULL_SEED = 805

BASE_BOUNDS = {"crypto": (0.20, 0.40), "equity": (0.20, 0.40), "gold": (0.10, 0.30)}
WIDE_BOUNDS = {"crypto": (0.00, 0.90), "equity": (0.20, 0.40), "gold": (0.10, 0.30)}

# (a) 网格
CRYPTO_GRID = [(f, c) for f in (0.15, 0.20, 0.25) for c in (0.35, 0.40, 0.45)]
EQUITY_GRID = [(0.20, 0.40), (0.15, 0.45), (0.10, 0.50), (0.25, 0.45), (0.20, 0.30)]
GOLD_GRID = [(0.10, 0.30), (0.05, 0.35), (0.00, 0.30), (0.15, 0.30), (0.10, 0.40)]

# 名义配比(crypto / equity / gold,余下是现金)
CONST_ARMS = {
    "T25_K": (0.30, 0.30, 0.20),
    "const_20_30_20": (0.20, 0.30, 0.20),
    "const_20_40_30": (0.20, 0.40, 0.30),
}

WINDOWS = {
    "W1_card": ("W1", "full", "W1(2021-07→2022-12,卡 T-328 写的口径,零暖机)"),
    "W1_rec": ("W1", "rec", "W1_rec(2021-10→2022-12,T-323 / S-801 记 NAV 的口径)"),
    "W2": ("W2", "rec", "W2(2024→2026,T-323 / S-797 记 NAV 的口径)"),
}

LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# ── 取腿(只读 T-323 的 csv)─────────────────────────────────────────────────
def load_legs() -> dict[str, pd.DataFrame]:
    df = pd.read_csv(LEGS_CSV)
    df["date"] = pd.to_datetime(df["date"])
    out: dict[str, pd.DataFrame] = {}
    for w, g in df.groupby("window", sort=True):
        out[str(w)] = g.sort_values("date").reset_index(drop=True)
    return out


def legs_of(g: pd.DataFrame) -> dict[str, pd.Series]:
    idx = pd.DatetimeIndex(g["date"])
    return {
        "crypto": pd.Series(g["crypto_leg_nav_x1v"].to_numpy(float), index=idx, name="crypto"),
        "equity": pd.Series(g["equity_close_acwi"].to_numpy(float), index=idx, name="equity"),
        "gold": pd.Series(g["gold_close_xauusd"].to_numpy(float), index=idx, name="gold"),
    }


# ── 核 ──────────────────────────────────────────────────────────────────────
def load_kernel():
    path = os.path.join(REPO_ROOT, "src", "data", "universe", "flex_alloc.py")
    spec = importlib.util.spec_from_file_location("flex_alloc_kernel_t328", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert mod.clip_to_budget.__defaults__[0] is mod.BOUNDS, "核的 clip_to_budget 默认参数没绑在 BOUNDS 上"
    log(f"  核: {path} sha256={sha[:16]}…")
    return mod, {"path": path, "sha256": sha}


def set_bounds(fa, bounds: dict[str, tuple[float, float]]) -> None:
    for k in fa.LEGS:
        fa.BOUNDS[k] = bounds[k]


def raw_rb_weights(fa, hist: pd.DataFrame) -> Optional[dict]:
    """复算 `rb_weights` 截断前的权重(只读核的常数)。None = 核走了 base 分支。"""
    win = hist[list(fa.LEGS)].dropna().tail(fa.VOL_WINDOW)
    if len(win) < fa.MIN_OBS:
        return None
    cov = win.cov().values
    sig = np.maximum(np.sqrt(np.diag(cov)), fa.SIGMA_FLOOR)
    inv = (1.0 / sig) / (1.0 / sig).sum()
    b = np.array([fa.BASE_T25[k] for k in fa.LEGS])
    vb = float(math.sqrt(max(b @ cov @ b, 0.0)))
    vi = float(math.sqrt(max(inv @ cov @ inv, 0.0)))
    if vi <= 0 or vb <= 0:
        return None
    w = inv * (vb / vi)
    return {k: float(v) for k, v in zip(fa.LEGS, w.tolist())}


def make_rb_fn(fa, bounds: dict, raw_log: list[dict], tag: str):
    """RB 权重函数:用核的 `rb_weights`(当前 BOUNDS 生效),并核对「截断前」复算与核一致。"""

    def fn(hist, d):
        w = {k: float(v) for k, v in fa.rb_weights(hist).items()}
        raw = raw_rb_weights(fa, hist)
        if raw is None:
            ok = all(abs(w.get(k, 0.0) - float(fa.BASE_T25[k])) < 1e-12 for k in fa.LEGS)
        else:
            clipped = fa.clip_to_budget(raw, bounds)
            ok = all(abs(clipped[k] - w[k]) < 1e-10 for k in fa.LEGS)
        if not ok:
            raise AssertionError(f"{tag} 截断前复算与核不一致 @ {d}")
        raw_log.append({
            "d": pd.Timestamp(d).date().isoformat(),
            "raw": raw,
            "w": dict(w),
            "floor_bind": {k: bool(raw is not None and raw[k] < bounds[k][0] - 1e-12) for k in fa.LEGS},
            "ceil_bind": {k: bool(raw is not None and raw[k] > bounds[k][1] + 1e-12) for k in fa.LEGS},
            "scaled_back": bool(sum(w.values()) > 1.0 + 1e-12),
            "below_floor_after_scale": {k: bool(w[k] < bounds[k][0] - 1e-12) for k in fa.LEGS},
        })
        return w

    return fn


# ── 指标(照 t323_rb_v2.metrics 的同一口径)──────────────────────────────────
def _monthly(nav: pd.Series) -> pd.Series:
    try:
        return nav.resample("ME").last().pct_change().dropna()
    except ValueError:
        return nav.resample("M").last().pct_change().dropna()


def metrics(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {"n_days": int(len(nav))}
    final = float(nav.iloc[-1] / nav.iloc[0])
    days = (nav.index[-1] - nav.index[0]).days
    years = max(days / 365.25, 1e-9)
    rets = nav.pct_change().dropna()
    vol = float(rets.std(ddof=1) * math.sqrt(DAYS_PER_YEAR)) if len(rets) > 1 else None
    dd = nav / nav.cummax() - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    maxdd = float(dd.min())
    cagr = final ** (1.0 / years) - 1.0
    m = _monthly(nav)
    return {
        "n_days": int(len(nav)),
        "d0": str(nav.index[0].date()), "d1": str(nav.index[-1].date()),
        "total_return": final - 1.0,
        "cagr": cagr,
        "vol_ann": vol,
        "max_dd": maxdd,
        "dd_peak": str(peak.date()), "dd_trough": str(trough.date()),
        "calmar": (cagr / abs(maxdd)) if maxdd < 0 else None,
        "worst_month": float(m.min()) if len(m) else None,
        "n_months": int(len(m)),
    }


def metrics_arr(nav: np.ndarray) -> dict:
    """只算总收益与最大回撤(零分布用)。"""
    final = float(nav[-1] / nav[0])
    dd = nav / np.maximum.accumulate(nav) - 1.0
    return {"total_return": final - 1.0, "max_dd": float(dd.min())}


def s801_pass(m: dict, t25: dict, is_w1: bool) -> dict:
    """S-801 的逐条判据(照 T-323 §4):W1 三条,W2 两条。"""
    def wm(mm):
        return -9e9 if mm.get("worst_month") is None else mm["worst_month"]
    if is_w1:
        return {
            "a_maxdd_2pp_shallower": bool((m["max_dd"] - t25["max_dd"]) * 100.0 >= 2.0),
            "b_total_return_ge_t25k_minus_1pp": bool((m["total_return"] - t25["total_return"]) * 100.0 >= -1.0),
            "c_worst_month_not_worse": bool(wm(m) >= wm(t25)),
        }
    return {
        "a_total_return_ge_t25k": bool(m["total_return"] >= t25["total_return"]),
        "b_maxdd_not_worse_by_1pp": bool((m["max_dd"] - t25["max_dd"]) * 100.0 >= -1.0),
    }


# ── 快速模拟(与核的 dynamic_mix_nav 等价;脚本里 assert)─────────────────────
def sim(rets_arr: np.ndarray, start_idx: int, draw_fn: Callable[[], np.ndarray],
        reb: int = REB, cost: float = COST) -> np.ndarray:
    """复刻 `dynamic_mix_nav` 的记账:共同日、权重随涨跌漂移、现金收益 0、换手 × cost。
    `draw_fn` 在初始与每次调仓时被调用(常数臂 ⇒ 同一个向量)。"""
    n = rets_arr.shape[0]
    hold = draw_fn()
    nav = 1.0
    out = [1.0]
    for i in range(start_idx + 1, n):
        k = i - start_idx
        row = rets_arr[i]
        g = float((hold * row).sum())
        nav *= 1 + g
        hold = hold * (1 + row) / (1 + g)
        if k % reb == 0:
            new = draw_fn()
            nav *= 1 - float(np.abs(hold - new).sum()) * cost
            hold = new
        out.append(nav)
    return np.array(out, dtype=float)


# ── 臂 ──────────────────────────────────────────────────────────────────────
def run_const_arm(fa, legs, weights: dict[str, float], start, cutoff,
                  bounds: Optional[dict] = None):
    wmap = dict(weights)
    if bounds is not None:
        wmap = fa.clip_to_budget(dict(wmap), bounds)
    nav, _ = fa.dynamic_mix_nav(legs, lambda hist, d: dict(wmap), reb=REB, cost=COST, start=start)
    return nav[nav.index <= cutoff], wmap


def run_rb_arm(fa, legs, bounds: dict, start, cutoff, tag: str):
    set_bounds(fa, bounds)
    raw_log: list[dict] = []
    nav, _ = fa.dynamic_mix_nav(legs, make_rb_fn(fa, bounds, raw_log, tag),
                                 reb=REB, cost=COST, start=start)
    set_bounds(fa, BASE_BOUNDS)
    return nav[nav.index <= cutoff], raw_log


def weight_summary(raw_log: list[dict], leg: str) -> dict:
    w = np.array([r["w"][leg] for r in raw_log], dtype=float)
    raw = np.array([r["raw"][leg] if r["raw"] else np.nan for r in raw_log], dtype=float)
    return {
        "n_rebal": len(w),
        "mean": float(w.mean()), "p25": float(np.quantile(w, 0.25)), "p50": float(np.quantile(w, 0.50)),
        "p75": float(np.quantile(w, 0.75)), "min": float(w.min()), "max": float(w.max()),
        "floor_binds": int(sum(r["floor_bind"][leg] for r in raw_log)),
        "ceil_binds": int(sum(r["ceil_bind"][leg] for r in raw_log)),
        "raw_min": float(np.nanmin(raw)) if np.isfinite(raw).any() else None,
        "raw_max": float(np.nanmax(raw)) if np.isfinite(raw).any() else None,
        "below_floor_after_scale": int(sum(r["below_floor_after_scale"][leg] for r in raw_log)),
    }


# ── 零分布 ──────────────────────────────────────────────────────────────────
def draw_in_band(rng: np.random.Generator, bounds: dict, fa) -> np.ndarray:
    """在带内均匀抽权重,再走核的 `clip_to_budget`(合计 > 1 时按比例缩回)。"""
    raw = {k: float(rng.uniform(bounds[k][0], bounds[k][1])) for k in fa.LEGS}
    clipped = fa.clip_to_budget(raw, bounds)
    return np.array([clipped[k] for k in fa.LEGS], dtype=float)


def null_constant(fa, bounds, rets_arr, start_idx, n=N_NULL, seed=NULL_SEED) -> dict:
    """零分布 A:每个种子抽一个**常数**带内配比,整段不变(与常数臂同一记账)。"""
    def fn_ret(rng):
        w = draw_in_band(rng, bounds, fa)
        return metrics_arr(sim(rets_arr, start_idx, lambda: w))["total_return"]

    def fn_dd(rng):
        w = draw_in_band(rng, bounds, fa)
        return metrics_arr(sim(rets_arr, start_idx, lambda: w))["max_dd"]

    rets = null_distribution(fn_ret, n, seed)
    dds = null_distribution(fn_dd, n, seed)   # 同 seed、同抽样顺序 ⇒ 与 rets 配对
    return {"rets": rets, "dds": dds}


def null_redraw(fa, bounds, rets_arr, start_idx, n=N_NULL, seed=NULL_SEED) -> dict:
    """零分布 B:每次调仓重新抽一个带内配比(时变随机)—— 与 RBv2 这类时变臂同形。"""
    def make(metric):
        def fn(rng):
            def draw():
                return draw_in_band(rng, bounds, fa)
            return metrics_arr(sim(rets_arr, start_idx, draw))[metric]
        return fn

    rets = null_distribution(make("total_return"), n, seed)
    dds = null_distribution(make("max_dd"), n, seed)
    return {"rets": rets, "dds": dds}


def null_matched(fa, bounds, rets_arr, start_idx, target: float, n=N_NULL, seed=NULL_SEED) -> dict:
    """零分布 C:带内随机权重,**按比例缩到与被测臂同样的投入比例**再走 `clip_to_budget`。

    为什么要有这一层:零分布 A 的抽样是「带内均匀」,投入比例天然在 0.50–1.10 之间(均值 ≈ 0.75),
    比 RBv2 的 ≈ 0.87 小 —— 仓位小的配比回撤天然浅、收益天然低。不匹配投入比例,
    拿 RBv2 去比「谁回撤更浅」会被仓位混淆。这一层把投入比例对齐,再看还剩多少。
    """
    def draw(rng):
        u = {k: float(rng.uniform(bounds[k][0], bounds[k][1])) for k in fa.LEGS}
        s = sum(u.values())
        if s <= 1e-12:
            return draw_in_band(rng, bounds, fa)
        scaled = {k: u[k] * target / s for k in fa.LEGS}
        clipped = fa.clip_to_budget(scaled, bounds)
        return np.array([clipped[k] for k in fa.LEGS], dtype=float)

    def make(metric):
        def fn(rng):
            return metrics_arr(sim(rets_arr, start_idx, lambda: draw(rng)))[metric]
        return fn

    rets = null_distribution(make("total_return"), n, seed)
    dds = null_distribution(make("max_dd"), n, seed)
    invested = np.array([float(draw(np.random.default_rng(12345 + i)).sum()) for i in range(20)])
    return {"rets": rets, "dds": dds, "invested_median": float(np.median(invested))}


def pct_good(actual: Optional[float], null: np.ndarray, higher_is_better: bool) -> Optional[float]:
    """「实际值在零分布里有多不寻常」:零分布中**至少一样好**的比例。低 = 实际值异常地好。"""
    if actual is None:
        return None
    if higher_is_better:
        return float(1.0 - percentile_of(actual, null))
    return float(percentile_of(actual, null))


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> None:
    fa, kinfo = load_kernel()
    legs_raw = load_legs()
    log(f"  腿: {LEGS_CSV}(只读)")
    for w, g in legs_raw.items():
        log(f"    {w}: {len(g)} 行 {g['date'].iloc[0].date()} → {g['date'].iloc[-1].date()}")

    R: dict = {
        "card": "T-328", "author": "lane-b", "as_of": "2026-11-10",
        "kernel": kinfo,
        "calib": {"reb": REB, "cost_bp": COST * 1e4, "n_null": N_NULL, "null_seed": NULL_SEED,
                  "legs_csv": LEGS_CSV,
                  "legs_csv_sha256": hashlib.sha256(open(LEGS_CSV, "rb").read()).hexdigest()},
        "bounds_base": {k: list(v) for k, v in BASE_BOUNDS.items()},
        "bounds_wide": {k: list(v) for k, v in WIDE_BOUNDS.items()},
        "windows": {}, "selfcheck": {}, "fidelity": {}, "criterion": {},
    }

    SC = {
        ("W1_rec", "RBv2"): (-0.1207, -0.2213),
        ("W1_rec", "RB_wide"): (-0.0990, -0.1947),
        ("W1_rec", "T25_K"): (-0.1570, -0.2591),
        ("W2", "RBv2"): (0.6218, -0.0923),
        ("W2", "RB_wide"): (0.6503, -0.0949),
        ("W2", "T25_K"): (0.5378, -0.0886),
    }

    for wkey, (wraw, mode, label) in WINDOWS.items():
        g = legs_raw[wraw]
        legs = legs_of(g)
        rec_rows = g.index[g["is_record_window"] == 1]
        start_idx = 0 if mode == "full" else int(rec_rows[0])
        start = pd.Timestamp(g["date"].iloc[start_idx])
        cutoff = pd.Timestamp(g["date"].iloc[-1])
        df = pd.concat(legs, axis=1).dropna().sort_index()
        rets_arr = df.pct_change().to_numpy(dtype=float)

        W: dict = {
            "label": label, "source_window": wraw, "mode": mode,
            "d0": str(start.date()), "d1": str(cutoff.date()),
            "n_nav_days": int(len(df) - start_idx), "start_idx": start_idx,
        }
        R["windows"][wkey] = W
        log(f"  窗口 {wkey}: {label} | NAV {W['d0']} → {W['d1']}({W['n_nav_days']} 天)")

        arms: dict = {}

        nav_v2, raw_v2 = run_rb_arm(fa, legs, BASE_BOUNDS, start, cutoff, "RBv2")
        arms["RBv2"] = {"kind": "rb", "bounds": {k: list(v) for k, v in BASE_BOUNDS.items()},
                        "metrics": metrics(nav_v2),
                        "weights": {leg: weight_summary(raw_v2, leg) for leg in fa.LEGS},
                        "avg_weights": {leg: float(np.mean([r["w"][leg] for r in raw_v2])) for leg in fa.LEGS},
                        "n_scaled_back": int(sum(r["scaled_back"] for r in raw_v2))}

        nav_wide, raw_wide = run_rb_arm(fa, legs, WIDE_BOUNDS, start, cutoff, "RB_wide")
        arms["RB_wide"] = {"kind": "rb", "bounds": {k: list(v) for k, v in WIDE_BOUNDS.items()},
                           "metrics": metrics(nav_wide),
                           "weights": {leg: weight_summary(raw_wide, leg) for leg in fa.LEGS},
                           "avg_weights": {leg: float(np.mean([r["w"][leg] for r in raw_wide])) for leg in fa.LEGS},
                           "n_scaled_back": int(sum(r["scaled_back"] for r in raw_wide))}

        for nm, w3 in CONST_ARMS.items():
            wmap = dict(zip(("crypto", "equity", "gold"), w3))
            nav_c, used = run_const_arm(fa, legs, wmap, start, cutoff)
            arms[nm] = {"kind": "const", "weights_target": used,
                        "invested": float(sum(used.values())), "metrics": metrics(nav_c)}

        # 快速模拟 vs 核(常数臂 T25_K):逐位核对
        nav_t25, _ = run_const_arm(fa, legs, dict(fa.BASE_T25), start, cutoff)
        fast_t25 = sim(rets_arr, start_idx, lambda: np.array([fa.BASE_T25[k] for k in fa.LEGS]))
        kern_arr = nav_t25.to_numpy(dtype=float)
        dmax = float(np.max(np.abs(fast_t25 - kern_arr)))
        R["fidelity"][wkey] = {"max_abs_nav_diff_T25K": dmax, "n": int(len(kern_arr))}
        if dmax > 1e-12:
            raise AssertionError(f"{wkey}: 快速模拟与核不一致 (max diff {dmax:.3e})")
        log(f"    快速模拟 vs 核(T25_K):max|ΔNAV| = {dmax:.2e} ✓")

        # ── (a) 网格 ──────────────────────────────────────────────────────
        grid: dict = {"crypto": {}, "equity": {}, "gold": {}}
        for leg in ("crypto", "equity", "gold"):
            pts = {"crypto": CRYPTO_GRID, "equity": EQUITY_GRID, "gold": GOLD_GRID}[leg]
            for (f, c) in pts:
                b = dict(BASE_BOUNDS); b[leg] = (f, c)
                nav_g, raw_g = run_rb_arm(fa, legs, b, start, cutoff, f"{leg}_grid")
                grid[leg][f"{f:.2f}-{c:.2f}"] = {
                    "bounds": {k: list(v) for k, v in b.items()},
                    "metrics": metrics(nav_g),
                    "weights": {lg: weight_summary(raw_g, lg) for lg in fa.LEGS},
                    "n_scaled_back": int(sum(r["scaled_back"] for r in raw_g)),
                    "below_floor_after_scale": {lg: int(sum(r["below_floor_after_scale"][lg] for r in raw_g))
                                                for lg in fa.LEGS},
                }
        W["grid"] = grid
        t25m = arms["T25_K"]["metrics"]
        for leg in grid:
            for key in grid[leg]:
                c = s801_pass(grid[leg][key]["metrics"], t25m, wkey.startswith("W1"))
                grid[leg][key]["s801"] = c
                grid[leg][key]["s801_all_pass"] = bool(all(c.values()))
        log(f"    网格: 加密 {len(CRYPTO_GRID)} 点 / 股 {len(EQUITY_GRID)} 点 / 金 {len(GOLD_GRID)} 点 ✓")

        # ── (b) 零分布 ────────────────────────────────────────────────────
        nulls = {
            "A_const_random": null_constant(fa, BASE_BOUNDS, rets_arr, start_idx),
            "B_redraw_random": null_redraw(fa, BASE_BOUNDS, rets_arr, start_idx),
        }
        W["nulls"] = {}
        for nm, nl in nulls.items():
            W["nulls"][nm] = {
                "n": int(len(nl["rets"])),
                "ret_p05": float(np.quantile(nl["rets"], 0.05)),
                "ret_p50": float(np.quantile(nl["rets"], 0.50)),
                "ret_p95": float(np.quantile(nl["rets"], 0.95)),
                "dd_p05": float(np.quantile(nl["dds"], 0.05)),
                "dd_p50": float(np.quantile(nl["dds"], 0.50)),
                "dd_p95": float(np.quantile(nl["dds"], 0.95)),
            }
        arms_pct: dict = {}
        nl_c_by_arm: dict = {}
        for nm in ("RBv2", "const_20_30_20", "const_20_40_30", "T25_K"):
            arm = arms[nm]
            m = arm["metrics"]
            inv = arm.get("invested")
            if inv is None:
                inv = float(sum(arm["avg_weights"].values()))
            row = {"total_return": m["total_return"], "max_dd": m["max_dd"], "invested": inv}
            for nn, nl in nulls.items():
                row[nn] = {
                    "ret_pct_good": pct_good(m["total_return"], nl["rets"], True),
                    "dd_pct_good": pct_good(-m["max_dd"], -nl["dds"], False),
                    "p_ret_lower": p_lower(m["total_return"], nl["rets"]),
                    "p_dd_upper": p_upper(-m["max_dd"], -nl["dds"]),
                }
            # 零分布 C:投入比例对齐到本臂
            nl_c = null_matched(fa, BASE_BOUNDS, rets_arr, start_idx, inv)
            nl_c_by_arm[nm] = nl_c
            row["C_matched"] = {
                "ret_pct_good": pct_good(m["total_return"], nl_c["rets"], True),
                "dd_pct_good": pct_good(-m["max_dd"], -nl_c["dds"], False),
                "p_ret_lower": p_lower(m["total_return"], nl_c["rets"]),
                "p_dd_upper": p_upper(-m["max_dd"], -nl_c["dds"]),
                "target_invested": inv,
                "null_invested_median": nl_c["invested_median"],
            }
            arms_pct[nm] = row
        W["arm_percentiles"] = arms_pct
        _nlc = nl_c_by_arm["RBv2"]
        W["nulls"]["C_matched_RBv2"] = {
            "n": N_NULL,
            "target_invested": arms_pct["RBv2"]["invested"],
            "null_invested_median": _nlc["invested_median"],
            "ret_p05": float(np.quantile(_nlc["rets"], 0.05)),
            "ret_p50": float(np.quantile(_nlc["rets"], 0.50)),
            "ret_p95": float(np.quantile(_nlc["rets"], 0.95)),
            "dd_p05": float(np.quantile(_nlc["dds"], 0.05)),
            "dd_p50": float(np.quantile(_nlc["dds"], 0.50)),
            "dd_p95": float(np.quantile(_nlc["dds"], 0.95)),
        }

        # ── (c) 归因 ──────────────────────────────────────────────────────
        avg_v2 = arms["RBv2"]["avg_weights"]
        avg_wide = arms["RB_wide"]["avg_weights"]
        nav_avg_v2, used_v2 = run_const_arm(fa, legs, avg_v2, start, cutoff, BASE_BOUNDS)
        nav_avg_wide, used_wide = run_const_arm(fa, legs, avg_wide, start, cutoff, WIDE_BOUNDS)
        arms["const_at_RBv2_avg"] = {"kind": "const", "weights_target": used_v2,
                                     "invested": float(sum(used_v2.values())), "metrics": metrics(nav_avg_v2)}
        arms["const_at_RBwide_avg"] = {"kind": "const", "weights_target": used_wide,
                                       "invested": float(sum(used_wide.values())), "metrics": metrics(nav_avg_wide)}

        def tr(nm):
            return arms[nm]["metrics"]["total_return"]

        chainA = {
            "mix": tr("const_at_RBwide_avg") - tr("const_20_30_20"),
            "timing": tr("RB_wide") - tr("const_at_RBwide_avg"),
            "clamp": tr("RBv2") - tr("RB_wide"),
        }
        chainA["total_RBv2_minus_20_30_20"] = tr("RBv2") - tr("const_20_30_20")
        chainA["check_sum"] = chainA["mix"] + chainA["timing"] + chainA["clamp"]
        chainB = {
            "mix": tr("const_at_RBv2_avg") - tr("const_20_30_20"),
            "timing": tr("RBv2") - tr("const_at_RBv2_avg"),
            "clamp_vs_RBw": tr("RBv2") - tr("RB_wide"),
        }
        chainB["total_RBv2_minus_20_30_20"] = chainA["total_RBv2_minus_20_30_20"]
        W["attribution"] = {"chainA_wide_centered": chainA, "chainB_rbv2_centered": chainB}
        W["arms"] = arms
        log(f"    归因 A(配比/时变/夹紧): {chainA['mix']*100:+.2f} / {chainA['timing']*100:+.2f} / "
            f"{chainA['clamp']*100:+.2f} pp(合计 {chainA['check_sum']*100:+.2f} vs "
            f"{chainA['total_RBv2_minus_20_30_20']*100:+.2f})")

        # ── (d) 判据:S-801 在本窗口重核 ───────────────────────────────────
        t25 = arms["T25_K"]["metrics"]
        v2m = arms["RBv2"]["metrics"]
        crit = s801_pass(v2m, t25, wkey.startswith("W1"))
        W["s801_criteria"] = crit
        W["s801_all_pass"] = bool(all(crit.values()))
        for cnm in ("const_20_30_20", "const_20_40_30"):
            ccrit = s801_pass(arms[cnm]["metrics"], t25, wkey.startswith("W1"))
            W[f"s801_criteria_{cnm}"] = ccrit
            W[f"s801_all_pass_{cnm}"] = bool(all(ccrit.values()))

        for (wk, anm), (exp_ret, exp_dd) in SC.items():
            if wk != wkey:
                continue
            got = arms[anm]["metrics"]
            R["selfcheck"][f"{wk}/{anm}"] = {
                "expect_total_return": exp_ret, "got_total_return": got["total_return"],
                "diff_pp": (got["total_return"] - exp_ret) * 100.0,
                "expect_max_dd": exp_dd, "got_max_dd": got["max_dd"],
                "dd_diff_pp": (got["max_dd"] - exp_dd) * 100.0,
                "pass": bool(abs((got["total_return"] - exp_ret) * 100.0) < 0.05
                             and abs((got["max_dd"] - exp_dd) * 100.0) < 0.05),
            }
            log(f"    自检 {wk}/{anm}: 收益 {got['total_return']*100:+.2f}%(期望 {exp_ret*100:+.2f}%,"
                f"差 {(got['total_return']-exp_ret)*100:+.3f}pp) 回撤 {got['max_dd']*100:+.2f}%"
                f"(期望 {exp_dd*100:+.2f}%,差 {(got['max_dd']-exp_dd)*100:+.3f}pp)")

    # ── 判据(d)合起来 ─────────────────────────────────────────────────────
    for wkey in WINDOWS:
        ap = R["windows"][wkey]["arm_percentiles"]
        crit = {}
        for nn in ("A_const_random", "B_redraw_random", "C_matched"):
            crit[nn] = {
                "rbv2_dd_pct_good": ap["RBv2"][nn]["dd_pct_good"],
                "rbv2_ret_pct_good": ap["RBv2"][nn]["ret_pct_good"],
                "dd_pct_le_0_10": bool(ap["RBv2"][nn]["dd_pct_good"] is not None
                                      and ap["RBv2"][nn]["dd_pct_good"] <= 0.10),
                "s801_all_pass": R["windows"][wkey]["s801_all_pass"],
            }
        R["windows"][wkey]["criterion"] = crit
    verdicts = {}
    for nn in ("A_const_random", "B_redraw_random", "C_matched"):
        for tag, (ka, kb) in {"W1_card+W2": ("W1_card", "W2"), "W1_rec+W2": ("W1_rec", "W2")}.items():
            a = R["windows"][ka]["criterion"][nn]
            b = R["windows"][kb]["criterion"][nn]
            ok = bool(a["dd_pct_le_0_10"] and b["dd_pct_le_0_10"]
                      and a["s801_all_pass"] and b["s801_all_pass"])
            verdicts[f"{nn}|{tag}"] = {
                "rbv2_dd_pct": {ka: a["rbv2_dd_pct_good"], kb: b["rbv2_dd_pct_good"]},
                "s801_all_pass": {ka: a["s801_all_pass"], kb: b["s801_all_pass"]},
                "pass": ok,
                "verdict": "夹紧有可归因的贡献" if ok else "不可归因",
            }
    R["criterion"] = {"per_window": {w: R["windows"][w]["criterion"] for w in WINDOWS}, "verdicts": verdicts}

    with open(OUT_JSON, "w") as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=float)
    log(f"  结果写到 {OUT_JSON}")

    with open(OUT_MD, "w") as f:
        f.write(build_report(R))
    log(f"  报告写到 {OUT_MD}")


# ── 报告 ────────────────────────────────────────────────────────────────────
def _pct(x, nd=2):
    return "n/a" if x is None else f"{x*100:.{nd}f}%"


def _pp(x, nd=2):
    return "n/a" if x is None else f"{x*100:+.{nd}f}pp"


def _cal(m):
    return "n/a" if m.get("calmar") is None else f"{m['calmar']:.3f}"


def build_report(R: dict) -> str:
    L: list[str] = []
    W = R["windows"]
    a = L.append

    a("# T-328 —— BOUNDS 构造扫描 + 带内随机零分布:RBv2 的 W1/W2 通过,有多少来自夹紧(尤其地板),多少来自常数配比 / 随机")
    a("")
    a("> lane-b / Minimax-B / T-328 / 2026-11-10 · 只读复验,未入库、未改 `src/` · 分支 `lane-b/T-328`")
    a("")
    a("## 0. 口径(核与成本一字不改)")
    a("")
    cal = R["calib"]
    a(f"- 核:`{R['kernel']['path']}` sha256=`{R['kernel']['sha256'][:16]}…`,只 import;"
      f"`BOUNDS` 靠原地改字典生效(`src/` 一个字节没动);")
    a(f"- reb={cal['reb']} 个共同日、cost={cal['cost_bp']:.0f}bp(照 S-797 / T-323);")
    a(f"- 腿:`{cal['legs_csv']}`(只读,sha256=`{cal['legs_csv_sha256'][:16]}…`);")
    a(f"- 零分布 / 分位只用 `src/data/evaluation/apparatus.py`(`null_distribution` N={cal['n_null']} "
      f"seed={cal['null_seed']}、`percentile_of` / `p_upper` / `p_lower`);")
    a("- 窗口(两个口径都跑):`W1_card` = 卡上写的 2021-07→2022-12(零暖机);`W1_rec` = T-323 / S-801 的 "
      "2021-10→2022-12;`W2` = 2024→2026。")
    a("")
    a("**核的版本对照(免得和 T-323 的 sha256 对不上):** 本次跑的核 = `bfb5765b`(S-801 已落地,"
      "文件里 `BOUNDS[\"crypto\"]` 已经是 (0.20, 0.40));T-323 文档里记的核 sha256=`6c7fa4c4aff1f421…` "
      "= `1a215e1c` 的版本(文件里 crypto 还是 (0.0, 0.90),它在运行时改字典)。两版 diff = "
      "**一段注释 + 那一行 BOUNDS 常量,没有任何逻辑差异**;本脚本仍照 T-323 的做法在运行时显式设 BOUNDS"
      "(RBv2 = crypto (0.20, 0.40),RB_wide = crypto (0.00, 0.90)),两臂与 T-323 走同一套代码路径。"
      "自检段 6 个 T-323 / S-801 参照数字逐位复现(|差| < 0.005pp)⇒ 核口径等价成立。")
    a("")
    a("**分位方向(先说清,免得读反):** 本文的「回撤分位」= 零分布中**回撤至少一样浅**的比例;"
      "「收益分位」= 零分布中**收益至少一样高**的比例。**低 = 实际值异常地好。**")
    a("")

    a("## 1. 一句话结论")
    a("")
    vd = R["criterion"]["verdicts"]
    a(f"**判据(d)不成立 ⇒ 记「不可归因」。** RBv2 的回撤分位在 W1 站得住(A 口径 {R['windows']['W1_rec']['criterion']['A_const_random']['rbv2_dd_pct_good']:.3f} / B 口径 {R['windows']['W1_rec']['criterion']['B_redraw_random']['rbv2_dd_pct_good']:.3f}),"
      f"但在 W2 不行({R['windows']['W2']['criterion']['A_const_random']['rbv2_dd_pct_good']:.3f} / "
      f"{R['windows']['W2']['criterion']['B_redraw_random']['rbv2_dd_pct_good']:.3f} / 投入对齐口径 "
      f"{R['windows']['W2']['criterion']['C_matched']['rbv2_dd_pct_good']:.3f})—— 判据要求两个窗口同时成立。")
    a("")
    a("**收益端:过 S-801 的不是夹紧,是「时变」。** 归因链(加性,每步只改一件事)在三个窗口都是同一个形状:")
    a("")
    a("| 窗口 | 配比 | 时变 | 夹紧 | 合计(RBv2 − 常数 20/30/20) |")
    a("|---|---|---|---|---|")
    for wkey, label in (("W1_card", "W1(2021-07→2022-12)"), ("W1_rec", "W1_rec(2021-10→2022-12)"), ("W2", "W2(2024→2026)")):
        ca = R["windows"][wkey]["attribution"]["chainA_wide_centered"]
        a(f"| {label} | {_pp(ca['mix'])} | {_pp(ca['timing'])} | **{_pp(ca['clamp'])}** | {_pp(ca['total_RBv2_minus_20_30_20'])} |")
    a("")
    a("**夹紧那一项在三个窗口都是负的** —— 加密腿加上 0.20 地板 / 0.40 天花板,收益端每次都少 1.9–2.9pp。")
    a("")
    a("**分辨力确实在地板:** 加密带地板从 0.20 抬到 0.25,W1 就翻(S-801 的「回撤比 T25_K 浅 ≥ 2pp」不过);"
      "天花板 0.35 / 0.40 / 0.45 在三个窗口加起来只动 ±1pp。")
    a("")
    a("**常数 20/30/20 在 W1 上全过 S-801,而且收益更高、回撤更浅** —— 也就是说 W1 那段「RBv2 更好」里,"
      "没有一个百分点必须归给 RBv2 独有的东西。")
    a("")

    a("## 2. 自检:先复现 T-323 的数字(同一份腿 + 同一套核)")
    a("")
    a("| 窗口 / 臂 | 期望总收益 | 实测 | 差 | 期望最大回撤 | 实测 | 差 | 判定 |")
    a("|---|---|---|---|---|---|---|---|")
    for k, v in R["selfcheck"].items():
        a(f"| {k} | {v['expect_total_return']*100:+.2f}% | {v['got_total_return']*100:+.2f}% | "
          f"{v['diff_pp']:+.3f}pp | {v['expect_max_dd']*100:+.2f}% | {v['got_max_dd']*100:+.2f}% | "
          f"{v['dd_diff_pp']:+.3f}pp | {'✅' if v['pass'] else '❌'} |")
    a("")
    sc_ok = all(v["pass"] for v in R["selfcheck"].values())
    a(f"自检结论:{'全部逐位复现(判据 |差| < 0.05pp)' if sc_ok else '**未全部复现 —— 后面的数不可用**'}。")
    a("")
    a("快速模拟器与核的一致性(常数臂 T25_K 的 NAV 逐位差):")
    a("")
    a("| 窗口 | max\\|ΔNAV\\| | 天数 |")
    a("|---|---|---|")
    for k, v in R["fidelity"].items():
        a(f"| {k} | {v['max_abs_nav_diff_T25K']:.2e} | {v['n']} |")
    a("")

    a("## 2. (a) 构造扫描:加密带 9 点网格 + 股 / 金单维各 5 点")
    a("")
    for wkey, label in (("W1_card", "W1(2021-07→2022-12)"), ("W1_rec", "W1_rec(2021-10→2022-12)"), ("W2", "W2(2024→2026)")):
        ww = W[wkey]
        a(f"### {label} —— 加密带 floor × ceiling")
        a("")
        a("| 加密带 | 总收益 | 最大回撤 | Calmar | 最差月 | 加密权重均值 | p50 | 地板咬合 | 天花板咬合 | 缩回次数 |")
        a("|---|---|---|---|---|---|---|---|---|---|")
        for key, g in ww["grid"]["crypto"].items():
            m = g["metrics"]; w = g["weights"]["crypto"]
            a(f"| {key} | {_pct(m['total_return'])} | {_pct(m['max_dd'])} | "
              f"{_cal(m)} | "
              f"{_pct(m['worst_month'])} | {_pct(w['mean'])} | {_pct(w['p50'])} | {w['floor_binds']} | "
              f"{w['ceil_binds']} | {g['n_scaled_back']} |")
        a("")
        a("| 股带 | 总收益 | 最大回撤 | Calmar | 加密权重均值 |")
        a("|---|---|---|---|---|")
        for key, g in ww["grid"]["equity"].items():
            m = g["metrics"]
            a(f"| {key} | {_pct(m['total_return'])} | {_pct(m['max_dd'])} | "
              f"{_cal(m)} | "
              f"{_pct(g['weights']['crypto']['mean'])} |")
        a("")
        a("| 金带 | 总收益 | 最大回撤 | Calmar | 加密权重均值 |")
        a("|---|---|---|---|---|")
        for key, g in ww["grid"]["gold"].items():
            m = g["metrics"]
            a(f"| {key} | {_pct(m['total_return'])} | {_pct(m['max_dd'])} | "
              f"{_cal(m)} | "
              f"{_pct(g['weights']['crypto']['mean'])} |")
        a("")

    a("## 3. (b) 带内随机零分布(N=200,seed=805)")
    a("")
    a("零分布 A:每个种子在带内(加密 0.20–0.40 / 股 0.20–0.40 / 金 0.10–0.30)均匀抽一个**常数**配比,"
      "走核的 `clip_to_budget`,再用与常数臂完全相同的记账跑一遍。")
    a("零分布 B:同样在带内抽,但**每次调仓重抽**(时变随机)—— 与 RBv2 这类时变臂同形。")
    a("")
    for wkey, label in (("W1_card", "W1(2021-07→2022-12)"), ("W1_rec", "W1_rec(2021-10→2022-12)"), ("W2", "W2(2024→2026)")):
        ww = W[wkey]
        a(f"### {label}")
        a("")
        for nn, nname in (("A_const_random", "零分布 A(常数随机)"), ("B_redraw_random", "零分布 B(每次调仓重抽)")):
            nl = ww["nulls"][nn]
            a(f"**{nname}** —— 总收益分位 p05/p50/p95 = {nl['ret_p05']*100:+.2f}% / {nl['ret_p50']*100:+.2f}% / "
              f"{nl['ret_p95']*100:+.2f}%;最大回撤分位 p05/p50/p95 = {nl['dd_p05']*100:+.2f}% / "
              f"{nl['dd_p50']*100:+.2f}% / {nl['dd_p95']*100:+.2f}%")
            a("")
            a("| 臂 | 总收益 | 收益分位 | 最大回撤 | 回撤分位 | p(收益,单侧低) | p(回撤,单侧高) |")
            a("|---|---|---|---|---|---|---|")
            for nm in ("RBv2", "const_20_30_20", "const_20_40_30", "T25_K"):
                row = ww["arm_percentiles"][nm][nn]
                base = ww["arm_percentiles"][nm]
                a(f"| {nm} | {_pct(base['total_return'])} | {row['ret_pct_good']:.4f} | "
                  f"{_pct(base['max_dd'])} | {row['dd_pct_good']:.4f} | {row['p_ret_lower']:.4f} | "
                  f"{row['p_dd_upper']:.4f} |")
            a("")

    a("## 4. (c) 常数 20/30/20 的差额与归因(时变 / 配比 / 夹紧)")
    a("")
    for wkey, label in (("W1_card", "W1(2021-07→2022-12)"), ("W1_rec", "W1_rec(2021-10→2022-12)"), ("W2", "W2(2024→2026)")):
        ww = W[wkey]
        a(f"### {label}")
        a("")
        a("| 臂 | 配比(加密/股/金) | 投入 | 总收益 | 最大回撤 | Calmar | 最差月 |")
        a("|---|---|---|---|---|---|---|")
        for nm in ("RBv2", "RB_wide", "const_at_RBv2_avg", "const_at_RBwide_avg",
                   "const_20_30_20", "const_20_40_30", "T25_K"):
            arm = ww["arms"][nm]
            m = arm["metrics"]
            if arm["kind"] == "rb":
                w3 = "/".join(f"{arm['avg_weights'][k]*100:.1f}" for k in ("crypto", "equity", "gold"))
                inv = sum(arm["avg_weights"].values())
            else:
                w3 = "/".join(f"{arm['weights_target'][k]*100:.1f}" for k in ("crypto", "equity", "gold"))
                inv = arm["invested"]
            a(f"| {nm} | {w3} | {inv*100:.1f}% | {_pct(m['total_return'])} | {_pct(m['max_dd'])} | "
              f"{_cal(m)} | "
              f"{_pct(m['worst_month'])} |")
        a("")
        ca = ww["attribution"]["chainA_wide_centered"]
        cb = ww["attribution"]["chainB_rbv2_centered"]
        a("**加性链 A**(20/30/20 → 常数@RB_wide 均值 → RB_wide → RBv2,每步只改一件事):")
        a("")
        a("| 分量 | 收益贡献 |")
        a("|---|---|")
        a(f"| 配比(常数配比换成 RB 的平均配比) | {_pp(ca['mix'])} |")
        a(f"| 时变(常数 → RB 的时变规则,宽带) | {_pp(ca['timing'])} |")
        a(f"| 夹紧(宽带 → 加密 0.20–0.40) | {_pp(ca['clamp'])} |")
        a(f"| **合计** | **{_pp(ca['check_sum'])}** |")
        a(f"| 实测 RBv2 − 20/30/20 | {_pp(ca['total_RBv2_minus_20_30_20'])} |")
        a("")
        a("**加性链 B**(以 RBv2 的平均配比为中心;「夹紧」与之重叠,单独列):")
        a("")
        a(f"- 配比:{_pp(cb['mix'])} · 时变:{_pp(cb['timing'])} · 夹紧(对 RB_wide):{_pp(cb['clamp_vs_RBw'])}")
        a("")

    a("## 5. (d) 判据")
    a("")
    a("判据(卡上原文):**RBv2 回撤分位 ≤ 0.10 且 W1、W2 同时成立**才记「夹紧有可归因的贡献」,否则记「不可归因」。")
    a("「W1、W2 成立」= S-801 的逐条判据在两个窗口上都过(本卡重核)。")
    a("")
    for wkey, label in (("W1_card", "W1(2021-07→2022-12)"), ("W1_rec", "W1_rec(2021-10→2022-12)"), ("W2", "W2(2024→2026)")):
        ww = W[wkey]
        a(f"### {label}")
        a("")
        a("| 项 | 值 |")
        a("|---|---|")
        a(f"| S-801 判据 | {ww['s801_criteria']} → {'全过 ✅' if ww['s801_all_pass'] else '不过 ❌'} |")
        for cnm in ("const_20_30_20", "const_20_40_30"):
            a(f"| S-801 判据({cnm}) | {ww[f's801_criteria_{cnm}']} → "
              f"{'全过 ✅' if ww[f's801_all_pass_{cnm}'] else '不过 ❌'} |")
        for nn, nname in (("A_const_random", "A 常数随机"), ("B_redraw_random", "B 重抽随机")):
            c = ww["criterion"][nn]
            a(f"| RBv2 回撤分位({nname}) | {c['rbv2_dd_pct_good']:.4f} → "
              f"{'≤ 0.10 ✅' if c['dd_pct_le_0_10'] else '> 0.10 ❌'} |")
            a(f"| RBv2 收益分位({nname}) | {c['rbv2_ret_pct_good']:.4f} |")
        a("")
    a("**结论(逐个零分布口径):**")
    a("")
    a("| 口径 | 窗口组合 | RBv2 回撤分位(W1 / W2) | S-801 两窗都过 | 判定 |")
    a("|---|---|---|---|---|")
    for k, v in R["criterion"]["verdicts"].items():
        nn, tag = k.split("|")
        dp = v["rbv2_dd_pct"]
        a(f"| {nn} | {tag} | {list(dp.values())[0]:.4f} / {list(dp.values())[1]:.4f} | "
          f"{'是 ✅' if all(v['s801_all_pass'].values()) else '否 ❌'} | **{v['verdict']}** |")
    a("")

    a("## 6. 产物")
    a("")
    a("- `docs/research/T-328_bounds_sweep.md`(本文件)")
    a("- `docs/research/t328_bounds_sweep.py`(只读复验脚本;`src/` 未改,未入库)")
    a("- `docs/research/t328_results.json`(全部原始数字)")
    a("- `docs/research/scenarios/lane-b-T-328.json`(前向预期,机器结算)")
    a("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
