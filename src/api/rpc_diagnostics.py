"""What the RPC call ACTUALLY did — not what we guessed it did (S-323m).

WHY THIS EXISTS. Measured across S-323 → S-323l, five consecutive rounds of
diagnosis, every one of them wrong, all misled by the same sentence:

    "深盘符号表**没读到**(RPC 不通/熔断/超时)"

That string is emitted by `main.py` when `deep_panel_symbols()` returns None.
It names three suspects — RPC, breaker, timeout — and the real cause across
those five rounds was, in order: a missing index, a cold PostgREST schema
cache, a 4xx recorded as breaker SUCCESS, a GRANT on a function whose name
appears nowhere in it, and finally a loop that was simply ASLEEP.

**The message was assembled from the hypotheses its author had at the time,
not from the response.** So it kept returning every reader — me, five times —
to that author's guesses. A message that enumerates guesses costs more than no
message at all: no message sends you to look at the response, that one
persuades you that you already have.

The real evidence existed the whole time. `store.py` logs status code and body
at WARNING and then throws them away:

    _logger.warning(f"[SUPABASE] rpc {fn} error {resp.status_code}: {resp.text[:120]}")

Nothing carries them to `_beat(error=...)`, so `/internal/data-freshness` — the
surface anyone actually reads — shows the guess and never the fact.

THE RULE THIS ENCODES. **A diagnostic field must carry an observation, never a
hypothesis.** If we do not know why something failed, the honest rendering is
the status code and the body, however unhelpful they look. A guess dressed as a
diagnosis is worse than "unknown", because "unknown" makes you go and measure.

Credit: Minimax-A reached this independently on 2026-09-09 while auditing the
whole project, and located it more precisely than I had — I had recorded the
symptom in the ledger four times without once fixing the layer that produced it.
"""
from __future__ import annotations

import json
import time
from typing import Any, Literal

__all__ = ["rpc_with_detail", "render_detail", "insert_with_detail",
           "_record_loop_attempt"]

#: S-408-2 (A-408-2). 闭环迭代 outcome 词汇,与 `_classify()` 返值 + 一个
#: loop-specific panel_unavailable 一一对齐。**字面冻结**,新增值必须:
#:   ① 在此处加 Literal 成员
#:   ② 在调用点映射
#:   ③ 在测试里覆盖
#: 否则 CI 静默(S-299 教训:未知 status 渲成 failing 比 loud fail 更糟)。
LoopOutcome = Literal["ok", "refused", "error", "panel_unavailable"]

#: 不记录对它自己的写入(loop_attempt 不会写 write_log,无递归路径,
#: 但保留同型常量便于后人理解)。
_LOOP_ATTEMPT_TABLE = "loop_attempt"


async def rpc_with_detail(fn_name: str,
                          payload: dict[str, Any] | None = None,
                          ) -> tuple[Any, dict[str, Any]]:
    """Call a PostgREST RPC and return `(data_or_None, detail)`.

    `detail` always says which of the mutually-exclusive outcomes happened, so
    a caller can render a fact instead of a list of suspects:

        not_configured  SUPABASE_URL / SUPABASE_KEY missing on this process
        breaker_open    short-circuited before any network call
        no_response     timeout, or all retries exhausted (None from the layer)
        http_error      the backend answered, and this is the code and the body
        not_json        HTTP 200 whose body would not parse
        ok              data returned

    These have DIFFERENT fixes — set a variable, wait for cooldown, look at the
    query plan, fix a grant, fix the payload — which is exactly why collapsing
    them into one None (and then into one sentence) cost five rounds.
    """
    from src.api import store

    detail: dict[str, Any] = {
        "fn": fn_name, "outcome": None, "status": None,
        "body": None, "elapsed_ms": None,
        # Breaker state at call time. Recorded because "the breaker did it" was
        # asserted repeatedly and was false every time; now it is observed.
        "breaker_open": None, "breaker_consecutive_failures": None,
        "breaker_lifetime_trips": None,
    }

    if not store._SB_URL or not store._SB_KEY:
        detail["outcome"] = "not_configured"
        return None, detail

    detail["breaker_open"] = bool(time.time() < store._cb_open_until)
    detail["breaker_consecutive_failures"] = store._cb_consecutive_failures
    detail["breaker_lifetime_trips"] = store._cb_trips

    url = f"{store._SB_URL}/rest/v1/rpc/{fn_name}"
    headers = {"apikey": store._SB_KEY,
               "Authorization": f"Bearer {store._SB_KEY}",
               "Content-Type": "application/json"}

    t0 = time.time()
    try:
        resp = await store._supabase_request_with_retry(
            "POST", url, json=(payload or {}), headers=headers)
    except Exception as e:                                      # noqa: BLE001
        detail["outcome"] = "exception"
        detail["body"] = f"{type(e).__name__}: {str(e)[:200]}"
        detail["elapsed_ms"] = int((time.time() - t0) * 1000)
        return None, detail
    detail["elapsed_ms"] = int((time.time() - t0) * 1000)

    if resp is None:
        # The layer already folds breaker-open / timeout / retries-exhausted
        # into one None. We cannot un-fold it from here, so we say which one it
        # WAS NOT: the breaker state was captured before the call.
        detail["outcome"] = "breaker_open" if detail["breaker_open"] else "no_response"
        return None, detail

    detail["status"] = resp.status_code
    if resp.status_code in (200, 204):
        try:
            data = resp.json()
        except Exception:                                       # noqa: BLE001
            detail["outcome"] = "not_json"
            detail["body"] = (resp.text or "")[:200]
            return None, detail
        detail["outcome"] = "ok"
        if isinstance(data, list):
            detail["n_rows"] = len(data)
        return data, detail

    # THE BODY IS THE POINT. PostgREST puts our own schema's message here —
    # "permission denied for function ohlcv_symbol_coverage" is the sentence
    # that would have ended this in round one.
    detail["outcome"] = "http_error"
    detail["body"] = (resp.text or "")[:300]
    return None, detail


def render_detail(detail: dict[str, Any], *, prefix: str = "") -> str:
    """One line, observation only. **Never append a suspected cause.**"""
    o = detail.get("outcome")
    fn = detail.get("fn", "?")
    ms = detail.get("elapsed_ms")
    took = f" [{ms}ms]" if ms is not None else ""
    cb = (f" breaker(open={detail.get('breaker_open')},"
          f"fails={detail.get('breaker_consecutive_failures')},"
          f"trips={detail.get('breaker_lifetime_trips')})")

    if o == "ok":
        return f"{prefix}{fn}: ok, {detail.get('n_rows', '?')} rows{took}"
    if o == "not_configured":
        return f"{prefix}{fn}: SUPABASE_URL/KEY not set on this process"
    if o == "breaker_open":
        return f"{prefix}{fn}: circuit breaker OPEN — no request was sent.{cb}"
    if o == "no_response":
        return (f"{prefix}{fn}: no response (timeout or retries exhausted)"
                f"{took}.{cb}")
    if o == "http_error":
        return (f"{prefix}{fn}: HTTP {detail.get('status')}{took} — "
                f"{detail.get('body')}")
    if o == "not_json":
        return (f"{prefix}{fn}: HTTP {detail.get('status')} but body is not JSON"
                f"{took} — {detail.get('body')}")
    if o == "exception":
        return f"{prefix}{fn}: {detail.get('body')}{took}"
    return f"{prefix}{fn}: outcome={o!r} (unrecognised — this is not success)"


#: 不记录对它自己的写入,否则一次失败会无限递归。
_WRITE_LOG_TABLE = "write_log"


def _caller() -> str:
    """谁在写 —— 回答「哪个模块尝试了」,而不只是「这张表被写了没有」(S-352)。

    跳过本模块和 store 的帧;取第一个真正的调用点。失败返回 "?" ——
    **一个问不出来的调用方是 "?",不是空字符串**,两者在下游读起来不一样。
    """
    try:
        import inspect
        for fr in inspect.stack()[2:8]:
            mod = fr.frame.f_globals.get("__name__", "")
            if mod and not mod.endswith(("rpc_diagnostics", "store")):
                return f"{mod}.{fr.function}"[:120]
    except Exception:                                           # noqa: BLE001
        pass
    return "?"


async def _record_attempt(detail: dict[str, Any], writer: str) -> bool:
    """把一次写入尝试落进 `write_log`。**绝不抛,绝不递归。**

    S-352。这一步存在的全部理由:在它之前,**写成功留下一行,写失败什么都不留**,
    于是「表里没有行」同时意味着「没人写过 / 写了失败 / 写到别处」三件事,
    而它们在库里完全同形 —— 这就是 Jazz 说的「写入没有写入完全是玄学」。

    ⚠️ 它自己失败时只能沉默(没有第二层日志可写)。代价写在这里而不是藏起来:
    那会在 write_log 里留下一个**洞**,而洞的表现是「某次尝试没有对应行」。
    所以 write_log 自己的新鲜度也必须被人看 —— 它不是一个免检的裁判。
    """
    if detail.get("table") == _WRITE_LOG_TABLE:
        return True                       # 按设计不记,不是记失败
    try:
        from src.api import store
        if not store._SB_URL or not store._SB_KEY:
            return False
        import httpx
        row = {
            "table_name": str(detail.get("table") or "?")[:120],
            "n_rows": int(detail.get("n_rows") or 0),
            "outcome": str(detail.get("outcome") or "?")[:40],
            "status": detail.get("status"),
            "body": (str(detail["body"])[:400] if detail.get("body") else None),
            "elapsed_ms": detail.get("elapsed_ms"),
            "writer": writer,
        }
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(
                f"{store._SB_URL}/rest/v1/{_WRITE_LOG_TABLE}",
                json=[row],
                headers={"apikey": store._SB_KEY,
                         "Authorization": f"Bearer {store._SB_KEY}",
                         "Content-Type": "application/json",
                         "Prefer": "return=minimal"})
        return r.status_code in (200, 201, 204)
    except Exception:                                           # noqa: BLE001
        return False


async def _record_loop_attempt(loop_name: str,
                               outcome: LoopOutcome,
                               reason: str | None = None,
                               *,
                               elapsed_ms: int | None = None,
                               detail: dict[str, Any] | None = None,
                               writer: str | None = None,
                               ) -> bool:
    """把一次循环迭代落进 `loop_attempt`(S-408-2 / A-408-2)。

    与 `_record_attempt` 同骨架:try-hard, **绝不抛**, 吞所有异常返 bool。
    它自己失败没有第二层日志可写 —— 同 S-352,docstring 写一次:
    `loop_attempt` 自己的健康必须被人看(`loop_attempt_health(loop_name)`),
    不能免检。

    `writer` 显式传入。**不**内部调 `_caller()`,因为循环主体内的栈帧不稳
    (`_asyncio.create_task` 展开后 `_caller()` 会落在不预期的帧上),显式
    字符串比 inspect-stack 推断更稳更便宜。
    """
    try:
        from src.api import store
        if not store._SB_URL or not store._SB_KEY:
            return False
        import httpx
        # build_sha 同源 inline (S-341c mypy scope doctrine: 不从 loop_beat 跨模块
        # import 拉宽 two-file strict 范围)。4 行 env 查找,值得避免一个跨模块耦合。
        import os as _os
        _build = (_os.environ.get("RAILWAY_GIT_COMMIT_SHA")
                  or _os.environ.get("GIT_COMMIT_SHA")
                  or _os.environ.get("SOURCE_COMMIT")
                  or "")[:8]
        row = {
            "loop_name":  str(loop_name)[:120],
            "outcome":    str(outcome)[:40],
            "reason":     (str(reason)[:400] if reason else None),
            "elapsed_ms": int(elapsed_ms) if elapsed_ms is not None else None,
            "detail":     detail,
            "writer":     (writer or _caller())[:120],
            "build":      _build,
        }
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(
                f"{store._SB_URL}/rest/v1/{_LOOP_ATTEMPT_TABLE}",
                json=[row],
                headers={"apikey": store._SB_KEY,
                         "Authorization": f"Bearer {store._SB_KEY}",
                         "Content-Type": "application/json",
                         "Prefer": "return=minimal"})
        return r.status_code in (200, 201, 204)
    except Exception:                                           # noqa: BLE001
        return False


def log_write_attempt(fn: Any) -> Any:
    """装饰 `store.py` 里返回 `StoreResult` 的写入函数,让每次尝试落进 `write_log`(S-352)。

    为什么是装饰器而不是改函数体。`store.py` 是 Minimax-A 当前的活跃面
    (S-341a/b/c,而且已经上了 `mypy --strict`),所以这里只留 4 行足迹:
    两个 import + 两个 `@`。实现留在本模块(Seth lane)。

    为什么必须覆盖这两个。实测调用点分布:`insert_with_detail` 10 处、
    `supabase_insert_table` 16 处、`supabase_upsert_table` 10 处。
    **只包第一个 = 覆盖 10/36,而 `write_log` 会看起来是满的** ——
    那正好是这张表要消灭的那种错觉。

    表名取第一个位置参数,这是这两个函数共同的签名约定。
    """
    import functools

    @functools.wraps(fn)
    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        res = await fn(*args, **kwargs)
        try:
            table = str(args[0]) if args else str(kwargs.get("table", "?"))
            n_rows = len(args[1]) if len(args) > 1 and hasattr(args[1], "__len__") else 0
            ok = bool(getattr(res, "ok", False))
            why = str(getattr(res, "why", "") or "")
            await _record_attempt({
                "table": table, "n_rows": n_rows,
                # StoreResult 没有分 outcome 类型 —— 有 `.why` 就照抄,
                # **不把它归类**(S-323m:装观测不装假设)。
                "outcome": "ok" if ok else "store_result_fail",
                "status": None, "body": (None if ok else why[:400]),
                "elapsed_ms": None,
            }, _caller())
        except Exception:                                       # noqa: BLE001
            pass                                                # 记录失败不能改变写入结果
        return res

    return _wrapped


async def insert_with_detail(table: str,
                             rows: list[dict[str, Any]],
                             on_conflict: str | None = None,
                             ) -> tuple[bool, dict[str, Any]]:
    """Insert rows and return `(ok, detail)`,并把这次尝试记进 `write_log`(S-328/S-352)。

    S-352 加的那一半:`detail` 早就算出了 outcome/status/body/elapsed,**算完就扔**。
    现在每一个 return 之前先落一行 —— 成功和失败都落。
    **「表里没有行」和「没人尝试过」从此是两个可区分的事实。**

    `on_conflict` (S-389 FIX-A, 2026-09-21): when set, the writer is UPSERT not
    INSERT — URL gains `?on_conflict=<value>` and Prefer gains
    `resolution=merge-duplicates`. The retry/re-run on the same primary key
    returns 200/201/204 instead of HTTP 409 (Postgres 23505), so the second
    write silently merges into the existing row. The nine other books that
    don't pass `on_conflict` keep the insert path unchanged.
    """
    ok, detail = await _insert_with_detail_inner(table, rows, on_conflict=on_conflict)
    # ⚠️ 记录器必须自报。`_record_attempt` 吞掉所有异常(它没有第二层日志可写),
    # 所以如果它从来没成功过,`write_log` 会是空的 —— 而空 = 「没人尝试过」,
    # **正好是最错的那个结论**。那样这个修复就带着它要修的故障模式。
    # `logged` 让它一路走到 `/internal/write-probe` 的返回里:**记录器坏了看得见**。
    detail["logged"] = await _record_attempt(detail, _caller())
    return ok, detail


async def _insert_with_detail_inner(table: str,
                                    rows: list[dict[str, Any]],
                                    on_conflict: str | None = None,
                                    ) -> tuple[bool, dict[str, Any]]:
    """原逻辑,七个 return 点不动 —— 记录发生在外层,所以每一条路径都被覆盖。

    WHY. `supabase_insert_table` returns a bare bool, and `nav_persist` says so
    itself: it "returns False for a role refusal, missing credentials, an empty
    payload AND a transport error. It does not say which, so neither do we."

    Measured 2026-09-11: ① reported `durable_write_failed` every day and the
    cause could not be determined from outside — the status code and body exist
    only in a Railway log line that nothing surfaces. Five other books hid the
    same failure entirely behind a cached `already_marked` (S-327).

    Same collapse as the RPC path before S-323m, one layer over. This returns
    the status and the PostgREST body, which is the sentence that names the
    cause.

    `on_conflict` (S-389 FIX-A): when set, the request becomes an UPSERT
    (`?on_conflict=<value>` + Prefer `resolution=merge-duplicates`) so retries
    on a unique-keyed table like `fusion_paper_nav(mark_date)` succeed instead
    of 409-ing. PostgREST's own contract: prefer-resolution=merge-duplicates
    is the upsert switch; without it the same URL is plain insert.
    """
    from src.api import store

    detail: dict[str, Any] = {
        "table": table, "n_rows": len(rows or []), "outcome": None,
        "status": None, "body": None, "elapsed_ms": None,
        "role_refusal": None,
        "on_conflict": on_conflict,                              # S-389
    }
    if not table or not rows:
        detail["outcome"] = "empty_payload"
        return False, detail

    # The role gate first — it is the one cause that never reaches the network,
    # and reporting it as a transport failure sends the reader to the wrong lane.
    try:
        from src.api.runtime_role import refuse_write
        refusal = refuse_write(table)
    except Exception:                                           # noqa: BLE001
        refusal = None
    if refusal:
        detail["outcome"] = "role_refusal"
        detail["role_refusal"] = str(refusal)[:300]
        return False, detail

    if not store._SB_URL or not store._SB_KEY:
        detail["outcome"] = "not_configured"
        return False, detail

    url = f"{store._SB_URL}/rest/v1/{table}"
    if on_conflict:
        url = f"{url}?on_conflict={on_conflict}"
    headers = {"apikey": store._SB_KEY,
               "Authorization": f"Bearer {store._SB_KEY}",
               "Content-Type": "application/json",
               "Prefer": ("return=minimal,resolution=merge-duplicates"
                          if on_conflict else "return=minimal")}
    t0 = time.time()
    try:
        resp = await store._supabase_request_with_retry(
            "POST", url, content=json.dumps(rows), headers=headers)
    except Exception as e:                                      # noqa: BLE001
        detail["outcome"] = "exception"
        detail["body"] = f"{type(e).__name__}: {str(e)[:200]}"
        detail["elapsed_ms"] = int((time.time() - t0) * 1000)
        return False, detail
    detail["elapsed_ms"] = int((time.time() - t0) * 1000)

    if resp is None:
        detail["outcome"] = "no_response"
        detail["breaker_open"] = bool(time.time() < store._cb_open_until)
        return False, detail

    detail["status"] = resp.status_code
    if resp.status_code in (200, 201, 204):
        detail["outcome"] = "ok"
        return True, detail

    # THE BODY IS THE POINT — PostgREST puts our own schema's message here.
    detail["outcome"] = "http_error"
    detail["body"] = (resp.text or "")[:400]
    return False, detail
