"""② CIS 倾斜 —— 在 ① 的持仓内按 CIS 超配,仍满仓多头(T-051 预注册 / T-052,S-491 / S-493)。

## 为什么有这本账

§5b(07-27)写下:CIS 的岗位是 ②(在持有的面板内决定超配谁),不是绝对的跑赢信号。对外的信号记录也这么说 ——
OUTPERFORM 的绝对信号在 β≈1.5 的宇宙里跑输 BTC(S-491)。可 ② 里一直没有一本 CIS 倾斜账本:
核心产品不在自己的验证机器里。这本账把它放进去。

## 预注册(lane B T-051 v0.5 + Seth 10-06 的三处收紧;改任何一项 = 新起点,旧记录留档)

    主臂   cis_a1    w ∝ w_①(d) × exp(K · z(d)),再用 core_cap.capped_weights 迭代压到单币 ≤ 40%     ← 只有这一臂
    w_①    与 core_cap 同一读法、同一函数:capped_weights(市值(d−1), α=1) —— 不读 core_cap_daily 的行(同一份计算,少一个依赖)
    z      面板内截面 z:raw_cis_score(未经 regime 调整的 CIS),取 recorded_at ≤ d 收盘(23:59:59 UTC)的最近一条;
           超过 CIS_MAX_AGE_DAYS 天的分数当缺;缺分的币 z = 0(保持 ① 权重,不剔除);有分的不足 2 个或标准差 0 ⇒ 全部 z = 0
    K      0.5,事先固定,不网格(T-051 §11.1)
    面板    core_cap.panel_universe()(24 名);只持现货、无杠杆、满仓
    价格    binance_hist;市值 asset_mcap_daily(与 ① 同源同读法)
    节奏    起点收盘建仓;每周一(UTC)收盘再平衡;其余日子随价格漂移
    成本    换手 × 10 bps(公用内核 nav_kernel.run_nav)
    起点    2026-10-06 收盘(代码与参数在当天收盘前定下;第一天前向收益 = 10-07)
    基准    ① 本身(登记表 benchmark="core")
    证伪    L3 l3-v2:前向 ≥ 60 天 + 任意时刻下界 > 0;最早 2026-12-05

Seth 收紧的三处(相对 T-051 v0.5):① 只留主臂(α=0.5 / α=0 的倾斜臂不增加决策信息,只增加试验次数);
② CIS 超过 3 天视为缺(与市值的 3 天规则一致);③ 起点提前到 10-06(v0.5 写的是 10-13 —— 参数今天就定了,多等一周只是少一周前向)。

## 判活判据(规则 5b ②)

    select max(d), count(*) from cis_tilt_daily;   -- UTC 08:00 后 max(d) 应 = 昨天
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pandas as pd

from src.data.signals.core_cap import (COST_BPS, MCAP_MAX_AGE_DAYS, MIN_MCAP_COVERAGE, MIN_QUOTED_WEIGHT,
                                       PRICE_SOURCE, SINGLE_ASSET_CAP, capped_weights, panel_universe)

TABLE = "cis_tilt_daily"
WRITES_TABLES = (TABLE,)
ARM = "cis_a1"
K = 0.5
CIS_COLUMN = "raw_cis_score"
CIS_MAX_AGE_DAYS = 3
INCEPTION = pd.Timestamp("2026-10-06")
CODE_REF = "T-052 cis_tilt v1"


def is_rebalance_day(d: pd.Timestamp) -> bool:
    return d == INCEPTION or d.weekday() == 0


def cis_z(scores: Mapping[str, Optional[float]], names: list[str]) -> dict[str, float]:
    """面板内截面 z。缺分 / 非有限 ⇒ 0;有分的不足 2 个或标准差为 0 ⇒ 全部 0。样本标准差(同 T-051 的 STDDEV_SAMP)。"""
    have = {s: float(v) for s, v in scores.items() if s in names and v is not None and math.isfinite(float(v))}
    if len(have) < 2:
        return {s: 0.0 for s in names}
    mu = sum(have.values()) / len(have)
    sd = math.sqrt(sum((v - mu) ** 2 for v in have.values()) / (len(have) - 1))
    if not sd > 0:
        return {s: 0.0 for s in names}
    return {s: ((have[s] - mu) / sd if s in have else 0.0) for s in names}


def tilted_weights(w_core: Mapping[str, float], z: Mapping[str, float], k: float = K,
                   cap: float = SINGLE_ASSET_CAP) -> dict[str, float]:
    """w ∝ w_① × exp(k·z),再按 ① 的同一个迭代算法压到单币 ≤ cap(capped_weights 以 α=1 吃原始值)。"""
    raw = {s: float(w) * math.exp(k * float(z.get(s, 0.0))) for s, w in w_core.items() if w > 0}
    return capped_weights(raw, 1.0, cap)


def compute_path(px: pd.DataFrame, mcap_prev: pd.DataFrame, cis_at: Mapping[pd.Timestamp, Mapping[str, float]],
                 barred: list[str], source: str, end: Optional[pd.Timestamp] = None) -> list[dict]:
    """纯函数。`cis_at`:再平衡日 → {币: 当时可用的 CIS}(调用方已按时点与新鲜度筛过)。"""
    from src.data.accounting.nav_kernel import run_nav

    px = px.sort_index()
    days = [d for d in px.index if d >= INCEPTION and (end is None or d <= end)]
    if not days or days[0] != INCEPTION:
        raise ValueError(f"起点 {INCEPTION.date()} 那天没有面板行 —— 不从别的日子悄悄开始")
    now = datetime.now(timezone.utc).isoformat()
    orders: dict[pd.Timestamp, dict[str, float]] = {}
    zs: dict[pd.Timestamp, dict[str, float]] = {}
    n_scored: dict[pd.Timestamp, int] = {}
    for d in days:
        if not is_rebalance_day(d):
            continue
        row_px = px.loc[d]
        mc = mcap_prev.loc[d] if d in mcap_prev.index else pd.Series(dtype=float)
        quoted = [s for s in px.columns if pd.notna(row_px.get(s))]
        avail = {s: mc.get(s) for s in quoted if pd.notna(mc.get(s))}
        if not quoted or len(avail) < MIN_MCAP_COVERAGE * len(quoted):
            raise ValueError(f"{d.date()} 有收盘的 {len(quoted)} 个币里只有 {len(avail)} 个有 ≤{MCAP_MAX_AGE_DAYS} 天的市值"
                             f" —— 不在半个面板上做 ① 的市值加权")
        w_core = capped_weights(avail, 1.0)
        scores = dict(cis_at.get(d) or {})
        z = cis_z(scores, list(w_core))
        zs[d] = z
        n_scored[d] = sum(1 for s in w_core if s in scores and scores[s] is not None)
        orders[d] = tilted_weights(w_core, z)
    book = run_nav(px, orders, cost_bps=COST_BPS, min_quoted_weight=MIN_QUOTED_WEIGHT, label=ARM,
                   renormalize_to_quoted=False, days=days)
    rows: list[dict] = []
    for d, b in zip(days, book):
        w = b["w"]
        rows.append({
            "d": d.date().isoformat(), "arm": ARM, "k": K,
            "nav": round(b["nav"], 8), "ret": round(b["ret"], 8),
            "weights": {s: round(v, 5) for s, v in sorted(w.items(), key=lambda kv: -kv[1])},
            "z": {s: round(v, 4) for s, v in sorted(zs[d].items(), key=lambda kv: -kv[1])} if d in zs else None,
            "n_scored": n_scored.get(d),
            "max_weight": round(max(w.values()), 5) if w else None,
            "rebalanced": b["traded"], "turnover": round(b["turnover"], 6),
            "n_quoted": b["n_quoted"], "n_filled": b["n_filled"],
            "barred": barred, "source": source,
            "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF, "computed_at": now,
        })
    return rows


async def _cis_at(rebal_days: list[pd.Timestamp], symbols: list[str]) -> dict[pd.Timestamp, dict[str, float]]:
    """每个再平衡日:各币 recorded_at ≤ d 收盘的最近一条 raw_cis_score,且不早于 d − CIS_MAX_AGE_DAYS。读不到抛异常。"""
    from src.data.style.header import _read_all
    out: dict[pd.Timestamp, dict[str, float]] = {}
    for d in rebal_days:
        lo = (d - pd.Timedelta(days=CIS_MAX_AGE_DAYS)).date().isoformat()
        hi = (d + pd.Timedelta(days=1)).date().isoformat()
        rows = await _read_all("cis_scores", {
            "select": f"symbol,{CIS_COLUMN},recorded_at", "order": "recorded_at.asc",
            "symbol": "in.(" + ",".join(symbols) + ")",
            "and": f"(recorded_at.gte.{lo}T00:00:00Z,recorded_at.lt.{hi}T00:00:00Z)"})
        latest: dict[str, float] = {}
        for r in rows:
            v = r.get(CIS_COLUMN)
            if v is not None:
                latest[r["symbol"]] = float(v)          # 升序读,后来的覆盖前面的 = 最近一条
        out[d] = latest
    return out


async def run_once() -> dict[str, Any]:
    """重算到昨天那根已收盘日线并整条 upsert。幂等。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.panel_read import read_panel
    from src.data.signals.core_cap import _mcap_prev
    from src.data.signals.tokenization_tilt import closing_bars_final

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    if target < INCEPTION:
        return {"ok": True, "refused": True, "written": 0, "reason": f"起点 {INCEPTION.date()} 未到"}
    panel = list(panel_universe())
    start = (INCEPTION - pd.Timedelta(days=3)).date().isoformat()
    p = await read_panel(panel, start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))   # 前推的价格不是价格

    ready, stale, why = await closing_bars_final(p.symbols, target, PRICE_SOURCE)
    if not ready:
        return why
    px.loc[target, [c for c in px.columns if c not in ready]] = float("nan")
    mc = await _mcap_prev(panel, start)
    rebal = [d for d in px.index if INCEPTION <= d <= target and is_rebalance_day(d)]
    cis = await _cis_at(rebal, panel)

    rows = await asyncio.to_thread(compute_path, px, mc, cis, list(p.barred), p.source, target)
    res = await supabase_upsert_table(TABLE, rows, on_conflict="d,arm")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    last = next((r for r in rows if r["d"] == target.date().isoformat()), {})
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"重算至 {target.date()}",
            "nav": last.get("nav"), "top": dict(list((last.get("weights") or {}).items())[:3]),
            "n_scored_last_rebal": len(cis[rebal[-1]]) if rebal else 0, "stale_in_source": stale}
