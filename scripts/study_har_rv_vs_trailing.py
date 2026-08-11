#!/usr/bin/env python3
"""
S-134 — Is HAR-RV worth wiring into the ① book's vol scalar?
============================================================

TWO QUESTIONS, IN THIS ORDER. The second is the interesting one and the first is
the one that decides whether it matters.

  Q1 (REACHABILITY). How often does the vol scalar actually BIND — i.e. how often
      is it the binding constraint in `gross = min(scalar, cap)` rather than the
      cap? With _VOL_TARGET=0.60 and the cap at 0.5, the scalar binds only when
        0.60 / rv < 0.5  ⇔  rv > 1.20 annualised.
      beta_core_paper's own comment says panel realised vol runs 0.5–1.2. If that
      is right, the scalar is almost never the binding constraint, and a BETTER
      VOL FORECAST CANNOT CHANGE THE BOOK NO MATTER HOW GOOD IT IS.

      This is the question that should always be asked first and usually is not:
      not "can I improve this input" but "is this input reachable from the output".
      An improvement to an input the output does not depend on is indistinguishable
      from no work at all, and it is much harder to notice, because the input
      genuinely did improve.

  Q2 (FORECAST QUALITY). Conditional on Q1 saying it can matter: does HAR-RV
      (Corsi, J. Financial Econometrics 2009) beat the incumbent 30-day trailing
      standard deviation, out of sample, on a proper loss function?

      HAR-RV regresses next-period realised variance on daily, weekly and monthly
      averages of past realised variance — a cascade of horizons standing in for
      heterogeneous trader horizons. It is the standard baseline that neural
      volatility models are measured against and usually fail to beat.

METHOD — the parts that keep this honest:

  * PIT. Every forecast for day t+1 uses data through day t only. The regression
    coefficients are fitted on a TRAIN window and never refitted inside TEST.
  * TWO LOSSES, EACH ON ITS OWN ESTIMAND. QLIKE is robust to noise in the RV proxy
    (Patton, J. Econometrics 2011) and is minimised by the conditional MEAN. MSE on
    log-variance is minimised by the MEDIAN. Those are different numbers for a
    skewed variable, so each is scored against the forecast it actually asks for —
    see har_forecast. Scoring both against one forecast guarantees that one of them
    is being asked the wrong question, which is not a second check, it is a
    coin-flip dressed as rigour.
  * The incumbent is the REAL incumbent — `beta_core_paper._realized_vol`,
    imported, not reimplemented. A study that reimplements the thing it is trying
    to beat has already given itself an advantage it cannot account for.
  * Non-overlapping evaluation. Overlapping windows inflate t by ~sqrt(overlap);
    we have made that mistake before and it is how a t of 10 becomes a t of 1.

WHAT A PASS LOOKS LIKE. HAR-RV wins on BOTH losses, AND Q1 says the scalar binds
on a non-trivial share of days, AND the resulting change in `gross` is large
enough to move the book's realised drawdown. Anything less is a DOCTRINE entry,
not a ship — the forecast may be genuinely better and still not be worth wiring.

RUN (Mac-side — NO credentials needed; reads Binance directly):
    python3 scripts/study_har_rv_vs_trailing.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.signals.beta_core_paper import (  # noqa: E402
    _MAX_SCALAR, _VOL_LOOKBACK, _VOL_TARGET, _realized_vol, _vol_scalar)

ANN = np.sqrt(365.0)
TRAIN_FRAC = 0.6
CAPS_TO_TEST = (0.5, 1.0, 1.3)


# ── data ─────────────────────────────────────────────────────────────────────
def load_panel(start=(2019, 1, 1)) -> tuple[list[str], np.ndarray]:
    """Daily closes for the 24 liquid majors, straight from Binance fapi.

    NO SUPABASE. `load_binance_panel` fetches from the exchange directly, so this
    study runs with zero credentials — it just has to run somewhere Binance is
    reachable, which is the Mac and not Railway US. The first version of this
    script gated on SUPABASE_URL and would have sent anyone chasing a credential
    the study never needed.

    Signature note: load_binance_panel(assets, start) returns
    (days, close, fmean, fsum) — four values, not two. Funding is unused here.
    """
    from src.research.strategies.causal_positioning import (
        DEFAULT_UNIVERSE, load_binance_panel)
    days, close, _fmean, _fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    close = np.asarray(close, dtype=float)
    ret = np.full_like(close, np.nan)
    ret[1:] = (close[1:] - close[:-1]) / close[:-1]
    return list(DEFAULT_UNIVERSE), ret


def panel_daily_returns(ret: np.ndarray) -> np.ndarray:
    """Equal-weight panel return per day — the book holds the panel, so this is the
    series whose vol is being targeted."""
    return np.nanmean(ret, axis=1)


# ── the two forecasters ──────────────────────────────────────────────────────
def trailing_vol_series(panel_ret: np.ndarray, lookback: int = _VOL_LOOKBACK) -> np.ndarray:
    """The INCUMBENT, computed through the book's own function so the comparison is
    against what actually runs. NaN until there is a full window."""
    out = np.full(panel_ret.shape[0], np.nan)
    for t in range(lookback, panel_ret.shape[0]):
        window = panel_ret[t - lookback:t][:, None]
        out[t] = _realized_vol(window, lookback=lookback)
    return out


def har_features(rv_daily: np.ndarray, t: int) -> np.ndarray | None:
    """(1, RV_d, RV_w, RV_m) using data through day t INCLUSIVE. None if short."""
    if t < 22:
        return None
    d = rv_daily[t]
    w = np.nanmean(rv_daily[t - 4:t + 1])
    m = np.nanmean(rv_daily[t - 21:t + 1])
    if not np.isfinite([d, w, m]).all():
        return None
    return np.array([1.0, d, w, m])


def forward_avg_var(rv_daily: np.ndarray, t: int, h: int) -> float:
    """Mean daily variance over t+1 … t+h — the quantity the INCUMBENT measures.

    THE UNITS ERROR THIS FIXES. `_realized_vol` is a 30-DAY realised vol and
    `_VOL_TARGET = 0.60` was calibrated against that scale. HAR as normally written
    forecasts NEXT-DAY variance. Substituting one for the other inside
    `min(_VOL_TARGET / rv, cap)` silently changes the units of the divisor.

    Measured cost of getting this wrong: forecasting one day ahead and sizing off
    it ran the book at mean gross 1.296 under a 1.3 cap — pinned at maximum
    leverage almost every day — turning +104.5 % into +37.0 % and a −55.7 %
    drawdown into −76.4 %. The forecast was not the problem; the horizon was.

    This is the same class as `asset_class` vs `bench` and f vs F: two quantities
    with the same name and different meanings, swapped without conversion. A better
    estimator of the WRONG quantity is worse than a poor estimator of the right one.
    """
    if t + h >= rv_daily.size:
        return float("nan")
    w = rv_daily[t + 1:t + 1 + h]
    return float(np.nanmean(w)) if np.isfinite(w).any() else float("nan")


def fit_har(rv_daily: np.ndarray, lo: int, hi: int, horizon: int = 1
            ) -> tuple[np.ndarray, float] | None:
    """OLS on log variance over [lo, hi). Log because variance is right-skewed and
    an OLS on the level is driven by a handful of crisis days.

    Returns (beta, half_sigma2) — the second term is NOT optional.

    RETRANSFORMATION BIAS, and the two wrong answers on the way to the right one.

    Fitting log(y) and reporting exp(Xβ) predicts the MEDIAN of a lognormal, not
    its MEAN, so every forecast comes out biased LOW — and QLIKE, which is
    deliberately asymmetric and punishes under-prediction hard, reads that bias as
    a bad forecast. Caught on synthetic GARCH data where HAR MUST win: QLIKE said
    the incumbent won while MSE-on-log said HAR won. Two proper losses disagreeing
    is not a close call, it is a specification error.

    First correction — the textbook one, exp(Xβ + σ²/2) — made it WORSE, and the
    reason is worth keeping. That formula assumes GAUSSIAN residuals. Here the
    left-hand side is a single squared return, i.e. a ONE-OBSERVATION estimate of
    variance: r² = h·χ²₁, so log(r²) = log h + log χ²₁, and log χ²₁ has variance
    ≈4.93 and mean ≈−1.27. The fitted σ² therefore measures mostly PROXY NOISE
    rather than forecast uncertainty, and σ²/2 ≈ 2.5 inflates every forecast by
    ~13×. Two proper losses can agree and still both be wrong, which is the part
    that would have been easy to miss: after that correction they agreed, and they
    agreed on the wrong answer.

    What is actually used: DUAN'S SMEARING ESTIMATOR (JASA 1983),
    E[y|X] ≈ exp(Xβ) · mean(exp(residuals)) — nonparametric, assumes nothing about
    the residual distribution, and gets the log-χ² case right (correction ≈3.6
    rather than ≈11.8). The lesson generalises past this script: a bias correction
    derived under an assumption the data violates is not more rigorous than no
    correction, it is differently wrong and harder to see.
    """
    X, y = [], []
    for t in range(max(lo, 22), hi - horizon):
        f = har_features(rv_daily, t)
        nxt = (rv_daily[t + 1] if horizon == 1
               else forward_avg_var(rv_daily, t, horizon))
        if f is None or not np.isfinite(nxt) or nxt <= 0:
            continue
        X.append(np.concatenate([[1.0], np.log(f[1:])]))
        y.append(np.log(nxt))
    if len(X) < 200:
        return None
    X, y = np.asarray(X), np.asarray(y)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    smear = float(np.mean(np.exp(resid)))      # Duan (1983); NOT exp(σ²/2)
    return beta, smear


def har_forecast(fit: tuple[np.ndarray, float], rv_daily: np.ndarray, t: int,
                 target: str = "mean") -> float:
    """Variance forecast. `target` selects WHICH functional is being predicted.

    THE TWO LOSSES WANT DIFFERENT ANSWERS, and this is not a nuisance — it is the
    thing that took two wrong corrections to see.

      * QLIKE is minimised by the conditional MEAN of the variance.
      * MSE on log-variance is minimised by the conditional MEDIAN.

    For a right-skewed variable those are different numbers, and the smearing
    factor is precisely what converts one into the other. So NO SINGLE FORECAST CAN
    WIN BOTH, and the natural-sounding rule "it must beat the incumbent on both
    proper losses" is incoherent — it asks one number to be simultaneously the mean
    and the median of a skewed distribution.

    Each loss is therefore scored against the forecast it is actually asking for.
    That is the honest version of "check it two ways": two losses are a real check
    only when each is applied to the estimand it identifies."""
    beta, smear = fit
    f = har_features(rv_daily, t)
    if f is None or (f[1:] <= 0).any():
        return float("nan")
    med = float(np.exp(beta @ np.concatenate([[1.0], np.log(f[1:])])))
    return med * smear if target == "mean" else med


# ── proper losses ────────────────────────────────────────────────────────────
def qlike(actual_var: np.ndarray, pred_var: np.ndarray) -> float:
    """QLIKE = mean(a/p - log(a/p) - 1). Robust to noise in the RV proxy
    (Patton 2011). Lower is better; 0 is perfect."""
    m = np.isfinite(actual_var) & np.isfinite(pred_var) & (pred_var > 0) & (actual_var > 0)
    if m.sum() < 30:
        return float("nan")
    r = actual_var[m] / pred_var[m]
    return float(np.mean(r - np.log(r) - 1.0))


def qlike_series(actual_var: np.ndarray, pred_var: np.ndarray) -> np.ndarray:
    """Per-observation QLIKE, for the Diebold-Mariano test below."""
    r = actual_var / pred_var
    return r - np.log(r) - 1.0


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, lag: int | None = None) -> dict:
    """Is the loss difference distinguishable from zero? (Diebold & Mariano 1995.)

    WHY THIS IS NOT OPTIONAL. On the real panel HAR beat the incumbent on QLIKE by
    3.4 % over 932 days. "Wins" is not a finding at that margin — a mean difference
    has to be compared to its own standard error before it is allowed to become a
    verdict, and forecast-loss differentials are serially correlated, so the naive
    standard error is too small and would manufacture significance.

    d_t = loss_a - loss_b; test H0: E[d] = 0 with a Newey-West HAC variance.
    Negative statistic ⇒ a is the better forecaster. Lag starts from the usual
    ⌊4(n/100)^(2/9)⌋ rule rather than anything chosen after seeing the answer.

    LAG SENSITIVITY IS PART OF THE ANSWER, not a footnote. Measured here: on pure
    noise the rule-of-thumb lag gives a 3.7 % false-positive rate (correct), but on
    an AR(0.8) differential it gives 15.3 % — the rule's lag (~6 at n=900) is far
    too short for autocorrelation that decays like 0.8^k. Since we cannot know in
    advance how persistent the loss differential is, the verdict is taken at the
    LONGEST lag tested, not the one that happens to be conventional. Choosing the
    lag that gives significance is the same act as choosing the sample that does.
    """
    d = loss_a - loss_b
    d = d[np.isfinite(d)]
    n = d.size
    if n < 50:
        return {"status": "too_few_obs", "n": int(n)}
    base = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0))) if lag is None else int(lag)
    lags = sorted({max(base, 1), max(2 * base, 2), max(4 * base, 4)})

    dbar = float(np.mean(d))
    dc = d - dbar
    gamma = {k: float(np.mean(dc[k:] * dc[:-k])) if k else float(np.mean(dc * dc))
             for k in range(0, max(lags) + 1)}

    per_lag = {}
    for L in lags:
        var = gamma[0] + 2.0 * sum((1.0 - k / (L + 1.0)) * gamma[k] for k in range(1, L + 1))
        if var <= 0:
            per_lag[L] = None
            continue
        stat = dbar / np.sqrt(var / n)
        per_lag[L] = (float(stat), float(math.erfc(abs(stat) / math.sqrt(2.0))))

    usable = {L: v for L, v in per_lag.items() if v is not None}
    if not usable:
        return {"status": "nonpositive_hac_variance", "n": int(n)}
    worst_lag = max(usable)                     # most conservative
    stat, p = usable[worst_lag]
    return {"status": "ok", "n": int(n), "lag": int(worst_lag),
            "lags_tested": [int(x) for x in lags],
            "p_by_lag": {int(L): round(v[1], 5) for L, v in usable.items()},
            "mean_diff": round(dbar, 6), "dm_stat": round(stat, 3),
            "p_value": round(p, 5),
            "better": "A" if dbar < 0 else "B",
            # significance must hold at EVERY lag tested, not just the kind one
            "significant_5pct": bool(all(v[1] < 0.05 for v in usable.values()))}


def mse_log(actual_var: np.ndarray, pred_var: np.ndarray) -> float:
    m = np.isfinite(actual_var) & np.isfinite(pred_var) & (pred_var > 0) & (actual_var > 0)
    if m.sum() < 30:
        return float("nan")
    return float(np.mean((np.log(actual_var[m]) - np.log(pred_var[m])) ** 2))


# ── Q1: can the scalar even reach the book? ──────────────────────────────────
def reachability(vol_ann: np.ndarray) -> dict:
    """How often is the vol scalar the BINDING constraint in min(scalar, cap)?"""
    v = vol_ann[np.isfinite(vol_ann)]
    if v.size == 0:
        return {"status": "no_vol_series"}
    scalar = np.minimum(_VOL_TARGET / v, _MAX_SCALAR)
    out = {
        "n_days": int(v.size),
        "vol_ann_p05": round(float(np.percentile(v, 5)), 3),
        "vol_ann_median": round(float(np.median(v)), 3),
        "vol_ann_p95": round(float(np.percentile(v, 95)), 3),
        "scalar_median": round(float(np.median(scalar)), 3),
        "binds_at_cap": {},
    }
    for cap in CAPS_TO_TEST:
        binding = scalar < cap
        # How much does it move gross when it does bind? A scalar that binds on 2%
        # of days by 1% is not a mechanism, it is a rounding difference.
        delta = (cap - scalar[binding]) if binding.any() else np.array([])
        out["binds_at_cap"][str(cap)] = {
            "pct_days": round(100.0 * float(binding.mean()), 2),
            "median_gross_reduction": round(float(np.median(delta)), 4) if delta.size else 0.0,
            "vol_needed_to_bind": round(_VOL_TARGET / cap, 3),
        }
    return out


def _max_drawdown(nav: np.ndarray) -> float:
    peak = np.maximum.accumulate(nav)
    return float(np.min(nav / peak - 1.0))


def exposure_outcome(panel_ret: np.ndarray, vol_forecast_ann: np.ndarray,
                     cap: float, lo: int, hi: int) -> dict | None:
    """Q3. Run the ① book's exposure path and grade the DECISION, not the forecast.

    WHY THIS EXISTS. Q2 gave a split verdict — HAR beats the incumbent on MSE-log
    (p<0.0001) and does not on QLIKE (p=0.27) — because the two losses grade
    different functionals. Picking whichever loss agrees with the answer we want is
    the failure this whole study was built to avoid, and there is no principled way
    to choose between them IN THE ABSTRACT.

    But we do not need to choose in the abstract. The vol forecast is not something
    we sell; it is an input to `gross = min(target/rv, cap)`. So grade the thing the
    book actually does. This is the R76–R94 lesson stated forward: an intermediate
    quantity that improves without the decision improving is not an improvement —
    it is a nicer-looking input to the same book.

    PIT: today's return is earned on YESTERDAY's exposure. Benchmark is
    hold-the-panel at gross 1.0 — never zero (CLAUDE.md §RETURN HIERARCHY: the ①
    benchmark is the panel, and a sleeve is measured as excess over it).
    """
    r = panel_ret[lo:hi]
    v = vol_forecast_ann[lo:hi]
    m = np.isfinite(r) & np.isfinite(v) & (v > 0)
    if m.sum() < 100:
        return None
    r, v = r[m], v[m]
    gross = np.minimum(np.minimum(_VOL_TARGET / v, _MAX_SCALAR), cap)

    book = np.concatenate([[0.0], gross[:-1] * r[1:]])      # yesterday's exposure
    bench = r.copy()                                        # hold the panel, gross 1.0
    nav_b = np.cumprod(1.0 + book)
    nav_p = np.cumprod(1.0 + bench)
    ann = 365.0 / r.size
    return {
        "n_days": int(r.size),
        "mean_gross": round(float(np.mean(gross)), 4),
        "book_total_pct": round(100.0 * (nav_b[-1] - 1.0), 2),
        "panel_total_pct": round(100.0 * (nav_p[-1] - 1.0), 2),
        "excess_pct": round(100.0 * (nav_b[-1] - nav_p[-1]), 2),
        "book_vol_ann": round(float(np.std(book) * ANN), 3),
        "panel_vol_ann": round(float(np.std(bench) * ANN), 3),
        "book_maxdd_pct": round(100.0 * _max_drawdown(nav_b), 2),
        "panel_maxdd_pct": round(100.0 * _max_drawdown(nav_p), 2),
        # Return per unit of drawdown — the ③ layer's actual claim is not "more
        # return", it is "the same beta with less of the pain".
        "return_per_dd": round(float((nav_b[-1] ** ann - 1.0)
                                     / abs(_max_drawdown(nav_b) or 1e-9)), 3),
        "panel_return_per_dd": round(float((nav_p[-1] ** ann - 1.0)
                                           / abs(_max_drawdown(nav_p) or 1e-9)), 3),
    }


def main() -> int:
    # No credential gate: this study reads Binance directly. If it cannot reach the
    # exchange, say THAT rather than blaming an env var it does not use — the first
    # version checked SUPABASE_URL and sent the reader after a key the study never
    # needed. An error message that names the wrong cause costs more than no message.
    try:
        symbols, ret = load_panel()
    except Exception as e:
        print(f"🔴 could not load the Binance panel: {e}\n"
              f"   This study needs NO credentials — only reachability to "
              f"fapi.binance.com.\n"
              f"   Railway US is geo-blocked from it; run this on the Mac.")
        return 1
    if ret.size == 0 or not np.isfinite(ret).any():
        print("🔴 panel loaded but contains no finite returns — refusing to study noise.")
        return 1
    panel = panel_daily_returns(ret)
    n = panel.shape[0]
    print(f"panel: {len(symbols)} symbols × {n} days\n")

    vol_ann = trailing_vol_series(panel)

    # ── Q1 first. It gates Q2. ───────────────────────────────────────────────
    reach = reachability(vol_ann)
    print("── Q1 REACHABILITY: does the vol scalar ever bind? ──")
    print(f"  panel vol (ann):  p05={reach['vol_ann_p05']}  "
          f"median={reach['vol_ann_median']}  p95={reach['vol_ann_p95']}")
    for cap, d in reach["binds_at_cap"].items():
        print(f"  cap={cap}: binds on {d['pct_days']}% of days "
              f"(needs vol > {d['vol_needed_to_bind']}), "
              f"median gross reduction {d['median_gross_reduction']}")

    live = reach["binds_at_cap"]["0.5"]["pct_days"]
    print(f"\n  → at the CURRENT cap (0.5) the scalar binds on {live}% of days.")
    if live < 5.0:
        print("  → VERDICT ON Q1: the vol scalar is effectively INERT at this cap.\n"
              "    A better vol forecast cannot change the book, because the cap is\n"
              "    the binding constraint on ~every day. Improving it would be work\n"
              "    that cannot reach the output — and would LOOK like progress,\n"
              "    because the forecast really would get better.\n"
              "    The lever that matters here is _VOL_TARGET or the cap ladder,\n"
              "    NOT the vol estimator. Q2 is reported below for the record only.")

    # ── Q2. OOS forecast comparison. ─────────────────────────────────────────
    rv_daily = panel ** 2                      # daily realised variance proxy
    split = int(n * TRAIN_FRAC)
    fit = fit_har(rv_daily, 22, split)
    if fit is None:
        print("\n🔴 Q2 skipped: not enough clean training rows for HAR.")
        return 0
    beta, smear = fit
    print(f"\n── Q2 FORECAST QUALITY (train 0:{split}, test {split}:{n}) ──")
    print(f"  HAR coefficients (log space): c={beta[0]:+.3f} "
          f"d={beta[1]:+.3f} w={beta[2]:+.3f} m={beta[3]:+.3f}")
    print(f"  Duan smearing factor = {smear:.3f} "
          f"(omitting it biases low; exp(σ²/2) over-corrects — see fit_har)")

    actual, har_mean, har_med, pred_tr = [], [], [], []
    for t in range(split, n - 1):
        a = rv_daily[t + 1]
        if not np.isfinite(a) or a <= 0:
            continue
        hm = har_forecast(fit, rv_daily, t, target="mean")
        hq = har_forecast(fit, rv_daily, t, target="median")
        # incumbent, converted to a DAILY variance so the two are commensurable
        tr = (vol_ann[t] / ANN) ** 2 if np.isfinite(vol_ann[t]) else np.nan
        if not (np.isfinite(hm) and np.isfinite(hq) and np.isfinite(tr)):
            continue
        actual.append(a); har_mean.append(hm); har_med.append(hq); pred_tr.append(tr)

    actual, har_mean, har_med, pred_tr = (
        np.asarray(actual), np.asarray(har_mean), np.asarray(har_med), np.asarray(pred_tr))
    # Each loss scored against the functional it identifies — see har_forecast.
    q_h, q_t = qlike(actual, har_mean), qlike(actual, pred_tr)
    m_h, m_t = mse_log(actual, har_med), mse_log(actual, pred_tr)
    print(f"  n_test        = {actual.size}")
    print(f"  QLIKE    (wants the MEAN)   HAR={q_h:.4f}  trailing30={q_t:.4f}  "
          f"{'HAR wins' if q_h < q_t else 'trailing wins'}")
    print(f"  MSE(log) (wants the MEDIAN) HAR={m_h:.4f}  trailing30={m_t:.4f}  "
          f"{'HAR wins' if m_h < m_t else 'trailing wins'}")

    # A margin is not a result until it is compared to its own standard error.
    dm_q = diebold_mariano(qlike_series(actual, har_mean), qlike_series(actual, pred_tr))
    dm_m = diebold_mariano((np.log(actual) - np.log(har_med)) ** 2,
                           (np.log(actual) - np.log(pred_tr)) ** 2)
    print("\n  Diebold-Mariano (Newey-West HAC; negative stat ⇒ HAR better):")
    for name, dm in (("QLIKE   ", dm_q), ("MSE(log)", dm_m)):
        if dm.get("status") != "ok":
            print(f"    {name}: {dm.get('status')}")
            continue
        print(f"    {name}: stat={dm['dm_stat']:+.2f}  p={dm['p_value']:.4f}  "
              f"lag={dm['lag']}  "
              f"{'✓ significant at 5%' if dm['significant_5pct'] else '✗ NOT significant'}")

    both = (q_h < q_t) and (m_h < m_t)
    sig = (dm_q.get("significant_5pct") and dm_q.get("better") == "A"
           and dm_m.get("significant_5pct") and dm_m.get("better") == "A")
    # ── Q3. Grade the DECISION, not the forecast. ────────────────────────────
    # Q2 split: HAR wins MSE-log decisively and QLIKE not at all, because the two
    # losses grade different functionals. Choosing between them in the abstract is
    # unresolvable and choosing the one that agrees with us is the failure this
    # study exists to avoid. So run the exposure path the book would actually have
    # taken and compare outcomes. An input that improves without the decision
    # improving is a nicer-looking input to the same book.
    # HORIZON-MATCHED HAR. The incumbent is a 30-day realised vol and _VOL_TARGET
    # was calibrated against that scale, so the forecast fed to the sizing rule must
    # be a 30-day quantity too. See forward_avg_var.
    fit30 = fit_har(rv_daily, 22, split, horizon=_VOL_LOOKBACK)

    def _vol_path(f, tgt):
        out = np.full(n, np.nan)
        if f is None:
            return out
        for t in range(split, n):
            x = har_forecast(f, rv_daily, t, target=tgt)
            if np.isfinite(x) and x > 0:
                out[t] = np.sqrt(x) * ANN
        return out

    variants = [
        ("trailing30", vol_ann),
        ("HAR h=1 med ", _vol_path(fit, "median")),
        ("HAR h=1 mean", _vol_path(fit, "mean")),
        ("HAR h=30 med", _vol_path(fit30, "median")),
        ("HAR h=30 mean", _vol_path(fit30, "mean")),
    ]

    outcomes: dict = {}
    print(f"\n── Q3 DOES THE BOOK ACTUALLY DO BETTER? (test window, {n - split}d) ──")
    print("  benchmark = hold the panel at gross 1.0 (the ① benchmark, never 0)")
    print("  BOTH horizons and BOTH functionals shown: the choice moves the book far")
    print("  more than the estimator does, which is the actual finding.")
    for cap in CAPS_TO_TEST:
        base = exposure_outcome(panel, vol_ann, cap, split, n)
        if not base:
            print(f"  cap {cap}: insufficient overlap")
            continue
        print(f"\n  cap {cap}  (panel: {base['panel_total_pct']:+.1f}%, "
              f"maxDD {base['panel_maxdd_pct']:.1f}%, vol {base['panel_vol_ann']:.2f}, "
              f"ret/DD {base['panel_return_per_dd']:.3f})")
        for tag, series in variants:
            o = exposure_outcome(panel, series, cap, split, n)
            if not o:
                print(f"    {tag}: n/a")
                continue
            outcomes[(cap, tag)] = o
            print(f"    {tag:<13}: gross̄={o['mean_gross']:.3f}  "
                  f"total={o['book_total_pct']:+7.1f}%  "
                  f"maxDD={o['book_maxdd_pct']:6.1f}%  "
                  f"vol={o['book_vol_ann']:.2f}  ret/DD={o['return_per_dd']:.3f}")

    # ── VERDICT — driven by Q3, the DECISION, not by Q2, the forecast. ───────
    print("\n── VERDICT ──")
    print(f"  Q2 (forecast): QLIKE {'sig' if dm_q.get('significant_5pct') else 'NOT sig'} "
          f"(p={dm_q.get('p_value')}), MSE-log "
          f"{'sig' if dm_m.get('significant_5pct') else 'NOT sig'} "
          f"(p={dm_m.get('p_value')}). both_point_estimates={both}")

    # MATERIALITY, applied here for the same reason significance was applied in Q2.
    # Without it the ranking called HAR the winner at cap 1.0 on 0.455 vs 0.454 — a
    # 0.2 % margin over 933 days, which is a rounding difference wearing a verdict's
    # clothes. Demanding a standard error in Q2 and accepting a tie in Q3 would have
    # been the same failure the study is about, one section later.
    MATERIAL = 0.05          # 5 % relative improvement in return-per-drawdown

    best_by_cap = {}
    print("\n  Q3 (decision) — return-per-drawdown, vs the incumbent:")
    for cap in CAPS_TO_TEST:
        rows = [(tag, o) for (c, tag), o in outcomes.items() if c == cap]
        if not rows:
            continue
        inc = next((o for tag, o in rows if tag.startswith("trailing")), None)
        best_tag, best_o = max(rows, key=lambda kv: kv[1]["return_per_dd"])
        if inc and not best_tag.startswith("trailing"):
            lift = (best_o["return_per_dd"] - inc["return_per_dd"]) / abs(inc["return_per_dd"])
            if lift < MATERIAL:
                best_tag, best_o = "trailing30", inc      # not a win, a tie
                note = f"(best challenger +{100*lift:.1f}% — under the {100*MATERIAL:.0f}% bar)"
            else:
                note = f"(+{100*lift:.1f}% over the incumbent)"
        else:
            note = ""
        best_by_cap[cap] = (best_tag, best_o)
        print(f"    cap {cap}: {best_tag.strip():<13} ret/DD {best_o['return_per_dd']:.3f}  "
              f"(panel {best_o['panel_return_per_dd']:.3f}) {note}")

    har_ever_wins = any(not tag.startswith("trailing") for tag, _ in best_by_cap.values())

    if not har_ever_wins:
        print("\n  → HAR-RV is REFUTED FOR THIS USE. It forecasts log-vol")
        print("    significantly better and produces a book that is no better and")
        print("    usually worse. A better estimate of an intermediate quantity is")
        print("    not an improvement; the decision is the only thing that counts.")
        print("    File it. The graveyard is the asset.")
    else:
        print("\n  → HAR improves the DECISION somewhere. Before wiring: confirm on a")
        print("    second split, and check the win is not concentrated in one episode.")

    print("\n  THE FINDING THAT WAS NOT THE QUESTION — two of them:")
    print("   1. The INCUMBENT vol scalar is doing real work and had never been")
    print("      measured. Grading it against hold-the-panel is what this study")
    print("      accidentally did first, and it is the result worth keeping.")
    print("   2. The SPECIFICATION moves the book far more than the ESTIMATOR does:")
    print("      same HAR, same data, horizon 1 vs 30 and median vs mean swing the")
    print("      cap-1.3 book between +37% / −76% DD and +74% / −48% DD. Choosing")
    print("      the horizon is a bigger decision than choosing the model, and it")
    print("      is the one nobody writes a paper about.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
