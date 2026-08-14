"""
Guard: no migration file may grant PUBLIC read or write (S-167, 2026-08-15).

WHAT WAS MEASURED, live, with `set local role anon`:

    api_keys             anon CAN read, 1 row
    signal_track_record  anon CAN read, 836 rows      ← the forward record
    experiment_runs      anon CAN read, 43 rows       ← the research ledger
    cis_scores           0 rows (correctly closed)

`signal_track_record` and `experiment_runs` ARE the product. ARCHITECTURE.md:
"in an A2A market the scarce resource is verifiable forward track record — the
validation apparatus IS the product." It was readable with the anon key.

WHY THE 2026-07-30 HARDENING DID NOT CLOSE IT, and this is the part to keep.
That pass added policies named `<table>_service_only` with `USING (false)`,
which read like denials. **Postgres PERMISSIVE policies are OR'd**, so
`api_keys_service_only USING(false)` OR `api_keys_select USING(true)` = allowed.
A permissive policy cannot subtract. Denial needs AS RESTRICTIVE, or removing
the grant.

    Lesson #71 was  "a security linter's silence is not safety."
    This is        "a policy that reads like a denial is not a denial" —

and it is the worse of the two, because the false denial made the table look
AUDITED. Something that appears to have been checked stops being checked.

SEPARATELY, the same day: 33 `CREATE POLICY ... FOR INSERT WITH CHECK (true)`
grants across 7 migration files, none of them live. The drift ran
file-more-permissive-than-production — the dangerous direction, because these
files are idempotent, they exist to be re-run, and on 2026-08-15 one of them
WAS re-run. Running any of them would have silently re-opened public writes on
a hardened table.

WHY THIS GUARD IS ON THE FILES. The live catalog is checked by the
deploy-verifier, which can only ever say "somebody already did it". This says
"nobody can" — at the point where a diff is still cheap to change. The two
answer different questions and neither replaces the other.

A `CREATE POLICY` with no `TO` clause is granted to PUBLIC. That is a Postgres
default many people misremember, so it is asserted here rather than trusted.

Run: python3 -m tests.test_no_sql_file_grants_public_access
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SQL_DIRS = ("scripts",)

# CREATE POLICY <name> ON <table> [AS PERMISSIVE|RESTRICTIVE] [FOR cmd] [TO roles] ...
_POLICY = re.compile(
    r"create\s+policy\s+\"?(?P<name>[a-z0-9_ ]+)\"?\s+on\s+(?P<tbl>[a-z0-9_.]+)"
    r"(?P<rest>[^;]*);",
    re.I | re.S)

# Roles that are NOT the internet. service_role bypasses RLS; authenticated is a
# signed-in user, which is a deliberate product decision rather than an accident.
_SAFE_ROLES = ("service_role",)

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _sql_files() -> list[Path]:
    out: list[Path] = []
    for d in _SQL_DIRS:
        out.extend(sorted((_ROOT / d).glob("*.sql")))
    return out


_COMMENT = re.compile(r"--[^\n]*")


def _strip_comments(text: str) -> str:
    """Scan CODE, not documentation.

    The first run of this guard failed on its OWN annotations — the lines it had
    just written reading `-- S-167: was CREATE POLICY "x_select" ON x FOR SELECT
    USING (true)`. It reported the tables as still open while they were closed
    in the same file, three lines above.

    That is the SIXTH time in this repo a guard has matched the text explaining
    the thing rather than the thing. The previous five were docstrings, fixed by
    parsing the AST; SQL has no AST here, so comments are stripped instead. The
    recurrence is the point: writing down what a fix does creates text shaped
    exactly like the defect, and any checker that reads a file as a flat string
    will eventually confuse the two. Strip the prose first, always.
    """
    return _COMMENT.sub("", text)


def _dead_denials(text: str) -> list[str]:
    """PERMISSIVE policies with USING (false) — they read as a denial and deny
    nothing, because permissive policies are OR'd.

    Recorded because I wrote three of these into the migration files on
    2026-08-15 in the same hour as the ledger entry explaining why they do not
    work. Knowing a trap and not encoding it are different states, and only the
    second one is safe.
    """
    out: list[str] = []
    for m in _POLICY.finditer(_strip_comments(text)):
        rest = " ".join(m.group("rest").split()).lower()
        if "as restrictive" in rest:
            continue
        if re.search(r"using\s*\(\s*false\s*\)", rest):
            out.append(f"{m.group('tbl')} ({m.group('name').strip()})")
    return out


def _offending(text: str) -> list[tuple[str, str, str]]:
    """(table, cmd, why) for each policy that opens something to PUBLIC."""
    bad: list[tuple[str, str, str]] = []
    for m in _POLICY.finditer(_strip_comments(text)):
        rest = " ".join(m.group("rest").split()).lower()
        tbl = m.group("tbl")

        # RESTRICTIVE policies only ever subtract. Never an exposure.
        if "as restrictive" in rest:
            continue

        to = re.search(r"\bto\s+([a-z_, ]+?)(?:\s+using|\s+with|$)", rest)
        roles = to.group(1).strip() if to else "public"
        if any(r in roles for r in _SAFE_ROLES):
            continue

        cmd_m = re.search(r"\bfor\s+(all|select|insert|update|delete)", rest)
        cmd = (cmd_m.group(1) if cmd_m else "all").upper()

        using_true = re.search(r"using\s*\(\s*true\s*\)", rest) is not None
        check_true = re.search(r"with\s+check\s*\(\s*true\s*\)", rest) is not None
        writes = cmd in ("ALL", "INSERT", "UPDATE", "DELETE")

        if writes and (check_true or using_true):
            bad.append((tbl, cmd, f"grants {cmd} to {roles} unconditionally"))
        elif cmd == "SELECT" and using_true:
            bad.append((tbl, cmd, f"grants SELECT to {roles} unconditionally"))
    return bad


def test_no_migration_file_opens_a_table_to_the_public() -> None:
    """The whole point: a diff that re-adds one of these fails before it lands."""
    problems: list[str] = []
    for f in _sql_files():
        for tbl, cmd, why in _offending(f.read_text(encoding="utf-8", errors="replace")):
            problems.append(f"{f.name}: {tbl} — {why}")
    check(f"no PUBLIC grants across {len(_sql_files())} migration files",
          not problems,
          "\n      ".join(problems[:8]) +
          ("\n      Use `TO service_role`, or drop the policy: RLS enabled with zero "
           "policies already denies everyone except service_role, which bypasses RLS. "
           "That is the posture cis_scores has."))


def test_a_policy_without_a_to_clause_is_treated_as_public() -> None:
    """Asserted, not assumed. `CREATE POLICY ... FOR INSERT WITH CHECK (true)`
    with no TO clause is granted to PUBLIC — a Postgres default that is easy to
    misremember, and misremembering it is how 33 of these got written."""
    sample = 'CREATE POLICY "x_insert" ON x FOR INSERT WITH CHECK (true);'
    check("a TO-less permissive policy is flagged",
          bool(_offending(sample)),
          "if this stops flagging, every historical grant becomes invisible again")
    safe = 'create policy x_ins on x for all to service_role using (true) with check (true);'
    check("an explicit service_role grant is not flagged", not _offending(safe), "")
    restr = 'create policy x_r on x as restrictive for all using (false);'
    check("a RESTRICTIVE policy is not flagged", not _offending(restr),
          "restrictive policies only subtract")


def test_no_file_contains_a_denial_that_denies_nothing() -> None:
    """A PERMISSIVE policy with USING (false) is decoration. It cannot subtract,
    so the table stays exactly as open as its other policies leave it — and it
    now LOOKS locked, which is why api_keys sat readable for 16 days after a
    security pass.

    I then wrote three more of these into these very files on 2026-08-15, in the
    same hour as the ledger entry explaining why they do not work. Knowing a
    trap and encoding it are different states; only the second one survives the
    next author, including when the next author is me an hour later."""
    problems: list[str] = []
    for f in _sql_files():
        for hit in _dead_denials(f.read_text(encoding="utf-8", errors="replace")):
            problems.append(f"{f.name}: {hit}")
    check("no permissive USING(false) policies", not problems,
          "\n      ".join(problems[:8]) +
          "\n      Delete them. RLS enabled with ZERO policies denies every role "
          "except service_role, which bypasses RLS — that is the honest expression "
          "of the same intent. Use AS RESTRICTIVE only when a real subtraction is "
          "needed on top of a legitimate grant.")


def test_the_permissive_or_trap_is_documented_where_it_bit() -> None:
    """The mechanism must stay written down next to the fix. A future author
    adding `USING (false)` to 'lock' a table will otherwise repeat it exactly,
    and the result LOOKS audited, which is the expensive part."""
    hits = [f for f in _sql_files()
            if "permissive" in f.read_text(encoding="utf-8", errors="replace").lower()
            and "or" in f.read_text(encoding="utf-8", errors="replace").lower()]
    check("at least one migration file explains the permissive-OR trap",
          bool(hits),
          "scripts/supabase_security_hardening.sql should carry it — a USING(false) "
          "policy does not deny while any permissive USING(true) policy exists")


def test_the_tables_that_leaked_are_named_so_the_check_cannot_drift_quiet() -> None:
    """A floor, not a freeze. These four were measured open on 2026-08-15; if a
    later refactor reintroduces a grant for any of them the guard must still be
    looking at them."""
    text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in _sql_files())
    for tbl in ("api_keys", "signal_track_record", "experiment_runs",
                "webhook_subscriptions"):
        opened = [t for t, _, _ in _offending(text) if t.endswith(tbl)]
        check(f"{tbl} is not granted to PUBLIC anywhere", not opened, "")


if __name__ == "__main__":
    print("── no .sql file grants PUBLIC read or write (S-167) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ every policy in scripts/ is service_role-scoped or restrictive")
