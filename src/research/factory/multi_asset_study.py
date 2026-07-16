"""
Multi-Asset Breadth Study (Seth 2026-07-15, Jazz's direction — deeper multi-asset/strategy model).
====================================================================================================

Our rotation study found the binding constraint: crypto majors nearly all move with BTC, so
effective breadth is ~4.7 of 24 — you can't diversify across assets that co-move. The thesis to
test: genuine breadth comes from OTHER ASSET CLASSES. Binance lists tokenized-RWA perps (equities:
MSTR/NVDA/TSLA/...; commodities: gold XAU / silver XAG / crude CL), so we can measure — on one
venue, real data — whether adding those classes actually relieves the breadth constraint.

Questions:
  A. Correlation to BTC by class — are equities/commodities genuinely less BTC-correlated than alts?
  B. Effective independent breadth: crypto-only vs crypto+equity+commodity.
  C. Do per-class market-neutral sleeves diversify each other (cross-class sleeve correlation)?

Honest caveat: tokenized-RWA perps are young (mostly 2026) → the panel is short; treat magnitudes
as indicative, the CORRELATION STRUCTURE as the finding. Binance fapi daily. Pure numpy.
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np

_FAPI = "https://fapi.binance.com/fapi/v1/klines"

CLASSES = {
    "crypto":     ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC"],
    "equity":     ["MSTR", "COIN", "NVDA", "TSLA", "HOOD", "PLTR", "AAPL", "META", "AMZN", "GOOGL"],
    "commodity":  ["XAU", "XAG", "CL"],
    # 热点行业 / sector-thematic ETF perps (24/7 on-chain) — the industry-rotation layer we lacked
    "sector_etf": ["XLE", "XBI", "URNM", "EWY", "EWZ", "EWJ", "SPY", "QQQ", "IWM", "DIA"],
}


def _daily(sym: str, limit: int = 1500) -> dict:
    try:
        u = f"{_FAPI}?symbol={sym}USDT&interval=1d&limit={limit}"
        rows = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cc"}), timeout=20).read())
        return {int(k[0]) // 86400000: float(k[4]) for k in rows} if isinstance(rows, list) else {}
    except Exception:
        return {}


def _eff_n(C):
    ev = np.linalg.eigvalsh(C); ev = ev[ev > 1e-10]; p = ev / ev.sum()
    return float(np.exp(-(p * np.log(p)).sum()))


def _xs_sleeve(R):
    """Simple cross-sectional momentum sleeve pnl within a block of assets (demeaned 30d mom)."""
    T, K = R.shape
    if K < 2:
        return np.zeros(T)
    mom = np.full((T, K), np.nan)
    for i in range(30, T):
        mom[i] = np.prod(1 + R[i - 30:i], axis=0) - 1
    pnl = np.zeros(T)
    for i in range(31, T - 1):
        w = mom[i] - np.nanmean(mom[i]); g = np.abs(w).sum()
        if g > 0:
            pnl[i + 1] = np.nansum((w / g) * R[i + 1])
    return pnl


def run() -> dict:
    series, klass = {}, {}
    for cl, syms in CLASSES.items():
        for s in syms:
            d = _daily(s)
            if len(d) > 60:
                series[s] = d; klass[s] = cl
    days = sorted(set.intersection(*[set(v) for v in series.values()])) if series else []
    if len(days) < 40:
        return {"status": "insufficient_overlap", "overlap_days": len(days), "assets": len(series)}
    names = list(series)
    px = np.array([[series[n][d] for n in names] for d in days])       # T×K aligned closes
    ret = np.zeros_like(px); ret[1:] = np.nan_to_num((px[1:] - px[:-1]) / px[:-1])
    ret = ret[1:]
    cls = np.array([klass[n] for n in names])

    btc_i = names.index("BTC")
    corr_btc = {}
    for cl in CLASSES:
        idx = [i for i in range(len(names)) if cls[i] == cl]
        cs = [float(np.corrcoef(ret[:, i], ret[:, btc_i])[0, 1]) for i in idx if i != btc_i]
        corr_btc[cl] = round(float(np.mean(cs)), 3) if cs else None

    def eff(sel):
        idx = [i for i in range(len(names)) if cls[i] in sel]
        if len(idx) < 2:
            return None
        C = np.nan_to_num(np.corrcoef(ret[:, idx].T))
        return round(_eff_n(C), 2)

    # per-class sleeves + cross-class sleeve correlation
    sleeves = {}
    for cl in CLASSES:
        idx = [i for i in range(len(names)) if cls[i] == cl]
        if len(idx) >= 3:
            sleeves[cl] = _xs_sleeve(ret[:, idx])
    sl_corr = {}
    keys = list(sleeves)
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            x, y = sleeves[keys[a]], sleeves[keys[b]]
            if x.std() > 0 and y.std() > 0:
                sl_corr[f"{keys[a]}×{keys[b]}"] = round(float(np.corrcoef(x, y)[0, 1]), 3)

    # ── payoff: combine the orthogonal per-class sleeves (inverse-variance) ──
    def _sr(x): return round(float(x.mean() / x.std() * np.sqrt(365)), 2) if x.std() > 0 else 0.0
    sleeve_sr = {cl: _sr(s) for cl, s in sleeves.items()}
    combined = None
    if len(sleeves) >= 2:
        M = np.array([sleeves[k] for k in keys]).T
        v = M.var(0); v[v == 0] = 1e18
        w = (1.0 / v) / (1.0 / v).sum()
        port = M @ w
        C = np.nan_to_num(np.corrcoef(M.T))
        combined = {"sleeves": keys, "per_sleeve_sharpe": sleeve_sr,
                    "combined_sharpe": _sr(port), "best_single": max(sleeve_sr.values()),
                    "enb": round(_eff_n(C), 2)}

    return {"overlap_days": len(days), "n_assets": len(names),
            "assets_by_class": {cl: [n for n in names if klass[n] == cl] for cl in CLASSES},
            "avg_corr_to_BTC_by_class": corr_btc,
            "effective_breadth": {"crypto_only": eff(["crypto"]),
                                  "crypto+equity": eff(["crypto", "equity"]),
                                  "crypto+equity+commodity": eff(["crypto", "equity", "commodity"]),
                                  "+sector_etf (all)": eff(["crypto", "equity", "commodity", "sector_etf"])},
            "cross_class_sleeve_corr": sl_corr,
            "multi_asset_combined_book": combined}


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
