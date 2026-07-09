"""
Strategy metrics with statistical inference.

Standardised metric suite used across all research-framework strategies.
Aligned with STRATEGY_VALIDATION.md gates 2 (sample size), 5 (multiple testing),
and the canonical BacktestResult dataclass shape from
`scripts/run_freqtrade_backtest.py`.

All metrics return a `StrategyMetrics` dataclass with both point estimates
and p-values (vs H0: alpha = 0) so the walk-forward runner can apply
multiple-testing correction.

Note on Sharpe inference
-------------------------
The Sharpe ratio t-statistic from a sample of N returns is:

    t = sqrt(N - 1) * log(1 + sharpe^2 / (N - 1)) / sqrt(2)   # older form
    t = sqrt(N) * (sharpe / sqrt(1 + sharpe^2 / N))            # Lo (2002)

We use the Lo (2002) form because it has been shown to have better
finite-sample properties (less rejection under the null when alpha=0).
See: Andrew Lo, "The Statistics of Sharpe Ratios", FAJ 2002.

Confidence interval uses the normal approximation:

    SE(sharpe) ~ sqrt((1 + sharpe^2 / N) / N)

Goodness of fit for crypto 4h strategies (typical):
    N=100 trades, Sharpe=1.0 → t=10, p<1e-15
    N=30 trades, Sharpe=0.5 → t=2.7, p=0.005
    N=10 trades, Sharpe=0.5 → t=1.4, p=0.10  (borderline)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Optional, Sequence

import numpy as np
from scipy import stats


# ── Annualisation factor ────────────────────────────────────────────────────
# Strategies run on different timeframes; the periods-per-year constant
# is critical for Sharpe interpretation.
PERIODS_PER_YEAR = {
    "1h":  24 * 365,
    "4h":  6 * 365,
    "1d":  365,
}


def _ann_factor(timeframe: str) -> int:
    tf = timeframe.lower()
    if tf not in PERIODS_PER_YEAR:
        raise ValueError(f"unknown timeframe {timeframe}; expected one of {list(PERIODS_PER_YEAR)}")
    return PERIODS_PER_YEAR[tf]


# ── Per-trade PnL stats ─────────────────────────────────────────────────────

def win_rate(pnls: Sequence[float]) -> float:
    """Fraction of trades with positive PnL."""
    if not pnls:
        return 0.0
    return sum(1 for p in pnls if p > 0) / len(pnls)


def profit_factor(pnls: Sequence[float]) -> float:
    """Gross profit / |gross loss|. Infinite if no losses."""
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def avg_trade_pnl(pnls: Sequence[float]) -> float:
    """Mean PnL per trade."""
    return float(np.mean(pnls)) if pnls else 0.0


# ── Equity curve + drawdown ─────────────────────────────────────────────────

def build_equity_curve(initial_balance: float, pnls: Sequence[float]) -> np.ndarray:
    """Cumulative equity from initial balance + per-trade PnLs."""
    eq = np.empty(len(pnls) + 1)
    eq[0] = initial_balance
    if pnls:
        eq[1:] = initial_balance + np.cumsum(pnls)
    return eq


def max_drawdown(equity: np.ndarray) -> tuple[float, int, int]:
    """Max drawdown as a percentage of peak equity.

    Returns (max_dd_pct, peak_idx, valley_idx) where max_dd_pct is a positive
    percentage (e.g. 4.54 means 4.54%), peak_idx/valley_idx are absolute
    indices into the equity array.
    """
    if len(equity) < 2:
        return 0.0, 0, 0
    peaks = np.maximum.accumulate(equity)
    dd = (equity - peaks) / np.where(peaks > 0, peaks, 1.0)
    valley = int(np.argmin(dd))
    # Find the peak that precedes this valley (absolute index into equity)
    peak = int(np.argmax(equity[: valley + 1]))
    return float(-dd[valley] * 100.0), peak, valley  # positive percentage


def cagr(initial: float, final: float, years: float) -> float:
    """Compound annual growth rate. Returns as percentage."""
    if initial <= 0 or years <= 0:
        return 0.0
    return ((final / initial) ** (1.0 / years) - 1.0) * 100.0


# ── Sharpe / Sortino ────────────────────────────────────────────────────────

def sharpe_ratio(pnls: Sequence[float], ann_factor: int) -> tuple[float, float]:
    """Annualised Sharpe ratio + p-value (H0: sharpe=0) using Lo (2002).

    Returns (sharpe, two-sided p-value).
    Falls back to (0.0, 1.0) if no variance.
    """
    arr = np.asarray(pnls, dtype=float)
    n = len(arr)
    if n < 2:
        return 0.0, 1.0
    mean = arr.mean()
    std = arr.std(ddof=1)
    if std <= 0:
        return 0.0, 1.0
    sharpe = (mean / std) * np.sqrt(ann_factor)
    # Lo (2002) t-stat — better finite-sample than naive sqrt(N) * sharpe / sqrt(1+sharpe^2)
    se = np.sqrt((1.0 + sharpe * sharpe / ann_factor) / n) * np.sqrt(ann_factor)
    # Equivalent to: t = sqrt(n) * sharpe / sqrt(1 + sharpe^2 / ann_factor)
    t = sharpe / se
    p_value = 2.0 * (1.0 - stats.norm.cdf(abs(t)))  # two-sided normal
    return float(sharpe), float(p_value)


def sortino_ratio(pnls: Sequence[float], ann_factor: int, target: float = 0.0) -> tuple[float, float]:
    """Annualised Sortino + p-value (H0: sortino=0).

    Uses downside deviation (semi-deviation below target).
    """
    arr = np.asarray(pnls, dtype=float)
    n = len(arr)
    if n < 2:
        return 0.0, 1.0
    excess = arr - target
    downside = excess[excess < 0]
    if len(downside) < 2:
        # No losing trades → perfect strategy. Cap Sortino to avoid inf.
        # Return (cap_value, p_value) so the 2-tuple unpacking invariant holds.
        mean_excess = float(excess.mean())
        cap = 10.0 if mean_excess > 0 else 0.0   # cap at 10 to keep it finite
        p_value = 0.0 if mean_excess > 0 else 1.0
        return cap, p_value
    dd_std = np.sqrt((downside ** 2).sum() / n)  # semi-deviation uses full N
    if dd_std <= 0:
        return 0.0, 1.0
    sortino = (excess.mean() / dd_std) * np.sqrt(ann_factor)
    se = np.sqrt((1.0 + sortino * sortino / ann_factor) / n) * np.sqrt(ann_factor)
    t = sortino / se
    p_value = 2.0 * (1.0 - stats.norm.cdf(abs(t)))
    return float(sortino), float(p_value)


def calmar_ratio(cagr_pct: float, max_dd_pct: float) -> float:
    """Calmar = CAGR% / |MaxDD%|. Returns 0 if no drawdown."""
    if max_dd_pct <= 0:
        return 0.0
    return cagr_pct / max_dd_pct


def sqn(pnls: Sequence[float]) -> float:
    """System Quality Number (Van K. Tharp).

    SQN = sqrt(N) * mean(pnl) / std(pnl)

    Interpretation:
        <1.0  poor,  1.0-1.9 average,  2.0-2.9 good,  3.0-4.9 excellent,  >5.0 superb
    """
    arr = np.asarray(pnls, dtype=float)
    n = len(arr)
    if n < 2:
        return 0.0
    std = arr.std(ddof=1)
    if std <= 0:
        return 0.0
    return float(np.sqrt(n) * arr.mean() / std)


# ── Volatility ──────────────────────────────────────────────────────────────

def volatility_annual(pnls: Sequence[float], ann_factor: int) -> float:
    arr = np.asarray(pnls, dtype=float)
    if len(arr) < 2:
        return 0.0
    return float(arr.std(ddof=1) * np.sqrt(ann_factor))


def downside_vol_annual(pnls: Sequence[float], ann_factor: int, target: float = 0.0) -> float:
    arr = np.asarray(pnls, dtype=float)
    if len(arr) < 2:
        return 0.0
    excess = arr - target
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    dd_std = np.sqrt((downside ** 2).sum() / len(arr))
    return float(dd_std * np.sqrt(ann_factor))


# ── Master dataclass ────────────────────────────────────────────────────────

@dataclass
class StrategyMetrics:
    """Standardised metric bundle for one backtest.

    Compatible shape with `scripts/run_freqtrade_backtest.py::BacktestResult`
    for parity with existing report format.
    """
    # Sample
    n_trades: int
    n_wins: int
    n_losses: int
    # Returns
    total_return_pct: float
    cagr_pct: float
    # Risk-adjusted
    sharpe: float
    sharpe_p_value: float
    sortino: float
    sortino_p_value: float
    calmar: float
    sqn: float
    # Risk
    max_drawdown_pct: float
    volatility_annual: float
    downside_vol_annual: float
    # Trade stats
    win_rate_pct: float
    profit_factor: float
    avg_trade_pnl: float
    # Time
    timeframe: str
    years: float
    # Meta
    initial_balance: float
    final_balance: float

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        return (
            f"n={self.n_trades} CAGR={self.cagr_pct:+.2f}% "
            f"Sharpe={self.sharpe:+.3f} (p={self.sharpe_p_value:.4f}) "
            f"MaxDD={self.max_drawdown_pct:.2f}% WR={self.win_rate_pct:.1f}% "
            f"PF={self.profit_factor:.2f} SQN={self.sqn:.2f}"
        )


# ── Master compute function ─────────────────────────────────────────────────

def compute_metrics(
    pnls: Sequence[float],
    initial_balance: float = 10_000.0,
    timeframe: str = "4h",
    years: Optional[float] = None,
) -> StrategyMetrics:
    """Compute the full metric bundle from a list of per-trade PnLs.

    Annualisation uses TRADES PER YEAR (not bar periods per year) because
    observations are closed trades, not bars. Sharpe/Sortino/Vol are
    per-trade statistics scaled by trade frequency.

    Args:
        pnls: per-trade PnLs in USDT (closed positions only)
        initial_balance: starting equity (USDT)
        timeframe: one of '1h', '4h', '1d' (used for fallback annualisation)
        years: total period in years (auto-inferred from trade count if None)

    Returns:
        StrategyMetrics dataclass with all point estimates + p-values.
    """
    pnls = list(pnls)
    n = len(pnls)
    n_wins = sum(1 for p in pnls if p > 0)
    n_losses = sum(1 for p in pnls if p < 0)

    equity = build_equity_curve(initial_balance, pnls)
    final_balance = float(equity[-1])
    total_return_pct = (final_balance / initial_balance - 1.0) * 100.0 if initial_balance > 0 else 0.0

    if years is None or years <= 0:
        # Fall back to "trade-based years" if no explicit period given.
        # Caller should pass `years` for real backtests.
        years = max(n / _ann_factor(timeframe), 1.0 / _ann_factor(timeframe))

    # Trade-frequency annualisation (the proper one for per-trade PnLs)
    trades_per_year = n / years if years > 0 else 1.0

    cagr_pct = cagr(initial_balance, final_balance, years)
    sharpe, sharpe_p = sharpe_ratio(pnls, trades_per_year)
    sortino, sortino_p = sortino_ratio(pnls, trades_per_year)
    max_dd_pct, _, _ = max_drawdown(equity)
    vol = volatility_annual(pnls, trades_per_year)
    dvol = downside_vol_annual(pnls, trades_per_year)
    wr = win_rate(pnls) * 100.0
    pf = profit_factor(pnls)
    avg = avg_trade_pnl(pnls)
    calmar = calmar_ratio(cagr_pct, max_dd_pct)
    sqn_v = sqn(pnls)

    return StrategyMetrics(
        n_trades=n,
        n_wins=n_wins,
        n_losses=n_losses,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        sharpe=sharpe,
        sharpe_p_value=sharpe_p,
        sortino=sortino,
        sortino_p_value=sortino_p,
        calmar=calmar,
        sqn=sqn_v,
        max_drawdown_pct=max_dd_pct,
        volatility_annual=vol,
        downside_vol_annual=dvol,
        win_rate_pct=wr,
        profit_factor=pf,
        avg_trade_pnl=avg,
        timeframe=timeframe,
        years=years,
        initial_balance=initial_balance,
        final_balance=final_balance,
    )


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Synthetic test: 100 trades, slight positive edge, ~5% winrate target
    import random
    random.seed(42)
    pnls = [random.gauss(50, 200) for _ in range(100)]
    m = compute_metrics(pnls, initial_balance=10_000, timeframe="4h", years=1.0)
    print(m.summary())
    print()
    print("As dict:")
    for k, v in m.to_dict().items():
        print(f"  {k}: {v}")
