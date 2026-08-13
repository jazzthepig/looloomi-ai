"""
Guard: the boot probe boots the app without running it (S-161).

2026-08-12/13. `scripts/smoke_test.py` carried this comment:

    "Background loops only create_task + sleep, so nothing network-bound runs
     during the test."

It was false, and the assumption cost a night. The loops do their work on the
FIRST iteration and sleep afterwards, so booting the app fires 30 of them into
Moralis, CoinGecko Pro, Binance and the paper-book marks. With no network egress
that fails instantly and the probe takes two seconds; with internet it runs a
full daily cycle and preflight stalls, printing `[HEARTBEAT]` last — which is
just the final line before the loops begin, not where the fault is.

THE FILTER IS THE WHOLE DESIGN. Of the 31 tasks the startup handlers create, 30
are named `*_loop` and exactly one is not: `_run()`, the MCP session manager,
whose handler then does `await _ready.wait()` with `_ready` set INSIDE `_run`.
Skipping that one does not skip work — it deadlocks the boot forever. An earlier
attempt suppressed all 31 indiscriminately and did exactly that, and it only
showed up on a machine where the `mcp` package is installed.

So this suite asserts the ratio, not the mechanism: if a future loop is added
without a `_loop` suffix it will silently run during the probe, and if the MCP
task is ever renamed to end in `_loop` the boot will hang. Both are caught here.

Run: python3 -m tests.test_the_boot_probe_does_not_run_the_app
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
    print(f"  {'✓' if cond else '✗'} {name}" + ("" if cond else f" :: {detail}"))
    if not cond:
        _FAILURES.append(name)


def _startup_task_names() -> list[str]:
    src = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    out = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "on_event"
                   and d.args and getattr(d.args[0], "value", None) == "startup"
                   for d in n.decorator_list):
            continue
        for c in ast.walk(n):
            if isinstance(c, ast.Call) and "create_task" in ast.unparse(c.func) and c.args:
                out.append(ast.unparse(c.args[0]))
    return out


def test_every_data_loop_is_named_so_the_filter_can_see_it() -> None:
    names = _startup_task_names()
    check("startup schedules a plausible number of tasks", len(names) >= 25, str(len(names)))
    unfiltered = [x for x in names if "_loop" not in x]
    check("exactly one startup task is not a *_loop",
          len(unfiltered) == 1,
          f"{unfiltered} — a data loop without a _loop name runs during the probe "
          f"and puts the gate back on the network")
    check("and it is the MCP session manager",
          unfiltered == ["_run()"],
          f"{unfiltered} — this is the task the boot AWAITS; suppressing it "
          f"deadlocks startup instead of skipping work")


def test_the_suppression_lives_outside_production_code() -> None:
    """main.py must stay bit-identical. An earlier attempt rewired 31 call sites
    in production code and deadlocked the boot."""
    main = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    check("main.py has no boot-probe switch", "DISABLE_BACKGROUND_LOOPS" not in main,
          "the suppression belongs to the test harness, not the app")
    smoke = (_ROOT / "scripts/smoke_test.py").read_text(encoding="utf-8")
    check("smoke_test owns the suppression", "DISABLE_BACKGROUND_LOOPS" in smoke, "")
    check("and restores create_task afterwards",
          "asyncio.create_task = restore" in smoke,
          "leaving it patched would silence loops for anything importing this later")
    # Checked in ACTIVE `#` comments only. The first cut searched the whole
    # file and fired on the docstring that QUOTES the false sentence in order
    # to correct it — a guard matching its own explanation, for the fifth time
    # in this repo. The quotation must survive; the claim must not.
    live_comments = "\n".join(l for l in smoke.splitlines()
                              if l.lstrip().startswith("#"))
    check("the false 'only create_task + sleep' claim is no longer asserted",
          "only create_task + sleep" not in live_comments,
          "that sentence is the assumption that cost the night")
    check("but the correction still quotes it, so the lesson survives",
          "only create_task + sleep" in smoke,
          "deleting the quote would erase why this exists")


def test_the_probe_is_fast_and_still_probes() -> None:
    env = {**os.environ, "INTERNAL_TOKEN": "x", "ENVIRONMENT": "ci",
           "DISABLE_BACKGROUND_LOOPS": "1"}
    r = subprocess.run([sys.executable, "scripts/smoke_test.py"], cwd=_ROOT,
                       env=env, capture_output=True, text=True, timeout=240)
    out = r.stdout + r.stderr
    check("smoke passes with loops suppressed", "SMOKE OK" in out, out[-400:])
    check("it still boots and probes an endpoint",
          "boot app + GET /internal/build-state" in out, out[-400:])
    check("it says how many loops it skipped",
          "background data loop(s) not started" in out,
          "a suppression nobody can see is one nobody can audit")


def test_the_default_still_starts_the_loops() -> None:
    """A switch that is on by default is a production outage with a test suite."""
    env = {**os.environ, "INTERNAL_TOKEN": "x", "ENVIRONMENT": "ci"}
    env.pop("DISABLE_BACKGROUND_LOOPS", None)
    r = subprocess.run([sys.executable, "scripts/smoke_test.py"], cwd=_ROOT,
                       env=env, capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    check("without the flag the loops still schedule",
          out.count("loop scheduled") > 20,
          f"only {out.count('loop scheduled')} — the switch is defaulting ON")


if __name__ == "__main__":
    print("── the boot probe boots without running the app (S-161) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ booting is not running")
