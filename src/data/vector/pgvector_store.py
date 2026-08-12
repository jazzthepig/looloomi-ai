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
import httpx

# The DEFAULT must track the embedder, not a literal (2026-08-12, S-144). This
# defaulted to 2 while the embedder produced 3, so every caller that did not pass
# the argument explicitly stamped the wrong version — and the stamp is the only
# thing that tells a reader whether a stored vector matches today's shape.
from src.data.vector.embedder import SCHEMA_VERSION
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


def load_embeddings_pg(limit: int = 500) -> tuple[dict[str, list], dict]:
    """Read-through to the SYSTEM OF RECORD. Returns ({symbol: vec}, meta).

    WHY THIS EXISTS (2026-08-12, S-144). `/api/v1/cis/embeddings` read only the
    Redis key and answered 503 "Embeddings not yet computed" when it was empty.
    But CLAUDE.md is explicit that Supabase is the system of record and Redis is a
    cache, and the whole embedding write is wrapped in one broad `except Exception`
    that degrades to a log line — so a single failure anywhere in that block left
    the cache empty and the endpoint dark, while 72 durable rows sat in Postgres.

    A cache miss must READ THROUGH, never fail. That is the same lesson the ① book
    learned the expensive way: cache miss ⇒ read the record, never start over.

    Rows superseded by a schema migration are excluded — they are kept for audit
    (see `superseded_reason`), not for serving, and returning a vector whose shape
    cannot be verified is worse than returning none.
    """
    url, key = _sb()
    if not url or not key:
        return {}, {"source": "unconfigured"}
    q = (f"{url}/rest/v1/asset_embeddings"
         f"?select=symbol,vec_full,dims,schema_version,macro_regime,computed_at"
         f"&schema_version=eq.{SCHEMA_VERSION}&superseded_reason=is.null"
         f"&order=computed_at.desc&limit={limit}")
    try:
        r = httpx.get(q, headers={"apikey": key, "Authorization": f"Bearer {key}"},
                      timeout=10)
        if r.status_code != 200:
            _logger.warning("[pgvector] read %s %s", r.status_code, r.text[:160])
            return {}, {"source": "pgvector", "error": r.status_code}
        rows = r.json() or []
    except Exception as e:
        _logger.warning("[pgvector] read failed: %s", e)
        return {}, {"source": "pgvector", "error": str(e)[:120]}

    out: dict[str, list] = {}
    newest = None
    for row in rows:                      # newest-first → first seen per symbol wins
        sym = str(row.get("symbol") or "").upper()
        vec = row.get("vec_full")
        if not sym or sym in out or not isinstance(vec, list):
            continue
        # JSON null is an UNMEASURED dim (I1) — restore to NaN so cosine skips it
        # rather than treating it as a genuine zero.
        out[sym] = [float("nan") if v is None else float(v) for v in vec]
        newest = newest or row.get("computed_at")
    return out, {"source": "pgvector", "asset_count": len(out),
                 "schema_version": SCHEMA_VERSION, "computed_at": newest}


def upsert_embeddings(embeddings: dict[str, list], *, asset_meta: dict | None = None,
                      macro_regime: str | None = None,
                      schema_version: int = SCHEMA_VERSION) -> bool:
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
