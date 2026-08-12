"""
Guard: universe membership is RECOMPUTED, and cannot see the future (S-153).

WHAT WAS MEASURED, live, 2026-08-12:

    universe_membership WHERE universe='investable'
      75 rows · valid_from = 2025-05-03 or 2025-06-20 for EVERY asset,
      including BTC · valid_to NULL on all 75 · zero exits ever recorded

So the "investable universe" has one birthday and no deaths. It is a snapshot of
what was in the CIS set the day the table was written, and every backtest that
filtered on it was holding, in 2021, a basket selected for surviving to 2026.

The `coverage` universe, by contrast, DOES carry the truth: 488 listings back to
2015 and **125 recorded delistings**. The history was never missing — it was
never used.

WHY THE GUARD IS A TRUNCATION TEST. "Does this function look ahead" cannot be
settled by reading it; look-ahead enters through a window boundary, a `<=` that
should be `<`, or a provider that helpfully back-fills. So the property asserted
here is behavioural and total:

    investable_universe(as_of, full_panel)
      ==
    investable_universe(as_of, panel_truncated_at(as_of))

If any datum on or after `as_of` reaches the answer, those differ. A function
that passes this cannot peek, whatever its internals do next month.

The three rules each have a failure behind them:
  · FAIL CLOSED — missing volume excludes. "No data" is not evidence of
    liquidity, and the cheap default is how a thin name walks into a backtest.
  · SEASONING — a token that 5x'd in listing week tops any momentum rank and no
    fund could have held it at size. This is Jazz's objection made executable.
  · DELISTED ASSETS ARE MEMBERS before their exit. A universe that only knows
    today's survivors cannot produce an honest 2022.

Run: python3 -m tests.test_universe_is_point_in_time
"""
from __future__ import annotations

import datetime as dt
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


D = dt.date


class FakePanel:
    """Deterministic panel. `cutoff` truncates every series, which is how the
    look-ahead property is exercised: the same question, asked of a panel that
    literally cannot contain the future."""

    def __init__(self, rows: dict, listings: dict, scores: dict, cutoff: D | None = None):
        self.rows, self.listings, self.scores, self.cutoff = rows, listings, scores, cutoff

    def symbols(self):
        return sorted(self.listings)

    def listed_range(self, s):
        return self.listings.get(s)

    def has_score(self, s, as_of):
        d = self.scores.get(s)
        return d is not None and d <= as_of

    def adv_usd(self, s, window_end, days):
        series = self.rows.get(s, {})
        vals = []
        for i in range(1, days + 1):
            d = window_end - dt.timedelta(days=i)          # STRICTLY before
            if self.cutoff and d >= self.cutoff:
                continue
            if d not in series:
                return None                                 # fail closed
            vals.append(series[d])
        if len(vals) < days:
            return None
        vals.sort()
        return vals[len(vals) // 2]


def _panel(cutoff=None):
    base = D(2026, 1, 1)
    rows, listings, scores = {}, {}, {}

    def add(sym, adv, listed, delisted=None, spike_after=None):
        listings[sym] = (listed, delisted)
        scores[sym] = listed
        rows[sym] = {}
        for i in range(-400, 400):
            d = base + dt.timedelta(days=i)
            if d < listed or (delisted and d >= delisted):
                continue
            # A future spike. If it reaches an as_of BEFORE it happens, the
            # function looked ahead.
            rows[sym][d] = adv * (100.0 if spike_after and d >= spike_after else 1.0)

    add("BIG",   50_000_000, D(2020, 1, 1))
    add("MID",    8_000_000, D(2020, 1, 1))
    add("THIN",     900_000, D(2020, 1, 1))                     # below the floor
    add("DEAD",  40_000_000, D(2020, 1, 1), delisted=D(2026, 3, 1))
    add("NEW",   90_000_000, D(2025, 12, 1))                    # unseasoned at as_of
    add("LATER",    100_000, D(2020, 1, 1), spike_after=D(2026, 2, 1))
    return FakePanel(rows, listings, scores, cutoff)


def _params(**over):
    from src.data.signals.strategy_params import ParamSet, NS_INVESTABLE
    from src.data.universe.investable import FALLBACK_PARAMS
    return ParamSet(NS_INVESTABLE, {**FALLBACK_PARAMS, **over}, -1, "code_fallback")


def test_truncating_the_future_changes_nothing() -> None:
    """THE guard. Everything else in this file is a special case of it."""
    from src.data.universe.investable import investable_universe
    as_of = D(2026, 1, 15)
    full = investable_universe(as_of, _panel(), _params())
    trunc = investable_universe(as_of, _panel(cutoff=as_of), _params())
    check("full panel == panel truncated at as_of",
          full.members == trunc.members,
          f"full={full.members} truncated={trunc.members} — a datum dated on or "
          f"after as_of reached the answer")


def test_a_future_liquidity_spike_does_not_grant_membership() -> None:
    """LATER is a $100k name that 100x's its volume on 2026-02-01. Asked about
    January it must be out; asked about March, in. A single `<=` in a window
    boundary is enough to get this wrong, which is why it is asserted rather
    than reviewed."""
    from src.data.universe.investable import investable_universe
    before = investable_universe(D(2026, 1, 15), _panel(), _params())
    after = investable_universe(D(2026, 3, 15), _panel(), _params())
    check("thin name excluded BEFORE its volume arrives",
          "LATER" not in before, str(before.excluded.get("LATER")))
    check("same name included AFTER it is genuinely liquid",
          "LATER" in after, str(after.excluded.get("LATER")))


def test_delisted_assets_are_members_before_they_die() -> None:
    """125 delistings sit in universe_membership.coverage. A backtest that
    cannot hold them is a backtest of survivors."""
    from src.data.universe.investable import investable_universe
    alive = investable_universe(D(2026, 1, 15), _panel(), _params())
    later = investable_universe(D(2026, 4, 1), _panel(), _params())
    check("DEAD is a member while it traded", "DEAD" in alive, str(alive.excluded.get("DEAD")))
    check("DEAD is excluded after its delisting", "DEAD" not in later,
          "a delisted asset stayed in the universe")
    check("and the reason is recorded, not silent",
          "delisted" in (later.excluded.get("DEAD") or ""), str(later.excluded.get("DEAD")))


def test_missing_data_excludes_rather_than_admits() -> None:
    """Rule 2. Silence is not a yes."""
    from src.data.universe.investable import investable_universe
    p = _panel()
    del p.rows["MID"]                       # volume vanishes entirely
    snap = investable_universe(D(2026, 1, 15), p, _params())
    check("an asset with no volume data is excluded", "MID" not in snap,
          "missing data was treated as passing the liquidity floor")
    check("the exclusion says why", "no volume" in (snap.excluded.get("MID") or ""),
          str(snap.excluded.get("MID")))


def test_seasoning_keeps_listing_pumps_out() -> None:
    from src.data.universe.investable import investable_universe
    snap = investable_universe(D(2026, 1, 15), _panel(), _params())
    check("a 45-day-old $90M listing is still excluded", "NEW" not in snap,
          str(snap.excluded.get("NEW")))
    check("the reason names seasoning",
          "seasoning" in (snap.excluded.get("NEW") or ""), str(snap.excluded.get("NEW")))


def test_the_liquidity_floor_actually_binds() -> None:
    from src.data.universe.investable import investable_universe
    snap = investable_universe(D(2026, 1, 15), _panel(), _params())
    check("BIG and MID are in", "BIG" in snap and "MID" in snap, str(snap.members))
    check("THIN is out on ADV", "THIN" not in snap, str(snap.excluded.get("THIN")))
    check("the reason carries the number",
          "ADV $" in (snap.excluded.get("THIN") or ""), str(snap.excluded.get("THIN")))


def test_the_snapshot_can_name_the_rule_that_produced_it() -> None:
    """A backtest result that cannot say which universe rule produced it is a
    result nobody can reproduce — which is the whole reason this exists."""
    from src.data.universe.investable import investable_universe
    snap = investable_universe(D(2026, 1, 15), _panel(), _params())
    st = snap.stamp()
    for k in ("universe_ns", "universe_param_version", "universe_param_source", "universe_n"):
        check(f"stamp carries {k}", k in st, str(st))


def test_a_floorless_or_seasonless_rule_cannot_load() -> None:
    """The thresholds live in strategy_params, so the way this regresses is a
    bad parameter row, not a bad commit."""
    from src.data.signals.strategy_params import validate, NS_INVESTABLE
    ok = validate(NS_INVESTABLE, {"min_adv_usd": 5e6, "adv_window_days": 30,
                                  "min_history_days": 180})
    check("a sane rule validates", not ok, str(ok))
    for bad, word in (({"min_adv_usd": 0, "adv_window_days": 30, "min_history_days": 180}, "liquidity floor"),
                      ({"min_adv_usd": 5e6, "adv_window_days": 30, "min_history_days": 5}, "listing pumps"),
                      ({"min_adv_usd": 5e6, "adv_window_days": 1, "min_history_days": 180}, "single event")):
        probs = " ".join(validate(NS_INVESTABLE, bad))
        check(f"rejected: {word}", word in probs, probs[:120])


if __name__ == "__main__":
    print("── universe membership is recomputed, not inherited (S-153) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ the future cannot reach into the past through the universe")
