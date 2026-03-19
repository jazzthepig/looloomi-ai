"""
Market router — prices, DeFi, MMI, signals
Endpoints: /api/v1/market/*, /api/v1/defi/*, /api/v1/mmi/*, /api/v1/signals
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime

from data.market.data_layer import (
    get_prices_multi, get_ohlcv, get_top_gainers_losers,
    get_defi_overview, get_dex_volumes, get_protocol_revenues,
    get_stablecoin_overview, get_top_yields, get_vc_raises,
    get_fear_greed, get_eth_gas, calculate_mmi,
)

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

@router.get("/api/v1/signals")
async def get_signals():
    """
    Trading signals from real market data.
    Combines Fear & Greed, price momentum, DeFi TVL, stablecoin dominance.
    Always returns at least the FNG signal.
    """
    signals = []
    now = datetime.now()

    try:
        # 1. Fear & Greed
        fng = await get_fear_greed(limit=1)
        if fng.get("current"):
            fng_val = fng["current"].get("value", 50)
            fng_time = fng["current"].get("update_time", "")
            if fng_val <= 20:
                sig_type, sig_imp = "RISK", "HIGH"
                sig_desc = f"F&G指数极度恐惧({fng_val})，历史数据显示此时入场BTC长期回报优异"
            elif fng_val <= 40:
                sig_type, sig_imp = "RISK", "MED"
                sig_desc = f"F&G指数恐惧({fng_val})，市场情绪低迷但未至极端，可关注优质标的"
            elif fng_val <= 60:
                sig_type, sig_imp = "MACRO", "LOW"
                sig_desc = f"F&G指数中性({fng_val})，市场无明显方向，保持仓位观望"
            elif fng_val <= 80:
                sig_type, sig_imp = "MACRO", "MED"
                sig_desc = f"F&G指数贪婪({fng_val})，市场乐观情绪升温，注意仓位管理"
            else:
                sig_type, sig_imp = "RISK", "HIGH"
                sig_desc = f"F&G指数极度贪婪({fng_val})，风险积聚，考虑分批减仓"
            signals.append({
                "id": "fng_1",
                "timestamp": fng_time or now.isoformat(),
                "type": sig_type,
                "description": sig_desc,
                "affected_assets": ["BTC", "ETH", "CRYPTO"],
                "importance": sig_imp,
                "source": "alternative.me",
                "value": fng_val,
            })

        # 2. Top Gainers/Losers (threshold ≥5%)
        movers = await get_top_gainers_losers()
        for g in (movers.get("gainers") or [])[:3]:
            change = g.get("change_24h", 0) or 0
            if change >= 5:
                signals.append({
                    "id": f"gainer_{g['symbol']}",
                    "timestamp": now.isoformat(),
                    "type": "MOMENTUM",
                    "description": f"{g['symbol']} 24h上涨{change:.1f}%，强劲上涨动能",
                    "affected_assets": [g["symbol"]],
                    "importance": "HIGH" if change >= 15 else ("MED" if change >= 10 else "LOW"),
                    "source": "coingecko",
                    "value": change,
                })
        for l in (movers.get("losers") or [])[:3]:
            change = l.get("change_24h", 0) or 0
            if change <= -5:
                signals.append({
                    "id": f"loser_{l['symbol']}",
                    "timestamp": now.isoformat(),
                    "type": "RISK",
                    "description": f"{l['symbol']} 24h下跌{abs(change):.1f}%，注意下行风险",
                    "affected_assets": [l["symbol"]],
                    "importance": "HIGH" if change <= -15 else ("MED" if change <= -10 else "LOW"),
                    "source": "coingecko",
                    "value": change,
                })

        # 3. DeFi TVL flows (threshold ≥2%)
        defi = await get_defi_overview()
        tvl_change = defi.get("change_24h", 0) or 0
        total_tvl  = defi.get("total_tvl", 0) or 0
        if total_tvl > 0:
            if tvl_change > 2:
                signals.append({
                    "id": "defi_tvl_up", "timestamp": now.isoformat(), "type": "FLOW",
                    "description": f"DeFi总TVL 24h增加{tvl_change:.1f}%，资金净流入(${total_tvl/1e9:.1f}B)",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "HIGH" if tvl_change > 8 else "MED",
                    "source": "defillama", "value": tvl_change,
                })
            elif tvl_change < -2:
                signals.append({
                    "id": "defi_tvl_down", "timestamp": now.isoformat(), "type": "RISK",
                    "description": f"DeFi总TVL 24h下降{abs(tvl_change):.1f}%，资金净流出(${total_tvl/1e9:.1f}B)",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "HIGH" if tvl_change < -8 else "MED",
                    "source": "defillama", "value": tvl_change,
                })
            else:
                signals.append({
                    "id": "defi_tvl_stable", "timestamp": now.isoformat(), "type": "FLOW",
                    "description": f"DeFi总TVL稳定在${total_tvl/1e9:.1f}B，24h变化{tvl_change:+.1f}%",
                    "affected_assets": ["ETH", "DeFi"],
                    "importance": "LOW", "source": "defillama", "value": tvl_change,
                })

        # 4. Stablecoin dominance
        stables = await get_stablecoin_overview()
        usdc_dom = stables.get("usdc", {}).get("dominance", 0) or 0
        usdt_dom = stables.get("usdt", {}).get("dominance", 0) or 0
        if usdt_dom > 0 or usdc_dom > 0:
            if usdc_dom > usdt_dom + 5:
                signals.append({
                    "id": "stablecoin_usdc_lead", "timestamp": now.isoformat(), "type": "FLOW",
                    "description": f"USDC主导地位领先USDT({usdc_dom:.0f}% vs {usdt_dom:.0f}%)，机构端稳定币偏好增强",
                    "affected_assets": ["USDC", "USDT"], "importance": "LOW", "source": "defillama",
                })
            elif usdt_dom > usdc_dom + 5:
                signals.append({
                    "id": "stablecoin_usdt_dom", "timestamp": now.isoformat(), "type": "FLOW",
                    "description": f"USDT保持稳定币主导地位({usdt_dom:.0f}%)，散户流动性优先",
                    "affected_assets": ["USDT", "USDC"], "importance": "LOW", "source": "defillama",
                })

    except Exception as e:
        print(f"[SIGNALS] generation error: {e}")

    importance_order = {"HIGH": 0, "MED": 1, "LOW": 2}
    signals.sort(key=lambda x: (
        importance_order.get(x["importance"], 2),
        -(datetime.fromisoformat(x["timestamp"].replace("Z", "")).timestamp()
          if "T" in x["timestamp"] else 0),
    ))
    return {
        "status": "success",
        "version": "1.1.0",
        "timestamp": now.isoformat(),
        "data_source": "coingecko+defillama+alternative.me",
        "signals": signals[:15],
    }
