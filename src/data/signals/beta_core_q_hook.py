"""
beta_core_q_hook.py — C2 ⓠ regime override layer hook for the ① book.

Per §C2-SHIP-SPEC 2026-08-12:
  gross_total[t] = beta_capture_gross[t] × q_override[t]
  q_override ∈ {0.0, 0.5, 1.0, 1.3}, default 1.0

This module is the THIN integration layer between the ① book (`beta_core_paper.py`)
and the ⓠ overlay helpers (`beta_core_q_overlay.py`). It does NOT compute the
VDB match itself — that is M-WO-7.1's match_regime_fingerprints RPC. The hook
calls the matcher, applies the dwell filter, and writes the resulting row to
`beta_core_nav_q`.

DEFAULT BEHAVIOR (first ship, 2026-09-15):
  - The VDB matcher is OPTIONAL but not yet wired to this hook.
  - Until the matcher is live, the hook returns q_override = 1.0 (baseline).
  - This means the first 60 days of the ⓠ overlay are IDENTICAL to the ①
    baseline — that is the correct safe ship state, since the C2 layer
    exists to verify the integration, not to immediately change behavior.
  - When the VDB matcher is wired (Mac-side D2), the hook activates and
    the ⓠ overlay begins to diverge from the ① baseline.

The C1 baseline is NEVER modified. The hook writes ONLY to:
  - beta_core_nav_q (the ⓠ overlay curve)
  - beta_core_nav_q_meta (event log)
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional

from src.data.signals.beta_core_q_overlay import (
    INCEPTION_ID,
    default_thresholds,
    env_thresholds,
    is_vdb_failure,
    derive_q_override,
    QOverrideState,
)

_log = logging.getLogger("beta_core_q_hook")


# ── C2 ⓠ hook config (frozen for first ship; overridable by env) ─────────────
@dataclass
class QHookConfig:
    """Hook configuration. Frozen defaults; env overrides per beta_core_q_overlay."""
    enter_q_zero_thr: float
    exit_q_zero_thr: float
    vdb_matcher_live: bool                                       # False → always q_override=1.0
    inception_id: str = INCEPTION_ID


def q_hook_config() -> QHookConfig:
    """Read the current hook config (env overrides honored)."""
    enter, exit_ = env_thresholds()
    return QHookConfig(
        enter_q_zero_thr=enter,
        exit_q_zero_thr=exit_,
        vdb_matcher_live=False,                                  # toggle on Mac-side wire
    )


# ── Pure-function hook (offline-testable) ────────────────────────────────────
def compute_q_hook_state(
    today: dt.date,
    gross: float,
    regime: str | None,
    smoothed_distance: float | None,
    enter_q_up_frac: float = 0.0,
    vdb_failure: bool = False,
    vdb_matcher_live: bool = False,
) -> QOverrideState:
    """Compute the q_override state for today.

    Pure function — caller passes smoothed_distance, enter_q_up_frac, and
    vdb_failure explicitly. The hook does NOT call Supabase or any network.

    On any failure (or first-ship before VDB matcher is live), the result is
    q_override = 1.0 (baseline-equivalent). This is per §C2-SHIP-SPEC §4:
    freeze + fall back to 1.0, NEVER hardcode 0.
    """
    cfg = q_hook_config()
    enter, exit_ = cfg.enter_q_zero_thr, cfg.exit_q_zero_thr
    if not vdb_matcher_live:
        # First-ship behavior: no matcher = no override. Baseline strictly preserved.
        return QOverrideState(
            mark_date=today, q_override=1.0,
            vdb_distance=None, smoothed_distance=None,
            enter_q_zero_thr=enter, exit_q_zero_thr=exit_,
            trigger="baseline_vdb_matcher_offline",
            vdb_failure=False,
        )
    if is_vdb_failure(smoothed_distance) or vdb_failure:
        return derive_q_override(
            mark_date=today, smoothed_distance=smoothed_distance,
            enter_q_zero_thr=enter, exit_q_zero_thr=exit_,
            enter_q_up_frac=enter_q_up_frac, baseline=1.0,
            vdb_failure=True,
        )
    return derive_q_override(
        mark_date=today, smoothed_distance=smoothed_distance,
        enter_q_zero_thr=enter, exit_q_zero_thr=exit_,
        enter_q_up_frac=enter_q_up_frac, baseline=1.0,
    )


# ── I/O wrapper (Supabase write, called by mark_and_rebalance) ───────────────
async def write_q_overlay_row(
    today: dt.date,
    q_state: QOverrideState,
    baseline_gross: float,
    nav: float,
    benchmark_nav: float,
    daily_return: float,
    excess_return: float,
    inception_id: str = INCEPTION_ID,
) -> bool:
    """Durable write to `beta_core_nav_q`. Mirrors `_write` shape from beta_core_paper.

    Returns True on success, False on failure. The C1 mark flow treats a False
    return as a transient failure (NOT a hard error) — the ① baseline is
    independent and keeps running.
    """
    from src.api.store import supabase_insert_table
    gross_total = round(baseline_gross * q_state.q_override, 6)
    row = {
        "mark_date": today.isoformat(),
        "inception_id": inception_id,
        "q_override": q_state.q_override,
        "vdb_distance": (None if q_state.smoothed_distance is None
                          or q_state.smoothed_distance != q_state.smoothed_distance
                         else round(q_state.smoothed_distance, 6)),
        "enter_q_zero_thr": q_state.enter_q_zero_thr,
        "exit_q_zero_thr": q_state.exit_q_zero_thr,
        "baseline_gross": round(baseline_gross, 6),
        "gross_total": gross_total,
        "nav": round(nav, 6),
        "benchmark_nav": round(benchmark_nav, 6),
        "daily_return": round(daily_return, 6),
        "excess_return": round(excess_return, 6),
        "note": f"trigger={q_state.trigger}",
    }
    try:
        ok = await supabase_insert_table("beta_core_nav_q", [row])
        # Same Lesson #107 / S-105 protection: a write that returns False is
        # NOT the same as a write that ran. The C1 baseline is independent,
        # but a missing q row is a silent delta that the next agent will not
        # see, so log it loudly.
        if not ok:
            _log.error("[beta_core_q] Q-OVERLAY WRITE REJECTED for %s — "
                       "supabase_insert_table returned False", today.isoformat())
        return bool(ok)
    except Exception as e:
        _log.error("[beta_core_q] Q-OVERLAY WRITE FAILED for %s: %s",
                    today.isoformat(), e)
        return False


async def log_q_meta_event(
    today: dt.date,
    event_type: str,                                             # vdb_failure | dwell_extension | q_override_fix
    q_state: QOverrideState,
    reason: str,
    inception_id: str = INCEPTION_ID,
) -> bool:
    """Append a row to `beta_core_nav_q_meta`. Loud failure on write reject."""
    from src.api.store import supabase_insert_table
    row = {
        "mark_date": today.isoformat(),
        "inception_id": inception_id,
        "event_type": event_type,
        "q_override": q_state.q_override,
        "vdb_distance": (None if q_state.smoothed_distance is None
                          or q_state.smoothed_distance != q_state.smoothed_distance
                         else round(q_state.smoothed_distance, 6)),
        "reason": reason,
    }
    try:
        ok = await supabase_insert_table("beta_core_nav_q_meta", [row])
        if not ok:
            _log.error("[beta_core_q] META EVENT WRITE REJECTED for %s/%s",
                       today.isoformat(), event_type)
        return bool(ok)
    except Exception as e:
        _log.error("[beta_core_q] META EVENT WRITE FAILED for %s/%s: %s",
                    today.isoformat(), event_type, e)
        return False
