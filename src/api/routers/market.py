"""
Market router — prices, DeFi, MMI, signals
Endpoints: /api/v1/market/*, /api/v1/defi/*, /api/v1/mmi/*, /api/v1/signals
"""
import re
from fastapi import APIRouter, HTTPException, Response
from datetime import datetime
import asyncio

# Symbol validation: alphanumeric, 2-12 chars, comma-separated
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}(,[A-Z0-9]{2,12})*$")

def _validate_symbols(symbols: str) -> list[str]:
    if not _SYMBOL_RE.match(symbols.upper()):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    return [s.strip().upper() for s in symbols.split(",")]

from data.market.data_layer import (
    get_prices_multi, get_ohlcv, get_top_gainers_losers,
    get_defi_overview, get_dex_volumes, get_protocol_revenues,
    get_stablecoin_overview, get_top_yields, get_vc_raises,
    get_fear_greed, get_eth_gas, calculate_mmi,
    get_cg_global, get_cg_trending, get_gecko_terminal_pools, get_cg_derivatives,
    get_cg_markets, get_defi_protocols_curated, get_macro_pulse,
    # v4.2: paid API endpoints
    get_economic_dashboard, get_cg_developer_data,
    get_cg_price_history, get_cg_exchange_concentration,
    get_eodhd_earnings_calendar,
)
from src.api.store import redis_get
from data.cis.cis_provider import ASSETS_CONFIG as _CIS_ASSETS_CONFIG

# Static fallback universe — keys of ASSETS_CONFIG (BTC, ETH, SOL, …)
# Used when Redis CIS cache is empty so signal filtering always has a reference set.
_STATIC_UNIVERSE: frozenset[str] = frozenset(_CIS_ASSETS_CONFIG.keys())

router = APIRouter()


# ── Market (Binance / CoinGecko) ─────────────────────────────────────────────

@router.get("/api/v1/market/prices")
async def get_market_prices(symbols: str = "BTC,ETH,SOL,BNB,AVAX"):
    symbol_list = _validate_symbols(symbols)
    data = await get_prices_multi(symbol_list)
    return {"timestamp": datetime.now().isoformat(), "data": data}


@router.get("/api/v1/market/ohlcv/{symbol}")
async def get_market_ohlcv(symbol: str, interval: str = "1h", limit: int = 100):
    data = await get_ohlcv(symbol, interval, limit)
    if isinstance(data, list) and data and isinstance(data[0], dict) and "error" in data[0]:
        raise HTTPException(status_code=502, detail=data[0]["error"])
    return {"symbol": symbol, "interval": interval, "data": data}


@router.get("/api/v1/market/movers")
async def get_market_movers():
    return await get_top_gainers_losers()


@router.get("/api/v1/market/gas")
async def get_gas_prices():
    return await get_eth_gas()


@router.get("/api/v1/market/coingecko-markets")
async def get_coingecko_markets(ids: str = "", response: Response = None):
    """
    Proxy for CoinGecko coins/markets — uses the Pro key server-side.
    Accepts comma-separated CoinGecko IDs: ?ids=bitcoin,ethereum,solana,...
    Returns the raw CoinGecko markets list (same schema the AssetRadar expects).
    Frontend calls this instead of direct CoinGecko to avoid browser rate limits.
    """
    if not ids:
        raise HTTPException(status_code=400, detail="ids parameter required")
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:60]  # max 60 ids
    if response:
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=60"
    data = await get_cg_markets(id_list)
    return {"data": data, "count": len(data)}


@router.get("/api/v1/market/macro-pulse")
async def macro_pulse(response: Response = None):
    """
    Combined macro overview: CG global + Fear & Greed + BTC price.
    Replaces 3 direct browser calls in MacroPulse.jsx with a single cached backend call.
    Response shape matches MacroPulse.jsx field accesses exactly.
    TTL: 5 min Redis, 2 min in-memory.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=180"
    return await get_macro_pulse()


# ── DeFi (DeFiLlama) ─────────────────────────────────────────────────────────

@router.get("/api/v1/defi/protocols")
async def defi_protocols():
    """
    Curated DeFi protocol list with live TVL from DeFiLlama.
    Used by ProtocolPage to display real data instead of mock values.
    Returns list of {name, slug, category, chains, tvl, change_1d, change_7d}.
    """
    return await get_defi_protocols_curated()


@router.get("/api/v1/defi/overview")
async def defi_overview():
    return await get_defi_overview()


@router.get("/api/v1/defi/dex-volumes")
async def dex_volumes():
    return await get_dex_volumes()


@router.get("/api/v1/defi/revenues")
async def protocol_revenues():
    return await get_protocol_revenues()


@router.get("/api/v1/defi/stablecoins")
async def stablecoins():
    return await get_stablecoin_overview()


@router.get("/api/v1/defi/yields")
async def top_yields(min_tvl: float = 1_000_000, limit: int = 20):
    return {"data": await get_top_yields(min_tvl, limit)}


@router.get("/api/v1/defi/protocol/{slug}")
async def protocol_detail(slug: str):
    from data.market.data_layer import get_protocol
    return await get_protocol(slug)


# ── MMI (composite) ───────────────────────────────────────────────────────────

@router.get("/api/v1/mmi/{token}")
async def get_mmi(token: str = "BTC"):
    return await calculate_mmi(token.upper())


@router.get("/api/v1/mmi/sentiment/fear-greed")
async def fear_greed(limit: int = 30):
    return await get_fear_greed(limit)


# ── Signals ───────────────────────────────────────────────────────────────────

async def _safe(coro):
    """Await a coroutine, return None on any exception."""
    try:
        return await coro
    except Exception:
        return None


# ── Signal helpers ────────────────────────────────────────────────────────────

def _vec_dir(pi: dict) -> str:
    """Derive vector direction from pillar_impact dict."""
    pos = sum(v for v in pi.values() if v > 0)
    neg = sum(abs(v) for v in pi.values() if v < 0)
    a   = pi.get("A", 0)
    s   = pi.get("S", 0)
    if pos + neg == 0:
        return "NEUTRAL"
    # Contrarian: bearish sentiment but strong alpha signal
    if a >= 12 and s <= -8:
        return "CONTRARIAN"
    if pos == 0:
        return "BEARISH"
    if neg == 0:
        return "BULLISH"
    if pos > neg * 1.5:
        return "BULLISH"
    if neg > pos * 1.5:
        return "BEARISH"
    return "MIXED"

def _strength(pi: dict) -> int:
    """Signal strength 0–100 based on total pillar movement."""
    return min(100, int(sum(abs(v) for v in pi.values()) / 1.5))

def _mk(base: dict, pi: dict, logic: str, horizon: str = "24H") -> dict:
    """Attach vector metadata to a signal dict."""
    return {**base,
        "pillar_impact":    pi,
        "logic":            logic,
        "vector_direction": _vec_dir(pi),
        "signal_strength":  _strength(pi),
        "time_horizon":     horizon,
    }


@router.get("/api/v1/signals")
async def get_signals():
    """
    Market signal feed v3.0 — pillar-aware vector signals.
    Each signal carries: pillar_impact (F/M/O/S/A), logic (causal chain),
    vector_direction, signal_strength, time_horizon.
    Sources: CIS engine · Fear & Greed · Price movers · DeFi TVL ·
             Stablecoin flows · DeFi yields · Macro events
    """
    signals = []
    now = datetime.now()

    (
        fng, movers, defi, stables, yields_data, cis_cache, macro_events,
        cg_global, cg_trending, gt_eth_pools, gt_sol_pools, derivatives,
    ) = await asyncio.gather(
        _safe(get_fear_greed(limit=1)),
        _safe(get_top_gainers_losers()),
        _safe(get_defi_overview()),
        _safe(get_stablecoin_overview()),
        _safe(get_top_yields(min_tvl=5_000_000, limit=5)),
        _safe(redis_get()),
        _safe(_fetch_macro_signals()),
        _safe(get_cg_global()),
        _safe(get_cg_trending()),
        _safe(get_gecko_terminal_pools("eth", limit=8)),
        _safe(get_gecko_terminal_pools("solana", limit=5)),
        _safe(get_cg_derivatives()),
    )

    # Universe filter — only emit per-asset signals for assets we score.
    # Prefer live cache (reflects any universe changes); fall back to static.
    _live = {a.get("symbol", "").upper() for a in ((cis_cache or {}).get("universe") or [])}
    universe_syms: frozenset[str] = frozenset(_live) if _live else _STATIC_UNIVERSE

    # ── 1. Fear & Greed → S + A vector ───────────────────────────────────────
    if fng and fng.get("current"):
        fng_val  = fng["current"].get("value", 50)
        fng_time = fng["current"].get("update_time", "") or now.isoformat()

        if fng_val <= 20:
            pi = {"F": 0, "M": -10, "O": -5, "S": -24, "A": +18}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time,
                "type": "RISK", "importance": "HIGH",
                "description": f"Fear & Greed 极度恐惧 {fng_val}/100 — 情绪处于历史极端低位",
                "affected_assets": ["BTC", "ETH", "SOL"],
                "source": "alternative.me", "value": fng_val,
            }, pi,
            "Extreme Fear (≤20) signals capitulation-phase sentiment. "
            "S pillar hard-depressed across crypto (-24). Historically BTC "
            "mean-reverts within 72–120h of readings ≤20. A pillar elevated "
            "(+18): assets are statistically cheap vs long-run baseline — "
            "creates contrarian entry. Confirm with OBV / on-chain accumulation "
            "before acting. Do NOT fade into accelerating volume.",
            "7D"))
        elif fng_val <= 40:
            pi = {"F": 0, "M": -6, "O": 0, "S": -12, "A": +8}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time,
                "type": "RISK", "importance": "MED",
                "description": f"Fear & Greed 恐惧 {fng_val}/100 — 情绪偏弱，市场保守",
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
                "source": "alternative.me", "value": fng_val,
            }, pi,
            "Fear zone (21–40): risk appetite suppressed, M pillar headwinds. "
            "High-beta alts underperform relative to BTC. S pillar drag compresses "
            "CIS scores across the board. Monitor for FNG stabilization above 40 "
            "before adding momentum exposure.",
            "24H"))
        elif fng_val <= 60:
            pi = {"F": 0, "M": 0, "O": 0, "S": +2, "A": 0}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time,
                "type": "MACRO", "importance": "LOW",
                "description": f"Fear & Greed 中性 {fng_val}/100 — 情绪均衡，无明显方向偏向",
                "affected_assets": ["BTC", "CRYPTO"],
                "source": "alternative.me", "value": fng_val,
            }, pi,
            "Neutral sentiment zone: no directional bias from S pillar. "
            "Market direction driven by F (fundamentals) and M (momentum) factors. "
            "No sentiment-based adjustment to CIS scores warranted.",
            "24H"))
        elif fng_val <= 80:
            pi = {"F": 0, "M": +8, "O": +5, "S": +16, "A": -10}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time,
                "type": "MACRO", "importance": "MED",
                "description": f"Fear & Greed 贪婪 {fng_val}/100 — 情绪乐观，风险溢价收窄",
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
                "source": "alternative.me", "value": fng_val,
            }, pi,
            "Greed zone: S pillar elevated, pulling risk assets higher. "
            "A pillar compressed (-10): alpha diminishes in crowded-bullish "
            "environments. Momentum still constructive. Avoid chasing parabolic moves. "
            "Risk-adjusted returns favor quality (A+ CIS) over speculative positions.",
            "24H"))
        else:
            pi = {"F": 0, "M": +5, "O": -8, "S": +22, "A": -20}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time,
                "type": "RISK", "importance": "HIGH",
                "description": f"Fear & Greed 极度贪婪 {fng_val}/100 — 情绪过热，波动率上升概率大",
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
                "source": "alternative.me", "value": fng_val,
            }, pi,
            "Extreme Greed (≥81): historically precedes 20–40% corrections within 30d "
            "in crypto markets. S pillar artificially elevated — will normalize "
            "downward. A pillar severely compressed (-20): near-zero alpha in crowded "
            "long positions. O pillar negative: watch exchange funding rates and "
            "open interest for forced-liquidation cascade risk.",
            "7D"))

    # ── 2. Price movers → M + A vector ───────────────────────────────────────
    if movers:
        for g in (movers.get("gainers") or [])[:15]:
            if g.get("symbol", "").upper() not in universe_syms:
                continue
            chg = g.get("change", g.get("change_24h", 0)) or 0
            if chg >= 5:
                if chg >= 20:
                    pi = {"F": 0, "M": +22, "O": -12, "S": +12, "A": -18}
                    imp, logic, horizon = "HIGH", (
                        f"{g['symbol']} +{chg:.0f}% in 24h: parabolic extension. "
                        "M pillar surges short-term but mean-reversion risk is acute. "
                        "O pillar stressed (-12): funding rates likely elevated, "
                        "OI concentrated = liquidation cascade exposure. "
                        "A pillar depleted (-18): entry alpha exhausted at these levels. "
                        "Signal: trim position, await pullback confirmation before adding."
                    ), "24H"
                elif chg >= 10:
                    pi = {"F": 0, "M": +16, "O": -5, "S": +8, "A": -8}
                    imp, logic, horizon = "HIGH", (
                        f"{g['symbol']} +{chg:.0f}%: strong momentum impulse. "
                        "M pillar elevated. Watch for continuation vs exhaustion — "
                        "volume profile and bid depth are key. A pillar moderately "
                        "compressed at these extended levels."
                    ), "24H"
                else:
                    pi = {"F": 0, "M": +10, "O": 0, "S": +5, "A": -3}
                    imp, logic, horizon = "MED", (
                        f"{g['symbol']} +{chg:.0f}%: healthy momentum. "
                        "M pillar improving. No O pillar stress at this range. "
                        "Monitor 7d performance relative to BTC for sustained alpha."
                    ), "24H"
                signals.append(_mk({
                    "id": f"gainer_{g['symbol']}", "timestamp": now.isoformat(),
                    "type": "MOMENTUM", "source": "coingecko",
                    "importance": imp, "value": chg,
                    "description": f"{g['symbol']} 24h +{chg:.1f}% — 强势上涨，动能指标偏强",
                    "affected_assets": [g["symbol"]],
                }, pi, logic, horizon))

        for l in (movers.get("losers") or [])[:15]:
            if l.get("symbol", "").upper() not in universe_syms:
                continue
            chg = l.get("change", l.get("change_24h", 0)) or 0
            if chg <= -5:
                if chg <= -20:
                    pi = {"F": -8, "M": -22, "O": -15, "S": -12, "A": +16}
                    imp, logic, horizon = "HIGH", (
                        f"{l['symbol']} {chg:.0f}% crash: severe drawdown. "
                        "M pillar broken. O pillar damage (-15): likely liquidation "
                        "cascade — check exchange flow data for capitulation signals. "
                        "F pillar moderately impacted (-8): assess protocol health before "
                        "assuming recovery. A pillar elevated (+16): if F intact, "
                        "this creates a high-conviction contrarian entry zone — "
                        "watch for volume capitulation + OBV divergence."
                    ), "7D"
                elif chg <= -10:
                    pi = {"F": -3, "M": -16, "O": -8, "S": -10, "A": +10}
                    imp, logic, horizon = "HIGH", (
                        f"{l['symbol']} {chg:.0f}%: significant correction. "
                        "M pillar breakdown. Monitor whether F pillar (TVL/revenue) "
                        "holds — if yes, creates tactical re-entry. Avoid catching "
                        "falling knives without on-chain confirmation of accumulation."
                    ), "24H"
                else:
                    pi = {"F": 0, "M": -10, "O": -3, "S": -6, "A": +5}
                    imp, logic, horizon = "MED", (
                        f"{l['symbol']} {chg:.0f}%: notable pullback within correction territory. "
                        "M pillar weakening. Normal volatility range — evaluate "
                        "relative to BTC benchmark before reading as directional."
                    ), "24H"
                signals.append(_mk({
                    "id": f"loser_{l['symbol']}", "timestamp": now.isoformat(),
                    "type": "RISK", "source": "coingecko",
                    "importance": imp, "value": chg,
                    "description": f"{l['symbol']} 24h {chg:.1f}% — 显著回落，下行压力增大",
                    "affected_assets": [l["symbol"]],
                }, pi, logic, horizon))

    # ── 3. DeFi TVL → F + O vector ───────────────────────────────────────────
    if defi:
        tvl_chg   = defi.get("defi_change_24h", 0) or 0
        total_tvl = defi.get("total_tvl", 0) or 0
        if total_tvl > 0:
            if tvl_chg > 5:
                pi = {"F": +22, "M": +8, "O": +15, "S": +5, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_up", "timestamp": now.isoformat(),
                    "type": "FLOW", "source": "defillama", "value": tvl_chg,
                    "importance": "HIGH",
                    "description": f"DeFi TVL 24h +{tvl_chg:.1f}% — 链上资金大规模净流入，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi,
                f"TVL surge >{tvl_chg:.0f}%: strong capital commitment to DeFi. "
                "F pillar (+22): genuine fundamental inflow — not just price appreciation. "
                "O pillar (+15): capital is locking into protocols = supply reduction. "
                "ETH gas demand benefits directly. Distinguish: protocol-specific TVL growth "
                "(higher quality) vs sector-wide rotation (liquidity-seeking). "
                "F-score beneficiaries: ETH, top-TVL protocols (AAVE, UNI, curve).",
                "24H"))
            elif tvl_chg > 1.5:
                pi = {"F": +12, "M": +5, "O": +8, "S": 0, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_up", "timestamp": now.isoformat(),
                    "type": "FLOW", "source": "defillama", "value": tvl_chg,
                    "importance": "MED",
                    "description": f"DeFi TVL 24h +{tvl_chg:.1f}% — 链上资金净流入，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi,
                f"Moderate TVL growth ({tvl_chg:.1f}%): positive F/O signal for DeFi sector. "
                "Not yet threshold-breaking but directionally constructive for ETH and "
                "protocol tokens. Monitor for sustained momentum.",
                "24H"))
            elif tvl_chg < -5:
                pi = {"F": -22, "M": -10, "O": -18, "S": -8, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_down", "timestamp": now.isoformat(),
                    "type": "RISK", "source": "defillama", "value": tvl_chg,
                    "importance": "HIGH",
                    "description": f"DeFi TVL 24h {tvl_chg:.1f}% — 链上资金大规模流出，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi,
                f"TVL crash ({tvl_chg:.1f}%): serious capital flight from DeFi. "
                "F pillar severely damaged (-22): revenue and usage metrics will compress. "
                "O pillar stress (-18): capital unlocking = supply pressure on protocol tokens. "
                "Could signal: exploit fear, regulatory event, or broader risk-off rotation. "
                "Investigate source: protocol-specific (higher severity) vs sector exodus (temporary).",
                "7D"))
            elif tvl_chg < -1.5:
                pi = {"F": -12, "M": -5, "O": -10, "S": -3, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_down", "timestamp": now.isoformat(),
                    "type": "RISK", "source": "defillama", "value": tvl_chg,
                    "importance": "MED",
                    "description": f"DeFi TVL 24h {tvl_chg:.1f}% — 链上资金净流出，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi,
                f"TVL decline ({tvl_chg:.1f}%): mild F/O headwind for DeFi assets. "
                "Monitor whether decline is secular or tactical rebalancing.",
                "24H"))
            else:
                pi = {"F": 0, "M": 0, "O": 0, "S": 0, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_stable", "timestamp": now.isoformat(),
                    "type": "FLOW", "source": "defillama", "value": tvl_chg,
                    "importance": "LOW",
                    "description": f"DeFi TVL稳定于 ${total_tvl/1e9:.1f}B，24h变化 {tvl_chg:+.1f}%",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi,
                "TVL stable: no directional F or O pillar signal. "
                "Neutral on DeFi sector — focus on protocol-specific metrics.",
                "24H"))

    # ── 4. Stablecoin flows → O + S vector ───────────────────────────────────
    if stables:
        usdc_dom      = stables.get("usdc", {}).get("dominance", 0) or 0
        usdt_dom      = stables.get("usdt", {}).get("dominance", 0) or 0
        total_sc_mcap = (
            (stables.get("usdc", {}).get("market_cap") or 0) +
            (stables.get("usdt", {}).get("market_cap") or 0)
        )
        if usdc_dom > usdt_dom + 5:
            pi = {"F": +5, "M": 0, "O": +10, "S": +5, "A": 0}
            signals.append(_mk({
                "id": "sc_usdc_lead", "timestamp": now.isoformat(),
                "type": "FLOW", "source": "defillama", "importance": "MED",
                "description": f"USDC主导稳定币市场 ({usdc_dom:.0f}% vs USDT {usdt_dom:.0f}%) — 机构稳定币偏好上升",
                "affected_assets": ["USDC", "ETH"],
            }, pi,
            "USDC dominance surge: signals institutional/regulated capital preference. "
            "USDC is the on-ramp for institutional DeFi. O pillar (+10): "
            "stable capital available for DeFi deployment. Historically precedes "
            "ETH DeFi protocol usage spikes. Watch for USDC supply moving on-chain.",
            "7D"))
        elif total_sc_mcap > 1e11:
            pi = {"F": 0, "M": 0, "O": +8, "S": +3, "A": +5}
            signals.append(_mk({
                "id": "sc_dry_powder", "timestamp": now.isoformat(),
                "type": "FLOW", "source": "defillama", "importance": "MED",
                "description": f"稳定币总供应 ${total_sc_mcap/1e9:.0f}B — 市场干火药充足",
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
            }, pi,
            f"${total_sc_mcap/1e9:.0f}B in stablecoin supply = significant dry powder on sidelines. "
            "O pillar positive: capital is available and positioned for deployment. "
            "A pillar elevated (+5): large stablecoin supply historically precedes "
            "BTC rallies as capital rotates. Watch for on-chain stablecoin inflows "
            "to exchanges as deployment confirmation signal.",
            "7D"))

    # ── 5. DeFi yield → F + O vector ─────────────────────────────────────────
    if yields_data:
        top = yields_data[0] if isinstance(yields_data, list) else None
        if top:
            apy   = top.get("apy") or 0
            pool  = top.get("symbol", top.get("pool", "Unknown"))
            proto = top.get("project", "")
            tvl   = top.get("tvlUsd", 0) or 0

            if apy >= 30:
                pi = {"F": +8, "M": 0, "O": +18, "S": 0, "A": -5}
                signals.append(_mk({
                    "id": "defi_yield_top", "timestamp": now.isoformat(),
                    "type": "FLOW", "source": "defillama",
                    "importance": "HIGH",
                    "description": f"高收益池: {pool} ({proto}) APY {apy:.1f}% — TVL ${tvl/1e6:.0f}M",
                    "affected_assets": [proto.upper()] if proto else ["DeFi"],
                }, pi,
                f"Extreme yield ({apy:.0f}% APY): likely emission-heavy or "
                f"highly leveraged. O pillar positive (+18) for token locking/supply. "
                "BUT: emission yields compress F pillar long-term via token inflation. "
                "Distinguish: real yield (protocol revenue-backed) = sustainable F+. "
                "Emission yield = temporary O+ with F- trajectory. "
                f"TVL ${tvl/1e6:.0f}M suggests {'meaningful' if tvl > 1e8 else 'limited'} capital commitment.",
                "7D"))
            elif apy >= 12:
                pi = {"F": +5, "M": 0, "O": +10, "S": 0, "A": 0}
                signals.append(_mk({
                    "id": "defi_yield_top", "timestamp": now.isoformat(),
                    "type": "FLOW", "source": "defillama",
                    "importance": "MED",
                    "description": f"稳健收益机会: {pool} ({proto}) APY {apy:.1f}% — TVL ${tvl/1e6:.0f}M",
                    "affected_assets": [proto.upper()] if proto else ["DeFi"],
                }, pi,
                f"Healthy yield range ({apy:.0f}% APY). O pillar positive: "
                "capital being put to work in DeFi. Modest F benefit if yield "
                "is real (revenue-based). Check: reward token vs base asset yield composition.",
                "24H"))

    # ── 6. CIS engine signals → multi-pillar ─────────────────────────────────
    if cis_cache and cis_cache.get("universe"):
        universe = cis_cache["universe"]
        regime   = cis_cache.get("macro_regime") or cis_cache.get("regime")

        if regime:
            regime_signals = {
                "RISK_ON": {
                    "pi": {"F": +3, "M": +12, "O": +5, "S": +10, "A": +5},
                    "desc": "风险偏好模式 — Risk-On 环境，高β资产活跃",
                    "type": "MACRO", "imp": "MED",
                    "logic": "Risk-On macro: M and S pillars elevated across crypto. "
                             "High-beta assets (alts, small-caps) outperform BTC in this regime. "
                             "CIS weight shifts: M pillar elevated in scoring — favor momentum leaders. "
                             "Reduce defensive positioning. Alpha in sector rotation plays.",
                    "horizon": "7D",
                },
                "RISK_OFF": {
                    "pi": {"F": 0, "M": -15, "O": -10, "S": -18, "A": +8},
                    "desc": "风险规避模式 — Risk-Off 环境，避险情绪主导",
                    "type": "RISK", "imp": "HIGH",
                    "logic": "Risk-Off macro: M and S pillars compressed across crypto. "
                             "BTC dominance typically rises (relative store-of-value). "
                             "Altcoin M pillars severely penalized in CIS scoring. "
                             "A pillar elevated (+8): BTC vs ETH divergence creates relative alpha. "
                             "Strategy: rotate to higher CIS F-pillar assets, reduce high-beta exposure.",
                    "horizon": "7D",
                },
                "TIGHTENING": {
                    "pi": {"F": -8, "M": -10, "O": -5, "S": -12, "A": +5},
                    "desc": "紧缩周期 — 宏观流动性收紧，利率上行压力",
                    "type": "MACRO", "imp": "HIGH",
                    "logic": "Tightening cycle: liquidity contraction weighs on F pillar "
                             "(higher discount rates compress valuations). M pillar headwinds "
                             "as capital exits risk assets. S pillar compressed. "
                             "DeFi rates rise with macro rates = yields become more competitive "
                             "vs TradFi but token prices compressed. O pillar: watch "
                             "stablecoin supply contraction — indicator of tightening severity.",
                    "horizon": "30D",
                },
                "EASING": {
                    "pi": {"F": +10, "M": +12, "O": +8, "S": +10, "A": +3},
                    "desc": "宽松周期 — 宏观流动性改善，金融条件趋宽松",
                    "type": "MACRO", "imp": "MED",
                    "logic": "Easing cycle: liquidity expansion benefits all risk assets. "
                             "F pillar improves as discount rates fall (higher DCF valuations). "
                             "M and S pillars expand as capital seeks yield in higher-risk assets. "
                             "Historically crypto outperforms in first 3–6 months of easing cycles. "
                             "Strategy: increase exposure to high-quality (F+M pillar) assets.",
                    "horizon": "30D",
                },
                "STAGFLATION": {
                    "pi": {"F": -12, "M": -12, "O": -8, "S": -15, "A": +10},
                    "desc": "滞胀环境 — 增长放缓叠加通胀，市场风险溢价上升",
                    "type": "RISK", "imp": "HIGH",
                    "logic": "Stagflation: worst macro regime for risk assets. "
                             "F pillar damage: growth slowdown reduces protocol revenue/usage. "
                             "Inflation erodes real returns but central banks cannot ease. "
                             "M and S pillars compressed. A pillar elevated (+10): "
                             "Bitcoin's fixed supply narrative strengthens as inflation hedge — "
                             "BTC/gold correlation rises. Alts face severe F and M pillar pressure.",
                    "horizon": "30D",
                },
                "GOLDILOCKS": {
                    "pi": {"F": +10, "M": +12, "O": +5, "S": +15, "A": +5},
                    "desc": "黄金时代 — 增长稳健、通胀可控，市场环境理想",
                    "type": "MACRO", "imp": "MED",
                    "logic": "Goldilocks: stable growth + controlled inflation = "
                             "ideal conditions for risk assets. All CIS pillars benefit. "
                             "Historical crypto returns strongest in this regime (2020-2021 analog). "
                             "F pillar expands with protocol adoption. "
                             "Strategy: maximize allocation to CIS A+ assets, "
                             "broader sector exposure justified.",
                    "horizon": "30D",
                },
            }
            r = regime_signals.get(regime, {
                "pi": {"F": 0, "M": 0, "O": 0, "S": 0, "A": 0},
                "desc": f"当前宏观体制: {regime}",
                "type": "MACRO", "imp": "LOW",
                "logic": f"Macro regime: {regime}. No specific pillar adjustment mapped.",
                "horizon": "7D",
            })
            signals.append(_mk({
                "id": "cis_regime", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": r["type"], "source": "cis_engine", "importance": r["imp"],
                "description": r["desc"],
                "affected_assets": ["MACRO"],
            }, r["pi"], r["logic"], r["horizon"]))

        # Top A+ assets
        top_assets = [
            a for a in universe
            if a.get("grade") in ("A+", "A") and
               (a.get("confidence") or a.get("conf", 1)) >= 0.6
        ][:3]
        for a in top_assets:
            sym   = a.get("symbol", "")
            score = a.get("score") or a.get("cis_score") or 0
            grade = a.get("grade", "")
            ac    = a.get("asset_class") or a.get("class", "")
            pillars = a.get("pillars", a.get("breakdown", {}))
            weak_p  = min(pillars, key=pillars.get) if pillars else "—"
            pi = {"F": +8, "M": +10, "O": +8, "S": +6, "A": +12}
            signals.append(_mk({
                "id": f"cis_top_{sym}", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": "MOMENTUM", "source": "cis_engine", "importance": "MED",
                "description": f"CIS {grade} 评级: {sym} 综合得分 {score:.1f}/100 — {ac}类资产领先",
                "affected_assets": [sym],
                "value": score,
            }, pi,
            f"{sym} scores {score:.1f}/100 placing it in top 5th percentile (grade {grade}). "
            f"Asset class: {ac}. All pillars constructive — weakest pillar: {weak_p}. "
            "High-conviction allocation candidate with broad fundamental support. "
            "No single pillar dependency = resilient to isolated market shocks.",
            "7D"))

        # Grade distribution — market structure signal
        total = len(universe)
        if total > 0:
            a_count  = sum(1 for x in universe if x.get("grade", "") in ("A+", "A", "B+"))
            d_count  = sum(1 for x in universe if x.get("grade", "") in ("D", "F"))
            pct_pos  = round(a_count / total * 100)
            pct_neg  = round(d_count / total * 100)
            breadth  = pct_pos - pct_neg
            if breadth > 20:
                pi = {"F": +5, "M": +10, "O": +5, "S": +8, "A": 0}
                struct = "偏强 — 市场广度高，多数资产技术面健康"
                logic = (f"Market breadth strong: {pct_pos}% of assets graded A/B+. "
                        "Broad-based bull signal — not a narrow leadership rally. "
                        "M and S pillars benefit from positive breadth feedback loop. "
                        "Low-risk environment for diversified crypto exposure.")
            elif breadth < -10:
                pi = {"F": -5, "M": -10, "O": -5, "S": -8, "A": 0}
                struct = "偏弱 — 市场广度低，资产评级分化加剧"
                logic = (f"Market breadth weak: {pct_neg}% of assets graded D/F. "
                        "Narrow leadership (few assets carrying the market). "
                        "M and S pillars suppressed across most assets. "
                        "High-selectivity environment: only CIS A-grade assets "
                        "warrant exposure.")
            else:
                pi = {"F": 0, "M": 0, "O": 0, "S": 0, "A": +5}
                struct = "分化 — 市场结构中性，个股机会分散"
                logic = ("Neutral breadth: mixed market structure. "
                        "Alpha pillar elevated (+5): dispersion creates "
                        "stock-picking opportunities within CIS universe. "
                        "Focus on individual asset F-pillar quality.")
            signals.append(_mk({
                "id": "cis_distribution", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": "MACRO", "source": "cis_engine", "importance": "MED",
                "description": f"市场广度: {total}资产中 {pct_pos}% A/B+ · {pct_neg}% D/F — {struct}",
                "affected_assets": ["CRYPTO", "MACRO"],
            }, pi, logic, "7D"))

    # ── 7. Macro events → type-specific pillar impact ─────────────────────────
    if macro_events:
        for evt in macro_events[:3]:
            impact = evt.get("impact", "").upper()
            if impact not in ("HIGH", "MEDIUM"):
                continue
            etype = evt.get("category", evt.get("type", "MARKET")).upper()
            type_map = {
                "REGULATORY": ("REGULATORY", {"F": -8, "M": -5, "O": -10, "S": -15, "A": +5},
                    "Regulatory event: S pillar suppressed short-term (uncertainty discount). "
                    "O pillar negative: exchange outflows / custody changes. "
                    "Long-term: clarity can be F-pillar positive. Watch for jurisdiction scope."),
                "INSTITUTIONAL": ("WHALE", {"F": +10, "M": +8, "O": +15, "S": +12, "A": -3},
                    "Institutional action: smart money signal. O pillar strong (+15): "
                    "large capital changing position. F positive if custody/regulatory "
                    "legitimacy improves. M positive via demand absorption."),
                "TECH": ("MOMENTUM", {"F": +15, "M": +10, "O": +5, "S": +8, "A": 0},
                    "Technology event: F pillar improvement. Protocol upgrades / "
                    "L2 launches directly improve fundamental utility and fee generation. "
                    "M benefit from narrative momentum. Long-horizon F+ impact."),
                "MARKET": ("MACRO", {"F": 0, "M": -8, "O": -5, "S": -10, "A": +3},
                    "Market structure event: primarily S/M pillar impact. "
                    "Monitor for sustained directional change vs noise."),
            }
            sig_type, pi, logic = type_map.get(etype, type_map["MARKET"])
            signals.append(_mk({
                "id": f"macro_{evt.get('id', hash(evt.get('title', '')))}",
                "timestamp": evt.get("date") or now.isoformat(),
                "type": sig_type,
                "source": evt.get("source", "news"),
                "importance": "HIGH" if impact == "HIGH" else "MED",
                "description": evt.get("title", ""),
                "affected_assets": evt.get("affected_assets", []),
            }, pi, logic, "24H"))

    # ── 8. CoinGecko Global → BTC dominance + market cap vector ──────────────
    if cg_global and not cg_global.get("error"):
        btc_dom    = cg_global.get("btc_dominance", 0)
        mcap_chg   = cg_global.get("mcap_change_pct_24h", 0)
        defi_ratio = cg_global.get("defi_to_total_ratio", 0)

        # BTC dominance level: high dom = alt headwinds
        if btc_dom >= 58:
            pi = {"F": 0, "M": -12, "O": -5, "S": -10, "A": +8}
            signals.append(_mk({
                "id": "cg_btc_dom_high", "timestamp": now.isoformat(),
                "type": "MACRO", "source": "coingecko", "importance": "HIGH",
                "description": f"BTC主导率 {btc_dom:.1f}% — 资金高度集中BTC，山寨季窗口关闭",
                "affected_assets": ["BTC", "ETH", "CRYPTO"], "value": btc_dom,
            }, pi,
            f"BTC dominance at {btc_dom:.1f}%: capital concentrated in BTC vs altcoins. "
            "Historically alt season requires BTC.D <50%. M pillar compressed for alts (-12). "
            "Relative strategy: long BTC/short alts until BTC.D reversal confirmed. "
            "Watch BTC.D breaking below 55% as alt cycle re-entry signal.",
            "7D"))
        elif btc_dom <= 45:
            pi = {"F": 0, "M": +15, "O": +5, "S": +12, "A": +5}
            signals.append(_mk({
                "id": "cg_btc_dom_low", "timestamp": now.isoformat(),
                "type": "MACRO", "source": "coingecko", "importance": "MED",
                "description": f"BTC主导率 {btc_dom:.1f}% — 山寨季环境，资金广泛分布",
                "affected_assets": ["ETH", "SOL", "CRYPTO"], "value": btc_dom,
            }, pi,
            f"BTC dominance at {btc_dom:.1f}%: capital rotating broadly into alts. "
            "M pillar elevated for high-beta assets. Historical alt season territory. "
            "CIS A+ alts benefit most. DeFi, L1s, and narrative sectors outperform.",
            "7D"))

        # Market cap 24h change — aggregate direction
        if mcap_chg >= 4:
            pi = {"F": +5, "M": +18, "O": +8, "S": +15, "A": -8}
            signals.append(_mk({
                "id": "cg_mcap_surge", "timestamp": now.isoformat(),
                "type": "MOMENTUM", "source": "coingecko", "importance": "HIGH",
                "description": f"加密总市值 24h +{mcap_chg:.1f}% — 全市场大幅拉升",
                "affected_assets": ["BTC", "ETH", "CRYPTO"], "value": mcap_chg,
            }, pi,
            f"Total crypto market cap +{mcap_chg:.1f}% in 24h: broad-based rally. "
            "M pillar strong (+18) — momentum leadership in place. "
            "S pillar elevated but watch for short-term exhaustion. "
            "A pillar compressed (-8): in broad rallies, alpha diminishes — "
            "favor CIS A+ assets over low-grade speculation.",
            "24H"))
        elif mcap_chg <= -4:
            pi = {"F": -5, "M": -18, "O": -10, "S": -15, "A": +5}
            signals.append(_mk({
                "id": "cg_mcap_crash", "timestamp": now.isoformat(),
                "type": "RISK", "source": "coingecko", "importance": "HIGH",
                "description": f"加密总市值 24h {mcap_chg:.1f}% — 全市场显著下跌",
                "affected_assets": ["BTC", "ETH", "CRYPTO"], "value": mcap_chg,
            }, pi,
            f"Total market cap {mcap_chg:.1f}%: broad market selloff. "
            "M pillar broken across the board. Look for divergence: "
            "assets holding or recovering vs index = CIS A pillar leaders. "
            "High-F pillar assets (strong fundamentals) recover first in bounces.",
            "24H"))

        # DeFi ratio expanding = ETH and DeFi sector tailwind
        if defi_ratio >= 8:
            pi = {"F": +12, "M": +5, "O": +10, "S": +5, "A": 0}
            signals.append(_mk({
                "id": "cg_defi_ratio", "timestamp": now.isoformat(),
                "type": "FLOW", "source": "coingecko", "importance": "MED",
                "description": f"DeFi占总市值 {defi_ratio:.1f}% — 链上资本比重处于高位",
                "affected_assets": ["ETH", "DeFi"],
            }, pi,
            f"DeFi market cap {defi_ratio:.1f}% of total crypto market. "
            "Elevated DeFi ratio signals capital committed to on-chain protocols. "
            "F pillar (+12) for ETH and DeFi protocol tokens. "
            "Higher DeFi ratio = higher ETH fee demand = stronger F fundamentals.",
            "7D"))

    # ── 9. CoinGecko Trending → S + M vector for named assets ────────────────
    if cg_trending:
        # Group: any DeFi/L1 coins trending = sector signal
        trending_symbols = [t.get("symbol", "") for t in cg_trending if t.get("symbol")]
        defi_l1 = {"ETH", "SOL", "AVAX", "ARB", "OP", "UNI", "AAVE", "MKR", "CRV", "LDO"}
        trending_defi = [s for s in trending_symbols if s in defi_l1]

        for coin in cg_trending[:10]:
            sym   = coin.get("symbol", "")
            if sym.upper() not in universe_syms:
                continue
            score = coin.get("score", 7)           # 0=top, 6=bottom
            rank  = coin.get("market_cap_rank") or 999
            chg24 = coin.get("price_change_24h", 0) or 0
            # Score 0 = top trending; convert to signal strength
            trend_rank = 6 - min(score, 6)         # 6=top, 0=bottom
            s_boost    = 8 + trend_rank * 2         # S: 8–20
            m_boost    = max(0, min(12, int(chg24))) if chg24 > 0 else max(-12, int(chg24))

            imp = "HIGH" if trend_rank >= 5 else "MED"
            pi  = {"F": 0, "M": m_boost, "O": 0, "S": s_boost, "A": -5 if rank < 50 else 0}
            signals.append(_mk({
                "id": f"cg_trend_{sym}", "timestamp": now.isoformat(),
                "type": "MOMENTUM", "source": "coingecko", "importance": imp,
                "description": f"CoinGecko 热搜 #{score+1}: {sym} — 搜索量激增，社区关注度高",
                "affected_assets": [sym],
                "value": chg24,
            }, pi,
            f"{sym} trending #{score+1} on CoinGecko by search volume. "
            f"Price {'+' if chg24>0 else ''}{chg24:.1f}% 24h. Market cap rank: #{rank}. "
            "Trending precedes price by 12–48h in typical breakout scenarios. "
            "S pillar elevated from social momentum. Validate with F pillar: "
            "check TVL/revenue for DeFi tokens, network metrics for L1s before acting.",
            "24H"))

        if len(trending_defi) >= 3:
            pi = {"F": +8, "M": +10, "O": +5, "S": +12, "A": 0}
            signals.append(_mk({
                "id": "cg_trend_defi_sector", "timestamp": now.isoformat(),
                "type": "MOMENTUM", "source": "coingecko", "importance": "MED",
                "description": f"DeFi/L1板块集体热搜: {', '.join(trending_defi[:4])} — 板块轮动信号",
                "affected_assets": trending_defi[:4],
            }, pi,
            f"Multiple DeFi/L1 tokens trending simultaneously ({', '.join(trending_defi)}). "
            "Sector-wide social momentum = capital rotation signal. "
            "F+M pillars benefit when trending driven by protocol events (upgrades, governance). "
            "Validate: check if trend is news-driven (sustainable) or meme-driven (fade quickly).",
            "7D"))

    # ── 10. GeckoTerminal On-chain Pools → O + M vector ──────────────────────
    all_pools = list(gt_eth_pools or []) + list(gt_sol_pools or [])
    for pool in all_pools[:20]:
        chg24  = pool.get("price_change_24h", 0) or 0
        vol24  = pool.get("volume_24h_usd", 0)   or 0
        tvl    = pool.get("reserve_usd", 0)       or 0
        name   = pool.get("name", "")
        net    = pool.get("network", "eth").upper()
        txns   = pool.get("transactions_24h", 0)  or 0
        token  = pool.get("base_token", name.split("/")[0].strip()) if name else "UNKNOWN"
        if token.upper() not in universe_syms:
            continue

        # New high-TVL pool (>$500k TVL, high tx count) = new liquidity event
        if tvl > 500_000 and txns > 500 and abs(chg24) < 30:
            pi = {"F": +5, "M": +8, "O": +18, "S": +5, "A": +3}
            signals.append(_mk({
                "id": f"gt_pool_new_{token[:8]}_{net}", "timestamp": now.isoformat(),
                "type": "FLOW", "source": "defillama", "importance": "MED",
                "description": f"链上新池: {name} ({net}) TVL ${tvl/1e6:.1f}M · {txns} 笔交易",
                "affected_assets": [token, net],
                "value": tvl,
            }, pi,
            f"Active DEX pool: {name} on {net}. TVL ${tvl/1e6:.1f}M, {txns} transactions 24h. "
            "O pillar strong (+18): significant capital committed on-chain. "
            "High tx count = genuine trading activity (not wash trading if volume/TVL ratio < 10×). "
            "Early on-chain signal often precedes broader market awareness by 6–24h.",
            "24H"))

        # Extreme pool move — potential early pump/dump signal
        elif chg24 >= 40 and vol24 > 100_000:
            pi = {"F": 0, "M": +20, "O": -10, "S": +15, "A": -20}
            signals.append(_mk({
                "id": f"gt_pump_{token[:8]}_{net}", "timestamp": now.isoformat(),
                "type": "RISK", "source": "defillama", "importance": "HIGH",
                "description": f"链上异动: {name} ({net}) 24h +{chg24:.0f}% · 成交量 ${vol24/1e3:.0f}K",
                "affected_assets": [token, net],
                "value": chg24,
            }, pi,
            f"DEX pool {name} up {chg24:.0f}% with ${vol24/1e3:.0f}K volume. "
            "Extreme short-term move: high M but O pillar stressed (-10). "
            "A pillar severely depleted (-20): no alpha at these extended levels. "
            "Risk: low liquidity pumps revert fast. Check TVL vs volume ratio — "
            "if volume > 5× TVL, likely manipulation. Avoid FOMO entry.",
            "24H"))

        elif chg24 <= -35 and vol24 > 100_000:
            pi = {"F": -10, "M": -18, "O": -15, "S": -12, "A": +12}
            signals.append(_mk({
                "id": f"gt_dump_{token[:8]}_{net}", "timestamp": now.isoformat(),
                "type": "RISK", "source": "defillama", "importance": "HIGH",
                "description": f"链上砸盘: {name} ({net}) 24h {chg24:.0f}% · 成交量 ${vol24/1e3:.0f}K",
                "affected_assets": [token, net],
                "value": chg24,
            }, pi,
            f"DEX pool {name} crashed {chg24:.0f}%. O pillar damaged (-15): "
            "liquidity flight. F impacted (-10): assess exploit/rug risk first. "
            "If F pillar (protocol fundamentals) intact, A pillar (+12) creates "
            "contrarian entry zone — confirm with on-chain TVL stabilization.",
            "7D"))

    # ── 11. Derivatives: funding rates + open interest → O vector ────────────
    if derivatives:
        # Aggregate funding rates by symbol
        fr_by_sym: dict = {}
        oi_by_sym: dict = {}
        for d in derivatives:
            sym = d.get("symbol", "")
            fr  = d.get("funding_rate")
            oi  = d.get("open_interest_usd")
            if sym and fr is not None:
                fr_by_sym.setdefault(sym, []).append(fr)
            if sym and oi is not None:
                oi_by_sym.setdefault(sym, []).append(oi)

        for sym, frs in fr_by_sym.items():
            if sym.upper() not in universe_syms:
                continue
            avg_fr   = sum(frs) / len(frs)
            total_oi = sum(oi_by_sym.get(sym, [0]))
            fr_pct   = avg_fr * 100

            if avg_fr >= 0.08:  # ≥0.08% per 8h = heavily long
                pi = {"F": 0, "M": +5, "O": -18, "S": +8, "A": -12}
                signals.append(_mk({
                    "id": f"deriv_fr_high_{sym}", "timestamp": now.isoformat(),
                    "type": "FUNDING", "source": "coingecko", "importance": "HIGH",
                    "description": f"{sym} 资金费率 +{fr_pct:.3f}% — 杠杆多头严重过热",
                    "affected_assets": [sym],
                    "value": fr_pct,
                }, pi,
                f"{sym} funding rate {fr_pct:.3f}% (avg across venues): "
                "longs paying a premium to stay leveraged. "
                "O pillar severely stressed (-18): high funding = crowded longs = "
                "liquidation cascade risk. Historically, BTC funding >0.1% precedes "
                "10–20% deleveraging events within 72h. "
                f"OI: ${total_oi/1e9:.2f}B — {'dangerously concentrated' if total_oi > 5e9 else 'elevated'}. "
                "Framework positions as UNDERWEIGHT; risk reduction positioning favored on bounces.",
                "24H"))

            elif avg_fr <= -0.04:  # negative funding = shorts overcrowded
                pi = {"F": 0, "M": -5, "O": +15, "S": -8, "A": +18}
                signals.append(_mk({
                    "id": f"deriv_fr_neg_{sym}", "timestamp": now.isoformat(),
                    "type": "FUNDING", "source": "coingecko", "importance": "MED",
                    "description": f"{sym} 资金费率 {fr_pct:.3f}% — 做空拥挤，逼空条件形成",
                    "affected_assets": [sym],
                    "value": fr_pct,
                }, pi,
                f"{sym} funding rate {fr_pct:.3f}%: shorts paying longs. "
                "Short squeeze potential: O pillar constructive (+15) as shorts cover = "
                "forced buying. A pillar elevated (+18): high-conviction contrarian long. "
                "S pillar negative (-8) confirms bearish sentiment = contrarian setup. "
                "Trigger: watch for volume spike on a green candle as squeeze catalyst.",
                "24H"))

            # OI-based whale accumulation signal
            if total_oi > 3e9 and 0 < avg_fr < 0.05:
                pi = {"F": 0, "M": +8, "O": +12, "S": +5, "A": -5}
                signals.append(_mk({
                    "id": f"deriv_oi_whale_{sym}", "timestamp": now.isoformat(),
                    "type": "WHALE", "source": "coingecko", "importance": "MED",
                    "description": f"{sym} 合约持仓 ${total_oi/1e9:.1f}B — 大资金建仓，温和做多结构",
                    "affected_assets": [sym],
                    "value": total_oi / 1e9,
                }, pi,
                f"{sym} open interest ${total_oi/1e9:.1f}B with mild positive funding {fr_pct:.3f}%. "
                "Institutional positioning pattern: large OI with controlled funding = "
                "sustained accumulation, not speculative excess. "
                "O pillar strong (+12): committed smart money in futures = demand floor. "
                "Watch for OI acceleration on price dips = conviction buying.",
                "7D"))

    # ── 12. WHALE: Volume-spike + on-chain flow proxies ──────────────────────
    # Source A: CoinGecko global — 24h vol/mcap ratio
    if cg_global and not cg_global.get("error"):
        vol_usd  = cg_global.get("volume_24h_usd", 0) or 0
        mcap_usd = cg_global.get("total_market_cap_usd", 0) or 0
        if mcap_usd > 0:
            vol_ratio = vol_usd / mcap_usd
            if vol_ratio >= 0.25:
                pi = {"F": 0, "M": +10, "O": +18, "S": +8, "A": -5}
                signals.append(_mk({
                    "id": "whale_vol_spike", "timestamp": now.isoformat(),
                    "type": "WHALE", "source": "coingecko", "importance": "HIGH",
                    "description": f"全市场成交量/市值比 {vol_ratio*100:.1f}% — 大资金异常活跃",
                    "affected_assets": ["BTC", "ETH", "CRYPTO"],
                    "value": vol_ratio * 100,
                }, pi,
                f"24h volume/market cap ratio {vol_ratio*100:.1f}%: extremely elevated. "
                "Normal range 5–12%. Spikes >20% signal institutional repositioning — "
                "either large-scale accumulation or distribution. "
                "O pillar surging (+18): unprecedented on-chain capital velocity. "
                "Observe direction: if price holds/rises on volume = accumulation. "
                "If price falls on volume = distribution by large holders.",
                "24H"))
            elif vol_ratio >= 0.15:
                pi = {"F": 0, "M": +8, "O": +10, "S": +5, "A": 0}
                signals.append(_mk({
                    "id": "whale_vol_elevated", "timestamp": now.isoformat(),
                    "type": "WHALE", "source": "coingecko", "importance": "MED",
                    "description": f"全市场成交量活跃度高 {vol_ratio*100:.1f}% — 机构级别换手明显",
                    "affected_assets": ["BTC", "ETH", "CRYPTO"],
                    "value": vol_ratio * 100,
                }, pi,
                f"24h volume/market cap ratio {vol_ratio*100:.1f}%: above normal. "
                "Elevated turnover suggests institutional rebalancing or rotation. "
                "O pillar elevated (+10): capital flowing through the market. "
                "Cross-reference with BTC.D change: rotation signal if dominance moves.",
                "24H"))

    # Source B: GeckoTerminal — whale wash / concentrated pool flow
    all_whale_pools = list(gt_eth_pools or []) + list(gt_sol_pools or [])
    for pool in all_whale_pools[:8]:
        vol24  = pool.get("volume_24h_usd", 0) or 0
        tvl    = pool.get("reserve_usd", 0)     or 0
        name   = pool.get("name", "")
        net    = pool.get("network", "eth").upper()
        txns   = pool.get("transactions_24h", 0) or 0
        chg24  = pool.get("price_change_24h", 0) or 0
        token  = pool.get("base_token", name.split("/")[0].strip()) if name else "UNKNOWN"
        if tvl < 50_000:
            continue
        vol_tvl = vol24 / tvl if tvl > 0 else 0

        if vol_tvl >= 8 and vol24 > 300_000:
            # Volume > 8x TVL = whale rotation through pool
            pi = {"F": -5, "M": +12, "O": +15, "S": +8, "A": -8}
            signals.append(_mk({
                "id": f"whale_pool_{token[:8]}_{net}", "timestamp": now.isoformat(),
                "type": "WHALE", "source": "defillama", "importance": "HIGH",
                "description": f"鲸鱼流动: {name} ({net}) 成交量 {vol_tvl:.0f}×TVL · ${vol24/1e6:.2f}M",
                "affected_assets": [token, net],
                "value": vol_tvl,
            }, pi,
            f"DEX pool {name}: volume {vol_tvl:.0f}× TVL with ${vol24/1e6:.2f}M traded. "
            f"Transactions: {txns}. Whale-scale flow signal — large holders rotating "
            "through this pool. O pillar elevated (+15): concentrated smart money activity. "
            "High vol/TVL with price stability = accumulation. "
            "High vol/TVL with price decline = whale distribution/exit. "
            f"24h price: {'+' if chg24 > 0 else ''}{chg24:.1f}%.",
            "24H"))

    # Source C: CoinGecko trending — small cap with high mcap rank change = whale pump
    if cg_trending:
        for coin in cg_trending[:7]:
            sym   = coin.get("symbol", "")
            rank  = coin.get("market_cap_rank") or 999
            chg24 = coin.get("price_change_24h", 0) or 0
            # Low rank + extreme move = likely whale-driven
            if rank > 200 and abs(chg24) >= 25:
                direction = "上涨" if chg24 > 0 else "下跌"
                pi = ({"F": 0, "M": +15, "O": +8, "S": +12, "A": -15}
                      if chg24 > 0 else
                      {"F": -8, "M": -12, "O": -10, "S": -8, "A": +10})
                signals.append(_mk({
                    "id": f"whale_smallcap_{sym}", "timestamp": now.isoformat(),
                    "type": "WHALE", "source": "coingecko", "importance": "HIGH",
                    "description": f"鲸鱼扫货/出货: {sym} (MC#{rank}) 24h {'+' if chg24>0 else ''}{chg24:.1f}% 登上热搜",
                    "affected_assets": [sym],
                    "value": chg24,
                }, pi,
                f"{sym} (market cap rank #{rank}) {direction} {abs(chg24):.1f}% while trending. "
                "Small-cap + trending + large move = whale-driven price action. "
                "No organic retail volume supports this without on-chain backing. "
                "HIGH risk: exit liquidity may be limited. Avoid chasing. "
                "If accumulating: size to max 1–2% portfolio with hard stop.",
                "IMMEDIATE"))

    # ── CIS universe: asset-specific positioning signals ─────────────────────────
    if cis_cache:
        universe = cis_cache.get("universe") or cis_cache.get("assets") or []
        macro_regime = cis_cache.get("macro_regime", "UNKNOWN")

        # Threshold by regime
        thresholds = {"TIGHTENING": 52, "GOLDILOCKS": 65, "RISK_ON": 60, "EASING": 58}
        threshold = thresholds.get(macro_regime, 58)

        # Top passing assets — signal: OUTPERFORM
        passing = [a for a in universe if (a.get("cis_score") or a.get("score") or 0) >= threshold]
        passing.sort(key=lambda a: a.get("cis_score") or a.get("score") or 0, reverse=True)

        if passing:
            top_symbols = [a.get("symbol") or a.get("asset_id") for a in passing[:5]]
            top_scores = [round(a.get("cis_score") or a.get("score") or 0, 1) for a in passing[:5]]
            summary = ", ".join(f"{s} ({sc})" for s, sc in zip(top_symbols, top_scores))
            pi = {"F": 8, "M": 5, "O": 4, "S": 3, "A": 5}
            signals.append(_mk({
                "id": "cis_passing",
                "timestamp": now.isoformat(),
                "type": "CIS",
                "importance": "HIGH",
                "description": f"{len(passing)} assets pass CIS ≥{threshold} in {macro_regime} regime: {summary}",
                "affected_assets": top_symbols,
                "source": "cometcloud_cis",
                "value": len(passing),
            }, pi,
            f"CIS universe scan: {len(passing)} of {len(universe)} assets meet institutional threshold "
            f"({threshold}) for current {macro_regime} regime. T1 Mac Mini scores. "
            f"Top assets by composite CIS: {summary}. "
            f"Regime-aware weights applied — tighter thresholds in Tightening, wider in Goldilocks.",
            "24H"))

        # Failing / excluded assets — signal: UNDERPERFORM
        failing = [a for a in universe if (a.get("cis_score") or a.get("score") or 0) < threshold]
        if failing:
            fail_symbols = [a.get("symbol") or a.get("asset_id") for a in failing[:5]]
            pi_neg = {"F": -5, "M": -4, "O": -3, "S": -6, "A": -4}
            signals.append(_mk({
                "id": "cis_failing",
                "timestamp": now.isoformat(),
                "type": "CIS",
                "importance": "MED",
                "description": f"{len(failing)} assets below CIS threshold in {macro_regime}: {', '.join(fail_symbols[:5])}{'...' if len(failing) > 5 else ''}",
                "affected_assets": fail_symbols,
                "source": "cometcloud_cis",
                "value": len(failing),
            }, pi_neg,
            f"{len(failing)} tracked assets fail CIS ≥{threshold}. S and A pillars most suppressed. "
            f"Common causes in {macro_regime}: momentum breakdown (M pillar), vol regime negative (S pillar), "
            f"underperformance vs BTC benchmark (A pillar). Do not override with manual entry.",
            "24H"))

    # ── Whale movement detection — vol/mcap spike across CIS universe ────────────
    # Uses CIS universe (not Binance movers — geo-blocked on Railway).
    # CIS universe fields: volume_24h, change_24h, market_cap, symbol, cis_score
    if cis_cache:
        _cis_universe = cis_cache.get("universe") or cis_cache.get("assets") or []

        whale_alerts = []
        for asset in _cis_universe:
            vol_24h   = asset.get("volume_24h") or 0
            mcap      = asset.get("market_cap") or 0
            price_chg = asset.get("change_24h") or 0
            cis_score = asset.get("cis_score") or asset.get("score") or 0

            if mcap <= 0:
                continue
            # Volume/mcap ratio spike: >8% vol/mcap in 24h = institutional-level flow
            vol_ratio = vol_24h / mcap
            if vol_ratio > 0.08 and abs(price_chg) > 3:
                symbol = (asset.get("symbol") or asset.get("asset_id") or "").upper()
                direction = "accumulation" if price_chg > 0 else "distribution"
                whale_alerts.append({
                    "symbol":    symbol,
                    "direction": direction,
                    "price_chg": round(price_chg, 2),
                    "vol_ratio": round(vol_ratio * 100, 1),
                    "cis_score": round(cis_score, 1),
                    "grade":     asset.get("grade", "?"),
                })

        if whale_alerts:
            # Sort by vol_ratio desc — biggest spike first
            whale_alerts.sort(key=lambda w: w["vol_ratio"], reverse=True)
            symbols = [w["symbol"] for w in whale_alerts[:5]]
            desc_parts = [
                f"{w['symbol']} ({w['direction']}, {w['price_chg']:+.1f}%, "
                f"vol/mcap {w['vol_ratio']}%, CIS {w['cis_score']})"
                for w in whale_alerts[:3]
            ]
            pi_whale = {"F": 0, "M": 12, "O": 8, "S": 6, "A": 4}
            signals.append(_mk({
                "id": "whale_volume",
                "timestamp": now.isoformat(),
                "type": "WHALE",
                "importance": "HIGH",
                "description": f"Abnormal volume detected — {len(whale_alerts)} CIS-tracked assets show whale-level activity",
                "affected_assets": symbols,
                "source": "cis_volume_analysis",
                "value": len(whale_alerts),
                "whale_detail": whale_alerts[:5],
            }, pi_whale,
            f"Volume/mcap ratio >8% with price movement >3% in CIS-tracked universe — "
            f"statistically significant institutional flow. "
            f"Signals: {'; '.join(desc_parts)}. "
            f"High vol_ratio with price rise = accumulation (bullish for M/O pillars). "
            f"High vol_ratio with price drop = distribution (negative M/S signal). "
            f"Cross-reference CIS score: whale flow in low-CIS (grade D/F) assets is noise.",
            "24H"))

    # ── Sort: HIGH first, then by strength, then by recency ──────────────────
    _order = {"HIGH": 0, "MED": 1, "LOW": 2}
    def _ts_sort(x):
        ts = x.get("timestamp") or ""
        try:
            return -(datetime.fromisoformat(ts.replace("Z", "")).timestamp()) if "T" in ts else 0
        except Exception:
            return 0
    signals.sort(key=lambda x: (
        _order.get(x.get("importance", "LOW"), 2),
        -x.get("signal_strength", 0),
        _ts_sort(x),
    ))
    return {
        "status": "success",
        "version": "3.2.0",
        "timestamp": now.isoformat(),
        "data_source": "cis_engine+coingecko_pro+defillama+alternative.me+geckoterminal+news",
        "count": len(signals[:40]),
        "signals": signals[:40],
    }


async def _fetch_macro_signals() -> list:
    """
    Pull macro events for the signal feed.
    Uses the shared in-memory cache from intelligence.py (60-min TTL) to avoid
    hammering RSS feeds on every signal refresh. Falls back to direct fetch on miss.
    Returns [] on failure.
    """
    try:
        # Re-use the intelligence router cache — avoids redundant RSS scrapes
        import importlib
        intel_mod = importlib.import_module("src.api.routers.intelligence")
        cache = getattr(intel_mod, "_macro_cache", {})
        ttl   = getattr(intel_mod, "_MACRO_TTL", 3600)
        import time as _time
        if cache.get("data") and (_time.time() - cache.get("at", 0)) < ttl:
            return cache["data"]
        # Cache miss — fetch fresh and populate cache
        from backend.macro_events_scraper import fetch_all_macro_events
        events = await fetch_all_macro_events()
        cache["data"] = events or []
        cache["at"]   = _time.time()
        return cache["data"]
    except Exception:
        return []


# ── v4.2: Paid API endpoints ──────────────────────────────────────────────────

@router.get("/api/v1/market/economic-indicators")
async def economic_indicators():
    """
    Multi-country macro dashboard powered by EODHD.
    Returns CPI, GDP growth, interest rate, unemployment, PMI for US, HK, CN.
    Derives macro regime from real economic data (not price action).
    Cache: 4h Redis TTL.
    """
    try:
        data = await get_economic_dashboard()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Economic dashboard error: {e}")


@router.get("/api/v1/market/developer-data/{coin_id}")
async def developer_data(coin_id: str):
    """
    CoinGecko Pro developer activity for a single coin.
    Returns commit_count_4_weeks, stars, closed_issues, pull_request_contributors,
    and a composite dev_activity_score (0-100).
    Cache: 24h Redis TTL (developer metrics change slowly).

    Example: /api/v1/market/developer-data/ethereum
    """
    # Basic validation — CG coin IDs are lowercase slug
    coin_id = coin_id.lower().strip()
    if not coin_id or len(coin_id) > 60:
        raise HTTPException(status_code=400, detail="Invalid coin_id")
    try:
        data = await get_cg_developer_data(coin_id)
        if not data or "error" in data:
            raise HTTPException(status_code=404, detail=f"No developer data for {coin_id}")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Developer data error: {e}")


@router.get("/api/v1/market/price-history/{coin_id}")
async def price_history(coin_id: str, days: int = 365):
    """
    CoinGecko Pro OHLCV history (daily candles) for a single coin.
    Default 365 days; supports 1-365 range. Includes price, volume, market_cap series.
    Cache: 2h Redis TTL.

    Example: /api/v1/market/price-history/bitcoin?days=90
    """
    coin_id = coin_id.lower().strip()
    if not coin_id or len(coin_id) > 60:
        raise HTTPException(status_code=400, detail="Invalid coin_id")
    days = max(1, min(365, days))
    try:
        data = await get_cg_price_history(coin_id, days)
        if not data or "error" in data:
            raise HTTPException(status_code=404, detail=f"No price history for {coin_id}")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Price history error: {e}")


@router.get("/api/v1/market/exchange-concentration/{coin_id}")
async def exchange_concentration(coin_id: str):
    """
    CoinGecko Pro exchange concentration analysis for a single coin.
    Returns per-exchange volume share, Herfindahl-Hirschman Index (HHI),
    and a concentration risk flag (low/moderate/high/very_high).
    Cache: 1h Redis TTL.

    Example: /api/v1/market/exchange-concentration/bitcoin
    """
    coin_id = coin_id.lower().strip()
    if not coin_id or len(coin_id) > 60:
        raise HTTPException(status_code=400, detail="Invalid coin_id")
    try:
        data = await get_cg_exchange_concentration(coin_id)
        if not data or "error" in data:
            raise HTTPException(status_code=404, detail=f"No exchange data for {coin_id}")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Exchange concentration error: {e}")


@router.get("/api/v1/market/earnings-calendar")
async def earnings_calendar(symbols: str = "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA", days_ahead: int = 30):
    """
    Upcoming earnings dates for US Equity symbols via EODHD.
    Returns report_date, estimate EPS, period end, and days_until for each symbol.
    Cache: 4h Redis TTL.

    Example: /api/v1/market/earnings-calendar?symbols=AAPL,NVDA&days_ahead=14
    """
    symbol_list = _validate_symbols(symbols)
    days_ahead = max(1, min(90, days_ahead))
    try:
        data = await get_eodhd_earnings_calendar(symbol_list, days_ahead)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Earnings calendar error: {e}")
