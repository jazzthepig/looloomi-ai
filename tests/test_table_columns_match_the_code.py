"""
Guard: the columns the code writes exist in the schema the code claims (S-138).

WHAT HAPPENED. `/api/v1/keys` POSTed a column named `intended_use`. The live
`api_keys` table has never had that column — it has `notes`. PostgREST answers an
unknown column with a 400, `_sb_post` collapsed every failure into the string
"Key storage failed", and so the endpoint returned the same opaque 500 from the
day it shipped. Zero keys were ever issued. `scripts/supabase_all_tables.sql`
declared `intended_use` too, so the file and the table disagreed and nothing
compared them.

THE PART WORTH REMEMBERING IS NOT THE TYPO. It is that a one-word bug survived
THREE confident diagnoses:

  1. "anon lacks INSERT on api_keys"          — it does not
  2. "SUPABASE_SERVICE_KEY is missing"        — it was not the cause
  3. "id has no sequence"                     — id is GENERATED ALWAYS AS IDENTITY,
                                                and information_schema reports
                                                column_default = null for identity
                                                columns, which is EXACTLY what a
                                                missing default looks like

Each was plausible, each was invented to fill the space the error message left
empty, and each cost a round trip through the one person with console access. A
generic failure message does not merely fail to help — it funds wrong answers.
Both halves are fixed: the column name, and `_sb_post` now passes PostgREST's own
message through (it describes OUR schema, not the caller's data).

WHAT THIS SUITE CHECKS. Offline, so it can sit in preflight: every column name a
router writes to a table must appear in that table's CREATE TABLE in
scripts/supabase_all_tables.sql. That catches code-vs-declared drift. It does NOT
catch declared-vs-live drift — only the live catalog can, and preflight is
offline by contract. So the SQL file carries the live column name and a note
saying why, and `scripts/verify_live_schema.sql` is the online half.

Run: python3 -m tests.test_table_columns_match_the_code
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


def _declared_columns(sql: str) -> dict[str, set[str]]:
    """{table: {column, …}} from CREATE TABLE blocks."""
    out: dict[str, set[str]] = {}
    for m in re.finditer(
            r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\((.*?)\n\);",
            sql, re.S | re.I):
        table, body = m.group(1), m.group(2)
        cols = set()
        for line in body.splitlines():
            line = line.split("--")[0].strip()
            if not line or line.upper().startswith(
                    ("PRIMARY", "UNIQUE", "FOREIGN", "CONSTRAINT", "CHECK")):
                continue
            tok = line.split()[0].strip(",")
            if re.fullmatch(r"\w+", tok):
                cols.add(tok.lower())
        out[table.lower()] = cols
    return out


_SQL = (_ROOT / "scripts/supabase_all_tables.sql").read_text(encoding="utf-8")
_DECLARED = _declared_columns(_SQL)


def test_the_sql_file_parses_into_tables() -> None:
    check("CREATE TABLE blocks parsed", len(_DECLARED) >= 10,
          f"only {len(_DECLARED)} tables found — the regex has drifted from the file")
    check("api_keys is among them", "api_keys" in _DECLARED, str(sorted(_DECLARED)[:8]))


def test_api_keys_writes_only_columns_that_exist() -> None:
    """The exact failure. The payload dict in keys.py is a literal, so its keys can
    be read without running anything."""
    src = (_ROOT / "src/api/routers/keys.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    written: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fn != "_sb_post" or not node.args:
            continue
        tbl = getattr(node.args[0], "value", None)
        if tbl != "api_keys" or len(node.args) < 2:
            continue
        payload = node.args[1]
        if isinstance(payload, ast.Dict):
            written |= {k.value for k in payload.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}

    check("the api_keys payload was found", bool(written),
          "no _sb_post('api_keys', {...}) literal — the scan needs updating")
    missing = written - _DECLARED.get("api_keys", set())
    check("every written column is declared", not missing,
          f"writes columns that do not exist: {sorted(missing)}")
    check("it writes `notes`, not `intended_use`",
          "notes" in written and "intended_use" not in written,
          f"payload keys: {sorted(written)}")


def test_no_router_selects_intended_use() -> None:
    """The same wrong name was ALSO in analytics.py's PostgREST `select`, which
    fails the same way and would have re-broken the page the moment keys existed.
    One typo, two call sites — fixing the one being debugged is not fixing the bug."""
    hits = []
    for p in (_ROOT / "src/api/routers").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0]
            if "intended_use" in code and "body.intended_use" not in code \
                    and "intended_use: Optional" not in code \
                    and '"intended_use":' not in code:
                hits.append(f"{p.name}:{i}")
    check("no router reads/writes a column named intended_use", not hits, str(hits))


def test_the_error_message_names_the_cause() -> None:
    """A generic failure does not merely fail to help — it funds plausible wrong
    answers. This one funded three."""
    src = (_ROOT / "src/api/routers/keys.py").read_text(encoding="utf-8")
    check("PostgREST's own message is passed through",
          'detail = f"Key storage failed: {body_msg}"' in src,
          "the endpoint must say WHY, not just that it failed")
    check("the response is not a bare constant",
          src.count('detail="Key storage failed"') == 0,
          "a bare 'Key storage failed' is still being raised somewhere")


def test_the_sql_file_records_why_the_name_matters() -> None:
    """The file is the thing a future agent will trust. If it just says `notes`
    with no history, the next person to 'tidy' it back to intended_use will have
    no reason not to."""
    i = _SQL.lower().find("create table if not exists api_keys")
    block = _SQL[i:i + 1400]
    check("api_keys.notes carries its provenance",
          "notes" in block and "NAME MATTERS" in block,
          "the live column name must be defended in the file, not just written")


if __name__ == "__main__":
    print("── table columns vs the code that writes them (S-138) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ written columns match the declared schema")
