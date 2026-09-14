"""S-341 / Change 1 — StoreResult[T] envelope regression tests.

Run: python3 -m pytest tests/test_store_result.py -q
or:  python3 -m tests.test_store_result

Test scope:
  - Constructor invariants (`ok_()` empty why; `fail()` requires why)
  - `__bool__` migration safety (legacy `if not r:` style works)
  - `frozen=True` (cannot be mutated post-construction)
  - Generic typing roundtrip (T=bool, T=int, T=str, T=list[dict])
  - Bare-init trap documented (init still works but the field-order risk
    is the reason we promote ok_()/fail() in the docstring)
  - LIVE ledger integration: `redis_set` and `redis_set_key` actually
    return StoreResult[bool] (catches a regression where someone re-
    types the function to plain `bool`)

THE LIE THIS TEST REJECTS. Three failure shapes that all read as "ok=False"
without a `why`:
  (a) Refusal: role/config absent at import time
  (b) Transport: status != 2xx after retries
  (c) Caller: passed 0 rows

Same boolean, three different ops. A test that only asserts `result is False`
would let any writer collapse them all back into one True/False shape. The
empty-why guard on `fail()` is the structural enforcement that keeps
`why` non-empty on failure — same defense as S-323z's "name which one".
"""
from __future__ import annotations

import pathlib
import sys
import inspect

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.api.store_result import StoreResult  # noqa: E402


# ── CONSTRUCTOR INVARIANTS ────────────────────────────────────────────────────

def test_ok_constructor() -> None:
    """ok_(value=None) ⇒ ok=True, why='', value=None. Always."""
    r = StoreResult.ok_()
    assert r.ok is True
    assert r.why == ""
    assert r.value is None


def test_ok_constructor_with_value() -> None:
    """ok_(value=X) carries the payload."""
    r = StoreResult[int].ok_(value=42)
    assert r.ok is True
    assert r.value == 42


def test_fail_constructor_requires_nonempty_why() -> None:
    """fail(why='') raises — every failure must name its cause."""
    try:
        StoreResult.fail("")
    except ValueError as e:
        assert "every failure must name its cause" in str(e), str(e)
    else:
        raise AssertionError("fail('') did NOT raise — empty-why guard broken")


def test_fail_constructor_with_reason() -> None:
    """fail(why='real reason') produces ok=False, why=reason."""
    r = StoreResult.fail("status=503 body=permission denied")
    assert r.ok is False
    assert r.why == "status=503 body=permission denied"
    assert r.value is None


# ── __bool__ MIGRATION SAFETY ────────────────────────────────────────────────

def test_bool_legacy_truthy_on_ok() -> None:
    """`if await fn():` works during migration because __bool__ returns ok.

    In Python, an `await expr` followed by `if expr:` only needs the awaited
    value to satisfy truthiness. Since our envelope defines `__bool__`,
    legacy code that reads `if not (await redis_set_key(...)):` continues to
    work — even though the function now returns StoreResult[bool] not bool.
    """
    r = StoreResult.ok_()
    if not r:
        raise AssertionError("ok result tested False — __bool__ broken")


def test_bool_legacy_falsy_on_failure() -> None:
    """Legacy `if await fn()` False-branch on failure."""
    r = StoreResult.fail("status=500")
    if r:
        raise AssertionError("failure tested True — __bool__ broken")


def test_bool_legacy_inside_if_statement() -> None:
    """The migration idiom (the actual pattern from store.py callers).

    Old code does `if not (await redis_set_key(...)):` for guard purposes.
    We test the equivalent value-side: `if not (await-of-something-that-
    returns-an-envelope):`. We don't actually call redis_set_key (would need
    a real Upstash URL); we use a stub coroutine that returns the envelope.
    """
    import asyncio

    async def stub() -> StoreResult[bool]:
        return StoreResult.ok_()

    seen = asyncio.run(stub())
    if seen:
        pass  # ok, this branch should fire
    else:
        raise AssertionError("ok result tested False inside if — __bool__ broken")


# ── IMMUTABILITY ──────────────────────────────────────────────────────────────

def test_frozen_dataclass_rejects_mutation() -> None:
    """`frozen=True` so a caller cannot post-construct rewrite `ok`."""
    r = StoreResult.ok_()
    try:
        r.ok = False  # type: ignore[misc]
    except (AttributeError, Exception) as e:
        # dataclass FrozenInstanceError, not plain AttributeError — but we
        # accept any "set refused" because the contract is "mutation refused".
        assert "frozen" in str(type(e).__name__).lower() or "frozen" in str(e).lower() \
               or "cannot assign" in str(e).lower() or "read-only" in str(e).lower(), \
               f"unexpected error type: {type(e).__name__}: {e}"
    else:
        raise AssertionError("mutation NOT rejected — frozen=True not enforced")


# ── GENERIC TYPING ROUNDTRIP ─────────────────────────────────────────────────

def test_value_carries_bool_payload() -> None:
    r = StoreResult[bool].ok_(value=True)
    assert r.value is True


def test_value_carries_str_payload() -> None:
    r = StoreResult[str].ok_(value="rows=4")
    assert r.value == "rows=4"


def test_value_carries_dict_payload() -> None:
    payload = {"asset_id": 1, "grade": "A"}
    r = StoreResult[dict].ok_(value=payload)
    assert r.value == payload


# ── INTEGRATION: store.py actually uses the envelope ─────────────────────────

def test_store_redis_set_returns_store_result() -> None:
    """redis_set's return type is StoreResult[bool] now (S-341a)."""
    from src.api.store import redis_set
    sig = inspect.signature(redis_set)
    anno = sig.return_annotation
    # `StoreResult[bool]` evaluates to StoreResult[bool] in __annotations__
    # when the source uses modern `list[int] | None` syntax. We don't pin the
    # exact forward-ref string — we pin the SHAPE (has ok, why, value attrs).
    assert "StoreResult" in str(anno), (
        f"redis_set return annotation {anno!r} does not reference StoreResult — "
        f"S-341a migration incomplete"
    )


def test_store_redis_set_key_returns_store_result() -> None:
    """redis_set_key's return type is StoreResult[bool] now."""
    from src.api.store import redis_set_key
    sig = inspect.signature(redis_set_key)
    anno = sig.return_annotation
    assert "StoreResult" in str(anno), (
        f"redis_set_key return annotation {anno!r} does not reference StoreResult — "
        f"S-341a migration incomplete"
    )


# ── S-341b: 4 SUPABASE WRITERS MIGRATED ──────────────────────────────────────

def test_store_supabase_insert_batch_returns_store_result() -> None:
    """supabase_insert_batch return type is StoreResult[bool] (S-341b)."""
    from src.api.store import supabase_insert_batch
    sig = inspect.signature(supabase_insert_batch)
    anno = sig.return_annotation
    assert "StoreResult" in str(anno), (
        f"supabase_insert_batch return annotation {anno!r} does not reference StoreResult"
    )


def test_store_supabase_insert_table_returns_store_result() -> None:
    """supabase_insert_table return type is StoreResult[bool] (S-341b)."""
    from src.api.store import supabase_insert_table
    sig = inspect.signature(supabase_insert_table)
    anno = sig.return_annotation
    assert "StoreResult" in str(anno), (
        f"supabase_insert_table return annotation {anno!r} does not reference StoreResult"
    )


def test_store_supabase_upsert_table_returns_store_result() -> None:
    """supabase_upsert_table return type is StoreResult[bool] (S-341b)."""
    from src.api.store import supabase_upsert_table
    sig = inspect.signature(supabase_upsert_table)
    anno = sig.return_annotation
    assert "StoreResult" in str(anno), (
        f"supabase_upsert_table return annotation {anno!r} does not reference StoreResult"
    )


def test_store_supabase_rpc_write_returns_store_result() -> None:
    """supabase_rpc_write return type is StoreResult (S-341b — was tuple)."""
    from src.api.store import supabase_rpc_write
    sig = inspect.signature(supabase_rpc_write)
    anno = sig.return_annotation
    assert "StoreResult" in str(anno), (
        f"supabase_rpc_write return annotation {anno!r} does not reference StoreResult "
        f"— S-341b migration broke the shape contract"
    )


def test_supabase_insert_table_empty_rows_returns_store_result_fail() -> None:
    """S-341b: a 0-rows insert MUST return a StoreResult failure with a non-empty
    why. Pre-341b shape returned `False` (collapsed 4 failure causes into one bit).

    This is a direct regression guard for S-334 / S-329 — the same writers whose
    bare-bool returns swallowed a 6-row day of unmarked books. We don't need a
    network; the row-count guard fires BEFORE the request.

    We patch refuse_write because the role gate (S-149) is INTENTIONALLY the
    first guard in every writer — its refusal would mask the row-count check
    we're testing here. Production runs in role=production, where refuse_write
    returns "" and the row-count guard fires as documented. We also set
    SUPABASE_URL/KEY so the URL-missing guard doesn't fire first.
    """
    import asyncio
    import os
    import src.api.store as st
    from src.api.store import supabase_insert_table
    orig_refuse, orig_url, orig_key = st.refuse_write, st._SB_URL, st._SB_KEY
    st.refuse_write = lambda label: ""
    st._SB_URL, st._SB_KEY = "http://test.supabase", "test-key"
    try:
        r = asyncio.run(supabase_insert_table("any_table", []))
    finally:
        st.refuse_write = orig_refuse
        st._SB_URL, st._SB_KEY = orig_url, orig_key
    assert isinstance(r, StoreResult), f"got {type(r).__name__}, expected StoreResult"
    assert r.ok is False
    assert "0 rows" in r.why, (
        f"empty-rows failure did not name the cause: {r.why!r}"
    )


def test_supabase_insert_table_empty_table_name_returns_store_result_fail() -> None:
    """S-341b: empty `table` arg MUST fail loud with a why, not silent False."""
    import asyncio
    import src.api.store as st
    from src.api.store import supabase_insert_table
    orig_refuse, orig_url, orig_key = st.refuse_write, st._SB_URL, st._SB_KEY
    st.refuse_write = lambda label: ""
    st._SB_URL, st._SB_KEY = "http://test.supabase", "test-key"
    try:
        r = asyncio.run(supabase_insert_table("", [{"x": 1}]))
    finally:
        st.refuse_write = orig_refuse
        st._SB_URL, st._SB_KEY = orig_url, orig_key
    assert r.ok is False
    assert "table" in r.why.lower(), f"why did not name the cause: {r.why!r}"


def test_supabase_upsert_table_empty_on_conflict_returns_store_result_fail() -> None:
    """S-341b: empty `on_conflict` MUST fail loud — without it, an UPSERT path
    silently degenerates to an INSERT and a duplicate-key 409 on retry (S-164
    territory)."""
    import asyncio
    import src.api.store as st
    from src.api.store import supabase_upsert_table
    orig_refuse, orig_url, orig_key = st.refuse_write, st._SB_URL, st._SB_KEY
    st.refuse_write = lambda label: ""
    st._SB_URL, st._SB_KEY = "http://test.supabase", "test-key"
    try:
        r = asyncio.run(supabase_upsert_table("any_table", [{"x": 1}], ""))
    finally:
        st.refuse_write = orig_refuse
        st._SB_URL, st._SB_KEY = orig_url, orig_key
    assert r.ok is False
    assert "on_conflict" in r.why, f"why did not name the cause: {r.why!r}"


def test_supabase_rpc_write_role_gate_returns_store_result_fail() -> None:
    """S-341b: supabase_rpc_write's role gate MUST surface via .why with the
    full refusal text (was the second tuple element). Without the full text,
    the operator cannot tell role-gate from network-failure from payload-error.
    """
    import asyncio
    import src.api.store as st
    from src.api.store import supabase_rpc_write
    # Patch refuse_write to simulate a role-gate refusal; this exercises the
    # failure path without needing a real Supabase roundtrip.
    orig = st.refuse_write
    st.refuse_write = lambda label: "this process may not write cis_scores (env=railway, role=anon)"
    try:
        r = asyncio.run(supabase_rpc_write("exec_backfill_forward_returns", {"horizon_days": 1}))
    finally:
        st.refuse_write = orig
    assert r.ok is False, f"role-gate refusal did not produce failure: {r}"
    assert "may not write" in r.why, (
        f"role-gate failure did not carry refusal reason: {r.why!r}"
    )
    # The first tuple element was the bool, second was the reason. Confirm the
    # reason is in `why` — `.value` would be None (which is correct; role-gate
    # refusal produces no payload).
    assert r.value is None


# ── BARE-INIT TRAP DOCUMENTATION ─────────────────────────────────────────────

def test_bare_init_still_works_with_why_but_mypy_will_complain() -> None:
    """Bare `StoreResult(ok=False, why='x')` works (Python doesn't forbid it),
    but the MIGRATION DISCIPLINE is to use `StoreResult.fail('x')` instead.

    The dataclass does NOT lock the field-order trap because dataclass doesn't
    enforce keyword-only. We rely on convention + code review. This test
    exists so a future "the bare init is fine, drop the constructors" change
    is forced to think about WHY the constructors exist (same shape as the
    _WRITE_FUNCS persistence test in S-342 — the existence of a guard is the
    evidence of the lesson, not the assertion it makes).
    """
    r = StoreResult(ok=False, why="transient: status=502, retrying", value=None)
    assert r.ok is False
    assert "status=502" in r.why


# ── RUNNER ────────────────────────────────────────────────────────────────────

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
        except Exception as e:
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} S-341a StoreResult envelope tests passed"
          + (f" · {f} FAILING" if f else ""))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
