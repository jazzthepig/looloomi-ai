"""
beta_core_q_overlay.py — C2 ⓠ regime override layer helpers (Seth, 2026-08-12).

Per §C2-SHIP-SPEC 2026-08-12 (Minimax-C contract):
  ⓠ = §RETURN_HIERARCHY ⓪ OVERRIDE 凌驾 ①②③④
  gross_total[t] = beta_capture_gross[t] × q_override[t]
  q_override ∈ {0.0, 0.5, 1.0, 1.3}, default 1.0

This module owns the PURE-FUNCTION helpers. The live endpoint
(/internal/beta-core-clock-q) and the ⓠ hook on beta_core_paper.py wire
the helpers to I/O. Helpers are offline-testable: no live Supabase, no
live network.

The C2 ⓠ overlay does NOT mutate the ① baseline. Curve includes both:
  - beta_core_nav     (no ⓠ)
  - beta_core_nav_q   (with ⓠ, 60-day clock, parallel)
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd


# ── Frozen constants (per §C2-SHIP-SPEC §8) ───────────────────────────────────
SCHEMA_VERSION = 1                                              # bumped on edit
INCEPTION_ID = "c2_q_v1"                                        # ship 2026-09-15
DAY_60 = "2026-11-14"                                           # 60-day clock

ENTER_Q_ZERO_THRESHOLD_DEFAULT = 0.85
EXIT_Q_ZERO_THRESHOLD_DEFAULT = 0.65
HYSTERESIS_GAP = 0.20
DWELL_DAYS = 5
ALLOWED_Q = (0.0, 0.5, 1.0, 1.3)

# ENTER_Q_UP filter: needs M-WO-1 r77_fwd_5d_alpha_pct history (D2 push backfill).
# Per §C2-SHIP-SPEC §8: this is NOT yet calibrated; defaults listed for reference.
ENTER_Q_UP_OUTCOME_THRESHOLD_DEFAULT = 0.05
ENTER_Q_UP_MIN_NEIGHBORS_DEFAULT = 5


# ── q_override derivation (pure) ─────────────────────────────────────────────
@dataclass
class QOverrideState:
    """One day's q_override state. Pure dataclass — no I/O."""
    mark_date: date
    q_override: float                                            # {0.0, 0.5, 1.0, 1.3}
    vdb_distance: float | None                                   # raw distance, NaN ok
    smoothed_distance: float | None
    enter_q_zero_thr: float
    exit_q_zero_thr: float
    trigger: str                                                 # baseline | zero_zone | half_zone | up_zone
    vdb_failure: bool                                            # True → q_override should be 1.0


def derive_q_override(
    mark_date: date,
    smoothed_distance: float | None,
    enter_q_zero_thr: float,
    exit_q_zero_thr: float,
    enter_q_up_frac: float = 0.0,                                # 0.0 if no VDB k=5 outcome
    baseline: float = 1.0,
    vdb_failure: bool = False,
) -> QOverrideState:
    """Compute q_override per §C2-SHIP-SPEC §1-§2.

    Priority of override:
      1. vdb_failure → q_override = 1.0 (freeze + fall back, per §C2-SHIP-SPEC §4)
      2. distance > enter_q_zero_thr → 0.0
      3. distance < exit_q_zero_thr  → 1.0
      4. mid-band: 0.5 (or 1.3 if enter_q_up_frac > 0.5, meaning ≥3 of 5 neighbors
         have r77_fwd_5d_alpha_pct > +5%)
    """
    if vdb_failure:
        return QOverrideState(
            mark_date=mark_date, q_override=baseline,
            vdb_distance=None, smoothed_distance=None,
            enter_q_zero_thr=enter_q_zero_thr, exit_q_zero_thr=exit_q_zero_thr,
            trigger="baseline_vdb_failure", vdb_failure=True,
        )
    if smoothed_distance is None or not math.isfinite(smoothed_distance):
        return QOverrideState(
            mark_date=mark_date, q_override=baseline,
            vdb_distance=None, smoothed_distance=None,
            enter_q_zero_thr=enter_q_zero_thr, exit_q_zero_thr=exit_q_zero_thr,
            trigger="baseline_missing", vdb_failure=False,
        )
    if smoothed_distance > enter_q_zero_thr:
        q = 0.0
        trig = "zero_zone"
    elif smoothed_distance < exit_q_zero_thr:
        q = 1.0
        trig = "one_zone"
    else:
        q = 1.3 if enter_q_up_frac > 0.5 else 0.5
        trig = "up_zone" if q > 1.0 else "half_zone"
    return QOverrideState(
        mark_date=mark_date, q_override=q,
        vdb_distance=None, smoothed_distance=float(smoothed_distance),
        enter_q_zero_thr=enter_q_zero_thr, exit_q_zero_thr=exit_q_zero_thr,
        trigger=trig, vdb_failure=False,
    )


# ── Dwell filter (5d median) ────────────────────────────────────────────────
def apply_dwell_filter(
    distances: pd.Series,
    dwell_days: int = DWELL_DAYS,
) -> pd.Series:
    """Median filter over a rolling window. NaN preserved by min_periods=1.

    Per M-WO-7.1: median run 19d > 5d SHIP floor. Single-day VDB jumps
    are smoothed out by the 5d median.
    """
    if not isinstance(distances.index, pd.DatetimeIndex):
        raise ValueError("distances.index must be pd.DatetimeIndex")
    return distances.rolling(window=dwell_days, min_periods=1).median()


# ── Continuity state (mirrors beta_core_paper.continuity_state shape) ────────
@dataclass
class ClockQState:
    """Returned to /internal/beta-core-clock-q. Schema-stable for the
    C2 ⓠ overlay's 60-day life. JSON-serializable."""
    configured: bool
    marks: int = 0
    inception: str | None = None
    last_mark: str | None = None
    days_since_mark: int = 0
    missing_days: int = 0
    gate_days_remaining: int = 60
    started: bool = False
    stalled: bool = True                                         # true until first mark
    vdb_failure_count: int = 0
    note: str = ""


def clock_q_continuity(
    rows: Sequence[dict],
    vdb_failure_count: int = 0,
    today: date | None = None,
) -> ClockQState:
    """Compute the ⓠ overlay's continuity state from a sequence of marked rows.

    `rows` is a list of dicts with at least `mark_date` (ISO string). No I/O.

    Mirrors beta_core_paper.continuity_state() shape so the two endpoints
    share a consumer contract.
    """
    if today is None:
        today = date.today()
    if not rows:
        return ClockQState(
            configured=True, marks=0, started=False,
            gate_days_remaining=60,
            note="ⓠ overlay has never marked — the clock is NOT running",
        )
    days = sorted({date.fromisoformat(r["mark_date"]) for r in rows})
    span = (days[-1] - days[0]).days + 1
    since = (today - days[-1]).days
    return ClockQState(
        configured=True, marks=len(days),
        inception=days[0].isoformat(), last_mark=days[-1].isoformat(),
        days_since_mark=since,
        missing_days=max(0, span - len(days)),
        gate_days_remaining=max(0, 60 - len(days)),
        started=True,
        stalled=since >= 2,
        vdb_failure_count=vdb_failure_count,
        note="",
    )


# ── State-as-of computation (pure) ───────────────────────────────────────────
def state_as_of(state: ClockQState) -> dict:
    """Serialize ClockQState for the endpoint. Pure: no side effects."""
    return asdict(state)


# ── VDB failure detector (pure) ──────────────────────────────────────────────
def is_vdb_failure(
    distance: float | None,
    rpc_status: str | None = None,
) -> bool:
    """Detect VDB failure per §C2-SHIP-SPEC §4.

    Failure modes:
      - distance is None (no match)
      - distance is NaN (sparse / I1)
      - rpc_status is not OK (network / DB failure)
    """
    if rpc_status is not None and rpc_status != "ok":
        return True
    if distance is None:
        return True
    if not math.isfinite(distance):
        return True
    return False


# ── DEFAULT THRESHOLDS (sourced from C2 spec §8) ─────────────────────────────
def default_thresholds() -> tuple[float, float]:
    """Spec defaults. Sourced from §C2-SHIP-SPEC §8.

    The data-calibrated values from `scripts/backtest_q_override.py` MAY
    differ. This is the data-grounded proposal vs the spec anchor.
    """
    return ENTER_Q_ZERO_THRESHOLD_DEFAULT, EXIT_Q_ZERO_THRESHOLD_DEFAULT


# ── env helpers (kept thin; the heavy I/O lives in beta_core_paper hook) ────
def env_thresholds() -> tuple[float, float]:
    """Read optional env-var overrides; fall back to spec defaults.

    `C2_ENTER_Q_ZERO` and `C2_EXIT_Q_ZERO` allow Jazz to override
    the spec defaults without a code change. Bounds-checked: must be
    in [0.0, 1.0]; ENTER MUST exceed EXIT (hysteresis gap ≥ 0.05).
    """
    try:
        enter = float(os.environ.get("C2_ENTER_Q_ZERO", ENTER_Q_ZERO_THRESHOLD_DEFAULT))
        exit_ = float(os.environ.get("C2_EXIT_Q_ZERO", EXIT_Q_ZERO_THRESHOLD_DEFAULT))
    except (TypeError, ValueError):
        return default_thresholds()
    if not (0.0 <= enter <= 1.0 and 0.0 <= exit_ <= 1.0):
        return default_thresholds()
    if enter - exit_ < 0.05:
        return default_thresholds()
    return enter, exit_
