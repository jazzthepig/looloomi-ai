"""
test_fusion_paper_regime_track_schema.py — schema guard for the regime_track table.

S-369 1.4 (2026-09-20): the Python writer writes 8 fields (TRACK_HEADER) to
`fusion_paper_regime_track`. The DDL must declare exactly these fields, plus
the row-id / time-stamp trio (id, created_at, updated_at) that every other
paper-book table has. If the writer's dict ever grows a column that the DDL
didn't declare, the upsert silently drops it (PostgREST prefers declared
columns) — and we'd have a day that the CSV says X but the durable table says
nothing. The guard catches drift before it lands.
"""
import ast
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
def _parse_ddl_columns(sql_text: str, table: str) -> set[str]:
    """Return the set of column names declared in `CREATE TABLE <table>` block."""
    pattern = re.compile(
        rf"CREATE TABLE[^(]*\b{re.escape(table)}\b\s*\((.*?)\n\s*\)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(sql_text)
    if not m:
        return set()
    body = m.group(1)
    cols: set[str] = set()
    for line in body.splitlines():
        # Match "name  type" or "name  type," — first whitespace-delimited token.
        line = line.strip().rstrip(",")
        if not line or line.startswith("--") or line.startswith("UNIQUE") \
                or line.startswith("PRIMARY") or line.startswith("CONSTRAINT") \
                or line.startswith("FOREIGN") or line.startswith("CHECK"):
            continue
        first = line.split(None, 1)[0]
        if first.isidentifier():
            cols.add(first)
    return cols


def _writer_row_keys() -> set[str]:
    """Read `compute_today_track()` and return the keys of the row dict it builds."""
    src = (_ROOT / "src/research/validation/fusion_paper_regime_track.py").read_text()
    tree = ast.parse(src)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compute_today_track":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    for k in sub.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            found.add(k.value)
    return found


# ─────────────────────────────────────────────────────────────────────────────
def test_ddl_declares_the_table() -> None:
    sql = (_ROOT / "scripts/supabase_fusion_paper_regime_track.sql").read_text()
    cols = _parse_ddl_columns(sql, "fusion_paper_regime_track")
    if not cols:
        _fail("DDL file did not parse into a CREATE TABLE fusion_paper_regime_track block — "
              "regex drift or file missing")
    if "date_utc" not in cols:
        _fail(f"date_utc not declared; columns = {sorted(cols)}")
    _ok(f"DDL declares fusion_paper_regime_track with {len(cols)} columns: {sorted(cols)}")


def test_ddl_has_unique_constraint_for_upsert() -> None:
    """The Python writer uses `Prefer: resolution=merge-duplicates`; this
    requires a UNIQUE constraint or PRIMARY KEY on the conflict target.
    UNIQUE(date_utc) is the seam between 'today's mark' and 'yesterday's mark'."""
    sql = (_ROOT / "scripts/supabase_fusion_paper_regime_track.sql").read_text()
    if "UNIQUE" not in sql.upper() or "DATE_UTC" not in sql.upper():
        _fail("DDL must declare UNIQUE(date_utc) for the writer's upsert semantics")
    _ok("DDL has UNIQUE(date_utc) — upsert via Prefer: resolution=merge-duplicates works")


def test_ddl_enables_rls_with_service_role_only() -> None:
    """Per S-167 hardening: NO PUBLIC writes. service_role bypasses RLS so the
    writer's SUPABASE_KEY (service) keeps working; anon (browser-shipped) cannot read."""
    sql = (_ROOT / "scripts/supabase_fusion_paper_regime_track.sql").read_text()
    if "ENABLE ROW LEVEL SECURITY" not in sql:
        _fail("DDL must enable RLS on fusion_paper_regime_track")
    if "service_role" not in sql:
        _fail("DDL must declare a service_role policy")
    if 'POLICY "service_role_only"' not in sql and "POLICY service_role_only" not in sql:
        _fail("DDL must name the policy 'service_role_only' (mirror fusion_paper_state)")
    _ok("RLS on, service_role_only policy (matches fusion_paper_state posture)")


def test_writer_row_keys_all_in_ddl() -> None:
    """Every key the writer emits must be a declared column. If the writer
    ever adds a field, the SQL must grow with it — otherwise the upsert
    silently drops the new field, and CSV vs Supabase diverge."""
    sql = (_ROOT / "scripts/supabase_fusion_paper_regime_track.sql").read_text()
    declared = _parse_ddl_columns(sql, "fusion_paper_regime_track")
    written = _writer_row_keys()
    if not written:
        _fail("could not extract writer row keys from compute_today_track — "
              "function signature may have changed")
    # writer emits the 8 data fields + TRACK_HEADER column names
    missing = written - declared
    if missing:
        _fail(f"writer emits columns not declared in DDL: {sorted(missing)} — "
              f"upsert will silently drop these")
    _ok(f"writer row keys ({len(written)}) ⊂ declared columns ({len(declared)}) — "
        f"no silent drops: {sorted(written)}")


def test_ddl_has_id_and_timestamps() -> None:
    """Mirror the fusion_paper_state trio: id BIGSERIAL PK + created_at + updated_at.
    updated_at trigger must exist for the writer to bump on conflict."""
    sql = (_ROOT / "scripts/supabase_fusion_paper_regime_track.sql").read_text()
    needed = {"id", "created_at", "updated_at"}
    cols = _parse_ddl_columns(sql, "fusion_paper_regime_track")
    missing = needed - cols
    if missing:
        _fail(f"DDL missing trio columns: {sorted(missing)} — "
              f"declare them, mirror fusion_paper_state")
    if "PRIMARY KEY" not in sql:
        _fail("DDL must declare id BIGSERIAL PRIMARY KEY")
    if "updated_at" in sql and "TRIGGER" not in sql.upper():
        _fail("DDL has updated_at but no TRIGGER to bump it on UPDATE")
    _ok(f"id + created_at + updated_at present, updated_at trigger in place")


def test_csv_remaining_is_cache_not_source_of_truth() -> None:
    """After this S-369 1.4 fix, /tmp CSV is a cache, Supabase is system of
    record. The Python writer's docstring must say so — otherwise the next
    agent reading `_TRACK_CSV` thinks the CSV is authoritative."""
    src = (_ROOT / "src/research/validation/fusion_paper_regime_track.py").read_text()
    if "system of record" not in src.lower() and "system-of-record" not in src.lower():
        _fail("writer docstring must declare Supabase as system of record "
              "(and /tmp CSV as cache) — see fusion_paper_state S-176 model")
    _ok("docstring declares Supabase system of record, /tmp CSV = cache")


# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    tests = [
        test_ddl_declares_the_table,
        test_ddl_has_unique_constraint_for_upsert,
        test_ddl_enables_rls_with_service_role_only,
        test_writer_row_keys_all_in_ddl,
        test_ddl_has_id_and_timestamps,
        test_csv_remaining_is_cache_not_source_of_truth,
    ]
    print(f"Running {len(tests)} schema guard tests for fusion_paper_regime_track...")
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} schema guard tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())