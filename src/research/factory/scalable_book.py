"""
Scalable Multi-Strategy Book (Seth 2026-07-15, Jazz: maximize return, capacity not too small).
================================================================================================

Quant logic for "收益最大化 with real capacity": the profit is Sharpe × capacity × leverage. The
highest-CAPACITY systematic strategies known are TIME-SERIES TREND (CTA/managed-futures — scales
to tens of billions) and CARRY, run diversified and vol-targeted on the DEEPEST instruments. Our
market-neutral FACTOR book (funding-crowd + cross-sectional value/mom/vol) is orthogonal to trend,
so the three combine into a scalable core.

This builds and OOS-tests that book on the liquid crypto majors (2y real history, deep perps —
BTC/ETH/SOL trade billions/day → real capacity), vol-targeted to a fixed annual vol:
  · FACTOR  — market-neutral cross-sectional (our validated sleeve), gross-neutral
  · TREND   — time-series momentum (each asset's own trend, risk-scaled) — the capacity engine
  · CARRY   — funding carry (receive funding on the crowded side), market-neutral
Combine risk-parity → vol-target → walk-forward OOS. Reports the scalable-book Sharpe + capacity note.
"""
from __future__ import annotations

import numpy as np

TARGET_VOL = 0.10          # annualized vol target for the combined book
FEE = 0.0005


def _sr(x):
    x = np.asarray(x); return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0


def _voltarget(pnl, lookback=30):
    """Scale daily pnl to a constant annualized vol (ex-ante, using trailing realized vol)."""
    out = np.zeros_like(pnl)
    for i in range(lookback, len(pnl)):
        rv = pnl[i - lookback:i].std() * np.sqrt(365)
        if rv > 0:
            out[i] = pnl[i] * (TARGET_VOL / rv)
    return out


def _factor_pnl(close, ret, fmean, fsum):
    """Market-neutral cross-sectional book (our validated sleeve family)."""
    from src.research.factory.signal_factory import signal_library, _bt
    lib = signal_library(close, ret, fmean, fsum)
    keep = ["positioning_funding", "momentum_extracted", "lowvol_extracted",
            "neg_skew_extracted", "downside_vol_extracted"]
    pnls = [_bt(lib[k], ret, fsum) for k in keep if k in lib]
    M = np.array(pnls).T
    v = M.var(0); v[v == 0] = 1e18
    w = (1 / v) / (1 / v).sum()
    return M @ w


def _trend_pnl(close, ret, k=60):
    """Time-series momentum (TSMOM): each asset long/short by its own k-day trend, risk-scaled to
    equal per-asset vol, book scaled to unit gross. The high-capacity engine — trades each deep
    instrument on its own signal, no cross-sectional crowding."""
    T, K = close.shape
    vol = np.full((T, K), np.nan)
    for i in range(30, T):
        vol[i] = ret[i - 30:i].std(0)
    trail = np.full((T, K), np.nan)
    trail[k:] = close[k:] / close[:-k] - 1.0
    pnl = np.zeros(T)
    prev = np.zeros(K)
    for i in range(k + 1, T - 1):
        sig = np.sign(np.nan_to_num(trail[i]))
        iv = np.where(vol[i] > 0, 1.0 / vol[i], 0.0)
        w = sig * iv
        g = np.abs(w).sum()
        w = w / g if g > 0 else w
        pnl[i + 1] = (w * ret[i + 1]).sum() - FEE * np.abs(w - prev).sum()
        prev = w
    return pnl


def _trend_multi_pnl(close, ret, horizons=(20, 60, 120, 250)):
    """Multi-horizon TSMOM — the robust CTA construction. Average the sign of the trend across
    several lookbacks (fast+slow) so no single horizon is a fragile knob; risk-scale per asset,
    unit gross. This is what real managed-futures books trade (diversified across speed)."""
    T, K = close.shape
    vol = np.full((T, K), np.nan)
    for i in range(30, T):
        vol[i] = ret[i - 30:i].std(0)
    trails = []
    for h in horizons:
        tr = np.full((T, K), np.nan); tr[h:] = close[h:] / close[:-h] - 1.0
        trails.append(tr)
    pnl = np.zeros(T); prev = np.zeros(K)
    start = max(horizons) + 1
    for i in range(start, T - 1):
        sig = np.mean([np.sign(np.nan_to_num(tr[i])) for tr in trails], axis=0)   # −1..+1 consensus
        iv = np.where(vol[i] > 0, 1.0 / vol[i], 0.0)
        w = sig * iv
        g = np.abs(w).sum()
        w = w / g if g > 0 else w
        pnl[i + 1] = (w * ret[i + 1]).sum() - FEE * np.abs(w - prev).sum()
        prev = w
    return pnl


def _carry_pnl(fmean, fsum, ret):
    """Funding carry: short the high-funding (crowded-long, they PAY), long the low/negative-funding
    (they RECEIVE) — market-neutral. Distinct from momentum; the return is the funding transfer."""
    T, K = fmean.shape
    pnl = np.zeros(T)
    prev = np.zeros(K)
    for i in range(8, T - 1):
        f = np.nan_to_num(fmean[i])
        w = -(f - f.mean())            # short high-funding, long low
        g = np.abs(w).sum()
        w = w / g if g > 0 else w
        # earn the funding + the price move on the neutral book
        pnl[i + 1] = (w * ret[i + 1]).sum() - (w * np.nan_to_num(fsum[i + 1])).sum() - FEE * np.abs(w - prev).sum()
        prev = w
    return pnl


def run(_cache=None, start=(2024, 1, 1)) -> dict:
    if _cache is not None:
        close, fmean, fsum = _cache["close"], _cache["fmean"], _cache["fsum"]
    else:
        from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE, load_binance_panel
        _, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    warm = 180

    sleeves = {
        "FACTOR": _factor_pnl(close, ret, fmean, fsum)[warm:],
        "TREND":  _trend_pnl(close, ret)[warm:],
        "CARRY":  _carry_pnl(fmean, fsum, ret)[warm:],
    }
    per = {k: round(_sr(v), 2) for k, v in sleeves.items()}
    M = np.array([sleeves[k] for k in sleeves]).T
    C = np.nan_to_num(np.corrcoef(M.T))
    # risk-parity combine (inverse-vol), then vol-target the book
    iv = 1.0 / np.where(M.std(0) > 0, M.std(0), 1e18)
    w = iv / iv.sum()
    book = M @ w
    book_vt = _voltarget(book)

    # walk-forward OOS: weights (inverse-vol) fit on train, applied forward, vol-targeted
    T = M.shape[0]; step = int(T * 0.5 / 5); oos = []
    for f in range(5):
        tr_end = int(T * 0.5) + f * step
        te = M[tr_end + 5: tr_end + 5 + step]
        if len(te) < 5:
            break
        tr = M[:tr_end]
        ivt = 1.0 / np.where(tr.std(0) > 0, tr.std(0), 1e18)
        wt = ivt / ivt.sum()
        oos.extend((te @ wt).tolist())
    oos = np.array(oos)

    return {"sleeves": list(sleeves), "per_sleeve_sharpe": per,
            "sleeve_corr": {f"{list(sleeves)[a]}×{list(sleeves)[b]}": round(float(C[a, b]), 2)
                            for a in range(3) for b in range(a + 1, 3)},
            "combined_in_sample_sharpe": round(_sr(book), 2),
            "combined_voltargeted_sharpe": round(_sr(book_vt), 2),
            "combined_OOS_sharpe": round(_sr(oos), 2),
            "target_vol": TARGET_VOL,
            "capacity_note": "liquid crypto majors (BTC/ETH/SOL perps, billions/day) — TREND+CARRY are the scalable engines"}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
