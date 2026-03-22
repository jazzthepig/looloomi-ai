"""
Market router — prices, DeFi, MMI, signals
Endpoints: /api/v1/market/*, /api/v1/defi/*, /api/v1/mmi/*, /api/v1/signals
"""
import re
from fastapi import APIRouter, HTTPException
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
)
from src.api.store import redis_get

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


# ── DeFi (DeFiLlama) ─────────────────────────────────────────────────────────

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
    pos = sum(v for v in pi.values() if v > 0)
    neg = sum(abs(v) for v in pi.values() if v < 0)
    a, s = pi.get("A", 0), pi.get("S", 0)
    if pos + neg == 0: return "NEUTRAL"
    if a >= 12 and s <= -8: return "CONTRARIAN"
    if pos == 0: return "BEARISH"
    if neg == 0: return "BULLISH"
    if pos > neg * 1.5: return "BULLISH"
    if neg > pos * 1.5: return "BEARISH"
    return "MIXED"

def _strength(pi: dict) -> int:
    return min(100, int(sum(abs(v) for v in pi.values()) / 1.5))

def _mk(base: dict, pi: dict, logic: str, horizon: str = "24H") -> dict:
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
    Each signal: pillar_impact (F/M/O/S/A), logic, vector_direction,
    signal_strength, time_horizon.
    """
    signals = []
    now = datetime.now()

    (fng, movers, defi, stables, yields_data, cis_cache, macro_events) = \
        await asyncio.gather(
            _safe(get_fear_greed(limit=1)),
            _safe(get_top_gainers_losers()),
            _safe(get_defi_overview()),
            _safe(get_stablecoin_overview()),
            _safe(get_top_yields(min_tvl=5_000_000, limit=5)),
            _safe(redis_get()),
            _safe(_fetch_macro_signals()),
        )

    # ── 1. Fear & Greed → S + A vector ───────────────────────────────────────
    if fng and fng.get("current"):
        fng_val  = fng["current"].get("value", 50)
        fng_time = fng["current"].get("update_time", "") or now.isoformat()
        if fng_val <= 20:
            pi = {"F": 0, "M": -10, "O": -5, "S": -24, "A": +18}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time, "type": "RISK", "importance": "HIGH",
                "description": f"Fear & Greed 极度恐惧 {fng_val}/100 — 情绪处于历史极端低位",
                "affected_assets": ["BTC", "ETH", "SOL"], "source": "alternative.me", "value": fng_val,
            }, pi, "Extreme Fear (≤20): capitulation-phase sentiment. S pillar hard-depressed (-24). "
               "Historically BTC mean-reverts within 72–120h. A pillar elevated (+18): assets statistically "
               "cheap vs long-run baseline — contrarian entry. Confirm with OBV/on-chain accumulation.", "7D"))
        elif fng_val <= 40:
            pi = {"F": 0, "M": -6, "O": 0, "S": -12, "A": +8}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time, "type": "RISK", "importance": "MED",
                "description": f"Fear & Greed 恐惧 {fng_val}/100 — 情绪偏弱，市场保守",
                "affected_assets": ["BTC", "ETH", "CRYPTO"], "source": "alternative.me", "value": fng_val,
            }, pi, "Fear zone (21–40): risk appetite suppressed, M pillar headwinds. High-beta alts "
               "underperform BTC. Monitor for FNG stabilization above 40 before adding momentum exposure.", "24H"))
        elif fng_val <= 60:
            pi = {"F": 0, "M": 0, "O": 0, "S": +2, "A": 0}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time, "type": "MACRO", "importance": "LOW",
                "description": f"Fear & Greed 中性 {fng_val}/100 — 情绪均衡，无明显方向偏向",
                "affected_assets": ["BTC", "CRYPTO"], "source": "alternative.me", "value": fng_val,
            }, pi, "Neutral sentiment: no directional S pillar bias. Market direction driven by F and M.", "24H"))
        elif fng_val <= 80:
            pi = {"F": 0, "M": +8, "O": +5, "S": +16, "A": -10}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time, "type": "MACRO", "importance": "MED",
                "description": f"Fear & Greed 贪婪 {fng_val}/100 — 情绪乐观，风险溢价收窄",
                "affected_assets": ["BTC", "ETH", "CRYPTO"], "source": "alternative.me", "value": fng_val,
            }, pi, "Greed zone: S pillar elevated, pulling risk assets higher. A pillar compressed (-10): "
               "alpha diminishes in crowded-bullish environments. Favor quality CIS A+ over speculation.", "24H"))
        else:
            pi = {"F": 0, "M": +5, "O": -8, "S": +22, "A": -20}
            signals.append(_mk({
                "id": "fng_1", "timestamp": fng_time, "type": "RISK", "importance": "HIGH",
                "description": f"Fear & Greed 极度贪婪 {fng_val}/100 — 情绪过热，波动率上升概率大",
                "affected_assets": ["BTC", "ETH", "CRYPTO"], "source": "alternative.me", "value": fng_val,
            }, pi, "Extreme Greed (≥81): historically precedes 20–40% corrections within 30d. "
               "A pillar severely compressed (-20): near-zero alpha in crowded longs. "
               "Watch exchange funding rates and OI for liquidation cascade risk.", "7D"))

    # ── 2. Price movers → M + A vector ───────────────────────────────────────
    if movers:
        for g in (movers.get("gainers") or [])[:3]:
            chg = g.get("change_24h", 0) or 0
            if chg >= 5:
                if chg >= 20:
                    pi = {"F": 0, "M": +22, "O": -12, "S": +12, "A": -18}
                    imp, logic, hz = "HIGH", (f"{g['symbol']} +{chg:.0f}%: parabolic extension. M surges but mean-reversion risk acute. "
                        "O stressed (-12): funding rates elevated, OI concentrated = liquidation exposure. A depleted (-18). Trim, await pullback."), "24H"
                elif chg >= 10:
                    pi = {"F": 0, "M": +16, "O": -5, "S": +8, "A": -8}
                    imp, logic, hz = "HIGH", (f"{g['symbol']} +{chg:.0f}%: strong momentum impulse. M elevated. "
                        "Watch continuation vs exhaustion via volume profile and bid depth. A moderately compressed."), "24H"
                else:
                    pi = {"F": 0, "M": +10, "O": 0, "S": +5, "A": -3}
                    imp, logic, hz = "MED", (f"{g['symbol']} +{chg:.0f}%: healthy momentum. "
                        "No O stress. Monitor 7d vs BTC for sustained alpha."), "24H"
                signals.append(_mk({
                    "id": f"gainer_{g['symbol']}", "timestamp": now.isoformat(),
                    "type": "MOMENTUM", "source": "coingecko", "importance": imp, "value": chg,
                    "description": f"{g['symbol']} 24h +{chg:.1f}% — 强势上涨，动能指标偏强",
                    "affected_assets": [g["symbol"]],
                }, pi, logic, hz))
        for l in (movers.get("losers") or [])[:3]:
            chg = l.get("change_24h", 0) or 0
            if chg <= -5:
                if chg <= -20:
                    pi = {"F": -8, "M": -22, "O": -15, "S": -12, "A": +16}
                    imp, logic, hz = "HIGH", (f"{l['symbol']} {chg:.0f}%: severe drawdown. M broken. O damage (-15): likely liquidation cascade. "
                        "F impacted (-8): assess protocol health. A elevated (+16): contrarian entry if F intact — confirm with OBV."), "7D"
                elif chg <= -10:
                    pi = {"F": -3, "M": -16, "O": -8, "S": -10, "A": +10}
                    imp, logic, hz = "HIGH", (f"{l['symbol']} {chg:.0f}%: significant correction. M breakdown. "
                        "If F pillar (TVL/revenue) holds, creates tactical re-entry. No knife-catching without on-chain accumulation signal."), "24H"
                else:
                    pi = {"F": 0, "M": -10, "O": -3, "S": -6, "A": +5}
                    imp, logic, hz = "MED", (f"{l['symbol']} {chg:.0f}%: notable pullback. M weakening. "
                        "Normal volatility range — evaluate vs BTC benchmark before reading directional."), "24H"
                signals.append(_mk({
                    "id": f"loser_{l['symbol']}", "timestamp": now.isoformat(),
                    "type": "RISK", "source": "coingecko", "importance": imp, "value": chg,
                    "description": f"{l['symbol']} 24h {chg:.1f}% — 显著回落，下行压力增大",
                    "affected_assets": [l["symbol"]],
                }, pi, logic, hz))

    # ── 3. DeFi TVL → F + O vector ───────────────────────────────────────────
    if defi:
        tvl_chg   = defi.get("change_24h", 0) or 0
        total_tvl = defi.get("total_tvl", 0) or 0
        if total_tvl > 0:
            if tvl_chg > 5:
                pi = {"F": +22, "M": +8, "O": +15, "S": +5, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_up", "timestamp": now.isoformat(), "type": "FLOW", "source": "defillama",
                    "value": tvl_chg, "importance": "HIGH",
                    "description": f"DeFi TVL 24h +{tvl_chg:.1f}% — 链上资金大规模净流入，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi, f"TVL surge >{tvl_chg:.0f}%: genuine fundamental inflow (F +22). O +15: capital locking = supply reduction. "
                   "Distinguish protocol-specific growth (higher quality) vs sector rotation. F beneficiaries: ETH, AAVE, UNI.", "24H"))
            elif tvl_chg > 1.5:
                pi = {"F": +12, "M": +5, "O": +8, "S": 0, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_up", "timestamp": now.isoformat(), "type": "FLOW", "source": "defillama",
                    "value": tvl_chg, "importance": "MED",
                    "description": f"DeFi TVL 24h +{tvl_chg:.1f}% — 链上资金净流入，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi, f"Moderate TVL growth ({tvl_chg:.1f}%): directionally constructive F/O signal. Monitor for sustained momentum.", "24H"))
            elif tvl_chg < -5:
                pi = {"F": -22, "M": -10, "O": -18, "S": -8, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_down", "timestamp": now.isoformat(), "type": "RISK", "source": "defillama",
                    "value": tvl_chg, "importance": "HIGH",
                    "description": f"DeFi TVL 24h {tvl_chg:.1f}% — 链上资金大规模流出，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi, f"TVL crash ({tvl_chg:.1f}%): serious capital flight. F -22: revenue/usage will compress. "
                   "O -18: supply pressure on protocol tokens. Could signal exploit, regulatory event, or risk-off. "
                   "Investigate: protocol-specific (higher severity) vs sector exodus (temporary).", "7D"))
            elif tvl_chg < -1.5:
                pi = {"F": -12, "M": -5, "O": -10, "S": -3, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_down", "timestamp": now.isoformat(), "type": "RISK", "source": "defillama",
                    "value": tvl_chg, "importance": "MED",
                    "description": f"DeFi TVL 24h {tvl_chg:.1f}% — 链上资金净流出，总规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi, f"TVL decline ({tvl_chg:.1f}%): mild F/O headwind. Monitor secular vs tactical rebalancing.", "24H"))
            else:
                pi = {"F": 0, "M": 0, "O": 0, "S": 0, "A": 0}
                signals.append(_mk({
                    "id": "defi_tvl_stable", "timestamp": now.isoformat(), "type": "FLOW", "source": "defillama",
                    "value": tvl_chg, "importance": "LOW",
                    "description": f"DeFi TVL稳定于 ${total_tvl/1e9:.1f}B，24h变化 {tvl_chg:+.1f}%",
                    "affected_assets": ["ETH", "DeFi"],
                }, pi, "TVL stable: no directional F/O signal. Focus on protocol-specific metrics.", "24H"))

    # ── 4. Stablecoin flows → O + S vector ───────────────────────────────────
    if stables:
        usdc_dom      = stables.get("usdc", {}).get("dominance", 0) or 0
        usdt_dom      = stables.get("usdt", {}).get("dominance", 0) or 0
        total_sc_mcap = ((stables.get("usdc", {}).get("market_cap") or 0) +
                         (stables.get("usdt", {}).get("market_cap") or 0))
        if usdc_dom > usdt_dom + 5:
            pi = {"F": +5, "M": 0, "O": +10, "S": +5, "A": 0}
            signals.append(_mk({
                "id": "sc_usdc_lead", "timestamp": now.isoformat(), "type": "FLOW",
                "source": "defillama", "importance": "MED",
                "description": f"USDC主导稳定币市场 ({usdc_dom:.0f}% vs USDT {usdt_dom:.0f}%) — 机构稳定币偏好上升",
                "affected_assets": ["USDC", "ETH"],
            }, pi, "USDC dominance: institutional/regulated capital preference. O +10: stable capital for DeFi deployment. "
               "Historically precedes ETH DeFi usage spikes. Watch USDC supply moving on-chain.", "7D"))
        elif total_sc_mcap > 1e11:
            pi = {"F": 0, "M": 0, "O": +8, "S": +3, "A": +5}
            signals.append(_mk({
                "id": "sc_dry_powder", "timestamp": now.isoformat(), "type": "FLOW",
                "source": "defillama", "importance": "MED",
                "description": f"稳定币总供应 ${total_sc_mcap/1e9:.0f}B — 市场干火药充足",
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
            }, pi, f"${total_sc_mcap/1e9:.0f}B stablecoin supply = dry powder on sidelines. "
               "A +5: historically precedes BTC rallies as capital rotates. Watch exchange inflows as deployment signal.", "7D"))

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
                    "id": "defi_yield_top", "timestamp": now.isoformat(), "type": "FLOW",
                    "source": "defillama", "importance": "HIGH",
                    "description": f"高收益池: {pool} ({proto}) APY {apy:.1f}% — TVL ${tvl/1e6:.0f}M",
                    "affected_assets": [proto.upper()] if proto else ["DeFi"],
                }, pi, f"Extreme yield ({apy:.0f}%): likely emission-heavy. O +18 for supply lock-up. "
                   "BUT: emission yields compress F via inflation. Real yield (revenue-backed) = sustainable F+. "
                   f"TVL ${tvl/1e6:.0f}M suggests {'meaningful' if tvl > 1e8 else 'limited'} commitment.", "7D"))
            elif apy >= 12:
                pi = {"F": +5, "M": 0, "O": +10, "S": 0, "A": 0}
                signals.append(_mk({
                    "id": "defi_yield_top", "timestamp": now.isoformat(), "type": "FLOW",
                    "source": "defillama", "importance": "MED",
                    "description": f"稳健收益机会: {pool} ({proto}) APY {apy:.1f}% — TVL ${tvl/1e6:.0f}M",
                    "affected_assets": [proto.upper()] if proto else ["DeFi"],
                }, pi, f"Healthy yield ({apy:.0f}%): O positive, capital deployed in DeFi. "
                   "Check reward token vs base asset yield composition for F sustainability.", "24H"))

    # ── 6. CIS engine → multi-pillar ─────────────────────────────────────────
    if cis_cache and cis_cache.get("universe"):
        universe = cis_cache["universe"]
        regime   = cis_cache.get("macro_regime") or cis_cache.get("regime")
        if regime:
            REGIMES = {
                "RISK_ON":     ({"F": +3, "M": +12, "O": +5, "S": +10, "A": +5}, "风险偏好模式 — Risk-On 环境，高β资产活跃", "MACRO", "MED",
                                "Risk-On: M and S elevated. High-beta alts outperform BTC. Reduce defensives. Alpha in sector rotation.", "7D"),
                "RISK_OFF":    ({"F": 0, "M": -15, "O": -10, "S": -18, "A": +8}, "风险规避模式 — Risk-Off 环境，避险情绪主导", "RISK", "HIGH",
                                "Risk-Off: M and S compressed. BTC dominance rises. A +8: BTC/ETH divergence = relative alpha. "
                                "Rotate to high F-pillar assets, reduce beta.", "7D"),
                "TIGHTENING":  ({"F": -8, "M": -10, "O": -5, "S": -12, "A": +5}, "紧缩周期 — 宏观流动性收紧，利率上行压力", "MACRO", "HIGH",
                                "Tightening: higher discount rates compress F valuations. M headwinds as capital exits risk. "
                                "Watch stablecoin supply contraction — indicator of severity.", "30D"),
                "EASING":      ({"F": +10, "M": +12, "O": +8, "S": +10, "A": +3}, "宽松周期 — 宏观流动性改善，金融条件趋宽松", "MACRO", "MED",
                                "Easing: liquidity expansion benefits all risk assets. F improves as rates fall. "
                                "Crypto historically outperforms first 3–6m of easing cycles.", "30D"),
                "STAGFLATION": ({"F": -12, "M": -12, "O": -8, "S": -15, "A": +10}, "滞胀环境 — 增长放缓叠加通胀，市场风险溢价上升", "RISK", "HIGH",
                                "Stagflation: worst macro regime. F damage from growth slowdown. Cannot ease. "
                                "A +10: BTC fixed-supply narrative as inflation hedge. Alts face severe F+M pressure.", "30D"),
                "GOLDILOCKS":  ({"F": +10, "M": +12, "O": +5, "S": +15, "A": +5}, "黄金时代 — 增长稳健、通胀可控，市场环境理想", "MACRO", "MED",
                                "Goldilocks: all CIS pillars benefit. Strongest crypto regime (2020-2021 analog). "
                                "Maximize allocation to A+ assets. Broad sector exposure justified.", "30D"),
            }
            r = REGIMES.get(regime)
            if r:
                pi, desc, rtype, rimp, logic, hz = r
            else:
                pi, desc, rtype, rimp, logic, hz = ({"F":0,"M":0,"O":0,"S":0,"A":0},
                    f"当前宏观体制: {regime}", "MACRO", "LOW", f"Regime: {regime}.", "7D")
            signals.append(_mk({
                "id": "cis_regime", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": rtype, "source": "cis_engine", "importance": rimp,
                "description": desc, "affected_assets": ["MACRO"],
            }, pi, logic, hz))

        top_assets = [a for a in universe
            if a.get("grade") in ("A+", "A") and (a.get("confidence") or a.get("conf", 1)) >= 0.6][:3]
        for a in top_assets:
            sym     = a.get("symbol", "")
            score   = a.get("score") or a.get("cis_score") or 0
            grade   = a.get("grade", "")
            ac      = a.get("asset_class") or a.get("class", "")
            pillars = a.get("pillars", a.get("breakdown", {}))
            weak_p  = min(pillars, key=pillars.get) if pillars else "—"
            pi = {"F": +8, "M": +10, "O": +8, "S": +6, "A": +12}
            signals.append(_mk({
                "id": f"cis_top_{sym}", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": "MOMENTUM", "source": "cis_engine", "importance": "MED",
                "description": f"CIS {grade} 评级: {sym} 综合得分 {score:.1f}/100 — {ac}类资产领先",
                "affected_assets": [sym], "value": score,
            }, pi, f"{sym} {score:.1f}/100 — top 5th percentile ({grade}). Class: {ac}. "
               f"All pillars constructive; weakest: {weak_p}. Broad fundamental support = resilient to isolated shocks.", "7D"))

        total = len(universe)
        if total > 0:
            a_count = sum(1 for x in universe if x.get("grade","") in ("A+","A","B+"))
            d_count = sum(1 for x in universe if x.get("grade","") in ("D","F"))
            pct_pos = round(a_count / total * 100)
            pct_neg = round(d_count / total * 100)
            breadth = pct_pos - pct_neg
            if breadth > 20:
                pi = {"F": +5, "M": +10, "O": +5, "S": +8, "A": 0}
                struct = "偏强 — 市场广度高，多数资产健康"
                logic = f"Strong breadth: {pct_pos}% graded A/B+. Broad bull — not narrow leadership. Low-risk for diversified exposure."
            elif breadth < -10:
                pi = {"F": -5, "M": -10, "O": -5, "S": -8, "A": 0}
                struct = "偏弱 — 市场广度低，评级分化加剧"
                logic = f"Weak breadth: {pct_neg}% graded D/F. Narrow leadership. High-selectivity env: only CIS A-grade warranted."
            else:
                pi = {"F": 0, "M": 0, "O": 0, "S": 0, "A": +5}
                struct = "分化 — 市场结构中性，个股机会分散"
                logic = "Neutral breadth. A +5: dispersion creates stock-picking alpha within CIS universe."
            signals.append(_mk({
                "id": "cis_distribution", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": "MACRO", "source": "cis_engine", "importance": "MED",
                "description": f"市场广度: {total}资产 {pct_pos}% A/B+ · {pct_neg}% D/F — {struct}",
                "affected_assets": ["CRYPTO", "MACRO"],
            }, pi, logic, "7D"))

    # ── 7. Macro events → type-specific pillar impact ─────────────────────────
    if macro_events:
        TYPE_MAP = {
            "REGULATORY": ("REGULATORY", {"F": -8, "M": -5, "O": -10, "S": -15, "A": +5},
                "Regulatory: S suppressed short-term (uncertainty). O negative: exchange outflows/custody changes. "
                "Long-term clarity can be F-positive. Watch jurisdiction scope."),
            "INSTITUTIONAL": ("WHALE", {"F": +10, "M": +8, "O": +15, "S": +12, "A": -3},
                "Institutional action: O +15 = large capital repositioning. F positive if custody/regulatory legitimacy improves."),
            "TECH": ("MOMENTUM", {"F": +15, "M": +10, "O": +5, "S": +8, "A": 0},
                "Tech event: F +15. Protocol upgrades/L2 launches improve utility and fee generation. M from narrative."),
            "MARKET": ("MACRO", {"F": 0, "M": -8, "O": -5, "S": -10, "A": +3},
                "Market structure event: S/M impact. Monitor for sustained directional change vs noise."),
        }
        for evt in macro_events[:3]:
            impact = evt.get("impact", "").upper()
            if impact not in ("HIGH", "MEDIUM"):
                continue
            etype = evt.get("type", "MARKET").upper()
            sig_type, pi, logic = TYPE_MAP.get(etype, TYPE_MAP["MARKET"])
            signals.append(_mk({
                "id": f"macro_{evt.get('id', hash(evt.get('title', '')))}",
                "timestamp": evt.get("date") or now.isoformat(),
                "type": sig_type, "source": evt.get("source", "news"),
                "importance": "HIGH" if impact == "HIGH" else "MED",
                "description": evt.get("title", ""),
                "affected_assets": evt.get("affected_assets", []),
            }, pi, logic, "24H"))

    # ── Sort: importance → strength → recency ─────────────────────────────────
    _order = {"HIGH": 0, "MED": 1, "LOW": 2}
    signals.sort(key=lambda x: (
        _order.get(x.get("importance", "LOW"), 2),
        -x.get("signal_strength", 0),
        -(datetime.fromisoformat(x["timestamp"].replace("Z","")).timestamp()
          if "T" in x.get("timestamp","") else 0),
    ))
    return {
        "status": "success", "version": "3.0.0",
        "timestamp": now.isoformat(),
        "data_source": "cis_engine+coingecko+defillama+alternative.me+news",
        "count": len(signals[:20]), "signals": signals[:20],
    }


async def _fetch_macro_signals() -> list:
    """Pull macro events for the signal feed. Returns [] on failure."""
    try:
        from backend.macro_events_scraper import fetch_all_macro_events
        events = await fetch_all_macro_events()
        return events or []
    except Exception:
        return []
