"""① 持有市场 —— 市值加权、单币 ≤ 40% 的核心持仓前向记录(Jazz 2026-10-03:「use 1」,S-472/S-473)。

## 为什么有这本账

S-472 把 ① 的加权写成一个连续参数:w ∝ 市值^α。同一 24 名面板、2023 年起,α = 0(等权,原 `beta_core` 的口径)
+144%、回撤 −76%;α = 1 +241%、回撤 −60%。α < 1 的部分是一个风格倾斜(重仓二线 L1 / 山寨),按层级它属于 ②,
要自己挣到位置。Jazz 定 ① 用 α = 1。原 `beta_core`(等权 + 波动率目标)不删,在登记表里改作 ② 的候选。

## 预注册(改任何一项 = 新起点,旧记录留档)

    主臂   cap_a1    w ∝ 市值(d−1),单币上限 40%(Jazz 09-29),超出部分按市值比例分给其余   ← 这是 ①
    对照   cap_a05   w ∝ √市值,同上限          ┐ 同一内核、同一节奏下把 α 这条轴的另外两点也记着,
    对照   ew_a0     等权                       ┘ 让「定 α = 1」这个决定本身有前向证据,而不是只有回放
    面板    causal_positioning.DEFAULT_UNIVERSE(24 名);只持现货、无杠杆、无择时(③ 归 L3,不在 ① 里)
    价格    binance_hist(与 β+ 同源;S-468 起前推假价已移出该源);市值 asset_mcap_daily(CoinGecko market_chart)
    节奏    起点收盘建仓;此后每周一(UTC)收盘再平衡到目标,其余日子权重随价格漂移(市值加权本来就自带漂移)
    成本    换手 × 10 bps
    起点    2026-10-02 收盘(决定在 10-03 做出,用的数据到 10-02;第一天收益 10-03 才是真正的前向)

## 2026-10-12 改版(Jazz「把单币上限 40% 解除」,S-556)—— 新起点,旧臂留档

    主臂   cap_a1_u  w ∝ 市值(d−1),**不设单币上限**                    ← 10-12 起这是 ①
    留档   cap_a1    原 ①(单币 ≤ 40%),照旧每天记 —— 10-02 → 10-12 的 ① 就是它
    起点    cap_a1_u 自 2026-10-12 收盘(决定在 10-12 15:55 UTC 做出,早于当天收盘;第一天前向收益是 10-13)
    其余    面板 / 价源 / 节奏 / 成本 / 覆盖率门槛与上面相同
    ① 的整条 NAV(registry.core_nav)按日期拼接:回放(≤ 10-02)→ cap_a1(10-02, 10-12] → cap_a1_u(> 10-12)。
    ③ / 组合层 / ② CIS 倾斜仍以旧 ① 为底,直到各自按新 ① 另起新臂(T-087 / T-088)—— 不在原臂上改规则。

## 不存状态 —— 每次从起点重算(同 S-427)

## 判活判据(规则 5b ②)

    select arm, max(d), count(*) from core_cap_daily group by 1;   -- UTC 08:00 后 max(d) 应 = 昨天
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pandas as pd

TABLE = "core_cap_daily"
WRITES_TABLES = (TABLE,)
ARMS = {"cap_a1": 1.0, "cap_a05": 0.5, "ew_a0": 0.0, "cap_a1_u": 1.0}
#: 每臂的单币上限:cap_a1_u = 不设上限(S-556);其余照 S-473 原规则
SINGLE_ASSET_CAP = 0.40
ARM_CAP = {"cap_a1": SINGLE_ASSET_CAP, "cap_a05": SINGLE_ASSET_CAP, "ew_a0": SINGLE_ASSET_CAP, "cap_a1_u": 1.0}
CORE_ARM = "cap_a1_u"
LEGACY_CORE_ARM = "cap_a1"
#: ① 换成 cap_a1_u 的那一天(收盘);在这之前 ① = LEGACY_CORE_ARM
COST_BPS = 10.0
INCEPTION = pd.Timestamp("2026-10-02")
CORE_SINCE = pd.Timestamp("2026-10-12")
ARM_INCEPTION = {"cap_a1_u": CORE_SINCE}
PRICE_SOURCE = "binance_hist"
MIN_QUOTED_WEIGHT = 0.90
#: 再平衡日:有收盘的币里至少这么多也有(≤ 3 天前的)市值,否则拒绝 —— 不在半个面板上算「市值加权」
MIN_MCAP_COVERAGE = 0.90
MCAP_MAX_AGE_DAYS = 3
CODE_REF = "S-473 core_cap v1"
ARM_CODE_REF = {"cap_a1_u": "S-556 core_cap v2 (no single-name cap)"}


def panel_universe() -> tuple[str, ...]:
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
    return tuple(DEFAULT_UNIVERSE)


def capped_weights(mcap: Mapping[str, float], alpha: float, cap: float = SINGLE_ASSET_CAP) -> dict[str, float]:
    """w ∝ mcap^alpha,单币 ≤ cap;超出部分按未触顶者的原始比例重分,迭代到没有人超过上限。
    市值缺失或非正的标的不进来(不猜)。名单太短、cap 不可行(n·cap < 1)时报错而不是悄悄破上限。"""
    raw = {s: float(v) ** alpha for s, v in mcap.items() if v is not None and v == v and float(v) > 0}
    if not raw:
        return {}
    if len(raw) * cap < 1 - 1e-12:
        raise ValueError(f"只有 {len(raw)} 个标的有市值,单币上限 {cap:.0%} 不可行")
    w = {s: v / sum(raw.values()) for s, v in raw.items()}
    fixed: dict[str, float] = {}
    for _ in range(len(w) + 1):
        over = {s for s, v in w.items() if s not in fixed and v > cap + 1e-12}
        if not over:
            break
        for s in over:
            fixed[s] = cap
        free = {s: raw[s] for s in raw if s not in fixed}
        left = 1.0 - sum(fixed.values())
        tot = sum(free.values())
        w = {**fixed, **{s: left * v / tot for s, v in free.items()}}
    return w


def is_rebalance_day(d: pd.Timestamp, inception: pd.Timestamp = INCEPTION) -> bool:
    return d == inception or d.weekday() == 0


def compute_path(px: pd.DataFrame, mcap_prev: pd.DataFrame, barred: list[str], source: str,
                 end: Optional[pd.Timestamp] = None) -> list[dict]:
    """纯函数。`px`:行 = 日期、列 = 币,NaN = 当天没有真实收盘。`mcap_prev`:行 = 日期 d、值 = d−1 的市值。
    再平衡日的目标只分给当天有真实收盘且有 d−1 市值的币。"""
    from src.data.accounting.nav_kernel import run_nav

    px = px.sort_index()
    days = [d for d in px.index if d >= INCEPTION and (end is None or d <= end)]
    if not days or days[0] != INCEPTION:
        raise ValueError(f"起点 {INCEPTION.date()} 那天没有面板行 —— 不从别的日子悄悄开始")
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for arm, alpha in ARMS.items():
        inc = ARM_INCEPTION.get(arm, INCEPTION)
        arm_days = [d for d in days if d >= inc]
        if not arm_days:
            continue                                      # 起点还没到的臂(cap_a1_u 在 10-12 收盘之前)
        orders: dict[pd.Timestamp, dict[str, float]] = {}
        for d in arm_days:
            if not is_rebalance_day(d, inc):
                continue
            row_px = px.loc[d]
            mc = mcap_prev.loc[d] if d in mcap_prev.index else pd.Series(dtype=float)
            quoted = [s for s in px.columns if pd.notna(row_px.get(s))]
            avail = {s: mc.get(s) for s in quoted if pd.notna(mc.get(s))}
            if not quoted or len(avail) < MIN_MCAP_COVERAGE * len(quoted):
                raise ValueError(f"{d.date()} 有收盘的 {len(quoted)} 个币里只有 {len(avail)} 个有 ≤{MCAP_MAX_AGE_DAYS} 天的市值"
                                 f" —— 不在半个面板上做市值加权")
            orders[d] = capped_weights(avail, alpha, ARM_CAP[arm])
        book = run_nav(px, orders, cost_bps=COST_BPS, min_quoted_weight=MIN_QUOTED_WEIGHT, label=arm,
                       renormalize_to_quoted=False, days=arm_days)
        for d, b in zip(arm_days, book):
            w = b["w"]
            rows.append({
                "d": d.date().isoformat(), "arm": arm, "alpha": alpha,
                "nav": round(b["nav"], 8), "ret": round(b["ret"], 8),
                "weights": {s: round(v, 5) for s, v in sorted(w.items(), key=lambda kv: -kv[1])},
                "max_weight": round(max(w.values()), 5) if w else None,
                "rebalanced": b["traded"], "turnover": round(b["turnover"], 6),
                "n_quoted": b["n_quoted"], "n_filled": b["n_filled"],
                "barred": barred, "source": source,
                "inception": inc.date().isoformat(), "code_ref": ARM_CODE_REF.get(arm, CODE_REF), "computed_at": now,
            })
    return rows


async def _mcap_prev(symbols: list[str], start: str) -> pd.DataFrame:
    """asset_mcap_daily → 行 = d、值 = d−1 的市值(前一天收盘时的市值,下单那天已知)。读不到抛异常。"""
    from src.data.style.header import _read_all
    rows = await _read_all("asset_mcap_daily", {"select": "symbol,d,mcap", "order": "d.asc",
                                                "symbol": "in.(" + ",".join(symbols) + ")",
                                                "d": f"gte.{start}"})
    if not rows:
        raise RuntimeError("asset_mcap_daily 在起点附近一行都读不到 —— 不按等权顶替")
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    mc = df.pivot_table(index="d", columns="symbol", values="mcap")
    mc = mc.reindex(pd.date_range(mc.index.min(), mc.index.max() + pd.Timedelta(days=1), freq="D"))
    # 市值写入端(风格表头循环)偶尔一轮失败;权重用的市值最多沿用 3 天前的,再旧就当缺(S-474)
    return mc.ffill(limit=MCAP_MAX_AGE_DAYS - 1).shift(1)


async def run_once() -> dict[str, Any]:
    """重算到昨天那根已收盘日线并整条 upsert。幂等。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.panel_read import read_panel
    from src.data.signals.tokenization_tilt import closing_bars_final

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    if target < INCEPTION:
        return {"ok": True, "refused": True, "written": 0, "reason": "起点未到"}
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

    rows = await asyncio.to_thread(compute_path, px, mc, list(p.barred), p.source, target)
    res = await supabase_upsert_table(TABLE, rows, on_conflict="d,arm")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    last = {r["arm"]: r["nav"] for r in rows if r["d"] == target.date().isoformat()}
    top = next((r["weights"] for r in rows if r["d"] == target.date().isoformat() and r["arm"] == CORE_ARM), {})
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"重算至 {target.date()}",
            "nav": last, "core_top": dict(list(top.items())[:3]), "barred": list(p.barred),
            "stale_in_source": stale}
