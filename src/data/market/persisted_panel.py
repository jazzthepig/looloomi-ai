"""账本读的面板 = 我们自己落过库的那一份,不是对一个会被地域封锁的主机的现场请求(S-607)。

## 为什么有这个模块

三本 paper book(`beta_core_paper` / `scalable_paper` / `combined_book`)的 `_load_panel`
每次 mark 都现场调 `fapi.binance.com`(`causal_positioning.load_binance_panel`)。
Railway 的出口 IP 不固定,**有的部署落在 Binance 限制的地区,返回 HTTP 451**:
实测 2026-10-18 00:35 `_binance_hf_loop` 26 个币 funding 全部 451,07:46 换了部署又全部可读。
451 的响应体是 `{"code": 0, "msg": "..."}`,`load_binance_panel` 把它当 K 线数组迭代,
`float(k[4])` 落在字符串 `"code"` 上 ⇒ **`string index out of range`** ——
三本账自 10-14 起每天 00:33 同一句报错,`beta_core_nav` 最后一行停在 10-13。

这是 v3 在 08-21 付过的同一笔学费(`beta_core_paper` 头注 v3 (a)),当时把「价格参考改成
Hyperliquid oracle」写进了 `_INCEPTION_REASON`,**代码却没有改**(NAV_POLICY §3 的更正段
自己点过这件事)。这一次改代码。

## 读什么

- **历史收盘**:`ohlcv_daily`,`source = binance_hist`(现货日线,由采集器经
  `data-api.binance.vision` 写入 —— 规则 3b 的那一条摄入 lane)。**只取已收完的日子**
  (`trade_date < 今天 UTC`):采集器也会写当天未收完的 K 线,那一格不是收盘。
- **今天的一行**:调用方传进来的现场价(NAV_POLICY §4 L1 = Hyperliquid oracle,一次请求)。
  没传或某个币缺价 ⇒ 前推并在 `filled` 里标出来 —— **前推的价格不是价格**(S-287)。
- **资金费**(可选):`funding_history`,`venue = binance_perp`,按 UTC 日求均值与求和。
  ① 持现货,不需要它,别为它多读 6 万行。

返回值与 `load_binance_panel` **同一个形状**(`days` 是 epoch 日整数),调用点只换一行。
"""
from __future__ import annotations

import datetime as dt
from typing import Mapping, Optional, Sequence

import numpy as np

CLOSE_SOURCE = "binance_hist"
FUNDING_VENUE = "binance_perp"
_EPOCH = dt.date(1970, 1, 1)


def _epoch_day(d: dt.date) -> int:
    return (d - _EPOCH).days


def build_panel(assets: Sequence[str], days: Sequence[dt.date],
                closes: Mapping[str, Mapping[str, float]],
                live: Optional[Mapping[str, float]] = None,
                funding: Optional[Mapping[str, Mapping[str, list[float]]]] = None):
    """纯函数。`days` 连续的 UTC 日历日,最后一天 = 今天;`closes[sym][YYYY-MM-DD]` 只含已收完的日子;
    `live[sym]` = 今天现场价;`funding[sym][YYYY-MM-DD]` = 当天各期费率。
    返回 (close, fmean, fsum, filled, observed):close 前推填满,filled 标出前推的格,
    observed = 前推之前的原值(缺失为 NaN),给只该用真实观测的计算(收益率 / 波动)。"""
    T, K = len(days), len(assets)
    obs = np.full((T, K), np.nan)
    fmean, fsum = np.zeros((T, K)), np.zeros((T, K))
    keys = [d.isoformat() for d in days]
    for j, a in enumerate(assets):
        by_day = closes.get(a) or {}
        for i, k in enumerate(keys[:-1]):
            v = by_day.get(k)
            if v is not None and v == v and v > 0:
                obs[i, j] = float(v)
        lv = (live or {}).get(a)
        if lv is not None and lv == lv and lv > 0:
            obs[-1, j] = float(lv)
        fu = (funding or {}).get(a) or {}
        for i, k in enumerate(keys):
            v = fu.get(k)
            if v:
                fmean[i, j] = sum(v) / len(v)
                fsum[i, j] = sum(v)
    close = obs.copy()
    filled = np.zeros((T, K), dtype=bool)
    for j in range(K):
        for i in range(1, T):
            if np.isnan(close[i, j]) and not np.isnan(close[i - 1, j]):
                close[i, j] = close[i - 1, j]
                filled[i, j] = True
    return close, fmean, fsum, filled, obs


def observed_returns(observed: np.ndarray) -> np.ndarray:
    """纯函数。只在两端都是真实观测时给收益率,其余 NaN —— 前推出来的平盘日不进波动(I1)。"""
    ret = np.full_like(observed, np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = (observed[1:] - observed[:-1]) / observed[:-1]
    return ret


async def _closes(assets: Sequence[str], start: dt.date, before: dt.date,
                  with_volume: bool = False) -> dict[str, dict[str, float]]:
    """{SYM: {YYYY-MM-DD: close}}(`with_volume` ⇒ 值是 (close, volume),volume = 现货基础币成交量)。"""
    from src.data.style.header import _read_all
    rows = await _read_all("ohlcv_daily", {
        "select": "symbol,trade_date,close" + (",volume" if with_volume else ""), "source": f"eq.{CLOSE_SOURCE}",
        "symbol": "in.(" + ",".join(sorted({a.upper() for a in assets})) + ")",
        "and": f"(trade_date.gte.{start.isoformat()},trade_date.lt.{before.isoformat()})",
        "order": "trade_date.asc,symbol.asc"})
    out: dict = {}
    for r in rows:
        if r.get("close") is None:
            continue
        v = (float(r["close"]), float(r.get("volume") or 0.0)) if with_volume else float(r["close"])
        out.setdefault(str(r["symbol"]).upper(), {})[str(r["trade_date"])[:10]] = v
    return out


async def _funding(assets: Sequence[str], start: dt.date) -> dict[str, dict[str, list[float]]]:
    """{SYM: {YYYY-MM-DD: [各期费率]}}。"""
    from src.data.style.header import _read_all
    rows = await _read_all("funding_history", {
        "select": "symbol,funding_time,funding_rate", "venue": f"eq.{FUNDING_VENUE}",
        "symbol": "in.(" + ",".join(sorted({a.upper() for a in assets})) + ")",
        "funding_time": f"gte.{start.isoformat()}", "order": "funding_time.asc,symbol.asc"})
    out: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        if r.get("funding_rate") is None:
            continue
        out.setdefault(str(r["symbol"]).upper(), {}).setdefault(str(r["funding_time"])[:10], []).append(
            float(r["funding_rate"]))
    return out


async def live_oracle_prices(assets: Sequence[str]) -> dict[str, float]:
    """NAV_POLICY §4 L1:Hyperliquid oracle,一次 `metaAndAssetCtxs`。读不到 ⇒ 空 dict(调用方的覆盖率底线负责拒绝)。"""
    from src.data.market.hyperliquid_collector import venue_snapshot
    snap = await venue_snapshot()
    if not snap.get("ok"):
        return {}
    got = snap.get("assets") or {}
    out = {}
    for a in assets:
        v = (got.get(a.upper()) or {}).get("oracle")
        if v is not None and v > 0:
            out[a] = float(v)
    return out


async def daily_closes(assets: Sequence[str], start: dt.date, before: dt.date,
                       with_volume: bool = False) -> dict:
    """公开入口:已收完的日线(`trade_date` ∈ [start, before))。"""
    return await _closes(assets, start, before, with_volume=with_volume)


async def daily_funding(assets: Sequence[str], start: dt.date) -> dict:
    """公开入口:`funding_history` binance_perp,按 UTC 日分组。"""
    return await _funding(assets, start)


async def load_persisted_panel(assets: Sequence[str], start: dt.date, *,
                               live: Optional[Mapping[str, float]] = None,
                               with_funding: bool = True, today: Optional[dt.date] = None):
    """(days, close, fmean, fsum, filled, observed)。读不到抛异常 —— 读不到 ≠ 0 行(S-180)。"""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    days = [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]
    closes = await _closes(assets, start, today)
    if not closes:
        raise RuntimeError(f"ohlcv_daily source={CLOSE_SOURCE} 在 {start} 之后对这 {len(assets)} 个标的没有行")
    fund = await _funding(assets, start) if with_funding else None
    close, fmean, fsum, filled, obs = build_panel(list(assets), days, closes, live, fund)
    return [_epoch_day(d) for d in days], close, fmean, fsum, filled, obs
