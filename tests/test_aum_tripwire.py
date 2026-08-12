"""
Guard: the capacity ceiling fires on SIZE, before it shows up in P&L (S-154).

THE SITUATION IT ENCODES, 2026-08-12. R66-C's edge sits in names too small to
hold at institutional size — sub-$20M ADV produced +186.5% of a +154.6% total,
and the ten names clearing a $5M ADV floor summed to −21.3%. At $500M that
disqualifies the sleeve. At the $10k Jazz starts with next week it is irrelevant:
$10k against $1.4M ADV is 0.7% participation.

Both are true, and they expire at different times. **A constraint that does not
bind today will bind later, silently, on a day nobody is thinking about it.**
The sleeve will not announce that it has outgrown its universe — the fills just
get worse, and worse fills look exactly like a decaying edge. By the time the
P&L shows it, the diagnosis is already ambiguous. So the alarm is on SIZE.

WHY THE CEILING IS RECOMPUTED, NEVER STORED. COMP measured $1.4M ADV on a
180-day median and $0.3M on a 30-day one, in the same hour. A capacity number
frozen into a strategy record on ship day describes a market that no longer
exists. Same discipline as `investable_universe(as_of)`: recompute, do not look
up. This suite therefore asserts the ceiling MOVES with ADV — a test that only
pinned one number would be re-creating the defect it is guarding.

Run: python3 -m tests.test_aum_tripwire
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


def _p(**over):
    from src.data.signals.strategy_params import ParamSet
    from src.data.universe.aum_tripwire import FALLBACK_PARAMS, NS_TRIPWIRE
    return ParamSet(NS_TRIPWIRE, {**FALLBACK_PARAMS, **over}, -1, "code_fallback")


# A two-name book, one liquid and one thin — R66-C's actual shape in RISK_OFF,
# where K=1 means the whole book is one long and one short.
W = {"BTC": 0.5, "RUNE": 0.5}
ADV = {"BTC": 1_300_000_000.0, "RUNE": 1_200_000.0}


def test_ten_thousand_dollars_does_not_bind() -> None:
    """The point of the whole module: say clearly when the constraint is OFF.
    A risk system that cannot say 'this does not apply to you today' gets muted,
    and a muted alarm is worse than none."""
    from src.data.universe.aum_tripwire import headroom, OK
    h = headroom(10_000, W, ADV, _p())
    check("$10k is OK", h.status == OK, f"{h.status}: {h.note}")
    check("utilisation is reported, not just a verdict",
          h.utilisation is not None and h.utilisation < 0.1, str(h.utilisation))
    check("the note says capacity bounds IMPACT only",
          "spread" in h.note.lower(),
          "a small account is free of impact and NOT free of spread — if the note "
          "omits that, the reader will hear 'no cost problem'")


def test_it_warns_before_the_ceiling_not_at_it() -> None:
    from src.data.universe.aum_tripwire import headroom, APPROACHING, BREACH
    ceiling = headroom(1, W, ADV, _p()).ceiling_usd
    check("a ceiling exists", ceiling and ceiling > 0, str(ceiling))
    warn = headroom(ceiling * 0.6, W, ADV, _p())
    brea = headroom(ceiling * 1.2, W, ADV, _p())
    check("60% of the ceiling warns", warn.status == APPROACHING, warn.status)
    check("120% breaches", brea.status == BREACH, brea.status)
    check("the warning names what binds", "RUNE" in warn.binding, str(warn.binding))
    check("the warning says what to decide",
          "cap the sleeve" in warn.note or "widen the universe" in warn.note,
          warn.note[:120])


def test_the_ceiling_moves_when_liquidity_moves() -> None:
    """COMP: $1.4M on a 180d median, $0.3M on a 30d one, same hour. A stored
    number would have been wrong by 4.7x within a single session."""
    from src.data.universe.aum_tripwire import headroom
    dry = headroom(1, W, {**ADV, "RUNE": 300_000.0}, _p()).ceiling_usd
    wet = headroom(1, W, {**ADV, "RUNE": 12_000_000.0}, _p()).ceiling_usd
    check("thinner ADV lowers the ceiling", dry < wet, f"{dry} vs {wet}")
    check("and it scales with ADV", abs(wet / dry - 40.0) < 1e-6, f"{wet/dry}")


def test_the_thin_name_sets_the_ceiling_not_the_average() -> None:
    """A book is as tradeable as its worst leg. Averaging BTC's $1.3bn against
    RUNE's $1.2M would report a capacity nobody can fill."""
    from src.data.universe.aum_tripwire import headroom
    h = headroom(1, W, ADV, _p())
    expected = 0.05 * 1_200_000.0 * 3 / 0.5
    check("ceiling comes from the thin leg", abs(h.ceiling_usd - expected) < 1,
          f"{h.ceiling_usd} vs {expected}")
    check("binding names are reported", h.binding == ("RUNE",), str(h.binding))


def test_partial_adv_coverage_refuses_to_produce_a_ceiling() -> None:
    """A minimum over the names we happen to have volume for is an UPPER BOUND
    on capacity, not capacity — and it is biased the dangerous way, because the
    name we are missing volume for is usually the thin one."""
    from src.data.universe.aum_tripwire import headroom, UNKNOWN
    h = headroom(10_000, W, {"BTC": 1.3e9}, _p())
    check("missing ADV -> UNKNOWN, not a number", h.status == UNKNOWN, h.status)
    check("no ceiling is invented", h.ceiling_usd is None, str(h.ceiling_usd))
    check("the unpriced name is named", "RUNE" in h.unpriced, str(h.unpriced))
    check("the note explains the bound",
          "upper bound" in h.note, h.note[:120])


def test_spread_is_reported_separately_from_capacity() -> None:
    """The two costs behave oppositely in size. Impact vanishes at $10k; spread
    is crossed at any size and is WIDER on the thin names carrying the edge.
    Reporting them as one number is how '150bps break-even' reads as safety."""
    from src.data.universe.aum_tripwire import spread_drag_pct_yr
    at10 = spread_drag_pct_yr(10, 28)
    at50 = spread_drag_pct_yr(50, 28)
    check("10bps x 28 rebalances ~ 11%/yr", abs(at10 - 11.2) < 0.1, str(at10))
    check("50bps x 28 rebalances ~ 56%/yr", abs(at50 - 56.0) < 0.1, str(at50))
    check("spread drag is independent of AUM",
          spread_drag_pct_yr(50, 28) == at50, "")


def test_a_useless_alarm_configuration_cannot_load() -> None:
    from src.data.universe.aum_tripwire import validate_tripwire
    check("sane config validates",
          not validate_tripwire({"participation": 0.05, "rebal_trade_days": 3,
                                 "warn_fraction": 0.5, "breach_fraction": 1.0}), "")
    same = validate_tripwire({"participation": 0.05, "rebal_trade_days": 3,
                              "warn_fraction": 1.0, "breach_fraction": 1.0})
    check("warn == breach is rejected",
          any("not a warning" in p for p in same), str(same))
    big = validate_tripwire({"participation": 0.90, "rebal_trade_days": 3,
                             "warn_fraction": 0.5, "breach_fraction": 1.0})
    check("90% participation is rejected",
          any("you are the market" in p for p in big), str(big))


def test_the_rule_is_registered_so_a_bad_row_cannot_ship() -> None:
    import src.data.signals.strategy_params as sp
    from src.data.universe.aum_tripwire import NS_TRIPWIRE
    check("tripwire namespace has a validator", NS_TRIPWIRE in sp._VALIDATORS,
          "an unregistered namespace loads unvalidated")


if __name__ == "__main__":
    print("── the capacity ceiling fires on size, not on P&L (S-154) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ the constraint that does not bind today will announce itself before it does")
