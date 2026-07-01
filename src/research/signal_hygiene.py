"""
Signal hygiene — measure strategy capacity and trading frictions.

Pre-deployment sanity checks before scaling capital. These guard against
backtest overfit caused by unrealistically low slippage, infinite capacity,
or instant fills.

Metrics:
- Turnover: how often positions change. High turnover = high fee drag.
- Capacity: order-of-magnitude estimate of the strategy's max AUM
  before its edge decays (Almgren-Chriss style).
- Slippage BPS: estimated slippage per fill based on order size vs
  average daily volume.

These numbers are reported per backtest so reviewers know what they're
trusting. Capacity matters: a strategy that only works at $10k AUM
is not institutional.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class HygieneReport:
    """Signal hygiene assessment for one strategy backtest."""
    # Turnover
    n_round_trips: int
    avg_hold_bars: float
    turnover_per_year: float     # round-trips per year
    # Capacity
    estimated_capacity_usd: float    # AUM at which slippage = gross edge
    capacity_ratio: float            # capacity / tested AUM
    # Slippage model inputs (per pair)
    avg_volume_usd_per_bar: float
    estimated_slippage_bps_per_fill: float
    # Verdict
    hygiene_grade: str   # "OK" | "WATCH" | "OVERFIT"
    notes: str = ""

    def summary(self) -> str:
        return (
            f"[{self.hygiene_grade}] turnover={self.turnover_per_year:.1f}/yr "
            f"hold={self.avg_hold_bars:.1f} bars "
            f"capacity≈${self.estimated_capacity_usd:,.0f} "
            f"slippage≈{self.estimated_slippage_bps_per_fill:.1f}bps  "
            f"ratio={self.capacity_ratio:.1f}x"
        )


def turnover_metrics(
    n_round_trips: int,
    avg_hold_bars: float,
    bars_per_year: int,
) -> tuple[float, float]:
    """Compute turnover per year from basic counters.

    Turnover (round-trips per year) = bars_per_year / avg_hold_bars.
    This represents maximum churn: if you hold every position for the same
    average period, this many round-trips per year.

    Note: the result depends only on `avg_hold_bars`, not `n_round_trips`,
    because turnover is a rate (frequency) not a count. The `n_round_trips`
    arg is kept for symmetry and downstream logging.

    Args:
        n_round_trips: total closed round-trips.
        avg_hold_bars: average holding period in bars.
        bars_per_year: total bars per year at the strategy's timeframe.

    Returns:
        (turnover_per_year, percent_time_in_market) where the second is
        always 1.0 (placeholder for future exposure-aware reporting).
    """
    if avg_hold_bars <= 0:
        return 0.0, 0.0
    turnover_per_year = bars_per_year / avg_hold_bars
    return float(turnover_per_year), 1.0


def capacity_estimate(
    avg_volume_usd_per_bar: float,
    position_size_usd: float,
    signal_edge_bps: float,
    market_impact_k: float = 0.1,
    max_pct_volume: float = 0.01,
) -> float:
    """Estimate the AUM at which market impact eats the signal edge.

    Standard square-root impact model (Kyle 1985, Almgren-Chriss):

        impact_return = k * sqrt(Q / V)

    where Q is order size, V is volume, and k is Kyle's lambda in
    return-form (e.g. 0.1 means sqrt(Q/V)=1 → impact = 10% return).

    Set impact = edge (in return form) and solve for Q:

        capacity_usd = V * (edge_return / k) ** 2

    Args:
        avg_volume_usd_per_bar: avg USD volume per bar.
        position_size_usd: tested position size (unused, kept for symmetry).
        signal_edge_bps: expected gross edge per round-trip, in basis points
            (e.g. 50 = 0.5% gross edge).
        market_impact_k: Kyle's lambda in return-form (default 0.1).
        max_pct_volume: max fraction of bar volume we consume. Default 1% is
            conservative; an additional safety buffer that divides capacity
            by max_pct_volume (so the reported capacity is "AUM at which we
            would use max_pct_volume of bar volume").

    Returns:
        Estimated capacity in USD. Above this, edge decays below breakeven
        once market impact is included.
    """
    if signal_edge_bps <= 0 or market_impact_k <= 0:
        return float("inf")
    edge_return = signal_edge_bps / 10_000.0
    capacity_raw = avg_volume_usd_per_bar * (edge_return / market_impact_k) ** 2
    # Scale by 1/max_pct_volume so we report capacity AT the volume cap
    return capacity_raw / max_pct_volume


def slippage_bps(
    position_size_usd: float,
    avg_volume_usd_per_bar: float,
    market_impact_k: float = 0.1,
) -> float:
    """Estimate market-impact slippage in bps per fill.

    Same Kyle model as `capacity_estimate`. Returns result in basis points
    so it can be directly compared to `signal_edge_bps`.

    Args:
        position_size_usd: order size in USD.
        avg_volume_usd_per_bar: avg USD volume per bar.
        market_impact_k: Kyle's lambda (default 0.1).

    Returns:
        Estimated slippage in basis points.
    """
    if avg_volume_usd_per_bar <= 0:
        return float("inf")
    impact_return = market_impact_k * (position_size_usd / avg_volume_usd_per_bar) ** 0.5
    return impact_return * 10_000.0


def assess(
    n_round_trips: int,
    avg_hold_bars: float,
    bars_per_year: int,
    avg_volume_usd_per_bar: float,
    position_size_usd: float,
    signal_edge_bps: float,
    market_impact_k: float = 0.1,
    max_pct_volume: float = 0.01,
) -> HygieneReport:
    """Full hygiene assessment.

    Args:
        n_round_trips: closed round-trip count.
        avg_hold_bars: average holding period.
        bars_per_year: bars per year at strategy TF (1h=8760, 4h=2190, 1d=365).
        avg_volume_usd_per_bar: aggregate or per-pair avg USD volume.
        position_size_usd: tested position size.
        signal_edge_bps: gross expected edge per round-trip in bps (e.g.
            50 = 0.5%).
        market_impact_k: Kyle's lambda (default 0.1).
        max_pct_volume: max % of bar volume (default 1%).

    Returns:
        HygieneReport with grade + ratios.
    """
    turnover, _ = turnover_metrics(n_round_trips, avg_hold_bars, bars_per_year)
    cap = capacity_estimate(
        avg_volume_usd_per_bar, position_size_usd, signal_edge_bps,
        market_impact_k, max_pct_volume,
    )
    slip_bps = slippage_bps(position_size_usd, avg_volume_usd_per_bar, market_impact_k)
    ratio = cap / max(position_size_usd, 1.0)

    # Grade thresholds
    if ratio < 2.0:
        grade = "OVERFIT"   # capacity < 2x tested size = cannot scale
    elif ratio < 10.0:
        grade = "WATCH"     # tight capacity
    else:
        grade = "OK"

    notes = ""
    if turnover > 200:
        notes += f"high turnover ({turnover:.0f}/yr) = high fee drag; "
    if slip_bps > signal_edge_bps:
        notes += f"slippage ({slip_bps:.0f}bps) exceeds edge ({signal_edge_bps:.0f}bps); "
    if not notes:
        notes = "all hygiene checks pass"

    return HygieneReport(
        n_round_trips=n_round_trips,
        avg_hold_bars=avg_hold_bars,
        turnover_per_year=turnover,
        estimated_capacity_usd=cap,
        capacity_ratio=ratio,
        avg_volume_usd_per_bar=avg_volume_usd_per_bar,
        estimated_slippage_bps_per_fill=slip_bps,
        hygiene_grade=grade,
        notes=notes.strip().rstrip(";").rstrip(),
    )


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Realistic crypto perp numbers
    r = assess(
        n_round_trips=300,
        avg_hold_bars=20,        # ~80h avg hold on 4h bars
        bars_per_year=2190,
        avg_volume_usd_per_bar=50_000_000,  # $50M daily per pair
        position_size_usd=10_000,
        signal_edge_bps=50,      # 0.5% gross edge per trade
    )
    print(r.summary())
    print(f"Notes: {r.notes}")

    # Tight capacity case
    print()
    r2 = assess(
        n_round_trips=300,
        avg_hold_bars=20,
        bars_per_year=2190,
        avg_volume_usd_per_bar=500_000,  # illiquid altcoin
        position_size_usd=10_000,
        signal_edge_bps=50,
    )
    print(r2.summary())
    print(f"Notes: {r2.notes}")