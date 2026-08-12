"""
beta_core_size.py — C3 conviction-size 2D table helpers (Seth, 2026-08-12).

Per §C3-SHIP-SPEC 2026-08-12 (Minimax-C contract):
  size[t] = lookup_2d(regime_band[t], signal_band[t]) × q_override[t]
  size[t] ∈ [0, 1.3] (clipped)

This module owns the 2D size table and the band-mapping helpers. The hook
integration lives in `beta_core_size_hook.py`. All functions are pure:
no I/O, no live Supabase, no live network.

DESIGN PRINCIPLES (per §C3 §1):
  - regime band ↑ → size ↓ (VDB far = unfamiliar = cut exposure)
  - signal band ↑ → size ↑ (strong signal = lean in)
  - extreme corner (regime 5, signal 1) = 0.10 (almost zero)
  - extreme corner (regime 1, signal 5) = 1.30 (max possible)
  - center cell (regime 3, signal 3) = 0.85 (default baseline)

DEPENDENCIES:
  - C2 ⓠ layer (q_override) is REQUIRED. Without C2, the size hook degrades
    to q_override = 1.0 — the C3 table still works, but the regime×signal
    2D effect is the only thing that varies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# ── Frozen constants (per §C3-SHIP-SPEC §1) ────────────────────────────────────
SCHEMA_VERSION = 2                                              # bumped: table externalised (S-151)
INCEPTION_ID = "c3_size_v1"                                     # ship 2026-09-10
DAY_60 = "2026-11-09"                                           # 60-day clock

N_BANDS = 5
SIZE_CLIP_MIN = 0.0
SIZE_CLIP_MAX = 1.3
SIZE_AUDIT_THRESHOLD_DEVIATION = 0.30                           # Day 30: drift guard
SIZE_AUDIT_THRESHOLD_FLIPS = 3                                  # Day 45: cell flip guard

# Bands the missing-data path lands on. Declared here so the validator can
# check what the NO-INFORMATION case actually costs (see strategy_params).
NAN_REGIME_BAND = 3
NAN_SIGNAL_BAND = 1


# ── The 2D size table now lives in `strategy_params` (S-151) ──────────────────
# TWO reasons, both load-bearing.
#
# 1. It IS the mined edge (Jazz, 2026-08-12). Everything else in this file is
#    plumbing; the 25 numbers are the research output, and they no longer ship
#    inside the repo. NOTE the module stays tracked — `src/api/main.py` imports
#    it and Railway deploys from git, so gitignoring it would 500 the endpoint.
#    The edge leaves as a PARAMETER, never as an import target.
#
# 2. **The table in this file was inverted on both axes.** Measured 2026-08-12:
#
#        lookup_size(regime=5 out-of-distribution, signal=1 weakest)  = 1.30
#        lookup_size(regime=1 in-distribution,     signal=5 strongest) = 0.10
#
#    exactly backwards from this module's own docstring, which says regime ↑ →
#    size ↓ and signal ↑ → size ↑. Centre cell (3,3)=0.85 was right — it is the
#    fixed point of a transpose, so spot-checking "the default baseline"
#    passed. With BOTH inputs missing the table returned **1.20**, and
#    `beta_core_size_hook` documented that as the intended first-ship baseline.
#
#    The tell is in this file, not outside it: `regime_band()` warns against
#    defaulting to band 1 because it "would look like a strong daily claim",
#    and `signal_band()` warns against band 5 because it "would look like a
#    conviction". BOTH warnings are only coherent if band 1 regime and band 5
#    signal are the LARGE-size ends. Under the shipped table they were the
#    small ones. The band functions were written against a correctly-oriented
#    table; the table and its smoke tests were not.
#
# So the fallback below is NEUTRAL, not "the good values": all cells 1.0, which
# degenerates C3 to the ① baseline. A fallback that reproduced the edge would
# defeat reason 1 and hide reason 2.
NEUTRAL_SIZE_TABLE: tuple[tuple[float, ...], ...] = tuple(
    tuple(1.0 for _ in range(N_BANDS)) for _ in range(N_BANDS)
)

_FALLBACK_PARAMS = {
    "size_table_2d": [list(r) for r in NEUTRAL_SIZE_TABLE],
    "size_clip_min": SIZE_CLIP_MIN,
    "size_clip_max": SIZE_CLIP_MAX,
    "nan_regime_band": NAN_REGIME_BAND,
    "nan_signal_band": NAN_SIGNAL_BAND,
}


def active_params():
    """Current C3 parameter set, with provenance. A payload that violates the
    behavioural invariants CANNOT LOAD — it is rejected and this returns the
    neutral fallback with `source='db_rejected_fallback'`, which is stamped
    into the NAV row. See `strategy_params` for why validation is behavioural
    (monotonicity, no-leverage-on-no-information) rather than value-equality:
    a frozen-value check would have passed the day the table was transposed,
    because it was transposed before it was frozen."""
    from src.data.signals.strategy_params import NS_C3_SIZE, load
    return load(NS_C3_SIZE, _FALLBACK_PARAMS, fallback_version=0)


def active_size_table() -> tuple[tuple[float, ...], ...]:
    p = active_params()
    return tuple(tuple(float(x) for x in row) for row in p.values["size_table_2d"])


# ── Band quantization (pure) ────────────────────────────────────────────────
def regime_band(vdb_distance: float | None) -> int:
    """Map VDB distance ∈ [0, 1] to regime_band ∈ {1, 2, 3, 4, 5}.

    Per §C3 §1:
      band 1: [0.0, 0.20]  ← in-distribution
      band 2: [0.20, 0.40]
      band 3: [0.40, 0.60]
      band 4: [0.60, 0.80]
      band 5: [0.80, 1.00]  ← out-of-distribution

    NaN/None → band 3 (mid-tail, default, conservative). Per I1: don't
    silently default to band 1 (in-distribution) where missing data would
    look like a strong daily claim.
    """
    if vdb_distance is None:
        return 3
    try:
        d = float(vdb_distance)
    except (TypeError, ValueError):
        return 3
    if d != d:                                                  # NaN check
        return 3
    if d < 0.0:
        return 1
    if d >= 1.0:
        return 5
    # Quantile-based: 0.0-0.20 → 1, 0.20-0.40 → 2, ..., 0.80-1.0 → 5
    return min(5, max(1, int(d * 5.0) + 1))


def signal_band(signal_strength: float | None) -> int:
    """Map signal_strength ∈ [0, 1] to signal_band ∈ {1, 2, 3, 4, 5}.

    Per §C3 §1: signal_strength = 0.5 × R62 fragility + 0.5 × VDB outcome
    NaN/None → band 1 (very weak signal). Per I1: don't silently default to
    band 5 (strong signal) where missing data would look like a conviction.
    """
    if signal_strength is None:
        return 1
    try:
        s = float(signal_strength)
    except (TypeError, ValueError):
        return 1
    if s != s:
        return 1
    if s < 0.0:
        return 1
    if s >= 1.0:
        return 5
    return min(5, max(1, int(s * 5.0) + 1))


# ── 2D table lookup (pure) ──────────────────────────────────────────────────
def lookup_size(regime: int, signal: int,
                table: tuple[tuple[float, ...], ...] | None = None) -> float:
    """Lookup size in the 5×5 table. Bounds-checked.

    `table` is injectable so the pure path stays pure and testable; when
    omitted it is loaded (and validated) from `strategy_params`. Callers
    marking the book should fetch it ONCE per mark via `active_params()` and
    pass it in, so a single day's mark cannot straddle two parameter versions.
    """
    if not (1 <= regime <= N_BANDS):
        raise ValueError(f"regime_band out of bounds: {regime}")
    if not (1 <= signal <= N_BANDS):
        raise ValueError(f"signal_band out of bounds: {signal}")
    t = table if table is not None else active_size_table()
    return t[regime - 1][signal - 1]


# ── Size computation (pure) ─────────────────────────────────────────────────
@dataclass
class Size2DState:
    """One day's size state. Pure dataclass — no I/O."""
    mark_date: str                                              # ISO date string
    regime_band: int
    signal_band: int
    raw_table_size: float                                       # pre-clip from 2D table
    q_override: float                                           # from C2 ⓠ layer
    size_final: float                                           # clipped
    clipped: bool                                               # True if clip engaged
    signal_strength: float | None
    vdb_distance: float | None
    # Provenance (S-151). NOT diagnostics — these go into the NAV row. A
    # forward record that cannot say which parameters produced it is a forward
    # record you cannot defend 60 days later.
    param_version: int = 0
    param_source: str = "code_fallback"


def compute_size(
    mark_date: str,
    vdb_distance: float | None,
    signal_strength: float | None,
    q_override: float,
    clip_min: float = SIZE_CLIP_MIN,
    clip_max: float = SIZE_CLIP_MAX,
    params=None,
) -> Size2DState:
    """Compute size[t] per §C3 §1-§2.

    size[t] = lookup_2d(regime_band, signal_band) × q_override
    clipped to [clip_min, clip_max] (default [0, 1.3]).

    Q_override defaults to 1.0 (C2 ⓠ offline / first-ship). When C2 is live,
    the q_override value is passed in explicitly.

    ONE parameter fetch per call, carried into the returned state: a mark that
    read the table twice could straddle two versions and the row would name
    only one of them.
    """
    p = params if params is not None else active_params()
    table = tuple(tuple(float(x) for x in row) for row in p.values["size_table_2d"])
    r = regime_band(vdb_distance)
    s = signal_band(signal_strength)
    raw = lookup_size(r, s, table=table) * q_override
    size_clipped = max(clip_min, min(clip_max, raw))
    return Size2DState(
        mark_date=mark_date,
        regime_band=r,
        signal_band=s,
        raw_table_size=round(raw, 6),
        q_override=q_override,
        size_final=round(size_clipped, 6),
        clipped=bool(size_clipped != raw),
        signal_strength=signal_strength,
        vdb_distance=vdb_distance,
        param_version=p.version,
        param_source=p.source,
    )


# ── Signal strength (pure) ──────────────────────────────────────────────────
def compute_signal_strength(
    r62_detector_fragility: float | None,
    vdb_match_outcome_strength: float | None,
) -> float | None:
    """Per §C3 §1: signal_strength = 0.5 × R62 fragility + 0.5 × VDB outcome.

    Both inputs ∈ [0, 1]. If either is None, returns the other; if both are
    None, returns None (will be quantized to band 1 by signal_band()).
    """
    r62 = _coerce_unit(r62_detector_fragility)
    vdb = _coerce_unit(vdb_match_outcome_strength)
    if r62 is None and vdb is None:
        return None
    if r62 is None:
        return vdb
    if vdb is None:
        return r62
    return 0.5 * r62 + 0.5 * vdb


def _coerce_unit(x: float | None) -> float | None:
    """Coerce x to [0, 1] range; NaN/None → None."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:                                                  # NaN
        return None
    return max(0.0, min(1.0, v))


# ── Day-30 drift guard (pure) ───────────────────────────────────────────────
def drift_from_baseline(size_distribution: Sequence[float], baseline: float = 1.0) -> float:
    """Day 30 guard: size distribution mean / baseline - 1.

    Per §C3 §3: |drift| > 0.30 → re-tighten cell range. The guard fires
    when the C3 size adjustment is consistently pushing the book far from
    the 1.0 default — a sign that the 2D table is too aggressive.
    """
    if not size_distribution:
        return 0.0
    mean_size = sum(size_distribution) / len(size_distribution)
    if baseline == 0:
        return 0.0
    return abs(mean_size / baseline - 1.0)


def cell_flip_audit(recent_sizes: Sequence[float],
                    flip_threshold: int = SIZE_AUDIT_THRESHOLD_FLIPS) -> int:
    """Day 45 guard: count of cell flips in the last 5 days.

    Per §C3 §3: > 3 flips → re-tighten cell values. A cell flip is a
    boundary crossing between two distinct size values, NOT necessarily
    between two distinct cells — but for the 5-day audit, the input is
    expected to be one size per day.
    """
    if len(recent_sizes) < 2:
        return 0
    flips = 0
    for i in range(1, len(recent_sizes)):
        if abs(recent_sizes[i] - recent_sizes[i - 1]) > 1e-9:
            flips += 1
    return flips
