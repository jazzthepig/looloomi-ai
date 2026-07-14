"""
CometCloud Breakout Strategy (S+M)
===================================
Factor weights: Sentiment 35% · Momentum 35% · Fundamental 10% · On-Chain 10% · Alpha 10%

Entry philosophy:
  Assets where crowd sentiment AND price momentum are accelerating simultaneously —
  classic pre-breakout setup before a trend becomes consensus. Optimal in Risk-On,
  Easing, and Goldilocks macro regimes.

CIS gate:
  Strategy CIS (re-weighted) ≥ 62 AND M pillar ≥ 55 AND S pillar ≥ 52
  Skips when macro_regime is Tightening / Risk-Off / Stagflation (low fitness)

Technical confirmation (secondary):
  - 4H MACD histogram positive (momentum confirmation)
  - RSI 4H between 45-72 (not exhausted)
  - Price above 20-period EMA (trend alignment)

Risk:
  Stoploss: -5%  |  ROI target: +12%  |  Hold: 14-30 days (concept)
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
CIS_ENDPOINT  = f"{RAILWAY_API}/strategies/breakout/signals?top_n=50"
CIS_CACHE_TTL = 1800  # 30min — matches Mac Mini push cadence

# ── Strategy Parameters ───────────────────────────────────────────────────────
MIN_STRATEGY_CIS  = 62
MIN_M_PILLAR      = 55
MIN_S_PILLAR      = 52
UNFAVORABLE_REGIMES = {"Tightening", "Risk-Off", "Stagflation", "TIGHTENING", "RISK_OFF", "STAGFLATION"}

_cis_cache: dict = {}
_cis_fetched_at: float = 0.0


def _fetch_strategy_signals() -> dict:
    """Fetch pre-weighted strategy signals from Railway API (breakout profile)."""
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
            # Build {symbol: {strategy_cis, pillar_scores, strategy_grade, qualifies}}
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
            logger.info(f"[Breakout] CIS signals loaded — {len(out['assets'])} assets, regime={regime}")
            return out
    except Exception as e:
        logger.warning(f"[Breakout] CIS fetch failed: {e}")
    return _cis_cache or {"regime": "Neutral", "assets": {}}


def _asset_qualifies(symbol: str, data: dict) -> bool:
    """Check if an asset passes breakout strategy entry criteria."""
    regime = data.get("regime", "Neutral")
    if regime in UNFAVORABLE_REGIMES:
        logger.debug(f"[Breakout] {symbol}: regime {regime} unfavorable — skip")
        return False
    asset = data.get("assets", {}).get(symbol)
    if not asset:
        return False
    strat_cis = asset.get("strategy_cis", 0)
    m_pillar   = asset.get("M", 0)
    s_pillar   = asset.get("S", 0)
    passes = (
        strat_cis >= MIN_STRATEGY_CIS and
        m_pillar  >= MIN_M_PILLAR and
        s_pillar  >= MIN_S_PILLAR
    )
    logger.debug(
        f"[Breakout] {symbol}: strat_cis={strat_cis:.1f}(≥{MIN_STRATEGY_CIS}) "
        f"M={m_pillar:.0f}(≥{MIN_M_PILLAR}) S={s_pillar:.0f}(≥{MIN_S_PILLAR}) → {passes}"
    )
    return passes


class BreakoutStrategy(IStrategy):
    """
    CIS-gated Breakout Strategy.
    Primary signal: strategy_cis (S+M weighted) ≥ 62.
    Technical confirmation: 4H MACD + RSI + EMA.
    """

    INTERFACE_VERSION = 3
    timeframe = "4h"

    # Risk
    stoploss      = -0.05
    minimal_roi   = {"0": 0.12, "720": 0.06, "1440": 0.03, "2880": 0}
    can_short     = False
    use_exit_signal = True

    # Position sizing
    position_adjustment_enable = False

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        sym = metadata["pair"].split("/")[0].upper()

        # ── Technical indicators ──────────────────────────────────────────────
        # MACD
        ema12 = dataframe["close"].ewm(span=12).mean()
        ema26 = dataframe["close"].ewm(span=26).mean()
        dataframe["macd"]        = ema12 - ema26
        dataframe["macd_signal"] = dataframe["macd"].ewm(span=9).mean()
        dataframe["macd_hist"]   = dataframe["macd"] - dataframe["macd_signal"]

        # RSI
        delta = dataframe["close"].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        dataframe["rsi"] = 100 - (100 / (1 + rs))

        # EMA 20
        dataframe["ema_20"] = dataframe["close"].ewm(span=20).mean()

        # ── CIS strategy gate ─────────────────────────────────────────────────
        cis_data = _fetch_strategy_signals()
        qualifies = _asset_qualifies(sym, cis_data)
        dataframe["cis_gate"] = 1 if qualifies else 0

        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        conditions = [
            dataframe["cis_gate"] == 1,             # CIS S+M strategy pass
            dataframe["macd_hist"] > 0,              # Momentum confirmation
            dataframe["rsi"] > 45,                   # Not oversold-stalled
            dataframe["rsi"] < 72,                   # Not overbought
            dataframe["close"] > dataframe["ema_20"],# Above 20 EMA
            dataframe["volume"] > 0,
        ]
        dataframe.loc[
            pd.concat(conditions, axis=1).all(axis=1), "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        conditions = [
            (dataframe["macd_hist"] < 0) |           # Momentum reversal
            (dataframe["rsi"] > 75) |                # Overbought exit
            (dataframe["close"] < dataframe["ema_20"]),  # Below 20 EMA
        ]
        dataframe.loc[conditions[0], "exit_long"] = 1
        return dataframe
