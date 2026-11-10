#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-329 —— S-805 风险几何第二步:RBv2 之外按事前组合波动收放整体敞口(0.5–1.0,只降不加)。

口径全部照 S-805 预注册原文(S805 常量,check_s805() 与台账逐字比对):
  - 核:`src/data/universe/flex_alloc.py`(只 import,一字不改);RBv2 = 运行时**原地**把
    `BOUNDS["crypto"]` 覆盖成 (0.20, 0.40)(S-801),用完还原,不改 src 的任何字节。
  - 腿:照 T-323(T-321 的 W1 / T-318 的 W2),21 个共同日调仓,20bp 换手。
  - g 层:每 5 个共同日算一次 g = clip(σ★ / σ_ex, 0.5, 1.0);
    σ_ex = 当日 RBv2 权重在最近 63 个共同日协方差下的事前年化波动(只用 ≤ d);
    σ★  = 该臂到当日为止所有 σ_ex 的扩张中位数;前 63 个共同日 g = 1。
    腿的权重 × g,余下现金(收益 0);g 变化的换手同样 × 20bp。
  - 窗口:W1 2021-10-11 → 2022-12-30(① = cap_pit24)、W2 2024-01-04 → 2026-10-30。
  - 对照:RBv2(g ≡ 1)。

只读:不入库、不改 src/、不改任何被跟踪的表结构。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MAIN_ROOT = "/Users/sbb/Projects/looloomi-ai"
DATA_ROOT = "/Volumes/CometCloudAI/cometcloud-local"

OUT_JSON = os.path.join(HERE, "t329_results.json")
OUT_MD = os.path.join(HERE, "T-329_gross_budget.md")
OUT_SCEN = os.path.join(HERE, "scenarios", "lane-a-T-329.json")

REB = 21                      # S-797:21 个共同日调仓(S-805 照抄 S-801)
COST = 20 / 1e4               # S-797:20bp(S-805 照抄 S-801)
DAYS_PER_YEAR = 365.0
AB_MEAN_BLOCK = 20.0          # S-797 预注册的 ab_test 参数,一字不改
AB_N_BOOT = 2000
AB_SEED = 797

# ── S-805 的 g 层参数(逐字照抄预注册)─────────────────────────────────────────
G_CADENCE = 5                 # 每 5 个共同日算一次 g
G_LO, G_HI = 0.5, 1.0         # g = clip(σ★/σ_ex, 0.5, 1.0):只降不加
G_VOL_WINDOW = 63             # σ_ex 的协方差窗口(最近 63 个共同日)
G_WARM_COMMON = 63            # 前 63 个共同日 g = 1

LEGS = ("crypto", "equity", "gold")

# S-805 预注册原文(逐字抄;check_s805() 与 REFUTATION_LEDGER.md 的对应块逐字比对)
S805 = "## S-805 — 高维的风险几何第二步(SPINE 7b「gross_budget = f(相位, 相关性状态)」):RBv2 权重之外,整体敞口按事前波动收放(只降不加,0.5–1.0)—— 预注册(Seth,2026-11-10 16:39 UTC;RBv2 的权重已进真钱,整体敞口一直是 1;交 A 道 T-329)\n**为什么。** S-797 → S-801 的读法:高维给出的可用东西是风险的几何,不是收益的预言。RBv2 只管「三条腿之间怎么分」,不管「整体放多少」—— 而 SPINE 记过:压力天腿间相关从 0.43 升到 0.68,分散在最需要的时候缩水。这一步问:用同一份协方差算出的事前组合波动,在它高于自身常态时把整体敞口降下来,值不值。\n**写死。** 核照 S-801(`flex_alloc.rb_weights`,BOUNDS 加密 / 股 0.20–0.40、金 0.10–0.30,21 个共同日换权重,20bp)。在它之上:每 **5 个共同日**算一次 g = clip(σ★ / σ_ex, **0.5, 1.0**),σ_ex = 当日 RBv2 权重在最近 63 个共同日协方差下的事前年化波动,σ★ = 该臂到当日为止(只用 ≤ d)所有 σ_ex 的**扩张中位数**(前 63 个共同日 g = 1);腿的权重 × g,余下现金(收益 0);g 变化的换手同样 × 20bp。窗口与腿完全同 S-801:W1 2021-10-11 → 2022-12-30(① = `cap_pit24`)、W2 2024-01-04 → 2026-10-30。对照 = RBv2(g ≡ 1)。\n**判(全过才 ✅):** (i) W1 最大回撤比 RBv2 **浅 ≥ 3pp**;(ii) W2 总收益 ≥ RBv2 − 3pp(保险的成本有上限);(iii) W2 Calmar ≥ RBv2;(iv) 两个窗口最差单月都不比 RBv2 差。另报平均 g、g < 1 的天数占比、`apparatus.ab_test` p(只报)、g 与之后 21 天腿间平均相关的关系(描述)。\n**后果:** 全过 ⇒ 提给 Jazz:真钱 T25 在 RBv2 之外加整体敞口收放(只降不加);不过 ⇒ 整体敞口维持 1,7b 的「相关性状态」这一半在 T25 三条腿上没有用。**试验计数:+1。**"

LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# ── 复用 lane-c 的 T-323(腿的装配 / 核 / 指标,一字不改)───────────────────────
def load_t323():
    p = os.path.join(HERE, "t323_rb_v2.py")
    if not os.path.exists(p):
        sys.exit(f"找不到 {p}(T-323 的腿装配),停。")
    spec = importlib.util.spec_from_file_location("t323_rb_v2", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
    log(f"  T-323 模块: {p} sha256={sha[:16]}…")
    return mod


def check_s805() -> dict:
    """核对嵌进报告的 S-805 原文与 REFUTATION_LEDGER.md 逐字一致。"""
    for p in (os.path.join(MAIN_ROOT, "REFUTATION_LEDGER.md"),
              os.path.join(REPO_ROOT, "REFUTATION_LEDGER.md")):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        i = txt.find("## S-805")
        if i < 0:
            continue
        lines = txt[i:].split("\n")
        end = len(lines)
        for k, ln in enumerate(lines):
            if k > 0 and (ln.startswith("## ") or ln.startswith("### ")):
                end = k
                break
        block = "\n".join(lines[:end]).strip()
        return {"ledger_path": p, "match": block == S805.strip(),
                "ledger_lines": end, "ledger_chars": len(block), "embed_chars": len(S805.strip()),
                "ledger_tail": block[-160:], "embed_tail": S805.strip()[-160:],
                "ledger_block": block}
    return {"ledger_path": None, "match": None}


# ── g 层:σ_ex / σ★ / g ───────────────────────────────────────────────────────
class GrossBudget:
    """g 的状态机(纯计算,只吃 ≤ d 的数据)。

    - σ_ex(d, w_rb):当日 RBv2 权重 w_rb 在最近 63 个共同日协方差下的事前年化波动。
    - σ★:该臂到当日为止所有 σ_ex 的扩张中位数(按 sigma_cadence 的节奏累积)。
    - g(d):clip(σ★/σ_ex, 0.5, 1.0);前 63 个共同日 g = 1。
    """

    def __init__(self, rets: pd.DataFrame, *, cadence: int = G_CADENCE,
                 lo: float = G_LO, hi: float = G_HI, vol_window: int = G_VOL_WINDOW,
                 warm: int = G_WARM_COMMON, sigma_cadence: str = "g", disabled: bool = False):
        self.rets = rets
        self.cadence = cadence
        self.lo, self.hi = lo, hi
        self.vol_window = vol_window
        self.warm = warm
        self.sigma_cadence = sigma_cadence   # "g" = 只在 g 日算 σ_ex;("daily" = 每日算)
        self.disabled = disabled             # True = g 层整层关掉(g ≡ 1),自检用
        self.index = {d: i for i, d in enumerate(rets.index)}
        self.sigma_log: list[tuple[pd.Timestamp, float]] = []
        self.g_log: list[dict] = []
        self.g_series: dict[pd.Timestamp, float] = {}

    # 共同日计数(1-based)与「是不是 g 日」──────────────────────────────────────
    def n_common(self, d) -> int:
        return self.index[d] + 1

    def is_g_day(self, d) -> bool:
        if self.disabled:
            return False
        return (self.n_common(d) % self.cadence) == 0

    def sigma_ex(self, d, w_rb: dict) -> float | None:
        win = self.rets.loc[:d, list(LEGS)].dropna().tail(self.vol_window)
        if len(win) < self.vol_window:
            return None
        cov = win.cov().values
        v = np.array([float(w_rb.get(k, 0.0)) for k in LEGS])
        var = float(v @ cov @ v)
        if not math.isfinite(var) or var <= 0:
            return None
        return math.sqrt(var) * math.sqrt(DAYS_PER_YEAR)

    def observe_sigma(self, d, w_rb: dict) -> float | None:
        """(daily 节奏用)把当日 σ_ex 记进扩张中位数的样本池。"""
        sig = self.sigma_ex(d, w_rb)
        if sig is not None:
            self.sigma_log.append((d, sig))
        return sig

    def step(self, d, w_rb: dict, g_cur: float) -> tuple[float, dict]:
        """在 g 日上算新的 g。返回 (g_new, info)。"""
        if self.disabled:
            return g_cur, {"d": d, "g": g_cur, "reason": "disabled(g ≡ 1)"}
        n = self.n_common(d)
        if n <= self.warm:
            return g_cur, {"d": d, "n_common": n, "g": g_cur, "sigma_ex": None,
                           "sigma_star": None, "reason": "前 63 个共同日 g = 1"}
        sig = self.sigma_ex(d, w_rb)
        if sig is None:
            return g_cur, {"d": d, "n_common": n, "g": g_cur, "sigma_ex": None,
                           "sigma_star": None, "reason": "协方差窗口不足 63 个共同日"}
        if self.sigma_cadence == "g":
            self.sigma_log.append((d, sig))
        sstar = float(np.median([s for _, s in self.sigma_log]))
        g_new = float(min(max(sstar / sig, self.lo), self.hi))
        info = {"d": d, "n_common": n, "g": g_new, "sigma_ex": sig, "sigma_star": sstar,
                "n_sigma": len(self.sigma_log), "reason": "ok"}
        self.g_log.append(info)
        return g_new, info


# ── 记账:RBv2 权重 + g 层(与核 `dynamic_mix_nav` 同一套)──────────────────────
def gb_nav(legs: dict, weights_fn, gb: GrossBudget, *, reb: int = REB, cost: float = COST,
           start=None, scale_mode: str = "proportional") -> tuple[pd.Series, list[dict], list[dict]]:
    """返回 (NAV Series, 事件表, 每日 g 序列)。

    记账口径与 `flex_alloc.dynamic_mix_nav` 逐字一致(权重随涨跌漂移、现金收益 0、换手 × cost);
    g ≡ 1 且 scale_mode="proportional" 时,本函数与核的输出逐位相同(自检里断言)。
    scale_mode:
      - "proportional":g 变化时把当前持仓**按比例**缩放(hold × g_new/g_old),换手 = (1−s)·Σ|hold|;
      - "target":g 变化时直接重设到 w_rb × g_new(顺带把 RBv2 的漂移也一起修掉)。
    """
    df = pd.concat({k: v for k, v in legs.items()}, axis=1).dropna().sort_index()
    rets = df.pct_change()
    idx = [d for d in df.index if start is None or d >= start]
    if not idx:
        return pd.Series(dtype=float), [], []
    first = idx[0]
    w0 = {k: float(weights_fn(rets.loc[:first].iloc[1:], first).get(k, 0.0)) for k in LEGS}
    hold = pd.Series(w0)
    g = 1.0
    nav, out = 1.0, {first: 1.0}
    events: list[dict] = []
    g_daily: list[dict] = [{"d": first, "g": 1.0}]
    w_cur = dict(w0)

    for i, d in enumerate(idx[1:], start=1):
        row = rets.loc[d, list(LEGS)]
        gr = float((hold * row).sum())
        nav *= 1 + gr
        hold = hold * (1 + row) / (1 + gr)

        # ── 事件 1:RBv2 调仓(每 reb 个共同日,与核同一节奏)───────────────────
        reb_day = (i % reb == 0)
        w_new = None
        if reb_day:
            w_new = {k: float(weights_fn(rets.loc[:d].iloc[1:], d).get(k, 0.0)) for k in LEGS}

        # ── 事件 2:g(每 cadence 个共同日)────────────────────────────────────
        if gb.sigma_cadence == "daily":
            gb.observe_sigma(d, w_new if w_new is not None else w_cur)
        g_new, ginfo = g, None
        if gb.is_g_day(d):
            g_new, ginfo = gb.step(d, (w_new if w_new is not None else w_cur), g)

        if g_new != g:
            if scale_mode == "target":
                target = pd.Series({k: w_cur[k] * g_new for k in LEGS})
                turn = float((hold - target).abs().sum())
                nav *= 1 - turn * cost
                hold = target.copy()
            else:
                s = g_new / g
                old = hold.copy()
                hold = hold * s
                turn = float((hold - old).abs().sum())
                nav *= 1 - turn * cost
            events.append({"d": str(pd.Timestamp(d).date()), "type": "g",
                           "g_old": g, "g_new": g_new, "turnover": turn,
                           "cost_bp": turn * cost * 1e4, **(ginfo or {})})
            g = g_new
        if reb_day:
            target = pd.Series({k: w_new[k] * g for k in LEGS})
            turn = float((hold - target).abs().sum())
            nav *= 1 - turn * cost
            hold = target.copy()
            w_cur = dict(w_new)
            events.append({"d": str(pd.Timestamp(d).date()), "type": "rebalance", "g": g,
                           "turnover": turn, "cost_bp": turn * cost * 1e4,
                           **{k: round(float(target[k]), 4) for k in LEGS}})
        out[d] = nav
        g_daily.append({"d": d, "g": g})
    return pd.Series(out), events, g_daily


# ── 腿间平均相关(描述用)────────────────────────────────────────────────────
def avg_pair_corr(rets: pd.DataFrame, lo, hi) -> float | None:
    """[lo, hi] 区间内三条腿日收益的平均两两 Pearson 相关。"""
    w = rets.loc[lo:hi, list(LEGS)].dropna()
    if len(w) < 3:
        return None
    cm = w.corr().values
    iu = np.triu_indices(len(LEGS), k=1)
    return float(np.nanmean(cm[iu]))


def mechanism_block(rets_all: pd.DataFrame, gb: GrossBudget, start) -> dict:
    """机制证据:σ_ex 的路径 + 加密腿(X1V)平仓的关系。

    S-801 的结构陷阱在上一级:RBv2 的加密腿在 X1V 空仓时收益恒为 0 ⇒ 它的近 63 日波动塌陷 ⇒
    组合的事前波动 σ_ex **不会**因为「风险最大的那条腿已经离场」而抬高。g 是拿 σ_ex 跟它自己的
    扩张中位数比,所以 σ_ex 不抬头 ⇒ g 不动。这块量的是这条链。
    """
    crypto = rets_all["crypto"]
    flat21 = crypto.rolling(21).apply(lambda x: float((x == 0.0).mean()), raw=True)
    vol63 = crypto.rolling(63).std(ddof=1)
    rows = []
    for info in gb.g_log:
        d = pd.Timestamp(info["d"])
        rows.append({**info,
                     "crypto_flat21": (float(flat21.loc[d]) if d in flat21.index else None),
                     "crypto_vol63": (float(vol63.loc[d]) if d in vol63.index else None)})
    nav_win = rets_all.loc[start:]
    sx = np.array([r["sigma_ex"] for r in rows if r.get("sigma_ex") is not None], dtype=float)
    fl = np.array([r["crypto_flat21"] for r in rows if r.get("crypto_flat21") is not None], dtype=float)
    out = {"sigma_path": rows,
           "crypto_flat_share_nav_window": float((nav_win["crypto"] == 0.0).mean()),
           "crypto_zero_days_nav_window": int((nav_win["crypto"] == 0.0).sum()),
           "n_nav_window_days": int(len(nav_win)),
           "sigma_ex_min": float(sx.min()) if len(sx) else None,
           "sigma_ex_max": float(sx.max()) if len(sx) else None,
           "sigma_ex_median": float(np.median(sx)) if len(sx) else None,
           "sigma_ex_last": float(sx[-1]) if len(sx) else None,
           "corr_sigma_ex_vs_crypto_flat21": (float(np.corrcoef(sx, fl)[0, 1])
                                             if len(sx) > 2 and len(sx) == len(fl) else None)}
    if len(rows):
        # σ_ex 抬得最多的 5 个点:σ_ex 到底有没有在「出事的时候」抬头
        top = sorted([r for r in rows if r.get("sigma_ex") is not None],
                     key=lambda r: -r["sigma_ex"])[:5]
        out["sigma_ex_top5"] = [{"d": r["d"], "sigma_ex": r["sigma_ex"], "g": r["g"],
                                 "crypto_flat21": r.get("crypto_flat21"),
                                 "crypto_vol63": r.get("crypto_vol63")} for r in top]
    return out


def g_vs_corr(rets: pd.DataFrame, g_daily: list[dict], horizon: int = 21) -> dict:
    """g 与「之后 horizon 个共同日的腿间平均相关」的关系(描述)。"""
    idxs = [d for d in rets.index]
    pos = {d: i for i, d in enumerate(idxs)}
    rows = []
    for r in g_daily:
        d = r["d"]
        i = pos.get(d)
        if i is None or i + horizon >= len(idxs):
            continue
        fwd = avg_pair_corr(rets, idxs[i + 1], idxs[i + horizon])
        bwd = avg_pair_corr(rets, idxs[max(i - horizon, 0)], idxs[i])
        if fwd is None:
            continue
        rows.append({"d": d, "g": r["g"], "rho_fwd": fwd, "rho_bwd": bwd})
    if len(rows) < 5:
        return {"n": len(rows), "rows": rows[:50]}
    gv = np.array([r["g"] for r in rows])
    fw = np.array([r["rho_fwd"] for r in rows])
    bw = np.array([r["rho_bwd"] for r in rows])
    lo_mask = gv < 1.0
    out = {
        "n": len(rows), "horizon_days": horizon,
        "corr_g_vs_rho_fwd": float(np.corrcoef(gv, fw)[0, 1]) if len(rows) > 2 else None,
        "corr_g_vs_rho_bwd": float(np.corrcoef(gv, bw)[0, 1]) if len(rows) > 2 else None,
        "mean_rho_fwd_all": float(fw.mean()),
        "mean_rho_fwd_when_g_lt_1": float(fw[lo_mask].mean()) if lo_mask.any() else None,
        "mean_rho_fwd_when_g_eq_1": float(fw[~lo_mask].mean()) if (~lo_mask).any() else None,
        "mean_rho_bwd_all": float(bw.mean()),
        "n_g_lt_1": int(lo_mask.sum()), "n_g_eq_1": int((~lo_mask).sum()),
        "rows": rows[:400],
    }
    return out


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--check", action="store_true", help="只核对 S-805 原文")
    args = ap.parse_args()

    chk = check_s805()
    log(f"  S-805 原文核对: match={chk.get('match')} "
        f"chars={chk.get('ledger_chars')}/{chk.get('embed_chars')}")
    if args.check:
        sys.exit(0 if chk.get("match") else 1)

    t323 = load_t323()
    fa, kinfo = t323.load_kernel()
    trade_path, trade_returns, ab_test = t323.load_tom_and_apparatus()
    log(f"  BASE_T25={fa.BASE_T25} BOUNDS={fa.BOUNDS} VOL_WINDOW={fa.VOL_WINDOW} "
        f"MIN_OBS={fa.MIN_OBS} SIGMA_FLOOR={fa.SIGMA_FLOOR}")

    # 本卡的期望值(S-801 / T-323 的 RBv2 两窗口总收益),对不上先停
    EXPECT = {"W1": -0.1207, "W2": 0.6218}

    results = {
        "card": "T-329", "ledger": "S-805", "author": "lane-a",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kernel": kinfo, "s805_text_check": chk,
        "params": {"REB": REB, "cost_bp": COST * 1e4, "g_cadence": G_CADENCE,
                   "g_clip": [G_LO, G_HI], "sigma_vol_window": G_VOL_WINDOW,
                   "g_warm_common_days": G_WARM_COMMON,
                   "ab_mean_block": AB_MEAN_BLOCK, "ab_n_boot": AB_N_BOOT, "ab_seed": AB_SEED,
                   "scale_mode_primary": "proportional",
                   "scale_mode_sensitivity": "target",
                   "sigma_cadence_primary": "g", "sigma_cadence_sensitivity": "daily"},
        "expect_rbv2_total_return": EXPECT,
        "windows": {},
    }

    windows = {}
    for cfg in (t323.W1, t323.W2):
        log(f"=== {cfg['name']}({cfg['ledger']})===")
        raw = None
        if os.path.exists(cfg["cache"]) and not args.no_cache:
            try:
                raw = json.load(open(cfg["cache"]))
                log(f"  用缓存 {cfg['cache']}")
            except Exception:  # noqa: BLE001
                raw = None
        if raw is None:
            if not t323.URL or not t323.KEY:
                sys.exit("缓存不在且环境里没有 SUPABASE_URL / SUPABASE_KEY,停。")
            raw = t323.fetch_window(cfg)
            try:
                json.dump(raw, open(cfg["cache"], "w"))
                log(f"  缓存写到 {cfg['cache']}")
            except Exception as e:  # noqa: BLE001
                log(f"  缓存写不了(不影响): {e}")

        A = t323.assemble(cfg, raw, trade_path, trade_returns)
        legs, start = A["legs"], A["start"]

        # ── 臂 1:RBv2(S-801 的 BOUNDS['crypto'] = 0.20–0.40),核的 dynamic_mix_nav ──
        fa.BOUNDS["crypto"] = t323.BOUNDS_CRYPTO_V2
        bounds_v2 = dict(fa.BOUNDS)
        raw_v2_log: list[dict] = []
        fn_rb = t323.make_rb_fn(fa, bounds_v2, raw_v2_log, "RBv2")
        nav_rbv2_kernel, log_rbv2 = fa.dynamic_mix_nav(legs, fn_rb, reb=REB, cost=COST, start=start)
        nav_rbv2_kernel = nav_rbv2_kernel[nav_rbv2_kernel.index <= pd.Timestamp(cfg["cutoff"])]

        # ── 自检 A:我的记账循环(g ≡ 1)与核的 dynamic_mix_nav 逐位相同 ─────────
        df_all = pd.concat(legs, axis=1).dropna().sort_index()
        rets_all = df_all.pct_change()
        gb_null = GrossBudget(rets_all, sigma_cadence="g", disabled=True)
        nav_rbv2_mine, _, _ = gb_nav(legs, fn_rb, gb_null, reb=REB, cost=COST, start=start,
                                     scale_mode="proportional")
        nav_rbv2_mine = nav_rbv2_mine[nav_rbv2_mine.index <= pd.Timestamp(cfg["cutoff"])]
        common = nav_rbv2_kernel.index.intersection(nav_rbv2_mine.index)
        max_diff = float((nav_rbv2_kernel.reindex(common) - nav_rbv2_mine.reindex(common)).abs().max())
        m_rbv2 = t323.metrics(nav_rbv2_kernel)
        exp = EXPECT[cfg["name"]]
        diff_pp = (m_rbv2["total_return"] - exp) * 100.0
        sc = {"expect_total_return": exp, "src": "T-323 报告 / S-801",
              "got_total_return": m_rbv2["total_return"], "diff_pp": diff_pp,
              "match": bool(abs(diff_pp) < 0.05),
              "record_window_expect": list(cfg["expect_record"]),
              "record_window_got": [m_rbv2["d0"], m_rbv2["d1"]],
              "window_match": bool(m_rbv2["d0"] == cfg["expect_record"][0]
                                   and m_rbv2["d1"] == cfg["expect_record"][1]),
              "my_loop_vs_kernel_max_abs_nav_diff": max_diff,
              "my_loop_matches_kernel": bool(max_diff < 1e-12)}
        log(f"  自检 {cfg['name']} RBv2 总收益 {m_rbv2['total_return']*100:+.2f}%"
            f"(期望 {exp*100:+.2f}%,差 {diff_pp:+.3f}pp){'✅' if sc['match'] else '❌'};"
            f"区间 {m_rbv2['d0']} → {m_rbv2['d1']}{'✅' if sc['window_match'] else '❌'};"
            f"我的循环 vs 核 max|ΔNAV|={max_diff:.2e}"
            f"{'✅' if sc['my_loop_matches_kernel'] else '❌'}")
        if not (sc["match"] and sc["window_match"] and sc["my_loop_matches_kernel"]):
            sys.exit(f"{cfg['name']} 自检不过,停(先修腿的装配,不要往下跑)。")

        # ── 臂 2:RBv2 + g 层(比例式,主口径)────────────────────────────────
        gb = GrossBudget(rets_all, sigma_cadence="g")
        nav_gb, ev_gb, g_daily = gb_nav(legs, fn_rb, gb, reb=REB, cost=COST, start=start,
                                        scale_mode="proportional")
        nav_gb = nav_gb[nav_gb.index <= pd.Timestamp(cfg["cutoff"])]

        # ── 臂 3(敏感性):目标式 g 变化 ───────────────────────────────────────
        gb_t = GrossBudget(rets_all, sigma_cadence="g")
        nav_gb_t, ev_gb_t, g_daily_t = gb_nav(legs, fn_rb, gb_t, reb=REB, cost=COST, start=start,
                                              scale_mode="target")
        nav_gb_t = nav_gb_t[nav_gb_t.index <= pd.Timestamp(cfg["cutoff"])]

        # ── 臂 4(敏感性):σ_ex 每日算(σ★ 的样本池更密)──────────────────────
        gb_d = GrossBudget(rets_all, sigma_cadence="daily")
        nav_gb_d, ev_gb_d, g_daily_d = gb_nav(legs, fn_rb, gb_d, reb=REB, cost=COST, start=start,
                                              scale_mode="proportional")
        nav_gb_d = nav_gb_d[nav_gb_d.index <= pd.Timestamp(cfg["cutoff"])]

        m_gb, m_gb_t, m_gb_d = t323.metrics(nav_gb), t323.metrics(nav_gb_t), t323.metrics(nav_gb_d)
        h_rbv2, h_gb = t323.half_metrics(nav_rbv2_kernel), t323.half_metrics(nav_gb)

        # ── g 的分布 ─────────────────────────────────────────────────────────
        gser = pd.Series({r["d"]: r["g"] for r in g_daily}).sort_index()
        gser = gser[gser.index >= start]
        n_lt1 = int((gser < 1.0 - 1e-12).sum())
        g_events = [e for e in ev_gb if e["type"] == "g"]
        reb_events = [e for e in ev_gb if e["type"] == "rebalance"]
        g_stats = {
            "mean_g": float(gser.mean()), "min_g": float(gser.min()), "max_g": float(gser.max()),
            "n_days": int(len(gser)), "n_days_g_lt_1": n_lt1,
            "share_days_g_lt_1": float(n_lt1 / max(len(gser), 1)),
            "n_g_events": len(g_events), "n_rebalance_events": len(reb_events),
            "mean_g_at_event_days": float(np.mean([e["g_new"] for e in g_events])) if g_events else None,
            "min_g_at_event_days": float(np.min([e["g_new"] for e in g_events])) if g_events else None,
            "g_change_turnover_sum": float(sum(e["turnover"] for e in g_events)),
            "g_change_cost_bp_sum": float(sum(e["cost_bp"] for e in g_events)),
            "rebalance_cost_bp_sum": float(sum(e["cost_bp"] for e in reb_events)),
            "sigma_ex_first": gb.g_log[0] if gb.g_log else None,
            "sigma_ex_last": gb.g_log[-1] if gb.g_log else None,
            "n_sigma_median_pool": len(gb.sigma_log),
        }
        log(f"  g:平均 {g_stats['mean_g']:.4f} 最小 {g_stats['min_g']:.4f} "
            f"g<1 天数占比 {g_stats['share_days_g_lt_1']*100:.1f}% "
            f"({n_lt1}/{len(gser)});g 事件 {len(g_events)} 次;"
            f"g 换手合计 {g_stats['g_change_turnover_sum']:.4f}"
            f"(成本 {g_stats['g_change_cost_bp_sum']:.1f}bp)")

        # ── ab_test(参数照 S-797 预注册,只报)──────────────────────────────────
        def ab_pair(a_name: str, b_name: str, a: pd.Series, b: pd.Series) -> dict:
            ra, rb_ = a.pct_change().dropna(), b.pct_change().dropna()
            ii = ra.index.intersection(rb_.index)
            out = ab_test(ra.reindex(ii).values, rb_.reindex(ii).values,
                          mean_block=AB_MEAN_BLOCK, n_boot=AB_N_BOOT, seed=AB_SEED)
            out["a"], out["b"] = a_name, b_name
            out["note"] = (f"mean_block={AB_MEAN_BLOCK} / n_boot={AB_N_BOOT} / seed={AB_SEED}"
                           f"(照 S-797 预注册,一字不改);a={a_name}、b={b_name};"
                           f"p_b_le_a = P({b_name} ≤ {a_name})、p_b_ge_a = P({b_name} ≥ {a_name})。只报,不作判据。")
            return out

        ab_gb = ab_pair("RBv2", "GB", nav_rbv2_kernel, nav_gb)
        ab_gb_t = ab_pair("RBv2", "GB_target", nav_rbv2_kernel, nav_gb_t)
        log(f"  ab_test RBv2→GB: p(b≤a)={ab_gb.get('p_b_le_a')} p(b≥a)={ab_gb.get('p_b_ge_a')} "
            f"verdict={ab_gb.get('verdict')} n={ab_gb.get('n_days')}")

        # ── g 与之后 21 天腿间平均相关(描述)──────────────────────────────────
        corr_desc = g_vs_corr(rets_all, g_daily, horizon=21)
        mech = mechanism_block(rets_all, gb, start)
        log(f"  机制:加密腿平仓占比(NAV 窗口){mech['crypto_flat_share_nav_window']*100:.1f}%"
            f"({mech['crypto_zero_days_nav_window']}/{mech['n_nav_window_days']} 天收益恒为 0);"
            f"σ_ex 中位 {mech['sigma_ex_median']:.4f} 最高 {mech['sigma_ex_max']:.4f};"
            f"corr(σ_ex, 加密腿近 21 日平仓占比)={mech['corr_sigma_ex_vs_crypto_flat21']}")

        # ── 判据(S-805)(i)–(iv)───────────────────────────────────────────────
        if cfg["name"] == "W1":
            checks = {
                "i_w1_maxdd_3pp_shallower": {
                    "rule": "(i) W1 最大回撤比 RBv2 浅 ≥ 3pp",
                    "rbv2_max_dd": m_rbv2["max_dd"], "gb_max_dd": m_gb["max_dd"],
                    "gap_pp": (m_gb["max_dd"] - m_rbv2["max_dd"]) * 100.0,
                    "need_pp": 3.0,
                    "pass": bool((m_gb["max_dd"] - m_rbv2["max_dd"]) * 100.0 >= 3.0)},
            }
        else:
            checks = {
                "ii_w2_total_return_ge_rbv2_minus_3pp": {
                    "rule": "(ii) W2 总收益 ≥ RBv2 − 3pp",
                    "rbv2_total_return": m_rbv2["total_return"], "gb_total_return": m_gb["total_return"],
                    "gap_pp": (m_gb["total_return"] - m_rbv2["total_return"]) * 100.0,
                    "need_pp": -3.0,
                    "pass": bool((m_gb["total_return"] - m_rbv2["total_return"]) * 100.0 >= -3.0)},
                "iii_w2_calmar_ge_rbv2": {
                    "rule": "(iii) W2 Calmar ≥ RBv2",
                    "rbv2_calmar": m_rbv2["calmar"], "gb_calmar": m_gb["calmar"],
                    "pass": bool(m_rbv2["calmar"] is not None and m_gb["calmar"] is not None
                                 and m_gb["calmar"] >= m_rbv2["calmar"])},
            }
        # (iv) 两个窗口最差单月都不比 RBv2 差 —— 两个窗口都要跑,最后合判
        checks["iv_worst_month_not_worse"] = {
            "rule": "(iv) 该窗口最差单月 ≥ RBv2 最差单月",
            "rbv2_worst_month": m_rbv2["worst_month"], "gb_worst_month": m_gb["worst_month"],
            "gap_pp": ((m_gb["worst_month"] or 0.0) - (m_rbv2["worst_month"] or 0.0)) * 100.0,
            "pass": bool((m_gb["worst_month"] or 0.0) >= (m_rbv2["worst_month"] or 0.0))}
        for k, c in checks.items():
            log(f"  判据 {k}: {'✅' if c['pass'] else '❌'}")

        windows[cfg["name"]] = {
            "ledger": cfg["ledger"], "warm_days": cfg["warm"], "cutoff": cfg["cutoff"],
            "interval": {"common_dates_total": int(len(df_all)),
                         "first_common_date": str(df_all.index[0].date()),
                         "record_start": str(start.date()), "record_end": str(df_all.index[-1].date()),
                         "n_record_days": int(len(nav_rbv2_kernel))},
            "selfcheck": sc,
            "arms": {"RBv2": m_rbv2, "GB": m_gb, "GB_target_mode": m_gb_t, "GB_daily_sigma": m_gb_d},
            "halves": {"rbv2": h_rbv2, "gb": h_gb},
            "g_stats": g_stats,
            "g_events": g_events[:80],
            "ab_test": {"rbv2_vs_gb": ab_gb, "rbv2_vs_gb_target": ab_gb_t},
            "g_vs_interleg_corr": corr_desc,
            "mechanism": mech,
            "checks": checks,
        }

    # ── (iv) 需要两个窗口都合过;总判据(i)–(iv)全过才 ✅ ─────────────────────
    w1, w2 = windows["W1"], windows["W2"]
    final_checks = {
        "i_w1_maxdd_3pp_shallower": w1["checks"]["i_w1_maxdd_3pp_shallower"],
        "ii_w2_total_return_ge_rbv2_minus_3pp": w2["checks"]["ii_w2_total_return_ge_rbv2_minus_3pp"],
        "iii_w2_calmar_ge_rbv2": w2["checks"]["iii_w2_calmar_ge_rbv2"],
        "iv_w1_worst_month_not_worse": w1["checks"]["iv_worst_month_not_worse"],
        "iv_w2_worst_month_not_worse": w2["checks"]["iv_worst_month_not_worse"],
    }
    n_pass = sum(1 for c in final_checks.values() if c["pass"])
    verdict = {"n_criteria": len(final_checks), "n_pass": n_pass,
               "pass": bool(n_pass == len(final_checks)), "checks": final_checks}
    results["windows"] = windows
    results["verdict"] = verdict
    for k, c in final_checks.items():
        log(f"  ⇒ 判据 {k}: {'✅' if c['pass'] else '❌'}")
    log(f"  ⇒ S-805 总判: {'✅ 过' if verdict['pass'] else '❌ 不过'}({n_pass}/{len(final_checks)} 条)")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    log(f"  写 {OUT_JSON}")
    write_report(results)
    write_scenarios(results)


# ── 报告 ──────────────────────────────────────────────────────────────────────
def _pct(x, nd=2):
    if x is None:
        return "—"
    return f"{x * 100:.{nd}f}%"


def _num(x, nd=3):
    if x is None:
        return "—"
    return f"{x:.{nd}f}"


def write_report(R: dict) -> None:
    w1, w2 = R["windows"]["W1"], R["windows"]["W2"]
    v = R["verdict"]
    chk = R["s805_text_check"]
    L: list[str] = []
    A = L.append

    A("# T-329 / S-805 —— 风险几何第二步:RBv2 之外按事前组合波动收放整体敞口(0.5–1.0,只降不加)")
    A("")
    A("> lane-a / Minimax / T-329 / " + R["generated_at"][:10]
      + " · 只读复验,未入库、未改 `src/` · 分支 `lane-a/T-329`")
    A("")
    A("## 0. S-805 预注册原文(照抄自 `REFUTATION_LEDGER.md`)")
    A("")
    A(f"> 逐字核对:`match = {chk.get('match')}`"
      f"(台账块 {chk.get('ledger_chars')} 字 / 嵌入 {chk.get('embed_chars')} 字,{chk.get('ledger_path')})。")
    A("")
    A(S805.strip())
    A("")
    A("---")
    A("")

    A("## 1. 一句话结论")
    A("")
    A(f"**{'全过 ✅:整体敞口收放可以连同 RBv2 一起摆给 Jazz' if v['pass'] else '不过 ❌:整体敞口维持 1,7b 的这一半在 T25 三条腿上没有用'}**"
      f"({v['n_pass']}/{v['n_criteria']} 条判据过)")
    A("")
    A(f"- W1(2021-10-11 → 2022-12-30,S-799):RBv2 总收益 {_pct(w1['arms']['RBv2']['total_return'])},"
      f"加 g 后 {_pct(w1['arms']['GB']['total_return'])};"
      f"最大回撤 {_pct(w1['arms']['RBv2']['max_dd'])} → {_pct(w1['arms']['GB']['max_dd'])};"
      f"平均 g {_num(w1['g_stats']['mean_g'], 4)},g < 1 的天数占比 "
      f"{_pct(w1['g_stats']['share_days_g_lt_1'], 1)}。")
    A(f"- W2(2024-01-04 → 2026-10-30,S-797):RBv2 总收益 {_pct(w2['arms']['RBv2']['total_return'])},"
      f"加 g 后 {_pct(w2['arms']['GB']['total_return'])};"
      f"最大回撤 {_pct(w2['arms']['RBv2']['max_dd'])} → {_pct(w2['arms']['GB']['max_dd'])};"
      f"Calmar {_num(w2['arms']['RBv2']['calmar'])} → {_num(w2['arms']['GB']['calmar'])};"
      f"平均 g {_num(w2['g_stats']['mean_g'], 4)},g < 1 的天数占比 "
      f"{_pct(w2['g_stats']['share_days_g_lt_1'], 1)}。")
    A("")
    A("**为什么不过(机制,不是调参问题)**:g 拿的是**组合自己的**事前波动 σ_ex 跟它自己的扩张中位数比。"
      "而 σ_ex 是腿的协方差算出来的 —— 加密腿是 X1V,它空仓的日子收益恒为 0、近 63 日波动随之塌陷,"
      f"于是「风险最大的那条腿已经离场」这件事**不会**让 σ_ex 抬头"
      f"(W1 实测 corr(σ_ex, 加密腿近 21 日平仓占比) = "
      f"{_num(w1['mechanism']['corr_sigma_ex_vs_crypto_flat21'])};"
      f"W2 = {_num(w2['mechanism']['corr_sigma_ex_vs_crypto_flat21'])})。"
      f"结果:W1(2022 崩盘段)加密腿有 {_pct(w1['mechanism']['crypto_flat_share_nav_window'], 1)} 的日子是平的、"
      f"σ_ex 最高只到 {_pct(w1['mechanism']['sigma_ex_max'])},g 几乎不动(平均 {_num(w1['g_stats']['mean_g'], 4)}),"
      f"保险在该起作用的地方是**哑的**;W2 反而降得多(平均 g {_num(w2['g_stats']['mean_g'], 4)},"
      f"g 最低 {_num(w2['g_stats']['min_g'], 4)}),把收益、Calmar、最差单月各赔一点,回撤一点没变浅。"
      "这是 S-801「空仓腿看起来低风险」那条结构陷阱在**上一层**的同一个形状 —— 不是这条边的算错了,"
      "是它选的输入测不到它要测的东西。")
    A("")
    A("**对 7b 的后果**:按 S-805 写死的后果条款 —— 不过 ⇒ 整体敞口维持 1,这一半留在纸面。"
      "但要说清楚的是:这**不是**「按事前波动收放整体敞口」这个想法被否掉,是被否掉的是"
      "**用 RBv2 这条臂自己的腿协方差**去算 σ_ex。这条臂的加密腿有一半日子是空的。")
    A("")
    A("")

    A("## 2. 自检(对不上先停)")
    A("")
    A("| 窗口 | RBv2 总收益 | 期望(T-323) | 差 | 记 NAV 区间 | 一致 | 我的循环 vs 核 max\\|ΔNAV\\| |")
    A("|---|---|---|---|---|---|---|")
    for nm, w in (("W1", w1), ("W2", w2)):
        s = w["selfcheck"]
        A(f"| {nm} | {_pct(s['got_total_return'])} | {_pct(s['expect_total_return'])} | "
          f"{s['diff_pp']:+.3f}pp | {s['record_window_got'][0]} → {s['record_window_got'][1]} | "
          f"{'✅' if s['match'] and s['window_match'] else '❌'} | "
          f"{s['my_loop_vs_kernel_max_abs_nav_diff']:.2e}"
          f"{'✅' if s['my_loop_matches_kernel'] else '❌'} |")
    A("")
    A("自检过 ⇒ 后面 RBv2 与 GB 的差只能来自 g 层;「我的循环 vs 核」= 我的记账循环在 g ≡ 1 时"
      "与核 `flex_alloc.dynamic_mix_nav` 逐位相同(记账口径没有偷偷改)。")
    A("")

    A("## 3. g 的机制(测得的)")
    A("")
    A("| 窗口 | 平均 g | 最小 g | g < 1 天数占比 | g 事件数 | g 换手合计 | g 成本 | 调仓成本 |")
    A("|---|---|---|---|---|---|---|---|")
    for nm, w in (("W1", w1), ("W2", w2)):
        gs = w["g_stats"]
        A(f"| {nm} | {_num(gs['mean_g'], 4)} | {_num(gs['min_g'], 4)} | "
          f"{_pct(gs['share_days_g_lt_1'], 1)}({gs['n_days_g_lt_1']}/{gs['n_days']}) | "
          f"{gs['n_g_events']} | {_num(gs['g_change_turnover_sum'], 4)} | "
          f"{_num(gs['g_change_cost_bp_sum'], 1)}bp | {_num(gs['rebalance_cost_bp_sum'], 1)}bp |")
    A("")
    A("σ_ex = 当日 RBv2 权重在最近 63 个共同日协方差下的事前年化波动;σ★ = 该臂到当日为止所有 σ_ex 的扩张中位数;"
      "g = clip(σ★/σ_ex, 0.5, 1.0),每 5 个共同日定一次,只降不加;前 63 个共同日 g = 1。")
    A("")
    A("| 窗口 | 首个 σ_ex(年化) | 末个 σ_ex(年化) | 末个 σ★(年化) | 末个 g |")
    A("|---|---|---|---|---|")
    for nm, w in (("W1", w1), ("W2", w2)):
        gs = w["g_stats"]
        f_, l_ = gs["sigma_ex_first"], gs["sigma_ex_last"]
        A(f"| {nm} | {_pct(f_['sigma_ex']) if f_ else '—'} | {_pct(l_['sigma_ex']) if l_ else '—'} | "
          f"{_pct(l_['sigma_star']) if l_ else '—'} | {_num(l_['g'], 4) if l_ else '—'} |")
    A("")

    A("### 3b. 机制:σ_ex 抬没抬起来(这是 g 为什么不动的原因)")
    A("")
    A("| 窗口 | 加密腿(X1V)平仓占比(NAV 窗口) | σ_ex 中位 | σ_ex 最高 | σ_ex 最低 | corr(σ_ex, 加密腿近 21 日平仓占比) |")
    A("|---|---|---|---|---|---|")
    for nm, w in (("W1", w1), ("W2", w2)):
        m = w["mechanism"]
        A(f"| {nm} | {_pct(m['crypto_flat_share_nav_window'], 1)}"
          f"({m['crypto_zero_days_nav_window']}/{m['n_nav_window_days']} 天) | "
          f"{_pct(m['sigma_ex_median'])} | {_pct(m['sigma_ex_max'])} | {_pct(m['sigma_ex_min'])} | "
          f"{_num(m['corr_sigma_ex_vs_crypto_flat21'])} |")
    A("")
    A("σ_ex 抬得最多的 5 个点(每个窗口):")
    A("")
    for nm, w in (("W1", w1), ("W2", w2)):
        A(f"- **{nm}**:" + "; ".join(
            f"{r['d']} σ_ex={r['sigma_ex']:.4f} g={r['g']:.4f} "
            f"加密腿近 21 日平仓占比={'—' if r.get('crypto_flat21') is None else format(r['crypto_flat21'], '.2f')}"
            for r in w["mechanism"].get("sigma_ex_top5", [])))
    A("")
    A("σ_ex = 当日 RBv2 权重在**腿的**近 63 个共同日协方差下的事前年化波动。加密腿是 X1V —— "
      "它空仓的日子收益恒为 0、近 63 日波动随之塌陷,于是「风险最大的那条腿已经离场」这件事"
      "**不会**让组合的事前波动 σ_ex 抬头。g 是拿 σ_ex 跟它自己的扩张中位数比,所以 σ_ex 不抬头 ⇒ g 不动。"
      "这是 S-801 那条结构陷阱(S-801:空仓腿看起来低风险)在**上一层**的同一个形状。")
    A("")

    A("## 4. 两窗口结果")
    A("")
    for nm, w in (("W1", w1), ("W2", w2)):
        A(f"### {nm}({w['record_start'] if 'record_start' in w else w['interval']['record_start']}"
          f" → {w['interval']['record_end']},{w['ledger']})")
        A("")
        A("| 臂 | 总收益 | 年化 | 最大回撤 | Calmar | 最差月 | 年化波动 |")
        A("|---|---|---|---|---|---|---|")
        for key, label in (("RBv2", "RBv2(g ≡ 1,对照)"), ("GB", "RBv2 + g(主口径,比例式)"),
                           ("GB_target_mode", "RBv2 + g(敏感性:目标式)"),
                           ("GB_daily_sigma", "RBv2 + g(敏感性:σ_ex 每日算)")):
            m = w["arms"][key]
            A(f"| {label} | {_pct(m['total_return'])} | {_pct(m['cagr'])} | {_pct(m['max_dd'])} | "
              f"{_num(m['calmar'])} | {_pct(m['worst_month'])} | {_pct(m['vol_ann'])} |")
        A("")

    A("## 5. 判据(S-805)(i)–(iv)")
    A("")
    A("| 判据 | 规则 | 测得 | 判定 |")
    A("|---|---|---|---|")
    for k, c in v["checks"].items():
        got = ""
        if "gap_pp" in c:
            got = f"差 {c['gap_pp']:+.3f}pp(需要 {c.get('need_pp', '—')})"
        elif "rbv2_calmar" in c:
            got = f"RBv2 {_num(c['rbv2_calmar'])} → GB {_num(c['gb_calmar'])}"
        A(f"| `{k}` | {c['rule']} | {got} | {'✅' if c['pass'] else '❌'} |")
    A("")
    A(f"**总判:{v['n_pass']}/{v['n_criteria']} ⇒ {'✅ 过' if v['pass'] else '❌ 不过'}**")
    A("")

    A("## 6. 另报:ab_test p 与 g 的行为")
    A("")
    for nm, w in (("W1", w1), ("W2", w2)):
        ab = w["ab_test"]["rbv2_vs_gb"]
        A(f"- **{nm} ab_test(RBv2 → GB)**:p(b ≤ a) = {_num(ab.get('p_b_le_a'))}、"
          f"p(b ≥ a) = {_num(ab.get('p_b_ge_a'))}、verdict = {ab.get('verdict')}、"
          f"n = {ab.get('n_days')} 天。(参数 mean_block=20 / n_boot=2000 / seed=797,照 S-797 一字不改;"
          f"只报,不作判据。)")
    A("")
    A("| 窗口 | n | corr(g, 之后 21 天腿间平均相关) | corr(g, 之前 21 天) | 平均 ρ̄(之后) | ρ̄(g<1) | ρ̄(g=1) |")
    A("|---|---|---|---|---|---|---|")
    for nm, w in (("W1", w1), ("W2", w2)):
        cd = w["g_vs_interleg_corr"]
        A(f"| {nm} | {cd.get('n')} | {_num(cd.get('corr_g_vs_rho_fwd'))} | "
          f"{_num(cd.get('corr_g_vs_rho_bwd'))} | {_num(cd.get('mean_rho_fwd_all'), 4)} | "
          f"{_num(cd.get('mean_rho_fwd_when_g_lt_1'), 4)} | {_num(cd.get('mean_rho_fwd_when_g_eq_1'), 4)} |")
    A("")
    A("ρ̄ = 三条腿日收益的平均两两 Pearson 相关;「之后 21 天」= g 定下来之后往后的 21 个共同日"
      "(描述性,不用来下判断)。")
    A("")

    A("## 7. 口径选择与敏感性(预注册里没写死的地方)")
    A("")
    A("S-805 写了 g 的公式、clip 区间、节奏、窗口和成本,但有两处没写死,本卡按下述读法执行并把另一种也跑了:")
    A("")
    A("1. **g 变化时怎么交易**。主口径 = **比例式**:把当前持仓按 g_new/g_old 等比缩放"
      "(换手 = (1−s)·Σ|持仓|,恰好是「g 变化的换手」);敏感性口径 = **目标式**:直接重设到 w_rb × g_new"
      "(顺带把 RBv2 的漂移也一起修掉,换手更大)。选比例式作主口径的理由:预注册写的是「g 变化的换手」"
      "—— 目标式的换手里混着 RBv2 的漂移修正,不是 g 造成的;而且目标式等于把 RBv2 的调仓节奏从 21 天"
      "悄悄改成 5 天,会把「降敞口」和「换手频率」两件事混在一起。")
    A("2. **σ_ex 什么时候算**。主口径 = 与 g 同节奏(每 5 个共同日算一次,σ★ 的中位数样本池也只有这些点);"
      "敏感性口径 = 每日算(样本池密 5 倍)。")
    A("")
    A("| 窗口 | 主口径(比例式 + 5 日 σ_ex) | 敏感性 1(目标式) | 敏感性 2(每日 σ_ex) |")
    A("|---|---|---|---|")
    for nm, w in (("W1", w1), ("W2", w2)):
        A(f"| {nm} 总收益 / 回撤 | {_pct(w['arms']['GB']['total_return'])} / {_pct(w['arms']['GB']['max_dd'])} | "
          f"{_pct(w['arms']['GB_target_mode']['total_return'])} / {_pct(w['arms']['GB_target_mode']['max_dd'])} | "
          f"{_pct(w['arms']['GB_daily_sigma']['total_return'])} / {_pct(w['arms']['GB_daily_sigma']['max_dd'])} |")
    A("")

    A("## 8. 限制(必须随结论一起说)")
    A("")
    A("1. 这是在**已实现的两段历史**上做的回放,不是前向证据;S-805 写死的两段各一次,没有留出段。")
    A("2. g 的 σ_ex 用的是**腿收益的协方差**(crypto/equity/gold 三条),不是 ① 的 24 个币;"
      "与 S-806 的「① 内部两两相关」不是同一个量,两件事不能互相代替。")
    A("3. 成本只按 20bp 的换手线性计,没有滑点、没有流动性冲击、没有申赎摩擦;"
      "g 变动的换手与 RBv2 调仓的换手分开记(见 §3)。")
    A("4. W2 覆盖 2024-01-04 → 2026-10-30,样本内已经包含 2025 与 2026 上半段的加密上涨;"
      "「降敞口」在这段里的代价是结构性的(少赚),不是实现问题。")
    A("5. 三个敏感性口径都只是口径的实现选择,不是新的判据;换口径不改变「全过才 ✅」这条规则。")
    A("")

    A("## 9. 产物")
    A("")
    A("- `docs/research/T-329_gross_budget.md`(本文件)")
    A("- `docs/research/t329_gross_budget.py`(脚本;腿的装配直接 import T-323,核只 import 一字不改)")
    A("- `docs/research/t329_results.json`(全部测得值)")
    A("- `docs/research/scenarios/lane-a-T-329.json`(前向命题)")
    A("")
    A(f"核:`{R['kernel']['path']}` sha256=`{R['kernel']['sha256'][:16]}…`({R['kernel']['source']})。")
    A("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    log(f"  写 {OUT_MD}")


def write_scenarios(R: dict) -> None:
    w1, w2 = R["windows"]["W1"], R["windows"]["W2"]
    m1, m2 = w1["arms"]["GB"], w2["arms"]["GB"]
    r1, r2 = w1["arms"]["RBv2"], w2["arms"]["RBv2"]
    g1, g2 = w1["g_stats"], w2["g_stats"]
    c1, c2 = w1["g_vs_interleg_corr"], w2["g_vs_interleg_corr"]
    passed = R["verdict"]["pass"]
    # 锚点:2026-11-09 的收盘(ohlcv_daily,只读;BTC 用 coingecko_pro_ohlc 那一行)
    BTC_CLOSE, ACWI_CLOSE = 75277.0, 156.35
    entries = [
        {
            "id": "T-329-1",
            "scenario": "T-329 S-805 整体敞口收放:前向一段里 RBv2+g 臂的累计收益不超过纯 RBv2 臂",
            "statement": (
                "用同一内核与同一 g 规则(每 5 个共同日 g = clip(σ★/σ_ex, 0.5, 1.0),比例式缩放)"
                "前向记账,2027-02-28 之前 RBv2+g 臂的累计收益 ≤ 纯 RBv2 臂的累计收益。"
                f"(本卡回放测得:W1 加 g 后 {_pct(m1['total_return'])} 对 RBv2 {_pct(r1['total_return'])}"
                f"、W2 {_pct(m2['total_return'])} 对 {_pct(r2['total_return'])};"
                f"W1 的 g 几乎不动(平均 g {_num(g1['mean_g'], 4)},g<1 的天数占比 "
                f"{_pct(g1['share_days_g_lt_1'], 1)}),W2 降得比较多(平均 g {_num(g2['mean_g'], 4)},"
                f"g<1 占比 {_pct(g2['share_days_g_lt_1'], 1)})。"
                "这条量的是「保险的账单」,不是收益承诺)"),
            "variable": "manual", "op": "lt", "hi": 0.0,
            "prob": 0.55, "horizon_d": "2027-02-28",
        },
        {
            "id": "T-329-2",
            "scenario": "T-329 S-805 腿间平均相关:前向 21 日窗口的中位数不超过 0.30",
            "statement": (
                "2027-02-28 之前,三条腿(crypto/equity/gold)日收益的 21 日平均两两相关 ρ̄,"
                "在所有滚动 21 日窗口上的中位数 ≤ 0.30(本卡实测:W1 窗口 ρ̄ 均值 "
                f"{_num(c1['mean_rho_fwd_all'], 3)}、W2 {_num(c2['mean_rho_fwd_all'], 3)};"
                "SPINE 记过压力天腿间相关升到 0.68;这条量「分散还在不在」)"),
            "variable": "manual", "op": "lt", "hi": 0.30,
            "prob": 0.65, "horizon_d": "2027-02-28",
        },
        {
            "id": "T-329-3",
            "scenario": "T-329 参照臂:BTC 在复核日仍在 2026-11-09 收盘价的 ±25% 带内",
            "statement": (
                f"2027-02-28 时 BTC 的收盘价落在 {BTC_CLOSE * 0.75:,.0f}–{BTC_CLOSE * 1.25:,.0f} 之间"
                f"(2026-11-09 收盘 {BTC_CLOSE:,.0f};这条只量 ② 基准的 beta 方向,不作收益承诺)"),
            "variable": "close:BTC", "op": "between",
            "lo": round(BTC_CLOSE * 0.75, 2), "hi": round(BTC_CLOSE * 1.25, 2),
            "prob": 0.6, "horizon_d": "2027-02-28",
        },
        {
            "id": "T-329-4",
            "scenario": "T-329 腿间风险:ACWI 在复核日仍在 2026-11-09 收盘价的 ±10% 带内",
            "statement": (
                f"2027-02-28 时 ACWI 的收盘价落在 {ACWI_CLOSE * 0.9:,.2f}–{ACWI_CLOSE * 1.1:,.2f} 之间"
                f"(2026-11-09 收盘 {ACWI_CLOSE};股票腿是 σ_ex 里始终在场的那条,这条量它的方向,不作收益承诺)"),
            "variable": "close:ACWI", "op": "between",
            "lo": round(ACWI_CLOSE * 0.9, 2), "hi": round(ACWI_CLOSE * 1.1, 2),
            "prob": 0.7, "horizon_d": "2027-02-28",
        },
    ]
    os.makedirs(os.path.dirname(OUT_SCEN), exist_ok=True)
    with open(OUT_SCEN, "w", encoding="utf-8") as f:
        json.dump({"author": "lane-a", "entries": entries}, f, ensure_ascii=False, indent=2)
    log(f"  写 {OUT_SCEN}")


if __name__ == "__main__":
    main()
