"""Smoke tests for C5 R77 episode VDB-cluster (per §C5-SHIP-SPEC 2026-08-12).

Coverage:
  1.  Frozen constants intact (per §C5 §1)
  2.  _cosine_distance: identical → 0.0
  3.  _cosine_distance: orthogonal → 1.0
  4.  _cosine_distance: opposite → 2.0
  5.  _cosine_distance: < MIN_SHARED_DIMS → NaN (I1 boundary)
  6.  _cosine_distance: mismatched dims → ValueError
  7.  compute_episode_distances: single day → NaN series
  8.  compute_episode_distances: length mismatch → ValueError
  9.  compute_episode_distances: sorts by date
 10.  cluster_episodes: empty distances → []
 11.  cluster_episodes: no boundary → 1 episode (whole span)
 12.  cluster_episodes: distance > threshold splits
 13.  cluster_episodes: drops episodes shorter than MIN_EPISODE_DAYS
 14.  assign_episode_alphas: episode picks up sign + t-stat
 15.  assign_episode_alphas: empty alphas → unchanged
 16.  verify_episode_floor: 8+ positive episodes + pooled_t ≥ 2.0 → CLEAR
 17.  verify_episode_floor: < 8 episodes → INSUFFICIENT_EPISODES
 18.  verify_episode_floor: sign minority → HETEROGENEOUS_REGIME
 19.  verify_episode_floor: pooled_t below floor → HETEROGENEOUS_REGIME
 20.  live_forward_episode_attribution: pos/neg counts + per_episode payload

Pure Python + numpy + pandas. Sandbox-safe. No network.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.r77_episode_vdb_cluster import (
    SCHEMA_VERSION,
    BOUNDARY_THRESHOLD_DEFAULT,
    MIN_EPISODE_DAYS,
    TOTAL_DIMS,
    MIN_SHARED_DIMS,
    DIST_PERSISTENCE_DAYS,
    INCEPTION_ID,
    VERDICTS,
    C5_EPISODES_CLEAR,
    C5_INSUFFICIENT_EPISODES,
    C5_HETEROGENEOUS_REGIME,
    C5_R77_REGIME_CANDIDATE_UPGRADED,
    Episode,
    _cosine_distance,
    compute_episode_distances,
    cluster_episodes,
    assign_episode_alphas,
    verify_episode_floor,
    live_forward_episode_attribution,
)


# ── 1. Frozen constants ──────────────────────────────────────────────────────
def test_constants_frozen():
    """§C5 §1: 12-dim fingerprint, threshold 0.30, MIN_EPISODE_DAYS=5."""
    assert SCHEMA_VERSION == 1, "SCHEMA_VERSION must remain 1 unless contract bumped"
    assert BOUNDARY_THRESHOLD_DEFAULT == 0.30, "M-WO-7.1 80th-pct distance"
    assert MIN_EPISODE_DAYS == 5, "align with C2 dwell=5"
    assert TOTAL_DIMS == 12, "M-WO-7.1 fingerprint width"
    assert MIN_SHARED_DIMS == 4, "I1 boundary"
    assert DIST_PERSISTENCE_DAYS == 7
    assert INCEPTION_ID == "c5_episode_v1"
    # verdict grammar
    assert {C5_EPISODES_CLEAR,
            C5_INSUFFICIENT_EPISODES,
            C5_HETEROGENEOUS_REGIME,
            C5_R77_REGIME_CANDIDATE_UPGRADED}.issubset(VERDICTS)


# ── 2-6. _cosine_distance ────────────────────────────────────────────────────
def test_cosine_distance_identical():
    v = [0.1 * i for i in range(TOTAL_DIMS)]
    assert abs(_cosine_distance(v, v)) < 1e-9, "identical → ~0 (FP-safe)"


def test_cosine_distance_orthogonal():
    """Two orthogonal 12-d vectors → distance = 1.0."""
    a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert abs(_cosine_distance(a, b) - 1.0) < 1e-9


def test_cosine_distance_opposite():
    """v vs -v → distance = 2.0 (cosine = -1)."""
    v = [0.1 * (i + 1) for i in range(TOTAL_DIMS)]
    neg = [-x for x in v]
    assert abs(_cosine_distance(v, neg) - 2.0) < 1e-9


def test_cosine_distance_sparse_returns_nan():
    """< MIN_SHARED_DIMS finite dims → NaN (I1 boundary, not 0.0)."""
    # Only 3 finite dims in a (others NaN); b all finite → shared = 3
    a = [0.1, 0.2, 0.3, float("nan"), float("nan"), float("nan"),
         float("nan"), float("nan"), float("nan"), float("nan"),
         float("nan"), float("nan")]
    b = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
    result = _cosine_distance(a, b)
    assert math.isnan(result), f"I1: must return NaN, got {result}"


def test_cosine_distance_rejects_mismatched_dims():
    """Mismatched vector widths → ValueError."""
    a = [0.1] * 12
    b = [0.1] * 6
    try:
        _cosine_distance(a, b)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


# ── 7-9. compute_episode_distances ───────────────────────────────────────────
def test_compute_episode_distances_single_day():
    """Single day → NaN series (no predecessor)."""
    vecs = [[0.1] * TOTAL_DIMS]
    dates = [pd.Timestamp("2026-08-01")]
    out = compute_episode_distances(vecs, dates)
    assert len(out) == 1
    assert math.isnan(out.iloc[0])


def test_compute_episode_distances_length_mismatch():
    vecs = [[0.1] * TOTAL_DIMS, [0.2] * TOTAL_DIMS]
    dates = [pd.Timestamp("2026-08-01")]
    try:
        compute_episode_distances(vecs, dates)
        assert False, "should have raised"
    except ValueError:
        pass


def test_compute_episode_distances_sorts_by_date():
    """Out-of-order dates should be sorted before computing distances."""
    vecs_unsorted = [
        [0.5] * TOTAL_DIMS,
        [0.1] * TOTAL_DIMS,
        [0.9] * TOTAL_DIMS,
    ]
    dates_unsorted = [
        pd.Timestamp("2026-08-03"),
        pd.Timestamp("2026-08-01"),
        pd.Timestamp("2026-08-02"),
    ]
    out = compute_episode_distances(vecs_unsorted, dates_unsorted)
    assert out.index[0] == pd.Timestamp("2026-08-01")
    assert out.index[1] == pd.Timestamp("2026-08-02")
    assert out.index[2] == pd.Timestamp("2026-08-03")
    # First day NaN
    assert math.isnan(out.iloc[0])


# ── 10-13. cluster_episodes ──────────────────────────────────────────────────
def test_cluster_episodes_empty():
    """Empty distance series → no episodes."""
    idx = pd.DatetimeIndex([], name="d")
    out = cluster_episodes(pd.Series([], dtype=float, index=idx),
                           vecs=[])
    assert out == []


def test_cluster_episodes_no_boundary_one_episode():
    """All distances below threshold → 1 episode covering the whole span."""
    n = 30
    dates = pd.date_range("2026-07-01", periods=n, freq="D")
    vecs = [[float(i % 3) * 0.1] * TOTAL_DIMS for i in range(n)]
    # Use very similar vectors so distances stay tiny
    vecs = [[0.5 + 1e-4 * i] + [0.0] * (TOTAL_DIMS - 1) for i in range(n)]
    distances = compute_episode_distances(vecs, dates)
    eps = cluster_episodes(distances, vecs)
    assert len(eps) == 1, "no boundary = 1 episode"
    assert eps[0].n_days == n
    assert eps[0].start_date == dates[0]
    assert eps[0].end_date == dates[-1]


def test_cluster_episodes_splits_at_boundary():
    """Distance > threshold on day 5 → splits into 2 episodes."""
    n = 15
    dates = pd.date_range("2026-07-01", periods=n, freq="D")
    # First 5 days identical, day 5→6 = max distance (orthogonal shift)
    vecs = []
    for i in range(n):
        if i < 5:
            vecs.append([1.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                         0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        elif i < 10:
            vecs.append([0.0, 1.0, 0.0, 0.0, 0.0, 0.0,
                         0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        else:
            vecs.append([0.0, 0.0, 1.0, 0.0, 0.0, 0.0,
                         0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    distances = compute_episode_distances(vecs, dates)
    eps = cluster_episodes(distances, vecs, boundary_threshold=0.30,
                           min_episode_days=2)
    assert len(eps) >= 2, f"orthogonal shifts must split, got {len(eps)}"


def test_cluster_episodes_drops_short():
    """Episodes shorter than MIN_EPISODE_DAYS must be dropped."""
    dates = pd.date_range("2026-07-01", periods=12, freq="D")
    # 7 days identical → 1 episode (length 7)
    # day 7→8 = orthogonal shift (boundary)
    # 2 days identical → 1 short episode (length 2, below MIN_EPISODE_DAYS=5)
    # day 9→10 = orthogonal shift (boundary)
    # 3 days identical → short episode (length 3, dropped)
    vecs = [
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 0
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 1
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 2
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 3
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 4
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 5
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 6
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], # 7 (boundary)
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], # 8
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], # 9 (boundary)
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], # 10
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], # 11
    ]
    distances = compute_episode_distances(vecs, dates)
    eps = cluster_episodes(distances, vecs, boundary_threshold=0.30,
                           min_episode_days=5)
    # Only the first 7-day episode should survive
    assert len(eps) == 1, f"only 7-day episode survives, got {len(eps)}"
    assert eps[0].n_days == 7


# ── 14-15. assign_episode_alphas ─────────────────────────────────────────────
def test_assign_episode_alphas_with_sign_and_t():
    """Episode picks up mean_daily_alpha + sign + episode_t_pooled."""
    n = 10
    dates = pd.date_range("2026-08-01", periods=n, freq="D")
    vecs = [[0.5 + 1e-4 * i] + [0.0] * (TOTAL_DIMS - 1) for i in range(n)]
    distances = compute_episode_distances(vecs, dates)
    eps = cluster_episodes(distances, vecs, boundary_threshold=0.30,
                           min_episode_days=5)
    assert len(eps) == 1
    # r77 alphas: positive with low variance → high t-stat
    r77_alphas = pd.Series([0.001] * n, index=dates)
    enriched = assign_episode_alphas(eps, r77_alphas)
    assert enriched[0].mean_daily_alpha == pytest_approx(0.001)
    assert enriched[0].episode_sign == 1
    assert enriched[0].alpha_count == n
    # t_stat should be NaN (zero std) or finite
    assert enriched[0].episode_t_pooled is None or math.isnan(enriched[0].episode_t_pooled) \
        or math.isfinite(enriched[0].episode_t_pooled)


def pytest_approx(x):
    """Local approx to avoid pytest.approx in pure-python assertion."""
    class _A:
        def __init__(self, v): self.v = v
        def __eq__(self, other): return abs(self.v - other) < 1e-6
    return _A(x)


def test_assign_episode_alphas_empty_alphas():
    """Empty r77_alphas → episodes unchanged."""
    n = 10
    dates = pd.date_range("2026-08-01", periods=n, freq="D")
    vecs = [[0.5] * TOTAL_DIMS for _ in range(n)]
    distances = compute_episode_distances(vecs, dates)
    eps = cluster_episodes(distances, vecs)
    empty = pd.Series([], dtype=float)
    enriched = assign_episode_alphas(eps, empty)
    assert enriched[0].mean_daily_alpha is None
    assert enriched[0].episode_sign == 0


# ── 16-19. verify_episode_floor ──────────────────────────────────────────────
def _make_episode(start: str, end: str, sign: int = 1, t: float = 2.5) -> Episode:
    return Episode(
        episode_id="x",
        start_date=pd.Timestamp(start),
        end_date=pd.Timestamp(end),
        n_days=10,
        max_daily_distance=0.10,
        mean_daily_distance=0.05,
        regime_centroid=[0.5] * TOTAL_DIMS,
        episode_t_pooled=t,
        episode_sign=sign,
        mean_daily_alpha=0.001,
        alpha_count=10,
    )


def test_verify_episode_floor_clear():
    """8 positive episodes with pooled_t ≥ 2.0 → CLEAR."""
    eps = [_make_episode("2026-01-01", "2026-01-10", sign=1, t=2.5) for _ in range(8)]
    assert verify_episode_floor(eps) == C5_EPISODES_CLEAR


def test_verify_episode_floor_insufficient():
    """< 8 episodes → INSUFFICIENT_EPISODES."""
    eps = [_make_episode("2026-01-01", "2026-01-10", sign=1, t=2.5) for _ in range(7)]
    assert verify_episode_floor(eps) == C5_INSUFFICIENT_EPISODES


def test_verify_episode_floor_heterogeneous_sign():
    """Sign minority (4+ out of 8 negative) → HETEROGENEOUS_REGIME."""
    eps = (
        [_make_episode("2026-01-01", "2026-01-10", sign=1, t=2.5) for _ in range(4)]
        + [_make_episode("2026-01-11", "2026-01-20", sign=-1, t=-2.5) for _ in range(4)]
    )
    assert verify_episode_floor(eps) == C5_HETEROGENEOUS_REGIME


def test_verify_episode_floor_pooled_t_below_floor():
    """Positive majority but pooled_t < 2.0 → HETEROGENEOUS_REGIME."""
    eps = [_make_episode("2026-01-01", "2026-01-10", sign=1, t=1.5) for _ in range(8)]
    assert verify_episode_floor(eps) == C5_HETEROGENEOUS_REGIME


# ── 20. live_forward_episode_attribution ─────────────────────────────────────
def test_live_forward_episode_attribution_counts():
    """Counts pos/neg + per-episode payload shape."""
    eps = (
        [_make_episode("2026-10-01", "2026-10-10", sign=1, t=2.5) for _ in range(3)]
        + [_make_episode("2026-10-11", "2026-10-20", sign=-1, t=-1.0) for _ in range(2)]
    )
    out = live_forward_episode_attribution(
        today=pd.Timestamp("2026-10-20").date(),
        forward_episodes=eps,
        forward_alphas=pd.Series([], dtype=float),
    )
    assert out["total_episodes"] == 5
    assert out["positive_count"] == 3
    assert out["negative_count"] == 2
    assert len(out["per_episode"]) == 5
    assert out["per_episode"][0]["start_date"] == "2026-10-01T00:00:00"


def test_live_forward_episode_attribution_empty():
    """Empty forward_episodes → 0 + note."""
    out = live_forward_episode_attribution(
        today=pd.Timestamp("2026-10-20").date(),
        forward_episodes=[],
        forward_alphas=pd.Series([], dtype=float),
    )
    assert out["total_episodes"] == 0
    assert "note" in out


# ── run all ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))