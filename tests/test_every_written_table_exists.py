"""
Guard: the OFFLINE half of "every table the code writes to exists" (S-166).

WHAT WAS MEASURED, 2026-08-15, against the live database. ELEVEN tables that
production code writes to did not exist:

    beta_core_nav_q, beta_core_nav_q_meta          C2 ⓠ sleeve
    beta_core_nav_size, beta_core_nav_size_meta    C3 size sleeve
    strategy_params                                S-151
    execution_intents, execution_outcomes          S-155
    fusion_paper_nav, fusion_paper_lifecycle
    crowd_clock_log

PROJECT_STATE's header read "C2 ⓠ + C3 size + C5 episode-code complete; 79/79
smoke green" on 2026-08-12. Green tests, and no table to write a single row
into. Those sleeves had never persisted anything and could not have.

THE PART THAT MATTERS IS THAT WE ALREADY KNEW. OPEN RISK #3(a) has read, since
2026-07-26: "A table that was never created. scripts/supabase_strategy_records.sql
... was never applied. `_pg_upsert()` POSTed to a nonexistent table, caught the
exception, logged one WARNING, returned False". The risk was written down, the
lesson recorded — and it happened eleven more times, because the fix was that
one table rather than the absence of any comparison between the set of tables
the code writes and the set that exists.

Every one of those writes returns False and is swallowed, which is
indistinguishable from "no data yet". That is the same shape as the 80-day dead
signal_outcomes pipeline and the strategy library in a 24h-TTL Redis key: the
system's way of failing is to look exactly like its way of being early.

TWO HALVES, and neither can pass vacuously:

    THIS FILE (offline, preflight)  — the manifest matches what the source does
    /internal/schema-drift (online) — the live catalog matches the manifest

preflight stays offline by contract (S-163: credentials in the gate are what
made it slow and machine-dependent). So the half that needs a database lives
where the credentials already are, and the deploy-verifier calls it.

A stale manifest fails here. A missing table fails there. Deleting the manifest
fails both.

Run: python3 -m tests.test_every_written_table_exists
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.api.schema_manifest import (       # noqa: E402
    _names_a_table,
    manifest_path,
    write_tables,
)

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _manifest() -> dict:
    p = manifest_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def test_the_manifest_exists_and_is_readable() -> None:
    m = _manifest()
    check("schema_manifest.json exists and parses", bool(m.get("write_tables")),
          f"regenerate: python3 -c \"import json,sys; sys.path.insert(0,'.'); "
          f"from src.api.schema_manifest import *; "
          f"manifest_path().write_text(json.dumps({{'write_tables': write_tables()}}, indent=2))\"")


def test_the_manifest_matches_what_the_source_actually_does() -> None:
    """The whole guard rests on the manifest being current. A hand-edited or
    stale manifest would let a new table slip past BOTH halves — the offline
    check would compare it to itself and the online one would confirm the
    subset that was already there."""
    m = _manifest()
    if not m:
        return
    declared = sorted(m.get("write_tables", []))
    actual = write_tables()
    added = sorted(set(actual) - set(declared))
    removed = sorted(set(declared) - set(actual))
    check("manifest lists every table the source writes to", not added,
          f"code writes to {added} but the manifest does not list them — "
          f"regenerate it, then make sure those tables EXIST in Supabase")
    check("manifest lists nothing the source no longer writes", not removed,
          f"manifest lists {removed} which no code writes to any more — "
          f"regenerate; a manifest with ghosts makes the online check noisy, "
          f"and a noisy check is one people learn to skip")


def test_the_manifest_is_not_empty_and_covers_the_known_regressions() -> None:
    """The ten tables that were missing on 2026-08-15 must stay in scope. Not a
    frozen list of everything — a floor. If a future refactor drops these from
    the manifest, the guard would go quiet on exactly the class that produced
    it."""
    m = _manifest()
    if not m:
        return
    declared = set(m.get("write_tables", []))
    check("manifest is not trivially small", len(declared) >= 15,
          f"only {len(declared)} tables — the scanner probably stopped matching")
    for t in ("beta_core_nav_q", "beta_core_nav_size", "execution_intents",
              "execution_outcomes", "crowd_clock_log", "fusion_paper_nav"):
        check(f"{t} is still in scope", t in declared,
              "this table was missing from production on 2026-08-15; if the "
              "scanner no longer sees it, the guard cannot protect it")


def test_table_constant_detection_does_not_over_or_under_match() -> None:
    """The first version of the name filter matched TABLE as a SUBSTRING and
    pulled in `NS_INVESTABLE = "investable_v1"` — INVES-TABLE — asserting that
    a namespace string had to exist as a Postgres table. The fix for that then
    over-corrected and stopped matching `_TABLE` itself.

    Both directions are recorded because they are the same failure: a check
    that reports confidently on a pattern match rather than on meaning. A guard
    with false positives gets muted, and a muted guard is worse than none — it
    also occupies the slot a real one would have filled."""
    for name, expected in (("_TABLE", True), ("_NAV_TABLE", True),
                           ("TABLE_NAME", True), ("SIZE_TABLE_2D", True),
                           ("NS_INVESTABLE", False), ("_EXECUTABLE", False),
                           ("PORTABLE", False)):
        check(f"{name} names a table = {expected}",
              _names_a_table(name) is expected, "")


def test_the_online_half_exists_and_is_wired() -> None:
    """This file cannot see the database. If the online half is missing, the
    check is half a check while reading like a whole one."""
    src = (_ROOT / "src/api/routers/research_intake.py").read_text(encoding="utf-8")
    check("/internal/schema-drift endpoint exists", "/internal/schema-drift" in src, "")
    check("it reads the same manifest", "manifest_path" in src,
          "two sources of truth would drift, which is the bug")
    store = (_ROOT / "src/api/store.py").read_text(encoding="utf-8")
    check("supabase_table_exists is three-valued", "bool | None" in store,
          "a boolean collapses 'table missing' into 'could not reach Supabase' — "
          "that collapse is exactly what hid eleven tables for weeks")


def test_a_missing_table_is_distinguishable_from_an_unreachable_database() -> None:
    """Asserted on the code, since we cannot make the network fail here. Only a
    404 / PGRST205 may return False; anything else must return None."""
    store = (_ROOT / "src/api/store.py").read_text(encoding="utf-8")
    blk = store.split("async def supabase_table_exists")[1][:1600]
    code = "\n".join(l for l in blk.splitlines() if not l.lstrip().startswith("#"))
    check("404 / PGRST205 is the only path to False",
          "PGRST205" in code and "404" in code, "")
    check("an exception yields None, not False", "return None" in code.split("except")[-1],
          "returning False on a network error would report healthy tables as missing")


if __name__ == "__main__":
    print("── every table the code writes to must exist (S-166, offline half) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ manifest is current · online half wired · missing ≠ unreachable")
