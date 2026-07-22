"""
Factor-Absorption gate — the "is this just old wine?" filter (Seth, 2026-07-17).
=================================================================================
Borrowed from the Google/academia LLM-factor-mining study: the killing floor isn't
multiple-testing, it's FACTOR ABSORPTION — most high-performing signals are just a repackaging
of KNOWN risk premia (market, momentum, size, quality). A candidate only earns a line in the book
if it carries RESIDUAL alpha AFTER we regress out our known factors. This is exactly the gate we
were missing (we caught the Crowd Clock by hand; this makes it automatic).

Method: OLS of the candidate's return series on {const + known factors}, with Newey-West HAC
standard errors (serial-correlation robust). Verdict:
  · raw signal significant but alpha-after-factors NOT  → ABSORBED (old wine — do not size)
  · alpha-after-factors significant                     → RESIDUAL ALPHA survives (genuine, orthogonal)

Pure numpy (no statsmodels dependency). Works on any aligned {candidate_ret, factor_rets} series.
Compliance: research/validation tooling; positioning language only downstream.
"""
from __future__ import annotations

import numpy as np


def _ols_nw(y: np.ndarray, X: np.ndarray, lags: int):
    """OLS beta + Newey-West (HAC) t-stats. X must already include an intercept column."""
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    Xe = X * resid[:, None]
    S = Xe.T @ Xe
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        G = Xe[l:].T @ Xe[:-l]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(cov), 1e-18))
    return beta, beta / se, resid


def absorption_test(candidate_ret, factors: dict, nw_lags: int = 6, periods_per_year: int = 365) -> dict:
    """candidate_ret: 1d return series. factors: {name: 1d series} (same length, aligned).
    Returns raw vs residual alpha with NW t-stats + verdict."""
    y = np.asarray(candidate_ret, dtype=float)
    names = list(factors.keys())
    cols = [np.asarray(factors[n], dtype=float) for n in names]
    n = min([len(y)] + [len(c) for c in cols])
    y = y[-n:]
    cols = [c[-n:] for c in cols]

    # raw: is the signal even significant on its own?
    braw, traw, _ = _ols_nw(y, np.ones((n, 1)), nw_lags)
    raw_mean, raw_t = float(braw[0]), float(traw[0])

    # residual: alpha after regressing out the known factors
    X = np.column_stack([np.ones(n)] + cols)
    beta, tstat, resid = _ols_nw(y, X, nw_lags)
    alpha, alpha_t = float(beta[0]), float(tstat[0])
    r2 = float(1.0 - (resid.var() / y.var())) if y.var() > 0 else 0.0
    betas = {names[i]: {"beta": round(float(beta[i + 1]), 3), "t": round(float(tstat[i + 1]), 2)} for i in range(len(names))}

    raw_sig = abs(raw_t) > 1.96
    alpha_sig = abs(alpha_t) > 1.96
    if raw_sig and not alpha_sig:
        verdict = "ABSORBED — raw edge is explained by known factors (old wine); do NOT size."
    elif alpha_sig:
        verdict = "RESIDUAL ALPHA — carries orthogonal incremental edge after known factors."
    elif not raw_sig:
        verdict = "NOT SIGNIFICANT raw — no edge to absorb."
    else:
        verdict = "INCONCLUSIVE."

    return {
        "n": n,
        "raw_mean_per_period": round(raw_mean, 6),
        "raw_ann_pct": round(raw_mean * periods_per_year * 100, 2),
        "raw_t": round(raw_t, 2),
        "alpha_per_period": round(alpha, 6),
        "alpha_ann_pct": round(alpha * periods_per_year * 100, 2),
        "alpha_t": round(alpha_t, 2),
        "factor_betas": betas,
        "r2": round(r2, 3),
        "raw_significant": raw_sig,
        "alpha_significant": alpha_sig,
        "verdict": verdict,
    }


# ── crypto known-factor builder ──────────────────────────────────────────────
def tsmom_factor(mkt_ret: np.ndarray, lookback: int = 30) -> np.ndarray:
    """Time-series momentum factor return: hold long when trailing-`lookback` return is positive,
    short when negative; realized as position(t-1) * mkt_ret(t). The canonical momentum premium."""
    r = np.asarray(mkt_ret, dtype=float)
    out = np.zeros_like(r)
    cum = np.cumsum(r)
    for t in range(lookback + 1, len(r)):
        trail = cum[t - 1] - cum[t - 1 - lookback]
        out[t] = np.sign(trail) * r[t]
    return out


if __name__ == "__main__":
    # DEMO / self-test: prove the gate auto-catches the Crowd Clock as momentum-absorbed.
    import httpx, datetime as dt
    from src.data.market.crowd_clock import compute_crowd_clock

    def day(t): return dt.datetime.utcfromtimestamp(t / 1000).strftime("%Y-%m-%d")
    fng = {}
    for r in httpx.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30).json()["data"]:
        fng[day(int(r["timestamp"]) * 1000)] = float(r["value"])
    cl = {}
    start = 1502928000000
    while True:
        kl = httpx.get("https://api.binance.com/api/v3/klines",
                       params={"symbol": "BTCUSDT", "interval": "1d", "startTime": start, "limit": 1000}, timeout=30).json()
        if not kl: break
        for k in kl: cl[day(k[0])] = float(k[4])
        start = kl[-1][0] + 86400000
        if len(kl) < 1000: break
    dates = sorted(set(fng) & set(cl)); px = np.array([cl[d] for d in dates])
    ret = np.zeros(len(px)); ret[1:] = px[1:] / px[:-1] - 1

    # candidate: Crowd-Clock long-in-markup strategy (position yesterday * today's mkt return)
    phase = ["neutral"] * len(dates)
    for i in range(30, len(dates)):
        phase[i] = compute_crowd_clock(fng[dates[i]], (px[i]/px[i-30]-1)*100, (px[i]/px[i-7]-1)*100, None, None, None)["phase"]
    pos = np.array([1.0 if phase[i] == "markup" else 0.0 for i in range(len(dates))])
    cand = np.zeros(len(dates)); cand[1:] = pos[:-1] * ret[1:]

    mkt = ret
    mom = tsmom_factor(ret, 30)
    s = slice(31, len(dates))
    res = absorption_test(cand[s], {"market": mkt[s], "momentum": mom[s]})
    import json
    print(json.dumps(res, indent=2))
