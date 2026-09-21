"""Smoke test for `paper_trading.jev_regime` — Pattern A pre-filter module.

Per `docs/jev_nautilus_integration_plan_2026-09-21.md`: Jev says yes/no to
"is this regime tradeable?" BEFORE the strategy fires. This module owns
the Jev gate (dataclass + pluggable backend + actor). The spec_runner
integration is tested in `test_run_paper_a17_smoke.py`.

What we test (each = one realistic failure mode):
  1. `JevRegimeDecision` is a frozen dataclass — no late mutation of a logged decision
  2. `MockJevRegimeBackend(mode="always_ok")` is the safe default — never vetoes
  3. `MockJevRegimeBackend(mode="always_veto")` vetoes unconditionally — the
     veto path is wired and reachable (a missing veto would silently let
     bad regimes through)
  4. `MockJevRegimeBackend(mode="deterministic", fn=...)` lets 60d validation
     replay a known function over historical state payloads (Gate 1 Brier)
  5. `JevRegimeActor.stats()` correctly tracks call count + cumulative latency
     + cumulative input tokens — these feed Gate 3 (frequency) + Gate 4 (cost)
  6. `build_state_payload` requires `bar_ts` — without it, downstream logging
     can't correlate decisions to bars
  7. Validation: bogus mode name raises ValueError (no silent fallthrough)
  8. Validation: `mode="deterministic"` without `fn=` raises ValueError

The TypeSafe backend itself is NOT tested here — it requires JEV_API_KEY and
a network call. Future TypesafeBackend tests live in a sibling file gated by
the env var.

These run without env vars; mock backend only. Real-Jev integration is
BLOCKED on the API key arriving in Seth lane.
"""
from __future__ import annotations

import dataclasses

import pytest

from paper_trading.jev_regime import (
    JevRegimeActor,
    JevRegimeBackend,
    JevRegimeDecision,
    MockJevRegimeBackend,
    build_state_payload,
)


def _state(bar_ts: str = "2026-09-21", **overrides):
    """Convenience builder for state payloads in tests."""
    base = dict(
        bar_ts=bar_ts, regime="EASING",
        panel_age_days=1, panel_n_symbols=24,
        vol_20d=0.42, breadth_200ma=0.65,
    )
    base.update(overrides)
    return build_state_payload(**base)


# ── Output type ────────────────────────────────────────────────────────────


def test_decision_is_frozen_dataclass():
    """JevRegimeDecision MUST be frozen — a logged decision must not mutate after write."""
    d = JevRegimeDecision(
        bar_ts="2026-09-21", regime_ok=True,
        direction_bias="neutral", confidence="med",
        jev_latency_ms=150.0, jev_input_tokens=1250,
        backend_name="mock_jev_regime", mock=True,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.regime_ok = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.backend_name = "compromised"  # type: ignore[misc]
    print("✓ frozen guards both fields")


def test_decision_carries_all_required_fields():
    """All fields present + non-None where required, so log JSONL shape is stable."""
    d = JevRegimeDecision(
        bar_ts="2026-09-21", regime_ok=False,
        direction_bias="short", confidence="high",
        jev_latency_ms=180.0, jev_input_tokens=3000,
        backend_name="typesafe_jev_v1", mock=False,
        raw={"error": "rate_limited"},
    )
    assert d.bar_ts == "2026-09-21"
    assert d.direction_bias == "short"
    assert d.confidence == "high"
    assert d.raw == {"error": "rate_limited"}
    print("✓ raw field carries structured error context")


# ── Mock backend modes ─────────────────────────────────────────────────────


def test_mock_backend_always_ok_default():
    """Default mode='always_ok' must be the safe no-op default — never vetoes."""
    b = MockJevRegimeBackend()  # default mode
    assert b.name == "mock_jev_regime"
    for _ in range(100):
        d = b.evaluate(_state())
        assert d.regime_ok is True, "always_ok mode must never veto"
        assert d.mock is True
        assert d.backend_name == "mock_jev_regime"
    print("✓ 100 calls in always_ok mode all returned regime_ok=True")


def test_mock_backend_always_veto():
    """always_veto mode MUST veto — missing veto path = silent bypass."""
    b = MockJevRegimeBackend(mode="always_veto")
    for _ in range(50):
        d = b.evaluate(_state())
        assert d.regime_ok is False, "always_veto mode must always veto"
    print("✓ 50 calls in always_veto mode all returned regime_ok=False")


def test_mock_backend_deterministic():
    """deterministic mode = user-supplied fn(state) -> bool. Used for 60d Gate 1 Brier."""
    # Replay a known function: veto whenever regime is RISK_OFF
    fn = lambda s: s.get("regime") != "RISK_OFF"
    b = MockJevRegimeBackend(mode="deterministic", fn=fn)
    for regime in ("EASING", "RISK_OFF", "TIGHTENING", "RISK_OFF", "STAGFLATION"):
        d = b.evaluate(_state(regime=regime))
        expected_ok = regime != "RISK_OFF"
        assert d.regime_ok is expected_ok, (
            f"deterministic mode fn(state) failed: regime={regime} "
            f"expected regime_ok={expected_ok}, got {d.regime_ok}"
        )
    print("✓ deterministic mode honors fn(state) per-call")


# ── Backend validation ─────────────────────────────────────────────────────


def test_bogus_mode_rejected():
    """An unknown mode name MUST raise ValueError — silent fallthrough would
    silently bypass the gate (a defect class we already paid for)."""
    with pytest.raises(ValueError, match="mode='bogus' unknown"):
        MockJevRegimeBackend(mode="bogus")
    print("✓ bogus mode rejected at construction")


def test_deterministic_without_fn_rejected():
    """mode='deterministic' without fn= is a misconfiguration that must surface now."""
    with pytest.raises(ValueError, match="mode='deterministic' requires `fn`"):
        MockJevRegimeBackend(mode="deterministic")
    print("✓ deterministic w/o fn rejected at construction")


def test_bogus_direction_bias_rejected():
    """direction_bias is part of the Jev Choice schema — invalid values break downstream parsers."""
    with pytest.raises(ValueError, match="direction_bias='sideways' not in"):
        MockJevRegimeBackend(direction_bias="sideways")
    print("✓ bogus direction_bias rejected")


def test_bogus_confidence_rejected():
    """confidence is part of the Jev Score schema — same constraint."""
    with pytest.raises(ValueError, match="confidence='maybe' not in"):
        MockJevRegimeBackend(confidence="maybe")
    print("✓ bogus confidence rejected")


def test_evaluate_requires_bar_ts():
    """state_payload 必须带 bar_ts — 没有它,决策无法对应到具体 bar/log 行。"""
    b = MockJevRegimeBackend()
    with pytest.raises(ValueError, match="bar_ts"):
        b.evaluate({"regime": "EASING", "panel_n_symbols": 24})
    print("✓ bar_ts absence raises")


# ── Actor stats ────────────────────────────────────────────────────────────


def test_actor_stats_track_calls_and_latency_and_tokens():
    """JevRegimeActor.stats() feeds Gate 3 (frequency) + Gate 4 (cost realism)."""
    b = MockJevRegimeBackend(mode="always_ok", fake_latency_ms=200.0, fake_input_tokens=800)
    actor = JevRegimeActor(backend=b, name="test_actor")
    for _ in range(7):
        actor.decide(_state())
    s = actor.stats()
    assert s["n_calls"] == 7
    assert s["cum_latency_ms"] == 1400.0
    assert s["avg_latency_ms"] == 200.0
    assert s["cum_input_tokens"] == 5600
    assert s["backend"] == "mock_jev_regime"
    assert s["name"] == "test_actor"
    print(f"✓ actor stats after 7 calls: {s}")


def test_actor_call_alias_works():
    """actor(state) is sugar for actor.decide(state) — both produce identical decisions."""
    actor = JevRegimeActor(backend=MockJevRegimeBackend())
    d1 = actor.decide(_state())
    d2 = actor(_state())
    # Same shape, possibly same content if backend is deterministic.
    assert isinstance(d2, JevRegimeDecision)
    assert d2.regime_ok == d1.regime_ok
    print("✓ actor.__call__ sugar works")


def test_actor_separate_instances_have_separate_stats():
    """Stats are per-instance — a leaked actor shouldn't pollute another's counters."""
    a = JevRegimeActor(backend=MockJevRegimeBackend())
    b = JevRegimeActor(backend=MockJevRegimeBackend())
    for _ in range(3):
        a(_state())
    for _ in range(5):
        b(_state())
    assert a.stats()["n_calls"] == 3
    assert b.stats()["n_calls"] == 5
    print("✓ per-actor stats isolated")


# ── build_state_payload ────────────────────────────────────────────────────


def test_build_state_payload_minimal():
    """Required fields only — extras optional."""
    p = build_state_payload(
        bar_ts="2026-09-21", regime=None,
        panel_age_days=1, panel_n_symbols=24,
    )
    assert p["bar_ts"] == "2026-09-21"
    assert p["regime"] is None
    assert p["panel_age_days"] == 1
    assert p["panel_n_symbols"] == 24
    assert p["vol_20d"] is None  # default
    assert p["breadth_200ma"] is None  # default
    assert "extra" not in p  # default no extras
    print("✓ minimal state payload has all canonical keys")


def test_build_state_payload_with_extras():
    """Extra fields go under 'extra' namespace to avoid colliding with canonical keys."""
    p = build_state_payload(
        bar_ts="2026-09-21", regime="EASING",
        panel_age_days=1, panel_n_symbols=24,
        extra={"btc_dominance_30d": 0.62, "fear_greed_index": 47},
    )
    assert p["extra"] == {"btc_dominance_30d": 0.62, "fear_greed_index": 47}
    # Canonical keys are NOT polluted by extras.
    assert "btc_dominance_30d" not in p
    print("✓ extras namespaced under 'extra'")


# ── Protocol conformance (compile-time + runtime check) ────────────────────


def test_mock_backend_satisfies_protocol():
    """MockJevRegimeBackend must satisfy JevRegimeBackend Protocol shape."""
    # Protocol check via isinstance (runtime_checkable required for this).
    # We use Protocol for type hints only; runtime check is best-effort.
    b = MockJevRegimeBackend()
    assert hasattr(b, "name") and isinstance(b.name, str)
    assert hasattr(b, "evaluate") and callable(b.evaluate)
    # Verify the actual call works
    d = b.evaluate(_state())
    assert isinstance(d, JevRegimeDecision)
    print(f"✓ MockJevRegimeBackend conforms to JevRegimeBackend contract (name={b.name})")
