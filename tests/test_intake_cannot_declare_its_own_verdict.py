"""
Guard: the research intake accepts evidence, never conclusions (S-164).

WHAT THIS PROTECTS. /internal/research-intake exists because the mining lanes
hold no service_role key and RLS correctly refuses them — measured 2026-08-15:
strategy_records and asset_embeddings have RLS on with ZERO policies,
experiment_runs has SELECT only. Opening a write path for them is right. Opening
one that also lets them declare a result SHIPPED would be a route around the only
gate we have, because SHIP is what tests/test_strategy_discipline.py earns over
the committed record — documented cause, oos_survival=True, >=60d paper trade,
regime-conditional reporting.

The asymmetry is the invariant, and it runs one way:

    a lane may submit evidence of any strength
    a lane may not submit the conclusion

BEHAVIOURAL, NOT FROZEN. This does not assert that the alias list contains
today's 15 strings — a frozen-value check would have passed on the day somebody
added a 16th spelling, which is precisely how the C3 table passed while
transposed. It asserts the PROPERTY: whatever a lane submits, the stored verdict
is never one that authorises deployment, and the downgrade is recorded rather
than silent. That holds for spellings nobody has written yet.

Run: python3 -m tests.test_intake_cannot_declare_its_own_verdict
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.api.contracts.research_intake import (   # noqa: E402
    NATURAL_KEY,
    SUBMITTABLE_VERDICTS,
    _SHIP_ALIASES,
    canonical_schema,
    normalize_research_payload,
    sanitize_text,
)

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _batch(rows, table="experiment_runs", lane="minimax-c", batch="t1"):
    return normalize_research_payload(
        {"table": table, "source_lane": lane, "batch_id": batch, "rows": rows})


def _row(**kw):
    base = {"run_id": "X-1", "kind": "sleeve", "hypothesis": "momentum tilt beats the panel"}
    base.update(kw)
    return base


# ── The one that matters ─────────────────────────────────────────────────────

def test_no_submitted_verdict_can_authorise_deployment() -> None:
    """The property, over every alias AND their casing/spacing variants."""
    bad = []
    for alias in sorted(_SHIP_ALIASES):
        for spelling in (alias, alias.lower(), alias.title(), f" {alias} ",
                         alias.replace("_", " ")):
            r = _batch([_row(verdict=spelling)])
            if not r["rows"]:
                bad.append(f"{spelling!r} rejected the row entirely (should downgrade, "
                           f"not discard — discarding teaches lanes to stop reporting)")
                continue
            stored = r["rows"][0]["verdict"]
            if stored.upper() in _SHIP_ALIASES:
                bad.append(f"{spelling!r} → stored as {stored!r}")
    check("no spelling of SHIP survives intake", not bad, "; ".join(bad[:4]))


def test_the_downgrade_is_recorded_not_silent() -> None:
    r = _batch([_row(verdict="SHIP", notes="original note")])
    row = r["rows"][0]
    check("downgrade appears in the row's own notes",
          "[INTAKE]" in (row["notes"] or ""),
          "a lane reading its row back must see that the verdict was changed")
    check("the original note survives the downgrade",
          "original note" in (row["notes"] or ""), "")
    check("downgrade is reported in the response warnings",
          any("CANDIDATE" in w for w in r["warnings"]),
          "a downgrade the submitter cannot see is a silent rewrite")


def test_a_lane_may_still_report_a_failure() -> None:
    """The graveyard is the asset. REFUTED must pass through untouched — an
    intake that made negative results harder to file would bias the record
    toward wins, which is the one bias we cannot afford."""
    for v in sorted(SUBMITTABLE_VERDICTS):
        r = _batch([_row(verdict=v)])
        check(f"verdict {v} passes through unchanged",
              bool(r["rows"]) and r["rows"][0]["verdict"] == v,
              f"got {r['rows'][0]['verdict'] if r['rows'] else 'REJECTED'}")


def test_an_unknown_verdict_is_triaged_not_dropped() -> None:
    r = _batch([_row(verdict="inconclusive?")])
    check("unrecognised verdict becomes PENDING rather than losing the row",
          bool(r["rows"]) and r["rows"][0]["verdict"] == "PENDING", "")


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_resubmission_is_an_upsert_not_an_append() -> None:
    check("experiment_runs resolves on run_id", NATURAL_KEY["experiment_runs"] == "run_id", "")
    check("strategy_records resolves on id", NATURAL_KEY["strategy_records"] == "id", "")
    r = _batch([_row(run_id="A"), _row(run_id="A", hypothesis="second copy")])
    check("a duplicate key WITHIN one batch is rejected, not silently last-wins",
          len(r["rows"]) == 1 and any("duplicate" in x for x in r["rejected"]),
          f"accepted={r['accepted']} rejected={r['rejected']}")


def test_the_upsert_path_is_what_the_router_calls() -> None:
    """An idempotent contract wired to an INSERT-only writer is not idempotent.
    Checked at the call site, because that is where it can drift."""
    src = (_ROOT / "src/api/routers/research_intake.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check("router calls supabase_upsert_table", "supabase_upsert_table(" in code, "")
    check("router does not call the insert-only path",
          "supabase_insert_table(" not in code,
          "INSERT turns every retry into duplicate rows, and duplicates in "
          "experiment_runs corrupt every base rate computed from the table")
    check("on_conflict is passed", "on_conflict=" in code, "")


# ── Honest failure ───────────────────────────────────────────────────────────

def test_a_write_that_did_not_happen_never_reports_accepted_rows() -> None:
    """The 80-day dead signal_outcomes pipeline shipped because a failed write
    returned a shape indistinguishable from a successful one."""
    src = (_ROOT / "src/api/routers/research_intake.py").read_text(encoding="utf-8")
    blk = src.split("if not written:")[1][:900]
    check("the declined-write branch reports accepted=0",
          '"accepted": 0' in blk,
          "reporting normalized rows as accepted would recreate the silent-write bug")
    check("and ok=False", '"ok": False' in blk, "")
    check("and says how to diagnose it", "diagnosis" in blk, "")


def test_bad_rows_never_cost_the_good_ones() -> None:
    rows = [_row(run_id="A"), {"garbage": True}, _row(run_id="C"), "not-an-object"]
    r = _batch(rows)
    check("one malformed row does not fail the batch",
          r["accepted"] == 2 and len(r["rejected"]) == 2,
          f"accepted={r['accepted']} rejected={r['rejected']}")


def test_an_unknown_lane_cannot_submit() -> None:
    r = normalize_research_payload(
        {"table": "experiment_runs", "source_lane": "somebody", "rows": [_row()]})
    check("unknown source_lane is fatal",
          not r["ok"] and any("source_lane" in f for f in r["fatal"]),
          "a row whose origin is unknown cannot be separated from a verified one")
    r2 = _batch([_row()], table="cis_scores")
    check("a table outside the allow-list is fatal",
          not r2["ok"] and any("cis_scores" in f for f in r2["fatal"]),
          "the intake must not become a general write channel into the record")


def test_provenance_lands_on_every_row() -> None:
    r = _batch([_row()])
    row = r["rows"][0]
    check("source_lane column is stamped", row.get("source_lane") == "minimax-c", "")
    check("intake_batch column is stamped", row.get("intake_batch") == "t1", "")
    check("and provenance also travels inside params",
          row["params"].get("_source_lane") == "minimax-c",
          "a row copied out without its columns still has to say where it came from")


# ── Compliance (CLAUDE.md #1) ────────────────────────────────────────────────

def test_buy_sell_language_cannot_enter_the_record() -> None:
    r = _batch([_row(hypothesis="buy the top decile and sell the bottom",
                     notes="hold through drawdowns")])
    txt = (r["rows"][0]["hypothesis"] + " " + (r["rows"][0]["notes"] or "")).lower()
    for term in ("buy", "sell", "hold"):
        check(f"'{term}' does not survive into the stored row",
              term not in txt.split("[intake]")[0], f"stored: {txt[:120]}")
    check("substitutions are reported, not silent",
          any("compliance" in w for w in r["warnings"]), "")


def test_long_term_is_not_mangled_into_overweight_term() -> None:
    """The substitution must not damage legitimate prose. `long` means a
    direction; `long-term`, `long run`, `long-only` do not."""
    for phrase in ("long-term holding", "over the long run", "long-only book",
                   "a long horizon", "long standing"):
        clean, subs = sanitize_text(phrase)
        check(f"{phrase!r} is left alone", clean == phrase, f"became {clean!r}")
    clean, _ = sanitize_text("we go long BTC")
    check("but a directional 'long' is still substituted",
          "long" not in clean.lower(), f"got {clean!r}")


def test_strategy_records_are_sanitised_at_any_depth() -> None:
    r = _batch([{"id": "S1", "record": {"legs": [{"note": "buy on breakout"}]}}],
               table="strategy_records")
    check("nested free text is sanitised",
          "buy" not in str(r["rows"][0]["record"]).lower(),
          f"{r['rows'][0]['record']}")
    r2 = _batch([{"id": "S2", "record": {"status": "DEPLOYED"}}], table="strategy_records")
    check("a self-declared status inside a record is downgraded too",
          r2["rows"][0]["record"]["status"] == "CANDIDATE",
          "rule 3 must not be bypassable by moving the word into a jsonb blob")


# ── The contract is readable without the repo ────────────────────────────────

def test_the_schema_echo_tells_a_lane_what_it_needs() -> None:
    s = canonical_schema()
    for key in ("envelope", "idempotency", "verdict", "compliance", "response"):
        check(f"schema echo documents {key}", key in s, "")
    check("the echo names the refused verdicts explicitly",
          bool(s["verdict"]["refused"]),
          "a lane must be able to learn the rule without reading this repo")
    check("and says why", "discipline suite" in s["verdict"]["why"], "")


if __name__ == "__main__":
    print("── research intake: evidence in, conclusions never (S-164) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ a lane may submit evidence of any strength, and never the conclusion")
