"""CI Smoke gate must cover scripts/ + tests/, not just src/.

The 2026-09-18 ops-console triage revealed a coverage gap: ci-smoke.yml's
`paths:` trigger listed only `src/**`, so changes to `scripts/ops_console.py`
(and any other scripts/ file) bypassed the gate entirely. The fix extended
the trigger list — this test pins it down so a future refactor can't quietly
revert it.

Run: python3 -m pytest tests/test_ci_smoke_paths.py
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci-smoke.yml"


def _read_workflow() -> str:
    assert WORKFLOW.exists(), f"ci-smoke.yml missing at {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_smoke_triggers_on_scripts_paths():
    """`scripts/**` must be in the push paths trigger.

    Without this, the S-371-style regression (NameError in scripts/ rendered as
    upstream error via the local ops console) reaches main unchecked.
    """
    text = _read_workflow()
    # The trigger lives inside the `paths:` block under `on.push`. Look for
    # both the literal and a comment-anchored confirmation so a future edit
    # doesn't accidentally narrow the path back to src-only.
    assert "scripts/**" in text, (
        "ci-smoke.yml no longer triggers on scripts/** — the S-371 gap "
        "(NameError in scripts/ops_console.py rendered as upstream error) "
        "would be back. See commit history for the 2026-09-18 fix."
    )


def test_ci_smoke_triggers_on_tests_paths():
    """`tests/**` must be in the push paths trigger.

    The discipline suite lives here. A syntax error in a test file is a
    discipline failure that should also block the gate, not slip through
    silently.
    """
    text = _read_workflow()
    assert "tests/**" in text, (
        "ci-smoke.yml no longer triggers on tests/** — a test file with a "
        "SyntaxError would slip into main and silently disable one branch of "
        "the discipline suite."
    )


def test_ci_smoke_has_compileall_step():
    """compileall step is what makes the gate meaningful for scripts/ changes.

    Without it, paths scope widens but the gate still only runs
    `scripts/smoke_test.py` — which doesn't import `scripts/ops_console.py`.
    A syntax error in ops_console.py would still slip through. compileall is
    parse-only (no top-level execution) so it won't false-fail on scripts
    that need env vars.
    """
    text = _read_workflow()
    assert "compileall" in text, (
        "ci-smoke.yml no longer has the compileall step — paths scope is "
        "wider but the gate still doesn't actually compile scripts/*.py."
    )
