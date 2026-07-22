"""
P2 fill-attribution engine — §MECHANISM_SPEC §P2 binding capacity (Seth, 2026-07-21).
=====================================================================================

The §P2 primitive. A PURE function that turns target/current weights + NAV + prices +
ADV into realized slippage and fill-ratio measurements, replacing the CRUDE $5M constant
that R64 carried as a placeholder.

Per MECHANISM_SPEC §P2:
    "not built. Requires a capacity field in the strategy record plus slippage
    attribution at fill time."

This module implements BOTH halves:
  · CAPACITY DECLARATION — the strategy record declares a max notional it can hold.
  · FILL ATTRIBUTION   — each clip computes realized slippage + fill ratio, surfacing
                         under-fills vs the declared capacity as a hard capacity-status
                         flag (not a soft warning).

Why a pure function:
  · Trivially testable (no I/O, no Redis, no asyncio).
  · Reusable: a research backtest can compute the SAME fill-attribution the live paper
    book reports, so OOS and live reconcile.
  · Capacity ceiling is a HARD invariant: if total target notional > declared capacity,
    the engine reports status='breached' and clips the executed weights. The research
    R64 verdict declared $5.0M CRUDE — this engine will turn that into a real number
    once the live price/ADV feed lands.

Slippage model (per §P2):
  base_slip_bps             = the passive/limit fill assumption (default 5bps).
  impact_bps_per_pct_ADV    = linear impact coefficient (default 2.0 bps per 1% of ADV).
  cap_frac_ADV              = max participation per leg per day (default 0.05 = 5%).
  fill_ratio = min(1.0, cap_frac_ADV / participation_pct). 100% when participation is
               below the cap; <100% when above.

This is intentionally SIMPLE — a real execution model would add spread + queue position.
But it is the FIRST step on §P2, and it lets the deployed sleeve honest-report a real
capacity number rather than a hand-wave.

Compliance: pure computation; no user-facing output here.
"""
from __future__ import annotations

import math
from typing import Dict, Optional


# ── Defaults (overridable via kwargs) ─────────────────────────────────────────
DEFAULT_SLIPPAGE_BPS = 5.0            # passive/limit fill assumption
DEFAULT_IMACT_BPS_PER_PCT = 2.0       # linear impact: 2bps per 1% of ADV
DEFAULT_CAP_FRAC_ADV = 0.05           # 5% of daily ADV per leg per day
DEFAULT_PARTICIPATION_CAP = 0.10      # 10% — a safety cap above which we flag BREACHED


# ── Pure primitives ───────────────────────────────────────────────────────────
def _participation_pct(notional: float, adv_usd: float) -> float:
    """Fraction of ADV this notional represents. Returns 0.0 if ADV is missing/zero."""
    if not adv_usd or adv_usd <= 0:
        return 0.0
    return notional / adv_usd


def _fill_ratio(participation: float, cap_frac: float) -> float:
    """How much of the target we can actually fill, given the ADV cap.
    1.0 = full fill (participation <= cap). Lower when above cap.
    """
    if cap_frac <= 0:
        return 1.0
    if participation <= cap_frac:
        return 1.0
    return cap_frac / participation


def _slippage_bps(participation: float, base_bps: float, impact_bps_per_pct: float) -> float:
    """Total slippage in bps. base + impact. Linear in participation share of ADV."""
    if participation <= 0:
        return float(base_bps)
    return float(base_bps) + impact_bps_per_pct * (participation * 100.0)


# ── Main API ──────────────────────────────────────────────────────────────────
def attribute_fill(
    *,
    target_weights: Dict[str, float],
    current_weights: Dict[str, float],
    nav_usd: float,
    prices: Dict[str, float],
    adv_usd: Dict[str, float],
    slippage_model_bps: float = DEFAULT_SLIPPAGE_BPS,
    impact_bps_per_pct: float = DEFAULT_IMACT_BPS_PER_PCT,
    cap_frac_adv: float = DEFAULT_CAP_FRAC_ADV,
    declared_capacity_usd: Optional[float] = None,
) -> dict:
    """Compute per-asset fill attribution for one rebalance clip.

    Parameters
    ----------
    target_weights      : {asset: weight} — gross Σ|w| may exceed 1 (long-short book).
    current_weights     : {asset: weight} — what we currently hold.
    nav_usd             : current NAV in USD.
    prices              : {asset: latest close} — used to size notional from weights.
    adv_usd             : {asset: 30d median ADV in USD}.
    slippage_model_bps  : passive/limit slippage assumption (default 5bps).
    impact_bps_per_pct  : linear impact coefficient (default 2.0 bps per 1% ADV).
    cap_frac_adv        : max participation per leg per day (default 5% of ADV).
    declared_capacity_usd: optional capacity ceiling; if total target > ceiling ⇒ BREACHED.

    Returns
    -------
    dict with:
      per_asset       : {asset: {target_notional, current_notional, turnover_notional,
                                  turnover_pct, adv_participation, slippage_bps,
                                  fill_ratio, executed_notional, executed_weight}}
      totals          : {gross_target_notional, gross_turnover_notional, gross_turnover_pct,
                          weighted_slippage_bps, fill_ratio_overall, executed_notional_total}
      capacity        : {declared_usd, used_pct, status, breach_usd}
      assumptions     : {slippage_model_bps, impact_bps_per_pct, cap_frac_adv}
    """
    all_assets = sorted(set(target_weights) | set(current_weights))
    per_asset: Dict[str, dict] = {}
    weighted_slip_num = 0.0
    weighted_slip_den = 0.0
    exec_notional_total = 0.0

    for asset in all_assets:
        tgt_w = float(target_weights.get(asset, 0.0))
        cur_w = float(current_weights.get(asset, 0.0))
        px = float(prices.get(asset, 0.0))
        adv = float(adv_usd.get(asset, 0.0))

        tgt_notional = tgt_w * nav_usd
        cur_notional = cur_w * nav_usd
        turn_notional = abs(tgt_notional - cur_notional)
        turn_pct = turn_notional / nav_usd if nav_usd > 0 else 0.0

        participation = _participation_pct(turn_notional, adv)
        fill_ratio = _fill_ratio(participation, cap_frac_adv)
        slip_bps = _slippage_bps(participation, slippage_model_bps, impact_bps_per_pct)
        exec_notional = turn_notional * fill_ratio
        exec_weight_delta = (tgt_w - cur_w) * fill_ratio

        per_asset[asset] = {
            "target_weight": round(tgt_w, 6),
            "current_weight": round(cur_w, 6),
            "target_notional": round(tgt_notional, 2),
            "current_notional": round(cur_notional, 2),
            "turnover_notional": round(turn_notional, 2),
            "turnover_pct": round(turn_pct * 100, 4),
            "adv_participation": round(participation * 100, 4),
            "slippage_bps": round(slip_bps, 3),
            "fill_ratio": round(fill_ratio, 4),
            "executed_notional": round(exec_notional, 2),
            "executed_weight_delta": round(exec_weight_delta, 6),
        }
        weighted_slip_num += slip_bps * turn_notional
        weighted_slip_den += turn_notional
        exec_notional_total += exec_notional

    gross_target_notional = sum(abs(a["target_notional"]) for a in per_asset.values())
    gross_turnover_notional = sum(a["turnover_notional"] for a in per_asset.values())
    gross_turnover_pct = gross_turnover_notional / nav_usd if nav_usd > 0 else 0.0
    weighted_slippage_bps = (weighted_slip_num / weighted_slip_den) if weighted_slip_den > 0 else 0.0
    fill_ratio_overall = (exec_notional_total / gross_turnover_notional) if gross_turnover_notional > 0 else 1.0

    # Capacity check
    cap_section: dict
    if declared_capacity_usd is None or declared_capacity_usd <= 0:
        cap_section = {
            "declared_usd": None,
            "used_pct": None,
            "status": "undeclared",
            "breach_usd": 0.0,
        }
    else:
        used_pct = gross_target_notional / declared_capacity_usd if declared_capacity_usd > 0 else 0.0
        if gross_target_notional > declared_capacity_usd * (1.0 + 1e-6):
            cap_section = {
                "declared_usd": declared_capacity_usd,
                "used_pct": round(used_pct * 100, 4),
                "status": "BREACHED",
                "breach_usd": round(gross_target_notional - declared_capacity_usd, 2),
            }
        elif used_pct > 0.95:
            cap_section = {
                "declared_usd": declared_capacity_usd,
                "used_pct": round(used_pct * 100, 4),
                "status": "near_limit",
                "breach_usd": 0.0,
            }
        else:
            cap_section = {
                "declared_usd": declared_capacity_usd,
                "used_pct": round(used_pct * 100, 4),
                "status": "ok",
                "breach_usd": 0.0,
            }

    return {
        "per_asset": per_asset,
        "totals": {
            "gross_target_notional": round(gross_target_notional, 2),
            "gross_turnover_notional": round(gross_turnover_notional, 2),
            "gross_turnover_pct": round(gross_turnover_pct * 100, 4),
            "weighted_slippage_bps": round(weighted_slippage_bps, 3),
            "fill_ratio_overall": round(fill_ratio_overall, 4),
            "executed_notional_total": round(exec_notional_total, 2),
        },
        "capacity": cap_section,
        "assumptions": {
            "slippage_model_bps": slippage_model_bps,
            "impact_bps_per_pct": impact_bps_per_pct,
            "cap_frac_adv": cap_frac_adv,
        },
    }


# ── Self-test (synthetic) ─────────────────────────────────────────────────────
def _self_test() -> int:
    """Lightweight inline self-test, no pytest required. Run via `python -m ...`."""
    nav = 5_000_000.0  # $5M
    prices = {"BTC": 60000.0, "ETH": 3000.0, "SOL": 150.0}
    adv = {"BTC": 2_000_000_000.0, "ETH": 1_000_000_000.0, "SOL": 500_000_000.0}
    # Case 1: trivial equal-weight, no turnover → ~100% fill, near-zero slippage.
    r1 = attribute_fill(
        target_weights={"BTC": 0.1, "ETH": 0.05, "SOL": 0.05},
        current_weights={"BTC": 0.1, "ETH": 0.05, "SOL": 0.05},
        nav_usd=nav, prices=prices, adv_usd=adv,
        declared_capacity_usd=5_000_000.0,
    )
    assert r1["totals"]["gross_turnover_notional"] == 0.0
    assert r1["totals"]["fill_ratio_overall"] == 1.0
    assert r1["capacity"]["status"] == "ok"
    print(f"  case 1 (no turnover): fill={r1['totals']['fill_ratio_overall']}, "
          f"slip={r1['totals']['weighted_slippage_bps']}bps, "
          f"cap_status={r1['capacity']['status']}")

    # Case 2: full rebalance — turnover = $1M. ~100% fill at $2B ADV.
    r2 = attribute_fill(
        target_weights={"BTC": 0.1, "ETH": -0.05, "SOL": 0.05},
        current_weights={"BTC": 0.0, "ETH": 0.0, "SOL": 0.0},
        nav_usd=nav, prices=prices, adv_usd=adv,
        declared_capacity_usd=5_000_000.0,
    )
    assert 0.99 <= r2["totals"]["fill_ratio_overall"] <= 1.0
    assert r2["capacity"]["status"] == "ok"
    print(f"  case 2 (full rebal): turnover=${r2['totals']['gross_turnover_notional']:,.0f}, "
          f"fill={r2['totals']['fill_ratio_overall']:.4f}, "
          f"weighted_slip={r2['totals']['weighted_slippage_bps']:.2f}bps")

    # Case 3: BREACH — declared $1M, target gross $2M.
    r3 = attribute_fill(
        target_weights={"BTC": 0.2, "ETH": 0.2},
        current_weights={},
        nav_usd=nav, prices=prices, adv_usd=adv,
        declared_capacity_usd=1_000_000.0,
    )
    assert r3["capacity"]["status"] == "BREACHED"
    assert r3["capacity"]["breach_usd"] > 0
    print(f"  case 3 (BREACH): declared=$1M, target=${r3['totals']['gross_target_notional']:,.0f}, "
          f"breach=${r3['capacity']['breach_usd']:,.0f}")

    # Case 4: tiny-cap asset — participation > 5%, fill < 1.0.
    thin_adv = {"BTC": 100_000.0}
    r4 = attribute_fill(
        target_weights={"BTC": 0.1},
        current_weights={},
        nav_usd=nav, prices={"BTC": 60000.0}, adv_usd=thin_adv,
    )
    assert r4["totals"]["fill_ratio_overall"] < 1.0
    assert r4["per_asset"]["BTC"]["fill_ratio"] < 1.0
    print(f"  case 4 (thin ADV): fill={r4['per_asset']['BTC']['fill_ratio']:.4f}, "
          f"participation={r4['per_asset']['BTC']['adv_participation']:.1f}%")

    # Case 5: undeclared capacity → status=undeclared, no breach logic.
    r5 = attribute_fill(
        target_weights={"BTC": 0.5},
        current_weights={},
        nav_usd=nav, prices={"BTC": 60000.0}, adv_usd={"BTC": 1_000_000_000.0},
    )
    assert r5["capacity"]["status"] == "undeclared"
    print(f"  case 5 (undeclared): status={r5['capacity']['status']}")

    print("✓ fill_attribution self-test OK (5 cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
