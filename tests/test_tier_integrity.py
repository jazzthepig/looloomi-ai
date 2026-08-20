"""S-180 / S-181 — the T1↔T2 boundary, guarded at the three places it broke.

WHAT HAPPENED (2026-08-19). `redis_get_key`'s docstring said "Returns None on
miss/error", and `_build_cis_universe` read that None as "the Mac engine has not
pushed". So a Redis transport failure — one dropped request — demoted the ENTIRE
58-asset universe from T1 to T2 in a single step. That is not a precision
change: measured on BTC the same instant, T1 said F=50 O=27 S=59 and T2 said
F=80 O=59 S=20, a ~13-point systematic score gap that crosses both the grade
boundary and the positioning boundary.

The hourly snapshot loop then wrote those rows into `cis_scores`, because its
guard is `tier_label == "T2"` and every asset now truthfully claimed to be T2.
Base rate measured over 266 hours: 8 hours affected (3.0%), 473 rows. Rare, and
wholesale when it fires — including 2026-08-19 11:00, inside the rally window
that prompted the investigation.

WHY TESTS AND NOT CARE. This is the THIRD instance of one class in a week
(`supabase_table_exists` missing-vs-unreachable S-166; loop-health "flowing" off
a single fresh row S-179). Each was fixed at the instance. Fixing the instance
is not fixing the class, so the class gets a test.
"""
import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def code_only(src: str) -> str:
    """Source with comments and docstrings removed.

    ⚠️ EVERY guard below must match against this, never against raw text.
    Mutation-tested 2026-08-20: the first version of this file passed all three
    of its own mutations, because each check looked for a NAME —
    `redis_get_key_status`, `supabase_fresh_t1_symbols` — and the explanatory
    comment sitting directly above the fixed code mentioned that name. Reverting
    the code left the comment, and the comment kept the test green.

    So the guards were not merely weak, they were ANTI-correlated with the thing
    they guarded: the better the comment explaining why the bug mattered, the
    more thoroughly it disabled the test that caught it. Written prose about a
    construct is not the construct. This is the same lesson as matching a JSX
    component name in a docstring (S-167) and matching `supabase_insert_batch`
    in an import line rather than at its call site — third occurrence in one
    session, hence a shared helper rather than a fourth careful reading.
    """
    out, prev_end = [], 0
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return re.sub(r"#.*", "", src)
    spans = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            spans.append((node.value.lineno, node.value.end_lineno))
    doc_lines = {n for a, b in spans for n in range(a, b + 1)}
    for i, line in enumerate(src.split("\n"), start=1):
        out.append("" if i in doc_lines else re.sub(r"#.*", "", line))
    del prev_end
    return "\n".join(out)


# ── 1. The read must carry WHY it is empty ───────────────────────────────────

def test_redis_read_distinguishes_miss_from_error():
    """`redis_get_key_status` must return a status, and must never call an HTTP
    failure a miss. Two-valued returns are what manufactured S-180."""
    from src.api.store import redis_get_key_status
    src = code_only(pathlib.Path(ROOT / "src/api/store.py").read_text())
    fn = src.split("async def redis_get_key_status")[1].split("\nasync def ")[0]

    for status in ("hit", "miss", "error", "unconfigured"):
        assert f'"{status}"' in fn, f"redis_get_key_status must be able to report {status!r}"

    # The non-200 branch must NOT fall through to "miss".
    assert "status_code != 200" in fn, "must branch on non-200 explicitly"
    non200 = fn.split("status_code != 200")[1].split("raw =")[0]
    assert '"error"' in non200 and '"miss"' not in non200, (
        "an HTTP error is not a miss — Upstash answers 200/result=null for an "
        "absent key. Calling a failed request a miss is exactly the S-180 bug.")


def test_tier_decision_does_not_use_the_two_valued_read():
    """`_build_cis_universe` must decide T1-vs-T2 on the status-carrying read."""
    src = code_only(pathlib.Path(ROOT / "src/api/routers/cis.py").read_text())
    body = src.split("async def _build_cis_universe")[1].split("\nasync def ")[0]

    assert "redis_get_status()" in body, (
        "the tier decision must use redis_get_status(); plain redis_get() cannot "
        "tell an absent Mac push from an unreachable Redis")
    assert re.search(r"^\s*cached\s*=\s*await\s+redis_get\(\)", body, re.M) is None, (
        "bare `cached = await redis_get()` reintroduces S-180")
    assert '== "error"' in body, (
        "the builder must branch on the error status and hold last-good T1 "
        "rather than demoting the whole universe")


# ── 2. The writer must refuse to shadow a live T1 ────────────────────────────

def test_hourly_t2_writer_checks_t1_occupancy():
    """Belt and braces: even with a wrong tier label upstream, the T2 writer must
    not overwrite a symbol that already has a fresh T1 row."""
    src = code_only(pathlib.Path(ROOT / "src/api/main.py").read_text())
    # Split on the DEFINITION, not the first mention — the name appears in a
    # create_task() call earlier in the file, and slicing there yields a window
    # that does not contain the loop at all. (First version of this test did
    # exactly that and "failed" against correct code.)
    loop = src.split("async def _hourly_t2_snapshot_loop")[1].split("\nasync def ")[0]

    assert "supabase_fresh_t1_symbols" in loop, (
        "the hourly T2 loop must consult the TABLE, not just the payload's own "
        "tier label — the label was wrong for all 58 assets on 2026-08-19")

    # Match the CALL SITE, not the name — the loop imports both symbols at its
    # top, so `.find("supabase_insert_batch")` lands on the import and reports
    # the insert as happening first. A guard that matches a name where it meant
    # a call is the same mistake this whole file exists to catch.
    insert_at = loop.find("await supabase_insert_batch(")
    check_at = loop.find("await supabase_fresh_t1_symbols(")
    assert insert_at > 0, "expected an `await supabase_insert_batch(` call in the loop"
    assert 0 <= check_at < insert_at, (
        "the occupancy check must run BEFORE the insert, not after it "
        f"(check at {check_at}, insert at {insert_at})")


def test_unknown_t1_occupancy_blocks_the_write():
    """None means 'could not ask'. Not-knowing is not permission."""
    src = code_only(pathlib.Path(ROOT / "src/api/main.py").read_text())
    loop = src.split("async def _hourly_t2_snapshot_loop")[1].split("\nasync def ")[0]
    assert "fresh_t1 is None" in loop, (
        "must branch explicitly on the unknown case")
    none_branch = loop.split("fresh_t1 is None")[1].split("elif")[0]
    assert "t2_rows = []" in none_branch, (
        "when T1 occupancy is unknown the write must be HELD. A missing hour is "
        "recoverable; an hour of rows shadowing a live T1 is not.")


def test_t1_occupancy_read_is_three_valued():
    from src.api.store import supabase_fresh_t1_symbols  # noqa: F401
    src = code_only(pathlib.Path(ROOT / "src/api/store.py").read_text())
    fn = src.split("async def supabase_fresh_t1_symbols")[1].split("\nasync def ")[0]
    assert "return None" in fn and "set[str] | None" in fn, (
        "must be able to say 'I could not ask' distinctly from 'there are none'")


# ── 3. The UI must not assert facts it has not checked ───────────────────────

_RADAR = ROOT / "dashboard/src/components/AssetRadar.jsx"
_LEADER = ROOT / "dashboard/src/components/CISLeaderboard.jsx"
_WIDGET = ROOT / "dashboard/src/components/CISWidget.jsx"


def test_radar_footer_does_not_hardcode_a_tier():
    """The footer said 'T2 Market Est.' unconditionally while 43 of 58 rows were
    T1 — which is what made two pages showing the SAME number look different."""
    txt = _RADAR.read_text()
    footer = txt.split("── Footer")[1]
    assert "dataTier" in footer, "the tier claim must be derived from the rows"
    assert not re.search(r'\{"\s*·\s*"\}<span[^>]*>T2</span>\s*Market Est\.',
                         footer.replace("\n", " ")) or "t1 === 0" in footer, (
        "an unconditional T2 claim is a hardcoded assertion about live data")


def test_two_views_of_the_same_number_sample_on_the_same_clock():
    """AssetRadar and CISLeaderboard read the identical field from the identical
    endpoint. If one refreshes and the other does not, they drift apart and the
    drift is misread as a scoring difference."""
    radar = _RADAR.read_text()
    leader = _LEADER.read_text()
    for name, txt in (("AssetRadar", radar), ("CISLeaderboard", leader)):
        assert "/api/v1/cis/universe" in txt, f"{name} should read the shared endpoint"
        assert "setInterval" in txt, (
            f"{name} never refreshes. BTC moved 44→58 over 2026-08-19; a page "
            f"frozen at mount showed a grade a full letter from its sibling.")

    def interval(txt):
        m = re.findall(r"setInterval\(\s*\w+\s*,\s*([\d_]+)\s*\)", txt)
        return {int(x.replace("_", "")) for x in m}

    assert interval(radar) & interval(leader), (
        f"the two views must share a cadence — radar={interval(radar)} "
        f"leaderboard={interval(leader)}")


def test_no_ui_box_promises_an_indicator_no_endpoint_produces():
    """Five boxes — Fed, 10Y, VIX, DXY, CPI — rendered an em-dash every day since
    launch because nothing in the backend has ever emitted those fields. An
    em-dash reads as a feed hiccup, so an absence disguised itself as an outage
    and survived indefinitely."""
    widget = _WIDGET.read_text()
    backend = "\n".join(
        p.read_text() for p in (ROOT / "src").rglob("*.py")
        if "__pycache__" not in str(p))

    banner = widget.split("export function CISMacroBanner")[1].split("\nexport ")[0]
    # Collapse runs of whitespace before substring-matching the guard. The source
    # aligns `!= null` into a column, so `macro?.fed_funds     != null` does not
    # contain the literal `macro?.fed_funds != null` — the first version of this
    # test reported five dead boxes against code that had already guarded them.
    flat = re.sub(r"\s+", " ", banner)
    for field in ("fed_funds", "treasury_10y", "vix", "dxy", "cpi_yoy",
                  "regime_confidence"):
        if f"macro?.{field}" not in banner:
            continue
        produced = f'"{field}"' in backend or f"'{field}'" in backend
        guarded = f"macro?.{field} != null" in flat
        assert produced or guarded, (
            f"CISMacroBanner renders {field!r}, no backend endpoint produces it, "
            f"and it is not null-guarded out of the DOM — so it will display a "
            f"permanent em-dash claiming we track a series we do not.")


def test_macro_banner_is_passed_what_it_reads():
    """The caller passed `{ regime }`; the component read six fields."""
    widget = _WIDGET.read_text()
    call = widget.split("<CISMacroBanner")[1].split("/>")[0]
    banner = widget.split("export function CISMacroBanner")[1].split("\nexport ")[0]
    flat = re.sub(r"\s+", " ", banner)   # see note in the test above
    read = set(re.findall(r"macro\?\.(\w+)", banner))
    passed = set(re.findall(r"(\w+)\s*:", call)) | {"regime"}
    unpassed = {f for f in read - passed if f"macro?.{f} != null" not in flat}
    assert not unpassed, (
        f"CISMacroBanner reads {sorted(unpassed)} which the caller never passes "
        f"and which are not null-guarded — dead boxes by construction")


# ── 3b. The class, not just the instances (S-184) ────────────────────────────
#
# S-180 was the third appearance of missing-vs-unreachable and the first two had
# both been fixed at the instance. So this section sweeps for the SHAPE rather
# than the site: a two-valued read whose None makes a WRITE take a different
# path. Three shapes were found and fixed alongside S-180 —
#   · quant.py       read trades → append → write back. None ⇒ history replaced.
#   · crowd_clock.py an idempotency key. None ⇒ duplicate row for the day.
#   · cis.py daily   T2 rows written over symbols that already had a fresh T1.
# `fusion_paper.py` was checked and is already correct (durable Supabase
# fallback, documented as load-bearing) — it is the pattern the others now match.

def _is_empty_literal(node) -> bool:
    """True for `[]`, `{}`, `()`, `""`, `0`, `None` — the laundering fallbacks.

    This is the narrow shape that turns "I could not read" into a value that
    looks like a legitimate answer. `existing = []` followed by
    `trades_data + existing` persists the read failure as data. Everything else
    — a call to another source, a name holding freshly computed data — is a
    genuine replacement and clears the taint.

    Arrived at by measurement, not by design: the broader rules flagged
    strategies.py (`assets = scored`), macro.py (payload from get_macro_pulse)
    and fusion_paper.py (durable Supabase fallback), all three of which are
    correct. Each false positive narrowed the rule until only the real one was
    left. A guard that flags correct code gets disabled by whoever hits it next,
    so precision here is not fastidiousness — it is whether the guard survives.
    """
    if isinstance(node, ast.Constant):
        return node.value in (None, 0, "", False) or node.value == 0
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _names(node) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_redis_get(node) -> bool:
    call = node.value if isinstance(node, ast.Await) else node
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "redis_get_key") or (
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        and call.func.id == "redis_get_key")


def _read_append_write_sites():
    """Sites where a value DERIVED FROM a redis read is written back to redis.

    A textual "read key then set key nearby" scan is not enough, and the first
    version of this test proved it by flagging `fusion_paper.py` — which reads
    the cache, falls through to the DURABLE Supabase copy on a miss, and writes
    THAT back. Refilling a cache from a source of truth is the correct pattern;
    it looks identical to the broken one from ten feet away.

    So this traces taint instead. The read's target is tainted; assignments
    fed by a tainted name spread it; an assignment that overwrites a tainted
    name from an untainted source CLEARS it (that is exactly the durable-fallback
    shape). Only a `redis_set_key` whose value is still tainted is reported —
    that is the case where the bytes being persisted encode the fact that the
    read failed.
    """
    hits = []
    for path in (ROOT / "src").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Parent map, so a reassignment can be told CONDITIONAL from
            # unconditional. Without it, quant.py's
            #     if not isinstance(existing, list): existing = []
            # clears the taint — but that line IS the laundering step: it is the
            # coercion that turns "could not read" into "there was nothing", on
            # the very branch the failure takes. Only a reassignment on the
            # function's main path genuinely replaces the value from another
            # source (fusion_paper's durable Supabase fallback). Mutation-tested:
            # without this distinction the scanner passes the exact bug it exists
            # to find.
            parent = {}
            for n in ast.walk(fn):
                for ch in ast.iter_child_nodes(n):
                    parent[ch] = n

            def _conditional(node):
                cur = parent.get(node)
                while cur is not None and cur is not fn:
                    if isinstance(cur, (ast.If, ast.Try, ast.While, ast.For)):
                        return True
                    cur = parent.get(cur)
                return False

            tainted: set[str] = set()
            origin: dict[str, int] = {}
            # SOURCE ORDER, not ast.walk order. `ast.walk` is breadth-first, so
            # a later reassignment that CLEARS taint can be visited after the
            # write that consumes it — which made this test report fusion_paper's
            # correct durable-fallback as an offender. Taint analysis without
            # program order is not taint analysis.
            ordered = sorted(
                (n for n in ast.walk(fn)
                 if isinstance(n, (ast.Assign, ast.Call)) and hasattr(n, "lineno")),
                key=lambda n: (n.lineno, n.col_offset))
            for stmt in ordered:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    tgt = stmt.targets[0]
                    if not isinstance(tgt, ast.Name):
                        continue
                    if _is_redis_get(stmt.value):
                        tainted.add(tgt.id)
                        origin[tgt.id] = stmt.lineno
                    elif _names(stmt.value) & tainted:
                        tainted.add(tgt.id)
                        origin.setdefault(tgt.id, stmt.lineno)
                    elif not _is_empty_literal(stmt.value):
                        # Untaint when the replacement comes from ANOTHER SOURCE
                        # (a call/await), conditional or not. Keep taint when a
                        # conditional branch replaces it with a LITERAL.
                        #
                        # That distinction is the whole rule, and three real
                        # sites drew it: strategies.py and macro.py fall back by
                        # calling calculate_cis_universe() / get_macro_pulse(),
                        # so what they persist is freshly fetched truth —
                        # correct, and flagged as false positives before this
                        # clause existed. quant.py fell back to `existing = []`,
                        # and `trades_data + []` is the read failure encoded as
                        # data. A fallback to a literal LAUNDERS the error into
                        # a plausible value; a fallback to a source REPLACES it.
                        tainted.discard(tgt.id)
                elif isinstance(stmt, ast.Call):
                    fname = (stmt.func.attr if isinstance(stmt.func, ast.Attribute)
                             else getattr(stmt.func, "id", None))
                    if fname != "redis_set_key" or len(stmt.args) < 2:
                        continue
                    used = _names(stmt.args[1]) & tainted
                    if used:
                        src = sorted(used)[0]
                        hits.append((str(path.relative_to(ROOT)),
                                     origin.get(src, stmt.lineno), src))
    return hits


def test_no_read_append_write_over_a_two_valued_read():
    """Reading a key, deriving from it, and writing the key back is the one
    pattern where None-on-error is destructive rather than degraded: the write
    persists the consequence of not having been able to read."""
    offenders = []
    for path, line, var in _read_append_write_sites():
        # code_only + a CALL-shaped pattern. Matching the bare name against raw
        # text let the comment above the fix satisfy the exemption.
        src = code_only((ROOT / path).read_text()).split("\n")
        window = "\n".join(src[max(0, line - 6):line + 14])
        if re.search(r"await\s+(?:store\.)?redis_get_key_status\s*\(", window):
            continue
        offenders.append(f"{path}:{line} (via `{var}`)")
    assert not offenders, (
        "a value derived from `redis_get_key` is written back to redis — on a "
        "transport failure the key is overwritten with something computed from "
        "having read nothing:\n  " + "\n  ".join(offenders))


def test_idempotency_keys_fail_closed():
    """A dedup check whose failure mode is a duplicate is not a dedup check."""
    txt = (ROOT / "src/data/market/crowd_clock.py").read_text()
    # Window AROUND the key, not after it — the status call and the key literal
    # are on the same line, so splitting on the key puts the call name on the
    # wrong side of the cut. (First version did exactly that and failed against
    # correct code, for the third time in this file. The lesson keeps being the
    # same one: a guard must match the construct, not a nearby string.)
    txt = code_only(txt)
    at = txt.index("crowd:clock:logged")
    guard = txt[max(0, at - 700):at + 700]
    assert re.search(r"await\s+(?:store\.)?redis_get_key_status\s*\(", guard), (
        "the dedup read must distinguish 'not logged' from 'could not ask'")
    assert 'in ("error", "unconfigured")' in guard, (
        "must fail CLOSED — a missing day is a visible gap someone can "
        "backfill; a duplicate day is a silent double-count in every aggregate")


def test_both_cis_snapshot_writers_use_the_same_shadow_guard():
    """The hourly and daily snapshot jobs write the same table from the same
    builder. Two guards of different shapes against one failure means two mental
    models, and eventually trusting the wrong one."""
    main = code_only((ROOT / "src/api/main.py").read_text())
    cis = code_only((ROOT / "src/api/routers/cis.py").read_text())
    daily = cis.split("async def snapshot_full_universe_to_supabase")[1].split("\n@router")[0]
    hourly = main.split("async def _hourly_t2_snapshot_loop")[1].split("\nasync def ")[0]
    for name, body in (("daily snapshot", daily), ("hourly loop", hourly)):
        assert re.search(r"await\s+supabase_fresh_t1_symbols\s*\(", body), (
            f"{name} writes cis_scores without CALLING the occupancy check — an "
            f"import of the name is not a call of it")


# ── 4. Cache windows must not outlive what they cache ────────────────────────

@pytest.mark.parametrize("path", ["src/api/routers/macro.py"])
def test_swr_window_does_not_exceed_the_refresh_cadence(path):
    """`stale-while-revalidate=3600` let a cold CDN edge serve a brief up to 70
    minutes old — longer than the 30-minute cadence that produces it, so the
    window could span an entire missed update. That is the cross-device lag."""
    txt = (ROOT / path).read_text()
    for m in re.finditer(r"max-age=(\d+),\s*stale-while-revalidate=(\d+)", txt):
        max_age, swr = int(m.group(1)), int(m.group(2))
        assert swr <= max_age, (
            f"{path}: max-age={max_age} but stale-while-revalidate={swr}. A SWR "
            f"window longer than the freshness window means the stale copy "
            f"outlives the fresh one — readers on cold edges see the past.")


# ── 5. A partial day must not be written as a day (S-190) ────────────────────

def test_deep_panel_refuses_to_write_below_the_floor():
    """`_MIN_OK_FRACTION` was wired only into the RETURN VALUE; the write went
    ahead regardless. Measured one day after shipping: exactly one symbol (BCH)
    had a bar since 08-14, written every run, reported ok=False to a print
    statement nobody reads — and `max(trade_date)` sat at today, so every
    freshness check in the system saw a current 262-symbol panel.

    The module's own docstring had diagnosed this exact failure ("a run that
    reaches 40 of 262 must not read like a quiet day") one function earlier.

    A partial panel day is not a thin day, it is a different object: a
    cross-sectional study reading it gets a one-symbol universe with no way to
    know. A visible gap is recoverable; a silently one-asset day is not."""
    src = code_only((ROOT / "src/data/market/deep_panel_collector.py").read_text())
    fn = src.split("async def collect_deep_panel")[1]

    guard_at = fn.find("frac < _MIN_OK_FRACTION")
    write_at = fn.find("await supabase_upsert_table(")
    assert guard_at > 0, "the floor must be checked inside collect_deep_panel"
    assert write_at > 0, "expected an upsert call"
    assert guard_at < write_at, (
        "the floor is checked AFTER the write — that is annotation, not a gate")

    between = fn[guard_at:write_at]
    assert "return" in between, (
        "below the floor the function must RETURN before writing; falling "
        "through with a flag set is what made a 1/262 run look like a fresh day")
