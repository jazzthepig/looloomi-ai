"""Force-mark primitive for the 9 daily paper books (A-21's vault-tick pattern).

THE 24H FEEDBACK LOOP WAS THE BUG. Every paper-book fix this week went unverified for
~24h because `beta_core_paper.py:843` (NAV_POLICY §3, 30-min tolerance) refuses writes
outside the 00:05 UTC window. `dry_run=True` was the only escape hatch — and S-335/S-336
caught me twice calling dry-run success "verification" when it does not touch the write
path at all. **An agent that cannot verify a fix in <5 min is an agent that will keep
re-fixing the same thing across context boundaries.**

Vault (Layer II) already has the answer. A-21 shipped `POST /internal/vault-tick/{vault_id}`
which is exactly the primitive that was missing for paper books: force-tick → curl reads
result → adjust → force-tick → cron takes over. The pattern works because the validation
loop is synchronous, not scheduled.

This router copies the shape:

    POST /internal/force-mark/{book}            # X-Internal-Token
      ?dry_run=false                            # default false = real write

Internal flow:
  1. book.mark_and_rebalance(dry_run=dry_run, force=True, source="manual")
     (mark_and_trade for dingge; mark_and_rebalance for the other 8)
  2. mark_and_rebalance: if force=True, skip _VALUATION_POINT_TOLERANCE_MIN guard
     (still BLOCK on missing-price / stale-price / coverage-fail / write-fail).
     This is the line 844 change in beta_core_paper.py — the ONLY book with a
     timing guard.
  3. write NAV row with mark_source="manual" (column added via migration
     `migrations/2026-09-14_paper_nav_mark_source.sql`).
  4. fire loop_beat.beat(f"_book_{book}_loop", ok=ok/False) per call
     (closes the S-327 / S-334 / S-336 loop: a successful write updates
     liveness immediately).
  5. return the mark result dict, augmented with {ok, wrote, mark_source,
     mark_ts, liveness_update_error}.

NAV_POLICY §3 still applies:
  - missing price → refuse (write no row, log to nav_exceptions when §10 ships)
  - stale price → refuse
  - coverage < 80% → refuse
  - write failed → refused (result is the information; HTTP 200 either way —
    vault-tick convention: protocol-level errors only)
  - valuation-point off-by > 30 min → refuse UNLESS force=True (operator override)

NOT in scope (explicit non-goals):
  - Replace NAV_POLICY §3 valuation point (still 00:05 UTC ±30min for cron).
  - Make paper books per-minute (they are not vault; cadence is product-driven).
  - Touch vault (A-21 shipped; Layer II hardening is separate, larger work).
  - Settle OPEN RISK 0c (`paper_books/sleeve_*.py`).

The product split is intentional and held here:
  - Fund NAV (the 9 daily paper books) = 24h at 00:05 UTC. Force-mark exists
    to verify fixes faster; daily cadence stays.
  - Vault NAV (A-21, vault_nav_tick) = per-minute on operator demand, ETH
    ERC-20 mainnet, signed off-chain NAV broadcast.
  - L2 deployment deferred per JAZZ 2026-09-14 (institutional LPs read mainnet
    as more trustworthy; L2 architectures inform design only).
"""
from __future__ import annotations

import datetime as dt
import importlib
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException

router = APIRouter()

#: Books whose daily mark can be force-struck. Name → import path.
#: Same shape as `write_probe.DRYRUN_BOOKS`; the two dicts are kept in lock-step
#: so a book missing here cannot be dry-run and cannot be force-marked (same
#: gate, two primitives). Re-importing here keeps this router self-contained
#: and avoids a cross-router runtime dependency.
_FORCE_BOOKS: dict[str, str] = {
    "beta_core": "src.data.signals.beta_core_paper",
    "causal": "src.data.signals.causal_paper",
    "combined": "src.data.signals.combined_book",
    "dingge": "src.data.signals.dingge_paper",
    "fusion": "src.data.signals.fusion_paper",
    "scalable": "src.data.signals.scalable_paper",
    "two_layer": "src.data.signals.two_layer_paper",
    "factor_tilt": "src.data.signals.factor_tilt_paper",
    "pod_aggregator": "src.data.signals.pod_aggregator_paper",
}

#: Book → NAV table. S-378b-B: force-mark checks this table for today's row
#: before invoking the book, so re-running force-mark after the daily cron
#: already wrote the row returns already_marked instead of HTTP 409.
_NAV_TABLE_BY_BOOK: dict[str, str] = {
    "beta_core":      "beta_core_paper_nav",
    "causal":         "causal_paper_nav",
    "combined":       "combined_book_nav",
    "dingge":         "dingge_paper_nav",
    "fusion":         "fusion_paper_nav",
    "scalable":       "scalable_book_nav",
    "two_layer":      "two_layer_paper_nav",
    "factor_tilt":    "factor_tilt_nav",
    "pod_aggregator": "pod_aggregator_nav",
}


def _token() -> str:
    # Read at call time, not import time — Railway rotates it.
    return os.getenv("INTERNAL_TOKEN", "")


def _auth(tok: str | None) -> None:
    t = _token()
    if not t or not tok or tok != t:
        raise HTTPException(status_code=401, detail="Invalid token")


def _already_marked_response(*, book: str, today: str, nav_table: str) -> dict:
    """S-378b-B: build the response when today's NAV row already exists.

    Pure function — no I/O. The caller (`force_mark`) does the Supabase check
    via `nav_row_exists` and hands the three needed facts here. Keeps the
    short-circuit logic testable without mocks for the rest of the request
    lifecycle.
    """
    return {
        "ok": True,
        "book": book,
        "mark_ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mark_source": "manual",
        "wrote": False,
        "phase": "idempotent_short_circuit",
        "mark_status": "already_marked",
        "result": {"status": "already_marked",
                   "date": today,
                   "reason": "today_row_exists"},
        "reading": ("ok=true: today's NAV row already exists. "
                    "force-mark is idempotent by design so the "
                    "24h cron write is not overwritten by an "
                    "operator verification call. Pass "
                    "?force_overwrite=true only if you deleted "
                    "the row first."),
    }


def _derive_force_mark_error(
    *, book: str, ok: bool, status: str | None, result: dict | None,
) -> str | None:
    """S-378b-A1: derive a non-empty error context for the liveness beat.

    Prior code passed `(result or {}).get("error")` directly — many paper books
    write the failure reason into `reason` / `note` / `phase` instead of `error`,
    so the beat landed in Redis with `last_error=""`. Dashboard then couldn't
    diagnose ("you cannot debug a blank"). Try every plausible field in order;
    if every one is empty, synthesize a clear "book returned <status> with no
    error field" message — that message tells the operator exactly which book
    has its failure-shape wrong.

    When `ok=True`, returns None — beats store last_error=None then.

    Pure function, importable for tests.
    """
    if ok:
        return None
    _err_fields = [
        (result or {}).get("error"),
        (result or {}).get("reason"),
        (result or {}).get("note"),
        (result or {}).get("phase"),
    ]
    _err_ctx = next((str(e) for e in _err_fields if e), "")
    if not _err_ctx.strip():
        _err_ctx = (f"{book}: mark returned status={status!r} with no "
                    f"error/reason/note/phase field — fix the book to write "
                    f"a failure string into one of those keys")
    return _err_ctx[:200]


@router.post("/internal/force-mark/{book}")
async def force_mark(
    book: str,
    dry_run: bool = False,
    force_overwrite: bool = False,
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
) -> dict[str, Any]:
    """Force one mark of one paper book. The validation primitive.

    NOT bound to any schedule. Caller invokes, reads result. This is the end of
    the 24h "did anything happen?" loop for paper-book NAV — the operator can
    ask "did this book mark just now?" and get the answer in one HTTP call.

    Args:
        book:    book slug matching one of _FORCE_BOOKS keys
        dry_run: if True, compute and return NAV but don't write.
                 Use this to inspect "what would the mark write?" before
                 committing. force=True still applies (bypasses valuation
                 guard).

    Returns:
        The mark result dict, augmented with:
          - ok:                  bool — True iff mark succeeded
          - mark_ts:             ISO8601 UTC — when the call was struck
          - mark_source:         "manual" (the column value written)
          - book:                echo of the slug
          - wrote:               bool — True iff a NAV row was written
          - liveness_update_error: str | None — beat firing failed but mark
                                  itself succeeded (rare; data is on disk)

        HTTP 200 in both ok=True and ok=False cases (vault-tick convention: the
        failure shape is the information; HTTP-level errors are for protocol
        problems, not for "missing price" or "valuation-point off-by").

    Auth: X-Internal-Token. Same as /internal/write-probe and /internal/vault-tick.
    """
    _auth(x_internal_token)

    if book not in _FORCE_BOOKS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown book {book!r}; known: {sorted(_FORCE_BOOKS)}")

    # S-378b-B: idempotency check before invoking the book. The daily cron
    # already wrote today's row at 00:05 UTC; re-running force-mark later in
    # the day would attempt a duplicate insert and 409. Short-circuit to
    # already_marked so the operator gets an explicit, non-error response
    # instead of "HTTP 409" appearing as last_error on the liveness beat.
    # Override via the `force_overwrite=true` query param when the operator
    # genuinely wants to replace today's row (e.g., they deleted the bad one
    # and want to re-mark).
    if not force_overwrite:
        _today = dt.date.today().isoformat()
        _nav_table = _NAV_TABLE_BY_BOOK.get(book)
        if _nav_table:
            try:
                from src.data.signals.nav_persist import nav_row_exists
                _exists = await nav_row_exists(_nav_table, _today)
            except Exception:                                   # noqa: BLE001
                _exists = None  # read fail ⇒ don't block the operator
            if _exists is True:
                _err_ctx = (f"{book}: today's row already exists in "
                            f"{_nav_table} for {_today}; force-mark is "
                            f"idempotent. Pass ?force_overwrite=true to "
                            f"replace it (you usually do NOT want this).")
                # Beat as refused (already_marked is in NO_WORK_STATUS → ok=
                # False, refused=True); keeps the failure counter clean and
                # the operator sees a clear "no work needed" on the dashboard.
                try:
                    from src.api.loop_beat import beat
                    await beat(f"_book_{book}_loop", ok=False, refused=True,
                               error=_err_ctx)
                except Exception:                               # noqa: BLE001
                    pass
                return _already_marked_response(
                    book=book, today=_today, nav_table=_nav_table,
                )

    try:
        mod = importlib.import_module(_FORCE_BOOKS[book])
    except Exception as e:                                      # noqa: BLE001
        return {
            "ok": False,
            "book": book,
            "mark_ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mark_source": "manual",
            "wrote": False,
            "phase": "import",
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }

    fn = getattr(mod, "mark_and_rebalance", None) or getattr(mod, "mark_and_trade", None)
    if fn is None:
        return {
            "ok": False,
            "book": book,
            "mark_ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mark_source": "manual",
            "wrote": False,
            "phase": "resolve",
            "error": "no mark_and_rebalance / mark_and_trade",
        }

    try:
        result = await fn(dry_run=dry_run, force=True, source="manual")
    except Exception as e:                                      # noqa: BLE001
        return {
            "ok": False,
            "book": book,
            "mark_ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mark_source": "manual",
            "wrote": False,
            "phase": "run",
            "error": f"{type(e).__name__}: {str(e)[:300]}",
        }

    # Determine write outcome from the mark result. Most books report "status":
    #   - "marked" / "inception" → wrote=True
    #   - "skipped" / "already_marked" / "mark_failed" → wrote=False
    #   - "degraded" / "ok" (pod_aggregator / factor_tilt) → wrote=ok flag
    #   - "error" → wrote=False
    _status = (result or {}).get("status")
    if _status in ("marked", "inception"):
        _wrote = True
    elif _status == "ok":
        # pod_aggregator / factor_tilt: `status: ok` only if nav_write.ok
        _wrote = bool((result or {}).get("nav_persisted", True))
    elif _status == "degraded":
        _wrote = False
    else:
        _wrote = False

    # ok=True iff the mark succeeded (a row landed) AND no exception escaped.
    _ok = _wrote and _status not in ("mark_failed", "error", "degraded")

    # S-378b-A1: derive a non-empty error context via the helper. Single source
    # of truth for the S-323z "no blank errors" discipline.
    _err_for_beat = _derive_force_mark_error(
        book=book, ok=_ok, status=_status, result=result,
    )

    # Fire the per-call beat. Liveness update failure must not block the
    # response — the mark data is already in (or failed for an honest reason).
    _liveness_error: str | None = None
    try:
        from src.api.loop_beat import beat
        await beat(f"_book_{book}_loop",
                   ok=_ok,
                   error=_err_for_beat)
    except Exception as _be:                                    # noqa: BLE001
        _liveness_error = f"{type(_be).__name__}: {str(_be)[:120]}"

    return {
        "ok": _ok,
        "book": book,
        "mark_ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mark_source": "manual",
        "wrote": _wrote,
        "mark_status": _status,
        "liveness_update_error": _liveness_error,
        "result": result,
        "reading": ("ok=true means a NAV row landed. ok=false: read "
                    "result.error / result.status / mark_status — missing "
                    "price, stale price, coverage-fail, valuation-point "
                    "off-by (bypassed by force=True), or write-fail all "
                    "return here, never raise."),
    }