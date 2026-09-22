"""Smoke test for `paper_trading.jev_decision` — S-397 §5b ④ L/S overlay kernel.

Per `s397-jev-ls-overlay-redesign-2026-09-21.md` (JAZZ-pivoted 2026-09-21):
Jev is NOT a regime filter (that's `jev_regime.py`). Jev IS a multi-primitive
decision kernel that returns Choice + Score + Noul in parallel for bound
answer spaces. This module owns the L/S kernel — the spec_runner integration
is tested in `test_run_paper_a17_smoke.py` and a new family-specific test.

What we test (each = one realistic failure mode):
  1. `JevDecision` is a frozen dataclass — no late mutation
  2. `MockJevDecisionBackend(mode="always_no_edge")` is the safe default —
     no L/S signal (baseline-of-wire-path, mirrors S-396 always_ok)
  3. `MockJevDecisionBackend(mode="deterministic", fn=...)` lets 60d validation
     replay a known function over historical state payloads (Gate 1 Brier / ECE)
  4. `JevDecisionActor.stats()` correctly tracks call count + cumulative latency
     + cumulative input tokens + n_questions_per_call
  5. `build_ls_questions(universe)` for 5 symbols = 30 questions (10 pairs × 3)
     — cardinality budget for 5-symbol panel
  6. `TypesafeJevDecisionBackend` fail-opens on missing JEV_API_KEY (no key →
     all-no_edge + error marker, not crash)
  7. `TypesafeJevDecisionBackend` fail-opens on HTTP error (mock transport)
  8. `TypesafeJevDecisionBackend` parses a valid response correctly
  9. `build_ls_state_payload` requires bar_ts (correlate to bar)
 10. Validation: bogus mode name raises ValueError
 11. Validation: `mode="deterministic"` without `fn=` raises ValueError
 12. Cardinality: 5-symbol universe = 35 fields in state (well under 255)

The Typesafe real API is NOT tested here directly — it requires JEV_API_KEY +
a network call. We use httpx MockTransport to simulate HTTP responses. Live
integration is BLOCKED on JEV_API_KEY (Seth lane env var, A lane Mac-side inject).
"""
from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_trading.jev_decision import (   # noqa: E402
    JevDecision, JevDecisionActor,
    JevQuestion, MockJevDecisionBackend, TypesafeJevDecisionBackend,
    build_ls_questions, build_ls_state_payload,
)
from paper_trading.ls_state_builder import build_ls_context, count_fields   # noqa: E402


UNIVERSE_5 = ["BTC", "ETH", "SOL", "BNB", "XRP"]


def _state(bar_ts: str = "2026-09-21", **overrides):
    """Convenience state builder (uses ls_state_builder)."""
    base = dict(
        bar_ts=bar_ts, universe=UNIVERSE_5,
        closes_by_sym={
            s: {f"2026-{m:02d}-{d:02d}": 100.0 + (m * 30) + d
                for m in range(1, 9) for d in range(1, 29)}
            for s in UNIVERSE_5
        },
        panel_age_days=1, cadence_days=7, cost_bps_rt=10.0,
        regime="EASING", btc_dominance=0.55,
    )
    base.update(overrides)
    return build_ls_context(**base)


# ── Output type ────────────────────────────────────────────────────────────


def test_decision_is_frozen_dataclass():
    """JevDecision MUST be frozen — a logged batch must not mutate after write."""
    d = JevDecision(
        bar_ts="2026-09-21", answers={"q1": {"noul": 0.5}},
        jev_latency_ms=150.0, jev_input_tokens=5000,
        backend_name="mock_jev_decision", mock=True,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.jev_latency_ms = 0.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.backend_name = "compromised"  # type: ignore[misc]
    print("✓ frozen guards both fields")


def test_decision_carries_all_required_fields():
    """All fields present + non-None where required."""
    d = JevDecision(
        bar_ts="2026-09-21", answers={"pair_00_BTC_ETH_direction":
                                      {"choice": "long_BTC", "probabilities":
                                       {"long_BTC": 0.7, "long_ETH": 0.2,
                                        "no_edge": 0.1}, "confidence": 0.7}},
        jev_latency_ms=180.0, jev_input_tokens=8000,
        backend_name="typesafe_jev_v1", mock=False,
    )
    assert d.bar_ts == "2026-09-21"
    assert "pair_00_BTC_ETH_direction" in d.answers
    assert d.answers["pair_00_BTC_ETH_direction"]["choice"] == "long_BTC"
    assert d.mock is False
    assert d.error is None
    print("✓ all required fields present")


# ── Mock backend ───────────────────────────────────────────────────────────


def test_mock_always_no_edge_is_safe_default():
    """always_no_edge mode = baseline of wire path. No L/S signal but wire 走."""
    backend = MockJevDecisionBackend(mode="always_no_edge")
    state = _state()
    questions = build_ls_questions(UNIVERSE_5)
    d = backend.evaluate_batch(state, questions)
    assert len(d.answers) == 30  # 10 pairs × 3 primitives
    # Every Choice answer is no_edge variant
    for name, ans in d.answers.items():
        if "_direction" in name:
            assert "no_edge" in ans["choice"]
            assert ans["confidence"] == 0.0
        elif "_conviction" in name:
            assert ans["score"] == 0.0
        elif "_thesis_valid" in name:
            assert ans["noul"] == 0.5
    print("✓ 30 answers, all no_edge / 0.0 / 0.5")


def test_mock_deterministic_with_fn():
    """deterministic mode lets 60d validation replay a known function."""
    def fn(state, q_name, primitive):
        if primitive == "Choice":
            return {"choice": "long_BTC", "probabilities": {"long_BTC": 0.9},
                    "confidence": 0.9}
        elif primitive == "Score":
            return {"score": 0.8, "legend": {}, "probabilities": {}}
        else:  # Noul
            return {"noul": 0.9}
    backend = MockJevDecisionBackend(mode="deterministic", fn=fn)
    state = _state()
    questions = build_ls_questions(UNIVERSE_5)
    d = backend.evaluate_batch(state, questions)
    # First pair's direction should be long_BTC
    first_dir = next(k for k in d.answers if k.endswith("_direction"))
    assert d.answers[first_dir]["choice"] == "long_BTC"
    print("✓ deterministic fn drives every answer")


def test_mock_validation_bogus_mode_raises():
    with pytest.raises(ValueError, match="unknown"):
        MockJevDecisionBackend(mode="bogus_mode")
    print("✓ bogus mode raises")


def test_mock_validation_deterministic_without_fn_raises():
    with pytest.raises(ValueError, match="requires `fn`"):
        MockJevDecisionBackend(mode="deterministic")
    print("✓ deterministic without fn raises")


def test_mock_requires_bar_ts():
    backend = MockJevDecisionBackend(mode="always_no_edge")
    bad_state = {"universe": UNIVERSE_5, "per_symbol": {}, "cross_asset": {}}
    with pytest.raises(ValueError, match="bar_ts"):
        backend.evaluate_batch(bad_state, build_ls_questions(UNIVERSE_5))
    print("✓ bar_ts required")


# ── Actor stats ────────────────────────────────────────────────────────────


def test_actor_stats_accumulate():
    """n_calls + cum_latency + cum_input_tokens + cum_n_questions all 累加."""
    backend = MockJevDecisionBackend(mode="always_no_edge",
                                     fake_latency_ms=100.0,
                                     fake_input_tokens=3000)
    actor = JevDecisionActor(backend=backend)
    state = _state()
    questions = build_ls_questions(UNIVERSE_5)
    for _ in range(3):
        actor.decide_batch(state, questions)
    s = actor.stats()
    assert s["n_calls"] == 3
    assert s["cum_latency_ms"] == 300.0
    assert s["cum_input_tokens"] == 9000
    assert s["n_questions_per_call"] == 30.0  # 30 questions per call × 3 calls / 3
    print(f"✓ actor stats: {s}")


# ── Question builder ───────────────────────────────────────────────────────


def test_build_ls_questions_5_symbols_30_questions():
    """5 symbols → C(5,2)=10 pairs × 3 prims = 30 questions."""
    qs = build_ls_questions(UNIVERSE_5)
    assert len(qs) == 30
    # Each question has valid name / primitive / instructions / criteria
    prim_counts = {"Choice": 0, "Score": 0, "Noul": 0}
    for q in qs:
        assert q.name
        assert q.primitive in ("Choice", "Score", "Noul")
        prim_counts[q.primitive] += 1
        if q.primitive == "Choice":
            assert isinstance(q.criteria, dict)
            assert "no_edge" in str(q.criteria)
        elif q.primitive == "Score":
            assert isinstance(q.criteria, list)
        else:  # Noul
            assert q.criteria is None
    assert prim_counts == {"Choice": 10, "Score": 10, "Noul": 10}
    print(f"✓ 30 questions = 10 Choice + 10 Score + 10 Noul")


def test_build_ls_questions_too_few_symbols_raises():
    with pytest.raises(ValueError, match="≥ 2 symbols"):
        build_ls_questions(["BTC"])
    print("✓ < 2 symbols raises")


# ── State payload + cardinality ───────────────────────────────────────────


def test_build_ls_state_payload_shape():
    payload = build_ls_state_payload(
        bar_ts="2026-09-21", universe=UNIVERSE_5,
        per_symbol_features={s: {"mom_60": 0.1, "vol_30": 0.5} for s in UNIVERSE_5},
        cross_asset_features={"regime": "EASING", "btc_dominance": 0.55},
    )
    assert payload["bar_ts"] == "2026-09-21"
    assert payload["universe"] == UNIVERSE_5
    assert "per_symbol" in payload
    assert "cross_asset" in payload
    print("✓ state payload shape correct")


def test_cardinality_5_symbols_under_cap():
    """5-symbol universe = ~35 fields total (well under 255 cap)."""
    payload = build_ls_state_payload(
        bar_ts="2026-09-21", universe=UNIVERSE_5,
        per_symbol_features={s: {"mom_30": 0.1, "mom_60": 0.1, "vol_30": 0.5,
                                 "breadth_pos": 0.0, "cs_score": 0.5}
                              for s in UNIVERSE_5},
        cross_asset_features={"regime": "EASING", "btc_dominance": 0.55,
                              "funding_rate_btc": 0.01, "breadth_200ma": 0.6,
                              "cross_skew": 0.0, "panel_age_days": 1,
                              "panel_n_symbols": 5, "vol_20d_panel": 0.5,
                              "cadence_days": 7, "cost_bps_rt": 10.0},
    )
    n_fields = count_fields(payload)
    assert n_fields == 35, f"expected 35 fields, got {n_fields}"
    assert n_fields < 255, "cardinality cap respected"
    print(f"✓ 5-symbol state = {n_fields} fields (cap 255)")


# ── Typesafe real backend (mocked transport) ───────────────────────────────


def test_typesafe_fail_open_no_key(monkeypatch):
    """No JEV_API_KEY → fail-open with error marker (not crash)."""
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    backend = TypesafeJevDecisionBackend()
    state = _state()
    questions = build_ls_questions(UNIVERSE_5)
    d = backend.evaluate_batch(state, questions)
    assert d.mock is False
    assert d.error and "JEV_API_KEY not set" in d.error
    # All answers are safe defaults (no_edge / 0 / 0.5)
    for name, ans in d.answers.items():
        if "_direction" in name:
            assert "no_edge" in ans["choice"]
        elif "_conviction" in name:
            assert ans["score"] == 0.0
        else:
            assert ans["noul"] == 0.5
    print("✓ no key → fail-open with safe defaults")


def test_typesafe_fail_open_http_error():
    """HTTP 500 → fail-open with error marker, latency tracked."""
    import httpx

    backend = TypesafeJevDecisionBackend(api_key="dummy_key_for_unit_test")
    state = _state()
    questions = build_ls_questions(UNIVERSE_5)

    # Monkey-patch _request to simulate 500
    orig_request = backend._request
    backend._request = lambda key, body: (   # noqa: ARG005
        httpx.Response(500, text="upstream error").raise_for_status()
    )
    try:
        d = backend.evaluate_batch(state, questions)
        assert d.mock is False
        assert d.error, "error should be set on HTTP failure"
        # Latency should still be tracked even on error
        assert d.jev_latency_ms >= 0
        print(f"✓ HTTP 500 → fail-open (error={d.error[:60]}, latency={d.jev_latency_ms}ms)")
    finally:
        backend._request = orig_request


def test_typesafe_parses_valid_response():
    """Valid response shape is parsed into Choice/Score/Noul answers."""
    backend = TypesafeJevDecisionBackend(api_key="test_key_dummy_for_unit_test")
    state = _state()
    questions = build_ls_questions(UNIVERSE_5)

    # Build a valid response with ALL 30 answers (one per question)
    from itertools import combinations
    valid_response_answers: dict[str, dict] = {}
    for i, (a, b) in enumerate(combinations(UNIVERSE_5, 2)):
        prefix = f"pair_{i:02d}_{a}_{b}"
        valid_response_answers[f"{prefix}_direction"] = {
            "choice": "no_edge", "probabilities": {"no_edge": 1.0},
            "confidence": 0.0,
        }
        valid_response_answers[f"{prefix}_conviction"] = {
            "score": 0.0, "legend": {}, "probabilities": {},
        }
        valid_response_answers[f"{prefix}_thesis_valid"] = {"noul": 0.5}
    # Override first pair with a real long signal
    valid_response_answers["pair_00_BTC_ETH_direction"] = {
        "choice": "long_BTC",
        "probabilities": {"long_BTC": 0.8, "long_ETH": 0.1, "no_edge": 0.1},
        "confidence": 0.8,
    }
    valid_response_answers["pair_00_BTC_ETH_conviction"] = {
        "score": 0.7, "legend": {}, "probabilities": {},
    }
    valid_response_answers["pair_00_BTC_ETH_thesis_valid"] = {"noul": 0.85}

    valid_response = {
        "answers": valid_response_answers,
        "usage": {"input_tokens": 4500},
    }
    backend._request = lambda key, body: valid_response   # noqa: ARG005
    d = backend.evaluate_batch(state, questions)
    assert d.mock is False
    assert d.error is None, f"unexpected error: {d.error}"
    assert d.jev_input_tokens == 4500
    # Spot-check first pair's Choice answer
    assert d.answers["pair_00_BTC_ETH_direction"]["choice"] == "long_BTC"
    assert d.answers["pair_00_BTC_ETH_thesis_valid"]["noul"] == 0.85
    # All 30 answers present
    assert len(d.answers) == 30
    print(f"✓ valid response parsed correctly (tokens={d.jev_input_tokens}, "
          f"30 answers present)")


def test_typesafe_response_schema_mismatch_raises():
    """Missing 'choice' key in Choice answer → ValueError → fail-open."""
    backend = TypesafeJevDecisionBackend(api_key="test_key_dummy")
    state = _state()
    questions = build_ls_questions(UNIVERSE_5)

    bad_response = {
        "answers": {
            "pair_00_BTC_ETH_direction": {"wrong_key": "long_BTC"},  # no 'choice'
            "pair_00_BTC_ETH_conviction": {"score": 0.7, "legend": {}},
            "pair_00_BTC_ETH_thesis_valid": {"noul": 0.85},
        },
        "usage": {"input_tokens": 4500},
    }
    backend._request = lambda key, body: bad_response   # noqa: ARG005
    d = backend.evaluate_batch(state, questions)
    assert d.error and "Choice" in d.error and "missing 'choice'" in d.error
    print(f"✓ schema mismatch → fail-open with parse error")
