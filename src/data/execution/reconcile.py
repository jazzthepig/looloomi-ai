"""
Reconcile live (or dry-run) execution against the paper book.

Why this exists separately from fill_log.py
--------------------------------------------
fill_log.py answers ONE question per intent: what was the implementation cost
of this single fill, expressed as bps against the decision_mid?  Three
components — slippage (price improvement or deterioration vs decision_mid),
fee (in bps of filled notional), and unfilled opportunity cost (the cost of
NOT getting the fill, for partial / expired / cancelled orders).  It is the
per-trade ledger.

reconcile.py answers a DIFFERENT question, on a different axis:

  per-day and per-week, how far did the live book drift from the paper book?

The paper book assumes every intent fills at decision_mid; the live book pays
spread, fees, and sometimes nothing at all.  The drift is THE measurement that
decides whether the live sleeve is a faithful expression of the backtest or a
shadow of it.  R66-C assumed 10 bps round-trip and showed break-even at 150
bps (S-602 sim six, X1V); the gap between that assumption and the realised
number is the number this module produces.

What this module does NOT do
----------------------------
* it does NOT touch Supabase or any persistent store — fill_log.py writes,
  this module reads what was written (or what was synthesised in a dry run);
* it does NOT compute paper NAV — the caller passes a `date -> NAV` series
  the paper book already produced;
* it does NOT judge whether the gap is "acceptable" — that is a sleeve-eval
  decision; this module only measures.

Inputs (pure, in-memory):

    pairs:           list[(Intent, Outcome)]   from fill_log.py
    paper_nav:       dict[date, float]         paper-book NAV at each UTC close

Outputs:

    list[TradeGap]                        per-intent gap, for drill-down
    dict[date, DailyTrackingError]        per-UTC-day TE, NAV-relative
    dict[(iso_year, iso_week), WeeklySummary]
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Mapping

from src.data.execution.fill_log import (
    Intent,
    Outcome,
    slippage_bps as _slippage_bps,
    opportunity_bps as _opportunity_bps,
)


def _fill_ratio(intent: Intent, outcome: Outcome) -> float:
    """filled_notional / target_notional, clamped to [0, 1].

    slippage_bps and fee_bps are denominated in FILLED notional; opportunity_bps
    already includes the unfilled multiplier internally.  To express the gap
    in a single denominator (target notional) we scale the filled-denominated
    parts by this — without it, partial fills inflate slippage + fee by the
    target/filled ratio (e.g. a 50% fill multiplies both sides by 2×)."""
    if intent.target_notional_usd <= 0:
        return 0.0
    return max(0.0, min(1.0, outcome.filled_notional_usd / intent.target_notional_usd))


# ── per-trade component: fee in bps of filled notional ──────────────────────

def fee_bps(outcome: Outcome) -> float | None:
    """Fees expressed in bps of the FILLED notional.  Returns None when no
    fill happened (no fee to express against) — matching the rule that a
    fills-only log deletes the unfilled half, so the fee number is only honest
    for orders that actually filled something."""
    if outcome.filled_notional_usd <= 0:
        return None
    return outcome.fee_usd / outcome.filled_notional_usd * 10_000.0


# ── per-trade aggregate: implementation gap (bps of intent notional) ────────

@dataclass
class TradeGap:
    """The three components sum to the implementation gap.  Each is left
    None rather than 0 when it doesn't apply (no fill → no slippage / fee;
    full fill → no opportunity cost).  The card is explicit that an unfilled
    order is data, not the absence of data — so is each absent component."""
    intent_id: str
    symbol: str
    side: str
    target_notional_usd: float
    status: str
    slippage_bps: float | None
    fee_bps: float | None
    opportunity_bps: float | None
    _fill_ratio: float = 1.0          # internal; = filled/target, clamped [0,1]

    @property
    def implementation_gap_bps(self) -> float | None:
        """Sum of the three components expressed in a single denominator —
        TARGET notional.  slippage_bps and fee_bps are bps of FILLED notional,
        opportunity_bps is already bps of target notional (it bakes in the
        unfilled ratio internally).  Mixing denominators was the original
        bug: with a 50% partial fill, the old code multiplied both sides by
        target, inflating the cost by 2×.  Scale the filled-denominated
        parts by filled/target so every term is in bps-of-target."""
        parts: list[float] = []
        if self.slippage_bps is not None:
            parts.append(self.slippage_bps * self._fill_ratio)
        if self.fee_bps is not None:
            parts.append(self.fee_bps * self._fill_ratio)
        if self.opportunity_bps is not None:
            parts.append(self.opportunity_bps)
        if not parts:
            return None
        return sum(parts)

    @property
    def realised_cost_usd(self) -> float | None:
        """Implementation gap converted to USD, weighted by target notional.
        The weighting uses TARGET notional (what we asked for), not filled,
        because the unfilled portion is itself a cost — pricing the gap on
        filled notional only would re-introduce the fills-only bias."""
        g = self.implementation_gap_bps
        if g is None:
            return None
        return g * self.target_notional_usd / 10_000.0


def per_trade_gap(intent: Intent, outcome: Outcome) -> TradeGap:
    """The full per-intent decomposition.  This is what a single trade's
    implementation gap looks like when you sit down to investigate why
    daily TE was what it was — you walk from day → intents resolved that day
    → this TradeGap per intent."""
    return TradeGap(
        intent_id=intent.intent_id,
        symbol=intent.symbol,
        side=intent.side,
        target_notional_usd=intent.target_notional_usd,
        status=outcome.status,
        slippage_bps=_slippage_bps(intent, outcome),
        fee_bps=fee_bps(outcome),
        opportunity_bps=_opportunity_bps(intent, outcome),
        _fill_ratio=_fill_ratio(intent, outcome),
    )


def per_trade_gaps(pairs: list[tuple[Intent, Outcome]]) -> list[TradeGap]:
    return [per_trade_gap(i, o) for i, o in pairs]


# ── daily tracking error ────────────────────────────────────────────────────

def _resolve_date(outcome: Outcome) -> dt.date:
    """Outcome resolution date in UTC.  Outcome.ts_resolved is ISO8601, which
    may carry an explicit offset (e.g. ``+09:00`` from a Mac writing in JST)
    or be naive.  Naive strings are treated as UTC per §5c — JST is display-
    layer only.  Slicing ``[:10]`` on an offset-bearing string picks the LOCAL
    date, not the UTC date — which placed events on the wrong day by up to
    one (and TE on the wrong bucket).  Parse to datetime, anchor to UTC, take
    the date."""
    parsed = dt.datetime.fromisoformat(outcome.ts_resolved)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).date()


@dataclass
class DailyTrackingError:
    date: dt.date
    paper_nav: float | None           # NAV passed in; None when no NAV on this date
    n_intents: int
    total_target_notional_usd: float
    total_filled_notional_usd: float
    weighted_gap_bps: float | None    # bps of paper NAV — TE expressed NAV-relative; None = no paper NAV that day (not 0)
    sum_realised_cost_usd: float      # raw USD crystallised this day

    @property
    def fill_rate(self) -> float:
        if not self.total_target_notional_usd:
            return 0.0
        return self.total_filled_notional_usd / self.total_target_notional_usd


def daily_tracking_error(
    pairs: list[tuple[Intent, Outcome]],
    paper_nav: Mapping[dt.date, float],
) -> dict[dt.date, DailyTrackingError]:
    """For each UTC date on which any outcome resolved, sum the per-trade
    implementation gap (in USD) and express it as bps of the paper NAV on
    that date.

    The choice of denominator (paper NAV, not live NAV) is deliberate: live
    NAV is contaminated by the very gap we are measuring.  The whole point
    of TE is to compare live against paper, and the denominator has to be
    the side that did NOT absorb the cost.

    Dates in `paper_nav` with no intents resolving on them are NOT returned
    — TE is a per-event quantity, and a day with no events is not a 0-bps
    day, it is a not-measured day."""
    by_date: dict[dt.date, list[tuple[Intent, Outcome]]] = {}
    for intent, outcome in pairs:
        d = _resolve_date(outcome)
        by_date.setdefault(d, []).append((intent, outcome))

    out: dict[dt.date, DailyTrackingError] = {}
    for d, day_pairs in by_date.items():
        gaps = per_trade_gaps(day_pairs)
        target_total = sum(g.target_notional_usd for g in gaps)
        filled_total = sum(o.filled_notional_usd for _, o in day_pairs)
        cost_usd = 0.0
        for g in gaps:
            c = g.realised_cost_usd
            if c is not None:
                cost_usd += c
        nav = paper_nav.get(d)
        # Merger 10-18 (§Seth-1018b-2): no paper NAV ⇒ the day's TE is NOT computable, so None —
        # a 0.0 here would read as "no tracking error" and enter the weekly mean as a perfect day.
        weighted_bps = (cost_usd / nav * 10_000.0) if (nav and nav > 0) else None
        out[d] = DailyTrackingError(
            date=d,
            paper_nav=nav,
            n_intents=len(day_pairs),
            total_target_notional_usd=target_total,
            total_filled_notional_usd=filled_total,
            weighted_gap_bps=weighted_bps,
            sum_realised_cost_usd=cost_usd,
        )
    return out


# ── weekly summary ──────────────────────────────────────────────────────────

@dataclass
class WeeklySummary:
    iso_year: int
    iso_week: int
    week_start: dt.date               # Monday of that ISO week
    n_days_with_events: int
    n_intents: int
    sum_target_notional_usd: float
    sum_filled_notional_usd: float
    sum_realised_cost_usd: float
    mean_weighted_gap_bps: float | None   # mean over event-days that HAVE a paper NAV; None if none do
    cumulative_gap_bps: float | None      # total USD / earliest paper NAV in the week; None if the week has none

    @property
    def key(self) -> tuple[int, int]:
        return (self.iso_year, self.iso_week)


def weekly_summary(
    daily: Mapping[dt.date, DailyTrackingError],
    paper_nav: Mapping[dt.date, float] | None = None,
) -> dict[tuple[int, int], WeeklySummary]:
    """Roll daily TE into ISO weeks.  Two views of the week:

        * mean_weighted_gap_bps  — typical day's bps-of-NAV cost
        * cumulative_gap_bps     — the single number you'd put in a status line

    Both are kept because the first answers "is each day drifting?" while the
    second answers "how much did the week cost?" — different questions for
    different audiences (sleeve design vs LP report)."""
    by_week: dict[tuple[int, int], list[DailyTrackingError]] = {}
    for dte in daily.values():
        iso = dte.date.isocalendar()
        by_week.setdefault((iso[0], iso[1]), []).append(dte)

    out: dict[tuple[int, int], WeeklySummary] = {}
    for key, days in by_week.items():
        ys, ws = key
        # week_start = Monday of the ISO week containing the first event-day
        first = min(d.date for d in days)
        week_start = first - dt.timedelta(days=first.weekday())
        n_intents = sum(d.n_intents for d in days)
        sum_target = sum(d.total_target_notional_usd for d in days)
        sum_filled = sum(d.total_filled_notional_usd for d in days)
        sum_cost = sum(d.sum_realised_cost_usd for d in days)
        measured = [d.weighted_gap_bps for d in days if d.weighted_gap_bps is not None]
        mean_bps = (sum(measured) / len(measured)) if measured else None
        # Merger 10-18 (§Seth-1018b-3): `daily` holds EVENT days only, so the Monday NAV was
        # usually absent and the week silently read 0 bps. Use the earliest paper NAV inside
        # the ISO week — from `paper_nav` when given (every marked day), else from the event
        # days — and None when the week has no NAV at all.
        navs = {d: v for d, v in (paper_nav or {}).items() if d.isocalendar()[:2] == key and v and v > 0}
        navs.update({d.date: d.paper_nav for d in days if d.paper_nav and d.paper_nav > 0 and d.date not in navs})
        nav_for_cum = navs[min(navs)] if navs else None
        cum_bps = (sum_cost / nav_for_cum * 10_000.0) if nav_for_cum else None
        out[key] = WeeklySummary(
            iso_year=ys, iso_week=ws, week_start=week_start,
            n_days_with_events=len(days),
            n_intents=n_intents,
            sum_target_notional_usd=sum_target,
            sum_filled_notional_usd=sum_filled,
            sum_realised_cost_usd=sum_cost,
            mean_weighted_gap_bps=mean_bps,
            cumulative_gap_bps=cum_bps,
        )
    return out