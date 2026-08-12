"""
Factor Registry & Performance Router — CometCloud AI
=====================================================
Endpoints:
  GET /api/v1/factors              — Full factor registry (all 30 factors)
  GET /api/v1/factors/{factor_id}  — Single factor detail
  GET /api/v1/factors/pillar/{p}   — Factors for a given pillar (F|M|O|S|A)
  GET /api/v1/factors/performance  — Factor performance health report (Pearson vs realized returns)
  GET /api/v1/factors/selection-standard — §F-SEL documented selection criteria
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

_logger = logging.getLogger(__name__)
router  = APIRouter()


def _reg():
    try:
        from src.data.factors.registry import FACTORS, get_by_pillar, get_by_id, get_by_class, summary
    except ImportError:
        from data.factors.registry import FACTORS, get_by_pillar, get_by_id, get_by_class, summary
    return FACTORS, get_by_pillar, get_by_id, get_by_class, summary


def _perf():
    try:
        from src.data.factors.performance import load, get_factor_health_report
    except ImportError:
        from data.factors.performance import load, get_factor_health_report
    return load, get_factor_health_report


# ── GET /api/v1/factors ───────────────────────────────────────────────────────

@router.get("/api/v1/factors")
async def list_factors(
    pillar:      Optional[str] = Query(None, description="Filter by pillar: F, M, O, S, A"),
    asset_class: Optional[str] = Query(None, description="Filter by asset class"),
    source:      Optional[str] = Query(None, description="Filter by data source"),
):
    """
    Full CIS factor registry. 30 factors across 5 pillars.
    Each factor includes: id, pillar, name, description, source, normalization,
    score_range, asset_classes, regime_weight, inclusion_criteria, known_issues, version_added.
    """
    FACTORS, get_by_pillar, get_by_id, get_by_class, summary = _reg()
    factors = FACTORS

    if pillar:
        p = pillar.upper()
        if p not in ("F", "M", "O", "S", "A"):
            raise HTTPException(400, f"Invalid pillar '{pillar}'. Must be F, M, O, S, or A.")
        factors = get_by_pillar(p)

    if asset_class:
        factors = [f for f in factors
                   if "all" in f["asset_classes"] or asset_class in f["asset_classes"]]

    if source:
        factors = [f for f in factors if f["source"] == source]

    return {
        "total": len(factors),
        "summary": summary(),
        "factors": factors,
    }


# ── GET /api/v1/factors/selection-standard ────────────────────────────────────

@router.get("/api/v1/factors/selection-standard")
async def get_selection_standard():
    """
    CIS factor selection standard (§F-SEL). Documents the 7 criteria a factor
    must satisfy to be included in the CIS model.
    """
    return {
        "standard": "§F-SEL — CIS Factor Selection Standard v4.3",
        "description": "A factor is included in the CIS model if and only if it meets ALL of:",
        "criteria": [
            {
                "id":       "F-SEL-1",
                "name":     "Measurability",
                "rule":     "Quantifiable from a reliable, systematic data source. No manual input.",
                "sources_accepted": [
                    "coingecko", "coingecko_pro", "defillama", "alternative.me",
                    "yfinance", "eodhd", "github", "binance"
                ],
                "sources_rejected": ["Twitter scrapes", "manual analyst judgement", "unverifiable on-chain"],
            },
            {
                "id":       "F-SEL-2",
                "name":     "Predictability",
                "rule":     "|Pearson r| > 0.10 vs 30d forward return, OR is a risk/regulatory flag preventing catastrophic drawdown.",
                "threshold_active":      0.10,
                "threshold_probationary":0.05,
                "threshold_removal":     0.05,
                "note":     "Risk flags (e.g., OI/MCap leverage, exchange HHI) are exempt from r-threshold if they prevent drawdown > 20%.",
            },
            {
                "id":       "F-SEL-3",
                "name":     "Orthogonality",
                "rule":     "Pairwise Pearson correlation < 0.70 with any existing factor in the same pillar.",
                "exception":"Dual-use factors (e.g., TVL in both F and O pillars) documented with justification in registry.",
            },
            {
                "id":       "F-SEL-4",
                "name":     "Timeliness",
                "rule":     "Data available within 24h (T2 assets) or 4h (T1 assets) of market close.",
                "note":     "Factors requiring T+2 settlement data (e.g., EODHD earnings) scored on last available reading with staleness flag.",
            },
            {
                "id":       "F-SEL-5",
                "name":     "Universe Breadth",
                "rule":     "Applicable to ≥ 60% of assets in the CIS universe OR class-restricted with documentation.",
                "note":     "Class-restricted factors (e.g., eodhd_pe = US Equity only) are permitted with explicit asset_classes field in registry.",
            },
            {
                "id":       "F-SEL-6",
                "name":     "Stability",
                "rule":     "Scoring function produces monotonic output. No cliff edges at data extremes (e.g., NaN inputs → 0, not exception).",
                "note":     "All factors use _log_score() or _linear_interp() with explicit clamp bounds. No undefined behavior at limits.",
            },
            {
                "id":       "F-SEL-7",
                "name":     "Compliance",
                "rule":     "Factor must not constitute an investment recommendation. Output is positioning signal only (OUTPERFORM/NEUTRAL/UNDERPERFORM).",
                "reference":"CLAUDE.md compliance rules §1. CIS_METHODOLOGY.md §5 and §8.",
            },
        ],
        "review_cadence": "Weekly (Sunday/Monday). Factor performance tracked via /api/v1/factors/performance.",
        "governance":     "Factor additions require Jazz (product lead) approval + Seth (technical validation). Removals require 3 consecutive probationary periods.",
    }


# ── GET /api/v1/factors/{factor_id} ──────────────────────────────────────────

@router.get("/api/v1/factors/pillar/{pillar}")
async def get_factors_by_pillar(pillar: str):
    """Factors for a single pillar with live performance."""
    FACTORS, get_by_pillar, get_by_id, get_by_class, summary = _reg()
    load, get_factor_health_report = _perf()

    p = pillar.upper()
    if p not in ("F", "M", "O", "S", "A"):
        raise HTTPException(400, f"Invalid pillar '{pillar}'")

    factors = get_by_pillar(p)
    perf_store = load()

    return {
        "pillar":  p,
        "count":   len(factors),
        "factors": [
            {**f, "live_performance": perf_store.get(f["id"])}
            for f in factors
        ],
    }


# ── GET /api/v1/factors/performance ──────────────────────────────────────────

@router.get("/api/v1/factors/performance")
async def get_factor_performance():
    """
    Factor performance health report.
    Shows Pearson correlation vs realized trade returns for each factor.
    Updated every time /api/v1/trading/mine?type=pillar_fitness is run.

    Status tiers:
      active            — |r| > 0.10 (retained)
      probationary      — 0.05 < |r| ≤ 0.10 (watch list)
      candidate_removal — |r| ≤ 0.05 for 3+ periods (flag for next review)
      no_data           — no paper trades with pillar data yet
    """
    load, get_factor_health_report = _perf()

    try:
        report = get_factor_health_report()
    except Exception as e:
        _logger.error(f"[factors] performance report failed: {e}")
        raise HTTPException(502, f"Performance report failed: {e}")

    return {
        "report": report,
        "selection_standard": "§F-SEL: |r| > 0.10 = active, > 0.05 = probationary, ≤ 0.05 for 3 periods = candidate_removal",
        "note": "Performance data accumulates from paper trading mine runs. Minimum 5 closed trades with pillar data required per factor.",
    }

@router.get("/api/v1/factors/{factor_id}")
async def get_factor(factor_id: str):
    """Single factor detail by id. Includes live performance data if available."""
    FACTORS, get_by_pillar, get_by_id, get_by_class, summary = _reg()
    load, get_factor_health_report = _perf()

    fac = get_by_id(factor_id)
    if fac is None:
        raise HTTPException(404, f"Factor '{factor_id}' not found. Valid ids: {[f['id'] for f in FACTORS]}")

    # Attach live performance if available
    perf_store = load()
    perf = perf_store.get(factor_id)
    return {
        **fac,
        "live_performance": perf,
    }


# ── GET /api/v1/factors/pillar/{pillar} ──────────────────────────────────────

