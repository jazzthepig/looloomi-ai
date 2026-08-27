"""
Walk-forward validation engine with purging + embargo.

Implements gate 3-4 of STRATEGY_VALIDATION.md:
- Walk-forward: rolling train/test windows over the backtest period.
- Purging: drop observations near the train/test boundary that would
  leak information between the two windows.
- Embargo: an additional gap after the test window to prevent serial
  correlation leakage into the next train window.

Decay ratio (gate 3): OOS_sharpe / IS_sharpe. Below 0.7 = overfit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
import pandas as pd


@dataclass
class WalkForwardConfig:
    """Configuration for a walk-forward validation run.

    All bar counts refer to per-instrument bars in the chosen timeframe
    (e.g. 4h bars per pair). Total available bars = end - start of timerange.
    """
    # Window sizes (in per-pair bars, e.g. 4h bars per symbol)
    train_bars: int = 365 * 6         # ~1 year of 4h bars per pair
    test_bars: int = 90 * 6           # ~3 months of 4h bars per pair
    n_rolls: int = 24                 # number of train→test roll forwards
    # Purging: number of bars to drop on EACH side of the train/test boundary
    # (prevents features computed on bar N from leaking into a label at bar N+1).
    purge_bars: int = 0
    # Embargo: additional bars of gap AFTER the test window before the next
    # train window starts (prevents serial correlation leakage).
    embargo_bars: int = 24 * 6        # ~24h of 4h bars = 1 day
    # PnL timing model: how long does it take for a trade signal to manifest
    # as a closed position? Used to enforce minimum gap between train label
    # and test observation. Default: 5 bars (20h on 4h) to match LS-V4 holds.
    signal_lag_bars: int = 5


@dataclass
class WalkForwardRoll:
    """One walk-forward roll: train window → test window + metrics for both."""
    roll_id: int
    train_start: int
    train_end: int                # exclusive
    test_start: int
    test_end: int                 # exclusive
    is_sharpe: float = 0.0
    is_cagr_pct: float = 0.0
    is_max_dd_pct: float = 0.0
    is_n_trades: int = 0
    oos_sharpe: float = 0.0
    oos_cagr_pct: float = 0.0
    oos_max_dd_pct: float = 0.0
    oos_n_trades: int = 0
    oos_win_rate_pct: float = 0.0


@dataclass
class WalkForwardResult:
    """Aggregate walk-forward result across all rolls."""
    config: WalkForwardConfig
    rolls: list[WalkForwardRoll] = field(default_factory=list)
    # Aggregate OOS (out-of-sample) metrics
    oos_sharpe_mean: float = 0.0
    oos_sharpe_std: float = 0.0
    oos_cagr_mean: float = 0.0
    oos_max_dd_max: float = 0.0
    oos_total_pnl: float | None = None
    oos_n_trades_total: int = 0
    # Aggregate IS (in-sample) metrics
    is_sharpe_mean: float = 0.0
    is_cagr_mean: float = 0.0
    # Decay (gate 3): OOS / IS ratio. < 0.7 = overfit.
    decay_ratio: float = 0.0
    decay_status: str = "OK"   # "OK" | "OVERFIT" | "NEGATIVE_OOS"

    def summary(self) -> str:
        return (
            f"WF: {len(self.rolls)} rolls  "
            f"OOS Sharpe = {self.oos_sharpe_mean:+.3f} ± {self.oos_sharpe_std:.3f}  "
            f"OOS CAGR = {self.oos_cagr_mean:+.2f}%  "
            f"OOS MaxDD = {self.oos_max_dd_max:.2f}%  "
            f"OOS n_trades = {self.oos_n_trades_total}  "
            f"decay = {self.decay_ratio:+.2f} ({self.decay_status})"
        )


def compute_window_boundaries(
    total_bars: int,
    cfg: WalkForwardConfig,
) -> list[tuple[int, int, int, int]]:
    """Compute (train_start, train_end, test_start, test_end) for each roll.

    Each roll advances by `test_bars` bars (the test window width).
    The earliest train_start is shifted so all rolls fit within `total_bars`.
    Returns inclusive-exclusive indices into a per-instrument bar array.
    """
    roll_step = cfg.test_bars
    # Total bars needed for one full roll: train + embargo + test
    span = cfg.train_bars + cfg.embargo_bars + cfg.test_bars
    # Total bars covered across all rolls
    n_rolls_max = max(0, (total_bars - span) // roll_step + 1)
    n_rolls = min(cfg.n_rolls, n_rolls_max)
    if n_rolls <= 0:
        return []

    boundaries = []
    # Align so the LAST roll ends at total_bars
    last_test_end = total_bars
    for i in range(n_rolls):
        # Roll i ends at last_test_end - (n_rolls - 1 - i) * roll_step
        test_end = last_test_end - (n_rolls - 1 - i) * roll_step
        test_start = test_end - cfg.test_bars
        # Embargo goes BEFORE the test (between train_end and test_start)
        train_end = test_start - cfg.embargo_bars
        train_start = train_end - cfg.train_bars
        if train_start < 0:
            # Not enough history for this roll — drop it
            continue
        boundaries.append((train_start, train_end, test_start, test_end))
    return boundaries


def compute_decay_ratio(
    is_sharpe: float,
    oos_sharpe: float,
    floor: float = 0.7,
) -> tuple[float, str]:
    """Compute decay ratio = OOS_sharpe / IS_sharpe.

    Returns (ratio, status) where status is:
    - "OK" if ratio >= floor (no significant decay)
    - "OVERFIT" if ratio < floor (overfit; reject)
    - "NEGATIVE_OOS" if OOS is negative while IS was positive (clear overfit)
    - "DEGENERATE" if IS sharpe is near zero (can't compute decay meaningfully)
    """
    if abs(is_sharpe) < 0.05:
        # IS sharpe too close to zero — decay undefined
        return 0.0, "DEGENERATE"
    ratio = oos_sharpe / is_sharpe
    if is_sharpe > 0 and oos_sharpe < 0:
        return float(ratio), "NEGATIVE_OOS"
    if ratio < floor:
        return float(ratio), "OVERFIT"
    return float(ratio), "OK"


def aggregate_walk_forward(rolls: list[WalkForwardRoll]) -> dict:
    """Aggregate per-roll metrics into OOS / IS summary."""
    if not rolls:
        return {
            "oos_sharpe_mean": 0.0,
            "oos_sharpe_std": 0.0,
            "oos_cagr_mean": 0.0,
            "oos_max_dd_max": 0.0,
            # 没有 roll 时同样是 None:0.0 会读成"跑了但没赚",而真相是没跑。
            "oos_total_pnl": None,
            "oos_total_pnl_reason": "no rolls",
            "oos_n_trades_total": 0,
            "is_sharpe_mean": 0.0,
            "is_cagr_mean": 0.0,
        }
    oos_sharpes = np.array([r.oos_sharpe for r in rolls])
    oos_cagrs = np.array([r.oos_cagr_pct for r in rolls])
    oos_maxdds = np.array([r.oos_max_dd_pct for r in rolls])
    return {
        "oos_sharpe_mean": float(oos_sharpes.mean()),
        "oos_sharpe_std": float(oos_sharpes.std(ddof=1)) if len(oos_sharpes) > 1 else 0.0,
        "oos_cagr_mean": float(oos_cagrs.mean()),
        "oos_max_dd_max": float(oos_maxdds.max()),
        # ⚠️ None,不是一个占位数 (S-235)。
        #
        # 原本是 `float(sum(r.oos_max_dd_pct for r in rolls))` 带一句
        # `# placeholder, real sum from PnLs` —— **它把最大回撤百分比求和,
        # 当成总盈亏**,而 `report.py` 把结果渲染成 `**OOS total PnL:** … USDT`。
        # 两个不同量纲的东西,一个被印成了另一个,单位还是错的。
        #
        # 更根本的是:`WalkForwardRoll` **根本没有 PnL 字段**。这个量不存在,
        # 所以占位符不是"暂时不准",是拿一个存在的量顶替一个不存在的量。
        # I1:未测量 = None 且必须传播。占位数会被读、被引用、被写进报告,
        # 而 None 会在渲染处逼出一句"未测量"。
        "oos_total_pnl": None,
        "oos_total_pnl_reason": "WalkForwardRoll 不携带 PnL;要报这个数,先给 roll 加 PnL 字段",
        "oos_n_trades_total": int(sum(r.oos_n_trades for r in rolls)),
        "is_sharpe_mean": float(np.mean([r.is_sharpe for r in rolls])),
        "is_cagr_mean": float(np.mean([r.is_cagr_pct for r in rolls])),
    }


def apply_purge_embargo(
    pnls: list[float],
    boundary_idx: int,
    purge: int = 5,
    embargo: int = 0,
) -> list[float]:
    """Drop pnls within `purge` indices before boundary_idx and `embargo` after.

    Useful when caller wants to apply purging/embargo to a pre-computed
    sequence of trade pnls aligned to bars. The caller should know the
    alignment between pnls and bars.

    Args:
        pnls: list of per-trade pnls (chronological by entry_ts).
        boundary_idx: index in the per-trade list corresponding to the
            train/test boundary. Trades AT boundary_idx start the test window.
        purge: number of trades to drop BEFORE boundary_idx.
        embargo: number of trades to drop AFTER boundary_idx.

    Returns:
        Filtered list of pnls.
    """
    start = max(0, boundary_idx - purge)
    end = min(len(pnls), boundary_idx + embargo)
    return pnls[:start] + pnls[end:]


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test boundary computation
    cfg = WalkForwardConfig(train_bars=100, test_bars=20, n_rolls=10, embargo_bars=5)
    boundaries = compute_window_boundaries(total_bars=500, cfg=cfg)
    print(f"Boundaries for total=500, train=100, test=20, embargo=5:")
    for b in boundaries:
        print(f"  train [{b[0]}:{b[1]}]  test [{b[2]}:{b[3]}]  span = {b[3] - b[0]}")

    # Test decay ratio
    print()
    cases = [
        (1.0, 0.8, "ok"),
        (1.0, 0.5, "overfit"),
        (1.0, -0.3, "negative_oos"),
        (0.04, 0.5, "degenerate"),
        (-0.5, -0.3, "ok (both negative)"),
    ]
    for is_sh, oos_sh, expected in cases:
        ratio, status = compute_decay_ratio(is_sh, oos_sh)
        print(f"  IS={is_sh:+.2f} OOS={oos_sh:+.2f}  →  decay={ratio:+.2f} status={status} (expected ~{expected})")