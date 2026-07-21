"""
Strategy Embedder — hand-crafted 30-dim vector per docs/MECHANISM_SPEC.md §3
=============================================================================

Mirrors the asset embedder pattern (src/data/vector/embedder.py) — no model
dependency, in-memory cosine similarity, JSON-storable.

Dimensions (fixed order; reorder = breaking change):

  [0–5]   regime_domain       (calm/storm vol, risk-on/off, trend/chop)
  [6–10]  factor_exposure     (market, momentum, carry, quality β + residual α)
  [11–14] mechanics           (holding_period_log, turnover, time_in_mkt, directionality)
  [15–17] capacity            (adv_fraction, declared, realized_fill_pct)
  [18–21] lifecycle           (age_days, decay_slope, crowding, half_life_days)
  [22–25] cost_sensitivity    (0bps, 2bps, 5bps, 10bps sharpe)
  [26–29] outcome             (realized_α, realized_decay, capacity_util, confidence)

All dims normalized to [-1, 1] or [0, 1] depending on semantics. Missing fields
default to 0.0 (neutral) — this is the core compromise for incremental backfill:
doctrinal primitives without cost-sensitivity sit at 0 for those dims, which is
fine because cosine cares about shape, not absolute level.

The strategy_embedder never raises on missing data; it warns via stdlib logging.
For pre-flight warnings before committing a record, use `coverage_summary()`.
"""
from __future__ import annotations

import logging
import math
from typing import Iterable

import numpy as np

from .strategy_schema import (
    StrategyRecord,
    REGIME_DIMS,
    FACTOR_DIMS,
    MECHANICS_DIMS,
    CAPACITY_DIMS,
    LIFECYCLE_DIMS,
    COST_DIMS,
    OUTCOME_DIMS,
)

_logger = logging.getLogger(__name__)

VECTOR_DIMS: int = 30


# ---------------------------------------------------------------------------
# Normalization helpers — keep them readable so each dim's meaning is inspectable
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _safe_get(d: dict, key: str, default=None):
    """Get with None fallback (None × number → 0)."""
    v = d.get(key, default)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Per-dim normalization functions, returning a float in [-1, 1] or [0, 1].

def _norm_sharpe(v) -> float:
    """Sharpe, normalized. cap at 4×annualized; missing → 0."""
    if v is None:
        return 0.0
    return _clamp(float(v) / 2.0, -1.0, 1.0)


def _norm_beta(v) -> float:
    """Factor β, normalized. cap at ±2; missing → 0."""
    if v is None:
        return 0.0
    return _clamp(float(v) / 2.0, -1.0, 1.0)


def _norm_holding_period_days(v) -> float:
    """log-hold normalized to [0,1] using 365d as 1.0."""
    if v is None or v <= 0:
        return 0.0
    return _clamp(math.log1p(float(v)) / math.log(365.0 + 1), 0.0, 1.0)


def _norm_turnover(v) -> float:
    """Flips per quarter, normalized to [0, 1] at 4."""
    if v is None:
        return 0.0
    return _clamp(float(v) / 4.0, 0.0, 1.0)


def _norm_time_in_market(v) -> float:
    """Already [0, 100]%; map to [0, 1]."""
    if v is None:
        return 0.0
    return _clamp(float(v) / 100.0, 0.0, 1.0)


def _norm_directionality(v) -> float:
    """Already [-1, 1]."""
    if v is None:
        return 0.0
    return _clamp(float(v), -1.0, 1.0)


def _norm_adv_fraction(v) -> float:
    """ADV participation cap at 10% of daily volume."""
    if v is None:
        return 0.0
    return _clamp(float(v) * 10.0, 0.0, 1.0)


def _norm_declared_capacity(v) -> float:
    """Declared capacity. log-normalized; $10M = 0.5, $100M = 0.75, $1B = 1.0."""
    if v is None or v <= 0:
        return 0.0
    # $1M -> 0.25, $10M -> 0.5, $100M -> 0.75, $1B -> 1.0
    return _clamp(math.log10(max(float(v), 1e4)) / 8.0, 0.0, 1.0)


def _norm_realized_fill_pct(v) -> float:
    """Realized fill as fraction of declared, mapped to [0, 1]."""
    if v is None:
        return 0.0
    return _clamp(float(v) / 100.0, 0.0, 1.0)


def _norm_age_days(v) -> float:
    """log age normalized. 365d = 0.5, 1825d (5y) = 1.0."""
    if v is None or v <= 0:
        return 0.0
    return _clamp(math.log1p(float(v)) / math.log(1825.0 + 1), 0.0, 1.0)


def _norm_decay_slope(v) -> float:
    """Decay slope per day. ±5%/day normalizes to ±1."""
    if v is None:
        return 0.0
    return _clamp(float(v) * 20.0, -1.0, 1.0)


def _norm_crowding(v) -> float:
    """Crowding signal [-1, 1]."""
    if v is None:
        return 0.0
    return _clamp(float(v), -1.0, 1.0)


def _norm_half_life_days(v) -> float:
    """log half-life; 90d = 0.5, 365d = 1.0."""
    if v is None or v <= 0:
        return 0.0
    return _clamp(math.log1p(float(v)) / math.log(365.0 + 1), 0.0, 1.0)


def _norm_outcome_alpha(v) -> float:
    """Realized α. Cap at ±20%."""
    if v is None:
        return 0.0
    return _clamp(float(v) * 5.0, -1.0, 1.0)


def _norm_outcome_decay(v) -> float:
    """Same as decay slope."""
    return _norm_decay_slope(v)


def _norm_capacity_util(v) -> float:
    """[0, 1]."""
    if v is None:
        return 0.0
    return _clamp(float(v), 0.0, 1.0)


def _norm_outcome_confidence(v) -> float:
    """[0, 1]."""
    if v is None:
        return 0.0
    return _clamp(float(v), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

def generate_embedding(record: StrategyRecord) -> list[float]:
    """Produce the 30-dim hand-crafted vector for a strategy record.

    Missing fields → 0.0 (neutral). This is the design tradeoff for
    incremental backfill: doctrinal primitives lack cost-sensitivity;
    refuted R-entries lack realized_α; both produce partial vectors.
    """
    vec: list[float] = []

    # [0–5] regime_domain
    rd = record.regime_domain
    for key in REGIME_DIMS:
        vec.append(_norm_sharpe(_safe_get(rd, key)))

    # [6–10] factor_exposure
    fe = record.factor_exposure
    for key in FACTOR_DIMS:
        if key == "residual_alpha":
            # residual_alpha uses Sharpe-style normalization
            vec.append(_norm_sharpe(_safe_get(fe, key)))
        else:
            vec.append(_norm_beta(_safe_get(fe, key)))

    # [11–14] mechanics
    mech = record.mechanics
    vec.append(_norm_holding_period_days(_safe_get(mech, "holding_period_days")))
    vec.append(_norm_turnover(_safe_get(mech, "turnover_per_q")))
    vec.append(_norm_time_in_market(_safe_get(mech, "time_in_market")))
    vec.append(_norm_directionality(_safe_get(mech, "directionality")))

    # [15–17] capacity
    cap = record.capacity
    vec.append(_norm_adv_fraction(_safe_get(cap, "adv_fraction")))
    vec.append(_norm_declared_capacity(_safe_get(cap, "declared_capacity")))
    vec.append(_norm_realized_fill_pct(_safe_get(cap, "realized_fill_pct")))

    # [18–21] lifecycle
    lc = record.lifecycle
    vec.append(_norm_age_days(_safe_get(lc, "age_days")))
    vec.append(_norm_decay_slope(_safe_get(lc, "decay_slope")))
    vec.append(_norm_crowding(_safe_get(lc, "crowding_proxy")))
    vec.append(_norm_half_life_days(_safe_get(lc, "half_life_days")))

    # [22–25] cost_sensitivity
    cs = record.cost_sensitivity
    for bps in ("0bps", "2bps", "5bps", "10bps"):
        vec.append(_norm_sharpe(_safe_get(cs, bps)))

    # [26–29] outcome
    vec.append(_norm_outcome_alpha(record.realized_alpha))
    vec.append(_norm_outcome_decay(record.realized_decay))
    vec.append(_norm_capacity_util(record.capacity_util))
    vec.append(_norm_outcome_confidence(record.outcome_confidence))

    if len(vec) != VECTOR_DIMS:
        raise RuntimeError(
            f"vector dim mismatch: expected {VECTOR_DIMS}, got {len(vec)}"
        )
    return vec


# ---------------------------------------------------------------------------
# Coverage diagnostic
# ---------------------------------------------------------------------------

def coverage_summary(record: StrategyRecord) -> dict:
    """What fraction of dimensions have non-default (non-zero) values?

    Useful pre-commit to flag records that are mostly empty — they will sit
    at origin in cosine space and be "similar to everything" by virtue of
    being "specific to nothing." Backfill authors should aim for ≥0.40
    coverage (12+ dimensions) before considering a record queryable.
    """
    vec = generate_embedding(record)
    n_nonzero = sum(1 for v in vec if abs(v) > 1e-9)
    return {
        "id": record.id,
        "dims_total": VECTOR_DIMS,
        "dims_nonzero": n_nonzero,
        "coverage_pct": round(100.0 * n_nonzero / VECTOR_DIMS, 1),
        "verdict": record.verdict.value if hasattr(record.verdict, "value") else str(record.verdict),
    }


# ---------------------------------------------------------------------------
# Similarity (mirrors embedder.py)
# ---------------------------------------------------------------------------

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def find_similar(
    target_id: str,
    embeddings: dict[str, list[float]],
    k: int = 5,
    include_doctrine: bool = True,
) -> list[dict]:
    """Top-k similar strategies to target by cosine similarity.

    Args:
      target_id:        key in `embeddings`
      embeddings:       {id: 30-dim vec}
      k:                max neighbors to return (excluding target itself)
      include_doctrine: include Verdict.DOCTRINE records (default True)

    Returns:
      [{id, similarity}] sorted by similarity desc.

    Note: filtering by verdict requires metadata; that lives in the StrategyRecord,
    not the vector. For verdict-filtered similarity, do the lookup in
    `strategy_store.find_similar_filtered()`.
    """
    target_vec = embeddings.get(target_id)
    if target_vec is None:
        return []
    results: list[dict] = []
    for cid, vec in embeddings.items():
        if cid == target_id:
            continue
        sim = cosine_similarity(target_vec, vec)
        results.append({"id": cid, "similarity": round(sim, 4)})
    results.sort(key=lambda x: -x["similarity"])
    return results[:k]


# ---------------------------------------------------------------------------
# Bulk helper
# ---------------------------------------------------------------------------

def embed_many(records: Iterable[StrategyRecord]) -> dict[str, list[float]]:
    """Generate embeddings for an iterable of records. Skips records that fail validation
    loudly (logs the validation issues first)."""
    out: dict[str, list[float]] = {}
    for r in records:
        problems = r.validate()
        if problems:
            _logger.warning(f"[strategy_embedder] {r.id} validation: {problems}")
        out[r.id] = generate_embedding(r)
    return out
