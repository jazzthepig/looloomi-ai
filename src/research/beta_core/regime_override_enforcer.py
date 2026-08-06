"""ⓠ REGIME OVERRIDE Enforcer — first cut (Seth, 2026-08-06).

Spec:  docs/REGIME_OVERRIDE_SPEC.md, docs/RISK_ALLOCATOR_SPEC.md §6, HIGH_DIM_ONTOLOGY.md §5b-bis.

Layer position (per §HIGH_DIM_ONTOLOGY §5b-bis):
    ⓠ REGIME OVERRIDE
        ↓ (capping, scaling, NOT signal generation)
    ① BETA CAPTURE   ← baseline_weights from M-WO-A
        ↓
    ② BETA+
        ↓
    ③ BETA MULTIPLIER
        ↓
    ④ PURE ALPHA

This module is the production-shape wrapper around the research-side
`m_wo_q_o1_stablecoin_gate.assign_band_hysteresis` — the function that
the live book calls daily to compute today's regime override, given
yesterday's stablecoin-supply signal.

Why this matters (per architecture audit 2026-08-02):
    ② / ③ / ④ have shipped product paths. ① has 1 candidate shape validated.
    ⓠ has the spec complete (REGIME_OVERRIDE_SPEC + RISK_ALLOCATOR_SPEC §6)
    BUT no production enforcer — only a research backtest harness.
    Finding #2 of the architecture audit: this is the most-needed layer.

PIT safety:
    `apply_regime_override_series(baseline, cap_series, pit_lag_bars=1)` lags
    the cap by 1 bar so the regime applied at day t uses the cap that was
    public at the close of bar t-1 (no look-ahead).

Behavior:
    baseline_weights @ day t (long-only ① layer output)
    × exposure_cap @ day t-1 (from assign_band_hysteresis)
    → renormalize so total gross == cap exactly

Allowed caps (from m_wo_q EXPOSURE_BANDS_V1):
    CRISIS      → 0.0   (shelter; v1 disables naked short)
    CONTRACTION → 0.5
    NEUTRAL     → 1.0   (pass-through identity)
    EXPANSION   → 1.0
    HOT         → 1.3

Out of scope here:
    - computing the stablecoin signal (m_wo_q_o1_stablecoin_gate.compute_o1_signal)
    - the hysteresis state machine (m_wo_q_o1_stablecoin_gate.assign_band_hysteresis)
    - the underlying DeFiLlama fetch (m_wo_q_o1_stablecoin_gate.load_stablecoin_history)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.research.validation.m_wo_q_o1_stablecoin_gate import (  # noqa: F401
    EXPOSURE_BANDS_V1,
    compute_o1_signal,
    assign_band_hysteresis,
)


# Frozen spec values, re-exported for production-side consumers.
DEFAULT_PIT_LAG = 1  # bar(s); PIT safety
# Allowed caps are the UNIQUE values from EXPOSURE_BANDS_V1, sorted ascending.
# Note: NEUTRAL and EXPANSION both map to 1.0 — by design (the system holds
# 1.0 in either band; what changes between them is the hysteresis path).
ALLOWED_CAPS: tuple[float, ...] = tuple(sorted(set(EXPOSURE_BANDS_V1.values())))
BAND_NAMES: tuple[str, ...] = tuple(EXPOSURE_BANDS_V1.keys())


@dataclass(frozen=True)
class RegimeOverride:
    """Single-day regime override decision — what the live book reads."""
    as_of_date: pd.Timestamp
    band: str                    # one of BAND_NAMES
    exposure_cap: float          # one of ALLOWED_CAPS
    raw_signal: float            # stablecoin 28d Δ decimal (NaN-aware)

    def __post_init__(self):
        if self.band not in BAND_NAMES:
            raise ValueError(f"band '{self.band}' not in {BAND_NAMES}")
        if self.exposure_cap not in ALLOWED_CAPS:
            raise ValueError(
                f"exposure_cap {self.exposure_cap} not in {ALLOWED_CAPS} "
                f"(per REGIME_OVERRIDE_SPEC §3 v1)"
            )


def validate_cap(cap: float) -> None:
    """Assert cap ∈ ALLOWED_CAPS. Raises ValueError with the allowed set."""
    if cap not in ALLOWED_CAPS:
        raise ValueError(
            f"exposure_cap {cap} not in allowed set {ALLOWED_CAPS}. "
            f"Allowed values come from EXPOSURE_BANDS_V1 (REGIME_OVERRIDE_SPEC §3 v1)."
        )


def apply_regime_override(baseline_weights: pd.Series, exposure_cap: float) -> pd.Series:
    """Apply regime override to a SINGLE-DAY baseline weights vector.

    Parameters
    ----------
    baseline_weights : pd.Series
        Indexed by symbol. Long-only ① layer weights summing to ≈1.0.
        (If sum ≠ 1.0, the override still scales + renormalizes so that
        total gross == exposure_cap exactly.)
    exposure_cap : float
        One of ALLOWED_CAPS = (0.0, 0.5, 1.0, 1.3).

    Returns
    -------
    pd.Series
        Same index as input, scaled so |sum(w)| == exposure_cap.

    Behavior by cap
    ---------------
    cap = 1.0 → identity (NEUTRAL pass-through)
    cap = 0.5 → half the book (CONTRACTION; defensive)
    cap = 1.3 → 1.3× the book (HOT; offensive)
    cap = 0.0 → all zeros (CRISIS shelter; v1 disables naked short)

    Notes
    -----
    The override caps GROSS, not net. For the long-only ① baseline this is
    equivalent to scaling book weight. A future ② sleeve that introduces a
    short side will need a separate net-cap branch — see HIGH_DIM_ONTOLOGY
    §5b-bis "exposure range [−0.3x, 1.3x]" which is NOT implemented here
    because v1 EXPOSURE_BANDS_V1 has CRISIS=0.0, not -0.3.
    """
    validate_cap(exposure_cap)
    if not isinstance(baseline_weights, pd.Series):
        raise TypeError(
            f"baseline_weights must be pd.Series, got "
            f"{type(baseline_weights).__name__}"
        )
    if baseline_weights.empty:
        return baseline_weights.copy()

    scaled = baseline_weights * exposure_cap
    current_gross = float(scaled.abs().sum())
    if current_gross > 0:
        scaled = scaled * (exposure_cap / current_gross)
    return scaled


def apply_regime_override_series(
    baseline_weights: pd.DataFrame,
    exposure_cap_series: pd.Series,
    pit_lag_bars: int = DEFAULT_PIT_LAG,
) -> pd.DataFrame:
    """Apply regime override across a daily weights panel.

    Parameters
    ----------
    baseline_weights : pd.DataFrame
        Indexed by trade_date, columns=symbol, values=① layer weights.
    exposure_cap_series : pd.Series
        Indexed by trade_date, values in ALLOWED_CAPS. Typically the
        `exposure_cap` output of `assign_band_hysteresis(signal)`.
    pit_lag_bars : int
        PIT safety: cap at day t uses the value from day t - pit_lag_bars.
        Default 1 (matches spec §4 "applied to portfolio on day t+1").

    Returns
    -------
    pd.DataFrame
        Same shape as baseline_weights. Where exposure_cap is NaN
        (window before the signal starts, or signal dropped), the
        baseline passes through unchanged.
    """
    if not isinstance(baseline_weights, pd.DataFrame):
        raise TypeError(
            f"baseline_weights must be pd.DataFrame, got "
            f"{type(baseline_weights).__name__}"
        )
    if not isinstance(exposure_cap_series, pd.Series):
        raise TypeError(
            f"exposure_cap_series must be pd.Series, got "
            f"{type(exposure_cap_series).__name__}"
        )
    if pit_lag_bars < 0:
        raise ValueError(f"pit_lag_bars must be >= 0, got {pit_lag_bars}")

    lagged = exposure_cap_series.shift(pit_lag_bars)
    rows = {}
    for d, w in baseline_weights.iterrows():
        cap = lagged.get(d, np.nan)
        if pd.isna(cap):
            rows[d] = w.copy()
        else:
            rows[d] = apply_regime_override(w, float(cap))
    return pd.DataFrame.from_dict(rows, orient="index").reindex(baseline_weights.index)


def band_for_cap(cap: float) -> str | None:
    """Inverse of EXPOSURE_BANDS_V1: cap → band name. None if cap not in allowed set."""
    for band, c in EXPOSURE_BANDS_V1.items():
        if c == cap:
            return band
    return None


# ── DECISION_INPUTS contract (per tests/test_strategy_discipline.py) ────────
DECISION_INPUTS = {
    "regime": "risk_meter",
    "universe": "m_wo_a_beta_capture_baseline",
    "weights": "regime_scaler_5band",
    "timing": "5band_hysteresis_pit_lag1d",
}
