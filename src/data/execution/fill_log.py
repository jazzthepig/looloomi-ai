"""
Execution log — the one input a backtest cannot have (S-155).

WHY. Next week the book goes live at $10k. At that size the capacity constraint
does not bind (utilisation 2.8% of a $360k ceiling) and market impact is zero.
What does NOT go away is the SPREAD, and the spread is the whole cost:

    the entire Binance VIP ladder, VIP0 -> VIP9      ~3.3 bps
    maker vs taker fee at VIP0 (2 vs 5 bps)          ~3   bps
    crossing the spread on a $1-2M ADV alt perp      25-50 bps

R66-C assumed 10 bps round-trip and its S4 ladder showed break-even at 150 bps,
which reads as 15x headroom — but that ladder priced FEES. At ~28 rebalances a
year the cost model is `(bps/1e4) x 2 x 2` per rebalance, so 50 bps is 56%/yr
against a realised ~96%/yr. Every backtest in this repo has been guessing at the
number that decides the sleeve.

So the point of a small account is not the P&L. It is that $10k buys the one
measurement 585 days of paper could not: **what we actually pay to trade.**

THE STRUCTURAL EDGE OF BEING SMALL, stated because it inverts the usual reading.
A $500M fund on a $1.2M ADV name must TAKE: it needs the fill, cannot wait, and
its order is larger than the book. At $10k you can POST and wait. That is worth
an order of magnitude more than the VIP tier we will never reach, and it applies
to exactly the thin names where R66-C's measured edge lives. A large fund
literally cannot run this strategy.

THE TRAP THIS MODULE EXISTS FOR. Posted orders fill through ADVERSE SELECTION:
you get filled when the market comes to you, which is when it is moving against
you. So a log of FILLS ONLY measures execution as excellent and hides the
tracking error entirely — the survivorship problem, moved to the execution
layer. **An order that did not fill is data, not the absence of data.** Every
intent is recorded at decision time and resolved exactly once, to a fill or to
an expiry, and the expiries carry the opportunity cost.

THE NUMBER THIS PRODUCES is implementation shortfall against the DECISION MID —
the price at the moment the signal said to trade, before any order existed.
Measuring against the arrival price of the order instead would quietly exclude
the delay between decision and placement, which is the part a systematic book
controls and therefore the part worth knowing.

    shortfall = spread_paid + fees + unfilled_opportunity_cost

Decomposed, because the three have different fixes: spread is an order-type
decision, fees are a venue decision, and unfilled cost is a patience-vs-tracking
tradeoff that only this log can price.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, asdict, field

_log = logging.getLogger("fill_log")

BUY, SELL = "buy", "sell"
MAKER, TAKER = "maker", "taker"
FILLED, PARTIAL, EXPIRED, CANCELLED = "filled", "partial", "expired", "cancelled"

_TERMINAL = (FILLED, PARTIAL, EXPIRED, CANCELLED)


@dataclass
class Intent:
    """Recorded when the SIGNAL fires, before an order exists.

    `decision_mid` is the anchor for everything downstream and must be captured
    here, not at placement: the decision→placement delay is a real cost that a
    systematic book controls, and anchoring on arrival price hides it."""
    intent_id: str
    ts_decision: str                 # ISO8601 UTC
    symbol: str
    side: str                        # buy | sell
    target_notional_usd: float
    decision_mid: float
    decision_bid: float | None = None
    decision_ask: float | None = None
    sleeve: str = ""
    signal_ref: str = ""             # which mark/row asked for this
    order_type: str = MAKER          # what we INTENDED; outcome records what happened
    limit_price: float | None = None

    @property
    def decision_spread_bps(self) -> float | None:
        """The spread we were quoted at decision time. This is the number the
        backtest assumed and never observed."""
        if self.decision_bid and self.decision_ask and self.decision_mid:
            return (self.decision_ask - self.decision_bid) / self.decision_mid * 10_000.0
        return None


@dataclass
class Outcome:
    """Exactly one per intent. `EXPIRED` with filled_qty 0 is a first-class
    result and must be written — a log that only contains fills reports the
    execution quality of the orders the market chose to give us."""
    intent_id: str
    ts_resolved: str
    status: str                      # filled | partial | expired | cancelled
    filled_notional_usd: float = 0.0
    avg_fill_price: float | None = None
    fee_usd: float = 0.0
    liquidity: str | None = None     # maker | taker, as REPORTED by the venue
    seconds_to_resolve: float | None = None
    mid_at_resolve: float | None = None   # prices the cost of NOT filling
    note: str = ""


def slippage_bps(intent: Intent, out: Outcome) -> float | None:
    """Signed cost against the decision mid. Positive = we paid.

    Sign convention is explicit because getting it backwards produces a log that
    reports every trade as profitable execution, which is exactly the kind of
    believable wrong answer that survives review."""
    if not out.avg_fill_price or not intent.decision_mid:
        return None
    d = (out.avg_fill_price - intent.decision_mid) / intent.decision_mid
    if intent.side == SELL:
        d = -d
    return d * 10_000.0


def opportunity_bps(intent: Intent, out: Outcome) -> float | None:
    """What NOT filling cost. Positive = the market left without us.

    This is the half a fills-only log deletes. A posted order that expires
    because price ran away is the expensive outcome, and it leaves no trace
    anywhere else in the system."""
    if out.status not in (EXPIRED, CANCELLED, PARTIAL):
        return None
    if not out.mid_at_resolve or not intent.decision_mid:
        return None
    d = (out.mid_at_resolve - intent.decision_mid) / intent.decision_mid
    if intent.side == SELL:
        d = -d
    unfilled = max(0.0, 1.0 - (out.filled_notional_usd / intent.target_notional_usd
                               if intent.target_notional_usd else 0.0))
    return d * 10_000.0 * unfilled


@dataclass
class ExecutionQuality:
    n_intents: int
    n_filled: int
    fill_rate: float
    notional_usd: float
    mean_slippage_bps: float | None
    mean_fee_bps: float | None
    mean_opportunity_bps: float | None
    implementation_shortfall_bps: float | None
    maker_share: float | None
    median_quoted_spread_bps: float | None
    note: str = ""


def execution_quality(pairs: list[tuple[Intent, Outcome]]) -> ExecutionQuality:
    """Aggregate. REQUIRES the unfilled intents to be present.

    It cannot verify that they were logged — nothing can, from inside — so it
    reports `fill_rate` prominently instead. A fill rate of 1.00 on posted
    orders is not excellent execution, it is a missing-data warning."""
    n = len(pairs)
    if not n:
        return ExecutionQuality(0, 0, 0.0, 0.0, None, None, None, None, None, None,
                                "no intents recorded")

    filled = [(i, o) for i, o in pairs if o.status in (FILLED, PARTIAL)
              and o.filled_notional_usd > 0]
    notional = sum(o.filled_notional_usd for _, o in filled)

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    slip = _mean([slippage_bps(i, o) for i, o in filled])
    fees = _mean([o.fee_usd / o.filled_notional_usd * 10_000.0
                  for i, o in filled if o.filled_notional_usd])
    opp = _mean([opportunity_bps(i, o) for i, o in pairs])
    spreads = sorted(v for v in (i.decision_spread_bps for i, _ in pairs) if v is not None)
    med_spread = spreads[len(spreads) // 2] if spreads else None
    mk = [o.liquidity for _, o in filled if o.liquidity]
    maker_share = (sum(1 for x in mk if x == MAKER) / len(mk)) if mk else None

    shortfall = None
    if slip is not None or fees is not None or opp is not None:
        shortfall = (slip or 0.0) + (fees or 0.0) + (opp or 0.0)

    fr = len(filled) / n
    note = ""
    if fr >= 0.999 and (maker_share or 0) > 0.5:
        note = ("fill_rate = 1.00 on posted orders. Either the limits were not "
                "actually passive, or the unfilled intents were never written — "
                "and a fills-only log reports the execution quality of the orders "
                "the market chose to give us.")
    elif n < 30:
        note = f"only {n} intents — too few to price the spread; keep logging."
    return ExecutionQuality(n, len(filled), fr, notional, slip, fees, opp,
                            shortfall, maker_share, med_spread, note)


# ── durable write ────────────────────────────────────────────────────────────
async def write_intent(i: Intent) -> bool:
    from src.api.store import supabase_insert_table
    return bool(await supabase_insert_table("execution_intents", [asdict(i)]))


async def write_outcome(o: Outcome) -> bool:
    """An outcome that fails to persist leaves an intent unresolved FOREVER,
    which is the honest state: the alternative — dropping the intent too —
    would restore the fills-only bias by deletion."""
    from src.api.store import supabase_insert_table
    if o.status not in _TERMINAL:
        _log.error("[fill_log] refusing non-terminal status %r for %s",
                   o.status, o.intent_id)
        return False
    return bool(await supabase_insert_table("execution_outcomes", [asdict(o)]))
