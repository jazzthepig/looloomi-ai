"""
Regime write-path guard — "unknown" must never be stored as a valid regime.

FOUND 2026-08-09 by chasing a discrepancy flagged twice and left unchased: the
score table said `Tightening` while the ① book had read `NEUTRAL`. One query
produced two bugs.

  · The daily snapshot passed a MISSING regime through the lenient
    `canonical_regime()`, which returns "NEUTRAL", and wrote it for all 58 symbols
    in a single batch — 58 rows sharing the timestamp 14:14:25.189708, while the
    SAME source wrote TIGHTENING at 04:04 and 14:53. Once a day, every day
    (08-07 08:44, 08-06 10:17).

  · The `/internal/cis-scores` receiver stored the Mac engine's label RAW, so the
    table carries `Tightening` (local_engine, 645 rows) beside `TIGHTENING`
    (railway, 749 rows) as if they were two regimes. Canonicalisation ran on READ
    and never on WRITE.

THE LIVE COST. The ① book sizes exposure off this label: TIGHTENING maps to 0.5,
NEUTRAL to 1.0. **The book ran at FULL SIZE on the first day of its forward
record** because a fallback default was indistinguishable from a real reading.

THE ASYMMETRY WORTH REMEMBERING. The snapshot already had a guard directly above
the defect — "never write nothing, an empty snapshot is a failure, not a valid
day" — and then wrote a fabricated value on every row. **Completeness was
checked; correctness was not.** That pairing shows up all over this codebase.

Run: python3 -m tests.test_regime_write_path
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.cis.cis_provider import (  # noqa: E402
    _CANONICAL_REGIMES, canonical_regime, canonical_regime_strict,
)

_CIS_ROUTER = os.path.join(os.path.dirname(__file__), "..", "src/api/routers/cis.py")


def test_strict_returns_none_where_lenient_invents_a_regime():
    """The whole point. Both are correct for their side: a renderer must show
    something, a writer must not invent something."""
    for unknown in (None, "", "UNKNOWN", "SOME_NEW_ENGINE_LABEL", "n/a"):
        assert canonical_regime(unknown) == "NEUTRAL", "lenient must stay lenient"
        assert canonical_regime_strict(unknown) is None, (
            f"{unknown!r} must be NULL on a write path — storing NEUTRAL makes "
            f"'we do not know' indistinguishable from a real neutral call")


def test_a_genuine_neutral_still_survives_strict():
    """The converse trap: a strict filter that also drops REAL neutrals would
    delete a third of the regime series to fix a fallback bug."""
    assert canonical_regime_strict("NEUTRAL") == "NEUTRAL"
    assert canonical_regime_strict("Neutral") == "NEUTRAL"


def test_casing_and_separators_normalise_on_the_write_path():
    """`Tightening` and `TIGHTENING` are 645 and 749 rows of the same regime in one
    table. Normalising on read only means every consumer must remember to do it —
    and the S-117 run-length analysis had to do it by hand."""
    for variant in ("Tightening", "TIGHTENING", "tightening", " Tightening "):
        assert canonical_regime_strict(variant) == "TIGHTENING"
    assert canonical_regime_strict("Risk-Off") == "RISK_OFF"
    assert canonical_regime_strict("risk off") == "RISK_OFF"


def test_every_canonical_regime_round_trips():
    """A strict normaliser that silently dropped a legitimate regime would be worse
    than the bug it replaces — it would delete real observations."""
    for r in _CANONICAL_REGIMES:
        assert canonical_regime_strict(r) == r, f"{r} must survive strict canonicalisation"
        assert canonical_regime_strict(r.title()) == r


def test_both_write_paths_use_the_strict_variant():
    """Two call sites, one helper. A second inline copy would drift from this test,
    and the copy that drifts is always the one running live."""
    src = open(_CIS_ROUTER, encoding="utf-8").read()
    assert src.count("canonical_regime_strict") >= 2, \
        "both the snapshot and the push receiver must use the strict variant"
    # the push receiver must not store the raw label any more
    assert not re.search(r'"macro_regime":\s+macro_regime_push,', src), \
        "the push receiver is storing the engine's label verbatim again"
    # and the snapshot must log rather than silently null
    assert "writing NULL" in src, "an undetermined regime must be logged, not just nulled"


def test_a_failed_measurement_yields_none_not_a_placeholder_string():
    """THE ROOT CAUSE, found by chasing why the fabricated batch appeared once a day
    at a DIFFERENT time each day — because it was a timeout, not a schedule.

        pulse = await asyncio.wait_for(get_macro_pulse(), timeout=5.0)
        except TimeoutError: pulse = {}
        _cached_regime = pulse.get("macro_regime") or "UNKNOWN"

    A slow FRED call produced the literal string "UNKNOWN", the snapshot fed it to
    the lenient canonicaliser, and 58 rows of NEUTRAL were written. Guarding only
    the sink would have left the source emitting a placeholder that every other
    consumer still cannot distinguish from a reading.

    So the paths that FEED a stored payload must yield None on failure. The
    remaining "UNKNOWN" literals are read-side: a confidence computation and two
    API response defaults, where a renderer legitimately needs something to show."""
    src = open(_CIS_ROUTER, encoding="utf-8").read()
    # every regime fallback that lands in a payload must be `or None`
    payload_paths = [
        '_cached_regime = pulse.get("macro_regime") or None',
        'result["macro_regime"] = pulse.get("macro_regime") or None',
    ]
    for frag in payload_paths:
        assert frag in src, f"failed measurement still yields a placeholder: {frag}"
    # and no regime fallback chain may still end in the literal
    assert 'or "UNKNOWN"\n            ),' not in src, \
        "a cached/last-known-good payload still falls back to the placeholder string"


def _code_only(text: str) -> dict:
    """Return {lineno: code} with comments and string literals blanked.

    Needed because the first cut of the two tests below fired on PROSE — a docstring
    in cis_provider that describes this very bug, and my own comment quoting the old
    query. A guard that cannot tell code from a comment about code will be silenced
    by whoever documents the next incident, which is precisely the wrong incentive.
    """
    import io
    import tokenize
    lines = {i: "" for i in range(1, text.count("\n") + 2)}
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {i: l for i, l in enumerate(text.splitlines(), 1)}
    for tok in toks:
        if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        lines[tok.start[0]] = lines.get(tok.start[0], "") + tok.string + " "
    return lines


def test_no_write_path_anywhere_still_uses_the_lenient_canonicaliser():
    """S-123. Fixing the two call sites I was looking at did not fix the CONTRACT.
    Four more modules held their own `canonical_regime()` call on a write path, and
    one of them was `beta_core_paper` — the ① book, i.e. the product. Its regime
    came back NEUTRAL while every source said TIGHTENING, so the book sized at 1.0
    where the map says 0.5, and both marks of the forward record are at double the
    intended exposure.

    Scoped to modules that write. The lenient variant is correct on the read side,
    where a renderer needs a value; this pins that it never reaches storage."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent
    writers = ("supabase_insert", "upsert_embeddings", "_pgv_upsert",
               "supabase_insert_batch", "supabase_insert_table")
    offenders = []
    for p in sorted((repo / "src").rglob("*.py")):
        if ".venv" in str(p) or "/research/" in str(p):
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if not any(w in txt for w in writers):
            continue
        for i, s in _code_only(txt).items():
            if not s or "canonical_regime_strict" in s or "def canonical_regime" in s:
                continue
            if re.search(r"\bcanonical_regime\s*\(", s):
                offenders.append(f"{p.relative_to(repo)}:{i}: {s.strip()[:80]}")
    assert not offenders, (
        "lenient canonical_regime() on a module that writes — unknown becomes "
        "NEUTRAL in storage:\n  " + "\n  ".join(offenders))


def test_regime_history_reads_the_recent_end_and_proves_its_freshness():
    """S-123, the bug underneath the bug. `_regime_history` asked PostgREST for
    `order=recorded_at.asc&limit=20000` over a window holding 53,250 rows, so the
    cap silently dropped the NEWEST end: the most recent day the ① book could see
    was 2026-07-17 while the date was 2026-08-09.

    Lesson #103: a row cap plus an ascending sort is a silent "oldest N", and the end
    it drops is never the random one. This class GROWS on its own — the table gets
    longer, the limit does not, so a query that was complete last month is truncating
    this month with no code change and no error.

    Lesson #104: a stale series is structurally indistinguishable from a fresh one —
    same length, same label set, same types, differing only in which days it covers.
    Nothing downstream has the information to be suspicious. So a time series must
    PROVE it reaches the present rather than be trusted to; same family as I1, except
    that what is unmeasured here is one end of time rather than a field.

    S-130 STRENGTHENS THIS. Switching to `desc` fixed our cap and exposed the
    server's: PostgREST enforces `db-max-rows` (1000 by default), which silently
    overrides `limit=20000`. At 1,000–2,000 cis_scores rows per day, "30 days" of
    history was 1–2 days, so `len(hist) < 5` never reached the dwell filter and the
    book sized off `regime = None` at cap 1.0 while every source read TIGHTENING.
    Measured cost: v2's first marks recorded `excess_return = 0.0000`, because
    `gross = min(1.30, 1.0) = 1.0` made the book identical to its own benchmark.

    Lesson #112: **do not transport rows you are about to aggregate.** Asking the
    database for the aggregate puts the row cap out of reach rather than merely
    further away — 35 rows instead of ~49,000, and no limit we do not control. A
    bigger `limit` would only have moved the failure date."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "src" / "data" / "signals" / "beta_core_paper.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "daily_macro_regime" in code, (
        "regime history must read the pre-aggregated daily view — fetching raw rows "
        "puts it back under PostgREST's db-max-rows, which we do not control")
    assert "cis_scores?select=recorded_at,macro_regime" not in code, \
        "the raw-row fetch is back; it is capped server-side regardless of our limit"
    assert "recorded_at.asc&limit" not in code, "the truncating ascending query is back"
    assert "STALE" in src and "refusing to size off it" in src, \
        "the series must verify it reaches the present rather than be trusted to"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} regime write-path checks passed")
    sys.exit(1 if f else 0)
