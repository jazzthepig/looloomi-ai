"""
Agent Task Queue — ROADMAP_A2A Phase 2.3
=========================================
Async task delegation for AI agents. Agents submit analysis tasks, get a task_id
back immediately (202), then poll or stream for results.

Endpoints:
  POST /api/v1/agent/tasks             — submit task, returns 202 + task_id
  GET  /api/v1/agent/tasks/{task_id}   — poll status + result
  GET  /api/v1/agent/tasks             — list recent tasks (auth required)

Task types:
  portfolio_analysis  — CIS-based allocation given constraints
  cis_snapshot        — filtered/sorted CIS universe for agent context
  regime_briefing     — macro regime + signal implications
"""

import uuid
import asyncio
import logging
import os
import json as _json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)

router = APIRouter()

# ── Upstash Redis (shared with cis_provider and data_layer) ─────────────────
import httpx as _httpx

_UPSTASH_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
_TASK_TTL      = 3600   # 1h — completed tasks survive Railway restarts

async def _redis_set(key: str, val: dict, ttl: int = _TASK_TTL) -> bool:
    if not _UPSTASH_URL:
        return False
    try:
        async with _httpx.AsyncClient(timeout=5) as cl:
            await cl.post(
                f"{_UPSTASH_URL}/set/{key}",
                headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
                params={"ex": ttl},
                json=val,
            )
        return True
    except Exception as e:
        _logger.warning(f"[tasks] Redis SET {key} failed: {e}")
        return False

async def _redis_get(key: str) -> Optional[dict]:
    if not _UPSTASH_URL:
        return None
    try:
        async with _httpx.AsyncClient(timeout=5) as cl:
            r = await cl.get(
                f"{_UPSTASH_URL}/get/{key}",
                headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
            )
            if r.status_code == 200:
                raw = r.json().get("result")
                return _json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        _logger.warning(f"[tasks] Redis GET {key} failed: {e}")
    return None

# In-memory fallback for active tasks (hot path, zero latency)
_active_tasks: Dict[str, dict] = {}
_MAX_ACTIVE    = 50  # evict oldest when over limit

# Concurrency guard — max 5 tasks running simultaneously on Railway
_task_semaphore = asyncio.Semaphore(5)


# ── Schema ───────────────────────────────────────────────────────────────────

TASK_TYPES = {"portfolio_analysis", "cis_snapshot", "regime_briefing"}

class TaskRequest(BaseModel):
    type: str = Field(..., description=f"Task type: {', '.join(sorted(TASK_TYPES))}")
    params: Dict[str, Any] = Field(default_factory=dict, description="Task-specific parameters")
    priority: str = Field("normal", description="normal | high")

class TaskStatus(BaseModel):
    task_id: str
    type: str
    status: str         # pending | working | completed | failed
    created_at: str
    updated_at: str
    params: dict
    result: Optional[dict] = None
    error: Optional[str] = None
    poll: str
    compliance_note: str = (
        "All CIS signals use positioning-only language (OUTPERFORM/NEUTRAL/UNDERPERFORM). "
        "Not investment advice. CometCloud AI — Hong Kong SFC compliance."
    )


# ── Task storage helpers ─────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _make_task(task_id: str, task_type: str, params: dict) -> dict:
    return {
        "task_id":    task_id,
        "type":       task_type,
        "status":     "pending",
        "created_at": _now(),
        "updated_at": _now(),
        "params":     params,
        "result":     None,
        "error":      None,
        "poll":       f"/api/v1/agent/tasks/{task_id}",
    }

async def _save_task(task: dict):
    """Persist to both in-memory dict and Redis."""
    tid = task["task_id"]
    # Evict oldest if at cap
    if len(_active_tasks) >= _MAX_ACTIVE:
        oldest = sorted(_active_tasks, key=lambda k: _active_tasks[k]["created_at"])[0]
        _active_tasks.pop(oldest, None)
    _active_tasks[tid] = task
    ok = await _redis_set(f"task:{tid}", task)
    if not ok and _UPSTASH_URL:
        _logger.warning(f"[tasks] Redis persist failed for {tid} — task is in-memory only (lost on restart)")

async def _load_task(task_id: str) -> Optional[dict]:
    """Hot-path: in-memory first, Redis fallback."""
    if task_id in _active_tasks:
        return _active_tasks[task_id]
    return await _redis_get(f"task:{task_id}")

async def _update_task(task_id: str, **kwargs):
    """Patch task fields and persist."""
    task = await _load_task(task_id)
    if task is None:
        return
    task.update(kwargs)
    task["updated_at"] = _now()
    await _save_task(task)


# ── Task executors ───────────────────────────────────────────────────────────

async def _exec_portfolio_analysis(task_id: str, params: dict):
    """
    CIS-based portfolio allocation given investor constraints.
    Returns ranked assets with suggested weights, regime context, compliance signals.
    """
    try:
        from src.data.cis.cis_provider import calculate_cis_universe
        from src.data.market.data_layer import get_macro_pulse

        target_return   = params.get("target_return", 0.12)
        max_drawdown    = params.get("max_drawdown", 0.15)
        asset_classes   = params.get("asset_classes", [])  # [] = all
        min_cis         = params.get("min_cis", 55)
        max_positions   = int(params.get("max_positions", 10))
        horizon         = params.get("horizon", "6m")

        # Fetch live data
        universe_data, macro_pulse = await asyncio.gather(
            calculate_cis_universe(),
            get_macro_pulse(),
            return_exceptions=True,
        )

        if isinstance(universe_data, Exception):
            raise RuntimeError(f"CIS universe fetch failed: {universe_data}")

        assets = universe_data.get("assets", []) or universe_data.get("universe", [])
        regime = (
            macro_pulse.get("macro_regime", "Unknown")
            if not isinstance(macro_pulse, Exception) else "Unknown"
        )

        # Filter
        candidates = []
        for a in assets:
            score = a.get("cis_score") or a.get("score", 0)
            ac    = a.get("asset_class", "")
            if score < min_cis:
                continue
            if asset_classes and ac not in asset_classes:
                continue
            candidates.append(a)

        # Sort by LAS (execution-adjusted score) then CIS
        candidates.sort(
            key=lambda x: (-(x.get("las") or x.get("cis_score") or x.get("score", 0))),
        )

        # Build allocation — equal-weight the top N, scaled by LAS confidence
        selected = candidates[:max_positions]
        total_las = sum(
            (a.get("las") or a.get("cis_score") or a.get("score", 0))
            for a in selected
        )

        allocation = []
        for a in selected:
            las   = a.get("las") or a.get("cis_score") or a.get("score", 0)
            score = a.get("cis_score") or a.get("score", 0)
            grade = a.get("grade", "?")
            sig   = a.get("signal", "NEUTRAL")
            w     = round((las / total_las) if total_las > 0 else 1 / max(len(selected), 1), 4)
            allocation.append({
                "symbol":         a.get("symbol") or a.get("asset_id"),
                "name":           a.get("name"),
                "asset_class":    a.get("asset_class"),
                "cis_score":      round(score, 1),
                "grade":          grade,
                "signal":         sig,      # positioning language only — OUTPERFORM etc.
                "las":            round(las, 1),
                "suggested_weight": w,
                "confidence":     a.get("confidence"),
                "data_tier":      a.get("data_tier"),
            })

        result = {
            "macro_regime":      regime,
            "horizon":           horizon,
            "constraints": {
                "target_return":  target_return,
                "max_drawdown":   max_drawdown,
                "min_cis":        min_cis,
                "max_positions":  max_positions,
                "asset_classes":  asset_classes or "all",
            },
            "candidates_found":  len(candidates),
            "allocation":        allocation,
            "compliance_note": (
                "All signals are positioning-only (STRONG OUTPERFORM/OUTPERFORM/NEUTRAL/"
                "UNDERPERFORM/UNDERWEIGHT). Not investment advice. "
                "CometCloud AI — Hong Kong SFC compliance."
            ),
        }
        await _update_task(task_id, status="completed", result=result)

    except Exception as e:
        _logger.error(f"[tasks] portfolio_analysis {task_id} failed: {e}", exc_info=True)
        await _update_task(task_id, status="failed", error=str(e))


async def _exec_cis_snapshot(task_id: str, params: dict):
    """
    Filtered, sorted CIS universe snapshot.
    Useful for embedding into agent context windows — compact and structured.
    """
    try:
        from src.data.cis.cis_provider import calculate_cis_universe

        asset_classes = params.get("asset_classes", [])
        min_grade     = params.get("min_grade", "")   # "B", "B+", "A", "A+"
        limit         = int(params.get("limit", 30))

        _GRADE_ORDER = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
        min_grade_val = _GRADE_ORDER.get(min_grade, 0)

        universe_data = await calculate_cis_universe()
        assets = universe_data.get("assets", []) or universe_data.get("universe", [])

        filtered = []
        for a in assets:
            grade = a.get("grade", "F")
            if _GRADE_ORDER.get(grade, 0) < min_grade_val:
                continue
            ac = a.get("asset_class", "")
            if asset_classes and ac not in asset_classes:
                continue
            filtered.append(a)

        filtered.sort(
            key=lambda x: -(x.get("cis_score") or x.get("score", 0))
        )
        filtered = filtered[:limit]

        compact = [
            {
                "symbol":      a.get("symbol") or a.get("asset_id"),
                "name":        a.get("name"),
                "class":       a.get("asset_class"),
                "cis":         round(a.get("cis_score") or a.get("score", 0), 1),
                "grade":       a.get("grade"),
                "signal":      a.get("signal"),
                "las":         round(a.get("las", 0) or 0, 1),
                "tier":        a.get("data_tier"),
                "pillars":     a.get("pillars"),
            }
            for a in filtered
        ]

        result = {
            "source":           universe_data.get("source"),
            "regime":           universe_data.get("macro_regime"),
            "total_assets":     len(assets),
            "filtered_assets":  len(filtered),
            "filters": {
                "asset_classes": asset_classes or "all",
                "min_grade":     min_grade or "none",
                "limit":         limit,
            },
            "assets":           compact,
        }
        await _update_task(task_id, status="completed", result=result)

    except Exception as e:
        _logger.error(f"[tasks] cis_snapshot {task_id} failed: {e}", exc_info=True)
        await _update_task(task_id, status="failed", error=str(e))


async def _exec_regime_briefing(task_id: str, params: dict):
    """
    Current macro regime + CIS signal implications.
    Depth: 'summary' (compact) | 'full' (pillar breakdown + sector rotation)
    """
    try:
        from src.data.market.data_layer import get_macro_pulse, get_fear_greed
        from src.data.cis.cis_provider import calculate_cis_universe

        depth = params.get("depth", "summary")

        macro_pulse, fng_data = await asyncio.gather(
            get_macro_pulse(),
            get_fear_greed(),
            return_exceptions=True,
        )

        regime  = macro_pulse.get("macro_regime", "Unknown") if not isinstance(macro_pulse, Exception) else "Unknown"
        btc     = macro_pulse.get("btc_price") if not isinstance(macro_pulse, Exception) else None
        fng     = macro_pulse.get("fear_greed_index") if not isinstance(macro_pulse, Exception) else None
        fng_cls = macro_pulse.get("fear_greed_label") if not isinstance(macro_pulse, Exception) else None
        dom     = macro_pulse.get("btc_dominance") if not isinstance(macro_pulse, Exception) else None

        _REGIME_SIGNALS = {
            "Goldilocks":  {"bias": "STRONG OUTPERFORM", "note": "Balanced growth, momentum rewarded. All asset classes positioned favorably."},
            "Risk-On":     {"bias": "OUTPERFORM",        "note": "High momentum assets outperform. DeFi and L2 positioned well."},
            "Easing":      {"bias": "OUTPERFORM",        "note": "Liquidity expanding. Alpha-generating assets favored."},
            "Neutral":     {"bias": "NEUTRAL",           "note": "Range-bound market. Fundamentals dominate. Selective positioning."},
            "Tightening":  {"bias": "NEUTRAL",           "note": "Liquidity withdrawal. Fundamentals dominate. High-quality assets only."},
            "Risk-Off":    {"bias": "UNDERPERFORM",      "note": "Broad risk reduction. Fundamentals and risk-adjusted scores critical."},
            "Stagflation": {"bias": "UNDERPERFORM",      "note": "Macro stress. Defensive positioning. RWA and commodity-correlated assets."},
        }
        regime_ctx = _REGIME_SIGNALS.get(regime, {"bias": "NEUTRAL", "note": "Regime undetermined."})

        result: dict = {
            "macro_regime":         regime,
            "regime_signal":        regime_ctx["bias"],
            "regime_note":          regime_ctx["note"],
            "btc_price_usd":        btc,
            "fear_greed_value":     fng,
            "fear_greed_class":     fng_cls,
            "btc_dominance_pct":    dom,
        }

        if depth == "full":
            universe_data = await calculate_cis_universe()
            assets = universe_data.get("assets", []) or universe_data.get("universe", [])

            # Sector rotation: avg CIS per class
            class_scores: Dict[str, list] = {}
            for a in assets:
                ac  = a.get("asset_class", "Unknown")
                cis = a.get("cis_score") or a.get("score", 0) or 0
                class_scores.setdefault(ac, []).append(cis)

            sector_rotation = {
                ac: round(sum(scores) / len(scores), 1)
                for ac, scores in class_scores.items()
                if scores
            }
            sector_rotation = dict(sorted(sector_rotation.items(), key=lambda x: -x[1]))

            # Top opportunities (grade B+ or above)
            top = [
                {
                    "symbol":  a.get("symbol") or a.get("asset_id"),
                    "class":   a.get("asset_class"),
                    "cis":     round(a.get("cis_score") or a.get("score", 0), 1),
                    "grade":   a.get("grade"),
                    "signal":  a.get("signal"),
                }
                for a in assets
                if (a.get("cis_score") or a.get("score", 0)) >= 65
            ]
            top.sort(key=lambda x: -x["cis"])

            result["sector_rotation"]   = sector_rotation
            result["top_opportunities"] = top[:10]
            result["total_assets"]      = len(assets)

        result["compliance_note"] = (
            "All signals use positioning-only language per Hong Kong SFC compliance. "
            "Not investment advice."
        )
        await _update_task(task_id, status="completed", result=result)

    except Exception as e:
        _logger.error(f"[tasks] regime_briefing {task_id} failed: {e}", exc_info=True)
        await _update_task(task_id, status="failed", error=str(e))


# ── Dispatch table ────────────────────────────────────────────────────────────

_EXECUTORS = {
    "portfolio_analysis": _exec_portfolio_analysis,
    "cis_snapshot":       _exec_cis_snapshot,
    "regime_briefing":    _exec_regime_briefing,
}


async def _run_task(task_id: str, task_type: str, params: dict):
    """Background worker: acquire semaphore, mark working, execute, persist result."""
    try:
        async with _task_semaphore:
            await _update_task(task_id, status="working")
            executor = _EXECUTORS.get(task_type)
            if executor is None:
                await _update_task(task_id, status="failed", error=f"Unknown task type: {task_type}")
                return
            await executor(task_id, params)
    except Exception as e:
        # Top-level safety net — prevents task staying "pending" forever if semaphore
        # or _update_task itself throws (e.g., Redis race on startup)
        _logger.error(f"[tasks] _run_task outer failure for {task_id}: {e}", exc_info=True)
        try:
            await _update_task(task_id, status="failed", error=f"Internal error: {e}")
        except Exception:
            pass  # at this point in-memory update already failed, nothing more to do


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/v1/agent/tasks", status_code=202)
async def submit_task(req: TaskRequest):
    """
    Submit an async analysis task. Returns immediately with task_id + poll URL.

    Task types:
    - portfolio_analysis: CIS-based portfolio allocation
      params: target_return, max_drawdown, asset_classes, min_cis, max_positions, horizon
    - cis_snapshot: filtered CIS universe for agent context
      params: asset_classes, min_grade, limit
    - regime_briefing: macro regime + signal implications
      params: depth ("summary"|"full")

    Compliance: all signals use positioning-only language per HK SFC requirements.
    """
    if req.type not in TASK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown task type '{req.type}'. Valid: {', '.join(sorted(TASK_TYPES))}",
        )

    task_id = uuid.uuid4().hex
    task    = _make_task(task_id, req.type, req.params)
    await _save_task(task)

    # Fire-and-forget background execution
    asyncio.create_task(_run_task(task_id, req.type, req.params))

    return {
        "task_id": task_id,
        "type":    req.type,
        "status":  "pending",
        "poll":    f"/api/v1/agent/tasks/{task_id}",
        "stream":  f"/api/v1/agent/tasks/{task_id}/stream",  # Phase 2.5
        "created_at": task["created_at"],
        "compliance_note": (
            "CometCloud AI uses positioning-only language (OUTPERFORM/NEUTRAL/UNDERPERFORM). "
            "Not investment advice."
        ),
    }


@router.get("/api/v1/agent/tasks/{task_id}")
async def get_task(task_id: str):
    """
    Poll task status and result.

    Status lifecycle: pending → working → completed | failed
    Completed tasks are retained for 1 hour.
    """
    task = await _load_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_id}' not found. Tasks expire after 1 hour.",
        )
    return task


@router.get("/api/v1/agent/tasks")
async def list_tasks(
    limit: int = 20,
    x_internal_token: Optional[str] = Header(None),
):
    """
    List recent in-memory tasks. Internal use only (requires X-Internal-Token).
    """
    _internal_token = os.getenv("INTERNAL_TOKEN", "")
    if not _internal_token or x_internal_token != _internal_token:
        raise HTTPException(status_code=401, detail="Internal token required")

    tasks = sorted(
        _active_tasks.values(),
        key=lambda t: t.get("created_at", ""),
        reverse=True,
    )[:limit]

    return {
        "active_tasks": len(_active_tasks),
        "tasks": [
            {
                "task_id":    t["task_id"],
                "type":       t["type"],
                "status":     t["status"],
                "created_at": t["created_at"],
                "updated_at": t["updated_at"],
                "poll":       t["poll"],
            }
            for t in tasks
        ],
    }


# ── Analytics: Pillar Fitness — Simons Upgrade P0.3 ──────────────────────────

@router.get("/api/v1/analytics/pillar-fitness")
async def get_pillar_fitness(response: Response = None):
    """
    Returns regime-specific pillar weights from signal_fitness_regression.
    These weights measure which pillars predict realized_return_7d across trade history.

    Output:
        regime_pillar_weights.json mapping regime → {F, M, O, S, A} weights.
        Each regime shows: correlations, weights, sample_size.

    Updated on every 100 new trade_results rows. Cached 1h in Redis.
    Schedule: run after every 100 new trade_results rows.

    Usage: agents use these weights to understand which pillars are most predictive
    in each macro regime — improving signal quality over time.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=7200"

    # Check Redis cache first
    cache_key = "analytics:pillar_fitness"
    cached = await _redis_get(cache_key)
    if cached:
        return {"status": "success", "source": "cache", **cached}

    # Compute fresh from Supabase trade_results
    try:
        from src.analytics.signal_fitness_regression import (
            build_pillar_fitness_output,
            _fetch_trade_results,
        )
        rows = _fetch_trade_results()
        if not rows:
            return {"status": "success", "source": "computed", "error": "No trade results yet"}

        data = build_pillar_fitness_output(rows)
        # Cache result
        await _redis_set(cache_key, data, ttl=3600)
        return {"status": "success", "source": "computed", **data}
    except Exception as e:
        _logger.warning(f"[PILLAR_FITNESS] compute failed: {e}")
        return {"status": "error", "message": str(e)}
