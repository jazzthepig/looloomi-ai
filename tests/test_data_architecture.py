"""
L0 architecture guard — the S-106 bug class, made statically detectable.

WHAT WENT WRONG. `asset_class` was stored on every OBSERVATION row instead of on
the asset. Measured 2026-08-07: 24 symbols carried multiple asset_class values,
because the column did not record a property of the asset — it recorded which
SOURCE the row came from. And source determines candle convention: rows with a
>1% open/prev_close gap were 31.3% under label 'Crypto' but 73.7% / 79.5% / 83.5%
under 'L1' / 'L2' / 'DeFi'.

So `where asset_class='Crypto'` looked like a class filter and was actually a
source filter. That is exactly how the S-106 first cut produced a fake
"+12.30 cumulative overnight return": it spliced two sources with different bar
conventions and read the seam as market structure.

WHY A TEST AND NOT A NOTE. The failure is invisible at the call site — the query
runs, returns plausible rows, and the number looks like a finding. Nothing about
`where asset_class = 'Crypto'` announces that it is a source filter. A reviewer
cannot see it; a grep can.

WHAT IS ENFORCED HERE (offline, so it can live in preflight):
  · the architecture contract exists and names its own verification
  · migrations for L0 are checked in, not only applied
  · analysis code does not filter observation tables by asset_class

Live checks (registry orphans, class conflicts, PIT membership) need database
access and are recorded as VERIFY commands in docs/DATA_ARCHITECTURE.md §4 —
they cannot run in the offline gate, and pretending otherwise would be another
test that asserts against a literal instead of the real artifact.

Run: python3 -m tests.test_data_architecture
"""
import os
import pathlib
import re
import sys

REPO = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
ARCH = REPO / "docs" / "DATA_ARCHITECTURE.md"

# Tables that hold OBSERVATIONS. Filtering these by asset_class is the bug.
OBS_TABLES = ("ohlcv_daily", "ohlcv_hourly", "funding_history", "ohlcv_daily_canonical")

# Files allowed to mention the legacy column: the migration that retires it, the
# architecture doc that explains it, and this test. An allowlist beats a blanket
# skip because each entry has to be justified by name.
ALLOW = {
    "tests/test_data_architecture.py",
    "docs/DATA_ARCHITECTURE.md",
    "scripts/supabase_l0_registry.sql",
}


def _sources():
    for p in list(REPO.glob("src/**/*.py")) + list(REPO.glob("scripts/**/*.py")):
        rel = str(p.relative_to(REPO))
        if "__pycache__" in rel or rel in ALLOW:
            continue
        try:
            yield rel, p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def test_architecture_contract_exists_and_is_verifiable():
    """A contract that does not say how to re-check itself decays into a story."""
    assert ARCH.exists(), "docs/DATA_ARCHITECTURE.md missing"
    txt = ARCH.read_text(encoding="utf-8")
    low = txt.lower()          # the doc is bilingual and names the universes in caps
    for token in ("coverage", "investable", "display"):
        assert token in low, f"the three universes must be named; missing '{token}'"
    assert "A1" in txt and "A4" in txt, "the measured failures must be stated, not summarised"
    assert "universe_membership" in txt, "PIT membership is the fix for A4 and must be named"


def test_l0_migration_is_checked_in_not_only_applied():
    """S-105: supabase_strategy_records.sql sat unapplied for 12 days precisely
    because a file and an applied migration are different things. The converse is
    just as bad — applied-but-unversioned schema cannot be reviewed or rebuilt."""
    f = REPO / "scripts" / "supabase_l0_registry.sql"
    assert f.exists(), "L0 registry migration must be checked in under scripts/"
    sql = f.read_text(encoding="utf-8").lower()
    for t in ("create table if not exists assets",
              "create table if not exists asset_aliases",
              "create table if not exists universe_membership"):
        assert t in sql, f"L0 migration missing: {t}"
    assert "row level security" in sql, "S-94: new tables ship with RLS"


def test_no_analysis_filters_observations_by_asset_class():
    """THE guard. `where asset_class = ...` on an observation table selects a
    SOURCE, not a class — 24 symbols carry conflicting labels. Class now lives in
    `assets`; join to it.

    Scoped at STATEMENT level, not file level. The first cut of this check asked
    "does the file mention an observation table?" and flagged five call sites that
    were fine: docstring examples, plain assignments like
    `asset_class = data.get(...)`, and an MCP request-parameter filter that never
    touches an observation table. A guard whose failures are mostly noise gets an
    ignore list bolted on within a week, and then it guards nothing — so the
    scanner is narrowed instead."""
    # Only SQL-ish text: a fragment that queries an obs table AND filters asset_class.
    obs = "|".join(OBS_TABLES)
    stmt = re.compile(
        rf"from\s+(?:{obs})\b[\s\S]{{0,400}}?asset_class\s*(?:=|!=|<>|\bin\b|\bnot\s+in\b)",
        re.I)
    offenders = []
    for rel, txt in _sources():
        for m in stmt.finditer(txt):
            line = txt[:m.start()].count("\n") + 1
            offenders.append(f"{rel}:{line}: {m.group(0)[:110].replace(chr(10), ' ')}")
    assert not offenders, (
        "asset_class filter on observation data — this selects a SOURCE, not a class "
        "(24 symbols carry conflicting labels; see S-106). Join `assets` instead:\n  "
        + "\n  ".join(offenders[:10]))


def test_observation_writes_do_not_set_asset_class():
    """Writing the column keeps the ambiguity alive even if nobody filters on it.
    Retiring a bad field means stopping the writes first, then dropping it."""
    offenders = []
    for rel, txt in _sources():
        low = txt.lower()
        if "insert into ohlcv" not in low and "insert into funding" not in low:
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            s = line.lower()
            if "asset_class" in s and ("insert" in s or "values" in s or "," in s):
                if "insert into" in low.split("asset_class")[0][-400:]:
                    offenders.append(f"{rel}:{i}: {line.strip()[:96]}")
    assert not offenders, (
        "new observation rows still carry asset_class; class belongs in `assets` only:\n  "
        + "\n  ".join(offenders[:10]))


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} data-architecture checks passed")
    sys.exit(1 if f else 0)
