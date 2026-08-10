"""
Strategy-intake guard — why nobody gets the database key.

THE ASK (2026-08-08). Minimax-A could not write beta-strategy records to Supabase
and asked for `service_role`. Declined. The endpoint that replaces it is not a
compromise; it is better on two counts:

  1. BLAST RADIUS. `service_role` bypasses RLS on every table — read, write, drop.
     A scoped token can only append strategy records and rotates without touching
     the database. Lesson #72 (a forged JWT that passed every local check) is the
     standing reminder that a credential in more places is a credential in more
     incidents.

  2. THE GATE BECOMES UNBYPASSABLE, which is the stronger reason. With a raw DB
     key, a SHIP record that fails the discipline floor can be written anyway —
     the floor lives in CI, and CI is not in the write path. Here validate() runs
     BEFORE the insert. **A gate the writer can route around is a suggestion.**

These tests pin the properties that make that true, because an intake endpoint
that accepts everything is just the DB key with extra steps.

Run: python3 -m tests.test_strategy_intake
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.api.routers import strategy_intake as si  # noqa: E402
from src.data.vector.strategy_schema import StrategyRecord, Verdict  # noqa: E402

_SHIP_OK = dict(
    id="ok", title="ok", doc_source="minimax", verdict="ship",
    pit_clean=True, cost_feasible_at_5bps=True, forward_committed=True,
    base_rate="cause", oos_survival=True, paper_trade_days=90, regime_reported=True,
    max_dd_stop=-0.15, capital_action_on_breach="zero_and_freeze",
    backtest_included_stop=True, deflated_sharpe=0.97, n_trials=40, pbo=0.2,
    median_holding_days=30.0, turnover_cost_pct_yr=1.0, net_effect_pct_yr=2.5,
    trigger_name="funding_z", trigger_median_run_days=35.0,
    # S-132: a SHIP record is no longer complete in percent alone. Berk & van
    # Binsbergen — percentage alpha does not persist, dollars extracted do — so
    # the intake floor now requires the capacity the percentage was earned on.
    deployable_notional_usd=48_000_000.0, value_added_usd_yr=1_200_000.0,
    notional_basis="min over 12 legs of 5% ADV × 3d / |w|",
)


def test_a_ship_record_missing_the_floor_is_rejected_with_its_reasons():
    """The whole argument for the endpoint. A rejection saying 'invalid' teaches
    nothing; one quoting validate()'s own strings is a fix the sender can apply
    without asking anyone."""
    bad = {**_SHIP_OK}
    del bad["deflated_sharpe"]
    rec, notes = si._coerce(bad)
    assert rec is not None, "the record must construct — it is the GATE that rejects"
    problems = rec.validate()
    assert problems, "a SHIP record without a deflated Sharpe must not pass"
    assert any("deflated_sharpe" in p for p in problems), \
        "the rejection must name the missing field, not just say invalid"


def test_a_fully_evidenced_ship_record_passes():
    """The converse. A gate that rejects everything is as useless as one that
    accepts everything — it just fails in the direction that looks responsible."""
    rec, notes = si._coerce(dict(_SHIP_OK))
    assert rec is not None and not notes
    assert not rec.validate(), f"fully-evidenced record rejected: {rec.validate()}"


def test_refute_records_are_accepted_without_the_ship_floor():
    """CLAUDE.md calls the graveyard the asset. If filing a failure were harder
    than filing a success, the ledger would silently bias toward wins — which is
    the one bias a refutation ledger exists to prevent."""
    rec, _ = si._coerce({"id": "dead", "title": "dead idea", "doc_source": "minimax",
                         "verdict": "refute", "notes": "no cause found"})
    assert rec is not None and rec.verdict == Verdict.REFUTE
    # the endpoint only runs validate() for SHIP; assert that policy explicitly
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/api/routers/strategy_intake.py"), encoding="utf-8").read()
    assert "if rec.verdict == Verdict.SHIP else []" in src, \
        "the floor must apply to SHIP only"


def test_unknown_fields_are_reported_not_swallowed():
    """An unknown field usually means the sender's schema drifted. Swallowing it is
    how two lanes both believe they are compliant while disagreeing — the same
    silent-drop class as the CIS payload warnings."""
    rec, notes = si._coerce({**_SHIP_OK, "sharpe_ratio_2": 1.4, "made_up": "x"})
    assert rec is not None
    assert notes and "made_up" in notes[0] and "sharpe_ratio_2" in notes[0]


def test_a_bad_verdict_string_is_refused_with_the_valid_set():
    """Coercion errors must name the allowed values. A sender that has to guess
    will eventually guess 'SHIPPED' and file it as something else."""
    rec, notes = si._coerce({**_SHIP_OK, "verdict": "SHIPPED"})
    assert rec is None
    assert any("ship" in n and "refute" in n for n in notes), \
        "must enumerate the valid verdicts in the error"


def test_auth_fails_closed_when_the_env_var_is_missing():
    """A missing INTERNAL_TOKEN must reject everything, never accept everything.
    The `not _INTERNAL_TOKEN or ...` ordering is the whole of that guarantee."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/api/routers/strategy_intake.py"), encoding="utf-8").read()
    assert "if not _INTERNAL_TOKEN or not x_internal_token" in src, \
        "auth must fail closed on a missing env var"
    assert "service_role is NOT required and NOT shared" in src, \
        "the schema echo must state that the DB key stays here"


def test_validated_but_unpersisted_is_never_reported_as_accepted():
    """S-105: the strategy library spent 12 days believing it had persisted records
    it had not, because the write failure only logged. A 200 that means 'validated'
    rather than 'stored' would rebuild exactly that trap."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "src/api/routers/strategy_intake.py"), encoding="utf-8").read()
    assert '"persisted": written' in src, "the response must report what was STORED"
    assert "status_code=503" in src, "a persist failure must not return success"
    assert "validated %d, persisted %d" in src, "a partial write must be logged loudly"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} strategy-intake checks passed")
    sys.exit(1 if f else 0)
