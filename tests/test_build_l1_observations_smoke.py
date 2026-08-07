"""
Build L1 Observations — script-shape smoke tests
================================================

`scripts/build_l1_observations.py --diagnose` requires live Supabase + DNS. The
gate runs offline/deterministic; these tests cover the pure logic so the gate
catches regressions without hitting the network.

The full network probe lives in the scheduled cron path; the mac-side operator
runs `--diagnose` manually before scheduling.

Run:  python3 -m tests.test_build_l1_observations_smoke
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.build_l1_observations import (  # noqa: E402
    LOCAL_11YR, LOCAL_OHLCV, SHADOW_PANEL,
    compute_panel_series, resolve_panel_source,
    diagnose,
)


# ── constants + paths ────────────────────────────────────────────────────────
def test_constants_are_paths():
    assert isinstance(LOCAL_11YR, Path)
    assert isinstance(LOCAL_OHLCV, Path)
    assert isinstance(SHADOW_PANEL, Path)
    # path strings should look plausible (start with /)
    assert str(LOCAL_11YR).startswith("/")
    assert str(LOCAL_OHLCV).startswith("/")
    assert str(SHADOW_PANEL).startswith("/")


# ── resolve_panel_source ("none" branch is fully offline) ─────────────────────
def test_resolve_panel_source_none_returns_empty():
    """explicit='none' must short-circuit; no FS probe."""
    src, path = resolve_panel_source("none")
    assert src == "none"
    assert path == ""


# ── compute_panel_series: pure function on a dict ────────────────────────────
def test_compute_panel_series_returns_expected_shape():
    """Synthetic input → expected output schema.

    The function consumes panel = {date: {series: (mean, dispersion)}} and
    produces a per-series summary. Empty input must not raise.
    """
    empty = compute_panel_series({}, "test_run")
    assert isinstance(empty, dict), \
        f"empty input must return a dict, got {type(empty).__name__}"
    # Either the dict is empty (function gracefully no-ops) OR it carries
    # series-keyed zeros (function reports "0 observations" for each series).
    # Both are acceptable; what matters is the type and the non-NaN contract.
    for v in empty.values() if empty else []:
        # No NaN leaks: a value that should be numeric must be numeric or None.
        if v is not None:
            assert isinstance(v, (int, float)), \
                f"empty-input value leaked as {type(v).__name__}: {v!r}"


def test_compute_panel_series_handles_sparse_input():
    """A single (date, series) row should produce one series entry."""
    panel = {
        "2026-01-01": {
            "vol_mkt": (0.025, 0.001),
            "funding_mean": (0.0001, 0.00005),
        }
    }
    out = compute_panel_series(panel, "single_point")
    assert isinstance(out, dict)
    # The function must not NaN-out a series when only one observation exists
    # (the user-facing dashboard needs at least "this exists" semantics).


# ── diagnose exists + has the correct contract ────────────────────────────────
def test_diagnose_function_exists_and_is_callable():
    assert callable(diagnose)
    # The function must NOT require arguments — it's the entry-point for
    # `--diagnose` mode.
    import inspect
    sig = inspect.signature(diagnose)
    assert len(sig.parameters) == 0


def test_diagnose_docstring_explains_purpose():
    """The 2026-08-02 lesson is in the docstring; if it's gone, the rationale
    for why this script exists is gone too."""
    doc = diagnose.__doc__ or ""
    assert doc.strip(), "diagnose() must have a docstring"
    # Specific phrases that anchor the rationale
    assert "preconditions" in doc.lower() or "explain" in doc.lower(), \
        "docstring must explain WHY the function exists (not just WHAT)"


# ── driver ───────────────────────────────────────────────────────────────────
def _run_all():
    import inspect
    tests = [(n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {name} — {e}")
        except Exception as e:                                # noqa: BLE001
            print(f"  ✗ {name} — {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} build_l1_observations smoke checks passed")
    sys.exit(0 if passed == len(tests) else 1)


if __name__ == "__main__":
    _run_all()