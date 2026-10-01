"""② β+ 前向记录:在 ① 的 24 币面板内按「动量 + 52 周高点」倾斜(S-428 → S-429,Jazz 2026-09-26)。

Jazz:「长持仓是 baseline,我们落地 beta+ 策略要做动量和其他有效因子的加权。」
「我们不是在做又一个平庸的 ETF,是在做真正的价值捕获与增长增强的量规。」

## 预注册(改任何一项 = 新起点,旧记录留档)

    面板      causal_positioning.DEFAULT_UNIVERSE 的 24 币;合格 = 已有 ≥180 天日线
    信号      combo = 截面排名均值( rank(动量组合), rank(52 周高点) )
              动量组合 = 截面排名均值( 14 天、28 天、90 天收益 )
              52 周高点 = 收盘 / 过去 365 天最高收盘(至少 180 天)
    权重      w_i = (1/N)·(1 + k·z_i),z = 排名映射到 [−1, 1] 去均值后按最大绝对值归一;k = 1 ⇒ 0 ~ 2/N
              只做多、满仓、无杠杆(DECISIONS 07-27 / 08-23)
    时点      信号在再平衡日收盘算,次日收盘成交,之间随价漂移;起点那天在起点收盘直接建仓
    四个臂    panel_hold_w / momentum_52w_w   周频,**7 等份分批**:每份在不同星期几出信号、次日成交(主检验)
              panel_hold_m / momentum_52w_m   每月 1 日出信号(低换手)
              分批的理由(S-431):同一信号只换再平衡的星期几,年化超额从 +13.6%(周六)到 +19.2%(周三),
              头条数字里有 5.6 个点是择时运气。7 份分批 = 每天调 1/7,换手不变(12.9×/年),
              结果 +16.6%、t 3.29、最差 12 个月 +0.2%、相对最大回撤 −11.0%(周一单批:−14.1%)。
              基准与倾斜臂同日程、同延迟、同成本 —— 差值只来自倾斜
    成本      换手 × 10 bps,两臂同扣
    价格      ohlcv_daily · binance_hist(与 S-428 研究同源;CG Pro 有 7 个币历史不足 180 天)
    起点      2026-09-25 收盘
    判据      倾斜臂 − 同日程基准 的累计差,按 regime(BTC 200 日线上/下)分段;≥60 个前向日再谈结论

历史(S-428/S-431,不是证据):周频分批 年化超额 +16.6%、t 3.29、β 0.98、2020–2026 每年为正;
8h K 线 20/60/365 根(≈6.7/20/122 天)不更好:20 根样本外为负,每 8h 再平衡全部更差(S-431)。
**组合因子是看过 86 个变体后挑的,数值偏高**,支撑它的是整个动量族在所有构造下同号。

## 同一份内核

`combo_signal` / `tilt_targets` 也被研究脚本 `s428_beta_plus_factor_tilt.py` 调用 ——
**回测里的权重,就是这本账那天会算出的权重。** `tests/test_beta_plus_momentum.py` 钉住这一点。

## 不存状态:每轮从起点整条重算(fusion 22 天只扣成本的教训,S-427)

判活:`select arm, max(d), count(*) from beta_plus_daily group by 1;` —— UTC 06:00 后 max(d) 应 = 昨天。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

TABLE = "beta_plus_daily"
WRITES_TABLES = (TABLE,)
ARMS = {  # arm → (schedule, tilted?);"W7" = 7 份分批,每份一个星期几
    "panel_hold_w": ("W7", False), "momentum_52w_w": ("W7", True),
    "panel_hold_m": ("M", False), "momentum_52w_m": ("M", True),
}
TRANCHES = 7
K = 1.0
COST_BPS = 10.0
MIN_HIST = 180
INCEPTION = pd.Timestamp("2026-09-25")
PRICE_SOURCE = "binance_hist"
MIN_QUOTED_WEIGHT = 0.90
HISTORY_DAYS = 400
CODE_REF = "S-431 beta_plus_momentum v2 (weekly = 7 tranches)"


def panel_universe() -> tuple[str, ...]:
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
    return tuple(DEFAULT_UNIVERSE)


# ── 内核(研究与账本共用)───────────────────────────────────────────────────────

def combo_signal(P: pd.DataFrame) -> pd.DataFrame:
    """每天每币的 combo 分(越大越该超配)。截面排名只在传入的列之间做。"""
    rk = lambda X: X.rank(axis=1, pct=True)
    mom = {n: P / P.shift(n) - 1 for n in (14, 28, 90)}
    mom_combo = (rk(mom[14]) + rk(mom[28]) + rk(mom[90])) / 3
    high52w = P / P.rolling(365, min_periods=180).max()
    return (rk(mom_combo) + rk(high52w)) / 2


def tilt_targets(x: pd.Series, k: float = K) -> pd.Series:
    """合格币的信号 → 只做多、合计为 1 的目标权重。k=0 ⇒ 等权。"""
    x = x.dropna()
    n = len(x)
    base = pd.Series(1.0 / n, index=x.index)
    if k == 0 or n < 2:
        return base
    z = 2 * x.rank(pct=True) - 1 - (1 / n)
    z = z - z.mean()
    tgt = base * (1 + k * z / z.abs().max())
    tgt = tgt.clip(lower=0)
    return tgt / tgt.sum()


def _signal_days(sched: str) -> list:
    """→ 每一份(tranche)的「出信号日」判据。W7 = 7 份,第 j 份在星期 j 出信号;M = 1 份,每月 1 日。"""
    if sched == "W7":
        return [lambda d, j=j: d.dayofweek == j for j in range(TRANCHES)]
    return [lambda d: d.day == 1]


# ── 账本(纯函数)──────────────────────────────────────────────────────────────

def compute_path(px: pd.DataFrame, panel: tuple[str, ...], source: str,
                 end: pd.Timestamp | None = None) -> list[dict]:
    """起点到 `end` 的每日行(四个臂)。`px` 须含起点前 ≥365 天;NaN = 那天没有真实收盘。"""
    px = px.sort_index()[[s for s in panel if s in px.columns]]
    # 日历化:读价器只返回「有数据的日子」。binance_hist 过去一年整天缺 41 天(最后一次 09-06),
    # 不补日历的话 shift(90) 是 90 行 ≈ 130 个自然日,动量窗口悄悄变长。缺的日子 = NaN。
    px = px.reindex(pd.date_range(px.index.min(), px.index.max(), freq="D"))
    days = [d for d in px.index if d >= INCEPTION and (end is None or d <= end)]
    if not days or days[0] != INCEPTION:
        raise ValueError(f"起点 {INCEPTION.date()} 那天没有面板行 —— 不从别的日子悄悄开始")
    hist = px.notna().cumsum()
    sig = combo_signal(px.ffill())            # 信号用前推价只为对齐窗口;是否可交易另看当天报价
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for arm, (sched, tilted) in ARMS.items():
        books = [_simulate(px, days, hist, sig, tilted, is_sig, arm) for is_sig in _signal_days(sched)]
        for i, d in enumerate(days):
            parts = [bk[i] for bk in books]
            navs = [p_["nav"] for p_ in parts]
            nav = sum(navs) / len(navs)                     # 各份起始资金相同 ⇒ 组合 NAV = 各份 NAV 的均值
            prev = sum(bk[i - 1]["nav"] for bk in books) / len(books) if i > 0 else 1.0
            ret = nav / prev - 1
            w: dict[str, float] = {}
            for p_ in parts:
                for s_, v in p_["w"].items():
                    w[s_] = w.get(s_, 0.0) + v * p_["nav"] / sum(navs)
            snap = next((p_["signal"] for p_ in parts if p_["signal"] is not None), None)
            rows.append({
                "d": d.date().isoformat(), "arm": arm,
                "nav": round(nav, 8), "ret": round(ret, 8),
                "weights": {s_: round(v, 5) for s_, v in sorted(w.items(), key=lambda kv: -kv[1])},
                "traded": any(p_["traded"] for p_ in parts),
                "turnover": round(sum(p_["turnover"] * p_["nav"] for p_ in parts) / sum(navs), 6),
                "signal": snap, "n_eligible": len(snap) if snap else None,
                "n_filled": max(p_["n_filled"] for p_ in parts), "source": source,
                "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF, "computed_at": now,
            })
    return rows


def _simulate(px, days, hist, sig, tilted: bool, is_signal_day, arm: str) -> list[dict]:
    """一份(tranche)从起点到末日的逐日记录。起点当天收盘建仓;此后出信号日收盘出目标、次日收盘成交。

    记账走公用内核 `src/data/accounting/nav_kernel.run_nav`(v0.2 阶段 1);这里只负责**出目标、定成交日**。
    """
    from src.data.accounting.nav_kernel import run_nav

    orders: dict = {}
    snapshots: dict = {}
    for i, d in enumerate(days):
        if not (i == 0 or is_signal_day(d)):
            continue
        row_px = px.loc[d]
        quoted = {s for s in row_px.index if pd.notna(row_px[s])}
        elig = [s for s in px.columns if hist.at[d, s] >= MIN_HIST and s in quoted]
        x = sig.loc[d, elig]
        t = tilt_targets(x, K if tilted else 0.0).to_dict()
        snapshots[d] = {s: round(float(v), 4) for s, v in x.dropna().sort_values(ascending=False).items()}
        if i == 0:                                   # 起点:当天收盘直接建仓
            orders[d] = t
        elif i + 1 < len(days):                      # 信号日收盘出目标,次日收盘成交
            orders[days[i + 1]] = t
    book = run_nav(px, orders, cost_bps=COST_BPS, min_quoted_weight=MIN_QUOTED_WEIGHT, label=arm,
                   days=list(days))
    return [{"nav": b["nav"], "w": b["w"], "traded": b["traded"], "turnover": b["turnover"],
             "signal": snapshots.get(d), "n_filled": b["n_filled"]} for d, b in zip(days, book)]


async def run_once() -> dict[str, Any]:
    """重算到昨天那根已收盘日线并整条 upsert。幂等、无状态。"""
    from src.data.market.panel_read import read_panel
    from src.api.store import supabase_upsert_table
    from src.data.signals.tokenization_tilt import closing_bars_final

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    if target < INCEPTION:
        return {"ok": True, "refused": True, "written": 0, "reason": "起点未到"}
    panel = panel_universe()
    start = (INCEPTION - pd.Timedelta(days=HISTORY_DAYS)).date().isoformat()
    p = await read_panel(list(panel), start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))   # 前推的价格不是价格

    ready, stale, why = await closing_bars_final(p.symbols, target, PRICE_SOURCE)
    if not ready:
        return why
    px.loc[target, [c for c in px.columns if c not in ready]] = np.nan

    rows = await asyncio.to_thread(compute_path, px, panel, p.source, target)
    res = await supabase_upsert_table(TABLE, rows, on_conflict="d,arm")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    last = {r["arm"]: r["nav"] for r in rows if r["d"] == target.date().isoformat()}
    return {"ok": True, "refused": False, "written": len(rows),
            "reason": f"重算至 {target.date()}", "nav": last, "barred": list(p.barred),
            "stale_in_source": stale}
