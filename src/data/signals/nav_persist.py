"""The one place a paper book's NAV row gets written, and the write gets CHECKED (S-214).

WHY THIS EXISTS. `pod_aggregator_paper.py` and `factor_tilt_paper.py` each declared
`NAV_TABLE = "..."` and never wrote to it. Both constants had been in the code for
weeks; both tables held 0 rows; both books were marking NAV into their *state* row
and reporting `status: ok`. Minimax-A found it by reading the tables, not the code
— from inside the process everything looked healthy, because the only thing that
was missing was a call nobody had written.

A constant naming a table is a PROMISE. `pod_aggregator_nav` existed, was migrated,
was documented, and was never once written to. That is worse than not having the
table: an empty table reads as "the strategy produced nothing", which is a result,
and it was never a result — it was an absent line of code.

THE DECISION, since it was mine and I deferred it three times. Add the writers, do
not delete the constants. A book that marks is FALSIFIABLE — sixty days of rows can
condemn it. A book that does not mark is neither alive nor dead, and CLAUDE.md is
explicit that the graveyard is the asset. You cannot bury something that never had
a pulse.

AND THE WRITE IS CHECKED. `supabase_insert_table` returns a bool and five paper
books throw it away (task #33). A discarded False is how a book reports `status: ok`
while persisting nothing — the same miss-vs-error collapse as S-180, one layer up.
So this returns a result the caller must place in its payload, and the endpoint
shows `nav_persisted: false` with a reason rather than a cheerful `ok`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

_log = logging.getLogger("nav_persist")


@dataclass(frozen=True)
class NavWrite:
    """Outcome of one NAV row write. Three-valued, like every other read this month."""

    ok: bool
    table: str
    reason: str = ""

    def as_payload(self) -> dict[str, Any]:
        """What the endpoint shows. `nav_persisted` is a fact, not an aspiration."""
        out: dict[str, Any] = {"nav_persisted": self.ok, "nav_table": self.table}
        if not self.ok:
            # A failure with no reason is indistinguishable from one nobody looked
            # at, so the reason travels with the flag rather than to a log file.
            out["nav_persist_error"] = self.reason or "unknown"
        return out


async def write_nav_row(table: str, row: Mapping[str, Any]) -> NavWrite:
    """Insert one NAV row. Never raises; the caller must surface the result.

    Deliberately NOT silent-on-failure and NOT fire-and-forget. The whole defect
    class this module closes is a write that did not happen and did not say so.
    """
    if not table:
        return NavWrite(False, table or "?", "no table configured")
    if not row or row.get("mark_date") is None:
        # A NAV row without its date cannot be deduplicated or ordered, so it is
        # not a mark — it is a number in a table.
        return NavWrite(False, table, "row has no mark_date")

    # ⚠️ S-329:这里原来调 `supabase_insert_table`,拿到一个**裸 bool**,
    # 然后照实说「不知道是哪一种」。那句话是诚实的,但代价是:
    # 2026-09-11 ① 每天报 `durable_write_failed`,而真因(状态码 + PostgREST
    # 的原话)只存在于一行没人读的 Railway 日志里 —— 我们花了一整轮排除法,
    # 逐个否掉 role gate / schema drift / 早退 / 204,才把它缩到「瞬时」。
    #
    # `insert_with_detail` 是 S-323m 那个 `(data, detail)` 模式搬到写路径:
    # **同一把 key、同一组 header、同一层重试、同一个 role gate**,
    # 但把互斥的结局分开报,并带回 body。Minimax-A 在 §PHASE-B 里独立提了同一条。
    #
    # **原因装观测,不装假设。** 下一次失败会自己说出它是谁。
    try:
        from src.api.rpc_diagnostics import insert_with_detail
    except Exception as e:                                        # noqa: BLE001
        return NavWrite(False, table, f"diagnostics import failed: {type(e).__name__}")

    try:
        ok, detail = await insert_with_detail(table, [dict(row)])
    except Exception as e:                                        # noqa: BLE001
        _log.warning("[NAV] %s write raised: %s", table, e)
        return NavWrite(False, table, f"{type(e).__name__}: {str(e)[:120]}")

    if not ok:
        outcome = detail.get("outcome")
        # Each of these has a DIFFERENT owner. Collapsing them is what made
        # durable_write_failed undiagnosable from outside.
        if outcome == "role_refusal":
            why = f"role gate refused: {detail.get('role_refusal')}"
        elif outcome == "not_configured":
            why = "SUPABASE_URL / SUPABASE_KEY not set on this process"
        elif outcome == "no_response":
            why = (f"no response after retries [{detail.get('elapsed_ms')}ms]"
                   f"{' — breaker OPEN' if detail.get('breaker_open') else ''}")
        elif outcome == "http_error":
            why = (f"HTTP {detail.get('status')} — {detail.get('body')}")
        else:
            why = f"outcome={outcome!r} (unrecognised — NOT success)"
        _log.warning("[NAV] %s write failed: %s", table, why)
        return NavWrite(False, table, why)

    _log.info("[NAV] %s ← %s", table, row.get("mark_date"))
    return NavWrite(True, table)


async def nav_row_exists(table: str, day: str) -> bool | None:
    """Is there a row for `day` in `table`? **Three-valued: True / False / None.**

    S-321 discovered this on `factor_tilt_nav` / `pod_aggregator_nav`: both were
    0 rows for weeks while every run returned `already_marked_today`, because
    the check asked Redis state and never asked the table.

    > **「我记得我做过」和「它确实在那里」是两个状态。**
    > Whether to skip is a judgement about the SECOND one, so ask the second one.

    ⚠️ S-327: that fix was written into the two books being debugged at the time
    and into NO others, and it was copy-pasted rather than shared — two private
    `_row_exists_for` definitions, in two files. Measured 2026-09-11: five book
    loops reported `ok` with zero consecutive failures for two days while their
    NAV tables had not grown since 09-09, because `already_marked` sits in
    `PROGRESS_STATUS` and was being returned on the strength of state alone.

    **A lesson applied to the call sites that broke, and not to the class, is a
    lesson that will be re-learned by the next call site.**

    `None` means we could not read the table. Callers **must not** treat it as
    True: 读不到 ≠ 已经写过, and re-marking is idempotent while a silently
    skipped day is not recoverable (§3).
    """
    if not table or not day:
        return None
    try:
        import httpx

        from src.api.store import _SB_KEY, _SB_URL
        if not _SB_URL or not _SB_KEY:
            return None
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{_SB_URL}/rest/v1/{table}"
                f"?select=mark_date&mark_date=eq.{day}&limit=1",
                headers={"apikey": _SB_KEY,
                         "Authorization": f"Bearer {_SB_KEY}"})
        if r.status_code != 200:
            _log.warning("[NAV] %s existence check HTTP %s — returning None, "
                         "which the caller must NOT read as 'already written'",
                         table, r.status_code)
            return None
        return bool(r.json())
    except Exception as e:                                        # noqa: BLE001
        _log.warning("[NAV] %s existence check raised: %s", table, e)
        return None


async def nav_table_has_any_rows(table: str) -> bool | None:
    """Has this book EVER marked? **Three-valued: True / False / None** (S-336).

    THE QUESTION THIS ANSWERS, and why it needs its own function. When a book
    loads empty state, `weights` is `{}` — and S-326 recorded that `{}` has two
    sources with opposite remedies:

        ① the book holds nothing BY DESIGN      → mark a flat day (arithmetic)
        ② the state could not be read           → refuse (a flat mark is a lie)

    `mark_coverage.weighted_mark` cannot separate them and therefore refuses,
    which is correct at that layer and is why `two_layer` has not marked since
    2026-08-22. The comment there says the split belongs to the CALLER.

    This is the fact the caller needs. A book whose table is empty and whose
    state is empty is at a genuine inception — nothing was lost, mark flat at
    NAV 1.0. A book whose table HAS rows and whose state is empty has lost its
    position: it held something yesterday and cannot say what. Those are the two
    cases, and only the table can tell them apart.

    Measured 2026-09-12 on `fusion_paper_nav`: 26 rows, every one NAV 0.9995,
    `daily_return` exactly `-cost`, NAV never compounding — 26 marks produced by
    case ② and recorded as case ①. `_load_state`'s own docstring already named
    this at 5 marks (S-176) and the remedy chosen then was a Supabase fallback,
    which makes the failure less LIKELY without making it VISIBLE.

    `None` means we could not read. Callers must not read it as False: "I could
    not check whether this book has history" is not "this book has no history",
    and treating it as inception would reset a live NAV to 1.0.
    """
    if not table:
        return None
    try:
        import httpx

        from src.api.store import _SB_KEY, _SB_URL
        if not _SB_URL or not _SB_KEY:
            return None
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{_SB_URL}/rest/v1/{table}?select=mark_date&limit=1",
                headers={"apikey": _SB_KEY,
                         "Authorization": f"Bearer {_SB_KEY}"})
        if r.status_code != 200:
            _log.warning("[NAV] %s history check HTTP %s — returning None, which "
                         "the caller must NOT read as 'never marked'",
                         table, r.status_code)
            return None
        return bool(r.json())
    except Exception as e:                                        # noqa: BLE001
        _log.warning("[NAV] %s history check raised: %s", table, e)
        return None
