"""
Strategy Vector Store — Redis-backed JSON persistence
======================================================

Mirrors `src/data/vector/store.py` exactly. Each upsert round-trips via
`StrategyRecord.to_dict()` ↔ `StrategyRecord.from_dict()`.

Keys (Upstash Redis):
  strategy:records    — JSON dict {id: record_dict}       TTL: 24h
  strategy:embeddings — JSON dict {id: [30 floats]}       TTL: 24h
  strategy:meta       — JSON {computed_at, count, version}

The split lets us rebuild the embedding cache from the records cache without
touching the canonical strategy records (records → JSON, embeddings → derived).

No external vector DB needed at strategy-record scale (typical 30–200 records).
All similarity search happens in-memory via `strategy_embedder.find_similar()`.

PIT discipline: every write to `strategy:records` is a full replace (not a
diff). Records are not blobs — they're the canonical contract. If a field
needs to change, re-upsert the whole record. There is no concept of "patch
one field." This eliminates partial-update races.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from .strategy_schema import StrategyRecord, Verdict
from .strategy_embedder import generate_embedding, VECTOR_DIMS

_logger = logging.getLogger(__name__)

_RECORDS_KEY   = "strategy:records"
_EMBED_KEY     = "strategy:embeddings"
_META_KEY      = "strategy:meta"
_TTL           = 86_400  # 24 hours


# ---------------------------------------------------------------------------
# Redis helpers (shared pattern from src/data/vector/store.py)
# ---------------------------------------------------------------------------

def _redis_get(key: str) -> Optional[str]:
    import os
    import urllib.request
    url   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
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
    import os
    import urllib.request
    url   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
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


# ---------------------------------------------------------------------------
# I1 NaN↔null — v-honest embeddings carry NaN for unmeasured dims; bare json.dumps(NaN)
# emits an invalid `NaN` token that Upstash/JS JSON.parse rejects. Serialize NaN→null, restore
# null→NaN on load so cosine's NaN-skip sees unmeasured dims.
# ---------------------------------------------------------------------------

def _nan_to_null(vec: list) -> list:
    return [None if isinstance(v, float) and v != v else v for v in vec]


def _null_to_nan(vec: list) -> list[float]:
    return [float("nan") if v is None else float(v) for v in vec]


def _dump_embeddings(embeds: dict) -> str:
    return json.dumps({k: _nan_to_null(v) for k, v in embeds.items()}, allow_nan=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all_records() -> dict[str, StrategyRecord]:
    """Load every strategy record from Redis. Returns {} on miss/error."""
    raw = _redis_get(_RECORDS_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: StrategyRecord.from_dict(v) for k, v in data.items()}
    except Exception as e:
        _logger.warning(f"[StrategyStore] Failed to parse records: {e}")
        return {}


def load_all_embeddings() -> dict[str, list[float]]:
    """Load pre-computed 30-dim embeddings. Returns {} on miss/error."""
    raw = _redis_get(_EMBED_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        # Sanity: drop any vector with wrong dim; restore JSON null → NaN (unmeasured dim, I1)
        return {k: _null_to_nan(v) for k, v in data.items() if len(v) == VECTOR_DIMS}
    except Exception as e:
        _logger.warning(f"[StrategyStore] Failed to parse embeddings: {e}")
        return {}


def upsert_record(record: StrategyRecord) -> bool:
    """Insert or update one strategy record. Validates first; logs warnings.

    Side-effect: re-generates and re-stores the embedding for the record too.
    Both writes are best-effort; if either fails, the records and embeddings
    caches can drift and a future `_recompute_embeddings()` will reconcile.
    """
    problems = record.validate()
    if problems:
        _logger.warning(
            f"[StrategyStore] {record.id} upsert validation issues: {problems}"
        )

    # Load current state, mutate, save (full replace — no partial updates)
    records = load_all_records()
    records[record.id] = record
    ok1 = _redis_set(_RECORDS_KEY, json.dumps({k: v.to_dict() for k, v in records.items()}))

    # Same for embeddings — recompute the one new entry, keep the rest
    embeddings = load_all_embeddings()
    embeddings[record.id] = generate_embedding(record)
    ok2 = _redis_set(_EMBED_KEY, _dump_embeddings(embeddings))

    if ok1 and ok2:
        _logger.info(f"[StrategyStore] Upserted {record.id} ({record.verdict.value})")
    return ok1 and ok2


def upsert_many(records: list[StrategyRecord]) -> int:
    """Bulk upsert. Returns count successfully written."""
    n_ok = 0
    existing_records = load_all_records()
    existing_embeds  = load_all_embeddings()
    for r in records:
        problems = r.validate()
        if problems:
            _logger.warning(f"[StrategyStore] {r.id} validation: {problems}")
        existing_records[r.id] = r
        existing_embeds[r.id]  = generate_embedding(r)
        n_ok += 1

    ok1 = _redis_set(
        _RECORDS_KEY,
        json.dumps({k: v.to_dict() for k, v in existing_records.items()}),
    )
    ok2 = _redis_set(_EMBED_KEY, _dump_embeddings(existing_embeds))

    # Meta
    meta = {
        "computed_at": time.time(),
        "count":       len(existing_records),
        "dims":        VECTOR_DIMS,
        "version":     "v1.0",
    }
    _redis_set(_META_KEY, json.dumps(meta))

    if not (ok1 and ok2):
        return 0
    _logger.info(f"[StrategyStore] Bulk upserted {n_ok} records (total={len(existing_records)})")
    return n_ok


def get_record(record_id: str) -> Optional[StrategyRecord]:
    records = load_all_records()
    return records.get(record_id)


def delete_record(record_id: str) -> bool:
    """Hard delete. Idempotent."""
    records = load_all_records()
    embeds  = load_all_embeddings()
    if record_id not in records:
        return True  # nothing to do
    records.pop(record_id, None)
    embeds.pop(record_id, None)
    ok1 = _redis_set(_RECORDS_KEY, json.dumps({k: v.to_dict() for k, v in records.items()}))
    ok2 = _redis_set(_EMBED_KEY, _dump_embeddings(embeds))
    return ok1 and ok2


def list_records(
    verdict: Optional[Verdict] = None,
    tag: Optional[str] = None,
    r_number_prefix: Optional[str] = None,
) -> list[StrategyRecord]:
    """In-memory filter over the loaded records cache. Cheap at our scale."""
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
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def age_seconds() -> Optional[float]:
    """Seconds since last upsert, or None if no meta."""
    meta = get_meta()
    ts = meta.get("computed_at")
    if not ts:
        return None
    return time.time() - float(ts)
