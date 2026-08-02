"""
Strategy Vector Store — durable Postgres jsonb (records) + Redis (embeddings).
===========================================================================

Seth, 2026-07-26 (MINIMAX_SYNC §VDB — strategy vectors item, 2026-07-23).

Source of truth for the strategy corpus moves from Redis-24h-TTL to a durable
Postgres jsonb table. Embeddings remain in Redis as a derived cache (rebuildable
from records via `strategy_embedder.generate_embedding`). Similarity stays in
Python NaN-aware cosine — at this scale pgvector-ANN gives no benefit AND its
dense cosine would impute unmeasured→0, silently corrupting R62-style risk
moments / sparse coverage analysis.

PIT discipline: every write to Postgres replaces the WHOLE record (no patch),
matching the previous Redis semantics. The single-row upsert is idempotent
(`on conflict (id) do update`).

Fallback: when Postgres is not configured (SUPABASE_URL/KEY missing), we fall
back to the legacy Redis-only path — same 24h TTL store. This preserves
behavior in dev environments without Supabase wiring.

Migration helper: `migrate_redis_to_postgres()` does a one-time bulk backfill
of every record currently in Redis → Postgres. Idempotent (Postgres upserts).
Call it ONCE at deploy time. The repo also ships a forward-only ship flag
`STRATEGY_RECORDS_DUAL_WRITE=1` (default ON) that writes BOTH paths during the
cutover window, then can be turned off in a follow-up.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Optional

from .strategy_schema import StrategyRecord, Verdict
from .strategy_embedder import generate_embedding, VECTOR_DIMS

_logger = logging.getLogger(__name__)

# Redis stays as the EMBEDDING cache (rebuildable from records).
_RECORDS_KEY   = "strategy:records"
_EMBED_KEY     = "strategy:embeddings"
_META_KEY      = "strategy:meta"
_TTL           = 86_400  # 24h (Redis cache TTL; only embeddings + meta live here)


# ============================================================================
# Configuration
# ============================================================================

def _sb_url_key():
    return os.environ.get("SUPABASE_URL", "").rstrip("/"), \
           os.environ.get("SUPABASE_KEY", "") or os.environ.get("SUPABASE_SERVICE_KEY", "")


def _dual_write_enabled() -> bool:
    """When Postgres is configured, write BOTH Postgres (durable) + Redis
    (embeddings cache) in the cutover window. Set to "0" to turn off Redis
    after migration is fully verified.
    """
    return os.environ.get("STRATEGY_RECORDS_DUAL_WRITE", "1") not in ("0", "false", "False")


# ============================================================================
# Redis helpers (unchanged — embeddings cache only)
# ============================================================================

def _redis_get(key: str) -> Optional[str]:
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    try:
        req = urllib.request.Request(
            f"{url}/get/{key}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
            return data.get("result")
    except Exception as e:
        _logger.debug(f"[StrategyStore] Redis GET {key} failed: {e}")
        return None


def _redis_set(key: str, value: str, ttl: int = _TTL) -> bool:
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return False
    try:
        payload = json.dumps(["SET", key, value, "EX", str(ttl)]).encode()
        req = urllib.request.Request(
            f"{url}/pipeline",
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        return True
    except Exception as e:
        _logger.warning(f"[StrategyStore] Redis SET {key} failed: {e}")
        return False


# ============================================================================
# Postgres helpers (NEW source of truth)
# ============================================================================

def _pg_upsert(id_: str, record_dict: dict) -> bool:
    """Upsert one record into Supabase `strategy_records` (jsonb).

    Uses `Prefer: resolution=merge-duplicates` so an existing row gets
    replaced; a missing row gets inserted. Single round-trip per upsert.
    """
    base, key = _sb_url_key()
    if not base or not key:
        return False
    url = f"{base}/rest/v1/strategy_records"
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    body = json.dumps([{"id": id_, "record": record_dict}]).encode()
    req = urllib.request.Request(
        url, data=body, headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True
    except Exception as e:
        _logger.warning(f"[StrategyStore] PG upsert {id_}: {e}")
        return False


def _pg_select_all() -> Optional[dict[str, dict]]:
    """Read every strategy row from Postgres. None on error; {} on empty."""
    base, key = _sb_url_key()
    if not base or not key:
        return None
    url = f"{base}/rest/v1/strategy_records?select=id,record"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return {row["id"]: row["record"] for row in json.loads(r.read())}
    except Exception as e:
        _logger.warning(f"[StrategyStore] PG select: {e}")
        return None


def _pg_count() -> int:
    base, key = _sb_url_key()
    if not base or not key:
        return -1
    url = f"{base}/rest/v1/strategy_records?select=id"
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Prefer": "count=exact", "Range-Unit": "items",
        "Range": "0-0",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            cr = r.headers.get("content-range", "0/0")
            if "/" in cr:
                return int(cr.rsplit("/", 1)[1])
    except Exception as e:
        _logger.warning(f"[StrategyStore] PG count: {e}")
    return -1


def _pg_delete_id(id_: str) -> bool:
    base, key = _sb_url_key()
    if not base or not key:
        return False
    url = f"{base}/rest/v1/strategy_records?id=eq.{urllib.parse.quote(id_)}"
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Prefer": "return=minimal",
    }
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True
    except Exception as e:
        _logger.warning(f"[StrategyStore] PG delete {id_}: {e}")
        return False


# ============================================================================
# I1 NaN↔null — v-honest embeddings carry NaN for unmeasured dims; bare json.dumps(NaN)
# emits an invalid `NaN` token that Upstash/JS JSON.parse rejects. Serialize NaN→null,
# restore null→NaN on load so cosine's NaN-skip sees unmeasured dims.
# ============================================================================

def _nan_to_null(vec):
    return [None if isinstance(v, float) and v != v else v for v in vec]


def _null_to_nan(vec):
    return [float("nan") if v is None else float(v) for v in vec]


def _dump_embeddings(embeds):
    return json.dumps({k: _nan_to_null(v) for k, v in embeds.items()}, allow_nan=False)


# ============================================================================
# Public API
# ============================================================================

def load_all_records() -> dict[str, StrategyRecord]:
    """Load every strategy record. Primary = Postgres (durable, MINIMAX_SYNC §VDB).
    Falls back to Redis cache when Postgres is unavailable.

    Returns {} on any miss/error.
    """
    pg = _pg_select_all()
    if pg is not None:
        return {k: StrategyRecord.from_dict(v) for k, v in pg.items()}

    # Fallback — Redis cache (legacy path, deprecated after migration)
    raw = _redis_get(_RECORDS_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: StrategyRecord.from_dict(v) for k, v in data.items()}
    except Exception as e:
        _logger.warning(f"[StrategyStore] Failed to parse Redis records: {e}")
        return {}


def load_all_embeddings() -> dict[str, list[float]]:
    """Load pre-computed N-dim embeddings from Redis (rebuilt from records
    on a miss by recomputing via `strategy_embedder.generate_embedding`).

    Returns {} on full miss/error.
    """
    raw = _redis_get(_EMBED_KEY)
    if raw:
        try:
            data = json.loads(raw)
            return {k: _null_to_nan(v) for k, v in data.items()
                    if len(v) == VECTOR_DIMS}
        except Exception as e:
            _logger.warning(f"[StrategyStore] Failed to parse embeddings: {e}")

    # Cold start / cache evicted — rebuild from records (always works because
    # records have a durable home now).
    records = load_all_records()
    if not records:
        return {}
    out = {rid: generate_embedding(rec) for rid, rec in records.items()}
    # Best-effort cache rebuild.
    try:
        _redis_set(_EMBED_KEY, _dump_embeddings(out))
    except Exception:
        pass
    return out


def upsert_record(record: StrategyRecord) -> bool:
    """Insert or update one strategy record. Writes:
      - Postgres strategy_records.jsonb (durable, source of truth)
      - Redis strategy:embeddings (derived cache, rebuildable)
      - Redis strategy:records (legacy cache, only during dual-write window)

    Returns True only if Postgres was updated successfully. Redis failures
    are logged but non-fatal — the embeddings can be rebuilt on next read.
    """
    problems = record.validate()
    if problems:
        _logger.warning(
            f"[StrategyStore] {record.id} upsert validation issues: {problems}"
        )

    record_dict = record.to_dict()
    ok_pg = _pg_upsert(record.id, record_dict)
    if not ok_pg:
        # If Postgres is down, fall back to legacy Redis-only path so
        # dev environments (no Supabase wiring) still function.
        _logger.warning(f"[StrategyStore] PG upsert failed for {record.id}; "
                        f"falling back to Redis-only legacy path")

    # Embedding cache (always rebuilt incrementally).
    embeddings = load_all_embeddings()
    embeddings[record.id] = generate_embedding(record)
    _redis_set(_EMBED_KEY, _dump_embeddings(embeddings))

    # Legacy records cache — only during the dual-write window, so a deploy
    # that finds Postgres mid-cutover can still read the old path.
    if _dual_write_enabled():
        legacy_records = load_all_records_redis_legacy()
        legacy_records[record.id] = record
        _redis_set(_RECORDS_KEY,
                   json.dumps({k: v.to_dict() for k, v in legacy_records.items()}))

    if ok_pg:
        _logger.info(f"[StrategyStore] Upserted {record.id} ({record.verdict.value})")
    return ok_pg


def upsert_many(records: list[StrategyRecord]) -> int:
    """Bulk upsert. Returns count successfully persisted to Postgres."""
    if not records:
        return 0
    n_ok = 0
    pg_payload = []
    for r in records:
        problems = r.validate()
        if problems:
            _logger.warning(f"[StrategyStore] {r.id} validation: {problems}")
        pg_payload.append({"id": r.id, "record": r.to_dict()})

    # One round-trip bulk upsert to Postgres.
    base, key = _sb_url_key()
    if base and key:
        url = f"{base}/rest/v1/strategy_records"
        headers = {
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        body = json.dumps(pg_payload).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
            n_ok = len(pg_payload)
        except Exception as e:
            _logger.warning(f"[StrategyStore] PG bulk upsert failed: {e}")
    else:
        # Dev fallback only
        for p in pg_payload:
            if _pg_upsert(p["id"], p["record"]):
                n_ok += 1

    # Always update the embeddings cache.
    embeddings = load_all_embeddings()
    for r in records:
        embeddings[r.id] = generate_embedding(r)
    _redis_set(_EMBED_KEY, _dump_embeddings(embeddings))

    if _dual_write_enabled():
        legacy_records = load_all_records_redis_legacy()
        legacy_embeddings = load_all_embeddings()
        for r in records:
            legacy_records[r.id] = r
            legacy_embeddings[r.id] = generate_embedding(r)
        _redis_set(_RECORDS_KEY,
                   json.dumps({k: v.to_dict() for k, v in legacy_records.items()}))

    meta = {
        "computed_at": time.time(),
        "count":       n_ok,
        "dims":        VECTOR_DIMS,
        "version":     "v2.0-pgvector-out,pg-in",
    }
    _redis_set(_META_KEY, json.dumps(meta))

    _logger.info(f"[StrategyStore] Bulk upserted {n_ok}/{len(records)} records "
                 f"(pg-durable + redis-embeddings cache)")
    return n_ok


def get_record(record_id: str) -> Optional[StrategyRecord]:
    return load_all_records().get(record_id)


def delete_record(record_id: str) -> bool:
    """Hard delete. Postgres first (source of truth), then Redis caches."""
    pg_ok = _pg_delete_id(record_id)
    # Best-effort cache cleanup — non-fatal if it fails; next upsert of the
    # same id will overwrite.
    records = load_all_records()
    embeds = load_all_embeddings()
    records.pop(record_id, None)
    embeds.pop(record_id, None)
    if _dual_write_enabled():
        _redis_set(_RECORDS_KEY,
                   json.dumps({k: v.to_dict() for k, v in records.items()}))
    _redis_set(_EMBED_KEY, _dump_embeddings(embeds))
    return pg_ok


def list_records(
    verdict: Optional[Verdict] = None,
    tag: Optional[str] = None,
    r_number_prefix: Optional[str] = None,
) -> list[StrategyRecord]:
    records = load_all_records().values()
    out = []
    for r in records:
        if verdict is not None and r.verdict != verdict:
            continue
        if tag is not None and tag not in r.tags:
            continue
        if r_number_prefix is not None:
            if not (r.r_number and r.r_number.startswith(r_number_prefix)):
                continue
        out.append(r)
    return out


def get_meta() -> dict:
    raw = _redis_get(_META_KEY)
    if not raw:
        # Cold-start fallback: derive meta from Postgres count.
        n = _pg_count()
        if n >= 0:
            return {"computed_at": None, "count": n, "dims": VECTOR_DIMS,
                    "version": "v2.0-pgvector-out,pg-in"}
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def age_seconds() -> Optional[float]:
    meta = get_meta()
    ts = meta.get("computed_at")
    if not ts:
        return None
    return time.time() - float(ts)


# ============================================================================
# Migration helper — one-time Postgres backfill from Redis
# ============================================================================

def load_all_records_redis_legacy() -> dict[str, StrategyRecord]:
    """Read the legacy Redis records cache WITHOUT touching Postgres. Used by
    the dual-write window and by `migrate_redis_to_postgres()` so we don't
    recursively call the Postgres primary while we're copy-migrating.
    """
    raw = _redis_get(_RECORDS_KEY)
    if not raw:
        return {}
    try:
        return {k: StrategyRecord.from_dict(v) for k, v in json.loads(raw).items()}
    except Exception:
        return {}


def migrate_redis_to_postgres() -> dict:
    """One-shot: copy every record currently in Redis → Postgres. Idempotent.

    Returns {redis_n, pg_n_before, pg_n_after, migrated_n}.
    Use at deploy time; safe to re-run (Postgres upserts on id conflict).
    """
    legacy = load_all_records_redis_legacy()
    pg_before = _pg_count()
    if not legacy:
        return {"redis_n": 0, "pg_n_before": pg_before, "pg_n_after": pg_before,
                "migrated_n": 0}
    records = list(legacy.values())
    n = upsert_many(records)
    pg_after = _pg_count()
    return {"redis_n": len(legacy), "pg_n_before": pg_before,
            "pg_n_after": pg_after, "migrated_n": n}
