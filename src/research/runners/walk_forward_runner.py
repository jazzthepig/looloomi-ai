"""
Walk-forward runner — orchestrate N train→test rolls, aggregate OOS metrics.

Each roll is one SingleRunConfig with a sub-window of the backtest period.
The OOS aggregate is the production-grade number; IS is shown for
overfit detection (decay ratio, gate 3 of STRATEGY_VALIDATION.md).

Data flow (matches single_run.py):
  1. compute_window_boundaries → N × (train_start, train_end, test_start, test_end)
  2. for each roll → run_single(RollConfig with sub-timerange) → metrics
  3. collect per-roll IS + OOS metrics → WalkForwardResult
  4. compute decay ratio (OOS_sharpe / IS_sharpe)
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from src.research.metrics import (
    StrategyMetrics, compute_metrics, sharpe_ratio, sortino_ratio,
    max_drawdown, build_equity_curve,
)
from src.research.walk_forward import (
    WalkForwardConfig, WalkForwardRoll, WalkForwardResult,
    compute_window_boundaries, compute_decay_ratio,
    aggregate_walk_forward,
)
from src.research.runners.single_run import (
    SingleRunConfig, SingleRunResult, run_single,
    load_universe, setup_engine,
)
from src.research.runners.fills_to_pnls import fills_to_trades, trades_to_pnls

logger = logging.getLogger(__name__)


@dataclass
class RollConfig(SingleRunConfig):
    """Like SingleRunConfig but identifies a single roll."""
    roll_id: int = -1
    is_oos: bool = False     # True → OOS metrics; False → IS metrics


def run_walk_forward(
    strategy_name: str,
    pairs: Sequence[str],
    timeframe: str,
    full_timerange: tuple[str, str],
    wf_cfg: WalkForwardConfig,
    *,
    fee: float = 0.0005,
    starting_balance: float = 10_000.0,
    trade_size_usd: float = 1000.0,
    max_open_trades: int = 5,
    label: str = "",
) -> WalkForwardResult:
    """Run the walk-forward validation for a strategy.

    Each roll:
      - Pre-loads UNIVERSE for the FULL timerange once (one parquet read)
      - Runs the strategy TWICE: once on train window (IS), once on test window (OOS)
      - For multi-pair strategies, all pairs use the SAME timerange (only one bar
        stream per pair for the full period).

    Args:
        strategy_name: registry key (see strategy_registry).
        pairs: pair symbols e.g. ["BTC", "ETH"].
        timeframe: "1h" | "4h" | "1d".
        full_timerange: (start, end) inclusive-exclusive YYYY-MM-DD strings.
        wf_cfg: WalkForwardConfig with train/test bar counts and n_rolls.
        fee: taker fee (default 0.0005).
        starting_balance: USDT.
        trade_size_usd: per-trade notional.
        max_open_trades: concurrent position cap.
        label: free-form label for reporting.

    Returns:
        WalkForwardResult with all rolls + aggregate OOS/IS + decay.

    Note: this implementation loads the full timerange ONCE per pair
    (faster than per-roll), then runs two engine.run() calls per roll
    (train and test). The engine supports arbitrary timerange filtering
    via bars, so each sub-window just uses a subset of bars.
    """
    t0 = time.time()
    roll_cfg_template = SingleRunConfig(
        strategy_name=strategy_name,
        pairs=list(pairs),
        timeframe=timeframe,
        timerange=full_timerange,
        fee=fee,
        starting_balance=starting_balance,
        trade_size_usd=trade_size_usd,
        max_open_trades=max_open_trades,
    )
    strategy_cls = _resolve_strategy_cls(strategy_name)

    # Load universe ONCE (full timerange) and reuse across rolls.
    indicators, i2s, instruments, all_bars = load_universe(
        list(pairs), timeframe, full_timerange,
    )
    n_bars_per_pair = len(all_bars) // max(len(pairs), 1)
    logger.info(
        f"Loaded universe: {len(pairs)} pairs × {n_bars_per_pair} bars = "
        f"{len(all_bars)} total"
    )

    boundaries = compute_window_boundaries(
        total_bars=n_bars_per_pair, cfg=wf_cfg,
    )
    if not boundaries:
        logger.warning("no valid rolls — insufficient data")
        return WalkForwardResult(config=wf_cfg, rolls=[])

    # Identify bar indices for boundary → date (so we can pass sub-timeranges)
    bar_starts = sorted({bar.ts_event for bar in all_bars})
    bar0_ns = bar_starts[0]
    bar_step_ns = (
        (bar_starts[1] - bar_starts[0]) if len(bar_starts) > 1 else 4 * 3600 * 1_000_000_000
    )

    def _ns_to_date(ns: int) -> str:
        ts = dt.datetime.utcfromtimestamp(ns / 1_000_000_000)
        return ts.strftime("%Y-%m-%d")

    def _bar_idx_to_date(idx: int) -> str:
        return _ns_to_date(bar0_ns + idx * bar_step_ns)

    logger.info(f"Computing {len(boundaries)} rolls over {n_bars_per_pair} bars/pair")

    rolls: list[WalkForwardRoll] = []

    for i, (train_s, train_e, test_s, test_e) in enumerate(boundaries):
        train_start_date = _bar_idx_to_date(train_s)
        train_end_date = _bar_idx_to_date(train_e)
        test_start_date = _bar_idx_to_date(test_s)
        test_end_date = _bar_idx_to_date(test_e)
        logger.info(
            f"Roll {i}: train [{train_start_date}:{train_end_date}]  "
            f"test [{test_start_date}:{test_end_date}]"
        )

        # IS run
        is_cfg = SingleRunConfig(
            strategy_name=strategy_name,
            pairs=list(pairs),
            timeframe=timeframe,
            timerange=(train_start_date, train_end_date),
            fee=fee, starting_balance=starting_balance,
            trade_size_usd=trade_size_usd, max_open_trades=max_open_trades,
            label=f"roll-{i}-IS",
        )
        is_result = run_single(is_cfg)
        # OOS run
        oos_cfg = SingleRunConfig(
            strategy_name=strategy_name,
            pairs=list(pairs),
            timeframe=timeframe,
            timerange=(test_start_date, test_end_date),
            fee=fee, starting_balance=starting_balance,
            trade_size_usd=trade_size_usd, max_open_trades=max_open_trades,
            label=f"roll-{i}-OOS",
        )
        oos_result = run_single(oos_cfg)

        roll = WalkForwardRoll(
            roll_id=i,
            train_start=train_s, train_end=train_e,
            test_start=test_s, test_end=test_e,
            is_sharpe=is_result.metrics.sharpe,
            is_cagr_pct=is_result.metrics.cagr_pct,
            is_max_dd_pct=is_result.metrics.max_drawdown_pct,
            is_n_trades=is_result.metrics.n_trades,
            oos_sharpe=oos_result.metrics.sharpe,
            oos_cagr_pct=oos_result.metrics.cagr_pct,
            oos_max_dd_pct=oos_result.metrics.max_drawdown_pct,
            oos_n_trades=oos_result.metrics.n_trades,
            oos_win_rate_pct=oos_result.metrics.win_rate_pct,
        )
        rolls.append(roll)

    # Aggregate
    agg = aggregate_walk_forward(rolls)
    decay_ratio, decay_status = compute_decay_ratio(
        is_sharpe=agg["is_sharpe_mean"],
        oos_sharpe=agg["oos_sharpe_mean"],
    )

    elapsed = time.time() - t0
    logger.info(f"Walk-forward complete in {elapsed:.1f}s — {len(rolls)} rolls")

    return WalkForwardResult(
        config=wf_cfg,
        rolls=rolls,
        oos_sharpe_mean=agg["oos_sharpe_mean"],
        oos_sharpe_std=agg["oos_sharpe_std"],
        oos_cagr_mean=agg["oos_cagr_mean"],
        oos_max_dd_max=agg["oos_max_dd_max"],
        oos_total_pnl=agg["oos_total_pnl"],
        oos_n_trades_total=agg["oos_n_trades_total"],
        is_sharpe_mean=agg["is_sharpe_mean"],
        is_cagr_mean=agg["is_cagr_mean"],
        decay_ratio=decay_ratio,
        decay_status=decay_status,
    )


def _resolve_strategy_cls(strategy_name: str):
    """Resolve strategy class from registry. Defensive helper."""
    from src.research.strategy_registry import get_strategy
    meta = get_strategy(strategy_name)
    return meta.cls


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Sanity: walk a registry-only trivial strategy (real LS-V4 takes ~30s)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    import sys
    sys.path.insert(0, "/tmp")
    from src.research.strategy_registry import register_strategy
    from nautilus_ls_v4 import CometCloudLongShortV4Nautilus
    register_strategy("ls_v4", required_timeframes=("4h",))(CometCloudLongShortV4Nautilus)

    wf = WalkForwardConfig(
        train_bars=180 * 6,   # ~6 months of 4h bars (smoke)
        test_bars=30 * 6,     # ~1 month
        n_rolls=3,            # small for quick test
        embargo_bars=24 * 6,  # 24h gap
    )

    result = run_walk_forward(
        strategy_name="ls_v4",
        pairs=["BTC", "ETH"],
        timeframe="4h",
        full_timerange=("2025-05-03", "2026-03-12"),
        wf_cfg=wf,
    )

    print()
    print(result.summary())
    print()
    for r in result.rolls:
        print(
            f"  roll {r.roll_id}: IS sharpe={r.is_sharpe:+.3f} "
            f"OOS sharpe={r.oos_sharpe:+.3f} "
            f"OOS n={r.oos_n_trades}"
        )