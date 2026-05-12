"""
Vector Embedding Store — CometCloud AI
=======================================
Redis-backed persistence for 18-dim asset embeddings.
Upserted after every CIS universe compute; read by the similarity/cluster endpoints.

Keys:
  cis:embeddings          — JSON {symbol: [18 floats]}         TTL: 4h
  cis:regime_embedding    — JSON [12 floats] macro fingerprint  TTL: 4h
  cis:embedding_meta      — JSON {computed_at, asset_count, regime, version}
"""

import json
import logging
import time
from typing import Optional

_logger = logging.getLogger(__name__)

_EMBED_KEY  = "cis:embeddings"
_REGIME_KEY = "cis:regime_embedding"
_META_KEY   = "cis:embedding_meta"
_TTL        = 14_400  # 4 hours


# ── Redis helpers (shared pattern from data_layer.py) ────────────────────────

def _redis_get(key: str) -> Optional[str]:
    """Synchronous Upstash REST GET."""
    import os, urllib.request
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
        _logger.debug(f"[VectorStore] Redis GET {key} failed: {e}")
        return None


def _redis_set(key: str, value: str, ttl: int = _TTL) -> bool:
    """Synchronous Upstash REST SET EX."""
    import os, urllib.request
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
        _logger.warning(f"[VectorStore] Redis SET {key} failed: {e}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def save_embeddings(
    embeddings: dict[str, list[float]],
    macro_regime: str = "Neutral",
    regime_vec: list[float] | None = None,
) -> bool:
    """
    Persist asset embeddings and optional regime fingerprint to Redis.
    Called after every CIS universe compute.

    Parameters
    ----------
    embeddings    : {symbol: [18 floats]}
    macro_regime  : current regime string (stored in meta)
    regime_vec    : 12-dim regime fingerprint (optional)

    Returns True if write succeeded.
    """
    ok1 = _redis_set(_EMBED_KEY, json.dumps(embeddings))

    if regime_vec is not None:
        _redis_set(_REGIME_KEY, json.dumps(regime_vec))

    meta = {
        "computed_at": time.time(),
        "asset_count": len(embeddings),
        "regime": macro_regime,
        "version": "v4.3",
        "dims": 18,
    }
    ok2 = _redis_set(_META_KEY, json.dumps(meta))

    if ok1:
        _logger.info(f"[VectorStore] Saved {len(embeddings)} embeddings (regime={macro_regime})")
    return ok1 and ok2


def load_embeddings() -> dict[str, list[float]]:
    """
    Load asset embeddings from Redis. Returns {} on miss/error.
    """
    raw = _redis_get(_EMBED_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception as e:
        _logger.warning(f"[VectorStore] Failed to parse embeddings: {e}")
        return {}


def load_regime_embedding() -> list[float] | None:
    """Load 12-dim regime fingerprint from Redis."""
    raw = _redis_get(_REGIME_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def load_meta() -> dict:
    """Load embedding metadata (computed_at, regime, asset_count)."""
    raw = _redis_get(_META_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def embedding_age_seconds() -> float | None:
    """Return seconds since embeddings were last computed, or None if no metadata."""
    meta = load_meta()
    ts = meta.get("computed_at")
    if not ts:
        return None
    return time.time() - float(ts)
