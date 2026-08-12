"""
Smoke tests — asset embedder v2 (pillar deltas + O/S stability). Build-order #2, 2026-07-22.
Sandbox-safe: pure numpy, no network. Run: python3 -m src.data.vector.tests.test_embedder_v2_smoke
Verifies the VECTOR_SCHEMA_SPEC §0 invariants: I1 (NaN not 0), I2 (PIT via caller), I6 (versioned,
v1 dims unchanged, 18/25 interop).
"""
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.data.vector.embedder import (  # noqa: E402
    generate_embedding, pillar_deltas, pillar_stability, edge_risk_moments,
    cosine_similarity, k_means_cluster,
    ASSET_DIMS_V1, ASSET_DIMS_V2, SCHEMA_VERSION, MIN_SHARED_DIMS,
)
from src.data.vector import store  # noqa: E402


def _isnan(x): return isinstance(x, float) and x != x


ASSET_NOW = {
    "symbol": "TEST", "asset_class": "L1", "market_cap": 1e9, "volume_24h": 1e8,
    "change_24h": 2.0, "change_7d": 5.0, "change_30d": 10.0, "las": 70, "confidence": 0.9,
    "pillars": {"F": 60, "M": 55, "O": 70, "S": 40, "A": 65}, "cis_score": 58,
}
PRIOR = {"F": 50, "M": 55, "O": 60, "S": 50, "A": 60}   # ΔF+10 ΔM0 ΔO+10 ΔS-10 ΔA+5


def test_v1_backward_compat():
    """No prior/history ⇒ exactly 18 dims, all finite, v1 unchanged (I6)."""
    v = generate_embedding(ASSET_NOW, macro_regime="Risk-On")
    assert len(v) == ASSET_DIMS_V1 == 18, f"v1 must be 18 dims, got {len(v)}"
    assert all(not _isnan(x) for x in v), "v1 has no NaN dims"
    assert abs(v[0] - 0.60) < 1e-6 and abs(v[3] - 0.40) < 1e-6, "pillar dims F,S unchanged"


def test_v2_shape_and_deltas():
    """prior_pillars ⇒ fixed 27-dim v2 block; deltas correctly signed & normalized (/50);
    risk moments [25..26] NaN when no edge_moments supplied (I1)."""
    v = generate_embedding(ASSET_NOW, macro_regime="Risk-On", prior_pillars=PRIOR)
    assert len(v) == ASSET_DIMS_V2 == 27, f"v2 must be 27 dims, got {len(v)}"
    assert v[:18] == generate_embedding(ASSET_NOW, macro_regime="Risk-On"), "v1 prefix byte-identical (I6)"
    # d_F=+10/50=.2  d_M=0  d_O=.2  d_S=-.2  d_A=+5/50=.1
    for got, exp in zip(v[18:23], [0.2, 0.0, 0.2, -0.2, 0.1]):
        assert abs(got - exp) < 1e-6, f"delta {got} != {exp}"
    assert _isnan(v[25]) and _isnan(v[26]), "risk moments NaN when edge_moments absent"


def test_risk_moments():
    """edge_moments ⇒ [25..26] finite & normalized (vol/25, p10/25); helper computes + NaN-gates."""
    v = generate_embedding(ASSET_NOW, prior_pillars=PRIOR, edge_moments=(16.5, -13.3))
    assert len(v) == 27
    assert abs(v[25] - 16.5 / 25.0) < 1e-6, "edge_vol normalized /25"
    assert abs(v[26] - (-13.3 / 25.0)) < 1e-6, "edge_p10 normalized /25, sign kept"
    # deep tail saturates at -1.0
    v2 = generate_embedding(ASSET_NOW, edge_moments=(40.0, -60.0))
    assert v2[25] == 1.0 and v2[26] == -1.0, "extreme vol/tail clamp"
    # helper: raw std + p10, NaN below min obs
    vol, p10 = edge_risk_moments([1.0, -2.0, 3.0, -4.0] * 6)   # 24 obs
    assert not _isnan(vol) and not _isnan(p10)
    assert all(_isnan(x) for x in edge_risk_moments([1.0, 2.0, 3.0])), "3 obs < min ⇒ NaN"


def test_deltas_nan_when_unmeasured():
    """I1: no prior ⇒ NaN; missing pillar on one side ⇒ that delta NaN, not 0."""
    assert all(_isnan(x) for x in pillar_deltas(ASSET_NOW["pillars"], None)), "no prior ⇒ all NaN"
    d = pillar_deltas({"F": 60, "M": 55, "O": 70, "S": 40, "A": 65},
                      {"F": 50, "M": 55, "O": 70, "S": 40})   # A missing in prior
    assert _isnan(d[4]) and not _isnan(d[0]), "missing pillar ⇒ NaN on that axis only"


def test_stability_std_and_min_obs():
    """stability = normalized trailing std; NaN below min obs (I1)."""
    # O varies, S flat across window incl current
    hist = [{"O": 60, "S": 40}, {"O": 62, "S": 40}, {"O": 70, "S": 40}]
    st = pillar_stability(hist, keys=("O", "S"))
    assert not _isnan(st[0]) and st[0] > 0, "O moved ⇒ positive stability coord"
    assert abs(st[1]) < 1e-9, "S flat ⇒ std 0"
    assert all(_isnan(x) for x in pillar_stability(hist[:2])), "2 obs < min ⇒ NaN"
    assert all(_isnan(x) for x in pillar_stability(None)), "no history ⇒ NaN"


def test_cosine_nan_aware_and_length_tolerant():
    v1 = generate_embedding(ASSET_NOW, macro_regime="Risk-On")                       # 18
    v2 = generate_embedding(ASSET_NOW, macro_regime="Risk-On", prior_pillars=PRIOR)  # 25
    assert abs(cosine_similarity(v2, v2) - 1.0) < 1e-6, "self-sim = 1"
    # 18-vs-25 interop: compares shared prefix, must be ~1 (same asset)
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-6, "length-tolerant prefix compare"
    # NaN dims skipped: a v2 with NaN tail vs another v2 still scores on the 18 real dims
    nanvec = [float("nan")] * 25
    assert cosine_similarity(nanvec, v2) == 0.0, "all-NaN ⇒ refuse (0.0)"
    short = [1.0, 2.0, 3.0]  # only 3 shared < MIN_SHARED_DIMS
    assert cosine_similarity(short, v2) == 0.0, f"<{MIN_SHARED_DIMS} shared ⇒ refuse"


def test_kmeans_survives_nan():
    """k_means must not crash on NaN dims (imputes column mean)."""
    embs = {
        "A": generate_embedding(ASSET_NOW, prior_pillars=PRIOR),                 # deltas set, stab NaN
        "B": generate_embedding({**ASSET_NOW, "symbol": "B", "pillars": {"F": 30, "M": 30, "O": 30, "S": 30, "A": 30}}),  # 18-dim
        "C": generate_embedding({**ASSET_NOW, "symbol": "C"}, prior_pillars={"F": 61, "M": 55, "O": 70, "S": 40, "A": 65}),
    }
    out = k_means_cluster(embs, k=2)
    assert sum(len(v) for v in out.values()) == 3, "all assets assigned, no crash"


def test_store_nan_null_roundtrip():
    """NaN → null → NaN survives JSON (I1); bare json.dumps would emit invalid NaN token."""
    import json
    emb = {"X": [1.0, float("nan"), 0.5]}
    js = json.dumps(store._nan_to_null(emb), allow_nan=False)   # must NOT raise
    assert "null" in js and "NaN" not in js
    back = store._null_to_nan(json.loads(js)["X"])
    assert back[0] == 1.0 and _isnan(back[1]) and back[2] == 0.5


def test_history_row_shape_deltas():
    """history_db rows use bare f/m/o/s/a — _pillars_of + deltas must handle them (provider path)."""
    row_prior = {"symbol": "TEST", "f": 50, "m": 55, "o": 60, "s": 50, "a": 60}
    v = generate_embedding(ASSET_NOW, prior_pillars=row_prior)
    for got, exp in zip(v[18:23], [0.2, 0.0, 0.2, -0.2, 0.1]):
        assert abs(got - exp) < 1e-6, f"bare-key delta {got} != {exp}"


def test_schema_version():
    """Pins the SHAPE, not the number.

    This asserted `SCHEMA_VERSION == 2`. The embedder went to 3 on 2026-08-09 and
    this test would have caught the store's hardcoded 2 — except it was never wired
    into preflight, so it never ran, and the one check that could have seen the
    drift was itself the thing asserting the stale value (S-144).

    A version-equality assertion is a maintenance tax that pays nothing: it fails on
    every legitimate bump and tells you only that someone bumped it. What matters is
    that the DIMENSION CONTRACT holds and that everything writing the version agrees
    with the embedder — pinned here and in test_vector_schema_version_is_single_sourced."""
    assert ASSET_DIMS_V2 == 27, ASSET_DIMS_V2
    assert ASSET_DIMS_V2 - ASSET_DIMS_V1 == 9, "v2 appends 9 dims (5 deltas + 4 stability)"
    assert SCHEMA_VERSION >= 3, (
        f"SCHEMA_VERSION={SCHEMA_VERSION}; v3 (2026-08-09) fixed pillar dims 0..4 "
        f"being identically zero in every stored vector — a regression below 3 would "
        f"silently restore that")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    passed = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); passed += 1
    print(f"\n✅ {passed}/{len(TESTS)} v2 embedder smoke tests passed")
