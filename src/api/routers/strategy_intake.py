"""
Strategy record intake — the write path that removes the need to share a DB key.

THE ASK. Minimax-A could not write beta-strategy records to Supabase and asked for
the `service_role` key. Jazz declined. That instinct is right, and the alternative
is better than a compromise — it is strictly better than sharing the key on two
independent grounds:

  1. BLAST RADIUS. `service_role` bypasses RLS on every table: read, write, drop.
     A token scoped to this endpoint can only append strategy records, and it
     rotates without touching the database. The forged-JWT incident (Lesson #72)
     is the standing reminder that a credential in more places is a credential in
     more incidents.

  2. THE GATE BECOMES UNBYPASSABLE — and this is the stronger argument.
     With a raw DB key, a SHIP record that fails `tests/test_strategy_discipline`
     can be written anyway; the discipline floor exists only in CI, and CI is not
     in the write path. Here `StrategyRecord.validate()` runs BEFORE the insert.
     A record that does not clear the floor is REJECTED WITH ITS REASONS, not
     stored and caught later by a test nobody ran.
     **A gate that the writer can route around is a suggestion.**

The pattern is not new here: the Mac engine has pushed CIS scores through
`POST /internal/cis-scores` with `X-Internal-Token` for months. This is that
contract applied to the other direction of traffic.

DESIGN NOTES
· Per-record verdicts, not all-or-nothing. A batch of 20 where 3 fail should land
  17 and report 3, because forcing a resubmit of the whole batch is how a lane
  starts working around the endpoint.
· Rejections carry `validate()`'s own problem strings verbatim. A rejection that
  says "invalid" teaches nothing; one that says "ship verdict but
  trigger_median_run_days 3.0 < the 30.0 position it opens" is a fix.
· REFUTE and PARK records are accepted without the SHIP floor — the graveyard is
  the asset (CLAUDE.md) and a failed experiment must be as easy to record as a
  successful one, or the ledger silently biases toward wins.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException

from src.data.vector.strategy_schema import StrategyRecord, Verdict

_logger = logging.getLogger(__name__)
router = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

# Fields a caller may set. Anything else is dropped with a warning rather than
# silently accepted — an unknown field usually means the sender's schema has
# drifted, and swallowing it is how two lanes end up disagreeing about a contract
# while both believe they are compliant.
_ALLOWED = set(StrategyRecord.__dataclass_fields__)


def _coerce(raw: dict) -> tuple[StrategyRecord | None, list[str]]:
    unknown = sorted(set(raw) - _ALLOWED)
    clean = {k: v for k, v in raw.items() if k in _ALLOWED}
    for req in ("id", "title", "doc_source"):
        if not clean.get(req):
            return None, [f"missing required field '{req}'"] + (
                [f"unknown fields ignored: {unknown}"] if unknown else [])
    if isinstance(clean.get("verdict"), str):
        try:
            clean["verdict"] = Verdict(clean["verdict"])
        except ValueError:
            return None, [f"verdict '{clean['verdict']}' not one of "
                          f"{[v.value for v in Verdict]}"]
    try:
        rec = StrategyRecord(**clean)
    except TypeError as e:
        return None, [f"could not construct record: {e}"]
    return rec, ([f"unknown fields ignored: {unknown}"] if unknown else [])


@router.post("/internal/strategy-records")
async def receive_strategy_records(payload: dict, x_internal_token: str = Header(None)):
    """Accept strategy records from any lane, validate, then persist.

    Body: {"records": [ {...StrategyRecord...}, ... ]}
    Auth: X-Internal-Token — the same token the CIS push already uses.

    Returns per-record verdicts so a partial batch lands. 207 when some were
    rejected, so a caller cannot read a blanket 200 as "all stored"."""
    # Reject-by-default: a missing env var must fail closed, never open.
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=400, detail="body must be {'records': [ ... ]}")
    if len(records) > 200:
        raise HTTPException(status_code=413, detail="max 200 records per call")

    accepted, rejected, to_write = [], [], []
    for raw in records:
        if not isinstance(raw, dict):
            rejected.append({"id": None, "problems": ["record is not an object"]})
            continue
        rec, notes = _coerce(raw)
        if rec is None:
            rejected.append({"id": raw.get("id"), "problems": notes})
            continue
        # THE GATE. Only SHIP carries the evidence floor: a REFUTE must be as easy
        # to file as a win, or the graveyard — which CLAUDE.md calls the asset —
        # fills up with successes only.
        problems = rec.validate() if rec.verdict == Verdict.SHIP else []
        if problems:
            rejected.append({"id": rec.id, "verdict": rec.verdict.value,
                             "problems": problems, "notes": notes})
            continue
        to_write.append(rec)
        accepted.append({"id": rec.id, "verdict": rec.verdict.value, "notes": notes})

    written = 0
    if to_write:
        from src.data.vector.strategy_store import upsert_many
        try:
            written = upsert_many(to_write)
        except Exception as e:                    # durability failure is NOT an
            _logger.error("[strategy-intake] persist failed: %s", e)   # acceptance
            raise HTTPException(status_code=503,
                                detail=f"validated {len(to_write)} but could not "
                                       f"persist: {str(e)[:120]}")

    if written != len(to_write):
        # Do not report validated-but-unwritten as accepted. S-105: the strategy
        # library spent 12 days believing it had persisted records it had not.
        _logger.warning("[strategy-intake] validated %d, persisted %d",
                        len(to_write), written)

    body = {
        "accepted": accepted, "rejected": rejected,
        "validated": len(to_write), "persisted": written,
        "gate": "StrategyRecord.validate() — SHIP records must clear the evidence "
                "floor; REFUTE/PARK are recorded as-is",
    }
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=207 if rejected else 200, content=body)


@router.get("/internal/strategy-records/schema")
async def strategy_record_schema():
    """Live echo of the accepted shape, so a sender can diff against reality rather
    than against a doc. Same reason the CIS contract exposes its schema: a written
    contract drifts, an echoed one cannot."""
    fields = {}
    for name, f in StrategyRecord.__dataclass_fields__.items():
        fields[name] = str(f.type).replace("typing.", "")
    return {
        "fields": fields,
        "verdicts": [v.value for v in Verdict],
        "ship_floor": [
            "base_rate", "oos_survival", "paper_trade_days>=60", "regime_reported",
            "max_dd_stop + capital_action_on_breach", "backtest_included_stop",
            "deflated_sharpe>=0.95 + n_trials", "pbo<=0.5",
            "median_holding_days>=5", "net_effect_pct_yr>0",
            "trigger_median_run_days >= median_holding_days",
        ],
        "auth": "X-Internal-Token header",
        "note": "service_role is NOT required and NOT shared — this endpoint holds it",
    }
