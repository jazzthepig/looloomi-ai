"""
Smoke tests — graveyard → canonical migration + library map (build-order #3 completion).
Sandbox-safe. Run: python3 -m src.research.tests.test_embed_graveyard_canonical_smoke
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.data.vector.strategy_embedder import is_disqualified  # noqa: E402
from src.research.embed_graveyard_canonical import LIBRARY, library_map, _rec  # noqa: E402


def _by_id(rid):
    return next(r for r in LIBRARY if r.id == rid)


def test_library_size():
    assert len(LIBRARY) == 8


def test_only_cost_infeasible_is_disqualified():
    """vol_carry (cost_feasible=False) disqualifies; nothing else does."""
    dq = [r.id for r in LIBRARY if is_disqualified(r)[0]]
    assert dq == ["vol_carry_btc"], f"only cost-infeasible sleeve disqualified, got {dq}"


def test_unverified_pit_not_disqualified():
    """swing_overlay_v9 has leakage_clean=None (UNVERIFIED) ⇒ pit_clean=True + tag, NOT disqualified."""
    v9 = _by_id("swing_overlay_v9")
    assert v9.pit_clean is True, "unverified ≠ proven leaky"
    assert "pit_unverified" in v9.tags
    assert is_disqualified(v9)[0] is False, "must not falsely disqualify an untested sleeve"


def test_field_mapping():
    """Seth kwargs → canonical fields: turnover/4, time_in_market×100, alpha_t→residual_alpha."""
    r = _rec("t", factors={"alpha_t": 2.0, "beta_market": 0.5},
             mechanics={"turnover_yr": 80, "time_in_market": 0.9})
    assert r.factor_exposure["residual_alpha"] == 2.0 and r.factor_exposure["beta_market"] == 0.5
    assert r.mechanics["turnover_per_q"] == 20.0        # 80/4
    assert r.mechanics["time_in_market"] == 90.0        # 0.9×100 (canonical expects 0-100)


def test_coverage_map_shows_volatility_gaps():
    """THE strategic output: calm-vol and storm-vol are n=0 (uncovered) — everything we own is directional."""
    m = library_map()
    gaps = {g["regime"]: g for g in m["coverage_gaps"]}
    assert gaps["regime_calm_vol"]["n_measured"] == 0 and not gaps["regime_calm_vol"]["covered"]
    assert gaps["regime_storm_vol"]["n_measured"] == 0 and not gaps["regime_storm_vol"]["covered"]
    # directional regimes ARE covered
    assert gaps["regime_trend"]["covered"] and gaps["regime_risk_on"]["covered"]
    assert m["n_live"] == 7 and m["disqualified"][0][0] == "vol_carry_btc"


def test_redundancy_finds_fake_breadth():
    m = library_map()
    pairs = {frozenset((d["a"], d["b"])) for d in m["redundancy"]}
    assert frozenset(("cis_quality_ls_5d", "risk_direction_score")) in pairs, "near-dupe pair expected"
    assert len(m["redundancy"]) >= 1


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} canonical-graveyard smoke tests passed")
