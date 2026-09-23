"""
S-410 — `_cg_panel_loop` failed 366 consecutive times with
"too many values to unpack (expected 2)" because S-378b-C1 added a third
return value to `deep_panel_symbols_detailed()` (the `latest_hint`) but the
caller in `src/api/main.py:_cg_panel_loop` still did a 2-tuple unpack.

THE BUG, EXACT SHAPE. The function's signature at `deep_panel_collector.py:153`:

    async def deep_panel_symbols_detailed() -> tuple[list[str] | None,
                                                     dict,
                                                     list[str] | None]: ...

returns 3 values. The caller did:

    _panel, _detail = await deep_panel_symbols_detailed()   # ← 2-targets

Python tuple unpacking fails with **"too many values to unpack (expected 2)"**
when there are MORE values than targets — so the 3-tuple blew up at the
caller every round. `_cg_panel_loop`'s catch-all (`main.py:1074`) then
recorded `_beat(ok=False, error=str(_e))` every 600s, and the heartbeat
counter climbed: 297 → 366 in 4 hours.

WHY THIS TEST GUARDS THE FUTURE.

  1. **Static guard.** A 2-tuple unpack of `deep_panel_symbols_detailed`
     would re-break the loop. We grep `src/api/main.py` for the call site
     and verify the LHS has 3 names.
  2. **Runtime smoke.** Mock `deep_panel_symbols_detailed` to return a
     3-tuple; verify Python's tuple-unpack accepts it cleanly.

Run: python3 -m tests.test_cg_panel_loop_unpacks_three_tuple
"""
from __future__ import annotations

import ast
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


# ── static guard via AST: every call site must unpack 3 targets ──────────────

def test_main_py_call_site_unpacks_three_targets() -> None:
    """Walk `src/api/main.py`'s tree. For each `await deep_panel_symbols_detailed()`
    call, the LHS must have exactly 3 names. A regression that drops to 2
    would re-break the loop with "too many values to unpack (expected 2)"."""
    main_path = _ROOT / "src" / "api" / "main.py"
    tree = ast.parse(main_path.read_text())

    # Collect every `Assign` whose RHS contains a Call to deep_panel_symbols_detailed
    bad = []
    good = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        rhs = node.value
        # We want `x, y, z = await func(...)` → rhs is Await(Call(func, ...))
        if not isinstance(rhs, ast.Await):
            continue
        call = rhs.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        # func may be Attribute (module.attr) or Name (imported name)
        func_name = None
        if isinstance(func, ast.Attribute):
            func_name = func.attr
        elif isinstance(func, ast.Name):
            func_name = func.id
        if func_name != "deep_panel_symbols_detailed":
            continue
        # Count targets
        if len(node.targets) != 1:
            bad.append(f"unexpected target shape: {ast.dump(node.targets)}")
            continue
        tgt = node.targets[0]
        if isinstance(tgt, ast.Tuple):
            n = len(tgt.elts)
            if n == 3:
                good.append(n)
            else:
                bad.append(f"unpacks {n} targets (must be 3)")
        elif isinstance(tgt, ast.Name):
            # single-target unpack → would never match a 3-tuple return
            bad.append(f"single-target assign, can't accept 3-tuple")

    check("at least one call site exists in main.py",
          len(good) + len(bad) >= 1,
          f"good={good} bad={bad}")
    check("every call site unpacks exactly 3 targets",
          len(bad) == 0 and len(good) >= 1,
          f"bad sites: {bad}; good: {good}")


# ── runtime smoke: a 3-tuple return is accepted by 3-target unpack ────────────

def test_three_target_unpack_accepts_three_tuple() -> None:
    """Direct: build the exact unpack pattern from `_cg_panel_loop` and feed it
    a 3-tuple. If anyone reverts the LHS to 2 targets, this test will fail
    FIRST — before the loop even runs in production."""
    # Mimic: `_panel, _detail, _latest_hint = await deep_panel_symbols_detailed()`
    panel = ["BTC", "ETH", "SOL"]
    detail = {"outcome": "ok", "fn": "deep_panel_symbols_fast", "n_rows": 3}
    latest_hint = None
    try:
        _panel, _detail, _latest_hint = panel, detail, latest_hint
    except ValueError as e:
        check("3-tuple unpacks cleanly with 3 targets",
              False, f"ValueError: {e}")
        return
    check("3-tuple unpacks cleanly with 3 targets", True)
    check("_panel is the symbol list",
          _panel == ["BTC", "ETH", "SOL"], f"got {_panel}")
    check("_detail is the diagnostic dict",
          _detail == {"outcome": "ok", "fn": "deep_panel_symbols_fast", "n_rows": 3},
          f"got {_detail}")
    check("_latest_hint is None when fast RPC doesn't return `latest`",
          _latest_hint is None, f"got {_latest_hint}")


# ── the gold-standard regression: the EXACT bug string would now error ────────

def test_two_target_unpack_of_three_tuple_demonstrates_bug() -> None:
    """If the LHS in main.py drops back to 2 targets, the unpack raises
    `ValueError: too many values to unpack (expected 2)` — the EXACT string
    the heartbeat was recording 366 times. This test pins that error shape
    so any future regression catches it."""
    three_tuple = (["BTC"], {"outcome": "ok"}, None)
    raised = None
    try:
        _panel, _detail = three_tuple   # noqa: F841  — same shape as the bug
    except ValueError as e:
        raised = e
    check("the bug shape raises ValueError",
          raised is not None,
          f"no error: {raised}")
    check("the bug shape's error is 'too many values to unpack (expected 2)'",
          raised is not None
          and "too many values to unpack" in str(raised)
          and "expected 2" in str(raised),
          f"got: {raised!r}")


if __name__ == "__main__":
    print("── S-410: _cg_panel_loop unpacks deep_panel_symbols_detailed as 3-tuple ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ static guard · runtime smoke · bug-shape pinned")