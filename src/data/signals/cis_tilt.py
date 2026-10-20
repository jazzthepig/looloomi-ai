"""② CIS 倾斜 —— 在 ① 的持仓内按 CIS 超配,仍满仓多头(T-051 预注册 / T-052,S-491 / S-493;新 ① 上的臂 = T-088 / S-556)。

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

## T-088 / S-556:① 切到 cap_a1_u(不设单币上限)后,在新 ① 上的 ② 臂(2026-10-12 起)

    主臂   cis_a1_u    同 cis_a1 的 K、z、面板、价格、节奏、成本 ——
                     但 w_① 用 capped_weights(市值(d−1), α=1, cap=1.0)(core_cap.ARM_CAP['cap_a1_u']),
                     **不再**按 40% 压;tilted_weights 的 cap 也 = 1.0(同一个迭代算法,只是封顶解开)
    起点    core_cap.CORE_SINCE = 2026-10-12 收盘(决定在 10-12 15:55 UTC 做出,早于当天收盘;第一天前向收益是 10-13)
    回放    cis_a1_u_replay 同样按 cap=1.0 重算 2023-01-02 起;z 用 cis_rebuild_daily(code_ref = rebuild.CODE_REF,
            d−1 那天的 score),不读 cis_scores 的实时表 ——
            重建版才能在 2023 起给出一条统一标准的历史(S-531/v1.3),实时表从 2025-05 起才有
    其余    cis_a1 与 cis_a1_u 并行写;cis_a1_replay 不在本卡的范围,另立

## z 的来源(cis_a1_u_replay)

T-088 acceptance:z **只用 d−1 及以前**。replay 把每一天的 z 钉在 d−1 那条重建的 CIS 行上 —— 重建与实盘 T2
同函数同输入(cis_rebuild.score_day),所以分母是同一份。code_ref 在数据里固定,跟 rebuild.CODE_REF 走。

## S-640:资金费拥挤倾斜(② 第 4 个候选,台账 S-640 预注册;B 道 T-155 过、Seth 独立复算)

    主臂   fund_a1_u   BTC / ETH 保持 w_①;其余在剩余份额内按 w_① × exp(K · z_f) 重排(K = 0.5,不网格)
    w_①    与 cis_a1_u 同一读法:capped_weights(市值(d−1), α=1, cap=1.0)
    z_f    −(山寨在 d−7 … d−1 的平均资金费率的截面 z)—— 资金费 = v_funding_daily(binance_perp),按期数加权;
           只用 d 之前的日子;没有资金费的山寨 z_f = 0;有费的不足 2 个或标准差 0 ⇒ 全部 0;BTC / ETH 不进 z
    节奏    与 ② 同:起点收盘建仓、每周一收盘再平衡、换手 × 10bps(同一个 run_nav)
    起点    2026-10-26 收盘(代码在 10-20 定下;第一天前向收益 = 10-27)。回放臂 fund_a1_u_replay 从 2023-01-02 起
    证伪    同 ② 的 L3:前向 ≥ 60 天且任意时刻下界 > 0;最早 2026-12-25。族内第 4 次、族内不显著 —— 前向才是检验

## 判活判据(规则 5b ②)

    select arm, max(d), count(*) from cis_tilt_daily group by 1;   -- UTC 08:00 后 max(d) 应 = 昨天(fund_a1_u 10-26 起)
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from src.data.signals.core_cap import (CORE_SINCE, COST_BPS, MCAP_MAX_AGE_DAYS, MIN_MCAP_COVERAGE,
                                       MIN_QUOTED_WEIGHT, PRICE_SOURCE, SINGLE_ASSET_CAP, ARM_CAP,
                                       capped_weights, panel_universe)

TABLE = "cis_tilt_daily"
WRITES_TABLES = (TABLE,)
ARM = "cis_a1"
#: T-088:① 不设上限后,② 在新 ① 上的臂(起点 = core_cap.CORE_SINCE)
ARM_U = "cis_a1_u"
REPLAY_ARM_U = "cis_a1_u_replay"
REPLAY_START = pd.Timestamp("2023-01-02")
K = 0.5
CIS_COLUMN = "raw_cis_score"
CIS_MAX_AGE_DAYS = 3
INCEPTION = pd.Timestamp("2026-10-06")
INCEPTION_U = CORE_SINCE
#: cis_a1 的单币上限 = ① 的旧上限 = 0.40;cis_a1_u = ① 解除上限后的 = 1.0
ARM_CAP_U = ARM_CAP["cap_a1_u"]
CODE_REF = "T-052 cis_tilt v1"
CODE_REF_U = "T-088 cis_tilt v2 (cap_a1_u 底仓,no single-name cap)"
# S-640:资金费拥挤倾斜(前向 + 回放)
FUND_ARM = "fund_a1_u"
FUND_REPLAY_ARM = "fund_a1_u_replay"
FUND_INCEPTION = pd.Timestamp("2026-10-26")
FUND_LOOKBACK_DAYS = 7
FUND_PINNED = ("BTC", "ETH")
FUND_VIEW = "v_funding_daily"
CODE_REF_FUND = "S-640 fund_tilt v1 (cap_a1_u 底仓,BTC/ETH 钉住,z = −资金费 7 日均值截面 z)"


def is_rebalance_day(d: pd.Timestamp, inception: pd.Timestamp = INCEPTION) -> bool:
    return d == inception or d.weekday() == 0


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
    """w ∝ w_① × exp(k·z),再按 ① 的同一个迭代算法压到单币 ≤ cap(capped_weights 以 α=1 吃原始值)。

    T-088:cis_a1_u 传 cap=1.0(== ARM_CAP['cap_a1_u']),不再按 40% 压;cis_a1 仍 0.40。"""
    raw = {s: float(w) * math.exp(k * float(z.get(s, 0.0))) for s, w in w_core.items() if w > 0}
    return capped_weights(raw, 1.0, cap)


def funding_z(mean_rates: Mapping[str, Optional[float]], alts: list[str]) -> dict[str, float]:
    """S-640:山寨截面上「负的」资金费 z(拥挤的 z 为负 ⇒ 少配)。缺 / 非有限 ⇒ 0;有费的不足 2 个或标准差 0 ⇒ 全部 0。
    与 cis_z 同一个样本标准差,只是取负。"""
    z = cis_z({s: mean_rates.get(s) for s in alts}, alts)
    return {s: (-v if v else 0.0) for s, v in z.items()}


def pinned_tilt(w_core: Mapping[str, float], z: Mapping[str, float], pinned: tuple[str, ...] = FUND_PINNED,
                k: float = K) -> dict[str, float]:
    """S-640:钉住的名字保持 w_①;其余在剩余份额(1 − 钉住之和)内按 w_① × exp(k·z) 重排。总和不变,不做单币上限(cap_a1_u)。"""
    w = {s: float(v) for s, v in w_core.items() if v and v > 0}
    fixed = {s: v for s, v in w.items() if s in pinned}
    rest = {s: v * math.exp(k * float(z.get(s, 0.0))) for s, v in w.items() if s not in pinned}
    share = sum(w.values()) - sum(fixed.values())
    tot = sum(rest.values())
    out = dict(fixed)
    if tot > 0:
        out.update({s: v / tot * share for s, v in rest.items()})
    return out


def fund_means(daily: list[Mapping[str, Any]], rebal_days: list[pd.Timestamp],
               lookback: int = FUND_LOOKBACK_DAYS) -> dict[pd.Timestamp, dict[str, float]]:
    """纯函数。v_funding_daily 的行(symbol, d, funding_rate = 当日平均, n = 当日期数)→ 每个再平衡日 d:
    各币 [d − lookback, d − 1] 的按期数加权平均资金费率。只用 d 之前的日子;窗口里一行都没有的币不出现(= 缺)。"""
    by_sym: dict[str, list[tuple[pd.Timestamp, float, int]]] = {}
    for r in daily:
        try:
            d, rate, n = pd.Timestamp(str(r["d"])[:10]), float(r["funding_rate"]), int(r.get("n") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if n > 0 and math.isfinite(rate):
            by_sym.setdefault(str(r["symbol"]), []).append((d, rate, n))
    out: dict[pd.Timestamp, dict[str, float]] = {}
    for d in rebal_days:
        lo = d - pd.Timedelta(days=lookback)
        m: dict[str, float] = {}
        for sym, rows in by_sym.items():
            num = sum(rate * n for dd, rate, n in rows if lo <= dd < d)
            den = sum(n for dd, rate, n in rows if lo <= dd < d)
            if den > 0:
                m[sym] = num / den
        out[d] = m
    return out


def compute_path(px: pd.DataFrame, mcap_prev: pd.DataFrame, cis_at: Mapping[pd.Timestamp, Mapping[str, float]],
                 barred: list[str], source: str, end: Optional[pd.Timestamp] = None,
                 arm: str = ARM, inception: Optional[pd.Timestamp] = None,
                 cap: Optional[float] = None, code_ref: Optional[str] = None,
                 mode: str = "cis") -> list[dict]:
    """纯函数。`cis_at`:再平衡日 → {币: 当时可用的 CIS}(调用方已按时点与新鲜度筛过)。
    S-640:mode="fund" 时 `cis_at` 是 {币: d−7…d−1 的平均资金费率},z = funding_z(只在山寨里),权重 = pinned_tilt(BTC / ETH 钉住)。

    T-088:加 `arm` / `inception` / `cap` / `code_ref` 参数。cis_a1_u 用 arm=ARM_U, inception=INCEPTION_U,
    cap=ARM_CAP_U(=1.0), code_ref=CODE_REF_U。cis_a1 不传参就是原行为。"""
    from src.data.accounting.nav_kernel import run_nav

    inception = inception if inception is not None else INCEPTION
    cap = cap if cap is not None else SINGLE_ASSET_CAP
    code_ref = code_ref if code_ref is not None else CODE_REF
    px = px.sort_index()
    days = [d for d in px.index if d >= inception and (end is None or d <= end)]
    if not days or days[0] != inception:
        raise ValueError(f"起点 {inception.date()} 那天没有面板行 —— 不从别的日子悄悄开始")
    now = datetime.now(timezone.utc).isoformat()
    orders: dict[pd.Timestamp, dict[str, float]] = {}
    zs: dict[pd.Timestamp, dict[str, float]] = {}
    n_scored: dict[pd.Timestamp, int] = {}
    for d in days:
        if not is_rebalance_day(d, inception):
            continue
        row_px = px.loc[d]
        mc = mcap_prev.loc[d] if d in mcap_prev.index else pd.Series(dtype=float)
        quoted = [s for s in px.columns if pd.notna(row_px.get(s))]
        avail = {s: mc.get(s) for s in quoted if pd.notna(mc.get(s))}
        if not quoted or len(avail) < MIN_MCAP_COVERAGE * len(quoted):
            raise ValueError(f"{d.date()} 有收盘的 {len(quoted)} 个币里只有 {len(avail)} 个有 ≤{MCAP_MAX_AGE_DAYS} 天的市值"
                             f" —— 不在半个面板上做 ① 的市值加权")
        # T-088:cis_a1_u 传 cap=1.0 给 core_cap.capped_weights —— 不再压 40%
        w_core = capped_weights(avail, 1.0, cap)
        scores = dict(cis_at.get(d) or {})
        if mode == "fund":
            alts = [s for s in w_core if s not in FUND_PINNED]
            z = funding_z(scores, alts)
            n_scored[d] = sum(1 for s in alts if scores.get(s) is not None)
            orders[d] = pinned_tilt(w_core, z)
        else:
            z = cis_z(scores, list(w_core))
            n_scored[d] = sum(1 for s in w_core if s in scores and scores[s] is not None)
            orders[d] = tilted_weights(w_core, z, cap=cap)
        zs[d] = z
    book = run_nav(px, orders, cost_bps=COST_BPS, min_quoted_weight=MIN_QUOTED_WEIGHT, label=arm,
                   renormalize_to_quoted=False, days=days)
    rows: list[dict] = []
    for d, b in zip(days, book):
        w = b["w"]
        rows.append({
            "d": d.date().isoformat(), "arm": arm, "k": K,
            "nav": round(b["nav"], 8), "ret": round(b["ret"], 8),
            "weights": {s: round(v, 5) for s, v in sorted(w.items(), key=lambda kv: -kv[1])},
            "z": {s: round(v, 4) for s, v in sorted(zs[d].items(), key=lambda kv: -kv[1])} if d in zs else None,
            "n_scored": n_scored.get(d),
            "max_weight": round(max(w.values()), 5) if w else None,
            "rebalanced": b["traded"], "turnover": round(b["turnover"], 6),
            "n_quoted": b["n_quoted"], "n_filled": b["n_filled"],
            "barred": barred, "source": source,
            "inception": inception.date().isoformat(), "code_ref": code_ref, "computed_at": now,
        })
    return rows


def compute_replay_path(px: pd.DataFrame, mcap_prev: pd.DataFrame,
                        cis_at: Mapping[pd.Timestamp, Mapping[str, float]],
                        barred: list[str], source: str,
                        start: pd.Timestamp = REPLAY_START,
                        end: Optional[pd.Timestamp] = None) -> list[dict]:
    """T-088:cis_a1_u_replay —— 2023-01-02 起按 cap=1.0 回放;z 由调用方从 cis_rebuild_daily 重建并按时点喂入。

    用 compute_path 的参数化形式,把 arm / inception / cap / code_ref 钉到 REPLAY_ARM_U + REPLAY_START + ARM_CAP_U + CODE_REF_U。
    """
    return compute_path(px, mcap_prev, cis_at, barred, source, end=end,
                        arm=REPLAY_ARM_U, inception=start, cap=ARM_CAP_U, code_ref=CODE_REF_U)


def random_z_pct(px: pd.DataFrame, mcap_prev: pd.DataFrame,
                 cis_at: Mapping[pd.Timestamp, Mapping[str, float]],
                 n: int = 200, seed: int = 63) -> dict[str, Optional[float]]:
    """T-088 acceptance:随机倾斜 —— 把每个再平衡日的 z 横截面打乱 200 次,重跑同一段回放,
    报实测 (cis_a1_u_replay − core_u) 总收益差在随机分布里的分位。

    横截面打乱 = 同一天的 z 字典按 symbol 随机重排,不在日之间打乱时序 —— CIS 的截面信息
    (同一天谁高谁低)才是我们想测的「会挑」能力,不是时序。"""
    from src.data.accounting.nav_kernel import run_nav
    rng = np.random.default_rng(seed)
    rebal_days = sorted(cis_at.keys())
    if not rebal_days:
        return {"pct_vs_random": None, "random_p50": None, "random_p95": None, "n": 0}

    def _core_ret(orders: dict[pd.Timestamp, dict[str, float]], days: list[pd.Timestamp]) -> pd.Series:
        book = run_nav(px, orders, cost_bps=COST_BPS, min_quoted_weight=MIN_QUOTED_WEIGHT,
                       label="x", renormalize_to_quoted=False, days=days)
        return pd.Series([b["ret"] for b in book], index=pd.DatetimeIndex(days))

    days = [d for d in px.sort_index().index if REPLAY_START <= d]
    # ① cap_uncapped 底仓(全回放期)
    core_orders: dict[pd.Timestamp, dict[str, float]] = {}
    for d in days:
        if not is_rebalance_day(d, REPLAY_START):
            continue
        row_px = px.loc[d]
        mc = mcap_prev.loc[d] if d in mcap_prev.index else pd.Series(dtype=float)
        quoted = [s for s in px.columns if pd.notna(row_px.get(s))]
        avail = {s: mc.get(s) for s in quoted if pd.notna(mc.get(s))}
        if not avail:
            continue
        core_orders[d] = capped_weights(avail, 1.0, cap=1.0)        # 同 core_u
    core_ret = _core_ret(core_orders, days)
    core_total = float((1 + core_ret).prod() - 1) if len(core_ret) else 0.0

    # 实测:cis_a1_u_replay
    actual_orders = dict(core_orders)
    for d, sc in cis_at.items():
        if not sc or d not in core_orders:
            continue
        z = cis_z(sc, list(core_orders[d]))
        actual_orders[d] = tilted_weights(core_orders[d], z, cap=ARM_CAP_U)
    actual_ret = _core_ret(actual_orders, days)
    actual_total = float((1 + actual_ret).prod() - 1) if len(actual_ret) else 0.0
    actual_excess = actual_total - core_total

    # 随机:每个再平衡日,只把 z 横截面打乱(sym ↔ z),不动其他
    syms_at: dict[pd.Timestamp, list[str]] = {d: list(core_orders[d].keys()) for d in cis_at if d in core_orders}
    z_at: dict[pd.Timestamp, list[float]] = {d: [cis_z(sc, list(core_orders[d])).get(s, 0.0) for s in syms_at[d]]
                                             for d, sc in cis_at.items() if d in core_orders}

    def _shuffled_total() -> float:
        sh_orders = dict(core_orders)
        for d in cis_at:
            if d not in core_orders or not syms_at[d]:
                continue
            sh_z = dict(zip(syms_at[d], list(rng.permutation(z_at[d]))))
            sh_orders[d] = tilted_weights(core_orders[d], sh_z, cap=ARM_CAP_U)
        sh_ret = _core_ret(sh_orders, days)
        return float((1 + sh_ret).prod() - 1) - core_total

    draws = np.array([_shuffled_total() for _ in range(n)])
    return {"pct_vs_random": round(float((draws < actual_excess).mean()), 4),
            "random_p50": round(float(np.percentile(draws, 50)), 5),
            "random_p95": round(float(np.percentile(draws, 95)), 5),
            "actual_excess": round(actual_excess, 5),
            "core_total": round(core_total, 5),
            "cis_a1_u_replay_total": round(actual_total, 5),
            "n": int(n), "n_rebal_days": int(len(cis_at))}


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


async def _cis_at_rebuild(rebal_days: list[pd.Timestamp], symbols: list[str],
                          code_ref: str) -> dict[pd.Timestamp, dict[str, float]]:
    """T-088:cis_a1_u_replay 的 z 来源。 从 cis_rebuild_daily 按 code_ref 取每个再平衡日 **d−1** 那天的 score。

    T-088 acceptance:z 只用 d−1 及以前 —— 这条规则在 replay 里最容易出格(实盘实时表会在 d 收盘后写入 d),
    所以用重建表(只有 d 当天的 score,且 d+1 才落库)取 d−1 的行,把「当时可知」这条规则直接钉死。

    缺分 = 缺;跑出来的 z 用 cis_z 同款规则(同 ② 同 K)。"""
    from src.data.style.header import _read_all
    out: dict[pd.Timestamp, dict[str, float]] = {}
    if not rebal_days:
        return out
    lo = (rebal_days[0] - pd.Timedelta(days=1)).date().isoformat()
    hi = rebal_days[-1].date().isoformat()
    rows = await _read_all("cis_rebuild_daily", {
        "select": "symbol,d,score", "code_ref": f"eq.{code_ref}",
        "symbol": "in.(" + ",".join(symbols) + ")",
        "and": f"(d.gte.{lo},d.lte.{hi})", "order": "d.asc"})   # 同一个键写两次,前一个会被静默覆盖
    by_d: dict[str, dict[str, float]] = {}
    for r in rows:
        v = r.get("score")
        if v is not None:
            by_d.setdefault(str(r["d"])[:10], {})[r["symbol"]] = float(v)
    for d in rebal_days:
        out[d] = dict(by_d.get((d - pd.Timedelta(days=1)).date().isoformat(), {}))
    return out


async def _fund_at(rebal_days: list[pd.Timestamp], symbols: list[str]) -> dict[pd.Timestamp, dict[str, float]]:
    """S-640:每个再平衡日 d 的 d−7 … d−1 平均资金费率(v_funding_daily,binance_perp,按期数加权)。读不到抛异常。"""
    from src.data.style.header import _read_all
    if not rebal_days:
        return {}
    lo = (rebal_days[0] - pd.Timedelta(days=FUND_LOOKBACK_DAYS)).date().isoformat()
    hi = rebal_days[-1].date().isoformat()
    alts = [s for s in symbols if s not in FUND_PINNED]
    rows = await _read_all(FUND_VIEW, {
        "select": "symbol,d,funding_rate,n", "symbol": "in.(" + ",".join(alts) + ")",
        "and": f"(d.gte.{lo},d.lt.{hi})", "order": "d.asc"})
    return fund_means(rows, rebal_days)


async def run_once() -> dict[str, Any]:
    """重算到昨天那根已收盘日线并整条 upsert。幂等。

    T-088:同时算 cis_a1(10-06 起)+ cis_a1_u(10-12 起)+ cis_a1_u_replay(2023 起)。"""
    from src.data.cis.rebuild import CODE_REF as REBUILD_CODE_REF
    from src.data.market.panel_read import read_panel
    from src.data.signals.core_cap import _mcap_prev
    from src.data.signals.tokenization_tilt import closing_bars_final

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    if target < INCEPTION:
        return {"ok": True, "refused": True, "written": 0, "reason": f"起点 {INCEPTION.date()} 未到"}
    panel = list(panel_universe())
    start = (REPLAY_START - pd.Timedelta(days=3)).date().isoformat()
    p = await read_panel(panel, start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))   # 前推的价格不是价格

    ready, stale, why = await closing_bars_final(p.symbols, target, PRICE_SOURCE)
    if not ready:
        return why
    px.loc[target, [c for c in px.columns if c not in ready]] = float("nan")
    mc = await _mcap_prev(panel, start)

    # cis_a1(原 ① ≤ 40%):实时 cis_scores;再平衡日 10-06 起
    rebal_old = [d for d in px.index if INCEPTION <= d <= target and is_rebalance_day(d)]
    cis_old = await _cis_at(rebal_old, panel)
    rows_old = await asyncio.to_thread(compute_path, px, mc, cis_old, list(p.barred), p.source, target)

    # cis_a1_u(新 ① 不设上限):实时 cis_scores;再平衡日 10-12 起,cap=1
    rebal_u = [d for d in px.index if INCEPTION_U <= d <= target and is_rebalance_day(d, INCEPTION_U)]
    cis_u = await _cis_at(rebal_u, panel)
    rows_u = await asyncio.to_thread(compute_path, px, mc, cis_u, list(p.barred), p.source, target,
                                     arm=ARM_U, inception=INCEPTION_U, cap=ARM_CAP_U, code_ref=CODE_REF_U)

    # cis_a1_u_replay(2023 起按 cap=1.0 回放):z 用 cis_rebuild_daily(重建版才到得了 2023)
    rebal_r = [d for d in px.index if REPLAY_START <= d <= target and is_rebalance_day(d, REPLAY_START)]
    cis_r = await _cis_at_rebuild(rebal_r, panel, REBUILD_CODE_REF)
    rows_r = await asyncio.to_thread(compute_replay_path, px, mc, cis_r, list(p.barred), p.source,
                                     start=REPLAY_START, end=target)

    # S-640 fund_a1_u_replay(2023 起)+ fund_a1_u(2026-10-26 起):资金费拥挤倾斜,BTC / ETH 钉住
    fund_r = await _fund_at(rebal_r, panel)
    rows_fr = await asyncio.to_thread(compute_path, px, mc, fund_r, list(p.barred), p.source, target,
                                      arm=FUND_REPLAY_ARM, inception=REPLAY_START, cap=ARM_CAP_U,
                                      code_ref=CODE_REF_FUND, mode="fund")
    rows_f: list[dict] = []
    if target >= FUND_INCEPTION:
        rebal_f = [d for d in px.index if FUND_INCEPTION <= d <= target and is_rebalance_day(d, FUND_INCEPTION)]
        fund_f = {d: fund_r[d] for d in rebal_f if d in fund_r}
        fund_f.update(await _fund_at([d for d in rebal_f if d not in fund_f], panel))
        rows_f = await asyncio.to_thread(compute_path, px, mc, fund_f, list(p.barred), p.source, target,
                                         arm=FUND_ARM, inception=FUND_INCEPTION, cap=ARM_CAP_U,
                                         code_ref=CODE_REF_FUND, mode="fund")

    rows = rows_old + rows_u + rows_r + rows_fr + rows_f
    # S-560:回放 + 前向一起整条重算 ⇒ 写之前过 forward_lock(d ≤ 今天 − 2 的前向行不再改写)
    from src.data.accounting.forward_lock import write_locked
    w = await write_locked(TABLE, rows, key="arm", on_conflict="d,arm")
    if not w["ok"]:
        return {"ok": False, "refused": False, "written": w["written"], "reason": f"写入失败:{w['why']}"}
    arms = sorted({r["arm"] for r in rows})
    last_arms = {a: next((r for r in rows if r["d"] == target.date().isoformat() and r["arm"] == a), {}) for a in arms}
    return {"ok": True, "refused": False, "written": w["written"], "lock": w["lock"], "reason": f"重算至 {target.date()} ({len(arms)} 臂)",
            "arms": arms,
            "nav_by_arm": {a: last_arms[a].get("nav") for a in arms},
            "n_scored_last_rebal": {a: len(cis_old.get(rebal_old[-1], {})) if a == ARM else
                                    len(cis_u.get(rebal_u[-1], {})) if a == ARM_U else
                                    len(fund_r.get(rebal_r[-1], {})) if a in (FUND_ARM, FUND_REPLAY_ARM) else
                                    len(cis_r.get(rebal_r[-1], {})) for a in arms},
            "stale_in_source": stale}
