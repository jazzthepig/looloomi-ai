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
MIN_SHARED_DIMS: int = 4          # cosine refuses below this many shared measured coords (I1)
_NAN = float("nan")

# Dimension-block offsets in the 30-dim vector (for library-level diagnostics).
_REGIME_SLICE = slice(0, 6)       # [0..5] regime_domain — coverage_gaps operates here


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


# Per-dim normalization, returning a float in [-1, 1] or [0, 1] — or NaN when UNMEASURED.
#
# I1 (VECTOR_SCHEMA_SPEC §0): unmeasured is NaN, NEVER 0. The prior version imputed 0.0 for a
# missing field, which asserts "average/neutral on an axis nobody measured" — with sparse records
# (doctrine primitives, refuted R-entries) that fabricates most of the map and makes every sparse
# record "similar to everything." NaN + NaN-aware cosine (skip shared-NaN dims) is the fix.
# A MEASURED 0 stays 0 (e.g. a market-neutral strategy's directionality); only an ABSENT field is NaN.

def _norm_sharpe(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) / 2.0, -1.0, 1.0)


def _norm_beta(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) / 2.0, -1.0, 1.0)


def _norm_holding_period_days(v) -> float:
    if v is None or v <= 0:          # non-positive hold on a log axis = unmeasurable, not 0
        return _NAN
    return _clamp(math.log1p(float(v)) / math.log(365.0 + 1), 0.0, 1.0)


def _norm_turnover(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) / 4.0, 0.0, 1.0)


def _norm_time_in_market(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) / 100.0, 0.0, 1.0)


def _norm_directionality(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v), -1.0, 1.0)


def _norm_adv_fraction(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) * 10.0, 0.0, 1.0)


def _norm_declared_capacity(v) -> float:
    """log-normalized; $10M = 0.5, $100M = 0.75, $1B = 1.0."""
    if v is None or v <= 0:
        return _NAN
    return _clamp(math.log10(max(float(v), 1e4)) / 8.0, 0.0, 1.0)


def _norm_realized_fill_pct(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) / 100.0, 0.0, 1.0)


def _norm_age_days(v) -> float:
    if v is None or v <= 0:
        return _NAN
    return _clamp(math.log1p(float(v)) / math.log(1825.0 + 1), 0.0, 1.0)


def _norm_decay_slope(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) * 20.0, -1.0, 1.0)


def _norm_crowding(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v), -1.0, 1.0)


def _norm_half_life_days(v) -> float:
    if v is None or v <= 0:
        return _NAN
    return _clamp(math.log1p(float(v)) / math.log(365.0 + 1), 0.0, 1.0)


def _norm_outcome_alpha(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v) * 5.0, -1.0, 1.0)


def _norm_outcome_decay(v) -> float:
    return _norm_decay_slope(v)


def _norm_capacity_util(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v), 0.0, 1.0)


def _norm_outcome_confidence(v) -> float:
    if v is None:
        return _NAN
    return _clamp(float(v), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

def generate_embedding(record: StrategyRecord) -> list[float]:
    """Produce the 30-dim hand-crafted vector for a strategy record.

    Missing fields → NaN (I1: unmeasured is not 0). Doctrinal primitives lack cost-sensitivity;
    refuted R-entries lack realized_α — those dims are NaN, and cosine_similarity skips them rather
    than pretending the strategy is average there. A MEASURED neutral (e.g. directionality 0) is 0.
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
    """What fraction of dimensions are actually MEASURED (non-NaN)?

    Under I1, an unmeasured dim is NaN, so coverage = non-NaN count (a measured 0 still counts —
    it is information). A low-coverage record is "specific to nothing" and similarity will refuse
    it below MIN_SHARED_DIMS. Backfill authors should aim for ≥0.40 coverage (12+ dims) before a
    record is queryable. `dims_nonzero` is retained as an alias for API back-compat (now = measured).
    """
    vec = generate_embedding(record)
    n_measured = sum(1 for v in vec if v == v)   # v==v is False only for NaN
    return {
        "id": record.id,
        "dims_total": VECTOR_DIMS,
        "dims_measured": n_measured,
        "dims_nonzero": n_measured,   # back-compat alias (semantics: measured, not literally nonzero)
        "coverage_pct": round(100.0 * n_measured / VECTOR_DIMS, 1),
        "verdict": record.verdict.value if hasattr(record.verdict, "value") else str(record.verdict),
    }


# ---------------------------------------------------------------------------
# Similarity (mirrors embedder.py)
# ---------------------------------------------------------------------------

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """NaN-aware, length-tolerant cosine in [−1, 1] (mirrors the asset embedder, I1).

    Compares only the shared leading prefix (schema-version tolerant), skips any coordinate NaN in
    EITHER vector, and refuses (0.0) below MIN_SHARED_DIMS shared measured coords — a confident
    number from one or two overlapping dims is noise, not similarity.
    """
    n = min(len(v1), len(v2))
    if n == 0:
        return 0.0
    a = np.asarray(v1[:n], dtype=np.float64)
    b = np.asarray(v2[:n], dtype=np.float64)
    mask = ~(np.isnan(a) | np.isnan(b))
    if int(mask.sum()) < MIN_SHARED_DIMS:
        return 0.0
    a, b = a[mask], b[mask]
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ---------------------------------------------------------------------------
# Binary validity floor + library-level diagnostics (ported from the converged
# src/research/strategy_vector.py — build-order #3, VECTOR_SCHEMA_SPEC §2.1)
# ---------------------------------------------------------------------------

def is_disqualified(record: StrategyRecord) -> tuple[bool, str]:
    """The BINARY validity floor (I4 / MECHANISM_SPEC §3). ONLY two conditions disqualify — they
    are facts, not lifecycle phases: PIT/look-ahead leakage, and cost-infeasibility at declared
    capacity (5 bps). `forward_committed` is a P1 lifecycle STATE, not a validity floor, so it does
    NOT disqualify. Everything else (regime fit, decay, crowding) is coordinates, never a kill.
    """
    if not record.pit_clean:
        return True, "PIT/look-ahead leakage — invalid, not a lifecycle phase"
    if not record.cost_feasible_at_5bps:
        return True, "cost-infeasible at declared capacity (5 bps)"
    return False, ""


def coverage_gaps(records, threshold: float = 0.25) -> list[dict]:
    """Which regimes the CURRENT library does NOT cover — the output that says what to build next
    instead of guessing. Disqualified sleeves are EXCLUDED (I4): a cost-infeasible sleeve cannot
    cover a regime it cannot trade. Operates on the regime block [0..5]. NaN dims are skipped.
    """
    live = [r for r in records if not is_disqualified(r)[0]]
    embeds = [generate_embedding(r) for r in live]
    gaps = []
    for i, dim in enumerate(REGIME_DIMS):
        vals = np.array([e[i] for e in embeds], dtype=np.float64)
        vals = vals[~np.isnan(vals)]
        best = float(vals.max()) if len(vals) else float("nan")
        gaps.append({
            "regime": dim,
            "n_measured": int(len(vals)),
            "best_in_library": None if math.isnan(best) else round(best, 3),
            "covered": bool(len(vals) and best >= threshold),
        })
    return gaps


def redundancy(records, thresh: float = 0.85) -> list[dict]:
    """Near-duplicate pairs — breadth we THINK we have but don't (R20: effective breadth was 6.74
    of 17 strategies). Correlated sleeves are one sleeve wearing several names. Excludes disqualified.
    """
    live = [r for r in records if not is_disqualified(r)[0]]
    embeds = [(r.id, generate_embedding(r)) for r in live]
    out = []
    for i in range(len(embeds)):
        for j in range(i + 1, len(embeds)):
            s = cosine_similarity(embeds[i][1], embeds[j][1])
            if s >= thresh:
                out.append({"a": embeds[i][0], "b": embeds[j][0], "similarity": round(s, 3)})
    return sorted(out, key=lambda d: -d["similarity"])


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
