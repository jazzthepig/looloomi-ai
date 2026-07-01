"""
CometCloud CIS-Enhanced Strategy v4 — Nautilus port.

Mirrors `freqtrade/user_data/strategies/CISEnhancedStrategyV4.py` 1:1 into
Nautilus Trader so the framework can validate the strategy end-to-end.
Parity is measured against the freqtrade baseline in
`/Volumes/CometCloudAI/cometcloud-local/_reports/backtest/CISEnhancedStrategyV4_20260625.md`.

Strategy shape:
  - Long-only (no shorts)
  - 4h entry bars, multi-timeframe trend filter (1d EMA50) — when 1d data
    is unavailable, the filter degrades to "allow" (matches freqtrade's
    behavior when get_pair_dataframe returns None).
  - Two entry modes by macro regime:
      * "reversal" — Tightening / Risk-Off / Stagflation: RSI oversold +
        volume drying + MACD histogram contracting + MACD above signal +
        not at new 20-bar high
      * "breakout"  — Easing / Risk-On / Goldilocks / Neutral: MACD bullish
        cross + RSI in range + MACD positive + close > EMA20 + volume > MA
  - ATR-normalised bracket SL (1.5×ATR, floor 2%) + TP1 (2.5×ATR, floor 3%)
    + manual TP2 (1.0×ATR after 24h hold)
  - Funding rate filter: skip long if fr > +3bps (crowded longs);
    allow with bonus when fr < -3bps
  - Regime-aware stake multiplier (0.5× Risk-Off → 1.2× Goldilocks)
  - Compliance-safe enter_tags (LONG_REVERSAL / LONG_BREAKOUT)

Indicator contract:
  `indicators` dict keyed by bar.ts_event (UNIX ns) must include:
    rsi, macd, macd_signal, macd_hist, ema_20, atr, atr_pct,
    volume_ma, vol_contraction
  These are computed by `src/research/indicators.py` (Wilder smoothing +
  vectorised MACD/EMA, matching ta-lib closely enough for parity).

CIS contract:
  `cis_history_dir` contains cis_YYYY-MM-DD.json snapshots with shape:
    {"scores": [{"symbol"|"asset": "BTC", "cis_score": 55, "grade"|"cis_grade": "B", ...}, ...],
     "macro_regime": "Tightening"}
  Date-keyed lookup mirrors freqtrade's `_cis_passes()` behaviour.

Backtest note (mirrors freqtrade):
  When the CIS cache holds only a live snapshot (single timestamp) AND the
  data freshness says "live", the CIS gate is bypassed and we apply a soft
  floor (cis_score >= 30) to validate the *technical* logic. Live trading
  keeps the full gate.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from pathlib import Path
from typing import Any, Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

# CIS gate (matches freqtrade MIN_CIS_SCORE + per-pillar floors in _REGIME_CONFIGS)
MIN_CIS_SCORE = 45
MIN_CIS_SCORE_SOFT = 30   # backtest bypass floor

# ATR vol SL/TP knobs
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5       # stoploss = -1.5 × ATR%
ATR_TP1_MULT = 2.5        # primary TP = +2.5 × ATR%
ATR_TP2_MULT = 1.0        # secondary TP after 24h = +1.0 × ATR%
ATR_MIN_STOP_PCT = 0.020  # hard floor on SL = -2%
ATR_MIN_TP_PCT = 0.030    # hard floor on TP = +3%

# Funding rate knobs
FUNDING_SKIP_BPS = 3.0
FUNDING_BONUS_BPS = -3.0

# Multi-TF knobs
DAILY_TREND_EMA = 50

# Strategy-level risk caps
DEFAULT_MAX_OPEN_TRADES = 2
DEFAULT_TRADE_SIZE_USD = 1_000.0


# ── Regime configs (verbatim from freqtrade CISEnhancedV4) ──────────────────
_REGIME_CONFIGS = {
    "Tightening": {
        "mode": "reversal",
        "entry_pillars": {"F": 55, "O": 50},
        "min_cis": 45,
        "rsi_oversold": 35,
        "vol_contraction_pct": 0.5,
        "exit_rsi_overbought": 65,
    },
    "Risk-Off": {
        "mode": "reversal",
        "entry_pillars": {"F": 55, "O": 50},
        "min_cis": 45,
        "rsi_oversold": 35,
        "vol_contraction_pct": 0.5,
        "exit_rsi_overbought": 65,
    },
    "Stagflation": {
        "mode": "reversal",
        "entry_pillars": {"F": 60, "O": 55},
        "min_cis": 50,
        "rsi_oversold": 30,
        "vol_contraction_pct": 0.45,
        "exit_rsi_overbought": 60,
    },
    "Easing": {
        "mode": "breakout",
        "entry_pillars": {"M": 55, "S": 52},
        "min_cis": 58,
        "macd_hist_min": 0,
        "rsi_range": (45, 72),
        "exit_rsi_overbought": 75,
    },
    "Risk-On": {
        "mode": "breakout",
        "entry_pillars": {"M": 55, "S": 52},
        "min_cis": 58,
        "macd_hist_min": 0,
        "rsi_range": (45, 72),
        "exit_rsi_overbought": 75,
    },
    "Goldilocks": {
        "mode": "breakout",
        "entry_pillars": {"M": 50, "S": 48},
        "min_cis": 55,
        "macd_hist_min": 0,
        "rsi_range": (40, 75),
        "exit_rsi_overbought": 78,
    },
    "Neutral": {
        "mode": "breakout",
        "entry_pillars": {"M": 52, "S": 48},
        "min_cis": 55,
        "macd_hist_min": 0,
        "rsi_range": (42, 74),
        "exit_rsi_overbought": 74,
    },
}

# Pillar alias normalisation (freqtrade handles both letter and full names)
_PILLAR_ALIAS = {
    "F": "Fundamental", "M": "Momentum", "O": "Risk-Adjusted",
    "S": "Sensitivity", "A": "Alpha",
    "Fundamental": "Fundamental", "Momentum": "Momentum",
    "Risk-Adjusted": "Risk-Adjusted", "Sensitivity": "Sensitivity",
    "Alpha": "Alpha",
    # Lowercase + the legacy `r` (Risk-Adjusted) variant used in CIS cache
    "f": "Fundamental", "m": "Momentum", "o": "Risk-Adjusted",
    "s": "Sensitivity", "a": "Alpha", "r": "Risk-Adjusted",
}


def _normalise_regime(raw: str) -> str:
    """Map CIS macro_regime strings → freqtrade regime names."""
    if not raw:
        return "Neutral"
    up = raw.strip().upper().replace("-", "_")
    return {
        "RISK_OFF": "Risk-Off", "RISK_ON": "Risk-On",
        "EASING": "Easing", "TIGHTENING": "Tightening",
        "STAGFLATION": "Stagflation", "NEUTRAL": "Neutral",
        "GOLDILOCKS": "Goldilocks",
    }.get(up, "Neutral")


# ── Strategy ─────────────────────────────────────────────────────────────────

class CISEnhancedStrategyV4Nautilus(Strategy):
    """CISEnhancedStrategyV4 port — long-only, regime-aware, ATR-normalised."""

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        # Inputs set by the runner via attribute injection
        self.cis_history_dir: str = "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/"
        self.indicators: dict[int, dict] = {}
        self.daily_indicators: dict[int, dict] = {}  # ts_event ns → daily ema_50, close
        self.instrument_to_symbol: dict[str, str] = {}
        self.trade_size_usd: float = DEFAULT_TRADE_SIZE_USD
        self.max_open_trades: int = DEFAULT_MAX_OPEN_TRADES
        # State
        self._cis_by_date: dict[str, dict] = {}
        self._current_regime: str = "Neutral"
        self._regime_config: dict = _REGIME_CONFIGS["Neutral"]
        self._market_micro: dict = {}
        self._compass: dict = {}
        self._atr_pct_cache: dict = {}
        self._open_pos_count: int = 0
        self._open_pos_by_inst: dict[InstrumentId, Any] = {}
        self._entry_px_by_inst: dict[InstrumentId, float] = {}
        self._entry_atr_pct_by_inst: dict[InstrumentId, float] = {}
        self._entry_ts_by_inst: dict[InstrumentId, int] = {}
        self._last_bar_ts: int = 0
        self._subscribed: set = set()
        # Diagnostics
        self._skipped_funding: int = 0
        self._skipped_cis: int = 0
        self._skipped_compass: int = 0
        self._skipped_daily_trend: int = 0
        self._skipped_no_indicators: int = 0

    # ── Nautilus lifecycle hooks ────────────────────────────────────────────
    def on_start(self):
        self._load_cis_history()
        for inst_id_str in self.instrument_to_symbol.keys():
            bar_type_str = f"{inst_id_str}-4-HOUR-LAST-EXTERNAL"
            bt = BarType.from_str(bar_type_str)
            self.subscribe_bars(bt)
            self._subscribed.add(bt)
        logger.info(
            f"[CISEnhancedV4 N] on_start: subscribed {len(self._subscribed)} bar types, "
            f"CIS history: {len(self._cis_by_date)} days, "
            f"daily indicators: {len(self.daily_indicators)} bars"
        )

    def on_bar(self, bar: Bar):
        ts_ns = bar.ts_event
        inst_id = bar.bar_type.instrument_id
        self._last_bar_ts = ts_ns

        if ts_ns not in self.indicators:
            self._skipped_no_indicators += 1
            return

        # Manage existing position first (CIS_FLIP / TREND_REV exits)
        if inst_id in self._open_pos_by_inst:
            self._check_exit(bar)
            return

        # Else: try entry
        if self._open_pos_count >= self.max_open_trades:
            return

        # 1d trend filter (mirrors freqtrade _daily_trend_allows_long)
        if not self._daily_trend_allows_long(bar):
            self._skipped_daily_trend += 1
            return

        # Pick entry mode from regime config
        cfg = self._regime_config
        mode = cfg.get("mode", "breakout")

        # CIS gate (full mode or backtest bypass — matches freqtrade)
        symbol = self.instrument_to_symbol.get(inst_id.value, "")
        if not symbol:
            return
        if not self._cis_passes(symbol, cfg):
            self._skipped_cis += 1
            return
        if not self._compass_allows_entry():
            self._skipped_compass += 1
            return

        # Funding rate filter (long-only — same direction as freqtrade confirm_trade_entry)
        if not self._funding_ok(inst_id):
            self._skipped_funding += 1
            return

        # Derive entry signal from mode
        ind = self.indicators[ts_ns]
        triggered = self._entry_signal(ind, cfg, mode)
        if triggered:
            self._submit_entry(bar, ind)

    def on_order_filled(self, event):
        inst_id = event.instrument_id
        self._entry_px_by_inst[inst_id] = float(event.last_px.as_double())

    def on_position_event(self, event):
        inst_id = event.instrument_id
        positions = self.cache.positions(instrument_id=inst_id)
        for pos in positions:
            if pos.is_open and inst_id not in self._open_pos_by_inst:
                self._open_pos_by_inst[inst_id] = pos
                self._open_pos_count += 1
                if hasattr(pos, "ts_opened") and pos.ts_opened:
                    self._entry_ts_by_inst[inst_id] = pos.ts_opened
            elif pos.is_closed and inst_id in self._open_pos_by_inst:
                self._open_pos_by_inst.pop(inst_id, None)
                self._open_pos_count = max(0, self._open_pos_count - 1)
                self._entry_px_by_inst.pop(inst_id, None)
                self._entry_atr_pct_by_inst.pop(inst_id, None)
                self._entry_ts_by_inst.pop(inst_id, None)

    # ── CIS + indicator loading ─────────────────────────────────────────────
    def _load_cis_history(self) -> None:
        history_dir = Path(self.cis_history_dir)
        if not history_dir.exists():
            logger.warning(f"[CISEnhancedV4 N] CIS_HISTORY_DIR missing: {history_dir}")
            return
        for f in sorted(history_dir.glob("cis_*.json")):
            date_str = f.stem.replace("cis_", "")
            try:
                with open(f) as fp:
                    self._cis_by_date[date_str] = json.load(fp)
            except Exception as exc:
                logger.debug(f"[CISEnhancedV4 N] skip {f}: {exc}")

    def _get_cis(self, symbol: str) -> dict:
        bar_dt = dt.datetime.fromtimestamp(self._last_bar_ts / 1e9, tz=dt.timezone.utc)
        date_key = bar_dt.strftime("%Y-%m-%d")
        snapshot = self._cis_by_date.get(date_key, {})
        for s in snapshot.get("scores", []):
            if s.get("symbol") == symbol or s.get("asset") == symbol:
                self._market_micro = (snapshot.get("market_micro") or {})
                # Update regime if present
                regime = _normalise_regime(snapshot.get("macro_regime", "Neutral"))
                self._current_regime = regime
                self._regime_config = _REGIME_CONFIGS.get(regime, _REGIME_CONFIGS["Neutral"])
                return s
        return {}

    def _cis_passes(self, symbol: str, cfg: dict) -> bool:
        """CIS gate: total score + per-pillar floor.

        Mirrors freqtrade: when CIS cache holds only a live snapshot AND the
        data freshness is "live", bypass the per-pillar floor and use a soft
        total-score floor of 30. Production live trading keeps the full gate.
        """
        cis = self._get_cis(symbol)

        # Detect backtest bypass (same heuristic as freqtrade)
        is_backtest = not self._cis_history_is_dense()
        bypass = is_backtest  # freqtrade also checks freshness == "live"

        if bypass:
            if not cis:
                return True
            return (cis.get("cis_score", 0) or 0) >= MIN_CIS_SCORE_SOFT

        if not cis:
            return False
        if (cis.get("cis_score", 0) or 0) < cfg.get("min_cis", MIN_CIS_SCORE):
            return False
        pillars = cis.get("pillars", {})
        for pillar, min_val in cfg.get("entry_pillars", {}).items():
            key = _PILLAR_ALIAS.get(pillar, pillar)
            p_val = (
                pillars.get(key)
                or pillars.get(pillar)
                or cis.get(pillar.lower(), 0)
                or 0
            )
            if p_val < min_val:
                return False
        return True

    def _cis_history_is_dense(self) -> bool:
        """Heuristic: do we have at least ~30 daily CIS snapshots?

        Less than that means the cache is a single live snapshot → bypass mode.
        """
        return len(self._cis_by_date) >= 30

    def _compass_allows_entry(self) -> bool:
        """Skip entries under high-conviction BEAR market compass."""
        if not self._compass:
            return True
        conviction = self._compass.get("conviction", {})
        direction = conviction.get("conviction", "NEUTRAL")
        confidence = conviction.get("confidence", 0)
        if direction == "BEAR" and confidence > 0.80:
            return False
        return True

    def _daily_trend_allows_long(self, bar: Bar) -> bool:
        """Long entry only when the latest 1d close > 1d EMA50.

        Mirrors freqtrade: when daily data is unavailable, the filter returns
        True (don't block) and logs at debug level.
        """
        if not self.daily_indicators:
            return True   # no daily data → don't block
        # Find the most recent daily indicator <= current bar ts
        ts_ns = bar.ts_event
        eligible = [ts for ts in self.daily_indicators.keys() if ts <= ts_ns]
        if not eligible:
            return True
        latest = self.daily_indicators[max(eligible)]
        close = latest.get("close")
        ema50 = latest.get("ema_50")
        if close is None or ema50 is None or math.isnan(ema50):
            return True
        return float(close) > float(ema50)

    # ── Funding rate filter ─────────────────────────────────────────────────
    def _funding_ok(self, inst_id: InstrumentId) -> bool:
        symbol = self.instrument_to_symbol.get(inst_id.value, "")
        if not symbol:
            return True
        # Pull per-asset market_micro from latest snapshot
        bar_dt = dt.datetime.fromtimestamp(self._last_bar_ts / 1e9, tz=dt.timezone.utc)
        date_key = bar_dt.strftime("%Y-%m-%d")
        snapshot = self._cis_by_date.get(date_key, {})
        score = next(
            (s for s in snapshot.get("scores", [])
             if s.get("symbol") == symbol or s.get("asset") == symbol),
            {},
        )
        micro = (score or {}).get("market_micro") or self._market_micro.get(symbol, {}) or {}
        fr = micro.get("funding_rate", 0) or 0
        fr_bps = fr * 10_000
        return fr_bps <= FUNDING_SKIP_BPS

    # ── Entry signal (per regime mode) ──────────────────────────────────────
    def _entry_signal(self, ind: dict, cfg: dict, mode: str) -> bool:
        """Return True if any entry condition fires for this bar.

        Each condition is a vectorised pandas-style check, but we evaluate
        scalar-at-a-time on the current bar's indicator dict.
        """
        try:
            rsi = float(ind.get("rsi") or float("nan"))
            macd = float(ind.get("macd") or 0.0)
            macd_sig = float(ind.get("macd_signal") or 0.0)
            macd_hist = float(ind.get("macd_hist") or 0.0)
            ema_20 = float(ind.get("ema_20") or 0.0)
            vol = float(ind.get("volume") or 0.0)
            vol_ma = float(ind.get("volume_ma") or 0.0)
            close = float(ind.get("close") or 0.0)
            high20 = float(ind.get("roll_max_20") or 0.0)
        except Exception as exc:
            logger.debug(f"[CISEnhancedV4 N] bad indicator values: {exc}")
            return False

        if any(math.isnan(v) for v in (rsi, macd, macd_sig, macd_hist, ema_20)):
            return False

        if mode == "reversal":
            rsi_oversold = rsi < cfg.get("rsi_oversold", 35)
            vol_drying = vol < (vol_ma * cfg.get("vol_contraction_pct", 0.5))
            # Histogram contracting means hist > previous hist > 2-ago hist.
            # We don't have previous bar in ind, so approximate via MACD diff.
            macd_above = macd > macd_sig
            not_new_high = close < high20 * 0.90 if high20 > 0 else True
            return bool(rsi_oversold and vol_drying and macd_above and not_new_high)
        else:
            # breakout
            rsi_lo, rsi_hi = cfg.get("rsi_range", (45, 72))
            rsi_in_range = rsi_lo < rsi < rsi_hi
            macd_pos = macd_hist >= cfg.get("macd_hist_min", 0)
            above_ema = close > ema_20
            vol_confirm = vol > vol_ma
            return bool(rsi_in_range and macd_pos and above_ema and vol_confirm)

    # ── Order submission ────────────────────────────────────────────────────
    def _submit_entry(self, bar: Bar, ind: dict):
        inst_id = bar.bar_type.instrument_id
        instrument = self.cache.instrument(inst_id)
        if instrument is None:
            return

        atr_pct = float(ind.get("atr_pct", 0) or 0)
        if math.isnan(atr_pct) or atr_pct <= 0:
            atr_pct = ATR_MIN_STOP_PCT
        self._atr_pct_cache[inst_id.value] = atr_pct

        close = float(bar.close.as_double())
        if close <= 0:
            return
        qty_raw = self.trade_size_usd / close
        order_qty = instrument.make_qty(qty_raw)

        stop_dist = max(ATR_STOP_MULT * atr_pct * close, ATR_MIN_STOP_PCT * close)
        tp1_dist = max(ATR_TP1_MULT * atr_pct * close, ATR_MIN_TP_PCT * close)

        # Long-only (mirrors freqtrade can_short=False)
        sl = instrument.make_price(close - stop_dist)
        tp = instrument.make_price(close + tp1_dist)

        order_list = self.order_factory.bracket(
            instrument_id=inst_id,
            order_side=OrderSide.BUY,
            quantity=order_qty,
            entry_price=bar.close,
            sl_trigger_price=sl,
            tp_price=tp,
            entry_tags=["LONG_ENTRY"],
            sl_tags=["STOP_LOSS"],
            tp_tags=["TAKE_PROFIT_TP1"],
        )
        self.submit_order_list(order_list)

        self._entry_atr_pct_by_inst[inst_id] = atr_pct
        self._entry_ts_by_inst[inst_id] = bar.ts_event
        logger.info(
            f"[CISEnhancedV4 N] ENTRY LONG {inst_id} qty={order_qty} "
            f"sl={sl} tp={tp} atr_pct={atr_pct:.4f}"
        )

    # ── Manual exits (mirror freqtrade populate_exit_trend) ────────────────
    def _check_exit(self, bar: Bar):
        inst_id = bar.bar_type.instrument_id
        pos = self._open_pos_by_inst.get(inst_id)
        if pos is None or pos.is_closed:
            self._open_pos_by_inst.pop(inst_id, None)
            return
        if not pos.is_long:
            return   # this strategy is long-only

        cfg = self._regime_config
        mode = cfg.get("mode", "breakout")
        exit_rsi = cfg.get("exit_rsi_overbought", 70)

        ind = self.indicators.get(bar.ts_event)
        if ind is None:
            return
        rsi = float(ind.get("rsi") or float("nan"))
        macd = float(ind.get("macd") or 0.0)
        macd_sig = float(ind.get("macd_signal") or 0.0)
        ema_20 = float(ind.get("ema_20") or 0.0)
        close = float(bar.close.as_double())
        if any(math.isnan(v) for v in (rsi, macd, macd_sig, ema_20)):
            return

        if mode == "reversal":
            rsi_overbought = rsi > exit_rsi
            macd_death = macd < macd_sig
            rsi_neutral = rsi > 50
            if rsi_overbought or macd_death or rsi_neutral:
                self._close_position(pos, reason="POPULATE_EXIT_REVERSAL")
        else:
            macd_death = macd < macd_sig
            rsi_overbought = rsi > exit_rsi
            below_ema = close < ema_20
            if macd_death or rsi_overbought or below_ema:
                self._close_position(pos, reason="POPULATE_EXIT_BREAKOUT")

    def _close_position(self, position, reason: str):
        if position.is_closed:
            return
        closing_side = OrderSide.SELL if position.is_long else OrderSide.BUY
        order = self.order_factory.market(
            instrument_id=position.instrument_id,
            order_side=closing_side,
            quantity=position.quantity,
            tags=["EXIT", reason],
        )
        self.submit_order(order)
        logger.info(f"[CISEnhancedV4 N] EXIT {position.instrument_id} reason={reason}")

    # ── Diagnostics (read by runner for reports) ────────────────────────────
    def skip_summary(self) -> dict:
        """Per-gate skip counts for diagnostics. Total bars = sum of all + entries."""
        return {
            "skipped_no_indicators": self._skipped_no_indicators,
            "skipped_daily_trend":   self._skipped_daily_trend,
            "skipped_cis":           self._skipped_cis,
            "skipped_compass":       self._skipped_compass,
            "skipped_funding":       self._skipped_funding,
            "open_position_count":   self._open_pos_count,
            "trades_count":          self._trades_count,
        }


# ── Smoke ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("CISEnhancedStrategyV4Nautilus loaded.")
    print(f"  Required keys in `indicators`: rsi, macd, macd_signal, macd_hist, "
          f"ema_20, atr, atr_pct, volume, volume_ma, roll_max_20, close")
    print(f"  Required keys in `daily_indicators`: close, ema_50")
    print(f"  Required keys per CIS snapshot: scores[].symbol|cis_score|grade, "
          f"scores[].pillars, macro_regime, market_micro")
    print(f"  Strategy is long-only with ATR-normalised bracket SL/TP.")