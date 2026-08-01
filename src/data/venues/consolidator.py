"""
Cross-venue consolidation.

Pure functions (`volume_weighted_median`, `consolidate`) carry all the logic and
are unit-tested without network. `fetch_consolidated` is a thin, failure-isolated
I/O shell around them.

Production invariants — each one exists because its absence caused an outage or
a silent wrong number:

  I1. One venue failing NEVER fails the consolidation. Every adapter is wrapped;
      exceptions and timeouts become a missing quote, not a raised error.
  I2. A wrong-asset mapping is REJECTED, not averaged in. Price consensus is a
      median; venues far from it are dropped and reported. This is what would
      have caught HYPE->Hyperlane (937x) automatically.
  I3. Nothing is ever fabricated. Zero usable venues returns None. Thin coverage
      returns a result flagged `degraded=True` with reduced confidence.
      (CLAUDE.md hard rule #9.)
  I4. Units are normalized at the adapter boundary, never in the caller.
  I5. Funding is never averaged across venues — the spread is the signal.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .registry import VENUES, VenueSpec, venue_symbol

log = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────

# Below this many agreeing venues the result is flagged degraded. Two venues can
# disagree but cannot arbitrate; three is the minimum for a real median.
MIN_VENUES_FOR_CONSENSUS = 3

# A venue whose price deviates from the consensus by more than this ratio is
# rejected as a bad mapping / stale market. 0.05 = 5%.
# Reference points measured 2026-08-01: healthy cross-venue dispersion on HYPE
# was 7bp (1.0007); the Hyperlane mis-mapping was 937x; the dying MKR spot
# market was 41% off. 5% separates real markets from broken ones with room.
OUTLIER_REJECT_RATIO = 0.05

# Dispersion (max/min of accepted prices, minus 1) at which confidence hits 0.
CONFIDENCE_ZERO_DISPERSION = 0.02      # 2%

HTTP_TIMEOUT = 8.0


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class VenueQuote:
    """One venue's view of one asset, already normalized to USD."""

    venue: str
    market_type: str            # "spot" | "perp"
    price: float
    volume_24h_usd: float = 0.0
    open_interest_usd: float = 0.0     # 0.0 for spot
    funding_rate: Optional[float] = None
    accessible: bool = True

    @property
    def turnover(self) -> Optional[float]:
        """volume / OI — how fast this venue's cohort recycles positions.

        Measured on HYPE 2026-08-01: Binance 1.78x (leverage churn) vs
        Hyperliquid 0.27x (position-takers). A 6.6x behavioural difference on
        the same asset at the same instant — the reason single-venue sourcing
        distorts even when it points at the right thing.
        """
        if not self.open_interest_usd:
            return None
        return self.volume_24h_usd / self.open_interest_usd


@dataclass
class ConsolidatedQuote:
    asset: str
    price: float
    volume_24h_usd: float
    open_interest_usd: float           # GROSS notional — see package docstring
    confidence: float                  # 0..1, from dispersion + venue count
    venues_used: list[str] = field(default_factory=list)
    venues_rejected: list[str] = field(default_factory=list)
    venues_failed: list[str] = field(default_factory=list)
    funding_by_venue: dict[str, float] = field(default_factory=dict)
    price_dispersion: float = 0.0      # max/min - 1 over accepted venues
    oi_concentration: float = 0.0      # HHI, 0..1 — 1.0 = all OI on one venue
    degraded: bool = False
    degraded_reason: str = ""

    @property
    def funding_spread(self) -> Optional[float]:
        """max - min funding across venues. The net-positioning signal that a
        single-venue read, or an average, destroys."""
        if len(self.funding_by_venue) < 2:
            return None
        vals = list(self.funding_by_venue.values())
        return max(vals) - min(vals)

    @property
    def accessible_volume_usd(self) -> float:
        """Alias kept explicit: LAS must be computed on liquidity we can route
        to, not on gross market volume."""
        return self.volume_24h_usd

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "price": self.price,
            "volume_24h_usd": self.volume_24h_usd,
            "open_interest_usd": self.open_interest_usd,
            "confidence": self.confidence,
            "venues_used": self.venues_used,
            "venues_rejected": self.venues_rejected,
            "venues_failed": self.venues_failed,
            "funding_by_venue": self.funding_by_venue,
            "funding_spread": self.funding_spread,
            "price_dispersion": self.price_dispersion,
            "oi_concentration": self.oi_concentration,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
        }


# ── Pure consolidation logic ──────────────────────────────────────────────────

def volume_weighted_median(pairs: list[tuple[float, float]]) -> float:
    """
    Volume-weighted median of (price, weight) pairs — the CME CF / Kaiko recipe.

    Median rather than mean so that a single venue printing a wrong price (or a
    wrong ASSET) cannot drag the consensus, and so that a large trade split into
    parts has no effect on the result.

    Zero/negative weights are treated as unweighted presence so a venue that
    reports no volume still votes on price.
    """
    pts = [(p, w) for p, w in pairs if p and p > 0]
    if not pts:
        raise ValueError("volume_weighted_median: no positive prices")
    if len(pts) == 1:
        return pts[0][0]

    if all(w <= 0 for _, w in pts):
        pts = [(p, 1.0) for p, _ in pts]
    else:
        floor = min((w for _, w in pts if w > 0), default=1.0) * 1e-6
        pts = [(p, w if w > 0 else floor) for p, w in pts]

    pts.sort(key=lambda x: x[0])
    total = sum(w for _, w in pts)
    half = total / 2.0
    cum = 0.0
    for i, (p, w) in enumerate(pts):
        cum += w
        if cum > half:
            return p
        if abs(cum - half) < 1e-12:
            # Exact split — average this price with the next for symmetry.
            return (p + pts[i + 1][0]) / 2.0 if i + 1 < len(pts) else p
    return pts[-1][0]


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        raise ValueError("median of empty")
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _confidence(dispersion: float, n_accepted: int) -> float:
    """Confidence from cross-venue agreement (Pyth's principle: the spread
    between independent sources IS the uncertainty) and from coverage depth."""
    if n_accepted <= 0:
        return 0.0
    disp_term = max(0.0, 1.0 - (dispersion / CONFIDENCE_ZERO_DISPERSION))
    coverage = min(1.0, n_accepted / float(MIN_VENUES_FOR_CONSENSUS))
    return round(max(0.0, min(1.0, disp_term * coverage)), 3)


def consolidate(asset: str, quotes: list[VenueQuote],
                failed: Optional[list[str]] = None) -> Optional[ConsolidatedQuote]:
    """
    Combine per-venue quotes into one view. Pure — no I/O.

    price   : volume-weighted median over accepted venues
    volume  : sum over accepted venues
    OI      : sum over accepted PERP venues (gross notional)
    funding : per-venue map, never averaged
    """
    failed = list(failed or [])
    usable = [q for q in quotes if q.price and q.price > 0]
    if not usable:
        return None

    rejected: list[str] = []
    accepted = usable

    # I2 — reject venues whose price is far from consensus. Needs >=3 venues:
    # with 2 disagreeing venues there is no majority to arbitrate, so we keep
    # both and let the dispersion flag it rather than guessing which is right.
    if len(usable) >= 3:
        ref = _median([q.price for q in usable])
        if ref > 0:
            keep, drop = [], []
            for q in usable:
                if abs(q.price - ref) / ref > OUTLIER_REJECT_RATIO:
                    drop.append(q)
                else:
                    keep.append(q)
            if keep:
                accepted, rejected = keep, [q.venue for q in drop]

    prices = [q.price for q in accepted]
    dispersion = (max(prices) / min(prices) - 1.0) if min(prices) > 0 else 0.0

    price = volume_weighted_median([(q.price, q.volume_24h_usd) for q in accepted])
    volume = sum(q.volume_24h_usd for q in accepted)
    oi = sum(q.open_interest_usd for q in accepted if q.market_type == "perp")

    ois = [q.open_interest_usd for q in accepted
           if q.market_type == "perp" and q.open_interest_usd > 0]
    hhi = round(sum((v / sum(ois)) ** 2 for v in ois), 4) if ois else 0.0

    funding = {q.venue: q.funding_rate for q in accepted if q.funding_rate is not None}

    degraded, reason = False, ""
    if len(accepted) < MIN_VENUES_FOR_CONSENSUS:
        degraded = True
        reason = f"only {len(accepted)} venue(s) responded (need {MIN_VENUES_FOR_CONSENSUS})"
    if rejected:
        degraded = True
        r = f"rejected outlier venue(s): {', '.join(rejected)}"
        reason = f"{reason}; {r}" if reason else r
    if dispersion > OUTLIER_REJECT_RATIO:
        degraded = True
        d = f"price dispersion {dispersion:.2%} exceeds {OUTLIER_REJECT_RATIO:.0%}"
        reason = f"{reason}; {d}" if reason else d

    conf = _confidence(dispersion, len(accepted))
    if rejected:
        conf = round(conf * 0.5, 3)

    return ConsolidatedQuote(
        asset=asset.upper(),
        price=price,
        volume_24h_usd=volume,
        open_interest_usd=oi,
        confidence=conf,
        venues_used=[q.venue for q in accepted],
        venues_rejected=rejected,
        venues_failed=failed,
        funding_by_venue=funding,
        price_dispersion=round(dispersion, 6),
        oi_concentration=hhi,
        degraded=degraded,
        degraded_reason=reason,
    )


# ── Venue adapters (I/O). Each normalizes to USD and never raises. ────────────

async def _binance_perp(c: httpx.AsyncClient, sym: str) -> Optional[VenueQuote]:
    t, oi, pi = await asyncio.gather(
        c.get("https://fapi.binance.com/fapi/v1/ticker/24hr", params={"symbol": sym}),
        c.get("https://fapi.binance.com/fapi/v1/openInterest", params={"symbol": sym}),
        c.get("https://fapi.binance.com/fapi/v1/premiumIndex", params={"symbol": sym}),
        return_exceptions=True,
    )
    if isinstance(t, Exception) or t.status_code != 200:
        return None
    d = t.json()
    price = float(d["lastPrice"])
    if price <= 0:
        return None
    oi_usd = 0.0
    if not isinstance(oi, Exception) and oi.status_code == 200:
        oi_usd = float(oi.json().get("openInterest", 0)) * price   # coin -> usd
    fr = None
    if not isinstance(pi, Exception) and pi.status_code == 200:
        raw = pi.json().get("lastFundingRate")
        fr = float(raw) if raw is not None else None
    return VenueQuote("binance_perp", "perp", price,
                      float(d.get("quoteVolume", 0)), oi_usd, fr)


async def _binance_spot(c: httpx.AsyncClient, sym: str) -> Optional[VenueQuote]:
    r = await c.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": sym})
    if r.status_code != 200:
        return None
    d = r.json()
    price = float(d.get("lastPrice", 0))
    if price <= 0:
        return None
    return VenueQuote("binance_spot", "spot", price, float(d.get("quoteVolume", 0)), 0.0, None)


async def _hyperliquid(c: httpx.AsyncClient, sym: str) -> Optional[VenueQuote]:
    r = await c.post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"})
    if r.status_code != 200:
        return None
    payload = r.json()
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    meta, ctxs = payload[0].get("universe", []), payload[1]
    for i, m in enumerate(meta):
        if m.get("name") != sym or i >= len(ctxs):
            continue
        ctx = ctxs[i]
        price = float(ctx.get("markPx") or 0)
        if price <= 0:
            return None
        oi_usd = float(ctx.get("openInterest") or 0) * price     # coin -> usd
        fr = ctx.get("funding")
        return VenueQuote("hyperliquid", "perp", price,
                          float(ctx.get("dayNtlVlm") or 0), oi_usd,
                          float(fr) if fr is not None else None)
    return None


async def _bybit_perp(c: httpx.AsyncClient, sym: str) -> Optional[VenueQuote]:
    r = await c.get("https://api.bybit.com/v5/market/tickers",
                    params={"category": "linear", "symbol": sym})
    if r.status_code != 200:
        return None
    lst = (r.json().get("result") or {}).get("list") or []
    if not lst:
        return None
    d = lst[0]
    price = float(d.get("lastPrice", 0))
    if price <= 0:
        return None
    fr = d.get("fundingRate")
    return VenueQuote("bybit_perp", "perp", price,
                      float(d.get("turnover24h", 0) or 0),
                      float(d.get("openInterest", 0) or 0) * price,
                      float(fr) if fr not in (None, "") else None)


_ADAPTERS = {
    "binance_perp": _binance_perp,
    "binance_spot": _binance_spot,
    "hyperliquid": _hyperliquid,
    "bybit_perp": _bybit_perp,
}


async def _safe(name: str, fn, c, sym) -> tuple[str, Optional[VenueQuote]]:
    """I1 — a venue may fail, time out, or return garbage. It may not raise."""
    try:
        return name, await asyncio.wait_for(fn(c, sym), timeout=HTTP_TIMEOUT)
    except Exception as e:                                   # noqa: BLE001
        log.warning("venue %s failed for %s: %s", name, sym, e)
        return name, None


async def fetch_consolidated(asset: str, accessible_only: bool = False,
                             client: Optional[httpx.AsyncClient] = None
                             ) -> Optional[ConsolidatedQuote]:
    """Fetch `asset` across all registered venues concurrently and consolidate."""
    targets = []
    for vname, spec in VENUES.items():
        if accessible_only and not spec.accessible:
            continue
        sym = venue_symbol(asset, vname)
        if sym and vname in _ADAPTERS:
            targets.append((vname, _ADAPTERS[vname], sym))
    if not targets:
        return None

    own = client is None
    c = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    try:
        results = await asyncio.gather(*[_safe(n, f, c, s) for n, f, s in targets])
    finally:
        if own:
            await c.aclose()

    quotes = [q for _, q in results if q is not None]
    failed = [n for n, q in results if q is None]
    return consolidate(asset, quotes, failed=failed)
