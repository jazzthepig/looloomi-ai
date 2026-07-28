"""
Smoke tests — Entity/Decision store (VDB space #5). Sandbox-safe, pure (no network).
Run: python3 -m src.data.vector.tests.test_entity_store_smoke

Guards the disciplines that make this object evidence rather than storytelling:
provenance mandatory · unmeasured influence flagged not fabricated · lead_score never assumed.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.data.vector import entity_store as E  # noqa: E402


def test_influence_vector_is_12d_and_flags_unmeasured():
    """I1: an unmeasured dim is 0.0 in the vector (pgvector can't hold NaN) but FLAGGED False —
    the flag is the truth; nobody may read the 0 as 'average influence'."""
    vec, measured = E.influence_vector({"capital_log": 9.2, "breadth": 0.4})
    assert len(vec) == 12 == len(E.INFLUENCE_DIMS)
    assert measured["capital_log"] is True and measured["breadth"] is True
    assert measured["lead_score"] is False and vec[E.INFLUENCE_DIMS.index("lead_score")] == 0.0
    assert sum(1 for m in measured.values() if m) == 2, "only the two supplied dims are measured"


def test_influence_vector_rejects_nonfinite():
    vec, measured = E.influence_vector({"capital_log": float("nan"), "breadth": float("inf")})
    assert measured["capital_log"] is False and measured["breadth"] is False
    assert all(v == 0.0 for v in vec), "NaN/Inf never enter the vector column"


def test_record_decision_refuses_without_provenance():
    """Anti-imposter: a decision without a source is not evidence (DB CHECK backs this up)."""
    try:
        E.record_decision("whale:test", "2026-07-27", "unlock", direction=-1.0, magnitude=0.05,
                          targets=["ARB"], provenance={})
        assert False, "should have raised — empty provenance"
    except ValueError as e:
        assert "provenance" in str(e)


def test_record_decision_requires_targets():
    try:
        E.record_decision("whale:test", "2026-07-27", "unlock", direction=-1.0, magnitude=0.05,
                          targets=[], provenance={"src": "x"})
        assert False, "should have raised — no kernel edge"
    except ValueError as e:
        assert "targets" in str(e)


def test_env_gated_best_effort():
    """No creds ⇒ no-ops, never raises (matches pgvector_store contract)."""
    old = os.environ.pop("SUPABASE_URL", None)
    try:
        assert E.upsert_entity("policy:fed", "policy", {"capital_log": 12.0}) is False
        assert E.source_term("2026-07-27") == {}
    finally:
        if old is not None:
            os.environ["SUPABASE_URL"] = old


def test_lead_score_defaults_to_none():
    """lead_score is EARNED (E2) — the store must never write an assumed influence."""
    import inspect
    sig = inspect.signature(E.upsert_entity)
    assert sig.parameters["lead_score"].default is None


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} entity_store smoke tests passed")
