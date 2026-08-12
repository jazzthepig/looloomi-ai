"""
Strategy Vector DB Router — kernel endpoint surface
===================================================

Endpoints (Strategy Vector DB, NOT the multi-factor strategy router):
  GET /api/v1/strategy/list                 — list records with filters
  GET /api/v1/strategy/{id}                 — fetch one record
  GET /api/v1/strategy/similar/{id}         — cosine-similarity neighbors + metadata
  GET /api/v1/strategy/coverage/{id}        — coverage audit for a single record
  GET /api/v1/strategy/stats                — corpus-level summary

The kernel: any decision in the system — a backtest, a sleeve, a behavioral
primitive, a doctrinal rule — must be queryable here. Decision #1 of this
router is to keep names strictly informative (record list, similar by id,
coverage by id) — no marketing varnish.

PIT discipline (mirrors src/api/routers/vector.py): all reads are best-effort
against the Redis cache (2-hour TTL); on miss, returns 503 with a clear
message instead of falling back to a different (potentially stale) source.
The strategy vector is a separate source of truth from the CIS embeddings —
do NOT cross-pollinate.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

_logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Lazy imports — keep router import cost near-zero for non-strategy endpoints
# ---------------------------------------------------------------------------

def _store():
    from src.data.vector.strategy_store import (
        load_all_records, load_all_embeddings, list_records,
        upsert_record, get_record, get_meta, age_seconds,
    )
    return {
        "load_all_records":  load_all_records,
        "load_all_embeddings": load_all_embeddings,
        "list_records":       list_records,
        "upsert_record":      upsert_record,
        "get_record":         get_record,
        "get_meta":           get_meta,
        "age_seconds":        age_seconds,
    }


def _embedder():
    from src.data.vector.strategy_embedder import (
        find_similar, coverage_summary, cosine_similarity, generate_embedding,
    )
    return {
        "find_similar":     find_similar,
        "coverage_summary": coverage_summary,
        "cosine_similarity": cosine_similarity,
        "generate_embedding": generate_embedding,
    }


def _schema():
    from src.data.vector.strategy_schema import StrategyRecord, Verdict
    return StrategyRecord, Verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(record, schema) -> dict:
    """StrategyRecord → JSON-safe dict (verdict enum coerced via to_dict)."""
    return record.to_dict()


# ---------------------------------------------------------------------------
# GET /api/v1/strategy/list
# ---------------------------------------------------------------------------

@router.get("/api/v1/strategy/list")
async def strategy_list(
    verdict: Optional[str] = Query(None, description="Filter by verdict: ship | hold | refute | doctrine"),
    tag: Optional[str] = Query(None, description="Filter by tag substring (matches any tag)"),
    r_prefix: Optional[str] = Query(None, description="Filter by R-number prefix, e.g. 'R4' for R40–R49"),
    k: int = Query(default=50, ge=1, le=500, description="Max records to return"),
    min_coverage: float = Query(
        default=0.0, ge=0.0, le=1.0,
        description="Min coverage_pct — drops skeletons below this threshold",
    ),
    sort_by: str = Query(
        default="coverage",
        description="Sort key: 'coverage' (default) | 'verdict' | 'recent'",
    ),
):
    """
    List strategy records with optional filters. Returns the records (without
    embeddings) so the kernel can decide what to embed on the fly.

    Coverage filter is the cheap proxy for "is this record queryable in cosine
    space?" A record with <30% coverage is mostly zeros and will distort
    neighbor results; drop it unless you really want raw inspection.
    """
    StrategyRecord, Verdict = _schema()
    modules = _store()
    emb_mods = _embedder()

    # Verdict coercion with friendly error
    verdict_enum: Optional[Verdict] = None
    if verdict:
        try:
            verdict_enum = Verdict(verdict)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"verdict must be one of {[v.value for v in Verdict]}, got '{verdict}'",
            )

    records = modules["list_records"](
        verdict=verdict_enum, tag=tag, r_number_prefix=r_prefix,
    )

    # Compute coverage for filter + sort
    out: list[dict] = []
    for r in records:
        cov = emb_mods["coverage_summary"](r)
        if cov["coverage_pct"] / 100.0 < min_coverage:
            continue
        d = r.to_dict()
        d["coverage"] = cov
        out.append(d)

    # Sort
    if sort_by == "coverage":
        out.sort(key=lambda x: -x["coverage"]["coverage_pct"])
    elif sort_by == "verdict":
        # ship > doctrine > hold > refute — order by last-letter of "sOdHhRr"
        vrank = {"ship": 0, "doctrine": 1, "hold": 2, "refute": 3}
        out.sort(key=lambda x: (vrank.get(x.get("verdict", "refute"), 9), -x["coverage"]["coverage_pct"]))
    elif sort_by == "recent":
        out.sort(key=lambda x: x.get("updated_at") or x.get("registered_at") or "", reverse=True)
    else:
        raise HTTPException(status_code=400, detail=f"unknown sort_by '{sort_by}'")

    out = out[:k]

    meta = modules["get_meta"]()
    return {
        "count":  len(out),
        "total":  len(records),
        "age_s":  modules["age_seconds"](),
        "meta":   meta,
        "filters": {
            "verdict":        verdict,
            "tag":            tag,
            "r_prefix":       r_prefix,
            "min_coverage":   min_coverage,
            "sort_by":        sort_by,
        },
        "records": out,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/strategy/{id}
# ---------------------------------------------------------------------------

@router.get("/api/v1/strategy/similar/{record_id}")
async def strategy_similar(
    record_id: str,
    k: int = Query(default=5, ge=1, le=50, description="Max neighbors to return"),
    include_doctrine: bool = Query(default=True, description="Include DOCTRINE records"),
    exclude_verdict: Optional[str] = Query(
        default=None,
        description="Exclude these verdicts (comma-sep): ship,hold,refute,doctrine",
    ),
    exclude_self: bool = Query(default=True, description="Drop target from neighbors (default true)"),
):
    """
    Top-k cosine-similarity neighbors with full record metadata.

    The kernel uses this to surface analogous experiments — when a sleeve is
    shipped, find what else in the corpus looks like it; when one refutes, find
    corroborating patterns.
    """
    StrategyRecord, Verdict = _schema()
    modules = _store()
    emb_mods = _embedder()

    records = modules["load_all_records"]()
    if record_id not in records:
        raise HTTPException(status_code=404, detail=f"record '{record_id}' not in strategy:records")

    embeddings = modules["load_all_embeddings"]()
    if not embeddings or record_id not in embeddings:
        raise HTTPException(
            status_code=503,
            detail="embeddings cache empty — run scripts/backfill_strategies.py --write first",
        )

    # Raw neighbors (id + sim only)
    raw = emb_mods["find_similar"](
        target_id=record_id,
        embeddings=embeddings,
        k=len(embeddings),  # pull all to filter
        include_doctrine=include_doctrine,
    )

    # Verdict exclusion
    excl_set: set[str] = set()
    if exclude_verdict:
        for v in exclude_verdict.split(","):
            v = v.strip().lower()
            try:
                Verdict(v)
                excl_set.add(v)
            except Exception:
                pass

    # Hydrate with metadata + filter
    out: list[dict] = []
    for n in raw:
        nid = n["id"]
        if exclude_self and nid == record_id:
            continue
        rec = records.get(nid)
        if rec is None:
            continue
        if rec.verdict.value in excl_set:
            continue
        if not include_doctrine and rec.verdict == Verdict.DOCTRINE:
            continue
        d = rec.to_dict()
        d["similarity"] = n["similarity"]
        d["coverage"] = emb_mods["coverage_summary"](rec)
        out.append(d)
        if len(out) >= k:
            break

    target_cov = emb_mods["coverage_summary"](records[record_id])
    return {
        "target_id":     record_id,
        "target_verdict": records[record_id].verdict.value,
        "target_coverage": target_cov,
        "k":             k,
        "neighbors":     out,
        "n_returned":    len(out),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/strategy/coverage/{id}
# ---------------------------------------------------------------------------

@router.get("/api/v1/strategy/coverage/{record_id}")
async def strategy_coverage(record_id: str):
    """
    Coverage audit for a single record — which 6 dim blocks are filled, %
    of 30-dim vector that is non-zero. Anti-imposter: a record with <30%
    coverage is mostly skeleton — never let its cosine neighbors mislead.
    """
    modules = _store()
    emb_mods = _embedder()
    records = modules["load_all_records"]()

    rec = records.get(record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"record '{record_id}' not in strategy:records")

    cov = emb_mods["coverage_summary"](rec)
    emb = emb_mods["generate_embedding"](rec)

    # Per-dim breakdown of MEASURED dims (non-NaN; a measured 0 is information under I1). NaN
    # (unmeasured) dims are skipped — and never enter the JSON response (invalid token otherwise).
    nonzero = [(i, round(v, 3)) for i, v in enumerate(emb) if v == v]

    return {
        "record_id":     record_id,
        "verdict":       rec.verdict.value,
        "tags":          rec.tags,
        "r_number":      rec.r_number,
        "coverage":      cov,
        "embedding_dims_total":    len(emb),
        "embedding_dims_nonzero":  len(nonzero),
        "nonzero_dims":  nonzero,
        "fields": {
            "regime_domain":      rec.regime_domain,
            "factor_exposure":    rec.factor_exposure,
            "mechanics":          rec.mechanics,
            "capacity":           rec.capacity,
            "lifecycle":          rec.lifecycle,
            "cost_sensitivity":   rec.cost_sensitivity,
            "realized_alpha":     rec.realized_alpha,
            "realized_decay":     rec.realized_decay,
            "outcome_confidence": rec.outcome_confidence,
        },
    }


# ---------------------------------------------------------------------------
# GET /api/v1/strategy/stats
# ---------------------------------------------------------------------------

@router.get("/api/v1/strategy/stats")
async def strategy_stats():
    """
    Corpus-level summary: total records, by-verdict, by-source, coverage
    histogram, age. Cheap (one Redis GET per key).
    """
    modules = _store()
    emb_mods = _embedder()
    records = modules["load_all_records"]()

    by_verdict: dict[str, int] = {}
    by_source: dict[str, int] = {}
    coverage_buckets = {"<10%": 0, "10-30%": 0, "30-60%": 0, "60-90%": 0, ">=90%": 0}
    queryable = 0
    total_dims_nonzero = 0

    for r in records.values():
        by_verdict[r.verdict.value] = by_verdict.get(r.verdict.value, 0) + 1
        by_source[r.doc_source]    = by_source.get(r.doc_source, 0) + 1
        cov = emb_mods["coverage_summary"](r)
        pct = cov["coverage_pct"]
        if pct < 10:
            coverage_buckets["<10%"] += 1
        elif pct < 30:
            coverage_buckets["10-30%"] += 1
        elif pct < 60:
            coverage_buckets["30-60%"] += 1
        elif pct < 90:
            coverage_buckets["60-90%"] += 1
        else:
            coverage_buckets[">=90%"] += 1
        if pct >= 40:
            queryable += 1
        total_dims_nonzero += cov["dims_nonzero"]

    meta = modules["get_meta"]()
    return {
        "total":           len(records),
        "queryable":       queryable,
        "skeleton":        len(records) - queryable,
        "by_verdict":      by_verdict,
        "by_source":       by_source,
        "coverage_buckets": coverage_buckets,
        "avg_dims_nonzero": round(total_dims_nonzero / max(1, len(records)), 2),
        "age_s":           modules["age_seconds"](),
        "meta":            meta,
    }

@router.get("/api/v1/strategy/{record_id}")
async def strategy_get(record_id: str):
    """Fetch one record by id. 404 if missing."""
    modules = _store()
    emb_mods = _embedder()

    rec = modules["get_record"](record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"record '{record_id}' not in strategy:records")

    d = rec.to_dict()
    d["coverage"] = emb_mods["coverage_summary"](rec)

    # Resolve embedding (full vector only if asked)
    embeddings = modules["load_all_embeddings"]()
    if record_id in embeddings:
        d["embedding_dims_filled"] = sum(1 for v in embeddings[record_id] if abs(v) > 1e-9)

    return d


# ---------------------------------------------------------------------------
# GET /api/v1/strategy/similar/{id}
# ---------------------------------------------------------------------------

