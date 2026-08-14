"""
Research intake contract — canonical schema + normalizer for
`POST /internal/research-intake` (S-164).

WHY THIS EXISTS. Measured 2026-08-15, against the live database:

    strategy_records   RLS on,  0 policies          → every key except service_role refused
    asset_embeddings   RLS on,  0 policies          → same
    experiment_runs    RLS on,  SELECT only, PUBLIC → readable, NOT writable
    strategy_params    table does not exist         → the S-151 SQL was never applied

Minimax-C was asked to land 172 mined artefacts into the record and could not.
That was not his error and not a bug: RLS with no INSERT policy denies by
default, correctly. The error was mine — I assigned work down a path that was
closed, and nothing anywhere said it was closed, so it was discovered by
collision. The service_role key is deliberately NOT shared with the mining
lanes (Jazz, 2026-08-11), so "give C the key" is not the fix.

So the write side keeps exactly one owner (`APP_ROLE=production`, i.e. Railway)
and the mining lanes reach it the same way the Mac Mini engine already reaches
`/internal/cis-scores`: an internal-token-guarded POST through a contract
module. One credential boundary, one normalizer, one schema echo, zero new
concepts for the operator on the other end.

────────────────────────────────────────────────────────────────────────────
FOUR RULES, and the third is the one that matters
────────────────────────────────────────────────────────────────────────────

1. RESILIENT, NEVER FATAL. A malformed row is skipped with a warning, never a
   422 for the batch. Same argument as cis_push: one bad field must not cost
   171 good records. The response reports `accepted` and `rejected` separately
   so a silent partial write is impossible to mistake for a success.

2. IDEMPOTENT. Rows land by UPSERT on the natural key (`run_id`, `id`), never
   by INSERT. A mining lane WILL retry — on timeout, on a 502, on a rerun of
   the same script — and an intake that appends on retry does not merely
   duplicate rows, it corrupts every base rate computed from the table.
   `17/29 refuted` is a number we make decisions with; it must not be a
   function of how many times a script was run.

3. **A MINING LANE CANNOT WRITE ITS OWN VERDICT.** `experiment_runs.verdict`
   is coerced into a controlled vocabulary, and `SHIP` is REFUSED from this
   endpoint under every spelling. Anything arriving as SHIP is stored as
   `CANDIDATE` with the downgrade recorded in `notes`.

   This is not distrust of C. It is that the discipline suite
   (`tests/test_strategy_discipline.py`) is what earns a SHIP — documented
   cause, `oos_survival=True`, ≥60d paper trade, regime-conditional reporting
   — and that suite runs in preflight, on this side, over the committed
   record. An endpoint that let a verdict arrive pre-declared would be a way
   to route around the only gate we have. The bar is "guilty until proven with
   out-of-sample outcomes"; a bar that can be asserted past is not a bar.

   The asymmetry is deliberate and runs one way: a lane may submit evidence of
   any strength, and may not submit the conclusion.

4. COMPLIANCE AT THE BOUNDARY (CLAUDE.md rule #1). Free text — `hypothesis`,
   `notes` — is scanned for buy/sell/hold language before it lands. Not
   because `experiment_runs` is user-facing today, but because
   `strategy_records` feeds the strategy library, the library feeds surfaces,
   and the distance between "internal note" and "rendered on strategy.html"
   is one product decision made by someone who was not in this conversation.
   Sanitising on the way in costs nothing; retrofitting it across a populated
   table costs an audit.

PROVENANCE IS NOT OPTIONAL. Every intake row carries `source_lane` and
`intake_batch`. Without them the table cannot answer "which of these did a
mining lane self-report and which did we verify", and a record that cannot
separate those two is not a track record — it is a pile of claims.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("research_intake")

SCHEMA_VERSION = "1.0"

# The only tables this endpoint may write. An allow-list, not a block-list:
# a typo'd table name must be a rejection, not a new table.
INTAKE_TABLES = ("experiment_runs", "strategy_records")

# Natural key per table — what UPSERT resolves duplicates on.
NATURAL_KEY = {
    "experiment_runs": "run_id",
    "strategy_records": "id",
}

# Lanes permitted to submit. The token proves "internal"; this proves "which".
KNOWN_LANES = ("minimax-a", "minimax-b", "minimax-c", "mac-t1", "seth", "austin")

# ── Verdict vocabulary ───────────────────────────────────────────────────────
# REFUTED / INCONCLUSIVE / CANDIDATE are findings — a lane may assert any of
# them, because each one is a claim AGAINST deployment or a request for review.
# SHIP is the only verdict that moves capital, and it is not in this set.
SUBMITTABLE_VERDICTS = {"REFUTED", "INCONCLUSIVE", "CANDIDATE", "REPLICATED", "PENDING"}

# Every spelling seen in the wild that means "deploy this".
_SHIP_ALIASES = {
    "SHIP", "SHIPPED", "SHIP_IT", "DEPLOY", "DEPLOYED", "LIVE", "PRODUCTION",
    "APPROVED", "PASS", "PASSED", "GO", "PROMOTE", "PROMOTED", "ACCEPTED",
}

# ── Compliance (CLAUDE.md rule #1; full tables in .claude/skills/compliance-language/)
_BANNED_TERMS = {
    r"\bbuy\b": "overweight",
    r"\bbuying\b": "overweighting",
    r"\bsell\b": "underweight",
    r"\bselling\b": "underweighting",
    r"\bhold\b": "neutral",
    r"\baccumulate\b": "overweight",
    r"\bavoid\b": "underweight",
    r"\breduce\b": "underweight",
    r"\bdump\b": "underweight",
    r"\blong\b(?!\s*[-_]?(term|run|only|horizon|period|window|standing))": "overweight",
}
_COMPILED = [(re.compile(p, re.IGNORECASE), r) for p, r in _BANNED_TERMS.items()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_text(s: Any) -> tuple[str | None, list[str]]:
    """Return (clean_text, substitutions_made). Never raises on odd input."""
    if s is None:
        return None, []
    text = str(s)
    subs: list[str] = []
    for rx, repl in _COMPILED:
        new, n = rx.subn(repl, text)
        if n:
            subs.append(f"{rx.pattern}→{repl}×{n}")
            text = new
    return text, subs


def _coerce_verdict(raw: Any) -> tuple[str, str | None]:
    """(verdict, downgrade_note). Rule 3 lives here.

    Unknown verdicts become PENDING rather than being rejected — losing a whole
    experiment because a lane wrote 'inconclusive?' would push lanes toward not
    reporting the ones that did not work, and the graveyard is the asset.
    """
    v = str(raw or "").strip().upper().replace(" ", "_")
    if v in _SHIP_ALIASES:
        return "CANDIDATE", (
            f"verdict '{raw}' submitted via /internal/research-intake was stored as "
            f"CANDIDATE. A SHIP verdict is earned by tests/test_strategy_discipline.py "
            f"(cause documented, oos_survival=True, >=60d paper trade, "
            f"regime-conditional reporting) over the committed record, not asserted "
            f"at submission.")
    if v in SUBMITTABLE_VERDICTS:
        return v, None
    return "PENDING", f"unrecognised verdict '{raw}' stored as PENDING for triage"


def _f(v: Any) -> float | None:
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        f = float(v)
        return None if f != f else f          # NaN → NULL, never 0.0
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


# ── Row normalizers ──────────────────────────────────────────────────────────

_EXPERIMENT_COLS = (
    "run_id", "ts", "kind", "hypothesis", "universe", "verdict", "sharpe", "ic",
    "dsr", "corr_to_book", "max_dd_pct", "total_return_pct", "n_obs", "cost_bps",
    "window", "params", "notes", "ledger_ref",
)


def _normalize_experiment_run(row: dict, lane: str, batch: str) -> tuple[dict | None, list[str]]:
    warns: list[str] = []
    run_id = str(row.get("run_id") or row.get("id") or "").strip()
    if not run_id:
        return None, ["missing run_id — the natural key; without it the row cannot be idempotent"]

    kind = str(row.get("kind") or "").strip() or "unspecified"
    hypothesis, s1 = sanitize_text(row.get("hypothesis") or row.get("claim") or "")
    if not (hypothesis or "").strip():
        return None, [f"{run_id}: missing hypothesis — an experiment without a stated "
                      f"claim cannot be refuted, so it cannot be evidence"]

    verdict, downgrade = _coerce_verdict(row.get("verdict"))
    notes, s2 = sanitize_text(row.get("notes"))
    subs = s1 + s2
    if subs:
        warns.append(f"{run_id}: compliance substitutions {subs}")
    if downgrade:
        warns.append(f"{run_id}: {downgrade}")
        notes = f"{notes}\n[INTAKE] {downgrade}" if notes else f"[INTAKE] {downgrade}"

    params = row.get("params")
    if not isinstance(params, dict):
        params = {"raw_params": params} if params is not None else {}
    # Provenance travels inside params too, so a row copied out of the table
    # without its columns still carries where it came from.
    params = {**params, "_source_lane": lane, "_intake_batch": batch,
              "_intake_schema": SCHEMA_VERSION}

    out = {
        "run_id": run_id,
        "ts": row.get("ts") or _now(),
        "kind": kind,
        "hypothesis": hypothesis,
        "universe": (str(row["universe"]) if row.get("universe") else None),
        "verdict": verdict,
        "sharpe": _f(row.get("sharpe")),
        "ic": _f(row.get("ic")),
        "dsr": _f(row.get("dsr")),
        "corr_to_book": _f(row.get("corr_to_book")),
        "max_dd_pct": _f(row.get("max_dd_pct")),
        "total_return_pct": _f(row.get("total_return_pct")),
        "n_obs": _i(row.get("n_obs")),
        "cost_bps": _f(row.get("cost_bps")),
        "window": (str(row["window"]) if row.get("window") else None),
        "params": params,
        "notes": notes,
        "ledger_ref": (str(row["ledger_ref"]) if row.get("ledger_ref") else None),
        "source_lane": lane,
        "intake_batch": batch,
    }

    # NOT a rejection — a flag. A result reported with no observation count and
    # no cost assumption is still worth keeping; it is just not yet evidence.
    if out["n_obs"] is None:
        warns.append(f"{run_id}: no n_obs — cannot be weighed against a base rate")
    if out["cost_bps"] is None and out["total_return_pct"] is not None:
        warns.append(f"{run_id}: return reported with no cost_bps — treat as gross")
    return out, warns


def _normalize_strategy_record(row: dict, lane: str, batch: str) -> tuple[dict | None, list[str]]:
    warns: list[str] = []
    rec_id = str(row.get("id") or row.get("strategy_id") or "").strip()
    if not rec_id:
        return None, ["missing id — the natural key"]

    record = row.get("record")
    if not isinstance(record, dict):
        record = {k: v for k, v in row.items() if k not in ("id", "strategy_id")}
    if not record:
        return None, [f"{rec_id}: empty record"]

    # Sanitise free text anywhere in the payload, at any depth.
    subs_all: list[str] = []

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            clean, subs = sanitize_text(node)
            subs_all.extend(subs)
            return clean
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        return node

    record = _walk(record)
    if subs_all:
        warns.append(f"{rec_id}: compliance substitutions {sorted(set(subs_all))}")

    # Rule 3 applies here too — a strategy record may not carry a self-declared
    # deployment status.
    for key in ("verdict", "status", "decision"):
        if key in record:
            v, downgrade = _coerce_verdict(record[key])
            if downgrade:
                record[key] = v
                record.setdefault("_intake_notes", []).append(downgrade)
                warns.append(f"{rec_id}: {downgrade}")

    record["_source_lane"] = lane
    record["_intake_batch"] = batch
    record["_intake_schema"] = SCHEMA_VERSION
    return {"id": rec_id, "record": record, "updated_at": _now()}, warns


_NORMALIZERS = {
    "experiment_runs": _normalize_experiment_run,
    "strategy_records": _normalize_strategy_record,
}


# ── Public entry point ───────────────────────────────────────────────────────

def normalize_research_payload(payload: dict) -> dict:
    """Validate + normalize one intake batch.

    Returns a report dict — it never raises, and it never returns rows without
    also returning what it threw away. A caller that only reads `rows` gets a
    correct write; a caller that only reads `rejected` gets the honest count.
    """
    table = str(payload.get("table") or payload.get("kind") or "").strip()
    lane = str(payload.get("source_lane") or payload.get("lane") or "").strip().lower()
    batch = str(payload.get("batch_id") or "").strip() or f"auto-{_now()}"
    raw_rows = payload.get("rows")

    fatal: list[str] = []
    if table not in INTAKE_TABLES:
        fatal.append(f"table {table!r} is not one of {INTAKE_TABLES}")
    if lane not in KNOWN_LANES:
        fatal.append(f"source_lane {lane!r} is not one of {KNOWN_LANES} — a row whose "
                     f"origin is unknown cannot be separated from a verified one later")
    if not isinstance(raw_rows, list) or not raw_rows:
        fatal.append("rows must be a non-empty list")
    if fatal:
        return {"ok": False, "schema_version": SCHEMA_VERSION, "fatal": fatal,
                "table": table, "rows": [], "accepted": 0, "rejected": [],
                "warnings": [], "batch_id": batch}

    norm = _NORMALIZERS[table]
    rows: list[dict] = []
    rejected: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    key = NATURAL_KEY[table]

    for i, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            rejected.append(f"row {i}: not an object")
            continue
        try:
            out, warns = norm(raw, lane, batch)
        except Exception as e:                       # noqa: BLE001 — rule 1
            rejected.append(f"row {i}: normalizer raised {type(e).__name__}: {e}")
            continue
        warnings.extend(warns)
        if out is None:
            rejected.extend(f"row {i}: {w}" for w in warns)
            continue
        # Duplicates WITHIN a batch: upsert would keep the last silently.
        if out[key] in seen:
            rejected.append(f"row {i}: duplicate {key}={out[key]} inside the same batch")
            continue
        seen.add(out[key])
        rows.append(out)

    return {
        "ok": bool(rows),
        "schema_version": SCHEMA_VERSION,
        "table": table,
        "source_lane": lane,
        "batch_id": batch,
        "on_conflict": key,
        "rows": rows,
        "accepted": len(rows),
        "rejected": rejected,
        "warnings": warnings,
        "fatal": [],
    }


def canonical_schema() -> dict:
    """Echoed by GET /internal/research-intake/schema so the submitting lane can
    verify the shape it is building against WITHOUT reading this repo — the
    mining lanes do not have it checked out."""
    return {
        "schema_version": SCHEMA_VERSION,
        "endpoint": "POST /internal/research-intake",
        "auth": "header X-Internal-Token",
        "envelope": {
            "table": list(INTAKE_TABLES),
            "source_lane": list(KNOWN_LANES),
            "batch_id": "string, stable across retries of the same batch",
            "rows": "list of objects, see per-table fields",
        },
        "idempotency": {
            "mode": "upsert",
            "on_conflict": NATURAL_KEY,
            "note": "resubmitting the same batch_id + row keys is safe and is the "
                    "intended retry behaviour",
        },
        "experiment_runs_fields": list(_EXPERIMENT_COLS),
        "strategy_records_fields": ["id", "record (object)"],
        "verdict": {
            "submittable": sorted(SUBMITTABLE_VERDICTS),
            "refused": sorted(_SHIP_ALIASES),
            "on_refusal": "stored as CANDIDATE, downgrade appended to notes",
            "why": "SHIP is earned by the discipline suite over the committed "
                   "record, never asserted at submission",
        },
        "compliance": {
            "rule": "CLAUDE.md #1 — no buy/sell/hold language, any surface",
            "applied_to": ["hypothesis", "notes", "record (recursively)"],
            "action": "substituted, not rejected; substitutions are reported",
        },
        "response": {
            "accepted": "int — rows written",
            "rejected": "list[str] — rows NOT written, with reasons",
            "warnings": "list[str] — rows written, but read these",
        },
    }
