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
