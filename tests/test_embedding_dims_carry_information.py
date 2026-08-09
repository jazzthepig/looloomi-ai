"""
Embedding dimension guard — a constant dimension is a silent modelling failure.

MEASURED 2026-08-09 on the live `asset_embeddings` table:

    vectors with a real array          58
    five pillar dims [0..4] all zero   58 / 58
    distinct pillar blocks             1     (every asset identical)
    dim 13, dim 17                     constant across all 58
    dims 18..24 (v2 block)             null for all
    vec_full carrying a provenance note 14 assets, {"note":"backfill_pillars_only"}
                                        (INTENTIONAL — Jazz: the note exists so a
                                        future reader knows what a mined row was,
                                        rather than rediscovering it after amnesia.
                                        Not a defect; listed so nobody "fixes" it.)

So the "18-dimensional embedding" that ARCHITECTURE calls the geometric substrate
carries information in fewer than 9 dimensions, and the dead ones are the FIVE CIS
PILLARS — the thing the whole product is built on.

ROOT CAUSE. `generate_embedding` reads pillars as:

    pillars = asset.get("pillars") or {}
    f_raw   = pillars.get("F") or asset.get("f_score", 0) or 0

Two shapes. But `_pillar_of` in main.py documents THREE, and says so explicitly:

    "Pillar value tolerant of every universe shape: nested pillars[K], flat lowercase
     a['k'], or a['pillar_k']. The T2 snapshot writer only read nested pillars[K] — so
     when the builder emits the FLAT shape it wrote NULL pillars every hour (latent
     since inception)."

That is the same bug, already found, already fixed, already documented — in a
different file. The fix was never propagated to the embedder, and nothing pointed
from one to the other. This is the fourth instance in one day of the repo containing
both the corrected and the uncorrected version of the same operation:

    revoke ... from public       vs  revoke ... from anon        (S-125)
    data_layer._redis_set        vs  vector/store._redis_set     (S-127)
    canonical_regime_strict      vs  canonical_regime            (S-120/123)
    _pillar_of                   vs  generate_embedding          (this)

WHY A ZERO-VARIANCE DIMENSION IS WORSE THAN A MISSING ONE. It still contributes to
the vector NORM, so it shrinks every angular difference toward zero — the measured
median pairwise cosine is 0.846 and 29.9% of all pairs sit above the 0.95 the MCP
tool documents as "near-identical". The similarity ranking survives; the absolute
numbers, and every threshold written against them, do not.

Run: python3 -m tests.test_embedding_dims_carry_information
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.vector.embedder import generate_embedding  # noqa: E402

# The three shapes a universe object is known to arrive in. `_pillar_of` in main.py
# enumerates them; the embedder must agree with it, because they read the same objects.
_SHAPES = {
    "nested":   lambda p: {"pillars": {k: v for k, v in p.items()}},
    "flat_low": lambda p: {k.lower(): v for k, v in p.items()},
    "prefixed": lambda p: {f"pillar_{k.lower()}": v for k, v in p.items()},
}

_A = {"F": 79.7, "M": 44.7, "O": 61.9, "S": 19.5, "A": 34.4}   # real BTC values
_B = {"F": 54.4, "M": 45.4, "O": 26.3, "S": 47.8, "A": 20.0}   # real AMZN values


def _pillar_dims(asset: dict) -> list:
    v = generate_embedding({**asset, "symbol": "TEST", "cis_score": 50}, macro_regime="NEUTRAL")
    return list(v[:5])


def test_every_known_universe_shape_reaches_the_pillar_dimensions():
    """The measured defect. In the FLAT LOWERCASE shape the embedder found nothing and
    `or 0` wrote five zeros — for all 58 assets, every rebuild, since inception.

    The `or 0` is what makes it silent: a KeyError would have surfaced on day one."""
    failures = []
    for name, build in _SHAPES.items():
        dims = _pillar_dims(build(_A))
        if all(d == 0 for d in dims):
            failures.append(f"{name}: all five pillar dims are 0 — the shape is not read")
    assert not failures, (
        "generate_embedding cannot see the pillars in these shapes:\n  "
        + "\n  ".join(failures)
        + "\n(main.py::_pillar_of handles all three and documents why — the embedder "
          "must agree with it, they read the same objects)")


def test_two_different_assets_produce_different_pillar_dims_in_every_shape():
    """Behavioural, not structural. A dimension that is identical for every asset
    contributes nothing to any distance while still inflating the norm, which drags
    every pairwise cosine toward 1. It is worse than an absent dimension."""
    failures = []
    for name, build in _SHAPES.items():
        a, b = _pillar_dims(build(_A)), _pillar_dims(build(_B))
        if a == b:
            failures.append(f"{name}: BTC and AMZN pillar blocks are identical ({a})")
    assert not failures, (
        "pillar dimensions carry no information in these shapes:\n  " + "\n  ".join(failures))


def test_a_missing_pillar_is_not_silently_zero():
    """I1 at the source. `or 0` conflates 'this asset has no F score' with 'F is zero',
    and zero is a legitimate pillar value — so the conflation is unrecoverable
    downstream. Unmeasured must be NaN, which cosine_similarity already skips."""
    v = generate_embedding({"symbol": "TEST", "cis_score": 50}, macro_regime="NEUTRAL",
                           unmeasured_as_nan=True)
    dims = list(v[:5])
    assert any(d != d for d in dims), (
        f"with unmeasured_as_nan=True an absent pillar must be NaN, got {dims} — "
        "zero is a real pillar value, so it cannot also mean 'absent'")





def test_the_two_pillar_resolvers_agree_on_every_shape():
    """There were TWO canonical resolvers — embedder._pillars_of and
    main.py::_pillar_of — and each handled a shape the other missed. Neither was
    wrong about what it knew; both were incomplete, and each was written believing
    itself the tolerant one.

    That is the shape of every finding in this code check: the repo holding both the
    corrected and the uncorrected version of one operation, with nothing pointing
    from one to the other. Pin the agreement so the next divergence fails CI instead
    of surfacing as a column of zeros in a vector store months later."""
    import importlib
    emb = importlib.import_module("src.data.vector.embedder")
    main = importlib.import_module("src.api.main")
    shapes = dict(_SHAPES)
    shapes["bare_upper"] = lambda p: dict(p)
    shapes["suffixed"] = lambda p: {f"{k.lower()}_score": v for k, v in p.items()}
    disagree = []
    for name, build in shapes.items():
        obj = build(_A)
        mine = emb._pillars_of(obj)
        for K in ("F", "M", "O", "S", "A"):
            theirs = main._pillar_of(obj, K)
            if theirs is None and mine[K] is None:
                continue
            if theirs is None or mine[K] is None or abs(float(theirs) - mine[K]) > 1e-9:
                disagree.append(f"{name}/{K}: embedder={mine[K]!r} main={theirs!r}")
    assert not disagree, (
        "the two pillar resolvers disagree — one of them is silently writing zeros:\n  "
        + "\n  ".join(disagree))


def test_lowercase_pillar_is_source_conditional_and_stays_last():
    """CORRECTION, 2026-08-09. An earlier draft of this file called the flat lowercase
    `f/m/o/s/a` and the nested `pillars.F/M/O/S/A` "two contradictory pillar sets".
    That was wrong, and Jazz said why in four words: case sensitive, different things.

      T2 / cis_provider   `"f": pillars["F"]`      same quantity
      history_db row      bare f/m/o/s/a           the pillar
      T1 engine payload   f = breakdown.*.score    a DIFFERENT quantity

    BTC in a T1 payload: f=79.7, pillars.F=50.0. The lowercase key is the raw
    sub-score that gets weighted into the total; the nested one is the pillar.

    So the danger is the opposite of what I first wrote. It is not that the data
    contradicts itself — it is that a resolver which accepts BOTH will silently
    substitute one quantity for the other whenever `pillars` happens to be absent.
    A "tolerant" resolver over source-conditional keys is a type confusion.

    What this pins: the nested lookup must come FIRST, so a well-formed T1 object can
    never resolve to the raw score. The remaining exposure — an object carrying only
    lowercase keys from a T1-shaped source — is documented at the call site rather
    than silently collapsed, because collapsing them is the actual error."""
    import importlib
    emb = importlib.import_module("src.data.vector.embedder")
    # a T1-shaped object: BOTH present, DIFFERENT quantities
    t1 = {"pillars": {"F": 50.0, "M": 49.4, "O": 27.0, "S": 55.1, "A": 50.1},
          "f": 79.7, "m": 44.7, "o": 61.9, "s": 19.5, "a": 34.4}
    got = emb._pillars_of(t1)
    assert got["F"] == 50.0, (
        f"nested pillars must win over the lowercase raw score, got F={got['F']} "
        "— resolving to 79.7 would put breakdown sub-scores into the pillar dims")
    assert got["O"] == 27.0 and got["S"] == 55.1

    src = (_REPO_SRC := __import__("pathlib").Path(__file__).resolve().parent.parent
           / "src" / "data" / "vector" / "embedder.py").read_text(encoding="utf-8")
    assert "SOURCE-CONDITIONAL" in src, (
        "the lowercase fallback's source-dependent meaning must be recorded at the "
        "call site — an undocumented tolerant lookup is how the two get collapsed")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} embedding-dimension checks passed")
    sys.exit(1 if f else 0)
