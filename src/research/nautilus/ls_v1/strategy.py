"""
CometCloud Nautilus LS v1 — strategy (Minimax-B, 2026-07-04)
=============================================================

Parity port of `freqtrade/user_data/strategies/CometCloudLongShortV4.py`
to Nautilus Trader 1.229+.  Targets:

  - 4h bars, BTC/ETH/SOL USDT-margined perpetuals
  - Long-short engine (can_short=True) — mirrors freqtrade
  - EMA(9) / EMA(21) cross for entry direction
  - ADX gate (DX + inline Wilder smoothing — Nautilus 1.229 has
    `DirectionalMovement` (+DI / -DI) but no ADX aggregate, so we
    compute DX and maintain a Wilder-smoothed ADX state)
  - ATR(14)-normalised SL / TP bracket
  - CIS gate: regime-aware `min_cis_score` (date-keyed lookup against
    `cis_history/cis_YYYY-MM-DD.json`; falls back to soft floor in
    backtest-bypass mode when the cache is sparse)

Engines layered as feature flags (default ON for parity, OFF for
"alpha-only" run that matches Shadow's earlier `ls_v4.py`):

    ENABLE_ADX_GATE   : bool = True   (Nautilus 1.229 has DirectionalMovement,
                                       ADX is computed inline from +DI / -DI)
    ENABLE_CIS_GATE   : bool = True   (regime-aware min_cis_score)
    ENABLE_FUNDING_FILTER : bool = False  (funding rate data not in catalog)

Compliance: signal labels use positioning language only (STRONG OUTPERFORM /
OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT) per CLAUDE.md.

Duck-type contract from `src/research/strategy_base.py` is implemented
via classmethods so the strategy can be introspected by tooling (the
strategy is intentionally NOT registered with the project strategy
registry — this lane is engine plumbing, see package docstring).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from nautilus_trader.common.enums import LogColor
from nautilus_trader.config import PositiveInt
from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import AverageTrueRange
from nautilus_trader.indicators import DirectionalMovement
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.data import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


logger = logging.getLogger(__name__)


# ── Constants (mirror freqtrade LS V4 exactly) ────────────────────────────────

# ADX / EMA technical gates
ADX_THRESHOLD = 25
ADX_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21

# ATR SL/TP knobs
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
ATR_TP1_MULT = 2.5
ATR_TP2_MULT = 1.0
ATR_MIN_STOP_PCT = 0.020
ATR_MIN_TP_PCT = 0.030

# Regime-aware CIS threshold (mirrors freqtrade LS V4 REGIME_CIS_FLOOR)
REGIME_CIS_FLOOR = {
    "Tightening":  52,
    "Risk-Off":    50,
    "Stagflation": 50,
    "Neutral":     58,
    "Easing":      62,
    "Risk-On":     65,
    "Goldilocks":  65,
}
# Soft floor used when CIS cache is sparse (backtest-bypass mode)
CIS_SOFT_FLOOR = 30

# CIS history directory (env-overridable for testing)
CIS_HISTORY_DIR = os.getenv(
    "CIS_HISTORY_DIR",
    "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/",
)

# Feature flags — turn OFF to match Shadow's earlier alpha-only ls_v4.py
ENABLE_ADX_GATE = os.getenv("LSV1_ENABLE_ADX_GATE", "1") == "1"
ENABLE_CIS_GATE = os.getenv("LSV1_ENABLE_CIS_GATE", "1") == "1"
ENABLE_FUNDING_FILTER = os.getenv("LSV1_ENABLE_FUNDING_FILTER", "0") == "1"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalise_regime(raw: str) -> str:
    """Map CIS macro_regime strings → freqtrade regime names (long-short aware)."""
    if not raw:
        return "Neutral"
    up = raw.strip().upper().replace("-", "_")
    return {
        "RISK_OFF": "Risk-Off", "RISK_ON": "Risk-On",
        "EASING": "Easing", "TIGHTENING": "Tightening",
        "STAGFLATION": "Stagflation", "NEUTRAL": "Neutral",
        "GOLDILOCKS": "Goldilocks",
    }.get(up, "Neutral")


# ── Config ───────────────────────────────────────────────────────────────────

class LSv1Config(StrategyConfig, frozen=True):
    """Frozen config for CometCloudNautilusLongShortV1."""

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal

    adx_period: PositiveInt = ADX_PERIOD
    adx_threshold: float = ADX_THRESHOLD
    ema_fast_period: PositiveInt = EMA_FAST
    ema_slow_period: PositiveInt = EMA_SLOW
    atr_period: PositiveInt = ATR_PERIOD
    atr_stop_mult: float = ATR_STOP_MULT
    atr_tp1_mult: float = ATR_TP1_MULT
    atr_tp2_mult: float = ATR_TP2_MULT
    atr_min_stop_pct: float = ATR_MIN_STOP_PCT
    atr_min_tp_pct: float = ATR_MIN_TP_PCT

    enable_adx_gate: bool = ENABLE_ADX_GATE
    enable_cis_gate: bool = ENABLE_CIS_GATE
    enable_funding_filter: bool = ENABLE_FUNDING_FILTER

    cis_history_dir: str = CIS_HISTORY_DIR
    cis_soft_floor: float = CIS_SOFT_FLOOR
    regime_cis_floor: dict[str, int] = None  # set in __init__ if None

    request_bars: bool = True
    close_positions_on_stop: bool = True

    def __post_init__(self) -> None:  # msgspec-friendly default
        if self.regime_cis_floor is None:
            object.__setattr__(self, "regime_cis_floor", dict(REGIME_CIS_FLOOR))


# ── Strategy ─────────────────────────────────────────────────────────────────

class CometCloudNautilusLongShortV1(Strategy):
    """
    Nautilus port of freqtrade LS V4 — 4h long-short, regime-aware, CIS-gated.

    Parity target: `CometCloudLongShortV4` (Shadow) — same 3 pairs, same
    OOS window (2025-05-03 → 2026-03-12), same ATR SL/TP.  This strategy
    adds back the CIS + ADX layers that the earlier Shadow `ls_v4.py`
    stub omitted.

    Expected divergence: with CIS + ADX ON this version should produce
    FEWER trades than Shadow's stub (the gate filters them out).  The
    parity check (`parity_check.diff_runs`) reports the gap.
    """

    # ── Duck-type contract from src/research/strategy_base.py ───────────
    @classmethod
    def required_indicators(cls) -> list[str]:
        return [
            "ema_9", "ema_21", "atr", "atr_pct",
            "plus_di", "minus_di", "adx",
            "close", "high", "low",
        ]

    @classmethod
    def required_timeframes(cls) -> list[str]:
        return ("4h",)

    @classmethod
    def required_history_bars(cls) -> int:
        # 4h bars: 60 ≈ 10 days, enough to warm up Wilder-smoothed ADX
        return 60

    @classmethod
    def regime_filter(cls, cis: dict, regime: str) -> bool:
        """Optional regime veto.  Returns True (allow) by default — the
        actual gate is applied in `_cis_passes()` which has the soft-floor
        fallback for backtest mode."""
        return True

    @classmethod
    def compliance_tag(cls) -> str:
        return "CC_LS_V1_NAUTILUS"  # positioning-language-safe per CLAUDE.md

    @classmethod
    def metrics_extra(cls) -> dict:
        return {
            "engine": "nautilus_trader",
            "engine_version": "1.229+",
            "can_short": True,
            "adx_gate": ENABLE_ADX_GATE,
            "cis_gate": ENABLE_CIS_GATE,
            "funding_filter": ENABLE_FUNDING_FILTER,
        }

    # ── ctor + state ──────────────────────────────────────────────────────
    def __init__(self, config: LSv1Config) -> None:
        if config.ema_fast_period >= config.ema_slow_period:
            raise ValueError("ema_fast_period must be < ema_slow_period")
        super().__init__(config)
        self.instrument: Optional[Instrument] = None

        # Nautilus indicators (live, registered for bar callback)
        self.fast_ema = ExponentialMovingAverage(config.ema_fast_period)
        self.slow_ema = ExponentialMovingAverage(config.ema_slow_period)
        self.atr = AverageTrueRange(config.atr_period)
        # DirectionalMovement gives +DI / -DI.  We don't register a
        # separate ADX indicator because Nautilus 1.229 doesn't ship one.
        self.dm = DirectionalMovement(config.adx_period)

        # Inline ADX state (Wilder-smoothed DX).  DM.pos / DM.neg in
        # Nautilus 1.229+ are smoothed +DM / -DM (NOT +DI / -DI which would
        # be normalised by TR).  We compute TR inline + Wilder-smooth it
        # so the formula matches ta.ADX from freqtrade's ta-lib.
        self._adx: float = 0.0
        self._dx_sum: float = 0.0
        self._dm_count: int = 0
        self._prev_close: Optional[float] = None
        self._tr_smoothed: Optional[float] = None

        # Cross state
        self._prev_fast: Optional[float] = None
        self._prev_slow: Optional[float] = None

        # CIS history (date-keyed, mirrors freqtrade _load_cis_cache)
        self._cis_by_date: dict[str, dict] = {}
        self._current_regime: str = "Neutral"
        self._regime_floor: int = REGIME_CIS_FLOOR["Neutral"]
        # Env-overridable per-regime floor (H2 sweep, Seth 2026-07-06):
        #   LSV1_REGIME_FLOOR_RISK_OFF=40 → use 40 instead of 50 for Risk-Off
        self._env_floor_override: dict[str, int] = {}

        # Position tracking for diagnostics
        self._last_bar_ts_ns: int = 0
        self._open_pos_count: int = 0

        # Skip counters (read by runner for diagnostics)
        self._skipped_adx: int = 0
        self._skipped_cis: int = 0
        self._skipped_already_in_pos: int = 0
        self._entered_long: int = 0
        self._entered_short: int = 0

    # ── CIS history loading (mirror freqtrade _load_cis_cache) ───────────
    def _load_cis_history(self) -> None:
        history_dir = Path(self.config.cis_history_dir)
        if not history_dir.exists():
            logger.warning(
                f"[LSv1] CIS_HISTORY_DIR missing: {history_dir} — "
                f"CIS gate will run in soft-floor (backtest bypass) mode"
            )
            return
        for f in sorted(history_dir.glob("cis_*.json")):
            date_str = f.stem.replace("cis_", "")
            try:
                with f.open() as fp:
                    self._cis_by_date[date_str] = json.load(fp)
            except Exception as exc:
                logger.debug(f"[LSv1] skip {f}: {exc}")
        logger.info(
            f"[LSv1] loaded CIS history: {len(self._cis_by_date)} days "
            f"from {history_dir}"
        )

    def _cis_for_symbol(self, symbol: str) -> dict:
        """Date-keyed CIS lookup.  Falls back to latest snapshot if date missing."""
        if not self._cis_by_date or self._last_bar_ts_ns == 0:
            return {}
        bar_dt = dt.datetime.fromtimestamp(
            self._last_bar_ts_ns / 1e9, tz=dt.timezone.utc
        )
        date_key = bar_dt.strftime("%Y-%m-%d")
        snapshot = self._cis_by_date.get(date_key) or (
            self._cis_by_date[max(self._cis_by_date.keys())]
            if self._cis_by_date else {}
        )
        # Update regime from snapshot
        regime = _normalise_regime(snapshot.get("macro_regime", "Neutral"))
        if regime != self._current_regime:
            self._current_regime = regime
            # Env override takes precedence (H2 magnitude sweep)
            override = self._env_floor_override.get(regime)
            if override is not None:
                self._regime_floor = override
            else:
                self._regime_floor = self.config.regime_cis_floor.get(
                    regime, REGIME_CIS_FLOOR["Neutral"]
                )
        for s in snapshot.get("scores", []):
            if s.get("symbol") == symbol or s.get("asset") == symbol:
                return s
        return {}

    def _cis_history_is_dense(self) -> bool:
        """Heuristic: ≥ 30 daily CIS snapshots = full gate.  Else backtest bypass."""
        return len(self._cis_by_date) >= 30

    def _cis_passes(self, symbol: str) -> bool:
        """CIS gate.  Backtest-bypass when cache is sparse — mirrors freqtrade
        `CometCloudLongShortV4` `_load_cis_cache` soft-fallback behaviour.

        Direction is regime-specific and env-overridable for research:
            LSV1_GATE_DIRECTION_<REGIMENAME>=high|inverted|drop
        Default for all regimes: "high" (current behavior).

        Per H1 (2026-07-06 Seth), several regimes show NEGATIVE composite IC,
        so research variants can flip to "inverted" (require LOW CIS) or "drop"
        (no gate) to test the directional hypothesis.
        """
        cis = self._cis_for_symbol(symbol)
        # Determine the gate direction for the current regime
        env_key = f"LSV1_GATE_DIRECTION_{self._current_regime.upper().replace('-', '_')}"
        direction = os.getenv(env_key, "high").lower()

        bypass = not self._cis_history_is_dense()  # freqtrade: also checks "live" freshness
        if bypass:
            if not cis:
                return True  # no data at all → allow (let tech+ADX decide)
            score = cis.get("cis_score", 0) or 0
            score = float(score)
            if direction == "drop":
                return True
            if direction == "inverted":
                # Low CIS passes; high CIS blocks (opposite of high-floor).
                return score <= self._regime_floor
            # "high" bypass uses regime_floor (env override already applied)
            return score >= self._regime_floor
        if not cis:
            return False
        score = float(cis.get("cis_score", 0) or 0)
        if direction == "drop":
            return True
        if direction == "inverted":
            # Inverted: require CIS BELOW the floor (low-CIS names pass)
            # Use the same numerical floor but flip the comparison.
            return score <= self._regime_floor
        return score >= self._regime_floor

    # ── Inline ADX (DX + Wilder smoothing, Nautilus 1.229 has no ADX) ────
    def _update_adx(self, bar: Bar) -> None:
        """Compute +DI / -DI from DM (smoothed +DM / -DM) and TR, then DX,
        then ADX (Wilder-smoothed DX).  Mirrors freqtrade's ta.ADX shape.

        Nautilus 1.229+ `DirectionalMovement` gives smoothed +DM and -DM
        (via its MovingAverage type — default EXPONENTIAL).  Wilder ADX
        requires +DM/TR and -DM/TR (the DI step), and a Wilder-smoothed
        DX.  We track `_prev_close` and `_tr_smoothed` ourselves; rest of
        the strategy uses `self._adx` as a number in [0, 100].

        ADX_0 = mean of first `period` DX values
        ADX_t = (ADX_{t-1} * (period-1) + DX_t) / period
        """
        # True Range (Wilder definition: prev close is needed)
        h = float(bar.high.as_double())
        l = float(bar.low.as_double())
        c = float(bar.close.as_double())
        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
        self._prev_close = c

        # Wilder-smoothed TR
        period = self.config.adx_period
        if self._tr_smoothed is None:
            self._tr_smoothed = tr
        else:
            self._tr_smoothed = (self._tr_smoothed * (period - 1) + tr) / period
        tr_s = self._tr_smoothed if self._tr_smoothed > 0 else 1.0

        pos = float(self.dm.pos)   # smoothed +DM
        neg = float(self.dm.neg)   # smoothed -DM
        plus_di = 100.0 * pos / tr_s
        minus_di = 100.0 * neg / tr_s
        s = plus_di + minus_di
        if s <= 0:
            dx = 0.0
        else:
            dx = 100.0 * abs(plus_di - minus_di) / s

        # ADX — Wilder smooth of DX with period-bar warmup
        self._dm_count += 1
        if self._dm_count < period:
            self._dx_sum += dx
            if self._dm_count == period:
                self._adx = self._dx_sum / period
        else:
            self._adx = (self._adx * (period - 1) + dx) / period

    # ── Nautilus lifecycle hooks ──────────────────────────────────────────
    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"No instrument for {self.config.instrument_id}")
            self.stop()
            return
        for ind in (self.fast_ema, self.slow_ema, self.atr, self.dm):
            self.register_indicator_for_bars(self.config.bar_type, ind)
        # Even in backtest we must subscribe so the DataEngine dispatches bars.
        self.subscribe_bars(self.config.bar_type)
        # CIS history (one-shot)
        self._load_cis_history()
        # Env-overridable per-regime floors (LSV1_REGIME_FLOOR_<REGIME>=N).
        # Lazily resolved because some env vars are only set for specific regimes.
        self._resolve_env_floor_overrides()
        self.log.info(
            f"[LSv1] on_start: instrument={self.instrument.id} "
            f"bar_type={self.config.bar_type} "
            f"adx_gate={self.config.enable_adx_gate} "
            f"cis_gate={self.config.enable_cis_gate} "
            f"cis_days={len(self._cis_by_date)} "
            f"env_floor_override={self._env_floor_override or '{}'}"
        )

    def _resolve_env_floor_overrides(self) -> None:
        """Read LSV1_REGIME_FLOOR_<REGIME>=N env vars and store per-regime override."""
        prefix = "LSV1_REGIME_FLOOR_"
        for key, val in os.environ.items():
            if not key.startswith(prefix):
                continue
            raw_regime = key[len(prefix):]
            # normalise: "RISK_OFF" → "Risk-Off", "TIGHTENING" → "Tightening"
            normalised = _normalise_regime(raw_regime.replace("_", "-"))
            try:
                self._env_floor_override[normalised] = int(val)
            except ValueError:
                logger.warning(
                    f"[LSv1] bad {key}={val!r} (expected int); ignored"
                )

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized():
            return
        if bar.is_single_price():
            return
        self._last_bar_ts_ns = bar.ts_event
        self._update_adx(bar)

        fast = float(self.fast_ema.value)
        slow = float(self.slow_ema.value)
        prev_fast = self._prev_fast
        prev_slow = self._prev_slow
        self._prev_fast = fast
        self._prev_slow = slow
        if prev_fast is None or prev_slow is None:
            return  # not enough history to detect cross

        cross_up = prev_fast <= prev_slow and fast > slow
        cross_dn = prev_fast >= prev_slow and fast < slow
        if not (cross_up or cross_dn):
            return

        # ── ADX gate (harness entry confirmation) ────────────────────────
        if self.config.enable_adx_gate and self._adx < self.config.adx_threshold:
            self._skipped_adx += 1
            return

        # ── CIS gate (regime-aware min_cis_score) ────────────────────────
        # We need the symbol for the gate.  Derive from instrument_id.
        # Convention used by data_adapter: BTCUSDT-PERP → "BTC"
        symbol = self._symbol_for_inst(self.config.instrument_id)
        if self.config.enable_cis_gate and not self._cis_passes(symbol):
            self._skipped_cis += 1
            return

        # ── Position state: flat → enter, wrong-side → flip ──────────────
        inst_id = self.config.instrument_id
        if cross_up:
            if self.portfolio.is_flat(inst_id):
                self._enter_long()
            elif self.portfolio.is_net_short(inst_id):
                self._skipped_already_in_pos += 1
                self.close_all_positions(inst_id)
                self._enter_long()
        elif cross_dn:
            if self.portfolio.is_flat(inst_id):
                self._enter_short()
            elif self.portfolio.is_net_long(inst_id):
                self._skipped_already_in_pos += 1
                self.close_all_positions(inst_id)
                self._enter_short()

    # ── Symbol / quantity helpers ─────────────────────────────────────────
    def _symbol_for_inst(self, inst_id: InstrumentId) -> str:
        """Derive CIS symbol from instrument_id.

        Convention: BTCUSDT-PERP → "BTC" (matches freqtrade config_ls_futures.json).
        Override via subclass if your catalog uses a different mapping.
        """
        raw = inst_id.symbol.value
        return raw.replace("USDT-PERP", "").replace("USD-PERP", "").replace("USDT", "")

    def create_order_qty(self) -> Quantity:
        return self.instrument.make_qty(self.config.trade_size)

    # ── Entries (bracket: market + SL + TP1) ──────────────────────────────
    def _enter_long(self) -> None:
        close = float(self._last_close())
        atr_pct = self._atr_pct_or_floor()
        if close <= 0 or atr_pct <= 0:
            return
        stop_dist = max(
            self.config.atr_stop_mult * atr_pct * close,
            self.config.atr_min_stop_pct * close,
        )
        tp_dist = max(
            self.config.atr_tp1_mult * atr_pct * close,
            self.config.atr_min_tp_pct * close,
        )
        instrument = self.instrument
        sl_price = instrument.make_price(close - stop_dist)
        tp_price = instrument.make_price(close + tp_dist)
        order_list = self.order_factory.bracket(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.create_order_qty(),
            entry_price=self._last_close_obj(),
            sl_trigger_price=sl_price,
            tp_price=tp_price,
            entry_tags=["LONG_ENTRY"],
            sl_tags=["STOP_LOSS"],
            tp_tags=["TAKE_PROFIT_TP1"],
        )
        self.submit_order_list(order_list)
        self._open_pos_count += 1
        self._entered_long += 1
        self.log.info(
            f"LONG entered bracket (ADX={self._adx:.1f} "
            f"regime={self._current_regime} "
            f"fast={self.fast_ema.value:.2f} slow={self.slow_ema.value:.2f})",
            LogColor.GREEN,
        )

    def _enter_short(self) -> None:
        close = float(self._last_close())
        atr_pct = self._atr_pct_or_floor()
        if close <= 0 or atr_pct <= 0:
            return
        stop_dist = max(
            self.config.atr_stop_mult * atr_pct * close,
            self.config.atr_min_stop_pct * close,
        )
        tp_dist = max(
            self.config.atr_tp1_mult * atr_pct * close,
            self.config.atr_min_tp_pct * close,
        )
        instrument = self.instrument
        sl_price = instrument.make_price(close + stop_dist)
        tp_price = instrument.make_price(close - tp_dist)
        order_list = self.order_factory.bracket(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self.create_order_qty(),
            entry_price=self._last_close_obj(),
            sl_trigger_price=sl_price,
            tp_price=tp_price,
            entry_tags=["SHORT_ENTRY"],
            sl_tags=["STOP_LOSS"],
            tp_tags=["TAKE_PROFIT_TP1"],
        )
        self.submit_order_list(order_list)
        self._open_pos_count += 1
        self._entered_short += 1
        self.log.info(
            f"SHORT entered bracket (ADX={self._adx:.1f} "
            f"regime={self._current_regime} "
            f"fast={self.fast_ema.value:.2f} slow={self.slow_ema.value:.2f})",
            LogColor.RED,
        )

    def _last_close(self):
        # Nautilus Bar.close is a Price; we treat it as float
        return self.cache.bar(self.config.bar_type).close.as_double()

    def _last_close_obj(self):
        return self.cache.bar(self.config.bar_type).close

    def _atr_pct_or_floor(self) -> float:
        atr_abs = float(self.atr.value)
        close = float(self._last_close())
        if atr_abs <= 0 or close <= 0 or math.isnan(atr_abs):
            return self.config.atr_min_stop_pct
        return atr_abs / close

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        if self.config.close_positions_on_stop:
            self.close_all_positions(self.config.instrument_id)
        self.unsubscribe_bars(self.config.bar_type)

    def on_reset(self) -> None:
        for ind in (self.fast_ema, self.slow_ema, self.atr, self.dm):
            ind.reset()
        self._adx = 0.0
        self._dx_sum = 0.0
        self._dm_count = 0
        self._prev_close = None
        self._tr_smoothed = None
        self._prev_fast = None
        self._prev_slow = None
        self._current_regime = "Neutral"
        self._regime_floor = REGIME_CIS_FLOOR["Neutral"]
        self._open_pos_count = 0
        self._skipped_adx = 0
        self._skipped_cis = 0
        self._skipped_already_in_pos = 0
        self._entered_long = 0
        self._entered_short = 0

    # ── Diagnostics (read by runner for parity_check) ─────────────────────
    def skip_summary(self) -> dict:
        return {
            "skipped_adx": self._skipped_adx,
            "skipped_cis": self._skipped_cis,
            "skipped_already_in_pos": self._skipped_already_in_pos,
            "entered_long": self._entered_long,
            "entered_short": self._entered_short,
            "open_pos_count_final": self._open_pos_count,
            "current_regime_final": self._current_regime,
            "cis_history_days": len(self._cis_by_date),
        }


# ── Smoke ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("CometCloudNautilusLongShortV1 loaded.")
    print(f"  classmethod contract:")
    print(f"    required_indicators: {CometCloudNautilusLongShortV1.required_indicators()}")
    print(f"    required_timeframes: {CometCloudNautilusLongShortV1.required_timeframes()}")
    print(f"    required_history_bars: {CometCloudNautilusLongShortV1.required_history_bars()}")
    print(f"    compliance_tag: {CometCloudNautilusLongShortV1.compliance_tag()}")
    print(f"    metrics_extra: {CometCloudNautilusLongShortV1.metrics_extra()}")
    print(f"  feature flags (env-overridable):")
    print(f"    ENABLE_ADX_GATE={ENABLE_ADX_GATE}, ENABLE_CIS_GATE={ENABLE_CIS_GATE}, "
          f"ENABLE_FUNDING_FILTER={ENABLE_FUNDING_FILTER}")
    print(f"  regime_cis_floor: {REGIME_CIS_FLOOR}")
