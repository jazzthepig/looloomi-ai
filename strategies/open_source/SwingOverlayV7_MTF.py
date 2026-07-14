"""
SwingOverlayV7_MTF — Multi-Timeframe swing sleeve (V7).
========================================================

The V6 swing bled -9.66% on longs because 4h MACD cross alone is too weak as
a directional filter. V7 adds a HARD 4h direction-bias gate to 15min RSI-pullback
entries — "buy the dip in an uptrend, short the rally in a downtrend".

Architecture:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  4h (HTF direction bias) — computed once per pair from feather cache    │
  │    MACD(12,26,9) cross + ADX≥15 + close vs EMA55                       │
  │    → _dir ∈ {-1, 0, +1}                                                │
  └─────────────────────────────────────────────────────────────────────────┘
                              ↓ forward-filled into 15min index
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  15min (LTF entry timing) — per-row vectorised                         │
  │    LONG entry:  _dir_4h == +1 AND RSI crosses below 35                 │
  │                  AND volume > 1.0× 20-volMA                             │
  │    SHORT entry: _dir_4h == -1 AND RSI crosses above 65                 │
  │                  AND volume > 1.0× 20-volMA                             │
  └─────────────────────────────────────────────────────────────────────────┘

Exit:
  - 15min RSI mean reversion (≥55 long, ≤45 short)
  - 4h direction flip (long exits if bias drops from +1 to 0/-1)
  - 1.5×ATR SL / 2.5×ATR TP

Why MTF?
  - V6: 160 trades 4h, shorts +4.48%, longs -9.66%
  - Long bleeds because MACD bullish cross at 4h ≠ bullish regime
  - V7: hard gate — only trade WITHIN established 4h direction

In live: deploy alongside CoreBasketV6 (60%) + SwingOverlayV7 (30%) + 10% cash.

Compliance: positioning language only. No BUY/SELL/ACCUMULATE/AVOID.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import talib.abstract as ta

from freqtrade.strategy import IStrategy
from freqtrade.persistence import Trade

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

CIS_CACHE_PATH = os.getenv(
    "CIS_CACHE_PATH",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_scores_latest.json",
)
CIS_HISTORY_DIR = os.getenv(
    "CIS_HISTORY_DIR",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
)
# 4h feather cache (read-only — same source V6 swing uses)
HTF_DATA_DIR = os.getenv(
    "HTF_DATA_DIR",
    "/Users/sbb/Projects/looloomi-ai/Shadow/freqtrade/user_data/data/binance/futures/",
)

UNIVERSE = ("BTC", "ETH", "SOL", "BNB", "XRP")

# ── HTF (4h) parameters ────────────────────────────────────────────────────

HTF_TIMEFRAME = "4h"
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ADX_PERIOD = 14
ADX_THRESHOLD = 15
EMA_TREND = 55

# ── LTF (15min) entry parameters ────────────────────────────────────────────

RSI_PERIOD = 14
RSI_LONG_ENTRY = 35   # cross below → oversold pullback
RSI_SHORT_ENTRY = 65  # cross above → overbought rally
RSI_LONG_EXIT = 55
RSI_SHORT_EXIT = 45
VOL_MA_PERIOD = 20
VOL_MULT_MIN = 1.0   # require volume > 1.0× 20-MA

# ── Risk ─────────────────────────────────────────────────────────────────────

ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TP1_MULT = 2.5
ATR_MIN_STOP_PCT = 0.015
ATR_MIN_TP_PCT = 0.025

FUNDING_BPS_SKIP_LONG = 3.0

# Max hold (in candles) — 15min × 96/day × 5 = 480 bars
MAX_HOLD_BARS = 480


class SwingOverlayV7_MTF(IStrategy):
    """MTF swing — 4h direction bias gates 15min RSI pullback entries."""

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = True

    minimal_roi = {"0": 1.0}
    stoploss = -0.05
    trailing_stop = False
    startup_candle_count = 100  # need enough 15min history for 20-volMA + EMA + ATR warmup
    max_open_trades = 5
    process_only_new_candles = False
    use_exit_signal = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cis_cache: dict = {}
        self._cis_load_time: Optional[datetime] = None
        self._atr_pct_cache: dict = {}
        # Per-pair 4h direction series, indexed by 4h date
        self._htf_dir_by_pair: dict = {}
        # Funding per symbol (latest snapshot)
        self._funding_by_symbol: dict = {}

    def _safe_pair_id(self, pair: str) -> str:
        """BTC/USDT:USDT → BTC_USDT_USDT (matches feather filename)."""
        return pair.replace("/", "_").replace(":", "_")

    def _load_cis_cache(self) -> None:
        now = datetime.now()
        if self._cis_cache and self._cis_load_time:
            age = (now - self._cis_load_time).total_seconds()
            if age < 300:
                return
        try:
            cache_path = Path(CIS_CACHE_PATH)
            if not cache_path.exists():
                return
            with open(cache_path) as f:
                data = json.load(f)
            scores = data.get("scores", [])
            for s in scores:
                sym = s.get("asset", s.get("symbol", ""))
                mm = s.get("market_micro") or {}
                fr = mm.get("funding_rate", 0) or 0
                self._funding_by_symbol[sym] = fr
            self._cis_load_time = now
        except Exception as exc:
            logger.warning(f"[V7MTF] CIS cache read failed: {exc}")

    # ── HTF direction loader (cached per pair) ──────────────────────────────
    def _load_htf_direction(self, pair: str) -> pd.Series:
        """Load 4h feather, compute direction series, return indexed by 4h datetime."""
        if pair in self._htf_dir_by_pair:
            return self._htf_dir_by_pair[pair]

        pair_safe = self._safe_pair_id(pair)
        htf_path = Path(HTF_DATA_DIR) / f"{pair_safe}-{HTF_TIMEFRAME}-futures.feather"
        if not htf_path.exists():
            logger.warning(f"[V7MTF] 4h feather missing for {pair}: {htf_path}")
            return pd.Series(dtype=float)

        try:
            htf = pd.read_feather(htf_path)
            htf["date"] = pd.to_datetime(htf["date"])
            htf = htf.set_index("date").sort_index()

            # Compute 4h indicators
            macd_df = ta.MACD(htf, fastperiod=MACD_FAST, slowperiod=MACD_SLOW, signalperiod=MACD_SIGNAL)
            htf["macd"] = macd_df["macd"]
            htf["macd_sig"] = macd_df["macdsignal"]
            htf["adx_14"] = ta.ADX(htf, timeperiod=ADX_PERIOD)
            htf["ema_55"] = ta.EMA(htf["close"], timeperiod=EMA_TREND)

            # Direction bias
            direction = pd.Series(0, index=htf.index, dtype=int)
            long_mask = (
                (htf["macd"] > htf["macd_sig"])
                & (htf["adx_14"] >= ADX_THRESHOLD)
                & (htf["close"] > htf["ema_55"])
            )
            short_mask = (
                (htf["macd"] < htf["macd_sig"])
                & (htf["adx_14"] >= ADX_THRESHOLD)
                & (htf["close"] < htf["ema_55"])
            )
            direction[long_mask] = 1
            direction[short_mask] = -1

            # Drop NaN window (first 55-60 bars before EMA warmup)
            direction = direction.dropna()

            # Floor to bar timestamp (already aligned, but ensure)
            direction.index = pd.to_datetime(direction.index)
            self._htf_dir_by_pair[pair] = direction
            n_long = int((direction == 1).sum())
            n_short = int((direction == -1).sum())
            n_neutral = int((direction == 0).sum())
            logger.info(
                f"[V7MTF] {pair}: 4h direction loaded "
                f"long={n_long} short={n_short} neutral={n_neutral} bars={len(direction)}"
            )
            return direction
        except Exception as exc:
            logger.warning(f"[V7MTF] 4h direction load failed for {pair}: {exc}")
            return pd.Series(dtype=float)

    # ── Indicators (per-row vectorised) ─────────────────────────────────────
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata.get("pair", "")
        symbol = pair.split("/")[0]

        self._load_cis_cache()

        # 1. Load 4h direction series for this pair and merge into 15min bars
        htf_dir = self._load_htf_direction(pair)
        if not htf_dir.empty and len(dataframe):
            # Reindex 4h direction to 15min timestamp series via ffill
            df_dates = pd.to_datetime(dataframe["date"])
            # Reindex using forward fill
            aligned = htf_dir.reindex(df_dates, method="ffill")
            # Where no 4h history yet (early 15min bars), set to 0
            aligned = aligned.fillna(0).astype(int)
            dataframe["_dir_4h"] = aligned.values

        # 2. 15min indicators
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=RSI_PERIOD)
        dataframe["vol_ma"] = ta.SMA(dataframe["volume"], timeperiod=VOL_MA_PERIOD)
        dataframe["vol_ok"] = dataframe["volume"] > (dataframe["vol_ma"] * VOL_MULT_MIN)

        # ATR (for SL/TP)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=ATR_PERIOD)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"].replace(0, pd.NA)
        if len(dataframe):
            sym = pair.split("/")[0]
            self._atr_pct_cache[sym] = float(dataframe["atr_pct"].dropna().iloc[-1]) if dataframe["atr_pct"].notna().any() else 0.02

        # 3. Per-row vectorised entry/exit signals
        if len(dataframe) > 1:
            rsi_prev = dataframe["rsi"].shift(1)
            dir_up = dataframe["_dir_4h"] == 1
            dir_dn = dataframe["_dir_4h"] == -1

            # LONG: 4h uptrend + 15min RSI crosses below 35 + volume
            dataframe["_long_entry"] = (
                dir_up
                & (rsi_prev >= RSI_LONG_ENTRY)
                & (dataframe["rsi"] < RSI_LONG_ENTRY)
                & dataframe["vol_ok"].fillna(False).astype(bool)
            )
            # SHORT: 4h downtrend + 15min RSI crosses above 65 + volume
            dataframe["_short_entry"] = (
                dir_dn
                & (rsi_prev <= RSI_SHORT_ENTRY)
                & (dataframe["rsi"] > RSI_SHORT_ENTRY)
                & dataframe["vol_ok"].fillna(False).astype(bool)
            )
            # 4h direction flip exits
            # (On a row where _dir_4h drops from +1 to 0, force exit longs)
            # Implemented as: exit if previous dir was 1 and current is NOT 1
            # We use a conservative trigger: exit if current _dir_4h != +1
            # when our entry was +1 (we don't track entry direction; instead use
            # an aggregate: if long bias disappears, exit)
            dir_changed_to_not_long = (
                (dataframe["_dir_4h"].shift(1) == 1) & (dataframe["_dir_4h"] != 1)
            )
            dir_changed_to_not_short = (
                (dataframe["_dir_4h"].shift(1) == -1) & (dataframe["_dir_4h"] != -1)
            )
            # Use them as aggregate "exit when bias flips"
            dataframe["_long_exit"] = (
                (dataframe["rsi"] >= RSI_LONG_EXIT) | dir_changed_to_not_long
            )
            dataframe["_short_exit"] = (
                (dataframe["rsi"] <= RSI_SHORT_EXIT) | dir_changed_to_not_short
            )

        return dataframe

    # ── Entry (vectorised per-row) ──────────────────────────────────────────
    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata.get("pair", "")
        symbol = pair.split("/")[0]

        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        if len(dataframe) <= 1 or symbol not in UNIVERSE:
            return dataframe
        if "_long_entry" not in dataframe.columns:
            return dataframe

        # Funding filter — skip crowded longs
        fr = self._funding_by_symbol.get(symbol, 0) or 0
        skip_long = fr * 10_000 > FUNDING_BPS_SKIP_LONG

        long_mask = dataframe["_long_entry"].fillna(False).astype(bool)
        if skip_long:
            long_mask = long_mask & False

        short_mask = dataframe["_short_entry"].fillna(False).astype(bool)

        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[short_mask, "enter_short"] = 1

        if long_mask.any():
            dataframe.loc[long_mask, "enter_tag"] = "MTF_LONG"
        if short_mask.any():
            dataframe.loc[short_mask, "enter_tag"] = "MTF_SHORT"

        return dataframe

    # ── Exit (vectorised per-row) ───────────────────────────────────────────
    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        pair = metadata.get("pair", "")
        symbol = pair.split("/")[0]

        if len(dataframe) <= 1 or symbol not in UNIVERSE:
            return dataframe
        if "_long_exit" not in dataframe.columns:
            return dataframe

        long_exit_mask = dataframe["_long_exit"].fillna(False).astype(bool)
        short_exit_mask = dataframe["_short_exit"].fillna(False).astype(bool)

        dataframe.loc[long_exit_mask, "exit_long"] = 1
        dataframe.loc[short_exit_mask, "exit_short"] = 1

        if "exit_tag" not in dataframe.columns:
            dataframe["exit_tag"] = ""
        dataframe.loc[long_exit_mask, "exit_tag"] = "MTF_EXIT_LONG"
        dataframe.loc[short_exit_mask, "exit_tag"] = "MTF_EXIT_SHORT"

        return dataframe

    # ── ATR-normalised stoploss / take-profit ───────────────────────────────
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float) -> float:
        symbol = pair.split("/")[0]
        atr_pct = self._atr_pct_cache.get(symbol) or ATR_MIN_STOP_PCT
        if not atr_pct or atr_pct != atr_pct:
            atr_pct = ATR_MIN_STOP_PCT
        return float(-max(ATR_STOP_MULT * atr_pct, ATR_MIN_STOP_PCT))

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float) -> Optional[str]:
        symbol = pair.split("/")[0]
        atr_pct = self._atr_pct_cache.get(symbol) or ATR_MIN_TP_PCT
        if not atr_pct or atr_pct != atr_pct:
            atr_pct = ATR_MIN_TP_PCT
        tp1 = max(ATR_TP1_MULT * atr_pct, ATR_MIN_TP_PCT)
        if current_profit >= tp1:
            return "atr_tp_2.5x"
        # Max hold: 5 days = 7200 minutes
        opened_at = trade.open_date_utc
        if opened_at:
            from datetime import timezone
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
            held_min = (current_time - opened_at).total_seconds() / 60
            if held_min >= 7200:
                return "max_hold_5d"
        return None

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        if Trade.get_trades_proxy(is_open=True) and \
                len(Trade.get_trades_proxy(is_open=True)) >= self.max_open_trades:
            return False
        return True

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        return True
