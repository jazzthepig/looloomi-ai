"""Deflated Sharpe Ratio — the discount for having searched (S-189, 2026-08-20).

WHY THIS EXISTS. `experiment_runs` has carried a `dsr` column since it was
created and it has never been populated once. Meanwhile R70's best-of-grid
Sharpe reached an investor-facing page with no multiple-testing correction at
all. A column that exists, is never written, and guards the one failure mode
this shop is most exposed to — searching until something looks good — is worse
than no column: it signals that the check is handled.

WHAT IT MEASURES. Run 72 configurations against a market and the best one looks
good even if none of them has any skill, because you selected the maximum of 72
noisy draws. Bailey & López de Prado (2014) make that precise: given N trials
whose Sharpe estimates have dispersion √V, the expected MAXIMUM under the null
of zero true skill is

    SR* = √V · [ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]        γ = Euler–Mascheroni

SR* is the bar luck alone clears. The Deflated Sharpe Ratio is then the
probability that the observed Sharpe beats that bar rather than being the
expected top draw:

    DSR = Z[ (SR̂ − SR*) · √(T−1) / √(1 − γ₃·SR̂ + ((γ₄−1)/4)·SR̂²) ]

Conventionally you want DSR > 0.95.

⚠️ FREQUENCY. SR̂, SR* and V must all be expressed at the frequency of the T
observations. Annualised Sharpes must be divided by √252 before they enter this,
or the deflation is wrong by an order of magnitude in the flattering direction.
This function takes annualised inputs and converts, because that is the form
every report in this repo publishes and a units mismatch here would produce a
comfortable number.

⚠️ WHAT THIS CANNOT SEE. N is the number of trials you TELL it about. Every
configuration ever run against the same data belongs in N, including the ones
nobody wrote down, the ones from an earlier round, and the judgement calls made
before the grid was specified. The honest N is almost always larger than the
recorded one, so DSR is an upper bound on how good the result is.

⚠️ AND THE THING DSR DOES NOT FIX. Holding out a window does not protect a
result if the configuration to publish is then chosen by ranking ON that window.
The selection consumes the held-out property: the data has been used, just at
the last step instead of the first. R70 held out 2026-01-08 → 06-07 correctly,
then published the argmax over it. That is the actual methodological hole, and
no amount of deflation repairs it — only a second window, untouched by the
selection, can.
"""
from __future__ import annotations

import math
from statistics import NormalDist, pvariance
from typing import Iterable

_Z = NormalDist()
_EULER = 0.5772156649015329
TRADING_DAYS = 252

#: Conventional threshold. Not a law — a convention worth stating so that
#: "we passed" and "we chose a lenient bar" cannot be confused later.
DSR_THRESHOLD = 0.95


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """SR* — the Sharpe that luck alone is expected to produce as the best of N.

    Per-observation units. `sharpe_variance` is the variance of the Sharpe
    estimates ACROSS trials, same units.
    """
    if n_trials < 2:
        return 0.0
    sd = math.sqrt(max(sharpe_variance, 0.0))
    return sd * ((1 - _EULER) * _Z.inv_cdf(1 - 1 / n_trials)
                 + _EULER * _Z.inv_cdf(1 - 1 / (n_trials * math.e)))


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
    sr_star = expected_max_sharpe(n, var)

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
    sr_star = expected_max_sharpe(n_trials, var)
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
