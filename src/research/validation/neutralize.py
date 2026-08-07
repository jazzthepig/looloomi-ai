"""
Factor neutralisation — strip known exposures before claiming alpha.

WHY THIS EXISTS. Seventy-one files in this repo mention neutralisation and ZERO
defined it (measured 2026-08-06). That gap has already cost us once: R62 found
that raw `a_ret − b_ret` was not alpha at all but LEVERAGED BETA, with betas
running 1.4–2.4. An "edge" that is really an exposure looks identical on a P&L
chart and behaves completely differently in a drawdown.

WHAT IT IS FOR HERE. Not a WorldQuant-style alpha factory — the panel does not
support that (N_eff ≈ 3.1 across 75 assets, `docs/MULTIFACTOR_FEASIBILITY.md`).
It is for ATTRIBUTION on the ①②③ path: when a tilt beats equal-weight, this
answers whether the tilt added anything or merely took more market.

DESIGN NOTES THAT MATTER
· Cross-sectional, per period — a time-series regression would leak information
  across the very boundary we are testing (I2 PIT).
· NaN-honest (I1): rows with unmeasured exposures are dropped from the fit and
  returned as NaN, never imputed to the mean. Imputing to the mean is the
  quietest way to manufacture a zero-exposure asset that does not exist.
· Returns residuals AND the fitted betas. The betas are the point as often as
  the residuals are: a tilt whose "alpha" vanishes under neutralisation has told
  you exactly what it was.
· Pure numpy least squares, no sklearn — one fewer dependency on the serving path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class NeutralisationResult:
    residual: np.ndarray                 # same length as y; NaN where inputs were unmeasured
    betas: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    r2: float = 0.0
    n_used: int = 0                      # rows that entered the fit
    n_total: int = 0

    @property
    def dropped(self) -> int:
        return self.n_total - self.n_used


def neutralize(y: np.ndarray,
               exposures: dict[str, np.ndarray],
               *, demean: bool = True, min_obs: int = 8) -> NeutralisationResult:
    """Regress `y` on `exposures` cross-sectionally; return the residual.

    y          : per-asset outcome for ONE period (e.g. forward return)
    exposures  : {name: per-asset exposure}, same length and order as y
    demean     : include an intercept (almost always yes — otherwise the market
                 level leaks into the first exposure's beta)
    min_obs    : below this many complete rows the fit is refused and everything
                 comes back NaN. A neutralisation fitted on five names is not a
                 neutralisation, it is an interpolation through noise, and it
                 would silently produce confident residuals.
    """
    y = np.asarray(y, dtype=float)
    n = y.size
    names = list(exposures)
    X_raw = np.column_stack([np.asarray(exposures[k], dtype=float) for k in names]) \
        if names else np.empty((n, 0))
    if X_raw.shape[0] != n:
        raise ValueError(f"exposure length {X_raw.shape[0]} != y length {n}")

    ok = np.isfinite(y) & (np.isfinite(X_raw).all(axis=1) if names else np.ones(n, bool))
    res = np.full(n, np.nan)
    out = NeutralisationResult(residual=res, n_total=n, n_used=int(ok.sum()))
    if ok.sum() < min_obs:
        return out                        # I1: refuse rather than fabricate

    X = X_raw[ok]
    if demean:
        X = np.column_stack([np.ones(X.shape[0]), X])
    yy = y[ok]

    coef, *_ = np.linalg.lstsq(X, yy, rcond=None)
    fitted = X @ coef
    res[ok] = yy - fitted

    ss_tot = float(((yy - yy.mean()) ** 2).sum())
    out.r2 = float(1.0 - ((yy - fitted) ** 2).sum() / ss_tot) if ss_tot > 0 else 0.0
    if demean:
        out.intercept = float(coef[0])
        out.betas = {k: float(c) for k, c in zip(names, coef[1:])}
    else:
        out.betas = {k: float(c) for k, c in zip(names, coef)}
    return out


def neutralize_panel(returns_by_day: dict, exposures_by_day: dict,
                     *, min_obs: int = 8) -> dict:
    """Apply `neutralize` independently per day. Each day is its own regression —
    never pooled — so no information crosses a period boundary (I2).

    Returns {day: NeutralisationResult}. Days that fail `min_obs` are PRESENT with
    an all-NaN residual rather than absent: a missing day and a day that could not
    be fitted are different facts, and only one of them is a data gap.
    """
    return {
        d: neutralize(returns_by_day[d], exposures_by_day.get(d, {}), min_obs=min_obs)
        for d in sorted(returns_by_day)
    }


def exposure_share(result: NeutralisationResult) -> float:
    """Fraction of cross-sectional variance explained by the known exposures.

    Read this before celebrating a residual: if it is 0.85, the 'alpha' is 15 % of
    what you were looking at and the rest was exposure you already owned.
    """
    return result.r2
