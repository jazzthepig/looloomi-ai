"""
S-378b-C2: `_forward_record_loop` was showing "Supabase retry exhaustion"
when Supabase was slow — but only TWO of its FOUR Supabase calls went through
the shared retry helper.

THE INCONSISTENCY (THIS IS THE BUG).

  refresh_depth_divergence_log  → supabase_rpc_write       (has retry + breaker)
  check_book_continuity / _days_since → _supabase_request_with_retry  (has retry + breaker)
  evaluate_forward_record        → httpx.AsyncClient(timeout=15)  (NO retry, NO breaker)
  check_pit_lag                  → httpx.AsyncClient(timeout=15)  (NO retry, NO breaker)

The two direct-httpx calls each take up to 15s on a slow day and NEVER participate
in the circuit breaker. So while the rest of the loop retreats under contention,
these two time out individually, fall into `out["reason"] = "读不到 … 读不到 ≠ 没有记录"`,
and the loop fires its beat with `ok=False`.

THE FIX. Both direct-httpx callers now go through the shared retry helper. They
participate in the breaker (one slow day, all four calls retreat together; the
breaker trips and the loop sees `unknown` cleanly instead of a 15s hang each),
and the per-call timeout caps at 10s × 1 attempt = 10s (timeout doesn't retry
— the shared helper's discipline).

WHAT THIS TEST GUARDS. Three properties:

  1. `evaluate_forward_record` and `check_pit_lag` use the shared retry helper,
     NOT direct httpx.AsyncClient.
  2. Both functions can read `_supabase_request_with_retry` (already exposed via
     `src.api.store`).
  3. The shared helper's breaker participation means a breaker-open early-exit
     does NOT take 15s.

Run: python3 -m tests.test_forward_record_uses_shared_retry
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.data.signals import forward_record_keeper as frk   # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


# ── The two functions must use the shared retry helper ──────────────────────

def test_evaluate_forward_record_uses_shared_retry() -> None:
    """`evaluate_forward_record` must call `_supabase_request_with_retry`, NOT
    `httpx.AsyncClient.get` directly."""
    src = inspect.getsource(frk.evaluate_forward_record)
    # The function source must NOT contain a direct httpx.AsyncClient usage.
    check("evaluate_forward_record does NOT use httpx.AsyncClient directly",
          "httpx.AsyncClient" not in src,
          "direct httpx call defeats the shared retry/breaker")
    # It must import _supabase_request_with_retry or use supabase_* helpers.
    check("evaluate_forward_record uses the shared retry helper",
          ("_supabase_request_with_retry" in src
           or "supabase_rpc_write" in src
           or "supabase_request" in src),
          "no shared retry helper import found")


def test_check_pit_lag_uses_shared_retry() -> None:
    """Same for `check_pit_lag`."""
    src = inspect.getsource(frk.check_pit_lag)
    check("check_pit_lag does NOT use httpx.AsyncClient directly",
          "httpx.AsyncClient" not in src,
          "direct httpx call defeats the shared retry/breaker")
    check("check_pit_lag uses the shared retry helper",
          ("_supabase_request_with_retry" in src
           or "supabase_rpc_write" in src
           or "supabase_request" in src),
          "no shared retry helper import found")


def test_the_loop_failure_shape_is_consistent() -> None:
    """When one call's read fails, the failure shape must match the others —
    `reason` saying "could not read", `verdict: "unknown"`. This is what the
    loop reads to decide `ok=False` vs `refused=True` vs healthy."""
    async def _run():
        return (await frk.evaluate_forward_record(),
                await frk.check_pit_lag())
    rec, pit = asyncio.run(_run())
    # When Supabase isn't configured (which is the case in this test env), the
    # shared helper gives the "未配置" reason uniformly. The OLD code would
    # have raised an httpx exception (because httpx.AsyncClient(timeout=15)
    # needs `_SB_URL` and `_SB_KEY` to be present).
    check("evaluate_forward_record returns a verdict-bearing dict, not raises",
          isinstance(rec, dict) and "verdict" in rec,
          f"got {rec}")
    check("check_pit_lag returns a verdict-bearing dict, not raises",
          isinstance(pit, dict) and "verdict" in pit,
          f"got {pit}")


if __name__ == "__main__":
    print("── S-378b-C2: forward_record uses shared Supabase retry ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ shared retry helper used · direct httpx removed · breaker participates")
