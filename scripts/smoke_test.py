#!/usr/bin/env python3
"""
Pre-merge smoke test — the gate that would have caught the 2026-06-14 outage.

That incident: a commit imported `supabase_insert_table` from `src.api.store`,
but the function wasn't committed → the app raised ImportError on boot → Railway
kept the old build and every deploy silently failed for 5 days. A single
"can the app even import + boot?" check blocks that entire class of failure.

Run locally:  python scripts/smoke_test.py
CI runs it on every push/PR to main (.github/workflows/ci-smoke.yml).
Exits non-zero (fails the build) on any import or boot error.
"""
import os
import sys
import traceback

# Ensure the repo root is importable regardless of CWD (so `import src...` works
# when run as `python scripts/smoke_test.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dummy env so config reads at import time never hard-fail in CI.
os.environ.setdefault("INTERNAL_TOKEN", "ci-smoke")
os.environ.setdefault("ENVIRONMENT", "ci")

FAILURES = []


def check(label, fn):
    try:
        fn()
        print(f"  ✓ {label}")
    except Exception as e:
        print(f"  ✗ {label}: {e}")
        traceback.print_exc()
        FAILURES.append(label)


def _import_app():
    # Importing main transitively imports every router + data module, so a
    # missing symbol (like the store.py one) surfaces right here.
    import src.api.main  # noqa: F401


def _suppress_background_loops():
    """Stop the boot probe from running the app's daily work (S-161).

    The comment this replaces said: "Background loops only create_task + sleep,
    so nothing network-bound runs during the test." **That was false**, and it
    was the assumption that cost 2026-08-12. The loops do their work on the
    FIRST iteration and sleep afterwards, so booting the app fires 30 of them
    into Moralis, CoinGecko Pro, Binance and the paper-book marks.

    On a machine without network egress they fail instantly and the smoke test
    takes two seconds. On a laptop with internet they execute a full daily
    cycle, and preflight stalls with `[HEARTBEAT]` as its last line — which is
    simply the last thing printed before the loops start doing work, not where
    the fault is. A gate whose runtime depends on whether the machine has
    internet is a coin flip you cannot read.

    SUPPRESSED BY COROUTINE NAME, and that is load-bearing. Of the 31 tasks the
    startup handlers create, 30 are named `*_loop` and exactly one is not:
    `_run()`, the MCP session manager — whose handler then does
    `await _ready.wait()`, with `_ready` set INSIDE `_run`. Declining to
    schedule that one does not skip work, it deadlocks the boot forever. An
    earlier attempt suppressed all 31 indiscriminately and did exactly that.

    So the filter is not a heuristic that happens to work; it is the line
    between fire-and-forget data loops and infrastructure the boot awaits.

    Scoped to this script. `src/api/main.py` is untouched, so production
    behaviour is bit-identical.
    """
    import asyncio
    _real_create_task = asyncio.create_task
    skipped = []

    def _filtered(coro, *args, **kwargs):
        name = getattr(getattr(coro, "cr_code", None), "co_name", "")
        if name.endswith("_loop") or "_loop" in name:
            skipped.append(name)
            coro.close()          # else Python warns "coroutine never awaited"
            return None
        return _real_create_task(coro, *args, **kwargs)

    asyncio.create_task = _filtered
    return _real_create_task, skipped


def _boot_and_probe():
    # Real ASGI startup via TestClient — proves routes resolve and startup
    # event handlers don't throw. Background data loops are suppressed (see
    # _suppress_background_loops); the MCP session manager still starts,
    # because the startup path awaits it.
    import asyncio
    restore = None
    if os.environ.get("DISABLE_BACKGROUND_LOOPS", "").lower() in ("1", "true", "yes"):
        restore, skipped = _suppress_background_loops()
    try:
        from fastapi.testclient import TestClient
        from src.api.main import app
        with TestClient(app) as client:
            r = client.get("/internal/build-state")
            assert r.status_code == 200, f"/internal/build-state → {r.status_code}"
    finally:
        if restore is not None:
            asyncio.create_task = restore
            print(f"    · {len(skipped)} background data loop(s) not started "
                  f"(DISABLE_BACKGROUND_LOOPS=1); MCP session manager unaffected")


def main():
    print("Smoke test — import + boot")
    check("import src.api.main", _import_app)
    # Only attempt boot if import succeeded (avoids a confusing second trace).
    if "import src.api.main" not in FAILURES:
        check("boot app + GET /internal/build-state", _boot_and_probe)

    if FAILURES:
        print(f"\nSMOKE FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nSMOKE OK")


if __name__ == "__main__":
    main()
