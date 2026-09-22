"""Smoke test for S-397 panel_long_short_jev_overlay spec_runner family.

Per `s397-jev-ls-overlay-redesign-2026-09-21.md`: the new spec family wires
① base (1/N long) + ④ Jev L/S overlay into a single `decide_*` function.

What we test:
  1. Spec.load accepts the new family and validates parameters
  2. decide_panel_long_short_jev_overlay returns ENTERED with base + overlay legs
  3. Coverage gate: no_edge / low confidence → overlay abstains, base still ENTERED
  4. Fail-open: jev_decision.error → base still ENTERED (no overlay signal)
  5. Mock always_no_edge backend → no overlay positions, base still ENTERED
  6. Jev actor stats accumulate across multiple decide() calls
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_trading.spec_runner import (   # noqa: E402
    Spec, Panel, decide_panel_long_short_jev_overlay,
    build_panel,
)
from paper_trading.jev_decision import (   # noqa: E402
    JevDecision, JevDecisionActor, MockJevDecisionBackend, build_ls_questions,
)


SPEC_PATH = str(_ROOT / "paper_trading" / "specs" / "s397_jev_ls_overlay.json")
UNIVERSE_5 = ["BTC", "ETH", "SOL", "BNB", "XRP"]


def _make_panel(n_days: int = 400, end: dt.date = None) -> Panel:
    """Synthetic panel — 5 symbols × n_days monotonically rising, ending at `end`.

    Default end = 2026-09-21 (so as_of=2026-09-21 has age=0, no BLOCKED on staleness).
    """
    if end is None:
        end = dt.date(2026, 9, 21)
    closes: dict[str, dict[str, float]] = {}
    base = end - dt.timedelta(days=n_days - 1)
    for sym in UNIVERSE_5:
        per_sym: dict[str, float] = {}
        px = 100.0
        for i in range(n_days):
            d = (base + dt.timedelta(days=i)).isoformat()
            px *= 1.0 + (0.001 if sym == "BTC" else 0.002 if sym == "ETH"
                          else 0.003 if sym == "SOL"
                          else 0.0005 if sym == "BNB" else -0.0008)
            per_sym[d] = round(px, 4)
        closes[sym] = per_sym
    last = max(d for s in closes.values() for d in s)
    return Panel(closes=closes, source="synthetic", last_bar=last, n_symbols=5)


# ── Spec.load validation ──────────────────────────────────────────────────


def test_spec_load_new_family_succeeds():
    """Spec.load accepts the s397 spec file."""
    spec = Spec.load(SPEC_PATH)
    assert spec.family == "panel_long_short_jev_overlay"
    assert set(spec.universe) == set(UNIVERSE_5)
    print(f"✓ spec loaded: family={spec.family}, universe={list(spec.universe)}")


def test_spec_load_rejects_bogus_jev_overlay():
    """bogus jev_overlay values raise ValueError in Spec.load."""
    bad_spec = json.loads(Path(SPEC_PATH).read_text())
    bad_spec["parameters"]["jev_overlay"]["coverage_threshold"] = 1.5  # > 1
    bad_path = _ROOT / "paper_trading" / "specs" / "_tmp_bad_s397.json"
    bad_path.write_text(json.dumps(bad_spec))
    try:
        with pytest.raises(ValueError, match="超出"):
            Spec.load(str(bad_path))
        print("✓ coverage_threshold > 1 raises")
    finally:
        bad_path.unlink()


# ── decide function ────────────────────────────────────────────────────────


def test_decide_entered_with_mock_always_no_edge():
    """always_no_edge backend → no overlay positions, base still ENTERED."""
    spec = Spec.load(SPEC_PATH)
    panel = _make_panel()
    backend = MockJevDecisionBackend(mode="always_no_edge")
    actor = JevDecisionActor(backend=backend)
    as_of = dt.date(2026, 9, 21)
    decision = decide_panel_long_short_jev_overlay(
        spec, panel, as_of=as_of, regime=None,
        n_open=0, last_rebalance=None, jev_actor=actor,
    )
    assert decision.verdict == "ENTERED"
    # 5 base legs (1/N long), 0 overlay legs (always_no_edge)
    assert len(decision.legs) == 5
    # All legs are "long"
    assert all(leg.side == "long" for leg in decision.legs)
    print(f"✓ ENTERED with 5 base legs (no overlay), actor stats: {actor.stats()}")


def test_decide_with_deterministic_overlay():
    """deterministic Jev → overlay positions + base = 5 + 2*N overlay legs."""
    spec = Spec.load(SPEC_PATH)
    panel = _make_panel()

    def fn(state, q_name, primitive):
        if primitive == "Choice":
            return {"choice": "long_BTC", "probabilities": {"long_BTC": 0.9},
                    "confidence": 0.9}
        elif primitive == "Score":
            return {"score": 0.7, "legend": {}, "probabilities": {}}
        else:
            return {"noul": 0.9}

    backend = MockJevDecisionBackend(mode="deterministic", fn=fn)
    actor = JevDecisionActor(backend=backend)
    as_of = dt.date(2026, 9, 21)
    decision = decide_panel_long_short_jev_overlay(
        spec, panel, as_of=as_of, regime=None,
        n_open=0, last_rebalance=None, jev_actor=actor,
    )
    assert decision.verdict == "ENTERED"
    # 5 base + N pair × 2 legs. The deterministic fn returns choice="long_BTC"
    # for EVERY pair, so:
    #   - pairs containing BTC (BTC-ETH, BTC-SOL, BTC-BNB, BTC-XRP = 4 pairs)
    #     → resolve to long BTC vs short <other>, pass all gates
    #   - pairs without BTC (ETH-SOL, ETH-BNB, ETH-XRP, SOL-BNB, SOL-XRP, BNB-XRP
    #     = 6 pairs) → abstain (chosen="long_BTC" matches neither symbol)
    # Total legs = 5 base + 4 pairs × 2 = 13.
    assert len(decision.legs) == 13
    # At least one short leg (overlay)
    assert any(leg.side == "short" for leg in decision.legs)
    print(f"✓ ENTERED with 13 legs (5 base + 4 BTC pairs × 2), "
          f"actor stats: {actor.stats()}")


def test_decide_fail_open_on_jev_error():
    """jev_decision.error → base still ENTERED, no overlay (fail-open default)."""
    spec = Spec.load(SPEC_PATH)
    panel = _make_panel()
    as_of = dt.date(2026, 9, 21)
    bad_decision = JevDecision(
        bar_ts="2026-09-21", answers={},
        jev_latency_ms=0, jev_input_tokens=0,
        backend_name="typesafe_jev_v1", mock=False,
        error="JEV_API_KEY not set in env",
    )
    decision = decide_panel_long_short_jev_overlay(
        spec, panel, as_of=as_of, regime=None,
        n_open=0, last_rebalance=None, jev_decision=bad_decision,
    )
    assert decision.verdict == "ENTERED"
    # Base 5 legs only (no overlay because assembler abstains on error)
    assert len(decision.legs) == 5
    assert "error=JEV_API_KEY" in decision.reason or "note:" in decision.reason
    print(f"✓ fail-open: error → base ENTERED, no overlay")


def test_decide_blocks_on_empty_panel():
    spec = Spec.load(SPEC_PATH)
    panel = Panel(closes={}, source="empty", last_bar=None, n_symbols=0)
    as_of = dt.date(2026, 9, 21)
    decision = decide_panel_long_short_jev_overlay(
        spec, panel, as_of=as_of, regime=None,
        n_open=0, last_rebalance=None,
        jev_decision=JevDecision(
            bar_ts="2026-09-21", answers={}, jev_latency_ms=0,
            jev_input_tokens=0, backend_name="mock", mock=True,
        ),
    )
    assert decision.verdict == "BLOCKED"
    assert "0 个标的" in decision.reason
    print("✓ empty panel → BLOCKED")


def test_decide_actor_stats_accumulate_across_calls():
    """3 decide() calls → actor.n_calls=3, n_questions_per_call=30."""
    spec = Spec.load(SPEC_PATH)
    panel = _make_panel()
    backend = MockJevDecisionBackend(mode="always_no_edge")
    actor = JevDecisionActor(backend=backend)
    as_of = dt.date(2026, 9, 21)
    for _ in range(3):
        decide_panel_long_short_jev_overlay(
            spec, panel, as_of=as_of, regime=None,
            n_open=0, last_rebalance=None, jev_actor=actor,
        )
    s = actor.stats()
    assert s["n_calls"] == 3
    assert s["n_questions_per_call"] == 30.0
    print(f"✓ 3 calls × 30 questions = {s}")
