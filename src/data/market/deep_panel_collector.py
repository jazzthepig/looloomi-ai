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

#: 真正有 bar 的标的数的**绝对**地板 (S-415)。覆盖率地板的分母现在只数「能回答的」
#: (下架/非 Binance 现货对不算失败,见 `collect_deep_panel`),于是需要一个绝对数
#: 防住「所有请求都回空」这种整体故障 —— 那时 reachable→0,比例失去意义。
#: 实测 2026-09-23:262 个符号里 139 个是活的 Binance 现货对,123 个回空
#: (1000SHIB 这类永续命名、AGIX 这类已下架、HL 独有名)。取 100。
_MIN_LIVE_SYMBOLS = 100

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
    rows, _detail = await deep_panel_state_detailed()
    return rows


async def deep_panel_state_detailed() -> tuple[list[dict] | None, dict]:
    """Same, but also returns WHAT HAPPENED (S-323m).

    ⚠️ 上一版把「熔断/超时/4xx/非 JSON」全折成一个 None,然后调用方把这个 None
    渲染成一句写死的「RPC 不通/熔断/超时」。**那句话里列的是当年作者的三个猜测,
    不是这次的响应** —— 而真凶(`permission denied for function
    ohlcv_symbol_coverage`)的名字在里面一个字都没有,于是它把连续五轮诊断
    全部送回了那三个猜测。

    真实证据一直都在:`store.py` 用 `_logger.warning` 打了状态码和 body,
    然后**扔掉**。没有任何东西把它们送到 `_beat(error=...)`,
    而 `/internal/data-freshness` 是所有人真正会读的那个面。

    **诊断字段只能装观测,不能装假设。**
    """
    from src.api.rpc_diagnostics import rpc_with_detail, render_detail
    rows, detail = await rpc_with_detail("deep_panel_symbol_list")
    if detail.get("outcome") != "ok" or not isinstance(rows, list):
        if detail.get("outcome") == "ok":
            # 200 且能解析,但不是 list —— 仍然是**没读到**,不是空面板。
            detail["outcome"] = "not_a_list"
            detail["body"] = f"{type(rows).__name__}: {str(rows)[:120]}"
        _log.warning("[DEEP] %s", render_detail(detail, prefix="symbol list "))
        return None, detail
    return rows, detail


async def deep_panel_symbols_detailed() -> tuple[list[str] | None, dict, list[str] | None]:
    """`deep_panel_symbols()` + the detail + an OPTIONAL latest-date hint.

    ⚠️ S-323x:走 `deep_panel_symbols_fast()`,**不再为了一串名字去付一次
    38 万行的聚合**。

    实测 2026-09-09,指挥台上第一次拿到真数字(而不是三个嫌疑人):

        _cg_panel_loop  deep_panel_symbol_list: no response
                        (timeout or retries exhausted) [52960ms]

    53 秒。同一个调用从外面量是 0.6–1.3s —— 差别是**争用**:所有循环都在
    开机后 180s 内起跑,同时打向一个每次都重算 386,257 行(binance_hist 占
    全表 71%)的函数,只为得到同样的 262 个名字。

    而这个调用方**从来不需要那个聚合** —— 它拿到 state 之后把 n_rows 和
    latest 全丢掉,只留名字。松散索引扫描(skip-scan)每个 DISTINCT symbol
    走一条索引项而不是每一行:**1315ms/2406 buffers → 203ms/793 buffers**。

    ⚠️ **这确实是「同一个量的第二个实现」,而 S-323 明确警告过它会漂移。**
    两者的口径必须永远一致,所以指挥台每轮对账两个 RPC 的符号集合,
    不一致即 act_now(见 `scripts/ops_console.py`)——
    **不是靠「记得它们要一致」,是靠每天有人把它们摆在一起看。**

    ## S-378b-C1 第三返回值:`latest` 提示
    如果快路径 RPC 返回的每一行恰好带 `latest`(SQL 写成了
    `select symbol, max(trade_date) as latest from ... group by symbol`),
    我们顺手把每个标的的 latest 收上来,好让 `collect_deep_panel` 算自愈窗口
    而**不必再去打一次慢 RPC**。当前生产 SQL 不返回 latest,这个值会是 `None`,
    自愈窗口退回默认 14 天 —— 那只是「不能更长」,不是「超时」,下一次 SQL 升级
    即恢复。测试环境里 stub 出来的 state 行带 latest,所以这个能力已经在守。
    """
    from src.api.rpc_diagnostics import rpc_with_detail, render_detail
    rows, detail = await rpc_with_detail("deep_panel_symbols_fast")
    if detail.get("outcome") != "ok" or not isinstance(rows, list):
        _log.warning("[DEEP] %s", render_detail(detail, prefix="symbol list "))
        return None, detail, None
    syms = sorted({str(r.get("symbol") or "").upper()
                  for r in rows if r.get("symbol")})
    # `latest` hint — only available when the SQL actually returns it. Empty
    # list (no rows had it) is treated like None.
    latest_dates = [str(r.get("latest") or "")[:10]
                    for r in rows if r.get("latest")]
    latest_dates = [d for d in latest_dates if d]
    return syms, detail, (latest_dates or None)


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


async def _panel_frontier():
    """binance_hist 全体的最新 trade_date;读不到 ⇒ None(调用方退回默认窗口)。"""
    import os

    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return None
    url = (f"{base}/rest/v1/ohlcv_daily?select=trade_date&source=eq.binance_hist"
           f"&order=trade_date.desc&limit=1")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        rows = r.json() if r.status_code == 200 else []
        return datetime.strptime(str(rows[0]["trade_date"])[:10], "%Y-%m-%d").date() if rows else None
    except Exception as e:                                   # noqa: BLE001
        _log.warning("[DEEP] frontier read failed: %s", e)
        return None


async def collect_deep_panel(days: int | None = None,
                             symbols: list[str] | None = None) -> dict[str, Any]:
    """Refresh the deep panel. Idempotent; safe to run repeatedly.

    `days=None` ⇒ **窗口自己算**,见 `_HEAL_MAX_DAYS`。
    """
    from src.api.store import supabase_upsert_table

    _state_detail: dict = {}
    state = None
    if symbols is not None:
        syms = symbols
    else:
        # S-378b-C1: fast path is PRIMARY. The slow RPC
        # (`deep_panel_symbol_list`) aggregates over 386k rows and dies at
        # ~15s under contention (10s httpx timeout + overhead) — every loop
        # fires within 180s of process boot, so on a normal day the slow RPC
        # is the dominant cost. `deep_panel_symbols_fast` is the skip-scan
        # equivalent: 203ms / 793 buffers vs 1315ms / 2406 buffers. We use it
        # as the primary call.
        syms_fast, _state_detail, latest_hint = await deep_panel_symbols_detailed()
        if syms_fast is not None:
            syms = syms_fast
            # S-378b-C1 third return value: `latest_hint`. The fast RPC's SQL
            # doesn't return `latest` in production today, so this is None
            # and the heal window stays at the 14-day default. When the SQL
            # is upgraded to also return `latest` (cheap — same skip-scan),
            # `latest_hint` becomes a list of date strings; we synthesise a
            # `state`-shaped view here so the existing heal-window branch
            # just works without a third copy. **Why a hint and not a fresh
            # full state read:** re-reading the slow RPC for the dates would
            # re-pay the 15s timeout we just stopped paying.
            state = None
            if latest_hint:
                state = [{"latest": d} for d in latest_hint if d]
        else:
            # Fast path failed: only consult the slow path if we actually
            # need `latest` for the auto-heal window. We don't want a normal
            # loop to pay 15s for the price of a healing-feature we won't use.
            state_slow, _slow_detail = await deep_panel_state_detailed()
            if state_slow is None:
                # Both paths failed — keep the fast-path detail (it's the
                # shorter timeout and the more likely root cause).
                syms = None
            else:
                state = state_slow
                syms = sorted({str(r["symbol"]).upper() for r in state_slow
                               if r.get("symbol")})

    # 「没读到」和「读通了但是空的」分开报 —— 前者等下一轮,后者改配置。
    # 上一版这里是 `either Supabase is unreachable or binance_hist is empty`:
    # **一句话把两个修法完全不同的状态并列,读的人两边都不能动。**
    if syms is None:
        # S-323m:不再写死「RPC 不通/熔断/超时」这三个嫌疑人 —— 那句话里
        # 没有真凶的名字,而它把五轮诊断送回了作者当年的猜测。装观测。
        from src.api.rpc_diagnostics import render_detail
        return {"ok": False, "status": "error", "written": False,
                "symbols_total": None, "rows_upserted": 0,
                "rpc_detail": _state_detail,
                "error": render_detail(_state_detail,
                                       prefix="深盘符号表没读到 — ")}
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
        if not state:
            # S-415:快路径不返回 latest(见上面 S-378b-C1 注释),于是自愈窗口
            # 永远是 14 天 —— 而 2026-09-08 起的断档已经 15 天,**恢复的第一轮会在
            # 09-09 留下一个永远补不上的洞**。一个便宜的读补上 frontier:整个
            # binance_hist 的最新 bar(全体同日停更,所以全局 max 就是 frontier)。
            frontier = await _panel_frontier()
            if frontier:
                gap = (datetime.now(timezone.utc).date() - frontier).days + 2
                days = max(_DEFAULT_DAYS, min(gap, _HEAL_MAX_DAYS))
        if days > _DEFAULT_DAYS:
            _log.warning("[DEEP] healing window %sd (gap detected) — not the usual %sd",
                         days, _DEFAULT_DAYS)

    # ── S-323i: 这个扇出违反 source_policy,而 source_policy 就是为它写的 ──────
    #
    # `src/data/market/source_policy.py` 的开篇第一个例子,一字不改:
    #
    #     · `deep_panel_collector` — 262 symbols against Binance's free mirror.
    #       Result: one symbol reachable, panel dead for days (S-190).
    #
    # 而它的规则是 `fan-out over > BULK_THRESHOLD assets → a PAID source. Always.`,
    # 它的 `PURPOSE_SCOPE[market_data]` 写着「整个研究面板(262)—— **付费源**,
    # fan-out 是买来的权利」。**策略文件点名了这个采集器,而这个采集器从来没有
    # 调用过那个策略** —— 全文件 0 处 `source_policy`。
    #
    # Jazz 已经说过很多次(2026-09-05 记在 `_hyperliquid_loop` 的 docstring 里,
    # S-296 据此修好了 hyperliquid),而**同一个文件里隔 40 行的这个循环没有跟着改**。
    # 规则被当成一次事故的补丁执行了,没有被当成一条会自己巡查的策略。
    #
    # 2026-09-08 的实测后果:binance_hist 覆盖 **4/123**,而 docstring 第 28 行
    # 早就写着「262 symbols fired at once is a burst that gets an IP banned,
    # **and the ban would look exactly like the stale feed this replaces**」——
    # 塌陷不是待修的故障,**就是那个 ban**。
    #
    # ⚠️ 最难看的一条:S-323e 之前挡住这一切的,是 `deep_panel_symbol_list()`
    # 的 42501 权限错误。**那个「bug」是当时唯一在执行这条策略的东西**,
    # 而我花了五轮把它诊断成故障、然后修好了它 —— 等于亲手恢复了违规。
    # 所以拦截必须落在**代码里**,不能只落在 env 开关上:
    # 一个只靠 env 拦住的违规,下一个把 loop 判成「坏了」的人还会再打开一次。
    from src.data.market.source_policy import MARKET_DATA, assert_purpose_source
    assert_purpose_source(MARKET_DATA, "binance_hist", n_assets=len(syms),
                          job="deep panel daily bars",
                          secondary_ok=True)  # S-323n: 9 年历史续接,显式 secondary

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
    # S-415:**下架和故障是两个结果**(与 hyperliquid_collector S-204 同一个修法,
    # 那边修了,这边隔一个文件没跟上)。262 个符号里 123 个在 Binance 现货上
    # 根本不存在 —— 永续命名(1000SHIB)、已下架(AGIX)、HL 独有名。它们每一轮
    # 都回空,把覆盖率永久钉在 53%,70% 地板每轮都拒绝写入:binance_hist 自
    # 2026-09-08 起一行没进,**不是被限流,是被一个永久事实拖住**。
    # 地板的分母只数「能回答的」符号;回空的另报,不算失败。
    delisted = {s: e for s, e in failures.items() if e.startswith("empty")}
    errored = {s: e for s, e in failures.items() if s not in delisted}
    reachable = ok_n + len(errored)
    frac = ok_n / reachable if reachable else 0.0

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
    if all_rows and (frac < _MIN_OK_FRACTION or ok_n < _MIN_LIVE_SYMBOLS):
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
            "symbols_reachable": reachable, "symbols_delisted": len(delisted),
            "symbols_errored": len(errored),
            "rows_built": len(all_rows), "rows_upserted": 0, "written": False,
            "refused": True,
            "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
            "failure_sample": dict(list(errored.items())[:8]) or dict(list(failures.items())[:8]),
            "diagnosis": (
                f"only {ok_n}/{reachable} reachable symbols ({frac:.0%}, floor "
                f"{_MIN_OK_FRACTION:.0%}; live floor {_MIN_LIVE_SYMBOLS}); "
                f"{len(delisted)} delisted/unlisted not counted. Write REFUSED so "
                f"the gap stays visible rather than being papered over by a partial day."),
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
        "ok": bool(written) and frac >= _MIN_OK_FRACTION and ok_n >= _MIN_LIVE_SYMBOLS,
        "symbols_total": len(syms),
        "symbols_ok": ok_n,
        "symbols_failed": len(failures),
        "symbols_reachable": reachable,
        "symbols_delisted": len(delisted),
        "symbols_errored": len(errored),
        "ok_fraction": round(frac, 3),
        "rows_upserted": len(all_rows) if written else 0,
        "rows_built": len(all_rows),
        "written": written,
        "elapsed_s": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        # First few reasons, not a count. "12 failed" is not actionable;
        # "12 failed with HTTP 418" is.
        "failure_sample": dict(list(errored.items())[:8]),
        "delisted_sample": sorted(delisted)[:12],
    }
    if frac < _MIN_OK_FRACTION:
        out["diagnosis"] = (
            f"only {ok_n}/{reachable} reachable symbols returned data ({frac:.0%}, floor "
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
