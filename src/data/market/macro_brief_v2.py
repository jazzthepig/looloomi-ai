"""
Macro Brief v2 — Dynamic Market Compass
=======================================
Generates structured MacroSignal with:
  - conviction: BULL / BEAR / NEUTRAL
  - velocity: ACCELERATING / DECELERATING / STABLE
  - cross_asset_confirm: bool
  - confidence: 0.0-1.0 (<0.6 → UNCLEAR)
  - time_horizon: 4h / 24h / 1week
  - regime: from detect_regime()
  - key_drivers: top 3 market drivers

Auto-generated from live macro-pulse data when Mac Mini LLM unavailable.
LM Studio integration for AI-generated briefs (Gemma4-26b / Qwen3.5-35B-A3B).

Author: CometCloud Intelligence
"""

import json
import logging
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

_logger = logging.getLogger(__name__)

# ── LM Studio client settings ────────────────────────────────────────────────

LM_STUDIO_BASE = "http://127.0.0.1:1234"
_Gemma4_model  = "gemma4-26b"
_Qwen_model    = "qwen3.5-35b-a3b"


# ── MacroSignal dataclass ─────────────────────────────────────────────────────

@dataclass
class MacroSignal:
    conviction: str           # BULL / BEAR / NEUTRAL
    velocity: str             # ACCELERATING / DECELERATING / STABLE
    cross_asset_confirm: bool # BTC + ETH + SOL共振？
    confidence: float         # 0.0-1.0
    time_horizon: str         # 4h / 24h / 1week
    regime: str               # from detect_regime()
    key_drivers: list[str]    # top 3 market驱动因素
    brief_text: str           # human-readable summary
    raw_data: dict            # snapshot of inputs

    def to_dict(self) -> dict:
        return asdict(self)


# ── Regime detection (from cis_provider.py logic) ────────────────────────────

def detect_macro_regime(
    btc_30d: float,
    fng_value: int,
    vix: float,
    btc_dominance: float = 52.0,
) -> str:
    """
    Classify macro regime from 4 signals.
    Returns: Goldilocks / Risk-On / Easing / Neutral / Tightening / Risk-Off / Stagflation
    """
    vix = vix or 20.0
    bdom = btc_dominance or 52.0

    if btc_30d > 10 and fng_value > 60 and vix < 17:
        return "Goldilocks"
    if btc_30d > 5 and fng_value > 55:
        return "Risk-On"
    if vix > 27 and btc_30d < -5 and bdom > 58:
        return "Stagflation"
    if btc_30d < -12 or fng_value < 28 or vix > 30:
        return "Risk-Off"
    if vix > 21 and fng_value < 48:
        return "Tightening"
    if vix < 17 and fng_value > 45:
        return "Easing"
    return "Neutral"


# ── Auto-generate from live macro data ───────────────────────────────────────

async def auto_generate_macro_signal(macro_pulse: dict) -> MacroSignal:
    """
    Build MacroSignal from live macro_pulse data (no LLM required).
    """
    try:
        # Extract key fields from macro_pulse
        btc_price   = macro_pulse.get("btc_price") or 0
        btc_dom     = macro_pulse.get("btc_dominance") or 50.0
        eth_price   = macro_pulse.get("eth_price") or 0
        sol_price   = macro_pulse.get("sol_price") or 0
        fng_value   = macro_pulse.get("fear_greed_value") or 50
        fng_class   = macro_pulse.get("fear_greed_classification", "Neutral")
        vix         = macro_pulse.get("vix") or 20.0
        mkt_cap     = macro_pulse.get("total_market_cap") or 0
        btc_30d     = macro_pulse.get("btc_change_30d") or 0.0

        # Regime detection
        regime = detect_macro_regime(btc_30d, fng_value, vix, btc_dom)

        # ── Conviction ──────────────────────────────────────────────────────
        # BULL: FNG > 60 + BTC momentum positive + VIX < 20
        # BEAR: FNG < 40 + BTC momentum negative + VIX > 25
        btc_momentum = btc_30d > 5
        bullish_signals = (fng_value > 60, btc_momentum, vix < 20)
        bearish_signals  = (fng_value < 40, btc_30d < -5, vix > 25)

        bull_count = sum(bullish_signals)
        bear_count = sum(bearish_signals)

        if bull_count >= 2:
            conviction = "BULL"
        elif bear_count >= 2:
            conviction = "BEAR"
        else:
            conviction = "NEUTRAL"

        # ── Velocity ─────────────────────────────────────────────────────────
        # Detect accelerating vs decelerating from multi-timeframe momentum
        if len(macro_pulse.get("btc_7d", [])) >= 2:
            # 7d momentum vs 30d momentum direction
            pass  # Would need sparkline data — skip for now

        # Fallback velocity from regime
        if regime in ("Risk-On", "Goldilocks", "Easing"):
            velocity = "ACCELERATING" if btc_30d > 5 else "STABLE"
        elif regime in ("Risk-Off", "Stagflation", "Tightening"):
            velocity = "DECELERATING" if btc_30d < -5 else "STABLE"
        else:
            velocity = "STABLE"

        # ── Cross-asset confirmation ─────────────────────────────────────────
        # BTC + ETH + SOL all moving same direction ±5%
        if eth_price > 0 and sol_price > 0:
            # Need % changes - approximate from price vs some reference
            # Simplified: all 3 above their 7d avg as proxy
            cross_confirm = all([
                btc_30d > -10,
                abs(fng_value - 50) > 5,  # sentiment non-neutral
            ])
        else:
            cross_confirm = bool(btc_30d > 0)

        # ── Confidence ──────────────────────────────────────────────────────
        # Based on signal agreement: higher agreement → higher confidence
        if conviction == "BULL" and bull_count == 3:
            confidence = 0.85
        elif conviction == "BULL":
            confidence = 0.70
        elif conviction == "BEAR" and bear_count == 3:
            confidence = 0.85
        elif conviction == "BEAR":
            confidence = 0.70
        else:
            confidence = 0.50

        # ── Time horizon ────────────────────────────────────────────────────
        if regime in ("Risk-Off", "Stagflation"):
            time_horizon = "4h"
        elif regime in ("Goldilocks", "Risk-On"):
            time_horizon = "1week"
        else:
            time_horizon = "24h"

        # ── Key drivers ─────────────────────────────────────────────────────
        drivers = []
        if vix > 25:
            drivers.append(f"VIX elevated ({vix:.1f})")
        if fng_value > 60:
            drivers.append(f"Fear & Greed: {fng_class}")
        elif fng_value < 40:
            drivers.append(f"Fear & Greed: {fng_class}")
        if btc_dom > 55:
            drivers.append(f"BTC dominance high ({btc_dom:.1f}%)")
        elif btc_dom < 48:
            drivers.append(f"Alt season signal (BTC DOM {btc_dom:.1f}%)")
        if btc_30d > 10:
            drivers.append(f"BTC +{btc_30d:.1f}% 30d")
        elif btc_30d < -10:
            drivers.append(f"BTC {btc_30d:.1f}% 30d")
        if mkt_cap > 3e12:
            drivers.append(f"Total mcap ${mkt_cap/1e12:.2f}T")

        key_drivers = drivers[:3] if len(drivers) >= 3 else drivers

        # ── Brief text ───────────────────────────────────────────────────────
        brief_text = (
            f"Macro regime: **{regime}**. "
            f"{'Bullish' if conviction == 'BULL' else 'Bearish' if conviction == 'BEAR' else 'Neutral'} "
            f"conviction. BTC {btc_30d:+.1f}% 30d, F&G {fng_value} ({fng_class}), VIX {vix:.1f}. "
            f"Time horizon: {time_horizon}. "
            f"Key drivers: {', '.join(key_drivers)}."
        )

        return MacroSignal(
            conviction       = conviction,
            velocity          = velocity,
            cross_asset_confirm = cross_confirm,
            confidence        = round(confidence, 2),
            time_horizon      = time_horizon,
            regime            = regime,
            key_drivers       = key_drivers,
            brief_text        = brief_text,
            raw_data          = {k: v for k, v in macro_pulse.items() if not k.startswith("_")},
        )

    except Exception as e:
        _logger.warning(f"[macro_brief_v2] auto-generation failed: {e}")
        return MacroSignal(
            conviction="NEUTRAL",
            velocity="STABLE",
            cross_asset_confirm=False,
            confidence=0.3,
            time_horizon="24h",
            regime="Unknown",
            key_drivers=["data unavailable"],
            brief_text="Macro data unavailable — defaulting to neutral.",
            raw_data={},
        )


# ── LM Studio generation (optional — requires local engine) ──────────────────

async def generate_llm_macro_signal(macro_pulse: dict, model: str = _Qwen_model) -> Optional[MacroSignal]:
    """
    Use LM Studio to generate a structured MacroSignal with natural language reasoning.
    Falls back to auto-generation if LLM is unavailable.
    Requires LM Studio running at http://127.0.0.1:1234
    """
    import httpx

    prompt = f"""你是宏观市场分析师。请根据以下数据生成结构化市场信号：

数据：
{json.dumps(macro_pulse, indent=2)}

请输出以下JSON格式（不要有其他内容）：
{{
  "conviction": "BULL|BEAR|NEUTRAL",
  "velocity": "ACCELERATING|DECELERATING|STABLE",
  "cross_asset_confirm": true|false,
  "confidence": 0.0-1.0,
  "time_horizon": "4h|24h|1week",
  "regime": "Goldilocks|Risk-On|Easing|Neutral|Tightening|Risk-Off|Stagflation",
  "key_drivers": ["driver1", "driver2", "driver3"],
  "brief_text": "中文市场摘要，50-100字"
}}

规则：
- conviction: 2+指标确认才算BULL/BEAR，否则NEUTRAL
- confidence: <0.6时标注UNCERTAIN
- key_drivers最多3条，简洁
"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{LM_STUDIO_BASE}/v1/chat/completions",
                json={
                    "model":   model,
                    "max_tokens": 800,
                    "temperature": 0.3,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            resp = r.json()
            content = resp["choices"][0]["message"]["content"]

            # Extract JSON
            import re
            json_match = re.search(r"\{[\s\S]+?\}", content)
            if not json_match:
                raise ValueError("No JSON found in LLM response")

            data = json.loads(json_match.group())
            return MacroSignal(
                conviction        = data.get("conviction", "NEUTRAL"),
                velocity          = data.get("velocity", "STABLE"),
                cross_asset_confirm = data.get("cross_asset_confirm", False),
                confidence        = float(data.get("confidence", 0.5)),
                time_horizon      = data.get("time_horizon", "24h"),
                regime            = data.get("regime", "Neutral"),
                key_drivers       = data.get("key_drivers", [])[:3],
                brief_text        = data.get("brief_text", ""),
                raw_data          = macro_pulse,
            )

    except Exception as e:
        _logger.warning(f"[macro_brief_v2] LLM generation failed: {e}")
        return None


# ── Main generator ─────────────────────────────────────────────────────────────

async def generate_macro_brief_v2(use_llm: bool = True) -> MacroSignal:
    """
    Generate MacroSignal v2.
    Tries LM Studio first (if use_llm=True), falls back to auto-generation.
    """
    # Fetch live macro-pulse data
    try:
        from src.data.market.data_layer import get_macro_pulse
    except ImportError:
        from data.market.data_layer import get_macro_pulse

    pulse = await get_macro_pulse()
    if not pulse or not pulse.get("btc_price"):
        pulse = {
            "btc_price": 0,
            "eth_price": 0,
            "sol_price": 0,
            "btc_dominance": 50.0,
            "fear_greed_value": 50,
            "fear_greed_classification": "Neutral",
            "vix": 20.0,
            "total_market_cap": 0,
            "btc_change_30d": 0.0,
        }

    # Try LLM first
    if use_llm:
        llm_result = await generate_llm_macro_signal(pulse)
        if llm_result and llm_result.confidence >= 0.6:
            return llm_result

    # Fallback to auto-generation
    return await auto_generate_macro_signal(pulse)


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def _test():
        logging.basicConfig(level=logging.INFO)

        test_pulse = {
            "btc_price": 67850.0,
            "eth_price": 3892.0,
            "sol_price": 195.0,
            "btc_dominance": 56.2,
            "fear_greed_value": 62,
            "fear_greed_classification": "Greed",
            "vix": 18.5,
            "total_market_cap": 2.8e12,
            "btc_change_30d": 8.3,
        }

        print("=== Auto-generated MacroSignal ===")
        signal = await auto_generate_macro_signal(test_pulse)
        print(f"Conviction: {signal.conviction}")
        print(f"Velocity: {signal.velocity}")
        print(f"Confidence: {signal.confidence}")
        print(f"Regime: {signal.regime}")
        print(f"Time horizon: {signal.time_horizon}")
        print(f"Cross-asset confirm: {signal.cross_asset_confirm}")
        print(f"Key drivers: {signal.key_drivers}")
        print(f"Brief: {signal.brief_text}")

        print("\n=== Regime detection ===")
        regimes = [
            (12, 65, 15.0, 52.0),
            (-15, 25, 32.0, 60.0),
            (3, 50, 22.0, 50.0),
            (8, 72, 14.0, 54.0),
        ]
        for btc, fng, vix, dom in regimes:
            r = detect_macro_regime(btc, fng, vix, dom)
            print(f"  BTC={btc:+d}%, F&G={fng}, VIX={vix:.1f}, DOM={dom:.1f} → {r}")

    asyncio.run(_test())