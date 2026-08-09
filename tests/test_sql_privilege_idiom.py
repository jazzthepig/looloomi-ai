"""
SQL privilege-idiom guard — the revoke that succeeds and changes nothing.

WHAT HAPPENED (2026-08-09, full code check). Four SECURITY DEFINER functions that
fetch from Binance over HTTP and write unbounded rows were callable by `anon` — a
role that is public by construction, shipping in the frontend bundle. A single
unauthenticated RPC with a large `p_max_batches` drives unbounded outbound requests
and unbounded INSERTs against a storage tier we were at 90% of the week before.

The part that makes this a guard rather than a one-off fix: the scripts ALREADY
contained the revoke, and had since the day they were written.

    revoke all on function backfill_binance_hourly(text, bigint, int)
      from anon, authenticated;          -- supabase_ohlcv_hourly.sql:103

`CREATE FUNCTION` grants EXECUTE to PUBLIC. `anon` merely INHERITS it, and never
holds it directly. Revoking from a role that was never granted is a SUCCESSFUL
NO-OP — no error, no warning, no rows — while the script reads as though the door
were locked. The ACL is where the truth lives:

    locked   {postgres=X/postgres, service_role=X/postgres}
    exposed  {=X/postgres, postgres=X/postgres, service_role=X/postgres}
              ^ empty grantee == PUBLIC

The correct idiom already existed once in this repo, in
supabase_refresh_signal_track_record_v2.sql (`... from public`), and that function
is the one that was actually locked. Same author, same week, both idioms, and
nothing in the text distinguishes the working one from the decorative one.

This is the house failure mode wearing new clothes — an operation that reports
success while changing nothing — after S-105 (durable write that never landed),
S-116 (mapping that never matched), S-122 (defaults that erased their own evidence).

LIMIT OF THIS GUARD, stated rather than implied: it reads scripts, so it proves the
IDIOM is right, never that the database is. The live check is in the header of
scripts/supabase_revoke_public_execute.sql and belongs to a scheduled probe, not to
an offline gate. A script is not a grant.

Run: python3 -m tests.test_sql_privilege_idiom
"""
import os
import pathlib
import re
import sys

REPO = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_REVOKE_FN = re.compile(
    r"revoke\s+.*?\s+on\s+function\s+([\w.]+)\s*\(([^)]*)\)\s*from\s+([^;]+);",
    re.I | re.S)


def _sql_files():
    for p in sorted(REPO.glob("scripts/**/*.sql")):
        yield p, p.read_text(encoding="utf-8", errors="ignore")


def test_function_revokes_target_public_not_just_named_roles():
    """A function's default EXECUTE grant belongs to PUBLIC. Revoking from `anon`
    alone removes a privilege that role never directly held, and Postgres reports
    success — so the script and the database disagree, silently and permanently."""
    offenders = []
    for path, txt in _sql_files():
        # ignore commented-out lines
        code = "\n".join(l for l in txt.splitlines() if not l.strip().startswith("--"))
        by_fn: dict = {}
        for m in _REVOKE_FN.finditer(code):
            fn = m.group(1).split(".")[-1]
            grantees = {g.strip().lower() for g in m.group(3).split(",")}
            by_fn.setdefault(fn, set()).update(grantees)
        for fn, grantees in by_fn.items():
            if "public" not in grantees:
                offenders.append(
                    f"{path.relative_to(REPO)}: revoke on {fn}() targets "
                    f"{sorted(grantees)} but never PUBLIC — the default grant survives")
    assert not offenders, (
        "revoke that cannot remove the default EXECUTE grant:\n  "
        + "\n  ".join(offenders))


def test_security_definer_functions_are_revoked_at_all():
    """A SECURITY DEFINER function bypasses RLS by definition, so leaving it on the
    default grant hands every anonymous caller the owner's rights. If a script
    defines one, the same script must lock it."""
    offenders = []
    for path, txt in _sql_files():
        code = "\n".join(l for l in txt.splitlines() if not l.strip().startswith("--"))
        for m in re.finditer(r"create\s+or\s+replace\s+function\s+([\w.]+)\s*\(",
                             code, re.I):
            fn = m.group(1).split(".")[-1]
            tail = code[m.start():]
            if not re.search(r"security\s+definer", tail[:2000], re.I):
                continue
            if not re.search(rf"revoke\s+.*?on\s+function\s+(public\.)?{re.escape(fn)}\s*\(",
                             code, re.I | re.S):
                offenders.append(f"{path.relative_to(REPO)}: {fn}() is SECURITY DEFINER "
                                 f"with no revoke in the same script")
    assert not offenders, (
        "SECURITY DEFINER function left on the default PUBLIC grant:\n  "
        + "\n  ".join(offenders))


def test_recreating_a_function_reinstates_the_grant_is_documented():
    """CREATE OR REPLACE re-grants EXECUTE to PUBLIC, so the hole reopens on the next
    migration that touches one of these. That is a property of Postgres, not of our
    code, which is exactly why it has to be written down next to the fix rather than
    remembered."""
    p = REPO / "scripts" / "supabase_revoke_public_execute.sql"
    assert p.exists(), "scripts/supabase_revoke_public_execute.sql missing"
    txt = p.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION" in txt.upper(), \
        "must warn that re-creating a function reinstates the PUBLIC grant"
    assert "PUBLIC" in txt.upper() and "no-op" in txt.lower(), \
        "must record WHY the previous revoke did nothing, not just that it was replaced"


def test_the_guard_fires_on_the_idiom_it_was_built_for():
    """Negative control. Both guards above were written after the defect, so each has
    to be shown failing on it — the discipline that caught two false-passing guards
    earlier today (S-122's scanner, S-124's multi-line query check)."""
    bad = ("create or replace function public.danger(p int) returns int\n"
           "language plpgsql security definer as $$ begin return 1; end $$;\n"
           "revoke all on function public.danger(int) from anon, authenticated;\n")
    by_fn = {}
    for m in _REVOKE_FN.finditer(bad):
        by_fn.setdefault(m.group(1).split(".")[-1], set()).update(
            g.strip().lower() for g in m.group(3).split(","))
    assert by_fn, "the revoke pattern failed to match a well-formed statement"
    assert "public" not in by_fn["danger"], \
        "the guard must classify a from-anon-only revoke as an offender"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} SQL privilege-idiom checks passed")
    sys.exit(1 if f else 0)
