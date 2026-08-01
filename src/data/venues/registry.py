"""
Venue registry — which venues carry which asset, and how each reports.

Design rules (learned from the HYPE ticker collision, 2026-08-01):

 1. NEVER derive a venue symbol from the asset ticker by string templating
    alone. Ticker collisions across venues are real and silent: Binance spot
    HYPERUSDT is Hyperlane, not Hyperliquid. Every mapping is explicit, and
    an asset absent from a venue is recorded as an explicit absence
    (NOT_LISTED) rather than left to a template that will happily produce a
    valid-looking symbol for the wrong asset.

 2. Every venue declares its reporting units so the consolidator can
    normalize. Getting OI in coins vs USD wrong is a silent 50x error.

 3. Venue eligibility is reviewed on a cadence (see REVIEWED_AT). The three
    production defects found on 2026-08-01 — HYPE absent from the research
    panel, HYPE mapped to the wrong asset, MKR still tracked after the Sky
    redenomination — were all "set once, never re-checked". A registry
    without a review date reproduces that failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Registry review cadence — see docs/UNIVERSE_DECISION_HYPE.md §4.
REVIEWED_AT = "2026-08-01"
REVIEW_CADENCE_DAYS = 90

# Sentinel: asset is deliberately known NOT to trade on this venue.
# Distinct from "no entry", which means nobody has checked.
NOT_LISTED = "__NOT_LISTED__"


@dataclass(frozen=True)
class VenueSpec:
    """How to talk to one venue, and how to read what it says back."""

    name: str
    market_type: str            # "spot" | "perp"
    # Units the venue reports in, so the consolidator can normalize to USD.
    oi_unit: str                # "coin" | "usd"
    volume_unit: str            # "usd" (quote notional) | "coin"
    # Whether we can actually route capital here. LAS must be computed on
    # accessible liquidity only; this is intentionally conservative and is a
    # product decision surface, not an engineering one.
    accessible: bool = True
    # Institutional weight for tie-breaks / reporting. Not used for price
    # aggregation (that is volume-weighted by construction).
    tier: int = 1
    notes: str = ""


VENUES: dict[str, VenueSpec] = {
    "binance_perp": VenueSpec(
        name="binance_perp",
        market_type="perp",
        oi_unit="coin",
        volume_unit="usd",
        tier=1,
        notes="fapi. quoteVolume is USD; openInterest is in coins.",
    ),
    "hyperliquid": VenueSpec(
        name="hyperliquid",
        market_type="perp",
        oi_unit="coin",
        volume_unit="usd",
        tier=1,
        notes="Native venue. dayNtlVlm is USD notional; openInterest in coins.",
    ),
    "bybit_perp": VenueSpec(
        name="bybit_perp",
        market_type="perp",
        oi_unit="coin",
        volume_unit="usd",
        tier=1,
        notes="category=linear. turnover24h is USD; openInterest in coins.",
    ),
    "binance_spot": VenueSpec(
        name="binance_spot",
        market_type="spot",
        oi_unit="usd",       # spot has no OI; consolidator ignores it
        volume_unit="usd",
        tier=1,
        notes="Spot reference. NO open interest, NO funding.",
    ),
}


# ── Explicit symbol map: asset -> venue -> venue symbol ────────────────────────
#
# Absence of a key means UNVERIFIED (the consolidator will skip and flag it).
# NOT_LISTED means verified-absent and is skipped silently.
#
# Every HYPE row below is the direct remediation of the 937x collision.

SYMBOL_MAP: dict[str, dict[str, str]] = {
    "BTC": {
        "binance_perp": "BTCUSDT", "binance_spot": "BTCUSDT",
        "bybit_perp": "BTCUSDT", "hyperliquid": "BTC",
    },
    "ETH": {
        "binance_perp": "ETHUSDT", "binance_spot": "ETHUSDT",
        "bybit_perp": "ETHUSDT", "hyperliquid": "ETH",
    },
    "SOL": {
        "binance_perp": "SOLUSDT", "binance_spot": "SOLUSDT",
        "bybit_perp": "SOLUSDT", "hyperliquid": "SOL",
    },
    "BNB": {
        "binance_perp": "BNBUSDT", "binance_spot": "BNBUSDT",
        "bybit_perp": "BNBUSDT", "hyperliquid": "BNB",
    },
    "XRP": {
        "binance_perp": "XRPUSDT", "binance_spot": "XRPUSDT",
        "bybit_perp": "XRPUSDT", "hyperliquid": "XRP",
    },
    "ADA": {
        "binance_perp": "ADAUSDT", "binance_spot": "ADAUSDT",
        "bybit_perp": "ADAUSDT", "hyperliquid": "ADA",
    },
    "AVAX": {
        "binance_perp": "AVAXUSDT", "binance_spot": "AVAXUSDT",
        "bybit_perp": "AVAXUSDT", "hyperliquid": "AVAX",
    },
    "DOT": {
        "binance_perp": "DOTUSDT", "binance_spot": "DOTUSDT",
        "bybit_perp": "DOTUSDT", "hyperliquid": "DOT",
    },
    "NEAR": {
        "binance_perp": "NEARUSDT", "binance_spot": "NEARUSDT",
        "bybit_perp": "NEARUSDT", "hyperliquid": "NEAR",
    },
    "SUI": {
        "binance_perp": "SUIUSDT", "binance_spot": "SUIUSDT",
        "bybit_perp": "SUIUSDT", "hyperliquid": "SUI",
    },
    "APT": {
        "binance_perp": "APTUSDT", "binance_spot": "APTUSDT",
        "bybit_perp": "APTUSDT", "hyperliquid": "APT",
    },
    # ── HYPE: the collision case. ─────────────────────────────────────────────
    # Binance SPOT has no HYPE market. HYPERUSDT on spot is Hyperlane
    # ($0.0558 on 2026-08-01) — mapping HYPE there caused the 937x error and
    # buried the asset at grade D through a +256% run. Verified absent.
    "HYPE": {
        "binance_spot": NOT_LISTED,
        "binance_perp": "HYPEUSDT",     # fapi DOES list the real HYPE perp
        "bybit_perp": "HYPEUSDT",
        "hyperliquid": "HYPE",          # native venue — 72% of open interest
    },
    "ARB": {
        "binance_perp": "ARBUSDT", "binance_spot": "ARBUSDT",
        "bybit_perp": "ARBUSDT", "hyperliquid": "ARB",
    },
    "OP": {
        "binance_perp": "OPUSDT", "binance_spot": "OPUSDT",
        "bybit_perp": "OPUSDT", "hyperliquid": "OP",
    },
    "POL": {
        "binance_perp": "POLUSDT", "binance_spot": "POLUSDT",
        "bybit_perp": "POLUSDT", "hyperliquid": "POL",
    },
    "STRK": {
        "binance_perp": "STRKUSDT", "binance_spot": "STRKUSDT",
        "bybit_perp": "STRKUSDT", "hyperliquid": "STRK",
    },
    "UNI": {
        "binance_perp": "UNIUSDT", "binance_spot": "UNIUSDT",
        "bybit_perp": "UNIUSDT", "hyperliquid": "UNI",
    },
    "AAVE": {
        "binance_perp": "AAVEUSDT", "binance_spot": "AAVEUSDT",
        "bybit_perp": "AAVEUSDT", "hyperliquid": "AAVE",
    },
    "LDO": {
        "binance_perp": "LDOUSDT", "binance_spot": "LDOUSDT",
        "bybit_perp": "LDOUSDT", "hyperliquid": "LDO",
    },
    "PENDLE": {
        "binance_perp": "PENDLEUSDT", "binance_spot": "PENDLEUSDT",
        "bybit_perp": "PENDLEUSDT", "hyperliquid": "PENDLE",
    },
    "LINK": {
        "binance_perp": "LINKUSDT", "binance_spot": "LINKUSDT",
        "bybit_perp": "LINKUSDT", "hyperliquid": "LINK",
    },
    "INJ": {
        "binance_perp": "INJUSDT", "binance_spot": "INJUSDT",
        "bybit_perp": "INJUSDT", "hyperliquid": "INJ",
    },
    "TIA": {
        "binance_perp": "TIAUSDT", "binance_spot": "TIAUSDT",
        "bybit_perp": "TIAUSDT", "hyperliquid": "TIA",
    },
    "ONDO": {
        "binance_perp": "ONDOUSDT", "binance_spot": "ONDOUSDT",
        "bybit_perp": "ONDOUSDT", "hyperliquid": "ONDO",
    },
    # ── MKR: redenominated to SKY. ────────────────────────────────────────────
    # CoinGecko `maker` reports market cap $0 and $83k/day volume on
    # 2026-08-01; the live asset is SKY ($1.30B cap). Binance spot MKRUSDT
    # still prints ($1813.70) but diverges 41% from CoinGecko and trades
    # $440k/day — a dying market. No MKR perp exists on fapi.
    # Left mapped so the integrity check keeps SEEING it and keeps failing;
    # silently deleting the row would hide the problem. Universe migration
    # MKR -> SKY is a product decision (see docs/UNIVERSE_DECISION_HYPE.md
    # Appendix A for the intake template; FTM->Sonic is the precedent, already
    # excluded under inclusion-standard criterion 5).
    "MKR": {
        "binance_spot": "MKRUSDT",
        "binance_perp": NOT_LISTED,
        "bybit_perp": "MKRUSDT",
        "hyperliquid": "MKR",
    },
}


def venue_symbol(asset: str, venue: str) -> Optional[str]:
    """
    Venue-specific symbol for `asset`, or None if not listed / unverified.

    Returns None for BOTH "verified absent" and "never checked" — callers that
    need to distinguish should use `unverified_pairs()`.
    """
    sym = SYMBOL_MAP.get(asset.upper(), {}).get(venue)
    if sym is None or sym == NOT_LISTED:
        return None
    return sym


def venues_for(asset: str, accessible_only: bool = False) -> list[VenueSpec]:
    """Venues that carry `asset`, in registry order."""
    out = []
    for vname, spec in VENUES.items():
        if accessible_only and not spec.accessible:
            continue
        if venue_symbol(asset, vname):
            out.append(spec)
    return out


def unverified_pairs(assets: list[str]) -> list[tuple[str, str]]:
    """
    (asset, venue) pairs with no registry entry at all.

    These are the dangerous ones: nobody has confirmed presence OR absence,
    so a future refactor could template a symbol and reintroduce a collision.
    """
    out = []
    for a in assets:
        row = SYMBOL_MAP.get(a.upper(), {})
        for vname in VENUES:
            if vname not in row:
                out.append((a.upper(), vname))
    return out


def registry_age_days(today: Optional[str] = None) -> int:
    """Days since the registry was last reviewed."""
    from datetime import date

    y, m, d = (int(x) for x in REVIEWED_AT.split("-"))
    ref = date(y, m, d)
    if today:
        ty, tm, td = (int(x) for x in today.split("-"))
        now = date(ty, tm, td)
    else:
        now = date.today()
    return (now - ref).days
