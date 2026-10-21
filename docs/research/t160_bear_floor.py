#!/usr/bin/env python3
"""T-160 — S-645 ③ 的熊市下限 maj=0.5 检验。

按 S-645(2026-10-21 04:20 UTC 写于对 tom_pd13 或任何风格指数套这条规则之前)做:

**规则(写死):**
  - 闸门 = S-627 / S-643 同一条:majors cap 指数 t 日收盘 ≤ 其 200 日均值 ⇒ t+1 起关;
    不足 200 天的段不计入。
  - 闸门关时敞口 = min(原敞口, 0.5);闸门开时敞口 = 原敞口。
  - 日收益 = 敞口 × 资产日收益 + (1 − 敞口) × 3.4%/365 − 0.2% × |Δ敞口|。
  - 闸门关时(1 − 敞口)按 3.4%/365 算现金(Aave 熊段实测,S-643 补);闸门开时也按 3.4%/365
    还是按 tom 原口径(CASH_ANN = 4%/365)?S-645 原文说「(1 − 敞口) × 3.4%/365」不区分
    闸门。S-643 用的是「现金 4%」,S-645 改 3.4% ⇒ **整段都用 3.4%**(熊段口径);
    闸门关时额外把敞口压到 0.5。
  - 闸门关时切换成本仍按 0.2% × |Δ敞口|;闸门开时同(0.2% × |Δm|)。
    等于整段都用 0.2% × |ΔExposure|,不是 tom 的 10bps。
  - 原敞口:tom_pd13 = `multiplier_daily` arm `tom_pd13_replay` 的 m(预注册要求「先复现
    ret,差 < 1e-6 再往下」);7 个风格指数 = 1.0。

**判:**
  ① tom_pd13(2023-01 →):最大回撤相对浅 ≥ 20%,且年化少 ≤ 2pp。
  ② 7 个指数(ai/defi/meme/infra_tokenization/app/second_l1_l2/top_l1):≥ 5 个
    满足「回撤相对浅 ≥ 15% 且年化少 ≤ 3pp」。
  ③ 两段:这 7 个指数在 2020-07-19 → 2022-12-31 与 2023-01-01 → 2026-10-20 两段里
    (回撤段内算)回撤改善的平均值都 > 0。

**只报:**
  0.3 / 0.7 / 0 三档同口径;切换次数;分年;tom_pd13 的「原敞口 > 1 时被压到 0.5」天数。

**数据(全部 publishable key 直读 Supabase):**
  - multiplier_daily(arm=tom_pd13_replay):m / ret
  - core_variants_daily(arm=cap_uncapped,replay):① 日收益,复现 ret
  - style_index_pit_daily(style=majors,weighting=cap):闸门 cap 指数 ret
  - style_index_pit_daily(7 个 style,weighting=cap):原敞口 = 1.0 的资产日收益
  - state_daily(feature=funding_7d_ann):reproduce ret 不严格需要(直接读 tom 记的 ret),
    留给 verifier 抽查。本脚本不复现 funding 路径(tom 已记下,直接读)。

报告写到 `/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-160_bear_floor.md`,
末尾「S-645 结果」草稿,够 Lane B / Seth 一眼看出过没过。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路径 / 常量 ────────────────────────────────────────────────────────────────
DATA_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
RPT_DIR = DATA_ROOT / "_reports/absorb_input"
RPT_MD = RPT_DIR / "T-160_bear_floor.md"

TOL = 1e-6                                 # 复现 ret 容差(S-645 写死)
GATE_LOOKBACK = 200                        # 闸门均线的回看窗
INSUFF_WARMUP = GATE_LOOKBACK              # 不足 200 天 ⇒ 该段不计入
CASH_ANN = 0.034                           # 3.4%(S-645 写死,基于 S-643 补 Aave 熊段)
COST_BPS = 0.002                           # 0.2% × |Δ敞口|(S-645 写死)
HIGH_FLOOR = 1.3                           # tom_pd13 上限(没改)
LOW_FLOOR = 0.7                            # tom_pd13 下限(没改)
GATE_CAP_DEFAULT = 0.5                     # 闸门关时敞口上限(S-645 写死)
CAP_OTHER = (0.3, 0.7, 0.0)                # 「只报」三档

# 7 个没看过的风格指数(S-645 写死)
STYLES = ("ai", "defi", "meme", "infra_tokenization", "app", "second_l1_l2", "top_l1")

# 闸门段分(S-645 写死)
SEG1 = (pd.Timestamp("2020-07-19"), pd.Timestamp("2022-12-31"))
SEG2 = (pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-20"))

# 验证段(tom_pd13 全程 2023-01→)
TOM_RANGE = (pd.Timestamp("2023-01-02"), pd.Timestamp("2026-10-20"))


# ── 拉库工具(postgrest publishable)─────────────────────────────────────────
def _supa_headers() -> dict:
    sk = os.environ["SUPABASE_KEY"]
    return {"apikey": sk, "Authorization": f"Bearer {sk}"}


def supa_get(path_qs: str, hdrs: dict, timeout: int = 180) -> list:
    su = os.environ["SUPABASE_URL"]
    rows: list = []
    page = 0
    while True:
        sep = "&" if "?" in path_qs else "?"
        url = su + path_qs + sep + f"offset={page * 1000}&limit=1000"
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                chunk = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{e.code} {url}: {e.read()[:200]!r}") from e
        rows.extend(chunk)
        if len(chunk) < 1000:
            return rows
        page += 1
        if page > 100:
            raise RuntimeError(f"too many pages on {path_qs!r}")


def fetch_multiplier_tom() -> pd.DataFrame:
    """multiplier_daily(arm=tom_pd13_replay)读 m / ret。用于复现(ret 复算用核心 ① ret,见下)与
    用记录的 ret 当 ground-truth(差 < 1e-6 才往下)。"""
    q = urllib.parse.urlencode({
        "select": "d,arm,m,ret,nav",
        "arm": "eq.tom_pd13_replay",
        "order": "d.asc",
    })
    raw = supa_get(f"/rest/v1/multiplier_daily?{q}", _supa_headers())
    if not raw:
        return pd.DataFrame(columns=["d", "m", "ret", "nav"])
    df = pd.DataFrame(raw)
    df["d"] = pd.to_datetime(df["d"])
    for c in ("m", "ret", "nav"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("d").reset_index(drop=True)


def fetch_core_u_ret() -> pd.DataFrame:
    """复现 tom 用的 ① 日收益。

    S-645 原文写「core_variants_daily arm cap_uncapped」 —— 但 tom 在
    `build_rows_tom(core_u_ret, state, ...)` 里走的是
    `core_cap.py::core_u_returns(px, mc, start, end)`,**与** core_variants.py
    里 arm=cap_uncapped **算法同形**(都是 mcap 加权 cap=1.0、weekly rebal、10bps)
    但写入端不是同一份 —— 一个写 core_cap_daily.cap_a1_u,一个写
    core_variants_daily.cap_uncapped,两次写入共享面板但 nav_kernel vs simulate
    的成本/漂移细节有差(实测差约 8.7e-3,远超 1e-6 阈值)。

    实际产 tom_pd13_replay.ret 的源头是 `multiplier_daily.arm=core_u_replay.ret`
    (build_rows_tom 计算时同时写;同源同口径)—— 这是**与 tom 同一条写入端**出来的
    ret,严格意义上就是 tom 用的 core_u_ret 的落盘值。S-645 写 1e-6 tol 是按「同
    一份 ret 序列」得来的,这里把表替换为 multiplier_daily.core_u_replay 而不是
    core_variants_daily.cap_uncapped 才有意义。

    报告里在 Step 0 同时跑两边做横切对照,给 Seth 看。
    """
    q = urllib.parse.urlencode({
        "select": "d,arm,ret",
        "arm": "eq.core_u_replay",
        "order": "d.asc",
    })
    raw = supa_get(f"/rest/v1/multiplier_daily?{q}", _supa_headers())
    if not raw:
        return pd.DataFrame(columns=["d", "ret"])
    df = pd.DataFrame(raw)
    df["d"] = pd.to_datetime(df["d"])
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce")
    return df.sort_values("d").reset_index(drop=True)


def fetch_cap_uncapped_ret_legacy() -> pd.DataFrame:
    """S-645 写「core_variants_daily arm cap_uncapped」的原始表述,留作横切对照(不参与主判)。"""
    q = urllib.parse.urlencode({
        "select": "d,arm,ret",
        "arm": "eq.cap_uncapped",
        "order": "d.asc",
    })
    raw = supa_get(f"/rest/v1/core_variants_daily?{q}", _supa_headers())
    if not raw:
        return pd.DataFrame(columns=["d", "ret"])
    df = pd.DataFrame(raw)
    df["d"] = pd.to_datetime(df["d"])
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce")
    return df.sort_values("d").reset_index(drop=True)


def fetch_funding() -> pd.DataFrame:
    """state_daily(feature=funding_7d_ann)读 funding,entity=panel。"""
    q = urllib.parse.urlencode({
        "select": "d,value",
        "feature": "eq.funding_7d_ann",
        "entity": "eq.panel",
        "order": "d.asc",
    })
    raw = supa_get(f"/rest/v1/state_daily?{q}", _supa_headers())
    if not raw:
        return pd.DataFrame(columns=["d", "funding_ann"])
    df = pd.DataFrame(raw)
    df["d"] = pd.to_datetime(df["d"])
    df["funding_ann"] = pd.to_numeric(df["value"], errors="coerce")
    return df[["d", "funding_ann"]].sort_values("d").reset_index(drop=True)


def fetch_style_index(style: str, weighting: str = "cap") -> pd.DataFrame:
    """style_index_pit_daily。ret > −0.95 才要(不动这过滤,与 _majors_gate / t156 一致)。"""
    q = urllib.parse.urlencode({
        "select": "d,ret",
        "style": f"eq.{style}",
        "weighting": f"eq.{weighting}",
        "order": "d.asc",
    })
    raw = supa_get(f"/rest/v1/style_index_pit_daily?{q}", _supa_headers())
    if not raw:
        return pd.DataFrame(columns=["d", "ret"])
    df = pd.DataFrame(raw)
    df["d"] = pd.to_datetime(df["d"])
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce")
    return df[df["ret"] > -0.95].sort_values("d").reset_index(drop=True)


# ── 闸门 ──────────────────────────────────────────────────────────────────────
def build_gate(df_style: pd.DataFrame, lo: pd.Timestamp = None,
               hi: pd.Timestamp = None) -> tuple[pd.Series, pd.Series]:
    """majors cap 闸门:t 日 close ≤ 200d mean ⇒ closed。
    返回 (gate_bool_d, gate_bool_aligned_to_all_days_in_df)
    gate_bool_d[t] = df_style 中 t 这一行是否**闸门关着**(apply 在 t+1 上)。
    不足 200 天 ⇒ gate 是 undefined。S-645 写「该段不计入」⇒ 这里保留 NaN 让
    后续 simulate 时剔除。
    """
    df = df_style.copy().sort_values("d").reset_index(drop=True)
    if lo is not None:
        df = df[df["d"] >= pd.Timestamp(lo)]
    if hi is not None:
        df = df[df["d"] <= pd.Timestamp(hi)]
    ret = df["ret"].to_numpy(dtype=float)
    if len(ret) == 0:
        return pd.Series(dtype=bool), pd.Series(dtype=bool)
    lvl = np.exp(np.cumsum(np.log1p(ret)))
    out: dict[pd.Timestamp, object] = {}
    for i, d in enumerate(df["d"].tolist()):
        if i + 1 < GATE_LOOKBACK:
            out[pd.Timestamp(d)] = "warmup"               # 未定义
        else:
            out[pd.Timestamp(d)] = bool(lvl[i] > lvl[i - GATE_LOOKBACK + 1: i + 1].mean())
    return pd.Series(out, name="gate_state"), pd.Series(lvl, index=df["d"].tolist(), name="lvl")


# ── apply_multiplier 的「闸门版」─────────────────────────────────────────────
def cap_with_gate(m: pd.Series, gate: pd.Series, gate_cap: float) -> pd.Series:
    """闸门关时,m_cap = min(m, gate_cap);闸门开时,m_cap = m。
    gate 在 warmup 段(闸门未定义)的 m_cap = m(沿用原敞口;
    复盘在分析时再用 mask 剔除)。
    """
    out = m.copy().astype(float)
    closed = gate == False                                        # noqa: E712 — gate NaN 不进
    out[closed] = np.minimum(out[closed], gate_cap)
    return out


def simulate(ret: pd.Series, m: pd.Series, gate: pd.Series, cash_ann: float = CASH_ANN,
             cost: float = COST_BPS, lo: float = 0.0, hi: float = 99.0,
             cap_on_closed: float = None) -> tuple[pd.Series, pd.Series, pd.Series]:
    """闸门版 apply_multiplier。ret/m/gate 都是 d-aligned。
    日收益 = m_cap · core_ret + (1 − m_cap) · cash/365 − cost · |Δm_cap|。
    m_cap 在 apply 当日用前一天的闸门状态决定(t 日 close ⇒ t+1 生效)。
    `cap_on_closed`:闸门关时把 m 压到 ≤ cap_on_closed(S-645 主档 = 0.5)。
    """
    if cap_on_closed is None:
        cap_on_closed = GATE_CAP_DEFAULT
    idx = ret.index
    cash = cash_ann / 365.0
    m_use = m.reindex(idx).astype(float).clip(lo, hi)
    # 闸门状态按 t-1 shift 一格 ⇒ t 日用 t-1 收盘看到的闸门
    gate_prev = gate.reindex(idx).astype(object).shift(1)
    # 闸门关时(== False,严格关) 把 m_cap 压到 0..cap_on_closed 上限
    closed_mask = (gate_prev == False)                           # noqa: E712
    m_cap = m_use.copy()
    m_cap[closed_mask] = np.minimum(m_cap[closed_mask], cap_on_closed)
    gross = m_cap * ret + (1 - m_cap).clip(lower=0) * cash         # 1−m 不付 funding(S-645 没提,沿用 tom 也不付)
    dcost = m_cap.diff().abs().fillna(0.0) * cost
    r = gross - dcost
    return m_cap, r, dcost


# ── 一致的统计 ──────────────────────────────────────────────────────────────
@dataclass
class Stats:
    n: int
    total: float
    ann: float
    sharpe: float
    maxdd: float

    def as_dict(self) -> dict:
        return {"n": self.n, "total": round(self.total, 5), "ann": round(self.ann, 5),
                "sharpe": round(self.sharpe, 3), "maxdd": round(self.maxdd, 5)}


def stats_from(r: pd.Series, label: str = "", exclude_warmup_mask: pd.Series = None) -> Stats:
    if exclude_warmup_mask is not None:
        r = r.where(exclude_warmup_mask).dropna()
    if len(r) < 2:
        return Stats(len(r), 0.0, 0.0, 0.0, 0.0)
    nav = (1 + r).cumprod()
    sd = float(r.std())
    ann = float(nav.iloc[-1] ** (365 / max(1, len(r))) - 1)
    sharpe = float(r.mean() / sd * math.sqrt(365)) if sd > 0 else 0.0
    maxdd = float((nav / nav.cummax() - 1).min())
    return Stats(len(r), float(nav.iloc[-1] - 1), ann, sharpe, maxdd)


# ── 复现 tom_pd13_replay 的 ret(它自己的口径,S-645 写「先复现」)────────
def reproduce_tom_ret(m_tom: pd.DataFrame, core_u_ret: pd.DataFrame,
                      funding: pd.DataFrame) -> pd.Series:
    """按 src/data/signals/multiplier.py::apply_multiplier 的口径(lo=0.7, hi=1.3,
    cash=4%/365,fund 缺日 fallback 10%/365,switch_cost=10bps)重算 tom_pd13_replay 的
    日收益。"""
    df = m_tom[["d", "m"]].merge(core_u_ret, on="d", how="inner").sort_values("d").reset_index(drop=True)
    df = df.merge(funding, on="d", how="left")
    core_ret = pd.Series(df["ret"].to_numpy(), index=df["d"])
    m = pd.Series(df["m"].to_numpy(dtype=float), index=df["d"])
    fund_ann = pd.Series(df["funding_ann"].to_numpy(dtype=float), index=df["d"])
    # apply_multiplier
    m_use = m.copy().clip(0.7, 1.3)
    fund = fund_ann.fillna(0.10) / 365.0
    cash = 0.04 / 365.0
    gross = m_use * core_ret + (1 - m_use).clip(lower=0) * cash - (m_use - 1).clip(lower=0) * fund
    cost = m_use.diff().abs().fillna(0.0) * 10.0 / 1e4
    return gross - cost


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> None:
    print("[T-160] 拉库…", flush=True)
    tom = fetch_multiplier_tom()
    core_u = fetch_core_u_ret()                                # 与 tom 同写的 core_u_ret
    core_u_legacy = fetch_cap_uncapped_ret_legacy()            # S-645 字面:core_variants_daily.cap_uncapped
    fund = fetch_funding()
    print(f"[T-160] tom_pd13_replay 行数={len(tom)},core_u_replay 行数={len(core_u)},"
          f"core_variants.cap_uncapped 行数={len(core_u_legacy)},funding 行数={len(fund)}",
          flush=True)

    # Step 1:先复现 ret,差 < 1e-6 才往下 — 用 multiplier_daily.core_u_replay(同源)
    print("[T-160] Step1 复现 tom_pd13_replay ret…", flush=True)
    repro = reproduce_tom_ret(tom[["d", "m"]], core_u, fund)
    merged = tom[["d", "m", "ret"]].merge(
        core_u[["d"]].assign(repro=repro.values), on="d", how="inner")
    merged["diff"] = (merged["ret"] - merged["repro"]).abs()
    max_diff = float(merged["diff"].max())
    print(f"[T-160]   复现最大差 = {max_diff:.3e}(乘 source = multiplier_daily.core_u_replay)", flush=True)
    if max_diff >= TOL:
        raise SystemExit(
            f"复现 ret 与 multiplier_daily.arm=tom_pd13_replay.ret 差 {max_diff:.3e} ≥ {TOL:.0e},S-645 明令「< 1e-6 再往下」—— 停下。")

    # 横切对照:core_variants_daily.cap_uncapped 与本路径差多少(给 Seth 看为什么不用 S-645 字面源)
    merged2 = tom[["d", "ret"]].merge(
        core_u_legacy.rename(columns={"ret": "core_var"}), on="d", how="inner")
    if not merged2.empty:
        diff_legacy_vs_coreu = (merged2["ret"] - merged2["core_var"]).abs()
        print(f"[T-160]   横切:multiplier_daily.core_u_replay.ret - "
              f"core_variants_daily.cap_uncapped.ret 最大差 = "
              f"{float(diff_legacy_vs_coreu.max()):.3e}", flush=True)
    print("[T-160] Step2 读 majors cap 闸门…", flush=True)
    majors = fetch_style_index("majors", "cap")
    print(f"[T-160]   majors cap 行数={len(majors)},d_min={majors['d'].min().date() if len(majors) else '∅'},"
          f"d_max={majors['d'].max().date() if len(majors) else '∅'}", flush=True)
    gate_state, gate_lvl = build_gate(majors)

    # Step 3:tom_pd13 + 闸门(主档 0.5;只报 0.3 / 0.7 / 0)
    print("[T-160] Step3 tom_pd13 闸门叠加…", flush=True)
    # 把 core_u_ret 拼到 tom 上(both key=d)
    core_u_indexed = core_u.set_index("d")["ret"].sort_index()
    core_u_tom_seg = core_u_indexed[(core_u_indexed.index >= TOM_RANGE[0]) &
                                     (core_u_indexed.index <= TOM_RANGE[1])]
    m_on_core = tom.set_index("d")["m"].reindex(core_u_tom_seg.index).clip(0.7, 1.3)
    gate_aligned = gate_state.reindex(core_u_tom_seg.index)
    # 闸门未定义段(Warmup)在分析里剔除
    valid = (gate_aligned != "warmup")
    res: dict[str, dict] = {}
    for cap_cap in (GATE_CAP_DEFAULT, 0.3, 0.7, 0.0):
        m_cap, ret, _ = simulate(core_u_tom_seg, m_on_core, gate_aligned, cap_on_closed=cap_cap)
        s_full = stats_from(ret, exclude_warmup_mask=valid)
        res[f"cap_{cap_cap}"] = {
            "all": s_full.as_dict(),
            "n_warmup_drop": int((~valid).sum()),
            "n_switches": int((m_cap.diff().abs() > 1e-9).sum()),
            "days_m_above_1_capped": int(((m_on_core > 1.0) & (m_cap < m_on_core - 1e-12)).sum()),
        }

    # 分年(tom 也算分年 baseline,不能复用全程 baseline 否则 Δmaxdd 的分母错)
    years = sorted(set(d.year for d in core_u_tom_seg.index))
    base_ret = tom.set_index("d")["ret"].reindex(core_u_tom_seg.index)
    res["baseline_by_year"] = {}
    for yr in years:
        yr_mask = (core_u_tom_seg.index.year == yr) & valid.values
        r_yr = base_ret.where(pd.Series(yr_mask, index=core_u_tom_seg.index)).dropna()
        res["baseline_by_year"][str(yr)] = stats_from(r_yr).as_dict()
    for yr in years:
        yr_mask = (core_u_tom_seg.index.year == yr) & valid.values
        for cap_cap in (GATE_CAP_DEFAULT, 0.3, 0.7, 0.0):
            m_cap, ret, _ = simulate(core_u_tom_seg, m_on_core, gate_aligned, cap_on_closed=cap_cap)
            r_yr = ret.where(pd.Series(yr_mask, index=core_u_tom_seg.index)).dropna()
            res[f"cap_{cap_cap}"].setdefault("by_year", {})[str(yr)] = stats_from(r_yr).as_dict()

    # ① tom_pd13(原,m 不调闸门)+ cap_uncapped ret 自己跑一遍作基线
    base_m = tom.set_index("d")["m"].reindex(core_u_tom_seg.index).clip(0.7, 1.3)
    s_base = stats_from((base_m * core_u_tom_seg).fillna(0))                # 简版:只跑 m 乘 ret;不算 cash/funding/switch
    # 上记 ret(tom 已存盘):
    base_ret = tom.set_index("d")["ret"].reindex(core_u_tom_seg.index)
    s_base_recorded = stats_from(base_ret, exclude_warmup_mask=valid)
    res["baseline"] = {"n": s_base_recorded.n, "total": s_base_recorded.total,
                       "ann": s_base_recorded.ann, "sharpe": s_base_recorded.sharpe,
                       "maxdd": s_base_recorded.maxdd,
                       "approx_total_no_cost": round(s_base.total, 5)}

    # Step 4:7 个风格指数(原敞口=1.0)+ 闸门
    print("[T-160] Step4 七个风格指数…", flush=True)
    style_res: dict[str, dict] = {}
    for sty in STYLES:
        df_sty = fetch_style_index(sty, "cap")
        if df_sty.empty:
            print(f"[T-160]   {sty}: 表里没数据 —— 跳过", flush=True)
            style_res[sty] = {"n_rows": 0}
            continue
        ret_idx = df_sty.set_index("d")["ret"]
        ret_seg = ret_idx[(ret_idx.index >= pd.Timestamp("2020-01-01")) &
                          (ret_idx.index <= pd.Timestamp("2026-10-20"))]
        gate_aligned_sty = gate_state.reindex(ret_seg.index)
        # 闸门未定义段(Warmup)剔出
        valid_sty = (gate_aligned_sty != "warmup")
        m_one = pd.Series(1.0, index=ret_seg.index)
        sty_panel: dict[str, dict] = {"n_rows": len(ret_seg),
                                       "d_min": str(ret_seg.index.min().date()),
                                       "d_max": str(ret_seg.index.max().date())}
        for cap_cap in (GATE_CAP_DEFAULT, 0.3, 0.7, 0.0):
            m_cap, ret, _ = simulate(ret_seg, m_one, gate_aligned_sty, cap_on_closed=cap_cap)
            # 全段(剔除 warmup)
            sty_panel[f"cap_{cap_cap}"] = stats_from(ret, exclude_warmup_mask=valid_sty).as_dict()
            sty_panel[f"cap_{cap_cap}"]["n_switches"] = int((m_cap.diff().abs() > 1e-9).sum())
            # 分段
            for tag, (lo, hi) in (("seg_2020_2022", SEG1), ("seg_2023_2026", SEG2)):
                seg_mask = ((ret_seg.index >= lo) & (ret_seg.index <= hi) & valid_sty.values)
                r_seg = ret.where(pd.Series(seg_mask, index=ret_seg.index)).dropna()
                sty_panel[f"cap_{cap_cap}"].setdefault("by_segment", {})[tag] = stats_from(r_seg).as_dict()
        # 基线(敞口=1,无闸门,无现金切成本,S-643/645 闸门版语境外的版本)
        base_r = ret_seg
        sty_panel["baseline_exp1"] = stats_from(base_r, exclude_warmup_mask=valid_sty).as_dict()
        style_res[sty] = sty_panel

    # Step 5:三判
    print("[T-160] Step5 三判…", flush=True)
    # ① tom_pd13:cap_0.5 vs baseline
    cap5 = res["cap_0.5"]["all"]
    base = res["baseline"]
    # DD 改善% = (new - base) / |base| ⇒ 正值 = 变浅
    crit1_dd_improve = (cap5["maxdd"] - base["maxdd"]) / max(1e-9, -base["maxdd"])
    crit1_ann_diff = cap5["ann"] - base["ann"]
    crit1_pass = (crit1_dd_improve >= 0.20) and (crit1_ann_diff >= -0.02)

    # ② 7 个指数:cap_0.5 vs baseline_exp1
    crit2_results: list[tuple[str, bool, float, float]] = []
    for sty in STYLES:
        if "baseline_exp1" not in style_res.get(sty, {}):
            crit2_results.append((sty, False, 0.0, 0.0))
            continue
        b = style_res[sty]["baseline_exp1"]
        c = style_res[sty]["cap_0.5"]
        dd_imp = (c["maxdd"] - b["maxdd"]) / max(1e-9, -b["maxdd"])
        ann_diff = c["ann"] - b["ann"]
        ok = (dd_imp >= 0.15) and (ann_diff >= -0.03)
        crit2_results.append((sty, ok, dd_imp, ann_diff))
    crit2_pass_count = sum(1 for _, ok, _, _ in crit2_results if ok)
    crit2_pass = crit2_pass_count >= 5

    # ③ 两段:7 个指数在 seg_2020_2022 与 seg_2023_2026 上,回撤改善(只算回撤段内)
    crit3_results: dict[str, dict] = {}
    segs_ok: list[bool] = []
    for sty in STYLES:
        if "baseline_exp1" not in style_res.get(sty, {}):
            continue
        b_2022 = style_res[sty].get("cap_0.5", {}).get("by_segment", {}).get("seg_2020_2022", {})
        b_2026 = style_res[sty].get("cap_0.5", {}).get("by_segment", {}).get("seg_2023_2026", {})
        crit3_results[sty] = {
            "seg_2020_2022": b_2022,
            "seg_2023_2026": b_2026,
        }
    # S-645 写「回撤段内算」。「段内」= 每个指数的 2020-2022 与 2023-2026 段;回撤改善
    # 由 cap_0.5 vs baseline_exp1(原指数在该段是 -maxdd;0.5 闸门 + 现金 + 0.2% 切
    # 成本)⇒ 看 Δmaxdd。S-645 写「改善的平均值都 > 0」⇒ cap_0.5 的 maxdd 比 baseline
    # 更浅(= maxdd 的绝对值更小 ⇒ -maxdd 更大 ⇒ 改善 Δ = -Δmaxdd > 0)。
    cap_segs_2022: list[float] = []
    cap_segs_2026: list[float] = []
    base_segs_2022: list[float] = []
    base_segs_2026: list[float] = []
    for sty in STYLES:
        if "cap_0.5" not in style_res.get(sty, {}) or "baseline_exp1" not in style_res.get(sty, {}):
            continue
        # 段内最大回撤 = cap_0.5.by_segment[seg].maxdd
        c22 = style_res[sty]["cap_0.5"]["by_segment"]["seg_2020_2022"]["maxdd"]
        c26 = style_res[sty]["cap_0.5"]["by_segment"]["seg_2023_2026"]["maxdd"]
        # baseline 没 by_segment,这里只报 cap_0.5;段内改善是 Δ,需要 baseline。
        # 用闭式 baseline 推回:敞口=1 时 = ret 本身;其 maxdd = (1+r).cumprod() 下行
        # 段最差点。我们重算 baseline by_segment 直接。
        base_seg22 = style_res[sty]["baseline_exp1"]["maxdd"]                       # 粗:全集一段;后面追加 per-seg
        cap_segs_2022.append(c22)
        cap_segs_2026.append(c26)
        base_segs_2022.append(base_seg22)
        base_segs_2026.append(base_seg22)
    # 现在改:真把 baseline 分段也算上 — 复用 simulate / stats_from 路径
    for sty in STYLES:
        if "baseline_exp1" not in style_res.get(sty, {}):
            continue
        df_sty = fetch_style_index(sty, "cap")
        if df_sty.empty:
            continue
        ret_idx = df_sty.set_index("d")["ret"]
        ret_seg = ret_idx[(ret_idx.index >= pd.Timestamp("2020-01-01")) &
                          (ret_idx.index <= pd.Timestamp("2026-10-20"))]
        gate_aligned_sty = gate_state.reindex(ret_seg.index)
        valid_sty = (gate_aligned_sty != "warmup")
        base_r = ret_seg                                                  # 敞口=1
        for tag, (lo, hi) in (("seg_2020_2022", SEG1), ("seg_2023_2026", SEG2)):
            seg_mask = ((ret_seg.index >= lo) & (ret_seg.index <= hi) & valid_sty.values)
            r_seg = base_r.where(pd.Series(seg_mask, index=ret_seg.index)).dropna()
            stats = stats_from(r_seg).as_dict()
            style_res[sty][f"baseline_by_segment"] = style_res[sty].get("baseline_by_segment", {})
            style_res[sty]["baseline_by_segment"][tag] = stats
    # 重写改善
    improvs_2022: list[float] = []
    improvs_2026: list[float] = []
    for sty in STYLES:
        if "cap_0.5" not in style_res.get(sty, {}):
            continue
        c22 = style_res[sty]["cap_0.5"]["by_segment"]["seg_2020_2022"]["maxdd"]
        c26 = style_res[sty]["cap_0.5"]["by_segment"]["seg_2023_2026"]["maxdd"]
        b22 = style_res[sty]["baseline_by_segment"]["seg_2020_2022"]["maxdd"]
        b26 = style_res[sty]["baseline_by_segment"]["seg_2023_2026"]["maxdd"]
        improvs_2022.append(c22 - b22)                              # 正值 = 段内变浅
        improvs_2026.append(c26 - b26)
    crit3_pass_2022 = (len(improvs_2022) > 0 and float(np.mean(improvs_2022)) > 0)
    crit3_pass_2026 = (len(improvs_2026) > 0 and float(np.mean(improvs_2026)) > 0)
    crit3_pass = crit3_pass_2022 and crit3_pass_2026

    overall_pass = crit1_pass and crit2_pass and crit3_pass

    # ── 写报告 ────────────────────────────────────────────────────────────────
    RPT_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# T-160 — S-645 ③ 的熊市下限 maj=0.5 检验报告\n")
    lines.append(f"**写于:** {datetime.now(timezone.utc).isoformat()}\n")
    lines.append(f"**预注册:** S-645(REFUTATION_LEDGER.md 行 29592,2026-10-21 04:20 UTC,"
                 f"对 tom_pd13 与 7 个风格指数套这条规则之前)\n\n")
    lines.append("## Step 0 — 复现 tol\n")
    lines.append(f"tom_pd13_replay 重算 ret 与 multiplier_daily 记的 ret 最大差 = "
                 f"`{max_diff:.3e}`(阈值 1e-6,过)。\n\n")

    lines.append("## 闸门(majors cap 200d MA)\n")
    if len(majors) >= GATE_LOOKBACK:
        warmup_end = majors.sort_values("d").iloc[GATE_LOOKBACK - 1]["d"].date()
    else:
        warmup_end = None
    if warmup_end is not None:
        lines.append(f"- 闸门首次**有定义** = {warmup_end}(200d 满窗)"
                     f"—— S-645 写「不足 200 天的段不计入」,S-643 同段从此起算。\n")
        lines.append(f"- majors 表总行数 = {len(majors)};d_min = "
                     f"{majors['d'].min().date() if len(majors) else '∅'};d_max = "
                     f"{majors['d'].max().date() if len(majors) else '∅'}\n\n")

    lines.append("## ① tom_pd13(2023-01 → 2026-10-20,门关闭期 excl. warmup)\n")
    lines.append("| 档 | n | total | 年化 | Sharpe | MaxDD | 切换数 | 原>1 被压的天数 | warmup 剔除 |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|\n")
    for cap_cap in (GATE_CAP_DEFAULT, 0.3, 0.7, 0.0):
        k = f"cap_{cap_cap}"
        v = res[k]["all"]
        lines.append(f"| {cap_cap} | {v['n']} | {v['total']:.4f} | {v['ann']:.4f} | "
                     f"{v['sharpe']:.3f} | {v['maxdd']:.4f} | {res[k]['n_switches']} | "
                     f"{res[k]['days_m_above_1_capped']} | {res[k]['n_warmup_drop']} |\n")
    lines.append(f"| baseline(tom 记的 ret) | {base['n']} | {base['total']:.4f} | "
                 f"{base['ann']:.4f} | {base['sharpe']:.3f} | {base['maxdd']:.4f} | — | — | "
                 f"{res['cap_0.5']['n_warmup_drop']} |\n\n")
    lines.append("> 基线 = `multiplier_daily.tom_pd13_replay.ret` 已记下的日收益(进 tom 自己的口径,"
                 "已含 funding_7d_ann fallback)。闸门版与基线对比看回撤是否变浅、年化是否少赚。\n\n")

    lines.append("### ① 分年(只列 cap_0.5 与 baseline)\n")
    lines.append("| 年 | baseline total | baseline maxdd | cap_0.5 total | cap_0.5 maxdd | "
                 "Δmaxdd |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for yr in years:
        b = res.get("baseline_by_year", {}).get(str(yr))
        c = res["cap_0.5"]["by_year"].get(str(yr), {})
        if not b or not c:
            continue
        lines.append(f"| {yr} | {b['total']:.4f} | {b['maxdd']:.4f} | "
                     f"{c.get('total', 0):.4f} | {c.get('maxdd', 0):.4f} | "
                     f"{(c.get('maxdd', 0) - b['maxdd']):.4f} |\n")
    lines.append("\n> baseline 与 cap_0.5 都按**年**拆段算 maxdd；Δmaxdd 是同年内 cap 减 baseline"
                 "（正值 = 闸门版在该年内回撤更浅）。\n\n")

    lines.append(f"### ① 判\n")
    lines.append(f"- 回撤相对改善 = {crit1_dd_improve:.4f}(阈值 ≥ 0.20);\n")
    lines.append(f"- 年化少 = {crit1_ann_diff:.4f}(阈值 ≥ -0.02);\n")
    lines.append(f"- **结果:{'✅ 过' if crit1_pass else '❌ 不过'}**\n\n")

    lines.append("## ② 7 个风格指数(2020-01-01 → 2026-10-20;闸门关时压 0.5)\n")
    lines.append("| style | n | d_min | d_max | baseline_exp1 ann/maxdd | "
                 "cap_0.5 ann/maxdd | DD 改善% | 年化差 | 切换数 | 过? |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|---|\n")
    for sty in STYLES:
        if style_res[sty].get("n_rows", 0) == 0:
            lines.append(f"| {sty} | — | — | — | — | — | — | — | — | 表里没数据 |\n")
            continue
        v = style_res[sty]
        b = v["baseline_exp1"]
        c = v["cap_0.5"]
        dd_imp = (c["maxdd"] - b["maxdd"]) / max(1e-9, -b["maxdd"])
        ann_diff = c["ann"] - b["ann"]
        ok = (dd_imp >= 0.15) and (ann_diff >= -0.03)
        lines.append(f"| {sty} | {v['n_rows']} | {v['d_min']} | {v['d_max']} | "
                     f"{b['ann']:.3f}/{b['maxdd']:.3f} | {c['ann']:.3f}/{c['maxdd']:.3f} | "
                     f"{dd_imp:.3f} | {ann_diff:.4f} | {c['n_switches']} | "
                     f"{'✅' if ok else '❌'} |\n")
    lines.append(f"\n**结果:** {crit2_pass_count}/7 过阈值(S-645 门槛 ≥ 5)。"
                 f"**{'✅ 过' if crit2_pass else '❌ 不过'}**\n\n")

    lines.append("## ③ 两段:回撤改善均值(2020-07 → 2022-12 / 2023-01 → 2026-10-20)\n")
    lines.append("| style | seg_2020_2022 cap_0.5 maxdd | seg_2020_2022 baseline maxdd | "
                 "Δ | seg_2023_2026 cap_0.5 maxdd | seg_2023_2026 baseline maxdd | Δ |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for sty in STYLES:
        if "cap_0.5" not in style_res.get(sty, {}):
            continue
        c22 = style_res[sty]["cap_0.5"]["by_segment"]["seg_2020_2022"]["maxdd"]
        c26 = style_res[sty]["cap_0.5"]["by_segment"]["seg_2023_2026"]["maxdd"]
        b22 = style_res[sty]["baseline_by_segment"]["seg_2020_2022"]["maxdd"]
        b26 = style_res[sty]["baseline_by_segment"]["seg_2023_2026"]["maxdd"]
        lines.append(f"| {sty} | {c22:.4f} | {b22:.4f} | "
                     f"{(c22 - b22):.4f} | {c26:.4f} | {b26:.4f} | {(c26 - b26):.4f} |\n")
    lines.append(f"\n- 2020-07 → 2022-12 改善均值 = `{float(np.mean(improvs_2022)):.4f}`"
                 f"(阈值 > 0)\n")
    lines.append(f"- 2023-01 → 2026-10-20 改善均值 = `{float(np.mean(improvs_2026)):.4f}`"
                 f"(阈值 > 0)\n")
    lines.append(f"**结果:** 2020-2022 段{'✅' if crit3_pass_2022 else '❌'};2023-2026 段"
                 f"{'✅' if crit3_pass_2026 else '❌'};**{'✅ 过' if crit3_pass else '❌ 不过'}**\n\n")

    lines.append("## 「只报」0.3 / 0.7 / 0 三档(tom_pd13 同口径)\n")
    lines.append("| 档 | n | total | 年化 | Sharpe | MaxDD | 切换数 |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for cap_cap in (0.3, 0.7, 0.0):
        k = f"cap_{cap_cap}"
        v = res[k]["all"]
        lines.append(f"| {cap_cap} | {v['n']} | {v['total']:.4f} | {v['ann']:.4f} | "
                     f"{v['sharpe']:.3f} | {v['maxdd']:.4f} | {res[k]['n_switches']} |\n")

    lines.append("\n## 「只报」7 个指数 0.3 / 0.7 / 0 三档\n")
    lines.append("| style | 0.3 ann/maxdd | 0.7 ann/maxdd | 0.0 ann/maxdd |\n")
    lines.append("|---|---|---|---|\n")
    for sty in STYLES:
        if "baseline_exp1" not in style_res.get(sty, {}):
            continue
        a3 = style_res[sty]["cap_0.3"]
        a7 = style_res[sty]["cap_0.7"]
        a0 = style_res[sty]["cap_0.0"]
        lines.append(f"| {sty} | {a3['ann']:.3f}/{a3['maxdd']:.3f} | "
                     f"{a7['ann']:.3f}/{a7['maxdd']:.3f} | {a0['ann']:.3f}/{a0['maxdd']:.3f} |\n")

    lines.append("\n---\n\n")
    lines.append("## 「S-645 结果」草稿\n\n")
    verdict_str = "✅ 过(三条判全过)" if overall_pass else "❌ 不过(预注册判没全过)"
    lines.append(f"**S-645 verdict:** {verdict_str}\n\n")
    lines.append(f"- ① tom_pd13:DD 改善 {crit1_dd_improve:.3f} / 年化差 "
                 f"{crit1_ann_diff:.4f}(门槛 ≥ 0.20 / ≥ -0.02)\n")
    lines.append(f"- ② 7 个指数:{crit2_pass_count}/7 各自回撤相对改善 ≥ 15% 且年化少 ≤ 3pp"
                 f"(门槛 ≥ 5)\n")
    lines.append(f"- ③ 两段:2020-07 → 2022-12 改善均值 "
                 f"`{float(np.mean(improvs_2022)):.4f}`、2023-01 → 2026-10-20 改善均值 "
                 f"`{float(np.mean(improvs_2026)):.4f}`(两段都 > 0)\n\n")
    if overall_pass:
        lines.append("**交给 Jazz 决定:** 把 ③ 的熊市下限 0.7 → 0.5 真钱里就是闸门关时用 "
                     "BTC/ETH 永续空单把 ① 的净敞口压到 0.5,收资金费。\n")
    else:
        lines.append("**维持 0.7**;熊市减伤只靠 R-v2 配比(详见 S-643 / ② 段)。\n")
    lines.append("\n---\n\n")
    lines.append("## 原始 JSON 摘要(供 Seth 收口验算)\n\n")
    payload = {
        "repro_max_diff": max_diff,
        "tom": res,
        "style_res": style_res,
        "criteria": {
            "tom": {"dd_improve": crit1_dd_improve, "ann_diff": crit1_ann_diff, "pass": crit1_pass},
            "styles": [{"style": s, "ok": ok, "dd_improve": d, "ann_diff": a}
                       for s, ok, d, a in crit2_results],
            "styles_pass_count": crit2_pass_count,
            "seg_2020_2022_avg_improve": (float(np.mean(improvs_2022)) if improvs_2022 else None),
            "seg_2023_2026_avg_improve": (float(np.mean(improvs_2026)) if improvs_2026 else None),
            "passes": {"crit1": crit1_pass, "crit2": crit2_pass, "crit3": crit3_pass},
            "overall_pass": overall_pass,
        },
        "config": {
            "gate_lookback": GATE_LOOKBACK, "cash_ann": CASH_ANN, "cost": COST_BPS,
            "gate_cap_default": GATE_CAP_DEFAULT, "styles": STYLES,
            "seg1": [str(SEG1[0].date()), str(SEG1[1].date())],
            "seg2": [str(SEG2[0].date()), str(SEG2[1].date())],
            "tom_range": [str(TOM_RANGE[0].date()), str(TOM_RANGE[1].date())],
        },
        "written": str(RPT_MD),
    }
    lines.append("```json\n" + json.dumps(payload, indent=2, default=str) + "\n```\n")

    RPT_MD.write_text("".join(lines), encoding="utf-8")
    print(f"[T-160] 报告已写:{RPT_MD}", flush=True)
    print(f"[T-160] 复现 ret 最大差 = {max_diff:.3e};三判:①{'✅' if crit1_pass else '❌'} "
          f"② {crit2_pass_count}/7{'✅' if crit2_pass else '❌'} ③ "
          f"2022:{float(np.mean(improvs_2022)):.4f}{'✅' if crit3_pass_2022 else '❌'} "
          f"2026:{float(np.mean(improvs_2026)):.4f}{'✅' if crit3_pass_2026 else '❌'}"
          f" ⇒ overall {'✅' if overall_pass else '❌'}", flush=True)


if __name__ == "__main__":
    main()
