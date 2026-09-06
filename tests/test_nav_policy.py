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


def test_the_valuation_point_tolerance_is_obeyed_not_merely_spelled():
    """`_VALUATION_POINT_TOLERANCE_MIN` must be READ by marking code.

    THE REASON THIS TEST EXISTS IS THAT ITS PREDECESSOR WAS WORSE THAN NOTHING.
    `test_beta_core_declares_a_valuation_point` asserted the constant appeared in
    the file. It did — as a definition and a comment, with **zero readers**. So
    on 2026-09-04 v5's inception row was struck at 07:00:52 UTC against a 00:05
    point, 6h55m out, and every guard stayed green.

    S-263 is the same shape (`LAST_REGIME_QUORUM`: 2 writes, 0 reads) and the
    S-284 entry names it: *written is not executed, executed is not observable*.
    The sharper version, from this one: **a rule that is falsely guarded is worse
    than an unguarded rule.** An unguarded rule invites a guard; a guard that
    checks spelling closes the question and sends the next reader elsewhere.
    """
    src = _src("beta_core_paper.py")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "mark_and_rebalance"), None)
    assert fn is not None, "beta_core must expose mark_and_rebalance()"
    # Must appear in a COMPARISON, not merely be loaded. The first version of
    # this check accepted any `Load` of the name — and an f-string interpolation
    # (`f"tolerance is {_VALUATION_POINT_TOLERANCE_MIN} min"`) is a genuine Load.
    # Mutating the real threshold to `> 999999` therefore left the guard green,
    # because the constant was still *mentioned* in the refusal message.
    #
    # Fourth guard in this file fooled by prose (see S-283, S-285). The pattern is
    # now explicit: **a control is used when it constrains a branch, not when it
    # appears in a string describing the branch.** Assert on the Compare node.
    compared = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Compare)
        and any(isinstance(x, ast.Name) and x.id == "_VALUATION_POINT_TOLERANCE_MIN"
                for x in [n.left, *n.comparators])
    ]
    assert compared, (
        "_VALUATION_POINT_TOLERANCE_MIN is never COMPARED against in "
        "mark_and_rebalance — the constant is spelled, not obeyed. Mentioning it "
        "in a log or refusal message does not count. The mark path must compare "
        "its own strike time against the point and REFUSE outside tolerance "
        "(NAV_POLICY §3)."
    )
    # ...and the refusal must be a refusal, not a warning.
    seg = ast.get_source_segment(src, fn) or ""
    assert "outside_valuation_point" in seg, (
        "the tolerance is read but nothing returns a refusal — a control that "
        "logs and proceeds is the substitute-instead-of-refuse pattern S-194 "
        "exists to forbid."
    )


def test_a_mark_far_from_the_valuation_point_is_actually_refused():
    """Behavioural, not structural — because the structural version has a hole.

    The AST guard above requires `_VALUATION_POINT_TOLERANCE_MIN` to appear in a
    Compare. Mutation testing found that `if False and _off_by > TOLERANCE:` keeps
    the Compare node, keeps the refusal string, and disables the control. Four
    guards in this file have now been fooled by something that *looks* like use
    (source text, an f-string interpolation, a dead branch), and each time the
    answer was a finer static check that the next trick walked around.

    So stop refining the reader and CALL THE FUNCTION. A behavioural assertion
    cannot be satisfied by anything except the behaviour. This is the same move
    the codebase already made for `/internal/cis-scores/schema`: a live echo beats
    a declaration, because a declaration is a claim and an echo is an observation.
    """
    import asyncio
    import src.data.signals.beta_core_paper as bc

    recorded, loaded = [], []

    async def _fake_record(control, action, reason, **kw):
        recorded.append((control, action))

    async def _fake_load_panel():
        loaded.append(1)                      # must NEVER run — refusal comes first
        raise AssertionError("panel loaded despite being outside the valuation point")

    orig_rec, orig_load, orig_off = (
        bc._record_exception, bc._load_panel, bc._minutes_from_valuation_point)
    bc._record_exception = _fake_record
    bc._load_panel = _fake_load_panel
    bc._minutes_from_valuation_point = lambda *a, **k: 415.0   # v5's actual 6h55m
    try:
        res = asyncio.run(bc.mark_and_rebalance(dry_run=False))
    finally:
        bc._record_exception, bc._load_panel, bc._minutes_from_valuation_point = (
            orig_rec, orig_load, orig_off)

    assert res.get("status") == "skipped" and res.get("reason") == "outside_valuation_point", (
        f"a mark struck 415 min from the valuation point returned {res!r} instead "
        "of refusing. This is the exact condition that produced v5's inception row "
        "at 07:00:52 UTC against a 00:05 point (NAV_POLICY §3)."
    )
    assert not loaded, "the panel was loaded before the valuation-point check"
    assert ("valuation_point", "refused") in recorded, (
        "the refusal was not written to nav_exceptions — refusing invisibly is "
        "still a silent failure (S-285)."
    )


def test_the_first_mark_after_a_deploy_also_waits_for_the_point():
    """The leading sleep matters as much as the trailing one.

    S-283 pointed the *trailing* sleep at a wall-clock target and stopped, so
    marks 2..N landed on the point and mark 1 did not. Railway redeploys on every
    push, which makes "mark 1" the common case, not the edge case.

    Same partial move as scoping the inception filter to Postgres but not Redis:
    the guard covers the path you were looking at and misses the path that runs
    first. **The first iteration of a loop is a path.**
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
        head = "\n".join(lines[start:start + 12])
        pre_loop = head.split("while True")[0]
        if "_await_valuation_point" not in pre_loop:
            offenders.append(name)
    assert not offenders, (
        f"NAV loops that mark once on boot before waiting for the valuation "
        f"point: {offenders}.\n"
        "Add `await _await_valuation_point()` after the warmup sleep and before "
        "`while True` (S-286 / NAV_POLICY §3)."
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


# ── §4/§5 Priceable is not the same as priced today ──────────────────────────

def test_the_panel_loader_can_report_which_closes_were_carried():
    """`load_binance_panel` must be able to say which cells it forward-filled.

    The fill is CORRECT for research — a vol estimate needs a contiguous series
    and a NaN hole is worse than a repeat. It is wrong for a book striking a NAV,
    and for its whole life it was indistinguishable: `close[-1, j]` held a value
    carried from days ago with nothing to mark it, so a symbol that stopped
    updating arrived as a live quote.

    Not a new signature for everyone — fourteen call sites unpack four values,
    and a guard that forces a repo-wide edit is a guard that gets reverted.
    """
    src = (_ROOT / "src" / "research" / "strategies" / "causal_positioning.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "load_binance_panel"), None)
    assert fn is not None, "load_binance_panel is gone — update this guard"
    kwonly = {a.arg for a in fn.args.kwonlyargs}
    assert "with_fill_mask" in kwonly, (
        "load_binance_panel cannot report its forward-fill. Without the mask a "
        "carried close is indistinguishable from an observed one, which is how a "
        "stale symbol passes the 80% coverage floor (S-287 / NAV_POLICY §4)."
    )
    arities = {len(r.value.elts) for r in ast.walk(fn)
               if isinstance(r, ast.Return) and isinstance(r.value, ast.Tuple)}
    assert arities == {4, 5}, (
        f"expected both a 4-tuple (default, existing callers) and a 5-tuple "
        f"(with the mask); got arities {sorted(arities)}"
    )


def test_beta_core_excludes_stale_closes_from_its_price_dict():
    """A carried close must not enter `px`.

    `px` fed two conditions — not-NaN and positive — and a forward-filled value
    satisfies both. S-194 stopped the book confusing "no data" with "no movement";
    the layer beneath it was still confusing "stale data" with "data". Excluding
    the name lets equal-weighting renormalise over what is actually observable,
    and lets the coverage floor refuse when too much of the book goes that way —
    which is what the floor is for.
    """
    src = _src("beta_core_paper.py")
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "_load_panel"), None)
    assert fn is not None, "_load_panel is gone — update this guard"
    seg = ast.get_source_segment(src, fn) or ""
    assert "with_fill_mask=True" in seg, (
        "_load_panel does not request the fill mask, so it cannot tell a carried "
        "close from an observed one (S-287)."
    )
    # The exclusion must actually constrain the comprehension building `px`.
    px_assign = next((n for n in ast.walk(fn)
                      if isinstance(n, ast.Assign)
                      and any(getattr(t, "id", None) == "px" for t in n.targets)), None)
    assert px_assign is not None, "px is no longer a simple assignment — update this guard"
    conds = ast.unparse(px_assign)
    assert "_stale_idx" in conds, (
        "px is built without excluding forward-filled closes. A stale price that "
        "passes not-NaN and positive is exactly what the coverage floor cannot "
        "see (S-287 / NAV_POLICY §4)."
    )


def test_stale_exclusions_are_recorded_even_when_the_mark_succeeds():
    """Dropping names for staleness is an event, not a detail.

    It used to be invisible in both directions: the book marked the stale name,
    and once excluded it would have vanished into a log line. "Was the panel
    whole today" has to be answerable after the fact, which means a row.
    """
    src = _src("beta_core_paper.py")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "mark_and_rebalance")
    seg = ast.get_source_segment(src, fn) or ""
    assert "price_freshness" in seg and "stale_names" in seg, (
        "mark_and_rebalance does not record stale-name exclusions to "
        "nav_exceptions (S-287 / NAV_POLICY §10)."
    )


# ── §3/§10 A refusal must leave a trace, on a different path ─────────────────

def test_every_refusal_path_records_an_exception():
    """Each `status: skipped / mark_failed / inception_failed` must log first.

    THE INCIDENT (2026-09-04). `_INCEPTION_ID` moved to v5 and deployed while the
    migration adding `interval_hours` had not run. Every insert 400'd, `_write`
    returned False, the book logged one line to stdout and stopped. The curve
    endpoint answered `{"days": 0}` — **identical to a book that had never been
    asked to run.** Refusing correctly and recording nothing is still a silent
    failure; the refusal was right and its invisibility was the defect.
    """
    src = _src("beta_core_paper.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "mark_and_rebalance")

    bad = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        keys = {k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "status" not in keys:
            continue
        status = next((v.value for k, v in zip(node.value.keys, node.value.values)
                       if isinstance(k, ast.Constant) and k.value == "status"
                       and isinstance(v, ast.Constant)), None)
        if status not in ("skipped", "mark_failed", "inception_failed"):
            continue
        # Walk back through the enclosing statements for a _record_exception await.
        seg = ast.get_source_segment(src, fn) or ""
        idx = seg.find(ast.unparse(node)[:60])
        window = seg[max(0, idx - 1400):idx]
        if "_record_exception(" not in window:
            bad.append(status + " @ " + ast.unparse(node)[:70])
    assert not bad, (
        "refusal paths that record nothing: " + "; ".join(bad) + "\n"
        "A refused mark must write to nav_exceptions BEFORE returning — on a "
        "different table via a different insert, because the commonest reason to "
        "refuse is that the NAV write path itself is broken (NAV_POLICY §3/§10)."
    )


def test_refusals_do_not_write_a_nav_row():
    """A refusal must not be recorded as a beta_core_nav row.

    A row in the NAV table asserts a NAV was struck; the content of a refusal is
    that none was. Recording "no NAV" as a NAV row with an annotation is the S-194
    shape one table over. NAV_POLICY §3 said to do this in v1 and was corrected
    the same day — by writing the code.
    """
    # Check the TABLE `_record_exception` inserts into, not whether the string
    # "beta_core_nav" appears anywhere in the call. The first version asserted the
    # latter and went red on the diagnostic text inside a reason message ("Check
    # beta_core_nav columns against the insert payload") — the THIRD text-matching
    # guard in this file to trip on prose rather than behaviour. In a codebase that
    # explains itself in place, a guard that reads strings will eventually fail on
    # its own documentation, and the next person weakens it to restore green.
    # House rule for this file: assert on the AST, never on the source text.
    src = _src("beta_core_paper.py")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "_record_exception"), None)
    assert fn is not None, "beta_core must expose _record_exception()"
    targets = [c.args[0].value for c in ast.walk(fn)
               if isinstance(c, ast.Call)
               and getattr(c.func, "id", None) == "supabase_insert_table"
               and c.args and isinstance(c.args[0], ast.Constant)]
    assert targets == ["nav_exceptions"], (
        f"_record_exception inserts into {targets!r}; refusals belong in "
        "nav_exceptions ONLY, reached by a different insert than the one that "
        "may have just failed (NAV_POLICY §3)."
    )
    doc = _POLICY.read_text()
    assert "nav_exceptions" in doc.split("## §3")[1].split("## §4")[0], (
        "NAV_POLICY §3 must name nav_exceptions as the refusal record."
    )


# ── An absent field cannot report anything ───────────────────────────────────

def test_a_gated_field_is_present_and_says_it_is_gated():
    """Token-gated detail must still emit a field, not vanish.

    2026-09-04: `books` was wrapped in `if _tok_ok:`, so without a token the key
    was ABSENT — and a deploy that predates the feature is also absent. Jazz ran
    `jq '.books'`, got `null`, and that null could mean not-deployed, wrong token,
    or RPC failure. Three states, one output.

    That is the miss-vs-error collapse of S-180/S-185/S-194/S-285, **committed by
    me on the day I was fixing it.** Writing the guard does not immunise you
    against what the guard prevents; only making three-valued the default reflex
    does. Hence this test rather than another note.
    """
    src = (_ROOT / "src" / "api" / "main.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "data_freshness"), None)
    assert fn is not None, "data_freshness is gone — update this guard"
    seg = ast.get_source_segment(src, fn) or ""
    assert '"verdict": "gated"' in seg, (
        "the token-gated branch does not emit a field. An absent key is "
        "indistinguishable from an old deploy — say 'gated' out loud."
    )
    # The gate must not wrap the assignment away entirely.
    assigns = [n for n in ast.walk(fn)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Subscript) and getattr(t.value, "id", None) == "out"
                       for t in n.targets)]
    assert len(assigns) >= 2, (
        "expected both a gated and an ungated assignment to out[...] for the "
        "book roster; found fewer, so one path emits nothing"
    )


def test_schema_drift_names_the_checks_it_ran():
    """The echo must say WHAT it checked, not only what it found.

    `column_drift: null` on a pre-S-286 deploy and `column_drift: {}` on a clean
    one differ by one character and mean opposite things. A response that cannot
    name its own checks forces the reader to know the build — which is the thing
    an echo exists to remove.
    """
    src = (_ROOT / "src" / "api" / "routers" / "research_intake.py").read_text()
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "schema_drift"), None)
    assert fn is not None, "schema_drift is gone — update this guard"
    seg = ast.get_source_segment(src, fn) or ""
    assert '"checks"' in seg and '"columns"' in seg, (
        "/internal/schema-drift does not report which checks this build runs, so "
        "a missing field cannot be told apart from a clean result."
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


def test_there_is_exactly_one_valuation_point_in_the_whole_repo() -> None:
    """**估值点只能有一个。** (S-314, Jazz 裁定 2026-09-06)

    Jazz:「crypto 世界没有 close 这个概念吧,我们只能姑且按…为限制到天的节点。」

    原则完全正确,而且 S-283 已经按这条做了 —— 代码里的注释写的是同一句:
    *"Crypto has no close, so the instant must be chosen; `sleep(24h)` chose it
    by accident, differently after every deploy."*

    他先提的是**美东 12 点**,权衡之后裁定 **保持 UTC 日界不动**。三个代价:

      1. ① 已按 00:05 UTC 记账。第二个估值点 = 一本账在一个点标记、研究在
         另一个点做 —— 正是 S-193 的 splice。① 跟着改 = 第 6 次 inception，
         60 天前向记录从头。
      2. **没有任何厂商的「日线」是美东 12 点。** CoinGecko / Hyperliquid 的
         daily candle 都以 UTC 日为界。选美东 12 点意味着要用小时线自己合成日线，
         而那是一条新的摄取路径（Sense 入口正是我们要往下降的数）。
      3. **夏令时。** 美东 12 点一年里对应两个 UTC 时刻，而「两次标记恰好相差
         24 小时」正是 S-283 买来的那条性质。

    > **标记用 UTC 日界，执行用流动性时段 —— 这是两件事。**
    > UTC 的好处不是它更「对」，是**它和所有数据源的原生边界重合**，
    > 我们不必重新推导任何一根 bar，也不会在边界上拼接。

    **这条守卫防的不是我们改主意,是第二个估值点悄悄出现。** 现有测试查
    「常量存在」「常量被读」,都不查「只有一个」—— 而今晚拆掉的每一个接缝,
    都是同一个量有了两个载体。
    """
    import ast as _ast

    SUSPECT = ("VALUATION_POINT", "MARK_HOUR", "DAY_BOUNDARY", "CUTOFF_HOUR",
               "DAILY_CUT", "MARK_UTC")
    sites = []
    for path in (_ROOT / "src").rglob("*.py"):
        if "__pycache__" in str(path) or ".venv" in str(path):
            continue
        try:
            tree = _ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, (_ast.Assign, _ast.AnnAssign)):
                continue
            targets = (node.targets if isinstance(node, _ast.Assign)
                       else [node.target])
            for t in targets:
                nm = getattr(t, "id", "") or ""
                if any(k in nm.upper() for k in SUSPECT):
                    sites.append(f"{path.relative_to(_ROOT)}::{nm}")
    # 容差常量与估值点是同一条政策的两半，允许并存；其余重名即为第二个估值点。
    points = [s for s in sites if "TOLERANCE" not in s.upper()]
    assert len(points) <= 1, (
        f"发现 {len(points)} 个估值点定义:{points}\n"
        f"**估值点必须单一来源**（docs/NAV_POLICY.md §3）。两个估值点意味着"
        f"两本账的「一天」不是同一天，而它们的日收益会被当成可比的。")
