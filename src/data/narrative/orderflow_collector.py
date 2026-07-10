"""
Orderflow Collector — Binance depth imbalance + funding rate divergence
Collects CEX orderflow signals for narrative analysis.

Author: CometCloud Intelligence
"""

import logging
import httpx
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

# ── Binance FUTURES client (perp signals — spot data-api 400s on perp-only tokens
#    like HYPE and can't serve real funding/OI; fapi is the correct venue) ────────

_BINANCE_BASE = "https://fapi.binance.com/fapi/v1"
_binance_client: httpx.AsyncClient | None = None

def _get_binance_client() -> httpx.AsyncClient:
    global _binance_client
    if _binance_client is None or _binance_client.is_closed:
        _binance_client = httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=20))
    return _binance_client

# Symbol mapping (same as data_layer.py for consistency)
_SYMBOL_MAP = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "BNB": "BNBUSDT", "AVAX": "AVAXUSDT", "ARB": "ARBUSDT",
    "OP":  "OPUSDT",  "LINK": "LINKUSDT", "UNI": "UNIUSDT",
    "AAVE": "AAVEUSDT", "DOT": "DOTUSDT", "NEAR": "NEARUSDT",
    "SUI": "SUIUSDT", "APT": "APTUSDT", "HYPE": "HYPEUSDT",
}


def _to_binance_ticker(symbol: str) -> str:
    return _SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")


# ── Orderbook imbalance ────────────────────────────────────────────────────────

async def fetch_orderbook_imbalance(symbol: str, limit: int = 20) -> dict:
    """
    Compute bid-imbalance from Binance depth.
    bid_imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)

    Returns: {bid_imbalance, bid_vol, ask_vol, spread, best_bid, best_ask}
    """
    ticker = _to_binance_ticker(symbol)
    try:
        client = _get_binance_client()
        r = await client.get(
            f"{_BINANCE_BASE}/depth",
            params={"symbol": ticker, "limit": limit},
        )
        r.raise_for_status()
        data = r.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        total   = bid_vol + ask_vol

        imbalance = 0.0 if total == 0 else (bid_vol - ask_vol) / total

        return {
            "symbol":        symbol.upper(),
            "bid_imbalance": round(imbalance, 4),
            "bid_vol":       round(bid_vol, 2),
            "ask_vol":       round(ask_vol, 2),
            "total_vol":     round(total, 2),
            "best_bid":      float(bids[0][0]) if bids else None,
            "best_ask":      float(asks[0][0]) if asks else None,
            "spread":        round(float(asks[0][0]) - float(bids[0][0]), 8) if (bids and asks) else None,
            "n_levels":      limit,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        _logger.warning(f"[orderflow_collector] Binance depth failed for {symbol}: {e}")
        return {"symbol": symbol.upper(), "bid_imbalance": 0.0, "error": str(e)}


# ── Funding rate from Binance perpetual ───────────────────────────────────────

async def fetch_funding_rate(symbol: str) -> dict:
    """
    Fetch current funding rate for a perpetual future.
    Returns: {funding_rate (annualised %), next_funding_time, mark_price}
    """
    ticker = _to_binance_ticker(symbol)
    try:
        client = _get_binance_client()
        # Premium index ticker for funding rate
        r = await client.get(
            f"{_BINANCE_BASE}/premiumIndex",
            params={"symbol": ticker},
        )
        r.raise_for_status()
        data = r.json()

        funding_rate = float(data.get("lastFundingRate", 0) or 0)
        # Annualise: funding_rate * 3 * 365 (8h intervals)
        annualised   = round(funding_rate * 3 * 365 * 100, 4)

        return {
            "symbol":       symbol.upper(),
            "funding_rate": funding_rate,
            "annualised_pct": annualised,
            "mark_price":   float(data.get("markPrice", 0) or 0),
            "index_price":  float(data.get("indexPrice", 0) or 0),
            "next_funding": data.get("nextFundingTime"),
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        _logger.warning(f"[orderflow_collector] Funding rate failed for {symbol}: {e}")
        return {"symbol": symbol.upper(), "funding_rate": 0.0, "error": str(e)}


# ── Funding rate divergence vs 7d avg ─────────────────────────────────────────

async def fetch_funding_divergence(symbol: str) -> dict:
    """
    Compute funding rate divergence: current vs 7d average.
    Positive = funding higher than avg (bearish signal if too high)
    Returns: {divergence_pct, current_rate, avg_rate_7d}
    """
    import asyncio, time

    ticker = _to_binance_ticker(symbol)

    # Use REAL funding history (fapi/v1/fundingRate) — the actual signal, not a price proxy.
    try:
        client = _get_binance_client()
        r = await client.get(
            f"{_BINANCE_BASE}/fundingRate",
            params={"symbol": ticker, "limit": 21},   # ~7 days of 8h funding settlements
        )
        r.raise_for_status()
        hist = r.json()

        rates = [float(x.get("fundingRate", 0) or 0) for x in hist]
        if not rates:
            return {"symbol": symbol.upper(), "divergence_pct": 0.0, "error": "no funding history"}

        current = rates[-1]
        avg     = sum(rates) / len(rates)
        # divergence in std units — how stretched is current funding vs its own 7d distribution
        import statistics
        sd = statistics.pstdev(rates) if len(rates) > 1 else 0.0
        divergence_z = round((current - avg) / sd, 4) if sd > 0 else 0.0

        return {
            "symbol":         symbol.upper(),
            "divergence_pct": round((current - avg) * 3 * 365 * 100, 4),  # annualized bps gap
            "divergence_z":   divergence_z,
            "current_funding": round(current, 8),
            "avg_funding_7d":  round(avg, 8),
            "n_periods":      len(rates),
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        _logger.warning(f"[orderflow_collector] Funding divergence failed for {symbol}: {e}")
        return {"symbol": symbol.upper(), "divergence_pct": 0.0, "error": str(e)}


# ── OI (Open Interest) change from Binance ────────────────────────────────────

async def fetch_oi_change(symbol: str) -> dict:
    """
    Fetch open interest from Binance usdm futures.
    OI change is a leading indicator for direction and momentum.

    Returns: {oi_usd, oi_change_pct_24h, symbol}
    """
    ticker = _to_binance_ticker(symbol)
    try:
        client = _get_binance_client()
        r = await client.get(
            f"{_BINANCE_BASE}/openInterest",
            params={"symbol": ticker},
        )
        r.raise_for_status()
        data = r.json()

        oi_base = float(data.get("openInterest", 0) or 0)
        # open_interest is in base asset (e.g. BTC), multiply by approx price
        # We don't have price here — return raw + note that caller should multiply
        return {
            "symbol":          symbol.upper(),
            "oi_base_asset":   round(oi_base, 4),
            "oi_change_pct_24h": 0.0,  # requires historical comparison
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "note":            "multiply oi_base_asset by price for USD value",
        }

    except Exception as e:
        _logger.warning(f"[orderflow_collector] OI fetch failed for {symbol}: {e}")
        return {"symbol": symbol.upper(), "oi_base_asset": 0.0, "error": str(e)}


# ── Batch orderflow for multiple symbols ───────────────────────────────────────

import asyncio

async def batch_orderflow(symbols: list[str]) -> dict[str, dict]:
    """
    Fetch orderbook imbalance + funding divergence for multiple symbols in parallel.
    Returns: {symbol: {orderflow_data}}
    """
    async def _one(symbol: str) -> tuple[str, dict]:
        ob = await fetch_orderbook_imbalance(symbol, limit=20)
        fd = await fetch_funding_divergence(symbol)
        return symbol, {**ob, **fd}

    results = {}
    for sym, data in await asyncio.gather(*[_one(s) for s in symbols]):
        results[sym] = data
    return results


if __name__ == "__main__":
    async def _test():
        logging.basicConfig(level=logging.INFO)
        print("=== BTC Orderbook Imbalance ===")
        print(await fetch_orderbook_imbalance("BTC"))
        print("\n=== Funding Rate (BTC) ===")
        print(await fetch_funding_rate("BTC"))
        print("\n=== Batch (BTC, ETH, SOL) ===")
        print(await batch_orderflow(["BTC", "ETH", "SOL"]))

    asyncio.run(_test())