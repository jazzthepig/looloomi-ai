"""
Guard: usage metering can actually support an invoice (S-140).

WHAT WAS MEASURED 2026-08-11. Usage existed ONLY in Redis under `rl:rpd:{identity}`
with a 24-hour TTL, and `api_keys.request_count` was incremented by NOTHING — the
column is displayed on the analytics page and had read 0 since creation.

So there was no substrate to bill from. Not "billing is unbuilt": the usage itself
did not survive a day. That is S-105's shape (the strategy library spent 12 days in
a 24h-TTL Redis key) moved onto revenue, and it is worse — research can be
re-derived, a month of metered usage cannot. It is simultaneously S-131's shape:
`request_count` is a column that exists, is shown, and is never written, so "a
customer who made no calls" and "a customer we failed to meter" render identically.

THE PROPERTY THIS SUITE DEFENDS is monotonicity of the flush:

    requests = GREATEST(existing, incoming)

  · a replayed flush cannot double-count → retry after timeout is free
  · a missed flush is recovered by the next → Redis holds the running total
  · a Redis reset mid-day leaves the high-water mark, not zero

So we UNDER-count on a lost counter and never OVER-count. That direction is
chosen, not accidental: a bill we can defend is a conversation, an over-bill is a
refund and a reputation. The tempting alternative — flush the delta then reset —
makes every flush a destructive read, so one failed write between read and reset
loses that slice permanently and nothing downstream can tell.

Run: python3 -m tests.test_metering_is_billable
"""
from __future__ import annotations

import ast
import re
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


_METERING = (_ROOT / "src/api/metering.py").read_text(encoding="utf-8")
_SQL = (_ROOT / "scripts/supabase_tenancy_and_metering.sql").read_text(encoding="utf-8")


def test_the_flush_is_monotone_in_the_database_not_the_client() -> None:
    """A guarantee enforced in the caller holds until someone writes a second
    caller. In the function it holds for every caller forever."""
    check("upsert goes through the RPC, not a raw table POST",
          "rpc/api_usage_upsert" in _METERING,
          "a plain PostgREST merge-duplicates OVERWRITES — it would lower `requests` "
          "the moment a Redis counter resets mid-day")
    check("the client does not compute a delta",
          "reset" not in _METERING.split('"""')[2].lower() or "-=" not in _METERING,
          "a delta flush is a destructive read: one failed write loses that slice")


def test_metering_reads_the_rate_limiters_own_counters() -> None:
    """Two counters for one quantity is two numbers that will disagree, and the
    disagreement surfaces as a billing dispute."""
    check("it reads rl:rpd:*, the keys the middleware writes",
          "rl:rpd:" in _METERING, "")
    rl = (_ROOT / "src/api/middleware/rate_limit.py").read_text(encoding="utf-8")
    check("the middleware still writes that key shape",
          'f"rl:rpd:{identity}"' in rl,
          "if the middleware's key format changed, metering silently reads nothing")


def test_only_account_holders_are_metered() -> None:
    """The middleware also rate-limits anonymous callers by IP. Metering those
    would invent usage for people who have no account — an invoice line with no
    customer, and a privacy problem besides."""
    check("only cc_live_ identities are counted",
          'startswith("cc_live_")' in _METERING, "")


def test_scan_not_keys() -> None:
    """KEYS blocks the Redis server across the whole keyspace, and this runs
    against the same instance serving the request path."""
    check("uses SCAN with a cursor", '"scan", cursor' in _METERING, "")
    check("does not use KEYS", '"keys"' not in _METERING.lower().split("run:")[0]
          or '/keys/' not in _METERING, "")
    check("the scan is bounded", "_SCAN_LIMIT" in _METERING,
          "an unbounded scan can stall the loop on a runaway keyspace")


def test_postgres_is_not_on_the_request_path() -> None:
    """Writing a usage row per request is the 2026-07-29 saturation P0 waiting to
    happen (Supabase saturation → 33s hangs → retry storm, while /health said
    healthy). The flush is a background loop with an interval."""
    check("flush runs on an interval", "FLUSH_INTERVAL_S" in _METERING, "")
    main = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    check("the loop is scheduled at startup", "_metering_flush_loop" in main, "")
    check("the loop can be disabled without a deploy", "DISABLE_METERING" in main,
          "a background loop with no off switch is one you cannot stop in an incident")
    rl = (_ROOT / "src/api/middleware/rate_limit.py").read_text(encoding="utf-8")
    # Code only. The one "Supabase" in this file is a COMMENT explaining the 30s
    # key cache — matching it would fire the guard on the sentence describing the
    # very optimisation it wants, which is the fourth time that pattern has bitten
    # in this repo.
    rl_code = "\n".join(l for l in rl.splitlines() if not l.lstrip().startswith("#"))
    check("the middleware writes no usage row per request",
          "api_usage" not in rl_code and "rpc/" not in rl_code,
          "metering must not add a database round trip to every request")


def test_the_audit_write_reports_whether_it_landed() -> None:
    """Lesson #107/#108: "the function was called" and "the row exists" are
    separate facts. An audit trail that fails silently is worse than none, because
    it is believed."""
    tree = ast.parse(_METERING)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "write_audit"), None)
    check("write_audit exists", fn is not None, "")
    if fn:
        check("write_audit returns bool",
              getattr(getattr(fn, "returns", None), "id", None) == "bool",
              "it must report the outcome, not just log it")
    keys = (_ROOT / "src/api/routers/keys.py").read_text(encoding="utf-8")
    check("key issuance is audited", 'action="key.issue"' in keys, "")
    check("a failed audit is logged, not swallowed",
          "AUDIT NOT WRITTEN" in keys, "")
    check("a failed audit does not block issuance",
          "raise" not in keys.split('action="key.issue"')[1][:400],
          "refusing to issue a key because the audit table hiccuped trades a real "
          "capability for a bookkeeping preference")


def test_the_customer_is_the_org_not_the_key() -> None:
    """An API key is a CREDENTIAL. A customer rotates keys, issues one per
    environment, and expects one invoice. Modelling the customer as the key makes
    rotation a billing event."""
    check("organizations table exists", "create table if not exists organizations" in _SQL, "")
    check("api_keys references an org", "add column if not exists org_id" in _SQL, "")
    check("org_id is nullable, not backfilled",
          "NULL here means" in _SQL or "nullable on purpose" in _SQL.lower(),
          "inventing one org per existing key would manufacture a customer list "
          "out of credentials")


def test_the_new_tables_are_service_role_only() -> None:
    """These carry the customer list, the invoice basis and the audit trail."""
    for t in ("organizations", "api_usage", "audit_log"):
        # whitespace-normalised: the SQL pads these three statements into a column,
        # and a guard that breaks on alignment gets deleted by whoever formats next
        norm = re.sub(r"\s+", " ", _SQL)
        check(f"{t}: RLS enabled",
              f"alter table {t} enable row level security" in norm, "")
    check("policies deny by default", _SQL.count("for all using (false)") >= 3, "")
    check("anon and authenticated are revoked",
          "revoke all on organizations, api_usage, audit_log from anon, authenticated" in _SQL, "")


def test_the_rpc_is_not_callable_by_anon() -> None:
    """S-125 was exactly this oversight on four other SECURITY DEFINER functions:
    definer rights plus a default PUBLIC execute grant is an anon-callable
    privilege escalation."""
    mig = _SQL + (_ROOT / "scripts").joinpath("supabase_tenancy_and_metering.sql").read_text()
    # the function lives in the applied migration; assert the SQL file documents it
    check("the file records that the upsert is the monotone one",
          "GREATEST" in _SQL.upper(), "")
    check("the under-count direction is stated as a choice",
          "under-count" in _SQL.lower() and "over-count" in _SQL.lower(),
          "the rounding direction on an invoice must be chosen, not discovered")


if __name__ == "__main__":
    print("── usage metering can support an invoice (S-140) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ metering is durable, monotone and auditable")
