"""
Smoke tests — canonical strategy embedder after the build-order #3 convergence (2026-07-22).
Verifies the four capabilities ported from src/research/strategy_vector.py into the keeper stack:
NaN-honesty (I1), the binary validity floor (I4), coverage_gaps(), redundancy(). Sandbox-safe.
Run: python3 -m src.data.vector.tests.test_strategy_embedder_honest_smoke
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.data.vector.strategy_schema import StrategyRecord, Verdict  # noqa: E402
from src.data.vector import strategy_embedder as SE  # noqa: E402
from src.data.vector import strategy_store as SS  # noqa: E402


def _isnan(x): return isinstance(x, float) and x != x


def _rec(rid, **kw):
    base = dict(id=rid, title=rid, doc_source="test", pit_clean=True, cost_feasible_at_5bps=True)
    base.update(kw)
    return StrategyRecord(**base)


def test_nan_honesty_unmeasured_is_nan():
    """I1: a record with only regime_domain measured ⇒ regime dims finite, EVERY other dim NaN (not 0)."""
    r = _rec("regime_only", regime_domain={"regime_calm_vol": 1.0, "regime_risk_on": 0.8})
    v = SE.generate_embedding(r)
    assert len(v) == SE.VECTOR_DIMS == 30
    assert not _isnan(v[0]) and not _isnan(v[2]), "measured regime dims are finite"
    # factor/mechanics/capacity/lifecycle/cost/outcome all unmeasured ⇒ NaN
    assert all(_isnan(x) for x in v[6:]), "unmeasured dims are NaN, never 0"


def test_measured_zero_is_kept():
    """A MEASURED neutral (directionality 0) stays 0 — only ABSENT fields are NaN."""
    r = _rec("neutral", mechanics={"directionality": 0.0})
    v = SE.generate_embedding(r)
    assert v[14] == 0.0 and not _isnan(v[14]), "measured 0 kept as 0 (dim 14 = directionality)"


def test_binary_validity_floor():
    """I4: ONLY leakage + cost-infeasibility disqualify. forward_committed is NOT a disqualifier."""
    assert SE.is_disqualified(_rec("ok"))[0] is False
    assert SE.is_disqualified(_rec("leak", pit_clean=False))[0] is True
    assert SE.is_disqualified(_rec("costly", cost_feasible_at_5bps=False))[0] is True
    assert SE.is_disqualified(_rec("uncommitted", forward_committed=False))[0] is False, \
        "forward_committed is a lifecycle state, not a validity floor"


def test_coverage_gaps_excludes_disqualified():
    """coverage_gaps reports uncovered regimes and EXCLUDES disqualified sleeves (can't cover what it can't trade)."""
    good = _rec("good", regime_domain={"regime_calm_vol": 1.5})
    dq = _rec("leaky", pit_clean=False, regime_domain={"regime_storm_vol": 2.0})
    gaps = {g["regime"]: g for g in SE.coverage_gaps([good, dq])}
    assert gaps["regime_calm_vol"]["covered"] is True, "good sleeve covers calm"
    assert gaps["regime_storm_vol"]["n_measured"] == 0, "disqualified sleeve's storm coverage excluded"
    assert gaps["regime_storm_vol"]["covered"] is False


def test_redundancy_finds_dupes_excludes_dq():
    """Near-identical live sleeves flagged; disqualified excluded. Needs ≥4 shared measured dims."""
    rd = {"regime_calm_vol": 1.0, "regime_storm_vol": 0.5, "regime_risk_on": 0.8,
          "regime_risk_off": -0.3, "regime_trend": 1.2}
    a = _rec("a", regime_domain=rd)
    b = _rec("b", regime_domain=dict(rd))       # identical ⇒ sim 1.0
    c = _rec("c", pit_clean=False, regime_domain=dict(rd))  # disqualified, must not appear
    dupes = SE.redundancy([a, b, c])
    ids = {frozenset((d["a"], d["b"])) for d in dupes}
    assert frozenset(("a", "b")) in ids, "a≈b flagged"
    assert not any("c" in (d["a"], d["b"]) for d in dupes), "disqualified c excluded"


def test_cosine_nan_aware():
    a = SE.generate_embedding(_rec("a", regime_domain={"regime_calm_vol": 1.0, "regime_storm_vol": 0.5,
                                                       "regime_risk_on": 0.8, "regime_risk_off": 0.2}))
    assert abs(SE.cosine_similarity(a, a) - 1.0) < 1e-6, "self-sim 1"
    assert SE.cosine_similarity([float("nan")] * 30, a) == 0.0, "all-NaN ⇒ refuse"
    assert SE.cosine_similarity([1.0, 2.0], a) == 0.0, "<4 shared measured ⇒ refuse"


def test_coverage_summary_counts_measured():
    r = _rec("partial", regime_domain={"regime_calm_vol": 1.0}, mechanics={"directionality": 0.0})
    cov = SE.coverage_summary(r)
    assert cov["dims_measured"] == 2, "1 regime + 1 measured-0 directionality = 2 measured"
    assert cov["dims_nonzero"] == cov["dims_measured"], "back-compat alias tracks measured"


def test_store_nan_null_roundtrip():
    import json
    v = SE.generate_embedding(_rec("x", regime_domain={"regime_calm_vol": 1.0}))
    js = json.dumps({"x": SS._nan_to_null(v)}, allow_nan=False)   # must NOT raise on NaN
    assert "NaN" not in js and "null" in js
    back = SS._null_to_nan(json.loads(js)["x"])
    assert not _isnan(back[0]) and _isnan(back[6]), "measured kept, unmeasured restored to NaN"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} canonical strategy-embedder honesty tests passed")
