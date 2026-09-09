"""S-323r — the valuation window is 30 minutes wide; we used one second of it.

NAV_POLICY §3 gives an INTERVAL: valuation point 00:05 UTC, tolerance ±30 min,
and a mark that cannot be struck inside it is refused rather than struck late.
All eight book loops were "wake, try once, fail, sleep 24h", so the remaining
29 minutes were never used.

Measured 2026-09-09: the Hyperliquid listing blipped at 00:05:39, ① refused,
and the next attempt was 24 hours later. A two-second blip cost an unrepeatable
day of the forward record — which is the product.

This does NOT relax §3. The window boundary is untouched: past tolerance it
still refuses and still never marks late. What changed is how many attempts we
make inside the time we are already allowed.

Run: python3 -m pytest tests/test_mark_retries_inside_the_valuation_window.py
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BOOK_LOOPS = [
    "_causal_paper_loop", "_dingge_paper_loop", "_combined_book_loop",
    "_scalable_book_loop", "_beta_core_loop", "_two_layer_paper_loop",
    "_fusion_paper_loop",
]


def _loop_body(src: str, name: str) -> str:
    st = src.index(f"async def {name}(")
    nx = src.find("\nasync def ", st + 10)
    at = src.find("\n@app", st + 10)
    end = min(x for x in (nx, at, len(src)) if x > 0)
    return src[st:end]


def test_every_book_loop_retries_inside_the_window():
    """The class, not the call site. Fixing only ① is the S-323i mistake."""
    src = (ROOT / "src" / "api" / "main.py").read_text()
    missing = [n for n in BOOK_LOOPS
               if "_mark_within_valuation_window" not in _loop_body(src, n)]
    assert not missing, (
        f"{missing} still mark one-shot. Eight loops share one skeleton; "
        f"patching only the one that broke is how S-323i and S-323o happened."
    )


def test_the_window_boundary_was_not_relaxed():
    """NEGATIVE CONTROL. Retrying must not become marking late."""
    src = (ROOT / "src" / "api" / "main.py").read_text()
    helper = src.split("async def _mark_within_valuation_window")[1].split(
        "\ndef _minutes_from_valuation_point_utc")[0]
    assert "tolerance_min" in helper and "left_min" in helper, (
        "the retry must be bounded by the tolerance window, not by a count"
    )
    assert "_minutes_from_valuation_point_utc" in helper, (
        "bound the retry with the SAME clock §3 uses — a second notion of "
        "'near the valuation point' is a second source of truth"
    )


def _inside_window(m, monkeypatch, minutes_from_point: float = 1.0):
    """Pin the clock INSIDE the valuation window.

    Without this the test is a clock test, not a retry test: run it at 06:30
    and the helper correctly declines to retry because the window shut hours
    ago — which is the behaviour §3 requires and must stay true.
    """
    monkeypatch.setattr(m, "_minutes_from_valuation_point_utc",
                        lambda *a, **k: minutes_from_point)


def test_a_transient_failure_is_retried_and_then_succeeds(monkeypatch):
    import src.api.main as m
    _inside_window(m, monkeypatch)

    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("venue blipped")
        return {"status": "ok", "nav": 1.0}

    m._MARK_RETRY_S = 0                      # no real sleeping in a test
    res, ok, ref, why, tries = asyncio.run(
        m._mark_within_valuation_window("_test_loop", _flaky, tolerance_min=30))
    assert ok is True and tries == 3, (res, ok, tries)


def test_an_exception_does_not_destroy_the_reason(monkeypatch):
    """res must stay dict-shaped: the call sites do res.get('status') straight
    after, and a None there raises AttributeError which the outer except then
    records INSTEAD of the real cause."""
    import src.api.main as m
    _inside_window(m, monkeypatch, minutes_from_point=999.0)   # window shut

    async def _always_fail():
        raise RuntimeError("the actual cause")

    m._MARK_RETRY_S = 0
    res, ok, ref, why, tries = asyncio.run(
        m._mark_within_valuation_window("_test_loop", _always_fail,
                                        tolerance_min=30))
    assert isinstance(res, dict), "res must remain .get()-able"
    assert res.get("status") == "error"
    assert "the actual cause" in why


def test_a_refusal_is_not_retried(monkeypatch):
    """`refused` means it ran and correctly had nothing to do — not a fault."""
    import src.api.main as m
    _inside_window(m, monkeypatch)

    calls = {"n": 0}

    async def _refuses():
        calls["n"] += 1
        return {"status": "skipped", "reason": "insufficient_live_data"}

    m._MARK_RETRY_S = 0
    res, ok, ref, why, tries = asyncio.run(
        m._mark_within_valuation_window("_test_loop", _refuses, tolerance_min=30))
    assert tries == 1, "a refusal was retried — that is noise, not recovery"


def test_outside_the_window_it_does_not_retry_at_all(monkeypatch):
    """NEGATIVE CONTROL for §3: past tolerance, one attempt and stop.

    This is the assertion that keeps 'retry inside the window' from quietly
    becoming 'retry until it works', which would be marking late.
    """
    import src.api.main as m
    _inside_window(m, monkeypatch, minutes_from_point=400.0)   # 6h past the point

    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        raise RuntimeError("still down")

    m._MARK_RETRY_S = 0
    _res, ok, _ref, _why, tries = asyncio.run(
        m._mark_within_valuation_window("_test_loop", _flaky, tolerance_min=30))
    assert ok is False and tries == 1, (
        "outside the tolerance window the mark must be refused, not retried — "
        "retrying there is marking late, which §3 forbids"
    )
