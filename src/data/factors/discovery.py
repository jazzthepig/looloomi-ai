"""
Factor Discovery Engine — CometCloud AI
========================================
Detects degraded pillar IC and queues Gemma4-26b discovery requests for Mac Mini.

Flow:
  _auto_mine_ic() → check_and_queue_discovery() → Redis cis:factor_discovery:needed
  Mac Mini cis_scheduler.py polls /api/v1/factors/discovery/pending (every 30min)
  → calls Gemma4-26b via LM Studio → POSTs to /internal/factor-hypotheses
  → save_hypotheses() → Redis cis:factor_hypotheses
  → GET /api/v1/factors/discovery → dashboard Factor Lab

Redis keys:
  cis:factor_discovery:needed    — pending request: {pillars, ic_history, regime, queued_at, status}
  cis:factor_hypotheses          — active hypotheses per pillar: {F: {hypotheses, generated_at}, ...}

Trigger rule (§F-SEL):
  |r| < 0.05 for ≥ 3 consecutive mine runs → queue Gemma4-26b discovery
  Suppressed if a request was already queued within the last 2h.
"""

import json
import time
import logging
from typing import Optional

_logger = logging.getLogger(__name__)

_KEY_NEEDED     = "cis:factor_discovery:needed"
_KEY_HYPOTHESES = "cis:factor_hypotheses"
_TTL_NEEDED     = 3600 * 6    # 6h — Mac Mini should pick up within 30min
_TTL_HYPOTHESES = 86400 * 14  # 14 days

_IC_WEAK_THRESHOLD = 0.05
_IC_CONSEC_TRIGGER = 3         # consecutive weak readings to trigger discovery
_REQUEUE_SUPPRESS  = 3600 * 2  # don't re-queue within 2h


def _redis_get(key: str) -> Optional[str]:
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
            return json.loads(r.read()).get("result")
    except Exception as e:
        _logger.debug(f"[FactorDiscovery] GET failed: {e}")
        return None


def _redis_set(key: str, value: str, ttl: int) -> bool:
    import os, urllib.request
    url   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return False
    try:
        req = urllib.request.Request(
            f"{url}/set/{key}?EX={ttl}",
            data=value.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        return True
    except Exception as e:
        _logger.warning(f"[FactorDiscovery] SET failed: {e}")
        return False


def check_and_queue_discovery(factor_performance: dict, regime: str) -> list:
    """
    Inspect factor_performance for pillars with ≥ _IC_CONSEC_TRIGGER consecutive
    mine runs below the IC weak threshold. If found, write a discovery request
    to Redis so Mac Mini's cis_scheduler.py can pick it up and invoke Gemma4-26b.

    Args:
        factor_performance: result from performance.load() after update_from_pillar_fitness()
        regime: current macro regime string (e.g., "TIGHTENING")

    Returns:
        list of pillar IDs queued for discovery (empty if no weak pillars or suppressed)
    """
    # Aggregate per-pillar: max consecutive weak readings + rolling IC history
    pillar_consec: dict[str, int] = {}
    pillar_history: dict[str, list] = {}

    for key, val in factor_performance.items():
        if key == "_meta" or not isinstance(val, dict):
            continue
        pillar = (val.get("pillar") or "").upper()
        if pillar not in ("F", "M", "O", "S", "A"):
            continue
        rolling = val.get("rolling_7d", [])
        if not rolling:
            continue

        # Count tail-consecutive weak readings
        consec = 0
        for r in reversed(rolling):
            if abs(r) <= _IC_WEAK_THRESHOLD:
                consec += 1
            else:
                break

        pillar_consec[pillar] = max(pillar_consec.get(pillar, 0), consec)
        pillar_history.setdefault(pillar, [])
        pillar_history[pillar] = (pillar_history[pillar] + rolling)[-7:]

    weak_pillars = [
        p for p, c in pillar_consec.items()
        if c >= _IC_CONSEC_TRIGGER
    ]
    if not weak_pillars:
        return []

    # Suppress re-queue if a request is already pending
    existing = _redis_get(_KEY_NEEDED)
    if existing:
        try:
            pending = json.loads(existing)
            age = time.time() - pending.get("queued_at", 0)
            if age < _REQUEUE_SUPPRESS:
                _logger.info(
                    f"[FactorDiscovery] Suppressed re-queue ({age/60:.0f}min since last) — "
                    f"pillars: {weak_pillars}"
                )
                return []
        except Exception:
            pass

    request = {
        "pillars":    weak_pillars,
        "ic_history": {p: pillar_history.get(p, []) for p in weak_pillars},
        "regime":     regime,
        "queued_at":  time.time(),
        "status":     "pending",
    }
    _redis_set(_KEY_NEEDED, json.dumps(request), ttl=_TTL_NEEDED)
    _logger.info(f"[FactorDiscovery] Queued discovery — pillars: {weak_pillars} | regime: {regime}")
    return weak_pillars


def save_hypotheses(pillar: str, hypotheses: list) -> bool:
    """Persist LLM-generated hypotheses from Mac Mini into Redis."""
    existing = _redis_get(_KEY_HYPOTHESES)
    store: dict = {}
    if existing:
        try:
            store = json.loads(existing)
        except Exception:
            pass
    store[pillar.upper()] = {
        "hypotheses":   hypotheses,
        "generated_at": time.time(),
        "status":       "active",
    }
    return _redis_set(_KEY_HYPOTHESES, json.dumps(store), ttl=_TTL_HYPOTHESES)


def get_active_hypotheses() -> dict:
    """Read current factor hypotheses — consumed by dashboard Factor Lab and agents."""
    raw = _redis_get(_KEY_HYPOTHESES)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def get_pending_discovery() -> Optional[dict]:
    """Read pending discovery request. Mac Mini cis_scheduler.py polls this."""
    raw = _redis_get(_KEY_NEEDED)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def mark_discovery_processing() -> bool:
    """
    Transition status pending → processing.
    Called after Mac Mini picks up the request, before calling LM Studio.
    """
    existing = _redis_get(_KEY_NEEDED)
    if not existing:
        return False
    try:
        pending = json.loads(existing)
        pending["status"] = "processing"
        pending["picked_up_at"] = time.time()
        return _redis_set(_KEY_NEEDED, json.dumps(pending), ttl=3600)
    except Exception:
        return False


def build_prompt(pending: dict) -> str:
    """
    Build the Gemma4-26b prompt string for Mac Mini to submit to LM Studio.
    Called by Mac Mini's discovery polling code (documented in MINIMAX_SYNC.md §8).
    Returns a ready-to-send prompt string.
    """
    pillars   = pending.get("pillars", [])
    regime    = pending.get("regime", "Unknown")
    ic_hist   = pending.get("ic_history", {})

    pillar_details = []
    for p in pillars:
        hist = ic_hist.get(p, [])
        hist_str = ", ".join(f"{r:.3f}" for r in hist) if hist else "no history"
        pillar_details.append(f"  - Pillar {p}: IC history = [{hist_str}]")

    pillar_block = "\n".join(pillar_details)

    return f"""You are a quantitative factor analyst for CometCloud AI, a DeFi/crypto scoring platform.

CONTEXT:
- Current macro regime: {regime}
- Pillars with degraded IC (|r| < 0.05 for 3+ consecutive mine runs):
{pillar_block}

Available data inputs (use only these):
  price_return_7d, price_return_30d, volume_24h, market_cap, tvl, tvl_growth_30d,
  protocol_fees_7d, staking_yield, fear_greed_index, btc_dominance, vix,
  funding_rate, open_interest_mcap_ratio, ath_drawdown, developer_commits_30d

TASK:
For each degraded pillar, propose 2 alternative factor hypotheses that might better
predict 7-14 day forward returns in a {regime} regime. Keep formulas concise.

Respond ONLY with a valid JSON array — no markdown, no commentary:
[
  {{
    "pillar": "F",
    "name": "TVL Momentum Adjusted",
    "formula": "tvl_growth_30d / max(market_cap / tvl, 1)",
    "regime_rationale": "In {regime}, protocol cash flow matters more than raw TVL",
    "confidence": "HIGH"
  }}
]"""
