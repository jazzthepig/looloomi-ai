"""v0.2 L3 配置层(纸面)—— 默认持有 ①,其余账本按前向证据连续加权,⓪ 人工通道带期限。

规则来自 `docs/ALLOCATION_ARCHITECTURE_v0.2.md` §3 L3 与 Jazz 09-29 的决定:
1. **① 是默认。** 其他账本的权重从 ① 里拨出;没有证据就是 0,① 就是 100%。
2. **其他账本的权重 = 0.25 × max(0, μ) / σ²**(μ、σ = 相对 ① 的日超额,年化),
   前提是超额的近似 95% 下界 > 0。证据越弱权重越小 —— 连续,不是开关。
3. **上限:** 单个账本 ≤ 80%;单一标的净持仓 ≤ 40%。v0 还没有标的层持仓(L4 未建),
   所以**任何非 ① 账本都按「可能全仓一个币」处理,单本上限取 40%**;① 是 24 名等权,不受此限。
   ④ 与事件类在前向记录不足 60 天时合计 ≤ 10%。
4. **① 是 `core_cap`(市值加权、单币 ≤ 40%,S-473;l3-v0 时是等权的 `beta_core`)。其余账本的证据 = 相对 ① 的超额**
   —— 从 ① 里拨出一份权重给它,挣到的就是它减 ① 的差;不是相对它自己挑的基准。
5. **证据只算前向:** 每本账的证据从 `INCEPTION` 起算。账本表里更早的行有些是历史回放
   (β+ / 代币化倾斜整条重算),回放给先验、前向定结论(v0.2 §5);先验接入等评估层
   (`rr_matrix_daily`)建好再说。所以头几周 ① = 100% 是**预期结果**,不是故障。
6. **总敞口 e ∈ [−0.3, 1.3]**,默认 1.0。v0 里只有人工通道能改它;状态驱动的择时等 L1 有经检验的信号再接
   (M-196 判了 FAIL,解读层权重 0)。
7. **人工通道(⓪):** 每条偏置选期限 —— 7 天 / 14 天 / 1 个月 / 全委托。前三档到期自动失效;
   「全委托」= 不设偏置,敞口交给 L3。
8. **每天一份「为什么」**,写在 ① 那一行。

纸面 NAV:当天收益 = 敞口 × Σ(前一天定的权重 × 账本当天收益)。1 − 敞口 的部分是零收益现金;
敞口为负 = 整本组合反向。各账本自身已扣成本;**配置层再平衡成本 v0 不计**。
账本缺某天的 NAV:当天按 0 计并计数,下一个有数的日子把缺口期间的变动一次补上(收益不丢)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Optional

import pandas as pd

INCEPTION = "2026-10-02"
CORE = "core_cap"
KELLY = 0.25
SINGLE_BOOK_CAP = 0.80
SINGLE_ASSET_CAP = 0.40
ALPHA_LAYERS = ("④", "事件")
ALPHA_CAP_BEFORE_60D = 0.10
FORWARD_DAYS_FOR_ALPHA = 60
MIN_DAYS = 20
EXPOSURE_RANGE = (-0.3, 1.3)
HORIZONS = {"7d": 7, "14d": 14, "1m": 30, "delegate": 0}
CODE_REF = "l3-v1"


@dataclass(frozen=True)
class Override:
    start: date
    delta: float
    horizon: str
    reason: str

    def active_on(self, d: date) -> bool:
        days = HORIZONS[self.horizon]
        return days > 0 and self.start <= d < self.start + timedelta(days=days)


def evidence(nav: Optional[pd.Series], bench: Optional[pd.Series]) -> dict[str, Any]:
    """相对基准的日超额:天数、年化均值与波动、近似 95% 下界(均值 − 2 标准误)。基准缺失 ⇒ 无证据。"""
    if nav is None or bench is None:
        return {"n_days": 0}
    a = nav.dropna().sort_index().pct_change()
    b = bench.dropna().sort_index().pct_change()
    ex = (a - b).dropna()
    n = len(ex)
    if n < 2:
        return {"n_days": n}
    m, s = float(ex.mean()), float(ex.std())
    return {"n_days": n, "mu": m * 365, "sigma": s * math.sqrt(365),
            "mu_lo95": (m - 2 * s / math.sqrt(n)) * 365}


def book_cap(bid: str) -> float:
    return SINGLE_BOOK_CAP if bid == CORE else min(SINGLE_BOOK_CAP, SINGLE_ASSET_CAP)


def decide(d: date, books: Mapping[str, Mapping[str, Any]], overrides: list[Override]) -> dict[str, Any]:
    """一天的配置。`books`:{id: {layer, status, caveat, evidence}}。纯函数。"""
    why: list[str] = []
    raw: dict[str, float] = {}
    for bid, b in books.items():
        if bid == CORE:
            continue
        ev = b.get("evidence") or {}
        n = ev.get("n_days", 0)
        if b.get("status") != "paper" or b.get("caveat"):
            why.append(f"{bid}: 0 —— 状态 {b.get('status')}" + (f";{b['caveat']}" if b.get("caveat") else ""))
        elif n < MIN_DAYS:
            why.append(f"{bid}: 0 —— 前向 {n} 天,不到 {MIN_DAYS} 天估不了")
        elif not ev.get("mu_lo95", -1.0) > 0:
            why.append(f"{bid}: 0 —— 超额 {ev['mu']:+.1%}/年,95% 下界 {ev['mu_lo95']:+.1%} 不 > 0({n} 天)")
        else:
            cap = book_cap(bid)
            w = min(cap, KELLY * ev["mu"] / max(ev["sigma"] ** 2, 1e-9))
            raw[bid] = w
            why.append(f"{bid}: {w:.1%} —— 超额 {ev['mu']:+.1%}/年,σ {ev['sigma']:.1%},下界 {ev['mu_lo95']:+.1%},"
                       f"{n} 天" + (f";触上限 {cap:.0%}" if w >= cap else ""))
    young = [k for k in raw if books[k].get("layer") in ALPHA_LAYERS
             and (books[k].get("evidence") or {}).get("n_days", 0) < FORWARD_DAYS_FOR_ALPHA]
    a_tot = sum(raw[k] for k in young)
    if a_tot > ALPHA_CAP_BEFORE_60D:
        for k in young:
            raw[k] *= ALPHA_CAP_BEFORE_60D / a_tot
        why.append(f"④/事件 前向不足 {FORWARD_DAYS_FOR_ALPHA} 天,合计从 {a_tot:.1%} 压到 {ALPHA_CAP_BEFORE_60D:.0%}")
    tot = sum(raw.values())
    if tot > 1.0:
        raw = {k: v / tot for k, v in raw.items()}
        why.append(f"其他账本合计 {tot:.1%} > 100%,按比例压到 100%")
    weights = {CORE: max(0.0, 1.0 - sum(raw.values())), **raw}
    why.insert(0, f"① {CORE}: {weights[CORE]:.1%} —— 默认持有,其余权重从这里拨出")

    exp = 1.0
    act = [o for o in overrides if o.active_on(d)]
    for o in act:
        exp += o.delta
        why.append(f"⓪ 人工偏置 {o.delta:+.2f}({o.horizon},{o.start} 起):{o.reason}")
    lo, hi = EXPOSURE_RANGE
    if not lo <= exp <= hi:
        why.append(f"敞口 {exp:.2f} 超出 [{lo}, {hi}],截到边界")
        exp = min(hi, max(lo, exp))
    if not act:
        why.append("敞口 1.00 —— 默认;无人工偏置;状态驱动的择时未接入(M-196 FAIL)")
    return {"d": d.isoformat(), "weights": weights, "exposure": exp, "why": why}


def nav_path(days: list[date], decisions: Mapping[date, dict],
             book_returns: Mapping[str, pd.Series]) -> list[dict]:
    nav, rows, prev = 1.0, [], None
    for d in days:
        ret, missing = 0.0, []
        if prev is not None:
            dec = decisions[prev]
            for bid, w in dec["weights"].items():
                r = book_returns.get(bid)
                v = r.get(pd.Timestamp(d)) if r is not None else None
                if v is None or pd.isna(v):
                    if w > 0:
                        missing.append(bid)
                    continue
                ret += w * float(v)
            ret *= dec["exposure"]
            nav *= 1 + ret
        rows.append({"d": d.isoformat(), "nav": nav, "ret": ret, "exposure": decisions[d]["exposure"],
                     "core_weight": decisions[d]["weights"].get(CORE, 0.0),
                     "n_books": sum(1 for w in decisions[d]["weights"].values() if w > 0),
                     "missing_returns": missing, "code_ref": CODE_REF})
        prev = d
    return rows


def forward_window(s: Optional[pd.Series], d: pd.Timestamp) -> Optional[pd.Series]:
    """证据窗口:INCEPTION 前一天(作为第一天收益的起点)到 d,含两端。"""
    if s is None:
        return None
    a = pd.Timestamp(INCEPTION) - pd.Timedelta(days=1)
    return s[(s.index >= a) & (s.index <= d)]


# ── I/O ─────────────────────────────────────────────────────────────────────

async def load_overrides() -> list[Override]:
    from src.data.style.header import _read_all
    rows = await _read_all("allocation_override", {"select": "start_d,delta,horizon,reason",
                                                   "order": "start_d.asc"})
    return [Override(date.fromisoformat(r["start_d"]), float(r["delta"]), r["horizon"], r.get("reason") or "")
            for r in rows]


async def run_once() -> dict[str, Any]:
    """从 INCEPTION 起逐日整条重算(无状态、幂等),写 allocation_daily 与 allocation_nav_daily。"""
    from datetime import datetime, timezone
    from src.api.store import supabase_upsert_table
    from src.data.accounting.registry import BOOKS, load_navs

    navs, _bench = await load_navs()
    core = navs.get(CORE)
    if core is None or core.dropna().empty:
        return {"ok": False, "reason": "① beta_core 读不到 NAV —— 不出配置"}
    today = datetime.now(timezone.utc).date()
    last = min(today - timedelta(days=1), core.dropna().index.max().date())
    days = [x.date() for x in pd.date_range(INCEPTION, last, freq="D")]
    if not days:
        return {"ok": True, "refused": True, "reason": f"① 最新 {last},起点 {INCEPTION} 还没到"}
    ovs = await load_overrides()
    returns = {k: v.dropna().sort_index().pct_change() for k, v in navs.items() if v is not None}
    decisions, alloc_rows = {}, []
    for d in days:
        ts = pd.Timestamp(d)
        core_w = forward_window(core, ts)
        books = {b.id: {"layer": b.layer, "status": b.status, "caveat": b.caveat,
                        "evidence": evidence(forward_window(navs.get(b.id), ts), core_w)}
                 for b in BOOKS}
        dec = decide(d, books, ovs)
        decisions[d] = dec
        for bid, w in dec["weights"].items():
            alloc_rows.append({"d": d.isoformat(), "book": bid, "weight": w, "exposure": dec["exposure"],
                               "evidence": books.get(bid, {}).get("evidence"),
                               "why": dec["why"] if bid == CORE else None, "code_ref": CODE_REF})
    nav_rows = nav_path(days, decisions, returns)
    # 表名写成字面量:schema_manifest 的 AST 扫描只认得字面量,循环变量里的表名它看不见(S-166)。
    for i in range(0, len(alloc_rows), 1000):
        w = await supabase_upsert_table("allocation_daily", alloc_rows[i:i + 1000], on_conflict="d,book")
        if not w.ok:
            return {"ok": False, "reason": f"allocation_daily 写入失败:{w.why}"}
    w = await supabase_upsert_table("allocation_nav_daily", nav_rows, on_conflict="d")
    if not w.ok:
        return {"ok": False, "reason": f"allocation_nav_daily 写入失败:{w.why}"}
    ld = decisions[days[-1]]
    return {"ok": True, "days": len(days), "last": days[-1].isoformat(), "nav": nav_rows[-1]["nav"],
            "weights": ld["weights"], "exposure": ld["exposure"], "why": ld["why"],
            "reason": (f"配置 {len(days)} 天至 {days[-1]};① {ld['weights'][CORE]:.0%};"
                       f"敞口 {ld['exposure']:.2f};NAV {nav_rows[-1]['nav']:.4f}")}
