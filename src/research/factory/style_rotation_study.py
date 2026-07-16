"""
Multi-Asset / Multi-Strategy Rotation Study (Seth 2026-07-15, Jazz's direction).
================================================================================

Three questions, tested honestly on our own factory signals:
  A. CORRELATION STRUCTURE — asset↔asset and strategy↔strategy. How many INDEPENDENT assets
     and independent styles do we actually have? (Crypto majors are ~all high-beta to BTC, so
     the effective breadth is far below the nominal count — this bounds what rotation can do.)
  B. STYLE CYCLES — do factors have time-varying performance? (i) factor momentum: do
     trailing-winner styles persist? (ii) regime-conditioning: per-signal Sharpe split by BTC
     vol regime + risk-on/off. Which style works when.
  C. ROTATION vs STATIC — does a dynamic weight overlay (factor-momentum tilt) beat the static
     inverse-variance blend OUT-OF-SAMPLE? Grounded expectation (Asness et al., "Contrarian
     Factor Timing is Deceptively Difficult"): rotation usually adds little over static
     diversification. We test whether OUR data agrees, honestly.

Reuses the factory signal library + panel. Pure numpy.
"""
from __future__ import annotations

import numpy as np

from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE, load_binance_panel
from src.research.factory.signal_factory import signal_library, _bt


def _sr(x):
    x = np.asarray(x)
    return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0


def _eff_n(C):
    """Effective number of independent series from a correlation matrix (entropy of eigenvalues)."""
    ev = np.linalg.eigvalsh(C); ev = ev[ev > 1e-10]; p = ev / ev.sum()
    return float(np.exp(-(p * np.log(p)).sum()))


def run(start=(2024, 1, 1)) -> dict:
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    lib = signal_library(close, ret, fmean, fsum)
    warm = 180
    names = list(lib)
    S = np.array([_bt(W, ret, fsum)[warm:] for W in lib.values()]).T     # T×K strategy pnl
    R = ret[warm:]                                                        # T×K asset returns
    T = S.shape[0]

    # ── A. correlation structure ──
    Cs = np.nan_to_num(np.corrcoef(S.T))
    Ca = np.nan_to_num(np.corrcoef(R.T))
    strat_eff = round(_eff_n(Cs), 2)
    asset_eff = round(_eff_n(Ca), 2)

    # ── B1. factor momentum: does trailing-60d Sharpe predict next-60d Sharpe? ──
    K = S.shape[1]
    look, hold = 60, 60
    xs, ys = [], []
    for i in range(look, T - hold, 20):
        past = np.array([_sr(S[i - look:i, j]) for j in range(K)])
        fut = np.array([_sr(S[i:i + hold, j]) for j in range(K)])
        for j in range(K):
            xs.append(past[j]); ys.append(fut[j])
    fm_ic = float(np.corrcoef(xs, ys)[0, 1]) if len(xs) > 10 else float("nan")

    # ── B2. regime-conditional per-signal Sharpe (BTC vol terciles) ──
    btc = R[:, 0]
    vol = np.array([btc[max(0, i - 30):i].std() for i in range(T)])
    lo, hi = np.nanpercentile(vol[30:], [33, 66])
    regimes = {"calm": vol <= lo, "mid": (vol > lo) & (vol <= hi), "stormy": vol > hi}
    by_regime = {}
    for rn, mask in regimes.items():
        by_regime[rn] = {names[j]: round(_sr(S[mask, j]), 2) for j in range(K)}

    # ── C. rotation vs static, OOS (walk-forward) ──
    def _static(train, test):                       # inverse-variance, positive-Sharpe only
        srs = np.array([_sr(train[:, j]) for j in range(K)]); v = train.var(0)
        w = np.where(srs > 0, 1.0 / np.where(v > 0, v, 1e18), 0.0)
        return w / w.sum() if w.sum() > 0 else np.ones(K) / K
    def _rotate(train, test):                        # factor-momentum tilt (weight by trailing SR+)
        srs = np.array([_sr(train[-60:, j]) for j in range(K)])
        w = np.clip(srs, 0, None)
        return w / w.sum() if w.sum() > 0 else np.ones(K) / K

    stat_oos, rot_oos, reg_oos = [], [], []
    step = int(T * 0.5 / 5)
    for f in range(5):
        tr_end = int(T * 0.5) + f * step
        te = S[tr_end + 5: tr_end + 5 + step]
        if len(te) < 5:
            break
        tr = S[:tr_end]
        stat_oos.extend((te @ _static(tr, te)).tolist())
        rot_oos.extend((te @ _rotate(tr, te)).tolist())
        # regime-conditional: weight by each signal's TRAIN Sharpe within the CURRENT regime
        tvol = vol[:tr_end]
        tlo, thi = np.nanpercentile(tvol[30:], [33, 66])
        blk_vol = np.nanmedian(vol[tr_end + 5: tr_end + 5 + step])
        cur = "calm" if blk_vol <= tlo else ("stormy" if blk_vol > thi else "mid")
        rmask = (tvol <= tlo) if cur == "calm" else ((tvol > thi) if cur == "stormy" else ((tvol > tlo) & (tvol <= thi)))
        rsr = np.array([_sr(tr[rmask[:len(tr)], j]) for j in range(K)])
        wv = np.clip(rsr, 0, None); wv = wv / wv.sum() if wv.sum() > 0 else np.ones(K) / K
        reg_oos.extend((te @ wv).tolist())

    st, ro, rg = _sr(stat_oos), _sr(rot_oos), _sr(reg_oos)
    return {"T": T, "n_signals": K,
            "asset_effective_n": asset_eff, "asset_nominal": R.shape[1],
            "strategy_effective_n": strat_eff, "strategy_nominal": K,
            "factor_momentum_ic": round(fm_ic, 3),
            "regime_sharpe": by_regime, "signal_names": names,
            "oos_static_sharpe": round(st, 2),
            "oos_momentum_rotation_sharpe": round(ro, 2),
            "oos_regime_rotation_sharpe": round(rg, 2),
            "best": max([("static", st), ("momentum_rotation", ro), ("regime_rotation", rg)], key=lambda x: x[1])[0]}


if __name__ == "__main__":
    import json
    r = run()
    print(f"\n=== MULTI-ASSET / MULTI-STRATEGY ROTATION — {r['T']}d, {r['n_signals']} signals ===\n")
    print(f"A. BREADTH (effective independent count):")
    print(f"   assets:     {r['asset_effective_n']} of {r['asset_nominal']} nominal  "
          f"(crypto majors move together → real breadth is low)")
    print(f"   strategies: {r['strategy_effective_n']} of {r['strategy_nominal']} nominal")
    print(f"\nB1. FACTOR MOMENTUM  IC(trailing-60d SR → next-60d SR) = {r['factor_momentum_ic']}  "
          f"({'persists' if r['factor_momentum_ic'] > 0.05 else 'no persistence — styles mean-revert/noisy'})")
    print(f"\nB2. STYLE × REGIME (per-signal Sharpe by BTC vol regime):")
    top = {rn: sorted(d.items(), key=lambda kv: -kv[1])[:3] for rn, d in r["regime_sharpe"].items()}
    for rn, lst in top.items():
        print(f"   {rn:7}: " + ", ".join(f"{n}={s}" for n, s in lst))
    print(f"\nC. ROTATION vs STATIC (OOS walk-forward):")
    print(f"   static blend:        {r['oos_static_sharpe']}")
    print(f"   momentum rotation:   {r['oos_momentum_rotation_sharpe']}  (chase recent-winner styles)")
    print(f"   regime rotation:     {r['oos_regime_rotation_sharpe']}  (tilt to current vol-regime's best styles)")
    print(f"   → BEST: {r['best']}")
