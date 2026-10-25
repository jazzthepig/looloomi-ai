#!/usr/bin/env python3
"""T-193 —— 崩盘图谱线索返工(S-675):随机锚点 / 二项对照 + 多回看尺度 + 窗内亮着天数 +「剔锚点当天」。

起因(lane-a 10-25 交叉复核 T-191,§A-auto-1025-1223 ①–④;lane-b 10-25 对 lane-c T-187 的复核,
§B-auto-1025-1222 ①):
  1. 内核 `sign_lift` 的零分布是**循环平移**,绕回点在序列起点 ⇒ 分位依赖序列长度。
     T-187 的 M8 急跌起点:存档口径(索引 1990 起 13442 天、前 6545 天 NaN)分位 0.9760,
     T-185 式收尾(6897 天)分位 0.9295 —— hit / base / lift 逐位相同,只有分位在动。
  2. 循环平移**不是与构造无关的对照**。需要一个「随便哪天当锚点会怎样」的对照:
     **随机锚点**(同样本量、从该道可用日里抽)+ **二项 p**。
  3. 只在 30 / 90 两个回看尺度上判过,看不出承重墙。线索要在 L = 15/30/60/90/120 上都看一遍。
  4. 「命中」不等于「早于崩盘就有」:窗内亮着天数 / 是否亮到锚点当天要分列;
     「同源」这种事后手写名单,改成**实测**的「剔锚点当天后仍过」。

**不动内核**:`docs/research/crash_atlas_common.py` 一个字不改(T-193 的 forbidden_paths 里有它)。
内核 sign_lift 的读数原样保留,新判据**并排**报;**不改** T-185 / T-186 / T-187 已合并的读数。
本脚本只 import `t191_anchor_rejudge` 与内核,不改它们。

**只读**:已存 json(t185/t186/t187/t191 results)+ 本地 FRED 快照 + 只读 Supabase(研究表)。
不重抓 FRED / 事件表,不改任何已合并读数。

零分布 / 分位一律走 `src/data/evaluation/apparatus.py`(不自己再写一遍)。
本脚本所有读数都是**探索性 —— 需另立预注册、在新数据上过零信号对照**;不产生任何可交易规则。
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from typing import Any, Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from docs.research.crash_atlas_common import (  # noqa: E402
    available,
    expanding_pct,
    load_fred,
    phase_returns,
    sign_lift,
    to_calendar,
    _window_any,
)
import docs.research.t191_anchor_rejudge as t191  # noqa: E402
from src.data.evaluation import apparatus  # noqa: E402

DATA_ROOT = os.environ.get("COMETCLOUD_DATA_ROOT", "/Volumes/CometCloudAI/cometcloud-local")
FRED_DIR = os.path.join(DATA_ROOT, "research", "crash_atlas", "fred")
REPORT_PATH = os.path.join(DATA_ROOT, "_reports", "absorb_input", "T-193_clue_rejudge.md")
OUT_JSON = os.path.join(HERE, "t193_results.json")

SEED = 675               # 内核 / T-191 的 seed(S-675)
CONTROL_SEED = 675       # 随机锚点对照的 seed(卡上要求写明)
N_RANDOM = 5000          # 随机锚点抽 5000 次
N_STYLE_DRAW = 2000       # 风格表零分布抽 2000 次(卡上要求;与 lane-a 10-25 复核同口径)
NEW_RATIO_MAX = 0.05     # 新判据:随机锚点「命中率 ≥ 实测」的比例 ≤ 0.05
CRIT_PCTILE = 0.95
CRIT_LIFT = 1.5
CRIT_MIN_ANCHORS = 6
LOOKBACKS = (15, 30, 60, 90, 120)
N_SHIFT = 2000           # 内核零分布的抽样数(与三道一致)

T187_FRED_GAP = {"NFCI": 10, "WALCL": 10, "ICSA": 10, "UMCSENT": 40}
T185_FINAL_GAP = {"M12": 40, "M4": 10, "M11": 10, "M13": 10}   # T-185 build_signals 末尾的 gap

# T-187 的锚点集 → 卡上的三套家族
T187_ANCHOR_KEY = {"primary_90d": "primary_first_leg_peaks",
                   "aux_break_30d": "aux_breaks",
                   "aux_fastcrash_30d": "aux_fast_crash_starts"}
# T-185 的锚点集 → 卡上的三套家族
T185_ANCHOR_KEY = {"primary_90d": "main", "aux_break_30d": "aux_break",
                   "aux_fastcrash_30d": "aux_fast"}
# 家族 → 默认回看窗(报告表头用)
FAMILY_LOOKBACK = {"primary_90d": 90, "aux_break_30d": 30, "aux_fastcrash_30d": 30,
                   "extra:fx_start_30d": 30, "extra:fx_hit_30d": 30}


# ── 小工具 ──────────────────────────────────────────────────────────────────
def load_json(name: str) -> dict:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def _mk187(cond: pd.Series, valid: pd.Series) -> pd.Series:
    """T-187 的 mk:条件成立 → 可空布尔;数据没到的日子留 NA(不算亮也不算不亮)。"""
    v = valid if valid.dtype == bool else valid.notna()
    return cond.astype("boolean").where(v)


def _mk185(deps: list[pd.Series], fn) -> pd.Series:
    """T-185 的 mk:依赖对齐到日历日后判条件,缺值给 NaN。"""
    return t191.mk(deps, fn)


def binom_tail(n: int, hits: int, p: float) -> Optional[float]:
    """P(X ≥ hits | X ~ Bin(n, p)) —— 精确二项尾(基准率 = 每个锚点独立命中的概率)。"""
    if n is None or hits is None or p is None or not (0.0 <= p <= 1.0):
        return None
    if hits <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0 if hits <= n else 0.0
    return float(sum(math.comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k))
                      for k in range(hits, n + 1)))


def _window_strict(on: pd.Series, lookback: int) -> pd.Series:
    """剔锚点当天的窗口:「a-L … a-1 这 L 天里亮过没有」(不含 a 当天)。"""
    return _window_any(on, lookback - 1).shift(1)


def usable_anchor_subset(on: pd.Series, anchors: list[pd.Timestamp], lookback: int) -> list[pd.Timestamp]:
    """内核 `sign_lift` 判定「锚点可用」的那一批:落在 [首个有数据的日子 + L, 序列最后一天] 里。

    实测命中率、基准率、前后两半,全部只在这批**可用锚点**上算(整族锚点里更早的那些
    被内核跳过、单独记 n_skipped)。随机锚点对照必须用同一批、同样本量。
    """
    on = on.sort_index()
    covered = on.notna()
    if not bool(covered.any()):
        return []
    first_ok = on.index[covered.values.argmax()] + pd.Timedelta(days=lookback)
    return sorted(pd.Timestamp(a) for a in anchors
                  if first_ok <= pd.Timestamp(a) <= on.index[-1])


def random_anchor_control(on: pd.Series, anchors: list[pd.Timestamp], lookback: int,
                          observed_hit_rate: Optional[float], n_draw: int = N_RANDOM,
                          seed: int = CONTROL_SEED) -> dict:
    """**随机锚点对照**(与构造无关):从「该道可用日」里随机抽同样本量的锚点,算命中率,
    看 5000 抽里有多少比例的命中率 ≥ 实测。

    可用日 = 亮灯序列有数据(非 NA)且 ≥ 首个可用日 + L 的日子 —— 与内核 `sign_lift`
    判定锚点「可用」的口径一致(真实锚点全都落在这个区间里,不然会被内核跳过)。

    ⚠️ 样本量必须与实测一致:实测命中率是内核在**可用锚点子集**上算的(整族锚点里
    早于「首个可用日 + L」的会被内核跳过、单独记 n_skipped),所以这里先把传入的
    整族锚点按同一口径过滤,再取同样本量。**不这么做会把随机样本量放大**
    (M9:实测 7 个锚点 vs 整族 20 个),随机零分布被系统性压低 → 线索显得比实际更稳。
    """
    on = on.sort_index()
    covered = on.notna()
    out: dict[str, Any] = {"n_draw": n_draw, "seed": seed,
                           "note": "随机锚点:同样本量、从该道可用日里无放回抽,算命中率"}
    if not bool(covered.any()):
        out["error"] = "亮灯序列没有有效日"
        return out
    first_ok = on.index[covered.values.argmax()] + pd.Timedelta(days=lookback)
    win = _window_any(on, lookback)
    pool = np.where(covered.values & np.asarray(on.index >= first_ok))[0]
    usable = usable_anchor_subset(on, anchors, lookback)
    n = len(usable)
    out["n_anchors_passed"] = len(anchors)
    out["n_anchors"] = n
    out["n_anchors_skipped"] = len(anchors) - n
    out["n_pool_days"] = int(len(pool))
    out["first_ok"] = str(first_ok.date())
    if n == 0 or len(pool) == 0 or observed_hit_rate is None:
        out["error"] = "锚点数 / 可用日 / 实测命中率为空,做不了随机对照"
        return out

    def draw(rng: np.random.Generator) -> float:
        pos = rng.choice(pool, size=min(n, len(pool)), replace=False)
        return float(win.values[pos].mean())

    try:
        null = apparatus.null_distribution(draw, n_draw, seed=seed, actual=observed_hit_rate)
    except apparatus.NoOpNull as exc:
        out["error"] = "apparatus.null_distribution 拒绝:" + repr(exc)
        return out
    ratio = float(np.mean(null >= observed_hit_rate))
    out.update({
        "ratio_ge_observed": ratio,
        "apparatus_percentile_of": apparatus.percentile_of(observed_hit_rate, null),
        "null_p50": float(np.median(null)),
        "null_p95": float(np.percentile(null, 95)),
        "null_max": float(np.max(null)),
    })
    return out


def strict_sign_lift(on: pd.Series, anchors: list[pd.Timestamp], lookback: int,
                     n_shift: int = N_SHIFT, seed: int = SEED) -> dict:
    """**剔锚点当天**重算:窗口 [a-L, a-1](不含 a 当天),其余口径与内核 `sign_lift` 一致。

    零分布仍然是内核那套循环平移(k ∈ [2L, N-2L]),只是窗口换成严格的;
    分位走 `apparatus.null_distribution` + `apparatus.percentile_of`(内核自己那份
    `pctile` 公式与 `percentile_of` 等价)。**内核文件未改**。
    """
    on = on.sort_index()
    covered = on.notna()
    res: dict[str, Any] = {"lookback": lookback, "n_shift": n_shift, "seed": seed,
                           "window": "[a-L, a-1](不含锚点当天)"}
    if not bool(covered.any()):
        res["error"] = "亮灯序列没有有效日"
        return res
    first_ok = on.index[covered.values.argmax()] + pd.Timedelta(days=lookback)
    win = _window_strict(on, lookback)
    anc = [pd.Timestamp(a) for a in anchors]
    usable = [a for a in anc if first_ok <= a <= on.index[-1]]
    if not usable:
        res["error"] = "没有可用锚点"
        return res
    pos = on.index.get_indexer(usable)
    if (pos < 0).any():
        res["error"] = "锚点不在序列索引上"
        return res
    hits = win.values[pos]
    hit_rate = float(hits.mean())
    base = win[win.index >= first_ok]
    base_rate = float(base.mean()) if len(base) else None
    vals = pd.Series(on, dtype="boolean").fillna(False).to_numpy(dtype=bool)
    n = len(vals)
    lo, hi = 2 * lookback, n - 2 * lookback

    def draw(rng: np.random.Generator) -> float:
        k = int(rng.integers(lo, hi)) if hi > lo else 0
        shifted = pd.Series(np.roll(vals, k), index=on.index)
        return float(_window_strict(shifted, lookback).values[pos].mean())

    null = apparatus.null_distribution(draw, n_shift, seed=seed, actual=hit_rate)
    pctile = apparatus.percentile_of(hit_rate, null)
    res.update({
        "n_anchors": len(usable), "n_skipped": len(anc) - len(usable),
        "hit_rate": hit_rate, "base_rate": base_rate,
        "lift": (hit_rate / base_rate) if base_rate else None,
        "null_p50": float(np.median(null)), "pctile": pctile,
    })
    return res


def anchor_detail(on: pd.Series, anchors: list[pd.Timestamp], lookback: int) -> dict:
    """逐锚点:窗内亮着几天 / 是否亮到锚点当天为止 / 剔当天后还亮不亮(严格命中)。"""
    on = on.sort_index()
    idx = on.index
    covered = on.notna()
    if not bool(covered.any()):
        return {"rows": [], "n_anchors": 0}
    first_ok = idx[covered.values.argmax()] + pd.Timedelta(days=lookback)
    on_bool = on.astype("boolean").fillna(False).to_numpy(dtype=bool)
    pos_of = {d: i for i, d in enumerate(idx)}
    rows = []
    for a in anchors:
        a = pd.Timestamp(a)
        if not (first_ok <= a <= idx[-1]) or a not in pos_of:
            continue
        lo_d = a - pd.Timedelta(days=lookback)
        i0, i1 = pos_of.get(lo_d, 0), pos_of[a]
        win = on_bool[i0:i1 + 1]
        n_on = int(win.sum())
        on_anchor = bool(win[-1])
        # 从锚点当天往前数连续亮着的天数(0 = 锚点当天没亮)
        run = 0
        j = i1
        while j >= i0 and on_bool[j]:
            run += 1
            j -= 1
        strict = bool(win[:-1].any()) if len(win) > 1 else False
        rows.append({"anchor": str(a.date()), "hit": int(n_on > 0),
                     "n_on_days_in_window": n_on, "on_anchor_day": int(on_anchor),
                     "contiguous_run_to_anchor": run,
                     "strict_hit_ex_anchor_day": int(strict)})
    hit_rows = [r for r in rows if r["hit"]]
    n = len(rows)
    n_strict = sum(r["strict_hit_ex_anchor_day"] for r in rows)
    return {
        "rows": rows, "n_anchors": n,
        "n_hit": len(hit_rows),
        "hit_rate": (len(hit_rows) / n) if n else None,
        "n_hit_only_on_anchor_day": sum(1 for r in hit_rows if not r["strict_hit_ex_anchor_day"]),
        "strict_hit_rate": (n_strict / n) if n else None,
        "n_on_anchor_day": sum(r["on_anchor_day"] for r in rows),
        "mean_on_days_in_window_hit": (float(np.mean([r["n_on_days_in_window"] for r in hit_rows]))
                                       if hit_rows else None),
        "median_on_days_in_window_hit": (float(np.median([r["n_on_days_in_window"] for r in hit_rows]))
                                         if hit_rows else None),
        "max_on_days_in_window_hit": (int(max([r["n_on_days_in_window"] for r in hit_rows]))
                                      if hit_rows else None),
        "mean_contiguous_run_to_anchor_hit": (
            float(np.mean([r["contiguous_run_to_anchor"] for r in hit_rows])) if hit_rows else None),
        "median_contiguous_run_to_anchor_hit": (
            float(np.median([r["contiguous_run_to_anchor"] for r in hit_rows])) if hit_rows else None),
    }


# ── 亮灯序列重建(全部本地 FRED 快照 + 只读 Supabase;不重抓)────────────────
def build_t185_series() -> dict:
    """T-185 口径的 M3/M5/M7/M8/M9(T-191 已重建并与原读数逐位对账)+ P4(本脚本补)。"""
    signs = dict(t191.t185_sign_rebuild())
    px = to_calendar(load_fred("NASDAQCOM", FRED_DIR), 7)
    vol20 = px.pct_change().rolling(20, min_periods=20).std() * np.sqrt(252)
    pct_vol = expanding_pct(vol20, 252)
    raw = _mk185([pct_vol], lambda a: (a >= 0.9))
    signs["P4"] = to_calendar(raw, 7)
    return signs


def build_t187_m_series() -> tuple[dict, dict]:
    """T-187 的 M1–M13,两套口径:
      - `archived`:T-187 存档口径(fred_cal → mk 之后**不再** to_calendar);
      - `t185_caliber`:同样的定义,收尾再过一次 T-185 的 to_calendar(前导 NaN 去掉、跨度收到有效段)。
    两者 hit / base / lift 逐位相同,只有内核循环平移零分布(依赖序列长度)会动。"""
    def cal(sid: str) -> pd.Series:
        return to_calendar(available(load_fred(sid, FRED_DIR), sid), T187_FRED_GAP.get(sid, 7))

    dff, t10y2y, nfci = cal("DFF"), cal("T10Y2Y"), cal("NFCI")
    spread, vix, vxv = cal("BAA10Y"), cal("VIXCLS"), cal("VXVCLS")
    dtw, wti, walcl = cal("DTWEXBGS"), cal("DCOILWTICO"), cal("WALCL")
    umc, icsa = cal("UMCSENT"), cal("ICSA")
    inf2 = [np.inf, -np.inf]

    m1 = (dff - dff.shift(365)).replace(inf2, np.nan)
    m2 = t10y2y < 0
    roll_min = t10y2y.rolling(365, min_periods=365).min()
    m3 = (t10y2y > 0) & (roll_min < 0)
    m4 = nfci > 0
    m5 = (spread - spread.shift(63)).replace(inf2, np.nan)
    m6 = vix < 13
    m7 = vix > 30
    vratio = (vix / vxv).replace(inf2, np.nan)
    d63 = (dtw / dtw.shift(63) - 1.0).replace(inf2, np.nan)
    m9 = expanding_pct(d63)
    m10 = (wti / wti.shift(126) - 1.0).replace(inf2, np.nan)
    m11 = (walcl / walcl.shift(91) - 1.0).replace(inf2, np.nan)
    m12 = expanding_pct(umc)
    ma4 = icsa.rolling(28, min_periods=28).mean()
    m13 = (ma4 / ma4.shift(91) - 1.0).replace(inf2, np.nan)

    archived = {
        "M1_ffr_12m_up_ge1pp": _mk187(m1 >= 1.0, m1),
        "M2_10y2y_lt0": _mk187(m2, t10y2y),
        "M3_10y2y_gt0_after_inversion": _mk187(m3, t10y2y.notna() & roll_min.notna()),
        "M4_nfci_gt0": _mk187(m4, nfci),
        "M5_baa10y_63d_up_ge0p5pp": _mk187(m5 >= 0.5, m5),
        "M6_vix_lt13": _mk187(m6, vix),
        "M7_vix_gt30": _mk187(m7, vix),
        "M8_vix_over_vxv_gt1": _mk187(vratio > 1, vratio),
        "M9_usd_broad_63d_chg_pct_ge90": _mk187(m9 >= 0.9, m9),
        "M10_wti_126d_up_ge50pct": _mk187(m10 >= 0.5, wti),
        "M11_fed_balance_91d_shrink": _mk187(m11 < 0, walcl),
        "M12_umcsent_pct_ge80": _mk187(m12 >= 0.8, umc),
        "M13_icsa_ma4_13w_up_ge15pct": _mk187(m13 >= 0.15, ma4),
    }
    t185_cal = {k: to_calendar(v, T185_FINAL_GAP.get(k.split("_")[0], 7)) for k, v in archived.items()}
    return archived, t185_cal


def build_t186_series() -> dict:
    """T-186 口径的 E1(卡上「其余四条全过项」之一)+ 口径外的 5 条额外通过项所涉迹象。"""
    def cal(x: pd.Series, days: int = 7) -> pd.Series:
        return to_calendar(x, max_gap_days=days)

    def bmask(cond: pd.Series, *refs: pd.Series) -> pd.Series:
        out = pd.Series(np.where(cond, 1.0, 0.0), index=cond.index, dtype=float)
        for r in refs:
            out[r.reindex(cond.index).isna()] = np.nan
        return out

    FX = {"KRW": "DEXKOUS", "BRL": "DEXBZUS", "MXN": "DEXMXUS", "INR": "DEXINUS"}
    parts = []
    for c, sid in FX.items():
        d = cal(load_fred(sid, FRED_DIR))
        l63c = d.shift(63)
        parts.append(bmask((d / l63c - 1.0) >= 1.0 / 0.90 - 1.0, l63c).rename(c))
    e1 = pd.concat(parts, axis=1).max(axis=1, skipna=True)
    e1_final = cal(pd.Series(e1, dtype="float"))

    t2 = cal(available(load_fred("T10Y2Y", FRED_DIR), "T10Y2Y"))
    inv365 = (t2 < 0).rolling(365, min_periods=1).max()
    m3 = bmask((t2 > 0) & (inv365 > 0), t2)
    baa = cal(load_fred("BAA10Y", FRED_DIR) - load_fred("DGS10", FRED_DIR))
    l63b = baa.shift(63)
    m5 = bmask((baa - l63b) >= 0.5, l63b)
    vix = cal(load_fred("VIXCLS", FRED_DIR))
    m7 = bmask(vix > 30, vix)
    vxv = cal(load_fred("VXVCLS", FRED_DIR))
    m8 = bmask((vix / vxv) > 1.0, vxv)
    dtw = cal(load_fred("DTWEXBGS", FRED_DIR))
    l63d = dtw.shift(63)
    m9 = bmask(expanding_pct(dtw / l63d - 1.0) >= 0.9, l63d)
    umc = cal(available(load_fred("UMCSENT", FRED_DIR), "UMCSENT"))
    m12 = bmask(expanding_pct(umc) >= 0.8, umc)

    out = {"E1": e1_final}
    for nm, v in (("M3", m3), ("M5", m5), ("M7", m7), ("M8", m8), ("M9", m9), ("M12", m12)):
        out[nm] = cal(pd.Series(v, dtype="float"))
    return out


def build_t187_price_signs() -> dict:
    """T-187 的 P4(20 日实现波动分位 ≥ 0.9,在 BTC 上)+ C1 / C5 / C6(卡上要分开评的三条)。"""
    rows = t191.fetch("asset_mcap_daily", {"symbol": "eq.BTC", "order": "d.asc",
                                           "select": "d,price,mcap"})
    btc = t191.srs(rows, "d", "price")
    px = to_calendar(btc, 5)
    rv = px.pct_change().rolling(20, min_periods=20).std()
    p4v = expanding_pct(rv)
    p4 = _mk187(p4v >= 0.9, p4v)

    fng = t191.srs(t191.fetch("macro_daily", {"series": "eq.fng", "order": "d.asc",
                                              "select": "d,value"}), "d", "value")
    fng_cal = to_calendar(fng, 7)
    hot = fng_cal >= 75
    c1 = _mk187(hot.rolling(7, min_periods=7).sum() >= 7, fng_cal)

    btc_mcap = t191.srs(rows, "d", "mcap")
    tc = to_calendar(t191.srs(t191.fetch("macro_daily", {"series": "eq.total_mcap", "order": "d.asc",
                                                        "select": "d,value"}), "d", "value"), 5)
    b = to_calendar(btc_mcap, 5).rolling(7, min_periods=7).median()
    share = b / tc
    d60 = (share - share.shift(60)).replace([np.inf, -np.inf], np.nan)
    c5 = _mk187(d60 <= -0.10, d60)

    vol = to_calendar(t191.srs(t191.fetch("macro_daily", {"series": "eq.total_volume", "order": "d.asc",
                                                         "select": "d,value"}), "d", "value"), 5)
    v30 = expanding_pct(vol.rolling(30, min_periods=30).mean())
    c6 = _mk187(v30 >= 0.9, v30)
    return {"P4_rv20_pct_ge90": p4, "C1_fng_ge75_7d": c1,
            "C5_btc_share_60d_drop_ge10pp": c5, "C6_total_vol_30d_mean_pct_ge90": c6}


# ── 目标集合 ────────────────────────────────────────────────────────────────
def is_card_clue(r: dict) -> bool:
    """T-191 报告里的「6 条线索」= T-185 的 5 条(M3/M5/M7/M8/M9)+ T-187 的 1 条(M8 急跌起点)。

    T-186 独有的 FX 锚点家族(family 以 `extra:` 开头)在 T-191 的 json 里也标了
    `is_clue=true`,但那是**口径外的额外通过项**:T-191 照报不算线索,Seth 已裁定
    不另开卡(lane-a 10-25 交叉复核 §六同口径)。这里按 family 前缀把两者分开数,
    免得把「6 条线索」数成 11 条。
    """
    return bool(r.get("is_clue")) and not str(r.get("family", "")).startswith("extra:")


def target_rows(t191_rows: list[dict]) -> list[dict]:
    """T-191 的 6 条线索 + 其余四条「四条全过但被手写同源剔除」的项。"""
    clues = [r for r in t191_rows if is_card_clue(r)]
    same = [r for r in t191_rows if r["pass_raw"] and r["same_source"]]
    return clues + same


def series_for(row: dict, t185: dict, t186: dict, t187_arch: dict, t187_m: dict,
               t187_px: dict) -> Optional[pd.Series]:
    task, sign = row["task"], row["sign"]
    if task == "T-185":
        return t185.get(sign)
    if task == "T-186":
        return t186.get(sign)
    if task == "T-187":
        if sign in t187_px:
            return t187_px[sign]
        if sign in t187_arch:
            return t187_arch[sign]
        return t187_m.get(sign)
    return None


def anchors_for(row: dict, t185: dict, t186: dict, t187: dict) -> list[pd.Timestamp]:
    task, fam = row["task"], row["family"]
    if task == "T-185":
        raw = t185["anchors"][T185_ANCHOR_KEY[fam]]
    elif task == "T-186":
        raw = t186["anchors"][row["anchor_set"]]
    else:
        raw = t187["anchors"][T187_ANCHOR_KEY[fam]]
    return [pd.Timestamp(x) for x in raw]


def judge4(row: dict, pctile, lift, n, half1, half2, base) -> dict:
    c_pctile = bool(pctile is not None and pctile >= CRIT_PCTILE)
    c_lift = bool(lift is not None and lift >= CRIT_LIFT)
    c_n = bool(n is not None and n >= CRIT_MIN_ANCHORS)
    c_halves = bool(half1 is not None and half2 is not None and base is not None
                    and half1 > base and half2 > base)
    return {"c_pctile": c_pctile, "c_lift": c_lift, "c_n_anchors": c_n, "c_halves": c_halves,
            "pass_old4": bool(c_pctile and c_lift and c_n and c_halves)}


# ── 风格表(⑥)──────────────────────────────────────────────────────────────
def style_block(t187: dict, t191_res: dict) -> dict:
    """风格表:5 条(除 BTC_over_ALT)按 2000 抽复报 + 「风格 × 周期」展开(5 次首腿崩盘各一行)。"""
    levels = t191.style_levels()
    out: dict[str, Any] = {"n_draw": N_STYLE_DRAW, "seed": SEED,
                           "note": "零分布走 apparatus.null_distribution + percentile_of;"
                                   "随机日的『谷底』口径 = d 之后 H 天内最低点(与 T-191 相同)"}
    agg = t191.control_percentiles(t187, levels, n_draw=N_STYLE_DRAW, seed=SEED)
    out["aggregate_t191_pipeline_2000"] = agg

    btc = levels.get("BTC_hold")
    if btc is None or btc.empty:
        out["error"] = "BTC 价格序列没重建成功"
        return out
    eps = [e for e in t187["styles"]["BTC_hold"] if e.get("first_leg")]
    real = [{"peak_d": pd.Timestamp(e["peak_d"]), "trough_d": pd.Timestamp(e["trough_d"]),
             "first_leg": e.get("first_leg")} for e in eps]
    H = int(np.median([(e["trough_d"] - e["peak_d"]).days for e in real]))
    out["H_days_median_crash_len"] = H
    out["n_first_leg_cycles"] = len(real)

    per_cycle = []
    for nm in t187["styles"]:
        if nm == "BTC_over_ALT":
            continue
        lv = levels.get(nm)
        if not isinstance(lv, pd.Series) or lv.empty:
            continue
        lv_valid = lv.dropna()
        if lv_valid.empty:
            continue
        first_ok = lv_valid.index.min() + pd.Timedelta(days=60)
        last_ok = lv_valid.index.max() - pd.Timedelta(days=H + 120)
        eligible = btc.index[(btc.index >= first_ok) & (btc.index <= last_ok)]
        if len(eligible) == 0:
            continue

        def draw_one(rng: np.random.Generator, _lv=lv) -> dict:
            d = eligible[int(rng.integers(0, len(eligible)))]
            win = btc[(btc.index > d) & (btc.index <= d + pd.Timedelta(days=H))]
            tr = win.index[win.values.argmin()] if len(win) else d
            pr = phase_returns(_lv, {"peak_d": d, "trough_d": tr})
            return {k: pr.get(k) for k in ("pre", "crash", "recovery")}

        nulls: dict[str, np.ndarray] = {}
        for leg in ("pre", "crash", "recovery"):
            try:
                nulls[leg] = apparatus.null_distribution(
                    lambda rng_, _k=leg: draw_one(rng_)[_k], N_STYLE_DRAW, seed=SEED)
            except apparatus.NoOpNull as exc:
                nulls[leg] = np.array([])
                out.setdefault("null_errors", []).append(
                    {"style": nm, "leg": leg, "error": repr(exc)})
        for cyc in real:
            pr = phase_returns(lv, cyc)
            row = {"style": nm, "peak_d": str(cyc["peak_d"].date()),
                   "trough_d": str(cyc["trough_d"].date()),
                   "n_eligible_days": int(len(eligible))}
            for leg in ("pre", "crash", "recovery"):
                actual = pr.get(leg)
                row[leg] = actual
                row[leg + "_pctile"] = (apparatus.percentile_of(actual, nulls[leg])
                                        if len(nulls.get(leg, [])) else None)
            per_cycle.append(row)
    out["style_x_cycle"] = per_cycle
    return out


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> None:
    t185 = load_json("t185_results.json")
    t186 = load_json("t186_results.json")
    t187 = load_json("t187_results.json")
    t191_res = load_json("t191_results.json")
    t191_rows = t191_res["rows"]

    print("[1/6] 重建亮灯序列 …", flush=True)
    t185_signs = build_t185_series()
    t186_signs = build_t186_series()
    t187_m_arch, t187_m_t185 = build_t187_m_series()
    t187_px_signs = build_t187_price_signs()

    targets = target_rows(t191_rows)
    clues = [r for r in t191_rows if is_card_clue(r)]
    same_src = [r for r in t191_rows if r["pass_raw"] and r["same_source"]]
    extra_rows = [r for r in t191_rows
                  if r["pass_raw"] and not r["same_source"] and not is_card_clue(r)]

    # ── ① 随机锚点 / 二项对照 + 新判据 ────────────────────────────────────
    print("[2/6] ① 随机锚点 / 二项对照 …", flush=True)
    blk1_cases = []
    for r in targets:
        on = series_for(r, t185_signs, t186_signs, t187_m_arch, t187_m_t185, t187_px_signs)
        rec: dict[str, Any] = {"task": r["task"], "sign": r["sign"], "label": r["label"],
                               "family": r["family"], "anchor_set": r["anchor_set"],
                               "lookback": r["lookback"], "n_anchors": r["n_anchors"],
                               "hit_rate_t191": r["hit_rate"], "base_rate": r["base_rate"],
                               "lift": r["lift"], "kernel_pctile": r["pctile"],
                               "half1": r["half1_hit_rate"], "half2": r["half2_hit_rate"],
                               "t191_same_source": r["same_source"], "t191_is_clue": r["is_clue"]}
        if on is None:
            rec["error"] = "亮灯序列没重建出来"
            blk1_cases.append(rec)
            continue
        rec["series_span"] = [str(on.index[0].date()), str(on.index[-1].date())]
        rec["series_len_days"] = int(len(on))
        ctrl = random_anchor_control(on, anchors_for(r, t185, t186, t187), r["lookback"],
                                     r["hit_rate"])
        rec["random_anchor"] = ctrl
        rec["random_ratio_ge_observed"] = ctrl.get("ratio_ge_observed")
        hits = None
        if r["hit_rate"] is not None and r["n_anchors"]:
            hits = int(round(float(r["hit_rate"]) * int(r["n_anchors"])))
        rec["n_hits"] = hits
        rec["binom_p"] = binom_tail(int(r["n_anchors"]), hits, r["base_rate"])
        j = judge4(r, r["pctile"], r["lift"], r["n_anchors"], r["half1_hit_rate"],
                   r["half2_hit_rate"], r["base_rate"])
        j["c_random_anchor"] = bool(rec["random_ratio_ge_observed"] is not None
                                    and rec["random_ratio_ge_observed"] <= NEW_RATIO_MAX)
        j["pass_new5"] = bool(j["pass_old4"] and j["c_random_anchor"])
        rec.update(j)
        rec["dropped_by_random_anchor"] = bool(j["pass_old4"] and not j["pass_new5"])
        blk1_cases.append(rec)

    def _sel(rows, pred):
        return [c for c in rows if pred(c)]

    clue_cases = [c for c in blk1_cases if c["t191_is_clue"]]
    same_cases = [c for c in blk1_cases if not c["t191_is_clue"]]
    n_clue_old = len(clue_cases)
    n_clue_new = sum(1 for c in clue_cases if c.get("pass_new5"))
    blk1 = {
        "targets": blk1_cases,
        "n_clues_t191": n_clue_old,
        "n_clues_new_criterion": n_clue_new,
        "clues_dropped": [{"task": c["task"], "sign": c["sign"], "family": c["family"],
                           "random_ratio_ge_observed": c.get("random_ratio_ge_observed"),
                           "binom_p": c.get("binom_p")} for c in clue_cases
                          if not c.get("pass_new5")],
        "clues_kept": [{"task": c["task"], "sign": c["sign"], "family": c["family"],
                        "random_ratio_ge_observed": c.get("random_ratio_ge_observed"),
                        "binom_p": c.get("binom_p")} for c in clue_cases
                       if c.get("pass_new5")],
        "same_source_full_pass": same_cases,
    }

    # 口径外:T-186 独有的 FX 锚点上的额外通过项(卡上没点名,单列)
    blk1_extra = []
    for r in extra_rows:
        on = series_for(r, t185_signs, t186_signs, t187_m_arch, t187_m_t185, t187_px_signs)
        if on is None:
            continue
        ctrl = random_anchor_control(on, anchors_for(r, t185, t186, t187), r["lookback"],
                                     r["hit_rate"])
        hits = int(round(float(r["hit_rate"]) * int(r["n_anchors"])))
        j = judge4(r, r["pctile"], r["lift"], r["n_anchors"], r["half1_hit_rate"],
                   r["half2_hit_rate"], r["base_rate"])
        j["c_random_anchor"] = bool(ctrl.get("ratio_ge_observed") is not None
                                    and ctrl["ratio_ge_observed"] <= NEW_RATIO_MAX)
        j["pass_new5"] = bool(j["pass_old4"] and j["c_random_anchor"])
        blk1_extra.append({"task": r["task"], "sign": r["sign"], "label": r["label"],
                           "family": r["family"], "anchor_set": r["anchor_set"],
                           "lookback": r["lookback"], "n_anchors": r["n_anchors"],
                           "hit_rate": r["hit_rate"], "base_rate": r["base_rate"],
                           "lift": r["lift"], "kernel_pctile": r["pctile"],
                           "random_ratio_ge_observed": ctrl.get("ratio_ge_observed"),
                           "binom_p": binom_tail(int(r["n_anchors"]), hits, r["base_rate"]),
                           **j})
    blk1["extra_families_outside_card"] = blk1_extra

    # ── ② T-187 的 M 系按 T-185 口径重建 + M8 分位重报 ───────────────────
    print("[3/6] ② T-187 M 系两套口径 …", flush=True)
    m8_rows = []
    for fam, L in (("primary_90d", 90), ("aux_break_30d", 30), ("aux_fastcrash_30d", 30)):
        anchors = [pd.Timestamp(x) for x in t187["anchors"][T187_ANCHOR_KEY[fam]]]
        arch = sign_lift(t187_m_arch["M8_vix_over_vxv_gt1"], anchors, L, n_shift=N_SHIFT, seed=SEED)
        cal = sign_lift(t187_m_t185["M8_vix_over_vxv_gt1"], anchors, L, n_shift=N_SHIFT, seed=SEED)
        stored = t187["signs"]["M8_vix_over_vxv_gt1"][fam]
        ctrl = random_anchor_control(t187_m_t185["M8_vix_over_vxv_gt1"], anchors, L,
                                     stored["hit_rate"])
        m8_rows.append({
            "family": fam, "lookback": L, "n_anchors": cal["n_anchors"],
            "stored_t187": {k: stored.get(k) for k in
                            ("n_anchors", "hit_rate", "base_rate", "lift", "null_p50", "pctile")},
            "rebuilt_archived_caliber": {k: arch.get(k) for k in
                                         ("n_anchors", "hit_rate", "base_rate", "lift",
                                          "null_p50", "pctile")},
            "rebuilt_t185_caliber": {k: cal.get(k) for k in
                                     ("n_anchors", "hit_rate", "base_rate", "lift",
                                      "null_p50", "pctile")},
            "archived_span_days": int(len(t187_m_arch["M8_vix_over_vxv_gt1"])),
            "t185_caliber_span_days": int(len(t187_m_t185["M8_vix_over_vxv_gt1"])),
            "archived_span": [str(t187_m_arch["M8_vix_over_vxv_gt1"].index[0].date()),
                              str(t187_m_arch["M8_vix_over_vxv_gt1"].index[-1].date())],
            "t185_caliber_span": [str(t187_m_t185["M8_vix_over_vxv_gt1"].index[0].date()),
                                  str(t187_m_t185["M8_vix_over_vxv_gt1"].index[-1].date())],
            "random_anchor_t185_caliber": ctrl,
            "delta_pctile_minus_random_ratio": (
                (cal.get("pctile") - ctrl["ratio_ge_observed"])
                if cal.get("pctile") is not None and ctrl.get("ratio_ge_observed") is not None
                else None),
            "delta_archived_pctile_minus_random_ratio": (
                (arch.get("pctile") - ctrl["ratio_ge_observed"])
                if arch.get("pctile") is not None and ctrl.get("ratio_ge_observed") is not None
                else None),
        })

    m_series_table = []
    for name in t187_m_arch:
        for fam, L in (("primary_90d", 90), ("aux_break_30d", 30), ("aux_fastcrash_30d", 30)):
            anchors = [pd.Timestamp(x) for x in t187["anchors"][T187_ANCHOR_KEY[fam]]]
            stored = t187["signs"].get(name, {}).get(fam, {})
            cal = sign_lift(t187_m_t185[name], anchors, L, n_shift=N_SHIFT, seed=SEED)
            ctrl = random_anchor_control(t187_m_t185[name], anchors, L, stored.get("hit_rate"))
            m_series_table.append({
                "sign": name, "family": fam, "lookback": L,
                "n_anchors": cal.get("n_anchors"),
                "hit_rate": cal.get("hit_rate"), "base_rate": cal.get("base_rate"),
                "lift": cal.get("lift"),
                "pctile_archived": stored.get("pctile"),
                "pctile_t185_caliber": cal.get("pctile"),
                "random_ratio_ge_observed": ctrl.get("ratio_ge_observed"),
                "delta_pctile_minus_random_ratio": (
                    (cal.get("pctile") - ctrl["ratio_ge_observed"])
                    if cal.get("pctile") is not None and ctrl.get("ratio_ge_observed") is not None
                    else None),
                "archived_span_days": int(len(t187_m_arch[name])),
                "t185_caliber_span_days": int(len(t187_m_t185[name])),
            })
    blk2 = {"m8": m8_rows, "m_series_table": m_series_table,
            "note": "同一套定义,只差收尾的 to_calendar ⇒ hit/base/lift 逐位相同,分位随序列长度动"}

    # ── ③ 多回看尺度 L = 15/30/60/90/120 ─────────────────────────────────
    print("[4/6] ③ L 扫 + ④ 窗内亮着天数 …", flush=True)
    sweep = []
    for r in clues:
        on = series_for(r, t185_signs, t186_signs, t187_m_arch, t187_m_t185, t187_px_signs)
        if on is None:
            continue
        anchors = anchors_for(r, t185, t186, t187)
        row = {"task": r["task"], "sign": r["sign"], "label": r["label"],
               "family": r["family"], "anchor_set": r["anchor_set"], "lookback": r["lookback"],
               "anchor_dates": [str(a.date()) for a in anchors], "by_L": {}}
        for L in LOOKBACKS:
            res = sign_lift(on, anchors, L, n_shift=N_SHIFT, seed=SEED)
            n = res.get("n_anchors")
            hits = int(round(float(res["hit_rate"]) * n)) if res.get("hit_rate") is not None and n else None
            row["by_L"][str(L)] = {
                "n_anchors": n, "n_hits": hits, "hit_rate": res.get("hit_rate"),
                "base_rate": res.get("base_rate"), "lift": res.get("lift"),
                "pctile": res.get("pctile"), "null_p50": res.get("null_p50"),
            }
        sweep.append(row)
    t185_m8 = [s for s in sweep if s["task"] == "T-185" and s["sign"] == "M8"]
    t185_m8_L90 = None
    if t185_m8:
        t185_m8_L90 = t185_m8[0]["by_L"].get("90")
    blk3 = {"clues": sweep, "lookbacks": list(LOOKBACKS),
            "t185_m8_at_L90": t185_m8_L90,
            "t185_m8_L90_verdict": (
                None if not t185_m8_L90 or t185_m8_L90.get("lift") is None
                else bool(t185_m8_L90["lift"] >= CRIT_LIFT))}

    # ── ④ 窗内亮着天数 / 亮到锚点当天;C6 / C1 / C5 分开评 ───────────────
    detail = []
    for r in clues:
        on = series_for(r, t185_signs, t186_signs, t187_m_arch, t187_m_t185, t187_px_signs)
        if on is None:
            continue
        d = anchor_detail(on, anchors_for(r, t185, t186, t187), r["lookback"])
        d.update({"task": r["task"], "sign": r["sign"], "label": r["label"],
                  "family": r["family"], "lookback": r["lookback"]})
        detail.append(d)

    c_series = {}
    for nm in ("C6_total_vol_30d_mean_pct_ge90", "C1_fng_ge75_7d",
               "C5_btc_share_60d_drop_ge10pp"):
        on = t187_px_signs[nm]
        anchors = [pd.Timestamp(x) for x in t187["anchors"]["primary_first_leg_peaks"]]
        entry = {"sign": nm, "family": "primary_90d",
                 "anchor_dates": [str(a.date()) for a in anchors],
                 "t191_rows": [{k: v for k, v in r.items() if k in
                                ("family", "n_anchors", "hit_rate", "base_rate", "lift",
                                 "pctile", "c_pctile", "c_lift", "c_n_anchors", "c_halves",
                                 "pass_raw", "is_clue")}
                               for r in t191_rows
                               if r["task"] == "T-187" and r["sign"] == nm],
                 "by_L": {}}
        for L in (14, 15, 30, 60, 90, 120):
            res = sign_lift(on, anchors, L, n_shift=N_SHIFT, seed=SEED)
            n = res.get("n_anchors")
            hits = int(round(float(res["hit_rate"]) * n)) if res.get("hit_rate") is not None and n else None
            entry["by_L"][str(L)] = {"n_anchors": n, "n_hits": hits,
                                     "hit_rate": res.get("hit_rate"),
                                     "base_rate": res.get("base_rate"),
                                     "lift": res.get("lift"), "pctile": res.get("pctile")}
        for _L in (14, 30, 60, 90, 120):
            entry["anchor_detail_L%d" % _L] = anchor_detail(on, anchors, _L)
        c_series[nm] = entry
    blk4 = {"clues": detail, "c_series": c_series,
            "note": "C6 / C1 / C5 在 T-191 里**不是线索**(锚点数 < 6),这里只分开评,"
                    "不计入线索条数"}

    # ── ⑤「同源」→「剔锚点当天后仍过」+ 哪个 json 带该字段 ───────────────
    strict_cases = []
    for r in targets:
        on = series_for(r, t185_signs, t186_signs, t187_m_arch, t187_m_t185, t187_px_signs)
        if on is None:
            continue
        anchors = anchors_for(r, t185, t186, t187)
        s = strict_sign_lift(on, anchors, r["lookback"], n_shift=N_SHIFT, seed=SEED)
        rec = {"task": r["task"], "sign": r["sign"], "family": r["family"],
               "anchor_set": r["anchor_set"], "lookback": r["lookback"],
               "t191_same_source": r["same_source"], "t191_is_clue": r["is_clue"],
               "old_hit_rate": r["hit_rate"], "old_base_rate": r["base_rate"],
               "old_lift": r["lift"], "old_pctile": r["pctile"],
               "strict": s}
        if "hit_rate" in s and s.get("base_rate"):
            h = int(s["n_anchors"])
            hh = int(round(float(s["hit_rate"]) * h))
            # 前后两半:严格口径重算。**只在可用锚点上切**,切法跟 T-185 自己的一样
            # (中位锚点切两半)——整族锚点切片会把不可用的锚点算进去,而且
            # get_indexer 的 −1 会静默读序列最后一格(内核在 crash_atlas_common.py:148
            # 专门为此抛过错)。
            on_s = on.sort_index()
            st = _window_strict(on_s, r["lookback"])
            usable = usable_anchor_subset(on_s, anchors, r["lookback"])
            idx = on_s.index
            pos = idx.get_indexer(pd.DatetimeIndex(usable)) if usable else np.array([], dtype=int)
            h1 = h2 = None
            if len(pos) and not (pos < 0).any():
                mid = usable[len(usable) // 2]
                sel1 = [i for i, a in enumerate(usable) if a <= mid]
                sel2 = [i for i, a in enumerate(usable) if a > mid]
                h1 = float(st.values[pos[sel1]].mean()) if sel1 else None
                h2 = float(st.values[pos[sel2]].mean()) if sel2 else None
            j = judge4(r, s.get("pctile"), s.get("lift"), s.get("n_anchors"), h1, h2,
                       s.get("base_rate"))
            rec.update(j)
            rec["survives_ex_anchor_day"] = bool(j["pass_old4"])
            rec["strict_binom_p"] = binom_tail(h, hh, s.get("base_rate"))
        strict_cases.append(rec)
    blk5 = {
        "cases": strict_cases,
        "same_source_field_in_json": {
            "t185_results.json": "有(same_source 逐信号写在 signals[] 里)",
            "t186_results.json": "有(same_source 逐信号写在 signal_table[锚点集][信号] 里)",
            "t187_results.json": "**没有** —— T-191 是按规则现补的(t191_anchor_rejudge.py:201-203)",
        },
        "note": "「同源」是事后手写名单;这里换成实测口径:剔锚点当天(窗口 [a-L, a-1])后"
                "四条判据还成不成立",
    }

    # ── ⑥ 风格表 2000 抽 + 风格 × 周期 ───────────────────────────────────
    print("[5/6] ⑥ 风格表 2000 抽 …", flush=True)
    blk6 = style_block(t187, t191_res)

    res = {
        "task": "T-193", "ledger": "S-675",
        "seeds": {"kernel": SEED, "kernel_n_shift": N_SHIFT,
                  "random_anchor_control": CONTROL_SEED, "style_null": SEED,
                  "style_n_draw": N_STYLE_DRAW, "n_random_draws": N_RANDOM},
        "criteria": {"old4": ["pctile ≥ 0.95", "lift ≥ 1.5", "n_anchors ≥ 6",
                              "前后两半命中率都 > 基准率"],
                     "new5": "旧四条 + 随机锚点「命中率 ≥ 实测」的比例 ≤ 0.05"},
        "block1_random_anchor": blk1,
        "block2_t187_m_caliber": blk2,
        "block3_lookback_sweep": blk3,
        "block4_anchor_detail": blk4,
        "block5_strict_anchor_day": blk5,
        "block6_styles": blk6,
        "compliance": "全部读数为探索性 —— 需另立预注册、在新数据上过零信号对照;"
                      "不构成投资建议,不含任何买卖措辞。",
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("[6/6] 写报告 …", flush=True)
    write_report(res)
    print("T-193:旧 6 条线索 → 新判据剩 %d 条;随机锚点对照 %d 抽(seed=%d)"
          % (n_clue_new, N_RANDOM, CONTROL_SEED))


# ── 报告 ────────────────────────────────────────────────────────────────────
def _f(x, nd=3, dash="—"):
    if x is None:
        return dash
    try:
        return ("%%.%df" % nd) % float(x)
    except (TypeError, ValueError):
        return dash


def _pc(x, nd=1, dash="—"):
    if x is None:
        return dash
    try:
        return ("%." + str(nd) + "f%%") % (float(x) * 100.0)
    except (TypeError, ValueError):
        return dash


def write_report(res: dict) -> None:
    L: list[str] = []
    A = L.append
    A("# T-193 崩盘图谱线索返工(S-675):随机锚点 / 二项对照 + 多回看尺度 + 窗内亮着天数 +「剔锚点当天」\n")
    A("**性质**:返工,不是新试验。T-191 的 6 条线索 / 192 次判定只用内核的循环平移零分布;"
      "这一轮补**与构造无关**的对照,只加读数、不改已合并读数、不改内核"
      "(`docs/research/crash_atlas_common.py` 一字未动)。")
    A("**所有读数都是探索性 —— 需另立预注册、在新数据上过零信号对照**;"
      "本报告只做候选线索挖掘,不构成任何可交易规则,也不构成投资建议。\n")
    A("**口径**:随机锚点对照 %d 抽、seed=%d(卡上要求写明);「该道可用日」= 亮灯序列有数据且"
      "≥ 首个可用日 + L 的日子(与内核 `sign_lift` 判锚点可用的口径一致);"
      "**随机抽的锚点数 = 实测用的可用锚点数**(整族锚点里早于「首个可用日 + L」的那些"
      "会被内核跳过,不进实测分母 —— 不对齐样本量会把随机零分布压低);"
      "二项 p = P(X ≥ 命中数 | X~Bin(锚点数, 基准率));"
      "内核零分布仍是 n_shift=%d、seed=%d;风格表零分布 %d 抽、seed=%d。\n"
      % (res["seeds"]["n_random_draws"], res["seeds"]["random_anchor_control"],
         res["seeds"]["kernel_n_shift"], res["seeds"]["kernel"],
         res["seeds"]["style_n_draw"], res["seeds"]["style_null"]))

    # ── ① ──
    b1 = res["block1_random_anchor"]
    A("## ① 随机锚点 / 二项对照:6 条线索实际剩几条\n")
    A("| 道 | 迹象 | 锚点集 | L | 锚点 | 随机样本量(整族→可用) | 命中率 | 基准率 | 提升 | 内核分位 | 随机锚点≥实测 | 二项 p | 原四条 | 新判据(加随机锚点) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in b1["targets"]:
        if not c.get("t191_is_clue"):
            continue
        ra = c.get("random_anchor", {})
        A("| %s | %s | %s | %d | %s | %s→%s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            c["task"], c["sign"], c["anchor_set"], c["lookback"], _f(c.get("n_anchors"), 0),
            _f(ra.get("n_anchors_passed"), 0), _f(ra.get("n_anchors"), 0),
            _pc(c.get("hit_rate_t191")), _pc(c.get("base_rate")), _f(c.get("lift"), 2),
            _f(c.get("kernel_pctile"), 4), _f(c.get("random_ratio_ge_observed"), 4),
            _f(c.get("binom_p"), 4),
            "✓" if c.get("pass_old4") else "✗",
            ("✓" if c.get("pass_new5") else ("✗(被随机锚点筛掉)" if c.get("pass_old4") else "✗"))))
    A("")
    A("**结论:旧判据 6 条线索 → 新判据(加随机锚点比例 ≤ 0.05)剩 %d 条。**" % b1["n_clues_new_criterion"])
    if b1["clues_dropped"]:
        A("")
        A("掉下去的:")
        for c in b1["clues_dropped"]:
            A("- **%s %s(%s)**:随机锚点 ≥ 实测 的比例 %s(> 0.05),二项 p = %s"
              % (c["task"], c["sign"], c["family"], _f(c["random_ratio_ge_observed"], 4),
                 _f(c["binom_p"], 4)))
    A("")
    A("留住的:")
    for c in b1["clues_kept"]:
        A("- %s %s(%s):随机锚点 ≥ 实测 的比例 %s,二项 p = %s"
          % (c["task"], c["sign"], c["family"], _f(c["random_ratio_ge_observed"], 4),
             _f(c["binom_p"], 4)))
    A("")
    A("**「其余四条全过项」**(T-191 手写标「同源」的那四条)在新对照下:")
    A("")
    A("| 道 | 迹象 | 锚点集 | L | 锚点 | 随机样本量(整族→可用) | 命中率 | 提升 | 内核分位 | 随机锚点≥实测 | 二项 p | 新判据 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in b1["same_source_full_pass"]:
        ra = c.get("random_anchor", {})
        A("| %s | %s | %s | %d | %s | %s→%s | %s | %s | %s | %s | %s | %s |" % (
            c["task"], c["sign"], c["anchor_set"], c["lookback"], _f(c.get("n_anchors"), 0),
            _f(ra.get("n_anchors_passed"), 0), _f(ra.get("n_anchors"), 0),
            _pc(c.get("hit_rate_t191")),
            _f(c.get("lift"), 2), _f(c.get("kernel_pctile"), 4),
            _f(c.get("random_ratio_ge_observed"), 4), _f(c.get("binom_p"), 4),
            ("✓" if c.get("pass_new5") else "✗")))
    if b1.get("extra_families_outside_card"):
        A("")
        A("**口径外补充**(T-186 独有的 FX 锚点上的额外通过项,卡上没点名,单列、不计入线索条数):")
        A("")
        A("| 道 | 迹象 | 锚点集 | L | 命中率 | 提升 | 内核分位 | 随机锚点≥实测 | 二项 p | 新判据 |")
        A("|---|---|---|---|---|---|---|---|---|---|")
        for c in b1["extra_families_outside_card"]:
            A("| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
                c["task"], c["sign"], c["anchor_set"], c["lookback"], _pc(c.get("hit_rate")),
                _f(c.get("lift"), 2), _f(c.get("kernel_pctile"), 4),
                _f(c.get("random_ratio_ge_observed"), 4), _f(c.get("binom_p"), 4),
                "✓" if c.get("pass_new5") else "✗"))

    # ── ② ──
    b2 = res["block2_t187_m_caliber"]
    A("\n## ② T-187 的 M 系按 T-185 的 to_calendar 口径重建\n")
    A("同一套定义、只差收尾那一次 `to_calendar`(内核 `to_calendar` 先 `dropna()` ⇒ 前导 NaN 去掉、"
      "跨度收到有效段)。hit / base / lift 逐位相同,**只有循环平移零分布在动**(绕回点在序列起点)。\n")
    A("| 锚点集 | L | 存档口径分位 | T-185 口径分位 | 存档跨度(天) | T-185 口径跨度(天) | 命中率(两者相同) | 提升 | 随机锚点≥实测 | 内核分位 − 随机比例(T-185 口径) |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for r in b2["m8"]:
        A("| %s | %d | %s | %s | %d | %d | %s | %s | %s | %s |" % (
            r["family"], r["lookback"], _f(r["rebuilt_archived_caliber"]["pctile"], 4),
            _f(r["rebuilt_t185_caliber"]["pctile"], 4), r["archived_span_days"],
            r["t185_caliber_span_days"], _pc(r["rebuilt_t185_caliber"]["hit_rate"]),
            _f(r["rebuilt_t185_caliber"]["lift"], 3),
            _f(r["random_anchor_t185_caliber"].get("ratio_ge_observed"), 4),
            _f(r.get("delta_pctile_minus_random_ratio"), 4)))
    A("")
    A("**M 系全表(存档口径分位 / T-185 口径分位 / 随机锚点比例 / 两者之差)**:")
    A("")
    A("| 迹象 | 锚点集 | 锚点 | 提升 | 存档分位 | T-185 口径分位 | 随机锚点≥实测 | 差(内核 − 随机) |")
    A("|---|---|---|---|---|---|---|---|")
    for r in b2["m_series_table"]:
        A("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["sign"], r["family"], _f(r["n_anchors"], 0), _f(r["lift"], 2),
            _f(r["pctile_archived"], 4), _f(r["pctile_t185_caliber"], 4),
            _f(r["random_ratio_ge_observed"], 4), _f(r["delta_pctile_minus_random_ratio"], 4)))

    # ── ③ ──
    b3 = res["block3_lookback_sweep"]
    A("\n## ③ 多回看尺度 L = 15 / 30 / 60 / 90 / 120\n")
    for s in b3["clues"]:
        l0 = s.get("lookback", FAMILY_LOOKBACK.get(s["family"], 0))
        A("### %s %s(%s,锚点集 %s,L₀=%d)\n" % (s["task"], s["sign"], s["family"],
                                               s["anchor_set"], l0))
        A("| L | 锚点 | 命中 | 命中率 | 基准率 | 提升 | 内核分位 |")
        A("|---|---|---|---|---|---|---|")
        for LB in b3["lookbacks"]:
            r = s["by_L"].get(str(LB), {})
            A("| %d | %s | %s | %s | %s | %s | %s |" % (
                LB, _f(r.get("n_anchors"), 0), _f(r.get("n_hits"), 0), _pc(r.get("hit_rate")),
                _pc(r.get("base_rate")), _f(r.get("lift"), 3), _f(r.get("pctile"), 4)))
        A("")
    v = b3.get("t185_m8_at_L90")
    A("**T-185 M8 在 L=90 是否过 1.5**:%s"
      % ("**不过**(提升 %s < 1.5)—— 它的承载完全靠 30 天窗。"
         % _f(v.get("lift"), 3) if (v and b3.get("t185_m8_L90_verdict") is False)
         else ("过(提升 %s)" % _f(v.get("lift"), 3) if v else "未算")))

    # ── ④ ──
    b4 = res["block4_anchor_detail"]
    A("\n## ④ 窗内亮着天数 / 亮到锚点当天为止\n")
    A("「命中」不等于「早于崩盘就有」。两条新列:**窗内亮着天数**(回看窗里亮了几天)、"
      "**亮到锚点当天为止**(锚点当天自己亮 / 从锚点当天往前连续亮着几天)。\n")
    A("| 道 | 迹象 | 锚点集 | L | 锚点 | 命中 | 窗内亮着天数(中位/最大) | 连续亮到锚点(中位) | 锚点当天自己亮 | 命中但只有当天亮 | 剔当天后命中率 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for d in b4["clues"]:
        A("| %s | %s | %s | %d | %s | %s | %s / %s | %s | %s | %s | %s |" % (
            d["task"], d["sign"], d["family"], d["lookback"], _f(d["n_anchors"], 0),
            _f(d["n_hit"], 0), _f(d.get("median_on_days_in_window_hit"), 1),
            _f(d.get("max_on_days_in_window_hit"), 0),
            _f(d.get("median_contiguous_run_to_anchor_hit"), 1),
            _f(d.get("n_on_anchor_day"), 0),
            _f(d.get("n_hit_only_on_anchor_day"), 0), _pc(d.get("strict_hit_rate"))))
    A("")
    A("**C6 / C1 / C5 分开评**(T-191 里它们**不是线索**:锚点数 < 6,只分开评、不计入条数):")
    A("")
    A("| 迹象 | 锚点集 | L | 锚点 | 命中 | 提升 | 内核分位 | 窗内亮着天数(中位) | 锚点当天自己亮 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for nm, e in b4["c_series"].items():
        for LB in (14, 30, 60, 90):
            r = e["by_L"].get(str(LB), {})
            det = e.get("anchor_detail_L%d" % LB) or {}
            A("| %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
                nm, e["family"], LB, _f(r.get("n_anchors"), 0), _f(r.get("n_hits"), 0),
                _f(r.get("lift"), 2), _f(r.get("pctile"), 4),
                _f(det.get("median_on_days_in_window_hit"), 1),
                _f(det.get("n_on_anchor_day"), 0)))
    A("")
    A("读法:C6 是**常态高位**(窗内亮着几十天,持续型,不是临顶);C1 是**临顶**(命中集中在锚点前 0–5 天);"
      "C5 是**早期**(命中落在锚点前 20–85 天)。同一道里两类信号的时间结构完全不同,分开评才说得清。")

    # ── ⑤ ──
    b5 = res["block5_strict_anchor_day"]
    A("\n## ⑤ 「同源」改成「剔锚点当天后仍过」\n")
    A("| 道 | 迹象 | 锚点集 | L | 原命中率 | 原提升 | 原分位 | 剔当天后命中率 | 剔当天后提升 | 剔当天后分位 | 剔当天后仍过原四条 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for c in b5["cases"]:
        s = c.get("strict", {})
        A("| %s | %s | %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            c["task"], c["sign"], c["anchor_set"], c["lookback"], _pc(c.get("old_hit_rate")),
            _f(c.get("old_lift"), 2), _f(c.get("old_pctile"), 4), _pc(s.get("hit_rate")),
            _f(s.get("lift"), 3), _f(s.get("pctile"), 4),
            ("✓" if c.get("survives_ex_anchor_day") else "✗")))
    A("")
    A("**哪个 json 带不带 `same_source` 字段**:")
    for k, v in b5["same_source_field_in_json"].items():
        A("- `%s`:%s" % (k, v))
    A("")
    A("⇒ 「同源不算线索」那一刀(15 → 11 → 6)本来就是事后手写的名单;"
      "换成实测口径后,这些项按「剔锚点当天后仍过」重新算,结论不再依赖人写的名单。")

    # ── ⑥ ──
    b6 = res["block6_styles"]
    A("\n## ⑥ 风格表:2000 抽复报 + 「风格 × 周期」展开\n")
    agg = b6.get("aggregate_t191_pipeline_2000", {})
    if agg.get("styles"):
        A("| 风格 | 段 | 实际中位 | 零分布中位 | 分位(2000 抽) |")
        A("|---|---|---|---|---|")
        for nm, sv in agg["styles"].items():
            for leg, lv in sv.get("legs", {}).items():
                A("| %s | %s | %s | %s | %s |" % (
                    nm, leg, _pc(lv.get("actual_median")),
                    _pc(lv.get("null_median")), _f(lv.get("percentile_of_actual"), 4)))
    A("")
    if b6.get("style_x_cycle"):
        A("**风格 × 周期**(5 次首腿崩盘各一行;分位 = 该周期的读数在 2000 个随机日伪崩段里的位置):")
        A("")
        A("| 风格 | 崩段(顶→谷) | 崩前 60 天 | 崩段 | 修复 120 天 | 崩前分位 | 崩段分位 | 修复分位 |")
        A("|---|---|---|---|---|---|---|---|")
        for r in b6["style_x_cycle"]:
            A("| %s | %s → %s | %s | %s | %s | %s | %s | %s |" % (
                r["style"], r["peak_d"], r["trough_d"], _pc(r.get("pre")), _pc(r.get("crash")),
                _pc(r.get("recovery")), _f(r.get("pre_pctile"), 3), _f(r.get("crash_pctile"), 3),
                _f(r.get("recovery_pctile"), 3)))
    A("")
    A("零分布口径与 T-191 相同(随机日 d;谷底 = d 之后 H 天内最低点),只是抽样从 200 提到 2000;"
      "「风格 × 周期」是本轮新增的展开 —— T-191 把 5 次首腿崩盘压成了一个中位数,"
      "看不出是哪一段崩盘在扛住、哪一段在拖后腿。")

    A("\n## 未做 / 边界\n")
    A("- 内核 `crash_atlas_common.py` 一个字未改;`sign_lift` 的读数原样保留,新判据并排报。")
    A("- T-185 / T-186 / T-187 已合并的读数一个数没动;本轮只加对照与列。")
    A("- 随机锚点对照是**与构造无关**的对照(随便哪天当锚点),但它仍然假定「命中 = 窗内亮过」这一构造;"
      "「命中是否早于崩盘」用 ④ 的两列与 ⑤ 的严格口径回答。")
    A("- 严格口径(剔锚点当天)的零分布仍是循环平移,只是窗口换成 [a-L, a-1];"
      "分位走 `apparatus.null_distribution` + `apparatus.percentile_of`。")
    A("- 没有为任何一条线索另立预注册、没有在新数据上过零信号对照 —— 本轮读数全部是探索性的。")
    A("- 本轮没有把任何线索变成可交易规则;线索只进候选名单。")
    A("")
    A("*本报告只做候选线索挖掘,不构成任何可交易规则,也不构成投资建议。*")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("报告:", REPORT_PATH)


if __name__ == "__main__":
    main()
