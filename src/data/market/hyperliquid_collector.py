"""Hyperliquid daily candles — the venue we will actually trade on (S-192).

WHY THIS AND NOT BINANCE. Jazz, 2026-08-20: "不是有用 hyperliquid 吗?之后我们要
接 hyperliquid 去交易的呀,直接用起来。" That reframes a problem I had been
solving badly for two days, and it is right on three separate counts:

1. IT REACHES. `data-api.binance.vision` is what `deep_panel_collector` uses
   because api.binance.com is geo-blocked from Railway US. Measured 2026-08-20,
   exactly ONE of 262 panel symbols had a bar since 08-14 — the mirror is not
   working either. Hyperliquid is a public DEX API, no key, not geo-blocked;
   `_fetch_hyperliquid_daily` in `routers/ohlcv.py` has said so in its docstring
   since 2026-07-23. I built a Binance collector anyway.

2. ITS BARS CARRY THEIR OWN DATE. Every candle has a `t` epoch. The CoinGecko
   writer labels rows with the WRITE date instead, which is how our
   `trade_date = 2026-08-19` row ended up holding 2026-08-18's close (measured
   against HL: ours 64,686.30, HL 08-18 64,696, HL 08-19 69,323). A source that
   ships the timestamp cannot drift like that.

3. IT IS THE VENUE. A paper book marked on CoinGecko spot and executed on
   Hyperliquid perps is a splice — it just shows up as unexplained slippage
   rather than as a discontinuity in a chart. Marks should come from where the
   fills will.

WHAT THIS COSTS, STATED PLAINLY. Of the 262-symbol Binance research panel, only
**88 (34%)** are listed on Hyperliquid; HL lists 144 the panel has never seen.
So this is not a drop-in replacement for the historical panel — it is a
different, SMALLER, TRADEABLE universe. The 174 non-overlapping symbols are
assets we can research and cannot execute, which is the same class of error as
building sleeve ④ before sleeve ① : work that cannot reach a book.

SOURCE LABEL. Writes `source='hyperliquid'`, never mixed into `binance_hist`.
Bar convention is a property of the source (S-106/S-107: >1% open gaps run
31.3% on Crypto vs 83.5% on DeFi), and perp marks are not spot closes. Two
labels, two conventions, no splice.

THE FLOOR BLOCKS. See S-190: `deep_panel_collector` had its coverage floor wired
into the return value only, so a 1-of-262 run still wrote, and `max(trade_date)`
then read as current. Here the floor returns before the write.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

_log = logging.getLogger("hyperliquid")

_INFO_URL = "https://api.hyperliquid.xyz/info"
SOURCE = "hyperliquid"

# ── S-204 (2026-08-23): the collector rate-limited ITSELF into refusing ─────
# Measured: concurrency 8 with a 0.15s pause is roughly 53 req/s. Hyperliquid
# answered HTTP 429 to 57 of 232 symbols — including BTC — which dropped coverage
# to 56%, below the 70% floor, so the collector refused to write and said so only
# to a print statement. Two days of silence, self-inflicted, and the refusal was
# CORRECT at every step: the throttling was real, the floor did its job, the
# write was rightly withheld. The defect is that the collector caused the
# condition it then correctly refused to write through.
#
# ~6 req/s stays well inside the documented budget. A collector that takes two
# minutes and finishes beats one that takes twenty seconds and gets banned —
# the same trade `deep_panel_collector` states and then set too aggressively.
_CONCURRENCY = 3
_BATCH_PAUSE_S = 0.5
_MAX_RETRIES = 3            # 429 is transient; a delisted symbol is not
_RETRY_BACKOFF_S = 2.0

_MIN_OK_FRACTION = 0.70
_DEFAULT_DAYS = 10
_TIMEOUT = 25.0


async def hyperliquid_universe(client: httpx.AsyncClient | None = None) -> list[str]:
    """Every perp currently listed. This IS our tradeable universe."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await client.post(_INFO_URL, json={"type": "meta"})
        r.raise_for_status()
        return [a["name"] for a in r.json().get("universe", []) if a.get("name")]
    except Exception as e:                                    # noqa: BLE001
        _log.warning("[HL] universe fetch failed: %s", e)
        return []
    finally:
        if own:
            await client.aclose()


async def _fetch_one(client: httpx.AsyncClient, coin: str,
                     days: int) -> tuple[str, list[dict], str | None]:
    """One symbol's daily candles. Never raises."""
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - (days + 2) * 86_400_000
    # 429 is a THROTTLE (retry) and an empty body is a DELISTING (never retry).
    # Collapsing them is what made a self-inflicted rate limit look like 45% of
    # the venue disappearing — the same miss-vs-error collapse as S-180, one
    # protocol layer down.
    candles = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = await client.post(_INFO_URL, json={
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": "1d",
                        "startTime": start_ms, "endTime": end_ms}})
            if r.status_code == 429:
                if attempt == _MAX_RETRIES - 1:
                    return coin, [], "throttled(429)"
                await asyncio.sleep(_RETRY_BACKOFF_S * (2 ** attempt))
                continue
            r.raise_for_status()
            candles = r.json()
            break
        except Exception as e:                                # noqa: BLE001
            if attempt == _MAX_RETRIES - 1:
                return coin, [], f"{type(e).__name__}: {str(e)[:80]}"
            await asyncio.sleep(_RETRY_BACKOFF_S * (2 ** attempt))
    if not isinstance(candles, list) or not candles:
        return coin, [], "delisted"

    rows = []
    for k in candles:
        try:
            # ⚠️ THE DATE COMES FROM THE BAR, NEVER FROM THE CLOCK.
            # This single line is the difference between this collector and the
            # CoinGecko one, whose rows are stamped with the write date and are
            # therefore all off by one day (S-191). A bar knows when it is; the
            # process writing it does not.
            ts = int(k["t"]) / 1000.0
            close = float(k["c"])
            rows.append({
                "symbol": coin.upper(),
                "asset_class": "Crypto",
                "trade_date": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                "open":  float(k.get("o") or close),
                "high":  float(k.get("h") or close),
                "low":   float(k.get("l") or close),
                "close": close,
                "volume": float(k.get("v") or 0.0),
                "source": SOURCE,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return coin, rows, None


async def venue_snapshot() -> dict[str, Any]:
    """Every perp's mark, oracle, funding, OI and day volume — in ONE request.

    ⚠️ S-205. This replaces a 232-request `candleSnapshot` fan-out that existed
    only because I never looked for a bulk endpoint. Jazz, 2026-08-23:
    「不可以那么依赖任何免费 api,大量多资产会被封啊」— and he had said it before.
    The 429s were not a wall to pace against; they were the venue telling me I
    was asking the wrong question 232 times.

    What this returns that CoinGecko cannot: FUNDING (the carry that decides
    whether a perp sleeve is viable — measured +23.07% annualised equal-weight on
    the ① panel), the oracle-vs-mark basis, open interest, and the tradeable
    listing itself. Those are venue facts. Bulk price history is CoinGecko Pro's
    job, which we pay for.
    """
    out: dict[str, Any] = {"ok": False, "assets": {}}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(_INFO_URL, json={"type": "metaAndAssetCtxs"})
            if r.status_code == 429:
                return {**out, "reason": "throttled — one call should never be; "
                                         "check for another fan-out in this process"}
            r.raise_for_status()
            meta, ctxs = r.json()
    except Exception as e:                                    # noqa: BLE001
        return {**out, "reason": f"{type(e).__name__}: {str(e)[:100]}"}

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None          # I1: unmeasured is None, never 0.0

    assets = {}
    for a, c in zip(meta.get("universe", []), ctxs):
        name = a.get("name")
        if not name:
            continue
        assets[name.upper()] = {
            "mark": _f(c.get("markPx")),
            "oracle": _f(c.get("oraclePx")),
            "prev_day": _f(c.get("prevDayPx")),
            "funding_1h": _f(c.get("funding")),
            "open_interest": _f(c.get("openInterest")),
            "day_notional_volume": _f(c.get("dayNtlVlm")),
        }
    return {"ok": True, "assets": assets, "n": len(assets),
            "fetched_at": datetime.now(timezone.utc).isoformat()}


async def collect_venue_marks() -> dict[str, Any]:
    """把 `venue_snapshot()` 落进 `funding_history` —— **接上那块从没插线的卡** (S-296).

    ## 这个函数存在的原因

    `venue_snapshot()` 是 S-205 为了替掉 233 次 candleSnapshot 而写的正确答案:
    一次请求拿到全部永续的 mark / oracle / funding / OI。写完之后
    **它的调用点是零个** —— 我 grep 过,全仓只有测试和一句注释提到它。

    于是 2026-08-23 起的两周是这样的:数量守卫正确地拦住了蜡烛扇出,
    循环每 6 小时抛一次 `SourcePolicyError`,而**替代路径就在同一个文件里、
    没人调用**。Jazz 的话:「买了显卡、存储、网卡,但是服务器不是连通的。」
    这次连显卡都是自己买的。

    ## 为什么这是 execution 用途,不是 market_data

    funding 是**只有场馆知道的事实**,CoinGecko 给不了。而它正是决定
    永续 sleeve 能不能成立的量 —— ① 面板 24 个名字实测等权 funding
    **年化 +23.07%**,所以毛 1.15 的永续版 ① 每年漏 ~26.5%。
    这个数字比我们证明过的任何 alpha 都大,它必须每天有人量。

    ## 一次请求,所以没有资产集口径问题

    用途轴要求 execution 扇出必须显式传名单。**这里不是扇出** ——
    一次 `metaAndAssetCtxs` 覆盖全部永续,`n_assets` 对策略层就是 1。
    这正是 S-205 那句「the venue telling me I was asking the wrong question」
    的落地形态。

    ## 时间戳取整到小时

    循环每 6 小时一轮,PK 是 `(symbol, funding_time, venue)`。取整到小时
    让同一小时内的重跑幂等,一天落 4 个时点 × ~233 个标的。
    **不取整的话每次重跑都是新行**,Supabase 免费档撑不了几周。
    """
    from src.api.store import supabase_upsert_table

    started = datetime.now(timezone.utc)
    snap = await venue_snapshot()
    if not snap.get("ok"):
        return {"ok": False, "error": snap.get("reason", "venue_snapshot failed"),
                "diagnosis": ("场馆快照拿不到 —— **这是一次请求就失败**,"
                              "不是限流。先查 api.hyperliquid.xyz 可达性")}

    ts = started.replace(minute=0, second=0, microsecond=0).isoformat()
    rows, n_no_funding = [], 0
    for sym, a in (snap.get("assets") or {}).items():
        # I1:funding 是 None 表示**没量到**,不是 0。一个 0 funding 的永续
        # 和一个我们没读到 funding 的永续,在 carry 计算上是两个完全不同的结论。
        if a.get("funding_1h") is None:
            n_no_funding += 1
            continue
        rows.append({"symbol": sym, "funding_time": ts, "venue": SOURCE,
                     "funding_rate": a["funding_1h"], "mark_price": a.get("mark")})

    written = 0
    for i in range(0, len(rows), 2000):
        if await supabase_upsert_table("funding_history", rows[i:i + 2000],
                                       on_conflict="symbol,funding_time,venue"):
            written += len(rows[i:i + 2000])
        else:
            break

    elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    return {
        "ok": bool(rows) and written == len(rows),
        "n_perps": snap.get("n"), "rows_written": written,
        "n_missing_funding": n_no_funding,
        "funding_time": ts, "elapsed_s": elapsed,
        "reason": (f"{snap.get('n')} 个永续一次请求 · 写入 {written} 行 funding"
                   + (f" · {n_no_funding} 个没读到 funding(记为未量到,不是 0)"
                      if n_no_funding else "")),
    }


async def collect_hyperliquid(days: int = _DEFAULT_DAYS,
                              symbols: list[str] | None = None) -> dict[str, Any]:
    """Refresh Hyperliquid daily bars **for an explicitly named execution set**.

    ⚠️ S-296:`symbols` 从「可选」变成**实质必填**。默认拿场馆挂牌当名单,
    正是 S-204 那次 233 个标的扇出的来源 —— 而「HL 挂了什么」是场馆的库存,
    「我们会在哪里下单」是我们的决定,两者塌进一个默认值就会得到那次事故。

    面板行情不走这里,走 CoinGecko Pro(付费,fan-out 是买来的权利)。
    这里只服务成交标记。
    """
    from src.api.store import supabase_upsert_table

    started = datetime.now(timezone.utc)
    explicit = bool(symbols)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        syms = symbols or await hyperliquid_universe(client)
        if not syms:
            return {"ok": False, "error": "no Hyperliquid symbols resolved",
                    "note": "meta endpoint unreachable or empty"}

        # ── S-296: 用途 + 数量,两道 ────────────────────────────────────────
        # 数量守卫(S-205)问「这么多资产能不能在这个源上取」;用途守卫问
        # 「这件事本来该在哪个源上做」,并且要求 execution 扇出的名单是
        # 调用方显式给的。**S-205 只拦不导,结果是把违规变成了两周的缺口。**
        from src.data.market.source_policy import (
            EXECUTION, assert_purpose_source)
        assert_purpose_source(EXECUTION, "hyperliquid", n_assets=len(syms),
                              job="hyperliquid execution-set candles",
                              explicit_set=explicit)

        sem = asyncio.Semaphore(_CONCURRENCY)
        all_rows: list[dict] = []
        failures: dict[str, str] = {}

        async def _go(s: str):
            async with sem:
                sym, rows, err = await _fetch_one(client, s, days)
                if err:
                    failures[sym] = err
                else:
                    all_rows.extend(rows)
                await asyncio.sleep(_BATCH_PAUSE_S)

        await asyncio.gather(*[_go(s) for s in syms])

    ok_n = len(syms) - len(failures)
    # ── S-204: the floor measures REACHABILITY, not listing churn ────────────
    # A delisted perp returns an empty body and will do so forever — MATIC, RNDR,
    # FTM and 42 others sit in the venue's `meta` list under names it no longer
    # serves candles for. Counting them as failures lets a PERMANENT fact drag a
    # health signal down on every run: on 2026-08-21 the combination (45 delisted
    # + 57 throttled) put coverage at 56%, tripped the 70% floor, and withheld
    # the write for two days.
    #
    # The denominator is symbols that COULD have answered. Delistings are
    # reported, not counted — inventory news, not an outage.
    delisted = {s for s, why in failures.items() if why == "delisted"}
    throttled = {s for s, why in failures.items() if why and why.startswith("throttled")}
    reachable = [s for s in syms if s not in delisted]
    frac = ok_n / len(reachable) if reachable else 0.0
    if throttled:
        _log.warning("[HL] %s symbols throttled after %s retries — the collector "
                     "is pacing itself too fast for the venue, not the venue "
                     "being down", len(throttled), _MAX_RETRIES)
    elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 1)

    # S-190: the floor BLOCKS. A partial panel day is not a thin day, it is a
    # different object — a cross-sectional read of it gets a handful of symbols
    # with no way to know, and `max(trade_date)` then reports the feed as
    # current. A visible gap is recoverable; a silently partial day is not.
    if all_rows and frac < _MIN_OK_FRACTION:
        _log.error("[HL] REFUSING TO WRITE — %s/%s symbols (%.0f%%, floor %.0f%%). "
                   "Sample: %s", ok_n, len(syms), frac * 100,
                   _MIN_OK_FRACTION * 100, dict(list(failures.items())[:5]))
        return {"ok": False, "refused": True, "written": False,
                "symbols_total": len(syms), "symbols_reachable": len(reachable),
                "symbols_delisted": len(delisted), "symbols_throttled": len(throttled),
                "symbols_ok": ok_n,
                "symbols_failed": len(failures), "ok_fraction": round(frac, 3),
                "rows_built": len(all_rows), "rows_upserted": 0,
                "elapsed_s": elapsed,
                "failure_sample": dict(list(failures.items())[:8]),
                "diagnosis": (f"only {ok_n}/{len(syms)} symbols ({frac:.0%}) — below "
                              f"the {_MIN_OK_FRACTION:.0%} floor. Write REFUSED so the "
                              f"gap stays visible.")}

    written = bool(all_rows)
    if all_rows:
        for i in range(0, len(all_rows), 2000):
            if not await supabase_upsert_table(
                    "ohlcv_daily", all_rows[i:i + 2000],
                    on_conflict="symbol,trade_date,source"):
                written = False
                break

    out = {
        "ok": written and frac >= _MIN_OK_FRACTION,
        "symbols_total": len(syms),
        "symbols_reachable": len(reachable),
        "symbols_delisted": len(delisted),
        "symbols_throttled": len(throttled),
        "symbols_ok": ok_n,
        "symbols_failed": len(failures),
        "ok_fraction": round(frac, 3),
        "rows_built": len(all_rows),
        "rows_upserted": len(all_rows) if written else 0,
        "written": written,
        "elapsed_s": elapsed,
        "latest_bar": max((r["trade_date"] for r in all_rows), default=None),
        "failure_sample": dict(list(failures.items())[:8]),
    }
    if not written and all_rows:
        out["diagnosis"] = ("rows built but the upsert was declined — check "
                            "APP_ROLE=production and the Supabase log")
    (_log.warning if not out["ok"] else _log.info)(
        "[HL] %s/%s symbols · %s rows · latest %s · %.1fs",
        ok_n, len(syms), out["rows_upserted"], out["latest_bar"], elapsed)
    return out


async def tradeable_overlap(panel_symbols: list[str]) -> dict[str, Any]:
    """How much of a research panel can actually be executed on Hyperliquid.

    Exists because the answer surprised me and belongs in front of anyone
    designing a sleeve: measured 2026-08-20, 88 of the 262-symbol Binance panel
    (34%) are listed on HL. Research on the other 174 cannot reach a book.
    """
    hl = set(await hyperliquid_universe())
    panel = {s.upper() for s in panel_symbols}
    both = sorted(panel & hl)
    return {
        "panel_n": len(panel),
        "hyperliquid_n": len(hl),
        "tradeable_n": len(both),
        "tradeable_pct": round(100 * len(both) / len(panel), 1) if panel else 0.0,
        "research_only": sorted(panel - hl),
        "untouched_on_venue": sorted(hl - panel),
    }
