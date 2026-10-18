"""
Reconcile module — guard that per-trade gap + daily TE + weekly summary
match what fill_log.py says they should, against fabricated pairs.

Why this test exists separately
-------------------------------
fill_log.py tests pin the SIGN CONVENTION of slippage / opportunity and the
fee handling.  This module composes those primitives into (a) a single
implementation-gap number per intent, (b) daily aggregation against paper
NAV, (c) weekly rollup.  The composition has its own failure modes — the
wrong denominator, an empty day bleeding into the next, a partial fill priced
on filled notional only — and they are not visible from fill_log's tests.

The card (T-124) is explicit: pure functions, no I/O, fake data, red-then-
green.  No Supabase, no fixtures beyond dataclass constructors.

Run: python3 -m tests.test_reconcile
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    """Merger 10-18 (§Seth-1018b-1): this used to only append to _FAILURES, and every
    test_* returned None — under pytest the file could never fail. It now raises."""
    if cond:
        print(f"  ✓ {name}")
        return
    print(f"  ✗ {name} :: {detail}")
    _FAILURES.append(name)
    raise AssertionError(f"{name} :: {detail}")


# ── fixtures ────────────────────────────────────────────────────────────────

def _intent(iid="i1", side="buy", mid=100.0, bid=99.9, ask=100.1, notional=5000.0):
    from src.data.execution.fill_log import Intent
    return Intent(intent_id=iid, ts_decision="2026-10-18T00:00:00Z", symbol="BTC",
                  side=side, target_notional_usd=notional, decision_mid=mid,
                  decision_bid=bid, decision_ask=ask, sleeve="x1v", order_type="maker")


def _out(iid="i1", status="filled", px=100.0, notional=5000.0, fee=1.5,
         liq="maker", mid_resolve=None, ts="2026-10-18T01:00:00Z"):
    from src.data.execution.fill_log import Outcome
    return Outcome(intent_id=iid, ts_resolved=ts, status=status,
                   filled_notional_usd=notional, avg_fill_price=px, fee_usd=fee,
                   liquidity=liq, mid_at_resolve=mid_resolve)


# ── per-trade gap ───────────────────────────────────────────────────────────

def test_per_trade_gap_filled_taker_has_slippage_plus_fee_no_opp() -> None:
    """Filled taker: slippage > 0 (paid ask), fee > 0, opportunity = None
    (full fill).  Total is the sum of two components."""
    from src.data.execution.reconcile import per_trade_gap
    g = per_trade_gap(
        _intent(side="buy", mid=100.0, bid=99.9, ask=100.1, notional=5000.0),
        _out(px=100.1, notional=5000.0, fee=2.5, liq="taker"),
    )
    check("slippage is ~10 bps (paid the ask)", g.slippage_bps is not None
          and abs(g.slippage_bps - 10.0) < 0.01, f"{g.slippage_bps}")
    check("fee is 5 bps of filled notional", g.fee_bps is not None
          and abs(g.fee_bps - 5.0) < 0.01, f"{g.fee_bps}")
    check("opportunity is None on full fill", g.opportunity_bps is None,
          f"{g.opportunity_bps}")
    check("implementation gap = 15 bps",
          g.implementation_gap_bps is not None
          and abs(g.implementation_gap_bps - 15.0) < 0.02,
          f"{g.implementation_gap_bps}")
    check("realised cost = 0.15% of 5000 = $7.50",
          g.realised_cost_usd is not None
          and abs(g.realised_cost_usd - 7.50) < 0.01,
          f"{g.realised_cost_usd}")


def test_per_trade_gap_sell_side_sign_is_a_cost() -> None:
    """Selling below the decision_mid is a COST (positive slippage_bps).
    Symmetric with the buy case — getting the sign backwards reports every
    sell as profitable execution."""
    from src.data.execution.reconcile import per_trade_gap
    g = per_trade_gap(
        _intent(side="sell", mid=100.0, bid=99.9, ask=100.1),
        _out(px=99.9, notional=5000.0, fee=2.5, liq="taker"),
    )
    check("selling at the bid is a COST (~10 bps)",
          g.slippage_bps is not None and g.slippage_bps > 0
          and abs(g.slippage_bps - 10.0) < 0.01, f"{g.slippage_bps}")


def test_per_trade_gap_posted_inside_the_spread_is_a_gain() -> None:
    """Posted maker filled inside the spread: slippage_bps is NEGATIVE
    (price improvement).  This is the half of execution quality a fills-only
    log makes invisible — when it gets deleted, every trade looks like a
    pure cost."""
    from src.data.execution.reconcile import per_trade_gap
    g = per_trade_gap(
        _intent(side="buy", mid=100.0, bid=99.9, ask=100.1),
        _out(px=99.95, notional=5000.0, fee=1.0, liq="maker"),
    )
    check("filling inside the spread is a GAIN (negative slippage)",
          g.slippage_bps is not None and g.slippage_bps < 0, f"{g.slippage_bps}")
    check("fee is still positive on maker fill",
          g.fee_bps is not None and g.fee_bps > 0, f"{g.fee_bps}")


def test_per_trade_gap_expired_order_carries_only_opp_cost() -> None:
    """Expired with zero filled: slippage and fee are both None
    (no fill happened — there is no fee and no price to slip against),
    opportunity_bps > 0 (the market left without us).  Total = opp only.
    This is the row that disappears in a fills-only log."""
    from src.data.execution.reconcile import per_trade_gap
    from src.data.execution.fill_log import EXPIRED
    g = per_trade_gap(
        _intent(side="buy", mid=100.0, notional=5000.0),
        _out(status=EXPIRED, px=None, notional=0.0, fee=0.0, liq=None,
             mid_resolve=101.0),
    )
    check("no slippage on unfilled", g.slippage_bps is None, str(g.slippage_bps))
    check("no fee on unfilled", g.fee_bps is None, str(g.fee_bps))
    check("opportunity cost > 0 (price ran away)",
          g.opportunity_bps is not None and g.opportunity_bps > 0
          and abs(g.opportunity_bps - 100.0) < 0.01, f"{g.opportunity_bps}")
    check("gap = opportunity cost on full expiry",
          g.implementation_gap_bps is not None
          and abs(g.implementation_gap_bps - 100.0) < 0.01,
          f"{g.implementation_gap_bps}")


def test_per_trade_gap_partial_fill_has_all_three_components() -> None:
    """Partial fill: half filled (slippage + fee on the filled half),
    half expired (opportunity on the unfilled half).  Each of the three
    components lives in a different denominator BEFORE the gap is summed —
    slippage / fee are bps of FILLED notional, opportunity is already in
    bps of TARGET notional (it bakes in the unfilled ratio).  The gap
    scales the filled-denominated parts by filled/target so the sum is in
    a single denominator (target).  Without that scaling, partial fills
    inflated slippage + fee by target/filled, the original denominator
    bug."""
    from src.data.execution.reconcile import per_trade_gap
    from src.data.execution.fill_log import PARTIAL
    g = per_trade_gap(
        _intent(side="buy", mid=100.0, notional=10000.0),
        _out(status=PARTIAL, px=100.1, notional=5000.0, fee=2.5,
              liq="taker", mid_resolve=101.0),
    )
    check("slippage on filled half is ~10 bps (raw, of filled notional)",
          g.slippage_bps is not None and abs(g.slippage_bps - 10.0) < 0.01,
          f"{g.slippage_bps}")
    check("fee on filled half (5000 notional, 2.5 fee) = 5 bps (raw)",
          g.fee_bps is not None and abs(g.fee_bps - 5.0) < 0.01, f"{g.fee_bps}")
    check("opportunity on unfilled half: 100 bps * 0.5 = 50 bps (already bps-of-target)",
          g.opportunity_bps is not None
          and abs(g.opportunity_bps - 50.0) < 0.01, f"{g.opportunity_bps}")
    # All three components expressed in target-notional bps:
    # slippage 10 * 0.5 = 5, fee 5 * 0.5 = 2.5, opp 50.  Total 57.5.
    check("gap = 10*0.5 + 5*0.5 + 50 = 57.5 bps (single denominator)",
          g.implementation_gap_bps is not None
          and abs(g.implementation_gap_bps - 57.5) < 0.01,
          f"{g.implementation_gap_bps}")
    check("realised cost = 57.5 bps of $10000 target = $57.50",
          g.realised_cost_usd is not None
          and abs(g.realised_cost_usd - 57.50) < 0.01,
          f"{g.realised_cost_usd}")


def test_per_trade_gap_partial_fill_denominator_demonstrated() -> None:
    """Seth 10-18 spec: 50% fill, 10 bps slippage, 5 bps fee, 100 bps
    opportunity ⇒ gap = 5 + 2.5 + 50 = 57.5 bps.  Pinning the exact number
    so the denominator fix can never silently revert."""
    from src.data.execution.reconcile import per_trade_gap
    from src.data.execution.fill_log import PARTIAL
    g = per_trade_gap(
        _intent(side="buy", mid=100.0, notional=10000.0),
        _out(status=PARTIAL, px=100.1, notional=5000.0, fee=2.5,
              liq="taker", mid_resolve=101.0),
    )
    check("gap = 5 + 2.5 + 50 = 57.5 bps (Seth spec)",
          g.implementation_gap_bps is not None
          and abs(g.implementation_gap_bps - 57.5) < 0.01,
          f"{g.implementation_gap_bps}")


def test_fee_bps_returns_none_when_nothing_filled() -> None:
    """No fill → no fee denominator → None.  Returning 0.0 would claim the
    fee was zero, which is a different (and survivorship-biased) claim."""
    from src.data.execution.reconcile import fee_bps
    from src.data.execution.fill_log import EXPIRED
    o = _out(status=EXPIRED, notional=0.0, fee=0.0, px=None, liq=None,
             mid_resolve=100.5)
    check("fee_bps(None) on unfilled", fee_bps(o) is None, str(fee_bps(o)))


# ── daily tracking error ────────────────────────────────────────────────────

def test_daily_te_aggregates_per_trade_into_per_day_bps_of_nav() -> None:
    """Two intents resolving on the same day, paper NAV = $1M.  Total cost
    in USD → divided by NAV → bps.  Per-event day, NOT zero-filling."""
    from src.data.execution.reconcile import daily_tracking_error
    pairs = [
        (_intent("a", notional=50000.0), _out("a", px=100.1, notional=50000.0,
                                              fee=25.0, liq="taker",
                                              ts="2026-10-18T03:00:00Z")),
        (_intent("b", notional=50000.0), _out("b", px=99.95, notional=50000.0,
                                              fee=10.0, liq="maker",
                                              ts="2026-10-18T15:30:00Z")),
    ]
    paper = {dt.date(2026, 10, 18): 1_000_000.0}
    te = daily_tracking_error(pairs, paper)
    check("exactly one day returned", len(te) == 1, str(len(te)))
    d = te[dt.date(2026, 10, 18)]
    # a: slip = +10bps, fee = +5bps (25/50000*1e4).  b: slip = -5bps, fee = +2bps.
    # a USD = 50000 * 15 / 1e4 = $75.  b USD = 50000 * (-3) / 1e4 = -$15.
    # total USD = 60.  bps of $1M = 60/1e6 * 1e4 = 0.6 bps
    check("n_intents = 2", d.n_intents == 2, str(d.n_intents))
    check("sum_realised_cost_usd ≈ $60", abs(d.sum_realised_cost_usd - 60.0) < 0.5,
          f"{d.sum_realised_cost_usd}")
    check("weighted_gap_bps ≈ 0.6 (60 USD on 1M NAV)",
          abs(d.weighted_gap_bps - 0.6) < 0.01, f"{d.weighted_gap_bps}")
    check("paper_nav recorded", d.paper_nav == 1_000_000.0, str(d.paper_nav))


def test_daily_te_does_not_zero_fill_days_without_events() -> None:
    """A NAV series spanning 3 days with events on day 2 only: result must
    contain ONLY day 2.  Day 1 and 3 are 'not measured', not 'zero TE' —
    returning them would silently pad the weekly rollup with zeros."""
    from src.data.execution.reconcile import daily_tracking_error
    pairs = [(_intent("a"), _out("a", ts="2026-10-19T10:00:00Z"))]
    paper = {
        dt.date(2026, 10, 18): 1_000_000.0,
        dt.date(2026, 10, 19): 1_005_000.0,
        dt.date(2026, 10, 20): 998_000.0,
    }
    te = daily_tracking_error(pairs, paper)
    check("only one day returned (the one that had events)",
          list(te.keys()) == [dt.date(2026, 10, 19)], str(list(te.keys())))


def test_daily_te_handles_missing_paper_nav_gracefully() -> None:
    """No paper NAV for the resolve date → weighted_gap_bps is None (was 0.0, which read as a perfect day)
    (degenerate denominator; the day's USD cost is still recorded).  The
    alternative — NaN, or division error — would mask the cost and force a
    reviewer to chase where it went."""
    from src.data.execution.reconcile import daily_tracking_error
    pairs = [(_intent("a", notional=10000.0),
              _out("a", px=100.1, notional=10000.0, fee=5.0, liq="taker",
                   ts="2026-10-21T10:00:00Z"))]
    te = daily_tracking_error(pairs, {})  # no NAV passed
    d = te[dt.date(2026, 10, 21)]
    check("paper_nav is None", d.paper_nav is None, str(d.paper_nav))
    check("weighted_gap_bps is None (no denominator — not computable, not 0)", d.weighted_gap_bps is None,
          str(d.weighted_gap_bps))
    check("USD cost still recorded",
          abs(d.sum_realised_cost_usd - 15.0) < 0.5,
          f"{d.sum_realised_cost_usd}")


def test_daily_te_empty_pairs_returns_empty_dict() -> None:
    """No events at all → empty dict, not a fake-zero day."""
    from src.data.execution.reconcile import daily_tracking_error
    te = daily_tracking_error([], {dt.date(2026, 10, 18): 1_000_000.0})
    check("empty pairs → empty daily dict", te == {}, str(te))


def test_resolve_date_offset_bearing_iso8601_lands_on_utc_date() -> None:
    """Seth 10-18 spec: ``2026-10-18T08:00:00+09:00`` is 23:00 UTC on
    2026-10-17.  The old ``[:10]`` slice returned "2026-10-18" — the LOCAL
    date — placing the event on the wrong day and one day's TE on the wrong
    bucket.  The fix parses the offset, anchors UTC, takes the date."""
    from src.data.execution.reconcile import _resolve_date
    from src.data.execution.fill_log import Outcome
    o = Outcome(intent_id="x", ts_resolved="2026-10-18T08:00:00+09:00",
                status="filled", filled_notional_usd=1000.0)
    check("+09:00 08:00 lands on UTC 2026-10-17",
          _resolve_date(o) == dt.date(2026, 10, 17), str(_resolve_date(o)))


def test_resolve_date_naive_iso8601_is_treated_as_utc() -> None:
    """Naive timestamps get a UTC anchor before date extraction, per §5c —
    the discipline is UTC dates everywhere, JST is display-only.  A Mac
    writing in JST at 15:01 UTC would otherwise silently stamp tomorrow's
    date on the row."""
    from src.data.execution.reconcile import _resolve_date
    from src.data.execution.fill_log import Outcome
    o = Outcome(intent_id="x", ts_resolved="2026-10-18T03:00:00",
                status="filled", filled_notional_usd=1000.0)
    check("naive 2026-10-18T03:00:00 → 2026-10-18",
          _resolve_date(o) == dt.date(2026, 10, 18), str(_resolve_date(o)))


def test_resolve_date_explicit_utc_marker() -> None:
    """An explicit Z suffix also routes through UTC; the parse handles both
    ``Z`` (which fromisoformat accepts in 3.11+) and ``+00:00``."""
    from src.data.execution.reconcile import _resolve_date
    from src.data.execution.fill_log import Outcome
    o = Outcome(intent_id="x", ts_resolved="2026-10-18T23:30:00+00:00",
                status="filled", filled_notional_usd=1000.0)
    check("+00:00 23:30 → 2026-10-18",
          _resolve_date(o) == dt.date(2026, 10, 18), str(_resolve_date(o)))


# ── weekly summary ───────────────────────────────────────────────────────────

def test_weekly_summary_rolls_up_two_days_in_same_week() -> None:
    """Two event-days in the same ISO week (Mon 2026-10-19 + Wed 2026-10-21
    are both ISO week 2026-W43).  Mean and cumulative both populated."""
    from src.data.execution.reconcile import (daily_tracking_error,
                                               weekly_summary)
    pairs = [
        (_intent("a", notional=10000.0),
         _out("a", px=100.1, notional=10000.0, fee=5.0, liq="taker",
              ts="2026-10-19T10:00:00Z")),
        (_intent("b", notional=10000.0),
         _out("b", px=100.2, notional=10000.0, fee=5.0, liq="taker",
              ts="2026-10-21T10:00:00Z")),
    ]
    paper = {
        dt.date(2026, 10, 19): 1_000_000.0,
        dt.date(2026, 10, 21): 1_001_000.0,
    }
    daily = daily_tracking_error(pairs, paper)
    weekly = weekly_summary(daily)
    check("exactly one ISO week", len(weekly) == 1, str(len(weekly)))
    w = next(iter(weekly.values()))
    check("ISO year-week = (2026, 43)",
          (w.iso_year, w.iso_week) == (2026, 43), f"{w.iso_year}-{w.iso_week}")
    check("week_start = Monday 2026-10-19",
          w.week_start == dt.date(2026, 10, 19), str(w.week_start))
    check("n_days_with_events = 2", w.n_days_with_events == 2, str(w.n_days_with_events))
    check("n_intents = 2", w.n_intents == 2, str(w.n_intents))
    check("sum cost > 0", w.sum_realised_cost_usd > 0,
          f"{w.sum_realised_cost_usd}")


def test_weekly_summary_separates_two_weeks() -> None:
    """Events spanning a week boundary produce TWO weekly entries, not one
    averaged blob.  ISO 2026-W43 ends Sun 2026-10-25; W44 starts Mon
    2026-10-26."""
    from src.data.execution.reconcile import (daily_tracking_error,
                                               weekly_summary)
    pairs = [
        (_intent("a", notional=10000.0),
         _out("a", px=100.1, notional=10000.0, fee=5.0, liq="taker",
              ts="2026-10-21T10:00:00Z")),
        (_intent("b", notional=10000.0),
         _out("b", px=100.1, notional=10000.0, fee=5.0, liq="taker",
              ts="2026-10-28T10:00:00Z")),
    ]
    paper = {dt.date(2026, 10, 21): 1_000_000.0,
             dt.date(2026, 10, 28): 1_002_000.0}
    daily = daily_tracking_error(pairs, paper)
    weekly = weekly_summary(daily)
    check("two weeks returned", len(weekly) == 2, str(len(weekly)))
    keys = sorted(weekly.keys())
    check("weeks are W43 and W44", keys == [(2026, 43), (2026, 44)], str(keys))


def test_weekly_summary_empty_daily_returns_empty_dict() -> None:
    """No events → empty weekly dict (matches daily semantics)."""
    from src.data.execution.reconcile import weekly_summary
    check("empty daily → empty weekly", weekly_summary({}) == {}, "")


def test_check_really_fails() -> None:
    """Red-then-green proof for the harness itself: a false condition must raise."""
    try:
        check("deliberately false", False, "expected")
    except AssertionError:
        _FAILURES.remove("deliberately false")
        return
    raise AssertionError("check() swallowed a failure — the suite could never go red")


def test_weekly_cumulative_uses_the_earliest_nav_in_the_week_not_monday() -> None:
    """Monday has no event (the usual case); the week's events are on Wednesday. The
    cumulative figure must come from the earliest paper NAV in that week, and a week with
    no paper NAV at all is None — never 0 bps."""
    from src.data.execution.reconcile import daily_tracking_error, weekly_summary
    wed = "2026-10-21T01:00:00+00:00"                     # ISO week 43, Monday = 10-19
    pairs = [(_intent(notional=10_000.0), _out(px=100.2, notional=10_000.0, fee=2.0, ts=wed))]
    paper = {dt.date(2026, 10, 19): 1_000_000.0, dt.date(2026, 10, 21): 1_010_000.0}
    daily = daily_tracking_error(pairs, paper)
    w = weekly_summary(daily, paper)[(2026, 43)]
    cost = daily[dt.date(2026, 10, 21)].sum_realised_cost_usd
    check("cumulative uses Monday's NAV from paper_nav", abs(w.cumulative_gap_bps - cost / 1_000_000.0 * 1e4) < 1e-9,
          str(w.cumulative_gap_bps))
    w2 = weekly_summary(daily)[(2026, 43)]
    check("without paper_nav, falls back to the event day's NAV", abs(w2.cumulative_gap_bps - cost / 1_010_000.0 * 1e4) < 1e-9,
          str(w2.cumulative_gap_bps))
    nonav = daily_tracking_error(pairs, {})
    w3 = weekly_summary(nonav)[(2026, 43)]
    check("no NAV anywhere in the week ⇒ None, not 0", w3.cumulative_gap_bps is None and w3.mean_weighted_gap_bps is None,
          f"{w3.cumulative_gap_bps} {w3.mean_weighted_gap_bps}")


def test_resolve_date_is_utc_even_with_an_offset() -> None:
    from src.data.execution.reconcile import _resolve_date
    check("+09:00 08:00 is the previous UTC day", _resolve_date(_out(ts="2026-10-18T08:00:00+09:00")) == dt.date(2026, 10, 17),
          "")


def _run_all() -> None:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"\n— {t.__name__} —")
        try:
            t()
        except AssertionError:
            pass                     # recorded in _FAILURES by check()
    print()
    if _FAILURES:
        print(f"FAILED: {len(_FAILURES)} / {len(tests)} :: {_FAILURES}")
        sys.exit(1)
    print(f"OK: {len(tests)} tests passed.")


if __name__ == "__main__":
    _run_all()