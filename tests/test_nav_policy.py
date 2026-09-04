"""docs/NAV_POLICY.md, as CI (S-283).

WHY THIS FILE EXISTS. The policy document is the deliverable an allocator asks for
by name in operational due diligence. But a valuation policy that lives only in a
markdown file is the failure mode the policy itself warns about — "a policy that is
written but not followed is worse in diligence than no policy at all." MEMORY.md
already records the general form: **if a test enforces it, the test is the memory.**

So each test below pins one control from the policy, and names the section. When a
test here fails, either the code drifted or the policy changed; in the second case
the doc gets edited in the same commit, never the test alone.

The three defects this file was written to make unrepeatable (all S-283):
  P0-1  `_STATE_KEY` unscoped by `_INCEPTION_ID` → v4 inherited v3's NAV (1.047005)
        and v3's three-day-stale prices, booking +20.19% as one "daily" return.
  P0-2  `get_curve` computing `last/first` instead of measuring from unit NAV, which
        published a 12-day window return as the book's return AND excluded the
        contaminated first row from the headline.
  P0-3  No elected valuation point: `sleep(24*3600)` anchored to process start, so
        every Railway deploy re-anchored the mark. Intervals ran 10.6h–35.9h (3.38x)
        on rows labelled daily and feeding realized_vol_30d → gross exposure.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SIGNALS = _ROOT / "src" / "data" / "signals"
_POLICY = _ROOT / "docs" / "NAV_POLICY.md"

#: Books that strike a NAV. Each keeps its own curve and its own inception clock.
_BOOKS = [
    "beta_core_paper.py", "causal_paper.py", "combined_book.py", "dingge_paper.py",
    "fusion_paper.py", "scalable_paper.py", "two_layer_paper.py",
]


def _src(name: str) -> str:
    p = _SIGNALS / name
    if not p.exists():                      # a book may be retired; that is not a failure
        pytest.skip(f"{name} not present")
    return p.read_text()


# ── §7 Record continuity — inception scoping ─────────────────────────────────

@pytest.mark.parametrize("book", _BOOKS)
def test_state_key_is_scoped_by_inception_id(book):
    """A book with an inception identity must scope EVERY state artifact by it.

    `_recover_state_from_nav` filters Postgres by `inception_id`, which is correct
    and was never the hole. The hole was the cache in FRONT of Postgres: on the
    v3→v4 flip the old Redis dict was still there, `state.get("weights")` was
    truthy, and the guarded recovery path never ran. A control that protects the
    durable store while leaving the thing that answers first unscoped protects
    nothing — it just moves where you have to look.
    """
    src = _src(book)
    if "_INCEPTION_ID" not in src:
        pytest.skip(f"{book} has no inception identity — nothing to scope")
    m = re.search(r"^_STATE_KEY\s*=\s*(.+)$", src, re.M)
    assert m, f"{book}: no module-level _STATE_KEY found"
    decl = m.group(1)
    assert "_INCEPTION_ID" in decl, (
        f"{book}: _STATE_KEY = {decl.strip()} is NOT scoped by _INCEPTION_ID.\n"
        "This is S-283 exactly. A re-inception changes the durable filter but leaves "
        "the cache holding the previous incarnation's NAV, weights and mark_prices; "
        "the next mark then compounds onto a NAV it was meant to replace and "
        "differences against prices from the run that was voided.\n"
        "Fix: _STATE_KEY = f\"<book>:state:{_INCEPTION_ID}\"  (NAV_POLICY §7)"
    )


# ── §8 Return basis ──────────────────────────────────────────────────────────

#: Matched against `ast.unparse` output, NOT raw source. The first version of this
#: test was a regex over the file text and it flagged the COMMENT that documents the
#: old form — in a codebase that explains every fix in prose next to the fix, a
#: text-matching guard eventually fails on its own documentation and gets weakened
#: to shut it up. Parsing means the guard sees expressions and nothing else.
_LAST_OVER_FIRST = re.compile(
    r"""(last|rows\[-1\])\[['"](nav|benchmark_nav)['"]\]\s*/\s*"""
    r"""(first|rows\[0\])\[['"](nav|benchmark_nav)['"]\]""")


def _division_expressions(src: str) -> list[str]:
    """Every division actually evaluated in the module, as source text."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            try:
                out.append(ast.unparse(node))
            except Exception:                       # pragma: no cover — 3.8 fallback
                pass
    return out


@pytest.mark.parametrize("book", _BOOKS)
def test_cumulative_return_is_measured_from_unit_nav(book):
    """Cumulative return is `nav - 1`, never `last_nav / first_nav`.

    NAV is unit-based by construction (inception sets 1.0), so subtracting 1 IS the
    since-inception return and it cannot drift when rows are trimmed, paginated or
    filtered. Dividing by the first RETAINED row makes the published return depend
    on which rows happen to come back — and when the first row is itself wrong, the
    headline silently excludes the very row a reader needs to see.

    ① — the book that is the BENCHMARK for every other book — was the only one doing
    this. Every other book already computed `(navs[-1] - 1) * 100`.
    """
    hits = [e for e in _division_expressions(_src(book)) if _LAST_OVER_FIRST.search(e)]
    assert not hits, (
        f"{book}: cumulative return computed as `{hits[0]}` — a window return "
        "presented as the book's return (S-283 / NAV_POLICY §8).\n"
        "Fix: cum = last[\"nav\"] - 1.0"
    )


# ── §3 Valuation point ───────────────────────────────────────────────────────

def test_beta_core_declares_a_valuation_point():
    """Crypto has no close, so the valuation point must be ELECTED and named.

    `sleep(24*3600)` also 'elects' one — differently after every deploy, which is
    how v4's intervals ended up spanning 10.6h to 35.9h.
    """
    src = _src("beta_core_paper.py")
    assert "_VALUATION_POINT_UTC" in src, (
        "beta_core declares no valuation point. AICPA digital-asset guidance is "
        "explicit that a continuously-traded asset needs an elected daily cut-off; "
        "without one, 'daily return' is whatever the scheduler did (NAV_POLICY §3)."
    )
    assert "_VALUATION_POINT_TOLERANCE_MIN" in src, (
        "A valuation point without a tolerance is a target, not a control. A mark "
        "that cannot be struck near the point must be REFUSED, not struck late — "
        "marking late is what turns a missed day into next day's return."
    )


def test_nav_loops_sleep_to_a_wall_clock_time_not_a_duration():
    """No NAV-marking loop may sleep a bare 24h.

    `await sleep(24*3600)` anchors to PROCESS START. Railway redeploys on every
    push, so each deploy re-anchors the schedule and the mark time walks. This is
    the mechanism behind P0-3 — not a bug in any book, an absent control in all of
    them at once.
    """
    src = (_ROOT / "src" / "api" / "main.py").read_text()
    lines = src.split("\n")
    nav_loops = [
        "_causal_paper_loop", "_dingge_paper_loop", "_combined_book_loop",
        "_scalable_book_loop", "_beta_core_loop", "_two_layer_paper_loop",
        "_fusion_paper_loop", "_r76_paper_loop", "_pod_aggregator_loop",
        "_factor_tilt_loop",
    ]
    offenders = []
    for name in nav_loops:
        start = next((i for i, l in enumerate(lines)
                      if l.startswith(f"async def {name}(")), None)
        if start is None:
            continue
        body = lines[start:start + 80]
        end = next((i for i, l in enumerate(body[1:], 1)
                    if l.startswith("async def ") or l.startswith("@app.")), len(body))
        chunk = "\n".join(body[:end])
        if "_sleep_until_utc" not in chunk and "sleep(24 * 3600)" in chunk:
            offenders.append(name)
    assert not offenders, (
        f"NAV-marking loops still sleeping a bare duration: {offenders}.\n"
        "Use `await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)` so two consecutive "
        "marks are 24h apart regardless of deploys (S-283 / NAV_POLICY §3)."
    )


def test_interval_hours_is_recorded_and_never_defaulted():
    """Every NAV row carries the MEASURED gap since the previous mark.

    `mark_date - mark_date` is 24h by definition and would record the assumption
    instead of testing it. And an unmeasurable interval must stay None: a plausible
    default (24.0) would recreate precisely the failure this column exists to
    expose — an unknown rendered as a normal-looking number, which is the S-194
    "zero is the most dangerous failure value" lesson in a different column.
    """
    src = _src("beta_core_paper.py")
    assert '"interval_hours"' in src, (
        "beta_core_nav rows do not carry interval_hours — a row cannot then "
        "distinguish one day of market from 35.9 hours labelled one day."
    )
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_interval_hours"), None)
    assert fn is not None, "beta_core must expose _interval_hours()"
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
            assert node.value.value is None, (
                f"_interval_hours returns the constant {node.value.value!r}. An "
                "unmeasurable interval must be None, never a plausible default."
            )


def test_annualization_requires_a_daily_series():
    """Sharpe/vol/annualized figures assume one observation per day — check it.

    A footnoted wrong number still gets quoted, so the reading surface suppresses
    rather than annotates (NAV_POLICY §12).
    """
    src = _src("beta_core_paper.py")
    assert "daily_series_ok" in src, (
        "get_curve does not test whether its observations are actually daily. "
        "`annualization_is_meaningful` gated on row COUNT alone passes happily on "
        "60 rows sampled at intervals from 10.6h to 35.9h."
    )
    assert re.search(r"annualization_is_meaningful\"?\s*:\s*.*daily_series_ok", src), (
        "annualization_is_meaningful must depend on daily_series_ok, not only on n."
    )


# ── §6 Materiality thresholds exist as constants, not as prose ───────────────

def test_policy_document_exists_and_pins_its_thresholds():
    """The policy must carry numeric thresholds a reader can act on.

    A valuation policy whose error section says "material errors are corrected" is
    the thing CSSF 24/856 replaced: the threshold, the classification and the
    correction path all have to be stated in advance, because deciding materiality
    after seeing the error is how every number becomes immaterial.
    """
    assert _POLICY.exists(), "docs/NAV_POLICY.md is missing — see S-283"
    doc = _POLICY.read_text()
    for token in ("0.25%", "0.50%", "0.10%"):
        assert token in doc, f"NAV_POLICY §6 lost its {token} threshold"
    for section in ("§3", "§6", "§7", "§8"):
        assert section in doc, f"NAV_POLICY lost {section}"
    # The qualitative override is the part percentage thresholds miss, and the part
    # most likely to be quietly dropped in a future edit.
    assert "regardless of magnitude" in doc, (
        "NAV_POLICY §6 lost the qualitative override. A 0.04% error that flips "
        "excess from -0.01% to +0.03% turns 'the layer contributed nothing' into "
        "'the layer added value'; a percentage threshold alone is blind to it."
    )


# ── Every column a NAV row writes must exist somewhere authoritative ─────────

def _snapshot_columns(table: str) -> set[str]:
    snap = _ROOT / "schema" / "public_columns.json"
    if not snap.exists():
        pytest.skip("schema/public_columns.json missing")
    import json
    return set(json.loads(snap.read_text()).get("tables", {}).get(table, []))


def _migration_added_columns(table: str) -> set[str]:
    """Columns a checked-in migration adds to `table`.

    A column is legitimate if the live snapshot has it OR a migration file adds
    it. This does not prove the migration was RUN — that is the deploy check —
    but it does make "insert a column that exists nowhere" impossible to push.
    """
    out: set[str] = set()
    mig = _ROOT / "migrations"
    if not mig.exists():
        return out
    pat = re.compile(
        rf"ALTER\s+TABLE\s+(?:public\.)?{re.escape(table)}\s+"
        r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I | re.S)
    for f in mig.glob("*.sql"):
        out.update(m.group(1) for m in pat.finditer(f.read_text()))
    return out


def test_beta_core_nav_insert_writes_only_columns_that_exist():
    """The ① book's INSERT payload must not name a column that exists nowhere.

    PostgREST answers an unknown column with 400. `supabase_insert_table` reports
    that by RETURNING False, `_write` propagates it, and the book logs
    "MARK NOT PERSISTED" and stops — process healthy, endpoint healthy, one table
    quietly stops filling. That is S-138/S-185, and the existing guard for it
    (`test_table_columns_match_the_code`) is scoped to `api_keys` only, so it
    would not have fired here. A control that stops at the incident that created
    it is the same shape as S-283 itself.

    Adding `interval_hours` to this payload is precisely the change that would
    have killed the ① book had the migration not landed first — so the guard is
    written from inside the change that needed it.
    """
    # Parsed, not regexed. The first version matched `"key":` at line start and
    # therefore missed a key appended to an existing line — a guard that reads
    # formatting instead of structure. Caught by mutation-testing the guard.
    src = _src("beta_core_paper.py")
    written: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "supabase_insert_table"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "beta_core_nav"):
            continue
        for row in ast.walk(node.args[1]):
            if isinstance(row, ast.Dict):
                written.update(k.value for k in row.keys
                               if isinstance(k, ast.Constant) and isinstance(k.value, str))
    assert written, "could not parse the beta_core_nav insert payload"
    known = _snapshot_columns("beta_core_nav") | _migration_added_columns("beta_core_nav")
    if not known:
        pytest.skip("beta_core_nav absent from the schema snapshot")
    unknown = sorted(written - known)
    assert not unknown, (
        f"beta_core_nav INSERT writes columns that exist in neither the schema "
        f"snapshot nor any migration: {unknown}.\n"
        "PostgREST will answer 400, the write returns False, and the book stops "
        "marking without raising. Add the column in migrations/*.sql first."
    )


# ── §8 The two-book separation on the trading surface ────────────────────────

def test_positions_endpoint_does_not_publish_a_blended_return():
    """The cash wallet and the notional sleeve have no common denominator.

    `total_pnl / _DEFAULT_BALANCE` published 65.509% for a book whose actual return
    was +1.55%. /api/v1/trading/metrics had separated the books since the
    2026-07-15 Loop Watch; the positions endpoint — and the MCP tool wrapping it —
    never got the fix.
    """
    src = (_ROOT / "src" / "api" / "routers" / "trading.py").read_text()
    start = src.index('@router.get("/api/v1/trading/positions")')
    end = src.index("@router.delete", start)
    body = src[start:end]
    assert "total_pnl / _DEFAULT_BALANCE" not in body, (
        "positions endpoint divides P&L by the starting cash balance. The sleeve "
        "runs on REBAL_SLEEVE_NAV and never debits cash (S-283 / NAV_POLICY §8)."
    )
    assert "sleeve_book" in body and "cash_book" in body, (
        "positions endpoint must report the two books separately, each with its "
        "own named denominator."
    )
