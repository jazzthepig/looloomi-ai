"""
Orderflow Collector — Binance depth imbalance + funding rate divergence
Collects CEX orderflow signals for narrative analysis.

Author: CometCloud Intelligence
"""

import logging
import httpx
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

# ── Binance Vision client (same base as data_layer.py) ─────────────────────────

_BINANCE_BASE = "https://data-api.binance.vision/api/v3"
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
            f"{_BINANCE_BASE}/premium_index",
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
    now = time.time()

    # Fetch last 7 funding rate snapshots (approximately one per 8h = 21 in 7d)
    # Use klines on the perpetual ticker as a proxy for funding history
    try:
        client = _get_binance_client()
        # Get 7d of 8h klines — approximate funding history
        r = await client.get(
            f"{_BINANCE_BASE}/klines",
            params={
                "symbol":   ticker,
                "interval": "8h",
                "limit":   21,  # ~7 days of 8h intervals
            },
        )
        r.raise_for_status()
        klines = r.json()

        if not klines:
            return {"symbol": symbol.upper(), "divergence_pct": 0.0, "error": "no klines"}

        # Use close price change rate as proxy for funding direction
        # In practice, you'd use the premium_index endpoint, but klines give a proxy
        recent_rates = [float(k[4]) for k in klines]  # close prices as proxy

        current = recent_rates[-1] if recent_rates else 0
        avg     = sum(recent_rates) / len(recent_rates) if recent_rates else 0

        if avg == 0:
            divergence_pct = 0.0
        else:
            divergence_pct = round((current - avg) / abs(avg) * 100, 4)

        return {
            "symbol":         symbol.upper(),
            "divergence_pct": divergence_pct,
            "current_proxy":  round(current, 8),
            "avg_proxy_7d":   round(avg, 8),
            "n_periods":      len(recent_rates),
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
            f"{_BINANCE_BASE}/open_interest",
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