"""
Regime attribution — per-regime P&L breakdown.

Implements gate 7 of STRATEGY_VALIDATION.md: every strategy must report
its performance broken down by macro regime (RISK_ON, RISK_OFF, TIGHTENING,
EASING, STAGFLATION, GOLDILOCKS).

Why this matters: a strategy with good overall metrics but negative in
TIGHTENING regimes is fragile. The regime-segmented view surfaces that
immediately, before the regime arrives again.

Inputs:
- Sequence of trade pnls
- For each trade, the macro regime AT THE TIME OF TRADE ENTRY
  (not exit — that's hindsight, contaminates the analysis)

Output: per-regime (n_trades, total_pnl, win_rate, contribution_pct, status)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np


# ── Regime definitions (mirror CIS methodology v4.1) ─────────────────────────
#
# Standard 6-regime taxonomy. "UNKNOWN" is the catch-all for periods
# where regime is ambiguous.

VALID_REGIMES = (
    "RISK_ON",
    "RISK_OFF",
    "TIGHTENING",
    "EASING",
    "STAGFLATION",
    "GOLDILOCKS",
    "UNKNOWN",
)


@dataclass
class RegimeBucket:
    """Per-regime P&L summary."""
    regime: str
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    total_pnl: float = 0.0
    win_rate_pct: float = 0.0
    contribution_pct: float = 0.0     # share of total P&L
    avg_pnl: float = 0.0
    sharpe: float = 0.0

    def summary(self) -> str:
        return (
            f"{self.regime:<12} n={self.n_trades:>4}  "
            f"WR={self.win_rate_pct:>5.1f}%  "
            f"PnL=${self.total_pnl:>+10.0f}  "
            f"contrib={self.contribution_pct:>+5.1f}%  "
            f"avg=${self.avg_pnl:>+6.2f}  "
            f"sharpe={self.sharpe:+.2f}"
        )


@dataclass
class RegimeAttribution:
    """Full regime attribution across all regimes."""
    buckets: dict[str, RegimeBucket] = field(default_factory=dict)
    total_trades: int = 0
    total_pnl: float = 0.0
    worst_regime: str = ""
    worst_regime_pnl: float = 0.0
    best_regime: str = ""
    best_regime_pnl: float = 0.0
    regime_dependency: float = 0.0    # 0 = robust, 1 = fragile (skew of contributions)

    def summary(self) -> str:
        lines = [
            f"Regime attribution: {self.total_trades} trades, ${self.total_pnl:+.2f} net",
            f"  best={self.best_regime} (${self.best_regime_pnl:+.2f})  "
            f"worst={self.worst_regime} (${self.worst_regime_pnl:+.2f})",
            f"  regime_dependency={self.regime_dependency:.2f}  "
            f"(0=robust, 1=concentrated)",
        ]
        for regime in VALID_REGIMES:
            if regime in self.buckets:
                lines.append("  " + self.buckets[regime].summary())
        return "\n".join(lines)


def attribute(
    pnls: Sequence[float],
    regimes: Sequence[str],
) -> RegimeAttribution:
    """Compute per-regime P&L attribution.

    Args:
        pnls: per-trade realized PnLs.
        regimes: macro regime label at the time of each trade entry (same
            length as pnls).

    Returns:
        RegimeAttribution with per-regime buckets + risk metrics.

    Raises:
        ValueError: if pnls and regimes differ in length, or any regime is
            not in VALID_REGIMES.
    """
    if len(pnls) != len(regimes):
        raise ValueError(
            f"pnls/regimes length mismatch: {len(pnls)} vs {len(regimes)}"
        )
    bad = [r for r in regimes if r not in VALID_REGIMES]
    if bad:
        raise ValueError(
            f"unknown regime(s) {set(bad)!r}; valid: {VALID_REGIMES}"
        )

    arr = np.asarray(pnls, dtype=float)
    buckets: dict[str, RegimeBucket] = {
        r: RegimeBucket(regime=r) for r in VALID_REGIMES
    }

    for p, regime in zip(arr, regimes):
        b = buckets[regime]
        b.n_trades += 1
        b.total_pnl += float(p)
        if p > 0:
            b.n_wins += 1
        elif p < 0:
            b.n_losses += 1

    total_pnl = float(arr.sum())
    total_n = len(arr)

    for r, b in buckets.items():
        if b.n_trades == 0:
            continue
        pnls_r = np.asarray([pnls[i] for i in range(len(pnls)) if regimes[i] == r])
        b.win_rate_pct = b.n_wins / b.n_trades * 100.0
        b.contribution_pct = (b.total_pnl / total_pnl * 100.0) if total_pnl != 0 else 0.0
        b.avg_pnl = b.total_pnl / b.n_trades
        # Sharpe = mean/std of trade pnls (not annualised; sample-level)
        if pnls_r.std(ddof=1) > 0:
            b.sharpe = float(pnls_r.mean() / pnls_r.std(ddof=1))

    # Best/worst regimes by total PnL
    non_empty = [(r, b.total_pnl) for r, b in buckets.items() if b.n_trades > 0]
    if non_empty:
        worst = min(non_empty, key=lambda x: x[1])
        best = max(non_empty, key=lambda x: x[1])
        worst_regime, worst_pnl = worst
        best_regime, best_pnl = best
        # Regime dependency: 1 - (entropy of contribution distribution / max entropy)
        # Lower entropy = strategy depends on few regimes = fragile
        pnls_abs = [abs(p) for _, p in non_empty]
        total_abs = sum(pnls_abs)
        if total_abs > 0:
            probs = [p / total_abs for p in pnls_abs]
            # Entropy of |PnL| distribution
            entropy = -sum(p * np.log(p) for p in probs if p > 0)
            max_entropy = np.log(len(probs))
            dep = 1.0 - entropy / max_entropy if max_entropy > 0 else 0.0
        else:
            dep = 0.0
    else:
        worst_regime = best_regime = "UNKNOWN"
        worst_pnl = best_pnl = 0.0
        dep = 0.0

    return RegimeAttribution(
        buckets=buckets,
        total_trades=total_n,
        total_pnl=total_pnl,
        worst_regime=worst_regime,
        worst_regime_pnl=worst_pnl,
        best_regime=best_regime,
        best_regime_pnl=best_pnl,
        regime_dependency=float(dep),
    )


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Realistic: 4 regimes, strategy wins on RISK_ON, loses on RISK_OFF
    pnls_ = [
        # RISK_ON: 5 wins, 1 loss
        100.0, 50.0, 80.0, 30.0, 60.0, -20.0,
        # RISK_OFF: 1 win, 4 losses
        -40.0, -30.0, -20.0, -10.0, 15.0,
        # TIGHTENING: 2 wins, 2 losses
        -15.0, 25.0, -10.0, 20.0,
        # GOLDILOCKS: 3 wins
        45.0, 35.0, 55.0,
    ]
    regimes_ = (
        ["RISK_ON"] * 6
        + ["RISK_OFF"] * 5
        + ["TIGHTENING"] * 4
        + ["GOLDILOCKS"] * 3
    )
    assert len(pnls_) == len(regimes_)

    result = attribute(pnls_, regimes_)
    print(result.summary())

    # Sanity: validate
    print()
    print(f"Total PnL: sum={sum(pnls_):.2f}  attributed={result.total_pnl:.2f}")
    print(f"Worst regime: {result.worst_regime} (${result.worst_regime_pnl:.2f})")
    print(f"Best regime: {result.best_regime} (${result.best_regime_pnl:.2f})")

    # Length-mismatch error
    try:
        attribute(pnls_, regimes_[:10])
    except ValueError as e:
        print(f"\nValueError raised correctly: {e}")