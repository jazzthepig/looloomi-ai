# Tests package.
#
# ── BOOTING THE APP MUST NOT RUN THE APP (S-161, 2026-08-13) ─────────────────
#
# Several suites do `with TestClient(app):` to prove routes resolve and startup
# handlers don't throw. That fires 30 background loops, and the loops do their
# work on the FIRST iteration and sleep afterwards — Moralis holder maps,
# CoinGecko Pro, Binance klines, the paper-book marks. With no network egress
# they fail instantly and preflight takes 47s; on a laptop with internet they
# execute a full daily cycle and the gate appears to hang, printing
# `[HEARTBEAT]` last, which is simply the final line before the work starts.
#
# WHY IT LIVES HERE AND NOT IN EACH FILE. The first fix patched
# scripts/smoke_test.py only. preflight boots the app from THREE places —
# smoke_test.py, tests/conftest.py and tests/test_no_route_is_shadowed.py — so
# two of them kept running the loops and the hang persisted, which cost another
# round and one more wrong diagnosis. `tests/` is a package, so this module runs
# before any `python3 -m tests.X`: one place, and it covers the suite somebody
# adds next month.
#
# SUPPRESSED BY COROUTINE NAME, and that is load-bearing rather than a
# heuristic. Of the 31 tasks main.py's startup handlers create, 30 are named
# `*_loop` and exactly one is not: `_run()`, the MCP session manager — whose
# handler then does `await _ready.wait()` with `_ready` set INSIDE `_run`.
# Declining to schedule that one does not skip work, it deadlocks the boot
# forever. An earlier attempt suppressed all 31 indiscriminately and did exactly
# that, visible only on a machine where the `mcp` package is installed.
#
# Default OFF. preflight opts in via DISABLE_BACKGROUND_LOOPS=1, and
# src/api/main.py is untouched, so production behaviour is bit-identical.
import os as _os

if _os.environ.get("DISABLE_BACKGROUND_LOOPS", "").lower() in ("1", "true", "yes"):
    import asyncio as _asyncio

    _real_create_task = _asyncio.create_task
    SKIPPED_LOOPS: list[str] = []

    def _filtered_create_task(coro, *args, **kwargs):
        name = getattr(getattr(coro, "cr_code", None), "co_name", "")
        if "_loop" in name:
            SKIPPED_LOOPS.append(name)
            coro.close()          # else Python warns "coroutine never awaited"
            return None
        return _real_create_task(coro, *args, **kwargs)

    _asyncio.create_task = _filtered_create_task
