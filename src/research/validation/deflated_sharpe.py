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
from statistics import NormalDist, pvariance
from dataclasses import dataclass
from typing import Sequence, Iterable

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


def expected_max_sharpe(*, sr_variance: float, n_trials: int) -> float:
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
    sr_star = expected_max_sharpe(sr_variance=sr_variance, n_trials=n_trials)
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

# ══════════════════════════════════════════════════════════════════════════════
# S-236 —— 下面这段是 2026-08-25 补回来的,而上面那段是我 2026-08-24 删掉的
#
# 我写 S-189(给 R70 算 DSR)时,**整份重写了这个文件**:-178 / +137 行。
# 被删掉的有 `SharpeStats` / `sharpe_stats()` / `probabilistic_sharpe_ratio()` /
# `deflated_sharpe_ratio()` / `StrategyEval` / `evaluate_universe()`。
#
# **8 个 src/research 模块 import 这些名字,其中包括 `signal_factory.py`** ——
# 每天产出 `signal_factory_*` 那批 experiment_runs 的那个。它们从那次提交起
# 就 import 不了,而没有任何东西发现:
#
#     py_compile 只查语法        → 绿
#     app boot smoke 不碰 research → 碰不到
#     我没有 import 过消费者      → 没人看
#
# **我在写下「先读消费者,再写生产者」(S-233)的同一个 session 里,
# 对自己的模块违反了它。** 而且是更糟的版本:S-233 是一个没有调用者的函数
# 指向没核对的契约;这次是一个【有 8 个调用者】的模块被整份换掉。
#
# ⚠️ 还有一个更隐蔽的:`expected_max_sharpe` 两版都在,而**参数顺序是反的** ——
# 旧 `(sr_variance, n_trials)`,我的 `(n_trials, sharpe_variance)`。两个都是 float,
# 传反了不报错,只是算出一个不同的数。所以它现在是 **keyword-only**:
# 位置调用直接 TypeError,而不是静默给出另一个答案。
# ══════════════════════════════════════════════════════════════════════════════

DSR_THRESHOLD = 0.95
TRADING_DAYS = 252
_Z = NormalDist()
_EULER = _EULER_MASCHERONI


def deflated_sharpe(observed_sr_ann: float,
                    all_trial_sr_ann: Iterable[float],
                    n_obs: int,
                    n_trials: int | None = None,
                    skew: float = 0.0,
                    kurtosis: float = 3.0) -> dict:
    """Deflate an annualised Sharpe for the search that produced it.

    `n_trials` defaults to len(all_trial_sr_ann) but SHOULD be overridden with
    the true funnel size when the reported grid is a survivor set of a larger
    one — which it usually is. R70's 72 configurations were the survivors of
    R69's 216.

    skew/kurtosis are of the RETURN series. Defaults are Gaussian, which is the
    generous assumption: real crypto returns are negatively skewed and fat
    tailed, and both push DSR down. If you do not have the moments, say so
    rather than quietly claiming normality.
    """
    trials = [s for s in all_trial_sr_ann if s is not None]
    if len(trials) < 2 or n_obs < 3:
        return {"ok": False, "reason": "need ≥2 trials and ≥3 observations"}

    ann = math.sqrt(TRADING_DAYS)
    n = int(n_trials or len(trials))
    sr = observed_sr_ann / ann
    var = pvariance([s / ann for s in trials])
    sr_star = expected_max_sharpe(n_trials=n, sr_variance=var)

    denom = 1 - skew * sr + ((kurtosis - 1) / 4) * sr ** 2
    if denom <= 0:
        return {"ok": False, "reason": "non-positive variance term; check moments"}
    dsr = _Z.cdf((sr - sr_star) * math.sqrt(n_obs - 1) / math.sqrt(denom))

    return {
        "ok": True,
        "dsr": round(dsr, 4),
        "passes": bool(dsr > DSR_THRESHOLD),
        "threshold": DSR_THRESHOLD,
        "observed_sr_ann": round(observed_sr_ann, 4),
        "luck_threshold_sr_ann": round(sr_star * ann, 4),
        "beats_luck_threshold": bool(sr > sr_star),
        "n_trials": n,
        "n_trials_reported": len(trials),
        "n_obs": n_obs,
        "trial_sr_ann_stdev": round(math.sqrt(var) * ann, 4),
        "trial_sr_ann_mean": round(sum(trials) / len(trials), 4),
        "skew": skew,
        "kurtosis": kurtosis,
        "moments_assumed": skew == 0.0 and kurtosis == 3.0,
    }


def required_sharpe(n_trials: int, sharpe_variance_ann: float, n_obs: int,
                    target: float = DSR_THRESHOLD) -> float:
    """The annualised Sharpe a search of this size would have to produce.

    Reported alongside DSR because a bare "0.36, fails" invites the reply
    "so how close were we?" — and the answer is usually "not close", which is
    the more useful fact.
    """
    ann = math.sqrt(TRADING_DAYS)
    var = (sharpe_variance_ann / ann) ** 2
    sr_star = expected_max_sharpe(n_trials=n_trials, sr_variance=var)
    lo, hi = 0.0, 20.0
    for _ in range(200):
        mid = (lo + hi) / 2
        d = _Z.cdf((mid - sr_star) * math.sqrt(n_obs - 1)
                   / math.sqrt(1 + 0.5 * mid ** 2))
        if d < target:
            lo = mid
        else:
            hi = mid
    return round(hi * ann, 3)
