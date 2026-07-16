"""
Cross-Asset TREND (Seth 2026-07-15) — the canonical high-capacity strategy, on-chain.
======================================================================================

Time-series trend (CTA/managed-futures) is the single most CAPACITY-rich systematic strategy;
its diversification/crisis-alpha comes from running it ACROSS uncorrelated asset classes. We can
now do that on one venue: crypto majors + gold(XAU)/silver(XAG) + a deep equity index (DIA 653d).

Test: does adding non-crypto trend to a crypto-only trend book improve it (Sharpe, drawdown,
consistency)? And is the non-crypto trend genuinely diversifying (low corr to crypto trend)?

Honest caveat: the non-crypto perps are young (overlap ~190d, limited by silver) → short horizons
only (10/20/40/60), small sample; the DIVERSIFICATION STRUCTURE is the finding, returns indicative.
Binance fapi daily. Pure numpy.
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np

_FAPI = "https://fapi.binance.com/fapi/v1/klines"
CRYPTO = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "LINK"]
NONCRYPTO = ["XAU", "XAG", "DIA"]          # deepest non-crypto perps (>=190d)
HORIZONS = (10, 20, 40, 60)


def _closes(sym, limit=700):
    try:
        u = f"{_FAPI}?symbol={sym}USDT&interval=1d&limit={limit}"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cc"}), timeout=15).read())
        return {int(k[0]) // 86400000: float(k[4]) for k in r} if isinstance(r, list) else {}
    except Exception:
        return {}


def _sr(x): x = np.asarray(x); return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0
def _maxdd(pnl):
    c = np.cumsum(pnl); return float((np.maximum.accumulate(c) - c).max())


def _trend_pnl(close):
    """Multi-horizon TSMOM book over a T×K close panel: consensus sign × inverse-vol, unit gross."""
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    T, K = close.shape
    pnl = np.zeros(T); prev = np.zeros(K)
    start = max(HORIZONS) + 1
    for i in range(start, T - 1):
        vol = ret[i - 30:i].std(0)
        sig = np.mean([np.sign(np.nan_to_num(close[i] / close[i - h] - 1.0)) for h in HORIZONS], axis=0)
        iv = np.where(vol > 0, 1.0 / vol, 0.0)
        w = sig * iv; g = np.abs(w).sum(); w = w / g if g > 0 else w
        pnl[i + 1] = (w * ret[i + 1]).sum() - 0.0005 * np.abs(w - prev).sum()
        prev = w
    return pnl


def run() -> dict:
    series = {s: _closes(s) for s in CRYPTO + NONCRYPTO}
    series = {s: d for s, d in series.items() if len(d) > 70}
    days = sorted(set.intersection(*[set(v) for v in series.values()]))
    if len(days) < 80:
        return {"status": "insufficient_overlap", "days": len(days)}
    names = list(series)
    px = np.array([[series[n][d] for n in names] for d in days])
    ci = [i for i, n in enumerate(names) if n in CRYPTO]

    crypto_pnl = _trend_pnl(px[:, ci])
    all_pnl = _trend_pnl(px)
    warm = max(HORIZONS) + 1
    cp, ap = crypto_pnl[warm:], all_pnl[warm:]
    # diversification: correlation of the non-crypto contribution vs crypto book
    nci = [i for i in range(len(names)) if names[i] in NONCRYPTO]
    noncrypto_pnl = _trend_pnl(px[:, nci])[warm:]
    corr = float(np.corrcoef(cp, noncrypto_pnl)[0, 1]) if cp.std() > 0 and noncrypto_pnl.std() > 0 else None

    return {"overlap_days": len(days), "assets": names,
            "crypto_only_trend": {"sharpe": round(_sr(cp), 2), "maxdd_pct": round(_maxdd(cp) * 100, 1)},
            "cross_asset_trend": {"sharpe": round(_sr(ap), 2), "maxdd_pct": round(_maxdd(ap) * 100, 1)},
            "noncrypto_trend_sharpe": round(_sr(noncrypto_pnl), 2),
            "corr_crypto_vs_noncrypto_trend": round(corr, 3) if corr is not None else None,
            "diversification_helped": _sr(ap) > _sr(cp) or _maxdd(ap) < _maxdd(cp)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
