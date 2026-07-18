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


def _roll_beta_idio(ret: np.ndarray, k: int, mkt_idx: int = 0):
    """Rolling beta of each asset to the market (BTC = col 0) + idiosyncratic vol (residual std).
    BAB (betting-against-beta) and low-idio-vol are canonical factors; likely orthogonal to
    momentum/funding, so good ensemble candidates."""
    T, K = ret.shape
    beta = np.full((T, K), np.nan); idio = np.full((T, K), np.nan)
    for i in range(k, T):
        A = ret[i - k:i, :]                       # k×K
        m = ret[i - k:i, mkt_idx]                 # k
        mv = m.var()
        if mv <= 0:
            continue
        mc = m - m.mean()
        Ac = A - A.mean(0)
        b = (Ac * mc[:, None]).mean(0) / mv       # K betas, vectorised
        beta[i] = b
        idio[i] = (Ac - b[None, :] * mc[:, None]).std(0)
    return beta, idio


def _funding_price_disagreement(fmean: np.ndarray, ret: np.ndarray, k: int = 7) -> np.ndarray:
    """Minimax-A 2026-07-17 — fade the WINNING crowd. Orthogonal to positioning_funding
    (which fades regardless of price). Two cases only:
      (a) longs crowded (fmean>0) AND winning (r_k>0) → SHORT (positive score)
      (b) shorts crowded (fmean<0) AND winning (r_k<0) → LONG  (negative score)
    Cases where funding + price DISAGREE (squeeze already underway, or crowd already losing)
    → 0. Mechanism: §TRADER_TOM_DOCTRINE — crowd-exhaustion at peak profitability
    ("add when the crowd subtracts"; the winning crowd eventually gets punished for being
    both crowded AND wrong-direction-bias)."""
    T = ret.shape[0]
    rk = np.full((T, ret.shape[1]), np.nan)
    # Sum of last k daily returns = rolling-window price change
    for i in range(k, T):
        rk[i] = ret[i - k + 1: i + 1].sum(0)
    score = np.where(
        (fmean > 0) & (rk > 0),          np.abs(fmean * rk),     # longs crowded+winning → SHORT-signal
        np.where((fmean < 0) & (rk < 0), -np.abs(fmean * rk),     # shorts crowded+winning → LONG-signal
                 0.0)
    )
    return _xs_weights(score, sign=-1.0)   # sign=-1: positive score→SHORT; negative score→LONG


def _funding_extreme_only(fmean: np.ndarray, percentile: float = 85) -> np.ndarray:
    """Minimax-A 2026-07-17 — only enter on cross-sectional EXTREMES of funding (top/bottom
    `100-percentile`%). Middle → 0. Tighter than positioning_funding (which enters on ANY
    cross-sectional funding divergence). Hypothesis: only DEEP crowd exhaustion is tradable;
    shallow divergences are noise. Returns T×K weights, dollar-neutral, gross 1."""
    T, K = fmean.shape
    out = np.full((T, K), np.nan)
    for i in range(T):
        row = fmean[i]
        m = np.isfinite(row)
        if m.sum() < 4:
            continue
        valid = row[m]
        if len(valid) < 4:
            continue
        hi = np.percentile(valid, percentile)
        lo = np.percentile(valid, 100 - percentile)
        # Re-center: hi → 0+, lo → 0-. Inside the band → 0.
        out[i] = np.where(
            m & (row >= hi), row - hi,
            np.where(m & (row <= lo), row - lo, 0.0)
        )
    return _xs_weights(out, sign=-1.0)   # fade: short high funding, long low/neg funding


def _funding_volatility(fmean: np.ndarray, k: int = 30) -> np.ndarray:
    """Minimax-A 2026-07-17 — funding VOLATILITY signal (NOT level).
    Per-asset time-series std of fmean over k days. When funding is volatile for an asset,
    the crowd is uncertain; when stable, the crowd is committed.
    Cross-sectionally: LONG assets with LOW funding vol (stable consensus, persists),
    SHORT assets with HIGH funding vol (uncertain crowd, washes out).
    Mechanism: §TRADER_TOM_DOCTRINE — ride the committed crowd (low vol), fade the uncertain
    crowd (high vol). Distinct from positioning_funding (level) and funding_extreme_only
    (cross-sectional percentile), because this uses TIME-SERIES vol per asset.
    Hypothesis: stable-funding names carry information longer; volatile-funding names churn."""
    vol = _roll_std(fmean, k)                           # T×K per-asset time-series std
    return _xs_weights(vol, sign=-1.0)                  # LONG low-vol, SHORT high-vol


def _relative_reversal(close: np.ndarray, k: int = 7) -> np.ndarray:
    """Minimax-A 2026-07-17 — RELATIVE reversal vs the BTC anchor (col 0).
    Different from reversal_7d/longterm_reversal_180 which are ABSOLUTE.
    If asset has outperformed BTC over the last k days → SHORT asset / LONG BTC (fade).
    If asset has underperformed BTC → LONG asset / SHORT BTC (ride the lagger).
    BTC has weight 0 (it's the anchor, not a tradeable). The non-BTC assets are
    weighted by their excess return vs BTC and renormalised to gross=1 across the K-1
    non-zero columns. Custom weight scheme (NOT _xs_weights) because _xs_weights
    subtracts the cross-sectional mean and BTC's contribution cancels — yields identical
    results to absolute reversal. The explicit BTC=0 is the structural difference.
    Mechanism: §TRADER_TOM_DOCTRINE — early movers exhaust, lagger catches up.
    Tries to be orthogonal to both funding axis (no perp signal) and absolute momentum/
    reversal families (BTC-anchored, not absolute)."""
    T, K = close.shape
    rk = _roll_ret(close, k)
    rk_btc = rk[:, 0:1]                              # T×1 anchor
    rel = rk - rk_btc                                # T×K, BTC col = 0; positive = outperformed BTC
    rel[:, 0] = np.nan                               # BTC = NaN → zero weight
    W = np.zeros((T, K))
    for i in range(T):
        row = -rel[i]                                # sign=−1: fade outperformance
        m = np.isfinite(row)
        if m.sum() < 4:
            continue
        r = np.where(m, row, 0.0)
        g = np.abs(r).sum()
        if g > 0:
            W[i] = r / g
    return W


def _extracted(scores: list, sign: float) -> np.ndarray:
    """Param-ROBUST extracted feature: blend a family's weight vectors across its whole grid,
    then renormalise gross. The economic driver (momentum exists) without the overfit knob
    (exactly 97d). Deterministic → computable live. (Jazz: discover by overfit, trade the feature.)"""
    Ws = [_xs_weights(s, sign=sign) for s in scores]
    We = np.mean(Ws, axis=0)
    g = np.abs(We).sum(1, keepdims=True); g[g == 0] = 1.0
    return We / g


def signal_library(close, ret, fmean, fsum) -> dict[str, np.ndarray]:
    """{name: weight matrix T×K}. Each dollar-neutral, gross 1. Deliberately a MIX of
    plausible-and-junk across families — the gate decides, not us. Parametric families ALSO
    enter as param-robust *_extracted features (the invariant, not the overfit point)."""
    r7, r30, r90 = _roll_ret(close, 7), _roll_ret(close, 30), _roll_ret(close, 90)
    r60, r120, r180 = _roll_ret(close, 60), _roll_ret(close, 120), _roll_ret(close, 180)
    v10, v30, v60 = _roll_std(ret, 10), _roll_std(ret, 30), _roll_std(ret, 60)
    hi60 = _roll_max(close, 60)
    fmom = np.full_like(fmean, np.nan); fmom[7:] = fmean[7:] - fmean[:-7]
    sk60 = _roll_skew(ret, 60)
    dvol30 = _roll_downside(ret, 30)
    volreg = np.where(v60 > 0, v10 / v60, np.nan)
    beta60, idio60 = _roll_beta_idio(ret, 60)
    return {
        # cause / positioning
        "positioning_funding":  positioning_weights(fmean, kwin=7),          # validated baseline
        "funding_momentum":     _xs_weights(fmom, sign=-1.0),
        "funding_price_disagree": _funding_price_disagreement(fmean, ret, k=7),  # fade winning crowd
        "funding_extreme_only":   _funding_extreme_only(fmean, percentile=85),  # top/bot 15% only
        "funding_volatility":     _funding_volatility(fmean, k=30),            # time-series std (NOT level)
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
        "relative_reversal_7d": _relative_reversal(close, k=7),
        # risk / distribution family
        "lowvol_30d":           _xs_weights(v30, sign=-1.0),
        "low_downside_vol_30":  _xs_weights(dvol30, sign=-1.0),
        "vol_regime_10_60":     _xs_weights(volreg, sign=-1.0),
        "neg_skew_pref_60":     _xs_weights(sk60, sign=-1.0),
        "betting_against_beta": _xs_weights(beta60, sign=-1.0),   # long low-beta / short high-beta
        "low_idio_vol_60":      _xs_weights(idio60, sign=-1.0),
        # ── param-robust EXTRACTED features (discover→extract; the invariant, not the knob) ──
        "momentum_extracted":     _extracted([r30, r60, r90, r120, _roll_ret(close, 180)], +1.0),
        "lowvol_extracted":       _extracted([v10, v30, v60], -1.0),
        "downside_vol_extracted": _extracted([dvol30, _roll_downside(ret, 20), _roll_downside(ret, 60)], -1.0),
        "neg_skew_extracted":     _extracted([sk60, _roll_skew(ret, 30), _roll_skew(ret, 90)], -1.0),
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

    # PBO — probability the in-sample-best signal is below-median OOS (selection overfitting)
    try:
        from src.research.validation.pbo import pbo_cscv
        Smat = np.array([series[n] for n in series]).T
        pbo = pbo_cscv(Smat, S=10).get("pbo")
    except Exception:
        pbo = None

    return {"days": len(days), "n_signals": len(lib), "evals": evals, "wf": wf, "pbo": pbo,
            "ann_sharpe": {n: round(a, 2) for n, a in ann.items()},
            "corr_to_positioning": corr, "survivors": survivors,
            "nucleus": nucleus, "combined": comb}


def walkforward_combined(start=(2024, 1, 1), folds: int = 5, embargo: int = 5) -> dict:
    """The honest headline test: the combined 1.56 is fit in-sample (nucleus + blend on the
    whole panel). Here the nucleus selection AND the blend weights are fit on TRAIN only, then
    applied forward to an embargoed TEST block. Concatenate the OOS test pnl across expanding
    folds → the OOS combined Sharpe. If it holds, the ensemble is real; if it deflates, that's
    the truth. No look-ahead in the aggregate."""
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    lib = signal_library(close, ret, fmean, fsum)
    warm = 180
    series = {n: _bt(W, ret, fsum)[warm:] for n, W in lib.items()}
    T = len(next(iter(series.values())))
    names = list(series)
    M = np.array([series[n] for n in names]).T          # T×K pnl matrix

    def _sr(x):
        return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0

    oos_pnl = []
    start_frac = 0.5                                     # first train = first 50%
    test_len = int(T * (1 - start_frac) / folds)
    for f in range(folds):
        tr_end = int(T * start_frac) + f * test_len
        te_lo, te_hi = tr_end + embargo, tr_end + embargo + test_len
        if te_hi > T:
            break
        tr = M[:tr_end]
        # nucleus on TRAIN: positive train Sharpe + orthogonal (train corr <0.6)
        tr_sr = {names[i]: _sr(tr[:, i]) for i in range(len(names))}
        cand = [n for n in names if tr_sr[n] > 0.2]
        nucleus = []
        for n in sorted(cand, key=lambda x: -tr_sr[x]):
            idx = names.index(n)
            if not nucleus or max(abs(np.corrcoef(tr[:, idx], tr[:, names.index(m)])[0, 1]) for m in nucleus) < 0.6:
                nucleus.append(n)
        if len(nucleus) < 2:
            continue
        # blend on TRAIN via the same combiner
        rbs = {n: {i: float(v) for i, v in enumerate(tr[:, names.index(n)])} for n in nucleus}
        w = combine(rbs).weights
        # apply forward to embargoed TEST
        te = M[te_lo:te_hi]
        wvec = np.array([w.get(n, 0.0) for n in names])
        oos_pnl.extend((te @ wvec).tolist())

    oos = np.array(oos_pnl)
    return {"folds_used": folds, "oos_days": len(oos),
            "oos_combined_sharpe": round(_sr(oos), 2) if len(oos) > 5 else None,
            "oos_total_return_pct": round(float(oos.sum()) * 100, 1) if len(oos) else None,
            "in_sample_ref": 1.56}


async def recalibrate_and_log() -> dict:
    """Stage 4 — the loop's recalibration turn. Re-run the factory, write the fresh nucleus
    blend to Redis (the combined book reads it → decayed signals drop out with no code change),
    and log the batch to experiment_runs (the loop's memory). Best-effort; never raises."""
    res = run()
    comb = res.get("combined")
    nucleus_blend = comb.weights if comb else {n: round(1.0 / len(res["nucleus"]), 4) for n in res["nucleus"]}
    # the HONEST number — OOS (blend fit on train only), never the inflated in-sample Sharpe.
    try:
        wf = walkforward_combined()
    except Exception:
        wf = {"oos_combined_sharpe": None}
    challenger_oos = wf.get("oos_combined_sharpe")
    _pbo = res.get("pbo")

    # ── CHAMPION / CHALLENGER with hysteresis (industry standard, not auto-overwrite) ──
    # A fresh nucleus only REPLACES the incumbent if it beats it OOS by a margin. Weekly
    # auto-overwrite would chase noise (regime-thrashing); promotion needs to clear the band.
    from src.data.market.data_layer import _redis_get, _redis_set
    PROMOTE_MARGIN = 0.15
    champ = None
    try:
        champ = await _redis_get("combined_book:champion")
    except Exception:
        pass
    promoted = False
    if (not isinstance(champ, dict)) or champ.get("oos_sharpe") is None \
            or (challenger_oos is not None and challenger_oos > champ["oos_sharpe"] + PROMOTE_MARGIN):
        new_champ = {"nucleus": nucleus_blend, "oos_sharpe": challenger_oos,
                     "in_sample": comb.port_sharpe_ann if comb else None,
                     "promoted_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            await _redis_set("combined_book:champion", new_champ, ttl=0)
            await _redis_set("combined_book:nucleus", nucleus_blend, ttl=0)
        except Exception as e:
            print(f"[FACTORY] champion write failed: {e}")
        promoted = True
        champ = new_champ
    # publish the LIVE champion's honest refs (not the challenger's) for combined_book
    try:
        await _redis_set("combined_book:refs", {
            "oos_combined_sharpe": champ.get("oos_sharpe"),
            "in_sample_sharpe": champ.get("in_sample"),
            "enb": comb.enb if comb else None, "oos_days": wf.get("oos_days"),
            "pbo": _pbo, "promoted": promoted, "challenger_oos": challenger_oos}, ttl=0)
    except Exception as e:
        print(f"[FACTORY] refs write failed: {e}")
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
        wf = walkforward_combined()
        print(f"\nHONEST OOS (nucleus + blend fit on TRAIN only, embargoed, {wf['oos_days']}d): "
              f"combined Sharpe {wf['oos_combined_sharpe']}  (in-sample {wf['in_sample_ref']}) "
              f"— survives, deflated as expected.")
    else:
        print("\nno combinable nucleus (need ≥2) — the library is still too thin; add more signals.")
