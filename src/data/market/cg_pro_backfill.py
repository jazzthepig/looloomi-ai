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
    #: 写到哪了 —— local(研究面)还是 supabase(系统记录)。
    #: 一个不说明目的地的回填结果,读者无从判断它有没有动生产库。
    dest: str = "local"

    def as_payload(self) -> dict[str, Any]:
        wrote = [s for s in self.per_symbol if s.ok]
        skipped = [s for s in self.per_symbol if not s.ok]
        out: dict[str, Any] = {
            "status": "ok" if self.ok else "degraded",
            "source": SOURCE_TAG,
            "dest": self.dest,
            "rows_written": self.rows_written,
            "symbols_written": len(wrote),
            "symbols_skipped": len(skipped),
            "detail": [s.as_payload() for s in self.per_symbol],
        }
        if not self.ok:
            out["reason"] = self.reason or "unknown"
        return out



def _why_all_failed(results) -> str:
    """全军覆没时,**把最常见的那条理由带出来**,而不是指向 detail (S-307)。

    理由按出现次数排 —— 57 个标的全挂时,通常是同一个原因,
    而知道那个原因是「35 个没有对照行」还是「额度用尽」,决定了修法完全不同。
    """
    from collections import Counter
    c = Counter((r.reason or "unknown").split("——")[0].strip()[:70]
                for r in results)
    top = c.most_common(3)
    head = f"{len(results)} 个标的全部未写入。"
    body = " · ".join(f"{n}× {why}" for why, n in top)
    more = f"(共 {len(c)} 种原因)" if len(c) > 3 else ""
    return head + body + more


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


#: coin_id 校验:同一天、同一 vendor 的两个端点,收盘价该有多接近。
#:
#: `/ohlc/range` 与 `market_chart/range` 都来自 CoinGecko,但一个是真 K 线、
#: 一个是采样点(S-195),所以**不会完全相等**。允许 5% 是给采样时刻差异的余量;
#: 一个错的 coin_id(把 BCH 写进 BTC)会差几十倍,一眼可辨。
MAPPING_TOLERANCE_PCT = 5.0


@dataclass(frozen=True)
class MappingCheck:
    """symbol→coin_id 的实证校验结果。"""

    symbol: str
    coin_id: str
    ok: bool
    pro_close: Optional[float] = None
    existing_close: Optional[float] = None
    gap_pct: Optional[float] = None
    reason: str = ""

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"symbol": self.symbol, "coin_id": self.coin_id,
                               "verified": self.ok}
        if self.gap_pct is not None:
            out["gap_pct"] = round(self.gap_pct, 2)
            out["pro"] = self.pro_close
            out["existing"] = self.existing_close
        if not self.ok:
            out["reason"] = self.reason
        return out


def check_mapping(symbol: str, coin_id: str, *, pro_close: Optional[float],
                  existing_close: Optional[float],
                  tolerance_pct: float = MAPPING_TOLERANCE_PCT) -> MappingCheck:
    """把「不猜映射」从一条政策变成一个**检查**。

    ## 为什么这条比它看起来重要

    一个错的 `symbol → coin_id` 会把**另一个币的整段价格历史**写进这个标的,
    而**那条曲线看起来完全正常** —— 没有任何下游检查能发现 BTC 的历史里
    混进了 BCH 的价格。它不会让任何断言变红,只会让每一个用到它的结论变错。

    校验方法:同一天,拿 `/ohlc/range` 的收盘价对 `ohlcv_daily` 里既有的
    `coingecko`(market_chart)收盘价。**同一个 vendor 的两个端点**,
    价格必须接近 —— 不完全相等(一个是真 K 线一个是采样点,S-195),
    但差 5% 以内。coin_id 错了会差几十倍。

    ⚠️ 这是**唯一**能用现有数据做的映射校验:库里没有 CG coin_id 的映射表,
    `asset_aliases` 存的是 binance venue symbol。所以校验只能是实证的。

    三值:verified / mismatch / not_checkable(没有对照行 —— **不是通过**)。
    """
    if pro_close is None:
        return MappingCheck(symbol, coin_id, False,
                            reason="Pro 端点没返回这一天的收盘 —— 无法校验映射")
    if existing_close is None or existing_close == 0:
        # 没有对照不是通过。S-163:not-checked 必须说出来。
        return MappingCheck(symbol, coin_id, False, pro_close, None, None,
                            reason="库里没有同日的 coingecko 对照行 —— "
                                   "【未校验】,不是通过。人工确认 coin_id 后再写。")
    gap = abs(pro_close / existing_close - 1.0) * 100.0
    if gap > tolerance_pct:
        return MappingCheck(symbol, coin_id, False, pro_close, existing_close, gap,
                            reason=f"同日收盘差 {gap:.1f}% > {tolerance_pct}% —— "
                                   f"同一 vendor 两个端点不该差这么多,"
                                   f"极可能 coin_id 指向了另一个币。不写。")
    return MappingCheck(symbol, coin_id, True, pro_close, existing_close, gap)


#: 本地研究面的 sqlite。**复用 `src/research/data/ohlcv_local.py` 的那一个,
#: 不建第三个 store** —— 今天已经因为「两个展平器 / 四个 regime 规范化实现」
#: 被守卫抓过两次 (S-249)。表结构相同(`ohlcv_daily`,含 `source` 列),
#: 所以 `load_local_panel(source="coingecko_pro_ohlc")` 直接可用。
LOCAL_DB = "/tmp/cometcloud_data/ohlcv.db"


def write_local(rows: Sequence[dict], *, db_path: str = LOCAL_DB) -> int:
    """把行写进**本地** sqlite。返回写入行数。

    ## 为什么先本地 (S-261)

    Jazz 2026-08-30:「supabase 我们是免费版的,能不增加用量就不增加。」

    实测当天:库 **253 MB / 500 MB = 50.7%**。
    而这次回填按 `ohlcv_daily` 的密度(90.2MB / 533,989 行 ≈ 177 B/行)
    只有 **约 3.2 MB**,占库 0.6% —— **担心的方向其实反了**:
    真正压着额度的是 `ohlcv_hourly` **85.6 MB(全库 34%)**,
    而它被 DATA-EXPANSION-HOLD 明令「不得用于统计结论」、
    `src/` 里没有任何代码读它、且已陈旧 22 天。

    但「先本地」这条本身是对的,而且理由比省额度更硬:

    **研究面和系统记录是两种东西。** 研究要反复重算、试错、丢弃;
    系统记录要稳定、可审计、被生产读。把研究中间产物写进 Supabase,
    等于让每一次试错都变成一条永久记录 —— 而**删掉它们又会破坏
    「the graveyard is the asset」**。两个都不想要,所以分开放。

    Supabase 只收**生产真正会读的东西**,而且是显式的一步。
    """
    import sqlite3
    from datetime import datetime as _dt
    from pathlib import Path as _P

    if not rows:
        return 0
    _P(db_path).parent.mkdir(parents=True, exist_ok=True)
    now_iso = _dt.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        # 表可能还不存在(全新机器)。字段与 `ohlcv_local.py` 读的那套对齐。
        conn.execute("""
            create table if not exists ohlcv_daily (
                symbol text, asset_class text, source text, trade_date text,
                open real, high real, low real, close real, volume real,
                fetched_at text,
                primary key (symbol, trade_date, source)
            )""")
        n = 0
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO ohlcv_daily "
                "(symbol, asset_class, source, trade_date, open, high, low, "
                " close, volume, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (r["symbol"], r.get("asset_class"), r["source"], r["trade_date"],
                 r.get("open"), r.get("high"), r.get("low"), r.get("close"),
                 r.get("volume"), now_iso))
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


async def _verify_mapping(symbol: str, coin_id: str, row: dict) -> MappingCheck:
    """拿库里同日的 `coingecko` 收盘做对照。读不到 → 未校验(不是通过)。"""
    try:
        from src.api.store import _supabase_request_with_retry
        import os as _os
        base = (_os.getenv("SUPABASE_URL") or "").rstrip("/")
        key = _os.getenv("SUPABASE_KEY") or _os.getenv("SUPABASE_SERVICE_KEY") or ""
        if not base or not key:
            return check_mapping(symbol, coin_id, pro_close=row.get("close"),
                                 existing_close=None)
        resp = await _supabase_request_with_retry(
            "GET", f"{base}/rest/v1/ohlcv_daily",
            params={"select": "close", "symbol": f"eq.{symbol}",
                    "trade_date": f"eq.{row['trade_date']}",
                    "source": "eq.coingecko", "limit": "1"},
            headers={"apikey": key, "Authorization": f"Bearer {key}"})
        existing = None
        if resp is not None and resp.status_code < 300:
            js = resp.json()
            if isinstance(js, list) and js:
                existing = js[0].get("close")
        return check_mapping(symbol, coin_id, pro_close=row.get("close"),
                             existing_close=existing)
    except Exception as e:                                        # noqa: BLE001
        return MappingCheck(symbol, coin_id, False,
                            reason=f"校验查询失败({type(e).__name__})—— 未校验,不是通过")


async def backfill_symbol(symbol: str, coin_id: str, *, start: date, end: date,
                          asset_class: Optional[str] = None,
                          dest: str = "local",
                          min_candles: Optional[int] = None,
                          vendor_paired: bool = False,
                          dry_run: bool = False) -> SymbolResult:
    """回填一个标的。**地板在写之前** (S-220)。

    `dest`:`"local"`(默认,写本地 sqlite)| `"supabase"`(显式,才进生产库)。
    **默认是 local** —— Supabase 是免费版,而研究面不该占系统记录的额度 (S-261)。
    """
    from src.data.market.data_layer import get_cg_ohlc_range

    all_candles: list[dict] = []
    for frm, to in chunk_windows(start, end):
        got = await get_cg_ohlc_range(coin_id, frm, to, interval="daily")
        if got:
            all_candles.extend(got)

    rows = to_rows(symbol, all_candles, asset_class=asset_class)

    # ── 映射校验在写之前 ────────────────────────────────────────────────────
    # 一个错的 coin_id 会把另一个币的整段历史写进这个标的,而曲线看起来完全正常。
    # 拿最后一根 bar 对库里同日的 coingecko 收盘 —— 同 vendor 两端点,必须接近。
    if rows:
        chk = await _verify_mapping(symbol, coin_id, rows[-1])
        # ⚠️ **不可校验 ≠ 校验不通过** (S-307)。
        #
        # 2026-09-05 实测:57 个映射里 **35 个库里没有 coingecko 对照行**,
        # 于是全部判「未校验,不是通过」而不写。而对照行只能来自那 25 个
        # coingecko 标的 —— **面板结构上永远扩不出已有的范围**。
        # 一个防止写错的守卫,变成了一个禁止增长的守卫。
        #
        # 校验存在的目的是抓**我们猜出来的**映射。而 vendor 成对给出的
        # (symbol, id)——`/coins/list` 里唯一的、或 trending 接口一并返回的——
        # **不是猜**。对它们,校验能做则做、不能做就记为未校验并放行;
        # 只有 `mcap_tiebreak`(我们自己按市值裁决的)必须先过校验。
        _not_checkable = "库里没有同日" in (chk.reason or "")
        if not chk.ok and not (_not_checkable and vendor_paired):
            return SymbolResult(symbol, coin_id, False, len(rows),
                                rows[0]["trade_date"], rows[-1]["trade_date"],
                                reason=f"映射未通过校验:{chk.reason}")

    # ⚠️ **地板要相对于请求的窗口,不能是绝对值** (S-306)。
    # 2026-09-05:`_cg_panel_loop` 用 7 天窗口做增量刷新,每个标的正常拿回
    # ~7 根 bar,而这里的绝对地板是 30 —— **57 个标的全部被拒,写入 0 行**,
    # 而每一次拒绝的理由都是对的。
    #
    # 地板本身没错,它防的是「窗口错了或额度用尽」。错的是它**假设调用方
    # 总是在做长窗口回填**。同一个数字在两种用途下含义相反:
    # 回填时 7 根 = 出错了;增量刷新时 7 根 = 完全正常。
    #
    # 所以判据改成「拿回的 bar 数 vs 这个窗口应该有的天数」,
    # 调用方也可以显式传 `min_candles` 说明自己的用途。
    _expected = max(1, (end - start).days)
    _floor = (min_candles if min_candles is not None
              else min(MIN_CANDLES_PER_SYMBOL, max(5, int(_expected * 0.7))))
    if len(rows) < _floor:
        # 少量 bar 通常是窗口错了或额度用尽。写进去会在面板上留下一段
        # 看起来正常的稀疏区间,而稀疏和"这段时间没交易"在下游长得一样。
        return SymbolResult(symbol, coin_id, False, len(rows),
                            reason=f"只取到 {len(rows)} 根 bar < 地板 {_floor}"
                                   f"(窗口 {_expected} 天),"
                                   f"不写 —— 稀疏区间在下游与'没有交易'不可分辨")

    if dry_run:
        return SymbolResult(symbol, coin_id, True, len(rows),
                            rows[0]["trade_date"], rows[-1]["trade_date"],
                            reason=f"dry_run(dest={dest})— 未写入")

    if dest == "local":
        n = write_local(rows)
        return SymbolResult(symbol, coin_id, True, n,
                            rows[0]["trade_date"], rows[-1]["trade_date"])

    if dest != "supabase":
        return SymbolResult(symbol, coin_id, False, len(rows),
                            reason=f"未知 dest '{dest}' —— 只有 local / supabase,"
                                   f"不猜")

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
                   dest: str = "local",
                   min_candles: Optional[int] = None,
                   vendor_paired: Optional[set] = None,
                   dry_run: bool = False) -> BackfillResult:
    """`pairs` = [(symbol, coin_id), ...]。逐个回填,一个失败不拖垮其余。

    **不做 symbol→coin_id 的猜测。** 猜错一个映射会把另一个币的价格写进这个
    标的的历史,而那条曲线看起来完全正常 —— 调用方必须显式给出映射。
    """
    if not pairs:
        return BackfillResult(False, 0, (), "没有给任何 (symbol, coin_id) —— 不猜映射",
                              dest=dest)

    results: list[SymbolResult] = []
    total = 0
    for symbol, coin_id in pairs:
        try:
            r = await backfill_symbol(symbol, coin_id, start=start, end=end,
                                      asset_class=asset_class, dest=dest,
                                      min_candles=min_candles,
                                      vendor_paired=(symbol in (vendor_paired or set())),
                                      dry_run=dry_run)
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
        # ⚠️ **「逐个原因见 detail」是一个指针,不是一个原因** (S-307)。
        # 心跳只带 `reason`,`detail` 留在返回值里没人看得到,于是面板上是
        # 一句「都失败了,原因在别处」—— 排查成本和没有原因一样。
        # 把最常见的那条理由带出来,并说明还有几种别的。
        reason="" if wrote else _why_all_failed(results),
        dest=dest)


__all__ = ["SOURCE_TAG", "CHUNK_DAYS", "ON_CONFLICT", "MIN_CANDLES_PER_SYMBOL",
           "MAPPING_TOLERANCE_PCT", "MappingCheck", "check_mapping",
           "LOCAL_DB", "write_local",
           "SymbolResult", "BackfillResult", "chunk_windows", "to_rows",
           "backfill_symbol", "backfill"]
