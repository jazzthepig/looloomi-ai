"""
Guard: a read-only production must be impossible to miss (S-168, 2026-08-15).

WHAT WAS MEASURED. The live deployment reported `environment: replica`. Under
S-149's role gate that means `is_writer() == False`, and `supabase_insert_table`
/ `supabase_upsert_table` return False on their FIRST line. Production could not
write the system of record, and had not since 2026-08-12:

    cis_scores       last write 2026-08-12 14:42Z   (66 h before discovery)
    beta_core_nav    last mark  2026-08-12
    experiment_runs  last row   2026-08-12 02:16Z
    strategy_records 0 rows
    beta_core_nav_q / _size  0 rows

Meanwhile `/internal/build-state` showed `last_cis_push: age 38 min, 43 assets,
stale: false`. **The Mac T1 engine was pushing the entire time.** The push
arrived, returned 200, and was refused at the store. Arriving-and-discarded is
indistinguishable from arriving-and-stored unless something says so.

THE ROOT IS A BELIEF ABOUT ANOTHER SYSTEM, WRITTEN DOWN AND NEVER PROBED.
runtime_role.py:

    # `production` here is deliberate and load-bearing: Railway sets
    # ENVIRONMENT=production explicitly, so the mapping preserves the live
    # deployment.

It does not. `_resolve()` falls through to `_LEGACY_MAP.get(legacy, REPLICA)`
and the live service became a replica the moment the gate shipped. The comment
is emphatic — "deliberate and load-bearing" — which is exactly the tone that
stops a reader checking. Confidence in prose is not evidence.

WHY NOTHING SAID ANYTHING. `refuse_write()` logs once per target, deliberately
(S-149: a refusal every five minutes buries the boot banner). And `environment:
replica` HAS been on /health the whole time — it names the ROLE, not the
CONSEQUENCE, and no one reads "replica" as "we are storing nothing."

    Every failure this week had this shape: the state was visible and the
    consequence was not.

So the fix is not another log line. /health now carries a `writes` block whose
`verdict` field says "READ-ONLY — nothing is being persisted" in words, and the
deploy-verifier fails on it.

Run: python3 -m tests.test_production_can_write
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def test_health_reports_whether_writes_are_possible() -> None:
    src = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    check("/health carries a writes block", '"writes": _writes_block()' in src,
          "a read-only production is invisible from every other field — the API "
          "is genuinely healthy, it just stores nothing")
    blk = src.split("def _writes_block")[1][:2600]
    check("it reports the consequence, not just the role",
          "READ-ONLY" in blk and "persisted" in blk,
          "'replica' names the role; nobody reads it as 'we are storing nothing'")
    check("it names the exact fix", "APP_ROLE=production" in blk,
          "a 3am alarm that does not say what to change costs a round trip")


def test_the_role_resolution_no_longer_asserts_what_railway_has() -> None:
    """The comment claimed Railway sets ENVIRONMENT=production. It does not, and
    that belief was load-bearing for every write in the system. Whatever the
    file says now, it must not present that as established fact."""
    src = (_ROOT / "src/api/runtime_role.py").read_text(encoding="utf-8")
    check("the false claim about Railway's env is corrected",
          "Railway sets ENVIRONMENT=production explicitly, so the mapping "
          "preserves the live deployment" not in src,
          "that sentence was measured false on 2026-08-15 — production had been "
          "a replica since 08-12. Replace it with what was observed.")


def test_the_gate_still_fails_closed() -> None:
    """The fix must not be 'default to production'. Guessing wrong in THAT
    direction means a laptop writing the LP-facing record, which is worse than
    an outage. Unset must still resolve to replica."""
    import importlib
    saved = {k: os.environ.pop(k, None) for k in ("APP_ROLE", "ENVIRONMENT")}
    try:
        import src.api.runtime_role as rr
        importlib.reload(rr)
        check("with nothing set, the role is replica", rr.ROLE == "replica",
              f"got {rr.ROLE} — defaulting to production would let any laptop "
              f"write the shared record")
        check("and is_writer() is False", rr.is_writer() is False, "")
        os.environ["APP_ROLE"] = "production"
        importlib.reload(rr)
        check("APP_ROLE=production makes it a writer", rr.is_writer() is True, "")
    finally:
        os.environ.pop("APP_ROLE", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
        import src.api.runtime_role as rr2
        importlib.reload(rr2)


def test_a_refused_write_is_reported_by_the_write_path() -> None:
    """A refused write must RETURN a failure a caller can read — never raise.

    ⚠️ S-359: this used to grep the source for the literal ``return False``.
    A's S-341b migrated both helpers to ``StoreResult[bool].fail(reason)`` —
    strictly better, because a bare False cannot say WHY — and the guard went
    red while the behaviour it protects got stronger.

    **It was checking the SPELLING of the old contract, not the behaviour.**
    And this file's own comment already recorded being fooled by source text
    once ("the guard was reading past the end of the prose"). Same class,
    second time. So it now CALLS them under a refusing role.

    The role gate fires before any network I/O, so this needs no credentials.
    """
    import asyncio
    import importlib
    import os

    saved = {k: os.environ.get(k) for k in ("APP_ROLE", "SUPABASE_URL", "SUPABASE_KEY")}
    try:
        os.environ["APP_ROLE"] = "replica"          # read-only ⇒ every write refused
        import src.api.runtime_role as rr
        importlib.reload(rr)
        import src.api.store as st
        importlib.reload(st)

        for fn_name, call in (
            ("supabase_insert_table",
             lambda: st.supabase_insert_table("beta_core_nav", [{"nav": 1.0}])),
            ("supabase_upsert_table",
             lambda: st.supabase_upsert_table("beta_core_nav", [{"nav": 1.0}], "mark_date")),
        ):
            try:
                res = asyncio.run(call())
                raised = None
            except Exception as e:                              # noqa: BLE001
                res, raised = None, f"{type(e).__name__}: {e}"

            check(f"{fn_name} returns rather than raising", raised is None, raised or "")
            if raised:
                continue
            ok = bool(getattr(res, "ok", res))
            why = str(getattr(res, "why", "") or "")
            check(f"{fn_name} reports the refusal as a failure", ok is False, f"got {res!r}")
            # A bare False is the defect S-329 spent a week on: the caller cannot
            # tell a role refusal from a timeout. Require a readable reason.
            check(f"{fn_name} says WHY it refused",
                  bool(why.strip()), f"why={why!r} — a bare False cannot be acted on")
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        import src.api.runtime_role as rr2
        importlib.reload(rr2)
        import src.api.store as st2
        importlib.reload(st2)


def test_the_role_gate_is_still_consulted_at_the_source() -> None:
    """Structural half: the gate must be IN the helper, not in its callers.

    Kept as a source check on purpose — this one is about WHERE the gate lives,
    and "a gate you have to remember to call is a gate that will be forgotten"
    (store.py's own words, S-149). Behaviour is asserted above.
    """
    store = (_ROOT / "src/api/store.py").read_text(encoding="utf-8")
    for fn in ("supabase_insert_table", "supabase_upsert_table"):
        blk = store.split(f"async def {fn}")[1][:2600]
        check(f"{fn} consults the role gate", "refuse_write(" in blk, "")


if __name__ == "__main__":
    print("── a read-only production must be impossible to miss (S-168) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ /health names the consequence · gate still fails closed")
