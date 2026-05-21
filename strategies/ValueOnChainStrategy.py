"""
CometCloud Value / On-Chain Strategy (F+O)
==========================================
Factor weights: Fundamental 40% · On-Chain/Risk 35% · Alpha 10% · Momentum 10% · Sentiment 5%

Entry philosophy:
  Targets assets that are fundamentally undervalued with strong on-chain metrics
  and risk-adjusted profile. Filters out hype — ideal when the market rewards
  quality over speculation. Best in Tightening, Risk-Off, Stagflation regimes.

CIS gate:
  Strategy CIS (re-weighted) ≥ 58 AND F pillar ≥ 60 AND O pillar ≥ 55
  Skips when macro_regime is Risk-On / Easing (momentum strategies outperform instead)

Technical confirmation (secondary):
  - RSI 1D below 55 (not extended / not momentum-driven)
  - Price within 15% of 50-period EMA (not runaway, value range)
  - Volume at least 0.7x of 20-day average (liquidity floor)
  - 7-day consecutive loss streak allowed (value accumulation zone)

Risk:
  Stoploss: -8% (wider — value takes time)  |  ROI: +18% over 30-90d  |  Hold: 30-90 days (concept)
  Freqtrade dry-run with paper capital only.

Minimax: copy to /Volumes/CometCloudAI/cometcloud-local/user_data/strategies/
"""

import logging, requests
from freqtrade.strategy import IStrategy
from freqtrade.persistence import Trade
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ── CIS Configuration ─────────────────────────────────────────────────────────
RAILWAY_API   = "https://looloomi.ai/api/v1"
CIS_ENDPOINT  = f"{RAILWAY_API}/strategies/value_onchain/signals?top_n=50"
CIS_CACHE_TTL = 1800  # 30min — matches Mac Mini push cadence

# ── Strategy Parameters ───────────────────────────────────────────────────────
MIN_STRATEGY_CIS  = 58
MIN_F_PILLAR      = 60
MIN_O_PILLAR      = 55
UNFAVORABLE_REGIMES = {"Risk-On", "Easing", "RISK_ON", "EASING"}

_cis_cache: dict = {}
_cis_fetched_at: float = 0.0


def _fetch_strategy_signals() -> dict:
    """Fetch pre-weighted strategy signals from Railway API (value_onchain profile)."""
    import time
    global _cis_cache, _cis_fetched_at
    now = time.time()
    if now - _cis_fetched_at < CIS_CACHE_TTL and _cis_cache:
        return _cis_cache
    try:
        r = requests.get(CIS_ENDPOINT, timeout=15)
        if r.ok:
            data = r.json()
            regime = data.get("current_regime", "Neutral")
            out = {"regime": regime, "assets": {}}
            for a in data.get("signals", []):
                sym = a.get("symbol", "").upper()
                if sym:
                    out["assets"][sym] = {
                        "strategy_cis": a.get("strategy_cis", 0),
                        "F": a.get("pillar_scores", {}).get("F", 0),
                        "M": a.get("pillar_scores", {}).get("M", 0),
                        "O": a.get("pillar_scores", {}).get("O", 0),
                        "S": a.get("pillar_scores", {}).get("S", 0),
                        "A": a.get("pillar_scores", {}).get("A", 0),
                        "strategy_signal": a.get("strategy_signal", "NEUTRAL"),
                    }
            _cis_cache = out
            _cis_fetched_at = now
            logger.info(f"[ValueOnChain] CIS signals loaded — {len(out['assets'])} assets, regime={regime}")
            return out
    except Exception as e:
        logger.warning(f"[ValueOnChain] CIS fetch failed: {e}")
    return _cis_cache or {"regime": "Neutral", "assets": {}}


def _asset_qualifies(symbol: str, data: dict) -> bool:
    """Check if an asset passes Value/On-Chain strategy entry criteria."""
    regime = data.get("regime", "Neutral")
    if regime in UNFAVORABLE_REGIMES:
        logger.debug(f"[ValueOnChain] {symbol}: regime {regime} unfavorable — skip")
        return False
    asset = data.get("assets", {}).get(symbol)
    if not asset:
        return False
    strat_cis = asset.get("strategy_cis", 0)
    f_pillar  = asset.get("F", 0)
    o_pillar  = asset.get("O", 0)
    passes = (
        strat_cis >= MIN_STRATEGY_CIS and
        f_pillar  >= MIN_F_PILLAR and
        o_pillar  >= MIN_O_PILLAR
    )
    logger.debug(
        f"[ValueOnChain] {symbol}: strat_cis={strat_cis:.1f}(≥{MIN_STRATEGY_CIS}) "
        f"F={f_pillar:.0f}(≥{MIN_F_PILLAR}) O={o_pillar:.0f}(≥{MIN_O_PILLAR}) → {passes}"
    )
    return passes


class ValueOnChainStrategy(IStrategy):
    """
    CIS-gated Value / On-Chain Strategy.
    Primary signal: strategy_cis (F+O weighted) ≥ 58.
    Technical confirmation: RSI ≤ 55, near EMA-50, volume floor.
    """

    INTERFACE_VERSION = 3
    timeframe = "1d"  # Daily — value strategy needs longer timeframe

    # Risk — wider stop, higher target
    stoploss      = -0.08
    minimal_roi   = {"0": 0.18, "1440": 0.10, "4320": 0.05, "8640": 0}
    can_short     = False
    use_exit_signal = True

    position_adjustment_enable = False

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        sym = metadata["pair"].split("/")[0].upper()

        # ── Technical indicators ──────────────────────────────────────────────
        # RSI
        delta = dataframe["close"].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        dataframe["rsi"] = 100 - (100 / (1 + rs))

        # EMA 50 (value range)
        dataframe["ema_50"] = dataframe["close"].ewm(span=50).mean()

        # Price distance from EMA (normalized)
        dataframe["ema_dist"] = (dataframe["close"] - dataframe["ema_50"]) / dataframe["ema_50"]

        # Volume ratio (vs 20-day avg)
        dataframe["vol_avg_20"] = dataframe["volume"].rolling(20).mean()
        dataframe["vol_ratio"]  = dataframe["volume"] / dataframe["vol_avg_20"].replace(0, np.nan)

        # Consecutive down days (value accumulation indicator)
        down_days = (dataframe["close"] < dataframe["close"].shift(1)).astype(int)
        dataframe["streak_down"] = down_days.groupby(
            (down_days == 0).cumsum()
        ).cumcount()

        # ── CIS strategy gate ─────────────────────────────────────────────────
        cis_data = _fetch_strategy_signals()
        qualifies = _asset_qualifies(sym, cis_data)
        dataframe["cis_gate"] = 1 if qualifies else 0

        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        conditions = [
            dataframe["cis_gate"] == 1,              # CIS F+O strategy pass
            dataframe["rsi"] < 55,                   # Not extended
            dataframe["rsi"] > 25,                   # Not in freefall
            dataframe["ema_dist"].abs() < 0.15,      # Within 15% of EMA-50
            dataframe["vol_ratio"] >= 0.7,           # Liquidity floor
            dataframe["volume"] > 0,
        ]
        dataframe.loc[
            pd.concat(conditions, axis=1).all(axis=1), "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Exit when momentum clearly kicks in (RSI overbought) or price far extended
        exit_cond = (
            (dataframe["rsi"] > 70) |
            (dataframe["ema_dist"] > 0.20)  # >20% above EMA — take profit
        )
        dataframe.loc[exit_cond, "exit_long"] = 1
        return dataframe

    def custom_stoploss(self, current_time, current_rate, current_profit,
                        min_profit, trade, **kwargs) -> float:
        """Trail stoploss to -4% after 8% gain (protect value capture)."""
        if current_profit >= 0.08:
            return -0.04
        return self.stoploss
