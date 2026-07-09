"""
Positioning pressure — the UPSTREAM cause #2 (reflexive forced flow, not a reflection).

Forward supply (cause #1) is STRUCTURAL forced selling (unlocks). This is REFLEXIVE forced flow:
leverage. Extreme positive funding + high open interest = overleveraged longs whose liquidation
is a forced future SELL (bearish); extreme negative funding + high OI = overleveraged shorts whose
squeeze is a forced future BUY (bullish). The positioning is a decision already made; the
liquidation propagates into price LATER — upstream, knowable now, not a reflection of price.

This is the marginal participant being *forced* — the mechanism under the whole 大象无形 / marginal-
buyer thesis, made a signal. Signed: positioning_pressure ∈ [-1 (bearish long-liq) .. +1 (bullish squeeze)].

Free: CoinGecko /derivatives (funding_rate + open_interest per perp market; Binance is geo-blocked on
Railway so we aggregate across all venues via CG). Unit-agnostic: funding is scaled by a robust
cross-sectional percentile, so the raw funding unit doesn't matter. Feeds the ONE kernel (conviction).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_POS_KEY = "cis:positioning"
_POS_TTL = 30 * 60          # positioning moves faster than supply → 30 min
_MIN_OI_USD = 5_000_000     # ignore illiquid perps; positioning is only meaningful with real OI


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _compute(agg: dict) -> dict:
    """agg: {SYM: {"oi_wsum": Σ funding·oi, "oi": Σ oi}} → signed positioning pressure per asset.
    Robust: |funding| scaled by its 90th percentile across assets (unit-agnostic)."""
    fund = {}
    for sym, a in agg.items():
        oi = a["oi"]
        if oi < _MIN_OI_USD:
            continue
        fund[sym] = (a["oi_wsum"] / oi, oi)          # OI-weighted mean funding, total OI
    if not fund:
        return {}
    mags = sorted(abs(f) for f, _ in fund.values())
    p90 = mags[int(0.9 * (len(mags) - 1))] or (mags[-1] or 1e-9)
    scale = p90 or 1e-9
    out = {}
    for sym, (f, oi) in fund.items():
        # extreme POSITIVE funding → overleveraged longs → forced SELL → bearish (negative pressure)
        pressure = _clamp(-f / scale, -1.0, 1.0)
        out[sym] = {"positioning_pressure": round(pressure, 3),
                    "funding": round(f, 6), "oi_usd": round(oi, 0)}
    return out


async def refresh_positioning() -> dict:
    """Fetch CG derivatives, aggregate funding·OI per asset, compute signed pressure → Redis."""
    from src.data.market.data_layer import _get_misc_client, _redis_set
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    known = set(CRYPTO_ASSETS.keys())
    try:
        client = _get_misc_client()
        r = await client.get("https://api.coingecko.com/api/v3/derivatives",
                             params={"include_tickers": "unexpired"}, timeout=20)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:
        logger.warning(f"[POSITIONING] CG derivatives fetch failed: {e}")
        return {}
    agg: dict = {}
    for t in rows or []:
        sym = (t.get("index_id") or "").upper()
        if sym not in known:
            continue
        try:
            f = float(t.get("funding_rate"))
            oi = float(t.get("open_interest") or 0)
        except (TypeError, ValueError):
            continue
        if oi <= 0:
            continue
        a = agg.setdefault(sym, {"oi_wsum": 0.0, "oi": 0.0})
        a["oi_wsum"] += f * oi
        a["oi"] += oi
    out = _compute(agg)
    await _redis_set(_POS_KEY, out, ttl=_POS_TTL)
    extreme = sorted(((v["positioning_pressure"], s) for s, v in out.items()), key=lambda x: x[0])
    tail = extreme[:3] + extreme[-3:]
    logger.info(f"[POSITIONING] {len(out)} assets; extremes: "
                f"{', '.join(f'{s}={p:+.2f}' for p, s in tail)}")
    return out


async def get_positioning_map() -> dict:
    from src.data.market.data_layer import _redis_get
    m = await _redis_get(_POS_KEY)
    return m if isinstance(m, dict) else {}


def attach_positioning(universe: list, pmap: dict) -> None:
    pmap = pmap or {}
    for a in universe:
        if isinstance(a, dict):
            sym = (a.get("symbol") or a.get("asset_id") or "").upper()
            a["positioning"] = pmap.get(sym)
