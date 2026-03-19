"""
Market router — prices, DeFi, MMI, signals
Endpoints: /api/v1/market/*, /api/v1/defi/*, /api/v1/mmi/*, /api/v1/signals
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
import asyncio

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
    symbol_list = [s.strip() for s in symbols.split(",")]
    data = await get_prices_multi(symbol_list)
    return {"timestamp": datetime.now().isoformat(), "data": data}


@router.get("/api/v1/market/ohlcv/{symbol}")
async def get_market_ohlcv(symbol: str, interval: str = "1h", limit: int = 100):
    data = await get_ohlcv(symbol, interval, limit)
    if data and "error" in data[0]:
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


@router.get("/api/v1/signals")
async def get_signals():
    """
    Market signals from 7 concurrent data sources:
    CIS scores · Fear & Greed · Price movers · DeFi TVL ·
    Stablecoin flows · DeFi yields · Macro events
    """
    signals = []
    now = datetime.now()

    # ── Fetch all sources concurrently ────────────────────────────────────────
    (
        fng,
        movers,
        defi,
        stables,
        yields_data,
        cis_cache,
        macro_events,
    ) = await asyncio.gather(
        _safe(get_fear_greed(limit=1)),
        _safe(get_top_gainers_losers()),
        _safe(get_defi_overview()),
        _safe(get_stablecoin_overview()),
        _safe(get_top_yields(min_tvl=5_000_000, limit=5)),
        _safe(redis_get()),
        _safe(_fetch_macro_signals()),
    )

    # ── 1. Fear & Greed ───────────────────────────────────────────────────────
    if fng and fng.get("current"):
        fng_val  = fng["current"].get("value", 50)
        fng_time = fng["current"].get("update_time", "") or now.isoformat()
        if fng_val <= 20:
            sig_type, sig_imp = "RISK", "HIGH"
            sig_desc = f"恐慌贪婪指数: 极度恐惧 ({fng_val}/100) — 市场情绪处于历史极端低位"
        elif fng_val <= 40:
            sig_type, sig_imp = "RISK", "MED"
            sig_desc = f"恐慌贪婪指数: 恐惧 ({fng_val}/100) — 整体市场情绪偏弱"
        elif fng_val <= 60:
            sig_type, sig_imp = "MACRO", "LOW"
            sig_desc = f"恐慌贪婪指数: 中性 ({fng_val}/100) — 市场情绪均衡，无明显方向偏向"
        elif fng_val <= 80:
            sig_type, sig_imp = "MACRO", "MED"
            sig_desc = f"恐慌贪婪指数: 贪婪 ({fng_val}/100) — 市场情绪偏乐观，风险溢价收窄"
        else:
            sig_type, sig_imp = "RISK", "HIGH"
            sig_desc = f"恐慌贪婪指数: 极度贪婪 ({fng_val}/100) — 市场情绪处于历史极端高位，波动率上升概率增大"
        signals.append({
            "id": "fng_1", "timestamp": fng_time,
            "type": sig_type, "importance": sig_imp,
            "description": sig_desc,
            "affected_assets": ["BTC", "ETH", "CRYPTO"],
            "source": "alternative.me", "value": fng_val,
        })

    # ── 2. Price movers (threshold ≥3%) ───────────────────────────────────────
    if movers:
        for g in (movers.get("gainers") or [])[:4]:
            chg = g.get("change_24h", 0) or 0
            if chg >= 3:
                signals.append({
                    "id": f"gainer_{g['symbol']}", "timestamp": now.isoformat(),
                    "type": "MOMENTUM", "source": "coingecko", "value": chg,
                    "importance": "HIGH" if chg >= 15 else ("MED" if chg >= 8 else "LOW"),
                    "description": f"{g['symbol']} 24h +{chg:.1f}% — 强势上涨，动能指标偏强",
                    "affected_assets": [g["symbol"]],
                })
        for l in (movers.get("losers") or [])[:4]:
            chg = l.get("change_24h", 0) or 0
            if chg <= -3:
                signals.append({
                    "id": f"loser_{l['symbol']}", "timestamp": now.isoformat(),
                    "type": "RISK", "source": "coingecko", "value": chg,
                    "importance": "HIGH" if chg <= -15 else ("MED" if chg <= -8 else "LOW"),
                    "description": f"{l['symbol']} 24h {chg:.1f}% — 显著回落，下行压力增大",
                    "affected_assets": [l["symbol"]],
                })

    # ── 3. DeFi TVL flows ─────────────────────────────────────────────────────
    if defi:
        tvl_chg   = defi.get("change_24h", 0) or 0
        total_tvl = defi.get("total_tvl", 0) or 0
        if total_tvl > 0:
            if tvl_chg > 1.5:
                signals.append({
                    "id": "defi_tvl_up", "timestamp": now.isoformat(),
                    "type": "FLOW", "source": "defillama", "value": tvl_chg,
                    "importance": "HIGH" if tvl_chg > 6 else "MED",
                    "description": f"DeFi总TVL 24h +{tvl_chg:.1f}% — 链上资金净流入，当前规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                })
            elif tvl_chg < -1.5:
                signals.append({
                    "id": "defi_tvl_down", "timestamp": now.isoformat(),
                    "type": "RISK", "source": "defillama", "value": tvl_chg,
                    "importance": "HIGH" if tvl_chg < -6 else "MED",
                    "description": f"DeFi总TVL 24h {tvl_chg:.1f}% — 链上资金净流出，当前规模 ${total_tvl/1e9:.1f}B",
                    "affected_assets": ["ETH", "DeFi"],
                })
            else:
                signals.append({
                    "id": "defi_tvl_stable", "timestamp": now.isoformat(),
                    "type": "FLOW", "source": "defillama", "value": tvl_chg,
                    "importance": "LOW",
                    "description": f"DeFi总TVL稳定于 ${total_tvl/1e9:.1f}B，24h变化 {tvl_chg:+.1f}%",
                    "affected_assets": ["ETH", "DeFi"],
                })

    # ── 4. Stablecoin dominance (threshold ≥2%) ───────────────────────────────
    if stables:
        usdc_dom = stables.get("usdc", {}).get("dominance", 0) or 0
        usdt_dom = stables.get("usdt", {}).get("dominance", 0) or 0
        total_sc_mcap = (
            (stables.get("usdc", {}).get("market_cap") or 0) +
            (stables.get("usdt", {}).get("market_cap") or 0)
        )
        if usdc_dom > usdt_dom + 2:
            signals.append({
                "id": "sc_usdc_lead", "timestamp": now.isoformat(),
                "type": "FLOW", "source": "defillama", "importance": "LOW",
                "description": f"USDC主导稳定币市场 ({usdc_dom:.0f}% vs USDT {usdt_dom:.0f}%) — 机构稳定币占比上升",
                "affected_assets": ["USDC", "USDT"],
            })
        elif usdt_dom > usdc_dom + 2:
            signals.append({
                "id": "sc_usdt_dom", "timestamp": now.isoformat(),
                "type": "FLOW", "source": "defillama", "importance": "LOW",
                "description": f"USDT主导稳定币市场 ({usdt_dom:.0f}%) — 总稳定币规模 ${total_sc_mcap/1e9:.0f}B",
                "affected_assets": ["USDT", "USDC"],
            })

    # ── 5. DeFi top yield ─────────────────────────────────────────────────────
    if yields_data:
        top = yields_data[0] if isinstance(yields_data, list) else None
        if top and (top.get("apy") or 0) >= 12:
            apy   = top["apy"]
            pool  = top.get("symbol", top.get("pool", "Unknown"))
            proto = top.get("project", "")
            tvl   = top.get("tvlUsd", 0) or 0
            signals.append({
                "id": "defi_yield_top", "timestamp": now.isoformat(),
                "type": "FLOW", "source": "defillama",
                "importance": "HIGH" if apy >= 30 else "MED",
                "description": f"链上高收益机会: {pool} ({proto}) APY {apy:.1f}% — TVL ${tvl/1e6:.0f}M",
                "affected_assets": [proto.upper()] if proto else ["DeFi"],
            })

    # ── 6. CIS scoring signals (from Redis cache) ─────────────────────────────
    if cis_cache and cis_cache.get("universe"):
        universe = cis_cache["universe"]
        regime   = cis_cache.get("macro_regime") or cis_cache.get("regime")

        # Macro regime signal
        if regime:
            regime_map = {
                "RISK_ON":     ("风险偏好模式 — 市场处于Risk-On状态，高β资产相对活跃", "MACRO", "MED"),
                "RISK_OFF":    ("风险规避模式 — 市场处于Risk-Off状态，避险情绪主导", "RISK", "HIGH"),
                "TIGHTENING":  ("紧缩周期 — 宏观流动性收紧，利率上行压力持续", "MACRO", "MED"),
                "EASING":      ("宽松周期 — 宏观流动性改善，金融条件趋于宽松", "MACRO", "MED"),
                "STAGFLATION": ("滞胀环境 — 增长放缓叠加通胀压力，市场风险溢价上升", "RISK", "HIGH"),
                "GOLDILOCKS":  ("黄金时代 — 增长与通胀双稳，市场环境较为理想", "MACRO", "LOW"),
            }
            desc, rtype, rimp = regime_map.get(regime, (f"当前宏观体制: {regime}", "MACRO", "LOW"))
            signals.append({
                "id": "cis_regime", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": rtype, "source": "cis_engine", "importance": rimp,
                "description": desc,
                "affected_assets": ["MACRO"],
            })

        # Top A+ assets by CIS score
        top_assets = [
            a for a in universe
            if a.get("grade") in ("A+", "A") and (a.get("confidence") or a.get("conf", 1)) >= 0.6
        ][:3]
        for a in top_assets:
            sym   = a.get("symbol", "")
            score = a.get("score") or a.get("cis_score") or 0
            grade = a.get("grade", "")
            ac    = a.get("asset_class") or a.get("class", "")
            signals.append({
                "id": f"cis_top_{sym}", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": "MOMENTUM", "source": "cis_engine", "importance": "MED",
                "description": f"CIS评级: {sym} 综合得分 {score:.1f}/100 ({grade}级) — {ac}类资产中领先",
                "affected_assets": [sym],
                "value": score,
            })

        # Grade distribution snapshot (always emit, informational)
        total = len(universe)
        if total > 0:
            a_count  = sum(1 for x in universe if x.get("grade", "") in ("A+", "A", "B+"))
            d_count  = sum(1 for x in universe if x.get("grade", "") in ("D", "F"))
            pct_pos  = round(a_count / total * 100)
            pct_neg  = round(d_count / total * 100)
            signals.append({
                "id": "cis_distribution", "timestamp": cis_cache.get("timestamp", now.isoformat()),
                "type": "MACRO", "source": "cis_engine", "importance": "LOW",
                "description": f"CIS全域概览: {total}个资产 — {pct_pos}%评级A/B+，{pct_neg}%评级D/F，市场结构{'偏强' if pct_pos > 40 else '偏弱' if pct_neg > 30 else '分化'}",
                "affected_assets": ["CRYPTO", "MACRO"],
            })

    # ── 7. Macro events (top HIGH/MEDIUM impact) ──────────────────────────────
    if macro_events:
        for evt in macro_events[:3]:
            impact = evt.get("impact", "").upper()
            if impact not in ("HIGH", "MEDIUM"):
                continue
            etype = evt.get("type", "MARKET").upper()
            type_map = {
                "REGULATORY": "REGULATORY", "INSTITUTIONAL": "WHALE",
                "TECH": "MOMENTUM", "MARKET": "MACRO",
            }
            signals.append({
                "id": f"macro_{evt.get('id', hash(evt.get('title','')))}",
                "timestamp": evt.get("date") or now.isoformat(),
                "type": type_map.get(etype, "MACRO"),
                "source": evt.get("source", "news"),
                "importance": "HIGH" if impact == "HIGH" else "MED",
                "description": evt.get("title", ""),
                "affected_assets": evt.get("affected_assets", []),
            })

    # ── Sort and return ───────────────────────────────────────────────────────
    _order = {"HIGH": 0, "MED": 1, "LOW": 2}
    signals.sort(key=lambda x: (
        _order.get(x.get("importance", "LOW"), 2),
        -(datetime.fromisoformat(x["timestamp"].replace("Z", "")).timestamp()
          if "T" in x.get("timestamp", "") else 0),
    ))
    return {
        "status": "success",
        "version": "2.0.0",
        "timestamp": now.isoformat(),
        "data_source": "cis_engine+coingecko+defillama+alternative.me+news",
        "count": len(signals[:20]),
        "signals": signals[:20],
    }


async def _fetch_macro_signals() -> list:
    """Pull macro events for the signal feed. Returns [] on failure."""
    try:
        from backend.macro_events_scraper import fetch_all_macro_events
        events = await fetch_all_macro_events()
        return events or []
    except Exception:
        return []
