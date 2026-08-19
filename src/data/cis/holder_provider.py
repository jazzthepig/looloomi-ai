"""
Holder-concentration provider (D3) via Moralis — the on-chain gold-standard tier for
cause_proximity (出圈). Turns per-token holder distribution into a diffusion `stage`.

Moralis covers EVM + Solana (matches our Solana fund); free tier ~10M req/mo. Registry-gated:
only tokens with a known (chain, contract) are fetched; everything else degrades gracefully to
the D4 attention / market-proxy floor (cause_proximity is never missing).

Serving never blocks on Moralis: a background loop (`refresh_holder_map`) writes the whole map
to Redis; `get_holder_map` just reads that cache. Cold cache → {} → graceful D4 degrade.

Phase 1 (this): current concentration → top10 supply share + HHI + a static `stage`
  (concentrated = in-circle/early = LOW stage; dispersed = out-of-circle/late = HIGH stage).
Phase 2 (later): Moralis holder TIMESERIES → dynamic season/chuquan (Wyckoff — Minimax lane);
  the downstream contract (stage/season → cause_proximity) is unchanged, so it's a fetch swap.
"""
from __future__ import annotations

import asyncio
import logging

from src.data.market.data_layer import (
    MORALIS_KEY, _redis_get, _redis_set, get_token_holders,
)

logger = logging.getLogger(__name__)

_HOLDER_MAP_KEY = "cis:holder_map"
_MAP_TTL = 6 * 3600

# Curated symbol → (Moralis chain, contract). EVM ERC-20 first — our DeFi/RWA mid-caps, exactly
# where 出圈 matters most. Solana SPL (Moralis solana-gateway) is Phase 2. TradFi / native L1s
# (BTC, SOL, ADA, TIA, APT, HYPE, all equities/bonds) have no ERC-20 contract → skipped → D4 floor.
_TOKEN_REGISTRY = {
    "ONDO":   ("eth", "0xfAbA6f8e4a5E8Ab82F62fe7C39859FA577269BE3"),
    "PENDLE": ("eth", "0x808507121B80c02388fAd14726482e061B8da827"),
    "UNI":    ("eth", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"),
    "AAVE":   ("eth", "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9"),
    "MKR":    ("eth", "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2"),
    "LINK":   ("eth", "0x514910771AF9Ca656af840dff83E8264EcF986CA"),
    "LDO":    ("eth", "0x5A98FcBEA516Cf06857215779Fd812CA3beF1B32"),
    "ARB":    ("arbitrum", "0x912CE59144191C1204E64559FE8253a0e49E6548"),
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _concentration(holders: list) -> dict | None:
    """From Moralis /erc20/{addr}/owners rows → top-10 supply share + HHI of the returned holders.
    Uses `percentage_relative_to_total_supply` (Moralis returns 0..100). Defensive: skip rows
    without a usable percentage; return None if nothing parses."""
    shares = []
    for h in holders:
        pct = h.get("percentage_relative_to_total_supply")
        if pct is None:
            continue
        try:
            shares.append(float(pct) / 100.0)
        except (TypeError, ValueError):
            continue
    if not shares:
        return None
    shares.sort(reverse=True)
    return {
        "top10_share": round(sum(shares[:10]), 4),
        "hhi": round(sum(s * s for s in shares), 4),   # concentration of returned (top-N) holders
        "n_top": len(shares),
    }


def _stage_from(top10_share: float) -> float:
    """Diffusion stage 0..1. Concentrated (high top10 = few whales = in-circle / upstream) → LOW;
    dispersed (low top10 = spread to the crowd = out-of-circle / late) → HIGH. Static proxy —
    provisional (a permanently low-float token can read 'early'); the dynamic timeseries (Phase 2)
    supersedes it with real diffusion velocity."""
    return round(_clamp01(1.0 - top10_share), 3)


async def _fetch_one(symbol: str, chain: str, address: str) -> dict | None:
    res = await get_token_holders(address, chain=chain, limit=100)
    if not isinstance(res, dict) or res.get("error"):
        return None
    conc = _concentration(res.get("holders", []))
    if not conc:
        return None
    return {
        "stage": _stage_from(conc["top10_share"]),
        "hhi": conc["hhi"],
        "top10": conc["top10_share"],
        "n_top": conc["n_top"],
        "chuquan": False,      # Phase 2 (needs timeseries)
        "season": None,        # Phase 2 (Wyckoff — Minimax lane)
        "source": "moralis_holders",
    }


async def refresh_holder_map() -> dict:
    """Background refresh: fetch concentration for every registry token, write the map to Redis.
    Concurrency-limited to respect the free tier. Gated on MORALIS_KEY."""
    if not MORALIS_KEY:
        logger.info("[HOLDER] MORALIS_API_KEY not set — skipping holder map")
        return {}
    sem = asyncio.Semaphore(4)
    out: dict = {}

    async def _go(sym: str, chain: str, addr: str):
        async with sem:
            try:
                row = await _fetch_one(sym, chain, addr)
                if row:
                    out[sym] = row
            except Exception as e:
                logger.warning(f"[HOLDER] {sym} failed: {e}")

    await asyncio.gather(*[_go(s, c, a) for s, (c, a) in _TOKEN_REGISTRY.items()])
    await _redis_set(_HOLDER_MAP_KEY, out, ttl=_MAP_TTL)
    await _persist_history(out)
    logger.info(f"[HOLDER] refreshed: {len(out)}/{len(_TOKEN_REGISTRY)} tokens "
                f"({', '.join(sorted(out)) or 'none'})")
    return out


async def _persist_history(rows: dict) -> bool:
    """Append today's concentration snapshot to `holder_concentration_history` (S-173).

    WHY THIS DID NOT EXIST. `_stage_from` above says it plainly: the static top-10
    share is a "provisional" proxy and "the dynamic timeseries (Phase 2)
    supersedes it with real diffusion velocity". `_fetch_one` returns
    `"chuquan": False,  # Phase 2 (needs timeseries)`.

    The timeseries never arrived because nothing ever stored one. Every refresh
    computed concentration, wrote it into a TTL'd Redis map, and let the previous
    day's value expire. **A velocity cannot be computed from a single snapshot**,
    so the entire holder-cohort direction — which is what ARCHITECTURE.md calls
    the deepest object, the Entity/Decision — was gated behind a table that was
    never created.

    This is the same defect as activation_z (computed, discarded), the strategy
    library in a 24h-TTL Redis key (S-105), and the eleven tables the code wrote
    to that did not exist (S-166). The pattern is not carelessness: it is that
    computing something FEELS like having it, and only a schema disagrees.

    Best-effort by design. A failure here degrades tomorrow's velocity study; it
    must not break today's CIS scoring, which reads the Redis map and is
    unaffected. But the failure is REPORTED — a silent False is what made the
    other four invisible.
    """
    if not rows:
        return False
    from datetime import date
    from src.api.store import supabase_upsert_table

    today = date.today().isoformat()
    payload = [{
        "d": today,
        "symbol": sym.upper(),
        "top10_share": r.get("top10"),
        "hhi": r.get("hhi"),
        "stage": r.get("stage"),
        "n_top": r.get("n_top"),
        "source": r.get("source"),
    } for sym, r in rows.items() if isinstance(r, dict)]

    ok = await supabase_upsert_table("holder_concentration_history", payload,
                                     on_conflict="d,symbol")
    if ok:
        logger.info("[HOLDER] history: %d snapshots persisted for %s "
                    "(velocity computable once >=2 days exist)", len(payload), today)
    else:
        # Named loudly. The whole point of this function is that the previous
        # arrangement lost data quietly for months.
        logger.warning("[HOLDER] history NOT persisted (%d rows). Either this "
                       "process is not APP_ROLE=production or Supabase declined. "
                       "Diffusion velocity stays uncomputable until this lands.",
                       len(payload))
    return ok


async def get_holder_map() -> dict:
    """Read the cached holder map. Fast; never triggers a Moralis fetch on the serving path.
    Cold cache → {} → cause_proximity degrades to the D4/market-proxy floor."""
    m = await _redis_get(_HOLDER_MAP_KEY)
    return m if isinstance(m, dict) else {}
