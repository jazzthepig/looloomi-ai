"""
Factor Discovery Router — CometCloud AI
========================================
LLM-driven factor hypothesis pipeline endpoints.

Flow:
  Railway detects weak pillar IC → writes cis:factor_discovery:needed
  Mac Mini polls GET /api/v1/factors/discovery/pending (every 30min before push)
  Mac Mini calls LM Studio → POST /internal/factor-hypotheses with Gemma4-26b output
  Dashboard reads GET /api/v1/factors/discovery → Factor Lab panel

Endpoints:
  GET  /api/v1/factors/discovery           — discovery state (pending + hypotheses)
  GET  /api/v1/factors/discovery/pending   — Mac Mini polls for queued requests (auth required)
  POST /internal/factor-hypotheses         — Mac Mini uploads Gemma4-26b results (auth required)
"""

import os
import time
import logging

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

_logger = logging.getLogger(__name__)
router  = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


# ── Schemas ────────────────────────────────────────────────────────────────────

class HypothesisItem(BaseModel):
    pillar:           str
    name:             str
    formula:          str
    regime_rationale: str
    confidence:       str   # HIGH | MEDIUM | LOW


class FactorHypothesesPayload(BaseModel):
    hypotheses:   list[HypothesisItem]
    model:        str = "gemma4-26b"
    generated_at: str | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/factors/discovery")
async def get_discovery_state():
    """
    Factor discovery state — consumed by dashboard Factor Lab panel and agent tools.

    Returns:
      hypotheses     — active LLM-generated hypotheses keyed by pillar
      pending        — current discovery request (if any)
      has_pending    — bool: a discovery request is awaiting Mac Mini
      has_hypotheses — bool: at least one pillar has generated hypotheses
    """
    from src.data.factors.discovery import get_active_hypotheses, get_pending_discovery
    hypotheses = get_active_hypotheses()
    pending    = get_pending_discovery()
    return {
        "hypotheses":     hypotheses,
        "pending":        pending,
        "has_pending":    bool(pending and pending.get("status") == "pending"),
        "has_hypotheses": bool(hypotheses),
        "ts":             time.time(),
    }


@router.get("/api/v1/factors/discovery/pending")
async def get_pending_for_mac_mini(x_internal_token: str = Header(None)):
    """
    Mac Mini cis_scheduler.py polls this before each push cycle.
    Returns the pending discovery request (with Gemma4-26b prompt), or null if none.
    Auth: X-Internal-Token
    """
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")

    from src.data.factors.discovery import get_pending_discovery, build_prompt, mark_discovery_processing
    pending = get_pending_discovery()
    if not pending or pending.get("status") != "pending":
        return {"pending": None, "prompt": None}

    # Build prompt and mark as picked up
    prompt = build_prompt(pending)
    mark_discovery_processing()

    return {
        "pending": pending,
        "prompt":  prompt,
    }


@router.post("/internal/factor-hypotheses")
async def receive_factor_hypotheses(
    payload: FactorHypothesesPayload,
    x_internal_token: str = Header(None),
):
    """
    Mac Mini POSTs Gemma4-26b factor hypotheses after completing LM Studio inference.
    Saves per-pillar hypotheses to Redis and clears the pending request.
    Auth: X-Internal-Token
    """
    if not _INTERNAL_TOKEN or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not payload.hypotheses:
        raise HTTPException(status_code=422, detail="hypotheses list is empty")

    # Group by pillar and save
    from src.data.factors.discovery import save_hypotheses
    pillar_map: dict[str, list] = {}
    for h in payload.hypotheses:
        p = h.pillar.upper()
        if p not in ("F", "M", "O", "S", "A"):
            _logger.warning(f"[FactorDiscovery] Invalid pillar in hypothesis: {p} — skipped")
            continue
        pillar_map.setdefault(p, []).append(h.model_dump())

    saved_pillars = []
    for pillar, hyps in pillar_map.items():
        ok = save_hypotheses(pillar, hyps)
        if ok:
            saved_pillars.append(pillar)

    _logger.info(
        f"[FactorDiscovery] Received {len(payload.hypotheses)} hypotheses "
        f"for pillars {saved_pillars} from {payload.model}"
    )

    return {
        "ok":           bool(saved_pillars),
        "saved_pillars": saved_pillars,
        "count":        len(payload.hypotheses),
        "model":        payload.model,
        "ts":           time.time(),
    }
