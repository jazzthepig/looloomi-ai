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


@router.get("/internal/schema-drift")
async def schema_drift(x_internal_token: str = Header(None, alias="X-Internal-Token")):
    """The ONLINE half of the schema guard (S-166 + A-29) — does every table
    the code writes to AND every RPC function the code calls actually exist?

    Measured 2026-08-15: ELEVEN tables did not, including both C2 and C3
    sleeve NAV tables, while PROJECT_STATE read "C2 ⓠ + C3 size complete;
    79/79 smoke green". Green tests, and nowhere to write a row. Measured
    2026-09-14 (A-29): the same drift probe flagged 7 RPC function names as
    MISSING TABLES, because the offline walker could not tell a function call
    from a table write. Both halves of the probe now exist.

    preflight cannot answer this — it is offline by contract (S-163), and that
    is the right trade. This process has the credentials, so this is where the
    question belongs. The deploy-verifier calls it after every push.

    Authenticated: the table list is architecture, and CLAUDE.md #8 keeps
    internals off surfaces a competitor reads.
    """
    tok = _token()
    if not tok or not x_internal_token or x_internal_token != tok:
        raise HTTPException(status_code=401, detail="Invalid token")

    import json
    from src.api.schema_manifest import manifest_path

    try:
        manifest = json.loads(manifest_path().read_text())
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "error": f"manifest unreadable: {type(e).__name__}: {e}",
                "note": "regenerate with tests/test_every_written_table_exists.py"}

    expected_tables = sorted(manifest.get("write_tables") or [])
    expected_rpcs = sorted(manifest.get("rpc_functions") or [])

    from src.api.rpc_diagnostics import rpc_with_detail
    from src.api.store import (
        supabase_function_exists, supabase_missing_columns, supabase_table_exists,
    )
    live, unknown = [], []
    for t in expected_tables:
        got = await supabase_table_exists(t)
        (live if got is True else unknown).append(t)

    missing = [t for t in unknown]

    # ── RPC FUNCTIONS (A-29, probe corrected S-354) ──────────────────────────
    # Same drift class as tables. But **existence is a CATALOG question, not a
    # call question** — and probing by calling produced the same false P0 three
    # separate times for the same three functions:
    #
    #   panel_closes / panel_funding / exec_backfill_forward_returns
    #
    # All three exist and return real data. PostgREST resolves RPCs by ARGUMENT
    # NAME, so POSTing `{}` to a function with a required parameter answers
    # PGRST202 — "no overload matches these argument names", NOT "no such
    # function". Measured 2026-09-15: **128 of this project's 148 functions have
    # a required argument**, so the call-probe would report 128 as missing.
    #
    # ⚠️ And the consequence text built on top of it was worse than the wrong
    # flag: "every write to them returns False and is swallowed — the sleeves
    # have no forward record and cannot start one." A complete causal story on a
    # false premise, pointing at rewriting functions that work.
    #
    # `catalog_inventory()` (S-350) reads pg_proc in one round trip. It was built
    # for exactly this and then left unwired — the report got fixed, the probe
    # did not.
    rpc_live, rpc_unknown, rpc_missing = [], [], []
    _cat, _cat_detail = await rpc_with_detail("catalog_inventory", {})
    if isinstance(_cat, list):
        _known = {r.get("name") for r in _cat
                  if isinstance(r, dict) and r.get("kind") == "function"}
        for fn in expected_rpcs:
            (rpc_live if fn in _known else rpc_missing).append(fn)
    else:
        # **Unreadable catalog is NOT "everything is missing".** Three values,
        # kept apart all the way to the output (S-350: `unknown` renamed to
        # `missing` two lines below its own docstring is how this started).
        rpc_unknown = list(expected_rpcs)

    # ── COLUMNS, not only tables (S-286) ────────────────────────────────────
    # This endpoint was built for S-166, where eleven TABLES were missing, and it
    # inherited that incident's scope. On 2026-09-04 the ① book went dark on a
    # missing COLUMN of a table that existed: `interval_hours`, code deployed
    # ahead of its migration. Every insert 400'd, `_write` returned False, the
    # book stopped, and this endpoint said ok — truthfully, about the wrong
    # question. **Coverage that answers a narrower question than the one you have
    # reads as coverage.**
    #
    # Only tables that exist are probed: asking which columns a missing table
    # lacks produces noise that buries the real finding.
    try:
        expected_cols = json.loads(manifest_path().read_text()).get("write_columns", {})
    except Exception:                                 # noqa: BLE001
        expected_cols = {}
    col_drift, col_unknown = {}, []
    for t in live:
        cols = expected_cols.get(t) or []
        if not cols:
            continue
        got = await supabase_missing_columns(t, cols)
        if got is None:
            col_unknown.append(t)                     # could not tell ≠ missing
        elif got:
            col_drift[t] = got

    return {
        # `rpc_unknown` 不参与 ok —— **读不到不是坏,但也不是好**,
        # 它单独出现在 rpc_check_unavailable 里让人看见。
        "ok": not missing and not col_drift and not rpc_missing,
        # WHICH CHECKS THIS BUILD RUNS. Without it, `column_drift: null` from a
        # deploy that predates the column check is indistinguishable from
        # `column_drift: {}` on a clean one — Jazz hit exactly this on 2026-09-04
        # and neither of us could tell "not deployed" from "nothing wrong" without
        # reading git. A response that cannot say what it checked forces the reader
        # to know the build, and that knowledge is exactly what an echo exists to
        # remove.
        "checks": ["tables", "rpc_functions", "columns"],
        "checked": len(expected_tables),
        "present": len(live),
        "missing": missing,
        "rpc_checked": len(expected_rpcs),
        "rpc_present": len(rpc_live),
        "rpc_missing": rpc_missing,
        # S-354:读不到目录 ≠ 全部缺失。三值一路带到输出,绝不在最后一步塌成两值。
        "rpc_check_unavailable": rpc_unknown,
        "column_drift": col_drift,
        "column_check_unavailable": col_unknown,
        "column_consequence": (
            "code writes column(s) the live table does not have. PostgREST answers "
            "400, the insert helper returns False, and the writer logs one line and "
            "stops — the table simply stops growing, which reads as 'no data yet'. "
            "Almost always a deploy that outran its migration."
            if col_drift else "every column the code writes exists"),
        # Naming the consequence, not just the count. "3 missing" reads like a
        # config nit; "these sleeves cannot persist anything" is the actual fact.
        "consequence": (
            (f"{len(missing)} table(s) the code writes to do not exist. "
             if missing else "")
            + (f"{len(rpc_missing)} RPC function(s) the code calls do not exist. "
             if rpc_missing else "")
            + ("Every write to them returns False and is swallowed — "
               "indistinguishable from 'no data yet'. The sleeves depending on "
               "them have no forward record and cannot start one."
             if missing or rpc_missing else
            "every table the code writes to and every RPC it calls exists")
            # ⚠️ S-354:这句话曾经挂在一个**假前提**上。前一版探针 POST `{}`,
            # 于是三个有必填参数的函数(panel_closes / panel_funding /
            # exec_backfill_forward_returns)被判缺失,而它们都存在且返回真数据。
            # **一个建立在错误事实上的完整因果故事,比一个错误的计数危险得多** ——
            # 它会把人送去重写正在工作的函数,造出第二个重载并弄坏现在能用的那个。
            + (f" ⚠️ catalog unreadable for {len(rpc_unknown)} RPC(s) — "
               f"**that is 'we could not ask', not 'they are missing'**."
             if rpc_unknown else "")),
    }


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
