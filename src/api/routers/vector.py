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

    embeddings = load_embeddings()
    if not embeddings:
        raise HTTPException(503, "Embeddings not yet computed — CIS universe may not have loaded yet")

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

    embeddings = load_embeddings()
    if not embeddings:
        raise HTTPException(503, "Embeddings not yet computed")

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

    embeddings = load_embeddings()
    if not embeddings:
        raise HTTPException(503, "Embeddings not yet computed")

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
        from src.data.cis.cis_provider import canonical_regime
    except Exception as e:
        _logger.error(f"[asset-vectors] import failed: {e}")
        raise HTTPException(status_code=500, detail="embedding modules unavailable")

    regime = canonical_regime(payload.get("macro_regime"))

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

    ok = upsert_embeddings(embeddings, asset_meta=asset_meta, macro_regime=regime, schema_version=2)
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
