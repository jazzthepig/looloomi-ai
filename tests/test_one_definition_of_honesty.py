"""
Guard: one definition of "how honest is this vector", for every writer (S-178).

`asset_embeddings_history` has two writers — scripts/backfill_embedding_history.py
and the Mac-side daily push. The backfill computed `measured_dims` and
`source_completeness` inline and dropped rows below a floor; the daily push wrote
neither and dropped nothing. One table, one honest writer and one not, which is
S-169's shape exactly: nothing compared them, so the daily path would have filled
the table with vectors indistinguishable from complete ones.

THE NUMBER THAT WAS ALMOST WRONG, and it is the reason this file exists rather
than a comment. Minimax-A's migration plan proposed `MIN_MEASURED_DIMS = 4`,
having read `MIN_SHARED_DIMS = 4` in embedder.py — a DIFFERENT quantity, the
point below which cosine refuses to compare two vectors. The write floor is 10 of
27, from backfill_embedding_history.py. Acked as written, the two writers would
have run two thresholds — the precise hole the shared helpers were being
introduced to close.

He asked for the value to be confirmed from source rather than trusting his own
reading, having just been caught assuming `schema_version=3` was right without
checking. **That request is what caught it**, and the lesson generalises past
this file: a transcribed constant is a claim, not a fact.

WHAT THIS PINS
  1. exactly one MIN_MEASURED_DIMS definition, in embedder.py
  2. writers do not re-declare SCHEMA_VERSION as a literal — a writer that can
     state the version can state the wrong one
  3. `vec` is NULL in the pgvector column, never 0.0 — coercing NaN to zero turns
     "unmeasured" into "measured zero", the I1 violation this layer exists for
  4. no always-True honesty flag. A field that cannot be False carries no
     information (S-105); measured_dims already says it, as a number

Run: python3 -m tests.test_one_definition_of_honesty
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.data.vector.embedder import (   # noqa: E402
    ASSET_DIMS_V2,
    MIN_MEASURED_DIMS,
    SCHEMA_VERSION,
    is_thin,
    measured_dims,
    source_completeness,
    vec_to_pg_row,
)

_WRITERS = ["scripts/backfill_embedding_history.py"]

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _code(p: Path) -> str:
    return "\n".join(l for l in p.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))


def test_the_floor_has_one_owner() -> None:
    check("MIN_MEASURED_DIMS is 10 of 27", MIN_MEASURED_DIMS == 10 and ASSET_DIMS_V2 == 27,
          f"got {MIN_MEASURED_DIMS} of {ASSET_DIMS_V2} — this is the WRITE floor. "
          f"MIN_SHARED_DIMS (4) is the cosine-refusal threshold and a different "
          f"quantity; conflating them gives two writers two floors")
    dup = []
    for w in _WRITERS:
        p = _ROOT / w
        if not p.is_file():
            continue
        for m in re.finditer(r"^\s*MIN_MEASURED_DIMS\s*=\s*(\d+)", _code(p), re.M):
            dup.append(f"{w}: literal {m.group(1)}")
    check("no writer re-declares the floor as a literal", not dup,
          "; ".join(dup) + " — a second constant that happens to agree today is "
          "how two writers drift tomorrow; reference the owner and assert")


def test_writers_do_not_hardcode_the_schema_version() -> None:
    bad = []
    for w in _WRITERS:
        p = _ROOT / w
        if not p.is_file():
            continue
        for i, line in enumerate(_code(p).splitlines(), 1):
            if re.match(r"^\s*SCHEMA_VERSION\s*=\s*\d+", line):
                bad.append(f"{w}:{i} {line.strip()}")
    check("writers import SCHEMA_VERSION, never assign it", not bad,
          "; ".join(bad) + " — a writer that can state the version can state the "
          "wrong one, and the row would then be wrong in a way only the row knows")


def test_unmeasured_never_becomes_measured_zero() -> None:
    nan = float("nan")
    v = [1.0] * 12 + [nan] * 15
    row = vec_to_pg_row("2026-08-19", "btc", v, "L1", "TIGHTENING")
    check("pgvector column is NULL, not a coerced vector", row["vec"] is None,
          "pgvector rejects NaN; writing 0.0 to satisfy it turns unmeasured into "
          "measured-zero, which is the I1 violation this layer exists to prevent")
    check("vec_full carries None for unmeasured dims", row["vec_full"][12] is None, "")
    check("and the real values survive", row["vec_full"][0] == 1.0, "")
    check("measured_dims counts only the measured", row["measured_dims"] == 12, "")
    check("source_completeness is the fraction", row["source_completeness"] == 0.444,
          f"got {row['source_completeness']}")
    check("schema_version comes from the module", row["schema_version"] == SCHEMA_VERSION, "")


def test_the_thin_filter_uses_the_shared_floor() -> None:
    nan = float("nan")
    check("9 measured is thin", is_thin([1.0] * 9 + [nan] * 18), "")
    check("10 measured is not", not is_thin([1.0] * 10 + [nan] * 17),
          "the floor is inclusive at MIN_MEASURED_DIMS")
    check("measured_dims uses the NaN identity test", measured_dims([nan, 1.0]) == 1, "")
    check("empty vector does not divide by zero", source_completeness([]) == 0.0, "")


def test_no_always_true_honesty_flag() -> None:
    """A column that can only be True is the always-on warning of S-105 in column
    form. measured_dims and source_completeness already say how honest a row is,
    in numbers a consumer can filter on."""
    row = vec_to_pg_row("2026-08-19", "btc", [1.0] * 27)
    for k, v in row.items():
        check(f"{k} is not a constant-True flag", not (v is True),
              f"{k} can only ever be True and therefore carries no information")


def test_the_receiver_echoes_what_arrived() -> None:
    """Requested by Minimax-A. The sender asserts a schema_version; the receiver
    reflects what actually arrived, so a writer running one version while
    something on the wire says another is visible immediately rather than in a
    query months later."""
    src = (_ROOT / "src/api/routers/mac_push.py").read_text(encoding="utf-8")
    check("endpoint echoes schema_version", "schema_version_echo" in src, "")
    check("and flags a mixed batch", "schema_version_mixed" in src,
          "one batch carrying two versions is a state the sender must be told about")
    check("and reports the measured_dims range", "measured_dims_range" in src,
          "a writer filtering at a different floor than ours shows up here as a "
          "number, instead of being discovered in the data later")
    # Scope to the asset-vectors handler. The first version sliced on the LAST
    # occurrence of schema_version_echo and swept in the risk-meter handler
    # below it, which raises legitimately for a missing argument — the guard
    # reporting a bug that was its own slicing. Narrow the window to the
    # function under test, the same correction as every other over-broad check
    # in this repo.
    fn = src.split("async def push_asset_vectors_history")[1].split("\n@router")[0]
    code = "\n".join(l for l in fn.splitlines() if not l.lstrip().startswith("#"))
    after_echo = code.split("schema_version_echo")[-1]
    check("echo does not REJECT on mismatch",
          "raise HTTPException" not in after_echo,
          "a receiver deciding which of two deployments is right cannot know; it "
          "reports and the sender decides")


if __name__ == "__main__":
    print("── one definition of honesty, for every writer (S-178) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ one floor · one serialiser · unmeasured stays unmeasured · receiver echoes")
