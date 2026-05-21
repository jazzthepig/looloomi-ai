"""
Multi-Factor Strategy Router
Endpoints: /api/v1/strategies/*

Each strategy defines a pillar weight profile (F/M/O/S/A) that overrides the
default asset-class base weights. The regime multipliers and Simons IC feedback
still apply on top — strategies set direction, regime sets context.

Architecture (4-layer weight system):
  Layer 0: Strategy weights  (this module — new)
  Layer 1: Asset-class base  (cis_provider _BASE_WEIGHTS — regime-neutral anchor)
  Layer 2: Regime multipliers (cis_provider _REGIME_MULT — macro context)
  Layer 3: Simons IC feedback (live IC loop — performance tracking)
  → Renormalize → CIS Score
"""
import logging, time, math
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query

from src.api.store import redis_get_key, redis_set_key, sanitize_floats
from src.data.cis.cis_provider import calculate_cis_universe

_logger = logging.getLogger(__name__)
router = APIRouter()

# ── Strategy Definitions ─────────────────────────────────────────────────────
#
# pillar_weights: override base weights per pillar (F/M/O/S/A).
#   Regime multipliers still applied on top → renormalized.
#   Sum of pillar_weights should equal 1.0.
#
# entry_criteria: minimum pillar/composite scores for a signal to qualify.
#   This gates which assets are surfaced as actionable.
#
# preferred_regimes: regimes where this strategy has highest edge.
#   Used to compute strategy_fitness score (0-100).
#
# risk_profile: conservative / balanced / aggressive
#   Maps to PortfolioAllocation min grade thresholds.

STRATEGIES: Dict[str, Dict[str, Any]] = {
    "breakout": {
        "id": "breakout",
        "name": "Breakout",
        "subtitle": "Sentiment · Momentum",
        "description": (
            "Captures assets building momentum before a breakout. "
            "Heavy S+M weighting surfaces assets where crowd sentiment "
            "and price momentum are both accelerating — optimal entry "
            "before a trend becomes consensus."
        ),
        "pillar_weights": {"F": 0.10, "M": 0.35, "O": 0.10, "S": 0.35, "A": 0.10},
        "entry_criteria": {
            "min_cis": 62,
            "min_pillar": {"M": 55, "S": 52},
        },
        "preferred_regimes": ["Risk-On", "Easing", "Goldilocks"],
        "unfavorable_regimes": ["Tightening", "Risk-Off", "Stagflation"],
        "risk_profile": "aggressive",
        "target_hold_days": "14–30",
        "color": "#06B6D4",    # cyan
        "icon": "⚡",
        "freqtrade_class": "BreakoutStrategy",
        "tags": ["momentum", "sentiment", "trend-following"],
    },
    "value_onchain": {
        "id": "value_onchain",
        "name": "Value / On-Chain",
        "subtitle": "Fundamental · Risk-Adjusted",
        "description": (
            "Targets undervalued assets with strong on-chain fundamentals "
            "and low risk-adjusted volatility. F+O dominance filters out "
            "hype-driven noise — ideal when the market rewards quality "
            "over speculation."
        ),
        "pillar_weights": {"F": 0.40, "M": 0.10, "O": 0.35, "S": 0.05, "A": 0.10},
        "entry_criteria": {
            "min_cis": 58,
            "min_pillar": {"F": 60, "O": 55},
        },
        "preferred_regimes": ["Tightening", "Risk-Off", "Stagflation"],
        "unfavorable_regimes": ["Risk-On", "Easing"],
        "risk_profile": "conservative",
        "target_hold_days": "30–90",
        "color": "#10B981",    # emerald
        "icon": "⚖",
        "freqtrade_class": "ValueOnChainStrategy",
        "tags": ["value", "fundamental", "on-chain", "quality"],
    },
    "regime_adaptive": {
        "id": "regime_adaptive",
        "name": "Regime-Adaptive",
        "subtitle": "Auto-Switch · Macro-Aware",
        "description": (
            "Automatically shifts pillar emphasis based on the detected "
            "macro regime. Weights swing between Breakout-style (Risk-On) "
            "and Value-style (Tightening) profiles, with smooth transitions "
            "during regime uncertainty."
        ),
        "pillar_weights": {"F": 0.25, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.15},  # base (neutral)
        "entry_criteria": {
            "min_cis": 60,
            "min_pillar": {},
        },
        "preferred_regimes": ["Goldilocks", "Neutral"],
        "unfavorable_regimes": [],
        "risk_profile": "balanced",
        "target_hold_days": "Variable",
        "color": "#8B5CF6",    # purple
        "icon": "◎",
        "freqtrade_class": "RegimeAdaptiveStrategy",
        "tags": ["macro-aware", "adaptive", "balanced"],
    },
}

# ── Regime → Breakout/Value blend for Regime-Adaptive ───────────────────────
_REGIME_BLEND: Dict[str, Dict[str, float]] = {
    "Risk-On":     {"F": 0.10, "M": 0.35, "O": 0.10, "S": 0.35, "A": 0.10},  # full breakout
    "Easing":      {"F": 0.15, "M": 0.30, "O": 0.15, "S": 0.28, "A": 0.12},  # breakout-leaning
    "Goldilocks":  {"F": 0.20, "M": 0.25, "O": 0.20, "S": 0.22, "A": 0.13},  # balanced
    "Neutral":     {"F": 0.25, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.15},  # neutral
    "Tightening":  {"F": 0.38, "M": 0.12, "O": 0.32, "S": 0.08, "A": 0.10},  # value-leaning
    "Risk-Off":    {"F": 0.40, "M": 0.10, "O": 0.35, "S": 0.05, "A": 0.10},  # full value
    "Stagflation": {"F": 0.42, "M": 0.08, "O": 0.35, "S": 0.05, "A": 0.10},  # defensive
}


def _compute_strategy_cis(
    asset: Dict[str, Any],
    strategy_weights: Dict[str, float],
) -> Dict[str, Any]:
    """
    Re-score a CIS asset using strategy-defined pillar weights instead of
    the default asset-class base weights. Produces:
      - strategy_cis: composite score with strategy weights
      - strategy_grade: grade bucket for this score
      - factor_exposure: per-pillar contribution breakdown
      - weight_delta: how strategy weights differ from the standard weights
    """
    # Extract pillar scores (handle both Mac Mini T1 and Railway T2 field shapes)
    f = asset.get("F") or asset.get("fundamental_score") or 0
    m = asset.get("M") or asset.get("momentum_score") or 0
    o = asset.get("O") or asset.get("risk_adjusted_score") or 0
    s = asset.get("S") or asset.get("sensitivity_score") or 0
    a = asset.get("A") or asset.get("alpha_score") or 0

    # If pillars dict exists (T1 Mac Mini structure)
    pillars = asset.get("pillars", {})
    if pillars:
        f = pillars.get("F", f) or f
        m = pillars.get("M", m) or m
        o = pillars.get("O", o) or o
        s = pillars.get("S", s) or s
        a = pillars.get("A", a) or a

    w = strategy_weights
    total = w["F"] * f + w["M"] * m + w["O"] * o + w["S"] * s + w["A"] * a

    # Factor exposure: weighted contribution per pillar
    factor_exposure = {
        "F": round(w["F"] * f, 1),
        "M": round(w["M"] * m, 1),
        "O": round(w["O"] * o, 1),
        "S": round(w["S"] * s, 1),
        "A": round(w["A"] * a, 1),
    }

    return {
        "strategy_cis": round(total, 1),
        "strategy_grade": _grade(total),
        "pillar_scores": {"F": f, "M": m, "O": o, "S": s, "A": a},
        "strategy_weights": w,
        "factor_exposure": factor_exposure,
    }


def _grade(score: float) -> str:
    if score >= 85: return "A+"
    if score >= 75: return "A"
    if score >= 65: return "B+"
    if score >= 55: return "B"
    if score >= 45: return "C+"
    if score >= 35: return "C"
    if score >= 25: return "D"
    return "F"


def _signal_for_score(score: float) -> str:
    if score >= 75: return "STRONG OUTPERFORM"
    if score >= 62: return "OUTPERFORM"
    if score >= 48: return "NEUTRAL"
    if score >= 35: return "UNDERPERFORM"
    return "UNDERWEIGHT"


def _strategy_fitness(strategy: Dict, regime: str) -> int:
    """
    0-100 fitness score: how well does current regime suit this strategy?
    preferred_regimes → high fitness, unfavorable → low, neutral → mid.
    """
    if regime in strategy["preferred_regimes"]:
        idx = strategy["preferred_regimes"].index(regime)
        return max(70, 100 - idx * 10)
    if regime in strategy["unfavorable_regimes"]:
        idx = strategy["unfavorable_regimes"].index(regime)
        return max(10, 45 - idx * 10)
    return 55  # neutral — strategy works but not optimal


def _resolve_weights(strategy: Dict, regime: str) -> Dict[str, float]:
    """For regime_adaptive, use the regime-specific blend. Others use fixed weights."""
    if strategy["id"] == "regime_adaptive":
        blend = _REGIME_BLEND.get(regime, strategy["pillar_weights"])
        # Normalize just in case
        total = sum(blend.values())
        return {k: round(v / total, 4) for k, v in blend.items()}
    return strategy["pillar_weights"]


def _passes_entry(asset_scored: Dict, entry_criteria: Dict, strategy_id: str) -> bool:
    """Check if an asset meets strategy entry criteria."""
    if asset_scored["strategy_cis"] < entry_criteria.get("min_cis", 0):
        return False
    pillar_scores = asset_scored["pillar_scores"]
    for pillar, min_val in entry_criteria.get("min_pillar", {}).items():
        if (pillar_scores.get(pillar) or 0) < min_val:
            return False
    return True


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/v1/strategies")
async def list_strategies():
    """
    List all available multi-factor strategies with metadata.
    Returns strategy definitions, pillar weights, and current regime fitness.
    """
    # Get current regime from Redis
    try:
        cached = await redis_get_key("cis:local_scores")
        if cached and isinstance(cached, dict):
            macro = cached.get("macro", {})
            regime = macro.get("regime", "Neutral") if isinstance(macro, dict) else "Neutral"
        else:
            regime = "Neutral"
    except Exception:
        regime = "Neutral"

    result = []
    for s in STRATEGIES.values():
        weights = _resolve_weights(s, regime)
        result.append({
            **{k: v for k, v in s.items() if k not in ("entry_criteria",)},
            "pillar_weights": weights,
            "strategy_fitness": _strategy_fitness(s, regime),
            "current_regime": regime,
        })

    return {"strategies": result, "current_regime": regime, "count": len(result)}


@router.get("/api/v1/strategies/{strategy_id}")
async def get_strategy(strategy_id: str):
    """Single strategy definition with current regime fitness."""
    if strategy_id not in STRATEGIES:
        raise HTTPException(404, f"Strategy '{strategy_id}' not found. "
                            f"Available: {list(STRATEGIES.keys())}")

    s = STRATEGIES[strategy_id]
    try:
        cached = await redis_get_key("cis:local_scores")
        regime = "Neutral"
        if cached and isinstance(cached, dict):
            macro = cached.get("macro", {})
            regime = macro.get("regime", "Neutral") if isinstance(macro, dict) else regime
    except Exception:
        regime = "Neutral"

    weights = _resolve_weights(s, regime)
    return {
        **s,
        "pillar_weights": weights,
        "strategy_fitness": _strategy_fitness(s, regime),
        "current_regime": regime,
    }


@router.get("/api/v1/strategies/{strategy_id}/universe")
async def strategy_universe(
    strategy_id: str,
    top_n: int = Query(default=20, ge=1, le=100),
    min_grade: Optional[str] = Query(default=None),
):
    """
    CIS universe re-scored using the strategy's pillar weights.
    Returns assets ranked by strategy_cis, filtered by entry_criteria.

    Use this to see which assets the strategy would currently target.
    min_grade: optional grade filter (e.g. "B", "B+", "A") — applied to strategy_cis grade.
    """
    if strategy_id not in STRATEGIES:
        raise HTTPException(404, f"Strategy '{strategy_id}' not found.")

    strategy = STRATEGIES[strategy_id]

    _CACHE_KEY = f"strategy:universe:{strategy_id}"
    _TTL = 300  # 5min cache

    cached = await redis_get_key(_CACHE_KEY)
    if cached and isinstance(cached, dict):
        assets = cached.get("assets", [])
        regime = cached.get("regime", "Neutral")
    else:
        # Fetch base universe
        try:
            base_universe = await calculate_cis_universe()
        except Exception as e:
            _logger.error(f"[Strategies] Failed to fetch base universe: {e}")
            raise HTTPException(500, "CIS universe unavailable")

        raw_assets = base_universe.get("assets", [])
        regime = base_universe.get("macro_regime", "Neutral")

        weights = _resolve_weights(strategy, regime)
        entry = strategy["entry_criteria"]

        scored = []
        for asset in raw_assets:
            try:
                result = _compute_strategy_cis(asset, weights)
                qualifies = _passes_entry(result, entry, strategy_id)
                scored.append({
                    # Core identity
                    "symbol": asset.get("symbol") or asset.get("asset_id", ""),
                    "name": asset.get("name", ""),
                    "asset_class": asset.get("asset_class", "Crypto"),
                    "data_tier": asset.get("data_tier", 2),
                    # Standard CIS (unchanged)
                    "cis_score": asset.get("cis_score") or asset.get("score", 0),
                    "grade": asset.get("grade", "C"),
                    "signal": asset.get("signal", "NEUTRAL"),
                    # Strategy-weighted CIS
                    "strategy_cis": result["strategy_cis"],
                    "strategy_grade": result["strategy_grade"],
                    "strategy_signal": _signal_for_score(result["strategy_cis"]),
                    "strategy_weights": result["strategy_weights"],
                    "factor_exposure": result["factor_exposure"],
                    "pillar_scores": result["pillar_scores"],
                    # Entry gate
                    "qualifies": qualifies,
                    # Market data pass-through
                    "price": asset.get("price"),
                    "change_24h": asset.get("change_24h"),
                    "change_7d": asset.get("change_7d"),
                    "market_cap": asset.get("market_cap"),
                    "volume_24h": asset.get("volume_24h"),
                    "las": asset.get("las"),
                    "confidence": asset.get("confidence"),
                })
            except Exception as e:
                _logger.debug(f"[Strategies] Skip {asset.get('symbol')}: {e}")

        # Sort by strategy_cis descending
        scored.sort(key=lambda x: x["strategy_cis"], reverse=True)
        assets = scored

        await redis_set_key(_CACHE_KEY, {"assets": assets, "regime": regime}, ttl=_TTL)

    # Apply grade filter
    _GRADE_ORDER = ["F", "D", "C", "C+", "B", "B+", "A", "A+"]
    if min_grade and min_grade in _GRADE_ORDER:
        min_idx = _GRADE_ORDER.index(min_grade)
        assets = [a for a in assets if _GRADE_ORDER.index(a.get("strategy_grade", "F")) >= min_idx]

    # Qualifying assets first, then all
    qualifying = [a for a in assets if a.get("qualifies")]
    non_qualifying = [a for a in assets if not a.get("qualifies")]

    result = qualifying + non_qualifying
    result = result[:top_n]

    return sanitize_floats({
        "strategy_id": strategy_id,
        "strategy_name": strategy["name"],
        "current_regime": regime,
        "strategy_fitness": _strategy_fitness(strategy, regime),
        "pillar_weights": _resolve_weights(strategy, regime),
        "entry_criteria": strategy["entry_criteria"],
        "qualifying_count": len(qualifying),
        "total_count": len(assets),
        "assets": result,
        "generated_at": int(time.time()),
    })


@router.get("/api/v1/strategies/{strategy_id}/signals")
async def strategy_signals(
    strategy_id: str,
    top_n: int = Query(default=10, ge=1, le=50),
):
    """
    Top N qualifying signals for this strategy — assets that pass entry criteria.
    Returns compliance-safe positioning signals only (no BUY/SELL language).
    """
    if strategy_id not in STRATEGIES:
        raise HTTPException(404, f"Strategy '{strategy_id}' not found.")

    universe_data = await strategy_universe(strategy_id, top_n=100)
    assets = universe_data.get("assets", [])
    qualifying = [a for a in assets if a.get("qualifies")][:top_n]

    signals = []
    for a in qualifying:
        pillar_s = a.get("pillar_scores", {})
        strategy = STRATEGIES[strategy_id]
        w = a.get("strategy_weights", strategy["pillar_weights"])

        # Identify dominant factors (top 2 by contribution)
        exposure = a.get("factor_exposure", {})
        sorted_factors = sorted(exposure.items(), key=lambda x: x[1], reverse=True)
        dominant = [f"{k}={v:.0f}" for k, v in sorted_factors[:2]]

        signals.append({
            "symbol": a["symbol"],
            "name": a.get("name", ""),
            "asset_class": a.get("asset_class", ""),
            "data_tier": a.get("data_tier", 2),
            "strategy_cis": a["strategy_cis"],
            "strategy_grade": a["strategy_grade"],
            "strategy_signal": a["strategy_signal"],
            "dominant_factors": dominant,
            "factor_exposure": exposure,
            "pillar_scores": pillar_s,
            "price": a.get("price"),
            "change_24h": a.get("change_24h"),
            "confidence": a.get("confidence"),
        })

    return sanitize_floats({
        "strategy_id": strategy_id,
        "strategy_name": STRATEGIES[strategy_id]["name"],
        "current_regime": universe_data.get("current_regime", "Neutral"),
        "strategy_fitness": universe_data.get("strategy_fitness", 55),
        "qualifying_signals": len(signals),
        "signals": signals,
        "generated_at": int(time.time()),
        "compliance_note": (
            "Positioning signals only. Not investment advice. "
            "CometCloud does not hold Type 9 advisory license."
        ),
    })


@router.get("/api/v1/strategies/compare/pillar-weights")
async def compare_pillar_weights():
    """
    Side-by-side comparison of all strategy pillar weights.
    Useful for building factor exposure charts in the frontend.
    """
    try:
        cached = await redis_get_key("cis:local_scores")
        regime = "Neutral"
        if cached and isinstance(cached, dict):
            macro = cached.get("macro", {})
            regime = macro.get("regime", "Neutral") if isinstance(macro, dict) else "Neutral"
    except Exception:
        regime = "Neutral"

    comparison = {}
    for sid, s in STRATEGIES.items():
        weights = _resolve_weights(s, regime)
        comparison[sid] = {
            "name": s["name"],
            "weights": weights,
            "fitness": _strategy_fitness(s, regime),
            "color": s["color"],
            "icon": s["icon"],
        }

    return {
        "current_regime": regime,
        "strategies": comparison,
        "pillars": ["F", "M", "O", "S", "A"],
        "pillar_labels": {
            "F": "Fundamental",
            "M": "Momentum",
            "O": "On-Chain/Risk",
            "S": "Sentiment",
            "A": "Alpha",
        },
    }
