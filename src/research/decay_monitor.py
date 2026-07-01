"""
Decay monitor — detect when a strategy stops working.

Implements the rolling Sharpe half-life concept from gate validation.
Once a live strategy's rolling Sharpe decays past its half-life,
the strategy should be flagged for review or auto-shutoff.

Components:
- Rolling Sharpe: per-trade or per-bar Sharpe over a sliding window.
- Half-life: time (in trades/bars) for rolling Sharpe to fall from peak
  to half-peak under no new information.
- Regime-shift flag: rolling Sharpe has dropped > 2σ below the historical mean.

Usage:
    monitor = DecayMonitor(window_size=30, halflife_threshold=0.5)
    live_sharpes = monitor.rolling_sharpe(realized_pnls_per_bar)
    status = monitor.check(live_sharpes)
    if status.status == "DECAY":
        fire alert / shut down strategy
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np


@dataclass
class DecayStatus:
    """One decay-monitor readout."""
    status: str                # "OK" | "WATCH" | "DECAY" | "INSUFFICIENT_DATA"
    rolling_sharpe_peak: float
    rolling_sharpe_current: float
    rolling_sharpe_mean: float
    rolling_sharpe_std: float
    half_life_bars: float      # bars for current Sharpe to decay from peak
    z_score: float             # current vs (mean, std)
    notes: str = ""

    def summary(self) -> str:
        return (
            f"[{self.status}] peak={self.rolling_sharpe_peak:+.3f} "
            f"current={self.rolling_sharpe_current:+.3f} "
            f"z={self.z_score:+.2f}  "
            f"halflife={self.half_life_bars:.0f} bars"
        )


class DecayMonitor:
    """Track rolling Sharpe and detect regime shifts.

    Args:
        window_size: number of trades/bars in each rolling window.
        z_threshold: number of standard deviations below mean to trigger DECAY.
            Default 2.0 = "outside 95% of historical".
        halflife_threshold: ratio (current/peak) below which we say
            "decayed to half-life". Default 0.5.
    """

    def __init__(
        self,
        window_size: int = 30,
        z_threshold: float = 2.0,
        halflife_threshold: float = 0.5,
    ):
        self.window_size = window_size
        self.z_threshold = z_threshold
        self.halflife_threshold = halflife_threshold

    def rolling_sharpe(
        self,
        pnls: Sequence[float],
        periods_per_year: Optional[int] = None,
    ) -> list[float]:
        """Rolling Sharpe ratio (non-annualised by default).

        Args:
            pnls: sequence of per-trade or per-bar returns.
            periods_per_year: if set, annualise each window's Sharpe.
                If None (default), return raw Sharpe = mean / std per window.

        Returns:
            List of length len(pnls) - window_size + 1. Empty if not enough data.
        """
        arr = np.asarray(pnls, dtype=float)
        n = len(arr)
        if n < self.window_size:
            return []
        out = []
        for i in range(self.window_size, n + 1):
            window = arr[i - self.window_size : i]
            mean = window.mean()
            std = window.std(ddof=1)
            if std <= 0:
                out.append(0.0)
            else:
                s = mean / std
                if periods_per_year:
                    s *= math.sqrt(periods_per_year)
                out.append(float(s))
        return out

    def half_life(
        self,
        rolling_sharpes: Sequence[float],
    ) -> float:
        """Estimate the half-life of rolling Sharpe decay.

        Models the decay as exponential decay from peak: y(t) = peak * exp(-λ t).
        Half-life = ln(2) / λ.

        Uses OLS to fit ln(rolling/peak) = -λ t for the DECAYING portion of the
        sequence (where rolling/peak < 1).

        Returns the half-life in units of "windows". Negative or NaN if no
        decay observed.
        """
        arr = np.asarray(rolling_sharpes, dtype=float)
        n = len(arr)
        if n < 5:
            return float("nan")
        peak = float(arr.max())
        if peak <= 0:
            return float("nan")
        # Use only the DECAY portion: indices after the peak
        peak_idx = int(np.argmax(arr))
        if peak_idx >= n - 1:
            return float("nan")
        decay = arr[peak_idx:]
        # Drop zeros / negatives for log
        valid = decay > 0
        if valid.sum() < 3:
            return float("nan")
        log_decay = np.log(decay[valid] / peak)
        t = np.arange(len(log_decay))
        # Fit log_decay = -λ * t  =>  λ = -slope
        # OLS slope = cov(t, log_decay) / var(t)
        t_mean = t.mean()
        log_mean = log_decay.mean()
        cov = ((t - t_mean) * (log_decay - log_mean)).sum()
        var = ((t - t_mean) ** 2).sum()
        if var <= 0 or cov >= 0:
            # No decay observed
            return float("inf")
        lam = -cov / var  # positive λ means decay
        if lam <= 0:
            return float("inf")
        half_life = math.log(2.0) / lam
        return float(half_life)

    def check(
        self,
        pnls: Sequence[float],
        periods_per_year: Optional[int] = None,
    ) -> DecayStatus:
        """Run a full decay check on a sequence of pnls.

        Returns a DecayStatus. Status is:
        - "INSUFFICIENT_DATA" if window can't be filled
        - "DECAY" if current rolling Sharpe is z < -z_threshold AND
          current/peak < halflife_threshold
        - "WATCH" if z < -z_threshold but ratio is borderline
        - "OK" otherwise
        """
        rolling = self.rolling_sharpe(pnls, periods_per_year)
        if not rolling:
            return DecayStatus(
                status="INSUFFICIENT_DATA",
                rolling_sharpe_peak=0.0, rolling_sharpe_current=0.0,
                rolling_sharpe_mean=0.0, rolling_sharpe_std=0.0,
                half_life_bars=float("nan"), z_score=0.0,
                notes=f"need >= {self.window_size} obs, got {len(pnls)}",
            )

        arr = np.asarray(rolling)
        peak = float(arr.max())
        current = float(arr[-1])
        mean = float(arr.mean())
        std = float(arr.std(ddof=1))
        z = (current - mean) / std if std > 0 else 0.0
        hl = self.half_life(rolling)

        ratio = current / peak if peak > 0 else 0.0
        notes = ""

        if ratio < self.halflife_threshold and z < -self.z_threshold:
            status = "DECAY"
            notes = (
                f"rolling Sharpe decayed to {ratio*100:.0f}% of peak "
                f"and is {abs(z):.1f}σ below historical mean"
            )
        elif z < -self.z_threshold:
            status = "WATCH"
            notes = f"current {z:.1f}σ below mean but ratio {ratio:.2f} acceptable"
        else:
            status = "OK"

        return DecayStatus(
            status=status,
            rolling_sharpe_peak=peak,
            rolling_sharpe_current=current,
            rolling_sharpe_mean=mean,
            rolling_sharpe_std=std,
            half_life_bars=hl,
            z_score=z,
            notes=notes,
        )


# ── Self-test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Synthetic: stable strategy, then regime shift → decay
    rng = np.random.default_rng(42)
    good = rng.normal(loc=10.0, scale=15.0, size=200)   # mean 10, std 15
    bad = rng.normal(loc=-5.0, scale=20.0, size=100)    # mean -5, std 20
    pnls = list(good) + list(bad)

    monitor = DecayMonitor(window_size=30, z_threshold=2.0, halflife_threshold=0.5)
    status = monitor.check(pnls, periods_per_year=None)
    print(status.summary())
    print(f"Notes: {status.notes}")

    # Pure no-decay case
    pure_good = list(rng.normal(loc=10.0, scale=15.0, size=300))
    status2 = monitor.check(pure_good)
    print()
    print(status2.summary())
    print(f"Notes: {status2.notes}")

    # Half-life test: monotonic decay curve
    print()
    synthetic = [2.0 - 0.01 * i for i in range(50)]  # linear decay from 2.0 to 1.5
    rolling = monitor.rolling_sharpe(synthetic)
    hl = monitor.half_life(rolling)
    print(f"Linear decay sequence: half_life = {hl:.1f} windows (~ ticks until Sharpe halves)")