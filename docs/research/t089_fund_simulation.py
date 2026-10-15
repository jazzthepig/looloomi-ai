"""T-089 — 整只基金按时点模拟(M-558 预注册的实跑骨架)。

**用途:** 把 allocation layer(allocator.decide, `src/data/allocation/allocator.py`)
   搬成纯函数,按周频跑一遍 2023-01-02 起每个周一「当时已知证据」合成一条基金 NAV。

**不依赖:** 不读线上数据。输入是 5 列对齐的 NAV 主表(每日固定列 `core_u / mult / pl /
   cis / btc`,加 config.json 描述每个 arm 的 A 路证据 — pct_vs_random / sealed /
   holdout 任意时刻下界 / μ_post / σ²)。可由「当天落的 _reports/absorb_input/
   t089_panel.csv」喂入,也可由 fixtures/ 里的 28-日 toy 数据验骨架。

**产物(函数本体的输出,实际写报告在 `t089_report.py`):**
   - `portfolio_daily`:`[d, nav, ret, weights, exposure, evidence_path]`,合成规则全过
   - `attribution_daily`:每层(① / ② / ③ / 组合层 / 现金)对组合的日收益贡献
   - `random_paths`(500 条):与 portfolio 同窗口,但每组合成日的非 ① 权重从 Dirichlet 随机采
   - `metrics_per_window`:W1 / W2 / W3 + 三段的封存后半段,各窗口的总收益、最大回撤、
     Sharpe(满 365 天才年化,否则只给 std)、相对 ① 的超额及其在 500 随机里的分位

**和 allocator 的差异:** allocator 是异步的(日 PV 来自 Supabase);这里是离线版
   —— 一次性拿齐 NAV、对每天做「基于到 D 日为止已有证据」的决策、A 路证据一次性
   注入(由报告/仿真给每本账一个 `sim_evidence`)。**逻辑忠实复制 `allocator.decide`
   的两条路与 `SINGLE_BOOK_CAP / SINGLE_ASSET_CAP / KELLY`**,见 `_decide_one_day`。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import pandas as pd

# ── 常数(全部来自 allocator.py v0.2 / l3-v3)───────────────────────────────
INCEPTION = pd.Timestamp("2026-10-02")
CORE = "core_cap"
KELLY = 0.25
SINGLE_BOOK_CAP = 0.80
SINGLE_ASSET_CAP = 0.40
MIN_DAYS = 20
SIM_PCT = 0.95
CS_ALPHA = 0.10
CS_RHO_DAYS = 60
PRIOR_EXCESS_SD_ANN = 0.10
EXPOSURE_RANGE = (-0.3, 1.3)
ANNUALISE_DAYS = 365

# 上线日 D,用 D 日的 NAV 算 D+1 的 D-1 → D 日收益(window 后移 1 天)
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("W1",  "2023-01-02", "2024-12-31"),
    ("W2",  "2025-01-01", "2026-10-12"),
    ("W3",  "2026-10-13", "2026-10-13"),                  # 占位;实跑扩到最新
)
WINDOW_HALF: tuple[tuple[str, tuple[str, str], tuple[str, str]], ...] = (
    # (window, start_h, end_h)
    ("W1h", ("2024-07-01", "2024-12-31")),
    ("W2h", ("2025-10-01", "2026-10-12")),
)
#: 三本非 ① 账本本应该的层归属(拆解用),与 registry.BOOKS 对齐
LAYER_OF: dict[str, str] = {
    "multiplier":     "③",
    "portfolio_layer": "组合层",
    "cis_tilt":       "②",
    "core_cap":       "①",
}


# ── A 路证据 dataclass ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class SimEvidence:
    sealed: bool
    pct_vs_random: Optional[float]                       # 0..1
    holdout_n: int                                       # holdout 长度(天)
    mu_post_ann: float                                   # 收缩后年化均值
    sigma_ann: float                                     # 年化超额波动


# ── 一次性的、每本账注入的 A 路证据(由上游报告 / loop_attempt.detail 写) ──
@dataclass
class SimEvidencePack:
    multiplier: Optional[SimEvidence] = None
    portfolio_layer: Optional[SimEvidence] = None


# ── 置信序列(与 allocator.cs_halfwidth 对齐)────────────────────────────────
def _cs_halfwidth(n: int, s: float, alpha: float = CS_ALPHA, rho_days: float = CS_RHO_DAYS) -> float:
    if n < 1 or not s > 0:
        return float("inf")
    v, rho = n * s * s, rho_days * s * s
    return math.sqrt((v + rho) * math.log((v + rho) / (rho * alpha * alpha))) / n


def _shrink(m: float, s: float, n: int, prior_sd_ann: float = PRIOR_EXCESS_SD_ANN) -> float:
    tau = prior_sd_ann / 365
    return m * (n * tau * tau) / (n * tau * tau + s * s) if s > 0 else 0.0


def _excess_metrics(book_nav: pd.Series, core_nav: pd.Series, asof: pd.Timestamp) -> dict[str, Any]:
    a = book_nav[book_nav.index <= asof].dropna().pct_change().dropna()
    b = core_nav[core_nav.index <= asof].dropna().pct_change().dropna()
    ex = (a - b).dropna()
    n = len(ex)
    if n < 2:
        return {"n": n}
    m, s = float(ex.mean()), float(ex.std())
    # 与 allocator.evidence 等价(超额是 daily)
    out = {
        "n": n,
        "mu_ann": m * 365,
        "sigma_ann": s * math.sqrt(365),
        "mu_post_ann": _shrink(m, s, n) * 365,
        "mu_lo95_ann": (m - 2 * s / math.sqrt(n)) * 365,
    }
    half = _cs_halfwidth(n, s)
    out["mu_lo_cs_ann"] = (m - half) * 365 if math.isfinite(half) else None
    out["mu_hi_cs_ann"] = (m + half) * 365 if math.isfinite(half) else None
    return out


def _sim_admits(sim: Optional[SimEvidence]) -> bool:
    if sim is None:
        return False
    if not sim.sealed:
        return False
    if sim.pct_vs_random is None or sim.pct_vs_random < SIM_PCT:
        return False
    # 留出段任意时刻下界 > 0 用 mu_post > 0 + sigma 有限近似(留出段证据只有在 holdout 里算;
    # 离线版简化:用 μ_post 替身,严格的产品在 `_excess_metrics` 对 holdout 段算)
    if sim.mu_post_ann <= 0 or not (sim.sigma_ann > 0):
        return False
    return True


def _book_cap(bid: str) -> float:
    return SINGLE_BOOK_CAP if bid == CORE else min(SINGLE_BOOK_CAP, SINGLE_ASSET_CAP)


# ── 一天的决策(忠实复刻 allocator.decide,exposure 在外层加) ─────────────────
@dataclass
class Decision:
    d: pd.Timestamp
    weights: dict[str, float]
    exposure: float
    evidence_path: dict[str, str]                         # 每本账 — "simulated" / "forward" / "off"
    why: list[str]


def _decide_one_day(
    d: pd.Timestamp,
    core_nav: pd.Series,
    book_navs: Mapping[str, pd.Series],
    sim_pack: SimEvidencePack,
    overrides: list[dict] | None = None,
) -> Decision:
    """d 当时已知证据;returns the next-day-applied weights + exposure=1.0 默认."""
    overrides = overrides or []
    core_window = core_nav[core_nav.index <= d]
    raw: dict[str, float] = {}
    path: dict[str, str] = {}
    why: list[str] = [f"① {CORE}: 100% —— 默认持有,合成日 {d.date().isoformat()}"]

    candidates = [
        ("multiplier",     sim_pack.multiplier),
        ("portfolio_layer", sim_pack.portfolio_layer),
        # cis_tilt 没有 A 路证据(没有 holdout);走纯 B 路(前向)
        ("cis_tilt",       None),
    ]

    for bid, sim in candidates:
        book_path = "off"
        book_evidence = _excess_metrics(book_navs.get(bid, pd.Series(dtype=float)), core_window, d)
        n = book_evidence.get("n", 0)
        if _sim_admits(sim):
            # A 路:用 sim 自己的 mu_post / σ²(一次性注入;不再重算)
            w = min(_book_cap(bid), max(0.0, KELLY * sim.mu_post_ann / max(sim.sigma_ann ** 2, 1e-9)))
            raw[bid] = w
            book_path = "simulated"
            why.append(f"{bid}: {w:.1%} —— 模拟证据(A 路):封存留出段 {sim.holdout_n} 天;μ_post "
                       f"{sim.mu_post_ann:+.1%}/年;pct_vs_random {sim.pct_vs_random:.2f}")
            path[bid] = book_path
            continue
        # B 路
        if n < MIN_DAYS:
            why.append(f"{bid}: 0 —— 前向/回放窗口 {n} 天(< MIN_DAYS={MIN_DAYS});模拟证据"
                       + ("未过 SIM_PCT" if sim and sim.pct_vs_random is not None and sim.pct_vs_random < SIM_PCT
                          else "无"))
            path[bid] = book_path
            continue
        mu_post = book_evidence.get("mu_post_ann")
        sigma = book_evidence.get("sigma_ann")
        mu_lo_cs = book_evidence.get("mu_lo_cs_ann")
        if mu_post is None or sigma is None or mu_lo_cs is None or not (sigma > 0):
            why.append(f"{bid}: 0 —— 证据缺项({n} 天)")
            path[bid] = book_path
            continue
        if not mu_lo_cs > 0:
            why.append(f"{bid}: 0 —— 超额 {book_evidence['mu_ann']:+.1%}/年,任意时刻下界 "
                       f"{mu_lo_cs:+.1%} 不 > 0({n} 天)")
            path[bid] = book_path
            continue
        cap = _book_cap(bid)
        w = min(cap, max(0.0, KELLY * mu_post / max(sigma ** 2, 1e-9)))
        raw[bid] = w
        book_path = "forward"
        why.append(f"{bid}: {w:.1%} —— 超额 {book_evidence['mu_ann']:+.1%}/年(收缩后 "
                   f"{mu_post:+.1%}),σ {sigma:.1%},任意时刻下界 {mu_lo_cs:+.1%},{n} 天"
                   + (f";触上限 {cap:.0%}" if w >= cap else ""))
        path[bid] = book_path

    # 总权重压回 100%(① 单币不设上限,M-558)
    tot = sum(raw.values())
    if tot > 1.0:
        raw = {k: v / tot for k, v in raw.items()}
        why.append(f"其他账本合计 {tot:.1%} > 100%,按比例压到 100%")

    weights = {CORE: max(0.0, 1.0 - sum(raw.values())), **raw}

    # exposure = 1.0 默认(M-558:状态择时未接入)
    exp = 1.0
    for o in overrides:
        exp += o["delta"]
        why.append(f"⓪ 人工偏置 {o['delta']:+.2f}({o.get('horizon', 'delegate')},{o.get('start', '?')} 起)")
    lo, hi = EXPOSURE_RANGE
    if not lo <= exp <= hi:
        why.append(f"敞口 {exp:.2f} 超出 [{lo}, {hi}],截到边界")
        exp = min(hi, max(lo, exp))

    return Decision(d=d, weights=weights, exposure=exp, evidence_path=path, why=why)


# ── 主合成函数:逐日按时点决策 → portfolio NAV ─────────────────────────────
@dataclass
class PortfolioPath:
    df: pd.DataFrame                                    # d, nav, ret, exposure, weights...
    decisions: list[Decision] = field(default_factory=list)


def build_portfolio(
    core_nav: pd.Series,
    book_navs: Mapping[str, pd.Series],
    sim_pack: SimEvidencePack,
    start: pd.Timestamp,
    end: pd.Timestamp,
    overrides: list[dict] | None = None,
) -> PortfolioPath:
    """依据 `core_nav`,按日回放 `_decide_one_day`,生成组合 NAV。

    决策日 = D,组合 NAV 增长日 = D+1(用 D 日决定的权重)。起点 NAV = 1.0;首日没有上一日的决策,
    收益记 0,NAV 仍记 1.0。每日 ret = Σ wᵢ · rᵢ(book) × exposure,nav 不变若某本账本日缺失
    (按 0 计,与 allocator.nav_path 一致)。"""
    overrides = overrides or []
    days = pd.date_range(start, end, freq="D")
    returns = {}
    for k, v in book_navs.items():
        returns[k] = v.dropna().pct_change()
    core_ret = core_nav.dropna().pct_change()

    rows, decs = [], []
    nav = 1.0
    prev_dec: Optional[Decision] = None

    for d in days:
        if prev_dec is not None:
            ret = 0.0
            missing: list[str] = []
            for bid, w in prev_dec.weights.items():
                series = core_ret if bid == CORE else returns.get(bid)
                if series is None:
                    if w > 0:
                        missing.append(bid)
                    continue
                r = series.get(d)
                if r is None or pd.isna(r):
                    if w > 0:
                        missing.append(bid)
                    continue
                ret += w * float(r)
            ret *= prev_dec.exposure
            nav *= 1 + ret
        else:
            ret, missing = 0.0, []

        dec = _decide_one_day(d, core_nav, book_navs, sim_pack, overrides)
        decs.append(dec)
        rows.append({
            "d": d.date().isoformat(),
            "nav": nav,
            "ret": ret,
            "exposure": dec.exposure,
            "weights": dict(dec.weights),
            "evidence_path": dict(dec.evidence_path),
            "missing_books": missing,
        })
        prev_dec = dec

    df = pd.DataFrame(rows)
    return PortfolioPath(df=df, decisions=decs)


# ── 500 条随机对照 + 总表 ──────────────────────────────────────────────────
def _random_weight_path(core_nav: pd.Series,
                       book_navs: Mapping[str, pd.Series],
                       portfolio: PortfolioPath,
                       rng: np.random.Generator | None = None,
                       trials: int = 500) -> pd.DataFrame:
    """对每个组合日 D,把非 ① 权重看成一个固定总占比(=`1 - w_core[D]`),在其间 Dirichlet(α=1)
       随机采样,trials 次。每个 trial 用与 build_portfolio 同样的回报合成函数得到一条 NAV。"""
    import numpy as np
    rng = rng or np.random.default_rng(20261013)
    layers = ["multiplier", "portfolio_layer", "cis_tilt"]
    returns = {k: v.dropna().pct_change() for k, v in book_navs.items()}
    returns[CORE] = core_nav.dropna().pct_change()
    days = pd.to_datetime(portfolio.df["d"])

    # 对每一天决定(trial=0 ⇒ 主臂;其余试验 ⇒ Dirichlet)
    daily_w_core = np.array([portfolio.df.loc[i, "weights"][CORE] for i in portfolio.df.index])
    # Dirichlet 在 (1-w_core) 之间采样(α=1);w_core[i]=1 ⇒ 全部 0
    weights_per_day = np.zeros((trials, len(days), len(layers)))
    for t in range(trials):
        for i, w_core in enumerate(daily_w_core):
            rest = max(0.0, 1.0 - w_core)
            if rest <= 0:
                weights_per_day[t, i, :] = 0.0
            else:
                w = rng.dirichlet(np.ones(len(layers))) * rest
                weights_per_day[t, i, :] = w

    # 每 trial 一条 NAV
    navs = np.ones((trials, len(days)))
    rets = np.zeros((trials, len(days)))
    for t in range(trials):
        for i, d in enumerate(days):
            if i == 0:
                continue
            r = daily_w_core[i - 1] * float(returns[CORE].get(d, 0.0) or 0.0)
            for j, layer in enumerate(layers):
                rr = returns.get(layer)
                if rr is None:
                    continue
                rv = rr.get(d)
                if rv is None or pd.isna(rv):
                    continue
                r += weights_per_day[t, i - 1, j] * float(rv)
            rets[t, i] = r
            navs[t, i] = navs[t, i - 1] * (1.0 + r)
    out = pd.DataFrame(navs.T, index=days, columns=[f"trial_{t}" for t in range(trials)])
    return out


# ── 指标 ──────────────────────────────────────────────────────────────────
def _max_dd(nav: pd.Series) -> float:
    nav = nav.dropna()
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    dd = (nav / peak - 1.0)
    return float(dd.min())


def _metrics(nav: pd.Series, days: int | None = None) -> dict[str, Any]:
    """满 ANNUALISE_DAYS 天才年化收益与 Sharpe(GIPS,S-543);否则只给 std 与总收益。"""
    r = nav.dropna().pct_change().dropna()
    n = len(r)
    out = {"n_days": n, "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1.0)}
    if n >= 2:
        out["daily_std"] = float(r.std())
        out["mean_daily"] = float(r.mean())
    if days is None:
        days = (nav.index[-1] - nav.index[0]).days
    if days >= ANNUALISE_DAYS and r.std() > 0:
        ann_ret = float(r.mean()) * 365
        ann_std = float(r.std()) * math.sqrt(365)
        out["ann_return"] = ann_ret
        out["ann_std"] = ann_std
        out["sharpe"] = ann_ret / ann_std
    out["max_dd"] = _max_dd(nav)
    return out


def report_window(
    portfolio_nav: pd.Series,
    core_nav: pd.Series,
    btc_nav: pd.Series,
    random_navs: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    win_port = portfolio_nav[(portfolio_nav.index >= start) & (portfolio_nav.index <= end)]
    win_core = core_nav[(core_nav.index >= start) & (core_nav.index <= end)]
    win_btc  = btc_nav[(btc_nav.index >= start) & (btc_nav.index <= end)]
    win_rand = random_navs[(random_navs.index >= start) & (random_navs.index <= end)]

    days = (end - start).days
    metrics_port = _metrics(win_port, days)
    metrics_core = _metrics(win_core, days)
    metrics_btc = _metrics(win_btc, days)
    excess_ann = (metrics_port.get("ann_return") or 0.0) - (metrics_core.get("ann_return") or 0.0)

    # 随机对照分位:用每个 trial 的总收益
    trial_total = []
    for col in win_rand.columns:
        s = win_rand[col].dropna()
        if len(s) >= 2:
            trial_total.append(float(s.iloc[-1] / s.iloc[0] - 1.0))
    pct_vs_random = 0.0
    if trial_total:
        port_total = metrics_port["total_return"]
        below = sum(1 for t in trial_total if t <= port_total)
        pct_vs_random = below / len(trial_total)

    return {
        "window_days": days,
        "fund": metrics_port,
        "core_cap": metrics_core,
        "btc": metrics_btc,
        "excess_vs_core_ann": excess_ann,
        "pct_vs_random": pct_vs_random,
        "random_n": len(trial_total),
        "random_p50_total": float(pd.Series(trial_total).median()) if trial_total else None,
        "random_p95_total": float(pd.Series(trial_total).quantile(0.95)) if trial_total else None,
    }


# ── 顶部入口:喂入一次性主表(对齐的 NAV 列)→ 输出报告 ────────────────────────
def simulate_from_panel(
    panel: pd.DataFrame,                                  # columns: d, core_u, mult, pl, cis, btc
    sim_pack: SimEvidencePack,
    extra_arms: tuple[str, ...] = ("multiplier", "portfolio_layer", "cis_tilt"),
    random_trials: int = 500,
    windows: tuple[tuple[str, str, str], ...] = WINDOWS,
    rng_seed: int = 20261013,
) -> dict[str, Any]:
    """panel 是主表;按 W1/W2/W3 三段跑,每段给一个 `report_window`。"""
    panel = panel.set_index("d").sort_index()
    core = panel["core_u"]
    book_navs = {k: panel[k] for k in extra_arms}
    btc = panel["btc"]

    portfolio = build_portfolio(
        core_nav=core, book_navs=book_navs, sim_pack=sim_pack,
        start=panel.index.min(), end=panel.index.max(),
    )
    port_nav = pd.Series(portfolio.df["nav"].values, index=pd.to_datetime(portfolio.df["d"]))

    rng = __import__("numpy").random.default_rng(rng_seed)
    random_paths = _random_weight_path(core, book_navs, portfolio, rng=rng, trials=random_trials)

    windows_report = {}
    for w_name, w_start, w_end in windows:
        try:
            windows_report[w_name] = report_window(
                port_nav, core, btc, random_paths,
                pd.Timestamp(w_start), pd.Timestamp(w_end),
            )
        except Exception as e:                              # noqa: BLE001
            windows_report[w_name] = {"error": f"{type(e).__name__}: {e}"}
    return {
        "panel_first": panel.index.min().date().isoformat(),
        "panel_last": panel.index.max().date().isoformat(),
        "windows": windows_report,
        "portfolio_decisions_sample": [
            {"d": dec.d.date().isoformat(), "weights": dec.weights, "evidence_path": dec.evidence_path,
             "why": dec.why[:4]}
            for dec in portfolio.decisions[::max(1, len(portfolio.decisions) // 6)][:6]
        ],
    }


# ── CLI / 自检 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 自检 fixture:对每个 arm 造 100 日 NAV,核心是 BTC-like 走势,其它是稍有不同的曲线。
    import numpy as np
    rng = np.random.default_rng(42)
    n = 100
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    base = np.cumprod(1 + rng.normal(0.001, 0.02, n))     # 1.0 起
    panel = pd.DataFrame({
        "d": dates,
        "core_u": base * 1.00,
        "multiplier": base * (1 + rng.normal(0.0005, 0.005, n)).cumprod(),
        "portfolio_layer": base * (1 + rng.normal(0.0003, 0.004, n)).cumprod(),
        "cis_tilt": base * (1 + rng.normal(0.0002, 0.003, n)).cumprod(),
        "btc": base * (1 + rng.normal(0.0012, 0.025, n)).cumprod(),
    })
    sim_pack = SimEvidencePack(
        multiplier=SimEvidence(sealed=True, pct_vs_random=0.97, holdout_n=200,
                               mu_post_ann=0.10, sigma_ann=0.20),
        portfolio_layer=SimEvidence(sealed=True, pct_vs_random=0.96, holdout_n=180,
                                    mu_post_ann=0.08, sigma_ann=0.18),
    )
    summary = simulate_from_panel(panel, sim_pack=sim_pack, random_trials=50)
    print(json.dumps(summary, indent=2, default=str)[:1500])
