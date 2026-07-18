"""
Smoke tests for phase_weighted_combined.py — verifies the honest OOS A/B + phase
distribution over a real factory panel. Network-dependent (loads Binance panel + FNG
history) but uses the existing factory loaders, so the assertions are structural.

Run from repo root:
    python3 -m pytest src/research/factory/tests/test_phase_weighted_combined.py -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.research.factory.phase_weighted_combined import run, run_in_sample_diagnostic


def test_oos_ab_has_required_keys():
    """The honest test must return all three: base, scaled, delta — the OOS A/B is the headline."""
    r = run()
    for k in ("base_oos_sharpe", "scaled_oos_sharpe", "delta_scaled_vs_base",
              "oos_days", "phase_dist", "avg_gross_scale"):
        assert k in r, f"missing key {k}"
    assert isinstance(r["base_oos_sharpe"], (int, float))
    assert isinstance(r["scaled_oos_sharpe"], (int, float))


def test_oos_days_sane():
    """19mo panel, 50% train + 5 embargoed folds ⇒ ≥200 OOS days."""
    r = run()
    assert r["oos_days"] >= 200, f"OOS days too few: {r['oos_days']}"


def test_phase_dist_covers_at_least_three_phases():
    """On a 19mo panel covering the BTC range from 40k to 120k, we MUST see at least 3 of the
    5 phases. If we see only accumulation, the date alignment broke (see R30 lessons)."""
    r = run()
    n_phases = sum(1 for ph, frac in r["phase_dist"].items() if frac > 0.02)
    assert n_phases >= 3, (
        f"only {n_phases} phases fired (>=2% share): {r['phase_dist']} — "
        f"phase reconstruction likely broken (epoch-day vs date-string mismatch)")


def test_avg_gross_below_one():
    """The phase policy is structurally defensive (R24). Avg gross over the window must be <1.0
    if the phase gate is actually applying different scales (not just uniform 1.0)."""
    r = run()
    assert r["avg_gross_scale"] < 1.0, (
        f"avg gross {r['avg_gross_scale']} — phase gate is uniform, not exercising the policy")


def test_in_sample_diagnostic_has_nucleus_and_all_phases():
    d = run_in_sample_diagnostic()
    assert len(d["nucleus"]) >= 2, f"nucleus too small: {d['nucleus']}"
    for ph in ("capitulation", "accumulation", "markup", "euphoria", "distribution"):
        assert ph in d["phase_breakdown"], f"phase {ph} missing from in-sample breakdown"


if __name__ == "__main__":
    test_oos_ab_has_required_keys()
    test_oos_days_sane()
    test_phase_dist_covers_at_least_three_phases()
    test_avg_gross_below_one()
    test_in_sample_diagnostic_has_nucleus_and_all_phases()
    print("ALL OK")
