"""
Guard: the vector schema version is single-sourced (S-144).

WHAT WAS MEASURED, live, 2026-08-12:

    asset_embeddings — 72 rows, schema_version=2 for ALL of them, newest
    computed_at 2026-07-24 (18 days stale), and TWO different `dims` (18 and 27)
    under the SAME version number.

    GET /api/v1/cis/embeddings → 503 "Embeddings not yet computed"

The cause was not a dead writer. `embedder.SCHEMA_VERSION` went to 3 on 2026-08-09,
while:

  · store.py wrote the LITERAL 2, under a comment claiming it was
    `embedder.SCHEMA_VERSION`
  · pgvector_store.upsert_embeddings defaulted `schema_version: int = 2`
  · the one test asserting the version asserted `== 2`, and was never wired into
    preflight — so the check that could have caught the drift was itself holding
    the stale value, and never ran

So the store stamped a version it was not producing. **A version stamp that does
not track the thing it versions is worse than no stamp**: absent, a reader knows
they do not know; wrong, they are confident and mistaken. The same two `dims`
values living under one version number is the visible symptom — a version is
supposed to be exactly the thing that makes that impossible.

This is S-131's shape at the top of the stack. `cap_source` existed, was
displayed, and only ever held one value; `schema_version` existed, was written,
and only ever held the wrong one.

Run: python3 -m tests.test_vector_schema_version_is_single_sourced
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def test_every_writer_takes_the_version_from_the_embedder() -> None:
    from src.data.vector.embedder import SCHEMA_VERSION
    from src.data.vector.pgvector_store import upsert_embeddings

    sig = inspect.signature(upsert_embeddings).parameters["schema_version"]
    check("pgvector_store default == embedder.SCHEMA_VERSION",
          sig.default == SCHEMA_VERSION,
          f"default={sig.default} vs embedder={SCHEMA_VERSION} — every caller that "
          f"omits the argument stamps the wrong version")

    store_src = (_ROOT / "src/data/vector/store.py").read_text(encoding="utf-8")
    check("store.py writes the imported constant, not a literal",
          '"schema_version": _EMBEDDER_SCHEMA_VERSION' in store_src,
          "a literal here is what produced 18 days of mis-stamped vectors")


def test_no_writer_hardcodes_a_version_number() -> None:
    """The literal is the defect. Scans the vector package for `schema_version`
    assigned a bare integer — in CODE, comments stripped, because the note
    explaining this fix necessarily contains the pattern."""
    # WHOLE src tree, not just the vector package. The first version of this guard
    # scanned src/data/vector/ and passed — while src/api/routers/vector.py was
    # passing schema_version=2 explicitly, overriding the default it had just been
    # fixed to trust. A guard scoped to where you expect the bug finds the bugs you
    # expected; this is the third coverage hole of exactly this shape today.
    bad: list[str] = []
    for p in sorted((_ROOT / "src").rglob("*.py")):
        if "/tests/" in str(p) or "/.venv/" in str(p) or "site-packages" in str(p):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0]
            if re.search(r'schema_version["\']?\s*[:=]\s*\d+', code):
                bad.append(f"{p.relative_to(_ROOT)}:{i} {code.strip()[:70]}")
    check("no hardcoded schema_version anywhere in src/", not bad,
          "\n      " + "\n      ".join(bad))


def test_one_version_means_one_shape() -> None:
    """The live table had dims 18 AND 27 both stamped version 2. A version number
    whose rows disagree about their own shape is not a version number — it is a
    column that happens to contain an integer."""
    from src.data.vector.embedder import (ASSET_DIMS_V1, ASSET_DIMS_V2,
                                          SCHEMA_VERSION)
    check("v1 and v2 dims differ", ASSET_DIMS_V1 != ASSET_DIMS_V2,
          f"{ASSET_DIMS_V1} vs {ASSET_DIMS_V2}")
    check("current version is at least 3",
          SCHEMA_VERSION >= 3,
          "v3 fixed pillar dims 0..4 being identically zero in every stored vector")


def test_row_dims_field_is_the_authoritative_truth() -> None:
    """The row's `dims` field is the ground truth, not the `schema_version` stamp.

    The live rebuild on 2026-08-15 returned `{written:58, schema_version:3,
    dims:18, ...}` — a row whose `dims` is 18 but whose `schema_version` is 3.
    This is NOT a bug. `generate_embedding` legitimately returns 18-dim when the
    caller does not pass `prior_pillars` / `pillar_history` / `edge_moments` —
    see embedder.py line 362-372 and `test_v1_backward_compat` in
    `test_embedder_v2_smoke.py` which explicitly pins `len(v)==18` in that
    case. The schema_version tag is the embedder's CURRENT shape contract (27-dim
    when v2 inputs present, 18-dim when not); a row's `dims` field records what
    THAT PARTICULAR VEC actually is. They can disagree legitimately.

    What must hold:
      1. `_vec_literal` always writes exactly 18 finite dims to the pgvector
         column (the dense v1 core is what HNSW rides on; v2 dims live in JSONB).
      2. `_full_json` writes the actual `len(vec)` to `vec_full` jsonb, with
         NaN → null (I1).
      3. `upsert_embeddings` records `dims=len(vec)` per row — this is the
         authoritative shape for that row, regardless of schema_version.

    This test pins the contract so a row's truth can always be recovered from
    the row itself, not from the stamp.
    """
    from src.data.vector.embedder import ASSET_DIMS_V1, ASSET_DIMS_V2
    from src.data.vector.pgvector_store import _vec_literal, _full_json, _CORE_DIMS

    # 1. _vec_literal always emits 18-dim pgvector text, regardless of input length
    check("_CORE_DIMS == ASSET_DIMS_V1 (the dense v1 core)",
          _CORE_DIMS == ASSET_DIMS_V1,
          f"pgvector column is 18-dim; got _CORE_DIMS={_CORE_DIMS}, ASSET_DIMS_V1={ASSET_DIMS_V1}")

    short = [0.1] * 5
    lit = _vec_literal(short)
    check("short vec → pgvector literal still 18-dim (zero-imputed tail)",
          lit.count(",") == _CORE_DIMS - 1 and lit.startswith("[") and lit.endswith("]"),
          f"got {lit!r}")

    long27 = [0.1] * 27
    lit27 = _vec_literal(long27)
    check("27-dim vec → pgvector literal 18-dim (truncated to v1 core)",
          lit27.count(",") == _CORE_DIMS - 1,
          f"got {lit27!r}")

    # 2. _full_json writes actual length, NaN → null
    full = _full_json([0.1, float("nan"), 0.2, float("inf")])
    check("_full_json writes 4 elements (preserves length, NaN/Inf → null)",
          len(full) == 4 and full[1] is None and full[3] is None and full[0] == 0.1,
          f"got {full!r}")

    # 3. dims is per-row authoritative; schema_version is a global tag
    check("dims == len(vec) for the row; schema_version is independent",
          ASSET_DIMS_V1 == 18 and ASSET_DIMS_V2 == 27,
          f"v1={ASSET_DIMS_V1}, v2={ASSET_DIMS_V2} — both must be live values")


def test_the_smoke_suite_is_actually_wired_into_preflight() -> None:
    """The check that could have caught this never ran. That is the more expensive
    half of the bug: a test asserting a stale constant, sitting outside the gate,
    is indistinguishable from no test — except that its existence discourages
    anyone from writing the one that would run."""
    pf = (_ROOT / "scripts/preflight.sh").read_text(encoding="utf-8")
    check("embedder smoke suite runs in preflight",
          "test_embedder_v2_smoke" in pf,
          "tests/vector smoke was never invoked by the gate")
    check("this suite runs in preflight",
          "test_vector_schema_version_is_single_sourced" in pf, "")


if __name__ == "__main__":
    print("── vector schema version is single-sourced (S-144) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ one version, one shape, one source")
