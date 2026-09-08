"""
The forward records must keep marking, and must say so when they stop (S-175).

TWO JOBS, ONE CAUSE.

  1. WIND THE CLOCK. `refresh_depth_divergence()` and `resolve_depth_divergence()`
     were created 2026-08-18 (S-173) and had ZERO callers. Measured the next day:
     the only two mentions of the function name in the whole repo were a test
     docstring and a preflight comment — both describing it, neither running it.
     The two rows in `depth_divergence_log` were written by hand from a SQL
     console.

     That is the same defect S-173's own ledger entry was about, committed by its
     author, one day later. Worth stating plainly rather than quietly fixing: the
     failure mode is not ignorance of the rule. **Building the thing feels like
     finishing it, and a scheduler disagrees.**

  2. PAGE WHEN A BOOK STOPS. The ① book went 5 days without a mark
     (2026-08-12 → 08-17, production was read-only under an unset APP_ROLE) and
     nothing said anything. `/internal/beta-core-clock` reported it accurately
     the whole time — `marks: 0, started: false` — to nobody, because a status
     endpoint only speaks when asked.

     A 60-day forward commitment that silently skips 5 days is not a 55-day
     record with a gap; **it is a record whose gaps you now have to argue were
     accidental.** The whole value of the ① book is that an LP can check it, and
     an unexplained hole is exactly what they will check.

WHY BOTH LIVE IN ONE LOOP. They are the same guarantee seen from two sides:
something must write the record, and something must shout when the record stops
growing. Splitting them into two loops means the day the shouting loop dies, the
writing loop keeps looking healthy — one more monitor inside the failure domain
it monitors (S-92).

ALERTS ARE RATE-LIMITED, NOT DEDUPLICATED AWAY. A book that has been dead for a
week should not send 7 identical pages, but it must not go quiet either: after
the first alert the cadence drops to one per day, so the channel stays honest
without becoming noise. An always-on warning carries no information (S-105); so
does an alarm that fires once and gives up.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

_log = logging.getLogger("forward_record")

# A book that has not marked in more than this many days is broken, not quiet.
# 1 = "yesterday's mark is missing". Deliberately tight: the ① book marks daily,
# so the first missed day IS the signal. Waiting for 3 would have turned the
# 5-day outage into a 3-day one, which is not a fix.
MAX_SILENT_DAYS = 1

# After the first page, at most one per 24h for the same book.
_ALERT_COOLDOWN_S = 24 * 3600
_last_alert: dict[str, float] = {}


async def _page(key: str, text: str) -> bool:
    """Send once, then at most daily for the same key."""
    import time
    now = time.time()
    last = _last_alert.get(key, 0.0)
    if now - last < _ALERT_COOLDOWN_S:
        _log.info("[FWD] %s still bad, page suppressed (cooldown)", key)
        return False
    _last_alert[key] = now
    try:
        from src.api.notify import notify_telegram
        ok = await notify_telegram(text)
    except Exception as e:                                   # noqa: BLE001
        _log.warning("[FWD] page failed to send: %s", e)
        ok = False
    # Log the alert text regardless. If Telegram is unconfigured the alert must
    # still exist somewhere — otherwise the alarm has the same failure mode as
    # the thing it watches.
    _log.warning("[FWD] ALERT%s: %s", "" if ok else " (not delivered)", text)
    return ok


async def refresh_depth_divergence_log() -> dict[str, Any]:
    """Job 1: write today's observations, then resolve anything 20 days due."""
    from src.api.store import supabase_rpc_write

    out: dict[str, Any] = {"written": None, "resolved": None, "problems": []}

    ok, res = await supabase_rpc_write("refresh_depth_divergence", {})
    if ok:
        out["written"] = res
    else:
        out["problems"].append(f"refresh: {res}")

    ok2, res2 = await supabase_rpc_write("resolve_depth_divergence", {})
    if ok2:
        out["resolved"] = res2
    else:
        out["problems"].append(f"resolve: {res2}")

    # Negative codes are REFUSALS, not row counts. The SQL side fails closed
    # rather than writing a day whose coverage has collapsed, because a forward
    # record containing 2-row days is one whose sample size nobody can state.
    # Measured 2026-08-19: the default target is the panel's max(trade_date),
    # and the asset classes update on different clocks — Crypto (262 symbols) was
    # 11 days behind five small classes, so "the latest day" had 2 symbols in it.
    w = out["written"]
    if w == -1:
        out["problems"].append(
            "refresh REFUSED: panel coverage for the latest date is under the 50% "
            "floor. The feed is stale, not the market quiet — check which asset "
            "class stopped collecting before overriding with an explicit date.")
    elif w == -2:
        out["problems"].append("refresh REFUSED: no panel data at all")
    elif w == 0:
        out["problems"].append(
            "refresh wrote 0 rows — the panel has no data for the target date")

    if out["problems"]:
        _log.warning("[FWD] depth_divergence: %s", "; ".join(out["problems"]))
    else:
        _log.info("[FWD] depth_divergence: %s written, %s resolved",
                  out["written"], out["resolved"])
    return out


async def check_book_continuity() -> list[dict[str, Any]]:
    """Job 2: page if any forward book has stopped marking.

    Reads the books' own tables rather than the clock endpoints. An endpoint can
    report healthily off a cached value; the table is where the record either
    exists or does not.
    """
    from src.api.store import supabase_rpc_write  # noqa: F401  (role gate parity)
    from src.api.store import _SB_URL, _SB_KEY    # noqa

    books = [
        ("beta_core_nav", "mark_date", "① beta-core book"),
        ("depth_divergence_log", "d", "depth-divergence forward record"),
    ]
    results: list[dict[str, Any]] = []

    for table, col, label in books:
        age = await _days_since(table, col)
        row = {"book": label, "table": table, "days_since_mark": age}
        if age is None:
            # THIRD STATE. "could not read" is not "healthy" and is not "dead".
            row["status"] = "unknown"
            _log.warning("[FWD] %s: could not read %s.%s — continuity UNKNOWN, "
                         "not assumed fine", label, table, col)
        elif age > MAX_SILENT_DAYS:
            row["status"] = "stalled"
            await _page(table,
                        f"🔴 {label} has not marked in {age} day(s).\n"
                        f"A 60-day forward commitment with an unexplained gap is "
                        f"not a shorter record — it is a record whose gaps have to "
                        f"be argued for. Check /health .writes first: production "
                        f"ran read-only for 5 days in August under an unset "
                        f"APP_ROLE and this exact silence was the symptom.")
        else:
            row["status"] = "ok"
        results.append(row)

    return results


async def _days_since(table: str, col: str) -> int | None:
    """Days since the newest row. None when unreadable — never 0, never a guess."""
    from src.api.store import _SB_URL, _SB_KEY, _supabase_request_with_retry
    if not _SB_URL or not _SB_KEY:
        return None
    url = f"{_SB_URL}/rest/v1/{table}?select={col}&order={col}.desc&limit=1"
    try:
        resp = await _supabase_request_with_retry(
            "GET", url, headers={"apikey": _SB_KEY,
                                 "Authorization": f"Bearer {_SB_KEY}"})
        if not resp or resp.status_code != 200:
            return None
        rows = resp.json()
        if not rows:
            return None
        raw = str(rows[0][col])[:10]
        return (date.today() - date.fromisoformat(raw)).days
    except Exception:                                        # noqa: BLE001
        return None


#: SHIP 门槛(CLAUDE.md「≥60d 纸面交易」)。**这个数不在这里定义,
#: 它在 tests/test_strategy_discipline.py 里被强制;这里只是引用它的值。**
FORWARD_RECORD_MIN_DAYS = 60

ACCRUING, QUALIFIED, GAPPED, NOT_DAILY = (
    "accruing", "qualified", "gapped", "not_daily")


async def evaluate_forward_record() -> dict[str, Any]:
    """Job 3:**对记录本身下判断**,每一轮,不等人来问 (S-315).

    ## 这条边缺了什么

    我们有两样东西,而它们之间是断的:

        check_book_continuity()   ① **有没有在标记**（活性）
        get_curve()               ① 的曲线 —— **只在被请求时计算**

    而本模块自己的 docstring 早就写过那句话:*"the ① book went 5 days without
    a mark in August while `/internal/beta-core-clock` reported that accurately
    to nobody, **because a status endpoint only speaks when asked**."*

    > **一条可以 fetch 的曲线不是闭环。** Sense → Judge → Act → Learn 里,
    > Learn 是那条**回来的**边,而「有人访问时才算」不是一条边。

    所以这里按时算一次,并给出一个**判决**,而不是一堆数字。

    ## 判决的门槛就是 SHIP 的门槛

    CLAUDE.md 要求任何 SHIP 裁决前 **≥60 天纸面**。那正是「能不能上实盘」
    的前提,而在此之前**从来没有任何东西自动算过它** —— 每次都是有人去问。

        accruing   < 60 天，正常累积中（**不是故障**）
        qualified  ≥ 60 天、无缺口、确为日频
        gapped     span 内有缺日 —— 告警原话:「一个有无法解释缺口的 60 天
                   前向承诺不是一段更短的记录，是一段缺口需要被论证的记录」
        not_daily  interval_hours 越界（S-283：10.6h–35.9h 曾经出现过）

    **缺口与天数是两个维度。** 一段 70 天里缺 6 天的记录,不是 64 天的记录 ——
    它是一段需要解释的记录,而把它报成 64 天正是在替它解释。
    """
    from src.api.store import _SB_KEY, _SB_URL

    out: dict[str, Any] = {"verdict": "unknown", "n_days": None}
    if not _SB_URL or not _SB_KEY:
        out["reason"] = "Supabase 未配置 —— **未测,不是合格**"
        return out
    try:
        import httpx
        from src.data.signals.beta_core_paper import _INCEPTION_ID
        url = (f"{_SB_URL}/rest/v1/beta_core_nav"
               f"?select=mark_date,nav,benchmark_nav,interval_hours"
               f"&inception_id=eq.{_INCEPTION_ID}&void_reason=is.null"
               f"&order=mark_date.asc")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, headers={"apikey": _SB_KEY,
                                          "Authorization": f"Bearer {_SB_KEY}"})
        rows = r.json() if r.status_code == 200 else None
    except Exception as e:                                      # noqa: BLE001
        out["reason"] = f"读不到 beta_core_nav:{type(e).__name__} —— **读不到 ≠ 没有记录**"
        return out
    if rows is None:
        out["reason"] = "beta_core_nav 读取非 200 —— **未测,不是合格**"
        return out
    if not rows:
        out.update(verdict=ACCRUING, n_days=0,
                   reason="当前 inception 下还没有任何一行 —— 记录从 0 开始")
        return out

    from datetime import date as _date
    days = [_date.fromisoformat(str(x["mark_date"])[:10]) for x in rows]
    span = (days[-1] - days[0]).days + 1
    n = len(set(days))
    gaps = span - n                       # span 内缺了几个日历日

    ivs = [x.get("interval_hours") for x in rows if x.get("interval_hours") is not None]
    off = [h for h in ivs if not (20.0 <= h <= 28.0)]

    cum = float(rows[-1]["nav"]) - 1.0
    bcum = float(rows[-1]["benchmark_nav"]) - 1.0

    if off:
        verdict = NOT_DAILY
    elif gaps > 0:
        verdict = GAPPED
    elif n >= FORWARD_RECORD_MIN_DAYS:
        verdict = QUALIFIED
    else:
        verdict = ACCRUING

    out.update(
        verdict=verdict, n_days=n, span_days=span, n_gaps=gaps,
        inception=_INCEPTION_ID,
        cum_return=round(cum, 6), benchmark_return=round(bcum, 6),
        # ① 的职责是吃到 beta,所以它的 outcome 是**跟踪差**,不是绝对收益。
        tracking_diff=round(cum - bcum, 6),
        days_to_threshold=max(0, FORWARD_RECORD_MIN_DAYS - n),
        n_off_interval=len(off),
        reason=(
            f"inception {_INCEPTION_ID} · {n} 天"
            + (f"(span {span} 天,**缺 {gaps} 天**)" if gaps else "")
            + f" · 累计 {cum:+.2%} vs 基准 {bcum:+.2%} · 跟踪差 {cum - bcum:+.2%}"
            + (f" · **{len(off)} 次间隔越界**" if off else "")
            + (f" · 距 {FORWARD_RECORD_MIN_DAYS} 天门槛还差 "
               f"{FORWARD_RECORD_MIN_DAYS - n} 天" if verdict == ACCRUING else "")
            + ("。**缺口需要被论证,不能当成一段更短的记录**" if gaps else "")),
    )
    return out


async def check_pit_lag() -> dict[str, Any]:
    """Job 4:**今天的 bar 今天在不在库里** (S-319)。

    ## S-207 的第二个 blocker,以及它为什么悄悄消失了

    S-207(2026-08 月中)写下:

    > *"PIT 必须卡 `recorded_at`,不是 `trade_date`:`ohlcv_daily.binance_hist` 的
    > recorded_at 中位数比 trade_date 晚 **28.2 天**。所以 marks 那半边现在
    > 做不了重放 —— 价格当时不在库里。**「会不会触发」可答,「NAV 多少」不可答。**"*

    2026-09-08 实测,`coingecko_pro_ohlc` 自 09-05 起 **lag = 0 天**:
    今天的 bar 今天就在库里。**那句「不可答」从三天前起不再成立** ——
    而没有任何东西注意到,因为没有任何东西在查。

    > **我们卡了好多天的不是工程,是我们对工程状态的记忆。**

    ⚠️ **不要过度声称。** 历史那 70 天的滞后写在旧行里,补不回来。
    变的是**前向**:从 09-05 起每一天都是 PIT 干净的,而前向恰好是
    ARCHITECTURE.md 说的那个产品。

    ## 所以这条必须被持续检查

    滞后不是一次性修好的属性,它是**循环还在按时跑**的副产品。
    循环一停,滞后立刻回来,而 `max(trade_date)` 上完全看不出来 ——
    与 S-190 的洞同形。所以每轮量一次,进心跳。
    """
    from src.api.store import _SB_KEY, _SB_URL

    out: dict[str, Any] = {"verdict": "unknown", "lag_days": None}
    if not _SB_URL or not _SB_KEY:
        out["reason"] = "Supabase 未配置 —— **未测,不是合格**"
        return out
    try:
        import httpx
        from datetime import date as _date
        url = (f"{_SB_URL}/rest/v1/ohlcv_daily"
               f"?select=trade_date,recorded_at&source=eq.coingecko_pro_ohlc"
               f"&order=trade_date.desc&limit=400")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, headers={"apikey": _SB_KEY,
                                          "Authorization": f"Bearer {_SB_KEY}"})
        rows = r.json() if r.status_code == 200 else None
    except Exception as e:                                      # noqa: BLE001
        out["reason"] = f"读不到:{type(e).__name__} —— **读不到 ≠ 滞后为 0**"
        return out
    if not rows:
        out["reason"] = "coingecko_pro_ohlc 没有行 —— 面板源停了"
        return out

    newest = max(str(x["trade_date"])[:10] for x in rows)
    first_seen = min(str(x["recorded_at"])[:10] for x in rows
                     if str(x["trade_date"])[:10] == newest)
    lag = (_date.fromisoformat(first_seen) - _date.fromisoformat(newest)).days
    out.update(
        newest_bar=newest, first_written=first_seen, lag_days=lag,
        # 0–1 天是 PIT 干净的(时区边界允许 1 天)。
        verdict="pit_clean" if lag <= 1 else "lagging",
        reason=(f"最新 bar {newest},首次写入 {first_seen},滞后 {lag} 天"
                + ("(**PIT 干净** —— marks 可重放)" if lag <= 1 else
                   f"(**滞后 {lag} 天 ⇒ marks 不可重放**,S-207 的那个 blocker "
                   f"回来了;循环停了或者源换了)")),
    )
    return out


async def run_once() -> dict[str, Any]:
    """One full pass. Safe to call from a loop, a startup hook, or by hand."""
    started = datetime.now(timezone.utc).isoformat()
    log = await refresh_depth_divergence_log()
    books = await check_book_continuity()
    record = await evaluate_forward_record()          # S-315: Learn 的那条边
    pit = await check_pit_lag()                       # S-319: S-207 的第二个 blocker
    stalled = [b["book"] for b in books if b["status"] == "stalled"]
    unknown = [b["book"] for b in books if b["status"] == "unknown"]
    return {
        "ran_at": started,
        "depth_divergence": log,
        "books": books,
        "forward_record": record,
        "pit_lag": pit,
        "stalled": stalled,
        "unknown": unknown,
        "ok": not stalled and not unknown and not log["problems"],
    }
