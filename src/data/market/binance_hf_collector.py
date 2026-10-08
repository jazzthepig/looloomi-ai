"""Binance 小时线(含主动买量)+ 永续资金费率:两条研究序列的续接(S-509,T-065 / T-066)。

WHAT WAS WRONG. `ohlcv_hourly`(source='binance_hist',10 个币,2021 起,带 taker_buy_base)
与 `funding_history`(venue='binance_perp',同 10 个币,2024-02 起)都是 2026-08-08 一次性导入的,
**从来没有日常写入端**。两条都停在 08-07 / 08-08,而 10-08 的情景扫描(S-507 / S-508)恰好要用它们:
「低波动之后涨还是跌」靠主动买占比与资金费率来区分。不是坏了,是从来没接上(规则 5b)。

WHERE THE REQUESTS GO. 本文件**不自己出外网**:两种页都经 `data_layer`
(`get_binance_hourly_page` / `get_binance_funding_page`)—— 取数入口只减不增
(tests/test_sense_entrypoints.py,S-302)。
- 小时线:`data-api.binance.vision`(api.binance.com 在 Railway US 被地区封锁),与日线深盘同源、
  同一个 bar 约定(ts = 开盘时刻)。用途 market_data,源 binance_hist,显式 secondary(S-323n)。
- 资金费率:`fapi.binance.com`。CoinGecko Pro 只有当前费率、没有历史 —— 续接 2024-02 起的
  binance_perp 序列只能在场馆取。登记为 market_data 的显式 secondary `binance_perp`(source_policy)。

CADENCE. 每天一轮,10 个符号 × 2 次请求 —— Jazz 09-09「多资产重复调取要走付费 api」,而这两条序列
没有付费源;所以把频率压到消费方需要的最低(日频研究特征),不做日内轮询。

SHAPE. 每个符号从库里自己的最新一行起取(小时线含最新那根 —— 导入时最后一根是半根,
upsert 会用整根覆盖);未收盘的那根不写;资金费时间取整到小时(PK 含时间,毫秒尾数会造出重复行,
与 hyperliquid_collector 同一个取整)。一轮最多补 3 页小时线(125 天)/ 2 页资金费(666 天),
缺口更大就分几轮补完,`pending` 里看得见。
覆盖地板 70%:低于它整轮拒写 —— 只写一部分符号会让 max(ts) 看起来是最新的(S-190 同形)。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

_log = logging.getLogger("binance_hf")

HF_SYMBOLS: tuple[str, ...] = ("ADA", "AVAX", "BNB", "BTC", "DOGE", "ETH", "LINK", "SOL", "SUI", "XRP")
HOURLY_SOURCE = "binance_hist"
FUNDING_VENUE = "binance_perp"

_HOUR_MS = 3_600_000
PAGE = 1000
MAX_PAGES_HOURLY = 3
MAX_PAGES_FUNDING = 2
MIN_OK_FRACTION = 0.70
_CONCURRENCY = 4
_PAUSE_S = 0.25
_NO_HISTORY_LOOKBACK_MS = 30 * 24 * _HOUR_MS   # 库里一行都没有时只往回取 30 天,不做全量

#: (交易对, start_ms) → 一页原始记录。生产里是 data_layer 的两个函数;测试里换成假的。
GetPage = Callable[[str, int], Awaitable[list]]


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def hourly_rows(symbol: str, bars: list, now_ms: int) -> list[dict]:
    """Binance 1h K 线原始数组 → ohlcv_hourly 行。收盘时刻 ≥ now 的那根(还在走)不写。"""
    out: list[dict] = []
    for k in bars or []:
        try:
            open_ms, close_ms = int(k[0]), int(k[6])
            if close_ms >= now_ms:
                continue
            out.append({
                "symbol": symbol, "asset_class": "Crypto", "ts": _iso(open_ms),
                "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]),
                "volume": float(k[5]), "quote_volume": float(k[7]), "trades": int(k[8]),
                "taker_buy_base": float(k[9]),
                "source": HOURLY_SOURCE, "asset_id": symbol,
            })
        except (IndexError, TypeError, ValueError):
            continue
    return out


def funding_rows(symbol: str, items: list) -> list[dict]:
    """fundingRate 记录 → funding_history 行。时间取整到小时;费率读不出的跳过,不补 0。"""
    out: list[dict] = []
    for x in items or []:
        try:
            rate = float(x["fundingRate"])
            t = int(x["fundingTime"])
        except (KeyError, TypeError, ValueError):
            continue
        mp = x.get("markPrice")
        try:
            mark = float(mp) if mp not in (None, "") else None
        except (TypeError, ValueError):
            mark = None
        out.append({"symbol": symbol, "funding_time": _iso(t - t % _HOUR_MS), "funding_rate": rate,
                    "mark_price": mark, "venue": FUNDING_VENUE, "asset_id": symbol})
    return out


async def fetch_hourly(get_page: GetPage, symbol: str, start_ms: int, now_ms: int) -> tuple[list[dict], bool]:
    """从 start_ms(含)起翻页。返回 (行, 还有没补完的)。"""
    rows: list[dict] = []
    cur = start_ms
    for _ in range(MAX_PAGES_HOURLY):
        page = await get_page(f"{symbol}USDT", cur)
        if not page:
            return rows, False
        rows += hourly_rows(symbol, page, now_ms)
        if len(page) < PAGE:
            return rows, False
        cur = int(page[-1][0]) + _HOUR_MS
    return rows, cur < now_ms - _HOUR_MS


async def fetch_funding(get_page: GetPage, symbol: str, start_ms: int) -> tuple[list[dict], bool]:
    rows: list[dict] = []
    cur = start_ms
    for _ in range(MAX_PAGES_FUNDING):
        page = await get_page(f"{symbol}USDT", cur)
        if not page:
            return rows, False
        rows += funding_rows(symbol, page)
        if len(page) < PAGE:
            return rows, False
        cur = int(page[-1]["fundingTime"]) + 1
    return rows, True


def coverage_ok(n_ok: int, n_total: int) -> bool:
    return n_total > 0 and n_ok / n_total >= MIN_OK_FRACTION


async def _frontier(table: str, col: str, flt: str, symbol: str) -> int | None:
    """库里该符号的最新时间(毫秒);没有行 ⇒ 0;读不到 ⇒ None(调用方把它当失败,不猜)。"""
    import httpx
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_KEY", "")
    if not base or not key:
        return None
    url = f"{base}/rest/v1/{table}?select={col}&symbol=eq.{symbol}&{flt}&order={col}.desc&limit=1"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return None
        rows = r.json()
        if not rows:
            return 0
        return int(datetime.fromisoformat(str(rows[0][col]).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception as e:                                   # noqa: BLE001
        _log.warning("[BINANCE-HF] frontier %s/%s: %s", table, symbol, e)
        return None


async def _write(table: str, rows: list[dict], on_conflict: str) -> bool:
    from src.api.store import supabase_upsert_table
    for i in range(0, len(rows), 2000):
        if not await supabase_upsert_table(table, rows[i:i + 2000], on_conflict=on_conflict):
            return False
    return True


async def _one_series(kind: str, get_page: GetPage, now_ms: int) -> dict:
    sem = asyncio.Semaphore(_CONCURRENCY)
    rows: list[dict] = []
    failures: dict[str, str] = {}
    pending: list[str] = []

    async def _go(sym: str) -> None:
        async with sem:
            if kind == "hourly":
                f = await _frontier("ohlcv_hourly", "ts", f"source=eq.{HOURLY_SOURCE}", sym)
            else:
                f = await _frontier("funding_history", "funding_time", f"venue=eq.{FUNDING_VENUE}", sym)
            if f is None:
                failures[sym] = "frontier unreadable"
                return
            start = f if f else now_ms - _NO_HISTORY_LOOKBACK_MS
            try:
                if kind == "hourly":
                    got, more = await fetch_hourly(get_page, sym, start, now_ms)
                else:
                    got, more = await fetch_funding(get_page, sym, start + 1 if f else start)
            except Exception as e:                           # noqa: BLE001
                failures[sym] = f"{type(e).__name__}: {str(e)[:80]}"
                return
            rows.extend(got)
            if more:
                pending.append(sym)
            await asyncio.sleep(_PAUSE_S)

    await asyncio.gather(*[_go(s) for s in HF_SYMBOLS])
    n_ok = len(HF_SYMBOLS) - len(failures)
    out: dict[str, Any] = {"symbols_ok": n_ok, "symbols_total": len(HF_SYMBOLS),
                           "rows_built": len(rows), "pending": sorted(pending),
                           "failure_sample": dict(list(failures.items())[:5])}
    if not coverage_ok(n_ok, len(HF_SYMBOLS)):
        out.update(written=False, refused=True, rows_upserted=0,
                   reason=f"{kind}: only {n_ok}/{len(HF_SYMBOLS)} symbols readable — write refused so the gap stays visible")
        return out
    table, conflict = (("ohlcv_hourly", "symbol,ts,source") if kind == "hourly"
                       else ("funding_history", "symbol,funding_time,venue"))
    written = await _write(table, rows, conflict) if rows else True
    out.update(written=written, refused=False, rows_upserted=len(rows) if written else 0,
               reason=None if written else f"{kind}: upsert declined (APP_ROLE / Supabase log)")
    return out


async def run_once() -> dict:
    """一轮:小时线 + 资金费率。返回 {ok, refused, reason, hourly, funding}。"""
    from src.data.market.data_layer import get_binance_funding_page, get_binance_hourly_page
    from src.data.market.source_policy import MARKET_DATA, assert_purpose_source
    assert_purpose_source(MARKET_DATA, HOURLY_SOURCE, n_assets=len(HF_SYMBOLS),
                          job="binance hourly bars", secondary_ok=True)
    assert_purpose_source(MARKET_DATA, FUNDING_VENUE, n_assets=len(HF_SYMBOLS),
                          job="binance perp funding history", secondary_ok=True)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    hourly = await _one_series("hourly", lambda pair, s: get_binance_hourly_page(pair, s, PAGE), now_ms)
    funding = await _one_series("funding", lambda pair, s: get_binance_funding_page(pair, s, PAGE), now_ms)

    refused = bool(hourly.get("refused") or funding.get("refused"))
    ok = bool(hourly.get("written")) and bool(funding.get("written")) and not refused
    reasons = [r for r in (hourly.get("reason"), funding.get("reason")) if r]
    return {"ok": ok, "refused": refused, "reason": "; ".join(reasons) or None,
            "hourly": hourly, "funding": funding}
