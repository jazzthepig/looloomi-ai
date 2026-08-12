"""
investable_universe(as_of) — the inclusion standard as a FUNCTION (S-153).

THE PROBLEM THIS REMOVES. Every multi-year backtest in this repo has silently
inherited today's membership list. Measured 2026-08-12:

    universe_membership, universe='investable'
      75 rows · valid_from = 2025-05-03 or 2025-06-20 for EVERY asset · valid_to
      NULL for every asset · zero exits ever recorded

That is not a point-in-time record, it is a snapshot of what happened to be in
the CIS set the day someone wrote the table. So "was this asset investable in
2021" has no stored answer, and a backtest that filters on the snapshot is
holding, in 2021, a basket chosen for having survived to 2026.

The failure is concrete, not theoretical. R66-C's reported edge sits almost
entirely in names that are too small to hold: sub-$20M ADV contributed +186.5%
of a +154.6% total, while every bucket above $20M was net negative. Run that
universe backwards and you are buying 2021 winners you could not have known
about; run it forwards and you are buying names you cannot size into.

THE INSIGHT: WE DO NOT NEED THE HISTORY TO HAVE BEEN RECORDED. We need the RULE
to be deterministic and its INPUTS to be point-in-time. Both exist already —
listing and DELISTING dates (universe_membership.coverage, 125 exits, back to
2015), volume (ohlcv), scores (cis history). So membership is RECOMPUTED, never
looked up, and survivorship stops being something to be careful about and
becomes structurally impossible.

THREE RULES, each of which has a failure behind it.

  1. NO LOOK-AHEAD BY CONSTRUCTION. Every window ends STRICTLY BEFORE `as_of`.
     The guard is not a code review, it is
     `test_universe_is_point_in_time.test_truncating_the_future_changes_nothing`:
     the answer computed on the full panel must equal the answer computed on a
     panel truncated at `as_of`. A function that passes that cannot peek.

  2. FAIL CLOSED. Missing data excludes. "We have no volume for this asset on
     that date" is not evidence of liquidity, and the cheap default — assume it
     was fine — is exactly how a delisted or thinly-traded name walks into a
     backtest. An asset must EARN inclusion; silence is not a yes.

  3. SEASONING. A newly listed asset is excluded until it has `min_history_days`
     of price. Listing pumps are the single most reliable artefact in crypto
     cross-sectional research: a token that 5x'd in its first week will top any
     momentum rank, and no fund could have held it at size. This is Jazz's
     objection, made executable.

THRESHOLDS LIVE IN `strategy_params`, not here. Raising the ADV floor from $5M
to $10M is a decision with a date, an author and an audit trail, and any
backtest run under it carries its `param_version`. A constant in this file
would make that decision invisible the moment it changed.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Iterable, Protocol

_log = logging.getLogger("investable_universe")

NS_INVESTABLE = "investable_v1"

# NEUTRAL fallback. Deliberately permissive on size and strict on seasoning:
# a too-low ADV floor produces a universe we can argue about, while a missing
# seasoning rule produces listing-pump artefacts that look like alpha. If the
# parameter row is unreachable, we would rather be visibly wrong than quietly
# wrong in the direction that manufactures performance.
FALLBACK_PARAMS = {
    "min_adv_usd": 5_000_000.0,
    "adv_window_days": 30,
    "min_history_days": 180,
    "require_score": True,
    "max_members": None,
}


def validate_investable(v: dict) -> list[str]:
    """Registered with strategy_params so the rule that gates production is the
    same object the tests assert against."""
    problems: list[str] = []
    try:
        adv = float(v["min_adv_usd"]); win = int(v["adv_window_days"])
        hist = int(v["min_history_days"])
    except (KeyError, TypeError, ValueError):
        return ["min_adv_usd / adv_window_days / min_history_days missing or non-numeric"]
    if adv <= 0:
        problems.append("min_adv_usd <= 0 — a universe with no liquidity floor is "
                        "the condition this module exists to remove")
    if win < 5:
        problems.append(f"adv_window_days={win} — a window this short measures a "
                        f"single event, not liquidity")
    if hist < 30:
        problems.append(f"min_history_days={hist} — too short to season out listing "
                        f"pumps, which are the most reliable false positive in "
                        f"crypto cross-sectional work")
    mm = v.get("max_members")
    if mm is not None and int(mm) < 4:
        problems.append("max_members < 4 — a cross-section needs something to cross")
    return problems


# ---------------------------------------------------------------------------
class PanelProvider(Protocol):
    """The three point-in-time inputs. Implemented over Supabase in production
    and over a local panel in research, so a backtest and the live book answer
    the membership question with the same code."""

    def listed_range(self, symbol: str) -> tuple[dt.date, dt.date | None]:
        """(first_seen, delisted_or_None). The second element is why delisted
        assets can be included in historical dates — the thing a snapshot of
        today's members can never do."""

    def adv_usd(self, symbol: str, window_end: dt.date, days: int) -> float | None:
        """Median daily USD volume over `days` ending STRICTLY BEFORE window_end.
        None when the window is not fully covered — see rule 2."""

    def has_score(self, symbol: str, as_of: dt.date) -> bool: ...

    def symbols(self) -> Iterable[str]: ...


@dataclass(frozen=True)
class UniverseSnapshot:
    as_of: dt.date
    members: tuple[str, ...]
    excluded: dict[str, str]          # symbol -> reason, kept for audit
    param_version: int
    param_source: str

    def stamp(self) -> dict:
        """Goes into the backtest/NAV row. A result that cannot say which
        universe rule produced it is a result you cannot reproduce."""
        return {"universe_ns": NS_INVESTABLE,
                "universe_param_version": self.param_version,
                "universe_param_source": self.param_source,
                "universe_n": len(self.members)}

    def __len__(self) -> int:
        return len(self.members)

    def __contains__(self, s: str) -> bool:
        return s in self.members


def investable_universe(as_of: dt.date, provider: PanelProvider,
                        params=None) -> UniverseSnapshot:
    """Who was investable on `as_of` — recomputed, never looked up.

    Deterministic in (as_of, provider-data-before-as_of, params). Nothing dated
    on or after `as_of` may influence the result; that is asserted by test, not
    by inspection."""
    if params is None:
        from src.data.signals.strategy_params import load
        params = load(NS_INVESTABLE, FALLBACK_PARAMS, fallback_version=0)
    p = params.values

    min_adv = float(p["min_adv_usd"])
    win = int(p["adv_window_days"])
    min_hist = int(p["min_history_days"])
    require_score = bool(p.get("require_score", True))
    max_members = p.get("max_members")

    members: list[tuple[str, float]] = []
    excluded: dict[str, str] = {}

    for sym in provider.symbols():
        rng = provider.listed_range(sym)
        if rng is None:
            excluded[sym] = "no listing record"      # rule 2: silence is not a yes
            continue
        first_seen, delisted = rng
        if first_seen is None or first_seen > as_of:
            excluded[sym] = f"not listed on {as_of}"
            continue
        # Delisted assets ARE members for dates before their exit. This is the
        # whole point: a universe that only knows today's survivors cannot
        # produce an honest 2022.
        if delisted is not None and delisted <= as_of:
            excluded[sym] = f"delisted {delisted}"
            continue
        if (as_of - first_seen).days < min_hist:
            excluded[sym] = (f"seasoning: {(as_of - first_seen).days}d listed "
                             f"< {min_hist}d")
            continue

        adv = provider.adv_usd(sym, as_of, win)
        if adv is None:
            excluded[sym] = f"no volume for the {win}d window before {as_of}"
            continue
        if adv < min_adv:
            excluded[sym] = f"ADV ${adv/1e6:.1f}M < ${min_adv/1e6:.1f}M"
            continue

        if require_score and not provider.has_score(sym, as_of):
            excluded[sym] = "no score as of this date"
            continue

        members.append((sym, adv))

    # Deterministic order. When capped, keep the most liquid — the cap exists to
    # bound operational load, so it must not be the thing that selects for
    # performance.
    members.sort(key=lambda x: (-x[1], x[0]))
    if max_members:
        for sym, _ in members[int(max_members):]:
            excluded[sym] = f"below the top {max_members} by ADV"
        members = members[:int(max_members)]

    return UniverseSnapshot(
        as_of=as_of,
        members=tuple(s for s, _ in members),
        excluded=excluded,
        param_version=getattr(params, "version", 0),
        param_source=getattr(params, "source", "code_fallback"),
    )
