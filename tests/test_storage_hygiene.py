"""
Storage hygiene guard — the class of waste that filled the database, not the data.

WHAT HAPPENED (2026-08-08). Supabase was at 449 MB of a 500 MB tier and the
obvious move was to start archiving rows to local storage. Measurement said the
database was not full of data:

  · ~84 MB of dead indexes (zero-to-thirty scans across 176 days of statistics)
  · ~128 MB of bloat I had created hours earlier — populating `asset_id` UPDATEd
    ~1M rows, and while autovacuum reclaimed the dead tuples (n_dead_tup = 0),
    free space inside pages is never returned to the OS without VACUUM FULL.

449 MB → 237 MB with zero rows archived and zero rows deleted.

THE GENERALISABLE PART, which is what this test pins:

  · **A bulk UPDATE is a storage event, not just a data event.** Any script that
    rewrites a large table must say so, so the VACUUM is planned rather than
    discovered a week later at 90% capacity.
  · **Index scan counts are only evidence if the statistics are old enough.**
    Four of the dropped indexes were created the same day; their low counts
    reflected age, not uselessness, and they had to be judged on structural
    redundancy instead. A hygiene script that omits the stats-age check is
    teaching the next reader to delete indexes on noise.
  · **Archive order is set by refetchability, not by size.** The largest table is
    also the most disposable because Binance can rebuild it in minutes; the
    smallest tables (forward NAV, graveyard) are the ones that cannot be rebuilt
    at any price.

Run: python3 -m tests.test_storage_hygiene
"""
import os
import pathlib
import re
import sys

REPO = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
HYGIENE = REPO / "scripts" / "supabase_storage_hygiene.sql"


def _sql_scripts():
    for p in sorted(REPO.glob("scripts/**/*.sql")):
        yield p, p.read_text(encoding="utf-8", errors="ignore")


def test_hygiene_script_records_the_stats_age_check():
    """Dropping an index on a zero scan count is only safe if the statistics have
    had time to accumulate. Recording the check — and the measured 176 days —
    is what separates this from cargo-culting a DROP INDEX list."""
    assert HYGIENE.exists(), "scripts/supabase_storage_hygiene.sql missing"
    txt = HYGIENE.read_text(encoding="utf-8")
    assert "stats_reset" in txt, "must show how to verify the statistics age"
    assert "176" in txt, "must record the measured stats age that justified the drops"
    assert "created TODAY" in txt or "hours old" in txt, (
        "must warn that a fresh index's low scan count reflects its AGE")


def test_hygiene_script_states_the_condition_that_reverses_it():
    """Four indexes were dropped because asset_id is currently 1:1 with symbol.
    That is a fact about today's data, not a law — so the reversal condition has
    to be written down, or the next schema change silently loses the index."""
    txt = HYGIENE.read_text(encoding="utf-8")
    assert "asset_id" in txt and "diverge" in txt.lower(), (
        "must state that asset_id indexes need recreating if it diverges from symbol")


def test_archive_order_is_by_refetchability_not_by_size():
    """The instinct is to evict the biggest table. The right question is what could
    not be rebuilt: hourly bars are refetchable from Binance in minutes, while the
    forward NAV and the graveyard are irreplaceable and tiny."""
    txt = HYGIENE.read_text(encoding="utf-8")
    assert "refetch" in txt.lower(), "archive order must be justified by refetchability"
    for keep in ("beta_core_nav", "signal_outcomes"):
        assert keep in txt, f"must name {keep} as never-archive"
    assert "NEVER archive" in txt


def test_bulk_update_scripts_flag_their_storage_cost():
    """The 128 MB was self-inflicted and predictable. Any SQL that UPDATEs a whole
    table has to say so next to the statement, so the VACUUM is planned with the
    migration instead of discovered at 90% capacity."""
    offenders = []
    # `UPDATE <table> ... FROM/WHERE` with no row-limiting predicate on a key
    pat = re.compile(r"^\s*update\s+(\w+)\s", re.I | re.M)
    for path, txt in _sql_scripts():
        if path.name == HYGIENE.name:
            continue
        low = txt.lower()
        for m in pat.finditer(txt):
            table = m.group(1)
            if table.startswith("_"):
                continue
            # only care about the tables big enough for it to matter
            if table not in ("ohlcv_daily", "ohlcv_hourly", "funding_history", "cis_scores"):
                continue
            if "vacuum" not in low and "storage" not in low and "bloat" not in low:
                line = txt[:m.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO)}:{line}: UPDATE {table}")
    assert not offenders, (
        "bulk UPDATE on a large table with no mention of VACUUM/bloat — an UPDATE "
        "rewrites every touched row and the freed space stays in the file:\n  "
        + "\n  ".join(offenders[:10]))


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} storage-hygiene checks passed")
    sys.exit(1 if f else 0)
