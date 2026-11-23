"""T-426:执行计划的收盘价兜底 —— CoinGecko 断供时的第二条价源。

**为什么需要(实测,不是推演)**:真钱执行计划的收盘价只认 `asset_mcap_daily`(CG 的 `market_chart`)。
Jazz 2026-11-21 停了 CG 订阅(12-01 恢复),`asset_mcap_daily` 从 **2026-11-20 起 0 行** ⇒
`tom_inputs` 拿不到收盘 ⇒ `host_plan.plan_core` 每轮都返回 `ok=False`
(最后一次 ok 是 2026-11-20 00:10Z,之后每轮同一句「2026-11-22 的收盘还没全部落库」)
⇒ X1V 既不能回场、也拿不到新的止损线。

**兜底的形状(卡 T-426 §③,逐条照做)**:
- 只在**主源缺行**的日期上补 —— 主源已有的任何一行都不覆盖、不重算;
- 补进来的价是 `ohlcv_daily`(source=`binance_hist`)的 `close` —— 库内真实成交价。
  **不补 0,不补前一日的值**;
- **默认关**:`EXEC_PRICE_FALLBACK` 不等于 `"1"` 时,`tom_inputs` 的返回与今天**逐位相同**,
  一次额外查询都不发(测试钉住);
- 接管时,每个日期的来源标在 `Series.attrs["price_source_by_date"]` 里(调用方日志能看见),
  并留一份模块级 `last_takeover()` 给日志/排查。

**开关由 Seth 决定。** 卡 T-426 expect 明写:「开关开不开由 Seth 在合并后按 ①② 的数定 —— 你不替真钱做决定」。
本模块只提供能力与「默认关」的行为,不开也不替真钱做主。

两源逐日差(365 天,BTC/ETH,2025-11-20 → 2026-11-19)与 11-01…11-19 计划一致性的实测见
`docs/research/t426_exec_price_fallback.md`。
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

#: 开关的环境变量名。值恰好等于 "1" 才开(其余一切值,包括未设置,都是关)。
FALLBACK_ENV = "EXEC_PRICE_FALLBACK"
#: 兜底价源:`ohlcv_daily` 的 source。
FALLBACK_SOURCE = "binance_hist"
#: 主价源:`asset_mcap_daily`(CoinGecko market_chart)。
PRIMARY_SOURCE = "asset_mcap_daily"

#: 最近一次接管(兜底实际生效)的记录 —— 给日志/排查用。模块级,不进返回契约。
_LAST: dict = {"enabled": False, "symbols": {}}


def fallback_enabled() -> bool:
    """`EXEC_PRICE_FALLBACK=1` 才开。默认关。"""
    return os.environ.get(FALLBACK_ENV, "") == "1"


def last_takeover() -> dict:
    """最近一次接管:{"enabled": bool, "symbols": {sym: {"fallback_days": [...], "last_primary_day": str|None}}}。"""
    return {"enabled": _LAST.get("enabled", False), "symbols": dict(_LAST.get("symbols", {}))}


async def fetch_ohlcv_closes(symbols: Iterable[str], start: str, end: str,
                             source: str = FALLBACK_SOURCE) -> dict[str, dict[str, float]]:
    """`ohlcv_daily` 的日收盘。{sym: {date: close}}。分页由 `_get_all` 负责(每页 1000 行)。"""
    from src.data.universe.world50_book import _get_all
    out: dict[str, dict[str, float]] = {}
    for sym in symbols:
        rows = await _get_all(
            f"ohlcv_daily?select=trade_date,close&source=eq.{source}&symbol=eq.{sym}"
            f"&trade_date=gte.{start}&trade_date=lte.{end}&order=trade_date")
        out[sym] = {r["trade_date"]: float(r["close"]) for r in rows if r.get("close") is not None}
    return out


def merge_missing(primary: dict[str, float], fallback: dict[str, float]
                  ) -> tuple[dict[str, float], dict[str, str]]:
    """纯函数。主源 + 兜底 → (合并后的 {date: close}, 每个日期的来源)。

    规则:主源已有的日期**一律保留主源的值**;只有主源没有、而兜底有的日期才补进去。
    补进去的值就是兜底源的真实 close(不填 0、不填前一日)。
    """
    merged = dict(primary)
    src = {d: PRIMARY_SOURCE for d in primary}
    for d, v in sorted(fallback.items()):
        if d not in merged:
            merged[d] = v
            src[d] = FALLBACK_SOURCE
    return merged, src


async def apply_fallback(px: dict[str, list[tuple[str, float]]], symbols: Iterable[str],
                         start: str, end: str) -> tuple[dict[str, list[tuple[str, float]]], dict[str, dict[str, str]]]:
    """兜底接管。返回 (新的 px, provenance)。

    - `px`:`forward_books.prices` 的返回 —— {sym: [(date, price), ...]}(主源 `asset_mcap_daily`)。
    - **接管条件**:该币主源的**最后一天 < end**(主源整体落后于 asof)。
      主源已经跟到 end 的币 —— 一个字节都不动(默认关时这也是唯一的行为)。
    - 接管后:补上主源缺、兜底有的那些天(≤ end);每个日期的来源写进 provenance。
    - 兜底源也缺的日期**不补**(宁可序列断在那里,也不猜价)。
    """
    syms = [s for s in symbols]
    need = [s for s in syms if px.get(s) and px[s][-1][0] < end]
    if not need:
        _LAST.update({"enabled": True, "symbols": {}})
        return px, {}
    fb = await fetch_ohlcv_closes(need, start, end)
    new_px, prov = dict(px), {}
    taken = {}
    for sym in need:
        prim = {d: v for d, v in px.get(sym, [])}
        merged, src = merge_missing(prim, fb.get(sym, {}))
        new_px[sym] = sorted(merged.items())
        prov[sym] = src
        fb_days = sorted(d for d, s in src.items() if s == FALLBACK_SOURCE)
        taken[sym] = {"fallback_days": fb_days,
                      "last_primary_day": max(prim) if prim else None}
    _LAST.update({"enabled": True, "symbols": taken})
    return new_px, prov
