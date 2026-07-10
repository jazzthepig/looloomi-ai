"""
Deflated Sharpe Ratio (DSR) + expected-max-Sharpe haircut — the instrument for a
50-strategy factory (Seth, 2026-07-10).
===============================================================================

We run ~50 strategies. When you search that many, the BEST observed Sharpe is
inflated by selection alone — even if every candidate were pure noise, the max of
50 noisy Sharpes is large. A raw Sharpe of 6 across 50 trials is NOT the same claim
as a Sharpe of 6 from a single pre-registered strategy.

The Deflated Sharpe Ratio (Bailey & López de Prado, 2014) is the correct fix. It
returns the PROBABILITY that a strategy's true Sharpe is > 0, after correcting for:
  1. Selection bias / multiple testing (N trials, variance of Sharpe across trials)
  2. Non-normal returns (skewness, kurtosis)
  3. Sample length (T observations)

DSR ≥ 0.95 ⇒ the Sharpe survives the 50-way search: a defensible, investor-grade
claim. DSR < 0.95 ⇒ plausibly a selection artifact. This is the confident,
rigorous version of "is it overfit" — an instrument, not a shrug.

Refs:
  Bailey & López de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
  Selection Bias, Backtest Overfitting and Non-Normality," J. Portfolio Mgmt.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

Pure numpy — no scipy. Normal CDF via erf; inverse-normal via Acklam's algorithm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

_EULER_MASCHERONI = 0.5772156649015329


# ── Normal CDF / inverse-CDF (no scipy) ──────────────────────────────────────

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF — Acklam's rational approximation (|err|<1.15e-9)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ── Sharpe moments from a return series ──────────────────────────────────────

@dataclass(frozen=True)
class SharpeStats:
    sr: float           # per-observation Sharpe (mean/std of returns)
    T: int              # number of observations
    skew: float         # skewness of returns
    kurt: float         # kurtosis (non-excess; normal = 3.0)


def sharpe_stats(returns: Sequence[float]) -> SharpeStats:
    r = np.asarray([x for x in returns if x is not None], dtype=float)
    T = r.size
    if T < 3 or r.std(ddof=1) == 0:
        return SharpeStats(sr=0.0, T=T, skew=0.0, kurt=3.0)
    mu, sd = r.mean(), r.std(ddof=1)
    sr = mu / sd
    z = (r - mu) / sd
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))          # non-excess kurtosis (normal = 3)
    return SharpeStats(sr=float(sr), T=int(T), skew=skew, kurt=kurt)


# ── PSR / expected-max-Sharpe / DSR ──────────────────────────────────────────

def probabilistic_sharpe_ratio(s: SharpeStats, sr_benchmark: float = 0.0) -> float:
    """P(true SR > sr_benchmark) given estimation error, skew, kurtosis, T.
    All Sharpes are per-observation (same frequency)."""
    denom = math.sqrt(max(1e-12, 1.0 - s.skew * s.sr + (s.kurt - 1.0) / 4.0 * s.sr**2))
    return norm_cdf(((s.sr - sr_benchmark) * math.sqrt(max(1, s.T - 1))) / denom)


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """E[max SR] under N independent trials of zero-true-Sharpe strategies
    (Bailey-LdP). sr_variance = Var of the per-observation SR estimates across trials."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    N = float(n_trials)
    z1 = norm_ppf(1.0 - 1.0 / N)
    z2 = norm_ppf(1.0 - 1.0 / (N * math.e))
    return math.sqrt(sr_variance) * ((1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)


def deflated_sharpe_ratio(s: SharpeStats, sr_variance: float, n_trials: int) -> float:
    """DSR = PSR evaluated at the expected-max-Sharpe benchmark. Probability (0..1)
    that the strategy's true Sharpe > 0 AFTER correcting for the N-trial search."""
    sr_star = expected_max_sharpe(sr_variance, n_trials)
    return probabilistic_sharpe_ratio(s, sr_benchmark=sr_star)


# ── Portfolio-level evaluation over many strategies ──────────────────────────

@dataclass
class StrategyEval:
    name: str
    sr_per_obs: float
    T: int
    skew: float
    kurt: float
    psr_vs_zero: float          # significance ignoring multiple testing
    dsr: float                  # significance AFTER N-trial correction
    survives: bool              # dsr >= threshold


def evaluate_universe(returns_by_strategy: dict[str, Sequence[float]],
                      *, n_trials: int | None = None,
                      dsr_threshold: float = 0.95) -> list[StrategyEval]:
    """Given {strategy_name: return_series}, compute DSR for each, using the
    cross-strategy variance of per-observation Sharpe as the selection-bias input.

    n_trials defaults to the number of strategies evaluated (honest, mildly
    conservative — the true search space is ≥ this once you count discarded configs).
    """
    stats = {n: sharpe_stats(r) for n, r in returns_by_strategy.items()}
    srs = [s.sr for s in stats.values() if s.T >= 3]
    sr_var = float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0
    N = n_trials if n_trials is not None else max(2, len(srs))

    out: list[StrategyEval] = []
    for name, s in stats.items():
        psr = probabilistic_sharpe_ratio(s, 0.0)
        dsr = deflated_sharpe_ratio(s, sr_var, N)
        out.append(StrategyEval(name=name, sr_per_obs=round(s.sr, 4), T=s.T,
                                skew=round(s.skew, 3), kurt=round(s.kurt, 3),
                                psr_vs_zero=round(psr, 4), dsr=round(dsr, 4),
                                survives=dsr >= dsr_threshold))
    out.sort(key=lambda e: e.dsr, reverse=True)
    return out


# ── Self-test against the Bailey-LdP worked properties ───────────────────────

def _selftest() -> int:
    rng = np.random.default_rng(7)
    # A genuinely-good strategy vs 40 noise strategies. DSR should keep the good one
    # and deflate the best noise one.
    good = rng.normal(0.004, 0.01, 500)                       # per-trade edge
    noise = {f"noise_{i}": rng.normal(0.0, 0.01, 500) for i in range(40)}
    universe = {"good": good, **noise}
    res = evaluate_universe(universe)
    good_e = next(e for e in res if e.name == "good")
    best_noise = max((e for e in res if e.name != "good"), key=lambda e: e.dsr)
    print(f"[SELFTEST] good:  SR/obs={good_e.sr_per_obs}  PSR={good_e.psr_vs_zero}  "
          f"DSR={good_e.dsr}  survives={good_e.survives}")
    print(f"[SELFTEST] best noise: SR/obs={best_noise.sr_per_obs}  "
          f"PSR={best_noise.psr_vs_zero}  DSR={best_noise.dsr}  survives={best_noise.survives}")
    assert good_e.dsr > best_noise.dsr, "good must out-rank best noise"
    assert not best_noise.survives, "best-of-40 noise must NOT survive DSR@0.95"
    print("[SELFTEST] DSR correctly separates real edge from best-of-N noise. ✅")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
