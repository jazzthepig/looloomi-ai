"""
CIS universe single-flight lock — the second half of the 2026-07-29 P0.
=======================================================================

INCIDENT (part 2). `/api/v1/cis/universe` hung 5/5 while Supabase's own REST
layer answered in 0.5s and the Postgres engine sat idle. Cause: the single-flight
lock — originally added to collapse a 503 burst — held across UNBOUNDED external
calls. One starved rebuild sat in the critical section for the full retry budget
and every other request queued behind it. A burst-protection fix had become a
total-outage amplifier.

RULE ENCODED HERE: a single-flight lock must bound BOTH
  (a) how long it can be HELD   → build budget
  (b) how long a caller WAITS   → lock-acquire timeout
Either bound alone still hangs. Degradation must be to STALE (flagged), never to
a queue, and never to a silent lie.

Run: python3 -m tests.test_cis_universe_lock
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException  # noqa: E402

from src.api.routers import cis  # noqa: E402


def _reset(cache=None, ts=None):
    cis._UNIVERSE_CACHE["data"] = cache
    cis._UNIVERSE_CACHE["ts"] = ts if ts is not None else time.time()
    if cis._UNIVERSE_LOCK.locked():
        cis._UNIVERSE_LOCK.release()
    cis._attach_asset_narratives = lambda d: None
    cis._attach_cause_proximity_async = lambda d: asyncio.sleep(0)


GOOD = {"universe": [{"symbol": "BTC", "cis_score": 80}], "source": "test"}


def _patch_build(delay=0.0, payload=GOOD):
    async def _fake(force_source=None):
        if delay:
            await asyncio.sleep(delay)
        return payload
    cis._build_cis_universe = _fake


def test_fresh_cache_served_without_touching_build():
    _reset(cache=GOOD)
    cis._build_cis_universe = None  # would explode if called
    out = asyncio.run(cis.get_cis_universe())
    assert out["universe"][0]["symbol"] == "BTC"
    assert not out.get("stale")


def test_slow_build_does_not_block_other_callers():
    """THE incident. One slow rebuild must not queue everyone else."""
    _reset(cache=GOOD, ts=time.time() - 100)   # past TTL(30s), well within stale window
    cis._UNIVERSE_LOCK_WAIT_S = 0.15
    cis._UNIVERSE_BUILD_BUDGET_S = 10
    _patch_build(delay=2.0)

    async def scenario():
        slow = asyncio.create_task(cis.get_cis_universe())
        await asyncio.sleep(0.05)       # let it take the lock
        t0 = time.time()
        fast = await cis.get_cis_universe()
        waited = time.time() - t0
        slow.cancel()
        return fast, waited

    fast, waited = asyncio.run(scenario())
    assert waited < 1.0, f"second caller queued {waited:.2f}s behind the rebuild"
    assert fast.get("stale") is True, "contended caller must get flagged stale data"
    assert fast["stale_age_s"] > 0


def test_build_timeout_serves_stale_not_hang():
    """Rebuild exceeding its budget degrades to stale within the budget."""
    _reset(cache=GOOD, ts=time.time() - 100)
    cis._UNIVERSE_LOCK_WAIT_S = 1.0
    cis._UNIVERSE_BUILD_BUDGET_S = 0.2
    _patch_build(delay=5.0)
    t0 = time.time()
    out = asyncio.run(cis.get_cis_universe())
    elapsed = time.time() - t0
    assert elapsed < 1.0, f"took {elapsed:.2f}s — must abort at the budget"
    assert out.get("stale") is True


def test_no_cache_plus_timeout_returns_503_not_hang():
    """With nothing to serve we must FAIL, fast and loudly. Hanging is the one
    behaviour that is never acceptable — it burns a worker and tells no one."""
    _reset(cache=None)
    cis._UNIVERSE_LOCK_WAIT_S = 1.0
    cis._UNIVERSE_BUILD_BUDGET_S = 0.2
    _patch_build(delay=5.0)
    t0 = time.time()
    try:
        asyncio.run(cis.get_cis_universe())
        raise AssertionError("expected HTTPException(503)")
    except HTTPException as e:
        assert e.status_code == 503
        assert time.time() - t0 < 1.0


def test_stale_is_flagged_never_silent():
    """Serving stale is fine; serving stale while claiming freshness is not.
    Same discipline as /health: degraded state must be visible."""
    _reset(cache=GOOD, ts=time.time() - 500)
    s = cis._universe_stale()
    assert s["stale"] is True and s["stale_age_s"] >= 500


def test_ancient_cache_is_refused():
    """Stale has a limit — beyond it, 503 beats presenting fossil data as live."""
    _reset(cache=GOOD, ts=time.time() - 10_000)
    assert cis._universe_stale(max_age_s=3600) is None


def test_lock_is_released_when_build_raises():
    """A build that throws must not strand the lock — that would permanently
    wedge the endpoint (same class as the S-90 freeze that never unfroze)."""
    _reset(cache=GOOD, ts=time.time() - 100)
    cis._UNIVERSE_LOCK_WAIT_S = 0.5
    cis._UNIVERSE_BUILD_BUDGET_S = 5

    async def _boom(force_source=None):
        raise RuntimeError("upstream exploded")
    cis._build_cis_universe = _boom

    try:
        asyncio.run(cis.get_cis_universe())
    except RuntimeError:
        pass
    assert not cis._UNIVERSE_LOCK.locked(), "lock stranded after exception"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} cis-universe lock checks passed")
