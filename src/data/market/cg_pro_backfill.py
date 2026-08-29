"""把 CoinGecko Pro 的真 K 线落库,作为**可信价源** (S-258).

## 缺的不是能力,是写入者

`get_cg_ohlc_range()` 早就存在(`data_layer.py`),`/api/v1/ohlcv` 也在调它。
S-195 那条修复把「用错端点四个月」这件事纠正了 —— **在读取路径上**。

而实测 2026-08-27,Supabase `ohlcv_daily` 里:

    coingecko            48,853 行   2015-07-14 → 2026-08-28   ← market_chart,S-195 禁用
    coingecko_pro_ohlc          0 行                            ← 一行都没有

**能力接通了,没有任何东西把它写下来。** 这是 S-214 的形状第 N 次出现:
一个存在、可用、被读过、从未被持久化的东西。

## 为什么现在必须做

S-251 实测:两个可信加密价源**全部停写** ——

    binance_hist  最近 3 天 0/212 标的(08-09 起每天只写 BCH 一个)
    hyperliquid   最近 3 天 0/177 标的
    coingecko     还在写,但 S-195 禁它做收益序列

**加密侧没有任何可用于收益的价源在更新。** 而 M-91 早就量过 binance_hist 的
天花板是 **343 天**(9/10 标的),M-92 用 CG Pro 拿到 **1811 天 × 10 标的**,
并因此把 M-90 从 REFUTED 翻成 PARTIAL SURVIVE —— **① 是 regime-conditional,
不是结构上不可行**。那个结论就是靠深盘拿到的。

一件事解三个堵点:

    S-245 的 market_state_writer  现在只能拿 343 天(我当时选了 binance_hist)
    M-86/M-87 的 paper 面板       现在 BLOCKED,因为源过期
    signal_journal 的价源回填     83/95 行出口价被禁

## 不覆盖旧数据

`ohlcv_daily` 的唯一键是 **`(symbol, trade_date, source)`**(实测确认)。
所以 `coingecko_pro_ohlc` 与 `coingecko` **共存**,不是替换。
旧的 48,853 行留在原地并保持被禁 —— **删掉它们会让"我们曾用错端点四个月"
这件事从数据里消失**,而 the graveyard is the asset。

## 分块:Pro 的 /ohlc/range 单次上限 180 天

M-92 实测并记录:`cap=180d/request; multi-year depth via 175d chunked walk`。
这里取 175 天,留 5 天余量 —— 贴着上限走会在闰秒/时区边界上偶发丢一天,
而丢的那一天不会报错,只会让某个窗口少一根 bar。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence

log = logging.getLogger("cg_pro_backfill")

#: 落库时的源标签。**必须是这个** —— `TRUSTED_RETURN_SOURCES` 认的是它,
#: 而裸的 `coingecko` 被 `BARRED_RETURN_SOURCES` 禁用于收益序列 (S-195/S-234)。
#: 同一个 vendor 的两个端点是两种数据,标签按【端点】分不按 vendor 分。
SOURCE_TAG = "coingecko_pro_ohlc"

#: 单次请求的天数。Pro 上限 180,取 175 留余量(见模块 docstring)。
CHUNK_DAYS = 175

#: upsert 的冲突键 —— 实测 `UNIQUE (symbol, trade_date, source)`。
#: 少写 `source` 会让新行覆盖掉旧的 `coingecko` 行,而那是不可逆的数据丢失。
ON_CONFLICT = "symbol,trade_date,source"

#: 写之前的地板。一次只拿回几根 bar 通常意味着请求窗口错了或额度用尽,
#: 而把它写进去会在面板上留下一段看起来正常的稀疏区间。
MIN_CANDLES_PER_SYMBOL = 30


@dataclass(frozen=True)
class SymbolResult:
    """一个标的的回填结果 = 值 + 它的可信域。"""

    symbol: str
    coin_id: str
    ok: bool
    candles: int
    first_day: Optional[str] = None
    last_day: Optional[str] = None
    reason: str = ""

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"symbol": self.symbol, "coin_id": self.coin_id,
                               "candles": self.candles}
        if self.first_day:
            out["coverage"] = f"{self.first_day}..{self.last_day}"
        if not self.ok:
            out["skipped_because"] = self.reason or "unknown"
        return out


@dataclass(frozen=True)
class BackfillResult:
    ok: bool
    rows_written: int
    per_symbol: tuple[SymbolResult, ...] = ()
    reason: str = ""

    def as_payload(self) -> dict[str, Any]:
        wrote = [s for s in self.per_symbol if s.ok]
        skipped = [s for s in self.per_symbol if not s.ok]
        out: dict[str, Any] = {
            "status": "ok" if self.ok else "degraded",
            "source": SOURCE_TAG,
            "rows_written": self.rows_written,
            "symbols_written": len(wrote),
            "symbols_skipped": len(skipped),
            "detail": [s.as_payload() for s in self.per_symbol],
        }
        if not self.ok:
            out["reason"] = self.reason or "unknown"
        return out


def chunk_windows(start: date, end: date, *, days: int = CHUNK_DAYS
                  ) -> list[tuple[int, int]]:
    """把 [start, end] 切成不超过 `days` 天的 unix 时间戳窗口。

    **闭区间,相邻窗口重叠一天。** 重叠是有意的:`/ohlc/range` 的边界归属
    取决于 candle 的开盘时刻落在哪一侧,不重叠会在每个接缝处丢一根 bar ——
    而丢的那根不会报错,只会让某个 60 日窗口变成 59 根。
    upsert 的唯一键吃掉重复,所以重叠的代价是零。
    """
    if end < start:
        return []
    out: list[tuple[int, int]] = []
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=days), end)
        out.append((
            int(datetime.combine(cur, datetime.min.time(), timezone.utc).timestamp()),
            int(datetime.combine(stop, datetime.max.time(), timezone.utc).timestamp()),
        ))
        if stop >= end:
            break
        cur = stop            # 重叠一天,见 docstring
    return out


def to_rows(symbol: str, candles: Iterable[dict], *,
            asset_class: Optional[str] = None) -> list[dict]:
    """把 `get_cg_ohlc_range` 的输出变成 `ohlcv_daily` 的行。

    **日期来自 candle,不来自写入时钟** —— `get_cg_ohlc_range` 的注释里写着
    「The DATE COMES FROM THE CANDLE. Never from the write clock — that is the
    mistake this whole endpoint switch exists to end.」这里不再做一次日期推导,
    直接用它给的 `trade_date`。

    `volume` 留空:`/ohlc/range` 不返回成交量,而**从别的端点拼一个成交量
    进来就是跨源** (S-230)。缺的量是 NULL,不是 0。
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for c in candles:
        d = str(c.get("trade_date") or "")[:10]
        if not d or d in seen:            # 窗口重叠会产生重复,这里去重
            continue
        if c.get("close") is None:
            continue
        seen.add(d)
        row = {
            "symbol": symbol,
            "trade_date": d,
            "open": c.get("open"),
            "high": c.get("high"),
            "low": c.get("low"),
            "close": c.get("close"),
            "volume": None,               # /ohlc/range 不给量;拼别处的量 = 跨源
            "source": SOURCE_TAG,
        }
        if asset_class:
            row["asset_class"] = asset_class
        rows.append(row)
    rows.sort(key=lambda r: r["trade_date"])
    return rows


async def backfill_symbol(symbol: str, coin_id: str, *, start: date, end: date,
                          asset_class: Optional[str] = None,
                          dry_run: bool = False) -> SymbolResult:
    """回填一个标的。**地板在写之前** (S-220)。"""
    from src.data.market.data_layer import get_cg_ohlc_range

    all_candles: list[dict] = []
    for frm, to in chunk_windows(start, end):
        got = await get_cg_ohlc_range(coin_id, frm, to, interval="daily")
        if got:
            all_candles.extend(got)

    rows = to_rows(symbol, all_candles, asset_class=asset_class)
    if len(rows) < MIN_CANDLES_PER_SYMBOL:
        # 少量 bar 通常是窗口错了或额度用尽。写进去会在面板上留下一段
        # 看起来正常的稀疏区间,而稀疏和"这段时间没交易"在下游长得一样。
        return SymbolResult(symbol, coin_id, False, len(rows),
                            reason=f"只取到 {len(rows)} 根 bar < {MIN_CANDLES_PER_SYMBOL},"
                                   f"不写 —— 稀疏区间在下游与'没有交易'不可分辨")

    if dry_run:
        return SymbolResult(symbol, coin_id, True, len(rows),
                            rows[0]["trade_date"], rows[-1]["trade_date"],
                            reason="dry_run — 未写入")

    from src.api.store import supabase_upsert_table
    ok = await supabase_upsert_table("ohlcv_daily", rows, on_conflict=ON_CONFLICT)
    if not ok:
        return SymbolResult(symbol, coin_id, False, len(rows),
                            rows[0]["trade_date"], rows[-1]["trade_date"],
                            reason="upsert 返回 False(角色门、凭证或传输)")
    return SymbolResult(symbol, coin_id, True, len(rows),
                        rows[0]["trade_date"], rows[-1]["trade_date"])


async def backfill(pairs: Sequence[tuple[str, str]], *, start: date, end: date,
                   asset_class: Optional[str] = None,
                   dry_run: bool = False) -> BackfillResult:
    """`pairs` = [(symbol, coin_id), ...]。逐个回填,一个失败不拖垮其余。

    **不做 symbol→coin_id 的猜测。** 猜错一个映射会把另一个币的价格写进这个
    标的的历史,而那条曲线看起来完全正常 —— 调用方必须显式给出映射。
    """
    if not pairs:
        return BackfillResult(False, 0, (), "没有给任何 (symbol, coin_id) —— 不猜映射")

    results: list[SymbolResult] = []
    total = 0
    for symbol, coin_id in pairs:
        try:
            r = await backfill_symbol(symbol, coin_id, start=start, end=end,
                                      asset_class=asset_class, dry_run=dry_run)
        except Exception as e:                                    # noqa: BLE001
            r = SymbolResult(symbol, coin_id, False, 0,
                             reason=f"{type(e).__name__}: {str(e)[:120]}")
        results.append(r)
        if r.ok and not dry_run:
            total += r.candles
        log.info("[CGPRO] %s(%s) → %s", symbol, coin_id, r.as_payload())

    wrote = [r for r in results if r.ok]
    return BackfillResult(
        ok=bool(wrote), rows_written=total, per_symbol=tuple(results),
        reason="" if wrote else "所有标的都没能回填 —— 逐个原因见 detail")


__all__ = ["SOURCE_TAG", "CHUNK_DAYS", "ON_CONFLICT", "MIN_CANDLES_PER_SYMBOL",
           "SymbolResult", "BackfillResult", "chunk_windows", "to_rows",
           "backfill_symbol", "backfill"]
