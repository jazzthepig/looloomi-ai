"""Instant verification of the NAV write path — no waiting for 00:05 (S-328).

WHY THIS EXISTS. Every repair in the S-323…S-327 chain ended the same way:
"check after the valuation point." That is a 24-hour feedback loop on a product
whose unit of value is a daily mark, and each wrong guess costs a day that §3
forbids backfilling. It also means the only way to observe a write failure was
to let it happen to the real record.

JAZZ, 2026-09-11: 「你不要搞 utc 0 点这种验收了。」He is right, and the habit was
mine.

Two endpoints, both token-gated (CLAUDE.md #8 — internals stay off surfaces a
competitor reads):

    GET /internal/write-probe    does the app's OWN write path actually work?
    GET /internal/book-dryrun    what would each book do if it marked right now?

WHAT MAKES THE PROBE HONEST. It writes through `insert_with_detail`, which uses
the same key, headers, retry layer and role gate as `supabase_insert_table` — so
a green probe means the books' write path is green, not that some other path is.
It targets `_write_probe`, a table with the SAME RLS posture and grants as the
NAV tables, then deletes what it wrote. It never touches the forward record.

WHAT IT DELIBERATELY DOES NOT DO. It does not mark, and `book-dryrun` passes
`dry_run=True`. A "verification" that writes a real NAV row to prove writing
works would be striking a mark outside the valuation point, which is the exact
thing §3 exists to prevent.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException

router = APIRouter()

PROBE_TABLE = "_write_probe"

#: Books whose daily mark can be exercised dry. Name → import path.
#: Derived nowhere: this one IS hand-written, and it says so, because a dry-run
#: needs a callable and there is no way to infer which coroutine is "the mark".
#: `tests/test_a_book_asks_the_table_not_the_cache.py` is what keeps the real
#: invariant honest; this list only decides what the convenience endpoint covers.
DRYRUN_BOOKS: dict[str, str] = {
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


def _token() -> str:
    # Read at call time, not import time — Railway rotates it.
    return os.getenv("INTERNAL_TOKEN", "")


def _auth(tok: str | None) -> None:
    t = _token()
    if not t or not tok or tok != t:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/internal/write-probe")
async def write_probe(x_internal_token: str = Header(None, alias="X-Internal-Token")
                      ) -> dict[str, Any]:
    """Can this process actually write? Answers in one request, any time.

    Returns the HTTP status and the PostgREST body — the sentence that names the
    cause — instead of the bare False that `supabase_insert_table` returns for a
    role refusal, missing credentials, an empty payload AND a transport error
    alike.
    """
    _auth(x_internal_token)

    from src.api.rpc_diagnostics import insert_with_detail
    from src.api.runtime_role import ROLE

    today = dt.date.today().isoformat()
    ok, detail = await insert_with_detail(
        PROBE_TABLE, [{"mark_date": today, "note": "write-probe"}])

    cleaned = None
    if ok:
        # Leave nothing behind. A probe that accumulates rows becomes a table
        # nobody judges, which is the thing we keep finding.
        try:
            import httpx

            from src.api.store import _SB_KEY, _SB_URL
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.delete(
                    f"{_SB_URL}/rest/v1/{PROBE_TABLE}?note=eq.write-probe",
                    headers={"apikey": _SB_KEY,
                             "Authorization": f"Bearer {_SB_KEY}"})
            cleaned = r.status_code in (200, 204)
        except Exception as e:                                  # noqa: BLE001
            cleaned = f"cleanup failed: {type(e).__name__}"

    return {
        "ok": ok,
        "app_role": ROLE,
        "probe_table": PROBE_TABLE,
        "detail": detail,
        "cleaned_up": cleaned,
        "reading": ("ok=true means the books' write path works right now. "
                    "ok=false: read detail.outcome — role_refusal / "
                    "not_configured / no_response / http_error — they have "
                    "different owners, which is why the bare bool was useless."),
    }


@router.get("/internal/book-dryrun")
async def book_dryrun(book: str = "",
                      x_internal_token: str = Header(None, alias="X-Internal-Token")
                      ) -> dict[str, Any]:
    """What would each book do if it marked now? `dry_run=True`, nothing written.

    This is the half that used to require waiting for the valuation point: it
    exercises data loading, coverage floors, the venue gate and the weighting —
    everything except the write, which `/internal/write-probe` covers.
    """
    _auth(x_internal_token)

    import importlib

    wanted = {book: DRYRUN_BOOKS[book]} if book in DRYRUN_BOOKS else DRYRUN_BOOKS
    if book and book not in DRYRUN_BOOKS:
        raise HTTPException(status_code=404,
                            detail=f"unknown book {book!r}; "
                                   f"known: {sorted(DRYRUN_BOOKS)}")

    out: dict[str, Any] = {}
    for name, mod_path in wanted.items():
        try:
            mod = importlib.import_module(mod_path)
        except Exception as e:                                  # noqa: BLE001
            out[name] = {"ok": False, "phase": "import",
                         "error": f"{type(e).__name__}: {str(e)[:200]}"}
            continue
        fn = getattr(mod, "mark_and_rebalance", None) or getattr(mod, "mark_and_trade", None)
        if fn is None:
            out[name] = {"ok": False, "phase": "resolve",
                         "error": "no mark_and_rebalance / mark_and_trade"}
            continue
        try:
            res = await fn(dry_run=True)
            # Report the status verbatim. Summarising it here would be the same
            # mistake as the heartbeat's hardcoded sentence.
            out[name] = {"ok": True, "phase": "ran", "result": res}
        except Exception as e:                                  # noqa: BLE001
            out[name] = {"ok": False, "phase": "run",
                         "error": f"{type(e).__name__}: {str(e)[:300]}"}

    return {
        "dry_run": True,
        "books": out,
        "reading": ("`ok` here means the mark PATH ran, not that it would have "
                    "written — look at result.status. A TypeError under phase="
                    "'run' is a shipped-half-a-change defect and fails the same "
                    "way every time; it will not clear by waiting."),
    }
