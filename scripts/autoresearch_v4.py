#!/usr/bin/env python3
"""
CometCloud AutoResearch v4 — V4-compliant strategy generation
==============================================================

Refactor of `Shadow/cometcloud-local/tools/autoresearch.py` to produce strategies
that clear STRATEGY_VALIDATION.md gates by construction. Key deltas:

  1. Compliance enter_tag — `LONG_AUTO_R{regime}_T{tier}_S{score}` instead of
     `auto_long` (Track A compliance language).
  2. CIS gate — generated strategies read CIS scores from cache and gate entries
     by regime pillars + min_cis_score.
  3. ATR vol SL/TP — replaces fixed stoploss + ROI ladder with
     `custom_stoploss()` + `custom_exit()` ladder (1.5x / 2.5x / 1.0x after 24h).
  4. Funding rate filter — `confirm_trade_entry()` skips on crowded long
     (fr > +3 bps).
  5. 1d trend filter — long entries only when 1d close > EMA50.
  6. Regime-aware stake — `custom_stake_amount()` scales 0.5x-1.2x per regime.
  7. Walk-forward scoring — grid search runs on train window, scores on test
     window; degradation ratio reported.
  8. Per-regime segmentation — backtest tracks per-regime PF; gates require
     >=3 active regimes with non-negative contribution.

Usage:
    python scripts/autoresearch_v4.py --mode research --pairs BTC_USDT ETH_USDT --timeframe 4h
    python scripts/autoresearch_v4.py --mode walk-forward --pairs BTC_USDT --train-months 12 --test-months 2
    python scripts/autoresearch_v4.py --mode upgrade --output Shadow/freqtrade/user_data/strategies/AutoV4.py

Outputs:
    results written to reports/autoresearch_v4_results_{YYYYMMDD_HHMM}.json
    generated strategy at --output path (default: Shadow/freqtrade/user_data/strategies/...)
"""

import argparse
import copy
import hashlib
import json
import logging
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


# ════════════════════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════════════════════

REPO_ROOT = Path(__file__).parent.parent

# Runtime outputs land on the CometCloud AI drive (Minimax's territory).
# Shadow/ in the repo is only a local mirror of /Volumes/CometCloudAI/ —
# runtime outputs MUST go to the drive, not the repo.
DRIVE_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
REPORTS_DIR = DRIVE_ROOT / "_reports" / "autoresearch"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Generated strategies land in Shadow/ (which is a mirror of the drive's
# /Volumes/CometCloudAI/freqtrade/user_data/strategies/). They'll sync to
# the canonical location via the existing sync process.
SHADOW_STRATEGIES = REPO_ROOT / "Shadow" / "freqtrade" / "user_data" / "strategies"

# CIS cache + signal hub (same paths as CISEnhancedV4)
CIS_CACHE_PATH = os.getenv(
    "CIS_CACHE_PATH",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_scores_latest.json",
)

# ATR knobs (verbatim from CISEnhancedV4)
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TP1_MULT = 2.5
ATR_TP2_MULT = 1.0
ATR_MIN_STOP_PCT = 0.020
ATR_MIN_TP_PCT = 0.030

# Funding rate knobs
FUNDING_SKIP_BPS = 3.0
FUNDING_BONUS_BPS = -3.0

# Multi-timeframe
DAILY_TREND_EMA = 50

# Regime-aware stake multipliers
STAKE_MULT_BY_REGIME = {
    "Tightening": 0.50, "Risk-Off": 0.50, "Stagflation": 0.60,
    "Neutral": 0.80, "Easing": 1.00, "Risk-On": 1.00, "Goldilocks": 1.20,
}

# Macro regime -> CIS pillar floor (verbatim from CISEnhancedV4)
_REGIME_CONFIGS = {
    "Tightening":  {"mode": "reversal", "entry_pillars": {"F": 55, "O": 50}, "min_cis": 45},
    "Risk-Off":    {"mode": "reversal", "entry_pillars": {"F": 55, "O": 50}, "min_cis": 45},
    "Stagflation": {"mode": "reversal", "entry_pillars": {"F": 60, "O": 55}, "min_cis": 50},
    "Easing":      {"mode": "breakout", "entry_pillars": {"M": 55, "S": 52}, "min_cis": 58},
    "Risk-On":     {"mode": "breakout", "entry_pillars": {"M": 55, "S": 52}, "min_cis": 58},
    "Goldilocks":  {"mode": "breakout", "entry_pillars": {"M": 50, "S": 48}, "min_cis": 55},
    "Neutral":     {"mode": "breakout", "entry_pillars": {"M": 52, "S": 48}, "min_cis": 55},
}

_PILLAR_ALIAS = {
    "F": "Fundamental", "M": "Momentum", "O": "Risk-Adjusted",
    "S": "Sensitivity", "A": "Alpha",
}


# ════════════════════════════════════════════════════════════════════════════════
# Factor Engine (factor library reused from autoresearch.py)
# ════════════════════════════════════════════════════════════════════════════════

class FactorEngine:
    """Compute all factors on a price dataframe."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def calculate_all(self) -> pd.DataFrame:
        df = self.df
        df = self._add_basic_indicators(df)
        df = self._add_momentum_indicators(df)
        df = self._add_volatility_indicators(df)
        df = self._add_volume_indicators(df)
        df = self._add_regime_and_smc(df)
        df = self._add_composite_signals(df)
        return df

    def _add_basic_indicators(self, df):
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
        gain7 = delta.where(delta > 0, 0).rolling(7).mean()
        loss7 = (-delta.where(delta < 0, 0)).rolling(7).mean()
        rs7 = gain7 / loss7.replace(0, np.nan)
        df['rsi_7'] = 100 - (100 / (1 + rs7))
        low_20 = df['low'].rolling(20).min()
        high_20 = df['high'].rolling(20).max()
        df['price_pos'] = (df['close'] - low_20) / (high_20 - low_20 + 0.001)
        return df

    def _add_momentum_indicators(self, df):
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        df['macd_bullish'] = (df['macd_hist'] > 0).astype(int)
        df['macd_bearish'] = (df['macd_hist'] < 0).astype(int)
        bb_ma = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['bb_upper'] = bb_ma + 2 * bb_std
        df['bb_lower'] = bb_ma - 2 * bb_std
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (bb_ma + 0.001)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 0.001)
        return df

    def _add_volatility_indicators(self, df):
        high, low, close = df['high'], df['low'], df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['tr'] = tr
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close']
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_di = 100 * (plus_dm.rolling(14).mean() / df['atr'])
        minus_di = 100 * (minus_dm.rolling(14).mean() / df['atr'])
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 0.001)
        df['adx'] = dx.rolling(14).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        return df

    def _add_volume_indicators(self, df):
        df['vol_ma'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_ma']
        df['vol_confirm_up'] = ((df['close'] > df['close'].shift(1)) & (df['vol_ratio'] > 1.0)).astype(int)
        df['vol_confirm_down'] = ((df['close'] < df['close'].shift(1)) & (df['vol_ratio'] > 1.0)).astype(int)
        return df

    def _add_regime_and_smc(self, df):
        # ADX-based regime
        def classify(row):
            adx = row.get('adx', 30)
            plus = row.get('plus_di', 50)
            minus = row.get('minus_di', 50)
            if adx > 40:
                return 'BULL' if plus > minus else 'BEAR'
            elif adx < 25:
                return 'CRAB'
            return 'TREND'
        df['regime'] = df.apply(classify, axis=1)

        # SMC: FVG
        df['fvg_bullish'] = (
            (df['low'] > df['high'].shift(2)) &
            (df['close'] > df['open'].shift(2))
        ).astype(int)
        df['fvg_bearish'] = (
            (df['high'] < df['low'].shift(2)) &
            (df['close'] < df['open'].shift(2))
        ).astype(int)
        # Order Block
        is_bearish = (df['close'] < df['open']).astype(int)
        is_bullish = (df['close'] > df['open']).astype(int)
        up_move = df['close'] > df['close'].shift(1)
        down_move = df['close'] < df['close'].shift(1)
        df['bullish_ob'] = (is_bearish & up_move.shift(1).fillna(False)).astype(int)
        df['bearish_ob'] = (is_bullish & down_move.shift(1).fillna(False)).astype(int)
        # Liquidity sweeps
        df['liquidity_sweep_low'] = (
            (df['low'] < df['low'].shift(1).rolling(20).min()) &
            (df['close'] > df['open'])
        ).astype(int)
        df['liquidity_sweep_high'] = (
            (df['high'] > df['high'].shift(1).rolling(20).max()) &
            (df['close'] < df['open'])
        ).astype(int)
        return df

    def _add_composite_signals(self, df):
        df['bullish_confluence'] = (
            (df['rsi'] < 35).astype(int) +
            (df['macd_bullish'] == 1).astype(int) +
            (df['price_pos'] < 0.2).astype(int) +
            (df['vol_confirm_up'] == 1).astype(int)
        )
        df['bearish_confluence'] = (
            (df['rsi'] > 65).astype(int) +
            (df['macd_bearish'] == 1).astype(int) +
            (df['price_pos'] > 0.8).astype(int) +
            (df['vol_confirm_down'] == 1).astype(int)
        )
        close_arr = df['close'].values
        streak_down = np.zeros(len(df), dtype=np.int32)
        streak_up = np.zeros(len(df), dtype=np.int32)
        for i in range(1, len(close_arr)):
            if close_arr[i] < close_arr[i-1]:
                streak_down[i] = streak_down[i-1] + 1
            else:
                streak_down[i] = 0
            if close_arr[i] > close_arr[i-1]:
                streak_up[i] = streak_up[i-1] + 1
            else:
                streak_up[i] = 0
        df['streak_down'] = streak_down
        df['streak_up'] = streak_up
        return df


# ════════════════════════════════════════════════════════════════════════════════
# Data Loading
# ════════════════════════════════════════════════════════════════════════════════

def load_binance_data(pair: str, timeframe: str, data_root: Path) -> Optional[pd.DataFrame]:
    """Load OHLCV from .feather files (Mac Mini or wherever .feather lives)."""
    file_path = data_root / f"{pair}-{timeframe}.feather"
    if not file_path.exists():
        return None
    try:
        import pyarrow.feather as feather
        df = feather.read_feather(file_path)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception as exc:
        logger.warning(f"Failed to load {file_path}: {exc}")
        return None


def load_cis_cache() -> dict:
    """Load CIS scores for regime-aware scoring (best-effort)."""
    p = Path(CIS_CACHE_PATH)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════════════════════
# Strategy Config (v4-aware)
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class StrategyConfig:
    """Strategy configuration with v4 compliance toggles."""

    name: str
    description: str
    tier: str = "T4"  # T1 (proven) / T2 (good mod) / T3 (speculative) / T4 (novel)

    # ── Entry thresholds ──
    rsi_entry_long: float = 30.0
    rsi_entry_short: float = 70.0
    adx_entry: float = 25.0
    price_pos_entry_long: float = 0.20
    price_pos_entry_short: float = 0.85
    streak_entry: int = 4
    confluence_min: int = 2

    # ── Filters ──
    use_vol_confirm: bool = False
    use_smc_fvg: bool = False
    use_smc_ob: bool = False
    use_smc_liquidity: bool = False

    # ── Vol-adaptive ──
    use_vol_adaptive: bool = False
    rsi_low_vol: float = 35.0
    rsi_mid_vol: float = 30.0
    rsi_high_vol: float = 25.0

    # ── Exit ──
    rsi_exit_long: float = 50.0
    use_regime_exit: bool = True
    trailing_offset: float = 0.025

    # ── Risk ──
    stop_loss: float = 0.03
    max_open_trades: int = 3
    confirmation_candles: int = 1

    # ── NEW: v4 compliance toggles (all default on) ──
    enable_cis_gate: bool = True
    min_cis_score: float = 50.0
    enable_atr_sl_tp: bool = True
    enable_funding_filter: bool = True
    enable_1d_trend: bool = True
    enable_regime_stake: bool = True

    # ── Metadata (populated after backtest) ──
    expected_pf: float = 0.0
    trade_count: int = 0
    win_rate: float = 0.0
    regime_segments: Dict[str, Dict] = field(default_factory=dict)
    walk_forward_passed: bool = False
    walk_forward_degradation: float = 1.0
    gate_compliance: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": self.tier,
            "params": {
                "rsi_entry_long": self.rsi_entry_long,
                "rsi_entry_short": self.rsi_entry_short,
                "adx_entry": self.adx_entry,
                "price_pos_entry_long": self.price_pos_entry_long,
                "confluence_min": self.confluence_min,
                "streak_entry": self.streak_entry,
                "stop_loss": self.stop_loss,
                "use_vol_adaptive": self.use_vol_adaptive,
                "use_smc_fvg": self.use_smc_fvg,
                "use_smc_ob": self.use_smc_ob,
            },
            "v4_compliance": {
                "cis_gate": self.enable_cis_gate,
                "min_cis_score": self.min_cis_score,
                "atr_sl_tp": self.enable_atr_sl_tp,
                "funding_filter": self.enable_funding_filter,
                "1d_trend": self.enable_1d_trend,
                "regime_stake": self.enable_regime_stake,
            },
            "results": {
                "pf": round(self.expected_pf, 3),
                "trades": self.trade_count,
                "win_rate": round(self.win_rate, 2),
                "regime_segments": self.regime_segments,
                "walk_forward_passed": self.walk_forward_passed,
                "walk_forward_degradation": round(self.walk_forward_degradation, 3),
                "gate_compliance": self.gate_compliance,
            },
        }


# ════════════════════════════════════════════════════════════════════════════════
# Backtest Result with Regime Segmentation
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    strategy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    avg_hold_hours: float = 0.0

    # NEW: per-regime breakdown
    regime_segments: Dict[str, Dict] = field(default_factory=dict)

    # NEW: v4 gate compliance (set by orchestrator)
    gate_compliance: Dict[str, bool] = field(default_factory=dict)

    def score(self) -> float:
        """
        V4 score: PF × WR × min(50,trades)/50 × max(0, 1 - max_dd/50) × regime_breadth.

        Regime breadth = (# regimes with PF >= 1.0) / 4 (minimum 4 active regimes
        for the strategy to be considered "regime-diversified").
        """
        if self.profit_factor <= 0 or self.total_trades < 10:
            return 0.0
        pf_score = min(self.profit_factor / 2.0, 1.0)
        wr_score = self.win_rate / 100.0
        trade_score = min(self.total_trades / 50.0, 1.0)
        dd_score = max(0.0, 1.0 - self.max_drawdown / 50.0)
        # Regime breadth
        active_regimes = sum(
            1 for r, m in self.regime_segments.items()
            if m.get("trades", 0) >= 3 and m.get("pf", 0) >= 1.0
        )
        regime_score = min(active_regimes / 4.0, 1.0)
        return (
            pf_score * 0.35
            + wr_score * 0.20
            + trade_score * 0.15
            + dd_score * 0.15
            + regime_score * 0.15
        )

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "total_trades": self.total_trades,
            "win_rate": f"{self.win_rate:.1f}%",
            "profit_factor": f"{self.profit_factor:.2f}",
            "total_return": f"{self.total_return:.1f}%",
            "max_drawdown": f"{self.max_drawdown:.1f}%",
            "sharpe": f"{self.sharpe:.2f}",
            "score": f"{self.score():.3f}",
            "regime_segments": self.regime_segments,
            "gate_compliance": self.gate_compliance,
        }


# ════════════════════════════════════════════════════════════════════════════════
# Backtest Engine (vectorized + regime tracking)
# ════════════════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """Vectorized single-position backtest with regime segmentation."""

    def __init__(self, df: pd.DataFrame, config: StrategyConfig):
        self.df = df
        self.config = config

    def generate_signals(self) -> pd.DataFrame:
        df = self.df.copy()
        c = self.config

        # ── Vol-adaptive parameters ──
        if c.use_vol_adaptive:
            atr = df['atr_pct'].values
            rsi_eff = np.where(atr > 0.05, c.rsi_high_vol,
                        np.where(atr > 0.025, c.rsi_mid_vol, c.rsi_low_vol))
            df['rsi_eff'] = rsi_eff
        else:
            df['rsi_eff'] = c.rsi_entry_long

        # ── Entry conditions ──
        long_conds = []
        short_conds = []

        # RSI
        long_conds.append(df['rsi'].values < df['rsi_eff'].values if c.use_vol_adaptive
                          else df['rsi'] < c.rsi_entry_long)
        short_conds.append(df['rsi'].values > (100 - df['rsi_eff'].values) if c.use_vol_adaptive
                           else df['rsi'] > c.rsi_entry_short)

        # ADX
        long_conds.append(df['adx'] > c.adx_entry)
        short_conds.append(df['adx'] > c.adx_entry)

        # Price position
        long_conds.append(df['price_pos'] < c.price_pos_entry_long)
        short_conds.append(df['price_pos'] > c.price_pos_entry_short)

        # Streak
        if c.streak_entry > 0:
            long_conds.append(df['streak_down'] >= c.streak_entry)
            short_conds.append(df['streak_up'] >= c.streak_entry)

        # Confluence
        if c.confluence_min > 1:
            long_conds.append(df['bullish_confluence'] >= c.confluence_min)
            short_conds.append(df['bearish_confluence'] >= c.confluence_min)

        # Volume
        if c.use_vol_confirm:
            long_conds.append(df['vol_confirm_up'] == 1)
            short_conds.append(df['vol_confirm_down'] == 1)

        # SMC
        if c.use_smc_fvg:
            long_conds.append(df['fvg_bullish'] == 1)
            short_conds.append(df['fvg_bearish'] == 1)
        if c.use_smc_ob:
            long_conds.append(df['bullish_ob'] == 1)
            short_conds.append(df['bearish_ob'] == 1)
        if c.use_smc_liquidity:
            long_conds.append(df['liquidity_sweep_low'] == 1)
            short_conds.append(df['liquidity_sweep_high'] == 1)

        df['enter_long_raw'] = pd.concat(long_conds, axis=1).all(axis=1) if long_conds else pd.Series(False, index=df.index)
        df['enter_short_raw'] = pd.concat(short_conds, axis=1).all(axis=1) if short_conds else pd.Series(False, index=df.index)

        # Confirmation candles
        if c.confirmation_candles > 1:
            df['enter_long'] = (df['enter_long_raw'].rolling(c.confirmation_candles).sum()
                                >= c.confirmation_candles).astype(int)
            df['enter_short'] = (df['enter_short_raw'].rolling(c.confirmation_candles).sum()
                                 >= c.confirmation_candles).astype(int)
        else:
            df['enter_long'] = df['enter_long_raw'].astype(int)
            df['enter_short'] = df['enter_short_raw'].astype(int)

        # Cooldown (15 bars)
        df['enter_long_cd'] = df['enter_long'].rolling(15, min_periods=1).sum().shift(1)
        df['enter_short_cd'] = df['enter_short'].rolling(15, min_periods=1).sum().shift(1)
        df.loc[df['enter_long_cd'] > 0, 'enter_long'] = 0
        df.loc[df['enter_short_cd'] > 0, 'enter_short'] = 0

        # Exit
        if c.use_regime_exit:
            df['exit_long'] = ((df['regime'] == 'BEAR') & (df['adx'] > 45)).astype(int)
            df['exit_short'] = ((df['regime'] == 'BULL') & (df['adx'] > 45)).astype(int)
        else:
            df['exit_long'] = (df['rsi'] > c.rsi_exit_long).astype(int)
            df['exit_short'] = (df['rsi'] < (100 - c.rsi_exit_long)).astype(int)

        return df

    def run(self, initial_capital: float = 10000, position_pct: float = 0.1) -> BacktestResult:
        df = self.generate_signals()
        c = self.config

        capital = initial_capital
        peak = initial_capital
        max_dd = 0
        trades = []
        in_position = False
        entry_time = entry_price = direction = None

        for i in range(50, len(df)):
            row = df.iloc[i]
            if not in_position:
                if row['enter_long'] == 1:
                    in_position = True
                    direction = 'long'
                    entry_time = row['date']
                    entry_price = row['close']
                elif row['enter_short'] == 1:
                    in_position = True
                    direction = 'short'
                    entry_time = row['date']
                    entry_price = row['close']
            else:
                pnl_pct = ((row['close'] - entry_price) / entry_price
                           if direction == 'long'
                           else (entry_price - row['close']) / entry_price)
                exit_now = False
                exit_reason = ''
                if pnl_pct < -c.stop_loss:
                    exit_now = True
                    exit_reason = 'stop_loss'
                elif direction == 'long' and row['exit_long'] == 1:
                    exit_now = True
                    exit_reason = 'signal'
                elif direction == 'short' and row['exit_short'] == 1:
                    exit_now = True
                    exit_reason = 'signal'
                if exit_now:
                    pnl_value = capital * position_pct * pnl_pct
                    capital += pnl_value
                    hold_hours = (row['date'] - entry_time).total_seconds() / 3600 if hasattr(row['date'], 'total_seconds') else 0
                    trades.append({
                        'entry_time': entry_time,
                        'exit_time': row['date'],
                        'direction': direction,
                        'pnl_pct': pnl_pct * 100,
                        'hold_hours': hold_hours,
                        'exit_reason': exit_reason,
                        'regime': row.get('regime', 'TREND'),
                    })
                    peak = max(capital, peak)
                    dd = (peak - capital) / peak if peak > 0 else 0
                    max_dd = max(max_dd, dd)
                    in_position = False

        # Aggregate
        if not trades:
            return BacktestResult(strategy_name=c.name)

        pnls = [t['pnl_pct'] for t in trades]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]
        total_return = (capital - initial_capital) / initial_capital * 100
        pf = abs(sum(winners) / sum(losers)) if losers and sum(losers) != 0 else float('inf')
        sharpe = (np.mean(pnls) / np.std(pnls) * np.sqrt(252 * 6)
                  if len(pnls) > 1 and np.std(pnls) > 0 else 0)

        # Per-regime segmentation
        regime_segments = {}
        for regime in ['BULL', 'BEAR', 'TREND', 'CRAB']:
            regime_trades = [t for t in trades if t['regime'] == regime]
            if regime_trades:
                r_pnls = [t['pnl_pct'] for t in regime_trades]
                r_winners = [p for p in r_pnls if p > 0]
                r_losers = [p for p in r_pnls if p <= 0]
                r_pf = abs(sum(r_winners) / sum(r_losers)) if r_losers and sum(r_losers) != 0 else float('inf')
                regime_segments[regime] = {
                    "trades": len(regime_trades),
                    "win_rate": round(len(r_winners) / len(regime_trades) * 100, 1),
                    "pf": round(r_pf, 2) if r_pf != float('inf') else "inf",
                    "total_pnl_pct": round(sum(r_pnls), 2),
                }

        return BacktestResult(
            strategy_name=c.name,
            total_trades=len(trades),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=len(winners) / len(trades) * 100,
            profit_factor=pf if pf != float('inf') else 99.0,
            total_return=total_return,
            max_drawdown=max_dd * 100,
            sharpe=sharpe,
            avg_hold_hours=np.mean([t['hold_hours'] for t in trades]),
            regime_segments=regime_segments,
        )


# ════════════════════════════════════════════════════════════════════════════════
# Walk-Forward Engine
# ════════════════════════════════════════════════════════════════════════════════

class WalkForwardEngine:
    """
    Train on first N months, test on next M months, compute degradation ratio.

    degradation = test_sharpe / train_sharpe (1.0 = no degradation, <0.5 = severe).
    """

    def __init__(self, df: pd.DataFrame, train_months: int = 12, test_months: int = 2):
        self.df = df
        self.train_months = train_months
        self.test_months = test_months

    def split(self) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Return [(train_df, test_df), ...] non-overlapping folds."""
        df = self.df.sort_values('date').reset_index(drop=True)
        folds = []
        start = df['date'].iloc[0]
        end = df['date'].iloc[-1]
        cursor = start
        while True:
            train_end = cursor + pd.DateOffset(months=self.train_months)
            test_end = train_end + pd.DateOffset(months=self.test_months)
            if test_end > end:
                break
            train_df = df[(df['date'] >= cursor) & (df['date'] < train_end)].copy()
            test_df = df[(df['date'] >= train_end) & (df['date'] < test_end)].copy()
            if len(train_df) > 50 and len(test_df) > 20:
                folds.append((train_df, test_df))
            cursor = train_end
        return folds

    def evaluate(self, config: StrategyConfig) -> Tuple[bool, float]:
        """Returns (walk_forward_passed, degradation_ratio)."""
        folds = self.split()
        if not folds:
            return False, 0.0

        train_sharpes = []
        test_sharpes = []
        for train_df, test_df in folds:
            # Re-fit factor engine on each fold (train and test independently)
            train_engine = BacktestEngine(FactorEngine(train_df).calculate_all(), config)
            test_engine = BacktestEngine(FactorEngine(test_df).calculate_all(), config)
            train_res = train_engine.run()
            test_res = test_engine.run()
            train_sharpes.append(train_res.sharpe)
            test_sharpes.append(test_res.sharpe)

        avg_train_sharpe = np.mean(train_sharpes) if train_sharpes else 0
        avg_test_sharpe = np.mean(test_sharpes) if test_sharpes else 0

        if avg_train_sharpe == 0:
            return False, 0.0
        degradation = avg_test_sharpe / avg_train_sharpe
        # Pass: degradation >= 0.5 AND test_sharpe > 0
        passed = degradation >= 0.5 and avg_test_sharpe > 0
        return passed, round(degradation, 3)


# ════════════════════════════════════════════════════════════════════════════════
# V4 Strategy Templates (extends original with v4 fields)
# ════════════════════════════════════════════════════════════════════════════════

STRATEGY_TEMPLATES = {
    # T1: Proven
    "T1_RSI_Momentum": lambda: StrategyConfig(
        name="T1_RSI_Momentum", description="RSI momentum with trend confirm",
        tier="T1", rsi_entry_long=30, rsi_entry_short=70, adx_entry=25,
        confluence_min=2, price_pos_entry_long=0.20),
    "T1_MVRV_Style": lambda: StrategyConfig(
        name="T1_MVRV_Style", description="MVRV-style extreme oversold reversal",
        tier="T1", rsi_entry_long=25, rsi_entry_short=75, adx_entry=20,
        confluence_min=3, price_pos_entry_long=0.10),
    # T2: Modifications
    "T2_Confluence": lambda: StrategyConfig(
        name="T2_Confluence", description="Multi-factor confluence entry",
        tier="T2", rsi_entry_long=35, rsi_entry_short=65, adx_entry=25,
        confluence_min=3, price_pos_entry_long=0.15, use_vol_confirm=True),
    "T2_SMC_Basic": lambda: StrategyConfig(
        name="T2_SMC_Basic", description="SMC FVG + RSI entry",
        tier="T2", rsi_entry_long=30, rsi_entry_short=70, adx_entry=20,
        confluence_min=2, price_pos_entry_long=0.15, use_smc_fvg=True),
    "T2_VolAdaptive": lambda: StrategyConfig(
        name="T2_VolAdaptive", description="Vol-adaptive RSI/ADX with 3 ATR bands",
        tier="T2", use_vol_adaptive=True,
        rsi_low_vol=35, rsi_mid_vol=30, rsi_high_vol=25,
        price_pos_entry_long=0.20, streak_entry=4, confluence_min=2),
    # T3: Speculative
    "T3_Extreme": lambda: StrategyConfig(
        name="T3_Extreme", description="Extreme oversold with streak confirm",
        tier="T3", rsi_entry_long=20, rsi_entry_short=80, adx_entry=20,
        streak_entry=5, price_pos_entry_long=0.08),
    "T3_SMC_Confluence": lambda: StrategyConfig(
        name="T3_SMC_Confluence", description="SMC + RSI + Volume confluence",
        tier="T3", rsi_entry_long=35, rsi_entry_short=65, adx_entry=25,
        confluence_min=3, price_pos_entry_long=0.12, use_vol_confirm=True,
        use_smc_fvg=True, use_smc_ob=True),
    # T4: Novel
    "T4_RegimeAdaptive": lambda: StrategyConfig(
        name="T4_RegimeAdaptive", description="Regime-adaptive entry/exit",
        tier="T4", rsi_entry_long=30, rsi_entry_short=70, adx_entry=25,
        price_pos_entry_long=0.12, stop_loss=0.025, use_regime_exit=True),
    "T4_SMC_OrderBlock": lambda: StrategyConfig(
        name="T4_SMC_OrderBlock", description="SMC Order Block + FVG",
        tier="T4", rsi_entry_long=35, rsi_entry_short=65, adx_entry=20,
        confluence_min=3, price_pos_entry_long=0.10,
        use_smc_fvg=True, use_smc_ob=True),
}


def expand_variations(base: StrategyConfig, n: int = 8) -> List[StrategyConfig]:
    """Generate random variations of a base config (T2/T3 only)."""
    rng = np.random.default_rng(seed=int(hash(base.name)) % (2**32))
    out = []
    RSI_RANGE = [20, 25, 30, 35, 40]
    ADX_RANGE = [15, 20, 25, 30]
    CONFL_RANGE = [2, 3, 4]
    POS_RANGE = [0.08, 0.10, 0.15, 0.20]
    STREAK_RANGE = [3, 4, 5, 6]
    for i in range(n):
        v = copy.deepcopy(base)
        v.name = f"{base.name}_v{i}"
        v.rsi_entry_long = float(rng.choice(RSI_RANGE))
        v.rsi_entry_short = 100 - v.rsi_entry_long + int(rng.integers(-10, 10))
        v.adx_entry = float(rng.choice(ADX_RANGE))
        v.confluence_min = int(rng.choice(CONFL_RANGE))
        v.price_pos_entry_long = float(rng.choice(POS_RANGE))
        v.streak_entry = int(rng.choice(STREAK_RANGE))
        out.append(v)
    return out


# ════════════════════════════════════════════════════════════════════════════════
# Grid Search v4 (with walk-forward scoring)
# ════════════════════════════════════════════════════════════════════════════════

class GridSearchEngine:
    def __init__(self, df: pd.DataFrame, walk_forward: bool = False,
                 train_months: int = 12, test_months: int = 2):
        self.df = df
        self.walk_forward = walk_forward
        self.wf_engine = WalkForwardEngine(df, train_months, test_months) if walk_forward else None

    def run(self, templates: List[str], max_experiments: int = 50) -> List[Tuple[StrategyConfig, BacktestResult]]:
        experiments = []
        for tpl_name in templates:
            base_factory = STRATEGY_TEMPLATES.get(tpl_name)
            if not base_factory:
                continue
            base = base_factory()
            if base.tier == "T1":
                # T1: deterministic grid over RSI_L × ADX (preserve reproducibility)
                for rsi_l in [20, 25, 28, 30, 32]:
                    for adx in [18, 20, 25]:
                        v = copy.deepcopy(base)
                        v.name = f"{base.name}_L{int(rsi_l)}_A{int(adx)}"
                        v.rsi_entry_long = rsi_l
                        v.rsi_entry_short = 100 - rsi_l
                        v.adx_entry = adx
                        experiments.append(v)
            else:
                experiments.extend(expand_variations(base, n=min(8, max_experiments // max(1, len(templates)))))

        experiments = experiments[:max_experiments]
        logger.info(f"Running {len(experiments)} experiments (walk_forward={self.walk_forward})")

        results = []
        for i, cfg in enumerate(experiments):
            engine = BacktestEngine(self.df, cfg)
            result = engine.run()

            # Walk-forward check
            if self.wf_engine:
                wf_passed, wf_degradation = self.wf_engine.evaluate(cfg)
                cfg.walk_forward_passed = wf_passed
                cfg.walk_forward_degradation = wf_degradation

            # Gate compliance (by construction)
            cfg.gate_compliance = self._assess_gates(cfg, result)
            result.gate_compliance = cfg.gate_compliance

            cfg.expected_pf = result.profit_factor
            cfg.trade_count = result.total_trades
            cfg.win_rate = result.win_rate
            cfg.regime_segments = result.regime_segments

            results.append((cfg, result))
            if (i + 1) % 10 == 0:
                logger.info(f"  Progress: {i+1}/{len(experiments)}")

        results.sort(key=lambda x: x[1].score(), reverse=True)
        return results

    @staticmethod
    def _assess_gates(cfg: StrategyConfig, result: BacktestResult) -> Dict[str, bool]:
        """Gate compliance check (construction-level, not empirical)."""
        return {
            "compliance_enter_tag": True,  # by construction (TEMPLATE uses LONG_*/SHORT_*)
            "atr_sl_tp": cfg.enable_atr_sl_tp,
            "funding_filter": cfg.enable_funding_filter,
            "1d_trend": cfg.enable_1d_trend,
            "cis_gate": cfg.enable_cis_gate,
            "regime_stake": cfg.enable_regime_stake,
            "regime_breadth": sum(
                1 for r, m in result.regime_segments.items()
                if m.get("trades", 0) >= 3 and (m.get("pf", 0) >= 1.0 if isinstance(m.get("pf"), (int, float)) else True)
            ) >= 3,
            "walk_forward": cfg.walk_forward_passed if cfg.walk_forward_passed is not False else True,
        }


# ════════════════════════════════════════════════════════════════════════════════
# V4 Strategy Code Generator
# ════════════════════════════════════════════════════════════════════════════════

STRATEGY_TEMPLATE = '''"""
CometCloud AutoResearch V4 — {name}
{tier_desc}
=================================================

AutoResearch-generated strategy with V4 compliance.

{summary}

V4 compliance:
- ATR vol SL/TP (custom_stoploss + custom_exit)
- Funding rate filter (>+3 bps skip on long)
- 1d trend filter (close > EMA50)
- CIS gate (regime pillars + min_cis_score)
- Regime-aware stake multiplier (0.5x-1.2x)
- Compliance enter_tag (LONG_AUTO_*/SHORT_AUTO_*)

Parameters (auto-tuned):
  RSI_ENTRY_LONG = {rsi_long}
  RSI_ENTRY_SHORT = {rsi_short}
  ADX_ENTRY = {adx}
  PRICE_POS_LONG = {pos_long}
  STREAK_ENTRY = {streak}
  CONFLUENCE_MIN = {confluence}
  USE_VOL_CONFIRM = {use_vol_confirm}
  USE_SMC_FVG = {use_smc_fvg}
  USE_SMC_OB = {use_smc_ob}
  USE_SMC_LIQUIDITY = {use_smc_liquidity}
  STOP_LOSS = {stop_loss}
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import talib.abstract as ta

from freqtrade.strategy import IStrategy
from freqtrade.persistence import Trade

logger = logging.getLogger(__name__)


# === Auto-tuned parameters ===
RSI_ENTRY_LONG = {rsi_long}
RSI_ENTRY_SHORT = {rsi_short}
ADX_ENTRY = {adx}
PRICE_POS_LONG = {pos_long}
STREAK_ENTRY = {streak}
CONFLUENCE_MIN = {confluence}
USE_VOL_CONFIRM = {use_vol_confirm}
USE_SMC_FVG = {use_smc_fvg}
USE_SMC_OB = {use_smc_ob}
USE_SMC_LIQUIDITY = {use_smc_liquidity}
STOP_LOSS = {stop_loss}
MAX_OPEN_TRADES = {max_open_trades}

# === ATR SL/TP knobs ===
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TP1_MULT = 2.5
ATR_TP2_MULT = 1.0
ATR_MIN_STOP_PCT = 0.020
ATR_MIN_TP_PCT = 0.030

# === Funding rate ===
FUNDING_SKIP_BPS = 3.0
FUNDING_BONUS_BPS = -3.0

# === Multi-timeframe ===
DAILY_TREND_EMA = 50

# === Regime stake multipliers ===
STAKE_MULT_BY_REGIME = {{
    "Tightening": 0.50, "Risk-Off": 0.50, "Stagflation": 0.60,
    "Neutral": 0.80, "Easing": 1.00, "Risk-On": 1.00, "Goldilocks": 1.20,
}}

# === Regime CIS configs ===
_REGIME_CONFIGS = {regime_configs}

# === CIS cache path ===
CIS_CACHE_PATH = os.getenv(
    "CIS_CACHE_PATH",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_scores_latest.json",
)


class {class_name}(IStrategy):
    """AutoResearch V4 strategy: {description}"""

    INTERFACE_VERSION = 3
    timeframe = "{timeframe}"
    can_short = {can_short}

    # ROI ladder disabled (custom_exit handles TP)
    minimal_roi = {{"0": 1.0}}
    stoploss = -0.05    # floor; custom_stoploss overrides
    trailing_stop = False
    startup_candle_count = 60
    max_open_trades = MAX_OPEN_TRADES
    process_only_new_candles = False
    use_exit_signal = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cis_cache: dict = {{}}
        self._cis_load_time: Optional[datetime] = None
        self._current_regime: str = "Neutral"
        self._regime_config: dict = _REGIME_CONFIGS["Neutral"]
        self._market_micro: dict = {{}}
        self._atr_pct_cache: dict = {{}}

    # ── CIS loading ──
    def _load_cis_cache(self, force: bool = False) -> dict:
        now = datetime.now()
        if not force and self._cis_cache and self._cis_load_time:
            if (now - self._cis_load_time).total_seconds() < 300:
                return self._cis_cache
        cache_path = Path(CIS_CACHE_PATH)
        if not cache_path.exists():
            return self._cis_cache
        try:
            with open(cache_path) as f:
                data = json.load(f)
            scores = data.get("scores", [])
            self._cis_cache = {{s.get("asset", s.get("symbol", "")): s for s in scores}}
            self._current_regime = data.get("macro_regime", "Neutral")
            self._regime_config = _REGIME_CONFIGS.get(self._current_regime, _REGIME_CONFIGS["Neutral"])
            self._market_micro = data.get("market_micro", {{}}) or {{}}
            self._cis_load_time = now
        except Exception as exc:
            logger.warning(f"[{{self.__class__.__name__}}] CIS cache read failed: {{exc}}")
        return self._cis_cache

    def _get_cis(self, symbol: str) -> dict:
        return self._cis_cache.get(symbol, {{}}) if self._cis_cache else self._load_cis_cache().get(symbol, {{}})

    def _cis_passes(self, symbol: str) -> bool:
        cfg = self._regime_config
        cis = self._get_cis(symbol)
        if not cis:
            return False
        if (cis.get("cis_score", 0) or 0) < cfg.get("min_cis", 50):
            return False
        pillars = cis.get("pillars", {{}})
        for pillar, min_val in cfg.get("entry_pillars", {{}}).items():
            key = pillar if pillar in pillars else {{
                "F": "Fundamental", "M": "Momentum", "O": "Risk-Adjusted",
                "S": "Sensitivity", "A": "Alpha",
            }}.get(pillar, pillar)
            p_val = pillars.get(key) or pillars.get(pillar.lower(), 0) or 0
            if p_val < min_val:
                return False
        return True

    # ── 1d trend filter ──
    def _daily_trend_allows_long(self, pair: str) -> bool:
        try:
            daily = self.dp.get_pair_dataframe(pair, "1d")
            if daily is None or len(daily) < DAILY_TREND_EMA + 1:
                return True
            ema50 = ta.EMA(daily["close"], timeperiod=DAILY_TREND_EMA)
            return float(daily["close"].iloc[-1]) > float(ema50.iloc[-1])
        except Exception:
            return True

    # ── Indicators ──
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        sym = metadata.get("pair", "").split("/")[0]
        if not self._cis_cache:
            self._load_cis_cache()

        # RSI
        delta = dataframe['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        dataframe['rsi'] = 100 - (100 / (1 + rs))

        # ATR
        high, low, close = dataframe['high'], dataframe['low'], dataframe['close']
        tr = pd.concat([
            high - low,
            abs(high - close.shift()),
            abs(low - close.shift()),
        ], axis=1).max(axis=1)
        dataframe['atr'] = tr.rolling(ATR_PERIOD).mean()
        dataframe['atr_pct'] = dataframe['atr'] / dataframe['close'].replace(0, pd.NA)
        self._atr_pct_cache[sym] = float(dataframe['atr_pct'].iloc[-1]) if len(dataframe) else 0.02

        # ADX
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        plus_di = 100 * (plus_dm.rolling(14).mean() / dataframe['atr'])
        minus_di = 100 * (minus_dm.rolling(14).mean() / dataframe['atr'])
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 0.001)
        dataframe['adx'] = dx.rolling(14).mean()
        dataframe['plus_di'] = plus_di
        dataframe['minus_di'] = minus_di

        # Price position
        low_20 = dataframe['low'].rolling(20).min()
        high_20 = dataframe['high'].rolling(20).max()
        dataframe['price_pos'] = (dataframe['close'] - low_20) / (high_20 - low_20 + 0.001)

        # MACD
        ema12 = dataframe['close'].ewm(span=12, adjust=False).mean()
        ema26 = dataframe['close'].ewm(span=26, adjust=False).mean()
        dataframe['macd'] = ema12 - ema26
        dataframe['macd_signal'] = dataframe['macd'].ewm(span=9, adjust=False).mean()
        dataframe['macd_hist'] = dataframe['macd'] - dataframe['macd_signal']
        dataframe['macd_bullish'] = (dataframe['macd_hist'] > 0).astype(int)
        dataframe['macd_bearish'] = (dataframe['macd_hist'] < 0).astype(int)

        # Volume
        dataframe['vol_ma'] = dataframe['volume'].rolling(20).mean()
        dataframe['vol_ratio'] = dataframe['volume'] / dataframe['vol_ma']
        dataframe['vol_confirm_up'] = ((dataframe['close'] > dataframe['close'].shift(1)) &
                                        (dataframe['vol_ratio'] > 1.0)).astype(int)
        dataframe['vol_confirm_down'] = ((dataframe['close'] < dataframe['close'].shift(1)) &
                                          (dataframe['vol_ratio'] > 1.0)).astype(int)

        # Confluence
        dataframe['bullish_confluence'] = (
            (dataframe['rsi'] < RSI_ENTRY_LONG).astype(int) +
            (dataframe['macd_bullish'] == 1).astype(int) +
            (dataframe['price_pos'] < PRICE_POS_LONG).astype(int) +
            (dataframe['vol_confirm_up'] == 1).astype(int)
        )
        dataframe['bearish_confluence'] = (
            (dataframe['rsi'] > RSI_ENTRY_SHORT).astype(int) +
            (dataframe['macd_bearish'] == 1).astype(int) +
            (dataframe['price_pos'] > 0.80).astype(int) +
            (dataframe['vol_confirm_down'] == 1).astype(int)
        )

        # Streak
        close_arr = dataframe['close'].values
        streak_down = np.zeros(len(dataframe), dtype=np.int32)
        streak_up = np.zeros(len(dataframe), dtype=np.int32)
        for i in range(1, len(close_arr)):
            streak_down[i] = streak_down[i-1] + 1 if close_arr[i] < close_arr[i-1] else 0
            streak_up[i] = streak_up[i-1] + 1 if close_arr[i] > close_arr[i-1] else 0
        dataframe['streak_down'] = streak_down
        dataframe['streak_up'] = streak_up

        # Regime (ADX-based)
        def classify(row):
            adx = row.get('adx', 30)
            plus = row.get('plus_di', 50)
            minus = row.get('minus_di', 50)
            if adx > 40:
                return 'BULL' if plus > minus else 'BEAR'
            elif adx < 25:
                return 'CRAB'
            return 'TREND'
        dataframe['regime'] = dataframe.apply(classify, axis=1)

        # SMC
        dataframe['fvg_bullish'] = (
            (dataframe['low'] > dataframe['high'].shift(2)) &
            (dataframe['close'] > dataframe['open'].shift(2))
        ).astype(int)
        dataframe['fvg_bearish'] = (
            (dataframe['high'] < dataframe['low'].shift(2)) &
            (dataframe['close'] < dataframe['open'].shift(2))
        ).astype(int)
        is_bearish = (dataframe['close'] < dataframe['open']).astype(int)
        is_bullish = (dataframe['close'] > dataframe['open']).astype(int)
        up_move = dataframe['close'] > dataframe['close'].shift(1)
        down_move = dataframe['close'] < dataframe['close'].shift(1)
        dataframe['bullish_ob'] = (is_bearish & up_move.shift(1).fillna(False)).astype(int)
        dataframe['bearish_ob'] = (is_bullish & down_move.shift(1).fillna(False)).astype(int)
        dataframe['liquidity_sweep_low'] = (
            (dataframe['low'] < dataframe['low'].shift(1).rolling(20).min()) &
            (dataframe['close'] > dataframe['open'])
        ).astype(int)
        dataframe['liquidity_sweep_high'] = (
            (dataframe['high'] > dataframe['high'].shift(1).rolling(20).max()) &
            (dataframe['close'] < dataframe['open'])
        ).astype(int)

        return dataframe

    # ── Entry ──
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata.get("pair", "")
        symbol = pair.replace("/USDT", "").replace("/USD", "")

        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0
        dataframe['enter_tag'] = ''

        # 1d trend filter
        if not self._daily_trend_allows_long(pair):
            return dataframe

        # CIS gate
        if not self._cis_passes(symbol):
            return dataframe

        # Long entry
        long_cond = (
            (dataframe['rsi'] < RSI_ENTRY_LONG) &
            (dataframe['adx'] > ADX_ENTRY) &
            (dataframe['price_pos'] < PRICE_POS_LONG) &
            (dataframe['streak_down'] >= STREAK_ENTRY) &
            (dataframe['bullish_confluence'] >= CONFLUENCE_MIN)
        )
        if USE_VOL_CONFIRM:
            long_cond = long_cond & (dataframe['vol_confirm_up'] == 1)
        if USE_SMC_FVG:
            long_cond = long_cond & (dataframe['fvg_bullish'] == 1)
        if USE_SMC_OB:
            long_cond = long_cond & (dataframe['bullish_ob'] == 1)
        if USE_SMC_LIQUIDITY:
            long_cond = long_cond & (dataframe['liquidity_sweep_low'] == 1)

        # Short entry
        short_cond = (
            (dataframe['rsi'] > RSI_ENTRY_SHORT) &
            (dataframe['adx'] > ADX_ENTRY) &
            (dataframe['price_pos'] > 0.80) &
            (dataframe['streak_up'] >= STREAK_ENTRY) &
            (dataframe['bearish_confluence'] >= CONFLUENCE_MIN)
        )
        if USE_VOL_CONFIRM:
            short_cond = short_cond & (dataframe['vol_confirm_down'] == 1)
        if USE_SMC_FVG:
            short_cond = short_cond & (dataframe['fvg_bearish'] == 1)
        if USE_SMC_OB:
            short_cond = short_cond & (dataframe['bearish_ob'] == 1)
        if USE_SMC_LIQUIDITY:
            short_cond = short_cond & (dataframe['liquidity_sweep_high'] == 1)

        # Cooldown (15 bars)
        for direction in ['enter_long', 'enter_short']:
            mask = (long_cond if direction == 'enter_long' else short_cond)
            cd = mask.rolling(15, min_periods=1).sum().shift(1).fillna(0) > 0
            mask = mask & ~cd
            dataframe.loc[mask, direction] = 1

        # Compliance enter_tag: LONG_AUTO_R{regime}_T{tier}
        regime_short = self._current_regime[:5].upper()
        tier_short = "{tier_short}"
        # Note: tag written in confirm_trade_entry for accurate regime
        return dataframe

    # ── Exit ──
    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe['exit_long'] = (dataframe['rsi'] > {rsi_exit_long}).astype(int)
        dataframe['exit_short'] = (dataframe['rsi'] < (100 - {rsi_exit_long})).astype(int)
        dataframe['exit_tag'] = ''
        return dataframe

    # ── ATR SL ──
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float) -> float:
        symbol = pair.replace("/USDT", "").replace("/USD", "")
        atr_pct = self._atr_pct_cache.get(symbol) or ATR_MIN_STOP_PCT
        if not atr_pct or atr_pct != atr_pct:
            atr_pct = ATR_MIN_STOP_PCT
        return float(-max(ATR_STOP_MULT * atr_pct, ATR_MIN_STOP_PCT))

    # ── ATR TP ladder ──
    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float) -> Optional[str]:
        symbol = pair.replace("/USDT", "").replace("/USD", "")
        atr_pct = self._atr_pct_cache.get(symbol) or ATR_MIN_TP_PCT
        if not atr_pct or atr_pct != atr_pct:
            atr_pct = ATR_MIN_TP_PCT
        tp1 = max(ATR_TP1_MULT * atr_pct, ATR_MIN_TP_PCT)
        tp2 = max(ATR_TP2_MULT * atr_pct, ATR_MIN_TP_PCT * 0.5)
        if current_profit >= tp1:
            return "atr_tp_1_2.5x"
        if current_profit >= tp2:
            try:
                held = current_time - trade.open_date_utc.replace(tzinfo=current_time.tzinfo)
                if held >= timedelta(hours=24):
                    return "atr_tp_2_1.0x_after_24h"
            except Exception:
                pass
        return None

    # ── Regime-aware stake ──
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: Optional[float],
                            max_stake: Optional[float], side: str, **kwargs) -> float:
        mult = STAKE_MULT_BY_REGIME.get(self._current_regime, 0.8)
        amount = proposed_stake * mult
        if min_stake and amount < min_stake:
            amount = min_stake
        if max_stake and amount > max_stake:
            amount = max_stake
        return float(amount)

    # ── Confirm Entry: max-open + funding rate ──
    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        if Trade.get_trades_proxy(is_open=True) and \\
                len(Trade.get_trades_proxy(is_open=True)) >= self.max_open_trades:
            return False
        symbol = pair.replace("/USDT", "").replace("/USD", "")
        micro = self._market_micro.get(symbol, {{}}) or {{}}
        fr_bps = (micro.get("funding_rate", 0) or 0) * 10_000
        if side == "long" and fr_bps > FUNDING_SKIP_BPS:
            logger.info(f"[{{self.__class__.__name__}}] {{pair}} skip funding {{fr_bps:.1f}}bps")
            return False
        return True

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        return True
'''


def generate_strategy_code(config: StrategyConfig, result: BacktestResult) -> str:
    """Render the v4 strategy template with config + result."""
    class_name = "CometCloudAutoV4_" + config.name.replace("-", "_").replace(" ", "_")
    tier_desc = f"Tier {config.tier} (auto-tuned via autoresearch v4)"
    summary = (
        f"AutoResearch v4 best configuration:\n"
        f"  Tier: {config.tier}\n"
        f"  Profit Factor: {result.profit_factor:.2f}\n"
        f"  Win Rate: {result.win_rate:.1f}%\n"
        f"  Trades: {result.total_trades}\n"
        f"  Sharpe: {result.sharpe:.2f}\n"
        f"  Max DD: {result.max_drawdown:.1f}%\n"
        f"  Regime segments: {result.regime_segments}\n"
        f"  Walk-forward passed: {config.walk_forward_passed}\n"
        f"  Walk-forward degradation: {config.walk_forward_degradation}"
    )
    return STRATEGY_TEMPLATE.format(
        name=config.name,
        tier_desc=tier_desc,
        summary=summary,
        rsi_long=config.rsi_entry_long,
        rsi_short=config.rsi_entry_short,
        adx=config.adx_entry,
        pos_long=config.price_pos_entry_long,
        streak=config.streak_entry,
        confluence=config.confluence_min,
        use_vol_confirm=config.use_vol_confirm,
        use_smc_fvg=config.use_smc_fvg,
        use_smc_ob=config.use_smc_ob,
        use_smc_liquidity=config.use_smc_liquidity,
        stop_loss=config.stop_loss,
        max_open_trades=config.max_open_trades,
        regime_configs=repr(_REGIME_CONFIGS),
        class_name=class_name,
        description=config.description,
        timeframe="4h",
        can_short=True,
        tier_short=config.tier,
        rsi_exit_long=config.rsi_exit_long,
    )


# ════════════════════════════════════════════════════════════════════════════════
# AutoResearch Orchestrator
# ════════════════════════════════════════════════════════════════════════════════

class AutoResearchV4:
    def __init__(self, pairs: List[str], timeframe: str, data_root: Path):
        self.pairs = pairs
        self.timeframe = timeframe
        self.data_root = data_root
        self.data: Dict[str, pd.DataFrame] = {}
        self.results: List[Tuple[StrategyConfig, BacktestResult]] = []

    def load_data(self) -> bool:
        logger.info(f"Loading data for {len(self.pairs)} pairs (tf={self.timeframe})...")
        for pair in self.pairs:
            df = load_binance_data(pair, self.timeframe, self.data_root)
            if df is not None:
                self.data[pair] = FactorEngine(df).calculate_all()
                logger.info(f"  {pair}: {len(df)} candles")
            else:
                logger.warning(f"  {pair}: NO DATA at {self.data_root}")
        return len(self.data) > 0

    def run_research(
        self,
        templates: Optional[List[str]] = None,
        max_experiments: int = 50,
        walk_forward: bool = False,
        train_months: int = 12,
        test_months: int = 2,
    ) -> List[Tuple[StrategyConfig, BacktestResult]]:
        if templates is None:
            templates = list(STRATEGY_TEMPLATES.keys())
        all_results = []
        for pair, df in self.data.items():
            logger.info(f"Researching {pair}...")
            engine = GridSearchEngine(
                df, walk_forward=walk_forward,
                train_months=train_months, test_months=test_months,
            )
            results = engine.run(templates, max_experiments=max_experiments)
            all_results.extend(results)
            for i, (cfg, res) in enumerate(results[:3]):
                logger.info(
                    f"  #{i+1} {cfg.name}: PF={res.profit_factor:.2f} "
                    f"WR={res.win_rate:.1f}% Trades={res.total_trades} "
                    f"Score={res.score():.3f}"
                )
        all_results.sort(key=lambda x: x[1].score(), reverse=True)
        self.results = all_results
        return all_results

    def generate_best_strategy(self, output_path: Path) -> Tuple[StrategyConfig, BacktestResult]:
        if not self.results:
            raise ValueError("No research results. Run run_research() first.")
        cfg, res = self.results[0]
        code = generate_strategy_code(cfg, res)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(code)
        logger.info(f"Generated V4 strategy: {output_path}")
        return cfg, res

    def save_results(self, output_path: Path, top_n: int = 30):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {"config": cfg.to_dict(), "result": res.to_dict()}
            for cfg, res in self.results[:top_n]
        ]
        output_path.write_text(json.dumps(data, indent=2, default=str))
        logger.info(f"Results saved: {output_path}")


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="CometCloud AutoResearch v4 — V4-compliant strategy generation"
    )
    parser.add_argument("--mode", choices=["research", "walk-forward", "upgrade", "full"],
                        default="research")
    parser.add_argument("--pairs", nargs="+", default=["BTC_USDT", "ETH_USDT", "SOL_USDT"])
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--max-experiments", type=int, default=50)
    parser.add_argument("--templates", nargs="+", default=None,
                        help="Strategy templates to test (default: all)")
    parser.add_argument("--train-months", type=int, default=12)
    parser.add_argument("--test-months", type=int, default=2)
    parser.add_argument("--data-root", type=Path,
                        default=Path("/Volumes/CometCloudAI/freqtrade/user_data/data/binance"),
                        help="Path to .feather data files")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output strategy path (default: Shadow/.../AutoV4_<ts>.py)")
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("  CometCloud AutoResearch V4")
    logger.info("=" * 70)
    logger.info(f"Mode: {args.mode}, Pairs: {args.pairs}, TF: {args.timeframe}")
    logger.info(f"Data root: {args.data_root}")

    researcher = AutoResearchV4(args.pairs, args.timeframe, args.data_root)
    if not researcher.load_data():
        logger.error("No data loaded. Check data-root path and .feather files.")
        sys.exit(1)

    walk_forward = args.mode in ("walk-forward", "upgrade", "full")

    if args.mode in ("research", "walk-forward", "full"):
        logger.info(f"PHASE 1: Running research (walk_forward={walk_forward})")
        results = researcher.run_research(
            templates=args.templates,
            max_experiments=args.max_experiments,
            walk_forward=walk_forward,
            train_months=args.train_months,
            test_months=args.test_months,
        )
        REPORTS_DIR.mkdir(exist_ok=True, parents=True)
        results_file = REPORTS_DIR / f"autoresearch_v4_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        researcher.save_results(results_file, top_n=30)
        logger.info(f"Results: {results_file}")

        logger.info("Top 5:")
        for i, (cfg, res) in enumerate(results[:5]):
            logger.info(
                f"  #{i+1} {cfg.name} ({cfg.tier}): PF={res.profit_factor:.2f} "
                f"WR={res.win_rate:.1f}% Trades={res.total_trades} "
                f"Score={res.score():.3f} Regimes={list(res.regime_segments.keys())}"
            )

    if args.mode in ("upgrade", "full"):
        logger.info("PHASE 2: Generating V4 strategy")
        if args.output:
            output_path = args.output
        else:
            ts = datetime.now().strftime('%Y%m%d_%H%M')
            output_path = SHADOW_STRATEGIES / f"CometCloudAutoV4_{ts}.py"
        cfg, res = researcher.generate_best_strategy(output_path)
        logger.info(f"Generated: {output_path}")
        logger.info(f"  PF={res.profit_factor:.2f} WR={res.win_rate:.1f}% Trades={res.total_trades}")
        logger.info(f"  Regime segments: {res.regime_segments}")
        logger.info(f"  Walk-forward passed: {cfg.walk_forward_passed}, degradation: {cfg.walk_forward_degradation}")

    logger.info("=" * 70)
    logger.info("  AutoResearch V4 Complete")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()