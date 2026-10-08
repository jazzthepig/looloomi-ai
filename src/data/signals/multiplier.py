"""③ 推力 —— ① 的持仓 × 状态决定的 0.7 / 1.0 / 1.3 倍敞口(T-063,S-505)。

## 为什么有这本账

Jazz 10-07 定调:执行只读一张表 —— ① 的推力 + ② 的倾斜。② 有账在跑,③ 一本都没有;按回报层级它排在 ④ 之前。
同日裁决「不等 30 / 60 / 90 天前向」:今天就按时点回放 2023 起的历史,前向账本同时开始。

## 预注册(2026-10-08 收盘前定下;零个拟合参数;改任何一项 = 新起点,旧记录留档)

    状态    state_daily 的面板特征,用 d−1 收盘的值决定 d 的敞口(state_daily 本身按时点计算):
            dist_200(面板距 200 日线)、vol_pct_3y(30 日波动在过去 3 年中的分位,本身滚动)
    规则    上行 = dist_200 > 0;平静 = vol_pct_3y ≤ 0.5
            m = 1.3 上行且平静;0.7 下行且不平静;其余 1.0                     ← 切点是常数,不来自任何样本
    敞口    ③ 的定义:0.7–1.3 倍,永不做空、永不到 0(m88 的 dd_stop 到 0× 越出了这个定义)
    底仓    ① = core_cap 的 cap_a1 规则(24 名、市值加权、单币 ≤ 40%、周一再平衡、10 bps)
    现金腿  m < 1 的部分按现金等价物年化 4%(10-05 裁决:类国债、高流动、无极端对手盘)
    杠杆    m > 1 的部分付资金费:面板 funding_7d_ann(缺值的日子按 10% 年化);① 自己仍是现货
    成本    敞口变化 |Δm| × 10 bps
    对照    ① 本身;随机择时 = 把 m 序列按 20 天一块随机重排(保留 m 的分布与大致换手),1,000 次,
            报实测「③ − ①」的总收益差在随机分布里的分位
    窗口    回放 2023-01-02 起;2023–2024 = 样本内语境(规则没有拟合,但它是在看过这段之后写的),
            2025-01-01 → 起点前一天 = 留出段;起点起 = 前向
    起点    2026-10-08 收盘(第一天前向收益 = 10-09)

## 已知偏差

① 的 24 名是今天的名单回填到 2023(幸存者)。它对 ① 与 ③ 同时成立;③ 相对 ① 的超额(择时价值)受影响小,但不是零。

## 写什么

`multiplier_daily (d, arm)`:`mult_v1` = 前向(只从起点起,NAV 在起点 = 1)· `mult_v1_replay` = 回放全程 ·
`core_replay` = 同期 ① 的回放。评估(三个窗口的总收益 / 回撤 / Sharpe / 随机分位)写进每轮的 loop_attempt.detail。

## 判活判据(规则 5b ②)

    select max(d) from multiplier_daily where arm = 'mult_v1_replay';   -- UTC 08:00 后应 = 昨天
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from src.data.signals.core_cap import (COST_BPS, MCAP_MAX_AGE_DAYS, MIN_MCAP_COVERAGE, MIN_QUOTED_WEIGHT,
                                       PRICE_SOURCE, capped_weights, panel_universe)

TABLE = "multiplier_daily"
WRITES_TABLES = (TABLE,)
ARM, REPLAY_ARM, CORE_ARM = "mult_v1", "mult_v1_replay", "core_replay"
LEVELS = (0.7, 1.0, 1.3)
VOL_CUT = 0.5
CASH_ANN = 0.04
FUNDING_FALLBACK_ANN = 0.10
SWITCH_COST_BPS = 10.0
REPLAY_START = pd.Timestamp("2023-01-02")
HOLDOUT_START = pd.Timestamp("2025-01-01")
INCEPTION = pd.Timestamp("2026-10-08")
N_RANDOM, BLOCK, SEED = 1000, 20, 63
CODE_REF = "T-063 multiplier v1"


def multiplier(dist_200: Optional[float], vol_pct: Optional[float]) -> float:
    """纯函数。读不到状态 ⇒ 1.0(不加不减 —— 不把『不知道』当成信号)。"""
    if dist_200 is None or vol_pct is None or not (math.isfinite(dist_200) and math.isfinite(vol_pct)):
        return 1.0
    up, calm = dist_200 > 0, vol_pct <= VOL_CUT
    if up and calm:
        return LEVELS[2]
    if not up and not calm:
        return LEVELS[0]
    return LEVELS[1]


def apply_multiplier(core_ret: pd.Series, m_prev: pd.Series, funding_ann: pd.Series) -> pd.DataFrame:
    """纯函数。m_prev(d) = d−1 收盘定下、作用于 d 的敞口。返回每天的 ret / 成本 / nav。"""
    m = m_prev.reindex(core_ret.index).fillna(1.0).clip(LEVELS[0], LEVELS[-1])
    fund = funding_ann.reindex(core_ret.index).astype(float).fillna(FUNDING_FALLBACK_ANN) / 365.0
    cash = CASH_ANN / 365.0
    gross = m * core_ret + (1 - m).clip(lower=0) * cash - (m - 1).clip(lower=0) * fund
    cost = m.diff().abs().fillna(0.0) * SWITCH_COST_BPS / 1e4
    ret = gross - cost
    return pd.DataFrame({"m": m, "ret": ret, "cost": cost, "nav": (1 + ret).cumprod()})


def _stats(r: pd.Series) -> dict[str, Optional[float]]:
    if len(r) < 2:
        return {"n": len(r), "total": None, "sharpe": None, "maxdd": None}
    nav = (1 + r).cumprod()
    sd = float(r.std())
    return {"n": int(len(r)), "total": round(float(nav.iloc[-1] - 1), 5),
            "sharpe": round(float(r.mean() / sd * math.sqrt(365)), 3) if sd > 0 else None,
            "maxdd": round(float((nav / nav.cummax() - 1).min()), 5)}


def random_timing_pct(core_ret: pd.Series, m_prev: pd.Series, funding_ann: pd.Series,
                      n: int = N_RANDOM, block: int = BLOCK, seed: int = SEED) -> dict[str, Optional[float]]:
    """把 m 序列按 block 天一块随机重排 n 次,重算「③ − ①」总收益差;报实测在其中的分位。"""
    idx = core_ret.index
    m = m_prev.reindex(idx).fillna(1.0).to_numpy()
    if len(m) < 2 * block:
        return {"pct_vs_random": None, "random_p50": None, "random_p95": None}
    r1 = core_ret.to_numpy()
    fund = funding_ann.reindex(idx).astype(float).fillna(FUNDING_FALLBACK_ANN).to_numpy() / 365.0
    cash = CASH_ANN / 365.0

    def excess(mm: np.ndarray) -> float:
        gross = mm * r1 + np.clip(1 - mm, 0, None) * cash - np.clip(mm - 1, 0, None) * fund
        cost = np.abs(np.diff(mm, prepend=mm[0])) * SWITCH_COST_BPS / 1e4
        return float(np.prod(1 + gross - cost) - np.prod(1 + r1))

    actual = excess(m)
    rng = np.random.default_rng(seed)
    blocks = [m[i:i + block] for i in range(0, len(m), block)]
    draws = np.array([excess(np.concatenate([blocks[j] for j in rng.permutation(len(blocks))])) for _ in range(n)])
    return {"excess_total": round(actual, 5), "pct_vs_random": round(float((draws < actual).mean()), 4),
            "random_p50": round(float(np.percentile(draws, 50)), 5),
            "random_p95": round(float(np.percentile(draws, 95)), 5)}


def evaluate(core_ret: pd.Series, m_prev: pd.Series, funding_ann: pd.Series, end: pd.Timestamp) -> dict[str, Any]:
    """三个窗口:样本内语境 / 留出段 / 前向。每个窗口:① 与 ③ 的总收益、Sharpe、回撤,以及随机择时分位。"""
    windows = {"in_sample_2023_2024": (REPLAY_START, HOLDOUT_START - pd.Timedelta(days=1)),
               "holdout_2025_to_inception": (HOLDOUT_START, INCEPTION - pd.Timedelta(days=1)),
               "forward": (INCEPTION + pd.Timedelta(days=1), end)}
    out: dict[str, Any] = {}
    for name, (lo, hi) in windows.items():
        sel = (core_ret.index >= lo) & (core_ret.index <= hi)
        r1 = core_ret[sel]
        if len(r1) < 2:
            out[name] = {"n": int(len(r1))}
            continue
        book = apply_multiplier(r1, m_prev, funding_ann)
        mm = book["m"]
        out[name] = {"core": _stats(r1), "mult": _stats(book["ret"]),
                     "share_days": {str(lv): round(float((mm == lv).mean()), 3) for lv in LEVELS},
                     **random_timing_pct(r1, m_prev, funding_ann)}
    return out


def core_returns(px: pd.DataFrame, mcap_prev: pd.DataFrame, start: pd.Timestamp,
                 end: pd.Timestamp) -> pd.Series:
    """① 的日收益(含成本),从 start 起按 core_cap 的同一规则回放。纯函数。"""
    from src.data.accounting.nav_kernel import run_nav

    days = [d for d in px.sort_index().index if start <= d <= end]
    orders: dict[pd.Timestamp, dict[str, float]] = {}
    for d in days:
        if not (d == days[0] or d.weekday() == 0):
            continue
        row_px = px.loc[d]
        mc = mcap_prev.loc[d] if d in mcap_prev.index else pd.Series(dtype=float)
        quoted = [s for s in px.columns if pd.notna(row_px.get(s))]
        avail = {s: mc.get(s) for s in quoted if pd.notna(mc.get(s))}
        if not quoted or len(avail) < MIN_MCAP_COVERAGE * len(quoted):
            raise ValueError(f"{d.date()} 有收盘的 {len(quoted)} 个币里只有 {len(avail)} 个有 ≤{MCAP_MAX_AGE_DAYS} 天的市值")
        orders[d] = capped_weights(avail, 1.0)
    book = run_nav(px, orders, cost_bps=COST_BPS, min_quoted_weight=MIN_QUOTED_WEIGHT, label="core_replay",
                   renormalize_to_quoted=False, days=days)
    return pd.Series([b["ret"] for b in book], index=pd.DatetimeIndex(days))


def build_rows(core_ret: pd.Series, state: pd.DataFrame, end: pd.Timestamp) -> tuple[list[dict], dict[str, Any]]:
    """纯函数。state:行 = d,列 = dist_200 / vol_pct_3y / funding_7d_ann(d 收盘可知的值)。"""
    m_at = pd.Series({d: multiplier(_f(row.get("dist_200")), _f(row.get("vol_pct_3y")))
                      for d, row in state.iterrows()}, dtype=float)
    m_prev = m_at.shift(1, freq="D")                       # d−1 收盘定的敞口作用于 d
    funding = state.get("funding_7d_ann", pd.Series(dtype=float)).astype(float)
    core_ret = core_ret[core_ret.index <= end]
    replay = apply_multiplier(core_ret, m_prev, funding)
    core_nav = (1 + core_ret).cumprod()
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for d, b in replay.iterrows():
        st = state.loc[d] if d in state.index else pd.Series(dtype=float)
        common = {"d": d.date().isoformat(), "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF,
                  "computed_at": now, "dist_200": _r(st.get("dist_200")), "vol_pct_3y": _r(st.get("vol_pct_3y"))}
        rows.append({**common, "arm": REPLAY_ARM, "m": float(b["m"]), "ret": round(float(b["ret"]), 8),
                     "nav": round(float(b["nav"]), 8), "cost": round(float(b["cost"]), 8)})
        rows.append({**common, "arm": CORE_ARM, "m": 1.0, "ret": round(float(core_ret[d]), 8),
                     "nav": round(float(core_nav[d]), 8), "cost": 0.0})
    fwd = core_ret[core_ret.index > INCEPTION]
    if len(fwd):
        book = apply_multiplier(fwd, m_prev, funding)
        for d, b in book.iterrows():
            rows.append({"d": d.date().isoformat(), "arm": ARM, "m": float(b["m"]), "ret": round(float(b["ret"]), 8),
                         "nav": round(float(b["nav"]), 8), "cost": round(float(b["cost"]), 8),
                         "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF, "computed_at": now,
                         "dist_200": None, "vol_pct_3y": None})
    return rows, evaluate(core_ret, m_prev, funding, end)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(v: Any) -> Optional[float]:
    x = _f(v)
    return round(x, 6) if x is not None else None


async def _state(start: str) -> pd.DataFrame:
    from src.data.style.header import _read_all
    rows = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                                           "feature": "in.(dist_200,vol_pct_3y,funding_7d_ann)",
                                           "d": f"gte.{start}", "order": "d.asc"})
    if not rows:
        raise RuntimeError("state_daily 读不到 —— 不按 1.0 顶替整段")
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    return df.pivot_table(index="d", columns="feature", values="value")


async def run_once() -> dict[str, Any]:
    """回放 2023 起到昨天已收盘那根,并写前向行。幂等,整条 upsert。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.panel_read import read_panel
    from src.data.signals.core_cap import _mcap_prev
    from src.data.signals.tokenization_tilt import closing_bars_final

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    panel = list(panel_universe())
    start = (REPLAY_START - pd.Timedelta(days=3)).date().isoformat()
    p = await read_panel(panel, start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))
    ready, stale, why = await closing_bars_final(p.symbols, target, PRICE_SOURCE)
    if not ready:
        return why
    px.loc[target, [c for c in px.columns if c not in ready]] = float("nan")
    mc = await _mcap_prev(panel, start)
    state = await _state(start)
    core_ret = await asyncio.to_thread(core_returns, px, mc, REPLAY_START, target)
    rows, ev = await asyncio.to_thread(build_rows, core_ret, state, target)
    res = await supabase_upsert_table(TABLE, rows, on_conflict="d,arm")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"回放至 {target.date()}",
            "eval": ev, "stale_in_source": stale}
