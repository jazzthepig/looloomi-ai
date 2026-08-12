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
