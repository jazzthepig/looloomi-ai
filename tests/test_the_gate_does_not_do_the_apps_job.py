"""
Guard: booting the app in a test must not run the app (S-158).

2026-08-13. Preflight boots the FastAPI app three times (the boot smoke, the
route-shadow guard, the strategy-vector smoke). Each boot fires 31
`@app.on_event("startup")` handlers, and every one of them schedules a
background loop that immediately does real work: Moralis holder maps, CoinGecko
Pro, Binance klines, the paper-book marks.

In a sandbox with no network egress those fail instantly and preflight finishes
in 48 seconds. On a laptop with internet they execute a full daily cycle, and
the gate appears to hang — Jazz watched it stall after check 27 twice and could
not tell a slow run from a dead one. **A gate whose runtime depends on whether
the machine has internet is a coin flip you cannot read**, and an unreadable
gate is one that gets skipped. That is how 2026-08-12's outage reached
production with 504 checks green.

Per-loop flags already existed — DISABLE_METERING, DISABLE_SL_TP_LOOP,
REBAL_LOOP_ENABLED — thirty-one loops and no way to say "none". `_schedule_task`
is the switch that also covers the loop somebody adds next month.

THE PRINTS ARE PART OF THE FIX. The first version declined to schedule and left
the 29 "✅ loop scheduled" lines printing anyway, which is a log that lies about
what the process is doing — the exact defect class this repo has spent two days
removing. The print is now conditional on the task actually being created.

Run: python3 -m tests.test_the_gate_does_not_do_the_apps_job
"""
from __future__ import annotations

import ast
import os
import subprocess
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


_MAIN = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
_LINES = _MAIN.splitlines()


def test_no_startup_handler_calls_create_task_directly() -> None:
    """The switch only holds if nothing routes around it. A loop added next
    month with a bare create_task is invisible to every flag we have."""
    tree = ast.parse(_MAIN)
    leaks = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        is_startup = any(
            isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "on_event"
            and d.args and getattr(d.args[0], "value", None) == "startup"
            for d in node.decorator_list)
        if not is_startup:
            continue
        for n in ast.walk(node):
            if not (isinstance(n, ast.Call) and "create_task" in ast.unparse(n.func)):
                continue
            # An exemption is allowed but must be DECLARED. Infrastructure the
            # boot awaits cannot go through the switch (see the MCP deadlock
            # below) — but "I forgot" and "I decided" must not look the same,
            # which is the whole lesson of the last two days.
            preceding = "\n".join(_LINES[max(0, n.lineno - 10):n.lineno])
            if "NOT _schedule_task" in preceding:
                continue
            leaks.append(f"{node.name} (line {n.lineno})")
    check("every startup scheduler goes through _schedule_task, or declares why not",
          not leaks,
          f"bare create_task in: {leaks} — route it through _schedule_task, or "
          f"write '# NOT _schedule_task' above it with the reason. An undeclared "
          f"exemption is indistinguishable from an oversight.")


def test_the_switch_declines_and_closes_the_coroutine() -> None:
    """Closing matters: an un-awaited coroutine emits a RuntimeWarning per loop,
    so a naive switch would add 31 warnings to the output of the very gate this
    exists to make readable."""
    src = _MAIN.split("def _schedule_task")[1][:600]
    check("_schedule_task closes the declined coroutine", "coro.close()" in src, src[:150])
    check("and returns None so the caller can tell", "return None" in src, src[:150])


def test_the_log_does_not_claim_a_loop_it_declined() -> None:
    """The first version left 29 '✅ loop scheduled' prints firing while nothing
    was scheduled. A log that lies is worse than a silent one, because it is
    believed."""
    unconditional = []
    lines = _MAIN.splitlines()
    for i, l in enumerate(lines):
        if "_schedule_task(" in l and not l.strip().startswith("#"):
            if l.strip().startswith("if _schedule_task("):
                continue
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if "loop scheduled" in nxt or "✅" in nxt:
                unconditional.append(i + 1)
    check("every 'loop scheduled' print is conditional on the task existing",
          not unconditional, f"unconditional prints after lines {unconditional}")


def test_preflight_sets_the_switch_for_every_suite() -> None:
    pf = (_ROOT / "scripts/preflight.sh").read_text(encoding="utf-8")
    check("preflight exports DISABLE_BACKGROUND_LOOPS",
          "export DISABLE_BACKGROUND_LOOPS=1" in pf,
          "set per-suite it would miss the suite added next month")


def test_the_app_still_schedules_its_loops_by_default() -> None:
    """A switch that is on by default is a production outage with a test suite.
    Booting WITHOUT the flag must still schedule them."""
    env = {**os.environ, "INTERNAL_TOKEN": "x", "ENVIRONMENT": "ci"}
    env.pop("DISABLE_BACKGROUND_LOOPS", None)
    r = subprocess.run([sys.executable, "scripts/smoke_test.py"], cwd=_ROOT,
                       env=env, capture_output=True, text=True, timeout=300)
    on = (r.stdout + r.stderr).count("loop scheduled")
    check("default boot schedules its loops", on > 20, f"only {on} — the switch "
          f"is defaulting ON, which would silently stop production")

    env["DISABLE_BACKGROUND_LOOPS"] = "1"
    r2 = subprocess.run([sys.executable, "scripts/smoke_test.py"], cwd=_ROOT,
                        env=env, capture_output=True, text=True, timeout=300)
    off = (r2.stdout + r2.stderr).count("loop scheduled")
    check("and the switch actually silences them", off == 0, f"{off} still scheduled")



def test_no_awaited_task_is_routed_through_the_switch() -> None:
    """THE 2026-08-13 deadlock, generalised.

    The switch was applied to all 31 startup create_tasks including the MCP
    session manager, whose handler does:

        _mcp_task = _schedule_task(_run())
        await _ready.wait()          # _ready is set INSIDE _run()

    Declining to schedule closed the coroutine, `_ready` was never set, and the
    boot blocked forever — preflight hung on the smoke test with no output, on
    a machine where `mcp` is installed. It passed in a sandbox where the module
    is absent and that whole branch never runs, which is why reading the code
    was the only thing that could find it.

    THE RULE: **a task whose completion the startup path AWAITS can never be
    optional.** Switching it off does not skip work, it deadlocks the boot. So
    infrastructure goes through `_asyncio.create_task` directly; only
    fire-and-forget data loops go through the switch."""
    import ast
    src = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    offenders = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_schedule_task":
            window = "\n".join(lines[n.lineno: n.lineno + 6])
            if "await " in window and (".wait()" in window or "_ready" in window):
                offenders.append(n.lineno)
    check("no _schedule_task result is awaited by the startup path",
          not offenders,
          f"lines {offenders} — declining to schedule these deadlocks the boot "
          f"instead of skipping work; use _asyncio.create_task directly")


def test_the_mcp_session_manager_is_exempt() -> None:
    """Named explicitly, because it is the one that bit and a future refactor
    that folds it back into the switch would reproduce the deadlock exactly."""
    src = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    blk = src.split("async def _run():")[1][:1200] if "async def _run():" in src else ""
    check("MCP task uses create_task, not the switch",
          "_mcp_task = _asyncio.create_task(_run())" in src,
          "the MCP session manager is infrastructure the boot awaits")
    check("and the reason is recorded at the site",
          "deadlocks the boot" in src or "block forever" in src,
          "a future refactor needs to know why this one is different")


if __name__ == "__main__":
    print("── the gate must not do the app's job (S-158) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ booting the app in a test no longer runs the app")
