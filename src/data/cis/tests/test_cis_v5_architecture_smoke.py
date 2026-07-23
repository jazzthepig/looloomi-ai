"""
Smoke tests — CIS v5 reference architecture (two-score decomposition). Sandbox-safe, pure.
Run: python3 -m src.data.cis.tests.test_cis_v5_architecture_smoke

The load-bearing test is test_rank_unchanged_size_collapses_at_high_S: it demonstrates the entire
reason v5 exists — high sentiment must NOT change the return rank (R63: mean-flat) but MUST collapse
the size (R63: vol +8%, tail −32%). v4's single weighted sum does the opposite (S is a positive-weight
pillar, so hot sentiment RAISES the composite — ranking a riskier asset as better).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.data.cis.cis_v5_architecture import (  # noqa: E402
    return_score, risk_score, cis_v5,
)


def _isnan(x): return isinstance(x, float) and x != x


BASE = {"F": 80, "M": 70, "O": 60, "S": 40, "A": 75}


def test_return_score_excludes_S_and_O():
    """S and O must NOT enter the return score (they are risk, not return — R63/S-76)."""
    a = return_score(BASE)["return_score"]
    b = return_score({**BASE, "S": 95, "O": 10})["return_score"]   # wildly different S/O
    assert a == b, f"return_score must ignore S/O; {a} != {b}"


def test_a_change_component_pit_honest():
    """A_change present only with a prior (coverage 4 vs 3, NaN-honest); rising A scores > falling A."""
    with_prior = return_score(BASE, prior_pillars={"A": 65})   # ΔA +10
    no_prior = return_score(BASE)
    assert with_prior["coverage"] == 4 and "A_change" in with_prior["components"]
    assert no_prior["coverage"] == 3 and "A_change" not in no_prior["components"]
    rising = return_score(BASE, prior_pillars={"A": 65})["return_score"]   # ΔA +10
    falling = return_score(BASE, prior_pillars={"A": 85})["return_score"]  # ΔA −10
    assert rising > falling, "the change term makes a rising-A asset outrank an identical falling-A one"


def test_return_nan_honest_renormalizes():
    """Missing F is DROPPED + weights renormalized (I1), not imputed 0 (which would drag the score)."""
    r = return_score({"M": 70, "A": 75})   # no F, no O/S needed
    assert r["coverage"] == 2 and not _isnan(r["return_score"])
    # renormalized over {M, A_level}: ~72, NOT dragged toward 0 by a phantom-0 F
    assert r["return_score"] > 60, f"phantom-0 F would crush this; got {r['return_score']}"


def test_risk_rises_with_O():
    """S-77: O is the dispersion pillar (corr(O,edge²)=+0.145, 2× any other) ⇒ risk is O-led."""
    lo = risk_score({"O": 30})
    hi = risk_score({"O": 90})
    assert hi["risk_score"] > lo["risk_score"], "risk rises with O level"
    assert hi["o_risk"] > 0.8 and lo["o_risk"] < 0.4
    # S is NOT a risk-level driver anymore (weak on both axes) — changing S alone barely moves risk
    assert abs((risk_score({"O": 60, "S": 10})["risk_score"] or 0)
               - (risk_score({"O": 60, "S": 95})["risk_score"] or 0)) < 1e-9


def test_confidence_from_stability_not_faked():
    """Unstable S/O ⇒ low confidence; ABSENT stability ⇒ neutral 0.5 fallback, never a false 1.0 (I1)."""
    stable = risk_score({"O": 50}, so_stability={"S": 2, "O": 2})
    churny = risk_score({"O": 50}, so_stability={"S": 22, "O": 20})
    assert stable["confidence"] > churny["confidence"], "stable ⇒ more confident"
    none_stab = risk_score({"O": 50}, so_stability=None)
    assert none_stab["confidence"] == 0.5, "no stability ⇒ flagged-neutral 0.5, not fake 1.0"


def test_rank_unchanged_size_collapses_at_high_O():
    """THE v5 thesis (S-77 refined to O, the dispersion pillar). Two assets identical except O:
    same return_score (O not in return ⇒ rank unchanged) but far lower size at high O."""
    lo = cis_v5({**BASE, "O": 30}, prior_pillars={"A": 70}, so_stability={"S": 4, "O": 4})
    hi = cis_v5({**BASE, "O": 95}, prior_pillars={"A": 70}, so_stability={"S": 4, "O": 4})
    assert lo["return_score"] == hi["return_score"], "O must not move the return rank"
    assert hi["size_mult"] < lo["size_mult"] * 0.5, "high-O (dispersion) collapses size, not rank"
    # v4 contrast (single weighted sum, O weight 0.20): high O RAISES the composite — v4 ranks the
    # higher-dispersion asset BETTER, the exact conflation v5 removes.
    v4_lo = 0.25 * 80 + 0.25 * 70 + 0.20 * 30 + 0.15 * BASE["S"] + 0.15 * 75
    v4_hi = 0.25 * 80 + 0.25 * 70 + 0.20 * 95 + 0.15 * BASE["S"] + 0.15 * 75
    assert v4_hi > v4_lo, "v4 ranks the riskier (high-O) asset BETTER — the conflation v5 removes"


def test_blended_is_display_only():
    o = cis_v5(BASE, prior_pillars={"A": 70}, so_stability={"S": 5, "O": 5})
    assert abs(o["blended_for_display"] - round(o["return_score"] * o["size_mult"], 2)) < 0.01


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} CIS v5 architecture smoke tests passed")
