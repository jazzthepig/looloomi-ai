"""
Guard: the Mac-lane write wrappers cannot report a write that did not happen
(S-169, 2026-08-18).

WHAT THEY REPLACE. Mac-A's §NO-DIRECT-SUPABASE, confirmed 2026-08-16:

    [M-WO-D1] INFO  — built 58 rows (live), 16.9 measured dims/row
    [M-WO-D1] ERROR — SUPABASE_URL or SUPABASE_KEY missing in .env
    [M-WO-D1] INFO  — M-WO-D1 push complete

Build succeeded, write did not, script said "complete". Measured 2026-08-18:
`asset_embeddings_history` 0 rows and `risk_meter_history` 0 rows. That path
never landed a single row — the tables were not stale, they were empty.

The mechanism: the Mac `.env` holds the ANON key, and both RPCs are SECURITY
INVOKER, so they execute with the caller's privileges and RLS denies the
underlying tables. The service_role key is deliberately not in any `.env`, so
the fix routes the write through the process that already holds it.

THE PROPERTY THIS FILE PINS is not the payload shape — that is a pass-through
and it should be free to change with the RPC. It is that **ok=false always
carries rows_written=0 and a named reason.** Every incident this week came from
a failure that rendered identically to a success:

    the 80-day dead signal_outcomes pipeline
    eleven tables that did not exist          (S-166)
    a read-only production                    (S-168)
    and this one

A wrapper that inherited that property would have moved the silence rather than
removed it.

SECOND PROPERTY: the write must go through the ROLE-GATED rpc helper.
`supabase_rpc` predates S-149 and has no gate; routing Mac writes through it
would have put them OUTSIDE the write boundary while `supabase_insert_table`
next to it refuses — one door locked, the door beside it not.

Run: python3 -m tests.test_mac_push_wrappers
"""
from __future__ import annotations

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


_ROUTER = (_ROOT / "src/api/routers/mac_push.py").read_text(encoding="utf-8")
_STORE = (_ROOT / "src/api/store.py").read_text(encoding="utf-8")


def _code(text: str) -> str:
    """Strip comments. The sixth guard-reads-its-own-prose bug was 2026-08-15
    (S-167); this file was written three days later and is not repeating it."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def test_a_failed_write_never_reports_rows_written() -> None:
    blk = _ROUTER.split("async def _call")[1][:1400]
    code = _code(blk)
    check("the failure branch pins rows_written to 0", '"rows_written": 0' in code, "")
    check("and ok False", '"ok": False' in code, "")
    check("and carries the reason through", '"reason": result' in code,
          "a generic message does not merely fail to help, it funds wrong answers")


def test_the_two_write_causes_are_named_separately() -> None:
    """Role gate and Supabase rejection have different owners and different
    fixes. Collapsing them sent us down the wrong one twice this week."""
    blk = _code(_ROUTER.split("async def _call")[1][:1600])
    check("role-gate refusal is identified", "APP_ROLE=production" in blk, "")
    check("Supabase rejection is identified separately", "Supabase rejected" in blk, "")


def test_the_write_goes_through_the_role_gated_helper() -> None:
    code = _code(_ROUTER)
    check("router uses supabase_rpc_write", "supabase_rpc_write(" in code, "")
    check("router does NOT use the ungated supabase_rpc",
          "supabase_rpc(" not in code.replace("supabase_rpc_write(", ""),
          "supabase_rpc has no role gate — a replica calling it writes the "
          "shared record while supabase_insert_table beside it refuses")
    blk = _code(_STORE.split("async def supabase_rpc_write")[1][:1800])
    check("supabase_rpc_write consults refuse_write", "refuse_write(" in blk, "")
    check("and returns a reason, not just False", "return False," in blk,
          "None-for-everything is the collapse that hid S-166 and S-168")


def test_the_rpc_signature_is_recorded_where_drift_is_visible() -> None:
    """Read from the live catalog 2026-08-18. If Postgres changes and this does
    not, the diff should be here rather than a 400 nobody can debug across a
    lane boundary."""
    for arg in ("p_d", "p_regime", "p_band", "p_score", "p_long_gross",
                "p_interpretation", "p_components"):
        check(f"risk-meter arg {arg} recorded", f'"{arg}"' in _ROUTER, "")
    check("asset-vectors RPC named", "upsert_asset_embeddings_history" in _ROUTER, "")


def test_both_argument_spellings_are_accepted() -> None:
    """The Mac builds one shape today and this side does not know which. A 400
    on the wrong spelling is a failure nobody can debug from the other lane."""
    code = _code(_ROUTER)
    check("bare names fall back from p_-prefixed", "bare = k[2:]" in code, "")
    check("a genuinely missing arg still 400s with the signature",
          "missing required argument" in code and "signature" in code, "")


def test_the_contract_is_readable_without_a_credential() -> None:
    check("schema echo exists", "/internal/mac-push/schema" in _ROUTER, "")
    blk = _ROUTER.split("async def mac_push_schema")[1][:2000]
    check("and states the failure contract", "failure_contract" in blk,
          "the lane on the other end must know that ok=false means nothing landed")


def test_the_sweep_script_does_not_pass_when_it_cannot_look() -> None:
    """§NO-DIRECT-SUPABASE step 5. The grep targets a Mac volume that does not
    exist in the sandbox or on CI; silently skipping would report 'clean' from a
    machine that never checked."""
    p = _ROOT / "scripts/check_no_direct_supabase.sh"
    check("sweep script exists", p.exists(), "")
    if not p.exists():
        return
    s = p.read_text(encoding="utf-8")
    check("unmounted prints NOT CHECKED, not a pass", "NOT CHECKED" in s, "")
    check("and says so explicitly", "This is not a pass" in s, "")
    check("strict mode is one flag away", "NO_DIRECT_SUPABASE_STRICT" in s,
          "step 5 flips to hard-fail after the Mac switches its callers")
    check("it points at the wrappers that replace the direct write",
          "/internal/asset-vectors-history" in s, "")


if __name__ == "__main__":
    print("── Mac-lane write wrappers: no silent success (S-169) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ ok=false always means nothing landed · writes stay behind the role gate")
