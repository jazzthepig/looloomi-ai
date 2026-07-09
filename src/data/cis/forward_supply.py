"""
Forward supply pressure — the UPSTREAM cause primitive (not a reflection).

ARCHITECTURE.md: beta+ comes from being closer to the CAUSE, not the reflection. Every other
layer — CIS, edge map, momentum, sentiment — reads price or its derivatives. All downstream.
This reads the one thing that is a DECISION ALREADY MADE, propagates into price LATER, and is
knowable in ADVANCE: forward token supply. A token 15% circulating with 85% still to unlock
carries a forced-seller overhang that will dilute price regardless of how good its CIS looks
today. That is the marginal SELLER arriving — the exact mirror of 出圈 (marginal buyer exhausted).
Together they are the full "who is the marginal participant, and are they forced" picture.

Free + upstream: structural overhang from CoinGecko circulating/total/max supply (the paywalled
unlock-calendar APIs — DeFiLlama emissions, TokenUnlocks — are NOT required for the magnitude of
forced dilution, only for its exact timing). Coarse but REAL and knowable before price moves.

Feeds the ONE kernel (conviction) as the cause factor — NOT a new endpoint. Convergence, not sprawl.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_FS_KEY = "cis:forward_supply"
_FS_TTL = 6 * 3600
# overhang (supply-still-to-come ÷ circulating) at which forward-supply risk saturates to ~1.
# 1.5 ⇒ a token with 150%+ more supply coming vs what floats reads maximal forced-dilution risk.
_SATURATE = 1.5


def _risk_from(circ, total, maxs) -> dict | None:
    """Structural forced-seller overhang from supply figures. None if supply unknown."""
    try:
        circ = float(circ or 0); total = float(total or 0); maxs = float(maxs or 0)
    except (TypeError, ValueError):
        return None
    if circ <= 0:
        return None
    future = max(total, maxs)            # eventual supply that will circulate
    if future <= circ:                   # fully circulating (BTC-like) → no forced dilution ahead
        return {"forward_supply_risk": 0.0, "float_ratio": 1.0, "overhang": 0.0}
    overhang = (future - circ) / circ    # % more tokens that WILL enter, vs current float
    risk = min(1.0, overhang / _SATURATE)
    return {"forward_supply_risk": round(risk, 3),
            "float_ratio": round(circ / future, 3),
            "overhang": round(overhang, 3)}


async def refresh_forward_supply() -> dict:
    """Fetch supply for the crypto universe from CoinGecko, compute forced-seller overhang,
    write {SYMBOL: {forward_supply_risk, float_ratio, overhang}} to Redis. Background loop."""
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.market.data_layer import get_cg_markets, _redis_set
    id_to_sym = {cfg["coingecko"]: sym for sym, cfg in CRYPTO_ASSETS.items() if cfg.get("coingecko")}
    if not id_to_sym:
        return {}
    rows = await get_cg_markets(list(id_to_sym.keys()))
    out: dict = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = id_to_sym.get(r.get("id"))
        if not sym:
            continue
        risk = _risk_from(r.get("circulating_supply"), r.get("total_supply"), r.get("max_supply"))
        if risk is not None:
            out[sym] = risk
    await _redis_set(_FS_KEY, out, ttl=_FS_TTL)
    hi = sorted(((v["forward_supply_risk"], s) for s, v in out.items()), reverse=True)[:5]
    logger.info(f"[FWD-SUPPLY] {len(out)} assets; highest forced-dilution: "
                f"{', '.join(f'{s}={r}' for r, s in hi)}")
    return out


async def get_forward_supply_map() -> dict:
    """Read the cached forward-supply map (fast; never blocks serving). Cold → {}."""
    from src.data.market.data_layer import _redis_get
    m = await _redis_get(_FS_KEY)
    return m if isinstance(m, dict) else {}


def attach_forward_supply(universe: list, fmap: dict) -> None:
    """Mutate each asset with its `forward_supply` block (upstream cause). Absent → None."""
    fmap = fmap or {}
    for a in universe:
        if isinstance(a, dict):
            sym = (a.get("symbol") or a.get("asset_id") or "").upper()
            a["forward_supply"] = fmap.get(sym)
