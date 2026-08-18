"""
Mac-lane write wrappers — §NO-DIRECT-SUPABASE step 2 (S-169, 2026-08-18).

    POST /internal/asset-vectors-history   → upsert_asset_embeddings_history(p_rows)
    POST /internal/risk-meter-history      → upsert_risk_meter_history(p_d, ...)
    GET  /internal/mac-push/schema         → the contract, unauthenticated

WHY. Mac-A's §NO-DIRECT-SUPABASE, confirmed 2026-08-16:

    [M-WO-D1] INFO  — d=2026-08-16: built 58 rows (live), 16.9 measured dims/row
    [M-WO-D1] ERROR — SUPABASE_URL or SUPABASE_KEY missing in .env
    [M-WO-D1] INFO  — M-WO-D1 push complete

Build succeeded. Write did not. Script reported "complete". The Mac `.env`
carries the anon key, and both RPCs are SECURITY INVOKER, so they run with the
caller's privileges and RLS denies the underlying tables. Measured today, both
targets are EMPTY — `asset_embeddings_history` 0 rows, `risk_meter_history`
0 rows. Not "stale for three weeks": that path has never landed a single row.

The service_role key is deliberately not in any `.env` (§SEC). So the fix is not
to hand out the key — it is to route the write through the process that already
holds it. Same shape as /internal/cis-scores and /internal/research-intake, and
Mac-A is right that this should be a lane-wide rule rather than the per-case
tunnel I built in S-164.

BUILT WITHOUT WAITING FOR THE MAC GREP, and the reason matters. §NO-DIRECT-
SUPABASE step 1 asks Minimax to sweep the Mac for direct-write callers before
wrappers are built — correct in general, and I agreed not to build blind. But
these two endpoints do not depend on that sweep: the RPC SIGNATURE is the
contract, it lives in the database I can reach, and it is more authoritative
than a grep of the caller. Read from the live catalog today:

    upsert_asset_embeddings_history(p_rows jsonb)                       → integer
    upsert_risk_meter_history(p_d date, p_regime text, p_band text,
        p_score numeric, p_long_gross numeric, p_interpretation text,
        p_components jsonb)                                             → integer

The sweep still matters — for whether OTHER callers exist, which is step 5's
guard. It does not gate these two.

PASS-THROUGH, NOT A NEW SHAPE. The Mac already builds the payload these RPCs
take. Reshaping it here would mean two contracts drifting apart, so the wrapper
forwards what it is given and only guarantees three things: the caller is
internal, the write is role-gated, and **the response never says success for a
write that did not happen.** That last one is the whole reason these tables sat
empty while the script logged "complete".
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException

router = APIRouter(tags=["internal"])
_log = logging.getLogger("mac_push")

SCHEMA_VERSION = "1.0"

# Signature read from the live catalog 2026-08-18. Kept here so a drift between
# this file and the database is a visible diff rather than a 400 at runtime.
_RISK_METER_ARGS = (
    "p_d", "p_regime", "p_band", "p_score",
    "p_long_gross", "p_interpretation", "p_components",
)


def _token() -> str:
    return os.getenv("INTERNAL_TOKEN", "")


def _auth(tok: str | None) -> None:
    real = _token()
    if not real or not tok or tok != real:
        raise HTTPException(status_code=401, detail="Invalid token")


async def _call(fn: str, payload: dict, label: str, n_rows: int | None) -> dict:
    """One place where 'did the write land' is decided and reported."""
    from src.api.store import supabase_rpc_write
    ok, result = await supabase_rpc_write(fn, payload)
    if not ok:
        _log.warning("[MAC-PUSH] %s → NOT WRITTEN: %s", label, result)
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "target": label,
            "rows_submitted": n_rows,
            "rows_written": 0,
            "reason": result,
            # Named because the two causes have different owners and different
            # fixes, and "write failed" alone sent us down the wrong one twice
            # this week.
            "diagnosis": (
                "role gate: this process is not APP_ROLE=production"
                if isinstance(result, str) and "may not write" in result else
                "Supabase rejected the call — the message above is from our own "
                "schema, not from your data"),
        }
    _log.info("[MAC-PUSH] %s ← %s rows, rpc returned %s", label, n_rows, result)
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "target": label,
        "rows_submitted": n_rows,
        "rows_written": result if isinstance(result, int) else None,
        "note": ("rows_written is the RPC's own count. If it is lower than "
                 "rows_submitted the upsert deduplicated — that is expected on "
                 "a re-run and is not an error."),
    }


@router.get("/internal/mac-push/schema")
async def mac_push_schema():
    """Unauthenticated: the Mac lane does not have this repo checked out, and a
    contract you need a credential to READ is a contract that gets guessed at."""
    return {
        "schema_version": SCHEMA_VERSION,
        "rule": "§NO-DIRECT-SUPABASE — no lane writes Supabase directly; every "
                "write goes through a Railway endpoint holding service_role",
        "auth": "header X-Internal-Token",
        "endpoints": {
            "POST /internal/asset-vectors-history": {
                "rpc": "upsert_asset_embeddings_history(p_rows jsonb)",
                "body": {"rows": "[ {...}, ... ]  — the same objects you build today"},
                "returns": "rows_written (int) from the RPC itself",
            },
            "POST /internal/risk-meter-history": {
                "rpc": "upsert_risk_meter_history(p_d, p_regime, p_band, p_score, "
                       "p_long_gross, p_interpretation, p_components)",
                "body": {k: "same as today" for k in _RISK_METER_ARGS},
                "note": "send either the p_-prefixed names or the bare ones; "
                        "both are accepted",
            },
        },
        "failure_contract": (
            "ok=false ALWAYS carries rows_written=0 and a reason. There is no "
            "response shape in which a write that did not happen reads as "
            "success — that is exactly how both target tables reached today "
            "with 0 rows while the push script logged 'complete'."),
    }


@router.post("/internal/asset-vectors-history")
async def push_asset_vectors_history(
    payload: dict,
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
):
    _auth(x_internal_token)
    rows: Any = payload.get("rows", payload.get("p_rows"))
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail={
            "error": "body must carry a non-empty 'rows' list",
            "schema": "GET /internal/mac-push/schema"})
    return await _call("upsert_asset_embeddings_history", {"p_rows": rows},
                       "asset_embeddings_history", len(rows))


@router.post("/internal/risk-meter-history")
async def push_risk_meter_history(
    payload: dict,
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
):
    _auth(x_internal_token)
    # Accept both `p_d` and `d`. The Mac builds one shape today and I do not
    # know which; rejecting the wrong one would be a 400 nobody can debug from
    # the other side of a lane boundary.
    args = {}
    missing = []
    for k in _RISK_METER_ARGS:
        bare = k[2:]
        if k in payload:
            args[k] = payload[k]
        elif bare in payload:
            args[k] = payload[bare]
        else:
            missing.append(f"{k} (or {bare})")
    if missing:
        raise HTTPException(status_code=400, detail={
            "error": f"missing required argument(s): {missing}",
            "signature": "upsert_risk_meter_history(" + ", ".join(_RISK_METER_ARGS) + ")",
            "schema": "GET /internal/mac-push/schema"})
    return await _call("upsert_risk_meter_history", args, "risk_meter_history", 1)
