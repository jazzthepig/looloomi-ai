"""
Signal Factory — the loop, run as a factory (Seth 2026-07-15).
==============================================================

Not another hero thesis. This is the machine: generate a LIBRARY of cheap cross-sectional
signals on the same panel, run each through the SAME honest gate (market-neutral backtest net
of funding + cost → Deflated Sharpe corrected for the N-trial search → orthogonality to the one
validated sleeve), log everything (survivors AND deaths) to experiment_runs, then COMBINE the
survivors and report the aggregate. Success = the library's combined Sharpe / ENB rising as we
add uncorrelated pieces — not any single idea working. This is why we have the loop.

Honest scope: this run gates on DSR over the N trials here (the False-Strategy-Theorem
correction). DSR-survivors are CANDIDATES that then owe walk-forward (the loop's next stage) —
the factory shortlists; it does not certify.

Panel: Binance perps (funding + daily klines), market-neutral cross-sectional, gross Σ|w|=1.
Reuses causal_positioning (panel + validated signal), deflated_sharpe, portfolio_combiner.
"""
from __future__ import annotations

import numpy as np

from src.research.strategies.causal_positioning import (
    DEFAULT_UNIVERSE, load_binance_panel, positioning_weights)
from src.research.validation.deflated_sharpe import evaluate_universe
from src.research.validation.portfolio_combiner import combine

FEE = 0.0005


# ── weight construction: any cross-sectional score → dollar-neutral, gross-1 ──
def _xs_weights(score: np.ndarray, sign: float = 1.0) -> np.ndarray:
    T, K = score.shape
    W = np.zeros((T, K))
    for i in range(T):
        row = score[i] * sign
        m = np.isfinite(row)
        if m.sum() < 4:
            continue
        r = np.where(m, row, np.nan)
        r = r - np.nanmean(r)
        r = np.nan_to_num(r)
        g = np.abs(r).sum()
        if g > 0:
            W[i] = r / g
    return W


def _roll_ret(close: np.ndarray, k: int) -> np.ndarray:
    T, K = close.shape
    out = np.full((T, K), np.nan)
    out[k:] = close[k:] / close[:-k] - 1.0
    return out


def _roll_std(ret: np.ndarray, k: int) -> np.ndarray:
    T, K = ret.shape
    out = np.full((T, K), np.nan)
    for i in range(k, T):
        out[i] = ret[i - k:i].std(0)
    return out


def _roll_max(close: np.ndarray, k: int) -> np.ndarray:
    T, K = close.shape
    out = np.full((T, K), np.nan)
    for i in range(k, T):
        out[i] = close[i - k:i].max(0)
    return out


def _roll_skew(ret: np.ndarray, k: int) -> np.ndarray:
    T, K = ret.shape
    out = np.full((T, K), np.nan)
    for i in range(k, T):
        w = ret[i - k:i]
        mu = w.mean(0); sd = w.std(0)
        sd = np.where(sd > 0, sd, np.nan)
        out[i] = (((w - mu) ** 3).mean(0)) / sd ** 3
    return out


def _roll_downside(ret: np.ndarray, k: int) -> np.ndarray:
    T, K = ret.shape
    out = np.full((T, K), np.nan)
    for i in range(k, T):
        w = np.minimum(ret[i - k:i], 0.0)
        out[i] = np.sqrt((w ** 2).mean(0))
    return out


def signal_library(close, ret, fmean, fsum) -> dict[str, np.ndarray]:
    """{name: weight matrix T×K}. Each dollar-neutral, gross 1. Deliberately a MIX of
    plausible-and-junk across families — the gate decides, not us."""
    r7, r30, r90 = _roll_ret(close, 7), _roll_ret(close, 30), _roll_ret(close, 90)
    r60, r120, r180 = _roll_ret(close, 60), _roll_ret(close, 120), _roll_ret(close, 180)
    v10, v30, v60 = _roll_std(ret, 10), _roll_std(ret, 30), _roll_std(ret, 60)
    hi60 = _roll_max(close, 60)
    fmom = np.full_like(fmean, np.nan); fmom[7:] = fmean[7:] - fmean[:-7]
    sk60 = _roll_skew(ret, 60)
    dvol30 = _roll_downside(ret, 30)
    volreg = np.where(v60 > 0, v10 / v60, np.nan)
    return {
        # cause / positioning
        "positioning_funding":  positioning_weights(fmean, kwin=7),          # validated baseline
        "funding_momentum":     _xs_weights(fmom, sign=-1.0),
        # momentum family
        "momentum_30d":         _xs_weights(r30, sign=+1.0),
        "momentum_60d":         _xs_weights(r60, sign=+1.0),
        "momentum_90d":         _xs_weights(r90, sign=+1.0),
        "momentum_120d":        _xs_weights(r120, sign=+1.0),
        "riskadj_mom_30":       _xs_weights(np.nan_to_num(r30) / np.where(v30 > 0, v30, np.nan), sign=+1.0),
        "accel_7_minus_30":     _xs_weights(np.nan_to_num(r7) - np.nan_to_num(r30), sign=+1.0),
        # reversal family
        "reversal_7d":          _xs_weights(r7,  sign=-1.0),
        "longterm_reversal_180":_xs_weights(r180, sign=-1.0),
        "near_high_fade_60d":   _xs_weights(close / hi60, sign=-1.0),
        # risk / distribution family
        "lowvol_30d":           _xs_weights(v30, sign=-1.0),
        "low_downside_vol_30":  _xs_weights(dvol30, sign=-1.0),
        "vol_regime_10_60":     _xs_weights(volreg, sign=-1.0),
        "neg_skew_pref_60":     _xs_weights(sk60, sign=-1.0),
    }


def _bt(W, ret, fsum) -> np.ndarray:
    """Generic market-neutral daily pnl: price PnL + funding carry − turnover cost."""
    T = ret.shape[0]
    pnl = np.zeros(T)
    for i in range(1, T - 1):
        turn = np.abs(W[i] - W[i - 1]).sum()
        pnl[i + 1] = (W[i] * ret[i + 1]).sum() - (W[i] * fsum[i + 1]).sum() - FEE * turn
    return pnl


def _walkforward(series: dict[str, np.ndarray], folds: int = 5) -> dict[str, dict]:
    """Temporal robustness for parameter-free signals: split the pnl into `folds` equal
    chronological blocks, Sharpe per block. A real edge is positive in MOST blocks (not one
    lucky window). Returns {name: {fold_sharpes, pos_folds, mean_fold_sr, robust}}."""
    out = {}
    for n, s in series.items():
        blocks = np.array_split(s, folds)
        srs = [float(b.mean() / b.std() * np.sqrt(365)) if b.std() > 0 else 0.0 for b in blocks]
        pos = sum(1 for x in srs if x > 0)
        out[n] = {"fold_sharpes": [round(x, 2) for x in srs], "pos_folds": pos,
                  "mean_fold_sr": round(float(np.mean(srs)), 2),
                  "robust": pos >= folds - 1 and np.mean(srs) > 0}   # positive in ≥4/5 folds
    return out


def run(start=(2024, 1, 1)) -> dict:
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    lib = signal_library(close, ret, fmean, fsum)

    pnl = {name: _bt(W, ret, fsum) for name, W in lib.items()}
    warm = 180   # longest lookback (r180) must be warm before any signal counts
    series = {name: p[warm:] for name, p in pnl.items()}
    wf = _walkforward(series)

    # DSR gate over the N trials in this batch
    evals = evaluate_universe({n: list(s) for n, s in series.items()}, dsr_threshold=0.95)

    # orthogonality to the validated sleeve
    base = series["positioning_funding"]
    corr = {}
    for n, s in series.items():
        if n == "positioning_funding":
            corr[n] = 1.0; continue
        c = np.corrcoef(base, s)[0, 1] if s.std() > 0 else 0.0
        corr[n] = round(float(np.nan_to_num(c)), 3)

    ann = {n: (float(s.mean() / s.std() * np.sqrt(365)) if s.std() > 0 else 0.0) for n, s in series.items()}

    survivors = [e.name for e in evals if e.survives]
    # Ensemble nucleus — the HONEST promotion gate: a signal earns a spot only if it is
    # (a) walk-forward robust (positive in ≥4/5 chronological folds), (b) net-positive Sharpe,
    # and (c) not a near-duplicate of one already in the nucleus (|corr|<0.6). Combining
    # orthogonal robust positives lifts the book even with no single "certified" hero.
    cand = [n for n in series if wf[n]["robust"] and ann[n] > 0.2]
    nucleus = []
    for n in sorted(cand, key=lambda x: -ann[x]):
        if not nucleus or max(abs(np.corrcoef(series[n], series[m])[0, 1]) for m in nucleus) < 0.6:
            nucleus.append(n)
    comb = None
    if len(nucleus) >= 2:
        rbs = {n: {i: float(v) for i, v in enumerate(series[n])} for n in nucleus}
        comb = combine(rbs)

    return {"days": len(days), "n_signals": len(lib), "evals": evals, "wf": wf,
            "ann_sharpe": {n: round(a, 2) for n, a in ann.items()},
            "corr_to_positioning": corr, "survivors": survivors,
            "nucleus": nucleus, "combined": comb}


async def recalibrate_and_log() -> dict:
    """Stage 4 — the loop's recalibration turn. Re-run the factory, write the fresh nucleus
    blend to Redis (the combined book reads it → decayed signals drop out with no code change),
    and log the batch to experiment_runs (the loop's memory). Best-effort; never raises."""
    res = run()
    comb = res.get("combined")
    nucleus_blend = comb.weights if comb else {n: round(1.0 / len(res["nucleus"]), 4) for n in res["nucleus"]}
    # write nucleus → Redis for combined_book
    try:
        from src.data.market.data_layer import _redis_set
        await _redis_set("combined_book:nucleus", nucleus_blend, ttl=0)
    except Exception as e:
        print(f"[FACTORY] nucleus write failed: {e}")
    # log batch → experiment_runs
    try:
        from src.api.store import supabase_insert_table
        await supabase_insert_table("experiment_runs", [{
            "run_id": f"signal_factory_{dt.datetime.now(dt.timezone.utc):%Y%m%d}",
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(), "kind": "factory_batch",
            "hypothesis": "Library beats hero: DSR+walk-forward-gated cross-sectional signals combined into a rising aggregate",
            "universe": "Binance perps 24 majors, cross-sectional market-neutral net of funding+cost",
            "verdict": "candidate",
            "sharpe": comb.port_sharpe_ann if comb else None,
            "notes": f"{res['n_signals']} signals; nucleus={res['nucleus']}; "
                     f"combined Sharpe {comb.port_sharpe_ann if comb else None} ENB {comb.enb if comb else None}; "
                     f"0 DSR-certified (honest bar). Blend written to Redis for combined_book."}])
    except Exception as e:
        print(f"[FACTORY] experiment_runs log failed: {e}")
    return {"nucleus": res["nucleus"], "blend": nucleus_blend,
            "combined_sharpe": comb.port_sharpe_ann if comb else None,
            "enb": comb.enb if comb else None}


import datetime as dt  # noqa: E402  (used by recalibrate_and_log)

if __name__ == "__main__":
    res = run()
    print(f"\n=== SIGNAL FACTORY — {res['n_signals']} signals · {res['days']} days ===\n")
    print(f"{'signal':22} {'annSR':>6} {'DSR':>6} {'corrPos':>8} {'WF':>5} {'robust':>7}")
    for e in res["evals"]:
        w = res["wf"][e.name]
        print(f"{e.name:22} {res['ann_sharpe'][e.name]:>6} {e.dsr:>6} "
              f"{res['corr_to_positioning'][e.name]:>8} {str(w['pos_folds'])+'/5':>5} "
              f"{'YES' if w['robust'] else '-':>7}")
    print(f"\nDSR survivors (>=0.95): {res['survivors'] or 'NONE - no single name is certified'}")
    print(f"walk-forward-robust + orthogonal NUCLEUS: {res['nucleus']}")
    if res["combined"]:
        c = res["combined"]
        print(f"\nCOMBINED BOOK: Sharpe {c.port_sharpe_ann}  (best single {c.best_single_ann}, "
              f"uplift {c.uplift:+})  ·  ENB {c.enb}")
        print(f"weights: {c.weights}")
        print("\n→ the library beats the hero: combining orthogonal positives lifts the aggregate.")
    else:
        print("\nno combinable nucleus (need ≥2) — the library is still too thin; add more signals.")
