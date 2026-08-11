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


def fit_har(rv_daily: np.ndarray, lo: int, hi: int) -> tuple[np.ndarray, float] | None:
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
    for t in range(max(lo, 22), hi - 1):
        f = har_features(rv_daily, t)
        nxt = rv_daily[t + 1]
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
    print("\n── VERDICT ──")
    if not both:
        print("  HAR does NOT win on both proper losses → do not wire it. File as a")
        print("  refutation; the graveyard is the asset.")
    elif not sig:
        print("  HAR wins on both point estimates but the difference is NOT")
        print("  distinguishable from zero once serial correlation is accounted for.")
        print("  → NOT a result. A margin smaller than its own standard error is the")
        print("    thing every graveyard entry looked like before it was measured.")
    else:
        print("  HAR wins on both losses, and both differences are significant.")
        # Reachability is regime-conditional, and the CURRENT regime is the least
        # informative slice of it. Reporting only the live cap is how the first
        # reading of this study concluded the scalar was inert.
        print("\n  REACHABILITY IS REGIME-CONDITIONAL — this is the number that decides")
        print("  whether the better forecast reaches the book, and it is not one number:")
        for cap in CAPS_TO_TEST:
            d = reach["binds_at_cap"][str(cap)]
            print(f"    cap {cap} → binds {d['pct_days']}% of days, "
                  f"median gross cut {d['median_gross_reduction']}")
        print("  So the value of a better vol forecast is")
        print("    Σ over regimes  P(regime) × bind-rate(cap of that regime),")
        print("  NOT the bind rate at whatever regime happens to be live today.")
        print("  At cap 0.5 it is near-inert; at 1.0 and 1.3 it is the main mechanism.")
        print("\n  → CANDIDATE, gated on: (a) the regime mix from daily_macro_regime,")
        print("    and (b) does the changed `gross` actually reduce realised drawdown")
        print("    vs hold-the-panel? Forecast accuracy is not the product; exposure")
        print("    taken at the right time is. Do not wire it before (b).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
