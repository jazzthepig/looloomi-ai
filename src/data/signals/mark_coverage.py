"""Weighted mark-to-market that cannot report "no data" as "no movement" (S-194).

THE DEFECT, in four books at once. Every paper book computes its daily return as

    pnl = 0.0
    for sym, w in weights.items():
        if sym in prices and sym in mark_prices and mark_prices[sym] > 0:
            pnl += w * (prices[sym] / mark_prices[sym] - 1.0)

and `beta_core` writes the same thing as `sum(... for ... if ...)`. Both are
initialise-to-zero-then-conditionally-accumulate, and both produce **0.0 when
nothing is priceable** — a value indistinguishable in the table from a market
that did not move.

MEASURED 2026-08-23. The equal-weight panel ran +8.84%, +5.23%, +11.03%, −1.43%
over 08-19…08-22. The books recorded:

    beta_core / beta_core_q / causal   0.00% on 3 of 6 marks
    two_layer                          0.00% on 6 of 6
    fusion                             −0.05% every single day (pure fee drag)
    combined / scalable                stopped marking entirely on 08-20

Over 08-18 → 08-23 the panel compounded **+23.99%**; the ① book's NAV sat at
1.0470 when it should have been near 1.16–1.23.

WHY NOTHING CAUGHT IT. `realized_vol_30d` kept rising correctly (0.302 → 0.586)
because nanmean/nanstd skip the unusable rows, so the vol-target scaler did its
job and cut gross 1.30 → 1.00. Every field on the row was individually correct
and the row as a whole described a working book having a quiet couple of days.
**A zero is the most dangerous possible failure value: it is in-range, it is
plausible, and it is what an empty accumulation produces.**

THE RULE. A book that cannot price its holdings must REFUSE TO MARK. Not mark
flat, not mark partial, not log a warning and continue. Same discipline as
S-190 (a partial panel day is not a thin day) and S-185 (a guard whose failure
emits no signal is worse than no guard).

Returns a THREE-VALUED result — priced / refused / empty-book — because the
whole family of bugs this codebase keeps rediscovering comes from collapsing
"could not" into a number that looks like "did not".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

_log = logging.getLogger("mark_coverage")

#: Below this fraction of HELD WEIGHT priceable, refuse to mark.
#: Weight, not name count: dropping one 0.4%-weight name from a 24-name book is
#: noise, dropping the 30% BTC leg is not, and a name-count floor cannot tell
#: those apart.
DEFAULT_MIN_COVERAGE = 0.80


@dataclass
class MarkResult:
    ok: bool
    pnl: float = 0.0
    coverage: float = 0.0
    priced: list[str] = field(default_factory=list)
    unpriced: list[str] = field(default_factory=list)
    reason: str = ""

    def as_skip(self, book: str) -> dict:
        """The dict a caller should return when `ok` is False."""
        return {
            "status": "skipped",
            "book": book,
            "reason": self.reason,
            "coverage": round(self.coverage, 4),
            "priced": len(self.priced),
            "unpriced": len(self.unpriced),
            "unpriced_sample": sorted(self.unpriced)[:10],
        }


def weighted_mark(weights: dict[str, float],
                  prices: dict[str, float],
                  mark_prices: dict[str, float],
                  *,
                  book: str,
                  min_coverage: float = DEFAULT_MIN_COVERAGE) -> MarkResult:
    """Weighted return since the last mark, or a refusal.

    `coverage` is the fraction of |weight| that could be priced, so a book whose
    small names are missing still marks and one whose large names are missing
    does not.
    """
    if not weights:
        return MarkResult(ok=False, reason=f"{book}: no positions held", coverage=0.0)

    total_w = sum(abs(w) for w in weights.values())
    if total_w <= 0:
        return MarkResult(ok=False, reason=f"{book}: total weight is zero")

    pnl = 0.0
    priced_w = 0.0
    priced: list[str] = []
    unpriced: list[str] = []

    for sym, w in weights.items():
        p, m = prices.get(sym), mark_prices.get(sym)
        if p is None or m is None or m <= 0 or p <= 0 or p != p or m != m:
            unpriced.append(sym)
            continue
        pnl += w * (p / m - 1.0)
        priced_w += abs(w)
        priced.append(sym)

    coverage = priced_w / total_w
    if coverage < min_coverage:
        reason = (f"{book}: price coverage {coverage:.1%} below the {min_coverage:.0%} "
                  f"floor — {len(priced)}/{len(weights)} holdings priceable. Marking "
                  f"now would record a flat day indistinguishable from a real one.")
        _log.error("[MARK] REFUSING — %s · unpriced: %s", reason,
                   ",".join(sorted(unpriced)[:10]))
        return MarkResult(ok=False, pnl=0.0, coverage=coverage,
                          priced=priced, unpriced=unpriced, reason=reason)

    if unpriced:
        _log.warning("[MARK] %s marked at %.1f%% coverage; unpriced: %s",
                     book, coverage * 100, ",".join(sorted(unpriced)[:10]))
    return MarkResult(ok=True, pnl=pnl, coverage=coverage,
                      priced=priced, unpriced=unpriced)
