"""
Daily collector for the deep research panel (S-179, 2026-08-19).

WHAT WAS WRONG. `ohlcv_daily` holds 262 crypto symbols back to 2017 under
`source='binance_hist'` — the panel every historical study runs on. It was
loaded once by a backfill and **no daily collector ever covered it**. Measured
2026-08-19 it was 11 days stale, which silently blocked the depth-divergence
forward record, any embedding rebuild, and anything else that needs today.

`collect_ohlcv` covers 58 symbols (ASSETS_CONFIG, the CIS universe) and always
did. This is not a broken feed; it is a feed that was never built.

WHY BINANCE AND NOT COINGECKO. Volumetrically CoinGecko Pro would do it — Jazz
is right about that. But this repo measured the thing that decides it (S-106 /
S-107):

    "bar convention is a property of the SOURCE, not of the class"
    >1% open gaps: Crypto 31.3% · L1 73.7% · L2 79.5% · DeFi 83.5%

Nine years of this panel are Binance bars. Appending CoinGecko bars from
2026-08-08 onward would splice two conventions into one series, and any study
crossing that date would read the discontinuity as market structure. S-106 made
exactly that mistake once already. Same source in, same source forward.

`data-api.binance.vision` is used deliberately: api.binance.com is geo-blocked
from Railway US, and `get_klines_binance` already routes to the mirror.

CONCURRENCY IS CAPPED. 262 symbols fired at once is a burst that gets an IP
banned, and the ban would look exactly like the stale feed this replaces.
`_CONCURRENCY` matches the 8 that `collect_ohlcv` already settled on, with a
small inter-batch pause. A collector that takes 30 seconds and finishes beats
one that takes 3 and gets throttled.

PARTIAL RUNS ARE VISIBLE, NOT AVERAGED AWAY. The return value reports
`symbols_ok`, `symbols_failed` and the failure reasons. A run that reaches 40 of
262 must not read like a quiet day — that collapse is what let the panel sit
stale for eleven days while `/internal/loop-health` reported "flowing" off a
single fresh BTC row.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("deep_panel")

# Matches collect_ohlcv's settled value. Binance weight for a 1d klines call is
# small; the risk is connection burst, not weight budget.
_CONCURRENCY = 8
_BATCH_PAUSE_S = 0.25

# Below this the run is a failure, not a thin day. Chosen to sit under normal
# attrition (a handful of delisted pairs 404) and well above a throttle event.
_MIN_OK_FRACTION = 0.70

#: 深盘 universe 的**分母**地板 (S-323)。覆盖率地板量的是分子,量不了分母。
#: 库里实测 262 个 binance_hist 符号 (2026-09-08)。地板取 200 —— 留出正常的
#: 下架流失空间,但任何一次「掉到 200 以下」都是符号表本身出了事,不是行情。
#: **这个数只能往上调,不能往下调**:调低它等于把一次塌陷重新定义成正常。
_MIN_PANEL_SYMBOLS = 200

_DEFAULT_DAYS = 14   # a fortnight of overlap; upsert makes re-writes free

#: 自愈窗口上限 (S-323)。Binance 1d klines 一次请求最多 1000 根,所以 180 天
#: 仍是**每个符号一个请求** —— 自愈不会变成一场洪水。
#: 上限存在只是为了让一次异常的 latest(比如某个符号 2017 年就停更)不会
#: 把整轮拖成全量重拉。
_HEAL_MAX_DAYS = 180


async def deep_panel_symbols() -> list[str] | None:
    """Symbols that already have binance_hist history — i.e. the panel itself.

    **三值,不是两值** (S-323 第二轮):

        [...]   读到了,这些就是全部
        []      读通了,库里确实一个都没有
        None    **没读到** —— RPC 不通/熔断/超时

    第一轮修复我把三个折成了两个:日志里区分了「读不到」和「没有」,
    `return []` 又把区分丢掉了,于是 `_deep_panel_loop` 报
    `no deep-panel symbols resolved` —— 一句同时covers「Supabase 没应答」
    和「面板真的空了」的话,一个要等,一个要改配置。
    **我在修「两个状态一个表示」的补丁里,又做了一次「两个状态一个表示」。**

    Driven off the DATA rather than the `assets` registry on purpose. Measured
    2026-08-19: 487 registry rows carry monitor_daily=true with `class` NULL and
    zero of them are fresh, because nothing can route a symbol whose class is
    unknown. Fixing that registry is worth doing and is not a prerequisite for
    keeping the panel current — the panel knows what it is.

    ⚠️ **S-323:这里原本靠「把行拉回来再去重」得到符号集** ——
    `?select=symbol&source=eq.binance_hist&limit=100000`。PostgREST 有服务端
    `max-rows` 上限(默认 1000):请求 100000 只回 1000 行,**并且返回 200**。
    38 万行表的头 1000 行在物理顺序上几乎全属同一个 symbol,所以这个函数
    实测回了 **2** 个,而库里是 **262**。

    「拿到了一页」和「拿到了全部」是两个状态,HTTP 200 对这两个的回答一样。
    截断在这里不是「少了点数据」,是**把一个 262 元的集合换成一个 2 元的集合**;
    下游(`collect_deep_panel`,以及 S-318 起的 `_cg_panel_loop`)拿到 2 个照跑,
    照报 ok —— **一个覆盖 2 个资产的成功,和覆盖 262 个的成功,输出完全一样。**

    改为调 `deep_panel_symbol_list()` RPC:去重在数据库里做,回来的是 262 行
    而不是 38 万行,**结构上不可能再被 max-rows 截断**。
    """
    rows = await deep_panel_state()
    if rows is None:
        return None
    return sorted({str(r["symbol"]).upper() for r in rows if r.get("symbol")})


async def deep_panel_state() -> list[dict] | None:
    """每个深盘符号的 (symbol, n_rows, latest)。三值,同上。

    `latest` 是这个循环自愈的依据:固定 14 天的重叠窗**同时也是一个上限** ——
    它决定了这个循环永远只能修复 14 天以内的洞。2026-09-08 实测洞有 21 天
    (08-18 起每天只进 1–4 个标的),固定窗口够不着,只能靠人手跑一次。
    **一个需要人手补的自动循环,下次出事还是要人手。**
    """
    from src.api.store import supabase_rpc
    try:
        rows = await supabase_rpc("deep_panel_symbol_list")
    except Exception as e:                                   # noqa: BLE001
        _log.warning("[DEEP] symbol list RPC raised: %s", e)
        return None
    if rows is None or rows is True or not isinstance(rows, list):
        # `supabase_rpc` 把「熔断/超时/4xx」全折成 None,把「200 但不是 JSON」
        # 折成 True。两者都是**没读到**,往上传 None 而不是 []。
        _log.warning("[DEEP] symbol list RPC unreachable — None (NOT an empty panel)")
        return None
    return rows


async def _fetch_one(symbol: str, days: int) -> tuple[str, list[dict], str | None]:
    """One symbol. Returns (symbol, rows, error). Never raises."""
    from src.data.market.data_layer import get_klines_binance
    pair = symbol if symbol.upper().endswith("USDT") else f"{symbol.upper()}USDT"
    try:
        kl = await get_klines_binance(pair, "1d", months=max(1, days // 30 + 1))
    except Exception as e:                                   # noqa: BLE001
        return symbol, [], f"{type(e).__name__}: {str(e)[:80]}"
    if not kl:
        # A delisted pair answers empty. Distinguished from an error so the
        # summary can tell attrition from an outage.
        return symbol, [], "empty (delisted or unlisted pair?)"

    rows = []
    for k in kl[-days:]:
        try:
            ts = int(k["time"]) / 1000.0
            rows.append({
                "symbol": symbol.upper(),
                "asset_class": "Crypto",
                "trade_date": datetime.fromtimestamp(ts, timezone.utc).date().isoformat(),
                "open": float(k["open"]), "high": float(k["high"]),
                "low": float(k["low"]), "close": float(k["close"]),
                "volume": float(k["volume"]),
                # SAME LABEL AS THE HISTORY, deliberately. 'hist' is a misnomer
                # now, but the label's job is to mark the bar convention, and a
                # second label for the same convention would fragment the series
                # for every query that filters on source.
                "source": "binance_hist",
            })
        except (KeyError, TypeError, ValueError):
            continue
    return symbol, rows, None


async def collect_deep_panel(days: int | None = None,
                             symbols: list[str] | None = None) -> dict[str, Any]:
    """Refresh the deep panel. Idempotent; safe to run repeatedly.

    `days=None` ⇒ **窗口自己算**,见 `_HEAL_MAX_DAYS`。
    """
    from src.api.store import supabase_upsert_table

    state = None if symbols is not None else await deep_panel_state()
    syms = (symbols if symbols is not None
            else (None if state is None
                  else sorted({str(r["symbol"]).upper() for r in state
                               if r.get("symbol")})))

    # 「没读到」和「读通了但是空的」分开报 —— 前者等下一轮,后者改配置。
    # 上一版这里是 `either Supabase is unreachable or binance_hist is empty`:
    # **一句话把两个修法完全不同的状态并列,读的人两边都不能动。**
    if syms is None:
        return {"ok": False, "status": "error", "written": False,
                "symbols_total": None, "rows_upserted": 0,
                "error": ("深盘符号表**没读到**(RPC 不通/熔断/超时)—— "
                          "**这不是「面板空了」**,是这一轮没问到。等下一轮;"
                          "若连续多轮,查 Supabase 熔断器与 deep_panel_symbol_list 授权。")}
    if not syms:
        return {"ok": False, "status": "error", "written": False,
                "symbols_total": 0, "rows_upserted": 0,
                "error": ("深盘符号表**读通了,但是空的** —— binance_hist 一行都没有。"
                          "这是配置/数据问题,重试不会变好。")}

    # ── S-323:**universe 塌了** 和 **抓取失败** 是两个状态 ──────────────────
    # 2026-09-08 线上:`deep_panel_symbols()` 被 PostgREST 的 max-rows 截断,
    # 回了 2 个符号(库里 262)。下面的 `_MIN_OK_FRACTION` 地板照常工作,
    # 报出来是「only 0/2 symbols returned data」—— 读起来像「两个标的抓不到」,
    # 而真相是「我们弄丢了 260 个标的」。**报错文本把一个 99% 的覆盖塌陷
    # 讲成了一次小失败**,所以它在心跳里躺了不知道多少轮没人看出来。
    #
    # 覆盖率地板量的是「拿到的这些里成功几个」,量不了「拿到的这些够不够全」。
    # 分母自己也需要一个地板 —— 否则分母缩到 2,100% 成功依然是空的。
    if symbols is None and len(syms) < _MIN_PANEL_SYMBOLS:
        _log.error("[DEEP] REFUSING TO RUN — universe resolved to %s symbols, "
                   "floor %s. This is not a fetch failure: the SYMBOL LIST is "
                   "short. Check deep_panel_symbol_list() / max-rows truncation.",
                   len(syms), _MIN_PANEL_SYMBOLS)
        return {
            "ok": False, "status": "error", "written": False,
            "symbols_total": len(syms), "symbols_ok": 0, "rows_upserted": 0,
            "universe_collapsed": True,
            "error": (f"深盘 universe 只解析出 {len(syms)} 个标的(地板 "
                      f"{_MIN_PANEL_SYMBOLS})—— **这不是抓取失败,是符号表本身短了**。"
                      f"分母塌了的时候,100% 成功率依然是空的。"),
        }

    # ── S-323:重叠窗口**自己算**,不写死 ────────────────────────────────────
    # 固定 14 天的重叠窗同时也是一个上限:**这个循环永远只能修复 14 天以内的洞。**
    # 2026-09-08 实测洞有 21 天(08-18 起每天只进 1–4 个标的),够不着,只能人手跑。
    # **一个需要人手补的自动循环,下次出事还是要人手。**
    # `deep_panel_symbol_list()` 本来就返回每个符号的 latest —— 用它,不额外读。
    if days is None:
        days = _DEFAULT_DAYS
        if state:
            try:
                lat = sorted(datetime.strptime(str(r["latest"])[:10], "%Y-%m-%d").date()
                             for r in state if r.get("latest"))
            except ValueError:
                lat = []
            if lat:
                # **中位数,不是 min。** min 会被一个 2017 年就下架的符号绑架,
                # 把窗口永久钉在上限 —— 那是「一个离群点决定了全局策略」,
                # 和覆盖率地板被 2 个标的的分母绑架是同一个形状。
                frontier = lat[len(lat) // 2]
                gap = (datetime.now(timezone.utc).date() - frontier).days + 2
                days = max(_DEFAULT_DAYS, min(gap, _HEAL_MAX_DAYS))
        if days > _DEFAULT_DAYS:
            _log.warning("[DEEP] healing window %sd (gap detected) — not the usual %sd",
                         days, _DEFAULT_DAYS)

    started = datetime.now(timezone.utc)
    sem = asyncio.Semaphore(_CONCURRENCY)
    all_rows: list[dict] = []
    failures: dict[str, str] = {}

    async def _go(s: str):
        async with sem:
            sym, rows, err = await _fetch_one(s, days)
            if err:
                failures[sym] = err
            else:
                all_rows.extend(rows)
            await asyncio.sleep(_BATCH_PAUSE_S)

    await asyncio.gather(*[_go(s) for s in syms])

    ok_n = len(syms) - len(failures)
    frac = ok_n / len(syms) if syms else 0.0

    # ── S-190 (2026-08-20): the floor must BLOCK, not annotate ───────────────
    # This function's own docstring says "a run that reaches 40 of 262 must not
    # read like a quiet day", citing the eleven days the panel sat stale while
    # loop-health reported "flowing" off one fresh BTC row. `_MIN_OK_FRACTION`
    # was then wired only into `out["ok"]` — the write went ahead regardless.
    #
    # Measured 2026-08-20, one day after shipping: exactly ONE symbol (BCH) has
    # a bar since 08-14. The collector had been writing that single symbol every
    # run, reporting ok=False to a print statement nobody reads, and leaving
    # `max(trade_date)` at today — so every freshness check in the system saw a
    # current panel. I diagnosed the failure in the docstring and reproduced it
    # one function later.
    #
    # A partial panel day is not a thin panel day, it is a DIFFERENT OBJECT: any
    # cross-sectional study reading 2026-08-20 gets a one-symbol universe and no
    # way to know. A visible gap is recoverable; a day that silently contains
    # one asset corrupts every study that crosses it.
    if all_rows and frac < _MIN_OK_FRACTION:
        _log.error(
            "[DEEP] REFUSING TO WRITE — only %s/%s symbols returned data (%.0f%%, "
            "floor %.0f%%). Writing them would leave max(trade_date) at today and "
            "make the panel read as current. Sample failures: %s",
            ok_n, len(syms), frac * 100, _MIN_OK_FRACTION * 100,
            dict(list(failures.items())[:5]))
        return {
            "ok": False,
            "symbols_total": len(syms), "symbols_ok": ok_n,
            "symbols_failed": len(failures), "ok_fraction": round(frac, 3),
            "rows_built": len(all_rows), "rows_upserted": 0, "written": False,
            "refused": True,
            "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
            "failure_sample": dict(list(failures.items())[:8]),
            "diagnosis": (
                f"only {ok_n}/{len(syms)} symbols ({frac:.0%}) — below the "
                f"{_MIN_OK_FRACTION:.0%} floor. Write REFUSED so the gap stays "
                f"visible rather than being papered over by a partial day."),
        }

    written = False
    if all_rows:
        # Chunked: a single 250k-row body is a timeout, not a write.
        written = True
        for i in range(0, len(all_rows), 2000):
            if not await supabase_upsert_table(
                    "ohlcv_daily", all_rows[i:i + 2000],
                    on_conflict="symbol,trade_date,source"):
                written = False
                break

    out = {
        "ok": bool(written) and frac >= _MIN_OK_FRACTION,
        "symbols_total": len(syms),
        "symbols_ok": ok_n,
        "symbols_failed": len(failures),
        "ok_fraction": round(frac, 3),
        "rows_upserted": len(all_rows) if written else 0,
        "rows_built": len(all_rows),
        "written": written,
        "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        # First few reasons, not a count. "12 failed" is not actionable;
        # "12 failed with HTTP 418" is.
        "failure_sample": dict(list(failures.items())[:8]),
    }
    if frac < _MIN_OK_FRACTION:
        out["diagnosis"] = (
            f"only {ok_n}/{len(syms)} symbols returned data ({frac:.0%}, floor "
            f"{_MIN_OK_FRACTION:.0%}). Below this it is a throttle or an outage, "
            f"not normal delisting attrition — do NOT read the result as a quiet day.")
    if not written and all_rows:
        out["diagnosis"] = ("rows built but the upsert was declined — check "
                            "APP_ROLE=production and the Supabase log")

    (_log.warning if not out["ok"] else _log.info)(
        "[DEEP] %s/%s symbols · %s rows · %.1fs%s",
        ok_n, len(syms), out["rows_upserted"], out["elapsed_s"],
        "  ⚠️ " + out.get("diagnosis", "") if not out["ok"] else "")
    return out
