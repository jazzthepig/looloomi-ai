"""
Vector Search & Cluster Router — CometCloud AI
================================================
Endpoints:
  GET /api/v1/cis/similar        — cosine similarity neighbors for a symbol
  GET /api/v1/cis/cluster        — k-means asset clusters
  GET /api/v1/cis/embeddings     — raw embedding dump (internal / agent use)
  GET /api/v1/market/funding-rates   — full CIS universe funding rate overlay
  GET /api/v1/market/trending-overlay — trending rank overlay on CIS universe
"""

import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Response, Header
from fastapi.responses import JSONResponse

_logger = logging.getLogger(__name__)
router  = APIRouter()

# Mac T1 → Railway asset-vector push contract (MINIMAX_SYNC §ASSET-VECTORS).
ASSET_VECTOR_SCHEMA_VERSION = "1.0"
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


def _load_store():
    """Lazy-import vector store to avoid circular deps at startup."""
    try:
        from src.data.vector.store import load_embeddings, load_meta, embedding_age_seconds
        return load_embeddings, load_meta, embedding_age_seconds
    except ImportError:
        from data.vector.store import load_embeddings, load_meta, embedding_age_seconds
        return load_embeddings, load_meta, embedding_age_seconds



def _embeddings_read_through():
    """Redis first, then the SYSTEM OF RECORD. Returns (embeddings, meta).

    Redis is a CACHE and Supabase is the record (CLAUDE.md). These endpoints used
    to read only the cache and answer 503 "Embeddings not yet computed" when it was
    empty — while durable rows sat in Postgres. The whole embedding write in the CIS
    cycle is wrapped in one broad `except Exception` that degrades to a log line, so
    a single failure anywhere in that block darkened the entire vector layer with no
    signal beyond a warning nobody was reading (S-144).

    A cache miss must read through, never fail. Same lesson the ① book paid for:
    cache miss ⇒ read the record, never start over.
    """
    load_embeddings, load_meta, embedding_age_seconds = _load_store()
    emb = load_embeddings()
    if emb:
        meta = {}
        try:
            meta = dict(load_meta() or {})
        except Exception:
            pass
        meta["source"] = "redis"
        return emb, meta
    try:
        from src.data.vector.pgvector_store import load_embeddings_pg
        return load_embeddings_pg()
    except Exception as e:
        _logger.warning("[vector] pgvector read-through failed: %s", e)
        return {}, {"source": "none", "error": str(e)[:120]}

def _load_embedder():
    try:
        from src.data.vector.embedder import find_similar, k_means_cluster, cosine_similarity
        return find_similar, k_means_cluster, cosine_similarity
    except ImportError:
        from data.vector.embedder import find_similar, k_means_cluster, cosine_similarity
        return find_similar, k_means_cluster, cosine_similarity


def _load_data_layer():
    try:
        from src.data.market.data_layer import get_derivatives_map, get_trending_map
        return get_derivatives_map, get_trending_map
    except ImportError:
        from data.market.data_layer import get_derivatives_map, get_trending_map
        return get_derivatives_map, get_trending_map


async def _get_cached_universe() -> dict | None:
    """Fetch CIS universe from Redis (same key as CIS router). Returns None on miss."""
    try:
        from src.api.store import redis_get
        return await redis_get()
    except Exception:
        try:
            from api.store import redis_get
            return await redis_get()
        except Exception:
            return None


# ── /api/v1/cis/similar ──────────────────────────────────────────────────────

@router.get("/api/v1/cis/similar")
async def get_similar_assets(
    symbol: str = Query(..., description="Target symbol, e.g. ETH"),
    k: int = Query(5, ge=1, le=20, description="Number of neighbors"),
    cross_class: bool = Query(False, description="Exclude same asset class (find cross-class analogs)"),
):
    """
    Return top-k most similar assets to target symbol by cosine similarity.
    Served by the pgvector HNSW index (VDB 落库); falls back to Redis + in-process cosine.
    """
    # VDB 落库: try the pgvector HNSW index first (the real vector DB). Redis+Python is the fallback
    # so the endpoint never hard-depends on the migration being fully populated.
    try:
        from src.data.vector.pgvector_store import similar as _pgv_similar
        pgv = _pgv_similar(symbol.upper(), k=k, class_mode=("cross" if cross_class else "any"))
        if pgv:
            return {
                "symbol": symbol.upper(), "k": k, "cross_class": cross_class,
                "neighbors": [{"symbol": r.get("symbol"),
                               "similarity": round(float(r.get("cosine_sim") or 0), 4),
                               "asset_class": r.get("asset_class")} for r in pgv],
                "source": "pgvector_hnsw",
            }
    except Exception:
        pass  # fall back to Redis + in-process cosine

    load_embeddings, load_meta, embedding_age_seconds = _load_store()
    find_similar, k_means_cluster, cosine_similarity = _load_embedder()

    embeddings, _emb_meta = _embeddings_read_through()
    if not embeddings:
        raise HTTPException(503, "Embeddings unavailable in BOTH the cache and "
                                 "the record — the CIS embedding block has not "
                                 "completed since the last schema migration")

    sym = symbol.upper()
    if sym not in embeddings:
        raise HTTPException(404, f"Symbol '{sym}' not found in embedding store ({len(embeddings)} assets available)")

    # Build asset_classes map from embedding dimension [16] (class_enc × 10)
    # We don't store class separately, so re-derive from CIS universe if needed
    asset_classes: Optional[dict[str, str]] = None
    if cross_class:
        try:
            cached = await _get_cached_universe()
            if cached and cached.get("universe"):
                asset_classes = {a["symbol"].upper(): a.get("asset_class", "Crypto")
                                 for a in cached["universe"]}
        except Exception:
            pass

    results = find_similar(sym, embeddings, k=k,
                           exclude_same_class=cross_class,
                           asset_classes=asset_classes)

    meta = load_meta()
    age  = embedding_age_seconds()

    return {
        "symbol":       sym,
        "k":            k,
        "cross_class":  cross_class,
        "neighbors":    results,
        "embedding_age_seconds": round(age, 0) if age is not None else None,
        "embedding_meta": meta,
        "total_assets": len(embeddings),
    }


# ── /api/v1/cis/cluster ──────────────────────────────────────────────────────

@router.get("/api/v1/cis/cluster")
async def get_asset_clusters(
    k: int = Query(6, ge=2, le=15, description="Number of clusters"),
    seed: int = Query(42, description="Random seed for reproducibility"),
):
    """
    K-means++ clustering of all 84 assets by 18-dim embedding.
    Cluster 0 = highest quality centroid. Returns clusters with per-cluster metadata.
    """
    load_embeddings, load_meta, embedding_age_seconds = _load_store()
    find_similar, k_means_cluster, cosine_similarity = _load_embedder()

    embeddings, _emb_meta = _embeddings_read_through()
    if not embeddings:
        raise HTTPException(503, "Embeddings unavailable in BOTH the cache and "
                                 "the record — the CIS embedding block has not "
                                 "completed since the last schema migration")

    clusters = k_means_cluster(embeddings, k=k, seed=seed)

    # Enrich clusters with CIS data
    try:
        cached = await _get_cached_universe()
        universe_map: dict[str, dict] = {}
        if cached and cached.get("universe"):
            for a in cached["universe"]:
                universe_map[a["symbol"].upper()] = a
    except Exception:
        universe_map = {}

    enriched: list[dict] = []
    for cluster_id, symbols in clusters.items():
        members = []
        scores  = []
        classes: dict[str, int] = {}
        for sym in symbols:
            asset = universe_map.get(sym, {})
            cis   = asset.get("cis_score") or asset.get("score") or 0
            scores.append(cis)
            ac = asset.get("asset_class", "Unknown")
            classes[ac] = classes.get(ac, 0) + 1
            members.append({
                "symbol":     sym,
                "cis_score":  cis,
                "grade":      asset.get("grade", "?"),
                "signal":     asset.get("signal", ""),
                "asset_class": ac,
            })
        members.sort(key=lambda x: -x["cis_score"])
        dominant_class = max(classes, key=classes.get) if classes else "Mixed"
        enriched.append({
            "cluster_id":     cluster_id,
            "size":           len(symbols),
            "avg_cis":        round(sum(scores) / len(scores), 1) if scores else 0,
            "dominant_class": dominant_class,
            "class_breakdown": classes,
            "members":        members,
        })

    # Sort clusters by avg CIS descending
    enriched.sort(key=lambda x: -x["avg_cis"])
    # Re-label: cluster rank 0 = best
    for i, c in enumerate(enriched):
        c["rank"] = i

    meta = load_meta()
    return {
        "k": k,
        "total_assets": len(embeddings),
        "clusters": enriched,
        "embedding_meta": meta,
    }


# ── /api/v1/cis/embeddings ───────────────────────────────────────────────────

@router.get("/api/v1/cis/embeddings")
async def get_embeddings(
    symbol: Optional[str] = Query(None, description="Return single symbol's vector if specified"),
):
    """
    Return raw embedding vectors. Agent / research use.
    Returns all 84 if symbol omitted, or one specific 18-dim vector.
    """
    load_embeddings, load_meta, embedding_age_seconds = _load_store()

    embeddings, _emb_meta = _embeddings_read_through()
    if not embeddings:
        raise HTTPException(503, "Embeddings unavailable in BOTH the cache and "
                                 "the record — the CIS embedding block has not "
                                 "completed since the last schema migration")

    meta = load_meta()
    age  = embedding_age_seconds()

    if symbol:
        sym = symbol.upper()
        vec = embeddings.get(sym)
        if vec is None:
            raise HTTPException(404, f"Symbol '{sym}' not found")
        return {
            "symbol": sym,
            "vector": vec,
            "dims":   len(vec),
            "dim_labels": [
                "F/100","M/100","O/100","S/100","A/100","CIS/100",
                "log_mcap/15","chg_24h_norm","chg_7d_norm","chg_30d_norm",
                "vol_mcap","funding_rate","oi_mcap_ratio","ath_proximity",
                "las/100","confidence","asset_class_enc","regime_alignment",
            ],
            "embedding_meta": meta,
        }

    return {
        "total": len(embeddings),
        "dims":  18,
        "embeddings": embeddings,
        "embedding_age_seconds": round(age, 0) if age is not None else None,
        "embedding_meta": meta,
    }


# ── /api/v1/market/funding-rates ─────────────────────────────────────────────

@router.get("/api/v1/market/funding-rates")
async def get_funding_rates(response: Response = None):
    """
    CoinGecko Pro derivatives: funding rates + OI for all CIS perpetual assets.
    Aggregated by OI-weighted average across all exchanges per symbol.
    Signals: overleveraged_long | bullish_basis | neutral | bearish_basis | extreme_short
    """
    get_derivatives_map, get_trending_map = _load_data_layer()

    try:
        deriv_map = await get_derivatives_map()
    except Exception as e:
        _logger.error(f"[vector] funding-rates error: {e}")
        raise HTTPException(502, f"Derivatives fetch failed: {e}")

    # Get CIS scores to annotate
    cis_map: dict[str, dict] = {}
    try:
        cached = await _get_cached_universe()
        if cached and cached.get("universe"):
            for a in cached["universe"]:
                cis_map[a["symbol"].upper()] = a
    except Exception:
        pass

    rows = []
    for sym, d in deriv_map.items():
        asset = cis_map.get(sym, {})
        fr    = float(d.get("funding_rate") or 0)
        oi    = float(d.get("open_interest_usd") or 0)
        mcap  = asset.get("market_cap") or 0

        rows.append({
            "symbol":           sym,
            "funding_rate_8h":  round(fr * 100, 4),       # as %
            "funding_rate_ann": round(fr * 3 * 365 * 100, 1),  # annualized %
            "open_interest_usd": oi,
            "oi_mcap_ratio":    round(oi / mcap, 4) if mcap > 0 else None,
            "funding_signal":   d.get("funding_signal", "neutral"),
            "markets_count":    d.get("markets_count", 0),
            "cis_score":        asset.get("cis_score"),
            "grade":            asset.get("grade"),
            "signal":           asset.get("signal"),
            "asset_class":      asset.get("asset_class"),
        })

    # Sort by abs(funding_rate) descending — extreme rates first
    rows.sort(key=lambda x: abs(x["funding_rate_8h"]), reverse=True)

    if response:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
    return {
        "count":   len(rows),
        "assets":  rows,
        "note":    "Funding rate per 8h period (OI-weighted avg across all exchanges). Ann = rate × 3 × 365.",
    }


# ── /api/v1/market/trending-overlay ──────────────────────────────────────────

@router.get("/api/v1/market/trending-overlay")
async def get_trending_overlay():
    """
    CoinGecko trending coins overlaid with CIS scores.
    Top 15 coins by CoinGecko trending rank; annotated with CIS grade + signal.
    Used to spot sentiment divergences: trending but low CIS = hype trap.
    """
    get_derivatives_map, get_trending_map = _load_data_layer()

    try:
        trend_map = await get_trending_map()
    except Exception as e:
        _logger.error(f"[vector] trending-overlay error: {e}")
        raise HTTPException(502, f"Trending fetch failed: {e}")

    cis_map: dict[str, dict] = {}
    try:
        cached = await _get_cached_universe()
        if cached and cached.get("universe"):
            for a in cached["universe"]:
                cis_map[a["symbol"].upper()] = a
    except Exception:
        pass

    rows = []
    for sym, rank in sorted(trend_map.items(), key=lambda x: x[1]):
        asset = cis_map.get(sym.upper(), {})
        cis   = asset.get("cis_score")
        rows.append({
            "rank":        rank,
            "symbol":      sym.upper(),
            "in_universe": bool(asset),
            "cis_score":   cis,
            "grade":       asset.get("grade"),
            "signal":      asset.get("signal"),
            "asset_class": asset.get("asset_class"),
            "change_24h":  asset.get("change_24h"),
            # Divergence tag: trending vs CIS conviction
            "divergence": (
                "hype_trap"        if cis is not None and cis < 45 else
                "trending_quality" if cis is not None and cis >= 65 else
                "neutral"
            ),
        })

    return {
        "count":  len(rows),
        "assets": rows,
        "note":   "Hype trap = trending rank top-15 but CIS < 45. Quality = trending + CIS ≥ 65.",
    }


# ── Mac T1 → Railway asset-vector push (MINIMAX_SYNC §ASSET-VECTORS contract v1.0) ──────────
# The Mac engine computes full pillar history; Railway owns the embedding + pgvector write, so
# the vector definition lives in ONE place (embedder.py) and both tiers can't drift apart.

@router.post("/internal/asset-vectors/rebuild")
async def rebuild_asset_vectors(x_internal_token: str = Header(None)):
    """Force a full re-embed of the live universe at the CURRENT schema version.

    WHY A MANUAL TRIGGER (2026-08-12, S-144). Embeddings are written as a side
    effect of the CIS cycle, inside one broad `except Exception` that degrades to a
    log line. When `embedder.SCHEMA_VERSION` moved to 3 the stored rows kept being
    stamped 2 by a hardcoded literal, so every read filtered them out and the whole
    vector layer went dark for 18 days — with no failure anywhere, because nothing
    was failing. It was writing the wrong version, successfully.

    After a version bump there is no automatic path back: the old rows are excluded
    by the version filter and the new ones only appear on the next successful cycle,
    which may itself be the thing that broke. This endpoint closes that gap — it
    runs the same embedder over the same universe and reports what it wrote, so
    "the migration is done" is a fact you can establish rather than wait for.

    Token-guarded and idempotent (upsert on symbol)."""
    _tok = os.environ.get("INTERNAL_TOKEN", "")
    if not _tok or x_internal_token != _tok:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})

    from src.data.vector.embedder import SCHEMA_VERSION, generate_embedding
    from src.data.vector.pgvector_store import upsert_embeddings

    try:
        # The real name is calculate_cis_universe. The first draft imported
        # `get_cis_universe`, which does not exist — caught here only because the
        # endpoint reported the ImportError instead of swallowing it, which is the
        # whole argument for not wrapping this in a bare except (S-103's class).
        from src.data.cis.cis_provider import calculate_cis_universe
        uni = (await calculate_cis_universe()).get("universe") or []
    except Exception as e:
        return JSONResponse(status_code=503,
                            content={"detail": f"universe unavailable: {str(e)[:160]}"})
    if not uni:
        return JSONResponse(status_code=503, content={"detail": "universe is empty"})

    embeddings, failed = {}, []
    regime = None
    for a in uni:
        sym = str(a.get("symbol") or "").upper()
        if not sym:
            continue
        regime = regime or a.get("macro_regime")
        try:
            embeddings[sym] = generate_embedding(a)
        except Exception as e:            # per-asset, never abort the batch
            failed.append(f"{sym}:{str(e)[:60]}")

    if not embeddings:
        return JSONResponse(status_code=500,
                            content={"detail": "embedder produced nothing",
                                     "failed": failed[:10]})

    ameta = {str(a.get("symbol")).upper(): {"asset_class": a.get("asset_class")}
             for a in uni if a.get("symbol")}
    ok = upsert_embeddings(embeddings, asset_meta=ameta, macro_regime=regime)
    return {
        "status": "ok" if ok else "write_failed",
        "written": len(embeddings) if ok else 0,
        "schema_version": SCHEMA_VERSION,
        "dims": len(next(iter(embeddings.values()))),
        "failed_assets": failed[:10],
        "n_failed": len(failed),
        # Stated because a rebuild that wrote 58 rows and a rebuild that wrote 58
        # rows OF THE WRONG SHAPE look identical in a row count.
        "verify": "select schema_version, dims, count(*) from asset_embeddings "
                  "where superseded_reason is null group by 1,2",
    }


@router.get("/internal/vdb-health")
async def vdb_health_endpoint():
    """Freshness of every vector store — the stage loop_health was not watching (S-216).

    Public read: row counts and ages, no vectors and no secrets. Unauthenticated
    on purpose, because a health probe that needs a token is a probe that will be
    skipped by whoever is trying to find out why the substrate went dark.

    Measured the day this was written: asset_embeddings 31 days stale,
    market_state_vectors 19 days stale with regime_label NULL on all 582 rows,
    strategy_records 0 rows. All three were discovered by hand.
    """
    from src.data.vector.vdb_health import vdb_health
    try:
        return await vdb_health()
    except Exception as e:                                        # noqa: BLE001
        # "unknown" — never an empty-looking success. See vdb_health.classify.
        return {"ok": False, "overall": "unknown",
                "reason": f"{type(e).__name__}: {str(e)[:120]}"}


@router.get("/internal/asset-vectors/schema")
async def asset_vectors_schema():
    """Contract echo — the dryrun target both lanes verify against before the live hook fires.
    Mirrors the /internal/cis-scores/schema pattern: the live endpoint IS the source of truth."""
    from src.data.vector.embedder import (
        SCHEMA_VERSION as VEC_SCHEMA, ASSET_DIMS_V1, ASSET_DIMS_V2,
    )
    return {
        "schema_version": ASSET_VECTOR_SCHEMA_VERSION,
        "vector_schema": VEC_SCHEMA,
        "dims_v1": ASSET_DIMS_V1,      # 18 — no v2 inputs supplied
        "dims_v2": ASSET_DIMS_V2,      # 27 — prior_pillars / pillar_history / edge_moments supplied
        "required": ["schema_version", "macro_regime", "assets[].symbol", "assets[].pillars"],
        "optional": ["assets[].prior_pillars", "assets[].pillar_history", "assets[].funding_rate",
                     "assets[].open_interest_usd", "assets[].market_cap", "assets[].volume_24h",
                     "assets[].change_24h", "assets[].change_7d", "assets[].change_30d",
                     "assets[].ath_distance_pct", "assets[].las", "assets[].confidence",
                     "assets[].asset_class"],
        "notes": "edge_moments (v2 dims 25-26) are filled server-side from the asset_edge_moments "
                 "view; absent ⇒ NaN (I1, never 0). NaN never enters pgvector `vec` — the full "
                 "27-dim vector with nulls lives in `vec_full` jsonb.",
    }


@router.post("/internal/asset-vectors")
async def receive_asset_vectors(payload: dict, x_internal_token: str = Header(None)):
    """Receive per-asset pillar/market data from the Mac T1 engine, embed, upsert to pgvector.

    Contract: MINIMAX_SYNC §ASSET-VECTORS v1.0. Best-effort by design — the CIS score push has
    already succeeded by the time this fires, so a failure here must never look like a scoring
    failure (Mac logs WARNING and moves on).
    """
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    sv = str(payload.get("schema_version") or "")
    if sv != ASSET_VECTOR_SCHEMA_VERSION:
        raise HTTPException(status_code=400,
                            detail=f"unknown schema_version {sv!r}; expected {ASSET_VECTOR_SCHEMA_VERSION}")

    assets = payload.get("assets") or []
    if not isinstance(assets, list) or not assets:
        raise HTTPException(status_code=400, detail="assets[] required and must be non-empty")

    try:
        from src.data.vector.embedder import generate_embedding
        from src.data.vector.pgvector_store import upsert_embeddings
        from src.data.cis.cis_provider import canonical_regime_strict
    except Exception as e:
        _logger.error(f"[asset-vectors] import failed: {e}")
        raise HTTPException(status_code=500, detail="embedding modules unavailable")

    # S-123: strict — this label is stored on the embedding and later used to slice
    # them by regime, so a fabricated NEUTRAL silently widens the NEUTRAL cohort.
    regime = canonical_regime_strict(payload.get("macro_regime"))

    # v2 dims [25..26]: risk moments from the asset_edge_moments view. One bulk read; absent ⇒ NaN.
    edge_map: dict = {}
    try:
        import json as _json, urllib.request as _u
        _sb = os.environ.get("SUPABASE_URL", "").rstrip("/")
        _k = os.environ.get("SUPABASE_KEY", "")
        if _sb and _k:
            req = _u.Request(f"{_sb}/rest/v1/asset_edge_moments?select=symbol,edge_vol,edge_p10",
                             headers={"apikey": _k, "Authorization": f"Bearer {_k}"})
            with _u.urlopen(req, timeout=5) as r:
                for row in _json.loads(r.read()):
                    edge_map[str(row["symbol"]).upper()] = (row.get("edge_vol"), row.get("edge_p10"))
    except Exception as e:
        _logger.warning(f"[asset-vectors] edge_moments read failed (dims 25-26 → NaN): {e}")

    embeddings: dict = {}
    asset_meta: dict = {}
    derivatives: dict = {}
    for a in assets:
        sym = str(a.get("symbol") or "").upper()
        if not sym:
            continue
        derivatives[sym] = {"funding_rate": a.get("funding_rate"),
                            "open_interest_usd": a.get("open_interest_usd")}
    n_v2 = 0
    for a in assets:
        sym = str(a.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            vec = generate_embedding(
                a, macro_regime=regime, derivatives=derivatives,
                prior_pillars=a.get("prior_pillars"),
                pillar_history=a.get("pillar_history"),
                edge_moments=edge_map.get(sym),
            )
            embeddings[sym] = vec
            asset_meta[sym] = {"asset_class": a.get("asset_class") or a.get("class")}
            if len(vec) > 18:
                n_v2 += 1
        except Exception as e:
            _logger.warning(f"[asset-vectors] embed {sym} failed: {e}")

    if not embeddings:
        raise HTTPException(status_code=400, detail="no embeddable assets in payload")

    # NO EXPLICIT VERSION (2026-08-12, S-144). This passed schema_version=2,
    # overriding the store's default and re-stamping every vector this endpoint
    # wrote with a version the embedder stopped producing on 2026-08-09. The
    # default now tracks embedder.SCHEMA_VERSION; passing anything here would
    # reintroduce the same drift one layer up.
    ok = upsert_embeddings(embeddings, asset_meta=asset_meta, macro_regime=regime)
    _logger.info(f"[asset-vectors] upsert ok={ok} count={len(embeddings)} v2={n_v2} regime={regime}")
    return {
        "status": "ok" if ok else "error",
        "count": len(embeddings),
        "v2_count": n_v2,                    # how many got the full 27-dim treatment
        "edge_moments_available": len(edge_map),
        "macro_regime": regime,
        "schema_version": ASSET_VECTOR_SCHEMA_VERSION,
        "ts": int(time.time()),
    }
