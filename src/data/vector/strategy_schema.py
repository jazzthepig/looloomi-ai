"""
Strategy Vector — schema (per docs/MECHANISM_SPEC.md §3)
==========================================================

A StrategyRecord is the machine-readable contract for a single trading strategy,
sleeve, or behavioral primitive. The schema follows MECHANISM_SPEC §3:

  - BINARY validity (one False = permanently disqualifying)
      pit_clean, cost_feasible_at_5bps, forward_committed

  - DIMENSIONAL (six blocks, never binary)
      regime_domain, factor_exposure, mechanics, capacity, lifecycle,
      cost_sensitivity

  - RESOLVED outcome (auto-filled by P1 forward-commitment loop)
      realized_alpha, realized_decay, realized_capacity, last_eval_ts

Source of truth: docs/MECHANISM_SPEC.md §3 ("The strategy vector"). This module
is its implementation. The MECHANISM_SPEC doc must be updated first if any block
changes — the schema and the document must stay in sync.

Records are stored as JSON in Upstash Redis (key: strategy:records). All fields
are JSON-serializable. Missing fields are tolerated (default to neutral) so that
records can be backfilled incrementally from partial sources (R-entries without
P1 outcome, doctrinal primitives without capacity, etc.).

Verdict values:
  ship      — strategy is live-deployed (paper or real)
  hold      — validated but parked (e.g. core-gated awaiting replacement)
  refute    — refuted; archived for honesty (R-flag negative results)
  doctrine  — not a tradeable strategy; a behavioral/architectural primitive

The verdict is metadata; the binary validity fields are the actual disqualifier.
A "ship" verdict with pit_clean=False is a self-contradiction that should be
caught by `validate_record()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Verdict(str, Enum):
    SHIP = "ship"
    HOLD = "hold"
    REFUTE = "refute"
    DOCTRINE = "doctrine"


# ---------------------------------------------------------------------------
# Constants — the 30 vector dimensions are fixed; reorder is a breaking change.
# (See strategy_embedder.py for what each dimension holds.)
# ---------------------------------------------------------------------------

REGIME_DIMS: tuple[str, ...] = (
    "regime_calm_vol",    # Sharpe conditional on calm vol regime
    "regime_storm_vol",   # Sharpe conditional on stormy vol regime
    "regime_risk_on",     # Sharpe conditional on Risk-On macro
    "regime_risk_off",    # Sharpe conditional on Risk-Off macro
    "regime_trend",       # Sharpe conditional on trending tape
    "regime_chop",        # Sharpe conditional on choppy tape
)

FACTOR_DIMS: tuple[str, ...] = (
    "beta_market",        # abs exposure to benchmark
    "beta_momentum",      # cross-section momentum factor β
    "beta_carry",         # funding / carry factor β
    "beta_quality",       # CIS quality factor β
    "residual_alpha",     # α after {market, momentum, carry, quality} absorbed
)

MECHANICS_DIMS: tuple[str, ...] = (
    "holding_period_log",  # log scale of typical hold
    "turnover_per_q",      # flip rate per quarter
    "time_in_market",      # fraction of trading days with a position
    "directionality",      # long-bias vs short-bias [-1, 1]
)

CAPACITY_DIMS: tuple[str, ...] = (
    "adv_fraction",        # capacity as fraction of avg daily volume
    "declared_capacity",   # declared max notional (P2)
    "realized_fill_pct",   # % of declared capacity actually fillable
)

LIFECYCLE_DIMS: tuple[str, ...] = (
    "age_days",            # days since record registered
    "decay_slope",         # rolling performance slope (negative = decaying)
    "crowding_proxy",      # crowding signal [-1, 1]
    "half_life_days",      # estimated decay half-life in days
)

COST_DIMS: tuple[str, ...] = (
    "sharpe_0bps",         # raw Sharpe, no cost
    "sharpe_2bps",         # with 2bps/side round-trip spread
    "sharpe_5bps",         # with 5bps (Binance VIP taker baseline)
    "sharpe_10bps",        # with 10bps (retail / worst-case)
)

OUTCOME_DIMS: tuple[str, ...] = (
    "realized_alpha",      # P1 resolved 30d benchmark-relative α
    "realized_decay",      # rolling performance decay observed
    "capacity_util",       # used vs declared capacity (P2)
    "outcome_confidence",  # confidence of forward-resolution (P1)
)


# ---------------------------------------------------------------------------
# Record container
# ---------------------------------------------------------------------------

@dataclass
class StrategyRecord:
    """One strategy / sleeve / behavioral primitive in the system of record."""

    # Identity
    id: str                                                  # unique key
    title: str                                               # human label
    doc_source: str                                          # file path
    r_number: Optional[str] = None                           # e.g. "R46"
    verdict: Verdict = Verdict.HOLD                          # ship / hold / refute / doctrine
    tags: list[str] = field(default_factory=list)            # free-form tags

    # BINARY validity (per MECHANISM_SPEC §3)
    pit_clean: bool = False
    cost_feasible_at_5bps: bool = False
    forward_committed: bool = False

    # DIMENSIONAL — six blocks (values clamped to schema ranges by embedder)
    regime_domain: dict = field(default_factory=dict)        # {regime_key: sharpe_or_None}
    factor_exposure: dict = field(default_factory=dict)      # {factor: beta}
    mechanics: dict = field(default_factory=dict)            # {key: value}
    capacity: dict = field(default_factory=dict)             # {key: value}
    lifecycle: dict = field(default_factory=dict)            # {key: value}
    cost_sensitivity: dict = field(default_factory=dict)     # {cost_bps: sharpe}

    # RESOLVED outcome (P1 forward-commitment loop fills these)
    realized_alpha: Optional[float] = None
    realized_decay: Optional[float] = None
    capacity_util: Optional[float] = None
    outcome_confidence: Optional[float] = None
    last_eval_ts: Optional[float] = None                     # epoch seconds

    # EVIDENCE-GRADE (2026-07-27, per Minimax feedback — "把哲学编译成约束"). Additive, optional (I6).
    # These make "guilty until proven with OOS outcomes" machine-checkable instead of prose:
    base_rate: Optional[str] = None          # the CAUSE + its base rate (§TRADER_TOM: every sleeve traces to a behavioral cause)
    oos_window: Optional[str] = None         # e.g. "2026-02-01→2026-05-03" — the held-out window actually used
    oos_survival: Optional[bool] = None      # survived OOS + independent-event count (None = untested, NOT False)
    paper_trade_days: Optional[int] = None   # forward paper days accrued (SHIP requires ≥ 60)
    regime_skip: list[str] = field(default_factory=list)     # regimes the sleeve is gated OFF in
    regime_reported: Optional[bool] = None   # OOS metrics reported per-regime (RISK_OFF/NEUTRAL/RISK_ON), not aggregate-only

    # RISK-ALLOCATOR fields (Millennium discipline — docs/RISK_ALLOCATOR_SPEC.md, 2026-07-27).
    # A component without a stop rule cannot go to production: the platform's edge is risk
    # allocation, not any single pod. `backtest_included_stop` guards the self-deception of
    # adding the stop AFTER the curve was drawn — a stop changes the curve's shape.
    max_dd_stop: Optional[float] = None          # e.g. -0.15 → zero the pod, 30d freeze (§3 ladder)
    capital_action_on_breach: Optional[str] = None   # halve | quarter | zero_and_freeze | observe
    backtest_included_stop: Optional[bool] = None    # was the ladder applied DURING the backtest?
    promotion_stage: Optional[str] = None        # research | paper | pilot | standard | core (§5)

    # Notes / free-text
    notes: str = ""                                          # ≤1 KB; not embedded

    # Bookkeeping
    registered_at: str = ""                                  # ISO8601 UTC
    updated_at: str = ""                                     # ISO8601 UTC

    def __post_init__(self):
        if isinstance(self.verdict, str):
            self.verdict = Verdict(self.verdict)
        if not self.registered_at:
            self.registered_at = _iso_now()
        if not self.updated_at:
            self.updated_at = self.registered_at

    # -------- JSON round-trip -------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyRecord":
        d = dict(d)
        if "verdict" in d and isinstance(d["verdict"], str):
            d["verdict"] = Verdict(d["verdict"])
        return cls(**d)

    # -------- Validation -------------------------------------------------------

    def validate(self) -> list[str]:
        """Return list of validation warnings (does NOT raise)."""
        problems: list[str] = []
        if not self.id:
            problems.append("missing id")
        if not self.title:
            problems.append("missing title")
        if self.verdict == Verdict.SHIP:
            if not self.pit_clean:
                problems.append("ship verdict but pit_clean=False")
            if not self.cost_feasible_at_5bps:
                problems.append("ship verdict but cost_feasible_at_5bps=False")
            if not self.forward_committed:
                problems.append("ship verdict but forward_committed=False")
            # EVIDENCE-GRADE floor for production (the compiled philosophy — 2026-07-27):
            if not self.base_rate:
                problems.append("ship verdict but no base_rate/cause documented (§TRADER_TOM: every sleeve needs a cause)")
            if self.oos_survival is not True:
                problems.append("ship verdict but oos_survival is not True (guilty until proven with OOS outcomes)")
            if (self.paper_trade_days or 0) < 60:
                problems.append(f"ship verdict but paper_trade_days={self.paper_trade_days} < 60 (forward paper gate)")
            if self.regime_reported is not True:
                problems.append("ship verdict but regime_reported is not True (aggregate-only metrics hide regime failure)")
            # Millennium discipline: no stop rule ⇒ no production. Ever.
            if self.max_dd_stop is None or not self.capital_action_on_breach:
                problems.append("ship verdict but no max_dd_stop/capital_action_on_breach "
                                "(RISK_ALLOCATOR §3: a component without a stop cannot go live)")
            if self.backtest_included_stop is not True:
                problems.append("ship verdict but backtest_included_stop is not True "
                                "(a stop added AFTER the curve is self-deception — it changes the shape)")
        if self.verdict == Verdict.REFUTE and self.pit_clean and self.cost_feasible_at_5bps:
            problems.append("refute verdict but all validity flags True — contradiction")
        return problems


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
