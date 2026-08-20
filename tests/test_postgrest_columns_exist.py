"""Every PostgREST filter column must exist on the table it filters (S-185).

WHY. `supabase_fresh_t1_symbols` — the S-180 guard deciding whether a T2 writer
may shadow a live T1 — filtered `cis_scores` on `created_at`. That column does
not exist; the timestamp is `recorded_at`. PostgREST answers 400, the helper
correctly mapped that to `None` ("could not ask"), and the hourly writer
correctly treated `None` as "do not write".

Every layer behaved exactly as designed, and the net effect was that the hourly
T2 snapshot silently wrote nothing for two cycles. **A fail-closed guard turns a
typo into an outage that emits no error anywhere** — process healthy, endpoint
healthy, and one table simply stops filling. That is a worse detection problem
than the bug the guard was added to prevent, so the guard needs a guard.

Sharper: the identical mistake had already produced
`ERROR: 42703: column "created_at" does not exist` in an ad-hoc query in the
SAME session, an hour before this code was written. Knowing a fact and encoding
it are different acts; only the second survives the next session.

TWO THINGS THIS TEST GOT WRONG FIRST, both worth keeping:

1. It validated against `scripts/*.sql`. That produced THREE false positives and
   zero true ones — `asset_embeddings.superseded_reason` and
   `beta_core_nav.exposure_cap` exist live and appear in no CREATE TABLE, because
   the .sql files have drifted from the database. Validating against a stale
   definition is worse than not validating: a guard that flags correct code gets
   switched off by whoever hits it next. Authority is now `schema/public_columns.json`,
   snapshotted from `information_schema`.

2. It scanned a 5-line text window, which glued two adjacent URLs together and
   attributed `event_type` (a real column of `beta_core_nav_q_meta`) to
   `beta_core_nav_q`. URLs are now recovered via AST so each stays one string.

Net: 4 sites flagged by the first version, 4 of them correct code, 0 real bugs.
The rewrite finds the real one and nothing else.
"""
import ast
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "schema/public_columns.json"

_OPS = "eq|neq|gt|gte|lt|lte|like|ilike|is|in|cs|cd|not|fts|plfts"
_RESERVED = {"select", "order", "limit", "offset", "on_conflict", "and", "or",
             "columns", "apikey"}

# Table name held in a module constant rather than written inline.
_CONST_TABLES = {"_SB_TABLE": "cis_scores"}


def _schema() -> dict[str, set[str]]:
    raw = json.loads(SNAPSHOT.read_text())
    return {t: set(c) for t, c in raw["tables"].items()}


def _literal_skeleton(node) -> str:
    """Reconstruct a string expression's LITERAL parts, with `{expr}` holes.

    Handles f-strings, implicit adjacent-literal concatenation and `+`. The
    interpolated values are irrelevant here — only the URL's shape matters.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                name = getattr(v.value, "id", None)
                out.append("{%s}" % name if name else "{}")
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_skeleton(node.left) + _literal_skeleton(node.right)
    return ""


def _postgrest_urls():
    """(file, line, url_skeleton) for every string containing /rest/v1/."""
    found = []
    for path in (ROOT / "src").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.JoinedStr, ast.BinOp, ast.Constant)):
                continue
            sk = _literal_skeleton(node)
            if "/rest/v1/" in sk:
                found.append((str(path.relative_to(ROOT)), node.lineno, sk))
    # A concatenation reports both the whole and its parts; keep the longest
    # skeleton per (file, line) so the URL is scored once, intact.
    best: dict[tuple, str] = {}
    for f, ln, sk in found:
        if len(sk) > len(best.get((f, ln), "")):
            best[(f, ln)] = sk
    return [(f, ln, sk) for (f, ln), sk in sorted(best.items())]


def _refs():
    """(file, line, table, column) — filters paired with their OWN table."""
    refs, unresolved = [], []
    for path, line, url in _postgrest_urls():
        m = re.search(r"/rest/v1/(\{?[A-Za-z_][A-Za-z0-9_]*\}?)", url)
        if not m:
            continue
        table = m.group(1)
        if table.startswith("{"):
            table = _CONST_TABLES.get(table.strip("{}"))
            if not table:
                unresolved.append((path, line))
                continue
        # Only the query string, and only up to the end of THIS url.
        qs = url.split("?", 1)[1] if "?" in url else ""
        for cm in re.finditer(rf"[?&]?([a-z_][a-z0-9_]*)=(?:{_OPS})\.", qs):
            col = cm.group(1)
            if col not in _RESERVED:
                refs.append((path, line, table.lower(), col))
    return refs, unresolved


def test_every_postgrest_filter_column_exists():
    schema = _schema()
    refs, _ = _refs()
    assert refs, "found no PostgREST filters — the scanner is broken"

    bad = []
    for path, line, table, col in refs:
        if table not in schema:
            continue          # not in the snapshot; see the blind-spot test
        if col not in schema[table]:
            near = ", ".join(sorted(c for c in schema[table]
                                    if col.split("_")[-1] in c)) or "—"
            bad.append(f"{path}:{line}  {table}.{col} does not exist "
                       f"(did you mean: {near})")

    assert not bad, (
        "PostgREST filter on a column the table does not have. PostgREST 400s, "
        "callers map that to 'could not ask', and a fail-closed writer then "
        "stops writing — with no error raised anywhere:\n  " + "\n  ".join(bad))


def test_the_blind_spot_is_named():
    """An empty check and a passing check look identical from outside."""
    schema = _schema()
    refs, unresolved = _refs()
    checked = {t for _, _, t, _ in refs if t in schema}
    skipped = {t for _, _, t, _ in refs if t not in schema}
    assert checked, (
        f"zero tables verifiable — snapshot has {len(schema)} tables and none "
        f"matched the {len(refs)} filters found. Passing vacuously.")
    print(f"\n  verified {len(refs)} filter(s) across {len(checked)} table(s)"
          f"\n  absent from snapshot, skipped: {sorted(skipped) or '—'}"
          f"\n  table not statically resolvable: {len(unresolved)} site(s)")


def test_snapshot_is_present_and_plausible():
    assert SNAPSHOT.exists(), (
        "schema/public_columns.json is the authority for this check — "
        "regenerate it (see schema/README.md) rather than deleting the test")
    schema = _schema()
    assert len(schema) > 50, f"snapshot has only {len(schema)} tables — truncated?"
    assert "recorded_at" in schema["cis_scores"]
    assert "created_at" not in schema["cis_scores"], (
        "if cis_scores ever gains created_at, S-185's specific pin below needs "
        "revisiting — but the bug was that the code used a column that has "
        "never existed")


def test_the_occupancy_query_filters_on_a_column_that_exists():
    """The specific instance, pinned."""
    src = (ROOT / "src/api/store.py").read_text()
    fn = src.split("async def supabase_fresh_t1_symbols")[1].split("\nasync def ")[0]
    assert "recorded_at=gte." in fn, "must filter cis_scores on recorded_at"
    assert "created_at=gte." not in fn, (
        "cis_scores has no created_at — PostgREST 400s, the helper returns "
        "None, and the hourly T2 writer stops writing silently")
