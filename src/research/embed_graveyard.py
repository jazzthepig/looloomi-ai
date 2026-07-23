"""
Re-embed the graveyard — refuted sleeves become LOCATED, not dead (Seth, 2026-07-21).
======================================================================================

⚠️ SUPERSEDED (2026-07-23, build-order #3 complete). The 8 sleeves below now live in the CANONICAL
schema at `src/research/embed_graveyard_canonical.py` (StrategyRecord + canonical coverage_gaps/
redundancy), which also prints the strategy-library "what to build next" map. This file + its import
target `src/research/strategy_vector.py` are both DEPRECATED — run the canonical module instead. Both
can be `git rm`'d Mac-side (RULE 2: stage only your own paths). Kept temporarily for reference only.

Turns `REFUTATION_LEDGER.md` from a record of failures into the library's opening inventory.
Most entries there were killed for being regime-dependent — which, under the library doctrine
(`docs/MECHANISM_SPEC.md` §3), is a *coordinate*, not a verdict. Only two things truly disqualify:
look-ahead leakage and cost-infeasibility at declared capacity.

Values are transcribed from ledger entries. Where a dimension was never measured it stays **NaN** —
an unmeasured dimension is not zero, and pretending otherwise fabricates a map. Sparse is honest.

Run:  python3 -m src.research.embed_graveyard
Out:  reports/strategy_library.jsonl  (+ printed library summary)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.research.strategy_vector import build, save, format_library  # noqa: E402

OUT = "reports/strategy_library.jsonl"

POOL = [
    # ── V5c trend core: the archetypal "killed for being regime-dependent" sleeve ──
    build("trend_v5c_long_only",
          regime={"trend": 1.9, "chop": -1.4, "risk_on": 2.1, "risk_off": -1.7},
          factors={"beta_market": 0.85, "beta_momentum": 1.10, "alpha_t": 0.0},
          mechanics={"holding_days": 30, "turnover_yr": 8, "time_in_market": 0.55,
                     "directionality": 1.0},
          capacity={"usd": 5e7, "adv_fraction": 0.01},
          lifecycle={"age_days": 400, "perf_slope": -0.8},
          cost_slope=-0.15, leakage_clean=True, cost_feasible=True,
          ledger_ref="R49/R55/R57", status="live",
          notes="Momentum-beta harvester, NOT alpha. Rides up-cycle, defends crashes, bleeds in chop. "
                "R57: core DEAD since 2025-11 (2.7% engagement) — that is a LIFECYCLE/regime fact, "
                "not invalidity. Deployed in §5b overlay-only with a core-health gate."),

    # ── vol carry: cleared every statistical gate, died on replication + real costs ──
    build("vol_carry_btc",
          regime={"calm": 2.7, "stormy": -1.5},
          factors={"beta_market": 0.15, "beta_momentum": -0.1, "alpha_t": 3.66},
          mechanics={"holding_days": 10, "turnover_yr": 36, "time_in_market": 0.8,
                     "directionality": -0.5},
          capacity={"usd": 2e6, "adv_fraction": 0.15},
          lifecycle={"age_days": 2, "perf_slope": 0.0},
          cost_slope=-0.95, leakage_clean=True, cost_feasible=False,
          ledger_ref="R39", status="refuted",
          notes="DISQUALIFIED on cost floor: SR +2.69 → −2.22 under a realistic 30% options "
                "bid/ask haircut, and failed ETH replication. Calm-regime coordinates are real; "
                "the instrument is too expensive for us to trade."),

    # ── funding-crowding pooled book: mechanism real, one regime kills it ──
    build("funding_crowding_pooled",
          regime={"risk_on": -1.2, "risk_off": 1.1, "trend": 0.4, "chop": 0.9},
          factors={"beta_market": 0.02, "beta_momentum": 0.05, "beta_carry": 0.9, "alpha_t": 1.04},
          mechanics={"holding_days": 5, "turnover_yr": 80, "time_in_market": 0.9,
                     "directionality": 0.0},
          capacity={"usd": 1e7, "adv_fraction": 0.03},
          lifecycle={"age_days": 30, "perf_slope": -0.3, "crowding": 0.7},
          cost_slope=-0.4, leakage_clean=True, cost_feasible=True,
          ledger_ref="R47/R49/R60", status="refuted",
          notes="Market-neutral, ENB 198, βs≈0 — genuinely orthogonal. Dies in the F1 "
                "quality-rotation regime (α_t −3.02) where the crowd was correctly positioned. "
                "A located sleeve with a known blind spot, not an invalid one."),

    # ── CIS-quality L/S at 5-day cadence: the one that SURVIVED the 3-check gauntlet ──
    build("cis_quality_ls_5d",
          regime={"risk_on": 1.2, "risk_off": 0.8, "trend": 1.0, "chop": 0.6},
          factors={"beta_market": 0.05, "beta_momentum": 0.1, "beta_quality": 1.2, "alpha_t": 2.64},
          mechanics={"holding_days": 5, "turnover_yr": 79, "time_in_market": 0.95,
                     "directionality": 0.0},
          capacity={"usd": 1.5e7, "adv_fraction": 0.02},
          lifecycle={"age_days": 1, "perf_slope": 0.0},
          cost_slope=-0.3, leakage_clean=True, cost_feasible=True,
          ledger_ref="R46/R62", status="candidate",
          notes="Survives 3-check gauntlet at 5d cadence (5bps t=+2.64, 10bps +2.43). Removes β BY "
                "CONSTRUCTION — which is exactly why it worked while the raw signal metric looked "
                "inverted (R62). Known W5 (late-cycle risk-on) failure window. Crypto-specific (R48)."),

    # ── V9 swing: high Sharpe, real, but capacity-bounded far below our AUM target ──
    build("swing_overlay_v9",
          regime={"trend": 1.5, "chop": 0.3},
          factors={"beta_momentum": -1.07, "alpha_t": 4.85},
          mechanics={"holding_days": 0.1, "turnover_yr": 550, "time_in_market": 0.10,
                     "directionality": 0.2},
          capacity={"usd": 2e6, "adv_fraction": 0.18},
          lifecycle={"age_days": 15, "perf_slope": 0.0},
          cost_slope=-0.85, leakage_clean=None, cost_feasible=True,
          ledger_ref="§V9-SWING-LEGACY-BASELINE", status="candidate",
          notes="SR ~5 is arithmetically coherent (32.4%/yr, ~6.4% vol, ~10% time-in-market) — not "
                "implausible, but it is EXECUTION alpha: capacity ~$2M, drag already 17.25%/yr. "
                "leakage_clean=None: the hand-rolled 4h→15m merge is UNVERIFIED. Must pass the "
                "shift-one-period leak test before it can be credited."),

    # ── LS V4: the honest label for a churning momentum proxy ──
    build("ls_v4_ema_flip",
          regime={"trend": 1.2, "chop": -1.8},
          factors={"beta_market": 0.7, "beta_momentum": 1.4, "alpha_t": -0.5},
          mechanics={"holding_days": 3.7, "turnover_yr": 100, "time_in_market": 1.0,
                     "directionality": 0.0},
          capacity={"usd": 2e7, "adv_fraction": 0.02},
          lifecycle={"age_days": 500, "perf_slope": -0.9},
          cost_slope=-0.7, leakage_clean=True, cost_feasible=True,
          ledger_ref="R49", status="retired",
          notes="Momentum beta in an EMA-cross costume: absorption momentum-β t=9→24, residual α "
                "NEGATIVE, 9.5%/yr churn drag. Superseded by trend_v5c (same exposure, 13× less churn)."),

    # ── weekly liquidity gate: today's most promising NEW candidate ──
    build("weekly_liquidity_gate",
          regime={"risk_on": 1.4, "risk_off": 0.9, "trend": 1.1},
          factors={"beta_market": 0.6},
          mechanics={"holding_days": 21, "turnover_yr": 6, "time_in_market": 0.71,
                     "directionality": 1.0},
          capacity={"usd": 5e8, "adv_fraction": 0.001},
          lifecycle={"age_days": 1, "perf_slope": 0.0},
          cost_slope=-0.05, leakage_clean=True, cost_feasible=True,
          ledger_ref="WEEKLY_REVIEW 2026-07-21", status="candidate",
          notes="Stablecoin-supply Δ gate on crypto beta: SR 0.83 / +35.4%/yr / DD −56.5% vs "
                "buy-hold 0.64 / +22.3% / −75.2%. HIGH capacity (macro-scale, no execution edge) — "
                "the right SHAPE for $30M. NOT yet gauntleted; single full-sample window."),

    # ── RDS: construction validated, not yet a credited book ──
    build("risk_direction_score",
          regime={"risk_on": 0.5, "risk_off": 1.3, "chop": 0.2},
          factors={"beta_market": 0.4},
          mechanics={"holding_days": 2, "turnover_yr": 60, "time_in_market": 0.49,
                     "directionality": 0.1},
          lifecycle={"age_days": 1, "perf_slope": 0.0},
          cost_slope=-0.35, leakage_clean=True, cost_feasible=True,
          ledger_ref="R50*", status="candidate",
          notes="Smoothed continuous multi-factor gate: SR +0.44, positive BOTH halves, and the only "
                "tested book positive in the recent risk-OFF half. Over-eager to short; best crude "
                "calibration thr0.60/cap0.4 (SR +0.46, DD −29.6%). Awaiting MVRV + funding + 15m."),
]

if __name__ == "__main__":
    os.makedirs("reports", exist_ok=True)
    n = save(POOL, OUT)
    print(format_library(POOL))
    print(f"\nwrote {n} strategy vectors → {OUT}")
