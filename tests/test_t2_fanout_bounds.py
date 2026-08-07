"""
T2 fan-out bounds — the 2026-08-07 stale-forever build (S-104).
===============================================================

INCIDENT. `/api/v1/cis/universe` answered 200 the whole time and the external
probe read "slow, but up". It was not slow. It had not completed a build in at
least 56 minutes. Measured: total 17,358 ms, of which `railway_t2_ms` = 16,476.
Every 30 s the response cache expired, one unlucky request paid 10–14 s, the
build overran the 12 s budget, and the SAME payload (frozen at 01:03:51Z,
data_age_s = 3,353) was served again. Fresh Mac T1 scores arrived every ~3 min
and never reached anyone.

TWO DEFECTS, both of which are rules this codebase had already written down and
then failed to carry across one boundary:

  1. ALL-OR-NOTHING BUILD. `calculate_cis_universe` fanned out to 11 providers
     concurrently, but with no per-branch timeout. The only bound was the
     caller's build budget, and when it fired it cancelled the whole gather —
     discarding the nine branches that had ALREADY SUCCEEDED. A bound on the
     whole is not a bound on the parts. One slow provider therefore produced
     zero fresh data rather than slightly-less-rich fresh data.

     cis.py already says "enrichment moved outside the lock ... decoration never
     gates the payload". Correct rule, applied one layer up, never carried into
     T2's own fan-out. `cg_dev` is 24 h-cadence GitHub statistics: it must never
     be able to withhold a price.

  2. SUCCESS-ONLY CACHING. `get_cg_developer_data` cached for 24 h on success
     and wrote NOTHING on failure, while the bulk caller discarded any result
     containing "error". So a failing provider was re-attempted in full on every
     build — 25 coins, Semaphore(4), 15 s each = 7 serial waves — and since the
     build never completed, nothing was ever cached, so the next build repeated
     it exactly. A TTL that only caches success is not protection against a
     provider that is down; it is an amplifier.

RULES ENCODED HERE:
  - a slow DECORATION branch must not delay the payload beyond its own budget
  - a degraded branch must be REPORTED, not silently swallowed to {} (a guard
    must observe the real artifact; a branch that quietly yields {} is how a
    dead provider stays invisible)
  - a failed provider call must be remembered, so the cost is paid once per
    negative-TTL window rather than once per build

Run: python3 -m tests.test_t2_fanout_bounds
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ── 1. per-branch bound: a hung decoration branch cannot hold the build ───────

def test_slow_branch_does_not_gate_the_build():
    """A branch that never returns must cost its budget, not the whole build."""
    budget = 0.3
    degraded = []
    branch_ms = {}

    async def _bounded(name, coro, default):
        t = time.time()
        try:
            return await asyncio.wait_for(coro, timeout=budget)
        except asyncio.TimeoutError:
            degraded.append(name)
            return default
        except Exception:
            degraded.append(f"{name}:err")
            return default
        finally:
            branch_ms[f"{name}_ms"] = int((time.time() - t) * 1000)

    async def _fast():
        return {"ok": True}

    async def _hung():
        await asyncio.sleep(30)          # provider that never answers
        return {"never": True}

    async def _run():
        t0 = time.time()
        core, decor = await asyncio.gather(
            _bounded("core", _fast(), {}),
            _bounded("decor", _hung(), {}),
        )
        return core, decor, time.time() - t0

    core, decor, elapsed = asyncio.run(_run())

    assert core == {"ok": True}, "core branch lost its result"
    assert decor == {}, "hung branch should yield its default"
    # The whole point: bounded by max(budget), NOT by the hung branch.
    assert elapsed < budget * 3, f"build took {elapsed:.2f}s — branch bound not applied"
    assert "decor" in degraded, "degraded branch was not recorded"
    assert "core" not in degraded, "healthy branch wrongly marked degraded"


def test_degradation_is_reported_not_silent():
    """Silently returning {} is the failure mode that hid this for 56 minutes."""
    from src.data.cis import cis_provider
    src = open(cis_provider.__file__, encoding="utf-8").read()
    assert "degraded_branches" in src, \
        "T2 fan-out must report which branches degraded"
    assert "_branch_timing" in src, \
        "T2 must return per-branch timings for /health"
    assert "asyncio.wait_for" in src, \
        "T2 fan-out branches must be individually bounded"


def test_branch_timings_reach_health():
    """A diagnostic that only exists after the incident is not a diagnostic."""
    from src.api.routers import cis
    src = open(cis.__file__, encoding="utf-8").read()
    assert "t2_branches" in src, \
        "per-branch timings must be plumbed into the build record for /health"


def test_decoration_budget_is_below_the_build_budget():
    """Decoration must be capped well under the caller's budget, or the bound
    is decorative itself. Branches run concurrently, so the ceiling is max()."""
    from src.data.cis import cis_provider
    src = open(cis_provider.__file__, encoding="utf-8").read()
    assert "CIS_T2_BUDGET_DECOR_S" in src, "decoration budget must be configurable"
    # default decoration budget literal must be small
    import re
    m = re.search(r'CIS_T2_BUDGET_DECOR_S",\s*"(\d+(?:\.\d+)?)"', src)
    assert m, "could not read default decoration budget"
    decor = float(m.group(1))
    assert decor <= 5.0, f"decoration budget {decor}s is too close to the 12s build budget"


# ── 2. negative caching: a down provider is paid for once, not once per build ──

def test_provider_failure_is_negative_cached():
    """The amplifier: 24h TTL that stores successes only."""
    from src.data.market import data_layer
    src = open(data_layer.__file__, encoding="utf-8").read()
    assert "_NEG_TTL_S" in src, "no negative-cache TTL defined"
    # both bulk providers implicated in the incident must negative-cache
    for fn in ("get_cg_developer_data", "get_eodhd_fundamentals"):
        i = src.index(f"async def {fn}")
        j = src.index("\nasync def ", i + 10)
        body = src[i:j]
        assert "__neg" in body, f"{fn} does not negative-cache failures"
        assert "_redis_set" in body, f"{fn} negative cache is process-local only"


def test_negative_cache_ttl_is_short_enough_to_self_heal():
    """Long enough to collapse a build's retries, short enough that recovery
    needs no deploy."""
    from src.data.market import data_layer
    ttl = data_layer._NEG_TTL_S
    assert 60 <= ttl <= 3600, f"negative TTL {ttl}s outside sane self-heal window"


def test_negative_cache_actually_short_circuits():
    """Behavioural, not textual: a second call inside the TTL must not re-hit
    the provider. This is the property that turns 7 serial waves into 0."""
    from src.data.market import data_layer

    calls = {"n": 0}

    key = "cg_devdata_unit-test-coin"
    # seed a failure marker exactly as the except-branch would
    data_layer._cache_set(f"{key}__neg", {"error": "boom", "at": int(time.time())})

    async def _never_called(*a, **k):
        calls["n"] += 1
        raise AssertionError("provider was re-attempted despite negative cache")

    orig_key, orig_redis = data_layer.CG_API_KEY, data_layer._redis_get
    try:
        data_layer.CG_API_KEY = "test-key"          # get past the early return

        async def _redis_miss(k):
            return None
        data_layer._redis_get = _redis_miss
        data_layer._get_cg_client = _never_called

        out = asyncio.run(data_layer.get_cg_developer_data("unit-test-coin"))
    finally:
        data_layer.CG_API_KEY = orig_key
        data_layer._redis_get = orig_redis
        data_layer._cache.pop(f"{key}__neg", None)

    assert out.get("available") is False, "negative-cached call should report unavailable"
    assert "negative-cached" in str(out.get("error", "")), \
        f"expected negative-cache short-circuit, got {out}"
    assert calls["n"] == 0, "provider client was constructed despite negative cache"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} T2 fan-out bound checks passed")
