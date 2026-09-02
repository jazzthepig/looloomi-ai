"""往回走到每个标的自己的起点,不是走到一个全局的 2013 (S-269).

## 为什么需要这一层

S-258 建了 `/coins/{id}/ohlc/range` 的分块抓取(175 天一块、接缝重叠一天、
`interval="daily"`)。机器是对的,缺的是**往回走多深**。

Analyst 档给日线 **from 2013**(Basic 只给 2 年),所以理论上可以走 ~4,750 天。
但从 2013 对每个标的全量走是错的:**一个 2024 才上线的代币,前 11 年全是空块**,
262 个标的 × 28 块 = 7,336 次调用,其中大半在问一个不存在的问题。

正确做法是**从近往远走,走到没有数据为止**。

## 「还没上线」和「中间有个洞」是两个状态

这是这一层唯一真正的设计判断。一个空块可能是:

    ① 这个标的在这段时间还不存在        → 应该停
    ② 数据源在这段时间有缺口            → **不应该停**,停了会把它之前的历史全丢掉

第一个空块无法区分这两者。所以判据是**连续** `MAX_EMPTY_CHUNKS` 个空块才停 ——
一个孤立的洞跨不过这个门槛,而真正的起点之前是无限个空块。

代价是每个标的多花 `MAX_EMPTY_CHUNKS - 1` 次调用。取 2:多花一次,
换掉「一个缺口就把十年历史截断」这个静默错误。

## ⚠️ 不能拿 `get_cg_ohlc_range` 当回填原语(2026-09-02 活数据咬到)

首次真跑,ONDO 那一列出现:

    [CG] ohlc/range ondo-finance failed: Event loop is closed
    ONDO  reached_genesis  最早 2023-10-24 · 787 根 · 8 次调用

`data_layer.get_cg_ohlc_range` **捕获一切异常、打一条 warning、返回 `[]`**。
于是一次传输失败在调用点上和一个空窗口**完全同形** —— 它进了连续空块计数,
而那次 `reached_genesis` 因此不可信:真正的起点可能更早,
它是被一个关闭的事件循环截断的。

**那个 fail-soft 在它自己的场景里是对的**:请求路径上,一个标的的历史打嗝
不该让页面 500。错的是把它当回填原语用 ——

> **同一个函数服务两个对失败要求相反的调用者。**
> 请求路径要 fail-soft(宁可少一段也别炸),回填路径要 fail-loud
> (宁可炸也别把失败记成「这里没有数据」)。

所以本模块自带 `make_cg_fetcher()`,**它抛,不吞**。
`walk_symbol` 的 `FAILED` 裁决只有在取数器会抛的前提下才有意义。

## 深度是量出来的,不是设定的

`DeepResult.earliest_reached` 是**实际拿到数据的最早日期**,不是我们要求的
`start`。这两个在 S-260 的教训里是同一类东西:
`market_state_writer` 要求 2022-01-01、实际只拿到 343 天,而那个差额
在任何日志里都看不见,直到有人去数行数。

所以这里把「要求多深」和「实际多深」做成两个字段,并且报出每个标的的差额。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from src.data.market.cg_pro_backfill import CHUNK_DAYS

#: 连续这么多个空块才判「到起点了」。**1 会把数据缺口误判成起点。**
MAX_EMPTY_CHUNKS = 2

#: 绝对下界 —— CG Analyst 档的日线深度起点。走到这里就停,不再往前问。
FLOOR = dt.date(2013, 1, 1)

#: 单标的的调用上限。护栏,不是预期深度:2013→今天 ÷ 175 ≈ 28 块。
#: 超过它更可能是循环逻辑坏了,而不是这个标的真有那么久的历史。
MAX_CHUNKS_PER_SYMBOL = 40

REACHED_FLOOR, REACHED_GENESIS, HIT_CAP, NO_DATA, FAILED = (
    "reached_floor", "reached_genesis", "hit_cap", "no_data", "failed")


@dataclass(frozen=True)
class DeepResult:
    """一个标的往回走的结果。**要求多深与实际多深是两个字段。**"""
    symbol: str
    coin_id: str
    verdict: str
    reason: str
    requested_start: str
    earliest_reached: Optional[str] = None
    n_candles: int = 0
    n_chunks_called: int = 0
    n_empty_chunks: int = 0

    @property
    def depth_days(self) -> Optional[int]:
        if not self.earliest_reached:
            return None
        return (dt.date.today() - dt.date.fromisoformat(self.earliest_reached)).days

    @property
    def shortfall_days(self) -> Optional[int]:
        """要求的深度与实际拿到的差额。**S-260:这个差额过去在任何日志里都看不见。**"""
        if not self.earliest_reached:
            return None
        req = dt.date.fromisoformat(self.requested_start)
        got = dt.date.fromisoformat(self.earliest_reached)
        return max(0, (got - req).days)


@dataclass(frozen=True)
class WalkPlan:
    """走之前先说清楚要花多少 —— 额度是共享的,一个任务不该悄悄吃掉别人的。"""
    n_symbols: int
    max_chunks_each: int
    est_calls_max: int
    monthly_credit: int
    pct_of_monthly: float
    note: str


def plan(n_symbols: int, *, monthly_credit: int = 500_000,
         max_chunks: int = MAX_CHUNKS_PER_SYMBOL) -> WalkPlan:
    """调用预算。**上界,不是期望值** —— 大多数标的会在远早于上限处停。"""
    est = n_symbols * max_chunks
    return WalkPlan(
        n_symbols, max_chunks, est, monthly_credit,
        round(est / monthly_credit * 100, 2) if monthly_credit else 0.0,
        f"上界 {est:,} 次 = 月额度的 {est / monthly_credit:.1%}。"
        f"实际远低于此:每个标的在连续 {MAX_EMPTY_CHUNKS} 个空块后停,"
        f"而一个 2024 上线的代币大约 6 块就到底了")


def _windows_backwards(end: dt.date, *, floor: dt.date = FLOOR,
                       days: int = CHUNK_DAYS):
    """从 `end` 往回切块,最老的一块不越过 `floor`。"""
    cur_end = end
    while cur_end > floor:
        cur_start = max(floor, cur_end - dt.timedelta(days=days - 1))
        yield cur_start, cur_end
        if cur_start <= floor:
            return
        # 重叠一天:与 S-258 的正向分块同一个理由 —— 接缝处的归属取决于
        # candle 开盘时刻落在哪一侧,不重叠会静默丢一根 bar。
        cur_end = cur_start


async def walk_symbol(
    symbol: str,
    coin_id: str,
    *,
    fetch_chunk: Callable,
    end: Optional[dt.date] = None,
    floor: dt.date = FLOOR,
    max_chunks: int = MAX_CHUNKS_PER_SYMBOL,
) -> DeepResult:
    """从今天往回走到这个标的自己的起点。

    `fetch_chunk(coin_id, start, end) -> list` 由调用方注入 —— 这一层不关心
    HTTP,所以它可以被完全离线地测试。**注入不是为了优雅,是为了这层的判断
    (何时停)能在没有网络的情况下被验证。**
    """
    end = end or dt.date.today()
    all_candles: list = []
    earliest: Optional[dt.date] = None
    consecutive_empty = 0
    n_called = 0
    n_empty = 0

    for c_start, c_end in _windows_backwards(end, floor=floor):
        if n_called >= max_chunks:
            return DeepResult(
                symbol, coin_id, HIT_CAP,
                f"走了 {n_called} 块仍未到起点(上限 {max_chunks})—— 更可能是"
                f"循环逻辑坏了而不是这个标的真有这么久的历史。**不静默截断。**",
                floor.isoformat(),
                earliest.isoformat() if earliest else None,
                len(all_candles), n_called, n_empty)
        n_called += 1
        try:
            got = await fetch_chunk(coin_id, c_start, c_end)
        except Exception as e:                                 # noqa: BLE001
            return DeepResult(
                symbol, coin_id, FAILED,
                f"第 {n_called} 块({c_start}→{c_end})抓取失败:"
                f"{type(e).__name__}: {str(e)[:80]}。**已拿到的 {len(all_candles)} "
                f"根不丢**,但深度到此为止",
                floor.isoformat(),
                earliest.isoformat() if earliest else None,
                len(all_candles), n_called, n_empty)

        if not got:
            n_empty += 1
            consecutive_empty += 1
            # ⚠️ 这里是本模块唯一真正的判断。一个空块分不清「还没上线」与
            # 「数据源有洞」;连续两个才停,一个孤立的洞跨不过这个门槛。
            if consecutive_empty >= MAX_EMPTY_CHUNKS:
                if earliest is None:
                    return DeepResult(
                        symbol, coin_id, NO_DATA,
                        f"从 {end} 往回连续 {consecutive_empty} 块为空,一根都没拿到 —— "
                        f"确认 coin_id '{coin_id}' 是否正确(S-258 的映射校验)",
                        floor.isoformat(), None, 0, n_called, n_empty)
                return DeepResult(
                    symbol, coin_id, REACHED_GENESIS,
                    f"连续 {consecutive_empty} 块为空 ⇒ 到这个标的自己的起点。"
                    f"实际最早 {earliest}({(end - earliest).days} 天),"
                    f"{n_called} 次调用",
                    floor.isoformat(), earliest.isoformat(),
                    len(all_candles), n_called, n_empty)
            continue

        consecutive_empty = 0
        all_candles.extend(got)
        earliest = c_start if earliest is None else min(earliest, c_start)

    return DeepResult(
        symbol, coin_id, REACHED_FLOOR,
        f"走到档位下界 {floor}(Analyst 日线深度起点),{n_called} 次调用,"
        f"{len(all_candles)} 根",
        floor.isoformat(),
        earliest.isoformat() if earliest else None,
        len(all_candles), n_called, n_empty)


def summarise(results: Sequence[DeepResult]) -> dict:
    """面板层的深度读数。**报中位数和最差的,不只报总数。**

    一个「平均 3,000 天」的面板可能是 200 个标的有 4,000 天、62 个只有 200 天 ——
    而横截面策略的可用窗口由**最短的那批**决定,不由平均决定。
    """
    ok = [r for r in results if r.earliest_reached]
    if not ok:
        return {"n": len(results), "n_with_data": 0, "median_depth_days": None,
                "min_depth_days": None,
                "reason": "没有任何标的拿到数据 —— 先查 coin_id 映射"}
    depths = sorted(r.depth_days for r in ok)
    by_verdict: dict = {}
    for r in results:
        by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
    return {
        "n": len(results),
        "n_with_data": len(ok),
        "median_depth_days": depths[len(depths) // 2],
        "min_depth_days": depths[0],
        "p10_depth_days": depths[max(0, len(depths) // 10)],
        "total_candles": sum(r.n_candles for r in results),
        "total_calls": sum(r.n_chunks_called for r in results),
        "by_verdict": by_verdict,
        # 横截面策略的可用窗口由最短的那批决定 —— 所以 p10 比中位数更该看。
        "reason": f"{len(ok)}/{len(results)} 个标的有数据;深度中位数 "
                  f"{depths[len(depths) // 2]} 天、p10 {depths[max(0, len(depths) // 10)]} 天、"
                  f"最短 {depths[0]} 天。**横截面窗口由最短的那批决定,不由中位数决定**",
    }


def make_cg_fetcher(*, timeout: float = 30.0):
    """给 `walk_symbol` 用的取数器。**失败时抛,不返回空。**

    不复用 `data_layer.get_cg_ohlc_range`:那个函数 `except Exception → return []`,
    是为请求路径设计的 fail-soft。在回填路径上,它会把一次网络失败记成
    「这段时间没有数据」,而连续两次就会终止回溯 —— **把一个标的的真实历史
    在一次网络抖动上截断,且裁决仍然是 `reached_genesis`。**

    实测 2026-09-02:ONDO 的一次 `Event loop is closed` 就是这样进的空块计数。

    返回的取数器持有**一个** httpx client(调用方负责关闭),因为每块新建一个
    连接正是上面那次 `Event loop is closed` 的成因。
    """
    import os

    import httpx
    key = os.environ.get("COINGECKO_API_KEY", "")
    if not key:
        raise RuntimeError("COINGECKO_API_KEY 未设置(S-246:仓库不加载 .env)")
    client = httpx.AsyncClient(timeout=timeout,
                               headers={"x-cg-pro-api-key": key})

    async def fetch_chunk(coin_id: str, start: dt.date, end: dt.date) -> list:
        r = await client.get(
            f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/ohlc/range",
            params={"vs_currency": "usd",
                    "from": int(dt.datetime.combine(
                        start, dt.time(), tzinfo=dt.timezone.utc).timestamp()),
                    "to": int(dt.datetime.combine(
                        end, dt.time(), tzinfo=dt.timezone.utc).timestamp()),
                    "interval": "daily"})
        # **不吞。** 429/5xx/超时都要冒到 walk_symbol,让它判 FAILED 而不是
        # 把这一块当成「这里没有数据」。
        r.raise_for_status()
        out = r.json()
        return out if isinstance(out, list) else []

    fetch_chunk.aclose = client.aclose        # 调用方负责关
    return fetch_chunk
