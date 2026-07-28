"""
Entity/Decision store — the kernel's missing object, persisted (Seth, 2026-07-27).
==================================================================================

VDB space #5 (`docs/HIGH_DIM_ONTOLOGY.md` §5; design: `docs/ENTITY_DECISION_SPACE.md`). Mirrors the
`pgvector_store` contract: REST upsert + RPC read, best-effort, env-gated, NaN never enters a vector
column (I1 — unmeasured influence dims live as nulls in `meta.measured`, not as fabricated 0s).

WHY THIS EXISTS: everything else we store is the REFLECTION (asset/quality/price). S-81 proved
diffusing reflections carries nothing — **the signal to diffuse is the CHANGE**, and a Decision is
exactly a dated change event at a point in the field. `decision_source_term(as_of)` returns the
PIT-safe decayed push per asset, which is the correct `s` for `propagation.propagate()`.

DISCIPLINE (enforced here, not just documented):
  · provenance is MANDATORY — `record_decision` refuses a row without it (the DB CHECK backs it up).
  · `d` is the KNOWN-BY date, never the occurred date (PIT; a decision we learned late is late).
  · `lead_score` is EARNED via experiment E2 — this module never writes a default/assumed influence.
  · compliance: `direction` is a signed FIELD PUSH (+risk-on/−risk-off), never buy/sell language.
"""
from __future__ import annotations

import json
import logging
import math
import os
import urllib.request

_logger = logging.getLogger(__name__)

INFLUENCE_DIMS = (
    "capital_log", "breadth", "directionality", "persistence", "lead_score", "reach_attention",
    "reach_flow", "gov_power", "opacity", "activity_freq", "regime_sensitivity", "confidence",
)
_NDIM = len(INFLUENCE_DIMS)   # 12


def _sb() -> tuple[str, str]:
    return os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_KEY", "")


def _post(path: str, payload, headers_extra: dict | None = None, timeout: int = 10):
    url, key = _sb()
    if not url or not key:
        return None
    hdrs = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    hdrs.update(headers_extra or {})
    req = urllib.request.Request(f"{url}{path}", data=json.dumps(payload).encode(),
                                 headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else True


def influence_vector(coords: dict) -> tuple[list, dict]:
    """{dim: value|None} → (12-dim finite vector, measured-flags).

    pgvector rejects NaN, so an UNMEASURED dim is stored as 0.0 in `vec` but flagged False in
    `meta.measured` — the flag is the truth (I1). Similarity consumers must consult the flags;
    never read a 0 as "average influence". Returns the pair so callers can't lose the flags.
    """
    vec, measured = [], {}
    for d in INFLUENCE_DIMS:
        v = coords.get(d)
        ok = v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))
        measured[d] = bool(ok)
        vec.append(round(float(v), 6) if ok else 0.0)
    return vec, measured


def upsert_entity(entity_id: str, kind: str, coords: dict | None = None, *,
                  label: str | None = None, lead_score: float | None = None,
                  meta: dict | None = None) -> bool:
    """Upsert an influence node. `lead_score` stays None unless EARNED by experiment E2."""
    vec, measured = influence_vector(coords or {})
    row = {
        "entity_id": entity_id, "kind": kind, "label": label,
        "vec": "[" + ",".join(f"{x:.6g}" for x in vec) + "]",
        "lead_score": lead_score,
        "meta": {**(meta or {}), "measured": measured},
    }
    try:
        # _post returns None when creds are absent — that is a NO-OP, not a success.
        return _post("/rest/v1/entities?on_conflict=entity_id", [row],
                     {"Prefer": "resolution=merge-duplicates,return=minimal"}) is not None
    except Exception as e:
        _logger.warning(f"[entity_store] upsert_entity({entity_id}) failed: {e}")
        return False


def record_decision(entity_id: str, d: str, kind: str, *, direction: float, magnitude: float,
                    targets: list[str], provenance: dict, half_life_d: float = 14.0) -> bool:
    """Record a dated CHANGE event. REFUSES without provenance (anti-imposter, mirrors the DB CHECK).

    `d` MUST be the known-by date (PIT). `direction` is a signed field push, not a recommendation.
    """
    if not provenance:
        raise ValueError("provenance is mandatory — a decision without a source is not evidence")
    if not targets:
        raise ValueError("targets required — a decision with no target has no kernel edge")
    row = {"entity_id": entity_id, "d": d, "kind": kind, "direction": float(direction),
           "magnitude": float(magnitude), "targets": list(targets),
           "half_life_d": float(half_life_d), "provenance": provenance}
    try:
        return _post("/rest/v1/decisions", [row], {"Prefer": "return=minimal"}) is not None
    except Exception as e:
        _logger.warning(f"[entity_store] record_decision({entity_id},{d}) failed: {e}")
        return False


def source_term(as_of: str, lookback_days: int = 30) -> dict[str, float]:
    """PIT decayed decision push per asset at `as_of` → {symbol: s}. This is the `s` that
    `propagation.propagate()` diffuses — the CHANGE, not the level (S-81)."""
    try:
        rows = _post("/rest/v1/rpc/decision_source_term",
                     {"as_of": as_of, "lookback_days": int(lookback_days)})
        if not isinstance(rows, list):
            return {}
        return {r["symbol"]: float(r["s"]) for r in rows if r.get("s") is not None}
    except Exception as e:
        _logger.warning(f"[entity_store] source_term({as_of}) failed: {e}")
        return {}
