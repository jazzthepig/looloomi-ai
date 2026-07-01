"""
Single-run backtest: one strategy, one window, returns StrategyMetrics.

This is the canonical entry point for any non-walk-forward validation.
Used by:
- `scripts/run_research.py {strategy}` (basic run)
- The walk-forward runner (each roll = one single_run)
- The framework-validation sanity check (must match /tmp/nautilus_parity.py output)

Data path:
    /Volumes/CometCloudAI/data/ohlcv/{SYMBOL}.parquet (1h, ~2yr, ~17,520 rows)

Indicators pre-computed in pandas (Wilder smoothing matches talib.ADX output),
keyed by `bar.ts_event` (UNIX ns).

The runner is "framework-aware" — it uses the strategy_registry + baselines
tables to know what to load and what to compare against.
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.config import StrategyConfig

from src.research.data_bridge import (
    bars_from_df, build_instrument, filter_timerange, load_1h_parquet,
    precompute_indicators, resample_to_4h,
)
from src.research.metrics import StrategyMetrics, compute_metrics
from src.research.baselines import (
    BaselineMetrics, Tolerance, DEFAULT_TOLERANCE, get_baseline,
)


# ── Engine report → per-trade PnL extraction ────────────────────────────────

import re

_MONEY_RE = re.compile(r"(-?[\d.]+)\s+USDT")


def _parse_money(value) -> float:
    """Parse a Money-like value (Decimal, str 'X.XX USDT', or float) to float."""
    if hasattr(value, "as_decimal"):
        return float(value.as_decimal())
    if isinstance(value, str):
        m = _MONEY_RE.match(value)
        if m:
            return float(m.group(1))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_realized_pnls(positions_report) -> list[float]:
    """Extract per-position realized PnL (net of fees) from positions report.

    Args:
        positions_report: DataFrame from `engine.trader.generate_positions_report()`.
            Must have a `realized_pnl` column with Money-like values.

    Returns:
        List of net PnL floats (one per closed position), chronological by
        ts_opened. Includes only fully-closed positions (qty == 0).
    """
    if not hasattr(positions_report, "iterrows"):
        return []
    cols = set(positions_report.columns)
    # Filter to fully-closed positions only. The quantity column can hold
    # zero in several string variants ("0", "0.0", "0.00", "0.000"), so
    # parse numerically and check == 0. Different engine versions name
    # the column differently (qty vs quantity vs signed_qty).
    qty_col = next((c for c in ("quantity", "qty", "signed_qty") if c in cols), None)
    if qty_col is None:
        # Last-resort: if the strategy never opened a position, the report
        # has no rows at all → not an error, just no trades.
        if len(positions_report) == 0:
            return []
        # Unknown shape — log and bail so the caller can see the actual
        # columns rather than getting a generic KeyError downstream.
        logger.warning(
            f"[_extract_realized_pnls] unknown positions_report columns: "
            f"{list(positions_report.columns)}; returning empty PnL list"
        )
        return []

    def _is_zero(v) -> bool:
        try:
            return float(str(v).strip()) == 0.0
        except (TypeError, ValueError):
            return False

    closed = positions_report[positions_report[qty_col].apply(_is_zero)]
    if closed.empty:
        # Fall back to all positions if none are fully closed (shouldn't
        # happen since generate_positions_report returns historical, not
        # snapshot).
        closed = positions_report
    return [_parse_money(p) for p in closed["realized_pnl"]]


def _positions_summary(positions_report, pnls_net: list[float]) -> dict:
    """Build a trades_summary-shaped dict from a positions report."""
    if not pnls_net:
        return {"n_trades": 0}
    wins = sum(1 for p in pnls_net if p > 0)
    losses = sum(1 for p in pnls_net if p < 0)
    longs = shorts = 0
    if hasattr(positions_report, "iterrows"):
        def _is_zero(v) -> bool:
            try:
                return float(str(v).strip()) == 0.0
            except (TypeError, ValueError):
                return False
        for _, row in positions_report.iterrows():
            if not _is_zero(row.get("quantity", "")):
                continue
            entry = str(row.get("entry", ""))
            if entry == "BUY":
                longs += 1
            elif entry == "SELL":
                shorts += 1
    return {
        "n_trades": len(pnls_net),
        "n_wins": wins,
        "n_losses": losses,
        "win_rate_pct": wins / len(pnls_net) * 100.0,
        "longs": longs,
        "shorts": shorts,
        "total_pnl_net": sum(pnls_net),
        "avg_pnl_net": sum(pnls_net) / len(pnls_net),
    }

logger = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────────

@dataclass
class SingleRunConfig:
    """Configuration for one backtest window."""
    strategy_name: str                    # registry key
    pairs: list[str]                      # ["BTC", "ETH", "SOL", "BNB", "XRP"]
    timeframe: str = "4h"                 # "1h" | "4h" | "1d"
    timerange: tuple[str, str] = ("2025-05-03", "2026-03-12")
    fee: float = 0.0005
    starting_balance: float = 10_000.0
    trade_size_usd: float = 1000.0
    max_open_trades: int = 5
    # OOS holdout (gate 8)
    oos_window: Optional[tuple[str, str]] = None  # excluded from this run
    # Reporting
    baseline_name: Optional[str] = None   # for parity check
    label: str = ""                       # free-form label e.g. "in-sample" / "roll-12"


@dataclass
class SingleRunResult:
    """Result of one backtest."""
    config: SingleRunConfig
    metrics: StrategyMetrics
    trades_summary: dict
    # Parity check
    parity: Optional[dict] = None         # {metric: (delta, pass_bool)}
    elapsed_seconds: float = 0.0
    # Engine internals (for debugging)
    n_fills: int = 0
    n_open_positions: int = 0

    def summary(self) -> str:
        s = f"[{self.config.strategy_name}] {self.config.label}: {self.metrics.summary()}"
        if self.parity:
            passed = sum(1 for _, (_, ok) in self.parity.items() if ok)
            total = len(self.parity)
            s += f"   parity {passed}/{total}"
        return s


# ── Universe loading ────────────────────────────────────────────────────────

def load_universe(
    pairs: Sequence[str],
    timeframe: str,
    timerange: tuple[str, str],
) -> tuple[dict[int, dict], dict[str, str], list, list]:
    """Load OHLCV + pre-compute indicators for the given pairs/timeframe.

    Returns:
        (indicators, instrument_to_symbol, instruments, all_bars)
    """
    indicators: dict[int, dict] = {}
    instrument_to_symbol: dict[str, str] = {}
    all_bars: list = []
    instruments: list = []

    for sym in pairs:
        df1h = load_1h_parquet(sym)
        if timeframe == "1h":
            df = df1h.copy()
        elif timeframe == "4h":
            df = resample_to_4h(df1h)
        else:
            raise ValueError(f"timeframe {timeframe} not yet supported (use 1h or 4h)")
        df = filter_timerange(df, timerange[0], timerange[1])
        df = precompute_indicators(df)
        # Key indicators by bar.ts_event
        for _, row in df.iterrows():
            ts_ns = dt_to_unix_nanos(row["timestamp"].to_pydatetime())
            indicators[ts_ns] = {
                "adx_14":     float(row["adx_14"]),
                "plus_di_14": float(row["plus_di_14"]),
                "minus_di_14": float(row["minus_di_14"]),
                "ema_9":      float(row["ema_9"]),
                "ema_21":     float(row["ema_21"]),
                "ema_50":     float(row["ema_50"]),
                "atr":        float(row["atr"]),
                "atr_pct":    float(row["atr_pct"]) if not pd.isna(row["atr_pct"]) else 0.02,
                "rsi":        float(row["rsi"]),
                "roll_min_20": float(row["roll_min_20"]) if not pd.isna(row["roll_min_20"]) else float(row["low"]),
                "roll_max_20": float(row["roll_max_20"]) if not pd.isna(row["roll_max_20"]) else float(row["high"]),
            }
        # Build instrument + bars
        inst = build_instrument(sym)
        instrument_to_symbol[inst.id.value] = sym
        instruments.append(inst)
        bars = bars_from_df(inst, df)
        all_bars.extend(bars)
        logger.info(f"  {sym}: {len(bars)} bars ({df.iloc[0]['timestamp']} → {df.iloc[-1]['timestamp']})")

    return indicators, instrument_to_symbol, instruments, all_bars


# ── Engine setup ────────────────────────────────────────────────────────────

def setup_engine(
    strategy_cls,
    indicators: dict[int, dict],
    instrument_to_symbol: dict[str, str],
    instruments: list,
    all_bars: list,
    cfg: SingleRunConfig,
) -> tuple[BacktestEngine, Any]:
    """Build and add the strategy to a fresh BacktestEngine.

    Returns (engine, strategy_instance).
    """
    engine_config = BacktestEngineConfig(
        trader_id=f"{cfg.strategy_name.upper()}-SINGLE",
        logging=LoggingConfig(log_level="WARN"),
    )
    engine = BacktestEngine(config=engine_config)
    engine.add_venue(
        venue=Venue("BINANCE"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=None,
        starting_balances=[Money(cfg.starting_balance, USDT)],
    )
    for inst in instruments:
        engine.add_instrument(inst)
    engine.add_data(all_bars)

    strategy = strategy_cls(config=StrategyConfig())
    strategy.indicators = indicators
    strategy.instrument_to_symbol = instrument_to_symbol
    # Set common params — strategy may use any subset
    strategy.trade_size_usd = cfg.trade_size_usd
    strategy.max_open_trades = cfg.max_open_trades
    if hasattr(strategy, "cis_history_dir"):
        # Default to absolute path on Mac Mini
        strategy.cis_history_dir = "/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/"
    engine.add_strategy(strategy)
    return engine, strategy


# ── Single run ──────────────────────────────────────────────────────────────

def run_single(cfg: SingleRunConfig) -> SingleRunResult:
    """Execute one backtest with the given configuration.

    Args:
        cfg: SingleRunConfig with strategy name, pairs, timeframe, etc.

    Returns:
        SingleRunResult with metrics + optional parity check vs baseline.
    """
    from src.research.strategy_registry import get_strategy
    meta = get_strategy(cfg.strategy_name)
    strategy_cls = meta.cls

    t0 = time.time()

    # 1. Load data
    logger.info(f"[{cfg.strategy_name}] loading {len(cfg.pairs)} pairs, "
                f"tf={cfg.timeframe}, range={cfg.timerange}")
    indicators, instrument_to_symbol, instruments, all_bars = load_universe(
        cfg.pairs, cfg.timeframe, cfg.timerange,
    )

    # 2. Setup engine
    engine, strategy = setup_engine(
        strategy_cls, indicators, instrument_to_symbol,
        instruments, all_bars, cfg,
    )

    # 3. Run
    logger.info(f"[{cfg.strategy_name}] running engine ({len(all_bars)} bars)")
    engine.run()

    # 4. Extract per-position PnLs from the engine's positions report.
    #
    # We use `generate_positions_report()` rather than pairing fills
    # ourselves because the engine's NETTING OMS groups fills by
    # instrument (not by round-trip), and a strategy can open a new
    # position before the previous one closes. Hand-rolled pairing
    # (e.g. fills_to_trades) can drop those concurrent positions.
    #
    # The engine's `realized_pnl` is GROSS - entry commission - exit
    # commission, i.e. the net PnL per closed position in quote ccy.
    positions_report = engine.trader.generate_positions_report()
    pnls_net = _extract_realized_pnls(positions_report)
    fills = engine.trader.generate_order_fills_report()  # for n_fills counter

    # 5. Compute metrics
    # Years = actual time elapsed in the backtest window, not bars × timeframe
    # (n_bars is summed across all pairs, so it would inflate by N×).
    start_dt = dt.datetime.fromisoformat(cfg.timerange[0])
    end_dt = dt.datetime.fromisoformat(cfg.timerange[1])
    days = (end_dt - start_dt).days
    years = days / 365.0

    metrics = compute_metrics(
        pnls_net,
        initial_balance=cfg.starting_balance,
        timeframe=cfg.timeframe,
        years=years,
    )
    # trades_summary is best-effort; we don't have a TradePnl list any more.
    # Build it from the engine's positions report.
    summary = _positions_summary(positions_report, pnls_net)

    # 6. Parity check vs baseline (if specified)
    parity = None
    if cfg.baseline_name:
        baseline = get_baseline(cfg.baseline_name)
        ours = {
            "n_trades":    metrics.n_trades,
            "cagr_pct":    metrics.cagr_pct,
            "max_dd_pct":  metrics.max_drawdown_pct,
            "win_rate_pct": metrics.win_rate_pct,
            "sharpe":      metrics.sharpe,
        }
        parity = DEFAULT_TOLERANCE.check(ours, baseline)

    # 7. Engine internals
    n_open = sum(1 for p in engine.cache.positions() if not p.is_closed)

    elapsed = time.time() - t0

    return SingleRunResult(
        config=cfg,
        metrics=metrics,
        trades_summary=summary,
        parity=parity,
        elapsed_seconds=elapsed,
        n_fills=len(fills),
        n_open_positions=n_open,
    )


# ── Self-test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Smoke test: load LS-V4 from /tmp/, run via framework
    sys.path.insert(0, "/tmp")
    from nautilus_ls_v4 import CometCloudLongShortV4Nautilus

    from src.research.strategy_registry import register_strategy
    register_strategy(
        "ls_v4_smoke",
        description="LS-V4 port (smoke test of single_run)",
        required_timeframes=("4h",),
    )(CometCloudLongShortV4Nautilus)

    cfg = SingleRunConfig(
        strategy_name="ls_v4_smoke",
        pairs=["BTC", "ETH", "SOL"],
        timeframe="4h",
        timerange=("2025-05-03", "2026-03-12"),
        fee=0.0005,
        starting_balance=10_000.0,
        trade_size_usd=1000.0,
        max_open_trades=5,
        baseline_name="ls_v4",
        label="smoke-test",
    )
    result = run_single(cfg)
    print()
    print("=" * 70)
    print(result.summary())
    print("=" * 70)
    if result.parity:
        print("Parity:")
        for k, (delta, ok) in result.parity.items():
            mark = "PASS" if ok else "FAIL"
            print(f"  {k:<12} delta={delta:+.2f}  {mark}")
