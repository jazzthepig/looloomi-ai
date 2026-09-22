"""Pair decision assembler — S-397 §5b ④ L/S overlay post-processor.

Take a `JevDecision` (multi-primitive batch output) and assemble it into a
list of L/S positions, applying:

  1. **Coverage gate** — if `choice.confidence < coverage_threshold` or
     `|score| < score_threshold`, abstain from that pair (selective
     classification discipline, arXiv 2110.14914).
  2. **Thesis-valid gate** — if `noul < thesis_threshold`, the thesis is
     broken → exit (for held pairs) or skip (for new entries).
  3. **Net exposure** — keep book market-neutral (Σ weights ≈ 0) by construction
     so the L/S overlay sits cleanly on top of ①/②/③ base without doubling beta.
  4. **Per-pair max weight** — cap each pair at `max_pair_weight` to limit
     idiosyncratic concentration.

Output: `list[PairPosition]` where each position is `(sym_long, sym_short,
weight)` with weight ∈ [-max_pair_weight, +max_pair_weight] and Σ weights ≈ 0.

## Why a separate module

`spec_runner.py` owns the strategy decision contract (verdict / reason /
legs). This module owns the post-processing logic (how 30 Jev judgments →
N L/S positions). Keeping them separate means `spec_runner.py` doesn't grow
a stateful assembler it doesn't own — same discipline as `jev_regime.py`
being a separate actor module.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Optional, Sequence


# ── Output type ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PairPosition:
    """One L/S pair position. weight > 0 means long `sym_long` / short `sym_short`.

    `score` is the raw -1↔+1 Jev conviction (post-coverage gate, post-thesis
    filter). `confidence` is the Choice primitive's reported confidence.
    """

    pair_id: str               # e.g. "BTC_ETH"
    sym_long: str              # the leg to long
    sym_short: str             # the leg to short
    weight: float              # signed weight in [-max_pair_weight, +max_pair_weight]
    score: float               # Jev conviction Score primitive
    confidence: float          # Jev Choice primitive confidence
    thesis_noul: float         # Jev Noul primitive (thesis validity)


@dataclass(frozen=True)
class AssembleResult:
    """Result of assembling one JevDecision into L/S positions.

    `positions` is the list of `PairPosition` to take.
    `n_pairs_total` is how many pairs Jev was asked about (10 for 5 symbols).
    `n_pairs_abstained` is how many were filtered out by coverage/thesis gates.
    `coverage` = `len(positions) / n_pairs_total` (selective classification metric).
    """

    positions: tuple[PairPosition, ...]
    n_pairs_total: int
    n_pairs_abstained: int
    coverage: float
    error: Optional[str] = None  # set if assembly failed


# ── Question-name parsing ───────────────────────────────────────────────────


def _parse_pair_question_name(name: str) -> Optional[tuple[str, str, str]]:
    """Parse a Jev question name like `pair_03_BTC_ETH_direction` → ("BTC","ETH","direction").

    Returns None if the name doesn't match the L/S pair convention.
    `kind` can be 1 word (direction / conviction) or 2 words (thesis_valid).
    """
    parts = name.split("_")
    if len(parts) < 4 or parts[0] != "pair":
        return None
    # parts[1] is the index ("00", "01", ...), parts[2] and parts[3] are symbols,
    # parts[4:] is the primitive kind (1 or 2 words).
    sym_a = parts[2]
    sym_b = parts[3]
    kind = "_".join(parts[4:]) if len(parts) >= 5 else parts[-1]
    if sym_a and sym_b and kind in ("direction", "conviction", "thesis_valid"):
        return (sym_a, sym_b, kind)
    return None


def _pair_id(sym_a: str, sym_b: str) -> str:
    return f"{sym_a}_{sym_b}"


# ── Assembly ────────────────────────────────────────────────────────────────


def assemble_pair_positions(
    jev_decision: Any,  # JevDecision — duck-typed to avoid circular import
    *,
    universe: Sequence[str],
    coverage_threshold: float = 0.55,
    score_threshold: float = 0.15,
    thesis_threshold: float = 0.55,
    max_pair_weight: float = 0.10,
) -> AssembleResult:
    """Assemble one `JevDecision` into L/S positions.

    Coverage gate (selective classification):
      - For each pair, look at `_direction` (Choice) answer:
        * If `confidence < coverage_threshold` → abstain (no signal).
        * If `choice == no_edge` (or any key containing "no_edge") → abstain.
      - Look at `_conviction` (Score) answer:
        * If `|score| < score_threshold` → abstain (signal too weak).
      - Look at `_thesis_valid` (Noul) answer:
        * If `noul < thesis_threshold` → abstain (thesis broken).

    Sizing:
      - weight = clip(score, -max, +max) — Score primitive is the size input.
      - Net exposure: the long/short pairs naturally sum to ~0 if scores are
        symmetric; we don't force a neutralization step here. spec_runner
        applies §5b ④ beta-neutrality check at strategy level if needed.
    """
    if jev_decision.error:
        return AssembleResult(
            positions=(),
            n_pairs_total=len(list(combinations(universe, 2))),
            n_pairs_abstained=len(list(combinations(universe, 2))),
            coverage=0.0,
            error=f"jev_decision.error={jev_decision.error}",
        )

    answers = jev_decision.answers or {}
    pairs = list(combinations(universe, 2))
    positions: list[PairPosition] = []

    for sym_a, sym_b in pairs:
        pid = _pair_id(sym_a, sym_b)
        # Names follow build_ls_questions convention: pair_<idx>_<a>_<b>_<kind>
        # We match by suffix because the index can vary across runs.
        dir_key = next(
            (k for k in answers
             if k.endswith(f"_{sym_a}_{sym_b}_direction")),
            None,
        )
        conv_key = next(
            (k for k in answers
             if k.endswith(f"_{sym_a}_{sym_b}_conviction")),
            None,
        )
        thesis_key = next(
            (k for k in answers
             if k.endswith(f"_{sym_a}_{sym_b}_thesis_valid")),
            None,
        )
        if not (dir_key and conv_key and thesis_key):
            # Missing primitive for this pair — abstain (fail-safe).
            continue

        choice = answers[dir_key]
        score_ans = answers[conv_key]
        thesis = answers[thesis_key]

        # ── Coverage gate ──
        confidence = float(choice.get("confidence", 0.0) or 0.0)
        if confidence < coverage_threshold:
            continue

        chosen = str(choice.get("choice", "") or "")
        if "no_edge" in chosen.lower():
            continue

        # ── Score gate (signal strength) ──
        score = float(score_ans.get("score", 0.0) or 0.0)
        if abs(score) < score_threshold:
            continue

        # ── Thesis gate ──
        thesis_noul = float(thesis.get("noul", 0.5) or 0.5)
        if thesis_noul < thesis_threshold:
            continue

        # ── Resolve direction ──
        # Jev returns "long_<sym>" — the sym determines which leg is long.
        long_sym: Optional[str] = None
        short_sym: Optional[str] = None
        if chosen.startswith("long_") and chosen.endswith(f"_{sym_a}"):
            long_sym, short_sym = sym_a, sym_b
        elif chosen.startswith("long_") and chosen.endswith(f"_{sym_b}"):
            long_sym, short_sym = sym_b, sym_a
        else:
            # Unrecognized choice (e.g. "no_edge" with different casing) → abstain.
            continue

        # ── Size (clip to max_pair_weight) ──
        # Score primitive is -1↔+1; we treat +1 as max_pair_weight long, -1 as
        # max_pair_weight short. Sign of score aligns with sign of weight.
        weight = max(-max_pair_weight, min(max_pair_weight, score))

        positions.append(PairPosition(
            pair_id=pid,
            sym_long=long_sym,
            sym_short=short_sym,
            weight=round(weight, 6),
            score=round(score, 6),
            confidence=round(confidence, 6),
            thesis_noul=round(thesis_noul, 6),
        ))

    n_total = len(pairs)
    n_abstained = n_total - len(positions)
    coverage = (len(positions) / n_total) if n_total else 0.0

    return AssembleResult(
        positions=tuple(positions),
        n_pairs_total=n_total,
        n_pairs_abstained=n_abstained,
        coverage=round(coverage, 6),
        error=None,
    )


# ── Net-exposure check ──────────────────────────────────────────────────────


def net_exposure(positions: Sequence[PairPosition]) -> dict[str, float]:
    """Compute net per-symbol exposure from a list of L/S positions.

    Each `weight` is the gross long-short weight on that pair (positive = long
    sym_long, negative = short sym_short, which means subtract from sym_short).
    Returns dict[symbol, net_weight]. Should sum to ~0 for a market-neutral book.

    For a per-symbol book:
      +w on (long=X, short=Y) means +w of X and -w of Y.
    """
    out: dict[str, float] = {}
    for p in positions:
        out[p.sym_long] = out.get(p.sym_long, 0.0) + p.weight
        out[p.sym_short] = out.get(p.sym_short, 0.0) - p.weight
    return {k: round(v, 6) for k, v in out.items()}


__all__ = [
    "PairPosition",
    "AssembleResult",
    "assemble_pair_positions",
    "net_exposure",
]
