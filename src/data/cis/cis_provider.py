"""
CIS Data Provider - Real-time CIS scoring from market data
===========================================================
Fetches real market data and calculates CIS scores using the scoring engine.
v4.1: Continuous scoring functions, unified grading, LAS.

Author: Seth
"""

import math
import statistics
import httpx
import asyncio
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys
import os
import time

_logger = logging.getLogger(__name__)


# One-shot warn flag — see the GITHUB_TOKEN note in the dev-activity fetcher.
_GH_TOKEN_WARNED = False
# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# CoinGecko API base
CG_PRO_BASE = "https://pro-api.coingecko.com/api/v3"
CG_API_KEY = os.getenv("COINGECKO_API_KEY", "")

# Upstash Redis — persistent L2 cache across Railway deploys
# Mirrors the pattern in data_layer.py. Gracefully no-ops if not configured.
_UPSTASH_URL   = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

# Simons feedback loop — IC-based pillar weight multiplier cache
# Populated once per scoring run from cis:factor_performance (30min TTL).
_ic_mult_cache: dict = {"data": None, "expires": 0.0}

import json as _json

async def _upstash_get(key: str):
    """Read from Upstash REST. Returns None on miss or if not configured."""
    if not _UPSTASH_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as cl:
            r = await cl.get(
                f"{_UPSTASH_URL}/get/{key}",
                headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
            )
            if r.status_code == 200:
                raw = r.json().get("result")
                return _json.loads(raw) if raw else None
    except Exception:
        pass
    return None

async def _upstash_set(key: str, val, ttl: int) -> bool:
    """Write to Upstash with TTL. Fire-and-forget — never blocks on failure."""
    if not _UPSTASH_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as cl:
            r = await cl.post(
                f"{_UPSTASH_URL}/set/{key}",
                content=_json.dumps(val),
                headers={
                    "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                    "Content-Type": "application/json",
                },
                params={"EX": ttl},
            )
            return r.status_code == 200
    except Exception:
        return False


async def _refresh_ic_multipliers() -> dict:
    """
    Simons feedback loop — reads cis:factor_performance from Redis and computes
    per-pillar IC strength multipliers for the current scoring run.

    Returns {"F": float, "M": float, "O": float, "S": float, "A": float}.
    Multiplier formula: 1.0 + clamp(mean_active_IC × 2.5, -0.30, +0.30)
      • IC = 0.10 (minimum active)  →  1.25x weight boost
      • IC = 0.20                   →  1.50x weight boost
      • IC = -0.10                  →  0.75x dampen
    Only "active" factors (|r| > 0.10, sample ≥ 10) contribute.
    Neutral {k: 1.0} returned on any error — scoring unaffected until data exists.
    Cache TTL: 1800s (matches Mac Mini scheduler frequency).
    """
    import time as _time
    now = _time.time()

    # Serve from cache if still valid
    if _ic_mult_cache["data"] is not None and now < _ic_mult_cache["expires"]:
        return _ic_mult_cache["data"]

    neutral = {"F": 1.0, "M": 1.0, "O": 1.0, "S": 1.0, "A": 1.0}

    try:
        fp = await _upstash_get("cis:factor_performance")
        if not fp or not isinstance(fp, dict):
            _ic_mult_cache.update({"data": neutral, "expires": now + 1800})
            return neutral

        # Factor ID → pillar mapping — MUST match _PILLAR_COMPONENT_MAP in performance.py exactly
        _factor_to_pillar: dict[str, str] = {
            # F pillar
            "market_cap": "F", "tvl": "F", "volume_24h": "F",
            "supply_inflation": "F", "fdv_ratio": "F", "dev_activity": "F",
            "eodhd_pe": "F", "eodhd_revenue_growth": "F",
            # M pillar
            "momentum_30d": "M", "momentum_7d_sparkline": "M", "ath_distance": "M",
            # O pillar
            "volatility_annualised": "O", "ath_drawdown": "O", "tvl_risk_score": "O",
            "exchange_hhi": "O", "funding_rate": "O", "oi_mcap_ratio": "O",
            # S pillar
            "fear_greed_index": "S", "vix_inverse": "S", "category_divergence": "S",
            "vol_regime": "S", "momentum_structure": "S", "beta_dxy_vix": "S",
            "trending_rank": "S", "recovery_bonus": "S",
            # A pillar
            "btc_divergence": "A", "spy_divergence": "A",
            "class_independence": "A", "size_efficiency": "A", "correlation_discount": "A",
        }

        pillar_ics: dict[str, list[float]] = {"F": [], "M": [], "O": [], "S": [], "A": []}
        for factor_id, data in fp.items():
            if factor_id.startswith("_"):
                continue  # skip _meta entry
            if not isinstance(data, dict):
                continue
            pillar = _factor_to_pillar.get(factor_id)
            if not pillar:
                continue
            r = data.get("pearson_r")
            status = data.get("status", "probationary")
            sample = data.get("sample_size", 0) or 0
            # Only trust active factors with meaningful sample size
            if status == "active" and isinstance(r, (int, float)) and sample >= 10:
                pillar_ics[pillar].append(float(r))

        result: dict[str, float] = {}
        active_count = 0
        for pillar, ics in pillar_ics.items():
            if ics:
                mean_r = sum(ics) / len(ics)
                # ±30% max weight shift per pillar
                mult = 1.0 + max(-0.30, min(0.30, mean_r * 2.5))
                active_count += len(ics)
            else:
                mult = 1.0
            result[pillar] = round(mult, 4)

        if active_count > 0:
            _logger.info(
                f"[CIS·Simons] IC multipliers applied — {active_count} active factors: "
                + " ".join(f"{k}={v:.3f}" for k, v in result.items())
            )
        else:
            _logger.debug("[CIS·Simons] No active IC factors yet — neutral weights used")

        _ic_mult_cache.update({"data": result, "expires": now + 1800})
        return result

    except Exception as e:
        _logger.warning(f"[CIS·Simons] IC multiplier load failed: {e} — using neutral weights")
        _ic_mult_cache.update({"data": neutral, "expires": now + 300})
        return neutral

def _cg_base() -> str:
    """Use Pro API if key is set, otherwise free tier."""
    return CG_PRO_BASE if CG_API_KEY else "https://api.coingecko.com/api/v3"

def _cg_headers() -> dict:
    """Attach Pro API key header if configured."""
    return {"x-cg-pro-api-key": CG_API_KEY} if CG_API_KEY else {}

# Crypto assets config - maps to CoinGecko IDs
# Universe aligned with CometCloud Inclusion Standard v2.0 (May 2026)
# 10 hard gates: Liquidity($10M/30d+3tier1), MarketCap($500M+FDV), CG Rank(top150),
# Data Completeness(90d+OHLCV), Custody(institutional), Regulatory,
# TokenMechanics(circ/total>=0.30/inflation<20%/yr), TradingHistory(180d),
# ProtocolIntegrity, FastTrack($1B+FDV+custody+tier1listing). Ref: INCLUSION_STANDARD.md v2.0
CRYPTO_ASSETS = {
        # L1 — Layer 1 blockchains
    "BTC":   {"coingecko": "bitcoin",                  "name": "Bitcoin",       "class": "L1"},
    "ETH":   {"coingecko": "ethereum",                 "name": "Ethereum",      "class": "L1"},
    "SOL":   {"coingecko": "solana",                   "name": "Solana",         "class": "L1"},
    "BNB":   {"coingecko": "binancecoin",              "name": "BNB",            "class": "L1"},
    "XRP":   {"coingecko": "ripple",                   "name": "XRP",            "class": "L1"},
    "ADA":   {"coingecko": "cardano",                  "name": "Cardano",        "class": "L1"},
    "AVAX":  {"coingecko": "avalanche-2",              "name": "Avalanche",      "class": "L1"},
    "DOT":   {"coingecko": "polkadot",                 "name": "Polkadot",       "class": "L1"},
    "NEAR":  {"coingecko": "near",                     "name": "NEAR Protocol",  "class": "L1"},
    "SUI":   {"coingecko": "sui",                     "name": "Sui",            "class": "L1"},
    "APT":   {"coingecko": "aptos",                   "name": "Aptos",          "class": "L1"},
    # Hyperliquid — mcap ~#11, ~$13.5B FDV. Passes all 9 gates. Fast-track eligible.
    "HYPE":  {"coingecko": "hyperliquid",              "name": "Hyperliquid",   "class": "L1"},
    # L2 — Layer 2 scaling
    "ARB":   {"coingecko": "arbitrum",                 "name": "Arbitrum",       "class": "L2"},
    "OP":    {"coingecko": "optimism",                 "name": "Optimism",       "class": "L2"},
    "POL":   {"coingecko": "polygon-ecosystem-token",  "name": "Polygon",        "class": "L2"},
    "STRK":  {"coingecko": "starknet",                 "name": "StarkNet",       "class": "L2"},
    # DeFi — Decentralized Finance
    "UNI":   {"coingecko": "uniswap",                 "name": "Uniswap",        "class": "DeFi"},
    "AAVE":  {"coingecko": "aave",                    "name": "Aave",           "class": "DeFi"},
    "LDO":   {"coingecko": "lido-dao",                "name": "Lido DAO",       "class": "DeFi"},
    "PENDLE":{"coingecko": "pendle",                   "name": "Pendle",         "class": "DeFi"},
    # Infrastructure
    "LINK":  {"coingecko": "chainlink",                "name": "Chainlink",      "class": "Infrastructure"},
    "INJ":   {"coingecko": "injective-protocol",      "name": "Injective",      "class": "Infrastructure"},
    "TIA":   {"coingecko": "celestia",                 "name": "Celestia",       "class": "Infrastructure"},
    # RWA — Real World Assets
    "ONDO":  {"coingecko": "ondo-finance",            "name": "Ondo Finance",   "class": "RWA"},
    "MKR":   {"coingecko": "maker",                   "name": "Maker",           "class": "RWA"},
}

# 24 crypto assets. Universe v2.0 total: 24 crypto + 10 US Equity + 6 Bonds + 3 Commodities = 43

# US Equities - yfinance symbols
US_EQUITIES = {
    "SPY":  {"yfinance": "SPY",  "name": "S&P 500 ETF",       "class": "US Equity"},
    "QQQ":  {"yfinance": "QQQ",  "name": "Nasdaq 100 ETF",    "class": "US Equity"},
    "AAPL": {"yfinance": "AAPL", "name": "Apple",             "class": "US Equity"},
    "MSFT": {"yfinance": "MSFT", "name": "Microsoft",         "class": "US Equity"},
    "NVDA": {"yfinance": "NVDA", "name": "NVIDIA",            "class": "US Equity"},
    "GOOGL":{"yfinance": "GOOGL","name": "Alphabet",          "class": "US Equity"},
    "AMZN": {"yfinance": "AMZN", "name": "Amazon",            "class": "US Equity"},
    "META": {"yfinance": "META", "name": "Meta",              "class": "US Equity"},
    "TSLA": {"yfinance": "TSLA", "name": "Tesla",             "class": "US Equity"},
    "XLF":  {"yfinance": "XLF",  "name": "Financial Select",  "class": "US Equity"},
}

# Bonds - yfinance symbols
BONDS = {
    "TLT": {"yfinance": "TLT", "name": "20+ Year Treasury Bond ETF",    "class": "US Bond"},
    "IEF": {"yfinance": "IEF", "name": "7-10 Year Treasury Bond ETF",   "class": "US Bond"},
    "SHY": {"yfinance": "SHY", "name": "1-3 Year Treasury Bond ETF",    "class": "US Bond"},
    "TIP": {"yfinance": "TIP", "name": "TIPS ETF",                      "class": "US Bond"},
    "HYG": {"yfinance": "HYG", "name": "High Yield Bond ETF",           "class": "US Bond"},
    "LQD": {"yfinance": "LQD", "name": "Investment Grade Bond ETF",     "class": "US Bond"},
}

# Commodities - yfinance symbols
COMMODITIES = {
    "GLD":  {"yfinance": "GLD",  "name": "Gold ETF",           "class": "Commodity"},
    "SLV":  {"yfinance": "SLV",  "name": "Silver ETF",         "class": "Commodity"},
    "USO":  {"yfinance": "USO",  "name": "Oil ETF",            "class": "Commodity"},
    "UNG":  {"yfinance": "UNG",  "name": "Natural Gas ETF",    "class": "Commodity"},
    "CPER": {"yfinance": "CPER", "name": "Copper ETF",         "class": "Commodity"},
    "DBA":  {"yfinance": "DBA",  "name": "Agriculture ETF",    "class": "Commodity"},
}

# FX — Currency ETFs (yfinance)
FX = {
    "UUP": {"yfinance": "UUP", "name": "US Dollar ETF",    "class": "FX"},
    "FXE": {"yfinance": "FXE", "name": "Euro ETF",         "class": "FX"},
    "FXY": {"yfinance": "FXY", "name": "Yen ETF",          "class": "FX"},
    "FXI": {"yfinance": "FXI", "name": "China Large Cap",  "class": "FX"},
}

# Real Estate — REIT ETFs (yfinance)
REAL_ESTATE = {
    "VNQ":  {"yfinance": "VNQ",  "name": "US REIT ETF",       "class": "Real Estate"},
    "IYR":  {"yfinance": "IYR",  "name": "US Real Estate ETF", "class": "Real Estate"},
    "VNQI": {"yfinance": "VNQI", "name": "Intl REIT ETF",      "class": "Real Estate"},
}

# EM Equity — Emerging Market ETFs (yfinance)
EM_EQUITY = {
    "EEM":  {"yfinance": "EEM",  "name": "EM ETF",            "class": "EM Equity"},
    "VWO":  {"yfinance": "VWO",  "name": "Vanguard EM ETF",   "class": "EM Equity"},
    "INDA": {"yfinance": "INDA", "name": "India ETF",         "class": "EM Equity"},
    "EWZ":  {"yfinance": "EWZ",  "name": "Brazil ETF",        "class": "EM Equity"},
}

# Combined assets config
ASSETS_CONFIG = {**CRYPTO_ASSETS, **US_EQUITIES, **BONDS, **COMMODITIES, **FX, **REAL_ESTATE, **EM_EQUITY}

# GitHub repo paths for developer-activity tracking (Phase 2B)
# Format: asset_id -> "owner/repo"
# Covers assets in CRYPTO_ASSETS v2.0 with active public repos
GITHUB_REPOS: Dict[str, str] = {
    "BTC":  "bitcoin/bitcoin",
    "ETH":  "ethereum/go-ethereum",
    "SOL":  "solana-labs/solana",
    "BNB":  "bnb-chain/op-geth",           # BNB Chain (Beacon Chain)
    "XRP":  "XRPLF/rippled",
    "ADA":  "IntersectMBO/cardano-node",
    "AVAX": "ava-labs/avalanchego",
    "DOT":  "paritytech/polkadot",
    "NEAR": "near/nearcore",
    "SUI":  "MystenLabs/sui",
    "APT":  "aptos-labs/aptos-core",
    # HYPE: no public GitHub repo (Hyperliquid is proprietary/closed source)
    "ARB":  "OffchainLabs/nitro",
    "OP":   "ethereum-optimism/optimism",
    "POL":  "0xPolygon/polygon-cli",
    "STRK": "starkware-libs/cairo",
    "UNI":  "Uniswap/v4-core",
    "AAVE": "aave/aave-v3-core",
    "LDO":  "lidofinance/lido-dao",
    "PENDLE":"pendle-finance/core-v2",
    "LINK": "smartcontractkit/chainlink",
    "INJ":  "InjectiveLabs/injective-core",
    "TIA":  "celestiaorg/celestia-node",
}

# Cache
_cache: Dict = {}
_cache_ttl = 300  # 5 minutes


def _cache_get(key: str) -> Optional[Any]:
    if key in _cache:
        val, ts = _cache[key]
        if datetime.now().timestamp() - ts < _cache_ttl:
            return val
    return None


def _cache_set(key: str, val: Any):
    _cache[key] = (val, datetime.now().timestamp())
    return val


# === Beta Calculation for S Pillar ===
# ── The macro factors are GLOBAL — fetch them once, not once per asset ───────
# (2026-08-12, S-148.) DXY / VIX / TNX are the same three series for every asset
# in the panel, and `_betas_in_thread` is called PER ASSET. So 24 assets produced
# 72 yfinance calls per cycle. When Yahoo stops answering — measured 2026-08-12,
# all three returning "possibly delisted; no price data found" — each call still
# burns ~10s, so one cycle spent roughly twelve minutes failing, and the Mac log
# filled with one ERROR line every ten seconds around the clock.
#
# This is the third instance of the same shape today: a GLOBAL quantity fetched
# PER ITEM. GitHub's dev-activity ran 25 repos unauthenticated; CryptoPanic's one
# global RSS was fetched once per asset. In each case the cache sat downstream of
# the network call, so it deduplicated the parsing and never the request.
#
# The breaker matters as much as the cache: without it, a Yahoo outage costs 72
# attempts per cycle forever, and the retry pressure is indistinguishable from the
# outage in the logs.
_FACTOR_CACHE: dict = {}                 # name → (ts, rets|None)
_FACTOR_TTL_S = 3600.0                   # daily bars; refetching sooner buys nothing
_FACTOR_BREAKER: dict = {"until": 0.0}
_FACTOR_COOLDOWN_S = 1800.0


async def _fetch_factor_rets(symbol: str, name: str) -> tuple[str, list | None]:
    """Fetch factor returns in thread pool (yfinance is sync-blocking).

    Cached globally and breaker-guarded — see the note above. A cache MISS that
    returns None is stored too: "we asked and Yahoo had nothing" must cost one
    attempt per TTL, not one per asset."""
    import time as _t
    now = _t.time()
    hit = _FACTOR_CACHE.get(name)
    if hit is not None and (now - hit[0]) < _FACTOR_TTL_S:
        return name, hit[1]
    if now < _FACTOR_BREAKER["until"]:
        return name, (hit[1] if hit else None)

    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="35d")
        if len(hist) < 20:
            # Negative-cache the miss. Yahoo answering "nothing" for VIX is a real
            # answer about Yahoo, and asking 71 more times will not change it.
            _FACTOR_CACHE[name] = (now, None)
            _FACTOR_BREAKER["until"] = now + _FACTOR_COOLDOWN_S
            _logger.warning(
                "[Beta] yfinance returned no data for %s — negative-cached and "
                "breaker open for %.0fs. These three factors are GLOBAL; without "
                "this, a Yahoo outage costs 3 calls x every asset, every cycle.",
                symbol, _FACTOR_COOLDOWN_S)
            return name, None
        prices = hist['Close'].values
        rets = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                rets.append((prices[i] - prices[i-1]) / prices[i-1])
        out = rets if len(rets) >= 15 else None
        _FACTOR_CACHE[name] = (now, out)
        return name, out
    except Exception as e:
        # Cache the failure too, and open the breaker. Without this the next asset
        # in the loop retries immediately and the exception rate IS the load.
        _FACTOR_CACHE[name] = (now, None)
        _FACTOR_BREAKER["until"] = now + _FACTOR_COOLDOWN_S
        _logger.warning("[Beta] yfinance factor %s failed: %s — breaker open %.0fs",
                        symbol, e, _FACTOR_COOLDOWN_S)
        return name, None


async def _betas_in_thread(asset_id: str, asset_price_30d: list) -> dict:
    """Run the full beta calc (numpy + yfinance sync calls) in thread pool."""
    import numpy as np

    if len(asset_price_30d) < 20:
        return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "insufficient_data"}

    asset_returns = [
        (asset_price_30d[i] - asset_price_30d[i-1]) / asset_price_30d[i-1]
        for i in range(1, len(asset_price_30d))
        if asset_price_30d[i-1] > 0
    ]
    if len(asset_returns) < 15:
        return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "insufficient_data"}

    # Fetch 3 factors concurrently in thread pool
    results = await asyncio.gather(
        _fetch_factor_rets("DX-Y.NYB", "dxy"),
        _fetch_factor_rets("^VIX", "vix"),
        _fetch_factor_rets("^TNX", "tnx"),
    )
    factors = {name: rets for name, rets in results if rets is not None}

    if "dxy" not in factors and "vix" not in factors:
        return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "insufficient_data"}

    def calc_beta(asset_rets, factor_rets):
        if not factor_rets or len(factor_rets) < 15:
            return 0
        n = min(len(asset_rets), len(factor_rets))
        a, f = asset_rets[:n], factor_rets[:n]
        if np.std(a) == 0 or np.std(f) == 0:
            return 0
        corr = np.corrcoef(a, f)[0, 1]
        return round(corr, 3) if not np.isnan(corr) else 0

    return {
        "dxy_beta": calc_beta(asset_returns, factors.get("dxy", [])),
        "vix_beta": calc_beta(asset_returns, factors.get("vix", [])),
        "tnx_beta": calc_beta(asset_returns, factors.get("tnx", [])),
        "source": "30d_rolling",
    }


_beta_sem = asyncio.Semaphore(3)

async def calculate_asset_betas(asset_id: str, asset_price_30d: list) -> dict:
    """
    Calculate 30d rolling betas between asset and macro factors (DXY, VIX, 10Y).
    Runs fully in thread pool — yfinance sync calls no longer block the event loop.
    Concurrent beta calcs capped at 3 via semaphore.
    """
    cache_key = f"betas:{asset_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with _beta_sem:
            # Python 3.14: asyncio.to_thread with async func returns coroutine, not awaitable
            # Run directly without to_thread wrapper (sync yfinance calls inside are the bottleneck, not this wrapper)
            result = await _betas_in_thread(asset_id, asset_price_30d)
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        return {"dxy_beta": 0, "vix_beta": 0, "tnx_beta": 0, "source": "error"}


# Symbol mapping: CIS symbol -> Binance symbol
# Aligned with cometcloud-local ASSET_UNIVERSE crypto assets
BINANCE_SYMBOLS = {
    # L1
    "BTC":   "btcusdt",
    "ETH":   "ethusdt",
    "SOL":   "solusdt",
    "BNB":   "bnbusdt",
    "XRP":   "xrpusdt",
    "ADA":   "adausdt",
    "AVAX":  "avaxusdt",
    "DOT":   "dotusdt",
    "NEAR":  "nearusdt",
    "SUI":   "suiusdt",
    "APT":   "aptusdt",
    # HYPE REMOVED 2026-08-01 — "hyperusdt" on Binance SPOT is HYPERLANE, not
    # Hyperliquid. $0.0558 vs $52.32: a 937x wrong-asset read that produced
    # volume_mcap_ratio=0.0002 → liquidity_score=-4.8 → LAS 3.1 → grade D →
    # UNDERWEIGHT, held through a +256% run (2026-01 $20.92 → 2026-06 $74.39).
    # HYPEUSDT does not exist on Binance spot at all. The real market is perps;
    # HYPE is now sourced through VENUE_OVERLAY_ASSETS below.
    # L2
    "ARB":   "arbusdt",
    "OP":    "opusdt",
    "POL":   "polusdt",
    "STRK":  "strkusdt",
    # DeFi
    "UNI":   "uniusdt",
    "AAVE":  "aaveusdt",
    "LDO":   "ldousdt",
    "PENDLE":"pendleusdt",
    # Infrastructure
    "LINK":  "linkusdt",
    "INJ":   "injusdt",
    "TIA":   "tiausdt",
    # RWA
    "ONDO":  "ondousdt",
    "MKR":   "mkrusdt",
}
# Reverse mapping
BINANCE_TO_CIS = {v: k for k, v in BINANCE_SYMBOLS.items()}


async def fetch_binance_prices() -> Dict[str, dict]:
    """Fetch crypto prices from Binance public data mirror.

    Uses data-api.binance.vision (not api.binance.com) — the vision endpoint
    is geo-accessible from Railway US, whereas api.binance.com is geo-blocked.

    Cache hierarchy: L1 in-process → L2 Upstash (300s TTL, survives deploys).
    """
    cache_key = "binance_prices"
    redis_key = "cis:binance_prices"

    cached = _cache_get(cache_key)
    if cached:
        return cached

    r2 = await _upstash_get(redis_key)
    if r2:
        _cache_set(cache_key, r2)
        return r2

    result = {}
    binsym = list(BINANCE_SYMBOLS.values())

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # data-api.binance.vision is the public mirror — no geo-block, no API key
            url = "https://data-api.binance.vision/api/v3/ticker/24hr"

            # Get all 24hr tickers
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

            # Filter for our symbols
            for ticker in data:
                sym = ticker.get("symbol", "").lower()
                if sym in binsym:
                    cis_sym = BINANCE_TO_CIS.get(sym, sym.upper().replace("USDT", ""))

                    # Get 7d history for 7d change (approximate from 24hr)
                    # Binance doesn't have 7d, so we'll estimate from current data
                    price = float(ticker.get("lastPrice", 0))
                    change_24h = float(ticker.get("priceChangePercent", 0))
                    high_24h = float(ticker.get("highPrice", 0))
                    low_24h = float(ticker.get("lowPrice", 0))
                    volume = float(ticker.get("quoteVolume", 0))

                    result[cis_sym] = {
                        "symbol": cis_sym,
                        "name": cis_sym,
                        "price": price,
                        "change_24h": change_24h,
                        "change_7d": None,   # Will be filled from CoinGecko merge
                        "change_30d": None,  # Will be filled from CoinGecko merge
                        "volume_24h": volume,
                        "high_24h": high_24h,
                        "low_24h": low_24h,
                        "market_cap": 0,  # Will be filled from CoinGecko merge
                        "circulating_supply": 0,
                        "total_supply": 0,
                        "ath_change_percentage": 0,
                        "source": "binance",
                    }

            _logger.info(f"Binance: fetched {len(result)} assets")
            _cache_set(cache_key, result)
            await _upstash_set(redis_key, result, ttl=300)   # 5min TTL — prices are time-sensitive
            return result

    except Exception as e:
        _logger.warning(f"Binance API error: {e}")
        return r2 or result


# ── Cross-venue overlay (2026-08-01) ──────────────────────────────────────────
#
# Assets whose real market is NOT Binance spot. Sourcing these from a single
# spot venue is wrong twice over: it can silently resolve to a different asset
# (HYPE → Hyperlane, 937x), and even when correct it undercounts, because each
# venue hosts a different trader cohort. Measured on HYPE 2026-08-01:
#   Binance perp $440.8M vol / $248.1M OI (turnover 1.78x — leverage churn)
#   Hyperliquid  $314.4M vol / $1,174.4M OI (turnover 0.27x — position-takers)
#   Bybit        $178.2M vol / $201.2M OI
# Consolidated: $937M volume, $1.62B gross OI, 7bp price dispersion.
#
# Full rationale + aggregation rules: src/data/venues/__init__.py
VENUE_OVERLAY_ASSETS = {"HYPE"}


async def fetch_venue_overlay() -> Dict[str, dict]:
    """
    Consolidated cross-venue market data for assets Binance spot cannot serve.

    Returns {asset: {price, volume_24h, open_interest_usd, funding_rate,
                     venue_confidence, venues_used, degraded}}.

    Never raises and never fabricates: on total failure it returns {} and the
    caller falls through to whatever CoinGecko provides, exactly as before.
    Railway is US-hosted and api.binance.com is geo-blocked there — the
    multi-venue design degrades to Hyperliquid + Bybit rather than failing,
    which is the operational reason for it as much as the accuracy one.
    """
    cache_key = "venue_overlay"
    redis_key = "cis:venue_overlay"

    cached = _cache_get(cache_key)
    if cached:
        return cached
    r2 = await _upstash_get(redis_key)
    if r2:
        _cache_set(cache_key, r2)
        return r2

    out: Dict[str, dict] = {}
    try:
        try:
            from src.data.venues import fetch_consolidated
        except ImportError:
            from data.venues import fetch_consolidated

        async with httpx.AsyncClient(timeout=10) as client:
            results = await asyncio.gather(
                *[fetch_consolidated(a, client=client) for a in sorted(VENUE_OVERLAY_ASSETS)],
                return_exceptions=True,
            )

        for asset, res in zip(sorted(VENUE_OVERLAY_ASSETS), results):
            if isinstance(res, Exception) or res is None:
                _logger.warning("venue overlay: %s unresolved (%s)", asset, res)
                continue
            # A rejected venue means a mapping is pointing at the wrong asset.
            # Refuse the value rather than pass a plausible-looking wrong number
            # downstream — that failure mode is what this whole path exists for.
            if res.venues_rejected:
                _logger.error(
                    "venue overlay: %s REJECTED venue(s) %s (dispersion %.2f%%) — "
                    "possible wrong-asset mapping; skipping overlay",
                    asset, res.venues_rejected, res.price_dispersion * 100,
                )
                continue
            out[asset] = {
                "price": res.price,
                "volume_24h": res.volume_24h_usd,
                "open_interest_usd": res.open_interest_usd,
                # MEDIAN across venues, not any single one. The O pillar reads a
                # scalar funding rate against fixed thresholds (>0.05%/8h =
                # overleveraged longs), and on HYPE the venues span 8x
                # (0.0000125 .. 0.0001) — picking one would let a single venue's
                # cohort decide a scoring band. The full map and the spread are
                # carried alongside; the spread is the net-positioning signal.
                "funding_rate": (statistics.median(list(res.funding_by_venue.values()))
                                 if res.funding_by_venue else None),
                "funding_by_venue": res.funding_by_venue,
                "funding_spread": res.funding_spread,
                "venue_confidence": res.confidence,
                "venues_used": res.venues_used,
                "oi_concentration": res.oi_concentration,
                "degraded": res.degraded,
                "source": "venue_consolidated",
            }

        if out:
            _cache_set(cache_key, out)
            await _upstash_set(redis_key, out, ttl=300)
        _logger.info("venue overlay: %d asset(s) consolidated", len(out))
        return out

    except Exception as e:                                        # noqa: BLE001
        _logger.warning("venue overlay failed: %s", e)
        return r2 or out


async def fetch_cg_markets() -> Dict[str, dict]:
    """Fetch market data from CoinGecko for all tracked crypto assets.

    Cache hierarchy:
      L1 — in-process memory (_cache): 300s TTL, resets on restart/deploy
      L2 — Upstash Redis: 1800s TTL, survives Railway deploys and cold starts

    Uses explicit coin IDs (not top-N) so POLYX, NEON etc. are always included.
    Batches into chunks of 50 to stay within CG URL length limits.
    """
    cache_key = "cg_markets_v3"
    redis_key = "cis:cg_markets_v3"

    # L1: in-process memory (fastest)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # L2: Upstash Redis (survives deploys)
    r2 = await _upstash_get(redis_key)
    if r2:
        _cache_set(cache_key, r2)   # warm L1
        return r2

    result = {}

    # Collect all CoinGecko IDs we need
    all_cg_ids = [cfg["coingecko"] for cfg in CRYPTO_ASSETS.values() if cfg.get("coingecko")]
    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for cid in all_cg_ids:
        if cid not in seen:
            seen.add(cid)
            unique_ids.append(cid)

    # Pro key present: larger batches, parallel fetch, sparkline enabled
    # Free tier: smaller batches, serial, no sparkline (rate limit workaround)
    _pro = bool(CG_API_KEY)
    batch_size = 200 if _pro else 50

    async def _fetch_batch(client: httpx.AsyncClient, batch: list[str]) -> list:
        ids_str = ",".join(batch)
        params = {
            "vs_currency":            "usd",
            "ids":                    ids_str,
            "order":                  "market_cap_desc",
            "per_page":               250,
            "page":                   1,
            "sparkline":              "true" if _pro else "false",
            "price_change_percentage": "30d,7d,1y",
        }
        try:
            r = await client.get(f"{_cg_base()}/coins/markets",
                                 params=params, headers=_cg_headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            _logger.warning(f"CoinGecko batch error: {e}")
            return []

    def _sparkline_7d_return(sparkline_prices: list) -> float | None:
        """Compute 7d return from 168-point hourly sparkline. More accurate than CG's field."""
        if not sparkline_prices or len(sparkline_prices) < 2:
            return None
        p0, p_last = sparkline_prices[0], sparkline_prices[-1]
        if p0 and p0 > 0:
            return round((p_last - p0) / p0 * 100, 4)
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            batches = [unique_ids[i:i + batch_size] for i in range(0, len(unique_ids), batch_size)]

            if _pro:
                # Pro: fetch all batches in parallel (500 rpm headroom)
                batch_results = await asyncio.gather(*[_fetch_batch(client, b) for b in batches])
                all_coins = [coin for batch in batch_results for coin in batch]
            else:
                # Free: serial with rate-limit delay
                all_coins = []
                for i, batch in enumerate(batches):
                    all_coins.extend(await _fetch_batch(client, batch))
                    if i < len(batches) - 1:
                        await asyncio.sleep(1.5)

            for coin in all_coins:
                coin_id = coin["id"]
                sparkline_prices = (coin.get("sparkline_in_7d") or {}).get("price") or []
                sparkline_return = _sparkline_7d_return(sparkline_prices) if _pro else None
                result[coin_id] = {
                    "symbol":               coin["symbol"].upper(),
                    "name":                 coin["name"],
                    "market_cap":           coin.get("market_cap", 0),
                    "fdv":                  coin.get("fully_diluted_valuation", 0),
                    "volume_24h":           coin.get("total_volume", 0),
                    "price":                coin.get("current_price", 0),
                    "change_24h":           coin.get("price_change_percentage_24h", 0),
                    "change_7d":            sparkline_return if sparkline_return is not None
                                            else (coin.get("price_change_percentage_7d_in_currency")
                                                  or coin.get("price_change_percentage_7d", 0)),
                    "change_30d":           coin.get("price_change_percentage_30d_in_currency")
                                            or coin.get("price_change_percentage_30d", 0),
                    "change_1y":            coin.get("price_change_percentage_1y_in_currency", 0),
                    "circulating_supply":   coin.get("circulating_supply", 0),
                    "total_supply":         coin.get("total_supply", 0),
                    "max_supply":           coin.get("max_supply"),
                    "supply_ratio":         round(coin.get("circulating_supply", 0) / coin.get("total_supply", 1), 4)
                                            if coin.get("total_supply") else None,
                    "ath_change_percentage": coin.get("ath_change_percentage", 0),
                    "high_24h":             coin.get("high_24h", 0),
                    "low_24h":              coin.get("low_24h", 0),
                    "sparkline_7d":         sparkline_prices[-24:] if sparkline_prices else [],  # last 24h hourly
                    "sparkline_return_7d":  sparkline_return,
                    "source":               "coingecko_pro" if _pro else "coingecko",
                }

            _logger.info(f"CoinGecko {'Pro' if _pro else 'free'}: fetched {len(result)}/{len(unique_ids)} assets "
                         f"({'parallel' if _pro else 'serial'}, batch_size={batch_size})")
            _cache_set(cache_key, result)
            await _upstash_set(redis_key, result, ttl=1800)
            return result

    except Exception as e:
        _logger.warning(f"CoinGecko API error: {e}")
        # Return stale L2 if available rather than empty
        if not r2:
            r2 = await _upstash_get(redis_key)
        return r2 or result


async def fetch_defillama_tvl() -> Dict[str, float]:
    """Fetch TVL data from DeFiLlama."""
    cache_key = "llama_tvl"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.llama.fi/protocols")
            r.raise_for_status()
            protocols = r.json()

            result = {}
            for p in protocols:
                # Match by ticker symbol
                slug = p.get("slug", "").lower()
                symbol = p.get("symbol", "").upper()
                tvl = p.get("tvl", 0)

                # Map to our config
                for asset_id, config in ASSETS_CONFIG.items():
                    cg_id = config.get("coingecko", "")
                    if cg_id and cg_id.lower() == slug or symbol == asset_id:
                        result[asset_id] = tvl
                        break

            return _cache_set(cache_key, result)
    except Exception as e:
        _logger.warning(f"DeFiLlama API error: {e}")
        return {}


async def fetch_fear_greed() -> Optional[dict]:
    """Fetch Fear & Greed index."""
    cache_key = "fear_greed"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://api.alternative.me/fng/")
            r.raise_for_status()
            data = r.json()
            return _cache_set(cache_key, data.get("data", [{}])[0])
    except Exception as e:
        _logger.warning(f"Fear&Greed API error: {e}")
        return None


async def fetch_cg_global() -> Optional[dict]:
    """Fetch CoinGecko global data (includes BTC dominance)."""
    cache_key = "cg_global"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_cg_base()}/global", headers=_cg_headers())
            r.raise_for_status()
            data = r.json()
            return _cache_set(cache_key, data.get("data", {}))
    except Exception as e:
        _logger.warning(f"CoinGecko global API error: {e}")
        return None


async def fetch_github_activity() -> Dict[str, int]:
    """
    Fetch commit counts for the last 4 weeks from GitHub public API.
    Uses /repos/{owner}/{repo}/stats/participation (no auth, 60 req/hr).
    Returns {asset_id: commits_last_4w} — best effort, empty on failure.
    Cached for 2 hours to stay within the 60 req/hr rate limit.
    """
    cache_key = "github_activity"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    results: Dict[str, int] = {}
    # AUTHENTICATE (2026-08-12, S-145). Unauthenticated GitHub allows 60 requests
    # per HOUR per IP. This fetches ~25 repos per cycle and the cycle runs several
    # times an hour, so the quota is gone inside the first run and every call after
    # that returns 403 — measured in the Mac log: 25 × "403 rate limit exceeded",
    # every cycle, all night. A token raises the limit to 5,000/hr.
    #
    # The cost was not only the missing data. Each 403 is still a round trip, so
    # the dev-activity branch burned its whole 3s budget failing, which contributed
    # to the universe build exceeding its 12s budget — and THAT is what turned a
    # missing pillar into a total outage of every downstream writer.
    _gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    _gh_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _gh_token:
        _gh_headers["Authorization"] = f"Bearer {_gh_token}"
    else:
        # Say it ONCE per process, at WARNING. A per-repo log line for a condition
        # that is identical across 25 repos is noise that hides the signal.
        global _GH_TOKEN_WARNED
        if not _GH_TOKEN_WARNED:
            _GH_TOKEN_WARNED = True
            _logger.warning(
                "[CIS] GITHUB_TOKEN unset — GitHub allows 60 req/hr unauthenticated "
                "and this needs ~25/cycle, so dev-activity will 403 and default. "
                "Set GITHUB_TOKEN (a classic PAT with NO scopes is enough for "
                "public repo stats) to restore it.")

    async def _fetch_one(client: httpx.AsyncClient, asset_id: str, repo: str):
        try:
            url = f"https://api.github.com/repos/{repo}/stats/participation"
            r = await client.get(url, headers=_gh_headers)
            if r.status_code == 200:
                data = r.json()
                # 'all' = array of 52 weekly totals (owner + contributors)
                all_weeks = data.get("all", [])
                if all_weeks and len(all_weeks) >= 4:
                    return asset_id, sum(all_weeks[-4:])
            # 202 = GitHub still computing; 404/403 = unavailable — skip silently
        except Exception as e:
            _logger.warning(f"[GitHub] activity fetch for {repo}: {e}")
        return asset_id, None

    async with httpx.AsyncClient(timeout=8) as client:
        tasks = [_fetch_one(client, aid, repo) for aid, repo in GITHUB_REPOS.items()]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

    for item in raw:
        if isinstance(item, tuple) and item[1] is not None:
            results[item[0]] = int(item[1])

    # Use a 2-hour TTL via a manual timestamp check on next hit
    # (simple _cache_set uses global _cache_ttl=300; we override by storing a wrapper)
    _cache[cache_key] = (results, datetime.now().timestamp() + 7200)
    return results


async def get_yfinance_data(symbol: str) -> Optional[dict]:
    """Fetch US equity/bond/commodity data using yfinance."""
    cache_key = f"yf:{symbol}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        import yfinance as yf

        # Rate limiting - async sleep to avoid blocking event loop
        await asyncio.sleep(0.2)

        def _fetch():
            ticker = yf.Ticker(symbol)
            info = ticker.info
            hist = ticker.history(period="35d")
            price_now = float(hist['Close'].iloc[-1]) if len(hist) > 0 else 0
            # 7D change from history
            if len(hist) > 7:
                price_7d_ago = float(hist['Close'].iloc[-8])
                change_7d = ((price_now - price_7d_ago) / price_7d_ago) * 100 if price_7d_ago else 0
            else:
                change_7d = 0
            # 30D change from history
            if len(hist) > 30:
                price_30d_ago = float(hist['Close'].iloc[-31] if len(hist) > 31 else hist['Close'].iloc[0])
                change_30d = ((price_now - price_30d_ago) / price_30d_ago) * 100 if price_30d_ago else 0
                # Daily return std dev over available history (used for vol-adjusted SL/TP)
                daily_rets = hist['Close'].pct_change().dropna()
                volatility_30d = float(daily_rets.std()) if len(daily_rets) >= 5 else 0.0
            else:
                change_30d = 0
                volatility_30d = 0.0
            # market_cap: ETFs report totalNetAssets / totalAssets instead of marketCap
            mcap = (info.get("marketCap") or
                    info.get("totalNetAssets") or
                    info.get("totalAssets") or 0)
            # change_24h: regularMarketChange is dollar delta — use percent field instead
            change_24h_pct = (info.get("regularMarketChangePercent") or
                              info.get("regularMarketChangePct") or 0)
            # Derive from history if yfinance percent field unavailable
            if not change_24h_pct and len(hist) >= 2:
                prev_close = float(hist['Close'].iloc[-2])
                if prev_close:
                    change_24h_pct = ((price_now - prev_close) / prev_close) * 100
            # high/low 24h for spread penalty
            high_24h = float(info.get("dayHigh") or info.get("regularMarketDayHigh") or 0)
            low_24h  = float(info.get("dayLow")  or info.get("regularMarketDayLow")  or 0)
            # ATH distance from 52-week high as a proxy
            week52_high = float(info.get("fiftyTwoWeekHigh") or 0)
            ath_chg = 0.0
            if week52_high and price_now:
                ath_chg = ((price_now - week52_high) / week52_high) * 100  # negative = below ATH
            return {
                "symbol": symbol,
                "price": info.get("currentPrice", info.get("regularMarketPrice", price_now)),
                "market_cap": mcap,
                "volume_24h": info.get("regularMarketVolume", 0),
                "change_24h": round(change_24h_pct, 2),
                "high_24h": high_24h,
                "low_24h": low_24h,
                "change_7d": change_7d,
                "change_30d": change_30d,
                "volatility_30d": round(volatility_30d, 5),
                "circulating_supply": info.get("sharesOutstanding", 0),
                "total_supply": info.get("sharesOutstanding", 0),
                "ath_change_percentage": round(ath_chg, 1),
            }

        result = await asyncio.to_thread(_fetch)
        return _cache_set(cache_key, result)
    except Exception as e:
        # Don't print on rate limit - it's expected
        if "Rate limited" not in str(e):
            _logger.warning(f"yfinance error for {symbol}: {e}")
        return None


# Macro data cache path - configurable via env var for different deployments
# On Mac Mini: /Volumes/CometCloudAI/data/macro_cache.json
# On Railway: set MACRO_CACHE_PATH env var to a Railway-appropriate path
MACRO_CACHE_PATH = os.getenv("MACRO_CACHE_PATH", "/Volumes/CometCloudAI/data/macro_cache.json")
MACRO_CACHE_TTL = 3600  # 1 hour


def _load_macro_cache() -> Optional[dict]:
    """Load macro data from external drive cache."""
    try:
        if os.path.exists(MACRO_CACHE_PATH):
            import json
            with open(MACRO_CACHE_PATH, 'r') as f:
                data = json.load(f)
            # Check if cache is still valid
            ts = data.get("timestamp", 0)
            if datetime.now().timestamp() - ts < MACRO_CACHE_TTL:
                return data
    except Exception as e:
        _logger.warning(f"[MacroCache] read failed: {e}")
    return None


def _save_macro_cache(data: dict):
    """Save macro data to external drive cache."""
    try:
        cache_dir = os.path.dirname(MACRO_CACHE_PATH)
        if not os.path.exists(cache_dir):
            # Path not available (e.g., Railway) — skip disk cache silently
            return
        import json
        with open(MACRO_CACHE_PATH, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        _logger.warning(f"Failed to save macro cache: {e}")


async def fetch_macro_data() -> dict:
    """
    Fetch macro indicators via FRED API and Yahoo Finance.
    Falls back to hardcoded values if API fails.

    Cached to external drive for 1 hour.
    """
    FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
    # FRED is optional enrichment — VIX, DXY, btc_dominance come from yfinance/CG
    # If key missing, skip FRED fetch entirely and rely on yfinance fallbacks below

    # Try memory cache first
    cache_key = "macro_data"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # Try external drive cache
    disk_cache = _load_macro_cache()
    if disk_cache:
        _cache_set(cache_key, disk_cache)
        return disk_cache

    # Default fallback values (2025-03 realistic values)
    fallback = {
        "fed_funds": 4.25,      # ~4.25% as of March 2025
        "treasury_10y": 4.15,   # ~4.15% 10Y yield
        "vix": 19.5,            # ~19.5 VIX (normal market)
        "dxy": 104.2,           # ~104 DXY
        "cpi_yoy": 2.8,         # ~2.8% CPI YoY
        "btc_dominance": 52.0,  # BTC dominance %
    }

    # Fetch fresh data
    result = {
        "timestamp": datetime.now().timestamp(),
        "regime": "unknown",
        "fed_funds": fallback["fed_funds"],
        "treasury_10y": fallback["treasury_10y"],
        "vix": fallback["vix"],
        "dxy": fallback["dxy"],
        "cpi_yoy": fallback["cpi_yoy"],
        "btc_dominance": fallback["btc_dominance"],
        "_source": "fallback",
    }

    fetched_any = False

    # Fetch from FRED API (optional — skip entirely if key not configured)
    if FRED_API_KEY:
        try:
            fred_series = {
                "fed_funds": "FEDFUNDS",      # Effective Federal Funds Rate
                "treasury_10y": "GS10",       # 10-Year Treasury Constant Maturity Rate
                "cpi_yoy": "CPIAUCSL",        # CPI for All Urban Consumers
            }
            async with httpx.AsyncClient(timeout=15) as client:
                for key, series_id in fred_series.items():
                    try:
                        url = f"https://api.stlouisfed.org/fred/series/observations"
                        params = {
                            "series_id": series_id,
                            "api_key": FRED_API_KEY,
                            "observation_limit": 12,  # Need 12 for YoY CPI
                            "sort_order": "desc",
                            "file_type": "json",
                        }
                        resp = await client.get(url, params=params)
                        if resp.status_code == 200:
                            data = resp.json()
                            observations = data.get("observations", [])
                            if observations and observations[0].get("value") != ".":
                                value = float(observations[0].get("value", 0))
                                if key == "cpi_yoy":
                                    # CPI is monthly, calculate YoY change
                                    if len(observations) >= 12 and observations[11].get("value") != ".":
                                        prev_value = float(observations[11].get("value", 0))
                                        if prev_value > 0:
                                            result[key] = round(((value - prev_value) / prev_value) * 100, 1)
                                            fetched_any = True
                                else:
                                    result[key] = round(value, 2)
                                    fetched_any = True
                    except Exception as e:
                        _logger.warning(f"FRED error for {key}: {e}")
        except Exception as e:
            _logger.warning(f"FRED API error: {e}")

    # Yahoo Finance v8 quote endpoints
    ticker_map = {
        "vix": "^VIX",
        "dxy": "DX-Y.NYB",
        "treasury_10y": "^TNX",
        "fed_funds": "^IRX",  # 13-week T-Bill as Fed proxy
    }

    async def fetch_yf_async(symbol: str) -> Optional[float]:
        """Fetch using Yahoo Finance v8 quote API via httpx."""
        import time

        for attempt in range(2):
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                async with httpx.AsyncClient(timeout=8) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        result_data = data.get("chart", {}).get("result")
                        if result_data and len(result_data) > 0:
                            meta = result_data[0].get("meta", {})
                            price = (
                                meta.get("regularMarketPrice") or
                                meta.get("previousClose")
                            )
                            if price:
                                return float(price)
            except Exception as e:
                _logger.warning(f"[YFinance] price fetch failed for {symbol}: {e}")
            if attempt < 1:
                time.sleep(0.5)
        return None

    try:
        # Fetch VIX/DXY from Yahoo Finance
        for key, symbol in ticker_map.items():
            value = await fetch_yf_async(symbol)
            if value is not None:
                fetched_any = True
                if key == "fed_funds":
                    result[key] = round(value / 100, 4)  # Convert % to decimal
                else:
                    result[key] = round(value, 2)

        # Fetch BTC dominance from CoinGecko global
        cg_global = await fetch_cg_global()
        if cg_global:
            btc_dom = cg_global.get("market_cap_percentage", {}).get("btc")
            if btc_dom is not None:
                result["btc_dominance"] = round(btc_dom, 1)
                fetched_any = True

        if fetched_any:
            result["_source"] = "api"

    except Exception as e:
        _logger.warning(f"Error fetching macro data: {e}")

    # Determine regime based on VIX
    if result["vix"]:
        if result["vix"] < 15:
            result["regime"] = "low_volatility"
        elif result["vix"] < 25:
            result["regime"] = "normal"
        else:
            result["regime"] = "high_volatility"

    # Save to external drive cache
    _save_macro_cache(result)
    _cache_set(cache_key, result)

    return result


def get_asset_class(asset_id: str) -> str:
    """Get asset class from config."""
    if asset_id in ASSETS_CONFIG:
        return ASSETS_CONFIG[asset_id]["class"]
    return "Crypto"


def _log_score(value: float, base: float, scale: float, cap: float) -> float:
    """Continuous log-scale scoring. value=base → 0, each 10x → +scale, capped at cap."""
    if value <= 0:
        return 0.0
    if value <= base:
        return 0.0
    return min(cap, scale * math.log10(value / base))


def _linear_interp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Linear interpolation clamped to [y0, y1] (or [y1, y0] if inverted)."""
    lo, hi = min(y0, y1), max(y0, y1)
    if x1 == x0:
        return (y0 + y1) / 2
    t = (x - x0) / (x1 - x0)
    return max(lo, min(hi, y0 + t * (y1 - y0)))


def calculate_cis_score(
    market_data: dict,
    tvl: float,
    fng: Optional[dict],
    asset_class: str,
    asset_id: Optional[str] = None,
    btc_change_30d: Optional[float] = None,
    github_commits_4w: Optional[int] = None,
    vix: Optional[float] = None,
    spy_change_30d: Optional[float] = None,
    asset_betas: Optional[dict] = None,
    category_median_30d: Optional[float] = None,  # v4.1: median 30d change for category
    dev_activity_score: Optional[float] = None,   # v4.2: CG Pro dev score 0-100 (tech assets)
    eodhd_fundamentals: Optional[dict] = None,    # v4.2: EODHD PE/revenue data (US Equity)
    regime: str = "Neutral",                      # v4.2: macro regime for regime-aware A pillar
    _deriv_map: Optional[dict] = None,            # v4.3: derivatives funding rate + OI (internal)
    _trend_map: Optional[dict] = None,            # v4.3: trending rank for S-pillar boost (internal)
    narrative_modifier: float = 0.0,              # NMA-driven S-pillar adjustment from narrative engine
) -> Dict[str, Any]:
    """
    CIS v4.2 — Continuous scoring functions.
    All pillars use log-scale or linear interpolation for genuine differentiation.
    v4.2 additions: CG Pro dev_activity_score in F pillar for tech assets;
    EODHD PE/revenue scoring in F pillar for US Equity.
    v4.x: NMA narrative_modifier applied to S pillar (narrative engine injection).
    """
    market_cap = market_data.get("market_cap", 0) if market_data else 0
    volume_24h = market_data.get("volume_24h", 0) if market_data else 0
    circ_supply = market_data.get("circulating_supply", 0) if market_data else 0
    total_supply = market_data.get("total_supply", 0) if market_data else 0
    change_30d = market_data.get("change_30d", 0) or 0
    change_7d = market_data.get("change_7d", 0) or 0
    change_24h = market_data.get("change_24h", 0) or 0
    # Pro: sparkline_return_7d is computed from 168-point hourly data (more precise than CG field)
    sparkline_return_7d = market_data.get("sparkline_return_7d") if market_data else None
    ath_distance = abs(market_data.get("ath_change_percentage", 0)) if market_data else 50
    price = market_data.get("price", 0) if market_data else 0
    high_24h = market_data.get("high_24h", 0) or 0
    low_24h = market_data.get("low_24h", 0) or 0
    fdv = market_data.get("fdv", 0) if market_data else 0
    max_supply = market_data.get("max_supply") if market_data else None
    _is_tradfi = asset_class in ["US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"]

    # ── F — Fundamental (Structural Quality) ──────────────────────────
    # Continuous: mcap log-scale (0-50) + tvl log-scale (0-20) + fdv fairness (0-15) + supply (0-15)
    # v4.2: US Equity → PE/revenue replace fdv/supply; tech assets → CG dev_activity bonus (0-10)
    has_tvl_class = asset_class in ["DeFi", "L2"]
    # Reduce mcap cap for mega-cap assets (>$500B) to prevent F score maxing at 100
    # Mega-cap (>$500B) → mcap_cap 40; Large-cap ($50-500B) → 55; Others → 70/50
    if market_cap > 500e9:
        mcap_cap = 40 if not has_tvl_class else 30
    else:
        mcap_cap = 50 if has_tvl_class else 55

    mcap_score = _log_score(market_cap, 1e6, 10, mcap_cap)  # $1M base, +10 per decade
    tvl_score = _log_score(tvl, 1e6, 5, 20) if (has_tvl_class and tvl and tvl > 0) else 0.0

    # FDV fairness: ratio=1 → 15, ratio≥5 → 0, linear between
    fdv_score = 0.0
    supply_ratio = (circ_supply / total_supply) if (total_supply > 0 and circ_supply > 0) else 0
    supply_score = min(15, supply_ratio * 15)

    # Pro: capped-emission bonus — if max_supply is set and >85% issued, the asset is
    # near peak inflation → supply certainty premium (+0 to +5 on F pillar)
    # BTC (93% issued) and LTC (94% issued) benefit most.
    emission_bonus = 0.0
    if max_supply and max_supply > 0 and circ_supply > 0:
        emission_pct = circ_supply / max_supply
        if emission_pct >= 0.85:
            emission_bonus = _linear_interp(emission_pct, 0.85, 1.0, 0.0, 5.0)

    if asset_class != "US Equity":
        if fdv > 0 and market_cap > 0:
            ratio = fdv / market_cap
            fdv_score = max(0, _linear_interp(ratio, 1.0, 5.0, 15.0, 0.0))

    # v4.2: EODHD fundamentals for US Equity — PE + revenue replace fdv + supply
    eodhd_pe_score = 0.0
    eodhd_rev_score = 0.0
    if asset_class == "US Equity" and eodhd_fundamentals:
        pe = eodhd_fundamentals.get("pe_ratio")
        # EODHD field is "revenue_growth" (TTM) — accept both keys for safety
        rev_growth = eodhd_fundamentals.get("revenue_growth_yoy") or eodhd_fundamentals.get("revenue_growth")
        # PE scoring: sweet spot 10-25 → up to 15pts; high PE or negative → penalty
        if pe is not None and pe > 0:
            if pe <= 10:
                eodhd_pe_score = _linear_interp(pe, 5, 10, 8, 13)
            elif pe <= 25:
                eodhd_pe_score = _linear_interp(pe, 10, 25, 13, 15)
            elif pe <= 40:
                eodhd_pe_score = _linear_interp(pe, 25, 40, 15, 5)
            else:
                eodhd_pe_score = max(0, _linear_interp(pe, 40, 100, 5, 0))
        # Revenue growth YoY: -10% → 0, flat → 7, +25% → 15 (cap)
        if rev_growth is not None:
            if rev_growth >= 25:
                eodhd_rev_score = 15.0
            elif rev_growth >= 0:
                eodhd_rev_score = _linear_interp(rev_growth, 0, 25, 7, 15)
            else:
                eodhd_rev_score = max(0, _linear_interp(rev_growth, -10, 0, 0, 7))
        fdv_score = eodhd_pe_score
        supply_score = eodhd_rev_score

    # v4.2: Dev activity bonus for tech assets (CG Pro developer_data, pre-fetched)
    # Classes that benefit: L1, L2, DeFi, Infrastructure, AI, RWA
    _is_tech_asset = asset_class in {"L1", "L2", "DeFi", "Infrastructure", "AI", "RWA"}
    dev_bonus = 0.0
    if _is_tech_asset and dev_activity_score is not None:
        # dev_activity_score 0-100 → bonus 0-10 (linear; 50 → 5, 90 → 9)
        dev_bonus = min(10.0, dev_activity_score * 0.10)

    f_score = round(max(0, min(100, mcap_score + tvl_score + fdv_score + supply_score + dev_bonus + emission_bonus)), 1)

    # Resilience floor for listed TradFi instruments. Their Fundamental pillar
    # rests almost entirely on market_cap; a missing data point — a closed-session
    # weekend, an ETF with no fundamentals feed, a vendor hiccup — would otherwise
    # crater F to ~0 and drag the whole asset to D/F (the "美股变D" failure). A
    # listed equity/ETF/bond is structurally sound by definition, so floor F at a
    # neutral baseline. Forward-looking: as tokenized equities trade 24/7, this
    # keeps grades stable across the underlying's market hours.
    _TRADFI_CLASSES_F = {"US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"}
    if asset_class in _TRADFI_CLASSES_F:
        f_score = max(f_score, 45.0)

    f_components: dict = {
        "market_cap_usd": market_cap,
        "market_cap_score": round(mcap_score, 1),
        "tvl_usd": tvl if has_tvl_class else None,
        "tvl_score": round(tvl_score, 1),
    }
    if asset_class == "US Equity" and eodhd_fundamentals:
        f_components.update({
            "pe_ratio": eodhd_fundamentals.get("pe_ratio"),
            "pe_score": round(eodhd_pe_score, 1),
            "revenue_growth_yoy": eodhd_fundamentals.get("revenue_growth_yoy") or eodhd_fundamentals.get("revenue_growth"),
            "revenue_score": round(eodhd_rev_score, 1),
            "gross_margin": eodhd_fundamentals.get("gross_margin"),
            "profit_margin": eodhd_fundamentals.get("profit_margin"),
        })
    else:
        f_components.update({
            "fdv_usd": fdv,
            "fdv_ratio": round(fdv / market_cap, 2) if market_cap > 0 and fdv > 0 else None,
            "fdv_score": round(fdv_score, 1),
            "supply_ratio": round(supply_ratio, 3),
            "supply_score": round(supply_score, 1),
        })
    if dev_bonus > 0:
        f_components["dev_activity_score_cg"] = round(dev_activity_score, 1)
        f_components["dev_bonus"] = round(dev_bonus, 1)

    # ── M — Momentum (Market Activity) ───────────────────────────────
    # volume log-scale (0-40) + liquidity ratio (0-25) + price momentum (0-35)
    vol_score = _log_score(volume_24h, 1e5, 8, 40)  # $100K base, +8 per decade

    # Liquidity ratio: vol/mcap continuous, cap at 25
    liq_score = 0.0
    if market_cap > 0:
        vol_ratio = volume_24h / market_cap
        if vol_ratio >= 0.01:
            liq_score = min(25, vol_ratio * 200)  # 5%→10, 12.5%→25
        else:
            liq_score = max(-5, vol_ratio * 1000 - 5)  # Below 1% → penalty

    # Price momentum 30d: continuous linear map
    # -50% → 0, 0% → 15, +50% → 27, +100% → 30 (cap reduced to 30 to make room for sparkline)
    if change_30d <= -50:
        mom_score = 0.0
    elif change_30d <= 0:
        mom_score = _linear_interp(change_30d, -50, 0, 0, 15)
    elif change_30d <= 50:
        mom_score = _linear_interp(change_30d, 0, 50, 15, 27)
    else:
        mom_score = min(30, _linear_interp(change_30d, 50, 100, 27, 30))

    # 7d sparkline momentum (Pro: 168-point hourly precision; fallback: CG change_7d field)
    # -20% → 0, 0% → 5, +20% → 10 (max 10; blended with 30d for short-term confirmation)
    _r7 = sparkline_return_7d if sparkline_return_7d is not None else change_7d
    if _r7 <= -20:
        sparkline_7d_score = 0.0
    elif _r7 <= 0:
        sparkline_7d_score = _linear_interp(_r7, -20, 0, 0, 5)
    elif _r7 <= 20:
        sparkline_7d_score = _linear_interp(_r7, 0, 20, 5, 10)
    else:
        sparkline_7d_score = 10.0  # cap — avoid rewarding short spikes above 10

    m_score = round(max(0, min(100, vol_score + liq_score + mom_score + sparkline_7d_score)), 1)

    m_components = {
        "volume_24h": volume_24h,
        "volume_score": round(vol_score, 1),
        "volume_mcap_ratio": round(volume_24h / market_cap, 4) if market_cap > 0 else 0,
        "liquidity_score": round(liq_score, 1),
        "momentum_30d_pct": round(change_30d, 1),
        "momentum_score": round(mom_score, 1),
        "momentum_7d_pct": round(_r7, 1),
        "sparkline_7d_score": round(sparkline_7d_score, 1),
        "sparkline_source": "pro_168pt" if sparkline_return_7d is not None else "cg_field",
    }

    # ── O — On-Chain Health / Risk-Adjusted ──────────────────────────
    # ATH recovery (0-35) + drawdown estimate (0-35) + supply+tvl health (0-30)
    # NOTE: For TradFi assets, O pillar is not applicable — set to 0 or null

    # Pre-define locals so o_components can always reference them safely
    ath_score = 0.0
    dd_score = 0.0
    health_score = 0.0
    o_score = 0.0

    if not _is_tradfi:
        # ATH recovery: continuous, at ATH → 35, -80% → 0
        ath_score = max(0, _linear_interp(ath_distance, 0, 80, 35, 0))

        # Drawdown estimate from 24h range (annualized vol proxy)
        dd_score = 35.0  # default if no range data
        if low_24h > 0 and high_24h > low_24h:
            daily_range = (high_24h - low_24h) / low_24h
            ann_vol = daily_range * math.sqrt(365) * 100  # rough annualized
            dd_score = max(0, _linear_interp(ann_vol, 0, 200, 35, 0))

        # Supply + TVL health (reuse)
        health_score = supply_score  # 0-15 from F pillar
        if has_tvl_class and tvl and tvl > 0:
            health_score += min(15, _log_score(tvl, 1e6, 3.75, 15))
        else:
            health_score += max(0, _linear_interp(ath_distance, 0, 50, 15, 0))

        o_score = round(max(0, min(100, ath_score + dd_score + health_score)), 1)
    else:
        # For TradFi: use volatility as proxy for risk (inverse of stability)
        # Lower volatility = better O score (0-40, not 0-100 like crypto)
        if low_24h > 0 and high_24h > low_24h:
            daily_range_pct = ((high_24h - low_24h) / low_24h) * 100
            # 0.5% daily range → 40, 2% range → 20, 5% range → 0
            o_score = round(max(0, _linear_interp(daily_range_pct, 0.5, 5.0, 40, 0)), 1)
        else:
            o_score = 20.0  # neutral fallback for TradFi

    # ── v4.3: Derivatives (funding rate + OI) → O-pillar adjustment ─────
    # Funding rate encodes market positioning risk:
    #   Extreme positive (>0.05%/8h): overleveraged longs → cascade risk → O penalty (-8 to -15)
    #   Healthy positive (0.01-0.05%): bullish basis, normal → slight bonus (+3)
    #   Neutral (±0.01%): balanced → 0
    #   Negative (-0.01% to -0.05%): shorts dominant → squeeze setup → neutral/+2
    #   Extreme negative (<-0.05%): massive short exposure = squeeze risk = NOT inherently safer → -3
    # OI/MCap ratio: high leverage in system vs spot market
    #   >100% OI vs MCap: extreme leverage → O penalty (-5 to -10)
    #   50-100%: elevated → -3
    #   <20%: spot-driven = healthy → +3
    _sym_key  = asset_id.upper()
    _drv       = _deriv_map.get(_sym_key, {})
    _fr        = float(_drv.get("funding_rate") or 0)
    _oi_usd    = float(_drv.get("open_interest_usd") or 0)
    _fr_adj    = 0.0
    _oi_adj    = 0.0
    _fr_signal = "N/A (no derivatives)"

    if _drv and not _is_tradfi:
        _fr_signal = _drv.get("funding_signal", "unknown")
        # Funding rate modifier
        if _fr > 0.0005:      # >0.05%/8h — overleveraged longs
            _fr_adj = _linear_interp(_fr, 0.0005, 0.002, -8.0, -15.0)
        elif _fr > 0.0001:    # healthy bullish
            _fr_adj = _linear_interp(_fr, 0.0001, 0.0005, 3.0, 0.0)
        elif _fr > -0.0001:   # neutral
            _fr_adj = 0.0
        elif _fr > -0.0005:   # negative — shorts paying
            _fr_adj = 2.0     # slight squeeze setup bonus (risk-adjusted)
        else:                  # extreme negative
            _fr_adj = -3.0    # excessive leverage on short side also risky

        # OI / MCap leverage ratio
        if market_cap > 0 and _oi_usd > 0:
            _oi_ratio = _oi_usd / market_cap
            if _oi_ratio > 1.0:
                _oi_adj = _linear_interp(_oi_ratio, 1.0, 3.0, -5.0, -10.0)
            elif _oi_ratio > 0.5:
                _oi_adj = _linear_interp(_oi_ratio, 0.5, 1.0, -3.0, -5.0)
            elif _oi_ratio < 0.2:
                _oi_adj = 3.0   # low leverage = spot-driven = healthy

        # Apply adjustments to o_score
        if not _is_tradfi:
            o_score = round(max(0.0, min(100.0, o_score + _fr_adj + _oi_adj)), 1)

    o_components = {
        "ath_distance_pct": round(ath_distance, 1),
        "ath_recovery_score": round(ath_score, 1),
        "drawdown_estimate_score": round(dd_score, 1),
        "health_score": round(health_score, 1),
        "supply_ratio": round(supply_ratio, 3),
        "tvl_usd": tvl,
        # v4.3 derivatives additions
        "funding_rate": round(_fr, 6) if _drv else None,
        "funding_signal": _fr_signal,
        "funding_adj": round(_fr_adj, 1),
        "oi_usd": round(_oi_usd, 0) if _oi_usd > 0 else None,
        "oi_mcap_ratio": round(_oi_usd / market_cap, 3) if market_cap > 0 and _oi_usd > 0 else None,
        "oi_adj": round(_oi_adj, 1),
    }

    # ── S — Sentiment (Baseline + Divergence + Vol Regime) ───────────
    # baseline (0-40) + divergence (-20 to +40) + vol regime (-10 to +20)

    s_components = {
        "return_30d": round(change_30d / 100, 4),
        "return_24h": round(change_24h / 100, 4),
    }

    # FNG value — needed by both crypto and TradFi (divergence dampener).
    # Must be assigned before the if/else branch to avoid UnboundLocalError.
    fng_value = int(fng.get("value", 50)) if fng else None

    # Baseline
    # v4.1.1 enhancement: crypto baseline now uses 3-signal composite (0-40)
    # instead of FNG×0.4 alone. Signals are volume-observable and momentum-derived.
    baseline = 0.0
    if _is_tradfi:
        s_components["vix"] = vix
        if vix is not None:
            # VIX continuous: 10 → 50, 20 → 30, 35 → 5
            # TradFi gets higher baseline range (0-50) since markets are more stable/efficient
            baseline = max(5, _linear_interp(vix, 10, 35, 50, 5))
            s_components["baseline_score"] = round(baseline, 1)
        else:
            baseline = 25  # neutral fallback (was 20)
            s_components["baseline_score"] = 25
    else:
        # === Signal 1: Volume Surge (0–15) ===
        # Relative turnover (vol/mcap) as a proxy for active market participation.
        # High vol/mcap = real interest; low = dead market.
        vol_surge_signal = 0.0
        if market_cap > 0 and volume_24h > 0:
            vol_mcap_ratio = volume_24h / market_cap
            if vol_mcap_ratio >= 0.10:
                vol_surge_signal = 15.0
            elif vol_mcap_ratio >= 0.03:
                vol_surge_signal = _linear_interp(vol_mcap_ratio, 0.03, 0.10, 8.0, 15.0)
            elif vol_mcap_ratio >= 0.01:
                vol_surge_signal = _linear_interp(vol_mcap_ratio, 0.01, 0.03, 3.0, 8.0)
            elif vol_mcap_ratio >= 0.0005:
                vol_surge_signal = _linear_interp(vol_mcap_ratio, 0.0005, 0.003, 0.5, 3.0)
            # below 0.05% vol/mcap → 0 (illiquid / dead)
        else:
            vol_mcap_ratio = 0.0

        # === Signal 2: Momentum Structure (0–15) ===
        # Cross-timeframe alignment (24h / 7d / 30d). Aligned trend = conviction.
        # Mixed = neutral. All negative = risk-off.
        mom_struct = 0.0
        if change_24h > 0 and change_7d > 0 and change_30d > 0:
            # Full bullish alignment: score by composite strength
            strength = min(1.0, (change_24h / 3.0 + change_7d / 10.0 + change_30d / 20.0) / 3.0)
            mom_struct = _linear_interp(strength, 0.0, 1.0, 8.0, 15.0)
        elif change_24h < 0 and change_7d < 0 and change_30d < 0:
            # Full bearish alignment: no contribution (handled by divergence penalty)
            mom_struct = 0.0
        else:
            # Mixed signals: moderate score based on medium-term direction
            if change_7d > 5:
                mom_struct = _linear_interp(change_7d, 5.0, 20.0, 7.0, 11.0)
            elif change_7d >= -3:
                mom_struct = 6.0  # consolidating / neutral
            else:
                mom_struct = max(0.0, _linear_interp(change_7d, -15.0, -3.0, 0.0, 6.0))
            # v4.2: Recovery bonus — short-term bounce but not yet confirmed
            # 24h + 7d positive while 30d still negative = early recovery signal
            if change_24h > 0 and change_7d > 0 and change_30d < 0:
                recovery_bonus = min(5.0, _linear_interp(change_24h, 0.0, 5.0, 0.0, 5.0))
                mom_struct = min(15.0, mom_struct + recovery_bonus)
                s_components["recovery_bonus"] = round(recovery_bonus, 1)

        # === Signal 3: FNG Secondary (0–10) ===
        # Fear & Greed as a reduced-weight sentiment backdrop only.
        # (fng_value already assigned above the if/else branch)
        s_components["fear_greed_value"] = fng_value
        s_components["fear_greed_classification"] = fng.get("value_classification") if fng else None
        fng_secondary = 0.0
        if fng_value is not None:
            fng_secondary = _linear_interp(float(fng_value), 0.0, 100.0, 0.0, 10.0)
        else:
            fng_secondary = 5.0  # neutral fallback

        baseline = vol_surge_signal + mom_struct + fng_secondary
        s_components["vol_surge_signal"] = round(vol_surge_signal, 1)
        s_components["vol_mcap_ratio"] = round(vol_mcap_ratio, 4)
        s_components["momentum_structure_signal"] = round(mom_struct, 1)
        s_components["fng_secondary_signal"] = round(fng_secondary, 1)
        s_components["baseline_score"] = round(baseline, 1)

    # Divergence: asset 30d vs category median (continuous)
    cat_median = category_median_30d if category_median_30d is not None else 0
    asset_div = change_30d - cat_median
    # v4.2: Dampener in extreme fear (FNG < 25 → 0.5; FNG < 40 → 0.75)
    _dampen = 1.0
    if fng_value and fng_value < 25:
        _dampen = 0.5
    elif fng_value and fng_value < 40:
        _dampen = 0.75
    div_score = max(-15, min(25, asset_div * 0.5 * _dampen))
    # 24h burst
    burst_score = max(-5, min(10, change_24h * 0.5))
    divergence_total = div_score + burst_score
    s_components["category_divergence"] = round(asset_div, 1)
    s_components["divergence_score"] = round(div_score, 1)
    s_components["burst_score"] = round(burst_score, 1)

    # Dev activity
    dev_score = 0.0
    if github_commits_4w is not None:
        s_components["github_commits_4w"] = github_commits_4w
        if github_commits_4w > 300:
            dev_score = 5
        elif github_commits_4w > 100:
            dev_score = 3
        elif github_commits_4w > 30:
            dev_score = 1
        elif github_commits_4w <= 5:
            dev_score = -8
        s_components["dev_activity_score"] = dev_score
    else:
        s_components["github_commits_4w"] = None
        s_components["dev_activity_score"] = None

    # Volatility regime modifier
    vol_regime_score = 0.0
    if low_24h > 0 and high_24h > low_24h:
        daily_range_pct = ((high_24h - low_24h) / low_24h) * 100
        elevated_vol = daily_range_pct > 5  # >5% daily range = elevated
        if elevated_vol and change_7d > 5:
            vol_regime_score = 15  # breakout
        elif elevated_vol and change_7d < -5:
            vol_regime_score = -10  # capitulation
        elif not elevated_vol and change_7d > 3:
            vol_regime_score = 10  # accumulation
        elif not elevated_vol and change_7d < -3:
            vol_regime_score = -5  # stagnation
        s_components["vol_regime"] = "breakout" if vol_regime_score > 10 else "capitulation" if vol_regime_score < -5 else "accumulation" if vol_regime_score > 0 else "stagnation" if vol_regime_score < 0 else "neutral"
    s_components["vol_regime_score"] = round(vol_regime_score, 1)

    # Beta scoring (unchanged logic, continuous)
    beta_score = 0.0
    if asset_betas and asset_betas.get("source") == "30d_rolling":
        dxy_beta = asset_betas.get("dxy_beta", 0)
        vix_beta = asset_betas.get("vix_beta", 0)
        s_components["dxy_beta"] = dxy_beta
        s_components["vix_beta"] = vix_beta
        if dxy_beta < 0:
            beta_score += min(10, abs(dxy_beta) * 10)
        elif dxy_beta > 0.7:
            beta_score -= 5
        if vix_beta < 0:
            beta_score += min(5, abs(vix_beta) * 5)
        s_components["beta_score"] = round(beta_score, 1)
    else:
        # T2 fallback: use CG change_30d relative to BTC as beta proxy
        # assets that outperform BTC get positive beta score
        # This is crude but ensures S pillar isn't structurally 0 for all T2
        if btc_change_30d is not None and change_30d is not None and btc_change_30d != 0:
            rel_perf = (change_30d - btc_change_30d) / abs(btc_change_30d)
            if rel_perf > 0:
                beta_score = min(8.0, rel_perf * 15)
            else:
                beta_score = max(-5.0, rel_perf * 10)
        else:
            beta_score = 0.0
        s_components["beta_score"] = round(beta_score, 1)
        s_components["beta_source"] = "cg_proxy"

    # ── v4.3: Trending rank → S-pillar boost ─────────────────────────
    # CoinGecko trending = top-15 by search volume in 24h (Pro endpoint).
    # Rank 1=highest. Search volume is a leading indicator of social sentiment.
    #   Top 1-3:  +10 to +15 (strong momentum signal)
    #   Top 4-7:  +5 to +9
    #   Top 8-15: +2 to +4
    _trend_rank = _trend_map.get(_sym_key)
    _trend_boost = 0.0
    if _trend_rank is not None and not _is_tradfi:
        if _trend_rank <= 3:
            _trend_boost = _linear_interp(float(_trend_rank), 1.0, 3.0, 15.0, 10.0)
        elif _trend_rank <= 7:
            _trend_boost = _linear_interp(float(_trend_rank), 4.0, 7.0, 9.0, 5.0)
        elif _trend_rank <= 15:
            _trend_boost = _linear_interp(float(_trend_rank), 8.0, 15.0, 4.0, 2.0)
        s_components["trending_rank"] = _trend_rank
        s_components["trending_boost"] = round(_trend_boost, 1)
    else:
        s_components["trending_rank"] = None
        s_components["trending_boost"] = 0

    s_score = round(max(0, min(100, baseline + divergence_total + dev_score + vol_regime_score + beta_score + _trend_boost)), 1)
    # v4.x: NMA narrative modifier injection — applied after base s_score
    # narrative_modifier: +0.10 to +0.15 (STRONG_NARRATIVE, NMA>65)
    #                    -0.05 to -0.10 (NARRATIVE_FADE, NMA<40)
    if narrative_modifier != 0.0:
        s_score = round(max(0, min(100, s_score * (1 + narrative_modifier))), 1)
        s_components["narrative_modifier"] = narrative_modifier
        s_components["nma_injected"] = True
    else:
        s_components["narrative_modifier"] = 0.0
        s_components["nma_injected"] = False

    # ── A — Alpha Independence ───────────────────────────────────────
    # benchmark divergence (-20 to +40) + class independence (0-20) + size efficiency (-5 to +20) + correlation (-15 to 0)
    a_components = {
        "asset_class": asset_class,
        "market_cap_usd": market_cap,
        "ath_distance_pct": ath_distance,
    }

    # Class independence
    # v4.3: L1 raised from 12→18 — L1 ecosystems have equal structural alpha potential as L2.
    # Size-efficiency already zero-scores large-caps; class_ind should not double-penalise them.
    class_ind = 0.0
    if not _is_tradfi:
        class_map = {"DeFi": 20, "RWA": 20, "L2": 18, "L1": 18, "Infrastructure": 15, "Memecoin": 5}
        class_ind = class_map.get(asset_class, 8)
    a_components["class_independence_score"] = class_ind

    # Size efficiency: smaller cap with relatively strong fundamentals → more alpha potential
    size_eff = 0.0
    if market_cap > 100e9:
        size_eff = -5
    elif market_cap > 10e9:
        size_eff = 0
    elif market_cap > 1e9:
        size_eff = 10
    elif market_cap > 100e6:
        size_eff = 15
    else:
        size_eff = 20
    a_components["size_efficiency_score"] = size_eff

    # Benchmark divergence — continuous linear
    div_a_score = 0.0
    if _is_tradfi:
        if spy_change_30d is not None and asset_class != "US Equity":
            if asset_class == "US Bond":
                divergence = spy_change_30d - change_30d
            else:
                divergence = change_30d - spy_change_30d
            a_components["spy_divergence_30d"] = round(divergence, 1)
            div_a_score = max(-20, min(40, divergence * 0.8))
            a_components["alpha_score"] = round(div_a_score, 1)
        else:
            a_components["spy_divergence_30d"] = None
            a_components["alpha_score"] = 0
    else:
        if btc_change_30d is not None:
            divergence = change_30d - btc_change_30d
            a_components["btc_divergence_30d"] = round(divergence, 1)
            div_a_score = max(-20, min(40, divergence * 0.8))
            a_components["alpha_score"] = round(div_a_score, 1)
        elif spy_change_30d is not None:
            divergence = change_30d - spy_change_30d
            a_components["spy_divergence_30d"] = round(divergence, 1)
            a_components["benchmark"] = "SPY (cross-asset)"
            div_a_score = max(-20, min(40, divergence * 0.8))
            a_components["alpha_score"] = round(div_a_score, 1)
        else:
            a_components["btc_divergence_30d"] = None
            a_components["alpha_score"] = 0

    # Correlation discount (from betas)
    # v4.2: In Risk-Off, floor is -8 (less punitive — high correlation is expected in
    # drawdowns; S pillar already penalises macro beta). Other regimes: floor = -20.
    corr_discount = 0.0
    if asset_betas and asset_betas.get("source") == "30d_rolling":
        btc_corr = abs(asset_betas.get("dxy_beta", 0))
        if btc_corr > 0.8:
            _floor = -8 if regime == "Risk-Off" else -20
            corr_discount = max(_floor, _linear_interp(btc_corr, 0.8, 1.0, 0, _floor))
        elif btc_corr > 0.5:
            corr_discount = -8 if regime == "Risk-Off" else -12
    a_components["correlation_discount"] = corr_discount
    a_components["corr_floor_regime"] = regime

    # v4.3: base raised from +10 → +20. Neutral divergence (zero outperformance) anchors at 38+
    # for mid-cap assets rather than 22+. Large-cap L1 floor: 18+0+20 = 38 (was 22).
    a_score = round(max(0, min(100, class_ind + size_eff + div_a_score + corr_discount + 25)), 1)  # v4.3: base +25 (raised from +20)

    # ── Build breakdown ──────────────────────────────────────────────
    breakdown = {
        "fundamental": {"score": f_score, "components": f_components},
        "momentum": {"score": m_score, "components": m_components},
        "risk_adjusted": {"score": o_score, "components": o_components},
        "sensitivity": {"score": s_score, "components": s_components},
        "alpha": {"score": a_score, "components": a_components},
    }

    return {
        "F": f_score,
        "M": m_score,
        "O": o_score,
        "S": s_score,
        "A": a_score,
        "breakdown": breakdown,
    }


def detect_regime(
    btc_30d: float,
    fng_value: int,
    vix: Optional[float],
    btc_dominance: Optional[float] = None,
) -> str:
    """
    Classify macro regime from 4 signals.
    Returns one of: Goldilocks / Risk-On / Easing / Neutral / Tightening / Risk-Off / Stagflation
    Used to shift pillar weights in calculate_total_score().
    """
    vix  = vix  or 20.0
    bdom = btc_dominance or 52.0

    # Goldilocks: strong momentum + greed + calm vol
    if btc_30d > 10 and fng_value > 60 and vix < 17:
        return "Goldilocks"
    # Pure Risk-On: positive momentum + greed (VIX moderate)
    if btc_30d > 5 and fng_value > 55:
        return "Risk-On"
    # Stagflation: high vol + falling crypto + BTC dom surge (flight-to-quality)
    if vix > 27 and btc_30d < -5 and bdom > 58:
        return "Stagflation"
    # Risk-Off: severe fear or crash
    if btc_30d < -12 or fng_value < 28 or vix > 30:
        return "Risk-Off"
    # Tightening: elevated vol + compressed sentiment (rates up / liquidity withdrawal)
    if vix > 21 and fng_value < 48:
        return "Tightening"
    # Easing: calm vol + recovering sentiment (liquidity returning)
    if vix < 17 and fng_value > 45:
        return "Easing"
    return "Neutral"


# Canonical stored regime label. The Mac T1 engine emits UPPER_SNAKE (RISK_ON/RISK_OFF/EASING/…);
# this Railway T2 path's detect_regime returns title-case for its internal _REGIME_MULT/_REGIME_ALIGN
# lookups. When T1 stalls and T2 becomes the fallback writer, storing title-case corrupts the
# cross-engine `cis_scores.macro_regime` contract (2026-07: two formats + "UNKNOWN" coexisted, and a
# title-case "Risk-On" period read as an anti-signal purely from a 2025-05 market window). Normalize
# ONLY the stored/contract value to UPPER_SNAKE so both engines agree; internal lookups keep title-case.
# §GRADE-ALIGN for regime — see MINIMAX_SYNC §REGIME-ALIGN; canonical set confirmed with Minimax.
_CANONICAL_REGIMES = {"GOLDILOCKS", "RISK_ON", "EASING", "NEUTRAL", "TIGHTENING", "RISK_OFF", "STAGFLATION"}


def canonical_regime(r: Optional[str]) -> str:
    """Any regime label (title-case / upper-snake / 'UNKNOWN' / None) → canonical UPPER_SNAKE.
    Unknown/failed markers collapse to NEUTRAL (a valid regime; UNKNOWN is not one consumers accept).

    ⚠️ FOR READS ONLY. This collapses "we do not know" into a VALID REGIME, which is
    right for a consumer that must render something and wrong for anything that
    persists. Use `canonical_regime_strict()` on every WRITE path — see below."""
    if not r:
        return "NEUTRAL"
    s = str(r).strip().upper().replace("-", "_").replace(" ", "_")
    return s if s in _CANONICAL_REGIMES else "NEUTRAL"


def canonical_regime_strict(r: Optional[str]) -> Optional[str]:
    """Canonical UPPER_SNAKE, or **None when the label is missing or unrecognised**.

    WHY THIS EXISTS (2026-08-09). Two bugs found in one query, both from the lenient
    version above being used where a value gets STORED:

    · The daily snapshot passed a missing regime through `canonical_regime()` and
      wrote **NEUTRAL for all 58 symbols** in one batch — measured 2026-08-08, 58
      rows sharing the timestamp 14:14:25.189708, while the same source wrote
      TIGHTENING at 04:04 and 14:53. Once a day, every day.
    · The `/internal/cis-scores` receiver stored the Mac engine's label RAW, so the
      table carries `Tightening` (local_engine, 645 rows) and `TIGHTENING`
      (railway, 749 rows) as if they were different regimes. Canonicalisation was
      happening at READ time and never at WRITE time.

    The first one had a live cost: the ① book sizes exposure off this label,
    TIGHTENING maps to 0.5 and NEUTRAL to 1.0, so the book ran FULL SIZE on the
    first day of its forward record because a fallback default was indistinguishable
    from a real reading.

    **A normaliser that turns "unknown" into a legitimate value belongs on the read
    side only.** On the write side, unmeasured is NULL (I1) — otherwise every
    consumer downstream inherits a fact that was never observed.
    """
    if r is None or str(r).strip() == "":
        return None
    s = str(r).strip().upper().replace("-", "_").replace(" ", "_")
    return s if s in _CANONICAL_REGIMES else None


def calculate_total_score(
    pillars: Dict[str, float],
    asset_class: str,
    regime: str = "Neutral",
    ic_mult: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Calculate weighted total CIS score with three-layer pillar weights:
      1. Base weights (per asset class)
      2. Regime multipliers (market cycle adjustment)
      3. IC multipliers (Simons feedback — Pearson IC from paper trades)
    ic_mult is optional; if None or empty, layer 3 is skipped (neutral).
    """

    # Base weights per asset class
    # CANONICAL base weights — single source of truth: CIS_BASE_WEIGHTS.md (GRADE-ALIGN 2026-07-02).
    # T1 (cis_v4_engine.py BASE_WEIGHTS, R≡O) MUST adopt this SAME table for "same pillars → same
    # grade across engines" to hold. Changed vs prior T2: Infrastructure, Memecoin, US Equity,
    # US Bond, Commodity (see CIS_BASE_WEIGHTS.md reconciliations). Regime-neutral; regime is a
    # separate multiplier applied on top (Option B).
    _BASE_WEIGHTS: Dict[str, Dict[str, float]] = {
        "Crypto":         {"F": 0.25, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.15},
        "L1":             {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "L2":             {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "DeFi":           {"F": 0.25, "M": 0.25, "O": 0.25, "S": 0.15, "A": 0.10},
        "RWA":            {"F": 0.35, "M": 0.20, "O": 0.20, "S": 0.15, "A": 0.10},
        "Infrastructure": {"F": 0.30, "M": 0.25, "O": 0.20, "S": 0.15, "A": 0.10},
        "AI":             {"F": 0.20, "M": 0.30, "O": 0.20, "S": 0.15, "A": 0.15},
        "Gaming":         {"F": 0.20, "M": 0.30, "O": 0.15, "S": 0.25, "A": 0.10},
        "NFT":            {"F": 0.15, "M": 0.25, "O": 0.15, "S": 0.30, "A": 0.15},
        "Memecoin":       {"F": 0.10, "M": 0.30, "O": 0.10, "S": 0.40, "A": 0.10},
        "US Equity":      {"F": 0.35, "M": 0.25, "O": 0.20, "S": 0.10, "A": 0.10},
        "US Bond":        {"F": 0.35, "M": 0.10, "O": 0.30, "S": 0.10, "A": 0.15},
        "Commodity":      {"F": 0.25, "M": 0.30, "O": 0.15, "S": 0.20, "A": 0.10},
        "FX":             {"F": 0.25, "M": 0.25, "O": 0.20, "S": 0.20, "A": 0.10},
        "EM Equity":      {"F": 0.30, "M": 0.25, "O": 0.15, "S": 0.20, "A": 0.10},
        "Real Estate":    {"F": 0.40, "M": 0.15, "O": 0.20, "S": 0.15, "A": 0.10},
        "Alternative":    {"F": 0.25, "M": 0.20, "O": 0.25, "S": 0.15, "A": 0.15},
    }

    # Regime multipliers — applied to base weights, then renormalized to sum=1.
    # Philosophy:
    #   Risk-On   → momentum + sentiment + alpha outperform; fundamentals matter less
    #   Risk-Off  → fundamentals + risk-adjusted protection; sentiment suppressed
    #   Tightening→ fundamentals dominate; momentum punished; risk-adj rises
    #   Easing    → alpha + momentum rewarded; fundamentals secondary
    #   Stagflation→ fundamentals + risk-adj paramount; sentiment & momentum penalized
    #   Goldilocks→ balanced but alpha + sentiment elevated
    _REGIME_MULT: Dict[str, Dict[str, float]] = {
        "Goldilocks":  {"F": 0.90, "M": 1.10, "O": 0.90, "S": 1.15, "A": 1.25},
        "Risk-On":     {"F": 0.85, "M": 1.20, "O": 0.85, "S": 1.20, "A": 1.25},
        "Easing":      {"F": 0.90, "M": 1.15, "O": 0.95, "S": 1.10, "A": 1.20},
        "Neutral":     {"F": 1.00, "M": 1.00, "O": 1.00, "S": 1.00, "A": 1.00},
        "Tightening":  {"F": 1.25, "M": 0.85, "O": 1.20, "S": 0.90, "A": 1.05},
        "Risk-Off":    {"F": 1.20, "M": 0.80, "O": 1.25, "S": 0.85, "A": 1.10},
        "Stagflation": {"F": 1.30, "M": 0.75, "O": 1.25, "S": 0.70, "A": 1.00},
    }

    base = dict(_BASE_WEIGHTS.get(asset_class, _BASE_WEIGHTS["Crypto"]))
    mult = _REGIME_MULT.get(regime, _REGIME_MULT["Neutral"])

    # Layer 1+2: base × regime
    w = {k: base[k] * mult[k] for k in base}

    # Layer 3: Simons IC feedback — apply per-pillar IC strength multipliers
    if ic_mult:
        for k in w:
            if k in ic_mult:
                w[k] *= ic_mult[k]

    # Renormalize so weights always sum to 1.0
    total_w = sum(w.values())
    w = {k: round(v / total_w, 4) for k, v in w.items()}

    # Handle None pillar values - replace with 0
    f_val = pillars.get("F") or 0
    m_val = pillars.get("M") or 0
    o_val = pillars.get("O") or 0
    s_val = pillars.get("S") or 0
    a_val = pillars.get("A") or 0

    # v4.2: raw_cis_score = base weights only (no regime adjustment)
    # This shows "what pillars actually score" before market regime adjustment
    base = dict(_BASE_WEIGHTS.get(asset_class, _BASE_WEIGHTS["Crypto"]))
    raw_total = (
        base["F"] * f_val +
        base["M"] * m_val +
        base["O"] * o_val +
        base["S"] * s_val +
        base["A"] * a_val
    )

    # Calculate contributions (regime-adjusted weights)
    contributions = {
        "fundamental": {
            "score": f_val,
            "weight": w["F"],
            "contribution": round(w["F"] * f_val, 2),
        },
        "momentum": {
            "score": m_val,
            "weight": w["M"],
            "contribution": round(w["M"] * m_val, 2),
        },
        "risk_adjusted": {
            "score": o_val,
            "weight": w["O"],
            "contribution": round(w["O"] * o_val, 2),
        },
        "sensitivity": {
            "score": s_val,
            "weight": w["S"],
            "contribution": round(w["S"] * s_val, 2),
        },
        "alpha": {
            "score": a_val,
            "weight": w["A"],
            "contribution": round(w["A"] * a_val, 2),
        },
    }

    total = (
        w["F"] * f_val +
        w["M"] * m_val +
        w["O"] * o_val +
        w["S"] * s_val +
        w["A"] * a_val
    )

    return {
        "total_score": round(total, 1),
        "raw_cis_score": round(raw_total, 1),  # v4.2: pre-regime base score
        "weights": w,
        "contributions": contributions,
    }


def get_grade(score: float) -> str:
    """
    Unified absolute grading — v4.1.
    Both Railway and Mac Mini engines use these identical thresholds.
    See CIS_METHODOLOGY.md §5.
    """
    if score >= 85:  return "A+"
    if score >= 75:  return "A"
    if score >= 65:  return "B+"
    if score >= 55:  return "B"
    if score >= 45:  return "C+"
    if score >= 35:  return "C"
    if score >= 25:  return "D"
    return "F"


def compute_percentile_ranks(universe: list) -> list:
    """
    Compute percentile rank as METADATA only — does NOT override grades.
    v4.1: Grades come from absolute thresholds via get_grade().
    Percentile is still exposed in API for agents that want relative positioning.
    """
    if not universe:
        return universe
    n = len(universe)
    sorted_u = sorted(universe, key=lambda x: x.get("cis_score", 0), reverse=True)
    for i, asset in enumerate(sorted_u):
        rank = round(((n - i) / n) * 100, 1)
        asset["percentile_rank"] = rank
        # v4.1: NO grade override — absolute grades stand
    return sorted_u


def calculate_las(
    cis_score: float,
    volume_24h: float,
    high_24h: float,
    low_24h: float,
    confidence: float,
    aum: float = 30_000_000,
    max_position_pct: float = 0.05,
    participation_rate: float = 0.10,
) -> Dict[str, Any]:
    """
    Liquidity-Adjusted Score — v4.1.
    See CIS_METHODOLOGY.md §6.
    """
    target_position = aum * max_position_pct
    daily_tradeable = volume_24h * participation_rate

    if target_position > 0 and daily_tradeable > 0:
        liq_mult = min(1.0, daily_tradeable / target_position)
    elif daily_tradeable > 0:
        liq_mult = 1.0
    else:
        liq_mult = 0.0

    # Floor: any asset in the curated universe has at least 15% liquidity credit.
    # Prevents near-zero LAS from CoinGecko / yfinance volume data quality gaps
    # (e.g. MKR reporting $42K volume when real CEX volume is $50M+).
    liq_mult = max(liq_mult, 0.15)

    # Spread penalty
    spread_penalty = 1.0
    if low_24h > 0 and high_24h > low_24h:
        hl_range = (high_24h - low_24h) / low_24h
        if hl_range > 0.05:
            spread_penalty = max(0.8, 1.0 - (hl_range - 0.05) * 2)

    las = round(cis_score * liq_mult * spread_penalty * confidence, 1)

    return {
        "las": max(0, las),
        "las_params": {
            "assumed_aum": aum,
            "participation_rate": participation_rate,
            "liquidity_multiplier": round(liq_mult, 3),
            "spread_penalty": round(spread_penalty, 3),
            "daily_tradeable_usd": round(daily_tradeable, 0),
        },
    }


def get_signal(score: float, grade: str) -> str:
    """
    CIS positioning signal — v4.1 compliance-safe.
    NO buy/sell language — we are not licensed investment advisors.
    These are quantitative positioning indicators, not investment recommendations.
    """
    if grade == "A+":
        return "STRONG OUTPERFORM"
    if grade in ("A", "B+"):
        return "OUTPERFORM"
    if grade in ("B", "C+"):
        return "NEUTRAL"
    if grade == "C":
        return "UNDERPERFORM"
    return "UNDERWEIGHT"  # D, F


async def calculate_cis_universe() -> Dict[str, Any]:
    """
    Calculate CIS scores for all tracked assets.
    Returns the complete universe with scores.

    Data sources:
    - Crypto: CoinGecko API
    - US Equities/Bonds/Commodities: yfinance
    """
    # ── v4.2 pre-fetch helpers ────────────────────────────────────────
    async def _fetch_cg_dev_bulk() -> dict:
        """Pre-fetch CG Pro developer_data for all tech assets. 24h Redis TTL."""
        _tech_classes = {"L1", "L2", "DeFi", "Infrastructure", "AI", "RWA"}
        _sem = asyncio.Semaphore(4)
        _results: dict = {}
        async def _one(aid: str, cg_id: str):
            async with _sem:
                try:
                    try:
                        from src.data.market.data_layer import get_cg_developer_data
                    except ImportError:
                        from data.market.data_layer import get_cg_developer_data
                    data = await get_cg_developer_data(cg_id)
                    if data and "error" not in data:
                        _results[aid] = data
                except Exception:
                    pass
        tasks = [
            _one(aid, cfg["coingecko"])
            for aid, cfg in CRYPTO_ASSETS.items()
            if cfg.get("class") in _tech_classes and cfg.get("coingecko")
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return _results

    async def _fetch_eodhd_bulk() -> dict:
        """Pre-fetch EODHD fundamentals for US Equity assets. 6h Redis TTL."""
        _sem = asyncio.Semaphore(3)
        _results: dict = {}
        async def _one(aid: str, ticker: str):
            async with _sem:
                try:
                    try:
                        from src.data.market.data_layer import get_eodhd_fundamentals
                    except ImportError:
                        from data.market.data_layer import get_eodhd_fundamentals
                    data = await get_eodhd_fundamentals(ticker, "US")
                    if data and "error" not in data:
                        _results[aid] = data
                except Exception:
                    pass
        tasks = [
            _one(aid, cfg["yfinance"])
            for aid, cfg in US_EQUITIES.items()
            if cfg.get("yfinance")
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return _results

    async def _fetch_narrative_signals() -> dict:
        """
        v4.x: Pre-fetch NMA narrative signals for crypto assets.
        Feeds S-pillar modifier injection in calculate_cis_score().
        Falls back gracefully if narrative module is unavailable.
        """
        try:
            from data.narrative.narrative_engine import batch_narrative_signals
            from data.narrative import social_collector, orderflow_collector
        except ImportError:
            try:
                from src.data.narrative.narrative_engine import batch_narrative_signals
                from src.data.narrative import social_collector, orderflow_collector
            except ImportError:
                _logger.debug("[CIS·NMA] narrative module unavailable — skipping")
                return {}

        _crypto_ids = ["BTC","ETH","SOL","BNB","XRP","ADA","AVAX","DOT","NEAR","SUI","APT","HYPE",
                       "ARB","OP","LINK","UNI","AAVE","MKR","LDO","PENDLE","INJ","TIA","ONDO"]
        try:
            signals = await batch_narrative_signals(_crypto_ids, social_collector, orderflow_collector)
            # Build {symbol: nma_score} map for calculate_cis_score injection
            return {sym: sig.nma_score for sym, sig in signals.items()}
        except Exception as e:
            _logger.warning(f"[CIS·NMA] narrative batch failed: {e}")
            return {}

    # v4.x: NMA modifier lookup — maps NMA score → S-pillar modifier
    def _get_narrative_modifier(symbol: str, nma_map: dict) -> float:
        """Compute S-pillar modifier from NMA score. 0.0 if NMA unavailable."""
        nma = nma_map.get(symbol)
        if nma is None:
            return 0.0
        if nma >= 65:
            modifier = 0.10 + (nma - 65) / (80 - 65) * 0.05
            return round(min(0.15, modifier), 3)
        elif nma <= 40:
            modifier = -0.05 - (40 - nma) / (40 - 25) * 0.05
            return round(max(-0.10, modifier), 3)
        return 0.0

    # Fetch all data concurrently — including CG Pro derivatives + trending for pillar wiring
    try:
        from src.data.market.data_layer import get_derivatives_map, get_trending_map
    except ImportError:
        from data.market.data_layer import get_derivatives_map, get_trending_map

    # ── Per-branch bounds (2026-08-07, S-104) ────────────────────────────────
    # The gather below was already concurrent, so the build cost is the SLOWEST
    # branch, not the sum. But it had no per-branch timeout: the only bound was
    # the caller's 12 s build budget in cis.py, and when that fired it cancelled
    # the WHOLE gather — discarding the nine branches that had already returned
    # successfully. Measured 2026-08-07: total 17,358 ms of which railway_t2 was
    # 16,476 ms, and the merged payload had not advanced for 56 minutes. Every
    # 30 s the response cache expired, one unlucky request paid 10–14 s, the
    # build blew its budget, and the same stale payload was served again. T2 was
    # not slow, it was never completing.
    #
    # Two rules, both already stated elsewhere in this codebase and both violated
    # here because the boundary they were written for was one layer up:
    #   1. decoration must never gate the payload   (cis.py: "enrichment moved
    #      outside the lock" — same rule, never carried into T2's own fan-out)
    #   2. a bound on the whole is not a bound on the parts — an all-or-nothing
    #      build converts one slow dependency into zero fresh data
    #
    # So: each branch gets its own budget sized by how much the payload actually
    # needs it, and a branch that overruns yields its default instead of killing
    # the build. Budgets total well under the caller's 12 s because they run
    # concurrently — the ceiling is max(), not sum().
    _BRANCH_BUDGET_S = {
        # core — the payload is wrong without these
        "binance":     float(os.environ.get("CIS_T2_BUDGET_BINANCE_S",  "8")),
        "cg_markets":  float(os.environ.get("CIS_T2_BUDGET_CGMKT_S",    "8")),
        "defillama":   float(os.environ.get("CIS_T2_BUDGET_LLAMA_S",    "6")),
        # decoration — the payload is merely less rich without these
        "fng":         float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
        "github":      float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
        "cg_dev":      float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
        "eodhd":       float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
        "derivatives": float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
        "trending":    float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
        "ic_mult":     float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
        "nma":         float(os.environ.get("CIS_T2_BUDGET_DECOR_S",    "3")),
    }
    _branch_ms: dict = {}
    _branch_timeouts: list = []

    async def _bounded(name: str, coro, default):
        """Run one branch under its own budget. Overrun or failure yields the
        default and is RECORDED — a branch that silently degrades to {} is how
        a dead provider stays invisible (Lesson: a guard must observe the real
        artifact). Timing is kept for /health so the next slow build is one
        glance, not an investigation."""
        _t = time.time()
        try:
            return await asyncio.wait_for(coro, timeout=_BRANCH_BUDGET_S.get(name, 5.0))
        except asyncio.TimeoutError:
            _branch_timeouts.append(name)
            _logger.warning(f"[CIS·T2] branch '{name}' exceeded "
                            f"{_BRANCH_BUDGET_S.get(name, 5.0)}s — using default, build continues")
            return default
        except Exception as e:
            _branch_timeouts.append(f"{name}:err")
            _logger.warning(f"[CIS·T2] data source '{name}' failed: {e}")
            return default
        finally:
            _branch_ms[f"{name}_ms"] = int((time.time() - _t) * 1000)

    _t_fanout = time.time()
    (binance_prices, cg_markets, llama_tvl, fng, github_activity, cg_dev_data,
     eodhd_data, _deriv_map, _trend_map, _ic_mult, _nma_map) = await asyncio.gather(
        _bounded("binance",     fetch_binance_prices(),   {}),
        _bounded("cg_markets",  fetch_cg_markets(),       []),
        _bounded("defillama",   fetch_defillama_tvl(),    {}),
        _bounded("fng",         fetch_fear_greed(),       {}),
        # Phase 2B: dev activity (best-effort, 2h cache)
        _bounded("github",      fetch_github_activity(),  {}),
        # v4.2: CG Pro developer data for tech assets. 25 assets behind Semaphore(4)
        # = 7 serial waves at 15 s per call — the prime suspect for the 16.5 s and
        # the reason this branch is capped hardest. It is 24 h-cadence data; it has
        # no business gating a live payload at all (see fix ladder step 4).
        _bounded("cg_dev",      _fetch_cg_dev_bulk(),     {}),
        # v4.2: EODHD fundamentals for US Equity
        _bounded("eodhd",       _fetch_eodhd_bulk(),      {}),
        # v4.3: funding rates + OI → O-pillar adjustment
        _bounded("derivatives", get_derivatives_map(),    {}),
        # v4.3: trending rank → S-pillar boost
        _bounded("trending",    get_trending_map(),       {}),
        # Simons: IC-based pillar weight feedback
        _bounded("ic_mult",     _refresh_ic_multipliers(),
                 {"F": 1.0, "M": 1.0, "O": 1.0, "S": 1.0, "A": 1.0}),
        # v4.x: NMA narrative signals for S-pillar injection (bulk fetch for all
        # crypto symbols). NOTE: this is a single bulk call — there is no per-asset
        # `is_tradfi` context here. A stray `if not is_tradfi else ...` referenced a
        # loop-local before assignment, raising UnboundLocalError on EVERY call and
        # silently killing the entire Railway T2 universe (blank leaderboard whenever
        # the Mac Mini cache lapsed). Fixed 2026-06-05.
        _bounded("nma",         _fetch_narrative_signals(), {}),
    )
    _branch_ms["fanout_total_ms"] = int((time.time() - _t_fanout) * 1000)
    if _branch_timeouts:
        _branch_ms["degraded_branches"] = _branch_timeouts
    if _branch_ms:
        _slow = {k: v for k, v in _branch_ms.items()
                 if k.endswith("_ms") and k != "fanout_total_ms"}
        if _slow:
            _branch_ms["slowest_branch"] = max(_slow, key=_slow.get)

    # Merge: Binance as primary (speed), CoinGecko enriches missing fields
    # Binance has: price, change_24h, volume, high/low
    # CoinGecko has: market_cap, change_7d, change_30d, circ_supply, ATH distance
    merged_markets = {}
    for asset_id in ASSETS_CONFIG.keys():
        cg_id = ASSETS_CONFIG[asset_id].get("coingecko", "")
        cg_data = cg_markets.get(cg_id, {})

        if asset_id in binance_prices:
            rec = dict(binance_prices[asset_id])  # copy
            # Enrich from CoinGecko for fields Binance doesn't provide
            if cg_data:
                # Handle None values properly
                cg_7d = cg_data.get("change_7d")
                cg_30d = cg_data.get("change_30d")
                rec["change_7d"] = cg_7d if cg_7d is not None else rec.get("change_7d")
                rec["change_30d"] = cg_30d if cg_30d is not None else rec.get("change_30d")
                cg_mc = cg_data.get("market_cap", 0) or 0
                cg_fdv = cg_data.get("fdv", 0) or 0
                cg_supply = cg_data.get("circulating_supply", 0) or 0
                cg_total_supply = cg_data.get("total_supply", 0) or 0
                # CG sometimes returns market_cap=0 for rebranded tokens (e.g. MKR→SKY).
                # Fallback chain: price×circ_supply → price×total_supply → FDV → volume×20
                if cg_mc == 0:
                    price = rec.get("price", 0) or cg_data.get("price", 0) or 0
                    if cg_supply > 0 and price > 0:
                        cg_mc = price * cg_supply
                    elif cg_total_supply > 0 and price > 0:
                        # circ_supply=0 but total_supply exists (e.g. MKR rebrand)
                        cg_mc = price * cg_total_supply
                    elif cg_fdv > 0:
                        cg_mc = cg_fdv
                    else:
                        volume = rec.get("volume_24h", 0) or cg_data.get("volume_24h", 0) or 0
                        if volume > 0:
                            cg_mc = volume * 20  # vol ~5% of mcap → ×20 conservative
                rec["market_cap"] = cg_mc
                rec["fdv"] = cg_fdv
                rec["circulating_supply"] = cg_supply
                rec["total_supply"] = cg_total_supply
                rec["ath_change_percentage"] = cg_data.get("ath_change_percentage", 0) or 0
            else:
                # Fallback: estimate market_cap from volume when CoinGecko fails entirely
                volume = rec.get("volume_24h", 0) or 0
                if volume > 0 and rec.get("market_cap", 0) == 0:
                    rec["market_cap"] = volume * 20  # Conservative estimate
            merged_markets[asset_id] = rec
        elif cg_data:
            merged_markets[asset_id] = cg_data

    # ── Cross-venue overlay ───────────────────────────────────────────────────
    # Applied AFTER the Binance/CoinGecko merge so it wins on the two fields a
    # single spot venue gets wrong for perp-native assets: price and volume.
    # CoinGecko supplies market cap and supply (which it gets right); the
    # overlay supplies traded reality. Keeping mcap from CG and volume from the
    # venues is deliberate — mixing a correct mcap with ONE venue's volume is
    # precisely what produced volume_mcap_ratio=0.0002 on HYPE.
    # ── S-198 (2026-08-23): time what happens AFTER the fanout ──────────────
    # S-104 added per-branch timing for the fan-out and the bottleneck promptly
    # moved outside it. Measured in production 2026-08-23: railway_t2_ms =
    # 110,390 against a 12,000 ms budget, while every timed branch summed to
    # 19,250 — **91 seconds with no owner**. The build blew its budget, was
    # cancelled, and `/cis/universe` served 43 T1-only assets with
    # macro_regime=None instead of the merged 58.
    #
    # The measurement has to follow the failure. Everything from here to the
    # per-asset loop is now attributed.
    _t_post = time.time()
    try:
        _venue_overlay = await fetch_venue_overlay()
    except Exception as _e:                                        # noqa: BLE001
        _logger.warning("venue overlay unavailable: %s", _e)
        _venue_overlay = {}
    _branch_ms["post_venue_overlay_ms"] = int((time.time() - _t_post) * 1000)

    for _aid, _v in (_venue_overlay or {}).items():
        _rec = dict(merged_markets.get(_aid) or {})
        _cgv = cg_markets.get(ASSETS_CONFIG.get(_aid, {}).get("coingecko", ""), {}) or {}
        _rec.update({
            "symbol": _aid,
            "name": _rec.get("name") or _cgv.get("name") or _aid,
            "price": _v["price"],
            "volume_24h": _v["volume_24h"],
            "source": "venue_consolidated",
            "venue_confidence": _v.get("venue_confidence"),
            "venues_used": _v.get("venues_used"),
        })
        # Fields the venues do not carry — keep CoinGecko's.
        for _k in ("market_cap", "fdv", "circulating_supply", "total_supply",
                   "change_7d", "change_30d", "ath_change_percentage"):
            if not _rec.get(_k):
                _rec[_k] = _cgv.get(_k) or _rec.get(_k) or 0
        if _rec.get("change_24h") is None:
            _rec["change_24h"] = _cgv.get("change_24h") or 0
        merged_markets[_aid] = _rec

        # Feed the O pillar. Before this, HYPE's breakdown carried
        # funding_rate=null, oi_usd=null, funding_signal="N/A (no derivatives)"
        # and funding_adj=oi_adj=0.0 — the engine believed the largest perp DEX
        # in crypto had no derivatives market, so an entire scoring dimension
        # was silently zeroed rather than measured.
        if _deriv_map is not None and _v.get("open_interest_usd"):
            _existing = dict(_deriv_map.get(_aid, {}) or {})
            _existing.setdefault("funding_signal", "cross_venue")
            _existing.update({
                "funding_rate": _v.get("funding_rate"),
                "open_interest_usd": _v.get("open_interest_usd"),
                "funding_by_venue": _v.get("funding_by_venue"),
                "funding_spread": _v.get("funding_spread"),
                "source": "venue_consolidated",
            })
            _deriv_map[_aid] = _existing

    # Fetch TradFi price data — EODHD primary (yfinance is rate-limited and has
    # blocked the portal); yfinance kept only as a last-resort fallback.
    yf_data = {}
    yf_assets = {**US_EQUITIES, **BONDS, **COMMODITIES, **FX, **REAL_ESTATE, **EM_EQUITY}
    yf_sem = asyncio.Semaphore(5)
    try:
        from src.data.market.data_layer import get_eodhd_eod_data
    except ImportError:
        try:
            from data.market.data_layer import get_eodhd_eod_data
        except ImportError:
            get_eodhd_eod_data = None

    async def _fetch_yf(sym, cfg):
        ticker = cfg["yfinance"]
        async with yf_sem:
            # EODHD first
            if get_eodhd_eod_data is not None:
                try:
                    eod = await get_eodhd_eod_data(ticker, "US")
                    if eod and eod.get("price"):
                        return sym, eod
                except Exception:
                    pass
            # Fallback: yfinance
            return sym, await get_yfinance_data(ticker)

    _t_yf = time.time()
    yf_results = await asyncio.gather(
        *[_fetch_yf(sym, cfg) for sym, cfg in yf_assets.items()],
        return_exceptions=True
    )
    for item in yf_results:
        if isinstance(item, Exception):
            continue
        sym, data = item
        if data:
            yf_data[sym] = data

    # Macro data fetch — VIX needed for regime detection + S pillar
    _branch_ms["post_yfinance_ms"] = int((time.time() - _t_yf) * 1000)
    _t_macro = time.time()
    macro_data_early = await fetch_macro_data()
    _branch_ms["post_macro_ms"] = int((time.time() - _t_macro) * 1000)
    live_vix = macro_data_early.get("vix")

    # Macro regime determination — 7-state classifier using 4 signals
    btc_data = merged_markets.get("BTC", {})
    btc_30d = btc_data.get("change_30d", 0) or 0 if btc_data else 0
    fng_value = int(fng.get("value", 50) or 50) if fng else 50
    btc_dom = macro_data_early.get("btc_dominance")  # from fetch_macro_data CG global
    regime = detect_regime(btc_30d, fng_value, live_vix, btc_dom)

    # Benchmarks for non-crypto scoring
    spy_30d = (yf_data.get("SPY", {}) or {}).get("change_30d", None)

    # v4.1: Pre-compute category median 30d change for S pillar divergence
    category_changes = {}  # {class: [change_30d, ...]}
    for aid, cfg in ASSETS_CONFIG.items():
        ac = cfg["class"]
        if ac in ["US Equity", "US Bond", "Commodity"]:
            md = yf_data.get(aid, {})
        else:
            md = merged_markets.get(aid, {})
        if md:
            c30 = md.get("change_30d", 0) or 0
            category_changes.setdefault(ac, []).append(c30)
    category_medians = {}
    for ac, changes in category_changes.items():
        sorted_c = sorted(changes)
        n = len(sorted_c)
        category_medians[ac] = sorted_c[n // 2] if n else 0

    # Calculate scores for each asset
    universe = []

    # Pre-fetch klines for all crypto assets that need beta calculation (avoid N serial HTTP calls)
    try:
        from src.data.market.data_layer import get_klines as _gk
    except ImportError:
        try:
            from data.market.data_layer import get_klines as _gk
        except ImportError:
            _gk = None
    _kline_tasks = {}
    if _gk is not None:
        for aid, cfg in ASSETS_CONFIG.items():
            ac = cfg["class"]
            if ac not in ["US Equity", "US Bond", "Commodity"] and aid in BINANCE_SYMBOLS:
                sym = BINANCE_SYMBOLS[aid].upper().replace("USDT", "") + "USDT"
                _kline_tasks[aid] = _gk(sym, months=1)
    _t_kl = time.time()
    _kline_results = await asyncio.gather(*_kline_tasks.values(), return_exceptions=True) if _kline_tasks else []
    _branch_ms["post_klines_ms"] = int((time.time() - _t_kl) * 1000)
    _kline_map = {}
    for aid, result in zip(_kline_tasks.keys(), _kline_results):
        if not isinstance(result, Exception) and result and len(result) >= 20:
            _kline_map[aid] = [k["close"] for k in result]

    for asset_id, config in ASSETS_CONFIG.items():
        asset_class = config["class"]

        # Get market data based on asset type
        _is_yfinance_asset = asset_class in ["US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"]
        if _is_yfinance_asset:
            # Use yfinance data
            market_data = yf_data.get(asset_id, {})
            tvl = 0  # No TVL for traditional assets
        else:
            # Use merged markets (Binance primary, CoinGecko fallback)
            market_data = merged_markets.get(asset_id, {})
            tvl = llama_tvl.get(asset_id, 0)

        # Skip if no market data
        if not market_data:
            continue

        # Calculate pillar scores with breakdown
        is_tradfi = asset_class in ["US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"]
        # BTC: no BTC benchmark (can't compare to itself); spy_change_30d passed so A pillar uses SPY cross-asset
        # Other crypto: use BTC 30d as benchmark
        # TradFi: no BTC benchmark; use SPY (with SPY itself excluded)
        asset_btc_30d = btc_30d if (asset_id != "BTC" and not is_tradfi) else None
        asset_spy_30d = spy_30d if (is_tradfi and asset_id != "SPY") or asset_id == "BTC" else None
        gh_commits = github_activity.get(asset_id)

        # Calculate betas for crypto assets (pre-fetched above to avoid serial HTTP calls)
        asset_betas = None
        if not is_tradfi and asset_id in _kline_map:
            try:
                prices = _kline_map[asset_id]
                _t_b = time.time()
                asset_betas = await calculate_asset_betas(asset_id, prices)
                # ACCUMULATED, not overwritten — this sits inside the per-asset
                # loop, so one call's duration says nothing. 43 sequential awaits
                # is exactly the shape that hides in an unattributed total.
                _branch_ms["post_betas_ms_total"] = (
                    _branch_ms.get("post_betas_ms_total", 0)
                    + int((time.time() - _t_b) * 1000))
            except Exception as e:
                _logger.warning(f"[CIS] beta calculation failed for {asset_id}: {e}")

        # v4.2: resolve per-asset enrichment data
        asset_dev_score = (cg_dev_data.get(asset_id) or {}).get("dev_activity_score") if not is_tradfi else None
        asset_eodhd = eodhd_data.get(asset_id) if asset_class == "US Equity" else None

        try:
            pillars_result = calculate_cis_score(
                market_data, tvl, fng, asset_class,
                asset_id=asset_id,
                btc_change_30d=asset_btc_30d,
                github_commits_4w=gh_commits,
                vix=live_vix if is_tradfi else None,
                spy_change_30d=asset_spy_30d,
                asset_betas=asset_betas,
                category_median_30d=category_medians.get(asset_class, 0),
                dev_activity_score=asset_dev_score,
                eodhd_fundamentals=asset_eodhd,
                regime=regime,
                _deriv_map=_deriv_map,
                _trend_map=_trend_map,
                narrative_modifier=_get_narrative_modifier(asset_id, _nma_map),
            )
        except Exception as e:
            _logger.warning(f"[CIS] score calculation failed for {asset_id} ({asset_class}): {e}")
            continue
        pillars = {k: v for k, v in pillars_result.items() if k != "breakdown"}
        breakdown = pillars_result.get("breakdown", {})

        # Calculate total with three-layer weights: base → regime → IC feedback
        total_result = calculate_total_score(pillars, asset_class, regime=regime, ic_mult=_ic_mult)
        total_score = total_result["total_score"]
        raw_cis_score = total_result.get("raw_cis_score", total_score)  # v4.2: base score
        weights = total_result["weights"]
        contributions = total_result["contributions"]

        # GRADE-ALIGN Option B (SCHEMA 1.1): grade reflects QUALITY (regime-neutral raw_cis_score),
        # NOT the regime-adjusted score. Regime is a SEPARATE exposure axis — it lives in `signal`
        # and `recommended_weight`, never in the grade. So a B+ asset stays B+ across regimes; the
        # regime tells you whether to *act* on it now. (T1 cis_v4_engine MUST mirror this — same
        # pillars → same grade. See MINIMAX_SYNC §GRADE-ALIGN.)
        grade = get_grade(raw_cis_score)                       # quality grade (regime-neutral)
        signal = get_signal(total_score, get_grade(total_score))  # positioning (regime-aware)

        # 30d price change
        change_30d = market_data.get("change_30d", 0) or 0
        change_7d = market_data.get("change_7d", 0) or 0

        # Volatility (from 24h high/low)
        high_24h = market_data.get("high_24h", 0) or 0
        low_24h = market_data.get("low_24h", 0) or 0
        volatility_30d = 0
        if low_24h > 0 and high_24h > low_24h:
            volatility_30d = round((high_24h - low_24h) / low_24h * 100, 1)

        # Percentile (simplified - based on score)
        percentile = int(min(99, max(1, total_score)))

        # Merge contributions into breakdown
        for key in contributions:
            if key in breakdown:
                breakdown[key]["weight"] = contributions[key]["weight"]
                breakdown[key]["contribution"] = contributions[key]["contribution"]

        # Data completeness (confidence) — asset-class-aware.
        # TradFi / Commodity ETFs don't have TVL or crypto FNG, so we only
        # score them on fields that are actually available for their class.
        _is_tradfi_class = asset_class in (
            "US Equity", "US Bond", "Commodity", "FX", "Real Estate", "EM Equity"
        )
        data_completeness = {
            "price": bool(market_data.get("price", 0)),
            "volume": bool(market_data.get("volume_24h", 0)),
            "market_cap": bool(market_data.get("market_cap", 0)),
        }
        if not _is_tradfi_class:
            # Crypto-native fields — only penalise crypto assets for missing these
            data_completeness["tvl"] = bool(tvl and tvl > 0)
            data_completeness["sentiment"] = bool(fng and fng.get("value"))
            data_completeness["circulating_supply"] = bool(market_data.get("circulating_supply", 0))
        # Confidence score: 0-1 based on applicable data completeness
        confidence = round(sum(data_completeness.values()) / len(data_completeness), 2)

        # Get CIS score change from history
        score_change_7d = 0
        score_change_30d = 0
        try:
            from .history_db import get_score_change
            sc_30d = get_score_change(asset_id, days=30)
            if sc_30d:
                score_change_30d = round(sc_30d.get("change", 0), 1)
            sc_7d = get_score_change(asset_id, days=7)
            if sc_7d:
                score_change_7d = round(sc_7d.get("change", 0), 1)
        except Exception as e:
            _logger.warning(f"[CIS] score change fetch failed for {asset_id}: {e}")

        # Max drawdown estimation (simplified from ath_distance)
        ath_distance = abs(market_data.get("ath_change_percentage", 0) or 0)
        max_drawdown_90d = min(ath_distance, 90)  # Cap at 90%

        # v4.1: Liquidity-Adjusted Score
        _vol_24h = market_data.get("volume_24h", 0) or 0
        _h24 = market_data.get("high_24h", 0) or 0
        _l24 = market_data.get("low_24h", 0) or 0
        las_result = calculate_las(total_score, _vol_24h, _h24, _l24, confidence)

        # v4.3: Apply OI leverage penalty to LAS — high OI/MCap = systemic liquidation risk
        #
        # 2026-08-06: this block referenced a bare `market_cap`, which exists as a local
        # in calculate_cis_asset() but NOT here — so every asset carrying open interest
        # raised NameError, and because the raise happened inside the per-asset loop it
        # killed the whole T2 universe calculation. The caller swallowed it into a
        # warning log, so T2 had been dead silently: T1 (Mac) was carrying production
        # alone with no working fallback, and the failed attempt still burned ~5.2 s on
        # every rebuild — the reproducible 12 s budget overrun.
        # Found only once /health began reporting build-phase timings; three earlier
        # hypotheses for that latency were wrong. Use the same defensive read as the
        # surrounding code rather than reintroducing a bare name.
        _mcap_for_las = float(market_data.get("market_cap", 0) or 0)
        _oi_for_las = float((_deriv_map or {}).get(asset_id.upper(), {}).get("open_interest_usd") or 0)
        if _oi_for_las > 0 and _mcap_for_las > 0:
            _oi_ratio_las = _oi_for_las / _mcap_for_las
            # OI > 20% MCap starts applying discount (max 30% LAS reduction at 100% OI/MCap)
            _leverage_mult = max(0.7, 1.0 - max(0.0, (_oi_ratio_las - 0.2)) * 0.375)
            las_result["las"] = round(las_result["las"] * _leverage_mult, 1)
            las_result["las_params"]["oi_leverage_multiplier"] = round(_leverage_mult, 3)
            las_result["las_params"]["oi_mcap_ratio"] = round(_oi_ratio_las, 4)

        universe.append({
            "symbol": asset_id,
            "name": config["name"],
            "asset_class": asset_class,
            # GRADE-ALIGN Option B (SCHEMA 1.1): cis_score IS the quality (regime-neutral) score,
            # so it stays coherent with `grade` (both on raw). Regime adjustment moves to its own
            # field `regime_adjusted_score` (the exposure lens) — never the headline quality number.
            "cis_score": raw_cis_score,
            "raw_cis_score": raw_cis_score,
            "regime_adjusted_score": total_score,
            "grade": grade,
            "signal": signal,
            "confidence": confidence,
            "data_tier": 2,  # Railway = Tier 2
            "macro_regime": canonical_regime_strict(regime),  # S-123: strict on write; unknown → NULL
            "las": las_result["las"],
            "las_params": las_result["las_params"],
            "f": pillars["F"],
            "m": pillars["M"],
            "o": pillars["O"],
            "s": pillars["S"],
            "a": pillars["A"],
            "breakdown": breakdown,
            "weights": weights,
            "change_7d": round(change_7d, 1),
            "change_30d": round(change_30d, 1),
            "score_change_7d": score_change_7d,
            "score_change_30d": score_change_30d,
            "volatility_30d": volatility_30d,
            "max_drawdown_90d": round(max_drawdown_90d, 1),
            "percentile": percentile,
            "data_completeness": data_completeness,
            "price": market_data.get("price", 0),
            "change_24h": round(market_data.get("change_24h", 0) or 0, 2),
            "market_cap": market_data.get("market_cap", 0),
            "volume_24h": _vol_24h,
            "tvl": tvl,
        })

    # Sort by CIS score
    universe.sort(key=lambda x: x["cis_score"], reverse=True)

    # v4.1: Compute percentile ranks as metadata only — grades NOT overridden
    universe = compute_percentile_ranks(universe)

    # Use macro_data already fetched above (cached, no double call)
    macro_data = macro_data_early
    macro = {
        "regime": regime,
        "fed_funds": macro_data.get("fed_funds"),
        "treasury_10y": macro_data.get("treasury_10y"),
        "vix": macro_data.get("vix"),
        "dxy": macro_data.get("dxy"),
        "cpi_yoy": macro_data.get("cpi_yoy"),
        "btc_dominance": macro_data.get("btc_dominance"),
    }

    # Save to history database
    try:
        from .history_db import save_cis_snapshot
        save_cis_snapshot(universe, macro)
    except Exception as e:
        _logger.warning(f"Failed to save CIS history: {e}")

    # v4.3: Generate and persist asset embeddings to Redis vector store
    try:
        from src.data.vector.embedder import generate_embedding, generate_regime_embedding
        from src.data.vector.store import save_embeddings
        macro_pulse_for_embed = {
            "macro_regime": regime,
            "btc_dominance": macro_data.get("btc_dominance", 50),
            "fear_greed_index": fng.get("value", 50) if fng else 50,
            "global_mcap_usd": macro_data.get("global_mcap_usd"),
            "btc_change_7d": btc_data.get("change_7d", 0) if btc_data else 0,
        }
        # v2 (build-order #2): source PIT-prior pillars + a short window for deltas + O/S
        # stability. save_cis_snapshot() ran above, so get_cis_history returns [...prior, current]
        # (chronological); history[-2] is the strictly-prior snapshot (I2). Best-effort — any
        # failure leaves the v2 dims NaN (I1), which cosine skips, so this can never break v1.
        try:
            from .history_db import get_cis_history
        except Exception:
            get_cis_history = None
        # v4 (build-order #4): per-asset β-adj edge risk moments (I5) from the Supabase
        # asset_edge_moments view — one best-effort GET; missing symbol / failure ⇒ NaN dims (I1).
        edge_moments_map: dict[str, tuple] = {}
        try:
            import os as _os, json as _json, urllib.request as _u
            _sb = _os.environ.get("SUPABASE_URL", "").rstrip("/")
            _sbk = _os.environ.get("SUPABASE_KEY", "")
            if _sb and _sbk:
                _req = _u.Request(
                    f"{_sb}/rest/v1/asset_edge_moments?select=symbol,edge_vol,edge_p10",
                    headers={"apikey": _sbk, "Authorization": f"Bearer {_sbk}"})
                with _u.urlopen(_req, timeout=5) as _r:
                    for _row in _json.loads(_r.read()):
                        edge_moments_map[str(_row["symbol"]).upper()] = (_row.get("edge_vol"), _row.get("edge_p10"))
        except Exception:
            edge_moments_map = {}
        embeddings: dict[str, list[float]] = {}
        for asset in universe:
            try:
                prior_p, hist = None, None
                if get_cis_history is not None:
                    try:
                        h = get_cis_history(asset.get("symbol", ""), days=6)  # oldest→newest, incl current
                        if h and len(h) >= 2:
                            prior_p = h[-2]        # most recent snapshot strictly before now
                        if h and len(h) >= 3:
                            hist = h               # trailing window (incl current) for std
                    except Exception:
                        prior_p, hist = None, None
                vec = generate_embedding(asset, macro_regime=regime, derivatives=_deriv_map,
                                         prior_pillars=prior_p, pillar_history=hist,
                                         edge_moments=edge_moments_map.get(asset.get("symbol", "").upper()))
                embeddings[asset["symbol"].upper()] = vec
            except Exception:
                pass
        regime_vec = generate_regime_embedding(macro_pulse_for_embed, universe)
        save_embeddings(embeddings, macro_regime=regime, regime_vec=regime_vec)
        _logger.info(f"[CIS] Vector store updated: {len(embeddings)} embeddings")
        # VDB 落库 (2026-07-23): DUAL-WRITE to Supabase pgvector (the proper vector DB) beside Redis.
        # Best-effort — a pgvector outage never breaks the CIS cycle; Redis stays belt-and-braces until
        # reads are fully migrated to the HNSW index (match_asset_embeddings RPC).
        try:
            from src.data.vector.pgvector_store import upsert_embeddings as _pgv_upsert
            _ameta = {str(a.get("symbol")).upper(): {"asset_class": a.get("asset_class", a.get("class"))}
                      for a in universe if a.get("symbol")}
            _pgv_upsert(embeddings, asset_meta=_ameta,
                        macro_regime=canonical_regime_strict(regime))  # S-123
        except Exception as _pe:
            _logger.warning(f"[CIS] pgvector dual-write failed: {_pe}")
    except Exception as e:
        _logger.warning(f"[CIS] Vector store update failed: {e}")

    return {
        "status": "error" if not universe else "success",
        "version": "4.1.0",
        "timestamp": datetime.now().isoformat(),
        "data_source": "coingecko+defillama+alternative.me",
        "data_tier": 2,
        "macro": macro,
        "universe": universe,
        # Per-branch fan-out timings + any branch that degraded to its default.
        # Consumed by _build_cis_universe → /health. Collected on EVERY build,
        # not just slow ones: a diagnostic that only exists after the incident
        # is not a diagnostic (Lesson #70, 10.4 h outage).
        "_branch_timing": _branch_ms,
    }


# Test
if __name__ == "__main__":
    import json
    result = asyncio.run(calculate_cis_universe())
    print(json.dumps(result, indent=2))
