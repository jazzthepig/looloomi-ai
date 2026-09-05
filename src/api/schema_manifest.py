"""
Which tables the code writes to — extracted from the source, not remembered (S-166).

THE BUG THIS CLASS KEEPS PRODUCING. Measured 2026-08-15 against the live DB:
ELEVEN tables that live code writes to did not exist.

    beta_core_nav_q, beta_core_nav_q_meta          C2 ⓠ sleeve
    beta_core_nav_size, beta_core_nav_size_meta    C3 size sleeve
    strategy_params                                S-151
    execution_intents, execution_outcomes          S-155
    fusion_paper_nav, fusion_paper_lifecycle
    crowd_clock_log

PROJECT_STATE's own header read "C2 ⓠ + C3 size + C5 episode-code complete;
79/79 smoke green" — green tests, and no table to write a single row into. The
sleeves had never persisted anything and never could.

AND WE ALREADY KNEW. OPEN RISK #3(a) has said since 2026-07-26: "A table that
was never created. scripts/supabase_strategy_records.sql ... was never applied.
`_pg_upsert()` POSTed to a nonexistent table, caught the exception, logged one
WARNING, returned False". That risk was written down, the lesson was recorded,
and it then happened eleven more times — because what got fixed was that one
table, not the fact that nothing compares the set of tables the code writes
against the set that exists.

WHY THE EXISTING GUARD MISSED IT, in its own words. tests/test_table_columns_
match_the_code.py: "That catches code-vs-declared drift. It does NOT catch
declared-vs-live drift — only the live catalog can, and preflight is offline by
contract. So ... scripts/verify_live_schema.sql is the online half."

The gap was known, documented, and handed to a .sql file somebody has to
remember to run. That file's own founding argument is that a rule nobody
enforces is a wish, applied here to its own escape hatch. Nobody ran it.

THE SPLIT, and why it is two halves rather than one check. preflight must stay
offline (S-163: credentials in the gate are what made it slow and
machine-dependent). So:

    offline, in preflight   — this manifest matches what the source actually does
    online, post-deploy     — the live catalog matches this manifest

Neither half can pass vacuously. A stale manifest fails the offline half; a
missing table fails the online half. Deleting the manifest fails both.

EXTRACTED, NOT DECLARED. A hand-maintained list is a list that drifts, and drift
is the thing being guarded. This walks the AST and the literals, so adding a
`supabase_insert_table("new_thing", ...)` puts new_thing in the manifest on the
next run whether or not the author thought about it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# Call sites that mean "this string is a table we write to".
_WRITE_FUNCS = {
    "supabase_insert_table",
    "supabase_upsert_table",
    "supabase_delete_table",
}

# `_TABLE = "foo"` / `_NAV_TABLE = "foo"` module constants.
#
# TABLE must be its own underscore-delimited word. The first version of this
# regex matched TABLE as a substring and picked up `NS_INVESTABLE = "investable_v1"`
# — INVES-TABLE — putting a namespace string into the list of tables that must
# exist in Postgres. Funny, and exactly the failure mode this file exists to
# stop: a check that reports something confidently because it pattern-matched
# rather than understood. A guard with false positives gets muted, and a muted
# guard is worse than no guard, because it also occupies the slot where a real
# one would have gone.
#
# Done in two steps rather than one clever regex. The first attempt at a fix
# over-corrected and stopped matching `_TABLE = "..."` itself — a guard that
# silently narrows is the same hazard as one that over-matches, just quieter.
# Capture the name, then decide with plain Python that can be read at a glance.
_CONST_RX = re.compile(r"^(_?[A-Z][A-Z0-9_]*)\s*=\s*[\"']([a-z0-9_]+)[\"']", re.M)


def _names_a_table(const_name: str) -> bool:
    """TABLE must be a whole underscore-delimited word, so INVESTABLE is out."""
    return "TABLE" in const_name.strip("_").split("_")

# Directories whose writes are real production writes. `src/research/**` is
# excluded ON PURPOSE: those are one-off study scripts, they are run by hand,
# and a study that fails loudly on a missing table costs one person one minute.
# Including them would flood the manifest with tables nobody deployed, and a
# noisy guard is a guard people learn to skip.
_PROD_DIRS = ("src/api", "src/data", "src/mcp")

# Not a table. Vendored dependencies, virtualenvs, caches.
_SKIP = ("__pycache__", "/.venv/", "site-packages", "/node_modules/")


def _is_prod(p: Path) -> bool:
    rel = str(p.relative_to(_ROOT)).replace("\\", "/")
    return rel.startswith(_PROD_DIRS) and not any(s in f"/{rel}" for s in _SKIP)


def _tables_in(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found: set[str] = set()

    # 1. Module constants.
    found.update(v for name, v in _CONST_RX.findall(text) if _names_a_table(name))

    # 2. Write-helper call sites. AST, not regex: a table name inside a comment
    #    or a docstring is documentation, not a write, and the whole point of
    #    this file is to stop confusing what is written down with what runs.
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name not in _WRITE_FUNCS or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
        # A non-literal first arg (a variable, an f-string) is invisible here.
        # That is a known blind spot, recorded rather than papered over: a
        # dynamic table name cannot be checked statically, and pretending
        # otherwise would make the manifest look more complete than it is.
    return found


def write_tables() -> list[str]:
    """Every table name a production module writes to. Sorted, deduped."""
    out: set[str] = set()
    for p in sorted(_ROOT.rglob("*.py")):
        if _is_prod(p):
            out |= _tables_in(p)
    return sorted(t for t in out if t and not t.startswith("_"))


def _columns_in(path: Path) -> dict[str, set[str]]:
    """table -> column names this file passes to a write helper (S-286).

    Only literal `dict` payloads with literal string keys count. A payload built
    from a variable is invisible here, which is the same blind spot `_tables_in`
    records for dynamic table names — noted rather than papered over, because a
    manifest that looks more complete than it is becomes the thing people trust
    instead of the database.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return {}
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in _WRITE_FUNCS or len(node.args) < 2:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        for d in ast.walk(node.args[1]):
            if isinstance(d, ast.Dict):
                out.setdefault(first.value, set()).update(
                    k.value for k in d.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str))
    return out


def write_columns() -> dict[str, list[str]]:
    """Every column a production module writes, per table. Sorted, deduped.

    THE HALF THAT WAS MISSING. `write_tables()` answers "does the table exist",
    which is the S-166 question. On 2026-09-04 the ① book was taken down by a
    missing COLUMN on a table that existed — `interval_hours`, code deployed
    ahead of its migration — and every existing guard stayed green. The offline
    guard can only prove a migration FILE exists; only a live probe can prove it
    RAN. This is the contract half of that probe (see `/internal/schema-drift`).
    """
    out: dict[str, set[str]] = {}
    for p in sorted(_ROOT.rglob("*.py")):
        if _is_prod(p):
            for t, cols in _columns_in(p).items():
                out.setdefault(t, set()).update(cols)
    return {t: sorted(c) for t, c in sorted(out.items()) if t and not t.startswith("_")}


def manifest_path() -> Path:
    return _ROOT / "src" / "api" / "schema_manifest.json"
