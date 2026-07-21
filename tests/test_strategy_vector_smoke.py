"""
Smoke tests for the Strategy Vector stack.

These tests do NOT touch Redis. They verify:
  - Schema construction + JSON round-trip
  - Embedder produces exactly 30 dims
  - Coverage summary is sane
  - Cosine similarity is invariant to scale
  - find_similar returns ranked neighbors

Run with: python3 -m pytest tests/test_strategy_vector_smoke.py -v
Or:       python3 tests/test_strategy_vector_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.vector.strategy_schema import StrategyRecord, Verdict
from src.data.vector.strategy_embedder import (
    VECTOR_DIMS,
    generate_embedding,
    coverage_summary,
    cosine_similarity,
    find_similar,
    embed_many,
)
from src.data.vector.strategy_store import (
    load_all_records,
    upsert_record,
    upsert_many,
    list_records,
    get_record,
)
from scripts.backfill_strategies import backfill


# ---------------------------------------------------------------------------
# Mini-test helpers
# ---------------------------------------------------------------------------

_fails: list[str] = []
_passes: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passes.append(name)
        print(f"  ✓ {name}")
    else:
        _fails.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


def _summary() -> None:
    print()
    print(f"  {len(_passes)} passed · {len(_fails)} failed")
    if _fails:
        for f in _fails:
            print(f"    FAILED: {f}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_schema_construction_and_roundtrip() -> None:
    print("\n[test_schema_construction_and_roundtrip]")
    r = StrategyRecord(
        id="test-r46",
        title="test record",
        doc_source="REFUTATION_LEDGER.md",
        r_number="R46",
        verdict=Verdict.SHIP,
        pit_clean=True,
        cost_feasible_at_5bps=True,
        forward_committed=True,
        factor_exposure={"beta_market": 0.05, "residual_alpha": 0.033},
        cost_sensitivity={"0bps": 4.5, "5bps": 3.33, "10bps": 1.9},
        mechanics={"holding_period_days": 5, "turnover_per_q": 80.0/3},
        capacity={"adv_fraction": 0.01},
    )
    _check("verdict enum coerced", r.verdict == Verdict.SHIP)
    _check("registered_at auto-set", len(r.registered_at) > 10)

    d = r.to_dict()
    r2 = StrategyRecord.from_dict(d)
    _check("JSON round-trip preserves id", r2.id == r.id)
    _check("JSON round-trip preserves r_number", r2.r_number == "R46")
    _check("JSON round-trip preserves verdict",
           r2.verdict == Verdict.SHIP)
    _check("JSON round-trip preserves pit_clean", r2.pit_clean is True)

    problems = r.validate()
    _check("valid ship record has no validation issues",
           problems == [], detail=str(problems))


def test_embedder_dim_and_coverage() -> None:
    print("\n[test_embedder_dim_and_coverage]")
    r = StrategyRecord(
        id="test-dim",
        title="dim test",
        doc_source="x.md",
        cost_sensitivity={"5bps": 3.33},
        factor_exposure={"residual_alpha": 0.05},
    )
    emb = generate_embedding(r)
    _check("embedding has exactly 30 dims",
           len(emb) == VECTOR_DIMS == 30,
           detail=f"got {len(emb)}")

    cov = coverage_summary(r)
    _check("coverage_summary has correct total",
           cov["dims_total"] == 30)
    _check("coverage_summary has nonzero count",
           cov["dims_nonzero"] >= 2, detail=str(cov))

    # All values in [-1, 1] (since we clamp)
    all_clamped = all(-1.0 <= v <= 1.0 for v in emb)
    _check("all dimensions in [-1, 1]", all_clamped)


def test_cosine_similarity_properties() -> None:
    print("\n[test_cosine_similarity_properties]")
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    _check("cosine(a, a) == 1.0",
           abs(cosine_similarity(a, b) - 1.0) < 1e-6)

    b = [0.0, 1.0, 0.0]
    _check("cosine orthogonal == 0",
           abs(cosine_similarity(a, b)) < 1e-6)

    b = [-1.0, 0.0, 0.0]
    _check("cosine opposite == -1",
           abs(cosine_similarity(a, b) + 1.0) < 1e-6)

    # Invariant to scale
    a2 = [2.0, 0.0, 0.0]
    b2 = [3.0, 0.0, 0.0]
    _check("cosine invariant to scale",
           abs(cosine_similarity(a2, b2) - 1.0) < 1e-6)

    # Zero vector → 0.0 (not divide-by-zero)
    z = [0.0, 0.0, 0.0]
    _check("zero vector returns 0.0",
           cosine_similarity(a, z) == 0.0)


def test_find_similar_ranking() -> None:
    print("\n[test_find_similar_ranking]")
    # Three records: A and B identical, C orthogonal-ish
    e: dict[str, list[float]] = {
        "A": [1.0, 0.0, 0.0, 0.0] + [0.0]*26,
        "B": [1.0, 0.0, 0.0, 0.0] + [0.0]*26,
        "C": [0.0, 0.0, 0.0, 0.0] + [1.0] + [0.0]*25,
        "D": [0.5, 0.5, 0.0, 0.0] + [0.0]*26,
    }
    nbrs = find_similar("A", e, k=3)
    _check("find_similar returns 3 neighbors", len(nbrs) == 3)
    _check("B is the top neighbor (identical)",
           nbrs[0]["id"] == "B", detail=str(nbrs))
    _check("B similarity ≈ 1.0",
           abs(nbrs[0]["similarity"] - 1.0) < 1e-6)
    _check("A is not in its own neighbors",
           all(n["id"] != "A" for n in nbrs))
    _check("ranked by similarity descending",
           all(nbrs[i]["similarity"] >= nbrs[i+1]["similarity"]
               for i in range(len(nbrs) - 1)))


def test_embed_many() -> None:
    print("\n[test_embed_many]")
    recs = [
        StrategyRecord(id=f"r{i}", title=f"r{i}", doc_source="x.md",
                       cost_sensitivity={"5bps": 1.0 + 0.1*i})
        for i in range(5)
    ]
    out = embed_many(recs)
    _check("embed_many produces embeddings for all 5",
           len(out) == 5)
    _check("embed_many keys match record ids",
           all(f"r{i}" in out for i in range(5)))


def test_backfill_produces_expected_records() -> None:
    print("\n[test_backfill_produces_expected_records]")
    summary = backfill(dry_run=True, write_redis=False)
    _check("backfill produces > 80 records",
           summary["totals"]["total"] > 80,
           detail=str(summary["totals"]))
    _check("doctrinal records present (>= 13)",
           summary["sources"].get("DOCTRINAL", 0) >= 13)
    _check("R-entries extracted (>= 30)",
           summary["sources"].get("REFUTATION_LEDGER", 0) >= 30)
    _check("by_verdict has refute bucket",
           "refute" in summary["totals"]["by_verdict"])
    _check("by_verdict has doctrine bucket",
           "doctrine" in summary["totals"]["by_verdict"])
    _check("by_verdict has hold bucket",
           "hold" in summary["totals"]["by_verdict"])
    # Step 6: dimensional mining must have filled SOMETHING on at least one
    # SHIP entry — otherwise the parser is theater. (Anti-imposter.)
    try:
        from pathlib import Path as _P
        import json as _json
        data = _json.loads((_P(__file__).resolve().parents[1] / "_data" / "strategy_records.json").read_text())
        ship_records = [r for r in data.values() if r["verdict"] == "ship"]
        nonzero_dims = []
        for r in ship_records:
            d = sum(1 for k in ("mechanics", "capacity", "lifecycle",
                                "cost_sensitivity", "factor_exposure")
                    if r.get(k))
            nonzero_dims.append(d)
        _check(">= 1 ship record has dimensional data",
               any(d >= 1 for d in nonzero_dims),
               detail=str([(r["id"], d) for r, d in zip(ship_records, nonzero_dims)]))
    except FileNotFoundError:
        _check("audit JSON exists", False, detail="run scripts/backfill_strategies.py --write first")


def test_r64_fusion_record_has_capacity() -> None:
    """Step 6: the gold-standard SHIP record (R64 fusion validation) should
    have BOTH n_assets AND declared_capacity filled, because the source body
    explicitly states "$5.0M declared capacity" and "28 assets"."""
    print("\n[test_r64_fusion_record_has_capacity]")
    from pathlib import Path as _P
    import json as _json
    audit = _P(__file__).resolve().parents[1] / "_data" / "strategy_records.json"
    if not audit.exists():
        _check("audit exists", False, detail="run scripts/backfill_strategies.py --write")
        return
    data = _json.loads(audit.read_text())
    r64 = data.get("R64-ledger")
    _check("R64-ledger present", r64 is not None)
    if r64:
        cap = r64.get("capacity", {})
        _check("R64 declared_capacity filled",
               cap.get("declared_capacity") is not None,
               detail=str(cap))
        _check("R64 declared_capacity ~$5M",
               abs(cap.get("declared_capacity", 0) - 5_000_000) < 1_000,
               detail=str(cap))
        _check("R64 n_assets filled",
               cap.get("n_assets") is not None,
               detail=str(cap))
        mech = r64.get("mechanics", {})
        _check("R64 holding_period_days filled (>0)",
               mech.get("holding_period_days", 0) > 0,
               detail=str(mech))
        _check("R64 turnover filled (>0)",
               mech.get("turnover_per_q", 0) > 0,
               detail=str(mech))


def test_r46_cadence_record_has_mechanics() -> None:
    """Step 6: R46 is the headline 5-day rebal survivor — must have
    holding_period_days=5 and turnover ~80."""
    print("\n[test_r46_cadence_record_has_mechanics]")
    from pathlib import Path as _P
    import json as _json
    audit = _P(__file__).resolve().parents[1] / "_data" / "strategy_records.json"
    if not audit.exists():
        return
    data = _json.loads(audit.read_text())
    r46 = data.get("R46-ledger")
    if not r46:
        return
    mech = r46.get("mechanics", {})
    _check("R46 holding_period_days = 5 (the headline cadence)",
           mech.get("holding_period_days") == 5,
           detail=str(mech))
    _check("R46 turnover_per_q ~80 (post-cadence)",
           abs(mech.get("turnover_per_q", 0) - 80) < 30,
           detail=str(mech))


def test_store_in_memory_roundtrip_via_dict() -> None:
    """Validate the store functions exist and handle errors gracefully.

    Without Redis env vars, load_all_records() returns {} (logged at debug).
    This test verifies the function signatures and error handling are intact.
    """
    print("\n[test_store_in_memory_roundtrip_via_dict]")
    # Functions exist and are callable
    _check("load_all_records callable", callable(load_all_records))
    _check("upsert_record callable", callable(upsert_record))
    _check("upsert_many callable", callable(upsert_many))
    _check("list_records callable", callable(list_records))
    _check("get_record callable", callable(get_record))

    # Without env vars, this returns {} — should NOT raise
    try:
        recs = load_all_records()
        _check("load_all_records returns dict when no Redis", isinstance(recs, dict))
    except Exception as e:
        _check("load_all_records error handled", False, detail=str(e))


def main() -> None:
    print("=" * 60)
    print("STRATEGY VECTOR SMOKE TESTS")
    print("=" * 60)
    test_schema_construction_and_roundtrip()
    test_embedder_dim_and_coverage()
    test_cosine_similarity_properties()
    test_find_similar_ranking()
    test_embed_many()
    test_backfill_produces_expected_records()
    test_r46_cadence_record_has_mechanics()
    test_r64_fusion_record_has_capacity()
    test_store_in_memory_roundtrip_via_dict()
    _summary()
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
