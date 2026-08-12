"""
Guard: the execution log records what did NOT fill (S-155).

WHY THIS IS THE WHOLE TEST. Posted orders fill through adverse selection — you
get the fill when the market comes to you, which is when it is moving against
you. So a log containing only fills measures execution as excellent and deletes
the tracking error. It is the survivorship problem moved one layer down, and it
is easier to commit here than anywhere else, because an unfilled order leaves no
trace in the account, the P&L, or the exchange statement. Nothing except this
log will ever notice it is missing.

WHAT IT IS FOR. At $10k the capacity ceiling does not bind (2.8% utilisation
against $360k) and impact is zero. The spread does not go away, and the spread
is the entire cost:

    the whole Binance VIP ladder, VIP0 -> VIP9   ~3.3 bps
    maker vs taker fee at VIP0                   ~3   bps
    crossing a $1-2M ADV alt perp spread         25-50 bps

R66-C assumed 10 bps and showed break-even at 150 bps — but that ladder priced
FEES. At ~28 rebalances/yr, 50 bps of spread is 56%/yr against a realised
~96%/yr. Every backtest here has guessed the number that decides the sleeve, and
$10k buys the measurement.

Run: python3 -m tests.test_fill_log_records_the_misses
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _intent(iid="i1", side="buy", mid=100.0, bid=99.9, ask=100.1, notional=5000.0):
    from src.data.execution.fill_log import Intent
    return Intent(intent_id=iid, ts_decision="2026-08-17T00:00:00Z", symbol="RUNE",
                  side=side, target_notional_usd=notional, decision_mid=mid,
                  decision_bid=bid, decision_ask=ask, sleeve="r66c", order_type="maker")


def _out(iid="i1", status="filled", px=100.0, notional=5000.0, fee=1.0,
         liq="maker", mid_resolve=None):
    from src.data.execution.fill_log import Outcome
    return Outcome(intent_id=iid, ts_resolved="2026-08-17T00:05:00Z", status=status,
                   filled_notional_usd=notional, avg_fill_price=px, fee_usd=fee,
                   liquidity=liq, mid_at_resolve=mid_resolve)


def test_slippage_sign_is_right_in_both_directions() -> None:
    """Getting this backwards produces a log that reports every trade as
    profitable execution — a believable wrong answer that survives review."""
    from src.data.execution.fill_log import slippage_bps
    buy = slippage_bps(_intent(side="buy"), _out(px=100.1))     # paid the ask
    sell = slippage_bps(_intent(side="sell"), _out(px=99.9))    # hit the bid
    check("buying above mid is a COST", buy is not None and buy > 0, str(buy))
    check("selling below mid is a COST", sell is not None and sell > 0, str(sell))
    check("both are ~10bps on a 20bps spread",
          abs(buy - 10) < 0.2 and abs(sell - 10) < 0.2, f"{buy} / {sell}")
    good = slippage_bps(_intent(side="buy"), _out(px=99.95))    # posted, filled inside
    check("filling inside the spread is a GAIN", good is not None and good < 0, str(good))


def test_an_expired_order_carries_its_opportunity_cost() -> None:
    """The half a fills-only log deletes. A posted order that expires because
    price ran away is the expensive outcome and leaves no trace anywhere else."""
    from src.data.execution.fill_log import opportunity_bps, EXPIRED
    o = _out(status=EXPIRED, notional=0.0, px=None, fee=0.0, liq=None, mid_resolve=101.0)
    cost = opportunity_bps(_intent(side="buy"), o)
    check("an unfilled buy into a rising market is a cost",
          cost is not None and cost > 90, str(cost))
    o2 = _out(status=EXPIRED, notional=0.0, px=None, fee=0.0, liq=None, mid_resolve=99.0)
    check("an unfilled buy into a falling market is a saving",
          (opportunity_bps(_intent(side="buy"), o2) or 0) < 0, "")
    part = _out(status="partial", notional=2500.0, px=100.0, mid_resolve=101.0)
    half = opportunity_bps(_intent(side="buy"), part)
    check("a half fill carries half the opportunity cost",
          half is not None and abs(half - 50) < 1, str(half))


def test_a_perfect_fill_rate_on_posted_orders_is_flagged_as_missing_data() -> None:
    """THE guard. 100% fills on passive orders is not excellent execution, it is
    the signature of unlogged misses. Nothing can verify from inside that the
    expiries were written — so the suspicious case is called out by name."""
    from src.data.execution.fill_log import execution_quality
    pairs = [(_intent(f"i{k}"), _out(f"i{k}", px=99.95)) for k in range(40)]
    q = execution_quality(pairs)
    check("fill_rate 1.00 with maker fills raises the flag",
          "never written" in q.note or "not actually passive" in q.note, q.note[:110])
    check("fill_rate is reported prominently", q.fill_rate == 1.0, str(q.fill_rate))


def test_shortfall_is_decomposed_not_a_single_number() -> None:
    """Spread, fees and unfilled cost have different fixes — an order-type
    decision, a venue decision, and a patience-vs-tracking tradeoff. One blended
    number is how '150bps break-even' came to read as safety."""
    from src.data.execution.fill_log import execution_quality, EXPIRED
    pairs = [(_intent(f"f{k}"), _out(f"f{k}", px=100.1, fee=2.5)) for k in range(20)]
    pairs += [(_intent(f"e{k}"), _out(f"e{k}", status=EXPIRED, notional=0.0, px=None,
                                      fee=0.0, liq=None, mid_resolve=100.5))
              for k in range(20)]
    q = execution_quality(pairs)
    for f in ("mean_slippage_bps", "mean_fee_bps", "mean_opportunity_bps"):
        check(f"{f} reported separately", getattr(q, f) is not None, str(q))
    check("shortfall is the sum of the parts",
          q.implementation_shortfall_bps is not None
          and abs(q.implementation_shortfall_bps
                  - (q.mean_slippage_bps + q.mean_fee_bps + q.mean_opportunity_bps)) < 1e-6,
          str(q))
    check("fill rate reflects the misses", abs(q.fill_rate - 0.5) < 1e-9, str(q.fill_rate))


def test_the_quoted_spread_is_captured_at_decision_time() -> None:
    """The number every backtest assumed and none observed. Captured at DECISION
    time, not at placement: the decision->placement delay is a real cost a
    systematic book controls, and anchoring on arrival price hides it."""
    from src.data.execution.fill_log import execution_quality
    q = execution_quality([(_intent(f"s{k}"), _out(f"s{k}")) for k in range(31)])
    check("median quoted spread is reported",
          q.median_quoted_spread_bps is not None and abs(q.median_quoted_spread_bps - 20) < 0.5,
          str(q.median_quoted_spread_bps))
    i = _intent()
    check("Intent computes its own quoted spread",
          i.decision_spread_bps is not None, str(i.decision_spread_bps))


def test_an_empty_log_says_so_instead_of_returning_zero() -> None:
    """Zero cost and no data must not render identically — that is S-131's shape
    and it has cost this repo four separate incidents."""
    from src.data.execution.fill_log import execution_quality
    q = execution_quality([])
    check("no data -> None, not 0.0", q.implementation_shortfall_bps is None, str(q))
    check("and it says why", "no intents" in q.note, q.note)


def test_a_non_terminal_outcome_is_refused() -> None:
    """An intent resolved to 'working' would sit unresolved forever while
    looking answered."""
    import asyncio
    from src.data.execution.fill_log import write_outcome, Outcome
    o = Outcome(intent_id="x", ts_resolved="2026-08-17T00:00:00Z", status="working")
    check("non-terminal status refused", asyncio.run(write_outcome(o)) is False, "")


if __name__ == "__main__":
    print("── the execution log records the misses (S-155) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ an order that did not fill is data, not the absence of data")
