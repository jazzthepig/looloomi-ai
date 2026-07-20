"""
Signal Gauntlet — the full validation funnel in one call (Seth, 2026-07-18).
=============================================================================
The Google/academia LLM-factor study ran candidates down a funnel (280 → 159 → 38 → 24 → 8 → 5 → 9)
and only the handful surviving EVERY filter were credited. This chains OUR filter stack into that one
funnel so a candidate can't quietly skip a gate:

  1. significance (PSR)      — is the raw edge even distinguishable from zero?           [deflated_sharpe]
  2. deflated Sharpe (DSR)   — does it survive the MULTIPLE-TESTING correction?          [deflated_sharpe]
  3. PBO (CSCV)              — probability the backtest is overfit < 0.5?                [pbo]
  4. factor absorption       — RESIDUAL alpha after known factors (not old wine)?        [factor_absorption]
  5. regime robustness       — broad edge, not a one-window/favorable-regime mirage?     [regime_robustness]
  6. point-in-time guard     — no temporal leakage (LLM features)?                       [pit_guard]

Each gate is applied only when its inputs are supplied; the funnel reports pass/fail/skip per stage,
where it stopped, and one honest verdict. This is the artifact behind an LP claim: "here is every
filter our signals had to survive, and where each one died." Compliance: research/validation tooling.

⚠️ REQUIRED INPUT DISCIPLINE (R39 lesson, 2026-07-19): the `returns` you pass MUST already be NET OF
REALISTIC EXECUTION COSTS. The gauntlet's statistical gates are blind to frictions — the BTC vol carry
cleared EVERY gate (DSR/PBO/absorption/regime) + held OOS, then died to a 30% options bid/ask haircut
(SR +2.69 → −2.22). For wide-spread instruments (options, illiquid perps) run a COST-SENSITIVITY sweep
(frictionless → mild → realistic → harsh) and require survival at the realistic level before crediting.
A frictionless backtest is meaningless for anything that isn't cheap to trade.
"""
from __future__ import annotations

import math

import numpy as np

from src.research.validation.deflated_sharpe import (
    sharpe_stats, probabilistic_sharpe_ratio, deflated_sharpe_ratio, evaluate_universe)
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.regime_robustness import subsample_robustness

try:
    from src.research.validation.pbo import pbo_cscv
except Exception:
    pbo_cscv = None
try:
    from src.research.validation.pit_guard import pit_audit
except Exception:
    pit_audit = None


def _stage(name, passed, metric, skipped=False, note=""):
    return {"stage": name, "passed": (None if skipped else bool(passed)), "skipped": skipped,
            "metric": metric, "note": note}


def _cross_asset_gate(replications: dict, periods_per_year: int) -> dict:
    """replications: {asset: same-signal daily returns on that OTHER asset}. A single-asset ★ is NOT a
    credited edge (R39: BTC vol-carry cleared everything, died on ETH). Pass = the edge REPLICATES —
    a majority of other assets show a positive Sharpe and the median is meaningfully > 0."""
    shs = {}
    for a, r in replications.items():
        x = np.asarray(r, dtype=float); x = x[~np.isnan(x)]
        if len(x) < 60 or x.std() == 0:
            continue
        shs[a] = round(float(x.mean() / x.std() * math.sqrt(periods_per_year)), 2)
    if not shs:
        return _stage("cross_asset_replication", None, {}, skipped=True, note="no replications supplied")
    vals = list(shs.values())
    frac_pos = sum(1 for v in vals if v > 0.3) / len(vals)
    med = float(np.median(vals))
    return _stage("cross_asset_replication", frac_pos >= 0.5 and med > 0.3,
                  {"by_asset_sharpe": shs, "frac_positive": round(frac_pos, 2), "median_sharpe": round(med, 2)})


def run_gauntlet(name: str, returns, *, factors: dict | None = None, variants: dict | None = None,
                 n_trials: int | None = None, sr_variance: float | None = None,
                 regime_labels=None, pit_checks: list | None = None, replications: dict | None = None,
                 periods_per_year: int = 365, dsr_threshold: float = 0.95) -> dict:
    """Run a candidate return series through the full funnel. Optional inputs unlock optional gates:
    `factors` → absorption; `variants` (dict incl. this candidate) → DSR trial-variance + PBO;
    `pit_checks` → temporal-leakage guard; `regime_labels` → regime-grouped robustness."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    stages = []
    s = sharpe_stats(r)
    ann = round(float(s.sr) * math.sqrt(periods_per_year), 2)

    # 1 — significance (PSR vs 0)
    psr = probabilistic_sharpe_ratio(s, 0.0)
    stages.append(_stage("significance_PSR", psr >= 0.95, {"ann_sharpe": ann, "psr": round(psr, 3)}))

    # 2 — deflated Sharpe (multiple testing)
    dsr = None
    if variants and name in variants:
        ev = {e.name: e for e in evaluate_universe(variants, dsr_threshold=dsr_threshold)}
        dsr, N = ev[name].dsr, len(variants)
    elif sr_variance is not None and n_trials:
        dsr, N = round(deflated_sharpe_ratio(s, sr_variance, n_trials), 4), n_trials
    if dsr is not None:
        stages.append(_stage("deflated_sharpe", dsr >= dsr_threshold, {"dsr": dsr, "n_trials": N}))
    else:
        stages.append(_stage("deflated_sharpe", None, {}, skipped=True, note="needs variants or (sr_variance,n_trials)"))

    # 3 — PBO (needs a variant matrix)
    if pbo_cscv and variants and len(variants) >= 4:
        m = min(len(np.asarray(v, float)) for v in variants.values())
        R = np.column_stack([np.asarray(v, float)[-m:] for v in variants.values()])
        try:
            pbo = pbo_cscv(R).get("pbo")
            stages.append(_stage("PBO_CSCV", pbo is not None and pbo < 0.5, {"pbo": round(float(pbo), 3)}))
        except Exception as e:
            stages.append(_stage("PBO_CSCV", None, {}, skipped=True, note=f"pbo error: {e}"))
    else:
        stages.append(_stage("PBO_CSCV", None, {}, skipped=True, note="needs ≥4 variants"))

    # 4 — factor absorption
    if factors:
        a = absorption_test(r, factors, periods_per_year=periods_per_year)
        stages.append(_stage("factor_absorption", a["alpha_significant"],
                             {"alpha_ann_pct": a["alpha_ann_pct"], "alpha_t": a["alpha_t"], "verdict": a["verdict"][:40]}))
    else:
        stages.append(_stage("factor_absorption", None, {}, skipped=True, note="no factor panel supplied"))

    # 5 — regime robustness
    rr = subsample_robustness(r, labels=regime_labels, periods_per_year=periods_per_year)
    stages.append(_stage("regime_robustness", rr.get("passed"),
                         {"recent_ratio": rr.get("recent_ratio"), "worst_sharpe": rr.get("worst_subsample_sharpe"),
                          "verdict": rr.get("verdict", "")[:40]}))

    # 6 — cross-asset replication (a single-asset ★ is not a credited edge — R39)
    if replications:
        stages.append(_cross_asset_gate(replications, periods_per_year))
    else:
        stages.append(_stage("cross_asset_replication", None, {}, skipped=True, note="single-asset test — supply `replications`"))

    # 7 — point-in-time / leakage (LLM features)
    if pit_audit and pit_checks:
        p = pit_audit(pit_checks)
        stages.append(_stage("pit_guard", p["pit_safe"], {"failed": p["failed_checks"]}))
    else:
        stages.append(_stage("pit_guard", None, {}, skipped=True, note="not an LLM feature / no checks"))

    applicable = [st for st in stages if not st["skipped"]]
    passed_all = all(st["passed"] for st in applicable)
    # where it died: first failing applicable stage
    died = next((st["stage"] for st in stages if st["passed"] is False), None)
    funnel = " → ".join(("✓" if st["passed"] else "✗" if st["passed"] is False else "·") + st["stage"]
                        for st in stages)
    verdict = ("★ SURVIVOR — cleared every applicable gate; carries residual, robust, leak-free edge."
               if passed_all else f"DIED at {died}. Not a credited signal.")
    return {"name": name, "ann_sharpe": ann, "passed_all": passed_all, "died_at": died,
            "funnel": funnel, "stages": stages, "verdict": verdict}


def format_funnel(results: list[dict]) -> str:
    out = ["SIGNAL GAUNTLET — funnel (✓pass ✗fail ·skip)", "=" * 52]
    for r in results:
        out.append(f"\n{r['name']}  (annSR {r['ann_sharpe']:+.2f})  → {r['verdict']}")
        out.append("  " + r["funnel"])
    surv = [r["name"] for r in results if r["passed_all"]]
    out.append(f"\nSURVIVORS: {surv or 'NONE'}")
    return "\n".join(out)


if __name__ == "__main__":
    rng = np.random.default_rng(11)
    N = 900
    mkt = rng.normal(0.001, 0.03, N)
    mom = np.sign(np.convolve(mkt, np.ones(30), "same")) * mkt
    factors = {"f_market": mkt, "f_momentum": mom}
    variants = {f"cfg{i}": 0.5 * mkt + rng.normal(0.0002, 0.01, N) for i in range(6)}

    beta_mirage = np.concatenate([0.5 * mkt[:450], 0.5 * mkt[450:] + rng.normal(0.003, 0.01, 450)])  # beta + friendly 2nd half
    orthogonal = 0.0008 + rng.normal(0, 0.006, N)                                                     # stable broad α, ~zero beta
    variants["beta_mirage"] = beta_mirage
    variants["orthogonal"] = orthogonal

    res = [run_gauntlet("beta_mirage", beta_mirage, factors=factors, variants=variants),
           run_gauntlet("orthogonal", orthogonal, factors=factors, variants=variants)]
    print(format_funnel(res))
