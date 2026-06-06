"""
Executability layer — turns the opaque LAS liquidity multiplier into a concrete,
agent-actionable answer: "how much can I move in this asset, and at what cost?"

For a trading agent, a CIS score is necessary but not sufficient — before it sizes
a position it needs to know the price impact of trading $X notional. This module
produces a structured slippage estimate per asset:

  - spread_bps            half-spread cost to cross the book
  - slippage_curve        [{notional_usd, impact_bps}, …] across standard sizes
  - max_notional_at       {"10bps", "25bps", "50bps", "100bps"} → $ you can move
  - liquidity_tier        deep | high | medium | thin | illiquid
  - source                model_estimate | cg_tickers | macmini_orderbook | tradfi_assumed
  - confidence            0–1

Model — square-root market impact (standard practical form):

    impact_bps(Q) = half_spread_bps + IMPACT_COEF · 1e4 · sqrt(Q / ADV)

where Q = trade notional (USD), ADV = 24h USD volume, IMPACT_COEF is a
calibration constant. Inverting gives the max notional tradeable within a target
impact. This is an ESTIMATE labeled as such; the Mac Mini can push real order-book
depth (`orderbook` field on a push) to replace the estimate with an exact curve —
Binance depth is geo-blocked on Railway US, so full-fidelity depth is computed
local-side. The estimate is the never-missing floor.

Two entry points:
  estimate_inline(market_data, asset_class)  — cheap, no HTTP; for the universe.
  executability_detail(symbol, coin_id, asset_class, market_data) — HTTP via CG
        tickers for real per-exchange spread; for the per-asset endpoint.
"""
from __future__ import annotations

import math
from typing import Any

IMPACT_COEF = 0.015           # square-root impact calibration: ~10% of ADV ≈ 50bps
STANDARD_NOTIONALS = [10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000, 10_000_000]
TARGET_BPS = [10, 25, 50, 100]

# ADV (24h USD volume) → (tier, representative half-spread bps) when spread unknown
_TIERS = [
    (1_000_000_000, "deep",      1.0),
    (250_000_000,   "high",      3.0),
    (50_000_000,    "medium",    8.0),
    (10_000_000,    "thin",      25.0),
    (0,             "illiquid",  75.0),
]

_TRADFI_CLASSES = {"US Equity", "US Bond", "EM Equity", "DM Equity", "Commodity", "TradFi"}


def _tier_for(adv_usd: float) -> tuple[str, float]:
    for floor, tier, spread in _TIERS:
        if adv_usd >= floor:
            return tier, spread
    return "illiquid", 75.0


def _impact_bps(notional: float, adv_usd: float, half_spread_bps: float) -> float:
    if adv_usd <= 0:
        return 9999.0
    return round(half_spread_bps + IMPACT_COEF * 1e4 * math.sqrt(max(notional, 0) / adv_usd), 1)


def _max_notional_at(target_bps: float, adv_usd: float, half_spread_bps: float) -> float:
    """Invert the impact model: largest notional whose impact ≤ target_bps."""
    if adv_usd <= 0 or target_bps <= half_spread_bps:
        return 0.0
    frac = (target_bps - half_spread_bps) / (IMPACT_COEF * 1e4)
    return round(adv_usd * frac * frac, 0)


def _build(adv_usd: float, half_spread_bps: float, source: str, confidence: float,
           extra: dict | None = None) -> dict:
    tier, _ = _tier_for(adv_usd)
    curve = [
        {"notional_usd": q, "impact_bps": _impact_bps(q, adv_usd, half_spread_bps)}
        for q in STANDARD_NOTIONALS
    ]
    max_at = {
        f"{t}bps": _max_notional_at(t, adv_usd, half_spread_bps) for t in TARGET_BPS
    }
    out = {
        "spread_bps":       round(half_spread_bps * 2, 1),
        "half_spread_bps":  round(half_spread_bps, 1),
        "adv_usd":          round(adv_usd, 0),
        "liquidity_tier":   tier,
        "slippage_curve":   curve,
        "max_notional_at":  max_at,
        "source":           source,
        "confidence":       round(confidence, 2),
        "model":            "sqrt_impact",
    }
    if extra:
        out.update(extra)
    return out


def estimate_inline(market_data: dict, asset_class: str | None = None) -> dict:
    """
    Cheap executability estimate from already-fetched market data — NO network.
    Used to enrich every asset in the universe without adding latency.
    """
    adv = float(
        market_data.get("volume_24h") or market_data.get("total_volume")
        or market_data.get("volume") or 0
    )
    if asset_class in _TRADFI_CLASSES:
        # Listed equities / major ETFs clear enormous size with negligible impact.
        # Treat as deep with a tight assumed spread; flag the assumption.
        adv = max(adv, 250_000_000)
        return _build(adv, half_spread_bps=1.0, source="tradfi_assumed", confidence=0.5)

    _, spread = _tier_for(adv)
    conf = 0.6 if adv > 0 else 0.2
    return _build(adv, half_spread_bps=spread, source="model_estimate", confidence=conf)


def summarize(exec_full: dict) -> dict:
    """Compact view attached inline to each universe asset (agents read this first)."""
    return {
        "spread_bps":            exec_full.get("spread_bps"),
        "liquidity_tier":        exec_full.get("liquidity_tier"),
        "max_notional_25bps_usd": (exec_full.get("max_notional_at") or {}).get("25bps"),
        "max_notional_50bps_usd": (exec_full.get("max_notional_at") or {}).get("50bps"),
        "source":                exec_full.get("source"),
        "confidence":            exec_full.get("confidence"),
    }


def attach_executability(universe: list) -> None:
    """Mutate each asset in place with an inline executability summary."""
    for a in universe:
        if not isinstance(a, dict):
            continue
        # Mac Mini may push a full order-book-derived block; keep it if present.
        if isinstance(a.get("executability"), dict) and a["executability"].get("source") == "macmini_orderbook":
            a["executability"] = summarize(a["executability"])
            continue
        md = {
            "volume_24h": a.get("volume_24h") or a.get("volume"),
            "total_volume": a.get("total_volume"),
        }
        a["executability"] = summarize(estimate_inline(md, a.get("asset_class")))


async def executability_detail(symbol: str, coin_id: str | None,
                               asset_class: str | None, market_data: dict | None = None) -> dict:
    """
    Full per-asset executability. For crypto, pulls real per-exchange bid/ask
    spread + aggregate volume from CoinGecko tickers (Railway-accessible). Falls
    back to the inline estimate if tickers are unavailable.
    """
    market_data = market_data or {}
    if asset_class in _TRADFI_CLASSES:
        d = estimate_inline(market_data, asset_class)
        d["symbol"] = symbol.upper()
        d["note"] = "Listed-market liquidity assumed deep; order-book depth not modeled for TradFi."
        return d

    if coin_id:
        try:
            from src.data.market.data_layer import get_cg_coin_tickers
            t = await get_cg_coin_tickers(coin_id, depth=10)
        except Exception:
            t = None
        if t and t.get("available"):
            adv = float(t.get("total_volume_usd") or 0)
            # Use the tightest spread among trusted (green) venues — where an agent
            # would actually route — falling back to any reported spread.
            spreads = [
                ex.get("bid_ask_spread") for ex in t.get("exchanges", [])
                if ex.get("bid_ask_spread") is not None
                and ex.get("trust_score") in ("green", "yellow", "")
            ]
            if spreads:
                half_spread_bps = max(0.5, min(spreads) * 100 / 2)  # pct → bps, halved
            else:
                _, half_spread_bps = _tier_for(adv)
            extra = {
                "symbol":           symbol.upper(),
                "venue_count":      len(t.get("exchanges", [])),
                "top3_share_pct":   t.get("top3_share_pct"),
                "concentration_hhi": t.get("hhi"),
            }
            return _build(adv, half_spread_bps, source="cg_tickers", confidence=0.8, extra=extra)

    d = estimate_inline(market_data, asset_class)
    d["symbol"] = symbol.upper()
    return d
