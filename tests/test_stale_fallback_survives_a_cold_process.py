"""
Guard: the stale fallback is reachable from a COLD process (S-146).

WHAT HAPPENED, overnight 2026-08-11 → 08-12. Every Mac-side cycle logged:

    [SNAPSHOT] universe build failed: 503: CIS universe build timed out and no
    cached payload available

and the day's writes died with it. Measured in Supabase the next morning:

    cis_scores             116 rows today   ← T1 push, does not use this build
    trending_log             0 rows today
    conviction_verdicts      0
    narrative_snapshots      0
    cause_snapshots_daily    0
    beta_core_nav            0
    causal_paper_nav         0

One slow build starved every writer downstream of it, for a whole day.

THE MECHANISM, and why it is worse than "the build is slow". There IS a stale
fallback — `_universe_stale()` — and it reads `_UNIVERSE_CACHE`, a module-level
dict. The scheduler runs each task as a fresh process, so that dict is EMPTY at
the moment the fallback is consulted. The safety net existed, was tested, looked
present in the code, and could not fire in the one situation it was built for.

That is the session's recurring shape once more: not a thing that fails loudly,
but a thing that is confidently absent. `cap_source` only ever held one value;
`schema_version` only ever held the wrong one; four routes were only ever
shadowed; and this fallback was only ever cold.

THE FIX is not a longer budget. A longer budget moves the failure date; a
cross-process fallback changes the failure MODE, from "no record for a day" to
"a record marked stale". Redis is already the cross-process CIS cache.

Run: python3 -m tests.test_stale_fallback_survives_a_cold_process
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


_SRC = (_ROOT / "src/api/routers/cis.py").read_text(encoding="utf-8")


def test_a_durable_fallback_exists() -> None:
    from src.api.routers import cis
    check("_universe_stale_durable is defined",
          hasattr(cis, "_universe_stale_durable"), "")
    check("it is async (it does I/O)",
          inspect.iscoroutinefunction(getattr(cis, "_universe_stale_durable", None)), "")


def test_every_503_path_tries_the_durable_copy_first() -> None:
    """Both 503 sites — lock-busy and budget-exceeded — must fall through. Fixing
    only the one being debugged is not fixing the bug; that was S-138's second
    call site, one week earlier."""
    n = _SRC.count("_universe_stale() or await _universe_stale_durable()")
    check(f"{n} of 2 stale sites chain to the durable copy", n >= 2,
          "a 503 path that skips the durable read is the outage, unchanged")
    # and no bare in-process-only call survives on a 503 path
    bare = _SRC.count("stale = _universe_stale()\n")
    check("no 503 path reads the in-process cache alone", bare == 0,
          f"{bare} site(s) still consult only the module-level dict")


def test_the_in_process_cache_is_documented_as_cold_on_start() -> None:
    """The next author must not 'simplify' the chain back to one call. The reason
    lives next to the function, not only in a ledger entry."""
    check("_universe_stale says it is in-process only",
          "IN-PROCESS ONLY" in _SRC, "")
    check("the durable path explains the cold-start failure",
          "empty in every freshly started process" in _SRC, "")


def test_stale_is_never_served_silently() -> None:
    """A stale payload that does not announce itself is a fresh payload as far as
    every consumer is concerned. S-104 established this; the durable path must
    honour it too."""
    check("durable stale sets data_status", '"data_status"] = "stale"' in _SRC
          or 'out["data_status"] = "stale"' in _SRC, "")
    check("durable stale reports its age", "stale_age_seconds" in _SRC, "")
    check("durable stale names its source", "stale_source" in _SRC, "")
    check("it logs at ERROR, not INFO",
          '_logger.error("[CIS] serving STALE universe' in _SRC,
          "an outage-adjacent degradation that logs at INFO is invisible")


def test_the_durable_read_refuses_an_ancient_payload() -> None:
    """Serving a week-old universe as though it were merely 'stale' would be a
    different lie. The age bound must still apply on the durable path."""
    from src.api.routers import cis

    async def _ancient(**_):
        return {"universe": [{"symbol": "BTC"}], "last_updated": 0.0}

    import src.api.store as store
    orig = getattr(store, "redis_get", None)
    try:
        store.redis_get = _ancient
        got = asyncio.run(cis._universe_stale_durable(max_age_s=3600))
    finally:
        if orig is not None:
            store.redis_get = orig
    check("a payload older than the bound is refused", got is None,
          f"served an ancient payload: {str(got)[:80]}")


def test_a_fresh_durable_payload_is_served_and_flagged() -> None:
    import time

    from src.api.routers import cis

    async def _fresh(**_):
        return {"universe": [{"symbol": "BTC"}], "last_updated": time.time() - 60}

    import src.api.store as store
    orig = getattr(store, "redis_get", None)
    try:
        store.redis_get = _fresh
        got = asyncio.run(cis._universe_stale_durable(max_age_s=3600))
    finally:
        if orig is not None:
            store.redis_get = orig
    check("a fresh-enough payload is served", isinstance(got, dict) and got.get("universe"),
          str(got)[:100])
    check("and is flagged stale", (got or {}).get("data_status") == "stale", str(got)[:100])


if __name__ == "__main__":
    print("── the stale fallback survives a cold process (S-146) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ a slow build degrades instead of starving the record")
