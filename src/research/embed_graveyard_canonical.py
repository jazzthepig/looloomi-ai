"""
Graveyard → canonical strategy library, + the "what to build next" map (Seth, 2026-07-23)
==========================================================================================

Completes build-order #3: the 8 refuted/parked sleeves that `embed_graveyard.py` embedded in the
DEPRECATED `src/research/strategy_vector.py` schema are re-expressed here as canonical
`StrategyRecord`s (`src/data/vector/strategy_schema.py`) and run through the canonical
`coverage_gaps()` / `redundancy()` ported in #3a. Output = the strategic build-list: which regimes
the live library does NOT cover, and which sleeves are near-duplicates (fake breadth).

Two honest mapping choices (the reason the raw port was "lossy"):
  · `leakage_clean` is tri-state (True=verified / False=proven-leaky / None=UNVERIFIED). Canonical
    `pit_clean` is a bool where False DISQUALIFIES. So None → `pit_clean=True` + a `pit_unverified`
    TAG — an untested sleeve is NOT proven leaky and must not be falsely disqualified (this is the
    swing_overlay_v9 case). Only an EXPLICIT False disqualifies.
  · `cost_slope` (a d(perf)/d(bps) scalar) has no home in canonical `cost_sensitivity{0/2/5/10bps}`
    and is dropped — one derived dim, acceptable; the sleeve keeps its other coordinates.

This module reads nothing live and mutates no store — pure, run it to print the map. It supersedes
`embed_graveyard.py`; that file + `src/research/strategy_vector.py` can be `git rm`'d Mac-side once
this is confirmed (RULE 2: stage only your own paths).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.data.vector.strategy_schema import StrategyRecord, Verdict  # noqa: E402
from src.data.vector.strategy_embedder import (  # noqa: E402
    coverage_gaps, redundancy, is_disqualified, coverage_summary,
)

_REGIME = {"calm": "regime_calm_vol", "stormy": "regime_storm_vol", "risk_on": "regime_risk_on",
           "risk_off": "regime_risk_off", "trend": "regime_trend", "chop": "regime_chop"}
_VERDICT = {"live": Verdict.SHIP, "candidate": Verdict.HOLD, "refuted": Verdict.REFUTE,
            "retired": Verdict.REFUTE}


def _rec(name, *, regime=None, factors=None, mechanics=None, capacity=None, lifecycle=None,
         cost_slope=None, leakage_clean=True, cost_feasible=True, ledger_ref="", status="candidate",
         notes=""):
    """Map the deprecated strategy_vector.build() kwargs onto a canonical StrategyRecord."""
    regime, factors = regime or {}, factors or {}
    mechanics, capacity, lifecycle = mechanics or {}, capacity or {}, lifecycle or {}
    tags = []
    if leakage_clean is None:
        tags.append("pit_unverified")           # unverified ≠ proven leaky ⇒ not disqualified
    fe = {}
    for k in ("beta_market", "beta_momentum", "beta_carry", "beta_quality"):
        if k in factors:
            fe[k] = factors[k]
    if "alpha_t" in factors:
        fe["residual_alpha"] = factors["alpha_t"]
    return StrategyRecord(
        id=name, title=name, doc_source="REFUTATION_LEDGER.md", r_number=ledger_ref,
        verdict=_VERDICT.get(status, Verdict.HOLD), tags=tags,
        pit_clean=(leakage_clean is not False),
        cost_feasible_at_5bps=bool(cost_feasible),
        forward_committed=(status == "live"),
        regime_domain={_REGIME[k]: v for k, v in regime.items() if k in _REGIME},
        factor_exposure=fe,
        mechanics={
            "holding_period_days": mechanics.get("holding_days"),
            "turnover_per_q": (mechanics["turnover_yr"] / 4.0) if "turnover_yr" in mechanics else None,
            "time_in_market": (mechanics["time_in_market"] * 100.0) if "time_in_market" in mechanics else None,
            "directionality": mechanics.get("directionality"),
        },
        capacity={"declared_capacity": capacity.get("usd"), "adv_fraction": capacity.get("adv_fraction")},
        lifecycle={"age_days": lifecycle.get("age_days"), "decay_slope": lifecycle.get("perf_slope"),
                   "crowding_proxy": lifecycle.get("crowding")},
        cost_sensitivity={},   # cost_slope has no lossless canonical home (see module docstring)
        notes=notes,
    )


# The 8 sleeves (values transcribed from embed_graveyard.py, unchanged).
LIBRARY = [
    _rec("trend_v5c_long_only", regime={"trend": 1.9, "chop": -1.4, "risk_on": 2.1, "risk_off": -1.7},
         factors={"beta_market": 0.85, "beta_momentum": 1.10, "alpha_t": 0.0},
         mechanics={"holding_days": 30, "turnover_yr": 8, "time_in_market": 0.55, "directionality": 1.0},
         capacity={"usd": 5e7, "adv_fraction": 0.01}, lifecycle={"age_days": 400, "perf_slope": -0.8},
         cost_slope=-0.15, leakage_clean=True, cost_feasible=True, ledger_ref="R49/R55/R57", status="live"),
    _rec("vol_carry_btc", regime={"calm": 2.7, "stormy": -1.5},
         factors={"beta_market": 0.15, "beta_momentum": -0.1, "alpha_t": 3.66},
         mechanics={"holding_days": 10, "turnover_yr": 36, "time_in_market": 0.8, "directionality": -0.5},
         capacity={"usd": 2e6, "adv_fraction": 0.15}, lifecycle={"age_days": 2, "perf_slope": 0.0},
         cost_slope=-0.95, leakage_clean=True, cost_feasible=False, ledger_ref="R39", status="refuted"),
    _rec("funding_crowding_pooled", regime={"risk_on": -1.2, "risk_off": 1.1, "trend": 0.4, "chop": 0.9},
         factors={"beta_market": 0.02, "beta_momentum": 0.05, "beta_carry": 0.9, "alpha_t": 1.04},
         mechanics={"holding_days": 5, "turnover_yr": 80, "time_in_market": 0.9, "directionality": 0.0},
         capacity={"usd": 1e7, "adv_fraction": 0.03}, lifecycle={"age_days": 30, "perf_slope": -0.3, "crowding": 0.7},
         cost_slope=-0.4, leakage_clean=True, cost_feasible=True, ledger_ref="R47/R49/R60", status="refuted"),
    _rec("cis_quality_ls_5d", regime={"risk_on": 1.2, "risk_off": 0.8, "trend": 1.0, "chop": 0.6},
         factors={"beta_market": 0.05, "beta_momentum": 0.1, "beta_quality": 1.2, "alpha_t": 2.64},
         mechanics={"holding_days": 5, "turnover_yr": 79, "time_in_market": 0.95, "directionality": 0.0},
         capacity={"usd": 1.5e7, "adv_fraction": 0.02}, lifecycle={"age_days": 1, "perf_slope": 0.0},
         cost_slope=-0.3, leakage_clean=True, cost_feasible=True, ledger_ref="R46/R62", status="candidate"),
    _rec("swing_overlay_v9", regime={"trend": 1.5, "chop": 0.3},
         factors={"beta_momentum": -1.07, "alpha_t": 4.85},
         mechanics={"holding_days": 0.1, "turnover_yr": 550, "time_in_market": 0.10, "directionality": 0.2},
         capacity={"usd": 2e6, "adv_fraction": 0.18}, lifecycle={"age_days": 15, "perf_slope": 0.0},
         cost_slope=-0.85, leakage_clean=None, cost_feasible=True, ledger_ref="§V9-SWING-LEGACY-BASELINE", status="candidate"),
    _rec("ls_v4_ema_flip", regime={"trend": 1.2, "chop": -1.8},
         factors={"beta_market": 0.7, "beta_momentum": 1.4, "alpha_t": -0.5},
         mechanics={"holding_days": 3.7, "turnover_yr": 100, "time_in_market": 1.0, "directionality": 0.0},
         capacity={"usd": 2e7, "adv_fraction": 0.02}, lifecycle={"age_days": 500, "perf_slope": -0.9},
         cost_slope=-0.7, leakage_clean=True, cost_feasible=True, ledger_ref="R49", status="retired"),
    _rec("weekly_liquidity_gate", regime={"risk_on": 1.4, "risk_off": 0.9, "trend": 1.1},
         factors={"beta_market": 0.6},
         mechanics={"holding_days": 21, "turnover_yr": 6, "time_in_market": 0.71, "directionality": 1.0},
         capacity={"usd": 5e8, "adv_fraction": 0.001}, lifecycle={"age_days": 1, "perf_slope": 0.0},
         cost_slope=-0.05, leakage_clean=True, cost_feasible=True, ledger_ref="WEEKLY_REVIEW 2026-07-21", status="candidate"),
    _rec("risk_direction_score", regime={"risk_on": 0.5, "risk_off": 1.3, "chop": 0.2},
         factors={"beta_market": 0.4},
         mechanics={"holding_days": 2, "turnover_yr": 60, "time_in_market": 0.49, "directionality": 0.1},
         lifecycle={"age_days": 1, "perf_slope": 0.0},
         cost_slope=-0.35, leakage_clean=True, cost_feasible=True, ledger_ref="R50*", status="candidate"),
]


def library_map(records=LIBRARY) -> dict:
    """The strategic output: coverage gaps (build-list) + redundancy (fake breadth), disqualified excluded."""
    live = [r for r in records if not is_disqualified(r)[0]]
    dq = [(r.id, is_disqualified(r)[1]) for r in records if is_disqualified(r)[0]]
    return {
        "n_total": len(records),
        "n_live": len(live),
        "disqualified": dq,
        "coverage_gaps": coverage_gaps(records),
        "redundancy": redundancy(records),
        "coverage_per_sleeve": {r.id: coverage_summary(r)["coverage_pct"] for r in records},
    }


if __name__ == "__main__":
    m = library_map()
    print(f"STRATEGY LIBRARY — {m['n_live']} live / {m['n_total']} total")
    print("=" * 64)
    if m["disqualified"]:
        print("DISQUALIFIED (validity floor, excluded from coverage):")
        for name, why in m["disqualified"]:
            print(f"  ✗ {name:26s} {why}")
    print("\nREGIME COVERAGE (build where covered=False) — disqualified excluded:")
    for g in m["coverage_gaps"]:
        flag = "covered" if g["covered"] else "❗ GAP  "
        print(f"  {flag}  {g['regime']:18s} best={g['best_in_library']}  (n_measured={g['n_measured']})")
    print("\nNEAR-DUPLICATES (fake breadth):")
    if m["redundancy"]:
        for d in m["redundancy"]:
            print(f"  {d['a']} ≈ {d['b']}  ({d['similarity']})")
    else:
        print("  (none ≥ threshold)")
