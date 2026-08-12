"""
beta_core_size_hook.py — C3 conviction-size 2D layer hook.

Per §C3-SHIP-SPEC 2026-08-12: size[t] = 2D_table[regime, signal] × q_override,
clipped to [0, 1.3].

This module is the THIN integration layer between the ① book and the C3
size helpers. The C2 ⓠ layer (q_override) is REQUIRED; without it, the
hook degrades to q_override=1.0 (size = table lookup only).

DEFAULT BEHAVIOUR (first ship, 2026-09-10):
  - vdb_distance is None / signal_strength is None → regime_band=3, signal_band=1
  - size = lookup_size(3, 1) × 1.0, and under the validated table that cell is
    **≤ 1.0 by invariant**: no information must never produce leverage.

  CORRECTION (S-151, 2026-08-12). This docstring previously read:

      "size = lookup_size(3, 1) × 1.0 = 1.20 — This is the C3 baseline: with
       both inputs missing, the size is 1.20 (slightly above 1.0, the C1
       default)."

  That number came from a size table that was transposed on both axes, and
  writing it down here turned a defect into a specification. With zero
  information the book would have run at 1.20× gross, described as the plan.
  A bug is never more expensive than when it has been documented as intended —
  the docstring is the artefact the next reader trusts instead of measuring.

  The table now lives in `strategy_params` and a payload whose missing-data
  cell exceeds 1.0 cannot load. See `strategy_params._validate_c3_size`.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from src.data.signals.beta_core_size import (
    INCEPTION_ID,
    N_BANDS,
    active_params,
    compute_size as _compute_size,
    compute_signal_strength,
    Size2DState,
)

_log = logging.getLogger("beta_core_size_hook")


@dataclass
class C3HookConfig:
    """First-ship wire config. Sourced from C3 spec."""
    c2_q_override_source: str = "live"                          # "live" | "default_1.0"
    inception_id: str = INCEPTION_ID
    r62_detector_fragility: float | None = None                # 0.5 × R62 component
    vdb_match_outcome_strength: float | None = None            # 0.5 × VDB component


def c3_hook_config() -> C3HookConfig:
    """Read the current C3 hook config."""
    return C3HookConfig()


def compute_size_for_today(
    today: dt.date,
    vdb_distance: float | None,
    q_override: float,
    r62_detector_fragility: float | None = None,
    vdb_match_outcome_strength: float | None = None,
    params=None,
) -> Size2DState:
    """Compute C3 size for today. Pure function.

    Inputs:
      - vdb_distance: VDB match distance ∈ [0, 1] (NaN/None → band 3)
      - q_override: from C2 ⓠ layer (1.0 if C2 offline)
      - r62_detector_fragility: R62 detector fragility ∈ [0, 1] (None → no R62)
      - vdb_match_outcome_strength: VDB 5NN outcome strength ∈ [0, 1] (None → no VDB)

    Returns Size2DState with all diagnostic fields populated.
    """
    signal_strength = compute_signal_strength(
        r62_detector_fragility, vdb_match_outcome_strength,
    )
    return _compute_size(
        mark_date=today.isoformat(),
        vdb_distance=vdb_distance,
        signal_strength=signal_strength,
        q_override=q_override,
        params=params,
    )


# ── I/O wrapper (Supabase write) ─────────────────────────────────────────────
async def write_size_row(
    today: dt.date,
    size_state: Size2DState,
    nav: float,
    benchmark_nav: float,
    daily_return: float,
    excess_return: float,
    inception_id: str = INCEPTION_ID,
) -> bool:
    """Durable write to `beta_core_nav_size`. Returns False on failure.

    Per Lesson #107: a write that returns False is NOT the same as a write
    that ran. The ① baseline is independent, but a missing C3 row is a
    silent gap.
    """
    from src.api.store import supabase_insert_table
    row = {
        "mark_date": today.isoformat(),
        "inception_id": inception_id,
        "regime_band": size_state.regime_band,
        "signal_band": size_state.signal_band,
        "raw_table_size": size_state.raw_table_size,
        "q_override": size_state.q_override,
        "size_final": size_state.size_final,
        "clipped": size_state.clipped,
        "signal_strength": size_state.signal_strength,
        "vdb_distance": size_state.vdb_distance,
        # Provenance (S-151). Which parameters produced this mark. Without
        # these three, externalising the table would have made the sizing
        # silently mutable — the forward record cannot show what it cannot see.
        "param_namespace": INCEPTION_ID,
        "param_version": size_state.param_version,
        "param_source": size_state.param_source,
        "nav": round(nav, 6),
        "benchmark_nav": round(benchmark_nav, 6),
        "daily_return": round(daily_return, 6),
        "excess_return": round(excess_return, 6),
        "note": f"size={size_state.size_final:.4f} (r={size_state.regime_band},s={size_state.signal_band})",
    }
    try:
        ok = await supabase_insert_table("beta_core_nav_size", [row])
        if not ok:
            _log.error("[beta_core_size] SIZE ROW WRITE REJECTED for %s", today.isoformat())
        return bool(ok)
    except Exception as e:
        _log.error("[beta_core_size] SIZE ROW WRITE FAILED for %s: %s", today.isoformat(), e)
        return False


async def log_size_meta_event(
    today: dt.date,
    event_type: str,
    size_state: Size2DState | None,
    reason: str,
    drift_pct: float | None = None,
    flips_in_window: int | None = None,
    inception_id: str = INCEPTION_ID,
) -> bool:
    """Append to `beta_core_nav_size_meta`. Logs size_lookup_failure / drift_audit / cell_flip."""
    from src.api.store import supabase_insert_table
    row = {
        "mark_date": today.isoformat(),
        "inception_id": inception_id,
        "event_type": event_type,
        "regime_band": size_state.regime_band if size_state else None,
        "signal_band": size_state.signal_band if size_state else None,
        "size_final": size_state.size_final if size_state else None,
        "drift_pct": drift_pct,
        "flips_in_window": flips_in_window,
        "reason": reason,
    }
    try:
        ok = await supabase_insert_table("beta_core_nav_size_meta", [row])
        if not ok:
            _log.error("[beta_core_size] SIZE META WRITE REJECTED for %s/%s",
                       today.isoformat(), event_type)
        return bool(ok)
    except Exception as e:
        _log.error("[beta_core_size] SIZE META WRITE FAILED for %s/%s: %s",
                    today.isoformat(), event_type, e)
        return False
