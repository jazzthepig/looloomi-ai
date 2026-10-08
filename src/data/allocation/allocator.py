"""v0.2 L3 配置层(纸面)—— 默认持有 ①,其余账本按前向证据连续加权,⓪ 人工通道带期限。

规则来自 `docs/ALLOCATION_ARCHITECTURE_v0.2.md` §3 L3 与 Jazz 09-29 的决定:
1. **① 是默认。** 其他账本的权重从 ① 里拨出;没有证据就是 0,① 就是 100%。
2. **其他账本的权重 = 0.25 × μ_post / σ²**(σ = 相对 ① 的日超额波动,年化;μ_post = 超额均值向 0 收缩后的值)。
   **l3-v2(S-485 / T-050)** 改了三处,因为 l3-v1 每天重算「均值 − 2 标准误 > 0」是反复看的 p 值:
   零超额账本一年内 17% 会在某个运气好的日子被放进去,而越过门槛那一刻 Kelly 就顶到上限。
   - **门槛 = 任意时刻有效的置信序列**(正态混合边界,`CS_ALPHA`、`CS_RHO_DAYS`):天天看也不膨胀;
   - **Kelly 之前先收缩:** 先验 超额 ~ N(0, `PRIOR_EXCESS_SD_ANN`²),权重随证据平滑爬升,不再一步顶格;
   - ~~任何非 ① 账本前向不足 60 天一律 0~~ **l3-v3(T-064 / S-514,Jazz 10-07「不等 30/60/90 天」、10-08「不按日期计划走」):**
     60 天是日期门,不是证据门 —— 同一个零超额、天天重看的模拟里,60 天地板把一年内误放率从 1.2% 压到 1.07%,
     几乎全部的保护来自任意时刻有效的置信序列。现在只留 `MIN_DAYS = 20`:插入式方差估计需要的最少点数。
   - **两条准入路(T-064):** B 路 = 前向置信序列(上面这套);A 路 = **模拟证据** —— 按时点回放的封存留出段
     (规则从没在这段上调过)里,择时 / 倾斜的超额高于随机对照 p95,且留出段超额的任意时刻下界 > 0。
     A 路进来的账本权重按留出段证据算(同样先收缩再 ¼ Kelly),标 `evidence_path = simulated`;
     前向攒够 `MIN_DAYS` 天、且前向超额的任意时刻**上界** < 0 ⇒ 降回 0(前向证据转负可以否决模拟)。
     留出段看过数据才定规则的账本(如组合层 v2,S-511)不走 A 路。
   代价写在台账 S-488:超额夏普 1 的账本一年内被放进去的概率约 12%。证据越弱权重越小 —— 连续,不是开关。
3. **上限:** 单个账本 ≤ 80%;单一标的净持仓 ≤ 40%。v0 还没有标的层持仓(L4 未建),
   所以**任何非 ① 账本都按「可能全仓一个币」处理,单本上限取 40%**;① 是 24 名等权,不受此限。
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
MIN_DAYS = 20
#: A 路:模拟证据的随机对照分位门槛
SIM_PCT = 0.95
#: 置信序列:双侧水平(单侧越界概率约一半)与边界最紧的时点(天)。S-488 的模拟:零超额账本一年内被放进去约 1%。
CS_ALPHA = 0.10
CS_RHO_DAYS = 60
#: 超额(相对 ①)的先验标准差,年化。真实账本的长期超额很少超过这个量级。
PRIOR_EXCESS_SD_ANN = 0.10
EXPOSURE_RANGE = (-0.3, 1.3)
HORIZONS = {"7d": 7, "14d": 14, "1m": 30, "delegate": 0}
CODE_REF = "l3-v3"


@dataclass(frozen=True)
class Override:
    start: date
    delta: float
    horizon: str
    reason: str

    def active_on(self, d: date) -> bool:
        days = HORIZONS[self.horizon]
        return days > 0 and self.start <= d < self.start + timedelta(days=days)


def cs_halfwidth(n: int, s: float, alpha: float = CS_ALPHA, rho_days: float = CS_RHO_DAYS) -> float:
    """日均值的任意时刻有效半宽(正态混合边界,Robbins 1970 / Howard et al. 2021):
    以内禀时间 V = n·s²、ρ = rho_days·s²,对所有 n 同时有 |Σx − nμ| ≤ √((V+ρ)·ln((V+ρ)/(ρ·α²)))(概率 ≥ 1−α)。
    s 用样本估计(插入式);厚尾下由 S-488 的 t3 模拟兜底。"""
    if n < 1 or not s > 0:
        return float("inf")
    v, rho = n * s * s, rho_days * s * s
    return math.sqrt((v + rho) * math.log((v + rho) / (rho * alpha * alpha))) / n


def shrink(m: float, s: float, n: int, prior_sd_ann: float = PRIOR_EXCESS_SD_ANN) -> float:
    """日均值向 0 收缩(正态先验 N(0, τ²),τ 为日化先验标准差):后验均值 = m · nτ² / (nτ² + s²)。"""
    tau = prior_sd_ann / 365
    return m * (n * tau * tau) / (n * tau * tau + s * s) if s > 0 else 0.0


def evidence(nav: Optional[pd.Series], bench: Optional[pd.Series]) -> dict[str, Any]:
    """相对基准的日超额:天数、年化均值与波动、固定 2 标准误下界(只作显示)、
    任意时刻有效下界 `mu_lo_cs`(门槛用)、收缩后的均值 `mu_post`(权重用)。基准缺失 ⇒ 无证据。"""
    if nav is None or bench is None:
        return {"n_days": 0}
    a = nav.dropna().sort_index().pct_change()
    b = bench.dropna().sort_index().pct_change()
    ex = (a - b).dropna()
    n = len(ex)
    if n < 2:
        return {"n_days": n}
    m, s = float(ex.mean()), float(ex.std())
    # S-489:超额波动为 0(① 对它自己)时半宽是 inf ⇒ 下界 −inf;json 写成 -Infinity,PostgREST 整批拒收。
    # 不可估的量写 None(「没有」),不写无穷。
    return {k: (v if not isinstance(v, float) or math.isfinite(v) else None) for k, v in {
        "n_days": n, "mu": m * 365, "sigma": s * math.sqrt(365),
        "mu_lo95": (m - 2 * s / math.sqrt(n)) * 365,
        "mu_lo_cs": (m - cs_halfwidth(n, s)) * 365,
        "mu_hi_cs": (m + cs_halfwidth(n, s)) * 365,
        "mu_post": shrink(m, s, n) * 365}.items()}


#: A 路的模拟证据来源:账本 → 回放臂、① 回放臂、留出段起点、评估所在的循环与键、留出段是否封存(规则没在它上面调过)。
SIM_SOURCES: dict[str, dict[str, Any]] = {
    "multiplier": {"table": "multiplier_daily", "arm": "mult_v1_replay", "core_arm": "core_replay",
                   "holdout": ("2025-01-01", "2026-10-07"), "loop": "_multiplier_loop",
                   "eval_key": "holdout_2025_to_inception", "sealed": True},
    "portfolio_layer": {"table": "portfolio_layer_daily", "arm": "pl_v2_replay", "core_arm": None,
                        "holdout": ("2025-01-01", "2026-10-08"), "loop": "_portfolio_layer_loop",
                        "eval_key": "holdout_2025_to_inception", "sealed": False},   # S-511:变量看过留出段
}


def sim_admits(sim: Mapping[str, Any]) -> bool:
    """纯函数。A 路:留出段封存、随机分位 ≥ SIM_PCT、留出段超额任意时刻下界 > 0、证据齐。"""
    ev = sim.get("replay_evidence") or {}
    return bool(sim.get("sealed")) and (sim.get("pct_vs_random") or 0) >= SIM_PCT and \
        ev.get("mu_lo_cs") is not None and ev["mu_lo_cs"] > 0 and ev.get("mu_post") is not None and bool(ev.get("sigma"))


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
        sim = b.get("sim") or {}
        if b.get("status") == "paper" and not b.get("caveat") and sim_admits(sim):
            if n >= MIN_DAYS and ev.get("mu_hi_cs") is not None and ev["mu_hi_cs"] < 0:
                why.append(f"{bid}: 0 —— 模拟证据过了,但前向 {n} 天超额任意时刻上界 {ev['mu_hi_cs']:+.1%} < 0,前向否决")
                continue
            sev = sim["replay_evidence"]
            cap = book_cap(bid)
            w = min(cap, max(0.0, KELLY * sev["mu_post"] / max(sev["sigma"] ** 2, 1e-9)))
            raw[bid] = w
            why.append(f"{bid}: {w:.1%} —— 模拟证据(A 路):封存留出段超额 {sev['mu']:+.1%}/年,随机分位 "
                       f"{sim['pct_vs_random']:.2f},下界 {sev['mu_lo_cs']:+.1%};前向 {n} 天")
            continue
        if b.get("status") != "paper" or b.get("caveat"):
            why.append(f"{bid}: 0 —— 状态 {b.get('status')}" + (f";{b['caveat']}" if b.get("caveat") else ""))
        elif n < MIN_DAYS:
            why.append(f"{bid}: 0 —— 前向 {n} 天,方差还估不出来(< {MIN_DAYS});模拟证据" +
                       (f"随机分位 {sim['pct_vs_random']:.2f} 未过 {SIM_PCT}" if sim.get("pct_vs_random") is not None
                        else "没有") + ("" if sim.get("sealed", True) else "(留出段看过数据,不算)"))
        elif ev.get("mu_lo_cs") is None or ev.get("mu_post") is None or not ev.get("sigma"):
            why.append(f"{bid}: 0 —— 证据缺任意时刻下界或收缩均值、或超额波动为 0,不可估({n} 天)")
        elif not ev["mu_lo_cs"] > 0:
            why.append(f"{bid}: 0 —— 超额 {ev['mu']:+.1%}/年,任意时刻下界 {ev['mu_lo_cs']:+.1%} 不 > 0({n} 天)")
        else:
            cap = book_cap(bid)
            w = min(cap, max(0.0, KELLY * ev["mu_post"] / max(ev["sigma"] ** 2, 1e-9)))
            raw[bid] = w
            why.append(f"{bid}: {w:.1%} —— 超额 {ev['mu']:+.1%}/年(收缩后 {ev['mu_post']:+.1%}),σ {ev['sigma']:.1%},"
                       f"任意时刻下界 {ev['mu_lo_cs']:+.1%},{n} 天" + (f";触上限 {cap:.0%}" if w >= cap else ""))
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


async def load_sim_evidence(core_nav: pd.Series) -> dict[str, dict[str, Any]]:
    """A 路的输入:每个 SIM_SOURCES 账本的留出段回放证据 + 最近一轮评估的随机分位。读不到 ⇒ 不给(不当成过)。"""
    from src.data.style.header import _read_all
    out: dict[str, dict[str, Any]] = {}
    for bid, src in SIM_SOURCES.items():
        try:
            lo, hi = src["holdout"]
            rows = await _read_all(src["table"], {"select": "d,nav", "arm": f"eq.{src['arm']}",
                                                  "d": f"gte.{(pd.Timestamp(lo) - pd.Timedelta(days=1)).date()}",
                                                  "order": "d.asc"})
            nav = pd.Series({pd.Timestamp(r["d"]): float(r["nav"]) for r in rows}).sort_index()
            nav = nav[nav.index <= pd.Timestamp(hi)]
            if src["core_arm"]:
                crow = await _read_all(src["table"], {"select": "d,nav", "arm": f"eq.{src['core_arm']}",
                                                      "d": f"gte.{(pd.Timestamp(lo) - pd.Timedelta(days=1)).date()}",
                                                      "order": "d.asc"})
                bench = pd.Series({pd.Timestamp(r["d"]): float(r["nav"]) for r in crow}).sort_index()
            else:
                bench = await _core_replay_nav(lo)
            bench = bench[bench.index <= pd.Timestamp(hi)]
            la = await _read_all("loop_attempt", {"select": "detail", "loop_name": f"eq.{src['loop']}",
                                                  "outcome": "eq.ok", "order": "at.desc", "limit": "1"})
            ev_detail = ((la[0].get("detail") or {}).get("eval") or {}).get(src["eval_key"]) or {} if la else {}
            out[bid] = {"sealed": src["sealed"], "pct_vs_random": ev_detail.get("pct_vs_random"),
                        "replay_evidence": evidence(nav, bench)}
        except Exception as e:                              # noqa: BLE001 — 读不到 ⇒ 不走 A 路,不是过了
            out[bid] = {"sealed": src["sealed"], "pct_vs_random": None, "error": f"{type(e).__name__}: {str(e)[:80]}"}
    return out


async def _core_replay_nav(lo: str) -> pd.Series:
    from src.data.style.header import _read_all
    rows = await _read_all("multiplier_daily", {"select": "d,nav", "arm": "eq.core_replay",
                                                "d": f"gte.{(pd.Timestamp(lo) - pd.Timedelta(days=1)).date()}",
                                                "order": "d.asc"})
    return pd.Series({pd.Timestamp(r["d"]): float(r["nav"]) for r in rows}).sort_index()


async def run_once() -> dict[str, Any]:
    """从 INCEPTION 起逐日整条重算(无状态、幂等),写 allocation_daily 与 allocation_nav_daily。"""
    from datetime import datetime, timezone
    from src.api.store import supabase_upsert_table
    from src.data.accounting.registry import BOOKS, load_navs

    navs, _bench = await load_navs()
    core = navs.get(CORE)
    if core is None or core.dropna().empty:
        return {"ok": False, "reason": f"① {CORE} 读不到 NAV —— 不出配置(读不到 ≠ ① 为 0)"}
    today = datetime.now(timezone.utc).date()
    last = min(today - timedelta(days=1), core.dropna().index.max().date())
    days = [x.date() for x in pd.date_range(INCEPTION, last, freq="D")]
    if not days:
        return {"ok": True, "refused": True, "reason": f"① 最新 {last},起点 {INCEPTION} 还没到"}
    ovs = await load_overrides()
    sims = await load_sim_evidence(core)
    returns = {k: v.dropna().sort_index().pct_change() for k, v in navs.items() if v is not None}
    decisions, alloc_rows = {}, []
    for d in days:
        ts = pd.Timestamp(d)
        core_w = forward_window(core, ts)
        books = {b.id: {"layer": b.layer, "status": b.status, "caveat": b.caveat,
                        "evidence": evidence(forward_window(navs.get(b.id), ts), core_w),
                        "sim": sims.get(b.id)}
                 for b in BOOKS}
        dec = decide(d, books, ovs)
        decisions[d] = dec
        for bid, w in dec["weights"].items():
            _sim = books.get(bid, {}).get("sim") or {}
            _ev = dict(books.get(bid, {}).get("evidence") or {})
            if _sim:
                _ev["sim"] = {k: _sim.get(k) for k in ("sealed", "pct_vs_random")}
                _ev["evidence_path"] = "simulated" if (w > 0 and sim_admits(_sim)) else "forward"
            alloc_rows.append({"d": d.isoformat(), "book": bid, "weight": w, "exposure": dec["exposure"],
                               "evidence": _ev,
                               "why": dec["why"] if bid == CORE else None, "code_ref": CODE_REF})
    nav_rows = nav_path(days, decisions, returns)
    # S-489:写之前按严格 JSON 检查一遍 —— 无穷 / NaN 会让 PostgREST 以「Empty or invalid json」拒收整批,
    # 原因被埋在 400 里;在这里拦下来,报出是哪一种。
    import json
    try:
        json.dumps(alloc_rows, allow_nan=False)
        json.dumps(nav_rows, allow_nan=False)
    except ValueError as e:
        return {"ok": False, "reason": f"写入前检查:行里有非有限数({e})—— 不写"}
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
