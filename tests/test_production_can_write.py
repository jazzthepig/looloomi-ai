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
    """Both write helpers must return False rather than raise, AND the caller
    must be able to tell. Checked at the source because the five paper books
    that swallow the return value are the reason this went unseen for days."""
    store = (_ROOT / "src/api/store.py").read_text(encoding="utf-8")
    for fn in ("supabase_insert_table", "supabase_upsert_table"):
        # Window wide enough to clear the docstring. The first version used 900
        # chars and reported upsert as raising — the guard was reading past the
        # end of the prose, not past the end of the function.
        blk = store.split(f"async def {fn}")[1][:2600]
        check(f"{fn} consults the role gate", "refuse_write(" in blk, "")
        check(f"{fn} returns False rather than raising", "return False" in blk, "")


if __name__ == "__main__":
    print("── a read-only production must be impossible to miss (S-168) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ /health names the consequence · gate still fails closed")
