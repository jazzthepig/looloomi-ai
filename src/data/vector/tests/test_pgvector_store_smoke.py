"""
Smoke tests — pgvector_store serialization (VDB 落库). Sandbox-safe, pure (no network).
Run: python3 -m src.data.vector.tests.test_pgvector_store_smoke
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.data.vector import pgvector_store as P  # noqa: E402

NAN = float("nan")


def test_vec_literal_takes_18_finite():
    v = [i / 100 for i in range(27)]                     # 27-dim v2
    lit = P._vec_literal(v)
    assert lit.startswith("[") and lit.endswith("]")
    assert len(lit.strip("[]").split(",")) == 18, "pgvector column is the 18-dim core only"


def test_vec_literal_nan_guarded():
    # a NaN inside the core (shouldn't happen for v1, but must never reach pgvector) → 0
    v = [0.5] * 18
    v[3] = NAN
    parts = P._vec_literal(v).strip("[]").split(",")
    assert parts[3] == "0", "NaN in the core is guarded to 0 (pgvector rejects NaN)"


def test_vec_literal_pads_short():
    assert len(P._vec_literal([0.1, 0.2]).strip("[]").split(",")) == 18


def test_full_json_preserves_nan_as_null():
    v = [0.5] * 18 + [NAN, 0.2, NAN, NAN, 0.3, NAN, NAN, NAN, NAN]  # 27-dim, v2 tail has NaN
    fj = P._full_json(v)
    assert len(fj) == 27
    assert fj[18] is None and fj[19] == 0.2, "unmeasured dim → null (I1), measured kept"
    assert all(x is None for x in (fj[18], fj[20], fj[21]))


def test_finite_guard():
    assert P._finite(NAN) == 0.0 and P._finite(float("inf")) == 0.0
    assert P._finite("x", 1.0) == 1.0 and P._finite(0.7) == 0.7


def test_upsert_similar_env_gated():
    # no SUPABASE creds in sandbox ⇒ best-effort no-ops, never raise
    old = os.environ.pop("SUPABASE_URL", None)
    try:
        assert P.upsert_embeddings({"BTC": [0.5] * 27}) is False
        assert P.similar("BTC") == []
    finally:
        if old is not None:
            os.environ["SUPABASE_URL"] = old


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} pgvector_store smoke tests passed")
