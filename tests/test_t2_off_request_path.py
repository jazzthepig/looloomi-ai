"""T2 must not be computed behind a web request (S-200).

MEASURED IN PRODUCTION 2026-08-23:

    _UNIVERSE_BUILD_BUDGET_S   12,000 ms
    railway_t2_ms             110,390 ms
    sum of all timed branches  19,250 ms   → 91 seconds with no owner

That is a DEADLOCK, not slowness. Only a build that COMPLETES writes
`_UNIVERSE_CACHE`, so a build that always exceeds its budget means the cache can
never fill, so the next request rebuilds from scratch and is cancelled again.
Permanent degradation, with every request burning twelve seconds and a full
round of external provider calls before discarding the work.

Symptom chain: /cis/universe served 43 T1-only assets with macro_regime=None
instead of the merged 58 → the ① book could not read a regime → two other books
stopped marking → /internal/loop-health read `broken`.

T1 stopped being computed on the request path months ago; the Mac builds it and
pushes to Redis. This gives T2 the same shape.
"""
import pathlib
import re

from tests._source import code_only

ROOT = pathlib.Path(__file__).resolve().parents[1]
_CIS = ROOT / "src/api/routers/cis.py"
_MAIN = ROOT / "src/api/main.py"


def test_the_request_path_prefers_the_precomputed_universe():
    src = code_only(_CIS.read_text())
    body = src.split("async def _build_cis_universe")[1].split("\nasync def ")[0]
    read_at = body.find("_T2_PRECOMPUTE_KEY")
    compute_at = body.find("await calculate_cis_universe(")
    assert read_at > 0, "the request path must look for a precomputed T2"
    assert compute_at > 0, "the inline build must still exist as a fallback"
    assert read_at < compute_at, (
        "the cache read must come BEFORE the inline compute, or the slow path "
        "still runs on every request")


def test_a_stale_precompute_falls_through_rather_than_serving_anything():
    src = code_only(_CIS.read_text())
    assert "_T2_PRECOMPUTE_MAX_AGE_S" in src, (
        "a precomputed universe of unbounded age is a different failure — it "
        "must expire into the inline path, not serve forever")


def test_the_precompute_loop_exists_and_is_registered():
    """S-175: a computation with no scheduler is a computation that does not run."""
    main = code_only(_MAIN.read_text())
    assert "async def _t2_precompute_loop" in main
    assert "create_task(_t2_precompute_loop())" in main.replace(" ", "")
    loop = main.split("async def _t2_precompute_loop")[1].split("\n@app")[0]
    assert "calculate_cis_universe" in loop
    assert "cis:t2_universe" in loop, "must write the key the request path reads"


def test_the_loop_budget_exceeds_the_request_budget():
    """The whole point: nobody is waiting on the loop, so it may take the time
    the work actually needs. A loop budget at or below the request budget would
    reproduce the deadlock one level up."""
    cis = code_only(_CIS.read_text())
    main = code_only(_MAIN.read_text())
    req = float(re.search(r'CIS_UNIVERSE_BUILD_BUDGET_S",\s*"([\d.]+)"', cis).group(1))
    loop = float(re.search(r'CIS_T2_PRECOMPUTE_BUDGET_S",\s*"([\d.]+)"', main).group(1))
    assert loop > req * 5, (
        f"loop budget {loop}s vs request budget {req}s — the measured build took "
        f"110s, so a loop budget anywhere near the request budget just moves the "
        f"deadlock")


def test_an_empty_build_does_not_overwrite_the_last_good_universe():
    """S-190 again: an empty result is a failed build, not a quiet day. Writing
    it would replace a working universe with nothing."""
    main = code_only(_MAIN.read_text())
    loop = main.split("async def _t2_precompute_loop")[1].split("\n@app")[0]
    # The CALL, not the name — `from src.api.store import redis_set_key` sits at
    # the top of the loop, so `.find("redis_set_key")` lands on the import and
    # reports the write as happening first. Sixth time this session; the helper
    # in tests/_source.py exists for exactly this and I still matched a bare
    # name. Match the construct.
    write_at = loop.find("await redis_set_key(")
    guard_at = loop.find("if uni:")
    assert write_at > 0, "expected an `await redis_set_key(` call in the loop"
    assert 0 <= guard_at < write_at, (
        "the write must be guarded by a non-empty universe check")


def test_a_timeout_keeps_serving_the_previous_value():
    main = code_only(_MAIN.read_text())
    loop = main.split("async def _t2_precompute_loop")[1].split("\n@app")[0]
    assert "TimeoutError" in loop, "an overrun must be caught, not crash the loop"
    blk = loop.split("TimeoutError")[1][:300]
    assert "still serving" in blk or "previous" in blk, (
        "an overrun must leave the last good copy in place and say so")
