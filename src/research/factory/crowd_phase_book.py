"""
Crowd-Phase Book — the sizing switch for the two-layer book (Seth, 2026-07-17).
================================================================================
Ties the Crowd Clock (src/data/market/crowd_clock.py) to the Trader Tom two-layer doctrine
(docs/TRADER_TOM_DOCTRINE.md §5b): the crowd's emotional phase decides WHICH sleeve leads and
HOW HARD to press — the master-trend judgment made mechanical.

  · mean-reversion sleeve  = the win-rate engine (MultiFactorV2 MVRV capitulation buyer)
  · trend sleeve           = the convex engine (SwingOverlayV9 regime trend-rider)

Policy (positioning-safe; a research sizing read, NOT advice):
  capitulation  → mean-reversion LEADS (contrarian window), trend defensive, gross moderate
  accumulation  → balanced, low gross (build quietly)
  markup        → trend LEADS, press (add to confirmed strength), gross high
  euphoria      → trend trims, defend, gross low (crowded longs = flush fuel)
  distribution  → reduce, hedge, gross lowest

This is the phase→weight map that Minimax's §STRATEGY-REVIVE C-S4 two-layer book plugs into.
HONEST: candidate policy, tied to Refutation Ledger R24 — the phase's predictive value is not yet
validated, so gross never exceeds a conservative cap and the policy degrades to balanced/low on
low phase-conviction.
"""
from __future__ import annotations

# phase → (mean_reversion_weight, trend_weight, base_gross, net_bias, note). Weights are the
# split WITHIN the risk book; base_gross is the exposure scale (1.0 = neutral). Caps stay humble
# until R24 resolves — we do not lever an unvalidated phase call.
# Recalibrated to R24 backtest evidence: markup edge VALIDATED (press), distribution bearish
# VALIDATED (defend), capitulation contrarian REFUTED at 30d (momentum > reversal in crypto) — so
# capitulation is NO LONGER a broad long tilt; the mean-reversion sleeve leads but sized modestly on
# its OWN selective deep-extreme entries, net-neutral.
_POLICY = {
    "capitulation": (0.65, 0.35, 0.60, "neutral","Fear extreme — NOT a broad 30d long (R24: momentum beats reversal in crypto). Mean-reversion sleeve leads on its own selective deep-extreme entries, sized modestly; no directional tilt."),
    "accumulation": (0.55, 0.45, 0.55, "neutral","Basing — balanced, low gross; accumulate quality without urgency."),
    "markup":       (0.30, 0.70, 1.00, "long",   "Uptrend — press the trend sleeve. NB: the edge here is plain MOMENTUM (survives OOS, weaker); the greed/sentiment add-on did NOT survive walk-forward (R24 F3), so do not over-credit the phase."),
    "euphoria":     (0.35, 0.65, 0.50, "reduce", "Late-cycle — trim the trend sleeve into strength; crowded longs are flush fuel (untested live; stay defensive)."),
    "distribution": (0.45, 0.55, 0.45, "reduce", "Topping — weakly bearish and NOT robust cross-asset (ETH broke it, R24 F1); modest defensive tilt only, do not lean hard."),
}
_GROSS_CAP = 1.10   # humble hard cap until R24 validates the phase edge


def phase_allocation(phase: str, confidence: float = 1.0) -> dict:
    """crowd-clock phase (+ its confidence) → two-layer sizing. Low confidence dampens gross
    toward neutral (we press only when the phase read is clean). Pure + testable."""
    mr, tr, gross, bias, note = _POLICY.get(phase, (0.5, 0.5, 0.55, "neutral", "Unknown phase — balanced, low gross."))
    c = max(0.0, min(1.0, confidence))
    # dampen gross toward a neutral 0.55 when the phase is low-conviction; never exceed the cap
    gross_adj = round(min(_GROSS_CAP, 0.55 + (gross - 0.55) * c), 3)
    return {
        "phase": phase,
        "mean_reversion_weight": mr,
        "trend_weight": tr,
        "gross_scale": gross_adj,
        "gross_scale_raw": gross,
        "net_bias": bias,
        "note": note,
        "status": "candidate",
        "disclaimer": "Phase-conditional sizing candidate (Refutation Ledger R24) — not validated, "
                      "gross capped. Positioning read only; not investment advice.",
    }


async def get_phase_allocation() -> dict:
    """Live: read the current Crowd Clock, return the two-layer sizing policy for this phase."""
    from src.data.market.crowd_clock import get_crowd_clock
    clock = await get_crowd_clock()
    alloc = phase_allocation(clock.get("phase", "accumulation"), clock.get("confidence", 1.0))
    alloc["crowd_clock"] = {"phase": clock.get("phase"), "confidence": clock.get("confidence"),
                            "posture": clock.get("posture")}
    return alloc


if __name__ == "__main__":   # sanity — the policy must express the doctrine
    for ph in ["capitulation", "accumulation", "markup", "euphoria", "distribution"]:
        a = phase_allocation(ph, 1.0)
        print(f"{ph:14s} MR={a['mean_reversion_weight']:.2f} TR={a['trend_weight']:.2f} "
              f"gross={a['gross_scale']:.2f} bias={a['net_bias']:<8s} {a['note'][:52]}")
    print("\nlow-conviction (conf=0.2) dampens gross toward neutral:")
    for ph in ["markup", "euphoria"]:
        a = phase_allocation(ph, 0.2)
        print(f"  {ph:12s} gross {a['gross_scale']:.2f} (raw {a['gross_scale_raw']:.2f})")
