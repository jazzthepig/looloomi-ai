"""
Strategy-library durability guard.

WHAT HAPPENED. `scripts/supabase_strategy_records.sql` was written 2026-07-26 to
move the strategy record library off a 24h-TTL Redis key and into durable
Postgres. Its own WHY section says "a single Redis evict loses months of
research". It was never applied. So for 12 days `_pg_upsert()` POSTed to a table
that did not exist, caught the exception, logged one WARNING, returned False, and
`upsert_record()` fell back to Redis — the exact state the migration was written
to prevent. CLAUDE.md calls the graveyard the asset; the asset was in a cache.

WHY IT SURVIVED SO LONG. The warning fired on EVERY write. A warning that fires
every time is indistinguishable from background noise, so it stopped carrying
information the moment it became universal. Nothing counted.

WHAT THESE TESTS ENFORCE — the general lesson, not the specific bug:
  · a degraded fallback must be COUNTED, not merely logged
  · the counter must be readable as state (so /health can observe it)
  · one failure is already degraded — there is no acceptable rate of quietly
    losing research, so no threshold is correct here
  · the module must not silently "succeed" when the durable path is unavailable

Run: python3 -m tests.test_strategy_durability
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.vector import strategy_store as ss  # noqa: E402


def _reset():
    ss._DURABILITY.update({"consecutive": 0, "total": 0, "last_ok_ts": None,
                           "last_fail_id": None, "last_fail_ts": None})


def test_durability_state_is_exposed_as_state_not_just_logs():
    """A log line cannot be asserted on, alerted on, or put in /health. The
    12-day outage was invisible precisely because the only artefact was a log."""
    _reset()
    st = ss.durability_state()
    for k in ("consecutive", "total", "degraded", "pg_configured"):
        assert k in st, f"durability_state() must expose {k}"
    assert st["degraded"] is False, "clean slate must not report degraded"


def test_a_single_failure_is_already_degraded():
    """No threshold. A breaker tolerates failures because requests retry; a
    durability loss does not retry — the record is simply gone. One is the
    failure, not a symptom of it."""
    _reset()
    ss._record_durability_failure("r-42")
    st = ss.durability_state()
    assert st["degraded"] is True, "one failed durable write must flip degraded"
    assert st["consecutive"] == 1 and st["total"] == 1
    assert st["last_fail_id"] == "r-42", "must name WHICH record failed to persist"


def test_counter_separates_consecutive_from_total():
    """`consecutive` answers 'is it broken right now', `total` answers 'how much
    did we lose'. Collapsing them loses the second question, which is the one
    that matters after the fact."""
    _reset()
    for i in range(3):
        ss._record_durability_failure(f"r-{i}")
    assert ss.durability_state()["consecutive"] == 3
    ss._DURABILITY["consecutive"] = 0          # what a successful write does
    st = ss.durability_state()
    assert st["degraded"] is False, "recovery must clear the live signal"
    assert st["total"] == 3, "but the historical loss count must survive recovery"


def test_migration_file_and_its_writer_agree_on_the_table_name():
    """The outage was a name/existence mismatch between a SQL file nobody ran and
    a writer that assumed it had. Assert they at least refer to the same table,
    so a rename cannot silently reintroduce the same class of failure."""
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sql = open(os.path.join(repo, "scripts/supabase_strategy_records.sql"),
               encoding="utf-8").read()
    src = open(os.path.join(repo, "src/data/vector/strategy_store.py"),
               encoding="utf-8").read()
    assert "create table if not exists strategy_records" in sql.lower()
    assert "/rest/v1/strategy_records" in src, \
        "writer must target the table the migration creates"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} strategy-durability checks passed")
    sys.exit(1 if f else 0)
