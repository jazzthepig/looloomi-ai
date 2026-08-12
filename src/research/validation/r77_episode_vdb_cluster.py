"""
r77_episode_vdb_cluster.py — C5 VDB episode-structure for R77 forward evaluation.

Per §C5-SHIP-SPEC 2026-08-12 (Minimax-C contract):
  Episode = VDB-similarity cluster of consecutive days. The boundary is
  cosine_distance(vec[t], vec[t-1]) > BOUNDARY_THRESHOLD (default 0.30).
  Per episode ≥ MIN_EPISODE_DAYS (default 5, aligned with C2 dwell=5).

The M-WO-1 calendar gap>7d episode definition produces 1 episode for any
daily-rebal book (the 731d window is mostly continuous). C5's VDB-cluster
definition produces 8-15 episodes on the same window, allowing the
R77 forward 60d evaluation to use episode-conditional t-stat instead of
day-level t-stat.

This module is pure: every function takes explicit args, no live Supabase,
no live network. The dependency on D2 push backfill (r77_fwd_5d_alpha_pct
labels) is captured as an explicit `r77_alphas` argument — the caller
fetches them and passes them in.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd


# ── Frozen constants (per §C5-SHIP-SPEC §1) ─────────────────────────────────
SCHEMA_VERSION = 1                                              # bumped on edit
BOUNDARY_THRESHOLD_DEFAULT = 0.30                               # M-WO-7.1 distance 80th pct
MIN_EPISODE_DAYS = 5                                            # align with C2 dwell=5
TOTAL_DIMS = 12                                                 # M-WO-7.1 fingerprint
MIN_SHARED_DIMS = 4                                             # I1 boundary
DIST_PERSISTENCE_DAYS = 7                                       # episodes < 7d are absorbed
INCEPTION_ID = "c5_episode_v1"                                  # ship 9 月

# ── Verdict grammar (per §C5 §3) ─────────────────────────────────────────────
C5_EPISODES_CLEAR = "C5_EPISODES_CLEAR"
C5_INSUFFICIENT_EPISODES = "C5_INSUFFICIENT_EPISODES"
C5_HETEROGENEOUS_REGIME = "C5_HETEROGENEOUS_REGIME"
C5_R77_REGIME_CANDIDATE_UPGRADED = "C5_R77_REGIME_CANDIDATE_UPGRADED"

VERDICTS = {
    C5_EPISODES_CLEAR,
    C5_INSUFFICIENT_EPISODES,
    C5_HETEROGENEOUS_REGIME,
    C5_R77_REGIME_CANDIDATE_UPGRADED,
}


# ── Cosine distance (port of regime_fingerprints.cosine_similarity) ──────────
def _cosine_distance(vec_a: list[float], vec_b: list[float]) -> float:
    """1 - cosine_similarity over shared non-NaN dims. NaN if shared < MIN_SHARED_DIMS.

    I1: NaN is preserved; no silent default to 0.0.
    """
    if len(vec_a) != len(vec_b) or len(vec_a) != TOTAL_DIMS:
        raise ValueError(f"cosine_distance requires two {TOTAL_DIMS}-dim vectors, got "
                         f"{len(vec_a)}, {len(vec_b)}")
    a_finite = [(i, v) for i, v in enumerate(vec_a)
                if isinstance(v, float) and math.isfinite(v)]
    b_finite = [(i, v) for i, v in enumerate(vec_b)
                if isinstance(v, float) and math.isfinite(v)]
    shared = [(i, va, vb) for (i, va) in a_finite for (j, vb) in b_finite if i == j]
    if len(shared) < MIN_SHARED_DIMS:
        return float("nan")
    num = sum(va * vb for _, va, vb in shared)
    den_a = math.sqrt(sum(va * va for _, va, _ in shared))
    den_b = math.sqrt(sum(vb * vb for _, _, vb in shared))
    if den_a <= 0 or den_b <= 0:
        return float("nan")
    return 1.0 - num / (den_a * den_b)


# ── Daily distance series (pure) ────────────────────────────────────────────
def compute_episode_distances(
    vecs: Sequence[Sequence[float]],
    dates: Sequence[pd.Timestamp],
) -> pd.Series:
    """cosine_distance(vec[t], vec[t-1]) for each t > 0. Index = dates.

    First day (no predecessor) → NaN. Sparse / I1 violation → NaN.
    Sorts by date before computing (the spec assumes time-ordered panel).
    """
    if len(vecs) != len(dates):
        raise ValueError(f"vecs/dates length mismatch: {len(vecs)} vs {len(dates)}")
    if len(dates) < 2:
        return pd.Series([float("nan")] * len(dates),
                         index=pd.to_datetime(dates))
    # Sort by date
    pairs = sorted(zip(pd.to_datetime(dates), vecs), key=lambda kv: kv[0])
    sorted_dates = [p[0] for p in pairs]
    sorted_vecs = [p[1] for p in pairs]
    out = [float("nan")]                                          # first day has no predecessor
    for i in range(1, len(sorted_vecs)):
        out.append(_cosine_distance(sorted_vecs[i], sorted_vecs[i - 1]))
    return pd.Series(out, index=pd.DatetimeIndex(sorted_dates))


# ── Episode clustering (pure) ────────────────────────────────────────────────
@dataclass
class Episode:
    """A VDB-similarity cluster of consecutive days."""
    episode_id: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    n_days: int
    max_daily_distance: float
    mean_daily_distance: float
    regime_centroid: list[float]
    n_neighbors: int = 0                                         # VDB k=20 placeholder
    episode_t_pooled: float | None = None
    episode_sign: int = 0                                        # +1, -1, 0
    mean_daily_alpha: float | None = None
    alpha_count: int = 0                                         # number of r77_alphas available


def cluster_episodes(
    distances: pd.Series,
    vecs: Sequence[Sequence[float]],
    boundary_threshold: float = BOUNDARY_THRESHOLD_DEFAULT,
    min_episode_days: int = MIN_EPISODE_DAYS,
) -> list[Episode]:
    """Cluster consecutive days into episodes via VDB distance boundary.

    episode boundary = d[t] > boundary_threshold.
    Episodes with n_days < min_episode_days are DROPPED (not merged to neighbors).
    Per §C5 §1: episodes are 'genuine regime shifts', not just low-vol stretches.
    """
    if len(distances) != len(vecs):
        raise ValueError(f"distances/vecs length mismatch: {len(distances)} vs {len(vecs)}")
    if distances.empty:
        return []
    # First day always starts an episode (no predecessor).
    episodes: list[Episode] = []
    cur_start_idx = 0
    for i in range(1, len(distances)):
        d = distances.iloc[i]
        if pd.isna(d) or d > boundary_threshold:
            # Boundary at index i: close current episode
            episodes.append(_episode_slice(
                vecs=vecs, distances=distances,
                start_idx=cur_start_idx, end_idx=i - 1,         # inclusive
            ))
            cur_start_idx = i
    # Close the final episode
    episodes.append(_episode_slice(
        vecs=vecs, distances=distances,
        start_idx=cur_start_idx, end_idx=len(distances) - 1,
    ))
    # Filter by min_episode_days
    return [e for e in episodes if e.n_days >= min_episode_days]


def _episode_slice(
    vecs: Sequence[Sequence[float]],
    distances: pd.Series,
    start_idx: int,
    end_idx: int,
) -> Episode:
    """Build an Episode dataclass from a slice of the panel."""
    n_days = end_idx - start_idx + 1
    if n_days < 1:
        raise ValueError(f"empty episode slice: {start_idx}..{end_idx}")
    # Episode-level distances (skip NaN at start_idx if it is the first day)
    ep_distances = distances.iloc[start_idx:end_idx + 1].dropna()
    max_d = float(ep_distances.max()) if not ep_distances.empty else float("nan")
    mean_d = float(ep_distances.mean()) if not ep_distances.empty else float("nan")
    # Regime centroid: per-dim mean (NaN-aware)
    centroid = []
    for dim in range(TOTAL_DIMS):
        vals = [vecs[i][dim] for i in range(start_idx, end_idx + 1)
                if isinstance(vecs[i][dim], float) and math.isfinite(vecs[i][dim])]
        centroid.append(float(np.mean(vals)) if vals else float("nan"))
    return Episode(
        episode_id=str(uuid.uuid4()),
        start_date=distances.index[start_idx],
        end_date=distances.index[end_idx],
        n_days=n_days,
        max_daily_distance=round(max_d, 6),
        mean_daily_distance=round(mean_d, 6),
        regime_centroid=centroid,
    )


# ── Episode features (alpha + t-stat) ───────────────────────────────────────
def assign_episode_alphas(
    episodes: Sequence[Episode],
    r77_alphas: pd.Series,                                       # indexed by date
) -> list[Episode]:
    """Attach r77_fwd_5d_alpha_pct labels to each episode.

    `r77_alphas` indexed by date; each episode looks up its date range
    and computes mean_daily_alpha + episode_t_pooled (one-sample t-test
    vs 0) + episode_sign.

    Episodes with zero alpha labels are returned with alpha fields None.
    """
    if r77_alphas.empty:
        return list(episodes)
    enriched = []
    for ep in episodes:
        mask = (r77_alphas.index >= ep.start_date) & (r77_alphas.index <= ep.end_date)
        ep_alphas = r77_alphas[mask].dropna()
        if ep_alphas.empty:
            enriched.append(ep)
            continue
        mean_alpha = float(ep_alphas.mean())
        if ep_alphas.size > 1:
            std_alpha = float(ep_alphas.std(ddof=1))
            t_stat = mean_alpha / (std_alpha / math.sqrt(ep_alphas.size)) \
                if std_alpha > 0 else float("nan")
        else:
            t_stat = float("nan")
        sign = 1 if mean_alpha > 0 else (-1 if mean_alpha < 0 else 0)
        enriched.append(Episode(
            episode_id=ep.episode_id,
            start_date=ep.start_date, end_date=ep.end_date,
            n_days=ep.n_days,
            max_daily_distance=ep.max_daily_distance,
            mean_daily_distance=ep.mean_daily_distance,
            regime_centroid=ep.regime_centroid,
            n_neighbors=ep.n_neighbors,
            episode_t_pooled=round(t_stat, 4) if math.isfinite(t_stat) else None,
            episode_sign=sign,
            mean_daily_alpha=round(mean_alpha, 6),
            alpha_count=int(ep_alphas.size),
        ))
    return enriched


# ── Verdict (per §C5 §3) ─────────────────────────────────────────────────────
def verify_episode_floor(
    episodes: Sequence[Episode],
    min_episodes: int = 8,
    sign_majority: float = 2 / 3,
    min_pooled_t: float = 2.0,
) -> str:
    """Return C5 verdict grammar.

    Rationale:
      - ≥8 episodes AND sign majority positive AND episode_t_pooled ≥2.0
        ⇒ C5_EPISODES_CLEAR (R77 status UNCHANGED: regime-specific candidate)
      - <8 episodes ⇒ C5_INSUFFICIENT_EPISODES
      - Episodes emit but signs are heterogeneous (< 2/3 majority) ⇒ C5_HETEROGENEOUS_REGIME
    """
    if not episodes:
        return C5_INSUFFICIENT_EPISODES
    if len(episodes) < min_episodes:
        return C5_INSUFFICIENT_EPISODES
    # Sign majority (only count episodes with a sign)
    signed = [ep for ep in episodes if ep.episode_sign != 0]
    if not signed:
        return C5_HETEROGENEOUS_REGIME
    pos_frac = sum(1 for ep in signed if ep.episode_sign > 0) / len(signed)
    if pos_frac < sign_majority:
        return C5_HETEROGENEOUS_REGIME
    # Pooled t-stat across episodes (mean of episode_t_pooled)
    pooled_ts = [ep.episode_t_pooled for ep in episodes
                 if ep.episode_t_pooled is not None and math.isfinite(ep.episode_t_pooled)]
    if not pooled_ts:
        return C5_HETEROGENEOUS_REGIME
    pooled_t = sum(pooled_ts) / len(pooled_ts)
    if pooled_t < min_pooled_t:
        return C5_HETEROGENEOUS_REGIME
    return C5_EPISODES_CLEAR


# ── Episode attribution (forward live, per §C5 §4) ──────────────────────────
def live_forward_episode_attribution(
    today: date,
    forward_episodes: Sequence[Episode],
    forward_alphas: pd.Series,
) -> dict:
    """For C4 evaluation (2026-10-08): report the current forward 60d episodes.

    Returns a dict with: total_episodes, positive_count, negative_count,
    pooled_t_pooled, episode_signs, per_episode alpha summary.
    """
    if not forward_episodes:
        return {"total_episodes": 0, "note": "no forward episodes yet"}
    pos = sum(1 for ep in forward_episodes if ep.episode_sign > 0)
    neg = sum(1 for ep in forward_episodes if ep.episode_sign < 0)
    pooled_ts = [ep.episode_t_pooled for ep in forward_episodes
                 if ep.episode_t_pooled is not None and math.isfinite(ep.episode_t_pooled)]
    return {
        "as_of": today.isoformat(),
        "total_episodes": len(forward_episodes),
        "positive_count": pos,
        "negative_count": neg,
        "pooled_t_mean": round(sum(pooled_ts) / len(pooled_ts), 4) if pooled_ts else None,
        "per_episode": [
            {
                "episode_id": ep.episode_id,
                "start_date": ep.start_date.isoformat(),
                "end_date": ep.end_date.isoformat(),
                "n_days": ep.n_days,
                "mean_daily_alpha": ep.mean_daily_alpha,
                "episode_sign": ep.episode_sign,
            }
            for ep in forward_episodes
        ],
    }
