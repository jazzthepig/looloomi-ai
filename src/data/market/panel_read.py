"""账本读价的唯一入口 —— **组装,不是新造** (S-302).

## 为什么 24 条取数路径不是因为大家懒

2026-09-05 实测,Sense 段的三层是这样的:

    写入者   3    受 `tests/test_one_ingestion_lane.py` 守卫 ✓
    读取层   0    ← 不存在
    取数者  24    各自出去打外网

**没有共享读取层,是 24 条路径存在的原因。** 每本账要价格,能调的东西只有
`httpx`,于是每本账都长出一条自己的取数路径。而这 24 条里只有 3 条会落库 ——
**另外 21 条从外网拿到价格、用完就扔,不落库,也从不与库里的价格对账。**

于是两本账可以在同一天对同一个资产用不同的价格记 NAV,而系统里
没有任何东西会发现。这正是「同一个量有两个值」长在价格层上。

## 三块料都在,只是从没被组装

    src/data/vector/market_state_writer.py::fetch_panel   单源读 ohlcv_daily + 热身期
    src/data/market/single_source.py                      NO CROSS-SOURCE RETURNS 的规则
    src/data/market/price_route.py                        哪个源合法 · 哪些标的禁入账本

三块都对、都在、都没被组合成一个账本能调的东西。Jazz 2026-09-05:
「很多东西建好闭环,然后一直没有用……然后又重新建了新的层,但旧的路径还在。」
**本模块的全部内容是组合上面三块,不新增任何取数逻辑** ——
新增的取数逻辑正是要消灭的东西。

## 三条不可让步的语义

**① 单源。** 跨源拼接的收益率是两个不同测量口径的差,不是收益。
`single_source.assert_single_source` 已经写好这条,这里只是让账本调得到。

**② 前推的价格不是价格 (S-287)。** 一个被 forward-fill 的最后收盘价,
在「不是 NaN 且为正」上与真实报价完全同形。`fill_mask` 让它可分 ——
账本据此把该标的**排除**,等权在可观测的那部分上重新归一。

**③ 禁入标的必须先出局 (S-193)。** 262 个研究标的里只有一部分可执行;
对不可执行的标的做出好看的回测,是「回测好看实盘没法用」的机制本身。

## 迁移方式:一次一本,每次删掉一条私有取数路径

不做大爆炸重构。每迁一本账,`scripts/loop_status.py` 的 **Sense 入口**
少一条 —— 那个数就是这件事的进度条,而它在 CI 里只减不增。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class Panel:
    """一次读价的全部结果。**四样东西一起给,因为少任何一样都会被误用。**

    只给 `close` 会让调用方拿前推价当报价(S-287 那次);
    只给 `close + mask` 会让调用方跨源拼接(S-273 那次);
    不给 `barred` 会让账本在不可执行的标的上出成绩(S-193 那次)。
    """
    symbols: list[str]
    days: list[str]
    #: `close[i][j]` = 第 i 天、第 j 个标的的收盘。缺失是 `None`,**不是 0.0**(I1)。
    close: list[list[Optional[float]]]
    #: `True` = 这一格是从前一天前推来的。**前推的价格不是价格。**
    filled: list[list[bool]]
    #: 这个面板来自哪一个源。跨源拼接在这里是不可能的 —— 只有一个值。
    source: str
    #: 被 price_route 判为不可执行、已从面板中剔除的标的。**显式列出,不静默丢弃。**
    barred: list[str]
    reason: str = ""

    @property
    def n_usable_today(self) -> int:
        """今天有真实(非前推)报价的标的数。**账本的等权应当在这个数上归一。**"""
        if not self.close:
            return 0
        last, mask = self.close[-1], self.filled[-1]
        return sum(1 for v, f in zip(last, mask)
                   if v is not None and v > 0 and not f)


def apply_fill_mask(series: Sequence[Optional[float]]
                    ) -> tuple[list[Optional[float]], list[bool]]:
    """前推,并**记下哪一格是前推的**。

    ⚠️ 前推本身是对的 —— 一个波动率估计需要连续序列,NaN 洞比重复价更糟。
    危险的是它**不可见**:`close[-1]` 于是握着前天的价格而没有任何东西说明。
    S-287 的原话:「priceable is not the same as priced today」。

    所以这里不取消前推,只让它留下痕迹。需要新鲜度的调用方读 mask,
    需要连续序列的不读,两边不必知道对方的存在。
    """
    out: list[Optional[float]] = []
    mask: list[bool] = []
    last: Optional[float] = None
    for v in series:
        if v is not None and v == v and v > 0:
            last, filled = v, False
        else:
            filled = last is not None
        out.append(last)
        mask.append(filled)
    return out, mask


async def read_panel(symbols: Sequence[str], *, start: str,
                     source: str = "coingecko_pro_ohlc",
                     enforce_tradeable: bool = True) -> Panel:
    """账本读价的唯一入口。

    `enforce_tradeable=True` 时先过 `price_route`,把不可执行的标的剔出去 ——
    **这一步在读之前做**,因为在读之后做就意味着我们已经为它们花了额度,
    而且很容易忘了再剔一次。

    ⚠️ 读不到**抛异常,不返回空面板**。一个空面板会被下游读成
    「今天没有行情」,而真相是「我们没读到」—— S-180 那条,
    这里绝不能重犯:账本会据此把 NAV 记成不变。
    """
    from src.data.market.single_source import (
        BARRED_RETURN_SOURCES, TRUSTED_RETURN_SOURCES)

    if source in BARRED_RETURN_SOURCES:
        raise ValueError(
            f"source='{source}' 在 BARRED_RETURN_SOURCES 里 —— "
            f"它不能用来算收益率。可用的:{TRUSTED_RETURN_SOURCES}")

    syms = list(dict.fromkeys(s.upper() for s in symbols if s))
    barred: list[str] = []
    if enforce_tradeable:
        from src.data.market.price_route import split_universe
        split = await split_universe(syms)
        # ⚠️ 键名实测是 `tradeable` / `research_only`。我第一版按记忆写了
        # `barred` / `non_tradeable`,**两个都不存在** —— 而 `.get()` 会让它
        # 静默返回空列表,也就是「没有标的被剔除」,恰好是最危险的那个答案。
        # 猜键名今天第三次(前两次 `supabase_select`、`n_covered`)。
        barred = list(split["research_only"])
        syms = list(split["tradeable"])

    if not syms:
        raise ValueError(
            f"过滤后没有可用标的(输入 {len(symbols)} 个,禁入 {len(barred)} 个)。"
            f"**这不是「今天没行情」,是这个面板没有可执行的标的** —— "
            f"账本在这种情况下应当拒绝记账,而不是记一个不变的 NAV")

    from src.data.vector.market_state_writer import fetch_panel
    raw, series_source = await fetch_panel(start, source=source)

    days = sorted({d for s in syms for d in (raw.get(s) or {})})
    if not days:
        raise ValueError(
            f"source='{source}' 在 {start} 之后对这 {len(syms)} 个标的没有任何行 —— "
            f"**读到了 0 行,不等于市场没开**。先跑 "
            f"`curl /internal/data-coverage?symbol={syms[0]}` 看这个源覆盖到哪")

    cols: list[list[Optional[float]]] = []
    masks: list[list[bool]] = []
    for s in syms:
        by_day = raw.get(s) or {}
        ser = [(by_day.get(d) or (None, None))[0] for d in days]
        filled_ser, m = apply_fill_mask(ser)
        cols.append(filled_ser)
        masks.append(m)

    close = [[cols[j][i] for j in range(len(syms))] for i in range(len(days))]
    filled = [[masks[j][i] for j in range(len(syms))] for i in range(len(days))]

    p = Panel(symbols=syms, days=days, close=close, filled=filled,
              source=str(getattr(series_source, "source", source)),
              barred=barred)
    return Panel(**{**p.__dict__, "reason": (
        f"{len(syms)} 个标的 × {len(days)} 天,单源 '{p.source}';"
        f"今天有真实报价的 {p.n_usable_today} 个"
        + (f";{len(barred)} 个因不可执行被剔除(显式列出,不静默丢弃)"
           if barred else "")
        + "。**前推的价格已标记,等权应在真实报价上归一**")})
