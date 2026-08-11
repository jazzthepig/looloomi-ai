"""
Guard: the HAR-RV study's estimator is correctly specified (S-134).

This suite exists because the study produced THREE different verdicts on synthetic
data where the answer is known by construction, and only the third was right. A
study that can be wrong in three ways without looking wrong is not a study, it is
a number generator, and the ledger would have recorded whichever run happened to
finish first.

  1. exp(Xβ) alone — predicts the MEDIAN, so every forecast is biased low. QLIKE
     punishes under-prediction hard and declared the incumbent the winner.
  2. exp(Xβ + σ²/2) — the textbook Gaussian correction. WORSE. The left-hand side
     is a single squared return, i.e. a one-observation variance estimate, so
     log(r²) carries log-χ²₁ noise (variance ≈4.93). The fitted σ² measures mostly
     PROXY NOISE, and σ²/2 ≈ 2.5 inflated every forecast by ~13×. Both losses then
     agreed — on the wrong answer.
  3. Duan's smearing, exp(Xβ)·mean(exp(resid)) — nonparametric, assumes nothing
     about the residual distribution, correction ≈3.6 instead of ≈11.8.

Plus the structural point that took the longest to see: QLIKE and MSE-on-log are
not two checks of one thing. QLIKE is minimised by the conditional MEAN, MSE-on-log
by the MEDIAN. For a skewed variable those are different numbers and the smearing
factor is exactly what maps between them — so "must beat the incumbent on both
proper losses" is incoherent unless each loss is scored against the functional it
identifies.

Run: python3 -m tests.test_har_rv_study_is_specified_correctly
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


_STUDY_SRC = (_ROOT / "scripts/study_har_rv_vs_trailing.py").read_text()


def _strip_comments_and_strings(src: str) -> str:
    """Executable code only — comments and string literals removed.

    Guards that grep raw source fire on the prose describing the bug they guard
    against. That has now happened three times in this codebase (the S-122 batch,
    the beta_core_nav read-path scanner, and here), so the pattern is: a guard
    whose subject is CODE must be given code."""
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        return src
    return " ".join(out)


_STUDY_CODE = _strip_comments_and_strings(_STUDY_SRC)


def _load_study() -> types.ModuleType:
    """Load the study with its beta_core import stubbed — the guard must run inside
    the offline preflight, and the real import wants Supabase env."""
    src = (_ROOT / "scripts/study_har_rv_vs_trailing.py").read_text()
    src = src.replace(
        "from src.data.signals.beta_core_paper import (  # noqa: E402\n"
        "    _MAX_SCALAR, _VOL_LOOKBACK, _VOL_TARGET, _realized_vol, _vol_scalar)",
        "_MAX_SCALAR=1.3\n_VOL_LOOKBACK=30\n_VOL_TARGET=0.60\n"
        "def _realized_vol(w, lookback=30):\n"
        "    p=np.nanmean(w,axis=1); s=float(np.nanstd(p)); return s*np.sqrt(365.0)\n"
        "def _vol_scalar(rv): return 1.0")
    src = src.replace("sys.path.insert(0, str(Path(__file__).resolve().parents[1]))", "")
    m = types.ModuleType("har_study")
    exec(compile(src, "study_har_rv_vs_trailing.py", "exec"), m.__dict__)
    return m


_S = _load_study()


def _garch(seed: int, n: int = 3000) -> np.ndarray:
    """Persistent stochastic vol — HAR MUST beat a flat trailing window here."""
    rng = np.random.default_rng(seed)
    h = np.zeros(n); h[0] = 1e-4; r = np.zeros(n)
    for t in range(1, n):
        h[t] = 2e-6 + 0.09 * r[t - 1] ** 2 + 0.90 * h[t - 1]
        r[t] = rng.normal(0, np.sqrt(h[t]))
    return r


def _score(seed: int) -> tuple[bool, bool, float]:
    r = _garch(seed)
    rv = r ** 2
    fit = _S.fit_har(rv, 22, 1800)
    vol = _S.trailing_vol_series(r)
    a, hm, hq, tr = [], [], [], []
    for t in range(1800, r.size - 1):
        x = rv[t + 1]
        if x <= 0 or not np.isfinite(x):
            continue
        f1 = _S.har_forecast(fit, rv, t, "mean")
        f2 = _S.har_forecast(fit, rv, t, "median")
        b = (vol[t] / np.sqrt(365.0)) ** 2
        if not (np.isfinite(f1) and np.isfinite(f2) and np.isfinite(b)):
            continue
        a.append(x); hm.append(f1); hq.append(f2); tr.append(b)
    a, hm, hq, tr = map(np.asarray, (a, hm, hq, tr))
    return (_S.qlike(a, hm) < _S.qlike(a, tr),
            _S.mse_log(a, hq) < _S.mse_log(a, tr),
            fit[1])


def test_har_beats_trailing_where_it_must() -> None:
    """The study's own positive control. If HAR cannot win on persistent synthetic
    vol, the study cannot be trusted to say it loses on real data."""
    res = [_score(s) for s in (7, 11, 23, 42, 99)]
    q = sum(1 for a, _, _ in res if a)
    m = sum(1 for _, b, _ in res if b)
    check("QLIKE picks HAR on all 5 synthetic seeds", q == 5, f"{q}/5")
    check("MSE(log) picks HAR on all 5 synthetic seeds", m == 5, f"{m}/5")
    check("the two losses never disagree once matched to their functionals",
          all(a == b for a, b, _ in res), str([(a, b) for a, b, _ in res]))


def test_the_smearing_factor_is_duan_not_gaussian() -> None:
    """The correction that made it worse. For log-χ²₁ residuals the Gaussian
    exp(σ²/2) lands near 11.8 while Duan's smearing lands near 3.6 — a 3x
    over-correction that both losses then endorsed."""
    smears = [s for _, _, s in (_score(x) for x in (7, 11, 23))]
    for s in smears:
        check(f"smearing factor {s:.2f} is in the Duan range, not the Gaussian one",
              2.0 < s < 6.0,
              "≈11.8 means exp(sigma^2/2) crept back in; ≈1.0 means no correction")
    doc = _S.fit_har.__doc__ or ""
    check("fit_har records why the Gaussian correction was rejected",
          "duan" in doc.lower() and "χ²" in doc and "σ²/2" in doc,
          f"the reasoning must survive in the code; doc len={len(doc)}")
    check("the Gaussian form is not what actually runs",
          "np.var(resid) / 2.0" not in _STUDY_SRC
          and "np.mean(np.exp(resid))" in _STUDY_SRC,
          "exp(sigma^2/2) crept back into the estimator")


def test_the_two_losses_are_scored_against_different_functionals() -> None:
    """The structural point. QLIKE identifies the mean, MSE-on-log the median, and
    one forecast cannot be both. Scoring both losses against the SAME forecast
    guarantees one of them is being asked the wrong question."""
    src = _STUDY_SRC
    check("QLIKE is scored on the mean forecast",
          "qlike(actual, har_mean)" in src, "")
    check("MSE(log) is scored on the median forecast",
          "mse_log(actual, har_med)" in src, "")
    doc = _S.har_forecast.__doc__ or ""
    check("har_forecast documents the mean/median split",
          "MEAN" in doc and "MEDIAN" in doc, "")


def test_reachability_gates_the_forecast_question() -> None:
    """Q1 before Q2. Improving an input the output does not depend on is
    indistinguishable from no work, and harder to notice, because the input really
    did improve. With _VOL_TARGET=0.60 and cap 0.5 the scalar binds only above
    vol 1.2 annualised."""
    src = (_ROOT / "scripts/study_har_rv_vs_trailing.py").read_text()
    check("the study computes reachability", "def reachability" in src, "")
    check("reachability is reported BEFORE the forecast comparison",
          src.index("Q1 REACHABILITY") < src.index("Q2 FORECAST QUALITY"), "")
    # the binding threshold is arithmetic, not opinion: vol > target/cap
    r = _S.reachability(np.full(500, 0.8))      # 0.8 vol: scalar 0.75
    check("at vol 0.8 the scalar does NOT bind under a 0.5 cap",
          r["binds_at_cap"]["0.5"]["pct_days"] == 0.0,
          str(r["binds_at_cap"]["0.5"]))
    check("at vol 0.8 the scalar DOES bind under a 1.0 cap",
          r["binds_at_cap"]["1.0"]["pct_days"] == 100.0,
          str(r["binds_at_cap"]["1.0"]))
    check("the vol needed to bind is reported, not left to be derived",
          r["binds_at_cap"]["0.5"]["vol_needed_to_bind"] == 1.2, "")


def test_a_margin_must_beat_its_own_standard_error() -> None:
    """On the real panel HAR beat the incumbent on QLIKE by 3.4 % over 932 days.
    "Wins" is not a finding at that margin. Forecast-loss differentials are serially
    correlated, so a naive standard error manufactures significance."""
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 900)
    r = _S.diebold_mariano(x, x + 0.4)
    check("a real effect is detected", r["significant_5pct"] and r["better"] == "A",
          str(r))
    check("multiple lags are tested, not one", len(r["lags_tested"]) >= 3,
          str(r.get("lags_tested")))

    fp = sum(_S.diebold_mariano(np.random.default_rng(s).normal(0, 1, 900),
                                np.random.default_rng(9000 + s).normal(0, 1, 900)
                                )["significant_5pct"] for s in range(200))
    check(f"pure-noise false-positive rate {100*fp/200:.1f}% is near 5%",
          fp / 200 <= 0.08, f"{fp}/200")

    # The reason the lag ladder exists: at the conventional lag alone this
    # over-rejected at 15.3%.
    hits = 0
    for s in range(200):
        g = np.random.default_rng(1000 + s)
        e = g.normal(0, 1, 900); ar = np.zeros(900)
        for t in range(1, 900):
            ar[t] = 0.8 * ar[t - 1] + e[t]
        hits += _S.diebold_mariano(ar, np.zeros(900))["significant_5pct"]
    check(f"AR(0.8) differential rejects at {100*hits/200:.1f}%, not 15%",
          hits / 200 <= 0.10, f"{hits}/200 — the lag ladder is not doing its job")

    check("the verdict is taken at the LONGEST lag, not the kindest",
          "all(v[1] < 0.05 for v in usable.values())" in _STUDY_CODE
          or "all(v[1] < 0.05" in _STUDY_SRC,
          "significance must hold at every lag tested")


def test_reachability_is_reported_for_every_cap_not_just_the_live_one() -> None:
    """The first reading of this study concluded the vol scalar was inert because it
    looked only at the cap that happened to be live (0.5, binds 6.4 % of days). At
    cap 1.0 it binds on 71 % of days and at 1.3 on 92 % — it is the MAIN mechanism
    outside TIGHTENING. Reachability is regime-conditional, and reporting the live
    slice alone inverts the conclusion."""
    src = _STUDY_SRC
    check("all three caps are tested", "CAPS_TO_TEST = (0.5, 1.0, 1.3)" in src, "")
    check("the verdict states the regime-weighted form",
          "P(regime) × bind-rate" in src,
          "the value is a sum over regimes, not the live bind rate")
    check("the verdict does not stop at the live cap",
          "REACHABILITY IS REGIME-CONDITIONAL" in src, "")


def test_the_study_needs_no_credentials() -> None:
    """The study reads Binance directly. Its first version gated on SUPABASE_URL,
    so the failure message sent the reader after a credential the study never used
    — and the credential in question (SUPABASE_KEY) happens to be empty on the Mac,
    which would have looked like confirmation. An error naming the wrong cause is
    more expensive than no error, because it is followed."""
    # Read CODE, not commentary. The docstring explaining this very fix names
    # SUPABASE_URL, and matching raw text would fire the guard on its own
    # documentation — the S-122 defect, third appearance this session.
    check("no SUPABASE gate in executable code",
          "SUPABASE_URL" not in _STUDY_CODE and "SUPABASE_KEY" not in _STUDY_CODE,
          "the study does not use Supabase; it must not check for it")
    src = _STUDY_SRC
    check("failure names reachability, not a key",
          "fapi.binance.com" in src and "geo-blocked" in src, "")
    check("panel loader is called with the universe it needs",
          "load_binance_panel(DEFAULT_UNIVERSE, start=start)" in src,
          "load_binance_panel(assets, start) takes the asset list")
    check("the loader's 4-tuple return is unpacked correctly",
          "days, close, _fmean, _fsum = load_binance_panel" in src,
          "it returns (days, close, fmean, fsum), not (symbols, close)")


def test_the_incumbent_is_imported_not_reimplemented() -> None:
    """A study that reimplements the thing it is trying to beat has given itself an
    advantage it cannot account for."""
    src = (_ROOT / "scripts/study_har_rv_vs_trailing.py").read_text()
    check("the study imports the book's own _realized_vol",
          "from src.data.signals.beta_core_paper import" in src
          and "_realized_vol" in src, "")
    check("trailing_vol_series calls it rather than recomputing a stdev",
          "_realized_vol(window" in src, "")


def test_forecasts_are_point_in_time() -> None:
    """A forecast for t+1 that touches t+1 is not a forecast."""
    src = _STUDY_SRC
    check("har_features slices only up to t inclusive",
          "rv_daily[t - 4:t + 1]" in src and "rv_daily[t - 21:t + 1]" in src, "")
    check("training stops before the test split",
          "range(max(lo, 22), hi - 1)" in src, "")
    check("no feature window reaches past t",
          "t + 2" not in src and "rv_daily[t + 1]" in src,
          "rv_daily[t+1] should appear only as the TARGET, never as a feature")


if __name__ == "__main__":
    print("── HAR-RV study specification (S-134) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ HAR-RV study is correctly specified")
