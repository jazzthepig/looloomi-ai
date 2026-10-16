"""策略自选拼组合(Jazz 10-12):选几本账、给权重 → 组合的风险与收益来源(S-543)。

「我们很多策略,应该可以让人选择拼组合,来计算组合的风险和收益来源。」Long/Short 与只做多并存,不冲突 ——
组合层面把它们放在一起看:每一份收益来自哪一层(① β / ② β+ / ③ 推力 / ④ 纯 α / 事件 / 组合层),风险由谁贡献。

## 两种口径(都标明,不混)

- `forward`:各账本自己的纸面记录(登记表 `load_navs`,估值点已对齐到市场日)。窗口 = 所选账本共同有记录的日子 ——
  大多数账本刚起步,窗口短;不足 20 天只描述、不估计(与配置层 MIN_DAYS 同一条线);不满一年不年化(GIPS)。
- `replay`:按时点回放(事后算的,不是当时的记录):① = `core_replay`,③ = `mult_v1_replay`,组合层 = `pl_v2_replay`,
  2023 起。没有回放的账本在这个口径下不可选,如实说。

## 算法

组合日收益 = Σ wᵢ·rᵢ(每天按目标权重再平衡;权重和 < 1 的部分是现金,收益 0;允许 ④ 的多空账本出现在组合里)。
收益来源两种拆法:按层(Σ 每本账 wᵢ·rᵢ 的累计,按层加总)与相对 ①(组合日收益对 ① 回归:β × ① 的收益 + 截距 α)。
风险贡献 = wᵢ·cov(rᵢ, r_组合) / var(r_组合)(加总 = 1)。
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365
MIN_DAYS = 20
#: 年化只在共同记录满一年时做(GIPS:不足一年的收益不年化)。31 天 +12% 年化成 +292%、Sharpe 8.5 —— 上线当天实测,
#: 这种数字摆在页面上就是误导。波动率可以年化(按实际观测频率),收益 / Sharpe / 年化 α 不行。
ANNUALISE_DAYS = 365
LAYER_SOURCE = {"①": "beta", "②": "beta_plus", "③": "multiplier", "④": "alpha", "①+③": "beta_and_multiplier",
                "组合层": "portfolio_layer", "事件": "event", "—": "other"}
#: 对外的名字与一句话说明(页面是英文的;登记表里的中文名与内部编号不出站)
PUBLIC = {
    "core_cap": ("Core holding", "24 names, market-cap weighted, no single-name cap (until 2026-10-12: no name above 40%) — holding the market."),
    "core_cap_c40": ("Core holding, 40% cap (control)", "The previous core rule, kept running as the control for removing the cap."),
    "beta_core": ("Equal weight + volatility target", "The same panel equal-weighted, with exposure scaled to a volatility target."),
    "beta_plus_w": ("Momentum tilt (weekly)", "Overweights names with strong trends near their 52-week highs, inside the panel."),
    "beta_plus_m": ("Momentum tilt (monthly)", "The momentum tilt, rebalanced monthly."),
    "cis_tilt": ("CIS tilt", "Overweights higher-CIS names inside the core holding."),
    "multiplier": ("Exposure timing (0.7–1.3x)", "The core holding scaled between 0.7x and 1.3x by market state; never short."),
    "tom_overlay": ("Add-to-winners overlay (0.7–1.3x)", "The core scaled up only while it is already making money - one step per new high, steps removed on a 20-day low - and cut to 0.7x below its long-term trend; never short."),
    "multiplier_v1": ("Exposure timing v1 (control)", "The same timing rule on the previous 40%-capped core, kept as the control."),
    "portfolio_layer": ("Portfolio layer (0–1x)", "Exposure between 0 and 1 by market-state flags; can sit in cash."),
    "portfolio_layer_v2": ("Portfolio layer v2 (control)", "The same exposure rule on the previous 40%-capped core, kept as the control."),
    "tokenization_tilt": ("Tokenization infrastructure tilt", "A 25% tilt toward names carrying traditional assets on-chain."),
    "hl_mech": ("Four-coin rule-based sizing", "Four liquid coins held spot, position size set by rule."),
    "hl_jev": ("Four-coin discretionary sizing", "The same four coins, with discretionary size adjustments."),
    "causal_paper": ("Funding-rate long/short", "Long/short on funding-rate and positioning structure."),
    "scalable_book": ("Multi-strategy long/short", "A long/short book built to scale."),
    "combined_book": ("Combined long/short", "Several long/short sleeves combined."),
    "dingge_paper": ("Event-driven", "Positions taken around identified events."),
    "fusion_paper": ("Fusion long/short", "Several sleeves fused into one long/short book."),
    "two_layer_paper": ("Two-layer book", "A core-plus-overlay book; inactive while its core is replaced."),
}

#: 回放口径:账本 → (表, 臂)
#: S-556:① 的回放 = 不设单币上限的市值加权(core_variants 的 cap_uncapped,同面板、同周一再平衡、同 10 bps);
#: ③ / 组合层的回放自 T-087 起也建在新 ① 上(mult_v2_replay / pl_v3_replay)。
REPLAY = {"core_cap": ("core_variants_daily", "cap_uncapped"),
          "multiplier": ("multiplier_daily", "mult_v2_replay"),
          "tom_overlay": ("multiplier_daily", "tom_pd13_replay"),
          "portfolio_layer": ("portfolio_layer_daily", "pl_v3_replay")}


def parse_weights(spec: str) -> dict[str, float]:
    """`core_cap:0.6,causal_paper:0.2` → {book: weight}。权重可以是百分数(60)或比例(0.6);负数不收(做空在账本内部)。"""
    out: dict[str, float] = {}
    for part in (spec or "").split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        try:
            w = float(v)
        except ValueError:
            continue
        if w > 1.0:
            w = w / 100.0
        if w > 0 and k.strip():
            out[k.strip()] = out.get(k.strip(), 0.0) + w
    return out


def combine(navs: Mapping[str, pd.Series], weights: Mapping[str, float], layers: Mapping[str, str],
            core: Optional[pd.Series] = None) -> dict[str, Any]:
    """纯函数。navs:{book: 日 NAV};weights:{book: 权重}(和 ≤ 1,其余为现金);layers:{book: 层}。"""
    total_w = sum(weights.values())
    if not weights:
        return {"ok": False, "reason": "no books selected"}
    if total_w > 1.0 + 1e-9:
        weights = {k: v / total_w for k, v in weights.items()}
        total_w = 1.0
    levels = {}
    for b in weights:
        s = navs.get(b)
        if s is None or len(s.dropna()) < 2:
            return {"ok": False, "reason": f"{b}: no record in this basis"}
        s = s.dropna().sort_index()
        levels[b] = s[~s.index.duplicated(keep="last")]
    # 先对齐 NAV 再算收益:每本账的收益都覆盖同一段时间(先各自 pct_change 再对齐,缺口两侧的收益区间会对不上)
    lv = pd.DataFrame(levels).dropna()
    df = lv.pct_change().dropna()
    if len(df) < 2:
        return {"ok": False, "reason": "the selected books share fewer than 2 days of record"}
    w = pd.Series(weights)
    contrib = df.mul(w, axis=1)
    port = contrib.sum(axis=1)
    nav = (1 + port).cumprod()
    n = len(port)
    span = max(1, (lv.index[-1] - lv.index[0]).days)
    per_year = n * DAYS_PER_YEAR / span                  # 实际观测频率(有缺口时少于 365)
    annualised = span >= ANNUALISE_DAYS
    total = float(nav.iloc[-1] - 1)
    ann_ret = float(nav.iloc[-1] ** (DAYS_PER_YEAR / span) - 1) if annualised else None
    vol = float(port.std(ddof=1) * math.sqrt(per_year)) if n >= 3 else None
    dd = float((nav / nav.cummax() - 1).min())
    var_p = float(port.var(ddof=1)) if n >= 3 else 0.0
    books = []
    for b in weights:
        rb = df[b]
        nb = (1 + rb).cumprod()
        cov = float(np.cov(rb, port, ddof=1)[0, 1]) if n >= 3 else 0.0
        books.append({
            "book": b, "layer": layers.get(b), "source": LAYER_SOURCE.get(layers.get(b) or "—", "other"),
            "weight": round(float(weights[b]), 4),
            "book_return": float(nb.iloc[-1] - 1),
            "return_contribution": float(contrib[b].sum()),
            "risk_contribution": (float(weights[b]) * cov / var_p) if var_p > 0 else None,
        })
    by_source: dict[str, float] = {}
    for x in books:
        by_source[x["source"]] = by_source.get(x["source"], 0.0) + x["return_contribution"]
    corr = df.corr().round(3) if n >= 3 else None
    out: dict[str, Any] = {
        "ok": True, "window": [lv.index[0].date().isoformat(), lv.index[-1].date().isoformat()], "days": n,
        "calendar_days": span, "estimable": n >= MIN_DAYS, "annualised": annualised,
        "cash_weight": round(max(0.0, 1.0 - total_w), 4),
        "portfolio": {"total_return": total, "ann_return": ann_ret, "ann_vol": vol,
                      "sharpe": (ann_ret / vol) if ann_ret is not None and vol else None,
                      "max_drawdown": dd, "worst_day": float(port.min()), "best_day": float(port.max())},
        "books": books,
        "return_sources_by_layer": by_source,
        "correlation": {k: {kk: (None if pd.isna(vv) else float(vv)) for kk, vv in row.items()}
                        for k, row in corr.to_dict(orient="index").items()} if corr is not None else None,
        "nav": [{"d": d.date().isoformat(), "nav": round(float(v), 6)} for d, v in nav.items()],
    }
    if core is not None and n >= 3:
        cl = core.dropna().sort_index()
        c = cl[~cl.index.duplicated(keep="last")].reindex(lv.index).pct_change().reindex(df.index)
        ok = c.notna()
        if ok.sum() >= 3 and float(c[ok].var(ddof=1)) > 0:
            beta = float(np.cov(port[ok], c[ok], ddof=1)[0, 1] / c[ok].var(ddof=1))
            alpha_d = float(port[ok].mean() - beta * c[ok].mean())
            core_total = float((1 + c[ok]).prod() - 1)
            resid = port[ok] - beta * c[ok]
            out["vs_core"] = {"beta": beta, "core_return": core_total,
                              "beta_part": beta * core_total, "residual_part": float(resid.sum()),
                              "alpha_ann": alpha_d * per_year if annualised else None,
                              "r2": float(np.corrcoef(port[ok], c[ok])[0, 1] ** 2)}
    return out


async def load_basis(mode: str) -> tuple[dict[str, pd.Series], dict[str, str], dict[str, Any]]:
    """读一种口径的 NAV。返回 (navs, layers, 每本账的说明)。"""
    from src.data.accounting.registry import BOOKS, load_navs
    from src.data.style.header import _read_all
    layers = {b.id: b.layer for b in BOOKS}
    info = {b.id: {"id": b.id, "name": PUBLIC.get(b.id, (b.id, ""))[0], "layer": b.layer,
                   "source": LAYER_SOURCE.get(b.layer, "other"), "thesis": PUBLIC.get(b.id, ("", ""))[1],
                   "status": b.status, "_caveat": bool(b.caveat)} for b in BOOKS}
    if mode == "replay":
        navs: dict[str, pd.Series] = {}
        for bid, (table, arm) in REPLAY.items():
            rows = await _read_all(table, {"select": "d,nav", "arm": f"eq.{arm}", "order": "d.asc"})
            if rows:
                navs[bid] = pd.Series({pd.Timestamp(r["d"]): float(r["nav"]) for r in rows}).sort_index()
        for bid in info:
            info[bid].pop("_caveat", None)
            info[bid]["available"] = bid in navs
            info[bid]["note"] = (f"point-in-time replay ({REPLAY[bid][1]}), computed after the fact"
                                 if bid in navs else "no point-in-time replay for this book")
        return navs, layers, info
    navs, _bench = await load_navs()
    for bid in info:
        s = navs.get(bid)
        s = s.dropna() if s is not None else None
        info[bid]["available"] = s is not None and len(s) >= 2 and info[bid]["status"] != "retired_by_design" \
            and not info[bid]["_caveat"]
        info[bid]["record"] = ([s.index[0].date().isoformat(), s.index[-1].date().isoformat()]
                               if s is not None and len(s) >= 2 else None)
        info[bid]["note"] = ("paper record" if info[bid]["available"]
                             else ("record under review — not selectable" if info[bid]["_caveat"]
                                   else ("retired" if info[bid]["status"] == "retired_by_design" else "no usable record")))
    for v in info.values():
        v.pop("_caveat", None)
    return navs, layers, info
