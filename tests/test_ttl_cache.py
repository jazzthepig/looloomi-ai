"""Stale-while-revalidate cache for slow public endpoints (src/api/ttl_cache.py)."""
import asyncio
import time

from src.api import ttl_cache


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_fresh_value_is_reused_and_stale_one_served_while_refreshing():
    ttl_cache.clear()
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        return calls["n"]

    async def scenario():
        a = await ttl_cache.swr("k", 60, fn)
        b = await ttl_cache.swr("k", 60, fn)
        assert (a, b, calls["n"]) == (1, 1, 1)                 # fresh: no recompute
        ttl_cache._VALUES["k"] = (time.time() - 120, 1)          # age past ttl
        c = await ttl_cache.swr("k", 60, fn)
        assert c == 1                                            # stale value served immediately
        await asyncio.sleep(0.01)                                # background refresh ran
        d = await ttl_cache.swr("k", 60, fn)
        assert d == 2 and calls["n"] == 2
    _run(scenario())


def test_failed_refresh_keeps_last_good_value_and_errors_are_not_cached():
    ttl_cache.clear()

    async def boom():
        raise RuntimeError("upstream down")

    async def scenario():
        try:
            await ttl_cache.swr("e", 60, boom)
            raise AssertionError("first call must raise — nothing to serve yet")
        except RuntimeError:
            pass
        assert "e" not in ttl_cache._VALUES
        ttl_cache._VALUES["e"] = (time.time() - 120, "good")
        assert await ttl_cache.swr("e", 60, boom) == "good"
        await asyncio.sleep(0.01)
        assert ttl_cache._VALUES["e"][1] == "good"
    _run(scenario())
