"""Smoke test for `paper_trading.pair_decision_assembler` — S-397 §5b ④ L/S overlay.

The assembler takes a `JevDecision` (multi-primitive batch output) and
assembles it into a list of L/S `PairPosition`s, applying coverage / score /
thesis gates. This module owns the post-processing logic — the spec_runner
integration is tested in `test_run_paper_a17_smoke.py` / new family-specific
test.

What we test:
  1. `PairPosition` is a frozen dataclass
  2. Coverage gate: confidence < threshold → abstain
  3. Coverage gate: choice == no_edge → abstain
  4. Score gate: |score| < threshold → abstain
  5. Thesis gate: noul < threshold → abstain
  6. Direction resolution: long_a → sym_a is long, sym_b is short
  7. Direction resolution: long_b → sym_b is long, sym_a is short
  8. Sizing: weight = clip(score, -max, +max)
  9. Fail-open on jev_decision.error
 10. `net_exposure` sums to ~0 for symmetric L/S book
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paper_trading.jev_decision import JevDecision, JevQuestion   # noqa: E402
from paper_trading.pair_decision_assembler import (   # noqa: E402
    AssembleResult, PairPosition,
    assemble_pair_positions, net_exposure, _parse_pair_question_name,
)


UNIVERSE_5 = ["BTC", "ETH", "SOL", "BNB", "XRP"]


def _make_decision(
    *, per_pair_answers: dict[str, dict],
    error: str = None,
    n_questions: int = 30,
) -> JevDecision:
    """Build a JevDecision with the standard 30-question shape, customizing
    per-pair answers via `per_pair_answers` keyed by pair tuple `(a, b)`."""
    answers: dict[str, dict] = {}
    from itertools import combinations
    for i, (a, b) in enumerate(combinations(UNIVERSE_5, 2)):
        prefix = f"pair_{i:02d}_{a}_{b}"
        override = per_pair_answers.get((a, b), {})
        answers[f"{prefix}_direction"] = override.get(
            "direction",
            {"choice": "no_edge", "probabilities": {"no_edge": 1.0}, "confidence": 0.0},
        )
        answers[f"{prefix}_conviction"] = override.get(
            "conviction", {"score": 0.0, "legend": {}, "probabilities": {}},
        )
        answers[f"{prefix}_thesis_valid"] = override.get(
            "thesis_valid", {"noul": 0.5},
        )
    return JevDecision(
        bar_ts="2026-09-21",
        answers=answers,
        jev_latency_ms=150.0,
        jev_input_tokens=5000,
        backend_name="test_backend",
        mock=True,
        error=error,
    )


# ── Output type ────────────────────────────────────────────────────────────


def test_pair_position_is_frozen():
    p = PairPosition(
        pair_id="BTC_ETH", sym_long="BTC", sym_short="ETH",
        weight=0.05, score=0.5, confidence=0.7, thesis_noul=0.85,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.weight = 0.10  # type: ignore[misc]
    print("✓ PairPosition frozen")


# ── Question-name parsing ──────────────────────────────────────────────────


def test_parse_pair_question_name():
    assert _parse_pair_question_name("pair_03_BTC_ETH_direction") == ("BTC", "ETH", "direction")
    assert _parse_pair_question_name("pair_07_SOL_BNB_conviction") == ("SOL", "BNB", "conviction")
    assert _parse_pair_question_name("pair_00_BTC_ETH_thesis_valid") == ("BTC", "ETH", "thesis_valid")
    assert _parse_pair_question_name("not_a_pair_question") is None
    print("✓ question name parsing")


# ── Coverage / score / thesis gates ────────────────────────────────────────


def test_coverage_gate_low_confidence_abstains():
    """confidence < threshold → abstain (selective classification)."""
    decision = _make_decision(per_pair_answers={
        ("BTC", "ETH"): {
            "direction": {"choice": "long_BTC",
                          "probabilities": {"long_BTC": 0.6, "no_edge": 0.4},
                          "confidence": 0.4},  # < 0.55 default
            "conviction": {"score": 0.8, "legend": {}, "probabilities": {}},
            "thesis_valid": {"noul": 0.9},
        },
    })
    result = assemble_pair_positions(decision, universe=UNIVERSE_5)
    # BTC/ETH should be abstained (low confidence)
    assert all(p.pair_id != "BTC_ETH" for p in result.positions)
    assert result.n_pairs_abstained == 10
    assert result.coverage == 0.0
    print("✓ coverage gate: low confidence → abstain")


def test_coverage_gate_no_edge_abstains():
    decision = _make_decision(per_pair_answers={
        ("BTC", "ETH"): {
            "direction": {"choice": "no_edge",
                          "probabilities": {"no_edge": 1.0},
                          "confidence": 0.9},
            "conviction": {"score": 0.8, "legend": {}, "probabilities": {}},
            "thesis_valid": {"noul": 0.9},
        },
    })
    result = assemble_pair_positions(decision, universe=UNIVERSE_5)
    assert all(p.pair_id != "BTC_ETH" for p in result.positions)
    print("✓ no_edge choice → abstain")


def test_score_gate_low_conviction_abstains():
    decision = _make_decision(per_pair_answers={
        ("BTC", "ETH"): {
            "direction": {"choice": "long_BTC",
                          "probabilities": {"long_BTC": 0.8, "no_edge": 0.2},
                          "confidence": 0.8},
            "conviction": {"score": 0.1, "legend": {}, "probabilities": {}},  # < 0.15 default
            "thesis_valid": {"noul": 0.9},
        },
    })
    result = assemble_pair_positions(decision, universe=UNIVERSE_5)
    assert all(p.pair_id != "BTC_ETH" for p in result.positions)
    print("✓ score gate: |score| < threshold → abstain")


def test_thesis_gate_broken_thesis_abstains():
    decision = _make_decision(per_pair_answers={
        ("BTC", "ETH"): {
            "direction": {"choice": "long_BTC",
                          "probabilities": {"long_BTC": 0.8, "no_edge": 0.2},
                          "confidence": 0.8},
            "conviction": {"score": 0.8, "legend": {}, "probabilities": {}},
            "thesis_valid": {"noul": 0.4},  # < 0.55 default
        },
    })
    result = assemble_pair_positions(decision, universe=UNIVERSE_5)
    assert all(p.pair_id != "BTC_ETH" for p in result.positions)
    print("✓ thesis gate: broken thesis → abstain")


# ── Direction resolution + sizing ──────────────────────────────────────────


def test_long_a_resolution():
    decision = _make_decision(per_pair_answers={
        ("BTC", "ETH"): {
            "direction": {"choice": "long_BTC",
                          "probabilities": {"long_BTC": 0.85, "no_edge": 0.15},
                          "confidence": 0.85},
            "conviction": {"score": 0.05, "legend": {}, "probabilities": {}},  # under max
            "thesis_valid": {"noul": 0.9},
        },
    })
    result = assemble_pair_positions(decision, universe=UNIVERSE_5,
                                      score_threshold=0.04)  # 0.04 < 0.05 score
    btc_eth_pos = next((p for p in result.positions if p.pair_id == "BTC_ETH"), None)
    assert btc_eth_pos is not None
    assert btc_eth_pos.sym_long == "BTC"
    assert btc_eth_pos.sym_short == "ETH"
    assert btc_eth_pos.weight == pytest.approx(0.05, abs=1e-6)  # clip(0.05, -0.10, 0.10) = 0.05
    print("✓ long_BTC → BTC long / ETH short / weight=0.05 (unclipped)")


def test_long_b_resolution():
    decision = _make_decision(per_pair_answers={
        ("BTC", "ETH"): {
            "direction": {"choice": "long_ETH",
                          "probabilities": {"long_ETH": 0.85, "no_edge": 0.15},
                          "confidence": 0.85},
            "conviction": {"score": 0.7, "legend": {}, "probabilities": {}},
            "thesis_valid": {"noul": 0.9},
        },
    })
    result = assemble_pair_positions(decision, universe=UNIVERSE_5)
    btc_eth_pos = next((p for p in result.positions if p.pair_id == "BTC_ETH"), None)
    assert btc_eth_pos.sym_long == "ETH"
    assert btc_eth_pos.sym_short == "BTC"
    print("✓ long_ETH → ETH long / BTC short")


def test_sizing_clipped_to_max_pair_weight():
    """Score 0.95 with max_pair_weight=0.10 → weight=0.10 (clipped)."""
    decision = _make_decision(per_pair_answers={
        ("BTC", "ETH"): {
            "direction": {"choice": "long_BTC",
                          "probabilities": {"long_BTC": 0.85, "no_edge": 0.15},
                          "confidence": 0.85},
            "conviction": {"score": 0.95, "legend": {}, "probabilities": {}},
            "thesis_valid": {"noul": 0.9},
        },
    })
    result = assemble_pair_positions(decision, universe=UNIVERSE_5,
                                      max_pair_weight=0.10)
    btc_eth_pos = next(p for p in result.positions if p.pair_id == "BTC_ETH")
    assert btc_eth_pos.weight == pytest.approx(0.10, abs=1e-6)
    print("✓ weight clipped to max_pair_weight")


def test_fail_open_on_error():
    """jev_decision.error → all pairs abstained (no signal, base still runs)."""
    decision = _make_decision(per_pair_answers={}, error="JEV_API_KEY not set in env")
    result = assemble_pair_positions(decision, universe=UNIVERSE_5)
    assert result.error and "JEV_API_KEY" in result.error
    assert result.positions == ()
    assert result.coverage == 0.0
    assert result.n_pairs_abstained == 10
    print("✓ fail-open: error → all abstained")


# ── Net exposure ───────────────────────────────────────────────────────────


def test_net_exposure_symmetric_book():
    """Symmetric L/S book → per-symbol net ≈ 0."""
    positions = [
        PairPosition(pair_id="BTC_ETH", sym_long="BTC", sym_short="ETH",
                     weight=0.05, score=0.5, confidence=0.7, thesis_noul=0.85),
        PairPosition(pair_id="BTC_SOL", sym_long="BTC", sym_short="SOL",
                     weight=0.05, score=0.5, confidence=0.7, thesis_noul=0.85),
        PairPosition(pair_id="ETH_SOL", sym_long="ETH", sym_short="SOL",
                     weight=0.05, score=0.5, confidence=0.7, thesis_noul=0.85),
    ]
    exposure = net_exposure(positions)
    # BTC: +0.05 + 0.05 = 0.10
    # ETH: -0.05 + 0.05 = 0.00
    # SOL: -0.05 - 0.05 = -0.10
    assert exposure["BTC"] == pytest.approx(0.10, abs=1e-6)
    assert exposure["ETH"] == pytest.approx(0.00, abs=1e-6)
    assert exposure["SOL"] == pytest.approx(-0.10, abs=1e-6)
    print(f"✓ net exposure {exposure}")
