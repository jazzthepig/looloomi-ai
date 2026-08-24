"""R70 frozen as an executable decision function (S-207).

R70 is our strongest recorded backtest — held-out OOS 2026-01-08 → 06-07, 151
days, β-adjusted SR 1.58, net 14.5% annualised at 5bps. Source of record:
`Shadow/cometcloud-local/_reports/absorb_input/r70_held_out_oos_2026-07-22_summary.json`.

⚠️ IT HAS NEVER HAD A PAPER BOOK. Jazz flagged "R70 策略到执行端有问题" and the
truth is worse than a problem: no path existed. This module is that path's first
half — the rule, written down as something that can be RUN rather than cited.

⚠️ AND IT DOES NOT CLEAR OUR OWN BAR. S-189: the 1.58 was selected from a
72-configuration sweep, and its Deflated Sharpe is 0.27 against a 0.95 threshold.
Encoding a rule is not endorsing it. What this enables is the question Jazz
actually asked — *would it even have fired* — which is answerable now and does
not depend on the DSR argument at all.

THE PART THAT MATTERS, measured before this file was written. R70 skips
RISK_OFF, STAGFLATION and TIGHTENING. Over the 70 days of stored scores to
2026-08-24, the daily modal regime was TIGHTENING on 59 of them (84.3%) and
NEUTRAL on 5. So R70 stands down on ~93% of the recent record. Its 14.5% was
earned in a regime mix we have not seen since. That is not an execution defect;
it is a strategy that is, by design, absent from the market we are in.

REGIME SPELLING. The recorded skip list contains BOTH `RISK_OFF` and `Risk-Off`.
Two spellings of one state in a config is someone hitting S-209 and routing
around it: `canonical_regime()` is not applied at write time, so `cis_scores`
holds RISK-OFF (4 days) and RISK_OFF (2 days) as if they were different markets.
This module canonicalises on read instead of enumerating variants, because a
skip list that must be extended every time a writer invents a new spelling will
eventually miss one, and missing one means trading a regime you meant to skip.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from src.research.validation.pit_replay import Decision, InputUnavailable

#: Frozen from the R70 summary JSON. Canonical UPPER_SNAKE, one spelling each.
SKIP_REGIMES = frozenset({"RISK_OFF", "STAGFLATION", "TIGHTENING"})

#: Rebalance every N days. R70's reported turnover (69.7%/yr) assumes cadence 3.
CADENCE_DAYS = 3

#: R70 ran "pillar_A" — the Alpha pillar as the cross-sectional sort key.
SORT_PILLAR = "pillar_a"

#: Top-N by the sort pillar. R70's grid used decile-style selection on the panel.
TOP_N = 8

#: Below this many scored names the cross-section is too thin to rank honestly.
MIN_PANEL = 12


def canonical_regime(raw: str | None) -> str | None:
    """`Risk-Off`, `risk off`, `RISK_OFF` → `RISK_OFF`. One state, one name."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s.upper().replace("-", "_").replace(" ", "_")


def _modal_regime(rows: Sequence[Mapping[str, Any]]) -> str | None:
    counts: dict[str, int] = {}
    for r in rows:
        rg = canonical_regime(r.get("macro_regime"))
        if rg:
            counts[rg] = counts.get(rg, 0) + 1
    return max(counts, key=counts.__getitem__) if counts else None


def r70_decide(day: date, rows: Sequence[Mapping[str, Any]]) -> Decision:
    """One day of R70. Raises InputUnavailable when the rule cannot run at all.

    The two are kept apart deliberately: a regime skip is R70 WORKING, and a
    thin panel is our pipeline failing. A replay that reports both as "no
    position" answers Jazz's question with the one word that hides the answer.
    """
    regime = _modal_regime(rows)
    if regime is None:
        raise InputUnavailable("no regime label on any row — cannot evaluate the gate")

    scored = [r for r in rows if isinstance(r.get(SORT_PILLAR), (int, float))]
    if len(scored) < MIN_PANEL:
        raise InputUnavailable(
            f"only {len(scored)} names carry {SORT_PILLAR} (need {MIN_PANEL})")

    # The gate runs AFTER the panel check on purpose. Skipping first would let a
    # day with no usable data be recorded as a clean regime skip, which is the
    # flattering reading and the wrong one.
    if regime in SKIP_REGIMES:
        return Decision({}, f"regime gate: {regime} is in SKIP_REGIMES", regime=regime,
                        detail={"panel": len(scored)})

    # Cadence is measured in calendar days from a fixed epoch so the replay is
    # reproducible from the date alone — no hidden state between days.
    if day.toordinal() % CADENCE_DAYS != 0:
        return Decision({}, f"off-cadence (every {CADENCE_DAYS}d)", regime=regime,
                        detail={"panel": len(scored)})

    ranked = sorted(scored, key=lambda r: float(r[SORT_PILLAR]), reverse=True)[:TOP_N]
    if not ranked:
        raise InputUnavailable("ranking produced nothing from a non-empty panel")

    w = 1.0 / len(ranked)
    return Decision(
        {str(r["symbol"]): w for r in ranked},
        f"top {len(ranked)} by {SORT_PILLAR}",
        regime=regime,
        detail={"panel": len(scored), "regime": regime},
    )
