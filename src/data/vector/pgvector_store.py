"""
pgvector store — the PROPER vector-DB path (Seth, 2026-07-23, "VDB 落库").
=========================================================================

Replaces the Redis-JSON blob path (`store.py`) with Supabase **pgvector** — a real vector database
with an HNSW cosine index and SQL k-NN. Redis stored `{symbol: [floats]}` as an opaque JSON string and
did similarity in Python; that is fine at 84 assets but is not a vector DB (no index, no ANN, O(n) scans,
can't scale to text/news embeddings). This module writes to `asset_embeddings` (migration
`vdb_pgvector_asset_embeddings`) and queries the `match_asset_embeddings` RPC.

The I1 (unmeasured ≠ 0) design carries over cleanly:
  · `vec vector(18)` = the DENSE, always-finite v1 core [0..17] — this is what the HNSW cosine index rides.
  · `vec_full jsonb` = the full v2 vector [0..26] with **null** for NaN dims — pgvector rejects NaN, so the
    unmeasured dims live in JSONB for exact NaN-aware re-ranking, never fabricated as 0 in the index.

Best-effort + env-gated (SUPABASE_URL / SUPABASE_KEY). Sync urllib to match the CIS provider's embedding
loop and `store.py`. Intended as a DUAL-WRITE beside Redis first (both), then Redis can be retired.
"""
from __future__ import annotations

import json
import logging
import math
import os
import urllib.request

_logger = logging.getLogger(__name__)

_TABLE = "asset_embeddings"
_RPC = "match_asset_embeddings"
_CORE_DIMS = 18   # the finite v1 core that goes into the pgvector column


def _sb() -> tuple[str, str]:
    return os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_KEY", "")


def _finite(x, default: float = 0.0) -> float:
    """pgvector rejects NaN/Inf — the v1 core is already 0-imputed, but guard defensively."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _vec_literal(vec: list) -> str:
    """First 18 dims → a pgvector text literal '[a,b,...]' (finite-guarded)."""
    core = list(vec)[:_CORE_DIMS]
    if len(core) < _CORE_DIMS:
        core = core + [0.0] * (_CORE_DIMS - len(core))
    return "[" + ",".join(f"{_finite(x):.6g}" for x in core) + "]"


def _full_json(vec: list):
    """Full vector with NaN → None (JSON null) so the unmeasured dims survive without fabrication (I1)."""
    return [None if (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 6) for x in vec]


def upsert_embeddings(embeddings: dict[str, list], *, asset_meta: dict | None = None,
                      macro_regime: str | None = None, schema_version: int = 2) -> bool:
    """Upsert {symbol: full_vec} into pgvector. vec = 18-dim core, vec_full = full v2 (null for NaN).

    `asset_meta` optional {symbol: {asset_class, ...}}. Best-effort — returns False on missing config /
    HTTP failure so a pgvector outage never breaks the CIS cycle (Redis stays the belt-and-braces path).
    """
    url, key = _sb()
    if not url or not key or not embeddings:
        return False
    meta = asset_meta or {}
    rows = []
    for sym, vec in embeddings.items():
        if not vec:
            continue
        m = meta.get(sym, {}) if isinstance(meta.get(sym), dict) else {}
        rows.append({
            "symbol": str(sym).upper(),
            "asset_class": m.get("asset_class"),
            "macro_regime": macro_regime,
            "schema_version": schema_version,
            "dims": len(vec),
            "vec": _vec_literal(vec),
            "vec_full": _full_json(vec),
        })
    if not rows:
        return False
    try:
        req = urllib.request.Request(
            f"{url}/rest/v1/{_TABLE}?on_conflict=symbol",
            data=json.dumps(rows).encode(),
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = r.status in (200, 201, 204)
        if ok:
            _logger.info(f"[pgvector] upserted {len(rows)} asset embeddings")
        return ok
    except Exception as e:
        _logger.warning(f"[pgvector] upsert failed: {e}")
        return False


def similar(symbol: str, k: int = 5, class_mode: str = "any") -> list[dict]:
    """Top-k cosine neighbours via the pgvector HNSW index (the match_asset_embeddings RPC).
    class_mode ∈ 'any' | 'same' | 'cross' (exclude same class). Returns
    [{symbol, asset_class, macro_regime, cosine_sim}]; [] on miss/failure."""
    url, key = _sb()
    if not url or not key:
        return []
    if class_mode not in ("any", "same", "cross"):
        class_mode = "any"
    try:
        req = urllib.request.Request(
            f"{url}/rest/v1/rpc/{_RPC}",
            data=json.dumps({"target": str(symbol).upper(), "k": int(k),
                             "class_mode": class_mode}).encode(),
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read()) or []
    except Exception as e:
        _logger.warning(f"[pgvector] similar({symbol}) failed: {e}")
        return []
