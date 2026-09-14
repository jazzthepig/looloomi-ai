"""StoreResult[T] — typed envelope for store I/O (S-341 / Change 1).

WHY THIS EXISTS. Bare `bool` returns from writers collapse three different
outcomes into one bit:

  - "operation succeeded"        → True,  nothing to say
  - "we refused: missing role"   → False, [role: anon, env: railway]
  - "we refused: missing config"  → False, [SUPABASE_URL is empty in this process]
  - "transport gave 503"          → False, [status=503, body=...]
  - "we never tried: 0 rows"      → False, [caller passed 0 rows]

Same `False`, **five different reasons**. The fault was measured every time
this week:
  - S-180 (Redis None on transport failure ⇒ CIS panel demoted 58 assets T1→T2)
  - S-323d (PostgREST breaker blind spot)
  - S-329 (writer `False` carried no reason ⇒ `durable_write_failed` diagnosis
    took an entire exclusion round)
  - S-334 (six books reported `marked` because the writer's `False` was
    swallowed in caller `try/except Exception` — `bool` failures do NOT raise)

The fix: stop handing back a bit. Hand back a record with `ok` AND `why`.

THE SHAPE.

    StoreResult[T] = ok: bool
                     why: str              # empty when ok=True
                     value: T | None = None  # operation payload when relevant

`__bool__` returns `self.ok` so legacy `if await fn(...)` code keeps
working during migration. New callers should read `.ok` explicitly so
they can also read `.why` for logging:

    r = await redis_set_key(_REDIS_KEY, payload)
    if not r.ok:
        _logger.warning(f"redis_set_key failed: {r.why}")

WHY `T | None` AND NOT `T`. Some writers return a payload on success (e.g.
`supabase_get_history` should return `list[dict]`). Bare-bool writers
return `T = bool` with `value = True|None` — the `value` field is mostly
unused for those, but kept so a single envelope serves both shapes.

WHY NOT A TUPLE. The (ok, why) tuple pair already exists in
`paper_books/daily_runner.py:_run_module` output — see S-345 for why the
named-record shape is preferred (the field the caller forgets to read is
the field that breaks). Dataclass > tuple for THIS envelope because:
  - mypy sees `result.ok` / `result.why` as discrete types
  - `__bool__` lets migration land without touching callers
  - the SAME discipline (`WhyThis.fail(...)` and `WhyThis.ok_(...)`)
    already exists in `schema_manifest.py:NavWrite` — we're promoting that
    pattern from one-off to canonical.

USAGE.

    from src.api.store_result import StoreResult

    async def redis_set_key(...) -> StoreResult[bool]:
        ...
        if not _UPSTASH_URL:
            return StoreResult.fail("UPSTASH_REDIS_REST_URL not configured")
        ...
        if resp.status_code == 200:
            return StoreResult.ok_(value=True)
        return StoreResult.fail(f"status={resp.status_code}")

MIGRATION PATH.

  Stage 1 (S-341a, this commit): skeleton + `redis_set` / `redis_set_key`.
                                  Callers unchanged (`__bool__` carries them).
  Stage 2 (S-341b):              rest of bare-bool writers + caller-side
                                  `.ok` / `.why` consumption.
  Stage 3 (S-341c):              `mypy --strict src/api/store.py
                                  src/api/store_result.py` (ONLY those two).

The two-file strict scope is doctrine, not laziness — see plan evaluation
(S-341c) for why every "fix one typing error" scope-creep has burned us.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class StoreResult(Generic[T]):
    """Typed envelope for store I/O.

    Read fields by name: `result.ok`, `result.why`, `result.value`.
    Truthiness is `result.ok` for legacy `if await fn(...)` migration.

    Construction goes through the classmethod constructors below; do NOT
    instantiate the bare dataclass (the field-order trap is real — we
    want `StoreResult(ok=True)` and `StoreResult(ok=False, why="...")`
    both to FAIL mypy if anyone forgets the `why` on failure).
    """
    ok: bool
    why: str = ""
    value: T | None = None

    def __bool__(self) -> bool:
        # Migration aid: legacy `if await fn()` still works. New code
        # should read `.ok` directly so it can also read `.why`.
        return self.ok

    # ── Constructors — classmethod factories keep the "ok=True ⇒ empty why"
    # invariant unobtainable from bare dataclass init.

    @classmethod
    def ok_(cls, value: T | None = None) -> "StoreResult[T]":
        """Construct a successful result. `value` is the operation payload."""
        return cls(ok=True, why="", value=value)

    @classmethod
    def fail(cls, why: str) -> "StoreResult[T]":
        """Construct a failure result. `why` is non-empty by construction.

        The non-empty guard makes "wrote a function but forgot to set why"
        a constructor error rather than a logging error.
        """
        if not why:
            raise ValueError(
                "StoreResult.fail(why='') is a programming error — "
                "every failure must name its cause. Use StoreResult.ok_() "
                "for success."
            )
        return cls(ok=False, why=why, value=None)
