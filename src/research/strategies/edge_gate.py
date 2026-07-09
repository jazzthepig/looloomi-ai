"""
Edge gate — the bridge from the intelligence layer (edge map) to the execution strategies
(Minimax-B Nautilus LS v1, Minimax-C freqtrade LS V4).

The problem it solves: both strategies gate entries on a HAND-TUNED `REGIME_CIS_FLOOR`
(`cis_score >= floor`). H1 (2026-07-06) proved that gate is directionally INVERTED in 3 of 6
regimes — it's a guess, not evidence. This module replaces the guess with the EMPIRICAL,
SHRUNK, (soon) backfilled edge map: given a name's signal tier, today's risk band, and the
side the technical engine wants to take (EMA cross), it asks OUR OWN 30-day outcomes whether
that trade has positive expected edge — and returns pass/size grounded in data.

Pure + I/O-free: the strategy loads a shrunk edge-map snapshot (JSON) once and calls `gate()`
per bar. Same call works in backtest and live. No pandas/scipy dependency (runs inside Nautilus).

Contract:
    grid = {signal_tier: {risk_band: expected_30d_alpha_pct}}   # SHRUNK values
    gate(grid, tier, band, side) -> EdgeDecision(allow, expected_edge_pct, conviction, reason)

Direction handling (this IS the H1 fix, done empirically):
    side LONG  passes when the tier's edge in this band is >= +min_edge  (data says it gains)
    side SHORT passes when the tier's edge in this band is <= -min_edge  (data says it bleeds → short pays)
  So in a risk-OFF band where the top tier's empirical edge is negative, a LONG is BLOCKED and a
  SHORT is ALLOWED — the regime-conditional direction falls out of the data, no hand-tuning.
"""
from __future__ import annotations

from dataclasses import dataclass

_EDGE_SCALE = 8.0     # |expected alpha %| mapping to full conviction (matches conviction.py)
_MIN_EDGE = 1.0       # |alpha %| below this = no actionable edge → let tech decide (allow, low conf)


@dataclass(frozen=True)
class EdgeDecision:
    allow: bool
    expected_edge_pct: float | None
    conviction: float          # 0..1
    reason: str


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def gate(grid: dict, tier: str, band: str, side: str,
         min_edge: float = _MIN_EDGE) -> EdgeDecision:
    """Empirical entry gate. `side` in {"LONG","SHORT"}. `grid` = shrunk edge map."""
    side = (side or "").upper()
    cell = (grid.get(tier) or {})
    edge = cell.get(band)
    if edge is None:
        # No evidence for this tier×band → don't veto the technical signal, but zero conviction.
        return EdgeDecision(True, None, 0.0, f"no edge data for {tier}×{band} — tech-only")
    edge = float(edge)

    if side == "LONG":
        if edge >= min_edge:
            return EdgeDecision(True, edge, _clamp01(edge / _EDGE_SCALE),
                                f"LONG confirmed: {tier} in {band} +{edge:.1f}% edge")
        if edge <= -min_edge:
            return EdgeDecision(False, edge, 0.0,
                                f"LONG blocked: {tier} in {band} {edge:.1f}% (data says it bleeds here)")
        return EdgeDecision(True, edge, 0.15, f"LONG weak: {tier} in {band} ~flat ({edge:.1f}%)")

    if side == "SHORT":
        if edge <= -min_edge:
            return EdgeDecision(True, edge, _clamp01(-edge / _EDGE_SCALE),
                                f"SHORT confirmed: {tier} in {band} {edge:.1f}% (bleeds → short pays)")
        if edge >= min_edge:
            return EdgeDecision(False, edge, 0.0,
                                f"SHORT blocked: {tier} in {band} +{edge:.1f}% (data says it gains here)")
        return EdgeDecision(True, edge, 0.15, f"SHORT weak: {tier} in {band} ~flat ({edge:.1f}%)")

    return EdgeDecision(True, edge, 0.0, f"unknown side {side!r} — allow")


def size_multiplier(decision: EdgeDecision, floor: float = 0.4, cap: float = 1.3) -> float:
    """Conviction → position-size multiplier for the strategy (Millennium soft sizing):
    blocked → 0; allowed → floor..cap scaled by conviction. Keeps a base size on weak-but-allowed."""
    if not decision.allow:
        return 0.0
    return round(floor + (cap - floor) * decision.conviction, 3)


def build_grid_from_edge_map(rows: list) -> dict:
    """{tier: {band: shrunk_alpha}} from raw signal_edge_map rows, applying EB shrinkage.
    Falls back to raw avg_alpha_pct if the shrinkage module is unavailable (e.g. inside a
    minimal Nautilus runtime)."""
    try:
        from src.data.signals.edge_shrinkage import shrunk_grid_by_signal
        return shrunk_grid_by_signal(rows)
    except Exception:
        grid: dict = {}
        for r in rows:
            grid.setdefault(r.get("signal"), {})[r.get("risk_band")] = r.get("avg_alpha_pct")
        return grid
