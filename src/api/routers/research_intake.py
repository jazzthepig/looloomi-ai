"""
Research intake — the write path for lanes that hold no service_role key (S-164).

    POST /internal/research-intake          submit a batch
    GET  /internal/research-intake/schema   echo the contract (no auth on the echo)

Measured 2026-08-15: strategy_records and asset_embeddings have RLS on and ZERO
policies; experiment_runs has a SELECT-only policy. Every key except service_role
is refused, correctly and silently-by-design. Minimax-C was asked to land 172
mined artefacts down a path that was closed, and discovered it by collision,
because nothing said it was closed.

The service_role key is deliberately not shared with the mining lanes, so the
fix is not a key — it is this: one credential boundary (Railway), reached the
same way the Mac Mini engine already reaches /internal/cis-scores. The lane on
the other end learns no new concept.

WHAT THIS ENDPOINT WILL NOT DO. It will not accept a SHIP verdict. See
contracts/research_intake.py rule 3: a lane may submit evidence of any strength
and may not submit the conclusion, because the conclusion is what the discipline
suite earns over the committed record. An intake that accepted a pre-declared
verdict would be a route around the only gate we have.

HONEST FAILURE. A batch that writes nothing returns ok=false with reasons, and a
batch that writes some rows returns the rejected list alongside the accepted
count. There is no response shape in which a partial write reads as a success —
that is the failure mode that produced 80 days of a dead signal_outcomes
pipeline, and it is not being rebuilt here.
"""
from __future__ import annotations

import logging
import os
from fastapi import APIRouter, Header, HTTPException

from src.api.contracts.research_intake import (
    NATURAL_KEY,
    SCHEMA_VERSION,
    canonical_schema,
    normalize_research_payload,
)

router = APIRouter(tags=["internal"])
_log = logging.getLogger("research_intake")


def _token() -> str:
    # Read at call time, not import time: Railway rotates it, and a module-level
    # snapshot would keep authenticating against a value nobody can see.
    return os.getenv("INTERNAL_TOKEN", "")


@router.get("/internal/research-intake/schema")
async def research_intake_schema():
    """Unauthenticated on purpose. The submitting lane does not have this repo
    checked out, and a contract you must hold a credential to READ is a contract
    that gets guessed at. It describes shape only — no data, no secrets."""
    return canonical_schema()


@router.post("/internal/research-intake")
async def receive_research_batch(
    payload: dict,
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
):
    tok = _token()
    # Reject by default: a missing env var must fail closed, not open.
    if not tok or not x_internal_token or x_internal_token != tok:
        raise HTTPException(status_code=401, detail="Invalid token")

    report = normalize_research_payload(payload)

    if report["fatal"]:
        # 400, not 422: the envelope itself is wrong, and the lane needs to see
        # the schema. Point at it rather than describing it.
        raise HTTPException(status_code=400, detail={
            "fatal": report["fatal"],
            "schema": "GET /internal/research-intake/schema",
        })

    table = report["table"]
    rows = report["rows"]
    written = False

    if rows:
        from src.api.store import supabase_upsert_table
        written = await supabase_upsert_table(
            table, rows, on_conflict=NATURAL_KEY[table]
        )
        if not written:
            # The role gate or Supabase declined. Say which is possible, and do
            # NOT report accepted rows — nothing landed.
            _log.warning("[INTAKE] %s: %d normalized rows were NOT written",
                         table, len(rows))
            return {
                "ok": False,
                "schema_version": SCHEMA_VERSION,
                "table": table,
                "batch_id": report["batch_id"],
                "accepted": 0,
                "normalized_but_unwritten": len(rows),
                "rejected": report["rejected"],
                "warnings": report["warnings"],
                "diagnosis": (
                    "rows normalized cleanly but the write was declined. Either this "
                    "process is not APP_ROLE=production (replicas may not write the "
                    "shared record), or Supabase rejected the upsert. Check the "
                    "deployment log for [ROLE] or [SUPABASE]."),
            }

    for w in report["warnings"]:
        _log.info("[INTAKE] %s", w)
    for r in report["rejected"]:
        _log.warning("[INTAKE] rejected: %s", r)

    _log.info("[INTAKE] %s ← lane=%s batch=%s accepted=%d rejected=%d",
              table, report["source_lane"], report["batch_id"],
              len(rows), len(report["rejected"]))

    return {
        "ok": bool(rows),
        "schema_version": SCHEMA_VERSION,
        "table": table,
        "source_lane": report["source_lane"],
        "batch_id": report["batch_id"],
        "accepted": len(rows),
        "rejected": report["rejected"],
        "warnings": report["warnings"],
        "idempotent_on": NATURAL_KEY[table],
        "note": ("resubmitting this batch_id with the same row keys is safe and is "
                 "the intended retry behaviour"),
    }
