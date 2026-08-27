"""
CometCloud Nautilus Sleeve A — strategy (Seth, 2026-07-17)
==========================================================

Parity port of `freqtrade/user_data/strategies/CometCloudMultiFactorV2.py`
(the MVRV-mean-reversion Sleeve A per `PROFITABLE_STRATEGY_REPORT.md`) to
Nautilus Trader 1.229+.  Mirrors `ls_v1/strategy.py` structure but is
**simpler in every dimension** because Sleeve A is intentionally a
durable fundamental core with hard rules (vs LS v1's tactical
long-short with ATR/CIS/edge gates).

Targets:
  - 1h bars, BTC/ETH/SOL USDT-margined perpetuals
  - Long-only (can_short=False) — mirrors freqtrade
  - Hard -3% stop loss (no ATR bracket — Sleeve A is meant to give the
    cause-room for an MVRV-style mean reversion; no premature shake-out)
  - 3-dimension entry gate:
      1. trend    — EMA9 > EMA21 AND +DI > -DI AND ADX > 25
      2. extreme  — RSI < 30 OR streak_down >= 4
      3. momentum — volume_ratio > 1.5 OR price_position < 0.2
    (all 3 required — same as freqtrade `populate_entry_trend`)
  - Exit on RSI > 65 OR price_position > 75% (close position; relies
    primarily on the -3% stop + the rare tp-hit case)
  - MAX_OPEN_TRADES = 2 (per-pair via Nautilus portfolio)
  - MAX_DAILY_TRADES = 2 (tracked in-process via per-UTC-day counter)
  - 15-bar cooldown between entries on the same instrument
  - 3× leverage default (per PROFITABLE_STRATEGY_REPORT — backtest
    showed 77% WR and +119.5% annualized at 3× lev on 14mo window)

Parity target: `CometCloudMultiFactorV2` (Shadow/freqtrade).  Same 3
pairs, same 14mo OOS window (2025-01-01 → 2026-03-12).  Sleeve A is the
"durable fundamental core" of the surviving two-layer book per
MINIMAX_SYNC.md §STRATEGY-REVIVE; it MUST clear Minimax-C's C-S3
out-of-sample walk-forward gate before any "production" label lands.

Engines — Sleeve A has no CIS gate, no edge gate, no funding filter.
The strategy is intentionally NOT the tactical layer; it carries the
book through MVRV-style oversold bounces with hard risk.  Keep it
small, deterministic, easy to audit.

Compliance: signal labels use positioning language only (STRONG OUTPERFORM /
OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT) per CLAUDE.md.

Duck-type contract from `src/research/strategy_base.py` is implemented
via classmethods so the strategy can be introspected by tooling (the
strategy is intentionally NOT registered with the project strategy
registry — this lane is engine plumbing, see package docstring).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from nautilus_trader.common.enums import LogColor
from nautilus_trader.config import PositiveInt
from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators.average.true_range import AverageTrueRange
from nautilus_trader.indicators.directional_movement import DirectionalMovement
from nautilus_trader.indicators.exponential_moving_average import ExponentialMovingAverage
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


logger = logging.getLogger(__name__)


# ── Constants (mirror freqtrade CometCloudMultiFactorV2 exactly) ─────────────

# Technical gates
RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
ADX_PERIOD = 14
ADX_THRESHOLD = 25

# Extreme / momentum
STREAK_DOWN_THRESHOLD = 4          # consecutive down bars to count as "extreme"
RSI_OVERSOLD = 30                  # RSI floor for "extreme"
RSI_OVERBOUGHT = 65                # RSI ceiling for exit
VOLUME_RATIO_THRESHOLD = 1.5       # volume / volume_ma(20) for "momentum"
PRICE_POSITION_LOW = 0.2           # close vs (low_20, high_20) for "momentum"
PRICE_POSITION_HIGH = 0.75         # price_position for exit

# Lookback for indicators
LOOKBACK_20 = 20
LOOKBACK_VOLUME_MA = 20
COOLDOWN_BARS = 15                 # 15-bar entry cooldown (matches freqtrade)

# Risk knobs
HARD_STOP_PCT = 0.03               # -3% hard stop
LEVERAGE_DEFAULT = 3               # 3× leverage (PROFITABLE_STRATEGY_REPORT)

# Position caps (mirror freqtrade constants exactly)
MAX_OPEN_TRADES = 2
MAX_DAILY_TRADES = 2

# Path to 1h feather files (env-overridable for testing on Mac).
# Default from src.research.paths.SLEEVE_A_DATA_DIR (env-overridable via
# COMETCLOUD_SLEEVE_A_DATA_DIR). Local SLEEVE_A_FEATHER_DIR env still wins
# for per-run overrides.
from src.research.paths import SLEEVE_A_DATA_DIR as _DEFAULT_SLEEVE_A_DATA_DIR
FEATHER_DIR = os.getenv(
    "SLEEVE_A_FEATHER_DIR",
    str(_DEFAULT_SLEEVE_A_DATA_DIR) + "/",
)

# Path to Nautilus catalog (built by data_adapter from feather)
CATALOG_DIR = os.getenv(
    "SLEEVE_A_CATALOG_DIR",
    "/tmp/sleeve_a_catalog/",
)

# Window (mirror PROFITABLE_STRATEGY_REPORT backtest)
WINDOW_START = os.getenv("SLEEVE_A_WINDOW_START", "2025-01-01T00:00:00")
WINDOW_END = os.getenv("SLEEVE_A_WINDOW_END", "2026-03-12T00:00:00")

# Feature flags — Sleeve A has no CIS gate, no edge gate.  Kept here
# for parity with ls_v1 (env overrides if a future iteration wants to
# add a guard, e.g. "skip on TIGHTENING regime").
SLEEVE_A_ENABLE_RSI_EXIT = os.getenv("SLEEVE_A_ENABLE_RSI_EXIT", "1") == "1"
SLEEVE_A_ENABLE_PRICEPOS_EXIT = os.getenv("SLEEVE_A_ENABLE_PRICEPOS_EXIT", "1") == "1"


# ── Config ───────────────────────────────────────────────────────────────────

class SleeveAConfig(StrategyConfig, frozen=True):
    """Frozen config for CometCloudNautilusMultiFactorV2."""

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal

    # Indicator periods
    rsi_period: PositiveInt = RSI_PERIOD
    ema_fast_period: PositiveInt = EMA_FAST
    ema_slow_period: PositiveInt = EMA_SLOW
    adx_period: PositiveInt = ADX_PERIOD
    adx_threshold: float = ADX_THRESHOLD
    volume_ma_period: PositiveInt = LOOKBACK_VOLUME_MA
    lookback_20: PositiveInt = LOOKBACK_20

    # Risk knobs
    # Optional[float]: default = HARD_STOP_PCT (= 0.03) preserves freqtrade
    # `-3% stoploss` behaviour.  Pass `None` to disable the stop entirely
    # (used by B-S1 envelope variant `A1_ORIGINAL_3X_NOSTOP` to mirror the
    # freqtrade marketing-claim baseline: 3× lev, no stop, signal exit only).
    hard_stop_pct: Optional[float] = HARD_STOP_PCT
    leverage: PositiveInt = LEVERAGE_DEFAULT

    # Position caps
    max_open_trades: PositiveInt = MAX_OPEN_TRADES
    max_daily_trades: PositiveInt = MAX_DAILY_TRADES
    cooldown_bars: PositiveInt = COOLDOWN_BARS

    # Signal thresholds
    rsi_oversold: float = RSI_OVERSOLD
    rsi_overbought: float = RSI_OVERBOUGHT
    streak_down_threshold: PositiveInt = STREAK_DOWN_THRESHOLD
    volume_ratio_threshold: float = VOLUME_RATIO_THRESHOLD
    price_position_low: float = PRICE_POSITION_LOW
    price_position_high: float = PRICE_POSITION_HIGH

    # Feature flags
    enable_rsi_exit: bool = SLEEVE_A_ENABLE_RSI_EXIT
    enable_pricepos_exit: bool = SLEEVE_A_ENABLE_PRICEPOS_EXIT

    # Window (string → will be parsed in on_start)
    window_start: str = WINDOW_START
    window_end: str = WINDOW_END

    request_bars: bool = True
    close_positions_on_stop: bool = True


# ── Strategy ─────────────────────────────────────────────────────────────────

class CometCloudNautilusMultiFactorV2(Strategy):
    """
    Nautilus port of freqtrade `CometCloudMultiFactorV2` — 1h long-only,
    3-dimension gate (trend + extreme + momentum), hard -3% stop.

    Parity target: CometCloudMultiFactorV2 (Shadow) — same 3 pairs
    (BTC/ETH/SOL), same 14mo OOS window (2025-01-01 → 2026-03-12),
    same -3% stop, same 3-dimension entry gate.  Sleeve A is the
    durable fundamental core of the surviving two-layer book per
    MINIMAX_SYNC.md §STRATEGY-REVIVE.

    Expected parity gap: freqtrade's `confirm_trade_entry` does a
    Trade-proxy DB lookup; Nautilus cannot reach freqtrade's local
    sqlite from inside the strategy.  We mirror the semantics via
    in-process counters (_today_entry_count + portfolio.is_flat
    check).  The diff should land within 1 trade on the 14mo window
    if data + offsets are aligned (the gap is exactly the daily-cap
    off-by-one when freqtrade's proxy lookup crosses UTC midnight
    mid-bar).
    """

    # ── Duck-type contract from src/research/strategy_base.py ───────────
    @classmethod
    def required_indicators(cls) -> list[str]:
        return [
            "rsi", "ema_9", "ema_21",
            "plus_di", "minus_di", "adx",
            "streak_down",
            "volume_ma", "volume_ratio",
            "low_20", "high_20", "price_position",
            "close", "high", "low", "volume",
        ]

    @classmethod
    def required_timeframes(cls) -> list[str]:
        return ("1h",)

    @classmethod
    def required_history_bars(cls) -> int:
        # 1h bars: 50 (per freqtrade `if len(dataframe) < 50: return`)
        # + buffer for Wilder-smoothed ADX (period=14)
        return 60

    @classmethod
    def regime_filter(cls, cis: dict, regime: str) -> bool:
        """Optional regime veto.  Sleeve A is the durable core — no veto
        (the two-layer book uses Sleeve B's CIS gate for regime control).
        Returns True always."""
        return True

    @classmethod
    def compliance_tag(cls) -> str:
        return "CC_SLEEVE_A_NAUTILUS"  # positioning-language-safe per CLAUDE.md

    @classmethod
    def metrics_extra(cls) -> dict:
        return {
            "engine": "nautilus_trader",
            "engine_version": "1.229+",
            "can_short": False,
            "rsi_exit": SLEEVE_A_ENABLE_RSI_EXIT,
            "pricepos_exit": SLEEVE_A_ENABLE_PRICEPOS_EXIT,
            "max_open_trades": MAX_OPEN_TRADES,
            "max_daily_trades": MAX_DAILY_TRADES,
            "cooldown_bars": COOLDOWN_BARS,
            "hard_stop_pct": HARD_STOP_PCT,
            "leverage": LEVERAGE_DEFAULT,
        }

    # ── ctor + state ──────────────────────────────────────────────────────
    def __init__(self, config: SleeveAConfig) -> None:
        if config.ema_fast_period >= config.ema_slow_period:
            raise ValueError("ema_fast_period must be < ema_slow_period")
        super().__init__(config)
        self.instrument: Optional[Instrument] = None

        # Nautilus indicators (live, registered for bar callback).
        # We use ExponentialMovingAverage for the fast/slow EMA.  We
        # compute RSI inline because Nautilus 1.229 doesn't ship an
        # RSI indicator (verified at write time).  Same for the
        # 20-bar lookback (we maintain rolling high/low/volume_ma
        # via deque).
        self.fast_ema = ExponentialMovingAverage(config.ema_fast_period)
        self.slow_ema = ExponentialMovingAverage(config.ema_slow_period)
        self.atr = AverageTrueRange(ADX_PERIOD)  # for ADX computation
        # DirectionalMovement gives +DM / -DM; we compute DI inline
        # because Nautilus 1.229's DirectionalMovement exposes
        # pos / neg but not the DI normalisation (TR division).
        self.dm = DirectionalMovement(config.adx_period)

        # Inline ADX state (Wilder-smoothed DX).  Mirror LS v1's
        # _update_adx implementation — see _update_adx() below.
        self._adx: float = 0.0
        self._tr_smoothed: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._prev_high: Optional[float] = None
        self._prev_low: Optional[float] = None

        # Inline RSI state (Wilder-smoothed avg_gain / avg_loss).
        # Same convention as the freqtrade strategy but maintained
        # bar-by-bar instead of via pandas rolling.
        self._avg_gain: Optional[float] = None
        self._avg_loss: Optional[float] = None
        self._rsi: float = 50.0  # neutral default before warmup

        # Streak / volume / price_position rolling windows.
        # We can't allocate 20-element rolling state inside Nautilus
        # indicators (no built-in), so we keep deques in the strategy.
        from collections import deque
        self._close_window: deque = deque(maxlen=config.lookback_20)
        self._high_window: deque = deque(maxlen=config.lookback_20)
        self._low_window: deque = deque(maxlen=config.lookback_20)
        self._vol_window: deque = deque(maxlen=config.volume_ma_period)

        # Streak state — count consecutive down-close bars.  Resets
        # to 0 on any up-close bar (matches freqtrade loop).
        self._streak_down: int = 0

        # Bar counter (for cooldown).
        self._bars_since_last_entry: int = 10**9  # sentinel: "no recent entry"

        # Daily-trade cap (mirror freqtrade `confirm_trade_entry`
        # `today = [t for t in Trade.get_trades_proxy() if t.enter_date.date() == today]`).
        self._today_utc: Optional[str] = None  # YYYY-MM-DD
        self._today_entry_count: int = 0

        # Position tracking
        self._last_bar_ts_ns: int = 0
        self._open_pos_count: int = 0

        # Skip counters (read by runner for diagnostics).
        self._skipped_trend: int = 0
        self._skipped_extreme: int = 0
        self._skipped_momentum: int = 0
        self._skipped_cooldown: int = 0
        self._skipped_daily_cap: int = 0
        self._skipped_open_cap: int = 0
        self._skipped_already_long: int = 0
        self._exited_rsi: int = 0
        self._exited_pricepos: int = 0
        self._entered_long: int = 0

        # Last-known indicator snapshot — exposed via skip_summary()
        # so the parity_check diff has something to compare against
        # even if Nautilus aggregates only show the final trade list.
        self._last_indicators: dict = {}

    # ── Bar processing helpers ───────────────────────────────────────────

    def _update_adx(self, bar: Bar) -> None:
        """Wilder-smoothed DX → ADX.  Mirrors LS v1._update_adx
        exactly so Sleeve A and LS v1 produce the same ADX value on
        the same bar (parity property)."""
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)

        if self._prev_close is None:
            self._prev_close = c
            self._prev_high = h
            self._prev_low = l
            return

        # True Range
        if self._prev_close is not None:
            tr = max(
                h - l,
                abs(h - self._prev_close),
                abs(l - self._prev_close),
            )
        else:
            tr = h - l

        # Wilder smoothing of TR (14-period)
        period = self.config.adx_period
        if self._tr_smoothed is None:
            self._tr_smoothed = tr
            # First bar: seed +DM / -DM
            up_move = h - self._prev_high
            down_move = self._prev_low - l
            plus_dm = max(up_move, 0.0) if up_move > down_move else 0.0
            minus_dm = max(down_move, 0.0) if down_move > up_move else 0.0
            self._plus_dm_smoothed = plus_dm
            self._minus_dm_smoothed = minus_dm
        else:
            self._tr_smoothed = (
                (self._tr_smoothed * (period - 1) + tr) / period
            )
            up_move = h - self._prev_high
            down_move = self._prev_low - l
            plus_dm = max(up_move, 0.0) if up_move > down_move else 0.0
            minus_dm = max(down_move, 0.0) if down_move > up_move else 0.0
            self._plus_dm_smoothed = (
                (self._plus_dm_smoothed * (period - 1) + plus_dm) / period
            )
            self._minus_dm_smoothed = (
                (self._minus_dm_smoothed * (period - 1) + minus_dm) / period
            )

        # DI = 100 × smoothed_DM / smoothed_TR
        if self._tr_smoothed and self._tr_smoothed > 0:
            plus_di = 100.0 * self._plus_dm_smoothed / self._tr_smoothed
            minus_di = 100.0 * self._minus_dm_smoothed / self._tr_smoothed
        else:
            plus_di = 0.0
            minus_di = 0.0

        # DX = 100 × |+DI - -DI| / (+DI + -DI)
        denom = plus_di + minus_di
        if denom > 0:
            dx = 100.0 * abs(plus_di - minus_di) / denom
        else:
            dx = 0.0

        # Wilder-smoothed ADX (same 14-period, starting from the first DX)
        if not hasattr(self, "_adx_initialized") or not self._adx_initialized:
            self._adx = dx
            self._adx_initialized = True
        else:
            self._adx = (self._adx * (period - 1) + dx) / period

        # Store last DI values for indicator snapshot
        self._plus_di_last = plus_di
        self._minus_di_last = minus_di

        self._prev_close = c
        self._prev_high = h
        self._prev_low = l

    def _update_rsi(self, bar: Bar) -> None:
        """Wilder-smoothed RSI(14).  Mirrors freqtrade's
        `delta.where(delta > 0, 0).rolling(14).mean()` shape."""
        c = float(bar.close)
        if self._prev_close is None:
            self._prev_close_for_rsi = c
            return
        change = c - self._prev_close_for_rsi
        self._prev_close_for_rsi = c
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        period = self.config.rsi_period
        if self._avg_gain is None:
            self._avg_gain = gain
            self._avg_loss = loss
        else:
            self._avg_gain = (self._avg_gain * (period - 1) + gain) / period
            self._avg_loss = (self._avg_loss * (period - 1) + loss) / period

        if self._avg_loss == 0:
            self._rsi = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self._rsi = 100.0 - (100.0 / (1.0 + rs))

    def _update_rolling(self, bar: Bar) -> None:
        """Maintain 20-bar high/low/volume_ma deques + streak_down."""
        c = float(bar.close)
        h = float(bar.high)
        l = float(bar.low)
        v = float(bar.volume)

        self._close_window.append(c)
        self._high_window.append(h)
        self._low_window.append(l)
        self._vol_window.append(v)

        # streak_down (mirror freqtrade loop)
        if len(self._close_window) >= 2:
            prev = self._close_window[-2]
            if c < prev:
                self._streak_down += 1
            else:
                self._streak_down = 0

    def _volume_ratio(self) -> Optional[float]:
        if len(self._vol_window) < self.config.volume_ma_period:
            return None
        ma = sum(self._vol_window) / len(self._vol_window)
        if ma <= 0:
            return None
        return self._vol_window[-1] / ma

    def _price_position(self) -> Optional[float]:
        if len(self._close_window) < self.config.lookback_20:
            return None
        lo = min(self._low_window)
        hi = max(self._high_window)
        denom = hi - lo
        if denom == 0:
            return None
        return (self._close_window[-1] - lo) / (denom + 0.001)

    def _low_20(self) -> Optional[float]:
        if len(self._low_window) < self.config.lookback_20:
            return None
        return min(self._low_window)

    def _high_20(self) -> Optional[float]:
        if len(self._high_window) < self.config.lookback_20:
            return None
        return max(self._high_window)

    def _volume_ma(self) -> Optional[float]:
        if len(self._vol_window) < self.config.volume_ma_period:
            return None
        return sum(self._vol_window) / len(self._vol_window)

    # ── Nautilus lifecycle ────────────────────────────────────────────────
    def on_start(self) -> None:
        # Initialise today-counter on first bar.  The actual date
        # reset happens in on_bar via the bar timestamp.
        self._today_utc = None
        self._today_entry_count = 0
        self.log.info(
            f"SLEEVE A started: instrument={self.config.instrument_id} "
            f"bar_type={self.config.bar_type} "
            f"lev={self.config.leverage}x "
            f"stop={'NONE' if self.config.hard_stop_pct is None else f'{self.config.hard_stop_pct:.1%}'} "
            f"max_open={self.config.max_open_trades} max_daily={self.config.max_daily_trades}",
            LogColor.GREEN,
        )

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized():
            return
        if bar.is_single_price():
            return

        self._last_bar_ts_ns = bar.ts_event

        # Update indicators in fixed order (matches freqtrade
        # populate_indicators column order).
        self._update_adx(bar)
        self._update_rsi(bar)
        self._update_rolling(bar)

        # Daily-trade-cap refresh: when bar's UTC date changes,
        # reset the counter.
        bar_date = datetime.fromtimestamp(
            bar.ts_event / 1e9, tz=timezone.utc,
        ).strftime("%Y-%m-%d")
        if self._today_utc != bar_date:
            self._today_utc = bar_date
            self._today_entry_count = 0

        # Save indicator snapshot (for parity_check diff)
        fast = float(self.fast_ema.value)
        slow = float(self.slow_ema.value)
        adx = self._adx
        plus_di = getattr(self, "_plus_di_last", 0.0)
        minus_di = getattr(self, "_minus_di_last", 0.0)
        rsi = self._rsi
        vr = self._volume_ratio()
        pp = self._price_position()

        self._last_indicators = {
            "ts": bar.ts_event,
            "close": float(bar.close),
            "ema_9": fast,
            "ema_21": slow,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "rsi": rsi,
            "streak_down": self._streak_down,
            "volume_ratio": vr,
            "price_position": pp,
        }

        # ── ENTRY GATE (mirror freqtrade populate_entry_trend) ───────
        # All three dimensions required + cooldown + caps.
        # Each skip is counted separately for parity_check diagnostics.
        if len(self._close_window) < 50:
            return  # freqtrade: `if len(dataframe) < 50: return`

        if vr is None or pp is None:
            return  # rolling windows not warm yet

        inst_id = self.config.instrument_id

        # === Dimension 1: trend ===
        trend_ok = (fast > slow) and (plus_di > minus_di) and (adx > self.config.adx_threshold)
        if not trend_ok:
            self._skipped_trend += 1
        else:
            # === Dimension 2: extreme ===
            extreme_ok = (rsi < self.config.rsi_oversold) or (self._streak_down >= self.config.streak_down_threshold)
            if not extreme_ok:
                self._skipped_extreme += 1
            else:
                # === Dimension 3: momentum ===
                momentum_ok = (vr > self.config.volume_ratio_threshold) or (pp < self.config.price_position_low)
                if not momentum_ok:
                    self._skipped_momentum += 1
                else:
                    # All 3 dims OK — apply cooldown + caps
                    self._bars_since_last_entry += 1
                    if self._bars_since_last_entry < self.config.cooldown_bars:
                        self._skipped_cooldown += 1
                    elif self._today_entry_count >= self.config.max_daily_trades:
                        self._skipped_daily_cap += 1
                    elif self._open_pos_count >= self.config.max_open_trades:
                        self._skipped_open_cap += 1
                    elif not self.portfolio.is_flat(inst_id):
                        self._skipped_already_long += 1
                    else:
                        # ── ENTER LONG ─────────────────────────────
                        self._enter_long(bar)
                        self._bars_since_last_entry = 0
                        self._today_entry_count += 1
                        self._open_pos_count += 1
                        self._entered_long += 1

        # ── EXIT GATE (mirror freqtrade populate_exit_trend) ──────────
        # freqtrade leaves populate_exit_trend empty (relies on the -3%
        # stop + ROI=0).  We add the RSI > 65 OR price_position > 75%
        # exit that the strategy file documents in its docstring — these
        # fire only when we have a long position.  Behind feature flags
        # for parity runs.
        if not self.portfolio.is_net_long(inst_id):
            return
        if self.config.enable_rsi_exit and rsi > self.config.rsi_overbought:
            self._exited_rsi += 1
            self.close_all_positions(inst_id)
            self._open_pos_count = max(0, self._open_pos_count - 1)
        elif self.config.enable_pricepos_exit and pp > self.config.price_position_high:
            self._exited_pricepos += 1
            self.close_all_positions(inst_id)
            self._open_pos_count = max(0, self._open_pos_count - 1)

    # ── Position entry ───────────────────────────────────────────────────
    def _enter_long(self, bar: Bar) -> None:
        """Enter long at market with a hard stop (default -3%, can be NONE).
        Mirror freqtrade's `stoploss = -0.03` — no bracket, no ATR,
        no take-profit.
        The Nautilus engine handles the stop via `close_positions_on_stop=True`
        + a manual `stop_loss` order on the position.
        """
        instrument = self.instrument
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.create_order_qty(),
            time_in_force=None,  # default GTC for futures
            tags=["LONG_ENTRY"],
        )
        self.submit_order(order, position_id=None)  # let engine assign

        # Place a hard stop at -X% from entry, ONLY if hard_stop_pct is set.
        # We use a STOP_MARKET order referencing the position via the
        # position_id assigned at fill time.  Nautilus recommends using
        # bracket orders for simultaneous entry+SL, but Sleeve A's stop is
        # intentionally simple — mirror freqtrade's `stoploss = -0.03` exactly.
        #
        # NOSTOP variant (B-S1 envelope `A1_ORIGINAL_3X_NOSTOP`):
        # `hard_stop_pct=None`  →  skip stop placement, signal exits only.
        entry_price = float(bar.close)
        sl_price = None
        if self.config.hard_stop_pct is not None:
            sl_distance = self.config.hard_stop_pct * entry_price
            sl_price = instrument.make_price(entry_price - sl_distance)
            stop_order = self.order_factory.stop_market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.SELL,
                quantity=self.create_order_qty(),
                trigger_price=sl_price,
                time_in_force=None,
                tags=[f"HARD_STOP_{int(self.config.hard_stop_pct * 100)}PCT"],
            )
            self.submit_order(stop_order)

        # Build enter_tag (mirror freqtrade's "_".join(signals[:3]))
        signals = []
        if self._rsi < self.config.rsi_oversold:
            signals.append(f"RSI{int(self._rsi)}")
        if self._streak_down >= self.config.streak_down_threshold:
            signals.append(f"DROP{self._streak_down}")
        if (self._volume_ratio() or 0) > self.config.volume_ratio_threshold:
            signals.append("VOL")
        if (self._price_position() or 1) < self.config.price_position_low:
            signals.append("LOW")
        if self._adx > 30:
            signals.append(f"ADX{int(self._adx)}")
        enter_tag = "_".join(signals[:3]) if signals else "BASIC"

        if sl_price is not None:
            sl_log = f"sl={sl_price}"
        else:
            sl_log = "sl=NONE"
        self.log.info(
            f"LONG_ENTRY {enter_tag} @ {entry_price:.2f} "
            f"{sl_log} rsi={self._rsi:.1f} adx={self._adx:.1f} "
            f"streak={self._streak_down} vol_ratio={self._volume_ratio():.2f} "
            f"price_pos={self._price_position():.3f}",
            LogColor.GREEN,
        )

    # ── Quantity ──────────────────────────────────────────────────────────
    def create_order_qty(self) -> Quantity:
        """Order quantity = trade_size × leverage."""
        instrument = self.instrument
        notional = float(self.config.trade_size) * float(self.config.leverage)
        # Convert notional USD to base-units via the current close price
        close = float(self.cache.bar(self.config.bar_type).close.as_double())
        if close <= 0:
            return instrument.make_qty(0.0)
        raw_qty = notional / close
        return instrument.make_qty(raw_qty)

    # ── Symbol helper ────────────────────────────────────────────────────
    def _symbol_for_inst(self, inst_id: InstrumentId) -> str:
        """Derive CIS symbol from instrument_id.

        Convention: BTCUSDT-PERP → "BTC" (matches freqtrade config).
        Override via subclass if your catalog uses a different mapping.
        """
        raw = inst_id.symbol.value
        return raw.replace("USDT-PERP", "").replace("USD-PERP", "").replace("USDT", "")

    # ── Lifecycle cleanup ────────────────────────────────────────────────
    def on_stop(self) -> None:
        # Reset state so a re-run starts clean (parity runs re-launch
        # the strategy inside a fresh BacktestNode).
        self._prev_close = None
        self._prev_high = None
        self._prev_low = None
        self._prev_close_for_rsi = None
        self._tr_smoothed = None
        self._plus_dm_smoothed = None
        self._minus_dm_smoothed = None
        self._adx = 0.0
        self._adx_initialized = False
        self._avg_gain = None
        self._avg_loss = None
        self._rsi = 50.0
        self._streak_down = 0
        self._bars_since_last_entry = 10**9
        self._today_utc = None
        self._today_entry_count = 0
        self._open_pos_count = 0
        self._skipped_trend = 0
        self._skipped_extreme = 0
        self._skipped_momentum = 0
        self._skipped_cooldown = 0
        self._skipped_daily_cap = 0
        self._skipped_open_cap = 0
        self._skipped_already_long = 0
        self._exited_rsi = 0
        self._exited_pricepos = 0
        self._entered_long = 0

    # ── Diagnostics ──────────────────────────────────────────────────────
    def skip_summary(self) -> dict:
        return {
            "entered_long": self._entered_long,
            "exited_rsi": self._exited_rsi,
            "exited_pricepos": self._exited_pricepos,
            "skipped_trend": self._skipped_trend,
            "skipped_extreme": self._skipped_extreme,
            "skipped_momentum": self._skipped_momentum,
            "skipped_cooldown": self._skipped_cooldown,
            "skipped_daily_cap": self._skipped_daily_cap,
            "skipped_open_cap": self._skipped_open_cap,
            "skipped_already_long": self._skipped_already_long,
            "open_pos_count_final": self._open_pos_count,
            "today_entry_count_final": self._today_entry_count,
            "bars_seen": getattr(self, "_bars_seen", 0),
            "last_indicators": self._last_indicators,
        }


# ── Smoke ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("CometCloudNautilusMultiFactorV2 (Sleeve A) loaded.")
    print(f"  classmethod contract:")
    print(f"    required_indicators:  {CometCloudNautilusMultiFactorV2.required_indicators()}")
    print(f"    required_timeframes:  {CometCloudNautilusMultiFactorV2.required_timeframes()}")
    print(f"    required_history_bars: {CometCloudNautilusMultiFactorV2.required_history_bars()}")
    print(f"    compliance_tag:        {CometCloudNautilusMultiFactorV2.compliance_tag()}")
    print(f"    metrics_extra:         {CometCloudNautilusMultiFactorV2.metrics_extra()}")
    print(f"  feature flags (env-overridable):")
    print(f"    SLEEVE_A_ENABLE_RSI_EXIT={SLEEVE_A_ENABLE_RSI_EXIT}, "
          f"SLEEVE_A_ENABLE_PRICEPOS_EXIT={SLEEVE_A_ENABLE_PRICEPOS_EXIT}")
    print(f"  risk knobs: stop={HARD_STOP_PCT:.1%}, leverage={LEVERAGE_DEFAULT}x, "
          f"max_open={MAX_OPEN_TRADES}, max_daily={MAX_DAILY_TRADES}, "
          f"cooldown_bars={COOLDOWN_BARS}")