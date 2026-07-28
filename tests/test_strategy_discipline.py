"""
Strategy discipline — the PHILOSOPHY compiled into CI (Seth, 2026-07-27, per Minimax feedback P2).
==================================================================================================

CLAUDE.md / TRADER_TOM_DOCTRINE / ARCHITECTURE.md are prose; prose gets bypassed under deadline
pressure. This test compiles the non-negotiables into red/green:

  · every sleeve traces to a CAUSE with a base rate            (§TRADER_TOM: no cause, no sleeve)
  · guilty until proven with OOS outcomes                      (oos_survival must be True to SHIP)
  · ≥60 days forward paper trade before production             (Minimax-C's hard gate)
  · regime-conditional reporting mandatory                     (aggregate metrics hide regime failure)
  · binary validity floor (PIT + cost) intact                  (I4 — the only two hard kills)

Legacy debt is EXPLICIT, not silent: pre-convention live sleeves sit in LEGACY_ALLOWLIST with the
reason + what they owe. Adding a NEW ship-verdict record without the evidence floor turns CI red.
Run: python3 -m tests.test_strategy_discipline   (also wired into scripts/preflight.sh stage 3)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.vector.strategy_schema import StrategyRecord, Verdict  # noqa: E402
from src.research.embed_graveyard_canonical import LIBRARY  # noqa: E402

# Pre-convention live sleeves — visible debt, each with the reason it is tolerated and what it owes.
# Removing an entry here without fixing its evidence fields turns CI red. Do NOT add new entries
# for new sleeves — new production records must carry the full evidence floor from day one.
LEGACY_ALLOWLIST: dict[str, str] = {
    "trend_v5c_long_only": "pre-convention live sleeve; deployed §5b overlay-only behind the core-health "
                           "gate (holds ZERO while core dead). OWES: base_rate, oos_survival, "
                           "paper_trade_days, regime_reported backfill.",
}


def test_every_sleeve_has_a_cause_or_notes():
    """§TRADER_TOM: a sleeve without an articulated cause is not a strategy, it's a curve."""
    for r in LIBRARY:
        assert (r.base_rate or r.notes), f"{r.id}: no cause documented (base_rate empty AND notes empty)"


def test_ship_records_carry_the_evidence_floor():
    """SHIP ⇒ full evidence floor (validate() emits zero problems), unless explicitly legacy-allowlisted."""
    for r in LIBRARY:
        if r.verdict != Verdict.SHIP:
            continue
        problems = r.validate()
        if r.id in LEGACY_ALLOWLIST:
            continue  # visible debt — tracked in the allowlist, not silently green
        assert not problems, f"{r.id} ships without the evidence floor: {problems}"


def test_allowlist_entries_are_still_needed():
    """Stale allowlist entries must be removed — if a legacy sleeve now passes, delete its entry."""
    lib_ids = {r.id for r in LIBRARY}
    for lid in LEGACY_ALLOWLIST:
        assert lid in lib_ids, f"allowlist entry '{lid}' no longer in the library — remove it"
        rec = next(r for r in LIBRARY if r.id == lid)
        assert rec.validate(), f"'{lid}' now passes validate() — remove it from LEGACY_ALLOWLIST"


def test_refuted_records_stay_honest():
    """A REFUTE verdict with every validity flag True is a contradiction (validate catches it)."""
    for r in LIBRARY:
        if r.verdict == Verdict.REFUTE:
            assert not (r.pit_clean and r.cost_feasible_at_5bps and r.forward_committed), \
                f"{r.id}: refuted but all validity flags true — which is it?"


def test_new_ship_record_without_evidence_is_rejected():
    """The gate itself: a fresh SHIP record missing the evidence floor must fail validation."""
    bad = StrategyRecord(id="new_hero", title="new hero", doc_source="test",
                         verdict=Verdict.SHIP, pit_clean=True, cost_feasible_at_5bps=True,
                         forward_committed=True)
    problems = bad.validate()
    assert any("base_rate" in p for p in problems), "missing cause must be flagged"
    assert any("oos_survival" in p for p in problems), "unproven OOS must be flagged"
    assert any("paper_trade_days" in p for p in problems), "missing 60d paper gate must be flagged"
    assert any("regime_reported" in p for p in problems), "aggregate-only reporting must be flagged"
    assert any("max_dd_stop" in p for p in problems), "no stop rule ⇒ no production (Millennium)"
    # and a fully-evidenced record passes:
    good = StrategyRecord(id="proven", title="proven", doc_source="test",
                          verdict=Verdict.SHIP, pit_clean=True, cost_feasible_at_5bps=True,
                          forward_committed=True, base_rate="funding crowding reverts (behavioral)",
                          oos_survival=True, paper_trade_days=75, regime_reported=True,
                          oos_window="2026-02-01→2026-05-03", max_dd_stop=-0.15,
                          capital_action_on_breach="zero_and_freeze", backtest_included_stop=True)
    assert not good.validate(), "fully-evidenced ship record must pass"


def test_stop_added_after_the_fact_is_rejected():
    """A stop bolted on AFTER the backtest curve is self-deception — it changes the curve's shape."""
    r = StrategyRecord(id="post_hoc_stop", title="x", doc_source="test", verdict=Verdict.SHIP,
                       pit_clean=True, cost_feasible_at_5bps=True, forward_committed=True,
                       base_rate="cause", oos_survival=True, paper_trade_days=90,
                       regime_reported=True, max_dd_stop=-0.15,
                       capital_action_on_breach="zero_and_freeze", backtest_included_stop=False)
    assert any("backtest_included_stop" in p for p in r.validate())


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} strategy-discipline checks passed (philosophy compiled to CI)")
